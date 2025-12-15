import logging
import os
import time
from typing import Dict, Optional

from django.conf import settings
from django.core.cache import cache

try:  # Redis is optional; fall back to process-local cache
    import redis  # type: ignore
except Exception:  # pragma: no cover - handled by fallback
    redis = None

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SEC = int(getattr(settings, "MOTION_HEARTBEAT_SEC", 15))
PRESENCE_TIMEOUT_SEC = int(getattr(settings, "MOTION_PRESENCE_TIMEOUT_SEC", 45))


class PresenceTracker:
    """
    Tracks live attendance per event using Redis when available, otherwise an
    in-process cache. Presence is defined as a heartbeat within the timeout window.
    """

    def __init__(self):
        self.redis_url = os.environ.get("REDIS_URL") or getattr(settings, "REDIS_URL", None)
        self._client = None

    def _key(self, event_id: int) -> str:
        return f"presence:event:{event_id}"

    def _get_client(self):
        if self._client or not (self.redis_url and redis):
            return self._client
        try:
            self._client = redis.from_url(self.redis_url, decode_responses=True)
        except Exception as exc:  # pragma: no cover - best-effort fallback
            logger.warning("PresenceTracker: redis unavailable, falling back to cache (%s)", exc)
            self._client = None
        return self._client

    def _fallback_store(self, key: str) -> Dict[str, int]:
        return cache.get(key, {}) or {}

    def heartbeat(self, event_id: int, voter_id: str) -> int:
        now = int(time.time())
        client = self._get_client()
        key = self._key(event_id)

        if client:
            try:
                client.zadd(key, {voter_id: now})
                client.zremrangebyscore(key, 0, now - PRESENCE_TIMEOUT_SEC)
                client.expire(key, max(PRESENCE_TIMEOUT_SEC * 2, 120))
                return int(client.zcard(key))
            except Exception as exc:  # pragma: no cover - fallback on runtime failure
                logger.warning("PresenceTracker: redis heartbeat failed, using cache (%s)", exc)

        store = self._fallback_store(key)
        store[voter_id] = now
        cutoff = now - PRESENCE_TIMEOUT_SEC
        store = {k: ts for k, ts in store.items() if ts >= cutoff}
        cache.set(key, store, timeout=PRESENCE_TIMEOUT_SEC * 2)
        return len(store)

    def count(self, event_id: int) -> int:
        now = int(time.time())
        client = self._get_client()
        key = self._key(event_id)
        cutoff = now - PRESENCE_TIMEOUT_SEC
        if client:
            try:
                client.zremrangebyscore(key, 0, cutoff)
                return int(client.zcard(key))
            except Exception as exc:  # pragma: no cover
                logger.warning("PresenceTracker: redis count failed, using cache (%s)", exc)
        store = self._fallback_store(key)
        store = {k: ts for k, ts in store.items() if ts >= cutoff}
        cache.set(key, store, timeout=PRESENCE_TIMEOUT_SEC * 2)
        return len(store)

    def mark_gone(self, event_id: int, voter_id: str):
        client = self._get_client()
        key = self._key(event_id)
        if client:
            try:
                client.zrem(key, voter_id)
                return
            except Exception:  # pragma: no cover
                logger.debug("PresenceTracker: redis mark_gone fallback")
        store = self._fallback_store(key)
        if voter_id in store:
            store.pop(voter_id, None)
            cache.set(key, store, timeout=PRESENCE_TIMEOUT_SEC * 2)
