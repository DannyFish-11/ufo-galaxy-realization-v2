"""tests/test_pr_canonical_ownership_truth_chain.py
======================================================
PR-4V2 Canonical Ownership Truth Chain — Behavior Tests.

These tests validate that canonical ownership context from the Android
participant truth ingress boundary has been pushed into the deeper
truth / replay / recovery / provenance substrates.

They prove that ownership is NOT merely a label at the ingress edge — it
influences real behavior in:
- ``CanonicalSessionTruthRecord`` (deeper truth substrate)
- ``CanonicalSessionTruthRuntime`` admission gate (behavioral exclusion)
- ``TaskExecutionRecord`` (replay substrate)
- Recovery eligibility routing
- Provenance payload structure

Coverage groups
---------------
Group A — Module authority and sentinel chain reachability.
Group B — OwnershipBoundary enum completeness and string values.
Group C — extract_ownership_boundary: correct extraction from ownership_context.
Group D — admit_to_canonical_truth_substrate: canonical vs non-canonical gate.
Group E — CanonicalSessionTruthRecord.participant_ownership_boundary field:
          construction, to_dict, from_dict round-trip.
Group F — CanonicalSessionTruthRuntime admission gate (behavioral):
          non-canonical records blocked from ring buffer;
          canonical records admitted normally.
Group G — CanonicalSessionTruthSnapshot.non_canonical_rejected_count:
          counts incremented correctly by admission gate behavior.
Group H — record_session_truth() participant_ownership_boundary propagation:
          field flows into record and ring buffer gate.
Group I — TaskExecutionRecord.participant_ownership_boundary field:
          construction, to_dict, from_dict round-trip.
Group J — build_ownership_aware_session_truth_record(): ownership-aware record.
Group K — build_ownership_aware_replay_execution_record(): ownership copied
          from ingress context into replay record.
Group L — record_participant_truth_with_ownership(): end-to-end bridge test.
Group M — is_recovery_eligible(): ownership-gated recovery admission.
Group N — Non-canonical isolation test: fallback/divergence does not pollute
          canonical ring buffer; canonical ring buffer records remain canonical.
Group O — Provenance alignment: ownership_context appears in record metadata.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

try:
    from core.canonical_ownership_truth_bridge import (
        CANONICAL_OWNERSHIP_TRUTH_BRIDGE_AUTHORITY,
        CANONICAL_OWNERSHIP_TRUTH_BRIDGE_PR4V2_SENTINEL,
        NON_CANONICAL_TRUTH_EXCLUDED_FROM_CANONICAL_SUBSTRATE_POLICY,
        OWNERSHIP_AWARE_REPLAY_RECORD_POLICY,
        RECOVERY_ELIGIBILITY_REQUIRES_CANONICAL_OWNERSHIP_POLICY,
        OwnershipBoundary,
        admit_to_canonical_truth_substrate,
        build_ownership_aware_replay_execution_record,
        build_ownership_aware_session_truth_record,
        extract_ownership_boundary,
        is_recovery_eligible,
        record_participant_truth_with_ownership,
    )
    _BRIDGE_AVAILABLE = True
except ImportError:
    _BRIDGE_AVAILABLE = False

try:
    from core.canonical_session_truth import (
        CANONICAL_TRUTH_ADMITS_ONLY_CANONICALIZED_OWNERSHIP_POLICY,
        NON_CANONICAL_PARTICIPANT_TRUTH_ISOLATED_POLICY,
        PARTICIPANT_OWNERSHIP_BOUNDARY_FIELD_POLICY,
        CanonicalSessionTruthRecord,
        CanonicalSessionTruthRuntime,
        get_canonical_session_truth_runtime,
        record_session_truth,
        reset_canonical_session_truth_runtime,
    )
    _CST_AVAILABLE = True
except ImportError:
    _CST_AVAILABLE = False

try:
    from core.replay_foundation import (
        REPLAY_RECORD_CARRIES_OWNERSHIP_BOUNDARY_POLICY,
        TaskExecutionRecord,
        get_replay_foundation,
        reset_replay_foundation,
    )
    _REPLAY_AVAILABLE = True
except ImportError:
    _REPLAY_AVAILABLE = False

_SKIP_BRIDGE = pytest.mark.skipif(
    not _BRIDGE_AVAILABLE, reason="canonical_ownership_truth_bridge unavailable"
)
_SKIP_CST = pytest.mark.skipif(
    not _CST_AVAILABLE, reason="canonical_session_truth unavailable"
)
_SKIP_REPLAY = pytest.mark.skipif(
    not _REPLAY_AVAILABLE, reason="replay_foundation unavailable"
)
_SKIP_ALL = pytest.mark.skipif(
    not (_BRIDGE_AVAILABLE and _CST_AVAILABLE and _REPLAY_AVAILABLE),
    reason="one or more required modules unavailable",
)

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_ownership_context(
    ownership_status: str = "canonicalized",
    device_id: str = "dev-test",
    session_id: str = "sess-test",
    truth_kind: str = "cancel",
    divergence: bool = False,
) -> Dict[str, Any]:
    return {
        "truth_kind": truth_kind,
        "authority_scope": (
            "v2_canonical_orchestration"
            if ownership_status == "canonicalized"
            else "android_participant_local"
        ),
        "ownership_status": ownership_status,
        "participant_identity": device_id,
        "participant_identity_attached": bool(device_id),
        "participant_identity_divergence": divergence,
        "canonical_session_identity": {
            "conversation_session_id": "",
            "control_session_id": "",
            "runtime_attachment_session_id": session_id,
            "source_session_id": session_id,
            "device_id": device_id,
        },
    }


def _make_mock_outcome(
    ownership_status: str = "canonicalized",
    device_id: str = "dev-outcome",
    session_id: str = "sess-outcome",
) -> Any:
    """Build a minimal mock AndroidParticipantReconcileOutcome."""
    ctx = _make_ownership_context(
        ownership_status=ownership_status,
        device_id=device_id,
        session_id=session_id,
    )
    envelope = SimpleNamespace(
        session_id=session_id,
        trace_id=f"trace-{uuid.uuid4().hex[:8]}",
        device_id=device_id,
    )
    return SimpleNamespace(
        ownership_context=ctx,
        envelope=envelope,
        was_reconciled=(ownership_status == "canonicalized"),
    )


# ===========================================================================
# Group A — Module authority and sentinel chain reachability
# ===========================================================================


@_SKIP_BRIDGE
class TestGroupA_Authority:
    def test_a1_bridge_authority_sentinel_present(self) -> None:
        assert isinstance(CANONICAL_OWNERSHIP_TRUTH_BRIDGE_AUTHORITY, str)
        assert "CANONICAL_OWNERSHIP_TRUTH_BRIDGE" in CANONICAL_OWNERSHIP_TRUTH_BRIDGE_AUTHORITY
        assert "PR4V2" in CANONICAL_OWNERSHIP_TRUTH_BRIDGE_AUTHORITY

    def test_a2_non_canonical_excluded_policy_present(self) -> None:
        assert isinstance(NON_CANONICAL_TRUTH_EXCLUDED_FROM_CANONICAL_SUBSTRATE_POLICY, str)
        assert "participant_local_only" in NON_CANONICAL_TRUTH_EXCLUDED_FROM_CANONICAL_SUBSTRATE_POLICY
        assert "fallback_non_canonical" in NON_CANONICAL_TRUTH_EXCLUDED_FROM_CANONICAL_SUBSTRATE_POLICY
        assert "rejected_non_canonical" in NON_CANONICAL_TRUTH_EXCLUDED_FROM_CANONICAL_SUBSTRATE_POLICY

    def test_a3_replay_record_ownership_policy_present(self) -> None:
        assert isinstance(OWNERSHIP_AWARE_REPLAY_RECORD_POLICY, str)
        assert "participant_ownership_boundary" in OWNERSHIP_AWARE_REPLAY_RECORD_POLICY

    def test_a4_recovery_eligibility_policy_present(self) -> None:
        assert isinstance(RECOVERY_ELIGIBILITY_REQUIRES_CANONICAL_OWNERSHIP_POLICY, str)
        assert "canonicalized" in RECOVERY_ELIGIBILITY_REQUIRES_CANONICAL_OWNERSHIP_POLICY

    def test_a5_pr4v2_integration_sentinel_present(self) -> None:
        assert isinstance(CANONICAL_OWNERSHIP_TRUTH_BRIDGE_PR4V2_SENTINEL, str)
        assert "PR4V2" in CANONICAL_OWNERSHIP_TRUTH_BRIDGE_PR4V2_SENTINEL

    @_SKIP_CST
    def test_a6_cst_ownership_policy_sentinels_present(self) -> None:
        assert isinstance(CANONICAL_TRUTH_ADMITS_ONLY_CANONICALIZED_OWNERSHIP_POLICY, str)
        assert "canonicalized" in CANONICAL_TRUTH_ADMITS_ONLY_CANONICALIZED_OWNERSHIP_POLICY
        assert isinstance(PARTICIPANT_OWNERSHIP_BOUNDARY_FIELD_POLICY, str)
        assert isinstance(NON_CANONICAL_PARTICIPANT_TRUTH_ISOLATED_POLICY, str)

    @_SKIP_REPLAY
    def test_a7_replay_ownership_policy_sentinel_present(self) -> None:
        assert isinstance(REPLAY_RECORD_CARRIES_OWNERSHIP_BOUNDARY_POLICY, str)
        assert "participant_ownership_boundary" in REPLAY_RECORD_CARRIES_OWNERSHIP_BOUNDARY_POLICY


# ===========================================================================
# Group B — OwnershipBoundary enum completeness
# ===========================================================================


@_SKIP_BRIDGE
class TestGroupB_OwnershipBoundary:
    def test_b1_all_required_values_present(self) -> None:
        values = {b.value for b in OwnershipBoundary}
        assert "canonicalized" in values
        assert "participant_local_only" in values
        assert "fallback_non_canonical" in values
        assert "rejected_non_canonical" in values
        assert "" in values  # unset

    def test_b2_enum_members_are_strings(self) -> None:
        for member in OwnershipBoundary:
            assert isinstance(member.value, str)

    def test_b3_string_comparison_works(self) -> None:
        assert OwnershipBoundary.canonicalized == "canonicalized"
        assert OwnershipBoundary.fallback_non_canonical == "fallback_non_canonical"


# ===========================================================================
# Group C — extract_ownership_boundary
# ===========================================================================


@_SKIP_BRIDGE
class TestGroupC_ExtractOwnershipBoundary:
    def test_c1_extracts_canonicalized(self) -> None:
        ctx = _make_ownership_context("canonicalized")
        assert extract_ownership_boundary(ctx) == "canonicalized"

    def test_c2_extracts_participant_local_only(self) -> None:
        ctx = _make_ownership_context("participant_local_only")
        assert extract_ownership_boundary(ctx) == "participant_local_only"

    def test_c3_extracts_fallback_non_canonical(self) -> None:
        ctx = _make_ownership_context("fallback_non_canonical")
        assert extract_ownership_boundary(ctx) == "fallback_non_canonical"

    def test_c4_extracts_rejected_non_canonical(self) -> None:
        ctx = _make_ownership_context("rejected_non_canonical")
        assert extract_ownership_boundary(ctx) == "rejected_non_canonical"

    def test_c5_none_returns_empty(self) -> None:
        assert extract_ownership_boundary(None) == ""

    def test_c6_empty_dict_returns_empty(self) -> None:
        assert extract_ownership_boundary({}) == ""

    def test_c7_missing_ownership_status_key_returns_empty(self) -> None:
        assert extract_ownership_boundary({"authority_scope": "v2"}) == ""


# ===========================================================================
# Group D — admit_to_canonical_truth_substrate
# ===========================================================================


@_SKIP_BRIDGE
class TestGroupD_AdmitToCanonicalTruthSubstrate:
    def test_d1_canonicalized_is_admitted(self) -> None:
        assert admit_to_canonical_truth_substrate("canonicalized") is True

    def test_d2_empty_is_admitted_backward_compat(self) -> None:
        assert admit_to_canonical_truth_substrate("") is True

    def test_d3_participant_local_only_is_not_admitted(self) -> None:
        assert admit_to_canonical_truth_substrate("participant_local_only") is False

    def test_d4_fallback_non_canonical_is_not_admitted(self) -> None:
        assert admit_to_canonical_truth_substrate("fallback_non_canonical") is False

    def test_d5_rejected_non_canonical_is_not_admitted(self) -> None:
        assert admit_to_canonical_truth_substrate("rejected_non_canonical") is False

    def test_d6_unknown_value_is_admitted_by_default(self) -> None:
        # Unknown values should not accidentally block admission
        assert admit_to_canonical_truth_substrate("some_unknown_value") is True


# ===========================================================================
# Group E — CanonicalSessionTruthRecord.participant_ownership_boundary field
# ===========================================================================


@_SKIP_CST
class TestGroupE_CSTRecordOwnershipBoundaryField:
    def test_e1_field_defaults_to_empty(self) -> None:
        rec = CanonicalSessionTruthRecord()
        assert rec.participant_ownership_boundary == ""

    def test_e2_field_accepts_canonicalized(self) -> None:
        rec = CanonicalSessionTruthRecord(participant_ownership_boundary="canonicalized")
        assert rec.participant_ownership_boundary == "canonicalized"

    def test_e3_field_accepts_fallback_non_canonical(self) -> None:
        rec = CanonicalSessionTruthRecord(
            participant_ownership_boundary="fallback_non_canonical"
        )
        assert rec.participant_ownership_boundary == "fallback_non_canonical"

    def test_e4_to_dict_includes_participant_ownership_boundary(self) -> None:
        rec = CanonicalSessionTruthRecord(
            participant_ownership_boundary="rejected_non_canonical"
        )
        d = rec.to_dict()
        assert "participant_ownership_boundary" in d
        assert d["participant_ownership_boundary"] == "rejected_non_canonical"

    def test_e5_from_dict_round_trips_participant_ownership_boundary(self) -> None:
        rec = CanonicalSessionTruthRecord(
            session_id="sess-e5",
            participant_ownership_boundary="participant_local_only",
        )
        d = rec.to_dict()
        restored = CanonicalSessionTruthRecord.from_dict(d)
        assert restored.participant_ownership_boundary == "participant_local_only"

    def test_e6_from_dict_missing_field_defaults_empty(self) -> None:
        d = {"session_id": "sess-e6", "source_runtime_posture": "control_only"}
        rec = CanonicalSessionTruthRecord.from_dict(d)
        assert rec.participant_ownership_boundary == ""


# ===========================================================================
# Group F — CanonicalSessionTruthRuntime admission gate (behavioral)
# ===========================================================================


@_SKIP_CST
class TestGroupF_CSTRuntimeAdmissionGate:
    """Verify that the admission gate blocks non-canonical records from the ring buffer."""

    def setup_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def teardown_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def test_f1_canonicalized_record_is_admitted_to_ring_buffer(self) -> None:
        rt = CanonicalSessionTruthRuntime()
        rec = CanonicalSessionTruthRecord(
            session_id="sess-f1",
            participant_ownership_boundary="canonicalized",
        )
        rt.record(rec)
        snap = rt.snapshot()
        assert snap.total_records == 1
        assert snap.non_canonical_rejected_count == 0

    def test_f2_fallback_non_canonical_blocked_from_ring_buffer(self) -> None:
        rt = CanonicalSessionTruthRuntime()
        rec = CanonicalSessionTruthRecord(
            session_id="sess-f2",
            participant_ownership_boundary="fallback_non_canonical",
        )
        rt.record(rec)
        snap = rt.snapshot()
        # Ring buffer must NOT contain the fallback record
        assert snap.total_records == 0
        assert snap.non_canonical_rejected_count == 1

    def test_f3_participant_local_only_blocked_from_ring_buffer(self) -> None:
        rt = CanonicalSessionTruthRuntime()
        rec = CanonicalSessionTruthRecord(
            session_id="sess-f3",
            participant_ownership_boundary="participant_local_only",
        )
        rt.record(rec)
        snap = rt.snapshot()
        assert snap.total_records == 0
        assert snap.non_canonical_rejected_count == 1

    def test_f4_rejected_non_canonical_blocked_from_ring_buffer(self) -> None:
        rt = CanonicalSessionTruthRuntime()
        rec = CanonicalSessionTruthRecord(
            session_id="sess-f4",
            participant_ownership_boundary="rejected_non_canonical",
        )
        rt.record(rec)
        snap = rt.snapshot()
        assert snap.total_records == 0
        assert snap.non_canonical_rejected_count == 1

    def test_f5_empty_boundary_admitted_backward_compat(self) -> None:
        rt = CanonicalSessionTruthRuntime()
        rec = CanonicalSessionTruthRecord(
            session_id="sess-f5",
            participant_ownership_boundary="",
        )
        rt.record(rec)
        snap = rt.snapshot()
        assert snap.total_records == 1
        assert snap.non_canonical_rejected_count == 0

    def test_f6_mixed_records_only_canonical_in_ring_buffer(self) -> None:
        """Canonical and non-canonical records submitted together: only canonical in ring buffer."""
        rt = CanonicalSessionTruthRuntime()
        canonical = CanonicalSessionTruthRecord(
            session_id="sess-f6-canonical",
            participant_ownership_boundary="canonicalized",
        )
        fallback = CanonicalSessionTruthRecord(
            session_id="sess-f6-fallback",
            participant_ownership_boundary="fallback_non_canonical",
        )
        diverged = CanonicalSessionTruthRecord(
            session_id="sess-f6-diverged",
            participant_ownership_boundary="rejected_non_canonical",
        )
        rt.record(canonical)
        rt.record(fallback)
        rt.record(diverged)

        snap = rt.snapshot(max_recent=10)
        assert snap.total_records == 1
        assert snap.non_canonical_rejected_count == 2
        # Only canonical session appears in ring buffer
        session_ids = [r["session_id"] for r in snap.recent_records]
        assert "sess-f6-canonical" in session_ids
        assert "sess-f6-fallback" not in session_ids
        assert "sess-f6-diverged" not in session_ids


# ===========================================================================
# Group G — CanonicalSessionTruthSnapshot.non_canonical_rejected_count
# ===========================================================================


@_SKIP_CST
class TestGroupG_SnapshotNonCanonicalCount:
    def setup_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def teardown_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def test_g1_snapshot_has_non_canonical_rejected_count_field(self) -> None:
        rt = CanonicalSessionTruthRuntime()
        snap = rt.snapshot()
        assert hasattr(snap, "non_canonical_rejected_count")
        assert snap.non_canonical_rejected_count == 0

    def test_g2_count_increments_per_rejected_record(self) -> None:
        rt = CanonicalSessionTruthRuntime()
        for boundary in ("participant_local_only", "fallback_non_canonical", "rejected_non_canonical"):
            rt.record(CanonicalSessionTruthRecord(participant_ownership_boundary=boundary))
        snap = rt.snapshot()
        assert snap.non_canonical_rejected_count == 3

    def test_g3_snapshot_to_dict_includes_non_canonical_rejected_count(self) -> None:
        rt = CanonicalSessionTruthRuntime()
        rt.record(CanonicalSessionTruthRecord(participant_ownership_boundary="fallback_non_canonical"))
        snap = rt.snapshot()
        d = snap.to_dict()
        assert "non_canonical_rejected_count" in d
        assert d["non_canonical_rejected_count"] == 1


# ===========================================================================
# Group H — record_session_truth() participant_ownership_boundary propagation
# ===========================================================================


@_SKIP_CST
class TestGroupH_RecordSessionTruthOwnership:
    """Verify the admission gate works via CanonicalSessionTruthRuntime.record() directly.

    NOTE: The record_session_truth() module-level function requires pydantic
    (via merge_session_truth → contracts). These tests validate the same
    admission-gate behavior through the lower-level runtime API, which is
    what the bridge and downstream callers use.
    """

    def setup_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def teardown_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def test_h1_canonicalized_boundary_admits_record(self) -> None:
        rt = get_canonical_session_truth_runtime()
        rec = CanonicalSessionTruthRecord(
            session_id="sess-h1",
            participant_ownership_boundary="canonicalized",
        )
        rt.record(rec)
        snap = rt.snapshot()
        assert snap.total_records >= 1
        assert snap.non_canonical_rejected_count == 0

    def test_h2_fallback_boundary_blocks_record_from_ring_buffer(self) -> None:
        rt = get_canonical_session_truth_runtime()
        before_total = rt.snapshot().total_records

        rec = CanonicalSessionTruthRecord(
            session_id="sess-h2",
            participant_ownership_boundary="fallback_non_canonical",
        )
        rt.record(rec)
        assert rec.participant_ownership_boundary == "fallback_non_canonical"

        after_snap = rt.snapshot()
        # Ring buffer total must not have increased
        assert after_snap.total_records == before_total
        assert after_snap.non_canonical_rejected_count >= 1

    def test_h3_rejected_boundary_blocks_record(self) -> None:
        rt = get_canonical_session_truth_runtime()
        before_total = rt.snapshot().total_records

        rec = CanonicalSessionTruthRecord(
            session_id="sess-h3",
            participant_ownership_boundary="rejected_non_canonical",
        )
        rt.record(rec)
        after_snap = rt.snapshot()
        assert after_snap.total_records == before_total

    def test_h4_no_boundary_admits_record_backward_compat(self) -> None:
        rt = get_canonical_session_truth_runtime()
        before_total = rt.snapshot().total_records
        rec = CanonicalSessionTruthRecord(
            session_id="sess-h4",
            participant_ownership_boundary="",
        )
        rt.record(rec)
        assert rt.snapshot().total_records == before_total + 1


# ===========================================================================
# Group I — TaskExecutionRecord.participant_ownership_boundary field
# ===========================================================================


@_SKIP_REPLAY
class TestGroupI_ReplayRecordOwnershipBoundaryField:
    def test_i1_field_defaults_to_empty(self) -> None:
        rec = TaskExecutionRecord()
        assert rec.participant_ownership_boundary == ""

    def test_i2_field_accepts_canonicalized(self) -> None:
        rec = TaskExecutionRecord(
            task_id="task-i2",
            participant_ownership_boundary="canonicalized",
        )
        assert rec.participant_ownership_boundary == "canonicalized"

    def test_i3_field_accepts_fallback_non_canonical(self) -> None:
        rec = TaskExecutionRecord(
            task_id="task-i3",
            participant_ownership_boundary="fallback_non_canonical",
        )
        assert rec.participant_ownership_boundary == "fallback_non_canonical"

    def test_i4_to_dict_includes_participant_ownership_boundary(self) -> None:
        rec = TaskExecutionRecord(
            task_id="task-i4",
            participant_ownership_boundary="rejected_non_canonical",
        )
        d = rec.to_dict()
        assert "participant_ownership_boundary" in d
        assert d["participant_ownership_boundary"] == "rejected_non_canonical"

    def test_i5_from_dict_round_trips_participant_ownership_boundary(self) -> None:
        rec = TaskExecutionRecord(
            task_id="task-i5",
            participant_ownership_boundary="participant_local_only",
        )
        d = rec.to_dict()
        restored = TaskExecutionRecord.from_dict(d)
        assert restored.participant_ownership_boundary == "participant_local_only"

    def test_i6_from_dict_missing_field_defaults_empty(self) -> None:
        d = {"task_id": "task-i6"}
        rec = TaskExecutionRecord.from_dict(d)
        assert rec.participant_ownership_boundary == ""


# ===========================================================================
# Group J — build_ownership_aware_session_truth_record()
# ===========================================================================


@_SKIP_ALL
class TestGroupJ_BuildOwnershipAwareSessionTruthRecord:
    def setup_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def teardown_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def test_j1_canonical_ownership_context_produces_admitted_record(self) -> None:
        ctx = _make_ownership_context("canonicalized")
        rec = build_ownership_aware_session_truth_record(
            session_id="sess-j1",
            ownership_context=ctx,
        )
        assert rec.participant_ownership_boundary == "canonicalized"
        snap = get_canonical_session_truth_runtime().snapshot()
        assert snap.total_records >= 1

    def test_j2_fallback_ownership_context_produces_blocked_record(self) -> None:
        before_total = get_canonical_session_truth_runtime().snapshot().total_records
        ctx = _make_ownership_context("fallback_non_canonical")
        rec = build_ownership_aware_session_truth_record(
            session_id="sess-j2",
            ownership_context=ctx,
        )
        assert rec.participant_ownership_boundary == "fallback_non_canonical"
        after_total = get_canonical_session_truth_runtime().snapshot().total_records
        assert after_total == before_total  # not admitted

    def test_j3_metadata_includes_ownership_context(self) -> None:
        ctx = _make_ownership_context("canonicalized", device_id="dev-j3")
        rec = build_ownership_aware_session_truth_record(
            session_id="sess-j3",
            ownership_context=ctx,
        )
        meta = rec.metadata
        assert "ownership_context" in meta
        assert meta["ownership_context"].get("participant_identity") == "dev-j3"

    def test_j4_metadata_includes_admission_eligible_flag(self) -> None:
        ctx = _make_ownership_context("canonicalized")
        rec = build_ownership_aware_session_truth_record(
            session_id="sess-j4",
            ownership_context=ctx,
        )
        assert rec.metadata.get("ownership_admission_eligible") is True

    def test_j5_non_canonical_metadata_admission_eligible_false(self) -> None:
        ctx = _make_ownership_context("rejected_non_canonical")
        rec = build_ownership_aware_session_truth_record(
            session_id="sess-j5",
            ownership_context=ctx,
        )
        assert rec.metadata.get("ownership_admission_eligible") is False

    def test_j6_explicit_boundary_overrides_context(self) -> None:
        ctx = _make_ownership_context("canonicalized")  # would be admitted
        before_total = get_canonical_session_truth_runtime().snapshot().total_records
        rec = build_ownership_aware_session_truth_record(
            session_id="sess-j6",
            ownership_context=ctx,
            participant_ownership_boundary="fallback_non_canonical",  # explicit override
        )
        assert rec.participant_ownership_boundary == "fallback_non_canonical"
        after_total = get_canonical_session_truth_runtime().snapshot().total_records
        assert after_total == before_total  # blocked by explicit override


# ===========================================================================
# Group K — build_ownership_aware_replay_execution_record()
# ===========================================================================


@_SKIP_BRIDGE
@_SKIP_REPLAY
class TestGroupK_BuildOwnershipAwareReplayRecord:
    def test_k1_canonicalized_context_sets_boundary_on_replay_record(self) -> None:
        base = TaskExecutionRecord(task_id="task-k1")
        ctx = _make_ownership_context("canonicalized")
        result = build_ownership_aware_replay_execution_record(base, ownership_context=ctx)
        assert result.participant_ownership_boundary == "canonicalized"
        assert result.task_id == "task-k1"

    def test_k2_fallback_context_sets_boundary_on_replay_record(self) -> None:
        base = TaskExecutionRecord(task_id="task-k2")
        ctx = _make_ownership_context("fallback_non_canonical")
        result = build_ownership_aware_replay_execution_record(base, ownership_context=ctx)
        assert result.participant_ownership_boundary == "fallback_non_canonical"

    def test_k3_rejected_context_sets_boundary_on_replay_record(self) -> None:
        base = TaskExecutionRecord(task_id="task-k3", session_id="sess-k3")
        ctx = _make_ownership_context("rejected_non_canonical")
        result = build_ownership_aware_replay_execution_record(base, ownership_context=ctx)
        assert result.participant_ownership_boundary == "rejected_non_canonical"
        assert result.session_id == "sess-k3"

    def test_k4_explicit_boundary_overrides_context(self) -> None:
        base = TaskExecutionRecord(task_id="task-k4")
        ctx = _make_ownership_context("canonicalized")
        result = build_ownership_aware_replay_execution_record(
            base,
            ownership_context=ctx,
            participant_ownership_boundary="participant_local_only",
        )
        assert result.participant_ownership_boundary == "participant_local_only"

    def test_k5_no_context_leaves_boundary_empty(self) -> None:
        base = TaskExecutionRecord(task_id="task-k5")
        result = build_ownership_aware_replay_execution_record(base)
        assert result.participant_ownership_boundary == ""

    def test_k6_base_record_is_not_mutated(self) -> None:
        base = TaskExecutionRecord(task_id="task-k6")
        ctx = _make_ownership_context("canonicalized")
        build_ownership_aware_replay_execution_record(base, ownership_context=ctx)
        assert base.participant_ownership_boundary == ""  # original unchanged

    def test_k7_round_trip_preserves_other_fields(self) -> None:
        base = TaskExecutionRecord(
            task_id="task-k7",
            session_id="sess-k7",
            trace_id="trace-k7",
            final_lifecycle="completed",
            success=True,
        )
        ctx = _make_ownership_context("canonicalized")
        result = build_ownership_aware_replay_execution_record(base, ownership_context=ctx)
        assert result.task_id == "task-k7"
        assert result.session_id == "sess-k7"
        assert result.trace_id == "trace-k7"
        assert result.final_lifecycle == "completed"
        assert result.success is True
        assert result.participant_ownership_boundary == "canonicalized"


# ===========================================================================
# Group L — record_participant_truth_with_ownership() end-to-end
# ===========================================================================


@_SKIP_ALL
class TestGroupL_RecordParticipantTruthWithOwnership:
    def setup_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def teardown_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def test_l1_canonicalized_outcome_produces_admitted_record(self) -> None:
        outcome = _make_mock_outcome("canonicalized", session_id="sess-l1")
        rec = record_participant_truth_with_ownership(outcome)
        assert rec.participant_ownership_boundary == "canonicalized"
        snap = get_canonical_session_truth_runtime().snapshot()
        assert snap.total_records >= 1

    def test_l2_fallback_outcome_produces_blocked_record(self) -> None:
        before_total = get_canonical_session_truth_runtime().snapshot().total_records
        outcome = _make_mock_outcome("fallback_non_canonical", session_id="sess-l2")
        rec = record_participant_truth_with_ownership(outcome)
        assert rec.participant_ownership_boundary == "fallback_non_canonical"
        after_total = get_canonical_session_truth_runtime().snapshot().total_records
        assert after_total == before_total  # not admitted

    def test_l3_rejected_outcome_does_not_enter_canonical_ring_buffer(self) -> None:
        before_total = get_canonical_session_truth_runtime().snapshot().total_records
        outcome = _make_mock_outcome("rejected_non_canonical", session_id="sess-l3")
        record_participant_truth_with_ownership(outcome)
        after_snap = get_canonical_session_truth_runtime().snapshot()
        assert after_snap.total_records == before_total
        assert after_snap.non_canonical_rejected_count >= 1

    def test_l4_session_id_propagated_from_envelope(self) -> None:
        outcome = _make_mock_outcome("canonicalized", session_id="sess-l4-specific")
        rec = record_participant_truth_with_ownership(outcome)
        assert rec.session_id == "sess-l4-specific"

    def test_l5_ownership_context_in_record_metadata(self) -> None:
        outcome = _make_mock_outcome("canonicalized", device_id="dev-l5", session_id="sess-l5")
        rec = record_participant_truth_with_ownership(outcome)
        assert rec.metadata.get("ownership_context", {}).get("participant_identity") == "dev-l5"


# ===========================================================================
# Group M — is_recovery_eligible()
# ===========================================================================


@_SKIP_BRIDGE
class TestGroupM_RecoveryEligibility:
    def test_m1_canonicalized_is_recovery_eligible(self) -> None:
        assert is_recovery_eligible("canonicalized") is True

    def test_m2_empty_is_recovery_eligible_backward_compat(self) -> None:
        assert is_recovery_eligible("") is True

    def test_m3_participant_local_only_not_recovery_eligible(self) -> None:
        assert is_recovery_eligible("participant_local_only") is False

    def test_m4_fallback_non_canonical_not_recovery_eligible(self) -> None:
        assert is_recovery_eligible("fallback_non_canonical") is False

    def test_m5_rejected_non_canonical_not_recovery_eligible(self) -> None:
        assert is_recovery_eligible("rejected_non_canonical") is False

    def test_m6_recovery_eligibility_consistent_with_admission_gate(self) -> None:
        for boundary in (
            "canonicalized",
            "participant_local_only",
            "fallback_non_canonical",
            "rejected_non_canonical",
            "",
        ):
            assert is_recovery_eligible(boundary) == admit_to_canonical_truth_substrate(boundary), (
                f"is_recovery_eligible and admit_to_canonical_truth_substrate "
                f"inconsistent for boundary={boundary!r}"
            )


# ===========================================================================
# Group N — Non-canonical isolation test
# ===========================================================================


@_SKIP_ALL
class TestGroupN_NonCanonicalIsolation:
    """Verify fallback/divergence cannot pollute canonical ring buffer even under volume."""

    def setup_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def teardown_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def test_n1_only_canonical_records_appear_in_snapshot(self) -> None:
        rt = CanonicalSessionTruthRuntime()
        canonical_sessions = []
        for i in range(5):
            sid = f"sess-n1-canonical-{i}"
            canonical_sessions.append(sid)
            rt.record(CanonicalSessionTruthRecord(
                session_id=sid,
                participant_ownership_boundary="canonicalized",
            ))
        for boundary in ("fallback_non_canonical", "participant_local_only", "rejected_non_canonical"):
            rt.record(CanonicalSessionTruthRecord(
                session_id=f"sess-n1-blocked-{boundary}",
                participant_ownership_boundary=boundary,
            ))

        snap = rt.snapshot(max_recent=20)
        assert snap.total_records == 5
        assert snap.non_canonical_rejected_count == 3

        recorded_sessions = {r["session_id"] for r in snap.recent_records}
        for sid in canonical_sessions:
            assert sid in recorded_sessions, f"Canonical session {sid} missing from snapshot"
        for boundary in ("fallback_non_canonical", "participant_local_only", "rejected_non_canonical"):
            assert f"sess-n1-blocked-{boundary}" not in recorded_sessions, (
                f"Non-canonical session for {boundary} appeared in canonical snapshot"
            )

    def test_n2_divergence_origin_does_not_pollute_canonical_substrate(self) -> None:
        """Rejected/diverged participant records must not increase canonical record count."""
        rt = CanonicalSessionTruthRuntime()
        # Submit a legitimate canonical record
        rt.record(CanonicalSessionTruthRecord(
            session_id="sess-n2-canonical",
            participant_ownership_boundary="canonicalized",
        ))
        # Simulate diverged participant attempting to inject truth
        rt.record(CanonicalSessionTruthRecord(
            session_id="sess-n2-diverged",
            participant_ownership_boundary="rejected_non_canonical",
        ))
        snap = rt.snapshot()
        assert snap.total_records == 1
        assert snap.non_canonical_rejected_count == 1

    def test_n3_bridge_non_canonical_rejection_is_audited_not_silenced(self) -> None:
        """Non-canonical rejections must be counted (visible), not silently dropped."""
        rt = CanonicalSessionTruthRuntime()
        rt.record(CanonicalSessionTruthRecord(
            session_id="sess-n3-fallback",
            participant_ownership_boundary="fallback_non_canonical",
        ))
        snap = rt.snapshot()
        # Rejection must be visible in the snapshot
        assert snap.non_canonical_rejected_count > 0, (
            "Non-canonical rejection must be counted, not silenced"
        )


# ===========================================================================
# Group O — Provenance alignment
# ===========================================================================


@_SKIP_ALL
class TestGroupO_ProvenanceAlignment:
    """Verify ownership context appears in deeper truth record metadata (provenance)."""

    def setup_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def teardown_method(self) -> None:
        reset_canonical_session_truth_runtime()

    def test_o1_ownership_context_preserved_in_canonical_record_metadata(self) -> None:
        ctx = _make_ownership_context(
            "canonicalized",
            device_id="dev-o1",
            session_id="sess-o1",
        )
        rec = build_ownership_aware_session_truth_record(
            session_id="sess-o1",
            ownership_context=ctx,
        )
        meta = rec.metadata
        assert "ownership_context" in meta
        assert meta["ownership_context"]["ownership_status"] == "canonicalized"
        assert meta["ownership_context"]["participant_identity"] == "dev-o1"

    def test_o2_participant_ownership_boundary_in_record_to_dict(self) -> None:
        ctx = _make_ownership_context("canonicalized")
        rec = build_ownership_aware_session_truth_record(
            session_id="sess-o2",
            ownership_context=ctx,
        )
        d = rec.to_dict()
        assert d.get("participant_ownership_boundary") == "canonicalized"

    def test_o3_replay_record_provenance_carries_ownership_boundary(self) -> None:
        base = TaskExecutionRecord(
            task_id="task-o3",
            session_id="sess-o3",
            trace_id="trace-o3",
        )
        ctx = _make_ownership_context("canonicalized", device_id="dev-o3", session_id="sess-o3")
        result = build_ownership_aware_replay_execution_record(base, ownership_context=ctx)
        d = result.to_dict()
        assert d.get("participant_ownership_boundary") == "canonicalized"
        assert d.get("task_id") == "task-o3"

    def test_o4_non_canonical_replay_record_carries_non_canonical_boundary(self) -> None:
        base = TaskExecutionRecord(task_id="task-o4")
        ctx = _make_ownership_context("fallback_non_canonical")
        result = build_ownership_aware_replay_execution_record(base, ownership_context=ctx)
        assert result.participant_ownership_boundary == "fallback_non_canonical"
        # This replay record's ownership boundary signals it should not be used
        # in canonical recovery paths
        assert not is_recovery_eligible(result.participant_ownership_boundary)

    def test_o5_canonical_record_to_dict_authority_chain_consistent(self) -> None:
        rec = CanonicalSessionTruthRecord(
            session_id="sess-o5",
            participant_ownership_boundary="canonicalized",
        )
        d = rec.to_dict()
        assert d["participant_ownership_boundary"] == "canonicalized"
        assert "authority" in d  # canonical authority preserved
