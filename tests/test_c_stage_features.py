"""
C阶段功能测试
==============

覆盖：
  1A - SOUL 人格继承增强（split_agent / create_from_template 携带 inherited_soul）
  2C - 工具/MCP 调用守护（风险评分 + 拦截 + 重试 + 回滚）
  3B - 协同策略映射表（task_type → strategy）
  4B - 任务记忆/长期记忆（写入/读取/注入 context）
  5C - 执行链路可视化（ExecutionResult 包含 total_latency_ms/total_tokens/total_cost_usd）
"""

import asyncio
import os
import tempfile
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# =============================================================================
# 1A: SOUL 人格继承
# =============================================================================

class TestSOULInheritance:
    """子 Agent 继承主控 SOUL（1A）。"""

    def _make_factory(self):
        from core.agent_factory import AgentFactory
        f = AgentFactory(llm_router=None)
        f.agents.clear()
        return f

    def test_agent_config_has_inherited_soul_field(self):
        from core.agent_factory import AgentConfig, AgentRole, AgentCapability
        cfg = AgentConfig(
            role=AgentRole.EXECUTOR,
            name="test",
            description="test",
            capabilities=[],
            system_prompt="you are a test agent",
            inherited_soul="SOUL constraint from master",
            soul_supplement="My extra personality",
        )
        assert cfg.inherited_soul == "SOUL constraint from master"
        assert cfg.soul_supplement == "My extra personality"

    def test_get_effective_soul_combines_fields(self):
        from core.agent_factory import AgentConfig, AgentRole, get_effective_soul
        cfg = AgentConfig(
            role=AgentRole.EXECUTOR,
            name="test",
            description="",
            capabilities=[],
            system_prompt="",
            inherited_soul="主控 SOUL 约束",
            soul_supplement="子 Agent 补充",
        )
        effective = get_effective_soul(cfg)
        assert "主控 SOUL 约束" in effective
        assert "子 Agent 补充" in effective

    def test_get_effective_soul_no_soul(self):
        from core.agent_factory import AgentConfig, AgentRole, get_effective_soul
        cfg = AgentConfig(
            role=AgentRole.EXECUTOR,
            name="test",
            description="",
            capabilities=[],
            system_prompt="",
        )
        assert get_effective_soul(cfg) == ""

    def test_create_from_template_propagates_inherited_soul(self):
        f = self._make_factory()
        agent = f.create_from_template(
            "coordinator",
            inherited_soul="主控 SOUL",
        )
        assert agent.config.inherited_soul == "主控 SOUL"

    def test_split_agent_inherits_soul(self):
        """子 Agent 分裂时继承父代的 soul 约束。"""
        from core.agent_factory import AgentConfig, AgentRole, AgentCapability, TaskAgent, CreationMode, AgentState
        f = self._make_factory()

        # 手动创建一个带 soul 的父代 Agent
        from dataclasses import field as dc_field
        cfg = AgentConfig(
            role=AgentRole.COORDINATOR,
            name="parent",
            description="parent agent",
            capabilities=[],
            system_prompt="parent prompt",
            inherited_soul="master soul constraint",
            metadata={"soul_policy": "master soul constraint"},
        )
        from core.agent_factory import TaskAgent, CreationMode, AgentState
        parent = TaskAgent(
            id="parent_001",
            config=cfg,
            state=AgentState.IDLE,
        )
        parent.task_queue = [{"task": "sub1"}, {"task": "sub2"}]
        f.agents["parent_001"] = parent

        children = asyncio.get_event_loop().run_until_complete(
            f.split_agent("parent_001", num_children=2)
        )
        assert len(children) == 2
        for child in children:
            # C阶段 1A: 子代必须继承主控 SOUL
            assert child.config.inherited_soul == "master soul constraint", \
                f"Child should inherit master soul, got: {child.config.inherited_soul!r}"


# =============================================================================
# 2C: 工具/MCP 调用守护与回滚
# =============================================================================

class TestToolGuardian:
    """工具调用守护: 风险评分 + 拦截 + 重试 + 回滚（2C）。"""

    def test_score_safe_tool(self):
        from core.tool_guardian import score_tool_risk, ToolRiskLevel
        result = score_tool_risk("screenshot")
        assert result["level"] == ToolRiskLevel.SAFE
        assert result["score"] < 0.5

    def test_score_dangerous_tool(self):
        from core.tool_guardian import score_tool_risk, ToolRiskLevel
        result = score_tool_risk("file_delete")
        assert result["level"] == ToolRiskLevel.DANGEROUS
        assert result["score"] >= 0.7

    def test_score_critical_tool(self):
        from core.tool_guardian import score_tool_risk, ToolRiskLevel
        result = score_tool_risk("system_cmd_exec")
        assert result["level"] == ToolRiskLevel.CRITICAL
        assert result["score"] >= 0.9

    @pytest.mark.asyncio
    async def test_passthrough_when_disabled(self):
        """disabled 时直接透传，不影响调用。"""
        from core.tool_guardian import call_with_guardian, GuardedCallConfig

        called = []

        async def mock_fn(*args, **kwargs):
            called.append(True)
            return {"success": True}

        result = await call_with_guardian(
            fn=mock_fn,
            fn_args=(),
            tool_name="any_tool",
            config=GuardedCallConfig(enabled=False),
        )
        assert result == {"success": True}
        assert called

    @pytest.mark.asyncio
    async def test_blocks_critical_tool(self):
        """风险得分 >= block_score 时抛出 ToolGuardianBlockedError。"""
        from core.tool_guardian import call_with_guardian, GuardedCallConfig, ToolGuardianBlockedError

        async def critical_fn():
            return {}

        with pytest.raises(ToolGuardianBlockedError) as exc_info:
            await call_with_guardian(
                fn=critical_fn,
                tool_name="system_cmd_format_disk",  # score >= 0.95
                config=GuardedCallConfig(enabled=True, block_score=0.9),
            )
        assert exc_info.value.tool_name == "system_cmd_format_disk"

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """调用失败时按 max_retries 重试。"""
        from core.tool_guardian import call_with_guardian, GuardedCallConfig

        attempt_counts = [0]

        async def flaky_fn():
            attempt_counts[0] += 1
            if attempt_counts[0] < 3:
                raise RuntimeError("transient error")
            return {"success": True}

        result = await call_with_guardian(
            fn=flaky_fn,
            tool_name="read_file",  # safe tool
            config=GuardedCallConfig(enabled=True, max_retries=3, retry_delay_s=0.0),
        )
        assert result == {"success": True}
        assert attempt_counts[0] == 3

    @pytest.mark.asyncio
    async def test_rollback_called_on_final_failure(self):
        """所有重试失败后调用 rollback_fn。"""
        from core.tool_guardian import call_with_guardian, GuardedCallConfig

        rollback_called = []

        async def failing_fn():
            raise RuntimeError("always fails")

        async def my_rollback(tool_name, args, kwargs, exc):
            rollback_called.append(tool_name)

        with pytest.raises(RuntimeError):
            await call_with_guardian(
                fn=failing_fn,
                tool_name="read_file",
                config=GuardedCallConfig(
                    enabled=True,
                    max_retries=1,
                    retry_delay_s=0.0,
                    rollback_fn=my_rollback,
                ),
            )
        assert rollback_called == ["read_file"]

    def test_audit_log_records_entries(self):
        """成功调用后审计日志中有记录。"""
        from core.tool_guardian import call_with_guardian, GuardedCallConfig, get_guardian_audit_log
        import asyncio

        async def ok_fn():
            return "ok"

        asyncio.get_event_loop().run_until_complete(
            call_with_guardian(
                fn=ok_fn,
                tool_name="list_files",
                config=GuardedCallConfig(enabled=True, audit_log=True),
            )
        )
        log = get_guardian_audit_log(n=10)
        assert any(e.get("tool") == "list_files" for e in log)


# =============================================================================
# 3B: 协同策略映射表
# =============================================================================

class TestStrategyMappingTable:
    """任务类型 → 执行策略映射表（3B）。"""

    def test_mapping_table_exists_and_non_empty(self):
        from core.agent.execution_planner import TASK_TYPE_STRATEGY_MAP
        assert isinstance(TASK_TYPE_STRATEGY_MAP, dict)
        assert len(TASK_TYPE_STRATEGY_MAP) > 0

    def test_fast_response_maps_to_single(self):
        from core.agent.execution_planner import TASK_TYPE_STRATEGY_MAP
        assert TASK_TYPE_STRATEGY_MAP.get("fast_response") == "single"

    def test_swarm_maps_to_swarm(self):
        from core.agent.execution_planner import TASK_TYPE_STRATEGY_MAP
        assert TASK_TYPE_STRATEGY_MAP.get("swarm") == "swarm"

    def test_research_maps_to_specialized(self):
        from core.agent.execution_planner import TASK_TYPE_STRATEGY_MAP
        assert TASK_TYPE_STRATEGY_MAP.get("research") == "specialized"

    def test_pick_strategy_uses_mapping_first(self):
        """task_type 在映射表中时，_pick_strategy 优先使用映射。"""
        from core.agent.execution_planner import ExecutionPlanner
        planner = ExecutionPlanner(llm_router=None)

        # fast_response → single，即使 complexity 很高
        result = planner._pick_strategy("complex long message " * 20, complexity=0.9, task_type="fast_response")
        assert result == "single"

    def test_pick_strategy_falls_back_when_no_mapping(self):
        """task_type 不在映射表时回退到原有复杂度规则。"""
        from core.agent.execution_planner import ExecutionPlanner
        planner = ExecutionPlanner(llm_router=None)

        result = planner._pick_strategy("普通消息", complexity=0.3, task_type="unknown_type")
        # 低复杂度无关键词 → single
        assert result == "single"

    def test_pick_strategy_keyword_still_works(self):
        """即使 task_type 不在表中，关键词规则依然生效。"""
        from core.agent.execution_planner import ExecutionPlanner
        planner = ExecutionPlanner(llm_router=None)

        result = planner._pick_strategy("swarm 批量任务处理", complexity=0.3, task_type="")
        assert result == "swarm"


# =============================================================================
# 4B: 任务记忆/长期记忆
# =============================================================================

class TestTaskMemory:
    """任务记忆: 写入/读取/注入 context（4B）。"""

    def _make_memory(self):
        """每个测试使用独立的临时目录，避免文件污染。"""
        from core.task_memory import TaskMemory
        tmp = tempfile.mkdtemp()
        return TaskMemory(data_dir=tmp)

    def test_record_task_returns_summary(self):
        mem = self._make_memory()
        entry = mem.record_task(task="搜索 Python 教程", result_summary="找到 5 篇", success=True)
        assert entry.task == "搜索 Python 教程"
        assert entry.success is True

    def test_get_recent_summaries(self):
        mem = self._make_memory()
        for i in range(5):
            mem.record_task(task=f"task_{i}")
        recent = mem.get_recent_summaries(n=3)
        assert len(recent) == 3
        # 应为最近的 3 条
        assert recent[-1].task == "task_4"

    def test_persistence_to_file(self):
        """记录写入文件，重新加载后可读取。"""
        import json
        from core.task_memory import TaskMemory
        tmp = tempfile.mkdtemp()
        mem1 = TaskMemory(data_dir=tmp)
        mem1.record_task(task="persistent task", success=True)

        # 新实例从同一目录加载
        mem2 = TaskMemory(data_dir=tmp)
        recent = mem2.get_recent_summaries(n=5)
        tasks = [s.task for s in recent]
        assert "persistent task" in tasks

    def test_inject_into_context_adds_hint(self):
        mem = self._make_memory()
        mem.record_task(task="上一次任务", result_summary="成功完成")
        ctx = [{"role": "user", "content": "新任务"}]
        new_ctx = mem.inject_into_context(ctx, n=1)
        assert len(new_ctx) == 2  # hint + original
        assert "[TaskMemory]" in new_ctx[0]["content"]

    def test_inject_idempotent(self):
        """重复调用 inject_into_context 不应重复注入。"""
        mem = self._make_memory()
        mem.record_task(task="test")
        ctx = [{"role": "user", "content": "msg"}]
        ctx2 = mem.inject_into_context(ctx, n=1)
        ctx3 = mem.inject_into_context(ctx2, n=1)
        # 第二次注入应跳过
        marker_count = sum(1 for c in ctx3 if "[TaskMemory]" in c.get("content", ""))
        assert marker_count == 1

    def test_get_stats(self):
        mem = self._make_memory()
        mem.record_task(task="t1", success=True, strategy="single")
        mem.record_task(task="t2", success=False, strategy="specialized")
        stats = mem.get_stats()
        assert stats["total"] == 2
        assert stats["successful"] == 1
        assert stats["failed"] == 1
        assert "single" in stats["strategy_distribution"]

    def test_empty_memory_inject_returns_original(self):
        mem = self._make_memory()
        ctx = [{"role": "user", "content": "hello"}]
        result = mem.inject_into_context(ctx, n=5)
        # 无记录时返回原始 context
        assert result == ctx


# =============================================================================
# 5C: 执行链路可视化字段
# =============================================================================

class TestExecutionVisualizationFields:
    """ExecutionResult 包含 total_latency_ms / total_tokens / total_cost_usd（5C）。"""

    def test_execution_result_has_new_fields(self):
        from core.agent.execution_planner import ExecutionResult
        r = ExecutionResult(success=True, reply="done")
        # 字段存在且默认 None（向后兼容）
        assert hasattr(r, "total_latency_ms")
        assert hasattr(r, "total_tokens")
        assert hasattr(r, "total_cost_usd")
        assert r.total_latency_ms is None
        assert r.total_tokens is None
        assert r.total_cost_usd is None

    def test_execution_result_can_set_new_fields(self):
        from core.agent.execution_planner import ExecutionResult
        r = ExecutionResult(
            success=True,
            reply="done",
            total_latency_ms=123.4,
            total_tokens=500,
            total_cost_usd=0.00123,
        )
        assert r.total_latency_ms == pytest.approx(123.4)
        assert r.total_tokens == 500
        assert r.total_cost_usd == pytest.approx(0.00123)

    def test_execution_result_serializable(self):
        """新字段不破坏 Pydantic model_dump / JSON 序列化。"""
        from core.agent.execution_planner import ExecutionResult
        r = ExecutionResult(
            success=True,
            reply="test",
            total_latency_ms=50.0,
            total_tokens=100,
            total_cost_usd=0.001,
        )
        d = r.model_dump()
        assert "total_latency_ms" in d
        assert "total_tokens" in d
        assert "total_cost_usd" in d

    def test_old_fields_still_present(self):
        """现有字段不受影响（向后兼容性）。"""
        from core.agent.execution_planner import ExecutionResult
        r = ExecutionResult(
            success=True,
            reply="done",
            duration_ms=99.0,
            chosen_strategy="single",
            soul_enforced=True,
        )
        assert r.duration_ms == pytest.approx(99.0)
        assert r.chosen_strategy == "single"
        assert r.soul_enforced is True


# =============================================================================
# 整合：C阶段 API 路由
# =============================================================================

class TestCStageAPIRoutes:
    """C阶段 API 路由基本可加载（2C/3B/4B）。"""

    def test_c_stage_router_importable(self):
        from core.routes.c_stage import create_router
        router = create_router()
        assert router is not None

    def test_strategy_endpoint_path_exists(self):
        from core.routes.c_stage import create_router
        router = create_router()
        paths = [r.path for r in router.routes]
        assert "/api/v1/strategy/mappings" in paths

    def test_memory_endpoints_exist(self):
        from core.routes.c_stage import create_router
        router = create_router()
        paths = [r.path for r in router.routes]
        assert "/api/v1/memory/tasks" in paths
        assert "/api/v1/memory/stats" in paths

    def test_guardian_audit_endpoint_exists(self):
        from core.routes.c_stage import create_router
        router = create_router()
        paths = [r.path for r in router.routes]
        assert "/api/v1/guardian/audit" in paths
