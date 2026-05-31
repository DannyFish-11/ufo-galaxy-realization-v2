"""
galaxy_gateway/routes/sync_status.py

GET /sync/status — Real-time cross-device sync quality metrics.

Returns per-device latency profiles, current topology, and phase sync
history. Used by external monitoring or CLI tools.
"""
from __future__ import annotations

import time
from typing import Any, Dict

try:
    from fastapi import APIRouter
    router = APIRouter()
    _FASTAPI = True
except ImportError:
    router = None  # type: ignore[assignment]
    _FASTAPI = False

from core.cross_device_sync import get_sync_diagnostics


def get_sync_status() -> Dict[str, Any]:
    """Build sync status response."""
    diagnostics = get_sync_diagnostics()
    profiles = diagnostics.get("latency_profiles", {})

    # Summarize
    healthy = sum(1 for p in profiles.values() if p.get("healthy"))
    unhealthy = sum(1 for p in profiles.values() if not p.get("healthy"))
    avg_latencies = [p["avg_ms"] for p in profiles.values() if p.get("avg_ms", 0) > 0]
    overall_avg = round(sum(avg_latencies) / len(avg_latencies), 1) if avg_latencies else 0

    return {
        "timestamp": int(time.time() * 1000),
        "engine": "adaptive_async_concurrent",
        "summary": {
            "tracked_devices": len(profiles),
            "healthy": healthy,
            "unhealthy": unhealthy,
            "overall_avg_latency_ms": overall_avg,
        },
        "devices": profiles,
    }


if _FASTAPI and router:
    @router.get("/sync/status")
    async def sync_status():
        return get_sync_status()
