"""tests/test_pr9_post533_delegated_runtime_handoff_contract.py
==============================================================
Tests for PR package 9 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Delegated-Runtime Handoff Contract Foundations.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — HandoffContractVersion enum: all values present, from_string(), defaults.
C  — HandoffContractStatus enum: all values present, from_string(),
     is_terminal(), is_dispatch_ready(), can_advance_to().
D  — DelegatedHandoffContractIdentity: construction, defaults, to_dict(),
     to_json(), from_dict().
E  — DelegatedHandoffContractMeta: construction, defaults, to_dict(),
     to_json(), from_dict().
F  — DelegatedHandoffContractPayload: construction, defaults, to_dict(),
     to_json(), from_dict().
G  — DelegatedHandoffContractRecord: construction, defaults, to_dict(),
     to_json(), from_dict(), is_accepted(), is_rejected(), is_pending(),
     is_dispatch_ready().
H  — DelegatedHandoffContractSnapshot: construction, defaults, to_dict(),
     to_json().
I  — DelegatedHandoffContractRuntime: push, list_all, list_pending,
     get_latest_for_session, clear, size, capacity.
J  — build_delegated_handoff_contract: valid inputs → accepted (draft) record.
K  — build_delegated_handoff_contract: empty session_id → rejected (cancelled).
L  — build_delegated_handoff_contract: empty dispatch_record_id → rejected.
M  — build_delegated_handoff_contract: empty task_body → rejected.
N  — build_delegated_handoff_contract: trace_id auto-generated when absent.
O  — build_delegated_handoff_contract: trace_id propagated when provided.
P  — build_delegated_handoff_contract: task_id auto-generated when absent.
Q  — build_delegated_handoff_contract: posture preserved unchanged from inputs.
R  — build_delegated_handoff_contract: coordination_role forwarded.
S  — build_delegated_handoff_contract: android_host_role forwarded.
T  — build_delegated_handoff_contract: capability_tier forwarded.
U  — build_delegated_handoff_contract: delegation_intent forwarded.
V  — build_delegated_handoff_contract: continuation_hint forwarded.
W  — build_delegated_handoff_contract: contract_version forwarded.
X  — build_delegated_handoff_contract: meta_metadata propagated.
Y  — build_delegated_handoff_contract: payload_metadata propagated.
Z  — build_delegated_handoff_contract: raw_payload defaults to copy of task_body.
AA — build_delegated_handoff_contract: persisted to runtime ring-buffer.
AB — build_delegated_handoff_contract: custom runtime isolation.
AC — seal_handoff_contract: draft → sealed advancement.
AD — seal_handoff_contract: sealed_at timestamp set on sealing.
AE — seal_handoff_contract: already terminal record returned unchanged.
AF — seal_handoff_contract: sealed record persisted to runtime.
AG — seal_handoff_contract: is_dispatch_ready() True after sealing.
AH — record_handoff_contract: persists record to runtime.
AI — get_handoff_contract: returns most recent for session_id.
AJ — get_handoff_contract: returns None for unknown session_id.
AK — list_pending_handoff_contracts: returns draft+sealed only.
AL — list_pending_handoff_contracts: empty when no pending contracts.
AM — build_handoff_contract_snapshot: counts pending and total correctly.
AN — build_handoff_contract_snapshot: includes policy sentinels.
AO — build_handoff_contract_snapshot: empty runtime → zero counts.
AP — core.runtime re-exports: all PR-9 symbols accessible from core.runtime.
AQ — projection.py sentinel: DELEGATED_RUNTIME_HANDOFF_CONTRACT_ALIGNED_PR9
     is present and not UNAVAILABLE.
AR — Ring buffer capacity: 128.
AS — Ring buffer eviction: oldest entry evicted when full.
AT — Serialisation round-trip: DelegatedHandoffContractRecord to_dict → from_dict.
AU — Serialisation round-trip: to_json produces valid JSON.
AV — Serialisation: from_dict with non-dict raises ValueError.
AW — Multiple sessions: each gets its own record.
AX — HandoffContractVersion.from_string: unknown string → unknown.
AY — HandoffContractStatus.from_string: unknown string → draft.
AZ — Snapshot snapshotted_at is recent timestamp.
BA — All 10 policy sentinels are non-empty strings.
BB — HandoffContractStatus.can_advance_to: terminal → False.
BC — HandoffContractStatus.can_advance_to: draft → sealed → True.
BD — HandoffContractStatus.can_advance_to: sealed → dispatched → True.
BE — HandoffContractStatus.can_advance_to: draft → cancelled → True.
BF — HandoffContractStatus.can_advance_to: sealed → draft → False (regression).
BG — DelegatedHandoffContractRecord.is_accepted: True when no reject_reason.
BH — DelegatedHandoffContractRecord.is_accepted: False when reject_reason set.
BI — DelegatedHandoffContractRecord.is_rejected: True when reject_reason set.
BJ — DelegatedHandoffContractRecord.is_pending: True when draft or sealed.
BK — DelegatedHandoffContractRecord.is_pending: False when dispatched.
BL — build_delegated_handoff_contract: contract_id is auto-generated UUID.
BM — Snapshot to_dict contains 'records', 'pending_count', 'total_count'.
BN — Record to_dict: reject_reason empty when accepted.
BO — Record to_dict: identity sub-dict has expected keys.
BP — Record to_dict: meta sub-dict has expected keys.
BQ — Record to_dict: payload sub-dict has expected keys.
BR — get_handoff_contract_runtime returns same singleton.
BS — reset_handoff_contract_runtime clears singleton for isolation.
BT — Two separate sessions: list_pending returns both when both pending.
BU — build_delegated_handoff_contract: does not mutate other records in runtime.
BV — end-to-end: build contract → seal → snapshot reflects sealed status.
BW — DELEGATED_RUNTIME_HANDOFF_CONTRACT_PR9_SENTINEL contains 'package=9'.
BX — DelegatedHandoffContractRecord from_dict: missing fields use safe defaults.
BY — DelegatedHandoffContractIdentity from_dict: non-dict raises ValueError.
BZ — DelegatedHandoffContractMeta from_dict: non-dict raises ValueError.
CA — DelegatedHandoffContractPayload from_dict: non-dict raises ValueError.
CB — DelegatedHandoffContractRecord from_dict: non-dict raises ValueError.
CC — seal_handoff_contract: already-cancelled record unchanged.
CD — seal_handoff_contract: already-expired record unchanged.
CE — Snapshot to_json is valid JSON.
CF — DelegatedHandoffContractRuntime: clear() empties the buffer.
CG — contract_id is stable across to_dict/from_dict round-trip.
CH — list_pending excludes dispatched, expired, cancelled.
CI — build_handoff_contract_snapshot: records are newest-first.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest

from core.delegated_runtime_handoff_contract import (
    DELEGATED_RUNTIME_HANDOFF_CONTRACT_AUTHORITY,
    DELEGATED_RUNTIME_HANDOFF_CONTRACT_PR9_SENTINEL,
    HANDOFF_CONTRACT_IDENTITY_IS_IMMUTABLE_POLICY,
    HANDOFF_CONTRACT_PAYLOAD_MUST_BE_NON_EMPTY_POLICY,
    HANDOFF_CONTRACT_POSTURE_IS_PRESERVED_POLICY,
    HANDOFF_CONTRACT_REQUIRES_ATTACHED_SESSION_POLICY,
    HANDOFF_CONTRACT_REQUIRES_DISPATCH_RECORD_POLICY,
    HANDOFF_CONTRACT_STATUS_IS_MONOTONIC_POLICY,
    HANDOFF_CONTRACT_TRACE_ID_IS_PROPAGATED_POLICY,
    HANDOFF_CONTRACT_VERSION_MUST_BE_EXPLICIT_POLICY,
    SEALED_CONTRACT_IS_DISPATCH_READY_POLICY,
    DelegatedHandoffContractIdentity,
    DelegatedHandoffContractMeta,
    DelegatedHandoffContractPayload,
    DelegatedHandoffContractRecord,
    DelegatedHandoffContractRuntime,
    DelegatedHandoffContractSnapshot,
    HandoffContractStatus,
    HandoffContractVersion,
    build_delegated_handoff_contract,
    build_handoff_contract_snapshot,
    get_handoff_contract,
    get_handoff_contract_runtime,
    list_pending_handoff_contracts,
    record_handoff_contract,
    reset_handoff_contract_runtime,
    seal_handoff_contract,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_runtime() -> DelegatedHandoffContractRuntime:
    return DelegatedHandoffContractRuntime()


def _session_id() -> str:
    return str(uuid.uuid4())


def _dispatch_id() -> str:
    return str(uuid.uuid4())


def _task_body() -> dict:
    return {"command": "take_screenshot", "context": {"display": 0}}


def _make_accepted(
    rt: DelegatedHandoffContractRuntime | None = None,
    session_id: str | None = None,
    dispatch_record_id: str | None = None,
) -> DelegatedHandoffContractRecord:
    return build_delegated_handoff_contract(
        session_id=session_id or _session_id(),
        dispatch_record_id=dispatch_record_id or _dispatch_id(),
        task_body=_task_body(),
        source_runtime_posture="join_runtime",
        runtime=rt,
    )


# ---------------------------------------------------------------------------
# Group A — Authority / policy sentinels
# ---------------------------------------------------------------------------

class TestGroupA:
    def test_A1_authority_non_empty(self):
        assert isinstance(DELEGATED_RUNTIME_HANDOFF_CONTRACT_AUTHORITY, str)
        assert len(DELEGATED_RUNTIME_HANDOFF_CONTRACT_AUTHORITY) > 0

    def test_A2_requires_dispatch_record_policy(self):
        assert isinstance(HANDOFF_CONTRACT_REQUIRES_DISPATCH_RECORD_POLICY, str)
        assert len(HANDOFF_CONTRACT_REQUIRES_DISPATCH_RECORD_POLICY) > 0

    def test_A3_requires_attached_session_policy(self):
        assert isinstance(HANDOFF_CONTRACT_REQUIRES_ATTACHED_SESSION_POLICY, str)
        assert len(HANDOFF_CONTRACT_REQUIRES_ATTACHED_SESSION_POLICY) > 0

    def test_A4_version_must_be_explicit_policy(self):
        assert isinstance(HANDOFF_CONTRACT_VERSION_MUST_BE_EXPLICIT_POLICY, str)
        assert len(HANDOFF_CONTRACT_VERSION_MUST_BE_EXPLICIT_POLICY) > 0

    def test_A5_identity_is_immutable_policy(self):
        assert isinstance(HANDOFF_CONTRACT_IDENTITY_IS_IMMUTABLE_POLICY, str)
        assert len(HANDOFF_CONTRACT_IDENTITY_IS_IMMUTABLE_POLICY) > 0

    def test_A6_status_is_monotonic_policy(self):
        assert isinstance(HANDOFF_CONTRACT_STATUS_IS_MONOTONIC_POLICY, str)
        assert len(HANDOFF_CONTRACT_STATUS_IS_MONOTONIC_POLICY) > 0

    def test_A7_posture_is_preserved_policy(self):
        assert isinstance(HANDOFF_CONTRACT_POSTURE_IS_PRESERVED_POLICY, str)
        assert len(HANDOFF_CONTRACT_POSTURE_IS_PRESERVED_POLICY) > 0

    def test_A8_sealed_is_dispatch_ready_policy(self):
        assert isinstance(SEALED_CONTRACT_IS_DISPATCH_READY_POLICY, str)
        assert len(SEALED_CONTRACT_IS_DISPATCH_READY_POLICY) > 0

    def test_A9_payload_must_be_non_empty_policy(self):
        assert isinstance(HANDOFF_CONTRACT_PAYLOAD_MUST_BE_NON_EMPTY_POLICY, str)
        assert len(HANDOFF_CONTRACT_PAYLOAD_MUST_BE_NON_EMPTY_POLICY) > 0

    def test_A10_trace_id_is_propagated_policy(self):
        assert isinstance(HANDOFF_CONTRACT_TRACE_ID_IS_PROPAGATED_POLICY, str)
        assert len(HANDOFF_CONTRACT_TRACE_ID_IS_PROPAGATED_POLICY) > 0

    def test_BA_all_10_sentinels_non_empty(self):
        sentinels = [
            DELEGATED_RUNTIME_HANDOFF_CONTRACT_AUTHORITY,
            HANDOFF_CONTRACT_REQUIRES_DISPATCH_RECORD_POLICY,
            HANDOFF_CONTRACT_REQUIRES_ATTACHED_SESSION_POLICY,
            HANDOFF_CONTRACT_VERSION_MUST_BE_EXPLICIT_POLICY,
            HANDOFF_CONTRACT_IDENTITY_IS_IMMUTABLE_POLICY,
            HANDOFF_CONTRACT_STATUS_IS_MONOTONIC_POLICY,
            HANDOFF_CONTRACT_POSTURE_IS_PRESERVED_POLICY,
            SEALED_CONTRACT_IS_DISPATCH_READY_POLICY,
            HANDOFF_CONTRACT_PAYLOAD_MUST_BE_NON_EMPTY_POLICY,
            HANDOFF_CONTRACT_TRACE_ID_IS_PROPAGATED_POLICY,
        ]
        assert len(sentinels) == 10
        for s in sentinels:
            assert isinstance(s, str) and len(s) > 0


# ---------------------------------------------------------------------------
# Group B — HandoffContractVersion enum
# ---------------------------------------------------------------------------

class TestGroupB:
    def test_B1_all_values_present(self):
        values = {m.value for m in HandoffContractVersion}
        assert values == {"v1", "v2", "unknown"}

    def test_B2_from_string_v1(self):
        assert HandoffContractVersion.from_string("v1") == HandoffContractVersion.v1

    def test_B3_from_string_v2(self):
        assert HandoffContractVersion.from_string("v2") == HandoffContractVersion.v2

    def test_B4_from_string_unknown(self):
        assert HandoffContractVersion.from_string("unknown") == HandoffContractVersion.unknown

    def test_B5_from_string_bogus_defaults_unknown(self):
        assert HandoffContractVersion.from_string("v99") == HandoffContractVersion.unknown

    def test_B6_from_string_uppercase_normalised(self):
        assert HandoffContractVersion.from_string("V2") == HandoffContractVersion.v2

    def test_B7_from_string_non_string_defaults_unknown(self):
        assert HandoffContractVersion.from_string(None) == HandoffContractVersion.unknown  # type: ignore[arg-type]

    def test_AX_from_string_empty_defaults_unknown(self):
        assert HandoffContractVersion.from_string("") == HandoffContractVersion.unknown


# ---------------------------------------------------------------------------
# Group C — HandoffContractStatus enum
# ---------------------------------------------------------------------------

class TestGroupC:
    def test_C1_all_values_present(self):
        values = {m.value for m in HandoffContractStatus}
        assert values == {"draft", "sealed", "dispatched", "expired", "cancelled"}

    def test_C2_from_string_draft(self):
        assert HandoffContractStatus.from_string("draft") == HandoffContractStatus.draft

    def test_C3_from_string_sealed(self):
        assert HandoffContractStatus.from_string("sealed") == HandoffContractStatus.sealed

    def test_C4_from_string_dispatched(self):
        assert HandoffContractStatus.from_string("dispatched") == HandoffContractStatus.dispatched

    def test_C5_from_string_expired(self):
        assert HandoffContractStatus.from_string("expired") == HandoffContractStatus.expired

    def test_C6_from_string_cancelled(self):
        assert HandoffContractStatus.from_string("cancelled") == HandoffContractStatus.cancelled

    def test_C7_from_string_bogus_defaults_draft(self):
        assert HandoffContractStatus.from_string("bogus") == HandoffContractStatus.draft

    def test_C8_from_string_non_string_defaults_draft(self):
        assert HandoffContractStatus.from_string(None) == HandoffContractStatus.draft  # type: ignore[arg-type]

    def test_C9_is_terminal_dispatched(self):
        assert HandoffContractStatus.dispatched.is_terminal() is True

    def test_C10_is_terminal_expired(self):
        assert HandoffContractStatus.expired.is_terminal() is True

    def test_C11_is_terminal_cancelled(self):
        assert HandoffContractStatus.cancelled.is_terminal() is True

    def test_C12_is_not_terminal_draft(self):
        assert HandoffContractStatus.draft.is_terminal() is False

    def test_C13_is_not_terminal_sealed(self):
        assert HandoffContractStatus.sealed.is_terminal() is False

    def test_C14_is_dispatch_ready_sealed_only(self):
        assert HandoffContractStatus.sealed.is_dispatch_ready() is True
        assert HandoffContractStatus.draft.is_dispatch_ready() is False
        assert HandoffContractStatus.dispatched.is_dispatch_ready() is False

    def test_BB_can_advance_to_terminal_from_terminal_is_false(self):
        assert HandoffContractStatus.dispatched.can_advance_to(HandoffContractStatus.sealed) is False
        assert HandoffContractStatus.cancelled.can_advance_to(HandoffContractStatus.draft) is False

    def test_BC_can_advance_draft_to_sealed(self):
        assert HandoffContractStatus.draft.can_advance_to(HandoffContractStatus.sealed) is True

    def test_BD_can_advance_sealed_to_dispatched(self):
        assert HandoffContractStatus.sealed.can_advance_to(HandoffContractStatus.dispatched) is True

    def test_BE_can_advance_draft_to_cancelled(self):
        assert HandoffContractStatus.draft.can_advance_to(HandoffContractStatus.cancelled) is True

    def test_BF_cannot_regress_sealed_to_draft(self):
        assert HandoffContractStatus.sealed.can_advance_to(HandoffContractStatus.draft) is False

    def test_AY_from_string_uppercase_normalised(self):
        assert HandoffContractStatus.from_string("SEALED") == HandoffContractStatus.sealed


# ---------------------------------------------------------------------------
# Group D — DelegatedHandoffContractIdentity
# ---------------------------------------------------------------------------

class TestGroupD:
    def test_D1_defaults(self):
        ident = DelegatedHandoffContractIdentity()
        assert isinstance(ident.contract_id, str)
        assert len(ident.contract_id) > 0
        assert ident.session_id == ""
        assert ident.device_id == ""
        assert ident.trace_id == ""
        assert ident.dispatch_record_id == ""

    def test_D2_construction(self):
        cid = str(uuid.uuid4())
        ident = DelegatedHandoffContractIdentity(
            contract_id=cid,
            session_id="s1",
            device_id="d1",
            trace_id="t1",
            dispatch_record_id="dr1",
        )
        assert ident.contract_id == cid
        assert ident.session_id == "s1"
        assert ident.device_id == "d1"
        assert ident.trace_id == "t1"
        assert ident.dispatch_record_id == "dr1"

    def test_D3_to_dict(self):
        ident = DelegatedHandoffContractIdentity(session_id="s", dispatch_record_id="dr")
        d = ident.to_dict()
        assert set(d.keys()) == {"contract_id", "session_id", "device_id", "trace_id", "dispatch_record_id"}
        assert d["session_id"] == "s"

    def test_D4_to_json(self):
        ident = DelegatedHandoffContractIdentity(session_id="s")
        raw = ident.to_json()
        parsed = json.loads(raw)
        assert parsed["session_id"] == "s"

    def test_D5_from_dict(self):
        cid = str(uuid.uuid4())
        d = {"contract_id": cid, "session_id": "s2", "dispatch_record_id": "dr2"}
        ident = DelegatedHandoffContractIdentity.from_dict(d)
        assert ident.contract_id == cid
        assert ident.session_id == "s2"
        assert ident.dispatch_record_id == "dr2"

    def test_BY_from_dict_non_dict_raises(self):
        with pytest.raises(ValueError):
            DelegatedHandoffContractIdentity.from_dict("not-a-dict")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Group E — DelegatedHandoffContractMeta
# ---------------------------------------------------------------------------

class TestGroupE:
    def test_E1_defaults(self):
        meta = DelegatedHandoffContractMeta()
        assert meta.source_runtime_posture == "control_only"
        assert meta.coordination_role == ""
        assert meta.android_host_role == ""
        assert meta.capability_tier == "unknown"
        assert meta.delegation_intent == "none"
        assert meta.continuation_hint == ""
        assert meta.contract_version == HandoffContractVersion.v2
        assert meta.metadata == {}

    def test_E2_construction(self):
        meta = DelegatedHandoffContractMeta(
            source_runtime_posture="join_runtime",
            coordination_role="source_controller",
            android_host_role="full_runtime_host",
            capability_tier="full_runtime",
            delegation_intent="delegate",
            continuation_hint="hint123",
            contract_version=HandoffContractVersion.v1,
            metadata={"k": "v"},
        )
        assert meta.source_runtime_posture == "join_runtime"
        assert meta.contract_version == HandoffContractVersion.v1
        assert meta.metadata == {"k": "v"}

    def test_E3_to_dict_keys(self):
        meta = DelegatedHandoffContractMeta()
        d = meta.to_dict()
        expected = {
            "source_runtime_posture", "coordination_role", "android_host_role",
            "capability_tier", "delegation_intent", "continuation_hint",
            "contract_version", "metadata",
        }
        assert set(d.keys()) == expected

    def test_E4_to_json_valid(self):
        meta = DelegatedHandoffContractMeta()
        parsed = json.loads(meta.to_json())
        assert parsed["contract_version"] == "v2"

    def test_E5_from_dict_round_trip(self):
        meta = DelegatedHandoffContractMeta(source_runtime_posture="join_runtime")
        rt = DelegatedHandoffContractMeta.from_dict(meta.to_dict())
        assert rt.source_runtime_posture == "join_runtime"

    def test_BZ_from_dict_non_dict_raises(self):
        with pytest.raises(ValueError):
            DelegatedHandoffContractMeta.from_dict(42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Group F — DelegatedHandoffContractPayload
# ---------------------------------------------------------------------------

class TestGroupF:
    def test_F1_defaults(self):
        p = DelegatedHandoffContractPayload()
        assert p.task_body == {}
        assert p.task_id == ""
        assert p.capability == ""
        assert p.exec_mode == "remote"
        assert p.raw_payload == {}
        assert p.metadata == {}

    def test_F2_construction(self):
        body = {"cmd": "run"}
        p = DelegatedHandoffContractPayload(
            task_body=body,
            task_id="t1",
            capability="screen_control",
            exec_mode="local",
            raw_payload={"raw": True},
            metadata={"m": 1},
        )
        assert p.task_body == body
        assert p.task_id == "t1"
        assert p.capability == "screen_control"

    def test_F3_to_dict_keys(self):
        p = DelegatedHandoffContractPayload()
        d = p.to_dict()
        assert set(d.keys()) == {
            "task_body", "task_id", "capability", "exec_mode", "raw_payload", "metadata"
        }

    def test_F4_to_json_valid(self):
        p = DelegatedHandoffContractPayload(task_body={"x": 1})
        parsed = json.loads(p.to_json())
        assert parsed["task_body"] == {"x": 1}

    def test_F5_from_dict_round_trip(self):
        p = DelegatedHandoffContractPayload(capability="cap1")
        rt = DelegatedHandoffContractPayload.from_dict(p.to_dict())
        assert rt.capability == "cap1"

    def test_CA_from_dict_non_dict_raises(self):
        with pytest.raises(ValueError):
            DelegatedHandoffContractPayload.from_dict("x")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Group G — DelegatedHandoffContractRecord
# ---------------------------------------------------------------------------

class TestGroupG:
    def test_G1_defaults(self):
        r = DelegatedHandoffContractRecord()
        assert isinstance(r.identity, DelegatedHandoffContractIdentity)
        assert isinstance(r.meta, DelegatedHandoffContractMeta)
        assert isinstance(r.payload, DelegatedHandoffContractPayload)
        assert r.status == HandoffContractStatus.draft
        assert r.reject_reason == ""
        assert r.sealed_at == 0.0

    def test_G2_is_accepted_no_reject_reason(self):
        r = DelegatedHandoffContractRecord(
            identity=DelegatedHandoffContractIdentity(
                session_id="s1", dispatch_record_id="dr1"
            ),
        )
        assert r.is_accepted() is True

    def test_BG_is_accepted_false_when_reject_reason(self):
        r = DelegatedHandoffContractRecord(
            identity=DelegatedHandoffContractIdentity(session_id="s1", dispatch_record_id="dr1"),
            reject_reason="bad",
        )
        assert r.is_accepted() is False

    def test_BH_is_accepted_false_when_session_empty(self):
        r = DelegatedHandoffContractRecord(
            identity=DelegatedHandoffContractIdentity(session_id="", dispatch_record_id="dr1"),
        )
        assert r.is_accepted() is False

    def test_BI_is_rejected_true_when_reject_reason(self):
        r = DelegatedHandoffContractRecord(reject_reason="oops")
        assert r.is_rejected() is True

    def test_BJ_is_pending_true_when_draft(self):
        r = DelegatedHandoffContractRecord(status=HandoffContractStatus.draft)
        assert r.is_pending() is True

    def test_G3_is_pending_true_when_sealed(self):
        r = DelegatedHandoffContractRecord(status=HandoffContractStatus.sealed)
        assert r.is_pending() is True

    def test_BK_is_pending_false_when_dispatched(self):
        r = DelegatedHandoffContractRecord(status=HandoffContractStatus.dispatched)
        assert r.is_pending() is False

    def test_G4_to_dict_keys(self):
        r = DelegatedHandoffContractRecord()
        d = r.to_dict()
        assert set(d.keys()) == {
            "identity", "meta", "payload", "status", "created_at", "sealed_at", "reject_reason"
        }

    def test_G5_to_json_valid(self):
        r = DelegatedHandoffContractRecord()
        parsed = json.loads(r.to_json())
        assert parsed["status"] == "draft"

    def test_AT_from_dict_round_trip(self):
        rt_obj = _fresh_runtime()
        r = _make_accepted(rt=rt_obj)
        restored = DelegatedHandoffContractRecord.from_dict(r.to_dict())
        assert restored.identity.session_id == r.identity.session_id
        assert restored.status == HandoffContractStatus.draft
        assert restored.reject_reason == ""

    def test_CB_from_dict_non_dict_raises(self):
        with pytest.raises(ValueError):
            DelegatedHandoffContractRecord.from_dict(99)  # type: ignore[arg-type]

    def test_BX_from_dict_missing_fields_use_safe_defaults(self):
        r = DelegatedHandoffContractRecord.from_dict({})
        assert r.status == HandoffContractStatus.draft
        assert r.reject_reason == ""
        assert r.sealed_at == 0.0


# ---------------------------------------------------------------------------
# Group H — DelegatedHandoffContractSnapshot
# ---------------------------------------------------------------------------

class TestGroupH:
    def test_H1_defaults(self):
        snap = DelegatedHandoffContractSnapshot()
        assert isinstance(snap.snapshot_id, str)
        assert snap.records == []
        assert snap.pending_count == 0
        assert snap.total_count == 0
        assert isinstance(snap.snapshotted_at, float)
        assert snap.policy_sentinels == []

    def test_H2_to_dict_keys(self):
        snap = DelegatedHandoffContractSnapshot()
        d = snap.to_dict()
        assert set(d.keys()) == {
            "snapshot_id", "records", "pending_count", "total_count",
            "snapshotted_at", "policy_sentinels",
        }

    def test_CE_to_json_valid(self):
        snap = DelegatedHandoffContractSnapshot()
        parsed = json.loads(snap.to_json())
        assert "pending_count" in parsed

    def test_AZ_snapshotted_at_is_recent(self):
        before = time.time()
        snap = DelegatedHandoffContractSnapshot()
        after = time.time()
        assert before <= snap.snapshotted_at <= after


# ---------------------------------------------------------------------------
# Group I — DelegatedHandoffContractRuntime
# ---------------------------------------------------------------------------

class TestGroupI:
    def test_AR_capacity_128(self):
        rt = DelegatedHandoffContractRuntime()
        assert rt.capacity == 128

    def test_I1_push_and_size(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        assert rt.size == 1

    def test_I2_list_all_newest_first(self):
        rt = _fresh_runtime()
        r1 = _make_accepted(rt=rt)
        r2 = _make_accepted(rt=rt)
        all_records = rt.list_all()
        assert all_records[0].identity.contract_id == r2.identity.contract_id

    def test_I3_list_pending_draft_and_sealed(self):
        rt = _fresh_runtime()
        draft = _make_accepted(rt=rt)
        sealed = seal_handoff_contract(draft, runtime=rt)
        pending = rt.list_pending()
        cids = {r.identity.contract_id for r in pending}
        # sealed record is a new entry so both are in pending
        assert sealed.identity.contract_id in cids

    def test_I4_get_latest_for_session(self):
        rt = _fresh_runtime()
        sid = _session_id()
        r = _make_accepted(rt=rt, session_id=sid)
        result = rt.get_latest_for_session(sid)
        assert result is not None
        assert result.identity.session_id == sid

    def test_AJ_get_latest_for_session_none_for_unknown(self):
        rt = _fresh_runtime()
        assert rt.get_latest_for_session("nonexistent") is None

    def test_CF_clear_empties_buffer(self):
        rt = _fresh_runtime()
        _make_accepted(rt=rt)
        rt.clear()
        assert rt.size == 0

    def test_AS_ring_buffer_eviction(self):
        rt = _fresh_runtime()
        for _ in range(130):
            _make_accepted(rt=rt)
        assert rt.size == 128


# ---------------------------------------------------------------------------
# Group J — build_delegated_handoff_contract: accepted paths
# ---------------------------------------------------------------------------

class TestGroupJ:
    def test_J1_valid_inputs_accepted(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        assert r.is_accepted()
        assert r.status == HandoffContractStatus.draft
        assert r.reject_reason == ""

    def test_N_trace_id_auto_generated_when_absent(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            runtime=rt,
        )
        assert r.identity.trace_id != ""

    def test_O_trace_id_propagated_when_provided(self):
        rt = _fresh_runtime()
        tid = "trace-abc"
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            trace_id=tid,
            runtime=rt,
        )
        assert r.identity.trace_id == tid

    def test_P_task_id_auto_generated_when_absent(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            runtime=rt,
        )
        assert r.payload.task_id != ""

    def test_Q_posture_preserved(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            source_runtime_posture="join_runtime",
            runtime=rt,
        )
        assert r.meta.source_runtime_posture == "join_runtime"

    def test_R_coordination_role_forwarded(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            coordination_role="source_controller",
            runtime=rt,
        )
        assert r.meta.coordination_role == "source_controller"

    def test_S_android_host_role_forwarded(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            android_host_role="full_runtime_host",
            runtime=rt,
        )
        assert r.meta.android_host_role == "full_runtime_host"

    def test_T_capability_tier_forwarded(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            capability_tier="full_runtime",
            runtime=rt,
        )
        assert r.meta.capability_tier == "full_runtime"

    def test_U_delegation_intent_forwarded(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            delegation_intent="delegate",
            runtime=rt,
        )
        assert r.meta.delegation_intent == "delegate"

    def test_V_continuation_hint_forwarded(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            continuation_hint="chkpt-42",
            runtime=rt,
        )
        assert r.meta.continuation_hint == "chkpt-42"

    def test_W_contract_version_forwarded(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            contract_version=HandoffContractVersion.v1,
            runtime=rt,
        )
        assert r.meta.contract_version == HandoffContractVersion.v1

    def test_X_meta_metadata_propagated(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            meta_metadata={"k": "v"},
            runtime=rt,
        )
        assert r.meta.metadata == {"k": "v"}

    def test_Y_payload_metadata_propagated(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            payload_metadata={"pm": 1},
            runtime=rt,
        )
        assert r.payload.metadata == {"pm": 1}

    def test_Z_raw_payload_defaults_to_task_body(self):
        rt = _fresh_runtime()
        body = _task_body()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body=body,
            runtime=rt,
        )
        assert r.payload.raw_payload == body

    def test_AA_persisted_to_runtime(self):
        rt = _fresh_runtime()
        _make_accepted(rt=rt)
        assert rt.size == 1

    def test_AB_custom_runtime_isolation(self):
        rt1 = _fresh_runtime()
        rt2 = _fresh_runtime()
        _make_accepted(rt=rt1)
        assert rt2.size == 0

    def test_BL_contract_id_is_auto_generated_uuid(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        cid = r.identity.contract_id
        assert isinstance(cid, str) and len(cid) == 36  # UUID4 format


# ---------------------------------------------------------------------------
# Group K — build_delegated_handoff_contract: rejection paths
# ---------------------------------------------------------------------------

class TestGroupK:
    def test_K1_empty_session_id_rejected(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id="",
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            runtime=rt,
        )
        assert r.is_rejected()
        assert r.status == HandoffContractStatus.cancelled

    def test_L1_empty_dispatch_record_id_rejected(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id="",
            task_body=_task_body(),
            runtime=rt,
        )
        assert r.is_rejected()
        assert r.status == HandoffContractStatus.cancelled

    def test_M1_empty_task_body_rejected(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id=_session_id(),
            dispatch_record_id=_dispatch_id(),
            task_body={},
            runtime=rt,
        )
        assert r.is_rejected()
        assert r.status == HandoffContractStatus.cancelled

    def test_BN_reject_reason_empty_when_accepted(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        assert r.reject_reason == ""

    def test_BO_identity_keys(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        d = r.identity.to_dict()
        assert "contract_id" in d
        assert "session_id" in d
        assert "dispatch_record_id" in d

    def test_BP_meta_keys(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        d = r.meta.to_dict()
        assert "source_runtime_posture" in d
        assert "contract_version" in d

    def test_BQ_payload_keys(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        d = r.payload.to_dict()
        assert "task_body" in d
        assert "exec_mode" in d


# ---------------------------------------------------------------------------
# Group AC — seal_handoff_contract
# ---------------------------------------------------------------------------

class TestGroupAC:
    def test_AC1_draft_advances_to_sealed(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        sealed = seal_handoff_contract(r, runtime=rt)
        assert sealed.status == HandoffContractStatus.sealed

    def test_AD_sealed_at_set(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        before = time.time()
        sealed = seal_handoff_contract(r, runtime=rt)
        after = time.time()
        assert before <= sealed.sealed_at <= after

    def test_AE_already_terminal_returned_unchanged(self):
        rt = _fresh_runtime()
        cancelled = DelegatedHandoffContractRecord(
            status=HandoffContractStatus.cancelled
        )
        result = seal_handoff_contract(cancelled, runtime=rt)
        assert result is cancelled

    def test_CC_already_cancelled_returned_unchanged(self):
        rt = _fresh_runtime()
        r = build_delegated_handoff_contract(
            session_id="",
            dispatch_record_id=_dispatch_id(),
            task_body=_task_body(),
            runtime=rt,
        )
        before_size = rt.size
        result = seal_handoff_contract(r, runtime=rt)
        assert result is r
        assert rt.size == before_size

    def test_CD_already_expired_returned_unchanged(self):
        rt = _fresh_runtime()
        expired = DelegatedHandoffContractRecord(
            status=HandoffContractStatus.expired
        )
        result = seal_handoff_contract(expired, runtime=rt)
        assert result is expired

    def test_AF_sealed_record_persisted(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        size_before = rt.size
        seal_handoff_contract(r, runtime=rt)
        assert rt.size == size_before + 1

    def test_AG_is_dispatch_ready_after_sealing(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        sealed = seal_handoff_contract(r, runtime=rt)
        assert sealed.is_dispatch_ready() is True


# ---------------------------------------------------------------------------
# Group AH–AI — record_handoff_contract / get_handoff_contract
# ---------------------------------------------------------------------------

class TestGroupAHAI:
    def test_AH_record_persists(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        rt2 = _fresh_runtime()
        record_handoff_contract(r, runtime=rt2)
        assert rt2.size == 1

    def test_AI_get_returns_latest_for_session(self):
        rt = _fresh_runtime()
        sid = _session_id()
        r = _make_accepted(rt=rt, session_id=sid)
        result = get_handoff_contract(sid, runtime=rt)
        assert result is not None
        assert result.identity.session_id == sid

    def test_AJ_get_returns_none_for_unknown_session(self):
        rt = _fresh_runtime()
        assert get_handoff_contract("ghost-session", runtime=rt) is None


# ---------------------------------------------------------------------------
# Group AK–AL — list_pending_handoff_contracts
# ---------------------------------------------------------------------------

class TestGroupAKAL:
    def test_AK_returns_draft_and_sealed(self):
        rt = _fresh_runtime()
        draft = _make_accepted(rt=rt)
        sealed = seal_handoff_contract(draft, runtime=rt)
        pending = list_pending_handoff_contracts(runtime=rt)
        cids = {r.identity.contract_id for r in pending}
        assert draft.identity.contract_id in cids
        assert sealed.identity.contract_id in cids

    def test_AL_empty_when_no_pending(self):
        rt = _fresh_runtime()
        pending = list_pending_handoff_contracts(runtime=rt)
        assert pending == []

    def test_CH_excludes_dispatched_expired_cancelled(self):
        rt = _fresh_runtime()
        dispatched = DelegatedHandoffContractRecord(
            identity=DelegatedHandoffContractIdentity(session_id="s1"),
            status=HandoffContractStatus.dispatched,
        )
        record_handoff_contract(dispatched, runtime=rt)
        expired_r = DelegatedHandoffContractRecord(
            identity=DelegatedHandoffContractIdentity(session_id="s2"),
            status=HandoffContractStatus.expired,
        )
        record_handoff_contract(expired_r, runtime=rt)
        cancelled_r = DelegatedHandoffContractRecord(
            identity=DelegatedHandoffContractIdentity(session_id="s3"),
            status=HandoffContractStatus.cancelled,
        )
        record_handoff_contract(cancelled_r, runtime=rt)
        pending = list_pending_handoff_contracts(runtime=rt)
        assert pending == []

    def test_BT_two_sessions_both_pending(self):
        rt = _fresh_runtime()
        r1 = _make_accepted(rt=rt)
        r2 = _make_accepted(rt=rt)
        pending = list_pending_handoff_contracts(runtime=rt)
        cids = {r.identity.contract_id for r in pending}
        assert r1.identity.contract_id in cids
        assert r2.identity.contract_id in cids


# ---------------------------------------------------------------------------
# Group AM–AO — build_handoff_contract_snapshot
# ---------------------------------------------------------------------------

class TestGroupAMAO:
    def test_AM_pending_and_total_counts(self):
        rt = _fresh_runtime()
        _make_accepted(rt=rt)
        sealed = seal_handoff_contract(_make_accepted(rt=rt), runtime=rt)
        dispatched = DelegatedHandoffContractRecord(
            identity=DelegatedHandoffContractIdentity(session_id="sd"),
            status=HandoffContractStatus.dispatched,
        )
        record_handoff_contract(dispatched, runtime=rt)
        snap = build_handoff_contract_snapshot(runtime=rt)
        assert snap.total_count >= 3
        assert snap.pending_count >= 2

    def test_AN_includes_policy_sentinels(self):
        rt = _fresh_runtime()
        snap = build_handoff_contract_snapshot(runtime=rt)
        assert len(snap.policy_sentinels) == 10
        for s in snap.policy_sentinels:
            assert isinstance(s, str) and len(s) > 0

    def test_AO_empty_runtime_zero_counts(self):
        rt = _fresh_runtime()
        snap = build_handoff_contract_snapshot(runtime=rt)
        assert snap.pending_count == 0
        assert snap.total_count == 0

    def test_BM_snapshot_dict_keys(self):
        rt = _fresh_runtime()
        snap = build_handoff_contract_snapshot(runtime=rt)
        d = snap.to_dict()
        assert "records" in d
        assert "pending_count" in d
        assert "total_count" in d

    def test_CI_records_newest_first(self):
        rt = _fresh_runtime()
        r1 = _make_accepted(rt=rt)
        r2 = _make_accepted(rt=rt)
        snap = build_handoff_contract_snapshot(runtime=rt)
        assert snap.records[0].identity.contract_id == r2.identity.contract_id


# ---------------------------------------------------------------------------
# Group AP — core.runtime re-exports
# ---------------------------------------------------------------------------

class TestGroupAP:
    def test_AP_all_pr9_symbols_accessible_from_core_runtime(self):
        pytest.importorskip("pydantic")
        from core.runtime import (  # noqa: F401
            DELEGATED_RUNTIME_HANDOFF_CONTRACT_AUTHORITY,
            DELEGATED_RUNTIME_HANDOFF_CONTRACT_PR9_SENTINEL,
            HANDOFF_CONTRACT_IDENTITY_IS_IMMUTABLE_POLICY,
            HANDOFF_CONTRACT_PAYLOAD_MUST_BE_NON_EMPTY_POLICY,
            HANDOFF_CONTRACT_POSTURE_IS_PRESERVED_POLICY,
            HANDOFF_CONTRACT_REQUIRES_ATTACHED_SESSION_POLICY,
            HANDOFF_CONTRACT_REQUIRES_DISPATCH_RECORD_POLICY,
            HANDOFF_CONTRACT_STATUS_IS_MONOTONIC_POLICY,
            HANDOFF_CONTRACT_TRACE_ID_IS_PROPAGATED_POLICY,
            HANDOFF_CONTRACT_VERSION_MUST_BE_EXPLICIT_POLICY,
            SEALED_CONTRACT_IS_DISPATCH_READY_POLICY,
            DelegatedHandoffContractIdentity,
            DelegatedHandoffContractMeta,
            DelegatedHandoffContractPayload,
            DelegatedHandoffContractRecord,
            DelegatedHandoffContractRuntime,
            DelegatedHandoffContractSnapshot,
            HandoffContractStatus,
            HandoffContractVersion,
            build_delegated_handoff_contract,
            build_handoff_contract_snapshot,
            get_handoff_contract,
            get_handoff_contract_runtime,
            list_pending_handoff_contracts,
            record_handoff_contract,
            reset_handoff_contract_runtime,
            seal_handoff_contract,
        )


# ---------------------------------------------------------------------------
# Group AQ — projection.py sentinel
# ---------------------------------------------------------------------------

class TestGroupAQ:
    def test_AQ_projection_sentinel_present_and_not_unavailable(self):
        pytest.importorskip("fastapi")
        from core.routes.projection import DELEGATED_RUNTIME_HANDOFF_CONTRACT_ALIGNED_PR9
        assert "UNAVAILABLE" not in DELEGATED_RUNTIME_HANDOFF_CONTRACT_ALIGNED_PR9
        assert "PR9" in DELEGATED_RUNTIME_HANDOFF_CONTRACT_ALIGNED_PR9


# ---------------------------------------------------------------------------
# Group BR–BS — singleton management
# ---------------------------------------------------------------------------

class TestGroupBRBS:
    def test_BR_get_runtime_returns_same_singleton(self):
        reset_handoff_contract_runtime()
        rt1 = get_handoff_contract_runtime()
        rt2 = get_handoff_contract_runtime()
        assert rt1 is rt2

    def test_BS_reset_replaces_singleton(self):
        reset_handoff_contract_runtime()
        rt1 = get_handoff_contract_runtime()
        rt1.push(DelegatedHandoffContractRecord())
        reset_handoff_contract_runtime()
        rt2 = get_handoff_contract_runtime()
        assert rt2.size == 0


# ---------------------------------------------------------------------------
# Group AU–AV — serialisation
# ---------------------------------------------------------------------------

class TestGroupAUAV:
    def test_AU_to_json_valid(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        raw = r.to_json()
        parsed = json.loads(raw)
        assert parsed["status"] == "draft"

    def test_AV_from_dict_with_non_dict_raises(self):
        with pytest.raises(ValueError):
            DelegatedHandoffContractRecord.from_dict("nope")  # type: ignore[arg-type]

    def test_CG_contract_id_stable_round_trip(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        restored = DelegatedHandoffContractRecord.from_dict(r.to_dict())
        assert restored.identity.contract_id == r.identity.contract_id


# ---------------------------------------------------------------------------
# Group AW — multiple sessions
# ---------------------------------------------------------------------------

class TestGroupAW:
    def test_AW_multiple_sessions_independent(self):
        rt = _fresh_runtime()
        sid1 = _session_id()
        sid2 = _session_id()
        _make_accepted(rt=rt, session_id=sid1)
        _make_accepted(rt=rt, session_id=sid2)
        r1 = get_handoff_contract(sid1, runtime=rt)
        r2 = get_handoff_contract(sid2, runtime=rt)
        assert r1 is not None and r1.identity.session_id == sid1
        assert r2 is not None and r2.identity.session_id == sid2

    def test_BU_build_does_not_mutate_other_records(self):
        rt = _fresh_runtime()
        sid1 = _session_id()
        r1 = _make_accepted(rt=rt, session_id=sid1)
        _make_accepted(rt=rt)
        retrieved = get_handoff_contract(sid1, runtime=rt)
        assert retrieved is not None
        assert retrieved.identity.session_id == sid1


# ---------------------------------------------------------------------------
# Group BV–BW — end-to-end and PR9 sentinel
# ---------------------------------------------------------------------------

class TestGroupBVBW:
    def test_BV_end_to_end_build_seal_snapshot(self):
        rt = _fresh_runtime()
        r = _make_accepted(rt=rt)
        assert r.status == HandoffContractStatus.draft
        sealed = seal_handoff_contract(r, runtime=rt)
        assert sealed.status == HandoffContractStatus.sealed
        snap = build_handoff_contract_snapshot(runtime=rt)
        statuses = {rec.status for rec in snap.records}
        assert HandoffContractStatus.sealed in statuses

    def test_BW_pr9_sentinel_contains_package_9(self):
        assert "package=9" in DELEGATED_RUNTIME_HANDOFF_CONTRACT_PR9_SENTINEL
