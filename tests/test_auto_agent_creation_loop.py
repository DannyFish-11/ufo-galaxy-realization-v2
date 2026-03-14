"""
tests/test_auto_agent_creation_loop.py
=========================================
Acceptance tests for the OpenClawd auto-agent-creation loop (PR154 Loop C).

Covers:
  1. Trigger conditions   — AUTO_AGENT_TRIGGER_KEYWORDS defined and tested
  2. Factory invocation   — AgentFactory is automatically called when triggered
  3. Visibility / lifecycle — created agents queryable via get_agent_tree / get_status
  4. Safe fallback        — task continues with fallback if creation fails

Note:
  All LLM calls are mocked; no real services are required.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def factory():
    from core.agent_factory import AgentFactory
    f = AgentFactory(llm_router=None)
    f.agents.clear()
    f.agent_tree.clear()
    return f


@pytest.fixture
def planner():
    from core.agent.execution_planner import ExecutionPlanner
    return ExecutionPlanner(llm_router=None)


# ---------------------------------------------------------------------------
# Test 1: trigger conditions
# ---------------------------------------------------------------------------

class TestTriggerConditions:
    """Loop C-1: AUTO_AGENT_TRIGGER_KEYWORDS define explicit trigger rules."""

    def test_auto_agent_trigger_keywords_exported(self):
        """AUTO_AGENT_TRIGGER_KEYWORDS must be exported from execution_planner."""
        from core.agent.execution_planner import AUTO_AGENT_TRIGGER_KEYWORDS
        assert isinstance(AUTO_AGENT_TRIGGER_KEYWORDS, tuple)
        assert len(AUTO_AGENT_TRIGGER_KEYWORDS) > 0

    def test_auto_agent_trigger_keywords_include_parallel_signals(self):
        """Trigger keywords must include parallel/multi-step signals."""
        from core.agent.execution_planner import AUTO_AGENT_TRIGGER_KEYWORDS
        parallel_words = {"team", "swarm", "并行", "多个", "批量"}
        found = parallel_words & set(AUTO_AGENT_TRIGGER_KEYWORDS)
        assert found, f"Missing parallel keywords in AUTO_AGENT_TRIGGER_KEYWORDS: {parallel_words}"

    def test_complexity_estimate_high_for_trigger_message(self):
        """Messages containing trigger keywords must score higher complexity."""
        from core.agent.execution_planner import _estimate_complexity

        low_msg = "hello, what time is it?"
        high_msg = "请同时在多个设备上并行执行任务"

        low = _estimate_complexity(low_msg)
        high = _estimate_complexity(high_msg)
        assert high > low, f"Expected high ({high}) > low ({low})"

    def test_pick_strategy_returns_non_single_for_trigger_message(self):
        """_pick_strategy must not return 'single' for high-complexity trigger messages."""
        from core.agent.execution_planner import ExecutionPlanner, _estimate_complexity
        from core.agent.intent_router import IntentResult, IntentMode

        planner = ExecutionPlanner(llm_router=None)

        msg = "team 并行多个设备同时执行批量任务"
        complexity = _estimate_complexity(msg)
        strategy = planner._pick_strategy(msg, complexity)
        assert strategy != "single", f"Expected non-single strategy for trigger message, got: {strategy}"

    def test_pick_strategy_returns_single_for_simple_message(self):
        """_pick_strategy returns 'single' for simple, low-complexity messages."""
        from core.agent.execution_planner import ExecutionPlanner, _estimate_complexity
        from core.agent.intent_router import IntentResult, IntentMode

        planner = ExecutionPlanner(llm_router=None)

        msg = "hello"
        complexity = _estimate_complexity(msg)
        strategy = planner._pick_strategy(msg, complexity)
        assert strategy == "single"

    def test_task_type_strategy_map_exists_and_non_empty(self):
        """TASK_TYPE_STRATEGY_MAP must be a non-empty dict."""
        from core.agent.execution_planner import TASK_TYPE_STRATEGY_MAP
        assert isinstance(TASK_TYPE_STRATEGY_MAP, dict)
        assert len(TASK_TYPE_STRATEGY_MAP) > 0


# ---------------------------------------------------------------------------
# Test 2: factory invocation
# ---------------------------------------------------------------------------

class TestFactoryInvocation:
    """Loop C-2: AgentFactory is automatically invoked when trigger conditions met."""

    @pytest.mark.asyncio
    async def test_run_single_agent_invokes_agent_factory(self, factory):
        """_run_single_agent must call AgentFactory to create an agent."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult, IntentMode

        planner = ExecutionPlanner(llm_router=None)

        plan = ExecutionPlan(
            message="analyze this data",
            intent=IntentResult(
                mode=IntentMode.TASK_EXECUTE,
                raw_intent="task_execute",
                confidence=0.9,
            ),
            session_id="test_session",
        )

        with patch("core.agent_factory.get_agent_factory", return_value=factory):
            with patch.object(factory, "execute_agent_task", new_callable=AsyncMock) as mock_exec:
                mock_exec.return_value = {
                    "status": "success",
                    "reply": "analysis complete",
                    "results": [{"output": "analysis complete"}],
                }
                result = await planner._run_single_agent(plan, [], [])

        assert result.auto_agent_id is not None
        assert len(result.auto_agent_id) > 0

    @pytest.mark.asyncio
    async def test_run_single_agent_sets_template_in_result(self, factory):
        """_run_single_agent must set auto_agent_template in ExecutionResult."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult, IntentMode

        planner = ExecutionPlanner(llm_router=None)

        plan = ExecutionPlan(
            message="write some python code",
            intent=IntentResult(
                mode=IntentMode.TASK_EXECUTE,
                raw_intent="task_execute",
                confidence=0.9,
                task_hint="coding",
            ),
            session_id="test_session",
        )

        with patch("core.agent_factory.get_agent_factory", return_value=factory):
            with patch.object(factory, "execute_agent_task", new_callable=AsyncMock) as mock_exec:
                mock_exec.return_value = {
                    "status": "success",
                    "reply": "code written",
                    "results": [{"output": "code written"}],
                }
                result = await planner._run_single_agent(plan, [], [])

        assert result.auto_agent_template is not None
        assert result.auto_agent_template in list(__import__(
            "core.agent_factory", fromlist=["AGENT_TEMPLATES"]
        ).AGENT_TEMPLATES.keys())

    @pytest.mark.asyncio
    async def test_execute_plan_triggers_agent_creation(self, factory):
        """ExecutionPlanner.execute() must create an agent for task_execute intent."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult, IntentMode

        planner = ExecutionPlanner(llm_router=None)

        plan = ExecutionPlan(
            message="analyze some data",
            intent=IntentResult(
                mode=IntentMode.TASK_EXECUTE,
                raw_intent="task_execute",
                confidence=0.9,
            ),
            session_id="test_session",
        )

        with patch("core.agent_factory.get_agent_factory", return_value=factory), \
             patch.object(factory, "execute_agent_task", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {
                "status": "success",
                "reply": "done",
                "results": [{"output": "done"}],
            }
            result = await planner.execute(plan)

        assert result.auto_agent_id is not None


# ---------------------------------------------------------------------------
# Test 3: visibility and lifecycle
# ---------------------------------------------------------------------------

class TestAgentVisibilityAndLifecycle:
    """Loop C-3: created agents are queryable through existing APIs."""

    def test_agent_factory_get_agent_tree_includes_new_agent(self, factory):
        """get_agent_tree must include newly created agents."""
        from core.agent_factory import AgentFactory, AGENT_TEMPLATES

        # Create an agent via template
        agent = factory.create_from_template("coordinator")

        tree = factory.get_agent_tree()
        assert tree["total_agents"] >= 1

        # Agent should be in the tree roots (no parent)
        root_ids = [r["id"] for r in tree.get("roots", [])]
        assert agent.id in root_ids

    def test_agent_factory_get_status_includes_agent_count(self, factory):
        """get_status must reflect created agents in total_agents."""
        from core.agent_factory import AgentFactory

        initial_status = factory.get_status()
        initial_count = initial_status["total_agents"]

        factory.create_from_template("coordinator")
        new_status = factory.get_status()

        assert new_status["total_agents"] == initial_count + 1

    def test_agent_factory_get_all_agents_non_empty_after_creation(self, factory):
        """get_all_agents must return created agents as a dict."""
        from core.agent_factory import AgentFactory

        agent = factory.create_from_template("data_analyst")
        all_agents = factory.get_all_agents()

        assert agent.id in all_agents
        assert "id" in all_agents[agent.id]

    def test_execution_result_auto_agent_id_is_queryable(self, factory):
        """auto_agent_id in ExecutionResult can be used to query get_agent."""
        from core.agent_factory import AgentFactory

        agent = factory.create_from_template("coordinator")
        # Simulate ExecutionResult referring to this agent
        auto_agent_id = agent.id

        retrieved = factory.get_agent(auto_agent_id)
        assert retrieved is not None
        assert retrieved.id == auto_agent_id

    def test_execution_result_contains_task_session_binding(self):
        """ExecutionResult fields for session and task binding must exist."""
        from core.agent.execution_planner import ExecutionResult

        result = ExecutionResult(
            success=True,
            mode="single_agent",
            reply="done",
            auto_agent_id="agent_xyz",
            auto_agent_template="coordinator",
            chosen_strategy="single_agent",
        )

        assert result.auto_agent_id == "agent_xyz"
        assert result.auto_agent_template == "coordinator"
        assert result.chosen_strategy == "single_agent"


# ---------------------------------------------------------------------------
# Test 4: safe fallback when agent creation fails
# ---------------------------------------------------------------------------

class TestSafeFallbackOnCreationFailure:
    """Loop C-4: task continues with fallback if auto-agent creation fails."""

    @pytest.mark.asyncio
    async def test_run_single_agent_falls_back_to_coordinator_template(self, factory):
        """_run_single_agent falls back to 'coordinator' template if primary fails."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult, IntentMode

        planner = ExecutionPlanner(llm_router=None)
        plan = ExecutionPlan(
            message="do something impossible",
            intent=IntentResult(
                mode=IntentMode.TASK_EXECUTE,
                raw_intent="task_execute",
                confidence=0.9,
            ),
        )

        original_create = factory.create_from_template
        call_count = [0]

        def failing_first_create(template):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ValueError("Template 'impossible' not found")
            return original_create("coordinator")

        factory.create_from_template = failing_first_create

        with patch("core.agent_factory.get_agent_factory", return_value=factory), \
             patch.object(factory, "execute_agent_task", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {
                "status": "success",
                "reply": "fallback result",
                "results": [{"output": "fallback result"}],
            }
            # Should not raise; coordinator fallback must be used
            result = await planner._run_single_agent(plan, [], [])

        assert result.success is True or result.auto_agent_id is not None

    @pytest.mark.asyncio
    async def test_execute_plan_returns_error_result_not_raise_on_all_failures(self, factory):
        """ExecutionPlanner.execute() must return failure result, not raise."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult, IntentMode

        planner = ExecutionPlanner(llm_router=None)
        plan = ExecutionPlan(
            message="fail everything",
            intent=IntentResult(
                mode=IntentMode.TASK_EXECUTE,
                raw_intent="task_execute",
                confidence=0.9,
            ),
        )

        with patch("core.agent_factory.get_agent_factory", return_value=factory):
            factory.create_from_template = MagicMock(
                side_effect=RuntimeError("all templates failed")
            )
            result = await planner.execute(plan)

        # Must return a result, not raise
        assert isinstance(result.success, bool)
        assert result.success is False
        assert result.error != ""

    def test_agent_factory_get_agent_returns_none_for_unknown_id(self, factory):
        """get_agent must return None for unknown agent_id (safe lookup)."""
        result = factory.get_agent("nonexistent_agent_id_xyz")
        assert result is None

    @pytest.mark.asyncio
    async def test_task_continues_after_partial_team_creation_failure(self, factory):
        """ExecutionPlanner must return a result even when team AND fractal creation fail."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan, ExecutionResult
        from core.agent.intent_router import IntentResult, IntentMode

        planner = ExecutionPlanner(llm_router=None)

        # Use a message that triggers non-single strategy
        plan = ExecutionPlan(
            message="use team parallel multiple tasks at once",
            intent=IntentResult(
                mode=IntentMode.TASK_EXECUTE,
                raw_intent="task_execute",
                confidence=0.9,
            ),
        )

        # Patch both _run_team AND _run_fractal to raise, forcing fallback to single agent
        # or structured failure — the key requirement is that execute() returns an
        # ExecutionResult, not raises.
        async def failing_dispatch(*args, **kwargs):
            raise RuntimeError("all strategies failed")

        with patch.object(planner, "_dispatch", side_effect=failing_dispatch):
            result = await planner.execute(plan)

        assert isinstance(result, ExecutionResult)
        assert result.success is False
        assert result.error != ""
