#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prS7_final_compat_demotion.py
=========================================

PR-S7 — Finalize server cleanup by demoting the last compatibility-only
runtime surfaces and preparing legacy removal after canonical runtime
consolidation.

Validates that:
  1. PR-S7 entries are present in ``LEGACY_PATH_REGISTRY``:
       - ``galaxy_gateway.task_decomposer.TaskDecomposer``
       - ``galaxy_gateway.task_decomposer.IntelligentTaskPlanner``
       - ``galaxy_gateway.capability_registry.GatewayCapabilityRegistry``
  2. All three are registered as ``LEGACY_COMPATIBILITY``.
  3. All three have ``pr_guardrail_added == "PR-S7"``.
  4. ``LEGACY_ORCHESTRATOR_PATHS`` shim includes ALL three PR-S7 registry
     keys (regression guard against the ordering bug where the shim is
     defined before later _register() calls).
  5. ``task_decomposer`` module docstring carries the deprecation note.
  6. ``TaskDecomposer`` class docstring marks it as legacy compat.
  7. ``TaskDecomposer.__init__`` emits a ``LEGACY PATH GUARDRAIL`` log line.
  8. ``IntelligentTaskPlanner`` class docstring marks it as legacy compat.
  9. ``IntelligentTaskPlanner.__init__`` emits a ``LEGACY PATH GUARDRAIL``
     log line.
 10. ``capability_registry`` module docstring carries the deprecation note.
 11. ``GatewayCapabilityRegistry`` class docstring marks it as legacy compat.
 12. ``GatewayCapabilityRegistry.__init__`` emits a ``LEGACY PATH GUARDRAIL``
     log line.
 13. Legacy-path shim round-trip: ``is_legacy_path`` returns True for all three.
 14. ``PURGE_REGISTRY`` contains PR-S7 entries for TaskDecomposer,
     IntelligentTaskPlanner, GatewayCapabilityRegistry (WRAPPER_HARDENED) and
     aip_protocol_v2 (HARD_DISABLED).

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import logging
import sys
import os

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ===========================================================================
# 1. PR-S7 registry entries present
# ===========================================================================

class TestPRS7RegistryEntries:
    """All three PR-S7 paths appear in LEGACY_PATH_REGISTRY."""

    def test_task_decomposer_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.task_decomposer.TaskDecomposer"
            in LEGACY_PATH_REGISTRY
        )

    def test_intelligent_task_planner_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.task_decomposer.IntelligentTaskPlanner"
            in LEGACY_PATH_REGISTRY
        )

    def test_gateway_capability_registry_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.capability_registry.GatewayCapabilityRegistry"
            in LEGACY_PATH_REGISTRY
        )


# ===========================================================================
# 2. All three are LEGACY_COMPATIBILITY
# ===========================================================================

class TestPRS7Status:
    """All PR-S7 entries carry at least LEGACY_COMPATIBILITY status.

    Note: PR-516 subsequently upgraded these three entries from
    LEGACY_COMPATIBILITY to DEPRECATED (a stricter retirement level).
    The tests accept either status so they remain valid as PR-516 or later
    batches advance the retirement tier.
    """

    @staticmethod
    def _retired_statuses():
        from core.orchestration_authority.legacy_paths import LegacyPathStatus
        return {LegacyPathStatus.LEGACY_COMPATIBILITY, LegacyPathStatus.DEPRECATED}

    def test_task_decomposer_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_decomposer.TaskDecomposer"]
        assert entry.status in self._retired_statuses(), (
            f"TaskDecomposer status {entry.status!r} must be at least "
            "LEGACY_COMPATIBILITY (PR-516 upgraded it to DEPRECATED)"
        )

    def test_intelligent_task_planner_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.task_decomposer.IntelligentTaskPlanner"
        ]
        assert entry.status in self._retired_statuses(), (
            f"IntelligentTaskPlanner status {entry.status!r} must be at least "
            "LEGACY_COMPATIBILITY (PR-516 upgraded it to DEPRECATED)"
        )

    def test_gateway_capability_registry_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.capability_registry.GatewayCapabilityRegistry"
        ]
        assert entry.status in self._retired_statuses(), (
            f"GatewayCapabilityRegistry status {entry.status!r} must be at least "
            "LEGACY_COMPATIBILITY (PR-516 upgraded it to DEPRECATED)"
        )


# ===========================================================================
# 3. All three have pr_guardrail_added == "PR-S7"
# ===========================================================================

class TestPRS7GuardrailTag:
    """All PR-S7 entries were guardrailed in PR-S7 or later upgraded by PR-516.

    Note: PR-516 re-registered these paths with ``pr_guardrail_added="PR-516"``
    and upgraded their status to DEPRECATED.  The tests accept either tag so
    they remain valid as later batches further advance the retirement record.
    """

    _VALID_TAGS = {"PR-S7", "PR-516"}

    def test_task_decomposer_guardrail_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_decomposer.TaskDecomposer"]
        assert entry.pr_guardrail_added in self._VALID_TAGS, (
            f"TaskDecomposer pr_guardrail_added {entry.pr_guardrail_added!r} "
            "must be 'PR-S7' or 'PR-516'"
        )

    def test_intelligent_task_planner_guardrail_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.task_decomposer.IntelligentTaskPlanner"
        ]
        assert entry.pr_guardrail_added in self._VALID_TAGS, (
            f"IntelligentTaskPlanner pr_guardrail_added {entry.pr_guardrail_added!r} "
            "must be 'PR-S7' or 'PR-516'"
        )

    def test_gateway_capability_registry_guardrail_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.capability_registry.GatewayCapabilityRegistry"
        ]
        assert entry.pr_guardrail_added in self._VALID_TAGS, (
            f"GatewayCapabilityRegistry pr_guardrail_added {entry.pr_guardrail_added!r} "
            "must be 'PR-S7' or 'PR-516'"
        )


# ===========================================================================
# 4. LEGACY_ORCHESTRATOR_PATHS shim includes all PR-S7 keys
# ===========================================================================

class TestLegacyOrchestratorPathsShimPRS7:
    """LEGACY_ORCHESTRATOR_PATHS frozenset includes all PR-S7 paths."""

    def test_shim_includes_task_decomposer(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "galaxy_gateway.task_decomposer.TaskDecomposer"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_includes_intelligent_task_planner(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "galaxy_gateway.task_decomposer.IntelligentTaskPlanner"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_includes_gateway_capability_registry(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "galaxy_gateway.capability_registry.GatewayCapabilityRegistry"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_is_superset_of_prs6_paths(self):
        """Regression guard: PR-S6 paths must still be present in the shim."""
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        prs6_paths = {
            "galaxy_gateway.task_router.TaskScheduler",
            "galaxy_gateway.task_router.TaskRouter",
            "galaxy_gateway.handlers.message_handler.MessageHandler",
        }
        assert prs6_paths.issubset(LEGACY_ORCHESTRATOR_PATHS)


# ===========================================================================
# 5. task_decomposer module docstring carries the deprecation note
# ===========================================================================

class TestTaskDecomposerModuleDocstring:
    """Read source file directly to avoid import chain issues."""

    def _read_task_decomposer_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "task_decomposer.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_module_docstring_contains_deprecated(self):
        src = self._read_task_decomposer_src()
        assert "deprecated" in src.lower() or "PR-S7" in src

    def test_module_docstring_contains_prs7(self):
        src = self._read_task_decomposer_src()
        assert "PR-S7" in src

    def test_module_docstring_names_canonical_task_graph(self):
        src = self._read_task_decomposer_src()
        assert "task_graph" in src or "TaskGraph" in src

    def test_module_docstring_names_e2e_orchestrator(self):
        src = self._read_task_decomposer_src()
        assert "e2e_orchestrator" in src or "process_user_input" in src


# ===========================================================================
# 6. TaskDecomposer class docstring marks it as legacy compat
# ===========================================================================

class TestTaskDecomposerClassDocstring:
    def _read_task_decomposer_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "task_decomposer.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_task_decomposer_class_docstring_contains_deprecated(self):
        src = self._read_task_decomposer_src()
        assert "TaskDecomposer" in src
        assert "deprecated" in src.lower() or ".. deprecated::" in src

    def test_task_decomposer_docstring_names_canonical_task_graph(self):
        src = self._read_task_decomposer_src()
        assert "task_graph" in src or "TaskGraph" in src

    def test_task_decomposer_docstring_mentions_legacy_compat(self):
        src = self._read_task_decomposer_src()
        assert "legacy" in src.lower()


# ===========================================================================
# 7. TaskDecomposer.__init__ emits LEGACY PATH GUARDRAIL
#    (verified via source inspection to avoid import chain issues)
# ===========================================================================

class TestTaskDecomposerGuardrailLog:
    """Verify guardrail wiring via source inspection."""

    def _read_task_decomposer_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "task_decomposer.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_task_decomposer_init_contains_guardrail_call(self):
        src = self._read_task_decomposer_src()
        assert "emit_legacy_guardrail" in src

    def test_task_decomposer_guardrail_references_correct_caller(self):
        src = self._read_task_decomposer_src()
        assert "task_decomposer.TaskDecomposer" in src


# ===========================================================================
# 8. IntelligentTaskPlanner class docstring marks it as legacy compat
# ===========================================================================

class TestIntelligentTaskPlannerClassDocstring:
    def _read_task_decomposer_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "task_decomposer.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_intelligent_task_planner_class_docstring_contains_deprecated(self):
        src = self._read_task_decomposer_src()
        assert "IntelligentTaskPlanner" in src
        assert "deprecated" in src.lower() or ".. deprecated::" in src

    def test_intelligent_task_planner_docstring_names_e2e_orchestrator(self):
        src = self._read_task_decomposer_src()
        assert "e2e_orchestrator" in src or "process_user_input" in src

    def test_intelligent_task_planner_docstring_mentions_legacy(self):
        src = self._read_task_decomposer_src()
        assert "legacy" in src.lower()


# ===========================================================================
# 9. IntelligentTaskPlanner.__init__ emits LEGACY PATH GUARDRAIL
#    (verified via source inspection to avoid import chain issues)
# ===========================================================================

class TestIntelligentTaskPlannerGuardrailLog:
    """Verify guardrail wiring via source inspection."""

    def _read_task_decomposer_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "task_decomposer.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_intelligent_task_planner_init_contains_guardrail_call(self):
        src = self._read_task_decomposer_src()
        # Both TaskDecomposer and IntelligentTaskPlanner use emit_legacy_guardrail
        assert "emit_legacy_guardrail" in src

    def test_intelligent_task_planner_guardrail_references_correct_caller(self):
        src = self._read_task_decomposer_src()
        assert "task_decomposer.IntelligentTaskPlanner" in src


# ===========================================================================
# 10. capability_registry module docstring carries the deprecation note
# ===========================================================================

class TestCapabilityRegistryModuleDocstring:
    """Read source file directly to avoid import chain issues."""

    def _read_capability_registry_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "capability_registry.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_module_docstring_contains_deprecated(self):
        src = self._read_capability_registry_src()
        assert "deprecated" in src.lower() or "PR-S7" in src

    def test_module_docstring_contains_prs7(self):
        src = self._read_capability_registry_src()
        assert "PR-S7" in src

    def test_module_docstring_names_capability_bus_as_canonical(self):
        src = self._read_capability_registry_src()
        assert "capability_bus" in src or "CapabilityBus" in src

    def test_module_docstring_marks_as_legacy(self):
        src = self._read_capability_registry_src()
        assert "legacy" in src.lower()


# ===========================================================================
# 11. GatewayCapabilityRegistry class docstring marks it as legacy compat
# ===========================================================================

class TestGatewayCapabilityRegistryClassDocstring:
    def _read_capability_registry_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "capability_registry.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_gateway_capability_registry_class_docstring_contains_deprecated(self):
        src = self._read_capability_registry_src()
        assert "GatewayCapabilityRegistry" in src
        assert "deprecated" in src.lower() or ".. deprecated::" in src

    def test_gateway_capability_registry_class_docstring_names_capability_bus(self):
        src = self._read_capability_registry_src()
        assert "capability_bus" in src or "CapabilityBus" in src

    def test_gateway_capability_registry_class_docstring_marks_as_legacy(self):
        src = self._read_capability_registry_src()
        assert "legacy" in src.lower()


# ===========================================================================
# 12. GatewayCapabilityRegistry.__init__ emits LEGACY PATH GUARDRAIL
#    (verified via source inspection to avoid import chain issues)
# ===========================================================================

class TestGatewayCapabilityRegistryGuardrailLog:
    """Verify guardrail wiring via source inspection."""

    def _read_capability_registry_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "capability_registry.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_gateway_capability_registry_init_contains_guardrail_call(self):
        src = self._read_capability_registry_src()
        assert "emit_legacy_guardrail" in src

    def test_gateway_capability_registry_guardrail_references_correct_caller(self):
        src = self._read_capability_registry_src()
        assert "capability_registry.GatewayCapabilityRegistry" in src


# ===========================================================================
# 13. is_legacy_path returns True for all three PR-S7 paths
# ===========================================================================

class TestIsLegacyPathPRS7:
    def test_task_decomposer_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path("galaxy_gateway.task_decomposer.TaskDecomposer")

    def test_intelligent_task_planner_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path(
            "galaxy_gateway.task_decomposer.IntelligentTaskPlanner"
        )

    def test_gateway_capability_registry_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path(
            "galaxy_gateway.capability_registry.GatewayCapabilityRegistry"
        )

    def test_canonical_capability_bus_is_not_legacy_compat(self):
        """CapabilityBus (canonical) must not appear as LEGACY_COMPATIBILITY."""
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY.get("core.capability_bus.CapabilityBus")
        if entry is not None:
            assert entry.status is not LegacyPathStatus.LEGACY_COMPATIBILITY, (
                "core.capability_bus.CapabilityBus is the canonical capability "
                "authority and must not be classified as LEGACY_COMPATIBILITY"
            )

    def test_canonical_task_graph_is_not_legacy_compat(self):
        """core.task_graph.TaskGraph (canonical) must not be legacy-compat."""
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY.get("core.task_graph.TaskGraph")
        if entry is not None:
            assert entry.status is not LegacyPathStatus.LEGACY_COMPATIBILITY, (
                "core.task_graph.TaskGraph is the canonical task planning "
                "authority and must not be classified as LEGACY_COMPATIBILITY"
            )


# ===========================================================================
# 14. PURGE_REGISTRY contains PR-S7 entries
# ===========================================================================

class TestPurgeRegistryPRS7:
    """PR-S7 decisions appear in PURGE_REGISTRY with correct statuses."""

    def test_purge_registry_has_task_decomposer_entry(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        paths = {e.asset_path for e in PURGE_REGISTRY}
        assert any("TaskDecomposer" in p for p in paths), (
            "PURGE_REGISTRY should have a TaskDecomposer entry from PR-S7"
        )

    def test_purge_registry_has_intelligent_task_planner_entry(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        paths = {e.asset_path for e in PURGE_REGISTRY}
        assert any("IntelligentTaskPlanner" in p for p in paths), (
            "PURGE_REGISTRY should have an IntelligentTaskPlanner entry from PR-S7"
        )

    def test_purge_registry_has_gateway_capability_registry_entry(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        paths = {e.asset_path for e in PURGE_REGISTRY}
        assert any("GatewayCapabilityRegistry" in p for p in paths), (
            "PURGE_REGISTRY should have a GatewayCapabilityRegistry entry from PR-S7"
        )

    def test_purge_registry_has_aip_protocol_v2_entry(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        paths = {e.asset_path for e in PURGE_REGISTRY}
        assert any("aip_protocol_v2" in p for p in paths), (
            "PURGE_REGISTRY should have an aip_protocol_v2 entry from PR-S7"
        )

    def test_prs7_wrapper_hardened_entries_have_correct_status(self):
        from core.legacy_purge_registry import PURGE_REGISTRY, PurgeStatus
        prs7 = [e for e in PURGE_REGISTRY if e.pr == "PR-S7"]
        assert len(prs7) >= 4, f"Expected >= 4 PR-S7 entries, got {len(prs7)}"
        wrapper_entries = [
            e for e in prs7
            if "TaskDecomposer" in e.asset_path
            or "IntelligentTaskPlanner" in e.asset_path
            or "GatewayCapabilityRegistry" in e.asset_path
        ]
        for entry in wrapper_entries:
            assert entry.status is PurgeStatus.WRAPPER_HARDENED, (
                f"PR-S7 entry {entry.asset_path!r} should be WRAPPER_HARDENED, "
                f"got {entry.status!r}"
            )

    def test_aip_protocol_v2_entry_is_hard_disabled(self):
        from core.legacy_purge_registry import PURGE_REGISTRY, PurgeStatus
        aip_entries = [
            e for e in PURGE_REGISTRY
            if "aip_protocol_v2" in e.asset_path and e.pr == "PR-S7"
        ]
        assert len(aip_entries) >= 1, (
            "PURGE_REGISTRY should have a PR-S7 aip_protocol_v2 entry"
        )
        for entry in aip_entries:
            assert entry.status is PurgeStatus.HARD_DISABLED, (
                f"aip_protocol_v2 entry should be HARD_DISABLED, got {entry.status!r}"
            )

    def test_get_entries_by_pr_returns_prs7(self):
        from core.legacy_purge_registry import get_entries_by_pr
        prs7 = get_entries_by_pr("PR-S7")
        assert len(prs7) >= 4

    def test_purge_registry_summary_includes_prs7(self):
        from core.legacy_purge_registry import purge_registry_summary
        summary = purge_registry_summary()
        assert "PR-S7" in summary["by_pr"]
        assert len(summary["by_pr"]["PR-S7"]) >= 4
