from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.views.decorators.csrf import csrf_protect
from django.db import transaction
from django.conf import settings
from django.utils import timezone as tz
from django.urls import reverse
import hmac, hashlib, json, os

try:
    import requests  # ensure available in requirements
except Exception:  # pragma: no cover
    requests = None

from .models import VotingSession, VotingSegmentHeader, Candidate, Ballot, ManualCheckCard, log_event


def _host_ok(request, expect='vote'):
    """Allow any host in single-host mode; enforce fragment in multi-host."""
    if not getattr(settings, 'CIS_ENFORCE_HOST', False):
        return True
    host = request.get_host() or ''
    return (expect in host) or getattr(settings, 'DEBUG', False)


def _cis_call(request, path, payload):
    if requests is None:
        return 500, {"ok": False, "error": "requests_missing"}
    if not getattr(settings, 'CIS_ENFORCE_HOST', False):
        base = (request.build_absolute_uri('/') or '').rstrip('/')
    else:
        base = getattr(settings, 'CIS_BASE_URL', None) or os.environ.get('CIS_BASE_URL') or 'https://verify.agm.local'
    url = f"{base}{path}"
    body = json.dumps(payload).encode()
    sig = hmac.new(settings.CIS_BBS_SHARED_SECRET.encode(), body, hashlib.sha256).hexdigest()
    r = requests.post(url, data=body, headers={
        "Content-Type": "application/json",
        "X-CIS-Signature": sig
    }, timeout=5)
    return r.status_code, r.json()


@require_GET
def ballot_entry(request, session_uuid):
    if not _host_ok(request, 'vote'):
        return HttpResponseForbidden("Wrong host")
    # Accept optional ?handoff=<code> for first entry and ?segment=<n> for navigation
    code = request.GET.get("handoff")
    seg_num = int(request.GET.get("segment", "1") or 1)
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f"{session_uuid}")

    if code:
        status, data = _cis_call(request, "/api/redeem", {"redirect_code": code, "session_uuid": str(session_uuid)})
        if status != 200 or not data.get("ok"):
            error = (data.get("error") if isinstance(data, dict) else "redeem_failed") or "redeem_failed"
            return HttpResponseForbidden({
                "invalid_or_used": "This link has already been used or expired. Please re-verify to obtain a new code.",
                "missing_fields": "Missing handoff details. Please try again from the verification page.",
            }.get(error, "Handoff validation failed. Please re-verify."))
        request.session['ANON_ID'] = data['anon_id']
        request.session['ANON_SESSION_UUID'] = str(session_uuid)

        # Strip single-use handoff token from the browser URL so refreshes do not re-redeem
        clean_url = reverse('bbs_ballot_entry', args=[session_uuid])
        if request.GET.get("segment"):
            clean_url = f"{clean_url}?segment={seg_num}"
        return redirect(clean_url)
    else:
        # Must already have anon session if navigating
        if request.session.get('ANON_SESSION_UUID') != str(session_uuid) or not request.session.get('ANON_ID'):
            return HttpResponseForbidden("Session expired. Please re-verify.")

    # Render the existing voting page template (one segment at a time)
    segments = list(VotingSegmentHeader.objects.filter(session=session).order_by('order', 'id'))
    if not segments:
        return HttpResponseBadRequest("No segments configured")
    total = len(segments)
    seg_num = max(1, min(total, seg_num))
    segment = segments[seg_num - 1]

    segment_ids = [seg.id for seg in segments]

    return render(request, 'voters/voting_page.html', {
        'session': session,
        'segment': segment,
        'current_segment': seg_num,
        'total_segments': total,
        'session_uuid': str(session_uuid),
        'segment_ids_json': json.dumps(segment_ids),
        # No voter_id provided in BBS
    })


@require_POST
@csrf_protect
@transaction.atomic
def api_cast(request):
    if not _host_ok(request, 'vote'):
        return HttpResponseForbidden("Wrong host")
    # Accept JSON { session_uuid, choices: [[segment_id, candidate_id], ...] }
    try:
        data = json.loads(request.body.decode())
    except Exception:
        return HttpResponseBadRequest("Bad JSON")

    session_uuid = data.get('session_uuid')
    choices = data.get('choices') or []
    if not session_uuid or not isinstance(choices, list):
        return HttpResponseBadRequest("Missing fields")

    anon_id = request.session.get('ANON_ID')
    anon_session_uuid = request.session.get('ANON_SESSION_UUID')
    if not anon_id or str(session_uuid) != str(anon_session_uuid):
        return HttpResponseForbidden("Session expired or mismatched")

    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except VotingSession.DoesNotExist:
        session = VotingSession.objects.filter(unique_url__contains=f"{session_uuid}").first()
        if not session:
            return JsonResponse({"error": "session_not_found"}, status=404)

    segments_by_id = {seg.id: seg for seg in VotingSegmentHeader.objects.filter(session=session)}
    if not segments_by_id:
        return JsonResponse({"error": "no_segments"}, status=400)

    created = 0
    manual_card = None
    now = tz.now()
    for pair in choices:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            return JsonResponse({"error": "invalid_choice_format"}, status=400)
        raw_seg_id, raw_cand_id = pair
        try:
            seg_id = int(raw_seg_id)
            cand_id = int(raw_cand_id)
        except (TypeError, ValueError):
            return JsonResponse({"error": "invalid_choice_format"}, status=400)

        segment = segments_by_id.get(seg_id)
        if not segment:
            return JsonResponse({"error": "invalid_segment", "segment_id": seg_id}, status=400)

        try:
            candidate = Candidate.objects.get(pk=cand_id, voting_session=session, segment_header_id=seg_id)
        except Candidate.DoesNotExist:
            return JsonResponse(
                {"error": "invalid_candidate", "segment_id": seg_id, "candidate_id": cand_id},
                status=400,
            )

        if manual_card is None:
            manual_card = ManualCheckCard.objects.create(session=session)
        Ballot.objects.create(session=session, segment=segment, candidate=candidate, bundle=manual_card)
        created += 1

    # Mark ANON spent in CIS (server-to-server)
    status, resp = _cis_call(request, "/api/mark-spent", {"anon_id": anon_id, "session_uuid": str(session_uuid)})
    if status != 200 or not resp.get("ok"):
        error_code = (resp or {}).get("error") if isinstance(resp, dict) else None
        if error_code == "already_voted":
            return JsonResponse({
                "ok": False,
                "error": "already_voted",
                "message": "You have already voted in this session.",
            }, status=403)
        if error_code in {"invalid_or_spent", "already_spent", "expired"}:
            return JsonResponse({
                "ok": False,
                "error": error_code,
                "message": "This ballot link is no longer valid. Please re-verify.",
            }, status=400)
        raise Exception("CIS mark-spent failed")

    # Clear anon from session so it can't be reused
    request.session.pop('ANON_ID', None)
    request.session.pop('ANON_SESSION_UUID', None)

    receipt = hashlib.sha256(f"{session_uuid}:{now.isoformat()}:{created}".encode()).hexdigest()[:12]
    log_event(session, "CAST_BATCH", {"count": created})

    return JsonResponse({"ok": True, "created": created, "receipt": receipt})


@require_GET
def results(request, session_uuid):
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f"{session_uuid}")
    from django.db.models import Count
    segments = list(VotingSegmentHeader.objects.filter(session=session).order_by('order', 'id'))
    # Precompute ballot counts per (segment, candidate)
    counts = (Ballot.objects.filter(session=session)
              .values('segment_id', 'candidate_id')
              .annotate(votes=Count('candidate_id')))
    count_map = {(row['segment_id'], row['candidate_id']): row['votes'] for row in counts}

    tally = []
    for seg in segments:
        cands = []
        for cand in Candidate.objects.filter(voting_session=session, segment_header=seg).select_related('segment_header'):
            votes = count_map.get((seg.id, cand.id), 0)
            cands.append({
                'id': cand.id,
                'name': cand.name,
                'votes': votes,
                'photo_url': cand.photo.url if cand.photo else '',
            })
        # Sort candidates by votes (desc), then name to keep ordering stable for equal votes
        cands.sort(key=lambda x: (-x['votes'], x['name']))
        winner = None
        if cands:
            winner_obj = cands[0]
            winner = {
                'id': winner_obj['id'],
                'name': winner_obj['name'],
                'votes': winner_obj['votes'],
                'photo_url': winner_obj['photo_url'],
            }
        tally.append({
            'segment_id': seg.id,
            'name': seg.name,
            'candidates': cands,
            'winner': winner,
        })
    # Restrict results to authenticated staff (admin-only view)
    if not request.user.is_authenticated or not getattr(request.user, 'is_staff', False):
        return HttpResponseForbidden("Results are restricted to administrators.")
    ctx = {'session': session, 'tally': tally, 'segments_json': json.dumps(tally)}
    return render(request, 'voters/results.html', ctx)


@require_GET
def thanks(request, session_uuid):
    """Neutral confirmation page after anonymous cast with optional receipt download.
    Uses segment/candidate metadata to help client render a PNG receipt locally.
    """
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f"{session_uuid}")

    # Provide lightweight metadata for client-side receipt rendering
    segments = []
    for seg in VotingSegmentHeader.objects.filter(session=session).order_by('order', 'id'):
        seg_entry = {
            'id': seg.id,
            'name': seg.name,
            'candidates': [
                {'id': c.id, 'name': c.name, 'photo_url': (c.photo.url if c.photo else '')}
                for c in Candidate.objects.filter(voting_session=session, segment_header=seg)
            ]
        }
        segments.append(seg_entry)

    ctx = {
        'session': session,
        'segments_json': json.dumps(segments),
        'session_uuid': str(session_uuid),
    }
    return render(request, 'voters/thanks.html', ctx)


@require_GET
def export_cvr(request, session_uuid):
    import csv
    from django.http import HttpResponse
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f"{session_uuid}")
    rows = (Ballot.objects.filter(session=session)
            .select_related('segment', 'candidate')
            .order_by('created_at'))
    resp = HttpResponse(content_type='text/csv')
    resp['Content-Disposition'] = f'attachment; filename="cvr_{session_uuid}.csv"'
    writer = csv.writer(resp)
    writer.writerow(["ballot_id", "segment", "candidate", "created_at_minute"])
    for b in rows:
        minute = b.created_at.strftime("%Y-%m-%d %H:%M")
        writer.writerow([str(b.ballot_id), b.segment.name, b.candidate.name, minute])
    return resp
