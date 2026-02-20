

# -*- coding: utf-8 -*-

"""
UFO Galaxy - Node_28_Reserved

这是一个预留节点，实现了一个通用的插件化框架。
它能够动态地发现、加载、执行和管理插件，为系统提供灵活的扩展能力。
"""

import asyncio
import logging
import os
import importlib.util
import inspect
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, Optional, List, Type, Coroutine

# ==============================================================================
# 1. 枚举定义 (Enums)
# ==============================================================================

class NodeStatus(Enum):
    """节点运行状态"""
    INITIALIZING = "初始化中"
    RUNNING = "运行中"
    STOPPED = "已停止"
    ERROR = "错误"
    DEGRADED = "降级运行"

class PluginStatus(Enum):
    """插件状态"""
    LOADED = "已加载"
    ACTIVE = "活动中"
    INACTIVE = "未活动"
    FAILED = "失败"

class LogLevel(Enum):
    """日志级别"""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL

# ==============================================================================
# 2. 数据类定义 (Dataclasses)
# ==============================================================================

@dataclass
class NodeConfig:
    """节点配置"""
    node_name: str = "Node_28_Reserved"
    log_level: LogLevel = LogLevel.INFO
    plugin_dir: str = "/home/ubuntu/plugins"
    health_check_port: int = 8080

@dataclass
class PluginInfo:
    """插件元数据信息"""
    name: str
    version: str
    author: str
    description: str
    status: PluginStatus = PluginStatus.LOADED
    instance: Optional[Any] = None

# ==============================================================================
# 3. 插件基类 (Plugin Base Class)
# ==============================================================================

class BasePlugin:
    """所有插件必须继承的基类，定义了插件的标准接口"""

    def __init__(self, config: NodeConfig):
        self.config = config
        self.logger = logging.getLogger(self.__class__.__name__)

    async def setup(self) -> None:
        """插件初始化设置，在服务启动时调用"""
        self.logger.info(f"插件 {self.__class__.__name__} 初始化完成。")

    async def execute(self, *args, **kwargs) -> Any:
        """执行插件的核心功能，必须由子类实现"""
        raise NotImplementedError("插件的 execute 方法必须被实现")

    async def teardown(self) -> None:
        """插件清理工作，在服务停止时调用"""
        self.logger.info(f"插件 {self.__class__.__name__} 清理完成。")


# ==============================================================================
# 4. 主服务类 (Main Service Class)
# ==============================================================================

class ReservedNodeService:
    """预留节点服务，实现一个通用的插件框架"""

    def __init__(self, config: NodeConfig):
        """服务初始化"""
        self.config = config
        self.status = NodeStatus.INITIALIZING
        self.plugins: Dict[str, PluginInfo] = {}
        self._setup_logging()
        self.logger.info(f"节点 {self.config.node_name} 正在初始化...")

    def _setup_logging(self) -> None:
        """配置日志记录器"""
        logging.basicConfig(
            level=self.config.log_level.value,
            format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        self.logger = logging.getLogger(self.__class__.__name__)

    async def discover_and_load_plugins(self) -> None:
        """扫描插件目录，动态加载并注册所有合法的插件"""
        self.logger.info(f"开始从目录 ✨ {self.config.plugin_dir} ✨ 发现插件...")
        if not os.path.isdir(self.config.plugin_dir):
            self.logger.warning(f"插件目录 {self.config.plugin_dir} 不存在，将自动创建。")
            os.makedirs(self.config.plugin_dir, exist_ok=True)
            # 创建一个示例插件，以便框架可以演示功能
            self._create_example_plugin()
        
        for filename in os.listdir(self.config.plugin_dir):
            if filename.endswith(".py") and not filename.startswith("__"):
                module_name = filename[:-3]
                module_path = os.path.join(self.config.plugin_dir, filename)
                self.logger.debug(f"发现潜在插件文件: {module_path}")
                try:
                    spec = importlib.util.spec_from_file_location(module_name, module_path)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        for name, obj in inspect.getmembers(module, inspect.isclass):
                            if issubclass(obj, BasePlugin) and obj is not BasePlugin:
                                self.logger.info(f"成功加载插件: {name}")
                                instance = obj(self.config)
                                plugin_info = PluginInfo(
                                    name=getattr(instance, "name", name),
                                    version=getattr(instance, "version", "0.1.0"),
                                    author=getattr(instance, "author", "未知作者"),
                                    description=getattr(instance, "description", "无描述"),
                                    instance=instance
                                )
                                self.plugins[plugin_info.name] = plugin_info
                except Exception as e:
                    self.logger.error(f"加载插件 {module_name} 失败: {e}", exc_info=True)

    def _create_example_plugin(self):
        """如果插件目录为空，则创建一个示例插件"""
        example_plugin_path = os.path.join(self.config.plugin_dir, "example_plugin.py")
        example_code = """\
from main import BasePlugin, NodeConfig
import asyncio

class ExamplePlugin(BasePlugin):
    # 插件元数据
    name = "Example_Plugin"
    version = "1.0.0"
    author = "Manus AI"
    description = "一个用于演示的简单插件"

    def __init__(self, config: NodeConfig):
        super().__init__(config)

    async def setup(self) -> None:
        self.logger.info(f"示例插件 {self.name} 已设置。")

    async def execute(self, message: str = "World") -> dict:
        self.logger.info(f"正在执行示例插件，接收到消息: {message}")
        await asyncio.sleep(1) # 模拟IO操作
        response = f"Hello, {message}! 来自 {self.name}."
        self.logger.info("示例插件执行完毕。")
        return {"status": "success", "response": response}

    async def teardown(self) -> None:
        self.logger.info(f"示例插件 {self.name} 已卸载。")
"""
        with open(example_plugin_path, "w", encoding="utf-8") as f:
            f.write(example_code)
        self.logger.info(f"已创建示例插件: {example_plugin_path}")

    async def start(self) -> None:
        """启动节点服务和所有插件"""
        self.logger.info("节点服务正在启动...")
        await self.discover_and_load_plugins()
        for name, plugin_info in self.plugins.items():
            try:
                if plugin_info.instance:
                    await plugin_info.instance.setup()
                    plugin_info.status = PluginStatus.ACTIVE
                    self.logger.info(f"插件 {name} 已成功启动并激活。")
            except Exception as e:
                plugin_info.status = PluginStatus.FAILED
                self.logger.error(f"启动插件 {name} 失败: {e}", exc_info=True)
        self.status = NodeStatus.RUNNING
        self.logger.info(f"节点 {self.config.node_name} 已成功启动，运行在端口 {self.config.health_check_port}。")

    async def stop(self) -> None:
        """停止所有插件和节点服务"""
        self.logger.info("节点服务正在停止...")
        self.status = NodeStatus.STOPPED
        for name, plugin_info in self.plugins.items():
            try:
                if plugin_info.instance and plugin_info.status == PluginStatus.ACTIVE:
                    await plugin_info.instance.teardown()
                    plugin_info.status = PluginStatus.INACTIVE
            except Exception as e:
                self.logger.error(f"停止插件 {name} 失败: {e}", exc_info=True)
        self.logger.info("所有插件已停止。节点服务已关闭。")

    async def run_plugin(self, plugin_name: str, *args, **kwargs) -> Any:
        """执行指定插件的功能"""
        plugin_info = self.plugins.get(plugin_name)
        if not plugin_info or not plugin_info.instance:
            self.logger.error(f"插件 {plugin_name} 未找到或未加载。")
            return {"status": "error", "message": f"Plugin {plugin_name} not found."}
        
        if plugin_info.status != PluginStatus.ACTIVE:
            self.logger.warning(f"插件 {plugin_name} 当前不是活动状态 ({plugin_info.status.value})，无法执行。")
            return {"status": "error", "message": f"Plugin {plugin_name} is not active."}

        try:
            self.logger.info(f"开始执行插件 {plugin_name}...")
            result = await plugin_info.instance.execute(*args, **kwargs)
            self.logger.info(f"插件 {plugin_name} 执行完成。")
            return result
        except Exception as e:
            self.logger.error(f"执行插件 {plugin_name} 时发生错误: {e}", exc_info=True)
            self.status = NodeStatus.DEGRADED
            return {"status": "error", "message": str(e)}

    def get_status(self) -> Dict[str, Any]:
        """获取节点和所有插件的当前状态"""
        plugin_statuses = {
            name: {
                "status": info.status.value,
                "version": info.version,
                "author": info.author,
                "description": info.description
            } for name, info in self.plugins.items()
        }
        return {
            "node_name": self.config.node_name,
            "node_status": self.status.value,
            "plugin_count": len(self.plugins),
            "plugins": plugin_statuses
        }

    async def health_check_server(self):
        """提供一个简单的HTTP健康检查接口"""
        async def handle_request(reader, writer):
            message = await reader.read(100)
            addr = writer.get_extra_info('peername')
            self.logger.debug(f"来自 {addr!r} 的健康检查请求")

            response_body = str(self.get_status())
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(response_body)}\r\n"
                "Connection: close\r\n\r\n"
                f"{response_body}"
            )
            writer.write(response.encode('utf-8'))
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(
            handle_request, '0.0.0.0', self.config.health_check_port
        )
        self.logger.info(f"健康检查服务已在 0.0.0.0:{self.config.health_check_port} 上启动。")
        async with server:
            await server.serve_forever()

# ==============================================================================
# 5. 主程序入口 (Main Execution Block)
# ==============================================================================

async def main():
    """主异步函数，用于启动和管理服务"""
    config = NodeConfig()
    service = ReservedNodeService(config)

    try:
        # 启动服务和健康检查
        await service.start()
        # 启动健康检查服务器作为后台任务
        health_check_task = asyncio.create_task(service.health_check_server())

        # 模拟运行一段时间并执行插件
        await asyncio.sleep(5) # 等待服务完全启动
        
        # 检查示例插件是否存在
        if "Example_Plugin" in service.plugins:
            print("\n" + "="*50)
            print("🚀 开始执行示例插件...")
            result = await service.run_plugin("Example_Plugin", message="UFO Galaxy")
            print(f"插件执行结果: {result}")
            print("="*50 + "\n")
        else:
            print("\n" + "="*50)
            print("🤔 未找到示例插件，请检查插件目录。")
            print("="*50 + "\n")

        # 打印当前状态
        print("\n" + "="*50)
        print("📊 获取当前节点状态...")
        status = service.get_status()
        import json
        print(json.dumps(status, indent=2, ensure_ascii=False))
        print("="*50 + "\n")

        # 保持服务运行，直到被中断
        print("节点正在运行... 按下 Ctrl+C 停止。")
        await health_check_task

    except asyncio.CancelledError:
        print("捕获到取消错误，服务即将关闭。")
    except KeyboardInterrupt:
        print("检测到用户中断，正在优雅地关闭服务...")
    finally:
        await service.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("主程序被强制中断。")


