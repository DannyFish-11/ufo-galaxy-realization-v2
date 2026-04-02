#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr517_cross_device_control_integrity.py
====================================================
PR-517 — Cross-Device / Multi-Device Control Integrity Audit: Tests.

Validates that:
* All authority, policy, and integration sentinels are importable and
  contain the expected vocabulary.
* All enum types cover the required values.
* All dataclasses have correct structure, to_dict() serialisation, and
  from_dict() round-trip fidelity.
* Factory helpers derive is_canonical / is_consistent / is_semantically_clear
  correctly from their inputs.
* record_integrity_event() correctly routes records to the runtime singleton
  and emits the correct log warnings.
* The singleton management (get / reset) works correctly.
* The residual gap catalog is complete and has the expected structure.
* build_integrity_snapshot() produces a correct MultiDeviceIntegritySnapshot.
* Ring-buffer overflow is handled correctly.

Test groups
-----------
 A)  Module structure — all __all__ symbols importable.
 B)  Authority sentinels — correct types and values.
 C)  Policy sentinels — vocabulary checks.
 D)  EntryUnificationKind enum — all required values present.
 E)  DispatchPathKind enum — all required values present.
 F)  FormationTruthConsistency enum — all required values present.
 G)  ControlSemanticKind enum — all required values present.
 H)  ResultSurfaceKind enum — all required values present.
 I)  EntryUnificationRecord — structure and to_dict/from_dict round-trip.
 J)  DispatchAuthorityRecord — structure and to_dict/from_dict round-trip.
 K)  FormationTruthRecord — structure and to_dict/from_dict round-trip.
 L)  ControlSemanticRecord — structure and to_dict/from_dict round-trip.
 M)  ResultSurfaceRecord — structure and to_dict/from_dict round-trip.
 N)  ResidualIntegrityGap — structure and to_dict.
 O)  MultiDeviceIntegritySnapshot — structure and to_dict.
 P)  build_entry_unification_record — canonical / legacy derivation.
 Q)  build_dispatch_authority_record — canonical derivation.
 R)  build_formation_truth_record — consistency derivation.
 S)  build_control_semantic_record — semantic clarity derivation.
 T)  build_result_surface_record — surface kind derivation.
 U)  record_integrity_event — routes to correct ring buffers.
 V)  record_integrity_event — emits legacy warnings.
 W)  Singleton management — get / reset.
 X)  MultiDeviceControlIntegrityRuntime — ring-buffer overflow.
 Y)  MultiDeviceControlIntegrityRuntime — counters correct.
 Z)  get_residual_integrity_gaps — catalog completeness.
 AA) build_integrity_snapshot — snapshot structure.
 BB) Snapshot — open_gaps() and gaps_by_area() helpers.
 CC) Device entry unification — canonical entry path identified correctly.
 DD) Cross-device dispatch — single dispatch authority verified.
 EE) Formation truth — consistency check with eligible / ineligible members.
 FF) Control semantics — local vs remote dispatch vs takeover distinction.
 GG) Result surface — full canonical surface vs partial vs transport-local.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from typing import Any, Dict, List
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helper: reset singleton between tests
# ---------------------------------------------------------------------------

def _reset():
    from core.multi_device_control_integrity import reset_multi_device_integrity_runtime
    reset_multi_device_integrity_runtime()


# ===========================================================================
# Test groups
# ===========================================================================


class TestA_ModuleStructure(unittest.TestCase):
    """A) All __all__ symbols are importable from the module."""

    def test_all_symbols_importable(self):
        import core.multi_device_control_integrity as m
        for name in m.__all__:
            self.assertTrue(
                hasattr(m, name),
                f"__all__ symbol {name!r} not found in module",
            )

    def test_module_docstring_present(self):
        import core.multi_device_control_integrity as m
        self.assertIsNotNone(m.__doc__)
        self.assertIn("PR-517", m.__doc__)


class TestB_AuthoritySentinels(unittest.TestCase):
    """B) Authority sentinels exist with correct types and values."""

    def test_main_authority_string(self):
        from core.multi_device_control_integrity import MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY
        self.assertIsInstance(MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY, str)
        self.assertIn("MULTI_DEVICE_CONTROL_INTEGRITY", MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY)

    def test_layer_position_is_int(self):
        from core.multi_device_control_integrity import MULTI_DEVICE_CONTROL_INTEGRITY_LAYER_POSITION
        self.assertIsInstance(MULTI_DEVICE_CONTROL_INTEGRITY_LAYER_POSITION, int)
        self.assertGreater(MULTI_DEVICE_CONTROL_INTEGRITY_LAYER_POSITION, 0)

    def test_integrated_sentinel_string(self):
        from core.multi_device_control_integrity import MULTI_DEVICE_CONTROL_INTEGRITY_INTEGRATED
        self.assertIsInstance(MULTI_DEVICE_CONTROL_INTEGRITY_INTEGRATED, str)
        self.assertIn("INTEGRATED", MULTI_DEVICE_CONTROL_INTEGRITY_INTEGRATED)

    def test_entry_unification_authority(self):
        from core.multi_device_control_integrity import MULTI_DEVICE_ENTRY_UNIFICATION_AUTHORITY
        self.assertIsInstance(MULTI_DEVICE_ENTRY_UNIFICATION_AUTHORITY, str)
        self.assertIn("CommandRouter", MULTI_DEVICE_ENTRY_UNIFICATION_AUTHORITY)

    def test_dispatch_authority_sentinel(self):
        from core.multi_device_control_integrity import SINGLE_CROSS_DEVICE_DISPATCH_AUTHORITY
        self.assertIsInstance(SINGLE_CROSS_DEVICE_DISPATCH_AUTHORITY, str)
        self.assertIn("CommandRouter", SINGLE_CROSS_DEVICE_DISPATCH_AUTHORITY)

    def test_formation_truth_authority(self):
        from core.multi_device_control_integrity import DEVICE_FORMATION_TRUTH_AUTHORITY
        self.assertIsInstance(DEVICE_FORMATION_TRUTH_AUTHORITY, str)
        self.assertIn("DeviceFormationGroup", DEVICE_FORMATION_TRUTH_AUTHORITY)

    def test_control_semantic_authority(self):
        from core.multi_device_control_integrity import CONTROL_SEMANTIC_SEPARATION_AUTHORITY
        self.assertIsInstance(CONTROL_SEMANTIC_SEPARATION_AUTHORITY, str)
        self.assertIn("source_device_id", CONTROL_SEMANTIC_SEPARATION_AUTHORITY)

    def test_result_surface_authority(self):
        from core.multi_device_control_integrity import RESULT_CANONICAL_SURFACE_AUTHORITY
        self.assertIsInstance(RESULT_CANONICAL_SURFACE_AUTHORITY, str)
        self.assertIn("ResultEnvelope", RESULT_CANONICAL_SURFACE_AUTHORITY)


class TestC_PolicySentinels(unittest.TestCase):
    """C) Policy sentinels contain required vocabulary."""

    def test_entry_convergence_policy(self):
        from core.multi_device_control_integrity import (
            ALL_DEVICE_ENTRY_CONVERGES_ON_COMMAND_ROUTER_POLICY,
        )
        self.assertIn("CommandRouter", ALL_DEVICE_ENTRY_CONVERGES_ON_COMMAND_ROUTER_POLICY)
        self.assertIn("TaskEnvelope", ALL_DEVICE_ENTRY_CONVERGES_ON_COMMAND_ROUTER_POLICY)

    def test_no_parallel_dispatch_policy(self):
        from core.multi_device_control_integrity import NO_PARALLEL_CROSS_DEVICE_DISPATCH_POLICY
        self.assertIn("CommandRouter", NO_PARALLEL_CROSS_DEVICE_DISPATCH_POLICY)
        self.assertIn("CrossDeviceCoordinator", NO_PARALLEL_CROSS_DEVICE_DISPATCH_POLICY)

    def test_formation_truth_policy(self):
        from core.multi_device_control_integrity import FORMATION_TRUTH_SINGLE_SOURCE_POLICY
        self.assertIn("DeviceFormationGroup", FORMATION_TRUTH_SINGLE_SOURCE_POLICY)

    def test_source_target_separation_policy(self):
        from core.multi_device_control_integrity import SOURCE_TARGET_SEMANTIC_SEPARATION_POLICY
        self.assertIn("source_device_id", SOURCE_TARGET_SEMANTIC_SEPARATION_POLICY)
        self.assertIn("target_device_id", SOURCE_TARGET_SEMANTIC_SEPARATION_POLICY)

    def test_result_canonical_policy(self):
        from core.multi_device_control_integrity import (
            CROSS_DEVICE_RESULT_SURFACES_CANONICALLY_POLICY,
        )
        self.assertIn("ResultEnvelope", CROSS_DEVICE_RESULT_SURFACES_CANONICALLY_POLICY)
        self.assertIn("OperatorSurface", CROSS_DEVICE_RESULT_SURFACES_CANONICALLY_POLICY)


class TestD_EntryUnificationKind(unittest.TestCase):
    """D) EntryUnificationKind enum covers required values."""

    def test_canonical_present(self):
        from core.multi_device_control_integrity import EntryUnificationKind
        self.assertIn("canonical", EntryUnificationKind._value2member_map_)

    def test_legacy_direct_dispatch_present(self):
        from core.multi_device_control_integrity import EntryUnificationKind
        self.assertIn("legacy_direct_dispatch", EntryUnificationKind._value2member_map_)

    def test_legacy_coordinator_bypass_present(self):
        from core.multi_device_control_integrity import EntryUnificationKind
        self.assertIn("legacy_coordinator_bypass", EntryUnificationKind._value2member_map_)

    def test_legacy_route_bypass_present(self):
        from core.multi_device_control_integrity import EntryUnificationKind
        self.assertIn("legacy_route_bypass", EntryUnificationKind._value2member_map_)

    def test_unknown_present(self):
        from core.multi_device_control_integrity import EntryUnificationKind
        self.assertIn("unknown", EntryUnificationKind._value2member_map_)

    def test_is_str_subclass(self):
        from core.multi_device_control_integrity import EntryUnificationKind
        self.assertTrue(issubclass(EntryUnificationKind, str))


class TestE_DispatchPathKind(unittest.TestCase):
    """E) DispatchPathKind enum covers required values."""

    def test_command_router_canonical_present(self):
        from core.multi_device_control_integrity import DispatchPathKind
        self.assertIn("command_router_canonical", DispatchPathKind._value2member_map_)

    def test_device_router_substrate_present(self):
        from core.multi_device_control_integrity import DispatchPathKind
        self.assertIn("device_router_substrate", DispatchPathKind._value2member_map_)

    def test_coordinator_legacy_present(self):
        from core.multi_device_control_integrity import DispatchPathKind
        self.assertIn("coordinator_legacy", DispatchPathKind._value2member_map_)

    def test_parallel_legacy_present(self):
        from core.multi_device_control_integrity import DispatchPathKind
        self.assertIn("parallel_legacy", DispatchPathKind._value2member_map_)

    def test_unknown_present(self):
        from core.multi_device_control_integrity import DispatchPathKind
        self.assertIn("unknown", DispatchPathKind._value2member_map_)


class TestF_FormationTruthConsistency(unittest.TestCase):
    """F) FormationTruthConsistency enum covers required values."""

    def test_consistent_present(self):
        from core.multi_device_control_integrity import FormationTruthConsistency
        self.assertIn("consistent", FormationTruthConsistency._value2member_map_)

    def test_participation_drift_present(self):
        from core.multi_device_control_integrity import FormationTruthConsistency
        self.assertIn("participation_drift", FormationTruthConsistency._value2member_map_)

    def test_readiness_drift_present(self):
        from core.multi_device_control_integrity import FormationTruthConsistency
        self.assertIn("readiness_drift", FormationTruthConsistency._value2member_map_)

    def test_formation_missing_present(self):
        from core.multi_device_control_integrity import FormationTruthConsistency
        self.assertIn("formation_missing", FormationTruthConsistency._value2member_map_)

    def test_unknown_present(self):
        from core.multi_device_control_integrity import FormationTruthConsistency
        self.assertIn("unknown", FormationTruthConsistency._value2member_map_)


class TestG_ControlSemanticKind(unittest.TestCase):
    """G) ControlSemanticKind enum covers required values."""

    def test_local_execution_present(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        self.assertIn("local_execution", ControlSemanticKind._value2member_map_)

    def test_remote_dispatch_present(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        self.assertIn("remote_dispatch", ControlSemanticKind._value2member_map_)

    def test_takeover_present(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        self.assertIn("takeover", ControlSemanticKind._value2member_map_)

    def test_hybrid_present(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        self.assertIn("hybrid", ControlSemanticKind._value2member_map_)

    def test_unknown_present(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        self.assertIn("unknown", ControlSemanticKind._value2member_map_)


class TestH_ResultSurfaceKind(unittest.TestCase):
    """H) ResultSurfaceKind enum covers required values."""

    def test_canonical_full_present(self):
        from core.multi_device_control_integrity import ResultSurfaceKind
        self.assertIn("canonical_full", ResultSurfaceKind._value2member_map_)

    def test_canonical_partial_present(self):
        from core.multi_device_control_integrity import ResultSurfaceKind
        self.assertIn("canonical_partial", ResultSurfaceKind._value2member_map_)

    def test_transport_local_only_present(self):
        from core.multi_device_control_integrity import ResultSurfaceKind
        self.assertIn("transport_local_only", ResultSurfaceKind._value2member_map_)

    def test_coordinator_only_present(self):
        from core.multi_device_control_integrity import ResultSurfaceKind
        self.assertIn("coordinator_only", ResultSurfaceKind._value2member_map_)

    def test_unknown_present(self):
        from core.multi_device_control_integrity import ResultSurfaceKind
        self.assertIn("unknown", ResultSurfaceKind._value2member_map_)


class TestI_EntryUnificationRecord(unittest.TestCase):
    """I) EntryUnificationRecord structure and round-trip."""

    def test_default_construction(self):
        from core.multi_device_control_integrity import EntryUnificationRecord, EntryUnificationKind
        r = EntryUnificationRecord()
        self.assertIsInstance(r.record_id, str)
        self.assertEqual(r.entry_kind, EntryUnificationKind.UNKNOWN)
        self.assertFalse(r.is_canonical)

    def test_to_dict_keys(self):
        from core.multi_device_control_integrity import EntryUnificationRecord
        r = EntryUnificationRecord(task_id="t1", source_device_id="dev1")
        d = r.to_dict()
        for key in ("record_id", "task_id", "trace_id", "source_device_id",
                    "entry_kind", "is_canonical", "entry_point", "reasons",
                    "timestamp", "extra"):
            self.assertIn(key, d, f"key {key!r} missing from to_dict()")

    def test_to_dict_json_serialisable(self):
        from core.multi_device_control_integrity import (
            EntryUnificationRecord, EntryUnificationKind,
        )
        r = EntryUnificationRecord(
            task_id="t1", source_device_id="dev1",
            entry_kind=EntryUnificationKind.CANONICAL,
            reasons=["via_command_router"],
        )
        json.dumps(r.to_dict())  # must not raise

    def test_from_dict_round_trip(self):
        from core.multi_device_control_integrity import (
            EntryUnificationRecord, EntryUnificationKind,
        )
        r = EntryUnificationRecord(
            task_id="t1", source_device_id="dev1",
            entry_kind=EntryUnificationKind.LEGACY_COORDINATOR_BYPASS,
            is_canonical=False,
            entry_point="core.routes.devices.cross_device_task",
        )
        r2 = EntryUnificationRecord.from_dict(r.to_dict())
        self.assertEqual(r.task_id, r2.task_id)
        self.assertEqual(r.entry_kind, r2.entry_kind)
        self.assertEqual(r.entry_point, r2.entry_point)
        self.assertEqual(r.source_device_id, r2.source_device_id)


class TestJ_DispatchAuthorityRecord(unittest.TestCase):
    """J) DispatchAuthorityRecord structure and round-trip."""

    def test_default_construction(self):
        from core.multi_device_control_integrity import DispatchAuthorityRecord, DispatchPathKind
        r = DispatchAuthorityRecord()
        self.assertIsInstance(r.record_id, str)
        self.assertEqual(r.dispatch_path, DispatchPathKind.UNKNOWN)
        self.assertFalse(r.is_canonical)

    def test_to_dict_keys(self):
        from core.multi_device_control_integrity import DispatchAuthorityRecord
        r = DispatchAuthorityRecord(task_id="t1")
        d = r.to_dict()
        for key in ("record_id", "task_id", "trace_id", "source_device_id",
                    "target_device_ids", "dispatch_path", "is_canonical",
                    "dispatcher_module", "reasons", "timestamp", "extra"):
            self.assertIn(key, d)

    def test_json_serialisable(self):
        from core.multi_device_control_integrity import (
            DispatchAuthorityRecord, DispatchPathKind,
        )
        r = DispatchAuthorityRecord(
            task_id="t1",
            target_device_ids=["dev2", "dev3"],
            dispatch_path=DispatchPathKind.COMMAND_ROUTER_CANONICAL,
        )
        json.dumps(r.to_dict())

    def test_from_dict_round_trip(self):
        from core.multi_device_control_integrity import (
            DispatchAuthorityRecord, DispatchPathKind,
        )
        r = DispatchAuthorityRecord(
            task_id="t2",
            source_device_id="src",
            target_device_ids=["tgt1", "tgt2"],
            dispatch_path=DispatchPathKind.COORDINATOR_LEGACY,
            is_canonical=False,
        )
        r2 = DispatchAuthorityRecord.from_dict(r.to_dict())
        self.assertEqual(r.task_id, r2.task_id)
        self.assertEqual(r.dispatch_path, r2.dispatch_path)
        self.assertEqual(r.target_device_ids, r2.target_device_ids)


class TestK_FormationTruthRecord(unittest.TestCase):
    """K) FormationTruthRecord structure and round-trip."""

    def test_default_construction(self):
        from core.multi_device_control_integrity import (
            FormationTruthRecord, FormationTruthConsistency,
        )
        r = FormationTruthRecord()
        self.assertEqual(r.consistency, FormationTruthConsistency.UNKNOWN)
        self.assertFalse(r.is_consistent)

    def test_to_dict_keys(self):
        from core.multi_device_control_integrity import FormationTruthRecord
        r = FormationTruthRecord(task_id="t1", formation_id="f1")
        d = r.to_dict()
        for key in ("record_id", "task_id", "trace_id", "formation_id",
                    "consistency", "is_consistent", "member_device_ids",
                    "ineligible_members", "drift_reasons", "source_device_id",
                    "primary_device_id", "timestamp", "extra"):
            self.assertIn(key, d)

    def test_from_dict_round_trip(self):
        from core.multi_device_control_integrity import (
            FormationTruthRecord, FormationTruthConsistency,
        )
        r = FormationTruthRecord(
            task_id="t3",
            formation_id="form-abc",
            consistency=FormationTruthConsistency.PARTICIPATION_DRIFT,
            member_device_ids=["dev1", "dev2"],
            ineligible_members=["dev2"],
            drift_reasons=["dev2 not orchestration_eligible"],
        )
        r2 = FormationTruthRecord.from_dict(r.to_dict())
        self.assertEqual(r.formation_id, r2.formation_id)
        self.assertEqual(r.consistency, r2.consistency)
        self.assertEqual(r.ineligible_members, r2.ineligible_members)


class TestL_ControlSemanticRecord(unittest.TestCase):
    """L) ControlSemanticRecord structure and round-trip."""

    def test_default_construction(self):
        from core.multi_device_control_integrity import (
            ControlSemanticRecord, ControlSemanticKind,
        )
        r = ControlSemanticRecord()
        self.assertEqual(r.control_kind, ControlSemanticKind.UNKNOWN)
        self.assertFalse(r.is_semantically_clear)

    def test_to_dict_keys(self):
        from core.multi_device_control_integrity import ControlSemanticRecord
        r = ControlSemanticRecord(task_id="t1")
        d = r.to_dict()
        for key in ("record_id", "task_id", "trace_id", "source_device_id",
                    "target_device_id", "control_kind", "is_local",
                    "is_remote_dispatch", "is_takeover", "is_semantically_clear",
                    "ambiguity_reasons", "timestamp", "extra"):
            self.assertIn(key, d)

    def test_from_dict_round_trip(self):
        from core.multi_device_control_integrity import (
            ControlSemanticRecord, ControlSemanticKind,
        )
        r = ControlSemanticRecord(
            task_id="t4",
            source_device_id="phone",
            target_device_id="desktop",
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
            is_remote_dispatch=True,
            is_semantically_clear=True,
        )
        r2 = ControlSemanticRecord.from_dict(r.to_dict())
        self.assertEqual(r.source_device_id, r2.source_device_id)
        self.assertEqual(r.target_device_id, r2.target_device_id)
        self.assertEqual(r.control_kind, r2.control_kind)


class TestM_ResultSurfaceRecord(unittest.TestCase):
    """M) ResultSurfaceRecord structure and round-trip."""

    def test_default_construction(self):
        from core.multi_device_control_integrity import ResultSurfaceRecord, ResultSurfaceKind
        r = ResultSurfaceRecord()
        self.assertEqual(r.surface_kind, ResultSurfaceKind.UNKNOWN)
        self.assertFalse(r.is_canonically_surfaced)

    def test_to_dict_keys(self):
        from core.multi_device_control_integrity import ResultSurfaceRecord
        r = ResultSurfaceRecord(task_id="t1")
        d = r.to_dict()
        for key in ("record_id", "task_id", "trace_id", "source_device_id",
                    "target_device_ids", "surface_kind", "is_canonically_surfaced",
                    "result_envelope_produced", "operator_surface_updated",
                    "task_graph_updated", "replay_foundation_updated",
                    "projection_updated", "surface_gap_reasons", "timestamp", "extra"):
            self.assertIn(key, d)

    def test_from_dict_round_trip(self):
        from core.multi_device_control_integrity import ResultSurfaceRecord, ResultSurfaceKind
        r = ResultSurfaceRecord(
            task_id="t5",
            surface_kind=ResultSurfaceKind.CANONICAL_FULL,
            is_canonically_surfaced=True,
            result_envelope_produced=True,
            operator_surface_updated=True,
        )
        r2 = ResultSurfaceRecord.from_dict(r.to_dict())
        self.assertEqual(r.surface_kind, r2.surface_kind)
        self.assertTrue(r2.result_envelope_produced)


class TestN_ResidualIntegrityGap(unittest.TestCase):
    """N) ResidualIntegrityGap structure and to_dict."""

    def test_default_construction(self):
        from core.multi_device_control_integrity import ResidualIntegrityGap
        g = ResidualIntegrityGap()
        self.assertFalse(g.is_resolved)

    def test_to_dict_keys(self):
        from core.multi_device_control_integrity import ResidualIntegrityGap
        g = ResidualIntegrityGap(
            gap_id="GAP-517-001",
            area="entry_unification",
            severity="HIGH",
            description="test gap",
        )
        d = g.to_dict()
        for key in ("gap_id", "area", "severity", "description",
                    "affected_modules", "recommended_action",
                    "is_resolved", "resolution_note"):
            self.assertIn(key, d)

    def test_json_serialisable(self):
        from core.multi_device_control_integrity import ResidualIntegrityGap
        g = ResidualIntegrityGap(gap_id="GAP-517-001", area="entry_unification")
        json.dumps(g.to_dict())


class TestO_MultiDeviceIntegritySnapshot(unittest.TestCase):
    """O) MultiDeviceIntegritySnapshot structure and to_dict."""

    def test_default_construction(self):
        from core.multi_device_control_integrity import MultiDeviceIntegritySnapshot
        s = MultiDeviceIntegritySnapshot()
        self.assertIsInstance(s.snapshot_id, str)
        self.assertEqual(s.canonical_entry_count, 0)

    def test_to_dict_keys(self):
        from core.multi_device_control_integrity import MultiDeviceIntegritySnapshot
        s = MultiDeviceIntegritySnapshot()
        d = s.to_dict()
        for key in ("snapshot_id", "recent_entry_records",
                    "recent_dispatch_records", "recent_formation_records",
                    "recent_control_semantic_records",
                    "recent_result_surface_records", "residual_gaps",
                    "canonical_entry_count", "legacy_entry_count",
                    "canonical_dispatch_count", "legacy_dispatch_count",
                    "timestamp", "authority"):
            self.assertIn(key, d)

    def test_authority_in_to_dict(self):
        from core.multi_device_control_integrity import (
            MultiDeviceIntegritySnapshot,
            MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY,
        )
        s = MultiDeviceIntegritySnapshot()
        self.assertEqual(s.to_dict()["authority"], MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY)


class TestP_BuildEntryUnificationRecord(unittest.TestCase):
    """P) build_entry_unification_record — canonical / legacy derivation."""

    def test_canonical_entry(self):
        from core.multi_device_control_integrity import (
            build_entry_unification_record, EntryUnificationKind,
        )
        r = build_entry_unification_record(
            task_id="t1",
            source_device_id="dev1",
            entry_kind=EntryUnificationKind.CANONICAL,
        )
        self.assertTrue(r.is_canonical)
        self.assertEqual(r.entry_kind, EntryUnificationKind.CANONICAL)

    def test_legacy_coordinator_bypass(self):
        from core.multi_device_control_integrity import (
            build_entry_unification_record, EntryUnificationKind,
        )
        r = build_entry_unification_record(
            task_id="t2",
            source_device_id="dev1",
            entry_kind=EntryUnificationKind.LEGACY_COORDINATOR_BYPASS,
        )
        self.assertFalse(r.is_canonical)

    def test_legacy_route_bypass(self):
        from core.multi_device_control_integrity import (
            build_entry_unification_record, EntryUnificationKind,
        )
        r = build_entry_unification_record(
            entry_kind=EntryUnificationKind.LEGACY_ROUTE_BYPASS,
        )
        self.assertFalse(r.is_canonical)

    def test_unknown_not_canonical(self):
        from core.multi_device_control_integrity import (
            build_entry_unification_record, EntryUnificationKind,
        )
        r = build_entry_unification_record(
            entry_kind=EntryUnificationKind.UNKNOWN,
        )
        self.assertFalse(r.is_canonical)

    def test_reasons_propagated(self):
        from core.multi_device_control_integrity import (
            build_entry_unification_record, EntryUnificationKind,
        )
        r = build_entry_unification_record(
            entry_kind=EntryUnificationKind.CANONICAL,
            reasons=["via_command_router", "task_envelope_normalised"],
        )
        self.assertIn("via_command_router", r.reasons)


class TestQ_BuildDispatchAuthorityRecord(unittest.TestCase):
    """Q) build_dispatch_authority_record — canonical derivation."""

    def test_command_router_is_canonical(self):
        from core.multi_device_control_integrity import (
            build_dispatch_authority_record, DispatchPathKind,
        )
        r = build_dispatch_authority_record(
            task_id="t1",
            dispatch_path=DispatchPathKind.COMMAND_ROUTER_CANONICAL,
        )
        self.assertTrue(r.is_canonical)

    def test_device_router_substrate_not_canonical(self):
        from core.multi_device_control_integrity import (
            build_dispatch_authority_record, DispatchPathKind,
        )
        r = build_dispatch_authority_record(
            dispatch_path=DispatchPathKind.DEVICE_ROUTER_SUBSTRATE,
        )
        self.assertFalse(r.is_canonical)

    def test_coordinator_legacy_not_canonical(self):
        from core.multi_device_control_integrity import (
            build_dispatch_authority_record, DispatchPathKind,
        )
        r = build_dispatch_authority_record(
            dispatch_path=DispatchPathKind.COORDINATOR_LEGACY,
        )
        self.assertFalse(r.is_canonical)

    def test_target_device_ids_propagated(self):
        from core.multi_device_control_integrity import (
            build_dispatch_authority_record, DispatchPathKind,
        )
        r = build_dispatch_authority_record(
            task_id="t2",
            target_device_ids=["dev2", "dev3"],
            dispatch_path=DispatchPathKind.COMMAND_ROUTER_CANONICAL,
        )
        self.assertIn("dev2", r.target_device_ids)
        self.assertIn("dev3", r.target_device_ids)


class TestR_BuildFormationTruthRecord(unittest.TestCase):
    """R) build_formation_truth_record — consistency derivation."""

    def test_consistent_verdict(self):
        from core.multi_device_control_integrity import (
            build_formation_truth_record, FormationTruthConsistency,
        )
        r = build_formation_truth_record(
            task_id="t1",
            consistency=FormationTruthConsistency.CONSISTENT,
            member_device_ids=["dev1", "dev2"],
        )
        self.assertTrue(r.is_consistent)

    def test_participation_drift_not_consistent(self):
        from core.multi_device_control_integrity import (
            build_formation_truth_record, FormationTruthConsistency,
        )
        r = build_formation_truth_record(
            consistency=FormationTruthConsistency.PARTICIPATION_DRIFT,
            ineligible_members=["dev2"],
            drift_reasons=["dev2 not orchestration_eligible"],
        )
        self.assertFalse(r.is_consistent)
        self.assertIn("dev2", r.ineligible_members)

    def test_formation_missing_not_consistent(self):
        from core.multi_device_control_integrity import (
            build_formation_truth_record, FormationTruthConsistency,
        )
        r = build_formation_truth_record(
            consistency=FormationTruthConsistency.FORMATION_MISSING,
        )
        self.assertFalse(r.is_consistent)


class TestS_BuildControlSemanticRecord(unittest.TestCase):
    """S) build_control_semantic_record — semantic clarity derivation."""

    def test_local_execution_clear(self):
        from core.multi_device_control_integrity import (
            build_control_semantic_record, ControlSemanticKind,
        )
        r = build_control_semantic_record(
            task_id="t1",
            source_device_id="phone",
            target_device_id="phone",
            control_kind=ControlSemanticKind.LOCAL_EXECUTION,
        )
        self.assertTrue(r.is_local)
        self.assertTrue(r.is_semantically_clear)

    def test_remote_dispatch_clear(self):
        from core.multi_device_control_integrity import (
            build_control_semantic_record, ControlSemanticKind,
        )
        r = build_control_semantic_record(
            task_id="t1",
            source_device_id="phone",
            target_device_id="desktop",
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
        )
        self.assertTrue(r.is_remote_dispatch)
        self.assertTrue(r.is_semantically_clear)
        self.assertFalse(r.is_local)

    def test_takeover_flagged(self):
        from core.multi_device_control_integrity import (
            build_control_semantic_record, ControlSemanticKind,
        )
        r = build_control_semantic_record(
            source_device_id="phone",
            target_device_id="tablet",
            control_kind=ControlSemanticKind.TAKEOVER,
            is_takeover=True,
        )
        self.assertTrue(r.is_takeover)

    def test_unknown_not_clear(self):
        from core.multi_device_control_integrity import (
            build_control_semantic_record, ControlSemanticKind,
        )
        r = build_control_semantic_record(
            control_kind=ControlSemanticKind.UNKNOWN,
        )
        self.assertFalse(r.is_semantically_clear)

    def test_ambiguity_reasons_make_unclear(self):
        from core.multi_device_control_integrity import (
            build_control_semantic_record, ControlSemanticKind,
        )
        r = build_control_semantic_record(
            source_device_id="phone",
            target_device_id="desktop",
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
            ambiguity_reasons=["source_device_id inferred from context"],
        )
        self.assertFalse(r.is_semantically_clear)


class TestT_BuildResultSurfaceRecord(unittest.TestCase):
    """T) build_result_surface_record — surface kind derivation."""

    def test_full_canonical_when_all_surfaces_true(self):
        from core.multi_device_control_integrity import (
            build_result_surface_record, ResultSurfaceKind,
        )
        r = build_result_surface_record(
            task_id="t1",
            result_envelope_produced=True,
            operator_surface_updated=True,
            task_graph_updated=True,
            replay_foundation_updated=True,
        )
        self.assertEqual(r.surface_kind, ResultSurfaceKind.CANONICAL_FULL)
        self.assertTrue(r.is_canonically_surfaced)

    def test_partial_when_some_surfaces(self):
        from core.multi_device_control_integrity import (
            build_result_surface_record, ResultSurfaceKind,
        )
        r = build_result_surface_record(
            task_id="t2",
            result_envelope_produced=True,
            operator_surface_updated=False,
            task_graph_updated=False,
            replay_foundation_updated=False,
        )
        self.assertEqual(r.surface_kind, ResultSurfaceKind.CANONICAL_PARTIAL)
        self.assertFalse(r.is_canonically_surfaced)

    def test_transport_local_when_no_surfaces(self):
        from core.multi_device_control_integrity import (
            build_result_surface_record, ResultSurfaceKind,
        )
        r = build_result_surface_record(task_id="t3")
        self.assertEqual(r.surface_kind, ResultSurfaceKind.TRANSPORT_LOCAL_ONLY)
        self.assertFalse(r.is_canonically_surfaced)

    def test_target_device_ids_propagated(self):
        from core.multi_device_control_integrity import build_result_surface_record
        r = build_result_surface_record(
            task_id="t4",
            target_device_ids=["dev1", "dev2"],
        )
        self.assertIn("dev1", r.target_device_ids)


class TestU_RecordIntegrityEvent(unittest.TestCase):
    """U) record_integrity_event routes to correct ring buffers."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_entry_record_added(self):
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_entry_unification_record,
            EntryUnificationKind,
            get_multi_device_integrity_runtime,
        )
        r = build_entry_unification_record(
            task_id="t1", entry_kind=EntryUnificationKind.CANONICAL
        )
        record_integrity_event(entry_record=r)
        rt = get_multi_device_integrity_runtime()
        snap = rt.snapshot()
        self.assertEqual(len(snap.recent_entry_records), 1)

    def test_dispatch_record_added(self):
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_dispatch_authority_record,
            DispatchPathKind,
            get_multi_device_integrity_runtime,
        )
        r = build_dispatch_authority_record(
            task_id="t2", dispatch_path=DispatchPathKind.COORDINATOR_LEGACY
        )
        record_integrity_event(dispatch_record=r)
        rt = get_multi_device_integrity_runtime()
        snap = rt.snapshot()
        self.assertEqual(len(snap.recent_dispatch_records), 1)

    def test_formation_record_added(self):
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_formation_truth_record,
            FormationTruthConsistency,
            get_multi_device_integrity_runtime,
        )
        r = build_formation_truth_record(
            task_id="t3", consistency=FormationTruthConsistency.CONSISTENT
        )
        record_integrity_event(formation_record=r)
        snap = get_multi_device_integrity_runtime().snapshot()
        self.assertEqual(len(snap.recent_formation_records), 1)

    def test_control_record_added(self):
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_control_semantic_record,
            ControlSemanticKind,
            get_multi_device_integrity_runtime,
        )
        r = build_control_semantic_record(
            task_id="t4",
            source_device_id="dev1",
            target_device_id="dev2",
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
        )
        record_integrity_event(control_record=r)
        snap = get_multi_device_integrity_runtime().snapshot()
        self.assertEqual(len(snap.recent_control_semantic_records), 1)

    def test_result_record_added(self):
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_result_surface_record,
            get_multi_device_integrity_runtime,
        )
        r = build_result_surface_record(task_id="t5")
        record_integrity_event(result_record=r)
        snap = get_multi_device_integrity_runtime().snapshot()
        self.assertEqual(len(snap.recent_result_surface_records), 1)

    def test_multiple_records_same_call(self):
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_entry_unification_record,
            build_dispatch_authority_record,
            EntryUnificationKind,
            DispatchPathKind,
            get_multi_device_integrity_runtime,
        )
        record_integrity_event(
            entry_record=build_entry_unification_record(
                entry_kind=EntryUnificationKind.CANONICAL
            ),
            dispatch_record=build_dispatch_authority_record(
                dispatch_path=DispatchPathKind.COMMAND_ROUTER_CANONICAL
            ),
        )
        snap = get_multi_device_integrity_runtime().snapshot()
        self.assertEqual(len(snap.recent_entry_records), 1)
        self.assertEqual(len(snap.recent_dispatch_records), 1)


class TestV_RecordIntegrityEventWarnings(unittest.TestCase):
    """V) record_integrity_event emits legacy warnings."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_legacy_entry_warning(self):
        import logging
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_entry_unification_record,
            EntryUnificationKind,
        )
        with self.assertLogs("Galaxy.MultiDeviceControlIntegrity", level=logging.WARNING):
            record_integrity_event(
                entry_record=build_entry_unification_record(
                    entry_kind=EntryUnificationKind.LEGACY_COORDINATOR_BYPASS,
                    task_id="t1",
                )
            )

    def test_legacy_dispatch_warning(self):
        import logging
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_dispatch_authority_record,
            DispatchPathKind,
        )
        with self.assertLogs("Galaxy.MultiDeviceControlIntegrity", level=logging.WARNING):
            record_integrity_event(
                dispatch_record=build_dispatch_authority_record(
                    dispatch_path=DispatchPathKind.COORDINATOR_LEGACY,
                    task_id="t2",
                )
            )

    def test_formation_drift_warning(self):
        import logging
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_formation_truth_record,
            FormationTruthConsistency,
        )
        with self.assertLogs("Galaxy.MultiDeviceControlIntegrity", level=logging.WARNING):
            record_integrity_event(
                formation_record=build_formation_truth_record(
                    consistency=FormationTruthConsistency.PARTICIPATION_DRIFT,
                    task_id="t3",
                )
            )

    def test_result_surface_incomplete_warning(self):
        import logging
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_result_surface_record,
        )
        # A record with no surfaces triggers a warning
        with self.assertLogs("Galaxy.MultiDeviceControlIntegrity", level=logging.WARNING):
            record_integrity_event(
                result_record=build_result_surface_record(task_id="t4")
            )

    def test_canonical_entry_no_warning(self):
        """No warning emitted for canonical entries."""
        import logging
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_entry_unification_record,
            EntryUnificationKind,
        )
        # Should not raise (no WARNING logs expected)
        logger = logging.getLogger("Galaxy.MultiDeviceControlIntegrity")
        with self.assertRaises(AssertionError):
            # assertLogs will raise AssertionError if no logs are emitted —
            # that is exactly what we want to happen for canonical entries.
            with self.assertLogs("Galaxy.MultiDeviceControlIntegrity", level=logging.WARNING):
                record_integrity_event(
                    entry_record=build_entry_unification_record(
                        entry_kind=EntryUnificationKind.CANONICAL,
                        task_id="t5",
                    )
                )


class TestW_SingletonManagement(unittest.TestCase):
    """W) Singleton management — get / reset."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_get_returns_same_instance(self):
        from core.multi_device_control_integrity import get_multi_device_integrity_runtime
        rt1 = get_multi_device_integrity_runtime()
        rt2 = get_multi_device_integrity_runtime()
        self.assertIs(rt1, rt2)

    def test_reset_clears_instance(self):
        from core.multi_device_control_integrity import (
            get_multi_device_integrity_runtime,
            reset_multi_device_integrity_runtime,
        )
        rt1 = get_multi_device_integrity_runtime()
        reset_multi_device_integrity_runtime()
        rt2 = get_multi_device_integrity_runtime()
        self.assertIsNot(rt1, rt2)

    def test_reset_clears_records(self):
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_entry_unification_record,
            EntryUnificationKind,
            get_multi_device_integrity_runtime,
            reset_multi_device_integrity_runtime,
        )
        record_integrity_event(
            entry_record=build_entry_unification_record(
                entry_kind=EntryUnificationKind.CANONICAL
            )
        )
        reset_multi_device_integrity_runtime()
        snap = get_multi_device_integrity_runtime().snapshot()
        self.assertEqual(len(snap.recent_entry_records), 0)


class TestX_RingBufferOverflow(unittest.TestCase):
    """X) Ring-buffer overflow is handled correctly (no crash, old entries dropped)."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_entry_overflow_no_crash(self):
        from core.multi_device_control_integrity import (
            MultiDeviceControlIntegrityRuntime,
            build_entry_unification_record,
            EntryUnificationKind,
        )
        rt = MultiDeviceControlIntegrityRuntime(max_records=5)
        for i in range(10):
            rt.append_entry(
                build_entry_unification_record(
                    task_id=f"t{i}",
                    entry_kind=EntryUnificationKind.CANONICAL,
                )
            )
        snap = rt.snapshot()
        self.assertLessEqual(len(snap.recent_entry_records), 5)

    def test_dispatch_overflow_no_crash(self):
        from core.multi_device_control_integrity import (
            MultiDeviceControlIntegrityRuntime,
            build_dispatch_authority_record,
            DispatchPathKind,
        )
        rt = MultiDeviceControlIntegrityRuntime(max_records=3)
        for i in range(6):
            rt.append_dispatch(
                build_dispatch_authority_record(
                    task_id=f"t{i}",
                    dispatch_path=DispatchPathKind.COORDINATOR_LEGACY,
                )
            )
        snap = rt.snapshot()
        self.assertLessEqual(len(snap.recent_dispatch_records), 3)


class TestY_Counters(unittest.TestCase):
    """Y) Canonical / legacy counters are correct."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_entry_canonical_counter(self):
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_entry_unification_record,
            EntryUnificationKind,
            get_multi_device_integrity_runtime,
        )
        for _ in range(3):
            record_integrity_event(
                entry_record=build_entry_unification_record(
                    entry_kind=EntryUnificationKind.CANONICAL
                )
            )
        record_integrity_event(
            entry_record=build_entry_unification_record(
                entry_kind=EntryUnificationKind.LEGACY_ROUTE_BYPASS
            )
        )
        snap = get_multi_device_integrity_runtime().snapshot()
        self.assertEqual(snap.canonical_entry_count, 3)
        self.assertEqual(snap.legacy_entry_count, 1)

    def test_dispatch_canonical_counter(self):
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_dispatch_authority_record,
            DispatchPathKind,
            get_multi_device_integrity_runtime,
        )
        record_integrity_event(
            dispatch_record=build_dispatch_authority_record(
                dispatch_path=DispatchPathKind.COMMAND_ROUTER_CANONICAL
            )
        )
        record_integrity_event(
            dispatch_record=build_dispatch_authority_record(
                dispatch_path=DispatchPathKind.COORDINATOR_LEGACY
            )
        )
        snap = get_multi_device_integrity_runtime().snapshot()
        self.assertEqual(snap.canonical_dispatch_count, 1)
        self.assertEqual(snap.legacy_dispatch_count, 1)


class TestZ_ResidualGapCatalog(unittest.TestCase):
    """Z) Residual gap catalog is complete and well-formed."""

    def test_get_residual_integrity_gaps_returns_list(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gaps = get_residual_integrity_gaps()
        self.assertIsInstance(gaps, list)
        self.assertGreater(len(gaps), 0)

    def test_all_gaps_have_required_fields(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        for gap in get_residual_integrity_gaps():
            self.assertTrue(gap.gap_id, f"gap_id empty for gap {gap!r}")
            self.assertTrue(gap.area, f"area empty for gap {gap.gap_id!r}")
            self.assertTrue(gap.description, f"description empty for gap {gap.gap_id!r}")

    def test_entry_unification_area_has_gaps(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        entry_gaps = [g for g in get_residual_integrity_gaps() if g.area == "entry_unification"]
        self.assertGreater(len(entry_gaps), 0, "No entry_unification gaps in catalog")

    def test_dispatch_authority_area_has_gaps(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        dispatch_gaps = [
            g for g in get_residual_integrity_gaps() if g.area == "dispatch_authority"
        ]
        self.assertGreater(len(dispatch_gaps), 0, "No dispatch_authority gaps in catalog")

    def test_formation_truth_area_has_gaps(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        formation_gaps = [
            g for g in get_residual_integrity_gaps() if g.area == "formation_truth"
        ]
        self.assertGreater(len(formation_gaps), 0, "No formation_truth gaps in catalog")

    def test_control_semantics_area_has_gaps(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        cs_gaps = [
            g for g in get_residual_integrity_gaps() if g.area == "control_semantics"
        ]
        self.assertGreater(len(cs_gaps), 0, "No control_semantics gaps in catalog")

    def test_result_surface_area_has_gaps(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        rs_gaps = [
            g for g in get_residual_integrity_gaps() if g.area == "result_surface"
        ]
        self.assertGreater(len(rs_gaps), 0, "No result_surface gaps in catalog")

    def test_gap_ids_stable(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gap_ids = [g.gap_id for g in get_residual_integrity_gaps()]
        self.assertIn("GAP-517-001", gap_ids)
        self.assertIn("GAP-517-003", gap_ids)
        self.assertIn("GAP-517-007", gap_ids)

    def test_all_gaps_json_serialisable(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        for gap in get_residual_integrity_gaps():
            json.dumps(gap.to_dict())


class TestAA_BuildIntegritySnapshot(unittest.TestCase):
    """AA) build_integrity_snapshot — snapshot structure."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_returns_snapshot_instance(self):
        from core.multi_device_control_integrity import (
            build_integrity_snapshot, MultiDeviceIntegritySnapshot,
        )
        snap = build_integrity_snapshot()
        self.assertIsInstance(snap, MultiDeviceIntegritySnapshot)

    def test_snapshot_has_residual_gaps(self):
        from core.multi_device_control_integrity import build_integrity_snapshot
        snap = build_integrity_snapshot()
        self.assertGreater(len(snap.residual_gaps), 0)

    def test_snapshot_json_serialisable(self):
        from core.multi_device_control_integrity import build_integrity_snapshot
        snap = build_integrity_snapshot()
        json.dumps(snap.to_dict())

    def test_snapshot_max_recent_respected(self):
        from core.multi_device_control_integrity import (
            record_integrity_event,
            build_entry_unification_record,
            EntryUnificationKind,
            build_integrity_snapshot,
        )
        for i in range(30):
            record_integrity_event(
                entry_record=build_entry_unification_record(
                    task_id=f"t{i}",
                    entry_kind=EntryUnificationKind.CANONICAL,
                )
            )
        snap = build_integrity_snapshot(max_recent=5)
        self.assertLessEqual(len(snap.recent_entry_records), 5)


class TestBB_SnapshotHelpers(unittest.TestCase):
    """BB) Snapshot open_gaps() and gaps_by_area() helpers."""

    def test_open_gaps_excludes_resolved(self):
        from core.multi_device_control_integrity import (
            MultiDeviceIntegritySnapshot, ResidualIntegrityGap,
        )
        s = MultiDeviceIntegritySnapshot(
            residual_gaps=[
                ResidualIntegrityGap(gap_id="G1", area="x", is_resolved=False),
                ResidualIntegrityGap(gap_id="G2", area="x", is_resolved=True),
            ]
        )
        open_gaps = s.open_gaps()
        self.assertEqual(len(open_gaps), 1)
        self.assertEqual(open_gaps[0].gap_id, "G1")

    def test_gaps_by_area_filter(self):
        from core.multi_device_control_integrity import (
            MultiDeviceIntegritySnapshot, ResidualIntegrityGap,
        )
        s = MultiDeviceIntegritySnapshot(
            residual_gaps=[
                ResidualIntegrityGap(gap_id="G1", area="entry_unification"),
                ResidualIntegrityGap(gap_id="G2", area="dispatch_authority"),
                ResidualIntegrityGap(gap_id="G3", area="entry_unification"),
            ]
        )
        entry_gaps = s.gaps_by_area("entry_unification")
        self.assertEqual(len(entry_gaps), 2)


class TestCC_DeviceEntryUnification(unittest.TestCase):
    """CC) Device entry unification — canonical vs legacy entry identification."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_canonical_entry_via_command_router(self):
        """A flow through CommandRouter → TaskEnvelope should be classified canonical."""
        from core.multi_device_control_integrity import (
            build_entry_unification_record, EntryUnificationKind,
        )
        r = build_entry_unification_record(
            task_id="task-001",
            trace_id="trace-001",
            source_device_id="phone-001",
            entry_kind=EntryUnificationKind.CANONICAL,
            entry_point="core.command_router.CommandRouter.route_envelope",
            reasons=["via_canonical_task_envelope", "normalised_by_task_adapter"],
        )
        self.assertTrue(r.is_canonical)
        self.assertEqual(r.source_device_id, "phone-001")

    def test_legacy_route_cross_device_endpoint(self):
        """The /api/v1/devices/cross-device endpoint is a legacy bypass (GAP-517-001)."""
        from core.multi_device_control_integrity import (
            build_entry_unification_record, EntryUnificationKind,
        )
        r = build_entry_unification_record(
            task_id="task-002",
            source_device_id="tablet-001",
            entry_kind=EntryUnificationKind.LEGACY_COORDINATOR_BYPASS,
            entry_point="core.routes.devices.cross_device_task",
            reasons=["GAP-517-001: calls coordinator directly, bypasses CommandRouter"],
        )
        self.assertFalse(r.is_canonical)
        self.assertIn("GAP-517-001", r.reasons[0])

    def test_multiple_devices_can_enter_canonically(self):
        """Multiple different devices can all contribute canonical entry records."""
        from core.multi_device_control_integrity import (
            build_entry_unification_record, EntryUnificationKind,
            record_integrity_event, get_multi_device_integrity_runtime,
        )
        for device_id in ["phone-001", "tablet-002", "desktop-003"]:
            r = build_entry_unification_record(
                task_id=f"task-{device_id}",
                source_device_id=device_id,
                entry_kind=EntryUnificationKind.CANONICAL,
            )
            record_integrity_event(entry_record=r)
        snap = get_multi_device_integrity_runtime().snapshot()
        self.assertEqual(snap.canonical_entry_count, 3)
        self.assertEqual(snap.legacy_entry_count, 0)


class TestDD_CrossDeviceDispatchAuthority(unittest.TestCase):
    """DD) Cross-device dispatch — single dispatch authority verified."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_command_router_is_canonical_dispatcher(self):
        from core.multi_device_control_integrity import (
            build_dispatch_authority_record, DispatchPathKind,
        )
        r = build_dispatch_authority_record(
            task_id="task-010",
            trace_id="trace-010",
            source_device_id="phone-001",
            target_device_ids=["desktop-001", "tablet-001"],
            dispatch_path=DispatchPathKind.COMMAND_ROUTER_CANONICAL,
            dispatcher_module="core.command_router.CommandRouter",
        )
        self.assertTrue(r.is_canonical)

    def test_cross_device_coordinator_is_legacy(self):
        """Calling coordinator directly is not canonical (GAP-517-003)."""
        from core.multi_device_control_integrity import (
            build_dispatch_authority_record, DispatchPathKind,
        )
        r = build_dispatch_authority_record(
            task_id="task-011",
            source_device_id="phone-001",
            target_device_ids=["desktop-001"],
            dispatch_path=DispatchPathKind.COORDINATOR_LEGACY,
            dispatcher_module="galaxy_gateway.cross_device_coordinator.CrossDeviceCoordinator",
            reasons=["GAP-517-003: direct coordinator call bypasses CommandRouter"],
        )
        self.assertFalse(r.is_canonical)
        self.assertEqual(r.dispatch_path, DispatchPathKind.COORDINATOR_LEGACY)

    def test_device_router_substrate_not_independent_authority(self):
        """DeviceRouter as substrate is not canonical dispatch authority."""
        from core.multi_device_control_integrity import (
            build_dispatch_authority_record, DispatchPathKind,
        )
        r = build_dispatch_authority_record(
            task_id="task-012",
            dispatch_path=DispatchPathKind.DEVICE_ROUTER_SUBSTRATE,
            dispatcher_module="galaxy_gateway.device_router.DeviceRouter",
            reasons=["substrate only; not authoritative as independent dispatcher"],
        )
        self.assertFalse(r.is_canonical)


class TestEE_FormationTruth(unittest.TestCase):
    """EE) Formation truth — consistency check with eligible / ineligible members."""

    def test_consistent_formation(self):
        from core.multi_device_control_integrity import (
            build_formation_truth_record, FormationTruthConsistency,
        )
        r = build_formation_truth_record(
            task_id="task-020",
            formation_id="form-abc",
            consistency=FormationTruthConsistency.CONSISTENT,
            member_device_ids=["phone-001", "desktop-001"],
            source_device_id="phone-001",
            primary_device_id="desktop-001",
        )
        self.assertTrue(r.is_consistent)
        self.assertEqual(len(r.ineligible_members), 0)

    def test_participation_drift_detected(self):
        from core.multi_device_control_integrity import (
            build_formation_truth_record, FormationTruthConsistency,
        )
        r = build_formation_truth_record(
            task_id="task-021",
            formation_id="form-def",
            consistency=FormationTruthConsistency.PARTICIPATION_DRIFT,
            member_device_ids=["phone-001", "stale-device"],
            ineligible_members=["stale-device"],
            drift_reasons=["stale-device: not orchestration_eligible (stale)"],
        )
        self.assertFalse(r.is_consistent)
        self.assertIn("stale-device", r.ineligible_members)

    def test_missing_formation_descriptor(self):
        from core.multi_device_control_integrity import (
            build_formation_truth_record, FormationTruthConsistency,
        )
        r = build_formation_truth_record(
            task_id="task-022",
            consistency=FormationTruthConsistency.FORMATION_MISSING,
            drift_reasons=["GAP-517-004: no DeviceFormationGroup produced before dispatch"],
        )
        self.assertFalse(r.is_consistent)
        self.assertIn("GAP-517-004", r.drift_reasons[0])


class TestFF_ControlSemantics(unittest.TestCase):
    """FF) Control semantics — local vs remote dispatch vs takeover."""

    def test_local_control_source_equals_target(self):
        from core.multi_device_control_integrity import (
            build_control_semantic_record, ControlSemanticKind,
        )
        r = build_control_semantic_record(
            task_id="task-030",
            source_device_id="phone-001",
            target_device_id="phone-001",
            control_kind=ControlSemanticKind.LOCAL_EXECUTION,
        )
        self.assertTrue(r.is_local)
        self.assertFalse(r.is_remote_dispatch)
        self.assertFalse(r.is_takeover)

    def test_cross_device_dispatch(self):
        from core.multi_device_control_integrity import (
            build_control_semantic_record, ControlSemanticKind,
        )
        r = build_control_semantic_record(
            task_id="task-031",
            source_device_id="phone-001",
            target_device_id="desktop-001",
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
        )
        self.assertFalse(r.is_local)
        self.assertTrue(r.is_remote_dispatch)
        self.assertTrue(r.is_semantically_clear)

    def test_takeover_semantics(self):
        from core.multi_device_control_integrity import (
            build_control_semantic_record, ControlSemanticKind,
        )
        r = build_control_semantic_record(
            task_id="task-032",
            source_device_id="phone-001",
            target_device_id="tablet-001",
            control_kind=ControlSemanticKind.TAKEOVER,
            is_takeover=True,
        )
        self.assertTrue(r.is_takeover)
        self.assertNotEqual(r.source_device_id, r.target_device_id)

    def test_hybrid_multi_device(self):
        from core.multi_device_control_integrity import (
            build_control_semantic_record, ControlSemanticKind,
        )
        r = build_control_semantic_record(
            task_id="task-033",
            source_device_id="phone-001",
            target_device_id="desktop-001",
            control_kind=ControlSemanticKind.HYBRID,
        )
        self.assertEqual(r.control_kind, ControlSemanticKind.HYBRID)

    def test_semantic_ambiguity_when_device_ids_missing(self):
        from core.multi_device_control_integrity import (
            build_control_semantic_record, ControlSemanticKind,
        )
        r = build_control_semantic_record(
            task_id="task-034",
            # No source or target device_id provided
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
            ambiguity_reasons=["GAP-517-006: source_device_id not set in route_task context"],
        )
        self.assertFalse(r.is_semantically_clear)


class TestGG_ResultSurface(unittest.TestCase):
    """GG) Result surface — full canonical / partial / transport-local."""

    def test_full_canonical_surface(self):
        from core.multi_device_control_integrity import (
            build_result_surface_record, ResultSurfaceKind,
        )
        r = build_result_surface_record(
            task_id="task-040",
            source_device_id="phone-001",
            target_device_ids=["desktop-001"],
            result_envelope_produced=True,
            operator_surface_updated=True,
            task_graph_updated=True,
            replay_foundation_updated=True,
            projection_updated=True,
        )
        self.assertEqual(r.surface_kind, ResultSurfaceKind.CANONICAL_FULL)
        self.assertTrue(r.is_canonically_surfaced)

    def test_partial_surface_result_envelope_only(self):
        from core.multi_device_control_integrity import (
            build_result_surface_record, ResultSurfaceKind,
        )
        r = build_result_surface_record(
            task_id="task-041",
            result_envelope_produced=True,
            # Operator surface and graph not updated
            surface_gap_reasons=["GAP-517-007: graph not updated after cross-device completion"],
        )
        self.assertEqual(r.surface_kind, ResultSurfaceKind.CANONICAL_PARTIAL)
        self.assertFalse(r.is_canonically_surfaced)
        self.assertIn("GAP-517-007", r.surface_gap_reasons[0])

    def test_transport_local_no_surface(self):
        from core.multi_device_control_integrity import (
            build_result_surface_record, ResultSurfaceKind,
        )
        r = build_result_surface_record(
            task_id="task-042",
            surface_gap_reasons=["coordinator returned raw dict; no surface exposure"],
        )
        self.assertEqual(r.surface_kind, ResultSurfaceKind.TRANSPORT_LOCAL_ONLY)
        self.assertFalse(r.is_canonically_surfaced)


if __name__ == "__main__":
    unittest.main()
