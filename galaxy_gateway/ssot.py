"""
SSOT (Single Source of Truth) helpers for UDM write-through operations.

**Canonical device mutation path**::

    caller → udm_write_*()              (this module — gateway SSOT entry point)
           → UnifiedDeviceManager       (core.unified.device_manager — SSOT)
               └→ CapabilityBus         (core.capability_bus — capability visibility)

All device state mutations — register, heartbeat, unregister — must go
through :func:`udm_write_register`, :func:`udm_write_heartbeat`, and
:func:`udm_write_unregister` **before** any local cache is touched.
For partial / incremental updates, use :func:`udm_write_upsert`.

If a UDM write fails the helper returns ``False`` and emits a structured
``logging.warning`` with a stable ``event`` tag so that callers can gate
local-cache updates on the return value:

    if not udm_write_heartbeat(device_id):
        return   # do NOT update local state

Capability visibility is handled automatically inside
:class:`~core.unified.device_manager.UnifiedDeviceManager` — callers of
``udm_write_register`` do **not** need to call the CapabilityBus separately.

Structured event tags (stable, machine-queryable):
    ssot_udm_write_failed      — register write failed
    ssot_udm_heartbeat_failed  — heartbeat write failed
    ssot_udm_unregister_failed — unregister / offline write failed
    ssot_udm_upsert_failed     — partial-update (upsert) write failed
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _get_udm():
    """Return the singleton UnifiedDeviceManager (lazy import)."""
    from core.unified.device_manager import get_unified_device_manager  # noqa: E402
    return get_unified_device_manager()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def udm_write_register(
    device_id: str,
    device_name: str,
    device_type_raw: str,
    capabilities: List[Any],
    metadata: Dict[str, Any],
    source: str = "gateway",
) -> bool:
    """Write a device registration to UnifiedDeviceManager.

    Returns:
        True  — UDM write succeeded; caller may update local caches.
        False — UDM write failed; caller must NOT update local caches.
    """
    try:
        from core.unified.models import (  # noqa: E402
            UnifiedDevice,
            UnifiedDeviceStatus,
            UnifiedDeviceType,
        )

        segment = device_type_raw.split("_")[0] if "_" in device_type_raw else device_type_raw
        try:
            utype = UnifiedDeviceType(segment)
        except ValueError:
            utype = UnifiedDeviceType.UNKNOWN

        udm_device = UnifiedDevice(
            device_id=device_id,
            device_name=device_name,
            device_type=utype,
            status=UnifiedDeviceStatus.ONLINE,
            capabilities=list(capabilities) if capabilities else [],
            metadata=metadata or {},
            source=source,
        )
        _get_udm().register_device(udm_device)
        return True

    except Exception as exc:
        logger.warning(
            "SSOT guardrail: UDM write failed for device %s — "
            "local gateway state will NOT be updated. error=%s",
            device_id,
            exc,
            extra={"event": "ssot_udm_write_failed", "device_id": device_id},
        )
        return False


def udm_write_heartbeat(device_id: str) -> bool:
    """Record a device heartbeat in UnifiedDeviceManager.

    Returns:
        True  — UDM write succeeded; caller may update local online status.
        False — UDM write failed; caller must NOT update local status as truth.
    """
    try:
        from core.unified.models import UnifiedDeviceStatus  # noqa: E402

        _get_udm().update_device_status(device_id, UnifiedDeviceStatus.ONLINE)
        return True

    except Exception as exc:
        logger.warning(
            "SSOT guardrail: UDM heartbeat write failed for device %s — "
            "local gateway status NOT updated as truth. error=%s",
            device_id,
            exc,
            extra={"event": "ssot_udm_heartbeat_failed", "device_id": device_id},
        )
        return False


def udm_write_upsert(
    device_id: str,
    patch: Dict[str, Any],
    source: str = "gateway",
) -> bool:
    """Perform a partial or full device state update through UnifiedDeviceManager.

    This is the preferred write helper for incremental state changes (e.g.
    status-only updates, capability changes) that do not require a full
    re-registration cycle.  Each successful call increments the device's
    ``state_version`` counter and records ``updated_at``.

    Returns:
        True  — UDM write succeeded; caller may update local caches.
        False — UDM write failed; caller must NOT update local caches.
    """
    try:
        _get_udm().upsert_device_state(device_id, patch, source=source)
        return True
    except Exception as exc:
        logger.warning(
            "SSOT guardrail: UDM upsert failed for device %s — "
            "local state will NOT be updated. error=%s",
            device_id,
            exc,
            extra={"event": "ssot_udm_upsert_failed", "device_id": device_id},
        )
        return False


def udm_write_unregister(device_id: str) -> bool:
    """Mark a device offline / unregistered in UnifiedDeviceManager.

    For connection teardown the socket is definitively gone, so the local
    cache must be cleaned up regardless of UDM outcome.  Callers should
    always clean up local state after calling this helper but should log
    or handle the False return when tracking UDM consistency.

    Returns:
        True  — UDM write succeeded.
        False — UDM write failed (local state may diverge; warning already logged).
    """
    try:
        from core.unified.models import UnifiedDeviceStatus  # noqa: E402

        udm = _get_udm()
        # Prefer marking offline to preserve history; fall back to full unregister.
        try:
            udm.update_device_status(device_id, UnifiedDeviceStatus.OFFLINE)
        except Exception:
            udm.unregister_device(device_id)
        return True

    except Exception as exc:
        logger.warning(
            "SSOT guardrail: UDM unregister failed for device %s — "
            "local state may diverge from UDM. error=%s",
            device_id,
            exc,
            extra={"event": "ssot_udm_unregister_failed", "device_id": device_id},
        )
        return False
