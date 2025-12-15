from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path(
        "ws/motions/<uuid:session_uuid>/voter/",
        consumers.MotionVoterConsumer.as_asgi(),
        name="motion_ws_voter",
    ),
    path(
        "ws/motions/<uuid:session_uuid>/admin/",
        consumers.MotionAdminConsumer.as_asgi(),
        name="motion_ws_admin",
    ),
]
