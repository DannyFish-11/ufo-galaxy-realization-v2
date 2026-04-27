#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_platform_closure_audit.py
======================================
PR-8: Formal Closure Audit and Production-Readiness Classification — Tests.

This test suite validates that:

* All public API symbols are importable from ``core.platform_closure_audit``.
* Authority and policy sentinels are present, non-empty, and contain
  required vocabulary.
* ``GapClosureEntry``, ``CapabilityBoundaryEntry``, ``ReadinessEntry``,
  ``OperationalRiskEntry``, and ``PlatformClosureAuditReport`` dataclass
  contracts are met.
* ``build_platform_closure_audit_report()`` produces a valid, self-consistent
  report with all required gap entries and capability entries.
* All gaps from PRs 1–7 are represented with evidence-bound references.
* ``GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION`` is marked CLOSED
  (closed by PR-7 / #854).
* No P0 gap in scope (PRs 1–7) is left OPEN in the report.
* All ACTIVE_MAINLINE capabilities have non-empty code and test references.
* ``PlatformClosureAuditReport.summary()`` returns required keys.
* Singleton management (get / reset / rebuild) works correctly.
* ``to_dict()`` produces valid JSON-serialisable output for all data classes.
* ``dual_repo_system_map.WORKSTREAM_GAP_REGISTRY`` has
  ``GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION`` with ``resolved=True``.

Coverage groups
---------------
 A)  Module structure — all ``__all__`` symbols importable.
 B)  Authority sentinels — non-empty strings with required vocabulary.
 C)  Policy sentinels — vocabulary checks.
 D)  GapClosureStatus — all values present and string-typed.
 E)  CapabilityTier — all values present and string-typed.
 F)  GapClosureEntry — dataclass contract, ``to_dict()`` keys.
 G)  CapabilityBoundaryEntry — dataclass contract, ``to_dict()`` keys.
 H)  ReadinessEntry — dataclass contract, ``to_dict()`` keys.
 I)  OperationalRiskEntry — dataclass contract, ``to_dict()`` keys.
 J)  PlatformClosureAuditReport — dataclass contract.
 K)  build_platform_closure_audit_report — required gap IDs present.
 L)  build_platform_closure_audit_report — no P0 gap is OPEN.
 M)  build_platform_closure_audit_report — GAP_MULTI_DEVICE closed by PR-7.
 N)  build_platform_closure_audit_report — capability tiers non-empty.
 O)  build_platform_closure_audit_report — all ACTIVE_MAINLINE have evidence.
 P)  build_platform_closure_audit_report — CONDITIONAL capabilities have conditions.
 Q)  build_platform_closure_audit_report — operational risks present.
 R)  PlatformClosureAuditReport.summary() — required keys.
 S)  PlatformClosureAuditReport.to_dict() — JSON-serialisable.
 T)  Singleton management — get / reset / rebuild.
 U)  Evidence-bound conclusions — code_reference non-empty for CLOSED gaps.
 V)  Evidence-bound conclusions — test_reference non-empty for CLOSED gaps.
 W)  dual_repo_system_map gap registry — GAP_MULTI_DEVICE resolved=True.
 X)  dual_repo_system_map gap registry — no P0 gap resolved=False.
 Y)  Open gap count — only acknowledged/scope-limited gaps remain open.
 Z)  Readiness tiers — all four tiers present in readiness_tiers list.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _reset():
    from core.platform_closure_audit import reset_platform_closure_audit
    reset_platform_closure_audit()


# ===========================================================================
# A)  Module structure
# ===========================================================================

class TestA_ModuleStructure(unittest.TestCase):
    """A) All __all__ symbols importable."""

    def test_A01_module_importable(self) -> None:
        import core.platform_closure_audit  # noqa: F401

    def test_A02_all_symbols_importable(self) -> None:
        import core.platform_closure_audit as mod
        for name in mod.__all__:
            self.assertTrue(
                hasattr(mod, name),
                f"__all__ symbol '{name}' not found on module",
            )

    def test_A03_all_list_nonempty(self) -> None:
        import core.platform_closure_audit as mod
        self.assertGreater(len(mod.__all__), 0)

    def test_A04_required_symbols_in_all(self) -> None:
        import core.platform_closure_audit as mod
        required = {
            "PLATFORM_CLOSURE_AUDIT_AUTHORITY",
            "PLATFORM_CLOSURE_AUDIT_PR8_SENTINEL",
            "GapClosureStatus",
            "CapabilityTier",
            "GapClosureEntry",
            "CapabilityBoundaryEntry",
            "ReadinessEntry",
            "OperationalRiskEntry",
            "PlatformClosureAuditReport",
            "build_platform_closure_audit_report",
            "get_platform_closure_audit_report",
            "reset_platform_closure_audit",
        }
        missing = required - set(mod.__all__)
        self.assertFalse(missing, f"Missing from __all__: {missing}")


# ===========================================================================
# B)  Authority sentinels
# ===========================================================================

class TestB_AuthoritySentinels(unittest.TestCase):
    """B) Authority sentinels are non-empty strings with required vocabulary."""

    def test_B01_platform_closure_audit_authority_nonempty(self) -> None:
        from core.platform_closure_audit import PLATFORM_CLOSURE_AUDIT_AUTHORITY
        self.assertIsInstance(PLATFORM_CLOSURE_AUDIT_AUTHORITY, str)
        self.assertTrue(PLATFORM_CLOSURE_AUDIT_AUTHORITY)

    def test_B02_authority_contains_authoritative_keyword(self) -> None:
        from core.platform_closure_audit import PLATFORM_CLOSURE_AUDIT_AUTHORITY
        self.assertIn("authoritative", PLATFORM_CLOSURE_AUDIT_AUTHORITY.lower())

    def test_B03_pr8_sentinel_nonempty(self) -> None:
        from core.platform_closure_audit import PLATFORM_CLOSURE_AUDIT_PR8_SENTINEL
        self.assertIsInstance(PLATFORM_CLOSURE_AUDIT_PR8_SENTINEL, str)
        self.assertTrue(PLATFORM_CLOSURE_AUDIT_PR8_SENTINEL)

    def test_B04_pr8_sentinel_contains_pr8(self) -> None:
        from core.platform_closure_audit import PLATFORM_CLOSURE_AUDIT_PR8_SENTINEL
        self.assertIn("PR8", PLATFORM_CLOSURE_AUDIT_PR8_SENTINEL)


# ===========================================================================
# C)  Policy sentinels
# ===========================================================================

class TestC_PolicySentinels(unittest.TestCase):
    """C) Policy sentinels contain required vocabulary."""

    def test_C01_projection_only_policy_nonempty(self) -> None:
        from core.platform_closure_audit import CLOSURE_AUDIT_IS_PROJECTION_ONLY_POLICY
        self.assertTrue(CLOSURE_AUDIT_IS_PROJECTION_ONLY_POLICY)

    def test_C02_evidence_bound_policy_nonempty(self) -> None:
        from core.platform_closure_audit import EVIDENCE_BOUND_CONCLUSIONS_ONLY_POLICY
        self.assertTrue(EVIDENCE_BOUND_CONCLUSIONS_ONLY_POLICY)

    def test_C03_honest_gap_reporting_policy_nonempty(self) -> None:
        from core.platform_closure_audit import HONEST_GAP_REPORTING_POLICY
        self.assertTrue(HONEST_GAP_REPORTING_POLICY)

    def test_C04_capability_classification_policy_nonempty(self) -> None:
        from core.platform_closure_audit import (
            CAPABILITY_CLASSIFICATION_BASED_ON_CODE_AND_TESTS_POLICY,
        )
        self.assertTrue(CAPABILITY_CLASSIFICATION_BASED_ON_CODE_AND_TESTS_POLICY)

    def test_C05_projection_policy_contains_must_not(self) -> None:
        from core.platform_closure_audit import CLOSURE_AUDIT_IS_PROJECTION_ONLY_POLICY
        self.assertIn("MUST NOT", CLOSURE_AUDIT_IS_PROJECTION_ONLY_POLICY)

    def test_C06_evidence_policy_contains_prohibited(self) -> None:
        from core.platform_closure_audit import EVIDENCE_BOUND_CONCLUSIONS_ONLY_POLICY
        self.assertIn("prohibited", EVIDENCE_BOUND_CONCLUSIONS_ONLY_POLICY.lower())


# ===========================================================================
# D)  GapClosureStatus
# ===========================================================================

class TestD_GapClosureStatus(unittest.TestCase):
    """D) GapClosureStatus — all values present and string-typed."""

    def test_D01_closed_present(self) -> None:
        from core.platform_closure_audit import GapClosureStatus
        self.assertIsInstance(GapClosureStatus.CLOSED.value, str)

    def test_D02_closed_conditional_present(self) -> None:
        from core.platform_closure_audit import GapClosureStatus
        self.assertIsInstance(GapClosureStatus.CLOSED_CONDITIONAL.value, str)

    def test_D03_open_present(self) -> None:
        from core.platform_closure_audit import GapClosureStatus
        self.assertIsInstance(GapClosureStatus.OPEN.value, str)

    def test_D04_acknowledged_present(self) -> None:
        from core.platform_closure_audit import GapClosureStatus
        self.assertIsInstance(GapClosureStatus.ACKNOWLEDGED.value, str)

    def test_D05_values_unique(self) -> None:
        from core.platform_closure_audit import GapClosureStatus
        values = [s.value for s in GapClosureStatus]
        self.assertEqual(len(values), len(set(values)))


# ===========================================================================
# E)  CapabilityTier
# ===========================================================================

class TestE_CapabilityTier(unittest.TestCase):
    """E) CapabilityTier — all values present and string-typed."""

    def test_E01_active_mainline_present(self) -> None:
        from core.platform_closure_audit import CapabilityTier
        self.assertIsInstance(CapabilityTier.ACTIVE_MAINLINE.value, str)

    def test_E02_conditional_present(self) -> None:
        from core.platform_closure_audit import CapabilityTier
        self.assertIsInstance(CapabilityTier.CONDITIONAL.value, str)

    def test_E03_experimental_present(self) -> None:
        from core.platform_closure_audit import CapabilityTier
        self.assertIsInstance(CapabilityTier.EXPERIMENTAL.value, str)

    def test_E04_structural_only_present(self) -> None:
        from core.platform_closure_audit import CapabilityTier
        self.assertIsInstance(CapabilityTier.STRUCTURAL_ONLY.value, str)

    def test_E05_values_unique(self) -> None:
        from core.platform_closure_audit import CapabilityTier
        values = [t.value for t in CapabilityTier]
        self.assertEqual(len(values), len(set(values)))


# ===========================================================================
# F)  GapClosureEntry dataclass contract
# ===========================================================================

class TestF_GapClosureEntry(unittest.TestCase):
    """F) GapClosureEntry — dataclass contract and to_dict() keys."""

    def _make_entry(self):
        from core.platform_closure_audit import GapClosureEntry, GapClosureStatus
        return GapClosureEntry(
            gap_id="TEST_GAP",
            title="Test gap",
            status=GapClosureStatus.CLOSED,
            closing_pr="PR-0",
            code_reference="core.test_module",
            test_reference="tests/test_module.py",
        )

    def test_F01_creation(self) -> None:
        entry = self._make_entry()
        self.assertEqual(entry.gap_id, "TEST_GAP")

    def test_F02_to_dict_has_required_keys(self) -> None:
        entry = self._make_entry()
        d = entry.to_dict()
        for key in ("gap_id", "title", "status", "closing_pr",
                    "code_reference", "test_reference", "scope_note"):
            self.assertIn(key, d)

    def test_F03_to_dict_status_is_string(self) -> None:
        entry = self._make_entry()
        d = entry.to_dict()
        self.assertIsInstance(d["status"], str)

    def test_F04_scope_note_default_empty(self) -> None:
        entry = self._make_entry()
        self.assertEqual(entry.scope_note, "")


# ===========================================================================
# G)  CapabilityBoundaryEntry dataclass contract
# ===========================================================================

class TestG_CapabilityBoundaryEntry(unittest.TestCase):
    """G) CapabilityBoundaryEntry — dataclass contract and to_dict() keys."""

    def _make_entry(self):
        from core.platform_closure_audit import CapabilityBoundaryEntry, CapabilityTier
        return CapabilityBoundaryEntry(
            capability_id="TEST_CAP",
            description="A test capability.",
            tier=CapabilityTier.ACTIVE_MAINLINE,
            code_reference="core.test",
            test_reference="tests/test.py",
        )

    def test_G01_creation(self) -> None:
        entry = self._make_entry()
        self.assertEqual(entry.capability_id, "TEST_CAP")

    def test_G02_to_dict_has_required_keys(self) -> None:
        entry = self._make_entry()
        d = entry.to_dict()
        for key in ("capability_id", "description", "tier",
                    "code_reference", "test_reference", "condition"):
            self.assertIn(key, d)

    def test_G03_to_dict_tier_is_string(self) -> None:
        entry = self._make_entry()
        d = entry.to_dict()
        self.assertIsInstance(d["tier"], str)

    def test_G04_condition_default_empty(self) -> None:
        entry = self._make_entry()
        self.assertEqual(entry.condition, "")


# ===========================================================================
# H)  ReadinessEntry dataclass contract
# ===========================================================================

class TestH_ReadinessEntry(unittest.TestCase):
    """H) ReadinessEntry — dataclass contract and to_dict() keys."""

    def test_H01_creation(self) -> None:
        from core.platform_closure_audit import ReadinessEntry, CapabilityTier
        entry = ReadinessEntry(
            tier=CapabilityTier.ACTIVE_MAINLINE,
            summary="Test tier",
            capability_ids=["CAP_A", "CAP_B"],
        )
        self.assertEqual(entry.tier, CapabilityTier.ACTIVE_MAINLINE)

    def test_H02_to_dict_has_required_keys(self) -> None:
        from core.platform_closure_audit import ReadinessEntry, CapabilityTier
        entry = ReadinessEntry(
            tier=CapabilityTier.CONDITIONAL,
            summary="Conditional.",
        )
        d = entry.to_dict()
        for key in ("tier", "summary", "capability_ids"):
            self.assertIn(key, d)

    def test_H03_capability_ids_default_empty_list(self) -> None:
        from core.platform_closure_audit import ReadinessEntry, CapabilityTier
        entry = ReadinessEntry(
            tier=CapabilityTier.EXPERIMENTAL,
            summary="X",
        )
        self.assertEqual(entry.capability_ids, [])


# ===========================================================================
# I)  OperationalRiskEntry dataclass contract
# ===========================================================================

class TestI_OperationalRiskEntry(unittest.TestCase):
    """I) OperationalRiskEntry — dataclass contract and to_dict() keys."""

    def _make_entry(self):
        from core.platform_closure_audit import OperationalRiskEntry
        return OperationalRiskEntry(
            risk_id="RISK_TEST",
            description="A test risk.",
            severity="P1",
            mitigation="Mitigation text.",
            follow_up="Follow up action.",
        )

    def test_I01_creation(self) -> None:
        entry = self._make_entry()
        self.assertEqual(entry.risk_id, "RISK_TEST")

    def test_I02_to_dict_has_required_keys(self) -> None:
        entry = self._make_entry()
        d = entry.to_dict()
        for key in ("risk_id", "description", "severity", "mitigation", "follow_up"):
            self.assertIn(key, d)

    def test_I03_severity_values_checked(self) -> None:
        entry = self._make_entry()
        self.assertIn(entry.severity, ("P0", "P1", "P2"))


# ===========================================================================
# J)  PlatformClosureAuditReport dataclass contract
# ===========================================================================

class TestJ_PlatformClosureAuditReport(unittest.TestCase):
    """J) PlatformClosureAuditReport — dataclass contract."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_J01_build_returns_report_instance(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            PlatformClosureAuditReport,
        )
        report = build_platform_closure_audit_report()
        self.assertIsInstance(report, PlatformClosureAuditReport)

    def test_J02_report_has_nonempty_report_id(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        self.assertTrue(report.report_id)

    def test_J03_report_has_positive_generated_at(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        import time
        before = time.time()
        report = build_platform_closure_audit_report()
        self.assertGreater(report.generated_at, before - 5)

    def test_J04_report_has_nonempty_gap_closures(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        self.assertGreater(len(report.gap_closures), 0)

    def test_J05_report_has_nonempty_capability_boundary(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        self.assertGreater(len(report.capability_boundary), 0)

    def test_J06_report_has_nonempty_readiness_tiers(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        self.assertGreater(len(report.readiness_tiers), 0)

    def test_J07_report_has_nonempty_operational_risks(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        self.assertGreater(len(report.operational_risks), 0)

    def test_J08_is_blocked_returns_bool(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        self.assertIsInstance(report.is_blocked(), bool)


# ===========================================================================
# K)  Required gap IDs present in the report
# ===========================================================================

class TestK_RequiredGapIds(unittest.TestCase):
    """K) build_platform_closure_audit_report — required gap IDs present."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def _get_gap_ids(self):
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        return {g.gap_id for g in report.gap_closures}

    def test_K01_gap_v2_truth_persistence_present(self) -> None:
        self.assertIn("GAP_V2_TRUTH_PERSISTENCE", self._get_gap_ids())

    def test_K02_gap_capability_gate_present(self) -> None:
        self.assertIn("GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT", self._get_gap_ids())

    def test_K03_gap_joint_integration_test_present(self) -> None:
        self.assertIn("GAP_JOINT_INTEGRATION_TEST", self._get_gap_ids())

    def test_K04_gap_multi_device_present(self) -> None:
        self.assertIn(
            "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION",
            self._get_gap_ids(),
        )

    def test_K05_gap_durable_truth_convergence_present(self) -> None:
        self.assertIn("GAP_DURABLE_TRUTH_AUTHORITY_CONVERGENCE", self._get_gap_ids())

    def test_K06_gap_continuation_rebind_present(self) -> None:
        self.assertIn("GAP_CONTINUATION_REBIND_CLOSED_LOOP", self._get_gap_ids())

    def test_K07_gap_android_local_ai_present(self) -> None:
        self.assertIn("GAP_ANDROID_LOCAL_AI_DEFAULT_OFF", self._get_gap_ids())

    def test_K08_gap_android_ci_present(self) -> None:
        self.assertIn("GAP_ANDROID_CI", self._get_gap_ids())

    def test_K09_gap_release_gate_present(self) -> None:
        self.assertIn("GAP_RELEASE_GATE_HARD_ENFORCEMENT", self._get_gap_ids())

    def test_K10_gap_runtime_truth_ingress_present(self) -> None:
        self.assertIn("GAP_RUNTIME_TRUTH_SINGLE_INGRESS", self._get_gap_ids())


# ===========================================================================
# L)  No P0 gap is OPEN in the report
# ===========================================================================

class TestL_NoP0GapOpen(unittest.TestCase):
    """L) build_platform_closure_audit_report — no P0 gap from PRs 1–7 is OPEN."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_L01_no_p0_gap_is_open(self) -> None:
        """No P0 gap covered by PRs 1–7 should have status OPEN."""
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            GapClosureStatus,
        )
        # P0 gaps that are in scope for PRs 1–7:
        p0_gap_ids = {
            "GAP_V2_TRUTH_PERSISTENCE",
            "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT",
            "GAP_JOINT_INTEGRATION_TEST",
            "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION",
        }
        report = build_platform_closure_audit_report()
        open_p0 = [
            g.gap_id for g in report.gap_closures
            if g.gap_id in p0_gap_ids and g.status == GapClosureStatus.OPEN
        ]
        self.assertFalse(
            open_p0,
            f"P0 gaps should not be OPEN after PRs 1–7: {open_p0}",
        )

    def test_L02_blocking_issues_list_is_list(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        self.assertIsInstance(report.blocking_issues, list)

    def test_L03_open_gap_ids_match_open_status(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            GapClosureStatus,
        )
        report = build_platform_closure_audit_report()
        expected_open = {
            g.gap_id for g in report.gap_closures
            if g.status == GapClosureStatus.OPEN
        }
        self.assertEqual(set(report.open_gap_ids), expected_open)


# ===========================================================================
# M)  GAP_MULTI_DEVICE is CLOSED (closed by PR-7)
# ===========================================================================

class TestM_MultiDeviceGapClosed(unittest.TestCase):
    """M) GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION is CLOSED by PR-7."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_M01_gap_status_is_closed(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            GapClosureStatus,
        )
        report = build_platform_closure_audit_report()
        multi_gap = next(
            (g for g in report.gap_closures
             if g.gap_id == "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION"),
            None,
        )
        self.assertIsNotNone(multi_gap, "GAP_MULTI_DEVICE not in report")
        self.assertEqual(multi_gap.status, GapClosureStatus.CLOSED)

    def test_M02_closing_pr_references_pr7(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        multi_gap = next(
            (g for g in report.gap_closures
             if g.gap_id == "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION"),
            None,
        )
        self.assertIsNotNone(multi_gap)
        # Closing PR should reference #854 or PR-7
        closing = multi_gap.closing_pr.lower()
        self.assertTrue(
            "854" in closing or "pr-7" in closing,
            f"closing_pr should reference #854 or PR-7, got: {multi_gap.closing_pr!r}",
        )

    def test_M03_code_reference_is_nonempty(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        multi_gap = next(
            g for g in report.gap_closures
            if g.gap_id == "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION"
        )
        self.assertTrue(multi_gap.code_reference)

    def test_M04_test_reference_is_nonempty(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        multi_gap = next(
            g for g in report.gap_closures
            if g.gap_id == "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION"
        )
        self.assertTrue(multi_gap.test_reference)

    def test_M05_multi_device_not_in_open_gap_ids(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        self.assertNotIn(
            "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION",
            report.open_gap_ids,
        )


# ===========================================================================
# N)  Capability tiers are non-empty
# ===========================================================================

class TestN_CapabilityTiersNonEmpty(unittest.TestCase):
    """N) build_platform_closure_audit_report — capability tiers non-empty."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_N01_active_mainline_has_capabilities(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            CapabilityTier,
        )
        report = build_platform_closure_audit_report()
        mainline = [
            c for c in report.capability_boundary
            if c.tier == CapabilityTier.ACTIVE_MAINLINE
        ]
        self.assertGreater(len(mainline), 0)

    def test_N02_conditional_has_capabilities(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            CapabilityTier,
        )
        report = build_platform_closure_audit_report()
        conditional = [
            c for c in report.capability_boundary
            if c.tier == CapabilityTier.CONDITIONAL
        ]
        self.assertGreater(len(conditional), 0)

    def test_N03_structural_only_has_capabilities(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            CapabilityTier,
        )
        report = build_platform_closure_audit_report()
        structural = [
            c for c in report.capability_boundary
            if c.tier == CapabilityTier.STRUCTURAL_ONLY
        ]
        self.assertGreater(len(structural), 0)

    def test_N04_capability_ids_unique(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        ids = [c.capability_id for c in report.capability_boundary]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate capability_ids found")


# ===========================================================================
# O)  All ACTIVE_MAINLINE capabilities have evidence references
# ===========================================================================

class TestO_ActiveMainlineEvidence(unittest.TestCase):
    """O) All ACTIVE_MAINLINE capabilities have non-empty code and test references."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_O01_all_active_mainline_have_code_reference(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            CapabilityTier,
        )
        report = build_platform_closure_audit_report()
        missing = [
            c.capability_id for c in report.capability_boundary
            if c.tier == CapabilityTier.ACTIVE_MAINLINE and not c.code_reference
        ]
        self.assertFalse(
            missing,
            f"ACTIVE_MAINLINE capabilities missing code_reference: {missing}",
        )

    def test_O02_all_active_mainline_have_test_reference(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            CapabilityTier,
        )
        report = build_platform_closure_audit_report()
        missing = [
            c.capability_id for c in report.capability_boundary
            if c.tier == CapabilityTier.ACTIVE_MAINLINE and not c.test_reference
        ]
        self.assertFalse(
            missing,
            f"ACTIVE_MAINLINE capabilities missing test_reference: {missing}",
        )


# ===========================================================================
# P)  CONDITIONAL capabilities have non-empty condition
# ===========================================================================

class TestP_ConditionalCapabilitiesHaveCondition(unittest.TestCase):
    """P) CONDITIONAL capabilities have non-empty condition string."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_P01_all_conditional_have_condition_string(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            CapabilityTier,
        )
        report = build_platform_closure_audit_report()
        missing = [
            c.capability_id for c in report.capability_boundary
            if c.tier == CapabilityTier.CONDITIONAL and not c.condition
        ]
        self.assertFalse(
            missing,
            f"CONDITIONAL capabilities missing condition: {missing}",
        )


# ===========================================================================
# Q)  Operational risks present and well-formed
# ===========================================================================

class TestQ_OperationalRisks(unittest.TestCase):
    """Q) Operational risks are present and well-formed."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_Q01_at_least_one_operational_risk(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        self.assertGreater(len(report.operational_risks), 0)

    def test_Q02_all_risks_have_nonempty_risk_id(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        for risk in report.operational_risks:
            self.assertTrue(risk.risk_id, f"Empty risk_id in {risk}")

    def test_Q03_all_risks_have_valid_severity(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        for risk in report.operational_risks:
            self.assertIn(
                risk.severity, ("P0", "P1", "P2"),
                f"Invalid severity '{risk.severity}' for risk {risk.risk_id}",
            )

    def test_Q04_all_risks_have_nonempty_follow_up(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        for risk in report.operational_risks:
            self.assertTrue(
                risk.follow_up,
                f"Empty follow_up for risk {risk.risk_id}",
            )

    def test_Q05_risk_runtime_truth_bypass_present(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        ids = {r.risk_id for r in report.operational_risks}
        self.assertIn("RISK_RUNTIME_TRUTH_BYPASS", ids)

    def test_Q06_risk_android_ci_absent_present(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        ids = {r.risk_id for r in report.operational_risks}
        self.assertIn("RISK_ANDROID_CI_ABSENT", ids)


# ===========================================================================
# R)  PlatformClosureAuditReport.summary() — required keys
# ===========================================================================

class TestR_Summary(unittest.TestCase):
    """R) PlatformClosureAuditReport.summary() — required keys."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_R01_summary_has_required_keys(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        s = report.summary()
        required_keys = {
            "report_id",
            "gaps_closed",
            "gaps_open",
            "open_gap_ids",
            "capability_tiers",
            "blocking_issues_count",
            "operational_risks_count",
            "is_blocked",
        }
        missing = required_keys - set(s.keys())
        self.assertFalse(missing, f"Missing keys in summary(): {missing}")

    def test_R02_summary_gaps_closed_is_int(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        s = report.summary()
        self.assertIsInstance(s["gaps_closed"], int)

    def test_R03_summary_is_blocked_is_bool(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        s = report.summary()
        self.assertIsInstance(s["is_blocked"], bool)

    def test_R04_summary_capability_tiers_is_dict(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        s = report.summary()
        self.assertIsInstance(s["capability_tiers"], dict)


# ===========================================================================
# S)  to_dict() — JSON-serialisable
# ===========================================================================

class TestS_ToDictJsonSerializable(unittest.TestCase):
    """S) PlatformClosureAuditReport.to_dict() is JSON-serialisable."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_S01_to_dict_serialisable(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        d = report.to_dict()
        serialised = json.dumps(d)
        self.assertIsInstance(serialised, str)
        self.assertGreater(len(serialised), 100)

    def test_S02_to_dict_roundtrip(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        d = report.to_dict()
        restored = json.loads(json.dumps(d))
        self.assertEqual(restored["report_id"], d["report_id"])
        self.assertEqual(len(restored["gap_closures"]), len(d["gap_closures"]))

    def test_S03_to_dict_has_top_level_keys(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        d = report.to_dict()
        for key in (
            "report_id",
            "generated_at",
            "gap_closures",
            "capability_boundary",
            "readiness_tiers",
            "operational_risks",
            "blocking_issues",
            "open_gap_ids",
        ):
            self.assertIn(key, d)


# ===========================================================================
# T)  Singleton management
# ===========================================================================

class TestT_SingletonManagement(unittest.TestCase):
    """T) Singleton management — get / reset / rebuild."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_T01_get_returns_same_instance(self) -> None:
        from core.platform_closure_audit import get_platform_closure_audit_report
        r1 = get_platform_closure_audit_report()
        r2 = get_platform_closure_audit_report()
        self.assertIs(r1, r2)

    def test_T02_reset_causes_rebuild(self) -> None:
        from core.platform_closure_audit import (
            get_platform_closure_audit_report,
            reset_platform_closure_audit,
        )
        r1 = get_platform_closure_audit_report()
        reset_platform_closure_audit()
        r2 = get_platform_closure_audit_report()
        self.assertIsNot(r1, r2)

    def test_T03_build_always_returns_new_instance(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        r1 = build_platform_closure_audit_report()
        r2 = build_platform_closure_audit_report()
        self.assertIsNot(r1, r2)
        self.assertNotEqual(r1.report_id, r2.report_id)


# ===========================================================================
# U)  CLOSED gap code_reference non-empty
# ===========================================================================

class TestU_ClosedGapCodeReference(unittest.TestCase):
    """U) Evidence-bound conclusions — code_reference non-empty for CLOSED gaps."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_U01_all_closed_gaps_have_code_reference(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            GapClosureStatus,
        )
        report = build_platform_closure_audit_report()
        missing = [
            g.gap_id for g in report.gap_closures
            if g.status == GapClosureStatus.CLOSED and not g.code_reference
        ]
        self.assertFalse(
            missing,
            f"CLOSED gaps missing code_reference: {missing}",
        )

    def test_U02_all_closed_conditional_gaps_have_code_reference(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            GapClosureStatus,
        )
        report = build_platform_closure_audit_report()
        missing = [
            g.gap_id for g in report.gap_closures
            if g.status == GapClosureStatus.CLOSED_CONDITIONAL
            and not g.code_reference
        ]
        self.assertFalse(
            missing,
            f"CLOSED_CONDITIONAL gaps missing code_reference: {missing}",
        )


# ===========================================================================
# V)  CLOSED gap test_reference non-empty
# ===========================================================================

class TestV_ClosedGapTestReference(unittest.TestCase):
    """V) Evidence-bound conclusions — test_reference non-empty for CLOSED gaps."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_V01_all_closed_gaps_have_test_reference(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            GapClosureStatus,
        )
        report = build_platform_closure_audit_report()
        missing = [
            g.gap_id for g in report.gap_closures
            if g.status == GapClosureStatus.CLOSED and not g.test_reference
        ]
        self.assertFalse(
            missing,
            f"CLOSED gaps missing test_reference: {missing}",
        )


# ===========================================================================
# W)  dual_repo_system_map — GAP_MULTI_DEVICE resolved=True
# ===========================================================================

class TestW_DualRepoSystemMapGapResolved(unittest.TestCase):
    """W) dual_repo_system_map.WORKSTREAM_GAP_REGISTRY — GAP_MULTI_DEVICE resolved=True."""

    def test_W01_gap_multi_device_resolved_true(self) -> None:
        from core.dual_repo_system_map import WORKSTREAM_GAP_REGISTRY
        entry = next(
            (g for g in WORKSTREAM_GAP_REGISTRY
             if g.gap_id == "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION"),
            None,
        )
        self.assertIsNotNone(
            entry,
            "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION not in WORKSTREAM_GAP_REGISTRY",
        )
        self.assertTrue(
            entry.resolved,
            "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION must be resolved=True "
            "after PR-7 (#854)",
        )

    def test_W02_resolution_pr_references_854(self) -> None:
        from core.dual_repo_system_map import WORKSTREAM_GAP_REGISTRY
        entry = next(
            g for g in WORKSTREAM_GAP_REGISTRY
            if g.gap_id == "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION"
        )
        self.assertTrue(
            entry.resolution_pr and "854" in entry.resolution_pr,
            f"resolution_pr should reference #854, got: {entry.resolution_pr!r}",
        )


# ===========================================================================
# X)  dual_repo_system_map — no P0 gap resolved=False
# ===========================================================================

class TestX_NoP0GapUnresolved(unittest.TestCase):
    """X) dual_repo_system_map — no P0 gap is resolved=False after PRs 1–7."""

    def test_X01_no_p0_gap_unresolved(self) -> None:
        from core.dual_repo_system_map import WORKSTREAM_GAP_REGISTRY, GapSeverity
        open_p0 = [
            g.gap_id for g in WORKSTREAM_GAP_REGISTRY
            if g.severity == GapSeverity.P0 and not g.resolved
        ]
        self.assertFalse(
            open_p0,
            f"P0 gaps must be resolved after PRs 1–7: {open_p0}",
        )


# ===========================================================================
# Y)  Open gap count — only non-P0 gaps remain open
# ===========================================================================

class TestY_OpenGapsAreNonP0(unittest.TestCase):
    """Y) Open gaps in the report correspond only to non-P0 gaps."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_Y01_open_gaps_are_not_p0(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            GapClosureStatus,
        )
        from core.dual_repo_system_map import WORKSTREAM_GAP_REGISTRY, GapSeverity

        report = build_platform_closure_audit_report()
        open_ids = {g.gap_id for g in report.gap_closures if g.status == GapClosureStatus.OPEN}
        p0_registry = {g.gap_id for g in WORKSTREAM_GAP_REGISTRY if g.severity == GapSeverity.P0}

        open_p0 = open_ids & p0_registry
        self.assertFalse(
            open_p0,
            f"Report has OPEN status for P0 gaps: {open_p0}",
        )


# ===========================================================================
# Z)  Readiness tiers — all four tiers present
# ===========================================================================

class TestZ_AllFourTiersPresent(unittest.TestCase):
    """Z) Readiness tiers — all four CapabilityTier values appear in readiness_tiers."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_Z01_all_four_tiers_present(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            CapabilityTier,
        )
        report = build_platform_closure_audit_report()
        present_tiers = {r.tier for r in report.readiness_tiers}
        for tier in CapabilityTier:
            self.assertIn(
                tier, present_tiers,
                f"Tier {tier.value} missing from readiness_tiers",
            )

    def test_Z02_readiness_tier_summaries_nonempty(self) -> None:
        from core.platform_closure_audit import build_platform_closure_audit_report
        report = build_platform_closure_audit_report()
        for tier_entry in report.readiness_tiers:
            self.assertTrue(
                tier_entry.summary,
                f"Empty summary for tier {tier_entry.tier.value}",
            )

    def test_Z03_active_mainline_tier_has_capability_ids(self) -> None:
        from core.platform_closure_audit import (
            build_platform_closure_audit_report,
            CapabilityTier,
        )
        report = build_platform_closure_audit_report()
        mainline_tier = next(
            (r for r in report.readiness_tiers
             if r.tier == CapabilityTier.ACTIVE_MAINLINE),
            None,
        )
        self.assertIsNotNone(mainline_tier)
        self.assertGreater(
            len(mainline_tier.capability_ids), 0,
            "ACTIVE_MAINLINE tier should have at least one capability_id",
        )


if __name__ == "__main__":
    unittest.main()
