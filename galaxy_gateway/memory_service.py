"""
Galaxy - 记忆服务 API
提供记忆管理的 HTTP 接口
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.memory import get_memory_manager

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter(prefix="/api/memory", tags=["Memory"])

# ============================================================================
# 请求模型
# ============================================================================

class AddMemoryRequest(BaseModel):
    content: str
    type: str = "fact"
    importance: float = 0.5

class AddPreferenceRequest(BaseModel):
    key: str
    value: Any

# ============================================================================
# API 端点
# ============================================================================

@router.get("/stats")
async def get_stats():
    """获取记忆统计"""
    manager = get_memory_manager()
    return manager.get_stats()

@router.get("/history")
async def get_history(session_id: str = "default", limit: int = 50):
    """获取对话历史"""
    manager = get_memory_manager()
    history = manager.get_history(session_id, limit)
    return history

@router.get("/memories")
async def get_memories(limit: int = 50):
    """获取长期记忆"""
    manager = get_memory_manager()
    memories = manager.get_recent_memories(limit)
    return memories

@router.post("/memories")
async def add_memory(request: AddMemoryRequest):
    """添加长期记忆"""
    manager = get_memory_manager()
    memory_id = manager.add_memory(
        content=request.content,
        memory_type=request.type,
        importance=request.importance
    )
    return {"success": True, "memory_id": memory_id}

@router.get("/search")
async def search_memories(q: str, limit: int = 10):
    """搜索记忆"""
    manager = get_memory_manager()
    results = manager.search_memories(q, limit)
    return results

@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: str):
    """删除记忆"""
    manager = get_memory_manager()
    if memory_id in manager.long_term_memories:
        del manager.long_term_memories[memory_id]
        manager._save_long_term_memories()
        return {"success": True}
    raise HTTPException(status_code=404, detail="Memory not found")

@router.get("/preferences")
async def get_preferences():
    """获取用户偏好"""
    manager = get_memory_manager()
    return manager.get_all_preferences()

@router.post("/preferences")
async def set_preference(request: AddPreferenceRequest):
    """设置用户偏好"""
    manager = get_memory_manager()
    manager.set_preference(request.key, request.value)
    return {"success": True}

@router.delete("/preferences/{key}")
async def delete_preference(key: str):
    """删除用户偏好"""
    manager = get_memory_manager()
    if key in manager.user_preferences:
        del manager.user_preferences[key]
        manager._save_user_preferences()
        return {"success": True}
    raise HTTPException(status_code=404, detail="Preference not found")

# ============================================================================
# 页面路由
# ============================================================================

from fastapi.responses import HTMLResponse
from pathlib import Path

@router.get("/page", response_class=HTMLResponse)
async def memory_page():
    """记忆管理页面"""
    static_path = Path(__file__).parent / "static" / "memory.html"
    if static_path.exists():
        return HTMLResponse(content=static_path.read_text(encoding='utf-8'))
    return {"error": "Memory page not found"}
