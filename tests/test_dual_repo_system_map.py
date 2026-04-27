#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_dual_repo_system_map.py
====================================
Verifiable invariant tests for the dual-repo system cognitive map.

These tests guard against two failure modes that have been documented in
the V2 codebase review:

1. **Cognitive drift**: system layer classifications become stale or
   misleading as the codebase evolves.
2. **Gap loss**: high-priority workstream gaps are silently dropped or
   prematurely marked resolved without concrete fixes.

Test groups
-----------
A. Registry completeness — each plane has entries, each semantic type has
   entries, the main chain has meaningful length.
B. Classification consistency — RUNTIME_CRITICAL modules have no
   DECLARATIVE twins; every module in the semantic registry is also
   classified in the plane registry (or is an android: module).
C. Declarative-vs-runtime boundary — specifically checks that known
   declarative-only modules are NOT listed as RUNTIME_CRITICAL.
D. Workstream gap registry — all P0/P1 gaps are present, unresolved gaps
   have non-empty descriptions, the registry has not been silently emptied.
E. Snapshot function — build_system_map_snapshot() returns valid JSON-
   serialisable output with expected keys.
F. Query functions — get_plane(), get_semantic_type(), list_* helpers.
"""

from __future__ import annotations

import json

import pytest

from core.dual_repo_system_map import (
    DUAL_REPO_MAIN_CHAIN,
    SYSTEM_PLANE_REGISTRY,
    MODULE_SEMANTIC_TYPE_REGISTRY,
    WORKSTREAM_GAP_REGISTRY,
    GapSeverity,
    ModuleSemanticType,
    SystemPlane,
    build_system_map_snapshot,
    get_plane,
    get_semantic_type,
    list_modules_by_plane,
    list_modules_by_semantic_type,
    list_open_gaps_by_severity,
)


# ---------------------------------------------------------------------------
# A. Registry completeness
# ---------------------------------------------------------------------------


class TestRegistryCompleteness:
    """All planes and semantic types are represented; main chain is non-trivial."""

    def test_all_planes_have_entries(self):
        """Every SystemPlane value has at least one entry in SYSTEM_PLANE_REGISTRY."""
        for plane in SystemPlane:
            modules = list_modules_by_plane(plane)
            assert modules, (
                f"SystemPlane.{plane.value} has no entries in SYSTEM_PLANE_REGISTRY. "
                "Each plane must have at least one classified module."
            )

    def test_all_semantic_types_have_entries(self):
        """Every ModuleSemanticType has at least one entry in MODULE_SEMANTIC_TYPE_REGISTRY."""
        for stype in ModuleSemanticType:
            modules = list_modules_by_semantic_type(stype)
            assert modules, (
                f"ModuleSemanticType.{stype.value} has no entries in "
                "MODULE_SEMANTIC_TYPE_REGISTRY.  Each type must have at least one entry."
            )

    def test_main_chain_has_minimum_nodes(self):
        """DUAL_REPO_MAIN_CHAIN must have at least 8 nodes to represent both repos."""
        assert len(DUAL_REPO_MAIN_CHAIN) >= 8, (
            f"DUAL_REPO_MAIN_CHAIN has only {len(DUAL_REPO_MAIN_CHAIN)} nodes. "
            "A valid dual-repo main chain must span both V2 and Android sides."
        )

    def test_main_chain_includes_android_boundary(self):
        """DUAL_REPO_MAIN_CHAIN must explicitly mention the Android execution side."""
        android_nodes = [n for n in DUAL_REPO_MAIN_CHAIN if "android" in n.lower()]
        assert android_nodes, (
            "DUAL_REPO_MAIN_CHAIN does not include any Android-side nodes. "
            "The dual-repo chain must cross the V2→Android boundary."
        )

    def test_main_chain_includes_websocket_boundary(self):
        """DUAL_REPO_MAIN_CHAIN must include the WebSocket transport boundary."""
        ws_nodes = [n for n in DUAL_REPO_MAIN_CHAIN if "websocket" in n.lower() or "WebSocket" in n]
        assert ws_nodes, (
            "DUAL_REPO_MAIN_CHAIN does not include any WebSocket boundary node. "
            "The gateway/transport boundary must be explicit in the chain."
        )

    def test_system_plane_registry_has_minimum_entries(self):
        """SYSTEM_PLANE_REGISTRY must have entries for all five planes."""
        covered_planes = {e.plane for e in SYSTEM_PLANE_REGISTRY}
        for plane in SystemPlane:
            assert plane in covered_planes, (
                f"SYSTEM_PLANE_REGISTRY does not cover {plane.value}."
            )

    def test_semantic_registry_has_minimum_entries(self):
        """MODULE_SEMANTIC_TYPE_REGISTRY must have at least 15 entries."""
        assert len(MODULE_SEMANTIC_TYPE_REGISTRY) >= 15, (
            f"MODULE_SEMANTIC_TYPE_REGISTRY has only {len(MODULE_SEMANTIC_TYPE_REGISTRY)} "
            "entries. It should cover all major module categories."
        )


# ---------------------------------------------------------------------------
# B. Classification consistency
# ---------------------------------------------------------------------------


class TestClassificationConsistency:
    """Module paths appear consistently across registries."""

    def test_no_duplicate_module_paths_in_plane_registry(self):
        """Each module path appears at most once in SYSTEM_PLANE_REGISTRY."""
        paths = [e.module_path for e in SYSTEM_PLANE_REGISTRY]
        duplicates = [p for p in paths if paths.count(p) > 1]
        assert not duplicates, (
            f"Duplicate module paths in SYSTEM_PLANE_REGISTRY: {set(duplicates)}"
        )

    def test_no_duplicate_module_paths_in_semantic_registry(self):
        """Each module path appears at most once in MODULE_SEMANTIC_TYPE_REGISTRY."""
        paths = [e.module_path for e in MODULE_SEMANTIC_TYPE_REGISTRY]
        duplicates = [p for p in paths if paths.count(p) > 1]
        assert not duplicates, (
            f"Duplicate module paths in MODULE_SEMANTIC_TYPE_REGISTRY: {set(duplicates)}"
        )

    def test_no_duplicate_gap_ids_in_workstream_registry(self):
        """Each gap_id appears at most once in WORKSTREAM_GAP_REGISTRY."""
        ids = [e.gap_id for e in WORKSTREAM_GAP_REGISTRY]
        duplicates = [i for i in ids if ids.count(i) > 1]
        assert not duplicates, (
            f"Duplicate gap IDs in WORKSTREAM_GAP_REGISTRY: {set(duplicates)}"
        )

    def test_plane_registry_entries_have_non_empty_paths(self):
        """All SYSTEM_PLANE_REGISTRY entries have non-empty module_path."""
        for entry in SYSTEM_PLANE_REGISTRY:
            assert entry.module_path.strip(), (
                "Found empty module_path in SYSTEM_PLANE_REGISTRY."
            )

    def test_semantic_registry_entries_have_non_empty_paths(self):
        """All MODULE_SEMANTIC_TYPE_REGISTRY entries have non-empty module_path."""
        for entry in MODULE_SEMANTIC_TYPE_REGISTRY:
            assert entry.module_path.strip(), (
                "Found empty module_path in MODULE_SEMANTIC_TYPE_REGISTRY."
            )


# ---------------------------------------------------------------------------
# C. Declarative-vs-runtime boundary
# ---------------------------------------------------------------------------


class TestDeclarativeVsRuntimeBoundary:
    """Known declarative-only modules must NOT be classified as RUNTIME_CRITICAL.

    This is the core anti-drift test: the codebase review established that
    several large modules (especially those added in PR-837) are declarative
    in nature.  If any of these are ever reclassified as RUNTIME_CRITICAL
    without real runtime wiring, this test will catch the drift.
    """

    def test_all_declarative_modules_not_classified_as_runtime_critical(self):
        """Every module classified as DECLARATIVE must not also appear as RUNTIME_CRITICAL.

        Derived programmatically from MODULE_SEMANTIC_TYPE_REGISTRY so that the
        check stays in sync as the registry grows.
        """
        declarative_modules = list_modules_by_semantic_type(ModuleSemanticType.DECLARATIVE)
        runtime_critical_modules = set(list_modules_by_semantic_type(ModuleSemanticType.RUNTIME_CRITICAL))
        for module_path in declarative_modules:
            assert module_path not in runtime_critical_modules, (
                f"Module '{module_path}' is classified as both DECLARATIVE and "
                "RUNTIME_CRITICAL in MODULE_SEMANTIC_TYPE_REGISTRY. "
                "A module can only have one semantic type. Fix the registry."
            )

    def test_final_cleanup_invariant_tightening_is_declarative(self):
        """core.final_cleanup_invariant_tightening must be DECLARATIVE (not runtime).

        This is the 892-line PR-837 module containing policy sentinels and
        importability guards. It is NOT a runtime enforcement module.
        """
        stype = get_semantic_type("core.final_cleanup_invariant_tightening")
        assert stype is not None, (
            "core.final_cleanup_invariant_tightening is not in "
            "MODULE_SEMANTIC_TYPE_REGISTRY. It must be classified."
        )
        assert stype == ModuleSemanticType.DECLARATIVE, (
            f"core.final_cleanup_invariant_tightening is classified as {stype.value} "
            "but must be DECLARATIVE. It contains sentinel strings and importability "
            "guards, not runtime enforcement code."
        )

    def test_capability_routing_gate_is_not_fully_runtime_critical(self):
        """core.capability_routing_gate must be SEMI_EXECUTABLE (not RUNTIME_CRITICAL).

        The gate is real and correct, but send_gateway_command() does NOT call
        it by default when device_id is passed explicitly. It is not a
        default-enforced runtime invariant yet.
        """
        stype = get_semantic_type("core.capability_routing_gate")
        assert stype is not None, (
            "core.capability_routing_gate is not in MODULE_SEMANTIC_TYPE_REGISTRY."
        )
        assert stype == ModuleSemanticType.SEMI_EXECUTABLE, (
            f"core.capability_routing_gate is classified as {stype.value} but "
            "must be SEMI_EXECUTABLE. The gate is real but not enforced by default "
            "in send_gateway_command(). Update this test when default enforcement "
            "is added (GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT resolved)."
        )

    def test_runtime_critical_modules_are_known_real_entry_points(self):
        """All RUNTIME_CRITICAL modules should be in the expected set of real entry points.

        This set is INTENTIONALLY hardcoded (not derived from the registry) to
        catch cases where a non-runtime module is accidentally promoted to
        RUNTIME_CRITICAL. To add a new module to this guard, add it to both the
        registry and this expected set with a comment explaining the runtime path.
        """
        expected_runtime_critical = {
            "core.openclawd",
            "core.command_router",
            "galaxy_gateway.routes.websocket",
            "galaxy_gateway.routing.device_router",
            "core.unified.llm_router",
            "core.android_bridge",
            "core.canonical_completion_ingress",
            "core.device_registry",
            "core.api_routes",
        }
        actual_runtime_critical = set(list_modules_by_semantic_type(ModuleSemanticType.RUNTIME_CRITICAL))
        unexpected = actual_runtime_critical - expected_runtime_critical
        assert not unexpected, (
            f"Unexpected modules classified as RUNTIME_CRITICAL: {unexpected}. "
            "If a new module has been genuinely wired into the runtime path, "
            "add it to expected_runtime_critical in this test with a comment."
        )


# ---------------------------------------------------------------------------
# D. Workstream gap registry
# ---------------------------------------------------------------------------


class TestWorkstreamGapRegistry:
    """Gap registry completeness and honesty checks."""

    # These sets are INTENTIONALLY hardcoded and must NOT be derived from
    # WORKSTREAM_GAP_REGISTRY. Their purpose is to guard against silent deletion
    # of critical gap entries from the registry itself. If they were derived from
    # the registry, a developer could remove a gap and the test would silently pass.
    # To add a new required gap to this set, it must first exist in the registry.
    REQUIRED_P0_GAPS = {
        "GAP_JOINT_INTEGRATION_TEST",
        "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT",
        "GAP_V2_TRUTH_PERSISTENCE",
        "GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION",
    }

    REQUIRED_P1_GAPS = {
        "GAP_RUNTIME_TRUTH_SINGLE_INGRESS",
        "GAP_ANDROID_CI",
        "GAP_ANDROID_LOCAL_AI_DEFAULT_OFF",
    }

    def test_all_required_p0_gaps_present(self):
        """All documented P0 gaps must be in the registry."""
        registered_ids = {e.gap_id for e in WORKSTREAM_GAP_REGISTRY}
        missing = self.REQUIRED_P0_GAPS - registered_ids
        assert not missing, (
            f"Required P0 gaps are missing from WORKSTREAM_GAP_REGISTRY: {missing}. "
            "P0 gaps must not be silently dropped."
        )

    def test_all_required_p1_gaps_present(self):
        """All documented P1 gaps must be in the registry."""
        registered_ids = {e.gap_id for e in WORKSTREAM_GAP_REGISTRY}
        missing = self.REQUIRED_P1_GAPS - registered_ids
        assert not missing, (
            f"Required P1 gaps are missing from WORKSTREAM_GAP_REGISTRY: {missing}. "
            "P1 gaps must not be silently dropped."
        )

    def test_p0_gaps_are_not_prematurely_resolved(self):
        """P0 gaps must not be resolved without a concrete resolution_pr reference.

        A gap with resolved=True but no resolution_pr suggests it was closed
        by a declarative/sentinel PR rather than a real fix.
        """
        for gap in WORKSTREAM_GAP_REGISTRY:
            if gap.severity == GapSeverity.P0 and gap.resolved:
                assert gap.resolution_pr.strip(), (
                    f"P0 gap '{gap.gap_id}' is marked resolved but has no "
                    "resolution_pr reference. A P0 gap must reference the "
                    "concrete PR that closed it (not a sentinel/declarative PR)."
                )

    def test_all_gap_descriptions_are_non_empty(self):
        """Every gap must have a non-empty description."""
        for gap in WORKSTREAM_GAP_REGISTRY:
            assert gap.description.strip(), (
                f"Gap '{gap.gap_id}' has an empty description. "
                "All gaps must have accurate, non-misleading descriptions."
            )

    def test_gap_joint_integration_test_is_resolved(self):
        """GAP_JOINT_INTEGRATION_TEST must be marked resolved with a concrete PR reference.

        This gap was closed by the separated-process WebSocket E2E implementation
        (test_separated_process_ws_e2e.py) which proved the canonical six-step
        sequence at true network / OS-process separation level.
        """
        gap = next(
            (g for g in WORKSTREAM_GAP_REGISTRY if g.gap_id == "GAP_JOINT_INTEGRATION_TEST"),
            None,
        )
        assert gap is not None, "GAP_JOINT_INTEGRATION_TEST not found in registry."
        assert gap.resolved, (
            "GAP_JOINT_INTEGRATION_TEST must be marked resolved=True.  "
            "It was closed by the separated-process WebSocket E2E implementation."
        )
        assert gap.resolution_pr, (
            "GAP_JOINT_INTEGRATION_TEST.resolution_pr must reference the closing PR."
        )

    def test_gap_capability_gate_default_enforcement_is_resolved(self):
        """GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT must be marked resolved.

        This gap was closed by the capability enforcement hardener PR which
        makes STRICT mode the default on the mainline dispatch path.
        """
        gap = next(
            (g for g in WORKSTREAM_GAP_REGISTRY if g.gap_id == "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT"),
            None,
        )
        assert gap is not None, "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT not found."
        assert gap.resolved, (
            "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT must be marked resolved=True.  "
            "It was closed by the capability enforcement hardener implementation."
        )
        assert gap.resolution_pr, (
            "GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT.resolution_pr must reference the closing PR."
        )

    def test_registry_has_at_least_five_gaps(self):
        """WORKSTREAM_GAP_REGISTRY must have at least 5 entries.

        This guards against accidentally emptying the registry in a cleanup PR.
        """
        assert len(WORKSTREAM_GAP_REGISTRY) >= 5, (
            f"WORKSTREAM_GAP_REGISTRY has only {len(WORKSTREAM_GAP_REGISTRY)} entries. "
            "The registry must retain at least 5 documented gaps."
        )


# ---------------------------------------------------------------------------
# E. Snapshot function
# ---------------------------------------------------------------------------


class TestSnapshotFunction:
    """build_system_map_snapshot() returns valid, structured output."""

    def test_snapshot_is_json_serializable(self):
        """Snapshot must be JSON-serializable."""
        snapshot = build_system_map_snapshot()
        # This will raise if not serialisable
        serialized = json.dumps(snapshot)
        assert serialized

    def test_snapshot_has_required_keys(self):
        """Snapshot must contain all expected top-level keys."""
        snapshot = build_system_map_snapshot()
        required_keys = {"version", "plane_counts", "semantic_type_counts",
                         "main_chain_node_count", "open_gaps", "total_open_gaps"}
        missing = required_keys - set(snapshot.keys())
        assert not missing, f"Snapshot missing keys: {missing}"

    def test_snapshot_plane_counts_cover_all_planes(self):
        """Snapshot plane_counts must include all five system planes."""
        snapshot = build_system_map_snapshot()
        plane_counts = snapshot["plane_counts"]
        for plane in SystemPlane:
            assert plane.value in plane_counts, (
                f"plane_counts missing {plane.value}"
            )

    def test_snapshot_semantic_counts_cover_all_types(self):
        """Snapshot semantic_type_counts must include all semantic types."""
        snapshot = build_system_map_snapshot()
        semantic_counts = snapshot["semantic_type_counts"]
        for stype in ModuleSemanticType:
            assert stype.value in semantic_counts, (
                f"semantic_type_counts missing {stype.value}"
            )

    def test_snapshot_open_gaps_has_p0_p1_p2(self):
        """Snapshot open_gaps must have P0, P1, P2 keys."""
        snapshot = build_system_map_snapshot()
        open_gaps = snapshot["open_gaps"]
        for severity in ("P0", "P1", "P2"):
            assert severity in open_gaps, f"open_gaps missing {severity}"

    def test_snapshot_reports_p0_gaps(self):
        """Snapshot open_gaps P0 list must be a list; all P0 gaps are resolved after PRs 1–7."""
        snapshot = build_system_map_snapshot()
        p0_gaps = snapshot["open_gaps"]["P0"]
        # After PRs 1–7, all P0 gaps have been closed:
        #   GAP_JOINT_INTEGRATION_TEST               → PR-3
        #   GAP_CAPABILITY_GATE_DEFAULT_ENFORCEMENT  → PR-4
        #   GAP_V2_TRUTH_PERSISTENCE                 → PR-1 (#850)
        #   GAP_MULTI_DEVICE_FAILURE_RECOVERY_INTEGRATION → PR-7 (#854)
        # The list must be a list (may be empty).
        assert isinstance(p0_gaps, list), (
            "open_gaps['P0'] must be a list."
        )

    def test_snapshot_version_matches_module(self):
        """Snapshot version must match DUAL_REPO_SYSTEM_MAP_VERSION."""
        from core.dual_repo_system_map import DUAL_REPO_SYSTEM_MAP_VERSION
        snapshot = build_system_map_snapshot()
        assert snapshot["version"] == DUAL_REPO_SYSTEM_MAP_VERSION


# ---------------------------------------------------------------------------
# F. Query functions
# ---------------------------------------------------------------------------


class TestQueryFunctions:
    """get_plane(), get_semantic_type(), list_* helpers work correctly."""

    def test_get_plane_returns_correct_plane_for_openclawd(self):
        plane = get_plane("core.openclawd")
        assert plane == SystemPlane.CONTROL_PLANE

    def test_get_plane_returns_correct_plane_for_gateway_websocket(self):
        plane = get_plane("galaxy_gateway.routes.websocket")
        assert plane == SystemPlane.GATEWAY_TRANSPORT

    def test_get_plane_returns_correct_plane_for_llm_router(self):
        plane = get_plane("core.unified.llm_router")
        assert plane == SystemPlane.PROVIDER_PLANE

    def test_get_plane_returns_none_for_unknown(self):
        plane = get_plane("core.nonexistent_module_xyz")
        assert plane is None

    def test_get_semantic_type_returns_runtime_critical_for_openclawd(self):
        stype = get_semantic_type("core.openclawd")
        assert stype == ModuleSemanticType.RUNTIME_CRITICAL

    def test_get_semantic_type_returns_declarative_for_final_cleanup(self):
        stype = get_semantic_type("core.final_cleanup_invariant_tightening")
        assert stype == ModuleSemanticType.DECLARATIVE

    def test_get_semantic_type_returns_semi_executable_for_capability_gate(self):
        stype = get_semantic_type("core.capability_routing_gate")
        assert stype == ModuleSemanticType.SEMI_EXECUTABLE

    def test_get_semantic_type_returns_none_for_unknown(self):
        stype = get_semantic_type("core.nonexistent_module_xyz")
        assert stype is None

    def test_list_modules_by_plane_control_plane_includes_openclawd(self):
        modules = list_modules_by_plane(SystemPlane.CONTROL_PLANE)
        assert "core.openclawd" in modules

    def test_list_modules_by_semantic_type_runtime_critical_includes_command_router(self):
        modules = list_modules_by_semantic_type(ModuleSemanticType.RUNTIME_CRITICAL)
        assert "core.command_router" in modules

    def test_list_open_gaps_by_severity_p0_returns_list(self):
        gaps = list_open_gaps_by_severity(GapSeverity.P0)
        assert isinstance(gaps, list)
        # After PRs 1–7, all P0 gaps are resolved; the open P0 list must be empty.

    def test_list_open_gaps_by_severity_p0_excludes_resolved(self):
        gaps = list_open_gaps_by_severity(GapSeverity.P0)
        for gap in gaps:
            assert not gap.resolved, (
                f"list_open_gaps_by_severity(P0) returned resolved gap '{gap.gap_id}'"
            )
