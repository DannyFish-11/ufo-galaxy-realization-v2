#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_e2e_openclawd_tool_path.py
======================================
End-to-end regression tests: canonical OpenClawd tool-call path

Covers all three callable tool layers:
  - node   → ``node__<node_id>__<action>``
  - skill  → ``skill__<skill_id>``
  - mcp    → ``mcp__<server_id>__<tool_name>``

Regression goals (per problem statement):
  1. OpenClawd can collect tools from the canonical capability path.
  2. The collected tool set includes expected representatives for node /
     skill / mcp.
  3. A tool call routed through ``OpenClawd._dispatch_tool_call(...)``
     reaches the correct execution path.
  4. A successful result is returned in the expected structure.
  5. Failure behaviour remains stable for malformed or missing tool names.

Test doubles are used for live-infrastructure calls (MCP servers, real nodes)
so the suite runs in CI without external services.  The skill layer uses the
existing ``skills/examples/hello_skill`` fixture to exercise the real
SkillLoader path end-to-end.

Patching strategy
-----------------
``_dispatch_tool_call`` uses local (deferred) imports for every sub-system
(``mcp_loader``, ``skill_registry``, ``routes._helpers``).  Patches must
therefore be applied to the *source module* (e.g.
``core.mcp_loader.mcp_loader``, ``core.skill_registry.get_skill_registry``,
``core.routes._helpers._load_node``) so that the dynamic ``from … import …``
inside the function picks up the stub.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_all() -> None:
    """Reset singleton registries between tests to avoid state leakage."""
    from core.agent.capability_registry import CapabilityRegistry
    from core.unified.capability_resolver import reset_capability_resolver

    reg = CapabilityRegistry.get_instance()
    reg._items.clear()
    reg._validation_errors.clear()
    try:
        reg._last_refresh = 0.0
    except AttributeError:
        pass

    reset_capability_resolver()

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


def _make_minimal_openclawd():
    """Return a minimal OpenClawd instance without starting the LLM backend."""
    from core.openclawd import OpenClawd

    oc = OpenClawd.__new__(OpenClawd)
    oc._initialized = False
    oc._tool_permission_checker = None
    oc._node_id_to_key = {}
    # Ensure no CanonicalDispatcher is present so the inline fallback path runs.
    oc._capability_dispatcher = None
    return oc


def _inject_node_capability(
    node_id: str = "node_test_01",
    action: str = "ping",
    description: str = "Test node",
) -> str:
    """Inject a synthetic node tool into CapabilityRegistry and return the tool name."""
    from core.agent.capability_registry import CapabilityItem, CapabilityRegistry

    tool_name = f"node__{node_id}__{action}"
    reg = CapabilityRegistry.get_instance()
    reg.inject_item(
        CapabilityItem(
            name=tool_name,
            description=description,
            source="node",
            source_id=node_id,
            parameters={"type": "object", "properties": {}},
            available=True,
        )
    )
    return tool_name


def _inject_mcp_capability(
    server_id: str = "test_mcp_server",
    tool_name_suffix: str = "echo",
) -> str:
    """Inject a synthetic MCP tool into CapabilityRegistry and return the tool name."""
    from core.agent.capability_registry import CapabilityRegistry

    full_name = f"mcp__{server_id}__{tool_name_suffix}"
    reg = CapabilityRegistry.get_instance()
    # inject_mcp_tool signature: (server_id, tool_name, description, parameters, ...)
    reg.inject_mcp_tool(
        server_id=server_id,
        tool_name=tool_name_suffix,
        description="Test MCP echo tool",
        parameters={"type": "object", "properties": {"message": {"type": "string"}}},
    )
    return full_name


# ===========================================================================
# Section 1: Tool Collection — all three layers appear in _collect_tools()
# ===========================================================================


class TestToolCollection:
    """Verify that _collect_tools() exposes tools from every layer."""

    def setup_method(self):
        _reset_all()

    def test_static_node_tools_appear_in_collect_tools(self):
        """_collect_tools() must always expose the built-in static node tools
        (e.g. node__06__list for the Filesystem node).  This verifies the
        _CORE_NODE_ACTIONS → collect_tools pipeline is intact."""
        from core.openclawd import OpenClawd

        oc = _make_minimal_openclawd()
        collected = oc._collect_tools()
        names = {t["function"]["name"] for t in collected if "function" in t}

        # Spot-check a representative set from _CORE_NODE_ACTIONS
        for expected in ("node__06__list", "node__08__get", "node__09__execute"):
            assert expected in names, (
                f"Static node tool '{expected}' missing from _collect_tools() output"
            )

    def test_node_tools_all_have_node_prefix(self):
        """Every tool produced from the node layer must start with 'node__'."""
        oc = _make_minimal_openclawd()
        collected = oc._collect_tools()
        node_tools = [
            t["function"]["name"]
            for t in collected
            if t.get("function", {}).get("name", "").startswith("node__")
        ]
        assert len(node_tools) > 0, "No node tools returned by _collect_tools()"
        for name in node_tools:
            parts = name.split("__")
            assert len(parts) >= 3, (
                f"Node tool name '{name}' must have at least 3 '__'-separated parts"
            )

    def test_mcp_tool_appears_in_collect_tools(self):
        """A MCP tool registered via inject_mcp_tool() must appear in the
        _collect_tools() output with the ``mcp__<server>__<tool>`` prefix."""
        tool_name = _inject_mcp_capability("srv_alpha", "search")
        oc = _make_minimal_openclawd()

        collected = oc._collect_tools()
        names = [t["function"]["name"] for t in collected if "function" in t]

        assert tool_name in names, (
            f"Expected '{tool_name}' in _collect_tools() output; got: {names[:20]}"
        )

    @pytest.mark.asyncio
    async def test_skill_tool_appears_in_collect_tools(self):
        """A skill loaded via SkillLoader must appear in the _collect_tools()
        output with the ``skill__<id>`` prefix."""
        from core.skill_loader import skill_loader

        skill_path = PROJECT_ROOT / "skills" / "examples" / "hello_skill"
        if not skill_path.exists():
            pytest.skip("hello_skill fixture not found — skipping live skill test")

        result = await skill_loader.load(str(skill_path))
        assert result.get("success"), f"Skill load failed: {result}"
        skill_id = result["skill_id"]

        oc = _make_minimal_openclawd()
        collected = oc._collect_tools()
        names = [t["function"]["name"] for t in collected if "function" in t]

        assert f"skill__{skill_id}" in names, (
            f"Expected 'skill__{skill_id}' in _collect_tools() output; got: {names[:20]}"
        )

    def test_collect_tools_schema_structure_for_node(self):
        """Each collected node tool must have the required OpenAI schema fields."""
        oc = _make_minimal_openclawd()
        collected = oc._collect_tools()
        # Pick the first node tool from the static set
        node_tools = [t for t in collected if t.get("function", {}).get("name", "").startswith("node__")]
        assert node_tools, "No node tools returned — cannot check schema"
        tool_entry = node_tools[0]

        fn = tool_entry["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        assert isinstance(fn["parameters"], dict), "parameters must be a dict"

    def test_collect_tools_schema_structure_for_mcp(self):
        """Each collected MCP tool must have the required OpenAI schema fields."""
        tool_name = _inject_mcp_capability("srv_beta", "list")
        oc = _make_minimal_openclawd()

        collected = oc._collect_tools()
        tool_entry = next(
            (t for t in collected if t.get("function", {}).get("name") == tool_name),
            None,
        )
        assert tool_entry is not None, f"Tool '{tool_name}' not found in collected tools"

        fn = tool_entry["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        assert isinstance(fn["parameters"], dict)

    def test_node_mcp_skill_all_present_simultaneously(self):
        """When MCP and skill capabilities are registered alongside the built-in
        node tools, all three layers must appear in a single _collect_tools() call."""
        mcp_tool = _inject_mcp_capability("srv_combo", "query")

        from core.agent.capability_registry import CapabilityRegistry

        reg = CapabilityRegistry.get_instance()
        reg.inject_skill(
            skill_id="combo_skill",
            skill_name="Combo Skill",
            description="Test combo skill",
            parameters={"type": "object", "properties": {}},
        )
        skill_tool = "skill__combo_skill"

        oc = _make_minimal_openclawd()
        collected = oc._collect_tools()
        names = {t["function"]["name"] for t in collected if "function" in t}

        # node layer: check a static representative
        assert any(n.startswith("node__") for n in names), "Node tools missing"
        assert mcp_tool in names, f"MCP tool '{mcp_tool}' missing"
        assert skill_tool in names, f"Skill tool '{skill_tool}' missing"


# ===========================================================================
# Section 2: Dispatch — _dispatch_tool_call reaches the correct execution path
# ===========================================================================


class TestDispatchToolCall:
    """Verify _dispatch_tool_call routes to the correct execution layer.

    Since _dispatch_tool_call uses deferred ``from … import …`` for every
    sub-system, patches are applied at the source module level so the dynamic
    import picks up the stub.
    """

    def setup_method(self):
        _reset_all()

    # ── Node dispatch ──────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_dispatch_node_tool_reaches_node_layer(self):
        """node__<id>__<action> dispatch must reach _load_node / _execute_node."""
        oc = _make_minimal_openclawd()
        oc._node_id_to_key["node_dispatch_01"] = "Node_dispatch_01"

        node_output = {"status": "ok", "pong": True}
        fake_node_info = {
            "type": "function",
            "execute": AsyncMock(return_value=node_output),
            "module": None,
        }

        # Patch at the source module so the deferred import inside
        # _dispatch_tool_call picks up the stubs.
        with patch("core.routes._helpers._load_node", return_value=fake_node_info) as mock_load, \
             patch("core.routes._helpers._execute_node",
                   new_callable=AsyncMock, return_value=node_output) as mock_exec, \
             patch("core.routes._helpers.nodes_root", "/fake/nodes"), \
             patch("os.path.exists", return_value=True):
            result = await oc._dispatch_tool_call(
                "node__node_dispatch_01__ping", {"params": {}}
            )

        assert result.get("success") is True, f"Node dispatch failed: {result}"
        mock_load.assert_called_once()
        mock_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatch_node_result_in_expected_structure(self):
        """Node dispatch must return ``{"success": True, "result": ...}``."""
        oc = _make_minimal_openclawd()
        oc._node_id_to_key["node_result_01"] = "Node_result_01"

        node_output = {"status": "ok", "value": 42}
        fake_node_info = {
            "type": "function",
            "execute": AsyncMock(return_value=node_output),
            "module": None,
        }

        with patch("core.routes._helpers._load_node", return_value=fake_node_info), \
             patch("core.routes._helpers._execute_node",
                   new_callable=AsyncMock, return_value=node_output), \
             patch("core.routes._helpers.nodes_root", "/fake/nodes"), \
             patch("os.path.exists", return_value=True):
            result = await oc._dispatch_tool_call(
                "node__node_result_01__status", {}
            )

        assert "success" in result
        assert result["success"] is True
        assert result.get("result") == node_output

    # ── Skill dispatch ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_dispatch_skill_tool_reaches_skill_layer(self):
        """skill__<id> dispatch must invoke the skill registry path."""
        oc = _make_minimal_openclawd()
        skill_output = {"message": "Hello, World!"}

        mock_reg = MagicMock()
        mock_reg.has_skill.return_value = True
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.outputs = skill_output
        mock_reg.invoke = AsyncMock(return_value=mock_resp)

        # Patch get_skill_registry at its source module so the deferred import
        # inside _dispatch_tool_call picks up the mock.
        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call(
                "skill__hello_world", {"name": "World"}
            )

        assert result.get("success") is True, f"Skill dispatch failed: {result}"
        assert result.get("result") == skill_output

    @pytest.mark.asyncio
    async def test_dispatch_skill_result_in_expected_structure(self):
        """Skill dispatch must return ``{"success": True, "result": ...}``."""
        oc = _make_minimal_openclawd()
        skill_output = {"answer": "pong"}

        mock_reg = MagicMock()
        mock_reg.has_skill.return_value = True
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.outputs = skill_output
        mock_reg.invoke = AsyncMock(return_value=mock_resp)

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call(
                "skill__test_ping_skill", {"input": "ping"}
            )

        assert "success" in result
        assert result["success"] is True
        assert result.get("result") == skill_output

    # ── MCP dispatch ───────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_dispatch_mcp_tool_reaches_mcp_layer(self):
        """mcp__<server>__<tool> dispatch must call mcp_loader.call_tool."""
        oc = _make_minimal_openclawd()
        mcp_output = {"echoed": "hello"}

        mock_loader = MagicMock()
        mock_loader.call_tool = AsyncMock(return_value=mcp_output)

        # Patch mcp_loader singleton at its source module and get_skill_registry
        # (used for observability logging inside the MCP path).
        mock_reg = MagicMock()
        mock_reg._emit_log = MagicMock()

        with patch("core.mcp_loader.mcp_loader", mock_loader), \
             patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call(
                "mcp__test_server__echo", {"message": "hello"}
            )

        assert result.get("success") is True, f"MCP dispatch failed: {result}"
        mock_loader.call_tool.assert_called_once_with(
            "test_server", "echo", {"message": "hello"}
        )

    @pytest.mark.asyncio
    async def test_dispatch_mcp_result_in_expected_structure(self):
        """MCP dispatch must return ``{"success": True, "result": ...}``."""
        oc = _make_minimal_openclawd()
        mcp_output = {"data": [1, 2, 3]}

        mock_loader = MagicMock()
        mock_loader.call_tool = AsyncMock(return_value=mcp_output)

        mock_reg = MagicMock()
        mock_reg._emit_log = MagicMock()

        with patch("core.mcp_loader.mcp_loader", mock_loader), \
             patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call(
                "mcp__data_server__fetch", {}
            )

        assert "success" in result
        assert result["success"] is True
        assert result.get("result") == mcp_output


# ===========================================================================
# Section 3: CapabilityResolver integration — node source surfaced correctly
# ===========================================================================


class TestCapabilityResolverNodeSource:
    """CapabilityResolver must surface NODE-source items and return them via
    collect_tool_schemas(sources=[CapabilitySource.NODE])."""

    def setup_method(self):
        _reset_all()

    def test_node_item_visible_via_resolver(self):
        """A node CapabilityItem injected into the registry must be resolvable
        through the canonical CapabilityResolver."""
        from core.unified.capability_resolver import get_capability_resolver
        from core.unified.capability_contract import CapabilitySource

        tool_name = _inject_node_capability("node_resolver_01", "ping")

        resolver = get_capability_resolver()
        resolver.invalidate_cache()

        contracts = resolver.resolve_all(source=CapabilitySource.NODE)
        names = [c.name for c in contracts]

        assert tool_name in names, (
            f"Expected '{tool_name}' in resolver (NODE source); got: {names}"
        )

    def test_collect_tool_schemas_node_source(self):
        """collect_tool_schemas(sources=[NODE]) must include injected node tools."""
        from core.unified.capability_resolver import get_capability_resolver
        from core.unified.capability_contract import CapabilitySource

        tool_name = _inject_node_capability("node_schema_01", "execute")

        resolver = get_capability_resolver()
        resolver.invalidate_cache()

        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.NODE])
        schema_names = [s["function"]["name"] for s in schemas if "function" in s]

        assert tool_name in schema_names, (
            f"Expected '{tool_name}' in collect_tool_schemas(NODE); got: {schema_names}"
        )

    def test_node_skill_mcp_resolver_isolation(self):
        """Filtering by source must be precise — node tools must not appear
        in SKILL/MCP slices, and vice versa."""
        from core.unified.capability_resolver import get_capability_resolver
        from core.unified.capability_contract import CapabilitySource
        from core.agent.capability_registry import CapabilityRegistry

        node_tool = _inject_node_capability("node_iso_01", "run")
        mcp_tool = _inject_mcp_capability("srv_iso_01", "call")
        reg = CapabilityRegistry.get_instance()
        reg.inject_skill(
            skill_id="iso_skill",
            skill_name="Iso Skill",
            description="Isolation test skill",
            parameters={"type": "object", "properties": {}},
        )

        resolver = get_capability_resolver()
        resolver.invalidate_cache()

        node_names = {
            c.name for c in resolver.resolve_all(source=CapabilitySource.NODE)
        }
        skill_names = {
            c.name for c in resolver.resolve_all(source=CapabilitySource.SKILL)
        }
        mcp_names = {
            c.name for c in resolver.resolve_all(source=CapabilitySource.MCP)
        }

        # Each tool must appear only in its own layer slice
        assert node_tool in node_names
        assert node_tool not in skill_names
        assert node_tool not in mcp_names

        assert "skill__iso_skill" in skill_names
        assert "skill__iso_skill" not in node_names
        assert "skill__iso_skill" not in mcp_names

        assert mcp_tool in mcp_names
        assert mcp_tool not in node_names
        assert mcp_tool not in skill_names


# ===========================================================================
# Section 4: Failure behaviour — malformed and missing tools
# ===========================================================================


class TestDispatchFailureBehaviour:
    """_dispatch_tool_call must return a stable error structure for bad inputs."""

    def setup_method(self):
        _reset_all()

    @pytest.mark.asyncio
    async def test_unknown_prefix_returns_error(self):
        """A tool name with an unknown prefix must return success=False with
        an informative error, not raise an exception."""
        oc = _make_minimal_openclawd()
        result = await oc._dispatch_tool_call("bogus__some_tool__action", {})
        assert result.get("success") is False
        assert "error" in result
        assert result["error"]  # non-empty error message

    @pytest.mark.asyncio
    async def test_malformed_node_tool_name_returns_error(self):
        """A node__ tool name with fewer than 3 parts must return success=False."""
        oc = _make_minimal_openclawd()
        result = await oc._dispatch_tool_call("node__missing_action", {})
        assert result.get("success") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_malformed_mcp_tool_name_returns_error(self):
        """A mcp__ tool name with fewer than 3 parts must return success=False."""
        oc = _make_minimal_openclawd()
        result = await oc._dispatch_tool_call("mcp__only_server", {})
        assert result.get("success") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_missing_node_registration_returns_error(self):
        """If the node_id is not in the registry or node_registry.json,
        dispatch must return success=False rather than raising."""
        oc = _make_minimal_openclawd()
        # Do NOT register "node_ghost" — it must be absent
        result = await oc._dispatch_tool_call("node__node_ghost__ping", {})
        assert result.get("success") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_node_fusion_entry_missing_returns_error(self):
        """If fusion_entry.py does not exist for a known node, dispatch returns
        success=False with a descriptive error."""
        oc = _make_minimal_openclawd()
        oc._node_id_to_key["node_nofusion"] = "Node_nofusion"

        with patch("core.routes._helpers.nodes_root", "/fake/nodes"), \
             patch("os.path.exists", return_value=False):
            result = await oc._dispatch_tool_call(
                "node__node_nofusion__run", {}
            )

        assert result.get("success") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_skill_dispatch_failure_returns_error(self):
        """When the skill registry returns a failed response, dispatch must
        surface success=False with the error detail."""
        oc = _make_minimal_openclawd()

        mock_reg = MagicMock()
        mock_reg.has_skill.return_value = True
        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_err = MagicMock()
        mock_err.message = "Skill execution failed"
        mock_resp.first_error = mock_err
        mock_reg.invoke = AsyncMock(return_value=mock_resp)

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call("skill__broken_skill", {})

        assert result.get("success") is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_mcp_dispatch_exception_returns_error(self):
        """An exception from mcp_loader.call_tool must result in
        success=False rather than propagating to the caller."""
        oc = _make_minimal_openclawd()

        mock_loader = MagicMock()
        mock_loader.call_tool = AsyncMock(
            side_effect=RuntimeError("MCP server unavailable")
        )

        mock_reg = MagicMock()
        mock_reg._emit_log = MagicMock()

        with patch("core.mcp_loader.mcp_loader", mock_loader), \
             patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call("mcp__broken_server__tool", {})

        assert result.get("success") is False
        assert "error" in result


# ===========================================================================
# Section 5: ToolCallRecord / ToolLayer schema validation
# ===========================================================================


class TestToolCallSchema:
    """Verify the ToolCallRecord / ToolLayer classification contract."""

    def test_tool_layer_classify_node(self):
        from core.schemas.tool_call import ToolCallRecord, ToolLayer

        assert ToolCallRecord.classify_layer("node__my_node__run") == ToolLayer.NODE

    def test_tool_layer_classify_skill(self):
        from core.schemas.tool_call import ToolCallRecord, ToolLayer

        assert ToolCallRecord.classify_layer("skill__my_skill") == ToolLayer.SKILL

    def test_tool_layer_classify_mcp(self):
        from core.schemas.tool_call import ToolCallRecord, ToolLayer

        assert ToolCallRecord.classify_layer("mcp__my_server__my_tool") == ToolLayer.MCP

    def test_tool_layer_classify_mcp_gateway(self):
        from core.schemas.tool_call import ToolCallRecord, ToolLayer

        assert ToolCallRecord.classify_layer("mcp__gateway__gen_tool") == ToolLayer.MCP_GW

    def test_tool_call_record_round_trip(self):
        """ToolCallRecord must serialise and deserialise correctly for all layers."""
        from core.schemas.tool_call import ToolCallRecord, ToolCallStatus, ToolLayer

        for tool_name, expected_layer in [
            ("node__n1__action", ToolLayer.NODE),
            ("skill__s1", ToolLayer.SKILL),
            ("mcp__srv1__tool1", ToolLayer.MCP),
        ]:
            record = ToolCallRecord(
                tool_name=tool_name,
                layer=ToolCallRecord.classify_layer(tool_name),
                arguments={"k": "v"},
                result={"ok": True},
                status=ToolCallStatus.SUCCESS,
                iteration=1,
            )
            assert record.layer == expected_layer
            d = record.model_dump()
            assert d["tool_name"] == tool_name
            assert d["layer"] == expected_layer.value


# ===========================================================================
# Section 6: Regression guard — layer independence
# ===========================================================================


class TestLayerIndependenceRegression:
    """Regression: breaking one layer must not silently hide failures in
    the other two.  Each test exercises exactly one dispatch layer in
    isolation so a per-layer regression will cause only that test to fail."""

    def setup_method(self):
        _reset_all()

    @pytest.mark.asyncio
    async def test_node_layer_isolated(self):
        """Node dispatch succeeds independently of skill/mcp layers."""
        oc = _make_minimal_openclawd()
        oc._node_id_to_key["isolated_node"] = "Node_isolated"

        sentinel_result = {"isolated": "node_ok"}
        fake_node_info = {
            "type": "function",
            "execute": AsyncMock(return_value=sentinel_result),
            "module": None,
        }

        with patch("core.routes._helpers._load_node", return_value=fake_node_info), \
             patch("core.routes._helpers._execute_node",
                   new_callable=AsyncMock, return_value=sentinel_result), \
             patch("core.routes._helpers.nodes_root", "/fake"), \
             patch("os.path.exists", return_value=True):
            result = await oc._dispatch_tool_call(
                "node__isolated_node__run", {}
            )

        assert result["success"] is True
        assert result["result"] == sentinel_result

    @pytest.mark.asyncio
    async def test_skill_layer_isolated(self):
        """Skill dispatch succeeds independently of node/mcp layers."""
        oc = _make_minimal_openclawd()
        sentinel_result = {"isolated": "skill_ok"}

        mock_reg = MagicMock()
        mock_reg.has_skill.return_value = True
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.outputs = sentinel_result
        mock_reg.invoke = AsyncMock(return_value=mock_resp)

        with patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call(
                "skill__isolated_skill", {}
            )

        assert result["success"] is True
        assert result["result"] == sentinel_result

    @pytest.mark.asyncio
    async def test_mcp_layer_isolated(self):
        """MCP dispatch succeeds independently of node/skill layers."""
        oc = _make_minimal_openclawd()
        sentinel_result = {"isolated": "mcp_ok"}

        mock_loader = MagicMock()
        mock_loader.call_tool = AsyncMock(return_value=sentinel_result)
        mock_reg = MagicMock()
        mock_reg._emit_log = MagicMock()

        with patch("core.mcp_loader.mcp_loader", mock_loader), \
             patch("core.skill_registry.get_skill_registry", return_value=mock_reg):
            result = await oc._dispatch_tool_call(
                "mcp__isolated_srv__query", {}
            )

        assert result["success"] is True
        assert result["result"] == sentinel_result


# ===========================================================================
# Standalone runner (python -m pytest or direct execution)
# ===========================================================================

if __name__ == "__main__":
    import subprocess

    code = subprocess.call(
        [sys.executable, "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=str(PROJECT_ROOT),
    )
    sys.exit(code)
