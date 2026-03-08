"""
高级 Agent 系统测试
===================

测试 Agent Swarm、Special Forces Team、Twin Commander 三大模块。
所有 LLM 调用均 mock，不依赖真实 API。
"""

import asyncio
import sys
import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

# 确保项目根目录在 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    """同步运行异步协程"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─────── Mock LLM Response ───────

@dataclass
class MockLLMResponse:
    content: str = "mock response"
    provider: str = "mock"
    model: str = "mock-model"
    latency_ms: float = 10.0
    usage: dict = None

    def __post_init__(self):
        if self.usage is None:
            self.usage = {"input_tokens": 10, "output_tokens": 20}


def _make_mock_router(chat_response=None, chat_json_response=None):
    """创建 mock LLM router"""
    router = MagicMock()
    router.chat = AsyncMock(return_value=chat_response or MockLLMResponse())
    router.chat_json = AsyncMock(return_value=chat_json_response or {})
    router.providers = {
        "anthropic": MagicMock(
            status=MagicMock(value="healthy"),
            default_model="claude-sonnet-4-5-20250929",
        ),
        "openai": MagicMock(
            status=MagicMock(value="healthy"),
            default_model="gpt-4o",
        ),
        "deepseek": MagicMock(
            status=MagicMock(value="healthy"),
            default_model="deepseek-chat",
        ),
    }
    return router


def _make_mock_factory():
    """创建 mock Agent factory"""
    from core.agent_factory import (
        AgentFactory, AgentConfig, AgentRole, AgentCapability,
        TaskAgent, AgentState, CreationMode,
    )

    factory = MagicMock(spec=AgentFactory)
    _counter = [0]

    def _create_from_template(template_name, parent_id=None, overrides=None):
        _counter[0] += 1
        name = (overrides or {}).get("name", f"mock_agent_{_counter[0]}")
        agent = TaskAgent(
            id=f"agent_mock_{_counter[0]:04d}",
            config=AgentConfig(
                role=AgentRole.COORDINATOR,
                name=name,
                description="mock agent",
                capabilities=[AgentCapability("mock", "mock")],
                system_prompt="mock",
            ),
            creation_mode=CreationMode.TEMPLATE,
        )
        return agent

    factory.create_from_template = MagicMock(side_effect=_create_from_template)
    factory.terminate_agent = MagicMock()
    return factory


# ============================================================================
# Agent Swarm 测试
# ============================================================================

class TestAgentSwarm(unittest.TestCase):

    def _reset_singleton(self):
        import core.agent_swarm as mod
        mod._swarm_instance = None

    def setUp(self):
        self._reset_singleton()

    def test_swarm_same_task_execution(self):
        """蜂群 SAME_TASK 策略：所有 Agent 执行同一任务"""
        from core.agent_swarm import AgentSwarm, SwarmConfig, SwarmStrategy

        router = _make_mock_router(
            chat_response=MockLLMResponse(content="分析完成：答案是42"),
        )
        factory = _make_mock_factory()
        config = SwarmConfig(swarm_size=3, strategy=SwarmStrategy.SAME_TASK, aggregation="best")

        swarm = AgentSwarm(llm_router=router, agent_factory=factory, config=config)
        result = _run(swarm.execute("计算答案"))

        assert result.agents_succeeded == 3
        assert result.agents_failed == 0
        assert result.aggregated_output is not None
        assert len(result.agent_results) == 3

    def test_swarm_split_task(self):
        """蜂群 SPLIT_TASK 策略：任务分片"""
        from core.agent_swarm import AgentSwarm, SwarmConfig, SwarmStrategy

        router = _make_mock_router(
            chat_response=MockLLMResponse(content="分片结果"),
            chat_json_response={"parts": ["part1", "part2"]},
        )
        factory = _make_mock_factory()
        config = SwarmConfig(swarm_size=2, strategy=SwarmStrategy.SPLIT_TASK)

        swarm = AgentSwarm(llm_router=router, agent_factory=factory, config=config)
        result = _run(swarm.execute("分析大量数据"))

        assert result.agents_succeeded == 2
        assert result.strategy == SwarmStrategy.SPLIT_TASK

    def test_swarm_compete(self):
        """蜂群 COMPETE 策略：竞速"""
        from core.agent_swarm import AgentSwarm, SwarmConfig, SwarmStrategy

        router = _make_mock_router(
            chat_response=MockLLMResponse(content="快速答案"),
        )
        factory = _make_mock_factory()
        config = SwarmConfig(swarm_size=3, strategy=SwarmStrategy.COMPETE)

        swarm = AgentSwarm(llm_router=router, agent_factory=factory, config=config)
        result = _run(swarm.execute("快速回答问题"))

        assert result.agents_succeeded >= 1
        assert result.aggregated_output is not None

    def test_swarm_semaphore_limits(self):
        """验证并发限制"""
        from core.agent_swarm import AgentSwarm, SwarmConfig, SwarmStrategy

        max_concurrent_seen = [0]
        current_concurrent = [0]

        original_chat = AsyncMock(return_value=MockLLMResponse(content="ok"))

        async def tracked_chat(*args, **kwargs):
            current_concurrent[0] += 1
            max_concurrent_seen[0] = max(max_concurrent_seen[0], current_concurrent[0])
            await asyncio.sleep(0.01)
            current_concurrent[0] -= 1
            return MockLLMResponse(content="ok")

        router = _make_mock_router()
        router.chat = tracked_chat
        factory = _make_mock_factory()
        config = SwarmConfig(swarm_size=5, max_concurrent=2, strategy=SwarmStrategy.SAME_TASK)

        swarm = AgentSwarm(llm_router=router, agent_factory=factory, config=config)
        result = _run(swarm.execute("测试并发"))

        assert result.agents_succeeded == 5
        assert max_concurrent_seen[0] <= 2

    def test_swarm_agent_cleanup(self):
        """验证执行后 Agent 被清理"""
        from core.agent_swarm import AgentSwarm, SwarmConfig

        router = _make_mock_router(
            chat_response=MockLLMResponse(content="done"),
        )
        factory = _make_mock_factory()
        config = SwarmConfig(swarm_size=3)

        swarm = AgentSwarm(llm_router=router, agent_factory=factory, config=config)
        _run(swarm.execute("test"))

        assert factory.terminate_agent.call_count == 3
        assert len(swarm._active_agents) == 0

    def test_swarm_no_llm_degraded(self):
        """无 LLM Router 时降级执行"""
        from core.agent_swarm import AgentSwarm, SwarmConfig

        config = SwarmConfig(swarm_size=2)
        swarm = AgentSwarm(llm_router=None, agent_factory=None, config=config)
        result = _run(swarm.execute("降级测试"))

        assert result.agents_succeeded == 2
        assert result.aggregated_output is not None

    def test_swarm_get_status(self):
        """状态查询"""
        from core.agent_swarm import AgentSwarm, SwarmConfig

        swarm = AgentSwarm(config=SwarmConfig(swarm_size=7))
        status = swarm.get_status()
        assert status["swarm_size"] == 7
        assert status["strategy"] == "same_task"


# ============================================================================
# Special Forces Team 测试
# ============================================================================

class TestSpecialForcesTeam(unittest.TestCase):

    def _reset_singleton(self):
        import core.special_forces_team as mod
        mod._team_instance = None

    def setUp(self):
        self._reset_singleton()

    def test_team_assembly(self):
        """团队组建 — 根据任务选择角色"""
        from core.special_forces_team import SpecialForcesTeam, TeamRole

        router = _make_mock_router(
            chat_json_response={"roles": ["coder", "analyst"]},
        )
        factory = _make_mock_factory()

        team = SpecialForcesTeam(llm_router=router, agent_factory=factory)
        members = _run(team.assemble("编写数据分析代码"))

        roles = [m.role for m in members]
        assert TeamRole.LEAD in roles
        assert TeamRole.CODER in roles
        assert TeamRole.ANALYST in roles

    def test_team_multi_provider(self):
        """验证不同成员使用不同 provider"""
        from core.special_forces_team import SpecialForcesTeam

        router = _make_mock_router(
            chat_response=MockLLMResponse(content="result"),
            chat_json_response={"roles": ["strategist", "coder"]},
        )
        factory = _make_mock_factory()

        team = SpecialForcesTeam(llm_router=router, agent_factory=factory)
        members = _run(team.assemble("复杂任务"))

        providers = {m.provider for m in members}
        # 至少有 2 个不同 provider（anthropic + deepseek）
        assert len(providers) >= 2

    def test_team_parallel_mode(self):
        """并行模式执行"""
        from core.special_forces_team import (
            SpecialForcesTeam, TeamConfig, CoordinationMode,
        )

        router = _make_mock_router(
            chat_response=MockLLMResponse(content="parallel result"),
            chat_json_response={
                "roles": ["strategist"],
                "assignments": {"strategist": "分析策略"},
            },
        )
        factory = _make_mock_factory()
        config = TeamConfig(coordination_mode=CoordinationMode.PARALLEL)

        team = SpecialForcesTeam(llm_router=router, agent_factory=factory, config=config)
        result = _run(team.execute("并行任务"))

        assert result.final_output is not None
        assert result.total_latency_ms > 0

    def test_team_sequential_mode(self):
        """顺序模式执行"""
        from core.special_forces_team import (
            SpecialForcesTeam, TeamConfig, CoordinationMode,
        )

        router = _make_mock_router(
            chat_response=MockLLMResponse(content="sequential result"),
            chat_json_response={
                "roles": ["scout", "strategist"],
                "assignments": {"scout": "搜索", "strategist": "分析"},
            },
        )
        factory = _make_mock_factory()
        config = TeamConfig(coordination_mode=CoordinationMode.SEQUENTIAL)

        team = SpecialForcesTeam(llm_router=router, agent_factory=factory, config=config)
        result = _run(team.execute("顺序任务"))

        assert result.final_output is not None

    def test_team_degraded_provider(self):
        """provider 不可用时降级"""
        from core.special_forces_team import SpecialForcesTeam

        router = _make_mock_router(
            chat_json_response={"roles": ["coder"]},
        )
        # 移除 deepseek provider
        del router.providers["deepseek"]
        factory = _make_mock_factory()

        team = SpecialForcesTeam(llm_router=router, agent_factory=factory)
        members = _run(team.assemble("代码任务"))

        # coder 应该降级到其他可用 provider
        coder = [m for m in members if m.role.value == "coder"]
        if coder:
            assert coder[0].provider != "deepseek"

    def test_team_rules_based_roles(self):
        """无 LLM 时基于规则选角色"""
        from core.special_forces_team import SpecialForcesTeam, TeamRole

        team = SpecialForcesTeam(llm_router=None, agent_factory=None)
        members = _run(team.assemble("编写代码实现功能"))

        roles = [m.role for m in members]
        assert TeamRole.LEAD in roles
        assert TeamRole.CODER in roles

    def test_team_get_status(self):
        """状态查询"""
        from core.special_forces_team import SpecialForcesTeam

        team = SpecialForcesTeam()
        status = team.get_status()
        assert "coordination_mode" in status
        assert "composition_roles" in status


# ============================================================================
# Twin Commander 测试
# ============================================================================

class TestTwinCommander(unittest.TestCase):

    def _reset_singleton(self):
        import core.twin_commander as mod
        mod._commander_instance = None

    def setUp(self):
        self._reset_singleton()

    def test_dual_analysis(self):
        """双方独立分析"""
        from core.twin_commander import TwinCommander

        router = _make_mock_router(
            chat_json_response={
                "plan": {"approach": "test", "steps": ["step1"]},
                "confidence": 0.8,
                "risks": ["risk1"],
                "reasoning": "because",
                "agreement": 0.9,
                "objections": [],
                "suggestions": [],
                "strengths": ["good"],
            },
        )

        cmd = TwinCommander(llm_router=router)
        result = _run(cmd.analyze("测试任务"))

        assert result.commander_a_analysis is not None
        assert result.commander_b_analysis is not None
        assert result.commander_a_analysis.commander_id == "commander_alpha"
        assert result.commander_b_analysis.commander_id == "commander_beta"

    def test_cross_validation(self):
        """交叉验证被调用"""
        from core.twin_commander import TwinCommander

        call_count = [0]

        async def mock_chat_json(*args, **kwargs):
            call_count[0] += 1
            return {
                "plan": {"approach": "test"}, "confidence": 0.7,
                "risks": [], "reasoning": "ok",
                "agreement": 0.8, "objections": [], "suggestions": [],
            }

        router = _make_mock_router()
        router.chat_json = mock_chat_json

        cmd = TwinCommander(llm_router=router)
        result = _run(cmd.analyze("交叉验证测试"))

        # 至少 4 次调用：2 次分析 + 2 次交叉验证
        assert call_count[0] >= 4
        assert result.agreement_score > 0

    def test_debate_consensus(self):
        """辩论模式共识"""
        from core.twin_commander import TwinCommander, ConsensusStrategy

        round_count = [0]

        async def mock_chat_json(*args, **kwargs):
            round_count[0] += 1
            # 前几轮低一致性，后续高一致性
            agreement = 0.3 if round_count[0] <= 4 else 0.9
            return {
                "plan": {"approach": f"plan_v{round_count[0]}"}, "confidence": 0.8,
                "risks": [], "reasoning": "revised",
                "agreement": agreement, "objections": ["issue"], "suggestions": ["fix"],
            }

        router = _make_mock_router()
        router.chat_json = mock_chat_json

        cmd = TwinCommander(
            llm_router=router,
            consensus_strategy=ConsensusStrategy.DEBATE,
            max_debate_rounds=3,
        )
        result = _run(cmd.analyze("需要辩论的任务"))

        assert result.consensus_strategy_used == ConsensusStrategy.DEBATE
        assert result.debate_rounds >= 1

    def test_confidence_defer(self):
        """信心优先模式"""
        from core.twin_commander import (
            TwinCommander, ConsensusStrategy, CommanderConfig,
        )

        call_idx = [0]

        async def mock_chat_json(*args, **kwargs):
            call_idx[0] += 1
            # A 的 confidence=0.9, B 的 confidence=0.4
            if call_idx[0] == 1:
                return {
                    "plan": {"approach": "plan_A"}, "confidence": 0.9,
                    "risks": [], "reasoning": "A is confident",
                }
            elif call_idx[0] == 2:
                return {
                    "plan": {"approach": "plan_B"}, "confidence": 0.4,
                    "risks": [], "reasoning": "B is unsure",
                }
            else:
                return {
                    "agreement": 0.6, "objections": [], "suggestions": [],
                }

        router = _make_mock_router()
        router.chat_json = mock_chat_json

        cmd = TwinCommander(
            llm_router=router,
            consensus_strategy=ConsensusStrategy.DEFER_TO_CONFIDENCE,
        )
        result = _run(cmd.analyze("选择信心高的"))

        assert result.consensus.get("approach") == "plan_A"

    def test_merge_strategy(self):
        """合并模式"""
        from core.twin_commander import TwinCommander, ConsensusStrategy

        async def mock_chat_json(*args, **kwargs):
            messages = args[0] if args else kwargs.get("messages", [])
            sys_content = messages[0]["content"] if messages else ""
            if "合并" in sys_content or "merge" in sys_content.lower():
                return {
                    "plan": {"approach": "merged_plan", "steps": ["a", "b"]},
                    "merge_reasoning": "combined both",
                }
            return {
                "plan": {"approach": "individual"}, "confidence": 0.7,
                "risks": [], "reasoning": "ok",
                "agreement": 0.5, "objections": [], "suggestions": [],
            }

        router = _make_mock_router()
        router.chat_json = mock_chat_json

        cmd = TwinCommander(
            llm_router=router,
            consensus_strategy=ConsensusStrategy.MERGE,
        )
        result = _run(cmd.analyze("需要合并的任务"))

        assert result.consensus_strategy_used == ConsensusStrategy.MERGE

    def test_no_llm_degraded(self):
        """无 LLM 降级"""
        from core.twin_commander import TwinCommander

        cmd = TwinCommander(llm_router=None)
        result = _run(cmd.analyze("降级任务"))

        assert result.commander_a_analysis is not None
        assert result.commander_b_analysis is not None
        assert result.commander_a_analysis.confidence == 0.5

    def test_decide_and_dispatch(self):
        """高层决策接口"""
        from core.twin_commander import TwinCommander

        router = _make_mock_router(
            chat_json_response={
                "plan": {"approach": "test", "execution_strategy": "swarm"},
                "confidence": 0.8, "risks": [], "reasoning": "ok",
                "agreement": 0.9, "objections": [], "suggestions": [],
            },
        )

        cmd = TwinCommander(llm_router=router)
        dispatch = _run(cmd.decide_and_dispatch("复杂任务"))

        assert "consensus" in dispatch
        assert "recommended_execution" in dispatch

    def test_get_status(self):
        """状态查询"""
        from core.twin_commander import TwinCommander

        cmd = TwinCommander()
        status = cmd.get_status()
        assert status["commander_a"]["perspective"] == "analytical"
        assert status["commander_b"]["perspective"] == "creative"


# ============================================================================
# Agent Factory 扩展测试
# ============================================================================

class TestAgentFactoryExtensions(unittest.TestCase):

    def test_new_agent_roles(self):
        """新增的 AgentRole 枚举值"""
        from core.agent_factory import AgentRole
        assert AgentRole.SWARM_MEMBER.value == "swarm_member"
        assert AgentRole.COMMANDER.value == "commander"

    def test_new_creation_modes(self):
        """新增的 CreationMode 枚举值"""
        from core.agent_factory import CreationMode
        assert CreationMode.SWARM.value == "swarm"
        assert CreationMode.TEAM.value == "team"
        assert CreationMode.TWIN_COMMAND.value == "twin_command"

    def test_new_templates_exist(self):
        """新增的模板存在"""
        from core.agent_factory import AGENT_TEMPLATES
        assert "swarm_coordinator" in AGENT_TEMPLATES
        assert "special_forces_member" in AGENT_TEMPLATES
        assert "twin_commander" in AGENT_TEMPLATES

    def test_swarm_coordinator_template(self):
        """蜂群协调模板配置正确"""
        from core.agent_factory import AGENT_TEMPLATES, AgentRole
        tpl = AGENT_TEMPLATES["swarm_coordinator"]
        assert tpl.role == AgentRole.COORDINATOR
        assert tpl.max_subtasks == 10

    def test_twin_commander_template(self):
        """孪生指挥官模板配置正确"""
        from core.agent_factory import AGENT_TEMPLATES, AgentRole
        tpl = AGENT_TEMPLATES["twin_commander"]
        assert tpl.role == AgentRole.COMMANDER

    def test_create_from_new_templates(self):
        """可以从新模板创建 Agent"""
        from core.agent_factory import AgentFactory

        factory = AgentFactory()
        for template_name in ["swarm_coordinator", "special_forces_member", "twin_commander"]:
            agent = factory.create_from_template(template_name)
            assert agent is not None
            assert agent.id.startswith("agent_")


# ============================================================================
# Capability Orchestrator 集成测试
# ============================================================================

class TestCapabilityOrchestratorIntegration(unittest.TestCase):

    def test_new_builtins_registered(self):
        """新增的内置能力已注册"""
        from core.capability_orchestrator import CapabilityOrchestrator

        orch = CapabilityOrchestrator()
        # _load_builtins() 在 async initialize() 中调用，手动触发
        orch._load_builtins()
        caps = {c.id for c in orch.capabilities.values()}

        assert "builtin_swarm_execute" in caps
        assert "builtin_team_execute" in caps
        assert "builtin_twin_decide" in caps


if __name__ == "__main__":
    unittest.main()
