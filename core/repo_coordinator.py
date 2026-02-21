"""
仓库协调层
==========

协调主仓库 和 Android 仓库

主仓库:
- 后端服务
- Dashboard
- 所有节点
- 协议层

Android 仓库:
- Android APK
- 无障碍服务
- WebSocket 客户端
- 设备注册

协调方式:
1. Android 设备注册到主仓库
2. 主仓库分发 Agent 到 Android 设备
3. Android 设备通过无障碍服务执行操作
4. 结果返回主仓库

版本: v2.3.23
"""

import os
import sys
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 导入已有协议
from enhancements.multidevice.device_protocol import (
    AIPMessage, AIPProtocol, MessageType as AIPMessageType
)

import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("RepoCoordinator")


class RepoCoordinator:
    """
    仓库协调器
    
    协调主仓库和 Android 仓库
    """
    
    def __init__(self):
        # 主仓库配置
        self.main_repo_url = os.getenv("MAIN_REPO_URL", "http://localhost:8080")
        
        # Android 设备注册表
        self.android_devices: Dict[str, Dict] = {}
        
        # HTTP 客户端
        self._http_client: Optional[httpx.AsyncClient] = None
        
        logger.info("仓库协调器初始化完成")
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client
    
    # =========================================================================
    # Android 设备注册
    # =========================================================================
    
    async def register_android_device(
        self,
        device_id: str,
        device_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        注册 Android 设备
        
        Android 仓库通过此接口注册到主仓库
        """
        self.android_devices[device_id] = {
            "device_id": device_id,
            "device_type": "android",
            "name": device_info.get("name", "Android Device"),
            "model": device_info.get("model", ""),
            "android_version": device_info.get("android_version", ""),
            "endpoint": device_info.get("endpoint", ""),
            "websocket_url": device_info.get("websocket_url", ""),
            "capabilities": device_info.get("capabilities", [
                "click", "swipe", "input", "screenshot", "open_app"
            ]),
            "status": "online",
            "registered_at": datetime.now().isoformat()
        }
        
        logger.info(f"已注册 Android 设备: {device_id}")
        
        # 创建 AIP 注册消息
        message = AIPMessage(
            message_type=AIPMessageType.DEVICE_REGISTER,
            source_id=device_id,
            target_id="galaxy_core",
            payload={
                "device_id": device_id,
                "device_type": "android",
                "name": device_info.get("name", "Android Device"),
                "capabilities": device_info.get("capabilities", [])
            }
        )
        
        return {
            "success": True,
            "device_id": device_id,
            "message": "Device registered successfully"
        }
    
    async def unregister_android_device(self, device_id: str) -> Dict[str, Any]:
        """注销 Android 设备"""
        if device_id in self.android_devices:
            del self.android_devices[device_id]
            logger.info(f"已注销 Android 设备: {device_id}")
            return {"success": True}
        return {"success": False, "error": "Device not found"}
    
    async def heartbeat_android_device(self, device_id: str) -> Dict[str, Any]:
        """Android 设备心跳"""
        if device_id in self.android_devices:
            self.android_devices[device_id]["last_heartbeat"] = datetime.now().isoformat()
            self.android_devices[device_id]["status"] = "online"
            return {"success": True}
        return {"success": False, "error": "Device not found"}
    
    # =========================================================================
    # Agent 分发到 Android 设备
    # =========================================================================
    
    async def dispatch_agent_to_android(
        self,
        device_id: str,
        task_type: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        分发 Agent 到 Android 设备
        
        通过 WebSocket 或 HTTP 发送命令
        """
        if device_id not in self.android_devices:
            return {"success": False, "error": f"Device {device_id} not found"}
        
        device = self.android_devices[device_id]
        
        # 创建 AIP 任务消息
        message = AIPMessage(
            message_type=AIPMessageType.TASK_ASSIGN,
            source_id="galaxy_core",
            target_id=device_id,
            payload={
                "task_type": task_type,
                "params": params,
                "timestamp": datetime.now().isoformat()
            }
        )
        
        try:
            # 优先使用 WebSocket
            ws_url = device.get("websocket_url")
            if ws_url:
                return await self._send_via_websocket(ws_url, message)
            
            # 否则使用 HTTP
            endpoint = device.get("endpoint")
            if endpoint:
                return await self._send_via_http(endpoint, message)
            
            return {"success": False, "error": "No endpoint available"}
        
        except Exception as e:
            logger.error(f"分发 Agent 到 {device_id} 失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_via_websocket(
        self,
        ws_url: str,
        message: AIPMessage
    ) -> Dict[str, Any]:
        """通过 WebSocket 发送"""
        import websockets
        
        try:
            async with websockets.connect(ws_url, timeout=10) as ws:
                await ws.send(message.to_json())
                response = await ws.recv()
                return json.loads(response)
        except Exception as e:
            logger.error(f"WebSocket 发送失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def _send_via_http(
        self,
        endpoint: str,
        message: AIPMessage
    ) -> Dict[str, Any]:
        """通过 HTTP 发送"""
        try:
            client = await self._get_http_client()
            response = await client.post(
                f"{endpoint}/task/execute",
                json=message.to_dict(),
                timeout=30
            )
            return response.json()
        except Exception as e:
            logger.error(f"HTTP 发送失败: {e}")
            return {"success": False, "error": str(e)}
    
    # =========================================================================
    # 批量操作
    # =========================================================================
    
    async def broadcast_to_all_android(
        self,
        task_type: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """广播到所有 Android 设备"""
        results = {}
        
        tasks = [
            self.dispatch_agent_to_android(device_id, task_type, params)
            for device_id in self.android_devices.keys()
        ]
        
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for device_id, response in zip(self.android_devices.keys(), responses):
            if isinstance(response, Exception):
                results[device_id] = {"success": False, "error": str(response)}
            else:
                results[device_id] = response
        
        return {
            "success": True,
            "total": len(results),
            "results": results
        }
    
    # =========================================================================
    # 状态查询
    # =========================================================================
    
    def get_android_devices(self) -> List[Dict[str, Any]]:
        """获取所有 Android 设备"""
        return list(self.android_devices.values())
    
    def get_android_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """获取指定 Android 设备"""
        return self.android_devices.get(device_id)
    
    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        online_count = sum(
            1 for d in self.android_devices.values()
            if d.get("status") == "online"
        )
        
        return {
            "android_devices": len(self.android_devices),
            "online_devices": online_count,
            "main_repo_url": self.main_repo_url,
            "timestamp": datetime.now().isoformat()
        }


# 全局实例
repo_coordinator = RepoCoordinator()
