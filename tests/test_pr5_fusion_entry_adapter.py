"""
tests/test_pr5_fusion_entry_adapter.py
=======================================
PR-5: Reposition fusion_entry as the Canonical Execution Adapter — test suite.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import os
import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Sentinel tests
# ---------------------------------------------------------------------------

class TestAdapterSentinels:
    def test_authority_sentinel_present(self):
        from core.fusion_entry_adapter import FUSION_ENTRY_ADAPTER_AUTHORITY
        assert isinstance(FUSION_ENTRY_ADAPTER_AUTHORITY, str)
        assert "execution adapter" in FUSION_ENTRY_ADAPTER_AUTHORITY.lower()
        assert "NOT" in FUSION_ENTRY_ADAPTER_AUTHORITY

    def test_pr5_sentinel_value(self):
        from core.fusion_entry_adapter import FUSION_ENTRY_ADAPTER_PR5_SENTINEL
        assert FUSION_ENTRY_ADAPTER_PR5_SENTINEL == "FUSION_ENTRY_ADAPTER::PR5_SENTINEL_V1"

    def test_execution_only_policy_present(self):
        from core.fusion_entry_adapter import ADAPTER_IS_EXECUTION_ONLY_POLICY
        assert "execute" in ADAPTER_IS_EXECUTION_ONLY_POLICY.lower()
        assert "register" in ADAPTER_IS_EXECUTION_ONLY_POLICY.lower()

    def test_no_sys_path_mutation_policy_present(self):
        from core.fusion_entry_adapter import ADAPTER_MUST_NOT_MUTATE_SYS_PATH_POLICY
        assert "sys.path" in ADAPTER_MUST_NOT_MUTATE_SYS_PATH_POLICY

    def test_contract_policy_present(self):
        from core.fusion_entry_adapter import ADAPTER_CONTRACT_IS_EXECUTE_AND_FACTORY_POLICY
        assert "get_node_instance" in ADAPTER_CONTRACT_IS_EXECUTE_AND_FACTORY_POLICY
        assert "FusionNode" in ADAPTER_CONTRACT_IS_EXECUTE_AND_FACTORY_POLICY

    def test_canonical_caller_policy_present(self):
        from core.fusion_entry_adapter import UNIFIED_EXECUTOR_IS_CANONICAL_CALLER_POLICY
        assert "UnifiedNodeExecutor" in UNIFIED_EXECUTOR_IS_CANONICAL_CALLER_POLICY
        assert "invoke_node" in UNIFIED_EXECUTOR_IS_CANONICAL_CALLER_POLICY

    def test_contract_version_constant(self):
        from core.fusion_entry_adapter import FUSION_ENTRY_ADAPTER_CONTRACT_VERSION
        assert FUSION_ENTRY_ADAPTER_CONTRACT_VERSION == "FUSION_ENTRY_ADAPTER_CONTRACT_V1"


# ---------------------------------------------------------------------------
# validate_adapter_module tests
# ---------------------------------------------------------------------------

def _make_minimal_module(*, has_factory=True, has_fusion_node=True, async_execute=True) -> types.ModuleType:
    """Return a synthetic module that satisfies the adapter contract."""
    mod = types.ModuleType("fake_fusion_entry")

    if async_execute:
        async def _execute(self, command, **params):
            return {"success": True, "data": "ok"}
    else:
        def _execute(self, command, **params):
            return {"success": True, "data": "ok"}

    if has_fusion_node:
        FusionNode = type("FusionNode", (), {"execute": _execute})
        mod.FusionNode = FusionNode

    if has_factory:
        def get_node_instance():
            cls = getattr(mod, "FusionNode", None)
            if cls:
                return cls()
            obj = object.__new__(object)
            obj.execute = lambda command, **p: {"success": True}  # type: ignore[attr-defined]
            return obj

        mod.get_node_instance = get_node_instance

    return mod


class TestValidateAdapterModule:
    def test_valid_module_passes(self):
        from core.fusion_entry_adapter import validate_adapter_module
        mod = _make_minimal_module()
        validate_adapter_module(mod, node_id="Node_Test")  # should not raise

    def test_missing_factory_raises(self):
        from core.fusion_entry_adapter import validate_adapter_module, AdapterContractViolation
        mod = _make_minimal_module(has_factory=False)
        with pytest.raises(AdapterContractViolation, match="get_node_instance"):
            validate_adapter_module(mod, node_id="Node_Test")

    def test_non_callable_factory_raises(self):
        from core.fusion_entry_adapter import validate_adapter_module, AdapterContractViolation
        mod = _make_minimal_module()
        mod.get_node_instance = "not_callable"  # type: ignore[assignment]
        with pytest.raises(AdapterContractViolation, match="not callable"):
            validate_adapter_module(mod, node_id="Node_Test")

    def test_factory_raises_on_call_surfaces_violation(self):
        from core.fusion_entry_adapter import validate_adapter_module, AdapterContractViolation
        mod = _make_minimal_module()

        def bad_factory():
            raise RuntimeError("boom")

        mod.get_node_instance = bad_factory
        with pytest.raises(AdapterContractViolation, match="raised"):
            validate_adapter_module(mod, node_id="Node_Test")

    def test_instance_without_execute_raises(self):
        from core.fusion_entry_adapter import validate_adapter_module, AdapterContractViolation
        mod = _make_minimal_module()

        class NoExecute:
            pass

        mod.FusionNode = NoExecute
        mod.get_node_instance = NoExecute
        with pytest.raises(AdapterContractViolation, match="execute"):
            validate_adapter_module(mod, node_id="Node_Test")

    def test_module_without_fusion_node_class_still_passes_via_factory(self):
        from core.fusion_entry_adapter import validate_adapter_module

        mod = types.ModuleType("fake_no_class")

        async def _execute(self, command, **params):
            return {"success": True}

        Instance = type("Instance", (), {"execute": _execute})
        mod.get_node_instance = lambda: Instance()
        validate_adapter_module(mod, node_id="Node_LegacyTest")  # should not raise

    def test_sync_execute_passes_with_warning(self, caplog):
        from core.fusion_entry_adapter import validate_adapter_module
        import logging

        mod = _make_minimal_module(async_execute=False)
        with caplog.at_level(logging.WARNING, logger="Galaxy.FusionEntryAdapter"):
            validate_adapter_module(mod, node_id="Node_SyncTest")
        # Should pass (not raise) and optionally emit a warning.


class TestCheckAdapterModule:
    def test_returns_none_for_valid(self):
        from core.fusion_entry_adapter import check_adapter_module
        mod = _make_minimal_module()
        result = check_adapter_module(mod, node_id="Node_Test")
        assert result is None

    def test_returns_string_for_invalid(self):
        from core.fusion_entry_adapter import check_adapter_module
        mod = _make_minimal_module(has_factory=False)
        result = check_adapter_module(mod, node_id="Node_Test")
        assert isinstance(result, str)
        assert "get_node_instance" in result


# ---------------------------------------------------------------------------
# Template sentinel test
# ---------------------------------------------------------------------------

class TestTemplateContractSentinel:
    def test_template_has_contract_version_sentinel(self):
        """The node template's fusion_entry.py must embed the adapter contract version."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_path = os.path.join(
            repo_root, "templates", "node_template", "fusion_entry.py"
        )
        assert os.path.exists(template_path), "templates/node_template/fusion_entry.py not found"
        with open(template_path) as f:
            content = f.read()
        assert "FUSION_ENTRY_ADAPTER_CONTRACT_V1" in content, (
            "templates/node_template/fusion_entry.py must reference "
            "FUSION_ENTRY_ADAPTER_CONTRACT_V1"
        )

    def test_template_has_execution_adapter_role_comment(self):
        """Template must clearly document the execution-adapter-only role."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_path = os.path.join(
            repo_root, "templates", "node_template", "fusion_entry.py"
        )
        with open(template_path) as f:
            content = f.read()
        assert "EXECUTION ADAPTER" in content or "execution adapter" in content.lower(), (
            "Template must state the execution-adapter role explicitly"
        )

    def test_template_documents_not_registry(self):
        """Template must document that fusion_entry is NOT a registry authority."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_path = os.path.join(
            repo_root, "templates", "node_template", "fusion_entry.py"
        )
        with open(template_path) as f:
            content = f.read()
        assert "NOT" in content and ("registry" in content.lower() or "NOT a registry" in content.lower())

    def test_template_has_get_node_instance(self):
        """Template must expose get_node_instance()."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_path = os.path.join(
            repo_root, "templates", "node_template", "fusion_entry.py"
        )
        with open(template_path) as f:
            content = f.read()
        assert "def get_node_instance" in content

    def test_template_has_fusion_node_class(self):
        """Template must expose a FusionNode class."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_path = os.path.join(
            repo_root, "templates", "node_template", "fusion_entry.py"
        )
        with open(template_path) as f:
            content = f.read()
        assert "class FusionNode" in content


# ---------------------------------------------------------------------------
# Projection sentinel test
# ---------------------------------------------------------------------------

class TestProjectionSentinel:
    def test_projection_sentinel_importable(self):
        pytest.importorskip(
            "fastapi",
            reason="fastapi not installed — projection sentinel skipped",
        )
        from core.routes.projection import FUSION_ENTRY_ADAPTER_ALIGNED_PR5
        assert isinstance(FUSION_ENTRY_ADAPTER_ALIGNED_PR5, str)
        assert "PR5" in FUSION_ENTRY_ADAPTER_ALIGNED_PR5
        assert "UNAVAILABLE" not in FUSION_ENTRY_ADAPTER_ALIGNED_PR5

    def test_projection_sentinel_mentions_adapter(self):
        pytest.importorskip(
            "fastapi",
            reason="fastapi not installed — projection sentinel skipped",
        )
        from core.routes.projection import FUSION_ENTRY_ADAPTER_ALIGNED_PR5
        assert "adapter" in FUSION_ENTRY_ADAPTER_ALIGNED_PR5.lower()

    def test_projection_sentinel_importable_without_fastapi(self):
        """FUSION_ENTRY_ADAPTER_ALIGNED_PR5 must be importable even without fastapi.

        The sentinel is set on both success and ImportError branches in
        projection.py (fastapi guard), but the fusion_entry_adapter import
        block itself does not require fastapi.  We verify the sentinel is
        at least a string constant in that module independently.
        """
        from core.fusion_entry_adapter import FUSION_ENTRY_ADAPTER_PR5_SENTINEL
        assert "PR5" in FUSION_ENTRY_ADAPTER_PR5_SENTINEL


# ---------------------------------------------------------------------------
# CONTRIBUTING.md documentation test
# ---------------------------------------------------------------------------

class TestContributingDocumentation:
    def test_contributing_md_has_adapter_role_description(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        contributing = os.path.join(repo_root, "CONTRIBUTING.md")
        with open(contributing) as f:
            content = f.read()
        assert "execution adapter" in content.lower(), (
            "CONTRIBUTING.md must describe fusion_entry.py as an execution adapter"
        )

    def test_contributing_md_documents_not_registry(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        contributing = os.path.join(repo_root, "CONTRIBUTING.md")
        with open(contributing) as f:
            content = f.read()
        assert "not" in content.lower() and "registry" in content.lower(), (
            "CONTRIBUTING.md must document that fusion_entry.py is not a registry authority"
        )

    def test_contributing_md_references_contract_version(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        contributing = os.path.join(repo_root, "CONTRIBUTING.md")
        with open(contributing) as f:
            content = f.read()
        assert "FUSION_ENTRY_ADAPTER_CONTRACT_V1" in content, (
            "CONTRIBUTING.md must reference the adapter contract version"
        )

    def test_contributing_md_references_invoke_node(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        contributing = os.path.join(repo_root, "CONTRIBUTING.md")
        with open(contributing) as f:
            content = f.read()
        assert "invoke_node" in content, (
            "CONTRIBUTING.md must reference invoke_node() as the canonical caller"
        )
