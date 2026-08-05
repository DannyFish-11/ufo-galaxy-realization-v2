"""core.status_ws_envelope — ``/ws/status`` 那条推送通道的信封，只此一处

要解决什么
==========
本仓有**两个** ``/ws/status``，路径同名、端口不同、信封不同：

* ``core/api_routes.py``（主 app）    → ``{"type": "initial_status", ...}``
* ``core/device_status_api.py``（:8766）→ ``{"event": "initial_status", "data": {...}}``

而 :8766 那个自己内部还不一致：推送用 ``event``，``pong`` 却用 ``type``。

后果不是"两种风格"。写客户端的人按其中一个端口调通之后连上另一个，收到的帧
``msg.type`` 是 ``undefined`` —— 不报错、不断连，只是**什么都解析不出来**，而路径
名一模一样，排查时根本不会怀疑连错了端口。三仓当前零客户端，所以这条现在不疼；
它疼的时刻恰恰是有人开始写第一个客户端的时候。

判据
====
规范键是 ``type``。理由不是投票，是**仓库其余部分都用它**：AIP v3 的
``AIPMessage.type``、兼容设备入口、面板在场通道，无一例外。``event`` 只在 :8766
出现，是那一个文件的历史遗留。

``legacy_event_key``
====================
只给 :8766 用，且只是**迁移垫片**：它的历史帧长着 ``event``，仓外可能有按那个键
写的脚本（三仓里没有，但这里看不见用户自己的工具）。开着它时同一个值会同时以
``type`` 与 ``event`` 出现 —— 两者出自**同一个入参**，结构上不可能不一致，因此这
不是"第二份定义"，而是一条明确标注了退役条件的兼容边。

主 app 那侧不开：它的帧从来没有过 ``event``，凭空加一个只会让"规范键是哪个"
重新变得可争论。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

__all__ = ["STATUS_FRAME_CANONICAL_KEY", "STATUS_FRAME_LEGACY_KEY", "build_status_frame"]

#: 规范键。变更它等于变更 ``/ws/status`` 的线上契约。
STATUS_FRAME_CANONICAL_KEY = "type"

#: 迁移垫片键，仅 :8766 使用。见模块头说明。
STATUS_FRAME_LEGACY_KEY = "event"


def build_status_frame(
    event_name: str,
    *,
    legacy_event_key: bool = False,
    **fields: Any,
) -> Dict[str, Any]:
    """构造一帧 ``/ws/status`` 消息。

    Args:
        event_name: 事件名（``initial_status`` / ``pong`` / ``device_status`` …）。
        legacy_event_key: 是否同时以历史键 ``event`` 带出同一个值。仅 :8766 开。
        **fields: 该事件自己的字段。调用方**不要**自己塞 ``timestamp`` ——
            由这里统一盖，否则两个端点的时间格式会各走各的。

    Returns:
        可直接 ``send_json`` 的 dict。
    """
    frame: Dict[str, Any] = {STATUS_FRAME_CANONICAL_KEY: event_name}
    if legacy_event_key:
        frame[STATUS_FRAME_LEGACY_KEY] = event_name
    frame.update(fields)
    frame["timestamp"] = datetime.now().isoformat()
    return frame
