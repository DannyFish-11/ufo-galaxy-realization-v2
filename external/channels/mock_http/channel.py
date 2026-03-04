"""
外部渠道插件示例：Mock HTTP 渠道
================================

这是一个外部渠道插件示例，演示如何在 external/channels/ 目录下
创建独立的渠道插件。本插件模拟一个 HTTP 回调渠道。

使用方法：
    from core.channel_plugins import get_channel_loader
    loader = get_channel_loader()
    await loader.load_plugin("mock_http", path="external/channels/mock_http")
    await loader.send("mock_http", "Hello!")
"""

import time
from typing import Any, Dict, Optional

# 必须从 core.channel_plugins 导入基类
from core.channel_plugins import ChannelAdapter


class Plugin(ChannelAdapter):
    """
    Mock HTTP 渠道插件

    将消息记录到内存列表中（模拟 HTTP 推送），供测试使用。
    """

    name = "mock_http"
    description = "Mock HTTP channel - stores messages in memory for testing"
    version = "1.0.0"

    def __init__(self):
        self._sent_messages = []
        self._inbox = []
        self._webhook_url = ""

    def configure(self, config: Dict[str, Any]) -> None:
        self._webhook_url = config.get("webhook_url", "http://localhost:9999/webhook")

    def get_config_schema(self) -> Dict[str, Any]:
        return {
            "webhook_url": {
                "type": "string",
                "description": "HTTP 回调地址",
                "default": "http://localhost:9999/webhook",
            }
        }

    async def send(self, message: str, **kwargs) -> Dict[str, Any]:
        record = {
            "message": message,
            "target": kwargs.get("target", "default"),
            "timestamp": time.time(),
            "webhook_url": self._webhook_url,
        }
        self._sent_messages.append(record)
        msg_id = f"mock-{int(time.time() * 1000)}"
        return {"success": True, "message_id": msg_id, "webhook_url": self._webhook_url}

    async def receive(self) -> Optional[Dict[str, Any]]:
        if self._inbox:
            return self._inbox.pop(0)
        return None

    async def health(self) -> Dict[str, Any]:
        return {
            "healthy": True,
            "details": f"Mock HTTP channel, sent={len(self._sent_messages)}",
        }

    def get_sent_messages(self):
        """测试辅助：返回所有已发送的消息"""
        return list(self._sent_messages)
