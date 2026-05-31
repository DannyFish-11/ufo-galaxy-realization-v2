"""
core/cross_device_sync.py
=========================
PR-CROSS-DEVICE-SYNC: Adaptive Async Concurrent State Synchronization.

Replaces the legacy serial for-loop with an adaptive concurrent engine:
- Devices are pushed concurrently via asyncio.gather
- Slow devices do NOT block fast devices
- Per-device latency tracking enables dynamic prioritization
- Adaptive timeout based on observed device RTT
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.CrossDeviceSync")

try:
    from core.schemas.aip_v3 import StateEventMsg  # noqa: F401
    _AIPV3_AVAILABLE = True
except ImportError:
    _AIPV3_AVAILABLE = False

# ---------------------------------------------------------------------------
# Per-device latency tracker (adaptive prioritization)
# ---------------------------------------------------------------------------

@dataclass
class DeviceLatencyProfile:
    """Observed latency profile for a single device."""
    device_id: str
    samples: List[float] = field(default_factory=list)  # ms
    max_samples: int = 10
    last_success: float = 0.0  # timestamp
    last_failure: float = 0.0  # timestamp
    failure_count: int = 0

    def record(self, latency_ms: float, success: bool) -> None:
        if success:
            self.samples.append(latency_ms)
            if len(self.samples) > self.max_samples:
                self.samples.pop(0)
            self.last_success = time.time()
            self.failure_count = max(0, self.failure_count - 1)
        else:
            self.last_failure = time.time()
            self.failure_count += 1

    @property
    def avg_latency(self) -> float:
        if not self.samples:
            return 50.0  # default assumption 50ms
        return sum(self.samples) / len(self.samples)

    @property
    def p95_latency(self) -> float:
        if not self.samples:
            return 100.0
        sorted_samples = sorted(self.samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]

    @property
    def is_healthy(self) -> bool:
        return self.failure_count < 3

    @property
    def adaptive_timeout(self) -> float:
        """Dynamic timeout: p95 + headroom, clamped to [0.5s, 5s]."""
        timeout = self.p95_latency * 3 + 100  # 3x p95 + 100ms buffer
        return max(0.5, min(timeout / 1000, 5.0))

    def priority_score(self) -> float:
        """Lower score = higher priority.

        Factors:
        - Lower latency = higher priority (faster devices first)
        - Recent failure = lower priority (penalize flaky devices)
        - No samples = medium priority (new devices)
        """
        score = self.avg_latency
        if not self.is_healthy:
            score += 200 * self.failure_count  # heavy penalty
        if not self.samples:
            score = 30.0  # treat new devices as fast (optimistic)
        return score


class _LatencyTracker:
    """Module-level singleton tracking observed latency per device."""

    def __init__(self) -> None:
        self._profiles: Dict[str, DeviceLatencyProfile] = {}

    def get(self, device_id: str) -> DeviceLatencyProfile:
        if device_id not in self._profiles:
            self._profiles[device_id] = DeviceLatencyProfile(device_id=device_id)
        return self._profiles[device_id]

    def remove(self, device_id: str) -> None:
        self._profiles.pop(device_id, None)

    def sorted_devices(self, device_ids: List[str]) -> List[str]:
        """Return device_ids sorted by priority (fastest first)."""
        def sort_key(did: str) -> float:
            return self.get(did).priority_score()
        return sorted(device_ids, key=sort_key)

    def all_profiles(self) -> Dict[str, Dict[str, Any]]:
        return {
            did: {
                "avg_ms": round(p.avg_latency, 1),
                "p95_ms": round(p.p95_latency, 1),
                "failures": p.failure_count,
                "healthy": p.is_healthy,
                "timeout_s": round(p.adaptive_timeout, 2),
            }
            for did, p in self._profiles.items()
        }


_latency_tracker = _LatencyTracker()

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def emit_cross_device_phase_sync(
    old_phase: str,
    new_phase: str,
    session_id: str,
    source: str = "desktop_presence_runtime",
    trace_id: str = "",
) -> None:
    """Fire-and-forget: push phase change to all connected Android devices.

    Called synchronously from RuntimeSession.advance().
    Uses asyncio.create_task so it never blocks the caller.
    """
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(
            _async_push_phase_to_all_devices(
                old_phase=old_phase,
                new_phase=new_phase,
                session_id=session_id,
                source=source,
                trace_id=trace_id,
            )
        )
    except RuntimeError:
        logger.debug("CrossDeviceSync: no event loop, skipping push")


async def _async_push_phase_to_all_devices(
    old_phase: str,
    new_phase: str,
    session_id: str,
    source: str,
    trace_id: str,
) -> None:
    """Adaptive async concurrent push to all connected devices.

    Key behaviours:
    1. All devices are pushed concurrently (asyncio.gather)
    2. Per-device adaptive timeout based on observed RTT
    3. Devices sorted by latency profile (fastest first in logs)
    4. Slow devices do NOT block fast devices
    5. Latency is recorded for future prioritization
    """
    try:
        from galaxy_gateway.android_bridge import (  # noqa: PLC0415
            android_bridge as _bridge,
        )
    except Exception as exc:
        logger.debug("CrossDeviceSync: bridge not available: %s", exc)
        return

    # Build AIP v3 STATE_EVENT message
    msg: Dict[str, Any] = {
        "type": "state_event",
        "event_category": "phase",
        "event_action": new_phase,
        "device_id": "v2_desktop",
        "timestamp": int(time.time() * 1000),
        "session_id": session_id,
        "trace_id": trace_id or session_id,
        "aip_version": "3.0",
        "payload": {
            "from_phase": old_phase,
            "to_phase": new_phase,
            "source": source,
            "sync_type": "cross_device_broadcast",
        },
        "phase": new_phase,
    }

    # Collect connected devices
    connected: List[Tuple[str, Any]] = []
    for device_id, device in _bridge._devices.items():
        if device.websocket is not None and getattr(device, "connected", False):
            connected.append((device_id, device))

    if not connected:
        logger.debug("CrossDeviceSync: no connected devices to push to")
        return

    # Sort by observed latency (fastest first) — adaptive prioritization
    device_ids = [did for did, _ in connected]
    sorted_ids = _latency_tracker.sorted_devices(device_ids)
    sorted_devices = [(did, dict(connected)[did]) for did in sorted_ids]

    # Concurrent push with per-device adaptive timeout
    push_start = time.time()
    tasks = [
        _push_to_one_device(did, dev, msg)
        for did, dev in sorted_devices
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect results
    sent = 0
    failed = 0
    for (did, _), result in zip(sorted_devices, results):
        if isinstance(result, Exception):
            failed += 1
            _latency_tracker.get(did).record(0, success=False)
            logger.debug("CrossDeviceSync: push to %s failed: %s", did, result)
        elif result is True:
            sent += 1

    total_ms = (time.time() - push_start) * 1000
    logger.info(
        "CrossDeviceSync: phase %s→%s pushed to %d/%d device(s) "
        "in %.1fms (adaptive concurrent)",
        old_phase, new_phase, sent, len(connected), total_ms,
    )


async def _push_to_one_device(
    device_id: str,
    device: Any,
    msg: Dict[str, Any],
) -> bool:
    """Push to a single device with adaptive timeout and retry.

    Returns True on success, raises on failure.
    """
    profile = _latency_tracker.get(device_id)
    timeout = profile.adaptive_timeout
    MAX_RETRIES = 2

    for attempt in range(MAX_RETRIES):
        t0 = time.time()
        try:
            await asyncio.wait_for(
                device.websocket.send_json(msg),
                timeout=timeout,
            )
            latency_ms = (time.time() - t0) * 1000
            profile.record(latency_ms, success=True)
            logger.debug(
                "CrossDeviceSync: push to %s OK (%.1fms, timeout=%.2fs)",
                device_id, latency_ms, timeout,
            )
            return True
        except asyncio.TimeoutError:
            profile.record(timeout * 1000, success=False)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(0.05 * (attempt + 1))
            else:
                raise
        except Exception:
            latency_ms = (time.time() - t0) * 1000
            profile.record(latency_ms, success=False)
            raise

    return False


async def push_task_state_to_device(
    device_id: str,
    task_status: str,
    task_result: Optional[str] = None,
    task_error: Optional[str] = None,
    session_id: str = "",
    trace_id: str = "",
) -> bool:
    """Push task state update to a specific Android device."""
    try:
        from galaxy_gateway.android_bridge import (  # noqa: PLC0415
            android_bridge as _bridge,
        )

        device = _bridge._devices.get(device_id)
        if device is None or device.websocket is None:
            return False

        msg: Dict[str, Any] = {
            "type": "state_event",
            "event_category": "task",
            "event_action": task_status,
            "device_id": "v2_desktop",
            "timestamp": int(time.time() * 1000),
            "session_id": session_id,
            "trace_id": trace_id,
            "aip_version": "3.0",
            "payload": {
                "task_status": task_status,
                "task_result": task_result,
                "task_error": task_error,
            },
        }

        return await _push_to_one_device(device_id, device, msg)

    except Exception as exc:
        logger.debug("CrossDeviceSync: task push to %s failed: %s", device_id, exc)
        return False


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def get_sync_diagnostics() -> Dict[str, Any]:
    """Return current sync engine diagnostics for /status endpoint."""
    return {
        "latency_profiles": _latency_tracker.all_profiles(),
        "total_tracked_devices": len(_latency_tracker._profiles),
    }


def forget_device(device_id: str) -> None:
    """Remove a device's latency profile (call on disconnect)."""
    _latency_tracker.remove(device_id)
