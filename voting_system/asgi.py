"""
ASGI config for voting_system project.

Handles both HTTP and WebSocket traffic via Channels for live motion voting.
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "voting_system.settings")

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

import motions.routing

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(motions.routing.websocket_urlpatterns))
        ),
    }
)
