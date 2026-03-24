"""
tests/test_pr6_startup_policy_normalization.py
===============================================

PR-6 — Normalize node registry fields and formalize startup policy state machine.

Tests verify that:
  1. Every entry in node_dependencies.json carries an explicit startup_policy field.
  2. All startup_policy values are within the valid set {active, optional, skip}.
  3. Registry-level counts are consistent with documented expectations.
  4. The state-machine metadata block is present in node_dependencies.json.
  5. launcher/node_startup.py correctly implements all three policy behaviours.
  6. node_audit.py _VALID_STARTUP_POLICIES is aligned with the canonical set.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Dict, Tuple
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def node_data() -> dict:
    path = PROJECT_ROOT / "node_dependencies.json"
    assert path.exists(), "node_dependencies.json must exist"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def nodes(node_data) -> Dict[str, dict]:
    nodes = node_data.get("nodes", {})
    assert nodes, "node_dependencies.json must have a non-empty 'nodes' key"
    return nodes


# ---------------------------------------------------------------------------
# 1. All nodes have an explicit startup_policy field
# ---------------------------------------------------------------------------

class TestExplicitStartupPolicy:
    """Every registry entry must carry an explicit startup_policy after PR-6."""

    def test_no_implicit_startup_policy(self, nodes):
        """No node entry should be missing the startup_policy key."""
        missing = [nid for nid, entry in nodes.items() if "startup_policy" not in entry]
        assert not missing, (
            f"PR-6 requires explicit startup_policy on every entry. "
            f"Missing on {len(missing)} nodes: {missing[:10]}"
        )

    def test_no_none_startup_policy(self, nodes):
        """No node entry should have startup_policy set to null/None."""
        with_none = [
            nid for nid, entry in nodes.items()
            if entry.get("startup_policy") is None
        ]
        assert not with_none, (
            f"startup_policy must not be null. Found on: {with_none[:10]}"
        )


# ---------------------------------------------------------------------------
# 2. All startup_policy values are within the valid set
# ---------------------------------------------------------------------------

VALID_POLICIES = frozenset({"active", "optional", "skip"})


class TestValidStartupPolicyValues:
    """startup_policy values must be one of {active, optional, skip}."""

    def test_all_policies_are_valid(self, nodes):
        invalid = [
            (nid, entry["startup_policy"])
            for nid, entry in nodes.items()
            if entry.get("startup_policy") not in VALID_POLICIES
        ]
        assert not invalid, (
            f"Unrecognised startup_policy values: {invalid[:10]}"
        )

    def test_no_legacy_policy_names(self, nodes):
        """Policy names like 'auto', 'manual', 'required' must not appear."""
        legacy_names = {"auto", "manual", "required", "disabled", "always"}
        found = [
            (nid, entry.get("startup_policy"))
            for nid, entry in nodes.items()
            if entry.get("startup_policy") in legacy_names
        ]
        assert not found, (
            f"Legacy startup_policy names found (use active/optional/skip): {found[:10]}"
        )


# ---------------------------------------------------------------------------
# 3. Registry-level counts match documented expectations
# ---------------------------------------------------------------------------

class TestPolicyCounts:
    """Registry counts must be consistent with NODE_ACTIVE_MANIFEST.md figures."""

    def test_total_node_count(self, nodes):
        assert len(nodes) == 130, (
            f"Expected 130 total nodes, got {len(nodes)}"
        )

    def test_active_count(self, nodes):
        active = sum(1 for e in nodes.values() if e.get("startup_policy") == "active")
        assert active == 95, f"Expected 95 active nodes, got {active}"

    def test_optional_count(self, nodes):
        optional = sum(1 for e in nodes.values() if e.get("startup_policy") == "optional")
        assert optional == 29, f"Expected 29 optional nodes, got {optional}"

    def test_skip_count(self, nodes):
        skip = sum(1 for e in nodes.values() if e.get("startup_policy") == "skip")
        assert skip == 6, f"Expected 6 skip nodes, got {skip}"

    def test_counts_sum_to_total(self, nodes):
        total = len(nodes)
        counted = sum(
            1 for e in nodes.values()
            if e.get("startup_policy") in VALID_POLICIES
        )
        assert counted == total, (
            f"All {total} nodes must have a recognized startup_policy, "
            f"but only {counted} do."
        )


# ---------------------------------------------------------------------------
# 4. PR-6 metadata block is present in node_dependencies.json
# ---------------------------------------------------------------------------

class TestPR6Metadata:
    """node_dependencies.json should contain the PR-6 normalization metadata."""

    def test_pr6_metadata_key_present(self, node_data):
        assert "_pr6_policy_normalization" in node_data, (
            "node_dependencies.json must contain _pr6_policy_normalization metadata from PR-6"
        )

    def test_pr6_metadata_states_field(self, node_data):
        meta = node_data.get("_pr6_policy_normalization", {})
        sm = meta.get("state_machine", {})
        states = sm.get("states", [])
        assert set(states) == {"active", "optional", "skip"}, (
            f"state_machine.states must be exactly {{active, optional, skip}}, got {states}"
        )

    def test_pr6_metadata_transitions_field(self, node_data):
        meta = node_data.get("_pr6_policy_normalization", {})
        sm = meta.get("state_machine", {})
        transitions = sm.get("transitions", {})
        assert transitions, "state_machine.transitions must be non-empty"
        expected_keys = {
            "optional -> active",
            "active -> optional",
            "active -> skip",
            "optional -> skip",
        }
        assert expected_keys.issubset(transitions.keys()), (
            f"state_machine.transitions missing keys: {expected_keys - transitions.keys()}"
        )

    def test_pr7_metadata_still_present(self, node_data):
        """PR-7 metadata must still exist (PR-6 must not remove it)."""
        assert "_pr7_node_unification" in node_data, (
            "PR-7 metadata _pr7_node_unification must still be present after PR-6"
        )


# ---------------------------------------------------------------------------
# 5. launcher/node_startup.py policy constants are aligned
# ---------------------------------------------------------------------------

class TestLauncherPolicyConstants:
    """NodeSystemLauncher policy constants must match the canonical policy set."""

    @pytest.fixture(scope="class")
    def launcher_module(self) -> ModuleType:
        """Import launcher/node_startup.py in isolation."""
        launcher_path = PROJECT_ROOT / "launcher" / "node_startup.py"
        assert launcher_path.exists(), "launcher/node_startup.py must exist"
        spec = importlib.util.spec_from_file_location(
            "launcher.node_startup_pr6_test", launcher_path
        )
        mod = importlib.util.module_from_spec(spec)
        # Stub out the hard dependencies so the import succeeds in test context
        bootstrap_stub = MagicMock()
        bootstrap_stub.PROJECT_ROOT = PROJECT_ROOT
        bootstrap_stub.print_status = MagicMock()
        sys.modules.setdefault("launcher.bootstrap", bootstrap_stub)
        sys.modules.setdefault("launcher.service_manager", MagicMock())
        with patch.dict(sys.modules, {
            "launcher.bootstrap": bootstrap_stub,
            "launcher.service_manager": MagicMock(),
        }):
            try:
                spec.loader.exec_module(mod)
            except Exception:
                pass
        return mod

    def test_policy_active_constant(self, launcher_module):
        assert getattr(launcher_module.NodeSystemLauncher, "_POLICY_ACTIVE", None) == "active"

    def test_policy_optional_constant(self, launcher_module):
        assert getattr(launcher_module.NodeSystemLauncher, "_POLICY_OPTIONAL", None) == "optional"

    def test_policy_skip_constant(self, launcher_module):
        assert getattr(launcher_module.NodeSystemLauncher, "_POLICY_SKIP", None) == "skip"


# ---------------------------------------------------------------------------
# 6. node_audit.py _VALID_STARTUP_POLICIES is aligned
# ---------------------------------------------------------------------------

class TestAuditValidPolicies:
    """scripts/node_audit.py _VALID_STARTUP_POLICIES must match canonical set."""

    @pytest.fixture(scope="class")
    def audit_module(self) -> ModuleType:
        audit_path = PROJECT_ROOT / "scripts" / "node_audit.py"
        assert audit_path.exists(), "scripts/node_audit.py must exist"
        spec = importlib.util.spec_from_file_location("node_audit_pr6_test", audit_path)
        mod = importlib.util.module_from_spec(spec)
        # Register module in sys.modules before exec so dataclasses can find it
        sys.modules["node_audit_pr6_test"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_valid_startup_policies_constant(self, audit_module):
        vsp = getattr(audit_module, "_VALID_STARTUP_POLICIES", None)
        assert vsp is not None, "_VALID_STARTUP_POLICIES must exist in node_audit.py"
        assert set(vsp) == {"active", "optional", "skip"}, (
            f"_VALID_STARTUP_POLICIES must be exactly {{active, optional, skip}}, got {set(vsp)}"
        )

    def test_registry_governance_warn_on_missing_policy(self, audit_module):
        """Audit engine must return WARN for a node with missing startup_policy."""
        # Build a minimal NodeAuditEntry with explicit config but no policy
        entry = audit_module.NodeAuditEntry(
            name="TestNode",
            path="nodes/TestNode",
            has_main_py=True,
            has_dockerfile=False,
            has_readme=True,
            has_fusion_entry=True,
            has_requirements=False,
            extra_py_files=[],
            main_py_lines=200,
            in_node_dependencies=True,
            config_port=9999,
            config_startup_policy=None,   # ← missing / implicit
            policy_valid=True,
        )
        entry.packaging = audit_module._build_packaging_status(entry)
        checks = audit_module._build_checks(entry)
        assert checks.get(audit_module.CHECK_REGISTRY_GOVERNANCE) == audit_module.CHECK_WARN, (
            "registry_governance check must be WARN when startup_policy is absent"
        )

    def test_registry_governance_pass_on_explicit_active(self, audit_module):
        """Audit engine must return PASS for a node with explicit startup_policy: active."""
        entry = audit_module.NodeAuditEntry(
            name="TestNode",
            path="nodes/TestNode",
            has_main_py=True,
            has_dockerfile=False,
            has_readme=True,
            has_fusion_entry=True,
            has_requirements=False,
            extra_py_files=[],
            main_py_lines=200,
            in_node_dependencies=True,
            config_port=9999,
            config_startup_policy="active",   # ← explicit
            policy_valid=True,
        )
        entry.packaging = audit_module._build_packaging_status(entry)
        checks = audit_module._build_checks(entry)
        assert checks.get(audit_module.CHECK_REGISTRY_GOVERNANCE) == audit_module.CHECK_PASS, (
            "registry_governance check must be PASS when startup_policy is explicit 'active'"
        )

    def test_registry_governance_fail_on_invalid_policy(self, audit_module):
        """Audit engine must return FAIL for a node with an unrecognised policy value."""
        entry = audit_module.NodeAuditEntry(
            name="TestNode",
            path="nodes/TestNode",
            has_main_py=True,
            has_dockerfile=False,
            has_readme=True,
            has_fusion_entry=True,
            has_requirements=False,
            extra_py_files=[],
            main_py_lines=200,
            in_node_dependencies=True,
            config_port=9999,
            config_startup_policy="auto",   # ← invalid legacy name
            policy_valid=False,
        )
        entry.packaging = audit_module._build_packaging_status(entry)
        checks = audit_module._build_checks(entry)
        assert checks.get(audit_module.CHECK_REGISTRY_GOVERNANCE) == audit_module.CHECK_FAIL, (
            "registry_governance check must be FAIL for invalid startup_policy value"
        )
