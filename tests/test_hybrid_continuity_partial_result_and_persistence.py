#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_hybrid_continuity_partial_result_and_persistence.py
================================================================
Tests for hybrid execution continuity partial-result classification,
file-backed durable persistence, and end-to-end restart/recovery flow.

This test suite covers the gap-closure work for PR-59 v2 — specifically:
- Partial result preservation, invalidation, and merge semantics
- Durable continuity snapshot store (HybridContinuityPersistenceStore)
- restore_hybrid_continuity_from_snapshot() recovery path
- End-to-end: save snapshot → simulate restart → restore → mark interrupted

Coverage
--------
  Sentinels
  1.  HYBRID_PARTIAL_RESULT_PRESERVATION_POLICY is a non-empty string.
  2.  HYBRID_PARTIAL_RESULT_INVALIDATION_POLICY is a non-empty string.
  3.  HYBRID_PARTIAL_RESULT_MERGE_SEMANTICS_POLICY is a non-empty string.
  4.  HYBRID_CONTINUITY_PERSISTENCE_IS_AUTHORITY is a non-empty string.
  5.  HYBRID_CONTINUITY_PERSISTENCE_GAP_CLOSURE_SENTINEL mentions 'pr59'.
  6.  HYBRID_CONTINUITY_RECOVERY_RESTORES_RECORDS_POLICY is a non-empty string.
  7.  HYBRID_CONTINUITY_DURABLE_RECOVERY_POLICY in runtime_restart_recovery
      is a non-empty string.

  HybridPartialResultStatus enum
  8.  PRESERVED, INVALIDATED, MERGEABLE values are present.
  9.  PRESERVED.can_be_reused is True.
  10. MERGEABLE.can_be_reused is True.
  11. INVALIDATED.can_be_reused is False.

  HybridPartialResult dataclass
  12. Default construction produces sensible defaults.
  13. to_dict() is JSON-serialisable.
  14. to_dict() contains all required fields.
  15. from_dict() round-trip preserves source.
  16. from_dict() round-trip preserves executor_level.
  17. from_dict() round-trip preserves status.
  18. from_dict() round-trip preserves payload.
  19. from_dict() with unknown status defaults to PRESERVED.
  20. from_dict() raises ValueError for non-dict input.

  HybridOrchestrationRecord — partial result integration
  21. Default partial_results is an empty list.
  22. record_partial_result() appends to partial_results.
  23. record_partial_result() returns the created HybridPartialResult.
  24. has_recoverable_partial_results is False when list is empty.
  25. has_recoverable_partial_results is True after adding PRESERVED result.
  26. has_recoverable_partial_results is True after adding MERGEABLE result.
  27. has_recoverable_partial_results is False when only INVALIDATED result.
  28. list_preserved_partial_results() returns only PRESERVED results.
  29. list_mergeable_partial_results() returns only MERGEABLE results.
  30. to_dict() includes 'partial_results' key.
  31. from_dict() round-trip restores partial_results.
  32. from_dict() with empty partial_results list yields empty list.
  33. from_dict() silently skips corrupt partial_results entries.

  HybridOrchestrationContinuityRegistry — partial result queries
  34. list_interrupted_with_partial_results() returns empty when no interrupted.
  35. list_interrupted_with_partial_results() excludes interrupted with no
      recoverable partials.
  36. list_interrupted_with_partial_results() includes interrupted with
      PRESERVED partial result.
  37. list_interrupted_with_partial_results() includes interrupted with
      MERGEABLE partial result.
  38. list_interrupted_with_partial_results() excludes terminal records.

  HybridContinuitySnapshot
  39. Default construction produces non-empty snapshot_id starting with 'hcs_'.
  40. to_dict() contains all required fields.
  41. from_dict() round-trip preserves snapshot_id.
  42. from_dict() round-trip preserves records list.

  HybridContinuityPersistenceStore
  43. save() creates the backing file.
  44. load() returns None when file does not exist.
  45. load() returns the saved snapshot.
  46. save() then load() round-trip preserves snapshot_id.
  47. save() then load() round-trip preserves all record dicts.
  48. delete() removes the backing file.
  49. delete() returns False when file does not exist.
  50. save() is atomic (no partial-write corruption visible).
  51. store_path property returns the configured path.

  save_hybrid_continuity_snapshot / load_hybrid_continuity_snapshot
  52. save_hybrid_continuity_snapshot() accepts list of records with to_dict().
  53. save_hybrid_continuity_snapshot() accepts plain dicts.
  54. load_hybrid_continuity_snapshot() returns None on empty store.
  55. load_hybrid_continuity_snapshot() returns snapshot after save.

  restore_hybrid_continuity_from_snapshot
  56. Returns 0 when no snapshot exists.
  57. Restores records into the registry.
  58. Returns the count of restored records.
  59. Silently skips corrupt record entries.
  60. Restores partial_results alongside lifecycle state.

  End-to-end restart/recovery
  61. Save snapshot → fresh registry → restore → mark interrupted.
  62. Interrupted count matches the number of non-terminal records saved.
  63. Partial results survive the snapshot/restore cycle.
  64. Terminal records are not transitioned by mark_all_running_as_interrupted.

  RuntimeRestartRecoveryCoordinator — durable hybrid recovery
  65. run_recovery() with hybrid_continuity_store restores records.
  66. run_recovery() sets hybrid_records_restored on report.
  67. run_recovery() marks restored running records as interrupted.
  68. hybrid_records_restored defaults to 0 on fresh RuntimeRecoveryReport.
  69. to_dict() includes 'hybrid_records_restored' key.

  run_startup_recovery — durable hybrid store parameter
  70. run_startup_recovery() accepts hybrid_continuity_store parameter.
  71. run_startup_recovery() with populated store sets hybrid_records_restored.

  HYBRID_CONTINUITY_DURABLE_RECOVERY_POLICY sentinel
  72. HYBRID_CONTINUITY_DURABLE_RECOVERY_POLICY is importable from
      core.runtime_restart_recovery.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path_str: str):
    from core.hybrid_continuity_persistence import HybridContinuityPersistenceStore
    path = os.path.join(tmp_path_str, "hc_snap.json")
    return HybridContinuityPersistenceStore(store_path=path)


def _make_registry():
    from core.hybrid_orchestration_continuity import HybridOrchestrationContinuityRegistry
    return HybridOrchestrationContinuityRegistry()


def _make_record(**kwargs):
    from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
    return HybridOrchestrationRecord(**kwargs)


def _state(name: str):
    from core.hybrid_orchestration_continuity import HybridOrchestrationLifecycleState
    return HybridOrchestrationLifecycleState(name)


def _status(name: str):
    from core.hybrid_orchestration_continuity import HybridPartialResultStatus
    return HybridPartialResultStatus(name)


# ---------------------------------------------------------------------------
# 1–7: Sentinels
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_01_preservation_policy_non_empty(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_PARTIAL_RESULT_PRESERVATION_POLICY,
        )
        assert isinstance(HYBRID_PARTIAL_RESULT_PRESERVATION_POLICY, str)
        assert len(HYBRID_PARTIAL_RESULT_PRESERVATION_POLICY) > 0

    def test_02_invalidation_policy_non_empty(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_PARTIAL_RESULT_INVALIDATION_POLICY,
        )
        assert len(HYBRID_PARTIAL_RESULT_INVALIDATION_POLICY) > 0

    def test_03_merge_semantics_policy_non_empty(self):
        from core.hybrid_orchestration_continuity import (
            HYBRID_PARTIAL_RESULT_MERGE_SEMANTICS_POLICY,
        )
        assert len(HYBRID_PARTIAL_RESULT_MERGE_SEMANTICS_POLICY) > 0

    def test_04_persistence_authority_non_empty(self):
        from core.hybrid_continuity_persistence import (
            HYBRID_CONTINUITY_PERSISTENCE_IS_AUTHORITY,
        )
        assert len(HYBRID_CONTINUITY_PERSISTENCE_IS_AUTHORITY) > 0

    def test_05_gap_closure_sentinel_mentions_pr59(self):
        from core.hybrid_continuity_persistence import (
            HYBRID_CONTINUITY_PERSISTENCE_GAP_CLOSURE_SENTINEL,
        )
        assert "pr59" in HYBRID_CONTINUITY_PERSISTENCE_GAP_CLOSURE_SENTINEL.lower()

    def test_06_recovery_restores_records_policy_non_empty(self):
        from core.hybrid_continuity_persistence import (
            HYBRID_CONTINUITY_RECOVERY_RESTORES_RECORDS_POLICY,
        )
        assert len(HYBRID_CONTINUITY_RECOVERY_RESTORES_RECORDS_POLICY) > 0

    def test_07_durable_recovery_policy_in_restart_recovery(self):
        from core.runtime_restart_recovery import (
            HYBRID_CONTINUITY_DURABLE_RECOVERY_POLICY,
        )
        assert isinstance(HYBRID_CONTINUITY_DURABLE_RECOVERY_POLICY, str)
        assert len(HYBRID_CONTINUITY_DURABLE_RECOVERY_POLICY) > 0


# ---------------------------------------------------------------------------
# 8–11: HybridPartialResultStatus
# ---------------------------------------------------------------------------

class TestPartialResultStatus:
    def test_08_all_values_present(self):
        from core.hybrid_orchestration_continuity import HybridPartialResultStatus
        values = {s.value for s in HybridPartialResultStatus}
        assert {"preserved", "invalidated", "mergeable"}.issubset(values)

    def test_09_preserved_can_be_reused(self):
        assert _status("preserved").can_be_reused is True

    def test_10_mergeable_can_be_reused(self):
        assert _status("mergeable").can_be_reused is True

    def test_11_invalidated_cannot_be_reused(self):
        assert _status("invalidated").can_be_reused is False


# ---------------------------------------------------------------------------
# 12–20: HybridPartialResult
# ---------------------------------------------------------------------------

class TestPartialResult:
    def test_12_default_construction(self):
        from core.hybrid_orchestration_continuity import HybridPartialResult
        pr = HybridPartialResult()
        assert pr.source == "local"
        assert pr.executor_level == "a2a"
        assert pr.status.value == "preserved"
        assert pr.payload is None

    def test_13_to_dict_json_serialisable(self):
        from core.hybrid_orchestration_continuity import HybridPartialResult
        pr = HybridPartialResult(payload={"key": "value"})
        assert isinstance(json.dumps(pr.to_dict()), str)

    def test_14_to_dict_required_fields(self):
        from core.hybrid_orchestration_continuity import HybridPartialResult
        d = HybridPartialResult().to_dict()
        for key in ("source", "executor_level", "status", "payload",
                    "captured_at", "reason"):
            assert key in d, f"missing key {key!r}"

    def test_15_from_dict_round_trip_source(self):
        from core.hybrid_orchestration_continuity import HybridPartialResult
        pr = HybridPartialResult(source="remote")
        pr2 = HybridPartialResult.from_dict(pr.to_dict())
        assert pr2.source == "remote"

    def test_16_from_dict_round_trip_executor_level(self):
        from core.hybrid_orchestration_continuity import HybridPartialResult
        pr = HybridPartialResult(executor_level="vlm")
        pr2 = HybridPartialResult.from_dict(pr.to_dict())
        assert pr2.executor_level == "vlm"

    def test_17_from_dict_round_trip_status(self):
        from core.hybrid_orchestration_continuity import HybridPartialResult
        pr = HybridPartialResult(status=_status("invalidated"))
        pr2 = HybridPartialResult.from_dict(pr.to_dict())
        assert pr2.status.value == "invalidated"

    def test_18_from_dict_round_trip_payload(self):
        from core.hybrid_orchestration_continuity import HybridPartialResult
        pr = HybridPartialResult(payload={"result": 42})
        pr2 = HybridPartialResult.from_dict(pr.to_dict())
        assert pr2.payload == {"result": 42}

    def test_19_from_dict_unknown_status_defaults_to_preserved(self):
        from core.hybrid_orchestration_continuity import HybridPartialResult
        pr = HybridPartialResult.from_dict({"status": "bogus"})
        assert pr.status.value == "preserved"

    def test_20_from_dict_raises_for_non_dict(self):
        from core.hybrid_orchestration_continuity import HybridPartialResult
        with pytest.raises(ValueError):
            HybridPartialResult.from_dict("not a dict")


# ---------------------------------------------------------------------------
# 21–33: HybridOrchestrationRecord — partial result integration
# ---------------------------------------------------------------------------

class TestRecordPartialResultIntegration:
    def test_21_default_partial_results_empty(self):
        r = _make_record()
        assert r.partial_results == []

    def test_22_record_partial_result_appends(self):
        r = _make_record()
        r.record_partial_result(
            status=_status("preserved"), payload={"x": 1}
        )
        assert len(r.partial_results) == 1

    def test_23_record_partial_result_returns_instance(self):
        from core.hybrid_orchestration_continuity import HybridPartialResult
        r = _make_record()
        pr = r.record_partial_result(status=_status("preserved"))
        assert isinstance(pr, HybridPartialResult)

    def test_24_no_recoverable_when_empty(self):
        r = _make_record()
        assert r.has_recoverable_partial_results is False

    def test_25_recoverable_after_preserved(self):
        r = _make_record()
        r.record_partial_result(status=_status("preserved"))
        assert r.has_recoverable_partial_results is True

    def test_26_recoverable_after_mergeable(self):
        r = _make_record()
        r.record_partial_result(status=_status("mergeable"))
        assert r.has_recoverable_partial_results is True

    def test_27_not_recoverable_after_invalidated_only(self):
        r = _make_record()
        r.record_partial_result(status=_status("invalidated"))
        assert r.has_recoverable_partial_results is False

    def test_28_list_preserved_returns_only_preserved(self):
        r = _make_record()
        r.record_partial_result(status=_status("preserved"), payload={"a": 1})
        r.record_partial_result(status=_status("invalidated"))
        preserved = r.list_preserved_partial_results()
        assert len(preserved) == 1
        assert preserved[0].payload == {"a": 1}

    def test_29_list_mergeable_returns_only_mergeable(self):
        r = _make_record()
        r.record_partial_result(status=_status("mergeable"), payload={"b": 2})
        r.record_partial_result(status=_status("preserved"))
        mergeable = r.list_mergeable_partial_results()
        assert len(mergeable) == 1
        assert mergeable[0].payload == {"b": 2}

    def test_30_to_dict_includes_partial_results(self):
        r = _make_record()
        r.record_partial_result(status=_status("preserved"), payload={"c": 3})
        d = r.to_dict()
        assert "partial_results" in d
        assert len(d["partial_results"]) == 1
        assert d["partial_results"][0]["status"] == "preserved"

    def test_31_from_dict_round_trip_partial_results(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        r = _make_record()
        r.record_partial_result(
            source="remote", executor_level="gui",
            status=_status("mergeable"), payload={"k": "v"},
        )
        r2 = HybridOrchestrationRecord.from_dict(r.to_dict())
        assert len(r2.partial_results) == 1
        assert r2.partial_results[0].source == "remote"
        assert r2.partial_results[0].executor_level == "gui"
        assert r2.partial_results[0].status.value == "mergeable"
        assert r2.partial_results[0].payload == {"k": "v"}

    def test_32_from_dict_empty_partial_results_list(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        r = HybridOrchestrationRecord.from_dict({"partial_results": []})
        assert r.partial_results == []

    def test_33_from_dict_skips_corrupt_partial_entries(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        d = _make_record().to_dict()
        d["partial_results"] = [
            {"source": "local", "executor_level": "a2a", "status": "preserved",
             "payload": None, "captured_at": 1.0, "reason": ""},
            "this is not a dict and should be skipped",
            None,
        ]
        r2 = HybridOrchestrationRecord.from_dict(d)
        # Only the first valid entry should be restored
        assert len(r2.partial_results) == 1


# ---------------------------------------------------------------------------
# 34–38: HybridOrchestrationContinuityRegistry — partial result queries
# ---------------------------------------------------------------------------

class TestRegistryPartialResultQueries:
    def test_34_list_interrupted_with_partials_empty_when_none_interrupted(self):
        reg = _make_registry()
        reg.create_and_register()
        assert reg.list_interrupted_with_partial_results() == []

    def test_35_interrupted_without_recoverable_partials_excluded(self):
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.record_partial_result(status=_status("invalidated"))
        r.transition(_state("interrupted"), reason="restart")
        result = reg.list_interrupted_with_partial_results()
        assert r not in result

    def test_36_interrupted_with_preserved_partial_included(self):
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.record_partial_result(status=_status("preserved"), payload={"d": 4})
        r.transition(_state("interrupted"), reason="restart")
        result = reg.list_interrupted_with_partial_results()
        assert r in result

    def test_37_interrupted_with_mergeable_partial_included(self):
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.record_partial_result(status=_status("mergeable"))
        r.transition(_state("interrupted"), reason="restart")
        result = reg.list_interrupted_with_partial_results()
        assert r in result

    def test_38_terminal_records_excluded_from_partial_query(self):
        reg = _make_registry()
        r = reg.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.record_partial_result(status=_status("preserved"))
        r.transition(_state("completed"))
        result = reg.list_interrupted_with_partial_results()
        assert r not in result


# ---------------------------------------------------------------------------
# 39–42: HybridContinuitySnapshot
# ---------------------------------------------------------------------------

class TestHybridContinuitySnapshot:
    def test_39_default_snapshot_id_starts_with_hcs(self):
        from core.hybrid_continuity_persistence import HybridContinuitySnapshot
        s = HybridContinuitySnapshot()
        assert s.snapshot_id.startswith("hcs_")

    def test_40_to_dict_required_fields(self):
        from core.hybrid_continuity_persistence import HybridContinuitySnapshot
        d = HybridContinuitySnapshot().to_dict()
        for key in ("snapshot_id", "created_at", "process_pid", "records"):
            assert key in d, f"missing key {key!r}"

    def test_41_from_dict_round_trip_snapshot_id(self):
        from core.hybrid_continuity_persistence import HybridContinuitySnapshot
        s = HybridContinuitySnapshot()
        s2 = HybridContinuitySnapshot.from_dict(s.to_dict())
        assert s2.snapshot_id == s.snapshot_id

    def test_42_from_dict_round_trip_records(self):
        from core.hybrid_continuity_persistence import HybridContinuitySnapshot
        s = HybridContinuitySnapshot(records=[{"key": "val"}])
        s2 = HybridContinuitySnapshot.from_dict(s.to_dict())
        assert s2.records == [{"key": "val"}]


# ---------------------------------------------------------------------------
# 43–51: HybridContinuityPersistenceStore
# ---------------------------------------------------------------------------

class TestPersistenceStore:
    def test_43_save_creates_file(self, tmp_path):
        from core.hybrid_continuity_persistence import HybridContinuitySnapshot
        store = _make_store(str(tmp_path))
        store.save(HybridContinuitySnapshot())
        assert os.path.exists(store.store_path)

    def test_44_load_returns_none_when_no_file(self, tmp_path):
        store = _make_store(str(tmp_path))
        assert store.load() is None

    def test_45_load_returns_saved_snapshot(self, tmp_path):
        from core.hybrid_continuity_persistence import HybridContinuitySnapshot
        store = _make_store(str(tmp_path))
        snap = HybridContinuitySnapshot()
        store.save(snap)
        loaded = store.load()
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id

    def test_46_save_load_round_trip_snapshot_id(self, tmp_path):
        from core.hybrid_continuity_persistence import HybridContinuitySnapshot
        store = _make_store(str(tmp_path))
        snap = HybridContinuitySnapshot()
        store.save(snap)
        loaded = store.load()
        assert loaded.snapshot_id == snap.snapshot_id

    def test_47_save_load_round_trip_records(self, tmp_path):
        from core.hybrid_continuity_persistence import HybridContinuitySnapshot
        store = _make_store(str(tmp_path))
        rec = _make_record(session_id="s1", task_id="t1")
        snap = HybridContinuitySnapshot(records=[rec.to_dict()])
        store.save(snap)
        loaded = store.load()
        assert len(loaded.records) == 1
        assert loaded.records[0]["session_id"] == "s1"

    def test_48_delete_removes_file(self, tmp_path):
        from core.hybrid_continuity_persistence import HybridContinuitySnapshot
        store = _make_store(str(tmp_path))
        store.save(HybridContinuitySnapshot())
        assert os.path.exists(store.store_path)
        result = store.delete()
        assert result is True
        assert not os.path.exists(store.store_path)

    def test_49_delete_returns_false_when_no_file(self, tmp_path):
        store = _make_store(str(tmp_path))
        assert store.delete() is False

    def test_50_save_atomic_no_corrupt_on_read(self, tmp_path):
        from core.hybrid_continuity_persistence import HybridContinuitySnapshot
        store = _make_store(str(tmp_path))
        # Write multiple times and check each read is valid
        for i in range(5):
            snap = HybridContinuitySnapshot(records=[{"idx": i}])
            store.save(snap)
            loaded = store.load()
            assert loaded is not None
            assert loaded.records[0]["idx"] == i

    def test_51_store_path_property(self, tmp_path):
        path = os.path.join(str(tmp_path), "my_store.json")
        from core.hybrid_continuity_persistence import HybridContinuityPersistenceStore
        store = HybridContinuityPersistenceStore(store_path=path)
        assert store.store_path == path


# ---------------------------------------------------------------------------
# 52–55: save_hybrid_continuity_snapshot / load_hybrid_continuity_snapshot
# ---------------------------------------------------------------------------

class TestConvenienceWrappers:
    def test_52_save_accepts_records_with_to_dict(self, tmp_path):
        from core.hybrid_continuity_persistence import save_hybrid_continuity_snapshot
        store = _make_store(str(tmp_path))
        r = _make_record(session_id="sess1")
        snap = save_hybrid_continuity_snapshot([r], store=store)
        assert len(snap.records) == 1
        assert snap.records[0]["session_id"] == "sess1"

    def test_53_save_accepts_plain_dicts(self, tmp_path):
        from core.hybrid_continuity_persistence import save_hybrid_continuity_snapshot
        store = _make_store(str(tmp_path))
        snap = save_hybrid_continuity_snapshot([{"key": "value"}], store=store)
        assert snap.records[0]["key"] == "value"

    def test_54_load_returns_none_on_empty_store(self, tmp_path):
        from core.hybrid_continuity_persistence import load_hybrid_continuity_snapshot
        store = _make_store(str(tmp_path))
        assert load_hybrid_continuity_snapshot(store=store) is None

    def test_55_load_returns_snapshot_after_save(self, tmp_path):
        from core.hybrid_continuity_persistence import (
            save_hybrid_continuity_snapshot,
            load_hybrid_continuity_snapshot,
        )
        store = _make_store(str(tmp_path))
        r = _make_record()
        save_hybrid_continuity_snapshot([r], store=store)
        loaded = load_hybrid_continuity_snapshot(store=store)
        assert loaded is not None
        assert len(loaded.records) == 1


# ---------------------------------------------------------------------------
# 56–60: restore_hybrid_continuity_from_snapshot
# ---------------------------------------------------------------------------

class TestRestoreFromSnapshot:
    def test_56_returns_zero_when_no_snapshot(self, tmp_path):
        from core.hybrid_continuity_persistence import restore_hybrid_continuity_from_snapshot
        store = _make_store(str(tmp_path))
        reg = _make_registry()
        count = restore_hybrid_continuity_from_snapshot(registry=reg, store=store)
        assert count == 0

    def test_57_restores_records_into_registry(self, tmp_path):
        from core.hybrid_continuity_persistence import (
            save_hybrid_continuity_snapshot,
            restore_hybrid_continuity_from_snapshot,
        )
        store = _make_store(str(tmp_path))
        r = _make_record(session_id="sess-restore", task_id="t-restore")
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        save_hybrid_continuity_snapshot([r], store=store)

        reg = _make_registry()
        restore_hybrid_continuity_from_snapshot(registry=reg, store=store)
        restored = reg.get(r.execution_id)
        assert restored is not None
        assert restored.session_id == "sess-restore"

    def test_58_returns_count_of_restored_records(self, tmp_path):
        from core.hybrid_continuity_persistence import (
            save_hybrid_continuity_snapshot,
            restore_hybrid_continuity_from_snapshot,
        )
        store = _make_store(str(tmp_path))
        records = [_make_record() for _ in range(3)]
        save_hybrid_continuity_snapshot(records, store=store)

        reg = _make_registry()
        count = restore_hybrid_continuity_from_snapshot(registry=reg, store=store)
        assert count == 3

    def test_59_silently_skips_corrupt_entries(self, tmp_path):
        from core.hybrid_continuity_persistence import (
            HybridContinuitySnapshot,
            restore_hybrid_continuity_from_snapshot,
        )
        store = _make_store(str(tmp_path))
        snap = HybridContinuitySnapshot(records=[
            _make_record().to_dict(),
            "not a dict",  # corrupt
            None,           # corrupt
        ])
        store.save(snap)

        reg = _make_registry()
        count = restore_hybrid_continuity_from_snapshot(registry=reg, store=store)
        assert count == 1

    def test_60_restores_partial_results_alongside_lifecycle(self, tmp_path):
        from core.hybrid_continuity_persistence import (
            save_hybrid_continuity_snapshot,
            restore_hybrid_continuity_from_snapshot,
        )
        store = _make_store(str(tmp_path))
        r = _make_record()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.record_partial_result(
            source="remote", executor_level="vlm",
            status=_status("preserved"), payload={"partial": "data"},
        )
        save_hybrid_continuity_snapshot([r], store=store)

        reg = _make_registry()
        restore_hybrid_continuity_from_snapshot(registry=reg, store=store)
        restored = reg.get(r.execution_id)
        assert restored is not None
        assert len(restored.partial_results) == 1
        assert restored.partial_results[0].status.value == "preserved"
        assert restored.partial_results[0].payload == {"partial": "data"}


# ---------------------------------------------------------------------------
# 61–64: End-to-end restart/recovery
# ---------------------------------------------------------------------------

class TestEndToEndRestartRecovery:
    def test_61_save_restore_mark_interrupted_cycle(self, tmp_path):
        """Full cycle: save snapshot → fresh registry → restore → mark interrupted."""
        from core.hybrid_continuity_persistence import (
            save_hybrid_continuity_snapshot,
            restore_hybrid_continuity_from_snapshot,
        )
        store = _make_store(str(tmp_path))

        # Pre-restart: create and start a hybrid execution
        reg_pre = _make_registry()
        r = reg_pre.create_and_register(session_id="s1", task_id="t1")
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        save_hybrid_continuity_snapshot(reg_pre.list_all(), store=store)

        # Post-restart: fresh registry, restore, then mark interrupted
        reg_post = _make_registry()
        restore_hybrid_continuity_from_snapshot(registry=reg_post, store=store)
        count = reg_post.mark_all_running_as_interrupted(reason="process_restart")

        assert count >= 1
        recovered = reg_post.get(r.execution_id)
        assert recovered is not None
        assert recovered.lifecycle_state.value == "interrupted"

    def test_62_interrupted_count_matches_non_terminal_saved(self, tmp_path):
        from core.hybrid_continuity_persistence import (
            save_hybrid_continuity_snapshot,
            restore_hybrid_continuity_from_snapshot,
        )
        store = _make_store(str(tmp_path))

        reg_pre = _make_registry()
        for _ in range(3):
            r = reg_pre.create_and_register()
            r.transition(_state("dispatched"))
            r.transition(_state("running"))
        # One terminal record
        r_done = reg_pre.create_and_register()
        r_done.transition(_state("dispatched"))
        r_done.transition(_state("running"))
        r_done.transition(_state("completed"))
        save_hybrid_continuity_snapshot(reg_pre.list_all(), store=store)

        reg_post = _make_registry()
        restore_hybrid_continuity_from_snapshot(registry=reg_post, store=store)
        count = reg_post.mark_all_running_as_interrupted(reason="restart")
        assert count == 3  # only the 3 non-terminal running records

    def test_63_partial_results_survive_snapshot_restore_cycle(self, tmp_path):
        from core.hybrid_continuity_persistence import (
            save_hybrid_continuity_snapshot,
            restore_hybrid_continuity_from_snapshot,
        )
        store = _make_store(str(tmp_path))

        reg_pre = _make_registry()
        r = reg_pre.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.record_partial_result(
            source="local", executor_level="a2a",
            status=_status("preserved"), payload={"step": "half-done"},
            reason="interrupted mid-stream",
        )
        save_hybrid_continuity_snapshot(reg_pre.list_all(), store=store)

        reg_post = _make_registry()
        restore_hybrid_continuity_from_snapshot(registry=reg_post, store=store)
        reg_post.mark_all_running_as_interrupted(reason="restart")

        recovered = reg_post.get(r.execution_id)
        assert recovered.lifecycle_state.value == "interrupted"
        assert len(recovered.partial_results) == 1
        assert recovered.partial_results[0].payload == {"step": "half-done"}
        assert recovered.partial_results[0].status.value == "preserved"

    def test_64_terminal_records_unchanged_after_restore_and_mark(self, tmp_path):
        from core.hybrid_continuity_persistence import (
            save_hybrid_continuity_snapshot,
            restore_hybrid_continuity_from_snapshot,
        )
        store = _make_store(str(tmp_path))

        reg_pre = _make_registry()
        r = reg_pre.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        r.transition(_state("completed"), result={"output": "done"})
        save_hybrid_continuity_snapshot(reg_pre.list_all(), store=store)

        reg_post = _make_registry()
        restore_hybrid_continuity_from_snapshot(registry=reg_post, store=store)
        reg_post.mark_all_running_as_interrupted(reason="restart")

        recovered = reg_post.get(r.execution_id)
        assert recovered.lifecycle_state.value == "completed"  # unchanged


# ---------------------------------------------------------------------------
# 65–69: RuntimeRestartRecoveryCoordinator — durable hybrid recovery
# ---------------------------------------------------------------------------

class TestCoordinatorDurableHybridRecovery:
    def test_65_run_recovery_with_store_restores_records(self, tmp_path):
        from core.hybrid_continuity_persistence import save_hybrid_continuity_snapshot
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator

        store = _make_store(str(tmp_path))
        reg_pre = _make_registry()
        r = reg_pre.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        save_hybrid_continuity_snapshot(reg_pre.list_all(), store=store)

        reg_post = _make_registry()
        coord = RuntimeRestartRecoveryCoordinator(
            hybrid_continuity_registry=reg_post,
            hybrid_continuity_store=store,
        )
        coord.run_recovery()
        recovered = reg_post.get(r.execution_id)
        assert recovered is not None

    def test_66_run_recovery_sets_hybrid_records_restored(self, tmp_path):
        from core.hybrid_continuity_persistence import save_hybrid_continuity_snapshot
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator

        store = _make_store(str(tmp_path))
        records = [_make_record() for _ in range(2)]
        save_hybrid_continuity_snapshot(records, store=store)

        reg = _make_registry()
        coord = RuntimeRestartRecoveryCoordinator(
            hybrid_continuity_registry=reg,
            hybrid_continuity_store=store,
        )
        report = coord.run_recovery()
        assert report.hybrid_records_restored == 2

    def test_67_run_recovery_marks_restored_running_records_interrupted(self, tmp_path):
        from core.hybrid_continuity_persistence import save_hybrid_continuity_snapshot
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator

        store = _make_store(str(tmp_path))
        reg_pre = _make_registry()
        r = reg_pre.create_and_register()
        r.transition(_state("dispatched"))
        r.transition(_state("running"))
        save_hybrid_continuity_snapshot(reg_pre.list_all(), store=store)

        reg_post = _make_registry()
        coord = RuntimeRestartRecoveryCoordinator(
            hybrid_continuity_registry=reg_post,
            hybrid_continuity_store=store,
        )
        report = coord.run_recovery()
        assert report.hybrid_executions_interrupted >= 1
        assert reg_post.get(r.execution_id).lifecycle_state.value == "interrupted"

    def test_68_hybrid_records_restored_defaults_to_zero(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        report = RuntimeRecoveryReport()
        assert report.hybrid_records_restored == 0

    def test_69_to_dict_includes_hybrid_records_restored(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        d = RuntimeRecoveryReport().to_dict()
        assert "hybrid_records_restored" in d


# ---------------------------------------------------------------------------
# 70–71: run_startup_recovery — durable hybrid store parameter
# ---------------------------------------------------------------------------

class TestRunStartupRecoveryDurableStore:
    def test_70_accepts_hybrid_continuity_store_parameter(self, tmp_path):
        from core.runtime_restart_recovery import run_startup_recovery
        store = _make_store(str(tmp_path))
        report = run_startup_recovery(hybrid_continuity_store=store)
        assert report is not None

    def test_71_with_populated_store_sets_hybrid_records_restored(self, tmp_path):
        from core.hybrid_continuity_persistence import save_hybrid_continuity_snapshot
        from core.runtime_restart_recovery import run_startup_recovery
        from core.hybrid_orchestration_continuity import reset_continuity_registry

        reset_continuity_registry()
        store = _make_store(str(tmp_path))
        records = [_make_record() for _ in range(2)]
        save_hybrid_continuity_snapshot(records, store=store)

        report = run_startup_recovery(hybrid_continuity_store=store)
        assert report.hybrid_records_restored == 2


# ---------------------------------------------------------------------------
# 72: HYBRID_CONTINUITY_DURABLE_RECOVERY_POLICY importability
# ---------------------------------------------------------------------------

class TestDurableRecoveryPolicyImportability:
    def test_72_importable_from_runtime_restart_recovery(self):
        from core.runtime_restart_recovery import HYBRID_CONTINUITY_DURABLE_RECOVERY_POLICY
        assert isinstance(HYBRID_CONTINUITY_DURABLE_RECOVERY_POLICY, str)
        assert "durable" in HYBRID_CONTINUITY_DURABLE_RECOVERY_POLICY.lower() \
            or "DURABLE" in HYBRID_CONTINUITY_DURABLE_RECOVERY_POLICY
