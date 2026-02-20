#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Node_38_BLE: 蓝牙低功耗 (BLE) 通信节点

该节点负责处理蓝牙低功耗设备的扫描、连接、数据读写和通知。
它提供了一个异步服务，可以与其他UFO Galaxy节点集成，
以实现复杂的物联网(IoT)应用场景。
"""

import asyncio
import logging
import platform
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Dict, List, Optional, Union

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

# --- 配置和日志 --- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("node_38_ble.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("Node_38_BLE")

# --- 枚举和数据类 --- #

class ServiceStatus(Enum):
    """服务状态枚举"""
    STOPPED = "stopped"
    RUNNING = "running"
    SCANNING = "scanning"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"

class BLECommand(Enum):
    """BLE操作命令枚举"""
    SCAN = "scan"
    CONNECT = "connect"
    DISCONNECT = "disconnect"
    READ_CHAR = "read_characteristic"
    WRITE_CHAR = "write_characteristic"
    SUBSCRIBE_NOTIFICATIONS = "subscribe_notifications"

@dataclass
class BLENodeConfig:
    """BLE节点配置"""
    scan_duration_seconds: int = 10
    default_connect_timeout: float = 20.0
    auto_reconnect: bool = True
    reconnect_delay_seconds: int = 5
    # 可以根据需要添加特定的设备地址或名称过滤器
    device_filters: List[Dict[str, str]] = field(default_factory=list)

@dataclass
class HealthStatus:
    """健康状态报告"""
    status: ServiceStatus
    uptime: float
    connected_device: Optional[str] = None
    error_message: Optional[str] = None

# --- 主服务类 --- #

class BLEService:
    """蓝牙低功耗通信服务"""

    def __init__(self, config: BLENodeConfig):
        """初始化服务"""
        self.config = config
        self._status = ServiceStatus.STOPPED
        self._client: Optional[BleakClient] = None
        self._target_device: Optional[Union[BLEDevice, str]] = None
        self._main_task: Optional[asyncio.Task] = None
        self._start_time = 0.0
        self._error_message: Optional[str] = None
        self.discovered_devices: Dict[str, BLEDevice] = {}

        logger.info(f"BLE服务已初始化，配置: {config}")

    async def start(self) -> None:
        """启动服务主循环"""
        if self._status == ServiceStatus.RUNNING:
            logger.warning("服务已在运行中。")
            return

        self._status = ServiceStatus.RUNNING
        self._start_time = asyncio.get_event_loop().time()
        logger.info("BLE服务已启动。")
        # 在实际应用中，这里可以有一个主循环来处理传入的命令
        # 此处仅为演示，保持服务运行状态
        try:
            while self._status == ServiceStatus.RUNNING:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            logger.info("服务主任务被取消。")
        finally:
            await self.stop()

    async def stop(self) -> None:
        """停止服务并断开连接"""
        if self._status == ServiceStatus.STOPPED:
            return

        logger.info("正在停止BLE服务...")
        if self._client and self._client.is_connected:
            await self.disconnect()

        if self._main_task:
            self._main_task.cancel()
            self._main_task = None

        self._status = ServiceStatus.STOPPED
        self._start_time = 0.0
        logger.info("BLE服务已停止。")

    async def scan(self, duration: Optional[int] = None) -> List[Dict[str, Any]]:
        """扫描附近的BLE设备"""
        scan_duration = duration or self.config.scan_duration_seconds
        logger.info(f"开始扫描BLE设备，持续 {scan_duration} 秒...")
        self._status = ServiceStatus.SCANNING
        self.discovered_devices.clear()

        scanner = BleakScanner()
        try:
            devices = await scanner.discover(timeout=scan_duration)
            for device in devices:
                self.discovered_devices[device.address] = device
            logger.info(f"扫描完成，发现 {len(self.discovered_devices)} 个设备。")
            
            # 返回可序列化的设备列表
            return [
                {
                    "name": dev.name,
                    "address": dev.address,
                    "rssi": dev.rssi,
                    "metadata": dev.metadata
                }
                for dev in self.discovered_devices.values()
            ]
        except Exception as e:
            logger.error(f"扫描过程中发生错误: {e}", exc_info=True)
            self._status = ServiceStatus.ERROR
            self._error_message = str(e)
            return []
        finally:
            if self._status == ServiceStatus.SCANNING:
                self._status = ServiceStatus.RUNNING

    async def connect(self, device_address: str) -> bool:
        """连接到指定的BLE设备"""
        if device_address not in self.discovered_devices:
            logger.error(f"设备地址 {device_address} 未在扫描中发现。请先执行扫描。")
            return False

        self._target_device = self.discovered_devices[device_address]
        logger.info(f"正在连接到设备: {self._target_device.name} ({self._target_device.address})")
        self._status = ServiceStatus.CONNECTING

        try:
            self._client = BleakClient(self._target_device, timeout=self.config.default_connect_timeout)
            await self._client.connect()
            self._status = ServiceStatus.CONNECTED
            logger.info(f"成功连接到设备: {self._target_device.address}")
            # 设置断开连接回调
            self._client.set_disconnected_callback(self._on_disconnect)
            return True
        except Exception as e:
            logger.error(f"连接到 {device_address} 失败: {e}", exc_info=True)
            self._status = ServiceStatus.ERROR
            self._error_message = str(e)
            self._client = None
            return False

    async def disconnect(self) -> None:
        """断开当前连接的设备"""
        if self._client and self._client.is_connected:
            logger.info(f"正在断开与 {self._client.address} 的连接...")
            await self._client.disconnect()
            # 回调 _on_disconnect 会处理状态更新
        else:
            logger.warning("没有活动的连接可以断开。")

    def _on_disconnect(self, client: BleakClient) -> None:
        """处理意外断开连接的回调"""
        logger.warning(f"与设备 {client.address} 的连接已断开。")
        self._status = ServiceStatus.RUNNING
        self._client = None
        # 如果配置了自动重连，则尝试重连
        if self.config.auto_reconnect and self._target_device:
            logger.info(f"将在 {self.config.reconnect_delay_seconds} 秒后尝试重连...")
            asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """自动重连逻辑"""
        await asyncio.sleep(self.config.reconnect_delay_seconds)
        if self._target_device:
            logger.info("正在尝试重连...")
            await self.connect(self._target_device.address)

    async def read_characteristic(self, char_uuid: str) -> Optional[bytearray]:
        """读取特征值"""
        if not self._client or not self._client.is_connected:
            logger.error("读取特征失败：未连接到任何设备。")
            return None
        try:
            value = await self._client.read_gatt_char(char_uuid)
            logger.info(f"从特征 {char_uuid} 读取到值: {value.hex()}")
            return value
        except Exception as e:
            logger.error(f"读取特征 {char_uuid} 失败: {e}", exc_info=True)
            self._error_message = str(e)
            return None

    async def write_characteristic(self, char_uuid: str, data: bytes, with_response: bool = True) -> bool:
        """向特征写入数据"""
        if not self._client or not self._client.is_connected:
            logger.error("写入特征失败：未连接到任何设备。")
            return False
        try:
            await self._client.write_gatt_char(char_uuid, data, response=with_response)
            logger.info(f"向特征 {char_uuid} 写入数据: {data.hex()}")
            return True
        except Exception as e:
            logger.error(f"写入特征 {char_uuid} 失败: {e}", exc_info=True)
            self._error_message = str(e)
            return False

    async def subscribe_to_notifications(self, char_uuid: str, callback: callable) -> bool:
        """订阅特征通知"""
        if not self._client or not self._client.is_connected:
            logger.error("订阅通知失败：未连接到任何设备。")
            return False
        try:
            await self._client.start_notify(char_uuid, callback)
            logger.info(f"成功订阅特征 {char_uuid} 的通知。")
            return True
        except Exception as e:
            logger.error(f"订阅特征 {char_uuid} 通知失败: {e}", exc_info=True)
            self._error_message = str(e)
            return False

    def get_health_status(self) -> HealthStatus:
        """获取当前服务的健康状态"""
        uptime = 0.0
        if self._start_time > 0:
            uptime = asyncio.get_event_loop().time() - self._start_time
        
        connected_device_addr = self._client.address if self._client and self._client.is_connected else None
        
        return HealthStatus(
            status=self._status,
            uptime=uptime,
            connected_device=connected_device_addr,
            error_message=self._error_message
        )

    def get_status(self) -> Dict[str, Any]:
        """获取详细状态信息"""
        health = self.get_health_status()
        return {
            "service_status": health.status.value,
            "uptime_seconds": health.uptime,
            "connected_device_address": health.connected_device,
            "last_error": health.error_message,
            "discovered_devices_count": len(self.discovered_devices),
            "platform": platform.system()
        }

# --- 示例使用和主函数 --- #

async def notification_handler(sender: int, data: bytearray):
    """示例通知回调处理函数"""
    logger.info(f"收到来自 {sender} 的通知: {data.hex()}")

async def main():
    """主执行函数"""
    logger.info("--- 启动 Node_38_BLE 演示 ---")
    
    # 1. 初始化配置和服务
    config = BLENodeConfig(scan_duration_seconds=5)
    service = BLEService(config)
    
    # 启动服务主任务
    service_task = asyncio.create_task(service.start())

    try:
        # 2. 扫描设备
        print("\n--- 步骤 1: 扫描设备 ---")
        devices = await service.scan()
        if not devices:
            logger.error("未发现任何BLE设备。请确保蓝牙已开启且有设备在广播。")
            return

        print("发现的设备:")
        for i, dev in enumerate(devices):
            print(f"  {i}: {dev['name']} ({dev['address']})")

        # 3. 尝试连接到第一个发现的设备
        # 在实际应用中，会让用户选择或根据配置过滤
        target_device_info = devices[0]
        target_address = target_device_info["address"]
        print(f"\n--- 步骤 2: 连接到设备 {target_address} ---")
        
        connection_success = await service.connect(target_address)
        if not connection_success:
            logger.error(f"无法连接到设备 {target_address}。演示结束。")
            return

        print("\n--- 步骤 3: 查询服务状态 ---")
        status = service.get_status()
        print(f"当前状态: {status}")
        await asyncio.sleep(2) # 等待连接稳定

        # 4. 探索服务和特征 (示例)
        # 实际应用中需要知道具体的服务和特征UUID
        # 这里仅为演示，假设我们知道一个可读写的特征
        # 例如，一个标准的心率服务特征
        HEART_RATE_MEASUREMENT_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

        print(f"\n--- 步骤 4: 订阅通知 (示例: {HEART_RATE_MEASUREMENT_UUID}) ---")
        await service.subscribe_to_notifications(HEART_RATE_MEASUREMENT_UUID, notification_handler)

        print("\n--- 订阅后等待通知 (等待15秒) ---")
        await asyncio.sleep(15)

        # 5. 断开连接
        print("\n--- 步骤 5: 断开连接 ---")
        await service.disconnect()
        await asyncio.sleep(2)
        status_after_disconnect = service.get_status()
        print(f"断开连接后的状态: {status_after_disconnect}")

    except Exception as e:
        logger.error(f"演示过程中发生未处理的异常: {e}", exc_info=True)
    finally:
        # 6. 停止服务
        print("\n--- 步骤 6: 停止服务 ---")
        await service.stop()
        service_task.cancel()
        try:
            await service_task
        except asyncio.CancelledError:
            pass # 任务取消是预期的
        logger.info("--- Node_38_BLE 演示结束 ---")

if __name__ == "__main__":
    # 在Windows上，需要不同的事件循环策略
    if platform.system() == "Windows":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断。")
