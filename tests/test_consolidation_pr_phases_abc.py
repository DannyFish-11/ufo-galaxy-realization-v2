#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_consolidation_pr_phases_abc.py
==========================================
Regression tests for the main-branch capability and runtime consolidation PR.

Coverage per phase:

Phase A — Capability + Tooling consolidation
  - A1: ``CapabilityRegistry`` in ``core/hybrid_executor.py`` renamed to
        ``AppExecutionCapabilityRegistry``; sentinel present.
  - A2: ``OpenClawd._collect_tools()`` includes ``CapabilitySource.NODE`` in the
        primary resolver call; always collects node tools from resolver.
  - A3: ``Scheduler.inject_mcp_tools()`` emits canonical ``mcp__`` prefix;
        ``inject_skill_tools()`` emits canonical ``skill__`` prefix;
        dispatch routes canonical prefixes first, legacy as compat aliases.

Phase B — Runtime acceptance + callable-node baseline
  - B1: ``core.callable_node_baseline`` module: sentinel, CALLABLE_ARCHITECTURAL_CLASSES,
        ``is_callable_by_openclawd()``, ``get_callable_node_names()``.
  - B2: ``scripts/validate_runtime.py`` exposes ``check_runtime_acceptance()`` and
        ``check_callable_node_baseline()`` functions.
  - B3: ``NodeArchitecturalClass`` enum accessible; ``_CAPABILITY_SYNC_ELIGIBLE`` is
        the authority set that matches the baseline.

Phase C — Legacy first-round reduction
  - C1: ``core/legacy_purge_registry.py`` contains Phase-A entries for the renames
        and normalizations.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Phase A — Capability + Tooling consolidation
# ===========================================================================


class TestPhaseA_HybridExecutorRename:
    """A1: CapabilityRegistry in core/hybrid_executor.py renamed."""

    def test_sentinel_present(self):
        from core.hybrid_executor import APP_EXECUTION_CAPABILITY_REGISTRY_RENAMED
        assert APP_EXECUTION_CAPABILITY_REGISTRY_RENAMED
        assert "AppExecutionCapabilityRegistry" in APP_EXECUTION_CAPABILITY_REGISTRY_RENAMED

    def test_app_execution_class_exists(self):
        from core.hybrid_executor import AppExecutionCapabilityRegistry
        inst = AppExecutionCapabilityRegistry()
        # Should still behave as the old CapabilityRegistry did.
        assert hasattr(inst, "register")
        assert hasattr(inst, "get")
        assert hasattr(inst, "get_preferred_levels")
        assert hasattr(inst, "list_apps")

    def test_old_name_gone(self):
        """The bare name 'CapabilityRegistry' must no longer be exported from
        core.hybrid_executor (it would collide with the canonical registry)."""
        import core.hybrid_executor as mod
        # AppExecutionCapabilityRegistry must exist.
        assert hasattr(mod, "AppExecutionCapabilityRegistry")
        # The old unqualified 'CapabilityRegistry' must NOT exist as a module-
        # level name in hybrid_executor to avoid import confusion.
        assert not hasattr(mod, "CapabilityRegistry"), (
            "CapabilityRegistry must not be a top-level name in core.hybrid_executor; "
            "it was renamed to AppExecutionCapabilityRegistry."
        )

    def test_arbiter_uses_renamed_class(self):
        from core.hybrid_executor import HybridExecutionArbiter, AppExecutionCapabilityRegistry
        arbiter = HybridExecutionArbiter()
        assert isinstance(arbiter.registry, AppExecutionCapabilityRegistry)

    def test_defaults_still_registered(self):
        """The renamed registry still registers default apps correctly."""
        from core.hybrid_executor import AppExecutionCapabilityRegistry
        reg = AppExecutionCapabilityRegistry()
        # Default apps must still be present.
        assert reg.get("com.tencent.mm") is not None
        assert reg.get("system_shell") is not None
        assert reg.get("file_manager") is not None

    def test_register_and_get_round_trip(self):
        """register() and get() still work after the rename."""
        from core.hybrid_executor import AppExecutionCapabilityRegistry, AppCapability, ExecutionLevel
        reg = AppExecutionCapabilityRegistry()
        cap = AppCapability(
            app_id="test.app.roundtrip",
            a2a_endpoint="http://localhost:9999",
            a2a_actions=["ping"],
        )
        reg.register(cap)
        fetched = reg.get("test.app.roundtrip")
        assert fetched is not None
        assert fetched.a2a_endpoint == "http://localhost:9999"
        assert "ping" in fetched.a2a_actions


class TestPhaseA_OpenClawdToolCollection:
    """A2: _collect_tools() includes NODE in primary resolver call."""

    def test_collect_tools_method_present(self):
        from core.openclawd import OpenClawd
        assert callable(getattr(OpenClawd, "_collect_tools", None))

    def test_node_source_in_primary_resolver_call(self):
        """Verify the source code includes CapabilitySource.NODE in the Layer 1
        resolver call (structural inspection)."""
        import inspect
        from core.openclawd import OpenClawd
        src = inspect.getsource(OpenClawd._collect_tools)
        # Phase-A: NODE must be listed alongside MCP and SKILL in the first
        # resolver.collect_tool_schemas(...) call.
        assert "CapabilitySource.NODE" in src, (
            "OpenClawd._collect_tools() must include CapabilitySource.NODE in the "
            "primary CapabilityResolver call (Phase-A consolidation)."
        )

    def test_node_tools_collected_from_resolver_when_resolver_has_nodes(self):
        """When the resolver cache already contains NODE entries, they appear in
        the output of _collect_tools() via the primary Layer 1 path."""
        from core.agent.capability_registry import CapabilityRegistry
        from core.openclawd import OpenClawd

        # Reset registry state.
        reg = CapabilityRegistry.get_instance()
        reg._items.clear()

        # Inject a synthetic node capability.
        from core.agent.capability_registry import CapabilityItem
        reg.register(CapabilityItem(
            name="node__test_node__ping",
            description="Test node ping",
            source="node",
            source_id="test_node",
            parameters={"type": "object", "properties": {}},
        ))

        # Warm the resolver cache.
        try:
            from core.unified.capability_resolver import get_capability_resolver, reset_capability_resolver
            reset_capability_resolver()
            resolver = get_capability_resolver()
            resolver.invalidate_cache()
        except Exception:
            pytest.skip("capability_resolver not available in this environment")

        oc = OpenClawd.__new__(OpenClawd)
        oc._initialized = False
        oc._tool_permission_checker = None
        oc._node_id_to_key = {}
        oc._capability_dispatcher = None

        tools = oc._collect_tools()
        names = {t["function"]["name"] for t in tools}
        assert "node__test_node__ping" in names, (
            "Node tools cached in CapabilityResolver must appear in _collect_tools() output."
        )

    def test_node_tools_collected_even_when_sync_count_is_zero(self):
        """Node tools already in the registry appear even when
        NodeFabricRegistry.sync_capabilities_to_registry() returns 0."""
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        from core.openclawd import OpenClawd

        reg = CapabilityRegistry.get_instance()
        reg._items.clear()
        reg.register(CapabilityItem(
            name="node__stable_node__run",
            description="Already synced node",
            source="node",
            source_id="stable_node",
            parameters={"type": "object", "properties": {}},
        ))

        try:
            from core.unified.capability_resolver import get_capability_resolver, reset_capability_resolver
            reset_capability_resolver()
            resolver = get_capability_resolver()
            resolver.invalidate_cache()
        except Exception:
            pytest.skip("capability_resolver not available in this environment")

        # Patch NodeFabricRegistry.sync_capabilities_to_registry to return 0.
        try:
            from core.nodes.node_fabric_registry import get_node_fabric_registry
            fabric = get_node_fabric_registry()
        except Exception:
            pytest.skip("node_fabric_registry not available")

        with patch.object(fabric, "sync_capabilities_to_registry", return_value=0):
            oc = OpenClawd.__new__(OpenClawd)
            oc._initialized = False
            oc._tool_permission_checker = None
            oc._node_id_to_key = {}
            oc._capability_dispatcher = None
            tools = oc._collect_tools()

        names = {t["function"]["name"] for t in tools}
        assert "node__stable_node__run" in names, (
            "Node tools already in the registry must appear in _collect_tools() "
            "even when sync_capabilities_to_registry() returns 0 (Phase-A fix)."
        )


class TestPhaseA_SchedulerToolNaming:
    """A3: Scheduler emits canonical prefixes; legacy prefixes are compat aliases."""

    def test_canonical_tool_naming_sentinel_present(self):
        from core.scheduler import SCHEDULER_CANONICAL_TOOL_NAMING_PRIMARY
        assert SCHEDULER_CANONICAL_TOOL_NAMING_PRIMARY
        assert "mcp__" in SCHEDULER_CANONICAL_TOOL_NAMING_PRIMARY
        assert "skill__" in SCHEDULER_CANONICAL_TOOL_NAMING_PRIMARY

    def test_inject_mcp_tools_emits_canonical_prefix(self):
        """inject_mcp_tools() must use ``mcp__<server>__<tool>`` naming."""
        from core.scheduler import AutonomousScheduler

        sched = AutonomousScheduler.__new__(AutonomousScheduler)
        sched.tools_cache = []

        class _FakeStatus:
            RUNNING = "running"

        class _FakeTool:
            name = "do_something"
            description = "desc"
            inputSchema = None

        class _FakeServer:
            status = "running"
            name = "MyServer"
            tools = [_FakeTool()]

        mock_loader = MagicMock()
        mock_loader.servers = {"abcd1234": _FakeServer()}

        with patch("core.mcp_loader.mcp_loader", mock_loader), \
             patch("core.mcp_loader.MCPServerStatus", _FakeStatus):
            sched.inject_mcp_tools()

        names = [t["function"]["name"] for t in sched.tools_cache]
        assert len(names) == 1
        assert names[0] == "mcp__abcd1234__do_something", (
            f"Expected canonical 'mcp__abcd1234__do_something', got {names[0]!r}"
        )
        # Ensure the legacy single-underscore form is NOT in the cache.
        assert not any(n.startswith("mcp_abcd1234_") for n in names), (
            "Legacy mcp_ prefix must NOT appear in inject_mcp_tools() output."
        )

    def test_inject_skill_tools_emits_canonical_prefix(self):
        """inject_skill_tools() must use ``skill__<id>`` naming."""
        from core.scheduler import AutonomousScheduler

        sched = AutonomousScheduler.__new__(AutonomousScheduler)
        sched.tools_cache = []

        mock_loader = MagicMock()
        mock_loader.list_skills.return_value = [
            {"name": "hello_skill", "description": "A hello skill", "params_schema": None}
        ]

        with patch("core.skill_loader.skill_loader", mock_loader):
            sched.inject_skill_tools()

        names = [t["function"]["name"] for t in sched.tools_cache]
        assert len(names) == 1
        assert names[0] == "skill__hello_skill", (
            f"Expected canonical 'skill__hello_skill', got {names[0]!r}"
        )
        assert not any(n.startswith("skill_hello") and not n.startswith("skill__") for n in names)

    @pytest.mark.asyncio
    async def test_dispatch_handles_canonical_mcp_prefix(self):
        """Dispatch routes canonical mcp__ prefix to _exec_mcp_tool."""
        from core.scheduler import AutonomousScheduler

        sched = AutonomousScheduler.__new__(AutonomousScheduler)
        sched._exec_mcp_tool = AsyncMock(return_value='{"result":"ok"}')

        result = await sched._execute_tool(
            function_name="mcp__srv01__screenshot",
            args={},
            context={},
        )
        sched._exec_mcp_tool.assert_called_once_with("mcp__srv01__screenshot", {})

    @pytest.mark.asyncio
    async def test_dispatch_handles_canonical_skill_prefix(self):
        """Dispatch routes canonical skill__ prefix to _exec_skill_tool."""
        from core.scheduler import AutonomousScheduler

        sched = AutonomousScheduler.__new__(AutonomousScheduler)
        sched._exec_skill_tool = AsyncMock(return_value='{"result":"ok"}')

        result = await sched._execute_tool(
            function_name="skill__my_skill",
            args={},
            context={},
        )
        sched._exec_skill_tool.assert_called_once_with("skill__my_skill", {})

    @pytest.mark.asyncio
    async def test_dispatch_handles_canonical_node_prefix(self):
        """Dispatch routes canonical node__ prefix to executor."""
        from core.scheduler import AutonomousScheduler

        sched = AutonomousScheduler.__new__(AutonomousScheduler)

        mock_executor = AsyncMock(return_value={"status": "ok"})

        result = await sched._execute_tool(
            function_name="node__node_01__ping",
            args={},
            context={"executor": mock_executor},
        )
        mock_executor.assert_called_once_with("node_01", "ping", {})

    @pytest.mark.asyncio
    async def test_legacy_mcp_prefix_still_dispatches(self):
        """Legacy mcp_ prefix still dispatches (compat alias)."""
        from core.scheduler import AutonomousScheduler

        sched = AutonomousScheduler.__new__(AutonomousScheduler)
        sched._exec_mcp_tool = AsyncMock(return_value='{"result":"legacy_ok"}')

        await sched._execute_tool(
            function_name="mcp_abcd1234_screenshot",
            args={},
            context={},
        )
        sched._exec_mcp_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_legacy_skill_prefix_still_dispatches(self):
        """Legacy skill_ prefix still dispatches (compat alias)."""
        from core.scheduler import AutonomousScheduler

        sched = AutonomousScheduler.__new__(AutonomousScheduler)
        sched._exec_skill_tool = AsyncMock(return_value='{"result":"legacy_ok"}')

        await sched._execute_tool(
            function_name="skill_some_skill",
            args={},
            context={},
        )
        sched._exec_skill_tool.assert_called_once()

    def test_exec_mcp_tool_canonical_parsing(self):
        """_exec_mcp_tool() correctly parses the canonical double-underscore form."""
        import inspect
        from core.scheduler import AutonomousScheduler
        src = inspect.getsource(AutonomousScheduler._exec_mcp_tool)
        # Must handle both mcp__ and mcp_ forms.
        assert "mcp__" in src
        assert 'split("__", 1)' in src or "split('__', 1)" in src

    def test_exec_skill_tool_canonical_parsing(self):
        """_exec_skill_tool() correctly parses the canonical double-underscore form."""
        import inspect
        from core.scheduler import AutonomousScheduler
        src = inspect.getsource(AutonomousScheduler._exec_skill_tool)
        assert "skill__" in src


# ===========================================================================
# Phase B — Runtime acceptance + callable-node baseline
# ===========================================================================


class TestPhaseB_CallableNodeBaseline:
    """B1: core.callable_node_baseline module contracts."""

    def test_sentinel_present(self):
        from core.callable_node_baseline import CALLABLE_NODE_BASELINE_ESTABLISHED
        assert CALLABLE_NODE_BASELINE_ESTABLISHED
        assert "CALLABLE_NODE_BASELINE" in CALLABLE_NODE_BASELINE_ESTABLISHED

    def test_callable_architectural_classes_non_empty(self):
        from core.callable_node_baseline import CALLABLE_ARCHITECTURAL_CLASSES
        assert len(CALLABLE_ARCHITECTURAL_CLASSES) >= 1

    def test_capability_node_is_callable(self):
        from core.callable_node_baseline import is_callable_by_openclawd
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        assert is_callable_by_openclawd(NodeArchitecturalClass.CAPABILITY_NODE) is True

    def test_service_node_not_callable(self):
        from core.callable_node_baseline import is_callable_by_openclawd
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        assert is_callable_by_openclawd(NodeArchitecturalClass.SERVICE_NODE) is False

    def test_legacy_orchestrator_not_callable(self):
        from core.callable_node_baseline import is_callable_by_openclawd
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        assert is_callable_by_openclawd(NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE) is False

    def test_experimental_node_not_callable(self):
        from core.callable_node_baseline import is_callable_by_openclawd
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        assert is_callable_by_openclawd(NodeArchitecturalClass.EXPERIMENTAL_NODE) is False

    def test_archived_node_not_callable(self):
        from core.callable_node_baseline import is_callable_by_openclawd
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        assert is_callable_by_openclawd(NodeArchitecturalClass.ARCHIVED_NODE) is False

    def test_string_value_accepted(self):
        """is_callable_by_openclawd() accepts plain string values too."""
        from core.callable_node_baseline import is_callable_by_openclawd
        assert is_callable_by_openclawd("capability_node") is True
        assert is_callable_by_openclawd("service_node") is False

    def test_get_callable_node_names_returns_list(self):
        from core.callable_node_baseline import get_callable_node_names
        result = get_callable_node_names()
        assert isinstance(result, list)

    def test_get_callable_node_names_only_capability_nodes(self):
        """Only CAPABILITY_NODE nodes appear in the list."""
        from core.callable_node_baseline import get_callable_node_names, is_callable_by_openclawd
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry,
            NodeInfo,
            NodeArchitecturalClass,
            NodeStatus,
        )

        registry = get_node_fabric_registry()
        # Register a mix of callable and non-callable nodes.
        registry.register(NodeInfo(
            node_id="test_callable_node",
            architectural_class=NodeArchitecturalClass.CAPABILITY_NODE,
            status=NodeStatus.HEALTHY,
        ))
        registry.register(NodeInfo(
            node_id="test_service_node",
            architectural_class=NodeArchitecturalClass.SERVICE_NODE,
            status=NodeStatus.HEALTHY,
        ))

        names = get_callable_node_names()
        assert "test_callable_node" in names
        assert "test_service_node" not in names

    def test_callable_classes_mirrors_capability_sync_eligible(self):
        """CALLABLE_ARCHITECTURAL_CLASSES must match _CAPABILITY_SYNC_ELIGIBLE."""
        from core.callable_node_baseline import CALLABLE_ARCHITECTURAL_CLASSES
        from core.nodes.node_fabric_registry import _CAPABILITY_SYNC_ELIGIBLE
        # Normalize both to sets of string values for comparison.
        baseline_values = set(CALLABLE_ARCHITECTURAL_CLASSES)
        eligible_values = {
            (c.value if hasattr(c, "value") else str(c))
            for c in _CAPABILITY_SYNC_ELIGIBLE
        }
        assert baseline_values == eligible_values, (
            "CALLABLE_ARCHITECTURAL_CLASSES must equal the string values of "
            "_CAPABILITY_SYNC_ELIGIBLE from node_fabric_registry "
            "(single source of truth for callable node classes). "
            f"baseline={baseline_values!r}, eligible={eligible_values!r}"
        )


class TestPhaseB_ValidateRuntimeAcceptanceCheck:
    """B2: validate_runtime.py exposes the new check functions."""

    def test_check_runtime_acceptance_present(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "validate_runtime",
            PROJECT_ROOT / "scripts" / "validate_runtime.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "check_runtime_acceptance", None))

    def test_check_callable_node_baseline_present(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "validate_runtime",
            PROJECT_ROOT / "scripts" / "validate_runtime.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "check_callable_node_baseline", None))

    def test_main_invokes_both_new_checks(self):
        """main() in validate_runtime.py must call both new check functions."""
        import inspect
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "validate_runtime",
            PROJECT_ROOT / "scripts" / "validate_runtime.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        main_src = inspect.getsource(mod.main)
        assert "check_runtime_acceptance()" in main_src
        assert "check_callable_node_baseline()" in main_src


class TestPhaseB_NodeArchitecturalClassAccess:
    """B3: NodeArchitecturalClass enum and _CAPABILITY_SYNC_ELIGIBLE accessible."""

    def test_enum_members_complete(self):
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        values = {c.value for c in NodeArchitecturalClass}
        assert "capability_node" in values
        assert "service_node" in values
        assert "legacy_orchestrator_node" in values
        assert "experimental_node" in values
        assert "archived_node" in values

    def test_capability_sync_eligible_non_empty(self):
        from core.nodes.node_fabric_registry import _CAPABILITY_SYNC_ELIGIBLE
        assert len(_CAPABILITY_SYNC_ELIGIBLE) >= 1

    def test_capability_sync_eligible_contains_capability_node(self):
        from core.nodes.node_fabric_registry import (
            _CAPABILITY_SYNC_ELIGIBLE,
            NodeArchitecturalClass,
        )
        assert NodeArchitecturalClass.CAPABILITY_NODE in _CAPABILITY_SYNC_ELIGIBLE

    def test_service_node_not_in_eligible(self):
        from core.nodes.node_fabric_registry import (
            _CAPABILITY_SYNC_ELIGIBLE,
            NodeArchitecturalClass,
        )
        assert NodeArchitecturalClass.SERVICE_NODE not in _CAPABILITY_SYNC_ELIGIBLE


# ===========================================================================
# Phase C — Legacy purge registry
# ===========================================================================


class TestPhaseC_PurgeRegistryEntries:
    """C1: Phase-A entries present in the legacy purge registry."""

    def _get_registry(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        return PURGE_REGISTRY

    def test_hybrid_executor_rename_entry_present(self):
        registry = self._get_registry()
        paths = {e.asset_path for e in registry}
        assert "core/hybrid_executor.py::CapabilityRegistry" in paths, (
            "Purge registry must contain an entry for the CapabilityRegistry → "
            "AppExecutionCapabilityRegistry rename (Phase-A consolidation)."
        )

    def test_scheduler_mcp_prefix_entry_present(self):
        registry = self._get_registry()
        paths = {e.asset_path for e in registry}
        assert "core/scheduler.py::inject_mcp_tools (mcp_ prefix)" in paths

    def test_scheduler_skill_prefix_entry_present(self):
        registry = self._get_registry()
        paths = {e.asset_path for e in registry}
        assert "core/scheduler.py::inject_skill_tools (skill_ prefix)" in paths

    def test_scheduler_call_prefix_entry_present(self):
        registry = self._get_registry()
        paths = {e.asset_path for e in registry}
        assert "core/scheduler.py::_dispatch_tool_call (call_ prefix)" in paths

    def test_hybrid_executor_entry_pr_phase_a(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        entry = next(
            (e for e in PURGE_REGISTRY
             if e.asset_path == "core/hybrid_executor.py::CapabilityRegistry"),
            None,
        )
        assert entry is not None
        assert entry.pr == "PR-consolidation-A"
        assert entry.canonical_replacement is not None
        assert "AppExecutionCapabilityRegistry" in entry.canonical_replacement

    def test_scheduler_entries_pr_phase_a(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        phase_a = [e for e in PURGE_REGISTRY if e.pr == "PR-consolidation-A"]
        assert len(phase_a) >= 4, (
            f"Expected ≥ 4 PR-consolidation-A purge entries, got {len(phase_a)}"
        )

    def test_all_phase_a_entries_have_canonical_replacement(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        for entry in PURGE_REGISTRY:
            if entry.pr == "PR-consolidation-A":
                assert entry.canonical_replacement, (
                    f"PR-consolidation-A entry {entry.asset_path!r} must have a canonical_replacement."
                )


# ===========================================================================
# Integration: Phase-A canonical naming round-trip
# ===========================================================================


class TestPhaseA_NamingRoundTrip:
    """Verify that canonical prefixes are correctly classified end-to-end."""

    def test_canonical_dispatcher_classifies_all_prefixes(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        cases = [
            ("mcp__server__tool", CapabilityLayer.MCP),
            ("mcp__gateway__tool", CapabilityLayer.MCP_GW),
            ("skill__hello", CapabilityLayer.SKILL),
            ("node__node_01__run", CapabilityLayer.NODE),
        ]
        for tool_name, expected in cases:
            got = CapabilityLayer.classify(tool_name)
            assert got == expected, (
                f"classify({tool_name!r}) → {got.value!r}, expected {expected.value!r}"
            )

    def test_tool_call_schema_classifies_canonical_prefixes(self):
        from core.schemas.tool_call import ToolCallRecord, ToolLayer
        cases = [
            ("mcp__server__screenshot", ToolLayer.MCP),
            ("mcp__gateway__do_thing", ToolLayer.MCP_GW),
            ("skill__greet", ToolLayer.SKILL),
            ("node__node_01__ping", ToolLayer.NODE),
        ]
        for tool_name, expected in cases:
            got = ToolCallRecord.classify_layer(tool_name)
            assert got == expected, (
                f"classify_layer({tool_name!r}) → {got.value!r}, expected {expected.value!r}"
            )
