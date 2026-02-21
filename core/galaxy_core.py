"""
Galaxy Core - 系统整合核心
=========================

使用已有协议进行系统性整合:
- core/node_protocol.py - 节点间通信
- enhancements/multidevice/device_protocol.py - 设备通信
- nodes/common/mcp_adapter.py - MCP 适配

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
from core.node_protocol import (
    Message, MessageHeader, MessageType, MessagePriority,
    NodeProtocolClient, NodeProtocolServer
)

from enhancements.multidevice.device_protocol import (
    AIPMessage, AIPProtocol, MessageType as AIPMessageType
)

from nodes.common.mcp_adapter import MCPAdapter, PythonMCPAdapter

import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GalaxyCore")


class GalaxyCore:
    """
    Galaxy 核心整合层
    
    使用已有协议整合所有节点
    """
    
    def __init__(self):
        self.nodes: Dict[str, Dict] = {}
        self.devices: Dict[str, Dict] = {}
        self._http_client: Optional[httpx.AsyncClient] = None
        self._protocol_client: Optional[NodeProtocolClient] = None
        
        # 加载节点注册表
        self._load_node_registry()
    
    def _load_node_registry(self):
        """加载节点注册表"""
        registry_path = os.path.join(PROJECT_ROOT, "config", "node_registry.json")
        
        if os.path.exists(registry_path):
            try:
                with open(registry_path, 'r') as f:
                    registry = json.load(f)
                    self.nodes = registry.get("nodes", {})
                    logger.info(f"已加载 {len(self.nodes)} 个节点")
            except Exception as e:
                logger.error(f"加载节点注册表失败: {e}")
                self._init_default_nodes()
        else:
            self._init_default_nodes()
    
    def _init_default_nodes(self):
        """初始化默认节点"""
        self.nodes = {
            "04": {"name": "Router", "port": 8004, "capabilities": ["route", "discover"]},
            "33": {"name": "ADB", "port": 8033, "capabilities": ["adb", "android"]},
            "36": {"name": "UIAWindows", "port": 8036, "capabilities": ["windows", "automation"]},
            "45": {"name": "DesktopAuto", "port": 8045, "capabilities": ["desktop", "automation"]},
            "50": {"name": "Transformer", "port": 8050, "capabilities": ["nlu", "chat"]},
            "70": {"name": "AutonomousLearning", "port": 8070, "capabilities": ["learning"]},
            "71": {"name": "MultiDeviceCoordination", "port": 8071, "capabilities": ["multi_device"]},
            "72": {"name": "KnowledgeBase", "port": 8072, "capabilities": ["knowledge"]},
            "90": {"name": "MultimodalVision", "port": 8090, "capabilities": ["vision", "ocr"]},
            "92": {"name": "AutoControl", "port": 8092, "capabilities": ["control"]},
            "108": {"name": "MetaCognition", "port": 8108, "capabilities": ["thinking"]},
        }
        logger.info(f"已初始化 {len(self.nodes)} 个默认节点")
    
    async def _get_http_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=30.0)
        return self._http_client
    
    # =========================================================================
    # 节点调用 - 使用已有协议
    # =========================================================================
    
    async def call_node(
        self,
        node_id: str,
        action: str,
        params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        调用节点 - 使用 node_protocol
        """
        if node_id not in self.nodes:
            return {"success": False, "error": f"Node {node_id} not found"}
        
        node = self.nodes[node_id]
        port = node.get("port", 8000)
        endpoint = f"http://localhost:{port}"
        
        params = params or {}
        
        try:
            client = await self._get_http_client()
            
            # 使用 /mcp/call 接口 (已有)
            response = await client.post(
                f"{endpoint}/mcp/call",
                json={"tool": action, "params": params}
            )
            
            if response.status_code == 200:
                return response.json()
            
            # 尝试直接调用
            response = await client.post(
                f"{endpoint}/{action}",
                json=params
            )
            
            return response.json()
        
        except Exception as e:
            logger.error(f"调用节点 {node_id} 失败: {e}")
            return {"success": False, "error": str(e)}
    
    async def call_node_with_protocol(
        self,
        node_id: str,
        action: str,
        params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        使用 node_protocol 调用节点
        """
        if node_id not in self.nodes:
            return {"success": False, "error": f"Node {node_id} not found"}
        
        node = self.nodes[node_id]
        port = node.get("port", 8000)
        
        # 创建协议消息
        message = Message(
            header=MessageHeader(
                message_type=MessageType.REQUEST,
                source_node="galaxy_core",
                target_node=node_id,
                priority=MessagePriority.NORMAL
            ),
            body={
                "action": action,
                "params": params or {}
            }
        )
        
        try:
            client = await self._get_http_client()
            
            response = await client.post(
                f"http://localhost:{port}/protocol/message",
                json=message.to_dict()
            )
            
            return response.json()
        
        except Exception as e:
            logger.error(f"协议调用节点 {node_id} 失败: {e}")
            return {"success": False, "error": str(e)}
    
    # =========================================================================
    # 设备管理 - 使用 device_protocol
    # =========================================================================
    
    async def register_device(
        self,
        device_id: str,
        device_type: str,
        name: str,
        endpoint: str = ""
    ) -> Dict[str, Any]:
        """
        注册设备 - 使用 device_protocol
        """
        # 创建 AIP 消息
        message = AIPMessage(
            message_type=AIPMessageType.DEVICE_REGISTER,
            source_id="galaxy_core",
            target_id=device_id,
            payload={
                "device_id": device_id,
                "device_type": device_type,
                "name": name,
                "endpoint": endpoint,
                "registered_at": datetime.now().isoformat()
            }
        )
        
        self.devices[device_id] = {
            "device_id": device_id,
            "device_type": device_type,
            "name": name,
            "endpoint": endpoint,
            "status": "online",
            "registered_at": datetime.now().isoformat()
        }
        
        logger.info(f"已注册设备: {device_id} ({name})")
        
        return {"success": True, "device_id": device_id}
    
    async def send_device_command(
        self,
        device_id: str,
        command: str,
        params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        发送设备命令 - 使用 device_protocol
        """
        if device_id not in self.devices:
            return {"success": False, "error": f"Device {device_id} not found"}
        
        device = self.devices[device_id]
        device_type = device.get("device_type", "android")
        
        # 根据设备类型选择节点
        if device_type == "android":
            # Android 设备通过 Node_33_ADB 或 Node_92_AutoControl
            return await self.call_node("92", command, {
                "device_id": device_id,
                "platform": "android",
                **(params or {})
            })
        
        elif device_type in ["windows", "desktop"]:
            # Windows 设备通过 Node_36_UIAWindows 或 Node_45_DesktopAuto
            return await self.call_node("36", command, params)
        
        else:
            return {"success": False, "error": f"Unknown device type: {device_type}"}
    
    # =========================================================================
    # 智能调用 - 通过 Node_04_Router 路由
    # =========================================================================
    
    async def smart_call(
        self,
        capability: str,
        action: str,
        params: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        智能调用 - 通过 Node_04_Router 路由
        """
        # 通过 Router 节点路由
        return await self.call_node("04", "route", {
            "capability": capability,
            "action": action,
            "params": params or {}
        })
    
    # =========================================================================
    # 自主能力 - 调用已有节点
    # =========================================================================
    
    async def autonomous_learn(
        self,
        experience: Dict[str, Any]
    ) -> Dict[str, Any]:
        """自主学习 - 调用 Node_70"""
        return await self.call_node("70", "record_experience", experience)
    
    async def autonomous_think(
        self,
        goal: str,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """自主思考 - 调用 Node_108"""
        return await self.call_node("108", "reflect", {
            "goal": goal,
            "context": context or {}
        })
    
    async def autonomous_code(
        self,
        task: str,
        files: List[str] = None
    ) -> Dict[str, Any]:
        """自主编程 - 调用 Node_101"""
        return await self.call_node("101", "generate_code", {
            "task": task,
            "target_files": files or []
        })
    
    async def query_knowledge(
        self,
        query: str,
        top_k: int = 5
    ) -> Dict[str, Any]:
        """查询知识库 - 调用 Node_72"""
        return await self.call_node("72", "search", {
            "query": query,
            "top_k": top_k
        })
    
    # =========================================================================
    # 系统状态
    # =========================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """获取系统状态"""
        return {
            "nodes": len(self.nodes),
            "devices": len(self.devices),
            "protocols": ["node_protocol", "device_protocol", "mcp"],
            "timestamp": datetime.now().isoformat()
        }


# 全局实例
galaxy_core = GalaxyCore()
