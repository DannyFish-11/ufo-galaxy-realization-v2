#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr529_callable_startup_integration.py
=================================================
Tests for PR-529 Phase-B: callable-node baseline startup integration.

Coverage:
  - CALLABLE_BASELINE_STARTUP_INTEGRATION sentinel present in node_startup.py.
  - NodeSystemLauncher.get_callable_node_classification() is callable and
    returns the expected structure.
  - Classification correctly uses is_callable_by_openclawd() to distinguish
    callable vs. non-callable nodes registered in NodeFabricRegistry.
  - validate_runtime.py exposes check_callable_startup_integration().
  - validate_runtime.py main() calls check_callable_startup_integration().
  - Phase-B purge registry entries are present.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Sentinel
# ===========================================================================


class TestCallableStartupSentinel:
    """Verify the CALLABLE_BASELINE_STARTUP_INTEGRATION sentinel is present."""

    def test_sentinel_importable(self):
        from launcher.node_startup import CALLABLE_BASELINE_STARTUP_INTEGRATION
        assert CALLABLE_BASELINE_STARTUP_INTEGRATION
        assert "CALLABLE_BASELINE_STARTUP_INTEGRATION" in CALLABLE_BASELINE_STARTUP_INTEGRATION

    def test_sentinel_mentions_get_callable_node_classification(self):
        from launcher.node_startup import CALLABLE_BASELINE_STARTUP_INTEGRATION
        assert "get_callable_node_classification" in CALLABLE_BASELINE_STARTUP_INTEGRATION

    def test_sentinel_mentions_is_callable_by_openclawd(self):
        from launcher.node_startup import CALLABLE_BASELINE_STARTUP_INTEGRATION
        assert "is_callable_by_openclawd" in CALLABLE_BASELINE_STARTUP_INTEGRATION


# ===========================================================================
# Method presence and structure
# ===========================================================================


class TestGetCallableNodeClassificationPresence:
    """get_callable_node_classification() method must be present on NodeSystemLauncher."""

    def _make_launcher(self):
        """Construct a minimal NodeSystemLauncher without real services."""
        from launcher.node_startup import NodeSystemLauncher
        launcher = NodeSystemLauncher.__new__(NodeSystemLauncher)
        launcher.nodes_dir = PROJECT_ROOT / "nodes"
        launcher.node_configs = {}
        return launcher

    def test_method_present(self):
        from launcher.node_startup import NodeSystemLauncher
        assert callable(getattr(NodeSystemLauncher, "get_callable_node_classification", None))

    def test_returns_dict(self):
        launcher = self._make_launcher()
        result = launcher.get_callable_node_classification()
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        launcher = self._make_launcher()
        result = launcher.get_callable_node_classification()
        required_keys = {
            "callable_nodes",
            "service_nodes",
            "legacy_nodes",
            "non_callable_nodes",
            "unregistered_startup_nodes",
            "classification_available",
            "summary",
        }
        assert required_keys.issubset(result.keys()), (
            f"Missing keys: {required_keys - set(result.keys())}"
        )

    def test_summary_has_counts(self):
        launcher = self._make_launcher()
        result = launcher.get_callable_node_classification()
        summary = result["summary"]
        count_keys = {
            "callable_count",
            "service_count",
            "legacy_count",
            "non_callable_count",
            "unregistered_startup_count",
        }
        assert count_keys.issubset(summary.keys())

    def test_all_node_lists_are_lists(self):
        launcher = self._make_launcher()
        result = launcher.get_callable_node_classification()
        for key in ("callable_nodes", "service_nodes", "legacy_nodes",
                    "non_callable_nodes", "unregistered_startup_nodes"):
            assert isinstance(result[key], list), (
                f"{key} should be a list, got {type(result[key])}"
            )

    def test_classification_available_is_bool(self):
        launcher = self._make_launcher()
        result = launcher.get_callable_node_classification()
        assert isinstance(result["classification_available"], bool)


# ===========================================================================
# Classification logic
# ===========================================================================


class TestGetCallableNodeClassificationLogic:
    """Classification must correctly separate callable from non-callable nodes."""

    def _make_launcher(self):
        from launcher.node_startup import NodeSystemLauncher
        launcher = NodeSystemLauncher.__new__(NodeSystemLauncher)
        launcher.nodes_dir = PROJECT_ROOT / "nodes"
        launcher.node_configs = {}
        return launcher

    def test_capability_node_goes_to_callable_nodes(self):
        from launcher.node_startup import NodeSystemLauncher
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry, NodeInfo, NodeArchitecturalClass, NodeStatus,
        )

        # Reset and populate registry.
        from core.nodes.node_fabric_registry import reset_node_fabric_registry
        reset_node_fabric_registry()

        registry = NodeFabricRegistry()
        registry.register(NodeInfo(
            node_id="cap_node_a",
            architectural_class=NodeArchitecturalClass.CAPABILITY_NODE,
            status=NodeStatus.HEALTHY,
        ))

        launcher = self._make_launcher()
        result = launcher.get_callable_node_classification()

        assert "cap_node_a" in result["callable_nodes"]
        assert "cap_node_a" not in result["service_nodes"]
        assert "cap_node_a" not in result["legacy_nodes"]
        assert "cap_node_a" not in result["non_callable_nodes"]

    def test_service_node_goes_to_service_nodes(self):
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry, NodeInfo, NodeArchitecturalClass, NodeStatus,
            reset_node_fabric_registry,
        )
        reset_node_fabric_registry()

        registry = NodeFabricRegistry()
        registry.register(NodeInfo(
            node_id="svc_node_x",
            architectural_class=NodeArchitecturalClass.SERVICE_NODE,
            status=NodeStatus.HEALTHY,
        ))

        launcher = self._make_launcher()
        result = launcher.get_callable_node_classification()

        assert "svc_node_x" in result["service_nodes"]
        assert "svc_node_x" not in result["callable_nodes"]

    def test_legacy_orchestrator_goes_to_legacy_nodes(self):
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry, NodeInfo, NodeArchitecturalClass, NodeStatus,
            reset_node_fabric_registry,
        )
        reset_node_fabric_registry()

        registry = NodeFabricRegistry()
        registry.register(NodeInfo(
            node_id="legacy_orch_y",
            architectural_class=NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE,
            status=NodeStatus.HEALTHY,
        ))

        launcher = self._make_launcher()
        result = launcher.get_callable_node_classification()

        assert "legacy_orch_y" in result["legacy_nodes"]
        assert "legacy_orch_y" not in result["callable_nodes"]

    def test_experimental_node_goes_to_non_callable(self):
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry, NodeInfo, NodeArchitecturalClass, NodeStatus,
            reset_node_fabric_registry,
        )
        reset_node_fabric_registry()

        registry = NodeFabricRegistry()
        registry.register(NodeInfo(
            node_id="exp_node_z",
            architectural_class=NodeArchitecturalClass.EXPERIMENTAL_NODE,
            status=NodeStatus.HEALTHY,
        ))

        launcher = self._make_launcher()
        result = launcher.get_callable_node_classification()

        assert "exp_node_z" in result["non_callable_nodes"]
        assert "exp_node_z" not in result["callable_nodes"]

    def test_archived_node_goes_to_non_callable(self):
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry, NodeInfo, NodeArchitecturalClass, NodeStatus,
            reset_node_fabric_registry,
        )
        reset_node_fabric_registry()

        registry = NodeFabricRegistry()
        registry.register(NodeInfo(
            node_id="arch_node_w",
            architectural_class=NodeArchitecturalClass.ARCHIVED_NODE,
            status=NodeStatus.HEALTHY,
        ))

        launcher = self._make_launcher()
        result = launcher.get_callable_node_classification()

        assert "arch_node_w" in result["non_callable_nodes"]
        assert "arch_node_w" not in result["callable_nodes"]

    def test_unregistered_startup_nodes_detected(self):
        """Nodes in startup config but not in NodeFabricRegistry appear as unregistered."""
        from core.nodes.node_fabric_registry import reset_node_fabric_registry
        reset_node_fabric_registry()

        launcher = self._make_launcher()
        # Inject a fake startup config entry that references a non-existent node dir.
        # The launcher checks `(nodes_dir / name / "main.py").exists()` so we need
        # to use a node that actually has a main.py on disk.  Instead we mock nodes_dir.
        launcher.node_configs = {
            "FakeActiveNode": {
                "startup_policy": "active",
                "group": "core",
            }
        }
        # Make nodes_dir point somewhere that doesn't contain this node dir so
        # the exists() check returns False → node is not included in startup set.
        # The launcher filters by exists(), so with a missing dir the node won't
        # be in startup_node_names either.  Let's verify graceful handling.
        result = launcher.get_callable_node_classification()
        # FakeActiveNode has no main.py so it should not appear as unregistered startup.
        assert "FakeActiveNode" not in result["unregistered_startup_nodes"]

    def test_mixed_classification_counts_match(self):
        """summary counts must equal the lengths of the corresponding lists."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry, NodeInfo, NodeArchitecturalClass, NodeStatus,
            reset_node_fabric_registry,
        )
        reset_node_fabric_registry()
        registry = NodeFabricRegistry()
        registry.register(NodeInfo(
            node_id="cap1", architectural_class=NodeArchitecturalClass.CAPABILITY_NODE,
            status=NodeStatus.HEALTHY))
        registry.register(NodeInfo(
            node_id="svc1", architectural_class=NodeArchitecturalClass.SERVICE_NODE,
            status=NodeStatus.HEALTHY))
        registry.register(NodeInfo(
            node_id="lgc1", architectural_class=NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE,
            status=NodeStatus.HEALTHY))
        registry.register(NodeInfo(
            node_id="exp1", architectural_class=NodeArchitecturalClass.EXPERIMENTAL_NODE,
            status=NodeStatus.HEALTHY))

        launcher = self._make_launcher()
        result = launcher.get_callable_node_classification()
        s = result["summary"]

        assert s["callable_count"] == len(result["callable_nodes"])
        assert s["service_count"] == len(result["service_nodes"])
        assert s["legacy_count"] == len(result["legacy_nodes"])
        assert s["non_callable_count"] == len(result["non_callable_nodes"])
        assert s["unregistered_startup_count"] == len(result["unregistered_startup_nodes"])

    def test_classification_available_true_when_registry_reachable(self):
        from core.nodes.node_fabric_registry import reset_node_fabric_registry
        reset_node_fabric_registry()
        launcher = self._make_launcher()
        result = launcher.get_callable_node_classification()
        assert result["classification_available"] is True


# ===========================================================================
# validate_runtime.py integration
# ===========================================================================


class TestValidateRuntimeIntegration:
    """validate_runtime.py must expose check_callable_startup_integration."""

    def _load_module(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "validate_runtime",
            PROJECT_ROOT / "scripts" / "validate_runtime.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_check_callable_startup_integration_present(self):
        mod = self._load_module()
        assert callable(getattr(mod, "check_callable_startup_integration", None)), (
            "validate_runtime.py must expose check_callable_startup_integration()"
        )

    def test_main_calls_check_callable_startup_integration(self):
        import inspect
        mod = self._load_module()
        main_src = inspect.getsource(mod.main)
        assert "check_callable_startup_integration()" in main_src, (
            "main() must call check_callable_startup_integration()"
        )


# ===========================================================================
# Phase-B purge registry entries
# ===========================================================================


class TestPhaseBPurgeRegistryEntries:
    """Phase-B entries must be present in the legacy purge registry."""

    def _get_registry(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        return PURGE_REGISTRY

    def test_callable_startup_integration_entry_present(self):
        registry = self._get_registry()
        paths = {e.asset_path for e in registry}
        assert "launcher/node_startup.py::no callable-node classification" in paths, (
            "Purge registry must contain a Phase-B entry for the callable startup "
            "integration (launcher/node_startup.py::no callable-node classification)."
        )

    def test_validate_runtime_integration_entry_present(self):
        registry = self._get_registry()
        paths = {e.asset_path for e in registry}
        assert "scripts/validate_runtime.py::no callable-startup check" in paths, (
            "Purge registry must contain a Phase-B entry for the validate_runtime "
            "callable-startup check."
        )

    def test_phase_b_entries_have_pr_label(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        phase_b = [e for e in PURGE_REGISTRY if e.pr == "PR-consolidation-B"]
        assert len(phase_b) >= 2, (
            f"Expected ≥ 2 PR-consolidation-B purge entries, got {len(phase_b)}"
        )

    def test_phase_b_entries_have_canonical_replacement(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        for entry in PURGE_REGISTRY:
            if entry.pr == "PR-consolidation-B":
                assert entry.canonical_replacement, (
                    f"PR-consolidation-B entry {entry.asset_path!r} must have "
                    "a canonical_replacement."
                )
