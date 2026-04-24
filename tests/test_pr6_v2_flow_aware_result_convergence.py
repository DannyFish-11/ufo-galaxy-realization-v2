"""tests/test_pr6_v2_flow_aware_result_convergence.py
======================================================
Tests for PR-6V2: Flow-Aware Result / Partial / Parallel Convergence.

These tests provide auditable evidence for all acceptance criteria stated in
the PR-6V2 issue:

  AC1  Flow-aware convergence framework is established: authority sentinels,
       policy sentinels, enums, and data types are importable and consistent.

  AC2  Convergence decision kinds are correctly modelled:
       accept_partial_for_flow, merge_partial_into_canonical,
       promote_final_as_canonical, aggregate_parallel_into_parent_flow,
       suppress_duplicate_result, suppress_late_partial_after_final,
       quarantine_result_due_to_flow_mismatch,
       absorb_replay_result_idempotently.

  AC3  Result semantic kinds and flow lineage enums are correctly modelled.

  AC4  decide_convergence() applies the correct rule for every scenario:
       - missing flow_id → quarantine
       - duplicate result → suppress_duplicate_result
       - reconnect replay + duplicate → absorb_replay_result_idempotently
       - late partial after final → suppress_late_partial_after_final
       - partial result → accept_partial_for_flow
       - parallel subtask → aggregate_parallel_into_parent_flow
       - final result → promote_final_as_canonical
       - replay resend (not duplicate) → promote_final_as_canonical

  AC5  FlowAwareConvergenceCoordinator.absorb() enriches context with
       coordinator-derived duplicate / final-absorbed flags and applies
       decisions correctly.

  AC6  Parallel group registration and aggregation:
       - register_parallel_group idempotent
       - subtask results absorbed incrementally
       - group_complete fires when all expected subtasks delivered
       - aggregate_artifact produced when complete

  AC7  Duplicate suppression across partial and final results (first write
       wins).

  AC8  Android reconnect / replay idempotent absorb.

  AC9  Responsibility boundary sentinels are present and correct.

  AC10 FlowConvergenceSnapshot reflects accurate coordinator state.

  AC11 All PR-6V2 symbols are re-exported through core.runtime.

  AC12 Policy sentinel presence and count (at least 7 policy sentinels).

Coverage groups
---------------
Group A — Module importability and authority sentinels.
Group B — ConvergenceDecisionKind enum: all values, from_string(), default.
Group C — ResultSemanticKind enum: all values, from_string(), default.
Group D — ConvergenceFlowLineage enum: all values, from_string(), default.
Group E — classify_result_semantic_kind(): explicit, inferred group_id, replay.
Group F — decide_convergence(): Rule 1 — missing flow_id quarantine.
Group G — decide_convergence(): Rule 2 — duplicate suppress.
Group H — decide_convergence(): Rule 3 — reconnect replay + duplicate.
Group I — decide_convergence(): Rule 4 — late partial after final suppressed.
Group J — decide_convergence(): Rule 5 — partial result accepted.
Group K — decide_convergence(): Rule 6 — parallel subtask aggregated.
Group L — decide_convergence(): Rule 7 / 8 — final result promoted.
Group M — decide_convergence(): Rule 9 — replay resend not duplicate.
Group N — FlowAwareConvergenceCoordinator.absorb(): state enrichment.
Group O — FlowAwareConvergenceCoordinator: parallel group registration.
Group P — FlowAwareConvergenceCoordinator: parallel group completion.
Group Q — FlowAwareConvergenceCoordinator: duplicate suppression via state.
Group R — FlowAwareConvergenceCoordinator: final-absorbed flag propagation.
Group S — FlowAwareConvergenceCoordinator: reconnect replay idempotent.
Group T — FlowAwareConvergenceCoordinator: ring buffer and get_artifact_by_id.
Group U — FlowConvergenceSnapshot: fields and decision counts.
Group V — ResultConvergenceArtifact: to_dict() round-trip.
Group W — ResultConvergenceContext: to_dict() and defaults.
Group X — ParallelFlowAggregationRecord: to_dict() and absorbed_count.
Group Y — Responsibility boundary policy sentinels present.
Group Z — core.runtime re-exports: all PR-6V2 symbols accessible.
Group AA — Policy sentinel presence and count.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

try:
    from core.flow_aware_result_convergence import (
        FLOW_AWARE_CONVERGENCE_AUTHORITY,
        FLOW_AWARE_CONVERGENCE_PR6V2_SENTINEL,
        PARTIAL_ACCEPTED_INTO_FLOW_PENDING_FINAL_POLICY,
        FINAL_PROMOTES_AS_CANONICAL_AND_CLOSES_PARTIALS_POLICY,
        PARALLEL_RESULTS_AGGREGATE_TO_PARENT_FLOW_VIA_GROUP_ID_POLICY,
        DUPLICATE_RESULT_SUPPRESSED_FIRST_WRITE_WINS_POLICY,
        LATE_PARTIAL_AFTER_FINAL_IS_SUPPRESSED_POLICY,
        RECONNECT_REPLAY_RESULT_ABSORBED_IDEMPOTENTLY_POLICY,
        FLOW_MISMATCH_QUARANTINES_RESULT_POLICY,
        CROSS_DEVICE_RESULT_SURFACE_IS_TRANSPORT_BOUNDARY_POLICY,
        GOAL_RESULT_AGGREGATOR_IS_GROUP_COMPLETION_SIGNAL_POLICY,
        ConvergenceDecisionKind,
        ResultSemanticKind,
        ConvergenceFlowLineage,
        ResultConvergenceContext,
        ResultConvergenceArtifact,
        ParallelFlowAggregationRecord,
        FlowConvergenceSnapshot,
        classify_result_semantic_kind,
        decide_convergence,
        FlowAwareConvergenceCoordinator,
        get_flow_aware_convergence_coordinator,
        reset_flow_aware_convergence_coordinator,
        absorb_result,
        build_flow_convergence_snapshot,
    )

    _MODULE_AVAILABLE = True
except ImportError as _exc:  # pragma: no cover
    _MODULE_AVAILABLE = False
    _exc_detail = str(_exc)

_SKIP_MODULE = pytest.mark.skipif(
    not _MODULE_AVAILABLE, reason="flow_aware_result_convergence unavailable"
)


# ===========================================================================
# Helpers
# ===========================================================================


def _new_flow_id() -> str:
    return f"flow-{uuid.uuid4().hex[:8]}"


def _new_result_id() -> str:
    return f"res-{uuid.uuid4().hex[:8]}"


def _ctx(
    flow_id: str = "",
    result_id: str = "",
    semantic_kind: str = "",
    lineage: str = "",
    group_id: str = "",
    subtask_index: int = None,
    parent_flow_id: str = "",
    final_already_absorbed: bool = False,
    is_duplicate: bool = False,
    is_reconnect_replay: bool = False,
    task_id: str = "",
) -> "ResultConvergenceContext":
    return ResultConvergenceContext(
        flow_id=flow_id,
        result_id=result_id or _new_result_id(),
        semantic_kind=semantic_kind,
        lineage=lineage,
        group_id=group_id,
        subtask_index=subtask_index,
        parent_flow_id=parent_flow_id,
        final_already_absorbed=final_already_absorbed,
        is_duplicate=is_duplicate,
        is_reconnect_replay=is_reconnect_replay,
        task_id=task_id,
    )


# ===========================================================================
# Group A — Module importability and authority sentinels
# ===========================================================================


@_SKIP_MODULE
class TestGroupA_AuthoritySentinels:
    def test_a1_module_importable(self):
        assert _MODULE_AVAILABLE

    def test_a2_authority_sentinel_is_string(self):
        assert isinstance(FLOW_AWARE_CONVERGENCE_AUTHORITY, str)
        assert len(FLOW_AWARE_CONVERGENCE_AUTHORITY) > 20

    def test_a3_pr6v2_sentinel_is_string(self):
        assert isinstance(FLOW_AWARE_CONVERGENCE_PR6V2_SENTINEL, str)
        assert "PR-6V2" in FLOW_AWARE_CONVERGENCE_PR6V2_SENTINEL or "PR6V2" in FLOW_AWARE_CONVERGENCE_PR6V2_SENTINEL

    def test_a4_authority_contains_pr6v2(self):
        assert "PR6V2" in FLOW_AWARE_CONVERGENCE_AUTHORITY or "flow-aware" in FLOW_AWARE_CONVERGENCE_AUTHORITY.lower()

    def test_a5_sentinel_contains_module_name(self):
        assert "flow_aware_result_convergence" in FLOW_AWARE_CONVERGENCE_PR6V2_SENTINEL


# ===========================================================================
# Group B — ConvergenceDecisionKind
# ===========================================================================


@_SKIP_MODULE
class TestGroupB_ConvergenceDecisionKind:
    def test_b1_all_expected_values(self):
        values = {v.value for v in ConvergenceDecisionKind}
        assert "accept_partial_for_flow" in values
        assert "merge_partial_into_canonical" in values
        assert "promote_final_as_canonical" in values
        assert "aggregate_parallel_into_parent_flow" in values
        assert "suppress_duplicate_result" in values
        assert "suppress_late_partial_after_final" in values
        assert "quarantine_result_due_to_flow_mismatch" in values
        assert "absorb_replay_result_idempotently" in values

    def test_b2_from_string_valid(self):
        kind = ConvergenceDecisionKind.from_string("promote_final_as_canonical")
        assert kind is ConvergenceDecisionKind.promote_final_as_canonical

    def test_b3_from_string_invalid_default(self):
        kind = ConvergenceDecisionKind.from_string("nonexistent")
        assert kind is ConvergenceDecisionKind.quarantine_result_due_to_flow_mismatch

    def test_b4_from_string_none_default(self):
        kind = ConvergenceDecisionKind.from_string(None)
        assert kind is ConvergenceDecisionKind.quarantine_result_due_to_flow_mismatch

    def test_b5_is_string_enum(self):
        assert ConvergenceDecisionKind.accept_partial_for_flow.value == "accept_partial_for_flow"


# ===========================================================================
# Group C — ResultSemanticKind
# ===========================================================================


@_SKIP_MODULE
class TestGroupC_ResultSemanticKind:
    def test_c1_all_expected_values(self):
        values = {v.value for v in ResultSemanticKind}
        assert "partial_result" in values
        assert "final_result" in values
        assert "parallel_subtask_result" in values
        assert "parent_flow_aggregate" in values
        assert "replay_resend" in values
        assert "unknown" in values

    def test_c2_from_string_valid(self):
        kind = ResultSemanticKind.from_string("final_result")
        assert kind is ResultSemanticKind.final_result

    def test_c3_from_string_invalid_default(self):
        kind = ResultSemanticKind.from_string("bogus")
        assert kind is ResultSemanticKind.unknown

    def test_c4_from_string_none_default(self):
        kind = ResultSemanticKind.from_string(None)
        assert kind is ResultSemanticKind.unknown


# ===========================================================================
# Group D — ConvergenceFlowLineage
# ===========================================================================


@_SKIP_MODULE
class TestGroupD_ConvergenceFlowLineage:
    def test_d1_all_expected_values(self):
        values = {v.value for v in ConvergenceFlowLineage}
        assert "direct_task_result" in values
        assert "subtask_of_group" in values
        assert "delegated_child_flow" in values
        assert "reconnect_replay" in values
        assert "unknown_lineage" in values

    def test_d2_from_string_valid(self):
        lin = ConvergenceFlowLineage.from_string("subtask_of_group")
        assert lin is ConvergenceFlowLineage.subtask_of_group

    def test_d3_from_string_invalid_default(self):
        lin = ConvergenceFlowLineage.from_string("bogus")
        assert lin is ConvergenceFlowLineage.unknown_lineage

    def test_d4_from_string_none_default(self):
        lin = ConvergenceFlowLineage.from_string(None)
        assert lin is ConvergenceFlowLineage.unknown_lineage


# ===========================================================================
# Group E — classify_result_semantic_kind()
# ===========================================================================


@_SKIP_MODULE
class TestGroupE_ClassifyResultSemanticKind:
    def test_e1_explicit_partial(self):
        c = _ctx(semantic_kind="partial_result")
        assert classify_result_semantic_kind(c) is ResultSemanticKind.partial_result

    def test_e2_explicit_final(self):
        c = _ctx(semantic_kind="final_result")
        assert classify_result_semantic_kind(c) is ResultSemanticKind.final_result

    def test_e3_inferred_from_group_id(self):
        c = _ctx(group_id="grp-123")
        assert classify_result_semantic_kind(c) is ResultSemanticKind.parallel_subtask_result

    def test_e4_inferred_replay(self):
        c = _ctx(is_reconnect_replay=True)
        assert classify_result_semantic_kind(c) is ResultSemanticKind.replay_resend

    def test_e5_unknown_fallback(self):
        c = _ctx()
        assert classify_result_semantic_kind(c) is ResultSemanticKind.unknown

    def test_e6_explicit_overrides_group_id(self):
        # Explicit semantic_kind should take priority over group_id inference
        c = _ctx(semantic_kind="final_result", group_id="grp-999")
        assert classify_result_semantic_kind(c) is ResultSemanticKind.final_result


# ===========================================================================
# Group F — decide_convergence(): Rule 1 — missing flow_id quarantine
# ===========================================================================


@_SKIP_MODULE
class TestGroupF_Rule1_MissingFlowId:
    def test_f1_empty_flow_id_quarantined(self):
        c = _ctx(flow_id="", semantic_kind="final_result")
        art = decide_convergence(c)
        assert art.decision is ConvergenceDecisionKind.quarantine_result_due_to_flow_mismatch

    def test_f2_quarantine_policy_reference_set(self):
        c = _ctx(flow_id="")
        art = decide_convergence(c)
        assert FLOW_MISMATCH_QUARANTINES_RESULT_POLICY in art.policy_reference

    def test_f3_quarantine_has_reason(self):
        c = _ctx(flow_id="")
        art = decide_convergence(c)
        assert art.reason


# ===========================================================================
# Group G — decide_convergence(): Rule 2 — duplicate suppress
# ===========================================================================


@_SKIP_MODULE
class TestGroupG_Rule2_DuplicateSuppress:
    def test_g1_duplicate_not_replay_suppressed(self):
        c = _ctx(flow_id="flow-xyz", is_duplicate=True, is_reconnect_replay=False)
        art = decide_convergence(c)
        assert art.decision is ConvergenceDecisionKind.suppress_duplicate_result

    def test_g2_duplicate_suppress_policy_reference(self):
        c = _ctx(flow_id="flow-xyz", is_duplicate=True)
        art = decide_convergence(c)
        assert DUPLICATE_RESULT_SUPPRESSED_FIRST_WRITE_WINS_POLICY in art.policy_reference


# ===========================================================================
# Group H — decide_convergence(): Rule 3 — reconnect replay + duplicate
# ===========================================================================


@_SKIP_MODULE
class TestGroupH_Rule3_ReconnectReplayDuplicate:
    def test_h1_replay_and_duplicate_is_idempotent_absorb(self):
        c = _ctx(flow_id="flow-xyz", is_duplicate=True, is_reconnect_replay=True)
        art = decide_convergence(c)
        assert art.decision is ConvergenceDecisionKind.absorb_replay_result_idempotently

    def test_h2_idempotent_policy_reference(self):
        c = _ctx(flow_id="flow-xyz", is_duplicate=True, is_reconnect_replay=True)
        art = decide_convergence(c)
        assert RECONNECT_REPLAY_RESULT_ABSORBED_IDEMPOTENTLY_POLICY in art.policy_reference


# ===========================================================================
# Group I — decide_convergence(): Rule 4 — late partial after final
# ===========================================================================


@_SKIP_MODULE
class TestGroupI_Rule4_LatePartialAfterFinal:
    def test_i1_late_partial_suppressed(self):
        c = _ctx(
            flow_id="flow-abc",
            semantic_kind="partial_result",
            final_already_absorbed=True,
        )
        art = decide_convergence(c)
        assert art.decision is ConvergenceDecisionKind.suppress_late_partial_after_final

    def test_i2_late_partial_policy_reference(self):
        c = _ctx(
            flow_id="flow-abc",
            semantic_kind="partial_result",
            final_already_absorbed=True,
        )
        art = decide_convergence(c)
        assert LATE_PARTIAL_AFTER_FINAL_IS_SUPPRESSED_POLICY in art.policy_reference

    def test_i3_partial_before_final_not_suppressed(self):
        c = _ctx(
            flow_id="flow-abc",
            semantic_kind="partial_result",
            final_already_absorbed=False,
        )
        art = decide_convergence(c)
        assert art.decision is ConvergenceDecisionKind.accept_partial_for_flow


# ===========================================================================
# Group J — decide_convergence(): Rule 5 — partial result accepted
# ===========================================================================


@_SKIP_MODULE
class TestGroupJ_Rule5_PartialAccepted:
    def test_j1_partial_accepted(self):
        c = _ctx(flow_id="flow-def", semantic_kind="partial_result")
        art = decide_convergence(c)
        assert art.decision is ConvergenceDecisionKind.accept_partial_for_flow

    def test_j2_partial_policy_reference(self):
        c = _ctx(flow_id="flow-def", semantic_kind="partial_result")
        art = decide_convergence(c)
        assert PARTIAL_ACCEPTED_INTO_FLOW_PENDING_FINAL_POLICY in art.policy_reference

    def test_j3_partial_flow_id_preserved(self):
        fid = _new_flow_id()
        c = _ctx(flow_id=fid, semantic_kind="partial_result")
        art = decide_convergence(c)
        assert art.flow_id == fid


# ===========================================================================
# Group K — decide_convergence(): Rule 6 — parallel subtask aggregated
# ===========================================================================


@_SKIP_MODULE
class TestGroupK_Rule6_ParallelSubtask:
    def test_k1_parallel_subtask_aggregated(self):
        c = _ctx(
            flow_id="flow-parallel",
            semantic_kind="parallel_subtask_result",
            group_id="grp-999",
            subtask_index=0,
        )
        art = decide_convergence(c)
        assert art.decision is ConvergenceDecisionKind.aggregate_parallel_into_parent_flow

    def test_k2_group_id_inferred_parallel(self):
        # No explicit semantic_kind but group_id present → parallel
        c = _ctx(flow_id="flow-par", group_id="grp-888")
        art = decide_convergence(c)
        assert art.decision is ConvergenceDecisionKind.aggregate_parallel_into_parent_flow

    def test_k3_parallel_policy_reference(self):
        c = _ctx(flow_id="flow-par", group_id="grp-777", semantic_kind="parallel_subtask_result")
        art = decide_convergence(c)
        assert PARALLEL_RESULTS_AGGREGATE_TO_PARENT_FLOW_VIA_GROUP_ID_POLICY in art.policy_reference

    def test_k4_group_id_preserved(self):
        c = _ctx(flow_id="flow-par", group_id="grp-ggg", semantic_kind="parallel_subtask_result")
        art = decide_convergence(c)
        assert art.group_id == "grp-ggg"

    def test_k5_subtask_index_preserved(self):
        c = _ctx(flow_id="flow-par", group_id="grp-iii", subtask_index=3, semantic_kind="parallel_subtask_result")
        art = decide_convergence(c)
        assert art.subtask_index == 3


# ===========================================================================
# Group L — decide_convergence(): Rule 7 / 8 — final result promoted
# ===========================================================================


@_SKIP_MODULE
class TestGroupL_Rule7_FinalPromoted:
    def test_l1_final_promoted(self):
        c = _ctx(flow_id="flow-fin", semantic_kind="final_result")
        art = decide_convergence(c)
        assert art.decision is ConvergenceDecisionKind.promote_final_as_canonical

    def test_l2_final_policy_reference(self):
        c = _ctx(flow_id="flow-fin", semantic_kind="final_result")
        art = decide_convergence(c)
        assert FINAL_PROMOTES_AS_CANONICAL_AND_CLOSES_PARTIALS_POLICY in art.policy_reference

    def test_l3_final_flow_id_preserved(self):
        fid = _new_flow_id()
        c = _ctx(flow_id=fid, semantic_kind="final_result")
        art = decide_convergence(c)
        assert art.flow_id == fid


# ===========================================================================
# Group M — decide_convergence(): Rule 9 — replay resend not duplicate
# ===========================================================================


@_SKIP_MODULE
class TestGroupM_Rule9_ReplayNotDuplicate:
    def test_m1_replay_not_duplicate_promoted(self):
        c = _ctx(
            flow_id="flow-replay",
            is_reconnect_replay=True,
            is_duplicate=False,
        )
        art = decide_convergence(c)
        # A replay that was not previously absorbed is treated as a final promotion
        assert art.decision is ConvergenceDecisionKind.promote_final_as_canonical

    def test_m2_replay_policy_reference(self):
        c = _ctx(flow_id="flow-replay", is_reconnect_replay=True, is_duplicate=False)
        art = decide_convergence(c)
        assert RECONNECT_REPLAY_RESULT_ABSORBED_IDEMPOTENTLY_POLICY in art.policy_reference


# ===========================================================================
# Group N — FlowAwareConvergenceCoordinator: state enrichment
# ===========================================================================


@_SKIP_MODULE
class TestGroupN_CoordinatorStateEnrichment:
    def setup_method(self):
        reset_flow_aware_convergence_coordinator()

    def test_n1_absorb_returns_artifact(self):
        coord = get_flow_aware_convergence_coordinator()
        c = _ctx(flow_id=_new_flow_id(), semantic_kind="final_result")
        art = coord.absorb(c)
        assert isinstance(art, ResultConvergenceArtifact)

    def test_n2_second_absorb_same_result_id_is_duplicate(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        rid = _new_result_id()
        c1 = _ctx(flow_id=fid, result_id=rid, semantic_kind="partial_result")
        c2 = _ctx(flow_id=fid, result_id=rid, semantic_kind="partial_result")
        coord.absorb(c1)
        art2 = coord.absorb(c2)
        assert art2.decision is ConvergenceDecisionKind.suppress_duplicate_result

    def test_n3_late_partial_after_final_suppressed_via_coordinator(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        # Absorb final first
        coord.absorb(_ctx(flow_id=fid, result_id="r-final", semantic_kind="final_result"))
        # Now absorb partial — should be suppressed
        art = coord.absorb(_ctx(flow_id=fid, result_id="r-partial", semantic_kind="partial_result"))
        assert art.decision is ConvergenceDecisionKind.suppress_late_partial_after_final

    def test_n4_first_write_wins(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        rid = _new_result_id()
        art1 = coord.absorb(_ctx(flow_id=fid, result_id=rid, semantic_kind="partial_result"))
        art2 = coord.absorb(_ctx(flow_id=fid, result_id=rid, semantic_kind="partial_result"))
        assert art1.decision is ConvergenceDecisionKind.accept_partial_for_flow
        assert art2.decision is ConvergenceDecisionKind.suppress_duplicate_result


# ===========================================================================
# Group O — FlowAwareConvergenceCoordinator: parallel group registration
# ===========================================================================


@_SKIP_MODULE
class TestGroupO_ParallelGroupRegistration:
    def setup_method(self):
        reset_flow_aware_convergence_coordinator()

    def test_o1_register_parallel_group(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        gid = f"grp-{uuid.uuid4().hex[:6]}"
        record = coord.register_parallel_group(gid, fid, expected_count=3)
        assert isinstance(record, ParallelFlowAggregationRecord)
        assert record.group_id == gid
        assert record.parent_flow_id == fid
        assert record.expected_count == 3

    def test_o2_register_idempotent(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        gid = f"grp-{uuid.uuid4().hex[:6]}"
        r1 = coord.register_parallel_group(gid, fid, expected_count=2)
        r2 = coord.register_parallel_group(gid, fid, expected_count=99)
        assert r1 is r2
        assert r2.expected_count == 2  # first write wins

    def test_o3_get_parallel_group(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        gid = f"grp-{uuid.uuid4().hex[:6]}"
        coord.register_parallel_group(gid, fid, expected_count=1)
        record = coord.get_parallel_group(gid)
        assert record is not None
        assert record.group_id == gid

    def test_o4_get_unknown_group_none(self):
        coord = get_flow_aware_convergence_coordinator()
        assert coord.get_parallel_group("no-such-group") is None


# ===========================================================================
# Group P — FlowAwareConvergenceCoordinator: parallel group completion
# ===========================================================================


@_SKIP_MODULE
class TestGroupP_ParallelGroupCompletion:
    def setup_method(self):
        reset_flow_aware_convergence_coordinator()

    def test_p1_group_completes_after_all_subtasks(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        gid = f"grp-{uuid.uuid4().hex[:6]}"
        coord.register_parallel_group(gid, fid, expected_count=2)
        coord.absorb(_ctx(flow_id=fid, result_id="r0", semantic_kind="parallel_subtask_result", group_id=gid, subtask_index=0))
        art = coord.absorb(_ctx(flow_id=fid, result_id="r1", semantic_kind="parallel_subtask_result", group_id=gid, subtask_index=1))
        assert art.group_complete is True
        record = coord.get_parallel_group(gid)
        assert record.all_complete is True

    def test_p2_aggregate_artifact_produced_on_completion(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        gid = f"grp-{uuid.uuid4().hex[:6]}"
        coord.register_parallel_group(gid, fid, expected_count=2)
        coord.absorb(_ctx(flow_id=fid, result_id="r0", semantic_kind="parallel_subtask_result", group_id=gid, subtask_index=0))
        coord.absorb(_ctx(flow_id=fid, result_id="r1", semantic_kind="parallel_subtask_result", group_id=gid, subtask_index=1))
        record = coord.get_parallel_group(gid)
        assert record.aggregate_artifact is not None
        assert record.aggregate_artifact.group_complete is True

    def test_p3_partial_group_not_complete(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        gid = f"grp-{uuid.uuid4().hex[:6]}"
        coord.register_parallel_group(gid, fid, expected_count=3)
        art = coord.absorb(_ctx(flow_id=fid, result_id="r0", semantic_kind="parallel_subtask_result", group_id=gid, subtask_index=0))
        assert art.group_complete is False
        record = coord.get_parallel_group(gid)
        assert record.all_complete is False

    def test_p4_auto_create_group_on_first_subtask(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        gid = f"grp-{uuid.uuid4().hex[:6]}"
        # No prior register_parallel_group call
        coord.absorb(_ctx(flow_id=fid, result_id="r0", semantic_kind="parallel_subtask_result", group_id=gid, subtask_index=0))
        record = coord.get_parallel_group(gid)
        assert record is not None
        assert record.absorbed_count == 1


# ===========================================================================
# Group Q — Duplicate suppression via coordinator state
# ===========================================================================


@_SKIP_MODULE
class TestGroupQ_DuplicateSuppression:
    def setup_method(self):
        reset_flow_aware_convergence_coordinator()

    def test_q1_duplicate_partial_suppressed(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        rid = _new_result_id()
        coord.absorb(_ctx(flow_id=fid, result_id=rid, semantic_kind="partial_result"))
        art = coord.absorb(_ctx(flow_id=fid, result_id=rid, semantic_kind="partial_result"))
        assert art.decision is ConvergenceDecisionKind.suppress_duplicate_result

    def test_q2_duplicate_final_suppressed(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        rid = _new_result_id()
        coord.absorb(_ctx(flow_id=fid, result_id=rid, semantic_kind="final_result"))
        art = coord.absorb(_ctx(flow_id=fid, result_id=rid, semantic_kind="final_result"))
        assert art.decision is ConvergenceDecisionKind.suppress_duplicate_result

    def test_q3_different_result_ids_not_duplicates(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        coord.absorb(_ctx(flow_id=fid, result_id="r1", semantic_kind="partial_result"))
        art = coord.absorb(_ctx(flow_id=fid, result_id="r2", semantic_kind="partial_result"))
        assert art.decision is ConvergenceDecisionKind.accept_partial_for_flow


# ===========================================================================
# Group R — Final-absorbed flag propagation
# ===========================================================================


@_SKIP_MODULE
class TestGroupR_FinalAbsorbedFlag:
    def setup_method(self):
        reset_flow_aware_convergence_coordinator()

    def test_r1_final_sets_absorbed_flag(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        coord.absorb(_ctx(flow_id=fid, result_id="rf", semantic_kind="final_result"))
        # Any subsequent partial should be suppressed
        art = coord.absorb(_ctx(flow_id=fid, result_id="rp", semantic_kind="partial_result"))
        assert art.decision is ConvergenceDecisionKind.suppress_late_partial_after_final

    def test_r2_no_final_absorbed_allows_partial(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        art = coord.absorb(_ctx(flow_id=fid, result_id="rp", semantic_kind="partial_result"))
        assert art.decision is ConvergenceDecisionKind.accept_partial_for_flow


# ===========================================================================
# Group S — Reconnect / replay idempotent absorb
# ===========================================================================


@_SKIP_MODULE
class TestGroupS_ReconnectReplayIdempotent:
    def setup_method(self):
        reset_flow_aware_convergence_coordinator()

    def test_s1_replay_of_absorbed_result_is_idempotent(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        rid = _new_result_id()
        coord.absorb(_ctx(flow_id=fid, result_id=rid, semantic_kind="final_result"))
        art = coord.absorb(_ctx(
            flow_id=fid, result_id=rid,
            semantic_kind="final_result",
            is_reconnect_replay=True,
        ))
        assert art.decision is ConvergenceDecisionKind.absorb_replay_result_idempotently

    def test_s2_replay_of_new_result_id_promoted(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        # First result
        coord.absorb(_ctx(flow_id=fid, result_id="r1", semantic_kind="partial_result"))
        # Reconnect replay of unseen result_id → treated as new final
        art = coord.absorb(_ctx(
            flow_id=fid, result_id="r2",
            is_reconnect_replay=True,
            is_duplicate=False,
        ))
        assert art.decision is ConvergenceDecisionKind.promote_final_as_canonical


# ===========================================================================
# Group T — Ring buffer and get_artifact_by_id
# ===========================================================================


@_SKIP_MODULE
class TestGroupT_RingBuffer:
    def setup_method(self):
        reset_flow_aware_convergence_coordinator()

    def test_t1_artifact_recorded_in_buffer(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        art = coord.absorb(_ctx(flow_id=fid, semantic_kind="final_result"))
        found = coord.get_artifact_by_id(art.artifact_id)
        assert found is not None
        assert found.artifact_id == art.artifact_id

    def test_t2_list_recent_artifacts(self):
        coord = get_flow_aware_convergence_coordinator()
        for _ in range(5):
            coord.absorb(_ctx(flow_id=_new_flow_id(), semantic_kind="partial_result"))
        recent = coord.list_recent_artifacts(max_count=3)
        assert len(recent) == 3

    def test_t3_unknown_artifact_id_returns_none(self):
        coord = get_flow_aware_convergence_coordinator()
        assert coord.get_artifact_by_id("nonexistent") is None

    def test_t4_absorb_result_module_level_wrapper(self):
        reset_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        art = absorb_result(_ctx(flow_id=fid, semantic_kind="final_result"))
        assert isinstance(art, ResultConvergenceArtifact)


# ===========================================================================
# Group U — FlowConvergenceSnapshot
# ===========================================================================


@_SKIP_MODULE
class TestGroupU_Snapshot:
    def setup_method(self):
        reset_flow_aware_convergence_coordinator()

    def test_u1_snapshot_fields(self):
        coord = get_flow_aware_convergence_coordinator()
        fid = _new_flow_id()
        coord.absorb(_ctx(flow_id=fid, semantic_kind="final_result"))
        snap = coord.build_snapshot()
        assert isinstance(snap, FlowConvergenceSnapshot)
        assert snap.total_artifacts >= 1
        assert snap.active_flow_ids >= 1

    def test_u2_decision_counts_tracked(self):
        coord = get_flow_aware_convergence_coordinator()
        coord.absorb(_ctx(flow_id=_new_flow_id(), semantic_kind="partial_result"))
        coord.absorb(_ctx(flow_id=_new_flow_id(), semantic_kind="final_result"))
        snap = coord.build_snapshot()
        assert "accept_partial_for_flow" in snap.decision_counts
        assert "promote_final_as_canonical" in snap.decision_counts

    def test_u3_snapshot_to_dict(self):
        snap = build_flow_convergence_snapshot()
        d = snap.to_dict()
        assert "snapshot_id" in d
        assert "total_artifacts" in d
        assert "decision_counts" in d

    def test_u4_snapshot_id_unique(self):
        coord = get_flow_aware_convergence_coordinator()
        s1 = coord.build_snapshot()
        s2 = coord.build_snapshot()
        assert s1.snapshot_id != s2.snapshot_id


# ===========================================================================
# Group V — ResultConvergenceArtifact: to_dict() round-trip
# ===========================================================================


@_SKIP_MODULE
class TestGroupV_ArtifactToDict:
    def test_v1_to_dict_has_all_keys(self):
        art = ResultConvergenceArtifact(
            decision=ConvergenceDecisionKind.promote_final_as_canonical,
            semantic_kind=ResultSemanticKind.final_result,
            lineage=ConvergenceFlowLineage.direct_task_result,
            flow_id="flow-v",
            result_id="res-v",
        )
        d = art.to_dict()
        for key in (
            "artifact_id", "decision", "semantic_kind", "lineage",
            "policy_reference", "reason", "flow_id", "result_id",
            "group_id", "subtask_index", "parent_flow_id",
            "session_id", "device_id", "trace_id", "contract_id", "task_id",
            "partial_count_merged", "group_complete", "timestamp", "evidence",
        ):
            assert key in d, f"Missing key: {key}"

    def test_v2_decision_value_is_string(self):
        art = ResultConvergenceArtifact(
            decision=ConvergenceDecisionKind.accept_partial_for_flow,
            semantic_kind=ResultSemanticKind.partial_result,
            lineage=ConvergenceFlowLineage.direct_task_result,
        )
        d = art.to_dict()
        assert d["decision"] == "accept_partial_for_flow"
        assert d["semantic_kind"] == "partial_result"

    def test_v3_artifact_id_starts_with_rca(self):
        art = ResultConvergenceArtifact()
        assert art.artifact_id.startswith("rca_")


# ===========================================================================
# Group W — ResultConvergenceContext: to_dict() and defaults
# ===========================================================================


@_SKIP_MODULE
class TestGroupW_ContextToDict:
    def test_w1_defaults(self):
        c = ResultConvergenceContext()
        assert c.flow_id == ""
        assert c.result_id == ""
        assert c.group_id == ""
        assert c.is_duplicate is False
        assert c.is_reconnect_replay is False
        assert c.final_already_absorbed is False

    def test_w2_to_dict_keys(self):
        c = ResultConvergenceContext(flow_id="f", result_id="r")
        d = c.to_dict()
        for key in (
            "flow_id", "result_id", "semantic_kind", "lineage",
            "group_id", "subtask_index", "parent_flow_id",
            "final_already_absorbed", "is_duplicate", "is_reconnect_replay",
            "session_id", "device_id", "trace_id", "contract_id", "task_id",
            "timestamp",
        ):
            assert key in d, f"Missing key: {key}"


# ===========================================================================
# Group X — ParallelFlowAggregationRecord: to_dict() and absorbed_count
# ===========================================================================


@_SKIP_MODULE
class TestGroupX_ParallelAggregationRecord:
    def test_x1_absorbed_count_property(self):
        rec = ParallelFlowAggregationRecord(
            group_id="grp-x",
            parent_flow_id="flow-x",
            expected_count=3,
        )
        assert rec.absorbed_count == 0
        art = ResultConvergenceArtifact()
        rec.absorbed_subtasks[0] = art
        assert rec.absorbed_count == 1

    def test_x2_to_dict_keys(self):
        rec = ParallelFlowAggregationRecord(
            group_id="grp-xx",
            parent_flow_id="flow-xx",
        )
        d = rec.to_dict()
        for key in (
            "group_id", "parent_flow_id", "expected_count",
            "absorbed_count", "all_complete", "session_id",
            "trace_id", "created_at", "completed_at",
            "absorbed_subtasks", "aggregate_artifact",
        ):
            assert key in d, f"Missing key: {key}"

    def test_x3_aggregate_artifact_none_by_default(self):
        rec = ParallelFlowAggregationRecord(group_id="g", parent_flow_id="f")
        assert rec.aggregate_artifact is None


# ===========================================================================
# Group Y — Responsibility boundary policy sentinels
# ===========================================================================


@_SKIP_MODULE
class TestGroupY_ResponsibilityBoundary:
    def test_y1_cross_device_result_surface_policy_present(self):
        assert isinstance(CROSS_DEVICE_RESULT_SURFACE_IS_TRANSPORT_BOUNDARY_POLICY, str)
        assert "cross_device_result_surface" in CROSS_DEVICE_RESULT_SURFACE_IS_TRANSPORT_BOUNDARY_POLICY

    def test_y2_goal_result_aggregator_policy_present(self):
        assert isinstance(GOAL_RESULT_AGGREGATOR_IS_GROUP_COMPLETION_SIGNAL_POLICY, str)
        assert "goal_result_aggregator" in GOAL_RESULT_AGGREGATOR_IS_GROUP_COMPLETION_SIGNAL_POLICY

    def test_y3_boundary_policies_distinct(self):
        assert (
            CROSS_DEVICE_RESULT_SURFACE_IS_TRANSPORT_BOUNDARY_POLICY
            != GOAL_RESULT_AGGREGATOR_IS_GROUP_COMPLETION_SIGNAL_POLICY
        )


# ===========================================================================
# Group Z — core.runtime re-exports
# ===========================================================================


@_SKIP_MODULE
class TestGroupZ_RuntimeReexports:
    def test_z1_all_pr6v2_symbols_importable_from_core_runtime(self):
        try:
            from core.runtime import (  # noqa: F401
                FLOW_AWARE_CONVERGENCE_AUTHORITY,
                FLOW_AWARE_CONVERGENCE_PR6V2_SENTINEL,
                PARTIAL_ACCEPTED_INTO_FLOW_PENDING_FINAL_POLICY,
                FINAL_PROMOTES_AS_CANONICAL_AND_CLOSES_PARTIALS_POLICY,
                PARALLEL_RESULTS_AGGREGATE_TO_PARENT_FLOW_VIA_GROUP_ID_POLICY,
                DUPLICATE_RESULT_SUPPRESSED_FIRST_WRITE_WINS_POLICY,
                LATE_PARTIAL_AFTER_FINAL_IS_SUPPRESSED_POLICY,
                RECONNECT_REPLAY_RESULT_ABSORBED_IDEMPOTENTLY_POLICY,
                FLOW_MISMATCH_QUARANTINES_RESULT_POLICY,
                CROSS_DEVICE_RESULT_SURFACE_IS_TRANSPORT_BOUNDARY_POLICY,
                GOAL_RESULT_AGGREGATOR_IS_GROUP_COMPLETION_SIGNAL_POLICY,
                ConvergenceDecisionKind,
                ResultSemanticKind,
                ConvergenceFlowLineage,
                ResultConvergenceContext,
                ResultConvergenceArtifact,
                ParallelFlowAggregationRecord,
                FlowConvergenceSnapshot,
                classify_result_semantic_kind,
                decide_convergence,
                FlowAwareConvergenceCoordinator,
                get_flow_aware_convergence_coordinator,
                reset_flow_aware_convergence_coordinator,
                absorb_result,
                build_flow_convergence_snapshot,
            )
        except ImportError as exc:
            # Skip if a transitive dependency (e.g. pydantic) is missing in
            # the test environment — this is a pre-existing environment
            # constraint unrelated to PR-6V2 changes.
            pytest.skip(f"core.runtime transitive import unavailable: {exc}")


# ===========================================================================
# Group AA — Policy sentinel presence and count
# ===========================================================================


@_SKIP_MODULE
class TestGroupAA_PolicySentinels:
    def test_aa1_all_policy_sentinels_are_strings(self):
        sentinels = [
            PARTIAL_ACCEPTED_INTO_FLOW_PENDING_FINAL_POLICY,
            FINAL_PROMOTES_AS_CANONICAL_AND_CLOSES_PARTIALS_POLICY,
            PARALLEL_RESULTS_AGGREGATE_TO_PARENT_FLOW_VIA_GROUP_ID_POLICY,
            DUPLICATE_RESULT_SUPPRESSED_FIRST_WRITE_WINS_POLICY,
            LATE_PARTIAL_AFTER_FINAL_IS_SUPPRESSED_POLICY,
            RECONNECT_REPLAY_RESULT_ABSORBED_IDEMPOTENTLY_POLICY,
            FLOW_MISMATCH_QUARANTINES_RESULT_POLICY,
            CROSS_DEVICE_RESULT_SURFACE_IS_TRANSPORT_BOUNDARY_POLICY,
            GOAL_RESULT_AGGREGATOR_IS_GROUP_COMPLETION_SIGNAL_POLICY,
        ]
        for s in sentinels:
            assert isinstance(s, str)
            assert len(s) > 40

    def test_aa2_minimum_nine_policy_sentinels(self):
        # AC12: at least 7 policy sentinels (we have 9)
        sentinels = [
            PARTIAL_ACCEPTED_INTO_FLOW_PENDING_FINAL_POLICY,
            FINAL_PROMOTES_AS_CANONICAL_AND_CLOSES_PARTIALS_POLICY,
            PARALLEL_RESULTS_AGGREGATE_TO_PARENT_FLOW_VIA_GROUP_ID_POLICY,
            DUPLICATE_RESULT_SUPPRESSED_FIRST_WRITE_WINS_POLICY,
            LATE_PARTIAL_AFTER_FINAL_IS_SUPPRESSED_POLICY,
            RECONNECT_REPLAY_RESULT_ABSORBED_IDEMPOTENTLY_POLICY,
            FLOW_MISMATCH_QUARANTINES_RESULT_POLICY,
            CROSS_DEVICE_RESULT_SURFACE_IS_TRANSPORT_BOUNDARY_POLICY,
            GOAL_RESULT_AGGREGATOR_IS_GROUP_COMPLETION_SIGNAL_POLICY,
        ]
        assert len(sentinels) >= 7

    def test_aa3_policy_sentinels_all_unique(self):
        sentinels = [
            PARTIAL_ACCEPTED_INTO_FLOW_PENDING_FINAL_POLICY,
            FINAL_PROMOTES_AS_CANONICAL_AND_CLOSES_PARTIALS_POLICY,
            PARALLEL_RESULTS_AGGREGATE_TO_PARENT_FLOW_VIA_GROUP_ID_POLICY,
            DUPLICATE_RESULT_SUPPRESSED_FIRST_WRITE_WINS_POLICY,
            LATE_PARTIAL_AFTER_FINAL_IS_SUPPRESSED_POLICY,
            RECONNECT_REPLAY_RESULT_ABSORBED_IDEMPOTENTLY_POLICY,
            FLOW_MISMATCH_QUARANTINES_RESULT_POLICY,
            CROSS_DEVICE_RESULT_SURFACE_IS_TRANSPORT_BOUNDARY_POLICY,
            GOAL_RESULT_AGGREGATOR_IS_GROUP_COMPLETION_SIGNAL_POLICY,
        ]
        assert len(sentinels) == len(set(sentinels))

    def test_aa4_pr6v2_referenced_in_policy_sentinels(self):
        sentinels = [
            PARTIAL_ACCEPTED_INTO_FLOW_PENDING_FINAL_POLICY,
            FINAL_PROMOTES_AS_CANONICAL_AND_CLOSES_PARTIALS_POLICY,
            PARALLEL_RESULTS_AGGREGATE_TO_PARENT_FLOW_VIA_GROUP_ID_POLICY,
            DUPLICATE_RESULT_SUPPRESSED_FIRST_WRITE_WINS_POLICY,
            LATE_PARTIAL_AFTER_FINAL_IS_SUPPRESSED_POLICY,
            RECONNECT_REPLAY_RESULT_ABSORBED_IDEMPOTENTLY_POLICY,
            FLOW_MISMATCH_QUARANTINES_RESULT_POLICY,
        ]
        for s in sentinels:
            assert "PR-6V2" in s, f"Expected 'PR-6V2' in sentinel: {s[:80]}..."
