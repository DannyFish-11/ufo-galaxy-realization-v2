#!/usr/bin/env python3
"""
Galaxy Fusion - Node Adapter Base Class (Reinforced)

节点适配器基类（加固版）

将你的 FastAPI 节点适配为微软 UFO 的 Device Agent，
实现 AIP 协议接口，并提供稳健的底层通信逻辑。

作者: Manus AI
日期: 2026-01-26
版本: 1.2.0 (生产级加固)
"""

import asyncio
import logging
import sys
import aiohttp
import time
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
from pathlib import Path

# 添加微软 UFO 到 Python 路径
MICROSOFT_UFO_PATH = Path(__file__).parent.parent / "microsoft-ufo"
if str(MICROSOFT_UFO_PATH) not in sys.path:
    sys.path.insert(0, str(MICROSOFT_UFO_PATH))

try:
    from aip.endpoints.client_endpoint import DeviceClientEndpoint
    from aip.messages import (
        ClientMessage, ServerMessage, Command, Result,
        ResultStatus, TaskStatus, ClientMessageType, ClientType
    )
    AIP_AVAILABLE = True
except ImportError as e:
    logging.warning(f"⚠️  Microsoft UFO AIP not available: {e}")
    AIP_AVAILABLE = False
    # 创建模拟类
    class DeviceClientEndpoint:
        def __init__(self, device_id, server_url): pass
        async def connect(self): pass
        async def disconnect(self): pass
    class Command: pass
    class Result:
        def __init__(self, status, result=None, error=None):
            self.status = status
            self.result = result
            self.error = error
    class ResultStatus:
        SUCCESS = "success"
        FAILURE = "failure"

logger = logging.getLogger("NodeAdapter")


class UFONodeAdapter(DeviceClientEndpoint if AIP_AVAILABLE else object, ABC):
    """
    UFO 节点适配器基类
    
    将你的 FastAPI 节点适配为微软 UFO 的 Device Agent
    """
    
    def __init__(
        self,
        node_id: str,
        node_name: str,
        layer: str,
        domain: str,
        server_url: str,
        node_api_url: str,
        capabilities: Optional[List[str]] = None,
        timeout: int = 10
    ):
        # 初始化 DeviceClientEndpoint (如果可用)
        if AIP_AVAILABLE:
            super().__init__(
                device_id=node_id,
                server_url=server_url
            )
        
        self.node_id = node_id
        self.node_name = node_name
        self.layer = layer
        self.domain = domain
        self.server_url = server_url
        self.node_api_url = node_api_url.rstrip('/')
        self._capabilities = capabilities or self.get_capabilities()
        self.timeout = timeout
        
        # HTTP 客户端
        self.http_session: Optional[aiohttp.ClientSession] = None
        
        # 状态跟踪
        self.is_connected = False
        self.is_healthy = False
        self.current_task: Optional[str] = None
        self.last_check_time = 0
        
        logger.info(f"🔌 Node adapter initialized: {self.node_id} ({self.node_name})")

    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 aiohttp 会话"""
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            )
        return self.http_session

    async def start(self):
        """启动适配器"""
        try:
            # 确保会话已创建
            await self._get_session()
            
            # 测试节点连接
            self.is_healthy = await self.health_check()
            
            # 注册到微软 Galaxy (如果 AIP 可用)
            if AIP_AVAILABLE:
                await self.connect()
                self.is_connected = True
                logger.info(f"✅ Node adapter started and connected: {self.node_id}")
            else:
                logger.warning(f"⚠️  AIP not available, running in standalone mode: {self.node_id}")
        
        except Exception as e:
            logger.error(f"❌ Failed to start node adapter {self.node_id}: {e}")
            raise
    
    async def stop(self):
        """停止适配器并清理资源"""
        try:
            if self.http_session and not self.http_session.closed:
                await self.http_session.close()
            
            if AIP_AVAILABLE and self.is_connected:
                await self.disconnect()
                self.is_connected = False
            
            logger.info(f"🛑 Node adapter stopped: {self.node_id}")
        except Exception as e:
            logger.error(f"❌ Failed to stop node adapter {self.node_id}: {e}")

    async def health_check(self) -> bool:
        """健康检查 - 测试节点是否可访问 (真实逻辑)"""
        try:
            session = await self._get_session()
            url = f"{self.node_api_url}/health"
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.is_healthy = data.get("status") == "healthy" or data.get("success") == True
                    self.last_check_time = time.time()
                    return self.is_healthy
                return False
        except Exception as e:
            logger.warning(f"⚠️  Node {self.node_id} health check failed: {e}")
            self.is_healthy = False
            return False

    async def call_node_api(
        self,
        endpoint: str,
        method: str = "POST",
        data: Optional[Dict] = None,
        params: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """调用节点的 FastAPI 的标准实现 (真实逻辑)"""
        url = f"{self.node_api_url}{endpoint}"
        session = await self._get_session()
        
        try:
            async with session.request(method, url, json=data, params=params) as resp:
                if resp.status == 200:
                    return await resp.json()
                else:
                    error_text = await resp.text()
                    logger.error(f"❌ API call failed: {resp.status} - {error_text}")
                    return {"success": False, "error": f"HTTP {resp.status}", "details": error_text}
        except Exception as e:
            logger.error(f"❌ Node API call failed ({method} {url}): {e}")
            return {"success": False, "error": str(e)}

    @abstractmethod
    async def execute_command(self, command: 'Command') -> 'Result':
        """执行单个命令 - 子类必须实现"""
        pass
    
    @abstractmethod
    def get_capabilities(self) -> List[str]:
        """返回节点能力列表 - 子类必须实现"""
        pass
    
    def get_metadata(self) -> Dict[str, Any]:
        """返回节点元数据"""
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "layer": self.layer,
            "domain": self.domain,
            "capabilities": self._capabilities,
            "api_url": self.node_api_url,
            "is_connected": self.is_connected,
            "is_healthy": self.is_healthy
        }


class SimpleNodeAdapter(UFONodeAdapter):
    """简单节点适配器实现 (真实逻辑)"""
    
    def __init__(self, node_id, node_name, layer, domain, server_url, node_api_url, capabilities, command_handler=None):
        super().__init__(node_id, node_name, layer, domain, server_url, node_api_url, capabilities)
        self.command_handler = command_handler
    
    async def execute_command(self, command: 'Command') -> 'Result':
        """执行命令的真实逻辑"""
        if self.command_handler:
            return await self.command_handler(command)
        
        # 默认调用节点的 /execute 接口
        # 处理 command 对象，提取其内容
        cmd_str = str(command)
        if hasattr(command, 'to_dict'):
            cmd_data = command.to_dict()
        else:
            cmd_data = {"command": cmd_str}
            
        res = await self.call_node_api("/execute", data=cmd_data)
        
        if AIP_AVAILABLE:
            status = ResultStatus.SUCCESS if res.get("success", True) else ResultStatus.FAILURE
            return Result(status=status, result=res.get("data"), error=res.get("error"))
        
        return res
    
    def get_capabilities(self) -> List[str]:
        return self._capabilities
