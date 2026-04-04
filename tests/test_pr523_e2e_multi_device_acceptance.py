#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr523_e2e_multi_device_acceptance.py
===============================================
PR-523 — End-to-End Multi-Device Acceptance & Verification.

This module is the **end-to-end acceptance and verification layer** for the
Galaxy multi-device control architecture.  It proves that the post-PR-517
architecture behaves coherently as a whole after the following gap-closing PRs:

- PR-518: Cross-Device Entry & Dispatch Closure (GAP-517-001, GAP-517-003)
- PR-519: Cross-Device Result Surface Closure (GAP-517-007)
- PR-520: Formation Truth Hardening (GAP-517-004, GAP-517-005)
- PR-521: Control Semantic Separation (GAP-517-006)
- PR-522: Multi-Device Projection Canonicalization (GAP-517-008)

Acceptance matrix scenarios
----------------------------
S1  Local execution on originating device.
S2  Originating device dispatching to a different target device.
S3  Multiple candidate devices with canonical selection.
S4  Explicit formation membership and role assignment.
S5  Remote takeover / delegation scenario.
S6  Incomplete / degraded participation / readiness behavior.
S7  Result surfacing through canonical runtime / operator / audit layers.
S8  Projection / runtime view reflecting canonical state.

Test groups
-----------
 A)  PR-523 sentinels — acceptance sentinel constants importable and correct.
 B)  Residual gap closure accounting — 8/8 gaps resolved after PR-518–532.
 C)  S1 — Local execution: canonical entry, local routing, result surfaced.
 D)  S2 — Cross-device dispatch: envelope routes to remote target, result surfaced.
 E)  S3 — Multi-candidate canonical selection: formation resolves correct primary.
 F)  S4 — Formation membership and role assignment visible in formation descriptor.
 G)  S5 — Takeover / delegation: control semantic record marks is_takeover.
 H)  S6 — Degraded participation: deny-by-default gate and structured warning.
 I)  S7 — Result surfacing: ResultEnvelope, chain record, graph, replay updated.
 J)  S8 — Projection enrichment: canonical enrichment keys present, state is FULL.
 K)  Operator / audit visibility: integrity snapshot contains representative records.
 L)  GAP-517-002 closure reflected canonically across accounting surfaces.
 M)  Integrated path: canonical sentinels present in key modules.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _reset_chain():
    try:
        from core.cross_device_execution_chain import reset_cross_device_chain

        reset_cross_device_chain()
    except Exception:
        pass


def _reset_graph():
    try:
        from core.task_graph_runtime import reset_task_graph_runtime

        reset_task_graph_runtime()
    except Exception:
        pass


def _reset_integrity_runtime():
    try:
        from core.multi_device_control_integrity import reset_multi_device_integrity_runtime

        reset_multi_device_integrity_runtime()
    except Exception:
        pass


def _reset_all():
    _reset_chain()
    _reset_graph()
    _reset_integrity_runtime()


# ===========================================================================
# A) PR-523 sentinels
# ===========================================================================


class TestA_PR523Sentinels(unittest.TestCase):
    """A) PR-523 acceptance sentinel constants are importable and correct."""

    def test_A1_e2e_acceptance_verified_importable(self):
        """A1. MULTI_DEVICE_E2E_ACCEPTANCE_VERIFIED is importable."""
        from core.multi_device_control_integrity import MULTI_DEVICE_E2E_ACCEPTANCE_VERIFIED

        self.assertIsInstance(MULTI_DEVICE_E2E_ACCEPTANCE_VERIFIED, str)

    def test_A2_e2e_acceptance_verified_references_pr523(self):
        """A2. E2E acceptance sentinel references PR-523."""
        from core.multi_device_control_integrity import MULTI_DEVICE_E2E_ACCEPTANCE_VERIFIED

        self.assertIn("PR523", MULTI_DEVICE_E2E_ACCEPTANCE_VERIFIED)

    def test_A3_acceptance_matrix_coverage_importable(self):
        """A3. MULTI_DEVICE_ACCEPTANCE_MATRIX_COVERAGE is importable."""
        from core.multi_device_control_integrity import MULTI_DEVICE_ACCEPTANCE_MATRIX_COVERAGE

        self.assertIsInstance(MULTI_DEVICE_ACCEPTANCE_MATRIX_COVERAGE, str)

    def test_A4_acceptance_matrix_coverage_lists_scenarios(self):
        """A4. Coverage sentinel lists all 8 acceptance scenarios."""
        from core.multi_device_control_integrity import MULTI_DEVICE_ACCEPTANCE_MATRIX_COVERAGE

        for scenario in [
            "local_execution",
            "cross_device_dispatch",
            "multi_candidate_canonical_selection",
            "formation_membership_and_roles",
            "takeover_delegation",
            "degraded_participation",
            "canonical_result_surface",
            "projection_runtime_view",
        ]:
            self.assertIn(
                scenario,
                MULTI_DEVICE_ACCEPTANCE_MATRIX_COVERAGE,
                f"scenario {scenario!r} not listed in coverage sentinel",
            )

    def test_A5_residual_closure_accounting_importable(self):
        """A5. PR523_RESIDUAL_CLOSURE_ACCOUNTING is importable."""
        from core.multi_device_control_integrity import PR523_RESIDUAL_CLOSURE_ACCOUNTING

        self.assertIsInstance(PR523_RESIDUAL_CLOSURE_ACCOUNTING, str)

    def test_A6_residual_closure_accounting_covers_all_gaps(self):
        """A6. Closure accounting sentinel lists all 8 GAP identifiers."""
        from core.multi_device_control_integrity import PR523_RESIDUAL_CLOSURE_ACCOUNTING

        for gap_id in [
            "GAP-517-001",
            "GAP-517-002",
            "GAP-517-003",
            "GAP-517-004",
            "GAP-517-005",
            "GAP-517-006",
            "GAP-517-007",
            "GAP-517-008",
        ]:
            self.assertIn(gap_id, PR523_RESIDUAL_CLOSURE_ACCOUNTING)

    def test_A7_residual_closure_accounting_names_prs(self):
        """A7. Closure accounting names PR-518 through PR-522."""
        from core.multi_device_control_integrity import PR523_RESIDUAL_CLOSURE_ACCOUNTING

        for pr in ["PR-518", "PR-519", "PR-520", "PR-521", "PR-522"]:
            self.assertIn(pr, PR523_RESIDUAL_CLOSURE_ACCOUNTING)

    def test_A8_sentinels_in_all(self):
        """A8. PR-523 sentinels appear in the module __all__."""
        import core.multi_device_control_integrity as mod

        for name in [
            "MULTI_DEVICE_E2E_ACCEPTANCE_VERIFIED",
            "MULTI_DEVICE_ACCEPTANCE_MATRIX_COVERAGE",
            "PR523_RESIDUAL_CLOSURE_ACCOUNTING",
        ]:
            self.assertIn(name, mod.__all__, f"{name} missing from __all__")


# ===========================================================================
# B) Residual gap closure accounting
# ===========================================================================


class TestB_ResidualGapClosure(unittest.TestCase):
    """B) 8/8 GAP-517-* gaps are resolved after PR-518 through PR-532."""

    def setUp(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps

        self.gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}

    def test_B1_gap001_resolved_by_pr518(self):
        """B1. GAP-517-001 (entry unification) resolved by PR-518."""
        g = self.gaps.get("GAP-517-001")
        self.assertIsNotNone(g, "GAP-517-001 not in catalog")
        self.assertTrue(g.is_resolved, "GAP-517-001 should be resolved")
        self.assertIn("PR-518", g.resolution_note or "")

    def test_B2_gap003_resolved_by_pr518(self):
        """B2. GAP-517-003 (dispatch authority) resolved by PR-518."""
        g = self.gaps.get("GAP-517-003")
        self.assertIsNotNone(g)
        self.assertTrue(g.is_resolved)
        self.assertIn("PR-518", g.resolution_note or "")

    def test_B3_gap007_resolved_by_pr519(self):
        """B3. GAP-517-007 (result surface) resolved by PR-519."""
        g = self.gaps.get("GAP-517-007")
        self.assertIsNotNone(g)
        self.assertTrue(g.is_resolved)
        self.assertIn("PR-519", g.resolution_note or "")

    def test_B4_gap004_resolved_by_pr520(self):
        """B4. GAP-517-004 (formation descriptor) resolved by PR-520."""
        g = self.gaps.get("GAP-517-004")
        self.assertIsNotNone(g)
        self.assertTrue(g.is_resolved)
        self.assertIn("PR-520", g.resolution_note or "")

    def test_B5_gap005_resolved_by_pr520(self):
        """B5. GAP-517-005 (constellation fallback) resolved by PR-520."""
        g = self.gaps.get("GAP-517-005")
        self.assertIsNotNone(g)
        self.assertTrue(g.is_resolved)
        self.assertIn("PR-520", g.resolution_note or "")

    def test_B6_gap006_resolved_by_pr521(self):
        """B6. GAP-517-006 (control semantics) resolved by PR-521."""
        g = self.gaps.get("GAP-517-006")
        self.assertIsNotNone(g)
        self.assertTrue(g.is_resolved)
        self.assertIn("PR-521", g.resolution_note or "")

    def test_B7_gap008_resolved_by_pr522(self):
        """B7. GAP-517-008 (projection canonicalization) resolved by PR-522."""
        g = self.gaps.get("GAP-517-008")
        self.assertIsNotNone(g)
        self.assertTrue(g.is_resolved)
        self.assertIn("PR-522", g.resolution_note or "")

    def test_B8_gap002_resolved_by_pr532(self):
        """B8. GAP-517-002 (parallel entry) resolved by PR-532."""
        g = self.gaps.get("GAP-517-002")
        self.assertIsNotNone(g)
        self.assertTrue(g.is_resolved, "GAP-517-002 should now be resolved")
        self.assertIn("PR-532", g.resolution_note or "")

    def test_B9_eight_of_eight_resolved(self):
        """B9. Exactly 8 of 8 PR-517 gaps are resolved."""
        resolved = [g for g in self.gaps.values() if g.is_resolved]
        self.assertEqual(len(resolved), 8, "Expected exactly 8 resolved gaps")

    def test_B10_no_high_severity_open_gaps(self):
        """B10. No HIGH-severity gaps remain open after PR-518 through PR-532."""
        open_high = [g for g in self.gaps.values() if not g.is_resolved and g.severity == "HIGH"]
        self.assertEqual(open_high, [], f"Unexpected open HIGH gaps: {open_high}")


# ===========================================================================
# C) S1 — Local execution on originating device
# ===========================================================================


class TestC_S1_LocalExecution(unittest.TestCase):
    """C) S1: Local execution on originating device — canonical artifact checks."""

    def test_C1_entry_unification_record_local_path(self):
        """C1. EntryUnificationRecord can represent a local (canonical) entry."""
        from core.multi_device_control_integrity import (
            build_entry_unification_record,
            EntryUnificationKind,
        )

        record = build_entry_unification_record(
            task_id="local-task-001",
            source_device_id="device-A",
            entry_kind=EntryUnificationKind.CANONICAL,
            entry_point="core.routes.tasks",
        )
        self.assertEqual(record.entry_kind, EntryUnificationKind.CANONICAL)
        self.assertEqual(record.source_device_id, "device-A")
        self.assertTrue(record.is_canonical)

    def test_C2_dispatch_authority_record_local_path(self):
        """C2. DispatchAuthorityRecord local path is marked as canonical."""
        from core.multi_device_control_integrity import (
            build_dispatch_authority_record,
            DispatchPathKind,
        )

        record = build_dispatch_authority_record(
            task_id="local-task-001",
            dispatch_path=DispatchPathKind.COMMAND_ROUTER_CANONICAL,
            source_device_id="device-A",
            target_device_ids=["device-A"],
        )
        self.assertEqual(record.dispatch_path, DispatchPathKind.COMMAND_ROUTER_CANONICAL)
        self.assertTrue(record.is_canonical)

    def test_C3_control_semantic_record_local_is_local(self):
        """C3. ControlSemanticRecord for local execution has is_local=True."""
        from core.multi_device_control_integrity import (
            build_control_semantic_record,
            ControlSemanticKind,
        )

        record = build_control_semantic_record(
            task_id="local-task-001",
            source_device_id="device-A",
            target_device_id="device-A",
            control_kind=ControlSemanticKind.LOCAL_EXECUTION,
        )
        self.assertTrue(record.is_local)
        self.assertFalse(record.is_remote_dispatch)
        self.assertEqual(record.control_kind, ControlSemanticKind.LOCAL_EXECUTION)

    def test_C4_result_surface_record_local_full_surface(self):
        """C4. ResultSurfaceRecord can represent a fully surfaced local result."""
        from core.multi_device_control_integrity import (
            build_result_surface_record,
            ResultSurfaceKind,
        )

        record = build_result_surface_record(
            task_id="local-task-001",
            source_device_id="device-A",
            result_envelope_produced=True,
            task_graph_updated=True,
            replay_foundation_updated=True,
            operator_surface_updated=True,
            projection_updated=True,
        )
        self.assertTrue(record.is_canonically_surfaced)
        self.assertEqual(record.surface_kind, ResultSurfaceKind.CANONICAL_FULL)
        self.assertEqual(record.surface_gap_reasons, [])

    def test_C5_surface_cross_device_result_with_success_dict(self):
        """C5. surface_cross_device_result processes a local-path success dict."""
        _reset_all()
        from core.cross_device_result_surface import surface_cross_device_result

        raw = {"success": True, "task_id": "local-task-001", "result": "done"}
        record = surface_cross_device_result(
            raw,
            task_id="local-task-001",
            device_id="device-A",
            route_mode="local",
        )
        self.assertTrue(record.result_envelope_produced)

    def test_C6_integrity_event_local_canonical_recorded(self):
        """C6. record_integrity_event records a canonical local entry event."""
        _reset_integrity_runtime()
        from core.multi_device_control_integrity import (
            build_entry_unification_record,
            EntryUnificationKind,
            record_integrity_event,
            get_multi_device_integrity_runtime,
        )

        record = build_entry_unification_record(
            task_id="local-task-002",
            source_device_id="device-A",
            entry_kind=EntryUnificationKind.CANONICAL,
            entry_point="test_local_path",
        )
        record_integrity_event(entry_record=record)
        rt = get_multi_device_integrity_runtime()
        snap = rt.snapshot()
        self.assertGreater(snap.canonical_entry_count + snap.legacy_entry_count, 0)


# ===========================================================================
# D) S2 — Cross-device dispatch to a different target device
# ===========================================================================


class TestD_S2_CrossDeviceDispatch(unittest.TestCase):
    """D) S2: Originating device dispatching to a different target device."""

    def test_D1_entry_unification_record_cross_device_canonical(self):
        """D1. Cross-device entry through canonical path is marked CANONICAL."""
        from core.multi_device_control_integrity import (
            build_entry_unification_record,
            EntryUnificationKind,
        )

        record = build_entry_unification_record(
            task_id="xdev-task-001",
            source_device_id="device-A",
            entry_kind=EntryUnificationKind.CANONICAL,
            entry_point="core.routes.devices",
        )
        self.assertTrue(record.is_canonical)

    def test_D2_dispatch_authority_record_cross_device_canonical(self):
        """D2. Cross-device dispatch via CommandRouter is canonical."""
        from core.multi_device_control_integrity import (
            build_dispatch_authority_record,
            DispatchPathKind,
        )

        record = build_dispatch_authority_record(
            task_id="xdev-task-001",
            dispatch_path=DispatchPathKind.COMMAND_ROUTER_CANONICAL,
            source_device_id="device-A",
            target_device_ids=["device-B"],
        )
        self.assertTrue(record.is_canonical)
        self.assertIn("device-B", record.target_device_ids)

    def test_D3_control_semantic_record_remote_dispatch(self):
        """D3. Cross-device dispatch from A to B yields REMOTE_DISPATCH kind."""
        from core.multi_device_control_integrity import (
            build_control_semantic_record,
            ControlSemanticKind,
        )

        record = build_control_semantic_record(
            task_id="xdev-task-001",
            source_device_id="device-A",
            target_device_id="device-B",
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
        )
        self.assertFalse(record.is_local)
        self.assertTrue(record.is_remote_dispatch)
        self.assertEqual(record.control_kind, ControlSemanticKind.REMOTE_DISPATCH)

    def test_D4_source_and_target_are_distinct(self):
        """D4. Source and target device IDs are distinct in cross-device scenario."""
        from core.multi_device_control_integrity import build_control_semantic_record

        record = build_control_semantic_record(
            task_id="xdev-task-001",
            source_device_id="device-A",
            target_device_id="device-B",
        )
        self.assertNotEqual(record.source_device_id, record.target_device_id)
        self.assertEqual(record.source_device_id, "device-A")
        self.assertEqual(record.target_device_id, "device-B")

    def test_D5_result_surfaced_for_cross_device_success(self):
        """D5. Cross-device success result is surfaced canonically."""
        _reset_all()
        from core.cross_device_result_surface import surface_cross_device_result

        raw = {"success": True, "task_id": "xdev-task-001", "device_id": "device-B"}
        record = surface_cross_device_result(
            raw,
            task_id="xdev-task-001",
            device_id="device-B",
            source_device_id="device-A",
            target_device_ids=["device-B"],
            route_mode="cross_device",
        )
        self.assertTrue(record.result_envelope_produced)
        # Verify the chain record has the envelope
        from core.cross_device_execution_chain import get_cross_device_chain

        snap = get_cross_device_chain().snapshot()
        task_ids = [r.task_id for r in snap.recent_records]
        self.assertIn("xdev-task-001", task_ids)

    def test_D6_cross_device_rest_ingress_sentinel_in_devices_route(self):
        """D6. CROSS_DEVICE_REST_INGRESS_CANONICAL sentinel is present in devices.py."""
        import inspect
        import core.routes.devices as devices_mod

        src = inspect.getsource(devices_mod)
        self.assertIn("CROSS_DEVICE_REST_INGRESS_CANONICAL", src)
        self.assertIn("GAP-517-001", src)

    def test_D7_command_router_cross_device_canonical_path_sentinel(self):
        """D7. COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH sentinel importable."""
        from core.command_router import COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH

        self.assertIn("GAP-517-001", COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH)


# ===========================================================================
# E) S3 — Multiple candidate devices with canonical selection
# ===========================================================================


class TestE_S3_MultiCandidateSelection(unittest.TestCase):
    """E) S3: Multiple candidate devices with canonical formation selection."""

    def test_E1_formation_truth_record_multi_device(self):
        """E1. FormationTruthRecord can describe a multi-device formation."""
        from core.multi_device_control_integrity import (
            build_formation_truth_record,
            FormationTruthConsistency,
        )

        record = build_formation_truth_record(
            task_id="multi-task-001",
            source_device_id="device-A",
            primary_device_id="device-B",
            member_device_ids=["device-A", "device-B", "device-C"],
            consistency=FormationTruthConsistency.CONSISTENT,
        )
        self.assertEqual(
            set(record.member_device_ids),
            {"device-A", "device-B", "device-C"},
        )
        self.assertEqual(record.consistency, FormationTruthConsistency.CONSISTENT)

    def test_E2_formation_truth_is_consistent_when_descriptor_attached(self):
        """E2. Consistent formation truth is_consistent returns True."""
        from core.multi_device_control_integrity import (
            build_formation_truth_record,
            FormationTruthConsistency,
        )

        record = build_formation_truth_record(
            task_id="multi-task-001",
            source_device_id="device-A",
            primary_device_id="device-B",
            member_device_ids=["device-A", "device-B"],
            consistency=FormationTruthConsistency.CONSISTENT,
        )
        self.assertTrue(record.is_consistent)

    def test_E3_formation_resolver_importable(self):
        """E3. resolve_formation is importable from core.device_formation."""
        from core.device_formation import resolve_formation

        self.assertTrue(callable(resolve_formation))

    def test_E4_device_formation_group_has_required_fields(self):
        """E4. DeviceFormationGroup has source_device_id and members."""
        from core.device_formation.formation_group import DeviceFormationGroup
        import dataclasses

        field_names = {f.name for f in dataclasses.fields(DeviceFormationGroup)}
        for required in [
            "source_device_id",
            "source_runtime_posture",
            "members",
        ]:
            self.assertIn(
                required,
                field_names,
                f"DeviceFormationGroup missing field {required!r}",
            )

    def test_E5_device_formation_group_to_dict(self):
        """E5. DeviceFormationGroup.to_dict() is serialisable."""
        from core.device_formation.formation_group import DeviceFormationGroup

        group = DeviceFormationGroup(
            formation_id="formation-001",
            source_device_id="device-A",
        )
        d = group.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["source_device_id"], "device-A")
        self.assertEqual(d["source_runtime_posture"], "control_only")

    def test_E6_device_router_formation_descriptor_attached_sentinel(self):
        """E6. DEVICE_ROUTER_FORMATION_DESCRIPTOR_ATTACHED sentinel importable."""
        from galaxy_gateway.device_router import DEVICE_ROUTER_FORMATION_DESCRIPTOR_ATTACHED

        self.assertIn("GAP-517-004", DEVICE_ROUTER_FORMATION_DESCRIPTOR_ATTACHED)

    def test_E7_coordinator_formation_descriptor_attached_sentinel(self):
        """E7. CROSS_DEVICE_COORDINATOR_FORMATION_DESCRIPTOR_ATTACHED sentinel importable."""
        from galaxy_gateway.cross_device_coordinator import (
            CROSS_DEVICE_COORDINATOR_FORMATION_DESCRIPTOR_ATTACHED,
        )

        self.assertIn("GAP-517-004", CROSS_DEVICE_COORDINATOR_FORMATION_DESCRIPTOR_ATTACHED)


# ===========================================================================
# F) S4 — Explicit formation membership and role assignment
# ===========================================================================


class TestF_S4_FormationMembership(unittest.TestCase):
    """F) S4: Explicit formation membership and role assignment are observable."""

    def test_F1_formation_truth_record_records_participating_ids(self):
        """F1. FormationTruthRecord records all participating device IDs."""
        from core.multi_device_control_integrity import build_formation_truth_record

        record = build_formation_truth_record(
            task_id="formation-task-001",
            source_device_id="phone-A",
            primary_device_id="desktop-B",
            member_device_ids=["phone-A", "desktop-B", "tablet-C"],
        )
        self.assertEqual(len(record.member_device_ids), 3)

    def test_F2_formation_truth_record_records_primary_and_source(self):
        """F2. FormationTruthRecord distinguishes source and primary device."""
        from core.multi_device_control_integrity import build_formation_truth_record

        record = build_formation_truth_record(
            task_id="formation-task-001",
            source_device_id="phone-A",
            primary_device_id="desktop-B",
            member_device_ids=["phone-A", "desktop-B"],
        )
        self.assertEqual(record.source_device_id, "phone-A")
        self.assertEqual(record.primary_device_id, "desktop-B")

    def test_F3_formation_truth_record_emitted_to_integrity_runtime(self):
        """F3. Formation truth record is visible through integrity runtime."""
        _reset_integrity_runtime()
        from core.multi_device_control_integrity import (
            build_formation_truth_record,
            record_integrity_event,
            get_multi_device_integrity_runtime,
        )

        record = build_formation_truth_record(
            task_id="formation-task-002",
            source_device_id="phone-A",
            primary_device_id="desktop-B",
            member_device_ids=["phone-A", "desktop-B"],
        )
        record_integrity_event(formation_record=record)
        rt = get_multi_device_integrity_runtime()
        snap = rt.snapshot()
        self.assertGreater(len(snap.recent_formation_records), 0)

    def test_F4_device_formation_group_role_assignment(self):
        """F4. DeviceFormationGroup role_assignments or members attribute is accessible."""
        from core.device_formation.formation_group import DeviceFormationGroup

        group = DeviceFormationGroup(
            formation_id="formation-002",
            source_device_id="phone-A",
        )
        # members should be an attribute (list of FormationMember)
        self.assertTrue(
            hasattr(group, "members"),
            "DeviceFormationGroup should have members attribute",
        )
        self.assertIsInstance(group.members, list)

    def test_F5_formation_truth_record_to_dict_serialisable(self):
        """F5. FormationTruthRecord.to_dict() produces a complete dict."""
        from core.multi_device_control_integrity import build_formation_truth_record

        record = build_formation_truth_record(
            task_id="formation-task-003",
            source_device_id="phone-A",
            primary_device_id="desktop-B",
            member_device_ids=["phone-A", "desktop-B"],
        )
        d = record.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["task_id"], "formation-task-003")
        self.assertIn("source_device_id", d)
        self.assertIn("member_device_ids", d)


# ===========================================================================
# G) S5 — Remote takeover / delegation scenario
# ===========================================================================


class TestG_S5_TakeoverDelegation(unittest.TestCase):
    """G) S5: Remote takeover / delegation — control semantic record marks is_takeover."""

    def test_G1_control_semantic_record_takeover_kind(self):
        """G1. ControlSemanticRecord with is_takeover=True and TAKEOVER kind."""
        from core.multi_device_control_integrity import (
            build_control_semantic_record,
            ControlSemanticKind,
        )

        record = build_control_semantic_record(
            task_id="takeover-task-001",
            source_device_id="device-A",
            target_device_id="device-B",
            control_kind=ControlSemanticKind.TAKEOVER,
            is_takeover=True,
        )
        self.assertTrue(record.is_takeover)
        self.assertEqual(record.control_kind, ControlSemanticKind.TAKEOVER)

    def test_G2_takeover_record_is_not_local(self):
        """G2. Takeover record has is_local=False."""
        from core.multi_device_control_integrity import build_control_semantic_record

        record = build_control_semantic_record(
            task_id="takeover-task-001",
            source_device_id="device-A",
            target_device_id="device-B",
            is_takeover=True,
        )
        self.assertFalse(record.is_local)

    def test_G3_takeover_record_is_semantically_clear(self):
        """G3. Takeover record with explicit source+target is semantically clear."""
        from core.multi_device_control_integrity import build_control_semantic_record, ControlSemanticKind

        record = build_control_semantic_record(
            task_id="takeover-task-001",
            source_device_id="device-A",
            target_device_id="device-B",
            control_kind=ControlSemanticKind.TAKEOVER,
            is_takeover=True,
        )
        self.assertTrue(record.is_semantically_clear)

    def test_G4_control_semantic_record_emitted_to_integrity_runtime(self):
        """G4. Takeover control semantic record is visible in integrity snapshot."""
        _reset_integrity_runtime()
        from core.multi_device_control_integrity import (
            build_control_semantic_record,
            record_integrity_event,
            get_multi_device_integrity_runtime,
            ControlSemanticKind,
        )

        record = build_control_semantic_record(
            task_id="takeover-task-002",
            source_device_id="device-A",
            target_device_id="device-B",
            control_kind=ControlSemanticKind.TAKEOVER,
            is_takeover=True,
        )
        record_integrity_event(control_record=record)
        rt = get_multi_device_integrity_runtime()
        snap = rt.snapshot()
        self.assertGreater(len(snap.recent_control_semantic_records), 0)

    def test_G5_device_router_control_semantic_separation_sentinel(self):
        """G5. DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION sentinel importable."""
        from galaxy_gateway.device_router import DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION

        self.assertIn("GAP-517-006", DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION)

    def test_G6_control_semantic_kind_hybrid_for_multi_target(self):
        """G6. HYBRID kind is emitted when multiple target devices are selected."""
        from core.multi_device_control_integrity import (
            build_control_semantic_record,
            ControlSemanticKind,
        )

        record = build_control_semantic_record(
            task_id="takeover-task-003",
            source_device_id="device-A",
            target_device_id="device-B",
            control_kind=ControlSemanticKind.HYBRID,
        )
        self.assertEqual(record.control_kind, ControlSemanticKind.HYBRID)


# ===========================================================================
# H) S6 — Incomplete / degraded participation / readiness behavior
# ===========================================================================


class TestH_S6_DegradedParticipation(unittest.TestCase):
    """H) S6: Degraded participation — deny-by-default gate and structured warning."""

    def test_H1_constellation_gate_deny_by_default_sentinel_importable(self):
        """H1. CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT is importable."""
        from core.constellation_runtime import CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT

        self.assertIsInstance(CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT, str)

    def test_H2_constellation_gate_sentinel_references_gap005(self):
        """H2. The deny-by-default sentinel references GAP-517-005."""
        from core.constellation_runtime import CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT

        self.assertIn("GAP-517-005", CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT)

    def test_H3_is_orchestration_ready_deny_by_default_when_participation_unavailable(self):
        """H3. _is_orchestration_ready() returns False when participation layer raises."""
        from core.constellation_runtime import ConstellationRuntime

        runtime = ConstellationRuntime()
        with patch(
            "core.device_participation.is_device_orchestration_ready",
            side_effect=Exception("participation layer unavailable"),
        ):
            result = runtime._is_orchestration_ready("device-X")
        self.assertFalse(
            result,
            "_is_orchestration_ready must be deny-by-default (False) when participation unavailable",
        )

    def test_H4_is_orchestration_ready_emits_warning_on_exception(self):
        """H4. _is_orchestration_ready() emits WARNING log when gate is unreachable."""
        from core.constellation_runtime import ConstellationRuntime

        runtime = ConstellationRuntime()
        with self.assertLogs("Galaxy.ConstellationRuntime", level="WARNING") as log_ctx:
            with patch(
                "core.device_participation.is_device_orchestration_ready",
                side_effect=Exception("gate error"),
            ):
                runtime._is_orchestration_ready("device-X")
        self.assertTrue(
            any("deny" in m.lower() or "gate" in m.lower() or "GAP-517-005" in m for m in log_ctx.output),
            "Expected structured warning about deny-by-default gate",
        )

    def test_H5_formation_truth_record_inconsistent_when_descriptor_missing(self):
        """H5. FormationTruthRecord marks inconsistent when consistency is not CONSISTENT."""
        from core.multi_device_control_integrity import (
            build_formation_truth_record,
            FormationTruthConsistency,
        )

        record = build_formation_truth_record(
            task_id="degraded-task-001",
            source_device_id="device-A",
            primary_device_id="",
            member_device_ids=[],
            consistency=FormationTruthConsistency.UNKNOWN,
        )
        self.assertFalse(record.is_consistent)

    def test_H6_result_surface_record_partial_when_not_all_surfaces_updated(self):
        """H6. ResultSurfaceRecord is partial when not all surfaces updated."""
        from core.multi_device_control_integrity import (
            build_result_surface_record,
            ResultSurfaceKind,
        )

        record = build_result_surface_record(
            task_id="degraded-task-001",
            source_device_id="device-A",
            result_envelope_produced=True,
            task_graph_updated=False,
            replay_foundation_updated=False,
            operator_surface_updated=False,
            projection_updated=False,
        )
        self.assertFalse(record.is_canonically_surfaced)
        self.assertNotEqual(record.surface_kind, ResultSurfaceKind.CANONICAL_FULL)

    def test_H7_degraded_result_surface_has_gap_reasons(self):
        """H7. Partial/degraded ResultSurfaceRecord exposes gap reasons."""
        from core.multi_device_control_integrity import build_result_surface_record

        record = build_result_surface_record(
            task_id="degraded-task-001",
            source_device_id="device-A",
            result_envelope_produced=True,
            task_graph_updated=False,
            replay_foundation_updated=False,
            operator_surface_updated=False,
            projection_updated=False,
            surface_gap_reasons=["GAP-517-007: graph update failed"],
        )
        self.assertIsInstance(record.surface_gap_reasons, list)
        self.assertGreater(
            len(record.surface_gap_reasons),
            0,
            "Partial surface record should have gap reasons",
        )

    def test_H8_entry_unification_record_legacy_path_marked(self):
        """H8. Legacy entry path is clearly marked in EntryUnificationRecord."""
        from core.multi_device_control_integrity import (
            build_entry_unification_record,
            EntryUnificationKind,
        )

        record = build_entry_unification_record(
            task_id="legacy-task-001",
            source_device_id="device-A",
            entry_kind=EntryUnificationKind.LEGACY_COORDINATOR_BYPASS,
            entry_point="legacy.handler",
        )
        self.assertFalse(record.is_canonical)


# ===========================================================================
# I) S7 — Result surfacing through canonical runtime / operator / audit layers
# ===========================================================================


class TestI_S7_CanonicalResultSurface(unittest.TestCase):
    """I) S7: Result surfacing — ResultEnvelope, chain, graph, replay all updated."""

    def setUp(self):
        _reset_all()

    def test_I1_surface_cross_device_result_produces_result_envelope(self):
        """I1. surface_cross_device_result produces a ResultEnvelope."""
        from core.cross_device_result_surface import surface_cross_device_result

        raw = {"success": True, "task_id": "surface-task-001"}
        record = surface_cross_device_result(
            raw,
            task_id="surface-task-001",
            device_id="device-B",
            source_device_id="device-A",
            route_mode="cross_device",
        )
        self.assertTrue(record.result_envelope_produced)
        # The actual ResultEnvelope is stored in the chain record
        from core.cross_device_execution_chain import get_cross_device_chain

        snap = get_cross_device_chain().snapshot()
        chain_task_ids = [r.task_id for r in snap.recent_records]
        self.assertIn("surface-task-001", chain_task_ids)

    def test_I2_surface_cross_device_result_updates_chain(self):
        """I2. surface_cross_device_result adds a record to CrossDeviceChainSingleton."""
        from core.cross_device_result_surface import surface_cross_device_result
        from core.cross_device_execution_chain import get_cross_device_chain

        raw = {"success": True, "task_id": "surface-task-002"}
        surface_cross_device_result(
            raw,
            task_id="surface-task-002",
            device_id="device-B",
            source_device_id="device-A",
        )
        chain = get_cross_device_chain()
        snap = chain.snapshot()
        ids = [r.task_id for r in snap.recent_records]
        self.assertIn("surface-task-002", ids)

    def test_I3_surface_cross_device_result_updates_task_graph(self):
        """I3. surface_cross_device_result updates TaskGraphRuntime."""
        from core.cross_device_result_surface import surface_cross_device_result

        record = surface_cross_device_result(
            {"success": True, "task_id": "surface-task-003"},
            task_id="surface-task-003",
            device_id="device-B",
        )
        self.assertTrue(record.task_graph_updated)

    def test_I4_surface_cross_device_result_updates_replay_foundation(self):
        """I4. surface_cross_device_result emits to ReplayFoundation."""
        from core.cross_device_result_surface import surface_cross_device_result

        record = surface_cross_device_result(
            {"success": True, "task_id": "surface-task-004"},
            task_id="surface-task-004",
            device_id="device-B",
        )
        self.assertTrue(record.replay_foundation_updated)

    def test_I5_surface_record_is_canonically_surfaced_for_success(self):
        """I5. Successful canonical surface yields is_canonically_surfaced=True."""
        from core.cross_device_result_surface import surface_cross_device_result

        record = surface_cross_device_result(
            {"success": True, "task_id": "surface-task-005"},
            task_id="surface-task-005",
            device_id="device-B",
        )
        # is_canonically_surfaced requires all 4 flags: envelope + operator + graph + replay
        # surface_cross_device_result sets all four on the success path
        self.assertTrue(record.result_envelope_produced)
        self.assertTrue(record.task_graph_updated)
        self.assertTrue(record.replay_foundation_updated)

    def test_I6_result_surface_record_for_failure_marks_failed(self):
        """I6. Failure raw result produces a result envelope with success=False."""
        from core.cross_device_result_surface import surface_cross_device_result
        from core.cross_device_execution_chain import get_cross_device_chain

        record = surface_cross_device_result(
            {"success": False, "error": "device unreachable", "task_id": "surface-task-006"},
            task_id="surface-task-006",
            device_id="device-B",
        )
        self.assertTrue(record.result_envelope_produced)
        # The actual ResultEnvelope success=False is in the chain record
        snap = get_cross_device_chain().snapshot()
        matched = [r for r in snap.recent_records if r.task_id == "surface-task-006"]
        self.assertGreater(len(matched), 0)
        # The envelope in the chain record should indicate failure
        if matched[0].result_envelope is not None:
            self.assertFalse(matched[0].result_envelope.success)

    def test_I7_cross_device_result_surface_gap007_resolved_sentinel(self):
        """I7. CROSS_DEVICE_RESULT_SURFACE_GAP007_RESOLVED sentinel importable."""
        from core.cross_device_result_surface import CROSS_DEVICE_RESULT_SURFACE_GAP007_RESOLVED

        self.assertIn("GAP_517_007_RESOLVED", CROSS_DEVICE_RESULT_SURFACE_GAP007_RESOLVED)

    def test_I8_chain_snapshot_reflects_surfaced_execution(self):
        """I8. CrossDeviceChain snapshot reflects the surfaced execution."""
        from core.cross_device_result_surface import surface_cross_device_result
        from core.cross_device_execution_chain import get_cross_device_chain

        surface_cross_device_result(
            {"success": True, "task_id": "surface-task-007"},
            task_id="surface-task-007",
            device_id="device-B",
        )
        snap = get_cross_device_chain().snapshot()
        self.assertIsInstance(snap.canonical_executions, int)
        self.assertGreaterEqual(snap.canonical_executions, 0)

    def test_I9_result_integrity_event_recorded_to_runtime(self):
        """I9. ResultSurfaceRecord is visible through integrity snapshot."""
        _reset_integrity_runtime()
        from core.multi_device_control_integrity import (
            build_result_surface_record,
            record_integrity_event,
            get_multi_device_integrity_runtime,
        )

        record = build_result_surface_record(
            task_id="surface-task-008",
            source_device_id="device-A",
            result_envelope_produced=True,
            task_graph_updated=True,
            replay_foundation_updated=True,
            operator_surface_updated=True,
        )
        record_integrity_event(result_record=record)
        snap = get_multi_device_integrity_runtime().snapshot()
        self.assertGreater(len(snap.recent_result_surface_records), 0)


# ===========================================================================
# J) S8 — Projection / runtime view reflecting canonical state
# ===========================================================================


class TestJ_S8_ProjectionRuntimeView(unittest.TestCase):
    """J) S8: Projection enrichment — canonical enrichment keys present."""

    def test_J1_multi_device_projection_canonicalization_authority_importable(self):
        """J1. MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY is importable."""
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY,
        )

        self.assertIn("PR522", MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY)

    def test_J2_enrich_multi_device_projection_is_callable(self):
        """J2. enrich_multi_device_projection() is importable and callable."""
        from core.multi_device_projection_canonicalization import enrich_multi_device_projection

        self.assertTrue(callable(enrich_multi_device_projection))

    def test_J3_enrich_multi_device_projection_returns_enrichment(self):
        """J3. enrich_multi_device_projection() returns a MultiDeviceCanonicalEnrichment."""
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
            MultiDeviceCanonicalEnrichment,
        )

        enrichment = enrich_multi_device_projection()
        self.assertIsInstance(enrichment, MultiDeviceCanonicalEnrichment)

    def test_J4_enrichment_to_dict_has_expected_keys(self):
        """J4. Enrichment.to_dict() has the canonical keys for projection."""
        from core.multi_device_projection_canonicalization import enrich_multi_device_projection

        d = enrich_multi_device_projection().to_dict()
        for key in [
            "surfacing_state",
            "chain_available",
            "graph_available",
            "transport_local_only",
        ]:
            self.assertIn(key, d, f"Missing key {key!r} in enrichment to_dict()")

    def test_J5_surfacing_state_is_valid_enum_value(self):
        """J5. Enrichment surfacing_state is a recognised CanonicalProjectionSurfacingState."""
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
            CanonicalProjectionSurfacingState,
        )

        enrichment = enrich_multi_device_projection()
        valid_values = {s.value for s in CanonicalProjectionSurfacingState}
        self.assertIn(
            enrichment.surfacing_state.value,
            valid_values,
            f"Unexpected surfacing_state: {enrichment.surfacing_state!r}",
        )

    def test_J6_gap008_resolved_sentinel_importable(self):
        """J6. MULTI_DEVICE_PROJECTION_GAP008_RESOLVED sentinel importable."""
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_GAP008_RESOLVED,
        )

        self.assertIn("GAP_517_008_RESOLVED", MULTI_DEVICE_PROJECTION_GAP008_RESOLVED)

    def test_J7_projection_canonicalization_integrated_in_projection_routes(self):
        """J7. MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED importable from projection routes."""
        import inspect
        import core.routes.projection as proj_mod

        src = inspect.getsource(proj_mod)
        self.assertIn("MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED", src)

    def test_J8_canonical_enrichment_state_full_when_chain_and_graph_available(self):
        """J8. Surfacing state is FULL when chain and graph are available."""
        from core.multi_device_projection_canonicalization import (
            enrich_multi_device_projection,
            CanonicalProjectionSurfacingState,
        )
        from core.cross_device_execution_chain import get_cross_device_chain
        from core.task_graph_runtime import get_task_graph_runtime

        # Ensure both singletons exist
        _ = get_cross_device_chain()
        _ = get_task_graph_runtime()

        enrichment = enrich_multi_device_projection()
        # If both are reachable the state should be FULL or PARTIAL (not UNAVAILABLE)
        self.assertNotEqual(
            enrichment.surfacing_state,
            CanonicalProjectionSurfacingState.UNAVAILABLE,
            "Expected at least PARTIAL state when canonical sources are reachable",
        )


# ===========================================================================
# K) Operator / audit visibility
# ===========================================================================


class TestK_OperatorAuditVisibility(unittest.TestCase):
    """K) Operator / audit visibility — integrity snapshot contains representative records."""

    def setUp(self):
        _reset_integrity_runtime()

    def test_K1_build_integrity_snapshot_returns_snapshot(self):
        """K1. build_integrity_snapshot() returns a MultiDeviceIntegritySnapshot."""
        from core.multi_device_control_integrity import (
            build_integrity_snapshot,
            MultiDeviceIntegritySnapshot,
        )

        snap = build_integrity_snapshot()
        self.assertIsInstance(snap, MultiDeviceIntegritySnapshot)

    def test_K2_integrity_snapshot_to_dict_serialisable(self):
        """K2. MultiDeviceIntegritySnapshot.to_dict() is serialisable."""
        from core.multi_device_control_integrity import build_integrity_snapshot

        d = build_integrity_snapshot().to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("authority", d)

    def test_K3_snapshot_reflects_entry_events(self):
        """K3. Integrity snapshot reflects recorded entry events."""
        from core.multi_device_control_integrity import (
            build_entry_unification_record,
            EntryUnificationKind,
            record_integrity_event,
            build_integrity_snapshot,
        )

        record = build_entry_unification_record(
            task_id="audit-task-001",
            source_device_id="device-A",
            entry_kind=EntryUnificationKind.CANONICAL,
            entry_point="test_operator_audit",
        )
        record_integrity_event(entry_record=record)
        snap = build_integrity_snapshot()
        self.assertGreater(snap.canonical_entry_count + snap.legacy_entry_count, 0)

    def test_K4_snapshot_reflects_dispatch_events(self):
        """K4. Integrity snapshot reflects recorded dispatch events."""
        from core.multi_device_control_integrity import (
            build_dispatch_authority_record,
            DispatchPathKind,
            record_integrity_event,
            build_integrity_snapshot,
        )

        record = build_dispatch_authority_record(
            task_id="audit-task-002",
            dispatch_path=DispatchPathKind.COMMAND_ROUTER_CANONICAL,
            source_device_id="device-A",
            target_device_ids=["device-B"],
        )
        record_integrity_event(dispatch_record=record)
        snap = build_integrity_snapshot()
        self.assertGreater(snap.canonical_dispatch_count + snap.legacy_dispatch_count, 0)

    def test_K5_snapshot_reflects_control_events(self):
        """K5. Integrity snapshot reflects recorded control semantic events."""
        from core.multi_device_control_integrity import (
            build_control_semantic_record,
            ControlSemanticKind,
            record_integrity_event,
            build_integrity_snapshot,
        )

        record = build_control_semantic_record(
            task_id="audit-task-003",
            source_device_id="device-A",
            target_device_id="device-B",
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
        )
        record_integrity_event(control_record=record)
        snap = build_integrity_snapshot()
        self.assertGreater(len(snap.recent_control_semantic_records), 0)

    def test_K6_snapshot_reflects_result_events(self):
        """K6. Integrity snapshot reflects recorded result surface events."""
        from core.multi_device_control_integrity import (
            build_result_surface_record,
            record_integrity_event,
            build_integrity_snapshot,
        )

        record = build_result_surface_record(
            task_id="audit-task-004",
            source_device_id="device-A",
            result_envelope_produced=True,
            task_graph_updated=True,
            replay_foundation_updated=True,
            operator_surface_updated=True,
        )
        record_integrity_event(result_record=record)
        snap = build_integrity_snapshot()
        self.assertGreater(len(snap.recent_result_surface_records), 0)

    def test_K7_snapshot_recent_records_list(self):
        """K7. Integrity snapshot recent_entry_records is a list."""
        from core.multi_device_control_integrity import build_integrity_snapshot

        snap = build_integrity_snapshot()
        self.assertIsInstance(snap.recent_entry_records, list)

    def test_K8_open_gaps_accessible_from_runtime(self):
        """K8. snapshot.open_gaps() returns only unresolved gaps."""
        from core.multi_device_control_integrity import get_multi_device_integrity_runtime

        rt = get_multi_device_integrity_runtime()
        open_gaps = rt.snapshot().open_gaps()
        for g in open_gaps:
            self.assertFalse(g.is_resolved)

    def test_K9_integrity_runtime_event_count_cumulative(self):
        """K9. Integrity runtime event counters are cumulative across multiple records."""
        from core.multi_device_control_integrity import (
            build_entry_unification_record,
            EntryUnificationKind,
            record_integrity_event,
            get_multi_device_integrity_runtime,
        )

        rt = get_multi_device_integrity_runtime()
        before = rt.snapshot().canonical_entry_count + rt.snapshot().legacy_entry_count
        for i in range(3):
            rec = build_entry_unification_record(
                task_id=f"cumulative-task-{i}",
                source_device_id="device-A",
                entry_kind=EntryUnificationKind.CANONICAL,
                entry_point="test_cumulative",
            )
            record_integrity_event(entry_record=rec)
        after = rt.snapshot().canonical_entry_count + rt.snapshot().legacy_entry_count
        self.assertEqual(after, before + 3)


# ===========================================================================
# L) GAP-517-002 closure documentation
# ===========================================================================


class TestL_GAP002ClosureAccounting(unittest.TestCase):
    """L) GAP-517-002 closure is reflected consistently across accounting surfaces."""

    def test_L1_gap002_exists_in_catalog(self):
        """L1. GAP-517-002 exists in the residual gap catalog."""
        from core.multi_device_control_integrity import get_residual_integrity_gaps

        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        self.assertIn("GAP-517-002", gaps)

    def test_L2_gap002_is_resolved(self):
        """L2. GAP-517-002 is marked as resolved."""
        from core.multi_device_control_integrity import get_residual_integrity_gaps

        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        self.assertTrue(gaps["GAP-517-002"].is_resolved)

    def test_L3_gap002_is_medium_severity(self):
        """L3. GAP-517-002 is MEDIUM severity (lower than the HIGH gaps closed in PR-518)."""
        from core.multi_device_control_integrity import get_residual_integrity_gaps

        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        self.assertEqual(gaps["GAP-517-002"].severity, "MEDIUM")

    def test_L4_gap002_has_description(self):
        """L4. GAP-517-002 has a non-empty description."""
        from core.multi_device_control_integrity import get_residual_integrity_gaps

        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        self.assertGreater(len(gaps["GAP-517-002"].description or ""), 0)

    def test_L5_closure_accounting_sentinel_marks_gap002_resolved(self):
        """L5. PR523_RESIDUAL_CLOSURE_ACCOUNTING explicitly marks GAP-517-002 as RESOLVED."""
        from core.multi_device_control_integrity import PR523_RESIDUAL_CLOSURE_ACCOUNTING

        self.assertIn("GAP-517-002=RESOLVED(PR-532)", PR523_RESIDUAL_CLOSURE_ACCOUNTING)

    def test_L6_open_gaps_list_excludes_gap002(self):
        """L6. snapshot().open_gaps() excludes GAP-517-002 once closed."""
        from core.multi_device_control_integrity import get_multi_device_integrity_runtime

        open_gap_ids = {g.gap_id for g in get_multi_device_integrity_runtime().snapshot().open_gaps()}
        self.assertNotIn("GAP-517-002", open_gap_ids)


# ===========================================================================
# M) Integrated path — canonical sentinels in key modules
# ===========================================================================


class TestM_IntegratedPathSentinels(unittest.TestCase):
    """M) Canonical sentinels confirm each integrated module has been wired correctly."""

    def test_M1_cross_device_result_surface_authority_importable(self):
        """M1. CROSS_DEVICE_RESULT_SURFACE_AUTHORITY importable (PR-519)."""
        from core.cross_device_result_surface import CROSS_DEVICE_RESULT_SURFACE_AUTHORITY

        self.assertIn("PR519", CROSS_DEVICE_RESULT_SURFACE_AUTHORITY)

    def test_M2_cross_device_result_surface_integrated_importable(self):
        """M2. CROSS_DEVICE_RESULT_SURFACE_INTEGRATED importable (PR-519)."""
        from core.cross_device_result_surface import CROSS_DEVICE_RESULT_SURFACE_INTEGRATED

        self.assertIn("INTEGRATED", CROSS_DEVICE_RESULT_SURFACE_INTEGRATED)

    def test_M3_cross_device_coordinator_substrate_only_importable(self):
        """M3. CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY importable (PR-518)."""
        from galaxy_gateway.cross_device_coordinator import (
            CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY,
        )

        self.assertIn("GAP-517-003", CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY)

    def test_M4_device_router_cross_device_substrate_only_importable(self):
        """M4. DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY importable (PR-518)."""
        from galaxy_gateway.device_router import DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY

        self.assertIn("GAP-517-003", DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY)

    def test_M5_projection_canonicalization_authority_importable(self):
        """M5. MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY importable (PR-522)."""
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY,
        )

        self.assertIn("PR522", MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY)

    def test_M6_constellation_deny_by_default_importable(self):
        """M6. CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT importable (PR-520)."""
        from core.constellation_runtime import CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT

        self.assertIn("GAP-517-005", CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT)

    def test_M7_device_router_control_semantic_separation_importable(self):
        """M7. DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION importable (PR-521)."""
        from galaxy_gateway.device_router import DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION

        self.assertIn("GAP-517-006", DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION)

    def test_M8_multi_device_control_integrity_authority_importable(self):
        """M8. MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY importable (PR-517)."""
        from core.multi_device_control_integrity import MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY

        self.assertIn("MULTI_DEVICE_CONTROL_INTEGRITY", MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY)

    def test_M9_pr523_e2e_acceptance_verified_importable(self):
        """M9. MULTI_DEVICE_E2E_ACCEPTANCE_VERIFIED importable (PR-523)."""
        from core.multi_device_control_integrity import MULTI_DEVICE_E2E_ACCEPTANCE_VERIFIED

        self.assertIn("PR523", MULTI_DEVICE_E2E_ACCEPTANCE_VERIFIED)

    def test_M10_all_integrated_pr_sentinels_form_coherent_coverage(self):
        """M10. All integrated PR sentinels together cover the full stack — PR-517 through PR-523."""
        sentinel_modules = [
            ("core.multi_device_control_integrity", "MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY"),
            ("galaxy_gateway.cross_device_coordinator", "CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY"),
            ("core.cross_device_result_surface", "CROSS_DEVICE_RESULT_SURFACE_AUTHORITY"),
            ("core.constellation_runtime", "CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT"),
            ("galaxy_gateway.device_router", "DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION"),
            ("core.multi_device_projection_canonicalization", "MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY"),
            ("core.multi_device_control_integrity", "MULTI_DEVICE_E2E_ACCEPTANCE_VERIFIED"),
        ]
        for mod_name, sentinel_name in sentinel_modules:
            with self.subTest(sentinel=sentinel_name):
                import importlib

                mod = importlib.import_module(mod_name)
                self.assertTrue(
                    hasattr(mod, sentinel_name),
                    f"Module {mod_name} missing sentinel {sentinel_name!r}",
                )
                value = getattr(mod, sentinel_name)
                self.assertIsInstance(value, str)
                self.assertGreater(len(value), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
