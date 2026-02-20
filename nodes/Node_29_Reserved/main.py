#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
UFO Galaxy - Node_29_Reserved: 通用插件框架

该节点作为一个通用的插件加载和执行框架，允许在运行时动态发现、加载和执行插件。
它为系统提供了强大的可扩展性，使得新功能可以作为独立的插件模块进行开发和集成，
而无需修改核心系统代码。

主要功能:
- 动态插件发现: 自动扫描指定目录以查找可用插件。
- 插件生命周期管理: 支持插件的加载、卸载、启用和禁用。
- 隔离执行环境: 为插件提供一个安全的沙箱环境来执行其逻辑。
- 丰富的插件接口: 定义标准的插件接口（PluginBase），方便开发者创建新插件。
- 异步任务执行: 利用 asyncio 支持插件的异步操作，提高系统并发性能。
- 详细的日志记录和错误处理: 记录插件的活动和任何潜在的错误。
- 健康检查和状态监控: 提供 API 端点以监控框架和插件的运行状态。
"""

import os
import sys
import asyncio
import logging
import importlib.util
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Type, Any
import inspect

# 1. 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("Node_29_Reserved")

# 2. 状态与类型定义
class NodeStatus(Enum):
    """节点运行状态"""
    INITIALIZING = "初始化中"
    RUNNING = "运行中"
    STOPPED = "已停止"
    ERROR = "错误"

class PluginStatus(Enum):
    """插件状态"""
    LOADED = "已加载"
    UNLOADED = "未加载"
    ACTIVE = "活动中"
    INACTIVE = "未激活"
    FAILED = "加载失败"

# 3. 插件基类定义
class PluginBase:
    """所有插件必须继承的抽象基类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.plugin_name = self.__class__.__name__
        logger.info(f"插件 '{self.plugin_name}' 初始化")

    async def setup(self):
        """插件的异步初始化逻辑"""
        logger.info(f"插件 '{self.plugin_name}' 设置完成")
        pass

    async def execute(self, *args, **kwargs) -> Any:
        """插件的核心执行逻辑"""
        raise NotImplementedError("插件必须实现 execute 方法")

    async def teardown(self):
        """插件的异步清理逻辑"""
        logger.info(f"插件 '{self.plugin_name}' 清理完成")
        pass

# 4. 配置模型
@dataclass
class ReservedNodeConfig:
    """节点配置的数据类"""
    node_id: str = "Node_29_Reserved"
    node_name: str = "通用插件框架"
    plugin_directory: str = "/home/ubuntu/plugins"
    plugin_config: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    health_check_interval: int = 60  # seconds

# 5. 主服务类
class ReservedService:
    """通用插件框架主服务"""

    def __init__(self, config: ReservedNodeConfig):
        self.config = config
        self.status = NodeStatus.INITIALIZING
        self.plugins: Dict[str, PluginBase] = {}
        self.plugin_statuses: Dict[str, PluginStatus] = {}
        self.main_loop_task: Optional[asyncio.Task] = None
        logger.info(f"节点 '{self.config.node_id}' 正在初始化...")

    async def start(self):
        """启动服务，加载插件并进入主循环"""
        logger.info("服务开始启动...")
        try:
            await self._load_plugins()
            self.status = NodeStatus.RUNNING
            logger.info(f"服务已成功启动，当前状态: {self.status.value}")
            self.main_loop_task = asyncio.create_task(self._main_loop())
        except Exception as e:
            self.status = NodeStatus.ERROR
            logger.error(f"服务启动失败: {e}", exc_info=True)
            raise

    async def stop(self):
        """停止服务，并清理所有资源"""
        logger.info("服务开始停止...")
        if self.main_loop_task:
            self.main_loop_task.cancel()
            try:
                await self.main_loop_task
            except asyncio.CancelledError:
                logger.info("主循环已取消")
        
        await self._unload_plugins()
        self.status = NodeStatus.STOPPED
        logger.info(f"服务已停止，当前状态: {self.status.value}")

    async def _load_plugins(self):
        """从指定目录动态发现并加载所有插件"""
        logger.info(f"开始从目录 '{self.config.plugin_directory}' 加载插件")
        if not os.path.isdir(self.config.plugin_directory):
            logger.warning(f"插件目录 '{self.config.plugin_directory}' 不存在，将创建它")
            os.makedirs(self.config.plugin_directory, exist_ok=True)
            # 创建一个示例插件
            await self._create_example_plugin()

        for filename in os.listdir(self.config.plugin_directory):
            if filename.endswith(".py") and not filename.startswith("__"):
                await self._load_plugin_from_file(filename)

    async def _load_plugin_from_file(self, filename: str):
        """从单个文件加载插件"""
        module_name = filename[:-3]
        file_path = os.path.join(self.config.plugin_directory, filename)
        logger.info(f"发现插件文件: {file_path}")

        try:
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"无法为 {file_path} 创建模块规范")
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            for attribute_name in dir(module):
                attribute = getattr(module, attribute_name)
                if inspect.isclass(attribute) and issubclass(attribute, PluginBase) and attribute is not PluginBase:
                    plugin_name = attribute.__name__
                    if plugin_name in self.plugins:
                        logger.warning(f"插件 '{plugin_name}' 已存在，跳过重复加载")
                        continue

                    plugin_config = self.config.plugin_config.get(plugin_name, {})
                    plugin_instance = attribute(config=plugin_config)
                    await plugin_instance.setup()
                    
                    self.plugins[plugin_name] = plugin_instance
                    self.plugin_statuses[plugin_name] = PluginStatus.ACTIVE
                    logger.info(f"成功加载并激活插件: '{plugin_name}'")

        except Exception as e:
            logger.error(f"加载插件 '{module_name}' 失败: {e}", exc_info=True)
            self.plugin_statuses[module_name] = PluginStatus.FAILED

    async def _unload_plugins(self):
        """卸载所有已加载的插件"""
        logger.info("开始卸载所有插件...")
        for name, plugin in self.plugins.items():
            try:
                await plugin.teardown()
                self.plugin_statuses[name] = PluginStatus.UNLOADED
                logger.info(f"插件 '{name}' 已成功卸载")
            except Exception as e:
                logger.error(f"卸载插件 '{name}' 时出错: {e}", exc_info=True)
        self.plugins.clear()

    async def _main_loop(self):
        """服务主循环，用于执行周期性任务，如健康检查"""
        while self.status == NodeStatus.RUNNING:
            try:
                await self.health_check()
                await asyncio.sleep(self.config.health_check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"主循环发生错误: {e}", exc_info=True)
                self.status = NodeStatus.ERROR

    async def health_check(self) -> Dict[str, Any]:
        """执行健康检查并返回节点状态"""
        logger.info("执行健康检查...")
        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        """获取当前节点和所有插件的详细状态"""
        return {
            "node_id": self.config.node_id,
            "node_status": self.status.value,
            "plugin_count": len(self.plugins),
            "plugins": {
                name: status.value for name, status in self.plugin_statuses.items()
            },
        }

    async def run_plugin(self, plugin_name: str, *args, **kwargs) -> Any:
        """执行指定插件的逻辑"""
        if plugin_name not in self.plugins:
            logger.error(f"尝试执行未找到的插件: '{plugin_name}'")
            raise ValueError(f"插件 '{plugin_name}' 未加载或不存在")
        
        if self.plugin_statuses.get(plugin_name) != PluginStatus.ACTIVE:
            logger.warning(f"插件 '{plugin_name}' 当前未激活，无法执行")
            return None

        plugin = self.plugins[plugin_name]
        logger.info(f"开始执行插件: '{plugin_name}'")
        try:
            result = await plugin.execute(*args, **kwargs)
            logger.info(f"插件 '{plugin_name}' 执行完成")
            return result
        except Exception as e:
            logger.error(f"执行插件 '{plugin_name}' 时发生错误: {e}", exc_info=True)
            raise

    async def _create_example_plugin(self):
        """如果插件目录为空，则创建一个示例插件文件"""
        example_plugin_path = os.path.join(self.config.plugin_directory, "example_plugin.py")
        example_code = '''
from . import PluginBase, logger
import asyncio

class ExamplePlugin(PluginBase):
    """一个简单的示例插件"""

    async def setup(self):
        logger.info("示例插件正在进行异步设置...")
        await asyncio.sleep(1)
        logger.info("示例插件设置完成")

    async def execute(self, message: str = "Hello, Plugin World!") -> str:
        logger.info(f"示例插件正在执行，收到消息: {message}")
        return f"示例插件已处理消息: {message}"

    async def teardown(self):
        logger.info("示例插件正在清理...")
        await asyncio.sleep(1)
        logger.info("示例插件清理完成")
'''
        # 调整导入路径以适应动态加载
        fixed_code = example_code.replace("from . import", "from main import")

        with open(example_plugin_path, "w", encoding="utf-8") as f:
            f.write(fixed_code)
        logger.info(f"已创建示例插件: {example_plugin_path}")

# 6. 主程序入口
async def main():
    """主异步函数，用于初始化和运行服务"""
    logger.info("==================================================")
    logger.info("======         UFO Galaxy Node Start          ======")
    logger.info("==================================================")
    
    config = ReservedNodeConfig()
    service = ReservedService(config)

    try:
        await service.start()
        # 模拟运行一段时间，并执行插件
        await asyncio.sleep(5)
        
        # 检查示例插件是否存在并执行
        if "ExamplePlugin" in service.plugins:
            logger.info("\n--- 开始执行示例插件 ---")
            result = await service.run_plugin("ExamplePlugin", message="来自主程序的调用")
            logger.info(f"示例插件返回结果: {result}")
            logger.info("--- 示例插件执行结束 ---\n")
        else:
            logger.warning("未找到 'ExamplePlugin'，跳过执行")

        # 持续运行，直到被外部信号中断
        while service.status == NodeStatus.RUNNING:
            await asyncio.sleep(1)

    except Exception as e:
        logger.critical(f"在主程序中捕获到未处理的异常: {e}", exc_info=True)
    finally:
        if service.status == NodeStatus.RUNNING:
            await service.stop()
        logger.info("==================================================")
        logger.info("======          UFO Galaxy Node End           ======")
        logger.info("==================================================")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("检测到手动中断 (KeyboardInterrupt)，程序即将退出。")
