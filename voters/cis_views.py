from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from django.utils import timezone as tz
from django.conf import settings
from django.db import transaction
import secrets, base64, hmac, hashlib, json, os, logging
from django.urls import reverse

from .models import VotingSession, Voter, AnonSession, RedirectCode, log_event

logger = logging.getLogger(__name__)


def _host_ok(request, expect='verify'):
    """
    Enforce host separation only when configured. In single-host deployments
    (e.g., Render), allow requests on the current host.
    """
    if not getattr(settings, 'CIS_ENFORCE_HOST', False):
        return True
    host = request.get_host() or ''
    fragment = getattr(settings, 'CIS_EXPECT_HOST_FRAGMENT', expect) or expect
    return (fragment in host) or settings.DEBUG


@require_GET
def verify_form(request, session_uuid):
    if not _host_ok(request, 'verify'):
        return HttpResponseForbidden("Wrong host")
    # Support both future session_uuid field and legacy unique_url substring
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f"{session_uuid}")
    return render(request, 'voters/voter_verification.html', {'session': session})


@require_POST
@csrf_protect
@transaction.atomic
def api_verify(request):
    if not _host_ok(request, 'verify'):
        return HttpResponseForbidden("Wrong host")
    session_uuid = request.POST.get('session_id') or request.POST.get('session_uuid')
    fname = (request.POST.get('Fname') or request.POST.get('fname') or request.POST.get('first_name') or '').strip()
    lname = (request.POST.get('Lname') or request.POST.get('lname') or request.POST.get('last_name') or '').strip()
    if not session_uuid or not fname or not lname:
        return HttpResponseBadRequest("Missing fields")
    # Support both the new UUID field and legacy unique_url contains
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f"{session_uuid}")

    voter = Voter.objects.filter(session=session, Fname__iexact=fname, Lname__iexact=lname).first()
    if not voter:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)

    # Enforce one ballot per voter: if already finished, do not issue a new handoff
    if getattr(voter, 'has_finished', False):
        return JsonResponse({'ok': False, 'error': 'already_voted'}, status=403)

    # Issue AnonSession
    anon_id = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip('=')
    anon = AnonSession.objects.create(
        anon_id=anon_id, session=session, voter=voter,
        expires_at=tz.now() + tz.timedelta(hours=12)
    )

    # One-use redirect code valid for 10 minutes
    code = base64.urlsafe_b64encode(secrets.token_bytes(16)).decode().rstrip('=')
    RedirectCode.objects.create(
        code=code, anon=anon, session=session,
        expires_at=tz.now() + tz.timedelta(minutes=10)
    )

    # Mark verified for ops dashboard
    if not voter.is_verified:
        voter.is_verified = True
        voter.save(update_fields=['is_verified'])

    log_event(session, "VERIFY_OK", {"voter_id": voter.voter_id, "anon": anon_id})

    # Build ballot URL. In single-host deployments (Render), keep same host.
    sess_uuid = getattr(session, 'session_uuid', session_uuid)
    ballot_path = reverse('bbs_ballot_entry', args=[sess_uuid]) + f"?handoff={code}"
    if not getattr(settings, 'CIS_ENFORCE_HOST', False):
        ballot_url = request.build_absolute_uri(ballot_path)
    else:
        # Multi-host mode: allow override via env, else fallback to legacy host
        base = getattr(settings, 'BBS_BASE_URL', None) or os.environ.get('BBS_BASE_URL') or 'https://vote.agm.local'
        ballot_url = f"{base.rstrip('/')}{ballot_path}"
    return JsonResponse({"ok": True, "ballot_url": ballot_url})


@require_POST
@csrf_exempt  # HMAC-authenticated server-to-server endpoint; CSRF not applicable
@transaction.atomic
def api_redeem(request):
    # BBS -> CIS, HMAC protected
    sig = request.headers.get("X-CIS-Signature", "")
    body = request.body or b""
    mac_ok = hmac.compare_digest(
        hmac.new(settings.CIS_BBS_SHARED_SECRET.encode(), body, hashlib.sha256).hexdigest(),
        sig
    )
    if not mac_ok:
        return HttpResponseForbidden("Bad signature")

    data = json.loads(body.decode() or '{}')
    code = data.get("redirect_code") or data.get("handoff")
    session_uuid = data.get("session_id") or data.get("session_uuid")
    if not code or not session_uuid:
        return HttpResponseBadRequest("Missing fields")

    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f"{session_uuid}")

    rc = RedirectCode.objects.select_for_update().filter(code=code, session=session).first()
    now = tz.now()
    failure = None
    if not rc:
        failure = "missing"
    elif rc.redeemed_at:
        failure = "already_redeemed"
    elif rc.expires_at and rc.expires_at < now:
        failure = "expired"

    if failure:
        logger.warning(
            "CIS redeem rejected (%s) for session=%s code=%s", failure, session_uuid, code
        )
        return JsonResponse({"ok": False, "error": "invalid_or_used", "reason": failure}, status=400)

    rc.redeemed_at = now
    rc.save(update_fields=['redeemed_at'])

    anon = rc.anon
    if not anon.activated_at:
        anon.activated_at = tz.now()
        anon.save(update_fields=['activated_at'])

    log_event(session, "REDEEM_OK", {"anon": anon.anon_id})
    return JsonResponse({"ok": True, "anon_id": anon.anon_id})


@transaction.atomic
def _mark_spent(session_uuid, anon_id):
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except VotingSession.DoesNotExist:
        session = VotingSession.objects.filter(unique_url__contains=f"{session_uuid}").first()
        if not session:
            return 404, {"ok": False, "error": "session_not_found"}

    anon = AnonSession.objects.select_for_update().filter(anon_id=anon_id, session=session).first()
    now = tz.now()
    if not anon:
        return 400, {"ok": False, "error": "invalid_or_spent"}
    if anon.spent_at:
        return 400, {"ok": False, "error": "already_spent"}
    if anon.expires_at and anon.expires_at < now:
        return 400, {"ok": False, "error": "expired"}

    voter = None
    if anon.voter_id:
        voter = Voter.objects.select_for_update().filter(pk=anon.voter_id).first()
        if voter and voter.has_finished:
            return 400, {"ok": False, "error": "already_voted"}

    anon.spent_at = now
    anon.save(update_fields=['spent_at'])

    if voter and not voter.has_finished:
        voter.has_finished = True
        voter.save(update_fields=['has_finished'])

        AnonSession.objects.filter(
            voter=voter,
            spent_at__isnull=True,
        ).exclude(pk=anon.pk).update(expires_at=now)

    log_event(session, "CAST_OK", {"anon": anon_id})
    return 200, {"ok": True}


@require_POST
@csrf_exempt  # HMAC-authenticated server-to-server endpoint; CSRF not applicable
@transaction.atomic
def api_mark_spent(request):
    # BBS -> CIS, HMAC protected
    sig = request.headers.get("X-CIS-Signature", "")
    body = request.body or b""
    mac_ok = hmac.compare_digest(
        hmac.new(settings.CIS_BBS_SHARED_SECRET.encode(), body, hashlib.sha256).hexdigest(),
        sig
    )
    if not mac_ok:
        return HttpResponseForbidden("Bad signature")

    data = json.loads(body.decode() or '{}')
    anon_id = data.get("anon_id")
    session_uuid = data.get("session_id") or data.get("session_uuid")
    if not anon_id or not session_uuid:
        return HttpResponseBadRequest("Missing fields")

    status, payload = _mark_spent(session_uuid, anon_id)
    return JsonResponse(payload, status=status)


@require_GET
def voter_status(request, session_uuid):
    # For your admin dashboard polling
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f"{session_uuid}")
    total = Voter.objects.filter(session=session).count()
    verified = Voter.objects.filter(session=session, is_verified=True).count()
    finished = Voter.objects.filter(session=session, has_finished=True).count()
    return JsonResponse({"total": total, "verified": verified, "finished": finished})
