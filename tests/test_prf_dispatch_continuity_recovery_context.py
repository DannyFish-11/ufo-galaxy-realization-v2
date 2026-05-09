"""tests/test_prf_dispatch_continuity_recovery_context.py
=============================================================
Tests for PR-F: Durable Dispatch-to-Session Continuity and Recovery Context.

Coverage:
  A.  DispatchContinuityClass enum has all required values.
  B.  DispatchContinuityContext round-trips through to_dict / from_dict.
  C.  build_dispatch_continuity_context populates all identity fields.
  D.  DispatchContinuityContext.is_resumable() behaves correctly per class.
  E.  ExecutionInterruptionClass enum has recoverable and terminal values.
  F.  build_execution_interruption_record — recoverable: is_resumable=True,
      recommended_action derived correctly.
  G.  build_execution_interruption_record — terminal: is_resumable=False,
      recommended_action='terminal_abort'.
  H.  ExecutionInterruptionRecord carries continuity_context back-link.
  I.  ExecutionInterruptionRecord round-trips through to_dict / from_dict.
  J.  SourceDispatchPlan accepts continuity_context field (None by default).
  K.  build_source_dispatch_plan forwards continuity_context to plan.
  L.  SourceDispatchResult accepts continuity_context field (None by default).
  M.  build_source_dispatch_result forwards continuity_context to result.
  N.  SourceDispatchResult.to_compact_summary includes has_continuity_context.
  O.  TaskEnvelope accepts continuity_context field (None by default).
  P.  TaskEnvelope with continuity_context round-trips through model_dump.
  Q.  MeshSessionLifecycleCoordinator.associate_resumed_execution stores
      association in session metadata.
  R.  associate_resumed_execution returns None for unknown session.
  S.  associate_resumed_execution returns None for terminal session.
  T.  associate_resumed_execution_with_session module-level helper works.
  U.  Sentinel constants are importable from contracts.dispatch_continuity.
  V.  PR-F sentinel and policies are importable from
      core.runtime.source_dispatch_orchestrator.
  W.  RESUMED_EXECUTION_ASSOCIATION sentinel importable from
      core.mesh.mesh_session_lifecycle.
  X.  Existing dispatch paths (local, remote_handoff, fallback_local)
      remain functional without continuity_context (backward compatibility).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional

import pytest

from contracts.dispatch_continuity import (
    DISPATCH_CONTINUITY_CONTEXT_IS_DURABLE,
    RECOVERABLE_INTERRUPTION_REQUIRES_CONTINUITY_CONTEXT_POLICY,
    TERMINAL_LOSS_IS_NON_RESUMABLE_POLICY,
    CONTINUITY_CONTEXT_SURVIVES_RECONNECT_POLICY,
    DispatchContinuityClass,
    DispatchContinuityContext,
    ExecutionInterruptionClass,
    ExecutionInterruptionRecord,
    build_dispatch_continuity_context,
    build_execution_interruption_record,
)


# ---------------------------------------------------------------------------
# A. DispatchContinuityClass enum values
# ---------------------------------------------------------------------------


class TestDispatchContinuityClassEnum:
    """DispatchContinuityClass has all required values."""

    def test_persistent(self):
        assert DispatchContinuityClass.persistent == "persistent"

    def test_request_scoped(self):
        assert DispatchContinuityClass.request_scoped == "request_scoped"

    def test_transfer_scoped(self):
        assert DispatchContinuityClass.transfer_scoped == "transfer_scoped"

    def test_ephemeral(self):
        assert DispatchContinuityClass.ephemeral == "ephemeral"

    def test_is_str_enum(self):
        assert isinstance(DispatchContinuityClass.persistent, str)

    def test_all_four_values_present(self):
        values = {e.value for e in DispatchContinuityClass}
        assert values == {"persistent", "request_scoped", "transfer_scoped", "ephemeral"}


# ---------------------------------------------------------------------------
# B. DispatchContinuityContext round-trip
# ---------------------------------------------------------------------------


class TestDispatchContinuityContextRoundTrip:
    """DispatchContinuityContext serialises and deserialises correctly."""

    def _make_context(self) -> DispatchContinuityContext:
        return DispatchContinuityContext(
            prior_dispatch_id="dispatch_001",
            prior_session_id="sess_001",
            prior_mesh_session_id="mesh_001",
            prior_task_id="task_001",
            prior_trace_id="trace_001",
            originating_device_id="android_01",
            resume_attempt_count=2,
            continuity_class=DispatchContinuityClass.persistent,
        )

    def test_to_dict_has_required_fields(self):
        ctx = self._make_context()
        d = ctx.to_dict()
        assert "continuity_id" in d
        assert d["prior_dispatch_id"] == "dispatch_001"
        assert d["prior_session_id"] == "sess_001"
        assert d["prior_mesh_session_id"] == "mesh_001"
        assert d["prior_task_id"] == "task_001"
        assert d["prior_trace_id"] == "trace_001"
        assert d["originating_device_id"] == "android_01"
        assert d["resume_attempt_count"] == 2
        assert d["continuity_class"] == "persistent"

    def test_from_dict_restores_fields(self):
        ctx = self._make_context()
        restored = DispatchContinuityContext.from_dict(ctx.to_dict())
        assert restored.continuity_id == ctx.continuity_id
        assert restored.prior_dispatch_id == "dispatch_001"
        assert restored.prior_mesh_session_id == "mesh_001"
        assert restored.resume_attempt_count == 2

    def test_to_json_is_valid_json(self):
        ctx = self._make_context()
        j = ctx.to_json()
        parsed = json.loads(j)
        assert parsed["prior_dispatch_id"] == "dispatch_001"

    def test_to_json_with_indent(self):
        ctx = self._make_context()
        j = ctx.to_json(indent=2)
        assert "\n" in j
        parsed = json.loads(j)
        assert parsed["prior_session_id"] == "sess_001"


# ---------------------------------------------------------------------------
# C. build_dispatch_continuity_context builder
# ---------------------------------------------------------------------------


class TestBuildDispatchContinuityContext:
    """build_dispatch_continuity_context populates all identity fields."""

    def test_all_fields_populated(self):
        ctx = build_dispatch_continuity_context(
            prior_dispatch_id="d_abc",
            prior_session_id="s_abc",
            prior_mesh_session_id="m_abc",
            prior_task_id="t_abc",
            prior_trace_id="tr_abc",
            originating_device_id="dev_01",
            resume_attempt_count=1,
            continuity_class=DispatchContinuityClass.transfer_scoped,
            last_checkpoint_at=1000.0,
            metadata={"custom": "value"},
        )
        assert ctx.prior_dispatch_id == "d_abc"
        assert ctx.prior_session_id == "s_abc"
        assert ctx.prior_mesh_session_id == "m_abc"
        assert ctx.prior_task_id == "t_abc"
        assert ctx.prior_trace_id == "tr_abc"
        assert ctx.originating_device_id == "dev_01"
        assert ctx.resume_attempt_count == 1
        assert ctx.continuity_class == DispatchContinuityClass.transfer_scoped
        assert ctx.last_checkpoint_at == 1000.0
        assert ctx.metadata["custom"] == "value"

    def test_defaults_produce_valid_context(self):
        ctx = build_dispatch_continuity_context()
        assert ctx.continuity_id  # non-empty UUID
        assert ctx.resume_attempt_count == 0
        assert ctx.continuity_class == DispatchContinuityClass.persistent
        assert ctx.prior_dispatch_id is None

    def test_has_unique_continuity_id(self):
        ctx1 = build_dispatch_continuity_context()
        ctx2 = build_dispatch_continuity_context()
        assert ctx1.continuity_id != ctx2.continuity_id


# ---------------------------------------------------------------------------
# D. DispatchContinuityContext.is_resumable()
# ---------------------------------------------------------------------------


class TestDispatchContinuityContextIsResumable:
    """is_resumable() returns correct value per continuity class."""

    def test_persistent_is_resumable(self):
        ctx = build_dispatch_continuity_context(continuity_class=DispatchContinuityClass.persistent)
        assert ctx.is_resumable() is True

    def test_transfer_scoped_is_resumable(self):
        ctx = build_dispatch_continuity_context(continuity_class=DispatchContinuityClass.transfer_scoped)
        assert ctx.is_resumable() is True

    def test_request_scoped_is_not_resumable(self):
        ctx = build_dispatch_continuity_context(continuity_class=DispatchContinuityClass.request_scoped)
        assert ctx.is_resumable() is False

    def test_ephemeral_is_not_resumable(self):
        ctx = build_dispatch_continuity_context(continuity_class=DispatchContinuityClass.ephemeral)
        assert ctx.is_resumable() is False


# ---------------------------------------------------------------------------
# E. ExecutionInterruptionClass enum values
# ---------------------------------------------------------------------------


class TestExecutionInterruptionClassEnum:
    """ExecutionInterruptionClass has recoverable and terminal values."""

    def test_recoverable(self):
        assert ExecutionInterruptionClass.recoverable == "recoverable"

    def test_terminal(self):
        assert ExecutionInterruptionClass.terminal == "terminal"

    def test_is_str_enum(self):
        assert isinstance(ExecutionInterruptionClass.recoverable, str)

    def test_exactly_two_values(self):
        values = {e.value for e in ExecutionInterruptionClass}
        assert values == {"recoverable", "terminal"}


# ---------------------------------------------------------------------------
# F. build_execution_interruption_record — recoverable
# ---------------------------------------------------------------------------


class TestBuildInterruptionRecordRecoverable:
    """Recoverable interruption record has correct defaults."""

    def _make_ctx(self) -> DispatchContinuityContext:
        return build_dispatch_continuity_context(
            prior_dispatch_id="d_001",
            prior_session_id="s_001",
        )

    def test_is_resumable_true_for_recoverable(self):
        ctx = self._make_ctx()
        rec = build_execution_interruption_record(
            interruption_class=ExecutionInterruptionClass.recoverable,
            interruption_reason="device_disconnect",
            continuity_context=ctx,
        )
        assert rec.is_resumable is True

    def test_recommended_action_default_resume_local(self):
        rec = build_execution_interruption_record(
            interruption_class=ExecutionInterruptionClass.recoverable,
        )
        assert rec.recommended_action == "resume_local"

    def test_custom_recommended_action(self):
        rec = build_execution_interruption_record(
            interruption_class=ExecutionInterruptionClass.recoverable,
            recommended_action="resume_on_target",
        )
        assert rec.recommended_action == "resume_on_target"

    def test_interruption_reason_preserved(self):
        rec = build_execution_interruption_record(
            interruption_class=ExecutionInterruptionClass.recoverable,
            interruption_reason="network_timeout",
        )
        assert rec.interruption_reason == "network_timeout"

    def test_all_identity_fields_preserved(self):
        rec = build_execution_interruption_record(
            dispatch_id="d_001",
            session_id="s_001",
            mesh_session_id="m_001",
            task_id="t_001",
            trace_id="tr_001",
            interruption_class=ExecutionInterruptionClass.recoverable,
            executor_target_device_id="android_01",
        )
        assert rec.dispatch_id == "d_001"
        assert rec.session_id == "s_001"
        assert rec.mesh_session_id == "m_001"
        assert rec.task_id == "t_001"
        assert rec.trace_id == "tr_001"
        assert rec.executor_target_device_id == "android_01"


# ---------------------------------------------------------------------------
# G. build_execution_interruption_record — terminal
# ---------------------------------------------------------------------------


class TestBuildInterruptionRecordTerminal:
    """Terminal interruption record is non-resumable."""

    def test_is_resumable_false_for_terminal(self):
        rec = build_execution_interruption_record(
            interruption_class=ExecutionInterruptionClass.terminal,
            interruption_reason="device_permanently_offline",
        )
        assert rec.is_resumable is False

    def test_recommended_action_terminal_abort(self):
        rec = build_execution_interruption_record(
            interruption_class=ExecutionInterruptionClass.terminal,
        )
        assert rec.recommended_action == "terminal_abort"

    def test_continuity_context_none_for_terminal(self):
        rec = build_execution_interruption_record(
            interruption_class=ExecutionInterruptionClass.terminal,
        )
        assert rec.continuity_context is None


# ---------------------------------------------------------------------------
# H. ExecutionInterruptionRecord carries continuity_context back-link
# ---------------------------------------------------------------------------


class TestInterruptionRecordContinuityBackLink:
    """ExecutionInterruptionRecord carries DispatchContinuityContext."""

    def test_continuity_context_back_link(self):
        ctx = build_dispatch_continuity_context(
            prior_dispatch_id="d_abc",
            prior_session_id="s_abc",
        )
        rec = build_execution_interruption_record(
            interruption_class=ExecutionInterruptionClass.recoverable,
            continuity_context=ctx,
        )
        assert rec.continuity_context is ctx
        assert rec.continuity_context.prior_dispatch_id == "d_abc"
        assert rec.continuity_context.prior_session_id == "s_abc"


# ---------------------------------------------------------------------------
# I. ExecutionInterruptionRecord round-trip
# ---------------------------------------------------------------------------


class TestExecutionInterruptionRecordRoundTrip:
    """ExecutionInterruptionRecord serialises and deserialises correctly."""

    def _make_record(self) -> ExecutionInterruptionRecord:
        ctx = build_dispatch_continuity_context(prior_dispatch_id="d_rt")
        return build_execution_interruption_record(
            dispatch_id="d_rt",
            session_id="s_rt",
            interruption_class=ExecutionInterruptionClass.recoverable,
            interruption_reason="reconnect",
            continuity_context=ctx,
        )

    def test_to_dict_has_required_fields(self):
        rec = self._make_record()
        d = rec.to_dict()
        assert "interruption_id" in d
        assert d["dispatch_id"] == "d_rt"
        assert d["interruption_class"] == "recoverable"
        assert d["is_resumable"] is True
        assert d["continuity_context"]["prior_dispatch_id"] == "d_rt"

    def test_from_dict_restores_fields(self):
        rec = self._make_record()
        restored = ExecutionInterruptionRecord.from_dict(rec.to_dict())
        assert restored.interruption_id == rec.interruption_id
        assert restored.dispatch_id == "d_rt"
        assert restored.is_resumable is True


# ---------------------------------------------------------------------------
# J. SourceDispatchPlan carries continuity_context field
# ---------------------------------------------------------------------------


class TestSourceDispatchPlanContinuityContext:
    """SourceDispatchPlan accepts continuity_context field."""

    def test_default_is_none(self):
        from contracts.source_dispatch import SourceDispatchPlan
        plan = SourceDispatchPlan()
        assert plan.continuity_context is None

    def test_set_continuity_context(self):
        from contracts.source_dispatch import SourceDispatchPlan
        ctx_dict = {"continuity_id": "abc", "prior_dispatch_id": "d_001"}
        plan = SourceDispatchPlan(continuity_context=ctx_dict)
        assert plan.continuity_context == ctx_dict

    def test_round_trip_preserves_continuity_context(self):
        from contracts.source_dispatch import SourceDispatchPlan
        ctx_dict = {"continuity_id": "abc", "prior_dispatch_id": "d_001"}
        plan = SourceDispatchPlan(continuity_context=ctx_dict)
        restored = SourceDispatchPlan.from_dict(plan.to_dict())
        assert restored.continuity_context == ctx_dict


# ---------------------------------------------------------------------------
# K. build_source_dispatch_plan forwards continuity_context
# ---------------------------------------------------------------------------


class TestBuildSourceDispatchPlanContinuityContext:
    """build_source_dispatch_plan forwards continuity_context to plan."""

    def test_continuity_context_forwarded(self):
        from contracts.source_dispatch import build_source_dispatch_plan
        ctx_dict = {"continuity_id": "x", "prior_session_id": "s_001"}
        plan = build_source_dispatch_plan(continuity_context=ctx_dict)
        assert plan.continuity_context == ctx_dict

    def test_none_by_default(self):
        from contracts.source_dispatch import build_source_dispatch_plan
        plan = build_source_dispatch_plan()
        assert plan.continuity_context is None


# ---------------------------------------------------------------------------
# L. SourceDispatchResult carries continuity_context field
# ---------------------------------------------------------------------------


class TestSourceDispatchResultContinuityContext:
    """SourceDispatchResult accepts continuity_context field."""

    def test_default_is_none(self):
        from contracts.source_dispatch import SourceDispatchResult
        result = SourceDispatchResult()
        assert result.continuity_context is None

    def test_set_continuity_context(self):
        from contracts.source_dispatch import SourceDispatchResult
        ctx_dict = {"continuity_id": "abc", "prior_task_id": "t_001"}
        result = SourceDispatchResult(continuity_context=ctx_dict)
        assert result.continuity_context == ctx_dict

    def test_round_trip_preserves_continuity_context(self):
        from contracts.source_dispatch import SourceDispatchResult
        ctx_dict = {"continuity_id": "abc", "prior_task_id": "t_001"}
        result = SourceDispatchResult(continuity_context=ctx_dict)
        restored = SourceDispatchResult.from_dict(result.to_dict())
        assert restored.continuity_context == ctx_dict


# ---------------------------------------------------------------------------
# M. build_source_dispatch_result forwards continuity_context
# ---------------------------------------------------------------------------


class TestBuildSourceDispatchResultContinuityContext:
    """build_source_dispatch_result forwards continuity_context to result."""

    def test_continuity_context_forwarded(self):
        from contracts.source_dispatch import build_source_dispatch_result
        ctx_dict = {"continuity_id": "y", "prior_trace_id": "tr_001"}
        result = build_source_dispatch_result(continuity_context=ctx_dict)
        assert result.continuity_context == ctx_dict

    def test_none_by_default(self):
        from contracts.source_dispatch import build_source_dispatch_result
        result = build_source_dispatch_result()
        assert result.continuity_context is None


# ---------------------------------------------------------------------------
# N. SourceDispatchResult.to_compact_summary includes has_continuity_context
# ---------------------------------------------------------------------------


class TestCompactSummaryHasContinuityContext:
    """to_compact_summary includes has_continuity_context flag."""

    def test_false_when_none(self):
        from contracts.source_dispatch import SourceDispatchResult
        result = SourceDispatchResult()
        summary = result.to_compact_summary()
        assert "has_continuity_context" in summary
        assert summary["has_continuity_context"] is False

    def test_true_when_set(self):
        from contracts.source_dispatch import SourceDispatchResult
        result = SourceDispatchResult(continuity_context={"continuity_id": "abc"})
        summary = result.to_compact_summary()
        assert summary["has_continuity_context"] is True


# ---------------------------------------------------------------------------
# O. TaskEnvelope accepts continuity_context field
# ---------------------------------------------------------------------------


class TestTaskEnvelopeContinuityContextField:
    """TaskEnvelope carries continuity_context field."""

    def test_default_is_none(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope()
        assert env.continuity_context is None

    def test_set_continuity_context(self):
        from core.schemas.task_envelope import TaskEnvelope
        ctx_dict = {"continuity_id": "abc", "prior_dispatch_id": "d_001"}
        env = TaskEnvelope(continuity_context=ctx_dict)
        assert env.continuity_context == ctx_dict

    def test_set_to_dict_serialised(self):
        from contracts.dispatch_continuity import build_dispatch_continuity_context
        from core.schemas.task_envelope import TaskEnvelope
        ctx = build_dispatch_continuity_context(prior_dispatch_id="d_env")
        env = TaskEnvelope(continuity_context=ctx.to_dict())
        assert env.continuity_context["prior_dispatch_id"] == "d_env"


# ---------------------------------------------------------------------------
# P. TaskEnvelope round-trip with continuity_context
# ---------------------------------------------------------------------------


class TestTaskEnvelopeContinuityContextRoundTrip:
    """TaskEnvelope continuity_context survives model_dump round-trip."""

    def test_model_dump_round_trip(self):
        from core.schemas.task_envelope import TaskEnvelope
        ctx_dict = {"continuity_id": "abc", "prior_session_id": "s_01"}
        env = TaskEnvelope(continuity_context=ctx_dict)
        dumped = env.model_dump()
        assert dumped["continuity_context"] == ctx_dict


# ---------------------------------------------------------------------------
# Q. MeshSessionLifecycleCoordinator.associate_resumed_execution
# ---------------------------------------------------------------------------


class TestAssociateResumedExecution:
    """associate_resumed_execution stores association in session metadata."""

    def _make_active_coordinator(self):
        """Return a coordinator with one active session."""
        from unittest.mock import MagicMock
        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleCoordinator

        store = MagicMock()
        store.save = MagicMock()
        coordinator = MeshSessionLifecycleCoordinator(store=store)

        session_dict = {
            "session_id": "sess_active",
            "status": "active",
            "participants": [],
        }
        coordinator.create_session(session_dict)
        # Force active status to bypass state-machine restrictions in test
        with coordinator._lock:
            coordinator._sessions["sess_active"].status = "active"
        return coordinator

    def test_association_recorded_in_metadata(self):
        coord = self._make_active_coordinator()
        ctx = build_dispatch_continuity_context(
            prior_dispatch_id="d_old",
            prior_session_id="sess_active",
        )
        record = coord.associate_resumed_execution(
            "sess_active",
            ctx.to_dict(),
            resumed_dispatch_id="d_new",
        )
        assert record is not None
        assoc = record.metadata.get("resumed_execution_association")
        assert assoc is not None
        assert assoc["continuity_context"]["prior_dispatch_id"] == "d_old"
        assert assoc["resumed_dispatch_id"] == "d_new"

    def test_association_includes_timestamp(self):
        coord = self._make_active_coordinator()
        record = coord.associate_resumed_execution(
            "sess_active",
            {"prior_dispatch_id": "d_old"},
        )
        assert record is not None
        assoc = record.metadata["resumed_execution_association"]
        assert "associated_at" in assoc
        assert assoc["associated_at"] > 0

    def test_resumed_trace_id_recorded(self):
        coord = self._make_active_coordinator()
        record = coord.associate_resumed_execution(
            "sess_active",
            {},
            resumed_trace_id="tr_new",
        )
        assert record is not None
        assoc = record.metadata["resumed_execution_association"]
        assert assoc["resumed_trace_id"] == "tr_new"

    def test_none_continuity_context_tolerated(self):
        coord = self._make_active_coordinator()
        record = coord.associate_resumed_execution("sess_active", None)
        assert record is not None
        assoc = record.metadata["resumed_execution_association"]
        assert assoc["continuity_context"]["prior_session_id"] == "sess_active"
        assert assoc["continuity_context"]["prior_mesh_session_id"] == "sess_active"

    def test_non_dict_continuity_context_is_normalized(self):
        coord = self._make_active_coordinator()
        record = coord.associate_resumed_execution("sess_active", "invalid")
        assert record is not None
        assoc = record.metadata["resumed_execution_association"]
        assert assoc["continuity_context"]["prior_session_id"] == "sess_active"
        assert assoc["continuity_context_type"] == "str"


# ---------------------------------------------------------------------------
# R. associate_resumed_execution returns None for unknown session
# ---------------------------------------------------------------------------


class TestAssociateResumedExecutionUnknownSession:
    """associate_resumed_execution returns None for unknown session."""

    def test_unknown_session_returns_none(self):
        from unittest.mock import MagicMock
        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleCoordinator

        store = MagicMock()
        coord = MeshSessionLifecycleCoordinator(store=store)
        result = coord.associate_resumed_execution("no_such_session", {})
        assert result is None


# ---------------------------------------------------------------------------
# S. associate_resumed_execution returns None for terminal session
# ---------------------------------------------------------------------------


class TestAssociateResumedExecutionTerminalSession:
    """associate_resumed_execution returns None for terminal sessions."""

    def test_terminal_session_returns_none(self):
        from unittest.mock import MagicMock
        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleCoordinator

        store = MagicMock()
        store.save = MagicMock()
        coord = MeshSessionLifecycleCoordinator(store=store)
        session_dict = {"session_id": "sess_term", "status": "pending"}
        coord.create_session(session_dict)
        # Force terminal
        with coord._lock:
            coord._sessions["sess_term"].status = "completed"
        result = coord.associate_resumed_execution("sess_term", {"prior_dispatch_id": "x"})
        assert result is None


# ---------------------------------------------------------------------------
# T. associate_resumed_execution_with_session module-level helper
# ---------------------------------------------------------------------------


class TestModuleLevelAssociateResumedExecution:
    """associate_resumed_execution_with_session module-level helper works."""

    def test_module_level_helper_importable(self):
        from core.mesh.mesh_session_lifecycle import associate_resumed_execution_with_session
        assert callable(associate_resumed_execution_with_session)

    def test_module_level_helper_uses_coordinator(self):
        from unittest.mock import MagicMock, patch
        from core.mesh.mesh_session_lifecycle import (
            associate_resumed_execution_with_session,
            MeshSessionLifecycleCoordinator,
            reset_lifecycle_coordinator,
        )

        reset_lifecycle_coordinator()
        store = MagicMock()
        store.save = MagicMock()
        coord = MeshSessionLifecycleCoordinator(store=store)
        session_dict = {"session_id": "sess_module", "status": "active"}
        coord.create_session(session_dict)
        with coord._lock:
            coord._sessions["sess_module"].status = "active"

        result = associate_resumed_execution_with_session(
            "sess_module",
            {"prior_dispatch_id": "d_module"},
            coordinator=coord,
        )
        assert result is not None
        assert "resumed_execution_association" in result.metadata

        reset_lifecycle_coordinator()


# ---------------------------------------------------------------------------
# U. Sentinel constants importable from contracts.dispatch_continuity
# ---------------------------------------------------------------------------


class TestDispatchContinuitySentinels:
    """Sentinel constants are importable and contain expected keywords."""

    def test_durable_sentinel_importable(self):
        assert DISPATCH_CONTINUITY_CONTEXT_IS_DURABLE
        assert "DispatchContinuityContext" in DISPATCH_CONTINUITY_CONTEXT_IS_DURABLE

    def test_recoverable_policy_importable(self):
        assert RECOVERABLE_INTERRUPTION_REQUIRES_CONTINUITY_CONTEXT_POLICY
        assert "recoverable" in RECOVERABLE_INTERRUPTION_REQUIRES_CONTINUITY_CONTEXT_POLICY.lower()

    def test_terminal_policy_importable(self):
        assert TERMINAL_LOSS_IS_NON_RESUMABLE_POLICY
        assert "terminal" in TERMINAL_LOSS_IS_NON_RESUMABLE_POLICY.lower()

    def test_reconnect_policy_importable(self):
        assert CONTINUITY_CONTEXT_SURVIVES_RECONNECT_POLICY
        assert "reconnect" in CONTINUITY_CONTEXT_SURVIVES_RECONNECT_POLICY.lower()


# ---------------------------------------------------------------------------
# V. PR-F sentinels importable from source_dispatch_orchestrator
# ---------------------------------------------------------------------------


class TestPRFSentinelsInOrchestrator:
    """PR-F sentinel and policies are importable from source_dispatch_orchestrator."""

    def test_pr_f_sentinel_importable(self):
        from core.runtime.source_dispatch_orchestrator import (
            DISPATCH_CONTINUITY_RECOVERY_CONTEXT_PR_F_SENTINEL,
        )
        assert DISPATCH_CONTINUITY_RECOVERY_CONTEXT_PR_F_SENTINEL
        assert "PR-F" in DISPATCH_CONTINUITY_RECOVERY_CONTEXT_PR_F_SENTINEL

    def test_continuity_connects_dispatch_session_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            CONTINUITY_CONTEXT_CONNECTS_DISPATCH_SESSION_STATE_PR_F_POLICY,
        )
        assert "DispatchContinuityContext" in CONTINUITY_CONTEXT_CONNECTS_DISPATCH_SESSION_STATE_PR_F_POLICY

    def test_recoverable_vs_terminal_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            RECOVERABLE_VS_TERMINAL_DISTINCTION_IS_EXPLICIT_PR_F_POLICY,
        )
        assert "recoverable" in RECOVERABLE_VS_TERMINAL_DISTINCTION_IS_EXPLICIT_PR_F_POLICY.lower()
        assert "terminal" in RECOVERABLE_VS_TERMINAL_DISTINCTION_IS_EXPLICIT_PR_F_POLICY.lower()

    def test_restoration_hook_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            RESTORATION_HOOK_ASSOCIATES_RESUMED_EXECUTION_PR_F_POLICY,
        )
        assert "associate_resumed_execution" in RESTORATION_HOOK_ASSOCIATES_RESUMED_EXECUTION_PR_F_POLICY

    def test_migration_compatibility_policy(self):
        from core.runtime.source_dispatch_orchestrator import (
            EXISTING_EXECUTION_PATHS_REMAIN_FUNCTIONAL_DURING_MIGRATION_PR_F_POLICY,
        )
        assert "backward" in EXISTING_EXECUTION_PATHS_REMAIN_FUNCTIONAL_DURING_MIGRATION_PR_F_POLICY.lower()


# ---------------------------------------------------------------------------
# W. RESUMED_EXECUTION_ASSOCIATION sentinel importable from mesh_session_lifecycle
# ---------------------------------------------------------------------------


class TestResumedExecutionAssociationSentinel:
    """RESUMED_EXECUTION_ASSOCIATION sentinel importable from mesh_session_lifecycle."""

    def test_sentinel_importable(self):
        from core.mesh.mesh_session_lifecycle import (
            RESUMED_EXECUTION_ASSOCIATION_IS_RESTORATION_PATH_POLICY,
        )
        assert RESUMED_EXECUTION_ASSOCIATION_IS_RESTORATION_PATH_POLICY
        assert "associate_resumed_execution" in RESUMED_EXECUTION_ASSOCIATION_IS_RESTORATION_PATH_POLICY


# ---------------------------------------------------------------------------
# X. Backward compatibility — existing dispatch paths work without continuity_context
# ---------------------------------------------------------------------------


class TestBackwardCompatibilityNoContext:
    """Existing execution paths remain functional without continuity_context."""

    def test_source_dispatch_plan_works_without_continuity(self):
        from contracts.source_dispatch import build_source_dispatch_plan, SourceDispatchMode
        plan = build_source_dispatch_plan(mode=SourceDispatchMode.local)
        assert plan.mode == SourceDispatchMode.local
        assert plan.continuity_context is None

    def test_source_dispatch_result_works_without_continuity(self):
        from contracts.source_dispatch import build_source_dispatch_result, SourceDispatchMode
        result = build_source_dispatch_result(
            mode=SourceDispatchMode.fallback_local,
            success=True,
        )
        assert result.mode == SourceDispatchMode.fallback_local
        assert result.continuity_context is None

    def test_task_envelope_works_without_continuity(self):
        from core.schemas.task_envelope import TaskEnvelope
        env = TaskEnvelope(tool_name="test_tool", source="test")
        assert env.continuity_context is None
        assert env.tool_name == "test_tool"

    def test_failure_dispatch_result_works_without_continuity(self):
        from contracts.source_dispatch import failure_dispatch_result, SourceDispatchMode
        result = failure_dispatch_result(
            dispatch_id="d_test",
            mode=SourceDispatchMode.remote_handoff,
            reason="handoff_failed",
        )
        assert result.success is False
        assert result.continuity_context is None
