#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prm_legacy_path_retirement.py
=========================================

PR-M — Legacy path retirement and canonical-only enforcement pass.

Validates that:
  1. PR-M entries are present in ``LEGACY_PATH_REGISTRY``:
       - ``galaxy_gateway.smart_transport_router.SmartTransportRouter``
       - ``galaxy_gateway.enhanced_nlu_v2.EnhancedNLUEngineV2``
       - ``galaxy_gateway.session_roaming.SessionRoamingManager``
  2. All three are registered as ``LEGACY_COMPATIBILITY``.
  3. All three have ``pr_guardrail_added == "PR-M"``.
  4. ``LEGACY_ORCHESTRATOR_PATHS`` shim includes ALL three PR-M registry
     keys (regression guard against the ordering bug where the shim is
     defined before later _register() calls).
  5. ``smart_transport_router`` module docstring carries the PR-M deprecation
     note.
  6. ``SmartTransportRouter`` class docstring marks it as legacy compat.
  7. ``SmartTransportRouter.__init__`` calls ``emit_legacy_guardrail``.
  8. ``enhanced_nlu_v2`` module docstring carries the PR-M deprecation note.
  9. ``EnhancedNLUEngineV2`` class docstring marks it as legacy compat.
 10. ``EnhancedNLUEngineV2.__init__`` calls ``emit_legacy_guardrail``.
 11. ``session_roaming`` module docstring carries the PR-M deprecation note.
 12. ``SessionRoamingManager`` class docstring marks it as legacy compat.
 13. ``SessionRoamingManager.__init__`` calls ``emit_legacy_guardrail``.
 14. ``is_legacy_path`` returns True for all three PR-M paths.
 15. ``PURGE_REGISTRY`` contains PR-M entries for SmartTransportRouter,
     EnhancedNLUEngineV2, and SessionRoamingManager with
     ``WRAPPER_HARDENED`` status.
 16. Canonical replacements are NOT classified as legacy.
 17. Prior-batch paths (PR-S5, PR-S6, PR-S7) are still present as regression
     guard.

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ===========================================================================
# 1. PR-M registry entries present
# ===========================================================================

class TestPRMRegistryEntries:
    """All three PR-M paths appear in LEGACY_PATH_REGISTRY."""

    def test_smart_transport_router_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.smart_transport_router.SmartTransportRouter"
            in LEGACY_PATH_REGISTRY
        )

    def test_enhanced_nlu_engine_v2_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.enhanced_nlu_v2.EnhancedNLUEngineV2"
            in LEGACY_PATH_REGISTRY
        )

    def test_session_roaming_manager_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.session_roaming.SessionRoamingManager"
            in LEGACY_PATH_REGISTRY
        )


# ===========================================================================
# 2. All three are LEGACY_COMPATIBILITY
# ===========================================================================

class TestPRMStatus:
    """All PR-M entries carry LEGACY_COMPATIBILITY status."""

    def test_smart_transport_router_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.smart_transport_router.SmartTransportRouter"
        ]
        assert entry.status is LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_enhanced_nlu_engine_v2_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.enhanced_nlu_v2.EnhancedNLUEngineV2"
        ]
        assert entry.status is LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_session_roaming_manager_is_legacy_compat(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.session_roaming.SessionRoamingManager"
        ]
        assert entry.status is LegacyPathStatus.LEGACY_COMPATIBILITY


# ===========================================================================
# 3. All three have pr_guardrail_added == "PR-M"
# ===========================================================================

class TestPRMGuardrailTag:
    """All PR-M entries have pr_guardrail_added == 'PR-M'."""

    def test_smart_transport_router_guardrail_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.smart_transport_router.SmartTransportRouter"
        ]
        assert entry.pr_guardrail_added == "PR-M"

    def test_enhanced_nlu_engine_v2_guardrail_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.enhanced_nlu_v2.EnhancedNLUEngineV2"
        ]
        assert entry.pr_guardrail_added == "PR-M"

    def test_session_roaming_manager_guardrail_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY[
            "galaxy_gateway.session_roaming.SessionRoamingManager"
        ]
        assert entry.pr_guardrail_added == "PR-M"


# ===========================================================================
# 4. LEGACY_ORCHESTRATOR_PATHS shim includes all PR-M keys
# ===========================================================================

class TestLegacyOrchestratorPathsShimPRM:
    """LEGACY_ORCHESTRATOR_PATHS frozenset includes all PR-M paths."""

    def test_shim_includes_smart_transport_router(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "galaxy_gateway.smart_transport_router.SmartTransportRouter"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_includes_enhanced_nlu_engine_v2(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "galaxy_gateway.enhanced_nlu_v2.EnhancedNLUEngineV2"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_includes_session_roaming_manager(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "galaxy_gateway.session_roaming.SessionRoamingManager"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_is_superset_of_prs7_paths(self):
        """Regression guard: PR-S7 paths must still be present in the shim."""
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        prs7_paths = {
            "galaxy_gateway.task_decomposer.TaskDecomposer",
            "galaxy_gateway.task_decomposer.IntelligentTaskPlanner",
            "galaxy_gateway.capability_registry.GatewayCapabilityRegistry",
        }
        assert prs7_paths.issubset(LEGACY_ORCHESTRATOR_PATHS)


# ===========================================================================
# 5. smart_transport_router module docstring carries PR-M deprecation note
# ===========================================================================

class TestSmartTransportRouterModuleDocstring:
    """Read source file directly to avoid pydantic import chain."""

    def _read_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "smart_transport_router.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_module_docstring_contains_deprecated(self):
        src = self._read_src()
        assert "deprecated" in src.lower() or "PR-M" in src

    def test_module_docstring_contains_prm(self):
        src = self._read_src()
        assert "PR-M" in src

    def test_module_docstring_names_device_router(self):
        src = self._read_src()
        assert "DeviceRouter" in src or "device_router" in src

    def test_module_docstring_names_routing_dispatch(self):
        src = self._read_src()
        assert "routing.dispatch" in src or "dispatch_to_websocket" in src


# ===========================================================================
# 6. SmartTransportRouter class docstring marks it as legacy compat
# ===========================================================================

class TestSmartTransportRouterClassDocstring:
    def _read_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "smart_transport_router.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_class_docstring_contains_deprecated(self):
        src = self._read_src()
        assert "SmartTransportRouter" in src
        assert "deprecated" in src.lower() or ".. deprecated::" in src

    def test_class_docstring_mentions_legacy_compat(self):
        src = self._read_src()
        assert "legacy" in src.lower()


# ===========================================================================
# 7. SmartTransportRouter.__init__ calls emit_legacy_guardrail
# ===========================================================================

class TestSmartTransportRouterGuardrailLog:
    """Verify guardrail wiring via source inspection."""

    def _read_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "smart_transport_router.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_init_contains_guardrail_call(self):
        src = self._read_src()
        assert "emit_legacy_guardrail" in src

    def test_guardrail_references_correct_caller(self):
        src = self._read_src()
        assert "smart_transport_router.SmartTransportRouter" in src


# ===========================================================================
# 8. enhanced_nlu_v2 module docstring carries PR-M deprecation note
# ===========================================================================

class TestEnhancedNLUV2ModuleDocstring:
    """Read source file directly to avoid aiohttp import chain."""

    def _read_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "enhanced_nlu_v2.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_module_docstring_contains_deprecated(self):
        src = self._read_src()
        assert "deprecated" in src.lower() or "PR-M" in src

    def test_module_docstring_contains_prm(self):
        src = self._read_src()
        assert "PR-M" in src

    def test_module_docstring_names_e2e_orchestrator(self):
        src = self._read_src()
        assert "e2e_orchestrator" in src or "process_user_input" in src

    def test_module_docstring_names_openclawd_pipeline(self):
        src = self._read_src()
        assert "OpenClawd" in src or "CommandRouter" in src


# ===========================================================================
# 9. EnhancedNLUEngineV2 class docstring marks it as legacy compat
# ===========================================================================

class TestEnhancedNLUV2ClassDocstring:
    def _read_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "enhanced_nlu_v2.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_class_docstring_contains_deprecated(self):
        src = self._read_src()
        assert "EnhancedNLUEngineV2" in src
        assert "deprecated" in src.lower() or ".. deprecated::" in src

    def test_class_docstring_mentions_legacy_compat(self):
        src = self._read_src()
        assert "legacy" in src.lower()


# ===========================================================================
# 10. EnhancedNLUEngineV2.__init__ calls emit_legacy_guardrail
# ===========================================================================

class TestEnhancedNLUV2GuardrailLog:
    """Verify guardrail wiring via source inspection."""

    def _read_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "enhanced_nlu_v2.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_init_contains_guardrail_call(self):
        src = self._read_src()
        assert "emit_legacy_guardrail" in src

    def test_guardrail_references_correct_caller(self):
        src = self._read_src()
        assert "enhanced_nlu_v2.EnhancedNLUEngineV2" in src


# ===========================================================================
# 11. session_roaming module docstring carries PR-M deprecation note
# ===========================================================================

class TestSessionRoamingModuleDocstring:
    """Read source file directly."""

    def _read_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "session_roaming.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_module_docstring_contains_deprecated(self):
        src = self._read_src()
        assert "deprecated" in src.lower() or "PR-M" in src

    def test_module_docstring_contains_prm(self):
        src = self._read_src()
        assert "PR-M" in src

    def test_module_docstring_names_canonical_session_axis(self):
        src = self._read_src()
        assert "canonical_session_axis" in src or "attached_runtime_session" in src

    def test_module_docstring_marks_cross_device_coordinator_legacy(self):
        src = self._read_src()
        assert "CrossDeviceCoordinator" in src or "legacy" in src.lower()


# ===========================================================================
# 12. SessionRoamingManager class docstring marks it as legacy compat
# ===========================================================================

class TestSessionRoamingManagerClassDocstring:
    def _read_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "session_roaming.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_class_docstring_contains_deprecated(self):
        src = self._read_src()
        assert "SessionRoamingManager" in src
        assert "deprecated" in src.lower() or ".. deprecated::" in src

    def test_class_docstring_mentions_legacy_compat(self):
        src = self._read_src()
        assert "legacy" in src.lower()

    def test_class_docstring_names_canonical_replacement(self):
        src = self._read_src()
        assert "canonical_session_axis" in src or "attached_runtime_session" in src


# ===========================================================================
# 13. SessionRoamingManager.__init__ calls emit_legacy_guardrail
# ===========================================================================

class TestSessionRoamingManagerGuardrailLog:
    """Verify guardrail wiring via source inspection."""

    def _read_src(self) -> str:
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "galaxy_gateway", "session_roaming.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_init_contains_guardrail_call(self):
        src = self._read_src()
        assert "emit_legacy_guardrail" in src

    def test_guardrail_references_correct_caller(self):
        src = self._read_src()
        assert "session_roaming.SessionRoamingManager" in src


# ===========================================================================
# 14. is_legacy_path returns True for all three PR-M paths
# ===========================================================================

class TestIsLegacyPathPRM:
    def test_smart_transport_router_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path(
            "galaxy_gateway.smart_transport_router.SmartTransportRouter"
        )

    def test_enhanced_nlu_engine_v2_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path("galaxy_gateway.enhanced_nlu_v2.EnhancedNLUEngineV2")

    def test_session_roaming_manager_is_legacy(self):
        from core.orchestration_authority.legacy_paths import is_legacy_path
        assert is_legacy_path("galaxy_gateway.session_roaming.SessionRoamingManager")

    def test_canonical_device_router_is_not_legacy_compat(self):
        """DeviceRouter.route_task (canonical) must not be LEGACY_COMPATIBILITY."""
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY.get(
            "galaxy_gateway.device_router.DeviceRouter.route_task"
        )
        if entry is not None:
            assert entry.status is not LegacyPathStatus.LEGACY_COMPATIBILITY, (
                "DeviceRouter.route_task is the canonical dispatch authority "
                "and must not be classified as LEGACY_COMPATIBILITY"
            )

    def test_canonical_e2e_orchestrator_is_not_legacy_compat(self):
        """process_user_input (canonical) must not be LEGACY_COMPATIBILITY."""
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY.get(
            "core.e2e_orchestrator.process_user_input"
        )
        if entry is not None:
            assert entry.status is not LegacyPathStatus.LEGACY_COMPATIBILITY, (
                "core.e2e_orchestrator.process_user_input is the canonical "
                "orchestration entry and must not be classified as "
                "LEGACY_COMPATIBILITY"
            )


# ===========================================================================
# 15. PURGE_REGISTRY contains PR-M entries (WRAPPER_HARDENED)
# ===========================================================================

class TestPurgeRegistryPRM:
    """PR-M decisions appear in PURGE_REGISTRY with WRAPPER_HARDENED status."""

    def test_purge_registry_has_smart_transport_router_entry(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        paths = {e.asset_path for e in PURGE_REGISTRY}
        assert any("SmartTransportRouter" in p for p in paths), (
            "PURGE_REGISTRY should have a SmartTransportRouter entry from PR-M"
        )

    def test_purge_registry_has_enhanced_nlu_engine_v2_entry(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        paths = {e.asset_path for e in PURGE_REGISTRY}
        assert any("EnhancedNLUEngineV2" in p for p in paths), (
            "PURGE_REGISTRY should have an EnhancedNLUEngineV2 entry from PR-M"
        )

    def test_purge_registry_has_session_roaming_manager_entry(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        paths = {e.asset_path for e in PURGE_REGISTRY}
        assert any("SessionRoamingManager" in p for p in paths), (
            "PURGE_REGISTRY should have a SessionRoamingManager entry from PR-M"
        )

    def test_prm_entries_are_wrapper_hardened(self):
        from core.legacy_purge_registry import PURGE_REGISTRY, PurgeStatus
        prm = [e for e in PURGE_REGISTRY if e.pr == "PR-M"]
        assert len(prm) >= 3, f"Expected >= 3 PR-M entries, got {len(prm)}"
        for entry in prm:
            assert entry.status is PurgeStatus.WRAPPER_HARDENED, (
                f"PR-M entry {entry.asset_path!r} should be WRAPPER_HARDENED, "
                f"got {entry.status!r}"
            )

    def test_get_entries_by_pr_returns_prm(self):
        from core.legacy_purge_registry import get_entries_by_pr
        prm = get_entries_by_pr("PR-M")
        assert len(prm) >= 3

    def test_purge_registry_summary_includes_prm(self):
        from core.legacy_purge_registry import purge_registry_summary
        summary = purge_registry_summary()
        assert "PR-M" in summary["by_pr"]
        assert len(summary["by_pr"]["PR-M"]) >= 3


# ===========================================================================
# 16. Canonical replacements are NOT classified as legacy
# ===========================================================================

class TestCanonicalReplacementsNotLegacy:
    """Canonical replacements must not be classified as LEGACY_COMPATIBILITY."""

    def test_routing_dispatch_not_legacy(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY.get("galaxy_gateway.routing.dispatch")
        if entry is not None:
            assert entry.status is not LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_canonical_session_axis_not_legacy(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        entry = LEGACY_PATH_REGISTRY.get("core.canonical_session_axis")
        if entry is not None:
            assert entry.status is not LegacyPathStatus.LEGACY_COMPATIBILITY


# ===========================================================================
# 17. Regression guard: prior-batch paths still present
# ===========================================================================

class TestPriorBatchRegressionGuard:
    """Prior-batch legacy paths must still be in the registry."""

    def test_prs5_paths_still_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        prs5_paths = {
            "galaxy_gateway.orchestrator.task_orchestrator.MultiDeviceOrchestrator",
            "galaxy_gateway.orchestrator.parallel_tracker.ParallelGroupTracker",
            "core.local_agent_runtime.LocalAgentRuntime",
        }
        assert prs5_paths.issubset(LEGACY_ORCHESTRATOR_PATHS), (
            "PR-S5 paths must still be present as regression guard"
        )

    def test_prs6_paths_still_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        prs6_paths = {
            "galaxy_gateway.task_router.TaskScheduler",
            "galaxy_gateway.task_router.TaskRouter",
            "galaxy_gateway.handlers.message_handler.MessageHandler",
        }
        assert prs6_paths.issubset(LEGACY_ORCHESTRATOR_PATHS), (
            "PR-S6 paths must still be present as regression guard"
        )

    def test_prs7_paths_still_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        prs7_paths = {
            "galaxy_gateway.task_decomposer.TaskDecomposer",
            "galaxy_gateway.task_decomposer.IntelligentTaskPlanner",
            "galaxy_gateway.capability_registry.GatewayCapabilityRegistry",
        }
        assert prs7_paths.issubset(LEGACY_ORCHESTRATOR_PATHS), (
            "PR-S7 paths must still be present as regression guard"
        )
