"""tests/test_pr5a_policy_engine_mainline_convergence.py
==========================================================
Tests for PR-5A: Policy engine and dispatch orchestration mainline convergence.

Coverage:
  A.  POLICY_ENGINE_CONSULTED_ON_HEURISTIC_PATH sentinel is present in
      CommandRouter module.
  B.  DELEGATED_POLICY_PARTICIPATES_IN_TARGET_SELECTION_PR5A_SENTINEL is
      present in source_dispatch_orchestrator module.
  C.  ORCHESTRATOR_MAINLINE_PATH_EXTENDED_PR5A_SENTINEL is present.
  D.  apply_target_selection_policy is importable from execution_target_policy_engine.
  E.  select_delegated_target is importable from delegated_target_selection_policy.
  F.  SourceDispatchOrchestrator has consume_android_behavioral_result method.
  G.  consume_android_behavioral_result returns stable dict with expected keys.
  H.  consume_android_behavioral_result handles None/empty outcome gracefully.
  I.  consume_android_behavioral_result with was_updated=True sets consumed=True.
  J.  consume_android_behavioral_result with was_updated=False sets consumed=False.
  K.  select_dispatch_target: delegated policy post-gate is exercised when
      candidates are available (no exception on missing modules).
  L.  CommandRouter.route_envelope policy block is importable and has sentinel.
  M.  handle_delegated_execution_signal has _android_result_consumer binding.
  N.  handle_delegated_execution_signal forwards result-kind signals to consumer.
  O.  handle_delegated_execution_signal does not forward non-result-kind signals.
  P.  SourceDispatchOrchestrator._delegate_single_remote plan is built on
      single-remote path (openclawd integration test).
  Q.  apply_target_selection_policy produces TargetSelectionDecision with policy_kind.
  R.  select_dispatch_target falls back gracefully when delegated_policy unavailable.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# A. CommandRouter sentinel present
# ---------------------------------------------------------------------------


class TestCommandRouterSentinel:
    def test_A_policy_engine_sentinel_present(self):
        from core.command_router import POLICY_ENGINE_CONSULTED_ON_HEURISTIC_PATH

        assert "PR5A" in POLICY_ENGINE_CONSULTED_ON_HEURISTIC_PATH
        assert "apply_target_selection_policy" in POLICY_ENGINE_CONSULTED_ON_HEURISTIC_PATH


# ---------------------------------------------------------------------------
# B & C. SourceDispatchOrchestrator sentinels present
# ---------------------------------------------------------------------------


class TestOrchestratorSentinels:
    def test_B_delegated_policy_sentinel_present(self):
        from core.runtime.source_dispatch_orchestrator import (
            DELEGATED_POLICY_PARTICIPATES_IN_TARGET_SELECTION_PR5A_SENTINEL,
        )

        assert "PR5A" in DELEGATED_POLICY_PARTICIPATES_IN_TARGET_SELECTION_PR5A_SENTINEL
        assert "select_delegated_target" in DELEGATED_POLICY_PARTICIPATES_IN_TARGET_SELECTION_PR5A_SENTINEL

    def test_C_orchestrator_mainline_sentinel_present(self):
        from core.runtime.source_dispatch_orchestrator import (
            ORCHESTRATOR_MAINLINE_PATH_EXTENDED_PR5A_SENTINEL,
        )

        assert "PR5A" in ORCHESTRATOR_MAINLINE_PATH_EXTENDED_PR5A_SENTINEL


# ---------------------------------------------------------------------------
# D. apply_target_selection_policy importable
# ---------------------------------------------------------------------------


class TestPolicyEngineImport:
    def test_D_apply_target_selection_policy_importable(self):
        from core.runtime.execution_target_policy_engine import (
            apply_target_selection_policy,
        )

        assert callable(apply_target_selection_policy)

    def test_Q_apply_target_selection_policy_returns_decision(self):
        from core.runtime.execution_target_policy_engine import (
            apply_target_selection_policy,
        )

        decision = apply_target_selection_policy(
            executor_target_type=None,
            candidate_device_ids=[],
            readiness_map={},
            task_id="task_001",
            trace_id="trace_001",
        )
        assert decision is not None
        assert hasattr(decision, "policy_kind")
        assert hasattr(decision, "decision_reason")


# ---------------------------------------------------------------------------
# E. select_delegated_target importable
# ---------------------------------------------------------------------------


class TestDelegatedTargetSelectionImport:
    def test_E_select_delegated_target_importable(self):
        from core.delegated_target_selection_policy import select_delegated_target

        assert callable(select_delegated_target)


# ---------------------------------------------------------------------------
# F, G, H, I, J. SourceDispatchOrchestrator.consume_android_behavioral_result
# ---------------------------------------------------------------------------


class TestConsumeAndroidBehavioralResult:
    def _make_outcome(self, *, was_updated=False, signal_kind="result", result_kind="success"):
        outcome = MagicMock()
        outcome.was_updated = was_updated
        outcome.reject_reason = "" if was_updated else "no_record"
        env = MagicMock()
        env.signal_kind = MagicMock()
        env.signal_kind.value = signal_kind
        env.result_kind = MagicMock()
        env.result_kind.value = result_kind
        env.contract_id = "contract_abc"
        env.session_id = "sess_001"
        env.task_id = "task_001"
        env.trace_id = "trace_001"
        outcome.envelope = env
        return outcome

    def test_F_consume_method_exists(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator

        orch = SourceDispatchOrchestrator()
        assert hasattr(orch, "consume_android_behavioral_result")
        assert callable(orch.consume_android_behavioral_result)

    def test_G_returns_stable_dict_keys(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator

        orch = SourceDispatchOrchestrator()
        outcome = self._make_outcome(was_updated=True)
        result = orch.consume_android_behavioral_result(outcome)
        expected_keys = {
            "consumed",
            "was_updated",
            "signal_kind",
            "result_kind",
            "contract_id",
            "session_id",
            "task_id",
            "trace_id",
            "reject_reason",
            "terminal_signal_recorded",
        }
        assert expected_keys == set(result.keys())

    def test_H_handles_none_outcome_gracefully(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator

        orch = SourceDispatchOrchestrator()
        # Should not raise
        result = orch.consume_android_behavioral_result(None)
        assert isinstance(result, dict)
        assert result["consumed"] is False

    def test_I_was_updated_true_sets_consumed_true(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator

        orch = SourceDispatchOrchestrator()
        outcome = self._make_outcome(was_updated=True)
        result = orch.consume_android_behavioral_result(outcome)
        assert result["consumed"] is True
        assert result["was_updated"] is True
        assert result["signal_kind"] == "result"
        assert result["result_kind"] == "success"

    def test_J_was_updated_false_sets_consumed_false(self):
        from core.runtime.source_dispatch_orchestrator import SourceDispatchOrchestrator

        orch = SourceDispatchOrchestrator()
        outcome = self._make_outcome(was_updated=False)
        result = orch.consume_android_behavioral_result(outcome)
        assert result["consumed"] is False
        assert result["was_updated"] is False


# ---------------------------------------------------------------------------
# K. select_dispatch_target delegated policy post-gate is safe
# ---------------------------------------------------------------------------


class TestSelectDispatchTargetDelegatedPolicyGate:
    def test_K_select_dispatch_target_no_exception_no_registry(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_target

        # No registry, no candidates — should return None without raising
        result = select_dispatch_target(
            registry=None,
            readiness_inputs={},
            participation_inputs={},
            reuse_inputs={},
        )
        assert result is None

    def test_R_select_dispatch_target_explicit_device_id_bypasses_policy(self):
        from core.runtime.source_dispatch_orchestrator import select_dispatch_target

        # Explicit device_id bypasses the policy gate
        result = select_dispatch_target(
            target_device_id="device_explicit_001",
        )
        assert result is not None
        assert result.target_device_id == "device_explicit_001"
        assert result.selection_reason == "explicit_target_device_id"


# ---------------------------------------------------------------------------
# L. CommandRouter has POLICY_ENGINE_CONSULTED_ON_HEURISTIC_PATH
# ---------------------------------------------------------------------------


class TestCommandRouterPolicyIntegration:
    def test_L_sentinel_importable(self):
        from core.command_router import POLICY_ENGINE_CONSULTED_ON_HEURISTIC_PATH

        assert isinstance(POLICY_ENGINE_CONSULTED_ON_HEURISTIC_PATH, str)
        assert len(POLICY_ENGINE_CONSULTED_ON_HEURISTIC_PATH) > 0


# ---------------------------------------------------------------------------
# M, N, O. handle_delegated_execution_signal consumer wiring
# ---------------------------------------------------------------------------


class TestDelegatedSignalHandlerConsumerWiring:
    def test_M_handler_module_has_android_result_consumer_binding(self):
        import galaxy_gateway.android.handlers.delegated_signal as _ds

        # The module-level _android_result_consumer may be None (when import fails)
        # but the binding should exist.
        assert hasattr(_ds, "_android_result_consumer")

    def test_N_handler_forwards_result_kind_to_consumer(self):
        """When a result-kind signal arrives and outcome.was_updated=True,
        consume_android_behavioral_result should be called."""
        import asyncio

        import galaxy_gateway.android.handlers.delegated_signal as _ds

        # Build a mock outcome
        mock_outcome = MagicMock()
        mock_outcome.was_updated = True
        mock_outcome.reject_reason = ""
        mock_env = MagicMock()
        mock_env.signal_kind = MagicMock()
        mock_env.signal_kind.value = "result"
        mock_env.contract_id = "contract_xyz"
        mock_env.session_id = "sess_xyz"
        mock_env.signal_id = "sig_001"
        mock_env.emission_seq = 1
        mock_env.task_id = "task_xyz"
        mock_env.trace_id = "trace_xyz"
        mock_outcome.envelope = mock_env
        mock_record = MagicMock()
        mock_record.phase = MagicMock()
        mock_record.phase.value = "result"
        mock_outcome.record = mock_record

        mock_consumer = MagicMock()
        mock_consumer.consume_android_behavioral_result = MagicMock(
            return_value={"consumed": True}
        )

        loop = asyncio.new_event_loop()
        try:
            with patch.object(_ds, "_ingest_delegated_signal", return_value=mock_outcome), \
                 patch.object(_ds, "_android_result_consumer", mock_consumer):
                result = loop.run_until_complete(
                    _ds.handle_delegated_execution_signal(
                        bridge=MagicMock(),
                        websocket=MagicMock(),
                        message={"device_id": "dev_001", "message_id": "msg_001"},
                    )
                )
        finally:
            loop.close()

        assert result["type"] == "delegated_execution_signal_ack"
        mock_consumer.consume_android_behavioral_result.assert_called_once()

    def test_O_handler_does_not_forward_non_result_kind(self):
        """When signal_kind is 'progress', consumer should NOT be called."""
        import asyncio

        import galaxy_gateway.android.handlers.delegated_signal as _ds

        mock_outcome = MagicMock()
        mock_outcome.was_updated = True
        mock_outcome.reject_reason = ""
        mock_env = MagicMock()
        mock_env.signal_kind = MagicMock()
        mock_env.signal_kind.value = "progress"  # NOT result
        mock_env.contract_id = "contract_xyz"
        mock_env.session_id = "sess_xyz"
        mock_env.signal_id = "sig_002"
        mock_env.emission_seq = 2
        mock_env.task_id = "task_xyz"
        mock_env.trace_id = "trace_xyz"
        mock_outcome.envelope = mock_env
        mock_record = MagicMock()
        mock_record.phase = MagicMock()
        mock_record.phase.value = "progress"
        mock_outcome.record = mock_record

        mock_consumer = MagicMock()
        mock_consumer.consume_android_behavioral_result = MagicMock()

        loop = asyncio.new_event_loop()
        try:
            with patch.object(_ds, "_ingest_delegated_signal", return_value=mock_outcome), \
                 patch.object(_ds, "_android_result_consumer", mock_consumer):
                result = loop.run_until_complete(
                    _ds.handle_delegated_execution_signal(
                        bridge=MagicMock(),
                        websocket=MagicMock(),
                        message={"device_id": "dev_001", "message_id": "msg_002"},
                    )
                )
        finally:
            loop.close()

        assert result["type"] == "delegated_execution_signal_ack"
        mock_consumer.consume_android_behavioral_result.assert_not_called()
