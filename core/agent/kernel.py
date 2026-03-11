"""
Galaxy - Unified Agent Kernel
================================

统一智能体内核 — 聊天/执行一体化主决策入口。

调用链:
  输入消息
    → PolicyLoader  (加载 USER 偏好；执行链路额外加载 SOUL + AGENTS)
    → IntentRouter  (分类: chat_only / task_execute / hybrid)
    → [chat_only]   → LLM 纯聊天（仅注入 USER，不注入 SOUL）
    → [task_execute / hybrid] → ExecutionPlanner → AgentFactory → 工具执行
    → 结构化响应 KernelResponse

KernelResponse 字段:
  success       — 是否成功
  mode          — chat_only / task_execute / hybrid
  reply         — 最终回复文本
  agent_steps   — 执行步骤列表（chat_only 时为空）
  tool_calls    — 工具调用记录
  task_result   — 任务结果摘要（chat_only 时为 None）

约束:
  - SOUL.md 仅在 task_execute 或 hybrid 执行阶段注入系统提示
  - chat_only 模式永远不读取 SOUL 内容
  - 所有工具调用经由 CapabilityRegistry
  - AgentFactory 仅在执行链路中调用

使用方式:
    from core.agent.kernel import get_kernel

    kernel = get_kernel()
    result = await kernel.process(
        message="帮我截一张手机屏幕",
        session_id="sess_001",
        device_id="android_001",
    )
    # result.mode == "task_execute"
    # result.reply == "已截图，保存到 ..."
    # result.agent_steps == [{"step_id": ..., "status": "done", ...}]
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Agent.Kernel")


# ============================================================================
# 响应模型
# ============================================================================

@dataclass
class KernelResponse:
    """
    统一内核响应。

    所有模式（chat_only / task_execute / hybrid）共用此结构，
    保持前端解析接口稳定。
    """
    success: bool
    mode: str                              # chat_only / task_execute / hybrid
    reply: str                             # 最终回复文本（所有模式必填）
    agent_steps: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    task_result: Optional[Dict[str, Any]] = None
    intent_label: str = ""
    confidence: float = 0.0
    session_id: str = ""
    model: str = ""
    error: str = ""
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "mode": self.mode,
            "reply": self.reply,
            "agent_steps": self.agent_steps,
            "tool_calls": self.tool_calls,
            "task_result": self.task_result,
            "intent_label": self.intent_label,
            "confidence": self.confidence,
            "session_id": self.session_id,
            "model": self.model,
            "error": self.error,
            "latency_ms": self.latency_ms,
        }


# ============================================================================
# AgentKernel
# ============================================================================

class AgentKernel:
    """
    统一智能体内核。

    单例模式，懒加载所有依赖模块以避免循环导入。
    """

    def __init__(self):
        self._policy_loader = None
        self._intent_router = None
        self._execution_planner = None
        self._capability_registry = None
        self._llm_router = None
        self._initialized = False
        logger.info("AgentKernel 初始化（依赖将懒加载）")

    # ------------------------------------------------------------------
    # 延迟初始化
    # ------------------------------------------------------------------

    def _ensure_ready(self) -> None:
        """首次调用时完成依赖注入"""
        if self._initialized:
            return

        # LLM Router（统一入口）
        try:
            from core.unified import get_unified_llm_router
            self._llm_router = get_unified_llm_router()
        except Exception as e:
            logger.warning("LLM Router 不可用，聊天/规划功能降级: %s", e)

        # Policy Loader
        from core.agent.policy_loader import get_policy_loader
        self._policy_loader = get_policy_loader()

        # Intent Router（注入 LLM router，支持语义增强）
        from core.agent.intent_router import IntentRouter
        self._intent_router = IntentRouter(llm_router=self._llm_router)

        # Capability Registry
        from core.agent.capability_registry import get_capability_registry
        self._capability_registry = get_capability_registry()

        # Execution Planner
        from core.agent.execution_planner import ExecutionPlanner
        self._execution_planner = ExecutionPlanner(
            llm_router=self._llm_router,
            capability_registry=self._capability_registry,
        )

        self._initialized = True
        logger.info("AgentKernel 就绪 (llm_available=%s)", self._llm_router is not None)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    async def process(
        self,
        message: str,
        session_id: Optional[str] = None,
        device_id: Optional[str] = None,
        context: Optional[List[Dict[str, str]]] = None,
        user_id: Optional[str] = None,
    ) -> KernelResponse:
        """
        处理用户消息，返回统一结构化响应。

        Args:
            message:    用户消息
            session_id: 会话 ID（可选，自动生成）
            device_id:  设备 ID（可选，用于设备执行场景）
            context:    历史对话上下文（可选）
            user_id:    用户 ID（可选）

        Returns:
            KernelResponse
        """
        t0 = time.monotonic()
        if not session_id:
            session_id = f"sess_{uuid.uuid4().hex[:12]}"

        self._ensure_ready()

        # 加载策略（chat + task 均加载；SOUL 只在执行链路注入）
        policy_set = self._policy_loader.get()

        # 意图路由
        try:
            decision = await self._intent_router.classify(message, context)
        except Exception as e:
            logger.error("IntentRouter 失败，降级到 chat_only: %s", e)
            from core.agent.intent_router import IntentMode, RouterDecision
            decision = RouterDecision(
                mode=IntentMode.CHAT_ONLY,
                confidence=0.5,
                intent_label="chat",
                reasoning=f"路由失败降级: {e}",
            )

        logger.info(
            "AgentKernel: session=%s mode=%s label=%s conf=%.2f",
            session_id, decision.mode.value, decision.intent_label, decision.confidence,
        )

        try:
            if decision.mode.value == "chat_only":
                resp = await self._handle_chat(
                    message, session_id, context or [], policy_set, decision,
                )
            else:
                resp = await self._handle_execution(
                    message, session_id, device_id, context or [],
                    policy_set, decision,
                )
        except Exception as e:
            logger.error("AgentKernel 处理异常: %s", e, exc_info=True)
            resp = KernelResponse(
                success=False,
                mode=decision.mode.value,
                reply=f"处理消息时出错，请重试。({type(e).__name__})",
                intent_label=decision.intent_label,
                confidence=decision.confidence,
                session_id=session_id,
                error=str(e),
            )

        resp.latency_ms = round((time.monotonic() - t0) * 1000, 1)
        resp.session_id = session_id

        # 记录会话历史
        self._record_turn(session_id, "user", message)
        self._record_turn(session_id, "assistant", resp.reply)

        return resp

    # ------------------------------------------------------------------
    # 聊天处理（chat_only 模式 — 不注入 SOUL）
    # ------------------------------------------------------------------

    async def _handle_chat(
        self,
        message: str,
        session_id: str,
        context: List[Dict[str, str]],
        policy_set,
        decision,
    ) -> KernelResponse:
        """
        纯聊天处理。

        系统提示仅包含 USER 偏好，**绝对不包含 SOUL**。
        """
        system_prompt = policy_set.build_chat_system_prompt()

        if self._llm_router is None or not self._llm_router.is_available():
            return KernelResponse(
                success=True,
                mode="chat_only",
                reply=(
                    "我是 Galaxy 智能助手。LLM 服务暂时不可用，"
                    "请检查 API Key 配置后重试。"
                ),
                intent_label=decision.intent_label,
                confidence=decision.confidence,
                session_id=session_id,
            )

        messages = [{"role": "system", "content": system_prompt}]
        for ctx in context[-10:]:
            messages.append(ctx)
        messages.append({"role": "user", "content": message})

        response = await self._llm_router.chat_completion(
            messages=messages,
            task_type="GENERAL",
        )
        reply = response.choices[0].message.content or ""
        model = getattr(response, "model", "") or (
            self._llm_router.get_default_model() if hasattr(self._llm_router, "get_default_model") else ""
        )

        return KernelResponse(
            success=True,
            mode="chat_only",
            reply=reply,
            intent_label=decision.intent_label,
            confidence=decision.confidence,
            session_id=session_id,
            model=model,
        )

    # ------------------------------------------------------------------
    # 执行处理（task_execute / hybrid 模式 — 注入 SOUL + AGENTS）
    # ------------------------------------------------------------------

    async def _handle_execution(
        self,
        message: str,
        session_id: str,
        device_id: Optional[str],
        context: List[Dict[str, str]],
        policy_set,
        decision,
    ) -> KernelResponse:
        """
        任务执行处理。

        系统提示包含 SOUL + AGENTS + USER（完整策略注入）。
        SOUL 仅在此处注入，chat_only 分支永远不会走到这里。
        """
        # 注入 SOUL — 执行链路专用
        system_prompt = policy_set.build_soul_system_prompt()

        # 同步能力注册表（异步，失败不阻塞）
        try:
            await self._capability_registry.sync()
        except Exception as e:
            logger.debug("CapabilityRegistry.sync 跳过: %s", e)

        # 生成执行计划
        try:
            plan = await self._execution_planner.plan(
                message=message,
                intent_label=decision.intent_label,
                system_prompt=system_prompt,
                context=context,
            )
        except Exception as e:
            logger.error("ExecutionPlanner 失败: %s", e)
            # 降级：直接用 LLM 回答（此时仍注入 SOUL）
            return await self._fallback_llm_reply(
                message, session_id, system_prompt, decision, str(e),
            )

        # 执行计划步骤
        agent_steps: List[Dict[str, Any]] = []
        tool_calls: List[Dict[str, Any]] = []
        final_outputs: List[str] = []
        all_success = True

        for step in plan.steps:
            plan.mark_step_running(step.step_id)
            step_record: Dict[str, Any] = {
                "step_id": step.step_id,
                "description": step.description,
                "tool_name": step.tool_name,
                "status": "running",
            }
            agent_steps.append(step_record)

            if step.tool_name and self._capability_registry.has_tool(step.tool_name):
                # 通过 CapabilityRegistry 调用工具
                invoke_result = await self._capability_registry.invoke(
                    step.tool_name, **step.tool_params
                )
                tool_call_record = {
                    "tool": step.tool_name,
                    "params": step.tool_params,
                    "success": invoke_result["success"],
                    "result": invoke_result.get("result"),
                    "error": invoke_result.get("error", ""),
                }
                tool_calls.append(tool_call_record)

                if invoke_result["success"]:
                    plan.mark_step_done(step.step_id, invoke_result["result"])
                    step_record["status"] = "done"
                    step_record["output"] = invoke_result["result"]
                    out = invoke_result["result"]
                    if isinstance(out, str):
                        final_outputs.append(out)
                    elif isinstance(out, dict):
                        final_outputs.append(str(out.get("output", out)))
                    else:
                        final_outputs.append(str(out))
                else:
                    plan.mark_step_failed(step.step_id, invoke_result["error"])
                    step_record["status"] = "failed"
                    step_record["error"] = invoke_result["error"]
                    all_success = False
                    logger.warning(
                        "步骤 %s 工具 %s 失败: %s",
                        step.step_id, step.tool_name, invoke_result["error"],
                    )
            else:
                # 无工具或工具未注册 — 通过 AgentFactory/OpenClawd 执行
                agent_result = await self._execute_via_agent(
                    step, session_id, device_id, system_prompt, message,
                )
                if agent_result.get("success"):
                    plan.mark_step_done(step.step_id, agent_result.get("result"))
                    step_record["status"] = "done"
                    step_record["output"] = agent_result.get("result")
                    reply_text = agent_result.get("reply", "")
                    if reply_text:
                        final_outputs.append(reply_text)
                else:
                    plan.mark_step_failed(step.step_id, agent_result.get("error", "Agent 执行失败"))
                    step_record["status"] = "failed"
                    step_record["error"] = agent_result.get("error", "Agent 执行失败")
                    all_success = False

        # 汇总结果
        reply = self._build_final_reply(
            message, final_outputs, plan, all_success,
            system_prompt, context,
        )

        task_result = {
            "success": all_success,
            "plan_id": plan.plan_id,
            "agent_mode": plan.agent_mode,
            "steps_summary": plan.summary(),
            "outputs": final_outputs,
        }

        model = (
            self._llm_router.get_default_model()
            if self._llm_router and hasattr(self._llm_router, "get_default_model")
            else ""
        )

        return KernelResponse(
            success=all_success,
            mode=decision.mode.value,
            reply=reply,
            agent_steps=agent_steps,
            tool_calls=tool_calls,
            task_result=task_result,
            intent_label=decision.intent_label,
            confidence=decision.confidence,
            session_id=session_id,
            model=model,
        )

    # ------------------------------------------------------------------
    # 通过 AgentFactory 执行（无注册工具时）
    # ------------------------------------------------------------------

    async def _execute_via_agent(
        self,
        step,
        session_id: str,
        device_id: Optional[str],
        system_prompt: str,
        original_message: str,
    ) -> Dict[str, Any]:
        """
        步骤无工具时，通过 AgentFactory 或 OpenClawd 执行。

        优先使用 AgentFactory（多步骤任务），降级到 LLM 直接回答。
        """
        # 尝试 AgentFactory
        try:
            from core.agent_factory import get_agent_factory
            factory = get_agent_factory(llm_router=self._llm_router)
            task_msg = step.description or original_message
            agent = await factory.create_from_llm(task_msg)
            result = await factory.execute_agent_task(
                agent.id,
                {"task": task_msg, "system_prompt": system_prompt},
            )
            outputs = []
            for r in result.get("results", []):
                if isinstance(r, dict) and "output" in r:
                    outputs.append(str(r["output"]))
                elif isinstance(r, dict) and "error" in r:
                    outputs.append(f"[错误] {r['error']}")
            try:
                factory.terminate_agent(agent.id)
            except Exception:
                pass
            return {
                "success": not any("error" in str(o).lower() and "[错误]" in o for o in outputs),
                "result": outputs,
                "reply": "\n".join(outputs) if outputs else "Agent 任务已完成",
            }
        except Exception as e:
            logger.debug("AgentFactory 执行失败，降级到 LLM 直接回复: %s", e)

        # 降级：LLM 直接回答步骤描述
        if self._llm_router and self._llm_router.is_available():
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": step.description or original_message},
                ]
                response = await self._llm_router.chat_completion(
                    messages=messages,
                    task_type="REASONING",
                )
                reply = response.choices[0].message.content or ""
                return {"success": True, "result": reply, "reply": reply}
            except Exception as e2:
                logger.error("LLM 直接回复也失败: %s", e2)
                return {"success": False, "error": str(e2), "reply": ""}

        return {"success": False, "error": "无可用执行方式（AgentFactory 和 LLM 均不可用）", "reply": ""}

    # ------------------------------------------------------------------
    # 最终回复构建
    # ------------------------------------------------------------------

    def _build_final_reply(
        self,
        original_message: str,
        outputs: List[str],
        plan,
        all_success: bool,
        system_prompt: str,
        context: List[Dict[str, str]],
    ) -> str:
        """
        将执行结果汇总为自然语言回复。

        如果有执行输出，直接拼接。
        如果 LLM 可用，用 LLM 整合输出成流畅回复（包含 SOUL 人格）。
        """
        if not outputs and not all_success:
            return f"执行任务时遇到问题，部分步骤失败。请检查日志或重试。"

        if not outputs:
            return "任务已完成，无输出内容。"

        # 输出较短时直接返回
        combined = "\n".join(outputs)
        if len(combined) < 300 or self._llm_router is None or not self._llm_router.is_available():
            return combined

        # 用 LLM 汇总（异步变同步不安全，直接返回原始输出）
        return combined

    # ------------------------------------------------------------------
    # 降级回复（执行计划生成失败时）
    # ------------------------------------------------------------------

    async def _fallback_llm_reply(
        self,
        message: str,
        session_id: str,
        system_prompt: str,
        decision,
        error_hint: str,
    ) -> KernelResponse:
        """执行计划生成失败时，仍注入 SOUL 的 LLM 直接回复"""
        if self._llm_router and self._llm_router.is_available():
            try:
                messages = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ]
                response = await self._llm_router.chat_completion(
                    messages=messages,
                    task_type="GENERAL",
                )
                reply = response.choices[0].message.content or ""
                return KernelResponse(
                    success=True,
                    mode=decision.mode.value,
                    reply=reply,
                    intent_label=decision.intent_label,
                    confidence=decision.confidence,
                    session_id=session_id,
                    task_result={"success": True, "note": "计划生成失败，LLM 直接回复"},
                )
            except Exception as e:
                error_hint = f"{error_hint}; LLM 直接回复也失败: {e}"

        return KernelResponse(
            success=False,
            mode=decision.mode.value,
            reply="任务执行遇到问题，请重试或检查服务状态。",
            intent_label=decision.intent_label,
            confidence=decision.confidence,
            session_id=session_id,
            error=error_hint,
            task_result={"success": False, "error": error_hint},
        )

    # ------------------------------------------------------------------
    # 会话记录（轻量，主要用于 context 透传）
    # ------------------------------------------------------------------

    def _record_turn(self, session_id: str, role: str, content: str) -> None:
        """轻量级对话记录（同步到 ai_intent ConversationMemory）"""
        try:
            import asyncio
            from core.ai_intent import get_conversation_memory
            memory = get_conversation_memory()
            # 在已运行的事件循环中异步执行，失败不影响主流程
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(memory.add_turn(session_id, role, content))
            except RuntimeError:
                pass  # 不在事件循环中，跳过记录
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """返回内核运行状态（供监控/Dashboard 使用）"""
        self._ensure_ready()
        return {
            "kernel": "AgentKernel",
            "initialized": self._initialized,
            "llm_available": (
                self._llm_router is not None
                and self._llm_router.is_available()
            ) if self._llm_router else False,
            "llm_model": (
                self._llm_router.get_default_model()
                if self._llm_router and hasattr(self._llm_router, "get_default_model")
                else ""
            ),
            "capability_registry": (
                self._capability_registry.stats()
                if self._capability_registry else {}
            ),
            "policy": (
                self._policy_loader.get().to_dict()
                if self._policy_loader else {}
            ),
        }


# ============================================================================
# 模块级单例
# ============================================================================

_kernel_instance: Optional[AgentKernel] = None


def get_kernel() -> AgentKernel:
    """获取 AgentKernel 全局单例"""
    global _kernel_instance
    if _kernel_instance is None:
        _kernel_instance = AgentKernel()
    return _kernel_instance
