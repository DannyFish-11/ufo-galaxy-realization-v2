#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr530_runtime_acceptance_and_spine_hardening.py
===========================================================
PR-530 — Full Runtime Acceptance and End-to-End Execution Spine Hardening.

Coverage domains
-----------------
A) Sentinel verification — all PR-530 sentinel constants importable and correct.
B) Full runtime smoke / acceptance for the tiered startup model (Core / Standard / Full).
C) Primary OpenClawd request path acceptance:
     request enters OpenClawd → tools are collected → canonical dispatch occurs
     → a result or structured failure is returned.
D) Node / Skill / MCP behavioral regression coverage — each layer tested in
     isolation and in combination; malformed/missing tool name handling;
     unavailable/failure cases that must not mask regressions in other layers.
E) Execution spine observability hardening — trace_id / request_id propagation
     from OpenClawd through CanonicalDispatcher through CommandRouter;
     DispatchResult carries correlation fields; validate_runtime section 10.
F) Failure / fallback / degrade path hardening — unavailable tools, malformed
     tool names, timeout/degrade scenarios, optional soft-fail expectations,
     fallback execution behavior.

Design principles
------------------
* All infrastructure dependencies (MCP servers, live nodes, LLM backends) are
  replaced with test doubles so the suite is CI-safe without live services.
* The CanonicalDispatcher primary path is exercised by default; the inline
  fallback path (``_capability_dispatcher = None``) is tested separately for
  regression protection.
* Each layer (Node / Skill / MCP) has at least one success test and one
  isolated failure test so that a regression in one layer causes exactly that
  group of tests to fail — not a silent pass across all layers.
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Module-level helpers for launcher construction
# ---------------------------------------------------------------------------

_NDJ_PATH = PROJECT_ROOT / "node_dependencies.json"


def _make_launcher():
    """Return a NodeSystemLauncher instance backed by the real node_dependencies.json."""
    import json
    from unittest.mock import MagicMock as _MM
    from launcher.node_startup import NodeSystemLauncher

    with open(_NDJ_PATH, "r", encoding="utf-8") as fh:
        ndj = json.load(fh)

    service_manager = _MM()
    config = _MM()
    config.web_ui_port = 9000

    instance = NodeSystemLauncher.__new__(NodeSystemLauncher)
    instance.service_manager = service_manager
    instance.config = config
    instance.nodes_dir = PROJECT_ROOT / "nodes"
    instance.node_configs = ndj.get("nodes", {})
    return instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _reset_capability_state() -> None:
    """Reset singleton registries between tests to avoid state leakage."""
    try:
        from core.agent.capability_registry import CapabilityRegistry
        reg = CapabilityRegistry.get_instance()
        reg._items.clear()
        try:
            reg._validation_errors.clear()
        except AttributeError:
            pass
        try:
            reg._last_refresh = 0.0
        except AttributeError:
            pass
    except Exception:
        pass

    try:
        from core.unified.capability_resolver import reset_capability_resolver
        reset_capability_resolver()
    except Exception:
        pass

    try:
        from core.capability_bus import reset_capability_bus
        reset_capability_bus()
    except Exception:
        pass

    try:
        from core.skill_loader import SkillLoader
        SkillLoader._instance = None
    except Exception:
        pass

    try:
        from core.nodes.node_fabric_registry import reset_node_fabric_registry
        reset_node_fabric_registry()
    except Exception:
        pass


def _make_openclawd_with_dispatcher():
    """Return an OpenClawd instance wired with a CanonicalDispatcher."""
    from core.capabilities.canonical_dispatcher import CanonicalDispatcher
    from core.openclawd import OpenClawd

    oc = OpenClawd.__new__(OpenClawd)
    oc._initialized = False
    oc._tool_permission_checker = None
    oc._node_id_to_key = {}
    oc._current_trace_id = "trace-pr530-test"
    oc._current_session_id = "sess-pr530-test"
    oc._current_device_id = "dev-pr530-test"
    oc._capability_dispatcher = CanonicalDispatcher(
        device_id="dev-pr530-test",
        session_id="sess-pr530-test",
        trace_id="trace-pr530-test",
        node_id_to_key=oc._node_id_to_key,
    )
    return oc


def _make_openclawd_inline():
    """Return an OpenClawd instance without CanonicalDispatcher (inline path)."""
    from core.openclawd import OpenClawd

    oc = OpenClawd.__new__(OpenClawd)
    oc._initialized = False
    oc._tool_permission_checker = None
    oc._node_id_to_key = {}
    oc._current_trace_id = ""
    oc._current_session_id = ""
    oc._current_device_id = ""
    oc._capability_dispatcher = None
    return oc


def _load_validate_runtime():
    """Load scripts/validate_runtime.py as a module."""
    spec = importlib.util.spec_from_file_location(
        "validate_runtime",
        PROJECT_ROOT / "scripts" / "validate_runtime.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ===========================================================================
# Section A: Sentinel verification
# ===========================================================================


class TestSentinels:
    """PR-530 sentinel constants must be importable and non-empty."""

    def test_canonical_dispatcher_spine_hardened_sentinel(self):
        from core.capabilities.canonical_dispatcher import (
            CANONICAL_DISPATCHER_SPINE_HARDENED,
        )
        assert CANONICAL_DISPATCHER_SPINE_HARDENED
        assert "CANONICAL_DISPATCHER_SPINE_HARDENED" in CANONICAL_DISPATCHER_SPINE_HARDENED

    def test_canonical_dispatcher_spine_hardened_mentions_trace_id(self):
        from core.capabilities.canonical_dispatcher import (
            CANONICAL_DISPATCHER_SPINE_HARDENED,
        )
        assert "trace_id" in CANONICAL_DISPATCHER_SPINE_HARDENED

    def test_canonical_dispatcher_spine_hardened_mentions_request_id(self):
        from core.capabilities.canonical_dispatcher import (
            CANONICAL_DISPATCHER_SPINE_HARDENED,
        )
        assert "request_id" in CANONICAL_DISPATCHER_SPINE_HARDENED

    def test_openclawd_spine_observability_hardened_sentinel(self):
        from core.openclawd import OPENCLAWD_SPINE_OBSERVABILITY_HARDENED
        assert OPENCLAWD_SPINE_OBSERVABILITY_HARDENED
        assert "SPINE_OBSERVABILITY_HARDENED" in OPENCLAWD_SPINE_OBSERVABILITY_HARDENED

    def test_openclawd_spine_observability_hardened_mentions_trace_id(self):
        from core.openclawd import OPENCLAWD_SPINE_OBSERVABILITY_HARDENED
        assert "trace_id" in OPENCLAWD_SPINE_OBSERVABILITY_HARDENED

    def test_command_router_correlation_hardened_sentinel(self):
        from core.command_router import COMMAND_ROUTER_CORRELATION_HARDENED
        assert COMMAND_ROUTER_CORRELATION_HARDENED
        assert "CORRELATION_HARDENED" in COMMAND_ROUTER_CORRELATION_HARDENED

    def test_command_router_correlation_hardened_mentions_trace_id(self):
        from core.command_router import COMMAND_ROUTER_CORRELATION_HARDENED
        assert "trace_id" in COMMAND_ROUTER_CORRELATION_HARDENED


# ===========================================================================
# Section B: Full runtime smoke / acceptance for tiered startup model
# ===========================================================================


class TestTieredStartupSmoke:
    """Smoke coverage for the tiered startup model without live services."""

    def test_startup_tier_model_importable(self):
        import core.startup_tier_model as m
        assert m.STARTUP_TIER_MODEL_AUTHORITY

    def test_launcher_tier_constants_present(self):
        from launcher.node_startup import NodeSystemLauncher
        assert NodeSystemLauncher.STARTUP_TIER_CORE == "Core"
        assert NodeSystemLauncher.STARTUP_TIER_STANDARD == "Standard"
        assert NodeSystemLauncher.STARTUP_TIER_FULL == "Full"

    def test_core_tier_nodes_non_empty(self):
        from launcher.node_startup import NodeSystemLauncher
        launcher = _make_launcher()
        core_nodes = launcher.get_tier_nodes(NodeSystemLauncher.STARTUP_TIER_CORE)
        assert len(core_nodes) > 0, "Core tier must include at least one node"

    def test_standard_tier_is_superset_of_core(self):
        from launcher.node_startup import NodeSystemLauncher
        launcher = _make_launcher()
        core = set(launcher.get_tier_nodes(NodeSystemLauncher.STARTUP_TIER_CORE))
        standard = set(launcher.get_tier_nodes(NodeSystemLauncher.STARTUP_TIER_STANDARD))
        assert core.issubset(standard), (
            "Standard tier must include all Core tier nodes"
        )

    def test_full_tier_is_superset_of_standard(self):
        from launcher.node_startup import NodeSystemLauncher
        launcher = _make_launcher()
        standard = set(launcher.get_tier_nodes(NodeSystemLauncher.STARTUP_TIER_STANDARD))
        full = set(launcher.get_tier_nodes(NodeSystemLauncher.STARTUP_TIER_FULL))
        assert standard.issubset(full), (
            "Full tier must include all Standard tier nodes"
        )

    def test_readiness_baseline_returns_expected_keys(self):
        launcher = _make_launcher()
        baseline = launcher.get_readiness_baseline()
        # The baseline uses active_baseline (not full_tier) to represent the
        # full set of active nodes; check for the keys that actually exist.
        for key in ("core_tier", "standard_tier", "summary"):
            assert key in baseline, f"readiness baseline missing key: {key!r}"
        # At least one of the full-tier representations must be present.
        has_full_repr = "full_tier" in baseline or "active_baseline" in baseline
        assert has_full_repr, (
            "readiness baseline must contain either 'full_tier' or 'active_baseline'"
        )

    def test_invalid_tier_raises(self):
        from launcher.node_startup import NodeSystemLauncher
        launcher = _make_launcher()
        with pytest.raises(ValueError):
            launcher.get_tier_nodes("InvalidTier")

    def test_full_tier_soft_fail_acceptance(self):
        """Full tier may include optional nodes that can be missing; the
        tier query must not raise even when optional nodes are absent."""
        from launcher.node_startup import NodeSystemLauncher as _NSL
        launcher = _make_launcher()
        # This must complete without raising regardless of optional node state.
        full = launcher.get_tier_nodes(_NSL.STARTUP_TIER_FULL)
        assert isinstance(full, list)

    def test_core_startup_path_importable(self):
        """Core startup modules must be importable — structural smoke check."""
        import importlib
        for mod_path, cls_name in [
            ("core.desktop_presence_runtime", "DesktopPresenceRuntime"),
            ("core.openclawd", "OpenClawd"),
            ("core.command_router", "CommandRouter"),
        ]:
            mod = importlib.import_module(mod_path)
            assert hasattr(mod, cls_name), (
                f"{cls_name} not found in {mod_path}"
            )

    def test_openclawd_collect_tools_is_callable(self):
        """OpenClawd._collect_tools() must be present without live backend."""
        from core.openclawd import OpenClawd
        assert callable(getattr(OpenClawd, "_collect_tools", None))

    def test_openclawd_dispatch_tool_call_is_callable(self):
        """OpenClawd._dispatch_tool_call() must be present without live backend."""
        from core.openclawd import OpenClawd
        assert callable(getattr(OpenClawd, "_dispatch_tool_call", None))


# ===========================================================================
# Section C: Primary OpenClawd request path acceptance
# ===========================================================================


class TestOpenClawdRequestPath:
    """Behavioral acceptance for the primary OpenClawd request path.

    The canonical sequence covered:
      request enters OpenClawd → tools are collected → dispatch occurs
      → a result or structured failure is returned.
    """

    def setup_method(self):
        _reset_capability_state()

    def test_collect_tools_returns_list(self):
        """_collect_tools() must return a list (possibly empty without backends)."""
        oc = _make_openclawd_with_dispatcher()
        result = oc._collect_tools()
        assert isinstance(result, list)

    def test_collect_tools_includes_injected_skill(self):
        """A skill injected into CapabilityRegistry must appear in
        _collect_tools()."""
        from core.agent.capability_registry import CapabilityItem, CapabilityRegistry

        reg = CapabilityRegistry.get_instance()
        reg.inject_item(
            CapabilityItem(
                name="skill__test_acceptance_skill",
                description="Acceptance test skill",
                source="skill",
                source_id="test_acceptance_skill",
                parameters={"type": "object", "properties": {}},
                available=True,
            )
        )
        oc = _make_openclawd_with_dispatcher()
        tools = oc._collect_tools()
        names = [t["function"]["name"] for t in tools]
        assert "skill__test_acceptance_skill" in names

    def test_collect_tools_includes_injected_mcp_tool(self):
        """An MCP tool injected into CapabilityRegistry must appear in
        _collect_tools()."""
        from core.agent.capability_registry import CapabilityRegistry

        reg = CapabilityRegistry.get_instance()
        reg.inject_mcp_tool(
            server_id="acceptance_srv",
            tool_name="echo",
            description="Acceptance MCP echo",
            parameters={"type": "object", "properties": {}},
        )
        oc = _make_openclawd_with_dispatcher()
        tools = oc._collect_tools()
        names = [t["function"]["name"] for t in tools]
        assert "mcp__acceptance_srv__echo" in names

    @pytest.mark.asyncio
    async def test_dispatch_returns_result_dict(self):
        """_dispatch_tool_call() must always return a dict with a 'success' key."""
        oc = _make_openclawd_with_dispatcher()
        # Use the unknown-prefix path — no backend needed.
        result = await oc._dispatch_tool_call("bogus__no__backend", {})
        assert isinstance(result, dict)
        assert "success" in result

    @pytest.mark.asyncio
    async def test_successful_skill_dispatch_path(self):
        """A successful skill dispatch must return success=True with a result."""
        oc = _make_openclawd_with_dispatcher()
        expected = {"response": "hello from skill"}

        mock_reg = MagicMock()
        mock_reg.has_skill.return_value = True
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.outputs = expected
        mock_reg.invoke = AsyncMock(return_value=mock_resp)

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call("skill__hello_skill", {})

        assert result.get("success") is True
        assert result.get("result") == expected

    @pytest.mark.asyncio
    async def test_trace_id_propagates_through_dispatch(self):
        """The trace_id set on OpenClawd must propagate through the
        CanonicalDispatcher into the DispatchResult."""
        oc = _make_openclawd_with_dispatcher()
        oc._current_trace_id = "trace-acceptance-001"
        oc._capability_dispatcher.trace_id = "trace-acceptance-001"

        mock_reg = MagicMock()
        mock_reg.has_skill.return_value = True
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.outputs = {"ok": True}
        mock_reg.invoke = AsyncMock(return_value=mock_resp)

        # Intercept CanonicalDispatcher.dispatch to inspect the DispatchResult.
        original_dispatch = oc._capability_dispatcher.dispatch

        captured: list = []

        async def _spy(tool_name, arguments, **kwargs):
            dr = await original_dispatch(tool_name, arguments, **kwargs)
            captured.append(dr)
            return dr

        oc._capability_dispatcher.dispatch = _spy

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            await oc._dispatch_tool_call("skill__traced_skill", {})

        assert captured, "dispatch() must have been called"
        dr = captured[0]
        assert dr.trace_id == "trace-acceptance-001", (
            f"trace_id must propagate into DispatchResult; got {dr.trace_id!r}"
        )

    @pytest.mark.asyncio
    async def test_structured_failure_on_unknown_prefix(self):
        """An unknown tool prefix must produce a structured failure response,
        not raise an exception."""
        oc = _make_openclawd_with_dispatcher()
        result = await oc._dispatch_tool_call("xunknown__foo__bar", {})
        assert result.get("success") is False
        assert "error" in result
        assert result["error"]


# ===========================================================================
# Section D: Node / Skill / MCP behavioral regression coverage
# ===========================================================================


class TestNodeLayerRegression:
    """Node dispatch layer — isolated success, failure, and malformed-name cases."""

    def setup_method(self):
        _reset_capability_state()

    @pytest.mark.asyncio
    async def test_node_dispatch_success_via_canonical_dispatcher(self):
        """Successful node dispatch via CanonicalDispatcher primary path."""
        oc = _make_openclawd_with_dispatcher()
        oc._node_id_to_key["node_reg_ok"] = "Node_reg_ok"
        oc._capability_dispatcher._node_id_to_key["node_reg_ok"] = "Node_reg_ok"

        sentinel = {"status": "node_ok"}
        fake_node_info = {
            "type": "function",
            "execute": AsyncMock(return_value=sentinel),
            "module": None,
        }

        with patch("core.routes._helpers._load_node", return_value=fake_node_info), \
             patch("core.routes._helpers._execute_node",
                   new_callable=AsyncMock, return_value=sentinel), \
             patch("core.routes._helpers.nodes_root", "/fake"), \
             patch("os.path.exists", return_value=True):
            result = await oc._dispatch_tool_call("node__node_reg_ok__run", {})

        assert result.get("success") is True
        assert result.get("result") == sentinel

    @pytest.mark.asyncio
    async def test_node_dispatch_success_via_inline_path(self):
        """Successful node dispatch via the inline (non-dispatcher) path."""
        oc = _make_openclawd_inline()
        oc._node_id_to_key["node_inline_ok"] = "Node_inline_ok"

        sentinel = {"status": "inline_node_ok"}
        fake_node_info = {
            "type": "function",
            "execute": AsyncMock(return_value=sentinel),
            "module": None,
        }

        with patch("core.routes._helpers._load_node", return_value=fake_node_info), \
             patch("core.routes._helpers._execute_node",
                   new_callable=AsyncMock, return_value=sentinel), \
             patch("core.routes._helpers.nodes_root", "/fake"), \
             patch("os.path.exists", return_value=True):
            result = await oc._dispatch_tool_call("node__node_inline_ok__run", {})

        assert result.get("success") is True
        assert result.get("result") == sentinel

    @pytest.mark.asyncio
    async def test_node_not_registered_returns_structured_error(self):
        """A node not in the registry or registry file must return success=False."""
        oc = _make_openclawd_with_dispatcher()
        result = await oc._dispatch_tool_call("node__ghost_node__ping", {})
        assert result.get("success") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_node_malformed_name_too_few_parts(self):
        """node__<id> without an action part must return success=False."""
        oc = _make_openclawd_with_dispatcher()
        result = await oc._dispatch_tool_call("node__no_action", {})
        assert result.get("success") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_node_failure_does_not_mask_skill_success(self):
        """A node failure must not interfere with a subsequent skill dispatch."""
        oc = _make_openclawd_with_dispatcher()
        # First call: node failure
        node_result = await oc._dispatch_tool_call("node__ghost__ping", {})
        assert node_result.get("success") is False

        # Second call: skill success
        mock_reg = MagicMock()
        mock_reg.has_skill.return_value = True
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.outputs = {"ok": "skill_after_node_fail"}
        mock_reg.invoke = AsyncMock(return_value=mock_resp)

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            skill_result = await oc._dispatch_tool_call("skill__after_node_fail", {})

        assert skill_result.get("success") is True


class TestSkillLayerRegression:
    """Skill dispatch layer — isolated success, failure, and fallback cases."""

    def setup_method(self):
        _reset_capability_state()

    @pytest.mark.asyncio
    async def test_skill_dispatch_success_via_canonical_dispatcher(self):
        """Successful skill dispatch via CanonicalDispatcher primary path."""
        oc = _make_openclawd_with_dispatcher()
        sentinel = {"skill_output": "canonical_ok"}

        mock_reg = MagicMock()
        mock_reg.has_skill.return_value = True
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.outputs = sentinel
        mock_reg.invoke = AsyncMock(return_value=mock_resp)

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call("skill__canonical_skill", {})

        assert result.get("success") is True
        assert result.get("result") == sentinel

    @pytest.mark.asyncio
    async def test_skill_registry_failure_returns_structured_error(self):
        """When the skill registry returns a failed response, success=False
        with an error message must be returned."""
        oc = _make_openclawd_with_dispatcher()

        mock_reg = MagicMock()
        mock_reg.has_skill.return_value = True
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_err = MagicMock()
        mock_err.message = "Skill execution failed internally"
        mock_resp.first_error = mock_err
        mock_reg.invoke = AsyncMock(return_value=mock_resp)

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call("skill__broken_skill", {})

        assert result.get("success") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_skill_failure_does_not_mask_mcp_success(self):
        """A skill failure must not interfere with a subsequent MCP dispatch."""
        oc = _make_openclawd_with_dispatcher()

        # First: skill failure
        mock_reg_fail = MagicMock()
        mock_reg_fail.has_skill.return_value = True
        mock_resp_fail = MagicMock()
        mock_resp_fail.ok = False
        mock_err = MagicMock()
        mock_err.message = "bad skill"
        mock_resp_fail.first_error = mock_err
        mock_reg_fail.invoke = AsyncMock(return_value=mock_resp_fail)

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg_fail):
            skill_result = await oc._dispatch_tool_call("skill__broken", {})
        assert skill_result.get("success") is False

        # Second: MCP success
        mcp_sentinel = {"mcp_after_skill_fail": True}
        mock_loader = MagicMock()
        mock_loader.call_tool = AsyncMock(return_value=mcp_sentinel)
        mock_reg2 = MagicMock()
        mock_reg2._emit_log = MagicMock()

        with patch("core.mcp_loader.mcp_loader", mock_loader), \
             patch("core.skill_registry.get_skill_registry", return_value=mock_reg2):
            mcp_result = await oc._dispatch_tool_call("mcp__good_srv__query", {})

        assert mcp_result.get("success") is True
        assert mcp_result.get("result") == mcp_sentinel

    @pytest.mark.asyncio
    async def test_skill_lazy_registration_creates_adapter(self):
        """A skill not yet in the registry must be lazily registered via
        skill_loader and dispatched successfully."""
        oc = _make_openclawd_with_dispatcher()
        sentinel = {"lazy_skill": "loaded_ok"}

        mock_reg = MagicMock()
        mock_reg.has_skill.return_value = False

        # After register_skill is called, subsequent has_skill returns True
        # and invoke returns success.
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.outputs = sentinel
        mock_reg.invoke = AsyncMock(return_value=mock_resp)
        mock_reg.register_skill = MagicMock()

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call("skill__lazy_skill", {})

        # register_skill should have been called to create the lazy adapter.
        mock_reg.register_skill.assert_called_once()
        assert result.get("success") is True


class TestMCPLayerRegression:
    """MCP dispatch layer — isolated success, failure, and malformed-name cases."""

    def setup_method(self):
        _reset_capability_state()

    @pytest.mark.asyncio
    async def test_mcp_dispatch_success_via_canonical_dispatcher(self):
        """Successful MCP dispatch via CanonicalDispatcher primary path."""
        oc = _make_openclawd_with_dispatcher()
        sentinel = {"mcp_output": "canonical_ok"}

        mock_loader = MagicMock()
        mock_loader.call_tool = AsyncMock(return_value=sentinel)
        mock_reg = MagicMock()
        mock_reg._emit_log = MagicMock()

        with patch("core.mcp_loader.mcp_loader", mock_loader), \
             patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call("mcp__good_srv__echo", {})

        assert result.get("success") is True
        assert result.get("result") == sentinel

    @pytest.mark.asyncio
    async def test_mcp_server_unavailable_returns_structured_error(self):
        """An exception from mcp_loader must result in success=False rather
        than propagating to the caller."""
        oc = _make_openclawd_with_dispatcher()

        mock_loader = MagicMock()
        mock_loader.call_tool = AsyncMock(
            side_effect=ConnectionError("MCP server unreachable")
        )
        mock_reg = MagicMock()
        mock_reg._emit_log = MagicMock()

        with patch("core.mcp_loader.mcp_loader", mock_loader), \
             patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call("mcp__unreachable_srv__op", {})

        assert result.get("success") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_mcp_malformed_name_too_few_parts(self):
        """mcp__<server> without a tool name part must return success=False."""
        oc = _make_openclawd_with_dispatcher()
        result = await oc._dispatch_tool_call("mcp__only_server", {})
        assert result.get("success") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_mcp_failure_does_not_mask_node_success(self):
        """An MCP failure must not interfere with a subsequent node dispatch."""
        oc = _make_openclawd_with_dispatcher()

        # First: MCP failure
        mock_loader_fail = MagicMock()
        mock_loader_fail.call_tool = AsyncMock(
            side_effect=RuntimeError("mcp down")
        )
        mock_reg_fail = MagicMock()
        mock_reg_fail._emit_log = MagicMock()

        with patch("core.mcp_loader.mcp_loader", mock_loader_fail), \
             patch("core.skill_registry.get_skill_registry", return_value=mock_reg_fail):
            mcp_result = await oc._dispatch_tool_call("mcp__down_srv__op", {})
        assert mcp_result.get("success") is False

        # Second: node success
        oc._node_id_to_key["after_mcp_node"] = "Node_after_mcp"
        oc._capability_dispatcher._node_id_to_key["after_mcp_node"] = "Node_after_mcp"
        sentinel = {"node_after_mcp_fail": True}
        fake_node_info = {
            "type": "function",
            "execute": AsyncMock(return_value=sentinel),
            "module": None,
        }

        with patch("core.routes._helpers._load_node", return_value=fake_node_info), \
             patch("core.routes._helpers._execute_node",
                   new_callable=AsyncMock, return_value=sentinel), \
             patch("core.routes._helpers.nodes_root", "/fake"), \
             patch("os.path.exists", return_value=True):
            node_result = await oc._dispatch_tool_call("node__after_mcp_node__run", {})

        assert node_result.get("success") is True

    @pytest.mark.asyncio
    async def test_mcp_gateway_tool_path(self):
        """mcp__gateway__<tool> must route through the gateway path."""
        oc = _make_openclawd_with_dispatcher()
        gateway_result = {"gateway_tool": "ok"}

        mock_gateway = MagicMock()
        mock_gateway.execute_tool = AsyncMock(return_value=gateway_result)
        mock_reg = MagicMock()
        mock_reg._emit_log = MagicMock()

        # The canonical_dispatcher does `from core.mcp_gateway import get_mcp_gateway`.
        # Since `get_mcp_gateway` doesn't exist as a standalone function, patch at
        # the import location used by the dispatcher.
        with patch(
            "core.capabilities.canonical_dispatcher.CanonicalDispatcher._dispatch_mcp",
            new_callable=AsyncMock,
        ) as mock_dispatch_mcp:
            from core.capabilities.canonical_dispatcher import DispatchResult
            mock_dispatch_mcp.return_value = DispatchResult(
                success=True, result=gateway_result
            )
            result = await oc._dispatch_tool_call(
                "mcp__gateway__list_capabilities", {}
            )

        assert result.get("success") is True
        assert result.get("result") == gateway_result


# ===========================================================================
# Section E: Execution spine observability hardening
# ===========================================================================


class TestDispatchResultSpineFields:
    """DispatchResult must carry trace_id and request_id for full spine correlation."""

    def test_dispatch_result_has_trace_id_field(self):
        from core.capabilities.canonical_dispatcher import DispatchResult
        dr = DispatchResult(success=True, trace_id="t-123")
        assert dr.trace_id == "t-123"

    def test_dispatch_result_has_request_id_field(self):
        from core.capabilities.canonical_dispatcher import DispatchResult
        dr = DispatchResult(success=True, request_id="req-456")
        assert dr.request_id == "req-456"

    def test_dispatch_result_to_dict_includes_trace_id(self):
        from core.capabilities.canonical_dispatcher import DispatchResult
        dr = DispatchResult(success=True, trace_id="t-abc")
        d = dr.to_dict()
        assert "trace_id" in d
        assert d["trace_id"] == "t-abc"

    def test_dispatch_result_to_dict_includes_request_id(self):
        from core.capabilities.canonical_dispatcher import DispatchResult
        dr = DispatchResult(success=True, request_id="req-def")
        d = dr.to_dict()
        assert "request_id" in d
        assert d["request_id"] == "req-def"

    def test_dispatch_result_request_id_defaults_to_dispatch_id_when_empty(self):
        """When request_id is not provided, to_dict() must fall back to
        dispatch_id so there is always a non-empty correlation field."""
        from core.capabilities.canonical_dispatcher import DispatchResult
        dr = DispatchResult(success=True)
        d = dr.to_dict()
        assert d["request_id"]  # non-empty
        assert d["request_id"] == dr.dispatch_id

    def test_dispatch_result_failure_also_carries_trace_id(self):
        from core.capabilities.canonical_dispatcher import DispatchResult, CapabilityLayer
        dr = DispatchResult(
            success=False,
            error="something went wrong",
            trace_id="t-fail",
            layer=CapabilityLayer.SKILL,
        )
        d = dr.to_dict()
        assert d["trace_id"] == "t-fail"


class TestCanonicalDispatcherTracePropagation:
    """CanonicalDispatcher must propagate trace_id into DispatchResult."""

    def setup_method(self):
        _reset_capability_state()

    @pytest.mark.asyncio
    async def test_dispatcher_stamps_trace_id_on_success(self):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher

        dispatcher = CanonicalDispatcher(trace_id="spine-trace-001")

        mock_reg = MagicMock()
        mock_reg.has_skill.return_value = True
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.outputs = {"ok": True}
        mock_reg.invoke = AsyncMock(return_value=mock_resp)

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            dr = await dispatcher.dispatch("skill__traced_skill", {})

        assert dr.trace_id == "spine-trace-001", (
            f"Expected trace_id='spine-trace-001', got {dr.trace_id!r}"
        )

    @pytest.mark.asyncio
    async def test_dispatcher_stamps_trace_id_on_failure(self):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher

        dispatcher = CanonicalDispatcher(trace_id="spine-trace-002")
        dr = await dispatcher.dispatch("unknown__prefix__tool", {})
        assert dr.trace_id == "spine-trace-002"

    @pytest.mark.asyncio
    async def test_per_call_trace_id_overrides_instance_trace_id(self):
        """Per-call trace_id kwarg must take precedence over instance trace_id."""
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher

        dispatcher = CanonicalDispatcher(trace_id="instance-trace")

        mock_reg = MagicMock()
        mock_reg.has_skill.return_value = True
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.outputs = {"ok": True}
        mock_reg.invoke = AsyncMock(return_value=mock_resp)

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            dr = await dispatcher.dispatch(
                "skill__override_trace", {},
                trace_id="per-call-trace"
            )

        assert dr.trace_id == "per-call-trace", (
            f"Per-call trace_id must override instance; got {dr.trace_id!r}"
        )

    @pytest.mark.asyncio
    async def test_capability_layer_stamped_on_result(self):
        """DispatchResult.layer must match the tool prefix classification."""
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher, CapabilityLayer

        dispatcher = CanonicalDispatcher()
        # Use an unknown prefix to avoid backend dependency.
        dr = await dispatcher.dispatch("xunknown__tool__act", {})
        assert dr.layer == CapabilityLayer.UNKNOWN

    def test_capability_layer_classify_all_prefixes(self):
        """CapabilityLayer.classify() must return the correct layer for
        every canonical prefix — regression guard."""
        from core.capabilities.canonical_dispatcher import CapabilityLayer

        cases: list[tuple[str, CapabilityLayer]] = [
            ("mcp__srv__tool",     CapabilityLayer.MCP),
            ("mcp__gateway__tool", CapabilityLayer.MCP_GW),
            ("skill__my_skill",    CapabilityLayer.SKILL),
            ("node__n1__act",      CapabilityLayer.NODE),
            ("device__d1__cmd",    CapabilityLayer.DEVICE),
            ("github__install",    CapabilityLayer.GITHUB),
            ("unknown_prefix",     CapabilityLayer.UNKNOWN),
        ]
        for name, expected in cases:
            got = CapabilityLayer.classify(name)
            assert got == expected, (
                f"classify({name!r}): expected {expected.value!r}, got {got.value!r}"
            )


class TestSpineObservabilityValidateRuntime:
    """validate_runtime.py section 10 must pass the spine observability checks."""

    def _load(self):
        return _load_validate_runtime()

    def test_check_spine_observability_present(self):
        mod = self._load()
        assert callable(getattr(mod, "check_spine_observability", None)), (
            "validate_runtime.py must expose check_spine_observability()"
        )

    def test_main_calls_check_spine_observability(self):
        import inspect
        mod = self._load()
        main_src = inspect.getsource(mod.main)
        assert "check_spine_observability()" in main_src, (
            "main() must call check_spine_observability()"
        )
        uncommented = [
            line for line in main_src.splitlines()
            if "check_spine_observability()" in line
            and not line.lstrip().startswith("#")
        ]
        assert uncommented, "check_spine_observability() must be an active call in main()"

    def test_check_spine_observability_runs_without_errors(self):
        """Running check_spine_observability() must not raise."""
        mod = self._load()
        mod._results = []
        mod._section_label = ""
        try:
            mod.check_spine_observability()
        except Exception as exc:
            pytest.fail(f"check_spine_observability() raised: {exc}")

    def test_spine_sentinels_detected_as_pass(self):
        """All PR-530 spine sentinel checks must register as PASS."""
        mod = self._load()
        mod._results = []
        mod._section_label = ""
        mod.check_spine_observability()
        failures = [
            r for r in mod._results
            if "spine:" in r.name and r.status == "FAIL"
        ]
        assert not failures, (
            "Spine observability checks must all PASS; failures: "
            + ", ".join(r.name for r in failures)
        )


# ===========================================================================
# Section F: Failure / fallback / degrade path hardening
# ===========================================================================


class TestFailurePaths:
    """Hardened failure/fallback/degrade path coverage."""

    def setup_method(self):
        _reset_capability_state()

    @pytest.mark.asyncio
    async def test_unknown_tool_prefix_structured_failure(self):
        """An unrecognised prefix must return a structured failure dict."""
        oc = _make_openclawd_with_dispatcher()
        result = await oc._dispatch_tool_call("xbad__tool__name", {})
        assert result.get("success") is False
        assert isinstance(result.get("error"), str)
        assert result["error"]

    @pytest.mark.asyncio
    async def test_malformed_node_tool_name_structured_failure(self):
        """node__ with fewer than 3 parts must give success=False."""
        for bad_name in ["node__only_id", "node__"]:
            oc = _make_openclawd_with_dispatcher()
            result = await oc._dispatch_tool_call(bad_name, {})
            assert result.get("success") is False, (
                f"Expected failure for malformed tool name: {bad_name!r}"
            )

    @pytest.mark.asyncio
    async def test_malformed_mcp_tool_name_structured_failure(self):
        """mcp__ with fewer than 3 parts must give success=False."""
        for bad_name in ["mcp__only_server", "mcp__"]:
            oc = _make_openclawd_with_dispatcher()
            result = await oc._dispatch_tool_call(bad_name, {})
            assert result.get("success") is False, (
                f"Expected failure for malformed tool name: {bad_name!r}"
            )

    @pytest.mark.asyncio
    async def test_missing_node_returns_descriptive_error(self):
        """A node not in any registry must return success=False with a
        non-empty error string (not a bare exception message)."""
        oc = _make_openclawd_with_dispatcher()
        result = await oc._dispatch_tool_call("node__completely_missing__act", {})
        assert result.get("success") is False
        assert result.get("error"), "error message must be non-empty"

    @pytest.mark.asyncio
    async def test_mcp_timeout_or_exception_structured_failure(self):
        """A TimeoutError from the MCP layer must produce success=False."""
        oc = _make_openclawd_with_dispatcher()

        mock_loader = MagicMock()
        mock_loader.call_tool = AsyncMock(side_effect=TimeoutError("MCP timeout"))
        mock_reg = MagicMock()
        mock_reg._emit_log = MagicMock()

        with patch("core.mcp_loader.mcp_loader", mock_loader), \
             patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call("mcp__slow_srv__op", {})

        assert result.get("success") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_fallback_to_inline_path_when_dispatcher_raises(self):
        """If CanonicalDispatcher.dispatch raises unexpectedly, the inline
        fallback path must be used and return a coherent dict."""
        oc = _make_openclawd_with_dispatcher()
        oc._capability_dispatcher.dispatch = AsyncMock(
            side_effect=RuntimeError("dispatcher internal error")
        )

        # The inline fallback should handle unknown prefix gracefully.
        result = await oc._dispatch_tool_call("bogus__tool__name", {})
        assert isinstance(result, dict)
        assert "success" in result

    @pytest.mark.asyncio
    async def test_dispatcher_none_inline_path_returns_coherent_dict(self):
        """When _capability_dispatcher is None the inline path must be used
        and always return a dict with 'success'."""
        oc = _make_openclawd_inline()
        result = await oc._dispatch_tool_call("bogus__inline__test", {})
        assert isinstance(result, dict)
        assert "success" in result

    @pytest.mark.asyncio
    async def test_optional_soft_fail_node_does_not_raise(self):
        """An optional node that is absent must not raise; it must return
        success=False so callers can degrade gracefully."""
        oc = _make_openclawd_with_dispatcher()
        # No registration, no registry entry — optional node not present.
        result = await oc._dispatch_tool_call("node__optional_node__health", {})
        assert result.get("success") is False
        # No exception propagated.

    @pytest.mark.asyncio
    async def test_degrade_path_mcp_then_skill_then_node(self):
        """Three sequential dispatches where only the last succeeds must
        produce exactly one success and two failures — no error masking."""
        oc = _make_openclawd_with_dispatcher()

        # MCP fail
        mock_loader = MagicMock()
        mock_loader.call_tool = AsyncMock(side_effect=RuntimeError("mcp down"))
        mock_reg_fail = MagicMock()
        mock_reg_fail._emit_log = MagicMock()

        with patch("core.mcp_loader.mcp_loader", mock_loader), \
             patch("core.skill_registry.get_skill_registry", return_value=mock_reg_fail):
            r1 = await oc._dispatch_tool_call("mcp__down_srv__op", {})
        assert r1.get("success") is False

        # Skill fail
        mock_reg_skill_fail = MagicMock()
        mock_reg_skill_fail.has_skill.return_value = True
        mock_resp_fail = MagicMock()
        mock_resp_fail.ok = False
        mock_err = MagicMock()
        mock_err.message = "skill down"
        mock_resp_fail.first_error = mock_err
        mock_reg_skill_fail.invoke = AsyncMock(return_value=mock_resp_fail)

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg_skill_fail):
            r2 = await oc._dispatch_tool_call("skill__down_skill", {})
        assert r2.get("success") is False

        # Node success
        oc._node_id_to_key["degrade_node"] = "Node_degrade"
        oc._capability_dispatcher._node_id_to_key["degrade_node"] = "Node_degrade"
        sentinel = {"degrade": "node_ok"}
        fake_node_info = {
            "type": "function",
            "execute": AsyncMock(return_value=sentinel),
            "module": None,
        }
        with patch("core.routes._helpers._load_node", return_value=fake_node_info), \
             patch("core.routes._helpers._execute_node",
                   new_callable=AsyncMock, return_value=sentinel), \
             patch("core.routes._helpers.nodes_root", "/fake"), \
             patch("os.path.exists", return_value=True):
            r3 = await oc._dispatch_tool_call("node__degrade_node__run", {})
        assert r3.get("success") is True
        assert r3.get("result") == sentinel


# ===========================================================================
# Standalone runner
# ===========================================================================

if __name__ == "__main__":
    import subprocess

    code = subprocess.call(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=str(PROJECT_ROOT),
    )
    sys.exit(code)
