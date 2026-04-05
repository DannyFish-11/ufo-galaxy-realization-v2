"""tests/test_pr8_post533_delegated_runtime_dispatch_intent.py
==============================================================
Tests for PR package 8 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Delegated-Runtime Dispatch Intent and
Handoff-Preparation Foundations.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — DelegationIntent enum: all values present, from_string(), defaults.
C  — HandoffPreparationState enum: all values present, from_string(),
     is_terminal(), is_actionable(), can_advance_to().
D  — DispatchEligibilityOutcome: construction, defaults, to_dict(), to_json().
E  — HandoffInputBundle: construction, defaults, to_dict(), to_json().
F  — DelegatedRuntimeDispatchRecord: construction, defaults, to_dict(),
     to_json(), from_dict(), is_accepted(), is_rejected(), is_pending().
G  — DelegatedRuntimeDispatchSnapshot: construction, defaults, to_dict(),
     to_json().
H  — DelegatedRuntimeDispatchRuntime: push, list_all, list_pending,
     get_latest_for_session, clear, size, capacity.
I  — evaluate_dispatch_eligibility: join_runtime + valid session → eligible.
J  — evaluate_dispatch_eligibility: empty session_id → ineligible (policy).
K  — evaluate_dispatch_eligibility: control_only posture → ineligible.
L  — evaluate_dispatch_eligibility: observer_only role → ineligible.
M  — evaluate_dispatch_eligibility: target_only_executor role → ineligible.
N  — evaluate_dispatch_eligibility: command_only tier + delegate → relay downgrade.
O  — evaluate_dispatch_eligibility: full_runtime tier → full delegate permitted.
P  — evaluate_dispatch_eligibility: partial_runtime tier → full delegate permitted.
Q  — evaluate_dispatch_eligibility: unknown tier → full delegate permitted.
R  — build_delegated_dispatch_record: join_runtime + valid → accepted record.
S  — build_delegated_dispatch_record: control_only → rejected record.
T  — build_delegated_dispatch_record: empty session_id → rejected record.
U  — build_delegated_dispatch_record: observer_only role → rejected.
V  — build_delegated_dispatch_record: target_only_executor → rejected.
W  — build_delegated_dispatch_record: command_only tier + delegate → relay accepted.
X  — build_delegated_dispatch_record: android_host_role carried.
Y  — build_delegated_dispatch_record: continuation_hint propagated.
Z  — build_delegated_dispatch_record: metadata propagated.
AA — build_delegated_dispatch_record: persisted to runtime.
AB — build_delegated_dispatch_record: custom runtime isolation.
AC — prepare_handoff_inputs: anchored bundle from accepted record.
AD — prepare_handoff_inputs: is_session_anchored=False when session_id empty.
AE — prepare_handoff_inputs: override_continuation_hint applied.
AF — prepare_handoff_inputs: posture/role/tier carried into bundle.
AG — record_delegated_dispatch_intent: persists record to runtime.
AH — get_delegated_dispatch_record: returns most recent for session_id.
AI — get_delegated_dispatch_record: returns None for unknown session_id.
AJ — list_pending_delegated_dispatch_records: returns preparing+ready only.
AK — list_pending_delegated_dispatch_records: empty when no pending.
AL — build_delegated_dispatch_snapshot: counts pending and total.
AM — build_delegated_dispatch_snapshot: includes policy sentinels.
AN — build_delegated_dispatch_snapshot: empty runtime → zero counts.
AO — core.runtime re-exports: all PR-8 symbols accessible from core.runtime.
AP — projection.py sentinel: DELEGATED_RUNTIME_DISPATCH_INTENT_ALIGNED_PR8
     is present and not UNAVAILABLE.
AQ — Ring buffer capacity: 128.
AR — Ring buffer eviction: oldest entry evicted when full.
AS — Serialisation round-trip: DelegatedRuntimeDispatchRecord to_dict → from_dict.
AT — Serialisation round-trip: to_json produces valid JSON.
AU — Serialisation: from_dict with non-dict raises ValueError.
AV — Multiple sessions: each gets its own record.
AW — DelegationIntent.from_string: unknown string → none.
AX — HandoffPreparationState.from_string: unknown string → not_started.
AY — Snapshot snapshotted_at is recent timestamp.
AZ — All 10 policy sentinels non-empty strings.
BA — evaluate_dispatch_eligibility: relay intent → relay accepted with valid inputs.
BB — evaluate_dispatch_eligibility: observe intent → observe accepted.
BC — evaluate_dispatch_eligibility: none intent → eligible with resolved=none.
BD — build_delegated_dispatch_record: preparation_state=ready accepted.
BE — build_delegated_dispatch_record: rejected record has preparation_state=cancelled.
BF — Record ID is auto-generated UUID and unique per record.
BG — Snapshot ID is auto-generated UUID and unique per snapshot.
BH — HandoffInputBundle record_id matches dispatch record record_id.
BI — DispatchEligibilityOutcome to_dict contains expected keys.
BJ — DelegatedRuntimeDispatchRecord from_dict: missing fields use safe defaults.
BK — list_pending: includes both preparing and ready, excludes dispatched/cancelled/failed.
BL — build_delegated_dispatch_snapshot: records are newest-first.
BM — reset_delegated_runtime_dispatch_runtime: clears singleton for isolation.
BN — get_delegated_runtime_dispatch_runtime: returns same singleton.
BO — DelegationIntent enum string values match expected lowercase strings.
BP — HandoffPreparationState enum string values match expected lowercase strings.
BQ — evaluate_dispatch_eligibility: blocking_reason non-empty when ineligible.
BR — Snapshot to_dict contains 'records', 'pending_count', 'total_count'.
BS — Record to_dict: reject_reason empty when accepted.
BT — Record to_dict: eligibility_outcome present when record is from build function.
BU — Two separate sessions: list_pending returns both when both pending.
BV — prepare_handoff_inputs: bundle metadata matches record metadata.
BW — build_delegated_dispatch_record: does not mutate other records in runtime.
BX — end-to-end: attach session → evaluate eligibility → build record → prepare inputs.
BY — DELEGATED_RUNTIME_DISPATCH_INTENT_PR8_SENTINEL contains 'package=8'.
BZ — HandoffPreparationState.can_advance_to: terminal → False.
CA — HandoffPreparationState.can_advance_to: not_started → preparing → True.
CB — HandoffPreparationState.can_advance_to: ready → not_started → False (regression).
CC — from_dict: serialised eligibility_outcome is reconstructed.
CD — record_id is stable across to_dict/from_dict round-trip.
CE — DelegatedRuntimeDispatchRuntime: clear() empties the buffer.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest

from core.delegated_runtime_dispatch_intent import (
    COMMAND_ONLY_TIER_BLOCKS_FULL_DELEGATION_POLICY,
    DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY,
    DELEGATED_RUNTIME_DISPATCH_INTENT_PR8_SENTINEL,
    DELEGATION_INTENT_IS_ADDITIVE_TO_SESSION_POLICY,
    DELEGATION_REQUIRES_ATTACHED_SESSION_POLICY,
    DELEGATION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    DISPATCH_RECORD_IS_IMMUTABLE_POLICY,
    HANDOFF_INPUTS_MUST_BE_SESSION_ANCHORED_POLICY,
    OBSERVER_ONLY_ROLE_BLOCKS_DELEGATION_POLICY,
    PREPARATION_STATE_IS_MONOTONICALLY_ADVANCING_POLICY,
    TARGET_ONLY_EXECUTOR_CANNOT_DELEGATE_POLICY,
    DelegatedRuntimeDispatchRecord,
    DelegatedRuntimeDispatchRuntime,
    DelegatedRuntimeDispatchSnapshot,
    DelegationIntent,
    DispatchEligibilityOutcome,
    HandoffInputBundle,
    HandoffPreparationState,
    build_delegated_dispatch_record,
    build_delegated_dispatch_snapshot,
    evaluate_dispatch_eligibility,
    get_delegated_dispatch_record,
    get_delegated_runtime_dispatch_runtime,
    list_pending_delegated_dispatch_records,
    prepare_handoff_inputs,
    record_delegated_dispatch_intent,
    reset_delegated_runtime_dispatch_runtime,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_runtime() -> DelegatedRuntimeDispatchRuntime:
    return DelegatedRuntimeDispatchRuntime()


def _make_session_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Group A — Authority / policy sentinels
# ---------------------------------------------------------------------------

class TestGroupA:
    def test_A1_authority_non_empty(self):
        assert isinstance(DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY, str)
        assert len(DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY) > 0

    def test_A2_delegation_requires_attached_session_policy(self):
        assert isinstance(DELEGATION_REQUIRES_ATTACHED_SESSION_POLICY, str)
        assert len(DELEGATION_REQUIRES_ATTACHED_SESSION_POLICY) > 0

    def test_A3_delegation_requires_join_runtime_posture_policy(self):
        assert isinstance(DELEGATION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY, str)
        assert len(DELEGATION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY) > 0

    def test_A4_observer_only_blocks_delegation_policy(self):
        assert isinstance(OBSERVER_ONLY_ROLE_BLOCKS_DELEGATION_POLICY, str)
        assert len(OBSERVER_ONLY_ROLE_BLOCKS_DELEGATION_POLICY) > 0

    def test_A5_target_only_executor_cannot_delegate_policy(self):
        assert isinstance(TARGET_ONLY_EXECUTOR_CANNOT_DELEGATE_POLICY, str)
        assert len(TARGET_ONLY_EXECUTOR_CANNOT_DELEGATE_POLICY) > 0

    def test_A6_command_only_tier_blocks_full_delegation_policy(self):
        assert isinstance(COMMAND_ONLY_TIER_BLOCKS_FULL_DELEGATION_POLICY, str)
        assert len(COMMAND_ONLY_TIER_BLOCKS_FULL_DELEGATION_POLICY) > 0

    def test_A7_handoff_inputs_must_be_session_anchored_policy(self):
        assert isinstance(HANDOFF_INPUTS_MUST_BE_SESSION_ANCHORED_POLICY, str)
        assert len(HANDOFF_INPUTS_MUST_BE_SESSION_ANCHORED_POLICY) > 0

    def test_A8_delegation_intent_is_additive_policy(self):
        assert isinstance(DELEGATION_INTENT_IS_ADDITIVE_TO_SESSION_POLICY, str)
        assert len(DELEGATION_INTENT_IS_ADDITIVE_TO_SESSION_POLICY) > 0

    def test_A9_dispatch_record_is_immutable_policy(self):
        assert isinstance(DISPATCH_RECORD_IS_IMMUTABLE_POLICY, str)
        assert len(DISPATCH_RECORD_IS_IMMUTABLE_POLICY) > 0

    def test_A10_preparation_state_monotonically_advancing_policy(self):
        assert isinstance(PREPARATION_STATE_IS_MONOTONICALLY_ADVANCING_POLICY, str)
        assert len(PREPARATION_STATE_IS_MONOTONICALLY_ADVANCING_POLICY) > 0

    def test_AZ_all_10_sentinels_non_empty(self):
        sentinels = [
            DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY,
            DELEGATION_REQUIRES_ATTACHED_SESSION_POLICY,
            DELEGATION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
            OBSERVER_ONLY_ROLE_BLOCKS_DELEGATION_POLICY,
            TARGET_ONLY_EXECUTOR_CANNOT_DELEGATE_POLICY,
            COMMAND_ONLY_TIER_BLOCKS_FULL_DELEGATION_POLICY,
            HANDOFF_INPUTS_MUST_BE_SESSION_ANCHORED_POLICY,
            DELEGATION_INTENT_IS_ADDITIVE_TO_SESSION_POLICY,
            DISPATCH_RECORD_IS_IMMUTABLE_POLICY,
            PREPARATION_STATE_IS_MONOTONICALLY_ADVANCING_POLICY,
        ]
        assert len(sentinels) == 10
        for s in sentinels:
            assert isinstance(s, str) and len(s) > 0


# ---------------------------------------------------------------------------
# Group B — DelegationIntent enum
# ---------------------------------------------------------------------------

class TestGroupB:
    def test_B1_all_values_present(self):
        values = {m.value for m in DelegationIntent}
        assert values == {"delegate", "relay", "observe", "none"}

    def test_B2_from_string_delegate(self):
        assert DelegationIntent.from_string("delegate") == DelegationIntent.delegate

    def test_B3_from_string_relay(self):
        assert DelegationIntent.from_string("relay") == DelegationIntent.relay

    def test_B4_from_string_observe(self):
        assert DelegationIntent.from_string("observe") == DelegationIntent.observe

    def test_B5_from_string_none(self):
        assert DelegationIntent.from_string("none") == DelegationIntent.none

    def test_B6_from_string_unknown_defaults_none(self):
        assert DelegationIntent.from_string("bogus") == DelegationIntent.none

    def test_B7_from_string_uppercase_normalised(self):
        assert DelegationIntent.from_string("DELEGATE") == DelegationIntent.delegate

    def test_B8_from_string_non_string_defaults_none(self):
        assert DelegationIntent.from_string(None) == DelegationIntent.none  # type: ignore[arg-type]

    def test_BO_string_values_match_lowercase(self):
        assert DelegationIntent.delegate.value == "delegate"
        assert DelegationIntent.relay.value == "relay"
        assert DelegationIntent.observe.value == "observe"
        assert DelegationIntent.none.value == "none"


# ---------------------------------------------------------------------------
# Group C — HandoffPreparationState enum
# ---------------------------------------------------------------------------

class TestGroupC:
    def test_C1_all_values_present(self):
        values = {m.value for m in HandoffPreparationState}
        assert values == {
            "not_started", "preparing", "ready", "dispatched", "cancelled", "failed"
        }

    def test_C2_from_string_not_started(self):
        assert (
            HandoffPreparationState.from_string("not_started")
            == HandoffPreparationState.not_started
        )

    def test_C3_from_string_preparing(self):
        assert (
            HandoffPreparationState.from_string("preparing")
            == HandoffPreparationState.preparing
        )

    def test_C4_from_string_ready(self):
        assert HandoffPreparationState.from_string("ready") == HandoffPreparationState.ready

    def test_C5_from_string_dispatched(self):
        assert (
            HandoffPreparationState.from_string("dispatched")
            == HandoffPreparationState.dispatched
        )

    def test_C6_from_string_cancelled(self):
        assert (
            HandoffPreparationState.from_string("cancelled")
            == HandoffPreparationState.cancelled
        )

    def test_C7_from_string_failed(self):
        assert HandoffPreparationState.from_string("failed") == HandoffPreparationState.failed

    def test_C8_from_string_unknown_defaults_not_started(self):
        assert (
            HandoffPreparationState.from_string("bogus")
            == HandoffPreparationState.not_started
        )

    def test_C9_is_terminal_dispatched(self):
        assert HandoffPreparationState.dispatched.is_terminal() is True

    def test_C10_is_terminal_cancelled(self):
        assert HandoffPreparationState.cancelled.is_terminal() is True

    def test_C11_is_terminal_failed(self):
        assert HandoffPreparationState.failed.is_terminal() is True

    def test_C12_is_terminal_not_started_false(self):
        assert HandoffPreparationState.not_started.is_terminal() is False

    def test_C13_is_actionable_not_started(self):
        assert HandoffPreparationState.not_started.is_actionable() is True

    def test_C14_is_actionable_preparing(self):
        assert HandoffPreparationState.preparing.is_actionable() is True

    def test_C15_is_actionable_ready_false(self):
        assert HandoffPreparationState.ready.is_actionable() is False

    def test_BZ_can_advance_to_terminal_from_terminal_false(self):
        assert HandoffPreparationState.dispatched.can_advance_to(
            HandoffPreparationState.ready
        ) is False

    def test_CA_can_advance_not_started_to_preparing(self):
        assert HandoffPreparationState.not_started.can_advance_to(
            HandoffPreparationState.preparing
        ) is True

    def test_CB_can_advance_regression_ready_to_not_started_false(self):
        assert HandoffPreparationState.ready.can_advance_to(
            HandoffPreparationState.not_started
        ) is False

    def test_BP_string_values_match_lowercase(self):
        assert HandoffPreparationState.not_started.value == "not_started"
        assert HandoffPreparationState.preparing.value == "preparing"
        assert HandoffPreparationState.ready.value == "ready"
        assert HandoffPreparationState.dispatched.value == "dispatched"
        assert HandoffPreparationState.cancelled.value == "cancelled"
        assert HandoffPreparationState.failed.value == "failed"


# ---------------------------------------------------------------------------
# Group D — DispatchEligibilityOutcome
# ---------------------------------------------------------------------------

class TestGroupD:
    def test_D1_default_construction(self):
        o = DispatchEligibilityOutcome()
        assert o.is_eligible is False
        assert o.resolved_intent == DelegationIntent.none

    def test_D2_to_dict_keys(self):
        o = DispatchEligibilityOutcome()
        d = o.to_dict()
        for key in (
            "is_eligible", "resolved_intent", "blocking_reason",
            "applied_policy", "note", "device_id", "session_id",
            "source_runtime_posture", "coordination_role", "capability_tier",
        ):
            assert key in d, f"Missing key: {key}"

    def test_D3_to_json_valid(self):
        o = DispatchEligibilityOutcome(is_eligible=True, resolved_intent=DelegationIntent.delegate)
        j = o.to_json()
        parsed = json.loads(j)
        assert parsed["is_eligible"] is True
        assert parsed["resolved_intent"] == "delegate"

    def test_BI_to_dict_contains_expected_keys(self):
        o = DispatchEligibilityOutcome(
            is_eligible=True,
            resolved_intent=DelegationIntent.relay,
            device_id="dev-1",
            session_id="sess-1",
        )
        d = o.to_dict()
        assert d["device_id"] == "dev-1"
        assert d["session_id"] == "sess-1"
        assert d["resolved_intent"] == "relay"


# ---------------------------------------------------------------------------
# Group E — HandoffInputBundle
# ---------------------------------------------------------------------------

class TestGroupE:
    def test_E1_default_construction(self):
        b = HandoffInputBundle()
        assert b.session_id == ""
        assert b.is_session_anchored is False
        assert b.delegation_intent == DelegationIntent.none

    def test_E2_to_dict_keys(self):
        b = HandoffInputBundle()
        d = b.to_dict()
        for key in (
            "record_id", "device_id", "session_id", "source_runtime_posture",
            "coordination_role", "android_host_role", "capability_tier",
            "delegation_intent", "continuation_hint", "assembled_at",
            "is_session_anchored", "metadata",
        ):
            assert key in d, f"Missing key: {key}"

    def test_E3_to_json_valid(self):
        b = HandoffInputBundle(session_id="sess-abc", is_session_anchored=True)
        j = b.to_json()
        parsed = json.loads(j)
        assert parsed["session_id"] == "sess-abc"
        assert parsed["is_session_anchored"] is True


# ---------------------------------------------------------------------------
# Group F — DelegatedRuntimeDispatchRecord
# ---------------------------------------------------------------------------

class TestGroupF:
    def test_F1_default_construction(self):
        r = DelegatedRuntimeDispatchRecord()
        assert r.device_id == ""
        assert r.delegation_intent == DelegationIntent.none
        assert r.preparation_state == HandoffPreparationState.not_started
        assert r.reject_reason == ""

    def test_F2_is_accepted_false_by_default(self):
        r = DelegatedRuntimeDispatchRecord()
        assert r.is_accepted() is False

    def test_F3_is_accepted_true_when_valid(self):
        r = DelegatedRuntimeDispatchRecord(
            session_id="sess-1",
            delegation_intent=DelegationIntent.delegate,
            reject_reason="",
        )
        assert r.is_accepted() is True

    def test_F4_is_rejected_false_by_default(self):
        r = DelegatedRuntimeDispatchRecord()
        assert r.is_rejected() is False

    def test_F5_is_rejected_true_when_reject_reason(self):
        r = DelegatedRuntimeDispatchRecord(reject_reason="blocked by policy")
        assert r.is_rejected() is True

    def test_F6_is_pending_preparing(self):
        r = DelegatedRuntimeDispatchRecord(preparation_state=HandoffPreparationState.preparing)
        assert r.is_pending() is True

    def test_F7_is_pending_ready(self):
        r = DelegatedRuntimeDispatchRecord(preparation_state=HandoffPreparationState.ready)
        assert r.is_pending() is True

    def test_F8_is_pending_false_dispatched(self):
        r = DelegatedRuntimeDispatchRecord(preparation_state=HandoffPreparationState.dispatched)
        assert r.is_pending() is False

    def test_F9_to_dict_keys(self):
        r = DelegatedRuntimeDispatchRecord()
        d = r.to_dict()
        for key in (
            "record_id", "device_id", "session_id", "source_runtime_posture",
            "coordination_role", "android_host_role", "capability_tier",
            "delegation_intent", "preparation_state", "eligibility_outcome",
            "continuation_hint", "created_at", "metadata", "reject_reason",
        ):
            assert key in d, f"Missing key: {key}"

    def test_F10_to_json_valid(self):
        r = DelegatedRuntimeDispatchRecord(session_id="s1")
        j = r.to_json()
        parsed = json.loads(j)
        assert parsed["session_id"] == "s1"

    def test_F11_from_dict_round_trip(self):
        r = DelegatedRuntimeDispatchRecord(
            device_id="dev-x",
            session_id="sess-x",
            source_runtime_posture="join_runtime",
            coordination_role="source_controller",
            delegation_intent=DelegationIntent.delegate,
            preparation_state=HandoffPreparationState.ready,
            continuation_hint="chk-42",
            metadata={"k": "v"},
            reject_reason="",
        )
        d = r.to_dict()
        r2 = DelegatedRuntimeDispatchRecord.from_dict(d)
        assert r2.device_id == "dev-x"
        assert r2.session_id == "sess-x"
        assert r2.delegation_intent == DelegationIntent.delegate
        assert r2.preparation_state == HandoffPreparationState.ready
        assert r2.continuation_hint == "chk-42"
        assert r2.metadata == {"k": "v"}

    def test_F12_from_dict_non_dict_raises(self):
        with pytest.raises(ValueError):
            DelegatedRuntimeDispatchRecord.from_dict("not-a-dict")  # type: ignore[arg-type]

    def test_BF_record_id_is_uuid_unique(self):
        r1 = DelegatedRuntimeDispatchRecord()
        r2 = DelegatedRuntimeDispatchRecord()
        assert r1.record_id != r2.record_id
        uuid.UUID(r1.record_id)  # validates UUID format

    def test_BS_reject_reason_empty_when_accepted(self):
        r = DelegatedRuntimeDispatchRecord(
            session_id="s", delegation_intent=DelegationIntent.delegate
        )
        assert r.to_dict()["reject_reason"] == ""

    def test_BJ_from_dict_missing_fields_use_defaults(self):
        r = DelegatedRuntimeDispatchRecord.from_dict({})
        assert r.delegation_intent == DelegationIntent.none
        assert r.preparation_state == HandoffPreparationState.not_started

    def test_CD_record_id_stable_across_round_trip(self):
        r = DelegatedRuntimeDispatchRecord(session_id="s")
        rid = r.record_id
        r2 = DelegatedRuntimeDispatchRecord.from_dict(r.to_dict())
        assert r2.record_id == rid

    def test_CC_from_dict_eligibility_outcome_reconstructed(self):
        o = DispatchEligibilityOutcome(
            is_eligible=True,
            resolved_intent=DelegationIntent.relay,
            blocking_reason="test",
        )
        r = DelegatedRuntimeDispatchRecord(session_id="s", eligibility_outcome=o)
        d = r.to_dict()
        r2 = DelegatedRuntimeDispatchRecord.from_dict(d)
        assert r2.eligibility_outcome is not None
        assert r2.eligibility_outcome.resolved_intent == DelegationIntent.relay


# ---------------------------------------------------------------------------
# Group G — DelegatedRuntimeDispatchSnapshot
# ---------------------------------------------------------------------------

class TestGroupG:
    def test_G1_default_construction(self):
        s = DelegatedRuntimeDispatchSnapshot()
        assert s.records == []
        assert s.pending_count == 0
        assert s.total_count == 0

    def test_G2_to_dict_keys(self):
        s = DelegatedRuntimeDispatchSnapshot()
        d = s.to_dict()
        for key in ("snapshot_id", "snapshotted_at", "records",
                    "pending_count", "total_count", "policy_sentinels"):
            assert key in d, f"Missing key: {key}"

    def test_G3_to_json_valid(self):
        s = DelegatedRuntimeDispatchSnapshot(pending_count=2, total_count=5)
        j = s.to_json()
        parsed = json.loads(j)
        assert parsed["pending_count"] == 2
        assert parsed["total_count"] == 5

    def test_BG_snapshot_id_unique(self):
        s1 = DelegatedRuntimeDispatchSnapshot()
        s2 = DelegatedRuntimeDispatchSnapshot()
        assert s1.snapshot_id != s2.snapshot_id

    def test_BR_to_dict_contains_records_pending_total(self):
        s = DelegatedRuntimeDispatchSnapshot(pending_count=1, total_count=3)
        d = s.to_dict()
        assert "records" in d
        assert "pending_count" in d
        assert "total_count" in d

    def test_AY_snapshotted_at_recent(self):
        before = time.time()
        s = DelegatedRuntimeDispatchSnapshot()
        after = time.time()
        assert before <= s.snapshotted_at <= after


# ---------------------------------------------------------------------------
# Group H — DelegatedRuntimeDispatchRuntime
# ---------------------------------------------------------------------------

class TestGroupH:
    def test_H1_default_capacity(self):
        rt = _fresh_runtime()
        assert rt.capacity == 128

    def test_H2_push_increases_size(self):
        rt = _fresh_runtime()
        r = DelegatedRuntimeDispatchRecord()
        rt.push(r)
        assert rt.size == 1

    def test_H3_list_all_newest_first(self):
        rt = _fresh_runtime()
        r1 = DelegatedRuntimeDispatchRecord(device_id="a")
        r2 = DelegatedRuntimeDispatchRecord(device_id="b")
        rt.push(r1)
        rt.push(r2)
        all_records = rt.list_all()
        assert all_records[0].device_id == "b"
        assert all_records[1].device_id == "a"

    def test_H4_list_pending_returns_preparing_ready(self):
        rt = _fresh_runtime()
        r1 = DelegatedRuntimeDispatchRecord(preparation_state=HandoffPreparationState.preparing, session_id="s1")
        r2 = DelegatedRuntimeDispatchRecord(preparation_state=HandoffPreparationState.ready, session_id="s2")
        r3 = DelegatedRuntimeDispatchRecord(preparation_state=HandoffPreparationState.dispatched, session_id="s3")
        rt.push(r1)
        rt.push(r2)
        rt.push(r3)
        pending = rt.list_pending()
        assert len(pending) == 2
        session_ids = {r.session_id for r in pending}
        assert session_ids == {"s1", "s2"}

    def test_H5_get_latest_for_session(self):
        rt = _fresh_runtime()
        sid = _make_session_id()
        r1 = DelegatedRuntimeDispatchRecord(session_id=sid, device_id="v1")
        r2 = DelegatedRuntimeDispatchRecord(session_id=sid, device_id="v2")
        rt.push(r1)
        rt.push(r2)
        latest = rt.get_latest_for_session(sid)
        assert latest is not None
        assert latest.device_id == "v2"

    def test_H6_get_latest_for_session_unknown_returns_none(self):
        rt = _fresh_runtime()
        assert rt.get_latest_for_session("unknown") is None

    def test_CE_clear_empties_buffer(self):
        rt = _fresh_runtime()
        rt.push(DelegatedRuntimeDispatchRecord())
        rt.clear()
        assert rt.size == 0

    def test_AQ_capacity_128(self):
        rt = DelegatedRuntimeDispatchRuntime()
        assert rt.capacity == 128

    def test_AR_eviction_when_full(self):
        rt = DelegatedRuntimeDispatchRuntime(capacity=3)
        r1 = DelegatedRuntimeDispatchRecord(device_id="r1")
        r2 = DelegatedRuntimeDispatchRecord(device_id="r2")
        r3 = DelegatedRuntimeDispatchRecord(device_id="r3")
        r4 = DelegatedRuntimeDispatchRecord(device_id="r4")
        rt.push(r1)
        rt.push(r2)
        rt.push(r3)
        rt.push(r4)
        assert rt.size == 3
        device_ids = {r.device_id for r in rt.list_all()}
        assert "r1" not in device_ids  # oldest evicted
        assert "r4" in device_ids


# ---------------------------------------------------------------------------
# Group I–Q — evaluate_dispatch_eligibility
# ---------------------------------------------------------------------------

class TestGroupI_Q:
    def test_I1_join_runtime_valid_session_eligible(self):
        out = evaluate_dispatch_eligibility(
            device_id="dev-1",
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            coordination_role="source_controller",
            capability_tier="full_runtime",
            requested_intent=DelegationIntent.delegate,
        )
        assert out.is_eligible is True
        assert out.resolved_intent == DelegationIntent.delegate

    def test_J1_empty_session_id_ineligible(self):
        out = evaluate_dispatch_eligibility(
            session_id="",
            source_runtime_posture="join_runtime",
        )
        assert out.is_eligible is False
        assert out.resolved_intent == DelegationIntent.none

    def test_K1_control_only_posture_ineligible(self):
        out = evaluate_dispatch_eligibility(
            session_id=_make_session_id(),
            source_runtime_posture="control_only",
        )
        assert out.is_eligible is False
        assert out.resolved_intent == DelegationIntent.none

    def test_L1_observer_only_role_ineligible(self):
        out = evaluate_dispatch_eligibility(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            coordination_role="observer_only",
        )
        assert out.is_eligible is False
        assert out.resolved_intent == DelegationIntent.none

    def test_M1_target_only_executor_ineligible(self):
        out = evaluate_dispatch_eligibility(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            coordination_role="target_only_executor",
        )
        assert out.is_eligible is False
        assert out.resolved_intent == DelegationIntent.none

    def test_N1_command_only_tier_delegate_downgraded_to_relay(self):
        out = evaluate_dispatch_eligibility(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            coordination_role="source_controller",
            capability_tier="command_only",
            requested_intent=DelegationIntent.delegate,
        )
        assert out.is_eligible is True
        assert out.resolved_intent == DelegationIntent.relay
        assert out.blocking_reason == ""  # blocking_reason is empty for eligible outcomes
        assert len(out.note) > 0  # note contains the downgrade explanation

    def test_O1_full_runtime_tier_delegate_permitted(self):
        out = evaluate_dispatch_eligibility(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            capability_tier="full_runtime",
            requested_intent=DelegationIntent.delegate,
        )
        assert out.is_eligible is True
        assert out.resolved_intent == DelegationIntent.delegate

    def test_P1_partial_runtime_tier_delegate_permitted(self):
        out = evaluate_dispatch_eligibility(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            capability_tier="partial_runtime",
            requested_intent=DelegationIntent.delegate,
        )
        assert out.is_eligible is True
        assert out.resolved_intent == DelegationIntent.delegate

    def test_Q1_unknown_tier_delegate_permitted(self):
        out = evaluate_dispatch_eligibility(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            capability_tier="unknown",
            requested_intent=DelegationIntent.delegate,
        )
        assert out.is_eligible is True
        assert out.resolved_intent == DelegationIntent.delegate

    def test_BA_relay_intent_accepted(self):
        out = evaluate_dispatch_eligibility(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            requested_intent=DelegationIntent.relay,
        )
        assert out.is_eligible is True
        assert out.resolved_intent == DelegationIntent.relay

    def test_BB_observe_intent_accepted(self):
        out = evaluate_dispatch_eligibility(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            requested_intent=DelegationIntent.observe,
        )
        assert out.is_eligible is True
        assert out.resolved_intent == DelegationIntent.observe

    def test_BC_none_intent_eligible_resolved_none(self):
        out = evaluate_dispatch_eligibility(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            requested_intent=DelegationIntent.none,
        )
        assert out.is_eligible is True
        assert out.resolved_intent == DelegationIntent.none

    def test_BQ_blocking_reason_non_empty_when_ineligible(self):
        out = evaluate_dispatch_eligibility(session_id="", source_runtime_posture="join_runtime")
        assert len(out.blocking_reason) > 0

    def test_BQ2_blocking_reason_empty_when_eligible(self):
        out = evaluate_dispatch_eligibility(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            requested_intent=DelegationIntent.delegate,
        )
        assert out.blocking_reason == ""


# ---------------------------------------------------------------------------
# Group R–AB — build_delegated_dispatch_record
# ---------------------------------------------------------------------------

class TestGroupR_AB:
    def test_R1_join_runtime_valid_returns_accepted(self):
        rt = _fresh_runtime()
        sid = _make_session_id()
        r = build_delegated_dispatch_record(
            device_id="dev-a",
            session_id=sid,
            source_runtime_posture="join_runtime",
            coordination_role="source_controller",
            capability_tier="full_runtime",
            requested_intent=DelegationIntent.delegate,
            runtime=rt,
        )
        assert r.is_accepted() is True
        assert r.delegation_intent == DelegationIntent.delegate
        assert r.reject_reason == ""

    def test_S1_control_only_returns_rejected(self):
        rt = _fresh_runtime()
        r = build_delegated_dispatch_record(
            session_id=_make_session_id(),
            source_runtime_posture="control_only",
            runtime=rt,
        )
        assert r.is_rejected() is True
        assert r.delegation_intent == DelegationIntent.none

    def test_T1_empty_session_id_returns_rejected(self):
        rt = _fresh_runtime()
        r = build_delegated_dispatch_record(
            session_id="",
            source_runtime_posture="join_runtime",
            runtime=rt,
        )
        assert r.is_rejected() is True

    def test_U1_observer_only_role_rejected(self):
        rt = _fresh_runtime()
        r = build_delegated_dispatch_record(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            coordination_role="observer_only",
            runtime=rt,
        )
        assert r.is_rejected() is True

    def test_V1_target_only_executor_rejected(self):
        rt = _fresh_runtime()
        r = build_delegated_dispatch_record(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            coordination_role="target_only_executor",
            runtime=rt,
        )
        assert r.is_rejected() is True

    def test_W1_command_only_tier_delegate_produces_relay(self):
        rt = _fresh_runtime()
        r = build_delegated_dispatch_record(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            capability_tier="command_only",
            requested_intent=DelegationIntent.delegate,
            runtime=rt,
        )
        assert r.is_accepted() is True
        assert r.delegation_intent == DelegationIntent.relay

    def test_X1_android_host_role_carried(self):
        rt = _fresh_runtime()
        r = build_delegated_dispatch_record(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            android_host_role="full_runtime_host",
            runtime=rt,
        )
        assert r.android_host_role == "full_runtime_host"

    def test_Y1_continuation_hint_propagated(self):
        rt = _fresh_runtime()
        r = build_delegated_dispatch_record(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            continuation_hint="chk-99",
            runtime=rt,
        )
        assert r.continuation_hint == "chk-99"

    def test_Z1_metadata_propagated(self):
        rt = _fresh_runtime()
        r = build_delegated_dispatch_record(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            metadata={"origin": "test"},
            runtime=rt,
        )
        assert r.metadata == {"origin": "test"}

    def test_AA_persisted_to_runtime(self):
        rt = _fresh_runtime()
        before = rt.size
        build_delegated_dispatch_record(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            runtime=rt,
        )
        assert rt.size == before + 1

    def test_AB_custom_runtime_isolation(self):
        rt_a = _fresh_runtime()
        rt_b = _fresh_runtime()
        build_delegated_dispatch_record(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            runtime=rt_a,
        )
        assert rt_a.size == 1
        assert rt_b.size == 0

    def test_BD_preparation_state_ready_accepted(self):
        rt = _fresh_runtime()
        r = build_delegated_dispatch_record(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            preparation_state=HandoffPreparationState.ready,
            runtime=rt,
        )
        assert r.preparation_state == HandoffPreparationState.ready

    def test_BE_rejected_record_has_cancelled_state(self):
        rt = _fresh_runtime()
        r = build_delegated_dispatch_record(
            session_id="",
            source_runtime_posture="join_runtime",
            runtime=rt,
        )
        assert r.preparation_state == HandoffPreparationState.cancelled

    def test_BT_eligibility_outcome_present(self):
        rt = _fresh_runtime()
        r = build_delegated_dispatch_record(
            session_id=_make_session_id(),
            source_runtime_posture="join_runtime",
            runtime=rt,
        )
        assert r.eligibility_outcome is not None

    def test_BW_does_not_mutate_other_records(self):
        rt = _fresh_runtime()
        sid1 = _make_session_id()
        sid2 = _make_session_id()
        r1 = build_delegated_dispatch_record(
            session_id=sid1, source_runtime_posture="join_runtime", runtime=rt
        )
        build_delegated_dispatch_record(
            session_id=sid2, source_runtime_posture="join_runtime", runtime=rt
        )
        # r1 should remain unchanged
        assert r1.session_id == sid1


# ---------------------------------------------------------------------------
# Group AC–AF — prepare_handoff_inputs
# ---------------------------------------------------------------------------

class TestGroupAC_AF:
    def test_AC1_anchored_bundle_from_accepted_record(self):
        rt = _fresh_runtime()
        sid = _make_session_id()
        r = build_delegated_dispatch_record(
            device_id="dev-b",
            session_id=sid,
            source_runtime_posture="join_runtime",
            runtime=rt,
        )
        bundle = prepare_handoff_inputs(r)
        assert bundle.is_session_anchored is True
        assert bundle.session_id == sid
        assert bundle.device_id == "dev-b"

    def test_AD1_is_session_anchored_false_when_empty_session(self):
        r = DelegatedRuntimeDispatchRecord(session_id="", device_id="dev-c")
        bundle = prepare_handoff_inputs(r)
        assert bundle.is_session_anchored is False

    def test_AE1_override_continuation_hint_applied(self):
        r = DelegatedRuntimeDispatchRecord(
            session_id="s1", continuation_hint="orig"
        )
        bundle = prepare_handoff_inputs(r, override_continuation_hint="new-hint")
        assert bundle.continuation_hint == "new-hint"

    def test_AF1_posture_role_tier_carried(self):
        r = DelegatedRuntimeDispatchRecord(
            session_id="s1",
            source_runtime_posture="join_runtime",
            coordination_role="source_controller",
            capability_tier="full_runtime",
        )
        bundle = prepare_handoff_inputs(r)
        assert bundle.source_runtime_posture == "join_runtime"
        assert bundle.coordination_role == "source_controller"
        assert bundle.capability_tier == "full_runtime"

    def test_BH_bundle_record_id_matches_record(self):
        r = DelegatedRuntimeDispatchRecord(session_id="s1")
        bundle = prepare_handoff_inputs(r)
        assert bundle.record_id == r.record_id

    def test_BV_bundle_metadata_matches_record(self):
        r = DelegatedRuntimeDispatchRecord(
            session_id="s1", metadata={"foo": "bar"}
        )
        bundle = prepare_handoff_inputs(r)
        assert bundle.metadata == {"foo": "bar"}


# ---------------------------------------------------------------------------
# Group AG–AN — record_delegated_dispatch_intent, get, list, snapshot
# ---------------------------------------------------------------------------

class TestGroupAG_AN:
    def test_AG1_record_persisted_to_runtime(self):
        rt = _fresh_runtime()
        r = DelegatedRuntimeDispatchRecord(session_id="s1")
        record_delegated_dispatch_intent(r, runtime=rt)
        assert rt.size == 1

    def test_AH1_get_returns_most_recent(self):
        rt = _fresh_runtime()
        sid = _make_session_id()
        r1 = DelegatedRuntimeDispatchRecord(session_id=sid, device_id="v1")
        r2 = DelegatedRuntimeDispatchRecord(session_id=sid, device_id="v2")
        rt.push(r1)
        rt.push(r2)
        latest = get_delegated_dispatch_record(sid, runtime=rt)
        assert latest is not None
        assert latest.device_id == "v2"

    def test_AI1_get_unknown_returns_none(self):
        rt = _fresh_runtime()
        assert get_delegated_dispatch_record("unknown", runtime=rt) is None

    def test_AJ1_list_pending_returns_preparing_ready(self):
        rt = _fresh_runtime()
        rt.push(DelegatedRuntimeDispatchRecord(preparation_state=HandoffPreparationState.preparing))
        rt.push(DelegatedRuntimeDispatchRecord(preparation_state=HandoffPreparationState.ready))
        rt.push(DelegatedRuntimeDispatchRecord(preparation_state=HandoffPreparationState.dispatched))
        pending = list_pending_delegated_dispatch_records(runtime=rt)
        assert len(pending) == 2

    def test_AK1_list_pending_empty_when_none(self):
        rt = _fresh_runtime()
        assert list_pending_delegated_dispatch_records(runtime=rt) == []

    def test_AL1_snapshot_counts_pending_and_total(self):
        rt = _fresh_runtime()
        rt.push(DelegatedRuntimeDispatchRecord(preparation_state=HandoffPreparationState.preparing))
        rt.push(DelegatedRuntimeDispatchRecord(preparation_state=HandoffPreparationState.dispatched))
        snap = build_delegated_dispatch_snapshot(runtime=rt)
        assert snap.total_count == 2
        assert snap.pending_count == 1

    def test_AM1_snapshot_includes_policy_sentinels(self):
        rt = _fresh_runtime()
        snap = build_delegated_dispatch_snapshot(runtime=rt)
        assert len(snap.policy_sentinels) >= 10
        assert DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY in snap.policy_sentinels

    def test_AN1_snapshot_empty_runtime_zero_counts(self):
        rt = _fresh_runtime()
        snap = build_delegated_dispatch_snapshot(runtime=rt)
        assert snap.total_count == 0
        assert snap.pending_count == 0

    def test_BK_list_pending_excludes_dispatched_cancelled_failed(self):
        rt = _fresh_runtime()
        for state in (
            HandoffPreparationState.dispatched,
            HandoffPreparationState.cancelled,
            HandoffPreparationState.failed,
            HandoffPreparationState.not_started,
        ):
            rt.push(DelegatedRuntimeDispatchRecord(preparation_state=state))
        pending = list_pending_delegated_dispatch_records(runtime=rt)
        assert pending == []

    def test_BL_snapshot_records_newest_first(self):
        rt = _fresh_runtime()
        r1 = DelegatedRuntimeDispatchRecord(device_id="first")
        r2 = DelegatedRuntimeDispatchRecord(device_id="second")
        rt.push(r1)
        rt.push(r2)
        snap = build_delegated_dispatch_snapshot(runtime=rt)
        assert snap.records[0].device_id == "second"
        assert snap.records[1].device_id == "first"

    def test_BU_two_sessions_both_in_pending(self):
        rt = _fresh_runtime()
        rt.push(DelegatedRuntimeDispatchRecord(
            session_id="sa", preparation_state=HandoffPreparationState.preparing
        ))
        rt.push(DelegatedRuntimeDispatchRecord(
            session_id="sb", preparation_state=HandoffPreparationState.ready
        ))
        pending = list_pending_delegated_dispatch_records(runtime=rt)
        session_ids = {r.session_id for r in pending}
        assert session_ids == {"sa", "sb"}


# ---------------------------------------------------------------------------
# Group AO–AP — core.runtime re-exports, projection sentinel
# ---------------------------------------------------------------------------

class TestGroupAO_AP:
    def test_AO_core_runtime_reexports(self):
        try:
            import core.runtime as cr
        except (ImportError, ModuleNotFoundError):
            pytest.skip("core.runtime not importable in this environment")
        assert hasattr(cr, "DelegationIntent")
        assert hasattr(cr, "HandoffPreparationState")
        assert hasattr(cr, "DelegatedRuntimeDispatchRecord")
        assert hasattr(cr, "HandoffInputBundle")
        assert hasattr(cr, "DispatchEligibilityOutcome")
        assert hasattr(cr, "DelegatedRuntimeDispatchSnapshot")
        assert hasattr(cr, "DelegatedRuntimeDispatchRuntime")
        assert hasattr(cr, "build_delegated_dispatch_record")
        assert hasattr(cr, "evaluate_dispatch_eligibility")
        assert hasattr(cr, "prepare_handoff_inputs")
        assert hasattr(cr, "record_delegated_dispatch_intent")
        assert hasattr(cr, "get_delegated_dispatch_record")
        assert hasattr(cr, "list_pending_delegated_dispatch_records")
        assert hasattr(cr, "build_delegated_dispatch_snapshot")
        assert hasattr(cr, "get_delegated_runtime_dispatch_runtime")
        assert hasattr(cr, "reset_delegated_runtime_dispatch_runtime")
        assert hasattr(cr, "DELEGATED_RUNTIME_DISPATCH_INTENT_AUTHORITY")
        assert hasattr(cr, "DELEGATED_RUNTIME_DISPATCH_INTENT_PR8_SENTINEL")

    def test_AP_projection_sentinel_aligned(self):
        try:
            from core.routes.projection import (
                DELEGATED_RUNTIME_DISPATCH_INTENT_ALIGNED_PR8,
            )
            assert "UNAVAILABLE" not in DELEGATED_RUNTIME_DISPATCH_INTENT_ALIGNED_PR8
            assert "PR8" in DELEGATED_RUNTIME_DISPATCH_INTENT_ALIGNED_PR8
        except (ImportError, ModuleNotFoundError):
            pytest.skip("projection route not importable in this environment")


# ---------------------------------------------------------------------------
# Group AW–AX — from_string fallbacks
# ---------------------------------------------------------------------------

class TestGroupAW_AX:
    def test_AW_delegation_intent_from_string_unknown_defaults_none(self):
        assert DelegationIntent.from_string("xyz") == DelegationIntent.none

    def test_AX_handoff_preparation_state_unknown_defaults_not_started(self):
        assert (
            HandoffPreparationState.from_string("xyz")
            == HandoffPreparationState.not_started
        )


# ---------------------------------------------------------------------------
# Group BM–BN — singleton management
# ---------------------------------------------------------------------------

class TestGroupBM_BN:
    def setup_method(self):
        reset_delegated_runtime_dispatch_runtime()

    def teardown_method(self):
        reset_delegated_runtime_dispatch_runtime()

    def test_BM_reset_clears_singleton(self):
        rt = get_delegated_runtime_dispatch_runtime()
        rt.push(DelegatedRuntimeDispatchRecord())
        reset_delegated_runtime_dispatch_runtime()
        rt2 = get_delegated_runtime_dispatch_runtime()
        assert rt2.size == 0

    def test_BN_get_runtime_same_singleton(self):
        rt1 = get_delegated_runtime_dispatch_runtime()
        rt2 = get_delegated_runtime_dispatch_runtime()
        assert rt1 is rt2


# ---------------------------------------------------------------------------
# Group AV — Multiple sessions
# ---------------------------------------------------------------------------

class TestGroupAV:
    def test_AV_multiple_sessions_independent(self):
        rt = _fresh_runtime()
        sid_a = _make_session_id()
        sid_b = _make_session_id()
        build_delegated_dispatch_record(
            session_id=sid_a, source_runtime_posture="join_runtime",
            device_id="dev-A", runtime=rt,
        )
        build_delegated_dispatch_record(
            session_id=sid_b, source_runtime_posture="join_runtime",
            device_id="dev-B", runtime=rt,
        )
        rec_a = get_delegated_dispatch_record(sid_a, runtime=rt)
        rec_b = get_delegated_dispatch_record(sid_b, runtime=rt)
        assert rec_a is not None
        assert rec_b is not None
        assert rec_a.device_id == "dev-A"
        assert rec_b.device_id == "dev-B"


# ---------------------------------------------------------------------------
# Group BY — PR8 sentinel string content
# ---------------------------------------------------------------------------

class TestGroupBY:
    def test_BY_pr8_sentinel_contains_package_8(self):
        assert "package=8" in DELEGATED_RUNTIME_DISPATCH_INTENT_PR8_SENTINEL

    def test_BY2_pr8_sentinel_contains_main(self):
        assert "main" in DELEGATED_RUNTIME_DISPATCH_INTENT_PR8_SENTINEL.lower()


# ---------------------------------------------------------------------------
# Group BX — End-to-end
# ---------------------------------------------------------------------------

class TestGroupBX:
    def test_BX_end_to_end_attach_evaluate_build_prepare(self):
        """
        E2E: simulate host receiving an attached session record (from PR-7),
        evaluate eligibility, build a dispatch record, and prepare handoff inputs.
        """
        # Simulate an attached session context (fields from PR-7 would normally come
        # from AttachedRuntimeSessionRecord; here we supply them directly).
        sid = _make_session_id()
        device_id = "android-device-001"
        posture = "join_runtime"
        role = "source_controller"
        tier = "full_runtime"
        android_host_role = "full_runtime_host"

        rt = _fresh_runtime()

        # Step 1: evaluate eligibility
        eligibility = evaluate_dispatch_eligibility(
            device_id=device_id,
            session_id=sid,
            source_runtime_posture=posture,
            coordination_role=role,
            capability_tier=tier,
            requested_intent=DelegationIntent.delegate,
        )
        assert eligibility.is_eligible is True
        assert eligibility.resolved_intent == DelegationIntent.delegate

        # Step 2: build dispatch record
        record = build_delegated_dispatch_record(
            device_id=device_id,
            session_id=sid,
            source_runtime_posture=posture,
            coordination_role=role,
            android_host_role=android_host_role,
            capability_tier=tier,
            requested_intent=DelegationIntent.delegate,
            continuation_hint="chk-001",
            preparation_state=HandoffPreparationState.preparing,
            runtime=rt,
        )
        assert record.is_accepted() is True
        assert record.is_pending() is True
        assert record.delegation_intent == DelegationIntent.delegate
        assert record.preparation_state == HandoffPreparationState.preparing

        # Step 3: prepare handoff inputs
        bundle = prepare_handoff_inputs(record)
        assert bundle.is_session_anchored is True
        assert bundle.session_id == sid
        assert bundle.device_id == device_id
        assert bundle.delegation_intent == DelegationIntent.delegate
        assert bundle.continuation_hint == "chk-001"
        assert bundle.source_runtime_posture == posture
        assert bundle.coordination_role == role
        assert bundle.android_host_role == android_host_role
        assert bundle.capability_tier == tier

        # Step 4: confirm record is in runtime
        found = get_delegated_dispatch_record(sid, runtime=rt)
        assert found is not None
        assert found.record_id == record.record_id

        # Step 5: list pending
        pending = list_pending_delegated_dispatch_records(runtime=rt)
        assert len(pending) == 1
        assert pending[0].record_id == record.record_id

        # Step 6: build snapshot
        snap = build_delegated_dispatch_snapshot(runtime=rt)
        assert snap.total_count == 1
        assert snap.pending_count == 1
        assert snap.policy_sentinels  # non-empty
