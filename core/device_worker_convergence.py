"""
core/device_worker_convergence.py
==================================
PR-DEVICE-WORKER-FUSION: Device–Worker Convergence Layer (NO BRIDGE)

Design principle:  A device registered in UDM IS a NATS Worker.

When a device registers via UDM.register_device():
    1. It is written to UDM (canonical truth) — existing
    2. It is registered as a NATS Worker — THIS MODULE
    3. Its capabilities are published to the capability bus — existing

When a device heartbeats:
    1. UDM updates last_seen — existing
    2. NATS Worker heartbeat is emitted — THIS MODULE

When Mesh needs to schedule a device:
    1. It looks up the device in UDM — existing
    2. If remote, NATS delivers the request — mesh_nats_fusion.py
    3. The device (as Worker) executes and replies

This is NOT a bridge between UDM and NATS.  It is a convergence:
both systems share the SAME entity (a device) and THIS module
keeps both views in sync.

Usage::

    from core.device_worker_convergence import DeviceWorkerConvergence

    dwc = DeviceWorkerConvergence(nats_bus)
    await dwc.on_device_registered(device)  # called after UDM write
    await dwc.on_device_heartbeat(device_id)  # called on heartbeat
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------
DEVICE_WORKER_CONVERGENCE_SENTINEL = (
    "DEVICE_WORKER_CONVERGENCE::UDM_IS_WORKER::NO_BRIDGE"
)


# ---------------------------------------------------------------------------
# Convergence layer
# ---------------------------------------------------------------------------
class DeviceWorkerConvergence:
    """Device–Worker convergence: UDM device IS a NATS Worker.

    This module is called by UDM hooks (after device registration)
    and by the heartbeat loop.  It does NOT duplicate UDM's state;
    it only emits the NATS-side Worker events that let the Mesh
    scheduler and task dispatch chain treat the device as a
    first-class distributed participant.
    """

    # NATS subject patterns
    SUBJ_WORKER_REGISTER = "galaxy.worker.register"
    SUBJ_WORKER_HEARTBEAT = "galaxy.worker.heartbeat"
    SUBJ_WORKER_CAPABILITIES = "galaxy.worker.capabilities"
    SUBJ_WORKER_SHUTDOWN = "galaxy.worker.shutdown"

    def __init__(self, nats_bus: Optional[Any] = None) -> None:
        self._nats = nats_bus
        self._device_worker_map: Dict[str, str] = {}  # device_id → worker_id

    # -- public: lifecycle ----------------------------------------------------

    def is_available(self) -> bool:
        return self._nats is not None and getattr(self._nats, "is_connected", lambda: False)()

    async def on_device_registered(self, device: Any) -> None:
        """Called AFTER UDM.register_device() succeeds.

        Emits the NATS Worker registration event so the Mesh
        scheduler knows this device exists as a remote-capable
        participant.
        """
        if not self.is_available():
            return

        device_id = self._extract(device, "device_id")
        device_type = self._extract(device, "device_type")
        transport = self._extract(device, "transport")
        capabilities = self._extract_list(device, "capabilities")

        if not device_id:
            return

        worker_id = f"device-{device_id}"
        self._device_worker_map[device_id] = worker_id

        payload = {
            "worker_id": worker_id,
            "worker_type": "device",
            "device_id": device_id,
            "device_type": device_type,
            "transport": transport,
            "capabilities": capabilities,
            "registered_at": time.time(),
        }

        try:
            await self._nats.publish(self.SUBJ_WORKER_REGISTER, payload)
            logger.info("[DevWorker] Device %s registered as Worker %s", device_id, worker_id)
        except Exception as exc:
            logger.error("[DevWorker] Register failed for %s: %s", device_id, exc)

        # Publish capabilities separately
        if capabilities:
            try:
                await self._nats.publish(self.SUBJ_WORKER_CAPABILITIES, {
                    "worker_id": worker_id,
                    "capabilities": capabilities,
                })
            except Exception:
                pass

    async def on_device_heartbeat(self, device_id: str) -> None:
        """Called when a device sends a heartbeat.

        Emits the NATS Worker heartbeat so the Mesh scheduler
        knows the device is still alive.
        """
        if not self.is_available():
            return

        worker_id = self._device_worker_map.get(device_id)
        if not worker_id:
            # Unknown device → try to reconstruct worker_id
            worker_id = f"device-{device_id}"
            self._device_worker_map[device_id] = worker_id

        try:
            await self._nats.publish(self.SUBJ_WORKER_HEARTBEAT, {
                "worker_id": worker_id,
                "device_id": device_id,
                "timestamp": time.time(),
            })
            logger.debug("[DevWorker] Heartbeat | device=%s worker=%s", device_id, worker_id)
        except Exception as exc:
            logger.error("[DevWorker] Heartbeat failed for %s: %s", device_id, exc)

    async def on_device_unregistered(self, device_id: str) -> None:
        """Called when a device is removed from UDM."""
        if not self.is_available():
            return

        worker_id = self._device_worker_map.pop(device_id, None)
        if not worker_id:
            return

        try:
            await self._nats.publish(self.SUBJ_WORKER_SHUTDOWN, {
                "worker_id": worker_id,
                "device_id": device_id,
                "reason": "unregistered",
            })
            logger.info("[DevWorker] Device %s unregistered (worker %s)", device_id, worker_id)
        except Exception as exc:
            logger.error("[DevWorker] Shutdown failed for %s: %s", device_id, exc)

    # -- public: Mesh scheduling helpers --------------------------------------

    def get_worker_id(self, device_id: str) -> Optional[str]:
        """Return the NATS Worker ID for a device, if known."""
        return self._device_worker_map.get(device_id)

    def is_worker_registered(self, device_id: str) -> bool:
        """Check if a device has been registered as a NATS Worker."""
        return device_id in self._device_worker_map

    # -- internal helpers ----------------------------------------------------

    @staticmethod
    def _extract(device: Any, key: str) -> Optional[str]:
        if hasattr(device, key):
            val = getattr(device, key)
            return str(val) if val is not None else None
        if isinstance(device, dict):
            val = device.get(key)
            return str(val) if val is not None else None
        return None

    @staticmethod
    def _extract_list(device: Any, key: str) -> list:
        if hasattr(device, key):
            val = getattr(device, key)
            if isinstance(val, (list, tuple, set)):
                return [str(v) for v in val]
        if isinstance(device, dict):
            val = device.get(key)
            if isinstance(val, (list, tuple, set)):
                return [str(v) for v in val]
        return []


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_dwc_instance: Optional[DeviceWorkerConvergence] = None


def get_dwc(nats_bus: Optional[Any] = None) -> DeviceWorkerConvergence:
    """Return the module-level DeviceWorkerConvergence singleton."""
    global _dwc_instance
    if _dwc_instance is None:
        _dwc_instance = DeviceWorkerConvergence(nats_bus)
    elif nats_bus is not None:
        _dwc_instance._nats = nats_bus
    return _dwc_instance
