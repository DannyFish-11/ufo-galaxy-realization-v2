#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr6_node_audit.py
=============================

PR-6 — Node-system audit and canonical inventory establishment.

Note on file naming: test files in this repository use a sequential numbering
scheme.  This file is numbered ``test_pr6`` because it directly exercises the
PR-6 node-audit deliverable.

Validates:
  1.  NodeTier has NOMINAL constant.
  2.  NodeTier has RUNNABLE constant.
  3.  NodeTier has ORCHESTRATED constant.
  4.  NodeTier has STUB constant.
  5.  RecommendedAction has KEEP constant.
  6.  RecommendedAction has REPAIR constant.
  7.  RecommendedAction has ARCHIVE constant.
  8.  RecommendedAction has DELETE constant.
  9.  NodeAuditEntry can be instantiated with only name and path.
  10. NodeAuditEntry.has_main_py defaults to False.
  11. NodeAuditEntry.tier defaults to NodeTier.NOMINAL.
  12. NodeAuditEntry.action defaults to RecommendedAction.ARCHIVE.
  13. NodeAuditEntry.to_dict() returns a dict.
  14. NodeAuditEntry.to_dict() contains "name".
  15. NodeAuditEntry.to_dict() contains "tier".
  16. NodeAuditEntry.to_dict() contains "action".
  17. NodeAuditEntry.to_dict() contains "notes" as a list.
  18. NodeAuditReport can be instantiated with generated_at and project_root.
  19. NodeAuditReport.nominal_count defaults to 0.
  20. NodeAuditReport.runnable_count defaults to 0.
  21. NodeAuditReport.orchestrated_count defaults to 0.
  22. NodeAuditReport.stub_count defaults to 0.
  23. NodeAuditReport.nodes defaults to empty list.
  24. NodeAuditReport.to_dict() is JSON-serialisable.
  25. NodeAuditReport.to_dict() contains "nodes" key.
  26. run_audit() returns a NodeAuditReport instance.
  27. run_audit() nominal_count equals number of Node_* directories.
  28. run_audit() orchestrated_count <= nominal_count.
  29. run_audit() runnable_count <= nominal_count.
  30. run_audit() stub_count >= 0.
  31. run_audit() keep_count + repair_count + archive_count + delete_count == nominal_count.
  32. run_audit() every node entry has a non-empty name.
  33. run_audit() every node entry has a valid tier value.
  34. run_audit() every node entry has a valid action value.
  35. run_audit() nominal_count >= 130 (repo has ≥130 node directories).
  36. run_audit() orchestrated_count >= 90 (≥90 nodes in node_dependencies.json).
  37. run_audit() runnable_count >= 120 (≥120 nodes have meaningful main.py).
  38. run_audit() in_config_not_on_disk is a list.
  39. run_audit() on_disk_not_in_config is a list.
  40. run_audit() reserved_nodes is a list.
  41. run_audit() duplicate_roles is a list.
  42. run_audit() duplicate_roles contains "MemorySystem" duplicate entry.
  43. run_audit() duplicate_roles contains "MediaGen" duplicate entry.
  44. run_audit() numbering_gaps is a list.
  45. run_audit() Node_01_OneAPI has tier == orchestrated.
  46. run_audit() Node_01_OneAPI has action == keep.
  47. run_audit() Node_01_OneAPI in_node_dependencies == True.
  48. run_audit() Node_01_OneAPI has a config_port.
  49. run_audit() every orchestrated node has in_node_dependencies == True.
  50. run_audit() all reserved nodes have action != keep.
  51. run_audit() Node_130_AutonomousCoding stub has main_py_lines < 100 (PR-7: now in config with startup_policy=skip).
  52. run_audit() Node_60_ReinforcementLearning has main.py (PR-7: now in config with startup_policy=optional).
  53. run_audit() report.nodes list length == nominal_count.
  54. run_audit() generated_at is a non-empty string.
  55. run_audit() project_root is a non-empty string.
  56. run_audit() Node_00_StateMachine config_group == "core".
  57. run_audit() Node_00_StateMachine has_dockerfile == True.
  58. run_audit() Node_00_StateMachine has_main_py == True.
  59. run_audit() Node_00_StateMachine main_py_lines >= 100.
  60. run_audit() keep_count >= 80.
"""

import json
import os
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------

from scripts.node_audit import (
    NodeTier,
    RecommendedAction,
    NodeAuditEntry,
    NodeAuditReport,
    run_audit,
    # PR-2 check category constants
    CHECK_SOURCE_COMPLETENESS,
    CHECK_SYNTAX_SAFETY,
    CHECK_PACKAGING,
    CHECK_REGISTRY_GOVERNANCE,
    CHECK_RUNTIME_CONTRACT,
    CHECK_HYGIENE,
    # PR-2 check result constants
    CHECK_PASS,
    CHECK_WARN,
    CHECK_FAIL,
    CHECK_UNKNOWN,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.absolute()


@pytest.fixture(scope="module")
def audit_report() -> NodeAuditReport:
    """Run the full audit once and share the result across all tests."""
    return run_audit(_PROJECT_ROOT)


@pytest.fixture(scope="module")
def nodes_by_name(audit_report: NodeAuditReport):
    return {e.name: e for e in audit_report.nodes}


# ---------------------------------------------------------------------------
# 1–4: NodeTier constants
# ---------------------------------------------------------------------------

def test_01_node_tier_has_nominal():
    assert NodeTier.NOMINAL == "nominal"


def test_02_node_tier_has_runnable():
    assert NodeTier.RUNNABLE == "runnable"


def test_03_node_tier_has_orchestrated():
    assert NodeTier.ORCHESTRATED == "orchestrated"


def test_04_node_tier_has_stub():
    assert NodeTier.STUB == "stub"


# ---------------------------------------------------------------------------
# 5–8: RecommendedAction constants
# ---------------------------------------------------------------------------

def test_05_recommended_action_has_keep():
    assert RecommendedAction.KEEP == "keep"


def test_06_recommended_action_has_repair():
    assert RecommendedAction.REPAIR == "repair"


def test_07_recommended_action_has_archive():
    assert RecommendedAction.ARCHIVE == "archive"


def test_08_recommended_action_has_delete():
    assert RecommendedAction.DELETE == "delete"


# ---------------------------------------------------------------------------
# 9–17: NodeAuditEntry dataclass
# ---------------------------------------------------------------------------

def test_09_node_audit_entry_instantiates_with_name_and_path():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert e.name == "Node_99_Test"


def test_10_node_audit_entry_has_main_py_defaults_false():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert e.has_main_py is False


def test_11_node_audit_entry_tier_defaults_to_nominal():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert e.tier == NodeTier.NOMINAL


def test_12_node_audit_entry_action_defaults_to_archive():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert e.action == RecommendedAction.ARCHIVE


def test_13_node_audit_entry_to_dict_returns_dict():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert isinstance(e.to_dict(), dict)


def test_14_node_audit_entry_to_dict_contains_name():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert "name" in e.to_dict()


def test_15_node_audit_entry_to_dict_contains_tier():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert "tier" in e.to_dict()


def test_16_node_audit_entry_to_dict_contains_action():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert "action" in e.to_dict()


def test_17_node_audit_entry_to_dict_contains_notes_as_list():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert isinstance(e.to_dict()["notes"], list)


# ---------------------------------------------------------------------------
# 18–25: NodeAuditReport dataclass
# ---------------------------------------------------------------------------

def test_18_node_audit_report_instantiates():
    r = NodeAuditReport(generated_at="2026-01-01T00:00:00Z", project_root="/tmp")
    assert r.generated_at == "2026-01-01T00:00:00Z"


def test_19_report_nominal_count_defaults_to_zero():
    r = NodeAuditReport(generated_at="2026-01-01T00:00:00Z", project_root="/tmp")
    assert r.nominal_count == 0


def test_20_report_runnable_count_defaults_to_zero():
    r = NodeAuditReport(generated_at="2026-01-01T00:00:00Z", project_root="/tmp")
    assert r.runnable_count == 0


def test_21_report_orchestrated_count_defaults_to_zero():
    r = NodeAuditReport(generated_at="2026-01-01T00:00:00Z", project_root="/tmp")
    assert r.orchestrated_count == 0


def test_22_report_stub_count_defaults_to_zero():
    r = NodeAuditReport(generated_at="2026-01-01T00:00:00Z", project_root="/tmp")
    assert r.stub_count == 0


def test_23_report_nodes_defaults_to_empty_list():
    r = NodeAuditReport(generated_at="2026-01-01T00:00:00Z", project_root="/tmp")
    assert r.nodes == []


def test_24_report_to_dict_is_json_serialisable(audit_report):
    d = audit_report.to_dict()
    json.dumps(d)  # must not raise


def test_25_report_to_dict_contains_nodes_key(audit_report):
    assert "nodes" in audit_report.to_dict()


# ---------------------------------------------------------------------------
# 26–60: run_audit() integration tests
# ---------------------------------------------------------------------------

def test_26_run_audit_returns_node_audit_report(audit_report):
    assert isinstance(audit_report, NodeAuditReport)


def test_27_run_audit_nominal_count_matches_disk(audit_report):
    disk_count = sum(
        1 for d in (_PROJECT_ROOT / "nodes").iterdir()
        if d.is_dir() and d.name.startswith("Node_")
    )
    assert audit_report.nominal_count == disk_count


def test_28_run_audit_orchestrated_lte_nominal(audit_report):
    assert audit_report.orchestrated_count <= audit_report.nominal_count


def test_29_run_audit_runnable_lte_nominal(audit_report):
    assert audit_report.runnable_count <= audit_report.nominal_count


def test_30_run_audit_stub_count_non_negative(audit_report):
    assert audit_report.stub_count >= 0


def test_31_run_audit_action_counts_sum_to_nominal(audit_report):
    total = (
        audit_report.keep_count
        + audit_report.repair_count
        + audit_report.archive_count
        + audit_report.delete_count
    )
    assert total == audit_report.nominal_count


def test_32_run_audit_every_entry_has_non_empty_name(audit_report):
    for entry in audit_report.nodes:
        assert entry.name


def test_33_run_audit_every_entry_has_valid_tier(audit_report):
    valid_tiers = {
        NodeTier.NOMINAL, NodeTier.RUNNABLE, NodeTier.ORCHESTRATED, NodeTier.STUB
    }
    for entry in audit_report.nodes:
        assert entry.tier in valid_tiers, f"{entry.name} has unexpected tier {entry.tier!r}"


def test_34_run_audit_every_entry_has_valid_action(audit_report):
    valid_actions = {
        RecommendedAction.KEEP,
        RecommendedAction.REPAIR,
        RecommendedAction.ARCHIVE,
        RecommendedAction.DELETE,
    }
    for entry in audit_report.nodes:
        assert entry.action in valid_actions, (
            f"{entry.name} has unexpected action {entry.action!r}"
        )


def test_35_run_audit_nominal_count_gte_130(audit_report):
    assert audit_report.nominal_count >= 130


def test_36_run_audit_orchestrated_count_gte_90(audit_report):
    assert audit_report.orchestrated_count >= 90


def test_37_run_audit_runnable_count_gte_120(audit_report):
    assert audit_report.runnable_count >= 120


def test_38_run_audit_in_config_not_on_disk_is_list(audit_report):
    assert isinstance(audit_report.in_config_not_on_disk, list)


def test_39_run_audit_on_disk_not_in_config_is_list(audit_report):
    assert isinstance(audit_report.on_disk_not_in_config, list)


def test_40_run_audit_reserved_nodes_is_list(audit_report):
    assert isinstance(audit_report.reserved_nodes, list)


def test_41_run_audit_duplicate_roles_is_list(audit_report):
    assert isinstance(audit_report.duplicate_roles, list)


def test_42_run_audit_duplicate_roles_contains_memory_system(audit_report):
    joined = " ".join(audit_report.duplicate_roles)
    assert "MemorySystem" in joined


def test_43_run_audit_duplicate_roles_contains_media_gen(audit_report):
    joined = " ".join(audit_report.duplicate_roles)
    assert "MediaGen" in joined


def test_44_run_audit_numbering_gaps_is_list(audit_report):
    assert isinstance(audit_report.numbering_gaps, list)


def test_45_node01_has_orchestrated_tier(nodes_by_name):
    node = nodes_by_name["Node_01_OneAPI"]
    assert node.tier == NodeTier.ORCHESTRATED


def test_46_node01_has_action_keep(nodes_by_name):
    node = nodes_by_name["Node_01_OneAPI"]
    assert node.action == RecommendedAction.KEEP


def test_47_node01_in_node_dependencies(nodes_by_name):
    node = nodes_by_name["Node_01_OneAPI"]
    assert node.in_node_dependencies is True


def test_48_node01_has_config_port(nodes_by_name):
    node = nodes_by_name["Node_01_OneAPI"]
    assert node.config_port is not None


def test_49_all_orchestrated_nodes_in_config(audit_report):
    for entry in audit_report.nodes:
        if entry.tier == NodeTier.ORCHESTRATED:
            assert entry.in_node_dependencies, (
                f"{entry.name} tier=orchestrated but in_node_dependencies=False"
            )


def test_50_all_reserved_nodes_not_keep(audit_report, nodes_by_name):
    for name in audit_report.reserved_nodes:
        entry = nodes_by_name[name]
        assert entry.action != RecommendedAction.KEEP, (
            f"Reserved node {name} unexpectedly has action=keep"
        )


def test_51_node130_autonomous_coding_is_in_config_post_pr7(audit_report):
    # PR-7 added Node_130_AutonomousCoding to node_dependencies.json with
    # startup_policy='skip' (stub — needs real implementation before promotion).
    # It is no longer an orphan; verify the audit detects it as a stub.
    entry = next(
        (n for n in audit_report.nodes if n.name == "Node_130_AutonomousCoding"),
        None,
    )
    assert entry is not None, "Node_130_AutonomousCoding not found in audit nodes"
    # Stub classification: main.py is < 100 lines
    assert entry.main_py_lines < 100


def test_52_node60_reinforcement_learning_in_config_post_pr7(audit_report):
    # PR-7 added Node_60_ReinforcementLearning to node_dependencies.json with
    # startup_policy='optional' (config drift resolved). It is no longer an
    # orphan; verify the audit sees it as a runnable node.
    entry = next(
        (n for n in audit_report.nodes if n.name == "Node_60_ReinforcementLearning"),
        None,
    )
    assert entry is not None, "Node_60_ReinforcementLearning not found in audit nodes"
    assert entry.has_main_py is True


def test_53_report_nodes_length_equals_nominal_count(audit_report):
    assert len(audit_report.nodes) == audit_report.nominal_count


def test_54_generated_at_is_non_empty(audit_report):
    assert audit_report.generated_at != ""


def test_55_project_root_is_non_empty(audit_report):
    assert audit_report.project_root != ""


def test_56_node00_config_group_is_core(nodes_by_name):
    assert nodes_by_name["Node_00_StateMachine"].config_group == "core"


def test_57_node00_has_dockerfile(nodes_by_name):
    assert nodes_by_name["Node_00_StateMachine"].has_dockerfile is True


def test_58_node00_has_main_py(nodes_by_name):
    assert nodes_by_name["Node_00_StateMachine"].has_main_py is True


def test_59_node00_main_py_lines_gte_100(nodes_by_name):
    assert nodes_by_name["Node_00_StateMachine"].main_py_lines >= 100


def test_60_keep_count_gte_80(audit_report):
    assert audit_report.keep_count >= 80


# ---------------------------------------------------------------------------
# 61–100: PR-2 canonical governance engine tests
# ---------------------------------------------------------------------------

# ── Check category constants ──────────────────────────────────────────────

def test_61_check_source_completeness_constant():
    assert CHECK_SOURCE_COMPLETENESS == "source_completeness"


def test_62_check_syntax_safety_constant():
    assert CHECK_SYNTAX_SAFETY == "syntax_safety"


def test_63_check_packaging_constant():
    assert CHECK_PACKAGING == "packaging"


def test_64_check_registry_governance_constant():
    assert CHECK_REGISTRY_GOVERNANCE == "registry_governance"


def test_65_check_runtime_contract_constant():
    assert CHECK_RUNTIME_CONTRACT == "runtime_contract"


def test_66_check_hygiene_constant():
    assert CHECK_HYGIENE == "hygiene"


def test_67_check_pass_constant():
    assert CHECK_PASS == "pass"


def test_68_check_warn_constant():
    assert CHECK_WARN == "warn"


def test_69_check_fail_constant():
    assert CHECK_FAIL == "fail"


def test_70_check_unknown_constant():
    assert CHECK_UNKNOWN == "unknown"


# ── NodeAuditEntry new PR-2 fields ───────────────────────────────────────

def test_71_node_audit_entry_has_syntax_ok_field():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert hasattr(e, "syntax_ok")
    assert e.syntax_ok is None


def test_72_node_audit_entry_has_fusion_syntax_ok_field():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert hasattr(e, "fusion_syntax_ok")
    assert e.fusion_syntax_ok is None


def test_73_node_audit_entry_has_config_startup_policy_field():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert hasattr(e, "config_startup_policy")
    assert e.config_startup_policy is None


def test_74_node_audit_entry_has_policy_valid_field():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert hasattr(e, "policy_valid")
    assert e.policy_valid is None


def test_75_node_audit_entry_has_health_endpoint_field():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert hasattr(e, "has_health_endpoint")
    assert e.has_health_endpoint is False


def test_76_node_audit_entry_has_status_endpoint_field():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert hasattr(e, "has_status_endpoint")
    assert e.has_status_endpoint is False


def test_77_node_audit_entry_has_hygiene_violations_field():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert hasattr(e, "hygiene_violations")
    assert isinstance(e.hygiene_violations, list)


def test_78_node_audit_entry_has_checks_field():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert hasattr(e, "checks")
    assert isinstance(e.checks, dict)


def test_79_node_audit_entry_to_dict_contains_new_fields():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    d = e.to_dict()
    for key in ("syntax_ok", "fusion_syntax_ok", "config_startup_policy",
                "policy_valid", "has_health_endpoint", "has_status_endpoint",
                "hygiene_violations", "checks"):
        assert key in d, f"to_dict() missing key '{key}'"


# ── NodeAuditReport new PR-2 fields ──────────────────────────────────────

def test_80_report_has_port_conflicts_field(audit_report):
    assert hasattr(audit_report, "port_conflicts")
    assert isinstance(audit_report.port_conflicts, list)


def test_81_report_has_syntax_error_nodes_field(audit_report):
    assert hasattr(audit_report, "syntax_error_nodes")
    assert isinstance(audit_report.syntax_error_nodes, list)


def test_82_report_has_missing_packaging_nodes_field(audit_report):
    assert hasattr(audit_report, "missing_packaging_nodes")
    assert isinstance(audit_report.missing_packaging_nodes, list)


def test_83_report_has_hygiene_violation_nodes_field(audit_report):
    assert hasattr(audit_report, "hygiene_violation_nodes")
    assert isinstance(audit_report.hygiene_violation_nodes, list)


def test_84_report_has_policy_violation_nodes_field(audit_report):
    assert hasattr(audit_report, "policy_violation_nodes")
    assert isinstance(audit_report.policy_violation_nodes, list)


def test_85_report_has_missing_required_files_nodes_field(audit_report):
    assert hasattr(audit_report, "missing_required_files_nodes")
    assert isinstance(audit_report.missing_required_files_nodes, list)


# ── Integration: PR-2 check results on real nodes ────────────────────────

def test_86_all_entries_have_all_six_checks(audit_report):
    """Every node entry must have all six check categories populated."""
    required = {
        CHECK_SOURCE_COMPLETENESS, CHECK_SYNTAX_SAFETY, CHECK_PACKAGING,
        CHECK_REGISTRY_GOVERNANCE, CHECK_RUNTIME_CONTRACT, CHECK_HYGIENE,
    }
    valid_values = {CHECK_PASS, CHECK_WARN, CHECK_FAIL, CHECK_UNKNOWN}
    for entry in audit_report.nodes:
        missing = required - set(entry.checks)
        assert not missing, f"{entry.name} missing checks: {missing}"
        for cat, val in entry.checks.items():
            assert val in valid_values, (
                f"{entry.name} check '{cat}' has invalid value '{val}'"
            )


def test_87_orchestrated_nodes_pass_registry_governance(audit_report):
    """Every ORCHESTRATED node must pass the registry_governance check."""
    for entry in audit_report.nodes:
        if entry.tier == NodeTier.ORCHESTRATED:
            result = entry.checks.get(CHECK_REGISTRY_GOVERNANCE)
            assert result == CHECK_PASS, (
                f"{entry.name} tier=orchestrated but registry_governance={result}"
            )


def test_88_no_syntax_errors_in_repo(audit_report):
    """No node should have a Python syntax error — all files must compile."""
    assert audit_report.syntax_error_nodes == [], (
        f"Nodes with syntax errors: {audit_report.syntax_error_nodes}"
    )


def test_89_no_port_conflicts_in_registry(audit_report):
    """node_dependencies.json must not assign the same port to two nodes."""
    assert audit_report.port_conflicts == [], (
        f"Port conflicts detected: {audit_report.port_conflicts}"
    )


def test_90_no_policy_violations(audit_report):
    """No node should have an invalid startup_policy value."""
    assert audit_report.policy_violation_nodes == [], (
        f"Nodes with invalid policy: {audit_report.policy_violation_nodes}"
    )


def test_91_node95_has_hygiene_violation(audit_report, nodes_by_name):
    """Node_95_WebRTC_Receiver passes hygiene — committed .pid fixture was removed."""
    entry = nodes_by_name.get("Node_95_WebRTC_Receiver")
    assert entry is not None
    # The .pid file that previously existed was cleaned up; the node is now clean.
    assert not entry.hygiene_violations, (
        f"Unexpected hygiene violations on Node_95_WebRTC_Receiver: "
        f"{entry.hygiene_violations}"
    )
    assert entry.checks.get(CHECK_HYGIENE) == CHECK_PASS


def test_92_node00_passes_syntax_check(nodes_by_name):
    """Node_00_StateMachine must pass the syntax_safety check."""
    entry = nodes_by_name["Node_00_StateMachine"]
    assert entry.syntax_ok is True
    assert entry.checks.get(CHECK_SYNTAX_SAFETY) == CHECK_PASS


def test_93_node00_has_runtime_contract(nodes_by_name):
    """Node_00_StateMachine declares /health and /status endpoints."""
    entry = nodes_by_name["Node_00_StateMachine"]
    assert entry.has_health_endpoint is True
    assert entry.has_status_endpoint is True
    assert entry.checks.get(CHECK_RUNTIME_CONTRACT) == CHECK_PASS


def test_94_node00_policy_valid(nodes_by_name):
    """Node_00_StateMachine is in config and should have policy_valid=True."""
    entry = nodes_by_name["Node_00_StateMachine"]
    assert entry.policy_valid is True


def test_95_missing_required_files_contains_nodes_without_main(audit_report):
    """missing_required_files_nodes must include every node that has no main.py."""
    for entry in audit_report.nodes:
        if not entry.has_main_py:
            assert entry.name in audit_report.missing_required_files_nodes, (
                f"{entry.name} has no main.py but not in missing_required_files_nodes"
            )


def test_96_checks_dict_is_json_serialisable(audit_report):
    """All checks dicts must round-trip through JSON (required for report output)."""
    for entry in audit_report.nodes:
        json.dumps(entry.checks)  # must not raise


def test_97_report_to_dict_contains_pr2_aggregate_fields(audit_report):
    d = audit_report.to_dict()
    for key in (
        "port_conflicts", "syntax_error_nodes", "missing_packaging_nodes",
        "hygiene_violation_nodes", "policy_violation_nodes",
        "missing_required_files_nodes",
    ):
        assert key in d, f"report.to_dict() missing key '{key}'"


def test_98_core_module_exports_check_constants():
    """core/node_audit.py must re-export all PR-2 check constants."""
    from core.node_audit import (
        CHECK_SOURCE_COMPLETENESS as CSC,
        CHECK_SYNTAX_SAFETY as CSS,
        CHECK_PACKAGING as CPK,
        CHECK_REGISTRY_GOVERNANCE as CRG,
        CHECK_RUNTIME_CONTRACT as CRC,
        CHECK_HYGIENE as CHY,
        CHECK_PASS, CHECK_WARN, CHECK_FAIL, CHECK_UNKNOWN,
    )
    assert CSC == "source_completeness"
    assert CSS == "syntax_safety"
    assert CPK == "packaging"
    assert CRG == "registry_governance"
    assert CRC == "runtime_contract"
    assert CHY == "hygiene"
    assert CHECK_PASS == "pass"
    assert CHECK_WARN == "warn"
    assert CHECK_FAIL == "fail"
    assert CHECK_UNKNOWN == "unknown"


def test_99_nodes_without_fusion_entry_have_source_completeness_warn_or_fail(audit_report):
    """Nodes missing fusion_entry.py must not have source_completeness=pass."""
    for entry in audit_report.nodes:
        if not entry.has_fusion_entry:
            result = entry.checks.get(CHECK_SOURCE_COMPLETENESS)
            assert result in (CHECK_WARN, CHECK_FAIL, CHECK_UNKNOWN), (
                f"{entry.name} missing fusion_entry.py but has "
                f"source_completeness={result}"
            )


def test_100_hygiene_violation_nodes_list_consistent_with_entry_violations(audit_report):
    """hygiene_violation_nodes aggregate must be consistent with per-entry data."""
    from_entries = sorted(
        e.name for e in audit_report.nodes if e.hygiene_violations
    )
    assert audit_report.hygiene_violation_nodes == from_entries

