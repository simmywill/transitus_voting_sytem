import secrets

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


def _motion_identity(session, session_uuid, create=False):
    """
    Provide a lightweight per-session identity for motions when no CIS/BBS
    handoff is present. Stored as a dict keyed by session UUID to avoid
    leaking identities across sessions.
    """
    if not session_uuid:
        return None
    tokens = {}
    try:
        tokens = session.get("MOTION_ANON_IDS") or {}
    except Exception:
        tokens = {}
    key = str(session_uuid)
    token = tokens.get(key)
    if token:
        return str(token)
    if not create:
        return None

    token = secrets.token_urlsafe(12)
    tokens[key] = token
    try:
        session["MOTION_ANON_IDS"] = tokens
        session.modified = True
    except Exception:
        pass
    return token


def get_voter_identity(request, session_uuid=None, create=False):
    """
    Adapter to reuse existing session identity without introducing new verification.
    Prefers the anonymous handoff ID issued by CIS/BBS, falls back to any stored voter_id
    or the authenticated user id. When a session_uuid is provided, generates a motion-only
    anonymous token to let QR entrants vote without CIS verification.
    """
    anon_id = request.session.get("ANON_ID")
    if anon_id:
        return str(anon_id)

    voter_id = request.session.get("voter_id") or request.session.get("VOTER_ID")
    if voter_id:
        return str(voter_id)

    if getattr(request, "user", None) and request.user.is_authenticated:
        return f"user:{request.user.pk}"

    motion_token = _motion_identity(request.session, session_uuid, create=create)
    return motion_token


def get_voter_identity_from_scope(scope, session_uuid=None):
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

    tokens = session.get("MOTION_ANON_IDS") or {}
    token = None
    if tokens:
        if session_uuid:
            token = tokens.get(str(session_uuid))
        else:
            # Fallback to the first token if no session is provided
            token = next(iter(tokens.values()), None)
    if token:
        return str(token)
    return None
