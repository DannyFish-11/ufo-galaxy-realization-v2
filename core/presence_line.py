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
``AGENT_AUTONOMOUS_SOURCES`` 不进。智能体自己发起的工作（定时心跳等），没有人在电脑前等它。
``LOCAL_BODY_SOURCES``     进。本机麦克风、唤醒词、自发注意力、主动感知、桌面视觉。
``DESKTOP_CONTROL_SOURCES`` 进。操作员面板、OpenClawd 直调、E2E 编排是桌面的控制面 ——
                           它们带的 ``device_id`` 可能是**目标**设备（操作员把任务派给
                           手机），所以按入口判，不按 ``device_id`` 判。
其他（含 ``chat``）         1. 请求声明来自桌面外壳（``client_surface="desktop_shell"``，
                              只有 Electron 外壳会带）→ 进；
                           2. 带了 ``device_id``（发起设备）：是本机标识 → 进，其余不进；
                           3. 没带 ``device_id``：连接来源是别的机器 → 不进；是本机或
                              说不清（不是 IP，例如进程内测试客户端）→ 进。
========================== =====================================================

「连接来源是不是本机」不看地址长得像不像本地，而是**试着绑定它**：绑得上就是这台机器自己的
地址（回环、局域网网卡、Tailscale 都算），绑不上就是别的机器。桌面外壳显式声明自己，是因为
容器、端口转发这类部署里外壳的连接地址未必是本机地址 —— 只靠地址会把电脑自己的对话判走。

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

智能体自己发起的工作
====================
不在任何一次请求里的自主工作（``core.openclawd_heartbeat`` 的定时心跳）经
:func:`autonomous_session` 拿到一条会话：不进三态、不朗读、没有发起设备可推；它若真在本机
落手，同样经 :func:`attach_to_host` 交还桌面 —— 与别的设备发起的请求同一条规则。

回复归发起方
============
会话上分开记两件事：``desktop_originated``（是不是电脑发起的，建会话时定下、不再变）与
``host_bound``（此刻是否外显到桌面，落手时会变成 ``True``）。在电脑上朗读回复看前者 ——
手机让电脑去点一下屏幕，桌面该显出它在动手，但回答仍该回到手机，而不是在电脑上念出来。

对外接口
========
* :func:`decide_presence_line` / :func:`bind_presence_line` —— 判定与写入会话；
* :func:`attach_to_host` —— 有需要时进三态（由 ``note_local_actuation`` 调）；
* :func:`autonomous_session` —— 智能体自主工作的会话；
* :func:`activity_snapshot` —— 智能体此刻在处理的全部请求，含不进三态的（``GET /api/v1/agent/activity``）。

没有开关
========
曾经有 ``GALAXY_PRESENCE_LINE`` / ``GALAXY_PRESENCE_LINE_LEGACY_SOURCES`` 两个回退开关，也曾
把「未登记的设备、另一台电脑」按宿主处理。按仓库所有者的要求两者都删了：谁发起就归谁，
不是可调的偏好。

本模块在热路径上（每请求一次），因此**不得** import ``core.meta``（守卫 G10），
模块级也只依赖标准库。
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, AsyncIterator, Callable, Dict, FrozenSet, Iterable, MutableMapping, Optional, Set

logger = logging.getLogger("Galaxy.PresenceLine")

#: 入口本身就说明请求来自别的设备。
REMOTE_SOURCES: FrozenSet[str] = frozenset(
    {"wear_voice", "wear_decision", "android_goal_execution", "android_vision", "participant_task"}
)

#: 智能体自己发起的工作 —— 没有发起设备，也没有人在电脑前等它。
AGENT_AUTONOMOUS_SOURCES: FrozenSet[str] = frozenset({"heartbeat"})

#: 桌面外壳（Electron）在请求里声明自己时用的值。
DESKTOP_SHELL_SURFACE = "desktop_shell"

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


@lru_cache(maxsize=256)
def _bindable(host: str, family: int) -> bool:
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.bind((host, 0))
        return True
    except OSError:
        return False


def is_local_address(host: Optional[str]) -> Optional[bool]:
    """连接来源是不是这台电脑。不是 IP（例如进程内测试客户端的 ``testclient``）返回 ``None``：说不清。"""
    try:
        ip = ipaddress.ip_address((host or "").strip())
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return True
    family = socket.AF_INET6 if isinstance(ip, ipaddress.IPv6Address) else socket.AF_INET
    return _bindable(str(ip), family)


def decide_presence_line(
    source: str,
    device_id: Optional[str],
    *,
    client_host: Optional[str] = None,
    client_surface: Optional[str] = None,
) -> PresenceLineDecision:
    origin = (device_id or "").strip()
    if source in REMOTE_SOURCES:
        return PresenceLineDecision(False, origin, "remote_source")
    if source in AGENT_AUTONOMOUS_SOURCES:
        return PresenceLineDecision(False, "", "agent_autonomous")
    if source in LOCAL_BODY_SOURCES:
        return PresenceLineDecision(True, origin, "local_body_source")
    if source in DESKTOP_CONTROL_SOURCES:
        return PresenceLineDecision(True, origin, "desktop_control_source")
    if client_surface == DESKTOP_SHELL_SURFACE:
        return PresenceLineDecision(True, origin, "desktop_shell")
    if origin:
        if is_local_body(origin):
            return PresenceLineDecision(True, origin, "desktop_origin")
        return PresenceLineDecision(False, origin, "other_device")
    if is_local_address(client_host) is False:
        return PresenceLineDecision(False, "", "other_address")
    return PresenceLineDecision(True, "", "no_device")


def request_origin(request: Any, client_surface: Optional[str] = None) -> Dict[str, Optional[str]]:
    """从 HTTP 请求取出分流要的两样：连接来源地址、发起界面。``request`` 是 Starlette 的 Request。"""
    client = getattr(request, "client", None)
    return {"client_host": getattr(client, "host", None), "client_surface": client_surface}


def bind_presence_line(
    session: Any,
    source: str,
    device_id: Optional[str],
    *,
    client_host: Optional[str] = None,
    client_surface: Optional[str] = None,
) -> PresenceLineDecision:
    """建会话时判一次，写到会话上。判定本身出错时按宿主处理，并记一条告警。"""
    try:
        decision = decide_presence_line(source, device_id, client_host=client_host, client_surface=client_surface)
    except Exception:  # noqa: BLE001 — 分流判定绝不拖垮请求
        logger.warning("presence_line: decision failed, treating as desktop-originated", exc_info=True)
        decision = PresenceLineDecision(True, (device_id or "").strip(), "decision_failed")
    session.host_bound = decision.host_bound
    session.desktop_originated = decision.host_bound
    session.origin_device_id = decision.origin_device_id
    session.presence_line_reason = decision.reason
    if not decision.host_bound:
        logger.info(
            "请求不进桌面三态 | runtime_session_id=%s source=%s origin=%s reason=%s",
            getattr(session, "runtime_session_id", "?"),
            source,
            decision.origin_device_id or client_host or "-",
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


@asynccontextmanager
async def autonomous_session(
    kind: str, create: Callable[[str], Any], sessions: MutableMapping[str, Any]
) -> AsyncIterator[Any]:
    """智能体自己发起的一段工作：不进三态；期间若在本机落手，经 ``note_local_actuation`` 交还桌面。

    ``create`` / ``sessions`` 由在场运行时传入（它的建会话方法与活动会话表）——
    自主工作与请求用同一种会话，所以 :func:`activity_snapshot`、落手交还都自动适用。
    """
    from core.liminal_activity import bind_runtime_session, unbind_runtime_session

    session = create(kind)
    bind_presence_line(session, kind, None)
    token = bind_runtime_session(session)
    phase = type(session.tristate)
    try:
        session.advance(phase("liminal"))
        yield session
    finally:
        try:
            if session.tristate.value == "liminal":
                session.advance(phase("manifest"))
            session.advance(phase("silent"))
        finally:
            sessions.pop(session.runtime_session_id, None)
            unbind_runtime_session(token)


def activity_snapshot(sessions: Iterable[Any]) -> Dict[str, Any]:
    """智能体此刻在处理的全部请求 —— 进三态的与不进的都在，一眼看出智能体没被桌面拴住。"""
    now = time.monotonic()
    rows = [
        {
            "runtime_session_id": s.runtime_session_id,
            "source": s.source,
            "origin_device_id": getattr(s, "origin_device_id", "") or "",
            "desktop_originated": bool(getattr(s, "desktop_originated", True)),
            "in_tri_state": bool(getattr(s, "host_bound", True)),
            "reason": getattr(s, "presence_line_reason", "") or "",
            "phase": s.tristate.value,
            "age_s": round(max(0.0, now - float(getattr(s, "created_at", now))), 3),
        }
        for s in list(sessions)
    ]
    inside = sum(1 for r in rows if r["in_tri_state"])
    return {"sessions": rows, "in_tri_state": inside, "outside_tri_state": len(rows) - inside}


__all__ = [
    "AGENT_AUTONOMOUS_SOURCES",
    "DESKTOP_CONTROL_SOURCES",
    "DESKTOP_SHELL_SURFACE",
    "HOST_SOURCES",
    "LOCAL_BODY_SOURCES",
    "REMOTE_SOURCES",
    "PresenceLineDecision",
    "activity_snapshot",
    "advance_detached",
    "attach_to_host",
    "autonomous_session",
    "bind_presence_line",
    "decide_presence_line",
    "is_local_address",
    "is_local_body",
    "register_local_identity",
    "request_origin",
]
