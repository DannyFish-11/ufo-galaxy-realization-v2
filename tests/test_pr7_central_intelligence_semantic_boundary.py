"""
tests/test_pr7_central_intelligence_semantic_boundary.py
==========================================================
PR-7: Central Intelligence semantic boundary regression tests.

Locks the following invariants:

1. Module sentinels — authority and PR7 sentinel are correctly formatted.
2. Policy sentinels — all six policy strings are non-empty and contain
   expected keywords.
3. CILayerRole enum — all four expected roles are present.
4. CILayerSurface dataclass — structure and to_dict().
5. CILayerBoundaryReport dataclass — structure and to_dict().
6. CI layer registry — non-empty, correct surface types.
7. classify_ci_surface() — found and not-found cases.
8. get_surfaces_by_ci_role() — filters correctly for each role.
9. build_ci_layer_boundary_report() — aggregate builder correctness.
10. Central-intelligence main layer has exactly 2 surfaces
    (DesktopPresenceRuntime + OpenClawd).
11. Expert capability sub-layers — AgentKernel / ExecutionPlanner /
    TeamManager / AgentTeam are classified correctly and carry the
    may_not_claim_independent_authority constraint.
12. Sub-domain coordinators — UnifiedOrchestrationSpine / DeviceOrchestrator /
    SwarmCoordinator are NOT classified as central intelligence.
13. Facade/compat/helper layers — e2e_orchestrator / RepoCoordinator /
    SystemOrchestrator are NOT classified as central intelligence.
14. canonical_execution_chain.SIDE_PATH_MODULE_REGISTRY contains PR-7 entries
    for AgentKernel, ExecutionPlanner, AgentTeam, SystemOrchestrator with
    their correct non-central-authority roles.
15. PR-7 entries in SIDE_PATH_MODULE_REGISTRY are NOT in
    MINIMAL_RUNTIME_MAINLINE_MODULES.
16. Android first-class runtime host policy is present and mentions
    DeviceRouter and Android.
"""

from __future__ import annotations

import pytest

from core.central_intelligence_layer import (
    ANDROID_FIRST_CLASS_RUNTIME_HOST_POLICY,
    CENTRAL_INTELLIGENCE_LAYER_AUTHORITY,
    CENTRAL_INTELLIGENCE_LAYER_PR7_SENTINEL,
    CI_LAYER_SURFACE_REGISTRY,
    KERNEL_IS_NOT_SECOND_AUTHORITY_POLICY,
    OPENCLAWD_IS_CENTRAL_INTELLIGENCE_CORE_POLICY,
    ORCHESTRATOR_COORDINATOR_SPINE_SCOPE_POLICY,
    PLANNER_IS_NOT_SECOND_AUTHORITY_POLICY,
    TEAM_IS_NOT_SECOND_AUTHORITY_POLICY,
    CILayerBoundaryReport,
    CILayerRole,
    CILayerSurface,
    build_ci_layer_boundary_report,
    classify_ci_surface,
    get_ci_layer_registry,
    get_surfaces_by_ci_role,
)


# ---------------------------------------------------------------------------
# 1. Module sentinels
# ---------------------------------------------------------------------------


def test_authority_sentinel_format():
    assert CENTRAL_INTELLIGENCE_LAYER_AUTHORITY.startswith(
        "CENTRAL_INTELLIGENCE_LAYER_AUTHORITY::"
    )
    assert "core.central_intelligence_layer" in CENTRAL_INTELLIGENCE_LAYER_AUTHORITY
    assert "central-intelligence" in CENTRAL_INTELLIGENCE_LAYER_AUTHORITY.lower()


def test_pr7_sentinel_format():
    assert CENTRAL_INTELLIGENCE_LAYER_PR7_SENTINEL.startswith(
        "CENTRAL_INTELLIGENCE_LAYER_PR7_SENTINEL::"
    )
    assert "PR7" in CENTRAL_INTELLIGENCE_LAYER_PR7_SENTINEL
    assert "central-intelligence-semantic-boundary-v1" in CENTRAL_INTELLIGENCE_LAYER_PR7_SENTINEL
    assert "core.central_intelligence_layer" in CENTRAL_INTELLIGENCE_LAYER_PR7_SENTINEL


# ---------------------------------------------------------------------------
# 2. Policy sentinels
# ---------------------------------------------------------------------------


def test_policy_sentinels_are_non_empty_strings():
    for sentinel in [
        OPENCLAWD_IS_CENTRAL_INTELLIGENCE_CORE_POLICY,
        KERNEL_IS_NOT_SECOND_AUTHORITY_POLICY,
        PLANNER_IS_NOT_SECOND_AUTHORITY_POLICY,
        TEAM_IS_NOT_SECOND_AUTHORITY_POLICY,
        ORCHESTRATOR_COORDINATOR_SPINE_SCOPE_POLICY,
        ANDROID_FIRST_CLASS_RUNTIME_HOST_POLICY,
    ]:
        assert isinstance(sentinel, str) and len(sentinel) > 0


def test_openclawd_policy_mentions_central_intelligence():
    lower = OPENCLAWD_IS_CENTRAL_INTELLIGENCE_CORE_POLICY.lower()
    assert "openclawd" in lower
    assert "central intelligence" in lower


def test_kernel_policy_mentions_not_second_authority():
    lower = KERNEL_IS_NOT_SECOND_AUTHORITY_POLICY.lower()
    assert "agentkernel" in lower
    assert "advisory" in lower
    assert "openclawd" in lower


def test_planner_policy_mentions_not_second_authority():
    lower = PLANNER_IS_NOT_SECOND_AUTHORITY_POLICY.lower()
    assert "executionplanner" in lower
    assert "agentkernel" in lower


def test_team_policy_mentions_not_second_authority():
    lower = TEAM_IS_NOT_SECOND_AUTHORITY_POLICY.lower()
    assert "teammanager" in lower
    assert "executionplanner" in lower


def test_orchestrator_policy_mentions_scope_constraint():
    lower = ORCHESTRATOR_COORDINATOR_SPINE_SCOPE_POLICY.lower()
    assert "unifiedorchestrationspine" in lower
    assert "per-request" in lower


def test_android_policy_mentions_first_class():
    lower = ANDROID_FIRST_CLASS_RUNTIME_HOST_POLICY.lower()
    assert "android" in lower
    assert "first-class" in lower
    assert "devicerouter" in lower


# ---------------------------------------------------------------------------
# 3. CILayerRole enum
# ---------------------------------------------------------------------------


def test_ci_layer_role_enum_has_all_four_roles():
    expected = {
        "central_intelligence_main_layer",
        "expert_capability_sub_layer",
        "sub_domain_coordinator",
        "facade_compat_helper",
    }
    actual = {role.value for role in CILayerRole}
    assert expected == actual


# ---------------------------------------------------------------------------
# 4. CILayerSurface dataclass
# ---------------------------------------------------------------------------


def test_ci_layer_surface_to_dict_has_required_keys():
    surface = CILayerSurface(
        surface_id="test_surface",
        module_path="test.module.TestClass",
        surface_name="Test Surface",
        ci_role=CILayerRole.facade_compat_helper,
        is_central_intelligence=False,
        may_not_claim_independent_authority=True,
        notes="test notes",
    )
    d = surface.to_dict()
    for key in [
        "surface_id",
        "module_path",
        "surface_name",
        "ci_role",
        "is_central_intelligence",
        "may_not_claim_independent_authority",
        "notes",
    ]:
        assert key in d


def test_ci_layer_surface_is_central_intelligence_false_for_non_ci():
    surface = CILayerSurface(
        surface_id="x",
        module_path="x.y",
        surface_name="X",
        ci_role=CILayerRole.expert_capability_sub_layer,
        is_central_intelligence=False,
        may_not_claim_independent_authority=True,
        notes="",
    )
    assert surface.is_central_intelligence is False


# ---------------------------------------------------------------------------
# 5. CILayerBoundaryReport dataclass
# ---------------------------------------------------------------------------


def test_ci_layer_boundary_report_to_dict_has_required_keys():
    report = CILayerBoundaryReport(
        total_surfaces=10,
        central_intelligence_count=2,
        expert_sub_layer_count=4,
        sub_domain_coordinator_count=2,
        facade_compat_helper_count=2,
        constrained_surfaces=["a", "b"],
    )
    d = report.to_dict()
    for key in [
        "total_surfaces",
        "central_intelligence_count",
        "expert_sub_layer_count",
        "sub_domain_coordinator_count",
        "facade_compat_helper_count",
        "constrained_surfaces",
        "generated_at",
    ]:
        assert key in d


# ---------------------------------------------------------------------------
# 6. CI layer registry
# ---------------------------------------------------------------------------


def test_ci_layer_registry_is_non_empty():
    registry = get_ci_layer_registry()
    assert len(registry) > 0


def test_ci_layer_registry_all_entries_are_ci_layer_surfaces():
    for surface in get_ci_layer_registry():
        assert isinstance(surface, CILayerSurface)


def test_ci_layer_registry_surface_ids_are_unique():
    registry = get_ci_layer_registry()
    ids = [s.surface_id for s in registry]
    assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# 7. classify_ci_surface()
# ---------------------------------------------------------------------------


def test_classify_ci_surface_returns_surface_for_known_id():
    surface = classify_ci_surface("openclawd")
    assert surface is not None
    assert surface.surface_id == "openclawd"


def test_classify_ci_surface_returns_none_for_unknown_id():
    assert classify_ci_surface("does_not_exist_xyz") is None


# ---------------------------------------------------------------------------
# 8. get_surfaces_by_ci_role()
# ---------------------------------------------------------------------------


def test_get_surfaces_by_ci_role_returns_only_matching_role():
    ci_surfaces = get_surfaces_by_ci_role(CILayerRole.central_intelligence_main_layer)
    for s in ci_surfaces:
        assert s.ci_role == CILayerRole.central_intelligence_main_layer


def test_get_surfaces_by_ci_role_expert_sub_layer_not_empty():
    expert_surfaces = get_surfaces_by_ci_role(CILayerRole.expert_capability_sub_layer)
    assert len(expert_surfaces) > 0


def test_get_surfaces_by_ci_role_facade_compat_not_empty():
    facades = get_surfaces_by_ci_role(CILayerRole.facade_compat_helper)
    assert len(facades) > 0


# ---------------------------------------------------------------------------
# 9. build_ci_layer_boundary_report()
# ---------------------------------------------------------------------------


def test_build_ci_layer_boundary_report_totals_match_registry():
    report = build_ci_layer_boundary_report()
    total = (
        report.central_intelligence_count
        + report.expert_sub_layer_count
        + report.sub_domain_coordinator_count
        + report.facade_compat_helper_count
    )
    assert total == report.total_surfaces
    assert report.total_surfaces == len(CI_LAYER_SURFACE_REGISTRY)


def test_build_ci_layer_boundary_report_constrained_surfaces_subset_of_ids():
    report = build_ci_layer_boundary_report()
    registry_ids = {s.surface_id for s in CI_LAYER_SURFACE_REGISTRY}
    for sid in report.constrained_surfaces:
        assert sid in registry_ids


def test_build_ci_layer_boundary_report_generated_at_is_recent():
    import time
    before = time.time()
    report = build_ci_layer_boundary_report()
    after = time.time()
    assert before <= report.generated_at <= after


# ---------------------------------------------------------------------------
# 10. Central intelligence main layer has exactly 2 surfaces
# ---------------------------------------------------------------------------


def test_central_intelligence_main_layer_has_exactly_two_surfaces():
    ci_surfaces = get_surfaces_by_ci_role(CILayerRole.central_intelligence_main_layer)
    assert len(ci_surfaces) == 2


def test_central_intelligence_main_layer_includes_openclawd():
    openclawd = classify_ci_surface("openclawd")
    assert openclawd is not None
    assert openclawd.ci_role == CILayerRole.central_intelligence_main_layer
    assert openclawd.is_central_intelligence is True
    assert openclawd.may_not_claim_independent_authority is False


def test_central_intelligence_main_layer_includes_desktop_presence_runtime():
    dpr = classify_ci_surface("desktop_presence_runtime")
    assert dpr is not None
    assert dpr.ci_role == CILayerRole.central_intelligence_main_layer
    assert dpr.is_central_intelligence is True
    assert dpr.may_not_claim_independent_authority is False


# ---------------------------------------------------------------------------
# 11. Expert capability sub-layers — AgentKernel / ExecutionPlanner / Team
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface_id", [
    "agent_kernel",
    "execution_planner",
    "team_manager",
    "agent_team",
])
def test_expert_capability_sub_layer_classification(surface_id):
    surface = classify_ci_surface(surface_id)
    assert surface is not None, f"{surface_id} not found in registry"
    assert surface.ci_role == CILayerRole.expert_capability_sub_layer
    assert surface.is_central_intelligence is False
    assert surface.may_not_claim_independent_authority is True


def test_agent_kernel_notes_mention_advisory():
    kernel = classify_ci_surface("agent_kernel")
    assert kernel is not None
    assert "advisory" in kernel.notes.lower()
    assert "openclawd" in kernel.notes.lower()


def test_execution_planner_notes_mention_agentkernel():
    planner = classify_ci_surface("execution_planner")
    assert planner is not None
    assert "agentkernel" in planner.notes.lower()


def test_team_manager_notes_mention_executionplanner():
    tm = classify_ci_surface("team_manager")
    assert tm is not None
    assert "executionplanner" in tm.notes.lower()


# ---------------------------------------------------------------------------
# 12. Sub-domain coordinators are NOT central intelligence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface_id", [
    "unified_orchestration_spine",
    "device_orchestrator",
    "swarm_coordinator",
])
def test_sub_domain_coordinator_is_not_central_intelligence(surface_id):
    surface = classify_ci_surface(surface_id)
    assert surface is not None, f"{surface_id} not found in registry"
    assert surface.ci_role == CILayerRole.sub_domain_coordinator
    assert surface.is_central_intelligence is False
    assert surface.may_not_claim_independent_authority is True


def test_unified_orchestration_spine_notes_mention_not_per_request():
    spine = classify_ci_surface("unified_orchestration_spine")
    assert spine is not None
    lower = spine.notes.lower()
    assert "per-request" in lower or "per request" in lower


# ---------------------------------------------------------------------------
# 13. Facade/compat/helper layers are NOT central intelligence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("surface_id", [
    "e2e_orchestrator",
    "repo_coordinator",
    "system_orchestrator",
])
def test_facade_compat_helper_is_not_central_intelligence(surface_id):
    surface = classify_ci_surface(surface_id)
    assert surface is not None, f"{surface_id} not found in registry"
    assert surface.ci_role == CILayerRole.facade_compat_helper
    assert surface.is_central_intelligence is False
    assert surface.may_not_claim_independent_authority is True


def test_e2e_orchestrator_notes_mention_facade():
    e2e = classify_ci_surface("e2e_orchestrator")
    assert e2e is not None
    assert "facade" in e2e.notes.lower()


def test_system_orchestrator_notes_mention_startup():
    so = classify_ci_surface("system_orchestrator")
    assert so is not None
    lower = so.notes.lower()
    assert "startup" in lower


# ---------------------------------------------------------------------------
# 14. canonical_execution_chain SIDE_PATH_MODULE_REGISTRY contains PR-7 entries
# ---------------------------------------------------------------------------


def test_side_path_registry_contains_agent_kernel():
    from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
    assert "core.agent.kernel" in SIDE_PATH_MODULE_REGISTRY
    assert SIDE_PATH_MODULE_REGISTRY["core.agent.kernel"] == "embedded_cognition_sub_layer"


def test_side_path_registry_contains_execution_planner():
    from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
    assert "core.agent.execution_planner" in SIDE_PATH_MODULE_REGISTRY
    assert SIDE_PATH_MODULE_REGISTRY["core.agent.execution_planner"] == "execution_planning_helper"


def test_side_path_registry_contains_agent_team():
    from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
    assert "core.agent_team" in SIDE_PATH_MODULE_REGISTRY
    assert SIDE_PATH_MODULE_REGISTRY["core.agent_team"] == "expert_execution_sub_layer"


def test_side_path_registry_contains_system_orchestrator():
    from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
    assert "core.system_orchestrator" in SIDE_PATH_MODULE_REGISTRY
    assert SIDE_PATH_MODULE_REGISTRY["core.system_orchestrator"] == "startup_phase_helper"


# ---------------------------------------------------------------------------
# 15. PR-7 side-path entries are NOT in MINIMAL_RUNTIME_MAINLINE_MODULES
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_name", [
    "core.agent.kernel",
    "core.agent.execution_planner",
    "core.agent_team",
    "core.system_orchestrator",
    "core.unified_orchestration_spine",
    "core.e2e_orchestrator",
    "core.repo_coordinator",
    "core.device_orchestrator",
    "core.swarm_coordinator",
])
def test_pr7_side_path_entries_not_in_minimal_mainline(module_name):
    from core.canonical_execution_chain import MINIMAL_RUNTIME_MAINLINE_MODULES
    assert module_name not in MINIMAL_RUNTIME_MAINLINE_MODULES, (
        f"{module_name!r} must NOT be in MINIMAL_RUNTIME_MAINLINE_MODULES"
    )


# ---------------------------------------------------------------------------
# 16. Android first-class runtime host policy
# ---------------------------------------------------------------------------


def test_android_policy_is_non_empty_string():
    assert isinstance(ANDROID_FIRST_CLASS_RUNTIME_HOST_POLICY, str)
    assert len(ANDROID_FIRST_CLASS_RUNTIME_HOST_POLICY) > 0


def test_android_policy_mentions_device_router():
    assert "DeviceRouter" in ANDROID_FIRST_CLASS_RUNTIME_HOST_POLICY


def test_android_policy_mentions_android():
    assert "Android" in ANDROID_FIRST_CLASS_RUNTIME_HOST_POLICY


def test_android_policy_mentions_first_class():
    assert "first-class" in ANDROID_FIRST_CLASS_RUNTIME_HOST_POLICY
