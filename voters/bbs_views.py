from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.http import require_http_methods, require_POST, require_GET
from django.views.decorators.csrf import csrf_protect
from django.db import transaction
from django.conf import settings
from django.utils import timezone as tz
import hmac, hashlib, json

try:
    import requests  # ensure available in requirements
except Exception:  # pragma: no cover
    requests = None

from .models import VotingSession, VotingSegmentHeader, Candidate, Ballot, log_event


def _host_ok(request, expect='vote'):
    host = request.get_host() or ''
    from django.conf import settings as _s
    return (expect in host) or getattr(_s, 'DEBUG', False)


def _cis_call(path, payload):
    if requests is None:
        return 500, {"ok": False, "error": "requests_missing"}
    url = f"https://verify.agm.local{path}"
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
        status, data = _cis_call("/api/redeem", {"redirect_code": code, "session_uuid": str(session_uuid)})
        if status != 200 or not data.get("ok"):
            return HttpResponseForbidden("Invalid or used handoff")
        request.session['ANON_ID'] = data['anon_id']
        request.session['ANON_SESSION_UUID'] = str(session_uuid)
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

    return render(request, 'voters/voting_page.html', {
        'session': session,
        'segment': segment,
        'current_segment': seg_num,
        'total_segments': total,
        'session_uuid': str(session_uuid),
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
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f"{session_uuid}")

    created = 0
    now = tz.now()
    for pair in choices:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        seg_id, cand_id = pair
        segment = get_object_or_404(VotingSegmentHeader, pk=seg_id, session=session)
        candidate = get_object_or_404(Candidate, pk=cand_id, voting_session=session, segment_header=segment)
        Ballot.objects.create(session=session, segment=segment, candidate=candidate)
        created += 1

    # Mark ANON spent in CIS (server-to-server)
    status, resp = _cis_call("/api/mark-spent", {"anon_id": anon_id, "session_uuid": str(session_uuid)})
    if status != 200 or not resp.get("ok"):
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
        winner = None
        if cands:
            winner_obj = max(cands, key=lambda x: x['votes'])
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
    ctx = {'session': session, 'tally': tally, 'segments_json': json.dumps(tally)}
    return render(request, 'voters/results.html', ctx)


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
