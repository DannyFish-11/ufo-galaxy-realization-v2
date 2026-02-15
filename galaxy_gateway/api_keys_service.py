"""
Galaxy - API Key 管理 API
提供 API Key 的增删改查接口
"""

import logging
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from enum import Enum

from core.api_key_manager import (
    get_api_key_manager, 
    APIKeyConfig, 
    APIKeyType
)

logger = logging.getLogger(__name__)

# 创建路由
router = APIRouter(prefix="/api/keys", tags=["API Keys"])

# ============================================================================
# 请求模型
# ============================================================================

class SetKeyRequest(BaseModel):
    key: str
    url: Optional[str] = None

class EnableRequest(BaseModel):
    enabled: bool

# ============================================================================
# API 端点
# ============================================================================

@router.get("/status")
async def get_status():
    """获取 API Key 状态"""
    manager = get_api_key_manager()
    return manager.get_status()

@router.get("/list")
async def list_keys(category: str = None):
    """列出所有 API Key 配置"""
    manager = get_api_key_manager()
    keys = manager.list_keys(category)
    
    # 隐藏实际的 key 值，只显示前4位
    result = []
    for config in keys:
        masked_key = ""
        if config.key:
            masked_key = config.key[:4] + "****" + config.key[-4:] if len(config.key) > 8 else "****"
        
        result.append({
            "key_type": config.key_type.value,
            "name": config.name,
            "key": masked_key,
            "has_key": bool(config.key),
            "url": config.url,
            "enabled": config.enabled,
            "description": config.description,
            "required": config.required,
            "category": config.category,
            "last_used": config.last_used
        })
    
    return result

@router.get("/{key_type}")
async def get_key_config(key_type: str):
    """获取单个 API Key 配置"""
    manager = get_api_key_manager()
    
    try:
        api_key_type = APIKeyType(key_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid key type: {key_type}")
    
    config = manager.get_config(api_key_type)
    if not config:
        raise HTTPException(status_code=404, detail="Key type not found")
    
    # 隐藏实际的 key 值
    masked_key = ""
    if config.key:
        masked_key = config.key[:4] + "****" + config.key[-4:] if len(config.key) > 8 else "****"
    
    return {
        "key_type": config.key_type.value,
        "name": config.name,
        "key": masked_key,
        "has_key": bool(config.key),
        "url": config.url,
        "enabled": config.enabled,
        "description": config.description,
        "required": config.required,
        "category": config.category
    }

@router.post("/{key_type}")
async def set_key(key_type: str, request: SetKeyRequest):
    """设置 API Key"""
    manager = get_api_key_manager()
    
    try:
        api_key_type = APIKeyType(key_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid key type: {key_type}")
    
    manager.set_key(api_key_type, request.key, request.url)
    
    return {"success": True, "message": f"API Key {key_type} 已设置"}

@router.post("/{key_type}/enable")
async def enable_key(key_type: str, request: EnableRequest):
    """启用/禁用 API Key"""
    manager = get_api_key_manager()
    
    try:
        api_key_type = APIKeyType(key_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid key type: {key_type}")
    
    manager.enable(api_key_type, request.enabled)
    
    return {"success": True, "message": f"API Key {key_type} 已{'启用' if request.enabled else '禁用'}"}

@router.delete("/{key_type}")
async def delete_key(key_type: str):
    """删除 API Key"""
    manager = get_api_key_manager()
    
    try:
        api_key_type = APIKeyType(key_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid key type: {key_type}")
    
    manager.set_key(api_key_type, "")
    
    return {"success": True, "message": f"API Key {key_type} 已删除"}

@router.get("/export/env")
async def export_env():
    """导出为环境变量格式"""
    manager = get_api_key_manager()
    return manager.export_to_env()

@router.get("/categories")
async def get_categories():
    """获取 API Key 分类"""
    return {
        "categories": [
            {"id": "llm", "name": "LLM 模型", "description": "大语言模型 API"},
            {"id": "tool", "name": "工具服务", "description": "搜索、天气、翻译等工具"},
            {"id": "storage", "name": "存储服务", "description": "数据库、缓存等"},
            {"id": "media", "name": "媒体生成", "description": "视频、图片生成"},
        ]
    }

# ============================================================================
# 页面路由
# ============================================================================

from fastapi.responses import HTMLResponse
from pathlib import Path

@router.get("/page", response_class=HTMLResponse)
async def api_keys_page():
    """API Key 管理页面"""
    static_path = Path(__file__).parent.parent / "galaxy_gateway" / "static" / "api_keys.html"
    if static_path.exists():
        return HTMLResponse(content=static_path.read_text(encoding='utf-8'))
    return {"error": "API Keys page not found"}
