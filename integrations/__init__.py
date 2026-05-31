"""
Galaxy ↔ Home Assistant Integration (Node_27_SmartHome)
=====================================================

Provides bidirectional control between Galaxy and Home Assistant:
- Entity discovery & state sync (WebSocket)
- Device control via service calls
- Area/room mapping for spatial awareness
- Automation trigger bridge

Env vars:
    HOME_ASSISTANT_URL      e.g. http://homeassistant.local:8123
    HOME_ASSISTANT_TOKEN    Long-lived access token

Thread-safety: All public APIs are async-safe with internal locking.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Coroutine, Optional

from .connector import HAConnector
from .discovery import EntityDiscovery
from .gateway import SmartHomeGateway

__all__ = ['SmartHomeGateway', 'HAConnector', 'EntityDiscovery', 'init_integration', 'shutdown_integration', 'get_gateway']

logger = logging.getLogger('galaxy.smarthome')

# ---------------------------------------------------------------------------
# Singleton state (managed by DesktopPresenceRuntime lifecycle)
# ---------------------------------------------------------------------------
_gateway: Optional[SmartHomeGateway] = None
_init_lock = asyncio.Lock()
_init_error: Optional[Exception] = None


async def init_integration(
    on_state_change: Optional[
        Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]
    ] = None,
) -> SmartHomeGateway:
    """Initialize Home Assistant integration.

    Called by Node_27_SmartHome during LIMINAL → MANIFEST transition.
    Returns the gateway singleton; safe to call multiple times (idempotent).
    Raises RuntimeError if credentials missing; HAError if connection fails.
    """
    global _gateway, _init_error

    async with _init_lock:
        # Already initialized
        if _gateway is not None and _gateway.initialized:
            logger.debug("SmartHome gateway already initialized")
            return _gateway

        # Previous init failed — don't retry blindly
        if _init_error is not None:
            logger.warning("Previous init failed with: %s", _init_error)

        url = os.environ.get('HOME_ASSISTANT_URL')
        token = os.environ.get('HOME_ASSISTANT_TOKEN')

        if not url or not token:
            missing = []
            if not url:
                missing.append('HOME_ASSISTANT_URL')
            if not token:
                missing.append('HOME_ASSISTANT_TOKEN')
            err_msg = f"Home Assistant credentials missing: {', '.join(missing)}"
            logger.warning(err_msg)
            raise RuntimeError(err_msg)

        connector = HAConnector(url=url, token=token)
        discovery = EntityDiscovery(connector=connector)

        _gateway = SmartHomeGateway(
            connector=connector,
            discovery=discovery,
            on_state_change=on_state_change,
        )

        try:
            await _gateway.connect()
            _init_error = None
            logger.info("SmartHome gateway initialized — %s", url)
            return _gateway
        except Exception:
            _gateway = None
            _init_error = Exception("Init failed")
            raise


async def shutdown_integration() -> None:
    """Graceful teardown. Called during MANIFEST → SILENT.
    Idempotent — safe to call multiple times.
    """
    global _gateway, _init_error

    async with _init_lock:
        if _gateway is not None:
            try:
                await _gateway.disconnect()
            except Exception as exc:
                logger.warning("Error during shutdown: %s", exc)
            finally:
                _gateway = None
                _init_error = None
                logger.info("SmartHome gateway shut down")


def get_gateway() -> Optional[SmartHomeGateway]:
    """Get current gateway instance (non-async, for status checks)."""
    return _gateway
