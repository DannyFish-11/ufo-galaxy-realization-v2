#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5_packaging_audit.py
===================================

PR-5 — Unify packaging coverage into the canonical node audit.

Validates:
  1.  NodePackagingStatus can be imported from scripts.node_audit.
  2.  NodePackagingStatus can be imported from core.node_audit.
  3.  NodePackagingStatus instantiates with default field values.
  4.  NodePackagingStatus.has_dockerfile defaults to False.
  5.  NodePackagingStatus.has_requirements defaults to False.
  6.  NodePackagingStatus.missing defaults to empty list.
  7.  NodePackagingStatus.policy_class defaults to "unregistered".
  8.  NodePackagingStatus.status defaults to "unknown".
  9.  NodePackagingStatus.severity defaults to "unknown".
  10. NodePackagingStatus.to_dict() returns a dict with all required keys.
  11. PACKAGING_POLICY_ACTIVE constant equals "active".
  12. PACKAGING_POLICY_OPTIONAL constant equals "optional".
  13. PACKAGING_POLICY_SKIP constant equals "skip".
  14. PACKAGING_POLICY_UNREGISTERED constant equals "unregistered".
  15. core.node_audit exports PACKAGING_POLICY_ACTIVE.
  16. core.node_audit exports PACKAGING_POLICY_OPTIONAL.
  17. core.node_audit exports PACKAGING_POLICY_SKIP.
  18. core.node_audit exports PACKAGING_POLICY_UNREGISTERED.
  19. NodeAuditEntry has a 'packaging' field.
  20. NodeAuditEntry.packaging is a NodePackagingStatus instance by default.
  21. NodeAuditEntry.to_dict() contains a 'packaging' key.
  22. NodeAuditEntry.to_dict()['packaging'] is a dict.
  23. NodeAuditReport has 'missing_dockerfile_nodes' field.
  24. NodeAuditReport has 'missing_requirements_nodes' field.
  25. NodeAuditReport.missing_dockerfile_nodes defaults to empty list.
  26. NodeAuditReport.missing_requirements_nodes defaults to empty list.
  27. NodeAuditReport.to_dict() contains 'missing_dockerfile_nodes'.
  28. NodeAuditReport.to_dict() contains 'missing_requirements_nodes'.
  29. run_audit() every entry has a packaging field of type NodePackagingStatus.
  30. run_audit() packaging.has_dockerfile is consistent with entry.has_dockerfile.
  31. run_audit() packaging.has_requirements is consistent with entry.has_requirements.
  32. run_audit() packaging.missing is a list.
  33. run_audit() packaging.missing contains "Dockerfile" iff not has_dockerfile.
  34. run_audit() packaging.missing contains "requirements.txt" iff not has_requirements.
  35. run_audit() packaging.policy_class is one of the four valid classes.
  36. run_audit() packaging.status is one of: pass/warn/fail.
  37. run_audit() packaging.severity is one of: pass/warn/fail.
  38. run_audit() fully-packaged nodes have packaging.status == "pass".
  39. run_audit() fully-packaged nodes have packaging.missing == [].
  40. run_audit() checks['packaging'] equals packaging.status for every node.
  41. run_audit() active nodes missing Dockerfile have packaging.status == "fail".
  42. run_audit() active nodes missing Dockerfile have packaging.severity == "fail".
  43. run_audit() optional/skip nodes missing packaging have packaging.status == "warn".
  44. run_audit() unregistered nodes missing packaging have packaging.status == "warn".
  45. run_audit() missing_dockerfile_nodes matches entries missing Dockerfile.
  46. run_audit() missing_requirements_nodes matches entries missing requirements.txt.
  47. run_audit() missing_packaging_nodes includes nodes missing EITHER file.
  48. run_audit() missing_packaging_nodes is superset of missing_dockerfile_nodes.
  49. run_audit() missing_packaging_nodes is superset of missing_requirements_nodes.
  50. run_audit() to_dict() packaging field is JSON-serialisable for all nodes.
  51. run_audit() packaging.policy_class "active" assigned for nodes in config with no policy.
  52. run_audit() packaging.policy_class "active" assigned for nodes with startup_policy="active".
  53. run_audit() packaging.policy_class "optional" assigned for nodes with startup_policy="optional".
  54. run_audit() packaging.policy_class "skip" assigned for nodes with startup_policy="skip".
  55. run_audit() packaging.policy_class "unregistered" for nodes not in node_dependencies.json.
  56. run_audit() Node_00_StateMachine has packaging.status == "pass".
  57. run_audit() Node_00_StateMachine has empty packaging.missing.
  58. run_audit() report.to_dict() contains 'missing_dockerfile_nodes' key.
  59. run_audit() report.to_dict() contains 'missing_requirements_nodes' key.
  60. run_audit() packaging objects are consistent with the checks['packaging'] column.
"""

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from scripts.node_audit import (
    NodeTier,
    NodePackagingStatus,
    NodeAuditEntry,
    NodeAuditReport,
    run_audit,
    CHECK_PASS,
    CHECK_WARN,
    CHECK_FAIL,
    CHECK_UNKNOWN,
    CHECK_PACKAGING,
    PACKAGING_POLICY_ACTIVE,
    PACKAGING_POLICY_OPTIONAL,
    PACKAGING_POLICY_SKIP,
    PACKAGING_POLICY_UNREGISTERED,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.absolute()


@pytest.fixture(scope="module")
def audit_report() -> NodeAuditReport:
    return run_audit(_PROJECT_ROOT)


@pytest.fixture(scope="module")
def nodes_by_name(audit_report: NodeAuditReport):
    return {e.name: e for e in audit_report.nodes}


# ---------------------------------------------------------------------------
# 1–2: Import smoke tests
# ---------------------------------------------------------------------------

def test_01_node_packaging_status_importable_from_scripts():
    from scripts.node_audit import NodePackagingStatus as NPS  # noqa: F401


def test_02_node_packaging_status_importable_from_core():
    from core.node_audit import NodePackagingStatus as NPS  # noqa: F401


# ---------------------------------------------------------------------------
# 3–10: NodePackagingStatus dataclass defaults
# ---------------------------------------------------------------------------

def test_03_packaging_status_instantiates():
    ps = NodePackagingStatus()
    assert ps is not None


def test_04_packaging_status_has_dockerfile_defaults_false():
    assert NodePackagingStatus().has_dockerfile is False


def test_05_packaging_status_has_requirements_defaults_false():
    assert NodePackagingStatus().has_requirements is False


def test_06_packaging_status_missing_defaults_empty():
    assert NodePackagingStatus().missing == []


def test_07_packaging_status_policy_class_defaults_to_unregistered():
    assert NodePackagingStatus().policy_class == PACKAGING_POLICY_UNREGISTERED


def test_08_packaging_status_status_defaults_to_unknown():
    assert NodePackagingStatus().status == CHECK_UNKNOWN


def test_09_packaging_status_severity_defaults_to_unknown():
    assert NodePackagingStatus().severity == CHECK_UNKNOWN


def test_10_packaging_status_to_dict_has_all_keys():
    d = NodePackagingStatus().to_dict()
    for key in ("has_dockerfile", "has_requirements", "missing",
                "policy_class", "status", "severity"):
        assert key in d, f"NodePackagingStatus.to_dict() missing key '{key}'"


# ---------------------------------------------------------------------------
# 11–18: Policy-class constants
# ---------------------------------------------------------------------------

def test_11_packaging_policy_active_constant():
    assert PACKAGING_POLICY_ACTIVE == "active"


def test_12_packaging_policy_optional_constant():
    assert PACKAGING_POLICY_OPTIONAL == "optional"


def test_13_packaging_policy_skip_constant():
    assert PACKAGING_POLICY_SKIP == "skip"


def test_14_packaging_policy_unregistered_constant():
    assert PACKAGING_POLICY_UNREGISTERED == "unregistered"


def test_15_core_exports_packaging_policy_active():
    from core.node_audit import PACKAGING_POLICY_ACTIVE as C
    assert C == "active"


def test_16_core_exports_packaging_policy_optional():
    from core.node_audit import PACKAGING_POLICY_OPTIONAL as C
    assert C == "optional"


def test_17_core_exports_packaging_policy_skip():
    from core.node_audit import PACKAGING_POLICY_SKIP as C
    assert C == "skip"


def test_18_core_exports_packaging_policy_unregistered():
    from core.node_audit import PACKAGING_POLICY_UNREGISTERED as C
    assert C == "unregistered"


# ---------------------------------------------------------------------------
# 19–22: NodeAuditEntry.packaging field
# ---------------------------------------------------------------------------

def test_19_node_audit_entry_has_packaging_field():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert hasattr(e, "packaging")


def test_20_node_audit_entry_packaging_is_node_packaging_status():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert isinstance(e.packaging, NodePackagingStatus)


def test_21_node_audit_entry_to_dict_contains_packaging():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert "packaging" in e.to_dict()


def test_22_node_audit_entry_to_dict_packaging_is_dict():
    e = NodeAuditEntry(name="Node_99_Test", path="nodes/Node_99_Test")
    assert isinstance(e.to_dict()["packaging"], dict)


# ---------------------------------------------------------------------------
# 23–28: NodeAuditReport new packaging aggregate fields
# ---------------------------------------------------------------------------

def test_23_report_has_missing_dockerfile_nodes_field():
    r = NodeAuditReport(generated_at="2026-01-01T00:00:00Z", project_root="/tmp")
    assert hasattr(r, "missing_dockerfile_nodes")


def test_24_report_has_missing_requirements_nodes_field():
    r = NodeAuditReport(generated_at="2026-01-01T00:00:00Z", project_root="/tmp")
    assert hasattr(r, "missing_requirements_nodes")


def test_25_report_missing_dockerfile_nodes_defaults_empty():
    r = NodeAuditReport(generated_at="2026-01-01T00:00:00Z", project_root="/tmp")
    assert r.missing_dockerfile_nodes == []


def test_26_report_missing_requirements_nodes_defaults_empty():
    r = NodeAuditReport(generated_at="2026-01-01T00:00:00Z", project_root="/tmp")
    assert r.missing_requirements_nodes == []


def test_27_report_to_dict_contains_missing_dockerfile_nodes():
    r = NodeAuditReport(generated_at="2026-01-01T00:00:00Z", project_root="/tmp")
    assert "missing_dockerfile_nodes" in r.to_dict()


def test_28_report_to_dict_contains_missing_requirements_nodes():
    r = NodeAuditReport(generated_at="2026-01-01T00:00:00Z", project_root="/tmp")
    assert "missing_requirements_nodes" in r.to_dict()


# ---------------------------------------------------------------------------
# 29–60: run_audit() integration tests
# ---------------------------------------------------------------------------

def test_29_every_entry_has_packaging_field(audit_report):
    for e in audit_report.nodes:
        assert isinstance(e.packaging, NodePackagingStatus), (
            f"{e.name} packaging field is not a NodePackagingStatus"
        )


def test_30_packaging_has_dockerfile_consistent_with_entry(audit_report):
    for e in audit_report.nodes:
        assert e.packaging.has_dockerfile == e.has_dockerfile, (
            f"{e.name}: packaging.has_dockerfile={e.packaging.has_dockerfile} "
            f"!= has_dockerfile={e.has_dockerfile}"
        )


def test_31_packaging_has_requirements_consistent_with_entry(audit_report):
    for e in audit_report.nodes:
        assert e.packaging.has_requirements == e.has_requirements, (
            f"{e.name}: packaging.has_requirements mismatch"
        )


def test_32_packaging_missing_is_list(audit_report):
    for e in audit_report.nodes:
        assert isinstance(e.packaging.missing, list), (
            f"{e.name} packaging.missing is not a list"
        )


def test_33_packaging_missing_contains_dockerfile_iff_absent(audit_report):
    for e in audit_report.nodes:
        has_df = "Dockerfile" not in e.packaging.missing
        assert has_df == e.has_dockerfile, (
            f"{e.name}: 'Dockerfile' in missing={not has_df} but "
            f"has_dockerfile={e.has_dockerfile}"
        )


def test_34_packaging_missing_contains_requirements_iff_absent(audit_report):
    for e in audit_report.nodes:
        has_req = "requirements.txt" not in e.packaging.missing
        assert has_req == e.has_requirements, (
            f"{e.name}: 'requirements.txt' in missing mismatch"
        )


def test_35_packaging_policy_class_is_valid(audit_report):
    valid = {
        PACKAGING_POLICY_ACTIVE, PACKAGING_POLICY_OPTIONAL,
        PACKAGING_POLICY_SKIP, PACKAGING_POLICY_UNREGISTERED,
    }
    for e in audit_report.nodes:
        assert e.packaging.policy_class in valid, (
            f"{e.name} packaging.policy_class={e.packaging.policy_class!r} invalid"
        )


def test_36_packaging_status_is_valid(audit_report):
    valid = {CHECK_PASS, CHECK_WARN, CHECK_FAIL}
    for e in audit_report.nodes:
        assert e.packaging.status in valid, (
            f"{e.name} packaging.status={e.packaging.status!r} invalid"
        )


def test_37_packaging_severity_is_valid(audit_report):
    valid = {CHECK_PASS, CHECK_WARN, CHECK_FAIL}
    for e in audit_report.nodes:
        assert e.packaging.severity in valid, (
            f"{e.name} packaging.severity={e.packaging.severity!r} invalid"
        )


def test_38_fully_packaged_nodes_have_status_pass(audit_report):
    for e in audit_report.nodes:
        if e.has_dockerfile and e.has_requirements:
            assert e.packaging.status == CHECK_PASS, (
                f"{e.name} fully packaged but packaging.status={e.packaging.status}"
            )


def test_39_fully_packaged_nodes_have_empty_missing(audit_report):
    for e in audit_report.nodes:
        if e.has_dockerfile and e.has_requirements:
            assert e.packaging.missing == [], (
                f"{e.name} fully packaged but packaging.missing={e.packaging.missing}"
            )


def test_40_checks_packaging_equals_packaging_status(audit_report):
    for e in audit_report.nodes:
        expected = e.packaging.status
        actual = e.checks.get(CHECK_PACKAGING)
        assert actual == expected, (
            f"{e.name} checks['packaging']={actual} != packaging.status={expected}"
        )


def test_41_active_nodes_missing_dockerfile_have_packaging_fail(audit_report):
    for e in audit_report.nodes:
        if (e.packaging.policy_class == PACKAGING_POLICY_ACTIVE
                and not e.has_dockerfile):
            assert e.packaging.status == CHECK_FAIL, (
                f"{e.name} active, missing Dockerfile, but packaging.status={e.packaging.status}"
            )


def test_42_active_nodes_missing_dockerfile_have_severity_fail(audit_report):
    for e in audit_report.nodes:
        if (e.packaging.policy_class == PACKAGING_POLICY_ACTIVE
                and not e.has_dockerfile):
            assert e.packaging.severity == CHECK_FAIL, (
                f"{e.name} active, missing Dockerfile, severity={e.packaging.severity}"
            )


def test_43_optional_skip_nodes_missing_packaging_have_status_warn(audit_report):
    non_active = {PACKAGING_POLICY_OPTIONAL, PACKAGING_POLICY_SKIP}
    for e in audit_report.nodes:
        if e.packaging.policy_class in non_active and e.packaging.missing:
            assert e.packaging.status == CHECK_WARN, (
                f"{e.name} ({e.packaging.policy_class}) missing packaging but "
                f"status={e.packaging.status}"
            )


def test_44_unregistered_nodes_missing_packaging_have_status_warn(audit_report):
    for e in audit_report.nodes:
        if (e.packaging.policy_class == PACKAGING_POLICY_UNREGISTERED
                and e.packaging.missing):
            assert e.packaging.status == CHECK_WARN, (
                f"{e.name} unregistered, missing packaging, status={e.packaging.status}"
            )


def test_45_missing_dockerfile_nodes_matches_entries(audit_report):
    from_entries = sorted(e.name for e in audit_report.nodes if not e.has_dockerfile)
    assert audit_report.missing_dockerfile_nodes == from_entries


def test_46_missing_requirements_nodes_matches_entries(audit_report):
    from_entries = sorted(e.name for e in audit_report.nodes if not e.has_requirements)
    assert audit_report.missing_requirements_nodes == from_entries


def test_47_missing_packaging_nodes_includes_either_missing(audit_report):
    from_entries = sorted(
        e.name for e in audit_report.nodes
        if not e.has_dockerfile or not e.has_requirements
    )
    assert audit_report.missing_packaging_nodes == from_entries


def test_48_missing_packaging_superset_of_missing_dockerfile(audit_report):
    df_set = set(audit_report.missing_dockerfile_nodes)
    pkg_set = set(audit_report.missing_packaging_nodes)
    assert df_set <= pkg_set, (
        f"missing_dockerfile_nodes is not a subset of missing_packaging_nodes: "
        f"{df_set - pkg_set}"
    )


def test_49_missing_packaging_superset_of_missing_requirements(audit_report):
    req_set = set(audit_report.missing_requirements_nodes)
    pkg_set = set(audit_report.missing_packaging_nodes)
    assert req_set <= pkg_set, (
        f"missing_requirements_nodes is not a subset of missing_packaging_nodes: "
        f"{req_set - pkg_set}"
    )


def test_50_packaging_to_dict_json_serialisable(audit_report):
    for e in audit_report.nodes:
        json.dumps(e.packaging.to_dict())  # must not raise


def test_51_active_policy_for_nodes_in_config_without_explicit_policy(audit_report):
    for e in audit_report.nodes:
        if e.in_node_dependencies and e.config_startup_policy is None:
            assert e.packaging.policy_class == PACKAGING_POLICY_ACTIVE, (
                f"{e.name} in config, policy=None should be 'active', "
                f"got {e.packaging.policy_class!r}"
            )


def test_52_active_policy_for_nodes_with_explicit_active(audit_report):
    for e in audit_report.nodes:
        if e.config_startup_policy == "active":
            assert e.packaging.policy_class == PACKAGING_POLICY_ACTIVE


def test_53_optional_policy_class_for_optional_nodes(audit_report):
    for e in audit_report.nodes:
        if e.config_startup_policy == "optional":
            assert e.packaging.policy_class == PACKAGING_POLICY_OPTIONAL, (
                f"{e.name} startup_policy=optional should have "
                f"policy_class='optional', got {e.packaging.policy_class!r}"
            )


def test_54_skip_policy_class_for_skip_nodes(audit_report):
    for e in audit_report.nodes:
        if e.config_startup_policy == "skip":
            assert e.packaging.policy_class == PACKAGING_POLICY_SKIP, (
                f"{e.name} startup_policy=skip should have "
                f"policy_class='skip', got {e.packaging.policy_class!r}"
            )


def test_55_unregistered_policy_class_for_nodes_not_in_config(audit_report):
    for e in audit_report.nodes:
        if not e.in_node_dependencies:
            assert e.packaging.policy_class == PACKAGING_POLICY_UNREGISTERED, (
                f"{e.name} not in config should have "
                f"policy_class='unregistered', got {e.packaging.policy_class!r}"
            )


def test_56_node00_packaging_status_pass(nodes_by_name):
    node = nodes_by_name["Node_00_StateMachine"]
    assert node.packaging.status == CHECK_PASS


def test_57_node00_packaging_missing_empty(nodes_by_name):
    node = nodes_by_name["Node_00_StateMachine"]
    assert node.packaging.missing == []


def test_58_report_to_dict_contains_missing_dockerfile_nodes(audit_report):
    assert "missing_dockerfile_nodes" in audit_report.to_dict()


def test_59_report_to_dict_contains_missing_requirements_nodes(audit_report):
    assert "missing_requirements_nodes" in audit_report.to_dict()


def test_60_packaging_status_consistent_with_checks_column(audit_report):
    """checks['packaging'] and packaging.status must agree for every node."""
    for e in audit_report.nodes:
        assert e.checks.get(CHECK_PACKAGING) == e.packaging.status, (
            f"{e.name}: checks['packaging']={e.checks.get(CHECK_PACKAGING)!r} "
            f"!= packaging.status={e.packaging.status!r}"
        )
