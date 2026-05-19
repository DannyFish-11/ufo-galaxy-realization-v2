"""PR-6 minimal runtime mainline boundary lock tests.

Locks the fixed minimal real runtime mainline and side-path demotion contract.
"""

from __future__ import annotations

from core.canonical_execution_chain import (
    CanonicalChainStage,
    CHAIN_STAGE_AUTHORITY,
    CANONICAL_STAGE_ORDER,
    DESKTOP_PRESENCE_RUNTIME_SHELL_AUTHORITY,
    OPENCLAWD_SUBJECT_AUTHORITY,
    COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
    DEVICE_ROUTER_DISPATCH_AUTHORITY,
    MINIMAL_RUNTIME_MAINLINE_MODULES,
    SIDE_PATH_MODULE_REGISTRY,
    get_minimal_runtime_mainline_boundary,
    is_canonical_module,
)


def test_minimal_runtime_mainline_modules_are_fixed_and_ordered():
    assert MINIMAL_RUNTIME_MAINLINE_MODULES == (
        DESKTOP_PRESENCE_RUNTIME_SHELL_AUTHORITY,
        OPENCLAWD_SUBJECT_AUTHORITY,
        COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
        DEVICE_ROUTER_DISPATCH_AUTHORITY,
    )


def test_desktop_runtime_shell_stage_is_in_chain_and_before_openclawd():
    assert CanonicalChainStage.DESKTOP_RUNTIME_SHELL in CHAIN_STAGE_AUTHORITY
    assert (
        CHAIN_STAGE_AUTHORITY[CanonicalChainStage.DESKTOP_RUNTIME_SHELL]
        == DESKTOP_PRESENCE_RUNTIME_SHELL_AUTHORITY
    )
    stages = list(CANONICAL_STAGE_ORDER)
    assert stages.index(CanonicalChainStage.DESKTOP_RUNTIME_SHELL) < stages.index(
        CanonicalChainStage.OPENCLAWD_SUBJECT
    )


def test_is_canonical_module_accepts_runtime_shell_and_rejects_demoted_paths():
    for module in MINIMAL_RUNTIME_MAINLINE_MODULES:
        assert is_canonical_module(module) is True
    for side_path_module in SIDE_PATH_MODULE_REGISTRY:
        assert is_canonical_module(side_path_module) is False


def test_demoted_side_paths_configuration():
    expected_side_path_modules = {
        "core.e2e_orchestrator",
        "core.unified_orchestration_spine",
        "core.local_execution_chain",
        "core.cross_device_execution_chain",
        "core.hybrid_executor",
        "core.remote_execution_mode_resolver",
        "core.repo_coordinator",
        "galaxy_gateway.agent_bridge",
        "galaxy_gateway.task_router",
        "galaxy_gateway.cross_device_coordinator",
        "core.android_runtime_dispatch_binding",
        "core.android_evaluator_artifact_ingress",
        "core.runtime_closure_audit",
        "core.truth_projection_boundary",
        "core.projection_surface_bridge",
    }
    assert set(SIDE_PATH_MODULE_REGISTRY.keys()) == expected_side_path_modules
    assert SIDE_PATH_MODULE_REGISTRY["core.e2e_orchestrator"] == "side_path_facade"
    assert (
        SIDE_PATH_MODULE_REGISTRY["core.unified_orchestration_spine"]
        == "multi_step_session_governor"
    )
    assert (
        SIDE_PATH_MODULE_REGISTRY["core.android_runtime_dispatch_binding"]
        == "android_runtime_binding_helper"
    )
    assert (
        SIDE_PATH_MODULE_REGISTRY["core.android_evaluator_artifact_ingress"]
        == "android_governance_ingress_adapter"
    )
    assert SIDE_PATH_MODULE_REGISTRY["core.runtime_closure_audit"] == "audit_layer_read_only"
    assert SIDE_PATH_MODULE_REGISTRY["core.projection_surface_bridge"] == "outward_projection_bridge"


def test_boundary_snapshot_exposes_mainline_and_side_paths():
    boundary = get_minimal_runtime_mainline_boundary()
    assert boundary["minimal_runtime_mainline"] == list(MINIMAL_RUNTIME_MAINLINE_MODULES)
    assert boundary["side_path_modules"]["core.e2e_orchestrator"] == "side_path_facade"
