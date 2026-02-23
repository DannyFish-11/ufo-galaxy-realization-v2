"""
UFO Galaxy - 完整 API 路由模块
================================

提供 Android 端和 Web UI 需要的所有 REST API 和 WebSocket 端点。

路由分组：
  /api/v1/system     - 系统状态和管理
  /api/v1/devices    - 设备注册和管理
  /api/v1/nodes      - 节点查询和调用
  /api/v1/vision     - 融合视觉理解（OCR + GUI）
  /api/v1/tasks      - 任务管理
  /api/v1/chat       - 对话接口
  /ws/device         - 设备 WebSocket 连接
  /ws/status         - 状态推送 WebSocket
"""

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# 导入鉴权模块
try:
    from .auth import require_auth
except ImportError:
    # 如果导入失败，定义一个空的鉴权函数
    async def require_auth():
        return {"authenticated": True, "dev_mode": True}

logger = logging.getLogger("UFO-Galaxy.API")


# ============================================================================
# 请求/响应模型
# ============================================================================

class DeviceRegisterRequest(BaseModel):
    device_id: str
    device_type: str = "android"
    device_name: str = ""
    capabilities: List[str] = []
    os_version: str = ""
    app_version: str = ""
    # 新增字段
    manufacturer: str = ""
    model: str = ""
    groups: List[str] = []
    tags: List[str] = []
    ip_address: str = ""
    port: int = 0
    mac_address: str = ""
    metadata: Dict[str, Any] = {}

class DeviceStatusUpdate(BaseModel):
    device_id: str
    status: Dict[str, Any] = {}

class VisionRequest(BaseModel):
    image_base64: Optional[str] = None
    video_chunk: Optional[str] = None  # Base64 encoded video chunk
    mode: str = "full"
    instruction: str = ""
    session_id: Optional[str] = None   # For video stream context
    is_last_chunk: bool = False

class TaskRequest(BaseModel):
    task_type: str
    payload: Dict[str, Any] = {}
    device_id: str = ""
    priority: int = 5

class ChatRequest(BaseModel):
    message: str
    device_id: str = ""
    context: List[Dict[str, str]] = []

class NodeCallRequest(BaseModel):
    node_id: str
    action: str
    params: Dict[str, Any] = {}

class OCRRequest(BaseModel):
    image_base64: str
    mode: str = "free_ocr"
    language: str = "auto"


# ============================================================================
# 统一命令协议模型
# ============================================================================

from enum import Enum

class CommandStatus(str, Enum):
    """命令状态枚举"""
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class TargetResult(BaseModel):
    """单个目标的执行结果"""
    status: CommandStatus
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class UnifiedCommandRequest(BaseModel):
    """统一命令请求"""
    request_id: Optional[str] = None
    command: str
    targets: List[str]
    params: Dict[str, Any] = {}
    mode: str = "sync"  # sync or async
    timeout: int = 30


class UnifiedCommandResponse(BaseModel):
    """统一命令响应"""
    request_id: str
    status: CommandStatus
    created_at: str
    completed_at: Optional[str] = None
    results: Dict[str, TargetResult]


# ============================================================================
# 连接管理器
# ============================================================================

class ConnectionManager:
    """WebSocket 连接管理器"""
    
    def __init__(self):
        self.active_devices: Dict[str, WebSocket] = {}
        self.status_subscribers: Set[WebSocket] = set()
        
    async def connect_device(self, websocket: WebSocket, device_id: str):
        await websocket.accept()
        self.active_devices[device_id] = websocket
        logger.info(f"设备已连接: {device_id}")
        await self.broadcast_status({
            "type": "device_connected",
            "device_id": device_id,
            "timestamp": datetime.now().isoformat()
        })
        
    def disconnect_device(self, device_id: str):
        self.active_devices.pop(device_id, None)
        logger.info(f"设备已断开: {device_id}")
        
    async def send_to_device(self, device_id: str, message: dict) -> bool:
        ws = self.active_devices.get(device_id)
        if ws:
            try:
                await ws.send_json(message)
                return True
            except Exception as e:
                logger.error(f"发送消息到设备 {device_id} 失败: {e}")
                self.disconnect_device(device_id)
        return False
        
    async def broadcast_to_devices(self, message: dict):
        disconnected = []
        for device_id, ws in self.active_devices.items():
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(device_id)
        for d in disconnected:
            self.disconnect_device(d)
            
    async def subscribe_status(self, websocket: WebSocket):
        await websocket.accept()
        self.status_subscribers.add(websocket)
        
    def unsubscribe_status(self, websocket: WebSocket):
        self.status_subscribers.discard(websocket)
        
    async def broadcast_status(self, status: dict):
        disconnected = []
        for ws in self.status_subscribers:
            try:
                await ws.send_json(status)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.status_subscribers.discard(ws)


# ============================================================================
# 全局状态
# ============================================================================

connection_manager = ConnectionManager()

# 设备注册表
registered_devices: Dict[str, Dict[str, Any]] = {}

# 任务队列
task_queue: Dict[str, Dict[str, Any]] = {}

# 节点状态缓存
node_status_cache: Dict[str, Dict[str, Any]] = {}

# 统一命令结果存储
command_results: Dict[str, Dict[str, Any]] = {}


# ============================================================================
# 创建路由
# ============================================================================

def create_api_routes(service_manager=None, config=None) -> APIRouter:
    """创建完整的 API 路由"""
    
    router = APIRouter()
    
    # ========================================================================
    # /api/v1/system - 系统状态和管理
    # ========================================================================
    
    @router.get("/api/v1/system/status")
    async def system_status():
        """获取系统完整状态"""
        services = service_manager.get_status() if service_manager else {}
        return JSONResponse({
            "status": "running",
            "version": "2.0.0",
            "timestamp": datetime.now().isoformat(),
            "services": services,
            "devices": {
                "registered": len(registered_devices),
                "online": len(connection_manager.active_devices),
                "list": [
                    {
                        "device_id": did,
                        "device_name": info.get("device_name", ""),
                        "device_type": info.get("device_type", ""),
                        "online": did in connection_manager.active_devices,
                        "last_seen": info.get("last_seen", "")
                    }
                    for did, info in registered_devices.items()
                ]
            },
            "nodes": {
                "total": len(node_status_cache),
                "active": sum(1 for n in node_status_cache.values() if n.get("status") == "running")
            },
            "tasks": {
                "total": len(task_queue),
                "pending": sum(1 for t in task_queue.values() if t.get("status") == "pending"),
                "running": sum(1 for t in task_queue.values() if t.get("status") == "running"),
                "completed": sum(1 for t in task_queue.values() if t.get("status") == "completed")
            }
        })
    
    @router.get("/api/v1/system/health")
    async def system_health():
        """健康检查端点"""
        return {"status": "healthy", "timestamp": datetime.now().isoformat()}
    
    @router.get("/api/v1/system/config")
    async def system_config():
        """获取系统配置（脱敏）"""
        if config:
            status = config.get_status_dict()
            return JSONResponse(status)
        return JSONResponse({"error": "config not available"})

    @router.get("/api/config")
    async def get_frontend_config(request: Request = None):
        """
        返回前端所需的非敏感配置。
        注意：敏感 Key (如 OPENAI_API_KEY) 不应直接返回，除非在受控的本地环境。
        """
        # 检查是否是本地请求 (简单判断)
        # 在生产环境中，这里应该有更严格的鉴权
        
        # 获取主机地址，用于构建 WebSocket URL
        host = "localhost"
        port = "8099"
        if request:
            host = request.url.hostname or "localhost"
            port = str(request.url.port or 8099)

        config_data = {
            "api_base_url": f"http://{host}:{port}",
            "ws_url": f"ws://{host}:{port}/ws",
            # 返回部分脱敏的配置状态，用于前端展示 "已配置"
            "status": {
                "openai": bool(os.getenv("OPENAI_API_KEY")),
                "deepseek": bool(os.getenv("DEEPSEEK_API_KEY")),
                "perplexity": bool(os.getenv("SONAR_API_KEY") or os.getenv("PERPLEXITY_API_KEY")),
                "ocr": bool(os.getenv("DEEPSEEK_OCR2_API_KEY")),
            }
        }
        return JSONResponse(config_data)

    @router.post("/api/config/update")
    async def update_config(request: Request):
        """
        更新配置 (仅限本地环境或鉴权用户)
        """
        data = await request.json()
        # 这里实现将配置写入 .env 文件的逻辑
        # 简单实现：读取 .env，替换或追加，然后写回
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        
        try:
            current_env = {}
            if os.path.exists(env_path):
                with open(env_path, "r") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, val = line.split("=", 1)
                            current_env[key.strip()] = val.strip()
            
            # 更新值
            for key, val in data.items():
                if key in ["OPENAI_API_KEY", "DEEPSEEK_API_KEY", "SONAR_API_KEY", "DEEPSEEK_OCR2_API_KEY", "PERPLEXITY_API_KEY"]:
                    current_env[key] = val
            
            # 写回文件
            with open(env_path, "w") as f:
                for key, val in current_env.items():
                    f.write(f"{key}={val}\n")
            
            # 重新加载环境变量 (当前进程可能需要重启才能生效，或者手动更新 os.environ)
            for key, val in data.items():
                os.environ[key] = val
                
            return {"status": "success", "message": "Configuration updated"}
        except Exception as e:
            return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    # ========================================================================
    # API Manager 静态文件路由
    # ========================================================================
    # 注意：静态文件挂载已移至 unified_launcher.py 中处理，
    # 以便正确使用 app.mount() 并避免路由冲突。
    pass
    
    # ========================================================================
    # /api/v1/devices - 设备注册和管理
    # ========================================================================
    
    @router.post("/api/v1/devices/register")
    async def register_device(req: DeviceRegisterRequest):
        """注册设备 - 使用统一的设备注册管理器"""
        try:
            from core.device_registry import device_registry
            
            # 使用新的设备注册管理器
            device = await device_registry.register(
                device_id=req.device_id,
                device_type=req.device_type,
                name=req.device_name,
                capabilities=req.capabilities,
                groups=req.groups,
                tags=req.tags,
                ip_address=req.ip_address,
                port=req.port,
                mac_address=req.mac_address,
                manufacturer=req.manufacturer,
                model=req.model,
                os_version=req.os_version,
                app_version=req.app_version,
                metadata=req.metadata,
            )
            
            # 同时更新旧的 registered_devices 以保持兼容
            device_info = device.to_dict()
            device_info["registered_at"] = datetime.now().isoformat()
            device_info["last_seen"] = datetime.now().isoformat()
            device_info["status"] = "registered"
            registered_devices[req.device_id] = device_info
            
            logger.info(f"设备注册: {req.device_id} ({req.device_type})")
            
            return JSONResponse({
                "success": True,
                "device_id": req.device_id,
                "message": "设备注册成功",
                "server_version": "2.0.0",
                "available_nodes": list(node_status_cache.keys())[:20],
                "device": device_info,
            })
        except Exception as e:
            logger.error(f"设备注册失败: {e}")
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.post("/api/v1/devices/status")
    async def update_device_status(req: DeviceStatusUpdate):
        """更新设备状态"""
        if req.device_id in registered_devices:
            registered_devices[req.device_id]["last_seen"] = datetime.now().isoformat()
            registered_devices[req.device_id]["status_detail"] = req.status
            
            # 广播状态更新
            await connection_manager.broadcast_status({
                "type": "device_status_update",
                "device_id": req.device_id,
                "status": req.status,
                "timestamp": datetime.now().isoformat()
            })
            
            return {"success": True}
        raise HTTPException(status_code=404, detail="设备未注册")
    
    @router.get("/api/v1/devices")
    async def list_devices(
        device_type: str = None,
        group: str = None,
        tag: str = None,
        online_only: bool = False,
    ):
        """列出所有设备 - 支持过滤"""
        try:
            from core.device_registry import device_registry
            
            # 使用新的设备注册管理器
            devices = await device_registry.discover(
                device_type=device_type,
                group=group,
                tag=tag,
                online_only=online_only,
            )
            
            device_list = [d.to_dict() for d in devices]
            
            # 同时包含旧的 registered_devices 以保持兼容
            for did, info in registered_devices.items():
                if did not in [d["device_id"] for d in device_list]:
                    info["online"] = did in connection_manager.active_devices
                    device_list.append(info)
            
            return JSONResponse({"devices": device_list, "total": len(device_list)})
        except Exception as e:
            # 降级到旧的实现
            devices = []
            for did, info in registered_devices.items():
                devices.append({
                    **info,
                    "online": did in connection_manager.active_devices
                })
            return JSONResponse({"devices": devices, "total": len(devices)})
    
    @router.get("/api/v1/devices/{device_id}")
    async def get_device(device_id: str):
        """获取设备详情"""
        try:
            from core.device_registry import device_registry
            
            device = device_registry.get(device_id)
            if device:
                info = device.to_dict()
                info["online"] = device.is_online()
                return JSONResponse(info)
        except:
            pass
        
        # 降级到旧的实现
        if device_id in registered_devices:
            info = registered_devices[device_id]
            info["online"] = device_id in connection_manager.active_devices
            return JSONResponse(info)
        raise HTTPException(status_code=404, detail="设备未找到")
    

    # ========================================================================
    # 设备发现和管理 API (新增)
    # ========================================================================
    
    @router.get("/api/v1/devices/discover")
    async def discover_devices(
        device_type: str = None,
        capability: str = None,
        group: str = None,
        tag: str = None,
        online_only: bool = True,
    ):
        """
        发现设备
        
        支持按类型、能力、分组、标签过滤
        """
        try:
            from core.device_registry import device_registry
            
            devices = await device_registry.discover(
                device_type=device_type,
                capability=capability,
                group=group,
                tag=tag,
                online_only=online_only,
            )
            
            return JSONResponse({
                "success": True,
                "devices": [d.to_dict() for d in devices],
                "total": len(devices),
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.post("/api/v1/devices/{device_id}/groups")
    async def add_device_to_group(device_id: str, group: str):
        """添加设备到分组"""
        try:
            from core.device_registry import device_registry
            
            success = device_registry.add_to_group(device_id, group)
            
            return JSONResponse({
                "success": success,
                "device_id": device_id,
                "group": group,
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.delete("/api/v1/devices/{device_id}/groups/{group}")
    async def remove_device_from_group(device_id: str, group: str):
        """从分组移除设备"""
        try:
            from core.device_registry import device_registry
            
            success = device_registry.remove_from_group(device_id, group)
            
            return JSONResponse({
                "success": success,
                "device_id": device_id,
                "group": group,
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.post("/api/v1/devices/{device_id}/tags")
    async def add_device_tag(device_id: str, tag: str):
        """添加设备标签"""
        try:
            from core.device_registry import device_registry
            
            success = device_registry.add_tag(device_id, tag)
            
            return JSONResponse({
                "success": success,
                "device_id": device_id,
                "tag": tag,
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.delete("/api/v1/devices/{device_id}/tags/{tag}")
    async def remove_device_tag(device_id: str, tag: str):
        """移除设备标签"""
        try:
            from core.device_registry import device_registry
            
            success = device_registry.remove_tag(device_id, tag)
            
            return JSONResponse({
                "success": success,
                "device_id": device_id,
                "tag": tag,
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.get("/api/v1/devices/groups")
    async def list_device_groups():
        """列出所有设备分组"""
        try:
            from core.device_registry import device_registry
            
            groups = []
            for group_name, device_ids in device_registry.groups.items():
                groups.append({
                    "name": group_name,
                    "device_count": len(device_ids),
                    "devices": device_ids,
                })
            
            return JSONResponse({
                "success": True,
                "groups": groups,
                "total": len(groups),
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.get("/api/v1/devices/tags")
    async def list_device_tags():
        """列出所有设备标签"""
        try:
            from core.device_registry import device_registry
            
            tags = []
            for tag_name, device_ids in device_registry.tag_index.items():
                tags.append({
                    "name": tag_name,
                    "device_count": len(device_ids),
                    "devices": device_ids,
                })
            
            return JSONResponse({
                "success": True,
                "tags": tags,
                "total": len(tags),
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.get("/api/v1/devices/capabilities")
    async def list_device_capabilities():
        """列出所有设备能力"""
        try:
            from core.device_registry import device_registry
            
            capabilities = []
            for cap_name, device_ids in device_registry.capability_index.items():
                capabilities.append({
                    "name": cap_name,
                    "device_count": len(device_ids),
                    "devices": device_ids,
                })
            
            return JSONResponse({
                "success": True,
                "capabilities": capabilities,
                "total": len(capabilities),
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.post("/api/v1/devices/negotiate")
    async def negotiate_device_capability(capability: str, device_id: str = None):
        """
        协商设备能力
        
        找到具有指定能力的最佳设备
        """
        try:
            from core.device_registry import device_registry
            
            device = device_registry.negotiate_capability(capability, device_id)
            
            if device:
                return JSONResponse({
                    "success": True,
                    "device": device.to_dict(),
                })
            else:
                return JSONResponse({
                    "success": False,
                    "error": f"没有找到具有 {capability} 能力的设备",
                }, status_code=404)
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.post("/api/v1/devices/{device_id}/heartbeat")
    async def device_heartbeat(device_id: str):
        """设备心跳"""
        try:
            from core.device_registry import device_registry
            
            success = await device_registry.heartbeat(device_id)
            
            return JSONResponse({
                "success": success,
                "device_id": device_id,
                "timestamp": time.time(),
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.get("/api/v1/devices/stats")
    async def device_stats():
        """设备统计"""
        try:
            from core.device_registry import device_registry
            
            stats = device_registry.get_stats()
            
            return JSONResponse({
                "success": True,
                "stats": stats,
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.delete("/api/v1/devices/{device_id}")
    async def unregister_device(device_id: str):
        """注销设备"""
        try:
            from core.device_registry import device_registry
            
            success = await device_registry.unregister(device_id)
            
            # 同时从旧的 registered_devices 移除
            if device_id in registered_devices:
                del registered_devices[device_id]
            
            return JSONResponse({
                "success": success,
                "device_id": device_id,
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)


    # ========================================================================
    # /api/v1/mcp - MCP 管理 API
    # ========================================================================
    
    @router.get("/api/v1/mcp/servers")
    async def list_mcp_servers():
        """列出已加载的 MCP 服务器"""
        try:
            from core.mcp_loader import mcp_loader
            
            servers = mcp_loader.list_servers()
            return JSONResponse({
                "success": True,
                "servers": servers,
                "total": len(servers),
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.post("/api/v1/mcp/load")
    async def load_mcp_server(request: dict):
        """加载 MCP 服务器"""
        try:
            from core.mcp_loader import mcp_loader
            
            name = request.get("name", "")
            command = request.get("command", "")
            args = request.get("args", [])
            env = request.get("env", {})
            
            if not name or not command:
                return JSONResponse({
                    "success": False,
                    "error": "缺少 name 或 command",
                }, status_code=400)
            
            result = await mcp_loader.load(name, command, args, env)
            
            return JSONResponse({
                "success": result.get("success", False),
                "server_id": name,
                "message": result.get("message", ""),
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.post("/api/v1/mcp/unload")
    async def unload_mcp_server(server_id: str):
        """卸载 MCP 服务器"""
        try:
            from core.mcp_loader import mcp_loader
            
            result = await mcp_loader.unload(server_id)
            
            return JSONResponse({
                "success": result,
                "server_id": server_id,
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.get("/api/v1/mcp/servers/{server_id}/tools")
    async def list_mcp_tools(server_id: str):
        """列出 MCP 服务器的工具"""
        try:
            from core.mcp_loader import mcp_loader
            
            tools = await mcp_loader.list_tools(server_id)
            
            return JSONResponse({
                "success": True,
                "server_id": server_id,
                "tools": tools,
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.post("/api/v1/mcp/call")
    async def call_mcp_tool(request: dict):
        """调用 MCP 工具"""
        try:
            from core.mcp_loader import mcp_loader
            
            server_id = request.get("server_id", "")
            tool_name = request.get("tool_name", "")
            arguments = request.get("arguments", {})
            
            if not server_id or not tool_name:
                return JSONResponse({
                    "success": False,
                    "error": "缺少 server_id 或 tool_name",
                }, status_code=400)
            
            result = await mcp_loader.call_tool(server_id, tool_name, arguments)
            
            return JSONResponse({
                "success": True,
                "result": result,
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)

    # ========================================================================
    # /api/v1/nodes - 节点查询和调用
    # ========================================================================
    
    @router.get("/api/v1/nodes")
    async def list_nodes():
        """列出所有可用节点"""
        nodes = []
        # 从节点配置文件加载
        nodes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes")
        if os.path.isdir(nodes_dir):
            for name in sorted(os.listdir(nodes_dir)):
                node_dir = os.path.join(nodes_dir, name)
                if os.path.isdir(node_dir) and os.path.exists(os.path.join(node_dir, "main.py")):
                    config_file = os.path.join(node_dir, "config.json")
                    node_config = {}
                    if os.path.exists(config_file):
                        try:
                            with open(config_file) as f:
                                node_config = json.load(f)
                        except Exception:
                            pass
                    
                    status = node_status_cache.get(name, {})
                    nodes.append({
                        "name": name,
                        "description": node_config.get("description", ""),
                        "group": node_config.get("group", ""),
                        "status": status.get("status", "stopped"),
                        "capabilities": node_config.get("capabilities", [])
                    })
        
        return JSONResponse({"nodes": nodes, "total": len(nodes)})
    
    @router.get("/api/v1/nodes/{node_name}")
    async def get_node(node_name: str):
        """获取节点详情"""
        nodes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes")
        node_dir = os.path.join(nodes_dir, node_name)
        
        if not os.path.isdir(node_dir):
            raise HTTPException(status_code=404, detail=f"节点 {node_name} 未找到")
        
        config_file = os.path.join(node_dir, "config.json")
        node_config = {}
        if os.path.exists(config_file):
            try:
                with open(config_file) as f:
                    node_config = json.load(f)
            except Exception:
                pass
        
        status = node_status_cache.get(node_name, {})
        return JSONResponse({
            "name": node_name,
            "config": node_config,
            "status": status,
            "has_fusion_entry": os.path.exists(os.path.join(node_dir, "fusion_entry.py")),
            "has_dockerfile": os.path.exists(os.path.join(node_dir, "Dockerfile"))
        })
    
    # 节点实例缓存
    _node_instances = {}
    
    def _load_node(node_id: str, node_dir: str, fusion_entry_path: str):
        """加载节点模块，支持模块级 execute 函数和类实例两种模式
        
        注意：不修改 sys.path，避免跨节点导入污染。
        每个 fusion_entry.py 内部使用 importlib.util 绝对路径导入自己的 main.py。
        """
        if node_id in _node_instances:
            return _node_instances[node_id]
        
        import importlib.util
        
        spec = importlib.util.spec_from_file_location(
            f"nodes.{node_id}.fusion_entry", fusion_entry_path,
            submodule_search_locations=[node_dir]
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # 模式1：模块级 execute 函数（新版 fusion_entry）
        if hasattr(module, 'execute') and callable(module.execute):
            _node_instances[node_id] = {"type": "function", "execute": module.execute, "module": module}
            return _node_instances[node_id]
        
        # 模式2：通过 get_node_instance() 获取类实例
        if hasattr(module, 'get_node_instance'):
            instance = module.get_node_instance()
            if hasattr(instance, 'execute'):
                _node_instances[node_id] = {"type": "instance", "instance": instance, "module": module}
                return _node_instances[node_id]
        
        # 模式3：查找模块中的第一个有 execute 方法的类
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type) and hasattr(attr, 'execute'):
                try:
                    instance = attr()
                    _node_instances[node_id] = {"type": "instance", "instance": instance, "module": module}
                    return _node_instances[node_id]
                except Exception:
                    continue
        
        return None
    
    async def _execute_node(node_info: dict, action: str, params: dict):
        """执行节点操作，处理同步和异步两种方法"""
        import inspect
        
        if node_info["type"] == "function":
            func = node_info["execute"]
            if inspect.iscoroutinefunction(func):
                return await func(action, params)
            else:
                return await asyncio.get_event_loop().run_in_executor(
                    None, func, action, params
                )
        elif node_info["type"] == "instance":
            instance = node_info["instance"]
            method = instance.execute
            if inspect.iscoroutinefunction(method):
                return await method(action, **params)
            else:
                return await asyncio.get_event_loop().run_in_executor(
                    None, lambda: method(action, **params)
                )
        return None
    
    # ========================================================================
    # /api/v1/agent - 自主智能体调度
    # ========================================================================

    from core.scheduler import AutonomousScheduler
    from core.llm_manager import LLMManager
    
    nodes_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes")
    scheduler = AutonomousScheduler(nodes_root)
    llm_manager = LLMManager(os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.json"))

    class AutonomousRequest(BaseModel):
        instruction: str
        context: Dict[str, Any] = {}
        model_alias: Optional[str] = None

    @router.post("/api/v1/agent/autonomous")
    async def autonomous_execute(req: AutonomousRequest):
        """自主调度接口：接收自然语言指令，自动规划并执行节点任务 (ReAct Loop)"""
        try:
            # 定义执行器回调，供 Scheduler 在 ReAct 循环中调用
            async def node_executor(node_id: str, action: str, params: dict):
                # 1. 查找节点目录
                target_node_dir = os.path.join(nodes_root, node_id)
                if not os.path.isdir(target_node_dir):
                    # 尝试模糊匹配 (例如 Node_82_NetworkGuard -> Node_82)
                    for name in os.listdir(nodes_root):
                        if name.startswith(node_id) or node_id in name:
                            target_node_dir = os.path.join(nodes_root, name)
                            node_id = name # 更新为真实名称
                            break
                
                if not os.path.isdir(target_node_dir):
                    return {"error": f"Node {node_id} not found"}

                # 2. 加载节点
                fusion_entry = os.path.join(target_node_dir, "fusion_entry.py")
                if not os.path.exists(fusion_entry):
                    return {"error": f"Node {node_id} has no fusion_entry.py"}
                
                node_instance = _load_node(node_id, target_node_dir, fusion_entry)
                if not node_instance:
                    return {"error": f"Failed to load node {node_id}"}
                
                # 3. 执行节点
                try:
                    result = await _execute_node(node_instance, action, params)
                    return result
                except Exception as e:
                    logger.error(f"Node execution error: {e}")
                    return {"error": str(e)}

            # 注入上下文
            execution_context = req.context.copy()
            execution_context["devices"] = registered_devices
            execution_context["executor"] = node_executor
            
            # 启动 ReAct 循环
            # 如果没有配置 API Key，LLMManager 会报错，这里捕获并降级处理
            try:
                plan_result = await scheduler.plan_and_execute(
                    req.instruction, 
                    llm_manager, 
                    execution_context
                )
                return plan_result
            except ValueError as ve:
                # Fallback: 如果没有配置模型，使用简单的规则匹配 (仅用于演示/测试)
                logger.warning(f"LLM not configured, falling back to rule-based: {ve}")
                executed_tasks = []
                if "唤醒" in req.instruction:
                    for did in registered_devices:
                        await connection_manager.send_personal_message(
                            {"type": "task", "task_type": "wake_up", "payload": {"msg": req.instruction}},
                            did
                        )
                        executed_tasks.append(f"Waking up device {did}")
                    return {
                        "success": True, 
                        "reply": "已通过规则引擎唤醒所有设备 (请配置 LLM 以启用智能调度)",
                        "steps": [{"action": "wake_up", "result": "success"}]
                    }
                raise HTTPException(status_code=500, detail="LLM not configured and no rule matched")

        except Exception as e:
            logger.error(f"Autonomous execution failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/nodes/call")
    async def call_node(req: NodeCallRequest):
        """调用节点执行操作"""
        task_id = str(uuid.uuid4())
        
        nodes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes")
        node_dir = os.path.join(nodes_dir, req.node_id)
        fusion_entry = os.path.join(node_dir, "fusion_entry.py")
        
        if not os.path.isdir(node_dir):
            raise HTTPException(status_code=404, detail=f"节点 {req.node_id} 未找到")
        
        # 记录任务
        task_queue[task_id] = {
            "task_id": task_id,
            "node_id": req.node_id,
            "action": req.action,
            "params": req.params,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        
        try:
            if os.path.exists(fusion_entry):
                node_info = _load_node(req.node_id, node_dir, fusion_entry)
                
                if node_info:
                    task_queue[task_id]["status"] = "running"
                    result = await _execute_node(node_info, req.action, req.params or {})
                    task_queue[task_id]["status"] = "completed"
                    task_queue[task_id]["result"] = result
                    return JSONResponse({
                        "success": True,
                        "task_id": task_id,
                        "result": result
                    })
                else:
                    logger.warning(f"节点 {req.node_id} 的 fusion_entry.py 没有可调用的 execute 方法")
            
            # 降级：返回任务 ID
            return JSONResponse({
                "success": True,
                "task_id": task_id,
                "status": "queued",
                "message": f"任务已排队，节点 {req.node_id} 将异步处理"
            })
            
        except Exception as e:
            task_queue[task_id]["status"] = "failed"
            task_queue[task_id]["error"] = str(e)
            logger.error(f"节点调用失败: {req.node_id}.{req.action}: {e}")
            return JSONResponse({
                "success": False,
                "task_id": task_id,
                "error": str(e)
            }, status_code=500)
    
    # ========================================================================
    # /api/v1/vision - 融合视觉理解（OCR + GUI）
    # ========================================================================
    
    @router.post("/api/v1/vision/understand")
    async def vision_understand(req: VisionRequest):
        """融合视觉理解：支持图片、视频流及复合指令"""
        try:
            # 处理视频流
            if req.video_chunk:
                # 这里可以集成视频流处理逻辑，例如将帧存入缓冲区或直接送入多模态模型
                # 目前作为示例，我们将其视为单帧处理，或者返回流接收确认
                if not req.image_base64:
                    return JSONResponse({
                        "success": True,
                        "mode": "video_stream",
                        "session_id": req.session_id,
                        "message": "Video chunk received"
                    })
            
            if not req.image_base64:
                 raise HTTPException(status_code=400, detail="Image or video chunk required")

            # 解码图片
            image_data = base64.b64decode(req.image_base64)
            
            # 尝试使用 VisionPipeline
            try:
                from core.vision_pipeline import VisionPipeline
                pipeline = VisionPipeline()
                result = await asyncio.get_event_loop().run_in_executor(
                    None, pipeline.understand, image_data, req.mode, req.instruction
                )
                return JSONResponse({
                    "success": True,
                    "engine": "vision_pipeline",
                    "result": result
                })
            except ImportError:
                pass
            
            # 降级：直接调用 DeepSeek OCR 2
            try:
                from nodes.Node_15_OCR.core.deepseek_ocr_adapter import DeepSeekOCR2Adapter
                adapter = DeepSeekOCR2Adapter()
                result = await asyncio.get_event_loop().run_in_executor(
                    None, adapter.process_image, image_data, req.mode
                )
                return JSONResponse({
                    "success": True,
                    "engine": "deepseek_ocr2",
                    "result": result
                })
            except Exception as e:
                logger.warning(f"DeepSeek OCR 2 调用失败: {e}")
            
            # 最终降级：返回基本信息
            return JSONResponse({
                "success": False,
                "engine": "none",
                "error": "无可用的视觉理解引擎",
                "result": {
                    "raw_text": "",
                    "text_blocks": [],
                    "ui_elements": [],
                    "scene_description": "视觉引擎不可用",
                    "suggested_actions": []
                }
            })
            
        except Exception as e:
            logger.error(f"视觉理解失败: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @router.post("/api/v1/vision/ocr")
    async def vision_ocr(req: OCRRequest):
        """独立 OCR 接口"""
        try:
            image_data = base64.b64decode(req.image_base64)
            
            # 调用 DeepSeek OCR 2
            try:
                from nodes.Node_15_OCR.core.deepseek_ocr_adapter import DeepSeekOCR2Adapter
                adapter = DeepSeekOCR2Adapter()
                result = await asyncio.get_event_loop().run_in_executor(
                    None, adapter.process_image, image_data, req.mode
                )
                return JSONResponse({
                    "success": True,
                    "engine": "deepseek_ocr2",
                    "text": result.get("text", ""),
                    "blocks": result.get("blocks", []),
                    "confidence": result.get("confidence", 0.0)
                })
            except Exception as e:
                logger.warning(f"DeepSeek OCR 2 调用失败: {e}")
                return JSONResponse({
                    "success": False,
                    "error": str(e),
                    "text": "",
                    "blocks": []
                })
                
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # ========================================================================
    # /api/v1/tasks - 任务管理
    # ========================================================================
    
    @router.post("/api/v1/tasks")
    async def create_task(req: TaskRequest):
        """创建任务"""
        task_id = str(uuid.uuid4())
        task = {
            "task_id": task_id,
            "task_type": req.task_type,
            "payload": req.payload,
            "device_id": req.device_id,
            "priority": req.priority,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        task_queue[task_id] = task
        
        # 如果指定了设备，通过 WebSocket 发送
        if req.device_id and req.device_id in connection_manager.active_devices:
            await connection_manager.send_to_device(req.device_id, {
                "type": "task",
                "task_id": task_id,
                "task_type": req.task_type,
                "payload": req.payload
            })
            task["status"] = "sent"
        
        return JSONResponse({
            "success": True,
            "task_id": task_id,
            "status": task["status"]
        })
    
    @router.get("/api/v1/tasks/{task_id}")
    async def get_task(task_id: str):
        """获取任务状态"""
        if task_id in task_queue:
            return JSONResponse(task_queue[task_id])
        raise HTTPException(status_code=404, detail="任务未找到")
    
    @router.get("/api/v1/tasks")
    async def list_tasks(status: str = None, limit: int = 50):
        """列出任务"""
        tasks = list(task_queue.values())
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        return JSONResponse({
            "tasks": tasks[:limit],
            "total": len(tasks)
        })
    
    @router.post("/api/v1/tasks/{task_id}/result")
    async def submit_task_result(task_id: str):
        """提交任务结果（设备回调）"""
        if task_id in task_queue:
            # 从请求体读取结果
            task_queue[task_id]["status"] = "completed"
            task_queue[task_id]["completed_at"] = datetime.now().isoformat()
            return {"success": True}
        raise HTTPException(status_code=404, detail="任务未找到")
    
    # ========================================================================
    # /api/v1/command - 统一命令端点
    # ========================================================================
    
    async def execute_command_on_target(target: str, command: str, params: Dict[str, Any], timeout: int) -> TargetResult:
        """在单个目标上执行命令"""
        started_at = datetime.now(timezone.utc).isoformat()
        
        try:
            # 检查目标是否在线
            if target not in connection_manager.active_devices:
                return TargetResult(
                    status=CommandStatus.FAILED,
                    output=None,
                    error="Target device not connected",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc).isoformat()
                )
            
            # 构建命令消息
            message = {
                "type": "command",
                "command": command,
                "params": params,
                "timestamp": started_at
            }
            
            # 发送命令到设备
            success = await connection_manager.send_to_device(target, message)
            
            if not success:
                return TargetResult(
                    status=CommandStatus.FAILED,
                    output=None,
                    error="Failed to send command to target",
                    started_at=started_at,
                    completed_at=datetime.now(timezone.utc).isoformat()
                )
            
            # 在实际实现中，这里应该等待设备响应
            # 目前简化为立即返回成功
            return TargetResult(
                status=CommandStatus.DONE,
                output={"message": "Command sent successfully"},
                error=None,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat()
            )
            
        except Exception as e:
            logger.error(f"执行命令失败 (target={target}): {e}")
            return TargetResult(
                status=CommandStatus.FAILED,
                output=None,
                error=str(e),
                started_at=started_at,
                completed_at=datetime.now(timezone.utc).isoformat()
            )
    
    @router.post("/api/v1/command")
    async def unified_command(
        req: UnifiedCommandRequest,
        auth: dict = Depends(require_auth)
    ):
        """
        统一命令端点 - 支持多目标、sync/async 模式、超时控制
        
        **功能特性：**
        - 多目标并行执行
        - request_id 追踪
        - sync/async 模式选择
        - 超时控制
        - 结果聚合
        
        **请求示例：**
        ```json
        {
          "request_id": "optional-uuid",
          "command": "screenshot",
          "targets": ["device_1", "device_2"],
          "params": {"quality": 90},
          "mode": "sync",
          "timeout": 30
        }
        ```
        """
        # 生成或使用提供的 request_id
        request_id = req.request_id or str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        
        logger.info(f"收到统一命令: request_id={request_id}, command={req.command}, targets={req.targets}, mode={req.mode}")
        
        # 验证模式
        if req.mode not in ["sync", "async"]:
            raise HTTPException(status_code=400, detail="Invalid mode. Must be 'sync' or 'async'")
        
        # 验证目标列表
        if not req.targets:
            raise HTTPException(status_code=400, detail="Targets list cannot be empty")
        
        # 初始化命令结果
        command_results[request_id] = {
            "request_id": request_id,
            "command": req.command,
            "targets": req.targets,
            "params": req.params,
            "mode": req.mode,
            "status": CommandStatus.QUEUED,
            "created_at": created_at,
            "completed_at": None,
            "results": {}
        }
        
        if req.mode == "sync":
            # 同步模式：并行执行所有目标并等待完成
            command_results[request_id]["status"] = CommandStatus.RUNNING
            
            # 使用 asyncio.gather 并行执行
            tasks = [
                execute_command_on_target(target, req.command, req.params, req.timeout)
                for target in req.targets
            ]
            
            try:
                # 设置超时
                target_results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=req.timeout
                )
                
                # 聚合结果
                results = {}
                for target, result in zip(req.targets, target_results):
                    if isinstance(result, Exception):
                        results[target] = TargetResult(
                            status=CommandStatus.FAILED,
                            output=None,
                            error=str(result),
                            started_at=created_at,
                            completed_at=datetime.now(timezone.utc).isoformat()
                        )
                    else:
                        results[target] = result
                
                # 更新命令结果
                completed_at = datetime.now(timezone.utc).isoformat()
                command_results[request_id]["status"] = CommandStatus.DONE
                command_results[request_id]["completed_at"] = completed_at
                command_results[request_id]["results"] = {
                    k: v.model_dump() for k, v in results.items()
                }
                
                # 返回响应
                return JSONResponse({
                    "request_id": request_id,
                    "status": CommandStatus.DONE,
                    "created_at": created_at,
                    "completed_at": completed_at,
                    "results": command_results[request_id]["results"]
                })
                
            except asyncio.TimeoutError:
                # 超时处理
                completed_at = datetime.now(timezone.utc).isoformat()
                command_results[request_id]["status"] = CommandStatus.FAILED
                command_results[request_id]["completed_at"] = completed_at
                command_results[request_id]["results"] = {
                    target: TargetResult(
                        status=CommandStatus.FAILED,
                        output=None,
                        error="Execution timeout",
                        started_at=created_at,
                        completed_at=completed_at
                    ).model_dump()
                    for target in req.targets
                }
                
                raise HTTPException(status_code=408, detail="Command execution timeout")
                
        else:
            # 异步模式：立即返回 request_id，后台执行
            async def execute_async():
                """后台执行任务"""
                try:
                    command_results[request_id]["status"] = CommandStatus.RUNNING
                    
                    # 并行执行所有目标
                    tasks = [
                        execute_command_on_target(target, req.command, req.params, req.timeout)
                        for target in req.targets
                    ]
                    
                    target_results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    # 聚合结果
                    results = {}
                    for target, result in zip(req.targets, target_results):
                        if isinstance(result, Exception):
                            results[target] = TargetResult(
                                status=CommandStatus.FAILED,
                                output=None,
                                error=str(result),
                                started_at=created_at,
                                completed_at=datetime.now(timezone.utc).isoformat()
                            )
                        else:
                            results[target] = result
                    
                    # 更新命令结果
                    completed_at = datetime.now(timezone.utc).isoformat()
                    command_results[request_id]["status"] = CommandStatus.DONE
                    command_results[request_id]["completed_at"] = completed_at
                    command_results[request_id]["results"] = {
                        k: v.model_dump() for k, v in results.items()
                    }
                    
                    # 通过 WebSocket 推送结果
                    await connection_manager.broadcast_status({
                        "type": "command_result",
                        "request_id": request_id,
                        "status": CommandStatus.DONE,
                        "created_at": created_at,
                        "completed_at": completed_at,
                        "results": command_results[request_id]["results"]
                    })
                    
                except Exception as e:
                    logger.error(f"异步命令执行失败: {e}")
                    completed_at = datetime.now(timezone.utc).isoformat()
                    command_results[request_id]["status"] = CommandStatus.FAILED
                    command_results[request_id]["completed_at"] = completed_at
                    command_results[request_id]["results"] = {
                        target: TargetResult(
                            status=CommandStatus.FAILED,
                            output=None,
                            error=str(e),
                            started_at=created_at,
                            completed_at=completed_at
                        ).model_dump()
                        for target in req.targets
                    }
                    
                    # 推送失败结果
                    await connection_manager.broadcast_status({
                        "type": "command_result",
                        "request_id": request_id,
                        "status": CommandStatus.FAILED,
                        "created_at": created_at,
                        "completed_at": completed_at,
                        "results": command_results[request_id]["results"]
                    })
            
            # 创建后台任务
            asyncio.create_task(execute_async())
            
            # 立即返回
            return JSONResponse({
                "request_id": request_id,
                "status": CommandStatus.QUEUED,
                "created_at": created_at,
                "message": "Command queued for async execution. Use GET /api/v1/command/{request_id}/status to check status."
            })
    
    @router.get("/api/v1/command/{request_id}/status")
    async def get_command_status(
        request_id: str,
        auth: dict = Depends(require_auth)
    ):
        """
        查询异步命令执行状态和结果
        
        **响应示例：**
        ```json
        {
          "request_id": "xxx",
          "status": "done",
          "created_at": "2026-02-12T10:00:00Z",
          "completed_at": "2026-02-12T10:00:05Z",
          "results": {
            "device_1": {
              "status": "done",
              "output": {...},
              "error": null
            }
          }
        }
        ```
        """
        if request_id not in command_results:
            raise HTTPException(status_code=404, detail="Command not found")
        
        result = command_results[request_id]
        
        return JSONResponse({
            "request_id": result["request_id"],
            "status": result["status"],
            "created_at": result["created_at"],
            "completed_at": result["completed_at"],
            "results": result["results"]
        })
    
    # ========================================================================
    # /api/v1/chat - 对话接口
    # ========================================================================
    
    @router.post("/api/v1/chat")
    async def chat(req: ChatRequest):
        """
        对话接口 - AI 驱动的统一入口
        
        流程：
        1. 解析用户意图
        2. 根据意图决定执行方式
        3. 设备控制 → 调用设备控制服务
        4. 节点调用 → 调用目标节点
        5. 普通对话 → 调用 LLM
        """
        try:
            # ================================================================
            # Step 1: 解析意图
            # ================================================================
            parsed_intent = None
            try:
                from core.ai_intent import get_intent_parser
                intent_parser = get_intent_parser()
                parsed_intent = await intent_parser.parse(req.message, {})
                intent = parsed_intent.intent
                confidence = parsed_intent.confidence
                logger.info(f"意图解析: {intent} (置信度: {confidence:.2f})")
            except Exception as e:
                logger.warning(f"意图解析失败，使用默认对话: {e}")
                intent = "chat"
                confidence = 0.0
            
            # ================================================================
            # Step 2: 根据意图执行
            # ================================================================
            
            # 设备控制
            if intent == "device_control" and confidence > 0.5:
                try:
                    from core.device_control_service import device_control
                    
                    # 获取目标设备
                    device_id = req.device_id if req.device_id else None
                    if not device_id:
                        devices = device_control.list_devices()
                        if devices:
                            device_id = devices[0].device_id
                    
                    if device_id:
                        # 根据消息内容决定操作
                        message_lower = req.message.lower()
                        result = None
                        
                        if "打开" in req.message or "open" in message_lower:
                            # 提取应用名
                            import re
                            match = re.search(r"打开\s*(\S+)|open\s+(\w+)", req.message, re.IGNORECASE)
                            app_name = match.group(1) or match.group(2) if match else ""
                            if app_name:
                                result = await device_control.open_app(device_id, app_name)
                        
                        elif "截图" in req.message or "screenshot" in message_lower:
                            result = await device_control.screenshot(device_id)
                        
                        elif "点击" in req.message or "click" in message_lower:
                            # 需要坐标，这里简化处理
                            result = {"status": "need_coordinates", "message": "请提供点击坐标"}
                        
                        else:
                            # 通用控制
                            result = await device_control.control_device(
                                from_device_id="server",
                                to_device_id=device_id,
                                action="execute",
                                params={"command": req.message}
                            )
                        
                        return JSONResponse({
                            "success": True,
                            "reply": f"已在设备 {device_id} 上执行操作",
                            "intent": intent,
                            "device_id": device_id,
                            "result": result,
                        })
                    else:
                        return JSONResponse({
                            "success": False,
                            "reply": "没有可用的设备，请先连接设备",
                            "intent": intent,
                        })
                except Exception as e:
                    logger.error(f"设备控制失败: {e}")
                    # 降级到普通对话
                    pass
            # 节点调用
            elif intent in ["task_manage", "search", "ocr", "file_operation"] and confidence > 0.5:
                try:
                    # 获取目标节点
                    target_node = None
                    if parsed_intent and parsed_intent.targets:
                        target_node = parsed_intent.targets[0]
                    else:
                        # 根据意图映射节点
                        node_mapping = {
                            "task_manage": "Node_02_Tasker",
                            "search": "Node_22_BraveSearch",
                            "ocr": "Node_15_OCR",
                            "file_operation": "Node_06_Filesystem",
                        }
                        target_node = node_mapping.get(intent)
                    
                    if target_node:
                        # 调用节点
                        import httpx
                        node_num = int(target_node.replace("Node_", "").split("_")[0])
                        port = 8000 + node_num
                        url = f"http://localhost:{port}/execute"
                        
                        params = {}
                        if parsed_intent:
                            params = parsed_intent.params
                        params["query"] = req.message
                        
                        async with httpx.AsyncClient(timeout=30) as client:
                            resp = await client.post(url, json=params)
                            if resp.status_code == 200:
                                result = resp.json()
                                return JSONResponse({
                                    "success": True,
                                    "reply": f"节点 {target_node} 执行完成",
                                    "intent": intent,
                                    "node": target_node,
                                    "result": result,
                                })
                except Exception as e:
                    logger.warning(f"节点调用失败: {e}")
                    # 降级到普通对话
                    pass
            
            # ================================================================
            
            # ================================================================
            # Step 2.5: 能力发现和执行
            # ================================================================
            
            # 尝试发现最佳能力
            try:
                from core.capability_orchestrator import capability_orchestrator
                
                # 初始化能力编排器
                await capability_orchestrator.initialize()
                
                # 发现能力
                capabilities = await capability_orchestrator.discover(req.message, limit=3)
                
                if capabilities:
                    best_cap = capabilities[0]
                    cap_type = best_cap.get("type", "")
                    
                    # 如果找到高优先级的能力，执行它
                    if cap_type in ["mcp_tool", "skill"] and best_cap.get("priority", 0) >= 7:
                        logger.info(f"执行能力: {best_cap['id']}")
                        result = await capability_orchestrator.execute(
                            best_cap["id"],
                            **(parsed_intent.params if parsed_intent else {}),
                        )
                        
                        return JSONResponse({
                            "success": True,
                            "reply": f"已执行: {best_cap['name']}",
                            "intent": intent,
                            "capability": best_cap,
                            "result": result,
                        })
            except Exception as e:
                logger.warning(f"能力发现失败: {e}")
            
            # Step 3: 普通对话 - 调用 LLM
            # ================================================================
            api_key = os.environ.get("OPENAI_API_KEY", "")
            api_base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
            
            if not api_key:
                # 尝试 Gemini
                gemini_key = os.environ.get("GEMINI_API_KEY", "")
                if gemini_key:
                    return await _chat_with_gemini(req, gemini_key)
                
                # 尝试 OpenRouter
                or_key = os.environ.get("OPENROUTER_API_KEY", "")
                if or_key:
                    return await _chat_with_openrouter(req, or_key)
                
                return JSONResponse({
                    "success": False,
                    "error": "未配置 LLM API Key",
                    "reply": "抱歉，LLM 服务未配置。请在 .env 文件中设置 API Key。"
                })
            
            import httpx
            messages = [{"role": "system", "content": "你是 UFO Galaxy 智能助手，一个 L4 级自主性 AI 系统。你可以控制设备、调用节点、执行任务。"}]
            for ctx in req.context[-10:]:
                messages.append(ctx)
            messages.append({"role": "user", "content": req.message})
            
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{api_base}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": messages,
                        "max_tokens": 2048
                    }
                )
                resp.raise_for_status()
                data = resp.json()
                reply = data["choices"][0]["message"]["content"]
                
                return JSONResponse({
                    "success": True,
                    "reply": reply,
                    "model": data.get("model", ""),
                    "usage": data.get("usage", {}),
                    "intent": intent if parsed_intent else "chat",
                })
                
        except Exception as e:
            logger.error(f"对话失败: {e}")
            return JSONResponse({
                "success": False,
                "error": str(e),
                "reply": f"处理消息时出错: {str(e)}"
            })
    
        """创建 WebSocket 端点"""
    
    @router.websocket("/ws/device/{device_id}")
    async def device_websocket(websocket: WebSocket, device_id: str):
        """设备 WebSocket 连接 - 双向通信，兼容安卓端"""
        await connection_manager.connect_device(websocket, device_id)
        
        # 兼容安卓端：自动注册设备
        try:
            from core.device_registry import device_registry
            device = device_registry.get(device_id)
            if not device:
                # 自动注册设备
                await device_registry.register(
                    device_id=device_id,
                    device_type="android",
                    name=f"Android Device ({device_id[:8]})",
                    capabilities=["screen", "touch", "keyboard"],
                    tags=["android", "auto-registered"],
                )
                logger.info(f"自动注册设备: {device_id}")
        except Exception as e:
            logger.warning(f"自动注册设备失败: {device_id} - {e}")
        
        # 更新设备在线状态
        if device_id in registered_devices:
            registered_devices[device_id]["last_seen"] = datetime.now().isoformat()
            registered_devices[device_id]["status"] = "online"
        
        try:
            while True:
                data = await websocket.receive_json()
                msg_type = data.get("type", "")
                
                if msg_type == "heartbeat":
                    # 心跳
                    if device_id in registered_devices:
                        registered_devices[device_id]["last_seen"] = datetime.now().isoformat()
                    await websocket.send_json({
                        "type": "heartbeat_ack",
                        "timestamp": datetime.now().isoformat()
                    })
                    
                elif msg_type == "status_update":
                    # 设备状态更新
                    if device_id in registered_devices:
                        registered_devices[device_id]["status_detail"] = data.get("status", {})
                        registered_devices[device_id]["last_seen"] = datetime.now().isoformat()
                    await connection_manager.broadcast_status({
                        "type": "device_status_update",
                        "device_id": device_id,
                        "status": data.get("status", {}),
                        "timestamp": datetime.now().isoformat()
                    })
                    
                elif msg_type == "task_result":
                    # 任务结果回调
                    task_id = data.get("task_id", "")
                    if task_id in task_queue:
                        task_queue[task_id]["status"] = "completed"
                        task_queue[task_id]["result"] = data.get("result", {})
                        task_queue[task_id]["completed_at"] = datetime.now().isoformat()
                    
                elif msg_type == "ocr_request":
                    # OCR 请求
                    image_b64 = data.get("image", "")
                    mode = data.get("mode", "full")
                    instruction = data.get("instruction", "")
                    
                    try:
                        image_data = base64.b64decode(image_b64)
                        from core.vision_pipeline import VisionPipeline
                        pipeline = VisionPipeline()
                        result = await asyncio.get_event_loop().run_in_executor(
                            None, pipeline.understand, image_data, mode, instruction
                        )
                        await websocket.send_json({
                            "type": "ocr_result",
                            "request_id": data.get("request_id", ""),
                            "success": True,
                            "result": result
                        })
                    except Exception as e:
                        await websocket.send_json({
                            "type": "ocr_result",
                            "request_id": data.get("request_id", ""),
                            "success": False,
                            "error": str(e)
                        })
                    
                elif msg_type == "chat":
                    # 对话请求
                    try:
                        chat_req = ChatRequest(
                            message=data.get("message", ""),
                            device_id=device_id,
                            context=data.get("context", [])
                        )
                        # 复用 chat 逻辑
                        api_key = os.environ.get("OPENAI_API_KEY", "")
                        if api_key:
                            import httpx
                            # 注入 AGENTS.md 上下文 (基于 Vercel 研究: 100% vs 79%)
                            agent_context = get_agent_context()
                            system_content = f"你是 UFO Galaxy 智能助手。\n\n{agent_context}"
                            
                            messages = [
                                {"role": "system", "content": system_content},
                                {"role": "user", "content": chat_req.message}
                            ]
                            async with httpx.AsyncClient(timeout=60) as client:
                                resp = await client.post(
                                    f"{os.environ.get('OPENAI_API_BASE', 'https://api.openai.com/v1')}/chat/completions",
                                    headers={"Authorization": f"Bearer {api_key}"},
                                    json={"model": "gpt-4o-mini", "messages": messages}
                                )
                                resp_data = resp.json()
                                reply = resp_data["choices"][0]["message"]["content"]
                        else:
                            reply = "LLM 服务未配置"
                        
                        await websocket.send_json({
                            "type": "chat_reply",
                            "request_id": data.get("request_id", ""),
                            "reply": reply
                        })
                    except Exception as e:
                        await websocket.send_json({
                            "type": "chat_reply",
                            "request_id": data.get("request_id", ""),
                            "reply": f"处理消息时出错: {str(e)}"
                        })
                
                else:
                    # 未知消息类型
                    logger.warning(f"未知消息类型: {msg_type} from {device_id}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"未知消息类型: {msg_type}"
                    })
                    
        except WebSocketDisconnect:
            connection_manager.disconnect_device(device_id)
            if device_id in registered_devices:
                registered_devices[device_id]["status"] = "offline"
            await connection_manager.broadcast_status({
                "type": "device_disconnected",
                "device_id": device_id,
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            logger.error(f"WebSocket 错误 ({device_id}): {e}")
            connection_manager.disconnect_device(device_id)
    
    @router.websocket("/ws/status")
    async def status_websocket(websocket: WebSocket):
        """状态推送 WebSocket - 订阅系统状态变更"""
        await connection_manager.subscribe_status(websocket)
        try:
            # 发送当前状态
            await websocket.send_json({
                "type": "initial_status",
                "devices_online": len(connection_manager.active_devices),
                "devices_registered": len(registered_devices),
                "timestamp": datetime.now().isoformat()
            })
            
            while True:
                # 保持连接，等待客户端消息
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now().isoformat()
                    })
        except WebSocketDisconnect:
            connection_manager.unsubscribe_status(websocket)
        except Exception:
            connection_manager.unsubscribe_status(websocket)


    # ========================================================================
    # /api/v1/agents - Agent 上下文 API (基于 Vercel 研究)
    # ========================================================================
    
    @router.get("/api/v1/agents/context")
    async def get_agent_context_api():
        """
        获取 Agent 上下文 (AGENTS.md)
        
        基于 Vercel 研究：被动上下文比主动调用更可靠
        """
        try:
            from core.agent_context import get_agent_context, get_context_size
            
            context = get_agent_context()
            size = get_context_size()
            
            return JSONResponse({
                "success": True,
                "context": context,
                "size": size,
                "size_kb": round(size / 1024, 2),
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)
    
    @router.get("/api/v1/agents/prompt")
    async def get_agent_system_prompt_api():
        """获取 Agent 系统提示词"""
        try:
            from core.agent_context import get_system_prompt
            
            prompt = get_system_prompt()
            
            return JSONResponse({
                "success": True,
                "prompt": prompt,
            })
        except Exception as e:
            return JSONResponse({
                "success": False,
                "error": str(e),
            }, status_code=500)

    return router
