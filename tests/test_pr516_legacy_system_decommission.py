#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr516_legacy_system_decommission.py
================================================
PR-516 — Legacy / Parallel System Decommission Sweep: Tests.

Validates that:
* The legacy_system_decommission module exports all required sentinels and symbols.
* DecommissionedPathKind and DecommissionStatus enums have all required values.
* DecommissionEntry, DecommissionActivationRecord, DecommissionSnapshot have
  correct structure and to_dict() round-trips.
* DecommissionSnapshot.summary() returns expected keys.
* LegacySystemDecommissionRuntime singleton management works.
* LegacySystemDecommissionRuntime ring buffer accepts and returns records.
* record_decommission_activation helper writes to the ring buffer.
* assert_path_not_active logs a violation for RETIRED paths.
* assert_path_not_active does NOT log a violation for GATED paths.
* get_decommission_catalog() returns the complete catalog.
* snapshot_decommission() returns combined dict with authority / layer fields.
* All expected RETIRED paths are present in the catalog.
* All expected GATED paths are present in the catalog.
* CONFLICT-003 is resolved in RuntimeClosureAudit.detect_parallel_truth_paths().
* CONFLICT-009 is present and resolved in detect_parallel_truth_paths().
* CONFLICT-010 is present and resolved in detect_parallel_truth_paths().
* PR-516 layer specs are present in RuntimeClosureAudit.verify_all_layers().
* Legacy orchestration authority registry contains all PR-516 entries.
* Decommission catalog covers the expected set of conflicts closed.
* Snapshot is operator-safe (no raw deque).
* Non-blocking: record_decommission_activation never raises.
* reset_legacy_system_decommission_runtime is callable and resets state.

Test groups
-----------
 A)  Module structure — all __all__ symbols importable.
 B)  Authority sentinels — correct values and types.
 C)  Policy sentinels — vocabulary checks.
 D)  DecommissionedPathKind enum — all required values present.
 E)  DecommissionStatus enum — all required values present.
 F)  DecommissionEntry dataclass — structure and to_dict().
 G)  DecommissionActivationRecord dataclass — structure and to_dict().
 H)  DecommissionSnapshot dataclass — structure and summary().
 I)  LegacySystemDecommissionRuntime — singleton management.
 J)  LegacySystemDecommissionRuntime — ring buffer writes and reads.
 K)  record_decommission_activation helper — ring buffer write.
 L)  assert_path_not_active — violation recorded for RETIRED path.
 M)  assert_path_not_active — no violation for GATED path.
 N)  get_decommission_catalog — returns full catalog.
 O)  snapshot_decommission — combined dict with authority / layer fields.
 P)  Retired paths in catalog — GatewayCapabilityRegistry, TaskDecomposer,
     IntelligentTaskPlanner, TaskRouter, TaskScheduler, dashboard contract.
 Q)  Gated paths in catalog — CapabilityRegistry, LocalAgentRuntime,
     ProjectionEngine, MessageHandler.
 R)  Conflicts closed coverage — CONFLICT-003, CONFLICT-009, CONFLICT-010.
 S)  CONFLICT-003 resolved in RuntimeClosureAudit.
 T)  CONFLICT-009 present and resolved in RuntimeClosureAudit.
 U)  CONFLICT-010 present and resolved in RuntimeClosureAudit.
 V)  PR-516 layer specs present in verify_all_layers.
 W)  Legacy orchestration authority registry — PR-516 entries present.
 X)  Operator-safe snapshot — no raw deque in summary().
 Y)  Non-blocking — record_decommission_activation never raises.
 Z)  reset callable and resets state.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helper: reset singleton between tests
# ---------------------------------------------------------------------------


def _reset() -> None:
    try:
        from core.legacy_system_decommission import (
            reset_legacy_system_decommission_runtime,
        )
        reset_legacy_system_decommission_runtime()
    except Exception:
        pass


# ===========================================================================
# A)  Module structure
# ===========================================================================


class TestA_ModuleStructure(unittest.TestCase):
    """A) All __all__ symbols importable."""

    def test_A01_module_importable(self) -> None:
        import core.legacy_system_decommission as mod  # noqa: F401
        self.assertIsNotNone(mod)

    def test_A02_all_symbols_importable(self) -> None:
        import core.legacy_system_decommission as mod
        for sym in mod.__all__:
            self.assertTrue(
                hasattr(mod, sym),
                f"__all__ member {sym!r} not found in module",
            )

    def test_A03_authority_sentinel_present(self) -> None:
        from core.legacy_system_decommission import LEGACY_SYSTEM_DECOMMISSION_AUTHORITY
        self.assertIsInstance(LEGACY_SYSTEM_DECOMMISSION_AUTHORITY, str)
        self.assertGreater(len(LEGACY_SYSTEM_DECOMMISSION_AUTHORITY), 0)

    def test_A04_integrated_sentinel_present(self) -> None:
        from core.legacy_system_decommission import LEGACY_SYSTEM_DECOMMISSION_INTEGRATED
        self.assertIsInstance(LEGACY_SYSTEM_DECOMMISSION_INTEGRATED, str)
        self.assertGreater(len(LEGACY_SYSTEM_DECOMMISSION_INTEGRATED), 0)


# ===========================================================================
# B)  Authority sentinels
# ===========================================================================


class TestB_AuthoritySentinels(unittest.TestCase):
    """B) Authority sentinels have correct values and types."""

    def test_B01_authority_contains_authority_keyword(self) -> None:
        from core.legacy_system_decommission import LEGACY_SYSTEM_DECOMMISSION_AUTHORITY
        self.assertIn("AUTHORITY", LEGACY_SYSTEM_DECOMMISSION_AUTHORITY)

    def test_B02_layer_position_is_int(self) -> None:
        from core.legacy_system_decommission import LEGACY_SYSTEM_DECOMMISSION_LAYER_POSITION
        self.assertIsInstance(LEGACY_SYSTEM_DECOMMISSION_LAYER_POSITION, int)

    def test_B03_layer_position_is_16(self) -> None:
        from core.legacy_system_decommission import LEGACY_SYSTEM_DECOMMISSION_LAYER_POSITION
        self.assertEqual(LEGACY_SYSTEM_DECOMMISSION_LAYER_POSITION, 16)

    def test_B04_integrated_sentinel_mentions_conflict_003(self) -> None:
        from core.legacy_system_decommission import LEGACY_SYSTEM_DECOMMISSION_INTEGRATED
        self.assertIn("CONFLICT-003", LEGACY_SYSTEM_DECOMMISSION_INTEGRATED)

    def test_B05_integrated_sentinel_mentions_conflict_009(self) -> None:
        from core.legacy_system_decommission import LEGACY_SYSTEM_DECOMMISSION_INTEGRATED
        self.assertIn("CONFLICT-009", LEGACY_SYSTEM_DECOMMISSION_INTEGRATED)

    def test_B06_integrated_sentinel_mentions_conflict_010(self) -> None:
        from core.legacy_system_decommission import LEGACY_SYSTEM_DECOMMISSION_INTEGRATED
        self.assertIn("CONFLICT-010", LEGACY_SYSTEM_DECOMMISSION_INTEGRATED)


# ===========================================================================
# C)  Policy sentinels
# ===========================================================================


class TestC_PolicySentinels(unittest.TestCase):
    """C) Policy sentinels are importable and contain required vocabulary."""

    def test_C01_decommission_audit_only_policy(self) -> None:
        from core.legacy_system_decommission import DECOMMISSION_AUDIT_ONLY_POLICY
        self.assertIn("MUST NOT", DECOMMISSION_AUDIT_ONLY_POLICY)

    def test_C02_canonical_capability_source_policy(self) -> None:
        from core.legacy_system_decommission import CANONICAL_CAPABILITY_SOURCE_POLICY
        self.assertIn("CapabilityAssimilationLayer", CANONICAL_CAPABILITY_SOURCE_POLICY)
        self.assertIn("CONFLICT-003", CANONICAL_CAPABILITY_SOURCE_POLICY)

    def test_C03_canonical_decomposition_path_policy(self) -> None:
        from core.legacy_system_decommission import CANONICAL_DECOMPOSITION_PATH_POLICY
        self.assertIn("TaskGraph", CANONICAL_DECOMPOSITION_PATH_POLICY)
        self.assertIn("CONFLICT-009", CANONICAL_DECOMPOSITION_PATH_POLICY)

    def test_C04_canonical_projection_contract_policy(self) -> None:
        from core.legacy_system_decommission import CANONICAL_PROJECTION_CONTRACT_POLICY
        self.assertIn("ProjectionSurfaceBridge", CANONICAL_PROJECTION_CONTRACT_POLICY)
        self.assertIn("CONFLICT-010", CANONICAL_PROJECTION_CONTRACT_POLICY)

    def test_C05_no_parallel_dispatch_authority_policy(self) -> None:
        from core.legacy_system_decommission import NO_PARALLEL_DISPATCH_AUTHORITY_POLICY
        self.assertIn("CommandRouter", NO_PARALLEL_DISPATCH_AUTHORITY_POLICY)

    def test_C06_decommission_non_regression_policy(self) -> None:
        from core.legacy_system_decommission import DECOMMISSION_NON_REGRESSION_POLICY
        self.assertIn("RETIRED", DECOMMISSION_NON_REGRESSION_POLICY)


# ===========================================================================
# D)  DecommissionedPathKind enum
# ===========================================================================


class TestD_DecommissionedPathKind(unittest.TestCase):
    """D) DecommissionedPathKind enum has all required values."""

    def _enum(self):
        from core.legacy_system_decommission import DecommissionedPathKind
        return DecommissionedPathKind

    def test_D01_capability_registry(self) -> None:
        self.assertEqual(self._enum().CAPABILITY_REGISTRY.value, "capability_registry")

    def test_D02_task_decomposer(self) -> None:
        self.assertEqual(self._enum().TASK_DECOMPOSER.value, "task_decomposer")

    def test_D03_dispatch_authority(self) -> None:
        self.assertEqual(self._enum().DISPATCH_AUTHORITY.value, "dispatch_authority")

    def test_D04_agent_planner(self) -> None:
        self.assertEqual(self._enum().AGENT_PLANNER.value, "agent_planner")

    def test_D05_projection_contract(self) -> None:
        self.assertEqual(self._enum().PROJECTION_CONTRACT.value, "projection_contract")

    def test_D06_envelope_ingress(self) -> None:
        self.assertEqual(self._enum().ENVELOPE_INGRESS.value, "envelope_ingress")

    def test_D07_all_six_values_present(self) -> None:
        required = {
            "capability_registry", "task_decomposer", "dispatch_authority",
            "agent_planner", "projection_contract", "envelope_ingress",
        }
        actual = {e.value for e in self._enum()}
        self.assertTrue(required.issubset(actual))


# ===========================================================================
# E)  DecommissionStatus enum
# ===========================================================================


class TestE_DecommissionStatus(unittest.TestCase):
    """E) DecommissionStatus enum has all required values."""

    def _enum(self):
        from core.legacy_system_decommission import DecommissionStatus
        return DecommissionStatus

    def test_E01_retired(self) -> None:
        self.assertEqual(self._enum().RETIRED.value, "retired")

    def test_E02_gated(self) -> None:
        self.assertEqual(self._enum().GATED.value, "gated")

    def test_E03_residual(self) -> None:
        self.assertEqual(self._enum().RESIDUAL.value, "residual")


# ===========================================================================
# F)  DecommissionEntry dataclass
# ===========================================================================


class TestF_DecommissionEntry(unittest.TestCase):
    """F) DecommissionEntry structure and to_dict()."""

    def test_F01_default_construction(self) -> None:
        from core.legacy_system_decommission import DecommissionEntry
        e = DecommissionEntry()
        self.assertIsInstance(e, DecommissionEntry)

    def test_F02_to_dict_keys(self) -> None:
        from core.legacy_system_decommission import (
            DecommissionEntry, DecommissionedPathKind, DecommissionStatus,
        )
        e = DecommissionEntry(
            path_id="test.path",
            kind=DecommissionedPathKind.DISPATCH_AUTHORITY,
            status=DecommissionStatus.RETIRED,
            canonical_replacement="core.command_router",
            reason="test reason",
        )
        d = e.to_dict()
        required_keys = {
            "path_id", "kind", "status", "canonical_replacement",
            "reason", "conflict_closed", "pr_origin", "pr_decommission", "notes",
        }
        self.assertTrue(required_keys.issubset(d.keys()))

    def test_F03_to_dict_roundtrip(self) -> None:
        from core.legacy_system_decommission import (
            DecommissionEntry, DecommissionedPathKind, DecommissionStatus,
        )
        e = DecommissionEntry(
            path_id="some.legacy.module",
            kind=DecommissionedPathKind.CAPABILITY_REGISTRY,
            status=DecommissionStatus.GATED,
            canonical_replacement="core.capability_assimilation",
            reason="legacy capability store",
            conflict_closed="CONFLICT-003",
        )
        d = e.to_dict()
        self.assertEqual(d["path_id"], "some.legacy.module")
        self.assertEqual(d["kind"], "capability_registry")
        self.assertEqual(d["status"], "gated")
        self.assertEqual(d["conflict_closed"], "CONFLICT-003")

    def test_F04_default_pr_decommission_is_pr516(self) -> None:
        from core.legacy_system_decommission import DecommissionEntry
        e = DecommissionEntry()
        self.assertEqual(e.pr_decommission, "PR-516")


# ===========================================================================
# G)  DecommissionActivationRecord dataclass
# ===========================================================================


class TestG_DecommissionActivationRecord(unittest.TestCase):
    """G) DecommissionActivationRecord structure and to_dict()."""

    def test_G01_default_construction(self) -> None:
        from core.legacy_system_decommission import DecommissionActivationRecord
        r = DecommissionActivationRecord()
        self.assertIsInstance(r, DecommissionActivationRecord)

    def test_G02_to_dict_keys(self) -> None:
        from core.legacy_system_decommission import (
            DecommissionActivationRecord, DecommissionStatus,
        )
        r = DecommissionActivationRecord(
            record_id=1,
            path_id="some.path",
            caller="test.module",
            reason="test",
            status=DecommissionStatus.RETIRED,
        )
        d = r.to_dict()
        required = {"record_id", "path_id", "caller", "reason", "status", "timestamp"}
        self.assertTrue(required.issubset(d.keys()))

    def test_G03_to_dict_values(self) -> None:
        from core.legacy_system_decommission import (
            DecommissionActivationRecord, DecommissionStatus,
        )
        r = DecommissionActivationRecord(
            record_id=42,
            path_id="galaxy_gateway.task_router.TaskRouter",
            caller="test",
            reason="compat",
            status=DecommissionStatus.RETIRED,
        )
        d = r.to_dict()
        self.assertEqual(d["record_id"], 42)
        self.assertEqual(d["path_id"], "galaxy_gateway.task_router.TaskRouter")
        self.assertEqual(d["status"], "retired")


# ===========================================================================
# H)  DecommissionSnapshot dataclass
# ===========================================================================


class TestH_DecommissionSnapshot(unittest.TestCase):
    """H) DecommissionSnapshot structure and summary()."""

    def test_H01_default_construction(self) -> None:
        from core.legacy_system_decommission import DecommissionSnapshot
        s = DecommissionSnapshot()
        self.assertIsInstance(s, DecommissionSnapshot)

    def test_H02_summary_keys(self) -> None:
        from core.legacy_system_decommission import DecommissionSnapshot
        s = DecommissionSnapshot(
            authority="TEST_AUTHORITY",
            layer_position=16,
            total_retired=5,
            total_gated=3,
            total_residual=0,
            total_activation_records=0,
            conflicts_closed=["CONFLICT-003"],
        )
        d = s.summary()
        required = {
            "authority", "layer_position", "total_retired", "total_gated",
            "total_residual", "total_activation_records", "conflicts_closed",
        }
        self.assertTrue(required.issubset(d.keys()))

    def test_H03_summary_values(self) -> None:
        from core.legacy_system_decommission import DecommissionSnapshot
        s = DecommissionSnapshot(
            authority="A",
            layer_position=16,
            total_retired=5,
            total_gated=3,
            total_residual=0,
            total_activation_records=2,
            conflicts_closed=["CONFLICT-003", "CONFLICT-009"],
        )
        d = s.summary()
        self.assertEqual(d["total_retired"], 5)
        self.assertEqual(d["total_gated"], 3)
        self.assertEqual(d["layer_position"], 16)
        self.assertIn("CONFLICT-003", d["conflicts_closed"])


# ===========================================================================
# I)  LegacySystemDecommissionRuntime — singleton management
# ===========================================================================


class TestI_SingletonManagement(unittest.TestCase):
    """I) Singleton management."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_I01_get_runtime_returns_instance(self) -> None:
        from core.legacy_system_decommission import (
            get_legacy_system_decommission_runtime,
            LegacySystemDecommissionRuntime,
        )
        rt = get_legacy_system_decommission_runtime()
        self.assertIsInstance(rt, LegacySystemDecommissionRuntime)

    def test_I02_singleton_identity(self) -> None:
        from core.legacy_system_decommission import get_legacy_system_decommission_runtime
        rt1 = get_legacy_system_decommission_runtime()
        rt2 = get_legacy_system_decommission_runtime()
        self.assertIs(rt1, rt2)

    def test_I03_reset_creates_new_instance(self) -> None:
        from core.legacy_system_decommission import (
            get_legacy_system_decommission_runtime,
            reset_legacy_system_decommission_runtime,
        )
        rt1 = get_legacy_system_decommission_runtime()
        reset_legacy_system_decommission_runtime()
        rt2 = get_legacy_system_decommission_runtime()
        self.assertIsNot(rt1, rt2)


# ===========================================================================
# J)  Ring buffer writes and reads
# ===========================================================================


class TestJ_RingBuffer(unittest.TestCase):
    """J) Ring buffer writes and reads."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_J01_record_activation_returns_record_for_known_path(self) -> None:
        from core.legacy_system_decommission import (
            get_legacy_system_decommission_runtime,
            DecommissionActivationRecord,
        )
        rt = get_legacy_system_decommission_runtime()
        rec = rt.record_activation(
            path_id="galaxy_gateway.task_router.TaskRouter",
            caller="test_J01",
        )
        self.assertIsInstance(rec, DecommissionActivationRecord)

    def test_J02_record_activation_returns_none_for_unknown_path(self) -> None:
        from core.legacy_system_decommission import get_legacy_system_decommission_runtime
        rt = get_legacy_system_decommission_runtime()
        rec = rt.record_activation(path_id="unknown.not.in.catalog")
        self.assertIsNone(rec)

    def test_J03_records_stored_in_ring_buffer(self) -> None:
        from core.legacy_system_decommission import get_legacy_system_decommission_runtime
        rt = get_legacy_system_decommission_runtime()
        rt.record_activation("galaxy_gateway.task_router.TaskRouter", "test_J03a")
        rt.record_activation("galaxy_gateway.task_router.TaskScheduler", "test_J03b")
        records = rt.get_activation_records()
        path_ids = [r.path_id for r in records]
        self.assertIn("galaxy_gateway.task_router.TaskRouter", path_ids)
        self.assertIn("galaxy_gateway.task_router.TaskScheduler", path_ids)

    def test_J04_record_ids_monotonically_increasing(self) -> None:
        from core.legacy_system_decommission import get_legacy_system_decommission_runtime
        rt = get_legacy_system_decommission_runtime()
        r1 = rt.record_activation("galaxy_gateway.task_router.TaskRouter", "J04a")
        r2 = rt.record_activation("galaxy_gateway.task_router.TaskScheduler", "J04b")
        self.assertIsNotNone(r1)
        self.assertIsNotNone(r2)
        self.assertGreater(r2.record_id, r1.record_id)  # type: ignore[union-attr]

    def test_J05_activation_record_has_correct_status(self) -> None:
        from core.legacy_system_decommission import (
            get_legacy_system_decommission_runtime, DecommissionStatus,
        )
        rt = get_legacy_system_decommission_runtime()
        rec = rt.record_activation("galaxy_gateway.task_router.TaskRouter", "J05")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.status, DecommissionStatus.RETIRED)  # type: ignore[union-attr]


# ===========================================================================
# K)  record_decommission_activation helper
# ===========================================================================


class TestK_RecordActivationHelper(unittest.TestCase):
    """K) record_decommission_activation helper writes to ring buffer."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_K01_helper_writes_to_ring_buffer(self) -> None:
        from core.legacy_system_decommission import (
            record_decommission_activation,
            get_legacy_system_decommission_runtime,
        )
        record_decommission_activation(
            path_id="galaxy_gateway.task_router.TaskRouter",
            caller="test_K01",
            reason="compat call",
        )
        rt = get_legacy_system_decommission_runtime()
        records = rt.get_activation_records()
        self.assertTrue(
            any(r.path_id == "galaxy_gateway.task_router.TaskRouter" for r in records)
        )

    def test_K02_helper_does_not_raise_for_unknown_path(self) -> None:
        from core.legacy_system_decommission import record_decommission_activation
        # Should not raise
        record_decommission_activation("totally.unknown.path", "test_K02")


# ===========================================================================
# L)  assert_path_not_active — violation recorded for RETIRED path
# ===========================================================================


class TestL_AssertPathNotActiveRetired(unittest.TestCase):
    """L) assert_path_not_active records violation for RETIRED path."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_L01_violation_recorded_for_retired_path(self) -> None:
        from core.legacy_system_decommission import (
            assert_path_not_active,
            get_legacy_system_decommission_runtime,
        )
        assert_path_not_active(
            "galaxy_gateway.task_router.TaskRouter",
            caller="test_L01",
        )
        rt = get_legacy_system_decommission_runtime()
        records = rt.get_activation_records()
        self.assertTrue(
            any(r.path_id == "galaxy_gateway.task_router.TaskRouter" for r in records),
            "Expected an activation record for the RETIRED path",
        )

    def test_L02_record_has_non_regression_reason(self) -> None:
        from core.legacy_system_decommission import (
            assert_path_not_active,
            get_legacy_system_decommission_runtime,
        )
        assert_path_not_active(
            "galaxy_gateway.task_decomposer.TaskDecomposer",
            caller="test_L02",
        )
        rt = get_legacy_system_decommission_runtime()
        records = rt.get_activation_records()
        matching = [r for r in records if r.path_id == "galaxy_gateway.task_decomposer.TaskDecomposer"]
        self.assertTrue(len(matching) > 0)
        self.assertIn("non-regression", matching[-1].reason.lower())


# ===========================================================================
# M)  assert_path_not_active — no violation for GATED path
# ===========================================================================


class TestM_AssertPathNotActiveGated(unittest.TestCase):
    """M) assert_path_not_active does NOT record violation for GATED path."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_M01_no_violation_for_gated_path(self) -> None:
        from core.legacy_system_decommission import (
            assert_path_not_active,
            get_legacy_system_decommission_runtime,
        )
        assert_path_not_active(
            "core.local_agent_runtime.LocalAgentRuntime",
            caller="test_M01",
        )
        rt = get_legacy_system_decommission_runtime()
        records = rt.get_activation_records()
        # For GATED paths, assert_path_not_active should NOT record
        violation_records = [
            r for r in records
            if r.path_id == "core.local_agent_runtime.LocalAgentRuntime"
        ]
        self.assertEqual(
            len(violation_records), 0,
            "GATED path should not produce a non-regression violation record",
        )


# ===========================================================================
# N)  get_decommission_catalog
# ===========================================================================


class TestN_GetDecommissionCatalog(unittest.TestCase):
    """N) get_decommission_catalog returns full catalog."""

    def test_N01_returns_list(self) -> None:
        from core.legacy_system_decommission import get_decommission_catalog
        catalog = get_decommission_catalog()
        self.assertIsInstance(catalog, list)

    def test_N02_catalog_not_empty(self) -> None:
        from core.legacy_system_decommission import get_decommission_catalog
        catalog = get_decommission_catalog()
        self.assertGreater(len(catalog), 0)

    def test_N03_all_entries_are_decommission_entries(self) -> None:
        from core.legacy_system_decommission import (
            get_decommission_catalog, DecommissionEntry,
        )
        for entry in get_decommission_catalog():
            self.assertIsInstance(entry, DecommissionEntry)

    def test_N04_returns_copy(self) -> None:
        from core.legacy_system_decommission import get_decommission_catalog
        c1 = get_decommission_catalog()
        c2 = get_decommission_catalog()
        self.assertIsNot(c1, c2)


# ===========================================================================
# O)  snapshot_decommission
# ===========================================================================


class TestO_SnapshotDecommission(unittest.TestCase):
    """O) snapshot_decommission returns combined dict with authority / layer fields."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_O01_returns_snapshot(self) -> None:
        from core.legacy_system_decommission import (
            snapshot_decommission, DecommissionSnapshot,
        )
        snap = snapshot_decommission()
        self.assertIsInstance(snap, DecommissionSnapshot)

    def test_O02_snapshot_authority_field(self) -> None:
        from core.legacy_system_decommission import snapshot_decommission
        snap = snapshot_decommission()
        self.assertIn("AUTHORITY", snap.authority)

    def test_O03_snapshot_layer_position_is_16(self) -> None:
        from core.legacy_system_decommission import snapshot_decommission
        snap = snapshot_decommission()
        self.assertEqual(snap.layer_position, 16)

    def test_O04_conflicts_closed_present(self) -> None:
        from core.legacy_system_decommission import snapshot_decommission
        snap = snapshot_decommission()
        self.assertIn("CONFLICT-003", snap.conflicts_closed)
        self.assertIn("CONFLICT-009", snap.conflicts_closed)
        self.assertIn("CONFLICT-010", snap.conflicts_closed)

    def test_O05_total_retired_positive(self) -> None:
        from core.legacy_system_decommission import snapshot_decommission
        snap = snapshot_decommission()
        self.assertGreater(snap.total_retired, 0)

    def test_O06_total_gated_positive(self) -> None:
        from core.legacy_system_decommission import snapshot_decommission
        snap = snapshot_decommission()
        self.assertGreater(snap.total_gated, 0)

    def test_O07_decommission_catalog_in_snapshot(self) -> None:
        from core.legacy_system_decommission import snapshot_decommission
        snap = snapshot_decommission()
        self.assertIsInstance(snap.decommission_catalog, list)
        self.assertGreater(len(snap.decommission_catalog), 0)


# ===========================================================================
# P)  Retired paths in catalog
# ===========================================================================


class TestP_RetiredPaths(unittest.TestCase):
    """P) All expected RETIRED paths are present in the catalog."""

    def _catalog_by_id(self):
        from core.legacy_system_decommission import get_decommission_catalog, DecommissionStatus
        return {e.path_id: e for e in get_decommission_catalog()}

    def test_P01_gateway_capability_registry_retired(self) -> None:
        from core.legacy_system_decommission import DecommissionStatus
        catalog = self._catalog_by_id()
        self.assertIn("galaxy_gateway.capability_registry.GatewayCapabilityRegistry", catalog)
        entry = catalog["galaxy_gateway.capability_registry.GatewayCapabilityRegistry"]
        self.assertEqual(entry.status, DecommissionStatus.RETIRED)

    def test_P02_task_decomposer_retired(self) -> None:
        from core.legacy_system_decommission import DecommissionStatus
        catalog = self._catalog_by_id()
        self.assertIn("galaxy_gateway.task_decomposer.TaskDecomposer", catalog)
        entry = catalog["galaxy_gateway.task_decomposer.TaskDecomposer"]
        self.assertEqual(entry.status, DecommissionStatus.RETIRED)

    def test_P03_intelligent_task_planner_retired(self) -> None:
        from core.legacy_system_decommission import DecommissionStatus
        catalog = self._catalog_by_id()
        self.assertIn("galaxy_gateway.task_decomposer.IntelligentTaskPlanner", catalog)
        entry = catalog["galaxy_gateway.task_decomposer.IntelligentTaskPlanner"]
        self.assertEqual(entry.status, DecommissionStatus.RETIRED)

    def test_P04_task_router_retired(self) -> None:
        from core.legacy_system_decommission import DecommissionStatus
        catalog = self._catalog_by_id()
        self.assertIn("galaxy_gateway.task_router.TaskRouter", catalog)
        entry = catalog["galaxy_gateway.task_router.TaskRouter"]
        self.assertEqual(entry.status, DecommissionStatus.RETIRED)

    def test_P05_task_scheduler_retired(self) -> None:
        from core.legacy_system_decommission import DecommissionStatus
        catalog = self._catalog_by_id()
        self.assertIn("galaxy_gateway.task_router.TaskScheduler", catalog)
        entry = catalog["galaxy_gateway.task_router.TaskScheduler"]
        self.assertEqual(entry.status, DecommissionStatus.RETIRED)

    def test_P06_dashboard_legacy_projection_contract_retired(self) -> None:
        from core.legacy_system_decommission import DecommissionStatus
        catalog = self._catalog_by_id()
        self.assertIn("dashboard.backend.legacy_projection_contract", catalog)
        entry = catalog["dashboard.backend.legacy_projection_contract"]
        self.assertEqual(entry.status, DecommissionStatus.RETIRED)


# ===========================================================================
# Q)  Gated paths in catalog
# ===========================================================================


class TestQ_GatedPaths(unittest.TestCase):
    """Q) All expected GATED paths are present in the catalog."""

    def _catalog_by_id(self):
        from core.legacy_system_decommission import get_decommission_catalog
        return {e.path_id: e for e in get_decommission_catalog()}

    def test_Q01_core_capability_registry_gated(self) -> None:
        from core.legacy_system_decommission import DecommissionStatus
        catalog = self._catalog_by_id()
        self.assertIn("core.capability_registry.CapabilityRegistry", catalog)
        entry = catalog["core.capability_registry.CapabilityRegistry"]
        self.assertEqual(entry.status, DecommissionStatus.GATED)

    def test_Q02_local_agent_runtime_gated(self) -> None:
        from core.legacy_system_decommission import DecommissionStatus
        catalog = self._catalog_by_id()
        self.assertIn("core.local_agent_runtime.LocalAgentRuntime", catalog)
        entry = catalog["core.local_agent_runtime.LocalAgentRuntime"]
        self.assertEqual(entry.status, DecommissionStatus.GATED)

    def test_Q03_projection_engine_gated(self) -> None:
        from core.legacy_system_decommission import DecommissionStatus
        catalog = self._catalog_by_id()
        self.assertIn("desktop_projection.projection_engine.ProjectionEngine", catalog)
        entry = catalog["desktop_projection.projection_engine.ProjectionEngine"]
        self.assertEqual(entry.status, DecommissionStatus.GATED)

    def test_Q04_message_handler_gated(self) -> None:
        from core.legacy_system_decommission import DecommissionStatus
        catalog = self._catalog_by_id()
        self.assertIn("galaxy_gateway.handlers.message_handler.MessageHandler", catalog)
        entry = catalog["galaxy_gateway.handlers.message_handler.MessageHandler"]
        self.assertEqual(entry.status, DecommissionStatus.GATED)


# ===========================================================================
# R)  Conflicts closed coverage
# ===========================================================================


class TestR_ConflictsClosed(unittest.TestCase):
    """R) Decommission catalog covers the expected set of conflicts closed."""

    def test_R01_conflict_003_closed_by_at_least_one_entry(self) -> None:
        from core.legacy_system_decommission import get_decommission_catalog
        closed = {e.conflict_closed for e in get_decommission_catalog() if e.conflict_closed}
        self.assertIn("CONFLICT-003", closed)

    def test_R02_conflict_009_closed_by_at_least_one_entry(self) -> None:
        from core.legacy_system_decommission import get_decommission_catalog
        closed = {e.conflict_closed for e in get_decommission_catalog() if e.conflict_closed}
        self.assertIn("CONFLICT-009", closed)

    def test_R03_conflict_010_closed_by_at_least_one_entry(self) -> None:
        from core.legacy_system_decommission import get_decommission_catalog
        closed = {e.conflict_closed for e in get_decommission_catalog() if e.conflict_closed}
        self.assertIn("CONFLICT-010", closed)

    def test_R04_all_closed_conflicts_in_snapshot(self) -> None:
        from core.legacy_system_decommission import snapshot_decommission
        snap = snapshot_decommission()
        for conflict_id in ("CONFLICT-003", "CONFLICT-009", "CONFLICT-010"):
            self.assertIn(conflict_id, snap.conflicts_closed)


# ===========================================================================
# S)  CONFLICT-003 resolved in RuntimeClosureAudit
# ===========================================================================


class TestS_Conflict003Resolved(unittest.TestCase):
    """S) CONFLICT-003 is resolved in RuntimeClosureAudit.detect_parallel_truth_paths()."""

    def test_S01_conflict_003_resolved(self) -> None:
        from core.runtime_closure_audit import detect_parallel_truth_paths
        conflicts = detect_parallel_truth_paths()
        conflict_003 = [c for c in conflicts if c.conflict_id == "CONFLICT-003"]
        self.assertTrue(len(conflict_003) > 0, "CONFLICT-003 not found in conflicts list")
        self.assertTrue(
            conflict_003[0].is_resolved,
            "CONFLICT-003 should be resolved in PR-516",
        )

    def test_S02_conflict_003_resolution_note_mentions_pr516(self) -> None:
        from core.runtime_closure_audit import detect_parallel_truth_paths
        conflicts = detect_parallel_truth_paths()
        conflict_003 = [c for c in conflicts if c.conflict_id == "CONFLICT-003"]
        self.assertTrue(len(conflict_003) > 0)
        self.assertIn("PR-516", conflict_003[0].resolution_note)


# ===========================================================================
# T)  CONFLICT-009 present and resolved in RuntimeClosureAudit
# ===========================================================================


class TestT_Conflict009Resolved(unittest.TestCase):
    """T) CONFLICT-009 is present and resolved in RuntimeClosureAudit."""

    def test_T01_conflict_009_present(self) -> None:
        from core.runtime_closure_audit import detect_parallel_truth_paths
        conflicts = detect_parallel_truth_paths()
        ids = [c.conflict_id for c in conflicts]
        self.assertIn("CONFLICT-009", ids)

    def test_T02_conflict_009_resolved(self) -> None:
        from core.runtime_closure_audit import detect_parallel_truth_paths
        conflicts = detect_parallel_truth_paths()
        conflict_009 = [c for c in conflicts if c.conflict_id == "CONFLICT-009"]
        self.assertTrue(conflict_009[0].is_resolved)

    def test_T03_conflict_009_mentions_task_decomposer(self) -> None:
        from core.runtime_closure_audit import detect_parallel_truth_paths
        conflicts = detect_parallel_truth_paths()
        conflict_009 = [c for c in conflicts if c.conflict_id == "CONFLICT-009"]
        self.assertIn("TaskDecomposer", conflict_009[0].description)


# ===========================================================================
# U)  CONFLICT-010 present and resolved in RuntimeClosureAudit
# ===========================================================================


class TestU_Conflict010Resolved(unittest.TestCase):
    """U) CONFLICT-010 is present and resolved in RuntimeClosureAudit."""

    def test_U01_conflict_010_present(self) -> None:
        from core.runtime_closure_audit import detect_parallel_truth_paths
        conflicts = detect_parallel_truth_paths()
        ids = [c.conflict_id for c in conflicts]
        self.assertIn("CONFLICT-010", ids)

    def test_U02_conflict_010_resolved(self) -> None:
        from core.runtime_closure_audit import detect_parallel_truth_paths
        conflicts = detect_parallel_truth_paths()
        conflict_010 = [c for c in conflicts if c.conflict_id == "CONFLICT-010"]
        self.assertTrue(conflict_010[0].is_resolved)

    def test_U03_conflict_010_mentions_projection_bridge(self) -> None:
        from core.runtime_closure_audit import detect_parallel_truth_paths
        conflicts = detect_parallel_truth_paths()
        conflict_010 = [c for c in conflicts if c.conflict_id == "CONFLICT-010"]
        self.assertIn("ProjectionSurfaceBridge", conflict_010[0].resolution_note)


# ===========================================================================
# V)  PR-516 layer specs in verify_all_layers
# ===========================================================================


class TestV_Pr516LayerSpecs(unittest.TestCase):
    """V) PR-516 layer specs are present in verify_all_layers()."""

    def test_V01_pr516_layer_specs_present(self) -> None:
        from core.runtime_closure_audit import get_runtime_closure_audit
        audit = get_runtime_closure_audit()
        specs = audit._LAYER_SPECS
        pr516_specs = [s for s in specs if s[0] == "PR-516"]
        self.assertTrue(
            len(pr516_specs) >= 2,
            f"Expected at least 2 PR-516 layer specs, found: {pr516_specs}",
        )

    def test_V02_legacy_decommission_authority_verified(self) -> None:
        from core.runtime_closure_audit import get_runtime_closure_audit
        audit = get_runtime_closure_audit()
        statuses = audit.verify_all_layers()
        pr516 = [s for s in statuses if s.pr_ref == "PR-516"]
        self.assertTrue(len(pr516) >= 1)
        # At least one should be VERIFIED (sentinel importable)
        verified = [s for s in pr516 if s.status == "VERIFIED"]
        self.assertTrue(
            len(verified) >= 1,
            f"Expected at least one VERIFIED PR-516 layer spec, got: {pr516}",
        )


# ===========================================================================
# W)  Legacy orchestration authority registry — PR-516 entries
# ===========================================================================


class TestW_LegacyPathRegistryPr516(unittest.TestCase):
    """W) Legacy orchestration authority registry contains all PR-516 entries."""

    def test_W01_gateway_capability_registry_in_registry(self) -> None:
        from core.orchestration_authority.legacy_paths import (
            is_legacy_path, LEGACY_PATH_REGISTRY,
        )
        self.assertIn(
            "galaxy_gateway.capability_registry.GatewayCapabilityRegistry",
            LEGACY_PATH_REGISTRY,
        )

    def test_W02_task_decomposer_in_registry(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        self.assertIn(
            "galaxy_gateway.task_decomposer.TaskDecomposer",
            LEGACY_PATH_REGISTRY,
        )

    def test_W03_intelligent_task_planner_in_registry(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        self.assertIn(
            "galaxy_gateway.task_decomposer.IntelligentTaskPlanner",
            LEGACY_PATH_REGISTRY,
        )

    def test_W04_projection_engine_in_registry(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        self.assertIn(
            "desktop_projection.projection_engine.ProjectionEngine",
            LEGACY_PATH_REGISTRY,
        )

    def test_W05_dashboard_legacy_contract_in_registry(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        self.assertIn(
            "dashboard.backend.legacy_projection_contract",
            LEGACY_PATH_REGISTRY,
        )

    def test_W06_all_pr516_entries_have_guardrail_pr516(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        pr516_paths = [
            "galaxy_gateway.capability_registry.GatewayCapabilityRegistry",
            "galaxy_gateway.task_decomposer.TaskDecomposer",
            "galaxy_gateway.task_decomposer.IntelligentTaskPlanner",
            "desktop_projection.projection_engine.ProjectionEngine",
            "dashboard.backend.legacy_projection_contract",
        ]
        for path_id in pr516_paths:
            entry = LEGACY_PATH_REGISTRY.get(path_id)
            self.assertIsNotNone(entry, f"Path {path_id!r} not in registry")
            self.assertEqual(
                entry.pr_guardrail_added, "PR-516",
                f"Expected pr_guardrail_added='PR-516' for {path_id!r}",
            )

    def test_W07_legacy_orchestrator_paths_frozenset_updated(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        self.assertIn(
            "galaxy_gateway.capability_registry.GatewayCapabilityRegistry",
            LEGACY_ORCHESTRATOR_PATHS,
        )
        self.assertIn(
            "galaxy_gateway.task_decomposer.TaskDecomposer",
            LEGACY_ORCHESTRATOR_PATHS,
        )


# ===========================================================================
# X)  Operator-safe snapshot — no raw deque in summary()
# ===========================================================================


class TestX_OperatorSafeSnapshot(unittest.TestCase):
    """X) Snapshot is operator-safe — no raw deque in summary()."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_X01_summary_values_are_serializable(self) -> None:
        from core.legacy_system_decommission import snapshot_decommission
        import collections
        snap = snapshot_decommission()
        d = snap.summary()
        for key, val in d.items():
            self.assertNotIsInstance(
                val, collections.deque,
                f"summary()[{key!r}] is a raw deque — not operator-safe",
            )

    def test_X02_recent_activations_is_list(self) -> None:
        from core.legacy_system_decommission import snapshot_decommission
        snap = snapshot_decommission()
        self.assertIsInstance(snap.recent_activations, list)

    def test_X03_decommission_catalog_entries_are_dicts(self) -> None:
        from core.legacy_system_decommission import snapshot_decommission
        snap = snapshot_decommission()
        for item in snap.decommission_catalog:
            self.assertIsInstance(item, dict)


# ===========================================================================
# Y)  Non-blocking — record_decommission_activation never raises
# ===========================================================================


class TestY_NonBlocking(unittest.TestCase):
    """Y) record_decommission_activation never raises."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_Y01_no_exception_for_known_path(self) -> None:
        from core.legacy_system_decommission import record_decommission_activation
        # Must not raise
        record_decommission_activation(
            "galaxy_gateway.task_router.TaskRouter",
            caller="test_Y01",
            reason="test",
        )

    def test_Y02_no_exception_for_unknown_path(self) -> None:
        from core.legacy_system_decommission import record_decommission_activation
        record_decommission_activation("totally.unknown", "test_Y02")

    def test_Y03_no_exception_for_empty_path(self) -> None:
        from core.legacy_system_decommission import record_decommission_activation
        record_decommission_activation("", "test_Y03")

    def test_Y04_assert_path_not_active_never_raises(self) -> None:
        from core.legacy_system_decommission import assert_path_not_active
        assert_path_not_active("galaxy_gateway.task_decomposer.TaskDecomposer", "test_Y04")
        assert_path_not_active("totally.unknown", "test_Y04b")
        assert_path_not_active("", "test_Y04c")


# ===========================================================================
# Z)  reset callable and resets state
# ===========================================================================


class TestZ_Reset(unittest.TestCase):
    """Z) reset_legacy_system_decommission_runtime is callable and resets state."""

    def setUp(self) -> None:
        _reset()

    def tearDown(self) -> None:
        _reset()

    def test_Z01_reset_callable(self) -> None:
        from core.legacy_system_decommission import reset_legacy_system_decommission_runtime
        reset_legacy_system_decommission_runtime()  # Must not raise

    def test_Z02_reset_clears_ring_buffer(self) -> None:
        from core.legacy_system_decommission import (
            get_legacy_system_decommission_runtime,
            reset_legacy_system_decommission_runtime,
        )
        rt = get_legacy_system_decommission_runtime()
        rt.record_activation("galaxy_gateway.task_router.TaskRouter", "Z02")
        self.assertTrue(len(rt.get_activation_records()) > 0)
        reset_legacy_system_decommission_runtime()
        rt2 = get_legacy_system_decommission_runtime()
        self.assertEqual(len(rt2.get_activation_records()), 0)

    def test_Z03_all_open_conflicts_still_present_after_pr516(self) -> None:
        """Non-regression: all CONFLICT-003/009/010 entries are now resolved."""
        from core.runtime_closure_audit import detect_parallel_truth_paths
        conflicts = {c.conflict_id: c for c in detect_parallel_truth_paths()}
        # These three must all be resolved after PR-516
        for cid in ("CONFLICT-003", "CONFLICT-009", "CONFLICT-010"):
            self.assertIn(cid, conflicts, f"Missing conflict entry: {cid}")
            self.assertTrue(
                conflicts[cid].is_resolved,
                f"{cid} should be resolved after PR-516",
            )


if __name__ == "__main__":
    unittest.main()
