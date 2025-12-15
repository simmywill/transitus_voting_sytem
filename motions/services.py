import logging
import os
from typing import Dict, Optional, Tuple

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone as tz

try:
    import redis  # type: ignore
except Exception:  # pragma: no cover
    redis = None

from .models import Motion, MotionVote

logger = logging.getLogger(__name__)

CHOICE_KEYS = {
    MotionVote.CHOICE_YES: "yes",
    MotionVote.CHOICE_NO: "no",
    MotionVote.CHOICE_ABSTAIN: "abstain",
}


def _redis_client():
    url = os.environ.get("REDIS_URL") or getattr(settings, "REDIS_URL", None)
    if not (url and redis):
        return None
    try:
        return redis.from_url(url, decode_responses=True)
    except Exception as exc:  # pragma: no cover
        logger.warning("Redis unavailable for motion tallies (%s)", exc)
        return None


def _tally_key(motion_id: int) -> str:
    return f"motion:{motion_id}:tally"


def _apply_delta(motion_id: int, delta: Dict[str, int]):
    client = _redis_client()
    key = _tally_key(motion_id)
    if client:
        try:
            pipe = client.pipeline()
            for choice, change in delta.items():
                pipe.hincrby(key, choice, change)
            pipe.expire(key, 86400)
            pipe.execute()
            return
        except Exception as exc:  # pragma: no cover
            logger.warning("Redis delta apply failed, falling back to memory (%s)", exc)
    # Fallback: keep a local cache dict in settings-level cache
    from django.core.cache import cache

    data = cache.get(key, {}) or {}
    for choice, change in delta.items():
        data[choice] = int(data.get(choice, 0)) + int(change)
    cache.set(key, data, timeout=86400)


def _set_counts(motion_id: int, counts: Dict[str, int]):
    client = _redis_client()
    key = _tally_key(motion_id)
    if client:
        try:
            client.delete(key)
            if counts:
                client.hset(key, mapping={k: int(v) for k, v in counts.items()})
                client.expire(key, 86400)
            return
        except Exception:  # pragma: no cover
            logger.debug("Redis set_counts fallback to cache")
    from django.core.cache import cache

    cache.set(key, {k: int(v) for k, v in counts.items()}, timeout=86400)


def get_live_counts(motion_id: int) -> Dict[str, int]:
    key = _tally_key(motion_id)
    client = _redis_client()
    if client:
        try:
            raw = client.hgetall(key) or {}
            return {k: int(v) for k, v in raw.items()}
        except Exception:  # pragma: no cover
            logger.debug("Redis live counts fallback to cache")
    from django.core.cache import cache

    raw = cache.get(key, {}) or {}
    return {k: int(v) for k, v in raw.items()}


def recompute_counts(motion: Motion) -> Dict[str, int]:
    agg = (
        MotionVote.objects.filter(motion=motion)
        .values("choice")
        .annotate(count=Count("id"))
    )
    counts = {CHOICE_KEYS.get(row["choice"], row["choice"]): row["count"] for row in agg}
    counts.setdefault(MotionVote.CHOICE_YES, counts.get("yes", 0))
    counts.setdefault(MotionVote.CHOICE_NO, counts.get("no", 0))
    counts.setdefault(MotionVote.CHOICE_ABSTAIN, counts.get("abstain", 0))
    _set_counts(motion.id, counts)
    return counts


@transaction.atomic
def record_vote(motion: Motion, voter_id: str, choice: str) -> Tuple[bool, Dict]:
    if motion.status != Motion.STATUS_OPEN:
        return False, {"error": "motion_closed"}
    if choice not in CHOICE_KEYS:
        return False, {"error": "invalid_choice"}

    existing = (
        MotionVote.objects.select_for_update().filter(motion=motion, voter_id=voter_id).first()
    )
    if existing:
        if not motion.allow_vote_change:
            return False, {"error": "vote_locked", "choice": existing.choice}
        if existing.choice == choice:
            return True, {
                "choice": choice,
                "changed": False,
                "created": False,
            }
        prev_choice = existing.choice
        existing.choice = choice
        existing.save(update_fields=["choice", "updated_at"])
        _apply_delta(motion.id, {CHOICE_KEYS[choice]: 1, CHOICE_KEYS[prev_choice]: -1})
        return True, {
            "choice": choice,
            "previous": prev_choice,
            "changed": True,
            "created": False,
        }

    MotionVote.objects.create(motion=motion, voter_id=voter_id, choice=choice)
    _apply_delta(motion.id, {CHOICE_KEYS[choice]: 1})
    return True, {"choice": choice, "created": True, "changed": False}


def ensure_only_one_open(event, target_motion: Motion):
    now = tz.now()
    Motion.objects.filter(event=event, status=Motion.STATUS_OPEN).exclude(pk=target_motion.pk).update(
        status=Motion.STATUS_CLOSED, closed_at=now
    )


def open_motion(motion: Motion):
    now = tz.now()
    with transaction.atomic():
        ensure_only_one_open(motion.event, motion)
        Motion.objects.filter(pk=motion.pk).update(
            status=Motion.STATUS_OPEN, opened_at=now, closed_at=None
        )
        motion.refresh_from_db()
        # Reset counters for a fresh open, seeding from DB if votes exist
        counts = recompute_counts(motion)
        _set_counts(motion.id, counts)
    return motion


def close_motion(motion: Motion) -> Dict[str, int]:
    now = tz.now()
    with transaction.atomic():
        Motion.objects.filter(pk=motion.pk).update(status=Motion.STATUS_CLOSED, closed_at=now)
        motion.refresh_from_db()
        counts = recompute_counts(motion)
    return counts


def reset_motion_votes(motion: Motion):
    with transaction.atomic():
        MotionVote.objects.filter(motion=motion).delete()
        _set_counts(motion.id, {})
