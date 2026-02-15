#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连接管理器 (Connection Manager)
================================

向日葵风格的稳定连接、重连和保活系统
用于管理与节点、网关和其他服务的连接

功能：
1. 心跳/保活机制
2. 断线检测和自动重连
3. 指数退避重连策略
4. 连接健康状态跟踪
5. 连接池管理

作者：Manus AI (Round 2 - R-4)
日期：2026-02-11
"""

import asyncio
import httpx
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json

logger = logging.getLogger("ConnectionManager")


# ============================================================================
# 连接状态定义
# ============================================================================

class ConnectionState(Enum):
    """连接状态"""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    CLOSED = "closed"


# ============================================================================
# 连接配置和数据模型
# ============================================================================

@dataclass
class ConnectionConfig:
    """连接配置"""
    url: str
    timeout: float = 5.0
    heartbeat_interval: float = 30.0  # 心跳间隔（秒）
    max_retries: int = 5
    initial_retry_delay: float = 1.0  # 初始重试延迟（秒）
    max_retry_delay: float = 60.0  # 最大重试延迟（秒）
    retry_backoff_factor: float = 2.0  # 重试退避因子
    health_check_path: str = "/health"
    

@dataclass
class ConnectionInfo:
    """连接信息"""
    connection_id: str
    url: str
    state: ConnectionState = ConnectionState.DISCONNECTED
    connected_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    retry_count: int = 0
    last_error: Optional[str] = None
    total_reconnects: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "connection_id": self.connection_id,
            "url": self.url,
            "state": self.state.value,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
            "total_reconnects": self.total_reconnects
        }


# ============================================================================
# 连接管理器
# ============================================================================

class ConnectionManager:
    """
    连接管理器 - 向日葵风格的连接管理
    
    管理所有外部连接，提供心跳、重连和健康检查
    """
    
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, config_dir: Optional[Path] = None):
        if self._initialized:
            return
        
        self.config_dir = config_dir or Path(__file__).parent.parent / "config"
        self.state_file = self.config_dir / "connection_state.json"
        
        # 连接池
        self.connections: Dict[str, ConnectionInfo] = {}
        self.configs: Dict[str, ConnectionConfig] = {}
        self.clients: Dict[str, httpx.AsyncClient] = {}
        
        # 心跳任务
        self.heartbeat_tasks: Dict[str, asyncio.Task] = {}
        
        # 回调函数
        self.on_connected_callbacks: Dict[str, List[Callable]] = {}
        self.on_disconnected_callbacks: Dict[str, List[Callable]] = {}
        
        self._lock = asyncio.Lock()
        self._running = False
        self._initialized = True
        
        logger.info("连接管理器已初始化")
    
    # ========================================================================
    # 连接管理
    # ========================================================================
    
    async def register_connection(
        self,
        connection_id: str,
        url: str,
        config: Optional[ConnectionConfig] = None
    ) -> bool:
        """
        注册连接
        
        Args:
            connection_id: 连接标识
            url: 连接URL
            config: 连接配置（可选）
            
        Returns:
            是否注册成功
        """
        async with self._lock:
            if connection_id in self.connections:
                logger.warning(f"连接已存在，将覆盖: {connection_id}")
            
            # 创建连接信息
            self.connections[connection_id] = ConnectionInfo(
                connection_id=connection_id,
                url=url
            )
            
            # 保存配置
            self.configs[connection_id] = config or ConnectionConfig(url=url)
            
            # 创建 HTTP 客户端
            self.clients[connection_id] = httpx.AsyncClient(
                timeout=self.configs[connection_id].timeout
            )
            
            logger.info(f"连接已注册: {connection_id} -> {url}")
            
            return True
    
    async def connect(self, connection_id: str) -> bool:
        """
        建立连接
        
        Args:
            connection_id: 连接标识
            
        Returns:
            是否连接成功
        """
        if connection_id not in self.connections:
            logger.error(f"连接未注册: {connection_id}")
            return False
        
        conn_info = self.connections[connection_id]
        config = self.configs[connection_id]
        
        conn_info.state = ConnectionState.CONNECTING
        
        try:
            # 尝试健康检查
            is_healthy = await self._check_health(connection_id)
            
            if is_healthy:
                conn_info.state = ConnectionState.CONNECTED
                conn_info.connected_at = datetime.now()
                conn_info.last_heartbeat = datetime.now()
                conn_info.retry_count = 0
                conn_info.last_error = None
                
                # 启动心跳任务
                await self._start_heartbeat(connection_id)
                
                # 触发回调
                await self._trigger_callbacks(connection_id, self.on_connected_callbacks)
                
                logger.info(f"连接已建立: {connection_id}")
                return True
            else:
                conn_info.state = ConnectionState.ERROR
                conn_info.last_error = "健康检查失败"
                return False
                
        except Exception as e:
            conn_info.state = ConnectionState.ERROR
            conn_info.last_error = str(e)
            logger.error(f"连接失败 {connection_id}: {e}")
            return False
    
    async def disconnect(self, connection_id: str, graceful: bool = True) -> bool:
        """
        断开连接
        
        Args:
            connection_id: 连接标识
            graceful: 是否优雅关闭
            
        Returns:
            是否断开成功
        """
        if connection_id not in self.connections:
            return False
        
        conn_info = self.connections[connection_id]
        
        # 停止心跳
        await self._stop_heartbeat(connection_id)
        
        # 关闭客户端
        if connection_id in self.clients:
            await self.clients[connection_id].aclose()
        
        # 更新状态
        conn_info.state = ConnectionState.CLOSED if graceful else ConnectionState.DISCONNECTED
        
        # 触发回调
        await self._trigger_callbacks(connection_id, self.on_disconnected_callbacks)
        
        logger.info(f"连接已断开: {connection_id}")
        
        return True
    
    async def reconnect(self, connection_id: str) -> bool:
        """
        重新连接（带指数退避）
        
        Args:
            connection_id: 连接标识
            
        Returns:
            是否重连成功
        """
        if connection_id not in self.connections:
            logger.error(f"连接未注册: {connection_id}")
            return False
        
        conn_info = self.connections[connection_id]
        config = self.configs[connection_id]
        
        conn_info.state = ConnectionState.RECONNECTING
        
        while conn_info.retry_count < config.max_retries:
            # 计算退避延迟
            delay = min(
                config.initial_retry_delay * (config.retry_backoff_factor ** conn_info.retry_count),
                config.max_retry_delay
            )
            
            logger.info(
                f"重连尝试 {conn_info.retry_count + 1}/{config.max_retries} "
                f"for {connection_id}，延迟 {delay:.1f}s"
            )
            
            await asyncio.sleep(delay)
            
            # 尝试连接
            if await self.connect(connection_id):
                conn_info.total_reconnects += 1
                logger.info(f"重连成功: {connection_id}")
                return True
            
            conn_info.retry_count += 1
        
        # 重连失败
        logger.error(f"重连失败，已达最大重试次数: {connection_id}")
        conn_info.state = ConnectionState.ERROR
        conn_info.last_error = "重连失败，超过最大重试次数"
        
        return False
    
    # ========================================================================
    # 心跳和健康检查
    # ========================================================================
    
    async def _check_health(self, connection_id: str) -> bool:
        """检查连接健康"""
        if connection_id not in self.clients:
            return False
        
        config = self.configs[connection_id]
        client = self.clients[connection_id]
        
        try:
            health_url = f"{config.url.rstrip('/')}{config.health_check_path}"
            response = await client.get(health_url)
            return response.status_code == 200
        except Exception as e:
            logger.debug(f"健康检查失败 {connection_id}: {e}")
            return False
    
    async def _heartbeat_loop(self, connection_id: str):
        """心跳循环"""
        config = self.configs[connection_id]
        conn_info = self.connections[connection_id]
        
        logger.debug(f"心跳循环已启动: {connection_id}")
        
        while self._running and conn_info.state == ConnectionState.CONNECTED:
            await asyncio.sleep(config.heartbeat_interval)
            
            # 执行健康检查
            is_healthy = await self._check_health(connection_id)
            
            if is_healthy:
                conn_info.last_heartbeat = datetime.now()
                logger.debug(f"心跳正常: {connection_id}")
            else:
                logger.warning(f"心跳失败，启动重连: {connection_id}")
                conn_info.state = ConnectionState.DISCONNECTED
                
                # 触发重连
                asyncio.create_task(self.reconnect(connection_id))
                break
    
    async def _start_heartbeat(self, connection_id: str):
        """启动心跳任务"""
        if connection_id in self.heartbeat_tasks:
            # 已有心跳任务，先取消
            self.heartbeat_tasks[connection_id].cancel()
        
        self._running = True
        task = asyncio.create_task(self._heartbeat_loop(connection_id))
        self.heartbeat_tasks[connection_id] = task
    
    async def _stop_heartbeat(self, connection_id: str):
        """停止心跳任务"""
        if connection_id in self.heartbeat_tasks:
            task = self.heartbeat_tasks[connection_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            del self.heartbeat_tasks[connection_id]
    
    # ========================================================================
    # 回调管理
    # ========================================================================
    
    def on_connected(self, connection_id: str, callback: Callable):
        """注册连接成功回调"""
        if connection_id not in self.on_connected_callbacks:
            self.on_connected_callbacks[connection_id] = []
        self.on_connected_callbacks[connection_id].append(callback)
    
    def on_disconnected(self, connection_id: str, callback: Callable):
        """注册断开连接回调"""
        if connection_id not in self.on_disconnected_callbacks:
            self.on_disconnected_callbacks[connection_id] = []
        self.on_disconnected_callbacks[connection_id].append(callback)
    
    async def _trigger_callbacks(self, connection_id: str, callback_dict: Dict[str, List[Callable]]):
        """触发回调函数"""
        if connection_id in callback_dict:
            for callback in callback_dict[connection_id]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(connection_id)
                    else:
                        callback(connection_id)
                except Exception as e:
                    logger.error(f"回调执行失败 {connection_id}: {e}")
    
    # ========================================================================
    # 查询和统计
    # ========================================================================
    
    def get_connection(self, connection_id: str) -> Optional[ConnectionInfo]:
        """获取连接信息"""
        return self.connections.get(connection_id)
    
    def get_all_connections(self) -> List[ConnectionInfo]:
        """获取所有连接"""
        return list(self.connections.values())
    
    def get_connected_connections(self) -> List[ConnectionInfo]:
        """获取所有已连接的连接"""
        return [
            conn for conn in self.connections.values()
            if conn.state == ConnectionState.CONNECTED
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """获取连接统计"""
        total = len(self.connections)
        connected = len([c for c in self.connections.values() if c.state == ConnectionState.CONNECTED])
        disconnected = len([c for c in self.connections.values() if c.state == ConnectionState.DISCONNECTED])
        error = len([c for c in self.connections.values() if c.state == ConnectionState.ERROR])
        
        return {
            "total_connections": total,
            "connected": connected,
            "disconnected": disconnected,
            "error": error,
            "reconnecting": total - connected - disconnected - error
        }
    
    def get_health_report(self) -> Dict[str, Any]:
        """获取健康报告"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "stats": self.get_stats(),
            "connections": []
        }
        
        for conn in self.connections.values():
            report["connections"].append(conn.to_dict())
        
        return report
    
    # ========================================================================
    # 状态持久化
    # ========================================================================
    
    async def save_state(self):
        """保存连接状态"""
        try:
            self.config_dir.mkdir(exist_ok=True, parents=True)
            
            state = {
                "timestamp": datetime.now().isoformat(),
                "connections": [conn.to_dict() for conn in self.connections.values()]
            }
            
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"连接状态已保存")
            
        except Exception as e:
            logger.error(f"保存连接状态失败: {e}")
    
    # ========================================================================
    # 生命周期管理
    # ========================================================================
    
    async def start_all(self):
        """启动所有连接"""
        for connection_id in self.connections:
            await self.connect(connection_id)
    
    async def stop_all(self):
        """停止所有连接"""
        self._running = False
        for connection_id in list(self.connections.keys()):
            await self.disconnect(connection_id)
    
    async def shutdown(self):
        """关闭连接管理器"""
        await self.stop_all()
        
        # 关闭所有客户端
        for client in self.clients.values():
            await client.aclose()
        
        await self.save_state()
        
        logger.info("连接管理器已关闭")


# ============================================================================
# 全局实例
# ============================================================================

_connection_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """获取全局连接管理器实例"""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager
