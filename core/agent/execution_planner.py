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

    tool_schemas: List[Dict[str, Any]] = Field(default_factory=list)
    """OpenAI function calling 格式的工具 schema 列表，由 ExecutionPlanner 从 CapabilityRegistry 注入"""

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
    # Auto-created agent info (optional, for UI surfacing)
    auto_agent_id: Optional[str] = None
    auto_agent_template: Optional[str] = None


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

    # PR86: 工具摘要中展示的最大工具数（避免 prompt 过长）
    _MAX_TOOL_SUMMARY_COUNT = 20
    # PR86: 能力注入标记（用于防止重复注入）
    _CAPABILITY_HINT_MARKER = "[CapabilityRegistry]"

    # Auto-agent template selection mapping: (keywords, template_name)
    # Type: List[Tuple[List[str], str]]
    _TEMPLATE_MAP: List[tuple] = [
        (["设备", "控制", "device", "hardware", "phone", "手机", "电脑", "平板",
          "screenshot", "截图", "截屏", "click", "点击", "swipe", "滑动"], "device_controller"),
        (["代码", "编程", "code", "script", "program", "写代码", "写脚本",
          "python", "javascript", "java", "function", "函数", "调试"], "code_executor"),
        (["分析", "数据", "统计", "analyze", "analyse", "data", "stat",
          "报告", "report", "insight", "chart", "图表"], "data_analyst"),
        (["搜索", "调研", "research", "search", "查找", "find",
          "信息", "news", "latest", "最新"], "research"),
        (["计划", "规划", "plan", "strategy", "策略", "步骤", "steps",
          "schedule", "路线图", "roadmap"], "planner"),
        (["协调", "team", "并行", "parallel", "分工", "多个", "组织"], "coordinator"),
    ]

    def __init__(self, llm_router: Optional[Any] = None) -> None:
        self._llm_router = llm_router

    def _auto_select_template(self, message: str, intent: IntentResult) -> str:
        """根据消息内容和意图自动选择最合适的 Agent 模板。"""
        msg = message.lower()
        for keywords, template in self._TEMPLATE_MAP:
            if any(kw in msg for kw in keywords):
                return template
        # Fallback: check task_hint from intent result
        if intent.task_hint:
            hint = intent.task_hint.lower()
            for keywords, template in self._TEMPLATE_MAP:
                if any(kw in hint for kw in keywords):
                    return template
        # Default: coordinator handles general/complex tasks
        return "coordinator"

    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        """
        执行计划入口。（PR86）

        约束：
        - 执行前必须从 CapabilityRegistry 刷新并拉取可用工具列表
        - 不允许绕过 CapabilityRegistry 直接硬编码工具调用
        - 执行策略选择：
            - 低复杂度任务 → 单 Agent
            - 高复杂度任务 → Team (SPECIALIZED) 或 Swarm
            - 涉及多设备 → Team + Gateway
        """
        t0 = time.monotonic()
        steps: List[StepRecord] = []
        tool_calls: List[ToolCallRecord] = []

        complexity = _estimate_complexity(plan.message)
        strategy = self._pick_strategy(plan.message, complexity)

        logger.info(
            "ExecutionPlanner: 开始执行 | strategy=%s complexity=%.2f intent=%s",
            strategy,
            complexity,
            plan.intent.mode,
        )

        # PR86 强制要求：从 CapabilityRegistry 拉取工具（禁止旁路）
        available_tools: List[Any] = []
        cap_stats: Dict[str, Any] = {}
        try:
            from core.agent.capability_registry import get_capability_registry
            registry = get_capability_registry()
            await registry.refresh()  # 确保最新
            available_tools = registry.list_tools()
            cap_stats = registry.stats()
            tool_schemas = registry.to_tool_schemas()
            logger.info(
                "ExecutionPlanner: CapabilityRegistry 已刷新 | "
                "total=%d available=%d (mcp=%d skill=%d gateway=%d)",
                cap_stats.get("total", 0),
                cap_stats.get("available", 0),
                cap_stats.get("by_source", {}).get("mcp", 0),
                cap_stats.get("by_source", {}).get("skill", 0),
                cap_stats.get("by_source", {}).get("gateway", 0),
            )
            # 将工具 schema 存储到 plan，供 LLM function calling 使用
            plan.tool_schemas = tool_schemas
            # 将工具 schema 注入到执行计划上下文，供 Agent 使用
            if available_tools and not plan.context:
                plan.context = []
            # 提供工具信息给 plan（通过 context 传递工具摘要）
            tool_summary = ", ".join(t.name for t in available_tools[:self._MAX_TOOL_SUMMARY_COUNT])
            if available_tools:
                plan.context = plan.context or []
                # 在上下文中注入工具列表提示（不覆盖已有对话历史）
                _tool_hint = {
                    "role": "system",
                    "content": f"{self._CAPABILITY_HINT_MARKER} 可用工具: {tool_summary}"
                    + (f"... 共 {len(available_tools)} 项"
                       if len(available_tools) > self._MAX_TOOL_SUMMARY_COUNT else ""),
                }
                # 只在没有同类 hint 时才插入
                if not any(
                    self._CAPABILITY_HINT_MARKER in c.get("content", "") for c in plan.context
                ):
                    plan.context = [_tool_hint] + plan.context
        except Exception as e:
            logger.warning("ExecutionPlanner: CapabilityRegistry 刷新失败（继续执行）: %s", e)

        try:
            result = await asyncio.wait_for(
                self._dispatch(plan, strategy, steps, tool_calls),
                timeout=plan.timeout,
            )
            duration_ms = (time.monotonic() - t0) * 1000
            result.agent_steps = steps
            result.tool_calls = tool_calls
            result.duration_ms = duration_ms
            # 在结果中记录工具来源
            if result.task_result is None:
                result.task_result = {}
            result.task_result["capability_stats"] = cap_stats
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

            # 自动选择最合适的 Agent 模板
            selected_template = self._auto_select_template(plan.message, plan.intent)
            agent = None

            # 优先从模板创建（快速、确定）
            try:
                agent = factory.create_from_template(selected_template)
                logger.info(
                    "ExecutionPlanner: 自动选择模板 '%s' → Agent %s",
                    selected_template, agent.id,
                )
            except Exception as tmpl_err:
                logger.debug("模板创建失败 (%s)，尝试 LLM 生成: %s", selected_template, tmpl_err)
                # 回退到 LLM 动态生成
                try:
                    agent = await factory.create_from_llm(
                        task_description=task_with_policy,
                        context={"session_id": plan.session_id},
                    )
                    selected_template = ""  # LLM-generated, no fixed template
                except Exception:
                    # 最终降级: coordinator 模板
                    selected_template = "coordinator"
                    agent = factory.create_from_template(selected_template)

            step.output = {
                "agent_id": agent.id,
                "agent_name": agent.config.name,
                "template": selected_template,
            }
            steps.append(step)

            # 执行任务
            exec_step = StepRecord(name="Agent 执行", tool="agent_execute")
            t1 = time.monotonic()
            task_dict = {
                "description": plan.message,
                "context": {"soul": plan.soul_policy, "agents_policy": plan.agents_policy},
                "session_id": plan.session_id,
                "tools": plan.tool_schemas,
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
                auto_agent_id=agent.id,
                auto_agent_template=selected_template or None,
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
                "tools": plan.tool_schemas,
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
