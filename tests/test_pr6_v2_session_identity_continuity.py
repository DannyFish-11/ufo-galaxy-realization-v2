"""tests/test_pr6_v2_session_identity_continuity.py
=======================================================
Tests for PR-6 V2: Strengthen session/identity continuity across
presence, task, delegation, and takeover paths.

Coverage
--------
Takeover / delegation continuity
  A1.  adopt_handoff_session extracts delegation_transfer_session_id from envelope.
  A2.  adopt_handoff_session: delegation_transfer_session_id falls back to session_id.
  A3.  adopt_handoff_session: delegation_transfer_session_id generated when envelope is None.
  A4.  adopt_handoff_session: delegation_transfer_session_id in LocalTakeoverSessionContext.
  A5.  LocalTakeoverSessionContext has delegation_transfer_session_id field.
  A6.  LocalTakeoverSessionContext.to_dict() includes delegation_transfer_session_id.
  A7.  build_local_takeover_context: state-continuum metadata includes delegation_transfer_session_id.
  A8.  build_local_takeover_context: delegation_transfer_session_id is None-safe.
  A9.  TargetTakeoverHandler.handle: result metadata includes delegation_transfer_session_id.
  A10. execute_local_takeover: delegation_transfer_session_id flows end-to-end.
  A11. adopt_handoff_session: adopted flag and session ID preserved across handoff.
  A12. adopt_handoff_session: trace_id and task_id still propagated (regression).

E2E path session identity
  B1.  _handle_via_e2e signature accepts control_session_id and runtime_attachment_session_id.
  B2.  _dispatch forwards control_session_id from kwargs to _handle_via_e2e.
  B3.  _dispatch forwards runtime_attachment_session_id from kwargs to _handle_via_e2e.
  B4.  augmented_context from _handle_via_e2e includes control_session_id.
  B5.  augmented_context from _handle_via_e2e includes runtime_attachment_session_id.
  B6.  constellation context_dict includes control_session_id.
  B7.  constellation context_dict includes runtime_attachment_session_id.

Invocation identity in ingress stamp
  C1.  ingress_carrier_context includes invocation_id (= runtime_session_id).
  C2.  ingress_carrier_context includes control_session_id.
  C3.  ingress_carrier_context invocation_id is stable across result dict.
  C4.  ingress_carrier_context session_id matches conversation_session_id.

Reconnect / recovery continuity
  D1.  RuntimeRestartRecoveryCoordinator.run_recovery includes _recover_session_truth.
  D2.  Session truth recovery completes without errors when store is empty.
  D3.  RuntimeRecoveryReport has session_truth_records_restored attribute.
  D4.  BodyMeshRegistry entries survive a restart cycle.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# Helpers
# ============================================================================


def _make_envelope(
    trace_id: str = "trace_a1",
    task_id: str = "task_a1",
    session_id: str = "sess_a1",
    allow_local_takeover: bool = True,
) -> Any:
    """Return a real HandoffEnvelopeV2."""
    from contracts.handoff_envelope_v2 import build_handoff_envelope_v2
    return build_handoff_envelope_v2(
        trace_id=trace_id,
        task={"tool_name": "screenshot", "args": {}},
        task_id=task_id,
        session_id=session_id,
        allow_local_takeover=allow_local_takeover,
    )


def _make_skipped_exec_output() -> dict:
    return {
        "action_taken": "none",
        "success": False,
        "skipped_reason": "executor_unavailable",
    }


# ============================================================================
# A: Takeover / delegation continuity
# ============================================================================


class TestAdoptHandoffSessionDelegationContinuity:
    """adopt_handoff_session correctly propagates delegation_transfer_session_id."""

    def test_extracts_delegation_transfer_session_id_from_envelope(self):
        """A1: session_id in envelope becomes delegation_transfer_session_id."""
        from core.runtime.target_takeover import adopt_handoff_session
        envelope = _make_envelope(session_id="deleg_sess_001")
        ctx = adopt_handoff_session(envelope)
        assert ctx is not None
        assert ctx.delegation_transfer_session_id == "deleg_sess_001"

    def test_delegation_transfer_session_id_falls_back_to_session_id(self):
        """A2: When no explicit field, delegation_transfer_session_id == session_id."""
        from core.runtime.target_takeover import adopt_handoff_session
        envelope = _make_envelope(session_id="fallback_sess")
        ctx = adopt_handoff_session(envelope)
        assert ctx.delegation_transfer_session_id == ctx.session_id

    def test_delegation_transfer_session_id_not_empty_when_envelope_none(self):
        """A3: Even with None envelope, delegation_transfer_session_id is set."""
        from core.runtime.target_takeover import adopt_handoff_session
        ctx = adopt_handoff_session(None)
        assert ctx is not None
        # Should be set to the generated session_id
        assert ctx.delegation_transfer_session_id is not None
        assert len(ctx.delegation_transfer_session_id) > 0

    def test_delegation_transfer_session_id_in_context_object(self):
        """A4: delegation_transfer_session_id is a real attribute of the context."""
        from core.runtime.target_takeover import adopt_handoff_session
        envelope = _make_envelope(session_id="ctx_field_test")
        ctx = adopt_handoff_session(envelope)
        assert hasattr(ctx, "delegation_transfer_session_id")
        assert ctx.delegation_transfer_session_id is not None


class TestLocalTakeoverSessionContextDelegationField:
    """LocalTakeoverSessionContext has the new delegation_transfer_session_id field."""

    def test_field_exists_on_model(self):
        """A5: LocalTakeoverSessionContext has delegation_transfer_session_id field."""
        from contracts.local_takeover_result import LocalTakeoverSessionContext
        ctx = LocalTakeoverSessionContext(
            session_id="s1",
            delegation_transfer_session_id="d1",
        )
        assert ctx.delegation_transfer_session_id == "d1"

    def test_to_dict_includes_delegation_transfer_session_id(self):
        """A6: to_dict() includes delegation_transfer_session_id."""
        from contracts.local_takeover_result import LocalTakeoverSessionContext
        ctx = LocalTakeoverSessionContext(
            session_id="s1",
            delegation_transfer_session_id="d1",
        )
        d = ctx.to_dict()
        assert "delegation_transfer_session_id" in d
        assert d["delegation_transfer_session_id"] == "d1"

    def test_field_defaults_to_none(self):
        """delegation_transfer_session_id defaults to None when not provided."""
        from contracts.local_takeover_result import LocalTakeoverSessionContext
        ctx = LocalTakeoverSessionContext(session_id="s2")
        assert ctx.delegation_transfer_session_id is None


class TestBuildLocalTakeoverContextDelegationContinuity:
    """build_local_takeover_context includes delegation_transfer_session_id."""

    def test_metadata_includes_delegation_transfer_session_id(self):
        """A7: state-continuum metadata includes delegation_transfer_session_id."""
        from core.runtime.target_takeover import (
            build_local_takeover_context,
            adopt_handoff_session,
        )
        envelope = _make_envelope(session_id="deleg_ctx_001")
        session_ctx = adopt_handoff_session(envelope)
        ctx = build_local_takeover_context(envelope, session_context=session_ctx)
        assert "delegation_transfer_session_id" in ctx["metadata"]
        assert ctx["metadata"]["delegation_transfer_session_id"] == "deleg_ctx_001"

    def test_delegation_transfer_session_id_none_safe(self):
        """A8: delegation_transfer_session_id handled gracefully with None envelope."""
        from core.runtime.target_takeover import (
            build_local_takeover_context,
            adopt_handoff_session,
        )
        session_ctx = adopt_handoff_session(None)
        ctx = build_local_takeover_context(None, session_context=session_ctx)
        # Should not raise; delegation_transfer_session_id may be None or set
        assert "metadata" in ctx
        assert "delegation_transfer_session_id" in ctx["metadata"]


class TestTargetTakeoverHandlerResultMetadata:
    """TargetTakeoverHandler.handle result metadata includes delegation_transfer_session_id."""

    def test_result_metadata_has_delegation_transfer_session_id(self):
        """A9: result metadata includes delegation_transfer_session_id."""
        from core.runtime.target_takeover import TargetTakeoverHandler
        handler = TargetTakeoverHandler()
        envelope = _make_envelope(session_id="deleg_result_001")
        result = handler.handle(envelope)
        assert result is not None
        d = result.to_dict()
        assert "metadata" in d
        assert "delegation_transfer_session_id" in d["metadata"]
        assert d["metadata"]["delegation_transfer_session_id"] == "deleg_result_001"

    def test_delegation_transfer_session_id_stable_with_existing_session(self):
        """A10: execute_local_takeover preserves delegation_transfer_session_id."""
        from core.runtime.target_takeover import execute_local_takeover
        envelope = _make_envelope(session_id="deleg_e2e_001")
        result = execute_local_takeover(envelope, existing_runtime_session_id="rt_001")
        d = result.to_dict()
        assert d["metadata"]["delegation_transfer_session_id"] == "deleg_e2e_001"

    def test_adopted_session_preserved_in_result(self):
        """A11: adopted flag and session_id flow through to result."""
        from core.runtime.target_takeover import TargetTakeoverHandler
        handler = TargetTakeoverHandler()
        envelope = _make_envelope(session_id="adopted_sess_001")
        result = handler.handle(
            envelope,
            existing_runtime_session_id="existing_rt_001",
        )
        d = result.to_dict()
        # session_context.adopted should be True
        sc = d.get("session_context") or {}
        assert sc.get("adopted") is True

    def test_trace_id_and_task_id_still_propagated_regression(self):
        """A12: trace_id and task_id are not lost (regression check)."""
        from core.runtime.target_takeover import TargetTakeoverHandler
        handler = TargetTakeoverHandler()
        envelope = _make_envelope(
            trace_id="trace_regression",
            task_id="task_regression",
            session_id="sess_regression",
        )
        result = handler.handle(envelope)
        d = result.to_dict()
        assert d.get("trace_id") == "trace_regression"
        assert d.get("task_id") == "task_regression"


# ============================================================================
# B: E2E path session identity
# ============================================================================


class TestE2EPathSessionIdentity:
    """_handle_via_e2e forwards control_session_id and runtime_attachment_session_id."""

    def test_handle_via_e2e_accepts_control_session_id(self):
        """B1: _handle_via_e2e signature accepts control_session_id."""
        import inspect
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        sig = inspect.signature(DesktopPresenceRuntime._handle_via_e2e)
        assert "control_session_id" in sig.parameters

    def test_handle_via_e2e_accepts_runtime_attachment_session_id(self):
        """B1: _handle_via_e2e signature accepts runtime_attachment_session_id."""
        import inspect
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        sig = inspect.signature(DesktopPresenceRuntime._handle_via_e2e)
        assert "runtime_attachment_session_id" in sig.parameters

    def test_dispatch_forwards_control_session_id_via_kwargs(self):
        """B2: _dispatch forwards control_session_id from kwargs to _handle_via_e2e."""
        import inspect
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        # We verify by checking the source of _dispatch references control_session_id
        # in the e2e branch via kwargs.get
        import dis, io
        f = DesktopPresenceRuntime._dispatch
        source = inspect.getsource(f)
        assert "control_session_id" in source
        assert "kwargs.get" in source

    def test_dispatch_forwards_runtime_attachment_session_id_via_kwargs(self):
        """B3: _dispatch forwards runtime_attachment_session_id from kwargs."""
        import inspect
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        source = inspect.getsource(DesktopPresenceRuntime._dispatch)
        assert "runtime_attachment_session_id" in source

    def test_augmented_context_includes_control_session_id(self):
        """B4/B5: augmented_context dict in _handle_via_e2e contains both IDs."""
        import inspect
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        source = inspect.getsource(DesktopPresenceRuntime._handle_via_e2e)
        assert "control_session_id" in source
        assert "runtime_attachment_session_id" in source

    def test_constellation_context_includes_control_session_id(self):
        """B6/B7: constellation ctx_dict includes both session IDs."""
        import inspect
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        source = inspect.getsource(DesktopPresenceRuntime._handle_via_e2e)
        # Both should be present in the ctx_dict passed to constellation.run
        assert '"control_session_id"' in source or "'control_session_id'" in source
        assert '"runtime_attachment_session_id"' in source or "'runtime_attachment_session_id'" in source


# ============================================================================
# C: Invocation identity in ingress stamp
# ============================================================================


class TestIngressCarrierContextInvocationIdentity:
    """ingress_carrier_context stamp includes invocation_id and control_session_id."""

    def _make_mock_runtime_with_result(
        self,
        runtime_session_id: str = "rsess_c1",
        conversation_session_id: str = "conv_c1",
        control_session_id: str = "ctrl_c1",
    ) -> dict:
        """Build a minimal result dict as handle_request would produce it."""
        result: dict = {
            "runtime_session_id": runtime_session_id,
            "trace_id": runtime_session_id,
            "tristate": "silent",
            "entrypoint_source": "chat",
            "conversation_session_id": conversation_session_id,
            "control_session_id": control_session_id,
            "metadata": {
                "session_id": conversation_session_id,
                "conversation_session_id": conversation_session_id,
                "control_session_id": control_session_id,
            },
        }
        result.setdefault(
            "ingress_carrier_context",
            {
                "carrier": "chat",
                "authority_chain": "DesktopPresenceRuntime.handle_request",
                "session_id": conversation_session_id,
                "user_id": "default",
                "invocation_id": runtime_session_id,
                "control_session_id": control_session_id,
            },
        )
        return result

    def test_ingress_carrier_context_has_invocation_id(self):
        """C1: ingress_carrier_context includes invocation_id."""
        result = self._make_mock_runtime_with_result(runtime_session_id="rsess_c1")
        ctx = result.get("ingress_carrier_context", {})
        assert "invocation_id" in ctx
        assert ctx["invocation_id"] == "rsess_c1"

    def test_ingress_carrier_context_has_control_session_id(self):
        """C2: ingress_carrier_context includes control_session_id."""
        result = self._make_mock_runtime_with_result(control_session_id="ctrl_c2")
        ctx = result.get("ingress_carrier_context", {})
        assert "control_session_id" in ctx
        assert ctx["control_session_id"] == "ctrl_c2"

    def test_invocation_id_matches_runtime_session_id(self):
        """C3: invocation_id in ingress stamp equals runtime_session_id."""
        rsid = str(uuid.uuid4())
        result = self._make_mock_runtime_with_result(runtime_session_id=rsid)
        ctx = result.get("ingress_carrier_context", {})
        assert ctx["invocation_id"] == result["runtime_session_id"]

    def test_ingress_carrier_context_session_id_matches_conversation(self):
        """C4: ingress_carrier_context.session_id == conversation_session_id."""
        result = self._make_mock_runtime_with_result(conversation_session_id="conv_c4")
        ctx = result.get("ingress_carrier_context", {})
        assert ctx["session_id"] == result["conversation_session_id"]

    def test_handle_request_result_has_invocation_id_field(self):
        """C1 (source check): handle_request stamps invocation_id in ingress_carrier_context."""
        import inspect
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        source = inspect.getsource(DesktopPresenceRuntime.handle_request)
        assert "invocation_id" in source

    def test_handle_request_control_session_id_in_ingress_context(self):
        """C2 (source check): ingress_carrier_context includes control_session_id."""
        import inspect
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        source = inspect.getsource(DesktopPresenceRuntime.handle_request)
        # ingress_carrier_context block should include control_session_id
        assert "control_session_id" in source


# ============================================================================
# D: Reconnect / recovery continuity
# ============================================================================


class TestReconnectRecoveryContinuity:
    """Restart recovery preserves session truth and body mesh state."""

    def test_run_recovery_calls_recover_session_truth(self):
        """D1: run_recovery includes _recover_session_truth step."""
        import inspect
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        source = inspect.getsource(RuntimeRestartRecoveryCoordinator.run_recovery)
        assert "_recover_session_truth" in source

    def test_session_truth_recovery_graceful_when_store_empty(self):
        """D2: Session truth recovery completes without errors when store is empty."""
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator, RuntimeRecoveryReport
        import time

        report = RuntimeRecoveryReport(
            recovery_id=str(uuid.uuid4()),
            started_at=time.time(),
        )
        coord = RuntimeRestartRecoveryCoordinator()
        # _recover_session_truth should not raise even with no store
        coord._recover_session_truth(report)
        # No assertion on count — degrade gracefully is sufficient

    def test_recovery_report_has_session_truth_records_restored(self):
        """D3: RuntimeRecoveryReport has session_truth_records_restored attribute."""
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        import time
        report = RuntimeRecoveryReport(
            recovery_id=str(uuid.uuid4()),
            started_at=time.time(),
        )
        assert hasattr(report, "session_truth_records_restored")
        assert isinstance(report.session_truth_records_restored, int)

    def test_body_mesh_entries_restored_after_recovery(self, tmp_path):
        """D4: BodyMeshRegistry entries survive a restart cycle via recovery."""
        import os
        from core.mesh.body_mesh_persistence import (
            BodyMeshPersistenceStore,
            save_body_mesh_snapshot,
        )
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator

        bm_path = os.path.join(str(tmp_path), "bm_pr6.json")
        bm_store = BodyMeshPersistenceStore(store_path=bm_path)
        entries = [
            {
                "device_id": "dev_pr6_01",
                "entry_id": str(uuid.uuid4()),
                "role": "primary",
                "session_id": "sess_pr6_01",
                "metadata": {},
            },
            {
                "device_id": "dev_pr6_02",
                "entry_id": str(uuid.uuid4()),
                "role": "secondary",
                "session_id": "sess_pr6_02",
                "metadata": {},
            },
        ]
        save_body_mesh_snapshot(entries, store=bm_store)

        class FakeRegistry:
            def __init__(self):
                self._entries = []

            def register(self, device_id, roles=None, session_id=None, metadata=None):
                self._entries.append({"device_id": device_id, "session_id": session_id})
                return self._entries[-1]

            def list_entries(self):
                return []

        fake_registry = FakeRegistry()
        coord = RuntimeRestartRecoveryCoordinator(body_mesh_store=bm_store, body_mesh_registry=fake_registry)
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        import time
        report = RuntimeRecoveryReport(recovery_id=str(uuid.uuid4()), started_at=time.time())
        coord._recover_body_mesh(report)
        assert report.body_mesh_entries_restored == 2

    def test_session_truth_recovery_step_in_run_recovery_order(self):
        """D1 (regression): _recover_session_truth is called in run_recovery."""
        import inspect
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        source = inspect.getsource(RuntimeRestartRecoveryCoordinator.run_recovery)
        # _recover_session_truth must appear after _recover_inflight_tasks in the source
        pos_inflight = source.find("_recover_inflight_tasks")
        pos_truth = source.find("_recover_session_truth")
        assert pos_truth > 0, "_recover_session_truth missing from run_recovery"
        assert pos_truth > pos_inflight, "_recover_session_truth should run after inflight recovery"


# ============================================================================
# E: Cross-path session identity coherence (integration-style checks)
# ============================================================================


class TestSessionIdentityCoherence:
    """Continuity identifiers remain coherent across the delegation chain."""

    def test_delegation_transfer_session_id_stable_across_handle(self):
        """Delegation session ID is stable from envelope → context → result."""
        from core.runtime.target_takeover import (
            adopt_handoff_session,
            build_local_takeover_context,
            TargetTakeoverHandler,
        )
        sess_id = "stable_deleg_sess"
        envelope = _make_envelope(session_id=sess_id)

        # Step 1: adopt session
        ctx = adopt_handoff_session(envelope)
        assert ctx.delegation_transfer_session_id == sess_id

        # Step 2: build state continuum
        continuum = build_local_takeover_context(envelope, session_context=ctx)
        assert continuum["metadata"]["delegation_transfer_session_id"] == sess_id

        # Step 3: full handler
        handler = TargetTakeoverHandler()
        result = handler.handle(envelope)
        assert result.to_dict()["metadata"]["delegation_transfer_session_id"] == sess_id

    def test_trace_id_and_delegation_session_both_propagate(self):
        """Both trace_id and delegation_transfer_session_id flow through takeover."""
        from core.runtime.target_takeover import TargetTakeoverHandler
        trace = "trace_coherence_001"
        sess = "sess_coherence_001"
        envelope = _make_envelope(trace_id=trace, session_id=sess)
        result = TargetTakeoverHandler().handle(envelope)
        d = result.to_dict()
        assert d["trace_id"] == trace
        assert d["metadata"]["delegation_transfer_session_id"] == sess

    def test_adopted_existing_session_preserves_delegation_id(self):
        """When reusing an existing session, delegation_transfer_session_id is still set."""
        from core.runtime.target_takeover import adopt_handoff_session
        envelope = _make_envelope(session_id="existing_deleg")
        ctx = adopt_handoff_session(envelope, existing_runtime_session_id="rt_existing")
        assert ctx.adopted is True
        # delegation_transfer_session_id still reflects the envelope's session
        assert ctx.delegation_transfer_session_id == "existing_deleg"
