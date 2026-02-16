"""
Galaxy 一体化系统 API
====================
暴露 MCP、Skills、HAL 的统一接口
"""

import logging
from typing import Dict, Any, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Integrated System"])

# ============================================================================
# 请求模型
# ============================================================================

class ExecuteRequest(BaseModel):
    """执行请求"""
    capability: str
    params: Dict[str, Any] = {}

class MCPServerRequest(BaseModel):
    """MCP 服务器请求"""
    server_id: str
    config: Dict[str, Any] = {}

class SkillRequest(BaseModel):
    """技能请求"""
    skill_id: str
    action: str
    params: Dict[str, Any] = {}

class DeviceRequest(BaseModel):
    """设备请求"""
    device_id: str
    action: str
    params: Dict[str, Any] = {}

# ============================================================================
# 系统状态 API
# ============================================================================

@router.get("/status")
async def get_system_status():
    """获取一体化系统状态"""
    try:
        from core.integrated_system import get_capability_router
        router = get_capability_router()
        return router.get_status()
    except Exception as e:
        return {"error": str(e), "available": False}

@router.get("/capabilities")
async def list_capabilities():
    """列出所有能力"""
    try:
        from core.integrated_system import get_capability_router
        router = get_capability_router()
        capabilities = router.get_capabilities()
        return {
            "total": len(capabilities),
            "capabilities": capabilities
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# 统一执行 API
# ============================================================================

@router.post("/execute")
async def execute_capability(request: ExecuteRequest):
    """执行能力 - 统一入口"""
    try:
        from core.integrated_system import get_capability_router
        router = get_capability_router()
        result = await router.execute(request.capability, request.params)
        return {
            **result,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# MCP API
# ============================================================================

@router.get("/mcp/servers")
async def list_mcp_servers():
    """列出 MCP 服务器"""
    try:
        from core.mcp_layer import get_mcp_layer
        mcp = get_mcp_layer()
        return {
            "total": len(mcp.servers),
            "servers": [s.to_dict() for s in mcp.get_servers()]
        }
    except Exception as e:
        return {"total": 0, "servers": [], "error": str(e)}

@router.get("/mcp/tools")
async def list_mcp_tools(category: str = None):
    """列出 MCP 工具"""
    try:
        from core.mcp_layer import get_mcp_layer
        mcp = get_mcp_layer()
        tools = mcp.get_tools(category)
        return {
            "total": len(tools),
            "tools": [t.to_dict() for t in tools]
        }
    except Exception as e:
        return {"total": 0, "tools": [], "error": str(e)}

@router.post("/mcp/register")
async def register_mcp_server(request: MCPServerRequest):
    """注册 MCP 服务器"""
    try:
        from core.mcp_layer import get_mcp_layer
        mcp = get_mcp_layer()
        success = mcp.register_server(request.config)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# Skills API
# ============================================================================

@router.get("/skills")
async def list_skills(category: str = None):
    """列出技能"""
    try:
        from core.skills_layer import get_skills_layer
        skills = get_skills_layer()
        skill_list = skills.get_skills(category)
        return {
            "total": len(skill_list),
            "skills": [s.to_dict() for s in skill_list]
        }
    except Exception as e:
        return {"total": 0, "skills": [], "error": str(e)}

@router.post("/skills/execute")
async def execute_skill(request: SkillRequest):
    """执行技能"""
    try:
        from core.skills_layer import get_skills_layer
        skills = get_skills_layer()
        result = await skills.execute(request.skill_id, request.action, request.params)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/skills/install")
async def install_skill(request: Dict[str, Any]):
    """安装技能"""
    try:
        from core.skills_layer import get_skills_layer
        skills = get_skills_layer()
        success = skills.install_skill(request)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# HAL API
# ============================================================================

@router.get("/devices")
async def list_devices():
    """列出设备"""
    try:
        from core.hal import get_hal
        hal = get_hal()
        devices = hal.get_devices()
        return {
            "total": len(devices),
            "devices": [d.info.to_dict() for d in devices]
        }
    except Exception as e:
        return {"total": 0, "devices": [], "error": str(e)}

@router.post("/devices/connect")
async def connect_device(request: Dict[str, Any]):
    """连接设备"""
    try:
        from core.hal import get_hal
        hal = get_hal()
        device = hal.get_device(request.get("device_id"))
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        connected = await device.connect()
        return {
            "success": connected,
            "device": device.info.to_dict()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/devices/execute")
async def execute_device_action(request: DeviceRequest):
    """执行设备操作"""
    try:
        from core.integrated_system import get_capability_router
        router = get_capability_router()
        capability = f"device.{request.device_id}.{request.action}"
        result = await router.execute(capability, request.params)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# 数字生命卡 API
# ============================================================================

@router.get("/digital-life/status")
async def get_digital_life_status():
    """获取数字生命卡状态"""
    try:
        from core.hal import get_hal
        hal = get_hal()
        device = hal.get_device("digital_life_card")
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        status = await device.get_status()
        return {"success": True, "status": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/digital-life/read")
async def read_digital_life_memory(request: Dict[str, Any]):
    """读取数字生命卡记忆"""
    try:
        from core.hal import get_hal
        hal = get_hal()
        device = hal.get_device("digital_life_card")
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        key = request.get("key", "default")
        data = await device.read_memory(key)
        return {"success": data is not None, "data": data.decode() if data else None}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/digital-life/write")
async def write_digital_life_memory(request: Dict[str, Any]):
    """写入数字生命卡记忆"""
    try:
        from core.hal import get_hal
        hal = get_hal()
        device = hal.get_device("digital_life_card")
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        key = request.get("key", "default")
        data = request.get("data", "").encode()
        success = await device.write_memory(key, data)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============================================================================
# 苯苯机械狗 API
# ============================================================================

@router.get("/benben/status")
async def get_benben_status():
    """获取苯苯机械狗状态"""
    try:
        from core.hal import get_hal
        hal = get_hal()
        device = hal.get_device("benben_dog")
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        status = await device.get_status()
        return {"success": True, "status": status}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/benben/move")
async def move_benben(request: Dict[str, Any]):
    """控制苯苯移动"""
    try:
        from core.hal import get_hal
        hal = get_hal()
        device = hal.get_device("benben_dog")
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        direction = request.get("direction", "forward")
        distance = request.get("distance", 1.0)
        success = await device.move(direction, distance)
        return {"success": success, "direction": direction, "distance": distance}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/benben/turn")
async def turn_benben(request: Dict[str, Any]):
    """控制苯苯转向"""
    try:
        from core.hal import get_hal
        hal = get_hal()
        device = hal.get_device("benben_dog")
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        angle = request.get("angle", 0)
        success = await device.turn(angle)
        return {"success": success, "angle": angle}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/benben/speak")
async def benben_speak(request: Dict[str, Any]):
    """苯苯说话"""
    try:
        from core.hal import get_hal
        hal = get_hal()
        device = hal.get_device("benben_dog")
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        
        text = request.get("text", "")
        success = await device.speak(text)
        return {"success": success, "text": text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
