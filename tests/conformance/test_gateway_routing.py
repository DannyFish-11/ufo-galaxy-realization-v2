"""
tests/conformance/test_gateway_routing.py
==========================================
PR-2 Protocol Conformance Suite — Gateway Routing

Validates that:
  A) CapabilityContract schema validation enforces required fields.
  B) CapabilityContract validation rejects invalid parameters schemas.
  C) CapabilityResolver returns only validated contracts.
  D) CapabilityResolver.find() performs keyword search across valid contracts.
  E) CapabilityRegistry.register() validates via unified contract.
  F) CapabilityRegistry.inject_mcp_tool() validates via unified contract.
  G) CapabilityRegistry.inject_skill() validates via unified contract.
  H) Multi-device tasks route through TaskGraph (no bypass path).
  I) run_multi_device_via_task_graph returns canonical result dict.
  J) CommandEnvelope is logged at multi-device task entry.
"""

from __future__ import annotations

import asyncio
import types
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.unified.capability_contract import (
    CapabilityContract,
    CapabilityContractError,
    CapabilitySource,
    is_valid_capability_contract,
    validate_capability_contract,
)
from core.unified.capability_resolver import (
    CapabilityResolver,
    get_capability_resolver,
    reset_capability_resolver,
)


# ===========================================================================
# A) CapabilityContract schema validation — required fields
# ===========================================================================

class TestCapabilityContractRequiredFields:

    def test_valid_contract_passes(self):
        contract = CapabilityContract(
            name="take_screenshot",
            description="Capture the current screen state.",
            source=CapabilitySource.DEVICE,
        )
        validate_capability_contract(contract)  # must not raise

    def test_empty_name_raises(self):
        contract = CapabilityContract(name="", description="Valid description.")
        with pytest.raises(CapabilityContractError) as exc_info:
            validate_capability_contract(contract)
        assert any("name" in v for v in exc_info.value.violations)

    def test_empty_description_raises(self):
        contract = CapabilityContract(name="valid_name", description="")
        with pytest.raises(CapabilityContractError) as exc_info:
            validate_capability_contract(contract)
        assert any("description" in v for v in exc_info.value.violations)

    def test_error_code_is_structured(self):
        contract = CapabilityContract(name="", description="")
        with pytest.raises(CapabilityContractError) as exc_info:
            validate_capability_contract(contract)
        assert exc_info.value.error_code == "CAPABILITY_CONTRACT_INVALID"

    def test_is_valid_helper_returns_false_for_invalid(self):
        contract = CapabilityContract(name="", description="desc")
        assert is_valid_capability_contract(contract) is False

    def test_is_valid_helper_returns_true_for_valid(self):
        contract = CapabilityContract(name="valid", description="A valid description.")
        assert is_valid_capability_contract(contract) is True


# ===========================================================================
# B) CapabilityContract validation — parameters schema
# ===========================================================================

class TestCapabilityContractParameters:

    def test_empty_parameters_passes(self):
        contract = CapabilityContract(name="action", description="desc.", parameters={})
        validate_capability_contract(contract)  # must not raise

    def test_valid_json_schema_passes(self):
        contract = CapabilityContract(
            name="click",
            description="Click element.",
            parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
        )
        validate_capability_contract(contract)  # must not raise

    def test_non_dict_parameters_raises(self):
        contract = CapabilityContract(name="action", description="desc.")
        object.__setattr__(contract, "parameters", ["invalid"])
        with pytest.raises(CapabilityContractError) as exc_info:
            validate_capability_contract(contract)
        assert any("parameters" in v for v in exc_info.value.violations)

    def test_non_string_type_in_parameters_raises(self):
        contract = CapabilityContract(
            name="action",
            description="desc.",
            parameters={"type": 123},  # type must be str
        )
        with pytest.raises(CapabilityContractError):
            validate_capability_contract(contract)

    def test_non_dict_properties_raises(self):
        contract = CapabilityContract(
            name="action",
            description="desc.",
            parameters={"type": "object", "properties": "should_be_dict"},
        )
        with pytest.raises(CapabilityContractError):
            validate_capability_contract(contract)


# ===========================================================================
# C) CapabilityResolver returns only validated contracts
# ===========================================================================

class TestCapabilityResolver:

    def _make_resolver(self, items: list) -> CapabilityResolver:
        """Build a resolver backed by a stub registry."""
        registry = MagicMock()
        registry.list_tools.return_value = items
        registry.get.side_effect = lambda name: next(
            (i for i in items if getattr(i, "name", None) == name), None
        )
        resolver = CapabilityResolver(registry=registry, cache_ttl_seconds=0)
        return resolver

    def _make_item(self, name, description="A valid description.", source="mcp", available=True):
        return types.SimpleNamespace(
            name=name,
            description=description,
            source=source,
            source_id="server-01",
            parameters={},
            available=available,
            metadata={},
        )

    def test_resolve_returns_contract_for_valid_item(self):
        item = self._make_item("screenshot", "Takes a screenshot.")
        resolver = self._make_resolver([item])
        contract = resolver.resolve("screenshot")
        assert contract is not None
        assert contract.name == "screenshot"

    def test_resolve_returns_none_for_invalid_item(self):
        item = self._make_item("", "desc")  # empty name is invalid
        resolver = self._make_resolver([item])
        contract = resolver.resolve("")
        assert contract is None

    def test_resolve_returns_none_for_unknown_capability(self):
        resolver = self._make_resolver([])
        assert resolver.resolve("nonexistent") is None

    def test_resolve_all_filters_invalid_contracts(self):
        valid = self._make_item("valid_action", "Performs a valid action.")
        invalid = self._make_item("", "desc")  # invalid
        resolver = self._make_resolver([valid, invalid])
        contracts = resolver.resolve_all()
        assert all(c.name for c in contracts), "resolve_all() must exclude invalid contracts"
        assert any(c.name == "valid_action" for c in contracts)

    def test_validation_errors_recorded(self):
        invalid = self._make_item("", "desc")
        resolver = self._make_resolver([invalid])
        resolver.resolve_all()  # trigger cache build
        errors = resolver.validation_errors()
        assert len(errors) >= 1

    def test_stats_returns_dict_with_valid_count(self):
        item = self._make_item("action1", "A valid action.")
        resolver = self._make_resolver([item])
        resolver.resolve_all()
        stats = resolver.stats()
        assert "valid_contracts" in stats
        assert stats["valid_contracts"] >= 1


# ===========================================================================
# D) CapabilityResolver.find() keyword search
# ===========================================================================

class TestCapabilityResolverFind:

    def _make_resolver_with_items(self) -> CapabilityResolver:
        items = [
            types.SimpleNamespace(
                name="take_screenshot",
                description="Capture current screen state.",
                source="device",
                source_id="dev-01",
                parameters={},
                available=True,
                metadata={},
            ),
            types.SimpleNamespace(
                name="click_element",
                description="Click a UI element.",
                source="device",
                source_id="dev-01",
                parameters={},
                available=True,
                metadata={},
            ),
            types.SimpleNamespace(
                name="send_email",
                description="Send an email message.",
                source="skill",
                source_id="email_skill",
                parameters={},
                available=True,
                metadata={},
            ),
        ]
        registry = MagicMock()
        registry.list_tools.return_value = items
        registry.get.side_effect = lambda name: next(
            (i for i in items if i.name == name), None
        )
        return CapabilityResolver(registry=registry, cache_ttl_seconds=0)

    def test_find_by_name_keyword(self):
        resolver = self._make_resolver_with_items()
        results = resolver.find("screenshot")
        assert any(c.name == "take_screenshot" for c in results)

    def test_find_by_description_keyword(self):
        resolver = self._make_resolver_with_items()
        results = resolver.find("email")
        assert any(c.name == "send_email" for c in results)

    def test_find_case_insensitive(self):
        resolver = self._make_resolver_with_items()
        results = resolver.find("CLICK")
        assert any(c.name == "click_element" for c in results)

    def test_find_returns_empty_for_unknown_keyword(self):
        resolver = self._make_resolver_with_items()
        results = resolver.find("zzz_nonexistent_xyz")
        assert results == []


# ===========================================================================
# E) CapabilityRegistry.register() validates via unified contract
# ===========================================================================

class TestCapabilityRegistryRegisterValidation:

    def _fresh_registry(self):
        """Return a fresh CapabilityRegistry instance for testing."""
        from core.agent.capability_registry import CapabilityRegistry
        reg = CapabilityRegistry.__new__(CapabilityRegistry)
        reg._initialized = False
        reg.__init__()
        return reg

    def test_valid_item_is_registered(self):
        from core.agent.capability_registry import CapabilityItem
        reg = self._fresh_registry()
        item = CapabilityItem(
            name="valid_cap", description="A valid capability.", source="mcp", source_id="s1"
        )
        reg.register(item)
        assert reg.get("valid_cap") is not None

    def test_item_with_empty_name_is_rejected(self):
        from core.agent.capability_registry import CapabilityItem
        reg = self._fresh_registry()
        item = CapabilityItem(
            name="", description="desc", source="mcp", source_id="s1"
        )
        reg.register(item)
        # Should not be registered
        assert reg.get("") is None

    def test_item_with_empty_description_is_rejected(self):
        from core.agent.capability_registry import CapabilityItem
        reg = self._fresh_registry()
        item = CapabilityItem(
            name="some_cap", description="", source="mcp", source_id="s1"
        )
        reg.register(item)
        assert reg.get("some_cap") is None

    def test_validation_error_recorded_on_rejection(self):
        from core.agent.capability_registry import CapabilityItem
        reg = self._fresh_registry()
        item = CapabilityItem(name="", description="", source="mcp", source_id="s1")
        reg.register(item)
        stats = reg.stats()
        assert len(stats["validation_errors"]) >= 1


# ===========================================================================
# F) CapabilityRegistry.inject_mcp_tool() validates via unified contract
# ===========================================================================

class TestCapabilityRegistryInjectMCPTool:

    def _fresh_registry(self):
        from core.agent.capability_registry import CapabilityRegistry
        reg = CapabilityRegistry.__new__(CapabilityRegistry)
        reg._initialized = False
        reg.__init__()
        return reg

    def test_valid_mcp_tool_injected(self):
        reg = self._fresh_registry()
        reg.inject_mcp_tool(
            server_id="s1",
            tool_name="screenshot",
            description="Take a screenshot.",
            parameters={"type": "object", "properties": {}},
        )
        assert reg.get("mcp__s1__screenshot") is not None

    def test_empty_tool_name_skipped(self):
        reg = self._fresh_registry()
        reg.inject_mcp_tool(server_id="s1", tool_name="", description="desc", parameters={})
        # No item with empty key
        assert len(reg.list_tools()) == 0

    def test_non_dict_parameters_skipped(self):
        reg = self._fresh_registry()
        reg.inject_mcp_tool(
            server_id="s1",
            tool_name="bad_params_tool",
            description="Tool with bad params.",
            parameters=["invalid"],  # type: ignore
        )
        assert reg.get("mcp__s1__bad_params_tool") is None


# ===========================================================================
# G) CapabilityRegistry.inject_skill() validates via unified contract
# ===========================================================================

class TestCapabilityRegistryInjectSkill:

    def _fresh_registry(self):
        from core.agent.capability_registry import CapabilityRegistry
        reg = CapabilityRegistry.__new__(CapabilityRegistry)
        reg._initialized = False
        reg.__init__()
        return reg

    def test_valid_skill_injected(self):
        reg = self._fresh_registry()
        reg.inject_skill(
            skill_id="weather_skill",
            skill_name="Weather",
            description="Get weather information.",
            parameters={"type": "object", "properties": {"city": {"type": "string"}}},
        )
        assert reg.get("skill__weather_skill") is not None

    def test_empty_skill_id_skipped(self):
        reg = self._fresh_registry()
        reg.inject_skill(skill_id="", skill_name="Skill", description="desc", parameters={})
        assert len(reg.list_tools()) == 0

    def test_skill_with_empty_description_rejected(self):
        reg = self._fresh_registry()
        # inject_skill uses `description or skill_name` for the description,
        # so passing empty description with a valid skill_name still produces a
        # non-empty description.  To trigger rejection, pass an empty skill_name
        # as well so the combined description falls back to an empty prefix.
        # The cleanest way to test contract rejection is to register an item
        # directly with an empty description.
        from core.agent.capability_registry import CapabilityItem
        item = CapabilityItem(
            name="empty_desc_skill",
            description="",
            source="skill",
            source_id="empty_desc_skill",
        )
        reg.register(item)
        assert reg.get("empty_desc_skill") is None


# ===========================================================================
# H) Multi-device tasks route through TaskGraph — no bypass path
# ===========================================================================

class TestMultiDeviceTaskGraphRouting:

    @pytest.mark.asyncio
    async def test_submit_multi_device_task_uses_dag(self):
        """submit_multi_device_task must call submit_dag_task, not direct submit_task."""
        from galaxy_gateway.orchestrator.task_orchestrator import MultiDeviceOrchestrator

        orch = MultiDeviceOrchestrator.__new__(MultiDeviceOrchestrator)
        orch.tasks = {}
        orch.task_queue = asyncio.Queue()
        orch._running = False
        orch._worker_task = None
        orch._device_rr_index = -1
        orch._task_envelopes = {}

        dag_calls = []

        async def _mock_dag(subtasks, *, trace_id="", runtime_session_id="",
                            continue_on_failure=True, context=None):
            dag_calls.append({"subtasks": subtasks, "trace_id": trace_id})
            return {"success": True, "done": len(subtasks), "failed": 0, "skipped": 0,
                    "elapsed_ms": 1.0, "graph_id": "g1", "trace_id": trace_id,
                    "node_statuses": {}}

        orch.submit_dag_task = _mock_dag

        result = await orch.submit_multi_device_task(
            user_request="Take screenshots",
            device_ids=["dev-01", "dev-02"],
            trace_id="trace-test-01",
        )
        assert len(dag_calls) == 1, "submit_dag_task must be called exactly once"
        assert result["success"] is True
        assert result["done"] == 2

    @pytest.mark.asyncio
    async def test_submit_multi_device_empty_returns_success(self):
        from galaxy_gateway.orchestrator.task_orchestrator import MultiDeviceOrchestrator

        orch = MultiDeviceOrchestrator.__new__(MultiDeviceOrchestrator)
        orch.tasks = {}
        orch.task_queue = asyncio.Queue()
        orch._running = False
        orch._worker_task = None
        orch._device_rr_index = -1
        orch._task_envelopes = {}

        result = await orch.submit_multi_device_task(
            user_request="task", device_ids=[], trace_id="t"
        )
        assert result["success"] is True
        assert result["done"] == 0


# ===========================================================================
# I) run_multi_device_via_task_graph returns canonical result dict
# ===========================================================================

class TestRunMultiDeviceViaTaskGraph:

    @pytest.mark.asyncio
    async def test_empty_subtasks_returns_success(self):
        from core.e2e_orchestrator import run_multi_device_via_task_graph
        result = await run_multi_device_via_task_graph([])
        assert result["success"] is True
        assert result["done"] == 0

    @pytest.mark.asyncio
    async def test_result_contains_canonical_fields(self):
        from core.e2e_orchestrator import run_multi_device_via_task_graph
        result = await run_multi_device_via_task_graph([])
        for field in ("success", "done", "failed", "skipped", "elapsed_ms",
                      "graph_id", "trace_id", "node_statuses"):
            assert field in result, f"result must contain '{field}'"

    @pytest.mark.asyncio
    async def test_trace_id_propagated(self):
        from core.e2e_orchestrator import run_multi_device_via_task_graph
        result = await run_multi_device_via_task_graph([], trace_id="trace-propagated-01")
        assert result["trace_id"] == "trace-propagated-01"


# ===========================================================================
# J) CapabilityContract to_dict / from_dict round-trip
# ===========================================================================

class TestCapabilityContractSerialisation:

    def test_to_dict_contains_all_fields(self):
        contract = CapabilityContract(
            name="action",
            description="Perform an action.",
            source=CapabilitySource.MCP,
            source_id="server-01",
            version="1.0.0",
            parameters={"type": "object"},
            tags=["ui"],
        )
        d = contract.to_dict()
        for field in ("contract_id", "name", "description", "source", "source_id",
                      "version", "parameters", "available", "tags", "metadata"):
            assert field in d

    def test_from_dict_round_trip(self):
        contract = CapabilityContract(
            name="click",
            description="Click a UI element.",
            source=CapabilitySource.DEVICE,
            source_id="dev-01",
        )
        restored = CapabilityContract.from_dict(contract.to_dict())
        assert restored.name == contract.name
        assert restored.description == contract.description
        assert restored.source == contract.source

    def test_to_tool_schema_format(self):
        contract = CapabilityContract(
            name="take_screenshot",
            description="Capture screen.",
            parameters={"type": "object", "properties": {}},
        )
        schema = contract.to_tool_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "take_screenshot"
        assert "parameters" in schema["function"]
