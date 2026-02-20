#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Node_74_DigitalTwin: 数字孪生节点主服务

该服务用于创建一个物理设备的数字孪生体，通过模拟数据源同步设备状态，
并提供API接口用于查询孪生体的状态和健康状况。
"""

import asyncio
import logging
import json
import random
import uuid
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional

# 使用 FastAPI 作为 Web 框架，提供 API 接口
from fastapi import FastAPI, HTTPException
from uvicorn import Config, Server

# --- 配置和日志 --- #

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger("DigitalTwinService")

# --- 枚举和数据类定义 --- #

class ServiceStatus(Enum):
    """服务运行状态枚举"""
    INITIALIZING = "正在初始化"
    RUNNING = "正在运行"
    STOPPED = "已停止"
    ERROR = "出现错误"

class DeviceStatus(Enum):
    """物理设备状态枚举"""
    ONLINE = "在线"
    OFFLINE = "离线"
    MAINTENANCE = "维护中"

@dataclass
class DigitalTwinConfig:
    """数字孪生节点配置"""
    node_id: str = field(default_factory=lambda: f"Node_74_DigitalTwin_{uuid.uuid4().hex[:8]}")
    host: str = "0.0.0.0"
    port: int = 8074
    simulation_interval_seconds: float = 5.0  # 模拟物理设备状态更新的间隔
    device_id: str = "Device_XYZ_001"

@dataclass
class DeviceState:
    """设备状态数据模型"""
    timestamp: str
    status: DeviceStatus
    temperature: float
    humidity: float
    location: Dict[str, float]
    metadata: Dict[str, Any] = field(default_factory=dict)

# --- 主服务类 --- #

class DigitalTwinService:
    """数字孪生主服务类"""

    def __init__(self, config: DigitalTwinConfig):
        """初始化服务"""
        self.config = config
        self.status = ServiceStatus.INITIALIZING
        self.start_time = None
        self.twin_state: Optional[DeviceState] = None
        self.app = FastAPI(
            title="Node_74_DigitalTwin API",
            description="用于与数字孪生节点交互的API",
            version="1.0.0"
        )
        self._setup_routes()
        logger.info(f"服务 {self.config.node_id} 正在初始化...")

    def _setup_routes(self):
        """配置 FastAPI 路由"""
        self.app.add_api_route("/health", self.health_check, methods=["GET"], summary="健康检查")
        self.app.add_api_route("/status", self.get_service_status, methods=["GET"], summary="服务状态查询")
        self.app.add_api_route("/twin/state", self.get_twin_state, methods=["GET"], summary="获取数字孪生状态")

    async def health_check(self) -> Dict[str, str]:
        """提供健康检查端点，确认服务是否正常运行"""
        logger.info("接收到健康检查请求")
        return {"status": "ok", "node_id": self.config.node_id}

    async def get_service_status(self) -> Dict[str, Any]:
        """提供服务状态查询接口"""
        logger.info("接收到服务状态查询请求")
        uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds() if self.start_time else 0
        return {
            "node_id": self.config.node_id,
            "service_status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "uptime_seconds": round(uptime, 2),
            "config": asdict(self.config)
        }

    async def get_twin_state(self) -> Dict[str, Any]:
        """获取当前数字孪生的状态"""
        logger.info("接收到孪生状态查询请求")
        if self.twin_state is None:
            raise HTTPException(status_code=404, detail="数字孪生状态尚未初始化")
        return asdict(self.twin_state)

    async def _simulate_physical_device(self):
        """模拟物理设备，定期生成并更新状态"""
        logger.info(f"启动对物理设备 {self.config.device_id} 的状态模拟...")
        while self.status == ServiceStatus.RUNNING:
            try:
                # 模拟生成设备数据
                new_state = DeviceState(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    status=random.choice([DeviceStatus.ONLINE, DeviceStatus.ONLINE, DeviceStatus.OFFLINE, DeviceStatus.MAINTENANCE]),
                    temperature=round(random.uniform(15.0, 30.0), 2),
                    humidity=round(random.uniform(40.0, 60.0), 2),
                    location={"latitude": round(random.uniform(30.0, 40.0), 6), "longitude": round(random.uniform(110.0, 120.0), 6)},
                    metadata={
                        "firmware_version": "v1.2.3",
                        "battery_level": round(random.uniform(0.1, 1.0), 2)
                    }
                )
                
                # 更新数字孪生状态
                self.twin_state = new_state
                logger.info(f"数字孪生状态已更新: 温度={new_state.temperature}°C, 湿度={new_state.humidity}%RH")
                
                await asyncio.sleep(self.config.simulation_interval_seconds)
            except asyncio.CancelledError:
                logger.info("物理设备模拟任务被取消")
                break
            except Exception as e:
                logger.error(f"物理设备模拟循环中发生错误: {e}", exc_info=True)
                self.status = ServiceStatus.ERROR
                break

    async def start(self):
        """启动服务和所有后台任务"""
        self.status = ServiceStatus.RUNNING
        self.start_time = datetime.now(timezone.utc)
        logger.info(f"服务 {self.config.node_id} 已启动，运行在 {self.config.host}:{self.config.port}")

        # 启动后台模拟任务
        self.simulation_task = asyncio.create_task(self._simulate_physical_device())

        # 启动Web服务器
        server_config = Config(app=self.app, host=self.config.host, port=self.config.port, log_level="warning")
        server = Server(server_config)
        await server.serve()

    async def stop(self):
        """停止服务和所有后台任务"""
        logger.info(f"正在停止服务 {self.config.node_id}...")
        self.status = ServiceStatus.STOPPED
        if self.simulation_task:
            self.simulation_task.cancel()
            await self.simulation_task
        logger.info(f"服务 {self.config.node_id} 已成功停止")

# --- 程序入口 --- #

async def main():
    """主执行函数"""
    try:
        # 1. 加载配置
        config = DigitalTwinConfig()
        logger.info("配置加载成功")

        # 2. 初始化服务
        service = DigitalTwinService(config)

        # 3. 启动服务
        await service.start()

    except Exception as e:
        logger.error(f"服务启动失败: {e}", exc_info=True)
        # 在实际应用中，这里可以添加更复杂的错误恢复逻辑

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("检测到手动中断，程序退出")

# --- 扩展功能：状态历史记录 --- #

from collections import deque

MAX_HISTORY_LENGTH = 50

class DigitalTwinService:
    """数字孪生主服务类（扩展版本）"""

    def __init__(self, config: DigitalTwinConfig):
        """初始化服务"""
        self.config = config
        self.status = ServiceStatus.INITIALIZING
        self.start_time = None
        self.twin_state: Optional[DeviceState] = None
        self.state_history: deque = deque(maxlen=MAX_HISTORY_LENGTH)
        self.app = FastAPI(
            title="Node_74_DigitalTwin API",
            description="用于与数字孪生节点交互的API",
            version="1.1.0"  # 版本升级
        )
        self._setup_routes()
        logger.info(f"服务 {self.config.node_id} 正在初始化 (扩展版本)...")

    def _setup_routes(self):
        """配置 FastAPI 路由（扩展）"""
        self.app.add_api_route("/health", self.health_check, methods=["GET"], summary="健康检查")
        self.app.add_api_route("/status", self.get_service_status, methods=["GET"], summary="服务状态查询")
        self.app.add_api_route("/twin/state", self.get_twin_state, methods=["GET"], summary="获取当前数字孪生状态")
        self.app.add_api_route("/twin/history", self.get_twin_history, methods=["GET"], summary="获取数字孪生状态历史")

    async def get_twin_history(self) -> Dict[str, Any]:
        """获取数字孪生的状态历史记录"""
        logger.info(f"接收到来自客户端的状态历史查询请求，将返回最近 {len(self.state_history)} 条记录")
        return {
            "device_id": self.config.device_id,
            "history_count": len(self.state_history),
            "history": list(self.state_history)
        }

    async def _simulate_physical_device(self):
        """模拟物理设备，定期生成并更新状态（扩展版本）"""
        logger.info(f"启动对物理设备 {self.config.device_id} 的状态模拟 (扩展版本)...")
        cycle_count = 0
        while self.status == ServiceStatus.RUNNING:
            try:
                cycle_count += 1
                # 模拟更丰富的设备数据
                new_state = DeviceState(
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    status=random.choice([DeviceStatus.ONLINE] * 8 + [DeviceStatus.OFFLINE, DeviceStatus.MAINTENANCE]), # 提高在线概率
                    temperature=round(random.uniform(18.0, 28.0) + (cycle_count % 10) * 0.1, 2),
                    humidity=round(random.uniform(45.0, 55.0) - (cycle_count % 10) * 0.05, 2),
                    location={"latitude": 34.0522, "longitude": -118.2437}, # 固定地点以模拟静态设备
                    metadata={
                        "firmware_version": "v1.2.4",
                        "battery_level": round(max(0, 1.0 - (cycle_count / 5000)), 2),
                        "signal_strength": random.randint(-90, -50),
                        "error_code": random.choice([0] * 95 + list(range(1, 6))) # 模拟偶发错误码
                    }
                )
                
                # 更新数字孪生状态并记录历史
                self.twin_state = new_state
                self.state_history.append(asdict(new_state))
                logger.info(f"[Cycle {cycle_count}] 数字孪生状态已更新: Temp={new_state.temperature}°C, Bat={new_state.metadata['battery_level']}")
                
                await asyncio.sleep(self.config.simulation_interval_seconds)
            except asyncio.CancelledError:
                logger.warning("物理设备模拟任务被优雅地取消")
                break
            except Exception as e:
                logger.critical(f"物理设备模拟循环中发生严重错误: {e}", exc_info=True)
                self.status = ServiceStatus.ERROR
                break

    # 保留其他方法不变，仅在 __main__ 中使用新版 Service
    async def health_check(self) -> Dict[str, str]:
        logger.info("健康检查请求已处理")
        return {"status": "ok", "node_id": self.config.node_id, "version": "1.1.0"}

    async def get_service_status(self) -> Dict[str, Any]:
        logger.info("服务状态查询请求已处理")
        uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds() if self.start_time else 0
        return {
            "node_id": self.config.node_id,
            "service_status": self.status.value,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "uptime_seconds": round(uptime, 2),
            "config": asdict(self.config),
            "history_buffer_size": len(self.state_history),
            "history_buffer_capacity": MAX_HISTORY_LENGTH
        }

    async def get_twin_state(self) -> Dict[str, Any]:
        logger.info("当前孪生状态查询请求已处理")
        if self.twin_state is None:
            raise HTTPException(status_code=404, detail="数字孪生状态尚未初始化，请稍后再试")
        return asdict(self.twin_state)

    async def start(self):
        """启动服务和所有后台任务"""
        self.status = ServiceStatus.RUNNING
        self.start_time = datetime.now(timezone.utc)
        logger.info(f"服务 {self.config.node_id} (v1.1.0) 已启动，监听于 {self.config.host}:{self.config.port}")
        self.simulation_task = asyncio.create_task(self._simulate_physical_device())
        server_config = Config(app=self.app, host=self.config.host, port=self.config.port, log_level="info")
        server = Server(server_config)
        await server.serve()

    async def stop(self):
        """停止服务和所有后台任务"""
        logger.info(f"正在停止服务 {self.config.node_id}...")
        self.status = ServiceStatus.STOPPED
        if hasattr(self, 'simulation_task') and self.simulation_task:
            self.simulation_task.cancel()
            try:
                await self.simulation_task
            except asyncio.CancelledError:
                pass # 任务取消是预期的
        logger.info(f"服务 {self.config.node_id} 已成功停止")
