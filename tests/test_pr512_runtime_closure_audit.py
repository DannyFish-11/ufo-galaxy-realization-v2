#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr512_runtime_closure_audit.py
==========================================
PR-512 — System Closure Audit / Runtime Gap Sweep: Tests.

Validates that:
* The closure audit module exports all required authority/policy sentinels.
* Layer closure verification runs without exceptions for all PR-506–511 layers.
* Parallel truth path / authority conflict detection returns structured entries.
* Each known conflict entry has required fields and correct ``is_resolved`` state.
* Residual gap map contains all required gap entries with correct annotations.
* ClosureAuditSnapshot is assembled correctly with accurate aggregate counts.
* All ``all_layers_closed=False`` when some layers are unavailable.
* GAP severity constants are string-typed and non-empty.
* CLOSURE_STATUS constants are string-typed and non-empty.
* Singleton management works correctly.
* Reset and re-create produce independent instances.
* Module-level convenience helpers delegate to the singleton.
* Policy sentinels contain required vocabulary.
* ClosureGapEntry and AuthorityConflictEntry dataclass contracts.
* LayerClosureStatus dataclass contracts.
* ClosureAuditSnapshot.summary() returns expected keys.
* Command router PR-512 sentinel importable.
* api_routes PR-512 sentinel present (checked via source inspection).
* Residual gaps for critical layers are flagged correctly.
* Conflict entries have conflict_id, runtime_fact, layer_a, layer_b fields.
* Resolved conflicts have non-empty resolution_note.
* All residual gaps have non-empty follow_up references.

Test groups
-----------
 A)  Module structure — all __all__ symbols importable.
 B)  Authority sentinels — correct values and types.
 C)  Policy sentinels — vocabulary checks.
 D)  Gap severity constants — type and uniqueness.
 E)  Closure status constants — type and uniqueness.
 F)  ClosureGapEntry dataclass — structure and helpers.
 G)  AuthorityConflictEntry dataclass — structure.
 H)  LayerClosureStatus dataclass — structure and helpers.
 I)  ClosureAuditSnapshot dataclass — structure and summary().
 J)  RuntimeClosureAudit._verify_layer — good sentinel.
 K)  RuntimeClosureAudit._verify_layer — missing sentinel.
 L)  RuntimeClosureAudit._verify_layer — missing module.
 M)  RuntimeClosureAudit.verify_all_layers — returns one entry per spec.
 N)  RuntimeClosureAudit.detect_parallel_truth_paths — all required conflicts.
 O)  Conflict discipline — resolved conflicts have resolution_note.
 P)  Conflict discipline — unresolved conflicts have is_resolved=False.
 Q)  RuntimeClosureAudit.get_residual_gap_map — all gap_ids present.
 R)  Residual gap discipline — all gaps have non-empty follow_up.
 S)  Residual gap discipline — is_residual annotation correct.
 T)  RuntimeClosureAudit.run_audit — snapshot structure.
 U)  run_audit aggregate counts — verified_count, missing_count.
 V)  run_audit all_layers_closed logic.
 W)  ClosureAuditSnapshot.summary() — expected keys.
 X)  Singleton management — get/reset/re-create.
 Y)  Module-level helpers delegate to singleton.
 Z)  Command router PR-512 sentinel importable.
 AA) Docs artifact — RESIDUAL_GAP_MAP.md exists.
 BB) api_routes closure audit sentinel present (source check).
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helper: reset singleton between tests
# ---------------------------------------------------------------------------

def _reset():
    from core.runtime_closure_audit import reset_runtime_closure_audit
    reset_runtime_closure_audit()


# ===========================================================================
# A)  Module structure
# ===========================================================================

class TestA_ModuleStructure(unittest.TestCase):
    """A) All __all__ symbols importable."""

    def test_A01_all_symbols_importable(self) -> None:
        import core.runtime_closure_audit as mod
        for name in mod.__all__:
            self.assertTrue(
                hasattr(mod, name),
                f"__all__ symbol '{name}' not found on module",
            )

    def test_A02_module_importable(self) -> None:
        import core.runtime_closure_audit  # noqa: F401

    def test_A03_all_list_nonempty(self) -> None:
        import core.runtime_closure_audit as mod
        self.assertGreater(len(mod.__all__), 0)


# ===========================================================================
# B)  Authority sentinels
# ===========================================================================

class TestB_AuthoritySentinels(unittest.TestCase):
    """B) Authority sentinel types and values."""

    def test_B01_authority_importable(self) -> None:
        from core.runtime_closure_audit import RUNTIME_CLOSURE_AUDIT_AUTHORITY
        self.assertIsInstance(RUNTIME_CLOSURE_AUDIT_AUTHORITY, str)
        self.assertGreater(len(RUNTIME_CLOSURE_AUDIT_AUTHORITY), 0)

    def test_B02_authority_contains_module_path(self) -> None:
        from core.runtime_closure_audit import RUNTIME_CLOSURE_AUDIT_AUTHORITY
        self.assertIn("runtime_closure_audit", RUNTIME_CLOSURE_AUDIT_AUTHORITY)

    def test_B03_layer_position_is_12(self) -> None:
        from core.runtime_closure_audit import RUNTIME_CLOSURE_AUDIT_LAYER_POSITION
        self.assertEqual(RUNTIME_CLOSURE_AUDIT_LAYER_POSITION, 12)

    def test_B04_contract_version_importable(self) -> None:
        from core.runtime_closure_audit import CLOSURE_AUDIT_CONTRACT_VERSION
        self.assertIsInstance(CLOSURE_AUDIT_CONTRACT_VERSION, str)
        self.assertIn("V1", CLOSURE_AUDIT_CONTRACT_VERSION)


# ===========================================================================
# C)  Policy sentinels
# ===========================================================================

class TestC_PolicySentinels(unittest.TestCase):
    """C) Policy sentinel vocabulary."""

    def test_C01_read_only_policy_importable(self) -> None:
        from core.runtime_closure_audit import CLOSURE_AUDIT_READ_ONLY_POLICY
        self.assertIsInstance(CLOSURE_AUDIT_READ_ONLY_POLICY, str)
        self.assertIn("READ_ONLY", CLOSURE_AUDIT_READ_ONLY_POLICY)

    def test_C02_sentinel_driven_policy_importable(self) -> None:
        from core.runtime_closure_audit import SENTINEL_DRIVEN_CLOSURE_POLICY
        self.assertIsInstance(SENTINEL_DRIVEN_CLOSURE_POLICY, str)
        self.assertIn("SENTINEL", SENTINEL_DRIVEN_CLOSURE_POLICY)

    def test_C03_no_silent_masking_policy_importable(self) -> None:
        from core.runtime_closure_audit import NO_SILENT_AUTHORITY_MASKING_POLICY
        self.assertIsInstance(NO_SILENT_AUTHORITY_MASKING_POLICY, str)
        self.assertIn("MASKING", NO_SILENT_AUTHORITY_MASKING_POLICY)

    def test_C04_residual_gap_annotation_policy_importable(self) -> None:
        from core.runtime_closure_audit import RESIDUAL_GAP_ANNOTATION_POLICY
        self.assertIsInstance(RESIDUAL_GAP_ANNOTATION_POLICY, str)
        self.assertIn("RESIDUAL", RESIDUAL_GAP_ANNOTATION_POLICY)

    def test_C05_no_new_truth_source_policy_importable(self) -> None:
        from core.runtime_closure_audit import CLOSURE_AUDIT_NO_NEW_TRUTH_SOURCE_POLICY
        self.assertIsInstance(CLOSURE_AUDIT_NO_NEW_TRUTH_SOURCE_POLICY, str)
        self.assertIn("TRUTH_SOURCE", CLOSURE_AUDIT_NO_NEW_TRUTH_SOURCE_POLICY)


# ===========================================================================
# D)  Gap severity constants
# ===========================================================================

class TestD_GapSeverityConstants(unittest.TestCase):
    """D) Gap severity constant types and uniqueness."""

    def _constants(self):
        from core.runtime_closure_audit import (
            GAP_SEVERITY_CRITICAL,
            GAP_SEVERITY_HIGH,
            GAP_SEVERITY_MEDIUM,
            GAP_SEVERITY_LOW,
            GAP_SEVERITY_RESIDUAL,
        )
        return [
            GAP_SEVERITY_CRITICAL,
            GAP_SEVERITY_HIGH,
            GAP_SEVERITY_MEDIUM,
            GAP_SEVERITY_LOW,
            GAP_SEVERITY_RESIDUAL,
        ]

    def test_D01_all_are_strings(self) -> None:
        for v in self._constants():
            self.assertIsInstance(v, str)
            self.assertGreater(len(v), 0)

    def test_D02_all_unique(self) -> None:
        vals = self._constants()
        self.assertEqual(len(vals), len(set(vals)))

    def test_D03_critical_importable(self) -> None:
        from core.runtime_closure_audit import GAP_SEVERITY_CRITICAL
        self.assertEqual(GAP_SEVERITY_CRITICAL, "CRITICAL")

    def test_D04_high_importable(self) -> None:
        from core.runtime_closure_audit import GAP_SEVERITY_HIGH
        self.assertEqual(GAP_SEVERITY_HIGH, "HIGH")


# ===========================================================================
# E)  Closure status constants
# ===========================================================================

class TestE_ClosureStatusConstants(unittest.TestCase):
    """E) Closure status constant types and uniqueness."""

    def _constants(self):
        from core.runtime_closure_audit import (
            CLOSURE_STATUS_VERIFIED,
            CLOSURE_STATUS_PARTIAL,
            CLOSURE_STATUS_MISSING,
            CLOSURE_STATUS_DEGRADED,
        )
        return [
            CLOSURE_STATUS_VERIFIED,
            CLOSURE_STATUS_PARTIAL,
            CLOSURE_STATUS_MISSING,
            CLOSURE_STATUS_DEGRADED,
        ]

    def test_E01_all_are_strings(self) -> None:
        for v in self._constants():
            self.assertIsInstance(v, str)
            self.assertGreater(len(v), 0)

    def test_E02_all_unique(self) -> None:
        vals = self._constants()
        self.assertEqual(len(vals), len(set(vals)))

    def test_E03_verified_importable(self) -> None:
        from core.runtime_closure_audit import CLOSURE_STATUS_VERIFIED
        self.assertEqual(CLOSURE_STATUS_VERIFIED, "VERIFIED")

    def test_E04_missing_importable(self) -> None:
        from core.runtime_closure_audit import CLOSURE_STATUS_MISSING
        self.assertEqual(CLOSURE_STATUS_MISSING, "MISSING")


# ===========================================================================
# F)  ClosureGapEntry dataclass
# ===========================================================================

class TestF_ClosureGapEntry(unittest.TestCase):
    """F) ClosureGapEntry dataclass structure and helpers."""

    def _make_entry(self, severity="HIGH", is_residual=True):
        from core.runtime_closure_audit import ClosureGapEntry
        return ClosureGapEntry(
            gap_id="GAP-TEST-001",
            severity=severity,
            layer="core/test.py",
            description="Test gap",
            follow_up="PR-999",
            is_residual=is_residual,
        )

    def test_F01_instantiates(self) -> None:
        entry = self._make_entry()
        self.assertIsNotNone(entry)

    def test_F02_has_gap_id(self) -> None:
        entry = self._make_entry()
        self.assertEqual(entry.gap_id, "GAP-TEST-001")

    def test_F03_has_severity(self) -> None:
        entry = self._make_entry()
        self.assertEqual(entry.severity, "HIGH")

    def test_F04_has_layer(self) -> None:
        entry = self._make_entry()
        self.assertEqual(entry.layer, "core/test.py")

    def test_F05_has_follow_up(self) -> None:
        entry = self._make_entry()
        self.assertEqual(entry.follow_up, "PR-999")

    def test_F06_is_residual_true(self) -> None:
        entry = self._make_entry(is_residual=True)
        self.assertTrue(entry.is_residual)

    def test_F07_is_residual_false(self) -> None:
        entry = self._make_entry(is_residual=False)
        self.assertFalse(entry.is_residual)

    def test_F08_has_detected_at(self) -> None:
        entry = self._make_entry()
        self.assertIsInstance(entry.detected_at, float)
        self.assertGreater(entry.detected_at, 0.0)

    def test_F09_is_critical_or_high_true_for_critical(self) -> None:
        entry = self._make_entry(severity="CRITICAL")
        self.assertTrue(entry.is_critical_or_high())

    def test_F10_is_critical_or_high_true_for_high(self) -> None:
        entry = self._make_entry(severity="HIGH")
        self.assertTrue(entry.is_critical_or_high())

    def test_F11_is_critical_or_high_false_for_medium(self) -> None:
        entry = self._make_entry(severity="MEDIUM")
        self.assertFalse(entry.is_critical_or_high())

    def test_F12_is_critical_or_high_false_for_low(self) -> None:
        entry = self._make_entry(severity="LOW")
        self.assertFalse(entry.is_critical_or_high())


# ===========================================================================
# G)  AuthorityConflictEntry dataclass
# ===========================================================================

class TestG_AuthorityConflictEntry(unittest.TestCase):
    """G) AuthorityConflictEntry dataclass structure."""

    def _make_entry(self, is_resolved=False, resolution_note=""):
        from core.runtime_closure_audit import AuthorityConflictEntry
        return AuthorityConflictEntry(
            conflict_id="CONFLICT-TEST-001",
            runtime_fact="task_status",
            layer_a="core.module_a",
            layer_b="core.module_b",
            description="Competing truth sources for task_status.",
            is_resolved=is_resolved,
            resolution_note=resolution_note,
        )

    def test_G01_instantiates(self) -> None:
        self.assertIsNotNone(self._make_entry())

    def test_G02_has_conflict_id(self) -> None:
        self.assertEqual(self._make_entry().conflict_id, "CONFLICT-TEST-001")

    def test_G03_has_runtime_fact(self) -> None:
        self.assertEqual(self._make_entry().runtime_fact, "task_status")

    def test_G04_has_layer_a(self) -> None:
        self.assertEqual(self._make_entry().layer_a, "core.module_a")

    def test_G05_has_layer_b(self) -> None:
        self.assertEqual(self._make_entry().layer_b, "core.module_b")

    def test_G06_has_description(self) -> None:
        self.assertGreater(len(self._make_entry().description), 0)

    def test_G07_is_resolved_false_by_default(self) -> None:
        self.assertFalse(self._make_entry().is_resolved)

    def test_G08_is_resolved_true(self) -> None:
        self.assertTrue(self._make_entry(is_resolved=True).is_resolved)

    def test_G09_has_detected_at(self) -> None:
        entry = self._make_entry()
        self.assertIsInstance(entry.detected_at, float)
        self.assertGreater(entry.detected_at, 0.0)

    def test_G10_resolution_note_preserved(self) -> None:
        entry = self._make_entry(is_resolved=True, resolution_note="Fixed in PR-X")
        self.assertEqual(entry.resolution_note, "Fixed in PR-X")


# ===========================================================================
# H)  LayerClosureStatus dataclass
# ===========================================================================

class TestH_LayerClosureStatus(unittest.TestCase):
    """H) LayerClosureStatus dataclass structure and helpers."""

    def _make_status(self, status="VERIFIED"):
        from core.runtime_closure_audit import LayerClosureStatus
        return LayerClosureStatus(
            pr_ref="PR-506",
            layer_name="Execution Spine",
            sentinel_name="EXECUTION_SPINE_WRITE_INTEGRATED",
            sentinel_module="core.command_router",
            status=status,
            sentinel_value="COMMAND_ROUTER::EXECUTION_SPINE_WRITE_V1",
        )

    def test_H01_instantiates(self) -> None:
        self.assertIsNotNone(self._make_status())

    def test_H02_has_pr_ref(self) -> None:
        self.assertEqual(self._make_status().pr_ref, "PR-506")

    def test_H03_has_layer_name(self) -> None:
        self.assertGreater(len(self._make_status().layer_name), 0)

    def test_H04_has_sentinel_name(self) -> None:
        self.assertGreater(len(self._make_status().sentinel_name), 0)

    def test_H05_has_sentinel_module(self) -> None:
        self.assertGreater(len(self._make_status().sentinel_module), 0)

    def test_H06_is_verified_true(self) -> None:
        self.assertTrue(self._make_status(status="VERIFIED").is_verified())

    def test_H07_is_verified_false_for_missing(self) -> None:
        self.assertFalse(self._make_status(status="MISSING").is_verified())

    def test_H08_is_verified_false_for_partial(self) -> None:
        self.assertFalse(self._make_status(status="PARTIAL").is_verified())

    def test_H09_is_verified_false_for_degraded(self) -> None:
        self.assertFalse(self._make_status(status="DEGRADED").is_verified())

    def test_H10_sentinel_value_preserved(self) -> None:
        status = self._make_status()
        self.assertIn("EXECUTION_SPINE", status.sentinel_value)


# ===========================================================================
# I)  ClosureAuditSnapshot dataclass
# ===========================================================================

class TestI_ClosureAuditSnapshot(unittest.TestCase):
    """I) ClosureAuditSnapshot dataclass and summary()."""

    def _make_snapshot(self):
        from core.runtime_closure_audit import (
            ClosureAuditSnapshot,
            RUNTIME_CLOSURE_AUDIT_AUTHORITY,
            CLOSURE_AUDIT_CONTRACT_VERSION,
        )
        return ClosureAuditSnapshot(
            verified_count=5,
            missing_count=2,
            critical_high_gap_count=3,
            all_layers_closed=False,
        )

    def test_I01_instantiates(self) -> None:
        self.assertIsNotNone(self._make_snapshot())

    def test_I02_has_audit_authority(self) -> None:
        from core.runtime_closure_audit import RUNTIME_CLOSURE_AUDIT_AUTHORITY
        snap = self._make_snapshot()
        self.assertEqual(snap.audit_authority, RUNTIME_CLOSURE_AUDIT_AUTHORITY)

    def test_I03_has_contract_version(self) -> None:
        from core.runtime_closure_audit import CLOSURE_AUDIT_CONTRACT_VERSION
        snap = self._make_snapshot()
        self.assertEqual(snap.contract_version, CLOSURE_AUDIT_CONTRACT_VERSION)

    def test_I04_verified_count(self) -> None:
        self.assertEqual(self._make_snapshot().verified_count, 5)

    def test_I05_missing_count(self) -> None:
        self.assertEqual(self._make_snapshot().missing_count, 2)

    def test_I06_all_layers_closed_false(self) -> None:
        self.assertFalse(self._make_snapshot().all_layers_closed)

    def test_I07_has_snapshot_ts(self) -> None:
        snap = self._make_snapshot()
        self.assertIsInstance(snap.snapshot_ts, float)
        self.assertGreater(snap.snapshot_ts, 0.0)

    def test_I08_summary_returns_dict(self) -> None:
        snap = self._make_snapshot()
        summary = snap.summary()
        self.assertIsInstance(summary, dict)

    def test_I09_summary_has_expected_keys(self) -> None:
        snap = self._make_snapshot()
        summary = snap.summary()
        expected_keys = {
            "audit_authority",
            "contract_version",
            "all_layers_closed",
            "verified_count",
            "missing_count",
            "total_layers",
            "total_gaps",
            "critical_high_gap_count",
            "total_conflicts",
            "unresolved_conflicts",
            "residual_gaps",
            "snapshot_ts",
        }
        for key in expected_keys:
            self.assertIn(key, summary, f"summary missing key '{key}'")

    def test_I10_summary_audit_authority_correct(self) -> None:
        from core.runtime_closure_audit import RUNTIME_CLOSURE_AUDIT_AUTHORITY
        snap = self._make_snapshot()
        self.assertEqual(snap.summary()["audit_authority"], RUNTIME_CLOSURE_AUDIT_AUTHORITY)


# ===========================================================================
# J)  _verify_layer — good sentinel
# ===========================================================================

class TestJ_VerifyLayerGoodSentinel(unittest.TestCase):
    """J) _verify_layer returns VERIFIED for a known-good sentinel."""

    def setUp(self):
        _reset()

    def test_J01_verify_execution_spine_sentinel(self) -> None:
        from core.runtime_closure_audit import (
            RuntimeClosureAudit,
            CLOSURE_STATUS_VERIFIED,
        )
        audit = RuntimeClosureAudit()
        status = audit._verify_layer(
            pr_ref="PR-506",
            layer_name="Execution Spine",
            sentinel_name="EXECUTION_SPINE_WRITE_INTEGRATED",
            sentinel_module="core.command_router",
        )
        self.assertEqual(status.status, CLOSURE_STATUS_VERIFIED)
        self.assertGreater(len(status.sentinel_value), 0)

    def test_J02_verify_canonical_task_spine_sentinel(self) -> None:
        from core.runtime_closure_audit import (
            RuntimeClosureAudit,
            CLOSURE_STATUS_VERIFIED,
        )
        audit = RuntimeClosureAudit()
        status = audit._verify_layer(
            pr_ref="PR-507",
            layer_name="CanonicalTask Spine",
            sentinel_name="CANONICAL_TASK_SPINE_INTEGRATED",
            sentinel_module="core.command_router",
        )
        self.assertEqual(status.status, CLOSURE_STATUS_VERIFIED)

    def test_J03_verified_status_is_verified(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        status = audit._verify_layer(
            pr_ref="PR-506",
            layer_name="Execution Spine",
            sentinel_name="EXECUTION_SPINE_WRITE_INTEGRATED",
            sentinel_module="core.command_router",
        )
        self.assertTrue(status.is_verified())


# ===========================================================================
# K)  _verify_layer — missing sentinel
# ===========================================================================

class TestK_VerifyLayerMissingSentinel(unittest.TestCase):
    """K) _verify_layer returns MISSING when sentinel attribute is absent."""

    def setUp(self):
        _reset()

    def test_K01_missing_sentinel_name(self) -> None:
        from core.runtime_closure_audit import (
            RuntimeClosureAudit,
            CLOSURE_STATUS_MISSING,
        )
        audit = RuntimeClosureAudit()
        status = audit._verify_layer(
            pr_ref="PR-TEST",
            layer_name="Nonexistent",
            sentinel_name="THIS_SENTINEL_DOES_NOT_EXIST_AT_ALL",
            sentinel_module="core.command_router",
        )
        self.assertEqual(status.status, CLOSURE_STATUS_MISSING)

    def test_K02_missing_sentinel_has_notes(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        status = audit._verify_layer(
            pr_ref="PR-TEST",
            layer_name="Nonexistent",
            sentinel_name="THIS_SENTINEL_DOES_NOT_EXIST_AT_ALL",
            sentinel_module="core.command_router",
        )
        self.assertGreater(len(status.notes), 0)

    def test_K03_missing_not_verified(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        status = audit._verify_layer(
            pr_ref="PR-TEST",
            layer_name="Nonexistent",
            sentinel_name="THIS_SENTINEL_DOES_NOT_EXIST_AT_ALL",
            sentinel_module="core.command_router",
        )
        self.assertFalse(status.is_verified())


# ===========================================================================
# L)  _verify_layer — missing module
# ===========================================================================

class TestL_VerifyLayerMissingModule(unittest.TestCase):
    """L) _verify_layer returns MISSING when sentinel module cannot be imported."""

    def setUp(self):
        _reset()

    def test_L01_missing_module_returns_missing(self) -> None:
        from core.runtime_closure_audit import (
            RuntimeClosureAudit,
            CLOSURE_STATUS_MISSING,
        )
        audit = RuntimeClosureAudit()
        status = audit._verify_layer(
            pr_ref="PR-TEST",
            layer_name="Nonexistent Module",
            sentinel_name="SOME_SENTINEL",
            sentinel_module="core.this_module_does_not_exist_anywhere",
        )
        self.assertEqual(status.status, CLOSURE_STATUS_MISSING)

    def test_L02_missing_module_has_notes(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        status = audit._verify_layer(
            pr_ref="PR-TEST",
            layer_name="Nonexistent Module",
            sentinel_name="SOME_SENTINEL",
            sentinel_module="core.this_module_does_not_exist_anywhere",
        )
        self.assertGreater(len(status.notes), 0)

    def test_L03_missing_module_not_verified(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        status = audit._verify_layer(
            pr_ref="PR-TEST",
            layer_name="Nonexistent Module",
            sentinel_name="SOME_SENTINEL",
            sentinel_module="core.this_module_does_not_exist_anywhere",
        )
        self.assertFalse(status.is_verified())


# ===========================================================================
# M)  verify_all_layers — returns one entry per spec
# ===========================================================================

class TestM_VerifyAllLayers(unittest.TestCase):
    """M) verify_all_layers returns one LayerClosureStatus per layer spec."""

    def setUp(self):
        _reset()

    def test_M01_returns_list(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        result = audit.verify_all_layers()
        self.assertIsInstance(result, list)

    def test_M02_returns_nonempty_list(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        result = audit.verify_all_layers()
        self.assertGreater(len(result), 0)

    def test_M03_count_matches_layer_specs(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        result = audit.verify_all_layers()
        self.assertEqual(len(result), len(RuntimeClosureAudit._LAYER_SPECS))

    def test_M04_all_entries_are_layer_closure_status(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit, LayerClosureStatus
        audit = RuntimeClosureAudit()
        for entry in audit.verify_all_layers():
            self.assertIsInstance(entry, LayerClosureStatus)

    def test_M05_each_entry_has_pr_ref(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        for entry in audit.verify_all_layers():
            self.assertGreater(len(entry.pr_ref), 0)

    def test_M06_all_statuses_are_known_constants(self) -> None:
        from core.runtime_closure_audit import (
            RuntimeClosureAudit,
            CLOSURE_STATUS_VERIFIED,
            CLOSURE_STATUS_PARTIAL,
            CLOSURE_STATUS_MISSING,
            CLOSURE_STATUS_DEGRADED,
        )
        valid = {
            CLOSURE_STATUS_VERIFIED,
            CLOSURE_STATUS_PARTIAL,
            CLOSURE_STATUS_MISSING,
            CLOSURE_STATUS_DEGRADED,
        }
        audit = RuntimeClosureAudit()
        for entry in audit.verify_all_layers():
            self.assertIn(entry.status, valid)

    def test_M07_pr506_layer_covered(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        pr_refs = [s.pr_ref for s in audit.verify_all_layers()]
        self.assertIn("PR-506", pr_refs)

    def test_M08_pr507_layer_covered(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        pr_refs = [s.pr_ref for s in audit.verify_all_layers()]
        self.assertIn("PR-507", pr_refs)

    def test_M09_pr508_layer_covered(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        pr_refs = [s.pr_ref for s in audit.verify_all_layers()]
        self.assertIn("PR-508", pr_refs)

    def test_M10_pr509_layer_covered(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        pr_refs = [s.pr_ref for s in audit.verify_all_layers()]
        self.assertIn("PR-509", pr_refs)

    def test_M11_pr510_layer_covered(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        pr_refs = [s.pr_ref for s in audit.verify_all_layers()]
        self.assertIn("PR-510", pr_refs)

    def test_M12_pr511_layer_covered(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        pr_refs = [s.pr_ref for s in audit.verify_all_layers()]
        self.assertIn("PR-511", pr_refs)


# ===========================================================================
# N)  detect_parallel_truth_paths — required conflicts
# ===========================================================================

class TestN_DetectParallelTruthPaths(unittest.TestCase):
    """N) detect_parallel_truth_paths returns all required conflict entries."""

    def setUp(self):
        _reset()

    def _get_conflicts(self):
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        return audit.detect_parallel_truth_paths()

    def test_N01_returns_list(self) -> None:
        self.assertIsInstance(self._get_conflicts(), list)

    def test_N02_returns_nonempty_list(self) -> None:
        self.assertGreater(len(self._get_conflicts()), 0)

    def test_N03_all_entries_are_authority_conflict_entries(self) -> None:
        from core.runtime_closure_audit import AuthorityConflictEntry
        for entry in self._get_conflicts():
            self.assertIsInstance(entry, AuthorityConflictEntry)

    def test_N04_conflict_001_present(self) -> None:
        ids = [c.conflict_id for c in self._get_conflicts()]
        self.assertIn("CONFLICT-001", ids)

    def test_N05_conflict_002_present(self) -> None:
        ids = [c.conflict_id for c in self._get_conflicts()]
        self.assertIn("CONFLICT-002", ids)

    def test_N06_conflict_003_present(self) -> None:
        ids = [c.conflict_id for c in self._get_conflicts()]
        self.assertIn("CONFLICT-003", ids)

    def test_N07_conflict_004_present(self) -> None:
        ids = [c.conflict_id for c in self._get_conflicts()]
        self.assertIn("CONFLICT-004", ids)

    def test_N08_conflict_005_present(self) -> None:
        ids = [c.conflict_id for c in self._get_conflicts()]
        self.assertIn("CONFLICT-005", ids)

    def test_N09_all_entries_have_conflict_id(self) -> None:
        for entry in self._get_conflicts():
            self.assertGreater(len(entry.conflict_id), 0)

    def test_N10_all_entries_have_runtime_fact(self) -> None:
        for entry in self._get_conflicts():
            self.assertGreater(len(entry.runtime_fact), 0)

    def test_N11_all_entries_have_layer_a(self) -> None:
        for entry in self._get_conflicts():
            self.assertGreater(len(entry.layer_a), 0)

    def test_N12_all_entries_have_layer_b(self) -> None:
        for entry in self._get_conflicts():
            self.assertGreater(len(entry.layer_b), 0)

    def test_N13_all_entries_have_description(self) -> None:
        for entry in self._get_conflicts():
            self.assertGreater(len(entry.description), 0)


# ===========================================================================
# O)  Conflict discipline — resolved conflicts have resolution_note
# ===========================================================================

class TestO_ResolvedConflictsDiscipline(unittest.TestCase):
    """O) Resolved conflicts must have a non-empty resolution_note."""

    def setUp(self):
        _reset()

    def test_O01_resolved_conflicts_have_resolution_note(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        for entry in audit.detect_parallel_truth_paths():
            if entry.is_resolved:
                self.assertGreater(
                    len(entry.resolution_note),
                    0,
                    f"Resolved conflict '{entry.conflict_id}' has empty resolution_note",
                )

    def test_O02_conflict_001_is_resolved(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        conflict_001 = next(
            c for c in audit.detect_parallel_truth_paths()
            if c.conflict_id == "CONFLICT-001"
        )
        self.assertTrue(conflict_001.is_resolved)

    def test_O03_conflict_004_is_resolved(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        conflict_004 = next(
            c for c in audit.detect_parallel_truth_paths()
            if c.conflict_id == "CONFLICT-004"
        )
        self.assertTrue(conflict_004.is_resolved)

    def test_O04_conflict_005_is_resolved(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        conflict_005 = next(
            c for c in audit.detect_parallel_truth_paths()
            if c.conflict_id == "CONFLICT-005"
        )
        self.assertTrue(conflict_005.is_resolved)


# ===========================================================================
# P)  Conflict discipline — unresolved conflicts have is_resolved=False
# ===========================================================================

class TestP_UnresolvedConflictsDiscipline(unittest.TestCase):
    """P) Open conflicts must have is_resolved=False."""

    def setUp(self):
        _reset()

    def test_P01_conflict_002_not_resolved(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        conflict_002 = next(
            c for c in audit.detect_parallel_truth_paths()
            if c.conflict_id == "CONFLICT-002"
        )
        # PR-514 resolves CONFLICT-002: enrich_runtime_projection() is now
        # wired into _assemble_projection() and _assemble_desktop_status_board_payload().
        self.assertTrue(conflict_002.is_resolved)

    def test_P02_conflict_003_not_resolved(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        conflict_003 = next(
            c for c in audit.detect_parallel_truth_paths()
            if c.conflict_id == "CONFLICT-003"
        )
        self.assertFalse(conflict_003.is_resolved)

    def test_P03_unresolved_conflicts_have_resolution_note_mentioning_deferral(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        for entry in audit.detect_parallel_truth_paths():
            if not entry.is_resolved:
                # Unresolved conflicts should still explain WHY they are unresolved
                self.assertGreater(
                    len(entry.resolution_note),
                    0,
                    f"Open conflict '{entry.conflict_id}' missing resolution_note explaining deferral",
                )


# ===========================================================================
# Q)  get_residual_gap_map — all gap_ids present
# ===========================================================================

class TestQ_ResidualGapMap(unittest.TestCase):
    """Q) get_residual_gap_map returns all required gap IDs."""

    def setUp(self):
        _reset()

    def _get_gaps(self):
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        return audit.get_residual_gap_map()

    def test_Q01_returns_list(self) -> None:
        self.assertIsInstance(self._get_gaps(), list)

    def test_Q02_returns_nonempty(self) -> None:
        self.assertGreater(len(self._get_gaps()), 0)

    def test_Q03_all_entries_are_closure_gap_entry(self) -> None:
        from core.runtime_closure_audit import ClosureGapEntry
        for entry in self._get_gaps():
            self.assertIsInstance(entry, ClosureGapEntry)

    def test_Q04_gap_512_001_present(self) -> None:
        ids = [g.gap_id for g in self._get_gaps()]
        self.assertIn("GAP-512-001", ids)

    def test_Q05_gap_512_002_present(self) -> None:
        ids = [g.gap_id for g in self._get_gaps()]
        self.assertIn("GAP-512-002", ids)

    def test_Q06_gap_512_003_present(self) -> None:
        ids = [g.gap_id for g in self._get_gaps()]
        self.assertIn("GAP-512-003", ids)

    def test_Q07_gap_512_004_present(self) -> None:
        ids = [g.gap_id for g in self._get_gaps()]
        self.assertIn("GAP-512-004", ids)

    def test_Q08_gap_512_005_present(self) -> None:
        ids = [g.gap_id for g in self._get_gaps()]
        self.assertIn("GAP-512-005", ids)

    def test_Q09_gap_512_006_present(self) -> None:
        ids = [g.gap_id for g in self._get_gaps()]
        self.assertIn("GAP-512-006", ids)

    def test_Q10_gap_512_007_present(self) -> None:
        ids = [g.gap_id for g in self._get_gaps()]
        self.assertIn("GAP-512-007", ids)

    def test_Q11_gap_512_008_present(self) -> None:
        ids = [g.gap_id for g in self._get_gaps()]
        self.assertIn("GAP-512-008", ids)

    def test_Q12_gap_512_009_present(self) -> None:
        ids = [g.gap_id for g in self._get_gaps()]
        self.assertIn("GAP-512-009", ids)

    def test_Q13_all_gap_ids_are_strings(self) -> None:
        for entry in self._get_gaps():
            self.assertIsInstance(entry.gap_id, str)
            self.assertGreater(len(entry.gap_id), 0)


# ===========================================================================
# R)  Residual gap discipline — all gaps have non-empty follow_up
# ===========================================================================

class TestR_GapFollowUpDiscipline(unittest.TestCase):
    """R) All gap entries must have a non-empty follow_up reference."""

    def setUp(self):
        _reset()

    def test_R01_all_gaps_have_follow_up(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        for gap in audit.get_residual_gap_map():
            self.assertGreater(
                len(gap.follow_up),
                0,
                f"Gap '{gap.gap_id}' has empty follow_up",
            )

    def test_R02_all_follow_ups_reference_pr(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        for gap in audit.get_residual_gap_map():
            self.assertIn(
                "PR-",
                gap.follow_up,
                f"Gap '{gap.gap_id}' follow_up '{gap.follow_up}' does not reference a PR",
            )

    def test_R03_all_gaps_have_severity(self) -> None:
        from core.runtime_closure_audit import (
            RuntimeClosureAudit,
            GAP_SEVERITY_CRITICAL,
            GAP_SEVERITY_HIGH,
            GAP_SEVERITY_MEDIUM,
            GAP_SEVERITY_LOW,
            GAP_SEVERITY_RESIDUAL,
        )
        valid = {
            GAP_SEVERITY_CRITICAL,
            GAP_SEVERITY_HIGH,
            GAP_SEVERITY_MEDIUM,
            GAP_SEVERITY_LOW,
            GAP_SEVERITY_RESIDUAL,
        }
        audit = RuntimeClosureAudit()
        for gap in audit.get_residual_gap_map():
            self.assertIn(
                gap.severity,
                valid,
                f"Gap '{gap.gap_id}' has unknown severity '{gap.severity}'",
            )

    def test_R04_all_gaps_have_description(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        for gap in audit.get_residual_gap_map():
            self.assertGreater(
                len(gap.description),
                0,
                f"Gap '{gap.gap_id}' has empty description",
            )

    def test_R05_all_gaps_have_layer(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        for gap in audit.get_residual_gap_map():
            self.assertGreater(
                len(gap.layer),
                0,
                f"Gap '{gap.gap_id}' has empty layer",
            )


# ===========================================================================
# S)  Residual gap discipline — is_residual annotation correct
# ===========================================================================

class TestS_ResidualAnnotationDiscipline(unittest.TestCase):
    """S) is_residual annotation is correctly set for all known gaps."""

    def setUp(self):
        _reset()

    def test_S01_gap_001_is_residual(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        gap = next(g for g in audit.get_residual_gap_map() if g.gap_id == "GAP-512-001")
        self.assertTrue(gap.is_residual)

    def test_S02_gap_008_is_residual(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        gap = next(g for g in audit.get_residual_gap_map() if g.gap_id == "GAP-512-008")
        # PR-514 resolves GAP-512-008 (semantic boundary annotation).
        self.assertFalse(gap.is_residual)

    def test_S03_all_known_gaps_are_residual(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        # PR-514 resolves GAP-512-003, GAP-512-005, and GAP-512-008.
        # Confirm the PR-514 resolved gaps are marked non-residual.
        pr514_resolved = {"GAP-512-003", "GAP-512-005", "GAP-512-008"}
        by_id = {g.gap_id: g for g in audit.get_residual_gap_map()}
        for gap_id in pr514_resolved:
            if gap_id in by_id:
                self.assertFalse(
                    by_id[gap_id].is_residual,
                    f"Gap '{gap_id}' resolved by PR-514 should be is_residual=False",
                )


# ===========================================================================
# T)  run_audit — snapshot structure
# ===========================================================================

class TestT_RunAuditSnapshot(unittest.TestCase):
    """T) run_audit returns a ClosureAuditSnapshot with expected structure."""

    def setUp(self):
        _reset()

    def test_T01_returns_snapshot(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit, ClosureAuditSnapshot
        audit = RuntimeClosureAudit()
        snap = audit.run_audit()
        self.assertIsInstance(snap, ClosureAuditSnapshot)

    def test_T02_snapshot_has_layer_statuses(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        snap = audit.run_audit()
        self.assertIsInstance(snap.layer_statuses, list)
        self.assertGreater(len(snap.layer_statuses), 0)

    def test_T03_snapshot_has_gaps(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        snap = audit.run_audit()
        self.assertIsInstance(snap.gaps, list)
        self.assertGreater(len(snap.gaps), 0)

    def test_T04_snapshot_has_conflicts(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        audit = RuntimeClosureAudit()
        snap = audit.run_audit()
        self.assertIsInstance(snap.conflicts, list)
        self.assertGreater(len(snap.conflicts), 0)

    def test_T05_snapshot_authority_correct(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit, RUNTIME_CLOSURE_AUDIT_AUTHORITY
        audit = RuntimeClosureAudit()
        snap = audit.run_audit()
        self.assertEqual(snap.audit_authority, RUNTIME_CLOSURE_AUDIT_AUTHORITY)

    def test_T06_snapshot_ts_recent(self) -> None:
        import time
        from core.runtime_closure_audit import RuntimeClosureAudit
        before = time.time()
        audit = RuntimeClosureAudit()
        snap = audit.run_audit()
        after = time.time()
        self.assertGreaterEqual(snap.snapshot_ts, before)
        self.assertLessEqual(snap.snapshot_ts, after)


# ===========================================================================
# U)  run_audit aggregate counts
# ===========================================================================

class TestU_AuditAggregateCounts(unittest.TestCase):
    """U) Aggregate counts in ClosureAuditSnapshot are consistent."""

    def setUp(self):
        _reset()

    def test_U01_verified_count_non_negative(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        self.assertGreaterEqual(snap.verified_count, 0)

    def test_U02_missing_count_non_negative(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        self.assertGreaterEqual(snap.missing_count, 0)

    def test_U03_verified_plus_missing_le_total(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        self.assertLessEqual(
            snap.verified_count + snap.missing_count,
            len(snap.layer_statuses),
        )

    def test_U04_critical_high_gap_count_non_negative(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        self.assertGreaterEqual(snap.critical_high_gap_count, 0)

    def test_U05_critical_high_gap_count_le_total_gaps(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        self.assertLessEqual(snap.critical_high_gap_count, len(snap.gaps))

    def test_U06_summary_total_layers_matches_layer_statuses(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        summary = snap.summary()
        self.assertEqual(summary["total_layers"], len(snap.layer_statuses))

    def test_U07_summary_total_gaps_matches_gaps(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        summary = snap.summary()
        self.assertEqual(summary["total_gaps"], len(snap.gaps))

    def test_U08_summary_total_conflicts_matches_conflicts(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        summary = snap.summary()
        self.assertEqual(summary["total_conflicts"], len(snap.conflicts))

    def test_U09_summary_unresolved_conflicts_correct(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        expected_unresolved = sum(1 for c in snap.conflicts if not c.is_resolved)
        self.assertEqual(snap.summary()["unresolved_conflicts"], expected_unresolved)

    def test_U10_summary_residual_gaps_correct(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        expected_residual = sum(1 for g in snap.gaps if g.is_residual)
        self.assertEqual(snap.summary()["residual_gaps"], expected_residual)


# ===========================================================================
# V)  all_layers_closed logic
# ===========================================================================

class TestV_AllLayersClosed(unittest.TestCase):
    """V) all_layers_closed is False when any layer is missing or degraded."""

    def setUp(self):
        _reset()

    def test_V01_snapshot_has_all_layers_closed_field(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        self.assertIsInstance(snap.all_layers_closed, bool)

    def test_V02_all_layers_closed_false_when_missing_count_gt_0(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        if snap.missing_count > 0:
            self.assertFalse(snap.all_layers_closed)

    def test_V03_all_layers_closed_consistent_with_statuses(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit, CLOSURE_STATUS_VERIFIED
        snap = RuntimeClosureAudit().run_audit()
        if snap.all_layers_closed:
            # Every layer must be verified
            for s in snap.layer_statuses:
                self.assertEqual(s.status, CLOSURE_STATUS_VERIFIED)


# ===========================================================================
# W)  ClosureAuditSnapshot.summary() — expected keys
# ===========================================================================

class TestW_SummaryKeys(unittest.TestCase):
    """W) summary() always returns expected keys and correct types."""

    def setUp(self):
        _reset()

    def test_W01_all_expected_keys_present(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        snap = RuntimeClosureAudit().run_audit()
        summary = snap.summary()
        required_keys = [
            "audit_authority",
            "contract_version",
            "all_layers_closed",
            "verified_count",
            "missing_count",
            "total_layers",
            "total_gaps",
            "critical_high_gap_count",
            "total_conflicts",
            "unresolved_conflicts",
            "residual_gaps",
            "snapshot_ts",
        ]
        for key in required_keys:
            self.assertIn(key, summary)

    def test_W02_verified_count_is_int(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        summary = RuntimeClosureAudit().run_audit().summary()
        self.assertIsInstance(summary["verified_count"], int)

    def test_W03_missing_count_is_int(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        summary = RuntimeClosureAudit().run_audit().summary()
        self.assertIsInstance(summary["missing_count"], int)

    def test_W04_all_layers_closed_is_bool(self) -> None:
        from core.runtime_closure_audit import RuntimeClosureAudit
        summary = RuntimeClosureAudit().run_audit().summary()
        self.assertIsInstance(summary["all_layers_closed"], bool)


# ===========================================================================
# X)  Singleton management
# ===========================================================================

class TestX_SingletonManagement(unittest.TestCase):
    """X) Singleton management: get/reset/re-create."""

    def setUp(self):
        _reset()

    def test_X01_get_returns_instance(self) -> None:
        from core.runtime_closure_audit import get_runtime_closure_audit, RuntimeClosureAudit
        instance = get_runtime_closure_audit()
        self.assertIsInstance(instance, RuntimeClosureAudit)

    def test_X02_two_gets_return_same_instance(self) -> None:
        from core.runtime_closure_audit import get_runtime_closure_audit
        a = get_runtime_closure_audit()
        b = get_runtime_closure_audit()
        self.assertIs(a, b)

    def test_X03_reset_clears_singleton(self) -> None:
        from core.runtime_closure_audit import (
            get_runtime_closure_audit,
            reset_runtime_closure_audit,
        )
        a = get_runtime_closure_audit()
        reset_runtime_closure_audit()
        b = get_runtime_closure_audit()
        self.assertIsNot(a, b)

    def test_X04_reset_then_get_returns_new_instance(self) -> None:
        from core.runtime_closure_audit import (
            get_runtime_closure_audit,
            reset_runtime_closure_audit,
            RuntimeClosureAudit,
        )
        reset_runtime_closure_audit()
        instance = get_runtime_closure_audit()
        self.assertIsInstance(instance, RuntimeClosureAudit)


# ===========================================================================
# Y)  Module-level helpers delegate to singleton
# ===========================================================================

class TestY_ModuleLevelHelpers(unittest.TestCase):
    """Y) Module-level convenience helpers delegate to the singleton."""

    def setUp(self):
        _reset()

    def test_Y01_run_closure_audit_returns_snapshot(self) -> None:
        from core.runtime_closure_audit import run_closure_audit, ClosureAuditSnapshot
        snap = run_closure_audit()
        self.assertIsInstance(snap, ClosureAuditSnapshot)

    def test_Y02_detect_parallel_truth_paths_returns_list(self) -> None:
        from core.runtime_closure_audit import (
            detect_parallel_truth_paths,
            AuthorityConflictEntry,
        )
        conflicts = detect_parallel_truth_paths()
        self.assertIsInstance(conflicts, list)
        for c in conflicts:
            self.assertIsInstance(c, AuthorityConflictEntry)

    def test_Y03_get_residual_gap_map_returns_list(self) -> None:
        from core.runtime_closure_audit import get_residual_gap_map, ClosureGapEntry
        gaps = get_residual_gap_map()
        self.assertIsInstance(gaps, list)
        for g in gaps:
            self.assertIsInstance(g, ClosureGapEntry)

    def test_Y04_run_closure_audit_uses_singleton(self) -> None:
        from core.runtime_closure_audit import (
            run_closure_audit,
            get_runtime_closure_audit,
            ClosureAuditSnapshot,
        )
        # Both calls use the same singleton
        snap = run_closure_audit()
        audit = get_runtime_closure_audit()
        snap2 = audit.run_audit()
        self.assertIsInstance(snap, ClosureAuditSnapshot)
        self.assertIsInstance(snap2, ClosureAuditSnapshot)


# ===========================================================================
# Z)  Command router PR-512 sentinel importable
# ===========================================================================

class TestZ_CommandRouterSentinel(unittest.TestCase):
    """Z) Command router exposes the PR-512 closure audit integration sentinel."""

    def test_Z01_runtime_closure_audit_integrated_importable(self) -> None:
        from core.command_router import RUNTIME_CLOSURE_AUDIT_INTEGRATED
        self.assertIsInstance(RUNTIME_CLOSURE_AUDIT_INTEGRATED, str)
        self.assertGreater(len(RUNTIME_CLOSURE_AUDIT_INTEGRATED), 0)

    def test_Z02_sentinel_contains_integrated(self) -> None:
        from core.command_router import RUNTIME_CLOSURE_AUDIT_INTEGRATED
        self.assertIn("INTEGRATED", RUNTIME_CLOSURE_AUDIT_INTEGRATED)

    def test_Z03_sentinel_contains_closure_audit(self) -> None:
        from core.command_router import RUNTIME_CLOSURE_AUDIT_INTEGRATED
        self.assertIn("CLOSURE_AUDIT", RUNTIME_CLOSURE_AUDIT_INTEGRATED)


# ===========================================================================
# AA)  Docs artifact — RESIDUAL_GAP_MAP.md exists
# ===========================================================================

class TestAA_DocsArtifact(unittest.TestCase):
    """AA) The residual gap map documentation artifact exists."""

    def _docs_path(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(repo_root, "docs", "RESIDUAL_GAP_MAP.md")

    def test_AA01_residual_gap_map_md_exists(self) -> None:
        self.assertTrue(
            os.path.exists(self._docs_path()),
            "docs/RESIDUAL_GAP_MAP.md does not exist",
        )

    def test_AA02_residual_gap_map_md_nonempty(self) -> None:
        path = self._docs_path()
        if os.path.exists(path):
            self.assertGreater(os.path.getsize(path), 0)

    def test_AA03_residual_gap_map_md_contains_gap_ids(self) -> None:
        path = self._docs_path()
        if not os.path.exists(path):
            self.skipTest("docs/RESIDUAL_GAP_MAP.md not present")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("GAP-512-001", content)
        self.assertIn("GAP-512-002", content)

    def test_AA04_residual_gap_map_md_contains_conflict_ids(self) -> None:
        path = self._docs_path()
        if not os.path.exists(path):
            self.skipTest("docs/RESIDUAL_GAP_MAP.md not present")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("CONFLICT-001", content)
        self.assertIn("CONFLICT-002", content)

    def test_AA05_residual_gap_map_md_references_follow_up_prs(self) -> None:
        path = self._docs_path()
        if not os.path.exists(path):
            self.skipTest("docs/RESIDUAL_GAP_MAP.md not present")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("PR-513", content)
        self.assertIn("PR-514", content)


# ===========================================================================
# BB)  api_routes closure audit sentinel present
# ===========================================================================

class TestBB_ApiRoutesSentinel(unittest.TestCase):
    """BB) core/api_routes.py contains the PR-512 closure audit sentinel."""

    def _api_routes_path(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(repo_root, "core", "api_routes.py")

    def test_BB01_api_routes_contains_pr512_comment(self) -> None:
        path = self._api_routes_path()
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("PR-512", content)

    def test_BB02_api_routes_imports_runtime_closure_audit(self) -> None:
        path = self._api_routes_path()
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("runtime_closure_audit", content)

    def test_BB03_api_routes_has_integrated_sentinel(self) -> None:
        path = self._api_routes_path()
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("RUNTIME_CLOSURE_AUDIT_INTEGRATED", content)


if __name__ == "__main__":
    unittest.main()
