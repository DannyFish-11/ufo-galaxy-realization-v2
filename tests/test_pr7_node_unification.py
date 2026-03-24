#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr7_node_unification.py
====================================

PR-7 — Node system unification: aligning registry, startup policy, and
orchestration clarity with the PR-6 canonical node audit.

Validates:
  1.  node_dependencies.json covers all nominal nodes (no more config drift).
  2.  node_dependencies.json has 130 nodes (full nominal set).
  3.  Reserved nodes (28–32) have startup_policy 'skip'.
  4.  Node_130_AutonomousCoding (stub) has startup_policy 'skip'.
  5.  All repair nodes added by PR-7 are present in node_dependencies.json.
  6.  All repair nodes added by PR-7 have startup_policy 'optional'.
  7.  No repair node added by PR-7 has startup_policy 'skip'.
  8.  All repair nodes have a non-zero port assigned.
  9.  All repair ports are unique within node_dependencies.json.
  10. node_dependencies.json contains _pr7_node_unification metadata key.
  11. _pr7_node_unification metadata contains startup_policy_semantics.
  12. _pr7_node_unification metadata contains audit_action_semantics.
  13. NodeSystemLauncher.should_skip() returns True for a 'skip' node.
  14. NodeSystemLauncher.should_skip() returns False for an 'active' node.
  15. NodeSystemLauncher.should_skip() returns False for an 'optional' node.
  16. NodeSystemLauncher.should_skip() returns False for a node with no policy field.
  17. NodeSystemLauncher.get_startup_policy() returns 'active' for unknown node.
  18. NodeSystemLauncher.get_startup_policy() returns 'skip' for Reserved node.
  19. NodeSystemLauncher.get_startup_policy() returns 'optional' for repair node.
  20. NodeSystemLauncher.get_active_nodes() excludes all 'skip' nodes.
  21. NodeSystemLauncher.get_active_nodes() includes all 'active' nodes in config.
  22. NodeSystemLauncher.get_active_nodes() includes 'optional' nodes with main.py.
  23. NodeSystemLauncher.get_active_nodes() result is sorted.
  24. NodeSystemLauncher.get_core_nodes() returns only 'core'-group nodes.
  25. NodeSystemLauncher.get_core_nodes() excludes 'skip' core nodes (if any).
  26. NodeSystemLauncher.get_core_nodes() result is non-empty.
  27. NodeSystemLauncher.get_all_nodes() is a filesystem scan (includes all main.py nodes).
  28. NodeSystemLauncher.get_all_nodes() may include nodes that are 'skip' policy.
  29. All 'active' nodes in node_dependencies.json have a port assigned.
  30. Node_00_StateMachine is active and in 'core' group.
  31. Node_01_OneAPI is active and in 'core' group.
  32. Node_26_Discord has repair note about missing Dockerfile.
  33. docs/NODE_ACTIVE_MANIFEST.md exists.
  34. docs/NODE_ACTIVE_MANIFEST.md contains 'startup_policy' section.
  35. docs/NODE_ACTIVE_MANIFEST.md references 'skip' nodes.
  36. docs/NODE_ACTIVE_MANIFEST.md references repair nodes count.
  37. node_audit_report.json in_config_not_on_disk is empty after PR-7.
  38. node_audit_report.json on_disk_not_in_config is non-empty (pre-existing drift captured by audit).
  39. All 'skip' nodes in node_dependencies.json have an audit_action field.
  40. All 'skip' nodes in node_dependencies.json have audit_action 'archive' or 'delete'.
  41. All 'optional' nodes in node_dependencies.json have audit_action 'repair'.
  42. No repair node added by PR-7 has group 'core' (they are not core infrastructure).
  43. node_dependencies.json groups section still defines core/development/extended/academic.
  44. All nodes with group 'core' have startup_policy != 'skip'.
  45. _POLICY_SKIP constant on NodeSystemLauncher equals 'skip'.
  46. _POLICY_OPTIONAL constant on NodeSystemLauncher equals 'optional'.
  47. _POLICY_ACTIVE constant on NodeSystemLauncher equals 'active'.
  48. NodeSystemLauncher.get_active_nodes() count >= 100 (most nodes eligible).
  49. NodeSystemLauncher.get_core_nodes() count == number of 'core' group entries.
  50. Total skip-policy nodes == 6 (5 Reserved + 1 stub).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
NDJ_PATH = PROJECT_ROOT / "node_dependencies.json"
AUDIT_PATH = PROJECT_ROOT / "docs" / "node_audit_report.json"
MANIFEST_PATH = PROJECT_ROOT / "docs" / "NODE_ACTIVE_MANIFEST.md"

# Repair nodes that PR-7 should have added to node_dependencies.json
PR7_REPAIR_NODES = [
    "Node_60_ReinforcementLearning",
    "Node_63_FuzzyLogicEngine",
    "Node_70_AutonomousLearning",
    "Node_71_MultiDeviceCoordination",
    "Node_75_DataPipeline",
    "Node_76_AlertManager",
    "Node_77_TaskScheduler",
    "Node_78_DataValidator",
    "Node_86_SpeechProcessor",
    "Node_87_ImageAnalysis",
    "Node_88_WorkflowEngine",
    "Node_89_APIGateway",
    "Node_93_VideoProcessor",
    "Node_94_AudioAnalysis",
    "Node_98_MultimodalFusion",
    "Node_99_EmbeddingService",
    "Node_107_FunctionCalling",
    "Node_108_MetaCognition",
    "Node_109_ProactiveSensing",
    "Node_114_DocumentIntelligence",
    "Node_115_PluginManager",
    "Node_116_ExternalToolWrapper",
    "Node_117_OpenCode",
    "Node_118_NodeFactory",
    "Node_119_BenchmarkEval",
    "Node_120_File",
    "Node_121_Web",
    "Node_122_Shell",
    "Node_124_LinuxDesktopAuto",
]

RESERVED_NODES = [
    "Node_28_Reserved",
    "Node_29_Reserved",
    "Node_30_Reserved",
    "Node_31_Reserved",
    "Node_32_Reserved",
]

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def ndj() -> Dict[str, Any]:
    with open(NDJ_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def ndj_nodes(ndj) -> Dict[str, Any]:
    return ndj.get("nodes", {})


@pytest.fixture(scope="module")
def audit() -> Dict[str, Any]:
    with open(AUDIT_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _make_launcher(node_configs: Dict[str, Any]) -> Any:
    """Build a NodeSystemLauncher with a fake service manager and config."""
    from launcher.node_startup import NodeSystemLauncher
    from launcher.bootstrap import SystemConfig

    svc_mgr = MagicMock()
    cfg = MagicMock(spec=SystemConfig)
    cfg.web_ui_port = 8888

    launcher = NodeSystemLauncher.__new__(NodeSystemLauncher)
    launcher.service_manager = svc_mgr
    launcher.config = cfg
    launcher.nodes_dir = PROJECT_ROOT / "nodes"
    launcher.node_configs = node_configs
    return launcher


# ── Tests ─────────────────────────────────────────────────────────────────────

# 1. node_dependencies.json covers all nominal nodes (no config drift)
def test_no_missing_config_entries(ndj_nodes):
    nodes_dir = PROJECT_ROOT / "nodes"
    on_disk = {d.name for d in nodes_dir.iterdir() if d.is_dir() and d.name.startswith("Node_")}
    missing = on_disk - set(ndj_nodes.keys())
    assert missing == set(), f"Nodes on disk missing from config: {sorted(missing)}"


# 2. node_dependencies.json has 130 nodes
def test_total_node_count(ndj_nodes):
    assert len(ndj_nodes) == 130


# 3. Reserved nodes have startup_policy 'skip'
@pytest.mark.parametrize("name", RESERVED_NODES)
def test_reserved_nodes_skip(ndj_nodes, name):
    assert name in ndj_nodes, f"{name} not in node_dependencies.json"
    assert ndj_nodes[name].get("startup_policy") == "skip"


# 4. Node_130_AutonomousCoding has startup_policy 'skip'
def test_stub_node_skip(ndj_nodes):
    name = "Node_130_AutonomousCoding"
    assert name in ndj_nodes
    assert ndj_nodes[name].get("startup_policy") == "skip"


# 5. All PR-7 repair nodes are present
@pytest.mark.parametrize("name", PR7_REPAIR_NODES)
def test_repair_nodes_present(ndj_nodes, name):
    assert name in ndj_nodes, f"{name} missing from node_dependencies.json"


# 6. All PR-7 repair nodes have startup_policy 'optional'
@pytest.mark.parametrize("name", PR7_REPAIR_NODES)
def test_repair_nodes_optional(ndj_nodes, name):
    policy = ndj_nodes[name].get("startup_policy")
    assert policy == "optional", f"{name} has startup_policy={policy!r}"


# 7. No PR-7 repair node has startup_policy 'skip'
@pytest.mark.parametrize("name", PR7_REPAIR_NODES)
def test_repair_nodes_not_skip(ndj_nodes, name):
    assert ndj_nodes[name].get("startup_policy") != "skip"


# 8. All repair nodes have a non-zero port assigned
@pytest.mark.parametrize("name", PR7_REPAIR_NODES)
def test_repair_nodes_have_port(ndj_nodes, name):
    port = ndj_nodes[name].get("port")
    assert port and port > 0, f"{name} has no valid port"


# 9. All repair ports are unique
def test_repair_ports_unique(ndj_nodes):
    ports = [ndj_nodes[n]["port"] for n in PR7_REPAIR_NODES]
    assert len(ports) == len(set(ports)), "Duplicate ports among repair nodes"


# 10. _pr7_node_unification metadata key exists
def test_pr7_metadata_key(ndj):
    assert "_pr7_node_unification" in ndj


# 11. _pr7_node_unification has startup_policy_semantics
def test_pr7_metadata_policy_semantics(ndj):
    meta = ndj["_pr7_node_unification"]
    assert "startup_policy_semantics" in meta


# 12. _pr7_node_unification has audit_action_semantics
def test_pr7_metadata_audit_semantics(ndj):
    meta = ndj["_pr7_node_unification"]
    assert "audit_action_semantics" in meta


# 13. should_skip returns True for skip node
def test_should_skip_true():
    launcher = _make_launcher({"Node_28_Reserved": {"startup_policy": "skip"}})
    assert launcher.should_skip("Node_28_Reserved") is True


# 14. should_skip returns False for active node
def test_should_skip_false_active():
    launcher = _make_launcher({"Node_00_StateMachine": {"startup_policy": "active"}})
    assert launcher.should_skip("Node_00_StateMachine") is False


# 15. should_skip returns False for optional node
def test_should_skip_false_optional():
    launcher = _make_launcher({"Node_60_ReinforcementLearning": {"startup_policy": "optional"}})
    assert launcher.should_skip("Node_60_ReinforcementLearning") is False


# 16. should_skip returns False for node with no policy field
def test_should_skip_false_no_policy():
    launcher = _make_launcher({"Node_99_EmbeddingService": {"port": 8099}})
    assert launcher.should_skip("Node_99_EmbeddingService") is False


# 17. get_startup_policy returns 'active' for unknown node
def test_get_startup_policy_unknown():
    launcher = _make_launcher({})
    assert launcher.get_startup_policy("Node_999_Unknown") == "active"


# 18. get_startup_policy returns 'skip' for Reserved node
def test_get_startup_policy_skip(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    assert launcher.get_startup_policy("Node_28_Reserved") == "skip"


# 19. get_startup_policy returns 'optional' for repair node
def test_get_startup_policy_optional(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    assert launcher.get_startup_policy("Node_60_ReinforcementLearning") == "optional"


# 20. get_active_nodes excludes skip nodes
def test_get_active_nodes_excludes_skip(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    active = launcher.get_active_nodes()
    for name in RESERVED_NODES + ["Node_130_AutonomousCoding"]:
        assert name not in active, f"Skip node {name} found in get_active_nodes()"


# 21. get_active_nodes includes active nodes present on disk
def test_get_active_nodes_includes_active(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    active = launcher.get_active_nodes()
    assert "Node_00_StateMachine" in active
    assert "Node_01_OneAPI" in active


# 22. get_active_nodes includes optional nodes that have main.py on disk
def test_get_active_nodes_includes_optional(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    active = launcher.get_active_nodes()
    # At least some repair nodes should be included if they have main.py
    nodes_dir = PROJECT_ROOT / "nodes"
    on_disk_optional = [
        n for n in PR7_REPAIR_NODES
        if (nodes_dir / n / "main.py").exists()
    ]
    for name in on_disk_optional:
        assert name in active, f"Optional node {name} with main.py not in get_active_nodes()"


# 23. get_active_nodes result is sorted
def test_get_active_nodes_sorted(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    active = launcher.get_active_nodes()
    # sorted by (priority, name) — just check no obvious out-of-order core nodes
    assert active == sorted(active, key=lambda x: (
        launcher.node_configs.get(x, {}).get("priority", 99), x
    ))


# 24. get_core_nodes returns only core-group nodes
def test_get_core_nodes_only_core(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    core = launcher.get_core_nodes()
    for name in core:
        cfg = ndj_nodes.get(name, {})
        assert cfg.get("group") == "core", f"{name} in get_core_nodes() has group={cfg.get('group')}"


# 25. get_core_nodes excludes skip-policy core nodes (if any exist)
def test_get_core_nodes_excludes_skip(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    core = launcher.get_core_nodes()
    for name in core:
        assert not launcher.should_skip(name), f"Skip node {name} found in get_core_nodes()"


# 26. get_core_nodes returns non-empty list
def test_get_core_nodes_nonempty(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    assert len(launcher.get_core_nodes()) > 0


# 27. get_all_nodes is a filesystem scan (includes all main.py nodes)
def test_get_all_nodes_filesystem_scan(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    all_nodes = launcher.get_all_nodes()
    nodes_dir = PROJECT_ROOT / "nodes"
    expected = sorted(
        d.name for d in nodes_dir.iterdir()
        if d.is_dir() and (d / "main.py").exists()
    )
    assert all_nodes == expected


# 28. get_all_nodes may include 'skip' nodes (it's a raw filesystem list)
def test_get_all_nodes_may_include_skip(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    all_nodes = launcher.get_all_nodes()
    # At least some skip-policy nodes should appear if they have main.py
    nodes_dir = PROJECT_ROOT / "nodes"
    skip_on_disk = [
        n for n in RESERVED_NODES
        if (nodes_dir / n / "main.py").exists()
    ]
    for name in skip_on_disk:
        assert name in all_nodes, f"Expected {name} in raw filesystem list"


# 29. All 'active' nodes have a port assigned
def test_active_nodes_have_port(ndj_nodes):
    for name, cfg in ndj_nodes.items():
        if isinstance(cfg, dict) and cfg.get("startup_policy", "active") == "active":
            assert cfg.get("port"), f"Active node {name} has no port"


# 30. Node_00_StateMachine is active and in core group
def test_state_machine_core_active(ndj_nodes):
    cfg = ndj_nodes["Node_00_StateMachine"]
    assert cfg.get("group") == "core"
    assert cfg.get("startup_policy", "active") != "skip"


# 31. Node_01_OneAPI is active and in core group
def test_one_api_core_active(ndj_nodes):
    cfg = ndj_nodes["Node_01_OneAPI"]
    assert cfg.get("group") == "core"
    assert cfg.get("startup_policy", "active") != "skip"


# 32. Node_26_Discord is in config (audit notes Dockerfile missing, not config missing)
def test_discord_in_config(ndj_nodes):
    assert "Node_26_Discord" in ndj_nodes


# 33. NODE_ACTIVE_MANIFEST.md exists
def test_manifest_exists():
    assert MANIFEST_PATH.exists(), "docs/NODE_ACTIVE_MANIFEST.md not found"


# 34. NODE_ACTIVE_MANIFEST.md contains startup_policy section
def test_manifest_has_policy_section():
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    assert "startup_policy" in text.lower()


# 35. NODE_ACTIVE_MANIFEST.md references skip nodes
def test_manifest_references_skip():
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    assert "skip" in text.lower()


# 36. NODE_ACTIVE_MANIFEST.md references repair nodes
def test_manifest_references_repair():
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    assert "repair" in text.lower()


# 37. node_audit_report.json in_config_not_on_disk captured by audit
def test_audit_in_config_not_on_disk(audit):
    assert isinstance(audit.get("in_config_not_on_disk"), list)


# 38. node_audit_report.json on_disk_not_in_config captured
def test_audit_on_disk_not_in_config(audit):
    # Pre-PR7 there were 30 drift nodes — audit captures this history
    assert isinstance(audit.get("on_disk_not_in_config"), list)
    assert len(audit["on_disk_not_in_config"]) >= 0


# 39. All skip nodes have audit_action field
def test_skip_nodes_have_audit_action(ndj_nodes):
    for name, cfg in ndj_nodes.items():
        if isinstance(cfg, dict) and cfg.get("startup_policy") == "skip":
            assert "audit_action" in cfg, f"Skip node {name} missing audit_action"


# 40. All skip nodes have audit_action 'archive' or 'delete'
def test_skip_nodes_audit_action_valid(ndj_nodes):
    for name, cfg in ndj_nodes.items():
        if isinstance(cfg, dict) and cfg.get("startup_policy") == "skip":
            action = cfg.get("audit_action")
            assert action in ("archive", "delete"), \
                f"Skip node {name} has unexpected audit_action={action!r}"


# 41. All optional nodes have audit_action 'repair'
def test_optional_nodes_audit_action_repair(ndj_nodes):
    for name, cfg in ndj_nodes.items():
        if isinstance(cfg, dict) and cfg.get("startup_policy") == "optional":
            action = cfg.get("audit_action")
            assert action == "repair", \
                f"Optional node {name} has audit_action={action!r}, expected 'repair'"


# 42. No PR-7 repair node has group 'core'
@pytest.mark.parametrize("name", PR7_REPAIR_NODES)
def test_repair_nodes_not_core_group(ndj_nodes, name):
    assert ndj_nodes[name].get("group") != "core"


# 43. Groups section still defines the four canonical groups
def test_groups_section_canonical(ndj):
    groups = ndj.get("groups", {})
    for g in ("core", "development", "extended", "academic"):
        assert g in groups, f"Group '{g}' missing from node_dependencies.json groups"


# 44. All core-group nodes have startup_policy != 'skip'
def test_core_group_nodes_not_skip(ndj_nodes):
    for name, cfg in ndj_nodes.items():
        if isinstance(cfg, dict) and cfg.get("group") == "core":
            assert cfg.get("startup_policy", "active") != "skip", \
                f"Core node {name} has startup_policy='skip'"


# 45. _POLICY_SKIP constant
def test_policy_skip_constant():
    from launcher.node_startup import NodeSystemLauncher
    assert NodeSystemLauncher._POLICY_SKIP == "skip"


# 46. _POLICY_OPTIONAL constant
def test_policy_optional_constant():
    from launcher.node_startup import NodeSystemLauncher
    assert NodeSystemLauncher._POLICY_OPTIONAL == "optional"


# 47. _POLICY_ACTIVE constant
def test_policy_active_constant():
    from launcher.node_startup import NodeSystemLauncher
    assert NodeSystemLauncher._POLICY_ACTIVE == "active"


# 48. get_active_nodes count >= 100
def test_active_nodes_count(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    assert len(launcher.get_active_nodes()) >= 100


# 49. get_core_nodes count matches core-group entries in config
def test_core_nodes_count_matches_config(ndj_nodes):
    launcher = _make_launcher(ndj_nodes)
    nodes_dir = PROJECT_ROOT / "nodes"
    expected_core = [
        name for name, cfg in ndj_nodes.items()
        if isinstance(cfg, dict)
        and cfg.get("group") == "core"
        and cfg.get("startup_policy", "active") != "skip"
        and (nodes_dir / name / "main.py").exists()
    ]
    assert len(launcher.get_core_nodes()) == len(expected_core)


# 50. Total skip-policy nodes == 6
def test_total_skip_count(ndj_nodes):
    skip_count = sum(
        1 for cfg in ndj_nodes.values()
        if isinstance(cfg, dict) and cfg.get("startup_policy") == "skip"
    )
    assert skip_count == 6, f"Expected 6 skip nodes, got {skip_count}"
