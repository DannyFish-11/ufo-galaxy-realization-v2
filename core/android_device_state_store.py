"""
core/android_device_state_store.py
=====================================
Canonical V2-side store for Android→V2 control-plane state projections.

This module receives and stores two canonical message types that Android
devices emit to the V2 control plane:

DEVICE_STATE_SNAPSHOT
    A structured snapshot of the complete Android device runtime state,
    covering native runtime availability (llamaCpp/NCNN), readiness state,
    model/runtime identity, local-loop config, offline queue depth, fallback
    ladder tier, and runtime health.  Stored per device_id; the most recent
    snapshot is always available for operator queries.

DEVICE_EXECUTION_EVENT
    A structured event emitted during delegated execution on Android,
    carrying flow_id, task_id, phase, step_index, blocking state, and other
    execution-phase truth.  Absorbed into FlowLevelOperatorSurface so the
    V2 operator plane can observe live cross-device execution.

Authority
---------
ANDROID_DEVICE_STATE_STORE_AUTHORITY is the canonical storage authority for
Android runtime truth on the V2 side.  Operator endpoints that need per-device
Android state MUST read from this store, not from raw device_communication
payloads.

Public API
----------
Functions::

    absorb_device_state_snapshot(device_id, payload) -> None
    absorb_device_execution_event(device_id, payload) -> None
    get_device_state_snapshot(device_id) -> Optional[DeviceStateSnapshot]
    list_device_state_snapshots() -> List[DeviceStateSnapshot]
    get_device_ecosystem_summary() -> Dict[str, Any]

Dataclasses::

    DeviceStateSnapshot
    DeviceExecutionEvent
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.AndroidDeviceStateStore")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

ANDROID_DEVICE_STATE_STORE_AUTHORITY: str = (
    "ANDROID_DEVICE_STATE_STORE_V1: "
    "core.android_device_state_store is the canonical V2-side store for "
    "Android runtime truth projected via DEVICE_STATE_SNAPSHOT and "
    "DEVICE_EXECUTION_EVENT messages.  All operator/control-plane surfaces "
    "that expose Android device state MUST read from this store."
)

DEVICE_STATE_SNAPSHOT_MSG_TYPE: str = "device_state_snapshot"
DEVICE_EXECUTION_EVENT_MSG_TYPE: str = "device_execution_event"


# ---------------------------------------------------------------------------
# DeviceStateSnapshot
# ---------------------------------------------------------------------------


@dataclass
class DeviceStateSnapshot:
    """Canonical V2-side projection of Android device runtime state.

    Populated from DEVICE_STATE_SNAPSHOT messages emitted by Android devices.
    All fields are optional — absent fields reflect that the Android side did
    not include that truth in the most recent snapshot.

    Attributes
    ----------
    device_id
        Identity of the Android device.
    absorbed_at
        Unix timestamp when V2 absorbed this snapshot.
    snapshot_ts
        Optional Unix timestamp from the Android device itself.

    Native runtime availability
    ---------------------------
    llama_cpp_available
        Whether libllama.so loaded successfully on the device.
    ncnn_available
        Whether libncnn.so loaded successfully on the device.
    active_runtime_type
        Current inference runtime in use (e.g. ``"LLAMA_CPP"``, ``"NCNN"``,
        ``"CENTER"``, ``"HYBRID"``).

    Readiness state
    ---------------
    model_ready
        Whether the local model is ready for inference.
    accessibility_ready
        Whether the Android Accessibility Service is active and ready.
    overlay_ready
        Whether the overlay (floating window) permission is granted and active.
    local_loop_ready
        Whether the full local loop (plan/ground/act) is ready.
    degraded_reasons
        List of human-readable reasons why the device is degraded, if any.

    Model identity
    --------------
    model_id
        Canonical model identifier (e.g. ``"mobilevlm_v2_7b"``).
    runtime_type
        Model runtime type string (e.g. ``"LLAMA_CPP"``, ``"NCNN"``).
    checksum_ok
        Whether the model checksum passed verification.
    compatibility_ok
        Whether the model is compatible with this runtime version.
    quantization
        Quantization type string (e.g. ``"q4_k_m"``), if known.
    model_version
        Model version string, if known.
    mobilevlm_present
        Whether the MobileVLM model file exists on device.
    mobilevlm_checksum_ok
        Whether the MobileVLM checksum passed.
    seeclick_present
        Whether the SeeClick model files are present.
    pending_first_download
        Whether the device is still waiting for the initial model download.

    Local loop config
    -----------------
    local_loop_config
        Active ``LocalLoopConfig`` dict as reported by the Android device.

    Runtime health
    --------------
    runtime_health_snapshot
        ``RuntimeHealthSnapshot`` dict as reported by the Android device.
    warmup_result
        Warmup result string (``"ok"``, ``"failed"``, ``"skipped"``, etc.).

    Queue / fallback state
    ----------------------
    offline_queue_depth
        Number of pending tasks in the device's offline queue.
    current_fallback_tier
        Current fallback ladder tier string (e.g. ``"planner_local"``,
        ``"center_delegated"``).
    planner_fallback_tier
        Current PlannerFallbackLadder active tier.
    grounding_fallback_tier
        Current GroundingFallbackLadder active tier.

    Extra
    -----
    raw_payload
        The original payload dict from the DEVICE_STATE_SNAPSHOT message,
        preserved for audit / forward-compat purposes.
    """

    device_id: str = ""
    absorbed_at: float = field(default_factory=time.time)
    snapshot_ts: Optional[float] = None

    # Native runtime availability
    llama_cpp_available: Optional[bool] = None
    ncnn_available: Optional[bool] = None
    active_runtime_type: Optional[str] = None

    # Readiness state
    model_ready: Optional[bool] = None
    accessibility_ready: Optional[bool] = None
    overlay_ready: Optional[bool] = None
    local_loop_ready: Optional[bool] = None
    degraded_reasons: List[str] = field(default_factory=list)

    # Model identity
    model_id: Optional[str] = None
    runtime_type: Optional[str] = None
    checksum_ok: Optional[bool] = None
    compatibility_ok: Optional[bool] = None
    quantization: Optional[str] = None
    model_version: Optional[str] = None
    mobilevlm_present: Optional[bool] = None
    mobilevlm_checksum_ok: Optional[bool] = None
    seeclick_present: Optional[bool] = None
    pending_first_download: Optional[bool] = None

    # Local loop config
    local_loop_config: Optional[Dict[str, Any]] = None

    # Runtime health
    runtime_health_snapshot: Optional[Dict[str, Any]] = None
    warmup_result: Optional[str] = None

    # Queue / fallback
    offline_queue_depth: Optional[int] = None
    current_fallback_tier: Optional[str] = None
    planner_fallback_tier: Optional[str] = None
    grounding_fallback_tier: Optional[str] = None

    # Raw payload
    raw_payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "device_id": self.device_id,
            "absorbed_at": self.absorbed_at,
            "snapshot_ts": self.snapshot_ts,
            "llama_cpp_available": self.llama_cpp_available,
            "ncnn_available": self.ncnn_available,
            "active_runtime_type": self.active_runtime_type,
            "model_ready": self.model_ready,
            "accessibility_ready": self.accessibility_ready,
            "overlay_ready": self.overlay_ready,
            "local_loop_ready": self.local_loop_ready,
            "degraded_reasons": list(self.degraded_reasons),
            "model_id": self.model_id,
            "runtime_type": self.runtime_type,
            "checksum_ok": self.checksum_ok,
            "compatibility_ok": self.compatibility_ok,
            "quantization": self.quantization,
            "model_version": self.model_version,
            "mobilevlm_present": self.mobilevlm_present,
            "mobilevlm_checksum_ok": self.mobilevlm_checksum_ok,
            "seeclick_present": self.seeclick_present,
            "pending_first_download": self.pending_first_download,
            "local_loop_config": self.local_loop_config,
            "runtime_health_snapshot": self.runtime_health_snapshot,
            "warmup_result": self.warmup_result,
            "offline_queue_depth": self.offline_queue_depth,
            "current_fallback_tier": self.current_fallback_tier,
            "planner_fallback_tier": self.planner_fallback_tier,
            "grounding_fallback_tier": self.grounding_fallback_tier,
        }

    def is_local_ai_ready(self) -> bool:
        """Return True when local AI inference is available and ready."""
        return bool(
            self.local_loop_ready
            and self.model_ready
            and (self.llama_cpp_available or self.ncnn_available)
        )

    def readiness_summary(self) -> Dict[str, Any]:
        """Return a compact readiness summary dict."""
        return {
            "model_ready": self.model_ready,
            "accessibility_ready": self.accessibility_ready,
            "overlay_ready": self.overlay_ready,
            "local_loop_ready": self.local_loop_ready,
            "local_ai_ready": self.is_local_ai_ready(),
            "llama_cpp_available": self.llama_cpp_available,
            "ncnn_available": self.ncnn_available,
            "pending_first_download": self.pending_first_download,
            "degraded_reasons": list(self.degraded_reasons),
        }


# ---------------------------------------------------------------------------
# DeviceExecutionEvent
# ---------------------------------------------------------------------------


@dataclass
class DeviceExecutionEvent:
    """A single structured execution event emitted by Android during a delegated flow.

    Populated from DEVICE_EXECUTION_EVENT messages.  These events are
    absorbed into :class:`~core.flow_level_operator_surface.FlowLevelOperatorSurface`
    so the V2 operator plane can observe live cross-device execution state.

    Attributes
    ----------
    device_id
        The Android device that emitted this event.
    absorbed_at
        Unix timestamp when V2 absorbed this event.
    flow_id
        Delegated flow id this event belongs to.
    task_id
        Task id associated with this execution step.
    phase
        Execution phase string (planning / grounding / execution / replan /
        stagnation / gate_decision / completed / failed / …).
    step_index
        Zero-based step index within the current loop, or -1 if unknown.
    is_blocking
        Whether this event represents a blocking condition.
    blocking_reason
        Human-readable reason for blocking, if is_blocking is True.
    stagnation_detected
        Whether stagnation was detected at this step.
    fallback_tier
        Fallback tier active at time of this event, if any.
    raw_payload
        Original payload dict for audit / forward-compat.
    """

    device_id: str = ""
    absorbed_at: float = field(default_factory=time.time)
    flow_id: str = ""
    task_id: str = ""
    phase: str = "unknown"
    step_index: int = -1
    is_blocking: bool = False
    blocking_reason: str = ""
    stagnation_detected: bool = False
    fallback_tier: Optional[str] = None
    raw_payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "device_id": self.device_id,
            "absorbed_at": self.absorbed_at,
            "flow_id": self.flow_id,
            "task_id": self.task_id,
            "phase": self.phase,
            "step_index": self.step_index,
            "is_blocking": self.is_blocking,
            "blocking_reason": self.blocking_reason,
            "stagnation_detected": self.stagnation_detected,
            "fallback_tier": self.fallback_tier,
        }


# ---------------------------------------------------------------------------
# In-process store
# ---------------------------------------------------------------------------


class _AndroidDeviceStateStore:
    """In-process singleton store for Android device state snapshots and execution events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Latest snapshot per device_id
        self._snapshots: Dict[str, DeviceStateSnapshot] = {}
        # Recent execution events (capped at _MAX_EVENTS)
        self._execution_events: List[DeviceExecutionEvent] = []
        self._MAX_EVENTS = 500

    # ------------------------------------------------------------------
    # Ingress: absorb DEVICE_STATE_SNAPSHOT payloads
    # ------------------------------------------------------------------

    def absorb_state_snapshot(self, device_id: str, payload: Dict[str, Any]) -> DeviceStateSnapshot:
        """Parse and store a DEVICE_STATE_SNAPSHOT payload for *device_id*.

        The most recent snapshot per device_id is retained.  Returns the
        parsed :class:`DeviceStateSnapshot` for caller inspection.
        """
        snap = _parse_state_snapshot(device_id, payload)
        with self._lock:
            self._snapshots[device_id] = snap
        logger.debug(
            "Absorbed DEVICE_STATE_SNAPSHOT from %s (local_loop_ready=%s, model_ready=%s)",
            device_id,
            snap.local_loop_ready,
            snap.model_ready,
        )
        return snap

    # ------------------------------------------------------------------
    # Ingress: absorb DEVICE_EXECUTION_EVENT payloads
    # ------------------------------------------------------------------

    def absorb_execution_event(self, device_id: str, payload: Dict[str, Any]) -> DeviceExecutionEvent:
        """Parse and store a DEVICE_EXECUTION_EVENT payload.

        Also attempts to forward the event to FlowLevelOperatorSurface for
        live cross-device flow visibility.  Returns the parsed event.
        """
        evt = _parse_execution_event(device_id, payload)
        with self._lock:
            self._execution_events.append(evt)
            if len(self._execution_events) > self._MAX_EVENTS:
                self._execution_events = self._execution_events[-self._MAX_EVENTS:]

        # Forward to FlowLevelOperatorSurface
        if evt.flow_id:
            _forward_execution_event_to_flow_surface(evt)

        logger.debug(
            "Absorbed DEVICE_EXECUTION_EVENT from %s (flow=%s, phase=%s, step=%d)",
            device_id,
            evt.flow_id,
            evt.phase,
            evt.step_index,
        )
        return evt

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_snapshot(self, device_id: str) -> Optional[DeviceStateSnapshot]:
        """Return the latest snapshot for *device_id*, or None."""
        with self._lock:
            return self._snapshots.get(device_id)

    def list_snapshots(self) -> List[DeviceStateSnapshot]:
        """Return all current device snapshots (one per device_id)."""
        with self._lock:
            return list(self._snapshots.values())

    def list_recent_execution_events(
        self,
        flow_id: Optional[str] = None,
        device_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[DeviceExecutionEvent]:
        """Return recent execution events, optionally filtered by flow_id / device_id."""
        with self._lock:
            events = list(reversed(self._execution_events))
        if flow_id:
            events = [e for e in events if e.flow_id == flow_id]
        if device_id:
            events = [e for e in events if e.device_id == device_id]
        return events[:limit]

    def get_ecosystem_summary(self) -> Dict[str, Any]:
        """Return a structured multi-device ecosystem summary for operator views."""
        with self._lock:
            snapshots = list(self._snapshots.values())

        total = len(snapshots)
        local_ai_ready = sum(1 for s in snapshots if s.is_local_ai_ready())
        model_ready = sum(1 for s in snapshots if s.model_ready)
        accessibility_ready = sum(1 for s in snapshots if s.accessibility_ready)
        overlay_ready = sum(1 for s in snapshots if s.overlay_ready)
        local_loop_ready = sum(1 for s in snapshots if s.local_loop_ready)
        pending_download = sum(1 for s in snapshots if s.pending_first_download)

        devices: List[Dict[str, Any]] = []
        for snap in snapshots:
            devices.append({
                "device_id": snap.device_id,
                "absorbed_at": snap.absorbed_at,
                "snapshot_ts": snap.snapshot_ts,
                "readiness": snap.readiness_summary(),
                "model": {
                    "model_id": snap.model_id,
                    "runtime_type": snap.runtime_type,
                    "checksum_ok": snap.checksum_ok,
                    "compatibility_ok": snap.compatibility_ok,
                    "quantization": snap.quantization,
                    "model_version": snap.model_version,
                },
                "active_runtime_type": snap.active_runtime_type,
                "offline_queue_depth": snap.offline_queue_depth,
                "current_fallback_tier": snap.current_fallback_tier,
                "planner_fallback_tier": snap.planner_fallback_tier,
                "grounding_fallback_tier": snap.grounding_fallback_tier,
                "warmup_result": snap.warmup_result,
            })

        return {
            "total_devices_with_snapshot": total,
            "local_ai_ready_count": local_ai_ready,
            "model_ready_count": model_ready,
            "accessibility_ready_count": accessibility_ready,
            "overlay_ready_count": overlay_ready,
            "local_loop_ready_count": local_loop_ready,
            "pending_first_download_count": pending_download,
            "devices": devices,
        }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_state_snapshot(device_id: str, payload: Dict[str, Any]) -> DeviceStateSnapshot:
    """Build a DeviceStateSnapshot from a raw DEVICE_STATE_SNAPSHOT payload dict."""

    def _bool(key: str, default=None) -> Optional[bool]:
        v = payload.get(key, default)
        if v is None:
            return None
        return bool(v)

    def _int(key: str, default=None) -> Optional[int]:
        v = payload.get(key, default)
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    def _str(key: str, default=None) -> Optional[str]:
        v = payload.get(key, default)
        return str(v) if v is not None else None

    def _list(key: str) -> List[str]:
        v = payload.get(key)
        if isinstance(v, list):
            return [str(x) for x in v]
        return []

    def _first_bool(*keys: str) -> Optional[bool]:
        """Return the first non-None bool value from the given keys."""
        for k in keys:
            if k in payload:
                v = payload[k]
                return bool(v)
        return None

    def _first_str(*keys: str) -> Optional[str]:
        """Return the first non-None str value from the given keys."""
        for k in keys:
            if k in payload and payload[k] is not None:
                return str(payload[k])
        return None

    def _first_int(*keys: str) -> Optional[int]:
        """Return the first non-None int value from the given keys."""
        for k in keys:
            if k in payload and payload[k] is not None:
                try:
                    return int(payload[k])
                except (TypeError, ValueError):
                    pass
        return None

    def _first_list(*keys: str) -> List[str]:
        """Return the first non-empty list value from the given keys."""
        for k in keys:
            v = payload.get(k)
            if isinstance(v, list):
                return [str(x) for x in v]
        return []

    return DeviceStateSnapshot(
        device_id=device_id,
        absorbed_at=time.time(),
        snapshot_ts=payload.get("snapshot_ts") or payload.get("timestamp"),
        # Native runtime
        llama_cpp_available=_first_bool("llama_cpp_available", "llamaCppAvailable"),
        ncnn_available=_first_bool("ncnn_available", "ncnnAvailable"),
        active_runtime_type=_first_str("active_runtime_type", "activeRuntimeType"),
        # Readiness
        model_ready=_first_bool("model_ready", "modelReady"),
        accessibility_ready=_first_bool("accessibility_ready", "accessibilityReady"),
        overlay_ready=_first_bool("overlay_ready", "overlayReady"),
        local_loop_ready=_first_bool("local_loop_ready", "localLoopReady"),
        degraded_reasons=_first_list("degraded_reasons", "degradedReasons"),
        # Model identity
        model_id=_first_str("model_id", "modelId"),
        runtime_type=_first_str("runtime_type", "runtimeType"),
        checksum_ok=_first_bool("checksum_ok", "checksumOk"),
        compatibility_ok=_first_bool("compatibility_ok", "compatibilityOk"),
        quantization=_first_str("quantization"),
        model_version=_first_str("model_version", "modelVersion"),
        mobilevlm_present=_first_bool("mobilevlm_present", "mobilevlmPresent"),
        mobilevlm_checksum_ok=_first_bool("mobilevlm_checksum_ok", "mobilevlmChecksumOk"),
        seeclick_present=_first_bool("seeclick_present", "seeclickPresent"),
        pending_first_download=_first_bool("pending_first_download", "pendingFirstDownload"),
        # Local loop config
        local_loop_config=(
            payload.get("local_loop_config")
            or payload.get("localLoopConfig")
        ),
        # Runtime health
        runtime_health_snapshot=(
            payload.get("runtime_health_snapshot")
            or payload.get("runtimeHealthSnapshot")
        ),
        warmup_result=_first_str("warmup_result", "warmupResult"),
        # Queue / fallback
        offline_queue_depth=_first_int("offline_queue_depth", "offlineQueueDepth"),
        current_fallback_tier=_first_str("current_fallback_tier", "currentFallbackTier"),
        planner_fallback_tier=_first_str("planner_fallback_tier", "plannerFallbackTier"),
        grounding_fallback_tier=_first_str("grounding_fallback_tier", "groundingFallbackTier"),
        raw_payload=dict(payload),
    )


def _parse_execution_event(device_id: str, payload: Dict[str, Any]) -> DeviceExecutionEvent:
    """Build a DeviceExecutionEvent from a raw DEVICE_EXECUTION_EVENT payload dict."""
    return DeviceExecutionEvent(
        device_id=device_id,
        absorbed_at=time.time(),
        flow_id=payload.get("flow_id") or payload.get("flowId") or "",
        task_id=payload.get("task_id") or payload.get("taskId") or "",
        phase=payload.get("phase") or "unknown",
        step_index=int(payload.get("step_index", payload.get("stepIndex", -1))),
        is_blocking=bool(payload.get("is_blocking") or payload.get("isBlocking")),
        blocking_reason=payload.get("blocking_reason") or payload.get("blockingReason") or "",
        stagnation_detected=bool(
            payload.get("stagnation_detected") or payload.get("stagnationDetected")
        ),
        fallback_tier=payload.get("fallback_tier") or payload.get("fallbackTier"),
        raw_payload=dict(payload),
    )


def _forward_execution_event_to_flow_surface(evt: DeviceExecutionEvent) -> None:
    """Attempt to forward execution event to FlowLevelOperatorSurface.

    Absorbs the event as an AndroidCanonicalExecutionEvent so that
    FlowLevelOperatorSurface can reflect live Android execution state.
    Failures are logged and swallowed — this is a best-effort path.
    """
    try:
        from core.flow_level_operator_surface import (
            AndroidCanonicalExecutionEvent,
            AndroidExecutionPhase,
            get_flow_level_operator_surface,
        )
        from core.delegated_flow_entity import get_delegated_flow_entity_runtime

        runtime = get_delegated_flow_entity_runtime()
        entity = runtime.get(evt.flow_id)
        if entity is None:
            return  # Flow not known to V2 — nothing to update

        surface = get_flow_level_operator_surface()
        ace = AndroidCanonicalExecutionEvent(
            flow_id=evt.flow_id,
            phase=AndroidExecutionPhase.from_string(evt.phase),
            step_index=evt.step_index,
            detail=evt.blocking_reason or f"phase={evt.phase}",
            is_blocking=evt.is_blocking,
            blocking_reason=evt.blocking_reason,
            android_ts=evt.absorbed_at,
            evidence={
                "device_id": evt.device_id,
                "task_id": evt.task_id,
                "stagnation_detected": evt.stagnation_detected,
                "fallback_tier": evt.fallback_tier,
                "source": "DEVICE_EXECUTION_EVENT",
            },
        )

        # Store on the flow entity's metadata for operator surface projection
        # by setting last_android_execution_event via entity metadata update.
        try:
            entity.metadata["_last_android_execution_event"] = ace.to_dict()
            entity.metadata["_last_android_phase"] = evt.phase
            entity.metadata["_last_android_event_absorbed_at"] = evt.absorbed_at
        except Exception:
            pass

    except Exception as exc:
        logger.debug("Failed to forward execution event to flow surface: %s", exc)


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_store_instance: Optional[_AndroidDeviceStateStore] = None
_store_lock = threading.Lock()


def get_android_device_state_store() -> _AndroidDeviceStateStore:
    """Return the process-level singleton AndroidDeviceStateStore."""
    global _store_instance
    if _store_instance is None:
        with _store_lock:
            if _store_instance is None:
                _store_instance = _AndroidDeviceStateStore()
    return _store_instance


def reset_android_device_state_store() -> None:
    """Reset the singleton (for test isolation only)."""
    global _store_instance
    with _store_lock:
        _store_instance = None


# ---------------------------------------------------------------------------
# Convenience entry points (called from device_communication.py routing)
# ---------------------------------------------------------------------------


def absorb_device_state_snapshot(device_id: str, payload: Dict[str, Any]) -> DeviceStateSnapshot:
    """Absorb a DEVICE_STATE_SNAPSHOT payload.  Convenience wrapper."""
    return get_android_device_state_store().absorb_state_snapshot(device_id, payload)


def absorb_device_execution_event(device_id: str, payload: Dict[str, Any]) -> DeviceExecutionEvent:
    """Absorb a DEVICE_EXECUTION_EVENT payload.  Convenience wrapper."""
    return get_android_device_state_store().absorb_execution_event(device_id, payload)


def get_device_state_snapshot(device_id: str) -> Optional[DeviceStateSnapshot]:
    """Return the latest snapshot for *device_id*.  Convenience wrapper."""
    return get_android_device_state_store().get_snapshot(device_id)


def list_device_state_snapshots() -> List[DeviceStateSnapshot]:
    """Return all current device snapshots.  Convenience wrapper."""
    return get_android_device_state_store().list_snapshots()


def get_device_ecosystem_summary() -> Dict[str, Any]:
    """Return multi-device ecosystem summary.  Convenience wrapper."""
    return get_android_device_state_store().get_ecosystem_summary()
