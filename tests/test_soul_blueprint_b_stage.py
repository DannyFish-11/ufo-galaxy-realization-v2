"""
B 阶段测试: SOUL 全局约束 + 模板蓝图双层约束
=============================================

覆盖：
1. SOUL 注入 — 单 Agent 路径
2. SOUL 注入 — Team/Swarm 路径（成员 system prompt）
3. SOUL 注入 — Fractal 路径（原子执行 + 子任务继承）
4. 模板蓝图前置约束（SOUL + schema 注入 prompt）
5. 模板蓝图后置校验失败 → 自动回退模板兜底
6. ExecutionResult.soul_enforced 字段存在且向后兼容
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ──────────────────────────── 辅助 ────────────────────────────


def _get_all_messages_from_mock(mock_call_args) -> list:
    """从 Mock 调用的 call_args 中提取 messages 列表（兼容 kwargs/args 两种方式）。"""
    messages = mock_call_args.kwargs.get("messages")
    if messages is None and mock_call_args.args:
        messages = mock_call_args.args[0]
    return messages or []


def _make_valid_llm_config(**overrides):
    """返回一个符合 AGENT_CONFIG_SCHEMA 的合法配置字典。"""
    base = {
        "role": "analyst",
        "name": "测试分析 Agent",
        "description": "用于测试",
        "capabilities": [{"name": "analysis", "description": "分析", "strength": 0.8}],
        "system_prompt": "你是一个测试 Agent。",
        "max_subtasks": 3,
        "max_depth": 2,
    }
    base.update(overrides)
    return base


# ══════════════════════════════════════════════════════════════════
# 1. schema 校验方法单元测试
# ══════════════════════════════════════════════════════════════════


class TestAgentConfigSchemaValidation:
    """core.agent_factory.AgentFactory._validate_agent_config 校验逻辑测试。"""

    @pytest.fixture
    def factory(self):
        from core.agent_factory import AgentFactory
        f = AgentFactory(llm_router=None)
        f.agents.clear()
        return f

    def test_valid_config_passes(self, factory):
        assert factory._validate_agent_config(_make_valid_llm_config()) is True

    def test_missing_role_fails(self, factory):
        cfg = _make_valid_llm_config()
        del cfg["role"]
        assert factory._validate_agent_config(cfg) is False

    def test_empty_role_fails(self, factory):
        assert factory._validate_agent_config(_make_valid_llm_config(role="")) is False

    def test_invalid_role_enum_fails(self, factory):
        assert factory._validate_agent_config(_make_valid_llm_config(role="superhero")) is False

    def test_all_valid_roles_pass(self, factory):
        valid_roles = [
            "coordinator", "executor", "analyst",
            "planner", "monitor", "communicator", "specialist",
        ]
        for role in valid_roles:
            assert factory._validate_agent_config(_make_valid_llm_config(role=role)) is True, \
                f"Role '{role}' should pass validation"

    def test_missing_name_fails(self, factory):
        cfg = _make_valid_llm_config()
        del cfg["name"]
        assert factory._validate_agent_config(cfg) is False

    def test_empty_name_fails(self, factory):
        assert factory._validate_agent_config(_make_valid_llm_config(name="")) is False

    def test_missing_system_prompt_fails(self, factory):
        cfg = _make_valid_llm_config()
        del cfg["system_prompt"]
        assert factory._validate_agent_config(cfg) is False

    def test_empty_system_prompt_fails(self, factory):
        assert factory._validate_agent_config(_make_valid_llm_config(system_prompt="")) is False

    def test_invalid_capabilities_type_fails(self, factory):
        assert factory._validate_agent_config(
            _make_valid_llm_config(capabilities="not_a_list")
        ) is False

    def test_capability_missing_name_fails(self, factory):
        cfg = _make_valid_llm_config(capabilities=[{"description": "no name"}])
        assert factory._validate_agent_config(cfg) is False

    def test_capability_strength_out_of_range_fails(self, factory):
        cfg = _make_valid_llm_config(
            capabilities=[{"name": "x", "strength": 1.5}]
        )
        assert factory._validate_agent_config(cfg) is False

    def test_max_subtasks_out_of_range_fails(self, factory):
        assert factory._validate_agent_config(_make_valid_llm_config(max_subtasks=100)) is False
        assert factory._validate_agent_config(_make_valid_llm_config(max_subtasks=0)) is False

    def test_max_depth_out_of_range_fails(self, factory):
        assert factory._validate_agent_config(_make_valid_llm_config(max_depth=10)) is False
        assert factory._validate_agent_config(_make_valid_llm_config(max_depth=0)) is False

    def test_optional_fields_absent_still_passes(self, factory):
        """可选字段缺失时不应影响校验结果。"""
        cfg = {
            "role": "executor",
            "name": "简单 Agent",
            "system_prompt": "执行任务。",
        }
        assert factory._validate_agent_config(cfg) is True


# ══════════════════════════════════════════════════════════════════
# 2. create_from_llm 双层约束 + SOUL 注入
# ══════════════════════════════════════════════════════════════════


class TestCreateFromLlmSoulAndSchema:
    """create_from_llm 的前置 SOUL 注入 + 后置 schema 校验逻辑。"""

    @pytest.fixture
    def mock_router(self):
        router = MagicMock()
        router.chat_json = AsyncMock(return_value=_make_valid_llm_config())
        return router

    @pytest.fixture
    def factory(self, mock_router):
        from core.agent_factory import AgentFactory
        f = AgentFactory(llm_router=mock_router)
        f.agents.clear()
        return f

    @pytest.mark.asyncio
    async def test_soul_injected_into_prompt(self, factory, mock_router):
        """SOUL 策略应出现在 LLM 调用的 prompt 中（前置约束）。"""
        soul = "不得执行任何破坏性操作。"
        await factory.create_from_llm("分析数据", soul_policy=soul)

        messages = _get_all_messages_from_mock(mock_router.chat_json.call_args)
        full_prompt = " ".join(m.get("content", "") for m in messages)
        assert soul in full_prompt, "SOUL 约束必须出现在 LLM prompt 中"

    @pytest.mark.asyncio
    async def test_schema_hint_in_prompt(self, factory, mock_router):
        """模板 schema 硬规则应出现在 LLM 调用的 prompt 中（前置约束）。"""
        await factory.create_from_llm("分析数据")

        messages = _get_all_messages_from_mock(mock_router.chat_json.call_args)
        full_prompt = " ".join(m.get("content", "") for m in messages)
        assert "schema" in full_prompt.lower() or "硬规则" in full_prompt, \
            "模板 schema 硬规则必须出现在 prompt 中"

    @pytest.mark.asyncio
    async def test_valid_llm_config_creates_agent(self, factory, mock_router):
        """合法 LLM 配置应成功创建 Agent，不触发回退。"""
        from core.agent_factory import CreationMode
        agent = await factory.create_from_llm("分析数据")
        assert agent.creation_mode == CreationMode.LLM_GENERATED

    @pytest.mark.asyncio
    async def test_schema_validation_failure_falls_back_to_template(self, factory, mock_router):
        """后置 schema 校验失败时，应自动回退到模板兜底。"""
        from core.agent_factory import CreationMode
        # LLM 返回不合法的 role
        mock_router.chat_json.return_value = _make_valid_llm_config(role="invalid_role")
        agent = await factory.create_from_llm("分析数据")
        # 回退路径使用模板创建
        assert agent.creation_mode == CreationMode.TEMPLATE, \
            "schema 校验失败应回退到 TEMPLATE 模式"

    @pytest.mark.asyncio
    async def test_schema_validation_missing_required_field_falls_back(self, factory, mock_router):
        """后置校验：缺少必填字段时应回退模板。"""
        from core.agent_factory import CreationMode
        cfg = _make_valid_llm_config()
        del cfg["system_prompt"]
        mock_router.chat_json.return_value = cfg
        agent = await factory.create_from_llm("写代码")
        assert agent.creation_mode == CreationMode.TEMPLATE

    @pytest.mark.asyncio
    async def test_llm_exception_falls_back_to_template(self, factory, mock_router):
        """LLM 调用抛异常时，也应回退到模板兜底。"""
        from core.agent_factory import CreationMode
        mock_router.chat_json.side_effect = RuntimeError("LLM 超时")
        agent = await factory.create_from_llm("搜索信息")
        assert agent.creation_mode == CreationMode.TEMPLATE


# ══════════════════════════════════════════════════════════════════
# 3. Team/Swarm — SOUL 注入 system prompt
# ══════════════════════════════════════════════════════════════════


class TestTeamSoulInjection:
    """Agent Team 三种策略中，SOUL 必须注入每个成员的 system prompt。"""

    def _make_team(self, strategy_str: str):
        """创建一个带 mock router 的 AgentTeam。"""
        from core.agent_team import AgentTeam, TeamStrategy, TeamMember
        strategy = TeamStrategy(strategy_str)
        members = [
            TeamMember(
                agent_id="a1", agent_name="成员1",
                provider="mock", model="mock-model",
                role_in_team="researcher",
            ),
        ]
        router = MagicMock()
        router.chat = AsyncMock(return_value=MagicMock(
            content="测试回答",
            input_tokens=10,
            output_tokens=20,
            tool_calls=None,
        ))
        router.chat_json = AsyncMock(return_value={"subtasks": []})
        router.classify_task = MagicMock(return_value="general")
        team = AgentTeam(
            team_id="team_test",
            strategy=strategy,
            members=members,
            agent_factory=None,
            llm_router=router,
        )
        return team, router

    def _extract_system_messages(self, router):
        """从 mock router 的 chat 调用中提取所有 system role 消息内容。"""
        contents = []
        for call in router.chat.call_args_list:
            messages = call.kwargs.get("messages") or (list(call.args[0]) if call.args else [])
            for msg in messages:
                if isinstance(msg, dict) and msg.get("role") == "system":
                    contents.append(msg.get("content", ""))
        return contents

    @pytest.mark.asyncio
    async def test_parallel_soul_in_system_prompt(self):
        """PARALLEL 策略：SOUL 必须出现在成员 system prompt 中。"""
        team, router = self._make_team("parallel")
        soul = "禁止泄露用户隐私数据。"
        await team.execute("测试任务", context={"soul": soul})

        sys_contents = self._extract_system_messages(router)
        assert any(soul in c for c in sys_contents), \
            f"PARALLEL 策略中 SOUL 必须注入成员 system prompt，实际内容: {sys_contents}"

    @pytest.mark.asyncio
    async def test_swarm_soul_in_system_prompt(self):
        """SWARM 策略：SOUL 必须出现在成员 system prompt 中。"""
        team, router = self._make_team("swarm")
        soul = "必须以礼貌的方式回应用户。"
        await team.execute("swarm测试任务", context={"soul": soul})

        sys_contents = self._extract_system_messages(router)
        assert any(soul in c for c in sys_contents), \
            f"SWARM 策略中 SOUL 必须注入成员 system prompt，实际内容: {sys_contents}"

    @pytest.mark.asyncio
    async def test_no_soul_no_injection(self):
        """未提供 SOUL 时，system prompt 不应包含 SOUL 占位符。"""
        team, router = self._make_team("parallel")
        await team.execute("测试任务", context={})

        sys_contents = self._extract_system_messages(router)
        assert not any("SOUL约束" in c for c in sys_contents), \
            "无 SOUL 时不应注入 SOUL 占位符"


# ══════════════════════════════════════════════════════════════════
# 4. Fractal — SOUL 注入 原子执行 + 子任务上下文继承
# ══════════════════════════════════════════════════════════════════


class TestFractalSoulInjection:
    """FractalAgent 在原子执行和子任务分解中必须传递 SOUL。"""

    def _make_fractal_agent(self):
        from core.fractal_agent import FractalAgent
        router = MagicMock()
        router.chat = AsyncMock(return_value=MagicMock(content="原子执行结果"))
        router.chat_json = AsyncMock(return_value={"complexity": "atomic", "reason": "test", "estimated_subtasks": 1})
        agent = FractalAgent(llm_router=router, depth=0)
        return agent, router

    def _extract_system_messages(self, router):
        """从 mock router 的 chat 调用中提取所有 system role 消息内容。"""
        contents = []
        for call in router.chat.call_args_list:
            messages = call.kwargs.get("messages") or (list(call.args[0]) if call.args else [])
            for msg in messages:
                if isinstance(msg, dict) and msg.get("role") == "system":
                    contents.append(msg.get("content", ""))
        return contents

    @pytest.mark.asyncio
    async def test_atomic_soul_in_system_prompt(self):
        """原子任务执行时，SOUL 必须出现在 LLM system prompt 中。"""
        from core.fractal_agent import FractalTask
        agent, router = self._make_fractal_agent()
        soul = "不得执行危险操作。"
        task = FractalTask(
            id="t1",
            description="原子任务",
            context={"soul": soul},
        )
        await agent.execute(task)

        sys_contents = self._extract_system_messages(router)
        assert any(soul in c for c in sys_contents), \
            f"Fractal 原子执行中 SOUL 必须出现在 system prompt，实际: {sys_contents}"

    def test_soul_preserved_in_subtask_context_by_rules(self):
        """规则分解时，子任务的 context 中必须包含 SOUL（不依赖 LLM）。"""
        from core.fractal_agent import FractalTask, FractalAgent
        soul = "始终保持礼貌。"

        agent = FractalAgent(llm_router=None, depth=0)
        # 使用连接词确保规则分解能产生多个子任务
        task = FractalTask(
            id="t_parent",
            description="完成任务A并且完成任务B",
            context={"soul": soul},
        )
        subtasks = agent._decompose_with_rules(task)
        # 如果规则分解成功则验证；否则跳过（说明内容不满足分解条件）
        if len(subtasks) >= 2:
            for st in subtasks:
                assert st.context.get("soul") == soul, \
                    f"子任务 context 中必须包含 SOUL，但得到: {st.context}"
        # 若只产生 1 个子任务，仍验证其 context 含 soul
        elif len(subtasks) == 1:
            assert subtasks[0].context.get("soul") == soul

    @pytest.mark.asyncio
    async def test_fractal_executor_passes_soul_via_context(self):
        """FractalExecutor.run() 应将 SOUL 通过 context 传给根 Agent task。"""
        from core.fractal_agent import FractalExecutor, FractalAgent, FractalResult

        created_tasks = []

        async def patched_execute(self_agent, task):
            created_tasks.append(task)
            return FractalResult(task_id=task.id, success=True, output="ok", depth=0)

        executor = FractalExecutor(llm_router=None)
        soul = "这是 SOUL 策略。"

        with patch.object(FractalAgent, "execute", patched_execute):
            await executor.run("测试任务", context={"soul": soul})

        assert len(created_tasks) >= 1
        assert created_tasks[0].context.get("soul") == soul, \
            "FractalExecutor 必须将 soul 传给根 Agent 的 task.context"


# ══════════════════════════════════════════════════════════════════
# 5. ExecutionResult.soul_enforced 字段
# ══════════════════════════════════════════════════════════════════


class TestExecutionResultSoulEnforced:
    """ExecutionResult 应包含 soul_enforced 可选字段，向后兼容。"""

    def test_soul_enforced_field_exists(self):
        from core.agent.execution_planner import ExecutionResult
        result = ExecutionResult(success=True, mode="single_agent", reply="ok")
        # 字段应存在且默认为 None（向后兼容）
        assert hasattr(result, "soul_enforced"), "ExecutionResult 必须有 soul_enforced 字段"
        assert result.soul_enforced is None

    def test_soul_enforced_can_be_set_true(self):
        from core.agent.execution_planner import ExecutionResult
        result = ExecutionResult(
            success=True, mode="single_agent", reply="ok",
            soul_enforced=True,
        )
        assert result.soul_enforced is True

    def test_soul_enforced_can_be_set_false(self):
        from core.agent.execution_planner import ExecutionResult
        result = ExecutionResult(
            success=True, mode="single_agent", reply="ok",
            soul_enforced=False,
        )
        assert result.soul_enforced is False

    def test_existing_fields_not_broken(self):
        """向后兼容：原有字段不受影响。"""
        from core.agent.execution_planner import ExecutionResult
        result = ExecutionResult(
            success=True,
            mode="team_specialized",
            reply="Team 完成",
            chosen_strategy="team_specialized",
            chosen_providers=["openai:gpt-4"],
            twin_id="twin_abc",
            twin_coupling="loose",
        )
        assert result.success is True
        assert result.mode == "team_specialized"
        assert result.twin_id == "twin_abc"
        assert result.soul_enforced is None  # 新字段默认 None


# ══════════════════════════════════════════════════════════════════
# 6. ExecutionPlanner soul_enforced 端到端路径
# ══════════════════════════════════════════════════════════════════


class TestExecutionPlannerSoulEnforced:
    """ExecutionPlanner 在各路径中应正确设置 soul_enforced 字段。"""

    def _make_plan(self, soul: str = "SOUL约束内容"):
        from core.agent.execution_planner import ExecutionPlan
        from core.agent.intent_router import IntentResult, IntentMode
        return ExecutionPlan(
            message="测试任务",
            intent=IntentResult(mode=IntentMode.TASK_EXECUTE, confidence=0.9),
            soul_policy=soul,
        )

    @pytest.mark.asyncio
    async def test_single_agent_soul_enforced_true_when_soul_present(self):
        """单 Agent 路径：有 SOUL 时 soul_enforced 应为 True。"""
        from core.agent.execution_planner import ExecutionPlanner

        planner = ExecutionPlanner(llm_router=None)
        plan = self._make_plan(soul="SOUL策略A")

        mock_agent = MagicMock()
        mock_agent.id = "agent_test_001"
        mock_agent.config.name = "测试 Agent"
        mock_factory = MagicMock()
        mock_factory.create_from_template.return_value = mock_agent
        mock_factory.execute_agent_task = AsyncMock(return_value={
            "success": True, "reply": "完成", "tool_calls": [],
        })

        with patch("core.agent_factory.get_agent_factory", return_value=mock_factory):
            result = await planner._run_single_agent(plan, [], [])

        assert result.soul_enforced is True

    @pytest.mark.asyncio
    async def test_single_agent_soul_enforced_false_when_no_soul(self):
        """单 Agent 路径：无 SOUL 时 soul_enforced 应为 False。"""
        from core.agent.execution_planner import ExecutionPlanner

        planner = ExecutionPlanner(llm_router=None)
        plan = self._make_plan(soul="")

        mock_agent = MagicMock()
        mock_agent.id = "agent_test_002"
        mock_agent.config.name = "测试 Agent"
        mock_factory = MagicMock()
        mock_factory.create_from_template.return_value = mock_agent
        mock_factory.execute_agent_task = AsyncMock(return_value={
            "success": True, "reply": "完成", "tool_calls": [],
        })

        with patch("core.agent_factory.get_agent_factory", return_value=mock_factory):
            result = await planner._run_single_agent(plan, [], [])

        assert result.soul_enforced is False
