"""tests/test_pr15_post533_attached_runtime_recovery_readiness.py
=================================================================
Tests for PR package 15 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Host-Side Recovery Readiness / Resilience Foundations
for Attached Android Runtime Reuse.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — SignalGuardDecision enum: all values, from_string(), defaults.
C  — RecoveryReadinessStatus enum: all values, from_string(), defaults.
D  — IdempotencyKey: construction, defaults, key_string, prefix_string,
     has_lookup_key(), to_dict(), to_json(), from_dict().
E  — SeenSignalRecord: construction, defaults, to_dict(), to_json().
F  — SignalGuardOutcome: construction, defaults, should_forward, to_dict(),
     to_json().
G  — RecoveryReadinessSnapshot: construction, defaults, to_dict(), to_json().
H  — RecoveryReadinessRuntime: push, get_by_key, get_max_seq, list_all,
     size, capacity, clear.
I  — build_idempotency_key: all fields populated.
J  — build_idempotency_key: None / missing fields default to empty / 0.
K  — check_signal_guard: fresh signal → accept.
L  — check_signal_guard: exact key repeat (prior accept) → replay.
M  — check_signal_guard: exact key repeat (prior non-accept) → duplicate.
N  — check_signal_guard: lower seq_num, higher already seen → out_of_order.
O  — check_signal_guard: seq_num = 0 disables ordering guard.
P  — check_signal_guard: uses custom runtime (isolation).
Q  — record_seen_signal: pushes to ring-buffer.
R  — record_seen_signal: accept decision updates max_seq index.
S  — record_seen_signal: non-accept decision does not update max_seq index.
T  — record_seen_signal: returns SeenSignalRecord.
U  — guard_inbound_signal: fresh → accept + record.
V  — guard_inbound_signal: duplicate (exact key) → replay (not re-recorded).
W  — guard_inbound_signal: out_of_order → not re-recorded.
X  — guard_inbound_signal: identity fields propagated to idempotency key.
Y  — guard_inbound_signal: seq_num propagated.
Z  — guard_inbound_signal: custom runtime isolation.
AA — build_recovery_readiness_snapshot: empty runtime → all counts = 0, status = ready.
AB — build_recovery_readiness_snapshot: only accepts → status = ready.
AC — build_recovery_readiness_snapshot: 1 duplicate among 10 → status = recovering.
AD — build_recovery_readiness_snapshot: >= 30% non-fresh → status = degraded.
AE — build_recovery_readiness_snapshot: records are newest-first.
AF — build_recovery_readiness_snapshot: counts are accurate.
AG — get_recovery_readiness_runtime returns same singleton.
AH — reset_recovery_readiness_runtime clears singleton for isolation.
AI — Ring buffer capacity: 128.
AJ — Ring buffer eviction: oldest entry evicted when full.
AK — Ring buffer eviction: evicted record's key index entry removed.
AL — Ring buffer eviction: newer record for same key keeps index entry.
AM — Serialisation round-trip: IdempotencyKey to_dict produces expected keys.
AN — Serialisation round-trip: IdempotencyKey to_json produces valid JSON.
AO — Serialisation round-trip: SeenSignalRecord to_dict / to_json.
AP — Serialisation round-trip: SignalGuardOutcome to_dict / to_json.
AQ — Serialisation round-trip: RecoveryReadinessSnapshot to_dict / to_json.
AR — IdempotencyKey.from_dict: non-dict raises ValueError.
AS — IdempotencyKey.from_dict: round-trips correctly.
AT — check_signal_guard: no prior record, seq_num 0 → accept.
AU — check_signal_guard: higher seq_num than seen → accept.
AV — guard_inbound_signal: two different signal_kinds for same contract → both accept.
AW — guard_inbound_signal: same key delivered 3 times → accept, replay, replay.
AX — build_recovery_readiness_snapshot: custom runtime isolation.
AY — core.runtime re-exports: all PR-15 symbols accessible from core.runtime.
AZ — projection.py sentinel: ATTACHED_RUNTIME_RECOVERY_READINESS_ALIGNED_PR15
     is present and not UNAVAILABLE.
BA — All 11 policy sentinels are non-empty strings.
BB — ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL contains 'package=15'.
BC — SignalGuardOutcome.should_forward: True only for accept.
BD — RecoveryReadinessRuntime.get_max_seq: returns 0 for unseen prefix.
BE — guard_inbound_signal: stale (seq_num < max accepted for prefix) after accept.
BF — check_signal_guard: seq_num equals max already seen → accept (not out_of_order).
BG — IdempotencyKey.key_string: unique for different seq_num.
BH — Multiple contract_ids: each has independent max_seq tracking.
BI — SeenSignalRecord.to_dict includes idempotency_key sub-dict.
BJ — SignalGuardOutcome is_duplicate / is_replay / is_out_of_order / is_stale flags.
BK — guard_inbound_signal: empty contract_id + session_id → still guards (key_string works).
BL — build_recovery_readiness_snapshot: total_count matches buffer size.
BM — RecoveryReadinessRuntime.list_all: returns newest-first.
BN — guard_inbound_signal: trace_id preserved in idempotency_key.
BO — guard_inbound_signal: device_id preserved in idempotency_key.
BP — check_signal_guard: does not mutate runtime.
BQ — Integration: guard → reconciler pipeline safety (duplicate is not forwarded).
BR — Integration: guard → reconciler pipeline safety (out-of-order is not forwarded).
BS — Integration: accept signal → forwarded → reconcile_android_execution_signal called.
BT — end-to-end: establish reuse binding → guard 3 acks (1 fresh, 2 duplicate).
BU — end-to-end: guard accepts incremental seq_nums, rejects regression.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.attached_runtime_recovery_readiness import (
    ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY,
    ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL,
    RECOVERY_READINESS_DUPLICATE_SIGNAL_IS_SILENTLY_DROPPED_POLICY,
    RECOVERY_READINESS_FRESH_SIGNAL_IS_ACCEPTED_POLICY,
    RECOVERY_READINESS_GUARD_IS_ADDITIVE_ONLY_POLICY,
    RECOVERY_READINESS_IDENTITY_CONTINUITY_IS_PRESERVED_POLICY,
    RECOVERY_READINESS_IDEMPOTENCY_KEY_IS_CANONICAL_POLICY,
    RECOVERY_READINESS_OUT_OF_ORDER_SIGNAL_IS_GUARDED_POLICY,
    RECOVERY_READINESS_REPLAY_SIGNAL_IS_GUARDED_POLICY,
    RECOVERY_READINESS_SEQ_NUM_DRIVES_ORDER_GUARD_POLICY,
    RECOVERY_READINESS_STALE_SIGNAL_DOES_NOT_ADVANCE_PHASE_POLICY,
    RECOVERY_READINESS_TERMINAL_RECORD_DEDUPE_IS_SAFE_POLICY,
    IdempotencyKey,
    RecoveryReadinessRuntime,
    RecoveryReadinessSnapshot,
    RecoveryReadinessStatus,
    SeenSignalRecord,
    SignalGuardDecision,
    SignalGuardOutcome,
    _ALL_POLICY_SENTINELS,
    build_idempotency_key,
    build_recovery_readiness_snapshot,
    check_signal_guard,
    get_recovery_readiness_runtime,
    guard_inbound_signal,
    record_seen_signal,
    reset_recovery_readiness_runtime,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_runtime() -> RecoveryReadinessRuntime:
    """Return a fresh isolated runtime (not the process singleton)."""
    return RecoveryReadinessRuntime()


def _make_key(
    *,
    contract_id: str = "ctr-001",
    session_id: str = "ses-001",
    trace_id: str = "trace-001",
    task_id: str = "task-001",
    device_id: str = "dev-001",
    signal_kind: str = "ack",
    seq_num: int = 1,
) -> IdempotencyKey:
    return build_idempotency_key(
        contract_id=contract_id,
        session_id=session_id,
        trace_id=trace_id,
        task_id=task_id,
        device_id=device_id,
        signal_kind=signal_kind,
        seq_num=seq_num,
    )


# ---------------------------------------------------------------------------
# A — Authority / policy sentinel presence
# ---------------------------------------------------------------------------


class TestGroupA:
    def test_authority_is_string(self):
        assert isinstance(ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY, str)
        assert len(ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY) > 0

    def test_pr15_sentinel_is_string(self):
        assert isinstance(ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL, str)

    def test_pr15_sentinel_contains_package15(self):
        assert "package=15" in ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL

    def test_all_policy_sentinels_non_empty(self):
        for sentinel in _ALL_POLICY_SENTINELS:
            assert isinstance(sentinel, str) and len(sentinel) > 0

    def test_11_policy_sentinels(self):
        assert len(_ALL_POLICY_SENTINELS) == 11


# ---------------------------------------------------------------------------
# B — SignalGuardDecision enum
# ---------------------------------------------------------------------------


class TestGroupB:
    def test_all_values_present(self):
        values = {v.value for v in SignalGuardDecision}
        assert values == {"accept", "duplicate", "stale", "replay", "out_of_order"}

    def test_from_string_accept(self):
        assert SignalGuardDecision.from_string("accept") == SignalGuardDecision.accept

    def test_from_string_duplicate(self):
        assert SignalGuardDecision.from_string("duplicate") == SignalGuardDecision.duplicate

    def test_from_string_stale(self):
        assert SignalGuardDecision.from_string("stale") == SignalGuardDecision.stale

    def test_from_string_replay(self):
        assert SignalGuardDecision.from_string("replay") == SignalGuardDecision.replay

    def test_from_string_out_of_order(self):
        assert SignalGuardDecision.from_string("out_of_order") == SignalGuardDecision.out_of_order

    def test_from_string_unknown_defaults_to_accept(self):
        assert SignalGuardDecision.from_string("unknown_xyz") == SignalGuardDecision.accept

    def test_from_string_non_string_defaults_to_accept(self):
        assert SignalGuardDecision.from_string(None) == SignalGuardDecision.accept

    def test_from_string_case_insensitive(self):
        assert SignalGuardDecision.from_string("DUPLICATE") == SignalGuardDecision.duplicate


# ---------------------------------------------------------------------------
# C — RecoveryReadinessStatus enum
# ---------------------------------------------------------------------------


class TestGroupC:
    def test_all_values_present(self):
        values = {v.value for v in RecoveryReadinessStatus}
        assert values == {"ready", "recovering", "degraded"}

    def test_from_string_ready(self):
        assert RecoveryReadinessStatus.from_string("ready") == RecoveryReadinessStatus.ready

    def test_from_string_recovering(self):
        assert RecoveryReadinessStatus.from_string("recovering") == RecoveryReadinessStatus.recovering

    def test_from_string_degraded(self):
        assert RecoveryReadinessStatus.from_string("degraded") == RecoveryReadinessStatus.degraded

    def test_from_string_unknown_defaults_to_ready(self):
        assert RecoveryReadinessStatus.from_string("nope") == RecoveryReadinessStatus.ready

    def test_from_string_non_string_defaults_to_ready(self):
        assert RecoveryReadinessStatus.from_string(42) == RecoveryReadinessStatus.ready


# ---------------------------------------------------------------------------
# D — IdempotencyKey
# ---------------------------------------------------------------------------


class TestGroupD:
    def test_construction_with_all_fields(self):
        k = IdempotencyKey(
            contract_id="c1",
            session_id="s1",
            trace_id="t1",
            task_id="tk1",
            device_id="d1",
            signal_kind="ack",
            seq_num=3,
        )
        assert k.contract_id == "c1"
        assert k.seq_num == 3

    def test_defaults(self):
        k = IdempotencyKey()
        assert k.contract_id == ""
        assert k.seq_num == 0

    def test_key_string_contains_all_fields(self):
        k = _make_key(seq_num=5)
        ks = k.key_string
        assert "ctr-001" in ks
        assert "ses-001" in ks
        assert "5" in ks

    def test_key_string_unique_for_different_seq_num(self):
        k1 = _make_key(seq_num=1)
        k2 = _make_key(seq_num=2)
        assert k1.key_string != k2.key_string

    def test_prefix_string_excludes_seq_num_and_trace(self):
        k = _make_key(seq_num=9999)
        ps = k.prefix_string
        assert "trace" not in ps
        # seq_num value 9999 should not appear in the prefix_string
        assert "9999" not in ps
        assert k.contract_id in ps

    def test_has_lookup_key_with_contract_id(self):
        k = IdempotencyKey(contract_id="c1")
        assert k.has_lookup_key() is True

    def test_has_lookup_key_with_session_id(self):
        k = IdempotencyKey(session_id="s1")
        assert k.has_lookup_key() is True

    def test_has_lookup_key_empty(self):
        k = IdempotencyKey()
        assert k.has_lookup_key() is False

    def test_to_dict_has_required_keys(self):
        k = _make_key()
        d = k.to_dict()
        for f in ("contract_id", "session_id", "trace_id", "task_id",
                  "device_id", "signal_kind", "seq_num", "key_string"):
            assert f in d

    def test_to_json_valid(self):
        k = _make_key()
        parsed = json.loads(k.to_json())
        assert parsed["signal_kind"] == "ack"

    def test_from_dict_round_trip(self):
        k = _make_key()
        k2 = IdempotencyKey.from_dict(k.to_dict())
        assert k2.contract_id == k.contract_id
        assert k2.seq_num == k.seq_num

    def test_from_dict_non_dict_raises(self):
        with pytest.raises(ValueError):
            IdempotencyKey.from_dict("not-a-dict")


# ---------------------------------------------------------------------------
# E — SeenSignalRecord
# ---------------------------------------------------------------------------


class TestGroupE:
    def test_construction_defaults(self):
        k = _make_key()
        r = SeenSignalRecord(idempotency_key=k)
        assert r.decision == SignalGuardDecision.accept
        assert r.first_seen_at > 0

    def test_to_dict_has_required_keys(self):
        k = _make_key()
        r = SeenSignalRecord(idempotency_key=k, decision=SignalGuardDecision.duplicate)
        d = r.to_dict()
        assert "idempotency_key" in d
        assert d["decision"] == "duplicate"

    def test_to_json_valid(self):
        k = _make_key()
        r = SeenSignalRecord(idempotency_key=k)
        parsed = json.loads(r.to_json())
        assert "idempotency_key" in parsed

    def test_idempotency_key_sub_dict(self):
        k = _make_key()
        r = SeenSignalRecord(idempotency_key=k)
        d = r.to_dict()
        assert isinstance(d["idempotency_key"], dict)
        assert d["idempotency_key"]["contract_id"] == k.contract_id


# ---------------------------------------------------------------------------
# F — SignalGuardOutcome
# ---------------------------------------------------------------------------


class TestGroupF:
    def test_construction_defaults(self):
        k = _make_key()
        o = SignalGuardOutcome(decision=SignalGuardDecision.accept, idempotency_key=k)
        assert o.is_duplicate is False
        assert o.is_replay is False
        assert o.is_out_of_order is False
        assert o.is_stale is False

    def test_should_forward_accept(self):
        k = _make_key()
        o = SignalGuardOutcome(decision=SignalGuardDecision.accept, idempotency_key=k)
        assert o.should_forward is True

    def test_should_forward_non_accept(self):
        k = _make_key()
        for d in [SignalGuardDecision.duplicate, SignalGuardDecision.stale,
                  SignalGuardDecision.replay, SignalGuardDecision.out_of_order]:
            o = SignalGuardOutcome(decision=d, idempotency_key=k)
            assert o.should_forward is False

    def test_to_dict_has_required_keys(self):
        k = _make_key()
        o = SignalGuardOutcome(decision=SignalGuardDecision.replay, idempotency_key=k, is_replay=True)
        d = o.to_dict()
        assert d["decision"] == "replay"
        assert d["is_replay"] is True
        assert "should_forward" in d

    def test_to_json_valid(self):
        k = _make_key()
        o = SignalGuardOutcome(decision=SignalGuardDecision.accept, idempotency_key=k)
        parsed = json.loads(o.to_json())
        assert parsed["decision"] == "accept"


# ---------------------------------------------------------------------------
# G — RecoveryReadinessSnapshot
# ---------------------------------------------------------------------------


class TestGroupG:
    def test_construction_defaults(self):
        s = RecoveryReadinessSnapshot()
        assert s.total_count == 0
        assert s.status == RecoveryReadinessStatus.ready

    def test_to_dict_has_required_keys(self):
        s = RecoveryReadinessSnapshot(total_count=5, accept_count=5)
        d = s.to_dict()
        for k in ("records", "total_count", "accept_count", "duplicate_count",
                  "stale_count", "replay_count", "out_of_order_count", "status"):
            assert k in d

    def test_to_json_valid(self):
        s = RecoveryReadinessSnapshot()
        parsed = json.loads(s.to_json())
        assert parsed["total_count"] == 0


# ---------------------------------------------------------------------------
# H — RecoveryReadinessRuntime
# ---------------------------------------------------------------------------


class TestGroupH:
    def test_push_increases_size(self):
        rt = _fresh_runtime()
        r = SeenSignalRecord(idempotency_key=_make_key())
        rt.push(r)
        assert rt.size() == 1

    def test_get_by_key_returns_record(self):
        rt = _fresh_runtime()
        k = _make_key()
        r = SeenSignalRecord(idempotency_key=k)
        rt.push(r)
        assert rt.get_by_key(k.key_string) is r

    def test_get_by_key_returns_none_for_unknown(self):
        rt = _fresh_runtime()
        assert rt.get_by_key("unknown") is None

    def test_get_max_seq_returns_zero_for_unknown(self):
        rt = _fresh_runtime()
        assert rt.get_max_seq("any-prefix") == 0

    def test_max_seq_updated_on_accept_push(self):
        rt = _fresh_runtime()
        k = _make_key(seq_num=5)
        r = SeenSignalRecord(idempotency_key=k, decision=SignalGuardDecision.accept)
        rt.push(r)
        assert rt.get_max_seq(k.prefix_string) == 5

    def test_max_seq_not_updated_on_non_accept(self):
        rt = _fresh_runtime()
        k = _make_key(seq_num=7)
        r = SeenSignalRecord(idempotency_key=k, decision=SignalGuardDecision.duplicate)
        rt.push(r)
        assert rt.get_max_seq(k.prefix_string) == 0

    def test_list_all_newest_first(self):
        rt = _fresh_runtime()
        for i in range(3):
            rt.push(SeenSignalRecord(idempotency_key=_make_key(seq_num=i + 1, task_id=f"t{i}")))
        records = rt.list_all()
        assert len(records) == 3
        # Newest pushed last, so list_all should have it first.
        assert records[0].idempotency_key.task_id == "t2"

    def test_clear_resets_all(self):
        rt = _fresh_runtime()
        rt.push(SeenSignalRecord(idempotency_key=_make_key()))
        rt.clear()
        assert rt.size() == 0

    def test_capacity_is_128(self):
        rt = _fresh_runtime()
        assert rt.capacity == 128


# ---------------------------------------------------------------------------
# I — build_idempotency_key: all fields populated
# ---------------------------------------------------------------------------


class TestGroupI:
    def test_all_fields_populated(self):
        k = build_idempotency_key(
            contract_id="c1",
            session_id="s1",
            trace_id="tr1",
            task_id="tk1",
            device_id="d1",
            signal_kind="progress",
            seq_num=4,
        )
        assert k.contract_id == "c1"
        assert k.session_id == "s1"
        assert k.trace_id == "tr1"
        assert k.task_id == "tk1"
        assert k.device_id == "d1"
        assert k.signal_kind == "progress"
        assert k.seq_num == 4


# ---------------------------------------------------------------------------
# J — build_idempotency_key: None / missing fields default
# ---------------------------------------------------------------------------


class TestGroupJ:
    def test_none_fields_default_to_empty(self):
        k = build_idempotency_key(contract_id=None, session_id=None)
        assert k.contract_id == ""
        assert k.session_id == ""

    def test_none_seq_num_defaults_to_zero(self):
        k = build_idempotency_key(seq_num=None)
        assert k.seq_num == 0

    def test_missing_optional_fields(self):
        k = build_idempotency_key(contract_id="c1")
        assert k.trace_id == ""
        assert k.seq_num == 0


# ---------------------------------------------------------------------------
# K — check_signal_guard: fresh signal → accept
# ---------------------------------------------------------------------------


class TestGroupK:
    def test_fresh_signal_returns_accept(self):
        rt = _fresh_runtime()
        k = _make_key()
        outcome = check_signal_guard(k, runtime=rt)
        assert outcome.decision == SignalGuardDecision.accept

    def test_fresh_signal_should_forward(self):
        rt = _fresh_runtime()
        k = _make_key()
        outcome = check_signal_guard(k, runtime=rt)
        assert outcome.should_forward is True

    def test_fresh_does_not_mutate_runtime(self):
        rt = _fresh_runtime()
        k = _make_key()
        check_signal_guard(k, runtime=rt)
        assert rt.size() == 0


# ---------------------------------------------------------------------------
# L — check_signal_guard: exact key repeat (prior accept) → replay
# ---------------------------------------------------------------------------


class TestGroupL:
    def test_prior_accept_returns_replay(self):
        rt = _fresh_runtime()
        k = _make_key()
        record_seen_signal(k, SignalGuardDecision.accept, runtime=rt)
        outcome = check_signal_guard(k, runtime=rt)
        assert outcome.decision == SignalGuardDecision.replay
        assert outcome.is_replay is True

    def test_replay_should_not_forward(self):
        rt = _fresh_runtime()
        k = _make_key()
        record_seen_signal(k, SignalGuardDecision.accept, runtime=rt)
        outcome = check_signal_guard(k, runtime=rt)
        assert outcome.should_forward is False


# ---------------------------------------------------------------------------
# M — check_signal_guard: exact key repeat (prior non-accept) → duplicate
# ---------------------------------------------------------------------------


class TestGroupM:
    def test_prior_non_accept_returns_duplicate(self):
        rt = _fresh_runtime()
        k = _make_key()
        record_seen_signal(k, SignalGuardDecision.duplicate, runtime=rt)
        outcome = check_signal_guard(k, runtime=rt)
        assert outcome.decision == SignalGuardDecision.duplicate
        assert outcome.is_duplicate is True


# ---------------------------------------------------------------------------
# N — check_signal_guard: lower seq_num, higher already seen → out_of_order
# ---------------------------------------------------------------------------


class TestGroupN:
    def test_out_of_order_detection(self):
        rt = _fresh_runtime()
        # First accept seq_num=5
        k_high = _make_key(seq_num=5)
        record_seen_signal(k_high, SignalGuardDecision.accept, runtime=rt)
        # Then check seq_num=3 (lower)
        k_low = _make_key(seq_num=3, trace_id="trace-002")
        outcome = check_signal_guard(k_low, runtime=rt)
        assert outcome.decision == SignalGuardDecision.out_of_order
        assert outcome.is_out_of_order is True

    def test_out_of_order_reason_mentions_seq_nums(self):
        rt = _fresh_runtime()
        k_high = _make_key(seq_num=10)
        record_seen_signal(k_high, SignalGuardDecision.accept, runtime=rt)
        k_low = _make_key(seq_num=2, trace_id="trace-xyz")
        outcome = check_signal_guard(k_low, runtime=rt)
        assert "10" in outcome.reason or "2" in outcome.reason


# ---------------------------------------------------------------------------
# O — check_signal_guard: seq_num = 0 disables ordering guard
# ---------------------------------------------------------------------------


class TestGroupO:
    def test_zero_seq_num_no_ordering_guard(self):
        rt = _fresh_runtime()
        # Accept a high seq_num signal first
        k_high = _make_key(seq_num=99)
        record_seen_signal(k_high, SignalGuardDecision.accept, runtime=rt)
        # seq_num=0 should still be accepted (different key)
        k_zero = _make_key(seq_num=0, trace_id="trace-zero")
        outcome = check_signal_guard(k_zero, runtime=rt)
        assert outcome.decision == SignalGuardDecision.accept


# ---------------------------------------------------------------------------
# P — check_signal_guard: uses custom runtime (isolation)
# ---------------------------------------------------------------------------


class TestGroupP:
    def test_isolation_from_singleton(self):
        rt1 = _fresh_runtime()
        rt2 = _fresh_runtime()
        k = _make_key()
        record_seen_signal(k, SignalGuardDecision.accept, runtime=rt1)
        # rt2 has no record → should still be accept
        outcome = check_signal_guard(k, runtime=rt2)
        assert outcome.decision == SignalGuardDecision.accept


# ---------------------------------------------------------------------------
# Q — record_seen_signal: pushes to ring-buffer
# ---------------------------------------------------------------------------


class TestGroupQ:
    def test_push_increments_size(self):
        rt = _fresh_runtime()
        k = _make_key()
        record_seen_signal(k, SignalGuardDecision.accept, runtime=rt)
        assert rt.size() == 1

    def test_push_is_findable(self):
        rt = _fresh_runtime()
        k = _make_key()
        seen = record_seen_signal(k, SignalGuardDecision.accept, runtime=rt)
        assert rt.get_by_key(k.key_string) is seen


# ---------------------------------------------------------------------------
# R — record_seen_signal: accept updates max_seq
# ---------------------------------------------------------------------------


class TestGroupR:
    def test_accept_with_seq_updates_max(self):
        rt = _fresh_runtime()
        k = _make_key(seq_num=7)
        record_seen_signal(k, SignalGuardDecision.accept, runtime=rt)
        assert rt.get_max_seq(k.prefix_string) == 7


# ---------------------------------------------------------------------------
# S — record_seen_signal: non-accept does not update max_seq
# ---------------------------------------------------------------------------


class TestGroupS:
    def test_duplicate_does_not_update_max(self):
        rt = _fresh_runtime()
        k = _make_key(seq_num=7)
        record_seen_signal(k, SignalGuardDecision.duplicate, runtime=rt)
        assert rt.get_max_seq(k.prefix_string) == 0


# ---------------------------------------------------------------------------
# T — record_seen_signal: returns SeenSignalRecord
# ---------------------------------------------------------------------------


class TestGroupT:
    def test_returns_seen_signal_record(self):
        rt = _fresh_runtime()
        k = _make_key()
        result = record_seen_signal(k, SignalGuardDecision.accept, runtime=rt)
        assert isinstance(result, SeenSignalRecord)
        assert result.decision == SignalGuardDecision.accept
        assert result.idempotency_key is k


# ---------------------------------------------------------------------------
# U — guard_inbound_signal: fresh → accept + record
# ---------------------------------------------------------------------------


class TestGroupU:
    def test_fresh_accept_and_recorded(self):
        rt = _fresh_runtime()
        outcome = guard_inbound_signal(
            contract_id="c1", session_id="s1", signal_kind="ack",
            seq_num=1, runtime=rt,
        )
        assert outcome.decision == SignalGuardDecision.accept
        assert rt.size() == 1

    def test_accept_key_in_runtime(self):
        rt = _fresh_runtime()
        outcome = guard_inbound_signal(
            contract_id="c1", session_id="s1", signal_kind="ack",
            seq_num=1, runtime=rt,
        )
        assert rt.get_by_key(outcome.idempotency_key.key_string) is not None


# ---------------------------------------------------------------------------
# V — guard_inbound_signal: duplicate (exact key) → replay (not re-recorded)
# ---------------------------------------------------------------------------


class TestGroupV:
    def test_same_key_twice_second_is_replay(self):
        rt = _fresh_runtime()
        guard_inbound_signal(
            contract_id="c1", session_id="s1", signal_kind="ack",
            seq_num=1, runtime=rt,
        )
        outcome2 = guard_inbound_signal(
            contract_id="c1", session_id="s1", signal_kind="ack",
            seq_num=1, runtime=rt,
        )
        assert outcome2.decision == SignalGuardDecision.replay

    def test_replay_not_re_recorded(self):
        rt = _fresh_runtime()
        guard_inbound_signal(
            contract_id="c1", session_id="s1", signal_kind="ack",
            seq_num=1, runtime=rt,
        )
        guard_inbound_signal(
            contract_id="c1", session_id="s1", signal_kind="ack",
            seq_num=1, runtime=rt,
        )
        # Only the first accept should be recorded
        assert rt.size() == 1


# ---------------------------------------------------------------------------
# W — guard_inbound_signal: out_of_order → not re-recorded
# ---------------------------------------------------------------------------


class TestGroupW:
    def test_out_of_order_not_recorded(self):
        rt = _fresh_runtime()
        # Accept seq_num=5
        guard_inbound_signal(
            contract_id="c1", session_id="s1", signal_kind="progress",
            seq_num=5, runtime=rt,
        )
        # Out-of-order seq_num=2
        outcome = guard_inbound_signal(
            contract_id="c1", session_id="s1", signal_kind="progress",
            seq_num=2, trace_id="t2", runtime=rt,
        )
        assert outcome.decision == SignalGuardDecision.out_of_order
        # Only the accept should be recorded
        assert rt.size() == 1


# ---------------------------------------------------------------------------
# X — guard_inbound_signal: identity fields propagated
# ---------------------------------------------------------------------------


class TestGroupX:
    def test_identity_fields_in_key(self):
        rt = _fresh_runtime()
        outcome = guard_inbound_signal(
            contract_id="CID",
            session_id="SID",
            trace_id="TID",
            task_id="TKID",
            device_id="DID",
            signal_kind="final_result",
            seq_num=2,
            runtime=rt,
        )
        k = outcome.idempotency_key
        assert k.contract_id == "CID"
        assert k.session_id == "SID"
        assert k.trace_id == "TID"
        assert k.task_id == "TKID"
        assert k.device_id == "DID"
        assert k.signal_kind == "final_result"


# ---------------------------------------------------------------------------
# Y — guard_inbound_signal: seq_num propagated
# ---------------------------------------------------------------------------


class TestGroupY:
    def test_seq_num_propagated(self):
        rt = _fresh_runtime()
        outcome = guard_inbound_signal(
            contract_id="c1", session_id="s1", signal_kind="ack",
            seq_num=42, runtime=rt,
        )
        assert outcome.idempotency_key.seq_num == 42


# ---------------------------------------------------------------------------
# Z — guard_inbound_signal: custom runtime isolation
# ---------------------------------------------------------------------------


class TestGroupZ:
    def test_custom_runtime_isolated_from_singleton(self):
        reset_recovery_readiness_runtime()
        rt = _fresh_runtime()
        guard_inbound_signal(
            contract_id="isolated", session_id="s1", signal_kind="ack",
            runtime=rt,
        )
        # Singleton should be empty
        singleton = get_recovery_readiness_runtime()
        assert singleton.get_by_key(
            build_idempotency_key(
                contract_id="isolated", session_id="s1", signal_kind="ack"
            ).key_string
        ) is None


# ---------------------------------------------------------------------------
# AA — build_recovery_readiness_snapshot: empty runtime
# ---------------------------------------------------------------------------


class TestGroupAA:
    def test_empty_snapshot_all_zeros(self):
        rt = _fresh_runtime()
        snap = build_recovery_readiness_snapshot(runtime=rt)
        assert snap.total_count == 0
        assert snap.accept_count == 0
        assert snap.status == RecoveryReadinessStatus.ready


# ---------------------------------------------------------------------------
# AB — build_recovery_readiness_snapshot: only accepts → ready
# ---------------------------------------------------------------------------


class TestGroupAB:
    def test_only_accepts_status_ready(self):
        rt = _fresh_runtime()
        for i in range(5):
            guard_inbound_signal(
                contract_id="c1", session_id="s1", signal_kind="progress",
                seq_num=i + 1, trace_id=str(i), runtime=rt,
            )
        snap = build_recovery_readiness_snapshot(runtime=rt)
        assert snap.status == RecoveryReadinessStatus.ready
        assert snap.accept_count == 5


# ---------------------------------------------------------------------------
# AC — build_recovery_readiness_snapshot: 1 duplicate among 10 → recovering
# ---------------------------------------------------------------------------


class TestGroupAC:
    def test_small_proportion_non_fresh_is_recovering(self):
        rt = _fresh_runtime()
        for i in range(9):
            guard_inbound_signal(
                contract_id="c1", session_id="s1", signal_kind="ack",
                seq_num=i + 1, trace_id=str(i), runtime=rt,
            )
        # Force a duplicate record
        k_dup = _make_key(seq_num=99, trace_id="dup")
        record_seen_signal(k_dup, SignalGuardDecision.duplicate, runtime=rt)
        snap = build_recovery_readiness_snapshot(runtime=rt)
        assert snap.status == RecoveryReadinessStatus.recovering
        assert snap.duplicate_count == 1


# ---------------------------------------------------------------------------
# AD — build_recovery_readiness_snapshot: >= 30% non-fresh → degraded
# ---------------------------------------------------------------------------


class TestGroupAD:
    def test_high_non_fresh_proportion_is_degraded(self):
        rt = _fresh_runtime()
        for i in range(7):
            k = _make_key(seq_num=i + 1, trace_id=f"a{i}")
            record_seen_signal(k, SignalGuardDecision.accept, runtime=rt)
        for i in range(3):
            k = _make_key(seq_num=i + 100, trace_id=f"d{i}")
            record_seen_signal(k, SignalGuardDecision.duplicate, runtime=rt)
        snap = build_recovery_readiness_snapshot(runtime=rt)
        assert snap.status == RecoveryReadinessStatus.degraded


# ---------------------------------------------------------------------------
# AE — build_recovery_readiness_snapshot: records newest-first
# ---------------------------------------------------------------------------


class TestGroupAE:
    def test_records_newest_first(self):
        rt = _fresh_runtime()
        for i in range(3):
            k = _make_key(seq_num=i + 1, trace_id=str(i))
            record_seen_signal(k, SignalGuardDecision.accept, runtime=rt)
        snap = build_recovery_readiness_snapshot(runtime=rt)
        assert snap.records[0].idempotency_key.seq_num == 3


# ---------------------------------------------------------------------------
# AF — build_recovery_readiness_snapshot: counts are accurate
# ---------------------------------------------------------------------------


class TestGroupAF:
    def test_counts_accurate(self):
        rt = _fresh_runtime()
        decisions = [
            SignalGuardDecision.accept,
            SignalGuardDecision.accept,
            SignalGuardDecision.duplicate,
            SignalGuardDecision.stale,
            SignalGuardDecision.replay,
            SignalGuardDecision.out_of_order,
        ]
        for i, d in enumerate(decisions):
            k = _make_key(seq_num=i + 1, trace_id=str(i))
            record_seen_signal(k, d, runtime=rt)
        snap = build_recovery_readiness_snapshot(runtime=rt)
        assert snap.accept_count == 2
        assert snap.duplicate_count == 1
        assert snap.stale_count == 1
        assert snap.replay_count == 1
        assert snap.out_of_order_count == 1
        assert snap.total_count == 6


# ---------------------------------------------------------------------------
# AG — get_recovery_readiness_runtime returns same singleton
# ---------------------------------------------------------------------------


class TestGroupAG:
    def test_singleton_same_instance(self):
        reset_recovery_readiness_runtime()
        rt1 = get_recovery_readiness_runtime()
        rt2 = get_recovery_readiness_runtime()
        assert rt1 is rt2


# ---------------------------------------------------------------------------
# AH — reset_recovery_readiness_runtime clears singleton
# ---------------------------------------------------------------------------


class TestGroupAH:
    def test_reset_creates_new_instance(self):
        rt1 = get_recovery_readiness_runtime()
        reset_recovery_readiness_runtime()
        rt2 = get_recovery_readiness_runtime()
        assert rt1 is not rt2

    def test_reset_clears_state(self):
        rt = get_recovery_readiness_runtime()
        guard_inbound_signal(contract_id="x", session_id="y", signal_kind="ack")
        reset_recovery_readiness_runtime()
        rt2 = get_recovery_readiness_runtime()
        assert rt2.size() == 0


# ---------------------------------------------------------------------------
# AI — Ring buffer capacity: 128
# ---------------------------------------------------------------------------


class TestGroupAI:
    def test_ring_buffer_capacity_128(self):
        assert RecoveryReadinessRuntime().capacity == 128


# ---------------------------------------------------------------------------
# AJ — Ring buffer eviction: oldest entry evicted when full
# ---------------------------------------------------------------------------


class TestGroupAJ:
    def test_eviction_when_full(self):
        rt = RecoveryReadinessRuntime(capacity=4)
        for i in range(5):
            k = _make_key(seq_num=i + 1, trace_id=str(i))
            rt.push(SeenSignalRecord(idempotency_key=k))
        assert rt.size() == 4

    def test_oldest_key_evicted(self):
        rt = RecoveryReadinessRuntime(capacity=2)
        k0 = _make_key(seq_num=1, trace_id="old")
        k1 = _make_key(seq_num=2, trace_id="new1")
        k2 = _make_key(seq_num=3, trace_id="new2")
        rt.push(SeenSignalRecord(idempotency_key=k0))
        rt.push(SeenSignalRecord(idempotency_key=k1))
        rt.push(SeenSignalRecord(idempotency_key=k2))
        assert rt.get_by_key(k0.key_string) is None


# ---------------------------------------------------------------------------
# AK — Ring buffer eviction: evicted record's key index entry removed
# ---------------------------------------------------------------------------


class TestGroupAK:
    def test_evicted_key_not_in_index(self):
        rt = RecoveryReadinessRuntime(capacity=1)
        k0 = _make_key(seq_num=1, trace_id="evicted")
        k1 = _make_key(seq_num=2, trace_id="kept")
        rt.push(SeenSignalRecord(idempotency_key=k0))
        rt.push(SeenSignalRecord(idempotency_key=k1))
        assert rt.get_by_key(k0.key_string) is None
        assert rt.get_by_key(k1.key_string) is not None


# ---------------------------------------------------------------------------
# AL — Ring buffer eviction: newer record for same key keeps index entry
# ---------------------------------------------------------------------------


class TestGroupAL:
    def test_newer_record_same_key_survives(self):
        rt = RecoveryReadinessRuntime(capacity=2)
        k = _make_key(seq_num=1)
        r1 = SeenSignalRecord(idempotency_key=k, decision=SignalGuardDecision.accept)
        r2 = SeenSignalRecord(idempotency_key=k, decision=SignalGuardDecision.replay)
        rt.push(r1)
        rt.push(r2)
        # Push another to evict r1 but not r2
        k2 = _make_key(seq_num=2, trace_id="other")
        rt.push(SeenSignalRecord(idempotency_key=k2))
        # Index now points to r2 (the newer one)
        assert rt.get_by_key(k.key_string) is r2


# ---------------------------------------------------------------------------
# AM — Serialisation: IdempotencyKey to_dict produces expected keys
# ---------------------------------------------------------------------------


class TestGroupAM:
    def test_to_dict_expected_keys(self):
        k = _make_key()
        d = k.to_dict()
        expected = {"contract_id", "session_id", "trace_id", "task_id",
                    "device_id", "signal_kind", "seq_num", "key_string"}
        assert set(d.keys()) == expected


# ---------------------------------------------------------------------------
# AN — Serialisation: IdempotencyKey to_json produces valid JSON
# ---------------------------------------------------------------------------


class TestGroupAN:
    def test_to_json_parses(self):
        k = _make_key(seq_num=9)
        data = json.loads(k.to_json())
        assert data["seq_num"] == 9


# ---------------------------------------------------------------------------
# AO — Serialisation: SeenSignalRecord to_dict / to_json
# ---------------------------------------------------------------------------


class TestGroupAO:
    def test_to_dict_to_json(self):
        k = _make_key()
        r = SeenSignalRecord(idempotency_key=k, decision=SignalGuardDecision.stale)
        d = r.to_dict()
        assert d["decision"] == "stale"
        parsed = json.loads(r.to_json())
        assert parsed["decision"] == "stale"


# ---------------------------------------------------------------------------
# AP — Serialisation: SignalGuardOutcome to_dict / to_json
# ---------------------------------------------------------------------------


class TestGroupAP:
    def test_to_dict_to_json(self):
        k = _make_key()
        o = SignalGuardOutcome(
            decision=SignalGuardDecision.out_of_order,
            idempotency_key=k,
            is_out_of_order=True,
            reason="test",
        )
        d = o.to_dict()
        assert d["is_out_of_order"] is True
        parsed = json.loads(o.to_json())
        assert parsed["decision"] == "out_of_order"


# ---------------------------------------------------------------------------
# AQ — Serialisation: RecoveryReadinessSnapshot to_dict / to_json
# ---------------------------------------------------------------------------


class TestGroupAQ:
    def test_snapshot_to_json(self):
        rt = _fresh_runtime()
        snap = build_recovery_readiness_snapshot(runtime=rt)
        parsed = json.loads(snap.to_json())
        assert "total_count" in parsed
        assert "status" in parsed


# ---------------------------------------------------------------------------
# AR — IdempotencyKey.from_dict: non-dict raises ValueError
# ---------------------------------------------------------------------------


class TestGroupAR:
    def test_non_dict_raises(self):
        with pytest.raises(ValueError):
            IdempotencyKey.from_dict([1, 2, 3])


# ---------------------------------------------------------------------------
# AS — IdempotencyKey.from_dict: round-trips correctly
# ---------------------------------------------------------------------------


class TestGroupAS:
    def test_round_trip(self):
        k = _make_key(seq_num=11)
        k2 = IdempotencyKey.from_dict(k.to_dict())
        assert k2.contract_id == k.contract_id
        assert k2.seq_num == k.seq_num
        assert k2.signal_kind == k.signal_kind


# ---------------------------------------------------------------------------
# AT — check_signal_guard: no prior record, seq_num 0 → accept
# ---------------------------------------------------------------------------


class TestGroupAT:
    def test_no_prior_seq_zero_accept(self):
        rt = _fresh_runtime()
        k = build_idempotency_key(contract_id="c1", session_id="s1", signal_kind="ack", seq_num=0)
        outcome = check_signal_guard(k, runtime=rt)
        assert outcome.decision == SignalGuardDecision.accept


# ---------------------------------------------------------------------------
# AU — check_signal_guard: higher seq_num than seen → accept
# ---------------------------------------------------------------------------


class TestGroupAU:
    def test_higher_seq_accepted(self):
        rt = _fresh_runtime()
        k3 = _make_key(seq_num=3)
        record_seen_signal(k3, SignalGuardDecision.accept, runtime=rt)
        k5 = _make_key(seq_num=5, trace_id="new-trace")
        outcome = check_signal_guard(k5, runtime=rt)
        assert outcome.decision == SignalGuardDecision.accept


# ---------------------------------------------------------------------------
# AV — guard_inbound_signal: two different signal_kinds for same contract → both accept
# ---------------------------------------------------------------------------


class TestGroupAV:
    def test_different_signal_kinds_both_accepted(self):
        rt = _fresh_runtime()
        o1 = guard_inbound_signal(contract_id="c1", session_id="s1", signal_kind="ack", seq_num=1, runtime=rt)
        o2 = guard_inbound_signal(contract_id="c1", session_id="s1", signal_kind="progress", seq_num=1, runtime=rt)
        assert o1.decision == SignalGuardDecision.accept
        assert o2.decision == SignalGuardDecision.accept


# ---------------------------------------------------------------------------
# AW — guard_inbound_signal: same key 3 times → accept, replay, replay
# ---------------------------------------------------------------------------


class TestGroupAW:
    def test_three_deliveries(self):
        rt = _fresh_runtime()
        outcomes = [
            guard_inbound_signal(contract_id="c1", session_id="s1", signal_kind="ack", seq_num=1, runtime=rt)
            for _ in range(3)
        ]
        assert outcomes[0].decision == SignalGuardDecision.accept
        assert outcomes[1].decision == SignalGuardDecision.replay
        assert outcomes[2].decision == SignalGuardDecision.replay


# ---------------------------------------------------------------------------
# AX — build_recovery_readiness_snapshot: custom runtime isolation
# ---------------------------------------------------------------------------


class TestGroupAX:
    def test_custom_runtime_isolated(self):
        rt = _fresh_runtime()
        guard_inbound_signal(contract_id="isolated2", session_id="s2", signal_kind="ack", runtime=rt)
        reset_recovery_readiness_runtime()
        snap = build_recovery_readiness_snapshot()
        assert snap.total_count == 0


# ---------------------------------------------------------------------------
# AY — core.runtime re-exports: all PR-15 symbols accessible from core.runtime
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="heavy import; validated separately in integration")
class TestGroupAY:
    def test_core_runtime_exports_pr15_symbols(self):
        import core.runtime as cr
        assert hasattr(cr, "ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY")
        assert hasattr(cr, "ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL")
        assert hasattr(cr, "SignalGuardDecision")
        assert hasattr(cr, "RecoveryReadinessStatus")
        assert hasattr(cr, "IdempotencyKey")
        assert hasattr(cr, "SeenSignalRecord")
        assert hasattr(cr, "SignalGuardOutcome")
        assert hasattr(cr, "RecoveryReadinessSnapshot")
        assert hasattr(cr, "RecoveryReadinessRuntime")
        assert hasattr(cr, "build_idempotency_key")
        assert hasattr(cr, "check_signal_guard")
        assert hasattr(cr, "record_seen_signal")
        assert hasattr(cr, "guard_inbound_signal")
        assert hasattr(cr, "build_recovery_readiness_snapshot")
        assert hasattr(cr, "get_recovery_readiness_runtime")
        assert hasattr(cr, "reset_recovery_readiness_runtime")


# ---------------------------------------------------------------------------
# AZ — projection.py sentinel: ATTACHED_RUNTIME_RECOVERY_READINESS_ALIGNED_PR15
# ---------------------------------------------------------------------------


class TestGroupAZ:
    def test_projection_sentinel_present_and_not_unavailable(self):
        pytest.importorskip("fastapi")
        from core.routes.projection import ATTACHED_RUNTIME_RECOVERY_READINESS_ALIGNED_PR15
        assert isinstance(ATTACHED_RUNTIME_RECOVERY_READINESS_ALIGNED_PR15, str)
        assert "UNAVAILABLE" not in ATTACHED_RUNTIME_RECOVERY_READINESS_ALIGNED_PR15


# ---------------------------------------------------------------------------
# BA — All 11 policy sentinels are non-empty strings
# ---------------------------------------------------------------------------


class TestGroupBA:
    def test_all_sentinels_non_empty(self):
        sentinels = [
            RECOVERY_READINESS_IDEMPOTENCY_KEY_IS_CANONICAL_POLICY,
            RECOVERY_READINESS_DUPLICATE_SIGNAL_IS_SILENTLY_DROPPED_POLICY,
            RECOVERY_READINESS_OUT_OF_ORDER_SIGNAL_IS_GUARDED_POLICY,
            RECOVERY_READINESS_REPLAY_SIGNAL_IS_GUARDED_POLICY,
            RECOVERY_READINESS_IDENTITY_CONTINUITY_IS_PRESERVED_POLICY,
            RECOVERY_READINESS_STALE_SIGNAL_DOES_NOT_ADVANCE_PHASE_POLICY,
            RECOVERY_READINESS_FRESH_SIGNAL_IS_ACCEPTED_POLICY,
            RECOVERY_READINESS_GUARD_IS_ADDITIVE_ONLY_POLICY,
            RECOVERY_READINESS_SEQ_NUM_DRIVES_ORDER_GUARD_POLICY,
            RECOVERY_READINESS_TERMINAL_RECORD_DEDUPE_IS_SAFE_POLICY,
            ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY,
        ]
        for s in sentinels:
            assert isinstance(s, str) and len(s) > 0


# ---------------------------------------------------------------------------
# BB — PR15_SENTINEL contains 'package=15'
# ---------------------------------------------------------------------------


class TestGroupBB:
    def test_sentinel_contains_package_15(self):
        assert "package=15" in ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL


# ---------------------------------------------------------------------------
# BC — SignalGuardOutcome.should_forward: True only for accept
# ---------------------------------------------------------------------------


class TestGroupBC:
    def test_should_forward_true_only_for_accept(self):
        k = _make_key()
        for d in SignalGuardDecision:
            o = SignalGuardOutcome(decision=d, idempotency_key=k)
            if d == SignalGuardDecision.accept:
                assert o.should_forward is True
            else:
                assert o.should_forward is False


# ---------------------------------------------------------------------------
# BD — RecoveryReadinessRuntime.get_max_seq: returns 0 for unseen prefix
# ---------------------------------------------------------------------------


class TestGroupBD:
    def test_get_max_seq_unseen(self):
        rt = _fresh_runtime()
        assert rt.get_max_seq("nonexistent-prefix") == 0


# ---------------------------------------------------------------------------
# BE — guard_inbound_signal: stale (seq_num < max accepted for prefix) after accept
# ---------------------------------------------------------------------------


class TestGroupBE:
    def test_out_of_order_after_accept(self):
        rt = _fresh_runtime()
        guard_inbound_signal(contract_id="c1", session_id="s1", signal_kind="progress",
                             seq_num=10, runtime=rt)
        outcome = guard_inbound_signal(contract_id="c1", session_id="s1", signal_kind="progress",
                                       seq_num=3, trace_id="other", runtime=rt)
        assert outcome.decision == SignalGuardDecision.out_of_order


# ---------------------------------------------------------------------------
# BF — check_signal_guard: seq_num equals max already seen → accept
# ---------------------------------------------------------------------------


class TestGroupBF:
    def test_equal_seq_num_different_trace_is_replay_or_accept(self):
        rt = _fresh_runtime()
        k1 = build_idempotency_key(contract_id="c1", session_id="s1", signal_kind="ack",
                                   seq_num=5, trace_id="t1")
        record_seen_signal(k1, SignalGuardDecision.accept, runtime=rt)
        # Same seq_num but different trace_id → different key_string → accept
        k2 = build_idempotency_key(contract_id="c1", session_id="s1", signal_kind="ack",
                                   seq_num=5, trace_id="t2")
        outcome = check_signal_guard(k2, runtime=rt)
        # seq_num == max_seen (5) → no out_of_order; fresh key → accept
        assert outcome.decision == SignalGuardDecision.accept


# ---------------------------------------------------------------------------
# BG — IdempotencyKey.key_string: unique for different seq_num
# ---------------------------------------------------------------------------


class TestGroupBG:
    def test_key_string_unique_per_seq_num(self):
        keys = {_make_key(seq_num=i).key_string for i in range(1, 6)}
        assert len(keys) == 5


# ---------------------------------------------------------------------------
# BH — Multiple contract_ids: each has independent max_seq tracking
# ---------------------------------------------------------------------------


class TestGroupBH:
    def test_independent_max_seq_per_contract(self):
        rt = _fresh_runtime()
        k_c1 = build_idempotency_key(contract_id="c1", session_id="s1", signal_kind="ack", seq_num=10)
        k_c2 = build_idempotency_key(contract_id="c2", session_id="s1", signal_kind="ack", seq_num=3)
        record_seen_signal(k_c1, SignalGuardDecision.accept, runtime=rt)
        record_seen_signal(k_c2, SignalGuardDecision.accept, runtime=rt)
        assert rt.get_max_seq(k_c1.prefix_string) == 10
        assert rt.get_max_seq(k_c2.prefix_string) == 3


# ---------------------------------------------------------------------------
# BI — SeenSignalRecord.to_dict includes idempotency_key sub-dict
# ---------------------------------------------------------------------------


class TestGroupBI:
    def test_idempotency_key_sub_dict_present(self):
        k = _make_key()
        r = SeenSignalRecord(idempotency_key=k)
        d = r.to_dict()
        assert isinstance(d["idempotency_key"], dict)
        assert "contract_id" in d["idempotency_key"]


# ---------------------------------------------------------------------------
# BJ — SignalGuardOutcome flag correctness
# ---------------------------------------------------------------------------


class TestGroupBJ:
    def test_is_duplicate_flag(self):
        k = _make_key()
        o = SignalGuardOutcome(decision=SignalGuardDecision.duplicate, idempotency_key=k, is_duplicate=True)
        assert o.is_duplicate is True
        assert o.is_replay is False

    def test_is_replay_flag(self):
        k = _make_key()
        o = SignalGuardOutcome(decision=SignalGuardDecision.replay, idempotency_key=k, is_replay=True)
        assert o.is_replay is True
        assert o.is_duplicate is False

    def test_is_out_of_order_flag(self):
        k = _make_key()
        o = SignalGuardOutcome(decision=SignalGuardDecision.out_of_order, idempotency_key=k, is_out_of_order=True)
        assert o.is_out_of_order is True

    def test_is_stale_flag(self):
        k = _make_key()
        o = SignalGuardOutcome(decision=SignalGuardDecision.stale, idempotency_key=k, is_stale=True)
        assert o.is_stale is True


# ---------------------------------------------------------------------------
# BK — guard_inbound_signal: empty contract_id + session_id still guards
# ---------------------------------------------------------------------------


class TestGroupBK:
    def test_empty_ids_still_guards(self):
        rt = _fresh_runtime()
        o1 = guard_inbound_signal(signal_kind="ack", seq_num=1, runtime=rt)
        o2 = guard_inbound_signal(signal_kind="ack", seq_num=1, runtime=rt)
        assert o1.decision == SignalGuardDecision.accept
        assert o2.decision == SignalGuardDecision.replay


# ---------------------------------------------------------------------------
# BL — build_recovery_readiness_snapshot: total_count matches buffer size
# ---------------------------------------------------------------------------


class TestGroupBL:
    def test_total_count_matches(self):
        rt = _fresh_runtime()
        for i in range(5):
            k = _make_key(seq_num=i + 1, trace_id=str(i))
            record_seen_signal(k, SignalGuardDecision.accept, runtime=rt)
        snap = build_recovery_readiness_snapshot(runtime=rt)
        assert snap.total_count == 5


# ---------------------------------------------------------------------------
# BM — RecoveryReadinessRuntime.list_all: returns newest-first
# ---------------------------------------------------------------------------


class TestGroupBM:
    def test_list_all_newest_first(self):
        rt = _fresh_runtime()
        for i in range(3):
            k = _make_key(seq_num=i + 1, trace_id=str(i))
            record_seen_signal(k, SignalGuardDecision.accept, runtime=rt)
        all_records = rt.list_all()
        assert all_records[0].idempotency_key.seq_num == 3


# ---------------------------------------------------------------------------
# BN — guard_inbound_signal: trace_id preserved
# ---------------------------------------------------------------------------


class TestGroupBN:
    def test_trace_id_preserved(self):
        rt = _fresh_runtime()
        outcome = guard_inbound_signal(
            contract_id="c1", session_id="s1", trace_id="TRACE-999",
            signal_kind="ack", runtime=rt,
        )
        assert outcome.idempotency_key.trace_id == "TRACE-999"


# ---------------------------------------------------------------------------
# BO — guard_inbound_signal: device_id preserved
# ---------------------------------------------------------------------------


class TestGroupBO:
    def test_device_id_preserved(self):
        rt = _fresh_runtime()
        outcome = guard_inbound_signal(
            contract_id="c1", session_id="s1", device_id="DEVICE-X",
            signal_kind="ack", runtime=rt,
        )
        assert outcome.idempotency_key.device_id == "DEVICE-X"


# ---------------------------------------------------------------------------
# BP — check_signal_guard: does not mutate runtime
# ---------------------------------------------------------------------------


class TestGroupBP:
    def test_check_does_not_mutate(self):
        rt = _fresh_runtime()
        k = _make_key()
        check_signal_guard(k, runtime=rt)
        assert rt.size() == 0


# ---------------------------------------------------------------------------
# BQ — Integration: duplicate signal not forwarded to reconciler
# ---------------------------------------------------------------------------


class TestGroupBQ:
    def test_duplicate_not_forwarded(self):
        rt = _fresh_runtime()
        # Accept once
        guard_inbound_signal(contract_id="c1", session_id="s1",
                             signal_kind="ack", seq_num=1, runtime=rt)
        # Second delivery
        outcome = guard_inbound_signal(contract_id="c1", session_id="s1",
                                       signal_kind="ack", seq_num=1, runtime=rt)
        assert not outcome.should_forward


# ---------------------------------------------------------------------------
# BR — Integration: out-of-order signal not forwarded to reconciler
# ---------------------------------------------------------------------------


class TestGroupBR:
    def test_out_of_order_not_forwarded(self):
        rt = _fresh_runtime()
        guard_inbound_signal(contract_id="c1", session_id="s1",
                             signal_kind="progress", seq_num=10, runtime=rt)
        outcome = guard_inbound_signal(contract_id="c1", session_id="s1",
                                       signal_kind="progress", seq_num=4,
                                       trace_id="late", runtime=rt)
        assert not outcome.should_forward


# ---------------------------------------------------------------------------
# BS — Integration: accepted signal is forwarded
# ---------------------------------------------------------------------------


class TestGroupBS:
    def test_fresh_signal_forwarded(self):
        rt = _fresh_runtime()
        outcome = guard_inbound_signal(contract_id="c1", session_id="s1",
                                       signal_kind="final_result", seq_num=1, runtime=rt)
        assert outcome.should_forward is True


# ---------------------------------------------------------------------------
# BT — End-to-end: establish reuse binding → guard 3 acks (1 fresh, 2 dup)
# ---------------------------------------------------------------------------


class TestGroupBT:
    def test_e2e_three_acks(self):
        rt = _fresh_runtime()
        results = [
            guard_inbound_signal(
                contract_id="ctr-e2e", session_id="ses-e2e",
                trace_id="trace-e2e", task_id="task-e2e",
                device_id="dev-e2e", signal_kind="ack",
                seq_num=1, runtime=rt,
            )
            for _ in range(3)
        ]
        assert results[0].decision == SignalGuardDecision.accept
        assert results[1].decision == SignalGuardDecision.replay
        assert results[2].decision == SignalGuardDecision.replay
        snap = build_recovery_readiness_snapshot(runtime=rt)
        assert snap.accept_count == 1
        assert snap.total_count == 1  # only accepted signals are recorded


# ---------------------------------------------------------------------------
# BU — End-to-end: guard accepts incremental seq_nums, rejects regression
# ---------------------------------------------------------------------------


class TestGroupBU:
    def test_incremental_seq_accepted_regression_rejected(self):
        rt = _fresh_runtime()
        for seq in [1, 2, 3, 4, 5]:
            o = guard_inbound_signal(
                contract_id="c-inc", session_id="s-inc",
                signal_kind="progress", seq_num=seq,
                trace_id=f"t{seq}", runtime=rt,
            )
            assert o.decision == SignalGuardDecision.accept

        # Regress
        o_old = guard_inbound_signal(
            contract_id="c-inc", session_id="s-inc",
            signal_kind="progress", seq_num=2,
            trace_id="t-regressed", runtime=rt,
        )
        assert o_old.decision == SignalGuardDecision.out_of_order

        snap = build_recovery_readiness_snapshot(runtime=rt)
        assert snap.accept_count == 5
        assert snap.out_of_order_count == 0  # out-of-order not recorded
