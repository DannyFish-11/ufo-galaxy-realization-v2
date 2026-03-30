"""
galaxy_gateway/android/handlers/vision.py

Handles vision_request messages from Android devices.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Dict, Optional

from galaxy_gateway.android.message_builder import MessageBuilder

if TYPE_CHECKING:
    from galaxy_gateway.android_bridge import AndroidBridge

logger = logging.getLogger(__name__)


async def handle_vision_request(
    bridge: "AndroidBridge", websocket: Any, message: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """处理视觉请求：Android 上传截图 → VisionPipeline 分析 → task_assign 回推"""
    device_id = message.get("device_id")
    task_id = message.get("task_id") or message.get("message_id") or str(uuid.uuid4())
    image_base64 = message.get("image_base64", "")
    mode = message.get("mode", "full")
    task_context = message.get("task_context", "")

    logger.info("Vision request from %s: task_id=%s, mode=%s", device_id, task_id, mode)

    if not image_base64:
        return MessageBuilder.error(
            device_id or "unknown",
            "VISION_NO_IMAGE",
            "image_base64 is required for vision_request",
        )

    # 调用 VisionPipeline 进行分析
    vision_payload: Dict[str, Any] = {}
    try:
        from core.vision_pipeline import VisionPipeline
        pipeline = VisionPipeline()
        vision_result = await pipeline.understand(
            image_base64=image_base64,
            mode=mode,
            task_context=task_context,
        )
        vision_payload = {
            "success": vision_result.success,
            "analysis": vision_result.to_dict() if hasattr(vision_result, "to_dict") else {
                k: v for k, v in vars(vision_result).items() if not k.startswith("_")
            },
        }
    except Exception as e:
        logger.warning("VisionPipeline unavailable, returning raw error: %s", e)
        vision_payload = {"success": False, "error": str(e)}

    # 以 task_assign 形式把结果回推给 Android 设备
    response = MessageBuilder.vision_result(
        device_id=device_id or "unknown",
        task_id=task_id,
        result=vision_payload,
    )

    # 通过 WebSocket 主动推送（异步，不等待 ACK）
    try:
        if websocket is not None:
            await websocket.send_json(response)
    except Exception as e:
        logger.warning("Failed to push vision_result to %s: %s", device_id, e)

    return response
