"""
Galaxy - 端到端全链路编排器
================================

从用户指令到设备操控的完整闭环:
  唤醒 → 会话管理 → 意图解析 → 智能路由 → Agent 分发 → 设备操控 → 结果广播

用法:
    from core.e2e_pipeline import get_pipeline

    pipeline = get_pipeline()
    result = await pipeline.execute(
        message="帮我在手机上打开微信",
        user_id="user_001",
        source_device_id="pc_01",
    )

全链路步骤:
  1. SessionManager: 会话管理 + 历史同步
  2. IntentParser: 意图解析 (操作 / 聊天 / 设备控制 / 多步骤)
  3. 智能路由:
     - 设备操控 → AgentManifest → 分发到目标设备
     - 复杂任务 → Agent Team / Fractal 分解
     - 简单聊天 → 直接 LLM
  4. 执行并收集结果
  5. 广播结果到所有关联设备 (WebSocket)
  6. 持久化到会话历史
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.E2EPipeline")


class EndToEndPipeline:
    """全链路编排器"""

    def __init__(
        self,
        session_manager=None,
        llm_router=None,
        agent_factory=None,
        connection_manager=None,
    ):
        self.session_manager = session_manager
        self.llm_router = llm_router
        self.agent_factory = agent_factory
        self.connection_manager = connection_manager
        logger.info("EndToEndPipeline 已初始化")

    async def execute(
        self,
        message: str,
        user_id: str = "default",
        source_device_id: str = "",
        session_id: Optional[str] = None,
        context: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """
        执行全链路编排

        Returns:
            {
                "success": bool,
                "reply": str,
                "session_id": str,
                "mode": str,  # "chat" | "device_control" | "agent_task" | "fallback"
                "data": {...},
                "devices_notified": [str],
            }
        """
        t0 = time.monotonic()
        result = {
            "success": False,
            "reply": "",
            "session_id": "",
            "mode": "fallback",
            "data": {},
            "devices_notified": [],
        }

        # ═══════ Step 1: 会话管理 ═══════
        try:
            if self.session_manager:
                if session_id:
                    session = self.session_manager.get_session(session_id)
                    if session and source_device_id:
                        self.session_manager.join_session(session_id, source_device_id)
                else:
                    session = self.session_manager.get_or_create_session(
                        user_id, source_device_id
                    )
                    session_id = session.id if session else None

                if session_id:
                    self.session_manager.add_message(
                        session_id, "user", message, source_device_id
                    )
                    result["session_id"] = session_id

                    # 从历史补充 context
                    if not context:
                        context = self.session_manager.get_history(
                            session_id, max_turns=10
                        )
        except Exception as e:
            logger.debug(f"会话管理异常: {e}")

        # ═══════ Step 2: 意图解析 ═══════
        intent_type = "chat"
        intent_data = {}
        target_device = ""

        try:
            from core.ai_intent import IntentParser
            if self.llm_router and self.llm_router.is_available():
                parser = IntentParser(llm_client=self.llm_router)
                parsed = await parser.parse(message, {"history": context} if context else None)
                intent_type = parsed.intent
                intent_data = {
                    "command": parsed.command,
                    "targets": parsed.targets,
                    "params": parsed.params,
                    "confidence": parsed.confidence,
                }
                # 提取目标设备
                for t in parsed.targets:
                    if isinstance(t, str) and any(
                        kw in t for kw in ["phone", "手机", "平板", "tablet", "pc", "电脑"]
                    ):
                        target_device = t
                        break
        except Exception as e:
            logger.debug(f"意图解析异常，使用关键词匹配: {e}")
            # 关键词匹配兜底
            from core.routes.chat import _is_action_intent
            if _is_action_intent(message):
                intent_type = "action"

        # ═══════ Step 3: 智能路由 + 执行 ═══════

        if intent_type in ("device_control", "multi_device") and target_device:
            # 路径 A: 设备操控 → AgentManifest 分发
            result = await self._execute_device_control(
                message, target_device, source_device_id, intent_data, result
            )
        elif intent_type in ("action", "workflow", "batch_task", "multi_device"):
            # 路径 B: 复杂任务 → Agent 工厂
            result = await self._execute_agent_task(
                message, intent_data, context, result
            )
        else:
            # 路径 C: 纯聊天 → LLM 直接回复
            result = await self._execute_chat(message, context, result)

        # ═══════ Step 4: 结果持久化 + 广播 ═══════
        latency_ms = (time.monotonic() - t0) * 1000
        result["data"]["latency_ms"] = latency_ms

        # 保存到会话
        if session_id and self.session_manager:
            try:
                self.session_manager.add_message(
                    session_id, "assistant", result["reply"], ""
                )
            except Exception:
                pass

        # 广播到所有关联设备
        if session_id and self.connection_manager and self.session_manager:
            try:
                session = self.session_manager.get_session(session_id)
                if session:
                    for device_id in session.devices:
                        if device_id != source_device_id:
                            await self.connection_manager.send_to_device(device_id, {
                                "type": "chat_response",
                                "session_id": session_id,
                                "reply": result["reply"],
                                "mode": result["mode"],
                            })
                            result["devices_notified"].append(device_id)
            except Exception as e:
                logger.debug(f"结果广播异常: {e}")

        return result

    async def _execute_device_control(
        self, message: str, target_device: str, source_device: str,
        intent_data: Dict, result: Dict,
    ) -> Dict:
        """路径 A: 设备操控 — 创建 AgentManifest 并分发"""
        result["mode"] = "device_control"
        try:
            from core.agent_manifest import AgentManifest

            manifest = AgentManifest.create_device_control_agent(
                target_device=target_device,
                instruction=message,
                source_device=source_device,
            )

            # 分发到目标设备
            if self.connection_manager:
                sent = await self.connection_manager.send_to_device(target_device, {
                    "type": "agent_manifest",
                    "manifest": manifest.to_dict(),
                })
                if sent:
                    result["success"] = True
                    result["reply"] = (
                        f"已将控制 Agent 分发到设备 {target_device}，正在执行: {message}"
                    )
                    result["data"]["manifest_id"] = manifest.manifest_id
                    result["data"]["target_device"] = target_device
                else:
                    result["reply"] = f"设备 {target_device} 不在线，无法分发 Agent"
            else:
                result["success"] = True
                result["reply"] = f"Agent 已创建（设备 {target_device}），等待连接后分发"
                result["data"]["manifest"] = manifest.to_dict()

        except Exception as e:
            logger.error(f"设备操控失败: {e}")
            result["reply"] = f"设备操控失败: {str(e)}"

        return result

    async def _execute_agent_task(
        self, message: str, intent_data: Dict,
        context: Optional[List[Dict]], result: Dict,
    ) -> Dict:
        """路径 B: 复杂任务 — Agent 工厂分发"""
        result["mode"] = "agent_task"
        try:
            if not self.agent_factory:
                from core.agent_factory import get_agent_factory
                self.agent_factory = get_agent_factory(self.llm_router)

            # 根据复杂度选择策略
            targets = intent_data.get("targets", [])

            if len(targets) > 2:
                # 高复杂度 → 分形分解
                try:
                    fractal_result = await self.agent_factory.create_fractal_task(
                        message, intent_data
                    )
                    result["success"] = fractal_result.get("success", False)
                    result["reply"] = fractal_result.get("reply", "分形任务已完成")
                    result["data"]["strategy"] = "fractal"
                    return result
                except Exception as e:
                    logger.debug(f"分形执行失败，降级到普通 Agent: {e}")

            # 标准 → LLM 动态生成 Agent
            agent = await self.agent_factory.create_from_llm(
                message, context=intent_data
            )
            exec_result = await self.agent_factory.execute_agent_task(
                agent.id, {"task": message, "context": intent_data}
            )

            outputs = []
            for r in exec_result.get("results", []):
                if isinstance(r, dict) and "output" in r:
                    outputs.append(r["output"])
                elif isinstance(r, dict) and "error" in r:
                    outputs.append(f"[错误] {r['error']}")

            result["success"] = True
            result["reply"] = "\n".join(outputs) if outputs else "Agent 任务已完成"
            result["data"]["agent_id"] = agent.id
            result["data"]["strategy"] = "agent_factory"

            # 清理临时 Agent
            self.agent_factory.terminate_agent(agent.id)

        except Exception as e:
            logger.error(f"Agent 任务执行失败: {e}")
            # 降级到纯聊天
            return await self._execute_chat(message, context, result)

        return result

    async def _execute_chat(
        self, message: str, context: Optional[List[Dict]], result: Dict,
    ) -> Dict:
        """路径 C: 纯 LLM 对话"""
        result["mode"] = "chat"
        if not self.llm_router or not self.llm_router.is_available():
            result["reply"] = (
                "LLM 服务未配置。请在 Dashboard 设置 API Key，"
                "或在 .env 中设置 OPENAI_API_KEY / DEEPSEEK_API_KEY。"
            )
            return result

        try:
            messages = [
                {"role": "system", "content": (
                    "你是 Galaxy 智能助手，一个 L4 级自主性 AI 系统。\n"
                    "你可以控制用户的多种设备（手机、电脑、平板等），"
                    "执行复杂任务，并在多设备间协调。\n"
                    "当用户想要操作设备时，直接描述操作指令即可。"
                )},
            ]
            for ctx in (context or [])[-10:]:
                messages.append(ctx)
            messages.append({"role": "user", "content": message})

            response = await self.llm_router.chat_completion(
                messages=messages, task_type="GENERAL"
            )
            result["success"] = True
            result["reply"] = response.choices[0].message.content or ""
            result["data"]["model"] = getattr(response, "model", "")

        except Exception as e:
            logger.error(f"LLM 对话失败: {e}")
            result["reply"] = f"AI 对话处理失败: {str(e)}"

        return result


# ═══════════════════ 单例 ═══════════════════

_pipeline: Optional[EndToEndPipeline] = None


def get_pipeline(**kwargs) -> EndToEndPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = EndToEndPipeline(**kwargs)
    return _pipeline


def init_pipeline(
    session_manager=None,
    llm_router=None,
    agent_factory=None,
    connection_manager=None,
) -> EndToEndPipeline:
    """初始化全链路编排器（由 startup.py 调用）"""
    global _pipeline
    _pipeline = EndToEndPipeline(
        session_manager=session_manager,
        llm_router=llm_router,
        agent_factory=agent_factory,
        connection_manager=connection_manager,
    )
    return _pipeline
