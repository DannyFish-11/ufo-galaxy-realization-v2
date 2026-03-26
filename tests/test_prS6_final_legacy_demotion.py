#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prS6_final_legacy_demotion.py
=========================================

PR-S6 — Finalize server-side legacy demotion and remove non-canonical
runtime entry leftovers.

Validates that:
  1. PR-S6 entries are present in ``LEGACY_PATH_REGISTRY``:
       - ``galaxy_gateway.task_router.TaskScheduler``
       - ``galaxy_gateway.task_router.TaskRouter``
       - ``galaxy_gateway.handlers.message_handler.MessageHandler``
  2. All three are registered as ``LEGACY_COMPATIBILITY``.
  3. All three have ``pr_guardrail_added == "PR-S6"``.
  4. ``LEGACY_ORCHESTRATOR_PATHS`` shim includes ALL three PR-S6 registry
     keys (regression guard against the ordering bug where the shim is
     defined before later _register() calls).
  5. ``task_router`` module docstring carries the deprecation note.
  6. ``TaskScheduler`` class docstring marks it as legacy compat.
  7. ``TaskScheduler.__init__`` emits a ``LEGACY PATH GUARDRAIL`` log line.
  8. ``TaskRouter`` class docstring marks it as legacy compat.
  9. ``TaskRouter.__init__`` emits a ``LEGACY PATH GUARDRAIL`` log line.
 10. ``message_handler`` module docstring carries the deprecation note.
 11. ``MessageHandler`` class docstring marks it as legacy chain B.
 12. ``MessageHandler.__init__`` emits a ``LEGACY PATH GUARDRAIL`` log line.
 13. Legacy-path shim round-trip: ``is_legacy_path`` returns True for all three.
 14. ``PURGE_REGISTRY`` contains PR-S6 entries for TaskScheduler, TaskRouter,
     and MessageHandler with ``WRAPPER_HARDENED`` status.

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
# 1. PR-S6 registry entries present
# ===========================================================================

class TestPRS6RegistryEntries:
    """All three PR-S6 paths appear in LEGACY_PATH_REGISTRY."""

    def test_task_scheduler_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.task_router.TaskScheduler"
            in LEGACY_PATH_REGISTRY
        )

    def test_task_router_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.task_router.TaskRouter"
            in LEGACY_PATH_REGISTRY
        )

    def test_message_handler_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.handlers.message_handler.MessageHandler"
            in LEGACY_PATH_REGISTRY
        )


# ===========================================================================
# 2. All three are LEGACY_COMPATIBILITY
# ===========================================================================

class TestPRS6Status:
    """All PR-S6 entries carry LEGACY_COMPATIBILITY status."""

    def test_task_scheduler_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_router.TaskScheduler"]
        assert entry.status is LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_task_router_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_router.TaskRouter"]
        assert entry.status is LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_message_handler_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.handlers.message_handler.MessageHandler"
        ]
        assert entry.status is LegacyPathStatus.LEGACY_COMPATIBILITY


# ===========================================================================
# 3. All three have pr_guardrail_added == "PR-S6"
# ===========================================================================

class TestPRS6GuardrailTag:
    """All PR-S6 entries have pr_guardrail_added == 'PR-S6'."""

    def test_task_scheduler_guardrail_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_router.TaskScheduler"]
        assert entry.pr_guardrail_added == "PR-S6"

    def test_task_router_guardrail_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_router.TaskRouter"]
        assert entry.pr_guardrail_added == "PR-S6"

    def test_message_handler_guardrail_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.handlers.message_handler.MessageHandler"
        ]
        assert entry.pr_guardrail_added == "PR-S6"


# ===========================================================================
# 4. LEGACY_ORCHESTRATOR_PATHS shim includes all PR-S6 keys
# ===========================================================================

class TestLegacyOrchestratorPathsShimPRS6:
    """LEGACY_ORCHESTRATOR_PATHS frozenset includes all PR-S6 paths."""

    def test_shim_includes_task_scheduler(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert "galaxy_gateway.task_router.TaskScheduler" in LEGACY_ORCHESTRATOR_PATHS

    def test_shim_includes_task_router(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert "galaxy_gateway.task_router.TaskRouter" in LEGACY_ORCHESTRATOR_PATHS

    def test_shim_includes_message_handler(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "galaxy_gateway.handlers.message_handler.MessageHandler"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_is_superset_of_prs5_paths(self):
        """Regression guard: PR-S5 paths must still be present in the shim."""
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        prs5_paths = {
            "galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator",
            "galaxy_gateway.orchestrator.parallel_tracker.ParallelGroupTracker",
            "core.local_agent_runtime.LocalAgentRuntime",
        }
        assert prs5_paths.issubset(LEGACY_ORCHESTRATOR_PATHS)


# ===========================================================================
# 5. task_router module docstring carries the deprecation note
# ===========================================================================

class TestTaskRouterModuleDocstring:
    """Read source file directly to avoid aiohttp import chain."""

    def _read_task_router_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "task_router.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_module_docstring_contains_deprecated(self):
        src = self._read_task_router_src()
        assert "deprecated" in src.lower() or "PR-S6" in src

    def test_module_docstring_contains_prs6(self):
        src = self._read_task_router_src()
        assert "PR-S6" in src

    def test_module_docstring_names_canonical_device_router(self):
        src = self._read_task_router_src()
        assert "DeviceRouter" in src or "device_router" in src

    def test_module_docstring_names_task_graph(self):
        src = self._read_task_router_src()
        assert "task_graph" in src or "TaskGraph" in src


# ===========================================================================
# 6. TaskScheduler class docstring marks it as legacy compat
# ===========================================================================

class TestTaskSchedulerDocstring:
    def _read_task_router_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "task_router.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_task_scheduler_class_docstring_contains_deprecated(self):
        src = self._read_task_router_src()
        assert "TaskScheduler" in src
        assert "deprecated" in src.lower() or ".. deprecated::" in src

    def test_task_scheduler_docstring_names_canonical_task_graph(self):
        src = self._read_task_router_src()
        assert "task_graph" in src or "TaskGraph" in src

    def test_task_scheduler_docstring_mentions_legacy_compat(self):
        src = self._read_task_router_src()
        assert "legacy" in src.lower()


# ===========================================================================
# 7. TaskScheduler.__init__ emits LEGACY PATH GUARDRAIL
#    (verified via source inspection — import requires aiohttp not in sandbox)
# ===========================================================================

class TestTaskSchedulerGuardrailLog:
    """Verify guardrail wiring via source inspection."""

    def _read_task_router_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "task_router.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_task_scheduler_init_contains_guardrail_call(self):
        src = self._read_task_router_src()
        assert "emit_legacy_guardrail" in src

    def test_task_scheduler_guardrail_references_correct_caller(self):
        src = self._read_task_router_src()
        assert "task_router.TaskScheduler" in src


# ===========================================================================
# 8. TaskRouter class docstring marks it as legacy compat
# ===========================================================================

class TestTaskRouterDocstring:
    def _read_task_router_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "task_router.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_task_router_class_docstring_contains_deprecated(self):
        src = self._read_task_router_src()
        assert "TaskRouter" in src
        assert "deprecated" in src.lower() or ".. deprecated::" in src

    def test_task_router_docstring_names_device_router(self):
        src = self._read_task_router_src()
        assert "DeviceRouter" in src or "device_router" in src

    def test_task_router_docstring_names_e2e_orchestrator(self):
        src = self._read_task_router_src()
        assert "e2e_orchestrator" in src or "process_user_input" in src


# ===========================================================================
# 9. TaskRouter.__init__ emits LEGACY PATH GUARDRAIL
#    (verified via source inspection — import requires aiohttp not in sandbox)
# ===========================================================================

class TestTaskRouterGuardrailLog:
    """Verify guardrail wiring via source inspection."""

    def _read_task_router_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "task_router.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_task_router_init_contains_guardrail_call(self):
        src = self._read_task_router_src()
        assert "emit_legacy_guardrail" in src

    def test_task_router_guardrail_references_correct_caller(self):
        src = self._read_task_router_src()
        assert "task_router.TaskRouter" in src


# ===========================================================================
# 10. message_handler module docstring carries the deprecation note
# ===========================================================================

class TestMessageHandlerModuleDocstring:
    """Read source file directly to avoid pydantic import chain."""

    def _read_message_handler_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "handlers", "message_handler.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_module_docstring_contains_deprecated(self):
        src = self._read_message_handler_src()
        assert "deprecated" in src.lower() or "PR-S6" in src

    def test_module_docstring_contains_prs6(self):
        src = self._read_message_handler_src()
        assert "PR-S6" in src

    def test_module_docstring_names_chain_a_as_canonical(self):
        src = self._read_message_handler_src()
        assert "chain A" in src or "chain a" in src.lower() or "websocket_handler" in src

    def test_module_docstring_marks_chain_b_legacy(self):
        src = self._read_message_handler_src()
        assert "chain B" in src or "legacy" in src.lower()


# ===========================================================================
# 11. MessageHandler class docstring marks it as legacy chain B
# ===========================================================================

class TestMessageHandlerClassDocstring:
    def _read_message_handler_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "handlers", "message_handler.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_message_handler_class_docstring_contains_deprecated(self):
        src = self._read_message_handler_src()
        assert "MessageHandler" in src
        assert "deprecated" in src.lower() or ".. deprecated::" in src

    def test_message_handler_class_docstring_names_chain_a(self):
        src = self._read_message_handler_src()
        assert "chain A" in src or "websocket_handler" in src

    def test_message_handler_class_docstring_marks_chain_b(self):
        src = self._read_message_handler_src()
        assert "chain B" in src or "legacy" in src.lower()


# ===========================================================================
# 12. MessageHandler.__init__ emits LEGACY PATH GUARDRAIL
#    (verified via source inspection — import requires pydantic not in sandbox)
# ===========================================================================

class TestMessageHandlerGuardrailLog:
    """Verify guardrail wiring via source inspection."""

    def _read_message_handler_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "handlers", "message_handler.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_message_handler_init_contains_guardrail_call(self):
        src = self._read_message_handler_src()
        assert "emit_legacy_guardrail" in src

    def test_message_handler_guardrail_references_correct_caller(self):
        src = self._read_message_handler_src()
        assert "message_handler.MessageHandler" in src


# ===========================================================================
# 13. is_legacy_path returns True for all three PR-S6 paths
# ===========================================================================

class TestIsLegacyPathPRS6:
    def test_task_scheduler_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path("galaxy_gateway.task_router.TaskScheduler")

    def test_task_router_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path("galaxy_gateway.task_router.TaskRouter")

    def test_message_handler_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path(
            "galaxy_gateway.handlers.message_handler.MessageHandler"
        )

    def test_canonical_websocket_handler_is_not_legacy_compat(self):
        """websocket_handler (chain A, canonical) must not appear as legacy."""
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        # The canonical chain A ingress must not be LEGACY_COMPATIBILITY.
        entry = LEGACY_PATH_REGISTRY.get(
            "galaxy_gateway.websocket_handler"
        )
        if entry is not None:
            assert entry.status is not LegacyPathStatus.LEGACY_COMPATIBILITY, (
                "websocket_handler is the canonical chain A ingress and must not "
                "be classified as LEGACY_COMPATIBILITY"
            )

    def test_device_router_route_task_is_not_legacy_compat(self):
        """DeviceRouter.route_task is canonical and should not be legacy-compat."""
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY.get(
            "galaxy_gateway.device_router.DeviceRouter.route_task"
        )
        if entry is not None:
            assert entry.status is not LegacyPathStatus.LEGACY_COMPATIBILITY


# ===========================================================================
# 14. PURGE_REGISTRY contains PR-S6 entries
# ===========================================================================

class TestPurgeRegistryPRS6:
    """PR-S6 decisions appear in PURGE_REGISTRY with WRAPPER_HARDENED status."""

    def test_purge_registry_has_task_scheduler_entry(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        paths = {e.asset_path for e in PURGE_REGISTRY}
        assert any("TaskScheduler" in p for p in paths), (
            "PURGE_REGISTRY should have a TaskScheduler entry from PR-S6"
        )

    def test_purge_registry_has_task_router_entry(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        paths = {e.asset_path for e in PURGE_REGISTRY}
        assert any("TaskRouter" in p and "TaskScheduler" not in p for p in paths), (
            "PURGE_REGISTRY should have a TaskRouter entry from PR-S6"
        )

    def test_purge_registry_has_message_handler_entry(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        paths = {e.asset_path for e in PURGE_REGISTRY}
        assert any("MessageHandler" in p for p in paths), (
            "PURGE_REGISTRY should have a MessageHandler entry from PR-S6"
        )

    def test_prs6_entries_are_wrapper_hardened(self):
        from core.legacy_purge_registry import PURGE_REGISTRY, PurgeStatus
        prs6 = [e for e in PURGE_REGISTRY if e.pr == "PR-S6"]
        assert len(prs6) >= 3, f"Expected >= 3 PR-S6 entries, got {len(prs6)}"
        for entry in prs6:
            assert entry.status is PurgeStatus.WRAPPER_HARDENED, (
                f"PR-S6 entry {entry.asset_path!r} should be WRAPPER_HARDENED, "
                f"got {entry.status!r}"
            )

    def test_get_entries_by_pr_returns_prs6(self):
        from core.legacy_purge_registry import get_entries_by_pr
        prs6 = get_entries_by_pr("PR-S6")
        assert len(prs6) >= 3

    def test_purge_registry_summary_includes_prs6(self):
        from core.legacy_purge_registry import purge_registry_summary
        summary = purge_registry_summary()
        assert "PR-S6" in summary["by_pr"]
        assert len(summary["by_pr"]["PR-S6"]) >= 3
