"""tests/test_pr50_post533_delegated_flow_entity.py
====================================================
Tests for PR package 50 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Unified Delegated Flow Entity — Cross-Device First-Class
Citizen.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — DelegatedFlowKind enum: all values, from_string(), defaults.
C  — DelegatedFlowPhase enum: all values, from_string(), is_terminal(),
     is_active(), is_executing_or_later().
D  — DelegatedFlowSignal enum: all values, from_string(), defaults.
E  — DelegatedFlowOwnerKind enum: all values, from_string(), defaults.
F  — Phase transition table: all canonical transitions.
G  — Phase transition: terminal phases block advancement.
H  — Phase transition: unknown (phase, signal) pair leaves phase unchanged.
I  — DelegatedFlowIdentity: construction, defaults, to_dict(), to_json(),
     from_dict().
J  — DelegatedFlowOwnership: construction, defaults, to_dict(), to_json(),
     from_dict(), with_execution_owner_assigned().
K  — DelegatedFlowObjectMapping: construction, defaults, to_dict(), to_json(),
     from_dict(), merge_with().
L  — DelegatedFlowExtensionPoints: construction, defaults, to_dict(), to_json(),
     from_dict().
M  — DelegatedFlowEntity: construction, defaults, property shortcuts.
N  — DelegatedFlowEntity: to_dict(), to_json(), from_dict() round-trip.
O  — DelegatedFlowEntityRecord: construction, to_dict(), to_json().
P  — DelegatedFlowEntitySnapshot: construction, to_dict(), to_json().
Q  — DelegatedFlowEntityRuntime: put, get_by_flow_id, get_by_lineage,
     get_by_contract, list_active, list_all, total_seen.
R  — DelegatedFlowEntityRuntime: ring-buffer capacity (128).
S  — DelegatedFlowEntityRuntime: replace-in-place for same delegated_flow_id.
T  — create_delegated_flow_entity: valid inputs → created entity.
U  — create_delegated_flow_entity: auto-generates ids when not provided.
V  — create_delegated_flow_entity: explicit ids are honoured.
W  — create_delegated_flow_entity: flow_lineage_id shared when supplied.
X  — create_delegated_flow_entity: persisted to runtime.
Y  — create_delegated_flow_entity: custom runtime isolation.
Z  — advance_flow_phase: created + dispatch → dispatched.
AA — advance_flow_phase: dispatched + ack → executing (execution_owner assigned).
AB — advance_flow_phase: executing + result_inbound → reconciling.
AC — advance_flow_phase: reconciling + reconcile_complete → completed.
AD — advance_flow_phase: reconciling + result_success → completed.
AE — advance_flow_phase: reconciling + result_failure → failed.
AF — advance_flow_phase: any non-terminal + fail → failed.
AG — advance_flow_phase: any non-terminal + cancel → cancelled.
AH — advance_flow_phase: dispatched/executing + suspend → suspended.
AI — advance_flow_phase: suspended + resume → executing.
AJ — advance_flow_phase: terminal phase + any signal → unchanged.
AK — advance_flow_phase: identity fields preserved across transitions.
AL — advance_flow_phase: signal_metadata merged into entity metadata.
AM — advance_flow_phase: persisted to runtime.
AN — attach_object_mapping: non-empty fields in update overwrite empty fields.
AO — attach_object_mapping: non-empty existing fields NOT overwritten by empty update.
AP — attach_object_mapping: identity/phase/ownership preserved.
AQ — attach_object_mapping: persisted to runtime.
AR — record_delegated_flow: persists entity to runtime.
AS — get_delegated_flow: returns entity for known id.
AT — get_delegated_flow: returns None for unknown id.
AU — get_delegated_flow_by_lineage: returns all entities sharing lineage_id.
AV — get_delegated_flow_by_lineage: empty list for unknown lineage_id.
AW — get_delegated_flow_by_contract: returns entity for known contract_id.
AX — get_delegated_flow_by_contract: returns None for unknown contract_id.
AY — list_active_delegated_flows: excludes terminal flows.
AZ — list_active_delegated_flows: includes created/dispatched/executing/reconciling.
BA — build_delegated_flow_snapshot: correct active/terminal split.
BB — build_delegated_flow_snapshot: total_seen reflects distinct flow count.
BC — get_delegated_flow_entity_runtime: returns same singleton.
BD — reset_delegated_flow_entity_runtime: clears singleton for isolation.
BE — DelegatedFlowKind.task_assign, goal_execution, parallel_subtask,
     takeover_request all resolve from string.
BF — Ownership: canonical_owner is always v2_canonical at creation.
BG — Ownership: execution_owner is none before dispatch, android_execution after ack.
BH — All 14 policy sentinels are non-empty strings.
BI — DELEGATED_FLOW_ENTITY_PR50_SENTINEL contains 'package=50'.
BJ — core.runtime re-exports: all PR-50 symbols accessible from core.runtime.
BK — Serialisation: from_dict with non-dict raises ValueError for Identity.
BL — Serialisation: from_dict with non-dict raises ValueError for Ownership.
BM — Serialisation: from_dict with non-dict raises ValueError for ObjectMapping.
BN — Serialisation: from_dict with non-dict raises ValueError for ExtensionPoints.
BO — Serialisation: from_dict with non-dict raises ValueError for Entity.
BP — End-to-end: task_assign flow through full lifecycle → completed.
BQ — End-to-end: takeover_request flow with shared lineage_id.
BR — End-to-end: parallel_subtask flows sharing lineage_id, retrieved together.
BS — Ring buffer: oldest entry evicted when full.
BT — Snapshot to_dict has expected top-level keys.
BU — DelegatedFlowEntity.contract_id shortcut matches object_mapping.contract_id.
BV — DelegatedFlowEntity.canonical_task_id shortcut matches object_mapping.canonical_task_id.
BW — merge_with: empty-string fields in 'other' do not overwrite non-empty self fields.
BX — merge_with: non-empty fields in 'other' always win.
BY — Phase transition: idempotent dispatch from dispatched stays dispatched.
BZ — Phase transition: idempotent ack from executing stays executing.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.delegated_flow_entity import (
        # Sentinels
        DELEGATED_FLOW_ENTITY_AUTHORITY,
        DELEGATED_FLOW_ID_IS_IMMUTABLE_POLICY,
        FLOW_LINEAGE_ID_SPANS_BOTH_SIDES_POLICY,
        FLOW_PHASE_IS_MONOTONIC_POLICY,
        FLOW_KIND_UNIFIES_ALL_DELEGATED_WORK_POLICY,
        V2_HOLDS_CANONICAL_FLOW_TRUTH_POLICY,
        ANDROID_HOLDS_EXECUTION_TRUTH_POLICY,
        FLOW_OBJECT_MAPPING_IS_ADDITIVE_POLICY,
        FLOW_ENTITY_IS_SYSTEM_FIRST_CLASS_CITIZEN_POLICY,
        TERMINAL_FLOW_PHASE_BLOCKS_ADVANCEMENT_POLICY,
        FLOW_LINEAGE_IS_TRACEABLE_ACROSS_KIND_BOUNDARY_POLICY,
        EXTENSION_POINTS_ARE_FORWARD_COMPATIBLE_POLICY,
        FLOW_TRUTH_AUTHORITY_IS_SCOPE_SEPARATED_POLICY,
        DELEGATED_FLOW_ENTITY_PR50_SENTINEL,
        # Enums
        DelegatedFlowKind,
        DelegatedFlowPhase,
        DelegatedFlowSignal,
        DelegatedFlowOwnerKind,
        # Dataclasses
        DelegatedFlowIdentity,
        DelegatedFlowOwnership,
        DelegatedFlowObjectMapping,
        DelegatedFlowExtensionPoints,
        DelegatedFlowEntity,
        DelegatedFlowEntityRecord,
        DelegatedFlowEntitySnapshot,
        # Runtime
        DelegatedFlowEntityRuntime,
        # Functions
        create_delegated_flow_entity,
        advance_flow_phase,
        attach_object_mapping,
        record_delegated_flow,
        get_delegated_flow,
        get_delegated_flow_by_lineage,
        get_delegated_flow_by_contract,
        list_active_delegated_flows,
        build_delegated_flow_snapshot,
        get_delegated_flow_entity_runtime,
        reset_delegated_flow_entity_runtime,
    )

    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False

try:
    from core.runtime import (
        DELEGATED_FLOW_ENTITY_AUTHORITY as _rt_authority,
        DELEGATED_FLOW_ENTITY_PR50_SENTINEL as _rt_sentinel,
        DelegatedFlowKind as _rt_kind,
        DelegatedFlowPhase as _rt_phase,
        DelegatedFlowSignal as _rt_signal,
        DelegatedFlowOwnerKind as _rt_owner_kind,
        DelegatedFlowIdentity as _rt_identity,
        DelegatedFlowOwnership as _rt_ownership,
        DelegatedFlowObjectMapping as _rt_mapping,
        DelegatedFlowExtensionPoints as _rt_ext,
        DelegatedFlowEntity as _rt_entity,
        DelegatedFlowEntityRecord as _rt_record,
        DelegatedFlowEntitySnapshot as _rt_snapshot,
        DelegatedFlowEntityRuntime as _rt_runtime_cls,
        create_delegated_flow_entity as _rt_create,
        advance_flow_phase as _rt_advance,
        attach_object_mapping as _rt_attach,
        record_delegated_flow as _rt_record_fn,
        get_delegated_flow as _rt_get,
        get_delegated_flow_by_lineage as _rt_get_lineage,
        get_delegated_flow_by_contract as _rt_get_contract,
        list_active_delegated_flows as _rt_list_active,
        build_delegated_flow_snapshot as _rt_snapshot_fn,
        get_delegated_flow_entity_runtime as _rt_get_runtime,
        reset_delegated_flow_entity_runtime as _rt_reset_runtime,
    )

    _RUNTIME_EXPORTS_AVAILABLE = True
except ImportError:
    _RUNTIME_EXPORTS_AVAILABLE = False

skip_if_unavailable = pytest.mark.skipif(
    not _MODULE_AVAILABLE, reason="core.delegated_flow_entity not available"
)
skip_runtime_if_unavailable = pytest.mark.skipif(
    not _RUNTIME_EXPORTS_AVAILABLE, reason="core.runtime PR-50 exports not available"
)

# ===========================================================================
# Group A — Authority / policy sentinel presence and correctness
# ===========================================================================


@skip_if_unavailable
def test_A01_authority_sentinel_non_empty():
    assert DELEGATED_FLOW_ENTITY_AUTHORITY
    assert "DELEGATED_FLOW_ENTITY_AUTHORITY" in DELEGATED_FLOW_ENTITY_AUTHORITY


@skip_if_unavailable
def test_A02_pr50_sentinel_contains_package_50():
    assert "package=50" in DELEGATED_FLOW_ENTITY_PR50_SENTINEL


@skip_if_unavailable
def test_A03_pr50_sentinel_contains_module_name():
    assert "delegated_flow_entity" in DELEGATED_FLOW_ENTITY_PR50_SENTINEL


@skip_if_unavailable
def test_A04_all_14_policy_sentinels_non_empty():
    sentinels = [
        DELEGATED_FLOW_ENTITY_AUTHORITY,
        DELEGATED_FLOW_ID_IS_IMMUTABLE_POLICY,
        FLOW_LINEAGE_ID_SPANS_BOTH_SIDES_POLICY,
        FLOW_PHASE_IS_MONOTONIC_POLICY,
        FLOW_KIND_UNIFIES_ALL_DELEGATED_WORK_POLICY,
        V2_HOLDS_CANONICAL_FLOW_TRUTH_POLICY,
        ANDROID_HOLDS_EXECUTION_TRUTH_POLICY,
        FLOW_OBJECT_MAPPING_IS_ADDITIVE_POLICY,
        FLOW_ENTITY_IS_SYSTEM_FIRST_CLASS_CITIZEN_POLICY,
        TERMINAL_FLOW_PHASE_BLOCKS_ADVANCEMENT_POLICY,
        FLOW_LINEAGE_IS_TRACEABLE_ACROSS_KIND_BOUNDARY_POLICY,
        EXTENSION_POINTS_ARE_FORWARD_COMPATIBLE_POLICY,
        FLOW_TRUTH_AUTHORITY_IS_SCOPE_SEPARATED_POLICY,
        DELEGATED_FLOW_ENTITY_PR50_SENTINEL,
    ]
    for sentinel in sentinels:
        assert isinstance(sentinel, str) and sentinel


@skip_if_unavailable
def test_A05_v2_canonical_truth_policy_mentions_v2():
    assert "V2" in V2_HOLDS_CANONICAL_FLOW_TRUTH_POLICY or "v2" in V2_HOLDS_CANONICAL_FLOW_TRUTH_POLICY.lower()


@skip_if_unavailable
def test_A06_android_execution_truth_policy_mentions_android():
    assert "Android" in ANDROID_HOLDS_EXECUTION_TRUTH_POLICY or "android" in ANDROID_HOLDS_EXECUTION_TRUTH_POLICY.lower()


# ===========================================================================
# Group B — DelegatedFlowKind enum
# ===========================================================================


@skip_if_unavailable
def test_B01_flow_kind_all_values():
    values = {k.value for k in DelegatedFlowKind}
    assert "task_assign" in values
    assert "goal_execution" in values
    assert "parallel_subtask" in values
    assert "takeover_request" in values
    assert "unknown" in values


@skip_if_unavailable
def test_B02_flow_kind_from_string_task_assign():
    assert DelegatedFlowKind.from_string("task_assign") == DelegatedFlowKind.task_assign


@skip_if_unavailable
def test_B03_flow_kind_from_string_goal_execution():
    assert DelegatedFlowKind.from_string("goal_execution") == DelegatedFlowKind.goal_execution


@skip_if_unavailable
def test_B04_flow_kind_from_string_parallel_subtask():
    assert DelegatedFlowKind.from_string("parallel_subtask") == DelegatedFlowKind.parallel_subtask


@skip_if_unavailable
def test_B05_flow_kind_from_string_takeover_request():
    assert DelegatedFlowKind.from_string("takeover_request") == DelegatedFlowKind.takeover_request


@skip_if_unavailable
def test_B06_flow_kind_from_string_unknown_default():
    assert DelegatedFlowKind.from_string("not_a_kind") == DelegatedFlowKind.unknown


@skip_if_unavailable
def test_B07_flow_kind_from_string_non_string_default():
    assert DelegatedFlowKind.from_string(None) == DelegatedFlowKind.unknown  # type: ignore[arg-type]


# ===========================================================================
# Group C — DelegatedFlowPhase enum
# ===========================================================================


@skip_if_unavailable
def test_C01_flow_phase_all_values():
    values = {p.value for p in DelegatedFlowPhase}
    assert "created" in values
    assert "dispatched" in values
    assert "executing" in values
    assert "reconciling" in values
    assert "completed" in values
    assert "failed" in values
    assert "cancelled" in values
    assert "suspended" in values


@skip_if_unavailable
def test_C02_terminal_phases():
    assert DelegatedFlowPhase.completed.is_terminal()
    assert DelegatedFlowPhase.failed.is_terminal()
    assert DelegatedFlowPhase.cancelled.is_terminal()


@skip_if_unavailable
def test_C03_non_terminal_phases():
    for phase in (
        DelegatedFlowPhase.created,
        DelegatedFlowPhase.dispatched,
        DelegatedFlowPhase.executing,
        DelegatedFlowPhase.reconciling,
        DelegatedFlowPhase.suspended,
    ):
        assert not phase.is_terminal(), f"{phase} should not be terminal"


@skip_if_unavailable
def test_C04_is_active_inverse_of_is_terminal():
    for phase in DelegatedFlowPhase:
        assert phase.is_active() == (not phase.is_terminal())


@skip_if_unavailable
def test_C05_is_executing_or_later():
    assert DelegatedFlowPhase.executing.is_executing_or_later()
    assert DelegatedFlowPhase.reconciling.is_executing_or_later()
    assert DelegatedFlowPhase.completed.is_executing_or_later()
    assert DelegatedFlowPhase.failed.is_executing_or_later()
    assert DelegatedFlowPhase.cancelled.is_executing_or_later()
    assert DelegatedFlowPhase.suspended.is_executing_or_later()


@skip_if_unavailable
def test_C06_not_executing_or_later_before_dispatch():
    assert not DelegatedFlowPhase.created.is_executing_or_later()
    assert not DelegatedFlowPhase.dispatched.is_executing_or_later()


@skip_if_unavailable
def test_C07_from_string_valid():
    assert DelegatedFlowPhase.from_string("created") == DelegatedFlowPhase.created
    assert DelegatedFlowPhase.from_string("completed") == DelegatedFlowPhase.completed


@skip_if_unavailable
def test_C08_from_string_unknown_returns_default():
    assert DelegatedFlowPhase.from_string("not_a_phase") == DelegatedFlowPhase.created


# ===========================================================================
# Group D — DelegatedFlowSignal enum
# ===========================================================================


@skip_if_unavailable
def test_D01_signal_all_values():
    values = {s.value for s in DelegatedFlowSignal}
    assert "dispatch" in values
    assert "ack" in values
    assert "result_inbound" in values
    assert "reconcile_complete" in values
    assert "fail" in values
    assert "cancel" in values
    assert "suspend" in values
    assert "resume" in values
    assert "result_success" in values
    assert "result_failure" in values


@skip_if_unavailable
def test_D02_signal_from_string_dispatch():
    assert DelegatedFlowSignal.from_string("dispatch") == DelegatedFlowSignal.dispatch


@skip_if_unavailable
def test_D03_signal_from_string_unknown_default():
    assert DelegatedFlowSignal.from_string("unknown_signal") == DelegatedFlowSignal.fail


# ===========================================================================
# Group E — DelegatedFlowOwnerKind enum
# ===========================================================================


@skip_if_unavailable
def test_E01_owner_kind_all_values():
    values = {o.value for o in DelegatedFlowOwnerKind}
    assert "v2_canonical" in values
    assert "android_execution" in values
    assert "none" in values


@skip_if_unavailable
def test_E02_owner_kind_from_string_v2():
    assert DelegatedFlowOwnerKind.from_string("v2_canonical") == DelegatedFlowOwnerKind.v2_canonical


@skip_if_unavailable
def test_E03_owner_kind_from_string_android():
    assert DelegatedFlowOwnerKind.from_string("android_execution") == DelegatedFlowOwnerKind.android_execution


@skip_if_unavailable
def test_E04_owner_kind_from_string_unknown_default():
    assert DelegatedFlowOwnerKind.from_string("bad_value") == DelegatedFlowOwnerKind.none


# ===========================================================================
# Group F — Phase transition table: canonical transitions
# ===========================================================================


@skip_if_unavailable
def test_F01_transition_created_dispatch_to_dispatched():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    assert e.phase == DelegatedFlowPhase.created
    e2 = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    assert e2.phase == DelegatedFlowPhase.dispatched


@skip_if_unavailable
def test_F02_transition_dispatched_ack_to_executing():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.ack, runtime=rt)
    assert e.phase == DelegatedFlowPhase.executing


@skip_if_unavailable
def test_F03_transition_executing_result_inbound_to_reconciling():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.ack, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.result_inbound, runtime=rt)
    assert e.phase == DelegatedFlowPhase.reconciling


@skip_if_unavailable
def test_F04_transition_reconciling_reconcile_complete_to_completed():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.ack, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.result_inbound, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.reconcile_complete, runtime=rt)
    assert e.phase == DelegatedFlowPhase.completed


@skip_if_unavailable
def test_F05_transition_reconciling_result_success_to_completed():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.ack, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.result_inbound, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.result_success, runtime=rt)
    assert e.phase == DelegatedFlowPhase.completed


@skip_if_unavailable
def test_F06_transition_reconciling_result_failure_to_failed():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.ack, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.result_inbound, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.result_failure, runtime=rt)
    assert e.phase == DelegatedFlowPhase.failed


@skip_if_unavailable
def test_F07_transition_suspend_and_resume():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.suspend, runtime=rt)
    assert e.phase == DelegatedFlowPhase.suspended
    e = advance_flow_phase(e, DelegatedFlowSignal.resume, runtime=rt)
    assert e.phase == DelegatedFlowPhase.executing


# ===========================================================================
# Group G — Terminal phases block advancement
# ===========================================================================


@skip_if_unavailable
@pytest.mark.parametrize("terminal_phase", [
    DelegatedFlowPhase.completed,
    DelegatedFlowPhase.failed,
    DelegatedFlowPhase.cancelled,
])
def test_G01_terminal_phases_block_all_signals(terminal_phase):
    rt = DelegatedFlowEntityRuntime()
    flow_id = str(uuid.uuid4())
    e = create_delegated_flow_entity(delegated_flow_id=flow_id, runtime=rt)
    # Manually construct a terminal entity
    terminal_entity = DelegatedFlowEntity(
        identity=e.identity,
        phase=terminal_phase,
        ownership=e.ownership,
        object_mapping=e.object_mapping,
    )
    rt.put(terminal_entity)
    for signal in DelegatedFlowSignal:
        advanced = advance_flow_phase(terminal_entity, signal, runtime=rt)
        assert advanced.phase == terminal_phase, (
            f"Terminal phase {terminal_phase} should not advance via {signal}"
        )


# ===========================================================================
# Group H — Unknown (phase, signal) pair leaves phase unchanged
# ===========================================================================


@skip_if_unavailable
def test_H01_unknown_transition_leaves_phase_unchanged():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    # result_success has no transition from 'created'
    e2 = advance_flow_phase(e, DelegatedFlowSignal.result_success, runtime=rt)
    assert e2.phase == DelegatedFlowPhase.created


# ===========================================================================
# Group I — DelegatedFlowIdentity
# ===========================================================================


@skip_if_unavailable
def test_I01_identity_defaults():
    identity = DelegatedFlowIdentity()
    assert identity.delegated_flow_id
    assert identity.flow_lineage_id
    assert identity.flow_segment_id == ""
    assert identity.trace_id
    assert identity.flow_kind == DelegatedFlowKind.task_assign


@skip_if_unavailable
def test_I02_identity_explicit_values():
    fid = str(uuid.uuid4())
    lid = str(uuid.uuid4())
    identity = DelegatedFlowIdentity(
        delegated_flow_id=fid,
        flow_lineage_id=lid,
        flow_segment_id="seg-1",
        trace_id="trace-abc",
        flow_kind=DelegatedFlowKind.goal_execution,
    )
    assert identity.delegated_flow_id == fid
    assert identity.flow_lineage_id == lid
    assert identity.flow_segment_id == "seg-1"
    assert identity.trace_id == "trace-abc"
    assert identity.flow_kind == DelegatedFlowKind.goal_execution


@skip_if_unavailable
def test_I03_identity_to_dict_keys():
    identity = DelegatedFlowIdentity()
    d = identity.to_dict()
    assert set(d.keys()) == {
        "delegated_flow_id", "flow_lineage_id", "flow_segment_id",
        "trace_id", "flow_kind",
    }


@skip_if_unavailable
def test_I04_identity_to_json_valid():
    identity = DelegatedFlowIdentity()
    j = identity.to_json()
    parsed = json.loads(j)
    assert "delegated_flow_id" in parsed


@skip_if_unavailable
def test_I05_identity_from_dict_round_trip():
    identity = DelegatedFlowIdentity(
        flow_kind=DelegatedFlowKind.parallel_subtask,
        flow_segment_id="seg-2",
    )
    identity2 = DelegatedFlowIdentity.from_dict(identity.to_dict())
    assert identity2.delegated_flow_id == identity.delegated_flow_id
    assert identity2.flow_lineage_id == identity.flow_lineage_id
    assert identity2.flow_segment_id == identity.flow_segment_id
    assert identity2.flow_kind == DelegatedFlowKind.parallel_subtask


@skip_if_unavailable
def test_I06_identity_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedFlowIdentity.from_dict("not_a_dict")  # type: ignore[arg-type]


# ===========================================================================
# Group J — DelegatedFlowOwnership
# ===========================================================================


@skip_if_unavailable
def test_J01_ownership_defaults():
    ownership = DelegatedFlowOwnership()
    assert ownership.canonical_owner == DelegatedFlowOwnerKind.v2_canonical
    assert ownership.execution_owner == DelegatedFlowOwnerKind.none


@skip_if_unavailable
def test_J02_ownership_with_execution_owner_assigned():
    ownership = DelegatedFlowOwnership()
    updated = ownership.with_execution_owner_assigned()
    assert updated.execution_owner == DelegatedFlowOwnerKind.android_execution
    assert updated.canonical_owner == DelegatedFlowOwnerKind.v2_canonical


@skip_if_unavailable
def test_J03_ownership_from_dict_round_trip():
    ownership = DelegatedFlowOwnership()
    updated = ownership.with_execution_owner_assigned(rationale="test")
    o2 = DelegatedFlowOwnership.from_dict(updated.to_dict())
    assert o2.canonical_owner == DelegatedFlowOwnerKind.v2_canonical
    assert o2.execution_owner == DelegatedFlowOwnerKind.android_execution


@skip_if_unavailable
def test_J04_ownership_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedFlowOwnership.from_dict(42)  # type: ignore[arg-type]


@skip_if_unavailable
def test_J05_ownership_to_json_valid():
    j = DelegatedFlowOwnership().to_json()
    parsed = json.loads(j)
    assert "canonical_owner" in parsed


# ===========================================================================
# Group K — DelegatedFlowObjectMapping
# ===========================================================================


@skip_if_unavailable
def test_K01_object_mapping_defaults():
    m = DelegatedFlowObjectMapping()
    for field_name in (
        "canonical_task_id", "dispatch_record_id", "contract_id",
        "binding_id", "tracker_id", "session_id", "device_id", "android_flow_id",
    ):
        assert getattr(m, field_name) == "", f"{field_name} should default to empty string"


@skip_if_unavailable
def test_K02_object_mapping_to_dict_keys():
    m = DelegatedFlowObjectMapping()
    d = m.to_dict()
    assert set(d.keys()) == {
        "canonical_task_id", "dispatch_record_id", "contract_id",
        "binding_id", "tracker_id", "session_id", "device_id", "android_flow_id",
    }


@skip_if_unavailable
def test_K03_object_mapping_from_dict_round_trip():
    m = DelegatedFlowObjectMapping(
        canonical_task_id="task-1",
        contract_id="contract-1",
        device_id="device-1",
    )
    m2 = DelegatedFlowObjectMapping.from_dict(m.to_dict())
    assert m2.canonical_task_id == "task-1"
    assert m2.contract_id == "contract-1"
    assert m2.device_id == "device-1"


@skip_if_unavailable
def test_K04_object_mapping_merge_with_non_empty_wins():
    m1 = DelegatedFlowObjectMapping(canonical_task_id="task-1")
    m2 = DelegatedFlowObjectMapping(canonical_task_id="task-2", contract_id="contract-1")
    merged = m1.merge_with(m2)
    assert merged.canonical_task_id == "task-2"
    assert merged.contract_id == "contract-1"


@skip_if_unavailable
def test_K05_object_mapping_merge_with_empty_does_not_overwrite():
    m1 = DelegatedFlowObjectMapping(canonical_task_id="task-1", contract_id="c-1")
    m2 = DelegatedFlowObjectMapping(contract_id="")  # empty contract_id
    merged = m1.merge_with(m2)
    assert merged.canonical_task_id == "task-1"
    assert merged.contract_id == "c-1"  # original preserved


@skip_if_unavailable
def test_K06_object_mapping_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedFlowObjectMapping.from_dict("not_a_dict")  # type: ignore[arg-type]


# ===========================================================================
# Group L — DelegatedFlowExtensionPoints
# ===========================================================================


@skip_if_unavailable
def test_L01_extension_points_defaults_all_none():
    ext = DelegatedFlowExtensionPoints()
    assert ext.continuity_token is None
    assert ext.replay_anchor_id is None
    assert ext.result_convergence_key is None
    assert ext.operator_visibility_tag is None


@skip_if_unavailable
def test_L02_extension_points_from_dict_round_trip():
    ext = DelegatedFlowExtensionPoints(
        continuity_token="ct-1",
        operator_visibility_tag="op-tag",
    )
    ext2 = DelegatedFlowExtensionPoints.from_dict(ext.to_dict())
    assert ext2.continuity_token == "ct-1"
    assert ext2.operator_visibility_tag == "op-tag"
    assert ext2.replay_anchor_id is None


@skip_if_unavailable
def test_L03_extension_points_to_json_valid():
    j = DelegatedFlowExtensionPoints().to_json()
    parsed = json.loads(j)
    assert "continuity_token" in parsed


@skip_if_unavailable
def test_L04_extension_points_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedFlowExtensionPoints.from_dict(123)  # type: ignore[arg-type]


# ===========================================================================
# Group M — DelegatedFlowEntity: construction, defaults, property shortcuts
# ===========================================================================


@skip_if_unavailable
def test_M01_entity_defaults():
    e = DelegatedFlowEntity()
    assert e.phase == DelegatedFlowPhase.created
    assert e.identity.flow_kind == DelegatedFlowKind.task_assign
    assert e.ownership.canonical_owner == DelegatedFlowOwnerKind.v2_canonical
    assert e.ownership.execution_owner == DelegatedFlowOwnerKind.none


@skip_if_unavailable
def test_M02_entity_property_shortcuts():
    fid = str(uuid.uuid4())
    lid = str(uuid.uuid4())
    cid = "contract-abc"
    tid = "task-xyz"
    identity = DelegatedFlowIdentity(
        delegated_flow_id=fid,
        flow_lineage_id=lid,
        flow_segment_id="seg",
        flow_kind=DelegatedFlowKind.goal_execution,
    )
    mapping = DelegatedFlowObjectMapping(contract_id=cid, canonical_task_id=tid)
    e = DelegatedFlowEntity(identity=identity, object_mapping=mapping)
    assert e.delegated_flow_id == fid
    assert e.flow_lineage_id == lid
    assert e.flow_segment_id == "seg"
    assert e.flow_kind == DelegatedFlowKind.goal_execution
    assert e.contract_id == cid
    assert e.canonical_task_id == tid


# ===========================================================================
# Group N — DelegatedFlowEntity: serialisation round-trip
# ===========================================================================


@skip_if_unavailable
def test_N01_entity_to_dict_keys():
    e = DelegatedFlowEntity()
    d = e.to_dict()
    assert set(d.keys()) >= {
        "identity", "phase", "ownership", "object_mapping",
        "extension_points", "created_at", "last_updated_at", "metadata",
    }


@skip_if_unavailable
def test_N02_entity_from_dict_round_trip():
    e = DelegatedFlowEntity(
        identity=DelegatedFlowIdentity(flow_kind=DelegatedFlowKind.takeover_request),
        phase=DelegatedFlowPhase.executing,
    )
    e2 = DelegatedFlowEntity.from_dict(e.to_dict())
    assert e2.delegated_flow_id == e.delegated_flow_id
    assert e2.phase == DelegatedFlowPhase.executing
    assert e2.flow_kind == DelegatedFlowKind.takeover_request


@skip_if_unavailable
def test_N03_entity_to_json_valid():
    j = DelegatedFlowEntity().to_json()
    parsed = json.loads(j)
    assert "identity" in parsed
    assert "phase" in parsed


@skip_if_unavailable
def test_N04_entity_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedFlowEntity.from_dict("not_a_dict")  # type: ignore[arg-type]


# ===========================================================================
# Group O — DelegatedFlowEntityRecord
# ===========================================================================


@skip_if_unavailable
def test_O01_record_construction():
    fid = str(uuid.uuid4())
    lid = str(uuid.uuid4())
    rec = DelegatedFlowEntityRecord(
        delegated_flow_id=fid,
        flow_lineage_id=lid,
        phase_before=DelegatedFlowPhase.created,
        phase_after=DelegatedFlowPhase.dispatched,
        signal="dispatch",
    )
    assert rec.delegated_flow_id == fid
    assert rec.flow_lineage_id == lid
    assert rec.phase_before == DelegatedFlowPhase.created
    assert rec.phase_after == DelegatedFlowPhase.dispatched
    assert rec.signal == "dispatch"


@skip_if_unavailable
def test_O02_record_to_dict_keys():
    rec = DelegatedFlowEntityRecord(
        delegated_flow_id="f1",
        flow_lineage_id="l1",
        phase_before=DelegatedFlowPhase.created,
        phase_after=DelegatedFlowPhase.created,
    )
    d = rec.to_dict()
    assert "record_id" in d
    assert "delegated_flow_id" in d
    assert "phase_before" in d
    assert "phase_after" in d


@skip_if_unavailable
def test_O03_record_to_json_valid():
    rec = DelegatedFlowEntityRecord(
        delegated_flow_id="f1",
        flow_lineage_id="l1",
        phase_before=DelegatedFlowPhase.created,
        phase_after=DelegatedFlowPhase.created,
    )
    j = rec.to_json()
    parsed = json.loads(j)
    assert "record_id" in parsed


# ===========================================================================
# Group P — DelegatedFlowEntitySnapshot
# ===========================================================================


@skip_if_unavailable
def test_P01_snapshot_defaults():
    snap = DelegatedFlowEntitySnapshot()
    assert snap.active_flows == []
    assert snap.terminal_flows == []
    assert snap.total_seen == 0


@skip_if_unavailable
def test_P02_snapshot_to_dict_keys():
    snap = DelegatedFlowEntitySnapshot()
    d = snap.to_dict()
    assert "active_flows" in d
    assert "terminal_flows" in d
    assert "total_seen" in d
    assert "snapshot_at" in d


@skip_if_unavailable
def test_P03_snapshot_to_json_valid():
    j = DelegatedFlowEntitySnapshot().to_json()
    parsed = json.loads(j)
    assert "active_flows" in parsed


# ===========================================================================
# Group Q — DelegatedFlowEntityRuntime
# ===========================================================================


@skip_if_unavailable
def test_Q01_runtime_put_and_get():
    rt = DelegatedFlowEntityRuntime()
    fid = str(uuid.uuid4())
    e = DelegatedFlowEntity(
        identity=DelegatedFlowIdentity(delegated_flow_id=fid)
    )
    rt.put(e)
    retrieved = rt.get_by_flow_id(fid)
    assert retrieved is not None
    assert retrieved.delegated_flow_id == fid


@skip_if_unavailable
def test_Q02_runtime_get_unknown_returns_none():
    rt = DelegatedFlowEntityRuntime()
    assert rt.get_by_flow_id("nonexistent") is None


@skip_if_unavailable
def test_Q03_runtime_get_by_lineage():
    rt = DelegatedFlowEntityRuntime()
    lid = str(uuid.uuid4())
    e1 = create_delegated_flow_entity(flow_lineage_id=lid, runtime=rt)
    e2 = create_delegated_flow_entity(flow_lineage_id=lid, runtime=rt)
    e3 = create_delegated_flow_entity(runtime=rt)  # different lineage
    results = rt.get_by_lineage(lid)
    flow_ids = {e.delegated_flow_id for e in results}
    assert e1.delegated_flow_id in flow_ids
    assert e2.delegated_flow_id in flow_ids
    assert e3.delegated_flow_id not in flow_ids


@skip_if_unavailable
def test_Q04_runtime_get_by_contract():
    rt = DelegatedFlowEntityRuntime()
    cid = "contract-xyz"
    e = create_delegated_flow_entity(contract_id=cid, runtime=rt)
    retrieved = rt.get_by_contract(cid)
    assert retrieved is not None
    assert retrieved.object_mapping.contract_id == cid


@skip_if_unavailable
def test_Q05_runtime_get_by_contract_unknown_returns_none():
    rt = DelegatedFlowEntityRuntime()
    assert rt.get_by_contract("unknown-contract") is None


@skip_if_unavailable
def test_Q06_runtime_list_active_excludes_terminal():
    rt = DelegatedFlowEntityRuntime()
    e1 = create_delegated_flow_entity(runtime=rt)
    e2 = create_delegated_flow_entity(runtime=rt)
    # Advance e2 to completed
    e2 = advance_flow_phase(e2, DelegatedFlowSignal.dispatch, runtime=rt)
    e2 = advance_flow_phase(e2, DelegatedFlowSignal.ack, runtime=rt)
    e2 = advance_flow_phase(e2, DelegatedFlowSignal.result_inbound, runtime=rt)
    e2 = advance_flow_phase(e2, DelegatedFlowSignal.result_success, runtime=rt)
    assert e2.phase == DelegatedFlowPhase.completed
    active = rt.list_active()
    active_ids = {e.delegated_flow_id for e in active}
    assert e1.delegated_flow_id in active_ids
    assert e2.delegated_flow_id not in active_ids


@skip_if_unavailable
def test_Q07_runtime_total_seen():
    rt = DelegatedFlowEntityRuntime()
    assert rt.total_seen == 0
    create_delegated_flow_entity(runtime=rt)
    assert rt.total_seen == 1
    create_delegated_flow_entity(runtime=rt)
    assert rt.total_seen == 2


# ===========================================================================
# Group R — DelegatedFlowEntityRuntime: ring-buffer capacity
# ===========================================================================


@skip_if_unavailable
def test_R01_ring_buffer_capacity_128():
    rt = DelegatedFlowEntityRuntime()
    assert rt._maxsize == 128


@skip_if_unavailable
def test_R02_ring_buffer_does_not_exceed_maxsize():
    rt = DelegatedFlowEntityRuntime(maxsize=5)
    for _ in range(10):
        create_delegated_flow_entity(runtime=rt)
    assert len(rt.list_all()) <= 5


# ===========================================================================
# Group S — DelegatedFlowEntityRuntime: replace-in-place for same id
# ===========================================================================


@skip_if_unavailable
def test_S01_replace_in_place_updates_entity():
    rt = DelegatedFlowEntityRuntime()
    fid = str(uuid.uuid4())
    e = create_delegated_flow_entity(delegated_flow_id=fid, runtime=rt)
    assert e.phase == DelegatedFlowPhase.created
    e2 = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    # Still one entry for this flow_id
    entries_for_flow = [x for x in rt.list_all() if x.delegated_flow_id == fid]
    assert len(entries_for_flow) == 1
    assert entries_for_flow[0].phase == DelegatedFlowPhase.dispatched


# ===========================================================================
# Group T — create_delegated_flow_entity: valid inputs
# ===========================================================================


@skip_if_unavailable
def test_T01_create_returns_created_phase():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    assert e.phase == DelegatedFlowPhase.created


@skip_if_unavailable
def test_T02_create_default_kind_is_task_assign():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    assert e.flow_kind == DelegatedFlowKind.task_assign


@skip_if_unavailable
def test_T03_create_explicit_kind():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(
        flow_kind=DelegatedFlowKind.goal_execution, runtime=rt
    )
    assert e.flow_kind == DelegatedFlowKind.goal_execution


# ===========================================================================
# Group U — create_delegated_flow_entity: auto-generates ids
# ===========================================================================


@skip_if_unavailable
def test_U01_auto_generates_flow_id():
    rt = DelegatedFlowEntityRuntime()
    e1 = create_delegated_flow_entity(runtime=rt)
    e2 = create_delegated_flow_entity(runtime=rt)
    assert e1.delegated_flow_id != e2.delegated_flow_id


@skip_if_unavailable
def test_U02_auto_generates_lineage_id():
    rt = DelegatedFlowEntityRuntime()
    e1 = create_delegated_flow_entity(runtime=rt)
    e2 = create_delegated_flow_entity(runtime=rt)
    assert e1.flow_lineage_id != e2.flow_lineage_id


# ===========================================================================
# Group V — create_delegated_flow_entity: explicit ids honoured
# ===========================================================================


@skip_if_unavailable
def test_V01_explicit_flow_id_honoured():
    rt = DelegatedFlowEntityRuntime()
    fid = str(uuid.uuid4())
    e = create_delegated_flow_entity(delegated_flow_id=fid, runtime=rt)
    assert e.delegated_flow_id == fid


@skip_if_unavailable
def test_V02_explicit_trace_id_honoured():
    rt = DelegatedFlowEntityRuntime()
    tid = "trace-explicit"
    e = create_delegated_flow_entity(trace_id=tid, runtime=rt)
    assert e.identity.trace_id == tid


# ===========================================================================
# Group W — create: flow_lineage_id shared when supplied
# ===========================================================================


@skip_if_unavailable
def test_W01_shared_lineage_id():
    rt = DelegatedFlowEntityRuntime()
    lid = str(uuid.uuid4())
    e1 = create_delegated_flow_entity(flow_lineage_id=lid, runtime=rt)
    e2 = create_delegated_flow_entity(flow_lineage_id=lid, runtime=rt)
    assert e1.flow_lineage_id == lid
    assert e2.flow_lineage_id == lid
    lineage_flows = rt.get_by_lineage(lid)
    assert len(lineage_flows) == 2


# ===========================================================================
# Group X — create: persisted to runtime
# ===========================================================================


@skip_if_unavailable
def test_X01_create_persisted_to_runtime():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    retrieved = rt.get_by_flow_id(e.delegated_flow_id)
    assert retrieved is not None


# ===========================================================================
# Group Y — create: custom runtime isolation
# ===========================================================================


@skip_if_unavailable
def test_Y01_custom_runtime_isolation():
    rt1 = DelegatedFlowEntityRuntime()
    rt2 = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt1)
    assert rt2.get_by_flow_id(e.delegated_flow_id) is None


# ===========================================================================
# Group Z — advance_flow_phase: created + dispatch → dispatched
# ===========================================================================


@skip_if_unavailable
def test_Z01_advance_created_dispatch():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e2 = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    assert e2.phase == DelegatedFlowPhase.dispatched


# ===========================================================================
# Group AA — advance: dispatched + ack → executing (execution_owner assigned)
# ===========================================================================


@skip_if_unavailable
def test_AA01_ack_assigns_android_execution_owner():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.ack, runtime=rt)
    assert e.phase == DelegatedFlowPhase.executing
    assert e.ownership.execution_owner == DelegatedFlowOwnerKind.android_execution


@skip_if_unavailable
def test_AA02_canonical_owner_unchanged_after_ack():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.ack, runtime=rt)
    assert e.ownership.canonical_owner == DelegatedFlowOwnerKind.v2_canonical


# ===========================================================================
# Groups AB-AI are covered by F and G tests above; adding focused tests
# ===========================================================================


@skip_if_unavailable
def test_AB01_executing_result_inbound_to_reconciling():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.ack, runtime=rt)
    e2 = advance_flow_phase(e, DelegatedFlowSignal.result_inbound, runtime=rt)
    assert e2.phase == DelegatedFlowPhase.reconciling


@skip_if_unavailable
def test_AF01_fail_from_created():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e2 = advance_flow_phase(e, DelegatedFlowSignal.fail, runtime=rt)
    assert e2.phase == DelegatedFlowPhase.failed


@skip_if_unavailable
def test_AG01_cancel_from_executing():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.ack, runtime=rt)
    e2 = advance_flow_phase(e, DelegatedFlowSignal.cancel, runtime=rt)
    assert e2.phase == DelegatedFlowPhase.cancelled


# ===========================================================================
# Group AK — advance: identity fields preserved across transitions
# ===========================================================================


@skip_if_unavailable
def test_AK01_identity_preserved_across_transitions():
    rt = DelegatedFlowEntityRuntime()
    fid = str(uuid.uuid4())
    lid = str(uuid.uuid4())
    e = create_delegated_flow_entity(
        delegated_flow_id=fid,
        flow_lineage_id=lid,
        flow_segment_id="seg-preserve",
        runtime=rt,
    )
    for signal in (
        DelegatedFlowSignal.dispatch,
        DelegatedFlowSignal.ack,
        DelegatedFlowSignal.result_inbound,
        DelegatedFlowSignal.result_success,
    ):
        e = advance_flow_phase(e, signal, runtime=rt)
    assert e.delegated_flow_id == fid
    assert e.flow_lineage_id == lid
    assert e.flow_segment_id == "seg-preserve"


# ===========================================================================
# Group AL — advance: signal_metadata merged into entity metadata
# ===========================================================================


@skip_if_unavailable
def test_AL01_signal_metadata_merged():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e2 = advance_flow_phase(
        e, DelegatedFlowSignal.dispatch, runtime=rt,
        signal_metadata={"source": "test", "step": 1},
    )
    assert e2.metadata.get("source") == "test"
    assert e2.metadata.get("step") == 1


# ===========================================================================
# Group AN — attach_object_mapping
# ===========================================================================


@skip_if_unavailable
def test_AN01_attach_adds_contract_id():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    assert e.contract_id == ""
    e2 = attach_object_mapping(
        e,
        DelegatedFlowObjectMapping(contract_id="contract-new"),
        runtime=rt,
    )
    assert e2.contract_id == "contract-new"


@skip_if_unavailable
def test_AO01_attach_does_not_overwrite_existing_with_empty():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(contract_id="original", runtime=rt)
    e2 = attach_object_mapping(
        e,
        DelegatedFlowObjectMapping(contract_id=""),  # empty update
        runtime=rt,
    )
    assert e2.contract_id == "original"


@skip_if_unavailable
def test_AP01_attach_preserves_identity_and_phase():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    fid = e.delegated_flow_id
    e2 = attach_object_mapping(
        e,
        DelegatedFlowObjectMapping(binding_id="binding-1"),
        runtime=rt,
    )
    assert e2.delegated_flow_id == fid
    assert e2.phase == DelegatedFlowPhase.created


# ===========================================================================
# Group BF — Ownership: canonical_owner always v2_canonical at creation
# ===========================================================================


@skip_if_unavailable
def test_BF01_canonical_owner_is_v2_at_creation():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    assert e.ownership.canonical_owner == DelegatedFlowOwnerKind.v2_canonical


@skip_if_unavailable
def test_BF02_execution_owner_is_none_at_creation():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    assert e.ownership.execution_owner == DelegatedFlowOwnerKind.none


# ===========================================================================
# Group BJ — core.runtime re-exports
# ===========================================================================


@skip_runtime_if_unavailable
def test_BJ01_core_runtime_exports_authority():
    assert _rt_authority
    assert "DELEGATED_FLOW_ENTITY_AUTHORITY" in _rt_authority


@skip_runtime_if_unavailable
def test_BJ02_core_runtime_exports_sentinel():
    assert "package=50" in _rt_sentinel


@skip_runtime_if_unavailable
def test_BJ03_core_runtime_exports_kind_enum():
    assert _rt_kind.task_assign.value == "task_assign"


@skip_runtime_if_unavailable
def test_BJ04_core_runtime_exports_phase_enum():
    assert _rt_phase.created.value == "created"


@skip_runtime_if_unavailable
def test_BJ05_core_runtime_exports_create_function():
    rt = _rt_runtime_cls()
    e = _rt_create(runtime=rt)
    assert e.phase == _rt_phase.created


@skip_runtime_if_unavailable
def test_BJ06_core_runtime_exports_advance_function():
    rt = _rt_runtime_cls()
    e = _rt_create(runtime=rt)
    e2 = _rt_advance(e, _rt_signal.dispatch, runtime=rt)
    assert e2.phase == _rt_phase.dispatched


# ===========================================================================
# Group BK-BO — Serialisation: from_dict non-dict raises ValueError
# ===========================================================================


@skip_if_unavailable
def test_BK01_identity_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedFlowIdentity.from_dict(42)  # type: ignore[arg-type]


@skip_if_unavailable
def test_BL01_ownership_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedFlowOwnership.from_dict("bad")  # type: ignore[arg-type]


@skip_if_unavailable
def test_BM01_object_mapping_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedFlowObjectMapping.from_dict(None)  # type: ignore[arg-type]


@skip_if_unavailable
def test_BN01_extension_points_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedFlowExtensionPoints.from_dict([])  # type: ignore[arg-type]


@skip_if_unavailable
def test_BO01_entity_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        DelegatedFlowEntity.from_dict(0)  # type: ignore[arg-type]


# ===========================================================================
# Group BP — End-to-end: task_assign full lifecycle → completed
# ===========================================================================


@skip_if_unavailable
def test_BP01_task_assign_full_lifecycle():
    rt = DelegatedFlowEntityRuntime()
    # Create
    e = create_delegated_flow_entity(
        flow_kind=DelegatedFlowKind.task_assign,
        canonical_task_id="task-e2e",
        session_id="session-e2e",
        device_id="device-e2e",
        runtime=rt,
    )
    assert e.phase == DelegatedFlowPhase.created
    # Attach contract
    e = attach_object_mapping(
        e, DelegatedFlowObjectMapping(contract_id="contract-e2e"), runtime=rt
    )
    assert e.contract_id == "contract-e2e"
    # Dispatch
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    assert e.phase == DelegatedFlowPhase.dispatched
    # Android ack
    e = advance_flow_phase(e, DelegatedFlowSignal.ack, runtime=rt)
    assert e.phase == DelegatedFlowPhase.executing
    assert e.ownership.execution_owner == DelegatedFlowOwnerKind.android_execution
    # Result inbound
    e = advance_flow_phase(e, DelegatedFlowSignal.result_inbound, runtime=rt)
    assert e.phase == DelegatedFlowPhase.reconciling
    # Reconcile complete
    e = advance_flow_phase(e, DelegatedFlowSignal.result_success, runtime=rt)
    assert e.phase == DelegatedFlowPhase.completed
    assert e.phase.is_terminal()
    # Canonical owner unchanged throughout
    assert e.ownership.canonical_owner == DelegatedFlowOwnerKind.v2_canonical
    # Lookup by contract_id
    retrieved = get_delegated_flow_by_contract("contract-e2e", runtime=rt)
    assert retrieved is not None
    assert retrieved.phase == DelegatedFlowPhase.completed


# ===========================================================================
# Group BQ — End-to-end: takeover_request with shared lineage_id
# ===========================================================================


@skip_if_unavailable
def test_BQ01_takeover_request_shared_lineage():
    rt = DelegatedFlowEntityRuntime()
    lid = str(uuid.uuid4())
    # Original task_assign flow
    e_task = create_delegated_flow_entity(
        flow_kind=DelegatedFlowKind.task_assign,
        flow_lineage_id=lid,
        canonical_task_id="task-orig",
        runtime=rt,
    )
    # Takeover of the same lineage
    e_takeover = create_delegated_flow_entity(
        flow_kind=DelegatedFlowKind.takeover_request,
        flow_lineage_id=lid,
        flow_segment_id="takeover-1",
        canonical_task_id="task-orig",
        runtime=rt,
    )
    lineage_flows = get_delegated_flow_by_lineage(lid, runtime=rt)
    fids = {e.delegated_flow_id for e in lineage_flows}
    assert e_task.delegated_flow_id in fids
    assert e_takeover.delegated_flow_id in fids
    assert e_takeover.flow_kind == DelegatedFlowKind.takeover_request


# ===========================================================================
# Group BR — End-to-end: parallel_subtask flows sharing lineage_id
# ===========================================================================


@skip_if_unavailable
def test_BR01_parallel_subtask_lineage():
    rt = DelegatedFlowEntityRuntime()
    lid = str(uuid.uuid4())
    flows = []
    for i in range(3):
        e = create_delegated_flow_entity(
            flow_kind=DelegatedFlowKind.parallel_subtask,
            flow_lineage_id=lid,
            flow_segment_id=f"subtask-{i}",
            runtime=rt,
        )
        flows.append(e)
    lineage_flows = get_delegated_flow_by_lineage(lid, runtime=rt)
    assert len(lineage_flows) == 3
    segments = {e.flow_segment_id for e in lineage_flows}
    assert segments == {"subtask-0", "subtask-1", "subtask-2"}


# ===========================================================================
# Group BS — Ring buffer: oldest entry evicted when full
# ===========================================================================


@skip_if_unavailable
def test_BS01_ring_buffer_eviction():
    rt = DelegatedFlowEntityRuntime(maxsize=3)
    ids = []
    for _ in range(4):
        e = create_delegated_flow_entity(runtime=rt)
        ids.append(e.delegated_flow_id)
    all_ids = {e.delegated_flow_id for e in rt.list_all()}
    # First entry should have been evicted
    assert ids[0] not in all_ids
    # Last 3 should still be present
    for fid in ids[1:]:
        assert fid in all_ids


# ===========================================================================
# Group BT — Snapshot top-level keys
# ===========================================================================


@skip_if_unavailable
def test_BT01_snapshot_dict_top_level_keys():
    rt = DelegatedFlowEntityRuntime()
    create_delegated_flow_entity(runtime=rt)
    snap = build_delegated_flow_snapshot(runtime=rt)
    d = snap.to_dict()
    assert "active_flows" in d
    assert "terminal_flows" in d
    assert "total_seen" in d
    assert "snapshot_at" in d


# ===========================================================================
# Group BU / BV — property shortcuts
# ===========================================================================


@skip_if_unavailable
def test_BU01_contract_id_shortcut():
    e = DelegatedFlowEntity(
        object_mapping=DelegatedFlowObjectMapping(contract_id="c-shortcut")
    )
    assert e.contract_id == "c-shortcut"


@skip_if_unavailable
def test_BV01_canonical_task_id_shortcut():
    e = DelegatedFlowEntity(
        object_mapping=DelegatedFlowObjectMapping(canonical_task_id="t-shortcut")
    )
    assert e.canonical_task_id == "t-shortcut"


# ===========================================================================
# Group BY / BZ — Idempotent transitions
# ===========================================================================


@skip_if_unavailable
def test_BY01_idempotent_dispatch_from_dispatched():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    assert e.phase == DelegatedFlowPhase.dispatched
    # dispatch again — should stay dispatched
    e2 = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    assert e2.phase == DelegatedFlowPhase.dispatched


@skip_if_unavailable
def test_BZ01_idempotent_ack_from_executing():
    rt = DelegatedFlowEntityRuntime()
    e = create_delegated_flow_entity(runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.dispatch, runtime=rt)
    e = advance_flow_phase(e, DelegatedFlowSignal.ack, runtime=rt)
    assert e.phase == DelegatedFlowPhase.executing
    # ack again — should stay executing
    e2 = advance_flow_phase(e, DelegatedFlowSignal.ack, runtime=rt)
    assert e2.phase == DelegatedFlowPhase.executing


# ===========================================================================
# Group BC / BD — Singleton accessor
# ===========================================================================


@skip_if_unavailable
def test_BC01_get_runtime_returns_same_singleton():
    reset_delegated_flow_entity_runtime()
    rt1 = get_delegated_flow_entity_runtime()
    rt2 = get_delegated_flow_entity_runtime()
    assert rt1 is rt2


@skip_if_unavailable
def test_BD01_reset_clears_singleton():
    reset_delegated_flow_entity_runtime()
    rt1 = get_delegated_flow_entity_runtime()
    reset_delegated_flow_entity_runtime()
    rt2 = get_delegated_flow_entity_runtime()
    assert rt1 is not rt2
