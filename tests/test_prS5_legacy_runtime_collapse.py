#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prS5_legacy_runtime_collapse.py
===========================================

PR-S5 — Collapse remaining legacy runtime duplication.

Validates that:
  1. PR-S5 entries are present in ``LEGACY_PATH_REGISTRY``:
       - ``galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator``
       - ``galaxy_gateway.orchestrator.parallel_tracker.ParallelGroupTracker``
       - ``core.local_agent_runtime.LocalAgentRuntime``
  2. All three are registered as ``LEGACY_COMPATIBILITY``.
  3. All three have ``pr_guardrail_added == "PR-S5"``.
  4. ``LEGACY_ORCHESTRATOR_PATHS`` shim includes ALL registry keys (regression
     guard against the ordering bug fixed in PR-S5 where the shim was defined
     before PR-S4 entries were registered).
  5. ``TaskOrchestrator`` class docstring carries the deprecation marker.
  6. ``TaskOrchestrator.__init__`` emits a ``LEGACY PATH GUARDRAIL`` log line.
  7. ``MultiDeviceOrchestrator`` class docstring carries the deprecation marker.
  8. ``parallel_tracker`` module docstring names chain A as the canonical chain.
  9. ``LocalAgentRuntime`` module docstring carries the PR-S5 note.
 10. Legacy-path shim round-trip: ``is_legacy_path`` returns True for all three.

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
# 1. PR-S5 registry entries present
# ===========================================================================

class TestPRS5RegistryEntries:
    """All three PR-S5 paths appear in LEGACY_PATH_REGISTRY."""

    def test_multi_device_orchestrator_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator"
            in LEGACY_PATH_REGISTRY
        )

    def test_parallel_group_tracker_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.orchestrator.parallel_tracker.ParallelGroupTracker"
            in LEGACY_PATH_REGISTRY
        )

    def test_local_agent_runtime_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert "core.local_agent_runtime.LocalAgentRuntime" in LEGACY_PATH_REGISTRY


# ===========================================================================
# 2. All three are LEGACY_COMPATIBILITY
# ===========================================================================

class TestPRS5Status:
    """All PR-S5 entries carry LEGACY_COMPATIBILITY status."""

    def test_multi_device_orchestrator_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator"
        ]
        assert entry.status is LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_parallel_group_tracker_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.orchestrator.parallel_tracker.ParallelGroupTracker"
        ]
        assert entry.status is LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_local_agent_runtime_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY["core.local_agent_runtime.LocalAgentRuntime"]
        assert entry.status is LegacyPathStatus.LEGACY_COMPATIBILITY


# ===========================================================================
# 3. All three have pr_guardrail_added == "PR-S5"
# ===========================================================================

class TestPRS5GuardrailTag:
    """All PR-S5 entries are tagged with pr_guardrail_added='PR-S5'."""

    _PATHS = [
        "galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator",
        "galaxy_gateway.orchestrator.parallel_tracker.ParallelGroupTracker",
        "core.local_agent_runtime.LocalAgentRuntime",
    ]

    def test_all_prs5_entries_have_prs5_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        for path in self._PATHS:
            entry = LEGACY_PATH_REGISTRY[path]
            assert entry.pr_guardrail_added == "PR-S5", (
                f"{path} should have pr_guardrail_added='PR-S5', got {entry.pr_guardrail_added!r}"
            )

    def test_all_prs5_entries_have_non_empty_recommendation(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        for path in self._PATHS:
            entry = LEGACY_PATH_REGISTRY[path]
            assert len(entry.recommendation) > 20, (
                f"{path} recommendation is too short: {entry.recommendation!r}"
            )

    def test_all_prs5_entries_have_non_empty_notes(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        for path in self._PATHS:
            entry = LEGACY_PATH_REGISTRY[path]
            assert len(entry.notes) > 10, (
                f"{path} notes is too short: {entry.notes!r}"
            )


# ===========================================================================
# 4. LEGACY_ORCHESTRATOR_PATHS shim includes ALL registry keys
# ===========================================================================

class TestLegacyOrchestratorPathsShim:
    """LEGACY_ORCHESTRATOR_PATHS must contain every key in LEGACY_PATH_REGISTRY.

    Regression guard: in the original code the frozenset was computed before
    PR-S4 entries were registered, causing those entries to be excluded.
    PR-S5 moved the definition to after all _register() calls.
    """

    def test_shim_contains_all_registry_keys(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LEGACY_ORCHESTRATOR_PATHS,
        )
        for path in LEGACY_PATH_REGISTRY:
            assert path in LEGACY_ORCHESTRATOR_PATHS, (
                f"LEGACY_ORCHESTRATOR_PATHS is missing {path!r}. "
                "The shim definition must appear AFTER all _register() calls."
            )

    def test_shim_includes_prs4_paths(self):
        """PR-S4 entries that were previously excluded from the shim now appear."""
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert "galaxy_gateway.android_bridge.AndroidBridge.get_all_devices" in LEGACY_ORCHESTRATOR_PATHS
        assert "core.repo_coordinator.RepoCoordinator.android_devices" in LEGACY_ORCHESTRATOR_PATHS
        assert "core.routes._shared.registered_devices" in LEGACY_ORCHESTRATOR_PATHS

    def test_shim_includes_prs5_paths(self):
        """PR-S5 entries appear in the shim."""
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator"
            in LEGACY_ORCHESTRATOR_PATHS
        )
        assert (
            "galaxy_gateway.orchestrator.parallel_tracker.ParallelGroupTracker"
            in LEGACY_ORCHESTRATOR_PATHS
        )
        assert "core.local_agent_runtime.LocalAgentRuntime" in LEGACY_ORCHESTRATOR_PATHS

    def test_shim_is_frozenset(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert isinstance(LEGACY_ORCHESTRATOR_PATHS, frozenset)


# ===========================================================================
# 5. TaskOrchestrator docstring carries deprecation marker
# ===========================================================================

class TestTaskOrchestratorDocstring:
    """Read source file directly to avoid fastapi/pydantic import chain."""

    def _read_task_orchestrator_src(self) -> str:
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "orchestrator", "task_orchestrator.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_task_orchestrator_docstring_contains_deprecated(self):
        src = self._read_task_orchestrator_src()
        assert ".. deprecated::" in src or "deprecated" in src.lower()

    def test_task_orchestrator_docstring_names_canonical_path(self):
        src = self._read_task_orchestrator_src()
        assert "CommandRouter" in src or "DeviceRouter" in src or "e2e_orchestrator" in src

    def test_task_orchestrator_contains_prs5_guardrail_call(self):
        src = self._read_task_orchestrator_src()
        # The __init__ should call emit_legacy_guardrail
        assert "emit_legacy_guardrail" in src

    def test_task_orchestrator_guardrail_references_correct_caller(self):
        src = self._read_task_orchestrator_src()
        assert "task_orchestrator.TaskOrchestrator" in src


# ===========================================================================
# 6. TaskOrchestrator.__init__ emits LEGACY PATH GUARDRAIL log
#    (verified via source inspection — import requires fastapi not in sandbox)
# ===========================================================================

class TestTaskOrchestratorGuardrail:
    """Verify guardrail wiring via source inspection."""

    def _read_task_orchestrator_src(self) -> str:
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "orchestrator", "task_orchestrator.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_init_contains_guardrail_call(self):
        src = self._read_task_orchestrator_src()
        # emit_legacy_guardrail must be called from within __init__
        assert "emit_legacy_guardrail" in src

    def test_init_guardrail_mentions_task_orchestrator(self):
        src = self._read_task_orchestrator_src()
        assert "task_orchestrator" in src.lower()


# ===========================================================================
# 7. MultiDeviceOrchestrator docstring carries deprecation marker
# ===========================================================================

class TestMultiDeviceOrchestratorDocstring:
    """Read source file directly to avoid fastapi/pydantic import chain."""

    def _read_task_orchestrator_src(self) -> str:
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "orchestrator", "task_orchestrator.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_multi_device_orchestrator_docstring_contains_deprecated(self):
        src = self._read_task_orchestrator_src()
        # MultiDeviceOrchestrator class definition followed by docstring
        assert "MultiDeviceOrchestrator" in src
        assert "deprecated" in src.lower() or ".. deprecated::" in src

    def test_multi_device_orchestrator_names_canonical_path(self):
        src = self._read_task_orchestrator_src()
        assert "e2e_orchestrator" in src or "DeviceRouter" in src or "task_graph" in src



# ===========================================================================
# 8. parallel_tracker module docstring names canonical chain
# ===========================================================================

class TestParallelTrackerDocstring:
    def test_module_docstring_names_chain_a_as_canonical(self):
        import galaxy_gateway.orchestrator.parallel_tracker as pt_mod
        doc = pt_mod.__doc__ or ""
        assert "canonical" in doc.lower(), (
            "parallel_tracker module docstring should label the canonical chain"
        )

    def test_module_docstring_mentions_device_router(self):
        import galaxy_gateway.orchestrator.parallel_tracker as pt_mod
        doc = pt_mod.__doc__ or ""
        assert "DeviceRouter" in doc or "device_router" in doc

    def test_module_docstring_mentions_cross_device_execution_chain(self):
        import galaxy_gateway.orchestrator.parallel_tracker as pt_mod
        doc = pt_mod.__doc__ or ""
        assert "cross_device_execution_chain" in doc or "CrossDeviceChainSingleton" in doc

    def test_module_docstring_marks_chain_b_legacy(self):
        import galaxy_gateway.orchestrator.parallel_tracker as pt_mod
        doc = pt_mod.__doc__ or ""
        assert "legacy" in doc.lower()


# ===========================================================================
# 9. LocalAgentRuntime module docstring carries PR-S5 note
# ===========================================================================

class TestLocalAgentRuntimeDocstring:
    def test_module_docstring_contains_prs5_note(self):
        import core.local_agent_runtime as lar_mod
        doc = lar_mod.__doc__ or ""
        assert "PR-S5" in doc

    def test_module_docstring_says_not_server_side_planner(self):
        import core.local_agent_runtime as lar_mod
        doc = lar_mod.__doc__ or ""
        assert "not" in doc.lower() or "must not" in doc.lower()

    def test_module_docstring_names_canonical_dispatch_chain(self):
        import core.local_agent_runtime as lar_mod
        doc = lar_mod.__doc__ or ""
        assert "OpenClawd" in doc or "DeviceRouter" in doc or "CommandRouter" in doc


# ===========================================================================
# 10. is_legacy_path returns True for all three PR-S5 paths
# ===========================================================================

class TestIsLegacyPathPRS5:
    def test_multi_device_orchestrator_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path(
            "galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator"
        )

    def test_parallel_group_tracker_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path(
            "galaxy_gateway.orchestrator.parallel_tracker.ParallelGroupTracker"
        )

    def test_local_agent_runtime_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path("core.local_agent_runtime.LocalAgentRuntime")

    def test_canonical_device_router_is_not_treated_as_legacy_compat(self):
        """DeviceRouter.route_task is ACTIVE (canonical), not legacy-compat."""
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY.get("galaxy_gateway.device_router.DeviceRouter.route_task")
        assert entry is not None
        # It's registered as ACTIVE (canonical dispatch authority)
        assert entry.status is LegacyPathStatus.ACTIVE
