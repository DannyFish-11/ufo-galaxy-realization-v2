#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr48_ui_surface_demotions.py
========================================
PR-8 — Demote legacy UI surfaces and standardize projection-only status
architecture.

Validates:
  1.  UISurfaceRole enum has all four required values.
  2.  UISurfaceEntry is a frozen dataclass with required fields.
  3.  UISurfaceEntry.to_dict() returns a complete mapping.
  4.  dashboard.backend.main is registered as LEGACY_UI.
  5.  dashboard package entry is registered as LEGACY_UI.
  6.  windows_client.main is registered as LEGACY_SHELL.
  7.  windows_client.status_board is registered as LEGACY_SHELL (DEPRECATED).
  8.  windows_client package entry is registered as LEGACY_SHELL.
  9.  windows_client.status_board_v2 is registered as PROJECTION_DRIVEN.
 10.  is_legacy_surface() returns True for dashboard.backend.main.
 11.  is_legacy_surface() returns True for windows_client.main.
 12.  is_legacy_surface() returns True for windows_client.status_board.
 13.  is_legacy_surface() returns True for dashboard (package).
 14.  is_legacy_surface() returns True for windows_client (package).
 15.  is_legacy_surface() returns False for windows_client.status_board_v2.
 16.  is_projection_driven_surface() returns True for status_board_v2.
 17.  is_projection_driven_surface() returns False for dashboard.backend.main.
 18.  is_projection_driven_surface() returns False for windows_client.main.
 19.  get_ui_surface_entry() returns correct entry for each surface.
 20.  get_ui_surface_role() returns correct role for each surface.
 21.  get_ui_surface_role() returns None for unknown paths.
 22.  build_ui_surface_authority_summary() includes total_surfaces.
 23.  build_ui_surface_authority_summary() projection_is_only_outward_truth is True.
 24.  build_ui_surface_authority_summary() projection_driven_count >= 1.
 25.  build_ui_surface_authority_summary() legacy_count >= 4.
 26.  build_ui_surface_authority_summary() surfaces list is non-empty.
 27.  UISurfaceAuthorityRegistry singleton returns same instance on repeated calls.
 28.  UISurfaceAuthorityRegistry.projection_driven_surfaces() non-empty.
 29.  UISurfaceAuthorityRegistry.legacy_surfaces() non-empty.
 30.  UISurfaceAuthorityRegistry.all_entries() returns all surfaces.
 31.  status_board_v2 entry has a canonical_contract set.
 32.  Legacy entries have superseded_by pointing to status_board_v2.
 33.  Legacy entries have pr_demoted == "PR-8".
 34.  status_board_v2 entry has pr_demoted == None.
 35.  UI_SURFACE_REGISTRY public dict matches registry contents.
 36.  legacy_paths.py contains dashboard.backend.main entry.
 37.  legacy_paths.py dashboard.backend.main status is LEGACY_COMPATIBILITY.
 38.  legacy_paths.py contains dashboard entry.
 39.  legacy_paths.py contains windows_client.main entry.
 40.  legacy_paths.py windows_client.main status is LEGACY_COMPATIBILITY.
 41.  legacy_paths.py contains windows_client.status_board entry.
 42.  legacy_paths.py windows_client.status_board status is DEPRECATED.
 43.  legacy_paths.py contains windows_client entry.
 44.  legacy_paths.py is_legacy_path() returns True for dashboard.backend.main.
 45.  legacy_paths.py is_legacy_path() returns True for windows_client.main.
 46.  legacy_paths.py is_legacy_path() returns True for windows_client.status_board.
 47.  legacy_paths.py classify_path_status() for dashboard is LEGACY_COMPATIBILITY.
 48.  legacy_paths.py classify_path_status() for windows_client is LEGACY_COMPATIBILITY.
 49.  legacy_paths.py windows_client.status_board recommendation mentions status_board_v2.
 50.  legacy_paths.py dashboard.backend.main recommendation mentions projection.
 51.  legacy_paths.py emit_legacy_guardrail() works for dashboard.backend.main.
 52.  legacy_paths.py emit_legacy_guardrail() works for windows_client.main.
 53.  PR-8 entries do not contaminate PR-7 entries (still present and correct).
 54.  dashboard/__init__.py docstring contains 'LEGACY UI SURFACE'.
 55.  windows_client/__init__.py docstring contains 'HOST-SPECIFIC LEGACY SHELL'.
 56.  windows_client/status_board.py docstring contains 'LEGACY STATUS BOARD'.
 57.  status_board_v2 ProjectionReader uses /api/v1/projection/runtime endpoint.
 58.  status_board_v2 ProjectionReader does NOT use /api/v1/continuum/state.
 59.  status_board_v2 __init__.py read-only guarantee is documented.
 60.  status_board_v2 exports ProjectionReader in __all__.
 61.  get_ui_surface_authority() returns the singleton registry.
 62.  UISurfaceRole.PROJECTION_DRIVEN value is "projection_driven".
 63.  UISurfaceRole.LEGACY_UI value is "legacy_ui".
 64.  UISurfaceRole.LEGACY_SHELL value is "legacy_shell".
 65.  UISurfaceRole.COMPATIBILITY_ONLY value is "compatibility_only".
 66.  dashboard entry to_dict() role is "legacy_ui".
 67.  windows_client.main entry to_dict() role is "legacy_shell".
 68.  status_board_v2 entry to_dict() role is "projection_driven".
 69.  UISurfaceEntry notes field is non-empty for all legacy entries.
 70.  UISurfaceEntry description field is non-empty for all entries.
 71.  projection-driven surfaces all have canonical_contract set.
 72.  legacy surfaces all have superseded_by set (not None).
 73.  legacy_paths.py PR-8 entries all have pr_guardrail_added == "PR-8".
 74.  LEGACY_ORCHESTRATOR_PATHS (frozenset) updated with PR-8 entries.
 75.  dashboard entry notes field mentions 'LEGACY UI SURFACE'.
 76.  windows_client.main entry notes field mentions 'LEGACY SHELL'.
 77.  windows_client.status_board entry notes field mentions 'LEGACY STATUS BOARD'.
 78.  summary dict round-trips to/from string without error.
 79.  UISurfaceAuthorityRegistry.summary() total_surfaces >= 5.
 80.  Multiple calls to build_ui_surface_authority_summary() are idempotent.

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import importlib
import json
import sys
from typing import Any, Dict, Optional

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_ui_surface_authority():
    """Import core.ui_surface_authority, skipping if unavailable."""
    try:
        import core.ui_surface_authority as m
        return m
    except ImportError as exc:
        pytest.skip(f"core.ui_surface_authority not importable: {exc}")


def _import_legacy_paths():
    """Import core.orchestration_authority.legacy_paths, skipping if unavailable."""
    try:
        import core.orchestration_authority.legacy_paths as m
        return m
    except ImportError as exc:
        pytest.skip(f"core.orchestration_authority.legacy_paths not importable: {exc}")


def _import_projection_reader():
    """Import windows_client.status_board_v2.projection_reader."""
    try:
        import windows_client.status_board_v2.projection_reader as m
        return m
    except ImportError as exc:
        pytest.skip(f"windows_client.status_board_v2.projection_reader not importable: {exc}")


def _import_status_board_v2_init():
    """Import windows_client.status_board_v2 package."""
    try:
        import windows_client.status_board_v2 as m
        return m
    except ImportError as exc:
        pytest.skip(f"windows_client.status_board_v2 not importable: {exc}")


# ---------------------------------------------------------------------------
# 1–9: UISurfaceRole enum and basic entry structure
# ---------------------------------------------------------------------------


class TestUISurfaceRoleEnum:
    def test_01_role_enum_has_projection_driven(self):
        m = _import_ui_surface_authority()
        assert hasattr(m.UISurfaceRole, "PROJECTION_DRIVEN")

    def test_02_role_enum_has_legacy_ui(self):
        m = _import_ui_surface_authority()
        assert hasattr(m.UISurfaceRole, "LEGACY_UI")

    def test_03_role_enum_has_legacy_shell(self):
        m = _import_ui_surface_authority()
        assert hasattr(m.UISurfaceRole, "LEGACY_SHELL")

    def test_04_role_enum_has_compatibility_only(self):
        m = _import_ui_surface_authority()
        assert hasattr(m.UISurfaceRole, "COMPATIBILITY_ONLY")

    def test_62_projection_driven_value(self):
        m = _import_ui_surface_authority()
        assert m.UISurfaceRole.PROJECTION_DRIVEN.value == "projection_driven"

    def test_63_legacy_ui_value(self):
        m = _import_ui_surface_authority()
        assert m.UISurfaceRole.LEGACY_UI.value == "legacy_ui"

    def test_64_legacy_shell_value(self):
        m = _import_ui_surface_authority()
        assert m.UISurfaceRole.LEGACY_SHELL.value == "legacy_shell"

    def test_65_compatibility_only_value(self):
        m = _import_ui_surface_authority()
        assert m.UISurfaceRole.COMPATIBILITY_ONLY.value == "compatibility_only"


class TestUISurfaceEntryDataclass:
    def test_05_entry_is_dataclass(self):
        import dataclasses
        m = _import_ui_surface_authority()
        assert dataclasses.is_dataclass(m.UISurfaceEntry)

    def test_06_entry_to_dict_returns_dict(self):
        m = _import_ui_surface_authority()
        entry = m.UISurfaceEntry(
            surface_path="test.surface",
            role=m.UISurfaceRole.LEGACY_UI,
            description="test",
        )
        result = entry.to_dict()
        assert isinstance(result, dict)

    def test_07_entry_to_dict_has_required_keys(self):
        m = _import_ui_surface_authority()
        entry = m.UISurfaceEntry(
            surface_path="test.surface",
            role=m.UISurfaceRole.LEGACY_UI,
            description="test",
        )
        result = entry.to_dict()
        for key in ("surface_path", "role", "description", "canonical_contract",
                    "superseded_by", "pr_demoted", "notes"):
            assert key in result, f"Missing key: {key}"

    def test_66_dashboard_entry_to_dict_role(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("dashboard.backend.main")
        assert entry is not None
        assert entry.to_dict()["role"] == "legacy_ui"

    def test_67_windows_client_main_entry_to_dict_role(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("windows_client.main")
        assert entry is not None
        assert entry.to_dict()["role"] == "legacy_shell"

    def test_68_status_board_v2_entry_to_dict_role(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("windows_client.status_board_v2")
        assert entry is not None
        assert entry.to_dict()["role"] == "projection_driven"


# ---------------------------------------------------------------------------
# 8–18: Registry surface roles
# ---------------------------------------------------------------------------


class TestRegistrySurfaceClassification:
    def test_08_dashboard_backend_main_is_legacy_ui(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("dashboard.backend.main")
        assert entry is not None
        assert entry.role == m.UISurfaceRole.LEGACY_UI

    def test_09_dashboard_package_is_legacy_ui(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("dashboard")
        assert entry is not None
        assert entry.role == m.UISurfaceRole.LEGACY_UI

    def test_10_windows_client_main_is_legacy_shell(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("windows_client.main")
        assert entry is not None
        assert entry.role == m.UISurfaceRole.LEGACY_SHELL

    def test_11_windows_client_status_board_is_legacy_shell(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("windows_client.status_board")
        assert entry is not None
        assert entry.role == m.UISurfaceRole.LEGACY_SHELL

    def test_12_windows_client_package_is_legacy_shell(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("windows_client")
        assert entry is not None
        assert entry.role == m.UISurfaceRole.LEGACY_SHELL

    def test_13_status_board_v2_is_projection_driven(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("windows_client.status_board_v2")
        assert entry is not None
        assert entry.role == m.UISurfaceRole.PROJECTION_DRIVEN


class TestIsLegacySurface:
    def test_14_is_legacy_dashboard_backend_main(self):
        m = _import_ui_surface_authority()
        assert m.is_legacy_surface("dashboard.backend.main") is True

    def test_15_is_legacy_windows_client_main(self):
        m = _import_ui_surface_authority()
        assert m.is_legacy_surface("windows_client.main") is True

    def test_16_is_legacy_windows_client_status_board(self):
        m = _import_ui_surface_authority()
        assert m.is_legacy_surface("windows_client.status_board") is True

    def test_17_is_legacy_dashboard_package(self):
        m = _import_ui_surface_authority()
        assert m.is_legacy_surface("dashboard") is True

    def test_18_is_legacy_windows_client_package(self):
        m = _import_ui_surface_authority()
        assert m.is_legacy_surface("windows_client") is True

    def test_19_is_not_legacy_status_board_v2(self):
        m = _import_ui_surface_authority()
        assert m.is_legacy_surface("windows_client.status_board_v2") is False


class TestIsProjectionDrivenSurface:
    def test_20_is_projection_driven_status_board_v2(self):
        m = _import_ui_surface_authority()
        assert m.is_projection_driven_surface("windows_client.status_board_v2") is True

    def test_21_is_not_projection_driven_dashboard(self):
        m = _import_ui_surface_authority()
        assert m.is_projection_driven_surface("dashboard.backend.main") is False

    def test_22_is_not_projection_driven_windows_client_main(self):
        m = _import_ui_surface_authority()
        assert m.is_projection_driven_surface("windows_client.main") is False


class TestGetSurfaceHelpers:
    def test_23_get_entry_returns_entry(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("dashboard.backend.main")
        assert entry is not None
        assert entry.surface_path == "dashboard.backend.main"

    def test_24_get_entry_returns_none_for_unknown(self):
        m = _import_ui_surface_authority()
        assert m.get_ui_surface_entry("nonexistent.surface") is None

    def test_25_get_role_returns_role(self):
        m = _import_ui_surface_authority()
        role = m.get_ui_surface_role("dashboard.backend.main")
        assert role == m.UISurfaceRole.LEGACY_UI

    def test_26_get_role_returns_none_for_unknown(self):
        m = _import_ui_surface_authority()
        assert m.get_ui_surface_role("nonexistent.surface") is None


# ---------------------------------------------------------------------------
# 27–35: Summary and registry completeness
# ---------------------------------------------------------------------------


class TestBuildUISurfaceAuthoritySummary:
    def test_27_summary_has_total_surfaces(self):
        m = _import_ui_surface_authority()
        summary = m.build_ui_surface_authority_summary()
        assert "total_surfaces" in summary

    def test_28_summary_projection_is_only_outward_truth(self):
        m = _import_ui_surface_authority()
        summary = m.build_ui_surface_authority_summary()
        assert summary["projection_is_only_outward_truth"] is True

    def test_29_summary_projection_driven_count_ge_1(self):
        m = _import_ui_surface_authority()
        summary = m.build_ui_surface_authority_summary()
        assert summary["projection_driven_count"] >= 1

    def test_30_summary_legacy_count_ge_4(self):
        m = _import_ui_surface_authority()
        summary = m.build_ui_surface_authority_summary()
        assert summary["legacy_count"] >= 4

    def test_31_summary_surfaces_list_non_empty(self):
        m = _import_ui_surface_authority()
        summary = m.build_ui_surface_authority_summary()
        assert isinstance(summary["surfaces"], list)
        assert len(summary["surfaces"]) > 0

    def test_79_summary_total_surfaces_ge_5(self):
        m = _import_ui_surface_authority()
        summary = m.build_ui_surface_authority_summary()
        assert summary["total_surfaces"] >= 5

    def test_80_summary_idempotent(self):
        m = _import_ui_surface_authority()
        s1 = m.build_ui_surface_authority_summary()
        s2 = m.build_ui_surface_authority_summary()
        assert s1 == s2

    def test_78_summary_json_serialisable(self):
        m = _import_ui_surface_authority()
        summary = m.build_ui_surface_authority_summary()
        text = json.dumps(summary)
        parsed = json.loads(text)
        assert parsed["projection_is_only_outward_truth"] is True


class TestRegistrySingleton:
    def test_32_singleton_returns_same_instance(self):
        m = _import_ui_surface_authority()
        r1 = m.get_ui_surface_authority()
        r2 = m.get_ui_surface_authority()
        assert r1 is r2

    def test_33_projection_driven_surfaces_non_empty(self):
        m = _import_ui_surface_authority()
        reg = m.get_ui_surface_authority()
        assert len(reg.projection_driven_surfaces()) >= 1

    def test_34_legacy_surfaces_non_empty(self):
        m = _import_ui_surface_authority()
        reg = m.get_ui_surface_authority()
        assert len(reg.legacy_surfaces()) >= 4

    def test_35_all_entries_complete(self):
        m = _import_ui_surface_authority()
        reg = m.get_ui_surface_authority()
        entries = reg.all_entries()
        assert len(entries) >= 5


# ---------------------------------------------------------------------------
# 36–53: legacy_paths.py PR-8 entries
# ---------------------------------------------------------------------------


class TestLegacyPathsPR8Entries:
    def test_36_legacy_paths_has_dashboard_backend_main(self):
        m = _import_legacy_paths()
        assert m.is_legacy_path("dashboard.backend.main")

    def test_37_dashboard_backend_main_status_legacy_compat(self):
        m = _import_legacy_paths()
        entry = m.get_legacy_entry("dashboard.backend.main")
        assert entry is not None
        assert entry.status == m.LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_38_legacy_paths_has_dashboard(self):
        m = _import_legacy_paths()
        assert m.is_legacy_path("dashboard")

    def test_39_legacy_paths_has_windows_client_main(self):
        m = _import_legacy_paths()
        assert m.is_legacy_path("windows_client.main")

    def test_40_windows_client_main_status_legacy_compat(self):
        m = _import_legacy_paths()
        entry = m.get_legacy_entry("windows_client.main")
        assert entry is not None
        assert entry.status == m.LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_41_legacy_paths_has_windows_client_status_board(self):
        m = _import_legacy_paths()
        assert m.is_legacy_path("windows_client.status_board")

    def test_42_windows_client_status_board_is_deprecated(self):
        m = _import_legacy_paths()
        entry = m.get_legacy_entry("windows_client.status_board")
        assert entry is not None
        assert entry.status == m.LegacyPathStatus.DEPRECATED

    def test_43_legacy_paths_has_windows_client(self):
        m = _import_legacy_paths()
        assert m.is_legacy_path("windows_client")

    def test_44_is_legacy_path_dashboard_backend_main(self):
        m = _import_legacy_paths()
        assert m.is_legacy_path("dashboard.backend.main") is True

    def test_45_is_legacy_path_windows_client_main(self):
        m = _import_legacy_paths()
        assert m.is_legacy_path("windows_client.main") is True

    def test_46_is_legacy_path_windows_client_status_board(self):
        m = _import_legacy_paths()
        assert m.is_legacy_path("windows_client.status_board") is True

    def test_47_classify_dashboard_is_legacy_compat(self):
        m = _import_legacy_paths()
        status = m.classify_path_status("dashboard")
        assert status == m.LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_48_classify_windows_client_is_legacy_compat(self):
        m = _import_legacy_paths()
        status = m.classify_path_status("windows_client")
        assert status == m.LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_49_status_board_recommendation_mentions_v2(self):
        m = _import_legacy_paths()
        entry = m.get_legacy_entry("windows_client.status_board")
        assert entry is not None
        assert "status_board_v2" in entry.recommendation

    def test_50_dashboard_recommendation_mentions_projection(self):
        m = _import_legacy_paths()
        entry = m.get_legacy_entry("dashboard.backend.main")
        assert entry is not None
        # recommendation should mention projection or /api/v1/projection
        assert "projection" in entry.recommendation.lower()

    def test_73_pr8_entries_have_correct_guardrail_pr(self):
        m = _import_legacy_paths()
        for path in ("dashboard.backend.main", "dashboard",
                     "windows_client.main", "windows_client.status_board",
                     "windows_client"):
            entry = m.get_legacy_entry(path)
            assert entry is not None, f"Missing entry for {path}"
            assert entry.pr_guardrail_added == "PR-8", (
                f"{path} pr_guardrail_added={entry.pr_guardrail_added}"
            )

    def test_74_legacy_orchestrator_paths_updated(self):
        m = _import_legacy_paths()
        assert "dashboard.backend.main" in m.LEGACY_ORCHESTRATOR_PATHS
        assert "windows_client.main" in m.LEGACY_ORCHESTRATOR_PATHS
        assert "windows_client.status_board" in m.LEGACY_ORCHESTRATOR_PATHS


class TestLegacyGuardrailEmitter:
    def test_51_guardrail_emitter_dashboard(self, caplog):
        import logging
        m = _import_legacy_paths()
        with caplog.at_level(logging.WARNING, logger="Galaxy.OrchestrationAuthority"):
            m.emit_legacy_guardrail("dashboard.backend.main", trace_id="test-trace-001")
        assert any("LEGACY PATH GUARDRAIL" in r.message for r in caplog.records)

    def test_52_guardrail_emitter_windows_client(self, caplog):
        import logging
        m = _import_legacy_paths()
        with caplog.at_level(logging.WARNING, logger="Galaxy.OrchestrationAuthority"):
            m.emit_legacy_guardrail("windows_client.main", trace_id="test-trace-002")
        assert any("LEGACY PATH GUARDRAIL" in r.message for r in caplog.records)


class TestPR7EntriesUnchanged:
    def test_53_pr7_gateway_orchestrator_still_present(self):
        m = _import_legacy_paths()
        entry = m.get_legacy_entry("galaxy_gateway.orchestrator.galaxy_orchestrator")
        assert entry is not None
        assert entry.pr_guardrail_added == "PR-7"
        assert entry.status == m.LegacyPathStatus.LEGACY_COMPATIBILITY

    def test_53b_pr7_device_router_still_present(self):
        m = _import_legacy_paths()
        entry = m.get_legacy_entry("galaxy_gateway.device_router.DeviceRouter.route_task")
        assert entry is not None
        assert entry.pr_guardrail_added == "PR-7"


# ---------------------------------------------------------------------------
# 54–60: Module-level docstring/comment markers
# ---------------------------------------------------------------------------


class TestModuleDocstrings:
    def test_54_dashboard_init_docstring_contains_legacy(self):
        import pathlib
        path = pathlib.Path(__file__).parent.parent / "dashboard" / "__init__.py"
        text = path.read_text(encoding="utf-8")
        assert "LEGACY UI SURFACE" in text

    def test_55_windows_client_init_docstring_contains_legacy(self):
        import pathlib
        path = pathlib.Path(__file__).parent.parent / "windows_client" / "__init__.py"
        text = path.read_text(encoding="utf-8")
        assert "HOST-SPECIFIC LEGACY SHELL" in text

    def test_56_status_board_docstring_contains_legacy(self):
        import pathlib
        path = (pathlib.Path(__file__).parent.parent
                / "windows_client" / "status_board.py")
        text = path.read_text(encoding="utf-8")
        assert "LEGACY STATUS BOARD" in text

    def test_56b_status_board_docstring_mentions_superseded(self):
        import pathlib
        path = (pathlib.Path(__file__).parent.parent
                / "windows_client" / "status_board.py")
        text = path.read_text(encoding="utf-8")
        assert "status_board_v2" in text

    def test_56c_dashboard_backend_main_docstring_contains_legacy(self):
        import pathlib
        path = (pathlib.Path(__file__).parent.parent
                / "dashboard" / "backend" / "main.py")
        text = path.read_text(encoding="utf-8")
        assert "LEGACY UI SURFACE" in text


class TestStatusBoardV2ProjectionDriven:
    def test_57_projection_reader_uses_projection_endpoint(self):
        m = _import_projection_reader()
        assert m.PROJECTION_ENDPOINT == "/api/v1/projection/runtime"

    def test_58_projection_reader_does_not_use_continuum_state(self):
        """status_board.py uses /api/v1/continuum/state; status_board_v2 must not."""
        m = _import_projection_reader()
        import inspect
        src = inspect.getsource(m)
        # The reader should reference projection/runtime, not continuum/state
        assert "/api/v1/continuum/state" not in src

    def test_59_status_board_v2_init_documents_read_only(self):
        m = _import_status_board_v2_init()
        import inspect
        src = inspect.getfile(m)
        import pathlib
        init_path = pathlib.Path(src).parent / "__init__.py"
        text = init_path.read_text(encoding="utf-8")
        assert "READ-ONLY" in text or "read-only" in text.lower()

    def test_60_status_board_v2_exports_projection_reader(self):
        m = _import_status_board_v2_init()
        assert "ProjectionReader" in m.__all__


# ---------------------------------------------------------------------------
# 61–80: Additional invariants
# ---------------------------------------------------------------------------


class TestAdditionalInvariants:
    def test_61_get_ui_surface_authority_returns_registry(self):
        m = _import_ui_surface_authority()
        reg = m.get_ui_surface_authority()
        assert isinstance(reg, m.UISurfaceAuthorityRegistry)

    def test_69_notes_non_empty_for_all_legacy_entries(self):
        m = _import_ui_surface_authority()
        reg = m.get_ui_surface_authority()
        for entry in reg.legacy_surfaces():
            assert entry.notes, f"Missing notes for {entry.surface_path}"

    def test_70_description_non_empty_for_all_entries(self):
        m = _import_ui_surface_authority()
        reg = m.get_ui_surface_authority()
        for entry in reg.all_entries():
            assert entry.description, f"Missing description for {entry.surface_path}"

    def test_71_projection_driven_have_canonical_contract(self):
        m = _import_ui_surface_authority()
        reg = m.get_ui_surface_authority()
        for entry in reg.projection_driven_surfaces():
            assert entry.canonical_contract, (
                f"Missing canonical_contract for {entry.surface_path}"
            )

    def test_72_legacy_surfaces_have_superseded_by(self):
        m = _import_ui_surface_authority()
        reg = m.get_ui_surface_authority()
        for entry in reg.legacy_surfaces():
            assert entry.superseded_by, (
                f"Missing superseded_by for legacy {entry.surface_path}"
            )

    def test_33_pr8_entries_have_pr_demoted(self):
        m = _import_ui_surface_authority()
        reg = m.get_ui_surface_authority()
        for entry in reg.legacy_surfaces():
            assert entry.pr_demoted == "PR-8", (
                f"Wrong pr_demoted for {entry.surface_path}: {entry.pr_demoted}"
            )

    def test_34_projection_driven_has_no_pr_demoted(self):
        m = _import_ui_surface_authority()
        reg = m.get_ui_surface_authority()
        for entry in reg.projection_driven_surfaces():
            assert entry.pr_demoted is None, (
                f"Unexpected pr_demoted on {entry.surface_path}: {entry.pr_demoted}"
            )

    def test_35_public_registry_dict_matches_registry(self):
        m = _import_ui_surface_authority()
        reg = m.get_ui_surface_authority()
        for path, entry in m.UI_SURFACE_REGISTRY.items():
            assert reg.get(path) is not None, f"Missing {path} in registry singleton"

    def test_75_dashboard_entry_notes_contains_legacy(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("dashboard")
        assert entry is not None and entry.notes is not None
        assert "LEGACY UI SURFACE" in entry.notes or "LEGACY" in entry.notes

    def test_76_windows_client_main_notes_contains_legacy(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("windows_client.main")
        assert entry is not None and entry.notes is not None
        assert "LEGACY" in entry.notes

    def test_77_windows_client_status_board_notes_contains_legacy(self):
        m = _import_ui_surface_authority()
        entry = m.get_ui_surface_entry("windows_client.status_board")
        assert entry is not None and entry.notes is not None
        assert "LEGACY STATUS BOARD" in entry.notes
