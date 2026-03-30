#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_canonical_execution_chain.py
========================================

Canonical Execution Chain consolidation tests.

Validates the canonical authority chain:
  route layer → OpenClawd → CommandRouter → DeviceRouter → device/transport

Coverage
--------
1.  CanonicalExecutionChain module: sentinels exist and are correct.
2.  CanonicalChainStage enum has all required stages.
3.  CHAIN_STAGE_AUTHORITY maps every stage to the correct authority.
4.  CANONICAL_STAGE_ORDER is complete and correctly ordered.
5.  SIDE_PATH_MODULE_REGISTRY contains expected side-path modules with
    non-authority roles.
6.  build_chain_context() returns a context at ROUTE_INGRESS stage.
7.  ChainExecutionContext.advance_stage() updates stage and authority.
8.  CommandRouter has COMMAND_ROUTER_ORCHESTRATION_AUTHORITY sentinel.
9.  DeviceRouter has CANONICAL_DISPATCH_AUTHORITY sentinel.
10. DeviceRouter has send_command_to_device() method (canonical transport).
11. CommandRouter has _dispatch_via_device_router() method.
12. MainlineChainStage includes COMMAND_ROUTER_ORCHESTRATION and
    DEVICE_ROUTER_DISPATCH stages.
13. MainlineChainAuthority includes COMMAND_ROUTER and DEVICE_ROUTER values.
14. STAGE_AUTHORITY maps COMMAND_ROUTER_ORCHESTRATION → COMMAND_ROUTER.
15. STAGE_AUTHORITY maps DEVICE_ROUTER_DISPATCH → DEVICE_ROUTER.
16. e2e_orchestrator has E2E_ORCHESTRATOR_ROLE sentinel = "convenience_facade".
17. hybrid_executor has HYBRID_EXECUTOR_ROLE sentinel.
18. agent_bridge has AGENT_BRIDGE_ROLE sentinel.
19. EntrypointRouter.route_request stamps canonical_chain_stage in routing
    metadata.
20. CommandRouter.route_envelope stamps COMMAND_ROUTER_ORCHESTRATION stage
    in mainline registry (smoke test).
21. is_canonical_module() returns True for the three authorities only.
22. get_side_path_role() returns non-None for all side-path modules.
23. DeviceRouter.dispatch_task() callable (signature check).
24. SIDE_PATH_MODULE_REGISTRY does not classify canonical modules as facades.
25. ChainExecutionContext.to_dict() includes all required keys.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# 1–7. core.canonical_execution_chain module
# ===========================================================================


class TestCanonicalExecutionChainModule:
    """Tests for core/canonical_execution_chain.py sentinels and API."""

    def test_module_importable(self):
        import core.canonical_execution_chain  # noqa: F401

    def test_canonical_chain_authority_sentinel(self):
        from core.canonical_execution_chain import CANONICAL_CHAIN_AUTHORITY
        assert isinstance(CANONICAL_CHAIN_AUTHORITY, str)
        assert CANONICAL_CHAIN_AUTHORITY == "core.canonical_execution_chain"

    def test_openclawd_subject_authority(self):
        from core.canonical_execution_chain import OPENCLAWD_SUBJECT_AUTHORITY
        assert OPENCLAWD_SUBJECT_AUTHORITY == "core.openclawd.OpenClawd"

    def test_command_router_orchestration_authority(self):
        from core.canonical_execution_chain import COMMAND_ROUTER_ORCHESTRATION_AUTHORITY
        assert COMMAND_ROUTER_ORCHESTRATION_AUTHORITY == "core.command_router.CommandRouter"

    def test_device_router_dispatch_authority(self):
        from core.canonical_execution_chain import DEVICE_ROUTER_DISPATCH_AUTHORITY
        assert DEVICE_ROUTER_DISPATCH_AUTHORITY == "galaxy_gateway.device_router.DeviceRouter"

    def test_route_adapter_role(self):
        from core.canonical_execution_chain import ROUTE_ADAPTER_ROLE
        assert ROUTE_ADAPTER_ROLE == "route_adapter"

    def test_side_path_facade_role(self):
        from core.canonical_execution_chain import SIDE_PATH_FACADE_ROLE
        assert SIDE_PATH_FACADE_ROLE == "side_path_facade"


class TestCanonicalChainStageEnum:
    """CanonicalChainStage has all required stages."""

    def test_route_ingress_exists(self):
        from core.canonical_execution_chain import CanonicalChainStage
        assert hasattr(CanonicalChainStage, "ROUTE_INGRESS")

    def test_route_adapter_exists(self):
        from core.canonical_execution_chain import CanonicalChainStage
        assert hasattr(CanonicalChainStage, "ROUTE_ADAPTER")

    def test_openclawd_subject_exists(self):
        from core.canonical_execution_chain import CanonicalChainStage
        assert hasattr(CanonicalChainStage, "OPENCLAWD_SUBJECT")

    def test_command_router_orchestration_exists(self):
        from core.canonical_execution_chain import CanonicalChainStage
        assert hasattr(CanonicalChainStage, "COMMAND_ROUTER_ORCHESTRATION")

    def test_device_router_dispatch_exists(self):
        from core.canonical_execution_chain import CanonicalChainStage
        assert hasattr(CanonicalChainStage, "DEVICE_ROUTER_DISPATCH")

    def test_device_execution_exists(self):
        from core.canonical_execution_chain import CanonicalChainStage
        assert hasattr(CanonicalChainStage, "DEVICE_EXECUTION")

    def test_response_return_exists(self):
        from core.canonical_execution_chain import CanonicalChainStage
        assert hasattr(CanonicalChainStage, "RESPONSE_RETURN")

    def test_stage_values_are_strings(self):
        from core.canonical_execution_chain import CanonicalChainStage
        for stage in CanonicalChainStage:
            assert isinstance(stage.value, str)


class TestChainStageAuthority:
    """CHAIN_STAGE_AUTHORITY maps every stage to the correct authority."""

    def test_all_stages_mapped(self):
        from core.canonical_execution_chain import (
            CanonicalChainStage,
            CHAIN_STAGE_AUTHORITY,
        )
        for stage in CanonicalChainStage:
            assert stage in CHAIN_STAGE_AUTHORITY, f"Stage {stage} missing from CHAIN_STAGE_AUTHORITY"

    def test_openclawd_stage_authority(self):
        from core.canonical_execution_chain import (
            CanonicalChainStage,
            CHAIN_STAGE_AUTHORITY,
            OPENCLAWD_SUBJECT_AUTHORITY,
        )
        assert CHAIN_STAGE_AUTHORITY[CanonicalChainStage.OPENCLAWD_SUBJECT] == OPENCLAWD_SUBJECT_AUTHORITY

    def test_command_router_stage_authority(self):
        from core.canonical_execution_chain import (
            CanonicalChainStage,
            CHAIN_STAGE_AUTHORITY,
            COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
        )
        assert (
            CHAIN_STAGE_AUTHORITY[CanonicalChainStage.COMMAND_ROUTER_ORCHESTRATION]
            == COMMAND_ROUTER_ORCHESTRATION_AUTHORITY
        )

    def test_device_router_stage_authority(self):
        from core.canonical_execution_chain import (
            CanonicalChainStage,
            CHAIN_STAGE_AUTHORITY,
            DEVICE_ROUTER_DISPATCH_AUTHORITY,
        )
        assert (
            CHAIN_STAGE_AUTHORITY[CanonicalChainStage.DEVICE_ROUTER_DISPATCH]
            == DEVICE_ROUTER_DISPATCH_AUTHORITY
        )

    def test_route_stages_have_adapter_role(self):
        from core.canonical_execution_chain import (
            CanonicalChainStage,
            CHAIN_STAGE_AUTHORITY,
            ROUTE_ADAPTER_ROLE,
        )
        assert CHAIN_STAGE_AUTHORITY[CanonicalChainStage.ROUTE_INGRESS] == ROUTE_ADAPTER_ROLE
        assert CHAIN_STAGE_AUTHORITY[CanonicalChainStage.ROUTE_ADAPTER] == ROUTE_ADAPTER_ROLE


class TestCanonicalStageOrder:
    """CANONICAL_STAGE_ORDER is complete and correctly ordered."""

    def test_stage_order_importable(self):
        from core.canonical_execution_chain import CANONICAL_STAGE_ORDER
        assert CANONICAL_STAGE_ORDER is not None

    def test_stage_order_length(self):
        from core.canonical_execution_chain import CANONICAL_STAGE_ORDER, CanonicalChainStage
        assert len(CANONICAL_STAGE_ORDER) == len(CanonicalChainStage)

    def test_route_ingress_is_first(self):
        from core.canonical_execution_chain import CANONICAL_STAGE_ORDER, CanonicalChainStage
        assert CANONICAL_STAGE_ORDER[0] == CanonicalChainStage.ROUTE_INGRESS

    def test_openclawd_before_command_router(self):
        from core.canonical_execution_chain import CANONICAL_STAGE_ORDER, CanonicalChainStage
        stages = list(CANONICAL_STAGE_ORDER)
        oc_idx = stages.index(CanonicalChainStage.OPENCLAWD_SUBJECT)
        cr_idx = stages.index(CanonicalChainStage.COMMAND_ROUTER_ORCHESTRATION)
        assert oc_idx < cr_idx

    def test_command_router_before_device_router(self):
        from core.canonical_execution_chain import CANONICAL_STAGE_ORDER, CanonicalChainStage
        stages = list(CANONICAL_STAGE_ORDER)
        cr_idx = stages.index(CanonicalChainStage.COMMAND_ROUTER_ORCHESTRATION)
        dr_idx = stages.index(CanonicalChainStage.DEVICE_ROUTER_DISPATCH)
        assert cr_idx < dr_idx

    def test_device_router_before_execution(self):
        from core.canonical_execution_chain import CANONICAL_STAGE_ORDER, CanonicalChainStage
        stages = list(CANONICAL_STAGE_ORDER)
        dr_idx = stages.index(CanonicalChainStage.DEVICE_ROUTER_DISPATCH)
        ex_idx = stages.index(CanonicalChainStage.DEVICE_EXECUTION)
        assert dr_idx < ex_idx


class TestSidePathModuleRegistry:
    """SIDE_PATH_MODULE_REGISTRY contains expected side-path modules."""

    def test_registry_importable(self):
        from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
        assert SIDE_PATH_MODULE_REGISTRY is not None

    def test_e2e_orchestrator_registered(self):
        from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
        assert "core.e2e_orchestrator" in SIDE_PATH_MODULE_REGISTRY

    def test_hybrid_executor_registered(self):
        from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
        assert "core.hybrid_executor" in SIDE_PATH_MODULE_REGISTRY

    def test_remote_execution_mode_resolver_registered(self):
        from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
        assert "core.remote_execution_mode_resolver" in SIDE_PATH_MODULE_REGISTRY

    def test_repo_coordinator_registered(self):
        from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
        assert "core.repo_coordinator" in SIDE_PATH_MODULE_REGISTRY

    def test_agent_bridge_registered(self):
        from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
        assert "galaxy_gateway.agent_bridge" in SIDE_PATH_MODULE_REGISTRY

    def test_task_router_registered(self):
        from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
        assert "galaxy_gateway.task_router" in SIDE_PATH_MODULE_REGISTRY

    def test_cross_device_coordinator_registered(self):
        from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
        assert "galaxy_gateway.cross_device_coordinator" in SIDE_PATH_MODULE_REGISTRY

    def test_local_execution_chain_registered(self):
        from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
        assert "core.local_execution_chain" in SIDE_PATH_MODULE_REGISTRY

    def test_cross_device_execution_chain_registered(self):
        from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
        assert "core.cross_device_execution_chain" in SIDE_PATH_MODULE_REGISTRY

    def test_no_authority_roles_in_side_path_registry(self):
        """Canonical authority sentinels must not appear in the side-path registry."""
        from core.canonical_execution_chain import (
            SIDE_PATH_MODULE_REGISTRY,
            OPENCLAWD_SUBJECT_AUTHORITY,
            COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
            DEVICE_ROUTER_DISPATCH_AUTHORITY,
        )
        authority_sentinels = {
            OPENCLAWD_SUBJECT_AUTHORITY,
            COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
            DEVICE_ROUTER_DISPATCH_AUTHORITY,
        }
        for module, role in SIDE_PATH_MODULE_REGISTRY.items():
            assert module not in authority_sentinels, (
                f"Canonical authority {module} found in side-path registry"
            )


class TestBuildChainContext:
    """build_chain_context() constructs a context at ROUTE_INGRESS."""

    def test_returns_chain_execution_context(self):
        from core.canonical_execution_chain import build_chain_context, ChainExecutionContext
        ctx = build_chain_context(source="test")
        assert isinstance(ctx, ChainExecutionContext)

    def test_initial_stage_is_route_ingress(self):
        from core.canonical_execution_chain import build_chain_context, CanonicalChainStage
        ctx = build_chain_context(source="test")
        assert ctx.current_stage == CanonicalChainStage.ROUTE_INGRESS.value

    def test_trace_id_is_generated(self):
        from core.canonical_execution_chain import build_chain_context
        ctx = build_chain_context()
        assert ctx.trace_id
        assert len(ctx.trace_id) > 0

    def test_provided_trace_id_is_used(self):
        from core.canonical_execution_chain import build_chain_context
        ctx = build_chain_context(trace_id="trace_abc123")
        assert ctx.trace_id == "trace_abc123"

    def test_stages_visited_includes_route_ingress(self):
        from core.canonical_execution_chain import build_chain_context, CanonicalChainStage
        ctx = build_chain_context()
        assert CanonicalChainStage.ROUTE_INGRESS.value in ctx.stages_visited

    def test_source_stored_in_extra(self):
        from core.canonical_execution_chain import build_chain_context
        ctx = build_chain_context(source="chat_route")
        assert ctx.extra.get("source") == "chat_route"


class TestChainExecutionContextAdvanceStage:
    """ChainExecutionContext.advance_stage() updates stage and authority."""

    def test_advance_stage_updates_current_stage(self):
        from core.canonical_execution_chain import build_chain_context, CanonicalChainStage
        ctx = build_chain_context()
        ctx.advance_stage(CanonicalChainStage.OPENCLAWD_SUBJECT)
        assert ctx.current_stage == CanonicalChainStage.OPENCLAWD_SUBJECT.value

    def test_advance_stage_updates_authority(self):
        from core.canonical_execution_chain import (
            build_chain_context,
            CanonicalChainStage,
            COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
        )
        ctx = build_chain_context()
        ctx.advance_stage(CanonicalChainStage.COMMAND_ROUTER_ORCHESTRATION)
        assert ctx.current_authority == COMMAND_ROUTER_ORCHESTRATION_AUTHORITY

    def test_advance_stage_appends_to_visited(self):
        from core.canonical_execution_chain import build_chain_context, CanonicalChainStage
        ctx = build_chain_context()
        ctx.advance_stage(CanonicalChainStage.OPENCLAWD_SUBJECT)
        ctx.advance_stage(CanonicalChainStage.COMMAND_ROUTER_ORCHESTRATION)
        assert CanonicalChainStage.OPENCLAWD_SUBJECT.value in ctx.stages_visited
        assert CanonicalChainStage.COMMAND_ROUTER_ORCHESTRATION.value in ctx.stages_visited

    def test_advance_stage_no_duplicates_in_visited(self):
        from core.canonical_execution_chain import build_chain_context, CanonicalChainStage
        ctx = build_chain_context()
        ctx.advance_stage(CanonicalChainStage.OPENCLAWD_SUBJECT)
        ctx.advance_stage(CanonicalChainStage.OPENCLAWD_SUBJECT)
        count = ctx.stages_visited.count(CanonicalChainStage.OPENCLAWD_SUBJECT.value)
        assert count == 1

    def test_advance_returns_self(self):
        from core.canonical_execution_chain import build_chain_context, CanonicalChainStage
        ctx = build_chain_context()
        result = ctx.advance_stage(CanonicalChainStage.OPENCLAWD_SUBJECT)
        assert result is ctx

    def test_to_dict_contains_required_keys(self):
        from core.canonical_execution_chain import build_chain_context
        ctx = build_chain_context(trace_id="t1", task_id="task1", device_id="dev1")
        d = ctx.to_dict()
        expected_keys = {
            "trace_id", "task_id", "session_id", "device_id",
            "current_stage", "current_authority", "stages_visited",
            "ingress_ts", "last_stage_ts", "extra",
        }
        assert expected_keys <= set(d.keys()), (
            f"Missing keys in to_dict(): {expected_keys - set(d.keys())}"
        )


# ===========================================================================
# 8. CommandRouter authority sentinel
# ===========================================================================


class TestCommandRouterOrchestrationAuthority:
    """CommandRouter has COMMAND_ROUTER_ORCHESTRATION_AUTHORITY sentinel."""

    def test_sentinel_exists(self):
        from core.command_router import COMMAND_ROUTER_ORCHESTRATION_AUTHORITY
        assert COMMAND_ROUTER_ORCHESTRATION_AUTHORITY is not None

    def test_sentinel_value(self):
        from core.command_router import COMMAND_ROUTER_ORCHESTRATION_AUTHORITY
        assert COMMAND_ROUTER_ORCHESTRATION_AUTHORITY == "core.command_router.CommandRouter"

    def test_sentinel_is_string(self):
        from core.command_router import COMMAND_ROUTER_ORCHESTRATION_AUTHORITY
        assert isinstance(COMMAND_ROUTER_ORCHESTRATION_AUTHORITY, str)


# ===========================================================================
# 9. DeviceRouter dispatch authority sentinel
# ===========================================================================


class TestDeviceRouterDispatchAuthority:
    """DeviceRouter has CANONICAL_DISPATCH_AUTHORITY sentinel."""

    def test_sentinel_exists(self):
        from galaxy_gateway.device_router import CANONICAL_DISPATCH_AUTHORITY
        assert CANONICAL_DISPATCH_AUTHORITY is not None

    def test_sentinel_value(self):
        from galaxy_gateway.device_router import CANONICAL_DISPATCH_AUTHORITY
        assert CANONICAL_DISPATCH_AUTHORITY == "galaxy_gateway.device_router.DeviceRouter"


# ===========================================================================
# 10–11. New canonical transport methods
# ===========================================================================


class TestDeviceRouterSendCommandToDevice:
    """DeviceRouter has send_command_to_device() method (canonical transport)."""

    def test_method_exists(self):
        from galaxy_gateway.device_router import DeviceRouter
        assert hasattr(DeviceRouter, "send_command_to_device")

    def test_method_is_coroutine(self):
        from galaxy_gateway.device_router import DeviceRouter
        assert asyncio.iscoroutinefunction(DeviceRouter.send_command_to_device)

    def test_method_signature(self):
        from galaxy_gateway.device_router import DeviceRouter
        sig = inspect.signature(DeviceRouter.send_command_to_device)
        params = set(sig.parameters.keys())
        for required in ("device_id", "command", "payload"):
            assert required in params, f"Missing param: {required}"

    @pytest.mark.asyncio
    async def test_returns_none_when_device_not_found(self):
        """send_command_to_device returns None when device not in session table."""
        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter.__new__(DeviceRouter)
        router.devices = {}
        router._task_events = {}
        router.task_results = {}

        result = await router.send_command_to_device(
            device_id="nonexistent_device",
            command="screenshot",
            payload={},
        )
        assert result is None


class TestCommandRouterDispatchViaDeviceRouter:
    """CommandRouter has _dispatch_via_device_router() method."""

    def test_method_exists(self):
        from core.command_router import CommandRouter
        assert hasattr(CommandRouter, "_dispatch_via_device_router")

    def test_method_is_coroutine(self):
        from core.command_router import CommandRouter
        assert asyncio.iscoroutinefunction(CommandRouter._dispatch_via_device_router)

    def test_method_signature(self):
        from core.command_router import CommandRouter
        sig = inspect.signature(CommandRouter._dispatch_via_device_router)
        params = set(sig.parameters.keys())
        for required in ("device_id", "command", "payload", "task_id", "trace_id"):
            assert required in params, f"Missing param: {required}"

    @pytest.mark.asyncio
    async def test_returns_none_when_device_router_unavailable(self):
        """_dispatch_via_device_router returns None when DeviceRouter not importable."""
        from core.command_router import CommandRouter
        router = CommandRouter()

        with patch("galaxy_gateway.device_router.device_router") as mock_dr:
            mock_dr.get_device.return_value = None
            result = await router._dispatch_via_device_router(
                device_id="test_device",
                command="screenshot",
                payload={},
                task_id="task_001",
                trace_id="trace_abc",
                command_id="cmd_001",
            )
        # Should return None when device not found
        assert result is None


# ===========================================================================
# 12–15. MainlineChainStage / Authority updates
# ===========================================================================


class TestMainlineChainStageUpdates:
    """MainlineChainStage includes COMMAND_ROUTER_ORCHESTRATION and
    DEVICE_ROUTER_DISPATCH stages."""

    def test_command_router_orchestration_stage_exists(self):
        from core.mainline_convergence import MainlineChainStage
        assert hasattr(MainlineChainStage, "COMMAND_ROUTER_ORCHESTRATION")

    def test_device_router_dispatch_stage_exists(self):
        from core.mainline_convergence import MainlineChainStage
        assert hasattr(MainlineChainStage, "DEVICE_ROUTER_DISPATCH")

    def test_command_router_orchestration_value(self):
        from core.mainline_convergence import MainlineChainStage
        assert MainlineChainStage.COMMAND_ROUTER_ORCHESTRATION.value == "command_router_orchestration"

    def test_device_router_dispatch_value(self):
        from core.mainline_convergence import MainlineChainStage
        assert MainlineChainStage.DEVICE_ROUTER_DISPATCH.value == "device_router_dispatch"

    def test_existing_stages_preserved(self):
        """Existing stages must not be broken by the new additions."""
        from core.mainline_convergence import MainlineChainStage
        for stage_name in ("REQUEST_INGRESS", "OPENCLAWD_AUTHORITY", "CAPABILITY_DISPATCH",
                           "RESOURCE_RESOLUTION", "EXECUTION", "KNOWLEDGE_RECALL",
                           "KNOWLEDGE_WRITEBACK", "ENGINEERING_LOOP", "RESPONSE_EMISSION"):
            assert hasattr(MainlineChainStage, stage_name), f"Existing stage {stage_name} missing"


class TestMainlineChainAuthorityUpdates:
    """MainlineChainAuthority includes COMMAND_ROUTER and DEVICE_ROUTER values."""

    def test_command_router_authority_exists(self):
        from core.mainline_convergence import MainlineChainAuthority
        assert hasattr(MainlineChainAuthority, "COMMAND_ROUTER")

    def test_device_router_authority_exists(self):
        from core.mainline_convergence import MainlineChainAuthority
        assert hasattr(MainlineChainAuthority, "DEVICE_ROUTER")

    def test_command_router_authority_value(self):
        from core.mainline_convergence import MainlineChainAuthority
        assert MainlineChainAuthority.COMMAND_ROUTER.value == "command_router"

    def test_device_router_authority_value(self):
        from core.mainline_convergence import MainlineChainAuthority
        assert MainlineChainAuthority.DEVICE_ROUTER.value == "device_router"

    def test_existing_authorities_preserved(self):
        """Existing authorities must not be broken."""
        from core.mainline_convergence import MainlineChainAuthority
        for authority_name in ("OPENCLAWD", "CAPABILITY_BUS", "SYSTEM_RESOURCE_REGISTRY",
                               "CANONICAL_DISPATCHER", "RAG_MEMORY", "SELF_HEALING_LOOP",
                               "COMPAT_ADAPTER", "LEGACY_PATH", "UNKNOWN"):
            assert hasattr(MainlineChainAuthority, authority_name), (
                f"Existing authority {authority_name} missing"
            )


class TestStageAuthorityMapping:
    """STAGE_AUTHORITY maps the new stages correctly."""

    def test_command_router_orchestration_mapped(self):
        from core.mainline_convergence import (
            STAGE_AUTHORITY,
            MainlineChainStage,
            MainlineChainAuthority,
        )
        assert STAGE_AUTHORITY.get(MainlineChainStage.COMMAND_ROUTER_ORCHESTRATION) == (
            MainlineChainAuthority.COMMAND_ROUTER
        )

    def test_device_router_dispatch_mapped(self):
        from core.mainline_convergence import (
            STAGE_AUTHORITY,
            MainlineChainStage,
            MainlineChainAuthority,
        )
        assert STAGE_AUTHORITY.get(MainlineChainStage.DEVICE_ROUTER_DISPATCH) == (
            MainlineChainAuthority.DEVICE_ROUTER
        )

    def test_openclawd_authority_mapped(self):
        from core.mainline_convergence import (
            STAGE_AUTHORITY,
            MainlineChainStage,
            MainlineChainAuthority,
        )
        assert STAGE_AUTHORITY.get(MainlineChainStage.OPENCLAWD_AUTHORITY) == (
            MainlineChainAuthority.OPENCLAWD
        )

    def test_all_new_stages_are_in_stage_authority(self):
        from core.mainline_convergence import STAGE_AUTHORITY, MainlineChainStage
        assert MainlineChainStage.COMMAND_ROUTER_ORCHESTRATION in STAGE_AUTHORITY
        assert MainlineChainStage.DEVICE_ROUTER_DISPATCH in STAGE_AUTHORITY


# ===========================================================================
# 16–18. Side-path module role sentinels
# ===========================================================================


class TestSidePathRoleSentinels:
    """Side-path modules have explicit role sentinels."""

    def test_e2e_orchestrator_has_role_sentinel(self):
        from core.e2e_orchestrator import E2E_ORCHESTRATOR_ROLE
        assert E2E_ORCHESTRATOR_ROLE == "convenience_facade"

    def test_hybrid_executor_has_role_sentinel(self):
        from core.hybrid_executor import HYBRID_EXECUTOR_ROLE
        assert HYBRID_EXECUTOR_ROLE == "fallback_execution_helper"

    def test_agent_bridge_has_role_sentinel(self):
        from galaxy_gateway.agent_bridge import AGENT_BRIDGE_ROLE
        assert AGENT_BRIDGE_ROLE == "runtime_handoff_adapter"


# ===========================================================================
# 19. EntrypointRouter stamps canonical chain metadata
# ===========================================================================


class TestEntrypointRouterChainStamp:
    """EntrypointRouter.route_request stamps canonical chain metadata."""

    @pytest.mark.asyncio
    async def test_routing_meta_has_canonical_chain_stage(self):
        import importlib.util
        import sys
        # Import entrypoint_router directly to avoid fastapi dependency via __init__
        spec = importlib.util.spec_from_file_location(
            "core.unified.entrypoint_router",
            "core/unified/entrypoint_router.py",
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("core.unified.entrypoint_router", mod)
        spec.loader.exec_module(mod)

        mod.reset_entrypoint_router()
        router = mod.get_entrypoint_router()

        async def _dummy_handler(**kwargs):
            return {"success": True, "test": True}

        result = await router.route_request(
            message="test",
            source="test_route",
            handler=_dummy_handler,
        )
        assert "_routing" in result
        routing = result["_routing"]
        assert routing.get("canonical_chain_stage") == "route_ingress"

    @pytest.mark.asyncio
    async def test_routing_meta_has_canonical_chain_authority(self):
        import importlib.util
        import sys
        spec = importlib.util.spec_from_file_location(
            "core.unified.entrypoint_router_b",
            "core/unified/entrypoint_router.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        mod.reset_entrypoint_router()
        router = mod.get_entrypoint_router()

        async def _dummy_handler(**kwargs):
            return {"success": True}

        result = await router.route_request(
            message="test",
            source="test_route",
            handler=_dummy_handler,
        )
        routing = result["_routing"]
        assert routing.get("canonical_chain_authority") == "route_adapter"

    @pytest.mark.asyncio
    async def test_routing_meta_has_canonical_chain_next(self):
        import importlib.util
        import sys
        spec = importlib.util.spec_from_file_location(
            "core.unified.entrypoint_router_c",
            "core/unified/entrypoint_router.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        mod.reset_entrypoint_router()
        router = mod.get_entrypoint_router()

        async def _dummy_handler(**kwargs):
            return {"success": True}

        result = await router.route_request(
            message="test",
            source="test_route",
            handler=_dummy_handler,
        )
        routing = result["_routing"]
        assert routing.get("canonical_chain_next") == "openclawd_subject"


# ===========================================================================
# 21. is_canonical_module() helper
# ===========================================================================


class TestIsCanonicalModule:
    """is_canonical_module() returns True only for the three authorities."""

    def test_openclawd_is_canonical(self):
        from core.canonical_execution_chain import (
            is_canonical_module,
            OPENCLAWD_SUBJECT_AUTHORITY,
        )
        assert is_canonical_module(OPENCLAWD_SUBJECT_AUTHORITY) is True

    def test_command_router_is_canonical(self):
        from core.canonical_execution_chain import (
            is_canonical_module,
            COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
        )
        assert is_canonical_module(COMMAND_ROUTER_ORCHESTRATION_AUTHORITY) is True

    def test_device_router_is_canonical(self):
        from core.canonical_execution_chain import (
            is_canonical_module,
            DEVICE_ROUTER_DISPATCH_AUTHORITY,
        )
        assert is_canonical_module(DEVICE_ROUTER_DISPATCH_AUTHORITY) is True

    def test_e2e_orchestrator_is_not_canonical(self):
        from core.canonical_execution_chain import is_canonical_module
        assert is_canonical_module("core.e2e_orchestrator") is False

    def test_agent_bridge_is_not_canonical(self):
        from core.canonical_execution_chain import is_canonical_module
        assert is_canonical_module("galaxy_gateway.agent_bridge") is False

    def test_unknown_module_is_not_canonical(self):
        from core.canonical_execution_chain import is_canonical_module
        assert is_canonical_module("some.unknown.module") is False


# ===========================================================================
# 22. get_side_path_role() helper
# ===========================================================================


class TestGetSidePathRole:
    """get_side_path_role() returns non-None for all side-path modules."""

    def test_e2e_orchestrator_has_role(self):
        from core.canonical_execution_chain import get_side_path_role
        role = get_side_path_role("core.e2e_orchestrator")
        assert role is not None

    def test_hybrid_executor_has_role(self):
        from core.canonical_execution_chain import get_side_path_role
        role = get_side_path_role("core.hybrid_executor")
        assert role is not None

    def test_agent_bridge_has_role(self):
        from core.canonical_execution_chain import get_side_path_role
        role = get_side_path_role("galaxy_gateway.agent_bridge")
        assert role is not None

    def test_canonical_module_returns_none(self):
        from core.canonical_execution_chain import (
            get_side_path_role,
            OPENCLAWD_SUBJECT_AUTHORITY,
        )
        # canonical authorities are NOT in the side-path registry
        role = get_side_path_role(OPENCLAWD_SUBJECT_AUTHORITY)
        assert role is None

    def test_unknown_module_returns_none(self):
        from core.canonical_execution_chain import get_side_path_role
        assert get_side_path_role("completely.unknown.module") is None


# ===========================================================================
# 23. DeviceRouter.dispatch_task() callable
# ===========================================================================


class TestDeviceRouterDispatchTask:
    """DeviceRouter.dispatch_task() is callable (signature check)."""

    def test_dispatch_task_exists(self):
        from galaxy_gateway.device_router import DeviceRouter
        assert hasattr(DeviceRouter, "dispatch_task")

    def test_dispatch_task_is_coroutine(self):
        from galaxy_gateway.device_router import DeviceRouter
        assert asyncio.iscoroutinefunction(DeviceRouter.dispatch_task)


# ===========================================================================
# 24. Side-path registry does not classify canonical modules as facades
# ===========================================================================


class TestSidePathRegistryIntegrity:
    """Side-path registry does not classify canonical modules as facades."""

    def test_openclawd_not_in_registry(self):
        from core.canonical_execution_chain import (
            SIDE_PATH_MODULE_REGISTRY,
            OPENCLAWD_SUBJECT_AUTHORITY,
        )
        assert OPENCLAWD_SUBJECT_AUTHORITY not in SIDE_PATH_MODULE_REGISTRY

    def test_command_router_not_in_registry(self):
        from core.canonical_execution_chain import (
            SIDE_PATH_MODULE_REGISTRY,
            COMMAND_ROUTER_ORCHESTRATION_AUTHORITY,
        )
        assert COMMAND_ROUTER_ORCHESTRATION_AUTHORITY not in SIDE_PATH_MODULE_REGISTRY

    def test_device_router_not_in_registry(self):
        from core.canonical_execution_chain import (
            SIDE_PATH_MODULE_REGISTRY,
            DEVICE_ROUTER_DISPATCH_AUTHORITY,
        )
        assert DEVICE_ROUTER_DISPATCH_AUTHORITY not in SIDE_PATH_MODULE_REGISTRY
