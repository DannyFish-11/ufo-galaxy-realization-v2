"""
Cross-Device Switch — Feature Flag Module
==========================================

Provides the single, authoritative cross-device switch for the Galaxy Gateway.

When the switch is **OFF** (the factory default — local mode) all cross-device
routing paths (task routing, WS/WebRTC signaling) are rejected immediately with
structured error responses and log entries that include the ``trace_id`` so
operators can correlate failures across the system.

When the switch is **ON** all cross-device paths operate normally, respecting
AIP v3 + trace/route_mode and capability-registry flows introduced in prior rounds.

What "ON" means is decided in exactly one place:
:func:`core.system_mode.cross_device_requested` — ``GALAXY_CROSS_DEVICE_ENABLED``
true *or* ``GALAXY_SYSTEM_MODE=desktop-cross-device``.  This module does not
derive it again.

Error codes / messages (switch OFF)
------------------------------------
HTTP  : 403  ``"cross_device_disabled"``
WS    : close code 4001  ``"cross-device routing disabled"``
Dict  : ``{"success": False, "error": "cross_device_disabled",
           "message": "Cross-device routing is disabled by server policy",
           "trace_id": "<trace_id>"}``

Dispatcher rule
---------------
``DeviceRouter`` (``galaxy_gateway/device_router.py``) is the **canonical,
single dispatcher**.  All cross-device sub-paths (coordinator, enhancements
scheduler) are gated through this module so the switch is checked in exactly
one place per entry-point, not scattered across callers.
"""

import logging
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: HTTP status code returned when cross-device routing is disabled.
HTTP_STATUS_CROSS_DEVICE_DISABLED: int = 403

#: WebSocket close code used when cross-device routing is disabled.
WS_CLOSE_CODE_CROSS_DEVICE_DISABLED: int = 4001

#: Machine-readable error token (stable across versions).
ERROR_CODE_CROSS_DEVICE_DISABLED: str = "cross_device_disabled"

#: Human-readable error message.
ERROR_MSG_CROSS_DEVICE_DISABLED: str = "Cross-device routing is disabled by server policy"


# ---------------------------------------------------------------------------
# Switch helpers
# ---------------------------------------------------------------------------


def is_cross_device_enabled() -> bool:
    """Return ``True`` when cross-device routing is **enabled**.

    Reads the environment at call-time so the switch can be toggled without
    restarting the process (useful for tests).

    Default: **disabled** (opt-in; local mode).  The answer comes from
    :func:`core.system_mode.cross_device_requested` — the same one the startup
    orchestrator, the desktop presence runtime and the health check use, so the
    layers can no longer disagree about which mode the system is in.
    """
    from core.system_mode import cross_device_requested

    return cross_device_requested()


def guard_cross_device(trace_id: Optional[str] = None) -> None:
    """Raise :class:`CrossDeviceDisabledError` when the switch is OFF.

    Logs a structured ``cross_device_blocked`` event at WARNING level that
    includes the ``trace_id`` for end-to-end traceability.

    Args:
        trace_id: Optional trace ID from the originating request.  When
            ``None`` a new UUID is generated so the log entry is always
            traceable.

    Raises:
        CrossDeviceDisabledError: When cross-device routing is disabled.
    """
    if not is_cross_device_enabled():
        tid = trace_id or str(uuid.uuid4())
        logger.warning(
            "cross_device_blocked trace_id=%s reason=%s",
            tid,
            ERROR_CODE_CROSS_DEVICE_DISABLED,
        )
        raise CrossDeviceDisabledError(trace_id=tid)


def make_disabled_response(trace_id: Optional[str] = None) -> Dict[str, Any]:
    """Build a structured error dict for callers that return dicts (not raise).

    Logs a ``cross_device_blocked`` event (same as :func:`guard_cross_device`).

    Args:
        trace_id: Optional trace ID from the originating request.

    Returns:
        Dict with ``success=False``, ``error``, ``message``, and ``trace_id``.
    """
    tid = trace_id or str(uuid.uuid4())
    logger.warning(
        "cross_device_blocked trace_id=%s reason=%s",
        tid,
        ERROR_CODE_CROSS_DEVICE_DISABLED,
    )
    return {
        "success": False,
        "error": ERROR_CODE_CROSS_DEVICE_DISABLED,
        "message": ERROR_MSG_CROSS_DEVICE_DISABLED,
        "trace_id": tid,
    }


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class CrossDeviceDisabledError(RuntimeError):
    """Raised by :func:`guard_cross_device` when cross-device routing is OFF.

    Attributes:
        trace_id: The trace ID attached to the blocked request.
    """

    def __init__(self, trace_id: Optional[str] = None) -> None:
        self.trace_id: str = trace_id or str(uuid.uuid4())
        super().__init__(f"{ERROR_MSG_CROSS_DEVICE_DISABLED} (trace_id={self.trace_id})")


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

__all__ = [
    "is_cross_device_enabled",
    "guard_cross_device",
    "make_disabled_response",
    "CrossDeviceDisabledError",
    "HTTP_STATUS_CROSS_DEVICE_DISABLED",
    "WS_CLOSE_CODE_CROSS_DEVICE_DISABLED",
    "ERROR_CODE_CROSS_DEVICE_DISABLED",
    "ERROR_MSG_CROSS_DEVICE_DISABLED",
]
