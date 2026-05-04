"""
Tests for the AI Agent System
=============================

Covers: AgentFactory, AgentMessageBus, AgentTeam, FractalAgent,
        AgentManifest, and SystemIntegration.
"""

import asyncio
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ──────────────────────────── Imports ────────────────────────────

from core.agent_factory import (
    AgentFactory,
    AgentMessageBus,
    AgentMessage,
    AgentRole,
    AgentState,
    CreationMode,
    AgentConfig,
    AgentCapability,
    TaskAgent,
    AGENT_TEMPLATES,
    get_message_bus,
)
from core.agent_manifest import (
    AgentManifest,
    ExecutionMode,
    AgentPriority,
    ToolDeclaration,
    TaskItem,
)


# ──────────────────────────── Fixtures ────────────────────────────


@pytest.fixture
def factory():
    """AgentFactory without LLM router."""
    f = AgentFactory(llm_router=None)
    f.agents.clear()
    f.agent_tree.clear()
    return f


@pytest.fixture
def mock_llm_router():
    """Mock LLM router for testing LLM-dependent features."""
    router = MagicMock()
    router.chat = AsyncMock(return_value=MagicMock(
        content='{"analysis": "test result"}',
        provider="mock",
    ))
    router.chat_json = AsyncMock(return_value={
        "role": "analyst",
        "name": "Test Analyst",
        "description": "Analyzes test data",
        "capabilities": [
            {"name": "analysis", "description": "Data analysis", "strength": 0.9}
        ],
        "system_prompt": "You are a test analyst.",
        "max_subtasks": 3,
        "max_depth": 2,
    })
    return router


@pytest.fixture
def factory_with_llm(mock_llm_router):
    """AgentFactory with mock LLM router."""
    f = AgentFactory(llm_router=mock_llm_router)
    f.agents.clear()
    f.agent_tree.clear()
    return f


@pytest.fixture
def message_bus():
    """Fresh message bus instance."""
    return AgentMessageBus()


# ============================================================================
# AgentMessageBus Tests
# ============================================================================


class TestAgentMessageBus:
    """Tests for the Agent message bus communication system."""

    def test_register_unregister(self, message_bus):
        message_bus.register("agent_001")
        assert "agent_001" in message_bus._queues
        message_bus.unregister("agent_001")
        assert "agent_001" not in message_bus._queues

    @pytest.mark.asyncio
    async def test_send_receive(self, message_bus):
        message_bus.register("sender")
        message_bus.register("receiver")

        msg = AgentMessage(
            id="msg_test001",
            sender_id="sender",
            receiver_id="receiver",
            msg_type="task_assign",
            payload={"task": "analyze data"},
        )
        result = await message_bus.send(msg)
        assert result is True

        received = await message_bus.receive("receiver", timeout=1.0)
        assert received is not None
        assert received.id == "msg_test001"
        assert received.payload == {"task": "analyze data"}

    @pytest.mark.asyncio
    async def test_send_to_nonexistent_agent(self, message_bus):
        msg = AgentMessage(
            id="msg_test002",
            sender_id="sender",
            receiver_id="nonexistent",
            msg_type="heartbeat",
        )
        result = await message_bus.send(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_receive_timeout(self, message_bus):
        message_bus.register("lonely_agent")
        received = await message_bus.receive("lonely_agent", timeout=0.1)
        assert received is None

    @pytest.mark.asyncio
    async def test_broadcast(self, message_bus):
        message_bus.register("broadcaster")
        message_bus.register("listener_1")
        message_bus.register("listener_2")

        await message_bus.broadcast("broadcaster", "heartbeat", {"status": "alive"})

        msg1 = await message_bus.receive("listener_1", timeout=1.0)
        msg2 = await message_bus.receive("listener_2", timeout=1.0)

        assert msg1 is not None
        assert msg2 is not None
        assert msg1.msg_type == "heartbeat"
        assert msg2.payload == {"status": "alive"}

    @pytest.mark.asyncio
    async def test_broadcast_excludes_sender(self, message_bus):
        message_bus.register("broadcaster")
        message_bus.register("listener")

        await message_bus.broadcast("broadcaster", "heartbeat", {})

        # Sender should NOT receive its own broadcast
        msg = await message_bus.receive("broadcaster", timeout=0.1)
        assert msg is None

    @pytest.mark.asyncio
    async def test_receive_from_unregistered(self, message_bus):
        received = await message_bus.receive("unregistered_agent", timeout=0.1)
        assert received is None


# ============================================================================
# AgentFactory - Template Creation Tests
# ============================================================================


class TestAgentFactoryTemplateCreation:
    """Tests for Mode 1: Template-based agent creation."""

    def test_create_all_templates(self, factory):
        for template_name in AGENT_TEMPLATES:
            agent = factory.create_from_template(template_name)
            assert agent.id.startswith("agent_")
            assert agent.creation_mode == CreationMode.TEMPLATE
            assert agent.state == AgentState.IDLE
            assert agent.depth == 0

    def test_create_with_overrides(self, factory):
        agent = factory.create_from_template(
            "coordinator",
            overrides={"name": "Custom Coordinator"}
        )
        assert agent.config.name == "Custom Coordinator"

    def test_create_unknown_template_raises(self, factory):
        with pytest.raises(ValueError, match="未知模板"):
            factory.create_from_template("nonexistent_template")

    def test_parent_child_relationship(self, factory):
        parent = factory.create_from_template("coordinator")
        child = factory.create_from_template("code_executor", parent_id=parent.id)

        assert child.parent_id == parent.id
        assert child.depth == 1

    def test_agent_registration(self, factory):
        agent = factory.create_from_template("coordinator")
        assert agent.id in factory.agents
        assert agent.id in factory.message_bus._queues

    def test_agent_to_dict(self, factory):
        agent = factory.create_from_template("coordinator")
        d = agent.to_dict()
        assert d["role"] == "coordinator"
        assert d["state"] == "idle"
        assert d["creation_mode"] == "template"
        assert "metrics" in d


# ============================================================================
# AgentFactory - LLM Generation Tests
# ============================================================================


class TestAgentFactoryLLMGeneration:
    """Tests for Mode 2: LLM-based agent generation."""

    @pytest.mark.asyncio
    async def test_create_from_llm(self, factory_with_llm):
        agent = await factory_with_llm.create_from_llm("Analyze sales data")
        assert agent.creation_mode == CreationMode.LLM_GENERATED
        assert agent.config.name == "Test Analyst"
        assert len(agent.config.capabilities) == 1

    @pytest.mark.asyncio
    async def test_llm_fallback_to_template(self, factory_with_llm, mock_llm_router):
        mock_llm_router.chat_json.side_effect = Exception("LLM unavailable")

        agent = await factory_with_llm.create_from_llm("分析数据趋势")
        # Should fall back to data_analyst template
        assert agent.creation_mode == CreationMode.TEMPLATE

    @pytest.mark.asyncio
    async def test_create_from_llm_without_router_raises(self, factory):
        with pytest.raises(RuntimeError, match="LLM Router 未配置"):
            await factory.create_from_llm("Some task")

    def test_template_matching_keywords(self, factory):
        assert factory._match_template("分析数据") == "data_analyst"
        assert factory._match_template("编程实现") == "code_executor"
        assert factory._match_template("搜索信息") == "research"
        assert factory._match_template("控制设备") == "device_controller"
        assert factory._match_template("制定计划") == "planner"
        assert factory._match_template("random gibberish") == "coordinator"


# ============================================================================
# AgentFactory - Split Tests
# ============================================================================


class TestAgentFactorySplit:
    """Tests for Mode 3: Agent splitting / reproduction."""

    @pytest.mark.asyncio
    async def test_split_agent(self, factory):
        parent = factory.create_from_template("coordinator")
        parent.task_queue = [
            {"task": "task_1"},
            {"task": "task_2"},
            {"task": "task_3"},
            {"task": "task_4"},
        ]

        children = await factory.split_agent(parent.id, num_children=2)

        assert len(children) == 2
        assert parent.state == AgentState.WAITING
        assert len(parent.task_queue) == 0
        for child in children:
            assert child.parent_id == parent.id
            assert child.creation_mode == CreationMode.SPLIT
            assert child.depth == parent.depth + 1

    @pytest.mark.asyncio
    async def test_split_respects_max_depth(self, factory):
        parent = factory.create_from_template("coordinator")
        parent.depth = parent.config.max_depth  # Already at max

        children = await factory.split_agent(parent.id)
        assert len(children) == 0

    @pytest.mark.asyncio
    async def test_split_nonexistent_agent_raises(self, factory):
        with pytest.raises(ValueError, match="Agent 不存在"):
            await factory.split_agent("nonexistent_id")

    @pytest.mark.asyncio
    async def test_child_ttl_halved(self, factory):
        parent = factory.create_from_template("coordinator")
        parent.task_queue = [{"task": "a"}, {"task": "b"}]
        parent_ttl = parent.config.ttl

        children = await factory.split_agent(parent.id, num_children=2)
        for child in children:
            assert child.config.ttl == parent_ttl // 2

    @pytest.mark.asyncio
    async def test_split_distributes_tasks(self, factory):
        parent = factory.create_from_template("coordinator")
        parent.task_queue = [{"task": f"task_{i}"} for i in range(6)]

        children = await factory.split_agent(parent.id, num_children=3)
        total_tasks = sum(len(c.task_queue) for c in children)
        assert total_tasks == 6

    @pytest.mark.asyncio
    async def test_split_updates_metrics(self, factory):
        parent = factory.create_from_template("coordinator")
        parent.task_queue = [{"task": "a"}, {"task": "b"}]

        await factory.split_agent(parent.id, num_children=2)
        assert parent.metrics["splits"] == 1


# ============================================================================
# Agent Execution Tests
# ============================================================================


class TestAgentExecution:
    """Tests for agent task execution."""

    @pytest.mark.asyncio
    async def test_execute_without_llm(self, factory):
        agent = factory.create_from_template("coordinator")
        result = await factory.execute_agent_task(agent.id, {"task": "test"})

        assert result is not None
        assert agent.metrics["tasks_completed"] >= 1

    @pytest.mark.asyncio
    async def test_execute_with_llm(self, factory_with_llm):
        agent = factory_with_llm.create_from_template("data_analyst")
        result = await factory_with_llm.execute_agent_task(
            agent.id, {"task": "analyze", "data": [1, 2, 3]}
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_execute_nonexistent_agent_raises(self, factory):
        with pytest.raises(ValueError, match="Agent 不存在"):
            await factory.execute_agent_task("nonexistent", {"task": "test"})


# ============================================================================
# AgentManifest Tests
# ============================================================================


class TestAgentManifest:
    """Tests for the agent manifest serialization/deserialization."""

    def test_create_manifest(self):
        manifest = AgentManifest(
            agent_name="test_agent",
            agent_role="executor",
            system_prompt="You are a test agent.",
        )
        assert manifest.agent_name == "test_agent"
        assert manifest.execution_mode == "react"
        assert manifest.timeout_seconds == 300

    def test_serialize_deserialize(self):
        original = AgentManifest(
            agent_name="roundtrip_test",
            agent_role="analyst",
            system_prompt="Analyze data.",
            tools=[ToolDeclaration("search", "Search the web").to_dict()],
            tasks=[TaskItem(instruction="Find sales data").to_dict()],
        )

        json_str = original.to_json()
        restored = AgentManifest.from_json(json_str)

        assert restored.agent_name == "roundtrip_test"
        assert restored.agent_role == "analyst"
        assert len(restored.tools) == 1
        assert len(restored.tasks) == 1

    def test_checksum_consistency(self):
        manifest = AgentManifest(agent_name="checksum_test")
        c1 = manifest.checksum()
        c2 = manifest.checksum()
        assert c1 == c2
        assert len(c1) == 16

    def test_checksum_changes_on_modification(self):
        m1 = AgentManifest(agent_name="original")
        m2 = AgentManifest(agent_name="modified")
        assert m1.checksum() != m2.checksum()

    def test_device_control_factory(self):
        manifest = AgentManifest.create_device_control_agent(
            target_device="phone01",
            instruction="Open Settings",
        )
        assert manifest.target_device == "phone01"
        assert manifest.source_device == "server"
        assert manifest.execution_mode == ExecutionMode.REACT.value
        assert len(manifest.tools) == 7  # 7 default tools
        assert len(manifest.tasks) == 1

    def test_multi_step_factory(self):
        steps = [
            {"instruction": "Step 1", "action": "click", "params": {"x": 100}},
            {"instruction": "Step 2", "action": "type_text", "params": {"text": "hi"}},
        ]
        manifest = AgentManifest.create_multi_step_agent(
            agent_name="multi_step",
            steps=steps,
        )
        assert manifest.execution_mode == ExecutionMode.SEQUENTIAL.value
        assert len(manifest.tasks) == 2

    def test_to_dict_roundtrip(self):
        original = AgentManifest(
            agent_name="dict_test",
            priority=AgentPriority.HIGH.value,
            ttl_seconds=7200,
        )
        d = original.to_dict()
        restored = AgentManifest.from_dict(d)
        assert restored.agent_name == "dict_test"
        assert restored.priority == "high"
        assert restored.ttl_seconds == 7200


# ============================================================================
# Data Model Tests
# ============================================================================


class TestDataModels:
    """Tests for agent data models and enums."""

    def test_agent_roles(self):
        assert len(AgentRole) == 7
        assert AgentRole.COORDINATOR.value == "coordinator"

    def test_agent_states(self):
        assert len(AgentState) == 7
        assert AgentState.IDLE.value == "idle"

    def test_creation_modes(self):
        assert len(CreationMode) == 3
        assert CreationMode.TEMPLATE.value == "template"
        assert CreationMode.LLM_GENERATED.value == "llm_generated"
        assert CreationMode.SPLIT.value == "split"

    def test_agent_config_defaults(self):
        config = AgentConfig(
            role=AgentRole.EXECUTOR,
            name="test",
            description="test",
            capabilities=[],
            system_prompt="test",
        )
        assert config.max_subtasks == 5
        assert config.max_depth == 3
        assert config.split_threshold == 3
        assert config.ttl == 3600

    def test_agent_capability(self):
        cap = AgentCapability("test_cap", "A test capability", strength=0.75)
        assert cap.name == "test_cap"
        assert cap.strength == 0.75

    def test_execution_modes(self):
        assert ExecutionMode.REACT.value == "react"
        assert ExecutionMode.SEQUENTIAL.value == "sequential"
        assert ExecutionMode.AUTONOMOUS.value == "autonomous"


# ============================================================================
# Fractal Agent Tests
# ============================================================================


class TestFractalAgent:
    """Tests for the fractal agent decomposition system."""

    def test_import_fractal_modules(self):
        from core.fractal_agent import (
            FractalAgent,
            FractalTask,
            FractalResult,
            Complexity,
        )
        assert Complexity.ATOMIC.value == "atomic"
        assert Complexity.EPIC.value == "epic"

    def test_fractal_task_creation(self):
        from core.fractal_agent import FractalTask, Complexity
        task = FractalTask(
            id="task_001",
            description="Analyze market data",
            complexity=Complexity.MODERATE,
        )
        assert task.id == "task_001"
        assert task.depth == 0
        assert task.parent_task_id is None
        assert task.subtask_ids == []

    def test_fractal_result_creation(self):
        from core.fractal_agent import FractalResult
        result = FractalResult(
            task_id="task_001",
            success=True,
            output="Analysis complete",
            depth=0,
        )
        assert result.success is True
        assert result.subtask_results == []
        assert result.decomposition_used is False

    def test_fractal_agent_limits(self):
        from core.fractal_agent import FractalAgent
        assert FractalAgent.MAX_DEPTH == 4
        assert FractalAgent.MAX_SUBTASKS == 6


# ============================================================================
# System Integration Tests
# ============================================================================


class TestSystemIntegration:
    """Tests for the system integration capability registry."""

    def test_import_system_integration(self):
        from core.system_integration import (
            SystemIntegration,
            CapabilityType,
            Capability,
        )
        assert CapabilityType.DEVICE.value == "device"
        assert CapabilityType.MCP.value == "mcp"
        assert CapabilityType.AGENT.value == "agent"

    def test_capability_to_dict(self):
        from core.system_integration import Capability, CapabilityType
        cap = Capability(
            name="device_control",
            source=CapabilityType.DEVICE,
            description="Control IoT devices",
            source_id="smart_hub_001",
            metadata={"system_integration_id": "cap_001", "priority": 8},
        )
        d = cap.to_dict()
        assert d["id"] == "cap_001"
        assert d["type"] == "device"
        assert d["priority"] == 8
        assert d["enabled"] is True


# ============================================================================
# Agent Team Tests
# ============================================================================


class TestAgentTeam:
    """Tests for the agent team collaboration system."""

    def test_import_team_modules(self):
        from core.agent_team import (
            AgentTeam,
            TeamStrategy,
            TeamStatus,
            TeamMember,
        )
        assert TeamStrategy.PARALLEL.value == "parallel"
        assert TeamStrategy.SPECIALIZED.value == "specialized"
        assert TeamStrategy.SWARM.value == "swarm"

    def test_team_member_to_dict(self):
        from core.agent_team import TeamMember
        member = TeamMember(
            agent_id="agent_001",
            agent_name="Analyst",
            provider="openai",
            model="gpt-4",
            role_in_team="data_analysis",
        )
        d = member.to_dict()
        assert d["agent_id"] == "agent_001"
        assert d["provider"] == "openai"
        assert d["model"] == "gpt-4"
