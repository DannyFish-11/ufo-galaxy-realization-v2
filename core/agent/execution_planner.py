"""
core/agent/execution_planner.py
=================================
执行规划器 — 基于意图组装并执行任务计划

负责：
  1. 根据 IntentResult 决定执行策略（单 Agent / Team / Swarm）
  2. 加载 SOUL + AGENTS 策略并注入到执行上下文
  3. 调用 AgentFactory / TeamManager 创建并执行 Agent
  4. 返回结构化 ExecutionResult

数据模型（Pydantic）：
  - ExecutionPlan   — 执行计划（输入）
  - StepRecord      — 单步执行记录
  - ExecutionResult — 执行结果（输出）
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.agent.intent_router import IntentResult

logger = logging.getLogger("Galaxy.Agent.ExecutionPlanner")

# ──────────────────────────────────────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────────────────────────────────────


class StepRecord(BaseModel):
    """单步执行记录。"""

    step_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    tool: str = ""
    input: Dict[str, Any] = Field(default_factory=dict)
    output: Dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    error: str = ""
    duration_ms: float = 0.0


class ToolCallRecord(BaseModel):
    """工具调用记录。"""

    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result: Dict[str, Any] = Field(default_factory=dict)
    success: bool = True
    error: str = ""


class ExecutionPlan(BaseModel):
    """执行计划（输入）。"""

    message: str
    """原始用户消息"""

    intent: IntentResult
    """路由器输出的意图结果"""

    soul_policy: str = ""
    """SOUL.md 内容（仅 task_execute / hybrid 注入）"""

    agents_policy: str = ""
    """AGENTS.md 内容"""

    user_policy: str = ""
    """USER.md 内容"""

    session_id: str = ""
    device_id: str = ""
    context: List[Dict[str, str]] = Field(default_factory=list)
    """对话历史"""

    timeout: float = 60.0
    """任务执行超时（秒）"""


class ExecutionResult(BaseModel):
    """执行结果（输出）。"""

    success: bool = True
    mode: str = "task_execute"
    reply: str = ""
    agent_steps: List[StepRecord] = Field(default_factory=list)
    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    task_result: Optional[Dict[str, Any]] = None
    error: str = ""
    model: str = ""
    duration_ms: float = 0.0


# ──────────────────────────────────────────────────────────────────────────────
# 执行规划器
# ──────────────────────────────────────────────────────────────────────────────

# 任务复杂度阈值（决定 agent 策略）
_COMPLEXITY_KEYWORDS_HIGH = [
    "team", "swarm", "并行", "多个", "同时", "分别",
    "全部", "所有设备", "批量", "大量", "复杂",
]


def _estimate_complexity(message: str) -> float:
    """粗略估算任务复杂度 0~1。"""
    m = message.lower()
    score = 0.3  # baseline
    score += min(len(message) / 500, 0.3)  # 消息越长越复杂
    if any(k in m for k in _COMPLEXITY_KEYWORDS_HIGH):
        score += 0.4
    return min(score, 1.0)


class ExecutionPlanner:
    """执行规划器（无状态，每次调用独立）。"""

    def __init__(self, llm_router: Optional[Any] = None) -> None:
        self._llm_router = llm_router

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        """
        执行计划入口。

        根据意图选择执行策略：
          - 低复杂度任务 → 单 Agent
          - 高复杂度任务 → Team (SPECIALIZED) 或 Swarm
          - 涉及多设备 → Team + Gateway

        CapabilityRegistry 为强制依赖：每次执行前刷新注册表并将工具 schema
        注入到计划上下文，确保 LLM 始终获得最新能力列表，不允许绕过。
        """
        t0 = time.monotonic()
        steps: List[StepRecord] = []
        tool_calls: List[ToolCallRecord] = []

        # ── 强制刷新 CapabilityRegistry ──────────────────────────────
        tool_schemas: List[dict] = []
        try:
            from core.agent.capability_registry import CapabilityRegistry
            registry = CapabilityRegistry.get_instance()
            await registry.refresh()
            tool_schemas = registry.to_tool_schemas()
            logger.debug(
                "ExecutionPlanner: CapabilityRegistry 已刷新，可用工具 %d 项", len(tool_schemas)
            )
        except Exception as _cap_exc:
            logger.warning("ExecutionPlanner: CapabilityRegistry 刷新失败（继续执行）: %s", _cap_exc)

        # 将 tool_schemas 注入 plan context（供 Agent 使用）
        if tool_schemas and not any(c.get("role") == "__tool_schemas__" for c in plan.context):
            plan.context.append({"role": "__tool_schemas__", "content": str(tool_schemas)})
        # ─────────────────────────────────────────────────────────────

        complexity = _estimate_complexity(plan.message)
        strategy = self._pick_strategy(plan.message, complexity)

        logger.info(
            "ExecutionPlanner: 开始执行 | strategy=%s complexity=%.2f intent=%s",
            strategy,
            complexity,
            plan.intent.mode,
        )

        try:
            result = await asyncio.wait_for(
                self._dispatch(plan, strategy, steps, tool_calls),
                timeout=plan.timeout,
            )
            duration_ms = (time.monotonic() - t0) * 1000
            result.agent_steps = steps
            result.tool_calls = tool_calls
            result.duration_ms = duration_ms
            return result

        except asyncio.TimeoutError:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.error("ExecutionPlanner: 任务执行超时 (%.1fs)", plan.timeout)
            return ExecutionResult(
                success=False,
                mode=strategy,
                reply=f"任务执行超时（超过 {plan.timeout:.0f}s），请简化任务或稍后重试。",
                agent_steps=steps,
                tool_calls=tool_calls,
                error="timeout",
                duration_ms=duration_ms,
            )
        except Exception as exc:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.exception("ExecutionPlanner: 执行异常: %s", exc)
            return ExecutionResult(
                success=False,
                mode=strategy,
                reply=f"任务执行失败：{exc}",
                agent_steps=steps,
                tool_calls=tool_calls,
                error=str(exc),
                duration_ms=duration_ms,
            )

    # ──────────────────────────────────────────────────────────────────
    # 策略选择
    # ──────────────────────────────────────────────────────────────────

    def _pick_strategy(self, message: str, complexity: float) -> str:
        m = message.lower()
        if any(k in m for k in ["swarm", "群体", "大量", "批量"]):
            return "swarm"
        if complexity > 0.65 or any(k in m for k in ["team", "团队", "并行", "多个", "分工"]):
            return "specialized"
        return "single"

    # ──────────────────────────────────────────────────────────────────
    # 调度分发
    # ──────────────────────────────────────────────────────────────────

    async def _dispatch(
        self,
        plan: ExecutionPlan,
        strategy: str,
        steps: List[StepRecord],
        tool_calls: List[ToolCallRecord],
    ) -> ExecutionResult:
        if strategy in ("specialized", "parallel", "swarm"):
            return await self._run_team(plan, strategy, steps, tool_calls)
        return await self._run_single_agent(plan, steps, tool_calls)

    # ──────────────────────────────────────────────────────────────────
    # 单 Agent 执行
    # ──────────────────────────────────────────────────────────────────

    async def _run_single_agent(
        self,
        plan: ExecutionPlan,
        steps: List[StepRecord],
        tool_calls: List[ToolCallRecord],
    ) -> ExecutionResult:
        """通过 AgentFactory 创建单 Agent 执行任务。"""
        step = StepRecord(name="创建 Agent", tool="agent_factory")
        t0 = time.monotonic()

        try:
            from core.agent_factory import get_agent_factory
            factory = get_agent_factory(self._llm_router)

            # 构建带策略注入的任务描述
            task_with_policy = self._build_task_prompt(plan)

            # 尝试 LLM 生成 Agent，失败降级到模板
            try:
                agent = await factory.create_from_llm(
                    task_description=task_with_policy,
                    context={"session_id": plan.session_id},
                )
            except Exception:
                agent = factory.create_from_template("executor")

            step.output = {"agent_id": agent.id, "agent_name": agent.config.name}
            steps.append(step)

            # 执行任务
            exec_step = StepRecord(name="Agent 执行", tool="agent_execute")
            t1 = time.monotonic()
            task_dict = {
                "description": plan.message,
                "context": {"soul": plan.soul_policy, "agents_policy": plan.agents_policy},
                "session_id": plan.session_id,
            }
            exec_result = await factory.execute_agent_task(agent.id, task_dict)
            exec_step.duration_ms = (time.monotonic() - t1) * 1000
            exec_step.success = exec_result.get("success", True)
            exec_step.output = exec_result
            steps.append(exec_step)

            # 收集工具调用记录
            for tc in exec_result.get("tool_calls", []):
                tool_calls.append(ToolCallRecord(
                    tool=tc.get("tool", ""),
                    arguments=tc.get("arguments", {}),
                    result=tc.get("result", {}),
                    success=tc.get("success", True),
                    error=tc.get("error", ""),
                ))

            step.duration_ms = (time.monotonic() - t0) * 1000
            return ExecutionResult(
                success=exec_result.get("success", True),
                mode="single_agent",
                reply=exec_result.get("reply") or exec_result.get("result") or "任务已完成",
                task_result=exec_result,
                model=exec_result.get("model", ""),
            )

        except Exception as exc:
            step.success = False
            step.error = str(exc)
            step.duration_ms = (time.monotonic() - t0) * 1000
            steps.append(step)
            raise

    # ──────────────────────────────────────────────────────────────────
    # Team / Swarm 执行
    # ──────────────────────────────────────────────────────────────────

    async def _run_team(
        self,
        plan: ExecutionPlan,
        strategy: str,
        steps: List[StepRecord],
        tool_calls: List[ToolCallRecord],
    ) -> ExecutionResult:
        """通过 TeamManager 创建并执行 Agent Team / Swarm。"""
        step = StepRecord(name=f"创建 {strategy} Team", tool="team_manager")
        t0 = time.monotonic()

        try:
            from core.agent_team import TeamManager
            from core.agent_factory import get_agent_factory

            factory = get_agent_factory(self._llm_router)
            manager = TeamManager(
                agent_factory=factory,
                llm_router=self._llm_router,
            )

            team_strategy = "swarm" if strategy == "swarm" else "specialized"
            complexity = _estimate_complexity(plan.message)
            team = await manager.create_team(
                strategy=team_strategy,
                task_hint=plan.intent.task_hint or plan.message[:100],
                complexity_score=complexity,
            )

            step.output = {"team_id": team.team_id, "member_count": len(team.members)}
            steps.append(step)

            # 执行 Team 任务
            exec_step = StepRecord(name="Team 执行", tool="team_execute")
            t1 = time.monotonic()
            context = {
                "soul": plan.soul_policy,
                "agents_policy": plan.agents_policy,
                "session_id": plan.session_id,
            }
            team_result = await manager.execute_team(team.team_id, plan.message, context)
            exec_step.duration_ms = (time.monotonic() - t1) * 1000
            exec_step.success = team_result.success
            exec_step.output = team_result.to_dict()
            steps.append(exec_step)

            # 收集 member 结果中的工具调用
            for member_res in (team_result.member_results or []):
                for tc in member_res.tool_calls or []:
                    tool_calls.append(ToolCallRecord(
                        tool=tc if isinstance(tc, str) else tc.get("tool", ""),
                        result={},
                    ))

            step.duration_ms = (time.monotonic() - t0) * 1000
            return ExecutionResult(
                success=team_result.success,
                mode=f"team_{team_strategy}",
                reply=team_result.final_answer or "Team 任务已完成",
                task_result=team_result.to_dict(),
            )

        except Exception as exc:
            step.success = False
            step.error = str(exc)
            step.duration_ms = (time.monotonic() - t0) * 1000
            steps.append(step)
            raise

    # ──────────────────────────────────────────────────────────────────
    # 辅助
    # ──────────────────────────────────────────────────────────────────

    def _build_task_prompt(self, plan: ExecutionPlan) -> str:
        """构建注入了 SOUL + AGENTS 策略的任务 prompt。"""
        parts = []
        if plan.agents_policy:
            parts.append(f"【工作规范】\n{plan.agents_policy}")
        if plan.soul_policy:
            parts.append(f"【Agent 人格与能力边界】\n{plan.soul_policy}")
        parts.append(f"【用户任务】\n{plan.message}")
        return "\n\n".join(parts)
