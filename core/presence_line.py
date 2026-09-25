"""core/presence_line.py — 入口分流：这一次请求，桌面这具身体要不要跟着动。

要解决什么（R3）
================
``DesktopPresenceRuntime.handle_request()`` 是所有入口的唯一收口 —— 桌面对话、手机
提交的任务、手表语音、手机截屏分析都经过它，这是对的（冻结守则 R1.1：不另起一套
入口）。但收口之后，**每一次**相位推进都做同样四件事：

1. 在状态事件总线上发 ``phase.*`` —— 桌面外壳（lumiv 桥）订阅它来驱动三态动画；
2. 落相位耐久账 —— 「这三天桌面是什么样子」；
3. 把相位广播给**所有**已连的手机与手表；
4. 起停 200ms 的 continuum tick —— 同样只喂桌面外壳。

而 lumiv 桥**不看** ``request_source``。于是手机上发一句「帮我查快递」，桌面外壳在
LIMINAL/MANIFEST 之间翻一遍，另一台手机和手表也跟着抖 —— 桌面这具身体什么都没做，
却表现得像它在做。三态说的是「主体在哪一相」，表达它的必须是**真在做事的那具身体**。

本模块做的判定
==============
一次请求建会话时判一次，结果写在 ``RuntimeSession`` 上两个字段：

* ``host_bound`` —— 这次请求是不是桌面这具身体自己的事。``True`` 时一切照旧。
* ``origin_device_id`` —— 请求来自哪台设备。

``host_bound=False``（下称「游离」）时，相位照常推进、照常记在会话里（认知段的阈限
内容、预演闸门都照常工作），只是**不外显到桌面**：上面 1、2、4 跳过，3 只推给发起
请求的那台设备 —— 手机上的三态照样是完整的。

判据只读类型化字段，不猜文本（见 :mod:`core.semantic_anchoring` 的判据）：

====================== ==========================================================
入口 ``source``        判定
====================== ==========================================================
``REMOTE_SOURCES``     游离。入口本身就说明请求来自远端身体。
``HOST_SOURCES``       宿主。本机麦克风、本机感知、本机操作员。
其他（含 ``chat``）    看 ``device_id``：空、等于本机标识 → 宿主；在设备注册表里
                       登记为 ``REMOTE_DEVICE_KINDS`` 之一 → 游离；其余 → 宿主。
====================== ==========================================================

「其余 → 宿主」是刻意的：未登记的设备、浏览器、另一台 PC 都按旧行为处理。另一台 PC
**不**算远端 —— 桌面自己的客户端可能以 ``windows_xxx`` 之类的标识注册，把它判成远端
会让本机对话的外壳静默下去，那是比「手机任务时桌面多抖一下」更糟的错误。宁可漏分，
不可错分。

落手即归位
==========
游离的请求一旦**真的在本机落手**（混合执行器操作本机应用、computer-use 操作本机
屏幕），它就成了桌面这具身体的事。:func:`attach_to_host` 把会话改回宿主，并经
正常的 ``advance()`` 补放一遍 ``SILENT → LIMINAL（→ MANIFEST）`` —— 外壳从这一刻
起看到的相位与宿主请求完全一致。触发点在 :func:`core.liminal_activity.note_local_actuation`。

开关
====
* ``GALAXY_PRESENCE_LINE=off`` —— 整体回退：所有请求都是宿主，行为与引入本模块前逐位一致。
* ``GALAXY_PRESENCE_LINE_LEGACY_SOURCES=a,b`` —— 按入口回退：列出的 ``source`` 一律按宿主处理。

本模块在热路径上（每请求一次），因此**不得** import ``core.meta``（守卫 G10），
模块级也只依赖标准库。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, FrozenSet, Optional

logger = logging.getLogger("Galaxy.PresenceLine")

PRESENCE_LINE_ENV = "GALAXY_PRESENCE_LINE"
PRESENCE_LINE_LEGACY_SOURCES_ENV = "GALAXY_PRESENCE_LINE_LEGACY_SOURCES"

#: 入口本身就说明请求来自远端身体。
REMOTE_SOURCES: FrozenSet[str] = frozenset({"wear_voice", "wear_decision", "android_goal_execution", "android_vision"})

#: 本机的耳朵、眼睛与操作员。
HOST_SOURCES: FrozenSet[str] = frozenset(
    {"voice", "voice_wake", "ambient", "active_perception", "operator", "openclawd", "e2e"}
)

#: 登记为这些类型的设备是远端身体。取值对齐 ``UnifiedDeviceType`` 与手表注册时上报的原始类型
#: （``galaxy_gateway/android/handlers/wearos_sync.is_wearos_device``）。
REMOTE_DEVICE_KINDS: FrozenSet[str] = frozenset({"android", "ios", "wear_os", "wearos", "watch", "galaxy_watch"})

_LOCAL_ALIASES: FrozenSet[str] = frozenset({"local", "localhost", "host", "desktop"})


@dataclass(frozen=True)
class PresenceLineDecision:
    host_bound: bool
    origin_device_id: str
    reason: str


def presence_line_enabled() -> bool:
    return (os.environ.get("GALAXY_PRESENCE_LINE", "on") or "on").strip().lower() not in ("off", "0", "false", "no")


def _legacy_sources() -> FrozenSet[str]:
    raw = os.environ.get("GALAXY_PRESENCE_LINE_LEGACY_SOURCES", "") or ""
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _local_device_id() -> str:
    try:
        from core.agent_card import local_device_id

        return local_device_id()
    except Exception:  # noqa: BLE001
        return ""


def registered_device_kind(device_id: str) -> str:
    """设备在注册表里登记的类型；查不到返回空串。

    先读 UDM（设备的事实来源），再读兼容缓存 ``registered_devices`` —— 手表经网关
    ``handle_register`` 注册，原始类型（``wear_os`` 等）只留在后者里。
    """
    if not device_id:
        return ""
    try:
        from core.unified.device_manager import get_unified_device_manager

        device = get_unified_device_manager().get_device(device_id)
        if device is not None:
            kind = getattr(device.device_type, "value", device.device_type)
            if kind and str(kind).lower() != "unknown":
                return str(kind).lower()
    except Exception:  # noqa: BLE001 — 查不到就按查不到处理
        logger.debug("presence_line: UDM lookup failed for %s", device_id, exc_info=True)
    try:
        from core.routes._shared import registered_devices

        return str((registered_devices.get(device_id) or {}).get("device_type", "")).lower()
    except Exception:  # noqa: BLE001
        return ""


def is_remote_device(device_id: Optional[str]) -> bool:
    """这台设备是不是一具远端身体。空、本机标识、未登记 —— 都不是。"""
    did = (device_id or "").strip()
    if not did or did.lower() in _LOCAL_ALIASES or did == _local_device_id():
        return False
    return registered_device_kind(did) in REMOTE_DEVICE_KINDS


def decide_presence_line(source: str, device_id: Optional[str]) -> PresenceLineDecision:
    origin = (device_id or "").strip()
    if not presence_line_enabled():
        return PresenceLineDecision(True, origin, "presence_line_off")
    if source in _legacy_sources():
        return PresenceLineDecision(True, origin, "legacy_source")
    if source in REMOTE_SOURCES:
        return PresenceLineDecision(False, origin, "remote_source")
    if source in HOST_SOURCES:
        return PresenceLineDecision(True, origin, "host_source")
    if is_remote_device(origin):
        return PresenceLineDecision(False, origin, "remote_device")
    return PresenceLineDecision(True, origin, "host_device" if origin else "no_device")


def bind_presence_line(session: Any, source: str, device_id: Optional[str]) -> PresenceLineDecision:
    """建会话时判一次，写到会话上。判定失败按宿主处理（旧行为）。"""
    try:
        decision = decide_presence_line(source, device_id)
    except Exception:  # noqa: BLE001 — 分流判定绝不拖垮请求
        logger.debug("presence_line: decision failed, falling back to host", exc_info=True)
        decision = PresenceLineDecision(True, (device_id or "").strip(), "decision_failed")
    session.host_bound = decision.host_bound
    session.origin_device_id = decision.origin_device_id
    session.presence_line_reason = decision.reason
    if not decision.host_bound:
        logger.info(
            "请求不外显到桌面 | runtime_session_id=%s source=%s origin=%s reason=%s",
            getattr(session, "runtime_session_id", "?"),
            source,
            decision.origin_device_id or "-",
            decision.reason,
        )
    return decision


def advance_detached(session: Any, old_state: Any, new_state: Any) -> None:
    """游离会话的相位推进：只推给发起请求的那台设备。"""
    origin = getattr(session, "origin_device_id", "") or ""
    if not origin:
        return
    try:
        from core.cross_device_sync import emit_cross_device_phase_sync

        emit_cross_device_phase_sync(
            old_phase=old_state.value,
            new_phase=new_state.value,
            session_id=session.runtime_session_id,
            source=session.source,
            trace_id=session.trace_id,
            target_device_id=origin,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("presence_line: detached phase push skipped: %s", exc)


def attach_to_host(session: Any, kind: str, target_device_id: Optional[str] = "") -> bool:
    """游离的请求在本机落手 —— 把它交还给桌面，并补放相位。

    Returns:
        ``True`` 表示这一次调用真的把会话从游离改成了宿主。
    """
    if session is None or getattr(session, "host_bound", True):
        return False
    if is_remote_device(target_device_id):
        return False  # 落手落在远端身体上，桌面仍然不是主角
    tri_state = type(session.tristate)
    current = session.tristate
    activity, summary = session.liminal_activity, session.simulation_summary
    session.host_bound = True
    session.presence_line_reason = f"attached:{kind}"
    # 宿主视角里这个会话此前一直是静默的：从 SILENT 起，经正常 advance 补放。
    session.tristate = tri_state("silent")
    session.advance(tri_state("liminal"))
    if current.value == "manifest":
        session.advance(tri_state("manifest"))
    else:
        session.liminal_activity, session.simulation_summary = activity, summary
    logger.info(
        "请求在本机落手，交还桌面 | runtime_session_id=%s kind=%s phase=%s",
        getattr(session, "runtime_session_id", "?"),
        kind,
        current.value,
    )
    return True


__all__ = [
    "HOST_SOURCES",
    "PRESENCE_LINE_ENV",
    "PRESENCE_LINE_LEGACY_SOURCES_ENV",
    "REMOTE_DEVICE_KINDS",
    "REMOTE_SOURCES",
    "PresenceLineDecision",
    "advance_detached",
    "attach_to_host",
    "bind_presence_line",
    "decide_presence_line",
    "is_remote_device",
    "presence_line_enabled",
    "registered_device_kind",
]
