"""core/a2a_link.py — 对外 A2A:中心智能体与派出去的 Agent 之间的通话协议(跨设备整体方案阶段 2)。

中心智能体内部的多 Agent 协作已经有(``core/agent_team.py`` 六种模式,进程内);这里是**对外**那一套:
中心与派到手机上的桥接 Agent、Linux / 云载体上的 Agent 之间。代码里另一个叫「A2A」的是混合执行里
「直接调应用 API / MCP」那一级(``core/hybrid_executor.py``),和这里不是一回事。

它跑在 AIP v3 上:一条 ``type="a2a"`` 帧,信封(:class:`Envelope`)放在 ``payload`` 里;设备经现有的
WebSocket 连接(自建内网或局域网)收发。安卓 / 手表共用的那一半在 ufo-galaxy-android
``shared-protocol/.../A2A.kt``,两端线格式与语义逐字一致(``tests/test_external_a2a_link.py`` 与
``A2ALinkTest`` 是同一组场景)。

「必达」由 :class:`Link` 保证:

* 发送方留着没收到确认的消息,重连后按序号补发(:meth:`Link.unacked`);
* 接收方按消息号去重,对每条要确认的消息回 ``ack``(重复的也回,发送方才会停);
* 同一会话按序号排序交付,先到的后面的消息先缓着,等前面的补上;缺口一直补不上时不把整条链路卡死。

哪一端重启都不会卡住或吞掉消息:每条信封带发送方链路的 ``epoch``(这一次的身份,重启就换)和 ``floor``
(发送方手里还没确认的最小序号 —— 比它小的都已了结)。接收方看到对端换了 ``epoch``(对端重启了,或者是
自己重启了、还不认识对端)就从 ``floor`` 重新数;同一个 ``epoch`` 里 ``floor`` 只会往前推,推过去的缺口
(丢了、又不要确认的消息)不再等。重启那一端手里没发出去的消息随进程没了 —— 等它们的协程也没了,
补发给谁都没有意义。

六类消息(加确认)见 :class:`Kind`;各类消息到了做什么由 :func:`register_handler` 登记(阶段 3 起:
接入握手、上下文交接、对话、委派目标、能力调用、交还)。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.A2A")

PROTOCOL = "a2a/1"
AIP_TYPE = "a2a"
MAX_SEEN = 4096
MAX_BUFFERED = 256

#: 中心智能体在 A2A 里的名字。派出去的 Agent 叫 ``agent:<device_id>``。
CENTER_AGENT = "center"


class Kind(str, Enum):
    AGENT_DISPATCH = "agent_dispatch"  # 中心 → 载体:派一个桥接 Agent 过去(接入握手)
    AGENT_INSTALLED = "agent_installed"  # 载体 → 中心:已装好
    CONTEXT_HANDOFF = "context_handoff"  # 载体 → 中心:本地上下文交接
    CONVERSATION = "conversation"  # 双向:人说的话上行,回答与进度下行
    DELEGATE_GOAL = "delegate_goal"  # 中心 → 载体:整段目标交给载体做
    DELEGATE_PROGRESS = "delegate_progress"  # 载体 → 中心:进度
    DELEGATE_RESULT = "delegate_result"  # 载体 → 中心:结果
    TOOL_CALL = "tool_call"  # 双向:调对方的一个能力
    TOOL_RESULT = "tool_result"  # 双向:能力调用的结果
    CONTEXT_RETURN = "context_return"  # 中心 → 载体:上下文交还
    RECALL = "recall"  # 中心 → 载体:收回派出去的 Agent
    ACK = "ack"  # 确认:不占序号、不再确认


KINDS = frozenset(k.value for k in Kind)


def agent_id_for(device_id: str) -> str:
    return f"agent:{device_id}"


@dataclass
class Envelope:
    """一条 A2A 消息。``seq`` 是同一链路同一方向上的序号,从 1 起;确认帧为 0(不排序)。"""

    msg_id: str
    seq: int
    session_id: str
    from_agent: str
    to_agent: str
    kind: str
    body: Dict[str, Any] = field(default_factory=dict)
    task_id: str = ""
    trace_id: str = ""
    ack_required: bool = True
    ts: int = 0
    epoch: str = ""
    floor: int = 0
    protocol: str = PROTOCOL

    def to_dict(self) -> Dict[str, Any]:
        return {
            "protocol": self.protocol,
            "msg_id": self.msg_id,
            "seq": self.seq,
            "session_id": self.session_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "kind": self.kind,
            "body": dict(self.body),
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "ack_required": self.ack_required,
            "ts": self.ts,
            "epoch": self.epoch,
            "floor": self.floor,
        }

    def to_aip_frame(self, device_id: str) -> Dict[str, Any]:
        """包成一条 AIP v3 帧(信封进 payload)。"""
        return {
            "version": "3.0",
            "type": AIP_TYPE,
            "device_id": device_id,
            "timestamp": self.ts,
            "payload": self.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Any) -> Optional["Envelope"]:
        """解析一条信封;协议不对、缺必填字段、kind 不认识时返回 None(不猜)。"""
        if not isinstance(d, dict) or d.get("protocol") != PROTOCOL:
            return None
        kind = str(d.get("kind") or "")
        msg_id = str(d.get("msg_id") or "")
        seq = d.get("seq")
        if kind not in KINDS or not msg_id or not isinstance(seq, int) or isinstance(seq, bool):
            return None
        body = d.get("body") if isinstance(d.get("body"), dict) else {}
        ack = d.get("ack_required")
        floor = d.get("floor")
        return cls(
            msg_id=msg_id,
            seq=seq,
            session_id=str(d.get("session_id") or ""),
            from_agent=str(d.get("from_agent") or ""),
            to_agent=str(d.get("to_agent") or ""),
            kind=kind,
            body=body,
            task_id=str(d.get("task_id") or ""),
            trace_id=str(d.get("trace_id") or ""),
            ack_required=ack if isinstance(ack, bool) else True,
            ts=int(d.get("ts") or 0),
            epoch=str(d.get("epoch") or ""),
            floor=floor if isinstance(floor, int) and not isinstance(floor, bool) and floor > 0 else 0,
        )


class Link:
    """一条链路:一个会话里、本端 Agent 与对端 Agent 之间。管「必达」,不管传输。"""

    def __init__(
        self,
        session_id: str,
        local_agent: str,
        peer_agent: str,
        *,
        clock: Callable[[], int] = lambda: int(time.time() * 1000),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self.session_id = session_id
        self.local_agent = local_agent
        self.peer_agent = peer_agent
        self._clock = clock
        self._new_id = new_id
        self.epoch = new_id()
        self._lock = threading.Lock()
        self._next_seq = 1
        self._expected = 1
        self._peer_epoch = ""
        self._outbox: Dict[str, Envelope] = {}
        self._seen: Dict[str, None] = {}  # 有序字典当有界集合用
        self._buffer: Dict[int, Envelope] = {}

    def make(
        self,
        kind: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        task_id: str = "",
        trace_id: str = "",
        ack_required: bool = True,
    ) -> Envelope:
        """造一条发给对端的消息;要确认的留在发件箱里,直到收到它的确认。"""
        kind = kind.value if isinstance(kind, Kind) else str(kind)
        if kind not in KINDS or kind == Kind.ACK.value:
            raise ValueError(f"unknown or reserved A2A kind: {kind}")
        with self._lock:
            env = Envelope(
                msg_id=self._new_id(),
                seq=self._next_seq,
                session_id=self.session_id,
                from_agent=self.local_agent,
                to_agent=self.peer_agent,
                kind=kind,
                body=dict(body or {}),
                task_id=task_id,
                trace_id=trace_id,
                ack_required=ack_required,
                ts=self._clock(),
                epoch=self.epoch,
            )
            self._next_seq += 1
            if ack_required:
                self._outbox[env.msg_id] = env
            env.floor = self._floor(env.seq)
            return env

    def _floor(self, default: int) -> int:
        return min((e.seq for e in self._outbox.values()), default=default)

    def unacked(self) -> List[Envelope]:
        """还没收到确认的消息,按序号排好 —— 重连后照这个顺序补发(带上此刻的 ``floor``)。"""
        with self._lock:
            floor = self._floor(self._next_seq)
            return [replace(e, floor=floor) for e in sorted(self._outbox.values(), key=lambda e: e.seq)]

    def accept(self, env: Envelope) -> Tuple[List[Envelope], Optional[Envelope]]:
        """收下对端的一条消息,返回 ``(按序该交付的消息, 要回给对方的确认或 None)``。"""
        with self._lock:
            if env.kind == Kind.ACK.value:
                self._outbox.pop(str(env.body.get("ack_of") or ""), None)
                return [], None
            ack = self._ack_for(env) if env.ack_required else None
            if env.msg_id in self._seen:
                return [], ack  # 重复:不交付,但照样确认
            self._seen[env.msg_id] = None
            while len(self._seen) > MAX_SEEN:
                self._seen.pop(next(iter(self._seen)))
            if env.seq <= 0:
                return [env], ack
            out: List[Envelope] = []
            if env.epoch and env.epoch != self._peer_epoch:
                # 对端换了一次身份(它重启了),或者我们自己是新的、还不认识它:从它说的 floor 重新数。
                # 上一次身份留下、缓着等缺口的已经确认过,缺口再也不会来了 —— 按序交出,不丢。
                self._peer_epoch = env.epoch
                out.extend(self._buffer.pop(s) for s in sorted(self._buffer))
                self._expected = env.floor or 1
            elif env.floor > self._expected:
                # 比 floor 小的对端都已了结:缓着的按序交出,缺口(丢了、又不要确认的)不再等
                for s in sorted(k for k in self._buffer if k < env.floor):
                    out.append(self._buffer.pop(s))
                self._expected = env.floor
            if env.seq < self._expected:
                return out, ack
            self._buffer[env.seq] = env
            while self._expected in self._buffer:
                out.append(self._buffer.pop(self._expected))
                self._expected += 1
            if len(self._buffer) > MAX_BUFFERED:
                # 缺口一直补不上(对端发件箱也丢了):别把整条链路卡死,按序交出缓着的,跳过缺口。
                for s in sorted(self._buffer):
                    out.append(self._buffer.pop(s))
                    self._expected = s + 1
            return out, ack

    def _ack_for(self, env: Envelope) -> Envelope:
        return Envelope(
            msg_id=self._new_id(),
            seq=0,
            session_id=self.session_id,
            from_agent=self.local_agent,
            to_agent=env.from_agent,
            kind=Kind.ACK.value,
            body={"ack_of": env.msg_id},
            task_id=env.task_id,
            trace_id=env.trace_id,
            ack_required=False,
            ts=self._clock(),
            epoch=self.epoch,
        )

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "session_id": self.session_id,
                "epoch": self.epoch,
                "local_agent": self.local_agent,
                "peer_agent": self.peer_agent,
                "next_seq": self._next_seq,
                "expected_seq": self._expected,
                "unacked": len(self._outbox),
                "buffered": len(self._buffer),
            }


# ── 中心这一端:每台设备一条链路,经 UCM 收发 ─────────────────────────────────────

Handler = Callable[[str, Envelope], Awaitable[None]]
_handlers: Dict[str, Handler] = {}
_links: Dict[Tuple[str, str], Link] = {}
_links_lock = threading.Lock()


def register_handler(kind: str, handler: Handler) -> None:
    """登记某类消息到了之后做什么(``handler(device_id, envelope)``)。同一类后登记的覆盖先登记的。"""
    _handlers[kind.value if isinstance(kind, Kind) else str(kind)] = handler


def link_for(device_id: str, session_id: str = "") -> Link:
    """中心与某台设备上那个 Agent 之间的链路(一个会话一条)。"""
    key = (device_id, session_id or device_id)
    with _links_lock:
        link = _links.get(key)
        if link is None:
            link = _links[key] = Link(key[1], CENTER_AGENT, agent_id_for(device_id))
        return link


def links_of(device_id: str) -> List[Link]:
    with _links_lock:
        return [l for (did, _), l in _links.items() if did == device_id]


def reset_links() -> None:
    """测试用。"""
    with _links_lock:
        _links.clear()


async def _send_frame(device_id: str, env: Envelope) -> bool:
    from core.unified.connection_manager import get_unified_connection_manager

    return bool(await get_unified_connection_manager().send_to_device(device_id, env.to_aip_frame(device_id)))


async def send(
    device_id: str,
    kind: str,
    body: Optional[Dict[str, Any]] = None,
    *,
    session_id: str = "",
    task_id: str = "",
    trace_id: str = "",
    ack_required: bool = True,
) -> Tuple[Envelope, bool]:
    """给某台设备上的 Agent 发一条 A2A 消息,返回 ``(信封, 这次送出去没有)``。

    没送出去(设备此刻没连着)也不丢:要确认的消息留在发件箱里,设备重连时 :func:`resend_unacked` 补发。
    """
    env = link_for(device_id, session_id).make(
        kind, body, task_id=task_id, trace_id=trace_id, ack_required=ack_required
    )
    try:
        sent = await _send_frame(device_id, env)
    except Exception as exc:  # noqa: BLE001 — 没送出去不是错,留着等补发
        logger.debug("a2a send to %s deferred: %s", device_id, exc)
        sent = False
    return env, sent


async def resend_unacked(device_id: str) -> int:
    """设备重连后,把发给它、还没确认的消息按序补发。返回补发了几条。"""
    count = 0
    for link in links_of(device_id):
        for env in link.unacked():
            try:
                if await _send_frame(device_id, env):
                    count += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("a2a resend to %s failed: %s", device_id, exc)
                return count
    return count


async def receive(device_id: str, frame: Dict[str, Any]) -> Dict[str, Any]:
    """设备发来一条 ``type="a2a"`` 帧:去重、排序、回确认、按类交给登记的处理器。

    返回给入口的结果(``accepted`` / ``delivered`` / ``reason``),入口不必再回别的。

    处理器在这台设备的收消息循环里按序被等待 —— 要做久的事(跑一轮对话、等委派结果)自己起后台任务,
    否则这台设备后面的帧(包括确认)都得等它。
    """
    env = Envelope.from_dict(frame.get("payload") if isinstance(frame, dict) else None)
    if env is None:
        return {"accepted": False, "reason": "malformed_a2a_envelope"}
    expected_from = agent_id_for(device_id)
    if env.from_agent != expected_from:
        # 一台设备只能以它自己那个 Agent 的身份说话 —— 否则一台已配对的设备能冒充别的设备的 Agent
        logger.warning("a2a: %s sent as %r (expected %r), dropped", device_id, env.from_agent, expected_from)
        return {"accepted": False, "reason": "from_agent_mismatch"}
    link = link_for(device_id, env.session_id)
    deliver, ack = link.accept(env)
    if ack is not None:
        try:
            await _send_frame(device_id, ack)
        except Exception as exc:  # noqa: BLE001 — 确认丢了对方会补发,我们会去重
            logger.debug("a2a ack to %s failed: %s", device_id, exc)
    for item in deliver:
        handler = _handlers.get(item.kind)
        if handler is None:
            logger.info("a2a: no handler for %s from %s (delivered, ignored)", item.kind, device_id)
            continue
        try:
            await handler(device_id, item)
        except Exception as exc:  # noqa: BLE001 — 一条处理失败不该卡住后面的
            logger.warning("a2a handler %s failed for %s: %s", item.kind, device_id, exc, exc_info=True)
    return {"accepted": True, "delivered": [e.msg_id for e in deliver]}
