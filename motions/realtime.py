import re
from typing import Any, Dict

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def voter_group(event_id: int) -> str:
    return f"motions_event_{event_id}"


def admin_group(event_id: int) -> str:
    return f"motions_admin_{event_id}"


def user_group(event_id: int, voter_token: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]", "-", str(voter_token))[:120]
    return f"motions_user_{event_id}_{safe}"


def _send(group: str, event: str, payload: Dict[str, Any]):
    layer = get_channel_layer()
    if not layer:
        return
    async_to_sync(layer.group_send)(
        group,
        {
            "type": "push.event",
            "event": event,
            "payload": payload,
        },
    )


def broadcast_to_voters(event_id: int, event: str, payload: Dict[str, Any]):
    _send(voter_group(event_id), event, payload)


def broadcast_to_admins(event_id: int, event: str, payload: Dict[str, Any]):
    _send(admin_group(event_id), event, payload)


def notify_voter(event_id: int, voter_token: str, event: str, payload: Dict[str, Any]):
    _send(user_group(event_id, voter_token), event, payload)
