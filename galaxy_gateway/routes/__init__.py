"""Galaxy Gateway route modules."""

from .health import router as health_router
from .devices import router as devices_router
from .tasks import router as tasks_router
from .sessions import router as sessions_router
from .chat import router as chat_router
from .llm import router as llm_router
from .websocket import register_websocket_routes, _handle_android_ws

__all__ = [
    "health_router",
    "devices_router",
    "tasks_router",
    "sessions_router",
    "chat_router",
    "llm_router",
    "register_websocket_routes",
    "_handle_android_ws",
]
