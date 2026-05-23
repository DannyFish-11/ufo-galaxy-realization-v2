"""
tests/test_pr46_schema_version_gate_runtime_enforcement.py

PR-46: Cross-repo schema/version gate runtime enforcement tests.

Validates that:
1. Key Android/V2 runtime uplink handlers enforce schema/version gate.
2. Schema/version mismatches are rejected or degraded (not silently processed).
3. Messages with matching schema/version proceed normally.

Covered uplink types:
- completion/closure: handoff_result, handoff_failure, handoff_envelope_v2_result
- result/task outcome: task_result, goal_execution_result, goal_result
- runtime/device snapshot: device_state_snapshot, device_execution_event
- continuity/reconciliation: reconciliation_signal
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from contracts.cross_repo_schema_version_gate import (
    ANDROID_COMPLETION_CLOSURE_CONTRACT_VERSION,
    ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
    STRICT_ANDROID_UPLINK_SCHEMA_GATE_MESSAGE_TYPES,
    COMPAT_ANDROID_UPLINK_SCHEMA_GATE_MESSAGE_TYPES,
    evaluate_android_uplink_schema_gate,
)

# ---------------------------------------------------------------------------
# Gate module: task_result is now in the strict set
# ---------------------------------------------------------------------------


class TestGateModuleTaskResultStrict:
    def test_task_result_in_strict_gate_message_types(self) -> None:
        assert "task_result" in STRICT_ANDROID_UPLINK_SCHEMA_GATE_MESSAGE_TYPES

    def test_task_result_not_in_compat_set(self) -> None:
        assert "task_result" not in COMPAT_ANDROID_UPLINK_SCHEMA_GATE_MESSAGE_TYPES

    def test_task_result_missing_schema_version_degrades_when_legacy_safe_identity_present(self) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type="task_result",
            message={"type": "task_result", "task_id": "t1", "status": "success"},
        )
        assert decision is not None
        assert decision.action == "degrade"
        assert decision.original_action == "reject"
        assert decision.reason == "legacy_task_result_missing_schema_version_compat"

    def test_task_result_missing_schema_version_rejected_without_terminal_status(self) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type="task_result",
            message={"type": "task_result", "task_id": "t1"},
        )
        assert decision is not None
        assert decision.action == "reject"
        assert decision.reason == "missing_schema_version_metadata"

    def test_task_result_old_schema_version_rejected(self) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type="task_result",
            message={
                "type": "task_result",
                "task_id": "t1",
                "schema_version": "0",
            },
        )
        assert decision is not None
        # strict mode: version "0" is in legacy set but STRICT mode doesn't degrade
        # — it rejects anything not matching.
        assert decision.action == "reject"

    def test_task_result_matching_schema_version_accepted(self) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type="task_result",
            message={
                "type": "task_result",
                "task_id": "t1",
                "schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
            },
        )
        assert decision is not None
        assert decision.action == "accept"
        assert decision.reason == "schema_version_gate_matched"


# ---------------------------------------------------------------------------
# Gate module: completion/closure types strict enforcement
# ---------------------------------------------------------------------------


class TestGateModuleCompletionClosureStrict:
    @pytest.mark.parametrize(
        "msg_type",
        [
            "handoff_result",
            "handoff_failure",
            "handoff_envelope_v2_result",
            "goal_execution_result",
            "goal_result",
        ],
    )
    def test_strict_type_missing_schema_rejected(self, msg_type: str) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type=msg_type,
            message={"type": msg_type},
        )
        assert decision is not None
        assert decision.action == "reject"
        assert decision.reason == "missing_schema_version_metadata"

    def test_completion_closure_contract_mismatch_rejected(self) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type="handoff_envelope_v2_result",
            message={
                "type": "handoff_envelope_v2_result",
                "payload": {
                    "schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
                    "completion_closure_contract_version": "0",
                },
            },
        )
        assert decision is not None
        assert decision.action == "reject"
        assert decision.reason == "completion_closure_contract_mismatch"

    def test_handoff_result_missing_contract_version_rejected(self) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type="handoff_result",
            message={
                "type": "handoff_result",
                "payload": {
                    "schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
                },
            },
        )
        assert decision is not None
        assert decision.action == "reject"
        assert decision.reason == "missing_completion_closure_contract_version"

    def test_handoff_result_valid_passes(self) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type="handoff_result",
            message={
                "type": "handoff_result",
                "payload": {
                    "schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
                    "completion_closure_contract_version": ANDROID_COMPLETION_CLOSURE_CONTRACT_VERSION,
                },
            },
        )
        assert decision is not None
        assert decision.action == "accept"


# ---------------------------------------------------------------------------
# Gate module: compat types degrade on old version
# ---------------------------------------------------------------------------


class TestGateModuleCompatTypes:
    @pytest.mark.parametrize(
        "msg_type",
        [
            "device_state_snapshot",
            "device_execution_event",
            "reconciliation_signal",
        ],
    )
    def test_compat_type_missing_schema_degrades(self, msg_type: str) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type=msg_type,
            message={"type": msg_type},
        )
        assert decision is not None
        assert decision.action == "degrade"
        assert decision.reason == "missing_schema_version_metadata"

    @pytest.mark.parametrize(
        "msg_type",
        [
            "device_state_snapshot",
            "device_execution_event",
            "reconciliation_signal",
        ],
    )
    def test_compat_type_old_schema_degrades(self, msg_type: str) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type=msg_type,
            message={
                "type": msg_type,
                "payload": {"schema_version": "0"},
            },
        )
        assert decision is not None
        assert decision.action == "degrade"

    @pytest.mark.parametrize(
        "msg_type",
        [
            "device_state_snapshot",
            "device_execution_event",
            "reconciliation_signal",
        ],
    )
    def test_compat_type_matching_schema_accepts(self, msg_type: str) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type=msg_type,
            message={
                "type": msg_type,
                "payload": {"schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION},
            },
        )
        assert decision is not None
        assert decision.action == "accept"

    def test_unknown_message_type_returns_none(self) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type="some_unknown_type",
            message={"type": "some_unknown_type"},
        )
        assert decision is None


# ---------------------------------------------------------------------------
# Handler: handoff_v2_result — gate wired to reject mismatches
# ---------------------------------------------------------------------------


def _make_bridge() -> MagicMock:
    bridge = MagicMock()
    bridge._devices = {}
    bridge._pending_responses = {}
    bridge._lock = asyncio.Lock()
    return bridge


def _make_websocket() -> MagicMock:
    return MagicMock()


class TestHandoffV2ResultGateEnforcement:
    def _run(self, coro: Any) -> Any:
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_handoff_result_missing_schema_version_rejected(self) -> None:
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        message = {
            "type": "handoff_result",
            "device_id": "dev1",
            "message_id": "msg1",
            "payload": {},
        }
        result = self._run(handle_handoff_v2_result(_make_bridge(), _make_websocket(), message))
        assert result is not None
        assert result.get("schema_gate_rejected") is True
        assert result.get("schema_gate_reason") == "missing_schema_version_metadata"
        assert "schema_gate_evidence" in result

    def test_handoff_failure_missing_schema_version_rejected(self) -> None:
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        message = {
            "type": "handoff_failure",
            "device_id": "dev1",
            "message_id": "msg2",
            "payload": {},
        }
        result = self._run(handle_handoff_v2_result(_make_bridge(), _make_websocket(), message))
        assert result is not None
        assert result.get("schema_gate_rejected") is True

    def test_handoff_envelope_v2_result_contract_mismatch_rejected(self) -> None:
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        message = {
            "type": "handoff_envelope_v2_result",
            "device_id": "dev1",
            "message_id": "msg3",
            "payload": {
                "schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
                "completion_closure_contract_version": "0",
            },
        }
        result = self._run(handle_handoff_v2_result(_make_bridge(), _make_websocket(), message))
        assert result is not None
        assert result.get("schema_gate_rejected") is True
        assert result.get("schema_gate_reason") == "completion_closure_contract_mismatch"

    def test_handoff_ack_not_gated_proceeds(self) -> None:
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        # handoff_ack is not in the gate sets — should reach ingress without rejection
        message = {
            "type": "handoff_ack",
            "device_id": "dev1",
            "message_id": "msg4",
            "payload": {},
        }
        with patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response",
            return_value=MagicMock(was_correlated=False, reject_reason="no_registry", envelope=None),
        ):
            result = self._run(handle_handoff_v2_result(_make_bridge(), _make_websocket(), message))
        assert result is not None
        assert result.get("schema_gate_rejected") is not True

    def test_handoff_result_valid_schema_not_rejected(self) -> None:
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        message = {
            "type": "handoff_result",
            "device_id": "dev1",
            "message_id": "msg5",
            "payload": {
                "schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
                "completion_closure_contract_version": ANDROID_COMPLETION_CLOSURE_CONTRACT_VERSION,
            },
        }
        with patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response",
            return_value=MagicMock(was_correlated=False, reject_reason="no_registry", envelope=None),
        ):
            result = self._run(handle_handoff_v2_result(_make_bridge(), _make_websocket(), message))
        assert result is not None
        assert result.get("schema_gate_rejected") is not True


# ---------------------------------------------------------------------------
# Handler: task_lifecycle — handle_task_result gate enforcement
# ---------------------------------------------------------------------------


class TestTaskResultGateEnforcement:
    def _run(self, coro: Any) -> Any:
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_task_result_missing_schema_version_degrades_to_truth_chain(self) -> None:
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_result

        bridge = _make_bridge()
        message = {
            "type": "task_result",
            "task_id": "task1",
            "device_id": "dev1",
            "status": "success",
        }
        # Should return early (None) when schema gate rejects — truth chain
        # must never be called.
        truth_chain_called = []

        def _fake_truth_chain(msg: Any, *, task_id: Any, result_status: Any) -> Any:
            truth_chain_called.append(True)
            return MagicMock(is_truth_chain_complete=True)

        with patch(
            "galaxy_gateway.android.handlers.task_lifecycle._run_task_result_truth_chain",
            _fake_truth_chain,
        ):
            self._run(handle_task_result(bridge, _make_websocket(), message))

        assert truth_chain_called
        evidence = message.get("_cross_repo_schema_version_gate")
        assert isinstance(evidence, dict)
        assert evidence.get("action") == "degrade"
        assert evidence.get("original_action") == "reject"
        assert evidence.get("reason") == "legacy_task_result_missing_schema_version_compat"

    def test_task_result_old_schema_blocked(self) -> None:
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_result

        bridge = _make_bridge()
        message = {
            "type": "task_result",
            "task_id": "task2",
            "device_id": "dev1",
            "status": "success",
            "schema_version": "0",
        }
        truth_chain_called = []

        def _fake_truth_chain(msg: Any, *, task_id: Any, result_status: Any) -> Any:
            truth_chain_called.append(True)
            return MagicMock(is_truth_chain_complete=True)

        with patch(
            "galaxy_gateway.android.handlers.task_lifecycle._run_task_result_truth_chain",
            _fake_truth_chain,
        ):
            self._run(handle_task_result(bridge, _make_websocket(), message))

        # strict reject: "0" is in legacy set but STRICT doesn't degrade → reject
        # truth chain must not have been called
        assert not truth_chain_called

    def test_task_result_matching_schema_proceeds(self) -> None:
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_result

        bridge = _make_bridge()
        message = {
            "type": "task_result",
            "task_id": "task3",
            "device_id": "dev1",
            "status": "success",
            "schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
        }
        truth_chain_called = []

        def _fake_truth_chain(msg: Any, *, task_id: Any, result_status: Any) -> Any:
            truth_chain_called.append(True)
            return MagicMock(is_truth_chain_complete=True)

        # Patch the durable idempotency check to always allow (avoid disk state
        # from previous test runs interfering with the schema gate test).
        with (
            patch(
                "galaxy_gateway.android.handlers.task_lifecycle._run_task_result_truth_chain",
                _fake_truth_chain,
            ),
            patch(
                "core.durable_result_idempotency.check_result_idempotency",
                return_value=False,
            ),
            patch(
                "core.durable_result_idempotency.record_result_idempotency",
                return_value=None,
            ),
        ):
            self._run(handle_task_result(bridge, _make_websocket(), message))

        # matching schema version: truth chain should run
        assert truth_chain_called


# ---------------------------------------------------------------------------
# Handler: device_state_snapshot — gate evidence in ACK for mismatches
# ---------------------------------------------------------------------------


class TestDeviceStateSnapshotGateEnforcement:
    def _run(self, coro: Any) -> Any:
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_snapshot_missing_schema_version_includes_evidence_in_ack(self) -> None:
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_state_snapshot,
        )

        bridge = _make_bridge()
        message = {
            "type": "device_state_snapshot",
            "device_id": "dev1",
            "message_id": "msg1",
            "payload": {},
        }
        # Run the handler; whether or not the store import succeeds the ACK
        # should always be returned with schema_gate_evidence attached.
        result = self._run(handle_device_state_snapshot(bridge, _make_websocket(), message))

        # COMPAT mode: gate mismatch should not block — ACK still returned
        assert result is not None
        assert result.get("type") == "device_state_snapshot_ack"
        # gate evidence should be present since schema was missing
        assert result.get("schema_gate_evidence") is not None
        evidence = result["schema_gate_evidence"]
        assert evidence.get("action") == "degrade"
        assert evidence.get("reason") == "missing_schema_version_metadata"

    def test_snapshot_old_schema_includes_evidence_in_ack(self) -> None:
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_state_snapshot,
        )

        bridge = _make_bridge()
        message = {
            "type": "device_state_snapshot",
            "device_id": "dev1",
            "message_id": "msg2",
            "payload": {"schema_version": "0"},
        }
        result = self._run(handle_device_state_snapshot(bridge, _make_websocket(), message))

        assert result is not None
        assert result.get("schema_gate_evidence") is not None
        assert result["schema_gate_evidence"]["action"] == "degrade"

    def test_snapshot_valid_schema_no_gate_evidence(self) -> None:
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_state_snapshot,
        )

        bridge = _make_bridge()
        message = {
            "type": "device_state_snapshot",
            "device_id": "dev1",
            "message_id": "msg3",
            "payload": {"schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION},
        }
        result = self._run(handle_device_state_snapshot(bridge, _make_websocket(), message))

        assert result is not None
        # No gate evidence for accepted messages
        assert result.get("schema_gate_evidence") is None


# ---------------------------------------------------------------------------
# Handler: reconciliation_signal — gate evidence in ACK for mismatches
# ---------------------------------------------------------------------------


class TestReconciliationSignalGateEnforcement:
    def _run(self, coro: Any) -> Any:
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_reconciliation_signal_missing_schema_includes_evidence(self) -> None:
        from galaxy_gateway.android.handlers.reconciliation_signal import (
            handle_reconciliation_signal,
        )

        bridge = _make_bridge()
        message = {
            "type": "reconciliation_signal",
            "device_id": "dev1",
            "message_id": "msg1",
            "payload": {},
        }
        with patch(
            "galaxy_gateway.android.handlers.reconciliation_signal._get_lifecycle_coordinator",
            None,
        ):
            result = self._run(handle_reconciliation_signal(bridge, _make_websocket(), message))

        assert result is not None
        assert result.get("type") == "reconciliation_signal_ack"
        assert result.get("schema_gate_evidence") is not None
        evidence = result["schema_gate_evidence"]
        assert evidence.get("action") == "degrade"
        assert evidence.get("reason") == "missing_schema_version_metadata"

    def test_reconciliation_signal_old_android_version_degrades_with_evidence(self) -> None:
        from galaxy_gateway.android.handlers.reconciliation_signal import (
            handle_reconciliation_signal,
        )

        bridge = _make_bridge()
        message = {
            "type": "reconciliation_signal",
            "device_id": "dev1",
            "message_id": "msg2",
            "payload": {"schema_version": "0"},
        }
        with patch(
            "galaxy_gateway.android.handlers.reconciliation_signal._get_lifecycle_coordinator",
            None,
        ):
            result = self._run(handle_reconciliation_signal(bridge, _make_websocket(), message))

        assert result is not None
        assert result.get("schema_gate_evidence") is not None
        assert result["schema_gate_evidence"]["action"] == "degrade"

    def test_reconciliation_signal_valid_schema_no_evidence(self) -> None:
        from galaxy_gateway.android.handlers.reconciliation_signal import (
            handle_reconciliation_signal,
        )

        bridge = _make_bridge()
        message = {
            "type": "reconciliation_signal",
            "device_id": "dev1",
            "message_id": "msg3",
            "payload": {"schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION},
        }
        with patch(
            "galaxy_gateway.android.handlers.reconciliation_signal._get_lifecycle_coordinator",
            None,
        ):
            result = self._run(handle_reconciliation_signal(bridge, _make_websocket(), message))

        assert result is not None
        assert result.get("schema_gate_evidence") is None


# ---------------------------------------------------------------------------
# Handler: goal_execution_result — gate wired to reject mismatches
# ---------------------------------------------------------------------------


class TestGoalExecutionResultGateEnforcement:
    def _run(self, coro: Any) -> Any:
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_goal_execution_result_missing_schema_degrades_to_truth_chain(self) -> None:
        from galaxy_gateway.android.handlers.goal_execution import handle_goal_execution_result

        bridge = _make_bridge()
        message = {
            "type": "goal_execution_result",
            "device_id": "dev1",
            "payload": {
                "task_id": "ger1",
                "status": "success",
            },
        }
        ingress_calls = []

        async def _fake_ingest_async(event: Any, *, store_fn: Any = None, bridge: Any = None) -> Any:
            ingress_calls.append((event.task_id, event.normalized_status))
            return MagicMock(
                is_fully_closed=False,
                was_deduplicated=False,
                truth_chain_complete=True,
                incomplete_reason="completion_not_notified",
                evidence_acceptance_verdict="degrade",
                evidence_trust_level="legacy_compat",
                task_completed=True,
                problem_solved=False,
                completion_notified=False,
                pending_response_resolved=False,
                dedupe_contract_action="degrade",
                dedupe_contract_reason="legacy_goal_execution_result_missing_schema_version_compat",
            )

        with (
            patch(
                "core.unified_result_ingress.ingest_result_async",
                side_effect=_fake_ingest_async,
            ),
            patch(
                "core.durable_result_idempotency.check_result_idempotency",
                return_value=False,
            ),
        ):
            self._run(handle_goal_execution_result(bridge, _make_websocket(), message))

        assert ingress_calls == [("ger1", "completed")]
        evidence = message.get("_cross_repo_schema_version_gate")
        assert isinstance(evidence, dict)
        assert evidence.get("action") == "degrade"
        assert evidence.get("original_action") == "reject"
        assert evidence.get("reason") == "legacy_goal_execution_result_missing_schema_version_compat"

    def test_goal_execution_result_old_android_version_blocked(self) -> None:
        from galaxy_gateway.android.handlers.goal_execution import handle_goal_execution_result

        bridge = _make_bridge()
        message = {
            "type": "goal_execution_result",
            "device_id": "dev1",
            "schema_version": "0",
            "payload": {
                "task_id": "ger2",
                "status": "success",
            },
        }
        truth_chain_called = []

        def _fake_truth_chain(msg: Any, *, task_id: Any, result_status: Any) -> Any:
            truth_chain_called.append(True)
            return MagicMock(is_truth_chain_complete=True)

        with patch(
            "galaxy_gateway.android.handlers.goal_execution._run_task_result_truth_chain",
            _fake_truth_chain,
        ):
            self._run(handle_goal_execution_result(bridge, _make_websocket(), message))

        # strict mode: "0" gets rejected even though it's a legacy version
        assert not truth_chain_called

    def test_goal_execution_result_matching_schema_proceeds(self) -> None:
        from galaxy_gateway.android.handlers.goal_execution import handle_goal_execution_result

        bridge = _make_bridge()
        message = {
            "type": "goal_execution_result",
            "device_id": "dev1",
            "schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
            "payload": {
                "task_id": "ger3",
                "status": "success",
            },
        }
        # For a message that passes the schema gate, the handler should proceed
        # to the full processing pipeline (durable idempotency, ingress, etc.)
        # rather than returning early.  We verify this by checking that no
        # schema_gate_rejected key appears (that field is only set on early exits
        # from handoff_v2_result, but for goal_execution_result which returns None
        # we use a sentinel to detect early-gate exit).
        gate_rejected = []

        _orig_gate = None
        import contracts.cross_repo_schema_version_gate as _gate_mod

        _orig_evaluate = _gate_mod.evaluate_android_uplink_schema_gate

        def _spy_gate(*, message_type: str, message: Any) -> Any:
            decision = _orig_evaluate(message_type=message_type, message=message)
            if decision is not None and decision.action == "reject":
                gate_rejected.append(decision)
            return decision

        with (
            patch.object(_gate_mod, "evaluate_android_uplink_schema_gate", _spy_gate),
            patch(
                "galaxy_gateway.android.handlers.goal_execution.store_task_result",
                None,
            ),
        ):
            self._run(handle_goal_execution_result(bridge, _make_websocket(), message))

        # matching schema: gate should NOT have rejected this message
        assert not gate_rejected


# ---------------------------------------------------------------------------
# Gate decision to_dict contains required evidence fields
# ---------------------------------------------------------------------------


class TestGateDecisionEvidenceStructure:
    def test_reject_decision_to_dict_has_gate_metadata(self) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type="handoff_result",
            message={"type": "handoff_result"},
        )
        assert decision is not None
        d = decision.to_dict()
        assert "action" in d
        assert "reason" in d
        assert "evidence" in d
        assert "authority" in d
        assert "gate_version" in d
        assert d["action"] == "reject"

    def test_degrade_decision_to_dict_has_gate_metadata(self) -> None:
        decision = evaluate_android_uplink_schema_gate(
            message_type="reconciliation_signal",
            message={"type": "reconciliation_signal"},
        )
        assert decision is not None
        d = decision.to_dict()
        assert d["action"] == "degrade"
        assert "authority" in d
        assert "gate_version" in d
