from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden, HttpResponseBadRequest
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_protect
from django.utils import timezone as tz
from django.conf import settings
from django.db import transaction
import secrets, base64, hmac, hashlib, json

from .models import VotingSession, Voter, AnonSession, RedirectCode, log_event


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

    ballot_url = f"https://vote.agm.local/ballot/{getattr(session, 'session_uuid', session_uuid)}?handoff={code}"
    return JsonResponse({"ok": True, "ballot_url": ballot_url})


@require_POST
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
    if not rc or rc.redeemed_at or (rc.expires_at and rc.expires_at < tz.now()):
        return JsonResponse({"ok": False, "error": "invalid_or_used"}, status=400)

    rc.redeemed_at = tz.now()
    rc.save(update_fields=['redeemed_at'])

    anon = rc.anon
    if not anon.activated_at:
        anon.activated_at = tz.now()
        anon.save(update_fields=['activated_at'])

    log_event(session, "REDEEM_OK", {"anon": anon.anon_id})
    return JsonResponse({"ok": True, "anon_id": anon.anon_id})


@require_POST
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

    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f"{session_uuid}")

    from .models import AnonSession as _Anon
    anon = _Anon.objects.select_for_update().filter(anon_id=anon_id, session=session).first()
    if not anon or anon.spent_at:
        return JsonResponse({"ok": False, "error": "invalid_or_spent"}, status=400)

    anon.spent_at = tz.now()
    anon.save(update_fields=['spent_at'])

    # Flip ops flag by name if present
    if anon.voter and not anon.voter.has_finished:
        anon.voter.has_finished = True
        anon.voter.save(update_fields=['has_finished'])

    log_event(session, "CAST_OK", {"anon": anon_id})
    return JsonResponse({"ok": True})


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
