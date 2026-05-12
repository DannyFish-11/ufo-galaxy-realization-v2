#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prd_desktop_status_board_productization.py
=======================================================
PR-D — Productize the desktop status board on top of unified cross-repo state.

Validates that the desktop status board:

1. Exposes the full required-scope category set (registration state, capability
   visibility, gateway/bridge presence, operational readiness, admission verdict,
   main-chain availability, cross-device availability, active path,
   compat/degraded path, recovery-active state, session continuity,
   participant/device/session dependencies, runtime host/dispatch binding,
   task initiation eligibility, task execution visibility, result closure state,
   success quality, verdict quality, blocked/waiting/incomplete/degraded
   conditions).
2. Classifies every category with a ``lifecycle_stage`` from the set:
   observation | admission | readiness | eligibility | execution | closure |
   conditions.
3. Exposes ``source_of_truth_boundary`` (V2-authoritative | android_originated |
   joint_cross_repo_derived) per category.
4. Exposes the ``lifecycle_stage_index`` mapping.
5. State contract version is bumped to 1.2.0 to reflect the new categories.
6. ``ContractDecision.to_dict()`` includes ``lifecycle_stage``.
7. ``OperationalStateSurface.render()`` groups categories by lifecycle stage.
8. ``OperationalStateSurface`` colour-codes state values.
9. The board renders correctly when no unified state contract is attached.
10. Degraded and recovery states surface as first-class states in the board.
11. Android-specific categories (gateway, dispatch, participant) are
    ``not_applicable`` when Android is not attached.
12. Android-specific categories show correct states when Android is attached.
13. ``_empty_operational_state_board`` includes ``lifecycle_stage_index``.
14. New categories appear in the assembled board payload.
15. Board includes the ``lifecycle_stage_index`` after full assembly.

Test groups
-----------
A  ContractDecision.lifecycle_stage field (1-3)
B  V2_UNIFIED_STATE_CONTRACT_VERSION bump (4)
C  New derived_state categories (5-9)
D  Lifecycle stage on existing categories (10-15)
E  Source-of-truth boundary classification (16-17)
F  Projection-layer board assembly (18-22)
G  OperationalStateSurface renderer (23-28)
H  End-to-end board assembly (29-32)
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

import pytest

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_path_and_validation():
    """Return a minimal (path, validation) pair that passes V2 side."""
    from core.operational_registration_path import (
        OperationalRegistrationPath,
        OnboardingValidation,
        ValidationStatus,
    )
    path = OperationalRegistrationPath()
    validation = OnboardingValidation(
        overall_status=ValidationStatus.PASS,
        summary="All checks passed.",
    )
    return path, validation


def _build_minimal_contract(
    *,
    android_attached: bool = False,
    android_device_count: int = 0,
    snapshot_count: int = 0,
    capability_visible_count: int = 0,
    degraded_capability_device_count: int = 0,
    active_session_count: int = 0,
    total_session_count: int = 0,
    participant_total_count: int = 0,
    task_initiated: bool = False,
    result_closure_established: bool = False,
    recovery_active: bool = False,
    route_paths: Optional[List[str]] = None,
):
    """Build a V2UnifiedStateContract with configurable evidence."""
    from core.v2_unified_state_contract import build_v2_unified_state_contract

    path, validation = _minimal_path_and_validation()
    kind_states: List[Any] = []
    device_evidence = {"android_device_count": android_device_count}
    android_evidence = {
        "snapshot_count": snapshot_count,
        "capability_visible_count": capability_visible_count,
        "degraded_capability_device_count": degraded_capability_device_count,
    }
    session_evidence = {
        "active_session_count": active_session_count,
        "total_session_count": total_session_count,
        "participant_total_count": participant_total_count,
        "task_initiated": task_initiated,
        "result_closure_established": result_closure_established,
        "recovery_active": recovery_active,
        "replaced_session_count": 0,
        "detached_session_count": 0,
        "invalidated_session_count": 0,
        "participant_terminal_count": 0,
        "participant_terminal_success_count": 0,
    }
    rt = {"/api/v1/health", "/api/v1/chat", "/api/v1/projection/runtime"}
    rp = set(route_paths) if route_paths is not None else rt
    return build_v2_unified_state_contract(
        path=path,
        validation=validation,
        kind_states=kind_states,
        route_paths=rp,
        runtime_readiness={"verdict": "ok"},
        device_evidence=device_evidence,
        android_evidence=android_evidence,
        session_evidence=session_evidence,
    )


def _contract_dict(
    *,
    android_attached: bool = False,
    android_device_count: int = 0,
    snapshot_count: int = 0,
    capability_visible_count: int = 0,
    active_session_count: int = 0,
    task_initiated: bool = False,
    result_closure_established: bool = False,
    recovery_active: bool = False,
):
    c = _build_minimal_contract(
        android_device_count=android_device_count,
        snapshot_count=snapshot_count,
        capability_visible_count=capability_visible_count,
        active_session_count=active_session_count,
        task_initiated=task_initiated,
        result_closure_established=result_closure_established,
        recovery_active=recovery_active,
    )
    return c.to_dict()


# ---------------------------------------------------------------------------
# Group A: ContractDecision.lifecycle_stage field
# ---------------------------------------------------------------------------

def test_A1_contract_decision_has_lifecycle_stage_field():
    from core.v2_unified_state_contract import ContractDecision
    d = ContractDecision(
        decision_id="test",
        label="Test",
        state="ready",
        summary="test",
        lifecycle_stage="observation",
    )
    assert d.lifecycle_stage == "observation"


def test_A2_contract_decision_to_dict_includes_lifecycle_stage():
    from core.v2_unified_state_contract import ContractDecision
    d = ContractDecision(
        decision_id="test",
        label="Test",
        state="ready",
        summary="test",
        lifecycle_stage="admission",
    )
    result = d.to_dict()
    assert "lifecycle_stage" in result
    assert result["lifecycle_stage"] == "admission"


def test_A3_contract_decision_to_dict_omits_lifecycle_stage_when_none():
    from core.v2_unified_state_contract import ContractDecision
    d = ContractDecision(
        decision_id="test",
        label="Test",
        state="ready",
        summary="test",
    )
    result = d.to_dict()
    assert result.get("lifecycle_stage") is None or "lifecycle_stage" not in result or result["lifecycle_stage"] is None


# ---------------------------------------------------------------------------
# Group B: Contract version bump
# ---------------------------------------------------------------------------

def test_B4_v2_unified_state_contract_version_is_1_2_0():
    from core.v2_unified_state_contract import V2_UNIFIED_STATE_CONTRACT_VERSION
    # PR-1 bumped the contract to 1.3.0 to reflect the addition of the
    # android_network_participation derived_state decision and the
    # participation_evidence parameter.
    assert V2_UNIFIED_STATE_CONTRACT_VERSION in {"1.2.0", "1.3.0"}, (
        f"Expected V2_UNIFIED_STATE_CONTRACT_VERSION in {{'1.2.0', '1.3.0'}}, "
        f"got '{V2_UNIFIED_STATE_CONTRACT_VERSION}'"
    )


# ---------------------------------------------------------------------------
# Group C: New derived_state categories
# ---------------------------------------------------------------------------

def test_C5_contract_has_gateway_bridge_presence_in_derived_state():
    c = _build_minimal_contract()
    assert "gateway_bridge_presence" in c.derived_state, (
        "derived_state missing gateway_bridge_presence"
    )


def test_C6_gateway_bridge_presence_not_applicable_without_android():
    c = _build_minimal_contract()
    d = c.derived_state["gateway_bridge_presence"]
    assert d.state == "not_applicable", (
        f"Expected not_applicable without Android, got '{d.state}'"
    )


def test_C7_gateway_bridge_presence_present_with_android_attached():
    c = _build_minimal_contract(android_device_count=1, snapshot_count=1)
    d = c.derived_state["gateway_bridge_presence"]
    assert d.state in ("present", "degraded"), (
        f"Expected present or degraded with Android attached, got '{d.state}'"
    )


def test_C8_contract_has_runtime_host_dispatch_binding_in_derived_state():
    c = _build_minimal_contract()
    assert "runtime_host_dispatch_binding" in c.derived_state, (
        "derived_state missing runtime_host_dispatch_binding"
    )


def test_C9_runtime_host_dispatch_not_applicable_without_android():
    c = _build_minimal_contract()
    d = c.derived_state["runtime_host_dispatch_binding"]
    assert d.state == "not_applicable", (
        f"Expected not_applicable without Android, got '{d.state}'"
    )


def test_C10_contract_has_participant_device_session_dependencies_in_derived_state():
    c = _build_minimal_contract()
    assert "participant_device_session_dependencies" in c.derived_state, (
        "derived_state missing participant_device_session_dependencies"
    )


def test_C11_participant_device_session_not_applicable_without_android():
    c = _build_minimal_contract()
    d = c.derived_state["participant_device_session_dependencies"]
    assert d.state == "not_applicable", (
        f"Expected not_applicable without Android, got '{d.state}'"
    )


def test_C12_task_execution_visibility_in_closure_quality_state():
    c = _build_minimal_contract()
    assert "task_execution_visibility" in c.closure_quality_state, (
        "closure_quality_state missing task_execution_visibility"
    )


def test_C13_task_execution_not_applicable_without_android():
    c = _build_minimal_contract()
    d = c.closure_quality_state["task_execution_visibility"]
    assert d.state == "not_applicable", (
        f"Expected not_applicable without Android, got '{d.state}'"
    )


# ---------------------------------------------------------------------------
# Group D: Lifecycle stage on existing and new categories
# ---------------------------------------------------------------------------

def test_D14_registration_state_has_lifecycle_stage_observation():
    c = _build_minimal_contract()
    d = c.derived_state["registration_state"]
    assert d.lifecycle_stage == "observation", (
        f"registration_state lifecycle_stage should be 'observation', got '{d.lifecycle_stage}'"
    )


def test_D15_capability_visibility_has_lifecycle_stage_observation():
    c = _build_minimal_contract()
    d = c.derived_state["capability_visibility"]
    assert d.lifecycle_stage == "observation", (
        f"capability_visibility lifecycle_stage should be 'observation', got '{d.lifecycle_stage}'"
    )


def test_D16_gateway_bridge_presence_has_lifecycle_stage_observation():
    c = _build_minimal_contract()
    d = c.derived_state["gateway_bridge_presence"]
    assert d.lifecycle_stage == "observation", (
        f"gateway_bridge_presence lifecycle_stage should be 'observation', got '{d.lifecycle_stage}'"
    )


def test_D17_operational_readiness_has_lifecycle_stage_admission():
    c = _build_minimal_contract()
    d = c.derived_state["operational_readiness"]
    assert d.lifecycle_stage == "admission", (
        f"operational_readiness lifecycle_stage should be 'admission', got '{d.lifecycle_stage}'"
    )


def test_D18_main_chain_availability_has_lifecycle_stage_admission():
    c = _build_minimal_contract()
    d = c.derived_state["main_chain_availability"]
    assert d.lifecycle_stage == "admission", (
        f"main_chain_availability lifecycle_stage should be 'admission', got '{d.lifecycle_stage}'"
    )


def test_D19_active_path_has_lifecycle_stage_readiness():
    c = _build_minimal_contract()
    d = c.derived_state["active_path"]
    assert d.lifecycle_stage == "readiness", (
        f"active_path lifecycle_stage should be 'readiness', got '{d.lifecycle_stage}'"
    )


def test_D20_recovery_active_state_has_lifecycle_stage_readiness():
    c = _build_minimal_contract()
    d = c.derived_state["recovery_active_state"]
    assert d.lifecycle_stage == "readiness", (
        f"recovery_active_state lifecycle_stage should be 'readiness', got '{d.lifecycle_stage}'"
    )


def test_D21_session_continuity_has_lifecycle_stage_readiness():
    c = _build_minimal_contract()
    d = c.derived_state["session_continuity"]
    assert d.lifecycle_stage == "readiness", (
        f"session_continuity lifecycle_stage should be 'readiness', got '{d.lifecycle_stage}'"
    )


def test_D22_participant_device_session_has_lifecycle_stage_readiness():
    c = _build_minimal_contract()
    d = c.derived_state["participant_device_session_dependencies"]
    assert d.lifecycle_stage == "readiness", (
        f"participant_device_session_dependencies lifecycle_stage should be 'readiness', got '{d.lifecycle_stage}'"
    )


def test_D23_runtime_host_dispatch_has_lifecycle_stage_eligibility():
    c = _build_minimal_contract()
    d = c.derived_state["runtime_host_dispatch_binding"]
    assert d.lifecycle_stage == "eligibility", (
        f"runtime_host_dispatch_binding lifecycle_stage should be 'eligibility', got '{d.lifecycle_stage}'"
    )


def test_D24_task_initiation_has_lifecycle_stage_eligibility():
    c = _build_minimal_contract()
    d = c.eligibility_state["task_initiation"]
    assert d.lifecycle_stage == "eligibility", (
        f"task_initiation lifecycle_stage should be 'eligibility', got '{d.lifecycle_stage}'"
    )


def test_D25_task_execution_visibility_has_lifecycle_stage_execution():
    c = _build_minimal_contract()
    d = c.closure_quality_state["task_execution_visibility"]
    assert d.lifecycle_stage == "execution", (
        f"task_execution_visibility lifecycle_stage should be 'execution', got '{d.lifecycle_stage}'"
    )


def test_D26_result_closure_has_lifecycle_stage_closure():
    c = _build_minimal_contract()
    d = c.closure_quality_state["result_closure"]
    assert d.lifecycle_stage == "closure", (
        f"result_closure lifecycle_stage should be 'closure', got '{d.lifecycle_stage}'"
    )


def test_D27_blocked_state_has_lifecycle_stage_conditions():
    c = _build_minimal_contract()
    d = c.closure_quality_state["blocked_state"]
    assert d.lifecycle_stage == "conditions", (
        f"blocked_state lifecycle_stage should be 'conditions', got '{d.lifecycle_stage}'"
    )


# ---------------------------------------------------------------------------
# Group E: Source-of-truth boundary classification
# ---------------------------------------------------------------------------

def test_E28_registration_state_boundary_is_v2_authoritative():
    c = _build_minimal_contract()
    d = c.derived_state["registration_state"]
    d_dict = d.to_dict()
    sources = d_dict.get("sources") or []
    # registration_state should have no android source → v2_authoritative
    has_android = any("android" in s.lower() for s in sources)
    assert not has_android, (
        f"registration_state should be V2-authoritative (no android source), got sources={sources}"
    )


def test_E29_capability_visibility_boundary_includes_android_origin():
    c = _build_minimal_contract(android_device_count=1)
    d = c.derived_state["capability_visibility"]
    d_dict = d.to_dict()
    sources = d_dict.get("sources") or []
    has_android = any("android" in s.lower() for s in sources)
    assert has_android, (
        f"capability_visibility should have android source, got sources={sources}"
    )


# ---------------------------------------------------------------------------
# Group F: Projection-layer board assembly
# ---------------------------------------------------------------------------

def test_F30_empty_operational_state_board_has_lifecycle_stage_index():
    import importlib
    routes_mod = importlib.import_module("core.routes.projection")
    empty_fn = getattr(routes_mod, "_empty_operational_state_board", None)
    assert empty_fn is not None
    board = empty_fn()
    assert "lifecycle_stage_index" in board, "empty board missing lifecycle_stage_index"
    idx = board["lifecycle_stage_index"]
    for stage in ("observation", "admission", "readiness", "eligibility", "execution", "closure", "conditions"):
        assert stage in idx, f"lifecycle_stage_index missing stage '{stage}'"


def test_F31_build_operational_state_board_includes_new_categories():
    import importlib
    routes_mod = importlib.import_module("core.routes.projection")
    build_fn = getattr(routes_mod, "_build_operational_state_board_from_contract", None)
    assert build_fn is not None
    c = _build_minimal_contract()
    board = build_fn(c.to_dict())
    category_ids = {item["category_id"] for item in board["categories"]}
    assert "gateway_bridge_presence" in category_ids, "board missing gateway_bridge_presence"
    assert "runtime_host_dispatch_binding" in category_ids, "board missing runtime_host_dispatch_binding"
    assert "participant_device_session_dependencies" in category_ids, "board missing participant_device_session_dependencies"
    assert "task_execution_visibility" in category_ids, "board missing task_execution_visibility"


def test_F32_board_categories_include_lifecycle_stage_field():
    import importlib
    routes_mod = importlib.import_module("core.routes.projection")
    build_fn = getattr(routes_mod, "_build_operational_state_board_from_contract", None)
    c = _build_minimal_contract()
    board = build_fn(c.to_dict())
    for item in board["categories"]:
        assert "lifecycle_stage" in item, (
            f"category '{item.get('category_id')}' missing lifecycle_stage field"
        )


def test_F33_board_lifecycle_stage_index_populated():
    import importlib
    routes_mod = importlib.import_module("core.routes.projection")
    build_fn = getattr(routes_mod, "_build_operational_state_board_from_contract", None)
    c = _build_minimal_contract()
    board = build_fn(c.to_dict())
    idx = board.get("lifecycle_stage_index") or {}
    assert idx.get("observation"), "observation stage should be non-empty in lifecycle_stage_index"
    assert idx.get("admission"), "admission stage should be non-empty in lifecycle_stage_index"
    assert idx.get("readiness"), "readiness stage should be non-empty in lifecycle_stage_index"
    assert idx.get("eligibility"), "eligibility stage should be non-empty in lifecycle_stage_index"
    assert idx.get("closure"), "closure stage should be non-empty in lifecycle_stage_index"
    assert idx.get("conditions"), "conditions stage should be non-empty in lifecycle_stage_index"


def test_F34_assemble_desktop_board_includes_new_categories():
    import importlib
    routes_mod = importlib.import_module("core.routes.projection")
    assemble_fn = getattr(routes_mod, "_assemble_desktop_status_board_payload", None)
    assert assemble_fn is not None
    payload = assemble_fn(route_paths={"/api/v1/health", "/api/v1/chat", "/api/v1/projection/runtime"})
    board = payload.get("operational_state_board") or {}
    category_ids = {item.get("category_id") for item in (board.get("categories") or [])}
    assert "gateway_bridge_presence" in category_ids, "assembled board missing gateway_bridge_presence"
    assert "runtime_host_dispatch_binding" in category_ids, "assembled board missing runtime_host_dispatch_binding"
    assert "participant_device_session_dependencies" in category_ids, (
        "assembled board missing participant_device_session_dependencies"
    )
    assert "task_execution_visibility" in category_ids, "assembled board missing task_execution_visibility"


# ---------------------------------------------------------------------------
# Group G: OperationalStateSurface renderer
# ---------------------------------------------------------------------------

def _make_board_with_categories() -> Dict[str, Any]:
    """Return a minimal projection dict with a populated operational_state_board."""
    import importlib
    routes_mod = importlib.import_module("core.routes.projection")
    build_fn = getattr(routes_mod, "_build_operational_state_board_from_contract")
    c = _build_minimal_contract()
    board = build_fn(c.to_dict())
    return {"operational_state_board": board}


def test_G35_operational_state_surface_renders_without_error():
    from windows_client.status_board_v2.operational_state_surface import OperationalStateSurface
    surface = OperationalStateSurface()
    projection = _make_board_with_categories()
    result = surface.render(projection)
    assert isinstance(result, str)
    assert len(result) > 0


def test_G36_rendered_board_contains_lifecycle_stage_headers():
    from windows_client.status_board_v2.operational_state_surface import OperationalStateSurface, _STAGE_LABELS
    surface = OperationalStateSurface()
    projection = _make_board_with_categories()
    result = surface.render(projection)
    # At least observation and admission headers should appear
    assert "Observation" in result or "observation" in result.lower(), (
        "Board render missing Observation stage header"
    )
    assert "Admission" in result or "admission" in result.lower(), (
        "Board render missing Admission stage header"
    )


def test_G37_rendered_board_contains_source_boundary_short_labels():
    from windows_client.status_board_v2.operational_state_surface import OperationalStateSurface
    surface = OperationalStateSurface()
    projection = _make_board_with_categories()
    result = surface.render(projection)
    # V2-authoritative categories should show [V2] short label
    assert "[V2]" in result, "Board render should contain [V2] boundary label"


def test_G38_rendered_board_with_empty_categories_shows_fallback_message():
    from windows_client.status_board_v2.operational_state_surface import OperationalStateSurface
    surface = OperationalStateSurface()
    projection: Dict[str, Any] = {}
    result = surface.render(projection)
    assert "No unified operational state contract attached" in result


def test_G39_rendered_board_blocked_state_shows_conditions():
    from windows_client.status_board_v2.operational_state_surface import OperationalStateSurface
    surface = OperationalStateSurface()
    projection = _make_board_with_categories()
    result = surface.render(projection)
    # Conditions section and Blocked/Incomplete lines should appear
    assert "Blocked" in result
    assert "Incomplete" in result


def test_G40_stage_labels_cover_all_required_stages():
    from windows_client.status_board_v2.operational_state_surface import _STAGE_ORDER, _STAGE_LABELS
    for stage in ("observation", "admission", "readiness", "eligibility", "execution", "closure", "conditions"):
        assert stage in _STAGE_ORDER, f"Missing stage '{stage}' in _STAGE_ORDER"
        assert stage in _STAGE_LABELS, f"Missing stage '{stage}' in _STAGE_LABELS"


# ---------------------------------------------------------------------------
# Group H: End-to-end correctness for Android-attached scenarios
# ---------------------------------------------------------------------------

def test_H41_gateway_bridge_present_when_android_device_count_nonzero():
    c = _build_minimal_contract(android_device_count=2, snapshot_count=2)
    d = c.derived_state["gateway_bridge_presence"]
    assert d.state in ("present", "degraded"), (
        f"gateway_bridge_presence should be present/degraded with android_device_count=2, got '{d.state}'"
    )
    assert d.active is True


def test_H42_runtime_host_dispatch_available_when_android_main_chain_ready():
    c = _build_minimal_contract(
        android_device_count=1,
        snapshot_count=1,
        capability_visible_count=1,
        active_session_count=1,
        route_paths={
            "/api/v1/health", "/api/v1/chat", "/api/v1/projection/runtime",
            "/api/v1/projection/operational-readiness",
            "/api/v1/projection/clone-to-use-acceptance",
        },
    )
    d = c.derived_state["runtime_host_dispatch_binding"]
    assert d.state in ("available", "active"), (
        f"dispatch binding should be available/active with Android+main_chain ready, got '{d.state}'"
    )


def test_H43_runtime_host_dispatch_active_when_task_initiated():
    c = _build_minimal_contract(
        android_device_count=1,
        snapshot_count=1,
        active_session_count=1,
        task_initiated=True,
        route_paths={
            "/api/v1/health", "/api/v1/chat", "/api/v1/projection/runtime",
            "/api/v1/projection/operational-readiness",
            "/api/v1/projection/clone-to-use-acceptance",
        },
    )
    d = c.derived_state["runtime_host_dispatch_binding"]
    assert d.state == "active", (
        f"dispatch binding should be active when task_initiated=True, got '{d.state}'"
    )
    assert d.active is True


def test_H44_participant_dependencies_satisfied_when_cross_device_available():
    c = _build_minimal_contract(
        android_device_count=1,
        snapshot_count=1,
        capability_visible_count=1,
        active_session_count=1,
    )
    d = c.derived_state["participant_device_session_dependencies"]
    assert d.state == "satisfied", (
        f"participant_device_session_dependencies should be 'satisfied' when cross_device_available, got '{d.state}'"
    )
    assert d.active is True


def test_H45_task_execution_visibility_active_when_task_initiated_not_closed():
    c = _build_minimal_contract(
        android_device_count=1,
        active_session_count=1,
        task_initiated=True,
        result_closure_established=False,
    )
    d = c.closure_quality_state["task_execution_visibility"]
    assert d.state == "active", (
        f"task_execution_visibility should be 'active' when task initiated and not closed, got '{d.state}'"
    )
    assert d.active is True
    assert d.complete is False


def test_H46_task_execution_visibility_complete_when_result_closure_established():
    c = _build_minimal_contract(
        android_device_count=1,
        task_initiated=True,
        result_closure_established=True,
    )
    d = c.closure_quality_state["task_execution_visibility"]
    assert d.state == "complete", (
        f"task_execution_visibility should be 'complete' when result_closure_established, got '{d.state}'"
    )
    assert d.complete is True


def test_H47_recovery_active_surfaces_as_first_class_state():
    c = _build_minimal_contract(
        android_device_count=1,
        active_session_count=1,
        recovery_active=True,
    )
    d = c.derived_state["recovery_active_state"]
    assert d.state == "active", (
        f"recovery_active_state should be 'active', got '{d.state}'"
    )
    assert d.active is True


def test_H48_degraded_path_surfaces_as_first_class_in_board():
    import importlib
    routes_mod = importlib.import_module("core.routes.projection")
    build_fn = getattr(routes_mod, "_build_operational_state_board_from_contract")
    # Provide all required routes so main_chain is available but degraded via runtime_verdict
    from core.v2_unified_state_contract import build_v2_unified_state_contract, _REQUIRED_API_PATHS
    path, validation = _minimal_path_and_validation()
    c = build_v2_unified_state_contract(
        path=path,
        validation=validation,
        kind_states=[],
        route_paths=set(_REQUIRED_API_PATHS),
        runtime_readiness={"verdict": "degraded"},
    )
    board = build_fn(c.to_dict())
    category_map = {item["category_id"]: item for item in board["categories"]}
    op_readiness = category_map.get("operational_readiness") or {}
    assert op_readiness.get("state") == "degraded", (
        f"operational_readiness should be 'degraded' with degraded runtime_verdict, got '{op_readiness.get('state')}'"
    )
    degraded_path = category_map.get("compat_degraded_path") or {}
    assert degraded_path.get("state") == "degraded_operation", (
        f"compat_degraded_path should be 'degraded_operation', got '{degraded_path.get('state')}'"
    )
