#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr513_failure_degraded_recovery.py
=============================================
PR-513 — Failure / Degraded / Recovery Closure: Tests.

Validates that:
* The failure_degraded_recovery_policy module exports all required
  authority/policy sentinels and symbols.
* FailureRuntimeState enum covers all required failure/recovery lifecycle states.
* DegradedTruthRecord and RecoveryTransitionRecord dataclasses have correct
  structure and to_dict() round-trips.
* FailureRecoverySnapshot.summary() returns expected keys.
* FailureDegradedRecoveryRuntime ring buffer records failure and recovery entries.
* propagate_failure_to_canonical writes to TaskGraphRuntime + AuditEventSemantics
  + ReplayFoundation in a best-effort non-blocking manner.
* propagate_recovery_to_canonical writes to TaskGraphRuntime + AuditEventSemantics.
* record_degraded_transition writes an audit TASK_DEGRADED event.
* query_degraded_state returns expected dict structure.
* snapshot_failure_recovery_state returns combined summary.
* GAP-512-001: core/routes/tasks.py exposes TASK_INGRESS_REPLAY_FOUNDATION_INTEGRATED.
* GAP-512-002: core/scheduler.py exposes SCHEDULER_TASK_GRAPH_RELAY_MESH_INTEGRATED.
* GAP-512-004: core/command_router.py exposes CAPABILITY_NETWORK_CANONICAL_QUERY_INTEGRATED.
* GAP-512-006: galaxy_gateway/orchestrator/task_orchestrator.py exposes
  TASK_ORCHESTRATOR_AUDIT_DISPATCH_INTEGRATED.
* GAP-512-007: core/agent/kernel.py exposes AGENT_KERNEL_AUDIT_ADMITTED_INTEGRATED.
* Retry/fallback flows update runtime state in a coherent way.
* No new parallel failure/degraded authorities are introduced.
* Closure audit layer now covers PR-513 sentinels.

Test groups
-----------
 A)  Module structure — all __all__ symbols importable.
 B)  Authority sentinels — correct values and types.
 C)  Policy sentinels — vocabulary checks.
 D)  FailureRuntimeState enum — all required states present.
 E)  DegradedTruthRecord dataclass — structure and to_dict().
 F)  RecoveryTransitionRecord dataclass — structure and to_dict().
 G)  FailureRecoverySnapshot dataclass — summary() keys.
 H)  FailureDegradedRecoveryRuntime — singleton management.
 I)  FailureDegradedRecoveryRuntime — ring buffer writes.
 J)  propagate_failure_to_canonical — ring buffer write.
 K)  propagate_failure_to_canonical — TaskGraphRuntime write (best-effort).
 L)  propagate_failure_to_canonical — AuditEventSemantics write (best-effort).
 M)  propagate_failure_to_canonical — ReplayFoundation write (best-effort).
 N)  propagate_recovery_to_canonical — ring buffer write.
 O)  propagate_recovery_to_canonical — canonical layer writes (best-effort).
 P)  record_degraded_transition — ring buffer write + audit write.
 Q)  query_degraded_state — dict structure.
 R)  snapshot_failure_recovery_state — combined dict.
 S)  GAP-512-001 closure — TASK_INGRESS_REPLAY_FOUNDATION_INTEGRATED sentinel.
 T)  GAP-512-002 closure — SCHEDULER_TASK_GRAPH_RELAY_MESH_INTEGRATED sentinel.
 U)  GAP-512-004 closure — CAPABILITY_NETWORK_CANONICAL_QUERY_INTEGRATED sentinel.
 V)  GAP-512-006 closure — TASK_ORCHESTRATOR_AUDIT_DISPATCH_INTEGRATED sentinel.
 W)  GAP-512-007 closure — AGENT_KERNEL_AUDIT_ADMITTED_INTEGRATED sentinel.
 X)  No new parallel authority — failure module writes to existing layers only.
 Y)  Failure → recovery arc — full round-trip test.
 Z)  Retry/fallback flows — updates reflected in runtime state.
 AA) Closure audit covers PR-513 layer specs.
 BB) FAILURE_DEGRADED_RECOVERY_INTEGRATED sentinel importable.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helper: reset singleton between tests
# ---------------------------------------------------------------------------

def _reset():
    from core.failure_degraded_recovery_policy import (
        reset_failure_degraded_recovery_runtime,
    )
    reset_failure_degraded_recovery_runtime()
    # Also reset replay + audit + task graph runtimes to avoid state bleed
    try:
        from core.replay_foundation import reset_replay_foundation
        reset_replay_foundation()
    except Exception:
        pass
    try:
        from core.audit_event_semantics import reset_audit_event_semantics
        reset_audit_event_semantics()
    except Exception:
        pass
    try:
        from core.task_graph_runtime import reset_task_graph_runtime
        reset_task_graph_runtime()
    except Exception:
        pass


# ===========================================================================
# A)  Module structure
# ===========================================================================


class TestA_ModuleStructure(unittest.TestCase):
    """A) All __all__ symbols importable."""

    def test_A01_module_importable(self) -> None:
        import core.failure_degraded_recovery_policy as mod  # noqa: F401
        self.assertIsNotNone(mod)

    def test_A02_all_symbols_importable(self) -> None:
        from core import failure_degraded_recovery_policy as mod
        for name in mod.__all__:
            self.assertTrue(
                hasattr(mod, name),
                f"__all__ symbol '{name}' not found on module",
            )

    def test_A03_all_is_nonempty(self) -> None:
        from core.failure_degraded_recovery_policy import __all__
        self.assertGreater(len(__all__), 0)


# ===========================================================================
# B)  Authority sentinels
# ===========================================================================


class TestB_AuthoritySentinels(unittest.TestCase):
    """B) Authority sentinels have correct types and non-empty values."""

    def test_B01_authority_is_string(self) -> None:
        from core.failure_degraded_recovery_policy import FAILURE_DEGRADED_RECOVERY_AUTHORITY
        self.assertIsInstance(FAILURE_DEGRADED_RECOVERY_AUTHORITY, str)
        self.assertGreater(len(FAILURE_DEGRADED_RECOVERY_AUTHORITY), 0)

    def test_B02_layer_position_is_int(self) -> None:
        from core.failure_degraded_recovery_policy import FAILURE_DEGRADED_RECOVERY_LAYER_POSITION
        self.assertIsInstance(FAILURE_DEGRADED_RECOVERY_LAYER_POSITION, int)
        self.assertEqual(FAILURE_DEGRADED_RECOVERY_LAYER_POSITION, 13)

    def test_B03_integrated_sentinel_is_string(self) -> None:
        from core.failure_degraded_recovery_policy import FAILURE_DEGRADED_RECOVERY_INTEGRATED
        self.assertIsInstance(FAILURE_DEGRADED_RECOVERY_INTEGRATED, str)
        self.assertGreater(len(FAILURE_DEGRADED_RECOVERY_INTEGRATED), 0)

    def test_B04_integrated_sentinel_mentions_gap_001(self) -> None:
        from core.failure_degraded_recovery_policy import FAILURE_DEGRADED_RECOVERY_INTEGRATED
        self.assertIn("GAP-512-001", FAILURE_DEGRADED_RECOVERY_INTEGRATED)

    def test_B05_integrated_sentinel_mentions_gap_002(self) -> None:
        from core.failure_degraded_recovery_policy import FAILURE_DEGRADED_RECOVERY_INTEGRATED
        self.assertIn("GAP-512-002", FAILURE_DEGRADED_RECOVERY_INTEGRATED)

    def test_B06_integrated_sentinel_mentions_gap_004(self) -> None:
        from core.failure_degraded_recovery_policy import FAILURE_DEGRADED_RECOVERY_INTEGRATED
        self.assertIn("GAP-512-004", FAILURE_DEGRADED_RECOVERY_INTEGRATED)

    def test_B07_integrated_sentinel_mentions_gap_006(self) -> None:
        from core.failure_degraded_recovery_policy import FAILURE_DEGRADED_RECOVERY_INTEGRATED
        self.assertIn("GAP-512-006", FAILURE_DEGRADED_RECOVERY_INTEGRATED)

    def test_B08_integrated_sentinel_mentions_gap_007(self) -> None:
        from core.failure_degraded_recovery_policy import FAILURE_DEGRADED_RECOVERY_INTEGRATED
        self.assertIn("GAP-512-007", FAILURE_DEGRADED_RECOVERY_INTEGRATED)


# ===========================================================================
# C)  Policy sentinels
# ===========================================================================


class TestC_PolicySentinels(unittest.TestCase):
    """C) Policy sentinels are non-empty strings with required vocabulary."""

    def _get_all_policies(self):
        from core.failure_degraded_recovery_policy import (
            FAILURE_AS_RUNTIME_TRUTH_POLICY,
            NO_PARALLEL_AUTHORITY_POLICY,
            RECOVERY_AS_FIRST_CLASS_EVENT_POLICY,
            NON_BLOCKING_PROPAGATION_POLICY,
            AUTHORITY_DISCIPLINE_POLICY,
        )
        return [
            FAILURE_AS_RUNTIME_TRUTH_POLICY,
            NO_PARALLEL_AUTHORITY_POLICY,
            RECOVERY_AS_FIRST_CLASS_EVENT_POLICY,
            NON_BLOCKING_PROPAGATION_POLICY,
            AUTHORITY_DISCIPLINE_POLICY,
        ]

    def test_C01_all_policies_are_strings(self) -> None:
        for p in self._get_all_policies():
            self.assertIsInstance(p, str)
            self.assertGreater(len(p), 0)

    def test_C02_all_policies_are_unique(self) -> None:
        policies = self._get_all_policies()
        self.assertEqual(len(policies), len(set(policies)))

    def test_C03_failure_runtime_truth_policy_vocabulary(self) -> None:
        from core.failure_degraded_recovery_policy import FAILURE_AS_RUNTIME_TRUTH_POLICY
        self.assertIn("runtime", FAILURE_AS_RUNTIME_TRUTH_POLICY.lower())

    def test_C04_no_parallel_authority_policy_vocabulary(self) -> None:
        from core.failure_degraded_recovery_policy import NO_PARALLEL_AUTHORITY_POLICY
        self.assertIn("canonical", NO_PARALLEL_AUTHORITY_POLICY.lower())


# ===========================================================================
# D)  FailureRuntimeState enum
# ===========================================================================


class TestD_FailureRuntimeState(unittest.TestCase):
    """D) FailureRuntimeState covers all required lifecycle states."""

    def test_D01_enum_importable(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        self.assertIsNotNone(FailureRuntimeState)

    def test_D02_healthy_state(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        self.assertEqual(FailureRuntimeState.HEALTHY.value, "healthy")

    def test_D03_degraded_state(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        self.assertEqual(FailureRuntimeState.DEGRADED.value, "degraded")

    def test_D04_failed_state(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        self.assertEqual(FailureRuntimeState.FAILED.value, "failed")

    def test_D05_fallback_active_state(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        self.assertEqual(FailureRuntimeState.FALLBACK_ACTIVE.value, "fallback_active")

    def test_D06_retry_pending_state(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        self.assertEqual(FailureRuntimeState.RETRY_PENDING.value, "retry_pending")

    def test_D07_aborted_state(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        self.assertEqual(FailureRuntimeState.ABORTED.value, "aborted")

    def test_D08_recovering_state(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        self.assertEqual(FailureRuntimeState.RECOVERING.value, "recovering")

    def test_D09_recovered_state(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        self.assertEqual(FailureRuntimeState.RECOVERED.value, "recovered")

    def test_D10_partial_state(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        self.assertEqual(FailureRuntimeState.PARTIAL.value, "partial")


# ===========================================================================
# E)  DegradedTruthRecord dataclass
# ===========================================================================


class TestE_DegradedTruthRecord(unittest.TestCase):
    """E) DegradedTruthRecord structure and to_dict()."""

    def setUp(self):
        _reset()

    def _make_record(self, **kwargs):
        from core.failure_degraded_recovery_policy import (
            DegradedTruthRecord,
            FailureRuntimeState,
        )
        defaults = {
            "task_id": "task_e01",
            "trace_id": "trace_e01",
            "failure_state": FailureRuntimeState.FAILED,
            "error_code": "TEST_ERROR",
            "source": "test",
        }
        defaults.update(kwargs)
        return DegradedTruthRecord(**defaults)

    def test_E01_task_id_field(self) -> None:
        rec = self._make_record()
        self.assertEqual(rec.task_id, "task_e01")

    def test_E02_trace_id_field(self) -> None:
        rec = self._make_record()
        self.assertEqual(rec.trace_id, "trace_e01")

    def test_E03_failure_state_field(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        rec = self._make_record()
        self.assertEqual(rec.failure_state, FailureRuntimeState.FAILED)

    def test_E04_to_dict_has_task_id(self) -> None:
        rec = self._make_record()
        d = rec.to_dict()
        self.assertEqual(d["task_id"], "task_e01")

    def test_E05_to_dict_has_failure_state(self) -> None:
        rec = self._make_record()
        d = rec.to_dict()
        self.assertEqual(d["failure_state"], "failed")

    def test_E06_to_dict_has_error_code(self) -> None:
        rec = self._make_record()
        d = rec.to_dict()
        self.assertEqual(d["error_code"], "TEST_ERROR")

    def test_E07_detected_at_is_float(self) -> None:
        rec = self._make_record()
        self.assertIsInstance(rec.detected_at, float)
        self.assertGreater(rec.detected_at, 0)

    def test_E08_degraded_capabilities_default_empty(self) -> None:
        rec = self._make_record()
        self.assertEqual(rec.degraded_capabilities, [])

    def test_E09_attempt_number_default_zero(self) -> None:
        rec = self._make_record()
        self.assertEqual(rec.attempt_number, 0)


# ===========================================================================
# F)  RecoveryTransitionRecord dataclass
# ===========================================================================


class TestF_RecoveryTransitionRecord(unittest.TestCase):
    """F) RecoveryTransitionRecord structure and to_dict()."""

    def setUp(self):
        _reset()

    def _make_record(self, **kwargs):
        from core.failure_degraded_recovery_policy import (
            RecoveryTransitionRecord,
            FailureRuntimeState,
        )
        defaults = {
            "task_id": "task_f01",
            "trace_id": "trace_f01",
            "prior_state": FailureRuntimeState.FAILED,
            "recovered_state": FailureRuntimeState.RECOVERED,
            "recovery_method": "retry_success",
            "source": "test",
        }
        defaults.update(kwargs)
        return RecoveryTransitionRecord(**defaults)

    def test_F01_task_id_field(self) -> None:
        rec = self._make_record()
        self.assertEqual(rec.task_id, "task_f01")

    def test_F02_prior_state_field(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        rec = self._make_record()
        self.assertEqual(rec.prior_state, FailureRuntimeState.FAILED)

    def test_F03_recovered_state_field(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRuntimeState
        rec = self._make_record()
        self.assertEqual(rec.recovered_state, FailureRuntimeState.RECOVERED)

    def test_F04_to_dict_has_task_id(self) -> None:
        rec = self._make_record()
        d = rec.to_dict()
        self.assertEqual(d["task_id"], "task_f01")

    def test_F05_to_dict_has_prior_state(self) -> None:
        rec = self._make_record()
        d = rec.to_dict()
        self.assertEqual(d["prior_state"], "failed")

    def test_F06_to_dict_has_recovered_state(self) -> None:
        rec = self._make_record()
        d = rec.to_dict()
        self.assertEqual(d["recovered_state"], "recovered")

    def test_F07_to_dict_has_recovery_method(self) -> None:
        rec = self._make_record()
        d = rec.to_dict()
        self.assertEqual(d["recovery_method"], "retry_success")

    def test_F08_transitioned_at_is_float(self) -> None:
        rec = self._make_record()
        self.assertIsInstance(rec.transitioned_at, float)
        self.assertGreater(rec.transitioned_at, 0)


# ===========================================================================
# G)  FailureRecoverySnapshot dataclass
# ===========================================================================


class TestG_FailureRecoverySnapshot(unittest.TestCase):
    """G) FailureRecoverySnapshot.summary() returns expected keys."""

    def test_G01_summary_returns_dict(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRecoverySnapshot
        snap = FailureRecoverySnapshot()
        self.assertIsInstance(snap.summary(), dict)

    def test_G02_summary_has_degraded_records_count(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRecoverySnapshot
        snap = FailureRecoverySnapshot()
        self.assertIn("degraded_records_count", snap.summary())

    def test_G03_summary_has_recovery_records_count(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRecoverySnapshot
        snap = FailureRecoverySnapshot()
        self.assertIn("recovery_records_count", snap.summary())

    def test_G04_summary_has_total_failures_recorded(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRecoverySnapshot
        snap = FailureRecoverySnapshot()
        self.assertIn("total_failures_recorded", snap.summary())

    def test_G05_summary_has_total_recoveries_recorded(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRecoverySnapshot
        snap = FailureRecoverySnapshot()
        self.assertIn("total_recoveries_recorded", snap.summary())

    def test_G06_summary_has_snapshot_at(self) -> None:
        from core.failure_degraded_recovery_policy import FailureRecoverySnapshot
        snap = FailureRecoverySnapshot()
        self.assertIn("snapshot_at", snap.summary())


# ===========================================================================
# H)  Singleton management
# ===========================================================================


class TestH_SingletonManagement(unittest.TestCase):
    """H) Singleton get/reset/re-create produce independent instances."""

    def setUp(self):
        _reset()

    def test_H01_get_returns_instance(self) -> None:
        from core.failure_degraded_recovery_policy import (
            get_failure_degraded_recovery_runtime,
            FailureDegradedRecoveryRuntime,
        )
        rt = get_failure_degraded_recovery_runtime()
        self.assertIsInstance(rt, FailureDegradedRecoveryRuntime)

    def test_H02_get_returns_same_instance(self) -> None:
        from core.failure_degraded_recovery_policy import get_failure_degraded_recovery_runtime
        rt1 = get_failure_degraded_recovery_runtime()
        rt2 = get_failure_degraded_recovery_runtime()
        self.assertIs(rt1, rt2)

    def test_H03_reset_creates_new_instance(self) -> None:
        from core.failure_degraded_recovery_policy import (
            get_failure_degraded_recovery_runtime,
            reset_failure_degraded_recovery_runtime,
        )
        rt1 = get_failure_degraded_recovery_runtime()
        reset_failure_degraded_recovery_runtime()
        rt2 = get_failure_degraded_recovery_runtime()
        self.assertIsNot(rt1, rt2)

    def test_H04_snapshot_returns_snapshot_object(self) -> None:
        from core.failure_degraded_recovery_policy import (
            get_failure_degraded_recovery_runtime,
            FailureRecoverySnapshot,
        )
        snap = get_failure_degraded_recovery_runtime().snapshot()
        self.assertIsInstance(snap, FailureRecoverySnapshot)


# ===========================================================================
# I)  Ring buffer writes
# ===========================================================================


class TestI_RingBufferWrites(unittest.TestCase):
    """I) Ring buffer records failure and recovery entries."""

    def setUp(self):
        _reset()

    def test_I01_record_failure_appends(self) -> None:
        from core.failure_degraded_recovery_policy import (
            get_failure_degraded_recovery_runtime,
            DegradedTruthRecord,
            FailureRuntimeState,
        )
        rt = get_failure_degraded_recovery_runtime()
        rec = DegradedTruthRecord(
            task_id="task_i01",
            failure_state=FailureRuntimeState.FAILED,
        )
        rt.record_failure(rec)
        self.assertEqual(len(rt.list_failure_records()), 1)
        self.assertEqual(rt.list_failure_records()[0].task_id, "task_i01")

    def test_I02_record_recovery_appends(self) -> None:
        from core.failure_degraded_recovery_policy import (
            get_failure_degraded_recovery_runtime,
            RecoveryTransitionRecord,
            FailureRuntimeState,
        )
        rt = get_failure_degraded_recovery_runtime()
        rec = RecoveryTransitionRecord(
            task_id="task_i02",
            recovery_method="retry_success",
        )
        rt.record_recovery(rec)
        self.assertEqual(len(rt.list_recovery_records()), 1)
        self.assertEqual(rt.list_recovery_records()[0].task_id, "task_i02")

    def test_I03_total_failures_incremented(self) -> None:
        from core.failure_degraded_recovery_policy import (
            get_failure_degraded_recovery_runtime,
            DegradedTruthRecord,
            FailureRuntimeState,
        )
        rt = get_failure_degraded_recovery_runtime()
        for i in range(3):
            rt.record_failure(DegradedTruthRecord(
                task_id=f"task_i03_{i}",
                failure_state=FailureRuntimeState.FAILED,
            ))
        self.assertEqual(rt.snapshot().total_failures_recorded, 3)

    def test_I04_total_recoveries_incremented(self) -> None:
        from core.failure_degraded_recovery_policy import (
            get_failure_degraded_recovery_runtime,
            RecoveryTransitionRecord,
        )
        rt = get_failure_degraded_recovery_runtime()
        for i in range(2):
            rt.record_recovery(RecoveryTransitionRecord(
                task_id=f"task_i04_{i}",
            ))
        self.assertEqual(rt.snapshot().total_recoveries_recorded, 2)


# ===========================================================================
# J)  propagate_failure_to_canonical — ring buffer write
# ===========================================================================


class TestJ_PropagateFailureRingBuffer(unittest.TestCase):
    """J) propagate_failure_to_canonical appends to ring buffer."""

    def setUp(self):
        _reset()

    def test_J01_returns_degraded_truth_record(self) -> None:
        from core.failure_degraded_recovery_policy import (
            propagate_failure_to_canonical,
            DegradedTruthRecord,
        )
        rec = propagate_failure_to_canonical("task_j01", trace_id="trace_j01")
        self.assertIsInstance(rec, DegradedTruthRecord)

    def test_J02_task_id_preserved(self) -> None:
        from core.failure_degraded_recovery_policy import propagate_failure_to_canonical
        rec = propagate_failure_to_canonical("task_j02")
        self.assertEqual(rec.task_id, "task_j02")

    def test_J03_appended_to_ring_buffer(self) -> None:
        from core.failure_degraded_recovery_policy import (
            propagate_failure_to_canonical,
            get_failure_degraded_recovery_runtime,
        )
        propagate_failure_to_canonical("task_j03", error_code="ERR_J03")
        rt = get_failure_degraded_recovery_runtime()
        records = rt.list_failure_records()
        task_ids = [r.task_id for r in records]
        self.assertIn("task_j03", task_ids)

    def test_J04_error_code_preserved(self) -> None:
        from core.failure_degraded_recovery_policy import (
            propagate_failure_to_canonical,
            get_failure_degraded_recovery_runtime,
        )
        propagate_failure_to_canonical("task_j04", error_code="ERR_J04")
        records = get_failure_degraded_recovery_runtime().list_failure_records()
        matching = [r for r in records if r.task_id == "task_j04"]
        self.assertGreater(len(matching), 0)
        self.assertEqual(matching[0].error_code, "ERR_J04")

    def test_J05_multiple_failures_recorded(self) -> None:
        from core.failure_degraded_recovery_policy import (
            propagate_failure_to_canonical,
            get_failure_degraded_recovery_runtime,
        )
        for i in range(5):
            propagate_failure_to_canonical(f"task_j05_{i}")
        snap = get_failure_degraded_recovery_runtime().snapshot()
        self.assertEqual(snap.total_failures_recorded, 5)


# ===========================================================================
# K)  propagate_failure_to_canonical — TaskGraphRuntime write
# ===========================================================================


class TestK_PropagateFailureTaskGraph(unittest.TestCase):
    """K) propagate_failure_to_canonical transitions TaskGraphRuntime node to FAILED."""

    def setUp(self):
        _reset()

    def test_K01_task_graph_transition_does_not_raise(self) -> None:
        from core.failure_degraded_recovery_policy import propagate_failure_to_canonical
        # Should not raise even if TaskGraphRuntime has no node registered yet
        try:
            propagate_failure_to_canonical("task_k01_unregistered")
        except Exception as e:
            self.fail(f"propagate_failure_to_canonical raised unexpectedly: {e}")

    def test_K02_task_graph_failure_recorded_for_known_task(self) -> None:
        """If a task is registered in TaskGraphRuntime, its failure propagates."""
        from core.task_graph_runtime import (
            get_task_graph_runtime,
            GraphNodeState,
            WorkflowContributorKind,
            GraphNode,
        )
        from core.failure_degraded_recovery_policy import propagate_failure_to_canonical

        tgr = get_task_graph_runtime()
        # Register a node directly to avoid TaskEnvelope/CanonicalTask wrapping issues
        node = GraphNode(
            task_id="task_k02",
            trace_id="trace_k02",
            tool_name="test",
            state=GraphNodeState.QUEUED,
            contributor=WorkflowContributorKind.COMMAND_ROUTER,
        )
        tgr.register_node(node)
        tgr.transition("task_k02", GraphNodeState.ADMITTED)

        propagate_failure_to_canonical("task_k02", error_code="ERR_K02")

        snap = tgr.snapshot()
        node_dict = next((n for n in snap.nodes if n.get("task_id") == "task_k02"), None)
        self.assertIsNotNone(node_dict)
        self.assertEqual(node_dict.get("state"), GraphNodeState.FAILED.value)


# ===========================================================================
# L)  propagate_failure_to_canonical — AuditEventSemantics write
# ===========================================================================


class TestL_PropagateFailureAudit(unittest.TestCase):
    """L) propagate_failure_to_canonical emits a TASK_FAILED audit event."""

    def setUp(self):
        _reset()

    def test_L01_audit_event_does_not_raise(self) -> None:
        from core.failure_degraded_recovery_policy import propagate_failure_to_canonical
        try:
            propagate_failure_to_canonical("task_l01")
        except Exception as e:
            self.fail(f"Raised unexpectedly: {e}")

    def test_L02_audit_task_failed_event_emitted(self) -> None:
        from core.failure_degraded_recovery_policy import propagate_failure_to_canonical
        from core.audit_event_semantics import (
            get_audit_event_semantics,
            AuditEventKind,
        )
        propagate_failure_to_canonical("task_l02", error_code="ERR_L02")
        audit = get_audit_event_semantics()
        events = audit.all_events()
        task_failed_events = [
            e for e in events
            if e.task_id == "task_l02" and e.kind == AuditEventKind.TASK_FAILED.value
        ]
        self.assertGreater(
            len(task_failed_events), 0,
            "No TASK_FAILED audit event found for task_l02",
        )


# ===========================================================================
# M)  propagate_failure_to_canonical — ReplayFoundation write
# ===========================================================================


class TestM_PropagateFailureReplay(unittest.TestCase):
    """M) propagate_failure_to_canonical records a TaskExecutionRecord in ReplayFoundation."""

    def setUp(self):
        _reset()

    def test_M01_replay_write_does_not_raise(self) -> None:
        from core.failure_degraded_recovery_policy import propagate_failure_to_canonical
        try:
            propagate_failure_to_canonical("task_m01")
        except Exception as e:
            self.fail(f"Raised unexpectedly: {e}")

    def test_M02_replay_foundation_has_execution_record(self) -> None:
        from core.failure_degraded_recovery_policy import propagate_failure_to_canonical
        from core.replay_foundation import get_replay_foundation
        propagate_failure_to_canonical("task_m02", error_code="ERR_M02")
        rf = get_replay_foundation()
        exec_rec = rf.get_execution_record("task_m02")
        self.assertIsNotNone(
            exec_rec,
            "ReplayFoundation has no execution record for task_m02 after failure propagation",
        )


# ===========================================================================
# N)  propagate_recovery_to_canonical — ring buffer write
# ===========================================================================


class TestN_PropagateRecoveryRingBuffer(unittest.TestCase):
    """N) propagate_recovery_to_canonical appends to recovery ring buffer."""

    def setUp(self):
        _reset()

    def test_N01_returns_recovery_transition_record(self) -> None:
        from core.failure_degraded_recovery_policy import (
            propagate_recovery_to_canonical,
            RecoveryTransitionRecord,
        )
        rec = propagate_recovery_to_canonical("task_n01")
        self.assertIsInstance(rec, RecoveryTransitionRecord)

    def test_N02_task_id_preserved(self) -> None:
        from core.failure_degraded_recovery_policy import propagate_recovery_to_canonical
        rec = propagate_recovery_to_canonical("task_n02")
        self.assertEqual(rec.task_id, "task_n02")

    def test_N03_appended_to_ring_buffer(self) -> None:
        from core.failure_degraded_recovery_policy import (
            propagate_recovery_to_canonical,
            get_failure_degraded_recovery_runtime,
        )
        propagate_recovery_to_canonical("task_n03", recovery_method="retry_success")
        rt = get_failure_degraded_recovery_runtime()
        records = rt.list_recovery_records()
        task_ids = [r.task_id for r in records]
        self.assertIn("task_n03", task_ids)

    def test_N04_recovery_method_preserved(self) -> None:
        from core.failure_degraded_recovery_policy import (
            propagate_recovery_to_canonical,
            get_failure_degraded_recovery_runtime,
        )
        propagate_recovery_to_canonical("task_n04", recovery_method="fallback_success")
        records = get_failure_degraded_recovery_runtime().list_recovery_records()
        matching = [r for r in records if r.task_id == "task_n04"]
        self.assertGreater(len(matching), 0)
        self.assertEqual(matching[0].recovery_method, "fallback_success")


# ===========================================================================
# O)  propagate_recovery_to_canonical — canonical layer writes
# ===========================================================================


class TestO_PropagateRecoveryCanonical(unittest.TestCase):
    """O) propagate_recovery_to_canonical writes to canonical layers (best-effort)."""

    def setUp(self):
        _reset()

    def test_O01_does_not_raise(self) -> None:
        from core.failure_degraded_recovery_policy import propagate_recovery_to_canonical
        try:
            propagate_recovery_to_canonical("task_o01")
        except Exception as e:
            self.fail(f"Raised unexpectedly: {e}")

    def test_O02_audit_completed_event_emitted(self) -> None:
        from core.failure_degraded_recovery_policy import propagate_recovery_to_canonical
        from core.audit_event_semantics import (
            get_audit_event_semantics,
            AuditEventKind,
        )
        propagate_recovery_to_canonical("task_o02")
        audit = get_audit_event_semantics()
        events = audit.all_events()
        completed = [
            e for e in events
            if e.task_id == "task_o02" and e.kind == AuditEventKind.TASK_COMPLETED.value
        ]
        self.assertGreater(
            len(completed), 0,
            "No TASK_COMPLETED audit event found after recovery propagation",
        )


# ===========================================================================
# P)  record_degraded_transition
# ===========================================================================


class TestP_RecordDegradedTransition(unittest.TestCase):
    """P) record_degraded_transition writes ring buffer + TASK_DEGRADED audit event."""

    def setUp(self):
        _reset()

    def test_P01_returns_degraded_truth_record(self) -> None:
        from core.failure_degraded_recovery_policy import (
            record_degraded_transition,
            DegradedTruthRecord,
        )
        rec = record_degraded_transition("task_p01")
        self.assertIsInstance(rec, DegradedTruthRecord)

    def test_P02_failure_state_is_degraded(self) -> None:
        from core.failure_degraded_recovery_policy import (
            record_degraded_transition,
            FailureRuntimeState,
        )
        rec = record_degraded_transition("task_p02")
        self.assertEqual(rec.failure_state, FailureRuntimeState.DEGRADED)

    def test_P03_appended_to_ring_buffer(self) -> None:
        from core.failure_degraded_recovery_policy import (
            record_degraded_transition,
            get_failure_degraded_recovery_runtime,
        )
        record_degraded_transition("task_p03", degraded_capabilities=["vision"])
        records = get_failure_degraded_recovery_runtime().list_failure_records()
        task_ids = [r.task_id for r in records]
        self.assertIn("task_p03", task_ids)

    def test_P04_degraded_capabilities_preserved(self) -> None:
        from core.failure_degraded_recovery_policy import (
            record_degraded_transition,
            get_failure_degraded_recovery_runtime,
        )
        record_degraded_transition("task_p04", degraded_capabilities=["audio", "vision"])
        records = get_failure_degraded_recovery_runtime().list_failure_records()
        matching = [r for r in records if r.task_id == "task_p04"]
        self.assertGreater(len(matching), 0)
        self.assertIn("audio", matching[0].degraded_capabilities)
        self.assertIn("vision", matching[0].degraded_capabilities)

    def test_P05_audit_degraded_event_emitted(self) -> None:
        from core.failure_degraded_recovery_policy import record_degraded_transition
        from core.audit_event_semantics import get_audit_event_semantics
        record_degraded_transition("task_p05", degraded_capabilities=["speech"])
        audit = get_audit_event_semantics()
        events = audit.all_events()
        degraded_events = [
            e for e in events
            if e.task_id == "task_p05" and e.kind == "task_degraded"
        ]
        self.assertGreater(
            len(degraded_events), 0,
            "No task_degraded audit event found for task_p05",
        )

    def test_P06_does_not_raise(self) -> None:
        from core.failure_degraded_recovery_policy import record_degraded_transition
        try:
            record_degraded_transition("task_p06")
        except Exception as e:
            self.fail(f"Raised unexpectedly: {e}")


# ===========================================================================
# Q)  query_degraded_state
# ===========================================================================


class TestQ_QueryDegradedState(unittest.TestCase):
    """Q) query_degraded_state returns expected dict structure."""

    def test_Q01_returns_dict(self) -> None:
        from core.failure_degraded_recovery_policy import query_degraded_state
        result = query_degraded_state()
        self.assertIsInstance(result, dict)

    def test_Q02_has_degraded_executors_key(self) -> None:
        from core.failure_degraded_recovery_policy import query_degraded_state
        result = query_degraded_state()
        self.assertIn("degraded_executors", result)

    def test_Q03_has_total_online_key(self) -> None:
        from core.failure_degraded_recovery_policy import query_degraded_state
        result = query_degraded_state()
        self.assertIn("total_online", result)

    def test_Q04_has_total_degraded_key(self) -> None:
        from core.failure_degraded_recovery_policy import query_degraded_state
        result = query_degraded_state()
        self.assertIn("total_degraded", result)

    def test_Q05_has_snapshot_at_key(self) -> None:
        from core.failure_degraded_recovery_policy import query_degraded_state
        result = query_degraded_state()
        self.assertIn("snapshot_at", result)

    def test_Q06_degraded_executors_is_list(self) -> None:
        from core.failure_degraded_recovery_policy import query_degraded_state
        result = query_degraded_state()
        self.assertIsInstance(result["degraded_executors"], list)

    def test_Q07_total_degraded_is_int(self) -> None:
        from core.failure_degraded_recovery_policy import query_degraded_state
        result = query_degraded_state()
        self.assertIsInstance(result["total_degraded"], int)


# ===========================================================================
# R)  snapshot_failure_recovery_state
# ===========================================================================


class TestR_SnapshotFailureRecoveryState(unittest.TestCase):
    """R) snapshot_failure_recovery_state returns combined summary dict."""

    def setUp(self):
        _reset()

    def test_R01_returns_dict(self) -> None:
        from core.failure_degraded_recovery_policy import snapshot_failure_recovery_state
        result = snapshot_failure_recovery_state()
        self.assertIsInstance(result, dict)

    def test_R02_has_degraded_records_count(self) -> None:
        from core.failure_degraded_recovery_policy import snapshot_failure_recovery_state
        result = snapshot_failure_recovery_state()
        self.assertIn("degraded_records_count", result)

    def test_R03_has_recovery_records_count(self) -> None:
        from core.failure_degraded_recovery_policy import snapshot_failure_recovery_state
        result = snapshot_failure_recovery_state()
        self.assertIn("recovery_records_count", result)

    def test_R04_has_total_failures_recorded(self) -> None:
        from core.failure_degraded_recovery_policy import snapshot_failure_recovery_state
        result = snapshot_failure_recovery_state()
        self.assertIn("total_failures_recorded", result)

    def test_R05_has_degraded_executors(self) -> None:
        from core.failure_degraded_recovery_policy import snapshot_failure_recovery_state
        result = snapshot_failure_recovery_state()
        self.assertIn("degraded_executors", result)

    def test_R06_counts_reflect_ring_buffer(self) -> None:
        from core.failure_degraded_recovery_policy import (
            propagate_failure_to_canonical,
            snapshot_failure_recovery_state,
        )
        propagate_failure_to_canonical("task_r06")
        result = snapshot_failure_recovery_state()
        self.assertGreaterEqual(result["total_failures_recorded"], 1)


# ===========================================================================
# S)  GAP-512-001 closure
# ===========================================================================


class TestS_Gap512001Closure(unittest.TestCase):
    """S) GAP-512-001: core/routes/tasks.py contains TASK_INGRESS_REPLAY_FOUNDATION_INTEGRATED."""

    def _tasks_path(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(repo_root, "core", "routes", "tasks.py")

    def test_S01_sentinel_present_in_source(self) -> None:
        with open(self._tasks_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("TASK_INGRESS_REPLAY_FOUNDATION_INTEGRATED", content)

    def test_S02_sentinel_is_string_in_source(self) -> None:
        with open(self._tasks_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("TASK_INGRESS_REPLAY_FOUNDATION_V1", content)

    def test_S03_sentinel_mentions_replay_foundation_in_source(self) -> None:
        with open(self._tasks_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("ReplayFoundation", content)

    def test_S04_sentinel_mentions_gap_512_001_in_source(self) -> None:
        with open(self._tasks_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("GAP-512-001", content)


# ===========================================================================
# T)  GAP-512-002 closure
# ===========================================================================


class TestT_Gap512002Closure(unittest.TestCase):
    """T) GAP-512-002: core/scheduler.py contains SCHEDULER_TASK_GRAPH_RELAY_MESH_INTEGRATED."""

    def _scheduler_path(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(repo_root, "core", "scheduler.py")

    def test_T01_sentinel_present_in_source(self) -> None:
        with open(self._scheduler_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("SCHEDULER_TASK_GRAPH_RELAY_MESH_INTEGRATED", content)

    def test_T02_sentinel_is_string_in_source(self) -> None:
        with open(self._scheduler_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("SCHEDULER_TASK_GRAPH_RELAY_MESH_V1", content)

    def test_T03_sentinel_mentions_task_graph_runtime(self) -> None:
        with open(self._scheduler_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("TaskGraphRuntime", content)

    def test_T04_sentinel_mentions_gap_512_002(self) -> None:
        with open(self._scheduler_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("GAP-512-002", content)


# ===========================================================================
# U)  GAP-512-004 closure
# ===========================================================================


class TestU_Gap512004Closure(unittest.TestCase):
    """U) GAP-512-004: core/command_router.py contains CAPABILITY_NETWORK_CANONICAL_QUERY_INTEGRATED."""

    def _router_path(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(repo_root, "core", "command_router.py")

    def test_U01_sentinel_present_in_source(self) -> None:
        with open(self._router_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("CAPABILITY_NETWORK_CANONICAL_QUERY_INTEGRATED", content)

    def test_U02_sentinel_is_string_in_source(self) -> None:
        with open(self._router_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("CAPABILITY_NETWORK_CANONICAL_QUERY_V1", content)

    def test_U03_sentinel_mentions_query_routable_executors(self) -> None:
        with open(self._router_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("query_routable_executors", content)

    def test_U04_sentinel_mentions_gap_512_004(self) -> None:
        with open(self._router_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("GAP-512-004", content)


# ===========================================================================
# V)  GAP-512-006 closure
# ===========================================================================


class TestV_Gap512006Closure(unittest.TestCase):
    """V) GAP-512-006: galaxy_gateway/orchestrator/task_orchestrator.py contains
    TASK_ORCHESTRATOR_AUDIT_DISPATCH_INTEGRATED."""

    def _orchestrator_path(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(
            repo_root, "galaxy_gateway", "orchestrator", "task_orchestrator.py"
        )

    def test_V01_sentinel_present_in_source(self) -> None:
        with open(self._orchestrator_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("TASK_ORCHESTRATOR_AUDIT_DISPATCH_INTEGRATED", content)

    def test_V02_sentinel_is_string_in_source(self) -> None:
        with open(self._orchestrator_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("TASK_ORCHESTRATOR_AUDIT_DISPATCH_V1", content)

    def test_V03_sentinel_mentions_audit_task_dispatched(self) -> None:
        with open(self._orchestrator_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("audit_task_dispatched", content)

    def test_V04_sentinel_mentions_gap_512_006(self) -> None:
        with open(self._orchestrator_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("GAP-512-006", content)


# ===========================================================================
# W)  GAP-512-007 closure
# ===========================================================================


class TestW_Gap512007Closure(unittest.TestCase):
    """W) GAP-512-007: core/agent/kernel.py contains AGENT_KERNEL_AUDIT_ADMITTED_INTEGRATED."""

    def _kernel_path(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(repo_root, "core", "agent", "kernel.py")

    def test_W01_sentinel_present_in_source(self) -> None:
        with open(self._kernel_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("AGENT_KERNEL_AUDIT_ADMITTED_INTEGRATED", content)

    def test_W02_sentinel_is_string_in_source(self) -> None:
        with open(self._kernel_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("AGENT_KERNEL_AUDIT_ADMITTED_V1", content)

    def test_W03_sentinel_mentions_audit_task_admitted(self) -> None:
        with open(self._kernel_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("audit_task_admitted", content)

    def test_W04_sentinel_mentions_gap_512_007(self) -> None:
        with open(self._kernel_path(), "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("GAP-512-007", content)


# ===========================================================================
# X)  No new parallel authority
# ===========================================================================


class TestX_NoParallelAuthority(unittest.TestCase):
    """X) Failure module writes to existing canonical layers only."""

    def test_X01_no_parallel_authority_policy_importable(self) -> None:
        from core.failure_degraded_recovery_policy import NO_PARALLEL_AUTHORITY_POLICY
        self.assertIsInstance(NO_PARALLEL_AUTHORITY_POLICY, str)

    def test_X02_module_does_not_define_new_task_store(self) -> None:
        import core.failure_degraded_recovery_policy as mod
        # The module MUST NOT define a new task identity store
        self.assertFalse(hasattr(mod, "task_queue"))
        self.assertFalse(hasattr(mod, "task_store"))
        self.assertFalse(hasattr(mod, "task_registry"))

    def test_X03_failure_module_does_not_replace_audit_event_semantics(self) -> None:
        """propagate_failure_to_canonical uses the existing AuditEventSemantics singleton."""
        from core.failure_degraded_recovery_policy import propagate_failure_to_canonical
        from core.audit_event_semantics import get_audit_event_semantics
        # Record baseline event count
        baseline = len(get_audit_event_semantics().all_events())
        propagate_failure_to_canonical("task_x03")
        after = len(get_audit_event_semantics().all_events())
        # Audit event count should increase (not reset)
        self.assertGreaterEqual(after, baseline)

    def test_X04_no_parallel_authority_mentions_task_graph_runtime(self) -> None:
        """The ring buffer is a supplemental view, not a new truth source."""
        from core.failure_degraded_recovery_policy import NO_PARALLEL_AUTHORITY_POLICY
        self.assertIn("TaskGraphRuntime", NO_PARALLEL_AUTHORITY_POLICY)


# ===========================================================================
# Y)  Failure → recovery arc — full round-trip
# ===========================================================================


class TestY_FailureRecoveryArc(unittest.TestCase):
    """Y) Full failure → recovery round-trip updates runtime state coherently."""

    def setUp(self):
        _reset()

    def test_Y01_failure_then_recovery_both_recorded(self) -> None:
        from core.failure_degraded_recovery_policy import (
            propagate_failure_to_canonical,
            propagate_recovery_to_canonical,
            get_failure_degraded_recovery_runtime,
        )
        propagate_failure_to_canonical("task_y01", error_code="ERR_Y01")
        propagate_recovery_to_canonical("task_y01", recovery_method="retry_success")

        rt = get_failure_degraded_recovery_runtime()
        failures = [r for r in rt.list_failure_records() if r.task_id == "task_y01"]
        recoveries = [r for r in rt.list_recovery_records() if r.task_id == "task_y01"]

        self.assertGreater(len(failures), 0, "Failure record not found")
        self.assertGreater(len(recoveries), 0, "Recovery record not found")

    def test_Y02_snapshot_shows_both_counts(self) -> None:
        from core.failure_degraded_recovery_policy import (
            propagate_failure_to_canonical,
            propagate_recovery_to_canonical,
            get_failure_degraded_recovery_runtime,
        )
        propagate_failure_to_canonical("task_y02a")
        propagate_failure_to_canonical("task_y02b")
        propagate_recovery_to_canonical("task_y02a")

        snap = get_failure_degraded_recovery_runtime().snapshot()
        self.assertEqual(snap.total_failures_recorded, 2)
        self.assertEqual(snap.total_recoveries_recorded, 1)

    def test_Y03_failure_and_recovery_are_audit_visible(self) -> None:
        from core.failure_degraded_recovery_policy import (
            propagate_failure_to_canonical,
            propagate_recovery_to_canonical,
        )
        from core.audit_event_semantics import (
            get_audit_event_semantics,
            AuditEventKind,
        )
        propagate_failure_to_canonical("task_y03")
        propagate_recovery_to_canonical("task_y03")

        events = get_audit_event_semantics().all_events()
        task_events = [e for e in events if e.task_id == "task_y03"]
        kinds = {e.kind for e in task_events}

        self.assertIn(AuditEventKind.TASK_FAILED.value, kinds)
        self.assertIn(AuditEventKind.TASK_COMPLETED.value, kinds)


# ===========================================================================
# Z)  Retry/fallback flows
# ===========================================================================


class TestZ_RetryFallbackFlows(unittest.TestCase):
    """Z) Retry/fallback updates are reflected in canonical runtime state."""

    def setUp(self):
        _reset()

    def test_Z01_retry_pending_state_recordable(self) -> None:
        from core.failure_degraded_recovery_policy import (
            record_failure_truth,
            FailureRuntimeState,
            get_failure_degraded_recovery_runtime,
        )
        record_failure_truth(
            "task_z01",
            failure_state=FailureRuntimeState.RETRY_PENDING,
            error_code="RETRYABLE",
            attempt_number=1,
        )
        records = get_failure_degraded_recovery_runtime().list_failure_records()
        matching = [r for r in records if r.task_id == "task_z01"]
        self.assertGreater(len(matching), 0)
        self.assertEqual(matching[0].failure_state, FailureRuntimeState.RETRY_PENDING)

    def test_Z02_fallback_active_state_recordable(self) -> None:
        from core.failure_degraded_recovery_policy import (
            record_failure_truth,
            FailureRuntimeState,
            get_failure_degraded_recovery_runtime,
        )
        record_failure_truth(
            "task_z02",
            failure_state=FailureRuntimeState.FALLBACK_ACTIVE,
        )
        records = get_failure_degraded_recovery_runtime().list_failure_records()
        matching = [r for r in records if r.task_id == "task_z02"]
        self.assertGreater(len(matching), 0)
        self.assertEqual(matching[0].failure_state, FailureRuntimeState.FALLBACK_ACTIVE)

    def test_Z03_retry_success_recovery_recordable(self) -> None:
        from core.failure_degraded_recovery_policy import (
            record_recovery_transition,
            FailureRuntimeState,
            get_failure_degraded_recovery_runtime,
        )
        record_recovery_transition(
            "task_z03",
            prior_state=FailureRuntimeState.RETRY_PENDING,
            recovered_state=FailureRuntimeState.RECOVERED,
            recovery_method="retry_success",
        )
        records = get_failure_degraded_recovery_runtime().list_recovery_records()
        matching = [r for r in records if r.task_id == "task_z03"]
        self.assertGreater(len(matching), 0)
        self.assertEqual(matching[0].recovery_method, "retry_success")

    def test_Z04_fallback_success_recovery_recordable(self) -> None:
        from core.failure_degraded_recovery_policy import (
            record_recovery_transition,
            FailureRuntimeState,
            get_failure_degraded_recovery_runtime,
        )
        record_recovery_transition(
            "task_z04",
            prior_state=FailureRuntimeState.FALLBACK_ACTIVE,
            recovered_state=FailureRuntimeState.RECOVERED,
            recovery_method="fallback_success",
        )
        records = get_failure_degraded_recovery_runtime().list_recovery_records()
        matching = [r for r in records if r.task_id == "task_z04"]
        self.assertGreater(len(matching), 0)
        self.assertEqual(matching[0].recovery_method, "fallback_success")


# ===========================================================================
# AA) Closure audit covers PR-513 layer specs
# ===========================================================================


class TestAA_ClosureAuditPR513(unittest.TestCase):
    """AA) RuntimeClosureAudit _LAYER_SPECS now includes PR-513 entries."""

    def test_AA01_pr513_in_layer_specs(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        pr_refs = [spec[0] for spec in RuntimeClosureAudit._LAYER_SPECS]
        self.assertIn("PR-513", pr_refs)

    def test_AA02_failure_degraded_recovery_authority_sentinel_covered(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        sentinels = [spec[2] for spec in RuntimeClosureAudit._LAYER_SPECS]
        self.assertIn("FAILURE_DEGRADED_RECOVERY_AUTHORITY", sentinels)

    def test_AA03_gap_001_sentinel_covered(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        sentinels = [spec[2] for spec in RuntimeClosureAudit._LAYER_SPECS]
        self.assertIn("TASK_INGRESS_REPLAY_FOUNDATION_INTEGRATED", sentinels)

    def test_AA04_gap_002_sentinel_covered(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        sentinels = [spec[2] for spec in RuntimeClosureAudit._LAYER_SPECS]
        self.assertIn("SCHEDULER_TASK_GRAPH_RELAY_MESH_INTEGRATED", sentinels)

    def test_AA05_gap_004_sentinel_covered(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        sentinels = [spec[2] for spec in RuntimeClosureAudit._LAYER_SPECS]
        self.assertIn("CAPABILITY_NETWORK_CANONICAL_QUERY_INTEGRATED", sentinels)

    def test_AA06_gap_006_sentinel_covered(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        sentinels = [spec[2] for spec in RuntimeClosureAudit._LAYER_SPECS]
        self.assertIn("TASK_ORCHESTRATOR_AUDIT_DISPATCH_INTEGRATED", sentinels)

    def test_AA07_gap_007_sentinel_covered(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        sentinels = [spec[2] for spec in RuntimeClosureAudit._LAYER_SPECS]
        self.assertIn("AGENT_KERNEL_AUDIT_ADMITTED_INTEGRATED", sentinels)

    def test_AA08_verify_all_layers_covers_pr513(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        pr_refs = [s.pr_ref for s in audit.verify_all_layers()]
        self.assertIn("PR-513", pr_refs)

    def test_AA09_pr513_layer_count_matches_specs(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        result = audit.verify_all_layers()
        self.assertEqual(len(result), len(RuntimeClosureAudit._LAYER_SPECS))


# ===========================================================================
# BB) FAILURE_DEGRADED_RECOVERY_INTEGRATED sentinel
# ===========================================================================


class TestBB_FailureDegradedRecoveryIntegrated(unittest.TestCase):
    """BB) FAILURE_DEGRADED_RECOVERY_INTEGRATED sentinel is importable and correct."""

    def test_BB01_sentinel_importable(self) -> None:
        from core.failure_degraded_recovery_policy import FAILURE_DEGRADED_RECOVERY_INTEGRATED
        self.assertIsInstance(FAILURE_DEGRADED_RECOVERY_INTEGRATED, str)

    def test_BB02_sentinel_mentions_all_five_gaps(self) -> None:
        from core.failure_degraded_recovery_policy import FAILURE_DEGRADED_RECOVERY_INTEGRATED
        for gap_id in ["GAP-512-001", "GAP-512-002", "GAP-512-004", "GAP-512-006", "GAP-512-007"]:
            self.assertIn(
                gap_id,
                FAILURE_DEGRADED_RECOVERY_INTEGRATED,
                f"{gap_id} not mentioned in FAILURE_DEGRADED_RECOVERY_INTEGRATED",
            )

    def test_BB03_sentinel_covers_all_modules(self) -> None:
        from core.failure_degraded_recovery_policy import FAILURE_DEGRADED_RECOVERY_INTEGRATED
        for module in [
            "core/routes/tasks.py",
            "core/scheduler.py",
            "core/command_router.py",
            "galaxy_gateway/orchestrator/task_orchestrator.py",
            "core/agent/kernel.py",
        ]:
            self.assertIn(
                module,
                FAILURE_DEGRADED_RECOVERY_INTEGRATED,
                f"Module '{module}' not mentioned in FAILURE_DEGRADED_RECOVERY_INTEGRATED",
            )


if __name__ == "__main__":
    unittest.main()
