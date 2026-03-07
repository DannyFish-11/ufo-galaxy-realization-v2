"""
Galaxy - Chat Routes
==========================

Routes:
  POST /api/v1/chat  - 统一对话接口 (意图分流: ReAct Agent / 纯聊天)
"""

import logging
import os
from typing import Any, Dict

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.routes._shared import connection_manager, registered_devices
from core.routes._helpers import nodes_root, _load_node, _execute_node
from core.routes._models import ChatRequest
from core.unified_response import UnifiedChatResponse

logger = logging.getLogger("Galaxy.API")

# 操作意图关键词 — 命中时走 ReAct Agent 调度而非纯聊天
_ACTION_KEYWORDS_ZH = [
    "打开", "关闭", "启动", "运行", "安装", "卸载", "截图", "截屏",
    "点击", "滑动", "输入", "搜索", "发送", "下载", "上传",
    "复制", "粘贴", "传输", "同步", "分享",
    "拍照", "录屏", "录音", "播放", "暂停", "停止",
    "查看电量", "查看状态", "连接设备", "断开设备",
    "帮我操作", "帮我执行", "帮我控制",
    "在手机上", "在电脑上", "在平板上", "在设备上",
    "切换应用", "返回桌面", "锁屏", "解锁", "音量",
]
_ACTION_KEYWORDS_EN = [
    "open ", "close ", "launch ", "run ", "install ", "click ",
    "swipe ", "type ", "screenshot", "send ", "download ",
    "upload ", "execute ", "control ", "operate ",
    "on my phone", "on my pc", "on device", "on android",
    "take photo", "record ", "play ", "pause ", "stop ",
]


def _is_action_intent(msg: str) -> bool:
    """判断用户消息是否为操作指令 (需要 Agent 调度)"""
    msg_lower = msg.lower().strip()
    if len(msg_lower) < 4:
        return False
    for kw in _ACTION_KEYWORDS_ZH:
        if kw in msg_lower:
            return True
    for kw in _ACTION_KEYWORDS_EN:
        if kw in msg_lower:
            return True
    return False


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create chat routes router."""
    router = APIRouter()

    from core.scheduler import AutonomousScheduler
    from core.llm_manager import LLMManager

    scheduler = AutonomousScheduler(nodes_root)
    llm_manager = LLMManager(os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "config.json"
    ))

    @router.post("/api/v1/chat")
    async def chat(req: ChatRequest):
        """
        统一对话接口 — 智能分流:
        1. 操作指令 → ReAct Agent 调度 (LLM + tool_call → 节点执行)
        2. 纯聊天 → LLM 对话回复

        所有 UI (Dashboard / Windows / Android) 统一调用此端点。
        """
        session_id = req.device_id or "default"

        try:
            # === 融合对话记忆 ===
            try:
                from core.ai_intent import get_conversation_memory
                memory = get_conversation_memory()
                await memory.add_turn(session_id, "user", req.message)
                if not req.context:
                    req.context = await memory.get_context(session_id, max_turns=10)
            except Exception as e:
                logger.debug(f"Conversation memory unavailable: {e}")

            # === 意图分流 ===
            if _is_action_intent(req.message) and llm_manager.is_available():
                result = await _handle_agent_action(req, session_id, scheduler, llm_manager)
                return result
            else:
                result = await _handle_pure_chat(req, session_id, llm_manager)
                return result

        except Exception as e:
            logger.error(f"对话失败: {e}")
            resp = UnifiedChatResponse(
                success=False,
                response=f"处理消息时出错: {str(e)}",
                error=str(e),
                session_id=session_id,
            )
            return JSONResponse(resp.to_json_response())

    return router


async def _handle_agent_action(
    req: ChatRequest, session_id: str, scheduler, llm_manager
) -> JSONResponse:
    """操作指令 → ReAct Agent 调度"""
    try:
        async def node_executor(node_id: str, action: str, params: dict):
            target_node_dir = os.path.join(nodes_root, node_id)
            if not os.path.isdir(target_node_dir):
                node_id_resolved = node_id
                for name in os.listdir(nodes_root):
                    if name.startswith(node_id) or node_id in name:
                        target_node_dir = os.path.join(nodes_root, name)
                        node_id_resolved = name
                        break
                else:
                    for did, ws in connection_manager.active_devices.items():
                        try:
                            await ws.send_json({
                                "type": "task",
                                "task_type": action,
                                "payload": params,
                            })
                            return {"success": True, "device": did, "action": action, "via": "websocket"}
                        except Exception:
                            continue
                    return {"error": f"Node {node_id} not found and no device available"}

            if not os.path.isdir(target_node_dir):
                return {"error": f"Node {node_id} not found"}

            fusion_entry = os.path.join(target_node_dir, "fusion_entry.py")
            if not os.path.exists(fusion_entry):
                return {"error": f"Node {node_id} has no fusion_entry.py"}

            node_instance = _load_node(node_id, target_node_dir, fusion_entry)
            if not node_instance:
                return {"error": f"Failed to load node {node_id}"}

            try:
                result = await _execute_node(node_instance, action, params)
                return result
            except Exception as e:
                return {"error": str(e)}

        async def ws_sender(device_id: str, message: dict):
            success = await connection_manager.send_to_device(device_id, message)
            if success:
                return {"success": True, "device_id": device_id, "sent": message.get("task_type", "")}
            return {"success": False, "error": f"Device {device_id} not connected"}

        execution_context = {
            "devices": registered_devices,
            "executor": node_executor,
            "ws_sender": ws_sender,
        }

        plan_result = await scheduler.plan_and_execute(
            req.message,
            llm_manager,
            execution_context,
            max_turns=5,
        )

        reply = plan_result.get("reply", "任务已执行")
        steps = plan_result.get("steps", [])

        if steps:
            step_summary = "\n".join(
                f"  {i+1}. [{s.get('node_id', '?')}] {s.get('action', '?')}"
                for i, s in enumerate(steps)
            )
            full_reply = f"{reply}\n\n执行步骤:\n{step_summary}"
        else:
            full_reply = reply

        try:
            from core.ai_intent import get_conversation_memory
            memory = get_conversation_memory()
            await memory.add_turn(session_id, "assistant", full_reply)
        except Exception:
            pass

        model_name = llm_manager.get_default_model()
        resp = UnifiedChatResponse(
            success=plan_result.get("success", True),
            response=full_reply,
            intent="action",
            confidence=0.9,
            mode="agent_react",
            model=model_name,
            data={"steps": steps},
            session_id=session_id,
        )
        # 增强响应：添加 reply 别名 + agent_steps + routing（Windows 客户端 UI 需要）
        resp_dict = resp.to_json_response()
        resp_dict["reply"] = full_reply
        resp_dict["agent_steps"] = [
            {"type": "action", "tool": s.get("action", ""), "content": s.get("node_id", ""),
             "input": s.get("params", {})}
            for s in steps
        ] if steps else []
        resp_dict["routing"] = {
            "task_type": "action",
            "provider": "",
            "model": model_name,
            "reason": "操作指令 → ReAct Agent 调度",
        }
        return JSONResponse(resp_dict)

    except ValueError as ve:
        logger.warning(f"Agent 调度失败 (LLM 不可用): {ve}, 降级到纯聊天")
        return await _handle_pure_chat(req, session_id, llm_manager)
    except Exception as e:
        logger.error(f"Agent 调度异常: {e}")
        resp = UnifiedChatResponse(
            success=False,
            response=f"操作调度失败: {str(e)}",
            mode="agent_react",
            error=str(e),
            session_id=session_id,
        )
        return JSONResponse(resp.to_json_response())


async def _handle_pure_chat(
    req: ChatRequest, session_id: str, llm_manager
) -> JSONResponse:
    """纯 LLM 对话 (无工具调用)"""
    if llm_manager.is_available():
        try:
            messages = [
                {"role": "system", "content": (
                    "你是 Galaxy 智能助手，一个 L4 级自主性 AI 系统。\n"
                    "当用户想要操作设备时，请告诉他们直接描述操作指令即可，"
                    "系统会自动调度 Agent 执行。例如: '帮我打开手机上的微信'。"
                )},
            ]
            for ctx in (req.context or [])[-10:]:
                messages.append(ctx)
            messages.append({"role": "user", "content": req.message})

            response = await llm_manager.chat_completion(messages=messages)
            reply = response.choices[0].message.content or ""
            model_name = response.model if hasattr(response, "model") else llm_manager.get_default_model()

            try:
                from core.ai_intent import get_conversation_memory
                memory = get_conversation_memory()
                await memory.add_turn(session_id, "assistant", reply)
            except Exception:
                pass

            resp = UnifiedChatResponse(
                success=True,
                response=reply,
                intent="chat",
                confidence=1.0,
                mode="chat",
                model=model_name,
                session_id=session_id,
            )
            # 增强响应：添加 reply 别名 + routing（Windows 客户端 UI 需要）
            resp_dict = resp.to_json_response()
            resp_dict["reply"] = reply
            resp_dict["routing"] = {
                "task_type": "chat",
                "provider": "",
                "model": model_name,
                "reason": "纯聊天 → LLM 对话",
            }
            return JSONResponse(resp_dict)
        except Exception as e:
            logger.warning(f"LLMManager chat failed: {e}")

    resp = UnifiedChatResponse(
        success=False,
        response=(
            "LLM 服务未配置。请在 Dashboard 的 API CONFIG 面板设置 API Key，"
            "或在 .env 文件中设置 OPENAI_API_KEY / DEEPSEEK_API_KEY 等。"
        ),
        mode="fallback",
        error="未配置 LLM API Key",
        session_id=session_id,
    )
    return JSONResponse(resp.to_json_response())
