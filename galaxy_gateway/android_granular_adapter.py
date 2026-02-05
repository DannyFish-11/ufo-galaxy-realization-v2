"""
UFO Galaxy Fusion - Android Granular Adapter
功能: 将 AIP v2.0 消息转化为 Node 33 (ADB) 可执行的颗粒级指令。
"""
import logging
from typing import Dict, Any, Optional
from .aip_protocol_v2 import AIPMessage, MessageType

logger = logging.getLogger("AndroidGranularAdapter")

class AndroidGranularAdapter:
    def __init__(self, adb_executor: Any):
        self.adb = adb_executor
        logger.info("Android Granular Adapter Initialized.")

    async def dispatch_aip_message(self, device_id: str, message: AIPMessage) -> Optional[AIPMessage]:
        """将 AIP 消息分发为具体的 Android 操作"""
        if message.message_type == MessageType.CONTROL_COMMAND:
            command = message.payload.get("command")
            params = message.payload.get("params", {})
            if command == "click":
                x, y = params.get("x"), params.get("y")
                await self.adb.shell(f"input tap {x} {y}", device_id)
                return AIPMessage.create_result_message(message, {"status": "success", "action": "click"})
            elif command == "type":
                text = params.get("text")
                await self.adb.shell(f"input text '{text}'", device_id)
                return AIPMessage.create_result_message(message, {"status": "success", "action": "type"})
        return None
