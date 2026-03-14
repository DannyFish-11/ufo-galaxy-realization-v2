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

# C阶段 4B: 任务记忆（可选依赖）
try:
    from core.task_memory import get_task_memory as _get_task_memory
    _TASK_MEMORY_AVAILABLE = True
except ImportError:
    _TASK_MEMORY_AVAILABLE = False
    _get_task_memory = None  # type: ignore

logger = logging.getLogger("Galaxy.Agent.ExecutionPlanner")


# ──────────────────────────────────────────────────────────────────────────────
# TaskDecomposer helper for multi-device task paths
# ──────────────────────────────────────────────────────────────────────────────

async def _try_decompose_task(message: str, targets: list, context: dict) -> list:
    """Attempt to decompose a multi-target task into subtasks via TaskDecomposer.
    Falls back to broadcasting the original message to all targets."""
    if len(targets) <= 1:
        return [{"target": targets[0] if targets else None, "message": message}]
    try:
        from galaxy_gateway.task_decomposer import TaskDecomposer
        decomposer = TaskDecomposer(device_registry=None)
        # Use decompose_multi_device_command for multi-target tasks
        commands = [
            {"device_id": t, "action": "execute", "target": message}
            for t in targets
        ]
        tasks, _data_flows = decomposer.decompose_multi_device_command(commands)
        if tasks:
            return [
                {"target": task.device_id, "message": getattr(task, "target", message) or message}
                for task in tasks
            ]
    except Exception as e:
        logging.getLogger("Galaxy.ExecutionPlanner").debug(f"TaskDecomposer unavailable: {e}")
    return [{"target": t, "message": message} for t in targets]


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
    # Dynamic execution metadata (new fields — all optional for backward compat)
    chosen_strategy: Optional[str] = None
    """Execution strategy chosen: single_agent / team_specialized / team_swarm / fractal"""
    chosen_providers: Optional[List[str]] = None
    """LLM providers/models used during execution (e.g. ['deepseek:deepseek-chat'])"""
    twin_id: Optional[str] = None
    """ID of the digital twin created for the primary agent (if any)"""
    twin_coupling: Optional[str] = None
    """Twin coupling mode: tight / loose / decoupled / shadow (default: loose)"""
    soul_enforced: Optional[bool] = None
    """True when SOUL policy was actively injected into this execution path (single/team/swarm/fractal)"""
    # C阶段 5C: 执行链路可视化细化 — latency / token / cost（均为可选，保持向后兼容）
    total_latency_ms: Optional[float] = None
    """整条执行链路总延迟（毫秒），等同于 duration_ms，额外暴露便于 UI 消费"""
    total_tokens: Optional[int] = None
    """本次执行消耗的 LLM token 总量（input + output，汇总所有 Agent/成员）"""
    total_cost_usd: Optional[float] = None
    """本次执行估算总费用（USD），由 CostTracker 汇总"""


def _collect_team_providers(team_result: Any) -> Optional[List[str]]:
    """从 TeamResult 中提取使用的 provider:model 列表（可选）。"""
    try:
        providers: List[str] = []
        for member_res in (team_result.member_results or []):
            prov = getattr(member_res, "provider", None)
            mdl = getattr(member_res, "model", None)
            if prov or mdl:
                entry = f"{prov or ''}:{mdl or ''}".strip(":")
                if entry and entry not in providers:
                    providers.append(entry)
        return providers or None
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# 执行规划器
# ──────────────────────────────────────────────────────────────────────────────

# 任务复杂度阈值（决定 agent 策略）
_COMPLEXITY_KEYWORDS_HIGH = [
    "team", "swarm", "并行", "多个", "同时", "分别",
    "全部", "所有设备", "批量", "大量", "复杂",
]

# PR154: 自动 Agent 创建触发关键词（明确文档化，供测试验证）
# 当消息包含这些关键词时，ExecutionPlanner 会自动触发 Agent 创建。
# 这些关键词与 _COMPLEXITY_KEYWORDS_HIGH 配合使用：
#   - 关键词命中 → complexity >= 0.75 → strategy = "fractal"/"specialized"
#   - 无论策略如何，AgentFactory 始终被调用（单 Agent / Team / Swarm）
AUTO_AGENT_TRIGGER_KEYWORDS: tuple = (
    # 并行 / 多任务信号
    "team", "swarm", "并行", "多个", "同时", "分别",
    "全部", "所有设备", "批量", "大量",
    # 高复杂度信号
    "复杂",
    # 分形 / 多层递归信号
    "fractal", "分型", "递归", "分形", "多层", "深度拆解",
)

def _estimate_complexity(message: str) -> float:
    """粗略估算任务复杂度 0~1。"""
    m = message.lower()
    score = 0.3  # baseline
    score += min(len(message) / 500, 0.3)  # 消息越长越复杂
    if any(k in m for k in _COMPLEXITY_KEYWORDS_HIGH):
        score += 0.4
    return min(score, 1.0)


# ──────────────────────────────────────────────────────────────────────────────
# C阶段 3B: 任务类型 → 执行策略映射表
# ──────────────────────────────────────────────────────────────────────────────
#
# 格式: task_type_keyword → recommended_strategy
# 可用策略: "single" | "specialized" | "swarm" | "fractal"
#
# 与现有复杂度/关键词规则融合（优先级最高，不移除原逻辑）。
# _pick_strategy() 优先查此表，查不到则回退至原有复杂度规则。

TASK_TYPE_STRATEGY_MAP: Dict[str, str] = {
    # 单步快速任务 → 单 Agent
    "fast_response":  "single",
    "chat":           "single",
    "question":       "single",
    "translation":    "single",
    "summary":        "single",
    # 推理/规划 → Team 专项
    "reasoning":      "specialized",
    "planning":       "specialized",
    "analysis":       "specialized",
    # 编码 → 单 Agent（多数编码任务不需要多 Agent 协作）
    "coding":         "single",
    # 研究/信息聚合 → Team 并行
    "research":       "specialized",
    # 大量同类任务 → Swarm
    "swarm":          "swarm",
    "batch":          "swarm",
    # 复杂多层分解 → Fractal
    "fractal":        "fractal",
    "deep_planning":  "fractal",
    # 设备控制 → 单 Agent
    "device_control": "single",
    "agent_control":  "single",
}


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
        # C阶段 3B: 从意图中提取 task_type 传给策略选择器
        intent_task_type = getattr(plan.intent, "task_hint", "") or ""
        strategy = self._pick_strategy(plan.message, complexity, task_type=intent_task_type)

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

        # C阶段 4B: 注入最近任务记忆摘要（可选，默认 3 条）
        if _TASK_MEMORY_AVAILABLE:
            try:
                _mem = _get_task_memory()
                plan.context = _mem.inject_into_context(plan.context or [], n=3)
            except Exception as _mem_err:
                logger.debug("ExecutionPlanner: 任务记忆注入失败（跳过）: %s", _mem_err)

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
            # C阶段 5C: 填充 latency/token/cost 字段
            result.total_latency_ms = duration_ms
            try:
                from core.cost_tracker import get_cost_tracker
                _ct = get_cost_tracker()
                _recent = _ct.get_recent(10)
                # NOTE (C阶段 5C 简化): 取最后 1 条 cost 记录近似本次调用开销。
                # 在高并发场景可能与其他并发请求混淆；后续可通过 correlation_id 精确关联。
                if _recent:
                    _last = _recent[-1]
                    result.total_tokens = (
                        _last.get("input_tokens", 0) + _last.get("output_tokens", 0)
                    )
                    result.total_cost_usd = _last.get("estimated_cost_usd", 0.0)
            except Exception as _ct_err:
                logger.debug("ExecutionPlanner: 获取 cost 信息失败（跳过）: %s", _ct_err)
            # C阶段 4B: 记录任务摘要到长期记忆
            if _TASK_MEMORY_AVAILABLE:
                try:
                    _get_task_memory().record_task(
                        task=plan.message,
                        result_summary=(result.reply or "")[:200],
                        success=result.success,
                        strategy=result.chosen_strategy or strategy,
                        duration_ms=duration_ms,
                        session_id=plan.session_id,
                    )
                except Exception as _rec_err:
                    logger.debug("ExecutionPlanner: 任务记忆记录失败（跳过）: %s", _rec_err)
            return result

        except asyncio.TimeoutError:
            duration_ms = (time.monotonic() - t0) * 1000
            logger.error("ExecutionPlanner: 任务执行超时 (%.1fs)", plan.timeout)
            # C阶段 4B: 超时也记录到任务记忆
            if _TASK_MEMORY_AVAILABLE:
                try:
                    _get_task_memory().record_task(
                        task=plan.message,
                        result_summary="任务超时",
                        success=False,
                        strategy=strategy,
                        duration_ms=(time.monotonic() - t0) * 1000,
                        session_id=plan.session_id,
                    )
                except Exception:
                    pass
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

    def _pick_strategy(self, message: str, complexity: float, task_type: str = "") -> str:
        """选择执行策略：fractal / swarm / specialized / single。

        优先级（C阶段 3B 后）：
          0. 任务类型映射表（TASK_TYPE_STRATEGY_MAP）— 最高优先级
          1. Swarm   — 关键词明确请求高并发
          2. Fractal — 复杂度极高 (>= 0.75) 或关键词指示多层递归分解
          3. Specialized (Team) — 复杂度中高 (>= 0.65) 或关键词指示并行/团队
          4. Single  — 默认单 Agent

        约束（硬编码）:
          - Swarm 并发上限: 20
          - Fractal 最大递归深度: 3
        """
        # C阶段 3B: 优先查任务类型 → 策略映射表
        if task_type:
            mapped = TASK_TYPE_STRATEGY_MAP.get(task_type.lower())
            if mapped:
                logger.debug("_pick_strategy: task_type=%s → %s (via mapping table)", task_type, mapped)
                return mapped
        m = message.lower()
        if any(k in m for k in ["swarm", "群体", "大量", "批量", "高并发"]):
            return "swarm"
        if complexity >= 0.75 or any(k in m for k in [
            "fractal", "分型", "递归", "分形", "多层", "深度拆解",
        ]):
            return "fractal"
        if complexity >= 0.65 or any(k in m for k in [
            "team", "团队", "并行", "多个", "分工", "异构",
        ]):
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
        if strategy == "fractal":
            return await self._run_fractal(plan, steps, tool_calls)
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
        """通过 AgentFactory 创建单 Agent 执行任务。

        创建策略（LLM 优先）：
          1. LLM 动态生成 Agent（主路径）—— 模板蓝图作为 schema 约束
          2. 若 LLM 不可用/失败 → 根据关键词匹配选择模板（兜底）
          3. 若模板也失败 → coordinator 模板兜底

        同时为主控 Agent 自动创建数字孪生（默认 LOOSE 耦合模式）。
        """
        step = StepRecord(name="创建 Agent", tool="agent_factory")
        t0 = time.monotonic()

        try:
            from core.agent_factory import get_agent_factory
            factory = get_agent_factory(self._llm_router)

            # 构建带策略注入的任务描述
            task_with_policy = self._build_task_prompt(plan)

            # 自动选择最合适的 Agent 模板（作为蓝图约束，不是静态产物）
            selected_template = self._auto_select_template(plan.message, plan.intent)
            agent = None

            # ── LLM 优先：动态生成 Agent（主路径）──────────────────────────
            if self._llm_router is not None:
                try:
                    agent = await factory.create_from_llm(
                        task_description=task_with_policy,
                        context={
                            "session_id": plan.session_id,
                            "template_hint": selected_template,  # 蓝图约束
                        },
                        soul_policy=plan.soul_policy,  # SOUL 全局约束注入（B阶段）
                    )
                    logger.info(
                        "ExecutionPlanner: LLM 动态生成 Agent %s (蓝图参考: %s)",
                        agent.id,
                        selected_template,
                    )
                except Exception as llm_err:
                    logger.debug("LLM 动态生成 Agent 失败，回退到模板: %s", llm_err)
                    agent = None

            # ── 模板兜底：LLM 不可用或失败时使用 ─────────────────────────
            if agent is None:
                try:
                    agent = factory.create_from_template(selected_template)
                    logger.info(
                        "ExecutionPlanner: 模板兜底 '%s' → Agent %s",
                        selected_template, agent.id,
                    )
                except Exception as tmpl_err:
                    logger.warning("模板创建失败 (%s): %s，使用 coordinator 兜底", selected_template, tmpl_err)
                    selected_template = "coordinator"
                    agent = factory.create_from_template(selected_template)

            step.output = {
                "agent_id": agent.id,
                "agent_name": agent.config.name,
                "template": selected_template,
            }
            steps.append(step)

            # ── 创建数字孪生（默认 LOOSE 耦合）────────────────────────────
            twin_id: Optional[str] = None
            twin_coupling: Optional[str] = None
            try:
                from enhancements.agent_factory.twin_model import (
                    twin_manager as _tm, CouplingMode as _CM
                )
                if _tm is not None:
                    twin = _tm.create_twin(
                        source_id=agent.id,
                        name=f"twin_{agent.config.name}",
                        coupling_mode=_CM.LOOSE,
                    )
                    twin_id = twin.twin_id
                    twin_coupling = twin.coupling_mode.value
                    logger.info(
                        "ExecutionPlanner: 孪生 Agent 已创建 twin_id=%s coupling=%s",
                        twin_id, twin_coupling,
                    )
            except Exception as twin_err:
                logger.debug("孪生 Agent 创建失败（非致命）: %s", twin_err)

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

            # 收集使用的 provider 信息
            chosen_providers: Optional[List[str]] = None
            _prov = exec_result.get("provider")
            _mdl = exec_result.get("model")
            if _prov or _mdl:
                chosen_providers = [f"{_prov or ''}:{_mdl or ''}".strip(":")]

            return ExecutionResult(
                success=exec_result.get("success", True),
                mode="single_agent",
                reply=exec_result.get("reply") or exec_result.get("result") or "任务已完成",
                task_result=exec_result,
                model=exec_result.get("model", ""),
                auto_agent_id=agent.id,
                auto_agent_template=selected_template or None,
                chosen_strategy="single_agent",
                chosen_providers=chosen_providers,
                twin_id=twin_id,
                twin_coupling=twin_coupling,
                soul_enforced=bool(plan.soul_policy),
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

            # If the plan targets multiple devices, attempt task decomposition
            _plan_targets = getattr(plan, "device_id", None)
            if isinstance(_plan_targets, list) and len(_plan_targets) > 1:
                try:
                    decomposed = await _try_decompose_task(
                        plan.message, _plan_targets, {"session_id": plan.session_id}
                    )
                    logger.info(
                        "TaskDecomposer: decomposed into %d subtasks for %d targets",
                        len(decomposed), len(_plan_targets),
                    )
                except Exception as _dec_err:
                    logger.debug("TaskDecomposer decomposition skipped: %s", _dec_err)

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
                chosen_strategy=f"team_{team_strategy}",
                chosen_providers=_collect_team_providers(team_result),
                soul_enforced=bool(plan.soul_policy),
            )

        except Exception as exc:
            step.success = False
            step.error = str(exc)
            step.duration_ms = (time.monotonic() - t0) * 1000
            steps.append(step)
            raise

    # ──────────────────────────────────────────────────────────────────
    # Fractal 执行
    # ──────────────────────────────────────────────────────────────────

    async def _run_fractal(
        self,
        plan: ExecutionPlan,
        steps: List[StepRecord],
        tool_calls: List[ToolCallRecord],
    ) -> ExecutionResult:
        """通过 FractalExecutor 执行复杂递归任务。

        约束（硬编码）：
          - max_depth = 3
          - max_subtasks_total = 20
        """
        step = StepRecord(name="创建 Fractal Agent", tool="fractal_executor")
        t0 = time.monotonic()

        try:
            from core.fractal_agent import FractalExecutor, FractalTask, Complexity
            from core.agent_factory import get_agent_factory

            factory = get_agent_factory(self._llm_router)
            executor = FractalExecutor(
                llm_router=self._llm_router,
                agent_factory=factory,
                max_depth=3,          # 硬编码上限
                max_subtasks=20,      # 硬编码上限
            )

            step.output = {"strategy": "fractal", "max_depth": 3, "max_subtasks": 20}
            steps.append(step)

            exec_step = StepRecord(name="Fractal 执行", tool="fractal_execute")
            t1 = time.monotonic()
            context = {
                "soul": plan.soul_policy,
                "agents_policy": plan.agents_policy,
                "session_id": plan.session_id,
                "tools": plan.tool_schemas,
            }
            fractal_result = await executor.run(plan.message, context)
            exec_step.duration_ms = (time.monotonic() - t1) * 1000
            exec_step.success = fractal_result.success if hasattr(fractal_result, "success") else True
            exec_step.output = {
                "depth": getattr(fractal_result, "depth", 0),
                "decomposition_used": getattr(fractal_result, "decomposition_used", False),
            }
            steps.append(exec_step)

            output = getattr(fractal_result, "output", None) or "Fractal 任务已完成"
            step.duration_ms = (time.monotonic() - t0) * 1000
            return ExecutionResult(
                success=getattr(fractal_result, "success", True),
                mode="fractal",
                reply=str(output) if output else "Fractal 任务已完成",
                task_result={
                    "fractal_depth": getattr(fractal_result, "depth", 0),
                    "decomposition_used": getattr(fractal_result, "decomposition_used", False),
                },
                chosen_strategy="fractal",
                soul_enforced=bool(plan.soul_policy),
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
