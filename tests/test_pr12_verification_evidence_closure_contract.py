#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr12_verification_evidence_closure_contract.py
==========================================================
PR-12 — Verification / Evidence Closure Contract.

Validates that:

 1. **Closure taxonomy is defined and importable** (five classes).
 2. **Fully closed** classification when all evidence sources present,
    all checks passed, no open items, multiple source convergence.
 3. **Conditionally closed** when all checks passed and no open items but
    conditions are documented and bounded, or evidence sources incomplete.
 4. **Partially substantiated** when some evidence/checks confirmed but
    not all pass or open items remain.
 5. **Evidence present verification pending** when evidence exists but
    checks have not been executed.
 6. **Unverified** when no evidence source confirmed (fail-conservative).
 7. **Evidence presence must not claim fully_closed** — ever.
 8. **Partial verification must not produce conditional closure**.
 9. **Review passed without complete evidence must downgrade**.
10. **Open verification items block fully_closed and conditionally_closed**.
11. **Undocumented/unbounded conditions block conditionally_closed**.
12. **Multiple source convergence required for fully_closed**.
13. **Policy sentinels are importable and non-empty**.
14. **to_dict() / from_dict() round-trip** for evidence and verdict.
15. **build_baseline_verification_closure_verdict()** returns unverified.
16. **SystemFinalAcceptanceEvaluator includes verification_evidence_closure**.
17. **AcceptanceDimensionId.all_dimensions() includes verification_evidence_closure**.
18. **Probe returns pending with conservative baseline verdict**.

Test groups
-----------
 A)  Sentinel imports — PR-12 authority and policy constants importable.
 B)  Enum completeness — all five VerificationClosureClass values exist.
 C)  Enum completeness — EvidenceSourceStatus and VerificationCheckStatus values.
 D)  fully_closed — all required conditions satisfied.
 E)  fully_closed — requires all_evidence_sources_present.
 F)  fully_closed — requires multiple_source_convergence.
 G)  fully_closed — blocked by open verification items.
 H)  conditionally_closed — checks passed, conditions documented and bounded.
 I)  conditionally_closed — requires conditions_bounded (not just documented).
 J)  conditionally_closed — requires conditions_documented.
 K)  partially_substantiated — checks passed but evidence incomplete.
 L)  partially_substantiated — open items with checks passed.
 M)  partially_substantiated — review accepted but checks not all passed.
 N)  evidence_present_verification_pending — evidence present but checks not run.
 O)  evidence_present_verification_pending — checks run but not passed, no review.
 P)  unverified — zero evidence (fail-conservative baseline).
 Q)  unverified — explicit no-evidence signal.
 R)  VerificationClosureEvidence to_dict / from_dict round-trip.
 S)  VerificationClosureVerdict to_dict / from_dict round-trip.
 T)  is_fully_closed flag — only True for fully_closed.
 U)  is_closed flag — True for fully_closed and conditionally_closed only.
 V)  is_evidence_present flag — True for all except unverified.
 W)  downgrade_reasons non-empty when downgrade occurred.
 X)  build_baseline_verification_closure_verdict() returns unverified.
 Y)  VerificationClosureClass.rank ordering contract.
 Z)  VerificationClosureClass.from_string fallback to unverified on unknown.
 AA) SystemFinalAcceptanceEvaluator includes verification_evidence_closure.
 AB) AcceptanceDimensionId.all_dimensions() includes verification_evidence_closure.
 AC) AcceptanceDimensionId probe returns pending with conservative baseline.
 AD) Zero-evidence probe must not return fully_closed (misconfiguration guard).
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Import guard — skip gracefully if module is unavailable
# ---------------------------------------------------------------------------

_MODULE_AVAILABLE = False
try:
    from core.verification_evidence_closure_contract import (
        # Authority / policy sentinels
        VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_AUTHORITY,
        VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_PR12_SENTINEL,
        EVIDENCE_PRESENCE_IS_NOT_VERIFICATION_CLOSURE_POLICY,
        PARTIAL_VERIFICATION_IS_NOT_CONDITIONAL_CLOSURE_POLICY,
        REVIEW_PASSED_WITHOUT_COMPLETE_EVIDENCE_MUST_DOWNGRADE_POLICY,
        EVIDENCE_ABSENCE_DEFAULTS_TO_UNVERIFIED_POLICY,
        OPEN_VERIFICATION_ITEMS_BLOCK_FULLY_CLOSED_POLICY,
        UNDOCUMENTED_CONDITIONS_BLOCK_CONDITIONAL_CLOSURE_POLICY,
        MULTIPLE_SOURCE_CONVERGENCE_REQUIRED_FOR_FULLY_CLOSED_POLICY,
        # Enumerations
        VerificationClosureClass,
        EvidenceSourceStatus,
        VerificationCheckStatus,
        # Data classes
        VerificationClosureEvidence,
        VerificationClosureVerdict,
        # Functions
        classify_verification_closure,
        build_verification_closure_verdict,
        build_baseline_verification_closure_verdict,
    )
    _MODULE_AVAILABLE = True
except ImportError as _imp_err:
    print(
        f"SKIP: core.verification_evidence_closure_contract unavailable: {_imp_err}"
    )


def _skip_if_unavailable(test_fn):
    """Decorator: skip test if the module is not available."""
    def wrapper(self):
        if not _MODULE_AVAILABLE:
            self.skipTest(
                "core.verification_evidence_closure_contract not available"
            )
        return test_fn(self)
    wrapper.__name__ = test_fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# Helper: build evidence with named overrides
# ---------------------------------------------------------------------------

def _ev(**kwargs) -> "VerificationClosureEvidence":
    """Build VerificationClosureEvidence with fully conservative defaults."""
    return VerificationClosureEvidence(
        evidence_sources_confirmed=kwargs.get("evidence_sources_confirmed", False),
        all_evidence_sources_present=kwargs.get("all_evidence_sources_present", False),
        verification_checks_executed=kwargs.get("verification_checks_executed", False),
        verification_checks_passed=kwargs.get("verification_checks_passed", False),
        review_completed=kwargs.get("review_completed", False),
        review_accepted=kwargs.get("review_accepted", False),
        conditions_documented=kwargs.get("conditions_documented", False),
        conditions_bounded=kwargs.get("conditions_bounded", False),
        no_open_verification_items=kwargs.get("no_open_verification_items", False),
        multiple_source_convergence=kwargs.get("multiple_source_convergence", False),
        participant_id=kwargs.get("participant_id"),
        trace_id=kwargs.get("trace_id"),
    )


def _full_evidence(**overrides) -> "VerificationClosureEvidence":
    """Build fully-closed evidence with optional overrides."""
    defaults = dict(
        evidence_sources_confirmed=True,
        all_evidence_sources_present=True,
        verification_checks_executed=True,
        verification_checks_passed=True,
        review_completed=True,
        review_accepted=True,
        conditions_documented=False,
        conditions_bounded=False,
        no_open_verification_items=True,
        multiple_source_convergence=True,
    )
    defaults.update(overrides)
    return VerificationClosureEvidence(**defaults)


# ===========================================================================
# Test class
# ===========================================================================


class TestVerificationEvidenceClosureContract(unittest.TestCase):

    # -----------------------------------------------------------------------
    # Group A — Sentinel imports
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_A01_authority_sentinel_importable_and_nonempty(self):
        self.assertIsInstance(VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_AUTHORITY, str)
        self.assertGreater(len(VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_AUTHORITY), 0)

    @_skip_if_unavailable
    def test_A02_pr12_sentinel_contains_pr12(self):
        self.assertIsInstance(VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_PR12_SENTINEL, str)
        self.assertIn("PR12", VERIFICATION_EVIDENCE_CLOSURE_CONTRACT_PR12_SENTINEL)

    @_skip_if_unavailable
    def test_A03_policy_sentinels_are_nonempty_strings(self):
        for sentinel in [
            EVIDENCE_PRESENCE_IS_NOT_VERIFICATION_CLOSURE_POLICY,
            PARTIAL_VERIFICATION_IS_NOT_CONDITIONAL_CLOSURE_POLICY,
            REVIEW_PASSED_WITHOUT_COMPLETE_EVIDENCE_MUST_DOWNGRADE_POLICY,
            EVIDENCE_ABSENCE_DEFAULTS_TO_UNVERIFIED_POLICY,
            OPEN_VERIFICATION_ITEMS_BLOCK_FULLY_CLOSED_POLICY,
            UNDOCUMENTED_CONDITIONS_BLOCK_CONDITIONAL_CLOSURE_POLICY,
            MULTIPLE_SOURCE_CONVERGENCE_REQUIRED_FOR_FULLY_CLOSED_POLICY,
        ]:
            with self.subTest(sentinel=sentinel[:50]):
                self.assertIsInstance(sentinel, str)
                self.assertGreater(len(sentinel), 20)

    @_skip_if_unavailable
    def test_A04_evidence_presence_policy_references_verification_closure(self):
        self.assertIn(
            "verification",
            EVIDENCE_PRESENCE_IS_NOT_VERIFICATION_CLOSURE_POLICY.lower(),
        )

    @_skip_if_unavailable
    def test_A05_open_items_policy_references_fully_closed(self):
        self.assertIn(
            "fully_closed",
            OPEN_VERIFICATION_ITEMS_BLOCK_FULLY_CLOSED_POLICY,
        )

    @_skip_if_unavailable
    def test_A06_multiple_source_policy_references_fully_closed(self):
        self.assertIn(
            "fully_closed",
            MULTIPLE_SOURCE_CONVERGENCE_REQUIRED_FOR_FULLY_CLOSED_POLICY,
        )

    # -----------------------------------------------------------------------
    # Group B — VerificationClosureClass enum completeness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_B01_five_classes_exist(self):
        classes = [c.value for c in VerificationClosureClass]
        self.assertIn("fully_closed", classes)
        self.assertIn("conditionally_closed", classes)
        self.assertIn("partially_substantiated", classes)
        self.assertIn("evidence_present_verification_pending", classes)
        self.assertIn("unverified", classes)

    @_skip_if_unavailable
    def test_B02_exactly_five_classes(self):
        self.assertEqual(len(list(VerificationClosureClass)), 5)

    @_skip_if_unavailable
    def test_B03_class_values_are_strings(self):
        for cls in VerificationClosureClass:
            self.assertIsInstance(cls.value, str)

    @_skip_if_unavailable
    def test_B04_fully_closed_is_str_enum_member(self):
        self.assertIsInstance(VerificationClosureClass.fully_closed, str)

    @_skip_if_unavailable
    def test_B05_unverified_is_str_enum_member(self):
        self.assertIsInstance(VerificationClosureClass.unverified, str)

    # -----------------------------------------------------------------------
    # Group C — EvidenceSourceStatus and VerificationCheckStatus completeness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_C01_evidence_source_status_values_exist(self):
        statuses = [s.value for s in EvidenceSourceStatus]
        self.assertIn("confirmed", statuses)
        self.assertIn("present_unconfirmed", statuses)
        self.assertIn("absent", statuses)
        self.assertIn("stale", statuses)
        self.assertIn("conflicting", statuses)
        self.assertIn("unknown", statuses)

    @_skip_if_unavailable
    def test_C02_verification_check_status_values_exist(self):
        statuses = [s.value for s in VerificationCheckStatus]
        self.assertIn("passed", statuses)
        self.assertIn("failed", statuses)
        self.assertIn("not_executed", statuses)
        self.assertIn("skipped_with_justification", statuses)
        self.assertIn("error", statuses)

    # -----------------------------------------------------------------------
    # Group D — fully_closed classification
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_D01_full_evidence_produces_fully_closed(self):
        verdict = classify_verification_closure(_full_evidence())
        self.assertEqual(
            verdict.closure_class, VerificationClosureClass.fully_closed
        )

    @_skip_if_unavailable
    def test_D02_fully_closed_sets_is_fully_closed_true(self):
        verdict = classify_verification_closure(_full_evidence())
        self.assertTrue(verdict.is_fully_closed)

    @_skip_if_unavailable
    def test_D03_fully_closed_sets_is_closed_true(self):
        verdict = classify_verification_closure(_full_evidence())
        self.assertTrue(verdict.is_closed)

    @_skip_if_unavailable
    def test_D04_fully_closed_sets_is_evidence_present_true(self):
        verdict = classify_verification_closure(_full_evidence())
        self.assertTrue(verdict.is_evidence_present)

    @_skip_if_unavailable
    def test_D05_fully_closed_downgrade_reasons_empty(self):
        verdict = classify_verification_closure(_full_evidence())
        self.assertEqual(verdict.downgrade_reasons, [])

    @_skip_if_unavailable
    def test_D06_fully_closed_rationale_is_nonempty(self):
        verdict = classify_verification_closure(_full_evidence())
        self.assertGreater(len(verdict.rationale), 0)

    # -----------------------------------------------------------------------
    # Group E — fully_closed requires all_evidence_sources_present
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_E01_missing_all_evidence_sources_blocks_fully_closed(self):
        evidence = _full_evidence(all_evidence_sources_present=False)
        verdict = classify_verification_closure(evidence)
        self.assertNotEqual(
            verdict.closure_class, VerificationClosureClass.fully_closed
        )

    @_skip_if_unavailable
    def test_E02_missing_all_sources_with_conditions_gives_conditionally_closed(self):
        evidence = _full_evidence(
            all_evidence_sources_present=False,
            conditions_documented=True,
            conditions_bounded=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertEqual(
            verdict.closure_class, VerificationClosureClass.conditionally_closed
        )

    @_skip_if_unavailable
    def test_E03_missing_all_sources_no_conditions_gives_partially_substantiated(self):
        evidence = _full_evidence(
            all_evidence_sources_present=False,
            multiple_source_convergence=True,
            conditions_documented=False,
        )
        verdict = classify_verification_closure(evidence)
        self.assertEqual(
            verdict.closure_class, VerificationClosureClass.partially_substantiated
        )

    # -----------------------------------------------------------------------
    # Group F — fully_closed requires multiple_source_convergence
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_F01_no_multiple_source_convergence_blocks_fully_closed(self):
        evidence = _full_evidence(multiple_source_convergence=False)
        verdict = classify_verification_closure(evidence)
        self.assertNotEqual(
            verdict.closure_class, VerificationClosureClass.fully_closed
        )

    @_skip_if_unavailable
    def test_F02_no_convergence_with_conditions_gives_conditionally_closed(self):
        evidence = _full_evidence(
            multiple_source_convergence=False,
            conditions_documented=True,
            conditions_bounded=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertEqual(
            verdict.closure_class, VerificationClosureClass.conditionally_closed
        )

    @_skip_if_unavailable
    def test_F03_no_convergence_downgrade_reason_mentions_convergence(self):
        evidence = _full_evidence(multiple_source_convergence=False)
        verdict = classify_verification_closure(evidence)
        reasons_text = " ".join(verdict.downgrade_reasons)
        self.assertIn("multiple_source_convergence", reasons_text)

    # -----------------------------------------------------------------------
    # Group G — open verification items block fully_closed and conditionally_closed
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_G01_open_items_block_fully_closed(self):
        evidence = _full_evidence(no_open_verification_items=False)
        verdict = classify_verification_closure(evidence)
        self.assertNotEqual(
            verdict.closure_class, VerificationClosureClass.fully_closed
        )

    @_skip_if_unavailable
    def test_G02_open_items_block_conditionally_closed(self):
        evidence = _full_evidence(
            no_open_verification_items=False,
            conditions_documented=True,
            conditions_bounded=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertNotEqual(
            verdict.closure_class, VerificationClosureClass.conditionally_closed
        )

    @_skip_if_unavailable
    def test_G03_open_items_produce_partially_substantiated(self):
        evidence = _full_evidence(no_open_verification_items=False)
        verdict = classify_verification_closure(evidence)
        self.assertEqual(
            verdict.closure_class, VerificationClosureClass.partially_substantiated
        )

    @_skip_if_unavailable
    def test_G04_open_items_downgrade_reason_mentions_open_items(self):
        evidence = _full_evidence(no_open_verification_items=False)
        verdict = classify_verification_closure(evidence)
        reasons_text = " ".join(verdict.downgrade_reasons)
        self.assertIn("no_open_verification_items", reasons_text)

    @_skip_if_unavailable
    def test_G05_open_items_is_not_closed(self):
        evidence = _full_evidence(no_open_verification_items=False)
        verdict = classify_verification_closure(evidence)
        self.assertFalse(verdict.is_closed)

    # -----------------------------------------------------------------------
    # Group H — conditionally_closed
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_H01_conditioned_checks_gives_conditionally_closed(self):
        # All checks passed, no open items, but conditions documented & bounded
        # (and not all evidence sources present / no multi-source convergence)
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=True,
            no_open_verification_items=True,
            conditions_documented=True,
            conditions_bounded=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertEqual(
            verdict.closure_class, VerificationClosureClass.conditionally_closed
        )

    @_skip_if_unavailable
    def test_H02_conditionally_closed_is_closed_true(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=True,
            no_open_verification_items=True,
            conditions_documented=True,
            conditions_bounded=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertTrue(verdict.is_closed)

    @_skip_if_unavailable
    def test_H03_conditionally_closed_is_not_fully_closed(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=True,
            no_open_verification_items=True,
            conditions_documented=True,
            conditions_bounded=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertFalse(verdict.is_fully_closed)

    # -----------------------------------------------------------------------
    # Group I — conditionally_closed requires conditions_bounded
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_I01_documented_but_unbounded_conditions_block_conditionally_closed(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=True,
            no_open_verification_items=True,
            conditions_documented=True,
            conditions_bounded=False,  # not bounded
        )
        verdict = classify_verification_closure(evidence)
        self.assertNotEqual(
            verdict.closure_class, VerificationClosureClass.conditionally_closed
        )

    @_skip_if_unavailable
    def test_I02_unbounded_conditions_produce_partially_substantiated(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=True,
            no_open_verification_items=True,
            conditions_documented=True,
            conditions_bounded=False,
        )
        verdict = classify_verification_closure(evidence)
        self.assertEqual(
            verdict.closure_class, VerificationClosureClass.partially_substantiated
        )

    # -----------------------------------------------------------------------
    # Group J — conditionally_closed requires conditions_documented
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_J01_bounded_but_undocumented_conditions_block_conditionally_closed(self):
        # conditions_bounded without conditions_documented doesn't help
        evidence = _ev(
            evidence_sources_confirmed=True,
            all_evidence_sources_present=False,  # needs conditions
            verification_checks_executed=True,
            verification_checks_passed=True,
            no_open_verification_items=True,
            conditions_documented=False,
            conditions_bounded=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertNotEqual(
            verdict.closure_class, VerificationClosureClass.conditionally_closed
        )

    # -----------------------------------------------------------------------
    # Group K — partially_substantiated
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_K01_evidence_and_checks_passed_no_full_evidence_gives_partial(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=True,
            no_open_verification_items=True,
            # not all sources present, no convergence, no conditions
        )
        verdict = classify_verification_closure(evidence)
        self.assertEqual(
            verdict.closure_class, VerificationClosureClass.partially_substantiated
        )

    @_skip_if_unavailable
    def test_K02_partially_substantiated_is_not_closed(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=True,
            no_open_verification_items=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertFalse(verdict.is_closed)

    @_skip_if_unavailable
    def test_K03_partially_substantiated_is_evidence_present(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=True,
            no_open_verification_items=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertTrue(verdict.is_evidence_present)

    # -----------------------------------------------------------------------
    # Group L — open items with checks passed → partially_substantiated
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_L01_checks_passed_with_open_items_gives_partially_substantiated(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            all_evidence_sources_present=True,
            verification_checks_executed=True,
            verification_checks_passed=True,
            multiple_source_convergence=True,
            no_open_verification_items=False,  # open items remain
        )
        verdict = classify_verification_closure(evidence)
        self.assertEqual(
            verdict.closure_class, VerificationClosureClass.partially_substantiated
        )

    # -----------------------------------------------------------------------
    # Group M — review accepted but checks not passed → partially_substantiated
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_M01_review_accepted_but_checks_not_passed_gives_partially_substantiated(self):
        """REVIEW_PASSED_WITHOUT_COMPLETE_EVIDENCE_MUST_DOWNGRADE_POLICY."""
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=False,  # checks not all passed
            review_completed=True,
            review_accepted=True,  # review accepted, but checks failed
        )
        verdict = classify_verification_closure(evidence)
        self.assertEqual(
            verdict.closure_class, VerificationClosureClass.partially_substantiated
        )

    @_skip_if_unavailable
    def test_M02_review_accepted_but_checks_not_passed_is_not_closed(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=False,
            review_completed=True,
            review_accepted=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertFalse(verdict.is_closed)

    @_skip_if_unavailable
    def test_M03_review_accepted_without_checks_not_pending(self):
        """Review accepted but checks not even executed: pending."""
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=False,  # not run at all
            review_completed=True,
            review_accepted=True,
        )
        verdict = classify_verification_closure(evidence)
        # Checks not executed → evidence_present_verification_pending
        self.assertEqual(
            verdict.closure_class,
            VerificationClosureClass.evidence_present_verification_pending,
        )

    # -----------------------------------------------------------------------
    # Group N — evidence_present_verification_pending
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_N01_evidence_present_but_checks_not_run_gives_pending(self):
        """EVIDENCE_PRESENCE_IS_NOT_VERIFICATION_CLOSURE_POLICY."""
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=False,
        )
        verdict = classify_verification_closure(evidence)
        self.assertEqual(
            verdict.closure_class,
            VerificationClosureClass.evidence_present_verification_pending,
        )

    @_skip_if_unavailable
    def test_N02_evidence_pending_is_evidence_present(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=False,
        )
        verdict = classify_verification_closure(evidence)
        self.assertTrue(verdict.is_evidence_present)

    @_skip_if_unavailable
    def test_N03_evidence_pending_is_not_closed(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=False,
        )
        verdict = classify_verification_closure(evidence)
        self.assertFalse(verdict.is_closed)

    @_skip_if_unavailable
    def test_N04_evidence_pending_is_not_fully_closed(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=False,
        )
        verdict = classify_verification_closure(evidence)
        self.assertFalse(verdict.is_fully_closed)

    # -----------------------------------------------------------------------
    # Group O — evidence_present_verification_pending when checks run but fail
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_O01_checks_executed_but_failed_with_no_review_gives_pending(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=False,
            review_completed=False,
            review_accepted=False,
        )
        verdict = classify_verification_closure(evidence)
        self.assertEqual(
            verdict.closure_class,
            VerificationClosureClass.evidence_present_verification_pending,
        )

    @_skip_if_unavailable
    def test_O02_checks_failed_no_review_is_not_closed(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=False,
        )
        verdict = classify_verification_closure(evidence)
        self.assertFalse(verdict.is_closed)

    # -----------------------------------------------------------------------
    # Group P — unverified (zero evidence)
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_P01_zero_evidence_gives_unverified(self):
        """EVIDENCE_ABSENCE_DEFAULTS_TO_UNVERIFIED_POLICY."""
        evidence = _ev()  # all False defaults
        verdict = classify_verification_closure(evidence)
        self.assertEqual(verdict.closure_class, VerificationClosureClass.unverified)

    @_skip_if_unavailable
    def test_P02_unverified_is_not_evidence_present(self):
        verdict = classify_verification_closure(_ev())
        self.assertFalse(verdict.is_evidence_present)

    @_skip_if_unavailable
    def test_P03_unverified_is_not_closed(self):
        verdict = classify_verification_closure(_ev())
        self.assertFalse(verdict.is_closed)

    @_skip_if_unavailable
    def test_P04_unverified_is_not_fully_closed(self):
        verdict = classify_verification_closure(_ev())
        self.assertFalse(verdict.is_fully_closed)

    @_skip_if_unavailable
    def test_P05_unverified_downgrade_reasons_nonempty(self):
        verdict = classify_verification_closure(_ev())
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    # -----------------------------------------------------------------------
    # Group Q — unverified with explicit no-evidence flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Q01_all_false_evidence_sources_gives_unverified(self):
        evidence = _ev(evidence_sources_confirmed=False)
        verdict = classify_verification_closure(evidence)
        self.assertEqual(verdict.closure_class, VerificationClosureClass.unverified)

    @_skip_if_unavailable
    def test_Q02_checks_passed_but_no_evidence_source_gives_unverified(self):
        """Checks cannot pass meaningfully without any confirmed evidence source."""
        evidence = _ev(
            evidence_sources_confirmed=False,
            verification_checks_executed=True,
            verification_checks_passed=True,
        )
        verdict = classify_verification_closure(evidence)
        # Rule 0: no confirmed source → unverified regardless
        self.assertEqual(verdict.closure_class, VerificationClosureClass.unverified)

    # -----------------------------------------------------------------------
    # Group R — VerificationClosureEvidence to_dict / from_dict round-trip
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_R01_to_dict_contains_all_expected_keys(self):
        evidence = _ev(evidence_sources_confirmed=True, participant_id="p1")
        d = evidence.to_dict()
        expected_keys = {
            "evidence_sources_confirmed",
            "all_evidence_sources_present",
            "verification_checks_executed",
            "verification_checks_passed",
            "review_completed",
            "review_accepted",
            "conditions_documented",
            "conditions_bounded",
            "no_open_verification_items",
            "multiple_source_convergence",
            "participant_id",
            "trace_id",
            "extra_context",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    @_skip_if_unavailable
    def test_R02_from_dict_round_trips_evidence_sources_confirmed(self):
        evidence = _ev(evidence_sources_confirmed=True)
        rt = VerificationClosureEvidence.from_dict(evidence.to_dict())
        self.assertEqual(rt.evidence_sources_confirmed, True)

    @_skip_if_unavailable
    def test_R03_from_dict_round_trips_verification_checks_passed(self):
        evidence = _ev(verification_checks_passed=True)
        rt = VerificationClosureEvidence.from_dict(evidence.to_dict())
        self.assertEqual(rt.verification_checks_passed, True)

    @_skip_if_unavailable
    def test_R04_from_dict_round_trips_conditions_bounded(self):
        evidence = _ev(conditions_bounded=True)
        rt = VerificationClosureEvidence.from_dict(evidence.to_dict())
        self.assertEqual(rt.conditions_bounded, True)

    @_skip_if_unavailable
    def test_R05_from_dict_round_trips_multiple_source_convergence(self):
        evidence = _ev(multiple_source_convergence=True)
        rt = VerificationClosureEvidence.from_dict(evidence.to_dict())
        self.assertEqual(rt.multiple_source_convergence, True)

    @_skip_if_unavailable
    def test_R06_from_dict_defaults_evidence_sources_confirmed_false_when_absent(self):
        rt = VerificationClosureEvidence.from_dict({})
        self.assertFalse(rt.evidence_sources_confirmed)

    @_skip_if_unavailable
    def test_R07_to_dict_is_json_serializable(self):
        evidence = _full_evidence()
        json_str = json.dumps(evidence.to_dict())
        self.assertIsInstance(json_str, str)

    # -----------------------------------------------------------------------
    # Group S — VerificationClosureVerdict to_dict / from_dict round-trip
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_S01_verdict_to_dict_contains_closure_class(self):
        verdict = classify_verification_closure(_ev())
        d = verdict.to_dict()
        self.assertIn("closure_class", d)

    @_skip_if_unavailable
    def test_S02_verdict_to_dict_contains_is_fully_closed(self):
        verdict = classify_verification_closure(_ev())
        d = verdict.to_dict()
        self.assertIn("is_fully_closed", d)

    @_skip_if_unavailable
    def test_S03_verdict_to_dict_contains_is_closed(self):
        verdict = classify_verification_closure(_ev())
        d = verdict.to_dict()
        self.assertIn("is_closed", d)

    @_skip_if_unavailable
    def test_S04_verdict_to_dict_contains_downgrade_reasons(self):
        verdict = classify_verification_closure(_ev())
        d = verdict.to_dict()
        self.assertIn("downgrade_reasons", d)

    @_skip_if_unavailable
    def test_S05_verdict_from_dict_round_trips_closure_class(self):
        verdict = classify_verification_closure(_full_evidence())
        rt = VerificationClosureVerdict.from_dict(verdict.to_dict())
        self.assertEqual(rt.closure_class, verdict.closure_class)

    @_skip_if_unavailable
    def test_S06_verdict_from_dict_unknown_class_falls_back_to_unverified(self):
        d = {"closure_class": "nonexistent_class", "rationale": "test"}
        rt = VerificationClosureVerdict.from_dict(d)
        self.assertEqual(rt.closure_class, VerificationClosureClass.unverified)

    @_skip_if_unavailable
    def test_S07_verdict_to_dict_is_json_serializable(self):
        verdict = classify_verification_closure(_full_evidence())
        json_str = json.dumps(verdict.to_dict())
        self.assertIsInstance(json_str, str)

    # -----------------------------------------------------------------------
    # Group T — is_fully_closed flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_T01_is_fully_closed_true_only_for_fully_closed_class(self):
        for evidence, expected_fully_closed in [
            (_full_evidence(), True),
            (_ev(evidence_sources_confirmed=True, verification_checks_executed=True,
                 verification_checks_passed=True, no_open_verification_items=True,
                 conditions_documented=True, conditions_bounded=True), False),
            (_ev(evidence_sources_confirmed=True, verification_checks_executed=True,
                 verification_checks_passed=True, no_open_verification_items=True), False),
            (_ev(evidence_sources_confirmed=True, verification_checks_executed=True), False),
            (_ev(evidence_sources_confirmed=True), False),
            (_ev(), False),
        ]:
            with self.subTest(expected_fully_closed=expected_fully_closed):
                verdict = classify_verification_closure(evidence)
                self.assertEqual(verdict.is_fully_closed, expected_fully_closed)

    # -----------------------------------------------------------------------
    # Group U — is_closed flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_U01_is_closed_true_for_fully_closed(self):
        verdict = classify_verification_closure(_full_evidence())
        self.assertTrue(verdict.is_closed)

    @_skip_if_unavailable
    def test_U02_is_closed_true_for_conditionally_closed(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=True,
            no_open_verification_items=True,
            conditions_documented=True,
            conditions_bounded=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertEqual(verdict.closure_class, VerificationClosureClass.conditionally_closed)
        self.assertTrue(verdict.is_closed)

    @_skip_if_unavailable
    def test_U03_is_closed_false_for_partially_substantiated(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=True,
            no_open_verification_items=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertEqual(verdict.closure_class, VerificationClosureClass.partially_substantiated)
        self.assertFalse(verdict.is_closed)

    @_skip_if_unavailable
    def test_U04_is_closed_false_for_evidence_pending(self):
        evidence = _ev(evidence_sources_confirmed=True)
        verdict = classify_verification_closure(evidence)
        self.assertFalse(verdict.is_closed)

    @_skip_if_unavailable
    def test_U05_is_closed_false_for_unverified(self):
        verdict = classify_verification_closure(_ev())
        self.assertFalse(verdict.is_closed)

    # -----------------------------------------------------------------------
    # Group V — is_evidence_present flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_V01_is_evidence_present_false_for_unverified(self):
        verdict = classify_verification_closure(_ev())
        self.assertFalse(verdict.is_evidence_present)

    @_skip_if_unavailable
    def test_V02_is_evidence_present_true_for_pending(self):
        evidence = _ev(evidence_sources_confirmed=True)
        verdict = classify_verification_closure(evidence)
        self.assertTrue(verdict.is_evidence_present)

    @_skip_if_unavailable
    def test_V03_is_evidence_present_true_for_partially_substantiated(self):
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=True,
            no_open_verification_items=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertTrue(verdict.is_evidence_present)

    @_skip_if_unavailable
    def test_V04_is_evidence_present_true_for_fully_closed(self):
        verdict = classify_verification_closure(_full_evidence())
        self.assertTrue(verdict.is_evidence_present)

    # -----------------------------------------------------------------------
    # Group W — downgrade_reasons non-empty when downgrade occurred
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_W01_downgrade_reasons_nonempty_when_class_downgraded(self):
        # no evidence → unverified → downgrade
        verdict = classify_verification_closure(_ev())
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    @_skip_if_unavailable
    def test_W02_downgrade_reasons_nonempty_for_open_items(self):
        evidence = _full_evidence(no_open_verification_items=False)
        verdict = classify_verification_closure(evidence)
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    @_skip_if_unavailable
    def test_W03_downgrade_reasons_empty_for_fully_closed(self):
        verdict = classify_verification_closure(_full_evidence())
        self.assertEqual(verdict.downgrade_reasons, [])

    # -----------------------------------------------------------------------
    # Group X — build_baseline_verification_closure_verdict
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_X01_baseline_verdict_returns_unverified(self):
        verdict = build_baseline_verification_closure_verdict()
        self.assertEqual(verdict.closure_class, VerificationClosureClass.unverified)

    @_skip_if_unavailable
    def test_X02_baseline_verdict_is_not_evidence_present(self):
        verdict = build_baseline_verification_closure_verdict()
        self.assertFalse(verdict.is_evidence_present)

    @_skip_if_unavailable
    def test_X03_baseline_verdict_is_not_fully_closed(self):
        verdict = build_baseline_verification_closure_verdict()
        self.assertFalse(verdict.is_fully_closed)

    @_skip_if_unavailable
    def test_X04_baseline_verdict_is_not_closed(self):
        verdict = build_baseline_verification_closure_verdict()
        self.assertFalse(verdict.is_closed)

    @_skip_if_unavailable
    def test_X05_build_verification_closure_verdict_alias_works(self):
        evidence = _full_evidence()
        v1 = classify_verification_closure(evidence)
        v2 = build_verification_closure_verdict(evidence)
        self.assertEqual(v1.closure_class, v2.closure_class)

    # -----------------------------------------------------------------------
    # Group Y — VerificationClosureClass rank ordering
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Y01_fully_closed_has_highest_rank(self):
        fc_rank = VerificationClosureClass.fully_closed.rank
        for cls in VerificationClosureClass:
            if cls != VerificationClosureClass.fully_closed:
                with self.subTest(cls=cls.value):
                    self.assertGreater(fc_rank, cls.rank)

    @_skip_if_unavailable
    def test_Y02_unverified_has_rank_zero(self):
        self.assertEqual(VerificationClosureClass.unverified.rank, 0)

    @_skip_if_unavailable
    def test_Y03_conditionally_closed_rank_higher_than_partially_substantiated(self):
        self.assertGreater(
            VerificationClosureClass.conditionally_closed.rank,
            VerificationClosureClass.partially_substantiated.rank,
        )

    @_skip_if_unavailable
    def test_Y04_partially_substantiated_rank_higher_than_pending(self):
        self.assertGreater(
            VerificationClosureClass.partially_substantiated.rank,
            VerificationClosureClass.evidence_present_verification_pending.rank,
        )

    @_skip_if_unavailable
    def test_Y05_pending_rank_higher_than_unverified(self):
        self.assertGreater(
            VerificationClosureClass.evidence_present_verification_pending.rank,
            VerificationClosureClass.unverified.rank,
        )

    # -----------------------------------------------------------------------
    # Group Z — from_string fallback
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Z01_from_string_valid_value_returns_correct_member(self):
        self.assertEqual(
            VerificationClosureClass.from_string("fully_closed"),
            VerificationClosureClass.fully_closed,
        )

    @_skip_if_unavailable
    def test_Z02_from_string_unknown_value_returns_unverified(self):
        self.assertEqual(
            VerificationClosureClass.from_string("invalid_class"),
            VerificationClosureClass.unverified,
        )

    @_skip_if_unavailable
    def test_Z03_from_string_non_string_returns_unverified(self):
        self.assertEqual(
            VerificationClosureClass.from_string(None),  # type: ignore[arg-type]
            VerificationClosureClass.unverified,
        )

    @_skip_if_unavailable
    def test_Z04_from_string_conditionally_closed(self):
        self.assertEqual(
            VerificationClosureClass.from_string("conditionally_closed"),
            VerificationClosureClass.conditionally_closed,
        )

    @_skip_if_unavailable
    def test_Z05_from_string_unverified_returns_unverified(self):
        self.assertEqual(
            VerificationClosureClass.from_string("unverified"),
            VerificationClosureClass.unverified,
        )

    # -----------------------------------------------------------------------
    # Group AA — SystemFinalAcceptanceEvaluator integration
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AA01_system_evaluator_includes_verification_closure_dimension(self):
        """SystemFinalAcceptanceEvaluator.evaluate() includes
        verification_evidence_closure in its checklist."""
        try:
            from core.system_final_acceptance_verdict import (
                get_system_acceptance_evaluator,
            )
        except ImportError:
            self.skipTest(
                "core.system_final_acceptance_verdict not available"
            )
        evaluator = get_system_acceptance_evaluator()
        report = evaluator.evaluate()
        self.assertIn("verification_evidence_closure", report.checklist)

    @_skip_if_unavailable
    def test_AA02_system_evaluator_verification_closure_item_has_valid_status(self):
        """The verification_evidence_closure checklist item has a valid status."""
        try:
            from core.system_final_acceptance_verdict import (
                get_system_acceptance_evaluator,
                DimensionStatus,
            )
        except ImportError:
            self.skipTest(
                "core.system_final_acceptance_verdict not available"
            )
        evaluator = get_system_acceptance_evaluator()
        report = evaluator.evaluate()
        item = report.checklist.get("verification_evidence_closure")
        self.assertIsNotNone(item)
        self.assertIn(
            item.status,
            [DimensionStatus.accepted, DimensionStatus.pending, DimensionStatus.unresolved],
        )

    # -----------------------------------------------------------------------
    # Group AB — AcceptanceDimensionId includes verification_evidence_closure
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AB01_all_dimensions_includes_verification_evidence_closure(self):
        try:
            from core.system_final_acceptance_verdict import AcceptanceDimensionId
        except ImportError:
            self.skipTest(
                "core.system_final_acceptance_verdict not available"
            )
        dims = [d.value for d in AcceptanceDimensionId.all_dimensions()]
        self.assertIn("verification_evidence_closure", dims)

    @_skip_if_unavailable
    def test_AB02_verification_evidence_closure_is_valid_dimension_id(self):
        try:
            from core.system_final_acceptance_verdict import AcceptanceDimensionId
        except ImportError:
            self.skipTest(
                "core.system_final_acceptance_verdict not available"
            )
        dim = AcceptanceDimensionId.verification_evidence_closure
        self.assertEqual(dim.value, "verification_evidence_closure")

    # -----------------------------------------------------------------------
    # Group AC — Probe returns pending with conservative baseline
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AC01_probe_returns_pending_with_conservative_baseline(self):
        """The acceptance probe should return pending (not unresolved) since
        the module is available, and the baseline correctly returns unverified."""
        try:
            from core.system_final_acceptance_verdict import (
                get_system_acceptance_evaluator,
                DimensionStatus,
            )
        except ImportError:
            self.skipTest(
                "core.system_final_acceptance_verdict not available"
            )
        evaluator = get_system_acceptance_evaluator()
        report = evaluator.evaluate()
        item = report.checklist.get("verification_evidence_closure")
        self.assertIsNotNone(item)
        # Module is available → should be pending (structure present)
        # or accepted if somehow live evidence was collected
        self.assertIn(
            item.status,
            [DimensionStatus.pending, DimensionStatus.accepted],
        )

    # -----------------------------------------------------------------------
    # Group AD — Zero-evidence probe must not return fully_closed
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AD01_zero_evidence_probe_must_not_be_fully_closed(self):
        """EVIDENCE_ABSENCE_DEFAULTS_TO_UNVERIFIED_POLICY: zero-evidence probe
        must return unverified, never fully_closed."""
        verdict = build_baseline_verification_closure_verdict()
        self.assertNotEqual(
            verdict.closure_class, VerificationClosureClass.fully_closed
        )

    @_skip_if_unavailable
    def test_AD02_zero_evidence_probe_must_not_be_conditionally_closed(self):
        verdict = build_baseline_verification_closure_verdict()
        self.assertNotEqual(
            verdict.closure_class, VerificationClosureClass.conditionally_closed
        )

    @_skip_if_unavailable
    def test_AD03_zero_evidence_probe_must_not_be_partially_substantiated(self):
        verdict = build_baseline_verification_closure_verdict()
        self.assertNotEqual(
            verdict.closure_class, VerificationClosureClass.partially_substantiated
        )

    @_skip_if_unavailable
    def test_AD04_zero_evidence_probe_must_not_be_pending(self):
        verdict = build_baseline_verification_closure_verdict()
        self.assertNotEqual(
            verdict.closure_class,
            VerificationClosureClass.evidence_present_verification_pending,
        )

    @_skip_if_unavailable
    def test_AD05_evidence_present_but_no_checks_must_not_claim_fully_closed(self):
        """EVIDENCE_PRESENCE_IS_NOT_VERIFICATION_CLOSURE_POLICY."""
        evidence = _ev(evidence_sources_confirmed=True)
        verdict = classify_verification_closure(evidence)
        self.assertNotEqual(
            verdict.closure_class, VerificationClosureClass.fully_closed
        )

    @_skip_if_unavailable
    def test_AD06_partial_verification_must_not_claim_conditionally_closed(self):
        """PARTIAL_VERIFICATION_IS_NOT_CONDITIONAL_CLOSURE_POLICY."""
        # Some checks executed but not all passed, with conditions claimed
        evidence = _ev(
            evidence_sources_confirmed=True,
            verification_checks_executed=True,
            verification_checks_passed=False,  # not all passed
            conditions_documented=True,
            conditions_bounded=True,
        )
        verdict = classify_verification_closure(evidence)
        self.assertNotEqual(
            verdict.closure_class, VerificationClosureClass.conditionally_closed
        )

    @_skip_if_unavailable
    def test_AD07_multiple_evidence_sources_alone_must_not_claim_fully_closed(self):
        """Multiple source convergence alone (without checks passed) must not
        produce fully_closed."""
        evidence = _ev(
            evidence_sources_confirmed=True,
            all_evidence_sources_present=True,
            multiple_source_convergence=True,
            # verification_checks_executed=False (default)
        )
        verdict = classify_verification_closure(evidence)
        self.assertNotEqual(
            verdict.closure_class, VerificationClosureClass.fully_closed
        )


if __name__ == "__main__":
    unittest.main()
