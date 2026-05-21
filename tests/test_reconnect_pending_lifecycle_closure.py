from __future__ import annotations

import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest


def _reset_all() -> None:
    try:
        from core.unified import device_manager as _udm_mod

        _udm_mod.UnifiedDeviceManager._instance = None
    except Exception:
        pass

    try:
        from core.attached_runtime_session import reset_attached_runtime_session_runtime

        reset_attached_runtime_session_runtime()
    except Exception:
        pass

    try:
        from core.attached_runtime_session_registry import reset_session_registry

        reset_session_registry()
    except Exception:
        pass

    try:
        from core.task_envelope_lifecycle_registry import reset_lifecycle_registry

        reset_lifecycle_registry()
    except Exception:
        pass

    try:
        from core.mesh.body_mesh_registry import reset_body_mesh_registry

        reset_body_mesh_registry()
    except Exception:
        pass

    try:
        from galaxy_gateway.android.handlers.registration import clear_registration_gaps

        clear_registration_gaps()
    except Exception:
        pass

    try:
        from galaxy_gateway.device_router import device_router

        device_router.devices.clear()
    except Exception:
        pass


def _make_websocket() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


def _make_registration_message(
    device_id: str,
    *,
    runtime_attachment_session_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    from galaxy_gateway.android.capabilities import DeviceCapability

    msg: Dict[str, Any] = {
        "version": "3.0",
        "type": "device_register",
        "message_id": f"msg-{device_id}",
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "name": "Reconnect Test Phone",
        "model": "Pixel 7",
        "os_version": "14",
        "sdk_version": 34,
        "platform": "android",
        "device_type": "android_phone",
        "capabilities": DeviceCapability.get_android_default(),
        "runtime_attachment_session_id": runtime_attachment_session_id,
    }
    msg.update(overrides)
    return msg


def _inject_pending_record(
    *,
    task_id: str,
    device_id: str,
    owner: str,
    timeout: float = 30.0,
    registered_at: float | None = None,
) -> None:
    from core.task_envelope_lifecycle_registry import (
        LifecycleOwner,
        PendingEnvelopeRecord,
        get_lifecycle_registry,
    )

    registry = get_lifecycle_registry()
    registry._pending[task_id] = PendingEnvelopeRecord(
        task_id=task_id,
        trace_id=f"trace-{task_id}",
        target_device_id=device_id,
        tool_name="test_tool",
        owner=LifecycleOwner(owner),
        timeout=timeout,
        registered_at=registered_at if registered_at is not None else time.time(),
        future=None,
        metadata={},
    )


class TestReconnectPendingLifecycleClosure:
    def setup_method(self) -> None:
        _reset_all()

    def teardown_method(self) -> None:
        _reset_all()

    @pytest.mark.asyncio
    async def test_continuity_resume_surfaces_resume_decision_and_keeps_pending(self) -> None:
        from core.attached_runtime_session_registry import register_session
        from core.task_envelope_lifecycle_registry import (
            LifecycleOwner,
            get_lifecycle_registry,
        )
        from galaxy_gateway.android_bridge import AndroidBridge

        device_id = "reconnect-resume-dev"
        attachment_id = "attach-resume-1"
        register_session(
            device_id,
            posture="join_runtime",
            runtime_attachment_session_id=attachment_id,
        )
        _inject_pending_record(
            task_id="resume-task",
            device_id=device_id,
            owner="device_dispatch",
        )

        bridge = AndroidBridge()
        ack = await bridge._handle_device_register(
            _make_websocket(),
            _make_registration_message(
                device_id,
                runtime_attachment_session_id=attachment_id,
            ),
        )

        assert ack["continuity_outcome"] == "continuity_resume"
        assert ack["pending_lifecycle_decision_summary"]["resume_existing_execution"] == 1
        assert ack["continuity_adjudication_summary"]["reconnect-recovery-required"] == 1
        decision = ack["pending_lifecycle_decisions"][0]
        assert decision["task_id"] == "resume-task"
        assert decision["decision"] == "resume_existing_execution"
        assert decision["continuity_adjudication_classification"] == "reconnect-recovery-required"

        record = get_lifecycle_registry().get_record("resume-task")
        assert record is not None
        assert record.owner == LifecycleOwner.DEVICE_DISPATCH
        assert record.metadata["reconnect_lifecycle_decision"] == "resume_existing_execution"

    @pytest.mark.asyncio
    async def test_reconnect_does_not_resume_result_completion_pending_record(self) -> None:
        from core.attached_runtime_session_registry import register_session
        from core.task_envelope_lifecycle_registry import get_lifecycle_registry
        from galaxy_gateway.android_bridge import AndroidBridge

        device_id = "reconnect-closure-dev"
        attachment_id = "attach-closure-1"
        register_session(
            device_id,
            posture="join_runtime",
            runtime_attachment_session_id=attachment_id,
        )
        _inject_pending_record(
            task_id="closure-task",
            device_id=device_id,
            owner="result_completion",
        )

        bridge = AndroidBridge()
        ack = await bridge._handle_device_register(
            _make_websocket(),
            _make_registration_message(
                device_id,
                runtime_attachment_session_id=attachment_id,
            ),
        )

        assert ack["pending_lifecycle_decision_summary"]["closure_already_decided"] == 1
        assert ack["continuity_adjudication_summary"]["abandoned-or-superseded"] == 1
        decision = ack["pending_lifecycle_decisions"][0]
        assert decision["decision"] == "closure_already_decided"
        assert decision["continuity_adjudication_classification"] == "abandoned-or-superseded"
        assert not get_lifecycle_registry().is_pending("closure-task")

    @pytest.mark.asyncio
    async def test_stale_pending_envelope_is_abandoned_instead_of_resumed(self) -> None:
        from core.attached_runtime_session_registry import register_session
        from core.task_envelope_lifecycle_registry import get_lifecycle_registry
        from galaxy_gateway.android_bridge import AndroidBridge

        device_id = "reconnect-stale-dev"
        attachment_id = "attach-stale-1"
        register_session(
            device_id,
            posture="join_runtime",
            runtime_attachment_session_id=attachment_id,
        )
        _inject_pending_record(
            task_id="stale-task",
            device_id=device_id,
            owner="device_dispatch",
            timeout=1.0,
            registered_at=time.time() - 30.0,
        )

        bridge = AndroidBridge()
        ack = await bridge._handle_device_register(
            _make_websocket(),
            _make_registration_message(
                device_id,
                runtime_attachment_session_id=attachment_id,
            ),
        )

        assert ack["pending_lifecycle_decision_summary"]["mark_abandoned_stale"] == 1
        assert ack["continuity_adjudication_summary"]["abandoned-or-superseded"] == 1
        decision = ack["pending_lifecycle_decisions"][0]
        assert decision["decision"] == "mark_abandoned_stale"
        assert decision["continuity_adjudication_classification"] == "abandoned-or-superseded"
        assert not get_lifecycle_registry().is_pending("stale-task")

    @pytest.mark.asyncio
    async def test_reconnect_makes_mixed_resume_replay_and_failover_decisions(self) -> None:
        from core.attached_runtime_session_registry import register_session
        from core.task_envelope_lifecycle_registry import (
            LifecycleOwner,
            get_lifecycle_registry,
        )
        from galaxy_gateway.android_bridge import AndroidBridge

        device_id = "reconnect-mixed-dev"
        attachment_id = "attach-mixed-1"
        register_session(
            device_id,
            posture="join_runtime",
            runtime_attachment_session_id=attachment_id,
        )
        _inject_pending_record(
            task_id="mixed-resume-task",
            device_id=device_id,
            owner="device_dispatch",
        )
        _inject_pending_record(
            task_id="mixed-routing-task",
            device_id=device_id,
            owner="routing",
        )
        _inject_pending_record(
            task_id="mixed-ingress-task",
            device_id=device_id,
            owner="gateway_ingress",
        )

        bridge = AndroidBridge()
        ack = await bridge._handle_device_register(
            _make_websocket(),
            _make_registration_message(
                device_id,
                runtime_attachment_session_id=attachment_id,
            ),
        )

        summary = ack["pending_lifecycle_decision_summary"]
        assert summary["resume_existing_execution"] == 1
        assert summary["request_replay_reconciliation"] == 1
        assert summary["trigger_failover"] == 1
        cls_summary = ack["continuity_adjudication_summary"]
        assert cls_summary["reconnect-recovery-required"] == 1
        assert cls_summary["replay-reconciliation-required"] == 1
        assert cls_summary["abandoned-or-superseded"] == 1

        registry = get_lifecycle_registry()
        assert registry.get_record("mixed-resume-task") is not None
        assert registry.get_record("mixed-resume-task").owner == LifecycleOwner.DEVICE_DISPATCH
        assert not registry.is_pending("mixed-routing-task")
        assert not registry.is_pending("mixed-ingress-task")

    def test_canonical_ingress_and_reconnect_share_unified_classification_vocabulary(self) -> None:
        from core.unified_result_ingress import UnifiedResultIngress

        ingress = UnifiedResultIngress()
        ingress._check_continuity_legality = lambda e, mode: "allow"  # type: ignore[method-assign]
        ingress._check_idempotency = lambda e: False  # type: ignore[method-assign]
        ingress._record_idempotency = lambda e: None  # type: ignore[method-assign]
        ingress._run_truth_chain = lambda e: True  # type: ignore[method-assign]
        ingress._sync_lifecycle = lambda e: None  # type: ignore[method-assign]
        ingress._notify_completion = lambda e: True  # type: ignore[method-assign]
        ingress._log_outcome = lambda e, o: None  # type: ignore[method-assign]

        from core.unified_result_ingress import NormalizedResultEvent, ResultSourceChannel

        event = NormalizedResultEvent(
            task_id="same-vocab-task",
            device_id="same-vocab-device",
            raw_message_type="goal_execution_result",
            normalized_result_kind="goal_execution_result",
            normalized_status="completed",
            source_channel=ResultSourceChannel.CANONICAL_WS,
            payload={"task_id": "same-vocab-task", "status": "completed"},
            idempotency_key="same-vocab-task",
        )
        outcome = ingress.process(event)
        assert outcome.continuity_adjudication_classification == "current-accepted"
