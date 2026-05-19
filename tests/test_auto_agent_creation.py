"""
tests/test_auto_agent_creation.py
==================================
Tests for automatic Agent creation and task execution.

Covers:
  1. IntentRouter — task/chat classification
  2. ExecutionPlanner._auto_select_template — template selection
  3. ExecutionPlanner._run_single_agent — auto_agent_id/template in result
  4. End-to-end: intent routing → auto agent creation → execution result

Note on running:
  These tests use pytest-asyncio and can be run locally with:
      pytest tests/test_auto_agent_creation.py -v
  No external services are required; all LLM calls are mocked.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.agent.intent_router import (
    IntentRouter,
    IntentResult,
    IntentMode,
    _classify_by_rules,
)
from core.agent.execution_planner import (
    ExecutionPlanner,
    ExecutionPlan,
    ExecutionResult,
)
from core.agent_factory import AgentFactory, AGENT_TEMPLATES


# ─────────────────────────── Fixtures ──────────────────────────────────────


@pytest.fixture
def router_no_llm():
    """IntentRouter without LLM (rules only)."""
    return IntentRouter(llm_router=None)


@pytest.fixture
def factory():
    f = AgentFactory(llm_router=None)
    f.agents.clear()
    f.agent_tree.clear()
    return f


@pytest.fixture
def planner():
    return ExecutionPlanner(llm_router=None)


@pytest.fixture
def mock_llm_router():
    router = MagicMock()
    router.chat = AsyncMock(return_value=MagicMock(
        content='{"analysis": "test result", "result": "done"}',
        provider="mock",
        model="mock-model",
        latency_ms=10.0,
        input_tokens=10,
        output_tokens=20,
    ))
    router.chat_json = AsyncMock(return_value={
        "role": "analyst",
        "name": "Auto Analyst",
        "description": "Test agent",
        "capabilities": [{"name": "analysis", "description": "analyze", "strength": 0.9}],
        "system_prompt": "You are an analyst.",
        "max_subtasks": 3,
        "max_depth": 2,
    })
    router.is_available = MagicMock(return_value=True)
    return router


# ─────────────────────────── IntentRouter Tests ──────────────────────────────


class TestIntentRouter:
    """Tests for intent classification (rules-based)."""

    def test_high_confidence_task_keywords_zh(self):
        """Chinese high-confidence task keywords → task_execute."""
        task_messages = [
            "帮我写一段Python代码",
            "帮我分析这些数据",
            "帮我生成一份报告",
            "打开微信",
            "截图",
            "在手机上运行这个程序",
            "创建一个新文件",
        ]
        for msg in task_messages:
            result = _classify_by_rules(msg)
            assert result.mode == IntentMode.TASK_EXECUTE, (
                f"Expected task_execute for '{msg}', got {result.mode}"
            )
            assert result.confidence >= 0.8

    def test_high_confidence_task_keywords_en(self):
        """English high-confidence task keywords → task_execute."""
        task_messages = [
            "write code for me",
            "generate a report",
            "create a file named test.txt",
            "open the browser",
            "take a screenshot",
            "deploy the application",
        ]
        for msg in task_messages:
            result = _classify_by_rules(msg)
            assert result.mode == IntentMode.TASK_EXECUTE, (
                f"Expected task_execute for '{msg}', got {result.mode}"
            )

    def test_low_confidence_task_keywords_classified_as_task(self):
        """Low-confidence task keywords in longer messages → task_execute or hybrid (execution mode)."""
        low_task_messages = [
            "help me do something",
            "can you help me",
            "please complete the work",
            "帮我写一下这个功能",   # "帮我" + action context (>= 4 chars)
        ]
        for msg in low_task_messages:
            result = _classify_by_rules(msg)
            assert result.is_execution(), (
                f"Expected execution intent for '{msg}', got mode={result.mode}"
            )
            assert result.confidence >= 0.6

    def test_very_short_messages_are_chat(self):
        """Very short messages without HIGH keywords → chat_only."""
        short_chat_messages = [
            "hi",
            "ok",
            "帮我",   # 2 chars, LOW keyword but too short — ambiguous
        ]
        for msg in short_chat_messages:
            result = _classify_by_rules(msg)
            assert result.mode == IntentMode.CHAT_ONLY, (
                f"Short/ambiguous message '{msg}' should be chat_only, got {result.mode}"
            )

    def test_pure_chat_keywords(self):
        """Pure chat keywords → chat_only."""
        chat_messages = [
            "你好",
            "hi there",
            "讲个故事",
            "什么是人工智能",
        ]
        for msg in chat_messages:
            result = _classify_by_rules(msg)
            assert result.mode == IntentMode.CHAT_ONLY, (
                f"Expected chat_only for '{msg}', got {result.mode}"
            )

    def test_short_message_is_chat(self):
        """Very short messages (<4 chars) → chat_only."""
        result = _classify_by_rules("hi")
        assert result.mode == IntentMode.CHAT_ONLY

    def test_is_execution_method(self):
        """IntentResult.is_execution() returns True for task_execute and hybrid."""
        assert IntentResult(mode=IntentMode.TASK_EXECUTE).is_execution() is True
        assert IntentResult(mode=IntentMode.HYBRID).is_execution() is True
        assert IntentResult(mode=IntentMode.CHAT_ONLY).is_execution() is False

    @pytest.mark.asyncio
    async def test_router_route_task(self, router_no_llm):
        """IntentRouter.route() classifies task messages correctly."""
        result = await router_no_llm.route("帮我写一个排序算法", use_llm=False)
        assert result.is_execution()

    @pytest.mark.asyncio
    async def test_router_route_chat(self, router_no_llm):
        """IntentRouter.route() classifies chat messages correctly."""
        result = await router_no_llm.route("你好，今天怎么样？", use_llm=False)
        assert result.mode == IntentMode.CHAT_ONLY


# ─────────────────────── ExecutionPlanner Template Selection ────────────────


class TestAutoTemplateSelection:
    """Tests for ExecutionPlanner._auto_select_template."""

    def test_code_keywords_select_code_executor(self, planner):
        intent = IntentResult(mode=IntentMode.TASK_EXECUTE, task_hint="write code")
        template = planner._auto_select_template("写代码实现排序", intent)
        assert template == "code_executor"

    def test_data_analysis_keywords(self, planner):
        intent = IntentResult(mode=IntentMode.TASK_EXECUTE, task_hint="analyze data")
        template = planner._auto_select_template("分析这些数据", intent)
        assert template == "data_analyst"

    def test_device_keywords(self, planner):
        intent = IntentResult(mode=IntentMode.TASK_EXECUTE, task_hint="device control")
        template = planner._auto_select_template("控制手机截图", intent)
        assert template == "device_controller"

    def test_research_keywords(self, planner):
        intent = IntentResult(mode=IntentMode.TASK_EXECUTE, task_hint="search")
        template = planner._auto_select_template("搜索关于AI的最新信息", intent)
        assert template == "research"

    def test_planner_keywords(self, planner):
        intent = IntentResult(mode=IntentMode.TASK_EXECUTE, task_hint="plan")
        template = planner._auto_select_template("制定一个项目规划方案", intent)
        assert template == "planner"

    def test_coordinator_fallback(self, planner):
        """Messages without specific keywords → coordinator."""
        intent = IntentResult(mode=IntentMode.TASK_EXECUTE, task_hint="")
        template = planner._auto_select_template("执行这个任务", intent)
        assert template == "coordinator"

    def test_task_hint_fallback(self, planner):
        """task_hint used when message doesn't have keywords."""
        intent = IntentResult(mode=IntentMode.TASK_EXECUTE, task_hint="分析数据")
        template = planner._auto_select_template("帮我处理一下", intent)
        assert template == "data_analyst"

    def test_all_templates_valid(self, planner):
        """All auto-selected templates must exist in AGENT_TEMPLATES."""
        test_cases = [
            ("写代码", "code_executor"),
            ("分析数据", "data_analyst"),
            ("控制设备", "device_controller"),
            ("搜索信息", "research"),
            ("制定计划", "planner"),
        ]
        for msg, expected in test_cases:
            intent = IntentResult(mode=IntentMode.TASK_EXECUTE)
            template = planner._auto_select_template(msg, intent)
            assert template in AGENT_TEMPLATES, (
                f"Template '{template}' not in AGENT_TEMPLATES"
            )


# ──────────────────────── ExecutionResult Model ──────────────────────────────


class TestExecutionResultModel:
    """Tests for ExecutionResult backward compatibility and new fields."""

    def test_new_fields_optional_default_none(self):
        """New auto_agent_id and auto_agent_template fields default to None."""
        result = ExecutionResult(success=True, reply="ok")
        assert result.auto_agent_id is None
        assert result.auto_agent_template is None

    def test_existing_fields_still_present(self):
        """Existing fields are not affected by new additions."""
        result = ExecutionResult(
            success=True,
            mode="single_agent",
            reply="done",
            error="",
            duration_ms=100.0,
        )
        assert result.success is True
        assert result.mode == "single_agent"
        assert result.reply == "done"

    def test_new_fields_can_be_set(self):
        """New fields can be set explicitly."""
        result = ExecutionResult(
            success=True,
            reply="ok",
            auto_agent_id="agent_abc123",
            auto_agent_template="data_analyst",
        )
        assert result.auto_agent_id == "agent_abc123"
        assert result.auto_agent_template == "data_analyst"

    def test_serialization_includes_new_fields(self):
        """Serialized dict includes new optional fields."""
        result = ExecutionResult(
            success=True,
            reply="ok",
            auto_agent_id="agent_abc123",
            auto_agent_template="planner",
        )
        d = result.model_dump()
        assert "auto_agent_id" in d
        assert "auto_agent_template" in d
        assert d["auto_agent_id"] == "agent_abc123"
        assert d["auto_agent_template"] == "planner"


# ────────────────────── ExecutionPlanner._run_single_agent ───────────────────


@pytest.mark.asyncio
async def test_run_single_agent_returns_auto_fields(factory):
    """_run_single_agent should populate auto_agent_id and auto_agent_template."""
    planner = ExecutionPlanner(llm_router=None)

    # get_agent_factory is imported inside _run_single_agent from core.agent_factory
    with patch("core.agent_factory.get_agent_factory", return_value=factory):
        # Mock execute_agent_task to avoid actual LLM calls
        with patch.object(factory, "execute_agent_task", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "reply": "分析完成",
                "tool_calls": [],
            }

            intent = IntentResult(mode=IntentMode.TASK_EXECUTE, task_hint="分析数据")
            plan = ExecutionPlan(message="帮我分析这些数据", intent=intent)

            steps = []
            tool_calls = []
            result = await planner._run_single_agent(plan, steps, tool_calls)

    assert result.success is True
    assert result.auto_agent_id is not None
    assert result.auto_agent_id.startswith("agent_")
    assert result.auto_agent_template == "data_analyst"
    assert len(steps) >= 2  # "创建 Agent" + "Agent 执行"


@pytest.mark.asyncio
async def test_run_single_agent_code_template(factory):
    """_run_single_agent picks code_executor for code-related tasks."""
    planner = ExecutionPlanner(llm_router=None)

    with patch("core.agent_factory.get_agent_factory", return_value=factory):
        with patch.object(factory, "execute_agent_task", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "reply": "代码生成完成",
                "tool_calls": [],
            }

            intent = IntentResult(mode=IntentMode.TASK_EXECUTE, task_hint="write code")
            plan = ExecutionPlan(message="帮我写一段Python排序代码", intent=intent)

            steps = []
            tool_calls = []
            result = await planner._run_single_agent(plan, steps, tool_calls)

    assert result.auto_agent_template == "code_executor"
    assert result.auto_agent_id is not None


# ──────────────────────── End-to-End: Intent → Agent ─────────────────────────


@pytest.mark.asyncio
async def test_e2e_intent_routing_to_auto_agent():
    """
    End-to-end: task message → IntentRouter classifies as task_execute →
    ExecutionPlanner creates agent → result has auto_agent fields.
    """
    router = IntentRouter(llm_router=None)
    factory = AgentFactory(llm_router=None)
    factory.agents.clear()
    planner = ExecutionPlanner(llm_router=None)

    # Step 1: Route the message
    message = "帮我分析一下这段数据"
    intent_result = await router.route(message, use_llm=False)
    assert intent_result.is_execution(), (
        f"Expected execution mode, got {intent_result.mode}"
    )

    # Step 2: Build plan and execute
    plan = ExecutionPlan(message=message, intent=intent_result)

    with patch("core.agent_factory.get_agent_factory", return_value=factory):
        with patch.object(factory, "execute_agent_task", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {
                "success": True,
                "reply": "分析结果: 数据正常",
                "tool_calls": [],
            }
            # Patch CapabilityRegistry to avoid external deps
            with patch("core.agent.capability_registry.get_capability_registry") as mock_reg:
                mock_registry = MagicMock()
                mock_registry.refresh = AsyncMock()
                mock_registry.list_tools = MagicMock(return_value=[])
                mock_registry.stats = MagicMock(return_value={})
                mock_registry.to_tool_schemas = MagicMock(return_value=[])
                mock_reg.return_value = mock_registry

                result = await planner.execute(plan)

    # Step 3: Verify result has auto-agent fields
    assert result.success is True
    assert result.auto_agent_id is not None
    assert result.auto_agent_template is not None
    assert result.auto_agent_template in AGENT_TEMPLATES
    assert result.specialist_boundary is not None
    assert result.specialist_boundary["specialist_layer_role"] == "specialists_as_tools"
    assert result.specialist_boundary["direct_side_effect_authority"] == "openclawd_mainline_only"


@pytest.mark.asyncio
async def test_e2e_chat_message_no_agent_creation():
    """Pure chat messages should not trigger auto agent creation via intent router."""
    router = IntentRouter(llm_router=None)

    chat_messages = ["你好", "hi", "告诉我一个故事"]
    for msg in chat_messages:
        result = await router.route(msg, use_llm=False)
        assert not result.is_execution(), (
            f"Chat message '{msg}' should not be classified as execution, "
            f"got mode={result.mode}"
        )


@pytest.mark.asyncio
async def test_e2e_multiple_task_types():
    """Multiple task types should all produce valid agent selections."""
    router = IntentRouter(llm_router=None)
    factory = AgentFactory(llm_router=None)
    factory.agents.clear()
    planner = ExecutionPlanner(llm_router=None)

    task_cases = [
        ("写一段Python代码实现快速排序", "code_executor"),
        ("分析一下这份销售数据", "data_analyst"),
        ("控制手机截图", "device_controller"),
        ("搜索关于深度学习的最新论文", "research"),
        ("制定一个产品发布计划", "planner"),
    ]

    for message, expected_template in task_cases:
        intent_result = await router.route(message, use_llm=False)
        selected = planner._auto_select_template(message, intent_result)
        assert selected == expected_template, (
            f"Message '{message}': expected template '{expected_template}', got '{selected}'"
        )


# ──────────────────────── New Flow: Strategy Selection ───────────────────────


class TestStrategySelection:
    """Tests for the updated _pick_strategy method (fractal / swarm / specialized / single)."""

    def test_swarm_keywords(self, planner):
        """Swarm-specific keywords → swarm strategy."""
        for msg in ["批量处理文件", "大量并发请求 swarm", "高并发任务"]:
            strategy = planner._pick_strategy(msg, complexity=0.3)
            assert strategy == "swarm", f"Expected swarm for '{msg}', got {strategy}"

    def test_fractal_by_complexity(self, planner):
        """Very high complexity (>= 0.75) → fractal strategy."""
        strategy = planner._pick_strategy("完成一个复杂的任务", complexity=0.8)
        assert strategy == "fractal"

    def test_fractal_by_keyword(self, planner):
        """Fractal keywords → fractal strategy."""
        for msg in ["递归分解这个任务", "分型处理", "多层深度拆解"]:
            strategy = planner._pick_strategy(msg, complexity=0.3)
            assert strategy == "fractal", f"Expected fractal for '{msg}', got {strategy}"

    def test_specialized_by_complexity(self, planner):
        """Medium-high complexity (>= 0.65 < 0.75) → specialized strategy."""
        strategy = planner._pick_strategy("分析这个项目", complexity=0.68)
        assert strategy == "specialized"

    def test_specialized_by_keyword(self, planner):
        """Team/parallel keywords → specialized strategy."""
        for msg in ["用 team 分工完成", "并行执行多个任务", "异构团队分析"]:
            strategy = planner._pick_strategy(msg, complexity=0.3)
            assert strategy == "specialized", f"Expected specialized for '{msg}', got {strategy}"

    def test_single_agent_default(self, planner):
        """Low complexity + no special keywords → single agent."""
        strategy = planner._pick_strategy("帮我整理一下笔记", complexity=0.2)
        assert strategy == "single"


class TestExecutionResultNewFields:
    """Tests for new optional fields in ExecutionResult."""

    def test_new_fields_default_none(self):
        """All new fields default to None."""
        result = ExecutionResult(success=True, reply="ok")
        assert result.chosen_strategy is None
        assert result.chosen_providers is None
        assert result.twin_id is None
        assert result.twin_coupling is None
        assert result.specialist_boundary is None

    def test_new_fields_can_be_set(self):
        """New fields can be set explicitly."""
        result = ExecutionResult(
            success=True,
            reply="ok",
            chosen_strategy="fractal",
            chosen_providers=["deepseek:deepseek-chat", "openai:gpt-4o"],
            twin_id="twin_abc123",
            twin_coupling="loose",
        )
        assert result.chosen_strategy == "fractal"
        assert result.chosen_providers == ["deepseek:deepseek-chat", "openai:gpt-4o"]
        assert result.twin_id == "twin_abc123"
        assert result.twin_coupling == "loose"
        assert result.specialist_boundary is None

    def test_backward_compat_serialization(self):
        """Old fields still serialize correctly with new additions."""
        result = ExecutionResult(
            success=True,
            mode="single_agent",
            reply="done",
            auto_agent_id="agent_abc123",
            auto_agent_template="planner",
        )
        d = result.model_dump()
        assert d["auto_agent_id"] == "agent_abc123"
        assert d["auto_agent_template"] == "planner"
        # New fields present but None
        assert "chosen_strategy" in d
        assert d["chosen_strategy"] is None
        assert "specialist_boundary" in d
        assert d["specialist_boundary"] is None

    def test_specialist_boundary_can_be_set(self):
        """specialist_boundary is a serializable additive metadata field."""
        boundary = {
            "specialist_layer_role": "specialists_as_tools",
            "direct_side_effect_authority": "openclawd_mainline_only",
        }
        result = ExecutionResult(success=True, reply="ok", specialist_boundary=boundary)
        assert result.specialist_boundary == boundary
        assert result.model_dump()["specialist_boundary"]["specialist_layer_role"] == "specialists_as_tools"


class TestSpecialistBoundaryMetadata:
    """PR-8v2 specialist-layer boundary metadata mapping.

    These tests intentionally target the helper because it is the canonical
    boundary-construction point reused by all execution paths.
    """

    def test_specialized_maps_to_subordinate_specialist_boundary(self, planner):
        boundary = planner._build_specialist_boundary("team_specialized", device_id="android-1")
        assert boundary["specialist_layer_role"] == "specialists_as_tools"
        assert boundary["specialist_authority_class"] == "experts_as_subordinate_capabilities"
        assert boundary["strategy_class"] == "specialized"
        assert boundary["direct_side_effect_authority"] == "openclawd_mainline_only"
        assert boundary["android_runtime_alignment"]["runtime_host_role"] == "first_class_runtime_host"
        assert boundary["android_runtime_alignment"]["multi_device_targeting"] is False

    def test_swarm_multi_device_marks_targeting_true(self, planner):
        boundary = planner._build_specialist_boundary("swarm", device_id=["android-1", "desktop-2"])
        assert boundary["strategy_class"] == "swarm"
        assert boundary["android_runtime_alignment"]["cross_device_entry"] == "DeviceRouter"
        assert boundary["android_runtime_alignment"]["multi_device_targeting"] is True


# ─────────────────── Intent Router: Default Execute for Ambiguous ────────────


class TestIntentRouterDefaultExecute:
    """Test that ambiguous messages default to task_execute."""

    def test_medium_length_ambiguous_message_defaults_to_task(self):
        """Ambiguous messages of length >= 10 should default to task_execute."""
        result = _classify_by_rules("这是一个测试消息，没有明确的任务关键词")
        assert result.mode == IntentMode.TASK_EXECUTE, (
            f"Expected task_execute for ambiguous long message, got {result.mode}"
        )

    def test_short_ambiguous_message_stays_chat(self):
        """Short ambiguous messages (< 10 chars without clear signals) → chat_only."""
        result = _classify_by_rules("好的")  # 2 chars, no keywords
        assert result.mode == IntentMode.CHAT_ONLY

    def test_pure_chat_still_chat(self):
        """Explicit chat keywords still produce chat_only."""
        result = _classify_by_rules("你好，今天天气怎么样？")
        assert result.mode == IntentMode.CHAT_ONLY
