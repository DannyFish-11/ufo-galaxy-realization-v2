#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr511_projection_surface_bridge.py
==============================================
PR-511 — Projection Stack Convergence / Surface Bridge: Tests.

Validates that:
* ``core/projection_surface_bridge.py`` declares its authority sentinels
  and topology semantics sentinels correctly.
* Bridge boundary sentinels declare projection-derived vs runtime-augmented.
* ``enrich_runtime_projection()`` enriches without mutating the input.
* ``build_bridge_snapshot()`` returns a valid :class:`ProjectionBridgeSnapshot`.
* ``get_runtime_augmentation()`` returns a :class:`RuntimeAugmentation`.
* Graceful degradation when all runtime layers are empty/unavailable.
* Projection-derived fields are never overwritten by runtime augmentation.
* ``ProjectionBridgeSnapshot.get_enriched_projection()`` merges correctly.
* No new parallel truth source is introduced.
* ``core/routes/projection.py`` wires the bridge integration sentinel.

Test groups
-----------
 A)  Module structure — authority sentinels importable and correct.
 B)  Topology semantics sentinels — three-domain disambiguation.
 C)  Bridge boundary sentinels — projection-derived vs runtime-augmented.
 D)  RuntimeAugmentation dataclass structure.
 E)  ProjectionBridgeSnapshot dataclass structure.
 F)  enrich_runtime_projection() — enriches copy, does not mutate.
 G)  enrich_runtime_projection() — projection-derived fields not overwritten.
 H)  build_bridge_snapshot() — returns ProjectionBridgeSnapshot.
 I)  build_bridge_snapshot() — graceful empty when runtime layers unavailable.
 J)  get_runtime_augmentation() — returns RuntimeAugmentation with correct shape.
 K)  ProjectionBridgeSnapshot.get_enriched_projection() merges without shadowing.
 L)  No new parallel truth source — bridge snapshot is derived/informational only.
 M)  Singleton management — get/reset projection surface bridge.
 N)  __all__ completeness.
 O)  routes/projection.py integration sentinel present.
 P)  Integration — bridge snapshot includes both projection and operator data.
 Q)  Integration — topology domain sentinels are mutually non-overlapping.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_bridge():
    from core.projection_surface_bridge import reset_projection_surface_bridge
    reset_projection_surface_bridge()


def _reset_task_graph():
    try:
        from core.task_graph_runtime import reset_task_graph_runtime
        reset_task_graph_runtime()
    except Exception:
        pass


def _reset_capability():
    try:
        from core.capability_assimilation import reset_capability_assimilation_layer
        reset_capability_assimilation_layer()
    except Exception:
        pass


def _reset_network_topology():
    try:
        from core.network_topology_runtime import reset_network_topology_runtime
        reset_network_topology_runtime()
    except Exception:
        pass


def _reset_replay():
    try:
        from core.replay_foundation import reset_replay_foundation
        reset_replay_foundation()
    except Exception:
        pass


def _reset_operator_surface():
    try:
        from core.operator_surface import reset_operator_surface
        reset_operator_surface()
    except Exception:
        pass


def _reset_all():
    _reset_bridge()
    _reset_task_graph()
    _reset_capability()
    _reset_network_topology()
    _reset_replay()
    _reset_operator_surface()


# ===========================================================================
# A)  Module structure
# ===========================================================================

class TestA_ModuleStructure(unittest.TestCase):
    """A) Authority sentinels importable and correct."""

    def test_A01_authority_importable(self) -> None:
        from core.projection_surface_bridge import PROJECTION_SURFACE_BRIDGE_AUTHORITY
        self.assertIsInstance(PROJECTION_SURFACE_BRIDGE_AUTHORITY, str)
        self.assertGreater(len(PROJECTION_SURFACE_BRIDGE_AUTHORITY), 0)

    def test_A02_authority_contains_v1(self) -> None:
        from core.projection_surface_bridge import PROJECTION_SURFACE_BRIDGE_AUTHORITY
        self.assertIn("PROJECTION_SURFACE_BRIDGE_V1", PROJECTION_SURFACE_BRIDGE_AUTHORITY)

    def test_A03_authority_contains_pr511(self) -> None:
        from core.projection_surface_bridge import PROJECTION_SURFACE_BRIDGE_AUTHORITY
        self.assertIn("PR-511", PROJECTION_SURFACE_BRIDGE_AUTHORITY)

    def test_A04_layer_position_is_11(self) -> None:
        from core.projection_surface_bridge import PROJECTION_SURFACE_BRIDGE_LAYER_POSITION
        self.assertEqual(PROJECTION_SURFACE_BRIDGE_LAYER_POSITION, 11)

    def test_A05_contract_version_importable(self) -> None:
        from core.projection_surface_bridge import PROJECTION_SURFACE_BRIDGE_CONTRACT_VERSION
        self.assertIsInstance(PROJECTION_SURFACE_BRIDGE_CONTRACT_VERSION, str)
        self.assertGreater(len(PROJECTION_SURFACE_BRIDGE_CONTRACT_VERSION), 0)

    def test_A06_convergence_policy_importable(self) -> None:
        from core.projection_surface_bridge import SURFACE_BRIDGE_CONVERGENCE_POLICY
        self.assertIsInstance(SURFACE_BRIDGE_CONVERGENCE_POLICY, str)
        self.assertIn("SURFACE_BRIDGE_CONVERGENCE_POLICY_V1", SURFACE_BRIDGE_CONVERGENCE_POLICY)

    def test_A07_convergence_policy_mentions_both_stacks(self) -> None:
        from core.projection_surface_bridge import SURFACE_BRIDGE_CONVERGENCE_POLICY
        self.assertIn("projection", SURFACE_BRIDGE_CONVERGENCE_POLICY.lower())
        self.assertIn("runtime", SURFACE_BRIDGE_CONVERGENCE_POLICY.lower())

    def test_A08_all_symbols_importable(self) -> None:
        import core.projection_surface_bridge as mod
        for name in mod.__all__:
            self.assertTrue(
                hasattr(mod, name),
                f"__all__ member {name!r} not found in module",
            )


# ===========================================================================
# B)  Topology semantics sentinels
# ===========================================================================

class TestB_TopologySemantics(unittest.TestCase):
    """B) Three-domain topology disambiguation."""

    def test_B01_three_domains_importable(self) -> None:
        from core.projection_surface_bridge import TOPOLOGY_SEMANTICS_THREE_DOMAINS
        self.assertIsInstance(TOPOLOGY_SEMANTICS_THREE_DOMAINS, str)
        self.assertIn("TOPOLOGY_SEMANTICS_THREE_DOMAINS_V1", TOPOLOGY_SEMANTICS_THREE_DOMAINS)

    def test_B02_model_provider_domain_importable(self) -> None:
        from core.projection_surface_bridge import MODEL_PROVIDER_TOPOLOGY_DOMAIN
        self.assertIsInstance(MODEL_PROVIDER_TOPOLOGY_DOMAIN, str)
        self.assertIn("MODEL_PROVIDER_TOPOLOGY_DOMAIN", MODEL_PROVIDER_TOPOLOGY_DOMAIN)

    def test_B03_device_network_domain_importable(self) -> None:
        from core.projection_surface_bridge import DEVICE_NETWORK_TOPOLOGY_DOMAIN
        self.assertIsInstance(DEVICE_NETWORK_TOPOLOGY_DOMAIN, str)
        self.assertIn("DEVICE_NETWORK_TOPOLOGY_DOMAIN", DEVICE_NETWORK_TOPOLOGY_DOMAIN)

    def test_B04_task_graph_domain_importable(self) -> None:
        from core.projection_surface_bridge import TASK_GRAPH_TOPOLOGY_DOMAIN
        self.assertIsInstance(TASK_GRAPH_TOPOLOGY_DOMAIN, str)
        self.assertIn("TASK_GRAPH_TOPOLOGY_DOMAIN", TASK_GRAPH_TOPOLOGY_DOMAIN)

    def test_B05_three_domains_mentions_model_provider(self) -> None:
        from core.projection_surface_bridge import TOPOLOGY_SEMANTICS_THREE_DOMAINS
        self.assertIn("MODEL/PROVIDER", TOPOLOGY_SEMANTICS_THREE_DOMAINS)

    def test_B06_three_domains_mentions_device_network(self) -> None:
        from core.projection_surface_bridge import TOPOLOGY_SEMANTICS_THREE_DOMAINS
        self.assertIn("DEVICE/NETWORK", TOPOLOGY_SEMANTICS_THREE_DOMAINS)

    def test_B07_three_domains_mentions_task_graph(self) -> None:
        from core.projection_surface_bridge import TOPOLOGY_SEMANTICS_THREE_DOMAINS
        self.assertIn("TASK GRAPH", TOPOLOGY_SEMANTICS_THREE_DOMAINS)

    def test_B08_model_provider_domain_references_stack_a(self) -> None:
        from core.projection_surface_bridge import MODEL_PROVIDER_TOPOLOGY_DOMAIN
        # Stack A authorities should be mentioned
        self.assertIn("TopologyRoutePlan", MODEL_PROVIDER_TOPOLOGY_DOMAIN)

    def test_B09_device_network_domain_references_stack_b(self) -> None:
        from core.projection_surface_bridge import DEVICE_NETWORK_TOPOLOGY_DOMAIN
        self.assertIn("NetworkTopologyRuntime", DEVICE_NETWORK_TOPOLOGY_DOMAIN)

    def test_B10_task_graph_domain_references_stack_b(self) -> None:
        from core.projection_surface_bridge import TASK_GRAPH_TOPOLOGY_DOMAIN
        self.assertIn("TaskGraphRuntime", TASK_GRAPH_TOPOLOGY_DOMAIN)

    def test_B11_three_domains_are_distinct_strings(self) -> None:
        from core.projection_surface_bridge import (
            MODEL_PROVIDER_TOPOLOGY_DOMAIN,
            DEVICE_NETWORK_TOPOLOGY_DOMAIN,
            TASK_GRAPH_TOPOLOGY_DOMAIN,
        )
        domains = [MODEL_PROVIDER_TOPOLOGY_DOMAIN, DEVICE_NETWORK_TOPOLOGY_DOMAIN,
                   TASK_GRAPH_TOPOLOGY_DOMAIN]
        self.assertEqual(len(set(domains)), 3)


# ===========================================================================
# C)  Bridge boundary sentinels
# ===========================================================================

class TestC_BridgeBoundaries(unittest.TestCase):
    """C) Projection-derived vs runtime-augmented boundary declarations."""

    def test_C01_projection_derived_boundary_importable(self) -> None:
        from core.projection_surface_bridge import PROJECTION_DERIVED_BOUNDARY
        self.assertIsInstance(PROJECTION_DERIVED_BOUNDARY, str)
        self.assertIn("PROJECTION_DERIVED_BOUNDARY_V1", PROJECTION_DERIVED_BOUNDARY)

    def test_C02_runtime_augmented_boundary_importable(self) -> None:
        from core.projection_surface_bridge import RUNTIME_AUGMENTED_BOUNDARY
        self.assertIsInstance(RUNTIME_AUGMENTED_BOUNDARY, str)
        self.assertIn("RUNTIME_AUGMENTED_BOUNDARY_V1", RUNTIME_AUGMENTED_BOUNDARY)

    def test_C03_no_new_truth_source_policy_importable(self) -> None:
        from core.projection_surface_bridge import NO_NEW_TRUTH_SOURCE_POLICY
        self.assertIsInstance(NO_NEW_TRUTH_SOURCE_POLICY, str)
        self.assertIn("NO_NEW_TRUTH_SOURCE_POLICY_V1", NO_NEW_TRUTH_SOURCE_POLICY)

    def test_C04_projection_derived_boundary_mentions_continuum_fields(self) -> None:
        from core.projection_surface_bridge import PROJECTION_DERIVED_BOUNDARY
        self.assertIn("tri_state_phase", PROJECTION_DERIVED_BOUNDARY)
        self.assertIn("primary_model_id", PROJECTION_DERIVED_BOUNDARY)

    def test_C05_runtime_augmented_boundary_mentions_task_graph(self) -> None:
        from core.projection_surface_bridge import RUNTIME_AUGMENTED_BOUNDARY
        self.assertIn("active_task_count", RUNTIME_AUGMENTED_BOUNDARY)

    def test_C06_runtime_augmented_boundary_mentions_executor_count(self) -> None:
        from core.projection_surface_bridge import RUNTIME_AUGMENTED_BOUNDARY
        self.assertIn("executor_count", RUNTIME_AUGMENTED_BOUNDARY)

    def test_C07_no_new_truth_source_policy_says_informational_only(self) -> None:
        from core.projection_surface_bridge import NO_NEW_TRUTH_SOURCE_POLICY
        self.assertIn("informational", NO_NEW_TRUTH_SOURCE_POLICY.lower())

    def test_C08_projection_derived_boundary_excludes_augmented_fields(self) -> None:
        from core.projection_surface_bridge import PROJECTION_DERIVED_BOUNDARY
        # active_task_count is runtime-augmented, must not appear in projection-derived
        self.assertNotIn("active_task_count", PROJECTION_DERIVED_BOUNDARY)

    def test_C09_runtime_augmented_boundary_says_additive(self) -> None:
        from core.projection_surface_bridge import RUNTIME_AUGMENTED_BOUNDARY
        self.assertIn("ADDITIVE", RUNTIME_AUGMENTED_BOUNDARY.upper())


# ===========================================================================
# D)  RuntimeAugmentation dataclass
# ===========================================================================

class TestD_RuntimeAugmentation(unittest.TestCase):
    """D) RuntimeAugmentation dataclass structure."""

    def test_D01_constructable_with_defaults(self) -> None:
        from core.projection_surface_bridge import RuntimeAugmentation
        aug = RuntimeAugmentation()
        self.assertIsNotNone(aug)

    def test_D02_default_counts_are_zero(self) -> None:
        from core.projection_surface_bridge import RuntimeAugmentation
        aug = RuntimeAugmentation()
        self.assertEqual(aug.active_task_count, 0)
        self.assertEqual(aug.executor_count, 0)
        self.assertEqual(aug.network_reachable_node_count, 0)
        self.assertEqual(aug.replay_event_count, 0)

    def test_D03_default_dicts_are_none(self) -> None:
        from core.projection_surface_bridge import RuntimeAugmentation
        aug = RuntimeAugmentation()
        self.assertIsNone(aug.operator_snapshot_dict)
        self.assertIsNone(aug.task_graph_snapshot_dict)

    def test_D04_source_field_contains_authority(self) -> None:
        from core.projection_surface_bridge import (
            RuntimeAugmentation,
            PROJECTION_SURFACE_BRIDGE_AUTHORITY,
        )
        aug = RuntimeAugmentation()
        self.assertEqual(aug._source, PROJECTION_SURFACE_BRIDGE_AUTHORITY)

    def test_D05_to_dict_returns_dict(self) -> None:
        from core.projection_surface_bridge import RuntimeAugmentation
        aug = RuntimeAugmentation()
        d = aug.to_dict()
        self.assertIsInstance(d, dict)

    def test_D06_to_dict_has_required_keys(self) -> None:
        from core.projection_surface_bridge import RuntimeAugmentation
        aug = RuntimeAugmentation()
        d = aug.to_dict()
        for key in [
            "active_task_count",
            "executor_count",
            "network_reachable_node_count",
            "replay_event_count",
            "operator_snapshot_dict",
            "task_graph_snapshot_dict",
            "augmented_at",
            "_source",
        ]:
            self.assertIn(key, d, f"Missing key: {key}")

    def test_D07_augmented_at_is_float(self) -> None:
        from core.projection_surface_bridge import RuntimeAugmentation
        aug = RuntimeAugmentation()
        self.assertIsInstance(aug.augmented_at, float)
        self.assertGreater(aug.augmented_at, 0.0)

    def test_D08_constructable_with_values(self) -> None:
        from core.projection_surface_bridge import RuntimeAugmentation
        aug = RuntimeAugmentation(
            active_task_count=3,
            executor_count=2,
            network_reachable_node_count=5,
            replay_event_count=10,
        )
        self.assertEqual(aug.active_task_count, 3)
        self.assertEqual(aug.executor_count, 2)
        self.assertEqual(aug.network_reachable_node_count, 5)
        self.assertEqual(aug.replay_event_count, 10)


# ===========================================================================
# E)  ProjectionBridgeSnapshot dataclass
# ===========================================================================

class TestE_ProjectionBridgeSnapshot(unittest.TestCase):
    """E) ProjectionBridgeSnapshot dataclass structure."""

    def test_E01_constructable_with_defaults(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        self.assertIsNotNone(snap)

    def test_E02_snapshot_id_is_string(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        self.assertIsInstance(snap.snapshot_id, str)
        self.assertTrue(snap.snapshot_id.startswith("psb_"))

    def test_E03_bridge_authority_field_present(self) -> None:
        from core.projection_surface_bridge import (
            ProjectionBridgeSnapshot,
            PROJECTION_SURFACE_BRIDGE_AUTHORITY,
        )
        snap = ProjectionBridgeSnapshot()
        self.assertEqual(snap.bridge_authority, PROJECTION_SURFACE_BRIDGE_AUTHORITY)

    def test_E04_three_topology_domain_fields_present(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        self.assertIsNotNone(snap.model_provider_topology_domain)
        self.assertIsNotNone(snap.device_network_topology_domain)
        self.assertIsNotNone(snap.task_graph_topology_domain)

    def test_E05_topology_domain_fields_are_distinct(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        domains = [
            snap.model_provider_topology_domain,
            snap.device_network_topology_domain,
            snap.task_graph_topology_domain,
        ]
        self.assertEqual(len(set(domains)), 3)

    def test_E06_projection_derived_fields_list_non_empty(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        self.assertIsInstance(snap.projection_derived_fields, list)
        self.assertGreater(len(snap.projection_derived_fields), 0)

    def test_E07_runtime_augmented_fields_list_non_empty(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        self.assertIsInstance(snap.runtime_augmented_fields, list)
        self.assertGreater(len(snap.runtime_augmented_fields), 0)

    def test_E08_projection_derived_and_augmented_fields_disjoint(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        overlap = set(snap.projection_derived_fields) & set(snap.runtime_augmented_fields)
        self.assertEqual(overlap, set(), f"Overlapping fields: {overlap}")

    def test_E09_to_dict_returns_dict(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        d = snap.to_dict()
        self.assertIsInstance(d, dict)

    def test_E10_to_dict_has_required_keys(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        d = snap.to_dict()
        for key in [
            "snapshot_id",
            "projection_dict",
            "runtime_augmentation",
            "model_provider_topology_domain",
            "device_network_topology_domain",
            "task_graph_topology_domain",
            "projection_derived_fields",
            "runtime_augmented_fields",
            "bridge_authority",
            "assembled_at",
        ]:
            self.assertIn(key, d, f"Missing key: {key}")

    def test_E11_projection_derived_contains_tri_state_phase(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        self.assertIn("tri_state_phase", snap.projection_derived_fields)

    def test_E12_runtime_augmented_contains_active_task_count(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        self.assertIn("active_task_count", snap.runtime_augmented_fields)


# ===========================================================================
# F)  enrich_runtime_projection() — enriches copy, does not mutate
# ===========================================================================

class TestF_EnrichRuntimeProjection(unittest.TestCase):
    """F) enrich_runtime_projection() returns an enriched copy without mutation."""

    def setUp(self) -> None:
        _reset_all()

    def tearDown(self) -> None:
        _reset_all()

    def test_F01_returns_dict(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        result = enrich_runtime_projection({"tri_state_phase": "manifest"})
        self.assertIsInstance(result, dict)

    def test_F02_does_not_mutate_input(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        original = {"tri_state_phase": "manifest", "primary_model_id": "gpt-4o"}
        original_copy = dict(original)
        enrich_runtime_projection(original)
        self.assertEqual(original, original_copy)

    def test_F03_result_is_different_object(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        original = {"tri_state_phase": "manifest"}
        result = enrich_runtime_projection(original)
        self.assertIsNot(result, original)

    def test_F04_result_contains_original_keys(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        original = {"tri_state_phase": "manifest", "primary_model_id": "gpt-4o"}
        result = enrich_runtime_projection(original)
        self.assertEqual(result["tri_state_phase"], "manifest")
        self.assertEqual(result["primary_model_id"], "gpt-4o")

    def test_F05_result_contains_bridge_authority(self) -> None:
        from core.projection_surface_bridge import (
            enrich_runtime_projection,
            PROJECTION_SURFACE_BRIDGE_AUTHORITY,
        )
        result = enrich_runtime_projection({"tri_state_phase": "silent"})
        self.assertEqual(result.get("_bridge_authority"), PROJECTION_SURFACE_BRIDGE_AUTHORITY)

    def test_F06_result_contains_runtime_augmented_fields(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        result = enrich_runtime_projection({})
        self.assertIn("active_task_count", result)
        self.assertIn("executor_count", result)
        self.assertIn("network_reachable_node_count", result)
        self.assertIn("replay_event_count", result)

    def test_F07_enrichment_with_empty_dict(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        result = enrich_runtime_projection({})
        self.assertIsInstance(result, dict)
        self.assertIn("active_task_count", result)


# ===========================================================================
# G)  enrich_runtime_projection() — projection fields not overwritten
# ===========================================================================

class TestG_ProjectionFieldsNotOverwritten(unittest.TestCase):
    """G) Projection-derived fields are never shadowed by runtime augmentation."""

    def setUp(self) -> None:
        _reset_all()

    def tearDown(self) -> None:
        _reset_all()

    def test_G01_tri_state_phase_preserved(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        result = enrich_runtime_projection({"tri_state_phase": "liminal"})
        self.assertEqual(result["tri_state_phase"], "liminal")

    def test_G02_primary_model_id_preserved(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        result = enrich_runtime_projection({"primary_model_id": "claude-3"})
        self.assertEqual(result["primary_model_id"], "claude-3")

    def test_G03_active_weights_preserved(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        weights = {"model_a": 0.7, "model_b": 0.3}
        result = enrich_runtime_projection({"active_weights": weights})
        self.assertEqual(result["active_weights"], weights)

    def test_G04_active_task_count_in_projection_not_overwritten(self) -> None:
        """If projection dict already has active_task_count, it is preserved."""
        from core.projection_surface_bridge import enrich_runtime_projection
        # Projection might include active_task_count — bridge must not overwrite
        result = enrich_runtime_projection({"active_task_count": 99})
        self.assertEqual(result["active_task_count"], 99)

    def test_G05_runtime_augmented_fields_added_when_absent(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        # executor_count not in projection — bridge adds it
        result = enrich_runtime_projection({"tri_state_phase": "silent"})
        self.assertIn("executor_count", result)
        self.assertIsNotNone(result["executor_count"])

    def test_G06_runtime_augmented_field_not_added_if_projection_has_it(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        result = enrich_runtime_projection({"executor_count": 42})
        # Projection's value (42) must be preserved, not overwritten
        self.assertEqual(result["executor_count"], 42)


# ===========================================================================
# H)  build_bridge_snapshot() — returns ProjectionBridgeSnapshot
# ===========================================================================

class TestH_BuildBridgeSnapshot(unittest.TestCase):
    """H) build_bridge_snapshot() returns a valid ProjectionBridgeSnapshot."""

    def setUp(self) -> None:
        _reset_all()

    def tearDown(self) -> None:
        _reset_all()

    def test_H01_returns_projection_bridge_snapshot(self) -> None:
        from core.projection_surface_bridge import (
            build_bridge_snapshot,
            ProjectionBridgeSnapshot,
        )
        snap = build_bridge_snapshot()
        self.assertIsInstance(snap, ProjectionBridgeSnapshot)

    def test_H02_snapshot_has_runtime_augmentation(self) -> None:
        from core.projection_surface_bridge import build_bridge_snapshot, RuntimeAugmentation
        snap = build_bridge_snapshot()
        self.assertIsInstance(snap.runtime_augmentation, RuntimeAugmentation)

    def test_H03_snapshot_has_topology_domain_fields(self) -> None:
        from core.projection_surface_bridge import build_bridge_snapshot
        snap = build_bridge_snapshot()
        self.assertIsNotNone(snap.model_provider_topology_domain)
        self.assertIsNotNone(snap.device_network_topology_domain)
        self.assertIsNotNone(snap.task_graph_topology_domain)

    def test_H04_snapshot_has_bridge_authority(self) -> None:
        from core.projection_surface_bridge import (
            build_bridge_snapshot,
            PROJECTION_SURFACE_BRIDGE_AUTHORITY,
        )
        snap = build_bridge_snapshot()
        self.assertEqual(snap.bridge_authority, PROJECTION_SURFACE_BRIDGE_AUTHORITY)

    def test_H05_snapshot_with_explicit_projection_dict(self) -> None:
        from core.projection_surface_bridge import build_bridge_snapshot
        projection = {"tri_state_phase": "manifest", "primary_model_id": "gpt-4o"}
        snap = build_bridge_snapshot(projection_dict=projection)
        self.assertIsNotNone(snap.projection_dict)
        self.assertEqual(snap.projection_dict.get("tri_state_phase"), "manifest")

    def test_H06_snapshot_projection_dict_not_mutated(self) -> None:
        from core.projection_surface_bridge import build_bridge_snapshot
        projection = {"tri_state_phase": "manifest"}
        original_copy = dict(projection)
        build_bridge_snapshot(projection_dict=projection)
        self.assertEqual(projection, original_copy)

    def test_H07_to_dict_contains_required_keys(self) -> None:
        from core.projection_surface_bridge import build_bridge_snapshot
        snap = build_bridge_snapshot(projection_dict={"tri_state_phase": "silent"})
        d = snap.to_dict()
        for key in ["snapshot_id", "projection_dict", "runtime_augmentation",
                    "bridge_authority", "assembled_at"]:
            self.assertIn(key, d)

    def test_H08_snapshot_id_is_unique(self) -> None:
        from core.projection_surface_bridge import build_bridge_snapshot
        snap1 = build_bridge_snapshot()
        snap2 = build_bridge_snapshot()
        self.assertNotEqual(snap1.snapshot_id, snap2.snapshot_id)


# ===========================================================================
# I)  build_bridge_snapshot() — graceful degradation
# ===========================================================================

class TestI_GracefulDegradation(unittest.TestCase):
    """I) Bridge returns minimal valid snapshot when runtime layers are empty."""

    def setUp(self) -> None:
        _reset_all()

    def tearDown(self) -> None:
        _reset_all()

    def test_I01_snapshot_with_no_runtime_data_does_not_raise(self) -> None:
        from core.projection_surface_bridge import build_bridge_snapshot
        # All runtimes are reset — should not raise
        snap = build_bridge_snapshot(projection_dict={})
        self.assertIsNotNone(snap)

    def test_I02_runtime_augmentation_zero_counts_when_empty(self) -> None:
        from core.projection_surface_bridge import build_bridge_snapshot
        snap = build_bridge_snapshot(projection_dict={})
        aug = snap.runtime_augmentation
        self.assertIsInstance(aug.active_task_count, int)
        self.assertGreaterEqual(aug.active_task_count, 0)
        self.assertIsInstance(aug.executor_count, int)
        self.assertGreaterEqual(aug.executor_count, 0)

    def test_I03_enrich_with_empty_projection_does_not_raise(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        result = enrich_runtime_projection({})
        self.assertIsInstance(result, dict)

    def test_I04_get_runtime_augmentation_does_not_raise_when_empty(self) -> None:
        from core.projection_surface_bridge import get_runtime_augmentation
        aug = get_runtime_augmentation()
        self.assertIsNotNone(aug)

    def test_I05_snapshot_assembled_at_is_recent(self) -> None:
        import time
        from core.projection_surface_bridge import build_bridge_snapshot
        before = time.time()
        snap = build_bridge_snapshot(projection_dict={})
        after = time.time()
        self.assertGreaterEqual(snap.assembled_at, before)
        self.assertLessEqual(snap.assembled_at, after + 1.0)


# ===========================================================================
# J)  get_runtime_augmentation() — shape
# ===========================================================================

class TestJ_GetRuntimeAugmentation(unittest.TestCase):
    """J) get_runtime_augmentation() returns RuntimeAugmentation with correct shape."""

    def setUp(self) -> None:
        _reset_all()

    def tearDown(self) -> None:
        _reset_all()

    def test_J01_returns_runtime_augmentation(self) -> None:
        from core.projection_surface_bridge import get_runtime_augmentation, RuntimeAugmentation
        aug = get_runtime_augmentation()
        self.assertIsInstance(aug, RuntimeAugmentation)

    def test_J02_has_all_expected_fields(self) -> None:
        from core.projection_surface_bridge import get_runtime_augmentation
        aug = get_runtime_augmentation()
        d = aug.to_dict()
        for key in [
            "active_task_count",
            "executor_count",
            "network_reachable_node_count",
            "replay_event_count",
            "operator_snapshot_dict",
            "task_graph_snapshot_dict",
            "augmented_at",
            "_source",
        ]:
            self.assertIn(key, d)

    def test_J03_source_field_contains_bridge_authority(self) -> None:
        from core.projection_surface_bridge import (
            get_runtime_augmentation,
            PROJECTION_SURFACE_BRIDGE_AUTHORITY,
        )
        aug = get_runtime_augmentation()
        self.assertEqual(aug._source, PROJECTION_SURFACE_BRIDGE_AUTHORITY)

    def test_J04_count_fields_are_non_negative_integers(self) -> None:
        from core.projection_surface_bridge import get_runtime_augmentation
        aug = get_runtime_augmentation()
        self.assertGreaterEqual(aug.active_task_count, 0)
        self.assertGreaterEqual(aug.executor_count, 0)
        self.assertGreaterEqual(aug.network_reachable_node_count, 0)
        self.assertGreaterEqual(aug.replay_event_count, 0)


# ===========================================================================
# K)  ProjectionBridgeSnapshot.get_enriched_projection()
# ===========================================================================

class TestK_GetEnrichedProjection(unittest.TestCase):
    """K) get_enriched_projection() merges without shadowing projection fields."""

    def setUp(self) -> None:
        _reset_all()

    def tearDown(self) -> None:
        _reset_all()

    def test_K01_returns_dict(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot, RuntimeAugmentation
        snap = ProjectionBridgeSnapshot(
            projection_dict={"tri_state_phase": "manifest"},
            runtime_augmentation=RuntimeAugmentation(active_task_count=2),
        )
        result = snap.get_enriched_projection()
        self.assertIsInstance(result, dict)

    def test_K02_contains_projection_fields(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot, RuntimeAugmentation
        snap = ProjectionBridgeSnapshot(
            projection_dict={"tri_state_phase": "manifest", "primary_model_id": "gpt-4o"},
            runtime_augmentation=RuntimeAugmentation(),
        )
        result = snap.get_enriched_projection()
        self.assertEqual(result["tri_state_phase"], "manifest")
        self.assertEqual(result["primary_model_id"], "gpt-4o")

    def test_K03_contains_runtime_augmented_fields(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot, RuntimeAugmentation
        snap = ProjectionBridgeSnapshot(
            projection_dict={"tri_state_phase": "manifest"},
            runtime_augmentation=RuntimeAugmentation(active_task_count=5),
        )
        result = snap.get_enriched_projection()
        self.assertEqual(result["active_task_count"], 5)

    def test_K04_projection_field_not_overwritten_by_augmentation(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot, RuntimeAugmentation
        # If projection_dict already has active_task_count, it must be kept
        snap = ProjectionBridgeSnapshot(
            projection_dict={"active_task_count": 99},
            runtime_augmentation=RuntimeAugmentation(active_task_count=1),
        )
        result = snap.get_enriched_projection()
        self.assertEqual(result["active_task_count"], 99)

    def test_K05_contains_bridge_authority_marker(self) -> None:
        from core.projection_surface_bridge import (
            ProjectionBridgeSnapshot,
            RuntimeAugmentation,
            PROJECTION_SURFACE_BRIDGE_AUTHORITY,
        )
        snap = ProjectionBridgeSnapshot(
            projection_dict={"tri_state_phase": "silent"},
            runtime_augmentation=RuntimeAugmentation(),
        )
        result = snap.get_enriched_projection()
        self.assertEqual(result["_bridge_authority"], PROJECTION_SURFACE_BRIDGE_AUTHORITY)

    def test_K06_contains_bridge_snapshot_id(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot, RuntimeAugmentation
        snap = ProjectionBridgeSnapshot(
            projection_dict={},
            runtime_augmentation=RuntimeAugmentation(),
        )
        result = snap.get_enriched_projection()
        self.assertEqual(result["_bridge_snapshot_id"], snap.snapshot_id)

    def test_K07_empty_projection_dict_returns_augmented_fields(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot, RuntimeAugmentation
        snap = ProjectionBridgeSnapshot(
            projection_dict={},
            runtime_augmentation=RuntimeAugmentation(executor_count=3),
        )
        result = snap.get_enriched_projection()
        self.assertEqual(result["executor_count"], 3)

    def test_K08_none_projection_dict_returns_augmented_fields(self) -> None:
        from core.projection_surface_bridge import ProjectionBridgeSnapshot, RuntimeAugmentation
        snap = ProjectionBridgeSnapshot(
            projection_dict=None,
            runtime_augmentation=RuntimeAugmentation(active_task_count=7),
        )
        result = snap.get_enriched_projection()
        self.assertEqual(result.get("active_task_count"), 7)


# ===========================================================================
# L)  No new parallel truth source
# ===========================================================================

class TestL_NoNewTruthSource(unittest.TestCase):
    """L) Bridge snapshot is derived/informational only — not a truth authority."""

    def test_L01_no_truth_source_policy_is_informational(self) -> None:
        from core.projection_surface_bridge import NO_NEW_TRUTH_SOURCE_POLICY
        self.assertIn("informational", NO_NEW_TRUTH_SOURCE_POLICY.lower())

    def test_L02_bridge_authority_sentinel_says_bridge_not_truth(self) -> None:
        from core.projection_surface_bridge import PROJECTION_SURFACE_BRIDGE_AUTHORITY
        # Authority name must say "bridge", not "truth" or "authority" in a
        # way that implies it is a primary truth source
        lower = PROJECTION_SURFACE_BRIDGE_AUTHORITY.lower()
        self.assertIn("bridge", lower)

    def test_L03_projection_surface_bridge_layer_position_above_operator_surface(self) -> None:
        from core.projection_surface_bridge import PROJECTION_SURFACE_BRIDGE_LAYER_POSITION
        from core.operator_surface import OPERATOR_SURFACE_LAYER_POSITION
        # Bridge is above OperatorSurface (layer 10) — it reads from it
        self.assertGreater(
            PROJECTION_SURFACE_BRIDGE_LAYER_POSITION,
            OPERATOR_SURFACE_LAYER_POSITION,
        )

    def test_L04_bridge_snapshot_carries_projection_derived_list(self) -> None:
        """Snapshot explicitly declares which fields are projection-derived."""
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        self.assertGreater(len(snap.projection_derived_fields), 0)

    def test_L05_bridge_snapshot_carries_runtime_augmented_list(self) -> None:
        """Snapshot explicitly declares which fields are runtime-augmented."""
        from core.projection_surface_bridge import ProjectionBridgeSnapshot
        snap = ProjectionBridgeSnapshot()
        self.assertGreater(len(snap.runtime_augmented_fields), 0)

    def test_L06_no_new_truth_source_policy_mentions_canonical_sources(self) -> None:
        from core.projection_surface_bridge import NO_NEW_TRUTH_SOURCE_POLICY
        self.assertIn("canonical", NO_NEW_TRUTH_SOURCE_POLICY.lower())


# ===========================================================================
# M)  Singleton management
# ===========================================================================

class TestM_SingletonManagement(unittest.TestCase):
    """M) get/reset singleton projection surface bridge."""

    def setUp(self) -> None:
        _reset_bridge()

    def tearDown(self) -> None:
        _reset_bridge()

    def test_M01_get_returns_instance(self) -> None:
        from core.projection_surface_bridge import (
            get_projection_surface_bridge,
            ProjectionSurfaceBridge,
        )
        bridge = get_projection_surface_bridge()
        self.assertIsInstance(bridge, ProjectionSurfaceBridge)

    def test_M02_get_returns_same_instance(self) -> None:
        from core.projection_surface_bridge import get_projection_surface_bridge
        b1 = get_projection_surface_bridge()
        b2 = get_projection_surface_bridge()
        self.assertIs(b1, b2)

    def test_M03_reset_creates_new_instance_on_next_get(self) -> None:
        from core.projection_surface_bridge import (
            get_projection_surface_bridge,
            reset_projection_surface_bridge,
        )
        b1 = get_projection_surface_bridge()
        reset_projection_surface_bridge()
        b2 = get_projection_surface_bridge()
        self.assertIsNot(b1, b2)

    def test_M04_reset_does_not_raise(self) -> None:
        from core.projection_surface_bridge import reset_projection_surface_bridge
        reset_projection_surface_bridge()
        reset_projection_surface_bridge()  # double reset safe


# ===========================================================================
# N)  __all__ completeness
# ===========================================================================

class TestN_AllCompleteness(unittest.TestCase):
    """N) __all__ completeness check."""

    def test_N01_all_defined(self) -> None:
        import core.projection_surface_bridge as mod
        self.assertTrue(hasattr(mod, "__all__"))
        self.assertIsInstance(mod.__all__, list)
        self.assertGreater(len(mod.__all__), 0)

    def test_N02_all_authority_sentinels_in_all(self) -> None:
        import core.projection_surface_bridge as mod
        for name in [
            "PROJECTION_SURFACE_BRIDGE_AUTHORITY",
            "PROJECTION_SURFACE_BRIDGE_LAYER_POSITION",
            "PROJECTION_SURFACE_BRIDGE_CONTRACT_VERSION",
            "SURFACE_BRIDGE_CONVERGENCE_POLICY",
        ]:
            self.assertIn(name, mod.__all__, f"Missing: {name}")

    def test_N03_all_topology_sentinels_in_all(self) -> None:
        import core.projection_surface_bridge as mod
        for name in [
            "TOPOLOGY_SEMANTICS_THREE_DOMAINS",
            "MODEL_PROVIDER_TOPOLOGY_DOMAIN",
            "DEVICE_NETWORK_TOPOLOGY_DOMAIN",
            "TASK_GRAPH_TOPOLOGY_DOMAIN",
        ]:
            self.assertIn(name, mod.__all__, f"Missing: {name}")

    def test_N04_all_boundary_sentinels_in_all(self) -> None:
        import core.projection_surface_bridge as mod
        for name in [
            "PROJECTION_DERIVED_BOUNDARY",
            "RUNTIME_AUGMENTED_BOUNDARY",
            "NO_NEW_TRUTH_SOURCE_POLICY",
        ]:
            self.assertIn(name, mod.__all__, f"Missing: {name}")

    def test_N05_all_dataclasses_in_all(self) -> None:
        import core.projection_surface_bridge as mod
        for name in ["RuntimeAugmentation", "ProjectionBridgeSnapshot"]:
            self.assertIn(name, mod.__all__, f"Missing: {name}")

    def test_N06_all_functions_in_all(self) -> None:
        import core.projection_surface_bridge as mod
        for name in [
            "enrich_runtime_projection",
            "build_bridge_snapshot",
            "get_runtime_augmentation",
            "get_projection_surface_bridge",
            "reset_projection_surface_bridge",
        ]:
            self.assertIn(name, mod.__all__, f"Missing: {name}")


# ===========================================================================
# O)  routes/projection.py integration sentinel
# ===========================================================================

class TestO_RoutesIntegrationSentinel(unittest.TestCase):
    """O) core/routes/projection.py wires the bridge integration sentinel."""

    def test_O01_sentinel_importable_from_projection_routes(self) -> None:
        from core.routes.projection import PROJECTION_SURFACE_BRIDGE_INTEGRATED
        self.assertIsInstance(PROJECTION_SURFACE_BRIDGE_INTEGRATED, str)
        self.assertGreater(len(PROJECTION_SURFACE_BRIDGE_INTEGRATED), 0)

    def test_O02_sentinel_contains_integrated(self) -> None:
        from core.routes.projection import PROJECTION_SURFACE_BRIDGE_INTEGRATED
        self.assertIn("INTEGRATED", PROJECTION_SURFACE_BRIDGE_INTEGRATED)

    def test_O03_sentinel_not_unavailable(self) -> None:
        """The bridge is available — sentinel must not indicate unavailable."""
        from core.routes.projection import PROJECTION_SURFACE_BRIDGE_INTEGRATED
        self.assertNotIn("UNAVAILABLE", PROJECTION_SURFACE_BRIDGE_INTEGRATED)


# ===========================================================================
# P)  Integration — bridge snapshot includes projection + operator data
# ===========================================================================

class TestP_Integration(unittest.TestCase):
    """P) Integration — bridge snapshot combines projection and operator data."""

    def setUp(self) -> None:
        _reset_all()

    def tearDown(self) -> None:
        _reset_all()

    def test_P01_snapshot_from_explicit_projection_has_correct_tri_state(self) -> None:
        from core.projection_surface_bridge import build_bridge_snapshot
        snap = build_bridge_snapshot(
            projection_dict={"tri_state_phase": "liminal", "primary_model_id": "gpt-4o"}
        )
        self.assertIsNotNone(snap.projection_dict)
        self.assertEqual(snap.projection_dict.get("tri_state_phase"), "liminal")

    def test_P02_enriched_projection_preserves_model_routing(self) -> None:
        from core.projection_surface_bridge import enrich_runtime_projection
        result = enrich_runtime_projection({
            "tri_state_phase": "manifest",
            "primary_model_id": "claude-3",
            "route_reason": "weight-based selection",
        })
        self.assertEqual(result["primary_model_id"], "claude-3")
        self.assertEqual(result["route_reason"], "weight-based selection")

    def test_P03_bridge_snapshot_to_dict_is_serialisable(self) -> None:
        """Bridge snapshot dict must be JSON-serialisable."""
        import json
        from core.projection_surface_bridge import build_bridge_snapshot
        snap = build_bridge_snapshot(projection_dict={"tri_state_phase": "silent"})
        json.dumps(snap.to_dict())  # should not raise

    def test_P04_runtime_augmentation_to_dict_is_serialisable(self) -> None:
        import json
        from core.projection_surface_bridge import get_runtime_augmentation
        aug = get_runtime_augmentation()
        json.dumps(aug.to_dict())  # should not raise

    def test_P05_bridge_layer_is_above_canonical_stack(self) -> None:
        from core.projection_surface_bridge import PROJECTION_SURFACE_BRIDGE_LAYER_POSITION
        from core.canonical_task import CANONICAL_TASK_LAYER_POSITION
        self.assertGreater(
            PROJECTION_SURFACE_BRIDGE_LAYER_POSITION,
            CANONICAL_TASK_LAYER_POSITION,
        )

    def test_P06_bridge_reads_operator_surface_not_raw_internals(self) -> None:
        """Bridge should reference OperatorSurface, not raw task/network runtimes directly."""
        import inspect
        import core.projection_surface_bridge as mod
        source = inspect.getsource(mod.ProjectionSurfaceBridge.get_runtime_augmentation)
        # The method should use OperatorSurface for the operator snapshot
        self.assertIn("operator_surface", source.lower())


# ===========================================================================
# Q)  Topology domain sentinels — mutually non-overlapping
# ===========================================================================

class TestQ_TopologyDomainNonOverlap(unittest.TestCase):
    """Q) Topology domain sentinels define non-overlapping authorities."""

    def test_Q01_model_provider_domain_does_not_mention_task_graph(self) -> None:
        from core.projection_surface_bridge import MODEL_PROVIDER_TOPOLOGY_DOMAIN
        # Model/provider topology must not bleed into task graph concerns
        self.assertNotIn("TaskGraphRuntime", MODEL_PROVIDER_TOPOLOGY_DOMAIN)

    def test_Q02_device_network_domain_does_not_mention_model_routing(self) -> None:
        from core.projection_surface_bridge import DEVICE_NETWORK_TOPOLOGY_DOMAIN
        self.assertNotIn("TopologyRoutePlan", DEVICE_NETWORK_TOPOLOGY_DOMAIN)

    def test_Q03_task_graph_domain_does_not_mention_model_routing(self) -> None:
        from core.projection_surface_bridge import TASK_GRAPH_TOPOLOGY_DOMAIN
        self.assertNotIn("TopologyRoutePlan", TASK_GRAPH_TOPOLOGY_DOMAIN)

    def test_Q04_model_provider_topology_not_redesigned_in_pr511(self) -> None:
        from core.projection_surface_bridge import MODEL_PROVIDER_TOPOLOGY_DOMAIN
        # Model topology should note it is not redesigned in this PR
        self.assertIn("PR-511", MODEL_PROVIDER_TOPOLOGY_DOMAIN)

    def test_Q05_three_domains_sentinel_disambiguates_all_three(self) -> None:
        from core.projection_surface_bridge import TOPOLOGY_SEMANTICS_THREE_DOMAINS
        self.assertIn("1.", TOPOLOGY_SEMANTICS_THREE_DOMAINS)
        self.assertIn("2.", TOPOLOGY_SEMANTICS_THREE_DOMAINS)
        self.assertIn("3.", TOPOLOGY_SEMANTICS_THREE_DOMAINS)

    def test_Q06_three_domains_sentinel_recommends_qualified_names(self) -> None:
        from core.projection_surface_bridge import TOPOLOGY_SEMANTICS_THREE_DOMAINS
        self.assertIn("model_provider_topology", TOPOLOGY_SEMANTICS_THREE_DOMAINS)
        self.assertIn("device_network_topology", TOPOLOGY_SEMANTICS_THREE_DOMAINS)
        self.assertIn("task_graph_topology", TOPOLOGY_SEMANTICS_THREE_DOMAINS)


if __name__ == "__main__":
    unittest.main()
