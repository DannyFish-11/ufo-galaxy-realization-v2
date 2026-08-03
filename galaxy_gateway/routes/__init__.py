"""Galaxy Gateway route modules."""

from .chat import router as chat_router
from .devices import router as devices_router
from .health import router as health_router
from .llm import router as llm_router
from .sessions import router as sessions_router
from .tasks import router as tasks_router
from .websocket import _handle_android_ws, register_websocket_routes

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
