"""core/device_declarations.py — 设备在能力上报里自己声明的几件事。

中心怎么对待一台设备,看它自己说的,**不看它是什么类型的设备**:

* ``answers_decisions`` —— 能把问题摆到人面前、把人的回答交回来。智能体问人(``decision_request``)只发给它们;
* ``shows_request_progress`` —— 会显示自己发起的那件请求做到哪了(``state_event`` 的 ``request_progress``)。
  中心只把进度推给它们,别的设备不收这种帧。

另两样设备级声明(``hosts_agent``、``tailnet``)由派桥接 Agent、配对各自读。原来还有 ``shows_messages``
(能显示智能体主动说的话):发给谁是模型的判断,已并回各设备自己报的消息动作(``ask_human__notify`` 调它),
中心不再读(设计文档 ``docs/DEVICE_SELF_DESCRIPTION_DESIGN.md`` 4.2)。

新版设备在设备自述 ``self_description.declares`` 里声明(``core/device_self.py`` 展开回这里读的顶层字段);
旧版设备在 ``capability_report`` 顶层(或 ``payload`` 里),布尔值。每次报能力都记进 UDM 元数据
(``galaxy_gateway/android/handlers/capability_report.py``):登记会换掉元数据,所以每次都记;没声明的记 False ——
新版 App 去掉了某项,中心跟着不再这样对待它。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger("Galaxy.DeviceDeclarations")

#: 设备可以声明的几件事。
DECLARATIONS = ("answers_decisions", "shows_request_progress")


def declared_in(capability_report: Dict[str, Any]) -> Dict[str, bool]:
    """一份能力上报里各项声明的值(没声明 = False)。"""
    payload = capability_report.get("payload") if isinstance(capability_report.get("payload"), dict) else {}
    out: Dict[str, bool] = {}
    for key in DECLARATIONS:
        value = capability_report.get(key, payload.get(key))
        out[key] = value is True or str(value).lower() == "true"
    return out


def declares(device_id: str, what: str) -> bool:
    """这台设备声明过 ``what``(见 ``DECLARATIONS``)。查不到就是没声明。"""
    try:
        from core.unified.device_manager import get_unified_device_manager

        d = get_unified_device_manager().get_device(device_id)
    except Exception:  # noqa: BLE001
        return False
    return (getattr(d, "metadata", None) or {}).get(what) is True


async def online_devices() -> List[str]:
    """此刻在线的设备。**以 UCM 为准**(规范入口 ``/ws/device/{id}`` 注册成功后会登记进去);
    旧入口连上来的设备仍然认得(并集)。"""
    candidates: List[str] = []
    try:
        from core.unified.connection_manager import get_unified_connection_manager

        for did, view in get_unified_connection_manager().get_presence_view().items():
            if view.get("online") and view.get("routable"):
                candidates.append(did)
    except Exception as exc:  # noqa: BLE001
        logger.debug("online_devices: UCM unavailable: %s", exc)
    try:
        from core import upper_ports

        connection_manager = upper_ports.resolve("gateway.websocket_handler.connection_manager")
        for did in await connection_manager.get_connected_devices():
            if did not in candidates:
                candidates.append(did)
    except Exception:  # noqa: BLE001
        pass
    return candidates


async def online_devices_that(what: str) -> List[str]:
    """在线、并且自己声明过 ``what`` 的设备。"""
    return [did for did in await online_devices() if declares(did, what)]
