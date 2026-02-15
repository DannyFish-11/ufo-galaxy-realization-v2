'''
# -*- coding: utf-8 -*-

"""
Node_32_Reserved: 预留节点 - 通用插件框架

该节点实现了一个通用的插件式框架，允许动态加载和执行插件。
主要功能包括：
- 插件发现与加载：动态从指定目录加载插件。
- 插件生命周期管理：控制插件的初始化、执行和卸载。
- 核心服务：提供一个主服务类来协调插件的运行。
- 异步支持：整个框架基于 asyncio，支持高并发场景。
- 配置管理：通过 dataclass 管理配置，支持从环境变量或配置文件加载。
- 健康检查与状态查询：提供 HTTP 接口用于监控节点状态。
"""

import os
import asyncio
import logging
import importlib
import inspect
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Type, Coroutine

# --- 配置与常量 ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Node_32_Reserved")

class NodeStatus(Enum):
    """节点运行状态"""
    INITIALIZING = "INITIALIZING"  # 正在初始化
    RUNNING = "RUNNING"            # 正在运行
    STOPPED = "STOPPED"            # 已停止
    ERROR = "ERROR"                # 出现错误

@dataclass
class PluginConfig:
    """插件配置"""
    name: str
    enabled: bool = True
    config: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ServiceConfig:
    """服务配置"""
    node_name: str = "Node_32_Reserved"
    plugin_dir: str = "/home/ubuntu/plugins"
    health_check_port: int = 8080
    plugins: Dict[str, PluginConfig] = field(default_factory=dict)

# --- 插件基类 ---

class BasePlugin:
    """
    插件基类，所有插件都应继承自该类。
    """
    def __init__(self, config: PluginConfig):
        self.config = config
        self.logger = logging.getLogger(f"Plugin.{self.config.name}")
        self.logger.info(f"插件 {self.config.name} 初始化完成。")

    async def setup(self) -> None:
        """异步初始化插件资源"""
        self.logger.info(f"插件 {self.config.name} 正在进行异步设置...")
        await asyncio.sleep(0.1) # 模拟异步操作
        self.logger.info(f"插件 {self.config.name} 异步设置完成。")

    async def execute(self, **kwargs) -> Any:
        """
        执行插件的核心逻辑。
        :param kwargs: 插件执行所需的参数
        :return: 插件执行结果
        """
        raise NotImplementedError("插件必须实现 execute 方法")

    async def teardown(self) -> None:
        """异步清理插件资源"""
        self.logger.info(f"插件 {self.config.name} 正在进行异步清理...")
        await asyncio.sleep(0.1) # 模拟异步操作
        self.logger.info(f"插件 {self.config.name} 异步清理完成。")

# --- 插件管理器 ---

class PluginManager:
    """
    负责插件的发现、加载和管理。
    """
    def __init__(self, config: ServiceConfig):
        self.config = config
        self.plugins: Dict[str, BasePlugin] = {}
        self.logger = logging.getLogger("PluginManager")

    async def discover_and_load(self) -> None:
        """
        从插件目录中发现并加载所有可用插件。
        """
        self.logger.info(f"开始从目录 {self.config.plugin_dir} 发现插件...")
        if not os.path.isdir(self.config.plugin_dir):
            self.logger.warning(f"插件目录 {self.config.plugin_dir} 不存在，将创建该目录。")
            os.makedirs(self.config.plugin_dir, exist_ok=True)
            return

        for filename in os.listdir(self.config.plugin_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                module_name = f"plugins.{filename[:-3]}"
                try:
                    await self._load_plugin_from_module(module_name)
                except Exception as e:
                    self.logger.error(f"加载插件 {module_name} 失败: {e}", exc_info=True)

    async def _load_plugin_from_module(self, module_name: str) -> None:
        """从指定的模块中加载插件"""
        spec = importlib.util.spec_from_file_location(module_name, os.path.join(self.config.plugin_dir, module_name.split('.')[1] + '.py'))
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj) and issubclass(obj, BasePlugin) and obj is not BasePlugin:
                    plugin_name = obj.__name__
                    if plugin_name in self.config.plugins and self.config.plugins[plugin_name].enabled:
                        plugin_config = self.config.plugins[plugin_name]
                        self.plugins[plugin_name] = obj(plugin_config)
                        self.logger.info(f"成功加载插件: {plugin_name}")
                        await self.plugins[plugin_name].setup()
                    else:
                        self.logger.info(f"发现插件 {plugin_name}，但未在配置中启用。")

    async def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """获取已加载的插件实例"""
        return self.plugins.get(name)

    async def unload_all(self) -> None:
        """卸载所有插件并清理资源"""
        self.logger.info("开始卸载所有插件...")
        for name, plugin in self.plugins.items():
            try:
                await plugin.teardown()
                self.logger.info(f"插件 {name} 已成功卸载。")
            except Exception as e:
                self.logger.error(f"卸载插件 {name} 失败: {e}", exc_info=True)
        self.plugins.clear()
        self.logger.info("所有插件已卸载。")

# --- 主服务类 ---

class ReservedNodeService:
    """
    预留节点主服务，负责整个节点的生命周期管理。
    """
    def __init__(self, config: ServiceConfig):
        self.config = config
        self.status = NodeStatus.INITIALIZING
        self.plugin_manager = PluginManager(config)
        self.logger = logging.getLogger(self.config.node_name)
        self.server_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """启动服务"""
        self.logger.info(f"节点 {self.config.node_name} 正在启动...")
        try:
            await self.plugin_manager.discover_and_load()
            self.server_task = asyncio.create_task(self._start_health_check_server())
            self.status = NodeStatus.RUNNING
            self.logger.info(f"节点 {self.config.node_name} 已成功启动，运行在端口 {self.config.health_check_port}。")
        except Exception as e:
            self.logger.error(f"节点启动失败: {e}", exc_info=True)
            self.status = NodeStatus.ERROR

    async def stop(self) -> None:
        """停止服务"""
        self.logger.info(f"节点 {self.config.node_name} 正在停止...")
        self.status = NodeStatus.STOPPED
        if self.server_task:
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                self.logger.info("健康检查服务已停止。")
        await self.plugin_manager.unload_all()
        self.logger.info(f"节点 {self.config.node_name} 已停止。")

    async def execute_plugin(self, plugin_name: str, **kwargs) -> Any:
        """执行指定插件"""
        plugin = await self.plugin_manager.get_plugin(plugin_name)
        if not plugin:
            raise ValueError(f"插件 {plugin_name} 不存在或未启用。")
        
        self.logger.info(f"开始执行插件 {plugin_name}...")
        try:
            result = await plugin.execute(**kwargs)
            self.logger.info(f"插件 {plugin_name} 执行完成。")
            return result
        except Exception as e:
            self.logger.error(f"插件 {plugin_name} 执行出错: {e}", exc_info=True)
            raise

    async def _handle_health_check(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """处理健康检查请求"""
        response = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{{\"status\": \"{self.status.value}\", \"node\": \"{self.config.node_name}\"}}"
        writer.write(response.encode('utf-8'))
        await writer.drain()
        writer.close()

    async def _handle_status_query(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """处理状态查询请求"""
        plugins_status = {name: "enabled" for name in self.plugin_manager.plugins.keys()}
        response_data = {
            "node_name": self.config.node_name,
            "status": self.status.value,
            "loaded_plugins": list(plugins_status.keys()),
            "plugin_count": len(plugins_status)
        }
        response_body = str(response_data).replace("'", '"')
        response = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{response_body}"
        writer.write(response.encode('utf-8'))
        await writer.drain()
        writer.close()

    async def _router(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """简单的请求路由器"""
        request_line = await reader.readline()
        if not request_line:
            writer.close()
            return

        method, path, _ = request_line.decode('utf-8').strip().split()

        if path == "/health":
            await self._handle_health_check(reader, writer)
        elif path == "/status":
            await self._handle_status_query(reader, writer)
        else:
            response = "HTTP/1.1 404 Not Found\r\n\r\nNot Found"
            writer.write(response.encode('utf-8'))
            await writer.drain()
            writer.close()

    async def _start_health_check_server(self) -> None:
        """启动健康检查和状态查询的 HTTP 服务器"""
        server = await asyncio.start_server(
            self._router,
            '0.0.0.0',
            self.config.health_check_port
        )
        async with server:
            await server.serve_forever()

# --- 示例插件 ---

def create_dummy_plugin():
    """创建一个用于演示的虚拟插件文件"""
    plugin_dir = "/home/ubuntu/plugins"
    if not os.path.exists(plugin_dir):
        os.makedirs(plugin_dir)

    plugin_code = '''
from Node_32_Reserved.main import BasePlugin, PluginConfig
import asyncio

class EchoPlugin(BasePlugin):
    def __init__(self, config: PluginConfig):
        super().__init__(config)

    async def execute(self, **kwargs) -> str:
        message = kwargs.get("message", "Hello, World!")
        self.logger.info(f"EchoPlugin 正在回显消息: {message}")
        await asyncio.sleep(0.5) # 模拟IO操作
        return f"Echo: {message}"
'''
    with open(os.path.join(plugin_dir, "echo_plugin.py"), "w", encoding="utf-8") as f:
        f.write(plugin_code)
    logger.info("已创建示例插件: echo_plugin.py")

# --- 主程序入口 ---

async def main():
    """主程序入口"""
    # 1. 创建示例插件和配置
    create_dummy_plugin()
    
    service_config = ServiceConfig(
        plugins={
            "EchoPlugin": PluginConfig(name="EchoPlugin", enabled=True)
        }
    )

    # 2. 初始化并启动服务
    service = ReservedNodeService(service_config)
    await service.start()

    # 3. 模拟执行插件
    try:
        # 等待服务完全启动
        await asyncio.sleep(1)
        
        # 执行插件
        result = await service.execute_plugin("EchoPlugin", message="这是一个测试消息")
        logger.info(f"插件执行结果: {result}")

        # 保持服务运行
        logger.info("服务正在运行，按 Ctrl+C 停止。")
        while True:
            await asyncio.sleep(3600)

    except asyncio.CancelledError:
        logger.info("主程序被取消。")
    except Exception as e:
        logger.error(f"主程序出现错误: {e}", exc_info=True)
    finally:
        # 4. 停止服务
        await service.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序被用户中断。")

'''
