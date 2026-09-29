"""core/unified/presence_fanout.py — 设备上线 / 离线 / 心跳，从 UDM 这一个写入点通知到其余被动方。

UDM 是设备状态的唯一写入口（SSOT）。此前它只把状态写给自己、能力总线、能力权威与 NATS worker 平面；
另外几处各自写好了「上线 / 离线 / 心跳」的接收方法，却没有调用方：

- 网络拓扑运行时（``absorb_device_presence_event`` 的拓扑一半）：设备节点永远没有连接状态，
  ``query_routable_executors`` 读到的网络状态恒为 unknown；
- 能力同化层的在场状态：只知道设备「注册过」，不知道它掉线了、也收不到它的心跳；
- 健康评分（``DeviceHealthScorer.reset_device``）：重连的设备带着掉线前的失败样本被打低分；
- Mesh 编组（``notify_device_lost``）：掉线的设备仍挂在编组里；
- 系统资源表：模型问「有哪些设备资源」时一条也没有。

UDM 在「是否在线」翻转时调 :func:`presence_changed`、每次心跳调 :func:`heartbeat_seen`。每个下游
独立吞异常，绝不影响 UDM 写入本身。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_ACTIVE = frozenset({"online", "busy"})


def is_active(status: Any) -> bool:
    """UDM 状态是否算「在线」（能收活）。"""
    return str(getattr(status, "value", status) or "").lower() in _ACTIVE


def presence_changed(device: Any, *, online: bool, reconnected: bool = False, reason: str = "") -> None:
    """设备从离线变在线（或反过来）。``reconnected``：之前掉过线、这次是回来了。"""
    device_id = str(getattr(device, "device_id", "") or "")
    if not device_id:
        return
    try:
        from core.capability_network_runtime_policy import absorb_device_presence_event

        absorb_device_presence_event(
            device_id,
            is_online=online,
            effective_routable=online,
            host=str(getattr(device, "ip_address", "") or ""),
            port=int(getattr(device, "port", 0) or 0),
            capabilities=[str(c) for c in (getattr(device, "capabilities", None) or [])],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("presence fan-out: topology/assimilation skipped for %s: %s", device_id, exc)

    try:
        from core.system_resource import track_device_resource

        track_device_resource(
            device_id,
            online=online,
            capabilities=[str(c) for c in (getattr(device, "capabilities", None) or [])],
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("presence fan-out: system resource skipped for %s: %s", device_id, exc)

    if online and reconnected:
        try:
            from core.unified.device_health import get_device_health_scorer

            get_device_health_scorer().reset_device(device_id)
        except Exception as exc:  # noqa: BLE001
            logger.debug("presence fan-out: health reset skipped for %s: %s", device_id, exc)

    if not online:
        try:
            from core.mesh.mesh_auto_enrollment import get_enrollment_record, notify_device_lost

            # 只通知真在编组里的设备：没进过编组的设备，失联也不该凭空多出一条编组记录
            if get_enrollment_record(device_id) is not None:
                notify_device_lost(device_id, reason=reason or "offline")
        except Exception as exc:  # noqa: BLE001
            logger.debug("presence fan-out: mesh notify skipped for %s: %s", device_id, exc)


def heartbeat_seen(device_id: str) -> None:
    """设备发来心跳：同化层里它的在场状态随之刷新。"""
    try:
        from core.capability_network_runtime_policy import absorb_heartbeat_event

        absorb_heartbeat_event(device_id)
    except Exception as exc:  # noqa: BLE001
        logger.debug("presence fan-out: heartbeat skipped for %s: %s", device_id, exc)


__all__ = ["heartbeat_seen", "is_active", "presence_changed"]
