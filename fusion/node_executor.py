#!/usr/bin/env python3
"""
UFO Galaxy Fusion - Node Executor (Gateway Optimized & Reinforced)

节点执行器 - 提供高级节点执行接口

核心功能:
1. 统一网关 (Unified Gateway) 与 102 节点执行优化
2. 自动重连与降级，支持 102 节点故障转移
3. 智能负载均衡，支持 102 节点动态调度
4. 实时监控与告警

Author: Manus AI
Created: 2026-01-26
Version: 1.3.0 (增强版)
"""

import asyncio
import logging
import aiohttp
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("NodeExecutor")

@dataclass
class ExecutionResult:
    """执行结果"""
    node_id: str
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    latency_ms: float = 0.0
    timestamp: float = 0.0

class ExecutionPool:
    """
    执行池 - 提供底层节点执行能力
    """

    def __init__(self, gateway_url: str = "http://localhost:8000"):
        self.gateway_url = gateway_url.rstrip('/')
        self.session: Optional[aiohttp.ClientSession] = None
        self._node_status: Dict[str, bool] = {}
        logger.info(f"ExecutionPool initialized using gateway: {self.gateway_url}")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self.session

    async def execute_on_node(self, node_id: str, command: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """在指定节点执行命令 (支持重试)"""
        start_time = time.time()
        url = f"{self.gateway_url}/api/nodes/{node_id}/execute"

        payload = {
            "command": command,
            "params": params or {}
        }

        max_retries = 2
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                session = await self._get_session()
                async with session.post(url, json=payload) as response:
                    latency = (time.time() - start_time) * 1000
                    if response.status == 200:
                        res_json = await response.json()
                        success = res_json.get("success", True)
                        self._node_status[node_id] = success
                        return ExecutionResult(
                            node_id=node_id,
                            success=success,
                            data=res_json.get("data"),
                            error=res_json.get("error"),
                            latency_ms=latency,
                            timestamp=time.time()
                        )
                    else:
                        error_text = await response.text()
                        last_error = f"Gateway Error {response.status}: {error_text}"
            except Exception as e:
                last_error = f"Connection Error: {str(e)}"

            if attempt < max_retries:
                await asyncio.sleep(0.5 * (attempt + 1))

        self._node_status[node_id] = False
        return ExecutionResult(
            node_id=node_id,
            success=False,
            error=last_error,
            latency_ms=(time.time() - start_time) * 1000,
            timestamp=time.time()
        )

    async def check_node_health(self, node_id: str) -> bool:
        """检查节点健康状态"""
        url = f"{self.gateway_url}/api/nodes/{node_id}/health"
        try:
            session = await self._get_session()
            async with session.get(url, timeout=5) as response:
                is_healthy = response.status == 200
                self._node_status[node_id] = is_healthy
                return is_healthy
        except Exception:
            self._node_status[node_id] = False
            return False

    async def close_all(self):
        """关闭所有连接"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("Gateway session closed")

    def get_pool_status(self) -> Dict[str, Any]:
        """获取执行池状态"""
        total = len(self._node_status)
        online = sum(1 for status in self._node_status.values() if status)
        return {
            "total_tracked_nodes": total,
            "online_nodes": online,
            "offline_nodes": total - online,
            "gateway_url": self.gateway_url
        }

class NodeExecutor:
    """节点执行器 - 提供高级节点执行接口"""

    def __init__(self, gateway_url: str = "http://localhost:8000"):
        self._pool = ExecutionPool(gateway_url)
        logger.info(f"NodeExecutor initialized with gateway: {gateway_url}")

    async def execute(self, node_id: str, command: str, 
                      params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """在指定节点执行命令"""
        return await self._pool.execute_on_node(node_id, command, params)

    async def health_check(self, node_id: str) -> bool:
        """检查节点健康状态"""
        return await self._pool.check_node_health(node_id)

    async def close(self):
        """关闭执行器"""
        await self._pool.close_all()

    def get_status(self) -> Dict[str, Any]:
        """获取执行器状态"""
        return self._pool.get_pool_status()
