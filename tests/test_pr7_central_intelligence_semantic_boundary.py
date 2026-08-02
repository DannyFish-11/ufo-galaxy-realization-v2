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

# ---------------------------------------------------------------------------
# 1. Module sentinels
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 2. Policy sentinels
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3. CILayerRole enum
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 4. CILayerSurface dataclass
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 5. CILayerBoundaryReport dataclass
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 6. CI layer registry
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 7. classify_ci_surface()
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 8. get_surfaces_by_ci_role()
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 9. build_ci_layer_boundary_report()
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 10. Central intelligence main layer has exactly 2 surfaces
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 11. Expert capability sub-layers — AgentKernel / ExecutionPlanner / Team
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 12. Sub-domain coordinators are NOT central intelligence
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 13. Facade/compat/helper layers are NOT central intelligence
# ---------------------------------------------------------------------------


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


@pytest.mark.parametrize(
    "module_name",
    [
        "core.agent.kernel",
        "core.agent.execution_planner",
        "core.agent_team",
        "core.system_orchestrator",
        "core.unified_orchestration_spine",
        "core.e2e_orchestrator",
        "core.repo_coordinator",
        "core.device_orchestrator",
        "core.swarm_coordinator",
    ],
)
def test_pr7_side_path_entries_not_in_minimal_mainline(module_name):
    from core.canonical_execution_chain import MINIMAL_RUNTIME_MAINLINE_MODULES

    assert (
        module_name not in MINIMAL_RUNTIME_MAINLINE_MODULES
    ), f"{module_name!r} must NOT be in MINIMAL_RUNTIME_MAINLINE_MODULES"


# ---------------------------------------------------------------------------
# 16. Android first-class runtime host policy
# ---------------------------------------------------------------------------


# 已删除依赖 core/central_intelligence_layer.py 的用例 —— 该模块是纯命名 / 语义边界
# 声明层（只产出标签，不做运行时判定），生产面零引用，已删除。
# 保留的用例测的是 core/canonical_execution_chain.py，仍在。
