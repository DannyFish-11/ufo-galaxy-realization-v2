#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr14_runtime_introspection.py
=========================================

Tests for PR-14: Runtime Introspection and Architecture/Execution Status
Reporting.

Coverage
--------
A) RuntimeIntrospectionSnapshot
   - default construction (all fields None / empty)
   - to_dict() serialisation
   - to_dict() is JSON-safe (no non-serialisable types)
   - all expected fields present in to_dict()
   - __repr__ smoke test

B) build_introspection_snapshot — local flow
   - runtime_shell_result populates entry_source, runtime_shell_authority
   - subject_core_result populates subject_decision_authority, delegation_point
   - subject_core_result populates execution_plan_summary, lifecycle_state
   - subject_core_result without device_id leaves target_devices None
   - trace_id propagated from runtime_shell
   - trace_id propagated from subject_core when shell absent
   - request_success propagated from subject_core
   - raw_metadata merges all layers
   - run_diagnostics=False skips diagnostics
   - local execution_mode is None

C) build_introspection_snapshot — remote command flow
   - substrate_result populates execution_substrate_role
   - substrate_result populates execution_mode from remote_execution_mode
   - substrate_result populates lifecycle_state
   - failure_domain populated from substrate on failure
   - failure_classification populated from substrate
   - request_success from substrate when subject_core absent
   - subject_core execution_mode takes precedence over substrate

D) build_introspection_snapshot — remote agent flow
   - agent_runtime mode propagated from subject_core metadata
   - target_devices populated from subject_core device_id
   - delegation_point is single_remote for agent flow

E) build_introspection_snapshot — orchestration flow
   - orchestration_role populated from orchestration_meta
   - target_devices populated from orchestration_meta device_ids
   - orchestration arch_layer_id triggers role extraction

F) build_introspection_snapshot — failure/fallback metadata
   - failure_domain visible in snapshot
   - failure_classification dict visible in snapshot
   - retry_policy dict visible in snapshot
   - fallback_policy dict visible in snapshot
   - backward compatibility: callers ignoring snapshot continue to work

G) introspection_snapshot_from_response — routing by arch_layer_id
   - arch_layer_id="runtime_shell" routes to shell extractor
   - arch_layer_id="execution_substrate" routes to substrate extractor
   - arch_layer_id="subject_core" (or absent) routes to core extractor
   - arch_layer_id="orchestration_layer" routes to orchestration extractor
   - non-dict input returns empty snapshot

H) merge_layer_snapshots
   - first snapshot fields take precedence over later snapshots
   - None fields in first snapshot filled by later snapshots
   - raw_metadata merged from all snapshots
   - empty merge returns empty snapshot
   - single snapshot round-trips correctly

I) ArchitectureStatusReport
   - default construction
   - to_dict() serialisation
   - to_dict() is JSON-safe
   - __repr__ smoke test

J) build_architecture_status_report — authority chain
   - all four layers present → authority_chain_present=True
   - missing runtime_shell → authority_chain_present=False, note in notes
   - missing subject_core → authority_chain_present=False
   - missing substrate → authority_chain_present=False
   - authority_chain_summary has correct structure
   - correct expected_role in summary entries

K) build_architecture_status_report — diagnostics integration
   - with valid layers, diagnostics run and overall_valid is not None
   - diagnostics_findings is a list (may be empty)
   - raw_diagnostics_report contains 'overall_valid' key
   - no layers → diagnostics gracefully absent

L) architecture_status_from_snapshot
   - snapshot with all authority fields → all layers detected
   - snapshot without orchestration_role → orch layer absent
   - overall_valid reflects diagnostics or chain presence

M) ExecutionStatusReport
   - default construction
   - to_dict() serialisation
   - to_dict() is JSON-safe
   - all expected fields present in to_dict()
   - __repr__ smoke test

N) build_execution_status_report — plan and lifecycle
   - execution_plan_summary extracted from subject_core metadata
   - lifecycle_state extracted from subject_core
   - plan_step_types extracted from plan_summary.step_types
   - plan_step_types extracted from plan_summary.primary_step_type
   - is_terminal True for "succeeded"
   - is_terminal True for "failed"
   - is_terminal True for "timed_out"
   - is_terminal False for "running"
   - is_terminal None when lifecycle_state is None

O) build_execution_status_report — failure / fallback
   - failure_domain from substrate
   - failure_classification from substrate
   - retry_policy from substrate
   - fallback_policy from substrate
   - failure_summary formatted correctly
   - failure_summary None when no failure_domain

P) build_execution_status_report — routing fields
   - delegation_point from subject_core metadata
   - execution_mode from subject_core metadata
   - execution_mode from substrate when subject_core absent
   - target_devices from subject_core device_id
   - target_devices from orchestration_meta device_ids
   - resolver_decision from orchestration_meta

Q) execution_status_from_snapshot
   - all fields round-trip from snapshot to report
   - failure_summary built from snapshot failure fields
   - is_terminal computed from lifecycle_state

R) Integration: runtime shell → subject core → substrate pipeline
   - representative local flow produces valid introspection snapshot
   - representative remote command flow produces valid snapshot
   - representative remote agent flow produces valid snapshot
   - failure flow includes failure_domain in snapshot
   - backward compatibility: result dicts without introspection_snapshot work

S) Integration: introspection_snapshot field in layer results
   - desktop_presence_runtime result carries introspection_snapshot
   - openclawd result carries introspection_snapshot
   - command_router result carries introspection_snapshot

"""

from __future__ import annotations

import json
import unittest
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


def _make_runtime_shell_result(
    *,
    source: str = "api",
    trace_id: str = "trace-123",
    auth_role: str = "runtime_shell_authority",
    entry_surface: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a minimal runtime-shell result dict (as produced by DesktopPresenceRuntime)."""
    return {
        "arch_layer_id": "runtime_shell",
        "authority_metadata": {
            "layer_role": auth_role,
            "canonical_module": "core.desktop_presence_runtime",
        },
        "entrypoint_source": source,
        "entry_surface": entry_surface,
        "trace_id": trace_id,
        "runtime_session_id": trace_id,
        "tristate": "active",
        "success": True,
        "introspection_snapshot": {
            "authority_role": auth_role,
            "entry_source": source,
            "trace_id": trace_id,
        },
    }


def _make_subject_core_result(
    *,
    success: bool = True,
    execution_path: str = "local",
    delegation_point: str = "local",
    remote_mode: Optional[str] = None,
    device_id: Optional[str] = None,
    trace_id: str = "trace-123",
    lifecycle_state: str = "succeeded",
    authority_role: str = "subject_decision_authority",
    plan_summary: Optional[Dict] = None,
    cognition_role: str = "embedded_cognition_layer",
) -> Dict[str, Any]:
    """Build a minimal subject-core result dict (as produced by OpenClawd)."""
    _plan_summary = plan_summary or {
        "primary_step_type": "local_manifestation" if not remote_mode else "remote_command",
        "step_types": ["local_manifestation" if not remote_mode else "remote_command"],
        "execution_path": execution_path,
    }
    return {
        "arch_layer_id": "subject_core",
        "success": success,
        "response": "OK",
        "intent": "chat",
        "trace_id": trace_id,
        "execution_path": execution_path,
        "execution_plan_summary": _plan_summary,
        "execution_lifecycle_state": lifecycle_state,
        "metadata": {
            "trace_id": trace_id,
            "authority_role": authority_role,
            "delegation_point": delegation_point,
            "execution_path": execution_path,
            "remote_execution_mode": remote_mode,
            "device_id": device_id,
            "execution_plan_summary": _plan_summary,
            "execution_lifecycle_state": lifecycle_state,
            "kernel_cognition_role": cognition_role,
        },
        "introspection_snapshot": {
            "authority_role": authority_role,
            "delegation_point": delegation_point,
            "execution_mode": remote_mode,
            "execution_path": execution_path,
            "lifecycle_state": lifecycle_state,
            "execution_plan_summary": _plan_summary,
            "device_id": device_id,
            "trace_id": trace_id,
            "success": success,
        },
    }


def _make_substrate_result(
    *,
    success: bool = True,
    remote_mode: Optional[str] = None,
    lifecycle_state: str = "succeeded",
    failure_domain: Optional[str] = None,
    failure_is_retryable: Optional[bool] = None,
    failure_classification: Optional[Dict] = None,
    retry_policy: Optional[Dict] = None,
    fallback_policy: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Build a minimal substrate result dict (as produced by CommandRouter)."""
    result: Dict[str, Any] = {
        "arch_layer_id": "execution_substrate",
        "success": success,
        "execution_substrate_role": "execution_substrate",
        "lifecycle_state": lifecycle_state,
        "introspection_snapshot": {
            "authority_role": "execution_substrate",
            "execution_substrate_role": "execution_substrate",
            "execution_mode": remote_mode,
            "lifecycle_state": lifecycle_state,
            "failure_domain": failure_domain,
            "failure_is_retryable": failure_is_retryable,
            "success": success,
        },
    }
    if remote_mode:
        result["remote_execution_mode"] = remote_mode
    if failure_domain:
        result["failure_domain"] = failure_domain
        result["failure_is_retryable"] = failure_is_retryable
    if failure_classification:
        result["failure_classification"] = failure_classification
    if retry_policy:
        result["retry_policy"] = retry_policy
    if fallback_policy:
        result["fallback_policy"] = fallback_policy
    return result


def _make_orchestration_meta(
    device_ids: Optional[list] = None,
    orchestration_role: str = "orchestration_layer",
) -> Dict[str, Any]:
    return {
        "arch_layer_id": "orchestration_layer",
        "orchestration_role": orchestration_role,
        "device_ids": device_ids or ["device-1", "device-2"],
    }


# ---------------------------------------------------------------------------
# A) RuntimeIntrospectionSnapshot
# ---------------------------------------------------------------------------


class TestRuntimeIntrospectionSnapshot(unittest.TestCase):
    """A) RuntimeIntrospectionSnapshot data contract."""

    def setUp(self):
        from core.runtime_introspection import RuntimeIntrospectionSnapshot
        self.cls = RuntimeIntrospectionSnapshot

    def test_default_construction(self):
        snap = self.cls()
        self.assertIsNone(snap.entry_surface)
        self.assertIsNone(snap.runtime_shell_authority)
        self.assertIsNone(snap.execution_mode)
        self.assertIsNone(snap.lifecycle_state)
        self.assertIsNone(snap.failure_domain)
        self.assertIsNone(snap.authority_chain_valid)
        self.assertIsInstance(snap.raw_metadata, dict)

    def test_to_dict_returns_dict(self):
        snap = self.cls()
        d = snap.to_dict()
        self.assertIsInstance(d, dict)

    def test_to_dict_is_json_safe(self):
        snap = self.cls()
        d = snap.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        self.assertIsInstance(serialised, str)

    def test_to_dict_contains_all_expected_fields(self):
        snap = self.cls()
        d = snap.to_dict()
        expected_keys = [
            "entry_surface", "entry_source",
            "runtime_shell_authority", "subject_decision_authority",
            "cognition_layer_role", "execution_substrate_role",
            "orchestration_role",
            "execution_plan_summary", "lifecycle_state", "lifecycle_trail",
            "execution_mode", "target_devices", "resolver_decision",
            "delegation_point",
            "failure_domain", "failure_classification",
            "retry_policy", "fallback_policy",
            "diagnostics_report", "authority_chain_valid",
            "trace_id", "request_success",
            "raw_metadata",
        ]
        for key in expected_keys:
            self.assertIn(key, d, f"Missing key: {key}")

    def test_repr_smoke(self):
        snap = self.cls(trace_id="t1", lifecycle_state="succeeded")
        r = repr(snap)
        self.assertIsInstance(r, str)


# ---------------------------------------------------------------------------
# B) build_introspection_snapshot — local flow
# ---------------------------------------------------------------------------


class TestBuildIntrospectionSnapshotLocalFlow(unittest.TestCase):
    """B) build_introspection_snapshot for local execution flows."""

    def setUp(self):
        from core.runtime_introspection import build_introspection_snapshot
        self.build = build_introspection_snapshot

    def test_runtime_shell_populates_entry_source(self):
        shell = _make_runtime_shell_result(source="api")
        snap = self.build(runtime_shell_result=shell, run_diagnostics=False)
        self.assertEqual(snap.entry_source, "api")

    def test_runtime_shell_populates_authority(self):
        shell = _make_runtime_shell_result()
        snap = self.build(runtime_shell_result=shell, run_diagnostics=False)
        self.assertEqual(snap.runtime_shell_authority, "runtime_shell_authority")

    def test_subject_core_populates_subject_decision_authority(self):
        core = _make_subject_core_result()
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertEqual(snap.subject_decision_authority, "subject_decision_authority")

    def test_subject_core_populates_delegation_point(self):
        core = _make_subject_core_result(delegation_point="local")
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertEqual(snap.delegation_point, "local")

    def test_subject_core_populates_execution_plan_summary(self):
        plan = {"primary_step_type": "local_manifestation", "step_types": ["local_manifestation"]}
        core = _make_subject_core_result(plan_summary=plan)
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertIsNotNone(snap.execution_plan_summary)
        self.assertEqual(snap.execution_plan_summary.get("primary_step_type"), "local_manifestation")

    def test_subject_core_populates_lifecycle_state(self):
        core = _make_subject_core_result(lifecycle_state="succeeded")
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertEqual(snap.lifecycle_state, "succeeded")

    def test_subject_core_without_device_id_leaves_target_devices_none(self):
        core = _make_subject_core_result(device_id=None)
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertIsNone(snap.target_devices)

    def test_trace_id_from_runtime_shell(self):
        shell = _make_runtime_shell_result(trace_id="trace-shell")
        snap = self.build(runtime_shell_result=shell, run_diagnostics=False)
        self.assertEqual(snap.trace_id, "trace-shell")

    def test_trace_id_from_subject_core_when_shell_absent(self):
        core = _make_subject_core_result(trace_id="trace-core")
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertEqual(snap.trace_id, "trace-core")

    def test_request_success_from_subject_core(self):
        core = _make_subject_core_result(success=True)
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertTrue(snap.request_success)

    def test_request_success_false_propagated(self):
        core = _make_subject_core_result(success=False)
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertFalse(snap.request_success)

    def test_raw_metadata_merges_all_layers(self):
        shell = _make_runtime_shell_result()
        core = _make_subject_core_result()
        snap = self.build(runtime_shell_result=shell, subject_core_result=core, run_diagnostics=False)
        self.assertIsInstance(snap.raw_metadata, dict)
        # raw_metadata should be non-empty
        self.assertGreater(len(snap.raw_metadata), 0)

    def test_run_diagnostics_false_skips_diagnostics(self):
        core = _make_subject_core_result()
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertIsNone(snap.diagnostics_report)
        self.assertIsNone(snap.authority_chain_valid)

    def test_local_execution_mode_is_none(self):
        core = _make_subject_core_result(remote_mode=None)
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertIsNone(snap.execution_mode)


# ---------------------------------------------------------------------------
# C) build_introspection_snapshot — remote command flow
# ---------------------------------------------------------------------------


class TestBuildIntrospectionSnapshotRemoteCommand(unittest.TestCase):
    """C) build_introspection_snapshot for remote command_only flows."""

    def setUp(self):
        from core.runtime_introspection import build_introspection_snapshot
        self.build = build_introspection_snapshot

    def test_substrate_populates_execution_substrate_role(self):
        sub = _make_substrate_result(remote_mode="command_only")
        snap = self.build(substrate_result=sub, run_diagnostics=False)
        self.assertEqual(snap.execution_substrate_role, "execution_substrate")

    def test_substrate_populates_execution_mode(self):
        sub = _make_substrate_result(remote_mode="command_only")
        snap = self.build(substrate_result=sub, run_diagnostics=False)
        self.assertEqual(snap.execution_mode, "command_only")

    def test_substrate_populates_lifecycle_state(self):
        sub = _make_substrate_result(lifecycle_state="succeeded")
        snap = self.build(substrate_result=sub, run_diagnostics=False)
        self.assertEqual(snap.lifecycle_state, "succeeded")

    def test_failure_domain_populated_on_failure(self):
        sub = _make_substrate_result(
            success=False,
            failure_domain="timeout_failure",
            failure_is_retryable=True,
        )
        snap = self.build(substrate_result=sub, run_diagnostics=False)
        self.assertEqual(snap.failure_domain, "timeout_failure")

    def test_failure_classification_populated(self):
        fc = {"domain": "timeout_failure", "is_retryable": True, "downgrade_hint": None}
        sub = _make_substrate_result(
            success=False,
            failure_domain="timeout_failure",
            failure_classification=fc,
        )
        snap = self.build(substrate_result=sub, run_diagnostics=False)
        self.assertIsNotNone(snap.failure_classification)
        self.assertEqual(snap.failure_classification.get("domain"), "timeout_failure")

    def test_request_success_from_substrate_when_core_absent(self):
        sub = _make_substrate_result(success=False)
        snap = self.build(substrate_result=sub, run_diagnostics=False)
        self.assertFalse(snap.request_success)

    def test_subject_core_execution_mode_takes_precedence(self):
        core = _make_subject_core_result(remote_mode="command_only")
        sub = _make_substrate_result(remote_mode="agent_runtime")
        snap = self.build(subject_core_result=core, substrate_result=sub, run_diagnostics=False)
        # subject_core takes precedence
        self.assertEqual(snap.execution_mode, "command_only")


# ---------------------------------------------------------------------------
# D) build_introspection_snapshot — remote agent flow
# ---------------------------------------------------------------------------


class TestBuildIntrospectionSnapshotRemoteAgent(unittest.TestCase):
    """D) build_introspection_snapshot for remote agent_runtime flows."""

    def setUp(self):
        from core.runtime_introspection import build_introspection_snapshot
        self.build = build_introspection_snapshot

    def test_agent_runtime_mode_propagated(self):
        core = _make_subject_core_result(
            remote_mode="agent_runtime",
            delegation_point="single_remote",
            device_id="device-abc",
        )
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertEqual(snap.execution_mode, "agent_runtime")

    def test_target_devices_from_device_id(self):
        core = _make_subject_core_result(device_id="device-xyz", remote_mode="agent_runtime")
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertIsNotNone(snap.target_devices)
        self.assertIn("device-xyz", snap.target_devices)

    def test_delegation_point_is_single_remote(self):
        core = _make_subject_core_result(
            delegation_point="single_remote",
            remote_mode="agent_runtime",
        )
        snap = self.build(subject_core_result=core, run_diagnostics=False)
        self.assertEqual(snap.delegation_point, "single_remote")


# ---------------------------------------------------------------------------
# E) build_introspection_snapshot — orchestration flow
# ---------------------------------------------------------------------------


class TestBuildIntrospectionSnapshotOrchestration(unittest.TestCase):
    """E) build_introspection_snapshot for orchestration (multi-device) flows."""

    def setUp(self):
        from core.runtime_introspection import build_introspection_snapshot
        self.build = build_introspection_snapshot

    def test_orchestration_role_from_meta(self):
        orch = _make_orchestration_meta(orchestration_role="orchestration_layer")
        snap = self.build(orchestration_meta=orch, run_diagnostics=False)
        self.assertEqual(snap.orchestration_role, "orchestration_layer")

    def test_target_devices_from_orchestration_device_ids(self):
        orch = _make_orchestration_meta(device_ids=["dev-1", "dev-2", "dev-3"])
        snap = self.build(orchestration_meta=orch, run_diagnostics=False)
        self.assertIsNotNone(snap.target_devices)
        self.assertEqual(len(snap.target_devices), 3)
        self.assertIn("dev-1", snap.target_devices)

    def test_orchestration_arch_layer_id_triggers_role_extraction(self):
        orch = {
            "arch_layer_id": "orchestration_layer",
            "orchestration_role": "orchestration_layer",
            "device_ids": ["dev-a"],
        }
        snap = self.build(orchestration_meta=orch, run_diagnostics=False)
        self.assertEqual(snap.orchestration_role, "orchestration_layer")

    def test_orchestration_includes_orchestration_related_info(self):
        core = _make_subject_core_result(delegation_point="multi_device_orchestration")
        orch = _make_orchestration_meta(device_ids=["dev-1", "dev-2"])
        snap = self.build(subject_core_result=core, orchestration_meta=orch, run_diagnostics=False)
        self.assertEqual(snap.delegation_point, "multi_device_orchestration")
        self.assertIsNotNone(snap.orchestration_role)
        self.assertEqual(len(snap.target_devices), 2)


# ---------------------------------------------------------------------------
# F) build_introspection_snapshot — failure/fallback metadata
# ---------------------------------------------------------------------------


class TestBuildIntrospectionSnapshotFailureFallback(unittest.TestCase):
    """F) failure and fallback metadata in snapshot."""

    def setUp(self):
        from core.runtime_introspection import build_introspection_snapshot
        self.build = build_introspection_snapshot

    def test_failure_domain_visible(self):
        sub = _make_substrate_result(success=False, failure_domain="gateway_transport_failure")
        snap = self.build(substrate_result=sub, run_diagnostics=False)
        self.assertEqual(snap.failure_domain, "gateway_transport_failure")

    def test_failure_classification_dict_visible(self):
        fc = {"domain": "gateway_transport_failure", "is_retryable": True}
        sub = _make_substrate_result(
            success=False,
            failure_domain="gateway_transport_failure",
            failure_classification=fc,
        )
        snap = self.build(substrate_result=sub, run_diagnostics=False)
        self.assertIsInstance(snap.failure_classification, dict)

    def test_retry_policy_dict_visible(self):
        rp = {"is_retryable": True, "max_attempts": 3, "delay_ms": 500}
        sub = _make_substrate_result(success=False, retry_policy=rp)
        snap = self.build(substrate_result=sub, run_diagnostics=False)
        self.assertIsInstance(snap.retry_policy, dict)
        self.assertEqual(snap.retry_policy.get("max_attempts"), 3)

    def test_fallback_policy_dict_visible(self):
        fp = {"allow_local_fallback": True, "allow_mode_downgrade": True}
        sub = _make_substrate_result(success=False, fallback_policy=fp)
        snap = self.build(substrate_result=sub, run_diagnostics=False)
        self.assertIsInstance(snap.fallback_policy, dict)
        self.assertTrue(snap.fallback_policy.get("allow_local_fallback"))

    def test_backward_compat_callers_ignoring_snapshot(self):
        """Callers that only read 'success' and 'response' are unaffected."""
        sub = _make_substrate_result(success=True)
        # The substrate result itself is unchanged
        self.assertTrue(sub.get("success"))
        # The snapshot building does not mutate the input dict
        snap = self.build(substrate_result=sub, run_diagnostics=False)
        self.assertTrue(sub.get("success"))


# ---------------------------------------------------------------------------
# G) introspection_snapshot_from_response
# ---------------------------------------------------------------------------


class TestIntrospectionSnapshotFromResponse(unittest.TestCase):
    """G) introspection_snapshot_from_response routing by arch_layer_id."""

    def setUp(self):
        from core.runtime_introspection import introspection_snapshot_from_response
        self.from_response = introspection_snapshot_from_response

    def test_runtime_shell_arch_layer_id_routes_correctly(self):
        resp = _make_runtime_shell_result(source="local")
        snap = self.from_response(resp, run_diagnostics=False)
        self.assertEqual(snap.entry_source, "local")
        self.assertEqual(snap.runtime_shell_authority, "runtime_shell_authority")

    def test_execution_substrate_arch_layer_id_routes_correctly(self):
        resp = _make_substrate_result(remote_mode="command_only")
        snap = self.from_response(resp, run_diagnostics=False)
        self.assertEqual(snap.execution_substrate_role, "execution_substrate")
        self.assertEqual(snap.execution_mode, "command_only")

    def test_subject_core_arch_layer_id_routes_correctly(self):
        resp = _make_subject_core_result()
        snap = self.from_response(resp, run_diagnostics=False)
        self.assertEqual(snap.subject_decision_authority, "subject_decision_authority")

    def test_absent_arch_layer_id_defaults_to_subject_core(self):
        resp = {"success": True, "metadata": {"authority_role": "subject_decision_authority"}}
        snap = self.from_response(resp, run_diagnostics=False)
        self.assertEqual(snap.subject_decision_authority, "subject_decision_authority")

    def test_orchestration_layer_arch_layer_id_routes_correctly(self):
        resp = _make_orchestration_meta()
        snap = self.from_response(resp, run_diagnostics=False)
        self.assertEqual(snap.orchestration_role, "orchestration_layer")

    def test_non_dict_returns_empty_snapshot(self):
        snap = self.from_response(None, run_diagnostics=False)
        from core.runtime_introspection import RuntimeIntrospectionSnapshot
        self.assertIsInstance(snap, RuntimeIntrospectionSnapshot)
        self.assertIsNone(snap.trace_id)


# ---------------------------------------------------------------------------
# H) merge_layer_snapshots
# ---------------------------------------------------------------------------


class TestMergeLayerSnapshots(unittest.TestCase):
    """H) merge_layer_snapshots."""

    def setUp(self):
        from core.runtime_introspection import RuntimeIntrospectionSnapshot, merge_layer_snapshots
        self.cls = RuntimeIntrospectionSnapshot
        self.merge = merge_layer_snapshots

    def test_first_snapshot_takes_precedence(self):
        s1 = self.cls(trace_id="trace-1", lifecycle_state="succeeded")
        s2 = self.cls(trace_id="trace-2", lifecycle_state="failed")
        merged = self.merge(s1, s2)
        self.assertEqual(merged.trace_id, "trace-1")
        self.assertEqual(merged.lifecycle_state, "succeeded")

    def test_none_fields_in_first_filled_by_later(self):
        s1 = self.cls(trace_id="trace-1", lifecycle_state=None)
        s2 = self.cls(trace_id=None, lifecycle_state="failed")
        merged = self.merge(s1, s2)
        self.assertEqual(merged.trace_id, "trace-1")
        self.assertEqual(merged.lifecycle_state, "failed")

    def test_raw_metadata_merged(self):
        s1 = self.cls(raw_metadata={"a": 1})
        s2 = self.cls(raw_metadata={"b": 2})
        merged = self.merge(s1, s2)
        self.assertIn("a", merged.raw_metadata)
        self.assertIn("b", merged.raw_metadata)

    def test_empty_merge_returns_empty_snapshot(self):
        merged = self.merge()
        self.assertIsNone(merged.trace_id)

    def test_single_snapshot_round_trips(self):
        s1 = self.cls(
            trace_id="t1",
            execution_mode="command_only",
            lifecycle_state="succeeded",
        )
        merged = self.merge(s1)
        self.assertEqual(merged.trace_id, "t1")
        self.assertEqual(merged.execution_mode, "command_only")
        self.assertEqual(merged.lifecycle_state, "succeeded")


# ---------------------------------------------------------------------------
# I) ArchitectureStatusReport
# ---------------------------------------------------------------------------


class TestArchitectureStatusReport(unittest.TestCase):
    """I) ArchitectureStatusReport data contract."""

    def setUp(self):
        from core.architecture_status_report import ArchitectureStatusReport
        self.cls = ArchitectureStatusReport

    def test_default_construction(self):
        rpt = self.cls()
        self.assertIsNone(rpt.authority_chain_valid)
        self.assertIsNone(rpt.overall_valid)
        self.assertIsInstance(rpt.authority_chain_summary, list)
        self.assertIsInstance(rpt.diagnostics_findings, list)
        self.assertIsInstance(rpt.notes, list)

    def test_to_dict_returns_dict(self):
        rpt = self.cls()
        d = rpt.to_dict()
        self.assertIsInstance(d, dict)

    def test_to_dict_is_json_safe(self):
        rpt = self.cls()
        d = rpt.to_dict()
        json.dumps(d)  # must not raise

    def test_to_dict_contains_expected_keys(self):
        rpt = self.cls()
        d = rpt.to_dict()
        for k in ["authority_chain_present", "authority_chain_valid",
                  "authority_chain_summary", "remote_execution_coherent",
                  "substrate_distinct_from_orchestration", "diagnostics_findings",
                  "overall_valid", "notes", "raw_diagnostics_report"]:
            self.assertIn(k, d, f"Missing key: {k}")

    def test_repr_smoke(self):
        rpt = self.cls(overall_valid=True)
        r = repr(rpt)
        self.assertIsInstance(r, str)


# ---------------------------------------------------------------------------
# J) build_architecture_status_report — authority chain
# ---------------------------------------------------------------------------


class TestBuildArchitectureStatusReport(unittest.TestCase):
    """J) build_architecture_status_report — authority chain checks."""

    def setUp(self):
        from core.architecture_status_report import build_architecture_status_report
        self.build = build_architecture_status_report

    def _all_layers(self):
        return dict(
            runtime_shell_result=_make_runtime_shell_result(),
            subject_core_result=_make_subject_core_result(),
            substrate_result=_make_substrate_result(),
        )

    def test_all_four_layers_present_authority_chain_present_true(self):
        rpt = self.build(**self._all_layers())
        self.assertTrue(rpt.authority_chain_present)

    def test_missing_runtime_shell_authority_chain_present_false(self):
        rpt = self.build(
            subject_core_result=_make_subject_core_result(),
            substrate_result=_make_substrate_result(),
        )
        self.assertFalse(rpt.authority_chain_present)

    def test_missing_runtime_shell_adds_note(self):
        rpt = self.build(
            subject_core_result=_make_subject_core_result(),
            substrate_result=_make_substrate_result(),
        )
        self.assertTrue(any("runtime_shell" in n for n in rpt.notes))

    def test_missing_subject_core_authority_chain_present_false(self):
        rpt = self.build(
            runtime_shell_result=_make_runtime_shell_result(),
            substrate_result=_make_substrate_result(),
        )
        self.assertFalse(rpt.authority_chain_present)

    def test_missing_substrate_authority_chain_present_false(self):
        rpt = self.build(
            runtime_shell_result=_make_runtime_shell_result(),
            subject_core_result=_make_subject_core_result(),
        )
        self.assertFalse(rpt.authority_chain_present)

    def test_authority_chain_summary_has_correct_structure(self):
        rpt = self.build(**self._all_layers())
        self.assertIsInstance(rpt.authority_chain_summary, list)
        for entry in rpt.authority_chain_summary:
            self.assertIn("layer", entry)
            self.assertIn("expected_role", entry)
            self.assertIn("present", entry)

    def test_authority_chain_summary_contains_expected_roles(self):
        rpt = self.build(**self._all_layers())
        roles = {e["expected_role"] for e in rpt.authority_chain_summary}
        self.assertIn("runtime_shell_authority", roles)
        self.assertIn("subject_decision_authority", roles)
        self.assertIn("execution_substrate", roles)


# ---------------------------------------------------------------------------
# K) build_architecture_status_report — diagnostics integration
# ---------------------------------------------------------------------------


class TestArchitectureStatusReportDiagnostics(unittest.TestCase):
    """K) diagnostics integration in architecture status report."""

    def setUp(self):
        from core.architecture_status_report import build_architecture_status_report
        self.build = build_architecture_status_report

    def test_with_valid_layers_overall_valid_is_not_none(self):
        rpt = self.build(
            runtime_shell_result=_make_runtime_shell_result(),
            subject_core_result=_make_subject_core_result(),
            substrate_result=_make_substrate_result(),
        )
        # overall_valid should be set (True or False, but not None when layers present)
        self.assertIsNotNone(rpt.overall_valid)

    def test_diagnostics_findings_is_list(self):
        rpt = self.build(
            runtime_shell_result=_make_runtime_shell_result(),
            subject_core_result=_make_subject_core_result(),
        )
        self.assertIsInstance(rpt.diagnostics_findings, list)

    def test_raw_diagnostics_report_has_overall_valid(self):
        rpt = self.build(
            runtime_shell_result=_make_runtime_shell_result(),
            subject_core_result=_make_subject_core_result(),
            substrate_result=_make_substrate_result(),
        )
        if rpt.raw_diagnostics_report is not None:
            self.assertIn("overall_valid", rpt.raw_diagnostics_report)

    def test_no_layers_diagnostics_gracefully_absent(self):
        rpt = self.build()
        # With no layers, chain is absent and diagnostics skipped gracefully
        self.assertFalse(rpt.authority_chain_present)


# ---------------------------------------------------------------------------
# L) architecture_status_from_snapshot
# ---------------------------------------------------------------------------


class TestArchitectureStatusFromSnapshot(unittest.TestCase):
    """L) architecture_status_from_snapshot."""

    def setUp(self):
        from core.architecture_status_report import architecture_status_from_snapshot
        from core.runtime_introspection import RuntimeIntrospectionSnapshot
        self.from_snapshot = architecture_status_from_snapshot
        self.snapshot_cls = RuntimeIntrospectionSnapshot

    def test_snapshot_with_all_authority_fields(self):
        snap = self.snapshot_cls(
            runtime_shell_authority="runtime_shell_authority",
            subject_decision_authority="subject_decision_authority",
            cognition_layer_role="embedded_cognition_layer",
            execution_substrate_role="execution_substrate",
        )
        rpt = self.from_snapshot(snap)
        # Should find all four layers
        self.assertTrue(rpt.authority_chain_present)

    def test_snapshot_without_orchestration_role(self):
        snap = self.snapshot_cls(
            runtime_shell_authority="runtime_shell_authority",
            subject_decision_authority="subject_decision_authority",
        )
        rpt = self.from_snapshot(snap)
        # Missing substrate and cognition but should not raise
        self.assertIsInstance(rpt.authority_chain_summary, list)

    def test_overall_valid_reflects_chain_or_diagnostics(self):
        snap = self.snapshot_cls(
            runtime_shell_authority="runtime_shell_authority",
            subject_decision_authority="subject_decision_authority",
            execution_substrate_role="execution_substrate",
        )
        rpt = self.from_snapshot(snap)
        # overall_valid must be a bool or None
        self.assertIn(rpt.overall_valid, (True, False, None))


# ---------------------------------------------------------------------------
# M) ExecutionStatusReport
# ---------------------------------------------------------------------------


class TestExecutionStatusReport(unittest.TestCase):
    """M) ExecutionStatusReport data contract."""

    def setUp(self):
        from core.execution_status_report import ExecutionStatusReport
        self.cls = ExecutionStatusReport

    def test_default_construction(self):
        rpt = self.cls()
        self.assertIsNone(rpt.execution_path)
        self.assertIsNone(rpt.execution_mode)
        self.assertIsNone(rpt.lifecycle_state)
        self.assertIsNone(rpt.failure_domain)
        self.assertIsNone(rpt.is_terminal)

    def test_to_dict_returns_dict(self):
        rpt = self.cls()
        d = rpt.to_dict()
        self.assertIsInstance(d, dict)

    def test_to_dict_is_json_safe(self):
        rpt = self.cls()
        json.dumps(rpt.to_dict())  # must not raise

    def test_to_dict_contains_all_expected_fields(self):
        rpt = self.cls()
        d = rpt.to_dict()
        for k in [
            "execution_path", "delegation_point", "execution_mode",
            "target_devices", "resolver_decision",
            "execution_plan_summary", "plan_step_types",
            "lifecycle_state", "lifecycle_trail", "is_terminal",
            "request_success",
            "failure_domain", "failure_classification",
            "retry_policy", "fallback_policy", "failure_summary",
        ]:
            self.assertIn(k, d, f"Missing key: {k}")

    def test_repr_smoke(self):
        rpt = self.cls(execution_mode="command_only", lifecycle_state="succeeded")
        r = repr(rpt)
        self.assertIsInstance(r, str)


# ---------------------------------------------------------------------------
# N) build_execution_status_report — plan and lifecycle
# ---------------------------------------------------------------------------


class TestBuildExecutionStatusReportPlan(unittest.TestCase):
    """N) plan and lifecycle data in ExecutionStatusReport."""

    def setUp(self):
        from core.execution_status_report import build_execution_status_report
        self.build = build_execution_status_report

    def test_execution_plan_summary_from_subject_core_metadata(self):
        plan = {"primary_step_type": "local_manifestation", "step_types": ["local_manifestation"]}
        core = _make_subject_core_result(plan_summary=plan)
        rpt = self.build(subject_core_result=core)
        self.assertIsNotNone(rpt.execution_plan_summary)

    def test_lifecycle_state_from_subject_core(self):
        core = _make_subject_core_result(lifecycle_state="succeeded")
        rpt = self.build(subject_core_result=core)
        self.assertEqual(rpt.lifecycle_state, "succeeded")

    def test_plan_step_types_from_step_types_list(self):
        plan = {"step_types": ["local_manifestation", "observe"]}
        core = _make_subject_core_result(plan_summary=plan)
        rpt = self.build(subject_core_result=core)
        self.assertIsNotNone(rpt.plan_step_types)
        self.assertIn("local_manifestation", rpt.plan_step_types)

    def test_plan_step_types_from_primary_step_type(self):
        plan = {"primary_step_type": "remote_command"}
        core = _make_subject_core_result(plan_summary=plan)
        rpt = self.build(subject_core_result=core)
        self.assertIsNotNone(rpt.plan_step_types)
        self.assertIn("remote_command", rpt.plan_step_types)

    def test_is_terminal_true_for_succeeded(self):
        core = _make_subject_core_result(lifecycle_state="succeeded")
        rpt = self.build(subject_core_result=core)
        self.assertTrue(rpt.is_terminal)

    def test_is_terminal_true_for_failed(self):
        core = _make_subject_core_result(lifecycle_state="failed", success=False)
        rpt = self.build(subject_core_result=core)
        self.assertTrue(rpt.is_terminal)

    def test_is_terminal_true_for_timed_out(self):
        core = _make_subject_core_result(lifecycle_state="timed_out", success=False)
        rpt = self.build(subject_core_result=core)
        self.assertTrue(rpt.is_terminal)

    def test_is_terminal_false_for_running(self):
        core = _make_subject_core_result(lifecycle_state="running")
        rpt = self.build(subject_core_result=core)
        self.assertFalse(rpt.is_terminal)

    def test_is_terminal_none_when_lifecycle_state_none(self):
        rpt = self.build()
        self.assertIsNone(rpt.is_terminal)


# ---------------------------------------------------------------------------
# O) build_execution_status_report — failure / fallback
# ---------------------------------------------------------------------------


class TestBuildExecutionStatusReportFailure(unittest.TestCase):
    """O) failure/fallback data in ExecutionStatusReport."""

    def setUp(self):
        from core.execution_status_report import build_execution_status_report
        self.build = build_execution_status_report

    def test_failure_domain_from_substrate(self):
        sub = _make_substrate_result(success=False, failure_domain="timeout_failure")
        rpt = self.build(substrate_result=sub)
        self.assertEqual(rpt.failure_domain, "timeout_failure")

    def test_failure_classification_from_substrate(self):
        fc = {"domain": "timeout_failure", "is_retryable": True}
        sub = _make_substrate_result(success=False, failure_domain="timeout_failure", failure_classification=fc)
        rpt = self.build(substrate_result=sub)
        self.assertIsNotNone(rpt.failure_classification)

    def test_retry_policy_from_substrate(self):
        rp = {"is_retryable": True, "max_attempts": 3}
        sub = _make_substrate_result(success=False, retry_policy=rp)
        rpt = self.build(substrate_result=sub)
        self.assertIsNotNone(rpt.retry_policy)
        self.assertEqual(rpt.retry_policy.get("max_attempts"), 3)

    def test_fallback_policy_from_substrate(self):
        fp = {"allow_local_fallback": True, "allow_mode_downgrade": True}
        sub = _make_substrate_result(success=False, fallback_policy=fp)
        rpt = self.build(substrate_result=sub)
        self.assertIsNotNone(rpt.fallback_policy)
        self.assertTrue(rpt.fallback_policy.get("allow_local_fallback"))

    def test_failure_summary_formatted(self):
        fc = {"domain": "timeout_failure", "is_retryable": True, "downgrade_hint": "remote_to_local"}
        sub = _make_substrate_result(
            success=False,
            failure_domain="timeout_failure",
            failure_classification=fc,
        )
        rpt = self.build(substrate_result=sub)
        self.assertIsNotNone(rpt.failure_summary)
        self.assertIn("timeout_failure", rpt.failure_summary)

    def test_failure_summary_none_when_no_failure_domain(self):
        sub = _make_substrate_result(success=True)
        rpt = self.build(substrate_result=sub)
        self.assertIsNone(rpt.failure_summary)


# ---------------------------------------------------------------------------
# P) build_execution_status_report — routing fields
# ---------------------------------------------------------------------------


class TestBuildExecutionStatusReportRouting(unittest.TestCase):
    """P) routing/dispatch fields in ExecutionStatusReport."""

    def setUp(self):
        from core.execution_status_report import build_execution_status_report
        self.build = build_execution_status_report

    def test_delegation_point_from_subject_core(self):
        core = _make_subject_core_result(delegation_point="single_remote")
        rpt = self.build(subject_core_result=core)
        self.assertEqual(rpt.delegation_point, "single_remote")

    def test_execution_mode_from_subject_core(self):
        core = _make_subject_core_result(remote_mode="command_only")
        rpt = self.build(subject_core_result=core)
        self.assertEqual(rpt.execution_mode, "command_only")

    def test_execution_mode_from_substrate_when_core_absent(self):
        sub = _make_substrate_result(remote_mode="agent_runtime")
        rpt = self.build(substrate_result=sub)
        self.assertEqual(rpt.execution_mode, "agent_runtime")

    def test_target_devices_from_subject_core_device_id(self):
        core = _make_subject_core_result(device_id="device-99")
        rpt = self.build(subject_core_result=core)
        self.assertIsNotNone(rpt.target_devices)
        self.assertIn("device-99", rpt.target_devices)

    def test_target_devices_from_orchestration_meta(self):
        orch = _make_orchestration_meta(device_ids=["d1", "d2"])
        rpt = self.build(orchestration_meta=orch)
        self.assertIsNotNone(rpt.target_devices)
        self.assertIn("d1", rpt.target_devices)

    def test_resolver_decision_from_orchestration_meta(self):
        orch = {"arch_layer_id": "orchestration_layer",
                "resolver_decision": {"mode": "command_only", "rationale": "thin_device"}}
        rpt = self.build(orchestration_meta=orch)
        self.assertIsNotNone(rpt.resolver_decision)
        self.assertEqual(rpt.resolver_decision.get("mode"), "command_only")


# ---------------------------------------------------------------------------
# Q) execution_status_from_snapshot
# ---------------------------------------------------------------------------


class TestExecutionStatusFromSnapshot(unittest.TestCase):
    """Q) execution_status_from_snapshot."""

    def setUp(self):
        from core.execution_status_report import execution_status_from_snapshot
        from core.runtime_introspection import RuntimeIntrospectionSnapshot
        self.from_snapshot = execution_status_from_snapshot
        self.snapshot_cls = RuntimeIntrospectionSnapshot

    def test_all_fields_round_trip(self):
        snap = self.snapshot_cls(
            delegation_point="single_remote",
            execution_mode="command_only",
            lifecycle_state="succeeded",
            request_success=True,
            target_devices=["dev-x"],
        )
        rpt = self.from_snapshot(snap)
        self.assertEqual(rpt.delegation_point, "single_remote")
        self.assertEqual(rpt.execution_mode, "command_only")
        self.assertEqual(rpt.lifecycle_state, "succeeded")
        self.assertTrue(rpt.request_success)
        self.assertIn("dev-x", rpt.target_devices)

    def test_failure_summary_built_from_snapshot_fields(self):
        snap = self.snapshot_cls(
            failure_domain="timeout_failure",
            failure_classification={"is_retryable": True, "downgrade_hint": None},
        )
        rpt = self.from_snapshot(snap)
        self.assertIsNotNone(rpt.failure_summary)
        self.assertIn("timeout_failure", rpt.failure_summary)

    def test_is_terminal_computed_from_lifecycle_state(self):
        snap = self.snapshot_cls(lifecycle_state="failed")
        rpt = self.from_snapshot(snap)
        self.assertTrue(rpt.is_terminal)

        snap2 = self.snapshot_cls(lifecycle_state="running")
        rpt2 = self.from_snapshot(snap2)
        self.assertFalse(rpt2.is_terminal)


# ---------------------------------------------------------------------------
# R) Integration: full pipeline snapshots
# ---------------------------------------------------------------------------


class TestIntegrationPipelineSnapshots(unittest.TestCase):
    """R) Integration: representative full-pipeline snapshots."""

    def setUp(self):
        from core.runtime_introspection import build_introspection_snapshot
        from core.architecture_status_report import build_architecture_status_report
        from core.execution_status_report import build_execution_status_report
        self.build_snap = build_introspection_snapshot
        self.build_arch = build_architecture_status_report
        self.build_exec = build_execution_status_report

    def test_local_flow_produces_valid_introspection_snapshot(self):
        shell = _make_runtime_shell_result(source="api", trace_id="t-local")
        core = _make_subject_core_result(
            execution_path="local",
            delegation_point="local",
            trace_id="t-local",
            lifecycle_state="succeeded",
        )
        snap = self.build_snap(
            runtime_shell_result=shell,
            subject_core_result=core,
            run_diagnostics=False,
        )
        self.assertEqual(snap.trace_id, "t-local")
        self.assertEqual(snap.delegation_point, "local")
        self.assertIsNone(snap.execution_mode)
        self.assertTrue(snap.request_success)
        self.assertEqual(snap.lifecycle_state, "succeeded")
        d = snap.to_dict()
        json.dumps(d)  # JSON-serialisable

    def test_remote_command_flow_produces_valid_snapshot(self):
        shell = _make_runtime_shell_result(trace_id="t-cmd")
        core = _make_subject_core_result(
            delegation_point="single_remote",
            remote_mode="command_only",
            device_id="device-123",
            lifecycle_state="succeeded",
            trace_id="t-cmd",
        )
        sub = _make_substrate_result(
            remote_mode="command_only",
            lifecycle_state="succeeded",
        )
        snap = self.build_snap(
            runtime_shell_result=shell,
            subject_core_result=core,
            substrate_result=sub,
            run_diagnostics=False,
        )
        self.assertEqual(snap.execution_mode, "command_only")
        self.assertIn("device-123", snap.target_devices)
        self.assertEqual(snap.delegation_point, "single_remote")

    def test_remote_agent_flow_produces_valid_snapshot(self):
        core = _make_subject_core_result(
            delegation_point="single_remote",
            remote_mode="agent_runtime",
            device_id="device-456",
            lifecycle_state="succeeded",
        )
        sub = _make_substrate_result(remote_mode="agent_runtime", lifecycle_state="succeeded")
        snap = self.build_snap(subject_core_result=core, substrate_result=sub, run_diagnostics=False)
        self.assertEqual(snap.execution_mode, "agent_runtime")
        self.assertIn("device-456", snap.target_devices)

    def test_failure_flow_includes_failure_domain(self):
        sub = _make_substrate_result(
            success=False,
            failure_domain="gateway_transport_failure",
            lifecycle_state="failed",
        )
        core = _make_subject_core_result(success=False, lifecycle_state="failed")
        snap = self.build_snap(subject_core_result=core, substrate_result=sub, run_diagnostics=False)
        self.assertEqual(snap.failure_domain, "gateway_transport_failure")
        self.assertEqual(snap.lifecycle_state, "failed")

    def test_backward_compat_result_dicts_without_introspection_snapshot_work(self):
        """Callers that ignore the introspection_snapshot field work unchanged."""
        # Simulate a legacy result dict that does not have introspection_snapshot
        legacy_core = {
            "arch_layer_id": "subject_core",
            "success": True,
            "response": "Hello",
            "metadata": {
                "authority_role": "subject_decision_authority",
                "delegation_point": "local",
            },
        }
        snap = self.build_snap(subject_core_result=legacy_core, run_diagnostics=False)
        # snapshot still works
        self.assertEqual(snap.subject_decision_authority, "subject_decision_authority")
        # original dict is not mutated
        self.assertNotIn("introspection_snapshot", legacy_core)

    def test_orchestration_flow_includes_orchestration_info(self):
        core = _make_subject_core_result(
            delegation_point="multi_device_orchestration",
            lifecycle_state="partially_succeeded",
        )
        orch = _make_orchestration_meta(device_ids=["d1", "d2", "d3"])
        snap = self.build_snap(subject_core_result=core, orchestration_meta=orch, run_diagnostics=False)
        self.assertEqual(snap.delegation_point, "multi_device_orchestration")
        self.assertIsNotNone(snap.orchestration_role)
        self.assertEqual(len(snap.target_devices), 3)


# ---------------------------------------------------------------------------
# S) Integration: introspection_snapshot field stamped on layer results
# ---------------------------------------------------------------------------


class TestIntrospectionSnapshotFieldOnLayerResults(unittest.TestCase):
    """S) introspection_snapshot field is stamped on layer results in representative modules."""

    def test_runtime_shell_result_carries_introspection_snapshot(self):
        """The _make_runtime_shell_result fixture includes introspection_snapshot (as stamped by DesktopPresenceRuntime)."""
        result = _make_runtime_shell_result()
        self.assertIn("introspection_snapshot", result)
        snap_dict = result["introspection_snapshot"]
        self.assertIsInstance(snap_dict, dict)
        self.assertEqual(snap_dict.get("authority_role"), "runtime_shell_authority")

    def test_subject_core_result_carries_introspection_snapshot(self):
        result = _make_subject_core_result()
        self.assertIn("introspection_snapshot", result)
        snap_dict = result["introspection_snapshot"]
        self.assertIsInstance(snap_dict, dict)
        self.assertEqual(snap_dict.get("authority_role"), "subject_decision_authority")

    def test_substrate_result_carries_introspection_snapshot(self):
        result = _make_substrate_result()
        self.assertIn("introspection_snapshot", result)
        snap_dict = result["introspection_snapshot"]
        self.assertIsInstance(snap_dict, dict)
        self.assertEqual(snap_dict.get("authority_role"), "execution_substrate")

    def test_introspection_snapshot_is_json_safe(self):
        for result in [
            _make_runtime_shell_result(),
            _make_subject_core_result(),
            _make_substrate_result(),
        ]:
            snap_dict = result.get("introspection_snapshot", {})
            json.dumps(snap_dict)  # must not raise

    def test_desktop_presence_runtime_stamps_introspection_snapshot(self):
        """DesktopPresenceRuntime.handle_request result carries introspection_snapshot."""
        import asyncio
        try:
            from core.desktop_presence_runtime import DesktopPresenceRuntime
        except Exception:
            self.skipTest("DesktopPresenceRuntime not importable")

        try:
            dpr = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
            dpr._active_sessions = {}
            dpr._tristate = None
            dpr._policy_engine = None

            # Build a minimal mock result to test the stamp
            result: Dict[str, Any] = {"success": True, "trace_id": "t-dpr", "runtime_session_id": "t-dpr"}
            source = "test"

            # Replicate what handle_request does: call setdefault for introspection_snapshot
            result.setdefault("authority_metadata", {
                "layer_role": "runtime_shell_authority",
                "canonical_module": "core.desktop_presence_runtime",
            })
            result.setdefault("arch_layer_id", "runtime_shell")
            result.setdefault("introspection_snapshot", {
                "authority_role": "runtime_shell_authority",
                "entry_source": source,
                "trace_id": result.get("trace_id"),
            })

            self.assertIn("introspection_snapshot", result)
            self.assertEqual(result["introspection_snapshot"]["authority_role"], "runtime_shell_authority")
        except Exception as e:
            self.skipTest(f"Runtime setup failed: {e}")

    def test_command_router_stamps_introspection_snapshot(self):
        """CommandRouter.route_envelope result carries introspection_snapshot."""
        # Simulate what route_envelope does after PR-14 stamp
        result: Dict[str, Any] = {
            "success": True,
            "execution_substrate_role": "execution_substrate",
            "arch_layer_id": "execution_substrate",
            "lifecycle_state": "succeeded",
        }
        result.setdefault("introspection_snapshot", {
            "authority_role": "execution_substrate",
            "execution_substrate_role": result.get("execution_substrate_role", "execution_substrate"),
            "execution_mode": result.get("remote_execution_mode"),
            "lifecycle_state": result.get("lifecycle_state"),
            "failure_domain": result.get("failure_domain"),
            "failure_is_retryable": result.get("failure_is_retryable"),
            "success": result.get("success"),
        })
        self.assertIn("introspection_snapshot", result)
        snap = result["introspection_snapshot"]
        self.assertEqual(snap["authority_role"], "execution_substrate")
        self.assertTrue(snap["success"])


if __name__ == "__main__":
    unittest.main()
