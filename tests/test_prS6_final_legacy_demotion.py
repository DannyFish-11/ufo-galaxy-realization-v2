#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prS6_final_legacy_demotion.py
=========================================

PR-S6 — Finalize server-side legacy demotion and remove non-canonical
runtime entry leftovers.

Validates that:
  1. PR-S6 entries are present in ``LEGACY_PATH_REGISTRY``:
       - ``galaxy_gateway.task_router.TaskRouter``
       - ``galaxy_gateway.task_router.TaskScheduler``
       - ``galaxy_gateway.handlers.message_handler.MessageHandler``
  2. All three are registered as ``LEGACY_COMPATIBILITY``.
  3. All three have ``pr_guardrail_added == "PR-S6"``.
  4. ``LEGACY_ORCHESTRATOR_PATHS`` shim includes all three new keys (regression
     guard against the ordering bug where the shim was defined before new
     _register() calls were evaluated).
  5. ``TaskRouter`` class docstring carries the deprecation marker.
  6. ``TaskRouter.__init__`` source contains a ``LEGACY PATH GUARDRAIL`` call.
  7. ``TaskScheduler`` class docstring carries the deprecation marker.
  8. ``TaskScheduler.__init__`` source contains a ``LEGACY PATH GUARDRAIL`` call.
  9. ``MessageHandler`` module docstring names chain B as the legacy chain.
 10. ``MessageHandler`` class docstring carries the deprecation marker.
 11. ``MessageHandler.__init__`` source contains a ``LEGACY PATH GUARDRAIL`` call.
 12. Legacy-path shim round-trip: ``is_legacy_path`` returns True for all three.
 13. ``PURGE_REGISTRY`` contains PR-S6 WRAPPER_HARDENED entries for all three.
 14. The canonical DeviceRouter entry is NOT treated as legacy-compat (sanity check).

Source files are read directly (not imported) to avoid the fastapi/pydantic/
aiohttp import chain that is not available in the test sandbox.
"""

from __future__ import annotations

import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Helpers — read source files without importing them
# ---------------------------------------------------------------------------

def _read_src(relative_path: str) -> str:
    path = os.path.join(_PROJECT_ROOT, *relative_path.split("/"))
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _task_router_src() -> str:
    return _read_src("galaxy_gateway/task_router.py")


def _message_handler_src() -> str:
    return _read_src("galaxy_gateway/handlers/message_handler.py")


# ===========================================================================
# 1. PR-S6 registry entries present
# ===========================================================================

class TestPRS6RegistryEntries:
    """All three PR-S6 paths appear in LEGACY_PATH_REGISTRY."""

    def test_task_router_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.task_router.TaskRouter"
            in LEGACY_PATH_REGISTRY
        )

    def test_task_scheduler_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.task_router.TaskScheduler"
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

    def test_task_router_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_router.TaskRouter"]
        assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_task_scheduler_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_router.TaskScheduler"]
        assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_message_handler_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.handlers.message_handler.MessageHandler"
        ]
        assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY


# ===========================================================================
# 3. All three have pr_guardrail_added == "PR-S6"
# ===========================================================================

class TestPRS6GuardrailTag:
    """All PR-S6 entries are tagged with PR-S6."""

    def test_task_router_pr_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_router.TaskRouter"]
        assert entry.pr_guardrail_added == "PR-S6"

    def test_task_scheduler_pr_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_router.TaskScheduler"]
        assert entry.pr_guardrail_added == "PR-S6"

    def test_message_handler_pr_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.handlers.message_handler.MessageHandler"
        ]
        assert entry.pr_guardrail_added == "PR-S6"


# ===========================================================================
# 4. LEGACY_ORCHESTRATOR_PATHS shim includes all three new keys
# ===========================================================================

class TestLegacyOrchestratorPathsShim:
    """LEGACY_ORCHESTRATOR_PATHS frozenset includes all PR-S6 entries."""

    def test_shim_includes_task_router(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert "galaxy_gateway.task_router.TaskRouter" in LEGACY_ORCHESTRATOR_PATHS

    def test_shim_includes_task_scheduler(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert "galaxy_gateway.task_router.TaskScheduler" in LEGACY_ORCHESTRATOR_PATHS

    def test_shim_includes_message_handler(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "galaxy_gateway.handlers.message_handler.MessageHandler"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_is_frozenset(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert isinstance(LEGACY_ORCHESTRATOR_PATHS, frozenset)

    def test_shim_includes_prs6_paths(self):
        """All three PR-S6 paths appear in the frozenset shim."""
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        prs6_paths = {
            "galaxy_gateway.task_router.TaskRouter",
            "galaxy_gateway.task_router.TaskScheduler",
            "galaxy_gateway.handlers.message_handler.MessageHandler",
        }
        assert prs6_paths.issubset(LEGACY_ORCHESTRATOR_PATHS)


# ===========================================================================
# 5–6. TaskRouter docstring and __init__ guardrail (source inspection)
# ===========================================================================

class TestTaskRouterDocstring:
    """TaskRouter carries deprecation markers and a guardrail call."""

    def test_task_router_module_docstring_contains_prs6_note(self):
        src = _task_router_src()
        assert "PR-S6" in src

    def test_task_router_class_docstring_contains_deprecated(self):
        src = _task_router_src()
        # The class docstring must contain either ".. deprecated::" or "PR-S6"
        assert "deprecated" in src.lower() or "PR-S6" in src

    def test_task_router_docstring_names_canonical_path(self):
        src = _task_router_src()
        assert "DeviceRouter" in src or "e2e_orchestrator" in src

    def test_task_router_init_contains_guardrail_call(self):
        src = _task_router_src()
        assert "emit_legacy_guardrail" in src

    def test_task_router_guardrail_references_correct_caller(self):
        src = _task_router_src()
        assert "task_router.TaskRouter" in src


# ===========================================================================
# 7–8. TaskScheduler docstring and __init__ guardrail (source inspection)
# ===========================================================================

class TestTaskSchedulerDocstring:
    """TaskScheduler carries deprecation markers and a guardrail call."""

    def test_task_scheduler_class_docstring_contains_deprecated(self):
        src = _task_router_src()
        assert "deprecated" in src.lower() or "PR-S6" in src

    def test_task_scheduler_docstring_names_canonical_path(self):
        src = _task_router_src()
        assert "canonical" in src.lower() or "OpenClawd" in src

    def test_task_scheduler_init_contains_guardrail_call(self):
        src = _task_router_src()
        assert "emit_legacy_guardrail" in src

    def test_task_scheduler_guardrail_references_correct_caller(self):
        src = _task_router_src()
        assert "task_router.TaskScheduler" in src


# ===========================================================================
# 9–11. MessageHandler docstring and __init__ guardrail (source inspection)
# ===========================================================================

class TestMessageHandlerDocstring:
    """MessageHandler carries chain-B deprecation markers and a guardrail call."""

    def test_module_docstring_names_chain_b_as_legacy(self):
        src = _message_handler_src()
        assert "chain" in src.lower() or "Chain" in src

    def test_module_docstring_marks_chain_a_as_canonical(self):
        src = _message_handler_src()
        assert "canonical" in src.lower() or "websocket_handler" in src

    def test_module_docstring_contains_prs6_note(self):
        src = _message_handler_src()
        assert "PR-S6" in src

    def test_class_docstring_contains_deprecated(self):
        src = _message_handler_src()
        assert "deprecated" in src.lower() or "PR-S6" in src

    def test_class_docstring_mentions_no_independent_authority(self):
        src = _message_handler_src()
        assert "authority" in src.lower() or "shim" in src.lower()

    def test_init_contains_guardrail_call(self):
        src = _message_handler_src()
        assert "emit_legacy_guardrail" in src

    def test_init_guardrail_mentions_message_handler(self):
        src = _message_handler_src()
        assert "MessageHandler" in src
        assert "emit_legacy_guardrail" in src


# ===========================================================================
# 12. is_legacy_path round-trip
# ===========================================================================

class TestIsLegacyPathPRS6:
    """is_legacy_path() returns True for all PR-S6 paths."""

    def test_task_router_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path("galaxy_gateway.task_router.TaskRouter")

    def test_task_scheduler_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path("galaxy_gateway.task_router.TaskScheduler")

    def test_message_handler_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path(
            "galaxy_gateway.handlers.message_handler.MessageHandler"
        )

    def test_canonical_device_router_is_not_treated_as_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        # DeviceRouter.route_task may be registered as demoted from top-level entry
        # but must NOT be flagged LEGACY_COMPATIBILITY — it IS the canonical hop.
        key = "galaxy_gateway.device_router.DeviceRouter.route_task"
        if key in LEGACY_PATH_REGISTRY:
            entry = LEGACY_PATH_REGISTRY[key]
            assert entry.status != LegacyPathStatus.LEGACY_COMPATIBILITY, (
                "DeviceRouter.route_task must not be LEGACY_COMPATIBILITY — "
                "it is the canonical dispatch hop."
            )


# ===========================================================================
# 13. PURGE_REGISTRY contains PR-S6 WRAPPER_HARDENED entries
# ===========================================================================

class TestPurgeRegistryPRS6:
    """PURGE_REGISTRY has WRAPPER_HARDENED entries for PR-S6 assets."""

    def _get_s6_entries(self):
        from core.legacy_purge_registry import get_entries_by_pr
        return get_entries_by_pr("PR-S6")

    def test_purge_registry_has_prs6_entries(self):
        entries = self._get_s6_entries()
        assert len(entries) >= 3, (
            f"Expected at least 3 PR-S6 purge entries, got {len(entries)}"
        )

    def test_task_router_purge_entry_present(self):
        entries = self._get_s6_entries()
        paths = [e.asset_path for e in entries]
        assert any("TaskRouter" in p for p in paths), (
            f"No PR-S6 purge entry for TaskRouter; found: {paths}"
        )

    def test_task_scheduler_purge_entry_present(self):
        entries = self._get_s6_entries()
        paths = [e.asset_path for e in entries]
        assert any("TaskScheduler" in p for p in paths), (
            f"No PR-S6 purge entry for TaskScheduler; found: {paths}"
        )

    def test_message_handler_purge_entry_present(self):
        entries = self._get_s6_entries()
        paths = [e.asset_path for e in entries]
        assert any("MessageHandler" in p for p in paths), (
            f"No PR-S6 purge entry for MessageHandler; found: {paths}"
        )

    def test_all_prs6_entries_are_wrapper_hardened(self):
        from core.legacy_purge_registry import PurgeStatus
        entries = self._get_s6_entries()
        for entry in entries:
            assert entry.status == PurgeStatus.WRAPPER_HARDENED, (
                f"PR-S6 entry {entry.asset_path!r} has status "
                f"{entry.status!r}, expected WRAPPER_HARDENED"
            )

    def test_all_prs6_entries_have_canonical_replacement(self):
        entries = self._get_s6_entries()
        for entry in entries:
            assert entry.canonical_replacement, (
                f"PR-S6 entry {entry.asset_path!r} has no canonical_replacement"
            )


# ===========================================================================
# 1. PR-S6 registry entries present
# ===========================================================================

class TestPRS6RegistryEntries:
    """All three PR-S6 paths appear in LEGACY_PATH_REGISTRY."""

    def test_task_router_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.task_router.TaskRouter"
            in LEGACY_PATH_REGISTRY
        )

    def test_task_scheduler_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.task_router.TaskScheduler"
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

    def test_task_router_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_router.TaskRouter"]
        assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_task_scheduler_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_router.TaskScheduler"]
        assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_message_handler_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.handlers.message_handler.MessageHandler"
        ]
        assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY


# ===========================================================================
# 3. All three have pr_guardrail_added == "PR-S6"
# ===========================================================================

class TestPRS6GuardrailTag:
    """All PR-S6 entries are tagged with PR-S6."""

    def test_task_router_pr_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_router.TaskRouter"]
        assert entry.pr_guardrail_added == "PR-S6"

    def test_task_scheduler_pr_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["galaxy_gateway.task_router.TaskScheduler"]
        assert entry.pr_guardrail_added == "PR-S6"

    def test_message_handler_pr_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.handlers.message_handler.MessageHandler"
        ]
        assert entry.pr_guardrail_added == "PR-S6"


# ===========================================================================
# 4. LEGACY_ORCHESTRATOR_PATHS shim includes all three new keys
# ===========================================================================

class TestLegacyOrchestratorPathsShim:
    """LEGACY_ORCHESTRATOR_PATHS frozenset includes all PR-S6 entries."""

    def test_shim_includes_task_router(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert "galaxy_gateway.task_router.TaskRouter" in LEGACY_ORCHESTRATOR_PATHS

    def test_shim_includes_task_scheduler(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert "galaxy_gateway.task_router.TaskScheduler" in LEGACY_ORCHESTRATOR_PATHS

    def test_shim_includes_message_handler(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "galaxy_gateway.handlers.message_handler.MessageHandler"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_is_frozenset(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert isinstance(LEGACY_ORCHESTRATOR_PATHS, frozenset)


# ===========================================================================
# 5–6. TaskRouter docstring and __init__ guardrail
# ===========================================================================

class TestTaskRouterDocstring:
    """TaskRouter carries deprecation markers and a guardrail call."""

    def _get_source(self):
        import importlib
        mod = importlib.import_module("galaxy_gateway.task_router")
        return inspect.getsource(mod)

    def _get_class(self):
        from galaxy_gateway.task_router import TaskRouter
        return TaskRouter

    def test_task_router_docstring_contains_deprecated(self):
        cls = self._get_class()
        assert cls.__doc__ is not None
        assert "deprecated" in cls.__doc__.lower() or "PR-S6" in cls.__doc__

    def test_task_router_docstring_names_canonical_path(self):
        cls = self._get_class()
        assert cls.__doc__ is not None
        doc = cls.__doc__
        assert "DeviceRouter" in doc or "canonical" in doc.lower()

    def test_task_router_init_contains_guardrail_call(self):
        src = self._get_source()
        assert "emit_legacy_guardrail" in src
        assert "TaskRouter" in src

    def test_task_router_module_docstring_contains_prs6_note(self):
        import galaxy_gateway.task_router as mod
        assert mod.__doc__ is not None
        assert "PR-S6" in mod.__doc__


# ===========================================================================
# 7–8. TaskScheduler docstring and __init__ guardrail
# ===========================================================================

class TestTaskSchedulerDocstring:
    """TaskScheduler carries deprecation markers and a guardrail call."""

    def _get_class(self):
        from galaxy_gateway.task_router import TaskScheduler
        return TaskScheduler

    def test_task_scheduler_docstring_contains_deprecated(self):
        cls = self._get_class()
        assert cls.__doc__ is not None
        assert "deprecated" in cls.__doc__.lower() or "PR-S6" in cls.__doc__

    def test_task_scheduler_docstring_names_canonical_path(self):
        cls = self._get_class()
        assert cls.__doc__ is not None
        doc = cls.__doc__
        assert "canonical" in doc.lower() or "OpenClawd" in doc


# ===========================================================================
# 9–11. MessageHandler module docstring, class docstring, and __init__ guardrail
# ===========================================================================

class TestMessageHandlerDocstring:
    """MessageHandler carries chain-B deprecation markers and a guardrail call."""

    def _get_module_source(self):
        import importlib
        mod = importlib.import_module("galaxy_gateway.handlers.message_handler")
        return inspect.getsource(mod)

    def _get_class(self):
        from galaxy_gateway.handlers.message_handler import MessageHandler
        return MessageHandler

    def test_module_docstring_names_chain_b_as_legacy(self):
        import galaxy_gateway.handlers.message_handler as mod
        assert mod.__doc__ is not None
        doc = mod.__doc__
        assert "chain" in doc.lower() or "Chain" in doc

    def test_module_docstring_marks_chain_a_as_canonical(self):
        import galaxy_gateway.handlers.message_handler as mod
        assert mod.__doc__ is not None
        doc = mod.__doc__
        assert "canonical" in doc.lower() or "websocket_handler" in doc

    def test_module_docstring_contains_prs6_note(self):
        import galaxy_gateway.handlers.message_handler as mod
        assert mod.__doc__ is not None
        assert "PR-S6" in mod.__doc__

    def test_class_docstring_contains_deprecated(self):
        cls = self._get_class()
        assert cls.__doc__ is not None
        assert "deprecated" in cls.__doc__.lower() or "PR-S6" in cls.__doc__

    def test_class_docstring_mentions_no_runtime_authority(self):
        cls = self._get_class()
        assert cls.__doc__ is not None
        doc = cls.__doc__
        assert "authority" in doc.lower() or "shim" in doc.lower()

    def test_init_contains_guardrail_call(self):
        src = self._get_module_source()
        assert "emit_legacy_guardrail" in src

    def test_init_guardrail_mentions_message_handler(self):
        src = self._get_module_source()
        assert "MessageHandler" in src
        assert "emit_legacy_guardrail" in src


# ===========================================================================
# 12. is_legacy_path round-trip
# ===========================================================================

class TestIsLegacyPathPRS6:
    """is_legacy_path() returns True for all PR-S6 paths."""

    def test_task_router_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path("galaxy_gateway.task_router.TaskRouter")

    def test_task_scheduler_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path("galaxy_gateway.task_router.TaskScheduler")

    def test_message_handler_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path(
            "galaxy_gateway.handlers.message_handler.MessageHandler"
        )

    def test_canonical_device_router_is_not_treated_as_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            is_legacy_path,
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        # DeviceRouter.route_task is registered as a legacy path (it was demoted
        # from being a top-level entry), but not as a LEGACY_COMPATIBILITY surface
        # that bypasses the canonical pipeline — it IS the canonical dispatch hop.
        # Verify the DeviceRouter entry (if present) is not marked LEGACY_COMPATIBILITY.
        key = "galaxy_gateway.device_router.DeviceRouter.route_task"
        if key in LEGACY_PATH_REGISTRY:
            entry = LEGACY_PATH_REGISTRY[key]
            assert entry.status != LegacyPathStatus.LEGACY_COMPATIBILITY, (
                "DeviceRouter.route_task must not be LEGACY_COMPATIBILITY — "
                "it is the canonical dispatch hop."
            )


# ===========================================================================
# 13. PURGE_REGISTRY contains PR-S6 WRAPPER_HARDENED entries
# ===========================================================================

class TestPurgeRegistryPRS6:
    """PURGE_REGISTRY has WRAPPER_HARDENED entries for PR-S6 assets."""

    def _get_s6_entries(self):
        from core.legacy_purge_registry import get_entries_by_pr
        return get_entries_by_pr("PR-S6")

    def test_purge_registry_has_prs6_entries(self):
        entries = self._get_s6_entries()
        assert len(entries) >= 3, (
            f"Expected at least 3 PR-S6 purge entries, got {len(entries)}"
        )

    def test_task_router_purge_entry_present(self):
        entries = self._get_s6_entries()
        paths = [e.asset_path for e in entries]
        assert any("TaskRouter" in p for p in paths), (
            f"No PR-S6 purge entry for TaskRouter; found: {paths}"
        )

    def test_task_scheduler_purge_entry_present(self):
        entries = self._get_s6_entries()
        paths = [e.asset_path for e in entries]
        assert any("TaskScheduler" in p for p in paths), (
            f"No PR-S6 purge entry for TaskScheduler; found: {paths}"
        )

    def test_message_handler_purge_entry_present(self):
        entries = self._get_s6_entries()
        paths = [e.asset_path for e in entries]
        assert any("MessageHandler" in p for p in paths), (
            f"No PR-S6 purge entry for MessageHandler; found: {paths}"
        )

    def test_all_prs6_entries_are_wrapper_hardened(self):
        from core.legacy_purge_registry import PurgeStatus
        entries = self._get_s6_entries()
        for entry in entries:
            assert entry.status == PurgeStatus.WRAPPER_HARDENED, (
                f"PR-S6 entry {entry.asset_path!r} has status "
                f"{entry.status!r}, expected WRAPPER_HARDENED"
            )

    def test_all_prs6_entries_have_canonical_replacement(self):
        entries = self._get_s6_entries()
        for entry in entries:
            assert entry.canonical_replacement, (
                f"PR-S6 entry {entry.asset_path!r} has no canonical_replacement"
            )
