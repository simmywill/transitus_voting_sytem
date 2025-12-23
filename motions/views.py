import logging
from typing import Dict, Optional

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    JsonResponse,
)
from django.core.cache import cache
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone as tz
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from voters import bbs_views
from voters.models import VotingSession

from .forms import MotionForm
from .models import Motion, MotionVote
from .presence import PresenceTracker
from .realtime import broadcast_to_admins, broadcast_to_voters, notify_voter
from .services import (
    close_motion as svc_close_motion,
    get_live_counts,
    open_motion as svc_open_motion,
    record_vote,
    recompute_counts,
    reset_motion_votes,
)
from .utils import get_event_by_uuid, get_voter_identity

logger = logging.getLogger(__name__)


PREVIEW_CACHE_TIMEOUT = 3600


def _preview_cache_key(event_id: int) -> str:
    return f"motions_preview_{event_id}"


def _motion_payload(motion: Motion) -> Dict:
    return {
        "id": motion.id,
        "title": motion.title,
        "body": motion.body,
        "status": motion.status,
        "allow_vote_change": motion.allow_vote_change,
        "reveal_results": motion.reveal_results,
        "auto_close_seconds": motion.auto_close_seconds,
        "opened_at": motion.opened_at.isoformat() if motion.opened_at else None,
        "closed_at": motion.closed_at.isoformat() if motion.closed_at else None,
    }


def _ensure_staff(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")


def _set_preview(event_id: int, payload: Dict):
    cache.set(_preview_cache_key(event_id), payload, timeout=PREVIEW_CACHE_TIMEOUT)


def _clear_preview(event_id: int):
    cache.delete(_preview_cache_key(event_id))


def _get_preview(event_id: int) -> Optional[Dict]:
    cached = cache.get(_preview_cache_key(event_id))
    if not cached:
        return None
    return cached.copy()


def _preview_payload_for_session(session: VotingSession) -> Optional[Dict]:
    """
    Retrieve the cached preview payload for a session, ensuring it still
    references a valid motion.
    """
    preview = _get_preview(session.pk)
    if not preview or "id" not in preview:
        return None
    try:
        motion = Motion.objects.get(pk=preview["id"], event=session)
    except Motion.DoesNotExist:
        _clear_preview(session.pk)
        return None
    payload = _motion_payload(motion)
    payload["preview"] = motion.status == Motion.STATUS_DRAFT
    if motion.status == Motion.STATUS_CLOSED and motion.reveal_results:
        payload["counts"] = recompute_counts(motion)
    _set_preview(session.pk, payload)
    return payload


@require_GET
def gated_entry(request, session_uuid):
    """
    Landing page shown after QR/URL. Preserves the existing identity created
    by the CIS/BBS handoff (ANON_ID/ANON_SESSION_UUID) without adding new auth.
    """
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return HttpResponseForbidden("Session is not active.")
    handoff = request.GET.get("handoff")
    if handoff:
        status, data = bbs_views._cis_call(
            request,
            "/api/redeem",
            {"redirect_code": handoff, "session_uuid": str(session_uuid)},
        )
        if status != 200 or not data.get("ok"):
            return HttpResponseForbidden(
                data.get("message")
                or "This link is no longer valid. Please re-verify to continue."
            )
        request.session["ANON_ID"] = data["anon_id"]
        request.session["ANON_SESSION_UUID"] = str(session_uuid)
        clean_url = reverse("motions:gated_entry", args=[session_uuid])
        return redirect(clean_url)

    # Clear mismatched anon session to avoid cross-session leakage
    anon_session = request.session.get("ANON_SESSION_UUID")
    if anon_session and anon_session != str(session_uuid):
        request.session.pop("ANON_SESSION_UUID", None)
        request.session.pop("ANON_ID", None)

    identity = get_voter_identity(request, session_uuid=session_uuid, create=True)

    context = {
        "session": session,
        "motion_url": reverse("motions:voter_portal", args=[session_uuid]),
        "election_url": reverse("cis_verify_form", args=[session_uuid]),
        "verify_url": reverse("cis_verify_form", args=[session_uuid]),
    }
    return render(request, "motions/gated_entry.html", context)


@require_GET
def voter_portal(request, session_uuid):
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return HttpResponseForbidden("Session is not active.")
    identity = get_voter_identity(request, session_uuid=session_uuid, create=True)
    if not identity:
        return redirect(reverse("motions:gated_entry", args=[session_uuid]))

    open_motion = (
        Motion.objects.filter(event=session, status=Motion.STATUS_OPEN)
        .order_by("display_order", "id")
        .first()
    )
    latest_closed = (
        Motion.objects.filter(event=session, status=Motion.STATUS_CLOSED)
        .order_by("-closed_at", "-id")
        .first()
    )
    selection = None
    if open_motion:
        selection = (
            MotionVote.objects.filter(motion=open_motion, voter_id=identity)
            .values_list("choice", flat=True)
            .first()
        )
        _clear_preview(session.pk)
    preview_payload = None if open_motion else _preview_payload_for_session(session)
    last_counts = {}
    latest_closed_payload = None
    if latest_closed and latest_closed.reveal_results:
        last_counts = recompute_counts(latest_closed)
        latest_closed_payload = _motion_payload(latest_closed)
        latest_closed_payload["counts"] = last_counts
        if identity:
            latest_selection = (
                MotionVote.objects.filter(motion=latest_closed, voter_id=identity)
                .values_list("choice", flat=True)
                .first()
            )
            if latest_selection:
                latest_closed_payload["selection"] = latest_selection

    open_payload = _motion_payload(open_motion) if open_motion else None
    if open_payload and selection:
        open_payload["selection"] = selection

    ws_path = f"/ws/motions/{session_uuid}/voter/"
    context = {
        "session": session,
        "open_motion": open_motion,
        "open_payload": open_payload,
        "latest_closed": latest_closed,
        "latest_closed_payload": latest_closed_payload,
        "selection": selection,
        "preview_payload": preview_payload,
        "last_counts": last_counts,
        "websocket_path": ws_path,
        "api_vote_url": reverse(
            "motions:api_cast_vote",
            args=[session_uuid, open_motion.id if open_motion else 0],
        )
        if open_motion
        else None,
        "api_current_url": reverse("motions:api_current_motion", args=[session_uuid]),
        "api_presence_url": reverse("motions:api_presence", args=[session_uuid]),
        "vote_base": f"/motions/session/{session_uuid}/motions/",
    }
    return render(request, "motions/voter_portal.html", context)


@login_required
def manage_motions(request, session_uuid):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return HttpResponseForbidden("Session is not active.")
    motions = session.motions.all()

    if request.method == "POST":
        form = MotionForm(request.POST)
        if form.is_valid():
            motion = form.save(commit=False)
            motion.event = session
            if not motion.display_order:
                existing_max = (
                    session.motions.order_by("-display_order").values_list("display_order", flat=True).first() or 0
                )
                motion.display_order = existing_max + 1
            motion.save()
            messages.success(request, "Motion created.")
            return redirect(reverse("motions:manage_motions", args=[session_uuid]))
    else:
        form = MotionForm()

    current_open = motions.filter(status=Motion.STATUS_OPEN).first()
    return render(
        request,
        "motions/manage_motions.html",
        {
            "session": session,
            "motions": motions.order_by("display_order", "id"),
            "form": form,
            "current_open": current_open,
        },
    )


@login_required
@require_POST
def motion_edit(request, session_uuid, motion_id):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return HttpResponseForbidden("Session is not active.")
    motion = get_object_or_404(Motion, pk=motion_id, event=session)
    form = MotionForm(request.POST, instance=motion)
    if form.is_valid():
        form.save()
        messages.success(request, "Motion updated.")
    else:
        messages.error(request, "Please correct the errors below.")
    return redirect(reverse("motions:manage_motions", args=[session_uuid]))


@login_required
@require_POST
def motion_create(request, session_uuid):
    return manage_motions(request, session_uuid)


@login_required
@require_POST
def api_reorder_motions(request, session_uuid):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")
    session = get_event_by_uuid(session_uuid)
    direction = request.POST.get("direction")
    motion_id = request.POST.get("motion_id")
    try:
        motion = Motion.objects.get(pk=motion_id, event=session)
    except Motion.DoesNotExist:
        return HttpResponseBadRequest("Invalid motion")

    if direction not in ("up", "down"):
        return HttpResponseBadRequest("Invalid direction")

    if direction == "up":
        neighbor = (
            Motion.objects.filter(event=session, display_order__lt=motion.display_order)
            .order_by("-display_order")
            .first()
        )
    else:
        neighbor = (
            Motion.objects.filter(event=session, display_order__gt=motion.display_order)
            .order_by("display_order")
            .first()
        )
    if neighbor:
        motion.display_order, neighbor.display_order = neighbor.display_order, motion.display_order
        motion.save(update_fields=["display_order"])
        neighbor.save(update_fields=["display_order"])
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    return redirect(reverse("motions:manage_motions", args=[session_uuid]))


@login_required
def presenter_console(request, session_uuid):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")
    session = get_event_by_uuid(session_uuid)
    motions = session.motions.annotate(votes_count=Count("votes")).order_by("display_order", "id")
    open_motion = motions.filter(status=Motion.STATUS_OPEN).first()
    ws_path = f"/ws/motions/{session_uuid}/admin/"
    counts = get_live_counts(open_motion.id) if open_motion else {}
    total_votes = sum(counts.values()) if counts else 0
    open_payload = _motion_payload(open_motion) if open_motion else None
    context = {
        "session": session,
        "motions": motions,
        "open_motion": open_motion,
        "websocket_path": ws_path,
        "presence_count": PresenceTracker().count(session.pk),
        "counts": counts,
        "total_votes": total_votes,
        "open_payload": open_payload,
    }
    return render(request, "motions/presenter_console.html", context)


@login_required
@require_POST
@csrf_protect
def open_motion(request, session_uuid, motion_id):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return HttpResponseForbidden("Session is not active.")
    motion = get_object_or_404(Motion, pk=motion_id, event=session)
    motion = svc_open_motion(motion)
    payload = _motion_payload(motion)
    _clear_preview(session.pk)
    broadcast_to_voters(session.pk, "motion_opened", payload)
    broadcast_to_admins(session.pk, "motion_opened", payload)
    return redirect(reverse("motions:presenter_console", args=[session_uuid]))


@login_required
@require_POST
@csrf_protect
def preview_motion(request, session_uuid, motion_id):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return HttpResponseForbidden("Session is not active.")
    motion = get_object_or_404(Motion, pk=motion_id, event=session)
    open_motion = (
        Motion.objects.filter(event=session, status=Motion.STATUS_OPEN)
        .order_by("display_order", "id")
        .first()
    )
    if open_motion and open_motion.id != motion.id:
        return JsonResponse({"ok": False, "error": "motion_open"}, status=400)

    payload = _motion_payload(motion)
    payload["preview"] = motion.status == Motion.STATUS_DRAFT
    if motion.status == Motion.STATUS_CLOSED and motion.reveal_results:
        payload["counts"] = recompute_counts(motion)
    _set_preview(session.pk, payload)
    broadcast_to_voters(session.pk, "motion_previewed", payload)
    return JsonResponse({"ok": True, "preview": payload})


@login_required
@require_POST
@csrf_protect
def close_motion(request, session_uuid, motion_id):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return HttpResponseForbidden("Session is not active.")
    motion = get_object_or_404(Motion, pk=motion_id, event=session)
    counts = svc_close_motion(motion)
    payload = _motion_payload(motion)
    payload["counts"] = counts
    broadcast_to_voters(session.pk, "motion_closed", payload)
    broadcast_to_admins(session.pk, "motion_closed", payload)
    if motion.reveal_results:
        broadcast_to_voters(session.pk, "results_revealed", {"motion_id": motion.id, "counts": counts})
    return redirect(reverse("motions:presenter_console", args=[session_uuid]))


@login_required
@require_POST
@csrf_protect
def reveal_motion_results(request, session_uuid, motion_id):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return HttpResponseForbidden("Session is not active.")
    motion = get_object_or_404(Motion, pk=motion_id, event=session)
    motion.reveal_results = True
    motion.save(update_fields=["reveal_results"])
    counts = recompute_counts(motion)
    broadcast_to_voters(session.pk, "results_revealed", {"motion_id": motion.id, "counts": counts})
    broadcast_to_admins(session.pk, "results_revealed", {"motion_id": motion.id, "counts": counts})
    return redirect(reverse("motions:presenter_console", args=[session_uuid]))


@login_required
@require_POST
@csrf_protect
def hide_motion_results(request, session_uuid, motion_id):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return HttpResponseForbidden("Session is not active.")
    motion = get_object_or_404(Motion, pk=motion_id, event=session)
    motion.reveal_results = False
    motion.save(update_fields=["reveal_results"])
    broadcast_to_voters(session.pk, "results_hidden", {"motion_id": motion.id})
    return redirect(reverse("motions:presenter_console", args=[session_uuid]))


@login_required
@require_POST
@csrf_protect
def reset_motion_votes_view(request, session_uuid, motion_id):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return HttpResponseForbidden("Session is not active.")
    motion = get_object_or_404(Motion, pk=motion_id, event=session)
    reset_motion_votes(motion)
    payload = {"motion_id": motion.id, "counts": {"yes": 0, "no": 0, "abstain": 0}}
    broadcast_to_admins(session.pk, "admin_vote_update", payload)
    broadcast_to_voters(session.pk, "admin_vote_update", payload)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, **payload})
    return redirect(reverse("motions:presenter_console", args=[session_uuid]))


@require_POST
@csrf_protect
def api_cast_vote(request, session_uuid, motion_id):
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return JsonResponse({"ok": False, "error": "inactive_session"}, status=403)
    motion = get_object_or_404(Motion, pk=motion_id, event=session)
    identity = get_voter_identity(request, session_uuid=session_uuid, create=True)
    if not identity:
        return JsonResponse({"ok": False, "error": "unauthorized"}, status=403)
    choice = (request.POST.get("choice") or "").lower()
    ok, data = record_vote(motion, identity, choice)
    if not ok:
        status = 400 if data.get("error") in ("invalid_choice",) else 403
        return JsonResponse({"ok": False, **data}, status=status)

    counts = get_live_counts(motion.id)
    notify_voter(session.pk, identity, "vote_ack", {"motion_id": motion.id, **data})
    broadcast_to_admins(session.pk, "admin_vote_update", {"motion_id": motion.id, "counts": counts})
    return JsonResponse({"ok": True, **data})


@require_GET
def api_current_motion(request, session_uuid):
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return JsonResponse({"ok": False, "error": "inactive_session"}, status=403)
    identity = get_voter_identity(request, session_uuid=session_uuid, create=True)
    open_motion = (
        Motion.objects.filter(event=session, status=Motion.STATUS_OPEN)
        .order_by("display_order", "id")
        .first()
    )
    closed_motion = (
        Motion.objects.filter(event=session, status=Motion.STATUS_CLOSED)
        .order_by("-closed_at", "-id")
        .first()
    )
    payload: Dict[str, Optional[Dict]] = {"open": None, "latest_closed": None, "preview": None}
    if open_motion:
        payload["open"] = _motion_payload(open_motion)
        if identity:
            vote = (
                MotionVote.objects.filter(motion=open_motion, voter_id=identity)
                .values_list("choice", flat=True)
                .first()
            )
            payload["open"]["selection"] = vote
        _clear_preview(session.pk)
    else:
        payload["preview"] = _preview_payload_for_session(session)
    if closed_motion and closed_motion.reveal_results:
        payload["latest_closed"] = _motion_payload(closed_motion)
        payload["latest_closed"]["counts"] = recompute_counts(closed_motion)
        if identity:
            last_vote = (
                MotionVote.objects.filter(motion=closed_motion, voter_id=identity)
                .values_list("choice", flat=True)
                .first()
            )
            if last_vote:
                payload["latest_closed"]["selection"] = last_vote
    return JsonResponse({"ok": True, **payload})


@require_GET
def api_presence(request, session_uuid):
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return JsonResponse({"ok": False, "error": "inactive_session"}, status=403)
    count = PresenceTracker().count(session.pk)
    return JsonResponse({"ok": True, "count": count})


@login_required
@require_GET
def api_tallies(request, session_uuid):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return JsonResponse({"ok": False, "error": "inactive_session"}, status=403)
    motion_id = request.GET.get("motion_id")
    motion = None
    if motion_id:
        motion = get_object_or_404(Motion, pk=motion_id, event=session)
    else:
        motion = (
            Motion.objects.filter(event=session, status=Motion.STATUS_OPEN)
            .order_by("display_order", "id")
            .first()
        )
    if not motion:
        return JsonResponse({"ok": True, "counts": {}, "motion_id": None})
    counts = recompute_counts(motion) if motion.is_closed else get_live_counts(motion.id)
    total = sum(counts.values()) if counts else 0
    return JsonResponse({"ok": True, "counts": counts, "motion_id": motion.id, "total": total})


@login_required
@require_POST
@csrf_protect
def api_set_timer(request, session_uuid, motion_id):
    if not request.user.is_staff:
        return HttpResponseForbidden("Staff login required")
    session = get_event_by_uuid(session_uuid)
    if not session.is_active:
        return JsonResponse({"ok": False, "error": "inactive_session"}, status=403)
    motion = get_object_or_404(Motion, pk=motion_id, event=session)
    if motion.status != Motion.STATUS_OPEN:
        return JsonResponse({"ok": False, "error": "not_open"}, status=400)

    now = tz.now()
    seconds_raw = request.POST.get("seconds")
    extend_raw = request.POST.get("extend")

    def _parse_int(value):
        try:
            return int(value)
        except Exception:
            return None

    extend_val = _parse_int(extend_raw)
    seconds_val = _parse_int(seconds_raw)
    if extend_val is None and seconds_val is None:
        return JsonResponse({"ok": False, "error": "missing_seconds"}, status=400)

    elapsed = 0
    if motion.opened_at and motion.auto_close_seconds:
        elapsed = max(0, int((now - motion.opened_at).total_seconds()))
    remaining = max(0, (motion.auto_close_seconds or 0) - elapsed)

    if extend_val is not None:
        target_seconds = remaining + max(0, extend_val)
    else:
        target_seconds = max(0, seconds_val or 0)

    Motion.objects.filter(pk=motion.pk).update(opened_at=now, auto_close_seconds=target_seconds)
    motion.refresh_from_db(fields=["opened_at", "auto_close_seconds"])
    payload = _motion_payload(motion)
    broadcast_to_admins(session.pk, "timer_updated", payload)
    broadcast_to_voters(session.pk, "timer_updated", payload)
    return JsonResponse({"ok": True, "motion": payload})
