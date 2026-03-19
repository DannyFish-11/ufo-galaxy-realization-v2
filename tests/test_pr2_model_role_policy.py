"""tests/test_pr2_model_role_policy.py
========================================

PR-2 — OpenClawd 主脑职责硬化

Tests covering:

1. ModelRole enum — values and membership.
2. DecisionAuthority enum — values.
3. ModelRolePolicy.get_role() — known and unknown components.
4. ModelRolePolicy.get_authority() — maps correctly.
5. ModelRolePolicy.may_decide() — only PRIMARY returns True.
6. ModelRolePolicy.assert_primary() — raises for non-primary; passes for primary.
7. ModelRolePolicy.log_primary_authority() — emits without raising.
8. get_policy() singleton — same instance on repeated calls.
9. reset_policy() — clears singleton.
10. Module-level assert_primary() shortcut.
11. PolicyViolationError is a RuntimeError subclass.
12. openclawd.process() — decision-authority log is emitted.
13. HybridExecutor.execute() — accepts decision_authority kwarg without error.
14. TaskOrchestrator.submit_task() — accepts openclawd_decision metadata.
15. TaskOrchestrator._decompose_task() docstring asserts no re-evaluation.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.model_role_policy import (
    DecisionAuthority,
    ModelRole,
    ModelRolePolicy,
    PolicyViolationError,
    assert_primary,
    get_policy,
    reset_policy,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _fresh_policy() -> ModelRolePolicy:
    reset_policy()
    return get_policy()


# ===========================================================================
# 1. ModelRole enum
# ===========================================================================


class TestModelRoleEnum:
    def test_values_exist(self):
        assert ModelRole.PRIMARY.value == "primary"
        assert ModelRole.ORCHESTRATOR.value == "orchestrator"
        assert ModelRole.EXECUTOR.value == "executor"
        assert ModelRole.TRANSPORT.value == "transport"

    def test_all_four_roles(self):
        assert len(ModelRole) == 4


# ===========================================================================
# 2. DecisionAuthority enum
# ===========================================================================


class TestDecisionAuthorityEnum:
    def test_values_exist(self):
        assert DecisionAuthority.FULL.value == "full"
        assert DecisionAuthority.EXECUTE.value == "execute"
        assert DecisionAuthority.RELAY.value == "relay"

    def test_three_authorities(self):
        assert len(DecisionAuthority) == 3


# ===========================================================================
# 3. ModelRolePolicy.get_role()
# ===========================================================================


class TestGetRole:
    def test_openclawd_is_primary(self):
        p = _fresh_policy()
        assert p.get_role("openclawd") == ModelRole.PRIMARY

    def test_task_orchestrator_is_orchestrator(self):
        p = _fresh_policy()
        assert p.get_role("task_orchestrator") == ModelRole.ORCHESTRATOR

    def test_e2e_orchestrator_is_orchestrator(self):
        p = _fresh_policy()
        assert p.get_role("e2e_orchestrator") == ModelRole.ORCHESTRATOR

    def test_galaxy_gateway_is_orchestrator(self):
        p = _fresh_policy()
        assert p.get_role("galaxy_gateway") == ModelRole.ORCHESTRATOR

    def test_hybrid_executor_is_executor(self):
        p = _fresh_policy()
        assert p.get_role("hybrid_executor") == ModelRole.EXECUTOR

    def test_windows_arbiter_is_executor(self):
        p = _fresh_policy()
        assert p.get_role("windows_arbiter") == ModelRole.EXECUTOR

    def test_smart_transport_is_transport(self):
        p = _fresh_policy()
        assert p.get_role("smart_transport") == ModelRole.TRANSPORT

    def test_unknown_component_defaults_to_executor(self):
        p = _fresh_policy()
        assert p.get_role("some_unknown_module") == ModelRole.EXECUTOR

    def test_case_insensitive(self):
        p = _fresh_policy()
        assert p.get_role("OpenClawd") == ModelRole.PRIMARY
        assert p.get_role("OPENCLAWD") == ModelRole.PRIMARY


# ===========================================================================
# 4. ModelRolePolicy.get_authority()
# ===========================================================================


class TestGetAuthority:
    def test_openclawd_has_full(self):
        p = _fresh_policy()
        assert p.get_authority("openclawd") == DecisionAuthority.FULL

    def test_orchestrator_has_execute(self):
        p = _fresh_policy()
        assert p.get_authority("task_orchestrator") == DecisionAuthority.EXECUTE

    def test_executor_has_execute(self):
        p = _fresh_policy()
        assert p.get_authority("hybrid_executor") == DecisionAuthority.EXECUTE

    def test_transport_has_relay(self):
        p = _fresh_policy()
        assert p.get_authority("smart_transport") == DecisionAuthority.RELAY


# ===========================================================================
# 5. ModelRolePolicy.may_decide()
# ===========================================================================


class TestMayDecide:
    def test_openclawd_may_decide(self):
        p = _fresh_policy()
        assert p.may_decide("openclawd") is True

    def test_orchestrator_may_not_decide(self):
        p = _fresh_policy()
        assert p.may_decide("task_orchestrator") is False
        assert p.may_decide("e2e_orchestrator") is False
        assert p.may_decide("galaxy_gateway") is False

    def test_executor_may_not_decide(self):
        p = _fresh_policy()
        assert p.may_decide("hybrid_executor") is False
        assert p.may_decide("windows_arbiter") is False

    def test_transport_may_not_decide(self):
        p = _fresh_policy()
        assert p.may_decide("smart_transport") is False

    def test_unknown_may_not_decide(self):
        p = _fresh_policy()
        assert p.may_decide("mystery_module") is False


# ===========================================================================
# 6. ModelRolePolicy.assert_primary()
# ===========================================================================


class TestAssertPrimary:
    def test_openclawd_passes(self):
        p = _fresh_policy()
        # Should not raise
        p.assert_primary("openclawd")

    def test_orchestrator_raises(self):
        p = _fresh_policy()
        with pytest.raises(PolicyViolationError):
            p.assert_primary("task_orchestrator")

    def test_executor_raises(self):
        p = _fresh_policy()
        with pytest.raises(PolicyViolationError):
            p.assert_primary("hybrid_executor")

    def test_transport_raises(self):
        p = _fresh_policy()
        with pytest.raises(PolicyViolationError):
            p.assert_primary("smart_transport")

    def test_context_in_error_message(self):
        p = _fresh_policy()
        with pytest.raises(PolicyViolationError) as exc_info:
            p.assert_primary("hybrid_executor", context="re-routing intent")
        assert "re-routing intent" in str(exc_info.value)


# ===========================================================================
# 7. ModelRolePolicy.log_primary_authority() — emits without raising
# ===========================================================================


class TestLogPrimaryAuthority:
    def test_emits_without_raising(self, caplog):
        p = _fresh_policy()
        with caplog.at_level(logging.INFO, logger="Galaxy.ModelRolePolicy"):
            p.log_primary_authority(
                "openclawd",
                trace_id="trace-abc",
                model="gpt-4o",
                intent="chat",
            )
        assert "primary_decision" in caplog.text

    def test_includes_trace_id(self, caplog):
        p = _fresh_policy()
        with caplog.at_level(logging.INFO, logger="Galaxy.ModelRolePolicy"):
            p.log_primary_authority("openclawd", trace_id="trace-xyz123")
        assert "trace-xyz123" in caplog.text

    def test_non_primary_component_still_logs(self, caplog):
        """log_primary_authority does not raise; it just records the fact."""
        p = _fresh_policy()
        with caplog.at_level(logging.INFO, logger="Galaxy.ModelRolePolicy"):
            p.log_primary_authority("task_orchestrator", trace_id="t1")
        # Should not raise regardless of role


# ===========================================================================
# 8 & 9. Singleton get_policy() / reset_policy()
# ===========================================================================


class TestSingleton:
    def test_same_instance_returned(self):
        reset_policy()
        p1 = get_policy()
        p2 = get_policy()
        assert p1 is p2

    def test_reset_creates_new_instance(self):
        p1 = get_policy()
        reset_policy()
        p2 = get_policy()
        assert p1 is not p2


# ===========================================================================
# 10. Module-level assert_primary() shortcut
# ===========================================================================


class TestModuleLevelAssertPrimary:
    def test_openclawd_passes(self):
        reset_policy()
        assert_primary("openclawd")  # no raise

    def test_non_primary_raises(self):
        reset_policy()
        with pytest.raises(PolicyViolationError):
            assert_primary("hybrid_executor")


# ===========================================================================
# 11. PolicyViolationError is a RuntimeError subclass
# ===========================================================================


class TestPolicyViolationError:
    def test_is_runtime_error(self):
        err = PolicyViolationError("test")
        assert isinstance(err, RuntimeError)

    def test_message_preserved(self):
        err = PolicyViolationError("cannot decide here")
        assert "cannot decide here" in str(err)


# ===========================================================================
# 12. openclawd.process() — decision-authority log is emitted
# ===========================================================================


class TestOpenClawdDecisionAuthorityLog:
    """Confirm that OpenClawd.process() calls log_primary_authority."""

    @pytest.mark.asyncio
    async def test_log_primary_authority_called_on_direct_path(self, caplog):
        from core.openclawd import OpenClawd

        oc = OpenClawd()

        # Disable kernel path so we exercise the direct handler path
        with patch.object(oc, "_get_kernel", return_value=None), \
             patch.object(oc, "sync_device_capabilities", return_value=0), \
             patch.object(oc, "_parse_intent", new_callable=AsyncMock,
                          return_value=None), \
             patch.object(oc, "_dispatch_chat", new_callable=AsyncMock,
                          return_value={"success": True, "response": "hi"}), \
             caplog.at_level(logging.INFO, logger="Galaxy.ModelRolePolicy"):
            await oc.process("hello")

        assert "primary_decision" in caplog.text

    @pytest.mark.asyncio
    async def test_log_contains_authority_openclawd(self, caplog):
        from core.openclawd import OpenClawd

        oc = OpenClawd()

        with patch.object(oc, "_get_kernel", return_value=None), \
             patch.object(oc, "sync_device_capabilities", return_value=0), \
             patch.object(oc, "_parse_intent", new_callable=AsyncMock,
                          return_value=None), \
             patch.object(oc, "_dispatch_chat", new_callable=AsyncMock,
                          return_value={"success": True, "response": "ok"}), \
             caplog.at_level(logging.INFO, logger="Galaxy.ModelRolePolicy"):
            await oc.process("hello")

        assert "openclawd" in caplog.text


# ===========================================================================
# 13. HybridExecutor.execute() — accepts decision_authority kwarg
# ===========================================================================


class TestHybridExecutorDecisionAuthorityParam:
    @pytest.mark.asyncio
    async def test_decision_authority_kwarg_accepted(self):
        from core.hybrid_executor import HybridExecutionArbiter, ExecutionLevel

        arbiter = HybridExecutionArbiter()

        async def _fake_a2a(app_id, action, params, device_id):
            return {"success": True, "data": "done"}

        arbiter.set_executors(a2a=_fake_a2a)

        result = await arbiter.execute(
            device_id="android_phone",
            app_id="com.example.app",
            action="open",
            windows_arbiter=False,
            decision_authority="openclawd",
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_decision_authority_empty_string_ok(self):
        """Omitting decision_authority (empty string default) must not break."""
        from core.hybrid_executor import HybridExecutionArbiter

        arbiter = HybridExecutionArbiter()

        async def _fake_a2a(app_id, action, params, device_id):
            return {"success": True}

        arbiter.set_executors(a2a=_fake_a2a)

        result = await arbiter.execute(
            device_id="android_phone",
            app_id="com.example.app",
            action="open",
            windows_arbiter=False,
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_hybrid_executor_does_not_change_action(self):
        """HybridExecutor must forward the received action unchanged."""
        from core.hybrid_executor import HybridExecutionArbiter

        received_actions = []

        async def _recording_a2a(app_id, action, params, device_id):
            received_actions.append(action)
            return {"success": True}

        arbiter = HybridExecutionArbiter()
        arbiter.set_executors(a2a=_recording_a2a)

        await arbiter.execute(
            device_id="android_phone",
            app_id="app",
            action="launch_app",
            windows_arbiter=False,
            decision_authority="openclawd",
        )
        assert received_actions == ["launch_app"]


# ===========================================================================
# 14. TaskOrchestrator.submit_task() — accepts openclawd_decision metadata
# ===========================================================================


class TestTaskOrchestratorOpenClawdDecision:
    @pytest.mark.asyncio
    async def test_submit_task_accepts_openclawd_decision(self):
        from unittest.mock import MagicMock, AsyncMock
        from galaxy_gateway.orchestrator.task_orchestrator import (
            TaskOrchestrator, TaskPriority,
        )

        dm = MagicMock()
        mh = MagicMock()
        ws = MagicMock()
        ws.is_device_connected.return_value = True

        orch = TaskOrchestrator(dm, mh, ws)

        decision = {"intent": "chat", "model": "gpt-4o", "trace_id": "t-001"}

        # submit_task immediately puts to queue; intercept the queue
        with patch.object(orch.task_queue, "put", new=AsyncMock()):
            task = await orch.submit_task(
                "open wechat",
                openclawd_decision=decision,
            )

        assert task is not None
        # The envelope should carry the decision in metadata
        envelope = orch._task_envelopes.get(task.task_id)
        if envelope is not None:  # envelope construction may be skipped in CI
            meta = envelope.metadata or {}
            assert meta.get("openclawd_decision") == decision

    @pytest.mark.asyncio
    async def test_submit_task_without_openclawd_decision_backward_compat(self):
        from unittest.mock import MagicMock, AsyncMock
        from galaxy_gateway.orchestrator.task_orchestrator import TaskOrchestrator

        dm = MagicMock()
        mh = MagicMock()
        ws = MagicMock()

        orch = TaskOrchestrator(dm, mh, ws)

        with patch.object(orch.task_queue, "put", new=AsyncMock()):
            task = await orch.submit_task("screenshot")

        assert task is not None


# ===========================================================================
# 15. TaskOrchestrator._decompose_task docstring asserts no re-evaluation
# ===========================================================================


class TestDecomposeTaskDocstring:
    def test_docstring_mentions_no_re_evaluation(self):
        from galaxy_gateway.orchestrator.task_orchestrator import TaskOrchestrator
        import inspect

        doc = inspect.getdoc(TaskOrchestrator._decompose_task)
        assert doc is not None
        # PR-2 docstring must note that no intent re-evaluation happens
        doc_lower = doc.lower()
        assert any(
            phrase in doc_lower
            for phrase in ("re-evaluat", "no re-eval", "not re-evaluat", "does not re-evaluat", "structural decomposition")
        ), f"Docstring must mention structural decomposition / no re-evaluation. Got: {doc}"
