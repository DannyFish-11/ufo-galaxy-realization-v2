"""
tests/integration/test_android_v2_continuity_correctness_matrix.py
===================================================================

Android ↔ V2 continuity correctness validation baseline.

Failure matrix / scenario naming
--------------------------------
CC-01 normal_task_lifecycle_acceptance
CC-02 reconnect_after_dispatch_replay_buffer
CC-03 late_stale_completion_rejected
CC-04 duplicate_completion_suppressed
CC-05 reconnect_reconciliation_decision_visible
CC-06 long_running_reconnect_cycles_preserve_continuity

Fault-injection invariant matrix
--------------------------------
FI-01 delayed_completion
FI-02 reconnect_mid_flight
FI-03 replay_after_epoch_bump
FI-04 duplicate_terminal_uplink
FI-05 stale_pending_envelope_on_reconnect
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Minimal longevity smoke loop: enough cycles to cover repeated resume behavior
# without turning this correctness suite into a stress/performance test.
LONG_RUNNING_RECONNECT_CYCLES = 5

# Fault-injection failure matrix (deterministic scenarios only).
FAULT_INJECTION_FAILURE_MATRIX = (
    ("FI-01", "delayed_completion"),
    ("FI-02", "reconnect_mid_flight"),
    ("FI-03", "replay_after_epoch_bump"),
    ("FI-04", "duplicate_terminal_uplink"),
    ("FI-05", "stale_pending_envelope_on_reconnect"),
)


def _v3(msg_type: str, device_id: str, **extra: Any) -> Dict[str, Any]:
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.send = AsyncMock()
    return ws


def _reset_runtime_state() -> None:
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
        from core.durable_result_idempotency import reset_durable_result_id_store

        reset_durable_result_id_store()
    except Exception:
        pass

    try:
        from core.task_envelope_lifecycle_registry import reset_lifecycle_registry

        reset_lifecycle_registry()
    except Exception:
        pass


def _inject_pending_lifecycle_record(
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
        tool_name="continuity_validation",
        owner=LifecycleOwner(owner),
        timeout=timeout,
        registered_at=registered_at if registered_at is not None else time.time(),
        future=None,
        metadata={},
    )


def _make_ingress():
    from core.unified_result_ingress import UnifiedResultIngress

    ingress = UnifiedResultIngress()
    ingress._check_continuity_legality = lambda _e, mode: "allow"  # type: ignore[method-assign]
    ingress._run_truth_chain = lambda _e: True  # type: ignore[method-assign]
    ingress._sync_lifecycle = lambda _e: None  # type: ignore[method-assign]
    ingress._notify_completion = lambda _e: True  # type: ignore[method-assign]
    ingress._log_outcome = lambda _e, _o: None  # type: ignore[method-assign]
    return ingress


def _ingress_event(
    *,
    task_id: str,
    device_id: str,
    session_epoch: int | None,
    source_channel: str,
    idempotency_key: str,
    completion_emission_id: str,
) -> Any:
    from core.unified_result_ingress import NormalizedResultEvent, ResultSourceChannel

    payload = {
        "task_id": task_id,
        "status": "completed",
        "result": "ok",
        "completion_emission_id": completion_emission_id,
    }
    return NormalizedResultEvent(
        task_id=task_id,
        device_id=device_id,
        raw_message_type="goal_execution_result",
        normalized_result_kind="goal_execution_result",
        normalized_status="completed",
        source_channel=ResultSourceChannel(source_channel),
        payload=payload,
        raw_message={**payload, "type": "goal_execution_result"},
        session_epoch=session_epoch,
        idempotency_key=idempotency_key,
        completion_emission_id=completion_emission_id,
    )


def _registry_entry(epoch: int) -> Any:
    entry = MagicMock()
    entry.continuity_epoch = epoch
    return entry


@contextmanager
def _mock_idempotency_store():
    seen: set[str] = set()

    def _check(key: str) -> bool:
        return key in seen

    def _record(key: str) -> bool:
        if key in seen:
            return False
        seen.add(key)
        return True

    with patch(
        "core.durable_result_idempotency.check_result_idempotency",
        side_effect=_check,
    ), patch(
        "core.durable_result_idempotency.record_result_idempotency",
        side_effect=_record,
    ):
        yield seen


def _assert_invariant_stale_does_not_advance_closure(outcome: Any) -> None:
    assert outcome.stale_epoch_rejected is True
    assert outcome.completion_disposition == "stale_rejected"
    assert outcome.continuity_adjudication_classification == "stale-rejected"
    assert outcome.is_fully_closed is False


def _assert_invariant_duplicate_has_no_second_accepted_finalization(
    first: Any,
    duplicate: Any,
) -> None:
    assert first.completion_disposition == "first_accepted"
    assert first.continuity_adjudication_classification == "current-accepted"
    assert duplicate.was_deduplicated is True
    assert duplicate.completion_disposition == "duplicate_ignored"
    assert duplicate.continuity_adjudication_classification == "duplicate-ignored"
    assert duplicate.is_fully_closed is False


def _assert_invariant_replay_does_not_masquerade_current(outcome: Any) -> None:
    assert outcome.stale_epoch_rejected is True
    assert outcome.stale_classification == "replay_epoch_mismatch"
    assert outcome.continuity_adjudication_classification == "stale-rejected"
    assert outcome.is_fully_closed is False


def _assert_invariant_final_closed_not_resumed(ack: Dict[str, Any], *, task_id: str) -> None:
    from core.task_envelope_lifecycle_registry import get_lifecycle_registry

    decisions = {d["task_id"]: d for d in ack.get("pending_lifecycle_decisions", [])}
    assert decisions[task_id]["decision"] == "closure_already_decided"
    assert (
        decisions[task_id]["continuity_adjudication_classification"]
        == "abandoned-or-superseded"
    )
    assert not get_lifecycle_registry().is_pending(task_id)


class TestAndroidV2ContinuityCorrectnessMatrix:
    def setup_method(self) -> None:
        _reset_runtime_state()

    def teardown_method(self) -> None:
        _reset_runtime_state()

    @pytest.mark.asyncio
    async def test_CC01_normal_task_lifecycle_acceptance(self) -> None:
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()
        device_id = f"cc01-{uuid.uuid4().hex[:8]}"
        task_id = f"task-{uuid.uuid4().hex[:8]}"

        ack = await bridge.handle_message(
            ws,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=f"attach-{uuid.uuid4().hex[:8]}",
            ),
        )
        runtime_session_id = ack["runtime_session_id"]

        future = asyncio.get_running_loop().create_future()
        bridge._pending_responses[task_id] = future
        await bridge.handle_message(
            ws,
            _v3(
                "task_result",
                device_id,
                task_id=task_id,
                status="completed",
                schema_version="1",
                route_mode="local",
                session_id=runtime_session_id,
                payload={"result": {"value": "accepted"}},
            ),
        )

        assert future.done()
        result_payload = future.result()
        assert result_payload["task_id"] == task_id
        assert result_payload["status"] == "completed"

    @pytest.mark.asyncio
    async def test_CC02_reconnect_after_dispatch_replay_buffer(self) -> None:
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws1 = _make_ws()
        ws2 = _make_ws()
        device_id = f"cc02-{uuid.uuid4().hex[:8]}"
        attachment_id = f"attach-{uuid.uuid4().hex[:8]}"
        task_id = f"buffered-{uuid.uuid4().hex[:8]}"

        await bridge.handle_message(
            ws1,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        await bridge.disconnect_device(device_id)

        buffered = await bridge.send_to_device(
            device_id,
            _v3(
                "task_assign",
                device_id,
                task_id=task_id,
                payload={"task_type": "continuity_replay"},
            ),
        )
        assert buffered is not None
        assert buffered.get("buffered") is True

        ack2 = await bridge.handle_message(
            ws2,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        assert ack2["continuity_outcome"] == "continuity_resume"
        assert ack2["recovery_replay_scheduled"] is True
        assert ack2["recovery_replay_buffered_count"] == 1

        await asyncio.sleep(0.01)
        ws2.send_json.assert_awaited_once()
        replayed = ws2.send_json.await_args_list[0].args[0]
        assert replayed["type"] == "task_assign"
        assert replayed["task_id"] == task_id

    @pytest.mark.asyncio
    async def test_CC03_late_stale_completion_rejected(self, caplog: Any) -> None:
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()
        device_id = f"cc03-{uuid.uuid4().hex[:8]}"
        task_id = f"stale-{uuid.uuid4().hex[:8]}"

        ack = await bridge.handle_message(
            ws,
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=f"attach-{uuid.uuid4().hex[:8]}",
            ),
        )
        runtime_session_id = ack["runtime_session_id"]
        stale_message = _v3(
            "task_result",
            device_id,
            task_id=task_id,
            status="completed",
            schema_version="1",
            route_mode="local",
            session_id=runtime_session_id,
            is_stale=True,
            stale_reason="late_stale_completion_after_reconnect",
            payload={"result": {"value": "late_stale"}},
        )
        await bridge.handle_message(
            ws,
            stale_message,
        )

        assert "stale epoch gate blocked result" in caplog.text
        assert "explicit_stale" in caplog.text
        assert "late_stale_completion_after_reconnect" in caplog.text
        assert task_id not in bridge._pending_responses

    @pytest.mark.asyncio
    async def test_CC04_duplicate_completion_suppressed(self) -> None:
        from core.durable_result_idempotency import check_result_idempotency
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_ws()
        device_id = f"cc04-{uuid.uuid4().hex[:8]}"
        task_id = f"dup-{uuid.uuid4().hex[:8]}"

        await bridge.handle_message(
            ws,
            _v3("device_register", device_id, platform="android"),
        )

        first_future = asyncio.get_running_loop().create_future()
        bridge._pending_responses[task_id] = first_future
        await bridge.handle_message(
            ws,
            _v3("task_result", device_id, task_id=task_id, status="completed", schema_version="1"),
        )
        assert first_future.done()
        assert check_result_idempotency(task_id) is True

        second_future = asyncio.get_running_loop().create_future()
        bridge._pending_responses[task_id] = second_future
        await bridge.handle_message(
            ws,
            _v3("task_result", device_id, task_id=task_id, status="completed", schema_version="1"),
        )
        assert not second_future.done()
        assert bridge._pending_responses[task_id] is second_future

    @pytest.mark.asyncio
    async def test_CC05_reconnect_reconciliation_decision_visible(self) -> None:
        from galaxy_gateway.android_bridge import AndroidBridge

        device_id = f"cc05-{uuid.uuid4().hex[:8]}"
        attachment_id = f"attach-{uuid.uuid4().hex[:8]}"
        _inject_pending_lifecycle_record(
            task_id=f"routing-{uuid.uuid4().hex[:8]}",
            device_id=device_id,
            owner="routing",
        )

        bridge = AndroidBridge()
        ack = await bridge.handle_message(
            _make_ws(),
            _v3(
                "device_register",
                device_id,
                platform="android",
                runtime_attachment_session_id=attachment_id,
            ),
        )
        assert ack["pending_lifecycle_decision_count"] >= 1
        assert (
            ack["pending_lifecycle_decision_summary"].get("request_replay_reconciliation", 0)
            >= 1
        )
        assert (
            ack["continuity_adjudication_summary"].get(
                "replay-reconciliation-required", 0
            )
            >= 1
        )
        assert isinstance(ack.get("pending_lifecycle_decisions", []), list)

    @pytest.mark.asyncio
    async def test_CC06_long_running_reconnect_cycles_preserve_continuity(self) -> None:
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        device_id = f"cc06-{uuid.uuid4().hex[:8]}"
        attachment_id = f"attach-{uuid.uuid4().hex[:8]}"
        runtime_session_ids = []
        resolved_task_ids = []

        for idx in range(LONG_RUNNING_RECONNECT_CYCLES):
            ws = _make_ws()
            ack = await bridge.handle_message(
                ws,
                _v3(
                    "device_register",
                    device_id,
                    platform="android",
                    runtime_attachment_session_id=attachment_id,
                ),
            )
            runtime_session_ids.append(ack["runtime_session_id"])
            if idx > 0:
                assert ack["continuity_outcome"] == "continuity_resume"

            task_id = f"cycle-{idx}-{uuid.uuid4().hex[:8]}"
            future = asyncio.get_running_loop().create_future()
            bridge._pending_responses[task_id] = future
            await bridge.handle_message(
                ws,
                _v3(
                    "task_result",
                    device_id,
                    task_id=task_id,
                    status="completed",
                    schema_version="1",
                    session_id=ack["runtime_session_id"],
                ),
            )
            assert future.done()
            resolved_task_ids.append(future.result()["task_id"])
            await bridge.disconnect_device(device_id)

        assert len(set(runtime_session_ids)) == 1
        assert len(set(resolved_task_ids)) == LONG_RUNNING_RECONNECT_CYCLES

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("scenario_id", "failure_mode"),
        FAULT_INJECTION_FAILURE_MATRIX,
        ids=[f"{sid}_{mode}" for sid, mode in FAULT_INJECTION_FAILURE_MATRIX],
    )
    async def test_CCFI_fault_injection_matrix_enforces_continuity_invariants(
        self,
        scenario_id: str,
        failure_mode: str,
    ) -> None:
        if failure_mode == "delayed_completion":
            ingress = _make_ingress()
            task_id = f"{scenario_id}-task-{uuid.uuid4().hex[:8]}"
            device_id = f"{scenario_id}-dev-{uuid.uuid4().hex[:8]}"

            current = _ingress_event(
                task_id=task_id,
                device_id=device_id,
                session_epoch=4,
                source_channel="canonical_ws",
                idempotency_key=f"{task_id}:current",
                completion_emission_id=f"{task_id}:accepted",
            )
            delayed = _ingress_event(
                task_id=task_id,
                device_id=device_id,
                session_epoch=3,
                source_channel="canonical_ws",
                idempotency_key=f"{task_id}:late",
                completion_emission_id=f"{task_id}:late",
            )

            with _mock_idempotency_store(), patch(
                "core.attached_runtime_session_registry.lookup_session_by_device",
                return_value=_registry_entry(4),
            ):
                accepted_outcome = ingress.process(current)
                delayed_outcome = ingress.process(delayed)

            assert accepted_outcome.completion_disposition == "first_accepted"
            assert (
                accepted_outcome.continuity_adjudication_classification
                == "current-accepted"
            )
            _assert_invariant_stale_does_not_advance_closure(delayed_outcome)
            return

        if failure_mode == "reconnect_mid_flight":
            from galaxy_gateway.android_bridge import AndroidBridge

            bridge = AndroidBridge()
            ws1 = _make_ws()
            ws2 = _make_ws()
            device_id = f"{scenario_id}-dev-{uuid.uuid4().hex[:8]}"
            attachment_id = f"{scenario_id}-attach-{uuid.uuid4().hex[:8]}"
            task_id = f"{scenario_id}-task-{uuid.uuid4().hex[:8]}"

            await bridge.handle_message(
                ws1,
                _v3(
                    "device_register",
                    device_id,
                    platform="android",
                    runtime_attachment_session_id=attachment_id,
                ),
            )
            await bridge.disconnect_device(device_id)

            buffered = await bridge.send_to_device(
                device_id,
                _v3(
                    "task_assign",
                    device_id,
                    task_id=task_id,
                    payload={"task_type": "mid_flight_reconnect"},
                ),
            )
            assert buffered is not None
            assert buffered.get("buffered") is True

            reconnect_ack = await bridge.handle_message(
                ws2,
                _v3(
                    "device_register",
                    device_id,
                    platform="android",
                    runtime_attachment_session_id=attachment_id,
                ),
            )
            assert reconnect_ack["continuity_outcome"] == "continuity_resume"
            assert reconnect_ack["recovery_replay_scheduled"] is True
            assert reconnect_ack["recovery_replay_buffered_count"] == 1
            return

        if failure_mode == "replay_after_epoch_bump":
            ingress = _make_ingress()
            task_id = f"{scenario_id}-task-{uuid.uuid4().hex[:8]}"
            device_id = f"{scenario_id}-dev-{uuid.uuid4().hex[:8]}"
            replay_event = _ingress_event(
                task_id=task_id,
                device_id=device_id,
                session_epoch=7,
                source_channel="replay",
                idempotency_key=f"{task_id}:replay",
                completion_emission_id=f"{task_id}:replay",
            )

            with _mock_idempotency_store(), patch(
                "core.attached_runtime_session_registry.lookup_session_by_device",
                return_value=_registry_entry(8),
            ):
                replay_outcome = ingress.process(replay_event)

            _assert_invariant_replay_does_not_masquerade_current(replay_outcome)
            return

        if failure_mode == "duplicate_terminal_uplink":
            ingress = _make_ingress()
            task_id = f"{scenario_id}-task-{uuid.uuid4().hex[:8]}"
            device_id = f"{scenario_id}-dev-{uuid.uuid4().hex[:8]}"
            first_event = _ingress_event(
                task_id=task_id,
                device_id=device_id,
                session_epoch=9,
                source_channel="canonical_ws",
                idempotency_key=f"{task_id}:result-a",
                completion_emission_id=f"{task_id}:completion-a",
            )
            duplicate_event = _ingress_event(
                task_id=task_id,
                device_id=device_id,
                session_epoch=9,
                source_channel="canonical_ws",
                idempotency_key=f"{task_id}:result-a",
                completion_emission_id=f"{task_id}:completion-a",
            )

            with _mock_idempotency_store(), patch(
                "core.attached_runtime_session_registry.lookup_session_by_device",
                return_value=_registry_entry(9),
            ):
                first_outcome = ingress.process(first_event)
                duplicate_outcome = ingress.process(duplicate_event)

            _assert_invariant_duplicate_has_no_second_accepted_finalization(
                first_outcome,
                duplicate_outcome,
            )
            return

        if failure_mode == "stale_pending_envelope_on_reconnect":
            from core.attached_runtime_session_registry import register_session
            from core.task_envelope_lifecycle_registry import get_lifecycle_registry
            from galaxy_gateway.android_bridge import AndroidBridge

            device_id = f"{scenario_id}-dev-{uuid.uuid4().hex[:8]}"
            attachment_id = f"{scenario_id}-attach-{uuid.uuid4().hex[:8]}"
            stale_task_id = f"{scenario_id}-stale-{uuid.uuid4().hex[:8]}"
            closed_task_id = f"{scenario_id}-closed-{uuid.uuid4().hex[:8]}"

            register_session(
                device_id,
                posture="join_runtime",
                runtime_attachment_session_id=attachment_id,
            )
            _inject_pending_lifecycle_record(
                task_id=stale_task_id,
                device_id=device_id,
                owner="device_dispatch",
                timeout=1.0,
                registered_at=time.time() - 30.0,
            )
            _inject_pending_lifecycle_record(
                task_id=closed_task_id,
                device_id=device_id,
                owner="result_completion",
            )

            bridge = AndroidBridge()
            ack = await bridge.handle_message(
                _make_ws(),
                _v3(
                    "device_register",
                    device_id,
                    platform="android",
                    runtime_attachment_session_id=attachment_id,
                ),
            )

            assert ack["pending_lifecycle_decision_summary"]["mark_abandoned_stale"] == 1
            assert ack["continuity_adjudication_summary"]["abandoned-or-superseded"] >= 2
            _assert_invariant_final_closed_not_resumed(ack, task_id=closed_task_id)
            assert not get_lifecycle_registry().is_pending(stale_task_id)
            return

        raise AssertionError(f"Unhandled failure mode: {failure_mode}")
