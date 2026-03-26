#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prS7_canonical_runtime_declaration.py
==================================================

PR-S7 — Make final server cleanup mechanical after canonical runtime
consolidation.

Validates that:
  1. ``core.canonical_runtime_declaration`` module is importable and
     exposes the expected public API.
  2. ``get_canonical_runtime_declaration()`` returns a
     :class:`CanonicalRuntimeDeclaration` instance.
  3. The canonical pipeline contains all expected ordered steps.
  4. All canonical entry surfaces are present and correctly classified.
  5. All expected legacy/demoted surfaces are present and correctly classified.
  6. ``is_canonical()`` and ``is_legacy()`` helpers behave correctly.
  7. ``to_dict()`` / ``to_json()`` serialise without error.
  8. PR-S7 entries are present in ``LEGACY_PATH_REGISTRY``:
       - ``core.device_orchestrator.DeviceOrchestrator``
       - ``fusion.unified_orchestrator``
  9. Both new PR-S7 entries have ``pr_guardrail_added == "PR-S7"``.
 10. ``LEGACY_ORCHESTRATOR_PATHS`` shim includes the two new PR-S7 keys.
 11. ``PURGE_REGISTRY`` contains PR-S7 entries for
       ``core/device_orchestrator.py::DeviceOrchestrator``,
       ``fusion/unified_orchestrator.py``, and
       ``core/canonical_runtime_declaration.py``.
 12. ``DeviceOrchestrator`` docstring carries the PR-S7 canonical-helper note.
 13. ``fusion.unified_orchestrator`` deprecation warning message references
     ``core.e2e_orchestrator`` (not the demoted ``GalaxyOrchestrator``).
 14. Architecture completion scorecard reports ``generated_by_pr == "PR-S7"``.
 15. Scorecard dimension CANONICAL_PATH_COVERAGE is at COMPLETE maturity.
 16. Scorecard dimension LEGACY_SURFACE_DEMOTION has no legacy ambiguity.
 17. ``reset_canonical_runtime_declaration()`` clears the singleton.
 18. Derived properties: ``canonical_entries``, ``legacy_surfaces``,
     ``canonical_pipeline_surfaces`` return non-empty lists.
 19. All pipeline steps have non-empty ``authority_module`` and
     ``pr_established`` fields.
 20. ``surface_by_module()`` correctly locates a known module.

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import importlib
import logging
import sys
import os
import warnings

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ===========================================================================
# 1. Module importable and public API present
# ===========================================================================

class TestModuleImport:
    """canonical_runtime_declaration is importable with expected API."""

    def test_module_importable(self):
        import core.canonical_runtime_declaration  # noqa: F401

    def test_public_symbols_present(self):
        from core.canonical_runtime_declaration import (  # noqa: F401
            CanonicalPipelineStage,
            CanonicalSurfaceRole,
            PipelineStepDeclaration,
            CanonicalSurfaceDeclaration,
            CanonicalRuntimeDeclaration,
            build_canonical_runtime_declaration,
            get_canonical_runtime_declaration,
            reset_canonical_runtime_declaration,
        )

    def test_all_exports(self):
        from core.canonical_runtime_declaration import __all__
        expected = {
            "CanonicalPipelineStage",
            "CanonicalSurfaceRole",
            "PipelineStepDeclaration",
            "CanonicalSurfaceDeclaration",
            "CanonicalRuntimeDeclaration",
            "build_canonical_runtime_declaration",
            "get_canonical_runtime_declaration",
            "reset_canonical_runtime_declaration",
        }
        assert expected <= set(__all__)


# ===========================================================================
# 2. get_canonical_runtime_declaration() returns correct type
# ===========================================================================

class TestGetDeclaration:
    """get_canonical_runtime_declaration() returns the expected type."""

    def setup_method(self):
        from core.canonical_runtime_declaration import reset_canonical_runtime_declaration
        reset_canonical_runtime_declaration()

    def test_returns_declaration_instance(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalRuntimeDeclaration,
        )
        decl = get_canonical_runtime_declaration()
        assert isinstance(decl, CanonicalRuntimeDeclaration)

    def test_singleton_same_object(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        a = get_canonical_runtime_declaration()
        b = get_canonical_runtime_declaration()
        assert a is b

    def test_generated_by_pr(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert decl.generated_by_pr == "PR-S7"

    def test_declaration_version(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert decl.declaration_version == "1.0"


# ===========================================================================
# 3. Pipeline steps
# ===========================================================================

class TestPipelineSteps:
    """Canonical pipeline steps are present and correctly ordered."""

    def test_pipeline_has_steps(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert len(decl.pipeline_steps) >= 6

    def test_stage_1_presence_shell(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalPipelineStage,
        )
        decl = get_canonical_runtime_declaration()
        stages = [s.stage for s in decl.pipeline_steps]
        assert CanonicalPipelineStage.STAGE_1_PRESENCE_SHELL in stages

    def test_stage_2_subject_core(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalPipelineStage,
        )
        decl = get_canonical_runtime_declaration()
        stages = [s.stage for s in decl.pipeline_steps]
        assert CanonicalPipelineStage.STAGE_2_SUBJECT_CORE in stages

    def test_stage_4_command_router(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalPipelineStage,
        )
        decl = get_canonical_runtime_declaration()
        stages = [s.stage for s in decl.pipeline_steps]
        assert CanonicalPipelineStage.STAGE_4_COMMAND_ROUTER in stages

    def test_stage_6_device_router(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalPipelineStage,
        )
        decl = get_canonical_runtime_declaration()
        stages = [s.stage for s in decl.pipeline_steps]
        assert CanonicalPipelineStage.STAGE_6_DEVICE_ROUTER in stages

    def test_stage_7_result_envelope(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalPipelineStage,
        )
        decl = get_canonical_runtime_declaration()
        stages = [s.stage for s in decl.pipeline_steps]
        assert CanonicalPipelineStage.STAGE_7_RESULT_ENVELOPE in stages

    def test_all_steps_have_authority_module(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        for step in decl.pipeline_steps:
            assert step.authority_module, f"Step {step.stage} has empty authority_module"

    def test_all_steps_have_pr_established(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        for step in decl.pipeline_steps:
            assert step.pr_established, f"Step {step.stage} has empty pr_established"

    def test_all_steps_have_description(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        for step in decl.pipeline_steps:
            assert step.description, f"Step {step.stage} has empty description"


# ===========================================================================
# 4. Canonical entry surfaces
# ===========================================================================

class TestCanonicalEntrySurfaces:
    """Canonical entry surfaces are present and correctly classified."""

    def test_chat_route_is_canonical_entry(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalSurfaceRole,
        )
        decl = get_canonical_runtime_declaration()
        surface = decl.surface_by_module("core.routes.chat")
        assert surface is not None
        assert surface.role == CanonicalSurfaceRole.CANONICAL_ENTRY

    def test_gateway_app_is_canonical_entry(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalSurfaceRole,
        )
        decl = get_canonical_runtime_declaration()
        surface = decl.surface_by_module("galaxy_gateway.app")
        assert surface is not None
        assert surface.role == CanonicalSurfaceRole.CANONICAL_ENTRY

    def test_e2e_orchestrator_is_canonical_entry(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalSurfaceRole,
        )
        decl = get_canonical_runtime_declaration()
        surface = decl.surface_by_module("core.e2e_orchestrator")
        assert surface is not None
        assert surface.role == CanonicalSurfaceRole.CANONICAL_ENTRY

    def test_canonical_entries_non_empty(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert len(decl.canonical_entries) >= 3


# ===========================================================================
# 5. Legacy/demoted surfaces
# ===========================================================================

class TestLegacySurfaces:
    """Legacy and demoted surfaces are present and correctly classified."""

    def test_task_router_is_demoted(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalSurfaceRole,
        )
        decl = get_canonical_runtime_declaration()
        surface = decl.surface_by_module("galaxy_gateway.task_router")
        assert surface is not None
        assert surface.role in (
            CanonicalSurfaceRole.LEGACY_COMPAT,
            CanonicalSurfaceRole.DEMOTED_ENTRY,
        )

    def test_message_handler_is_demoted(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalSurfaceRole,
        )
        decl = get_canonical_runtime_declaration()
        surface = decl.surface_by_module("galaxy_gateway.handlers.message_handler")
        assert surface is not None
        assert surface.role in (
            CanonicalSurfaceRole.LEGACY_COMPAT,
            CanonicalSurfaceRole.DEMOTED_ENTRY,
        )

    def test_fusion_unified_orchestrator_is_demoted(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalSurfaceRole,
        )
        decl = get_canonical_runtime_declaration()
        surface = decl.surface_by_module("fusion.unified_orchestrator")
        assert surface is not None
        assert surface.role in (
            CanonicalSurfaceRole.LEGACY_COMPAT,
            CanonicalSurfaceRole.DEMOTED_ENTRY,
        )

    def test_fusion_canonical_replacement_points_to_e2e(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        surface = decl.surface_by_module("fusion.unified_orchestrator")
        assert surface is not None
        assert surface.canonical_replacement is not None
        assert "e2e_orchestrator" in surface.canonical_replacement

    def test_legacy_surfaces_non_empty(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert len(decl.legacy_surfaces) >= 4

    def test_all_legacy_surfaces_have_canonical_replacement(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalSurfaceRole,
        )
        decl = get_canonical_runtime_declaration()
        for surface in decl.legacy_surfaces:
            assert surface.canonical_replacement, (
                f"Legacy surface {surface.module_path} has no canonical_replacement"
            )


# ===========================================================================
# 6. is_canonical() and is_legacy() helpers
# ===========================================================================

class TestHelpers:
    """Utility methods behave correctly."""

    def test_is_canonical_for_pipeline_module(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert decl.is_canonical("core.openclawd")

    def test_is_canonical_for_entry_surface(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert decl.is_canonical("core.e2e_orchestrator")

    def test_is_canonical_for_helper(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert decl.is_canonical("core.device_orchestrator")

    def test_is_legacy_for_demoted_surface(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert decl.is_legacy("galaxy_gateway.task_router")

    def test_is_legacy_for_fusion(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert decl.is_legacy("fusion.unified_orchestrator")

    def test_is_canonical_returns_false_for_unknown(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert not decl.is_canonical("some.unknown.module")

    def test_is_legacy_returns_false_for_unknown(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert not decl.is_legacy("some.unknown.module")


# ===========================================================================
# 7. Serialisation
# ===========================================================================

class TestSerialisation:
    """to_dict() and to_json() serialise without error."""

    def test_to_dict_returns_dict(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        d = decl.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_has_expected_keys(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        d = decl.to_dict()
        assert "declaration_version" in d
        assert "generated_by_pr" in d
        assert "pipeline_steps" in d
        assert "entry_surfaces" in d
        assert "canonical_entry_count" in d
        assert "legacy_surface_count" in d

    def test_to_json_returns_string(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        j = decl.to_json()
        assert isinstance(j, str)

    def test_to_json_parseable(self):
        import json
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        parsed = json.loads(decl.to_json())
        assert parsed["generated_by_pr"] == "PR-S7"

    def test_pipeline_step_to_dict(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        d = decl.pipeline_steps[0].to_dict()
        assert "stage" in d
        assert "authority_module" in d
        assert "description" in d

    def test_surface_to_dict(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        d = decl.entry_surfaces[0].to_dict()
        assert "module_path" in d
        assert "role" in d
        assert "description" in d


# ===========================================================================
# 8. PR-S7 entries in LEGACY_PATH_REGISTRY
# ===========================================================================

class TestPRS7LegacyPathEntries:
    """Both PR-S7 paths appear in LEGACY_PATH_REGISTRY."""

    def test_device_orchestrator_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert "core.device_orchestrator.DeviceOrchestrator" in LEGACY_PATH_REGISTRY

    def test_fusion_unified_orchestrator_registered(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert "fusion.unified_orchestrator" in LEGACY_PATH_REGISTRY


# ===========================================================================
# 9. Both PR-S7 entries have pr_guardrail_added == "PR-S7"
# ===========================================================================

class TestPRS7GuardrailTag:
    """Both PR-S7 entries carry the PR-S7 guardrail tag."""

    def test_device_orchestrator_guardrail_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["core.device_orchestrator.DeviceOrchestrator"]
        assert entry.pr_guardrail_added == "PR-S7"

    def test_fusion_guardrail_tag(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["fusion.unified_orchestrator"]
        assert entry.pr_guardrail_added == "PR-S7"


# ===========================================================================
# 10. LEGACY_ORCHESTRATOR_PATHS shim includes both new keys
# ===========================================================================

class TestLegacyPathsShim:
    """LEGACY_ORCHESTRATOR_PATHS shim includes the PR-S7 keys."""

    def test_device_orchestrator_in_shim(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert "core.device_orchestrator.DeviceOrchestrator" in LEGACY_ORCHESTRATOR_PATHS

    def test_fusion_in_shim(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert "fusion.unified_orchestrator" in LEGACY_ORCHESTRATOR_PATHS


# ===========================================================================
# 11. PURGE_REGISTRY contains PR-S7 entries
# ===========================================================================

class TestPRS7PurgeRegistry:
    """PURGE_REGISTRY contains all three PR-S7 entries."""

    def test_device_orchestrator_in_purge_registry(self):
        from core.legacy_purge_registry import get_entries_by_pr
        entries = get_entries_by_pr("PR-S7")
        paths = [e.asset_path for e in entries]
        assert any("device_orchestrator" in p for p in paths)

    def test_fusion_in_purge_registry(self):
        from core.legacy_purge_registry import get_entries_by_pr
        entries = get_entries_by_pr("PR-S7")
        paths = [e.asset_path for e in entries]
        assert any("fusion" in p for p in paths)

    def test_canonical_runtime_declaration_in_purge_registry(self):
        from core.legacy_purge_registry import get_entries_by_pr
        entries = get_entries_by_pr("PR-S7")
        paths = [e.asset_path for e in entries]
        assert any("canonical_runtime_declaration" in p for p in paths)

    def test_pr_s7_has_three_entries(self):
        from core.legacy_purge_registry import get_entries_by_pr
        entries = get_entries_by_pr("PR-S7")
        assert len(entries) >= 3


# ===========================================================================
# 12. DeviceOrchestrator docstring carries PR-S7 note
# ===========================================================================

class TestDeviceOrchestratorDocstring:
    """DeviceOrchestrator class docstring references PR-S7."""

    def test_class_docstring_has_prs7_note(self):
        from core.device_orchestrator import DeviceOrchestrator
        doc = DeviceOrchestrator.__doc__ or ""
        assert "PR-S7" in doc

    def test_class_docstring_says_canonical_helper(self):
        from core.device_orchestrator import DeviceOrchestrator
        doc = DeviceOrchestrator.__doc__ or ""
        assert "CANONICAL HELPER" in doc.upper() or "canonical helper" in doc.lower()


# ===========================================================================
# 13. fusion.unified_orchestrator deprecation warning references e2e_orchestrator
# ===========================================================================

class TestFusionDeprecationWarning:
    """fusion.unified_orchestrator warns with correct canonical reference."""

    def test_warning_references_e2e_orchestrator(self):
        # Import with warning capture; accept DeprecationWarning
        # The module-level _warnings.warn() fires before any imports that
        # may fail (aiohttp etc.), so we can capture it safely by looking
        # at module-level execution.
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            # Force reimport — even if it later fails with ImportError /
            # AttributeError we still want to check the warnings already
            # emitted at the top of the module.
            if "fusion.unified_orchestrator" in sys.modules:
                del sys.modules["fusion.unified_orchestrator"]
            try:
                import fusion.unified_orchestrator  # noqa: F401
            except Exception:
                pass  # missing deps (aiohttp etc.) are acceptable in test env
        dep_warnings = [
            x for x in w
            if issubclass(x.category, DeprecationWarning)
        ]
        assert dep_warnings, "Expected at least one DeprecationWarning"
        combined = " ".join(str(x.message) for x in dep_warnings)
        assert "e2e_orchestrator" in combined

    def test_warning_does_not_recommend_demoted_orchestrator(self):
        """The warning must NOT recommend galaxy_gateway.orchestrator.GalaxyOrchestrator."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            if "fusion.unified_orchestrator" in sys.modules:
                del sys.modules["fusion.unified_orchestrator"]
            try:
                import fusion.unified_orchestrator  # noqa: F401
            except Exception:
                pass
        dep_warnings = [
            x for x in w
            if issubclass(x.category, DeprecationWarning)
        ]
        combined = " ".join(str(x.message) for x in dep_warnings)
        # Must NOT simply recommend the already-demoted GalaxyOrchestrator
        # (it should be mentioned as "itself demoted" or similar, not as the target)
        assert "GalaxyOrchestrator" not in combined or "demoted" in combined.lower() or "废弃" in combined


# ===========================================================================
# 14–16. Architecture completion scorecard
# ===========================================================================

class TestArchitectureCompletionScorecard:
    """Architecture completion scorecard reflects PR-S7 improvements."""

    def setup_method(self):
        from core.architecture_completion import reset_architecture_completion_scorecard
        reset_architecture_completion_scorecard()

    def test_scorecard_generated_by_prs7(self):
        from core.architecture_completion import get_architecture_completion_scorecard
        sc = get_architecture_completion_scorecard()
        assert sc.generated_by_pr == "PR-S7"

    def test_canonical_path_coverage_is_complete(self):
        from core.architecture_completion import (
            get_architecture_completion_scorecard,
            CompletionDimension,
            MaturityLevel,
        )
        sc = get_architecture_completion_scorecard()
        dim = sc.dimension_by_name(CompletionDimension.CANONICAL_PATH_COVERAGE)
        assert dim is not None
        assert dim.maturity_level == MaturityLevel.COMPLETE

    def test_legacy_surface_demotion_no_ambiguity(self):
        from core.architecture_completion import (
            get_architecture_completion_scorecard,
            CompletionDimension,
        )
        sc = get_architecture_completion_scorecard()
        dim = sc.dimension_by_name(CompletionDimension.LEGACY_SURFACE_DEMOTION)
        assert dim is not None
        assert not dim.legacy_ambiguity_remains


# ===========================================================================
# 17. reset_canonical_runtime_declaration() clears singleton
# ===========================================================================

class TestReset:
    """reset_canonical_runtime_declaration() clears the cached singleton."""

    def test_reset_clears_singleton(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            reset_canonical_runtime_declaration,
        )
        a = get_canonical_runtime_declaration()
        reset_canonical_runtime_declaration()
        b = get_canonical_runtime_declaration()
        # After reset, a new object is returned
        assert a is not b

    def teardown_method(self):
        from core.canonical_runtime_declaration import reset_canonical_runtime_declaration
        reset_canonical_runtime_declaration()


# ===========================================================================
# 18. Derived properties
# ===========================================================================

class TestDerivedProperties:
    """Derived property lists are non-empty."""

    def test_canonical_entries_non_empty(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert len(decl.canonical_entries) > 0

    def test_canonical_pipeline_surfaces_non_empty(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert len(decl.canonical_pipeline_surfaces) > 0

    def test_legacy_surfaces_non_empty(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        assert len(decl.legacy_surfaces) > 0


# ===========================================================================
# 19. All pipeline steps have non-empty fields
# ===========================================================================

class TestPipelineStepFields:
    """Every pipeline step has the expected non-empty fields."""

    def test_all_steps_non_empty_authority_module(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        for step in decl.pipeline_steps:
            assert step.authority_module.strip()

    def test_all_steps_non_empty_pr_established(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        for step in decl.pipeline_steps:
            assert step.pr_established.strip()

    def test_all_steps_stage_is_enum(self):
        from core.canonical_runtime_declaration import (
            get_canonical_runtime_declaration,
            CanonicalPipelineStage,
        )
        decl = get_canonical_runtime_declaration()
        for step in decl.pipeline_steps:
            assert isinstance(step.stage, CanonicalPipelineStage)


# ===========================================================================
# 20. surface_by_module() lookup
# ===========================================================================

class TestSurfaceByModule:
    """surface_by_module() correctly locates known modules."""

    def test_finds_openclawd(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        surface = decl.surface_by_module("core.openclawd")
        assert surface is not None
        assert surface.module_path == "core.openclawd"

    def test_returns_none_for_unknown(self):
        from core.canonical_runtime_declaration import get_canonical_runtime_declaration
        decl = get_canonical_runtime_declaration()
        surface = decl.surface_by_module("no.such.module")
        assert surface is None
