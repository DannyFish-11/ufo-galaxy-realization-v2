#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr15_telemetry_freshness_contract.py
===============================================
PR-15 — Real-Time Observability / Telemetry Freshness Semantics Contract.

Validates that:

1. **Telemetry freshness taxonomy is defined and importable** (five classes).
2. **realtime_authoritative** classification when all six conditions are met:
   confirmed real-time channel, all channels active, freshness within window,
   authoritative delivery path, no delivery gaps, no sampling loss.
3. **fresh_not_realtime** when data is within freshness window and all
   channels are active, but at least one realtime_authoritative condition
   is missing (e.g. polling path, delivery gap, non-authoritative path).
4. **delayed_observable** when post-hoc evidence only, or when stale data
   is present with all channels active and known lag.
5. **partially_observable** when some channels are active but not all.
6. **telemetry_unreliable** when no evidence, or explicit_unreliable=True.
7. **Stale telemetry must downgrade** — never realtime_authoritative or
   fresh_not_realtime with stale samples.
8. **Post-hoc evidence must not claim realtime_authoritative** — ever.
9. **Signal presence alone must not claim realtime_authoritative**.
10. **Partial channels block realtime_authoritative** — always.
11. **Missing evidence defaults to telemetry_unreliable** (fail-conservative).
12. **explicit_unreliable always wins** over any other evidence.
13. **Policy sentinels are importable and non-empty**.
14. **to_dict() / from_dict() round-trip** produces valid output.
15. **build_baseline_telemetry_freshness_verdict()** returns
    telemetry_unreliable (fail-conservative baseline).
16. **SystemFinalAcceptanceEvaluator includes telemetry_freshness dimension**.
17. **AcceptanceDimensionId.all_dimensions() includes telemetry_freshness**.

Test groups
-----------
 A)  Sentinel imports — PR-15 authority and policy constants importable.
 B)  Enum completeness — all five TelemetryFreshnessClass values exist.
 C)  Enum completeness — ObservationPathKind values exist.
 D)  realtime_authoritative — all six conditions met, no post-hoc.
 E)  realtime_authoritative — stale data blocks it (freshness_within_window=False).
 F)  realtime_authoritative — post_hoc_evidence_only blocks it.
 G)  realtime_authoritative — missing realtime_channel_confirmed blocks it.
 H)  realtime_authoritative — delivery_path_authoritative=False blocks it.
 I)  realtime_authoritative — no_delivery_gaps=False blocks it.
 J)  realtime_authoritative — no_sampling_loss=False blocks it.
 K)  realtime_authoritative — partial channels block it.
 L)  fresh_not_realtime — fresh data, all channels, but not real-time confirmed.
 M)  fresh_not_realtime — fresh data, all channels, but delivery gap present.
 N)  fresh_not_realtime — fresh data, all channels, but sampling loss.
 O)  fresh_not_realtime — does NOT require realtime_channel_confirmed.
 P)  delayed_observable — post_hoc_evidence_only=True.
 Q)  delayed_observable — stale + all channels active + lag known.
 R)  delayed_observable — post-hoc does NOT produce realtime_authoritative.
 S)  partially_observable — not all channels active, some evidence present.
 T)  partially_observable — active channels still produce partial, not fresh.
 U)  telemetry_unreliable — zero evidence (fail-conservative baseline).
 V)  telemetry_unreliable — explicit_unreliable=True always wins.
 W)  telemetry_unreliable — explicit_unreliable overrides everything.
 X)  telemetry_unreliable vs delayed_observable distinction.
 Y)  TelemetryFreshnessEvidence to_dict / from_dict round-trip.
 Z)  TelemetryFreshnessVerdict to_dict / from_dict round-trip.
 AA) is_realtime_authoritative flag — only True for realtime_authoritative.
 AB) is_fresh flag — True for realtime_authoritative and fresh_not_realtime.
 AC) is_delayed flag — True only for delayed_observable.
 AD) is_partial flag — True only for partially_observable.
 AE) is_unreliable flag — True only for telemetry_unreliable.
 AF) downgrade_reasons non-empty when downgrade occurred.
 AG) build_baseline_telemetry_freshness_verdict() returns telemetry_unreliable.
 AH) SystemFinalAcceptanceEvaluator includes telemetry_freshness dimension.
 AI) AcceptanceDimensionId.all_dimensions() includes telemetry_freshness.
 AJ) AcceptanceDimensionId.telemetry_freshness probe returns pending with
     correct conservative baseline.
 AK) Zero-evidence probe returns unresolved when it returns
     realtime_authoritative (misconfiguration guard).
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
    from core.telemetry_freshness_contract import (
        # Authority / policy sentinels
        TELEMETRY_FRESHNESS_CONTRACT_AUTHORITY,
        TELEMETRY_FRESHNESS_CONTRACT_PR15_SENTINEL,
        FRESHNESS_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY,
        SIGNAL_PRESENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY,
        POST_HOC_EVIDENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY,
        PARTIAL_CHANNELS_BLOCK_REALTIME_AUTHORITATIVE_POLICY,
        STALE_TELEMETRY_MUST_DOWNGRADE_CLASS_POLICY,
        DELIVERY_GAP_MUST_DOWNGRADE_FROM_REALTIME_POLICY,
        TELEMETRY_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY,
        # Enumerations
        TelemetryFreshnessClass,
        ObservationPathKind,
        # Data classes
        TelemetryFreshnessEvidence,
        TelemetryFreshnessVerdict,
        # Functions
        classify_telemetry_freshness,
        build_telemetry_freshness_verdict,
        build_baseline_telemetry_freshness_verdict,
    )
    _MODULE_AVAILABLE = True
except ImportError as _imp_err:
    print(f"SKIP: core.telemetry_freshness_contract unavailable: {_imp_err}")


def _skip_if_unavailable(test_fn):
    """Decorator: skip test if the module is not available."""
    def wrapper(self):
        if not _MODULE_AVAILABLE:
            self.skipTest("core.telemetry_freshness_contract not available")
        return test_fn(self)
    wrapper.__name__ = test_fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# Helper: build evidence with named overrides
# ---------------------------------------------------------------------------

def _ev(**kwargs) -> "TelemetryFreshnessEvidence":
    """Build a TelemetryFreshnessEvidence with default-conservative values."""
    return TelemetryFreshnessEvidence(
        realtime_channel_confirmed=kwargs.get("realtime_channel_confirmed", False),
        all_required_channels_active=kwargs.get("all_required_channels_active", False),
        freshness_within_window=kwargs.get("freshness_within_window", False),
        delivery_path_authoritative=kwargs.get("delivery_path_authoritative", False),
        no_delivery_gaps=kwargs.get("no_delivery_gaps", False),
        no_sampling_loss=kwargs.get("no_sampling_loss", False),
        evidence_lag_known=kwargs.get("evidence_lag_known", False),
        post_hoc_evidence_only=kwargs.get("post_hoc_evidence_only", False),
        explicit_unreliable=kwargs.get("explicit_unreliable", False),
        observation_path_kind=kwargs.get(
            "observation_path_kind", ObservationPathKind.unknown
        ),
        participant_id=kwargs.get("participant_id"),
        trace_id=kwargs.get("trace_id"),
    )


def _ev_realtime_authoritative() -> "TelemetryFreshnessEvidence":
    """Convenience: build fully-populated realtime_authoritative evidence."""
    return _ev(
        realtime_channel_confirmed=True,
        all_required_channels_active=True,
        freshness_within_window=True,
        delivery_path_authoritative=True,
        no_delivery_gaps=True,
        no_sampling_loss=True,
        post_hoc_evidence_only=False,
        observation_path_kind=ObservationPathKind.realtime_push,
    )


# ===========================================================================
# Test class
# ===========================================================================


class TestTelemetryFreshnessContract(unittest.TestCase):

    # -----------------------------------------------------------------------
    # Group A — Sentinel imports
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_A01_authority_sentinel_importable_and_nonempty(self):
        self.assertIsInstance(TELEMETRY_FRESHNESS_CONTRACT_AUTHORITY, str)
        self.assertGreater(len(TELEMETRY_FRESHNESS_CONTRACT_AUTHORITY), 0)

    @_skip_if_unavailable
    def test_A02_pr15_sentinel_importable_and_nonempty(self):
        self.assertIsInstance(TELEMETRY_FRESHNESS_CONTRACT_PR15_SENTINEL, str)
        self.assertIn("PR15", TELEMETRY_FRESHNESS_CONTRACT_PR15_SENTINEL)

    @_skip_if_unavailable
    def test_A03_policy_sentinels_are_nonempty_strings(self):
        for sentinel in [
            FRESHNESS_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY,
            SIGNAL_PRESENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY,
            POST_HOC_EVIDENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY,
            PARTIAL_CHANNELS_BLOCK_REALTIME_AUTHORITATIVE_POLICY,
            STALE_TELEMETRY_MUST_DOWNGRADE_CLASS_POLICY,
            DELIVERY_GAP_MUST_DOWNGRADE_FROM_REALTIME_POLICY,
            TELEMETRY_ABSENCE_DEFAULTS_TO_UNRELIABLE_POLICY,
        ]:
            with self.subTest(sentinel=sentinel[:40]):
                self.assertIsInstance(sentinel, str)
                self.assertGreater(len(sentinel), 20)

    @_skip_if_unavailable
    def test_A04_signal_presence_policy_references_realtime_authoritative(self):
        self.assertIn(
            "realtime_authoritative",
            SIGNAL_PRESENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY,
        )

    @_skip_if_unavailable
    def test_A05_post_hoc_policy_references_realtime_authoritative(self):
        self.assertIn(
            "realtime_authoritative",
            POST_HOC_EVIDENCE_MUST_NOT_CLAIM_REALTIME_AUTHORITATIVE_POLICY,
        )

    @_skip_if_unavailable
    def test_A06_partial_channels_policy_references_blocking(self):
        self.assertIn(
            "BLOCK",
            PARTIAL_CHANNELS_BLOCK_REALTIME_AUTHORITATIVE_POLICY,
        )

    # -----------------------------------------------------------------------
    # Group B — TelemetryFreshnessClass enum completeness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_B01_five_classes_exist(self):
        classes = [c.value for c in TelemetryFreshnessClass]
        self.assertIn("realtime_authoritative", classes)
        self.assertIn("fresh_not_realtime", classes)
        self.assertIn("delayed_observable", classes)
        self.assertIn("partially_observable", classes)
        self.assertIn("telemetry_unreliable", classes)

    @_skip_if_unavailable
    def test_B02_exactly_five_classes(self):
        self.assertEqual(len(list(TelemetryFreshnessClass)), 5)

    @_skip_if_unavailable
    def test_B03_class_values_are_strings(self):
        for cls in TelemetryFreshnessClass:
            self.assertIsInstance(cls.value, str)

    # -----------------------------------------------------------------------
    # Group C — ObservationPathKind enum completeness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_C01_observation_path_kinds_exist(self):
        kinds = [k.value for k in ObservationPathKind]
        self.assertIn("realtime_push", kinds)
        self.assertIn("polling", kinds)
        self.assertIn("streaming_with_lag", kinds)
        self.assertIn("batch_ingestion", kinds)
        self.assertIn("post_hoc_replay", kinds)
        self.assertIn("unknown", kinds)

    # -----------------------------------------------------------------------
    # Group D — realtime_authoritative classification
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_D01_all_six_conditions_produces_realtime_authoritative(self):
        evidence = _ev_realtime_authoritative()
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.realtime_authoritative,
        )

    @_skip_if_unavailable
    def test_D02_realtime_authoritative_flag_true(self):
        verdict = classify_telemetry_freshness(_ev_realtime_authoritative())
        self.assertTrue(verdict.is_realtime_authoritative)

    @_skip_if_unavailable
    def test_D03_realtime_authoritative_is_fresh_true(self):
        verdict = classify_telemetry_freshness(_ev_realtime_authoritative())
        self.assertTrue(verdict.is_fresh)

    @_skip_if_unavailable
    def test_D04_realtime_authoritative_is_delayed_false(self):
        verdict = classify_telemetry_freshness(_ev_realtime_authoritative())
        self.assertFalse(verdict.is_delayed)

    @_skip_if_unavailable
    def test_D05_realtime_authoritative_downgrade_reasons_empty(self):
        verdict = classify_telemetry_freshness(_ev_realtime_authoritative())
        self.assertEqual(verdict.downgrade_reasons, [])

    @_skip_if_unavailable
    def test_D06_realtime_authoritative_is_partial_false(self):
        verdict = classify_telemetry_freshness(_ev_realtime_authoritative())
        self.assertFalse(verdict.is_partial)

    @_skip_if_unavailable
    def test_D07_realtime_authoritative_is_unreliable_false(self):
        verdict = classify_telemetry_freshness(_ev_realtime_authoritative())
        self.assertFalse(verdict.is_unreliable)

    # -----------------------------------------------------------------------
    # Group E — stale data blocks realtime_authoritative
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_E01_stale_data_not_realtime_authoritative(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=False,  # stale
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.realtime_authoritative,
        )

    @_skip_if_unavailable
    def test_E02_stale_data_not_fresh_not_realtime(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=False,  # stale
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.fresh_not_realtime,
        )

    @_skip_if_unavailable
    def test_E03_stale_with_all_channels_and_lag_known_is_delayed_observable(self):
        evidence = _ev(
            all_required_channels_active=True,
            freshness_within_window=False,
            evidence_lag_known=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.delayed_observable,
        )

    # -----------------------------------------------------------------------
    # Group F — post-hoc evidence blocks realtime_authoritative
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_F01_post_hoc_only_not_realtime_authoritative(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
            post_hoc_evidence_only=True,  # blocks realtime_authoritative
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.realtime_authoritative,
        )

    @_skip_if_unavailable
    def test_F02_post_hoc_only_produces_delayed_observable(self):
        evidence = _ev(
            all_required_channels_active=True,
            post_hoc_evidence_only=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.delayed_observable,
        )

    @_skip_if_unavailable
    def test_F03_post_hoc_is_delayed_true(self):
        evidence = _ev(
            all_required_channels_active=True,
            post_hoc_evidence_only=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertTrue(verdict.is_delayed)

    @_skip_if_unavailable
    def test_F04_post_hoc_is_realtime_authoritative_false(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
            post_hoc_evidence_only=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertFalse(verdict.is_realtime_authoritative)

    # -----------------------------------------------------------------------
    # Group G — missing realtime_channel_confirmed blocks realtime_authoritative
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_G01_no_realtime_channel_not_realtime_authoritative(self):
        evidence = _ev(
            realtime_channel_confirmed=False,  # missing
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.realtime_authoritative,
        )

    @_skip_if_unavailable
    def test_G02_no_realtime_channel_but_fresh_data_is_fresh_not_realtime(self):
        evidence = _ev(
            realtime_channel_confirmed=False,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.fresh_not_realtime,
        )

    # -----------------------------------------------------------------------
    # Group H — delivery_path_authoritative=False blocks realtime_authoritative
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_H01_non_authoritative_path_not_realtime_authoritative(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=False,  # not authoritative
            no_delivery_gaps=True,
            no_sampling_loss=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.realtime_authoritative,
        )

    @_skip_if_unavailable
    def test_H02_non_authoritative_fresh_path_is_fresh_not_realtime(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=False,
            no_delivery_gaps=True,
            no_sampling_loss=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.fresh_not_realtime,
        )

    # -----------------------------------------------------------------------
    # Group I — delivery gaps block realtime_authoritative
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_I01_delivery_gaps_not_realtime_authoritative(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=False,  # gaps detected
            no_sampling_loss=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.realtime_authoritative,
        )

    @_skip_if_unavailable
    def test_I02_delivery_gaps_fresh_data_is_fresh_not_realtime(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=False,
            no_sampling_loss=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.fresh_not_realtime,
        )

    # -----------------------------------------------------------------------
    # Group J — sampling loss blocks realtime_authoritative
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_J01_sampling_loss_not_realtime_authoritative(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=False,  # sampling loss
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.realtime_authoritative,
        )

    @_skip_if_unavailable
    def test_J02_sampling_loss_fresh_data_is_fresh_not_realtime(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=False,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.fresh_not_realtime,
        )

    # -----------------------------------------------------------------------
    # Group K — partial channels block realtime_authoritative
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_K01_partial_channels_not_realtime_authoritative(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=False,  # partial
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.realtime_authoritative,
        )

    @_skip_if_unavailable
    def test_K02_partial_channels_with_some_fresh_evidence_is_partially_observable(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=False,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.partially_observable,
        )

    # -----------------------------------------------------------------------
    # Group L — fresh_not_realtime classification
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_L01_polling_fresh_all_channels_is_fresh_not_realtime(self):
        evidence = _ev(
            realtime_channel_confirmed=False,  # polling, not confirmed realtime
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
            observation_path_kind=ObservationPathKind.polling,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.fresh_not_realtime,
        )

    @_skip_if_unavailable
    def test_L02_fresh_not_realtime_is_fresh_true(self):
        evidence = _ev(
            all_required_channels_active=True,
            freshness_within_window=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.fresh_not_realtime,
        )
        self.assertTrue(verdict.is_fresh)

    @_skip_if_unavailable
    def test_L03_fresh_not_realtime_is_realtime_authoritative_false(self):
        evidence = _ev(
            all_required_channels_active=True,
            freshness_within_window=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertFalse(verdict.is_realtime_authoritative)

    # -----------------------------------------------------------------------
    # Group M — delivery gap produces fresh_not_realtime when data is fresh
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_M01_fresh_data_with_gap_is_fresh_not_realtime(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=False,
            no_sampling_loss=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.fresh_not_realtime,
        )

    # -----------------------------------------------------------------------
    # Group N — sampling loss produces fresh_not_realtime when data is fresh
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_N01_fresh_data_with_sampling_loss_is_fresh_not_realtime(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=False,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.fresh_not_realtime,
        )

    # -----------------------------------------------------------------------
    # Group O — fresh_not_realtime does NOT require realtime_channel_confirmed
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_O01_fresh_not_realtime_without_realtime_channel(self):
        evidence = _ev(
            realtime_channel_confirmed=False,
            all_required_channels_active=True,
            freshness_within_window=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.fresh_not_realtime,
        )

    # -----------------------------------------------------------------------
    # Group P — delayed_observable from post-hoc evidence
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_P01_post_hoc_only_with_some_evidence_is_delayed_observable(self):
        evidence = _ev(
            post_hoc_evidence_only=True,
            all_required_channels_active=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.delayed_observable,
        )

    @_skip_if_unavailable
    def test_P02_delayed_observable_is_delayed_true(self):
        evidence = _ev(
            post_hoc_evidence_only=True,
            all_required_channels_active=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertTrue(verdict.is_delayed)

    @_skip_if_unavailable
    def test_P03_delayed_observable_is_fresh_false(self):
        evidence = _ev(
            post_hoc_evidence_only=True,
            all_required_channels_active=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertFalse(verdict.is_fresh)

    # -----------------------------------------------------------------------
    # Group Q — delayed_observable from stale + all channels + lag known
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Q01_stale_all_channels_lag_known_is_delayed_observable(self):
        evidence = _ev(
            all_required_channels_active=True,
            freshness_within_window=False,
            evidence_lag_known=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.delayed_observable,
        )

    @_skip_if_unavailable
    def test_Q02_stale_without_lag_known_not_necessarily_delayed(self):
        """Stale data without measured lag and without all channels active
        should fall through to partially_observable or unreliable."""
        evidence = _ev(
            all_required_channels_active=False,
            freshness_within_window=False,
            evidence_lag_known=False,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.realtime_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group R — post-hoc does NOT produce realtime_authoritative
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_R01_post_hoc_replay_path_not_realtime_authoritative(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
            post_hoc_evidence_only=True,
            observation_path_kind=ObservationPathKind.post_hoc_replay,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertFalse(verdict.is_realtime_authoritative)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.realtime_authoritative,
        )

    # -----------------------------------------------------------------------
    # Group S — partially_observable classification
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_S01_some_active_channels_not_all_is_partially_observable(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=False,  # partial
            freshness_within_window=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.partially_observable,
        )

    @_skip_if_unavailable
    def test_S02_partially_observable_is_partial_true(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=False,
            freshness_within_window=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertTrue(verdict.is_partial)

    @_skip_if_unavailable
    def test_S03_partially_observable_is_realtime_authoritative_false(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=False,
            freshness_within_window=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertFalse(verdict.is_realtime_authoritative)

    # -----------------------------------------------------------------------
    # Group T — partial channels block fresh and realtime
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_T01_partial_channels_with_fresh_data_not_fresh_not_realtime(self):
        evidence = _ev(
            all_required_channels_active=False,
            freshness_within_window=True,
            realtime_channel_confirmed=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.fresh_not_realtime,
        )

    # -----------------------------------------------------------------------
    # Group U — telemetry_unreliable from zero evidence
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_U01_zero_evidence_produces_telemetry_unreliable(self):
        evidence = _ev()
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.telemetry_unreliable,
        )

    @_skip_if_unavailable
    def test_U02_zero_evidence_is_unreliable_true(self):
        evidence = _ev()
        verdict = classify_telemetry_freshness(evidence)
        self.assertTrue(verdict.is_unreliable)

    @_skip_if_unavailable
    def test_U03_zero_evidence_is_realtime_authoritative_false(self):
        evidence = _ev()
        verdict = classify_telemetry_freshness(evidence)
        self.assertFalse(verdict.is_realtime_authoritative)

    @_skip_if_unavailable
    def test_U04_zero_evidence_is_fresh_false(self):
        evidence = _ev()
        verdict = classify_telemetry_freshness(evidence)
        self.assertFalse(verdict.is_fresh)

    # -----------------------------------------------------------------------
    # Group V — explicit_unreliable always wins
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_V01_explicit_unreliable_produces_telemetry_unreliable(self):
        # Even with all other conditions for realtime_authoritative met
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
            explicit_unreliable=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.telemetry_unreliable,
        )

    @_skip_if_unavailable
    def test_V02_explicit_unreliable_is_unreliable_true(self):
        evidence = _ev(explicit_unreliable=True)
        verdict = classify_telemetry_freshness(evidence)
        self.assertTrue(verdict.is_unreliable)

    # -----------------------------------------------------------------------
    # Group W — explicit_unreliable overrides everything
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_W01_explicit_unreliable_overrides_all_positive_evidence(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
            evidence_lag_known=True,
            explicit_unreliable=True,
            observation_path_kind=ObservationPathKind.realtime_push,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.telemetry_unreliable,
        )
        self.assertFalse(verdict.is_realtime_authoritative)
        self.assertFalse(verdict.is_fresh)

    # -----------------------------------------------------------------------
    # Group X — telemetry_unreliable vs delayed_observable distinction
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_X01_stale_all_channels_lag_known_is_delayed_not_unreliable(self):
        evidence = _ev(
            all_required_channels_active=True,
            freshness_within_window=False,
            evidence_lag_known=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.delayed_observable,
        )
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.telemetry_unreliable,
        )

    @_skip_if_unavailable
    def test_X02_no_channels_no_lag_is_unreliable_not_delayed(self):
        evidence = _ev(
            all_required_channels_active=False,
            freshness_within_window=False,
            evidence_lag_known=False,
            post_hoc_evidence_only=False,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.delayed_observable,
        )

    # -----------------------------------------------------------------------
    # Group Y — TelemetryFreshnessEvidence to_dict / from_dict round-trip
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Y01_evidence_to_dict_round_trip(self):
        original = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
            observation_path_kind=ObservationPathKind.realtime_push,
            participant_id="test-participant",
            trace_id="trace-001",
        )
        d = original.to_dict()
        self.assertIsInstance(d, dict)
        restored = TelemetryFreshnessEvidence.from_dict(d)
        self.assertEqual(
            restored.realtime_channel_confirmed, original.realtime_channel_confirmed
        )
        self.assertEqual(
            restored.all_required_channels_active,
            original.all_required_channels_active,
        )
        self.assertEqual(
            restored.freshness_within_window, original.freshness_within_window
        )
        self.assertEqual(
            restored.observation_path_kind, original.observation_path_kind
        )
        self.assertEqual(restored.participant_id, original.participant_id)

    @_skip_if_unavailable
    def test_Y02_evidence_to_dict_is_json_serialisable(self):
        evidence = _ev_realtime_authoritative()
        d = evidence.to_dict()
        serialised = json.dumps(d)
        self.assertIsInstance(serialised, str)

    @_skip_if_unavailable
    def test_Y03_evidence_from_dict_with_unknown_path_kind_defaults_to_unknown(self):
        d = _ev().to_dict()
        d["observation_path_kind"] = "nonexistent_path_kind"
        restored = TelemetryFreshnessEvidence.from_dict(d)
        self.assertEqual(restored.observation_path_kind, ObservationPathKind.unknown)

    # -----------------------------------------------------------------------
    # Group Z — TelemetryFreshnessVerdict to_dict / from_dict round-trip
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Z01_verdict_to_dict_round_trip(self):
        verdict = classify_telemetry_freshness(_ev_realtime_authoritative())
        d = verdict.to_dict()
        self.assertIsInstance(d, dict)
        restored = TelemetryFreshnessVerdict.from_dict(d)
        self.assertEqual(
            restored.freshness_class, verdict.freshness_class
        )
        self.assertEqual(
            restored.is_realtime_authoritative, verdict.is_realtime_authoritative
        )
        self.assertEqual(restored.is_fresh, verdict.is_fresh)

    @_skip_if_unavailable
    def test_Z02_verdict_to_dict_is_json_serialisable(self):
        verdict = classify_telemetry_freshness(_ev())
        d = verdict.to_dict()
        serialised = json.dumps(d)
        self.assertIsInstance(serialised, str)

    @_skip_if_unavailable
    def test_Z03_verdict_from_dict_with_unknown_class_defaults_to_unreliable(self):
        d = classify_telemetry_freshness(_ev()).to_dict()
        d["freshness_class"] = "nonexistent_class"
        restored = TelemetryFreshnessVerdict.from_dict(d)
        self.assertEqual(
            restored.freshness_class,
            TelemetryFreshnessClass.telemetry_unreliable,
        )

    # -----------------------------------------------------------------------
    # Group AA — is_realtime_authoritative flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AA01_is_realtime_authoritative_only_true_for_that_class(self):
        for cls in TelemetryFreshnessClass:
            evidence = (
                _ev_realtime_authoritative()
                if cls == TelemetryFreshnessClass.realtime_authoritative
                else _ev()
            )
            if cls == TelemetryFreshnessClass.realtime_authoritative:
                verdict = classify_telemetry_freshness(evidence)
                self.assertTrue(verdict.is_realtime_authoritative)
            else:
                # Other classes — zero evidence produces unreliable
                verdict = classify_telemetry_freshness(_ev())
                self.assertFalse(verdict.is_realtime_authoritative)

    # -----------------------------------------------------------------------
    # Group AB — is_fresh flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AB01_is_fresh_true_for_realtime_authoritative(self):
        verdict = classify_telemetry_freshness(_ev_realtime_authoritative())
        self.assertTrue(verdict.is_fresh)

    @_skip_if_unavailable
    def test_AB02_is_fresh_true_for_fresh_not_realtime(self):
        evidence = _ev(
            all_required_channels_active=True,
            freshness_within_window=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class, TelemetryFreshnessClass.fresh_not_realtime
        )
        self.assertTrue(verdict.is_fresh)

    @_skip_if_unavailable
    def test_AB03_is_fresh_false_for_delayed_observable(self):
        evidence = _ev(
            all_required_channels_active=True,
            freshness_within_window=False,
            evidence_lag_known=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertFalse(verdict.is_fresh)

    # -----------------------------------------------------------------------
    # Group AC — is_delayed flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AC01_is_delayed_true_only_for_delayed_observable(self):
        evidence = _ev(
            all_required_channels_active=True,
            post_hoc_evidence_only=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class, TelemetryFreshnessClass.delayed_observable
        )
        self.assertTrue(verdict.is_delayed)

    @_skip_if_unavailable
    def test_AC02_is_delayed_false_for_realtime_authoritative(self):
        verdict = classify_telemetry_freshness(_ev_realtime_authoritative())
        self.assertFalse(verdict.is_delayed)

    # -----------------------------------------------------------------------
    # Group AD — is_partial flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AD01_is_partial_true_only_for_partially_observable(self):
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=False,
            freshness_within_window=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class, TelemetryFreshnessClass.partially_observable
        )
        self.assertTrue(verdict.is_partial)

    @_skip_if_unavailable
    def test_AD02_is_partial_false_for_realtime_authoritative(self):
        verdict = classify_telemetry_freshness(_ev_realtime_authoritative())
        self.assertFalse(verdict.is_partial)

    # -----------------------------------------------------------------------
    # Group AE — is_unreliable flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AE01_is_unreliable_true_for_telemetry_unreliable(self):
        verdict = classify_telemetry_freshness(_ev())
        self.assertEqual(
            verdict.freshness_class, TelemetryFreshnessClass.telemetry_unreliable
        )
        self.assertTrue(verdict.is_unreliable)

    @_skip_if_unavailable
    def test_AE02_is_unreliable_false_for_realtime_authoritative(self):
        verdict = classify_telemetry_freshness(_ev_realtime_authoritative())
        self.assertFalse(verdict.is_unreliable)

    # -----------------------------------------------------------------------
    # Group AF — downgrade_reasons non-empty on downgrade
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AF01_downgrade_reasons_nonempty_for_fresh_not_realtime(self):
        evidence = _ev(
            all_required_channels_active=True,
            freshness_within_window=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertEqual(
            verdict.freshness_class, TelemetryFreshnessClass.fresh_not_realtime
        )
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    @_skip_if_unavailable
    def test_AF02_downgrade_reasons_nonempty_for_telemetry_unreliable(self):
        verdict = classify_telemetry_freshness(_ev())
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    @_skip_if_unavailable
    def test_AF03_downgrade_reasons_empty_for_realtime_authoritative(self):
        verdict = classify_telemetry_freshness(_ev_realtime_authoritative())
        self.assertEqual(verdict.downgrade_reasons, [])

    # -----------------------------------------------------------------------
    # Group AG — build_baseline_telemetry_freshness_verdict
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AG01_baseline_verdict_returns_telemetry_unreliable(self):
        verdict = build_baseline_telemetry_freshness_verdict()
        self.assertEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.telemetry_unreliable,
        )

    @_skip_if_unavailable
    def test_AG02_baseline_verdict_is_unreliable_true(self):
        verdict = build_baseline_telemetry_freshness_verdict()
        self.assertTrue(verdict.is_unreliable)

    @_skip_if_unavailable
    def test_AG03_baseline_verdict_is_realtime_authoritative_false(self):
        verdict = build_baseline_telemetry_freshness_verdict()
        self.assertFalse(verdict.is_realtime_authoritative)

    @_skip_if_unavailable
    def test_AG04_build_telemetry_freshness_verdict_wrapper_equivalent(self):
        evidence = _ev_realtime_authoritative()
        v1 = classify_telemetry_freshness(evidence)
        v2 = build_telemetry_freshness_verdict(evidence)
        self.assertEqual(v1.freshness_class, v2.freshness_class)
        self.assertEqual(v1.is_realtime_authoritative, v2.is_realtime_authoritative)

    # -----------------------------------------------------------------------
    # Group AH — SystemFinalAcceptanceEvaluator includes telemetry_freshness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AH01_system_evaluator_has_telemetry_freshness_dimension(self):
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
            )
        except ImportError:
            self.skipTest("core.system_final_acceptance_verdict not available")
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        self.assertIn("telemetry_freshness", report.checklist)

    @_skip_if_unavailable
    def test_AH02_telemetry_freshness_dimension_has_valid_status(self):
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                DimensionStatus,
            )
        except ImportError:
            self.skipTest("core.system_final_acceptance_verdict not available")
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        item = report.checklist.get("telemetry_freshness")
        self.assertIsNotNone(item)
        self.assertIn(item.status, list(DimensionStatus))

    # -----------------------------------------------------------------------
    # Group AI — AcceptanceDimensionId.all_dimensions includes telemetry_freshness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AI01_all_dimensions_includes_telemetry_freshness(self):
        try:
            from core.system_final_acceptance_verdict import AcceptanceDimensionId
        except ImportError:
            self.skipTest("core.system_final_acceptance_verdict not available")
        dims = [d.value for d in AcceptanceDimensionId.all_dimensions()]
        self.assertIn("telemetry_freshness", dims)

    @_skip_if_unavailable
    def test_AI02_telemetry_freshness_is_a_valid_dimension_id(self):
        try:
            from core.system_final_acceptance_verdict import AcceptanceDimensionId
        except ImportError:
            self.skipTest("core.system_final_acceptance_verdict not available")
        self.assertIn(
            "telemetry_freshness",
            [d.value for d in AcceptanceDimensionId],
        )

    # -----------------------------------------------------------------------
    # Group AJ — AcceptanceDimensionId telemetry_freshness probe
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AJ01_telemetry_freshness_probe_returns_pending_with_baseline(self):
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                DimensionStatus,
            )
        except ImportError:
            self.skipTest("core.system_final_acceptance_verdict not available")
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        item = report.checklist.get("telemetry_freshness")
        self.assertIsNotNone(item)
        # The zero-evidence probe should return pending (contract wired) or
        # unresolved (module not available), but never accepted with no evidence.
        self.assertIn(
            item.status,
            [DimensionStatus.pending, DimensionStatus.unresolved],
        )

    @_skip_if_unavailable
    def test_AJ02_telemetry_freshness_probe_not_accepted_with_zero_evidence(self):
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                DimensionStatus,
            )
        except ImportError:
            self.skipTest("core.system_final_acceptance_verdict not available")
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        item = report.checklist.get("telemetry_freshness")
        self.assertIsNotNone(item)
        self.assertNotEqual(item.status, DimensionStatus.accepted)

    # -----------------------------------------------------------------------
    # Group AK — misconfiguration guard
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_AK01_zero_evidence_must_not_produce_realtime_authoritative(self):
        """Core contract invariant: zero-evidence MUST produce telemetry_unreliable."""
        verdict = build_baseline_telemetry_freshness_verdict()
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.realtime_authoritative,
        )

    @_skip_if_unavailable
    def test_AK02_signal_presence_alone_must_not_produce_realtime_authoritative(self):
        """Signal-present-but-nothing-else must not produce realtime_authoritative."""
        # Only one "signal" present (evidence_lag_known=True as a proxy for
        # "we know something arrived"), but no channel confirmation, freshness,
        # or delivery path.
        evidence = _ev(evidence_lag_known=True)
        verdict = classify_telemetry_freshness(evidence)
        self.assertNotEqual(
            verdict.freshness_class,
            TelemetryFreshnessClass.realtime_authoritative,
        )

    @_skip_if_unavailable
    def test_AK03_delayed_ingestion_must_not_be_realtime_authoritative(self):
        """Delayed/post-hoc ingestion must not claim realtime_authoritative."""
        evidence = _ev(
            post_hoc_evidence_only=True,
            realtime_channel_confirmed=True,
            all_required_channels_active=True,
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
            observation_path_kind=ObservationPathKind.post_hoc_replay,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertFalse(verdict.is_realtime_authoritative)

    @_skip_if_unavailable
    def test_AK04_partial_channel_availability_must_not_be_realtime_authoritative(self):
        """Partial channel availability must not claim realtime_authoritative."""
        evidence = _ev(
            realtime_channel_confirmed=True,
            all_required_channels_active=False,  # partial
            freshness_within_window=True,
            delivery_path_authoritative=True,
            no_delivery_gaps=True,
            no_sampling_loss=True,
        )
        verdict = classify_telemetry_freshness(evidence)
        self.assertFalse(verdict.is_realtime_authoritative)


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    unittest.main()
