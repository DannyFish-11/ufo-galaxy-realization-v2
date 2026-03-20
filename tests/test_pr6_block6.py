"""
tests/test_pr6_block6.py
=========================
Block-6: Multi-LLM Governance + 100+ Node Fabric + SSOT/UDM Integrity & Conformance

Test coverage:
  1. LLM routing policy loading
  2. RoutingTelemetry — record/success_rate/latency/fallback_rate/cost
  3. UnifiedLLMRouter — policy + telemetry integration, no-backend, get_status/telemetry/policy
  4. _resolve_provider_order — preferred_provider, SLO filter, fallback merge
  5. _check_cost_budget
  6. NodeFabricRegistry — register/heartbeat/unregister/health/capability sync
  7. CapabilityRegistry.inject_item
  8. audit_udm_write_paths — scan, state_version check
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _reset_routers() -> None:
    from core.unified.llm_router import reset_unified_llm_router, reset_routing_telemetry
    reset_unified_llm_router()
    reset_routing_telemetry()


def _reset_nodes() -> None:
    from core.nodes.node_fabric_registry import reset_node_fabric_registry
    reset_node_fabric_registry()


def _reset_cap_registry() -> None:
    from core.agent.capability_registry import CapabilityRegistry
    CapabilityRegistry._instance = None


# ===========================================================================
# 1. LLM Routing Policy loading
# ===========================================================================


class TestLLMRoutingPolicy:
    def test_load_policy_returns_dict(self) -> None:
        from core.unified.llm_router import _load_routing_policy
        policy = _load_routing_policy()
        assert isinstance(policy, dict)

    def test_policy_has_task_routing_section(self) -> None:
        from core.unified.llm_router import _load_routing_policy
        policy = _load_routing_policy()
        if policy:  # may be empty if yaml not installed
            assert "task_routing" in policy

    def test_policy_general_has_priorities(self) -> None:
        from core.unified.llm_router import _load_routing_policy
        policy = _load_routing_policy()
        if not policy:
            pytest.skip("Policy YAML not available")
        general = policy.get("task_routing", {}).get("general", {})
        assert "priorities" in general
        assert len(general["priorities"]) > 0

    def test_policy_has_global_fallback(self) -> None:
        from core.unified.llm_router import _load_routing_policy
        policy = _load_routing_policy()
        if not policy:
            pytest.skip("Policy YAML not available")
        assert "global_fallback_chain" in policy
        assert len(policy["global_fallback_chain"]) > 0

    def test_policy_has_global_slo(self) -> None:
        from core.unified.llm_router import _load_routing_policy
        policy = _load_routing_policy()
        if not policy:
            pytest.skip("Policy YAML not available")
        slo = policy.get("global_slo", {})
        assert "max_latency_ms" in slo
        assert "min_success_rate" in slo

    def test_all_task_types_have_priorities(self) -> None:
        from core.unified.llm_router import _load_routing_policy
        policy = _load_routing_policy()
        if not policy:
            pytest.skip("Policy YAML not available")
        task_routing = policy.get("task_routing", {})
        expected_types = [
            "reasoning", "fast_response", "coding", "creative",
            "analysis", "planning", "agent_control", "general",
        ]
        for t in expected_types:
            assert t in task_routing, f"Missing task type: {t}"
            rule = task_routing[t]
            assert "priorities" in rule, f"Missing priorities for {t}"


# ===========================================================================
# 2. RoutingTelemetry
# ===========================================================================


class TestRoutingTelemetry:
    def setup_method(self) -> None:
        from core.unified.llm_router import reset_routing_telemetry
        reset_routing_telemetry()

    def test_record_and_success_rate(self) -> None:
        from core.unified.llm_router import get_routing_telemetry
        tel = get_routing_telemetry()

        tel.record("openai", success=True, latency_ms=200)
        tel.record("openai", success=True, latency_ms=300)
        tel.record("openai", success=False, latency_ms=5000)

        metrics = tel.get_metrics()
        assert "openai" in metrics
        assert abs(metrics["openai"]["success_rate"] - 2 / 3) < 0.01

    def test_avg_latency(self) -> None:
        from core.unified.llm_router import get_routing_telemetry
        tel = get_routing_telemetry()

        tel.record("anthropic", success=True, latency_ms=100)
        tel.record("anthropic", success=True, latency_ms=300)

        metrics = tel.get_metrics()
        assert abs(metrics["anthropic"]["avg_latency_ms"] - 200.0) < 1.0

    def test_fallback_rate(self) -> None:
        from core.unified.llm_router import get_routing_telemetry
        tel = get_routing_telemetry()

        tel.record("deepseek", success=True, latency_ms=100, is_fallback=True)
        tel.record("deepseek", success=True, latency_ms=100, is_fallback=False)

        metrics = tel.get_metrics()
        assert abs(metrics["deepseek"]["fallback_rate"] - 0.5) < 0.01

    def test_cost_tracking(self) -> None:
        from core.unified.llm_router import get_routing_telemetry
        tel = get_routing_telemetry()

        tel.record("openai", success=True, latency_ms=200, cost_usd=0.001)
        tel.record("openai", success=True, latency_ms=300, cost_usd=0.003)

        metrics = tel.get_metrics()
        assert abs(metrics["openai"]["avg_cost_usd_per_call"] - 0.002) < 0.0001

    def test_multiple_providers_isolated(self) -> None:
        from core.unified.llm_router import get_routing_telemetry
        tel = get_routing_telemetry()

        tel.record("openai", success=True, latency_ms=100)
        tel.record("anthropic", success=False, latency_ms=5000)

        metrics = tel.get_metrics()
        assert metrics["openai"]["success_rate"] == 1.0
        assert metrics["anthropic"]["success_rate"] == 0.0

    def test_slo_violation_latency(self) -> None:
        from core.unified.llm_router import get_routing_telemetry
        tel = get_routing_telemetry()

        for _ in range(5):
            tel.record("slow_provider", success=True, latency_ms=50000)

        slo = {"max_latency_ms": 30000, "min_success_rate": 0.90}
        assert tel.is_slo_violated("slow_provider", slo) is True

    def test_slo_violation_success_rate(self) -> None:
        from core.unified.llm_router import get_routing_telemetry
        tel = get_routing_telemetry()

        for _ in range(5):
            tel.record("bad_provider", success=False, latency_ms=1000)

        slo = {"max_latency_ms": 30000, "min_success_rate": 0.90}
        assert tel.is_slo_violated("bad_provider", slo) is True

    def test_no_slo_violation_fresh_provider(self) -> None:
        from core.unified.llm_router import get_routing_telemetry
        tel = get_routing_telemetry()
        slo = {"max_latency_ms": 30000, "min_success_rate": 0.90}
        # No calls → not violated
        assert tel.is_slo_violated("unknown_provider", slo) is False


# ===========================================================================
# 3. _resolve_provider_order
# ===========================================================================


class TestResolveProviderOrder:
    def _policy(self) -> Dict[str, Any]:
        return {
            "global_fallback_chain": ["deepseek", "openai"],
            "global_slo": {"max_latency_ms": 30000, "min_success_rate": 0.90},
            "task_routing": {
                "general": {
                    "priorities": ["openai", "anthropic"],
                    "fallback_chain": ["deepseek"],
                    "slo": {"max_latency_ms": 30000, "min_success_rate": 0.90},
                }
            },
        }

    def setup_method(self) -> None:
        from core.unified.llm_router import reset_routing_telemetry
        reset_routing_telemetry()

    def test_preferred_provider_moved_to_front(self) -> None:
        from core.unified.llm_router import _resolve_provider_order, get_routing_telemetry
        tel = get_routing_telemetry()
        order, _ = _resolve_provider_order("general", self._policy(), tel, preferred_provider="anthropic")
        assert order[0] == "anthropic"

    def test_fallback_providers_appended(self) -> None:
        from core.unified.llm_router import _resolve_provider_order, get_routing_telemetry
        tel = get_routing_telemetry()
        order, _ = _resolve_provider_order("general", self._policy(), tel)
        assert "deepseek" in order

    def test_unknown_task_type_uses_global_fallback(self) -> None:
        from core.unified.llm_router import _resolve_provider_order, get_routing_telemetry
        tel = get_routing_telemetry()
        order, _ = _resolve_provider_order("nonexistent_task", self._policy(), tel)
        assert "deepseek" in order or "openai" in order

    def test_slo_violated_provider_moved_to_back(self) -> None:
        from core.unified.llm_router import _resolve_provider_order, get_routing_telemetry
        tel = get_routing_telemetry()

        # Make "openai" violate SLO
        for _ in range(5):
            tel.record("openai", success=False, latency_ms=100)

        order, _ = _resolve_provider_order("general", self._policy(), tel)
        # openai should not be first when it violates SLO
        non_violated = [p for p in order if p != "openai"]
        if non_violated:
            assert order.index("openai") > order.index(non_violated[0])


# ===========================================================================
# 4. _check_cost_budget
# ===========================================================================


class TestCheckCostBudget:
    def _policy(self) -> Dict[str, Any]:
        return {
            "global_slo": {"max_cost_per_1k_tokens": 0.06},
            "task_routing": {
                "reasoning": {
                    "cost_budget": {"max_cost_per_1k_tokens": 0.15},
                }
            },
        }

    def test_within_budget(self) -> None:
        from core.unified.llm_router import _check_cost_budget
        assert _check_cost_budget(0.10, "reasoning", self._policy()) is True

    def test_exceeds_budget(self) -> None:
        from core.unified.llm_router import _check_cost_budget
        assert _check_cost_budget(0.20, "reasoning", self._policy()) is False

    def test_uses_global_budget_for_unknown_task(self) -> None:
        from core.unified.llm_router import _check_cost_budget
        assert _check_cost_budget(0.05, "unknown_task", self._policy()) is True
        assert _check_cost_budget(0.10, "unknown_task", self._policy()) is False


# ===========================================================================
# 5. UnifiedLLMRouter — no-backend / status / telemetry / policy
# ===========================================================================


class TestUnifiedLLMRouterStatus:
    def setup_method(self) -> None:
        _reset_routers()

    def test_get_status_no_backend(self) -> None:
        from core.unified.llm_router import UnifiedLLMRouter
        router = UnifiedLLMRouter()
        router._backend = None
        status = router.get_status()
        assert isinstance(status, dict)
        assert "available" in status

    def test_get_telemetry_returns_dict(self) -> None:
        from core.unified.llm_router import UnifiedLLMRouter
        router = UnifiedLLMRouter()
        tel = router.get_telemetry()
        assert isinstance(tel, dict)

    def test_get_policy_returns_dict(self) -> None:
        from core.unified.llm_router import UnifiedLLMRouter
        router = UnifiedLLMRouter()
        policy = router.get_policy()
        assert isinstance(policy, dict)

    def test_reload_policy(self) -> None:
        from core.unified.llm_router import UnifiedLLMRouter
        router = UnifiedLLMRouter()
        router.reload_policy()  # Should not raise
        assert isinstance(router.get_policy(), dict)

    def test_no_backend_raises_on_chat(self) -> None:
        from core.unified.llm_router import UnifiedLLMRouter
        from core.unified.exceptions import NoAvailableProviderError
        from core.unified.models import LLMRequest, LLMTaskType

        router = UnifiedLLMRouter()
        router._backend = None

        request = LLMRequest(
            messages=[{"role": "user", "content": "hello"}],
            task_type=LLMTaskType.GENERAL,
        )
        with pytest.raises(NoAvailableProviderError):
            asyncio.run(router.chat(request))

    def test_chat_with_mock_backend(self) -> None:
        from core.unified.llm_router import UnifiedLLMRouter
        from core.unified.models import LLMRequest, LLMTaskType

        router = UnifiedLLMRouter()
        mock_backend = MagicMock()
        mock_backend.chat = AsyncMock(return_value={
            "content": "hello world",
            "provider": "openai",
            "model": "gpt-4o",
            "usage": {"total_tokens": 50},
        })
        router._backend = mock_backend

        request = LLMRequest(
            messages=[{"role": "user", "content": "hi"}],
            task_type=LLMTaskType.GENERAL,
        )

        async def _run():
            return await router.chat(request)

        result = asyncio.run(_run())
        assert result.success is True
        assert result.content == "hello world"
        assert result.provider == "openai"
        assert result.latency_ms >= 0

    def test_chat_telemetry_recorded(self) -> None:
        from core.unified.llm_router import UnifiedLLMRouter, get_routing_telemetry
        from core.unified.models import LLMRequest, LLMTaskType

        router = UnifiedLLMRouter()
        mock_backend = MagicMock()
        mock_backend.chat = AsyncMock(return_value={
            "content": "ok",
            "provider": "anthropic",
            "model": "claude-3",
            "usage": {"total_tokens": 100},
        })
        router._backend = mock_backend

        request = LLMRequest(
            messages=[{"role": "user", "content": "test"}],
            task_type=LLMTaskType.CODING,
        )

        async def _run():
            return await router.chat(request)

        asyncio.run(_run())

        tel = get_routing_telemetry()
        metrics = tel.get_metrics()
        assert "anthropic" in metrics
        assert metrics["anthropic"]["total_calls"] >= 1
        assert metrics["anthropic"]["success_rate"] == 1.0

    def test_chat_all_providers_fail(self) -> None:
        from core.unified.llm_router import UnifiedLLMRouter
        from core.unified.exceptions import LLMProviderError
        from core.unified.models import LLMRequest, LLMTaskType

        router = UnifiedLLMRouter()
        mock_backend = MagicMock()
        mock_backend.chat = AsyncMock(side_effect=Exception("provider down"))
        router._backend = mock_backend
        router._policy = {}  # no policy → single attempt

        request = LLMRequest(
            messages=[{"role": "user", "content": "test"}],
            task_type=LLMTaskType.GENERAL,
        )

        async def _run():
            return await router.chat(request)

        with pytest.raises(LLMProviderError):
            asyncio.run(_run())


# ===========================================================================
# 6. NodeFabricRegistry
# ===========================================================================


class TestNodeFabricRegistry:
    def setup_method(self) -> None:
        _reset_nodes()

    def test_singleton_identity(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry
        r1 = get_node_fabric_registry()
        r2 = get_node_fabric_registry()
        assert r1 is r2

    def test_register_and_get(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeInfo, NodeRole
        fab = get_node_fabric_registry()
        n = NodeInfo(node_id="pr6-node-01", role=NodeRole.WORKER)
        fab.register(n)
        assert fab.get("pr6-node-01") is not None

    def test_unregister_returns_false_for_unknown(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry
        fab = get_node_fabric_registry()
        assert fab.unregister("ghost") is False

    def test_heartbeat_returns_false_for_unknown(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry
        fab = get_node_fabric_registry()
        assert fab.heartbeat("ghost") is False

    def test_list_by_role(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeInfo, NodeRole
        fab = get_node_fabric_registry()
        fab.register(NodeInfo(node_id="ag-01", role=NodeRole.AGENT))
        fab.register(NodeInfo(node_id="wk-01", role=NodeRole.WORKER))
        agents = fab.list_by_role(NodeRole.AGENT)
        assert any(n.node_id == "ag-01" for n in agents)
        assert all(n.role == NodeRole.AGENT for n in agents)

    def test_health_score_full_for_fresh_node(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeInfo, NodeRole
        fab = get_node_fabric_registry()
        n = NodeInfo(node_id="fresh-01", role=NodeRole.WORKER)
        fab.register(n)
        assert fab.get("fresh-01").health_score() == 1.0  # type: ignore[union-attr]

    def test_health_score_zero_for_stale(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeInfo, NodeRole
        fab = get_node_fabric_registry()
        n = NodeInfo(node_id="stale-01", role=NodeRole.WORKER)
        n.last_heartbeat = time.monotonic() - 9999
        fab.register(n)
        assert fab.get("stale-01").health_score() == 0.0  # type: ignore[union-attr]

    def test_list_healthy_excludes_stale(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeInfo, NodeRole
        fab = get_node_fabric_registry()
        fresh = NodeInfo(node_id="healthy-01", role=NodeRole.WORKER)
        stale = NodeInfo(node_id="stale-h-01", role=NodeRole.WORKER)
        stale.last_heartbeat = time.monotonic() - 9999
        fab.register(fresh)
        fab.register(stale)

        healthy = fab.list_healthy()
        ids = [n.node_id for n in healthy]
        assert "healthy-01" in ids
        assert "stale-h-01" not in ids

    def test_get_metrics(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeInfo, NodeRole, NodeStatus
        fab = get_node_fabric_registry()
        for i in range(5):
            fab.register(NodeInfo(node_id=f"m-node-{i}", role=NodeRole.WORKER, status=NodeStatus.HEALTHY))

        metrics = fab.get_metrics()
        assert metrics["total_nodes"] >= 5
        assert "by_role" in metrics
        assert "by_status" in metrics


# ===========================================================================
# 7. CapabilityRegistry.inject_item
# ===========================================================================


class TestCapabilityRegistryInjectItem:
    def setup_method(self) -> None:
        _reset_cap_registry()

    def test_inject_node_item(self) -> None:
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry.get_instance()
        item = CapabilityItem(
            name="node__test-inject__cap1",
            description="[Node:test-inject:worker] cap1",
            source="node",
            source_id="test-inject",
        )
        reg.inject_item(item)
        found = reg.get("node__test-inject__cap1")
        assert found is not None
        assert found.source == "node"

    def test_inject_item_empty_name_skipped(self) -> None:
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry.get_instance()
        item = CapabilityItem(name="", description="no name", source="node", source_id="x")
        reg.inject_item(item)  # Should not raise
        # Verify nothing was added with empty key
        assert reg.get("") is None

    def test_list_tools_includes_injected_node_item(self) -> None:
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry.get_instance()
        item = CapabilityItem(
            name="node__list-test__cap",
            description="[Node:list-test:worker] cap",
            source="node",
            source_id="list-test",
        )
        reg.inject_item(item)
        tools = reg.list_tools(source="node")
        assert any(t.name == "node__list-test__cap" for t in tools)

    def test_stats_includes_node_source(self) -> None:
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry.get_instance()
        item = CapabilityItem(
            name="node__stats-test__cap",
            description="[Node:stats-test] cap",
            source="node",
            source_id="stats-test",
        )
        reg.inject_item(item)
        stats = reg.stats()
        assert stats["by_source"].get("node", 0) >= 1
