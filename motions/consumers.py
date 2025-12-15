import json
import logging
from types import SimpleNamespace

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.http import Http404

from .presence import PresenceTracker
from .realtime import admin_group, broadcast_to_admins, user_group, voter_group
from .utils import get_event_by_uuid, get_voter_identity_from_scope

logger = logging.getLogger(__name__)


class MotionVoterConsumer(AsyncJsonWebsocketConsumer):
    """
    Receives live motion state and connection health for voters.
    """

    async def connect(self):
        self.session_uuid = self.scope["url_route"]["kwargs"].get("session_uuid")
        try:
            event = await self._get_event()
        except Http404:
            await self.close(code=4404)
            return

        identity = get_voter_identity_from_scope(self.scope)
        if not identity:
            await self.close(code=4401)
            return

        self.event = event
        self.event_id = event.pk
        self.identity = identity
        self.event_group = voter_group(self.event_id)
        self.user_group = user_group(self.event_id, identity)

        await self.channel_layer.group_add(self.event_group, self.channel_name)
        await self.channel_layer.group_add(self.user_group, self.channel_name)
        await self.accept()

        count = await self._heartbeat()
        await self._emit_presence(count)
        await self.send_json({"event": "connection", "payload": {"status": "connected"}})

    async def disconnect(self, code):
        try:
            await self.channel_layer.group_discard(self.event_group, self.channel_name)
            await self.channel_layer.group_discard(self.user_group, self.channel_name)
        except Exception:
            pass
        if getattr(self, "event_id", None) and getattr(self, "identity", None):
            await self._mark_gone()
            count = await self._count_presence()
            await self._emit_presence(count)

    async def receive_json(self, content, **kwargs):
        action = content.get("type")
        if action in ("heartbeat", "ping"):
            count = await self._heartbeat()
            await self._emit_presence(count)
            await self.send_json(
                {"event": "heartbeat_ack", "payload": {"active_count": count}}
            )
            return
        await self.send_json(
            {"event": "error", "payload": {"message": "Unknown event type"}}
        )

    async def push_event(self, event):
        await self.send_json({"event": event.get("event"), "payload": event.get("payload")})

    @database_sync_to_async
    def _get_event(self):
        return get_event_by_uuid(self.session_uuid)

    @database_sync_to_async
    def _heartbeat(self) -> int:
        tracker = PresenceTracker()
        return tracker.heartbeat(self.event_id, self.identity)

    @database_sync_to_async
    def _mark_gone(self):
        tracker = PresenceTracker()
        tracker.mark_gone(self.event_id, self.identity)

    @database_sync_to_async
    def _count_presence(self) -> int:
        tracker = PresenceTracker()
        return tracker.count(self.event_id)

    async def _emit_presence(self, count: int):
        try:
            await self.channel_layer.group_send(
                admin_group(self.event_id),
                {"type": "push.event", "event": "presence_update", "payload": {"count": count}},
            )
            await self.channel_layer.group_send(
                voter_group(self.event_id),
                {"type": "push.event", "event": "presence_update", "payload": {"count": count}},
            )
        except Exception:
            logger.debug("Failed to broadcast presence update", exc_info=True)


class MotionAdminConsumer(AsyncJsonWebsocketConsumer):
    """
    Admin/moderator channel for live tallies and control state updates.
    """

    async def connect(self):
        self.session_uuid = self.scope["url_route"]["kwargs"].get("session_uuid")
        user = self.scope.get("user")
        if not (user and user.is_authenticated and user.is_staff):
            await self.close(code=4403)
            return
        try:
            event = await self._get_event()
        except Http404:
            await self.close(code=4404)
            return

        self.event = event
        self.event_id = event.pk
        self.admin_group_name = admin_group(self.event_id)

        await self.channel_layer.group_add(self.admin_group_name, self.channel_name)
        await self.accept()

        count = await self._count_presence()
        await self.send_json(
            {"event": "presence_update", "payload": {"count": count, "role": "moderator"}}
        )

    async def disconnect(self, code):
        try:
            await self.channel_layer.group_discard(self.admin_group_name, self.channel_name)
        except Exception:
            pass

    async def receive_json(self, content, **kwargs):
        action = content.get("type")
        if action in ("heartbeat", "ping"):
            count = await self._count_presence()
            await self.send_json(
                {"event": "heartbeat_ack", "payload": {"active_count": count, "role": "moderator"}}
            )
            return
        await self.send_json(
            {"event": "error", "payload": {"message": "Unknown event type"}}
        )

    async def push_event(self, event):
        await self.send_json({"event": event.get("event"), "payload": event.get("payload")})

    @database_sync_to_async
    def _get_event(self):
        return get_event_by_uuid(self.session_uuid)

    @database_sync_to_async
    def _count_presence(self) -> int:
        tracker = PresenceTracker()
        return tracker.count(self.event_id)
