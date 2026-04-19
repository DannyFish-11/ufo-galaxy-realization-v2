"""tests/test_prg_observability_production_hooks.py
====================================================
PR-G4 / PR-4: Production observability emit hooks and automated contract
gate validation.

Coverage
--------
This module validates three acceptance criteria from the PR-4 problem statement:

1. **Four emit kinds are genuinely called in key production paths**:
   A. ``emit_device_lifecycle_event`` (attach) is called by
      ``galaxy_gateway.android.handlers.registration.handle_device_register``.
   B. ``emit_device_lifecycle_event`` (detach) is called by
      ``galaxy_gateway.android_bridge.AndroidBridge.disconnect_device``.
   C. ``emit_device_lifecycle_event`` (reconnect) is called by
      ``galaxy_gateway.android_bridge.AndroidBridge.reconnect_device``.
   D. ``emit_mesh_session_transition_event`` (create) is called by
      ``core.mesh.mesh_session_lifecycle.MeshSessionLifecycleCoordinator.create_session``.
   E. ``emit_mesh_session_transition_event`` (activate) is called by
      ``core.mesh.mesh_session_lifecycle.MeshSessionLifecycleCoordinator.activate_session``.
   F. ``emit_mesh_session_transition_event`` (suspend) is called by
      ``core.mesh.mesh_session_lifecycle.MeshSessionLifecycleCoordinator.suspend_session``.
   G. ``emit_mesh_session_transition_event`` (terminate) is called by
      ``core.mesh.mesh_session_lifecycle.MeshSessionLifecycleCoordinator.terminate_session``.
   H. ``emit_mesh_session_transition_event`` (restore) + ``emit_recovery_decision_event``
      are called by ``restore_session`` when a session is durably restored.
   I. ``emit_dispatch_decision_event`` is called by
      ``core.command_router.CommandRouter.route_envelope``.

2. **Compatibility / consistency checks enter automated verification**:
   J. ``contracts.contract_compatibility`` validation functions pass on valid
      canonical contract dicts (automated regression gate).
   K. ``core.cross_repo_consistency_gates`` gate runner returns pass/warn
      verdicts without raising (automated regression gate).
   L. The full gate snapshot is JSON-serialisable (CI-suitable output).
   M. Both check suites run together without interference (unified gate).

3. **Stable Android trace round-trip hook**:
   N. ``ANDROID_BRIDGE_TRACE_HOOK_SENTINEL`` is importable and non-empty.
   O. ``get_android_bridge_trace_id`` extracts ``trace_id`` from a message dict.
   P. ``get_android_bridge_trace_id`` extracts ``dispatch_trace_id`` as fallback.
   Q. ``get_android_bridge_trace_id`` returns ``None`` for missing trace fields.
   R. A trace ID extracted via the hook matches a dispatch decision event stored
      in the observability sink (end-to-end correlation).
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_async(coro):
    """Run a coroutine in a temporary event loop (test utility)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===========================================================================
# A–C: Device lifecycle emits — android_bridge paths
# ===========================================================================


class TestDeviceLifecycleEmits:
    """emit_device_lifecycle_event is called from Android bridge production paths."""

    def setup_method(self):
        from core.runtime.runtime_observability_sink import reset_observability_sink
        reset_observability_sink()

    # ── A: attach emit on device registration ────────────────────────────────

    def test_registration_handler_emits_attach(self):
        """handle_device_register emits a device_lifecycle 'attach' event."""
        from core.runtime.runtime_observability_sink import get_observability_sink

        bridge = MagicMock()
        bridge._lock = asyncio.Lock()
        bridge._devices = {}
        bridge._write_registration_to_udm = MagicMock()
        bridge._sync_device_router_session = MagicMock()

        ws = MagicMock()
        message = {
            "device_id": "test_device_attach",
            "type": "device_register",
            "name": "Test Phone",
            "model": "Pixel 7",
            "platform": "android",
        }

        from galaxy_gateway.android.handlers.registration import handle_device_register

        _run_async(handle_device_register(bridge, ws, message))

        sink = get_observability_sink()
        events = sink.list_device_lifecycle_events()
        assert any(
            e.get("device_id") == "test_device_attach" and e.get("event_kind") == "attach"
            for e in events
        ), f"Expected attach event for test_device_attach in {events}"

    # ── B: detach emit on disconnect_device ───────────────────────────────────

    def test_disconnect_device_emits_detach(self):
        """disconnect_device emits a device_lifecycle 'detach' event."""
        from core.runtime.runtime_observability_sink import get_observability_sink
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.android.models import AndroidDevice

        bridge = AndroidBridge()
        device_id = "test_device_detach"

        # Seed a fake connected device
        mock_ws = MagicMock()
        mock_device = MagicMock(spec=AndroidDevice)
        mock_device.connected = True
        mock_device.websocket = mock_ws
        bridge._devices[device_id] = mock_device

        with patch.object(bridge, "_sync_device_router_session"), \
             patch.object(bridge, "_patch_disconnect_to_udm"):
            _run_async(bridge.disconnect_device(device_id))

        sink = get_observability_sink()
        events = sink.list_device_lifecycle_events()
        assert any(
            e.get("device_id") == device_id and e.get("event_kind") == "detach"
            for e in events
        ), f"Expected detach event for {device_id} in {events}"

    # ── C: reconnect emit on reconnect_device ─────────────────────────────────

    def test_reconnect_device_emits_reconnect(self):
        """reconnect_device emits a device_lifecycle 'reconnect' event."""
        from core.runtime.runtime_observability_sink import get_observability_sink
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.android.models import AndroidDevice

        bridge = AndroidBridge()
        device_id = "test_device_reconnect"

        # Seed a disconnected device so reconnect is valid
        mock_device = MagicMock(spec=AndroidDevice)
        mock_device.websocket = None
        mock_device.connected = False
        mock_device.last_heartbeat = 0.0
        bridge._devices[device_id] = mock_device

        mock_ws = MagicMock()
        with patch.object(bridge, "_patch_reconnect_to_udm"), \
             patch.object(bridge, "_sync_device_router_session"):
            result = _run_async(bridge.reconnect_device(device_id, mock_ws))

        assert result is True
        sink = get_observability_sink()
        events = sink.list_device_lifecycle_events()
        assert any(
            e.get("device_id") == device_id and e.get("event_kind") == "reconnect"
            for e in events
        ), f"Expected reconnect event for {device_id} in {events}"


# ===========================================================================
# D–H: Mesh session transition emits — lifecycle coordinator paths
# ===========================================================================


class TestMeshSessionTransitionEmits:
    """emit_mesh_session_transition_event is called from lifecycle coordinator paths."""

    def setup_method(self):
        from core.runtime.runtime_observability_sink import reset_observability_sink
        reset_observability_sink()

    def _make_mock_store(self):
        store = MagicMock()
        store.save = MagicMock()
        store.load = MagicMock(return_value=None)
        store.mark_terminal = MagicMock()
        return store

    def _make_session_dict(self, session_id: Optional[str] = None):
        sid = session_id or uuid.uuid4().hex
        return {
            "session_id": sid,
            "status": "pending",
            "source_device_id": "dev_001",
            "primary_device_id": "dev_001",
        }

    # ── D: create emit ─────────────────────────────────────────────────────────

    def test_create_session_emits_create(self):
        """create_session emits a mesh_session_transition 'create' event."""
        from core.runtime.runtime_observability_sink import get_observability_sink
        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleCoordinator

        store = self._make_mock_store()
        coord = MeshSessionLifecycleCoordinator(store=store)
        sess = self._make_session_dict()

        coord.create_session(sess)

        sink = get_observability_sink()
        events = sink.list_mesh_session_transition_events()
        assert any(
            e.get("session_id") == sess["session_id"] and e.get("transition_kind") == "create"
            for e in events
        ), f"Expected create event for {sess['session_id']} in {events}"

    # ── E: activate emit ───────────────────────────────────────────────────────

    def test_activate_session_emits_activate(self):
        """activate_session emits a mesh_session_transition 'activate' event."""
        from core.runtime.runtime_observability_sink import get_observability_sink
        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleCoordinator

        store = self._make_mock_store()
        coord = MeshSessionLifecycleCoordinator(store=store)
        sess = self._make_session_dict()
        coord.create_session(sess)

        coord.activate_session(sess["session_id"])

        sink = get_observability_sink()
        events = sink.list_mesh_session_transition_events()
        assert any(
            e.get("session_id") == sess["session_id"] and e.get("transition_kind") == "activate"
            for e in events
        ), f"Expected activate event for {sess['session_id']} in {events}"

    # ── F: suspend emit ────────────────────────────────────────────────────────

    def test_suspend_session_emits_suspend(self):
        """suspend_session emits a mesh_session_transition 'suspend' event."""
        from core.runtime.runtime_observability_sink import get_observability_sink
        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleCoordinator

        store = self._make_mock_store()
        coord = MeshSessionLifecycleCoordinator(store=store)
        sess = self._make_session_dict()
        coord.create_session(sess)
        coord.activate_session(sess["session_id"])

        coord.suspend_session(sess["session_id"])

        sink = get_observability_sink()
        events = sink.list_mesh_session_transition_events()
        assert any(
            e.get("session_id") == sess["session_id"] and e.get("transition_kind") == "suspend"
            for e in events
        ), f"Expected suspend event for {sess['session_id']} in {events}"

    # ── G: terminate emit ──────────────────────────────────────────────────────

    def test_terminate_session_emits_terminate(self):
        """terminate_session emits a mesh_session_transition 'terminate' event."""
        from core.runtime.runtime_observability_sink import get_observability_sink
        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleCoordinator

        store = self._make_mock_store()
        coord = MeshSessionLifecycleCoordinator(store=store)
        sess = self._make_session_dict()
        coord.create_session(sess)
        coord.activate_session(sess["session_id"])

        coord.terminate_session(sess["session_id"], outcome="completed")

        sink = get_observability_sink()
        events = sink.list_mesh_session_transition_events()
        assert any(
            e.get("session_id") == sess["session_id"] and e.get("transition_kind") == "terminate"
            for e in events
        ), f"Expected terminate event for {sess['session_id']} in {events}"

    # ── H: restore + recovery_decision emit ───────────────────────────────────

    def test_restore_session_emits_restore_and_recovery(self):
        """restore_session emits both mesh_session_transition 'restore' and
        a recovery_decision 'resumable_reassociation' event."""
        from core.runtime.runtime_observability_sink import get_observability_sink
        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleCoordinator

        sess_id = uuid.uuid4().hex
        sess = {
            "session_id": sess_id,
            "status": "suspended",
            "source_device_id": "dev_restore",
            "primary_device_id": "dev_restore",
        }

        # Mock store that returns a SUSPENDED snapshot so restore_session proceeds
        store = MagicMock()
        snap = MagicMock()
        snap.overall_status = "suspended"
        snap.snapshot_dict = dict(sess)
        snap.is_terminal.return_value = False
        store.load = MagicMock(return_value=snap)
        store.save = MagicMock()
        store.mark_terminal = MagicMock()

        coord = MeshSessionLifecycleCoordinator(store=store)

        # Pre-populate the coordinator with a SUSPENDED record
        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleRecord
        record = MeshSessionLifecycleRecord(
            session_id=sess_id,
            status="suspended",
            session_dict=dict(sess),
        )
        with coord._lock:
            coord._sessions[sess_id] = record

        result = coord.restore_session(sess_id)

        assert result is not None, "restore_session should return an active record"
        assert result.status == "active"

        sink = get_observability_sink()
        mesh_events = sink.list_mesh_session_transition_events()
        recovery_events = sink.list_recovery_decision_events()

        assert any(
            e.get("session_id") == sess_id and e.get("transition_kind") == "restore"
            for e in mesh_events
        ), f"Expected restore mesh event for {sess_id} in {mesh_events}"

        assert any(
            e.get("decision_kind") == "resumable_reassociation"
            for e in recovery_events
        ), f"Expected resumable_reassociation recovery event in {recovery_events}"


# ===========================================================================
# I: Dispatch decision emit — command_router.route_envelope
# ===========================================================================


class TestDispatchDecisionEmit:
    """emit_dispatch_decision_event is called from CommandRouter.route_envelope."""

    def setup_method(self):
        from core.runtime.runtime_observability_sink import reset_observability_sink
        reset_observability_sink()

    def test_route_envelope_emits_dispatch_decision(self):
        """route_envelope emits a dispatch_decision 'plan_selected' event."""
        from core.runtime.runtime_observability_sink import get_observability_sink
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope

        router = CommandRouter()
        task_id = "task_" + uuid.uuid4().hex[:8]
        trace_id = "trace_" + uuid.uuid4().hex[:8]

        envelope = TaskEnvelope(
            task_id=task_id,
            trace_id=trace_id,
            source="test",
            targets=["test_device"],
            tool_name="test_command",
            args={},
        )

        # Patch all downstream dispatch paths to avoid real network calls
        with patch.object(router, "_execute_command", new=AsyncMock(return_value={
            "success": True,
            "task_id": task_id,
            "trace_id": trace_id,
            "result": "ok",
        })):
            _run_async(router.route_envelope(envelope))

        sink = get_observability_sink()
        events = sink.list_dispatch_decision_events()
        assert any(
            e.get("task_id") == task_id and e.get("event_kind") == "plan_selected"
            for e in events
        ), f"Expected plan_selected event for {task_id} in {events}"

    def test_route_envelope_dispatch_event_carries_trace_id(self):
        """The dispatch decision event carries the envelope's trace_id for correlation."""
        from core.runtime.runtime_observability_sink import get_observability_sink
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope

        router = CommandRouter()
        task_id = "task_" + uuid.uuid4().hex[:8]
        trace_id = "trace_" + uuid.uuid4().hex[:8]

        envelope = TaskEnvelope(
            task_id=task_id,
            trace_id=trace_id,
            source="test",
            targets=["device_xyz"],
            tool_name="probe",
            args={},
        )

        with patch.object(router, "_execute_command", new=AsyncMock(return_value={
            "success": True,
            "task_id": task_id,
            "trace_id": trace_id,
            "result": None,
        })):
            _run_async(router.route_envelope(envelope))

        sink = get_observability_sink()
        events = sink.list_dispatch_decision_events()
        matching = [e for e in events if e.get("task_id") == task_id]
        assert matching, f"No dispatch event for task_id={task_id}"
        assert matching[0].get("trace_id") == trace_id


# ===========================================================================
# J–L: Compatibility / consistency checks as automated regression gates
# ===========================================================================


class TestContractCompatibilityAutomatedGate:
    """contract_compatibility checks run as automated regression gate (PR-H)."""

    def test_valid_task_envelope_passes_compatibility_check(self):
        """A valid TaskEnvelope dict passes backward compatibility check."""
        from contracts.contract_compatibility import check_envelope_backward_compatibility

        env_dict = {
            "task_id": uuid.uuid4().hex,
            "trace_id": uuid.uuid4().hex,
            "executor_target_type": "android_device",
            "continuity_context": {"prior_dispatch_id": "disp_123"},
            "metadata": {"observability_metadata": {"trace_correlation": "ok"}},
        }
        report = check_envelope_backward_compatibility(env_dict)
        assert report.is_compatible, f"Expected compatible, got errors: {report.validation_errors}"
        assert report.has_executor_target_type
        assert report.has_continuity_context
        assert report.has_observability_metadata

    def test_pre_evolution_envelope_is_still_compatible(self):
        """A pre-PR-E/F envelope (no evolved fields) is backward-compatible."""
        from contracts.contract_compatibility import check_envelope_backward_compatibility

        env_dict = {
            "task_id": uuid.uuid4().hex,
            "trace_id": uuid.uuid4().hex,
        }
        report = check_envelope_backward_compatibility(env_dict)
        assert report.is_compatible
        assert not report.has_executor_target_type
        assert not report.has_continuity_context

    def test_valid_dispatch_plan_passes_compatibility_check(self):
        """A valid SourceDispatchPlan dict passes backward compatibility check."""
        from contracts.contract_compatibility import check_dispatch_plan_backward_compatibility

        plan_dict = {
            "plan_id": uuid.uuid4().hex,
            "mode": "remote_handoff",
            "continuity_context": {"prior_session_id": "sess_abc"},
        }
        report = check_dispatch_plan_backward_compatibility(plan_dict)
        assert report.is_compatible
        assert report.has_continuity_context

    def test_valid_dispatch_result_passes_compatibility_check(self):
        """A valid SourceDispatchResult dict passes backward compatibility check."""
        from contracts.contract_compatibility import check_dispatch_result_backward_compatibility

        result_dict = {
            "result_id": uuid.uuid4().hex,
            "mode": "local",
            "success": True,
        }
        report = check_dispatch_result_backward_compatibility(result_dict)
        assert report.is_compatible

    def test_contract_compatibility_sentinel_importable(self):
        """Sentinel constants in contracts.contract_compatibility are importable."""
        from contracts.contract_compatibility import (
            CONTRACT_COMPATIBILITY_PR_H_SENTINEL,
            CONTRACT_EVOLUTION_IS_EXPLICIT_POLICY,
            CONTRACT_VALIDATION_IS_AUTHORITY,
            EVOLVED_FIELDS_ARE_OPTIONAL_BACKWARD_COMPAT_POLICY,
            STAGED_MIGRATION_IS_SAFE_POLICY,
        )
        assert CONTRACT_COMPATIBILITY_PR_H_SENTINEL
        assert CONTRACT_EVOLUTION_IS_EXPLICIT_POLICY
        assert CONTRACT_VALIDATION_IS_AUTHORITY
        assert EVOLVED_FIELDS_ARE_OPTIONAL_BACKWARD_COMPAT_POLICY
        assert STAGED_MIGRATION_IS_SAFE_POLICY


class TestCrossRepoConsistencyGatesAutomatedGate:
    """cross_repo_consistency_gates run as automated regression gate (PR-12)."""

    def test_all_consistency_gates_run_without_exception(self):
        """run_all_consistency_gates() returns results without raising."""
        from core.cross_repo_consistency_gates import run_all_consistency_gates

        results = run_all_consistency_gates()
        assert isinstance(results, (list, tuple))
        assert len(results) > 0, "Expected at least one gate result"

    def test_gate_snapshot_is_json_serialisable(self):
        """build_consistency_gate_snapshot() returns a JSON-serialisable dict."""
        import json
        from core.cross_repo_consistency_gates import build_consistency_gate_snapshot

        snapshot = build_consistency_gate_snapshot()
        # Must be serialisable — the CI output pipeline requires this.
        json_str = json.dumps(snapshot.to_dict())
        assert isinstance(json_str, str)
        assert len(json_str) > 0

    def test_individual_gates_return_gate_results(self):
        """Each individual gate runner returns a ConsistencyGateResult."""
        from core.cross_repo_consistency_gates import (
            ConsistencyGateResult,
            run_schema_vocabulary_gate,
            run_session_family_gate,
            run_execution_enum_gate,
            run_terminal_state_gate,
            run_descriptor_field_gate,
            run_transitional_marker_gate,
        )

        for gate_fn in (
            run_schema_vocabulary_gate,
            run_session_family_gate,
            run_execution_enum_gate,
            run_terminal_state_gate,
            run_descriptor_field_gate,
            run_transitional_marker_gate,
        ):
            result = gate_fn()
            assert isinstance(result, ConsistencyGateResult), (
                f"{gate_fn.__name__} should return ConsistencyGateResult"
            )
            # Gates must not raise — they return verdicts
            assert result.verdict in ("pass", "warn", "fail", "skip"), (
                f"Unexpected verdict: {result.verdict}"
            )

    def test_consistency_gates_are_non_breaking(self):
        """run_all_consistency_gates does not raise even when drift is detected."""
        from core.cross_repo_consistency_gates import (
            GATES_ARE_NON_BREAKING_POLICY,
            run_all_consistency_gates,
        )

        assert GATES_ARE_NON_BREAKING_POLICY  # policy sentinel is present
        try:
            run_all_consistency_gates()
        except Exception as exc:
            pytest.fail(f"run_all_consistency_gates raised unexpectedly: {exc}")


class TestUnifiedCompatibilityAndConsistencyGate:
    """Unified gate: both compatibility checks and consistency gates run together."""

    def test_unified_gate_runs_both_check_suites(self):
        """Running both check suites together produces non-empty results."""
        from contracts.contract_compatibility import check_envelope_backward_compatibility
        from core.cross_repo_consistency_gates import (
            build_consistency_gate_snapshot,
            run_all_consistency_gates,
        )

        # Run contract compatibility check
        env_dict = {"task_id": uuid.uuid4().hex, "trace_id": uuid.uuid4().hex}
        compat_report = check_envelope_backward_compatibility(env_dict)
        assert compat_report.is_compatible

        # Run consistency gate check
        gate_results = run_all_consistency_gates()
        assert len(gate_results) > 0

        # Build CI snapshot
        snapshot = build_consistency_gate_snapshot()
        snap_dict = snapshot.to_dict()
        assert "gate_results" in snap_dict or "gates" in snap_dict or snap_dict

    def test_unified_gate_no_cross_contamination(self):
        """Compatibility report and gate results do not interfere with each other."""
        from contracts.contract_compatibility import (
            EvolutionCompatibilityReport,
            check_envelope_backward_compatibility,
        )
        from core.cross_repo_consistency_gates import (
            ConsistencyGateSnapshot,
            build_consistency_gate_snapshot,
        )

        # Both can be called in the same test without import or state issues
        report = check_envelope_backward_compatibility(
            {"task_id": "x", "trace_id": "y", "executor_target_type": "local"}
        )
        snapshot = build_consistency_gate_snapshot()

        assert isinstance(report, EvolutionCompatibilityReport)
        assert isinstance(snapshot, ConsistencyGateSnapshot)


# ===========================================================================
# N–R: Android trace round-trip hook
# ===========================================================================


class TestAndroidTraceHook:
    """ANDROID_BRIDGE_TRACE_HOOK sentinel and get_android_bridge_trace_id hook."""

    def test_trace_hook_sentinel_importable(self):
        """ANDROID_BRIDGE_TRACE_HOOK_SENTINEL is non-empty and importable."""
        from galaxy_gateway.android_bridge import ANDROID_BRIDGE_TRACE_HOOK_SENTINEL

        assert ANDROID_BRIDGE_TRACE_HOOK_SENTINEL
        assert "ANDROID_BRIDGE_TRACE_HOOK_V1" in ANDROID_BRIDGE_TRACE_HOOK_SENTINEL

    def test_get_trace_id_extracts_trace_id(self):
        """get_android_bridge_trace_id extracts trace_id from message dict."""
        from galaxy_gateway.android_bridge import get_android_bridge_trace_id

        trace_id = "tr_" + uuid.uuid4().hex[:8]
        message = {"device_id": "dev_01", "type": "task_result", "trace_id": trace_id}
        result = get_android_bridge_trace_id(message)
        assert result == trace_id

    def test_get_trace_id_fallback_to_dispatch_trace_id(self):
        """get_android_bridge_trace_id falls back to dispatch_trace_id."""
        from galaxy_gateway.android_bridge import get_android_bridge_trace_id

        dtr_id = "dtr_" + uuid.uuid4().hex[:8]
        message = {"device_id": "dev_01", "dispatch_trace_id": dtr_id}
        result = get_android_bridge_trace_id(message)
        assert result == dtr_id

    def test_get_trace_id_returns_none_when_absent(self):
        """get_android_bridge_trace_id returns None when no trace field is present."""
        from galaxy_gateway.android_bridge import get_android_bridge_trace_id

        message = {"device_id": "dev_01", "type": "heartbeat"}
        result = get_android_bridge_trace_id(message)
        assert result is None

    def test_get_trace_id_extracts_from_payload(self):
        """get_android_bridge_trace_id extracts trace_id from nested payload."""
        from galaxy_gateway.android_bridge import get_android_bridge_trace_id

        trace_id = "nested_tr_" + uuid.uuid4().hex[:8]
        message = {
            "device_id": "dev_01",
            "type": "task_result",
            "payload": {"trace_id": trace_id, "result": "ok"},
        }
        result = get_android_bridge_trace_id(message)
        assert result == trace_id

    def test_trace_hook_correlates_with_dispatch_event(self):
        """A trace ID extracted via the hook matches a dispatch decision sink event."""
        from core.runtime.runtime_observability_sink import (
            emit_dispatch_decision_event,
            get_observability_sink,
            reset_observability_sink,
        )
        from galaxy_gateway.android_bridge import get_android_bridge_trace_id

        reset_observability_sink()
        trace_id = "corr_tr_" + uuid.uuid4().hex[:8]
        task_id = "corr_task_" + uuid.uuid4().hex[:8]

        # Simulate V2 emitting a dispatch decision with this trace_id
        emit_dispatch_decision_event(
            mode="remote_handoff",
            event_kind="plan_selected",
            dispatch_id=task_id,
            trace_id=trace_id,
            task_id=task_id,
            decision_reason="test_correlation",
            success=True,
        )

        # Simulate Android returning a message carrying the same trace_id
        android_message = {
            "device_id": "android_dev",
            "type": "task_result",
            "trace_id": trace_id,
            "result": "success",
        }
        extracted_trace_id = get_android_bridge_trace_id(android_message)
        assert extracted_trace_id == trace_id

        # Verify correlation: the extracted trace_id matches an event in the sink
        sink = get_observability_sink()
        dispatch_events = sink.list_dispatch_decision_events()
        matched = [e for e in dispatch_events if e.get("trace_id") == extracted_trace_id]
        assert matched, (
            f"No dispatch event with trace_id={extracted_trace_id} found in sink. "
            f"Sink events: {dispatch_events}"
        )
        assert matched[0].get("task_id") == task_id
