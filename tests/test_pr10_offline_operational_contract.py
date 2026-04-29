#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr10_offline_operational_contract.py
===============================================
PR-10 — Offline / Disconnected / Delayed-Sync Operational Contract.

Validates that:

1. **Offline operational taxonomy is defined and importable** (five classes).
2. **Healthy online state produces online_operational** when participant is
   connected, evidence is fresh, and no deferred sync path is declared.
3. **Disconnected but resumable** classification when participant is
   disconnected with a bounded reconnect window and inflight tracking active.
4. **Offline deferred sync** classification when deferred sync is acknowledged.
5. **Pending reconciliation** classification when reconciliation is in progress
   but not complete.
6. **Unavailable** when no evidence, no connectivity, or explicit_unavailable.
7. **Stale evidence must downgrade** — never online_operational with stale
   evidence.
8. **Deferred sync must not claim online_operational** — ever.
9. **Missing evidence defaults to unavailable** (fail-conservative).
10. **online_operational requires active connected state** — not just reconnect
    expected.
11. **Policy sentinels are importable and non-empty**.
12. **to_dict() / from_dict() round-trip** produces valid output.
13. **build_baseline_offline_operational_verdict()** returns unavailable
    (fail-conservative baseline).
14. **SystemFinalAcceptanceEvaluator includes offline_operational dimension**.
15. **AcceptanceDimensionId.all_dimensions() includes offline_operational**.

Test groups
-----------
 A)  Sentinel imports — PR-10 authority and policy constants importable.
 B)  Enum completeness — all five OfflineOperationalClass values exist.
 C)  Enum completeness — ConnectivityState and SyncMode values exist.
 D)  online_operational — connected, fresh evidence, no deferred sync.
 E)  online_operational — requires fresh evidence (stale → not online).
 F)  online_operational — requires connected state (disconnected → not online).
 G)  online_operational — deferred_sync_acknowledged blocks online_operational.
 H)  bounded_disconnected_resumable — disconnected + reconnect_expected +
     inflight_tracking_active.
 I)  bounded_disconnected_resumable — requires all three conditions.
 J)  offline_deferred_sync — deferred_sync_acknowledged=True.
 K)  offline_deferred_sync — even with connected state, deferred sync wins.
 L)  pending_reconciliation — reconciliation_in_progress and not complete.
 M)  pending_reconciliation — complete reconciliation does not produce pending.
 N)  unavailable — zero evidence (fail-conservative baseline).
 O)  unavailable — explicit_unavailable=True (always wins).
 P)  unavailable — explicit_unavailable overrides everything else.
 Q)  OfflineOperationalEvidence to_dict / from_dict round-trip.
 R)  OfflineOperationalVerdict to_dict / from_dict round-trip.
 S)  is_online_operational flag contract — only True for online_operational.
 T)  is_resumable flag contract — True for online_operational and
     bounded_disconnected_resumable only.
 U)  is_deferred flag contract — True for offline_deferred_sync and
     pending_reconciliation.
 V)  downgrade_reasons is non-empty when a downgrade occurred.
 W)  build_baseline_offline_operational_verdict() returns unavailable.
 X)  SystemFinalAcceptanceEvaluator includes offline_operational dimension.
 Y)  AcceptanceDimensionId.all_dimensions() includes offline_operational.
 Z)  AcceptanceDimensionId.offline_operational probe returns pending with
     correct conservative baseline.
 AA) Probe returns unresolved when zero-evidence returns online_operational
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
    from core.offline_operational_contract import (
        # Authority / policy sentinels
        OFFLINE_OPERATIONAL_CONTRACT_AUTHORITY,
        OFFLINE_OPERATIONAL_CONTRACT_PR10_SENTINEL,
        OPERATIONAL_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY,
        DEFERRED_SYNC_MUST_NOT_CLAIM_ONLINE_OPERATIONAL_POLICY,
        RECONNECT_EXPECTED_IS_NOT_ONLINE_OPERATIONAL_POLICY,
        EVIDENCE_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY,
        RECONCILIATION_INCOMPLETE_BLOCKS_ONLINE_OPERATIONAL_POLICY,
        STALE_EVIDENCE_MUST_DOWNGRADE_CLASS_POLICY,
        # Enumerations
        OfflineOperationalClass,
        ConnectivityState,
        SyncMode,
        # Data classes
        OfflineOperationalEvidence,
        OfflineOperationalVerdict,
        # Functions
        classify_offline_operational,
        build_offline_operational_verdict,
        build_baseline_offline_operational_verdict,
    )
    _MODULE_AVAILABLE = True
except ImportError as _imp_err:
    print(f"SKIP: core.offline_operational_contract unavailable: {_imp_err}")


def _skip_if_unavailable(test_fn):
    """Decorator: skip test if the module is not available."""
    def wrapper(self):
        if not _MODULE_AVAILABLE:
            self.skipTest("core.offline_operational_contract not available")
        return test_fn(self)
    wrapper.__name__ = test_fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# Helper: build evidence with named overrides
# ---------------------------------------------------------------------------

def _ev(**kwargs) -> "OfflineOperationalEvidence":
    """Build an OfflineOperationalEvidence with default-conservative values."""
    return OfflineOperationalEvidence(
        connectivity_state=kwargs.get(
            "connectivity_state", ConnectivityState.unknown
        ),
        evidence_fresh=kwargs.get("evidence_fresh", False),
        reconnect_expected=kwargs.get("reconnect_expected", False),
        inflight_tracking_active=kwargs.get("inflight_tracking_active", False),
        deferred_sync_acknowledged=kwargs.get("deferred_sync_acknowledged", False),
        reconciliation_in_progress=kwargs.get("reconciliation_in_progress", False),
        reconciliation_complete=kwargs.get("reconciliation_complete", False),
        explicit_unavailable=kwargs.get("explicit_unavailable", False),
        participant_id=kwargs.get("participant_id"),
        trace_id=kwargs.get("trace_id"),
    )


# ===========================================================================
# Test class
# ===========================================================================


class TestOfflineOperationalContract(unittest.TestCase):

    # -----------------------------------------------------------------------
    # Group A — Sentinel imports
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_A01_authority_sentinel_importable_and_nonempty(self):
        self.assertIsInstance(OFFLINE_OPERATIONAL_CONTRACT_AUTHORITY, str)
        self.assertGreater(len(OFFLINE_OPERATIONAL_CONTRACT_AUTHORITY), 0)

    @_skip_if_unavailable
    def test_A02_pr10_sentinel_importable_and_nonempty(self):
        self.assertIsInstance(OFFLINE_OPERATIONAL_CONTRACT_PR10_SENTINEL, str)
        self.assertIn("PR10", OFFLINE_OPERATIONAL_CONTRACT_PR10_SENTINEL)

    @_skip_if_unavailable
    def test_A03_policy_sentinels_are_nonempty_strings(self):
        for sentinel in [
            OPERATIONAL_TAXONOMY_IS_FIRST_CLASS_DIMENSION_POLICY,
            DEFERRED_SYNC_MUST_NOT_CLAIM_ONLINE_OPERATIONAL_POLICY,
            RECONNECT_EXPECTED_IS_NOT_ONLINE_OPERATIONAL_POLICY,
            EVIDENCE_ABSENCE_DEFAULTS_TO_UNAVAILABLE_POLICY,
            RECONCILIATION_INCOMPLETE_BLOCKS_ONLINE_OPERATIONAL_POLICY,
            STALE_EVIDENCE_MUST_DOWNGRADE_CLASS_POLICY,
        ]:
            with self.subTest(sentinel=sentinel[:40]):
                self.assertIsInstance(sentinel, str)
                self.assertGreater(len(sentinel), 20)

    @_skip_if_unavailable
    def test_A04_deferred_sync_policy_references_online_operational(self):
        self.assertIn(
            "online_operational",
            DEFERRED_SYNC_MUST_NOT_CLAIM_ONLINE_OPERATIONAL_POLICY,
        )

    @_skip_if_unavailable
    def test_A05_reconnect_policy_references_online_operational(self):
        self.assertIn(
            "online_operational",
            RECONNECT_EXPECTED_IS_NOT_ONLINE_OPERATIONAL_POLICY,
        )

    @_skip_if_unavailable
    def test_A06_reconciliation_policy_references_blocking(self):
        self.assertIn(
            "BLOCKS",
            RECONCILIATION_INCOMPLETE_BLOCKS_ONLINE_OPERATIONAL_POLICY,
        )

    # -----------------------------------------------------------------------
    # Group B — OfflineOperationalClass enum completeness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_B01_five_classes_exist(self):
        classes = [c.value for c in OfflineOperationalClass]
        self.assertIn("online_operational", classes)
        self.assertIn("bounded_disconnected_resumable", classes)
        self.assertIn("offline_deferred_sync", classes)
        self.assertIn("pending_reconciliation", classes)
        self.assertIn("unavailable", classes)

    @_skip_if_unavailable
    def test_B02_exactly_five_classes(self):
        self.assertEqual(len(list(OfflineOperationalClass)), 5)

    @_skip_if_unavailable
    def test_B03_class_values_are_strings(self):
        for cls in OfflineOperationalClass:
            self.assertIsInstance(cls.value, str)

    # -----------------------------------------------------------------------
    # Group C — ConnectivityState and SyncMode enum completeness
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_C01_connectivity_states_exist(self):
        states = [s.value for s in ConnectivityState]
        self.assertIn("connected", states)
        self.assertIn("disconnected", states)
        self.assertIn("offline", states)
        self.assertIn("unknown", states)

    @_skip_if_unavailable
    def test_C02_sync_modes_exist(self):
        modes = [m.value for m in SyncMode]
        self.assertIn("realtime", modes)
        self.assertIn("deferred", modes)
        self.assertIn("none", modes)

    # -----------------------------------------------------------------------
    # Group D — online_operational classification
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_D01_connected_fresh_evidence_no_deferred_is_online_operational(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
            deferred_sync_acknowledged=False,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.online_operational,
        )

    @_skip_if_unavailable
    def test_D02_online_operational_is_online_operational_flag_true(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertTrue(verdict.is_online_operational)

    @_skip_if_unavailable
    def test_D03_online_operational_is_resumable_true(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertTrue(verdict.is_resumable)

    @_skip_if_unavailable
    def test_D04_online_operational_is_deferred_false(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.is_deferred)

    @_skip_if_unavailable
    def test_D05_online_operational_downgrade_reasons_empty(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(verdict.downgrade_reasons, [])

    # -----------------------------------------------------------------------
    # Group E — stale evidence blocks online_operational
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_E01_connected_but_stale_evidence_not_online_operational(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=False,  # stale
        )
        verdict = classify_offline_operational(evidence)
        self.assertNotEqual(
            verdict.operational_class,
            OfflineOperationalClass.online_operational,
        )

    @_skip_if_unavailable
    def test_E02_stale_evidence_produces_downgrade_reason(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=False,
        )
        verdict = classify_offline_operational(evidence)
        reasons_text = " ".join(verdict.downgrade_reasons)
        self.assertIn("evidence_fresh=False", reasons_text)

    @_skip_if_unavailable
    def test_E03_stale_evidence_references_stale_policy(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=False,
        )
        verdict = classify_offline_operational(evidence)
        reasons_text = " ".join(verdict.downgrade_reasons)
        self.assertIn("STALE", reasons_text)

    # -----------------------------------------------------------------------
    # Group F — disconnected state blocks online_operational
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_F01_disconnected_state_not_online_operational(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.disconnected,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertNotEqual(
            verdict.operational_class,
            OfflineOperationalClass.online_operational,
        )

    @_skip_if_unavailable
    def test_F02_offline_state_not_online_operational(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.offline,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertNotEqual(
            verdict.operational_class,
            OfflineOperationalClass.online_operational,
        )

    @_skip_if_unavailable
    def test_F03_unknown_state_not_online_operational(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.unknown,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertNotEqual(
            verdict.operational_class,
            OfflineOperationalClass.online_operational,
        )

    # -----------------------------------------------------------------------
    # Group G — deferred_sync_acknowledged blocks online_operational
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_G01_deferred_sync_with_connected_not_online_operational(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
            deferred_sync_acknowledged=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertNotEqual(
            verdict.operational_class,
            OfflineOperationalClass.online_operational,
        )

    @_skip_if_unavailable
    def test_G02_deferred_sync_acknowledged_produces_offline_deferred_sync(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.offline,
            deferred_sync_acknowledged=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.offline_deferred_sync,
        )

    @_skip_if_unavailable
    def test_G03_deferred_sync_policy_referenced_in_downgrade(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
            deferred_sync_acknowledged=True,
        )
        verdict = classify_offline_operational(evidence)
        reasons_text = " ".join(verdict.downgrade_reasons)
        self.assertIn("DEFERRED_SYNC", reasons_text)

    # -----------------------------------------------------------------------
    # Group H — bounded_disconnected_resumable classification
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_H01_disconnected_with_reconnect_and_tracking_is_resumable(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.disconnected,
            reconnect_expected=True,
            inflight_tracking_active=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.bounded_disconnected_resumable,
        )

    @_skip_if_unavailable
    def test_H02_bounded_disconnected_is_resumable_flag_true(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.disconnected,
            reconnect_expected=True,
            inflight_tracking_active=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertTrue(verdict.is_resumable)

    @_skip_if_unavailable
    def test_H03_bounded_disconnected_not_online_operational(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.disconnected,
            reconnect_expected=True,
            inflight_tracking_active=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.is_online_operational)

    @_skip_if_unavailable
    def test_H04_bounded_disconnected_not_deferred(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.disconnected,
            reconnect_expected=True,
            inflight_tracking_active=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.is_deferred)

    # -----------------------------------------------------------------------
    # Group I — bounded_disconnected_resumable requires all three conditions
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_I01_disconnected_no_reconnect_expected_not_resumable_class(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.disconnected,
            reconnect_expected=False,
            inflight_tracking_active=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertNotEqual(
            verdict.operational_class,
            OfflineOperationalClass.bounded_disconnected_resumable,
        )

    @_skip_if_unavailable
    def test_I02_disconnected_no_inflight_tracking_not_resumable_class(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.disconnected,
            reconnect_expected=True,
            inflight_tracking_active=False,
        )
        verdict = classify_offline_operational(evidence)
        self.assertNotEqual(
            verdict.operational_class,
            OfflineOperationalClass.bounded_disconnected_resumable,
        )

    @_skip_if_unavailable
    def test_I03_connected_with_fresh_evidence_produces_online_not_resumable_class(self):
        # Connected + fresh evidence → online_operational (fresh evidence is the
        # determining factor; bounded_disconnected_resumable requires disconnected state)
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
            reconnect_expected=True,
            inflight_tracking_active=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.online_operational,
        )

    # -----------------------------------------------------------------------
    # Group J — offline_deferred_sync classification
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_J01_offline_with_deferred_sync_is_offline_deferred_sync(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.offline,
            deferred_sync_acknowledged=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.offline_deferred_sync,
        )

    @_skip_if_unavailable
    def test_J02_offline_deferred_sync_is_deferred_true(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.offline,
            deferred_sync_acknowledged=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertTrue(verdict.is_deferred)

    @_skip_if_unavailable
    def test_J03_offline_deferred_sync_not_online_operational(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.offline,
            deferred_sync_acknowledged=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.is_online_operational)

    @_skip_if_unavailable
    def test_J04_disconnected_with_deferred_sync_is_offline_deferred(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.disconnected,
            deferred_sync_acknowledged=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.offline_deferred_sync,
        )

    # -----------------------------------------------------------------------
    # Group K — deferred sync with connected state still produces offline class
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_K01_connected_plus_deferred_sync_is_not_online_operational(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
            deferred_sync_acknowledged=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertNotEqual(
            verdict.operational_class,
            OfflineOperationalClass.online_operational,
        )

    @_skip_if_unavailable
    def test_K02_connected_plus_deferred_sync_produces_offline_deferred_sync(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
            deferred_sync_acknowledged=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.offline_deferred_sync,
        )

    # -----------------------------------------------------------------------
    # Group L — pending_reconciliation classification
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_L01_reconciliation_in_progress_not_complete_is_pending(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
            reconciliation_in_progress=True,
            reconciliation_complete=False,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.pending_reconciliation,
        )

    @_skip_if_unavailable
    def test_L02_pending_reconciliation_is_deferred_true(self):
        evidence = _ev(
            reconciliation_in_progress=True,
            reconciliation_complete=False,
        )
        verdict = classify_offline_operational(evidence)
        self.assertTrue(verdict.is_deferred)

    @_skip_if_unavailable
    def test_L03_pending_reconciliation_not_online_operational(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
            reconciliation_in_progress=True,
            reconciliation_complete=False,
        )
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.is_online_operational)

    @_skip_if_unavailable
    def test_L04_pending_reconciliation_references_policy_in_downgrade(self):
        evidence = _ev(
            reconciliation_in_progress=True,
            reconciliation_complete=False,
        )
        verdict = classify_offline_operational(evidence)
        reasons_text = " ".join(verdict.downgrade_reasons)
        self.assertIn("RECONCILIATION", reasons_text)

    # -----------------------------------------------------------------------
    # Group M — complete reconciliation does not produce pending class
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_M01_reconciliation_complete_does_not_produce_pending(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
            reconciliation_in_progress=True,
            reconciliation_complete=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertNotEqual(
            verdict.operational_class,
            OfflineOperationalClass.pending_reconciliation,
        )

    @_skip_if_unavailable
    def test_M02_reconciliation_complete_with_connected_can_be_online(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
            reconciliation_in_progress=True,
            reconciliation_complete=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.online_operational,
        )

    # -----------------------------------------------------------------------
    # Group N — unavailable default (zero evidence)
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_N01_zero_evidence_defaults_to_unavailable(self):
        evidence = OfflineOperationalEvidence()
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.unavailable,
        )

    @_skip_if_unavailable
    def test_N02_zero_evidence_not_online_operational(self):
        evidence = OfflineOperationalEvidence()
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.is_online_operational)

    @_skip_if_unavailable
    def test_N03_zero_evidence_not_resumable(self):
        evidence = OfflineOperationalEvidence()
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.is_resumable)

    @_skip_if_unavailable
    def test_N04_zero_evidence_downgrade_reasons_nonempty(self):
        evidence = OfflineOperationalEvidence()
        verdict = classify_offline_operational(evidence)
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    # -----------------------------------------------------------------------
    # Group O — explicit_unavailable=True always produces unavailable
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_O01_explicit_unavailable_produces_unavailable(self):
        evidence = _ev(explicit_unavailable=True)
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.unavailable,
        )

    @_skip_if_unavailable
    def test_O02_explicit_unavailable_evidence_present_false(self):
        evidence = _ev(explicit_unavailable=True)
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.evidence_present)

    # -----------------------------------------------------------------------
    # Group P — explicit_unavailable overrides everything else
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_P01_explicit_unavailable_overrides_connected_fresh_evidence(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
            explicit_unavailable=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.unavailable,
        )

    @_skip_if_unavailable
    def test_P02_explicit_unavailable_overrides_reconciliation(self):
        evidence = _ev(
            reconciliation_in_progress=True,
            reconciliation_complete=True,
            explicit_unavailable=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(
            verdict.operational_class,
            OfflineOperationalClass.unavailable,
        )

    # -----------------------------------------------------------------------
    # Group Q — OfflineOperationalEvidence to_dict / from_dict round-trip
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_Q01_evidence_to_dict_is_json_serialisable(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
            participant_id="p1",
            trace_id="t1",
        )
        d = evidence.to_dict()
        json.dumps(d)  # must not raise

    @_skip_if_unavailable
    def test_Q02_evidence_from_dict_round_trip(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.disconnected,
            evidence_fresh=False,
            reconnect_expected=True,
            inflight_tracking_active=True,
            participant_id="pid",
        )
        d = evidence.to_dict()
        ev2 = OfflineOperationalEvidence.from_dict(d)
        self.assertEqual(ev2.connectivity_state, ConnectivityState.disconnected)
        self.assertFalse(ev2.evidence_fresh)
        self.assertTrue(ev2.reconnect_expected)
        self.assertTrue(ev2.inflight_tracking_active)
        self.assertEqual(ev2.participant_id, "pid")

    @_skip_if_unavailable
    def test_Q03_evidence_from_dict_bad_connectivity_state_defaults_to_unknown(self):
        ev = OfflineOperationalEvidence.from_dict(
            {"connectivity_state": "not_a_real_state"}
        )
        self.assertEqual(ev.connectivity_state, ConnectivityState.unknown)

    # -----------------------------------------------------------------------
    # Group R — OfflineOperationalVerdict to_dict / from_dict round-trip
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_R01_verdict_to_dict_is_json_serialisable(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        d = verdict.to_dict()
        json.dumps(d)  # must not raise

    @_skip_if_unavailable
    def test_R02_verdict_from_dict_round_trip(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.offline,
            deferred_sync_acknowledged=True,
        )
        verdict = classify_offline_operational(evidence)
        d = verdict.to_dict()
        v2 = OfflineOperationalVerdict.from_dict(d)
        self.assertEqual(
            v2.operational_class, OfflineOperationalClass.offline_deferred_sync
        )
        self.assertTrue(v2.is_deferred)

    @_skip_if_unavailable
    def test_R03_verdict_from_dict_bad_class_defaults_to_unavailable(self):
        v = OfflineOperationalVerdict.from_dict(
            {"operational_class": "not_real", "rationale": "test"}
        )
        self.assertEqual(v.operational_class, OfflineOperationalClass.unavailable)

    @_skip_if_unavailable
    def test_R04_verdict_to_dict_contains_expected_keys(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        d = verdict.to_dict()
        for key in [
            "operational_class",
            "rationale",
            "downgrade_reasons",
            "is_online_operational",
            "is_resumable",
            "is_deferred",
            "evidence_present",
            "classified_at",
            "verdict_id",
        ]:
            self.assertIn(key, d)

    # -----------------------------------------------------------------------
    # Group S — is_online_operational flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_S01_only_online_operational_class_sets_is_online_operational_true(self):
        online_ev = _ev(
            connectivity_state=ConnectivityState.connected, evidence_fresh=True
        )
        online_verdict = classify_offline_operational(online_ev)
        self.assertTrue(online_verdict.is_online_operational)

        non_online_cases = [
            _ev(
                connectivity_state=ConnectivityState.disconnected,
                reconnect_expected=True,
                inflight_tracking_active=True,
            ),
            _ev(
                connectivity_state=ConnectivityState.offline,
                deferred_sync_acknowledged=True,
            ),
            _ev(reconciliation_in_progress=True, reconciliation_complete=False),
            OfflineOperationalEvidence(),
        ]
        for ev in non_online_cases:
            v = classify_offline_operational(ev)
            with self.subTest(class_=v.operational_class.value):
                self.assertFalse(v.is_online_operational)

    # -----------------------------------------------------------------------
    # Group T — is_resumable flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_T01_online_operational_is_resumable(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertTrue(verdict.is_resumable)

    @_skip_if_unavailable
    def test_T02_bounded_disconnected_resumable_is_resumable(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.disconnected,
            reconnect_expected=True,
            inflight_tracking_active=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertTrue(verdict.is_resumable)

    @_skip_if_unavailable
    def test_T03_offline_deferred_sync_not_resumable(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.offline,
            deferred_sync_acknowledged=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.is_resumable)

    @_skip_if_unavailable
    def test_T04_pending_reconciliation_not_resumable(self):
        evidence = _ev(
            reconciliation_in_progress=True, reconciliation_complete=False
        )
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.is_resumable)

    @_skip_if_unavailable
    def test_T05_unavailable_not_resumable(self):
        evidence = OfflineOperationalEvidence()
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.is_resumable)

    # -----------------------------------------------------------------------
    # Group U — is_deferred flag contract
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_U01_offline_deferred_sync_is_deferred_true(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.offline,
            deferred_sync_acknowledged=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertTrue(verdict.is_deferred)

    @_skip_if_unavailable
    def test_U02_pending_reconciliation_is_deferred_true(self):
        evidence = _ev(
            reconciliation_in_progress=True, reconciliation_complete=False
        )
        verdict = classify_offline_operational(evidence)
        self.assertTrue(verdict.is_deferred)

    @_skip_if_unavailable
    def test_U03_online_operational_is_deferred_false(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.is_deferred)

    @_skip_if_unavailable
    def test_U04_bounded_disconnected_resumable_is_deferred_false(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.disconnected,
            reconnect_expected=True,
            inflight_tracking_active=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertFalse(verdict.is_deferred)

    # -----------------------------------------------------------------------
    # Group V — downgrade_reasons non-empty when downgrade occurred
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_V01_stale_evidence_downgrade_reasons_nonempty(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=False,
        )
        verdict = classify_offline_operational(evidence)
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    @_skip_if_unavailable
    def test_V02_disconnected_state_downgrade_reasons_nonempty(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.disconnected,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertGreater(len(verdict.downgrade_reasons), 0)

    @_skip_if_unavailable
    def test_V03_online_operational_downgrade_reasons_empty(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
        )
        verdict = classify_offline_operational(evidence)
        self.assertEqual(verdict.downgrade_reasons, [])

    # -----------------------------------------------------------------------
    # Group W — build_baseline_offline_operational_verdict
    # -----------------------------------------------------------------------

    @_skip_if_unavailable
    def test_W01_baseline_verdict_is_unavailable(self):
        verdict = build_baseline_offline_operational_verdict()
        self.assertEqual(
            verdict.operational_class, OfflineOperationalClass.unavailable
        )

    @_skip_if_unavailable
    def test_W02_baseline_verdict_not_online_operational(self):
        verdict = build_baseline_offline_operational_verdict()
        self.assertFalse(verdict.is_online_operational)

    @_skip_if_unavailable
    def test_W03_baseline_verdict_not_resumable(self):
        verdict = build_baseline_offline_operational_verdict()
        self.assertFalse(verdict.is_resumable)

    @_skip_if_unavailable
    def test_W04_build_offline_operational_verdict_wrapper_works(self):
        evidence = _ev(
            connectivity_state=ConnectivityState.connected,
            evidence_fresh=True,
        )
        v1 = classify_offline_operational(evidence)
        v2 = build_offline_operational_verdict(evidence)
        self.assertEqual(v1.operational_class, v2.operational_class)

    # -----------------------------------------------------------------------
    # Group X — SystemFinalAcceptanceEvaluator includes offline_operational
    # -----------------------------------------------------------------------

    def test_X01_system_evaluator_includes_offline_operational_dimension(self):
        try:
            from core.system_final_acceptance_verdict import (
                get_system_acceptance_evaluator,
                AcceptanceDimensionId,
            )
        except ImportError as exc:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {exc}")

        report = get_system_acceptance_evaluator().evaluate()
        dim_key = AcceptanceDimensionId.offline_operational.value
        self.assertIn(dim_key, report.checklist)

    def test_X02_offline_operational_probe_not_optimistic_with_zero_evidence(self):
        try:
            from core.system_final_acceptance_verdict import (
                get_system_acceptance_evaluator,
                AcceptanceDimensionId,
                DimensionStatus,
            )
        except ImportError as exc:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {exc}")

        report = get_system_acceptance_evaluator().evaluate()
        item = report.checklist.get(
            AcceptanceDimensionId.offline_operational.value
        )
        self.assertIsNotNone(item)
        # Must be pending or unresolved — never accepted without live evidence
        self.assertIn(
            item.status,
            [DimensionStatus.pending, DimensionStatus.unresolved],
        )

    # -----------------------------------------------------------------------
    # Group Y — AcceptanceDimensionId.all_dimensions includes offline_operational
    # -----------------------------------------------------------------------

    def test_Y01_all_dimensions_includes_offline_operational(self):
        try:
            from core.system_final_acceptance_verdict import AcceptanceDimensionId
        except ImportError as exc:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {exc}")

        dims = [d.value for d in AcceptanceDimensionId.all_dimensions()]
        self.assertIn("offline_operational", dims)

    def test_Y02_offline_operational_dimension_exists_in_enum(self):
        try:
            from core.system_final_acceptance_verdict import AcceptanceDimensionId
        except ImportError as exc:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {exc}")

        self.assertEqual(
            AcceptanceDimensionId.offline_operational.value, "offline_operational"
        )

    # -----------------------------------------------------------------------
    # Group Z — AcceptanceDimensionId.offline_operational probe returns pending
    # -----------------------------------------------------------------------

    def test_Z01_offline_operational_probe_returns_pending_in_baseline(self):
        try:
            from core.system_final_acceptance_verdict import (
                get_system_acceptance_evaluator,
                AcceptanceDimensionId,
                DimensionStatus,
            )
        except ImportError as exc:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {exc}")
        if not _MODULE_AVAILABLE:
            self.skipTest("core.offline_operational_contract unavailable")

        report = get_system_acceptance_evaluator().evaluate()
        item = report.checklist.get(
            AcceptanceDimensionId.offline_operational.value
        )
        self.assertIsNotNone(item)
        # Structural availability → pending (wired, no live evidence)
        self.assertEqual(item.status, DimensionStatus.pending)

    def test_Z02_offline_operational_probe_signal_source_correct(self):
        try:
            from core.system_final_acceptance_verdict import (
                get_system_acceptance_evaluator,
                AcceptanceDimensionId,
            )
        except ImportError as exc:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {exc}")
        if not _MODULE_AVAILABLE:
            self.skipTest("core.offline_operational_contract unavailable")

        report = get_system_acceptance_evaluator().evaluate()
        item = report.checklist.get(
            AcceptanceDimensionId.offline_operational.value
        )
        self.assertIsNotNone(item)
        self.assertIn("offline_operational_contract", item.signal_source)

    # -----------------------------------------------------------------------
    # Group AA — misconfiguration guard
    # -----------------------------------------------------------------------

    def test_AA01_probe_unresolved_if_baseline_returns_online_operational(self):
        """If somehow the baseline returned online_operational, probe → unresolved."""
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                AcceptanceDimensionId,
                DimensionStatus,
            )
            import core.system_final_acceptance_verdict as sfav
        except ImportError as exc:
            self.skipTest(f"system_final_acceptance_verdict unavailable: {exc}")
        if not _MODULE_AVAILABLE:
            self.skipTest("core.offline_operational_contract unavailable")

        # Patch the baseline builder to return online_operational verdict
        from core.offline_operational_contract import (
            OfflineOperationalVerdict,
            OfflineOperationalClass,
        )
        fake_verdict = OfflineOperationalVerdict(
            operational_class=OfflineOperationalClass.online_operational,
            rationale="FAKE — misconfiguration test",
            is_online_operational=True,
            is_resumable=True,
            is_deferred=False,
        )
        original = sfav._build_baseline_offline_verdict

        try:
            sfav._build_baseline_offline_verdict = lambda: fake_verdict
            evaluator = SystemFinalAcceptanceEvaluator()
            item = evaluator._evaluate_offline_operational()
            self.assertEqual(item.status, DimensionStatus.unresolved)
        finally:
            sfav._build_baseline_offline_verdict = original


if __name__ == "__main__":
    unittest.main()
