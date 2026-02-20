#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UFO Galaxy - Node_31_Reserved: 通用插件框架节点

此节点实现了一个通用的插件化框架，允许在运行时动态加载和管理插件。
它被设计为可扩展的，以便在未来根据具体需求添加新的功能模块。

主要功能:
- 动态插件加载: 从指定目录自动发现并加载插件。
- 生命周期管理: 管理插件的初始化、执行和卸载生命周期。
- 异步任务执行: 基于 asyncio 实现非阻塞的插件任务执行。
- 状态监控: 提供节点自身和各插件的状态查询接口。
- 健康检查: 提供HTTP健康检查端点，便于系统集成和监控。
- 灵活配置: 通过JSON文件进行节点配置，如插件目录等。
"""

import os
import sys
import json
import asyncio
import logging
import importlib.util
from enum import Enum
from typing import Dict, Any, Optional, List, Type
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

# --- 核心枚举和数据类 --- #

class NodeStatus(Enum):
    """定义节点运行状态"""
    INITIALIZING = "正在初始化"
    RUNNING = "正在运行"
    DEGRADED = "降级运行"
    STOPPED = "已停止"
    ERROR = "错误"

class PluginStatus(Enum):
    """定义插件运行状态"""
    LOADED = "已加载"
    ACTIVE = "活动中"
    INACTIVE = "未活动"
    FAILED = "加载失败"

@dataclass
class NodeConfig:
    """节点配置信息"""
    node_name: str = "Node_31_Reserved"
    log_level: str = "INFO"
    plugin_dir: str = "/home/ubuntu/plugins"
    health_check_port: int = 8080

@dataclass
class PluginInfo:
    """存储插件的元数据和状态"""
    name: str
    path: str
    status: PluginStatus = PluginStatus.INACTIVE
    instance: Optional[Any] = None
    error_message: Optional[str] = None

# --- 插件基类 --- #

class BasePlugin(ABC):
    """所有插件必须继承的抽象基类"""

    @abstractmethod
    async def setup(self, config: NodeConfig, logger: logging.Logger) -> None:
        """初始化插件，在加载后立即调用"""
        pass

    @abstractmethod
    async def execute(self, *args, **kwargs) -> Any:
        """执行插件的核心逻辑"""
        pass

    @abstractmethod
    async def teardown(self) -> None:
        """清理资源，在节点关闭时调用"""
        pass

# --- 主服务类 --- #

class ReservedNodeService:
    """预留节点主服务，实现插件框架的核心功能"""

    def __init__(self, config_path: str = "config.json"):
        """初始化服务"""
        self.node_status = NodeStatus.INITIALIZING
        self.config_path = config_path
        self.config: NodeConfig = self._load_config()
        self._setup_logging()
        self.plugins: Dict[str, PluginInfo] = {}
        self.main_task: Optional[asyncio.Task] = None

        self.logger.info(f"节点 {self.config.node_name} 正在初始化...")

    def _load_config(self) -> NodeConfig:
        """加载配置文件，如果文件不存在则使用默认配置"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                return NodeConfig(**config_data)
            else:
                # 如果配置文件不存在，创建一个默认的
                default_config = NodeConfig()
                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(default_config.__dict__, f, indent=4)
                return default_config
        except (IOError, json.JSONDecodeError, TypeError) as e:
            logging.basicConfig(level="ERROR")
            logging.error(f"无法加载或创建配置文件: {e}", exc_info=True)
            sys.exit(1)

    def _setup_logging(self) -> None:
        """配置日志记录器"""
        self.logger = logging.getLogger(self.config.node_name)
        level = logging.getLevelName(self.config.log_level.upper())
        self.logger.setLevel(level)
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        if not self.logger.handlers:
            self.logger.addHandler(handler)

    def _discover_and_load_plugins(self) -> None:
        """从插件目录发现并动态加载插件"""
        self.logger.info(f"从目录 '{self.config.plugin_dir}' 发现插件...")
        if not os.path.isdir(self.config.plugin_dir):
            self.logger.warning(f"插件目录 '{self.config.plugin_dir}' 不存在，将创建它。")
            os.makedirs(self.config.plugin_dir, exist_ok=True)
            return

        for filename in os.listdir(self.config.plugin_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                plugin_path = os.path.join(self.config.plugin_dir, filename)
                plugin_name = os.path.splitext(filename)[0]
                self.logger.debug(f"发现潜在插件: {plugin_name} at {plugin_path}")
                self._load_plugin(plugin_name, plugin_path)

    def _load_plugin(self, name: str, path: str) -> None:
        """加载单个插件模块"""
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"无法为 {name} 创建模块规范")

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, BasePlugin) and attr is not BasePlugin:
                    plugin_class = attr
                    break
            
            if plugin_class:
                instance = plugin_class()
                self.plugins[name] = PluginInfo(
                    name=name,
                    path=path,
                    status=PluginStatus.LOADED,
                    instance=instance
                )
                self.logger.info(f"成功加载插件: {name}")
            else:
                raise TypeError(f"在 {name} 中未找到 BasePlugin 的子类")

        except Exception as e:
            self.logger.error(f"加载插件 '{name}' 失败: {e}", exc_info=True)
            self.plugins[name] = PluginInfo(
                name=name,
                path=path,
                status=PluginStatus.FAILED,
                error_message=str(e)
            )

    async def _initialize_plugins(self) -> None:
        """异步初始化所有已加载的插件"""
        self.logger.info("正在初始化所有已加载的插件...")
        for name, info in self.plugins.items():
            if info.status == PluginStatus.LOADED and info.instance:
                try:
                    await info.instance.setup(self.config, self.logger)
                    info.status = PluginStatus.ACTIVE
                    self.logger.info(f"插件 '{name}' 初始化成功并已激活。")
                except Exception as e:
                    self.logger.error(f"初始化插件 '{name}' 失败: {e}", exc_info=True)
                    info.status = PluginStatus.FAILED
                    info.error_message = str(e)

    async def _health_check_server(self) -> None:
        """提供一个简单的HTTP健康检查服务器"""
        async def handle_request(reader, writer):
            request_line = await reader.readline()
            if request_line:
                headers = {}
                while True:
                    line = await reader.readline()
                    if line == b'\r\n':
                        break
                    parts = line.decode().strip().split(':', 1)
                    if len(parts) == 2:
                        headers[parts[0].strip()] = parts[1].strip()

                response_body = self.get_status()
                response = (
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Type: application/json\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    f"Connection: close\r\n\r\n"
                    f"{response_body}"
                )
                writer.write(response.encode('utf-8'))
                await writer.drain()
            writer.close()

        server = await asyncio.start_server(
            handle_request, '0.0.0.0', self.config.health_check_port
        )
        self.logger.info(f"健康检查服务器正在监听 0.0.0.0:{self.config.health_check_port}")
        async with server:
            await server.serve_forever()

    def get_status(self) -> str:
        """查询并返回当前节点和所有插件的聚合状态"""
        status_data = {
            "node_name": self.config.node_name,
            "node_status": self.node_status.value,
            "plugins": [
                {
                    "name": info.name,
                    "status": info.status.value,
                    "error": info.error_message
                }
                for info in self.plugins.values()
            ]
        }
        return json.dumps(status_data, indent=4, ensure_ascii=False)

    async def run(self) -> None:
        """启动节点主循环和所有服务"""
        self.logger.info("节点服务开始运行...")
        self._discover_and_load_plugins()
        await self._initialize_plugins()

        self.node_status = NodeStatus.RUNNING
        if any(p.status == PluginStatus.FAILED for p in self.plugins.values()):
            self.node_status = NodeStatus.DEGRADED
            self.logger.warning("部分插件加载失败，节点以 '降级' 模式运行。")

        # 启动健康检查服务器
        self.main_task = asyncio.create_task(self._health_check_server())

        try:
            # 主循环可以用于执行周期性任务或等待事件
            while self.node_status in [NodeStatus.RUNNING, NodeStatus.DEGRADED]:
                self.logger.debug("主循环正在运行...")
                # 示例：可以调用某个插件的周期性任务
                # for plugin in self.plugins.values():
                #     if plugin.status == PluginStatus.ACTIVE:
                #         await plugin.instance.execute()
                await asyncio.sleep(60) # 每分钟检查一次
        except asyncio.CancelledError:
            self.logger.info("主任务被取消，准备关闭...")
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """优雅地关闭节点和所有插件"""
        self.logger.info("节点正在关闭...")
        self.node_status = NodeStatus.STOPPED

        if self.main_task and not self.main_task.done():
            self.main_task.cancel()

        for name, info in self.plugins.items():
            if info.status == PluginStatus.ACTIVE and info.instance:
                try:
                    await info.instance.teardown()
                    self.logger.info(f"插件 '{name}' 已成功卸载。")
                except Exception as e:
                    self.logger.error(f"卸载插件 '{name}' 时出错: {e}", exc_info=True)
        
        self.logger.info("节点已停止。")

async def main():
    """应用程序主入口"""
    service = ReservedNodeService()
    try:
        await service.run()
    except KeyboardInterrupt:
        print("\n检测到用户中断，正在关闭服务...")
    finally:
        await service.shutdown()

if __name__ == "__main__":
    # 为了演示，创建一个示例插件
    plugin_dir = "/home/ubuntu/plugins"
    os.makedirs(plugin_dir, exist_ok=True)
    sample_plugin_code = """
from typing import Any
import asyncio
import logging
from main import BasePlugin, NodeConfig

class SampleLoggerPlugin(BasePlugin):
    def __init__(self):
        self.logger: logging.Logger = logging.getLogger()
        self.counter = 0

    async def setup(self, config: NodeConfig, logger: logging.Logger) -> None:
        self.logger = logger
        self.logger.info(f"SampleLoggerPlugin (v1.0) 已初始化。节点名称: {config.node_name}")

    async def execute(self, *args, **kwargs) -> Any:
        self.counter += 1
        self.logger.info(f"SampleLoggerPlugin 正在执行... 调用次数: {self.counter}")
        await asyncio.sleep(1)
        return {"status": "ok", "count": self.counter}

    async def teardown(self) -> None:
        self.logger.info(f"SampleLoggerPlugin 正在卸载。总共执行了 {self.counter} 次。")
"""
    with open(os.path.join(plugin_dir, "sample_plugin.py"), "w", encoding="utf-8") as f:
        f.write(sample_plugin_code)

    # 运行主服务
    asyncio.run(main())
