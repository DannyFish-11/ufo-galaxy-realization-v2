"""galaxy_gateway/android/transport_ucm.py — 把规范入口上的设备连接登记进 UCM。

UCM 是连接与在线的权威。规范设备入口(``/ws/device/{id}``)注册/重连成功后若不登记,
设备在 UCM 里就没有连接记录:派发就绪闸判「传输不在」、``UCM.send_to_device`` /
``send_command_and_wait`` 找不到它 —— 手机、手表、笔记本全都连着却派不到活。
此前只有旧的 websocket_handler 做过这件事。断开由 ``AndroidBridge.disconnect_device``
经 ``UCM.mark_offline`` 处理。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def attach_transport_to_ucm(device_id: str, websocket: Any, message: Dict[str, Any]) -> None:
    """登记(或重连修补)这条已通过注册的连接;是刚配对的设备就在对话里说一声连上了。"""
    try:
        from core.unified.connection_manager import get_unified_connection_manager

        ucm = get_unified_connection_manager()
        metadata = {
            "device_type": message.get("device_type"),
            "platform": message.get("platform"),
            "ingress": message.get("_ingress_path"),
        }
        if ucm.get_connection(device_id) is not None:
            await ucm.reconnect_patch(device_id, websocket, metadata)
        else:
            await ucm.register_connection(device_id, websocket, metadata)
    except Exception as exc:  # noqa: BLE001 — 登记失败不该让注册本身失败,但要看得见
        logger.warning("UCM 连接登记失败 device_id=%s: %s", device_id, exc)
        return
    try:
        from core.device_onboarding.conversation import note_connected

        await note_connected(device_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("连上播报失败(non-fatal): %s", exc)
