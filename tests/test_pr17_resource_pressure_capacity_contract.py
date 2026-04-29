#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr17_resource_pressure_capacity_contract.py
=======================================================
PR-17 — Resource Pressure / Degraded-Capacity / Admission Semantics Contract.

Validates that:

1.  **Capacity taxonomy is defined and importable** (five classes).
2.  **Normal capacity** classification when all positive signals are present
    and no degradation signals are set.
3.  **Normal capacity requires all positive conditions** — any single missing
    condition or degradation signal prevents normal_capacity.
4.  **Degraded capacity** classification when resource pressure, throughput
    degradation, backpressure, or shed load is present.
5.  **Admission limited** classification when admission gate is active.
6.  **Best effort only** classification when best_effort_mode_active.
7.  **Unavailable** when no positive evidence or explicit_unavailable.
8.  **Backpressure must downgrade** from normal_capacity.
9.  **Admission gating must not claim normal_capacity** — ever.
10. **Load shedding must downgrade** from normal_capacity.
11. **Resource pressure must downgrade** from normal_capacity.
12. **Best-effort must not claim normal_capacity or degraded_capacity**.
13. **explicit_unavailable always wins** regardless of other flags.
14. **No positive evidence defaults to unavailable** (fail-conservative).
15. **Policy sentinels are importable and non-empty**.
16. **to_dict() / from_dict() round-trip** produces valid output.
17. **build_baseline_capacity_verdict()** returns unavailable.
18. **SystemFinalAcceptanceEvaluator includes resource_pressure_capacity**.
19. **AcceptanceDimensionId.all_dimensions() includes resource_pressure_capacity**.

Test groups
-----------
 A)  Sentinel imports — PR-17 authority and policy constants importable.
 B)  Enum completeness — all five CapacityClass values exist.
 C)  Enum completeness — ResourcePressureLevel values exist.
 D)  normal_capacity — all positive signals, no degradation.
 E)  normal_capacity — requires resource_pressure_within_normal_bounds.
 F)  normal_capacity — requires all_admission_gates_open.
 G)  normal_capacity — requires throughput_at_nominal_level.
 H)  normal_capacity — requires no_backpressure_active.
 I)  normal_capacity — requires no_shed_load_active.
 J)  normal_capacity — blocked by admission_gate_active.
 K)  normal_capacity — blocked by backpressure_active.
 L)  normal_capacity — blocked by shed_load_active.
 M)  normal_capacity — blocked by resource_pressure_observed.
 N)  normal_capacity — blocked by degraded_throughput_observed.
 O)  normal_capacity — blocked by capacity_uncertainty.
 P)  degraded_capacity — resource_pressure_observed.
 Q)  degraded_capacity — backpressure_active.
 R)  degraded_capacity — shed_load_active.
 S)  degraded_capacity — degraded_throughput_observed.
 T)  admission_limited — admission_gate_active=True.
 U)  admission_limited — takes priority over degraded signals.
 V)  best_effort_only — best_effort_mode_active=True.
 W)  best_effort_only — takes priority over admission_limited.
 X)  best_effort_only — takes priority over degraded_capacity.
 Y)  unavailable — zero evidence (fail-conservative baseline).
 Z)  unavailable — explicit_unavailable=True (always wins).
 AA) unavailable — explicit_unavailable overrides best_effort.
 AB) CapacityEvidence to_dict / from_dict round-trip.
 AC) CapacityVerdict to_dict / from_dict round-trip.
 AD) is_normal flag contract — only True for normal_capacity.
 AE) is_degraded flag contract — True for degraded_capacity only.
 AF) is_admission_limited flag contract.
 AG) is_best_effort_only flag contract.
 AH) is_unavailable flag contract.
 AI) downgrade_reasons is non-empty when a downgrade occurred.
 AJ) build_baseline_capacity_verdict() returns unavailable.
 AK) SystemFinalAcceptanceEvaluator includes resource_pressure_capacity.
 AL) AcceptanceDimensionId.all_dimensions() includes resource_pressure_capacity.
 AM) Probe returns pending when zero-evidence returns unavailable.
 AN) Probe returns unresolved when zero-evidence returns normal_capacity
     (misconfiguration guard).
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
    from core.resource_pressure_capacity_contract import (
        # Authority / policy sentinels
        RESOURCE_PRESSURE_CAPACITY_CONTRACT_AUTHORITY,
        RESOURCE_PRESSURE_CAPACITY_CONTRACT_PR17_SENTINEL,
        CAPACITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY,
        PARTIAL_SERVICE_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY,
        BACKPRESSURE_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_POLICY,
        ADMISSION_GATING_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY,
        SHED_LOAD_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_POLICY,
        BEST_EFFORT_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY,
        CAPACITY_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY,
        # Enumerations
        CapacityClass,
        ResourcePressureLevel,
        # Data classes
        CapacityEvidence,
        CapacityVerdict,
        # Functions
        classify_capacity,
        build_capacity_verdict,
        build_baseline_capacity_verdict,
    )
    _MODULE_AVAILABLE = True
except ImportError as _imp_err:
    print(f"SKIP: core.resource_pressure_capacity_contract unavailable: {_imp_err}")


def _skip_if_unavailable(test_fn):
    """Decorator: skip test if the module is not available."""
    def wrapper(self):
        if not _MODULE_AVAILABLE:
            self.skipTest("core.resource_pressure_capacity_contract not available")
        return test_fn(self)
    wrapper.__name__ = test_fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# Helper: build evidence with named overrides
# ---------------------------------------------------------------------------

def _ev(**kwargs) -> "CapacityEvidence":
    """Build a CapacityEvidence with default-conservative values."""
    return CapacityEvidence(
        resource_pressure_within_normal_bounds=kwargs.get(
            "resource_pressure_within_normal_bounds", False
        ),
        all_admission_gates_open=kwargs.get("all_admission_gates_open", False),
        throughput_at_nominal_level=kwargs.get("throughput_at_nominal_level", False),
        no_backpressure_active=kwargs.get("no_backpressure_active", False),
        no_shed_load_active=kwargs.get("no_shed_load_active", False),
        admission_gate_active=kwargs.get("admission_gate_active", False),
        degraded_throughput_observed=kwargs.get("degraded_throughput_observed", False),
        backpressure_active=kwargs.get("backpressure_active", False),
        shed_load_active=kwargs.get("shed_load_active", False),
        best_effort_mode_active=kwargs.get("best_effort_mode_active", False),
        resource_pressure_observed=kwargs.get("resource_pressure_observed", False),
        capacity_uncertainty=kwargs.get("capacity_uncertainty", False),
        explicit_unavailable=kwargs.get("explicit_unavailable", False),
        participant_id=kwargs.get("participant_id"),
        trace_id=kwargs.get("trace_id"),
    )


def _ev_normal() -> "CapacityEvidence":
    """Build a fully-normal capacity evidence (all positive, no degradation)."""
    return CapacityEvidence(
        resource_pressure_within_normal_bounds=True,
        all_admission_gates_open=True,
        throughput_at_nominal_level=True,
        no_backpressure_active=True,
        no_shed_load_active=True,
        admission_gate_active=False,
        degraded_throughput_observed=False,
        backpressure_active=False,
        shed_load_active=False,
        best_effort_mode_active=False,
        resource_pressure_observed=False,
        capacity_uncertainty=False,
        explicit_unavailable=False,
    )


# ===========================================================================
# Test class
# ===========================================================================


class TestResourcePressureCapacityContract(unittest.TestCase):

    # -----------------------------------------------------------------------
    # Group A — Sentinel imports
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_A01_authority_sentinel_importable_and_nonempty(self):
        self.assertIsInstance(RESOURCE_PRESSURE_CAPACITY_CONTRACT_AUTHORITY, str)
        self.assertGreater(len(RESOURCE_PRESSURE_CAPACITY_CONTRACT_AUTHORITY), 0)

    @_skip_if_unavailable
    def test_A02_pr17_sentinel_importable_and_nonempty(self):
        self.assertIsInstance(RESOURCE_PRESSURE_CAPACITY_CONTRACT_PR17_SENTINEL, str)
        self.assertIn("PR17", RESOURCE_PRESSURE_CAPACITY_CONTRACT_PR17_SENTINEL)

    @_skip_if_unavailable
    def test_A03_policy_sentinels_are_nonempty_strings(self):
        for sentinel in [
            CAPACITY_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY,
            PARTIAL_SERVICE_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY,
            BACKPRESSURE_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_POLICY,
            ADMISSION_GATING_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY,
            SHED_LOAD_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_POLICY,
            BEST_EFFORT_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY,
            CAPACITY_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY,
        ]:
            with self.subTest(sentinel=sentinel[:50]):
                self.assertIsInstance(sentinel, str)
                self.assertGreater(len(sentinel), 20)

    @_skip_if_unavailable
    def test_A04_partial_service_policy_references_normal_capacity(self):
        self.assertIn(
            "normal_capacity",
            PARTIAL_SERVICE_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY,
        )

    @_skip_if_unavailable
    def test_A05_backpressure_policy_references_normal_capacity(self):
        self.assertIn(
            "normal_capacity",
            BACKPRESSURE_MUST_DOWNGRADE_FROM_NORMAL_CAPACITY_POLICY,
        )

    @_skip_if_unavailable
    def test_A06_admission_gating_policy_references_normal_capacity(self):
        self.assertIn(
            "normal_capacity",
            ADMISSION_GATING_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY,
        )

    @_skip_if_unavailable
    def test_A07_best_effort_policy_references_best_effort_only(self):
        self.assertIn(
            "best_effort_only",
            BEST_EFFORT_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY,
        )

    # -----------------------------------------------------------------------
    # Group B — CapacityClass enum completeness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_B01_five_classes_exist(self):
        classes = [c.value for c in CapacityClass]
        self.assertIn("normal_capacity", classes)
        self.assertIn("degraded_capacity", classes)
        self.assertIn("admission_limited", classes)
        self.assertIn("best_effort_only", classes)
        self.assertIn("unavailable", classes)

    @_skip_if_unavailable
    def test_B02_exactly_five_classes(self):
        self.assertEqual(len(list(CapacityClass)), 5)

    @_skip_if_unavailable
    def test_B03_class_values_are_strings(self):
        for cls in CapacityClass:
            self.assertIsInstance(cls.value, str)

    # -----------------------------------------------------------------------
    # Group C — ResourcePressureLevel enum completeness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_C01_pressure_levels_exist(self):
        levels = [l.value for l in ResourcePressureLevel]
        self.assertIn("none", levels)
        self.assertIn("mild", levels)
        self.assertIn("moderate", levels)
        self.assertIn("severe", levels)
        self.assertIn("critical", levels)
        self.assertIn("unknown", levels)

    @_skip_if_unavailable
    def test_C02_level_values_are_strings(self):
        for level in ResourcePressureLevel:
            self.assertIsInstance(level.value, str)

    # -----------------------------------------------------------------------
    # Group D — normal_capacity classification
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_D01_all_positive_no_degradation_is_normal_capacity(self):
        evidence = _ev_normal()
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    @_skip_if_unavailable
    def test_D02_normal_capacity_sets_is_normal_true(self):
        verdict = classify_capacity(_ev_normal())
        self.assertTrue(verdict.is_normal)

    @_skip_if_unavailable
    def test_D03_normal_capacity_has_empty_downgrade_reasons(self):
        verdict = classify_capacity(_ev_normal())
        self.assertEqual(verdict.downgrade_reasons, [])

    @_skip_if_unavailable
    def test_D04_normal_capacity_has_nonempty_rationale(self):
        verdict = classify_capacity(_ev_normal())
        self.assertGreater(len(verdict.rationale), 0)

    # -----------------------------------------------------------------------
    # Group E — normal_capacity requires resource_pressure_within_normal_bounds
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_E01_missing_resource_pressure_within_normal_bounds_prevents_normal(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=False,  # missing
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
        )
        verdict = classify_capacity(evidence)
        self.assertNotEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    # -----------------------------------------------------------------------
    # Group F — normal_capacity requires all_admission_gates_open
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_F01_missing_all_admission_gates_open_prevents_normal(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=False,  # missing
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
        )
        verdict = classify_capacity(evidence)
        self.assertNotEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    # -----------------------------------------------------------------------
    # Group G — normal_capacity requires throughput_at_nominal_level
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_G01_missing_throughput_at_nominal_level_prevents_normal(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=False,  # missing
            no_backpressure_active=True,
            no_shed_load_active=True,
        )
        verdict = classify_capacity(evidence)
        self.assertNotEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    # -----------------------------------------------------------------------
    # Group H — normal_capacity requires no_backpressure_active
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_H01_missing_no_backpressure_active_prevents_normal(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=False,  # missing
            no_shed_load_active=True,
        )
        verdict = classify_capacity(evidence)
        self.assertNotEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    # -----------------------------------------------------------------------
    # Group I — normal_capacity requires no_shed_load_active
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_I01_missing_no_shed_load_active_prevents_normal(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=False,  # missing
        )
        verdict = classify_capacity(evidence)
        self.assertNotEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    # -----------------------------------------------------------------------
    # Group J — normal_capacity blocked by admission_gate_active
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_J01_admission_gate_active_blocks_normal_capacity(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            admission_gate_active=True,  # active gate
        )
        verdict = classify_capacity(evidence)
        self.assertNotEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    @_skip_if_unavailable
    def test_J02_admission_gate_active_produces_admission_limited(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            admission_gate_active=True,
        )
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.admission_limited)

    # -----------------------------------------------------------------------
    # Group K — normal_capacity blocked by backpressure_active
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_K01_backpressure_active_blocks_normal_capacity(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            backpressure_active=True,  # backpressure
        )
        verdict = classify_capacity(evidence)
        self.assertNotEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    # -----------------------------------------------------------------------
    # Group L — normal_capacity blocked by shed_load_active
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_L01_shed_load_active_blocks_normal_capacity(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            shed_load_active=True,  # shedding load
        )
        verdict = classify_capacity(evidence)
        self.assertNotEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    # -----------------------------------------------------------------------
    # Group M — normal_capacity blocked by resource_pressure_observed
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_M01_resource_pressure_observed_blocks_normal_capacity(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            resource_pressure_observed=True,  # pressure present
        )
        verdict = classify_capacity(evidence)
        self.assertNotEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    # -----------------------------------------------------------------------
    # Group N — normal_capacity blocked by degraded_throughput_observed
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_N01_degraded_throughput_blocks_normal_capacity(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            degraded_throughput_observed=True,  # degraded throughput
        )
        verdict = classify_capacity(evidence)
        self.assertNotEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    # -----------------------------------------------------------------------
    # Group O — normal_capacity blocked by capacity_uncertainty
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_O01_capacity_uncertainty_blocks_normal_capacity(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            capacity_uncertainty=True,  # uncertain
        )
        verdict = classify_capacity(evidence)
        self.assertNotEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    # -----------------------------------------------------------------------
    # Group P — degraded_capacity: resource_pressure_observed
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_P01_resource_pressure_observed_produces_degraded(self):
        evidence = _ev(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            resource_pressure_observed=True,
        )
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.degraded_capacity)

    @_skip_if_unavailable
    def test_P02_degraded_sets_is_degraded_true(self):
        evidence = _ev(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            resource_pressure_observed=True,
        )
        verdict = classify_capacity(evidence)
        self.assertTrue(verdict.is_degraded)

    # -----------------------------------------------------------------------
    # Group Q — degraded_capacity: backpressure_active
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Q01_backpressure_active_produces_degraded(self):
        evidence = _ev(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            backpressure_active=True,
        )
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.degraded_capacity)

    # -----------------------------------------------------------------------
    # Group R — degraded_capacity: shed_load_active
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_R01_shed_load_active_produces_degraded(self):
        evidence = _ev(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            shed_load_active=True,
        )
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.degraded_capacity)

    # -----------------------------------------------------------------------
    # Group S — degraded_capacity: degraded_throughput_observed
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_S01_degraded_throughput_produces_degraded(self):
        evidence = _ev(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            degraded_throughput_observed=True,
        )
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.degraded_capacity)

    # -----------------------------------------------------------------------
    # Group T — admission_limited: admission_gate_active
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_T01_admission_gate_produces_admission_limited(self):
        evidence = _ev(admission_gate_active=True)
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.admission_limited)

    @_skip_if_unavailable
    def test_T02_admission_limited_sets_is_admission_limited(self):
        verdict = classify_capacity(_ev(admission_gate_active=True))
        self.assertTrue(verdict.is_admission_limited)

    # -----------------------------------------------------------------------
    # Group U — admission_limited takes priority over degraded
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_U01_admission_gate_overrides_degraded_signals(self):
        evidence = _ev(
            admission_gate_active=True,
            backpressure_active=True,
            resource_pressure_observed=True,
        )
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.admission_limited)

    # -----------------------------------------------------------------------
    # Group V — best_effort_only: best_effort_mode_active
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_V01_best_effort_mode_active_produces_best_effort_only(self):
        evidence = _ev(best_effort_mode_active=True)
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.best_effort_only)

    @_skip_if_unavailable
    def test_V02_best_effort_sets_is_best_effort_only(self):
        verdict = classify_capacity(_ev(best_effort_mode_active=True))
        self.assertTrue(verdict.is_best_effort_only)

    # -----------------------------------------------------------------------
    # Group W — best_effort_only takes priority over admission_limited
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_W01_best_effort_overrides_admission_limited(self):
        evidence = _ev(
            best_effort_mode_active=True,
            admission_gate_active=True,
        )
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.best_effort_only)

    # -----------------------------------------------------------------------
    # Group X — best_effort_only takes priority over degraded_capacity
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_X01_best_effort_overrides_degraded_capacity(self):
        evidence = _ev(
            best_effort_mode_active=True,
            backpressure_active=True,
            resource_pressure_observed=True,
        )
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.best_effort_only)

    # -----------------------------------------------------------------------
    # Group Y — unavailable: zero evidence (fail-conservative)
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Y01_zero_evidence_produces_unavailable(self):
        verdict = classify_capacity(CapacityEvidence())
        self.assertEqual(verdict.capacity_class, CapacityClass.unavailable)

    @_skip_if_unavailable
    def test_Y02_zero_evidence_sets_is_unavailable(self):
        verdict = classify_capacity(CapacityEvidence())
        self.assertTrue(verdict.is_unavailable)

    @_skip_if_unavailable
    def test_Y03_zero_evidence_evidence_present_is_false(self):
        verdict = classify_capacity(CapacityEvidence())
        self.assertFalse(verdict.evidence_present)

    # -----------------------------------------------------------------------
    # Group Z — unavailable: explicit_unavailable always wins
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Z01_explicit_unavailable_true_produces_unavailable(self):
        evidence = _ev(explicit_unavailable=True)
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.unavailable)

    @_skip_if_unavailable
    def test_Z02_explicit_unavailable_overrides_all_positive_signals(self):
        evidence = CapacityEvidence(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            explicit_unavailable=True,  # overrides everything
        )
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.unavailable)

    # -----------------------------------------------------------------------
    # Group AA — explicit_unavailable overrides best_effort
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AA01_explicit_unavailable_overrides_best_effort(self):
        evidence = _ev(
            best_effort_mode_active=True,
            explicit_unavailable=True,
        )
        verdict = classify_capacity(evidence)
        self.assertEqual(verdict.capacity_class, CapacityClass.unavailable)

    # -----------------------------------------------------------------------
    # Group AB — CapacityEvidence to_dict / from_dict round-trip
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AB01_capacity_evidence_to_dict_round_trips(self):
        evidence = _ev_normal()
        d = evidence.to_dict()
        self.assertIsInstance(d, dict)
        reconstructed = CapacityEvidence.from_dict(d)
        self.assertEqual(reconstructed.resource_pressure_within_normal_bounds, True)
        self.assertEqual(reconstructed.all_admission_gates_open, True)
        self.assertEqual(reconstructed.throughput_at_nominal_level, True)
        self.assertEqual(reconstructed.no_backpressure_active, True)
        self.assertEqual(reconstructed.no_shed_load_active, True)
        self.assertEqual(reconstructed.admission_gate_active, False)

    @_skip_if_unavailable
    def test_AB02_capacity_evidence_to_dict_is_json_serialisable(self):
        evidence = _ev_normal()
        d = evidence.to_dict()
        json_str = json.dumps(d)
        self.assertIsInstance(json_str, str)

    @_skip_if_unavailable
    def test_AB03_pressure_level_survives_round_trip(self):
        evidence = CapacityEvidence(
            pressure_level=ResourcePressureLevel.moderate,
        )
        d = evidence.to_dict()
        reconstructed = CapacityEvidence.from_dict(d)
        self.assertEqual(reconstructed.pressure_level, ResourcePressureLevel.moderate)

    # -----------------------------------------------------------------------
    # Group AC — CapacityVerdict to_dict / from_dict round-trip
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AC01_capacity_verdict_to_dict_round_trips(self):
        verdict = classify_capacity(_ev_normal())
        d = verdict.to_dict()
        self.assertIsInstance(d, dict)
        reconstructed = CapacityVerdict.from_dict(d)
        self.assertEqual(reconstructed.capacity_class, CapacityClass.normal_capacity)
        self.assertTrue(reconstructed.is_normal)

    @_skip_if_unavailable
    def test_AC02_capacity_verdict_to_dict_is_json_serialisable(self):
        verdict = classify_capacity(_ev_normal())
        d = verdict.to_dict()
        json_str = json.dumps(d)
        self.assertIsInstance(json_str, str)

    @_skip_if_unavailable
    def test_AC03_unavailable_verdict_round_trips(self):
        verdict = classify_capacity(CapacityEvidence())
        d = verdict.to_dict()
        reconstructed = CapacityVerdict.from_dict(d)
        self.assertEqual(reconstructed.capacity_class, CapacityClass.unavailable)
        self.assertTrue(reconstructed.is_unavailable)

    # -----------------------------------------------------------------------
    # Group AD — is_normal flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AD01_is_normal_only_for_normal_capacity(self):
        normal_verdict = classify_capacity(_ev_normal())
        self.assertTrue(normal_verdict.is_normal)

    @_skip_if_unavailable
    def test_AD02_is_normal_false_for_degraded(self):
        verdict = classify_capacity(_ev(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            backpressure_active=True,
        ))
        self.assertFalse(verdict.is_normal)

    @_skip_if_unavailable
    def test_AD03_is_normal_false_for_unavailable(self):
        verdict = classify_capacity(CapacityEvidence())
        self.assertFalse(verdict.is_normal)

    # -----------------------------------------------------------------------
    # Group AE — is_degraded flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AE01_is_degraded_true_for_degraded_capacity(self):
        verdict = classify_capacity(_ev(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            resource_pressure_observed=True,
        ))
        self.assertTrue(verdict.is_degraded)

    @_skip_if_unavailable
    def test_AE02_is_degraded_false_for_normal_capacity(self):
        verdict = classify_capacity(_ev_normal())
        self.assertFalse(verdict.is_degraded)

    # -----------------------------------------------------------------------
    # Group AF — is_admission_limited flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AF01_is_admission_limited_true_for_admission_limited(self):
        verdict = classify_capacity(_ev(admission_gate_active=True))
        self.assertTrue(verdict.is_admission_limited)

    @_skip_if_unavailable
    def test_AF02_is_admission_limited_false_for_normal(self):
        verdict = classify_capacity(_ev_normal())
        self.assertFalse(verdict.is_admission_limited)

    # -----------------------------------------------------------------------
    # Group AG — is_best_effort_only flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AG01_is_best_effort_only_true_for_best_effort(self):
        verdict = classify_capacity(_ev(best_effort_mode_active=True))
        self.assertTrue(verdict.is_best_effort_only)

    @_skip_if_unavailable
    def test_AG02_is_best_effort_only_false_for_normal(self):
        verdict = classify_capacity(_ev_normal())
        self.assertFalse(verdict.is_best_effort_only)

    # -----------------------------------------------------------------------
    # Group AH — is_unavailable flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AH01_is_unavailable_true_for_zero_evidence(self):
        verdict = classify_capacity(CapacityEvidence())
        self.assertTrue(verdict.is_unavailable)

    @_skip_if_unavailable
    def test_AH02_is_unavailable_false_for_normal_capacity(self):
        verdict = classify_capacity(_ev_normal())
        self.assertFalse(verdict.is_unavailable)

    @_skip_if_unavailable
    def test_AH03_is_unavailable_true_for_explicit_unavailable(self):
        verdict = classify_capacity(_ev(explicit_unavailable=True))
        self.assertTrue(verdict.is_unavailable)

    # -----------------------------------------------------------------------
    # Group AI — downgrade_reasons populated on downgrade
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AI01_downgrade_reasons_nonempty_when_degraded(self):
        verdict = classify_capacity(_ev(
            resource_pressure_within_normal_bounds=True,
            all_admission_gates_open=True,
            throughput_at_nominal_level=True,
            no_backpressure_active=True,
            no_shed_load_active=True,
            backpressure_active=True,
        ))
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    @_skip_if_unavailable
    def test_AI02_downgrade_reasons_nonempty_for_explicit_unavailable(self):
        verdict = classify_capacity(_ev(explicit_unavailable=True))
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    @_skip_if_unavailable
    def test_AI03_downgrade_reasons_nonempty_for_best_effort(self):
        verdict = classify_capacity(_ev(best_effort_mode_active=True))
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    # -----------------------------------------------------------------------
    # Group AJ — build_baseline_capacity_verdict returns unavailable
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AJ01_build_baseline_returns_unavailable(self):
        verdict = build_baseline_capacity_verdict()
        self.assertEqual(verdict.capacity_class, CapacityClass.unavailable)

    @_skip_if_unavailable
    def test_AJ02_build_baseline_not_normal_capacity(self):
        verdict = build_baseline_capacity_verdict()
        self.assertNotEqual(verdict.capacity_class, CapacityClass.normal_capacity)

    @_skip_if_unavailable
    def test_AJ03_build_baseline_evidence_present_false(self):
        verdict = build_baseline_capacity_verdict()
        self.assertFalse(verdict.evidence_present)

    # -----------------------------------------------------------------------
    # Group AK — SystemFinalAcceptanceEvaluator includes the dimension
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AK01_system_final_acceptance_evaluator_includes_dimension(self):
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                AcceptanceDimensionId,
                DimensionStatus,
                reset_system_acceptance_evaluator,
            )
        except ImportError as e:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {e}")

        reset_system_acceptance_evaluator()
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        checklist_keys = list(report.checklist.keys())
        self.assertIn(
            AcceptanceDimensionId.resource_pressure_capacity.value,
            checklist_keys,
        )

    @_skip_if_unavailable
    def test_AK02_resource_pressure_capacity_dimension_is_not_missing(self):
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                AcceptanceDimensionId,
                DimensionStatus,
                reset_system_acceptance_evaluator,
            )
        except ImportError as e:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {e}")

        reset_system_acceptance_evaluator()
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        item = report.get_checklist_item(AcceptanceDimensionId.resource_pressure_capacity)
        self.assertIsNotNone(item)

    @_skip_if_unavailable
    def test_AK03_dimension_status_is_pending_or_accepted_not_unresolved_for_zero_pressure(
        self,
    ):
        """Zero-evidence baseline probe should yield pending (contract wired)
        rather than unresolved (module not found or misconfigured)."""
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                AcceptanceDimensionId,
                DimensionStatus,
                reset_system_acceptance_evaluator,
            )
        except ImportError as e:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {e}")

        reset_system_acceptance_evaluator()
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        item = report.get_checklist_item(AcceptanceDimensionId.resource_pressure_capacity)
        self.assertIsNotNone(item)
        # Must be pending (contract wired, no live evidence yet), not unresolved
        self.assertIn(
            item.status.value,
            ("pending", "accepted"),
            msg=(
                f"Expected pending or accepted status (contract wired) but got "
                f"'{item.status.value}': {item.gap_description}"
            ),
        )

    # -----------------------------------------------------------------------
    # Group AL — AcceptanceDimensionId.all_dimensions() includes dimension
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AL01_all_dimensions_includes_resource_pressure_capacity(self):
        try:
            from core.system_final_acceptance_verdict import AcceptanceDimensionId
        except ImportError as e:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {e}")

        dim_values = [d.value for d in AcceptanceDimensionId.all_dimensions()]
        self.assertIn("resource_pressure_capacity", dim_values)

    @_skip_if_unavailable
    def test_AL02_all_dimensions_has_fifteen_items(self):
        try:
            from core.system_final_acceptance_verdict import AcceptanceDimensionId
        except ImportError as e:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {e}")

        self.assertEqual(len(AcceptanceDimensionId.all_dimensions()), 15)

    # -----------------------------------------------------------------------
    # Group AM — Probe returns pending for correct baseline
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AM01_probe_returns_pending_not_unresolved_when_module_available(self):
        """When the contract module is available and zero-evidence returns
        unavailable, the acceptance probe should return pending status."""
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                AcceptanceDimensionId,
                DimensionStatus,
                reset_system_acceptance_evaluator,
            )
        except ImportError as e:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {e}")

        reset_system_acceptance_evaluator()
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        item = report.get_checklist_item(AcceptanceDimensionId.resource_pressure_capacity)
        self.assertIsNotNone(item)
        self.assertNotEqual(
            item.status,
            DimensionStatus.unresolved,
            msg=(
                "resource_pressure_capacity probe returned unresolved — "
                "this means the contract module failed to import or the "
                "zero-evidence probe raised an exception.  "
                f"gap_description: {item.gap_description}"
            ),
        )

    # -----------------------------------------------------------------------
    # Group AN — Misconfiguration guard: normal_capacity from zero evidence
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AN01_zero_evidence_must_not_return_normal_capacity(self):
        """The contract must never return normal_capacity for zero-evidence input.

        This is the core policy: CAPACITY_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY.
        """
        verdict = build_baseline_capacity_verdict()
        self.assertNotEqual(
            verdict.capacity_class,
            CapacityClass.normal_capacity,
            msg=(
                "build_baseline_capacity_verdict() returned normal_capacity "
                "with no evidence.  This violates "
                "CAPACITY_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY."
            ),
        )

    @_skip_if_unavailable
    def test_AN02_partial_service_must_not_claim_normal_capacity(self):
        """Partial service (some evidence, some degradation) must not produce
        normal_capacity.  This is the core policy:
        PARTIAL_SERVICE_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY.
        """
        # Simulate: system is still processing some tasks (some positive signals)
        # but resource pressure is observed (degradation present)
        evidence = _ev(
            throughput_at_nominal_level=True,     # some capacity remains
            no_shed_load_active=True,             # not shedding load currently
            resource_pressure_observed=True,      # BUT resource pressure present
        )
        verdict = classify_capacity(evidence)
        self.assertNotEqual(
            verdict.capacity_class,
            CapacityClass.normal_capacity,
            msg=(
                "classify_capacity() returned normal_capacity with "
                "resource_pressure_observed=True.  This violates "
                "PARTIAL_SERVICE_MUST_NOT_CLAIM_NORMAL_CAPACITY_POLICY."
            ),
        )


if __name__ == "__main__":
    unittest.main()
