"""
galaxy_gateway/android/handlers/device_state_snapshot.py
=========================================================
PR-RT: Android Runtime-State Transparency Uplink Handlers.

Handles two Android→V2 uplink message types that carry structured runtime-state
projections from the Android side into the V2 control plane:

DEVICE_STATE_SNAPSHOT (``MessageType.DEVICE_STATE_SNAPSHOT``)
    A periodic snapshot of the complete Android device runtime state, covering:
    * native runtime availability (llamaCpp / NCNN)
    * active inference runtime type
    * model identity, runtime type, checksum
    * readiness state (model_ready, accessibility_ready, overlay_ready)
    * local-loop configuration
    * offline queue depth / replay state
    * fallback ladder tier
    * warmup result / runtime health score

DEVICE_EXECUTION_EVENT (``MessageType.DEVICE_EXECUTION_EVENT``)
    A per-step execution phase event emitted during delegated execution on the
    Android side, carrying: flow_id, task_id, phase, step_index, blocking_state,
    blocking_reason, and timing metadata.

Both handlers delegate immediately to :mod:`core.android_device_state_store`
and return a structured ACK to the Android device.

Authority
---------
These handlers are the **canonical gateway ingress** for Android runtime-state
transparency data.  After this module absorbs the message, the data is
available at:

* ``GET /api/v1/operator/devices/ecosystem`` — multi-device snapshot summary
* ``GET /api/v1/operator/devices/ecosystem/{device_id}`` — per-device snapshot
* ``GET /api/v1/operator/devices/execution-events`` — recent execution events
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)

_EXECUTION_TERMINAL_PHASES = frozenset(
    {
        "completed",
        "failed",
        "stagnation",
        "gate_decision",
        "cancelled",
        "timeout",
        "timed_out",
        "terminal_success",
        "terminal_failure",
        "terminal_cancelled",
    }
)
_EXECUTION_ACTIVE_PHASES = frozenset(
    {
        "planning",
        "grounding",
        "execution",
        "replan",
        "in_progress",
    }
)


def _normalize_phase(value: Any) -> str:
    return str(value or "").strip().lower()


async def handle_device_state_snapshot(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Handle inbound ``device_state_snapshot`` message (PR-RT).

    Absorbs the Android device runtime-state snapshot into
    :mod:`core.android_device_state_store` and returns a structured ACK.

    Parameters
    ----------
    bridge:
        The :class:`~galaxy_gateway.android_bridge.AndroidBridge` instance.
    websocket:
        The WebSocket connection (unused; reserved for future use).
    message:
        Raw inbound ``device_state_snapshot`` AIP v3 message dict.

    Returns
    -------
    dict
        ACK response dict sent back to the Android device.
    """
    device_id = message.get("device_id", "unknown")
    message_id = message.get("message_id") or str(uuid.uuid4())
    payload = message.get("payload") or {}

    status = "absorbed"
    reconciliation_status = "unknown"
    applied_to_canonical_truth = False
    canonical_conflict = False
    participation_tier = None
    try:
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            get_device_snapshot_reconciliation,
        )
        snap = absorb_device_state_snapshot(device_id, payload)
        reconciliation = get_device_snapshot_reconciliation(device_id)
        reconciliation_status = str(reconciliation.get("status", "unknown"))
        applied_to_canonical_truth = bool(reconciliation.get("applied", False))
        canonical_conflict = bool(reconciliation.get("conflict", False))
        logger.debug(
            "device_state_snapshot absorbed: device_id=%s model_ready=%s "
            "active_runtime=%s fallback_tier=%s reconciliation_status=%s applied=%s",
            device_id,
            snap.model_ready,
            snap.active_runtime_type,
            snap.current_fallback_tier,
            reconciliation_status,
            applied_to_canonical_truth,
        )
        try:
            from core.android_network_participation import (  # noqa: PLC0415
                AndroidParticipationTransitionSignal,
                refresh_participation_state_from_runtime,
            )

            readiness_signal = (
                AndroidParticipationTransitionSignal.readiness_satisfied
                if (
                    bool(snap.model_ready)
                    and bool(snap.accessibility_ready)
                    and bool(snap.local_loop_ready)
                )
                else AndroidParticipationTransitionSignal.readiness_lost
            )
            participation_state = refresh_participation_state_from_runtime(
                device_id,
                signal=readiness_signal,
            )
            participation_tier = participation_state.tier.value
        except Exception as participation_exc:
            logger.debug(
                "device_state_snapshot: participation refresh non-fatal: device_id=%s error=%s",
                device_id,
                participation_exc,
            )

        # 统一设备生命周期状态：就绪信号更新生命周期阶段（ready 或回退到 connected）。
        try:
            from core.device_lifecycle_state import (  # noqa: PLC0415
                transition_device_lifecycle,
                DeviceLifecycleTransitionEvent,
            )
            from core.android_mode_gate_policy import evaluate_android_mode_readiness  # noqa: PLC0415
            _all_ready = (
                bool(snap.model_ready)
                and bool(snap.accessibility_ready)
                and bool(snap.local_loop_ready)
            )
            _mode_gate = evaluate_android_mode_readiness(device_id)
            _dispatch_gate_passed = bool(getattr(_mode_gate, "is_dispatch_eligible", False))
            _takeover_eligible = bool(getattr(_mode_gate, "is_takeover_eligible", False))
            _lc_snapshot_event = (
                DeviceLifecycleTransitionEvent.readiness_satisfied
                if _all_ready
                else DeviceLifecycleTransitionEvent.readiness_lost
            )
            transition_device_lifecycle(
                device_id,
                _lc_snapshot_event,
                readiness_satisfied=_all_ready,
                dispatch_gate_passed=_dispatch_gate_passed,
            )
            transition_device_lifecycle(
                device_id,
                (
                    DeviceLifecycleTransitionEvent.takeover_eligibility_gained
                    if _takeover_eligible
                    else DeviceLifecycleTransitionEvent.takeover_eligibility_lost
                ),
                takeover_eligible=_takeover_eligible,
            )
        except Exception as _lc_snap_exc:
            logger.debug(
                "device_state_snapshot: device_lifecycle transition non-fatal: "
                "device_id=%s error=%s",
                device_id, _lc_snap_exc,
            )
    except ImportError:
        logger.error(
            "device_state_snapshot: core.android_device_state_store not available; snapshot from %s discarded",
            device_id,
        )
        status = "error"
    except Exception as exc:
        logger.warning(
            "Failed to absorb device_state_snapshot from %s: %s",
            device_id, exc,
        )
        status = "error"

    return {
        "type": "device_state_snapshot_ack",
        "device_id": device_id,
        "status": status,
        "correlation_id": message_id,
        "reconciliation_status": reconciliation_status,
        "applied_to_canonical_truth": applied_to_canonical_truth,
        "canonical_conflict": canonical_conflict,
        "network_participation_tier": participation_tier,
    }


async def handle_device_execution_event(
    bridge: "AndroidBridge",
    websocket: Any,
    message: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Handle inbound ``device_execution_event`` message (PR-RT).

    Absorbs the Android execution phase event into
    :mod:`core.android_device_state_store` (which also forwards to
    :class:`~core.flow_level_operator_surface.FlowLevelOperatorSurface` when
    the event carries a ``flow_id``) and returns a structured ACK.

    Parameters
    ----------
    bridge:
        The :class:`~galaxy_gateway.android_bridge.AndroidBridge` instance.
    websocket:
        The WebSocket connection (unused; reserved for future use).
    message:
        Raw inbound ``device_execution_event`` AIP v3 message dict.

    Returns
    -------
    dict
        ACK response dict sent back to the Android device.
    """
    device_id = message.get("device_id", "unknown")
    message_id = message.get("message_id") or str(uuid.uuid4())
    payload = message.get("payload") or {}

    status = "absorbed"
    try:
        from core.android_device_state_store import absorb_device_execution_event
        from core.device_lifecycle_state import (
            transition_device_lifecycle,
            DeviceLifecycleTransitionEvent,
        )
        from core.android_network_participation import (
            refresh_participation_state_from_runtime,
            AndroidParticipationTransitionSignal,
        )
        evt = absorb_device_execution_event(device_id, payload)
        _phase = _normalize_phase(getattr(evt, "phase", ""))
        if _phase in _EXECUTION_ACTIVE_PHASES:
            transition_device_lifecycle(
                device_id,
                DeviceLifecycleTransitionEvent.execution_session_started,
                execution_active=True,
            )
            refresh_participation_state_from_runtime(
                device_id,
                signal=AndroidParticipationTransitionSignal.execution_session_started,
            )
        elif _phase in _EXECUTION_TERMINAL_PHASES:
            transition_device_lifecycle(
                device_id,
                DeviceLifecycleTransitionEvent.execution_session_ended,
                execution_active=False,
            )
            refresh_participation_state_from_runtime(
                device_id,
                signal=AndroidParticipationTransitionSignal.execution_session_ended,
            )
        else:
            logger.debug(
                "device_execution_event phase ignored for lifecycle transition: "
                "device_id=%s phase=%r",
                device_id,
                _phase,
            )
        logger.debug(
            "device_execution_event absorbed: device_id=%s flow=%s phase=%s step=%d",
            device_id,
            evt.flow_id,
            evt.phase,
            evt.step_index,
        )
    except ImportError:
        logger.error(
            "device_execution_event: core.android_device_state_store not available; "
            "event from %s discarded",
            device_id,
        )
        status = "error"
    except Exception as exc:
        logger.warning(
            "Failed to absorb device_execution_event from %s: %s",
            device_id, exc,
        )
        status = "error"

    return {
        "type": "device_execution_event_ack",
        "device_id": device_id,
        "status": status,
        "correlation_id": message_id,
    }
