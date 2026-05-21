"""
core/nats_posture.py
====================
Canonical runtime posture policy for NATS.
"""

from __future__ import annotations

import os
from typing import Any, Dict

NATS_POSTURE_AUTHORITY: str = "core.nats_posture"
NATS_POSTURE_PRODUCTION_REQUIRED: str = "production-required"
NATS_POSTURE_DEVELOPMENT_ALLOWED_DEGRADED: str = "development-allowed-degraded"


def build_default_posture_snapshot() -> Dict[str, Any]:
    """Return a stable fallback snapshot when posture evaluation is unavailable."""
    return {
        "authority": NATS_POSTURE_AUTHORITY,
        "posture": NATS_POSTURE_DEVELOPMENT_ALLOWED_DEGRADED,
        "required": False,
        "system_mode": "desktop-local",
        "nats_url": os.environ.get("GALAXY_NATS_URL", "nats://localhost:4222"),
        "connected": False,
        "noop_mode": True,
        "assertion_ok": True,
        "violation_reason": "",
        "bus": {},
        "bus_error": "",
    }


def evaluate_nats_posture() -> Dict[str, Any]:
    """Return the canonical NATS posture snapshot and assertion result."""
    from core.system_mode import resolve_fabric_config

    fabric = resolve_fabric_config()
    required = bool(fabric.nats_required)
    posture = (
        NATS_POSTURE_PRODUCTION_REQUIRED
        if required
        else NATS_POSTURE_DEVELOPMENT_ALLOWED_DEGRADED
    )

    bus_stats: Dict[str, Any] = {}
    connected = False
    noop_mode = True
    bus_error = ""
    try:
        from core.nats_bus import nats_bus

        bus_stats = nats_bus.get_stats()
        connected = bool(bus_stats.get("connected", False))
        noop_mode = bool(bus_stats.get("noop_mode", True))
    except Exception as exc:
        bus_error = str(exc)

    # Policy contract:
    # - production-required posture: NATS must be connected.
    # - development-allowed-degraded posture: allow degraded/no-op operation.
    assertion_ok = connected if required else True
    violation_reason = "" if assertion_ok else "required_nats_unreachable"

    result = build_default_posture_snapshot()
    result.update({
        "posture": posture,
        "required": required,
        "system_mode": fabric.mode.value,
        "nats_url": fabric.nats_url,
        "connected": connected,
        "noop_mode": noop_mode,
        "assertion_ok": assertion_ok,
        "violation_reason": violation_reason,
        "bus": bus_stats,
        "bus_error": bus_error,
    })
    return result
