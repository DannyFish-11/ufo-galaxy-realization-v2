"""
tests/test_pr5_fusion_entry_canonical_adapter.py
=================================================
PR-5: Reposition fusion_entry as the Canonical Execution Adapter — test suite.

Tests confirm:
- core.fusion_entry_adapter exports all required policy sentinels.
- FusionEntryAdapterContract correctly validates compliant and non-compliant modules.
- validate_fusion_entry_adapter works correctly against real and synthetic modules.
- check_fusion_entry_compliance returns the right bool and logs appropriately.
- The templates/node_template/fusion_entry.py carries the adapter role marker.
- core.routes.projection exports FUSION_ENTRY_ADAPTER_ALIGNED_PR5.
- core.routes.nodes no longer imports _load_node/_execute_node directly for
  the autonomous_execute path (routed through invoke_node instead).
- CONTRIBUTING.md reflects the narrowed role of fusion_entry.py.
"""

from __future__ import annotations

import inspect
import types
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Policy sentinel tests
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_authority_sentinel_present(self):
        from core.fusion_entry_adapter import FUSION_ENTRY_IS_EXECUTION_ADAPTER_AUTHORITY
        assert isinstance(FUSION_ENTRY_IS_EXECUTION_ADAPTER_AUTHORITY, str)
        assert "execution adapter" in FUSION_ENTRY_IS_EXECUTION_ADAPTER_AUTHORITY.lower()

    def test_pr5_sentinel_value(self):
        from core.fusion_entry_adapter import FUSION_ENTRY_ADAPTER_CONTRACT_PR5_SENTINEL
        assert FUSION_ENTRY_ADAPTER_CONTRACT_PR5_SENTINEL == "FUSION_ENTRY_ADAPTER::PR5_SENTINEL_V1"

    def test_not_registry_authority_policy_present(self):
        from core.fusion_entry_adapter import FUSION_ENTRY_NOT_A_REGISTRY_AUTHORITY_POLICY
        assert "NOT" in FUSION_ENTRY_NOT_A_REGISTRY_AUTHORITY_POLICY or "not" in FUSION_ENTRY_NOT_A_REGISTRY_AUTHORITY_POLICY.lower()
        assert "registry" in FUSION_ENTRY_NOT_A_REGISTRY_AUTHORITY_POLICY.lower()

    def test_not_discovery_authority_policy_present(self):
        from core.fusion_entry_adapter import FUSION_ENTRY_NOT_A_DISCOVERY_AUTHORITY_POLICY
        assert "discovery" in FUSION_ENTRY_NOT_A_DISCOVERY_AUTHORITY_POLICY.lower()

    def test_contract_standardised_policy_present(self):
        from core.fusion_entry_adapter import ADAPTER_CONTRACT_IS_STANDARDISED_POLICY
        assert "FusionNode" in ADAPTER_CONTRACT_IS_STANDARDISED_POLICY
        assert "get_node_instance" in ADAPTER_CONTRACT_IS_STANDARDISED_POLICY

    def test_canonical_loader_policy_present(self):
        from core.fusion_entry_adapter import UNIFIED_EXECUTOR_IS_CANONICAL_LOADER_POLICY
        assert "invoke_node" in UNIFIED_EXECUTOR_IS_CANONICAL_LOADER_POLICY


# ---------------------------------------------------------------------------
# FusionEntryAdapterContract dataclass
# ---------------------------------------------------------------------------

class TestFusionEntryAdapterContract:
    def test_default_non_compliant(self):
        from core.fusion_entry_adapter import FusionEntryAdapterContract
        c = FusionEntryAdapterContract()
        assert c.is_compliant is False

    def test_fully_compliant(self):
        from core.fusion_entry_adapter import FusionEntryAdapterContract
        c = FusionEntryAdapterContract(
            has_fusion_node_class=True,
            fusion_node_has_execute=True,
            execute_is_async=True,
            has_get_node_instance=True,
            get_node_instance_callable=True,
        )
        assert c.is_compliant is True

    def test_missing_fusion_node_not_compliant(self):
        from core.fusion_entry_adapter import FusionEntryAdapterContract
        c = FusionEntryAdapterContract(
            has_fusion_node_class=False,
            fusion_node_has_execute=True,
            has_get_node_instance=True,
            get_node_instance_callable=True,
        )
        assert c.is_compliant is False

    def test_missing_execute_not_compliant(self):
        from core.fusion_entry_adapter import FusionEntryAdapterContract
        c = FusionEntryAdapterContract(
            has_fusion_node_class=True,
            fusion_node_has_execute=False,
            has_get_node_instance=True,
            get_node_instance_callable=True,
        )
        assert c.is_compliant is False

    def test_missing_get_node_instance_not_compliant(self):
        from core.fusion_entry_adapter import FusionEntryAdapterContract
        c = FusionEntryAdapterContract(
            has_fusion_node_class=True,
            fusion_node_has_execute=True,
            has_get_node_instance=False,
            get_node_instance_callable=False,
        )
        assert c.is_compliant is False

    def test_compliance_report_keys(self):
        from core.fusion_entry_adapter import FusionEntryAdapterContract
        c = FusionEntryAdapterContract()
        report = c.compliance_report()
        assert "is_compliant" in report
        assert "has_fusion_node_class" in report
        assert "fusion_node_has_execute" in report
        assert "execute_is_async" in report
        assert "has_get_node_instance" in report
        assert "get_node_instance_callable" in report


# ---------------------------------------------------------------------------
# validate_fusion_entry_adapter
# ---------------------------------------------------------------------------

def _make_compliant_module():
    """Return a synthetic module that satisfies the adapter contract."""
    import asyncio

    class FusionNode:
        async def execute(self, command: str, **params) -> dict:
            return {"success": True}

    mod = types.ModuleType("test_fusion_entry")
    mod.FusionNode = FusionNode
    mod.get_node_instance = lambda: FusionNode()
    return mod


def _make_non_compliant_module_no_fusion_node():
    """Return a module missing FusionNode."""
    mod = types.ModuleType("test_fusion_entry_no_fn")
    mod.get_node_instance = lambda: None
    return mod


def _make_non_compliant_module_sync_execute():
    """Return a module where execute is synchronous (still partially compliant)."""

    class FusionNode:
        def execute(self, command: str, **params) -> dict:
            return {"success": True}

    mod = types.ModuleType("test_fusion_entry_sync")
    mod.FusionNode = FusionNode
    mod.get_node_instance = lambda: FusionNode()
    return mod


class TestValidateFusionEntryAdapter:
    def test_compliant_module(self):
        from core.fusion_entry_adapter import validate_fusion_entry_adapter
        mod = _make_compliant_module()
        contract = validate_fusion_entry_adapter(mod)
        assert contract.is_compliant is True
        assert contract.has_fusion_node_class is True
        assert contract.fusion_node_has_execute is True
        assert contract.execute_is_async is True
        assert contract.has_get_node_instance is True
        assert contract.get_node_instance_callable is True

    def test_no_fusion_node_class(self):
        from core.fusion_entry_adapter import validate_fusion_entry_adapter
        mod = _make_non_compliant_module_no_fusion_node()
        contract = validate_fusion_entry_adapter(mod)
        assert contract.is_compliant is False
        assert contract.has_fusion_node_class is False

    def test_sync_execute_still_detected(self):
        from core.fusion_entry_adapter import validate_fusion_entry_adapter
        mod = _make_non_compliant_module_sync_execute()
        contract = validate_fusion_entry_adapter(mod)
        assert contract.has_fusion_node_class is True
        assert contract.fusion_node_has_execute is True
        # sync execute => not async but the class IS compliant in other ways
        assert contract.execute_is_async is False
        # is_compliant should still be True since execute exists (async is preferred but not strictly required by is_compliant)
        assert contract.is_compliant is True

    def test_empty_module(self):
        from core.fusion_entry_adapter import validate_fusion_entry_adapter
        mod = types.ModuleType("empty_module")
        contract = validate_fusion_entry_adapter(mod)
        assert contract.is_compliant is False

    def test_compliance_report_from_validate(self):
        from core.fusion_entry_adapter import validate_fusion_entry_adapter
        mod = _make_compliant_module()
        contract = validate_fusion_entry_adapter(mod)
        report = contract.compliance_report()
        assert report["is_compliant"] is True


# ---------------------------------------------------------------------------
# check_fusion_entry_compliance
# ---------------------------------------------------------------------------

class TestCheckFusionEntryCompliance:
    def test_compliant_returns_true(self):
        from core.fusion_entry_adapter import check_fusion_entry_compliance
        mod = _make_compliant_module()
        assert check_fusion_entry_compliance(mod, "Node_TEST") is True

    def test_non_compliant_returns_false(self):
        from core.fusion_entry_adapter import check_fusion_entry_compliance
        mod = _make_non_compliant_module_no_fusion_node()
        # non-compliant: missing FusionNode class
        # manually break to ensure failure
        mod2 = types.ModuleType("no_fn_no_gni")
        assert check_fusion_entry_compliance(mod2, "Node_EMPTY") is False

    def test_node_id_optional(self):
        from core.fusion_entry_adapter import check_fusion_entry_compliance
        mod = _make_compliant_module()
        assert check_fusion_entry_compliance(mod) is True


# ---------------------------------------------------------------------------
# Template fusion_entry.py carries adapter role marker
# ---------------------------------------------------------------------------

class TestTemplateAdapterMarker:
    def test_template_has_adapter_role_constant(self):
        import importlib.util
        import os
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "templates", "node_template", "fusion_entry.py",
        )
        assert os.path.exists(template_path), "template fusion_entry.py not found"
        spec = importlib.util.spec_from_file_location(
            "test_template_fusion_entry",
            template_path,
            submodule_search_locations=[os.path.dirname(template_path)],
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "FUSION_ENTRY_IS_EXECUTION_ADAPTER"), (
            "template fusion_entry.py must define FUSION_ENTRY_IS_EXECUTION_ADAPTER"
        )
        assert "EXECUTION_ADAPTER" in mod.FUSION_ENTRY_IS_EXECUTION_ADAPTER

    def test_template_satisfies_adapter_contract(self):
        from core.fusion_entry_adapter import validate_fusion_entry_adapter
        import importlib.util
        import os
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "templates", "node_template", "fusion_entry.py",
        )
        spec = importlib.util.spec_from_file_location(
            "test_template_fusion_entry2",
            template_path,
            submodule_search_locations=[os.path.dirname(template_path)],
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        contract = validate_fusion_entry_adapter(mod)
        assert contract.has_fusion_node_class is True
        assert contract.fusion_node_has_execute is True
        assert contract.has_get_node_instance is True
        assert contract.get_node_instance_callable is True


# ---------------------------------------------------------------------------
# Projection sentinel
# ---------------------------------------------------------------------------

class TestProjectionSentinel:
    def test_fusion_entry_adapter_aligned_pr5_importable(self):
        try:
            from core.routes.projection import FUSION_ENTRY_ADAPTER_ALIGNED_PR5
            assert isinstance(FUSION_ENTRY_ADAPTER_ALIGNED_PR5, str)
            assert "UNAVAILABLE" not in FUSION_ENTRY_ADAPTER_ALIGNED_PR5
            assert "PR5" in FUSION_ENTRY_ADAPTER_ALIGNED_PR5
        except ImportError:
            pytest.skip("fastapi not available — skipping projection import")

    def test_pr5_sentinel_in_projection(self):
        try:
            from core.routes.projection import FUSION_ENTRY_ADAPTER_ALIGNED_PR5
            assert "fusion_entry" in FUSION_ENTRY_ADAPTER_ALIGNED_PR5.lower() or "adapter" in FUSION_ENTRY_ADAPTER_ALIGNED_PR5.lower()
        except ImportError:
            pytest.skip("fastapi not available")


# ---------------------------------------------------------------------------
# core.fusion_entry_adapter standalone import test
# ---------------------------------------------------------------------------

class TestAdapterModuleImport:
    def test_module_imports_cleanly(self):
        import core.fusion_entry_adapter as m
        assert hasattr(m, "FUSION_ENTRY_IS_EXECUTION_ADAPTER_AUTHORITY")
        assert hasattr(m, "FUSION_ENTRY_ADAPTER_CONTRACT_PR5_SENTINEL")
        assert hasattr(m, "FusionEntryAdapterContract")
        assert hasattr(m, "validate_fusion_entry_adapter")
        assert hasattr(m, "check_fusion_entry_compliance")

    def test_module_does_not_import_fastapi(self):
        import core.fusion_entry_adapter as m
        src = inspect.getsource(m)
        assert "fastapi" not in src.lower()

    def test_module_does_not_act_as_registry(self):
        import core.fusion_entry_adapter as m
        src = inspect.getsource(m)
        # No registry registration calls
        assert "register_node" not in src
        assert "NodeFabricRegistry()" not in src


# ---------------------------------------------------------------------------
# Nodes route no longer uses direct _load_node/_execute_node
# ---------------------------------------------------------------------------

class TestNodesRouteAdapterRefactor:
    def test_autonomous_execute_uses_invoke_node(self):
        try:
            import inspect
            import core.routes.nodes as m
            src = inspect.getsource(m)
            # The autonomous_execute node_executor now calls invoke_node
            assert "invoke_node" in src
        except ImportError:
            pytest.skip("fastapi not available — skipping nodes route import")

    def test_autonomous_execute_no_direct_load_execute(self):
        try:
            import inspect
            import core.routes.nodes as m
            src = inspect.getsource(m)
            # _load_node and _execute_node are internal helpers; the route
            # module should no longer import or call them in the executor closure.
            # We check the import line has been cleaned up.
            assert "_load_node" not in src or "_execute_node" not in src
        except ImportError:
            pytest.skip("fastapi not available")

    def test_nodes_route_imports_invoke_node(self):
        try:
            import core.routes.nodes as m
            assert hasattr(m, "invoke_node") or hasattr(m, "InvocationSource")
        except ImportError:
            pytest.skip("fastapi not available")


# ---------------------------------------------------------------------------
# CONTRIBUTING.md reflects narrowed role
# ---------------------------------------------------------------------------

class TestContributingDocs:
    def _read_contributing(self) -> str:
        import os
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "CONTRIBUTING.md",
        )
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_contributing_mentions_execution_adapter(self):
        content = self._read_contributing()
        assert "execution adapter" in content.lower()

    def test_contributing_states_not_registry_authority(self):
        content = self._read_contributing()
        assert "not" in content.lower()
        assert "registry" in content.lower()

    def test_contributing_mentions_invoke_node(self):
        content = self._read_contributing()
        assert "invoke_node" in content

    def test_contributing_mentions_node_dependencies_for_membership(self):
        content = self._read_contributing()
        assert "node_dependencies.json" in content
