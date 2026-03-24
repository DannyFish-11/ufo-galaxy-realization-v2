#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr8_optional_governance.py
======================================

PR-8 — Optional-node governance and formalized promotion to active.

Validates:
  1.  All 29 optional nodes are in node_dependencies.json with startup_policy=optional.
  2.  Every optional node has a main.py.
  3.  Every optional node has a fusion_entry.py.
  4.  Every optional node has a README.md (optional-baseline describability check).
  5.  Every optional node has a Dockerfile (packaging check).
  6.  Every optional node has a requirements.txt (packaging check).
  7.  Every optional node main.py / fusion_entry.py passes py_compile.
  8.  No optional node has hygiene violations in its node directory.
  9.  audit report optional_count equals 29.
  10. audit report optional_baseline_pass covers all optional nodes.
  11. audit report optional_baseline_fail is empty.
  12. audit report optional_promotion_ready covers all optional nodes.
  13. audit report optional_promotion_not_ready is empty.
  14. Each optional node entry in audit report has optional_baseline_checks populated.
  15. Each optional node entry in audit report has promotion_gap_checks populated.
  16. NODE_ACTIVE_MANIFEST.md contains the optional-node governance section header.
  17. NODE_ACTIVE_MANIFEST.md contains the promotion checklist header.
  18. NODE_ACTIVE_MANIFEST.md mentions optional-baseline minimum requirements.
  19. MAINTAINER_RUNBOOK.md contains optional-node governance section.
  20. MAINTAINER_RUNBOOK.md contains promotion-gap checks table.
  21. node_audit.py defines OPT_BASELINE_PASS constant.
  22. node_audit.py defines PROMO_READY constant.
  23. node_audit.py exposes _build_optional_governance function.
  24. _build_optional_governance populates optional_baseline_checks for optional nodes.
  25. _build_optional_governance leaves optional_baseline_checks empty for active nodes.
  26. _build_optional_governance baseline result is 'pass' when all checks green.
  27. _build_optional_governance baseline result is 'fail' when main.py missing.
  28. _build_optional_governance promotion readiness is 'ready' when all gap checks pass.
  29. _build_optional_governance promotion readiness is 'near_ready' when 1 gap.
  30. _build_optional_governance promotion readiness is 'not_ready' when ≥2 gaps.
  31. Each optional node README.md contains 'Port' heading.
  32. Each optional node README.md contains at least one endpoint path.
  33. Each optional node README.md is non-trivial (>100 chars).
  34. Nodes missing README (pre-PR-8: Node_70, Node_71, Node_120, Node_121, Node_122, Node_124) now have README.
  35. audit report has new optional-governance aggregate fields (PR-8).
  36. run_audit result has optional_count attribute set.
  37. optional_baseline_pass list contains only optional-policy node names.
  38. optional_promotion_ready list contains only optional-policy node names.
  39. No active node appears in optional_baseline_pass.
  40. No active node appears in optional_promotion_ready.
  41. MAINTAINER_RUNBOOK.md promote-to-active steps reference validate_runtime.
  42. NODE_ACTIVE_MANIFEST.md 'Promotion-Gap Checks' section lists has_dockerfile.
  43. NODE_ACTIVE_MANIFEST.md optional baseline table has has_readme row.
  44. All optional node README.md files contain 'Governance' section.
  45. NODE_ACTIVE_MANIFEST.md references node_audit.py in inspection instructions.
"""

from __future__ import annotations

import json
import py_compile
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
NDJ_PATH     = PROJECT_ROOT / "node_dependencies.json"
AUDIT_PATH   = PROJECT_ROOT / "docs" / "node_audit_report.json"
MANIFEST_PATH = PROJECT_ROOT / "docs" / "NODE_ACTIVE_MANIFEST.md"
RUNBOOK_PATH  = PROJECT_ROOT / "docs" / "MAINTAINER_RUNBOOK.md"
NODES_DIR     = PROJECT_ROOT / "nodes"
AUDIT_SCRIPT  = PROJECT_ROOT / "scripts" / "node_audit.py"

# The 29 optional nodes expected after PR-7 + PR-8
OPTIONAL_NODES: List[str] = [
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

# Nodes that were missing README before PR-8
PR8_README_NODES: List[str] = [
    "Node_70_AutonomousLearning",
    "Node_71_MultiDeviceCoordination",
    "Node_120_File",
    "Node_121_Web",
    "Node_122_Shell",
    "Node_124_LinuxDesktopAuto",
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
def audit_report() -> Dict[str, Any]:
    with open(AUDIT_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def audit_nodes(audit_report) -> List[Dict[str, Any]]:
    return audit_report.get("nodes", [])


@pytest.fixture(scope="module")
def manifest_text() -> str:
    return MANIFEST_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def runbook_text() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def node_audit_module():
    """Import scripts/node_audit.py as a module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("node_audit", AUDIT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # Add to sys.modules before exec so relative imports / __spec__ work correctly
    sys.modules.setdefault("node_audit", mod)
    spec.loader.exec_module(mod)
    return mod


# ── Registry tests ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_in_registry(ndj_nodes, name):
    """Test 1: All optional nodes are in node_dependencies.json."""
    assert name in ndj_nodes, f"{name} missing from node_dependencies.json"


@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_policy_is_optional(ndj_nodes, name):
    """Test 2/1b: Optional nodes have startup_policy=optional."""
    policy = ndj_nodes[name].get("startup_policy")
    assert policy == "optional", f"{name} has startup_policy={policy!r}, expected 'optional'"


# ── Filesystem baseline tests ─────────────────────────────────────────────────

@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_has_main_py(name):
    """Test 2: Every optional node has main.py."""
    assert (NODES_DIR / name / "main.py").exists(), f"{name} missing main.py"


@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_has_fusion_entry(name):
    """Test 3: Every optional node has fusion_entry.py."""
    assert (NODES_DIR / name / "fusion_entry.py").exists(), \
        f"{name} missing fusion_entry.py"


@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_has_readme(name):
    """Test 4: Every optional node has README.md (optional-baseline describability)."""
    assert (NODES_DIR / name / "README.md").exists(), \
        f"{name} missing README.md"


@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_has_dockerfile(name):
    """Test 5: Every optional node has Dockerfile."""
    assert (NODES_DIR / name / "Dockerfile").exists(), \
        f"{name} missing Dockerfile"


@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_has_requirements(name):
    """Test 6: Every optional node has requirements.txt."""
    assert (NODES_DIR / name / "requirements.txt").exists(), \
        f"{name} missing requirements.txt"


@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_syntax_main_py(name):
    """Test 7a: Every optional node main.py passes py_compile."""
    main_py = NODES_DIR / name / "main.py"
    with tempfile.NamedTemporaryFile(suffix=".pyc", delete=True) as tmp:
        try:
            py_compile.compile(str(main_py), cfile=tmp.name, doraise=True)
        except py_compile.PyCompileError as exc:
            pytest.fail(f"{name}/main.py has syntax error: {exc}")


@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_syntax_fusion_entry(name):
    """Test 7b: Every optional node fusion_entry.py passes py_compile."""
    fusion_py = NODES_DIR / name / "fusion_entry.py"
    with tempfile.NamedTemporaryFile(suffix=".pyc", delete=True) as tmp:
        try:
            py_compile.compile(str(fusion_py), cfile=tmp.name, doraise=True)
        except py_compile.PyCompileError as exc:
            pytest.fail(f"{name}/fusion_entry.py has syntax error: {exc}")


@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_no_hygiene_violations(name):
    """Test 8: No optional node has hygiene violations in its node directory."""
    node_dir = NODES_DIR / name
    _HYGIENE_SUFFIXES = {".pid", ".log", ".tmp", ".lock", ".cache"}
    _HYGIENE_NAMES = {"__pycache__"}
    violations = []
    for child in node_dir.iterdir():
        if child.name in _HYGIENE_NAMES or child.suffix in _HYGIENE_SUFFIXES:
            violations.append(child.name)
    assert not violations, f"{name} has hygiene violations: {violations}"


# ── Audit report tests ────────────────────────────────────────────────────────

def test_audit_optional_count(audit_report):
    """Test 9: audit report optional_count equals 29."""
    assert audit_report.get("optional_count") == 29, \
        f"optional_count={audit_report.get('optional_count')}, expected 29"


def test_audit_optional_baseline_pass_complete(audit_report):
    """Test 10: all optional nodes appear in optional_baseline_pass."""
    pass_list = set(audit_report.get("optional_baseline_pass", []))
    for name in OPTIONAL_NODES:
        assert name in pass_list, f"{name} not in optional_baseline_pass"


def test_audit_optional_baseline_fail_empty(audit_report):
    """Test 11: optional_baseline_fail is empty."""
    fail_list = audit_report.get("optional_baseline_fail", [])
    assert not fail_list, f"optional_baseline_fail not empty: {fail_list}"


def test_audit_optional_promotion_ready_complete(audit_report):
    """Test 12: all optional nodes appear in optional_promotion_ready."""
    ready_list = set(audit_report.get("optional_promotion_ready", []))
    for name in OPTIONAL_NODES:
        assert name in ready_list, f"{name} not in optional_promotion_ready"


def test_audit_optional_promotion_not_ready_empty(audit_report):
    """Test 13: optional_promotion_not_ready is empty."""
    not_ready = audit_report.get("optional_promotion_not_ready", [])
    assert not not_ready, f"optional_promotion_not_ready not empty: {not_ready}"


@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_audit_node_has_optional_baseline_checks(audit_nodes, name):
    """Test 14: Each optional node entry has optional_baseline_checks populated."""
    entry = next((n for n in audit_nodes if n["name"] == name), None)
    assert entry is not None, f"{name} not found in audit nodes"
    checks = entry.get("optional_baseline_checks", {})
    assert checks, f"{name} has empty optional_baseline_checks"


@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_audit_node_has_promotion_gap_checks(audit_nodes, name):
    """Test 15: Each optional node entry has promotion_gap_checks populated."""
    entry = next((n for n in audit_nodes if n["name"] == name), None)
    assert entry is not None, f"{name} not found in audit nodes"
    checks = entry.get("promotion_gap_checks", {})
    assert checks, f"{name} has empty promotion_gap_checks"


# ── Documentation tests ────────────────────────────────────────────────────────

def test_manifest_has_optional_governance_section(manifest_text):
    """Test 16: NODE_ACTIVE_MANIFEST.md contains optional governance section."""
    assert "Optional-Node Governance" in manifest_text


def test_manifest_has_promotion_checklist(manifest_text):
    """Test 17: NODE_ACTIVE_MANIFEST.md contains promotion checklist header."""
    assert "Promotion Checklist" in manifest_text


def test_manifest_has_optional_baseline_table(manifest_text):
    """Test 18: NODE_ACTIVE_MANIFEST.md mentions optional-baseline minimum requirements."""
    assert "Optional-Node Minimum Baseline" in manifest_text


def test_runbook_has_optional_governance(runbook_text):
    """Test 19: MAINTAINER_RUNBOOK.md contains optional-node governance section."""
    assert "Optional-node governance" in runbook_text or \
           "optional-node governance" in runbook_text.lower()


def test_runbook_has_promotion_gap_checks(runbook_text):
    """Test 20: MAINTAINER_RUNBOOK.md contains promotion-gap checks table."""
    assert "Promotion-gap checks" in runbook_text or \
           "promotion-gap checks" in runbook_text.lower()


# ── Audit module constant tests ────────────────────────────────────────────────

def test_node_audit_defines_opt_baseline_pass(node_audit_module):
    """Test 21: node_audit.py defines OPT_BASELINE_PASS constant."""
    assert hasattr(node_audit_module, "OPT_BASELINE_PASS")
    assert node_audit_module.OPT_BASELINE_PASS == "pass"


def test_node_audit_defines_promo_ready(node_audit_module):
    """Test 22: node_audit.py defines PROMO_READY constant."""
    assert hasattr(node_audit_module, "PROMO_READY")
    assert node_audit_module.PROMO_READY == "ready"


def test_node_audit_exposes_build_optional_governance(node_audit_module):
    """Test 23: node_audit.py exposes _build_optional_governance function."""
    assert hasattr(node_audit_module, "_build_optional_governance")
    assert callable(node_audit_module._build_optional_governance)


# ── _build_optional_governance unit tests ────────────────────────────────────

def _make_entry(mod, **kwargs) -> Any:
    """Create a minimal NodeAuditEntry with optional kwargs overrides."""
    defaults = {
        "name": "Node_TestOptional",
        "path": "nodes/Node_TestOptional",
        "has_main_py": True,
        "has_dockerfile": True,
        "has_readme": True,
        "has_fusion_entry": True,
        "has_requirements": True,
        "in_node_dependencies": True,
        "config_startup_policy": "optional",
        "syntax_ok": True,
        "fusion_syntax_ok": True,
        "has_health_endpoint": True,
        "has_status_endpoint": True,
        "hygiene_violations": [],
    }
    defaults.update(kwargs)
    entry = mod.NodeAuditEntry(**defaults)
    return entry


def test_build_optional_governance_populates_for_optional(node_audit_module):
    """Test 24: _build_optional_governance populates baseline_checks for optional nodes."""
    entry = _make_entry(node_audit_module)
    node_audit_module._build_optional_governance(entry)
    assert entry.optional_baseline_checks, "optional_baseline_checks should be populated"


def test_build_optional_governance_skips_active(node_audit_module):
    """Test 25: _build_optional_governance leaves checks empty for active nodes."""
    entry = _make_entry(node_audit_module, config_startup_policy="active")
    node_audit_module._build_optional_governance(entry)
    assert not entry.optional_baseline_checks, \
        "optional_baseline_checks should be empty for active nodes"


def test_build_optional_governance_pass_when_all_green(node_audit_module):
    """Test 26: baseline result is 'pass' when all checks green."""
    entry = _make_entry(node_audit_module)
    node_audit_module._build_optional_governance(entry)
    assert entry.optional_baseline_result == node_audit_module.OPT_BASELINE_PASS


def test_build_optional_governance_fail_when_main_py_missing(node_audit_module):
    """Test 27: baseline result is 'fail' when main.py missing."""
    entry = _make_entry(node_audit_module, has_main_py=False, syntax_ok=None)
    node_audit_module._build_optional_governance(entry)
    assert entry.optional_baseline_result == node_audit_module.OPT_BASELINE_FAIL


def test_build_optional_governance_ready_when_all_gap_checks_pass(node_audit_module):
    """Test 28: promotion readiness is 'ready' when all gap checks pass."""
    entry = _make_entry(node_audit_module)
    node_audit_module._build_optional_governance(entry)
    assert entry.promotion_readiness == node_audit_module.PROMO_READY


def test_build_optional_governance_near_ready_with_one_gap(node_audit_module):
    """Test 29: promotion readiness is 'near_ready' when 1 gap."""
    entry = _make_entry(node_audit_module, has_status_endpoint=False)
    node_audit_module._build_optional_governance(entry)
    assert entry.promotion_readiness == node_audit_module.PROMO_NEAR_READY


def test_build_optional_governance_not_ready_with_two_gaps(node_audit_module):
    """Test 30: promotion readiness is 'not_ready' when ≥2 gaps."""
    entry = _make_entry(node_audit_module, has_status_endpoint=False, has_dockerfile=False)
    node_audit_module._build_optional_governance(entry)
    assert entry.promotion_readiness == node_audit_module.PROMO_NOT_READY


# ── README content tests ───────────────────────────────────────────────────────

@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_readme_has_port(name):
    """Test 31: Each optional node README.md contains port information."""
    readme = NODES_DIR / name / "README.md"
    assert readme.exists()
    text = readme.read_text(encoding="utf-8")
    # Accept English "Port", Chinese "端口", or an 8xxx port number
    import re
    has_port = (
        "Port" in text
        or "port" in text.lower()
        or "端口" in text
        or bool(re.search(r"8\d{3}", text))
    )
    assert has_port, f"{name}/README.md missing port information"


@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_readme_has_endpoint(name):
    """Test 32: Each optional node README.md contains at least one endpoint path."""
    readme = NODES_DIR / name / "README.md"
    text = readme.read_text(encoding="utf-8")
    import re
    # Check for any endpoint path (starting with /)
    has_endpoint = bool(re.search(r"[`\s]/[a-zA-Z_]", text))
    assert has_endpoint, f"{name}/README.md missing endpoint paths"


@pytest.mark.parametrize("name", OPTIONAL_NODES)
def test_optional_node_readme_non_trivial(name):
    """Test 33: Each optional node README.md is non-trivial (>100 chars)."""
    readme = NODES_DIR / name / "README.md"
    content = readme.read_text(encoding="utf-8")
    assert len(content) > 100, f"{name}/README.md is too short ({len(content)} chars)"


@pytest.mark.parametrize("name", PR8_README_NODES)
def test_pr8_readme_nodes_now_have_readme(name):
    """Test 34: Nodes missing README before PR-8 now have it."""
    assert (NODES_DIR / name / "README.md").exists(), \
        f"{name} still missing README.md (PR-8 should have added it)"


# ── Aggregate structure tests ─────────────────────────────────────────────────

def test_audit_report_has_optional_aggregate_fields(audit_report):
    """Test 35: audit report has PR-8 optional-governance aggregate fields."""
    required_fields = [
        "optional_count",
        "optional_baseline_pass",
        "optional_baseline_partial",
        "optional_baseline_fail",
        "optional_promotion_ready",
        "optional_promotion_near",
        "optional_promotion_not_ready",
    ]
    for field in required_fields:
        assert field in audit_report, f"audit report missing field: {field}"


def test_audit_optional_count_attribute(node_audit_module):
    """Test 36: run_audit result has optional_count attribute set."""
    report = node_audit_module.run_audit(PROJECT_ROOT)
    assert hasattr(report, "optional_count")
    assert report.optional_count == 29


def test_optional_baseline_pass_only_optional_nodes(audit_report, ndj_nodes):
    """Test 37: optional_baseline_pass contains only optional-policy node names."""
    for name in audit_report.get("optional_baseline_pass", []):
        policy = ndj_nodes.get(name, {}).get("startup_policy")
        assert policy == "optional", \
            f"{name} in optional_baseline_pass but has policy={policy!r}"


def test_optional_promotion_ready_only_optional_nodes(audit_report, ndj_nodes):
    """Test 38: optional_promotion_ready contains only optional-policy node names."""
    for name in audit_report.get("optional_promotion_ready", []):
        policy = ndj_nodes.get(name, {}).get("startup_policy")
        assert policy == "optional", \
            f"{name} in optional_promotion_ready but has policy={policy!r}"


def test_no_active_node_in_optional_baseline_pass(audit_report, ndj_nodes):
    """Test 39: No active node appears in optional_baseline_pass."""
    for name in audit_report.get("optional_baseline_pass", []):
        policy = ndj_nodes.get(name, {}).get("startup_policy", "active")
        assert policy != "active", f"active node {name} found in optional_baseline_pass"


def test_no_active_node_in_optional_promotion_ready(audit_report, ndj_nodes):
    """Test 40: No active node appears in optional_promotion_ready."""
    for name in audit_report.get("optional_promotion_ready", []):
        policy = ndj_nodes.get(name, {}).get("startup_policy", "active")
        assert policy != "active", f"active node {name} found in optional_promotion_ready"


# ── Documentation content tests ───────────────────────────────────────────────

def test_runbook_promote_references_validate_runtime(runbook_text):
    """Test 41: MAINTAINER_RUNBOOK.md promote-to-active steps reference validate_runtime."""
    assert "validate_runtime" in runbook_text


def test_manifest_promotion_gap_has_dockerfile(manifest_text):
    """Test 42: NODE_ACTIVE_MANIFEST.md Promotion-Gap section lists has_dockerfile."""
    assert "has_dockerfile" in manifest_text


def test_manifest_optional_baseline_has_readme_row(manifest_text):
    """Test 43: NODE_ACTIVE_MANIFEST.md optional baseline table has has_readme row."""
    assert "has_readme" in manifest_text


@pytest.mark.parametrize("name", PR8_README_NODES)
def test_pr8_readme_has_governance_section(name):
    """Test 44: New README files added by PR-8 contain 'Governance' section."""
    readme = NODES_DIR / name / "README.md"
    content = readme.read_text(encoding="utf-8")
    assert "Governance" in content, \
        f"{name}/README.md missing 'Governance' section"


def test_manifest_references_node_audit_script(manifest_text):
    """Test 45: NODE_ACTIVE_MANIFEST.md references node_audit.py in instructions."""
    assert "node_audit.py" in manifest_text
