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
    "传到手机", "传到电脑", "发到手机", "发到电脑",
    "跨设备", "同步剪贴板", "设备间",
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

    from core.unified import get_unified_llm_router

    llm_router = get_unified_llm_router()  # 统一 LLM 路由器入口（委派到 MultiLLMRouter）

    @router.post("/api/v1/chat")
    async def chat(req: ChatRequest):
        """
        统一对话接口 — OpenClawd 唯一入口。

        架构约束（PR86）：
        - /api/v1/chat 只调用 OpenClawd.process()
        - AgentKernel 由 OpenClawd 内部调用，不在此处直接使用
        - 所有 UI (Dashboard / Windows / Android) 统一调用此端点
        - SOUL 注入规则由 OpenClawd 内部统一控制

        所有 UI (Dashboard / Windows / Android) 统一调用此端点。
        跨设备统一会话：同一 user_id 的不同设备共享会话历史。
        """
        # ── 唯一入口: OpenClawd 母体智能体 ──
        # OpenClawd 内部嵌入 AgentKernel；SOUL 注入规则由 OpenClawd 统一管理。
        try:
            from core.openclawd import get_openclawd
            clawd = get_openclawd()
            result = await clawd.process(
                message=req.message,
                device_id=req.device_id,
                session_id=req.session_id,
                context=req.context,
            )
            metadata = result.get("metadata", {})
            resp = UnifiedChatResponse(
                success=result.get("success", False),
                response=result.get("response", ""),
                intent=result.get("intent", "chat"),
                confidence=metadata.get("confidence", 1.0),
                mode=metadata.get("mode", "openclawd"),
                model=metadata.get("model", ""),
                session_id=metadata.get("session_id", req.session_id or ""),
                data=metadata,
                error=result.get("error", ""),
            )
            resp_dict = resp.to_json_response()
            resp_dict["reply"] = result.get("response", "")
            # 记录到会话管理器
            try:
                from core.session_manager import get_session_manager
                sm = get_session_manager()
                sid = req.session_id or req.device_id or "default"
                sm.add_message(sid, "user", req.message, req.device_id)
                sm.add_message(sid, "assistant", result.get("response", ""), req.device_id)
            except Exception:
                pass
            return JSONResponse(resp_dict)
        except Exception as e:
            logger.error(f"OpenClawd 处理异常: {e}", exc_info=True)
            resp = UnifiedChatResponse(
                success=False,
                response=f"处理消息时出错: {str(e)}",
                error=str(e),
                session_id=req.session_id or "",
            )
            return JSONResponse(resp.to_json_response())

    return router


async def _handle_agent_action(
    req: ChatRequest, session_id: str, scheduler, llm_router,
    parsed_intent=None,
) -> JSONResponse:
    """
    操作指令处理 — 三层调度:
    1. CapabilityOrchestrator 直接匹配（MCP/Skill/Node 精确命中）
    2. AgentFactory 创建专用 Agent（复杂/多步任务）
    3. Scheduler ReAct Loop 兜底（通用 tool_call 调度）
    """
    try:
        # ── 层 1: 能力编排器精确匹配 ──
        cap_result = await _try_capability_execute(req.message, parsed_intent)
        if cap_result is not None:
            full_reply = cap_result.get("reply", "能力执行完成")
            try:
                from core.ai_intent import get_conversation_memory
                memory = get_conversation_memory()
                await memory.add_turn(session_id, "assistant", full_reply)
            except Exception:
                pass

            resp = UnifiedChatResponse(
                success=cap_result.get("success", True),
                response=full_reply,
                intent=parsed_intent.intent if parsed_intent else "action",
                confidence=parsed_intent.confidence if parsed_intent else 0.9,
                mode="capability",
                model=llm_router.get_default_model(),
                data=cap_result.get("data"),
                session_id=session_id,
            )
            return JSONResponse(resp.to_json_response())

        # ── 层 2: AgentFactory（多步/复杂任务） ──
        agent_result = await _try_agent_factory(
            req.message, llm_router, parsed_intent
        )
        if agent_result is not None:
            full_reply = agent_result.get("reply", "Agent 任务完成")
            try:
                from core.ai_intent import get_conversation_memory
                memory = get_conversation_memory()
                await memory.add_turn(session_id, "assistant", full_reply)
            except Exception:
                pass

            resp = UnifiedChatResponse(
                success=agent_result.get("success", True),
                response=full_reply,
                intent=parsed_intent.intent if parsed_intent else "action",
                confidence=parsed_intent.confidence if parsed_intent else 0.9,
                mode="agent_factory",
                model=llm_router.get_default_model(),
                data=agent_result.get("data"),
                session_id=session_id,
            )
            return JSONResponse(resp.to_json_response())

        # ── 层 3: Scheduler ReAct Loop 兜底 ──
        return await _handle_scheduler_react(
            req, session_id, scheduler, llm_router, parsed_intent
        )

    except ValueError as ve:
        logger.warning(f"Agent 调度失败 (LLM 不可用): {ve}, 降级到纯聊天")
        return await _handle_pure_chat(req, session_id, llm_router)
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


async def _try_capability_execute(message: str, parsed_intent=None) -> dict | None:
    """
    尝试通过 CapabilityOrchestrator 精确匹配并执行。
    返回 None 表示无精确匹配，应继续后续层。
    """
    try:
        from core.capability_orchestrator import capability_orchestrator

        # 使用 IntentParser 提取的命令做精准发现（优于原始消息）
        query = (parsed_intent.command if parsed_intent and parsed_intent.command
                 else message)
        candidates = await capability_orchestrator.discover(query, limit=3)

        if not candidates:
            return None

        best = candidates[0]
        # 只有高优先级精确匹配才走此路径（避免 builtin_chat 之类的兜底项）
        if best.get("type") == "builtin" and best.get("id") == "builtin_chat":
            return None

        # 构建执行参数
        params = {}
        if parsed_intent and parsed_intent.params:
            params = parsed_intent.params
        params.setdefault("message", message)

        result = await capability_orchestrator.execute(best["id"], **params)
        logger.info(f"CapabilityOrchestrator 命中: {best['id']} ({best['name']})")

        # 统一结果格式
        if isinstance(result, dict):
            reply = result.get("reply") or result.get("content") or str(result)
            return {"success": True, "reply": reply, "data": {"capability": best, "result": result}}
        elif hasattr(result, "content"):
            return {"success": True, "reply": result.content, "data": {"capability": best}}
        else:
            return {"success": True, "reply": str(result), "data": {"capability": best}}

    except Exception as e:
        logger.debug(f"CapabilityOrchestrator 执行失败，继续后续调度: {e}")
        return None


async def _try_agent_factory(message: str, llm_router, parsed_intent=None) -> dict | None:
    """
    尝试通过 AgentFactory 创建专用 Agent 处理复杂任务。
    仅在 IntentParser 判定为复杂任务或涉及多设备/多步骤时触发。
    返回 None 表示任务不需要 AgentFactory。

    复杂度分级:
    - 高复杂 (targets > 2 或 workflow): FractalExecutor 分形递归分解
    - 中复杂 (targets > 1 或 multi_device): LLM 动态生成 Agent
    """
    # 判定是否需要 Agent 工厂
    is_complex = False
    is_highly_complex = False
    if parsed_intent:
        # 多目标 = 复杂
        if len(parsed_intent.targets) > 1:
            is_complex = True
        if len(parsed_intent.targets) > 2:
            is_highly_complex = True
        # 特定意图类型 = 复杂
        if parsed_intent.intent in ("multi_device", "workflow", "batch_task"):
            is_complex = True
        if parsed_intent.intent == "workflow":
            is_highly_complex = True

    if not is_complex:
        return None

    try:
        from core.agent_factory import get_agent_factory

        factory = get_agent_factory(llm_router)

        context = {}
        if parsed_intent:
            context = {
                "intent": parsed_intent.intent,
                "targets": parsed_intent.targets,
                "params": parsed_intent.params,
            }

        # 高复杂度 → 分形递归分解
        if is_highly_complex:
            try:
                result = await factory.create_fractal_task(message, context)
                logger.info(f"FractalExecutor 完成任务: {result.get('data', {}).get('total_agents', 0)} agents")
                return result
            except Exception as e:
                logger.debug(f"FractalExecutor 失败，降级到普通 Agent: {e}")

        # 中复杂度 → LLM 动态生成 Agent
        agent = await factory.create_from_llm(message, context=context)
        result = await factory.execute_agent_task(
            agent.id,
            {"task": message, "context": context},
        )

        # 汇总结果
        outputs = []
        for r in result.get("results", []):
            if isinstance(r, dict) and "output" in r:
                outputs.append(r["output"])
            elif isinstance(r, dict) and "error" in r:
                outputs.append(f"[错误] {r['error']}")

        reply = "\n".join(outputs) if outputs else "Agent 任务已完成"
        logger.info(f"AgentFactory 完成任务: agent={agent.id}, role={agent.config.role.value}")

        # 清理完成的 Agent
        factory.terminate_agent(agent.id)

        return {
            "success": not any("error" in r for r in result.get("results", []) if isinstance(r, dict)),
            "reply": reply,
            "data": {
                "agent_id": agent.id,
                "agent_role": agent.config.role.value,
                "creation_mode": agent.creation_mode.value,
                "results": result.get("results", []),
            },
        }

    except Exception as e:
        logger.debug(f"AgentFactory 执行失败，降级到 scheduler: {e}")
        return None


async def _handle_scheduler_react(
    req: ChatRequest, session_id: str, scheduler, llm_router,
    parsed_intent=None,
) -> JSONResponse:
    """Scheduler ReAct Loop — 通用 tool_call 调度兜底"""
    async def node_executor(node_id: str, action: str, params: dict):
        target_node_dir = os.path.join(nodes_root, node_id)
        if not os.path.isdir(target_node_dir):
            for name in os.listdir(nodes_root):
                if name.startswith(node_id) or node_id in name:
                    target_node_dir = os.path.join(nodes_root, name)
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
        "devices": connection_manager.get_all_devices(),
        "executor": node_executor,
        "ws_sender": ws_sender,
        "device_id": req.device_id or "",
    }

    plan_result = await scheduler.plan_and_execute(
        req.message,
        llm_router,
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

    resp = UnifiedChatResponse(
        success=plan_result.get("success", True),
        response=full_reply,
        intent=parsed_intent.intent if parsed_intent else "action",
        confidence=parsed_intent.confidence if parsed_intent else 0.9,
        mode="agent_react",
        model=llm_router.get_default_model(),
        data={"steps": steps},
        session_id=session_id,
    )
    return JSONResponse(resp.to_json_response())


async def _handle_pure_chat(
    req: ChatRequest, session_id: str, llm_router
) -> JSONResponse:
    """纯 LLM 对话 (无工具调用)"""
    if llm_router.is_available():
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

            response = await llm_router.chat_completion(messages=messages, task_type="GENERAL")
            reply = response.choices[0].message.content or ""
            model_name = response.model if hasattr(response, "model") else llm_router.get_default_model()

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
            logger.warning(f"LLM chat failed: {e}")

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
