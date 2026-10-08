"""galaxy_gateway/android/ingress_trust.py — 这条连接上的发送方，认证过没有。

为什么需要它
============
规范入口把一帧帧消息交给各个处理器，而处理器各自并不知道"这帧是不是一个认证过的
设备发的"。对只读/记账类消息这没关系；但手表发来的 ``command`` 会**进智能体的主链**
（语音提问），也会**回答待决策**（批准一次高风险操作）——这两件事不能让一条没认证过的
连接去做。

"认证过"的定义（认证开启时）：

* 这条连接上收到过 ``auth_ok``（``handle_auth`` 记下，并绑定当时的连接对象），或者
* 这台设备已经在**这条连接上**成功登记（``device_register`` 在认证不过时会被拒，
  登记成功本身就说明凭证验过）。

两条都按**连接对象**判，不按 device_id 判：否则另开一条连接、自报同一个 device_id，
就能借用别人的认证结果。认证关闭时（开放网关模式）一律放行 —— 与 ``handle_auth``
回 ``auth_enforced=false`` 的诚实口径一致。
"""

from __future__ import annotations

from typing import Any


def sender_is_trusted(bridge: Any, websocket: Any, device_id: str) -> bool:
    """这条连接上、自称 ``device_id`` 的发送方，是否已经通过认证。"""
    try:
        from core.auth import is_auth_enabled

        if not is_auth_enabled():
            return True
    except Exception:  # noqa: BLE001 — 认证模块不可用时按"需要认证"处理（fail-closed）
        pass

    if websocket is None or not device_id:
        return False

    state = (getattr(bridge, "_connection_auth_state", None) or {}).get(device_id) or {}
    ref = state.get("ws")
    if state.get("authenticated") and callable(ref) and ref() is websocket:
        return True

    device = (getattr(bridge, "_devices", None) or {}).get(device_id)
    return device is not None and getattr(device, "websocket", None) is websocket


def forget_connection_auth(bridge: Any, device_id: str, websocket: Any) -> None:
    """连接断开时作废这条连接上的认证结果（只作废绑在**这条**连接上的，别的连接不受影响）。"""
    table = getattr(bridge, "_connection_auth_state", None)
    ref = ((table or {}).get(device_id) or {}).get("ws")
    if websocket is not None and callable(ref) and ref() is websocket:
        table.pop(device_id, None)
