#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prg_recovery_correctness.py
=======================================
PR-G: Recovery correctness hardening and duplicate-safety — test suite.

Coverage
--------
A  — New policy sentinels in task_lifecycle_persistence are importable and
     non-empty strings.
B  — New policy sentinels in runtime_restart_recovery are importable and
     non-empty strings.
C  — INTERRUPTION_CLASS_VS_DISPOSITION_POLICY distinguishes the two concepts.
D  — TERMINAL_DISPOSITION_IS_FINAL_POLICY mentions TERMINAL_ON_INTERRUPT.
E  — SNAPSHOT_DEDUPLICATION_POLICY mentions first-occurrence semantics.
F  — Intra-snapshot deduplication: duplicate task_ids in snapshot are deduplicated
     (first occurrence kept).
G  — Intra-snapshot deduplication: distinct task_ids are all returned.
H  — Intra-snapshot deduplication: empty task_id records pass through unchanged.
I  — RuntimeRecoveryReport has inflight_tasks_already_pending_skipped field.
J  — to_dict includes inflight_tasks_already_pending_skipped key.
K  — Already-pending tasks are skipped and counted in the report.
L  — TERMINAL_ON_INTERRUPT tasks are never registered, even after two consecutive
     recovery passes (recovery idempotency for terminal records).
M  — Running recovery twice is idempotent: the second pass adds 0 new records
     when all tasks are already pending from the first pass.
N  — RECOVERY_DUPLICATE_SAFETY_POLICY sentinel is importable and non-empty.
O  — RECOVERY_IDEMPOTENCY_POLICY sentinel is importable and non-empty.
P  — Mixed scenario: duplicate in snapshot + already-pending + terminal together.
Q  — Duplicate task_id in snapshot with different owners: first owner wins.
R  — Already-pending skip count accumulates correctly across multiple tasks.
S  — RECOVERY_DUPLICATE_SAFETY_POLICY mentions all three layers of protection.
T  — RECOVERY_IDEMPOTENCY_POLICY mentions idempotency explicitly.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stores(tmp_dir: str):
    from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
    from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore
    from core.task_lifecycle_persistence import TaskLifecyclePersistenceStore

    ms_store = MeshSessionPersistenceStore(store_dir=tmp_dir)
    bm_store = BodyMeshPersistenceStore(store_path=os.path.join(tmp_dir, "bm.json"))
    tl_store = TaskLifecyclePersistenceStore(store_path=os.path.join(tmp_dir, "tl.json"))
    return ms_store, bm_store, tl_store


def _save_snapshot(tl_store, records: List[Dict[str, Any]]) -> None:
    from core.task_lifecycle_persistence import save_task_lifecycle_snapshot
    save_task_lifecycle_snapshot(records, store=tl_store)


def _record(
    task_id: str,
    owner: str,
    tool_name: str = "test_tool",
    target_device_id: str = "dev_01",
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "trace_id": f"trace_{task_id}",
        "target_device_id": target_device_id,
        "tool_name": tool_name,
        "owner": owner,
        "timeout": 30.0,
        "registered_at": time.time() - 5.0,
        "metadata": {},
    }


class FakeBodyMeshRegistry:
    def register(self, device_id, roles=None, session_id=None, metadata=None):
        return {}

    def list_entries(self):
        return []


def _make_coordinator(tmp_dir: str, records: List[Dict[str, Any]]):
    ms_store, bm_store, tl_store = _make_stores(tmp_dir)
    _save_snapshot(tl_store, records)
    from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
    return RuntimeRestartRecoveryCoordinator(
        mesh_session_store=ms_store,
        body_mesh_store=bm_store,
        body_mesh_registry=FakeBodyMeshRegistry(),
        task_lifecycle_store=tl_store,
    )


# ---------------------------------------------------------------------------
# A — New sentinels in task_lifecycle_persistence
# ---------------------------------------------------------------------------

class TestTaskLifecycleSentinels:
    def test_A_terminal_disposition_is_final_importable(self):
        from core.task_lifecycle_persistence import TERMINAL_DISPOSITION_IS_FINAL_POLICY
        assert isinstance(TERMINAL_DISPOSITION_IS_FINAL_POLICY, str)
        assert TERMINAL_DISPOSITION_IS_FINAL_POLICY

    def test_A_snapshot_deduplication_policy_importable(self):
        from core.task_lifecycle_persistence import SNAPSHOT_DEDUPLICATION_POLICY
        assert isinstance(SNAPSHOT_DEDUPLICATION_POLICY, str)
        assert SNAPSHOT_DEDUPLICATION_POLICY

    def test_A_interruption_class_vs_disposition_importable(self):
        from core.task_lifecycle_persistence import INTERRUPTION_CLASS_VS_DISPOSITION_POLICY
        assert isinstance(INTERRUPTION_CLASS_VS_DISPOSITION_POLICY, str)
        assert INTERRUPTION_CLASS_VS_DISPOSITION_POLICY


# ---------------------------------------------------------------------------
# B — New sentinels in runtime_restart_recovery
# ---------------------------------------------------------------------------

class TestRuntimeRecoverySentinels:
    def test_B_recovery_duplicate_safety_importable(self):
        from core.runtime_restart_recovery import RECOVERY_DUPLICATE_SAFETY_POLICY
        assert isinstance(RECOVERY_DUPLICATE_SAFETY_POLICY, str)
        assert RECOVERY_DUPLICATE_SAFETY_POLICY

    def test_B_recovery_idempotency_importable(self):
        from core.runtime_restart_recovery import RECOVERY_IDEMPOTENCY_POLICY
        assert isinstance(RECOVERY_IDEMPOTENCY_POLICY, str)
        assert RECOVERY_IDEMPOTENCY_POLICY


# ---------------------------------------------------------------------------
# C — INTERRUPTION_CLASS_VS_DISPOSITION_POLICY distinguishes the two concepts
# ---------------------------------------------------------------------------

class TestInterruptionClassVsDispositionPolicy:
    def test_C_mentions_interruption_class(self):
        from core.task_lifecycle_persistence import INTERRUPTION_CLASS_VS_DISPOSITION_POLICY
        text = INTERRUPTION_CLASS_VS_DISPOSITION_POLICY
        assert "ExecutionInterruptionClass" in text or "interruption_class" in text.lower()

    def test_C_mentions_inflight_task_disposition(self):
        from core.task_lifecycle_persistence import INTERRUPTION_CLASS_VS_DISPOSITION_POLICY
        text = INTERRUPTION_CLASS_VS_DISPOSITION_POLICY
        assert "InFlightTaskDisposition" in text or "disposition" in text.lower()

    def test_C_mentions_orthogonal_or_distinct(self):
        from core.task_lifecycle_persistence import INTERRUPTION_CLASS_VS_DISPOSITION_POLICY
        lower = INTERRUPTION_CLASS_VS_DISPOSITION_POLICY.lower()
        assert "orthogonal" in lower or "distinct" in lower or "not be conflated" in lower


# ---------------------------------------------------------------------------
# D — TERMINAL_DISPOSITION_IS_FINAL_POLICY mentions TERMINAL_ON_INTERRUPT
# ---------------------------------------------------------------------------

class TestTerminalDispositionPolicy:
    def test_D_mentions_terminal_on_interrupt(self):
        from core.task_lifecycle_persistence import TERMINAL_DISPOSITION_IS_FINAL_POLICY
        assert "TERMINAL_ON_INTERRUPT" in TERMINAL_DISPOSITION_IS_FINAL_POLICY

    def test_D_mentions_duplicate_delivery_risk(self):
        from core.task_lifecycle_persistence import TERMINAL_DISPOSITION_IS_FINAL_POLICY
        lower = TERMINAL_DISPOSITION_IS_FINAL_POLICY.lower()
        assert "duplicate" in lower

    def test_D_mentions_not_re_registered(self):
        from core.task_lifecycle_persistence import TERMINAL_DISPOSITION_IS_FINAL_POLICY
        lower = TERMINAL_DISPOSITION_IS_FINAL_POLICY.lower()
        assert "must not" in lower or "not be re-" in lower or "not re-activated" in lower


# ---------------------------------------------------------------------------
# E — SNAPSHOT_DEDUPLICATION_POLICY mentions first-occurrence semantics
# ---------------------------------------------------------------------------

class TestSnapshotDeduplicationPolicy:
    def test_E_mentions_first_occurrence(self):
        from core.task_lifecycle_persistence import SNAPSHOT_DEDUPLICATION_POLICY
        lower = SNAPSHOT_DEDUPLICATION_POLICY.lower()
        assert "first" in lower

    def test_E_mentions_duplicate(self):
        from core.task_lifecycle_persistence import SNAPSHOT_DEDUPLICATION_POLICY
        assert "duplicate" in SNAPSHOT_DEDUPLICATION_POLICY.lower()

    def test_E_mentions_task_id(self):
        from core.task_lifecycle_persistence import SNAPSHOT_DEDUPLICATION_POLICY
        assert "task_id" in SNAPSHOT_DEDUPLICATION_POLICY


# ---------------------------------------------------------------------------
# F — Intra-snapshot deduplication: duplicate task_ids are deduplicated
# ---------------------------------------------------------------------------

class TestIntraSnapshotDeduplication:
    def test_F_duplicate_task_ids_deduplicated(self, tmp_path):
        from core.task_lifecycle_persistence import (
            TaskLifecyclePersistenceStore,
            restore_inflight_tasks_from_snapshot,
            save_task_lifecycle_snapshot,
        )
        store = TaskLifecyclePersistenceStore(
            store_path=str(tmp_path / "tl.json")
        )
        # Two records with the same task_id but different owners
        records = [
            _record("dup-task-1", "device_dispatch"),
            _record("dup-task-1", "routing"),  # duplicate
        ]
        save_task_lifecycle_snapshot(records, store=store)
        restored = restore_inflight_tasks_from_snapshot(store=store)
        task_ids = [r.task_id for r in restored]
        assert task_ids.count("dup-task-1") == 1, (
            "Duplicate task_id in snapshot should yield exactly one restored record"
        )

    def test_F_first_occurrence_owner_is_kept(self, tmp_path):
        from core.task_lifecycle_persistence import (
            TaskLifecyclePersistenceStore,
            InFlightTaskDisposition,
            restore_inflight_tasks_from_snapshot,
            save_task_lifecycle_snapshot,
        )
        store = TaskLifecyclePersistenceStore(
            store_path=str(tmp_path / "tl.json")
        )
        records = [
            _record("dup-task-2", "device_dispatch"),   # first → RESUMABLE
            _record("dup-task-2", "routing"),            # duplicate → should be dropped
        ]
        save_task_lifecycle_snapshot(records, store=store)
        restored = restore_inflight_tasks_from_snapshot(store=store)
        assert len(restored) == 1
        assert restored[0].disposition == InFlightTaskDisposition.RESUMABLE

    def test_F_three_duplicates_only_one_kept(self, tmp_path):
        from core.task_lifecycle_persistence import (
            TaskLifecyclePersistenceStore,
            restore_inflight_tasks_from_snapshot,
            save_task_lifecycle_snapshot,
        )
        store = TaskLifecyclePersistenceStore(
            store_path=str(tmp_path / "tl.json")
        )
        records = [
            _record("trip-task", "device_dispatch"),
            _record("trip-task", "routing"),
            _record("trip-task", "gateway_ingress"),
        ]
        save_task_lifecycle_snapshot(records, store=store)
        restored = restore_inflight_tasks_from_snapshot(store=store)
        assert [r.task_id for r in restored].count("trip-task") == 1


# ---------------------------------------------------------------------------
# G — Intra-snapshot deduplication: distinct task_ids are all returned
# ---------------------------------------------------------------------------

class TestIntraSnapshotDistinct:
    def test_G_distinct_task_ids_all_returned(self, tmp_path):
        from core.task_lifecycle_persistence import (
            TaskLifecyclePersistenceStore,
            restore_inflight_tasks_from_snapshot,
            save_task_lifecycle_snapshot,
        )
        store = TaskLifecyclePersistenceStore(
            store_path=str(tmp_path / "tl.json")
        )
        records = [
            _record("task-a", "device_dispatch"),
            _record("task-b", "routing"),
            _record("task-c", "gateway_ingress"),
        ]
        save_task_lifecycle_snapshot(records, store=store)
        restored = restore_inflight_tasks_from_snapshot(store=store)
        assert len(restored) == 3
        returned_ids = {r.task_id for r in restored}
        assert returned_ids == {"task-a", "task-b", "task-c"}


# ---------------------------------------------------------------------------
# H — Records with empty task_id pass through without dedup tracking
# ---------------------------------------------------------------------------

class TestEmptyTaskId:
    def test_H_empty_task_id_passes_through(self, tmp_path):
        from core.task_lifecycle_persistence import (
            TaskLifecyclePersistenceStore,
            restore_inflight_tasks_from_snapshot,
            save_task_lifecycle_snapshot,
        )
        store = TaskLifecyclePersistenceStore(
            store_path=str(tmp_path / "tl.json")
        )
        # Record with empty task_id (unusual but shouldn't crash)
        raw_empty = {
            "task_id": "",
            "trace_id": "trace_empty",
            "target_device_id": "dev_01",
            "tool_name": "t",
            "owner": "routing",
            "timeout": 30.0,
            "registered_at": time.time(),
            "metadata": {},
        }
        save_task_lifecycle_snapshot([raw_empty, _record("normal-task", "routing")], store=store)
        restored = restore_inflight_tasks_from_snapshot(store=store)
        # Both should be present; empty task_id record is not dedup-tracked
        assert len(restored) == 2


# ---------------------------------------------------------------------------
# I — RuntimeRecoveryReport has inflight_tasks_already_pending_skipped
# ---------------------------------------------------------------------------

class TestReportHasAlreadyPendingSkipped:
    def test_I_field_exists(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        assert hasattr(r, "inflight_tasks_already_pending_skipped")
        assert r.inflight_tasks_already_pending_skipped == 0


# ---------------------------------------------------------------------------
# J — to_dict includes inflight_tasks_already_pending_skipped
# ---------------------------------------------------------------------------

class TestToDictIncludesAlreadyPendingSkipped:
    def test_J_to_dict_key_present(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        d = r.to_dict()
        assert "inflight_tasks_already_pending_skipped" in d

    def test_J_to_dict_value_reflects_field(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        r.inflight_tasks_already_pending_skipped = 7
        assert r.to_dict()["inflight_tasks_already_pending_skipped"] == 7


# ---------------------------------------------------------------------------
# K — Already-pending tasks are skipped and counted
# ---------------------------------------------------------------------------

class TestAlreadyPendingSkipped:
    def test_K_already_pending_skipped_is_counted(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
            LifecycleOwner,
            PendingEnvelopeRecord,
        )
        reset_lifecycle_registry()
        try:
            ms_store, bm_store, tl_store = _make_stores(str(tmp_path))
            _save_snapshot(tl_store, [
                _record("task-live", "device_dispatch"),    # already in registry
                _record("task-new", "routing"),             # fresh
            ])

            # Pre-register task-live so it's already pending
            registry = get_lifecycle_registry()
            live_rec = PendingEnvelopeRecord(
                task_id="task-live",
                trace_id="trace_live",
                target_device_id="dev_01",
                tool_name="tool",
                owner=LifecycleOwner.DEVICE_DISPATCH,
                timeout=30.0,
                registered_at=time.time(),
                future=None,
                metadata={},
            )
            registry._pending["task-live"] = live_rec

            from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
            coord = RuntimeRestartRecoveryCoordinator(
                mesh_session_store=ms_store,
                body_mesh_store=bm_store,
                body_mesh_registry=FakeBodyMeshRegistry(),
                task_lifecycle_store=tl_store,
            )
            report = coord.run_recovery()

            assert report.inflight_tasks_already_pending_skipped == 1
            assert report.inflight_tasks_dispatch_actions_taken == 1
        finally:
            reset_lifecycle_registry()


# ---------------------------------------------------------------------------
# L — TERMINAL_ON_INTERRUPT never registered after two consecutive recovery passes
# ---------------------------------------------------------------------------

class TestTerminalNeverReRegistered:
    def test_L_terminal_not_registered_after_two_passes(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
        )
        reset_lifecycle_registry()
        try:
            ms_store, bm_store, tl_store = _make_stores(str(tmp_path))
            _save_snapshot(tl_store, [
                _record("task-terminal", "result_completion"),
            ])

            from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
            # First pass
            coord1 = RuntimeRestartRecoveryCoordinator(
                mesh_session_store=ms_store,
                body_mesh_store=bm_store,
                body_mesh_registry=FakeBodyMeshRegistry(),
                task_lifecycle_store=tl_store,
            )
            report1 = coord1.run_recovery()
            assert report1.inflight_tasks_terminal == 1
            assert report1.inflight_tasks_dispatch_actions_taken == 0

            registry = get_lifecycle_registry()
            assert not registry.is_pending("task-terminal"), (
                "TERMINAL_ON_INTERRUPT must not be registered after first pass"
            )

            # Second pass (same snapshot still on disk)
            coord2 = RuntimeRestartRecoveryCoordinator(
                mesh_session_store=ms_store,
                body_mesh_store=bm_store,
                body_mesh_registry=FakeBodyMeshRegistry(),
                task_lifecycle_store=tl_store,
            )
            report2 = coord2.run_recovery()
            assert not registry.is_pending("task-terminal"), (
                "TERMINAL_ON_INTERRUPT must not be registered after second pass either"
            )
            assert report2.inflight_tasks_dispatch_actions_taken == 0
        finally:
            reset_lifecycle_registry()


# ---------------------------------------------------------------------------
# M — Recovery idempotency: second pass adds 0 new records
# ---------------------------------------------------------------------------

class TestRecoveryIdempotency:
    def test_M_second_pass_adds_no_new_records(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
            LifecycleOwner,
        )
        reset_lifecycle_registry()
        try:
            ms_store, bm_store, tl_store = _make_stores(str(tmp_path))
            records = [
                _record("idem-resumable", "device_dispatch"),
                _record("idem-replay", "routing"),
                _record("idem-reissue", "gateway_ingress"),
            ]
            _save_snapshot(tl_store, records)

            from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator

            # First pass
            coord1 = RuntimeRestartRecoveryCoordinator(
                mesh_session_store=ms_store,
                body_mesh_store=bm_store,
                body_mesh_registry=FakeBodyMeshRegistry(),
                task_lifecycle_store=tl_store,
            )
            report1 = coord1.run_recovery()
            assert report1.inflight_tasks_dispatch_actions_taken == 3

            registry = get_lifecycle_registry()
            assert registry.is_pending("idem-resumable")
            assert registry.is_pending("idem-replay")
            assert registry.is_pending("idem-reissue")

            # Second pass — snapshot still on disk, records already in registry
            coord2 = RuntimeRestartRecoveryCoordinator(
                mesh_session_store=ms_store,
                body_mesh_store=bm_store,
                body_mesh_registry=FakeBodyMeshRegistry(),
                task_lifecycle_store=tl_store,
            )
            report2 = coord2.run_recovery()

            # No new records should have been added
            assert report2.inflight_tasks_dispatch_actions_taken == 0
            assert report2.inflight_tasks_already_pending_skipped == 3

            # Registry ownership must not have changed
            assert registry.get_record("idem-resumable").owner == LifecycleOwner.DEVICE_DISPATCH
            assert registry.get_record("idem-replay").owner == LifecycleOwner.ROUTING
            assert registry.get_record("idem-reissue").owner == LifecycleOwner.GATEWAY_INGRESS
        finally:
            reset_lifecycle_registry()


# ---------------------------------------------------------------------------
# N — RECOVERY_DUPLICATE_SAFETY_POLICY sentinel
# ---------------------------------------------------------------------------

class TestRecoveryDuplicateSafetyPolicy:
    def test_N_importable_and_non_empty(self):
        from core.runtime_restart_recovery import RECOVERY_DUPLICATE_SAFETY_POLICY
        assert isinstance(RECOVERY_DUPLICATE_SAFETY_POLICY, str)
        assert RECOVERY_DUPLICATE_SAFETY_POLICY


# ---------------------------------------------------------------------------
# O — RECOVERY_IDEMPOTENCY_POLICY sentinel
# ---------------------------------------------------------------------------

class TestRecoveryIdempotencyPolicy:
    def test_O_importable_and_non_empty(self):
        from core.runtime_restart_recovery import RECOVERY_IDEMPOTENCY_POLICY
        assert isinstance(RECOVERY_IDEMPOTENCY_POLICY, str)
        assert RECOVERY_IDEMPOTENCY_POLICY


# ---------------------------------------------------------------------------
# P — Mixed scenario: duplicate in snapshot + already-pending + terminal
# ---------------------------------------------------------------------------

class TestMixedDuplicateSafetyScenario:
    def test_P_mixed_scenario_all_guards_work_together(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
            LifecycleOwner,
            PendingEnvelopeRecord,
        )
        reset_lifecycle_registry()
        try:
            ms_store, bm_store, tl_store = _make_stores(str(tmp_path))
            records = [
                _record("mix-dup", "device_dispatch"),      # first occurrence
                _record("mix-dup", "routing"),               # intra-snapshot duplicate
                _record("mix-live", "device_dispatch"),      # already pending in registry
                _record("mix-terminal", "result_completion"),  # TERMINAL_ON_INTERRUPT
                _record("mix-fresh", "routing"),              # fresh, should be added
            ]
            _save_snapshot(tl_store, records)

            # Pre-populate registry with mix-live
            registry = get_lifecycle_registry()
            registry._pending["mix-live"] = PendingEnvelopeRecord(
                task_id="mix-live",
                trace_id="tr",
                target_device_id="",
                tool_name="t",
                owner=LifecycleOwner.DEVICE_DISPATCH,
                timeout=30.0,
                registered_at=time.time(),
                future=None,
                metadata={"live": True},
            )

            from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
            coord = RuntimeRestartRecoveryCoordinator(
                mesh_session_store=ms_store,
                body_mesh_store=bm_store,
                body_mesh_registry=FakeBodyMeshRegistry(),
                task_lifecycle_store=tl_store,
            )
            report = coord.run_recovery()

            # mix-dup → deduplicated to 1 RESUMABLE, dispatched
            # mix-live → already pending, skipped
            # mix-terminal → TERMINAL, not dispatched
            # mix-fresh → dispatched
            # Expected: 2 dispatch actions (mix-dup + mix-fresh)
            assert report.inflight_tasks_dispatch_actions_taken == 2
            assert report.inflight_tasks_terminal == 1
            assert report.inflight_tasks_already_pending_skipped == 1

            # Registry checks
            assert registry.is_pending("mix-dup")
            assert registry.get_record("mix-dup").owner == LifecycleOwner.DEVICE_DISPATCH
            assert registry.is_pending("mix-fresh")
            assert not registry.is_pending("mix-terminal")
            # mix-live ownership must not have changed
            assert registry.get_record("mix-live").metadata.get("live") is True
        finally:
            reset_lifecycle_registry()


# ---------------------------------------------------------------------------
# Q — Duplicate task_id in snapshot: first owner wins
# ---------------------------------------------------------------------------

class TestDuplicateFirstOwnerWins:
    def test_Q_first_owner_wins_not_second(self, tmp_path):
        from core.task_lifecycle_persistence import (
            TaskLifecyclePersistenceStore,
            InFlightTaskDisposition,
            restore_inflight_tasks_from_snapshot,
            save_task_lifecycle_snapshot,
        )
        store = TaskLifecyclePersistenceStore(
            store_path=str(tmp_path / "tl.json")
        )
        # First: gateway_ingress (REISSUABLE), second: result_completion (TERMINAL)
        records = [
            _record("q-task", "gateway_ingress"),
            _record("q-task", "result_completion"),
        ]
        save_task_lifecycle_snapshot(records, store=store)
        restored = restore_inflight_tasks_from_snapshot(store=store)
        assert len(restored) == 1
        assert restored[0].disposition == InFlightTaskDisposition.REISSUABLE, (
            "First occurrence (gateway_ingress → REISSUABLE) must win over "
            "second occurrence (result_completion → TERMINAL_ON_INTERRUPT)"
        )


# ---------------------------------------------------------------------------
# R — Already-pending skip count accumulates correctly
# ---------------------------------------------------------------------------

class TestAlreadyPendingSkipAccumulation:
    def test_R_multiple_already_pending_all_counted(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
            LifecycleOwner,
            PendingEnvelopeRecord,
        )
        reset_lifecycle_registry()
        try:
            ms_store, bm_store, tl_store = _make_stores(str(tmp_path))
            _save_snapshot(tl_store, [
                _record("r-task-1", "device_dispatch"),
                _record("r-task-2", "routing"),
                _record("r-task-3", "gateway_ingress"),
                _record("r-task-new", "routing"),
            ])

            registry = get_lifecycle_registry()
            for tid in ("r-task-1", "r-task-2", "r-task-3"):
                registry._pending[tid] = PendingEnvelopeRecord(
                    task_id=tid,
                    trace_id=f"tr_{tid}",
                    target_device_id="",
                    tool_name="t",
                    owner=LifecycleOwner.DEVICE_DISPATCH,
                    timeout=30.0,
                    registered_at=time.time(),
                    future=None,
                    metadata={},
                )

            from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
            coord = RuntimeRestartRecoveryCoordinator(
                mesh_session_store=ms_store,
                body_mesh_store=bm_store,
                body_mesh_registry=FakeBodyMeshRegistry(),
                task_lifecycle_store=tl_store,
            )
            report = coord.run_recovery()

            assert report.inflight_tasks_already_pending_skipped == 3
            assert report.inflight_tasks_dispatch_actions_taken == 1
        finally:
            reset_lifecycle_registry()


# ---------------------------------------------------------------------------
# S — RECOVERY_DUPLICATE_SAFETY_POLICY mentions all three protection layers
# ---------------------------------------------------------------------------

class TestDuplicateSafetyPolicyContents:
    def test_S_mentions_terminal_on_interrupt(self):
        from core.runtime_restart_recovery import RECOVERY_DUPLICATE_SAFETY_POLICY
        assert "TERMINAL_ON_INTERRUPT" in RECOVERY_DUPLICATE_SAFETY_POLICY

    def test_S_mentions_already_pending(self):
        from core.runtime_restart_recovery import RECOVERY_DUPLICATE_SAFETY_POLICY
        lower = RECOVERY_DUPLICATE_SAFETY_POLICY.lower()
        assert "already" in lower or "pending" in lower

    def test_S_mentions_intra_snapshot(self):
        from core.runtime_restart_recovery import RECOVERY_DUPLICATE_SAFETY_POLICY
        lower = RECOVERY_DUPLICATE_SAFETY_POLICY.lower()
        assert "intra-snapshot" in lower or "snapshot" in lower


# ---------------------------------------------------------------------------
# T — RECOVERY_IDEMPOTENCY_POLICY mentions idempotency
# ---------------------------------------------------------------------------

class TestIdempotencyPolicyContents:
    def test_T_mentions_idempotent(self):
        from core.runtime_restart_recovery import RECOVERY_IDEMPOTENCY_POLICY
        lower = RECOVERY_IDEMPOTENCY_POLICY.lower()
        assert "idempotent" in lower

    def test_T_mentions_duplicate_guard(self):
        from core.runtime_restart_recovery import RECOVERY_IDEMPOTENCY_POLICY
        lower = RECOVERY_IDEMPOTENCY_POLICY.lower()
        assert "duplicate" in lower or "guard" in lower
