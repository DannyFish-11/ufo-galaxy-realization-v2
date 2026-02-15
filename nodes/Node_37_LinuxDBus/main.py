# -*- coding: utf-8 -*-
"""
Node_37_LinuxDBus: Linux D-Bus 通信节点

负责与 Linux D-Bus 系统服务进行交互，提供方法调用、信号监听和属性访问等功能。
需要安装 `dbus-next` 库: sudo pip3 install dbus-next
"""

import os
import sys
import json
import asyncio
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List

# 导入 D-Bus 库
# 确保已安装: pip install dbus-next
try:
    from dbus_next.aio import MessageBus
    from dbus_next.constants import BusType
    from dbus_next.errors import DBusError
except ImportError:
    print("错误: dbus-next 库未安装。请运行 'pip install dbus-next' 进行安装。", file=sys.stderr)
    sys.exit(1)

# 配置日志记录器
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger("Node_37_LinuxDBus")

class NodeStatus(Enum):
    """节点运行状态枚举"""
    INITIALIZING = "初始化中"
    CONNECTING = "连接中"
    CONNECTED = "已连接"
    RUNNING = "运行中"
    DISCONNECTED = "已断开"
    ERROR = "错误"
    STOPPED = "已停止"

@dataclass
class DBusConfig:
    """D-Bus 连接配置"""
    bus_type: BusType = BusType.SYSTEM
    node_name: str = "io.github.ufo_galaxy.Node37"

@dataclass
class ServiceConfig:
    """服务配置类"""
    node_id: str = "Node_37_LinuxDBus"
    log_level: str = "INFO"
    dbus_config: DBusConfig = field(default_factory=DBusConfig)

class LinuxDBusService:
    """
    主服务类，用于管理 D-Bus 通信。
    """

    def __init__(self, config_path: Optional[str] = None) -> None:
        """初始化服务"""
        self.config: ServiceConfig = self._load_config(config_path)
        self._setup_logging()
        self.status: NodeStatus = NodeStatus.INITIALIZING
        self.bus: Optional[MessageBus] = None
        self.introspection_cache: Dict[str, Any] = {}
        logger.info(f"节点 {self.config.node_id} 初始化完成。")

    def _load_config(self, config_path: Optional[str]) -> ServiceConfig:
        """加载配置文件，如果路径不存在则使用默认配置"""
        if config_path and os.path.exists(config_path):
            logger.info(f"从 {config_path} 加载配置。")
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    # 此处可以添加更复杂的配置解析逻辑
                    return ServiceConfig(**config_data)
            except (json.JSONDecodeError, TypeError) as e:
                logger.error(f"配置文件解析失败: {e}，将使用默认配置。")
                return ServiceConfig()
        logger.warning("未提供配置文件或文件不存在，将使用默认配置。")
        return ServiceConfig()

    def _setup_logging(self) -> None:
        """根据配置设置日志级别"""
        level = logging.getLevelName(self.config.log_level.upper())
        logger.setLevel(level)

    async def start(self) -> None:
        """启动服务并连接到 D-Bus"""
        if self.status in [NodeStatus.CONNECTING, NodeStatus.CONNECTED, NodeStatus.RUNNING]:
            logger.warning(f"服务已在运行中，当前状态: {self.status.value}")
            return

        self.status = NodeStatus.CONNECTING
        logger.info("正在连接到 D-Bus...")
        try:
            self.bus = await MessageBus(bus_type=self.config.dbus_config.bus_type).connect()
            self.status = NodeStatus.CONNECTED
            logger.info(f"成功连接到 {self.config.dbus_config.bus_type.name} D-Bus。")
            # 可以在此处添加 D-Bus 名称请求等逻辑
            # await self.bus.request_name(self.config.dbus_config.node_name)
            self.status = NodeStatus.RUNNING
            logger.info(f"节点 {self.config.node_id} 开始运行。")
        except (DBusError, asyncio.TimeoutError) as e:
            self.status = NodeStatus.ERROR
            logger.error(f"连接 D-Bus 失败: {e}")
            self.bus = None
        except Exception as e:
            self.status = NodeStatus.ERROR
            logger.critical(f"启动过程中发生未知严重错误: {e}", exc_info=True)
            self.bus = None

    async def stop(self) -> None:
        """停止服务并断开 D-Bus 连接"""
        logger.info("正在停止服务...")
        if self.bus and self.bus.connected:
            self.bus.disconnect()
        self.status = NodeStatus.STOPPED
        logger.info(f"节点 {self.config.node_id} 已停止。")

    async def health_check(self) -> Dict[str, Any]:
        """提供健康检查接口"""
        is_connected = self.bus is not None and self.bus.connected
        return {
            "node_id": self.config.node_id,
            "status": self.status.value,
            "dbus_connected": is_connected,
            "timestamp": asyncio.get_event_loop().time()
        }

    async def get_status(self) -> Dict[str, Any]:
        """提供详细状态查询接口"""
        health = await self.health_check()
        health["config"] = self.config.__dict__
        return health

    async def introspect_service(self, service_name: str, object_path: str) -> Any:
        """内省一个 D-Bus 服务以获取其接口信息"""
        if not self.bus or not self.bus.connected:
            raise ConnectionError("D-Bus 未连接。")
        
        cache_key = f"{service_name}:{object_path}"
        if cache_key in self.introspection_cache:
            return self.introspection_cache[cache_key]

        logger.info(f"正在内省服务: {service_name}, 对象路径: {object_path}")
        try:
            introspection = await self.bus.introspect(service_name, object_path)
            self.introspection_cache[cache_key] = introspection
            return introspection
        except DBusError as e:
            logger.error(f"内省失败: {e}")
            raise

    async def call_method(
        self, 
        service_name: str, 
        object_path: str, 
        interface_name: str, 
        method_name: str, 
        signature: str = '', 
        args: List[Any] = []
    ) -> Any:
        """调用一个 D-Bus 方法"""
        if not self.bus or not self.bus.connected:
            raise ConnectionError("D-Bus 未连接。")

        logger.info(f"调用方法: {interface_name}.{method_name} on {service_name}")
        try:
            proxy_object = self.bus.get_proxy_object(service_name, object_path, await self.introspect_service(service_name, object_path))
            interface = proxy_object.get_interface(interface_name)
            
            # 动态获取方法
            method_to_call = getattr(interface, f"call_{method_name}")
            result = await method_to_call(*args)
            logger.info(f"方法调用成功，返回: {result}")
            return result
        except DBusError as e:
            logger.error(f"调用 D-Bus 方法失败: {e}")
            raise
        except Exception as e:
            logger.error(f"调用期间发生未知错误: {e}", exc_info=True)
            raise

async def main():
    """主执行函数"""
    logger.info("--- D-Bus 节点演示 --- ")
    service = LinuxDBusService()
    
    try:
        # 启动服务
        await service.start()

        if service.status != NodeStatus.RUNNING:
            logger.error("服务未能成功启动，演示中止。")
            return

        # --- 演示 1: 获取 systemd 的版本 ---
        logger.info("\n--- 演示 1: 获取 systemd 版本 ---")
        try:
            systemd_version = await service.call_method(
                'org.freedesktop.systemd1',
                '/org/freedesktop/systemd1',
                'org.freedesktop.systemd1.Manager',
                'GetProperties', # 通常属性通过属性接口获取，但这里用方法调用演示
                's',
                ['Version']
            )
            # 返回值可能需要解析，这里仅作演示
            logger.info(f"获取到 systemd 原始返回: {systemd_version}")
        except Exception as e:
            logger.error(f"获取 systemd 版本失败: {e}")

        # --- 演示 2: 列出 systemd 管理的所有单元 ---
        logger.info("\n--- 演示 2: 列出 systemd 单元 ---")
        try:
            units = await service.call_method(
                'org.freedesktop.systemd1',
                '/org/freedesktop/systemd1',
                'org.freedesktop.systemd1.Manager',
                'ListUnits'
            )
            logger.info(f"成功列出 {len(units)} 个 systemd 单元。部分单元:")
            for unit in units[:5]: # 只显示前5个
                logger.info(f"  - {unit[0]}")
        except Exception as e:
            logger.error(f"列出 systemd 单元失败: {e}")

        # --- 演示 3: 健康检查和状态查询 ---
        logger.info("\n--- 演示 3: 健康与状态检查 ---")
        health = await service.health_check()
        logger.info(f"健康检查结果: {health}")
        status = await service.get_status()
        logger.info(f"详细状态: {status}")

    except Exception as e:
        logger.critical(f"主程序发生严重错误: {e}", exc_info=True)
    finally:
        # 停止服务
        await service.stop()

if __name__ == "__main__":
    # 在某些环境中，直接运行asyncio.run()可能会因嵌套事件循环而出错
    # 例如在Jupyter或某些框架中。标准Python脚本中是安全的。
    try:
        asyncio.run(main())
    except RuntimeError as e:
        if "cannot run loop while another loop is running" in str(e):
            logger.warning("检测到已在运行的事件循环。将使用 get_event_loop().run_until_complete()。")
            loop = asyncio.get_event_loop()
            loop.run_until_complete(main())
        else:
            raise
