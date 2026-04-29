#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr13_concurrent_mutation_conflict_contract.py
=========================================================
PR-13 — Multi-Writer / Concurrent Mutation / Conflict Semantics Contract.

Validates that:

1.  **Mutation conflict taxonomy is defined and importable** (five classes).
2.  **conflict_free_authoritative** when all single-writer conditions met.
3.  **conflict_free_authoritative requires all conditions** — any single
    missing or negative condition prevents it.
4.  **deterministically_merged** when deterministic merge applied and
    all conflicts resolved.
5.  **last_writer_won_non_authoritative** when last-writer-wins applied.
6.  **reconciliation_required** when reconciliation initiated but incomplete.
7.  **conflict_unresolved** when explicit_conflict_unresolved=True.
8.  **conflict_unresolved** when conflict acknowledged but no resolution.
9.  **conflict_unresolved** zero-evidence baseline (fail-conservative).
10. **last_writer_wins must not claim authoritative** — ever.
11. **reconciliation incomplete blocks authoritative class** — always.
12. **duplicate write without replay_safe prevents conflict_free**.
13. **out-of-order write without deterministic ordering prevents conflict_free**.
14. **mutation_uncertainty prevents conflict_free_authoritative**.
15. **explicit_conflict_unresolved always wins** regardless of other flags.
16. **Policy sentinels are importable and non-empty**.
17. **to_dict() / from_dict() round-trip** produces valid output.
18. **build_baseline_mutation_conflict_verdict()** returns conflict_unresolved.
19. **SystemFinalAcceptanceEvaluator includes concurrent_mutation_conflict**.
20. **AcceptanceDimensionId.all_dimensions() includes concurrent_mutation_conflict**.

Test groups
-----------
 A)  Sentinel imports — PR-13 authority and policy constants importable.
 B)  Enum completeness — all five MutationConflictClass values exist.
 C)  Enum completeness — WriterConcurrencyMode values exist.
 D)  conflict_free_authoritative — all conditions met, no negatives.
 E)  conflict_free_authoritative — requires single_writer_confirmed.
 F)  conflict_free_authoritative — requires no_concurrent_mutations.
 G)  conflict_free_authoritative — requires write_order_deterministic.
 H)  conflict_free_authoritative — requires replay_safe.
 I)  conflict_free_authoritative — blocked by last_writer_wins_applied.
 J)  conflict_free_authoritative — blocked by concurrent_writers_detected.
 K)  conflict_free_authoritative — blocked by mutation_uncertainty.
 L)  conflict_free_authoritative — blocked by conflict_acknowledged.
 M)  deterministically_merged — full merge conditions met.
 N)  deterministically_merged — requires deterministic_merge_applied.
 O)  deterministically_merged — requires merge_function_idempotent.
 P)  deterministically_merged — requires all_conflicts_resolved.
 Q)  last_writer_won_non_authoritative — last_writer_wins_applied=True.
 R)  last_writer_won_non_authoritative — takes priority over degraded signals.
 S)  reconciliation_required — initiated but not complete.
 T)  reconciliation_required — blocks authoritative classes.
 U)  conflict_unresolved — explicit_conflict_unresolved=True.
 V)  conflict_unresolved — conflict_acknowledged + conflict_resolution_absent.
 W)  conflict_unresolved — zero evidence (fail-conservative baseline).
 X)  explicit_conflict_unresolved overrides last_writer_wins.
 Y)  explicit_conflict_unresolved overrides deterministic_merge.
 Z)  duplicate write without replay_safe → not conflict_free_authoritative.
 AA) out-of-order write without deterministic ordering → not conflict_free.
 AB) duplicate write WITH replay_safe AND deterministic → allowed conflict_free.
 AC) MutationConflictEvidence to_dict / from_dict round-trip.
 AD) MutationConflictVerdict to_dict / from_dict round-trip.
 AE) is_conflict_free_authoritative flag — only True for that class.
 AF) is_deterministically_merged flag — True for deterministically_merged only.
 AG) is_last_writer_won flag — True for last_writer_won_non_authoritative only.
 AH) is_reconciliation_required flag — True for reconciliation_required only.
 AI) is_conflict_unresolved flag — True for conflict_unresolved only.
 AJ) downgrade_reasons is non-empty when a downgrade occurred.
 AK) build_baseline_mutation_conflict_verdict() returns conflict_unresolved.
 AL) SystemFinalAcceptanceEvaluator includes concurrent_mutation_conflict.
 AM) AcceptanceDimensionId.all_dimensions() includes concurrent_mutation_conflict.
 AN) Probe returns pending when zero-evidence correctly returns conflict_unresolved.
 AO) Probe returns unresolved when zero-evidence returns conflict_free_authoritative
     (misconfiguration guard).
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Import guard — skip gracefully if module is unavailable
# ---------------------------------------------------------------------------

_MODULE_AVAILABLE = False
try:
    from core.concurrent_mutation_conflict_contract import (
        # Authority / policy sentinels
        CONCURRENT_MUTATION_CONFLICT_CONTRACT_AUTHORITY,
        CONCURRENT_MUTATION_CONFLICT_CONTRACT_PR13_SENTINEL,
        MUTATION_CONFLICT_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY,
        LAST_WRITER_WINS_MUST_NOT_CLAIM_AUTHORITATIVE_POLICY,
        RECONCILIATION_INCOMPLETE_BLOCKS_AUTHORITATIVE_MUTATION_POLICY,
        DUPLICATE_WRITE_MUST_NOT_CLAIM_CONFLICT_FREE_POLICY,
        OUT_OF_ORDER_WRITE_MUST_NOT_CLAIM_CONFLICT_FREE_POLICY,
        MUTATION_ABSENCE_DEFAULTS_TO_CONFLICT_UNRESOLVED_POLICY,
        WRITE_SUCCESS_MUST_NOT_IMPLY_CONCURRENT_SEMANTICS_POLICY,
        # Enumerations
        MutationConflictClass,
        WriterConcurrencyMode,
        # Data classes
        MutationConflictEvidence,
        MutationConflictVerdict,
        # Functions
        classify_mutation_conflict,
        build_mutation_conflict_verdict,
        build_baseline_mutation_conflict_verdict,
    )
    _MODULE_AVAILABLE = True
except ImportError as _imp_err:
    print(
        f"SKIP: core.concurrent_mutation_conflict_contract unavailable: {_imp_err}"
    )


def _skip_if_unavailable(test_fn):
    """Decorator: skip test if the module is not available."""
    def wrapper(self):
        if not _MODULE_AVAILABLE:
            self.skipTest(
                "core.concurrent_mutation_conflict_contract not available"
            )
        return test_fn(self)
    wrapper.__name__ = test_fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# Helper: build evidence with named overrides
# ---------------------------------------------------------------------------

def _ev(**kwargs) -> "MutationConflictEvidence":
    """Build a MutationConflictEvidence with default-conservative values."""
    return MutationConflictEvidence(
        single_writer_confirmed=kwargs.get("single_writer_confirmed", False),
        no_concurrent_mutations=kwargs.get("no_concurrent_mutations", False),
        write_order_deterministic=kwargs.get("write_order_deterministic", False),
        replay_safe=kwargs.get("replay_safe", False),
        deterministic_merge_applied=kwargs.get("deterministic_merge_applied", False),
        merge_function_idempotent=kwargs.get("merge_function_idempotent", False),
        all_conflicts_resolved=kwargs.get("all_conflicts_resolved", False),
        last_writer_wins_applied=kwargs.get("last_writer_wins_applied", False),
        concurrent_writers_detected=kwargs.get("concurrent_writers_detected", False),
        duplicate_write_detected=kwargs.get("duplicate_write_detected", False),
        out_of_order_write_detected=kwargs.get("out_of_order_write_detected", False),
        reconciliation_initiated=kwargs.get("reconciliation_initiated", False),
        reconciliation_complete=kwargs.get("reconciliation_complete", False),
        conflict_acknowledged=kwargs.get("conflict_acknowledged", False),
        conflict_resolution_absent=kwargs.get("conflict_resolution_absent", False),
        mutation_uncertainty=kwargs.get("mutation_uncertainty", False),
        explicit_conflict_unresolved=kwargs.get("explicit_conflict_unresolved", False),
        participant_id=kwargs.get("participant_id"),
        trace_id=kwargs.get("trace_id"),
    )


def _ev_conflict_free() -> "MutationConflictEvidence":
    """Build a fully conflict-free single-writer evidence."""
    return MutationConflictEvidence(
        single_writer_confirmed=True,
        no_concurrent_mutations=True,
        write_order_deterministic=True,
        replay_safe=True,
        deterministic_merge_applied=False,
        merge_function_idempotent=False,
        all_conflicts_resolved=False,
        last_writer_wins_applied=False,
        concurrent_writers_detected=False,
        duplicate_write_detected=False,
        out_of_order_write_detected=False,
        reconciliation_initiated=False,
        reconciliation_complete=False,
        conflict_acknowledged=False,
        conflict_resolution_absent=False,
        mutation_uncertainty=False,
        explicit_conflict_unresolved=False,
    )


def _ev_deterministic_merge() -> "MutationConflictEvidence":
    """Build a deterministically-merged evidence."""
    return MutationConflictEvidence(
        single_writer_confirmed=False,
        no_concurrent_mutations=False,
        write_order_deterministic=True,
        replay_safe=False,
        deterministic_merge_applied=True,
        merge_function_idempotent=True,
        all_conflicts_resolved=True,
        last_writer_wins_applied=False,
        concurrent_writers_detected=True,  # concurrent exists, but resolved
        duplicate_write_detected=False,
        out_of_order_write_detected=False,
        reconciliation_initiated=False,
        reconciliation_complete=False,
        conflict_acknowledged=False,
        conflict_resolution_absent=False,
        mutation_uncertainty=False,
        explicit_conflict_unresolved=False,
    )


# ===========================================================================
# Test class
# ===========================================================================


class TestConcurrentMutationConflictContract(unittest.TestCase):

    # -----------------------------------------------------------------------
    # Group A — Sentinel imports
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_A01_authority_sentinel_importable_and_nonempty(self):
        self.assertIsInstance(
            CONCURRENT_MUTATION_CONFLICT_CONTRACT_AUTHORITY, str
        )
        self.assertGreater(
            len(CONCURRENT_MUTATION_CONFLICT_CONTRACT_AUTHORITY), 0
        )

    @_skip_if_unavailable
    def test_A02_pr13_sentinel_importable_and_nonempty(self):
        self.assertIsInstance(
            CONCURRENT_MUTATION_CONFLICT_CONTRACT_PR13_SENTINEL, str
        )
        self.assertIn(
            "PR13", CONCURRENT_MUTATION_CONFLICT_CONTRACT_PR13_SENTINEL
        )

    @_skip_if_unavailable
    def test_A03_policy_sentinels_are_nonempty_strings(self):
        for sentinel in [
            MUTATION_CONFLICT_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY,
            LAST_WRITER_WINS_MUST_NOT_CLAIM_AUTHORITATIVE_POLICY,
            RECONCILIATION_INCOMPLETE_BLOCKS_AUTHORITATIVE_MUTATION_POLICY,
            DUPLICATE_WRITE_MUST_NOT_CLAIM_CONFLICT_FREE_POLICY,
            OUT_OF_ORDER_WRITE_MUST_NOT_CLAIM_CONFLICT_FREE_POLICY,
            MUTATION_ABSENCE_DEFAULTS_TO_CONFLICT_UNRESOLVED_POLICY,
            WRITE_SUCCESS_MUST_NOT_IMPLY_CONCURRENT_SEMANTICS_POLICY,
        ]:
            self.assertIsInstance(sentinel, str)
            self.assertGreater(len(sentinel), 0)

    # -----------------------------------------------------------------------
    # Group B — MutationConflictClass enum completeness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_B01_five_mutation_conflict_classes_exist(self):
        values = {c.value for c in MutationConflictClass}
        self.assertIn("conflict_free_authoritative", values)
        self.assertIn("deterministically_merged", values)
        self.assertIn("last_writer_won_non_authoritative", values)
        self.assertIn("reconciliation_required", values)
        self.assertIn("conflict_unresolved", values)
        self.assertEqual(len(values), 5)

    @_skip_if_unavailable
    def test_B02_mutation_conflict_class_values_are_stable_strings(self):
        self.assertEqual(
            MutationConflictClass.conflict_free_authoritative.value,
            "conflict_free_authoritative",
        )
        self.assertEqual(
            MutationConflictClass.deterministically_merged.value,
            "deterministically_merged",
        )
        self.assertEqual(
            MutationConflictClass.last_writer_won_non_authoritative.value,
            "last_writer_won_non_authoritative",
        )
        self.assertEqual(
            MutationConflictClass.reconciliation_required.value,
            "reconciliation_required",
        )
        self.assertEqual(
            MutationConflictClass.conflict_unresolved.value,
            "conflict_unresolved",
        )

    # -----------------------------------------------------------------------
    # Group C — WriterConcurrencyMode enum completeness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_C01_writer_concurrency_mode_values_exist(self):
        values = {c.value for c in WriterConcurrencyMode}
        self.assertIn("single_writer", values)
        self.assertIn("serialised", values)
        self.assertIn("concurrent_detected", values)
        self.assertIn("replay_or_retry", values)
        self.assertIn("out_of_order", values)
        self.assertIn("unknown", values)

    # -----------------------------------------------------------------------
    # Group D — conflict_free_authoritative: all conditions met
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_D01_conflict_free_authoritative_all_conditions(self):
        evidence = _ev_conflict_free()
        verdict = classify_mutation_conflict(evidence)
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )
        self.assertTrue(verdict.is_conflict_free_authoritative)
        self.assertFalse(verdict.is_deterministically_merged)
        self.assertFalse(verdict.is_last_writer_won)
        self.assertFalse(verdict.is_reconciliation_required)
        self.assertFalse(verdict.is_conflict_unresolved)

    @_skip_if_unavailable
    def test_D02_conflict_free_authoritative_has_empty_downgrade_reasons(self):
        verdict = classify_mutation_conflict(_ev_conflict_free())
        self.assertEqual(verdict.downgrade_reasons, [])

    @_skip_if_unavailable
    def test_D03_conflict_free_authoritative_evidence_present_true(self):
        verdict = classify_mutation_conflict(_ev_conflict_free())
        self.assertTrue(verdict.evidence_present)

    # -----------------------------------------------------------------------
    # Group E — conflict_free_authoritative requires single_writer_confirmed
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_E01_missing_single_writer_confirmed_prevents_conflict_free(self):
        evidence = MutationConflictEvidence(
            single_writer_confirmed=False,  # missing
            no_concurrent_mutations=True,
            write_order_deterministic=True,
            replay_safe=True,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group F — conflict_free_authoritative requires no_concurrent_mutations
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_F01_missing_no_concurrent_mutations_prevents_conflict_free(self):
        evidence = MutationConflictEvidence(
            single_writer_confirmed=True,
            no_concurrent_mutations=False,  # missing
            write_order_deterministic=True,
            replay_safe=True,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group G — conflict_free_authoritative requires write_order_deterministic
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_G01_missing_write_order_deterministic_prevents_conflict_free(self):
        evidence = MutationConflictEvidence(
            single_writer_confirmed=True,
            no_concurrent_mutations=True,
            write_order_deterministic=False,  # missing
            replay_safe=True,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group H — conflict_free_authoritative requires replay_safe
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_H01_missing_replay_safe_prevents_conflict_free(self):
        evidence = MutationConflictEvidence(
            single_writer_confirmed=True,
            no_concurrent_mutations=True,
            write_order_deterministic=True,
            replay_safe=False,  # missing
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group I — conflict_free_authoritative blocked by last_writer_wins_applied
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_I01_last_writer_wins_blocks_conflict_free(self):
        evidence = MutationConflictEvidence(
            single_writer_confirmed=True,
            no_concurrent_mutations=True,
            write_order_deterministic=True,
            replay_safe=True,
            last_writer_wins_applied=True,  # blocks conflict_free
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.deterministically_merged,
        )

    # -----------------------------------------------------------------------
    # Group J — conflict_free_authoritative blocked by concurrent_writers_detected
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_J01_concurrent_writers_blocks_conflict_free(self):
        evidence = MutationConflictEvidence(
            single_writer_confirmed=True,
            no_concurrent_mutations=True,
            write_order_deterministic=True,
            replay_safe=True,
            concurrent_writers_detected=True,  # blocks conflict_free
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group K — conflict_free blocked by mutation_uncertainty
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_K01_mutation_uncertainty_blocks_conflict_free(self):
        evidence = MutationConflictEvidence(
            single_writer_confirmed=True,
            no_concurrent_mutations=True,
            write_order_deterministic=True,
            replay_safe=True,
            mutation_uncertainty=True,  # blocks conflict_free
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group L — conflict_free blocked by conflict_acknowledged
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_L01_conflict_acknowledged_blocks_conflict_free(self):
        evidence = MutationConflictEvidence(
            single_writer_confirmed=True,
            no_concurrent_mutations=True,
            write_order_deterministic=True,
            replay_safe=True,
            conflict_acknowledged=True,  # blocks conflict_free
            conflict_resolution_absent=True,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group M — deterministically_merged: full conditions
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_M01_deterministically_merged_full_conditions(self):
        evidence = _ev_deterministic_merge()
        verdict = classify_mutation_conflict(evidence)
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.deterministically_merged,
        )
        self.assertTrue(verdict.is_deterministically_merged)
        self.assertFalse(verdict.is_conflict_free_authoritative)
        self.assertFalse(verdict.is_last_writer_won)
        self.assertFalse(verdict.is_reconciliation_required)
        self.assertFalse(verdict.is_conflict_unresolved)

    @_skip_if_unavailable
    def test_M02_deterministically_merged_has_empty_downgrade_reasons(self):
        verdict = classify_mutation_conflict(_ev_deterministic_merge())
        self.assertEqual(verdict.downgrade_reasons, [])

    # -----------------------------------------------------------------------
    # Group N — deterministically_merged requires deterministic_merge_applied
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_N01_missing_deterministic_merge_applied_prevents_merged(self):
        evidence = MutationConflictEvidence(
            deterministic_merge_applied=False,  # missing
            merge_function_idempotent=True,
            all_conflicts_resolved=True,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.deterministically_merged,
        )

    # -----------------------------------------------------------------------
    # Group O — deterministically_merged requires merge_function_idempotent
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_O01_missing_merge_function_idempotent_prevents_merged(self):
        evidence = MutationConflictEvidence(
            deterministic_merge_applied=True,
            merge_function_idempotent=False,  # missing
            all_conflicts_resolved=True,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.deterministically_merged,
        )

    # -----------------------------------------------------------------------
    # Group P — deterministically_merged requires all_conflicts_resolved
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_P01_missing_all_conflicts_resolved_prevents_merged(self):
        evidence = MutationConflictEvidence(
            deterministic_merge_applied=True,
            merge_function_idempotent=True,
            all_conflicts_resolved=False,  # missing
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.deterministically_merged,
        )

    # -----------------------------------------------------------------------
    # Group Q — last_writer_won_non_authoritative
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Q01_last_writer_wins_applied_gives_non_authoritative(self):
        evidence = _ev(last_writer_wins_applied=True)
        verdict = classify_mutation_conflict(evidence)
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.last_writer_won_non_authoritative,
        )
        self.assertTrue(verdict.is_last_writer_won)
        self.assertFalse(verdict.is_conflict_free_authoritative)
        self.assertFalse(verdict.is_deterministically_merged)

    @_skip_if_unavailable
    def test_Q02_last_writer_won_has_downgrade_reasons(self):
        evidence = _ev(last_writer_wins_applied=True)
        verdict = classify_mutation_conflict(evidence)
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    # -----------------------------------------------------------------------
    # Group R — last_writer_won takes priority over other conditions
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_R01_last_writer_wins_takes_priority_over_merge_conditions(self):
        # Even if merge conditions are met, last_writer_wins blocks it
        evidence = MutationConflictEvidence(
            last_writer_wins_applied=True,
            deterministic_merge_applied=True,
            merge_function_idempotent=True,
            all_conflicts_resolved=True,
        )
        verdict = classify_mutation_conflict(evidence)
        # last_writer_wins is checked before merge — gets non_authoritative
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.last_writer_won_non_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group S — reconciliation_required: initiated but not complete
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_S01_reconciliation_initiated_not_complete_gives_required(self):
        evidence = _ev(
            reconciliation_initiated=True,
            reconciliation_complete=False,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.reconciliation_required,
        )
        self.assertTrue(verdict.is_reconciliation_required)

    @_skip_if_unavailable
    def test_S02_reconciliation_complete_does_not_produce_required(self):
        # If reconciliation is both initiated AND complete, it should not
        # produce reconciliation_required.
        evidence = _ev(
            reconciliation_initiated=True,
            reconciliation_complete=True,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.reconciliation_required,
        )

    # -----------------------------------------------------------------------
    # Group T — reconciliation_required blocks authoritative classes
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_T01_reconciliation_required_blocks_conflict_free(self):
        evidence = MutationConflictEvidence(
            single_writer_confirmed=True,
            no_concurrent_mutations=True,
            write_order_deterministic=True,
            replay_safe=True,
            reconciliation_initiated=True,  # blocks authoritative
            reconciliation_complete=False,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.reconciliation_required,
        )

    @_skip_if_unavailable
    def test_T02_reconciliation_required_blocks_deterministically_merged(self):
        evidence = MutationConflictEvidence(
            deterministic_merge_applied=True,
            merge_function_idempotent=True,
            all_conflicts_resolved=True,
            reconciliation_initiated=True,  # blocks authoritative
            reconciliation_complete=False,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.reconciliation_required,
        )

    # -----------------------------------------------------------------------
    # Group U — conflict_unresolved: explicit_conflict_unresolved=True
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_U01_explicit_conflict_unresolved_gives_unresolved(self):
        evidence = _ev(explicit_conflict_unresolved=True)
        verdict = classify_mutation_conflict(evidence)
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_unresolved,
        )
        self.assertTrue(verdict.is_conflict_unresolved)

    # -----------------------------------------------------------------------
    # Group V — conflict_unresolved: acknowledged but no resolution
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_V01_conflict_acknowledged_and_resolution_absent_gives_unresolved(self):
        evidence = _ev(
            conflict_acknowledged=True,
            conflict_resolution_absent=True,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_unresolved,
        )
        self.assertTrue(verdict.is_conflict_unresolved)

    @_skip_if_unavailable
    def test_V02_conflict_acknowledged_without_resolution_absent_does_not_force_unresolved(self):
        # conflict_acknowledged alone (without conflict_resolution_absent)
        # should not force conflict_unresolved via Rule 2.
        # It will still block conflict_free_authoritative via Rule 6.
        evidence = _ev(conflict_acknowledged=True, conflict_resolution_absent=False)
        verdict = classify_mutation_conflict(evidence)
        # Rule 2 does NOT apply here; outcome is unresolved due to lack of
        # positive evidence (Rule 7) or some other conservative path — but
        # this should NOT be conflict_free_authoritative.
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group W — conflict_unresolved: zero evidence (fail-conservative)
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_W01_zero_evidence_gives_conflict_unresolved(self):
        evidence = MutationConflictEvidence()
        verdict = classify_mutation_conflict(evidence)
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_unresolved,
        )
        self.assertTrue(verdict.is_conflict_unresolved)
        self.assertFalse(verdict.is_conflict_free_authoritative)

    @_skip_if_unavailable
    def test_W02_zero_evidence_has_downgrade_reasons(self):
        verdict = classify_mutation_conflict(MutationConflictEvidence())
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    # -----------------------------------------------------------------------
    # Group X — explicit_conflict_unresolved overrides last_writer_wins
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_X01_explicit_unresolved_overrides_last_writer_wins(self):
        evidence = _ev(
            last_writer_wins_applied=True,
            explicit_conflict_unresolved=True,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_unresolved,
        )

    # -----------------------------------------------------------------------
    # Group Y — explicit_conflict_unresolved overrides deterministic merge
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Y01_explicit_unresolved_overrides_deterministic_merge(self):
        evidence = MutationConflictEvidence(
            deterministic_merge_applied=True,
            merge_function_idempotent=True,
            all_conflicts_resolved=True,
            explicit_conflict_unresolved=True,  # always wins
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_unresolved,
        )

    # -----------------------------------------------------------------------
    # Group Z — duplicate write without replay_safe
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Z01_duplicate_write_without_replay_safe_not_conflict_free(self):
        evidence = MutationConflictEvidence(
            single_writer_confirmed=True,
            no_concurrent_mutations=True,
            write_order_deterministic=True,
            replay_safe=False,  # not replay safe
            duplicate_write_detected=True,  # duplicate detected
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group AA — out-of-order write without deterministic ordering
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AA01_out_of_order_without_deterministic_ordering_not_conflict_free(self):
        evidence = MutationConflictEvidence(
            single_writer_confirmed=True,
            no_concurrent_mutations=True,
            write_order_deterministic=False,  # not deterministic
            replay_safe=True,
            out_of_order_write_detected=True,  # out-of-order
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group AB — duplicate write WITH replay_safe AND deterministic → allowed
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AB01_duplicate_write_with_replay_safe_can_be_conflict_free(self):
        # Duplicate detected but write is idempotent and ordering is
        # deterministic → conflict_free_authoritative is allowed.
        evidence = MutationConflictEvidence(
            single_writer_confirmed=True,
            no_concurrent_mutations=True,
            write_order_deterministic=True,
            replay_safe=True,
            duplicate_write_detected=True,  # duplicate, but OK because replay_safe
            last_writer_wins_applied=False,
            concurrent_writers_detected=False,
            out_of_order_write_detected=False,
            reconciliation_initiated=False,
            conflict_acknowledged=False,
            mutation_uncertainty=False,
            explicit_conflict_unresolved=False,
        )
        verdict = classify_mutation_conflict(evidence)
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group AC — MutationConflictEvidence to_dict / from_dict round-trip
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AC01_evidence_to_dict_from_dict_roundtrip(self):
        evidence = _ev_conflict_free()
        d = evidence.to_dict()
        self.assertIsInstance(d, dict)
        restored = MutationConflictEvidence.from_dict(d)
        self.assertEqual(
            restored.single_writer_confirmed, evidence.single_writer_confirmed
        )
        self.assertEqual(
            restored.no_concurrent_mutations, evidence.no_concurrent_mutations
        )
        self.assertEqual(
            restored.write_order_deterministic, evidence.write_order_deterministic
        )
        self.assertEqual(restored.replay_safe, evidence.replay_safe)
        self.assertEqual(
            restored.last_writer_wins_applied, evidence.last_writer_wins_applied
        )

    @_skip_if_unavailable
    def test_AC02_evidence_to_dict_contains_all_keys(self):
        evidence = MutationConflictEvidence()
        d = evidence.to_dict()
        for key in [
            "single_writer_confirmed",
            "no_concurrent_mutations",
            "write_order_deterministic",
            "replay_safe",
            "deterministic_merge_applied",
            "merge_function_idempotent",
            "all_conflicts_resolved",
            "last_writer_wins_applied",
            "concurrent_writers_detected",
            "duplicate_write_detected",
            "out_of_order_write_detected",
            "reconciliation_initiated",
            "reconciliation_complete",
            "conflict_acknowledged",
            "conflict_resolution_absent",
            "mutation_uncertainty",
            "explicit_conflict_unresolved",
            "concurrency_mode",
        ]:
            self.assertIn(key, d, f"Key '{key}' missing from to_dict()")

    # -----------------------------------------------------------------------
    # Group AD — MutationConflictVerdict to_dict / from_dict round-trip
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AD01_verdict_to_dict_from_dict_roundtrip(self):
        verdict = classify_mutation_conflict(_ev_conflict_free())
        d = verdict.to_dict()
        self.assertIsInstance(d, dict)
        restored = MutationConflictVerdict.from_dict(d)
        self.assertEqual(restored.mutation_class, verdict.mutation_class)
        self.assertEqual(
            restored.is_conflict_free_authoritative,
            verdict.is_conflict_free_authoritative,
        )
        self.assertIsInstance(restored.rationale, str)
        self.assertGreater(len(restored.rationale), 0)

    @_skip_if_unavailable
    def test_AD02_verdict_to_dict_contains_all_keys(self):
        verdict = classify_mutation_conflict(MutationConflictEvidence())
        d = verdict.to_dict()
        for key in [
            "mutation_class",
            "rationale",
            "downgrade_reasons",
            "is_conflict_free_authoritative",
            "is_deterministically_merged",
            "is_last_writer_won",
            "is_reconciliation_required",
            "is_conflict_unresolved",
            "evidence_present",
            "classified_at",
            "verdict_id",
        ]:
            self.assertIn(key, d, f"Key '{key}' missing from to_dict()")

    # -----------------------------------------------------------------------
    # Group AE — is_conflict_free_authoritative flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AE01_is_conflict_free_authoritative_only_for_that_class(self):
        for ev, expected_class in [
            (_ev_conflict_free(), MutationConflictClass.conflict_free_authoritative),
            (_ev_deterministic_merge(), MutationConflictClass.deterministically_merged),
            (
                _ev(last_writer_wins_applied=True),
                MutationConflictClass.last_writer_won_non_authoritative,
            ),
            (
                _ev(reconciliation_initiated=True, reconciliation_complete=False),
                MutationConflictClass.reconciliation_required,
            ),
            (MutationConflictEvidence(), MutationConflictClass.conflict_unresolved),
        ]:
            v = classify_mutation_conflict(ev)
            self.assertEqual(v.mutation_class, expected_class, msg=f"Class mismatch for {expected_class}")
            if expected_class == MutationConflictClass.conflict_free_authoritative:
                self.assertTrue(v.is_conflict_free_authoritative)
            else:
                self.assertFalse(v.is_conflict_free_authoritative)

    # -----------------------------------------------------------------------
    # Group AF — is_deterministically_merged flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AF01_is_deterministically_merged_only_for_that_class(self):
        v = classify_mutation_conflict(_ev_deterministic_merge())
        self.assertTrue(v.is_deterministically_merged)
        v2 = classify_mutation_conflict(_ev_conflict_free())
        self.assertFalse(v2.is_deterministically_merged)

    # -----------------------------------------------------------------------
    # Group AG — is_last_writer_won flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AG01_is_last_writer_won_only_for_that_class(self):
        v = classify_mutation_conflict(_ev(last_writer_wins_applied=True))
        self.assertTrue(v.is_last_writer_won)
        v2 = classify_mutation_conflict(_ev_conflict_free())
        self.assertFalse(v2.is_last_writer_won)

    # -----------------------------------------------------------------------
    # Group AH — is_reconciliation_required flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AH01_is_reconciliation_required_only_for_that_class(self):
        v = classify_mutation_conflict(
            _ev(reconciliation_initiated=True, reconciliation_complete=False)
        )
        self.assertTrue(v.is_reconciliation_required)
        v2 = classify_mutation_conflict(_ev_conflict_free())
        self.assertFalse(v2.is_reconciliation_required)

    # -----------------------------------------------------------------------
    # Group AI — is_conflict_unresolved flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AI01_is_conflict_unresolved_only_for_that_class(self):
        v = classify_mutation_conflict(MutationConflictEvidence())
        self.assertTrue(v.is_conflict_unresolved)
        v2 = classify_mutation_conflict(_ev_conflict_free())
        self.assertFalse(v2.is_conflict_unresolved)

    # -----------------------------------------------------------------------
    # Group AJ — downgrade_reasons non-empty when downgrade occurred
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AJ01_downgrade_reasons_nonempty_for_last_writer_won(self):
        v = classify_mutation_conflict(_ev(last_writer_wins_applied=True))
        self.assertGreater(len(v.downgrade_reasons), 0)

    @_skip_if_unavailable
    def test_AJ02_downgrade_reasons_nonempty_for_reconciliation_required(self):
        v = classify_mutation_conflict(
            _ev(reconciliation_initiated=True, reconciliation_complete=False)
        )
        self.assertGreater(len(v.downgrade_reasons), 0)

    @_skip_if_unavailable
    def test_AJ03_downgrade_reasons_nonempty_for_conflict_unresolved(self):
        v = classify_mutation_conflict(MutationConflictEvidence())
        self.assertGreater(len(v.downgrade_reasons), 0)

    # -----------------------------------------------------------------------
    # Group AK — build_baseline_mutation_conflict_verdict returns conflict_unresolved
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AK01_baseline_verdict_is_conflict_unresolved(self):
        verdict = build_baseline_mutation_conflict_verdict()
        self.assertEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_unresolved,
        )

    @_skip_if_unavailable
    def test_AK02_baseline_verdict_is_not_conflict_free_authoritative(self):
        verdict = build_baseline_mutation_conflict_verdict()
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
        )

    @_skip_if_unavailable
    def test_AK03_build_mutation_conflict_verdict_is_alias(self):
        evidence = _ev_conflict_free()
        v1 = classify_mutation_conflict(evidence)
        v2 = build_mutation_conflict_verdict(evidence)
        self.assertEqual(v1.mutation_class, v2.mutation_class)

    # -----------------------------------------------------------------------
    # Group AL — SystemFinalAcceptanceEvaluator includes dimension
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AL01_system_final_acceptance_evaluator_includes_concurrent_mutation(self):
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                AcceptanceDimensionId,
            )
        except ImportError:
            self.skipTest("core.system_final_acceptance_verdict not available")

        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        self.assertIn(
            "concurrent_mutation_conflict",
            report.checklist,
            "concurrent_mutation_conflict dimension missing from checklist",
        )

    @_skip_if_unavailable
    def test_AL02_concurrent_mutation_dimension_is_not_unresolved_when_contract_deployed(self):
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                DimensionStatus,
            )
        except ImportError:
            self.skipTest("core.system_final_acceptance_verdict not available")

        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        item = report.checklist.get("concurrent_mutation_conflict")
        self.assertIsNotNone(item)
        # Should be 'pending' (contract present, no live evidence) not 'unresolved'
        self.assertNotEqual(
            item.status,
            DimensionStatus.unresolved,
            "concurrent_mutation_conflict dimension is unresolved when contract "
            "should be deployable",
        )

    # -----------------------------------------------------------------------
    # Group AM — AcceptanceDimensionId.all_dimensions() includes dimension
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AM01_all_dimensions_includes_concurrent_mutation_conflict(self):
        try:
            from core.system_final_acceptance_verdict import AcceptanceDimensionId
        except ImportError:
            self.skipTest("core.system_final_acceptance_verdict not available")

        all_dims = AcceptanceDimensionId.all_dimensions()
        dim_values = [d.value for d in all_dims]
        self.assertIn("concurrent_mutation_conflict", dim_values)

    @_skip_if_unavailable
    def test_AM02_all_dimensions_has_sixteen_items(self):
        try:
            from core.system_final_acceptance_verdict import AcceptanceDimensionId
        except ImportError:
            self.skipTest("core.system_final_acceptance_verdict not available")

        all_dims = AcceptanceDimensionId.all_dimensions()
        self.assertEqual(
            len(all_dims),
            16,
            f"Expected 16 dimensions, got {len(all_dims)}: "
            f"{[d.value for d in all_dims]}",
        )

    # -----------------------------------------------------------------------
    # Group AN — Probe returns pending when zero-evidence returns conflict_unresolved
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AN01_probe_returns_pending_for_zero_evidence_conflict_unresolved(self):
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                DimensionStatus,
            )
        except ImportError:
            self.skipTest("core.system_final_acceptance_verdict not available")

        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        item = report.checklist.get("concurrent_mutation_conflict")
        self.assertIsNotNone(item)
        self.assertEqual(
            item.status,
            DimensionStatus.pending,
            "Expected 'pending' when contract is wired and zero-evidence returns "
            f"conflict_unresolved; got {item.status}",
        )

    # -----------------------------------------------------------------------
    # Group AO — Misconfiguration guard: zero-evidence must not return
    #             conflict_free_authoritative
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AO01_zero_evidence_must_not_return_conflict_free_authoritative(self):
        verdict = build_baseline_mutation_conflict_verdict()
        self.assertNotEqual(
            verdict.mutation_class,
            MutationConflictClass.conflict_free_authoritative,
            "MISCONFIGURATION: build_baseline_mutation_conflict_verdict() "
            "returned conflict_free_authoritative with zero evidence.  "
            "This violates MUTATION_ABSENCE_DEFAULTS_TO_CONFLICT_UNRESOLVED_POLICY "
            "and WRITE_SUCCESS_MUST_NOT_IMPLY_CONCURRENT_SEMANTICS_POLICY.",
        )


if __name__ == "__main__":
    unittest.main()
