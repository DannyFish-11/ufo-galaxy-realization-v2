#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5_offline_durability_closure.py
=============================================
PR-5: OfflineQueueRecoveryBoundary — Bounded-Authority Offline Queue Replay
Ordering — test suite.

Coverage
--------
A  — Module importable; authority sentinel and PR-5 sentinel present.
B  — All 5 policy sentinels are non-empty strings with expected keywords.
C  — OfflineQueueDisposition enum has all 5 required values.
D  — OfflineQueueEntry dataclass has required fields; to_dict() works.
E  — OfflineQueueEntry.from_dict() round-trips correctly.
F  — OfflineQueueEntry to_json() returns valid JSON.
G  — OfflineQueueEntry: entry_id is auto-generated and unique.
H  — OfflineQueueEntryRecord dataclass has required fields; to_dict() works.
I  — OfflineQueueEntryRecord.from_dict() round-trips correctly.
J  — OfflineQueueEntryRecord to_json() returns valid JSON.
K  — OfflineQueueBoundarySnapshot has required fields; to_dict() works.
L  — OfflineQueueBoundarySnapshot to_json() returns valid JSON.
M  — OfflineQueueRecoveryBoundary instantiates with default capacity.
N  — replay_ordered: empty list → yields nothing, no exception.
O  — replay_ordered: single entry with valid key → accepted and yielded.
P  — replay_ordered: entries sorted by sequence (not insertion order).
Q  — replay_ordered: duplicate idempotency_key → first accepted, second rejected.
R  — replay_ordered: three entries with unique keys → all three accepted in order.
S  — replay_ordered: canonical_is_terminal=True → all entries rejected as stale_terminal.
T  — replay_ordered: empty idempotency_key → rejected_out_of_authority.
U  — replay_ordered: mix of valid, duplicate, empty key, terminal → correct disposition each.
V  — replay_ordered: deduplication is first-wins across all entries regardless of sequence.
W  — replay_ordered: terminal guard applies before sequence sort.
X  — build_snapshot: total_entries_processed reflects all processed entries.
Y  — build_snapshot: total_accepted matches accepted count.
Z  — build_snapshot: total_rejected_duplicate matches duplicate count.
AA — build_snapshot: total_rejected_stale_terminal matches terminal count.
AB — build_snapshot: total_rejected_out_of_authority matches authority count.
AC — build_snapshot: recent_records contains processed records.
AD — list_recent: returns newest-first up to n items.
AE — get_offline_queue_recovery_boundary returns singleton.
AF — reset_offline_queue_recovery_boundary resets singleton.
AG — OfflineQueueDisposition.from_string: known value → member.
AH — OfflineQueueDisposition.from_string: unknown value → held_for_review.
AI — replay_ordered: large batch with interleaved duplicates and out-of-order sequences.
AJ — replay_ordered: sequence numbers need not be contiguous.
AK — Two replay batches on the same boundary: dedup state is per-batch (not global).
AL — replay_ordered: record_id is unique per OfflineQueueEntryRecord.
AM — OfflineQueueBoundarySnapshot pr5_sentinel contains 'PR-5'.
"""

from __future__ import annotations

import json
import uuid
from typing import List

import pytest


# ---------------------------------------------------------------------------
# A — Module importable; sentinels present
# ---------------------------------------------------------------------------


class TestModuleSentinels:
    def test_module_is_importable(self):
        import core.offline_durability_closure  # noqa: F401

    def test_authority_sentinel_is_non_empty_string(self):
        from core.offline_durability_closure import (
            OFFLINE_DURABILITY_CLOSURE_AUTHORITY,
        )
        assert isinstance(OFFLINE_DURABILITY_CLOSURE_AUTHORITY, str)
        assert len(OFFLINE_DURABILITY_CLOSURE_AUTHORITY) > 0
        assert "OfflineQueueRecoveryBoundary" in OFFLINE_DURABILITY_CLOSURE_AUTHORITY
        assert "PR-5" in OFFLINE_DURABILITY_CLOSURE_AUTHORITY

    def test_pr5_sentinel_is_non_empty_string(self):
        from core.offline_durability_closure import (
            OFFLINE_DURABILITY_CLOSURE_PR5_SENTINEL,
        )
        assert isinstance(OFFLINE_DURABILITY_CLOSURE_PR5_SENTINEL, str)
        assert "PR-5" in OFFLINE_DURABILITY_CLOSURE_PR5_SENTINEL
        assert "package=5" in OFFLINE_DURABILITY_CLOSURE_PR5_SENTINEL


# ---------------------------------------------------------------------------
# B — All 5 policy sentinels are non-empty strings with expected keywords
# ---------------------------------------------------------------------------


class TestPolicySentinels:
    def test_sequence_order_policy(self):
        from core.offline_durability_closure import (
            OFFLINE_QUEUE_SEQUENCE_ORDER_IS_CANONICAL_POLICY,
        )
        assert isinstance(OFFLINE_QUEUE_SEQUENCE_ORDER_IS_CANONICAL_POLICY, str)
        assert "sequence" in OFFLINE_QUEUE_SEQUENCE_ORDER_IS_CANONICAL_POLICY.lower()

    def test_idempotency_key_dedup_policy(self):
        from core.offline_durability_closure import (
            OFFLINE_QUEUE_IDEMPOTENCY_KEY_DEDUP_IS_FIRST_WINS_POLICY,
        )
        assert isinstance(OFFLINE_QUEUE_IDEMPOTENCY_KEY_DEDUP_IS_FIRST_WINS_POLICY, str)
        assert "idempotency" in OFFLINE_QUEUE_IDEMPOTENCY_KEY_DEDUP_IS_FIRST_WINS_POLICY.lower()
        assert "first" in OFFLINE_QUEUE_IDEMPOTENCY_KEY_DEDUP_IS_FIRST_WINS_POLICY.lower()

    def test_terminal_state_policy(self):
        from core.offline_durability_closure import (
            OFFLINE_QUEUE_TERMINAL_STATE_REJECTS_ALL_ENTRIES_POLICY,
        )
        assert isinstance(OFFLINE_QUEUE_TERMINAL_STATE_REJECTS_ALL_ENTRIES_POLICY, str)
        assert "terminal" in OFFLINE_QUEUE_TERMINAL_STATE_REJECTS_ALL_ENTRIES_POLICY.lower()

    def test_v2_arbiter_policy(self):
        from core.offline_durability_closure import (
            V2_IS_OFFLINE_QUEUE_ARBITER_POLICY,
        )
        assert isinstance(V2_IS_OFFLINE_QUEUE_ARBITER_POLICY, str)
        assert "V2" in V2_IS_OFFLINE_QUEUE_ARBITER_POLICY

    def test_ordering_audit_policy(self):
        from core.offline_durability_closure import (
            OFFLINE_QUEUE_ORDERING_AUDIT_POLICY,
        )
        assert isinstance(OFFLINE_QUEUE_ORDERING_AUDIT_POLICY, str)
        assert "audit" in OFFLINE_QUEUE_ORDERING_AUDIT_POLICY.lower()


# ---------------------------------------------------------------------------
# C — OfflineQueueDisposition enum has all 5 required values
# ---------------------------------------------------------------------------


class TestOfflineQueueDispositionEnum:
    def test_all_required_values_present(self):
        from core.offline_durability_closure import OfflineQueueDisposition
        required = {
            "accepted",
            "rejected_duplicate",
            "rejected_stale_terminal",
            "rejected_out_of_authority",
            "held_for_review",
        }
        actual = {m.value for m in OfflineQueueDisposition}
        assert required.issubset(actual)


# ---------------------------------------------------------------------------
# D — OfflineQueueEntry dataclass has required fields; to_dict() works
# ---------------------------------------------------------------------------


class TestOfflineQueueEntry:
    def test_construction_and_to_dict(self):
        from core.offline_durability_closure import OfflineQueueEntry
        entry = OfflineQueueEntry(
            idempotency_key="key_001",
            sequence=1,
            payload={"msg": "hello"},
            device_id="dev_001",
            session_id="sess_001",
        )
        d = entry.to_dict()
        assert d["idempotency_key"] == "key_001"
        assert d["sequence"] == 1
        assert d["payload"] == {"msg": "hello"}
        assert d["device_id"] == "dev_001"
        assert "entry_id" in d

    def test_defaults(self):
        from core.offline_durability_closure import OfflineQueueEntry
        entry = OfflineQueueEntry(idempotency_key="k", sequence=0)
        assert entry.payload == {}
        assert entry.device_id == ""
        assert entry.session_id == ""
        assert entry.queued_at is None
        assert entry.metadata == {}


# ---------------------------------------------------------------------------
# E — OfflineQueueEntry.from_dict() round-trips correctly
# ---------------------------------------------------------------------------


class TestOfflineQueueEntryRoundTrip:
    def test_round_trip(self):
        from core.offline_durability_closure import OfflineQueueEntry
        original = OfflineQueueEntry(
            idempotency_key="rt_key",
            sequence=42,
            payload={"data": "value"},
            device_id="dev_rt",
            session_id="sess_rt",
        )
        restored = OfflineQueueEntry.from_dict(original.to_dict())
        assert restored.idempotency_key == original.idempotency_key
        assert restored.sequence == original.sequence
        assert restored.payload == original.payload
        assert restored.device_id == original.device_id
        assert restored.entry_id == original.entry_id


# ---------------------------------------------------------------------------
# F — OfflineQueueEntry to_json() returns valid JSON
# ---------------------------------------------------------------------------


class TestOfflineQueueEntryJson:
    def test_to_json_is_valid(self):
        from core.offline_durability_closure import OfflineQueueEntry
        entry = OfflineQueueEntry(idempotency_key="json_key", sequence=5)
        data = json.loads(entry.to_json())
        assert data["idempotency_key"] == "json_key"
        assert data["sequence"] == 5


# ---------------------------------------------------------------------------
# G — OfflineQueueEntry: entry_id is auto-generated and unique
# ---------------------------------------------------------------------------


class TestOfflineQueueEntryId:
    def test_entry_id_unique_per_instance(self):
        from core.offline_durability_closure import OfflineQueueEntry
        a = OfflineQueueEntry(idempotency_key="k1", sequence=1)
        b = OfflineQueueEntry(idempotency_key="k1", sequence=1)
        assert a.entry_id != b.entry_id


# ---------------------------------------------------------------------------
# H — OfflineQueueEntryRecord dataclass has required fields; to_dict() works
# ---------------------------------------------------------------------------


class TestOfflineQueueEntryRecord:
    def test_construction_and_to_dict(self):
        from core.offline_durability_closure import (
            OfflineQueueEntryRecord,
            OfflineQueueDisposition,
        )
        rec = OfflineQueueEntryRecord(
            entry_id="e001",
            idempotency_key="key_001",
            sequence=1,
            disposition=OfflineQueueDisposition.accepted,
        )
        d = rec.to_dict()
        assert d["entry_id"] == "e001"
        assert d["disposition"] == "accepted"
        assert "record_id" in d
        assert "processed_at" in d


# ---------------------------------------------------------------------------
# I — OfflineQueueEntryRecord.from_dict() round-trips correctly
# ---------------------------------------------------------------------------


class TestOfflineQueueEntryRecordRoundTrip:
    def test_round_trip(self):
        from core.offline_durability_closure import (
            OfflineQueueEntryRecord,
            OfflineQueueDisposition,
        )
        original = OfflineQueueEntryRecord(
            entry_id="e_rt",
            idempotency_key="k_rt",
            sequence=7,
            disposition=OfflineQueueDisposition.rejected_duplicate,
            evidence={"reason": "test"},
        )
        restored = OfflineQueueEntryRecord.from_dict(original.to_dict())
        assert restored.entry_id == original.entry_id
        assert restored.idempotency_key == original.idempotency_key
        assert restored.disposition == original.disposition
        assert restored.evidence == original.evidence
        assert restored.record_id == original.record_id


# ---------------------------------------------------------------------------
# J — OfflineQueueEntryRecord to_json() returns valid JSON
# ---------------------------------------------------------------------------


class TestOfflineQueueEntryRecordJson:
    def test_to_json_is_valid(self):
        from core.offline_durability_closure import (
            OfflineQueueEntryRecord,
            OfflineQueueDisposition,
        )
        rec = OfflineQueueEntryRecord(
            entry_id="e_json",
            idempotency_key="k_json",
            sequence=3,
            disposition=OfflineQueueDisposition.held_for_review,
        )
        data = json.loads(rec.to_json())
        assert data["disposition"] == "held_for_review"


# ---------------------------------------------------------------------------
# K, L — OfflineQueueBoundarySnapshot
# ---------------------------------------------------------------------------


class TestOfflineQueueBoundarySnapshot:
    def test_construction_and_to_dict(self):
        from core.offline_durability_closure import OfflineQueueBoundarySnapshot
        snap = OfflineQueueBoundarySnapshot(
            total_entries_processed=10,
            total_accepted=7,
        )
        d = snap.to_dict()
        assert d["total_entries_processed"] == 10
        assert d["total_accepted"] == 7
        assert "pr5_sentinel" in d
        assert "snapshot_id" in d

    def test_to_json_is_valid(self):
        from core.offline_durability_closure import OfflineQueueBoundarySnapshot
        snap = OfflineQueueBoundarySnapshot()
        data = json.loads(snap.to_json())
        assert "total_entries_processed" in data


# ---------------------------------------------------------------------------
# M — OfflineQueueRecoveryBoundary instantiates
# ---------------------------------------------------------------------------


class TestBoundaryInstantiation:
    def test_instantiates_with_default_capacity(self):
        from core.offline_durability_closure import OfflineQueueRecoveryBoundary
        b = OfflineQueueRecoveryBoundary()
        assert b is not None

    def test_instantiates_with_custom_capacity(self):
        from core.offline_durability_closure import OfflineQueueRecoveryBoundary
        b = OfflineQueueRecoveryBoundary(capacity=16)
        assert b is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_boundary():
    from core.offline_durability_closure import OfflineQueueRecoveryBoundary
    return OfflineQueueRecoveryBoundary(capacity=32)


def _entry(key: str, seq: int, **kwargs):
    from core.offline_durability_closure import OfflineQueueEntry
    return OfflineQueueEntry(idempotency_key=key, sequence=seq, **kwargs)


# ---------------------------------------------------------------------------
# N — Empty list yields nothing
# ---------------------------------------------------------------------------


class TestReplayOrderedEmpty:
    def test_empty_list_yields_nothing(self):
        b = _fresh_boundary()
        result = list(b.replay_ordered([]))
        assert result == []


# ---------------------------------------------------------------------------
# O — Single valid entry is accepted and yielded
# ---------------------------------------------------------------------------


class TestReplayOrderedSingleEntry:
    def test_single_valid_entry_accepted(self):
        from core.offline_durability_closure import OfflineQueueDisposition
        b = _fresh_boundary()
        entries = [_entry("key_a", 1, payload={"x": 1})]
        result = list(b.replay_ordered(entries))
        assert len(result) == 1
        assert result[0].idempotency_key == "key_a"
        snap = b.build_snapshot()
        assert snap.total_accepted == 1


# ---------------------------------------------------------------------------
# P — Entries sorted by sequence (not insertion order)
# ---------------------------------------------------------------------------


class TestReplayOrderedSequence:
    def test_entries_sorted_by_sequence(self):
        b = _fresh_boundary()
        entries = [
            _entry("key_c", 3),
            _entry("key_a", 1),
            _entry("key_b", 2),
        ]
        result = list(b.replay_ordered(entries))
        assert [e.idempotency_key for e in result] == ["key_a", "key_b", "key_c"]


# ---------------------------------------------------------------------------
# Q — Duplicate idempotency_key: first accepted, second rejected
# ---------------------------------------------------------------------------


class TestReplayOrderedDuplicate:
    def test_first_occurrence_accepted_second_rejected(self):
        from core.offline_durability_closure import OfflineQueueDisposition
        b = _fresh_boundary()
        entries = [
            _entry("dup_key", 1),
            _entry("dup_key", 2),
        ]
        result = list(b.replay_ordered(entries))
        assert len(result) == 1
        assert result[0].sequence == 1
        snap = b.build_snapshot()
        assert snap.total_accepted == 1
        assert snap.total_rejected_duplicate == 1


# ---------------------------------------------------------------------------
# R — Three entries with unique keys: all accepted in order
# ---------------------------------------------------------------------------


class TestReplayOrderedAllUnique:
    def test_all_unique_keys_accepted(self):
        b = _fresh_boundary()
        entries = [
            _entry("k1", 1),
            _entry("k2", 2),
            _entry("k3", 3),
        ]
        result = list(b.replay_ordered(entries))
        assert len(result) == 3
        assert [e.idempotency_key for e in result] == ["k1", "k2", "k3"]


# ---------------------------------------------------------------------------
# S — canonical_is_terminal=True: all entries rejected as stale_terminal
# ---------------------------------------------------------------------------


class TestReplayOrderedTerminalGuard:
    def test_all_rejected_when_canonical_is_terminal(self):
        b = _fresh_boundary()
        entries = [_entry(f"k{i}", i) for i in range(5)]
        result = list(b.replay_ordered(entries, canonical_is_terminal=True))
        assert result == []
        snap = b.build_snapshot()
        assert snap.total_rejected_stale_terminal == 5
        assert snap.total_accepted == 0


# ---------------------------------------------------------------------------
# T — Empty idempotency_key: rejected_out_of_authority
# ---------------------------------------------------------------------------


class TestReplayOrderedEmptyKey:
    def test_empty_key_rejected_out_of_authority(self):
        b = _fresh_boundary()
        entries = [_entry("", 1)]
        result = list(b.replay_ordered(entries))
        assert result == []
        snap = b.build_snapshot()
        assert snap.total_rejected_out_of_authority == 1


# ---------------------------------------------------------------------------
# U — Mixed: valid, duplicate, empty key, terminal
# ---------------------------------------------------------------------------


class TestReplayOrderedMixed:
    def test_mixed_batch(self):
        b = _fresh_boundary()
        entries = [
            _entry("valid_1", 1),
            _entry("valid_2", 2),
            _entry("valid_1", 3),   # duplicate of valid_1
            _entry("", 4),           # empty key → out_of_authority
            _entry("valid_3", 5),
        ]
        result = list(b.replay_ordered(entries))
        # valid_1, valid_2, valid_3 accepted; valid_1 dup and empty key rejected
        assert len(result) == 3
        assert [e.idempotency_key for e in result] == ["valid_1", "valid_2", "valid_3"]
        snap = b.build_snapshot()
        assert snap.total_accepted == 3
        assert snap.total_rejected_duplicate == 1
        assert snap.total_rejected_out_of_authority == 1


# ---------------------------------------------------------------------------
# V — Deduplication is first-wins regardless of sequence
# ---------------------------------------------------------------------------


class TestReplayOrderedFirstWins:
    def test_first_wins_across_all_sequences(self):
        b = _fresh_boundary()
        entries = [
            _entry("shared_key", 5),   # higher sequence; after sorting, appears second → rejected as duplicate
            _entry("shared_key", 1),   # lower sequence; after sorting, appears first → accepted
        ]
        result = list(b.replay_ordered(entries))
        assert len(result) == 1
        # After sorting by sequence, sequence=1 appears first → accepted
        assert result[0].sequence == 1


# ---------------------------------------------------------------------------
# W — Terminal guard applies before sequence sort
# ---------------------------------------------------------------------------


class TestTerminalBeforeSort:
    def test_terminal_guard_applies_to_all_regardless_of_sort(self):
        b = _fresh_boundary()
        entries = [
            _entry("k3", 3),
            _entry("k1", 1),
            _entry("k2", 2),
        ]
        result = list(b.replay_ordered(entries, canonical_is_terminal=True))
        assert result == []
        snap = b.build_snapshot()
        assert snap.total_rejected_stale_terminal == 3


# ---------------------------------------------------------------------------
# X–AC — build_snapshot counters
# ---------------------------------------------------------------------------


class TestBuildSnapshot:
    def test_total_entries_processed(self):
        b = _fresh_boundary()
        entries = [_entry("k1", 1), _entry("k1", 2)]  # 1 accepted, 1 dup
        list(b.replay_ordered(entries))
        snap = b.build_snapshot()
        assert snap.total_entries_processed == 2

    def test_total_accepted_counter(self):
        b = _fresh_boundary()
        list(b.replay_ordered([_entry("k1", 1), _entry("k2", 2)]))
        snap = b.build_snapshot()
        assert snap.total_accepted == 2

    def test_total_rejected_duplicate_counter(self):
        b = _fresh_boundary()
        list(b.replay_ordered([_entry("dup", 1), _entry("dup", 2), _entry("dup", 3)]))
        snap = b.build_snapshot()
        assert snap.total_rejected_duplicate == 2

    def test_total_rejected_stale_terminal_counter(self):
        b = _fresh_boundary()
        list(b.replay_ordered([_entry("k1", 1), _entry("k2", 2)], canonical_is_terminal=True))
        snap = b.build_snapshot()
        assert snap.total_rejected_stale_terminal == 2

    def test_total_rejected_out_of_authority_counter(self):
        b = _fresh_boundary()
        list(b.replay_ordered([_entry("", 1), _entry("", 2)]))
        snap = b.build_snapshot()
        assert snap.total_rejected_out_of_authority == 2

    def test_recent_records_populated(self):
        b = _fresh_boundary()
        list(b.replay_ordered([_entry("k1", 1), _entry("k2", 2)]))
        snap = b.build_snapshot()
        assert len(snap.recent_records) == 2


# ---------------------------------------------------------------------------
# AD — list_recent returns newest-first
# ---------------------------------------------------------------------------


class TestListRecent:
    def test_list_recent_returns_newest_first(self):
        b = _fresh_boundary()
        list(b.replay_ordered([_entry("k1", 1), _entry("k2", 2), _entry("k3", 3)]))
        recent = b.list_recent(n=2)
        assert len(recent) == 2
        # Newest first: k3 was processed last
        assert recent[0].idempotency_key == "k3"


# ---------------------------------------------------------------------------
# AE–AF — Singleton management
# ---------------------------------------------------------------------------


class TestSingletonManagement:
    def test_get_singleton_returns_same_instance(self):
        from core.offline_durability_closure import (
            get_offline_queue_recovery_boundary,
            reset_offline_queue_recovery_boundary,
        )
        reset_offline_queue_recovery_boundary()
        a = get_offline_queue_recovery_boundary()
        b = get_offline_queue_recovery_boundary()
        assert a is b

    def test_reset_singleton_returns_new_instance(self):
        from core.offline_durability_closure import (
            get_offline_queue_recovery_boundary,
            reset_offline_queue_recovery_boundary,
        )
        reset_offline_queue_recovery_boundary()
        a = get_offline_queue_recovery_boundary()
        reset_offline_queue_recovery_boundary()
        b = get_offline_queue_recovery_boundary()
        assert a is not b


# ---------------------------------------------------------------------------
# AG–AH — OfflineQueueDisposition.from_string
# ---------------------------------------------------------------------------


class TestDispositionFromString:
    def test_known_value_returns_member(self):
        from core.offline_durability_closure import OfflineQueueDisposition
        d = OfflineQueueDisposition.from_string("accepted")
        assert d == OfflineQueueDisposition.accepted

    def test_unknown_value_returns_held_for_review(self):
        from core.offline_durability_closure import OfflineQueueDisposition
        d = OfflineQueueDisposition.from_string("unknown_xyz")
        assert d == OfflineQueueDisposition.held_for_review


# ---------------------------------------------------------------------------
# AI — Large batch with interleaved duplicates and out-of-order sequences
# ---------------------------------------------------------------------------


class TestLargeBatch:
    def test_large_batch_interleaved(self):
        b = _fresh_boundary()
        # 10 unique keys at sequences 10, 9, 8, ..., 1, plus 5 duplicates
        entries = [_entry(f"k{i}", 10 - i) for i in range(10)]
        entries += [_entry(f"k{i}", 20 - i) for i in range(5)]  # duplicates
        result = list(b.replay_ordered(entries))
        assert len(result) == 10  # only unique first-occurrences
        # Result should be in ascending sequence order
        seqs = [e.sequence for e in result]
        assert seqs == sorted(seqs)
        snap = b.build_snapshot()
        assert snap.total_rejected_duplicate == 5


# ---------------------------------------------------------------------------
# AJ — Sequence numbers need not be contiguous
# ---------------------------------------------------------------------------


class TestNonContiguousSequences:
    def test_non_contiguous_sequences_ordered_correctly(self):
        b = _fresh_boundary()
        entries = [_entry("k100", 100), _entry("k1", 1), _entry("k50", 50)]
        result = list(b.replay_ordered(entries))
        assert [e.sequence for e in result] == [1, 50, 100]


# ---------------------------------------------------------------------------
# AK — Two replay batches: dedup state is per-batch (not global)
# ---------------------------------------------------------------------------


class TestPerBatchDedup:
    def test_dedup_state_is_per_batch_not_global(self):
        b = _fresh_boundary()
        # First batch: k1 is accepted
        result1 = list(b.replay_ordered([_entry("k1", 1)]))
        # Second batch: k1 should be accepted again (new batch, fresh dedup set)
        result2 = list(b.replay_ordered([_entry("k1", 1)]))
        assert len(result1) == 1
        assert len(result2) == 1


# ---------------------------------------------------------------------------
# AL — record_id is unique per OfflineQueueEntryRecord
# ---------------------------------------------------------------------------


class TestRecordIdUnique:
    def test_record_id_unique_per_record(self):
        from core.offline_durability_closure import (
            OfflineQueueEntryRecord,
            OfflineQueueDisposition,
        )
        a = OfflineQueueEntryRecord(
            entry_id="e1", idempotency_key="k1", sequence=1,
            disposition=OfflineQueueDisposition.accepted,
        )
        b = OfflineQueueEntryRecord(
            entry_id="e2", idempotency_key="k2", sequence=2,
            disposition=OfflineQueueDisposition.accepted,
        )
        assert a.record_id != b.record_id


# ---------------------------------------------------------------------------
# AM — pr5_sentinel contains 'PR-5'
# ---------------------------------------------------------------------------


class TestSnapshotSentinel:
    def test_snapshot_pr5_sentinel_contains_pr5(self):
        from core.offline_durability_closure import OfflineQueueBoundarySnapshot
        snap = OfflineQueueBoundarySnapshot()
        assert "PR-5" in snap.pr5_sentinel
