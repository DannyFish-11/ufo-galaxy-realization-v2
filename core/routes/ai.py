"""
Galaxy - AI Intent Routes
================================

Routes:
  POST   /api/v1/ai/intent                       - AI 意图解析
  POST   /api/v1/ai/conversation                 - 添加对话轮次
  GET    /api/v1/ai/conversation/{session_id}    - 对话上下文
  GET    /api/v1/ai/recommendations/{session_id} - 智能推荐
  DELETE /api/v1/ai/conversation/{session_id}    - 清除对话记忆
  POST   /api/v1/agents/twin                     - 孪生指挥创建
  POST   /api/v1/agents/swarm                    - Agent Swarm 创建
  GET    /api/v1/agents/{agent_id}/children      - Agent 子树
  POST   /api/v1/agents/{agent_id}/split         - 手动触发 Agent 分裂
"""

import logging
import uuid
from typing import Dict, List, Optional

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

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
        if parsed is None:
            return JSONResponse(
                {"success": False, "error": "Intent parse failed"},
                status_code=422,
            )
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

    # ─────── Agent 增强端点 ─────────

    class TwinCreateRequest(BaseModel):
        task: str = Field(..., description="要执行的任务描述")
        strategy: str = Field(default="SPECIALIZED", description="团队策略: PARALLEL/SPECIALIZED/SWARM")
        member_count: int = Field(default=2, ge=1, le=10, description="团队成员数")
        providers: List[str] = Field(default_factory=list, description="指定使用的 LLM 提供商列表")

    class SwarmCreateRequest(BaseModel):
        task: str = Field(..., description="要执行的任务描述")
        agent_count: int = Field(default=3, ge=1, le=20, description="Swarm Agent 数量")
        template: str = Field(default="general", description="Agent 模板名称")

    class AgentSplitRequest(BaseModel):
        subtasks: List[str] = Field(..., description="分裂后的子任务列表")

    @router.post("/api/v1/agents/twin")
    async def create_twin_command(req: TwinCreateRequest):
        """孪生指挥创建 — 使用 SPECIALIZED 策略让多个 LLM 协作完成任务"""
        try:
            from core.agent_team import TeamManager, TeamStrategy
            from core.agent_factory import get_agent_factory
            from core.llm.route_authority import get_llm_route_authority

            strategy_map = {
                "PARALLEL": TeamStrategy.PARALLEL,
                "SPECIALIZED": TeamStrategy.SPECIALIZED,
                "SWARM": TeamStrategy.SWARM,
            }
            strategy = strategy_map.get(req.strategy.upper(), TeamStrategy.SPECIALIZED)

            llm_router = get_llm_route_authority().execution_router
            factory = get_agent_factory(llm_router)
            team_manager = TeamManager(
                agent_factory=factory, llm_router=llm_router,
            )

            result = await team_manager.execute_team_task(
                task=req.task,
                strategy=strategy,
                member_count=req.member_count,
                providers=req.providers if req.providers else None,
            )

            return JSONResponse({
                "success": True,
                "strategy": req.strategy,
                "member_count": req.member_count,
                "result": result if isinstance(result, dict) else {"response": str(result)},
            })
        except ImportError:
            raise HTTPException(status_code=501, detail="agent_team 模块不可用")
        except Exception as e:
            logger.error(f"孪生指挥创建失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)}, status_code=500
            )

    @router.post("/api/v1/agents/swarm")
    async def create_agent_swarm(req: SwarmCreateRequest):
        """Agent Swarm 创建 — 批量同类 Agent 并行执行，投票/合并结果"""
        try:
            from core.agent_team import TeamManager, TeamStrategy
            from core.agent_factory import get_agent_factory
            from core.llm.route_authority import get_llm_route_authority

            llm_router = get_llm_route_authority().execution_router
            factory = get_agent_factory(llm_router)
            team_manager = TeamManager(
                agent_factory=factory, llm_router=llm_router,
            )

            result = await team_manager.execute_team_task(
                task=req.task,
                strategy=TeamStrategy.SWARM,
                member_count=req.agent_count,
            )

            return JSONResponse({
                "success": True,
                "strategy": "SWARM",
                "agent_count": req.agent_count,
                "template": req.template,
                "result": result if isinstance(result, dict) else {"response": str(result)},
            })
        except ImportError:
            raise HTTPException(status_code=501, detail="agent_team 模块不可用")
        except Exception as e:
            logger.error(f"Agent Swarm 创建失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)}, status_code=500
            )

    @router.get("/api/v1/agents/{agent_id}/children")
    async def get_agent_children(agent_id: str):
        """获取 Agent 子树 — 查看 Agent 创建的子 Agent"""
        try:
            from core.agent_factory import get_agent_factory

            factory = get_agent_factory()
            children = []
            for aid, agent in factory._agents.items():
                parent = getattr(agent, "parent_id", None)
                if parent == agent_id:
                    children.append({
                        "agent_id": aid,
                        "name": getattr(agent, "name", aid),
                        "status": getattr(agent, "status", "unknown"),
                        "template": getattr(agent, "template_name", ""),
                    })

            return JSONResponse({
                "agent_id": agent_id,
                "children": children,
                "count": len(children),
            })
        except ImportError:
            raise HTTPException(status_code=501, detail="agent_factory 模块不可用")
        except Exception as e:
            logger.error(f"获取 Agent 子树失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)}, status_code=500
            )

    @router.post("/api/v1/agents/{agent_id}/split")
    async def split_agent(agent_id: str, req: AgentSplitRequest):
        """手动触发 Agent 分裂 — 将当前任务拆分为子任务并创建子 Agent"""
        try:
            from core.agent_factory import get_agent_factory

            factory = get_agent_factory()
            child_agents = []

            for subtask in req.subtasks:
                child_id = f"{agent_id}-child-{uuid.uuid4().hex[:6]}"
                child = await factory.create_agent(
                    name=f"Split-{child_id}",
                    task=subtask,
                    parent_id=agent_id,
                )
                child_agents.append({
                    "agent_id": child_id,
                    "task": subtask,
                    "status": "created",
                })

            return JSONResponse({
                "success": True,
                "parent_agent_id": agent_id,
                "children": child_agents,
                "split_count": len(child_agents),
            })
        except ImportError:
            raise HTTPException(status_code=501, detail="agent_factory 模块不可用")
        except Exception as e:
            logger.error(f"Agent 分裂失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)}, status_code=500
            )

    # ─────── Agent 辩论推理端点 ─────────

    class DebateRequest(BaseModel):
        question: str = Field(..., description="需要辩论推理的问题")
        strategies: List[str] = Field(
            default_factory=lambda: ["COT", "TOT"],
            description="辩论策略列表: COT/TOT/PAL/CRITIQUE/RETRIEVAL",
        )
        rounds: int = Field(default=3, ge=1, le=10, description="辩论轮次")

    @router.post("/api/v1/agents/debate")
    async def run_agent_debate(req: DebateRequest):
        """多 Agent 辩论式推理 — 调用 Node_126_AgentSwarm 的锦标赛辩论引擎"""
        try:
            from core.port_config import get_service_port
            port = get_service_port("agent_swarm")
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"http://localhost:{port}/debate",
                    json={
                        "question": req.question,
                        "strategies": req.strategies,
                        "rounds": req.rounds,
                    },
                )
                if resp.status_code == 200:
                    return resp.json()
                return JSONResponse(
                    {"success": False, "error": f"Node_126 返回 HTTP {resp.status_code}"},
                    status_code=resp.status_code,
                )
        except httpx.ConnectError:
            raise HTTPException(
                status_code=503,
                detail="Node_126_AgentSwarm 服务不可达，请确认已启动",
            )
        except Exception as e:
            logger.error(f"Agent 辩论推理失败: {e}")
            return JSONResponse(
                {"success": False, "error": str(e)}, status_code=500
            )

    return router
