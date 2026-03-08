"""
Galaxy - AI Intent Routes
================================

Routes:
  POST   /api/v1/ai/intent                       - AI 意图解析
  POST   /api/v1/ai/conversation                 - 添加对话轮次
  GET    /api/v1/ai/conversation/{session_id}    - 对话上下文
  GET    /api/v1/ai/recommendations/{session_id} - 智能推荐
  DELETE /api/v1/ai/conversation/{session_id}    - 清除对话记忆
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.routes._shared import registered_devices, task_queue
from core.routes._models import AIIntentRequest, ConversationRequest

logger = logging.getLogger("Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create AI intent and conversation routes router."""
    router = APIRouter()

    from core.ai_intent import (
        get_intent_parser, get_conversation_memory, get_smart_recommender,
    )

    intent_parser = get_intent_parser()
    conversation_memory = get_conversation_memory()
    smart_recommender = get_smart_recommender()

    @router.post("/api/v1/ai/intent")
    async def parse_intent(req: AIIntentRequest):
        """
        AI 意图解析

        自然语言 → 结构化命令
        双级解析：规则引擎 (< 1ms) + LLM (高精度)
        """
        context = req.context
        if req.session_id:
            history = await conversation_memory.get_context(req.session_id)
            context["history"] = history

        parsed = await intent_parser.parse(req.text, context)
        return JSONResponse({
            "success": True,
            **parsed.to_dict(),
        })

    @router.post("/api/v1/ai/conversation")
    async def manage_conversation(req: ConversationRequest):
        """添加对话轮次到记忆系统"""
        await conversation_memory.add_turn(
            session_id=req.session_id,
            role=req.role,
            content=req.content,
            metadata=req.metadata,
        )
        return JSONResponse({
            "success": True,
            "session_id": req.session_id,
            "turns": len(await conversation_memory.get_context(req.session_id, max_turns=100)),
        })

    @router.get("/api/v1/ai/conversation/{session_id}")
    async def get_conversation_context(session_id: str, max_turns: int = 10):
        """获取对话上下文"""
        context = await conversation_memory.get_context(session_id, max_turns)
        summary = await conversation_memory.get_summary(session_id)
        return JSONResponse({
            "session_id": session_id,
            "context": context,
            "summary": summary,
        })

    @router.get("/api/v1/ai/recommendations/{session_id}")
    async def get_recommendations(session_id: str):
        """获取智能推荐"""
        current_context = {
            "devices": registered_devices,
            "tasks": {k: v.get("status") for k, v in task_queue.items()},
        }
        recs = await smart_recommender.get_recommendations(session_id, current_context)
        return JSONResponse({
            "session_id": session_id,
            "recommendations": recs,
        })

    @router.delete("/api/v1/ai/conversation/{session_id}")
    async def clear_conversation(session_id: str):
        """清除对话记忆"""
        await conversation_memory.clear_session(session_id)
        return JSONResponse({"success": True, "message": f"Session {session_id} cleared"})

    return router
