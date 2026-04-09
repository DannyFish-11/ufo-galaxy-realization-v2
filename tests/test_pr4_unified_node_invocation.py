"""
tests/test_pr4_unified_node_invocation.py
=========================================
PR-4: Unified Node Invocation Envelope -- test suite.
"""

from __future__ import annotations
import pytest


class TestSentinels:
    def test_authority_sentinel_present(self):
        from core.node_invocation import UNIFIED_NODE_INVOCATION_AUTHORITY
        assert isinstance(UNIFIED_NODE_INVOCATION_AUTHORITY, str)
        assert "canonical" in UNIFIED_NODE_INVOCATION_AUTHORITY.lower()

    def test_pr4_sentinel_value(self):
        from core.node_invocation import UNIFIED_NODE_INVOCATION_PR4_SENTINEL
        assert UNIFIED_NODE_INVOCATION_PR4_SENTINEL == "UNIFIED_NODE_INVOCATION::PR4_SENTINEL_V1"

    def test_all_paths_converge_policy_present(self):
        from core.node_invocation import ALL_INVOCATION_PATHS_CONVERGE_ON_UNIFIED_EXECUTOR_POLICY
        assert "invoke_node" in ALL_INVOCATION_PATHS_CONVERGE_ON_UNIFIED_EXECUTOR_POLICY

    def test_trace_schema_policy_present(self):
        from core.node_invocation import INVOCATION_ENVELOPE_IS_CANONICAL_TRACE_SCHEMA_POLICY
        assert "request_id" in INVOCATION_ENVELOPE_IS_CANONICAL_TRACE_SCHEMA_POLICY
        assert "trace_id" in INVOCATION_ENVELOPE_IS_CANONICAL_TRACE_SCHEMA_POLICY

    def test_result_contract_policy_present(self):
        from core.node_invocation import RESULT_ENVELOPE_IS_CANONICAL_RESULT_CONTRACT_POLICY
        assert "NodeInvocationResult" in RESULT_ENVELOPE_IS_CANONICAL_RESULT_CONTRACT_POLICY


class TestNodeInvocationEnvelope:
    def test_required_fields(self):
        from core.node_invocation import NodeInvocationEnvelope, InvocationSource
        env = NodeInvocationEnvelope(node_id="Node_01", action="ping")
        assert env.node_id == "Node_01"
        assert env.action == "ping"
        assert isinstance(env.params, dict)

    def test_auto_ids(self):
        from core.node_invocation import NodeInvocationEnvelope
        env = NodeInvocationEnvelope(node_id="Node_01", action="ping")
        assert env.request_id and len(env.request_id) >= 8
        assert env.trace_id and env.trace_id.startswith("trace_")

    def test_source_defaults_unknown(self):
        from core.node_invocation import NodeInvocationEnvelope, InvocationSource
        env = NodeInvocationEnvelope(node_id="Node_01", action="ping")
        assert env.invocation_source == InvocationSource.UNKNOWN

    def test_defaults(self):
        from core.node_invocation import NodeInvocationEnvelope
        env = NodeInvocationEnvelope(node_id="Node_01", action="ping")
        assert env.execution_domain == "local"
        assert env.timeout_ms == 30_000.0
        assert env.task_id is None
        assert env.session_id is None

    def test_caller_supplied_ids(self):
        from core.node_invocation import NodeInvocationEnvelope, InvocationSource
        env = NodeInvocationEnvelope(
            node_id="Node_01", action="run",
            request_id="req-abc", trace_id="trace-xyz",
            task_id="task-001", session_id="sess-999",
            invocation_source=InvocationSource.REST,
        )
        assert env.request_id == "req-abc"
        assert env.trace_id == "trace-xyz"
        assert env.task_id == "task-001"
        assert env.invocation_source == InvocationSource.REST


class TestNodeInvocationResult:
    def test_success_fields(self):
        from core.node_invocation import NodeInvocationResult
        r = NodeInvocationResult(
            success=True, node_id="Node_01", action="ping",
            request_id="r1", trace_id="t1", result={"ok": True}, duration_ms=5.0,
        )
        assert r.success is True
        assert r.error is None

    def test_failure_fields(self):
        from core.node_invocation import NodeInvocationResult
        r = NodeInvocationResult(
            success=False, node_id="Node_01", action="ping",
            request_id="r2", trace_id="t2", error="not found",
        )
        assert r.success is False
        assert r.result is None

    def test_to_legacy_dict_success(self):
        from core.node_invocation import NodeInvocationResult
        r = NodeInvocationResult(
            success=True, node_id="Node_01", action="ping",
            request_id="r3", trace_id="t3", result={"data": "hi"}, duration_ms=3.0,
        )
        d = r.to_legacy_dict()
        assert d["success"] is True
        assert d["request_id"] == "r3"
        assert d["trace_id"] == "t3"
        assert "result" in d

    def test_to_legacy_dict_failure(self):
        from core.node_invocation import NodeInvocationResult
        r = NodeInvocationResult(
            success=False, node_id="Node_01", action="ping",
            request_id="r4", trace_id="t4", error="oops",
        )
        d = r.to_legacy_dict()
        assert d["success"] is False
        assert d["error"] == "oops"
        assert "result" not in d


class TestInvocationSource:
    def test_all_sources_present(self):
        from core.node_invocation import InvocationSource
        values = {s.value for s in InvocationSource}
        assert "openclawd" in values
        assert "rest" in values
        assert "command" in values
        assert "capability" in values
        assert "system" in values
        assert "unknown" in values


class TestInvokeNodeMissingNode:
    @pytest.mark.asyncio
    async def test_missing_node_returns_failed_result(self):
        from core.node_invocation import invoke_node, NodeInvocationResult
        result = await invoke_node("Node_DOES_NOT_EXIST_XXXX", "ping", {})
        assert isinstance(result, NodeInvocationResult)
        assert result.success is False
        assert result.error

    @pytest.mark.asyncio
    async def test_missing_node_carries_trace_ids(self):
        from core.node_invocation import invoke_node
        result = await invoke_node(
            "Node_DOES_NOT_EXIST_YYYY", "run", {},
            request_id="req-test-001", trace_id="trace-test-001",
        )
        assert result.request_id == "req-test-001"
        assert result.trace_id == "trace-test-001"

    @pytest.mark.asyncio
    async def test_invocation_source_preserved(self):
        from core.node_invocation import invoke_node, InvocationSource
        result = await invoke_node(
            "Node_NONE_EVER", "act", {},
            invocation_source=InvocationSource.REST,
        )
        assert result.execution_source == "rest"

    @pytest.mark.asyncio
    async def test_duration_non_negative(self):
        from core.node_invocation import invoke_node
        result = await invoke_node("Node_NONE_EVER", "act", {})
        assert result.duration_ms >= 0.0


class TestSingleton:
    def test_get_unified_node_executor_singleton(self):
        from core.node_invocation import get_unified_node_executor
        e1 = get_unified_node_executor()
        e2 = get_unified_node_executor()
        assert e1 is e2


class TestProjectionSentinel:
    def test_projection_sentinel_importable(self):
        from core.routes.projection import UNIFIED_NODE_INVOCATION_ALIGNED_PR4
        assert isinstance(UNIFIED_NODE_INVOCATION_ALIGNED_PR4, str)
        assert "PR4" in UNIFIED_NODE_INVOCATION_ALIGNED_PR4
        assert "UNAVAILABLE" not in UNIFIED_NODE_INVOCATION_ALIGNED_PR4

    def test_projection_sentinel_mentions_invoke_node(self):
        from core.routes.projection import UNIFIED_NODE_INVOCATION_ALIGNED_PR4
        assert "invoke_node" in UNIFIED_NODE_INVOCATION_ALIGNED_PR4


class TestInvocationPathImports:
    def test_nodes_route_imports_invoke_node(self):
        import importlib
        import core.routes.nodes as m
        assert hasattr(m, "invoke_node") or hasattr(m, "InvocationSource")

    def test_command_route_imports_invoke_node(self):
        import core.routes.command as m
        assert hasattr(m, "invoke_node") or hasattr(m, "InvocationSource")

    def test_canonical_dispatcher_uses_invoke_node(self):
        import inspect, core.capabilities.canonical_dispatcher as m
        src = inspect.getsource(m)
        assert "invoke_node" in src

    def test_openclawd_uses_invoke_node(self):
        import inspect, core.openclawd as m
        src = inspect.getsource(m)
        assert "invoke_node" in src

    def test_system_integration_uses_invoke_node(self):
        import inspect, core.system_integration as m
        src = inspect.getsource(m)
        assert "invoke_node" in src
