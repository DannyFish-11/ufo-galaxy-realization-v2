#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr11_cross_device_responsiveness_contract.py
=======================================================
PR-11 — Cross-Device / Remote Execution Responsiveness Contract.

Validates that:

1. **Responsiveness taxonomy is defined and importable** (five levels).
2. **Healthy delegated participant produces near_interactive** when fully
   ready, healthy (≥ 0.8), and evidence-backed.
3. **Stale remote participant is downgraded** — never near_interactive or
   bounded_deferred.
4. **Partial-ready participant** — capped at eventual.
5. **Missing remote participant produces unavailable** — NEVER near_interactive.
6. **Evidence absence blocks near_interactive and bounded_deferred** (REMOTE
   domain).
7. **degraded / eventual states are NOT reported as bounded near-real-time**.
8. **Local domain classified separately from remote domain**.
9. **Single-device local vs cross-device remote distinction is preserved**.
10. **Policy sentinels are importable and reference correct PR**.
11. **to_dict() produces valid JSON-serialisable output**.
12. **Convenience wrapper responsiveness_for_participant() works correctly**.
13. **Unknown / bad inputs default to unavailable (fail-conservative)**.

Test groups
-----------
 A)  Sentinel imports — PR-11 authority and policy constants importable.
 B)  Enum completeness — all five ResponsivenessLevel values exist.
 C)  near_interactive — healthy remote participant (ready, health ≥ 0.8, evidence).
 D)  bounded_deferred — ready participant with health 0.5–0.79.
 E)  bounded_deferred — degraded readiness, health ≥ 0.5, evidence present.
 F)  eventual — partial readiness with evidence present.
 G)  eventual — evidence absent for remote participant.
 H)  degraded — stale remote participant (cap at degraded, not near_interactive).
 I)  degraded — low health (< 0.5) with evidence.
 J)  unavailable — missing remote participant.
 K)  unavailable — health = 0.0 on remote domain.
 L)  is_bounded_near_real_time contract — degraded/eventual are False.
 M)  is_bounded_near_real_time contract — near_interactive/bounded_deferred are True.
 N)  Local domain near_interactive — healthy local device.
 O)  Local domain vs remote domain distinction preserved.
 P)  to_dict() is JSON-serialisable and contains expected keys.
 Q)  Convenience wrapper responsiveness_for_participant() — string API.
 R)  Bad / unknown input defaults to unavailable (fail-conservative).
 S)  downgrade_reasons is non-empty when a downgrade occurred.
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
    from core.cross_device_responsiveness_contract import (
        # Authority / policy sentinels
        CROSS_DEVICE_RESPONSIVENESS_CONTRACT_AUTHORITY,
        CROSS_DEVICE_RESPONSIVENESS_CONTRACT_PR11_SENTINEL,
        RESPONSIVENESS_IS_FIRST_CLASS_OPERATIONAL_DIMENSION_POLICY,
        MISSING_PARTICIPANT_MUST_NOT_CLAIM_NEAR_INTERACTIVE_POLICY,
        STALE_PARTICIPANT_MUST_DOWNGRADE_POLICY,
        EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY,
        LOCAL_VS_REMOTE_DOMAIN_MUST_BE_DISTINGUISHED_POLICY,
        DEGRADED_MUST_NOT_BE_REPORTED_AS_BOUNDED_NEAR_REAL_TIME_POLICY,
        # Enumerations
        ResponsivenessLevel,
        ParticipantReadinessState,
        ExecutionDomain,
        # Data classes
        ResponsivenessInput,
        ResponsivenessContract,
        # Functions
        classify_responsiveness,
        responsiveness_for_participant,
    )
    _MODULE_AVAILABLE = True
except ImportError:
    pass


def _skip_if_unavailable(fn):
    """Decorator: skip test if module failed to import."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not _MODULE_AVAILABLE:
            raise unittest.SkipTest("core.cross_device_responsiveness_contract not available")
        return fn(*args, **kwargs)

    return wrapper


# ===========================================================================
# A) Sentinel imports
# ===========================================================================


class TestPR11Sentinels(unittest.TestCase):
    """All PR-11 sentinel constants are importable and reference PR-11."""

    @_skip_if_unavailable
    def test_A01_authority_sentinel_importable(self):
        assert "PR11" in CROSS_DEVICE_RESPONSIVENESS_CONTRACT_AUTHORITY
        assert "cross-device" in CROSS_DEVICE_RESPONSIVENESS_CONTRACT_AUTHORITY.lower()

    @_skip_if_unavailable
    def test_A02_pr11_sentinel_importable(self):
        assert "PR11" in CROSS_DEVICE_RESPONSIVENESS_CONTRACT_PR11_SENTINEL
        assert "cross_device_responsiveness_contract" in CROSS_DEVICE_RESPONSIVENESS_CONTRACT_PR11_SENTINEL

    @_skip_if_unavailable
    def test_A03_responsiveness_first_class_policy(self):
        assert "first-class" in RESPONSIVENESS_IS_FIRST_CLASS_OPERATIONAL_DIMENSION_POLICY.lower()
        assert "PR-11" in RESPONSIVENESS_IS_FIRST_CLASS_OPERATIONAL_DIMENSION_POLICY

    @_skip_if_unavailable
    def test_A04_missing_participant_policy(self):
        assert "near_interactive" in MISSING_PARTICIPANT_MUST_NOT_CLAIM_NEAR_INTERACTIVE_POLICY
        assert "PR-11" in MISSING_PARTICIPANT_MUST_NOT_CLAIM_NEAR_INTERACTIVE_POLICY

    @_skip_if_unavailable
    def test_A05_stale_participant_policy(self):
        assert "stale" in STALE_PARTICIPANT_MUST_DOWNGRADE_POLICY.lower()
        assert "PR-11" in STALE_PARTICIPANT_MUST_DOWNGRADE_POLICY

    @_skip_if_unavailable
    def test_A06_evidence_absence_policy(self):
        assert "evidence" in EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY.lower()
        assert "near_interactive" in EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY
        assert "PR-11" in EVIDENCE_ABSENCE_BLOCKS_NEAR_INTERACTIVE_POLICY

    @_skip_if_unavailable
    def test_A07_local_vs_remote_policy(self):
        assert "LOCAL" in LOCAL_VS_REMOTE_DOMAIN_MUST_BE_DISTINGUISHED_POLICY
        assert "REMOTE" in LOCAL_VS_REMOTE_DOMAIN_MUST_BE_DISTINGUISHED_POLICY
        assert "PR-11" in LOCAL_VS_REMOTE_DOMAIN_MUST_BE_DISTINGUISHED_POLICY

    @_skip_if_unavailable
    def test_A08_degraded_not_near_real_time_policy(self):
        assert "degraded" in DEGRADED_MUST_NOT_BE_REPORTED_AS_BOUNDED_NEAR_REAL_TIME_POLICY.lower()
        assert "PR-11" in DEGRADED_MUST_NOT_BE_REPORTED_AS_BOUNDED_NEAR_REAL_TIME_POLICY


# ===========================================================================
# B) Enum completeness
# ===========================================================================


class TestResponsivenessLevelTaxonomy(unittest.TestCase):
    """ResponsivenessLevel contains all five required values."""

    @_skip_if_unavailable
    def test_B01_near_interactive_exists(self):
        assert ResponsivenessLevel.near_interactive.value == "near_interactive"

    @_skip_if_unavailable
    def test_B02_bounded_deferred_exists(self):
        assert ResponsivenessLevel.bounded_deferred.value == "bounded_deferred"

    @_skip_if_unavailable
    def test_B03_eventual_exists(self):
        assert ResponsivenessLevel.eventual.value == "eventual"

    @_skip_if_unavailable
    def test_B04_degraded_exists(self):
        assert ResponsivenessLevel.degraded.value == "degraded"

    @_skip_if_unavailable
    def test_B05_unavailable_exists(self):
        assert ResponsivenessLevel.unavailable.value == "unavailable"

    @_skip_if_unavailable
    def test_B06_five_distinct_levels(self):
        values = {lvl.value for lvl in ResponsivenessLevel}
        assert len(values) == 5

    @_skip_if_unavailable
    def test_B07_participant_readiness_all_five(self):
        states = {s.value for s in ParticipantReadinessState}
        assert states == {"ready", "degraded", "partial", "stale", "missing"}

    @_skip_if_unavailable
    def test_B08_execution_domain_local_remote(self):
        assert ExecutionDomain.LOCAL.value == "local"
        assert ExecutionDomain.REMOTE.value == "remote"


# ===========================================================================
# C) near_interactive — healthy remote participant
# ===========================================================================


class TestNearInteractiveRemote(unittest.TestCase):
    """Healthy delegated remote participant yields near_interactive."""

    @_skip_if_unavailable
    def test_C01_fully_ready_high_health_evidence(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-001",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.95,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.near_interactive, (
            f"Expected near_interactive, got {contract.level}"
        )

    @_skip_if_unavailable
    def test_C02_health_exactly_0_8_yields_near_interactive(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-002",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.8,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.near_interactive

    @_skip_if_unavailable
    def test_C03_near_interactive_is_bounded_near_real_time(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-003",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.is_bounded_near_real_time is True

    @_skip_if_unavailable
    def test_C04_near_interactive_no_downgrade_reasons(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-004",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=1.0,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.near_interactive
        assert contract.downgrade_reasons == []


# ===========================================================================
# D) bounded_deferred — ready participant with health 0.5–0.79
# ===========================================================================


class TestBoundedDeferredReadyLowHealth(unittest.TestCase):
    """ready participant with health 0.5–0.79 yields bounded_deferred."""

    @_skip_if_unavailable
    def test_D01_health_0_5_ready_evidence(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-010",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.5,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.bounded_deferred

    @_skip_if_unavailable
    def test_D02_health_0_79_ready_evidence(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-011",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.79,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.bounded_deferred

    @_skip_if_unavailable
    def test_D03_bounded_deferred_is_bounded_near_real_time(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-012",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.6,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.is_bounded_near_real_time is True


# ===========================================================================
# E) bounded_deferred — degraded readiness, health ≥ 0.5
# ===========================================================================


class TestBoundedDeferredDegradedReadiness(unittest.TestCase):
    """degraded readiness with health ≥ 0.5 and evidence → bounded_deferred."""

    @_skip_if_unavailable
    def test_E01_degraded_readiness_health_0_6_evidence(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-020",
            participant_readiness=ParticipantReadinessState.degraded,
            health_score=0.6,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.bounded_deferred

    @_skip_if_unavailable
    def test_E02_degraded_readiness_health_0_5_evidence(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-021",
            participant_readiness=ParticipantReadinessState.degraded,
            health_score=0.5,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.bounded_deferred

    @_skip_if_unavailable
    def test_E03_degraded_not_near_interactive(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-022",
            participant_readiness=ParticipantReadinessState.degraded,
            health_score=0.85,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        # degraded readiness → never near_interactive
        assert contract.level is not ResponsivenessLevel.near_interactive


# ===========================================================================
# F) eventual — partial readiness
# ===========================================================================


class TestEventualPartialReadiness(unittest.TestCase):
    """Partial readiness participant → eventual (never bounded)."""

    @_skip_if_unavailable
    def test_F01_partial_readiness_evidence_present(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-030",
            participant_readiness=ParticipantReadinessState.partial,
            health_score=0.7,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.eventual

    @_skip_if_unavailable
    def test_F02_partial_readiness_high_health_still_eventual(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-031",
            participant_readiness=ParticipantReadinessState.partial,
            health_score=0.95,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.eventual

    @_skip_if_unavailable
    def test_F03_partial_readiness_not_bounded_near_real_time(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-032",
            participant_readiness=ParticipantReadinessState.partial,
            health_score=0.9,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.is_bounded_near_real_time is False


# ===========================================================================
# G) eventual — evidence absent for remote participant
# ===========================================================================


class TestEventualEvidenceAbsent(unittest.TestCase):
    """Evidence absent for remote participant → at most eventual (POLICY)."""

    @_skip_if_unavailable
    def test_G01_no_evidence_ready_readiness_capped_eventual(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-040",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=False,  # no evidence
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.eventual, (
            f"Expected eventual when evidence absent, got {contract.level}"
        )

    @_skip_if_unavailable
    def test_G02_no_evidence_cannot_be_near_interactive(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-041",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=1.0,
            evidence_available=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is not ResponsivenessLevel.near_interactive

    @_skip_if_unavailable
    def test_G03_no_evidence_cannot_be_bounded_deferred(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-042",
            participant_readiness=ParticipantReadinessState.degraded,
            health_score=0.8,
            evidence_available=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is not ResponsivenessLevel.bounded_deferred

    @_skip_if_unavailable
    def test_G04_no_evidence_downgrade_reason_recorded(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-043",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=False,
        )
        contract = classify_responsiveness(inp)
        assert any("evidence" in r for r in contract.downgrade_reasons), (
            "Expected evidence-related downgrade reason, got: "
            + str(contract.downgrade_reasons)
        )


# ===========================================================================
# H) degraded — stale remote participant
# ===========================================================================


class TestDegradedStaleParticipant(unittest.TestCase):
    """Stale remote participant is capped at degraded (POLICY)."""

    @_skip_if_unavailable
    def test_H01_stale_participant_yields_degraded(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-050",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.95,
            evidence_available=True,
            is_stale=True,  # stale
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.degraded

    @_skip_if_unavailable
    def test_H02_stale_participant_not_near_interactive(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-051",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=1.0,
            evidence_available=True,
            is_stale=True,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is not ResponsivenessLevel.near_interactive

    @_skip_if_unavailable
    def test_H03_stale_participant_not_bounded_deferred(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-052",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
            is_stale=True,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is not ResponsivenessLevel.bounded_deferred

    @_skip_if_unavailable
    def test_H04_stale_downgrade_reason_recorded(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-053",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
            is_stale=True,
        )
        contract = classify_responsiveness(inp)
        assert any("stale" in r for r in contract.downgrade_reasons)

    @_skip_if_unavailable
    def test_H05_stale_participant_not_bounded_near_real_time(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-054",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
            is_stale=True,
        )
        contract = classify_responsiveness(inp)
        assert contract.is_bounded_near_real_time is False


# ===========================================================================
# I) degraded — low health (< 0.5)
# ===========================================================================


class TestDegradedLowHealth(unittest.TestCase):
    """Low health (< 0.5) with evidence → degraded, not bounded."""

    @_skip_if_unavailable
    def test_I01_health_0_3_ready_evidence(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-060",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.3,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.degraded

    @_skip_if_unavailable
    def test_I02_health_0_1_degraded_evidence(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-061",
            participant_readiness=ParticipantReadinessState.degraded,
            health_score=0.1,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.degraded

    @_skip_if_unavailable
    def test_I03_low_health_not_bounded_near_real_time(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="device-062",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.2,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.is_bounded_near_real_time is False


# ===========================================================================
# J) unavailable — missing remote participant
# ===========================================================================


class TestUnavailableMissingParticipant(unittest.TestCase):
    """Missing remote participant → unavailable (POLICY)."""

    @_skip_if_unavailable
    def test_J01_missing_readiness_yields_unavailable(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id=None,
            participant_readiness=ParticipantReadinessState.missing,
            health_score=0.0,
            evidence_available=False,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.unavailable

    @_skip_if_unavailable
    def test_J02_missing_even_with_high_health_is_unavailable(self):
        # health score doesn't matter when readiness is missing
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="ghost-device",
            participant_readiness=ParticipantReadinessState.missing,
            health_score=0.99,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.unavailable

    @_skip_if_unavailable
    def test_J03_missing_not_near_interactive(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_readiness=ParticipantReadinessState.missing,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is not ResponsivenessLevel.near_interactive

    @_skip_if_unavailable
    def test_J04_missing_participant_downgrade_reason(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_readiness=ParticipantReadinessState.missing,
        )
        contract = classify_responsiveness(inp)
        assert any("missing" in r for r in contract.downgrade_reasons)

    @_skip_if_unavailable
    def test_J05_missing_not_bounded_near_real_time(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_readiness=ParticipantReadinessState.missing,
        )
        contract = classify_responsiveness(inp)
        assert contract.is_bounded_near_real_time is False


# ===========================================================================
# K) unavailable — health = 0.0 on remote domain
# ===========================================================================


class TestUnavailableZeroHealth(unittest.TestCase):
    """Participant with health=0.0 and no participant_id → unavailable."""

    @_skip_if_unavailable
    def test_K01_no_participant_id_zero_health_remote(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id=None,
            participant_readiness=ParticipantReadinessState.missing,
            health_score=0.0,
            evidence_available=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.unavailable


# ===========================================================================
# L) is_bounded_near_real_time — degraded/eventual are False
# ===========================================================================


class TestBoundedNearRealTimeDegradedEventual(unittest.TestCase):
    """degraded and eventual MUST NOT be reported as bounded near-real-time."""

    @_skip_if_unavailable
    def test_L01_degraded_not_bounded_near_real_time(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="dev-070",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.3,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.degraded
        assert contract.is_bounded_near_real_time is False

    @_skip_if_unavailable
    def test_L02_eventual_not_bounded_near_real_time(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="dev-071",
            participant_readiness=ParticipantReadinessState.partial,
            health_score=0.7,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.eventual
        assert contract.is_bounded_near_real_time is False

    @_skip_if_unavailable
    def test_L03_unavailable_not_bounded_near_real_time(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_readiness=ParticipantReadinessState.missing,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.unavailable
        assert contract.is_bounded_near_real_time is False

    @_skip_if_unavailable
    def test_L04_stale_not_bounded_near_real_time(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="dev-072",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
            is_stale=True,
        )
        contract = classify_responsiveness(inp)
        assert contract.is_bounded_near_real_time is False


# ===========================================================================
# M) is_bounded_near_real_time — near_interactive/bounded_deferred are True
# ===========================================================================


class TestBoundedNearRealTimePositive(unittest.TestCase):
    """near_interactive and bounded_deferred ARE bounded near-real-time."""

    @_skip_if_unavailable
    def test_M01_near_interactive_is_bounded_near_real_time(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="dev-080",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.near_interactive
        assert contract.is_bounded_near_real_time is True

    @_skip_if_unavailable
    def test_M02_bounded_deferred_is_bounded_near_real_time(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="dev-081",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.6,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.bounded_deferred
        assert contract.is_bounded_near_real_time is True


# ===========================================================================
# N) Local domain near_interactive — healthy local device
# ===========================================================================


class TestLocalDomainNearInteractive(unittest.TestCase):
    """Local single-device execution with healthy state → near_interactive."""

    @_skip_if_unavailable
    def test_N01_local_healthy_near_interactive(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.LOCAL,
            participant_id="local-device",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.near_interactive
        assert contract.execution_domain is ExecutionDomain.LOCAL

    @_skip_if_unavailable
    def test_N02_local_domain_label_preserved(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.LOCAL,
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.85,
            evidence_available=True,
        )
        contract = classify_responsiveness(inp)
        assert contract.execution_domain is ExecutionDomain.LOCAL
        assert contract.to_dict()["execution_domain"] == "local"


# ===========================================================================
# O) Local domain vs remote domain distinction preserved
# ===========================================================================


class TestLocalRemoteDomainDistinction(unittest.TestCase):
    """Local near_interactive and remote near_interactive are distinct domains."""

    @_skip_if_unavailable
    def test_O01_local_near_interactive_domain_is_local(self):
        local_inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.LOCAL,
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
        )
        local_contract = classify_responsiveness(local_inp)
        assert local_contract.execution_domain is ExecutionDomain.LOCAL

    @_skip_if_unavailable
    def test_O02_remote_near_interactive_domain_is_remote(self):
        remote_inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="remote-device",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
        )
        remote_contract = classify_responsiveness(remote_inp)
        assert remote_contract.execution_domain is ExecutionDomain.REMOTE

    @_skip_if_unavailable
    def test_O03_same_level_different_domain_contracts_are_distinct(self):
        """Two near_interactive contracts with different domains are not equal."""
        local_inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.LOCAL,
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
        )
        remote_inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="remote-dev",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
        )
        local_contract = classify_responsiveness(local_inp)
        remote_contract = classify_responsiveness(remote_inp)
        # Both near_interactive but domains differ
        assert local_contract.level is ResponsivenessLevel.near_interactive
        assert remote_contract.level is ResponsivenessLevel.near_interactive
        assert local_contract.execution_domain is not remote_contract.execution_domain


# ===========================================================================
# P) to_dict() is JSON-serialisable
# ===========================================================================


class TestToDictSerialisation(unittest.TestCase):
    """to_dict() output is fully JSON-serialisable and contains expected keys."""

    @_skip_if_unavailable
    def test_P01_to_dict_json_serialisable(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="dev-090",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
        )
        contract = classify_responsiveness(inp)
        d = contract.to_dict()
        # Must not raise
        serialised = json.dumps(d)
        assert serialised

    @_skip_if_unavailable
    def test_P02_to_dict_contains_level_key(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="dev-091",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=True,
        )
        contract = classify_responsiveness(inp)
        d = contract.to_dict()
        assert "level" in d
        assert d["level"] == "near_interactive"

    @_skip_if_unavailable
    def test_P03_to_dict_contains_all_required_keys(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="dev-092",
            participant_readiness=ParticipantReadinessState.degraded,
            health_score=0.6,
            evidence_available=True,
        )
        contract = classify_responsiveness(inp)
        d = contract.to_dict()
        required_keys = {
            "level",
            "execution_domain",
            "rationale",
            "downgrade_reasons",
            "is_bounded_near_real_time",
            "participant_id",
            "evidence_present",
            "classified_at",
        }
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

    @_skip_if_unavailable
    def test_P04_input_to_dict_json_serialisable(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="dev-093",
            participant_readiness=ParticipantReadinessState.partial,
            health_score=0.7,
            evidence_available=True,
        )
        d = inp.to_dict()
        serialised = json.dumps(d)
        assert serialised


# ===========================================================================
# Q) Convenience wrapper
# ===========================================================================


class TestConvenienceWrapper(unittest.TestCase):
    """responsiveness_for_participant() accepts string inputs."""

    @_skip_if_unavailable
    def test_Q01_string_ready_high_health_evidence(self):
        contract = responsiveness_for_participant(
            participant_readiness="ready",
            health_score=0.95,
            evidence_available=True,
            is_stale=False,
            execution_domain="remote",
            participant_id="dev-100",
        )
        assert contract.level is ResponsivenessLevel.near_interactive

    @_skip_if_unavailable
    def test_Q02_string_missing_yields_unavailable(self):
        contract = responsiveness_for_participant(
            participant_readiness="missing",
            health_score=0.0,
            evidence_available=False,
            execution_domain="remote",
        )
        assert contract.level is ResponsivenessLevel.unavailable

    @_skip_if_unavailable
    def test_Q03_string_stale_yields_degraded(self):
        contract = responsiveness_for_participant(
            participant_readiness="ready",
            health_score=0.9,
            evidence_available=True,
            is_stale=True,
            execution_domain="remote",
            participant_id="dev-101",
        )
        assert contract.level is ResponsivenessLevel.degraded

    @_skip_if_unavailable
    def test_Q04_local_domain_string(self):
        contract = responsiveness_for_participant(
            participant_readiness="ready",
            health_score=0.9,
            evidence_available=True,
            execution_domain="local",
        )
        assert contract.execution_domain is ExecutionDomain.LOCAL

    @_skip_if_unavailable
    def test_Q05_partial_readiness_yields_eventual(self):
        contract = responsiveness_for_participant(
            participant_readiness="partial",
            health_score=0.85,
            evidence_available=True,
            execution_domain="remote",
            participant_id="dev-102",
        )
        assert contract.level is ResponsivenessLevel.eventual


# ===========================================================================
# R) Bad / unknown input → unavailable (fail-conservative)
# ===========================================================================


class TestFailConservativeBadInput(unittest.TestCase):
    """Unknown input values default to unavailable (fail-conservative)."""

    @_skip_if_unavailable
    def test_R01_unknown_readiness_string_defaults_to_missing(self):
        contract = responsiveness_for_participant(
            participant_readiness="xyzzy_unknown_readiness",
            health_score=0.9,
            evidence_available=True,
            execution_domain="remote",
            participant_id="dev-110",
        )
        # unknown readiness → treated as missing → unavailable
        assert contract.level is ResponsivenessLevel.unavailable

    @_skip_if_unavailable
    def test_R02_unknown_domain_defaults_to_remote(self):
        # Unknown domain → remote (conservative)
        contract = responsiveness_for_participant(
            participant_readiness="missing",
            health_score=0.0,
            evidence_available=False,
            execution_domain="xyzzy_domain",
        )
        assert contract.execution_domain is ExecutionDomain.REMOTE


# ===========================================================================
# S) downgrade_reasons populated on downgrade
# ===========================================================================


class TestDowngradeReasons(unittest.TestCase):
    """downgrade_reasons is non-empty whenever a downgrade occurred."""

    @_skip_if_unavailable
    def test_S01_stale_has_downgrade_reason(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="dev-120",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.95,
            evidence_available=True,
            is_stale=True,
        )
        contract = classify_responsiveness(inp)
        assert len(contract.downgrade_reasons) > 0

    @_skip_if_unavailable
    def test_S02_missing_has_downgrade_reason(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_readiness=ParticipantReadinessState.missing,
        )
        contract = classify_responsiveness(inp)
        assert len(contract.downgrade_reasons) > 0

    @_skip_if_unavailable
    def test_S03_no_evidence_has_downgrade_reason(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="dev-121",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.9,
            evidence_available=False,
        )
        contract = classify_responsiveness(inp)
        assert len(contract.downgrade_reasons) > 0

    @_skip_if_unavailable
    def test_S04_healthy_near_interactive_no_downgrade_reasons(self):
        inp = ResponsivenessInput(
            execution_domain=ExecutionDomain.REMOTE,
            participant_id="dev-122",
            participant_readiness=ParticipantReadinessState.ready,
            health_score=0.95,
            evidence_available=True,
            is_stale=False,
        )
        contract = classify_responsiveness(inp)
        assert contract.level is ResponsivenessLevel.near_interactive
        assert contract.downgrade_reasons == []


if __name__ == "__main__":
    unittest.main()
