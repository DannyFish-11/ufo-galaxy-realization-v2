"""
Galaxy - 群智能 API
提供统一的交互入口
"""

import logging
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime

from core.swarm_core import get_swarm_core, SwarmState

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter(tags=["Galaxy Swarm"])

# ============================================================================
# 请求模型
# ============================================================================

class InteractRequest(BaseModel):
    """交互请求"""
    input: str
    context: Dict[str, Any] = {}
    mode: str = "auto"  # auto, chat, command, search

class CapabilityRequest(BaseModel):
    """能力请求"""
    category: str = None
    capability_id: str = None
    params: Dict[str, Any] = {}

class LearnRequest(BaseModel):
    """学习请求"""
    experience: Dict[str, Any]
    feedback: str = ""

# ============================================================================
# 群智能 API
# ============================================================================

@router.get("/status")
async def get_swarm_status():
    """获取群智能状态"""
    core = get_swarm_core()
    return core.get_status()

@router.post("/interact")
async def interact(request: InteractRequest):
    """
    统一交互入口
    所有与 Galaxy 的交互都通过这个接口
    """
    core = get_swarm_core()
    
    result = await core.interact(request.input)
    
    return {
        "success": result["success"],
        "response": result["output"],
        "intent": result.get("intent", "unknown"),
        "capability": result.get("capability", "unknown"),
        "state": result["state"],
        "timestamp": datetime.now().isoformat()
    }

@router.post("/chat")
async def chat(request: InteractRequest):
    """聊天模式"""
    core = get_swarm_core()
    
    result = await core.interact(request.input)
    
    return {
        "success": result["success"],
        "message": result["output"],
        "timestamp": datetime.now().isoformat()
    }

@router.get("/capabilities")
async def list_capabilities(category: str = None):
    """列出所有能力"""
    core = get_swarm_core()
    capabilities = await core.capability_pool.get_capabilities(category)
    
    return {
        "total": len(capabilities),
        "capabilities": [cap.to_dict() for cap in capabilities]
    }

@router.get("/capabilities/{capability_id}")
async def get_capability(capability_id: str):
    """获取能力详情"""
    core = get_swarm_core()
    
    if capability_id not in core.capability_pool.capabilities:
        raise HTTPException(status_code=404, detail="Capability not found")
    
    cap = core.capability_pool.capabilities[capability_id]
    return cap.to_dict()

@router.post("/capabilities/{capability_id}/execute")
async def execute_capability(capability_id: str, request: CapabilityRequest):
    """执行能力"""
    core = get_swarm_core()
    
    result = await core.capability_pool.execute(capability_id, request.params)
    
    return {
        "success": result.get("success", False),
        "result": result.get("result", ""),
        "capability": capability_id,
        "timestamp": datetime.now().isoformat()
    }

@router.post("/learn")
async def learn(request: LearnRequest):
    """学习"""
    core = get_swarm_core()
    
    await core.learn(request.experience)
    
    return {
        "success": True,
        "message": "学习完成",
        "timestamp": datetime.now().isoformat()
    }

@router.get("/stats")
async def get_stats():
    """获取统计信息"""
    core = get_swarm_core()
    status = core.get_status()
    
    return {
        "name": status["name"],
        "version": status["version"],
        "state": status["state"],
        "total_interactions": status["stats"]["total_interactions"],
        "successful_interactions": status["stats"]["successful_interactions"],
        "success_rate": status["stats"]["successful_interactions"] / max(status["stats"]["total_interactions"], 1),
        "uptime": datetime.now().isoformat(),
        "capabilities_count": status["capabilities"]
    }

# ============================================================================
# MCP 兼容接口
# ============================================================================

@router.get("/mcp/tools")
async def list_mcp_tools():
    """列出 MCP 工具"""
    core = get_swarm_core()
    capabilities = await core.capability_pool.get_capabilities()
    
    tools = []
    for cap in capabilities:
        tools.append({
            "name": cap.id,
            "description": cap.description,
            "inputSchema": cap.input_schema or {"type": "object", "properties": {}}
        })
    
    return {"tools": tools}

@router.post("/mcp/call")
async def call_mcp_tool(request: Dict[str, Any]):
    """调用 MCP 工具"""
    tool_name = request.get("tool", "")
    params = request.get("params", {})
    
    core = get_swarm_core()
    
    if tool_name not in core.capability_pool.capabilities:
        raise HTTPException(status_code=404, detail=f"Tool not found: {tool_name}")
    
    result = await core.capability_pool.execute(tool_name, params)
    
    return {
        "success": result.get("success", False),
        "result": result.get("result", ""),
        "tool": tool_name
    }
