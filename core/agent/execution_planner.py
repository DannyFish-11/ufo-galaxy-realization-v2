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
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from core import upper_ports
from core.agent.intent_router import IntentResult
from core.agent.multimodal_messages import MULTIMODAL_TASK_KEY

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
        TaskDecomposer = upper_ports.resolve("gateway.task_decomposer.TaskDecomposer")

        decomposer = TaskDecomposer(device_registry=None)
        # Use decompose_multi_device_command for multi-target tasks
        commands = [{"device_id": t, "action": "execute", "target": message} for t in targets]
        tasks, _data_flows = decomposer.decompose_multi_device_command(commands)
        if tasks:
            return [
                {"target": task.device_id, "message": getattr(task, "target", message) or message} for task in tasks
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

    multimodal_context: Optional[Any] = None
    """随消息带上来的图像负载（``core.schemas.multimodal.MultiModalContext``）。

    此前执行路径没有这个字段，「看这张截图帮我改掉这个设置」的截图在组装计划时就丢了。
    单 Agent 路径会把它拼成 OpenAI content 数组原生投喂（agent_factory._execute_single_task）。
    team / swarm / fractal 也消费本字段，但**只送到「成员第一次面对用户原始任务」的
    那些点**（各成员独立作答、子任务执行、critic 的执行者、流水线第一站、MoA 第一层、
    任务分解）；综合、聚合、复审、路由分类那几处读的是别的 agent 产出的文本，跟画面
    无关，附图只会把成本乘以层数。图像全程走独立形参，绝不进 ``context``（那里会被
    ``json.dumps``）。见 ``core.agent_team._seeing`` 与 ``core.fractal_agent._seeing``。
    """


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
    # PR-8v2: specialists-as-tools boundary metadata (advisory, non-authoritative)
    specialist_boundary: Optional[Dict[str, Any]] = None
    """Specialist layer boundary contract carried as execution metadata."""
    experience_guidance: Optional[Dict[str, Any]] = None
    """Whether past-task statistics moved this run's strategy, and on what evidence.

    Advisory metadata, same shape of contract as ``specialist_boundary``.  Without
    it, "why was this strategy chosen" is only answerable by reading logs — the
    exact kind of undiagnosable outcome the experience layer exists to remove."""
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
        for member_res in team_result.member_results or []:
            # MemberResult.provider/model 实际挂在 .member 上；两处都兼容读取
            _m = getattr(member_res, "member", None)
            prov = getattr(member_res, "provider", None) or getattr(_m, "provider", None)
            mdl = getattr(member_res, "model", None) or getattr(_m, "model", None)
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
    "team",
    "swarm",
    "并行",
    "多个",
    "同时",
    "分别",
    "全部",
    "所有设备",
    "批量",
    "大量",
    "复杂",
]

# PR154: 自动 Agent 创建触发关键词（明确文档化，供测试验证）
# 当消息包含这些关键词时，ExecutionPlanner 会自动触发 Agent 创建。
# 这些关键词与 _COMPLEXITY_KEYWORDS_HIGH 配合使用：
#   - 关键词命中 → complexity >= 0.75 → strategy = "fractal"/"specialized"
#   - 无论策略如何，AgentFactory 始终被调用（单 Agent / Team / Swarm）
AUTO_AGENT_TRIGGER_KEYWORDS: tuple = (
    # 并行 / 多任务信号
    "team",
    "swarm",
    "并行",
    "多个",
    "同时",
    "分别",
    "全部",
    "所有设备",
    "批量",
    "大量",
    # 高复杂度信号
    "复杂",
    # 分形 / 多层递归信号
    "fractal",
    "分型",
    "递归",
    "分形",
    "多层",
    "深度拆解",
)


# _pick_strategy() 的策略关键词。提成具名常量而非内联字面量:它们参与"这次选择是
# 显式还是隐式"的判定(见 _pick_strategy),内联时无法一眼看出判定依据是哪一组词。
_FRACTAL_KEYWORDS: tuple = ("fractal", "分型", "递归", "分形", "多层", "深度拆解")
_SPECIALIZED_KEYWORDS: tuple = ("team", "团队", "并行", "多个", "分工", "异构")


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
    "fast_response": "single",
    "chat": "single",
    "question": "single",
    "translation": "single",
    "summary": "single",
    # 推理/规划 → Team 专项
    "reasoning": "specialized",
    "planning": "specialized",
    "analysis": "specialized",
    # 编码 → 单 Agent（多数编码任务不需要多 Agent 协作）
    "coding": "single",
    # 研究/信息聚合 → Team 并行
    "research": "specialized",
    # 大量同类任务 → Swarm
    "swarm": "swarm",
    "batch": "swarm",
    # 复杂多层分解 → Fractal
    "fractal": "fractal",
    "deep_planning": "fractal",
    # 设备控制 → 单 Agent
    "device_control": "single",
    "agent_control": "single",
}

# PR-18: sentinel confirming activation budget is wired into ExecutionPlanner.
ACTIVATION_BUDGET_PLANNER_BREADTH_WIRED_PR18: str = (
    "ACTIVATION_BUDGET_PLANNER_BREADTH_WIRED_PR18: "
    "ExecutionPlanner.execute() accepts an optional activation_budget parameter "
    "(ActivationBudget from core.cognitive.cognitive_activation_budget).  "
    "When present and influenced_by_budget=True, _pick_strategy() applies "
    "PlannerBreadthGuidance to bias strategy selection based on cognitive posture.  "
    "Hard gates (governance, activation context) are unaffected."
)

# PR-19: sentinel confirming memory bias is wired into ExecutionPlanner.
MEMORY_BIAS_PLANNER_GUIDANCE_WIRED_PR19: str = (
    "MEMORY_BIAS_PLANNER_GUIDANCE_WIRED_PR19: "
    "ExecutionPlanner.execute() accepts an optional memory_bias parameter "
    "(MemoryBias from core.cognitive.memory_bias_layer).  "
    "When present and influenced_by_memory=True, _pick_strategy() applies "
    "MemoryPlannerGuidance to softly bias strategy selection based on "
    "continuity/retrieval/novelty posture.  Memory bias is the lowest-priority "
    "advisory influence; hard gates, task-type mapping, and explicit cognitive "
    "budget guidance all take precedence."
)

# Sentinel confirming experience statistics are object-anchored and advisory.
# Full rationale (and the defects of the superseded prose/regex path) lives in
# core.cognitive.experience_guidance — do not restate it here.
EXPERIENCE_GUIDANCE_OBJECT_ANCHORED_WIRED: str = (
    "EXPERIENCE_GUIDANCE_OBJECT_ANCHORED_WIRED: "
    "Strategy-success statistics come from "
    "core.cognitive.experience_guidance.derive_experience_guidance(), which "
    "aggregates typed TaskSummary fields over a BM25-scoped population. "
    "ExperienceGuidance is an input to _pick_strategy() alongside breadth and "
    "memory guidance — never a post-hoc override — and it never displaces "
    "task-type mapping, explicit keyword matches, budget preference, or memory "
    "continuity preference."
)


class ExecutionPlanner:
    """执行规划器（无状态，每次调用独立）。"""

    _DEFAULT_STRATEGY_NAME = "single"

    # PR86: 工具摘要中展示的最大工具数（避免 prompt 过长）
    _MAX_TOOL_SUMMARY_COUNT = 20
    # PR86: 能力注入标记（用于防止重复注入）
    _CAPABILITY_HINT_MARKER = "[CapabilityRegistry]"

    # Auto-agent template selection mapping: (keywords, template_name)
    # Type: List[Tuple[List[str], str]]
    _TEMPLATE_MAP: List[tuple] = [
        (
            [
                "设备",
                "控制",
                "device",
                "hardware",
                "phone",
                "手机",
                "电脑",
                "平板",
                "screenshot",
                "截图",
                "截屏",
                "click",
                "点击",
                "swipe",
                "滑动",
            ],
            "device_controller",
        ),
        (
            [
                "代码",
                "编程",
                "code",
                "script",
                "program",
                "写代码",
                "写脚本",
                "python",
                "javascript",
                "java",
                "function",
                "函数",
                "调试",
            ],
            "code_executor",
        ),
        (
            [
                "分析",
                "数据",
                "统计",
                "analyze",
                "analyse",
                "data",
                "stat",
                "报告",
                "report",
                "insight",
                "chart",
                "图表",
            ],
            "data_analyst",
        ),
        (["搜索", "调研", "research", "search", "查找", "find", "信息", "news", "latest", "最新"], "research"),
        (["计划", "规划", "plan", "strategy", "策略", "步骤", "steps", "schedule", "路线图", "roadmap"], "planner"),
        (["协调", "team", "并行", "parallel", "分工", "多个", "组织"], "coordinator"),
    ]

    def __init__(self, llm_router: Optional[Any] = None) -> None:
        self._llm_router = llm_router

    def _build_specialist_boundary(
        self,
        strategy: str,
        *,
        device_id: Optional[Union[str, List[str]]] = None,
    ) -> Dict[str, Any]:
        """Build PR-8v2 specialist-layer boundary metadata for runtime consumers.

        Args:
            strategy: Strategy label produced by planner/executor
                (for example ``single_agent``, ``team_specialized``, ``swarm``,
                ``fractal``).
            device_id: Optional device targeting descriptor from the execution
                plan. ``None`` and non-list values are treated as non-multi-device.
                A list with more than one device marks multi-device targeting.

        Returns:
            Dict containing specialist-layer boundary metadata, including:
            - specialist_layer_role
            - specialist_authority_class
            - strategy_class
            - planner_kernel_team_authority
            - direct_side_effect_authority
            - android_runtime_alignment
        """
        normalized_strategy = (strategy or self._DEFAULT_STRATEGY_NAME).lower()
        strategy_class = {
            "single": self._DEFAULT_STRATEGY_NAME,
            "single_agent": self._DEFAULT_STRATEGY_NAME,
            "specialized": "specialized",
            "parallel": "specialized",
            "team_specialized": "specialized",
            "swarm": "swarm",
            "team_swarm": "swarm",
            "fractal": "fractal",
        }.get(normalized_strategy, self._DEFAULT_STRATEGY_NAME)

        # A single explicit target (str or one-element list) is treated as
        # non-multi-device.  We only mark multi-device when >1 targets exist.
        multi_device = isinstance(device_id, list) and len(device_id) > 1
        return {
            "specialist_layer_role": "specialists_as_tools",
            "specialist_authority_class": "experts_as_subordinate_capabilities",
            "strategy_class": strategy_class,
            "planner_kernel_team_authority": "advisory_subordinate_only",
            "direct_side_effect_authority": "openclawd_mainline_only",
            "android_runtime_alignment": {
                "runtime_host_role": "first_class_runtime_host",
                "transport_binding": "GalaxyConnectionService/GalaxyWebSocketClient",
                "cross_device_entry": "DeviceRouter",
                "multi_device_targeting": multi_device,
            },
        }

    @staticmethod
    def _resolve_boundary_strategy(
        chosen_strategy: Optional[str],
        mode: Optional[str],
        fallback_strategy: str,
    ) -> str:
        """Resolve strategy used for specialist-boundary classification.

        Priority order:
        1. ``chosen_strategy`` (most specific runtime strategy output)
        2. ``mode`` (execution mode surface when chosen strategy is unavailable)
        3. ``fallback_strategy`` (planner-selected strategy fallback)
        """
        if chosen_strategy is not None:
            return chosen_strategy
        if mode is not None:
            return mode
        return fallback_strategy

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

    async def execute(
        self, plan: ExecutionPlan, *, activation_budget: Optional[Any] = None, memory_bias: Optional[Any] = None
    ) -> ExecutionResult:
        """
        执行计划入口。（PR86）

        约束：
        - 执行前必须从 CapabilityRegistry 刷新并拉取可用工具列表
        - 不允许绕过 CapabilityRegistry 直接硬编码工具调用
        - 执行策略选择：
            - 低复杂度任务 → 单 Agent
            - 高复杂度任务 → Team (SPECIALIZED) 或 Swarm
            - 涉及多设备 → Team + Gateway

        Args:
            plan:               The execution plan.
            activation_budget:  PR-18 — optional ActivationBudget from
                                core.cognitive.cognitive_activation_budget.
                                When provided, planner breadth guidance is
                                derived and used to bias strategy selection.
                                Hard governance gates are unaffected.
            memory_bias:        PR-19 — optional MemoryBias from
                                core.cognitive.memory_bias_layer.
                                When provided, memory planner guidance is
                                derived and used to softly bias strategy
                                selection (lowest-priority advisory influence).
                                Hard gates and activation-budget guidance take
                                precedence; memory bias cannot override them.
        """
        t0 = time.monotonic()
        steps: List[StepRecord] = []
        tool_calls: List[ToolCallRecord] = []

        complexity = _estimate_complexity(plan.message)
        # C阶段 3B: 从意图中提取 task_type 传给策略选择器
        intent_task_type = getattr(plan.intent, "task_hint", "") or ""

        # PR-18: derive planner breadth guidance from activation budget (advisory only)
        _breadth_guidance = None
        _budget_influenced_strategy = False
        try:
            if activation_budget is not None and getattr(activation_budget, "influenced_by_budget", False):
                from core.cognitive.cognitive_activation_budget import get_planner_breadth_guidance as _get_breadth

                _breadth_guidance = _get_breadth(activation_budget)
                logger.debug(
                    "PR-18 ExecutionPlanner: breadth_guidance=%s max_agents=%d adj=%.2f",
                    _breadth_guidance.breadth_mode,
                    _breadth_guidance.max_concurrent_agents,
                    _breadth_guidance.complexity_threshold_adjustment,
                )
        except Exception as _budget_guidance_err:
            logger.debug(
                "PR-18 ExecutionPlanner: breadth_guidance derivation skipped — %s",
                _budget_guidance_err,
            )

        # PR-19: derive memory planner guidance from memory bias (lowest-priority advisory)
        _memory_guidance = None
        _memory_influenced_strategy = False
        _experience_guidance = None
        _experience_influenced_strategy = False
        try:
            if memory_bias is not None and getattr(memory_bias, "influenced_by_memory", False):
                from core.cognitive.memory_bias_layer import get_memory_planner_guidance as _get_mem_guidance

                _memory_guidance = _get_mem_guidance(memory_bias)
                logger.debug(
                    "PR-19 ExecutionPlanner: memory_guidance posture=%s decomp=%s prefer_single=%s adj=%.2f",
                    _memory_guidance.posture,
                    _memory_guidance.decomposition_hint,
                    _memory_guidance.prefer_single_agent,
                    _memory_guidance.complexity_threshold_adjustment,
                )
        except Exception as _mem_guidance_err:
            logger.debug(
                "PR-19 ExecutionPlanner: memory_guidance derivation skipped — %s",
                _mem_guidance_err,
            )

        strategy = self._pick_strategy(
            plan.message,
            complexity,
            task_type=intent_task_type,
            breadth_guidance=_breadth_guidance,
            memory_guidance=_memory_guidance,
        )
        if _breadth_guidance is not None and _breadth_guidance.influenced_by_budget:
            _budget_influenced_strategy = True
        if _memory_guidance is not None and _memory_guidance.influenced_by_memory:
            _memory_influenced_strategy = True

        # 经验制导需要"当前策略"作对比基准,故在首次选择之后派生,再用同一个纯函数
        # 重跑一次选择——_pick_strategy 是微秒级纯逻辑,重跑无代价,且保证应用规则只有
        # 一处实现。派生内部是 BM25(同步 CPU),async 里必须 offload,否则占住事件循环。
        _experience_guidance = await asyncio.to_thread(
            self._derive_experience_guidance, plan.message, strategy, intent_task_type
        )
        if _experience_guidance is not None:
            strategy = self._pick_strategy(
                plan.message,
                complexity,
                task_type=intent_task_type,
                breadth_guidance=_breadth_guidance,
                memory_guidance=_memory_guidance,
                experience_guidance=_experience_guidance,
            )
            if getattr(_experience_guidance, "influenced_by_experience", False):
                _experience_influenced_strategy = True

        # 协作模式细化(Octo 六模式)：当本就要组队(specialized/parallel/swarm)时，
        # 用 collaboration_mode_policy 进一步判断是否该用 critic(做/审分离) / pipeline
        # (流水线) 等更合适的模式。single / fractal 不动（前者无需组队，后者递归分解）。
        if strategy in ("specialized", "parallel", "swarm"):
            try:
                from core.collaboration_mode_policy import select_collaboration_mode

                _collab = select_collaboration_mode(
                    plan.message,
                    complexity_score=complexity,
                    intent=plan.intent,
                )
                if _collab["mode"] != strategy:
                    logger.info(
                        "协作模式细化: %s → %s (%s)",
                        strategy,
                        _collab["mode"],
                        _collab["reason"],
                    )
                    strategy = _collab["mode"]
            except Exception as _collab_err:
                logger.debug("协作模式细化跳过(非致命): %s", _collab_err)

        logger.info(
            "ExecutionPlanner: 开始执行 | strategy=%s complexity=%.2f intent=%s "
            "budget_influenced=%s memory_influenced=%s experience_influenced=%s",
            strategy,
            complexity,
            plan.intent.mode,
            _budget_influenced_strategy,
            _memory_influenced_strategy,
            _experience_influenced_strategy,
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
                "ExecutionPlanner: CapabilityRegistry 已刷新 | " "total=%d available=%d (mcp=%d skill=%d gateway=%d)",
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
            tool_summary = ", ".join(t.name for t in available_tools[: self._MAX_TOOL_SUMMARY_COUNT])
            if available_tools:
                plan.context = plan.context or []
                # 在上下文中注入工具列表提示（不覆盖已有对话历史）
                _tool_hint = {
                    "role": "system",
                    "content": f"{self._CAPABILITY_HINT_MARKER} 可用工具: {tool_summary}"
                    + (
                        f"... 共 {len(available_tools)} 项"
                        if len(available_tools) > self._MAX_TOOL_SUMMARY_COUNT
                        else ""
                    ),
                }
                # 只在没有同类 hint 时才插入
                if not any(self._CAPABILITY_HINT_MARKER in c.get("content", "") for c in plan.context):
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

        # 经验复用（READ）：从统一记忆层语义召回与本任务相关的历史经验，注入上下文。
        # 与 ReAct 反思形成闭环：做→反思→沉淀(见下方 WRITE)→下次规划时召回。失败即跳过。
        try:
            import asyncio as _aio

            from core.memory import get_unified_memory

            _um = get_unified_memory()
            if _um.enabled and plan.message:
                # _um.recall 对 Chroma 后端要先把 query 编码成向量(CPU 密集的同步
                # 调用);execute() 是 async 方法,直接调用会占住共享事件循环——
                # offload 到线程。
                _exp_hits = await _aio.to_thread(_um.recall, plan.message, top_k=3)
                _exp_lines = [
                    f"- {h.content[:240]}"
                    for h in _exp_hits
                    if h.content and "experience" in (h.metadata.get("tags") or [])
                ]
                if _exp_lines:
                    plan.context = (plan.context or []) + [
                        {
                            "role": "system",
                            "content": "[相关历史经验 — 供参考，避免重蹈覆辙]\n" + "\n".join(_exp_lines),
                        }
                    ]
        except Exception as _exp_err:  # noqa: BLE001
            logger.debug("ExecutionPlanner: 经验召回跳过: %s", _exp_err)

        try:
            # ── 外层重规划（有界、可关、按结果触发）────────────────────────
            # 单 Agent 内部已有 ReAct 闭环；这里是 strategy 层的重规划：当一次
            # dispatch 以 success=False 软失败返回时，退到最稳妥的 single 路径并把
            # 失败原因回灌上下文重试。默认最多 1 次；GALAXY_PLANNER_MAX_REPLANS 调整。
            import os as _os

            try:
                _max_replans = max(0, int(_os.getenv("GALAXY_PLANNER_MAX_REPLANS", "1")))
            except ValueError:
                _max_replans = 1
            _replans = 0
            while True:
                result = await asyncio.wait_for(
                    self._dispatch(plan, strategy, steps, tool_calls),
                    timeout=plan.timeout,
                )
                if result.success or _replans >= _max_replans:
                    break
                _replans += 1
                _prev_strategy = strategy
                strategy = "single"  # 重规划：退到最稳妥的单 Agent 路径
                logger.info(
                    "ExecutionPlanner: 重规划 #%d | prev_strategy=%s → single | reason=%s",
                    _replans,
                    _prev_strategy,
                    (result.error or result.reply or "")[:120],
                )
                # 失败原因回灌上下文，供下一次执行参考
                plan.context = (plan.context or []) + [
                    {
                        "role": "system",
                        "content": (
                            f"[重规划] 上一次以「{_prev_strategy}」执行未成功："
                            f"{(result.error or result.reply or '')[:200]}。"
                            "请用更稳妥的方式重试并修正问题。"
                        ),
                    }
                ]
            duration_ms = (time.monotonic() - t0) * 1000
            if _replans:
                result.task_result = result.task_result or {}
                result.task_result["replans"] = _replans
            result.agent_steps = steps
            result.tool_calls = tool_calls
            result.duration_ms = duration_ms
            _strategy_for_boundary = self._resolve_boundary_strategy(
                result.chosen_strategy,
                result.mode,
                strategy,
            )
            if result.specialist_boundary is None:
                result.specialist_boundary = self._build_specialist_boundary(
                    _strategy_for_boundary,
                    device_id=plan.device_id,
                )
            # 经验制导的可观测性:这一次到底有没有被历史统计影响、依据是什么。
            # 不落到结果上,"策略为什么是这个"就只能靠翻日志猜——而"结论不可追到
            # 依据"正是本层要消除的那类缺陷,在自己身上留着说不过去。
            try:
                from core.cognitive.experience_guidance import build_experience_guidance_diagnostics

                result.experience_guidance = build_experience_guidance_diagnostics(
                    _experience_guidance,
                    applied=_experience_influenced_strategy,
                )
            except Exception as _exp_diag_err:  # noqa: BLE001 — 诊断绝不影响执行
                logger.debug("experience guidance diagnostics skipped: %s", _exp_diag_err)
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
                    result.total_tokens = _last.get("input_tokens", 0) + _last.get("output_tokens", 0)
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

            # 经验复用（WRITE）：把本次执行沉淀成一条"经验"写入统一记忆层，
            # 供未来语义召回（见上方 READ）。tags 含 "experience" 以便召回时筛选。
            # 这条散文**只**服务于上方 READ 的 prompt 上下文注入(供 LLM 参考的建议性
            # 文本,向量检索的正当用法)。策略选择不再读它,改读 TaskSummary 的类型化字段;
            # 结构化事实由上方 record_task() 落库,勿再从本文本反解结构。
            try:
                from core.memory import get_unified_memory

                _um_w = get_unified_memory()
                if _um_w.enabled and plan.message:
                    _outcome = "成功" if result.success else "失败"
                    _lesson = (result.reply or result.error or "")[:200]
                    _exp_text = (
                        f"经验: 任务[{plan.message[:160]}] 策略[{result.chosen_strategy or strategy}] "
                        f"结果[{_outcome}] 要点[{_lesson}]"
                    )
                    _um_w.remember(
                        _exp_text,
                        modality="text",
                        tags=["experience", "success" if result.success else "failure"],
                        metadata={"session_id": plan.session_id, "kind": "experience"},
                    )
            except Exception as _exp_w_err:  # noqa: BLE001
                logger.debug("ExecutionPlanner: 经验写入跳过: %s", _exp_w_err)
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
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
            return ExecutionResult(
                success=False,
                mode=strategy,
                reply=f"任务执行超时（超过 {plan.timeout:.0f}s），请简化任务或稍后重试。",
                agent_steps=steps,
                tool_calls=tool_calls,
                error="timeout",
                duration_ms=duration_ms,
                specialist_boundary=self._build_specialist_boundary(
                    strategy,
                    device_id=plan.device_id,
                ),
            )
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
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
                specialist_boundary=self._build_specialist_boundary(
                    strategy,
                    device_id=plan.device_id,
                ),
            )

    # ──────────────────────────────────────────────────────────────────
    # 策略选择
    # ──────────────────────────────────────────────────────────────────

    def _derive_experience_guidance(self, message: str, current: str, task_type: str = "") -> Optional[Any]:
        """从历史执行记录派生"策略→成败"制导（取代 ``_experience_strategy_adjust``）。

        读 :class:`core.task_memory.TaskSummary` 的类型化字段，作用域由 BM25 提供，
        无正则、无 embedding；产出的制导是 ``_pick_strategy()`` 的建议输入，
        与 PR-18/PR-19 同级。理由与旧实现的缺陷见
        :mod:`core.cognitive.experience_guidance`。

        同步 CPU 调用（BM25 排序），async 调用方需 offload —— 见 ``execute()``。
        返回 ``None`` 表示派生不可用，调用方按无制导处理。
        """
        try:
            from core.cognitive.experience_guidance import derive_experience_guidance

            return derive_experience_guidance(message, current, task_type=task_type)
        except Exception as exc:  # noqa: BLE001 — 经验制导失败不影响主流程
            logger.debug("experience guidance derivation skipped: %s", exc)
            return None

    def _pick_strategy(
        self,
        message: str,
        complexity: float,
        task_type: str = "",
        breadth_guidance: Optional[Any] = None,
        memory_guidance: Optional[Any] = None,
        experience_guidance: Optional[Any] = None,
    ) -> str:
        """选择执行策略：fractal / swarm / specialized / single。

        优先级（C阶段 3B + PR-18 + PR-19 后）：
          0. 任务类型映射表（TASK_TYPE_STRATEGY_MAP）— 最高优先级
          1. Swarm   — 关键词明确请求高并发
          2. Fractal — 复杂度极高 (>= 0.75) 或关键词指示多层递归分解
          3. Specialized (Team) — 复杂度中高 (>= 0.65) 或关键词指示并行/团队
          4. Single  — 默认单 Agent

        PR-18 activation budget influence (advisory, second-lowest priority):
          - narrow  (passive):   strategy_preference="single"; raises complexity
                                 thresholds to prefer simpler strategies.
          - moderate (liminal):  no strategy preference; no threshold adjustment.
          - broad   (manifest):  no strategy preference; lowers complexity
                                 thresholds slightly (more strategies eligible).

        PR-19 memory bias influence (advisory, lowest priority):
          - continuity posture:  prefer single-agent to maintain context coherence;
                                 raises complexity thresholds slightly (+0.10).
          - retrieval posture:   no strategy preference; no threshold change.
          - novelty posture:     no influence on strategy selection.
          Memory guidance is only applied after PR-18 budget guidance; it never
          overrides task-type mapping, keyword matches, or budget narrowing.

        Experience guidance influence (advisory, lowest priority — tied with PR-19):
          Applied ONLY when the strategy was reached *implicitly* (complexity
          threshold or default fallback); it never displaces one an explicit
          signal produced — task-type mapping, keyword match, budget preference,
          memory continuity.  Keeps memory-derived statistics subordinate per
          MEMORY_BIAS_LAYER::POLICY_4.  See core.cognitive.experience_guidance.

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

        # PR-18: apply complexity threshold adjustment from breadth guidance
        adj = 0.0
        _strategy_pref = None
        if breadth_guidance is not None and getattr(breadth_guidance, "influenced_by_budget", False):
            adj = float(getattr(breadth_guidance, "complexity_threshold_adjustment", 0.0))
            _strategy_pref = getattr(breadth_guidance, "strategy_preference", None)
            if adj != 0.0 or _strategy_pref:
                logger.debug(
                    "PR-18 _pick_strategy: breadth=%s adj=%.2f strategy_pref=%s",
                    getattr(breadth_guidance, "breadth_mode", "?"),
                    adj,
                    _strategy_pref,
                )

        # PR-19: apply memory guidance (lowest priority — only when no PR-18 override)
        _mem_adj = 0.0
        _mem_prefer_single = False
        if (
            memory_guidance is not None
            and getattr(memory_guidance, "influenced_by_memory", False)
            # Memory guidance complexity adjustment is only applied when PR-18
            # breadth guidance has not already set a strategy preference.
            and _strategy_pref is None
        ):
            _mem_adj = float(getattr(memory_guidance, "complexity_threshold_adjustment", 0.0))
            _mem_prefer_single = bool(getattr(memory_guidance, "prefer_single_agent", False))
            if _mem_adj != 0.0 or _mem_prefer_single:
                logger.debug(
                    "PR-19 _pick_strategy: memory posture=%s adj=%.2f prefer_single=%s",
                    getattr(memory_guidance, "posture", "?"),
                    _mem_adj,
                    _mem_prefer_single,
                )

        # Combine adjustments (PR-18 takes precedence; PR-19 is additive when PR-18 is neutral)
        total_adj = adj + (_mem_adj if adj == 0.0 else 0.0)

        fractal_threshold = 0.75 + total_adj
        specialized_threshold = 0.65 + total_adj

        _fractal_kw = any(k in m for k in _FRACTAL_KEYWORDS)
        _specialized_kw = any(k in m for k in _SPECIALIZED_KEYWORDS)

        # Decide the strategy AND record whether an *explicit* signal produced it.
        # Outcomes are identical to the previous cascade (`complexity >= threshold
        # or keyword` → strategy); the split exists only so experience guidance can
        # tell "a keyword said so" apart from "the score happened to land here".
        if complexity >= fractal_threshold:
            # A keyword pointing the same way makes it explicit, not merely inferred.
            base, explicit = "fractal", _fractal_kw
        elif _fractal_kw:
            base, explicit = "fractal", True
        elif complexity >= specialized_threshold:
            base, explicit = "specialized", _specialized_kw
        elif _specialized_kw:
            base, explicit = "specialized", True
        elif _strategy_pref == "single":
            # PR-18: if budget is narrow (passive), prefer single even if near threshold
            logger.debug("PR-18 _pick_strategy: passive posture — returning 'single' per budget guidance")
            base, explicit = "single", True
        elif _mem_prefer_single:
            # PR-19: if memory posture is continuity-seeking, prefer single for coherence
            logger.debug("PR-19 _pick_strategy: continuity posture — returning 'single' per memory guidance")
            base, explicit = "single", True
        else:
            base, explicit = "single", False

        # Experience guidance — lowest priority, and only over an implicit choice.
        if (
            not explicit
            and experience_guidance is not None
            and getattr(experience_guidance, "influenced_by_experience", False)
        ):
            candidate = getattr(experience_guidance, "candidate_strategy", "") or ""
            if candidate and candidate != base:
                logger.info(
                    "_pick_strategy: experience guidance %s → %s (%s)",
                    base,
                    candidate,
                    getattr(experience_guidance, "diagnostic_note", ""),
                )
                return candidate

        return base

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
        # ── Phase B（灰度，默认关闭）：统一 Workflow 层接入 ──
        # 开关 GALAXY_UNIFIED_WORKFLOW=1 时，经 core.agentic 的统一 forward(session)->session
        # 层运行该策略；任何异常都回退到下面的 legacy 路径。默认关闭 → 零默认行为变化。
        if os.environ.get("GALAXY_UNIFIED_WORKFLOW", "").strip().lower() in ("1", "true", "yes", "on"):
            try:
                from core.agentic.strategy import run_strategy_workflow

                _wf = await run_strategy_workflow(
                    message=plan.message,
                    strategy=strategy,
                    session_id=plan.session_id,
                    device_id=plan.device_id,
                    llm_router=self._llm_router,
                )
                return ExecutionResult(
                    success=bool(_wf.get("success", True)),
                    reply=_wf.get("reply", ""),
                    task_result=_wf.get("task_result"),
                    chosen_strategy=_wf.get("chosen_strategy", strategy),
                    agent_steps=steps,
                    tool_calls=tool_calls,
                )
            except Exception as _wf_exc:  # noqa: BLE001 —— 实验路径失败即回退 legacy
                logger.warning("统一 Workflow 路径失败，回退 legacy 执行: %s", _wf_exc)

        if strategy == "fractal":
            return await self._run_fractal(plan, steps, tool_calls)
        if strategy in ("specialized", "parallel", "swarm", "critic", "pipeline"):
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
                        selected_template,
                        agent.id,
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
                _CM = upper_ports.resolve("enhancements.agent_factory.twin_model.CouplingMode")
                _tm = upper_ports.resolve("enhancements.agent_factory.twin_model.twin_manager")

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
                        twin_id,
                        twin_coupling,
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
            # 单独的键：task_dict 会被 json.dumps 成 user 消息，base64 进 JSON 只烧 token，
            # 没有模型会把它当图看。消费端摘出来改走 content 数组。
            if plan.multimodal_context is not None:
                task_dict[MULTIMODAL_TASK_KEY] = plan.multimodal_context
            exec_result = await factory.execute_agent_task(agent.id, task_dict)
            exec_step.duration_ms = (time.monotonic() - t1) * 1000
            exec_step.success = exec_result.get("success", True)
            exec_step.output = exec_result
            steps.append(exec_step)

            # 收集工具调用记录
            for tc in exec_result.get("tool_calls", []):
                tool_calls.append(
                    ToolCallRecord(
                        tool=tc.get("tool", ""),
                        arguments=tc.get("arguments", {}),
                        result=tc.get("result", {}),
                        success=tc.get("success", True),
                        error=tc.get("error", ""),
                    )
                )

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
            logger.debug("Fallback triggered: %s", exc)
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
            from core.agent_factory import get_agent_factory
            from core.agent_team import TeamManager

            factory = get_agent_factory(self._llm_router)
            manager = TeamManager(
                agent_factory=factory,
                llm_router=self._llm_router,
            )

            # If the plan targets multiple devices, attempt task decomposition
            _plan_targets = getattr(plan, "device_id", None)
            if isinstance(_plan_targets, list) and len(_plan_targets) > 1:
                try:
                    decomposed = await _try_decompose_task(plan.message, _plan_targets, {"session_id": plan.session_id})
                    logger.info(
                        "TaskDecomposer: decomposed into %d subtasks for %d targets",
                        len(decomposed),
                        len(_plan_targets),
                    )
                except Exception as _dec_err:
                    logger.debug("TaskDecomposer decomposition skipped: %s", _dec_err)

            # Map strategy: swarm/parallel/specialized + critic(做审分离)/pipeline(流水线)
            team_strategy = (
                strategy if strategy in ("swarm", "parallel", "specialized", "critic", "pipeline") else "specialized"
            )
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
            # 图像走独立形参,不进 context —— context 在 _execute_parallel / MoA 第 1 层
            # 会被 json.dumps,MultiModalContext 是 pydantic 对象,塞进去当场抛 TypeError。
            team_result = await manager.execute_team(
                team.team_id,
                plan.message,
                context,
                multimodal_context=plan.multimodal_context,
            )
            exec_step.duration_ms = (time.monotonic() - t1) * 1000
            exec_step.success = team_result.success
            exec_step.output = team_result.to_dict()
            steps.append(exec_step)

            # 收集 member 结果中的工具调用（MemberResult 不一定带 tool_calls，安全读取）
            for member_res in team_result.member_results or []:
                for tc in getattr(member_res, "tool_calls", None) or []:
                    tool_calls.append(
                        ToolCallRecord(
                            tool=tc if isinstance(tc, str) else tc.get("tool", ""),
                            result={},
                        )
                    )

            step.duration_ms = (time.monotonic() - t0) * 1000
            return ExecutionResult(
                success=team_result.success,
                mode=f"team_{team_strategy}",
                # TeamResult 的最终产出字段是 synthesized（兼容旧 final_answer 命名）
                reply=getattr(team_result, "synthesized", None)
                or getattr(team_result, "final_answer", None)
                or "Team 任务已完成",
                task_result=team_result.to_dict(),
                chosen_strategy=f"team_{team_strategy}",
                chosen_providers=_collect_team_providers(team_result),
                soul_enforced=bool(plan.soul_policy),
            )

        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
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
            from core.agent_factory import get_agent_factory
            from core.fractal_agent import FractalExecutor

            factory = get_agent_factory(self._llm_router)
            executor = FractalExecutor(
                llm_router=self._llm_router,
                agent_factory=factory,
                max_depth=3,  # 硬编码上限
                max_subtasks=20,  # 硬编码上限
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
            fractal_result = await executor.run(
                plan.message,
                context,
                multimodal_context=plan.multimodal_context,
            )
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
            logger.debug("Fallback triggered: %s", exc)
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
