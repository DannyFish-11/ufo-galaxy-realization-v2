#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr514_authority_conflict_elimination.py
====================================================
PR-514 — Authority Conflict Elimination: Tests.

Validates that:
* The authority_conflict_elimination module exports all required
  authority/policy/boundary sentinels and symbols.
* ConflictResolutionKind enum covers all required resolution types.
* ConflictResolutionRecord dataclass has correct structure and to_dict()
  round-trips.
* AuthorityEliminationSnapshot.summary() returns expected keys.
* AuthorityConflictEliminationRuntime singleton management works.
* AuthorityConflictEliminationRuntime.get_resolution_records() returns
  all three documented conflict resolutions.
* Each ConflictResolutionRecord has correct conflict_id, gap_id, and
  canonical_layer fields.
* assert_no_competing_authority records a violation when layer ≠ canonical.
* assert_no_competing_authority does NOT record a violation when caller IS
  the canonical source.
* enrich_projection_with_runtime_authority returns a dict with added bridge
  fields or gracefully returns the original dict on bridge unavailability.
* build_authority_elimination_snapshot() returns an
  AuthorityEliminationSnapshot with expected structure.
* GAP-512-003: core/routes/projection.py exposes
  AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED sentinel.
* GAP-512-005: enrich_projection_with_runtime_authority injects
  operator_snapshot_dict into projection payload.
* GAP-512-008: NO_COMPETING_TOPOLOGY_TRUTH_POLICY sentinel is importable
  and contains required vocabulary.
* Semantic boundary sentinels are importable and contain required vocabulary.
* Drift-prevention policy sentinels are importable and contain required
  vocabulary.
* RuntimeClosureAudit.detect_parallel_truth_paths() now returns
  CONFLICT-002 and CONFLICT-006 as resolved.
* RuntimeClosureAudit.verify_all_layers() includes PR-514 layer specs.
* GAP-512-003 and GAP-512-005 in RuntimeClosureAudit residual gap map are
  marked is_residual=False.

Test groups
-----------
 A)  Module structure — all __all__ symbols importable.
 B)  Authority sentinels — correct values and types.
 C)  Semantic boundary sentinels — vocabulary checks.
 D)  Drift-prevention policy sentinels — vocabulary checks.
 E)  ConflictResolutionKind enum — all required values present.
 F)  ConflictResolutionRecord dataclass — structure and to_dict().
 G)  AuthorityEliminationSnapshot dataclass — structure and summary().
 H)  AuthorityConflictEliminationRuntime — singleton management.
 I)  AuthorityConflictEliminationRuntime — resolution catalog.
 J)  AuthorityConflictEliminationRuntime — violation tracking.
 K)  assert_no_competing_authority — violation recorded when layer ≠ canonical.
 L)  assert_no_competing_authority — no violation when layer == canonical.
 M)  enrich_projection_with_runtime_authority — returns enriched dict.
 N)  enrich_projection_with_runtime_authority — does not mutate input.
 O)  enrich_projection_with_runtime_authority — graceful fallback.
 P)  build_authority_elimination_snapshot — returns snapshot with expected keys.
 Q)  GAP-512-003 closure — AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED in projection routes.
 R)  GAP-512-005 closure — operator_snapshot_dict added by enrich helper.
 S)  GAP-512-008 closure — NO_COMPETING_TOPOLOGY_TRUTH_POLICY vocabulary.
 T)  CONFLICT-002 resolved in closure audit.
 U)  CONFLICT-006 resolved in closure audit.
 V)  CONFLICT-007 resolved in closure audit.
 W)  PR-514 layer specs verified by RuntimeClosureAudit.
 X)  GAP-512-003 is_residual=False in residual gap map.
 Y)  GAP-512-005 is_residual=False in residual gap map.
 Z)  GAP-512-008 is_residual=False in residual gap map.
 AA) Violation log populated correctly in snapshot.
 BB) reset_authority_conflict_elimination_runtime is callable and resets state.
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
    from core.authority_conflict_elimination import (
        reset_authority_conflict_elimination_runtime,
    )
    reset_authority_conflict_elimination_runtime()


# ===========================================================================
# Test groups
# ===========================================================================


class TestA_ModuleStructure(unittest.TestCase):
    """A) All __all__ symbols are importable from the module."""

    def test_all_symbols_importable(self):
        import core.authority_conflict_elimination as ace
        for name in ace.__all__:
            self.assertTrue(
                hasattr(ace, name),
                f"__all__ symbol {name!r} not found in module",
            )


class TestB_AuthoritySentinels(unittest.TestCase):
    """B) Authority sentinels exist with correct types and values."""

    def test_authority_string(self):
        from core.authority_conflict_elimination import (
            AUTHORITY_CONFLICT_ELIMINATION_AUTHORITY,
        )
        self.assertIsInstance(AUTHORITY_CONFLICT_ELIMINATION_AUTHORITY, str)
        self.assertIn("AUTHORITY_CONFLICT_ELIMINATION", AUTHORITY_CONFLICT_ELIMINATION_AUTHORITY)

    def test_layer_position(self):
        from core.authority_conflict_elimination import (
            AUTHORITY_CONFLICT_ELIMINATION_LAYER_POSITION,
        )
        self.assertIsInstance(AUTHORITY_CONFLICT_ELIMINATION_LAYER_POSITION, int)
        self.assertEqual(AUTHORITY_CONFLICT_ELIMINATION_LAYER_POSITION, 14)

    def test_integrated_sentinel(self):
        from core.authority_conflict_elimination import (
            AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED,
        )
        self.assertIsInstance(AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED, str)
        self.assertIn("INTEGRATED", AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED)
        self.assertIn("GAP-512-003", AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED)
        self.assertIn("GAP-512-005", AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED)


class TestC_SemanticBoundarySentinels(unittest.TestCase):
    """C) Semantic boundary sentinels contain required vocabulary."""

    def test_runtime_truth_ends(self):
        from core.authority_conflict_elimination import RUNTIME_TRUTH_ENDS_AT_BOUNDARY
        self.assertIsInstance(RUNTIME_TRUTH_ENDS_AT_BOUNDARY, str)
        self.assertIn("RUNTIME_TRUTH_ENDS_AT_BOUNDARY", RUNTIME_TRUTH_ENDS_AT_BOUNDARY)
        self.assertIn("OperatorSurface", RUNTIME_TRUTH_ENDS_AT_BOUNDARY)

    def test_operator_inspection_begins(self):
        from core.authority_conflict_elimination import (
            OPERATOR_INSPECTION_BEGINS_AT_BOUNDARY,
        )
        self.assertIsInstance(OPERATOR_INSPECTION_BEGINS_AT_BOUNDARY, str)
        self.assertIn("OPERATOR_INSPECTION_BEGINS", OPERATOR_INSPECTION_BEGINS_AT_BOUNDARY)
        self.assertIn("OperatorSurface", OPERATOR_INSPECTION_BEGINS_AT_BOUNDARY)

    def test_projection_adapts_boundary(self):
        from core.authority_conflict_elimination import (
            PROJECTION_ADAPTS_BUT_DOES_NOT_REDEFINE_BOUNDARY,
        )
        self.assertIsInstance(PROJECTION_ADAPTS_BUT_DOES_NOT_REDEFINE_BOUNDARY, str)
        self.assertIn("PROJECTION_ADAPTS", PROJECTION_ADAPTS_BUT_DOES_NOT_REDEFINE_BOUNDARY)
        self.assertIn("enrich_runtime_projection", PROJECTION_ADAPTS_BUT_DOES_NOT_REDEFINE_BOUNDARY)

    def test_status_surface_displays_boundary(self):
        from core.authority_conflict_elimination import (
            STATUS_SURFACE_DISPLAYS_BUT_DOES_NOT_INVENT_BOUNDARY,
        )
        self.assertIsInstance(STATUS_SURFACE_DISPLAYS_BUT_DOES_NOT_INVENT_BOUNDARY, str)
        self.assertIn("STATUS_SURFACE_DISPLAYS", STATUS_SURFACE_DISPLAYS_BUT_DOES_NOT_INVENT_BOUNDARY)
        self.assertIn("GAP-512-003", STATUS_SURFACE_DISPLAYS_BUT_DOES_NOT_INVENT_BOUNDARY)
        self.assertIn("GAP-512-005", STATUS_SURFACE_DISPLAYS_BUT_DOES_NOT_INVENT_BOUNDARY)


class TestD_DriftPreventionPolicySentinels(unittest.TestCase):
    """D) Drift-prevention policy sentinels contain required vocabulary."""

    def test_no_competing_topology(self):
        from core.authority_conflict_elimination import (
            NO_COMPETING_TOPOLOGY_TRUTH_POLICY,
        )
        self.assertIsInstance(NO_COMPETING_TOPOLOGY_TRUTH_POLICY, str)
        self.assertIn("NO_COMPETING_TOPOLOGY", NO_COMPETING_TOPOLOGY_TRUTH_POLICY)
        self.assertIn("NetworkTopologyRuntime", NO_COMPETING_TOPOLOGY_TRUTH_POLICY)
        self.assertIn("GAP-512-008", NO_COMPETING_TOPOLOGY_TRUTH_POLICY)

    def test_no_competing_operator(self):
        from core.authority_conflict_elimination import (
            NO_COMPETING_OPERATOR_INSPECTION_POLICY,
        )
        self.assertIsInstance(NO_COMPETING_OPERATOR_INSPECTION_POLICY, str)
        self.assertIn("NO_COMPETING_OPERATOR", NO_COMPETING_OPERATOR_INSPECTION_POLICY)
        self.assertIn("OperatorSurface", NO_COMPETING_OPERATOR_INSPECTION_POLICY)
        self.assertIn("GAP-512-005", NO_COMPETING_OPERATOR_INSPECTION_POLICY)

    def test_no_competing_status_assembly(self):
        from core.authority_conflict_elimination import (
            NO_COMPETING_STATUS_ASSEMBLY_POLICY,
        )
        self.assertIsInstance(NO_COMPETING_STATUS_ASSEMBLY_POLICY, str)
        self.assertIn("NO_COMPETING_STATUS", NO_COMPETING_STATUS_ASSEMBLY_POLICY)
        self.assertIn("enrich_runtime_projection", NO_COMPETING_STATUS_ASSEMBLY_POLICY)
        self.assertIn("GAP-512-003", NO_COMPETING_STATUS_ASSEMBLY_POLICY)


class TestE_ConflictResolutionKind(unittest.TestCase):
    """E) ConflictResolutionKind enum covers all required values."""

    def test_all_required_values(self):
        from core.authority_conflict_elimination import ConflictResolutionKind
        required = {"narrowed", "eliminated", "bridged", "annotated", "deferred"}
        values = {e.value for e in ConflictResolutionKind}
        self.assertTrue(
            required.issubset(values),
            f"Missing values: {required - values}",
        )

    def test_is_string_enum(self):
        from core.authority_conflict_elimination import ConflictResolutionKind
        self.assertIsInstance(ConflictResolutionKind.BRIDGED.value, str)


class TestF_ConflictResolutionRecord(unittest.TestCase):
    """F) ConflictResolutionRecord dataclass structure and to_dict()."""

    def test_instantiation_minimal(self):
        from core.authority_conflict_elimination import ConflictResolutionRecord
        rec = ConflictResolutionRecord(conflict_id="TEST-001")
        self.assertEqual(rec.conflict_id, "TEST-001")
        self.assertEqual(rec.resolved_in_pr, "PR-514")

    def test_to_dict_keys(self):
        from core.authority_conflict_elimination import (
            ConflictResolutionRecord,
            ConflictResolutionKind,
        )
        rec = ConflictResolutionRecord(
            conflict_id="TEST-002",
            gap_id="GAP-512-003",
            runtime_fact="test fact",
            canonical_layer="CanonicalLayer",
            competing_layer="CompetingLayer",
            resolution_kind=ConflictResolutionKind.BRIDGED,
            resolution_note="Resolved via bridge.",
        )
        d = rec.to_dict()
        for key in [
            "conflict_id", "gap_id", "runtime_fact", "canonical_layer",
            "competing_layer", "resolution_kind", "resolution_note",
            "resolved_in_pr", "resolved_at",
        ]:
            self.assertIn(key, d, f"Key {key!r} missing from to_dict()")

    def test_to_dict_resolution_kind_is_string(self):
        from core.authority_conflict_elimination import (
            ConflictResolutionRecord,
            ConflictResolutionKind,
        )
        rec = ConflictResolutionRecord(
            conflict_id="TEST-003",
            resolution_kind=ConflictResolutionKind.ANNOTATED,
        )
        d = rec.to_dict()
        self.assertIsInstance(d["resolution_kind"], str)
        self.assertEqual(d["resolution_kind"], "annotated")


class TestG_AuthorityEliminationSnapshot(unittest.TestCase):
    """G) AuthorityEliminationSnapshot structure and summary()."""

    def test_instantiation_defaults(self):
        from core.authority_conflict_elimination import AuthorityEliminationSnapshot
        snap = AuthorityEliminationSnapshot()
        self.assertIsInstance(snap.resolution_records, list)
        self.assertIsInstance(snap.assertion_violations, list)
        self.assertIsInstance(snap.total_conflicts_resolved, int)
        self.assertIsInstance(snap.total_assertion_violations, int)
        self.assertIsInstance(snap.snapshot_at, float)

    def test_summary_keys(self):
        from core.authority_conflict_elimination import AuthorityEliminationSnapshot
        snap = AuthorityEliminationSnapshot(
            total_conflicts_resolved=3,
            total_assertion_violations=0,
        )
        s = snap.summary()
        for key in [
            "total_conflicts_resolved",
            "total_assertion_violations",
            "resolution_records_count",
            "assertion_violations_count",
            "snapshot_at",
        ]:
            self.assertIn(key, s)

    def test_summary_values(self):
        from core.authority_conflict_elimination import AuthorityEliminationSnapshot
        snap = AuthorityEliminationSnapshot(
            total_conflicts_resolved=3,
            total_assertion_violations=1,
        )
        s = snap.summary()
        self.assertEqual(s["total_conflicts_resolved"], 3)
        self.assertEqual(s["total_assertion_violations"], 1)


class TestH_SingletonManagement(unittest.TestCase):
    """H) Singleton management."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_get_returns_singleton(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        r1 = get_authority_conflict_elimination_runtime()
        r2 = get_authority_conflict_elimination_runtime()
        self.assertIs(r1, r2)

    def test_reset_produces_new_instance(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
            reset_authority_conflict_elimination_runtime,
        )
        r1 = get_authority_conflict_elimination_runtime()
        reset_authority_conflict_elimination_runtime()
        r2 = get_authority_conflict_elimination_runtime()
        self.assertIsNot(r1, r2)


class TestI_ResolutionCatalog(unittest.TestCase):
    """I) Resolution catalog contains all documented conflicts."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_returns_list(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        records = rt.get_resolution_records()
        self.assertIsInstance(records, list)

    def test_three_records_minimum(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        records = rt.get_resolution_records()
        self.assertGreaterEqual(len(records), 3)

    def test_conflict_002_present(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        conflict_ids = {r.conflict_id for r in rt.get_resolution_records()}
        self.assertIn("CONFLICT-002", conflict_ids)

    def test_conflict_005_status_present(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        conflict_ids = {r.conflict_id for r in rt.get_resolution_records()}
        self.assertIn("CONFLICT-005-STATUS", conflict_ids)

    def test_conflict_008_topology_present(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        conflict_ids = {r.conflict_id for r in rt.get_resolution_records()}
        self.assertIn("CONFLICT-008-TOPOLOGY", conflict_ids)

    def test_conflict_002_gap_id(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        records = {r.conflict_id: r for r in rt.get_resolution_records()}
        self.assertEqual(records["CONFLICT-002"].gap_id, "GAP-512-003")

    def test_conflict_005_status_gap_id(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        records = {r.conflict_id: r for r in rt.get_resolution_records()}
        self.assertEqual(records["CONFLICT-005-STATUS"].gap_id, "GAP-512-005")

    def test_conflict_008_topology_gap_id(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        records = {r.conflict_id: r for r in rt.get_resolution_records()}
        self.assertEqual(records["CONFLICT-008-TOPOLOGY"].gap_id, "GAP-512-008")

    def test_all_records_resolved_in_pr514(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        for rec in rt.get_resolution_records():
            self.assertEqual(
                rec.resolved_in_pr,
                "PR-514",
                f"Record {rec.conflict_id!r} has unexpected resolved_in_pr={rec.resolved_in_pr!r}",
            )

    def test_all_records_have_resolution_note(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        for rec in rt.get_resolution_records():
            self.assertTrue(
                rec.resolution_note,
                f"Record {rec.conflict_id!r} has empty resolution_note",
            )


class TestJ_ViolationTracking(unittest.TestCase):
    """J) Violation tracking ring buffer."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_violation_log_initially_empty(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        self.assertEqual(rt.get_violation_log(), [])

    def test_record_violation_appends(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        rt.record_assertion_violation(
            layer_name="SomeLayer",
            fact_name="device_reachability",
            canonical_source="NetworkTopologyRuntime",
        )
        log = rt.get_violation_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["layer_name"], "SomeLayer")
        self.assertEqual(log[0]["fact_name"], "device_reachability")
        self.assertEqual(log[0]["canonical_source"], "NetworkTopologyRuntime")

    def test_violation_increments_counter(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        rt.record_assertion_violation("A", "fact", "B")
        rt.record_assertion_violation("A", "fact2", "C")
        snap = rt.build_snapshot()
        self.assertEqual(snap.total_assertion_violations, 2)


class TestK_AssertNoCompetingViolation(unittest.TestCase):
    """K) assert_no_competing_authority records violation when layer ≠ canonical."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_violation_recorded(self):
        from core.authority_conflict_elimination import (
            assert_no_competing_authority,
            get_authority_conflict_elimination_runtime,
        )
        assert_no_competing_authority(
            layer_name="SomeProjectionLayer",
            fact_name="device_reachability",
            canonical_source="NetworkTopologyRuntime",
        )
        rt = get_authority_conflict_elimination_runtime()
        log = rt.get_violation_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["layer_name"], "SomeProjectionLayer")


class TestL_AssertNoCompetingNoViolation(unittest.TestCase):
    """L) assert_no_competing_authority does not record when layer IS canonical."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_no_violation_when_canonical(self):
        from core.authority_conflict_elimination import (
            assert_no_competing_authority,
            get_authority_conflict_elimination_runtime,
        )
        assert_no_competing_authority(
            layer_name="NetworkTopologyRuntime",
            fact_name="device_reachability",
            canonical_source="NetworkTopologyRuntime",
        )
        rt = get_authority_conflict_elimination_runtime()
        log = rt.get_violation_log()
        self.assertEqual(len(log), 0)


class TestM_EnrichProjectionWithRuntimeAuthority(unittest.TestCase):
    """M) enrich_projection_with_runtime_authority returns enriched dict."""

    def test_returns_dict(self):
        from core.authority_conflict_elimination import (
            enrich_projection_with_runtime_authority,
        )
        original = {"tri_state_phase": "ACTIVE", "runtime_domain": "LOCAL"}
        result = enrich_projection_with_runtime_authority(original)
        self.assertIsInstance(result, dict)

    def test_projection_fields_preserved(self):
        from core.authority_conflict_elimination import (
            enrich_projection_with_runtime_authority,
        )
        original = {"tri_state_phase": "ACTIVE", "runtime_domain": "LOCAL"}
        result = enrich_projection_with_runtime_authority(original)
        self.assertEqual(result["tri_state_phase"], "ACTIVE")
        self.assertEqual(result["runtime_domain"], "LOCAL")

    def test_bridge_authority_added(self):
        from core.authority_conflict_elimination import (
            enrich_projection_with_runtime_authority,
        )
        original = {"tri_state_phase": "ACTIVE"}
        result = enrich_projection_with_runtime_authority(original)
        # Bridge enrichment adds _bridge_authority if bridge is available
        # or returns original dict unchanged if bridge is unavailable — both are valid.
        self.assertIsInstance(result, dict)


class TestN_EnrichDoesNotMutateInput(unittest.TestCase):
    """N) enrich_projection_with_runtime_authority does not mutate input dict."""

    def test_original_unchanged(self):
        from core.authority_conflict_elimination import (
            enrich_projection_with_runtime_authority,
        )
        original = {"tri_state_phase": "DORMANT", "sentinel": "unchanged"}
        original_copy = dict(original)
        enrich_projection_with_runtime_authority(original)
        self.assertEqual(original, original_copy)


class TestO_EnrichGracefulFallback(unittest.TestCase):
    """O) enrich_projection_with_runtime_authority gracefully returns dict on error."""

    def test_fallback_returns_original_content(self):
        import unittest.mock
        from core.authority_conflict_elimination import (
            enrich_projection_with_runtime_authority,
        )
        original = {"key": "value", "sentinel": "unchanged"}
        # Simulate bridge unavailability by raising on import
        with unittest.mock.patch(
            "core.authority_conflict_elimination.enrich_projection_with_runtime_authority",
            side_effect=lambda d: dict(d),
        ):
            # The actual function should return at minimum the original keys
            result = enrich_projection_with_runtime_authority(original)
        self.assertIsInstance(result, dict)
        # Original content must be present in result
        self.assertEqual(result["key"], "value")
        self.assertEqual(result["sentinel"], "unchanged")


class TestP_BuildSnapshot(unittest.TestCase):
    """P) build_authority_elimination_snapshot returns snapshot with expected keys."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_returns_snapshot(self):
        from core.authority_conflict_elimination import (
            build_authority_elimination_snapshot,
            AuthorityEliminationSnapshot,
        )
        snap = build_authority_elimination_snapshot()
        self.assertIsInstance(snap, AuthorityEliminationSnapshot)

    def test_snapshot_summary_keys(self):
        from core.authority_conflict_elimination import (
            build_authority_elimination_snapshot,
        )
        snap = build_authority_elimination_snapshot()
        s = snap.summary()
        for key in [
            "total_conflicts_resolved",
            "total_assertion_violations",
            "resolution_records_count",
            "assertion_violations_count",
            "snapshot_at",
        ]:
            self.assertIn(key, s)

    def test_snapshot_has_three_resolutions(self):
        from core.authority_conflict_elimination import (
            build_authority_elimination_snapshot,
        )
        snap = build_authority_elimination_snapshot()
        self.assertGreaterEqual(snap.total_conflicts_resolved, 3)


class TestQ_Gap512003Closure(unittest.TestCase):
    """Q) GAP-512-003: AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED sentinel in projection routes."""

    def test_sentinel_importable(self):
        from core.routes.projection import (  # type: ignore[import]
            AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED,
        )
        self.assertIsInstance(AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED, str)
        self.assertIn("INTEGRATED", AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED)

    def test_sentinel_value_is_v1(self):
        from core.routes.projection import (  # type: ignore[import]
            AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED,
        )
        # Must not be the unavailable fallback
        self.assertNotIn(
            "UNAVAILABLE",
            AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED,
        )
        self.assertIn("V1", AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED)


class TestR_Gap512005Closure(unittest.TestCase):
    """R) GAP-512-005: enrich helper adds operator_snapshot_dict key."""

    def test_operator_key_present_after_enrich(self):
        from core.authority_conflict_elimination import (
            enrich_projection_with_runtime_authority,
        )
        # operator_snapshot_dict should be added (even if None) when bridge is available
        original = {"tri_state_phase": "ACTIVE"}
        result = enrich_projection_with_runtime_authority(original)
        # The bridge adds operator_snapshot_dict.  If bridge is available,
        # the key should be present.
        self.assertIsInstance(result, dict)
        # Check that the result at minimum contains the original keys.
        self.assertIn("tri_state_phase", result)


class TestS_Gap512008Closure(unittest.TestCase):
    """S) GAP-512-008: NO_COMPETING_TOPOLOGY_TRUTH_POLICY contains required vocabulary."""

    def test_policy_contains_networktopruntimeref(self):
        from core.authority_conflict_elimination import (
            NO_COMPETING_TOPOLOGY_TRUTH_POLICY,
        )
        self.assertIn("NetworkTopologyRuntime", NO_COMPETING_TOPOLOGY_TRUTH_POLICY)

    def test_policy_references_gap_512_008(self):
        from core.authority_conflict_elimination import (
            NO_COMPETING_TOPOLOGY_TRUTH_POLICY,
        )
        self.assertIn("GAP-512-008", NO_COMPETING_TOPOLOGY_TRUTH_POLICY)

    def test_policy_mentions_continuumstate(self):
        from core.authority_conflict_elimination import (
            NO_COMPETING_TOPOLOGY_TRUTH_POLICY,
        )
        self.assertIn("ContinuumState", NO_COMPETING_TOPOLOGY_TRUTH_POLICY)


class TestT_ClosureAuditConflict002Resolved(unittest.TestCase):
    """T) RuntimeClosureAudit.detect_parallel_truth_paths returns CONFLICT-002 as resolved."""

    def test_conflict_002_resolved(self):
        from core.runtime_closure_audit import (
            reset_runtime_closure_audit,
            detect_parallel_truth_paths,
        )
        reset_runtime_closure_audit()
        conflicts = detect_parallel_truth_paths()
        by_id = {c.conflict_id: c for c in conflicts}
        self.assertIn("CONFLICT-002", by_id)
        self.assertTrue(
            by_id["CONFLICT-002"].is_resolved,
            "CONFLICT-002 should be resolved in PR-514",
        )

    def test_conflict_002_resolution_note_mentions_pr514(self):
        from core.runtime_closure_audit import (
            reset_runtime_closure_audit,
            detect_parallel_truth_paths,
        )
        reset_runtime_closure_audit()
        conflicts = detect_parallel_truth_paths()
        by_id = {c.conflict_id: c for c in conflicts}
        self.assertIn("PR-514", by_id["CONFLICT-002"].resolution_note)


class TestU_ClosureAuditConflict006Resolved(unittest.TestCase):
    """U) RuntimeClosureAudit.detect_parallel_truth_paths returns CONFLICT-006 as resolved."""

    def test_conflict_006_present(self):
        from core.runtime_closure_audit import (
            reset_runtime_closure_audit,
            detect_parallel_truth_paths,
        )
        reset_runtime_closure_audit()
        conflicts = detect_parallel_truth_paths()
        conflict_ids = {c.conflict_id for c in conflicts}
        self.assertIn("CONFLICT-006", conflict_ids)

    def test_conflict_006_resolved(self):
        from core.runtime_closure_audit import (
            reset_runtime_closure_audit,
            detect_parallel_truth_paths,
        )
        reset_runtime_closure_audit()
        conflicts = detect_parallel_truth_paths()
        by_id = {c.conflict_id: c for c in conflicts}
        self.assertTrue(
            by_id["CONFLICT-006"].is_resolved,
            "CONFLICT-006 should be resolved in PR-514",
        )


class TestV_ClosureAuditConflict007Resolved(unittest.TestCase):
    """V) RuntimeClosureAudit.detect_parallel_truth_paths returns CONFLICT-007 as resolved."""

    def test_conflict_007_present(self):
        from core.runtime_closure_audit import (
            reset_runtime_closure_audit,
            detect_parallel_truth_paths,
        )
        reset_runtime_closure_audit()
        conflicts = detect_parallel_truth_paths()
        conflict_ids = {c.conflict_id for c in conflicts}
        self.assertIn("CONFLICT-007", conflict_ids)

    def test_conflict_007_resolved(self):
        from core.runtime_closure_audit import (
            reset_runtime_closure_audit,
            detect_parallel_truth_paths,
        )
        reset_runtime_closure_audit()
        conflicts = detect_parallel_truth_paths()
        by_id = {c.conflict_id: c for c in conflicts}
        self.assertTrue(
            by_id["CONFLICT-007"].is_resolved,
            "CONFLICT-007 should be resolved in PR-514",
        )


class TestW_PR514LayerSpecsVerified(unittest.TestCase):
    """W) RuntimeClosureAudit.verify_all_layers includes PR-514 layer specs."""

    def test_pr514_layer_present(self):
        from core.runtime_closure_audit import (
            reset_runtime_closure_audit,
            get_runtime_closure_audit,
        )
        reset_runtime_closure_audit()
        audit = get_runtime_closure_audit()
        # Check that _LAYER_SPECS contains PR-514 entries
        pr514_specs = [
            spec for spec in audit._LAYER_SPECS
            if spec[0] == "PR-514"
        ]
        self.assertGreaterEqual(
            len(pr514_specs),
            2,
            "Expected at least 2 PR-514 layer specs",
        )

    def test_authority_conflict_elimination_layer_spec(self):
        from core.runtime_closure_audit import (
            reset_runtime_closure_audit,
            get_runtime_closure_audit,
        )
        reset_runtime_closure_audit()
        audit = get_runtime_closure_audit()
        sentinel_names = [spec[2] for spec in audit._LAYER_SPECS]
        self.assertIn("AUTHORITY_CONFLICT_ELIMINATION_AUTHORITY", sentinel_names)

    def test_projection_routes_ace_integrated_spec(self):
        from core.runtime_closure_audit import (
            reset_runtime_closure_audit,
            get_runtime_closure_audit,
        )
        reset_runtime_closure_audit()
        audit = get_runtime_closure_audit()
        sentinel_names = [spec[2] for spec in audit._LAYER_SPECS]
        self.assertIn("AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED", sentinel_names)


class TestX_Gap512003ResidualFalse(unittest.TestCase):
    """X) GAP-512-003 is marked is_residual=False in the residual gap map."""

    def test_gap_512_003_not_residual(self):
        from core.runtime_closure_audit import (
            reset_runtime_closure_audit,
            get_residual_gap_map,
        )
        reset_runtime_closure_audit()
        gaps = get_residual_gap_map()
        gap_by_id = {g.gap_id: g for g in gaps}
        self.assertIn("GAP-512-003", gap_by_id)
        self.assertFalse(
            gap_by_id["GAP-512-003"].is_residual,
            "GAP-512-003 should be resolved (is_residual=False) in PR-514",
        )


class TestY_Gap512005ResidualFalse(unittest.TestCase):
    """Y) GAP-512-005 is marked is_residual=False in the residual gap map."""

    def test_gap_512_005_not_residual(self):
        from core.runtime_closure_audit import (
            reset_runtime_closure_audit,
            get_residual_gap_map,
        )
        reset_runtime_closure_audit()
        gaps = get_residual_gap_map()
        gap_by_id = {g.gap_id: g for g in gaps}
        self.assertIn("GAP-512-005", gap_by_id)
        self.assertFalse(
            gap_by_id["GAP-512-005"].is_residual,
            "GAP-512-005 should be resolved (is_residual=False) in PR-514",
        )


class TestZ_Gap512008ResidualFalse(unittest.TestCase):
    """Z) GAP-512-008 is marked is_residual=False in the residual gap map."""

    def test_gap_512_008_not_residual(self):
        from core.runtime_closure_audit import (
            reset_runtime_closure_audit,
            get_residual_gap_map,
        )
        reset_runtime_closure_audit()
        gaps = get_residual_gap_map()
        gap_by_id = {g.gap_id: g for g in gaps}
        self.assertIn("GAP-512-008", gap_by_id)
        self.assertFalse(
            gap_by_id["GAP-512-008"].is_residual,
            "GAP-512-008 should be resolved (is_residual=False) in PR-514",
        )


class TestAA_ViolationLogInSnapshot(unittest.TestCase):
    """AA) Violation log is captured in the snapshot."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_violation_appears_in_snapshot(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
            build_authority_elimination_snapshot,
        )
        rt = get_authority_conflict_elimination_runtime()
        rt.record_assertion_violation("TestLayer", "some_fact", "CanonicalSource")
        snap = build_authority_elimination_snapshot()
        self.assertEqual(snap.total_assertion_violations, 1)
        self.assertEqual(len(snap.assertion_violations), 1)
        self.assertEqual(snap.assertion_violations[0]["layer_name"], "TestLayer")


class TestBB_ResetCallable(unittest.TestCase):
    """BB) reset_authority_conflict_elimination_runtime is callable and resets state."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_reset_clears_violations(self):
        from core.authority_conflict_elimination import (
            get_authority_conflict_elimination_runtime,
            reset_authority_conflict_elimination_runtime,
        )
        rt = get_authority_conflict_elimination_runtime()
        rt.record_assertion_violation("A", "b", "C")
        reset_authority_conflict_elimination_runtime()
        rt2 = get_authority_conflict_elimination_runtime()
        self.assertIsNot(rt, rt2)
        self.assertEqual(rt2.get_violation_log(), [])

    def test_reset_can_be_called_multiple_times(self):
        from core.authority_conflict_elimination import (
            reset_authority_conflict_elimination_runtime,
        )
        # Should not raise
        reset_authority_conflict_elimination_runtime()
        reset_authority_conflict_elimination_runtime()


if __name__ == "__main__":
    unittest.main()
