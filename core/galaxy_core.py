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
try:
    from core.node_protocol import (
        Message, MessageHeader, MessageType, MessagePriority,
    )
    # NodeProtocolClient/Server may not exist in all versions
    try:
        from core.node_protocol import NodeProtocolClient, NodeProtocolServer
    except ImportError:
        NodeProtocolClient = None
        NodeProtocolServer = None
except ImportError:
    Message = MessageHeader = MessageType = MessagePriority = None
    NodeProtocolClient = NodeProtocolServer = None

try:
    from galaxy_gateway.protocol.aip_v3 import (
        AIPMessage, MessageType as AIPMessageType
    )
    AIPProtocol = None  # no AIPProtocol in v3; legacy enhancements only
except ImportError:
    AIPMessage = AIPMessageType = AIPProtocol = None

try:
    from nodes.common.mcp_adapter import MCPAdapter, PythonMCPAdapter
except ImportError:
    MCPAdapter = PythonMCPAdapter = None

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
        self._node_host = os.getenv("UFO_NODE_HOST", "localhost")
        self._master_brain: Optional[Any] = None

        # 加载节点注册表
        self._load_node_registry()

        # Agentic OS: obtain the MasterBrain reference (opt-in via GALAXY_MASTER_BRAIN_ENABLED).
        # Actual async startup (NATS connect + subscription) is deferred to startup() so
        # it can be properly awaited from a FastAPI lifespan or explicit caller.
        if os.environ.get("GALAXY_MASTER_BRAIN_ENABLED", "").lower() == "true":
            try:
                from core.master_brain import get_master_brain
                self._master_brain = get_master_brain()
                logger.info("GalaxyCore: MasterBrain enabled (call startup() to initialize)")
            except Exception as e:
                logger.warning(f"GalaxyCore: MasterBrain init failed: {e}")
                self._master_brain = None

    async def startup(self) -> None:
        """Perform async initialisation for GalaxyCore.

        Must be called from a running event loop (e.g. FastAPI lifespan).
        Safe to call multiple times — :class:`MasterBrain` guards against
        duplicate starts internally.
        """
        if self._master_brain is not None:
            try:
                result = await self._master_brain.start()
                if result.get("already_started"):
                    logger.info("GalaxyCore.startup: MasterBrain already started")
                elif result.get("success"):
                    from core.nats_bus import nats_bus
                    logger.info(
                        "GalaxyCore.startup: MasterBrain started (NATS=%s)",
                        nats_bus.is_connected(),
                    )
                else:
                    logger.warning("GalaxyCore.startup: MasterBrain.start() returned %s", result)
            except Exception as exc:
                logger.warning("GalaxyCore.startup: MasterBrain start error: %s", exc)
    
    def _load_node_registry(self):
        """加载节点注册表"""
        registry_path = os.path.join(PROJECT_ROOT, "config", "node_registry.json")
        
        if os.path.exists(registry_path):
            try:
                with open(registry_path, "r", encoding="utf-8") as f:
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
        endpoint = f"http://{self._node_host}:{port}"
        
        params = params or {}
        
        try:
            client = await self._get_http_client()

            # 使用 /mcp/call 接口 (已有)
            logger.info(f"调用节点 {node_id} ({node.get('name', '?')}): action={action}, endpoint={endpoint}/mcp/call")
            response = await client.post(
                f"{endpoint}/mcp/call",
                json={"tool": action, "params": params},
                timeout=10.0
            )

            if response.status_code == 200:
                return response.json()

            # 第一种方式失败，尝试直接调用
            logger.info(f"节点 {node_id} /mcp/call 返回 {response.status_code}，尝试直接调用 /{action}")
            response = await client.post(
                f"{endpoint}/{action}",
                json=params,
                timeout=10.0
            )
            response.raise_for_status()

            return response.json()

        except httpx.TimeoutException:
            logger.error(f"调用节点 {node_id} ({node.get('name', '?')}) 超时: endpoint={endpoint}, action={action}")
            return {"success": False, "error": f"Node {node_id} request timeout"}
        except httpx.HTTPStatusError as e:
            logger.error(f"调用节点 {node_id} ({node.get('name', '?')}) HTTP错误: status={e.response.status_code}, action={action}")
            return {"success": False, "error": f"Node {node_id} returned HTTP {e.response.status_code}"}
        except Exception as e:
            logger.error(f"调用节点 {node_id} ({node.get('name', '?')}) 失败: {type(e).__name__}: {e}")
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
                f"http://{self._node_host}:{port}/protocol/message",
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
        # Construct AIPMessage for protocol validation only; the message object
        # is not dispatched here because register_device stores device info
        # locally in self.devices.  AIPMessage / AIPMessageType may be None
        # when the optional device-protocol extension package is not installed.
        if AIPMessage is not None and AIPMessageType is not None:
            AIPMessage(  # protocol validation — raises ValidationError on bad input
                type=AIPMessageType.DEVICE_REGISTER,
                device_id=device_id,
                payload={
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
        智能调用 - 优先通过 MasterBrain 分布式路由，降级为 Node_04_Router
        """
        # Agentic OS: if MasterBrain available and target is remote worker
        if self._master_brain is not None:
            p = params or {}
            if p.get("_distributed") or p.get("target_worker_id"):
                try:
                    result = await self._master_brain.dispatch_task({
                        "task_type": capability,
                        "target_worker_id": p.get("target_worker_id", ""),
                        "target_device_type": p.get("device_type", "unknown"),
                        "context": {"capability": capability, "action": action},
                        **({"code_payload": p["code_payload"]} if "code_payload" in p else {}),
                        **({"shell_payload": p["shell_payload"]} if "shell_payload" in p else {}),
                        **({"device_payload": p["device_payload"]} if "device_payload" in p else {}),
                    })
                    if result.get("success"):
                        return result
                    logger.info(f"MasterBrain dispatch failed, falling back to local: {result.get('error')}")
                except Exception as e:
                    logger.warning(f"MasterBrain dispatch error, falling back: {e}")

        # Fallback: 通过 Router 节点路由
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
