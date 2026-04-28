#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_offline_replay_ordering_contract.py
==============================================
PR-P0-3: Offline Replay Ordering Contract — automated validation suite.

Validates the V2-side authoritative offline replay ordering contract defined
in ``core.offline_replay_ordering_contract``.

Coverage matrix
---------------
Group A — Contract module structure and sentinels
  A01. Module importable; authority sentinel and PR sentinel present.
  A02. All policy sentinels are non-empty strings.
  A03. STALE_SEQ_WINDOW constant is a positive integer.
  A04. All enumerations importable with correct values.
  A05. OfflineReplayItemEvaluation dataclass has required fields; to_dict() works.
  A06. OfflineReplayItemEvaluation round-trips to_dict → from_dict.
  A07. OfflineReplayOrderingReport dataclass has required fields; to_dict() works.
  A08. OfflineReplayOrderingReport to_json() produces valid JSON.
  A09. OfflineReplayOrderingReport round-trips to_dict → from_dict.
  A10. OfflineReplayOrderingReport includes continuity and truth-convergence notes.

Group B — evaluate_replay_sequence(): ordered replay (normal semantics)
  B01. Empty sequence → contract_not_yet_evidenced verdict.
  B02. Single in-order item → accept decision, authoritative_contract_defined verdict.
  B03. Fully ordered sequence (seq 1,2,3) → all accept.
  B04. Ordering authority is v2_side in report.
  B05. Ordering guarantee is strict_fifo_within_session.
  B06. Duplicate avoidance boundary is v2_signal_guard.
  B07. accepted_count matches number of distinct in-order items.

Group C — evaluate_replay_sequence(): out-of-order replay
  C01. Item with seq below session max → reject_out_of_order.
  C02. Out-of-order item within stale window → status=out_of_order.
  C03. rejected_out_of_order_count incremented correctly.
  C04. Out-of-order item does not advance session max_seq.
  C05. Sequence with mixed in-order and out-of-order → contract_partially_evidenced.

Group D — evaluate_replay_sequence(): duplicate replay
  D01. Same item_id twice → second occurrence is reject_duplicate.
  D02. is_duplicate=True on second item.
  D03. rejected_duplicate_count incremented.
  D04. Duplicate rejection is independent of seq value.
  D05. Three items, one duplicate → only two accepted (or one if dup is first unique).

Group E — evaluate_replay_sequence(): stale replay downgrade
  E01. Item with seq more than STALE_SEQ_WINDOW below max → reject_stale.
  E02. is_stale=True on stale item.
  E03. rejected_stale_count incremented.
  E04. Stale item note references STALE_REPLAY policy.
  E05. Stale threshold exactly at STALE_SEQ_WINDOW → out_of_order, not stale.
  E06. Stale threshold one beyond STALE_SEQ_WINDOW → stale.

Group F — evaluate_replay_sequence(): partial and ambiguous authority
  F01. partial_drain=True caps verdict at contract_partially_evidenced.
  F02. partial_drain=True even for all-in-order sequence.
  F03. ordering_authority=ambiguous → verdict=downgraded regardless of items.
  F04. Ambiguous authority does NOT produce authoritative_contract_defined.
  F05. Items with missing item_id → ambiguous_authority decision.
  F06. ambiguous_count incremented for missing item_id items.

Group G — Authority enforcement (no optimistic upgrade)
  G01. Authority=ambiguous with all in-order items → still downgraded.
  G02. Authority=android_side (not ambiguous) → contract still evaluated,
       ordering semantics applied, verdict not downgraded by authority alone.
  G03. Deferred → advisory progression: verdict is never "deferred" string.
  G04. OfflineReplayContractVerdict.downgraded.is_contract_active is False.
  G05. OfflineReplayContractVerdict.contract_not_yet_evidenced.is_contract_active True.
  G06. OfflineReplayContractVerdict.authoritative_contract_defined.is_fully_evidenced True.
  G07. contract_not_yet_evidenced.is_fully_evidenced is False.

Group H — build_offline_replay_ordering_report() baseline
  H01. Returns OfflineReplayOrderingReport with correct authority sentinels.
  H02. Baseline verdict is contract_not_yet_evidenced.
  H03. Baseline has zero items evaluated.
  H04. Baseline ordering_authority is v2_side.
  H05. Baseline summary is non-empty.
  H06. get_offline_replay_ordering_report() returns a singleton.
  H07. reset_offline_replay_ordering_report() clears singleton.

Group I — Integration: recovery closure validator
  I01. RS-16 in RecoveryClosureReport is advisory (not deferred).
  I02. RS-16 references offline replay ordering contract.
  I03. OFFLINE_QUEUE_ORDERING_CONTRACT_NOW_DEFINED_POLICY is a non-empty string.

Group J — Integration: recovery truth surface
  J01. OFFLINE_QUEUE_REPLAY_ORDERING_CONTRACT_IS_DEFINED_TRUTH_POLICY is non-empty.
  J02. build_recovery_truth_report() runs without error with contract available.
  J03. No entry in truth report claims status=observed without live event.
"""

from __future__ import annotations

import json
import pytest


# ---------------------------------------------------------------------------
# Group A — Contract module structure and sentinels
# ---------------------------------------------------------------------------


class TestContractModuleStructure:
    def test_A01_module_importable_and_sentinels_present(self):
        from core.offline_replay_ordering_contract import (
            OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY,
            OFFLINE_REPLAY_ORDERING_CONTRACT_PR_P03_SENTINEL,
        )
        assert OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY
        assert OFFLINE_REPLAY_ORDERING_CONTRACT_PR_P03_SENTINEL
        assert "PR-P0-3" in OFFLINE_REPLAY_ORDERING_CONTRACT_PR_P03_SENTINEL
        assert "offline_replay_ordering_contract" in (
            OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY
        )

    def test_A02_all_policy_sentinels_non_empty(self):
        from core.offline_replay_ordering_contract import (
            V2_IS_REPLAY_ORDERING_AUTHORITY_POLICY,
            REPLAY_ORDERING_FORMAL_SEMANTICS_POLICY,
            DUPLICATE_AVOIDANCE_BOUNDARY_IS_V2_SIGNAL_GUARD_POLICY,
            STALE_REPLAY_MUST_DOWNGRADE_NOT_ACCEPT_POLICY,
            OUT_OF_ORDER_REPLAY_MUST_NOT_SILENTLY_ACCEPT_POLICY,
            AMBIGUOUS_AUTHORITY_MUST_NOT_OPTIMISTICALLY_UPGRADE_POLICY,
            PARTIAL_REPLAY_STAYS_ADVISORY_NOT_FULLY_CLOSED_POLICY,
            REPLAY_CONTINUITY_REQUIRES_CANONICAL_TASK_IDENTITY_POLICY,
            REPLAY_TRUTH_CONVERGENCE_REQUIRES_V2_ABSORPTION_POLICY,
        )
        for sentinel in [
            V2_IS_REPLAY_ORDERING_AUTHORITY_POLICY,
            REPLAY_ORDERING_FORMAL_SEMANTICS_POLICY,
            DUPLICATE_AVOIDANCE_BOUNDARY_IS_V2_SIGNAL_GUARD_POLICY,
            STALE_REPLAY_MUST_DOWNGRADE_NOT_ACCEPT_POLICY,
            OUT_OF_ORDER_REPLAY_MUST_NOT_SILENTLY_ACCEPT_POLICY,
            AMBIGUOUS_AUTHORITY_MUST_NOT_OPTIMISTICALLY_UPGRADE_POLICY,
            PARTIAL_REPLAY_STAYS_ADVISORY_NOT_FULLY_CLOSED_POLICY,
            REPLAY_CONTINUITY_REQUIRES_CANONICAL_TASK_IDENTITY_POLICY,
            REPLAY_TRUTH_CONVERGENCE_REQUIRES_V2_ABSORPTION_POLICY,
        ]:
            assert isinstance(sentinel, str) and sentinel, (
                f"empty policy sentinel: {sentinel!r}"
            )

    def test_A03_stale_seq_window_is_positive_int(self):
        from core.offline_replay_ordering_contract import STALE_SEQ_WINDOW
        assert isinstance(STALE_SEQ_WINDOW, int)
        assert STALE_SEQ_WINDOW > 0

    def test_A04_all_enums_importable(self):
        from core.offline_replay_ordering_contract import (
            ReplayOrderingAuthority,
            ReplayOrderingGuarantee,
            DuplicateAvoidanceBoundary,
            ReplaySequenceStatus,
            OfflineReplayItemDecision,
            OfflineReplayContractVerdict,
        )
        assert ReplayOrderingAuthority.v2_side.value == "v2_side"
        assert ReplayOrderingAuthority.ambiguous.value == "ambiguous"
        assert ReplayOrderingGuarantee.strict_fifo_within_session.value == (
            "strict_fifo_within_session"
        )
        assert DuplicateAvoidanceBoundary.v2_signal_guard.value == "v2_signal_guard"
        assert ReplaySequenceStatus.in_order.value == "in_order"
        assert ReplaySequenceStatus.out_of_order.value == "out_of_order"
        assert ReplaySequenceStatus.duplicate.value == "duplicate"
        assert ReplaySequenceStatus.stale.value == "stale"
        assert OfflineReplayItemDecision.accept.value == "accept"
        assert OfflineReplayItemDecision.reject_duplicate.value == "reject_duplicate"
        assert OfflineReplayItemDecision.reject_stale.value == "reject_stale"
        assert OfflineReplayItemDecision.reject_out_of_order.value == (
            "reject_out_of_order"
        )
        assert OfflineReplayContractVerdict.authoritative_contract_defined.value == (
            "authoritative_contract_defined"
        )
        assert OfflineReplayContractVerdict.contract_not_yet_evidenced.value == (
            "contract_not_yet_evidenced"
        )
        assert OfflineReplayContractVerdict.downgraded.value == "downgraded"

    def test_A05_item_evaluation_fields_and_to_dict(self):
        from core.offline_replay_ordering_contract import (
            OfflineReplayItemEvaluation,
            ReplaySequenceStatus,
            OfflineReplayItemDecision,
        )
        item = OfflineReplayItemEvaluation(
            item_id="item-1",
            seq=1,
            status=ReplaySequenceStatus.in_order,
            decision=OfflineReplayItemDecision.accept,
            note="test item",
        )
        d = item.to_dict()
        assert d["item_id"] == "item-1"
        assert d["seq"] == 1
        assert d["status"] == "in_order"
        assert d["decision"] == "accept"
        assert d["note"] == "test item"
        assert "is_duplicate" in d
        assert "is_stale" in d
        assert "is_out_of_order" in d

    def test_A06_item_evaluation_round_trip(self):
        from core.offline_replay_ordering_contract import (
            OfflineReplayItemEvaluation,
            ReplaySequenceStatus,
            OfflineReplayItemDecision,
        )
        original = OfflineReplayItemEvaluation(
            item_id="round-trip",
            seq=5,
            status=ReplaySequenceStatus.stale,
            decision=OfflineReplayItemDecision.reject_stale,
            is_stale=True,
            note="stale item",
        )
        restored = OfflineReplayItemEvaluation.from_dict(original.to_dict())
        assert restored.item_id == original.item_id
        assert restored.seq == original.seq
        assert restored.status == original.status
        assert restored.decision == original.decision
        assert restored.is_stale == original.is_stale
        assert restored.note == original.note

    def test_A07_report_fields_and_to_dict(self):
        from core.offline_replay_ordering_contract import (
            OfflineReplayOrderingReport,
            OfflineReplayContractVerdict,
            ReplayOrderingAuthority,
        )
        rpt = OfflineReplayOrderingReport()
        d = rpt.to_dict()
        for key in [
            "report_id", "generated_at", "authority_sentinel", "pr_sentinel",
            "ordering_authority", "ordering_guarantee", "duplicate_avoidance_boundary",
            "verdict", "items", "accepted_count", "rejected_duplicate_count",
            "rejected_stale_count", "rejected_out_of_order_count",
            "downgraded_count", "ambiguous_count", "total_items", "partial_drain",
            "continuity_relation_note", "truth_convergence_note", "summary",
            "is_contract_active", "is_fully_evidenced",
        ]:
            assert key in d, f"missing key {key!r} in report dict"

    def test_A08_report_to_json_is_valid_json(self):
        from core.offline_replay_ordering_contract import OfflineReplayOrderingReport
        rpt = OfflineReplayOrderingReport()
        raw = rpt.to_json()
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)
        assert "verdict" in parsed

    def test_A09_report_round_trips(self):
        from core.offline_replay_ordering_contract import (
            OfflineReplayOrderingReport,
            OfflineReplayContractVerdict,
            ReplayOrderingAuthority,
        )
        original = OfflineReplayOrderingReport(
            ordering_authority=ReplayOrderingAuthority.v2_side,
            verdict=OfflineReplayContractVerdict.contract_not_yet_evidenced,
            total_items=0,
        )
        restored = OfflineReplayOrderingReport.from_dict(original.to_dict())
        assert restored.ordering_authority == original.ordering_authority
        assert restored.verdict == original.verdict
        assert restored.total_items == original.total_items

    def test_A10_report_has_continuity_and_truth_convergence_notes(self):
        from core.offline_replay_ordering_contract import OfflineReplayOrderingReport
        rpt = OfflineReplayOrderingReport()
        assert rpt.continuity_relation_note
        assert rpt.truth_convergence_note
        # Continuity note must reference canonical task identity policy
        assert "task_id" in rpt.continuity_relation_note.lower() or \
               "canonical" in rpt.continuity_relation_note.lower() or \
               "identity" in rpt.continuity_relation_note.lower()
        # Truth convergence note must reference V2 absorption
        assert "absorption" in rpt.truth_convergence_note.lower() or \
               "v2" in rpt.truth_convergence_note.lower() or \
               "convergence" in rpt.truth_convergence_note.lower()


# ---------------------------------------------------------------------------
# Group B — evaluate_replay_sequence(): ordered replay (normal semantics)
# ---------------------------------------------------------------------------


class TestOrderedReplay:
    def test_B01_empty_sequence_is_not_yet_evidenced(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayContractVerdict,
        )
        rpt = evaluate_replay_sequence([])
        assert rpt.verdict == OfflineReplayContractVerdict.contract_not_yet_evidenced
        assert rpt.total_items == 0
        assert rpt.accepted_count == 0

    def test_B02_single_in_order_item_accepted(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayContractVerdict,
            OfflineReplayItemDecision,
        )
        rpt = evaluate_replay_sequence([{"item_id": "item-1", "seq": 1}])
        assert rpt.accepted_count == 1
        assert rpt.total_items == 1
        assert rpt.verdict == OfflineReplayContractVerdict.authoritative_contract_defined
        assert rpt.items[0].decision == OfflineReplayItemDecision.accept

    def test_B03_fully_ordered_sequence_all_accepted(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayItemDecision,
            OfflineReplayContractVerdict,
        )
        items = [{"item_id": f"item-{i}", "seq": i} for i in range(1, 6)]
        rpt = evaluate_replay_sequence(items)
        assert rpt.accepted_count == 5
        assert rpt.total_items == 5
        assert rpt.rejected_out_of_order_count == 0
        assert rpt.rejected_duplicate_count == 0
        assert rpt.rejected_stale_count == 0
        assert rpt.verdict == OfflineReplayContractVerdict.authoritative_contract_defined
        for item_eval in rpt.items:
            assert item_eval.decision == OfflineReplayItemDecision.accept, (
                f"Expected accept for {item_eval.item_id}; got {item_eval.decision}"
            )

    def test_B04_ordering_authority_is_v2_side(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            ReplayOrderingAuthority,
        )
        rpt = evaluate_replay_sequence([{"item_id": "x", "seq": 1}])
        assert rpt.ordering_authority == ReplayOrderingAuthority.v2_side

    def test_B05_ordering_guarantee_is_strict_fifo(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            ReplayOrderingGuarantee,
        )
        rpt = evaluate_replay_sequence([])
        assert rpt.ordering_guarantee == ReplayOrderingGuarantee.strict_fifo_within_session

    def test_B06_duplicate_avoidance_boundary_is_v2_signal_guard(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            DuplicateAvoidanceBoundary,
        )
        rpt = evaluate_replay_sequence([])
        assert rpt.duplicate_avoidance_boundary == DuplicateAvoidanceBoundary.v2_signal_guard

    def test_B07_accepted_count_matches_distinct_in_order_items(self):
        from core.offline_replay_ordering_contract import evaluate_replay_sequence
        items = [
            {"item_id": "a", "seq": 1},
            {"item_id": "b", "seq": 2},
            {"item_id": "c", "seq": 3},
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.accepted_count == 3


# ---------------------------------------------------------------------------
# Group C — evaluate_replay_sequence(): out-of-order replay
# ---------------------------------------------------------------------------


class TestOutOfOrderReplay:
    def test_C01_item_with_seq_below_session_max_rejected(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayItemDecision,
            STALE_SEQ_WINDOW,
        )
        # Establish max=5, then replay seq=4 (below max, within stale window)
        items = [
            {"item_id": "item-5", "seq": 5},
            {"item_id": "item-4", "seq": 4},
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.items[1].decision == OfflineReplayItemDecision.reject_out_of_order

    def test_C02_out_of_order_status_set_correctly(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            ReplaySequenceStatus,
        )
        items = [
            {"item_id": "item-5", "seq": 5},
            {"item_id": "item-3", "seq": 3},
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.items[1].status == ReplaySequenceStatus.out_of_order
        assert rpt.items[1].is_out_of_order is True

    def test_C03_rejected_out_of_order_count_incremented(self):
        from core.offline_replay_ordering_contract import evaluate_replay_sequence
        items = [
            {"item_id": "item-10", "seq": 10},
            {"item_id": "item-8", "seq": 8},
            {"item_id": "item-6", "seq": 6},
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.rejected_out_of_order_count == 2

    def test_C04_out_of_order_does_not_advance_session_max(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayItemDecision,
        )
        # seq=10 accepted, seq=5 rejected out-of-order, seq=11 accepted
        items = [
            {"item_id": "a", "seq": 10},
            {"item_id": "b", "seq": 5},   # out-of-order
            {"item_id": "c", "seq": 11},  # should still be accepted
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.items[0].decision == OfflineReplayItemDecision.accept
        assert rpt.items[1].decision == OfflineReplayItemDecision.reject_out_of_order
        assert rpt.items[2].decision == OfflineReplayItemDecision.accept

    def test_C05_mixed_in_order_and_out_of_order_is_partially_evidenced(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayContractVerdict,
        )
        items = [
            {"item_id": "a", "seq": 5},
            {"item_id": "b", "seq": 3},  # out-of-order
            {"item_id": "c", "seq": 7},
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.verdict == OfflineReplayContractVerdict.contract_partially_evidenced
        assert rpt.accepted_count >= 1
        assert rpt.rejected_out_of_order_count >= 1


# ---------------------------------------------------------------------------
# Group D — evaluate_replay_sequence(): duplicate replay
# ---------------------------------------------------------------------------


class TestDuplicateReplay:
    def test_D01_same_item_id_twice_second_is_reject_duplicate(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayItemDecision,
        )
        items = [
            {"item_id": "dup-item", "seq": 1},
            {"item_id": "dup-item", "seq": 2},  # duplicate
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.items[0].decision == OfflineReplayItemDecision.accept
        assert rpt.items[1].decision == OfflineReplayItemDecision.reject_duplicate

    def test_D02_is_duplicate_true_on_duplicate_item(self):
        from core.offline_replay_ordering_contract import evaluate_replay_sequence
        items = [
            {"item_id": "dup", "seq": 1},
            {"item_id": "dup", "seq": 2},
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.items[1].is_duplicate is True

    def test_D03_rejected_duplicate_count_incremented(self):
        from core.offline_replay_ordering_contract import evaluate_replay_sequence
        items = [
            {"item_id": "a", "seq": 1},
            {"item_id": "a", "seq": 2},
            {"item_id": "b", "seq": 3},
            {"item_id": "b", "seq": 4},
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.rejected_duplicate_count == 2
        assert rpt.accepted_count == 2

    def test_D04_duplicate_rejection_independent_of_seq(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayItemDecision,
        )
        # Same item_id at any seq → duplicate
        items = [
            {"item_id": "x", "seq": 100},
            {"item_id": "x", "seq": 200},  # higher seq, still duplicate
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.items[1].decision == OfflineReplayItemDecision.reject_duplicate

    def test_D05_three_items_one_duplicate(self):
        from core.offline_replay_ordering_contract import evaluate_replay_sequence
        items = [
            {"item_id": "a", "seq": 1},
            {"item_id": "b", "seq": 2},
            {"item_id": "a", "seq": 3},  # duplicate of first
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.accepted_count == 2
        assert rpt.rejected_duplicate_count == 1


# ---------------------------------------------------------------------------
# Group E — evaluate_replay_sequence(): stale replay downgrade
# ---------------------------------------------------------------------------


class TestStaleReplay:
    def test_E01_item_beyond_stale_window_is_reject_stale(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayItemDecision,
            STALE_SEQ_WINDOW,
        )
        # max=100, stale window=10 → seq < 90 is stale
        max_seq = 100
        stale_seq = max_seq - STALE_SEQ_WINDOW - 1  # one beyond window
        items = [
            {"item_id": "current", "seq": max_seq},
            {"item_id": "stale",   "seq": stale_seq},
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.items[1].decision == OfflineReplayItemDecision.reject_stale

    def test_E02_is_stale_true_on_stale_item(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            STALE_SEQ_WINDOW,
        )
        max_seq = 50
        stale_seq = max_seq - STALE_SEQ_WINDOW - 5
        items = [
            {"item_id": "a", "seq": max_seq},
            {"item_id": "b", "seq": stale_seq},
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.items[1].is_stale is True

    def test_E03_rejected_stale_count_incremented(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            STALE_SEQ_WINDOW,
        )
        max_seq = 100
        items = [
            {"item_id": "current", "seq": max_seq},
            {"item_id": "stale1",  "seq": max_seq - STALE_SEQ_WINDOW - 1},
            {"item_id": "stale2",  "seq": max_seq - STALE_SEQ_WINDOW - 2},
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.rejected_stale_count == 2

    def test_E04_stale_item_note_references_policy(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            STALE_SEQ_WINDOW,
        )
        max_seq = 50
        stale_seq = max_seq - STALE_SEQ_WINDOW - 1
        items = [
            {"item_id": "a", "seq": max_seq},
            {"item_id": "b", "seq": stale_seq},
        ]
        rpt = evaluate_replay_sequence(items)
        note_lower = rpt.items[1].note.lower()
        assert "stale" in note_lower

    def test_E05_exactly_at_stale_window_is_out_of_order_not_stale(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayItemDecision,
            STALE_SEQ_WINDOW,
        )
        # max - STALE_SEQ_WINDOW is exactly at the boundary → out_of_order
        max_seq = 50
        boundary_seq = max_seq - STALE_SEQ_WINDOW  # exactly at boundary
        items = [
            {"item_id": "a", "seq": max_seq},
            {"item_id": "b", "seq": boundary_seq},
        ]
        rpt = evaluate_replay_sequence(items)
        # boundary_seq is within window → should be out_of_order, not stale
        assert rpt.items[1].decision == OfflineReplayItemDecision.reject_out_of_order

    def test_E06_one_beyond_stale_window_is_stale(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayItemDecision,
            STALE_SEQ_WINDOW,
        )
        max_seq = 50
        stale_seq = max_seq - STALE_SEQ_WINDOW - 1  # one step beyond window
        items = [
            {"item_id": "a", "seq": max_seq},
            {"item_id": "b", "seq": stale_seq},
        ]
        rpt = evaluate_replay_sequence(items)
        assert rpt.items[1].decision == OfflineReplayItemDecision.reject_stale


# ---------------------------------------------------------------------------
# Group F — evaluate_replay_sequence(): partial and ambiguous authority
# ---------------------------------------------------------------------------


class TestPartialAndAmbiguous:
    def test_F01_partial_drain_caps_verdict(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayContractVerdict,
        )
        items = [{"item_id": "a", "seq": 1}, {"item_id": "b", "seq": 2}]
        rpt = evaluate_replay_sequence(items, partial_drain=True)
        assert rpt.verdict == OfflineReplayContractVerdict.contract_partially_evidenced

    def test_F02_partial_drain_even_for_all_in_order(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayContractVerdict,
        )
        # All items in order, but drain is partial
        items = [{"item_id": f"item-{i}", "seq": i} for i in range(1, 10)]
        rpt = evaluate_replay_sequence(items, partial_drain=True)
        assert rpt.verdict == OfflineReplayContractVerdict.contract_partially_evidenced
        assert rpt.partial_drain is True

    def test_F03_ambiguous_authority_produces_downgraded(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            ReplayOrderingAuthority,
            OfflineReplayContractVerdict,
        )
        items = [{"item_id": "a", "seq": 1}]
        rpt = evaluate_replay_sequence(
            items, ordering_authority=ReplayOrderingAuthority.ambiguous
        )
        assert rpt.verdict == OfflineReplayContractVerdict.downgraded

    def test_F04_ambiguous_authority_not_authoritative_contract_defined(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            ReplayOrderingAuthority,
            OfflineReplayContractVerdict,
        )
        items = [{"item_id": f"x{i}", "seq": i} for i in range(1, 20)]
        rpt = evaluate_replay_sequence(
            items, ordering_authority=ReplayOrderingAuthority.ambiguous
        )
        assert rpt.verdict != OfflineReplayContractVerdict.authoritative_contract_defined

    def test_F05_missing_item_id_yields_ambiguous_decision(self):
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            OfflineReplayItemDecision,
        )
        items = [{"seq": 1}]  # no item_id
        rpt = evaluate_replay_sequence(items)
        assert rpt.items[0].decision == OfflineReplayItemDecision.ambiguous_authority

    def test_F06_ambiguous_count_incremented_for_missing_id(self):
        from core.offline_replay_ordering_contract import evaluate_replay_sequence
        items = [{"seq": 1}, {"seq": 2}]  # no item_ids
        rpt = evaluate_replay_sequence(items)
        assert rpt.ambiguous_count == 2


# ---------------------------------------------------------------------------
# Group G — Authority enforcement (no optimistic upgrade)
# ---------------------------------------------------------------------------


class TestAuthorityEnforcement:
    def test_G01_ambiguous_authority_with_all_in_order_still_downgraded(self):
        """AMBIGUOUS_AUTHORITY_MUST_NOT_OPTIMISTICALLY_UPGRADE_POLICY.

        Even if every item is perfectly in-order, ambiguous authority MUST
        produce downgraded — never authoritative_contract_defined.
        """
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            ReplayOrderingAuthority,
            OfflineReplayContractVerdict,
        )
        items = [{"item_id": f"item-{i}", "seq": i} for i in range(1, 100)]
        rpt = evaluate_replay_sequence(
            items, ordering_authority=ReplayOrderingAuthority.ambiguous
        )
        assert rpt.verdict == OfflineReplayContractVerdict.downgraded
        # Verify the policy is referenced in module
        from core.offline_replay_ordering_contract import (
            AMBIGUOUS_AUTHORITY_MUST_NOT_OPTIMISTICALLY_UPGRADE_POLICY,
        )
        assert "MUST NOT" in AMBIGUOUS_AUTHORITY_MUST_NOT_OPTIMISTICALLY_UPGRADE_POLICY or \
               "must not" in AMBIGUOUS_AUTHORITY_MUST_NOT_OPTIMISTICALLY_UPGRADE_POLICY.lower()

    def test_G02_android_side_authority_still_applies_ordering_semantics(self):
        """Android-side authority is not ambiguous; ordering semantics still apply.

        When authority=android_side, V2 still evaluates ordering (advisory)
        and the verdict reflects item quality, not authority ambiguity.
        """
        from core.offline_replay_ordering_contract import (
            evaluate_replay_sequence,
            ReplayOrderingAuthority,
            OfflineReplayContractVerdict,
        )
        items = [{"item_id": "a", "seq": 1}, {"item_id": "b", "seq": 2}]
        rpt = evaluate_replay_sequence(
            items, ordering_authority=ReplayOrderingAuthority.android_side
        )
        # android_side is not ambiguous → not downgraded by authority alone
        assert rpt.verdict != OfflineReplayContractVerdict.downgraded

    def test_G03_verdict_value_is_never_deferred_string(self):
        """The contract produces advisory-or-better verdicts, never raw 'deferred'.

        The progression from deferred (old RS-16) to advisory (new contract)
        means that OfflineReplayContractVerdict enum has no 'deferred' value.
        """
        from core.offline_replay_ordering_contract import OfflineReplayContractVerdict
        verdict_values = {v.value for v in OfflineReplayContractVerdict}
        assert "deferred" not in verdict_values, (
            "OfflineReplayContractVerdict must not have a 'deferred' value; "
            "the contract replaces deferred with authoritative contract definition."
        )

    def test_G04_downgraded_is_contract_active_false(self):
        from core.offline_replay_ordering_contract import OfflineReplayContractVerdict
        assert OfflineReplayContractVerdict.downgraded.is_contract_active is False

    def test_G05_not_yet_evidenced_is_contract_active_true(self):
        from core.offline_replay_ordering_contract import OfflineReplayContractVerdict
        assert (
            OfflineReplayContractVerdict.contract_not_yet_evidenced.is_contract_active
            is True
        )

    def test_G06_authoritative_contract_defined_is_fully_evidenced(self):
        from core.offline_replay_ordering_contract import OfflineReplayContractVerdict
        assert (
            OfflineReplayContractVerdict.authoritative_contract_defined.is_fully_evidenced
            is True
        )

    def test_G07_not_yet_evidenced_is_not_fully_evidenced(self):
        from core.offline_replay_ordering_contract import OfflineReplayContractVerdict
        assert (
            OfflineReplayContractVerdict.contract_not_yet_evidenced.is_fully_evidenced
            is False
        )


# ---------------------------------------------------------------------------
# Group H — build_offline_replay_ordering_report() baseline
# ---------------------------------------------------------------------------


class TestBaselineReport:
    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        from core.offline_replay_ordering_contract import (
            reset_offline_replay_ordering_report,
        )
        reset_offline_replay_ordering_report()
        yield
        reset_offline_replay_ordering_report()

    def test_H01_baseline_has_correct_sentinels(self):
        from core.offline_replay_ordering_contract import (
            build_offline_replay_ordering_report,
            OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY,
            OFFLINE_REPLAY_ORDERING_CONTRACT_PR_P03_SENTINEL,
        )
        rpt = build_offline_replay_ordering_report()
        assert rpt.authority_sentinel == OFFLINE_REPLAY_ORDERING_CONTRACT_AUTHORITY
        assert rpt.pr_sentinel == OFFLINE_REPLAY_ORDERING_CONTRACT_PR_P03_SENTINEL

    def test_H02_baseline_verdict_is_not_yet_evidenced(self):
        from core.offline_replay_ordering_contract import (
            build_offline_replay_ordering_report,
            OfflineReplayContractVerdict,
        )
        rpt = build_offline_replay_ordering_report()
        assert rpt.verdict == OfflineReplayContractVerdict.contract_not_yet_evidenced

    def test_H03_baseline_has_zero_items(self):
        from core.offline_replay_ordering_contract import (
            build_offline_replay_ordering_report,
        )
        rpt = build_offline_replay_ordering_report()
        assert rpt.total_items == 0
        assert len(rpt.items) == 0

    def test_H04_baseline_ordering_authority_is_v2_side(self):
        from core.offline_replay_ordering_contract import (
            build_offline_replay_ordering_report,
            ReplayOrderingAuthority,
        )
        rpt = build_offline_replay_ordering_report()
        assert rpt.ordering_authority == ReplayOrderingAuthority.v2_side

    def test_H05_baseline_summary_non_empty(self):
        from core.offline_replay_ordering_contract import (
            build_offline_replay_ordering_report,
        )
        rpt = build_offline_replay_ordering_report()
        assert rpt.summary
        assert len(rpt.summary) > 10

    def test_H06_singleton_returns_same_object(self):
        from core.offline_replay_ordering_contract import (
            get_offline_replay_ordering_report,
        )
        rpt1 = get_offline_replay_ordering_report()
        rpt2 = get_offline_replay_ordering_report()
        assert rpt1 is rpt2

    def test_H07_reset_clears_singleton(self):
        from core.offline_replay_ordering_contract import (
            get_offline_replay_ordering_report,
            reset_offline_replay_ordering_report,
        )
        rpt1 = get_offline_replay_ordering_report()
        reset_offline_replay_ordering_report()
        rpt2 = get_offline_replay_ordering_report()
        assert rpt1 is not rpt2


# ---------------------------------------------------------------------------
# Group I — Integration: recovery closure validator
# ---------------------------------------------------------------------------


class TestIntegrationRecoveryClosureValidator:
    def test_I01_rs16_is_advisory_not_deferred(self):
        """RS-16 must be advisory after PR-P0-3 contract definition."""
        from core.recovery_durability_closure_validator import (
            build_recovery_closure_report,
            RecoveryScenarioStatus,
        )
        report = build_recovery_closure_report()
        rs16 = next(s for s in report.scenarios if s.scenario_id == "RS-16")
        assert rs16.status == RecoveryScenarioStatus.advisory, (
            f"RS-16 must be advisory after PR-P0-3; got {rs16.status!r}"
        )

    def test_I02_rs16_references_offline_replay_ordering_contract(self):
        """RS-16 note or policy_reference must reference the contract."""
        from core.recovery_durability_closure_validator import (
            build_recovery_closure_report,
        )
        report = build_recovery_closure_report()
        rs16 = next(s for s in report.scenarios if s.scenario_id == "RS-16")
        combined = (rs16.note + rs16.policy_reference).lower()
        assert (
            "offline_replay_ordering_contract" in combined
            or "pr-p0-3" in combined
            or "contract" in combined
        ), (
            f"RS-16 must reference the ordering contract; "
            f"note={rs16.note!r}, policy_ref={rs16.policy_reference!r}"
        )

    def test_I03_new_policy_sentinel_is_non_empty(self):
        from core.recovery_durability_closure_validator import (
            OFFLINE_QUEUE_ORDERING_CONTRACT_NOW_DEFINED_POLICY,
        )
        assert OFFLINE_QUEUE_ORDERING_CONTRACT_NOW_DEFINED_POLICY
        assert "PR-P0-3" in OFFLINE_QUEUE_ORDERING_CONTRACT_NOW_DEFINED_POLICY


# ---------------------------------------------------------------------------
# Group J — Integration: recovery truth surface
# ---------------------------------------------------------------------------


class TestIntegrationRecoveryTruthSurface:
    def test_J01_new_truth_sentinel_is_non_empty(self):
        from core.recovery_truth_surface import (
            OFFLINE_QUEUE_REPLAY_ORDERING_CONTRACT_IS_DEFINED_TRUTH_POLICY,
        )
        assert OFFLINE_QUEUE_REPLAY_ORDERING_CONTRACT_IS_DEFINED_TRUTH_POLICY
        assert "PR-P0-3" in (
            OFFLINE_QUEUE_REPLAY_ORDERING_CONTRACT_IS_DEFINED_TRUTH_POLICY
        )

    def test_J02_build_recovery_truth_report_runs_without_error(self):
        from core.recovery_truth_surface import (
            build_recovery_truth_report,
            reset_recovery_truth_surface,
        )
        reset_recovery_truth_surface()
        rpt = build_recovery_truth_report()
        assert rpt is not None
        assert len(rpt.entries) == 6
        d = rpt.to_dict()
        assert isinstance(d, dict)
        assert "verdict" not in d  # it's a truth report, not a verdict report
        assert "entries" in d

    def test_J03_no_entry_claims_observed_without_live_event(self):
        """No truth entry may claim status=observed without a live event.

        This test mirrors the existing test_F03 but also ensures the new
        offline replay contract integration does not introduce spurious
        'observed' claims.
        """
        from core.recovery_truth_surface import (
            build_recovery_truth_report,
            RecoveryTruthStatus,
            reset_recovery_truth_surface,
        )
        reset_recovery_truth_surface()
        rpt = build_recovery_truth_report()
        for entry in rpt.entries:
            assert entry.status != RecoveryTruthStatus.observed, (
                f"Entry {entry.dimension.value!r} claims status=observed "
                f"but no live event was simulated: {entry.evidence_summary!r}"
            )
