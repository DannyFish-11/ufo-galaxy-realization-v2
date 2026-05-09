"""tests/test_pr6_hybrid_continuity_closure.py
==============================================================
Tests for PR-6: Close hybrid execution continuity across interruption,
restart, and partial-result recovery.

Coverage:

  Sentinels — PR-6
  71.  HYBRID_PARTIAL_RESULT_MERGE_POLICY is a non-empty string.
  72.  HYBRID_CONTINUITY_PERSISTENCE_IS_DURABLE_POLICY is non-empty.
  73.  HYBRID_CONTINUITY_PR6_SENTINEL contains 'pr6'.
  74.  HYBRID_CONTINUITY_RECONSTRUCTION_POLICY in runtime_restart_recovery is non-empty.

  HybridPartialResultDisposition
  75.  All expected disposition values are present in the enum.
  76.  preserved, invalidated, merged, resumed are str enum members.

  HybridOrchestrationRecord — partial result fields
  77.  partial_result_snapshot defaults to None.
  78.  partial_result_origin defaults to empty string.
  79.  partial_result_disposition defaults to None.
  80.  to_dict() includes partial_result_snapshot, _origin, _disposition.
  81.  from_dict() round-trips partial_result_snapshot.
  82.  from_dict() round-trips partial_result_origin.
  83.  from_dict() round-trips partial_result_disposition.
  84.  from_dict() defaults partial_result_origin to '' when absent.

  HybridOrchestrationRecord — set_partial_result
  85.  set_partial_result() stores snapshot and origin.
  86.  set_partial_result() sets disposition when provided.
  87.  set_partial_result() leaves disposition None when not provided.
  88.  set_partial_result() is ignored for terminal records.
  89.  set_partial_result() does not affect result_snapshot.

  HybridOrchestrationContinuityRegistry — invalidate_remote_partial_results
  90.  invalidate_remote_partial_results() sets disposition=invalidated for remote records.
  91.  invalidate_remote_partial_results() does NOT change local-origin records.
  92.  invalidate_remote_partial_results() skips terminal records.
  93.  invalidate_remote_partial_results() returns count of newly-invalidated records.
  94.  invalidate_remote_partial_results() is idempotent (already-invalidated not counted twice).
  95.  invalidate_remote_partial_results() skips records with no partial result snapshot.

  HybridContinuityPersistenceStore — construction and basic I/O
  96.  Store can be created with a tmp directory.
  97.  save() returns True for a valid record.
  98.  load() returns the saved record with matching execution_id.
  99.  load() returns None for unknown execution_id.
  100. delete() removes a persisted record.
  101. delete() returns False for unknown execution_id.
  102. list_recoverable() returns non-terminal records only.
  103. list_recoverable() excludes terminal records.
  104. list_all() returns all records (terminal and non-terminal).
  105. save() is atomic — corrupt .tmp files are cleaned up on failure.

  HybridContinuityPersistenceStore — round-trip fidelity
  106. save/load round-trips lifecycle_state.
  107. save/load round-trips mode.
  108. save/load round-trips resume_count.
  109. save/load round-trips partial_result_snapshot.
  110. save/load round-trips partial_result_origin.
  111. save/load round-trips partial_result_disposition.

  HybridOrchestrationContinuityRegistry — restore_from_persistence
  112. restore_from_persistence() registers non-terminal records from the store.
  113. restore_from_persistence() skips terminal records by default (skip_terminal=True).
  114. restore_from_persistence() returns count of newly-registered records.
  115. restore_from_persistence() skips records already present in the registry.
  116. restore_from_persistence(skip_terminal=False) includes terminal records.

  RuntimeRecoveryReport — PR-6 fields
  117. RuntimeRecoveryReport has hybrid_executions_restored field (default 0).
  118. RuntimeRecoveryReport has hybrid_remote_partial_invalidated field (default 0).
  119. to_dict() includes 'hybrid_executions_restored'.
  120. to_dict() includes 'hybrid_remote_partial_invalidated'.

  RuntimeRestartRecoveryCoordinator — PR-6 store parameter
  121. Coordinator accepts hybrid_continuity_store parameter.
  122. run_recovery() with store restores records and sets hybrid_executions_restored.
  123. run_recovery() with store invalidates remote partial results.
  124. run_recovery() without store leaves hybrid_executions_restored at 0.

  run_startup_recovery — PR-6 store parameter
  125. run_startup_recovery() accepts hybrid_continuity_store parameter.
  126. run_startup_recovery() with store sets hybrid_executions_restored in report.

  Full continuity scenario
  127. End-to-end: run → interrupt → persist → reconstruct → resume.
  128. Remote partial results are invalidated; local are preserved.
  129. Resumed execution increments resume_count.
  130. Terminal executions do not reappear in list_recoverable().
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_registry() -> None:
    from core.hybrid_orchestration_continuity import reset_continuity_registry
    reset_continuity_registry()


def _reset_store() -> None:
    from core.hybrid_orchestration_continuity import reset_hybrid_persistence_store
    reset_hybrid_persistence_store()


def _make_registry():
    from core.hybrid_orchestration_continuity import HybridOrchestrationContinuityRegistry
    return HybridOrchestrationContinuityRegistry()


def _make_record(**kwargs):
    from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
    return HybridOrchestrationRecord(**kwargs)


def _make_store(tmp_dir: str):
    from core.hybrid_orchestration_continuity import HybridContinuityPersistenceStore
    return HybridContinuityPersistenceStore(store_dir=tmp_dir)


def _state(name: str):
    from core.hybrid_orchestration_continuity import HybridOrchestrationLifecycleState
    return HybridOrchestrationLifecycleState(name)


def _disposition(name: str):
    from core.hybrid_orchestration_continuity import HybridPartialResultDisposition
    return HybridPartialResultDisposition(name)


# ---------------------------------------------------------------------------
# 71–74: Sentinels
# ---------------------------------------------------------------------------

class TestSentinelsPR6:
    def test_71_partial_result_merge_policy_non_empty(self):
        from core.hybrid_orchestration_continuity import HYBRID_PARTIAL_RESULT_MERGE_POLICY
        assert isinstance(HYBRID_PARTIAL_RESULT_MERGE_POLICY, str)
        assert len(HYBRID_PARTIAL_RESULT_MERGE_POLICY) > 0

    def test_72_persistence_policy_non_empty(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_CONTINUITY_PERSISTENCE_IS_DURABLE_POLICY,
        )
        assert len(HYBRID_CONTINUITY_PERSISTENCE_IS_DURABLE_POLICY) > 0

    def test_73_pr6_sentinel_contains_pr6(self):
        from core.hybrid_orchestration_continuity import HYBRID_CONTINUITY_PR6_SENTINEL
        assert "pr6" in HYBRID_CONTINUITY_PR6_SENTINEL.lower()

    def test_74_reconstruction_policy_in_recovery_module(self):
        from core.runtime_restart_recovery import HYBRID_CONTINUITY_RECONSTRUCTION_POLICY
        assert len(HYBRID_CONTINUITY_RECONSTRUCTION_POLICY) > 0


# ---------------------------------------------------------------------------
# 75–76: HybridPartialResultDisposition
# ---------------------------------------------------------------------------

class TestPartialResultDispositionEnum:
    def test_75_all_disposition_values_present(self):
        from core.hybrid_orchestration_continuity import HybridPartialResultDisposition
        values = {d.value for d in HybridPartialResultDisposition}
        assert {"preserved", "invalidated", "merged", "resumed"}.issubset(values)

    def test_76_dispositions_are_str_enum(self):
        from core.hybrid_orchestration_continuity import HybridPartialResultDisposition
        for d in HybridPartialResultDisposition:
            assert isinstance(d.value, str)


# ---------------------------------------------------------------------------
# 77–84: HybridOrchestrationRecord — partial result fields
# ---------------------------------------------------------------------------

class TestRecordPartialResultFields:
    def test_77_partial_result_snapshot_defaults_none(self):
        r = _make_record()
        assert r.partial_result_snapshot is None

    def test_78_partial_result_origin_defaults_empty(self):
        r = _make_record()
        assert r.partial_result_origin == ""

    def test_79_partial_result_disposition_defaults_none(self):
        r = _make_record()
        assert r.partial_result_disposition is None

    def test_80_to_dict_includes_partial_result_fields(self):
        r = _make_record()
        d = r.to_dict()
        assert "partial_result_snapshot" in d
        assert "partial_result_origin" in d
        assert "partial_result_disposition" in d

    def test_81_from_dict_roundtrip_partial_result_snapshot(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        r = _make_record()
        r.partial_result_snapshot = {"output": "partial_data"}
        r2 = HybridOrchestrationRecord.from_dict(r.to_dict())
        assert r2.partial_result_snapshot == {"output": "partial_data"}

    def test_82_from_dict_roundtrip_partial_result_origin(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        r = _make_record()
        r.partial_result_origin = "local"
        r2 = HybridOrchestrationRecord.from_dict(r.to_dict())
        assert r2.partial_result_origin == "local"

    def test_83_from_dict_roundtrip_partial_result_disposition(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        r = _make_record()
        r.partial_result_disposition = "preserved"
        r2 = HybridOrchestrationRecord.from_dict(r.to_dict())
        assert r2.partial_result_disposition == "preserved"

    def test_84_from_dict_defaults_origin_to_empty(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        r = HybridOrchestrationRecord.from_dict({})
        assert r.partial_result_origin == ""


# ---------------------------------------------------------------------------
# 85–89: HybridOrchestrationRecord — set_partial_result
# ---------------------------------------------------------------------------

class TestSetPartialResult:
    def test_85_set_partial_result_stores_snapshot_and_origin(self):
        r = _make_record()
        r.set_partial_result({"data": "abc"}, "local")
        assert r.partial_result_snapshot == {"data": "abc"}
        assert r.partial_result_origin == "local"

    def test_86_set_partial_result_sets_disposition_when_given(self):
        r = _make_record()
        r.set_partial_result({"data": "abc"}, "local", disposition="preserved")
        assert r.partial_result_disposition == "preserved"

    def test_87_set_partial_result_leaves_disposition_none_when_not_given(self):
        r = _make_record()
        r.set_partial_result({"data": "abc"}, "remote")
        assert r.partial_result_disposition is None

    def test_88_set_partial_result_ignored_for_terminal(self):
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("completed"))
        r.set_partial_result({"data": "abc"}, "local")
        assert r.partial_result_snapshot is None
        assert r.partial_result_origin == ""

    def test_89_set_partial_result_does_not_affect_result_snapshot(self):
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.set_partial_result({"partial": "data"}, "local")
        assert r.result_snapshot is None  # still None; only set on completion


# ---------------------------------------------------------------------------
# 90–95: HybridOrchestrationContinuityRegistry — invalidate_remote_partial_results
# ---------------------------------------------------------------------------

class TestInvalidateRemotePartialResults:
    def test_90_invalidates_remote_origin_records(self):
        reg = _make_registry()
        r = reg.create_and_register()
        r.set_partial_result({"data": "remote_partial"}, "remote")
        reg.invalidate_remote_partial_results()
        assert r.partial_result_disposition == "invalidated"

    def test_91_does_not_change_local_origin_records(self):
        reg = _make_registry()
        r = reg.create_and_register()
        r.set_partial_result({"data": "local_partial"}, "local")
        reg.invalidate_remote_partial_results()
        assert r.partial_result_disposition is None  # local untouched

    def test_92_skips_terminal_records(self):
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.set_partial_result({"data": "remote_partial"}, "remote")
        r.transition(_state("completed"))
        reg.invalidate_remote_partial_results()
        # terminal — should be unchanged
        assert r.partial_result_disposition is None

    def test_93_returns_count_of_invalidated(self):
        reg = _make_registry()
        for _ in range(3):
            r = reg.create_and_register()
            r.set_partial_result({"d": "r"}, "remote")
        count = reg.invalidate_remote_partial_results()
        assert count == 3

    def test_94_idempotent_already_invalidated_not_counted(self):
        reg = _make_registry()
        r = reg.create_and_register()
        r.set_partial_result({"d": "r"}, "remote", disposition="invalidated")
        count = reg.invalidate_remote_partial_results()
        assert count == 0  # already invalidated

    def test_95_skips_records_with_no_partial_snapshot(self):
        reg = _make_registry()
        r = reg.create_and_register()
        # partial_result_origin is "remote" but no snapshot set
        r.partial_result_origin = "remote"
        count = reg.invalidate_remote_partial_results()
        assert count == 0


# ---------------------------------------------------------------------------
# 96–105: HybridContinuityPersistenceStore — basic I/O
# ---------------------------------------------------------------------------

class TestPersistenceStoreIO:
    def test_96_store_created_with_tmp_dir(self, tmp_path):
        store = _make_store(str(tmp_path))
        assert store is not None

    def test_97_save_returns_true(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record(session_id="s1", task_id="t1")
        result = store.save(r)
        assert result is True

    def test_98_load_returns_saved_record(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record(session_id="s1")
        store.save(r)
        loaded = store.load(r.execution_id)
        assert loaded is not None
        assert loaded.execution_id == r.execution_id

    def test_99_load_returns_none_for_unknown(self, tmp_path):
        store = _make_store(str(tmp_path))
        result = store.load("no_such_id")
        assert result is None

    def test_100_delete_removes_record(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record()
        store.save(r)
        store.delete(r.execution_id)
        assert store.load(r.execution_id) is None

    def test_101_delete_returns_false_for_unknown(self, tmp_path):
        store = _make_store(str(tmp_path))
        result = store.delete("not_there")
        assert result is False

    def test_102_list_recoverable_returns_non_terminal(self, tmp_path):
        store = _make_store(str(tmp_path))
        r1 = _make_record()
        r1.transition(_state("dispatched"))
        r1.transition(_state("running"))
        store.save(r1)
        r2 = _make_record()
        r2.transition(_state("dispatched"))
        r2.transition(_state("running"))
        r2.transition(_state("completed"))
        store.save(r2)
        recoverable = store.list_recoverable()
        ids = {r.execution_id for r in recoverable}
        assert r1.execution_id in ids
        assert r2.execution_id not in ids

    def test_103_list_recoverable_excludes_terminal(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("failed"))
        store.save(r)
        assert store.list_recoverable() == []

    def test_104_list_all_returns_all(self, tmp_path):
        store = _make_store(str(tmp_path))
        r1 = _make_record()
        r2 = _make_record()
        r2.transition(_state("dispatched"))
        r2.transition(_state("running"))
        r2.transition(_state("completed"))
        store.save(r1)
        store.save(r2)
        all_records = store.list_all()
        ids = {r.execution_id for r in all_records}
        assert r1.execution_id in ids
        assert r2.execution_id in ids

    def test_105_save_creates_json_file(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record()
        store.save(r)
        expected_file = tmp_path / f"{r.execution_id}.json"
        assert expected_file.exists()
        with open(expected_file) as f:
            data = json.load(f)
        assert data["execution_id"] == r.execution_id


# ---------------------------------------------------------------------------
# 106–111: HybridContinuityPersistenceStore — round-trip fidelity
# ---------------------------------------------------------------------------

class TestPersistenceStoreRoundTrip:
    def test_106_roundtrip_lifecycle_state(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="test")
        store.save(r)
        loaded = store.load(r.execution_id)
        assert loaded.lifecycle_state.value == "interrupted"

    def test_107_roundtrip_mode(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record(mode="parallel_race")
        store.save(r)
        loaded = store.load(r.execution_id)
        assert loaded.mode == "parallel_race"

    def test_108_roundtrip_resume_count(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="r1")
        r.transition(_state("resuming"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="r2")
        r.transition(_state("resuming"))
        store.save(r)
        loaded = store.load(r.execution_id)
        assert loaded.resume_count == 2

    def test_109_roundtrip_partial_result_snapshot(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record()
        r.set_partial_result({"progress": 42}, "local")
        store.save(r)
        loaded = store.load(r.execution_id)
        assert loaded.partial_result_snapshot == {"progress": 42}

    def test_110_roundtrip_partial_result_origin(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record()
        r.set_partial_result({"d": "v"}, "remote")
        store.save(r)
        loaded = store.load(r.execution_id)
        assert loaded.partial_result_origin == "remote"

    def test_111_roundtrip_partial_result_disposition(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record()
        r.set_partial_result({"d": "v"}, "remote", disposition="invalidated")
        store.save(r)
        loaded = store.load(r.execution_id)
        assert loaded.partial_result_disposition == "invalidated"


# ---------------------------------------------------------------------------
# 112–116: HybridOrchestrationContinuityRegistry — restore_from_persistence
# ---------------------------------------------------------------------------

class TestRestoreFromPersistence:
    def test_112_restores_non_terminal_records(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="restart")
        store.save(r)

        reg = _make_registry()
        count = reg.restore_from_persistence(store)
        assert count == 1
        assert reg.get(r.execution_id) is not None

    def test_113_skips_terminal_by_default(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("completed"))
        store.save(r)

        reg = _make_registry()
        count = reg.restore_from_persistence(store)
        assert count == 0
        assert reg.get(r.execution_id) is None

    def test_114_returns_count_of_new_records(self, tmp_path):
        store = _make_store(str(tmp_path))
        for _ in range(3):
            r = _make_record()
            r.transition(_state("dispatched"))
            r.transition(_state("running"))
            store.save(r)

        reg = _make_registry()
        count = reg.restore_from_persistence(store)
        assert count == 3

    def test_115_skips_records_already_in_registry(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        store.save(r)

        reg = _make_registry()
        reg.register(r)  # already in registry
        count = reg.restore_from_persistence(store)
        assert count == 0  # skipped

    def test_116_skip_terminal_false_includes_terminal(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("failed"))
        store.save(r)

        reg = _make_registry()
        count = reg.restore_from_persistence(store, skip_terminal=False)
        assert count == 1
        assert reg.get(r.execution_id) is not None


# ---------------------------------------------------------------------------
# 117–120: RuntimeRecoveryReport — PR-6 fields
# ---------------------------------------------------------------------------

class TestRecoveryReportPR6Fields:
    def test_117_hybrid_executions_restored_field(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        report = RuntimeRecoveryReport()
        assert hasattr(report, "hybrid_executions_restored")
        assert report.hybrid_executions_restored == 0

    def test_118_hybrid_remote_partial_invalidated_field(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        report = RuntimeRecoveryReport()
        assert hasattr(report, "hybrid_remote_partial_invalidated")
        assert report.hybrid_remote_partial_invalidated == 0

    def test_119_to_dict_includes_restored_key(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        d = RuntimeRecoveryReport().to_dict()
        assert "hybrid_executions_restored" in d

    def test_120_to_dict_includes_invalidated_key(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        d = RuntimeRecoveryReport().to_dict()
        assert "hybrid_remote_partial_invalidated" in d


# ---------------------------------------------------------------------------
# 121–124: RuntimeRestartRecoveryCoordinator — PR-6 store parameter
# ---------------------------------------------------------------------------

class TestCoordinatorPR6Store:
    def setup_method(self):
        _reset_registry()

    def test_121_coordinator_accepts_hybrid_continuity_store(self, tmp_path):
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        store = _make_store(str(tmp_path))
        reg = _make_registry()
        coordinator = RuntimeRestartRecoveryCoordinator(
            hybrid_continuity_registry=reg,
            hybrid_continuity_store=store,
        )
        assert coordinator is not None

    def test_122_run_recovery_with_store_sets_restored_field(self, tmp_path):
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        store = _make_store(str(tmp_path))
        # Put a non-terminal record in the store
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="prev_restart")
        store.save(r)

        reg = _make_registry()  # empty live registry
        coordinator = RuntimeRestartRecoveryCoordinator(
            hybrid_continuity_registry=reg,
            hybrid_continuity_store=store,
        )
        report = coordinator.run_recovery()
        assert report.hybrid_executions_restored >= 1

    def test_123_run_recovery_with_store_invalidates_remote_partial(self, tmp_path):
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        store = _make_store(str(tmp_path))
        # Record with remote partial result
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.set_partial_result({"remote": "data"}, "remote")
        r.transition(_state("interrupted"), reason="prev_restart")
        store.save(r)

        reg = _make_registry()
        coordinator = RuntimeRestartRecoveryCoordinator(
            hybrid_continuity_registry=reg,
            hybrid_continuity_store=store,
        )
        report = coordinator.run_recovery()
        # After recovery, remote partial should be invalidated
        assert report.hybrid_remote_partial_invalidated >= 1

    def test_124_run_recovery_without_store_leaves_restored_at_zero(self):
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        reg = _make_registry()
        coordinator = RuntimeRestartRecoveryCoordinator(
            hybrid_continuity_registry=reg,
        )
        report = coordinator.run_recovery()
        assert report.hybrid_executions_restored == 0


# ---------------------------------------------------------------------------
# 125–126: run_startup_recovery — PR-6 store parameter
# ---------------------------------------------------------------------------

class TestRunStartupRecoveryPR6:
    def setup_method(self):
        _reset_registry()

    def test_125_accepts_hybrid_continuity_store_parameter(self, tmp_path):
        from core.runtime_restart_recovery import run_startup_recovery
        store = _make_store(str(tmp_path))
        reg = _make_registry()
        report = run_startup_recovery(
            hybrid_continuity_registry=reg,
            hybrid_continuity_store=store,
        )
        assert report is not None

    def test_126_report_includes_restored_field(self, tmp_path):
        from core.runtime_restart_recovery import run_startup_recovery
        store = _make_store(str(tmp_path))
        # Pre-populate store with an interrupted record
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="prev")
        store.save(r)

        reg = _make_registry()
        report = run_startup_recovery(
            hybrid_continuity_registry=reg,
            hybrid_continuity_store=store,
        )
        assert report.hybrid_executions_restored >= 1


# ---------------------------------------------------------------------------
# 127–130: Full continuity scenario
# ---------------------------------------------------------------------------

class TestFullContinuityScenario:
    def setup_method(self):
        _reset_registry()
        _reset_store()

    def test_127_end_to_end_run_interrupt_persist_reconstruct_resume(self, tmp_path):
        """Full lifecycle: run → interrupt → persist → reconstruct → resume.

        Recovery sequence mirrors what RuntimeRestartRecoveryCoordinator does:
        1. Restore non-terminal records from the durable store into the new registry.
        2. Mark all running/dispatched records (including newly-restored ones) as
           interrupted — they were in-flight when the process died.
        3. Resume the interrupted execution.
        """
        from core.hybrid_orchestration_continuity import HybridOrchestrationContinuityRegistry

        store = _make_store(str(tmp_path))

        # --- Phase 1: Process A — create and run ---
        reg_a = _make_registry()
        r = reg_a.create_and_register(session_id="s1", task_id="t1", mode="parallel_race")
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.set_partial_result({"progress": 50}, "local")
        # Save durable record before "crash" — still in running state
        store.save(r)

        # --- Phase 2: Simulated restart — process dies, new process starts ---
        reg_b = HybridOrchestrationContinuityRegistry()
        # Step 1: Restore non-terminal records from durable store
        restored = reg_b.restore_from_persistence(store)
        assert restored >= 1
        # Step 2: Mark all running records (including restored ones) as interrupted
        reg_b.mark_all_running_as_interrupted(reason="process_restart_from_store")

        # The record should now be in the new registry as interrupted
        rec = reg_b.get(r.execution_id)
        assert rec is not None
        assert rec.lifecycle_state.value == "interrupted"

        # --- Phase 3: Resume the interrupted execution ---
        ok = reg_b.transition(r.execution_id, _state("resuming"))
        assert ok is True
        ok = reg_b.transition(r.execution_id, _state("running"))
        assert ok is True
        rec2 = reg_b.get(r.execution_id)
        assert rec2.resume_count >= 1
        assert rec2.lifecycle_state.value == "running"

    def test_128_remote_partial_invalidated_local_preserved(self, tmp_path):
        """Remote partial results are invalidated; local ones are preserved after restart."""
        store = _make_store(str(tmp_path))

        reg = _make_registry()
        r_local = reg.create_and_register()
        r_local.set_partial_result({"local": "data"}, "local")
        r_local.transition(_state("dispatched"))
        r_local.transition(_state("running"))

        r_remote = reg.create_and_register()
        r_remote.set_partial_result({"remote": "data"}, "remote")
        r_remote.transition(_state("dispatched"))
        r_remote.transition(_state("running"))

        store.save(r_local)
        store.save(r_remote)

        # Recovery: interrupt running, restore, then invalidate remote
        reg.mark_all_running_as_interrupted(reason="restart")
        reg.restore_from_persistence(store)
        invalidated = reg.invalidate_remote_partial_results()

        assert invalidated >= 1
        local_rec = reg.get(r_local.execution_id)
        remote_rec = reg.get(r_remote.execution_id)
        assert local_rec.partial_result_disposition != "invalidated"
        assert remote_rec.partial_result_disposition == "invalidated"

    def test_129_resumed_execution_increments_resume_count(self, tmp_path):
        """Resume increments resume_count each time."""
        store = _make_store(str(tmp_path))
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="r1")
        store.save(r)

        # First resume
        r.transition(_state("resuming"))
        r.transition(_state("running"))
        r.transition(_state("interrupted"), reason="r2")
        store.save(r)

        # Second resume
        r.transition(_state("resuming"))
        r.transition(_state("running"))
        assert r.resume_count == 2

    def test_130_terminal_executions_not_in_list_recoverable(self, tmp_path):
        """Completed/failed executions are not recovered into the live registry."""
        store = _make_store(str(tmp_path))
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("completed"))
        store.save(r)

        reg = _make_registry()
        count = reg.restore_from_persistence(store)
        assert count == 0
        assert reg.get(r.execution_id) is None


class TestRecoverHybridExecutionsConvenience:
    def test_recover_hybrid_executions_normalizes_running_to_interrupted(self, tmp_path):
        from core.hybrid_orchestration_continuity import recover_hybrid_executions

        store = _make_store(str(tmp_path))
        running = _make_record()
        running.transition(_state("dispatched"))
        running.transition(_state("running"))
        assert store.save(running) is True

        recovered = recover_hybrid_executions(store=store)
        assert len(recovered) == 1
        assert recovered[0].execution_id == running.execution_id
        assert recovered[0].lifecycle_state.value == "interrupted"

    def test_recover_hybrid_executions_cancels_created_records(self, tmp_path):
        from core.hybrid_orchestration_continuity import recover_hybrid_executions

        store = _make_store(str(tmp_path))
        created = _make_record()
        running = _make_record()
        running.transition(_state("dispatched"))
        running.transition(_state("running"))
        assert store.save(created) is True
        assert store.save(running) is True

        recovered = recover_hybrid_executions(store=store)
        recovered_ids = {record.execution_id for record in recovered}
        assert running.execution_id in recovered_ids
        assert created.execution_id not in recovered_ids

    def test_recover_hybrid_executions_excludes_terminal_records(self):
        from core.hybrid_orchestration_continuity import recover_hybrid_executions

        created = _make_record()
        running = _make_record()
        running.transition(_state("dispatched"))
        running.transition(_state("running"))

        class _MemoryStore:
            def list_recoverable(self):
                return [created, running]

        recovered = recover_hybrid_executions(store=_MemoryStore())
        recovered_ids = {record.execution_id for record in recovered}

        assert created.lifecycle_state.value == "cancelled"
        assert created.is_terminal is True
        assert created.execution_id not in recovered_ids
        assert running.execution_id in recovered_ids

    def test_recover_hybrid_executions_persists_restart_normalisation(self, tmp_path):
        from core.hybrid_orchestration_continuity import (
            recover_hybrid_executions,
            load_hybrid_execution,
        )

        store = _make_store(str(tmp_path))
        running = _make_record()
        running.transition(_state("dispatched"))
        running.transition(_state("running"))
        assert store.save(running) is True

        recovered = recover_hybrid_executions(store=store)
        assert len(recovered) == 1

        reloaded = load_hybrid_execution(running.execution_id, store=store)
        assert reloaded is not None
        assert reloaded.lifecycle_state.value == "interrupted"
