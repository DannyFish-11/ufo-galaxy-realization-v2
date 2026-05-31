"""
Galaxy - 外部渠道插件框架（Channel Plugins）
==============================================

定义统一 ChannelAdapter 接口，允许系统接入不同外部通信渠道（飞书、Slack、企业微信、SMS 等）。

使用方法：
    from core.channel_plugins import get_channel_loader

    loader = get_channel_loader()

    # 加载插件目录
    await loader.load_plugin("console")

    # 发送消息
    await loader.send("console", "Hello, World!")

    # 列出已加载插件
    plugins = loader.list_plugins()
"""

import asyncio
import importlib
import importlib.util
import logging
import os
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ChannelPlugins")


# ============================================================================
# ChannelAdapter 抽象基类
# ============================================================================

class ChannelAdapter(ABC):
    """
    渠道适配器抽象基类

    所有渠道插件必须继承此类并实现以下方法。
    """

    # 插件元数据（子类可覆盖）
    name: str = "base"
    description: str = ""
    version: str = "1.0.0"

    @abstractmethod
    async def send(self, message: str, **kwargs) -> Dict[str, Any]:
        """
        发送消息

        Args:
            message: 消息内容
            **kwargs: 渠道特定参数（如 target、group_id 等）

        Returns:
            {"success": bool, "message_id": str, ...}
        """

    @abstractmethod
    async def receive(self) -> Optional[Dict[str, Any]]:
        """
        接收消息（非阻塞，无消息时返回 None）

        Returns:
            {"from": str, "content": str, "timestamp": float, ...} or None
        """

    @abstractmethod
    async def health(self) -> Dict[str, Any]:
        """
        健康检查

        Returns:
            {"healthy": bool, "details": str}
        """

    def get_config_schema(self) -> Dict[str, Any]:
        """返回插件配置 schema（可选实现）"""
        return {}

    def configure(self, config: Dict[str, Any]) -> None:
        """应用配置（可选实现）"""
        pass


# ============================================================================
# 内置示例插件：Console（开箱即用，无需外部服务）
# ============================================================================

class ConsoleChannelAdapter(ChannelAdapter):
    """
    控制台渠道适配器

    将消息打印到控制台，无需任何外部服务，可直接用于测试和开发。
    """

    name = "console"
    description = "Console channel - prints messages to stdout, useful for testing"
    version = "1.0.0"

    def __init__(self):
        self._inbox: List[Dict] = []

    async def send(self, message: str, **kwargs) -> Dict[str, Any]:
        import time
        ts = datetime.now().strftime("%H:%M:%S")
        target = kwargs.get("target", "broadcast")
        print(f"[Channel:Console] [{ts}] -> {target}: {message}")
        return {"success": True, "message_id": f"console-{int(time.time()*1000)}"}

    async def receive(self) -> Optional[Dict[str, Any]]:
        if self._inbox:
            return self._inbox.pop(0)
        return None

    async def health(self) -> Dict[str, Any]:
        return {"healthy": True, "details": "Console channel is always available"}

    def inject(self, message: str, sender: str = "test") -> None:
        """向 inbox 注入消息（供测试使用）"""
        import time
        self._inbox.append({
            "from": sender,
            "content": message,
            "timestamp": time.time(),
        })


# ============================================================================
# 插件加载器
# ============================================================================

@dataclass
class PluginInfo:
    """已加载插件信息"""
    plugin_id: str
    adapter: ChannelAdapter
    loaded_at: float = field(default_factory=time.time)
    source: str = "builtin"


_BUILTIN_PLUGINS: Dict[str, type] = {
    "console": ConsoleChannelAdapter,
}


class ChannelPluginLoader:
    """
    渠道插件加载器

    支持：
    - 加载内置插件（console 等）
    - 从目录动态加载外部插件
    - 管理插件生命周期
    """

    _instance = None

    def __init__(self):
        self._plugins: Dict[str, PluginInfo] = {}

    @classmethod
    def get_instance(cls) -> "ChannelPluginLoader":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def load_plugin(
        self,
        plugin_id: str,
        path: Optional[str] = None,
        config: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        加载渠道插件

        Args:
            plugin_id: 插件 ID（如 "console"）
            path: 外部插件目录路径（含 channel.py 的目录）；为 None 时加载内置插件
            config: 插件配置

        Returns:
            {"success": bool, "plugin_id": str, "name": str, ...}
        """
        # 1. 内置插件
        if path is None:
            cls = _BUILTIN_PLUGINS.get(plugin_id)
            if cls is None:
                return {"success": False, "error": f"未知内置插件: {plugin_id}"}
            adapter = cls()
        else:
            # 2. 从文件系统加载
            adapter = await self._load_from_path(plugin_id, path)
            if adapter is None:
                return {"success": False, "error": f"从路径加载失败: {path}"}

        if config:
            try:
                adapter.configure(config)
            except Exception as e:
                logger.warning(f"Plugin configure failed: {e}")

        self._plugins[plugin_id] = PluginInfo(
            plugin_id=plugin_id,
            adapter=adapter,
            source=path or "builtin",
        )
        logger.info(f"Channel plugin loaded: {plugin_id} ({adapter.name})")
        return {
            "success": True,
            "plugin_id": plugin_id,
            "name": adapter.name,
            "description": adapter.description,
            "version": adapter.version,
        }

    async def _load_from_path(self, plugin_id: str, path: str) -> Optional[ChannelAdapter]:
        """从目录加载外部插件（目录中需有 channel.py，其中定义 Plugin 类继承 ChannelAdapter）"""
        channel_file = Path(path) / "channel.py"
        if not channel_file.exists():
            logger.error(f"channel.py not found in {path}")
            return None
        try:
            spec = importlib.util.spec_from_file_location(f"channel_{plugin_id}", channel_file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[f"channel_{plugin_id}"] = module
            spec.loader.exec_module(module)
            plugin_cls = getattr(module, "Plugin", None)
            if plugin_cls is None:
                logger.error(f"channel.py in {path} must define a 'Plugin' class")
                return None
            return plugin_cls()
        except Exception as e:
            logger.error(f"Failed to load channel plugin from {path}: {e}")
            return None

    async def unload_plugin(self, plugin_id: str) -> Dict[str, Any]:
        """卸载插件"""
        if plugin_id not in self._plugins:
            return {"success": False, "error": f"插件未加载: {plugin_id}"}
        del self._plugins[plugin_id]
        logger.info(f"Channel plugin unloaded: {plugin_id}")
        return {"success": True, "plugin_id": plugin_id}

    def list_plugins(self) -> List[Dict]:
        """列出已加载的插件"""
        result = []
        for pid, info in self._plugins.items():
            result.append({
                "plugin_id": pid,
                "name": info.adapter.name,
                "description": info.adapter.description,
                "version": info.adapter.version,
                "source": info.source,
                "loaded_at": info.loaded_at,
            })
        return result

    def get_adapter(self, plugin_id: str) -> Optional[ChannelAdapter]:
        """获取已加载插件的适配器实例"""
        info = self._plugins.get(plugin_id)
        return info.adapter if info else None

    async def send(self, plugin_id: str, message: str, **kwargs) -> Dict[str, Any]:
        """通过指定插件发送消息"""
        adapter = self.get_adapter(plugin_id)
        if adapter is None:
            return {"success": False, "error": f"插件未加载: {plugin_id}"}
        return await adapter.send(message, **kwargs)

    async def health_check_all(self) -> Dict[str, Any]:
        """检查所有插件健康状态"""
        results = {}
        for pid, info in self._plugins.items():
            try:
                results[pid] = await info.adapter.health()
            except Exception as e:
                logger.debug("Fallback triggered: %s", e)
                results[pid] = {"healthy": False, "details": str(e)}
        return results

    async def auto_load_plugins(self, plugins_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        自动扫描并加载插件目录（类似 skill_loader 的思路）

        每个子目录如果包含 channel.py，则尝试加载。
        """
        if plugins_dir is None:
            plugins_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "external", "channels"
            )

        if not os.path.isdir(plugins_dir):
            return {"loaded": 0, "results": []}

        results = []
        for entry in os.scandir(plugins_dir):
            if entry.is_dir():
                channel_file = os.path.join(entry.path, "channel.py")
                if os.path.exists(channel_file):
                    result = await self.load_plugin(entry.name, path=entry.path)
                    results.append(result)

        success_count = sum(1 for r in results if r.get("success"))
        return {"loaded": success_count, "total": len(results), "results": results}


# ============================================================================
# 单例访问
# ============================================================================

def get_channel_loader() -> ChannelPluginLoader:
    return ChannelPluginLoader.get_instance()
