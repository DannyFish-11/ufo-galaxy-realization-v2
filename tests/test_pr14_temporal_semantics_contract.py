#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr14_temporal_semantics_contract.py
===============================================
PR-14 — Time Semantics / Freshness / Staleness / Deadline Truth Contract.

Validates that:

 1. **Temporal taxonomy is defined and importable** (five classes).
 2. **timely_authoritative** classification when all required conditions hold.
 3. **timely_authoritative** requires timestamp_authoritative.
 4. **timely_authoritative** requires within_authoritative_window.
 5. **timely_authoritative** requires clock_uncertainty_acceptable.
 6. **timely_authoritative** requires lag_measured and lag_within_bound.
 7. **timely_authoritative** requires heartbeat when heartbeat_required.
 8. **timely_authoritative** requires heartbeat_within_window when required.
 9. **fresh_with_bounded_lag** when freshness window met, lag measured and bounded.
10. **fresh_with_bounded_lag** requires lag_measured.
11. **fresh_with_bounded_lag** requires lag_within_bound.
12. **stale_but_usable** when stale but within staleness tolerance + lag known.
13. **deadline_missed_or_timed_out** when deadline_set and NOT deadline_met.
14. **deadline_missed_or_timed_out** when data exceeds staleness tolerance.
15. **temporally_unreliable** when no timestamp (fail-conservative baseline).
16. **temporally_unreliable** when explicit_temporally_unreliable.
17. **Timestamp presence must NOT claim timely_authoritative** by itself.
18. **Explicit unreliable overrides ALL other evidence**.
19. **Deadline miss overrides freshness and heartbeat conditions**.
20. **Heartbeat absence blocks timely_authoritative when required**.
21. **Clock uncertainty blocks timely_authoritative**.
22. **Policy sentinels are importable and non-empty**.
23. **to_dict() / from_dict() round-trip** for evidence and verdict.
24. **build_baseline_temporal_verdict()** returns temporally_unreliable.
25. **TemporalClass.rank ordering contract**.
26. **TemporalClass.from_string fallback** to temporally_unreliable on unknown.
27. **SystemFinalAcceptanceEvaluator includes temporal_semantics**.
28. **AcceptanceDimensionId.all_dimensions() includes temporal_semantics**.
29. **Probe returns pending with conservative baseline verdict**.
30. **Zero-evidence probe must not return timely_authoritative**.

Test groups
-----------
 A)  Sentinel imports — PR-14 authority and policy constants importable.
 B)  Enum completeness — all five TemporalClass values exist.
 C)  timely_authoritative — all required conditions satisfied.
 D)  timely_authoritative — blocked by missing timestamp_authoritative.
 E)  timely_authoritative — blocked by missing within_authoritative_window.
 F)  timely_authoritative — blocked by unacceptable clock_uncertainty.
 G)  timely_authoritative — blocked by unmeasured lag.
 H)  timely_authoritative — blocked by lag out of bound.
 I)  timely_authoritative — blocked by absent required heartbeat.
 J)  timely_authoritative — blocked by heartbeat outside window.
 K)  fresh_with_bounded_lag — freshness met, lag measured and bounded.
 L)  fresh_with_bounded_lag — blocked by missing lag_measured.
 M)  fresh_with_bounded_lag — blocked by lag_within_bound=False.
 N)  stale_but_usable — stale, within staleness tolerance, lag measured.
 O)  stale_but_usable — requires lag_measured.
 P)  deadline_missed_or_timed_out — deadline_set and deadline_met=False.
 Q)  deadline_missed_or_timed_out — data exceeds staleness tolerance.
 R)  temporally_unreliable — zero evidence (fail-conservative baseline).
 S)  temporally_unreliable — explicit_temporally_unreliable=True.
 T)  temporally_unreliable — timestamp present but no other evidence.
 U)  explicit_temporally_unreliable overrides all other positive evidence.
 V)  deadline miss overrides freshness conditions.
 W)  is_timely_authoritative flag — only True for timely_authoritative.
 X)  is_fresh flag — True for timely_authoritative and fresh_with_bounded_lag.
 Y)  is_stale_but_usable — True only for stale_but_usable.
 Z)  is_deadline_missed — True only for deadline_missed_or_timed_out.
 AA) is_temporally_unreliable — True only for temporally_unreliable.
 AB) downgrade_reasons non-empty when downgrade occurred.
 AC) TemporalEvidence to_dict / from_dict round-trip.
 AD) TemporalVerdict to_dict / from_dict round-trip.
 AE) build_baseline_temporal_verdict() returns temporally_unreliable.
 AF) TemporalClass.rank ordering contract.
 AG) TemporalClass.from_string fallback to temporally_unreliable.
 AH) SystemFinalAcceptanceEvaluator includes temporal_semantics.
 AI) AcceptanceDimensionId.all_dimensions() includes temporal_semantics.
 AJ) AcceptanceDimensionId probe returns pending with conservative baseline.
 AK) Zero-evidence probe must not return timely_authoritative.
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
    from core.temporal_semantics_contract import (
        # Authority / policy sentinels
        TEMPORAL_SEMANTICS_CONTRACT_AUTHORITY,
        TEMPORAL_SEMANTICS_CONTRACT_PR14_SENTINEL,
        TIMESTAMP_PRESENCE_IS_NOT_TEMPORAL_AUTHORITY_POLICY,
        LAG_UNMEASURED_BLOCKS_FRESH_BOUNDED_LAG_POLICY,
        DEADLINE_MISS_FORCES_TIMED_OUT_CLASS_POLICY,
        HEARTBEAT_ABSENT_BLOCKS_TIMELY_AUTHORITATIVE_POLICY,
        CLOCK_UNCERTAINTY_BLOCKS_TIMELY_AUTHORITATIVE_POLICY,
        TEMPORAL_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY,
        EXPLICIT_UNRELIABLE_ALWAYS_FORCES_LOWEST_CLASS_POLICY,
        # Enumerations
        TemporalClass,
        # Data classes
        TemporalEvidence,
        TemporalVerdict,
        # Functions
        classify_temporal_semantics,
        build_temporal_verdict,
        build_baseline_temporal_verdict,
    )
    _MODULE_AVAILABLE = True
except ImportError as _imp_err:
    print(
        f"SKIP: core.temporal_semantics_contract unavailable: {_imp_err}"
    )


def _skip_if_unavailable(test_fn):
    """Decorator: skip test if the module is not available."""
    def wrapper(self):
        if not _MODULE_AVAILABLE:
            self.skipTest("core.temporal_semantics_contract not available")
        return test_fn(self)
    wrapper.__name__ = test_fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# Helpers: build evidence with named overrides
# ---------------------------------------------------------------------------

def _ev(**kwargs) -> "TemporalEvidence":
    """Build TemporalEvidence with fully conservative defaults."""
    return TemporalEvidence(
        timestamp_present=kwargs.get("timestamp_present", False),
        timestamp_authoritative=kwargs.get("timestamp_authoritative", False),
        within_authoritative_window=kwargs.get("within_authoritative_window", False),
        within_freshness_window=kwargs.get("within_freshness_window", False),
        within_staleness_tolerance=kwargs.get("within_staleness_tolerance", False),
        deadline_set=kwargs.get("deadline_set", False),
        deadline_met=kwargs.get("deadline_met", False),
        heartbeat_required=kwargs.get("heartbeat_required", False),
        heartbeat_present=kwargs.get("heartbeat_present", False),
        heartbeat_within_window=kwargs.get("heartbeat_within_window", False),
        lag_measured=kwargs.get("lag_measured", False),
        lag_within_bound=kwargs.get("lag_within_bound", False),
        clock_uncertainty_acceptable=kwargs.get("clock_uncertainty_acceptable", False),
        explicit_temporally_unreliable=kwargs.get(
            "explicit_temporally_unreliable", False
        ),
        participant_id=kwargs.get("participant_id"),
        trace_id=kwargs.get("trace_id"),
    )


def _ev_timely_authoritative(**overrides) -> "TemporalEvidence":
    """Build fully timely_authoritative evidence with optional overrides."""
    defaults = dict(
        timestamp_present=True,
        timestamp_authoritative=True,
        within_authoritative_window=True,
        within_freshness_window=True,
        lag_measured=True,
        lag_within_bound=True,
        clock_uncertainty_acceptable=True,
    )
    defaults.update(overrides)
    return _ev(**defaults)


def _ev_fresh_bounded_lag(**overrides) -> "TemporalEvidence":
    """Build fresh_with_bounded_lag evidence (missing authoritative window)."""
    defaults = dict(
        timestamp_present=True,
        within_freshness_window=True,
        lag_measured=True,
        lag_within_bound=True,
        # NOT within_authoritative_window → prevents timely_authoritative
    )
    defaults.update(overrides)
    return _ev(**defaults)


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestTemporalSemanticsContract(unittest.TestCase):
    """Automated tests for core.temporal_semantics_contract (PR-14)."""

    # -----------------------------------------------------------------------
    # Group A — Sentinel imports
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_A01_authority_sentinel_importable(self):
        self.assertIsInstance(TEMPORAL_SEMANTICS_CONTRACT_AUTHORITY, str)
        self.assertGreater(len(TEMPORAL_SEMANTICS_CONTRACT_AUTHORITY), 0)

    @_skip_if_unavailable
    def test_A02_pr14_sentinel_importable(self):
        self.assertIsInstance(TEMPORAL_SEMANTICS_CONTRACT_PR14_SENTINEL, str)
        self.assertIn("PR14", TEMPORAL_SEMANTICS_CONTRACT_PR14_SENTINEL)

    @_skip_if_unavailable
    def test_A03_timestamp_presence_policy_importable(self):
        self.assertIsInstance(
            TIMESTAMP_PRESENCE_IS_NOT_TEMPORAL_AUTHORITY_POLICY, str
        )
        self.assertGreater(
            len(TIMESTAMP_PRESENCE_IS_NOT_TEMPORAL_AUTHORITY_POLICY), 0
        )

    @_skip_if_unavailable
    def test_A04_lag_unmeasured_policy_importable(self):
        self.assertIsInstance(LAG_UNMEASURED_BLOCKS_FRESH_BOUNDED_LAG_POLICY, str)
        self.assertGreater(len(LAG_UNMEASURED_BLOCKS_FRESH_BOUNDED_LAG_POLICY), 0)

    @_skip_if_unavailable
    def test_A05_deadline_miss_policy_importable(self):
        self.assertIsInstance(DEADLINE_MISS_FORCES_TIMED_OUT_CLASS_POLICY, str)
        self.assertGreater(len(DEADLINE_MISS_FORCES_TIMED_OUT_CLASS_POLICY), 0)

    @_skip_if_unavailable
    def test_A06_heartbeat_absent_policy_importable(self):
        self.assertIsInstance(
            HEARTBEAT_ABSENT_BLOCKS_TIMELY_AUTHORITATIVE_POLICY, str
        )
        self.assertGreater(
            len(HEARTBEAT_ABSENT_BLOCKS_TIMELY_AUTHORITATIVE_POLICY), 0
        )

    @_skip_if_unavailable
    def test_A07_clock_uncertainty_policy_importable(self):
        self.assertIsInstance(
            CLOCK_UNCERTAINTY_BLOCKS_TIMELY_AUTHORITATIVE_POLICY, str
        )
        self.assertGreater(
            len(CLOCK_UNCERTAINTY_BLOCKS_TIMELY_AUTHORITATIVE_POLICY), 0
        )

    @_skip_if_unavailable
    def test_A08_temporal_absence_policy_importable(self):
        self.assertIsInstance(TEMPORAL_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY, str)
        self.assertGreater(len(TEMPORAL_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY), 0)

    @_skip_if_unavailable
    def test_A09_explicit_unreliable_policy_importable(self):
        self.assertIsInstance(
            EXPLICIT_UNRELIABLE_ALWAYS_FORCES_LOWEST_CLASS_POLICY, str
        )
        self.assertGreater(
            len(EXPLICIT_UNRELIABLE_ALWAYS_FORCES_LOWEST_CLASS_POLICY), 0
        )

    # -----------------------------------------------------------------------
    # Group B — Enum completeness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_B01_five_temporal_classes_exist(self):
        values = {c.value for c in TemporalClass}
        self.assertIn("timely_authoritative", values)
        self.assertIn("fresh_with_bounded_lag", values)
        self.assertIn("stale_but_usable", values)
        self.assertIn("deadline_missed_or_timed_out", values)
        self.assertIn("temporally_unreliable", values)

    @_skip_if_unavailable
    def test_B02_exactly_five_classes(self):
        self.assertEqual(len(list(TemporalClass)), 5)

    @_skip_if_unavailable
    def test_B03_class_values_are_strings(self):
        for c in TemporalClass:
            self.assertIsInstance(c.value, str)

    # -----------------------------------------------------------------------
    # Group C — timely_authoritative classification
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_C01_all_conditions_produces_timely_authoritative(self):
        evidence = _ev_timely_authoritative()
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )

    @_skip_if_unavailable
    def test_C02_timely_authoritative_flag_true(self):
        verdict = classify_temporal_semantics(_ev_timely_authoritative())
        self.assertTrue(verdict.is_timely_authoritative)

    @_skip_if_unavailable
    def test_C03_timely_authoritative_is_fresh_true(self):
        verdict = classify_temporal_semantics(_ev_timely_authoritative())
        self.assertTrue(verdict.is_fresh)

    @_skip_if_unavailable
    def test_C04_timely_authoritative_downgrade_reasons_empty(self):
        verdict = classify_temporal_semantics(_ev_timely_authoritative())
        self.assertEqual(verdict.downgrade_reasons, [])

    @_skip_if_unavailable
    def test_C05_timely_authoritative_with_heartbeat_conditions(self):
        evidence = _ev_timely_authoritative(
            heartbeat_required=True,
            heartbeat_present=True,
            heartbeat_within_window=True,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )

    @_skip_if_unavailable
    def test_C06_timely_authoritative_with_deadline_met(self):
        evidence = _ev_timely_authoritative(
            deadline_set=True,
            deadline_met=True,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )

    # -----------------------------------------------------------------------
    # Group D — timely_authoritative blocked by missing timestamp_authoritative
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_D01_non_authoritative_timestamp_not_timely_authoritative(self):
        evidence = _ev_timely_authoritative(timestamp_authoritative=False)
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )

    @_skip_if_unavailable
    def test_D02_non_authoritative_timestamp_not_timely_flag(self):
        evidence = _ev_timely_authoritative(timestamp_authoritative=False)
        verdict = classify_temporal_semantics(evidence)
        self.assertFalse(verdict.is_timely_authoritative)

    # -----------------------------------------------------------------------
    # Group E — timely_authoritative blocked by missing within_authoritative_window
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_E01_outside_authoritative_window_not_timely_authoritative(self):
        evidence = _ev_timely_authoritative(within_authoritative_window=False)
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )

    @_skip_if_unavailable
    def test_E02_outside_authoritative_window_can_be_fresh_bounded_lag(self):
        # If all freshness/lag conditions still hold except authoritative window,
        # should be fresh_with_bounded_lag
        evidence = _ev_timely_authoritative(within_authoritative_window=False)
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.fresh_with_bounded_lag
        )

    # -----------------------------------------------------------------------
    # Group F — timely_authoritative blocked by clock_uncertainty
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_F01_unacceptable_clock_uncertainty_not_timely_authoritative(self):
        evidence = _ev_timely_authoritative(clock_uncertainty_acceptable=False)
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )

    @_skip_if_unavailable
    def test_F02_clock_uncertainty_downgrade_reason_present(self):
        evidence = _ev_timely_authoritative(clock_uncertainty_acceptable=False)
        verdict = classify_temporal_semantics(evidence)
        reasons_text = " ".join(verdict.downgrade_reasons)
        self.assertIn("clock_uncertainty_acceptable", reasons_text)

    # -----------------------------------------------------------------------
    # Group G — timely_authoritative blocked by unmeasured lag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_G01_unmeasured_lag_not_timely_authoritative(self):
        evidence = _ev_timely_authoritative(lag_measured=False)
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )

    @_skip_if_unavailable
    def test_G02_unmeasured_lag_blocks_fresh_bounded_lag(self):
        # lag_measured=False blocks fresh_with_bounded_lag too
        evidence = _ev_fresh_bounded_lag(lag_measured=False)
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.fresh_with_bounded_lag
        )

    # -----------------------------------------------------------------------
    # Group H — timely_authoritative blocked by lag out of bound
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_H01_lag_out_of_bound_not_timely_authoritative(self):
        evidence = _ev_timely_authoritative(lag_within_bound=False)
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )

    @_skip_if_unavailable
    def test_H02_lag_out_of_bound_blocks_fresh_bounded_lag(self):
        evidence = _ev_fresh_bounded_lag(lag_within_bound=False)
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.fresh_with_bounded_lag
        )

    # -----------------------------------------------------------------------
    # Group I — timely_authoritative blocked by absent required heartbeat
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_I01_absent_required_heartbeat_not_timely_authoritative(self):
        evidence = _ev_timely_authoritative(
            heartbeat_required=True,
            heartbeat_present=False,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )

    @_skip_if_unavailable
    def test_I02_absent_required_heartbeat_downgrade_reason_present(self):
        evidence = _ev_timely_authoritative(
            heartbeat_required=True,
            heartbeat_present=False,
        )
        verdict = classify_temporal_semantics(evidence)
        reasons_text = " ".join(verdict.downgrade_reasons)
        self.assertIn("heartbeat_present=False", reasons_text)

    @_skip_if_unavailable
    def test_I03_heartbeat_not_required_does_not_block(self):
        # When heartbeat is not required, absence should not block
        evidence = _ev_timely_authoritative(
            heartbeat_required=False,
            heartbeat_present=False,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )

    # -----------------------------------------------------------------------
    # Group J — timely_authoritative blocked by heartbeat outside window
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_J01_heartbeat_outside_window_not_timely_authoritative(self):
        evidence = _ev_timely_authoritative(
            heartbeat_required=True,
            heartbeat_present=True,
            heartbeat_within_window=False,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )

    # -----------------------------------------------------------------------
    # Group K — fresh_with_bounded_lag classification
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_K01_fresh_bounded_lag_basic(self):
        evidence = _ev_fresh_bounded_lag()
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.fresh_with_bounded_lag
        )

    @_skip_if_unavailable
    def test_K02_fresh_bounded_lag_is_fresh_true(self):
        verdict = classify_temporal_semantics(_ev_fresh_bounded_lag())
        self.assertTrue(verdict.is_fresh)

    @_skip_if_unavailable
    def test_K03_fresh_bounded_lag_is_timely_authoritative_false(self):
        verdict = classify_temporal_semantics(_ev_fresh_bounded_lag())
        self.assertFalse(verdict.is_timely_authoritative)

    @_skip_if_unavailable
    def test_K04_fresh_bounded_lag_is_stale_false(self):
        verdict = classify_temporal_semantics(_ev_fresh_bounded_lag())
        self.assertFalse(verdict.is_stale_but_usable)

    @_skip_if_unavailable
    def test_K05_fresh_bounded_lag_is_deadline_missed_false(self):
        verdict = classify_temporal_semantics(_ev_fresh_bounded_lag())
        self.assertFalse(verdict.is_deadline_missed)

    # -----------------------------------------------------------------------
    # Group L — fresh_with_bounded_lag blocked by missing lag_measured
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_L01_unmeasured_lag_blocks_fresh_bounded_lag_classification(self):
        evidence = _ev(
            timestamp_present=True,
            within_freshness_window=True,
            lag_measured=False,  # lag unknown
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.fresh_with_bounded_lag
        )

    @_skip_if_unavailable
    def test_L02_unmeasured_lag_downgrade_reason_references_policy(self):
        evidence = _ev(
            timestamp_present=True,
            within_freshness_window=True,
            lag_measured=False,
        )
        verdict = classify_temporal_semantics(evidence)
        reasons_text = " ".join(verdict.downgrade_reasons)
        self.assertIn("lag_measured", reasons_text)

    # -----------------------------------------------------------------------
    # Group M — fresh_with_bounded_lag blocked by lag_within_bound=False
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_M01_lag_out_of_bound_blocks_fresh_bounded_lag_classification(self):
        evidence = _ev(
            timestamp_present=True,
            within_freshness_window=True,
            lag_measured=True,
            lag_within_bound=False,  # lag exceeds tolerance
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.fresh_with_bounded_lag
        )

    # -----------------------------------------------------------------------
    # Group N — stale_but_usable classification
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_N01_stale_but_usable_basic(self):
        evidence = _ev(
            timestamp_present=True,
            within_freshness_window=False,  # stale
            within_staleness_tolerance=True,  # but within tolerance
            lag_measured=True,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.stale_but_usable
        )

    @_skip_if_unavailable
    def test_N02_stale_but_usable_is_stale_flag_true(self):
        evidence = _ev(
            timestamp_present=True,
            within_staleness_tolerance=True,
            lag_measured=True,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(verdict.temporal_class, TemporalClass.stale_but_usable)
        self.assertTrue(verdict.is_stale_but_usable)

    @_skip_if_unavailable
    def test_N03_stale_but_usable_is_fresh_false(self):
        evidence = _ev(
            timestamp_present=True,
            within_staleness_tolerance=True,
            lag_measured=True,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertFalse(verdict.is_fresh)

    @_skip_if_unavailable
    def test_N04_stale_but_usable_is_timely_authoritative_false(self):
        evidence = _ev(
            timestamp_present=True,
            within_staleness_tolerance=True,
            lag_measured=True,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertFalse(verdict.is_timely_authoritative)

    # -----------------------------------------------------------------------
    # Group O — stale_but_usable requires lag_measured
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_O01_stale_within_tolerance_lag_unmeasured_not_stale_usable(self):
        evidence = _ev(
            timestamp_present=True,
            within_staleness_tolerance=True,
            lag_measured=False,  # lag not measured
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.stale_but_usable
        )

    # -----------------------------------------------------------------------
    # Group P — deadline_missed_or_timed_out via deadline_set + not deadline_met
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_P01_deadline_set_not_met_is_deadline_missed(self):
        evidence = _ev(
            timestamp_present=True,
            deadline_set=True,
            deadline_met=False,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.deadline_missed_or_timed_out
        )

    @_skip_if_unavailable
    def test_P02_deadline_miss_is_deadline_missed_flag_true(self):
        evidence = _ev(
            timestamp_present=True,
            deadline_set=True,
            deadline_met=False,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertTrue(verdict.is_deadline_missed)

    @_skip_if_unavailable
    def test_P03_deadline_miss_is_fresh_false(self):
        evidence = _ev(
            timestamp_present=True,
            within_freshness_window=True,  # data IS fresh BUT deadline missed
            deadline_set=True,
            deadline_met=False,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.deadline_missed_or_timed_out
        )
        self.assertFalse(verdict.is_fresh)

    @_skip_if_unavailable
    def test_P04_deadline_not_set_does_not_force_timed_out(self):
        # Without deadline_set, even fresh data should not be forced to
        # deadline_missed_or_timed_out
        evidence = _ev_timely_authoritative(
            deadline_set=False,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.deadline_missed_or_timed_out
        )

    # -----------------------------------------------------------------------
    # Group Q — deadline_missed_or_timed_out via staleness tolerance exceeded
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Q01_exceeds_staleness_tolerance_is_deadline_missed(self):
        evidence = _ev(
            timestamp_present=True,
            within_freshness_window=False,
            within_staleness_tolerance=False,  # beyond all tolerance bounds
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.deadline_missed_or_timed_out
        )

    @_skip_if_unavailable
    def test_Q02_within_staleness_tolerance_not_deadline_missed(self):
        evidence = _ev(
            timestamp_present=True,
            within_freshness_window=False,
            within_staleness_tolerance=True,  # within tolerance → stale_but_usable
            lag_measured=True,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.deadline_missed_or_timed_out
        )

    # -----------------------------------------------------------------------
    # Group R — temporally_unreliable (zero evidence)
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_R01_zero_evidence_is_temporally_unreliable(self):
        evidence = _ev()  # all False
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.temporally_unreliable
        )

    @_skip_if_unavailable
    def test_R02_zero_evidence_is_temporally_unreliable_flag(self):
        verdict = classify_temporal_semantics(_ev())
        self.assertTrue(verdict.is_temporally_unreliable)

    @_skip_if_unavailable
    def test_R03_zero_evidence_is_timely_authoritative_false(self):
        verdict = classify_temporal_semantics(_ev())
        self.assertFalse(verdict.is_timely_authoritative)

    @_skip_if_unavailable
    def test_R04_zero_evidence_evidence_present_false(self):
        verdict = classify_temporal_semantics(_ev())
        self.assertFalse(verdict.evidence_present)

    # -----------------------------------------------------------------------
    # Group S — temporally_unreliable via explicit_temporally_unreliable
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_S01_explicit_unreliable_forces_temporally_unreliable(self):
        evidence = _ev(explicit_temporally_unreliable=True)
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.temporally_unreliable
        )

    @_skip_if_unavailable
    def test_S02_explicit_unreliable_flag_is_true(self):
        evidence = _ev(explicit_temporally_unreliable=True)
        verdict = classify_temporal_semantics(evidence)
        self.assertTrue(verdict.is_temporally_unreliable)

    # -----------------------------------------------------------------------
    # Group T — temporally_unreliable when only timestamp present
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_T01_timestamp_only_is_not_timely_authoritative(self):
        """TIMESTAMP_PRESENCE_IS_NOT_TEMPORAL_AUTHORITY_POLICY check."""
        evidence = _ev(timestamp_present=True)  # only timestamp, no other evidence
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )

    @_skip_if_unavailable
    def test_T02_timestamp_only_is_not_fresh_bounded_lag(self):
        evidence = _ev(timestamp_present=True)
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.fresh_with_bounded_lag
        )

    @_skip_if_unavailable
    def test_T03_timestamp_only_is_not_stale_but_usable(self):
        evidence = _ev(timestamp_present=True)
        verdict = classify_temporal_semantics(evidence)
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.stale_but_usable
        )

    # -----------------------------------------------------------------------
    # Group U — explicit_temporally_unreliable overrides all
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_U01_explicit_unreliable_overrides_full_timely_evidence(self):
        """Even with fully timely_authoritative evidence, explicit unreliable wins."""
        evidence = _ev_timely_authoritative(explicit_temporally_unreliable=True)
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.temporally_unreliable
        )

    @_skip_if_unavailable
    def test_U02_explicit_unreliable_overrides_fresh_bounded_lag_evidence(self):
        evidence = _ev_fresh_bounded_lag(explicit_temporally_unreliable=True)
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.temporally_unreliable
        )

    @_skip_if_unavailable
    def test_U03_explicit_unreliable_overrides_stale_but_usable_evidence(self):
        evidence = _ev(
            timestamp_present=True,
            within_staleness_tolerance=True,
            lag_measured=True,
            explicit_temporally_unreliable=True,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.temporally_unreliable
        )

    # -----------------------------------------------------------------------
    # Group V — deadline miss overrides freshness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_V01_deadline_miss_overrides_timely_authoritative_conditions(self):
        """Even with all timely conditions met, deadline miss wins."""
        evidence = _ev_timely_authoritative(
            deadline_set=True,
            deadline_met=False,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.deadline_missed_or_timed_out
        )

    @_skip_if_unavailable
    def test_V02_deadline_miss_overrides_fresh_bounded_lag_conditions(self):
        evidence = _ev_fresh_bounded_lag(
            deadline_set=True,
            deadline_met=False,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.deadline_missed_or_timed_out
        )

    # -----------------------------------------------------------------------
    # Group W — is_timely_authoritative flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_W01_is_timely_authoritative_only_for_timely_authoritative(self):
        for cls_name, ev_fn in [
            ("fresh_with_bounded_lag", _ev_fresh_bounded_lag),
            ("stale_but_usable", lambda: _ev(
                timestamp_present=True,
                within_staleness_tolerance=True,
                lag_measured=True,
            )),
            ("temporally_unreliable", lambda: _ev()),
        ]:
            with self.subTest(cls=cls_name):
                verdict = classify_temporal_semantics(ev_fn())
                self.assertFalse(verdict.is_timely_authoritative)

    # -----------------------------------------------------------------------
    # Group X — is_fresh flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_X01_is_fresh_true_for_timely_authoritative(self):
        verdict = classify_temporal_semantics(_ev_timely_authoritative())
        self.assertTrue(verdict.is_fresh)

    @_skip_if_unavailable
    def test_X02_is_fresh_true_for_fresh_bounded_lag(self):
        verdict = classify_temporal_semantics(_ev_fresh_bounded_lag())
        self.assertTrue(verdict.is_fresh)

    @_skip_if_unavailable
    def test_X03_is_fresh_false_for_stale_but_usable(self):
        evidence = _ev(
            timestamp_present=True,
            within_staleness_tolerance=True,
            lag_measured=True,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertFalse(verdict.is_fresh)

    @_skip_if_unavailable
    def test_X04_is_fresh_false_for_deadline_missed(self):
        evidence = _ev(
            timestamp_present=True,
            deadline_set=True,
            deadline_met=False,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertFalse(verdict.is_fresh)

    @_skip_if_unavailable
    def test_X05_is_fresh_false_for_temporally_unreliable(self):
        verdict = classify_temporal_semantics(_ev())
        self.assertFalse(verdict.is_fresh)

    # -----------------------------------------------------------------------
    # Group Y — is_stale_but_usable flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Y01_is_stale_but_usable_only_for_stale_but_usable(self):
        evidence = _ev(
            timestamp_present=True,
            within_staleness_tolerance=True,
            lag_measured=True,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertTrue(verdict.is_stale_but_usable)
        self.assertFalse(verdict.is_timely_authoritative)
        self.assertFalse(verdict.is_fresh)
        self.assertFalse(verdict.is_deadline_missed)
        self.assertFalse(verdict.is_temporally_unreliable)

    # -----------------------------------------------------------------------
    # Group Z — is_deadline_missed flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Z01_is_deadline_missed_only_for_deadline_missed_or_timed_out(self):
        evidence = _ev(
            timestamp_present=True,
            deadline_set=True,
            deadline_met=False,
        )
        verdict = classify_temporal_semantics(evidence)
        self.assertTrue(verdict.is_deadline_missed)
        self.assertFalse(verdict.is_timely_authoritative)
        self.assertFalse(verdict.is_fresh)
        self.assertFalse(verdict.is_stale_but_usable)
        self.assertFalse(verdict.is_temporally_unreliable)

    # -----------------------------------------------------------------------
    # Group AA — is_temporally_unreliable flag
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AA01_is_temporally_unreliable_only_for_temporally_unreliable(self):
        verdict = classify_temporal_semantics(_ev())
        self.assertTrue(verdict.is_temporally_unreliable)
        self.assertFalse(verdict.is_timely_authoritative)
        self.assertFalse(verdict.is_fresh)
        self.assertFalse(verdict.is_stale_but_usable)
        self.assertFalse(verdict.is_deadline_missed)

    # -----------------------------------------------------------------------
    # Group AB — downgrade_reasons
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AB01_downgrade_reasons_non_empty_when_downgraded(self):
        # timely_authoritative with one blocker → should have downgrade reasons
        evidence = _ev_timely_authoritative(clock_uncertainty_acceptable=False)
        verdict = classify_temporal_semantics(evidence)
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    @_skip_if_unavailable
    def test_AB02_downgrade_reasons_empty_for_timely_authoritative(self):
        verdict = classify_temporal_semantics(_ev_timely_authoritative())
        self.assertEqual(verdict.downgrade_reasons, [])

    # -----------------------------------------------------------------------
    # Group AC — TemporalEvidence to_dict / from_dict round-trip
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AC01_evidence_to_dict_from_dict_roundtrip(self):
        ev = _ev_timely_authoritative(
            participant_id="test-participant",
            trace_id="trace-001",
        )
        d = ev.to_dict()
        ev2 = TemporalEvidence.from_dict(d)
        self.assertEqual(ev.timestamp_present, ev2.timestamp_present)
        self.assertEqual(ev.timestamp_authoritative, ev2.timestamp_authoritative)
        self.assertEqual(ev.within_authoritative_window, ev2.within_authoritative_window)
        self.assertEqual(ev.within_freshness_window, ev2.within_freshness_window)
        self.assertEqual(ev.lag_measured, ev2.lag_measured)
        self.assertEqual(ev.lag_within_bound, ev2.lag_within_bound)
        self.assertEqual(ev.clock_uncertainty_acceptable, ev2.clock_uncertainty_acceptable)
        self.assertEqual(ev.participant_id, ev2.participant_id)
        self.assertEqual(ev.trace_id, ev2.trace_id)

    @_skip_if_unavailable
    def test_AC02_evidence_to_dict_is_json_serialisable(self):
        ev = _ev_timely_authoritative()
        d = ev.to_dict()
        json_str = json.dumps(d)
        self.assertIsInstance(json_str, str)

    # -----------------------------------------------------------------------
    # Group AD — TemporalVerdict to_dict / from_dict round-trip
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AD01_verdict_to_dict_from_dict_roundtrip(self):
        verdict = classify_temporal_semantics(_ev_timely_authoritative())
        d = verdict.to_dict()
        verdict2 = TemporalVerdict.from_dict(d)
        self.assertEqual(verdict.temporal_class, verdict2.temporal_class)
        self.assertEqual(verdict.is_timely_authoritative, verdict2.is_timely_authoritative)
        self.assertEqual(verdict.is_fresh, verdict2.is_fresh)
        self.assertEqual(verdict.is_temporally_unreliable, verdict2.is_temporally_unreliable)

    @_skip_if_unavailable
    def test_AD02_verdict_to_dict_is_json_serialisable(self):
        verdict = classify_temporal_semantics(_ev())
        d = verdict.to_dict()
        json_str = json.dumps(d)
        self.assertIsInstance(json_str, str)

    @_skip_if_unavailable
    def test_AD03_verdict_from_dict_unknown_class_fallback(self):
        d = {
            "temporal_class": "some_unknown_class",
            "rationale": "test",
            "downgrade_reasons": [],
            "is_timely_authoritative": False,
            "is_fresh": False,
            "is_stale_but_usable": False,
            "is_deadline_missed": False,
            "is_temporally_unreliable": True,
        }
        verdict = TemporalVerdict.from_dict(d)
        self.assertEqual(verdict.temporal_class, TemporalClass.temporally_unreliable)

    # -----------------------------------------------------------------------
    # Group AE — build_baseline_temporal_verdict
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AE01_baseline_returns_temporally_unreliable(self):
        verdict = build_baseline_temporal_verdict()
        self.assertEqual(
            verdict.temporal_class, TemporalClass.temporally_unreliable
        )

    @_skip_if_unavailable
    def test_AE02_baseline_is_temporally_unreliable_flag(self):
        verdict = build_baseline_temporal_verdict()
        self.assertTrue(verdict.is_temporally_unreliable)

    @_skip_if_unavailable
    def test_AE03_baseline_is_not_timely_authoritative(self):
        verdict = build_baseline_temporal_verdict()
        self.assertFalse(verdict.is_timely_authoritative)

    @_skip_if_unavailable
    def test_AE04_build_temporal_verdict_alias_works(self):
        ev = _ev()
        verdict = build_temporal_verdict(ev)
        self.assertEqual(
            verdict.temporal_class, TemporalClass.temporally_unreliable
        )

    # -----------------------------------------------------------------------
    # Group AF — TemporalClass.rank ordering
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AF01_rank_ordering_contract(self):
        self.assertGreater(
            TemporalClass.rank(TemporalClass.timely_authoritative),
            TemporalClass.rank(TemporalClass.fresh_with_bounded_lag),
        )
        self.assertGreater(
            TemporalClass.rank(TemporalClass.fresh_with_bounded_lag),
            TemporalClass.rank(TemporalClass.stale_but_usable),
        )
        self.assertGreater(
            TemporalClass.rank(TemporalClass.stale_but_usable),
            TemporalClass.rank(TemporalClass.deadline_missed_or_timed_out),
        )
        self.assertGreater(
            TemporalClass.rank(TemporalClass.deadline_missed_or_timed_out),
            TemporalClass.rank(TemporalClass.temporally_unreliable),
        )

    @_skip_if_unavailable
    def test_AF02_timely_authoritative_has_highest_rank(self):
        highest = max(TemporalClass, key=TemporalClass.rank)
        self.assertEqual(highest, TemporalClass.timely_authoritative)

    @_skip_if_unavailable
    def test_AF03_temporally_unreliable_has_lowest_rank(self):
        lowest = min(TemporalClass, key=TemporalClass.rank)
        self.assertEqual(lowest, TemporalClass.temporally_unreliable)

    # -----------------------------------------------------------------------
    # Group AG — TemporalClass.from_string fallback
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AG01_from_string_valid_value(self):
        self.assertEqual(
            TemporalClass.from_string("timely_authoritative"),
            TemporalClass.timely_authoritative,
        )
        self.assertEqual(
            TemporalClass.from_string("fresh_with_bounded_lag"),
            TemporalClass.fresh_with_bounded_lag,
        )
        self.assertEqual(
            TemporalClass.from_string("stale_but_usable"),
            TemporalClass.stale_but_usable,
        )
        self.assertEqual(
            TemporalClass.from_string("deadline_missed_or_timed_out"),
            TemporalClass.deadline_missed_or_timed_out,
        )
        self.assertEqual(
            TemporalClass.from_string("temporally_unreliable"),
            TemporalClass.temporally_unreliable,
        )

    @_skip_if_unavailable
    def test_AG02_from_string_unknown_defaults_to_unreliable(self):
        self.assertEqual(
            TemporalClass.from_string("some_unknown_class"),
            TemporalClass.temporally_unreliable,
        )

    @_skip_if_unavailable
    def test_AG03_from_string_non_string_defaults_to_unreliable(self):
        self.assertEqual(
            TemporalClass.from_string(None),  # type: ignore[arg-type]
            TemporalClass.temporally_unreliable,
        )

    # -----------------------------------------------------------------------
    # Group AH — SystemFinalAcceptanceEvaluator includes temporal_semantics
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AH01_system_final_acceptance_evaluator_includes_temporal_semantics(self):
        """SystemFinalAcceptanceEvaluator.evaluate() must include temporal_semantics."""
        _ACCEPTANCE_AVAILABLE = False
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
            )
            _ACCEPTANCE_AVAILABLE = True
        except ImportError:
            pass

        if not _ACCEPTANCE_AVAILABLE:
            self.skipTest(
                "core.system_final_acceptance_verdict not available"
            )

        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        checklist = report.checklist
        self.assertIn("temporal_semantics", checklist)

    # -----------------------------------------------------------------------
    # Group AI — AcceptanceDimensionId.all_dimensions() includes temporal_semantics
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AI01_all_dimensions_includes_temporal_semantics(self):
        _ACCEPTANCE_AVAILABLE = False
        try:
            from core.system_final_acceptance_verdict import AcceptanceDimensionId
            _ACCEPTANCE_AVAILABLE = True
        except ImportError:
            pass

        if not _ACCEPTANCE_AVAILABLE:
            self.skipTest(
                "core.system_final_acceptance_verdict not available"
            )

        dims = AcceptanceDimensionId.all_dimensions()
        dim_values = [d.value for d in dims]
        self.assertIn("temporal_semantics", dim_values)

    @_skip_if_unavailable
    def test_AI02_all_dimensions_has_seventeen_entries(self):
        _ACCEPTANCE_AVAILABLE = False
        try:
            from core.system_final_acceptance_verdict import AcceptanceDimensionId
            _ACCEPTANCE_AVAILABLE = True
        except ImportError:
            pass

        if not _ACCEPTANCE_AVAILABLE:
            self.skipTest(
                "core.system_final_acceptance_verdict not available"
            )

        dims = AcceptanceDimensionId.all_dimensions()
        self.assertEqual(len(dims), 17)

    # -----------------------------------------------------------------------
    # Group AJ — AcceptanceDimensionId probe returns pending
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AJ01_temporal_semantics_probe_returns_pending_or_unresolved(self):
        """Probe should return pending (structure present) or unresolved."""
        _ACCEPTANCE_AVAILABLE = False
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                DimensionStatus,
            )
            _ACCEPTANCE_AVAILABLE = True
        except ImportError:
            pass

        if not _ACCEPTANCE_AVAILABLE:
            self.skipTest(
                "core.system_final_acceptance_verdict not available"
            )

        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        item = report.checklist.get("temporal_semantics")
        self.assertIsNotNone(item)
        # Should not be 'accepted' in a baseline context with no live evidence
        self.assertIn(
            item.status,
            [DimensionStatus.pending, DimensionStatus.unresolved],
        )

    # -----------------------------------------------------------------------
    # Group AK — Zero-evidence probe must not return timely_authoritative
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AK01_zero_evidence_probe_not_timely_authoritative(self):
        """TIMESTAMP_PRESENCE_IS_NOT_TEMPORAL_AUTHORITY_POLICY guard."""
        verdict = build_baseline_temporal_verdict()
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.timely_authoritative
        )
        self.assertFalse(verdict.is_timely_authoritative)

    @_skip_if_unavailable
    def test_AK02_zero_evidence_probe_not_fresh_bounded_lag(self):
        verdict = build_baseline_temporal_verdict()
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.fresh_with_bounded_lag
        )

    @_skip_if_unavailable
    def test_AK03_zero_evidence_probe_not_stale_but_usable(self):
        verdict = build_baseline_temporal_verdict()
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.stale_but_usable
        )

    @_skip_if_unavailable
    def test_AK04_zero_evidence_probe_not_deadline_missed(self):
        verdict = build_baseline_temporal_verdict()
        self.assertNotEqual(
            verdict.temporal_class, TemporalClass.deadline_missed_or_timed_out
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
