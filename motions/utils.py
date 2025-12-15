from django.http import Http404
from django.shortcuts import get_object_or_404


def get_event_by_uuid(session_uuid):
    """
    Fetch the VotingSession by canonical UUID, falling back to legacy unique_url substring.
    """
    from voters.models import VotingSession

    try:
        return VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        return get_object_or_404(VotingSession, unique_url__contains=str(session_uuid))


def get_voter_identity(request):
    """
    Adapter to reuse existing session identity without introducing new verification.
    Prefers the anonymous handoff ID issued by CIS/BBS, falls back to any stored voter_id
    or the authenticated user id. Returns a simple string token or None.
    """
    anon_id = request.session.get("ANON_ID")
    if anon_id:
        return str(anon_id)

    voter_id = request.session.get("voter_id") or request.session.get("VOTER_ID")
    if voter_id:
        return str(voter_id)

    if getattr(request, "user", None) and request.user.is_authenticated:
        return f"user:{request.user.pk}"

    return None


def get_voter_identity_from_scope(scope):
    """
    Lightweight identity resolver for Channels scope, mirroring get_voter_identity.
    """
    session = scope.get("session") or {}
    anon_id = session.get("ANON_ID")
    if anon_id:
        return str(anon_id)

    voter_id = session.get("voter_id") or session.get("VOTER_ID")
    if voter_id:
        return str(voter_id)

    user = scope.get("user")
    if user and getattr(user, "is_authenticated", False):
        return f"user:{user.pk}"
    return None
