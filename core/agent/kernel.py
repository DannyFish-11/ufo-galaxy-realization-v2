"""
core/agent/kernel.py
======================
统一智能体内核 — 对话/执行一体化入口

完整流程：
  1. 接收自然语言请求
  2. 注入 USER / AGENTS 策略（通用）
  3. 调用 IntentRouter 判定 chat_only / task_execute / hybrid
  4. 若需执行（task_execute 或 hybrid 执行阶段）：
       → 注入 SOUL 策略（仅此时）
       → 调用 ExecutionPlanner → AgentFactory / Team / Swarm
  5. 若纯聊天（chat_only）：
       → 直接走 LLM 对话，不加载 SOUL
  6. 统一返回 KernelResponse（Pydantic）

关键约束：
  - SOUL.md 仅在 task_execute / hybrid 执行阶段由本模块注入
  - 纯聊天路径完全不接触 SOUL
  - 任何异常均有超时/降级处理，不中断服务
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
# 响应模型
# ──────────────────────────────────────────────────────────────────────────────


class KernelResponse(BaseModel):
    """统一内核响应（所有出口统一使用此格式）。"""

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

    model: str = ""
    """使用的 LLM 模型名称"""

    session_id: str = ""
    error: str = ""
    latency_ms: float = 0.0

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
            "intent": self.intent.raw_intent,
            "confidence": self.intent.confidence,
            "model": self.model,
            "session_id": self.session_id,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


# ──────────────────────────────────────────────────────────────────────────────
# 内核主体
# ──────────────────────────────────────────────────────────────────────────────


class AgentKernel:
    """统一智能体内核（进程级单例）。"""

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
            result = await self._handle_chat(message, session_id, context, user_policy)
            result.intent = intent
            result.latency_ms = (time.monotonic() - t0) * 1000
            result.session_id = session_id
            return result

        # task_execute 或 hybrid：加载 SOUL（仅此时注入）
        soul_policy = _safe_load(get_soul, "SOUL")

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
    ) -> KernelResponse:
        """纯聊天处理路径——完全不加载 SOUL。"""
        # 优先委托 OpenClawd（已有完整聊天逻辑）
        try:
            from core.openclawd import get_openclawd
            clawd = get_openclawd()
            result = await clawd.handle_chat(message, session_id)
            return KernelResponse(
                success=result.get("success", True),
                mode=IntentMode.CHAT_ONLY,
                reply=result.get("response", ""),
                model=result.get("metadata", {}).get("model", ""),
            )
        except ImportError:
            pass
        except Exception as exc:
            logger.warning("OpenClawd 聊天失败，降级到直接 LLM 调用: %s", exc)

        # 降级：直接调用 LLM Router
        return await self._fallback_chat(message, session_id, context, user_policy)

    async def _fallback_chat(
        self,
        message: str,
        session_id: str,
        context: List[Dict[str, str]],
        user_policy: str,
    ) -> KernelResponse:
        """直接通过 LLM Router 处理聊天（最终降级路径）。"""
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

            if hasattr(self._llm_router, "chat"):
                raw = await self._llm_router.chat(messages, temperature=0.7, max_tokens=2048)
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
    """返回全局 AgentKernel 单例。"""
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
    """模块级快捷函数：直接调用全局内核处理消息。"""
    return await get_kernel().handle_message(
        message=message,
        session_id=session_id,
        device_id=device_id,
        context=context,
        timeout=timeout,
    )
