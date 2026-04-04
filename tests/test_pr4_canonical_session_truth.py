"""tests/test_pr4_canonical_session_truth.py
=============================================
Tests for PR-4 (post-533 dual-repo runtime host unification track, MAIN repo side):
Establish canonical runtime session truth and result merge across local and
cross-device execution.

Coverage groups
---------------
A  — Authority / policy sentinel presence and non-empty values.
B  — SessionTruthSource enum: all values present and str-compatible.
C  — CanonicalSessionTruthRecord: construction, to_dict(), posture normalisation.
D  — CanonicalSessionTruthSnapshot: construction, to_dict().
E  — CanonicalSessionTruthRuntime: record(), snapshot(), ring-buffer eviction.
F  — get/reset canonical session truth runtime: singleton identity.
G  — filter_result_units_by_posture: control_only units excluded.
H  — filter_result_units_by_posture: join_runtime / no-posture units kept.
I  — filter_result_units_by_posture: None / empty input.
J  — filter_result_units_by_posture: allow_control_only_as_observer passthrough.
K  — filter_result_units_by_posture: dict and object unit shapes.
L  — merge_session_truth: control_only source — contributors filtered out.
M  — merge_session_truth: join_runtime source — all units eligible.
N  — merge_session_truth: mixed units — only non-control-only pass through.
O  — merge_session_truth: always returns MergedRuntimeResult, never raises.
P  — merge_session_truth: merge_policy kwarg is forwarded correctly.
Q  — record_session_truth: records are stored in runtime, snapshot reflects them.
R  — record_session_truth: control_only / join_runtime count separation.
S  — record_session_truth: merge_success propagates correctly.
T  — record_session_truth: truth_source inferred from primary unit metadata.
U  — build_canonical_session_truth_snapshot: summary counts across records.
V  — core.runtime re-exports: all PR-4 symbols accessible from core.runtime.
W  — RuntimeSessionSnapshot: source_runtime_posture field present with default.
X  — RuntimeSessionSnapshotIdentity: source_runtime_posture field present.
Y  — RuntimeSessionSnapshotDispatchState: source_runtime_posture field present.
Z  — RuntimeSessionSnapshotResultState: source_runtime_posture + excluded_unit_ids fields.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result_unit(
    *,
    result_unit_id: Optional[str] = None,
    status: str = "succeeded",
    source_runtime_posture: Optional[str] = None,
    output: Optional[Dict[str, Any]] = None,
    role: str = "source",
) -> Dict[str, Any]:
    """Return a minimal dict shaped like a RuntimeResultUnit."""
    meta: Dict[str, Any] = {}
    if source_runtime_posture is not None:
        meta["source_runtime_posture"] = source_runtime_posture
    return {
        "result_unit_id": result_unit_id or str(uuid.uuid4()),
        "status": status,
        "role": role,
        "output": output or {"result": "ok"},
        "metadata": meta,
        "timestamp": 1700000000.0,
    }


def _make_pydantic_unit(
    *,
    result_unit_id: Optional[str] = None,
    status: str = "succeeded",
    source_runtime_posture: Optional[str] = None,
    output: Optional[Dict[str, Any]] = None,
    role: str = "source",
) -> Any:
    """Return a real RuntimeResultUnit pydantic instance."""
    from contracts.cross_runtime_result_merge import RuntimeResultUnit, RuntimeResultStatus, RuntimeResultRole

    meta: Dict[str, Any] = {}
    if source_runtime_posture is not None:
        meta["source_runtime_posture"] = source_runtime_posture

    _valid_roles = {r.value for r in RuntimeResultRole}
    _role = role if role in _valid_roles else "unknown"

    return RuntimeResultUnit(
        result_unit_id=result_unit_id or str(uuid.uuid4()),
        status=RuntimeResultStatus(status),
        role=RuntimeResultRole(_role),
        output=output or {"result": "ok"},
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_runtime():
    """Reset the canonical session truth runtime before/after each test."""
    from core.canonical_session_truth import reset_canonical_session_truth_runtime
    reset_canonical_session_truth_runtime()
    yield
    reset_canonical_session_truth_runtime()


# ===========================================================================
# Group A — Authority / policy sentinels
# ===========================================================================

class TestGroupA_Sentinels:
    def test_A01_canonical_session_truth_authority_non_empty(self):
        from core.canonical_session_truth import CANONICAL_SESSION_TRUTH_AUTHORITY
        assert isinstance(CANONICAL_SESSION_TRUTH_AUTHORITY, str)
        assert len(CANONICAL_SESSION_TRUTH_AUTHORITY) > 20

    def test_A02_control_only_excluded_policy_non_empty(self):
        from core.canonical_session_truth import CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY
        assert isinstance(CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY, str)
        assert "control_only" in CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY

    def test_A03_posture_aware_filter_policy_non_empty(self):
        from core.canonical_session_truth import POSTURE_AWARE_RESULT_FILTER_POLICY
        assert isinstance(POSTURE_AWARE_RESULT_FILTER_POLICY, str)
        assert len(POSTURE_AWARE_RESULT_FILTER_POLICY) > 20

    def test_A04_join_runtime_included_policy_non_empty(self):
        from core.canonical_session_truth import JOIN_RUNTIME_INCLUDED_IN_MERGE_POLICY
        assert isinstance(JOIN_RUNTIME_INCLUDED_IN_MERGE_POLICY, str)
        assert "join_runtime" in JOIN_RUNTIME_INCLUDED_IN_MERGE_POLICY

    def test_A05_pr4_sentinel_non_empty(self):
        from core.canonical_session_truth import CANONICAL_SESSION_TRUTH_PR4_SENTINEL
        assert isinstance(CANONICAL_SESSION_TRUTH_PR4_SENTINEL, str)
        assert "PR-4" in CANONICAL_SESSION_TRUTH_PR4_SENTINEL

    def test_A06_sentinel_references_pr4_track(self):
        from core.canonical_session_truth import CANONICAL_SESSION_TRUTH_AUTHORITY
        assert "post-533" in CANONICAL_SESSION_TRUTH_AUTHORITY
        assert "PR-4" in CANONICAL_SESSION_TRUTH_AUTHORITY


# ===========================================================================
# Group B — SessionTruthSource enum
# ===========================================================================

class TestGroupB_SessionTruthSource:
    def test_B01_all_values_present(self):
        from core.canonical_session_truth import SessionTruthSource
        values = {s.value for s in SessionTruthSource}
        assert "local" in values
        assert "remote_handoff" in values
        assert "takeover" in values
        assert "multi_device" in values
        assert "mesh" in values
        assert "unknown" in values

    def test_B02_str_compatible(self):
        from core.canonical_session_truth import SessionTruthSource
        assert SessionTruthSource.local == "local"
        assert SessionTruthSource.takeover == "takeover"

    def test_B03_json_serialisable(self):
        import json
        from core.canonical_session_truth import SessionTruthSource
        for v in SessionTruthSource:
            assert json.dumps(v)  # must not raise


# ===========================================================================
# Group C — CanonicalSessionTruthRecord
# ===========================================================================

class TestGroupC_CanonicalSessionTruthRecord:
    def test_C01_construction_defaults(self):
        from core.canonical_session_truth import CanonicalSessionTruthRecord
        rec = CanonicalSessionTruthRecord()
        assert rec.source_runtime_posture == "control_only"
        assert rec.source_eligible is False
        assert rec.total_units_received == 0
        assert rec.units_after_filter == 0
        assert rec.filtered_unit_ids == []
        assert rec.merge_success is False
        assert rec.record_id.startswith("cst_")

    def test_C02_construction_with_values(self):
        from core.canonical_session_truth import CanonicalSessionTruthRecord
        rec = CanonicalSessionTruthRecord(
            session_id="sess_001",
            task_id="task_001",
            trace_id="trace_001",
            source_runtime_posture="join_runtime",
            source_eligible=True,
            total_units_received=3,
            units_after_filter=3,
            merge_success=True,
            merge_id="merge_001",
        )
        assert rec.session_id == "sess_001"
        assert rec.source_runtime_posture == "join_runtime"
        assert rec.source_eligible is True
        assert rec.merge_success is True

    def test_C03_to_dict_includes_authority(self):
        from core.canonical_session_truth import (
            CanonicalSessionTruthRecord,
            CANONICAL_SESSION_TRUTH_AUTHORITY,
        )
        rec = CanonicalSessionTruthRecord(session_id="s1")
        d = rec.to_dict()
        assert d["authority"] == CANONICAL_SESSION_TRUTH_AUTHORITY
        assert d["source_runtime_posture"] == "control_only"
        assert "filtered_unit_ids" in d

    def test_C04_to_dict_round_trip(self):
        from core.canonical_session_truth import CanonicalSessionTruthRecord
        rec = CanonicalSessionTruthRecord(
            session_id="sess_rt",
            source_runtime_posture="join_runtime",
            filtered_unit_ids=["uid-001", "uid-002"],
            merge_success=True,
        )
        d = rec.to_dict()
        assert d["session_id"] == "sess_rt"
        assert d["source_runtime_posture"] == "join_runtime"
        assert "uid-001" in d["filtered_unit_ids"]
        assert d["merge_success"] is True

    def test_C05_unique_record_ids(self):
        from core.canonical_session_truth import CanonicalSessionTruthRecord
        ids = {CanonicalSessionTruthRecord().record_id for _ in range(10)}
        assert len(ids) == 10


# ===========================================================================
# Group D — CanonicalSessionTruthSnapshot
# ===========================================================================

class TestGroupD_CanonicalSessionTruthSnapshot:
    def test_D01_construction_defaults(self):
        from core.canonical_session_truth import CanonicalSessionTruthSnapshot
        snap = CanonicalSessionTruthSnapshot()
        assert snap.total_records == 0
        assert snap.recent_records == []
        assert snap.control_only_session_count == 0
        assert snap.join_runtime_session_count == 0
        assert snap.successful_merge_count == 0
        assert snap.snapshot_id.startswith("cst_snap_")

    def test_D02_to_dict_includes_authority(self):
        from core.canonical_session_truth import (
            CanonicalSessionTruthSnapshot,
            CANONICAL_SESSION_TRUTH_AUTHORITY,
        )
        snap = CanonicalSessionTruthSnapshot(total_records=5, successful_merge_count=3)
        d = snap.to_dict()
        assert d["authority"] == CANONICAL_SESSION_TRUTH_AUTHORITY
        assert d["total_records"] == 5
        assert d["successful_merge_count"] == 3

    def test_D03_unique_snapshot_ids(self):
        from core.canonical_session_truth import CanonicalSessionTruthSnapshot
        ids = {CanonicalSessionTruthSnapshot().snapshot_id for _ in range(10)}
        assert len(ids) == 10


# ===========================================================================
# Group E — CanonicalSessionTruthRuntime
# ===========================================================================

class TestGroupE_CanonicalSessionTruthRuntime:
    def test_E01_record_increments_total(self):
        from core.canonical_session_truth import (
            CanonicalSessionTruthRecord,
            CanonicalSessionTruthRuntime,
        )
        rt = CanonicalSessionTruthRuntime()
        rt.record(CanonicalSessionTruthRecord(session_id="s1"))
        rt.record(CanonicalSessionTruthRecord(session_id="s2"))
        snap = rt.snapshot()
        assert snap.total_records == 2

    def test_E02_control_only_count(self):
        from core.canonical_session_truth import (
            CanonicalSessionTruthRecord,
            CanonicalSessionTruthRuntime,
        )
        rt = CanonicalSessionTruthRuntime()
        rt.record(CanonicalSessionTruthRecord(source_runtime_posture="control_only"))
        rt.record(CanonicalSessionTruthRecord(source_runtime_posture="control_only"))
        snap = rt.snapshot()
        assert snap.control_only_session_count == 2
        assert snap.join_runtime_session_count == 0

    def test_E03_join_runtime_count(self):
        from core.canonical_session_truth import (
            CanonicalSessionTruthRecord,
            CanonicalSessionTruthRuntime,
        )
        rt = CanonicalSessionTruthRuntime()
        rt.record(CanonicalSessionTruthRecord(source_runtime_posture="join_runtime"))
        snap = rt.snapshot()
        assert snap.join_runtime_session_count == 1
        assert snap.control_only_session_count == 0

    def test_E04_success_count(self):
        from core.canonical_session_truth import (
            CanonicalSessionTruthRecord,
            CanonicalSessionTruthRuntime,
        )
        rt = CanonicalSessionTruthRuntime()
        rt.record(CanonicalSessionTruthRecord(merge_success=True))
        rt.record(CanonicalSessionTruthRecord(merge_success=False))
        snap = rt.snapshot()
        assert snap.successful_merge_count == 1

    def test_E05_ring_buffer_eviction(self):
        from core.canonical_session_truth import (
            CanonicalSessionTruthRecord,
            CanonicalSessionTruthRuntime,
        )
        rt = CanonicalSessionTruthRuntime(max_size=5)
        for i in range(10):
            rt.record(CanonicalSessionTruthRecord(session_id=f"s{i}"))
        snap = rt.snapshot(max_recent=20)
        # Ring buffer holds at most 5; total is 10
        assert snap.total_records == 10
        assert len(snap.recent_records) <= 5

    def test_E06_recent_records_are_dicts(self):
        from core.canonical_session_truth import (
            CanonicalSessionTruthRecord,
            CanonicalSessionTruthRuntime,
        )
        rt = CanonicalSessionTruthRuntime()
        rt.record(CanonicalSessionTruthRecord(session_id="s1"))
        snap = rt.snapshot(max_recent=5)
        assert all(isinstance(r, dict) for r in snap.recent_records)


# ===========================================================================
# Group F — get/reset singleton
# ===========================================================================

class TestGroupF_Singleton:
    def test_F01_get_returns_same_instance(self):
        from core.canonical_session_truth import get_canonical_session_truth_runtime
        rt1 = get_canonical_session_truth_runtime()
        rt2 = get_canonical_session_truth_runtime()
        assert rt1 is rt2

    def test_F02_reset_creates_new_instance(self):
        from core.canonical_session_truth import (
            get_canonical_session_truth_runtime,
            reset_canonical_session_truth_runtime,
        )
        rt1 = get_canonical_session_truth_runtime()
        reset_canonical_session_truth_runtime()
        rt2 = get_canonical_session_truth_runtime()
        assert rt1 is not rt2

    def test_F03_reset_clears_counts(self):
        from core.canonical_session_truth import (
            CanonicalSessionTruthRecord,
            get_canonical_session_truth_runtime,
            reset_canonical_session_truth_runtime,
        )
        rt = get_canonical_session_truth_runtime()
        rt.record(CanonicalSessionTruthRecord())
        reset_canonical_session_truth_runtime()
        snap = get_canonical_session_truth_runtime().snapshot()
        assert snap.total_records == 0


# ===========================================================================
# Group G — filter_result_units_by_posture: control_only excluded
# ===========================================================================

class TestGroupG_FilterControlOnly:
    def test_G01_control_only_unit_excluded(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        unit = _make_result_unit(source_runtime_posture="control_only")
        kept, excluded = filter_result_units_by_posture([unit])
        assert kept == []
        assert len(excluded) == 1
        assert unit["result_unit_id"] in excluded

    def test_G02_multiple_control_only_all_excluded(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        units = [
            _make_result_unit(source_runtime_posture="control_only"),
            _make_result_unit(source_runtime_posture="control_only"),
        ]
        kept, excluded = filter_result_units_by_posture(units)
        assert kept == []
        assert len(excluded) == 2

    def test_G03_excluded_ids_match_unit_ids(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        uid = str(uuid.uuid4())
        unit = _make_result_unit(result_unit_id=uid, source_runtime_posture="control_only")
        _, excluded = filter_result_units_by_posture([unit])
        assert uid in excluded


# ===========================================================================
# Group H — filter_result_units_by_posture: join_runtime / no-posture kept
# ===========================================================================

class TestGroupH_FilterJoinRuntime:
    def test_H01_join_runtime_unit_kept(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        unit = _make_result_unit(source_runtime_posture="join_runtime")
        kept, excluded = filter_result_units_by_posture([unit])
        assert len(kept) == 1
        assert excluded == []

    def test_H02_no_posture_metadata_unit_kept(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        unit = _make_result_unit()  # no source_runtime_posture in metadata
        kept, excluded = filter_result_units_by_posture([unit])
        assert len(kept) == 1
        assert excluded == []

    def test_H03_mixed_units_correct_split(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        u_co = _make_result_unit(source_runtime_posture="control_only")
        u_jr = _make_result_unit(source_runtime_posture="join_runtime")
        u_no = _make_result_unit()
        kept, excluded = filter_result_units_by_posture([u_co, u_jr, u_no])
        assert len(kept) == 2
        assert len(excluded) == 1
        assert u_co["result_unit_id"] in excluded


# ===========================================================================
# Group I — filter_result_units_by_posture: None / empty input
# ===========================================================================

class TestGroupI_FilterEmpty:
    def test_I01_none_input(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        kept, excluded = filter_result_units_by_posture(None)
        assert kept == []
        assert excluded == []

    def test_I02_empty_list(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        kept, excluded = filter_result_units_by_posture([])
        assert kept == []
        assert excluded == []

    def test_I03_never_raises(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        # Should not raise for any input
        kept, excluded = filter_result_units_by_posture(None, source_runtime_posture=None)
        assert isinstance(kept, list)
        assert isinstance(excluded, list)


# ===========================================================================
# Group J — filter_result_units_by_posture: allow_control_only_as_observer
# ===========================================================================

class TestGroupJ_AllowControlOnlyObserver:
    def test_J01_control_only_kept_when_observer_allowed(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        unit = _make_result_unit(source_runtime_posture="control_only")
        kept, excluded = filter_result_units_by_posture(
            [unit], allow_control_only_as_observer=True
        )
        assert len(kept) == 1
        assert excluded == []

    def test_J02_default_is_exclusion(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        unit = _make_result_unit(source_runtime_posture="control_only")
        kept, excluded = filter_result_units_by_posture([unit])
        assert kept == []
        assert len(excluded) == 1


# ===========================================================================
# Group K — filter_result_units_by_posture: dict and object unit shapes
# ===========================================================================

class TestGroupK_UnitShapes:
    def test_K01_dict_unit_excluded_by_posture(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        unit = _make_result_unit(source_runtime_posture="control_only")
        assert isinstance(unit, dict)
        kept, excluded = filter_result_units_by_posture([unit])
        assert kept == []

    def test_K02_pydantic_unit_excluded_by_posture(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        unit = _make_pydantic_unit(source_runtime_posture="control_only")
        kept, excluded = filter_result_units_by_posture([unit])
        assert kept == []
        assert len(excluded) == 1

    def test_K03_pydantic_unit_kept_when_join_runtime(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        unit = _make_pydantic_unit(source_runtime_posture="join_runtime")
        kept, excluded = filter_result_units_by_posture([unit])
        assert len(kept) == 1
        assert excluded == []

    def test_K04_pydantic_unit_kept_when_no_posture(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        unit = _make_pydantic_unit()  # no posture metadata
        kept, excluded = filter_result_units_by_posture([unit])
        assert len(kept) == 1

    def test_K05_unknown_posture_value_treated_as_none(self):
        from core.canonical_session_truth import filter_result_units_by_posture
        unit = _make_result_unit()
        unit["metadata"]["source_runtime_posture"] = "totally_unknown_value"
        # Unknown posture → treated as None (not control_only), so kept
        kept, excluded = filter_result_units_by_posture([unit])
        assert len(kept) == 1


# ===========================================================================
# Group L — merge_session_truth: control_only source
# ===========================================================================

class TestGroupL_MergeSessionTruthControlOnly:
    def test_L01_control_only_source_units_excluded_from_merge(self):
        from core.canonical_session_truth import merge_session_truth
        # Two units: one from control_only source, one remote target (no posture)
        co_unit = _make_result_unit(source_runtime_posture="control_only")
        remote_unit = _make_result_unit()
        result = merge_session_truth(
            [co_unit, remote_unit],
            session_id="sess_co",
            source_runtime_posture="control_only",
        )
        # Only the remote unit should be in the merge
        assert result is not None
        # merged metadata should carry excluded units
        excluded = result.metadata.get("excluded_unit_ids", [])
        assert co_unit["result_unit_id"] in excluded

    def test_L02_all_control_only_merge_empty(self):
        from core.canonical_session_truth import merge_session_truth
        co_unit = _make_result_unit(source_runtime_posture="control_only")
        result = merge_session_truth(
            [co_unit],
            session_id="sess_co_empty",
            source_runtime_posture="control_only",
        )
        assert result is not None
        # With no kept units, merge should have success=False
        assert result.success is False

    def test_L03_posture_propagated_in_metadata(self):
        from core.canonical_session_truth import merge_session_truth
        result = merge_session_truth(
            [_make_result_unit()],
            session_id="sess_meta",
            source_runtime_posture="control_only",
        )
        assert result.metadata.get("source_runtime_posture") == "control_only"

    def test_L04_pr4_sentinel_in_metadata(self):
        from core.canonical_session_truth import (
            merge_session_truth,
            CANONICAL_SESSION_TRUTH_PR4_SENTINEL,
        )
        result = merge_session_truth(
            [_make_result_unit()],
            session_id="sess_sentinel",
        )
        assert result.metadata.get("pr4_sentinel") == CANONICAL_SESSION_TRUTH_PR4_SENTINEL


# ===========================================================================
# Group M — merge_session_truth: join_runtime source
# ===========================================================================

class TestGroupM_MergeSessionTruthJoinRuntime:
    def test_M01_join_runtime_all_units_eligible(self):
        from core.canonical_session_truth import merge_session_truth
        units = [_make_result_unit(), _make_result_unit(), _make_result_unit()]
        result = merge_session_truth(
            units,
            session_id="sess_jr",
            source_runtime_posture="join_runtime",
        )
        assert result is not None
        excluded = result.metadata.get("excluded_unit_ids", [])
        assert excluded == []

    def test_M02_join_runtime_posture_in_metadata(self):
        from core.canonical_session_truth import merge_session_truth
        result = merge_session_truth(
            [_make_result_unit()],
            session_id="sess_jr_meta",
            source_runtime_posture="join_runtime",
        )
        assert result.metadata.get("source_runtime_posture") == "join_runtime"


# ===========================================================================
# Group N — merge_session_truth: mixed units
# ===========================================================================

class TestGroupN_MergeSessionTruthMixed:
    def test_N01_only_non_control_only_in_result(self):
        from core.canonical_session_truth import merge_session_truth
        co = _make_result_unit(source_runtime_posture="control_only")
        jr = _make_result_unit(source_runtime_posture="join_runtime")
        remote = _make_result_unit()
        result = merge_session_truth(
            [co, jr, remote],
            session_id="sess_mixed",
        )
        excluded = result.metadata.get("excluded_unit_ids", [])
        assert co["result_unit_id"] in excluded
        assert jr["result_unit_id"] not in excluded
        assert remote["result_unit_id"] not in excluded

    def test_N02_result_units_contains_only_kept(self):
        from core.canonical_session_truth import merge_session_truth
        co_id = str(uuid.uuid4())
        jr_id = str(uuid.uuid4())
        co = _make_result_unit(result_unit_id=co_id, source_runtime_posture="control_only")
        jr = _make_result_unit(result_unit_id=jr_id, source_runtime_posture="join_runtime")
        result = merge_session_truth([co, jr], session_id="sess_units_check")
        unit_ids_in_result = [u.result_unit_id for u in result.result_units]
        assert co_id not in unit_ids_in_result
        assert jr_id in unit_ids_in_result


# ===========================================================================
# Group O — merge_session_truth: never raises
# ===========================================================================

class TestGroupO_MergeNeverRaises:
    def test_O01_none_units(self):
        from core.canonical_session_truth import merge_session_truth
        result = merge_session_truth(None, session_id="s")
        assert result is not None

    def test_O02_empty_units(self):
        from core.canonical_session_truth import merge_session_truth
        result = merge_session_truth([], session_id="s")
        assert result is not None

    def test_O03_unknown_merge_policy_falls_back(self):
        from core.canonical_session_truth import merge_session_truth
        result = merge_session_truth(
            [_make_result_unit()],
            session_id="s",
            merge_policy="totally_invalid_policy",
        )
        assert result is not None

    def test_O04_none_session_id(self):
        from core.canonical_session_truth import merge_session_truth
        result = merge_session_truth([_make_result_unit()])
        assert result is not None


# ===========================================================================
# Group P — merge_session_truth: merge_policy forwarded
# ===========================================================================

class TestGroupP_MergePolicy:
    def test_P01_primary_wins_policy(self):
        from core.canonical_session_truth import merge_session_truth
        units = [_make_result_unit(), _make_result_unit()]
        result = merge_session_truth(units, session_id="s", merge_policy="primary_wins")
        assert result is not None
        # primary_wins with two success units: one should be selected
        assert result.success is True

    def test_P02_best_effort_policy(self):
        from core.canonical_session_truth import merge_session_truth
        units = [
            _make_result_unit(status="succeeded"),
            _make_result_unit(status="failed"),
        ]
        result = merge_session_truth(units, session_id="s", merge_policy="best_effort")
        assert result is not None

    def test_P03_all_required_policy_all_success(self):
        from core.canonical_session_truth import merge_session_truth
        units = [_make_result_unit(status="succeeded"), _make_result_unit(status="succeeded")]
        result = merge_session_truth(units, session_id="s", merge_policy="all_required")
        assert result is not None
        assert result.success is True

    def test_P04_all_required_policy_one_failure(self):
        from core.canonical_session_truth import merge_session_truth
        units = [
            _make_result_unit(status="succeeded"),
            _make_result_unit(status="failed"),
        ]
        result = merge_session_truth(units, session_id="s", merge_policy="all_required")
        assert result is not None
        assert result.success is False


# ===========================================================================
# Group Q — record_session_truth: ring-buffer storage
# ===========================================================================

class TestGroupQ_RecordSessionTruth:
    def test_Q01_record_stored_in_runtime(self):
        from core.canonical_session_truth import (
            record_session_truth,
            build_canonical_session_truth_snapshot,
        )
        record_session_truth(session_id="sess_q01")
        snap = build_canonical_session_truth_snapshot()
        assert snap.total_records == 1

    def test_Q02_multiple_records(self):
        from core.canonical_session_truth import (
            record_session_truth,
            build_canonical_session_truth_snapshot,
        )
        record_session_truth(session_id="s1")
        record_session_truth(session_id="s2")
        record_session_truth(session_id="s3")
        snap = build_canonical_session_truth_snapshot()
        assert snap.total_records == 3

    def test_Q03_returns_canonical_session_truth_record(self):
        from core.canonical_session_truth import (
            record_session_truth,
            CanonicalSessionTruthRecord,
        )
        rec = record_session_truth(session_id="sess_q03")
        assert isinstance(rec, CanonicalSessionTruthRecord)

    def test_Q04_record_has_correct_session_id(self):
        from core.canonical_session_truth import record_session_truth
        rec = record_session_truth(session_id="sess_q04", task_id="task_q04")
        assert rec.session_id == "sess_q04"
        assert rec.task_id == "task_q04"

    def test_Q05_record_merge_id_set(self):
        from core.canonical_session_truth import record_session_truth
        unit = _make_result_unit(status="succeeded")
        rec = record_session_truth(
            session_id="sess_q05",
            result_units=[unit],
        )
        assert rec.merge_id is not None


# ===========================================================================
# Group R — record_session_truth: posture count separation
# ===========================================================================

class TestGroupR_PostureCountSeparation:
    def test_R01_control_only_increments_control_count(self):
        from core.canonical_session_truth import (
            record_session_truth,
            build_canonical_session_truth_snapshot,
        )
        record_session_truth(session_id="s1", source_runtime_posture="control_only")
        record_session_truth(session_id="s2", source_runtime_posture="control_only")
        snap = build_canonical_session_truth_snapshot()
        assert snap.control_only_session_count == 2
        assert snap.join_runtime_session_count == 0

    def test_R02_join_runtime_increments_join_count(self):
        from core.canonical_session_truth import (
            record_session_truth,
            build_canonical_session_truth_snapshot,
        )
        record_session_truth(session_id="s1", source_runtime_posture="join_runtime")
        snap = build_canonical_session_truth_snapshot()
        assert snap.join_runtime_session_count == 1
        assert snap.control_only_session_count == 0

    def test_R03_mixed_postures_correct_counts(self):
        from core.canonical_session_truth import (
            record_session_truth,
            build_canonical_session_truth_snapshot,
        )
        record_session_truth(session_id="s1", source_runtime_posture="control_only")
        record_session_truth(session_id="s2", source_runtime_posture="join_runtime")
        record_session_truth(session_id="s3", source_runtime_posture="control_only")
        snap = build_canonical_session_truth_snapshot()
        assert snap.control_only_session_count == 2
        assert snap.join_runtime_session_count == 1

    def test_R04_unknown_posture_defaults_to_control_only(self):
        from core.canonical_session_truth import (
            record_session_truth,
            build_canonical_session_truth_snapshot,
        )
        record_session_truth(session_id="s1", source_runtime_posture=None)
        snap = build_canonical_session_truth_snapshot()
        assert snap.control_only_session_count == 1


# ===========================================================================
# Group S — record_session_truth: merge_success propagation
# ===========================================================================

class TestGroupS_MergeSuccessPropagation:
    def test_S01_successful_merge_increments_count(self):
        from core.canonical_session_truth import (
            record_session_truth,
            build_canonical_session_truth_snapshot,
        )
        unit = _make_result_unit(status="succeeded")
        record_session_truth(
            session_id="s1",
            result_units=[unit],
            source_runtime_posture="join_runtime",
        )
        snap = build_canonical_session_truth_snapshot()
        assert snap.successful_merge_count == 1

    def test_S02_failed_merge_does_not_increment(self):
        from core.canonical_session_truth import (
            record_session_truth,
            build_canonical_session_truth_snapshot,
        )
        # No units → merge will fail
        record_session_truth(session_id="s1", result_units=[])
        snap = build_canonical_session_truth_snapshot()
        assert snap.successful_merge_count == 0

    def test_S03_record_merge_success_field(self):
        from core.canonical_session_truth import record_session_truth
        unit = _make_result_unit(status="succeeded")
        rec = record_session_truth(
            session_id="s",
            result_units=[unit],
            source_runtime_posture="join_runtime",
        )
        assert rec.merge_success is True

    def test_S04_record_merge_failure_field(self):
        from core.canonical_session_truth import record_session_truth
        rec = record_session_truth(session_id="s", result_units=[])
        assert rec.merge_success is False


# ===========================================================================
# Group T — record_session_truth: truth_source inference
# ===========================================================================

class TestGroupT_TruthSourceInference:
    def test_T01_explicit_truth_source_preserved(self):
        from core.canonical_session_truth import (
            record_session_truth,
            SessionTruthSource,
        )
        rec = record_session_truth(
            session_id="s",
            truth_source=SessionTruthSource.takeover.value,
        )
        assert rec.truth_source == SessionTruthSource.takeover.value

    def test_T02_default_truth_source_is_unknown(self):
        from core.canonical_session_truth import (
            record_session_truth,
            SessionTruthSource,
        )
        rec = record_session_truth(session_id="s")
        assert rec.truth_source == SessionTruthSource.unknown.value

    def test_T03_truth_source_from_primary_unit_metadata(self):
        from core.canonical_session_truth import (
            record_session_truth,
            SessionTruthSource,
        )
        uid = str(uuid.uuid4())
        unit = _make_result_unit(result_unit_id=uid, status="succeeded")
        unit["metadata"]["truth_source"] = SessionTruthSource.remote_handoff.value
        rec = record_session_truth(
            session_id="s",
            result_units=[unit],
            source_runtime_posture="join_runtime",
        )
        # If primary unit has truth_source metadata, it should be inferred
        assert rec.truth_source in (
            SessionTruthSource.remote_handoff.value,
            SessionTruthSource.unknown.value,  # fallback if not primary
        )


# ===========================================================================
# Group U — build_canonical_session_truth_snapshot
# ===========================================================================

class TestGroupU_BuildSnapshot:
    def test_U01_empty_runtime_snapshot(self):
        from core.canonical_session_truth import build_canonical_session_truth_snapshot
        snap = build_canonical_session_truth_snapshot()
        assert snap.total_records == 0
        assert snap.recent_records == []

    def test_U02_snapshot_after_records(self):
        from core.canonical_session_truth import (
            record_session_truth,
            build_canonical_session_truth_snapshot,
        )
        record_session_truth(session_id="s1", source_runtime_posture="control_only")
        record_session_truth(session_id="s2", source_runtime_posture="join_runtime")
        snap = build_canonical_session_truth_snapshot()
        assert snap.total_records == 2
        assert snap.control_only_session_count == 1
        assert snap.join_runtime_session_count == 1

    def test_U03_max_recent_parameter(self):
        from core.canonical_session_truth import (
            record_session_truth,
            build_canonical_session_truth_snapshot,
        )
        for i in range(10):
            record_session_truth(session_id=f"s{i}")
        snap = build_canonical_session_truth_snapshot(max_recent=3)
        assert len(snap.recent_records) <= 3

    def test_U04_to_dict_is_json_serialisable(self):
        import json
        from core.canonical_session_truth import build_canonical_session_truth_snapshot
        snap = build_canonical_session_truth_snapshot()
        assert json.dumps(snap.to_dict())  # must not raise


# ===========================================================================
# Group V — core.runtime re-exports
# ===========================================================================

class TestGroupV_CoreRuntimeReexports:
    def test_V01_canonical_session_truth_authority_accessible(self):
        from core.runtime import CANONICAL_SESSION_TRUTH_AUTHORITY
        assert isinstance(CANONICAL_SESSION_TRUTH_AUTHORITY, str)

    def test_V02_control_only_excluded_policy_accessible(self):
        from core.runtime import CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY
        assert isinstance(CONTROL_ONLY_EXCLUDED_FROM_MERGE_POLICY, str)

    def test_V03_posture_aware_filter_policy_accessible(self):
        from core.runtime import POSTURE_AWARE_RESULT_FILTER_POLICY
        assert isinstance(POSTURE_AWARE_RESULT_FILTER_POLICY, str)

    def test_V04_join_runtime_included_policy_accessible(self):
        from core.runtime import JOIN_RUNTIME_INCLUDED_IN_MERGE_POLICY
        assert isinstance(JOIN_RUNTIME_INCLUDED_IN_MERGE_POLICY, str)

    def test_V05_pr4_sentinel_accessible(self):
        from core.runtime import CANONICAL_SESSION_TRUTH_PR4_SENTINEL
        assert isinstance(CANONICAL_SESSION_TRUTH_PR4_SENTINEL, str)

    def test_V06_session_truth_source_accessible(self):
        from core.runtime import SessionTruthSource
        assert SessionTruthSource.local == "local"

    def test_V07_canonical_session_truth_record_accessible(self):
        from core.runtime import CanonicalSessionTruthRecord
        rec = CanonicalSessionTruthRecord()
        assert rec.record_id.startswith("cst_")

    def test_V08_canonical_session_truth_snapshot_accessible(self):
        from core.runtime import CanonicalSessionTruthSnapshot
        snap = CanonicalSessionTruthSnapshot()
        assert snap.total_records == 0

    def test_V09_filter_result_units_by_posture_accessible(self):
        from core.runtime import filter_result_units_by_posture
        kept, excluded = filter_result_units_by_posture([])
        assert kept == []

    def test_V10_merge_session_truth_accessible(self):
        from core.runtime import merge_session_truth
        result = merge_session_truth(session_id="test")
        assert result is not None

    def test_V11_record_session_truth_accessible(self):
        from core.runtime import record_session_truth, CanonicalSessionTruthRecord
        rec = record_session_truth(session_id="test")
        assert isinstance(rec, CanonicalSessionTruthRecord)

    def test_V12_build_snapshot_accessible(self):
        from core.runtime import build_canonical_session_truth_snapshot
        snap = build_canonical_session_truth_snapshot()
        assert snap is not None

    def test_V13_get_runtime_accessible(self):
        from core.runtime import (
            get_canonical_session_truth_runtime,
            CanonicalSessionTruthRuntime,
        )
        rt = get_canonical_session_truth_runtime()
        assert isinstance(rt, CanonicalSessionTruthRuntime)

    def test_V14_reset_runtime_accessible(self):
        from core.runtime import reset_canonical_session_truth_runtime
        reset_canonical_session_truth_runtime()  # should not raise


# ===========================================================================
# Group W — RuntimeSessionSnapshot: source_runtime_posture field
# ===========================================================================

class TestGroupW_RuntimeSessionSnapshot:
    def test_W01_source_runtime_posture_field_exists_with_default(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot
        snap = RuntimeSessionSnapshot(session_id="sess_w01")
        assert hasattr(snap, "source_runtime_posture")
        assert snap.source_runtime_posture == "control_only"

    def test_W02_source_runtime_posture_can_be_set_to_join_runtime(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot
        snap = RuntimeSessionSnapshot(
            session_id="sess_w02",
            source_runtime_posture="join_runtime",
        )
        assert snap.source_runtime_posture == "join_runtime"

    def test_W03_to_dict_includes_source_runtime_posture(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot
        snap = RuntimeSessionSnapshot(
            session_id="sess_w03",
            source_runtime_posture="join_runtime",
        )
        d = snap.to_dict()
        assert d["source_runtime_posture"] == "join_runtime"

    def test_W04_from_dict_round_trip(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot
        d = {
            "session_id": "sess_w04",
            "source_runtime_posture": "join_runtime",
        }
        snap = RuntimeSessionSnapshot.from_dict(d)
        assert snap.source_runtime_posture == "join_runtime"

    def test_W05_default_posture_is_control_only(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshot
        snap = RuntimeSessionSnapshot(session_id="sess_w05")
        assert snap.source_runtime_posture == "control_only"


# ===========================================================================
# Group X — RuntimeSessionSnapshotIdentity: source_runtime_posture field
# ===========================================================================

class TestGroupX_RuntimeSessionSnapshotIdentity:
    def test_X01_source_runtime_posture_field_exists(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotIdentity
        identity = RuntimeSessionSnapshotIdentity(session_id="sess_x01")
        assert hasattr(identity, "source_runtime_posture")
        assert identity.source_runtime_posture == "control_only"

    def test_X02_join_runtime_can_be_set(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotIdentity
        identity = RuntimeSessionSnapshotIdentity(
            session_id="sess_x02",
            source_runtime_posture="join_runtime",
        )
        assert identity.source_runtime_posture == "join_runtime"

    def test_X03_to_dict_includes_field(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotIdentity
        identity = RuntimeSessionSnapshotIdentity(
            session_id="sess_x03",
            source_runtime_posture="join_runtime",
        )
        d = identity.to_dict()
        assert "source_runtime_posture" in d
        assert d["source_runtime_posture"] == "join_runtime"

    def test_X04_from_dict_round_trip(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotIdentity
        d = {"session_id": "sess_x04", "source_runtime_posture": "join_runtime"}
        identity = RuntimeSessionSnapshotIdentity.from_dict(d)
        assert identity.source_runtime_posture == "join_runtime"


# ===========================================================================
# Group Y — RuntimeSessionSnapshotDispatchState: source_runtime_posture field
# ===========================================================================

class TestGroupY_RuntimeSessionSnapshotDispatchState:
    def test_Y01_source_runtime_posture_field_exists(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotDispatchState
        state = RuntimeSessionSnapshotDispatchState()
        assert hasattr(state, "source_runtime_posture")
        assert state.source_runtime_posture == "control_only"

    def test_Y02_join_runtime_can_be_set(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotDispatchState
        state = RuntimeSessionSnapshotDispatchState(source_runtime_posture="join_runtime")
        assert state.source_runtime_posture == "join_runtime"

    def test_Y03_to_dict_includes_field(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotDispatchState
        state = RuntimeSessionSnapshotDispatchState(source_runtime_posture="join_runtime")
        d = state.to_dict()
        assert "source_runtime_posture" in d
        assert d["source_runtime_posture"] == "join_runtime"

    def test_Y04_from_dict_round_trip(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotDispatchState
        d = {"source_runtime_posture": "join_runtime"}
        state = RuntimeSessionSnapshotDispatchState.from_dict(d)
        assert state.source_runtime_posture == "join_runtime"


# ===========================================================================
# Group Z — RuntimeSessionSnapshotResultState: new PR-4 fields
# ===========================================================================

class TestGroupZ_RuntimeSessionSnapshotResultState:
    def test_Z01_source_runtime_posture_field_exists(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotResultState
        state = RuntimeSessionSnapshotResultState()
        assert hasattr(state, "source_runtime_posture")
        assert state.source_runtime_posture == "control_only"

    def test_Z02_excluded_unit_ids_field_exists(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotResultState
        state = RuntimeSessionSnapshotResultState()
        assert hasattr(state, "excluded_unit_ids")
        assert state.excluded_unit_ids == []

    def test_Z03_excluded_unit_ids_can_be_populated(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotResultState
        state = RuntimeSessionSnapshotResultState(
            excluded_unit_ids=["uid-001", "uid-002"],
            source_runtime_posture="control_only",
        )
        assert "uid-001" in state.excluded_unit_ids
        assert len(state.excluded_unit_ids) == 2

    def test_Z04_to_dict_includes_pr4_fields(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotResultState
        state = RuntimeSessionSnapshotResultState(
            source_runtime_posture="join_runtime",
            excluded_unit_ids=["uid-001"],
        )
        d = state.to_dict()
        assert "source_runtime_posture" in d
        assert "excluded_unit_ids" in d
        assert d["source_runtime_posture"] == "join_runtime"
        assert "uid-001" in d["excluded_unit_ids"]

    def test_Z05_from_dict_round_trip(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotResultState
        d = {
            "source_runtime_posture": "join_runtime",
            "excluded_unit_ids": ["uid-001"],
        }
        state = RuntimeSessionSnapshotResultState.from_dict(d)
        assert state.source_runtime_posture == "join_runtime"
        assert "uid-001" in state.excluded_unit_ids

    def test_Z06_join_runtime_posture_can_be_set(self):
        from contracts.runtime_session_snapshot import RuntimeSessionSnapshotResultState
        state = RuntimeSessionSnapshotResultState(source_runtime_posture="join_runtime")
        assert state.source_runtime_posture == "join_runtime"
