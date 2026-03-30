"""
galaxy_gateway/dependencies.py — App-scoped service dependency helpers.

Route handlers use these helpers to access initialized services stored on
``app.state`` without relying on module-level global variables.  Services are
populated during the application lifespan startup phase
(see ``galaxy_gateway.bootstrap.lifecycle``).

Example usage in a route handler::

    from fastapi import Depends
    from galaxy_gateway.dependencies import get_device_manager

    @router.get("/api/devices")
    async def list_devices(dm=Depends(get_device_manager)):
        return dm.to_dict()

All getters raise HTTP 503 when the requested service has not yet been
initialized (i.e., before lifespan startup completes).  Optional services
(e.g. NATS adapter, OpenClawd) return ``None`` instead of raising.
"""

import logging
from typing import Any, Optional

from fastapi import HTTPException
from starlette.requests import Request

logger = logging.getLogger(__name__)


def _get_state(request: Request, attr: str, *, required: bool = True) -> Any:
    """Retrieve a named service from ``request.app.state``."""
    value = getattr(request.app.state, attr, None)
    if required and value is None:
        raise HTTPException(status_code=503, detail="Service not ready")
    return value


# ---------------------------------------------------------------------------
# Required services — raise 503 when unavailable
# ---------------------------------------------------------------------------

def get_device_manager(request: Request):
    """Return the initialized ``DeviceManager`` from app state."""
    return _get_state(request, "device_manager")


def get_message_handler(request: Request):
    """Return the initialized ``MessageHandler`` from app state."""
    return _get_state(request, "message_handler")


def get_websocket_manager(request: Request):
    """Return the initialized ``WebSocketManager`` from app state."""
    return _get_state(request, "websocket_manager")


def get_task_orchestrator(request: Request):
    """Return the initialized ``TaskOrchestrator`` from app state."""
    return _get_state(request, "task_orchestrator")


# ---------------------------------------------------------------------------
# Optional services — return None when unavailable
# ---------------------------------------------------------------------------

def get_nats_adapter(request: Request) -> Optional[Any]:
    """Return the NATS adapter if available, else ``None``."""
    return _get_state(request, "nats_adapter", required=False)


def get_openclawd(request: Request) -> Optional[Any]:
    """Return the ``OpenClawd`` instance if available, else ``None``."""
    return _get_state(request, "openclawd_instance", required=False)


def get_llm_router_instance(request: Request) -> Optional[Any]:
    """Return the LLM router instance if available, else ``None``."""
    return _get_state(request, "llm_router_instance", required=False)
