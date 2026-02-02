#!/usr/bin/env python3
"""
UFO Galaxy Fusion - Node Executor (Gateway Optimized & Reinforced)

节点执行器（网关优化加固版）

核心职责:
1. 通过统一网关 (Unified Gateway) 与 102 个节点通信
2. 简化连接管理，不再需要维护 102 个端口
3. 提供统一的异常处理、重试机制和结果封装
4. 真实实现健康检查和状态监控

作者: Manus AI
日期: 2026-01-26
版本: 1.3.0 (生产级加固)
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
    执行池 - 优化为通过统一网关进行通信
    """
    
    def __init__(self, gateway_url: str = "http://localhost:8000"):
        self.gateway_url = gateway_url.rstrip('/')
        self.session: Optional[aiohttp.ClientSession] = None
        self._node_status: Dict[str, bool] = {}
        logger.info(f"🎯 ExecutionPool initialized using gateway: {self.gateway_url}")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30) # 网关模式建议超时设置长一点
            )
        return self.session

    async def execute_on_node(self, node_id: str, command: str, params: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """通过网关在指定节点上执行命令 (真实逻辑)"""
        start_time = time.time()
        # 统一网关路由格式
        url = f"{self.gateway_url}/api/nodes/{node_id}/execute"
        
        payload = {
            "command": command,
            "params": params or {}
        }
        
        # 包含重试逻辑
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
        """检查单个节点的健康状态"""
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
        """关闭网关连接会话"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("✅ Gateway session closed")

    def get_pool_status(self) -> Dict[str, Any]:
        """获取连接池状态统计"""
        total = len(self._node_status)
        online = sum(1 for status in self._node_status.values() if status)
        return {
            "total_tracked_nodes": total,
            "online_nodes": online,
            "offline_nodes": total - online,
            "gateway_url": self.gateway_url
        }
