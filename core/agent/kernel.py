"""
core/agent/kernel.py
======================
AgentKernel — OpenClawd 的内嵌认知/规划层

架构位置：
  DesktopPresenceRuntime   ← 运行时外壳 / 最外层主权
    └─ OpenClawd           ← 主体决策核心 / subject core
         └─ AgentKernel    ← 内嵌认知/规划层（本模块）

AgentKernel **不是**独立的顶级主权，**不是**传输/运行时基底，
**不是**多设备编排主体。它只为 OpenClawd 提供认知与规划支持，
并将结构化的认知产物（KernelResponse）返回给 OpenClawd 解释和执行。

完整流程：
  1. 接收自然语言请求（由 OpenClawd 调用，非外部直接入口）
  2. 注入 USER / AGENTS 策略（通用）
  3. 调用 IntentRouter 判定 chat_only / task_execute / hybrid
  4. 若需执行（task_execute 或 hybrid 执行阶段）：
       → 注入 SOUL 策略（仅此时）
       → 调用 ExecutionPlanner → AgentFactory / Team / Swarm
  5. 若纯聊天（chat_only）：
       → 直接走 LLM 对话，不加载 SOUL
  6. 统一返回 KernelResponse（Pydantic 认知产物）
       → OpenClawd 负责解释 KernelResponse 并决定后续行动

关键约束：
  - SOUL.md 仅在 task_execute / hybrid 执行阶段由本模块注入
  - 纯聊天路径完全不接触 SOUL
  - 任何异常均有超时/降级处理，不中断服务
  - AgentKernel 不主动调用 OpenClawd（避免循环依赖与角色模糊）
  - KernelResponse 是认知/规划产物，由 OpenClawd 拥有解释权
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.agent.intent_router import IntentMode, IntentResult, IntentRouter
from core.agent.policy_loader import get_agents, get_soul, get_user
from core.agent.execution_planner import (
    ExecutionPlan,
    ExecutionPlanner,
    ExecutionResult,
    StepRecord,
    ToolCallRecord,
)

logger = logging.getLogger("Galaxy.Agent.Kernel")

# ──────────────────────────────────────────────────────────────────────────────
# PR-507: Canonical task front-loading sentinel
# ──────────────────────────────────────────────────────────────────────────────

# Affirms that AgentKernel._process() now calls adapt_to_canonical_task() in
# the execution path (task_execute / hybrid) so that CanonicalTask is the
# primary ontology object before ExecutionPlan is assembled.
CANONICAL_TASK_KERNEL_FRONT_LOADED: str = (
    "CANONICAL_TASK_KERNEL_V1: core/agent/kernel.py AgentKernel._process() "
    "calls adapt_to_canonical_task() in task_execute/hybrid path before "
    "ExecutionPlan so CanonicalTask is always the primary ontology object."
)

# PR-513 / GAP-512-007: AgentKernel now emits audit_task_admitted after
# CanonicalTask front-load so task admission is visible in the audit trail.
AGENT_KERNEL_AUDIT_ADMITTED_INTEGRATED: str = (
    "AGENT_KERNEL_AUDIT_ADMITTED_V1: core/agent/kernel.py AgentKernel._process() "
    "emits AuditEventSemantics.audit_task_admitted after CanonicalTask "
    "front-load in task_execute/hybrid path (GAP-512-007)."
)

# ──────────────────────────────────────────────────────────────────────────────
# 响应模型
# ──────────────────────────────────────────────────────────────────────────────


class KernelResponse(BaseModel):
    """OpenClawd 内嵌 AgentKernel 的认知/规划产物。

    KernelResponse 是认知层的输出契约：它携带 AgentKernel 完成认知与规划后
    产生的结构化结果，供 OpenClawd（且只有 OpenClawd）解释并决定后续执行/委托。

    字段分为四类：
      - 规划/认知输出：mode, intent, agent_steps, tool_calls, task_result
      - 委托建议：delegation_hint（OpenClawd 自行决定是否采纳，advisory only）
      - SOUL 注入审计：soul_injection_phase（仅在 task_execute/hybrid 时非 None）
      - 权威边界元数据：authority_role, routing_authority, arch_layer_id
      - 通用元数据：model, session_id, error, latency_ms

    PR-006 contract clarifications:
      - ``delegation_hint`` is strictly advisory: OpenClawd is the sole decision
        authority and may ignore or override this field.
      - ``soul_injection_phase`` is None for chat_only paths; set to the intent
        mode string ("task_execute" or "hybrid") when SOUL was injected.
      - ``routing_authority`` is always "advisory_to_openclawd" to make explicit
        that any routing suggestion from AgentKernel is advisory only — OpenClawd
        (or its routing module) owns final multi-model routing authority.
    """

    success: bool = True
    mode: str = IntentMode.CHAT_ONLY
    """处理模式: chat_only / task_execute / hybrid"""

    reply: str = ""
    """主要回复文本"""

    agent_steps: List[StepRecord] = Field(default_factory=list)
    """Agent 执行步骤（执行模式下填充）"""

    tool_calls: List[ToolCallRecord] = Field(default_factory=list)
    """工具调用记录（执行模式下填充）"""

    task_result: Optional[Dict[str, Any]] = None
    """任务完整结果（可选）"""

    intent: IntentResult = Field(default_factory=IntentResult)
    """意图路由结果"""

    delegation_hint: Optional[str] = None
    """委托建议（认知产物字段，advisory only）。

    AgentKernel 可在此字段提示 OpenClawd 适合的委托路径，
    例如 "local"、"single_remote"、"multi_device"。
    OpenClawd 拥有最终委托决策权，此字段仅作建议参考，OpenClawd 可自行决定忽略。

    PR-006: This field is strictly advisory. OpenClawd logs whether it accepts
    or ignores this hint (see metadata.delegation_hint_decision).
    """

    soul_injection_phase: Optional[str] = None
    """SOUL 策略注入阶段审计字段（PR-006）。

    - None：纯聊天路径（chat_only），未注入 SOUL。
    - "task_execute"：已在 task_execute 执行阶段注入 SOUL。
    - "hybrid"：已在 hybrid 执行阶段注入 SOUL。

    此字段明确记录 SOUL 策略的注入边界，使调用方可以验证纯聊天路径从未接触 SOUL。
    """

    routing_authority: str = "advisory_to_openclawd"
    """多模型路由权威注解（PR-006）。

    AgentKernel 不拥有最终路由决策权。任何路由建议均为 advisory，
    最终路由决策权由 OpenClawd（及其路由模块）持有。
    此字段固定为 "advisory_to_openclawd" 以明确该边界。
    """

    model: str = ""
    """使用的 LLM 模型名称"""

    session_id: str = ""
    error: str = ""
    latency_ms: float = 0.0
    # PR-9: cognition/planning layer authority annotation (additive, non-breaking).
    # AgentKernel is the embedded cognition/planning sub-layer of OpenClawd.
    authority_role: str = "cognition_planning_layer"

    def to_api_dict(self) -> Dict[str, Any]:
        """转换为 API 响应兼容的 dict（兼容现有 UnifiedChatResponse）。"""
        return {
            "success": self.success,
            "mode": self.mode,
            "reply": self.reply,
            "response": self.reply,  # 向后兼容
            "agent_steps": [s.model_dump() for s in self.agent_steps],
            "tool_calls": [t.model_dump() for t in self.tool_calls],
            "task_result": self.task_result,
            "delegation_hint": self.delegation_hint,
            # PR-006: SOUL injection boundary audit field
            "soul_injection_phase": self.soul_injection_phase,
            # PR-006: routing authority is advisory only — OpenClawd owns final routing
            "routing_authority": self.routing_authority,
            "intent": self.intent.raw_intent,
            "confidence": self.intent.confidence,
            "model": self.model,
            "session_id": self.session_id,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "authority_role": self.authority_role,
            # PR-10: architecture diagnostics layer identifier (additive)
            "arch_layer_id": "cognition_layer",
        }


# ──────────────────────────────────────────────────────────────────────────────
# 内核主体
# ──────────────────────────────────────────────────────────────────────────────


class AgentKernel:
    """OpenClawd 的内嵌认知/规划内核。

    架构角色：
      AgentKernel 是 OpenClawd 的内部组件，负责认知推理和规划。它不是独立的
      顶级主权实体，不拥有传输通道，也不主导多设备编排。所有的 AgentKernel
      实例均由 OpenClawd 通过 _get_kernel() 创建和持有。

    职责边界：
      - 执行意图路由（chat_only / task_execute / hybrid）
      - 在执行路径注入 SOUL 策略并调用 ExecutionPlanner
      - 返回结构化的 KernelResponse（认知/规划产物）
      - 不直接调用 OpenClawd（避免循环依赖，保持单向依赖关系）
      - 不拥有传输、设备注册或跨设备调度主权

    OpenClawd 持有 AgentKernel 实例（_kernel 属性），负责：
      - AgentKernel 的生命周期管理
      - 解释 KernelResponse（认知产物）
      - 根据 delegation_hint 和 execution_path 决定后续动作

    PR-006 执行契约（明确且可强制执行）:
      1. OpenClawd 是最终主体决策权威；AgentKernel 仅为认知/规划层。
      2. delegation_hint 严格为建议性质（advisory only）；
         OpenClawd 记录是否采纳该建议，并拥有完全的否决权。
      3. SOUL 策略仅在 task_execute 或 hybrid 执行阶段注入；
         纯聊天路径（chat_only）绝不加载 SOUL。
      4. 多模型路由权威属于 OpenClawd（或其路由模块）；
         AgentKernel 的任何路由建议均为 advisory（见 KernelResponse.routing_authority）。
    """

    _instance: Optional["AgentKernel"] = None

    def __new__(cls) -> "AgentKernel":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._llm_router: Optional[Any] = None
        self._intent_router: Optional[IntentRouter] = None
        self._planner: Optional[ExecutionPlanner] = None
        logger.info("AgentKernel 已初始化")

    # ──────────────────────────────────────────────────────────────────
    # 延迟初始化（避免循环导入）
    # ──────────────────────────────────────────────────────────────────

    def _ensure_components(self) -> None:
        """按需初始化依赖组件（懒加载）。"""
        if self._llm_router is None:
            try:
                from core.unified import get_unified_llm_router
                self._llm_router = get_unified_llm_router()
            except Exception as exc:
                logger.warning("AgentKernel: 无法加载 UnifiedLLMRouter: %s", exc)
                try:
                    from core.multi_llm_router import get_llm_router
                    self._llm_router = get_llm_router()
                except Exception as exc2:
                    logger.warning("AgentKernel: 无法加载 MultiLLMRouter: %s", exc2)

        if self._intent_router is None:
            self._intent_router = IntentRouter(self._llm_router)

        if self._planner is None:
            self._planner = ExecutionPlanner(self._llm_router)

    # ──────────────────────────────────────────────────────────────────
    # 主入口
    # ──────────────────────────────────────────────────────────────────

    async def handle_message(
        self,
        message: str,
        session_id: str = "",
        device_id: str = "",
        context: Optional[List[Dict[str, str]]] = None,
        timeout: float = 90.0,
    ) -> KernelResponse:
        """
        统一消息处理入口。

        Args:
            message:    用户自然语言输入
            session_id: 会话 ID（跨设备共享）
            device_id:  请求来源设备 ID
            context:    对话历史（最近 N 轮）
            timeout:    整体超时秒数

        Returns:
            KernelResponse — 结构化响应
        """
        t0 = time.monotonic()
        sid = session_id or device_id or f"sess_{uuid.uuid4().hex[:8]}"
        ctx = context or []

        logger.info(
            "AgentKernel.handle_message | session=%s device=%s len(msg)=%d",
            sid, device_id, len(message),
        )

        try:
            return await asyncio.wait_for(
                self._process(message, sid, device_id, ctx),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            latency = (time.monotonic() - t0) * 1000
            logger.error("AgentKernel: 整体超时 (%.1fs)", timeout)
            return KernelResponse(
                success=False,
                mode=IntentMode.CHAT_ONLY,
                reply=f"请求处理超时（{timeout:.0f}s），请稍后重试。",
                session_id=sid,
                error="timeout",
                latency_ms=latency,
            )
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            logger.exception("AgentKernel: 未捕获异常: %s", exc)
            return KernelResponse(
                success=False,
                mode=IntentMode.CHAT_ONLY,
                reply=f"系统内部错误：{exc}",
                session_id=sid,
                error=str(exc),
                latency_ms=latency,
            )

    async def _process(
        self,
        message: str,
        session_id: str,
        device_id: str,
        context: List[Dict[str, str]],
    ) -> KernelResponse:
        t0 = time.monotonic()
        self._ensure_components()

        # ── 步骤 1: 加载通用策略（AGENTS + USER，不含 SOUL）──
        agents_policy = _safe_load(get_agents, "AGENTS")
        user_policy = _safe_load(get_user, "USER")

        # ── 步骤 2: 意图路由 ──
        intent = await self._intent_router.route(message, context)
        logger.info(
            "意图路由完成: mode=%s confidence=%.2f method=%s",
            intent.mode, intent.confidence, intent.method,
        )

        # ── 步骤 3: 根据意图分流处理 ──
        if intent.mode == IntentMode.CHAT_ONLY:
            result = await self._handle_chat(
                message, session_id, context, user_policy,
                task_hint=intent.task_hint,
            )
            result.intent = intent
            result.latency_ms = (time.monotonic() - t0) * 1000
            result.session_id = session_id
            return result

        # task_execute 或 hybrid：加载 SOUL（仅此时注入）
        # 显式断言：确保此代码路径只在执行模式下被触发
        assert intent.mode in (IntentMode.TASK_EXECUTE, IntentMode.HYBRID), (
            f"SOUL 只能在 task_execute/hybrid 模式加载，当前 mode={intent.mode}"
        )
        # PR-006: record the phase at which SOUL is injected so KernelResponse
        # carries an auditable soul_injection_phase field (None for chat_only).
        soul_injection_phase = intent.mode
        logger.debug("SOUL 注入: 执行路径 mode=%s", intent.mode)
        soul_policy = _safe_load(get_soul, "SOUL")

        # PR-507: Front-load CanonicalTask — establish task ontology before
        # assembling ExecutionPlan so the canonical layer is always primary.
        try:
            from core.task_adapter import adapt_to_canonical_task as _adapt_kernel
            from core.canonical_task import TaskOrigin as _KernelTaskOrigin
            _kernel_canonical = _adapt_kernel(
                {
                    "goal": message,
                    "tool_name": intent.task_hint or "kernel_execute",
                    "args": {"message": message, "mode": intent.mode},
                },
                origin=_KernelTaskOrigin.AI_INTENT,
                session_id=session_id,
            )
            logger.debug(
                "AgentKernel._process: CanonicalTask front-loaded task_id=%s",
                _kernel_canonical.identity.task_id,
            )
            # PR-513 / GAP-512-007: Emit audit_task_admitted so task admission
            # is visible in the canonical audit trail.
            try:
                from core.audit_event_semantics import audit_task_admitted as _aud_admitted
                _aud_admitted(
                    _kernel_canonical.identity.task_id,
                    trace_id=_kernel_canonical.identity.trace_id or "",
                    source="agent_kernel._process",
                )
            except Exception as _aud_adm_err:
                logger.debug(
                    "AgentKernel._process: audit_task_admitted skipped — %s", _aud_adm_err
                )
        except Exception as _kt_err:
            logger.debug(
                "AgentKernel._process: CanonicalTask front-load skipped — %s", _kt_err
            )

        plan = ExecutionPlan(
            message=message,
            intent=intent,
            soul_policy=soul_policy,
            agents_policy=agents_policy,
            user_policy=user_policy,
            session_id=session_id,
            device_id=device_id,
            context=context,
        )
        exec_result = await self._planner.execute(plan)

        # hybrid 模式：在执行结果前添加自然语言回复
        reply = exec_result.reply
        if intent.mode == IntentMode.HYBRID and exec_result.success:
            reply = self._format_hybrid_reply(message, exec_result)

        resp = KernelResponse(
            success=exec_result.success,
            mode=intent.mode,
            reply=reply,
            agent_steps=exec_result.agent_steps,
            tool_calls=exec_result.tool_calls,
            task_result=exec_result.task_result,
            intent=intent,
            model=exec_result.model,
            session_id=session_id,
            error=exec_result.error,
            latency_ms=(time.monotonic() - t0) * 1000,
            # PR-006: record which execution phase injected SOUL
            soul_injection_phase=soul_injection_phase,
        )

        # ── 步骤 4: 记录会话 ──
        self._record_session(session_id, message, resp.reply)

        return resp

    # ──────────────────────────────────────────────────────────────────
    # 聊天处理（不注入 SOUL）
    # ──────────────────────────────────────────────────────────────────

    async def _handle_chat(
        self,
        message: str,
        session_id: str,
        context: List[Dict[str, str]],
        user_policy: str,
        task_hint: str = "",
    ) -> KernelResponse:
        """纯聊天处理路径——完全不加载 SOUL。

        设计约束：
          此方法不回调 OpenClawd，以保持单向依赖关系（OpenClawd → AgentKernel）。
          聊天响应通过 LLM Router 直接生成，OpenClawd 持有最终解释权。
        """
        # 直接调用 LLM Router 处理聊天（保持单向依赖，不回调 OpenClawd）
        return await self._fallback_chat(message, session_id, context, user_policy, task_hint=task_hint)

    async def _fallback_chat(
        self,
        message: str,
        session_id: str,
        context: List[Dict[str, str]],
        user_policy: str,
        task_hint: str = "",
    ) -> KernelResponse:
        """直接通过 LLM Router 处理聊天（最终降级路径）。

        ``task_hint`` is the ``IntentResult.task_hint`` string produced by
        :class:`~core.agent.intent_router.IntentRouter`.  When non-empty it is
        forwarded to :py:meth:`~core.multi_llm_router.MultiLLMRouter.chat` as
        the ``task_type`` hint so that the router can apply task-aware model
        selection instead of falling back to generic classification.
        """
        if self._llm_router is None:
            return KernelResponse(
                success=False,
                mode=IntentMode.CHAT_ONLY,
                reply="LLM 服务未配置，请在 Dashboard 中设置 API Key。",
                error="llm_unavailable",
            )

        try:
            system_content = "你是 Galaxy 智能助手，一个自然流畅的 AI 对话伙伴。"
            if user_policy:
                system_content += f"\n\n用户偏好：\n{user_policy}"

            messages: List[Dict[str, str]] = [
                {"role": "system", "content": system_content},
            ]
            for turn in context[-8:]:
                messages.append(turn)
            messages.append({"role": "user", "content": message})

            logger.debug(
                "text-path routing: task_hint=%r → forwarding to llm_router.chat as task_type",
                task_hint or "(none)",
            )
            if hasattr(self._llm_router, "chat"):
                raw = await self._llm_router.chat(
                    messages,
                    task_type=task_hint or None,
                    temperature=0.7,
                    max_tokens=2048,
                )
                if hasattr(raw, "content"):
                    reply = raw.content
                elif isinstance(raw, dict):
                    reply = raw.get("content") or raw.get("response") or str(raw)
                else:
                    reply = str(raw)
                model = getattr(raw, "model", "") or (raw.get("model", "") if isinstance(raw, dict) else "")
            else:
                reply = "LLM Router 接口不兼容。"
                model = ""

            return KernelResponse(
                success=True,
                mode=IntentMode.CHAT_ONLY,
                reply=reply,
                model=model,
            )
        except Exception as exc:
            logger.error("LLM 直接调用失败: %s", exc)
            return KernelResponse(
                success=False,
                mode=IntentMode.CHAT_ONLY,
                reply=f"对话处理失败：{exc}",
                error=str(exc),
            )

    # ──────────────────────────────────────────────────────────────────
    # 辅助方法
    # ──────────────────────────────────────────────────────────────────

    def _format_hybrid_reply(self, message: str, result: ExecutionResult) -> str:
        """Hybrid 模式：在执行结果前附加自然语言说明。"""
        if not result.reply:
            return f"我已根据你的请求执行了任务。"
        return result.reply

    def _record_session(self, session_id: str, user_msg: str, assistant_msg: str) -> None:
        """异步记录会话历史（失败不中断主流程）。"""
        try:
            from core.session_manager import get_session_manager
            sm = get_session_manager()
            sm.add_message(session_id, "user", user_msg)
            sm.add_message(session_id, "assistant", assistant_msg)
        except Exception:
            pass

    def get_status(self) -> Dict[str, Any]:
        """返回内核状态信息（供 Dashboard 监控）。"""
        self._ensure_components()
        llm_available = False
        if self._llm_router is not None:
            try:
                llm_available = bool(
                    self._llm_router.is_available()
                    if hasattr(self._llm_router, "is_available")
                    else True
                )
            except Exception:
                pass

        return {
            "kernel": "AgentKernel",
            "llm_router": type(self._llm_router).__name__ if self._llm_router else "none",
            "llm_available": llm_available,
            "soul_policy_loaded": bool(get_soul()),
            "agents_policy_loaded": bool(get_agents()),
            "user_policy_loaded": bool(get_user()),
        }


# ──────────────────────────────────────────────────────────────────────────────
# 内部辅助
# ──────────────────────────────────────────────────────────────────────────────


def _safe_load(fn, name: str) -> str:
    """安全调用策略加载函数，捕获所有异常。"""
    try:
        return fn()
    except Exception as exc:
        logger.warning("策略文件加载失败 [%s]: %s", name, exc)
        return ""


# ──────────────────────────────────────────────────────────────────────────────
# 模块级单例与便捷函数
# ──────────────────────────────────────────────────────────────────────────────

_kernel: Optional[AgentKernel] = None


def get_kernel() -> AgentKernel:
    """返回全局 AgentKernel 单例。

    注意：AgentKernel 是 OpenClawd 的内嵌认知层。
    外部代码应通过 OpenClawd（openclawd._get_kernel()）访问，
    而非直接调用本函数，以维护正确的架构边界。
    """
    global _kernel
    if _kernel is None:
        _kernel = AgentKernel()
    return _kernel


async def handle_message(
    message: str,
    session_id: str = "",
    device_id: str = "",
    context: Optional[List[Dict[str, str]]] = None,
    timeout: float = 90.0,
) -> KernelResponse:
    """模块级快捷函数：直接调用全局内核处理消息。

    注意：正常流程应由 OpenClawd 调用内嵌 AgentKernel；
    此函数主要供内部测试和诊断使用。
    """
    return await get_kernel().handle_message(
        message=message,
        session_id=session_id,
        device_id=device_id,
        context=context,
        timeout=timeout,
    )
