"""core/presence_line.py — 入口分流：谁发起的请求，才进桌面三态。

规则（这是架构，不是开关）
==========================
桌面三态（SILENT / LIMINAL / MANIFEST）是**电脑这具身体**的表达。只有**从电脑这边发起**的
请求进三态；手机、手表、平板、另一台电脑、任何经通用接入进来的参与方 —— 不看类型、不看
是否登记 —— 发起的请求**一律不进**：直接交给智能体处理，相位只回推给发起的那台设备。

「从电脑这边发起」按类型化字段判，不猜文本（见 :mod:`core.semantic_anchoring` 的判据）：

========================== =====================================================
入口 ``source``            判定
========================== =====================================================
``REMOTE_SOURCES``         不进。入口本身就说明请求来自别的设备。
``LOCAL_BODY_SOURCES``     进。本机麦克风、唤醒词、自发注意力、主动感知、桌面视觉。
``DESKTOP_CONTROL_SOURCES`` 进。操作员面板、OpenClawd 直调、E2E 编排是桌面的控制面 ——
                           它们带的 ``device_id`` 可能是**目标**设备（操作员把任务派给
                           手机），所以按入口判，不按 ``device_id`` 判。
其他（含 ``chat``）         ``device_id`` 是**发起**设备：没带、或是本机自己的标识 → 进；
                           其余一律不进。
========================== =====================================================

**电脑上发起的跨设备 / 混合任务仍是电脑发起的。** 桌面面板发请求不带 ``device_id``，目标设备
走 ``target_device`` / ``entry_mode``，操作员派发走控制面入口 —— 目标是别的设备不改变发起方，
照样走三态。它与「手机发起的请求」不是一回事。

有需要才进
==========
不进三态的请求照常由智能体处理：会话里的相位照常推进（认知段的阈限内容、预演闸门照常
工作），只是不外显到桌面 —— 不发 ``phase.*``、不落桌面相位账、不起 continuum tick、不改
桌面在场模式、不在电脑上朗读回复；相位只推给发起的那台设备。

一旦它**真的在本机落手**（computer-use 操作本机屏幕、混合执行器操作本机应用），桌面就成了
在做事的那具身体：:func:`attach_to_host` 把会话交还桌面，经正常的 ``advance()`` 补放
``SILENT → LIMINAL（→ MANIFEST）``。落手的目标不是本机（手机、别的电脑）时不交还。触发点在
:func:`core.liminal_activity.note_local_actuation`。

没有开关
========
曾经有 ``GALAXY_PRESENCE_LINE`` / ``GALAXY_PRESENCE_LINE_LEGACY_SOURCES`` 两个回退开关，也曾
把「未登记的设备、另一台电脑」按宿主处理。按仓库所有者的要求两者都删了：谁发起就归谁，
不是可调的偏好。

本模块在热路径上（每请求一次），因此**不得** import ``core.meta``（守卫 G10），
模块级也只依赖标准库。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, FrozenSet, Optional, Set

logger = logging.getLogger("Galaxy.PresenceLine")

#: 入口本身就说明请求来自别的设备。
REMOTE_SOURCES: FrozenSet[str] = frozenset(
    {"wear_voice", "wear_decision", "android_goal_execution", "android_vision", "participant_task"}
)

#: 本机的耳朵与眼睛 —— 物理上就长在这台电脑上。
LOCAL_BODY_SOURCES: FrozenSet[str] = frozenset(
    {"voice", "voice_wake", "ambient", "active_perception", "desktop_vision"}
)

#: 桌面的控制面。它们带的 ``device_id`` 可能是目标设备，不能拿来判发起方。
DESKTOP_CONTROL_SOURCES: FrozenSet[str] = frozenset({"operator", "openclawd", "e2e"})

HOST_SOURCES: FrozenSet[str] = LOCAL_BODY_SOURCES | DESKTOP_CONTROL_SOURCES

_LOCAL_ALIASES: FrozenSet[str] = frozenset({"local", "localhost", "host", "desktop"})

#: 运行时登记的本机标识（例如桌面在场运行时开跨设备时铸的 ``galaxy_desktop_*``）。
_registered_local_ids: Set[str] = set()


@dataclass(frozen=True)
class PresenceLineDecision:
    host_bound: bool
    origin_device_id: str
    reason: str


def register_local_identity(device_id: Optional[str]) -> None:
    """把一个标识登记为「就是这台电脑」。由持有本机身份的模块在铸出身份时调用。"""
    did = (device_id or "").strip()
    if did:
        _registered_local_ids.add(did)


def _local_device_id() -> str:
    try:
        from core.agent_card import local_device_id

        return local_device_id()
    except Exception:  # noqa: BLE001
        return ""


def is_local_body(device_id: Optional[str]) -> bool:
    """这个标识是不是这台电脑自己。没带标识也算 —— 桌面面板发请求就不带。"""
    did = (device_id or "").strip()
    if not did or did.lower() in _LOCAL_ALIASES or did in _registered_local_ids:
        return True
    return did == _local_device_id()


def decide_presence_line(source: str, device_id: Optional[str]) -> PresenceLineDecision:
    origin = (device_id or "").strip()
    if source in REMOTE_SOURCES:
        return PresenceLineDecision(False, origin, "remote_source")
    if source in LOCAL_BODY_SOURCES:
        return PresenceLineDecision(True, origin, "local_body_source")
    if source in DESKTOP_CONTROL_SOURCES:
        return PresenceLineDecision(True, origin, "desktop_control_source")
    if is_local_body(origin):
        return PresenceLineDecision(True, origin, "desktop_origin" if origin else "no_device")
    return PresenceLineDecision(False, origin, "other_device")


def bind_presence_line(session: Any, source: str, device_id: Optional[str]) -> PresenceLineDecision:
    """建会话时判一次，写到会话上。判定本身出错时按宿主处理，并记一条告警。"""
    try:
        decision = decide_presence_line(source, device_id)
    except Exception:  # noqa: BLE001 — 分流判定绝不拖垮请求
        logger.warning("presence_line: decision failed, treating as desktop-originated", exc_info=True)
        decision = PresenceLineDecision(True, (device_id or "").strip(), "decision_failed")
    session.host_bound = decision.host_bound
    session.origin_device_id = decision.origin_device_id
    session.presence_line_reason = decision.reason
    if not decision.host_bound:
        logger.info(
            "请求不进桌面三态 | runtime_session_id=%s source=%s origin=%s reason=%s",
            getattr(session, "runtime_session_id", "?"),
            source,
            decision.origin_device_id or "-",
            decision.reason,
        )
    return decision


def advance_detached(session: Any, old_state: Any, new_state: Any) -> None:
    """不进三态的会话的相位推进：只推给发起请求的那台设备。"""
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
    """不进三态的请求在本机落手 —— 把它交还给桌面，并补放相位。

    Returns:
        ``True`` 表示这一次调用真的把会话从「不进」改成了「进」。
    """
    if session is None or getattr(session, "host_bound", True):
        return False
    if not is_local_body(target_device_id):
        return False  # 落手落在别的设备上，桌面仍然不是主角
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
    "DESKTOP_CONTROL_SOURCES",
    "HOST_SOURCES",
    "LOCAL_BODY_SOURCES",
    "REMOTE_SOURCES",
    "PresenceLineDecision",
    "advance_detached",
    "attach_to_host",
    "bind_presence_line",
    "decide_presence_line",
    "is_local_body",
    "register_local_identity",
]
