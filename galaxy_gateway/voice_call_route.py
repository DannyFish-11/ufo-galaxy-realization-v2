"""galaxy_gateway/voice_call_route.py —— 设备实时语音通话的网关侧接线。

职责边界
--------
本模块只做**信令与生命周期**:接住设备发来的六条语音消息,建/拆 ``RTCPeerConnection``,
把媒体轨交给 :mod:`core.voice_call_bridge`,并把会话事件回推给设备。

音频本身一秒都不经过这里 —— 它在 WebRTC 的媒体通道里走。这条分工不是洁癖:AIP
WebSocket 建在 TCP 上,丢一个包后面全被堵住,而重传回来的是过期音频;实时语音里迟到
的音频没有价值,只会把延迟越堆越高。

为什么 PeerConnection 建在网关进程里
------------------------------------
``Node_95_WebRTC_Receiver`` 已经有一套 WebRTC 接收,但它是**摄像头帧**取向的:只处理
``track.kind == "video"``,而且没有 ``addTrack`` —— 它只收不发,而通话必须双向。更要紧
的是 ``DuplexSession`` 活在网关进程里,把媒体终结在另一个进程等于给每一帧音频加一次
跨进程搬运。所以语音通话自建 PeerConnection,与 Node_95 各管各的。

诚实边界
--------
* ``aiortc`` 是可选依赖。没装时通话请求被**如实拒绝**并说明原因,绝不静默假装接通。
* 真 provider(OpenAI Realtime / Gemini Live)需要 key 与出网,本仓测试环境都没有。
  可验证的是信令状态机与轨道接线;provider 那一端由 ``voice_duplex_session`` 自己的
  测试覆盖。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Set

logger = logging.getLogger("Galaxy.VoiceCallRoute")

#: 本模块认领的消息类型(wire 值)。放成集合而不是散在 if/elif 里,是为了让
#: "网关到底接了哪几条" 这个问题有一个能被测试直接读的答案。
VOICE_CALL_TYPES: Set[str] = {
    "voice_call_start",
    "voice_call_accepted",
    "voice_call_end",
    "voice_ice",
    "voice_event",
    "voice_interrupt",
}

#: 设备只应该发这几条。``voice_call_accepted`` / ``voice_event`` 是网关下行的,
#: 设备发上来说明客户端搞反了方向 —— 如实拒绝而不是默默处理。
DEVICE_ORIGINATED: Set[str] = {
    "voice_call_start",
    "voice_call_end",
    "voice_ice",
    "voice_interrupt",
}


def is_voice_call_message(msg_type: Any) -> bool:
    """这条消息归本模块管吗。接受枚举或裸字符串。"""
    value = getattr(msg_type, "value", msg_type)
    return isinstance(value, str) and value in VOICE_CALL_TYPES


def voice_calls_enabled() -> bool:
    """总开关。默认**开**:协议、桥、测试都齐了才接线,没有理由再藏一道门。

    留这个开关是为了让运维在 provider 出问题时能一键停掉通话而不必回滚版本。
    """
    return os.getenv("GALAXY_VOICE_CALL", "1").strip().lower() not in ("0", "false", "no", "off")


class VoiceCallRoute:
    """一条设备连接上的通话信令端点。

    每个 WebSocket 连接一个实例:通话是连接级的资源,连接没了通话也必须跟着结束。
    """

    def __init__(self, device_id: str, send_json: Any) -> None:
        self.device_id = device_id
        self._send = send_json
        self._pc: Any = None
        self._call: Any = None

    # ── 下行 ────────────────────────────────────────────────────────────

    async def _reply(self, payload: Dict[str, Any]) -> None:
        try:
            result = self._send(payload)
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:  # noqa: BLE001
            logger.debug("device=%s 回包失败(连接可能已断): %s", self.device_id, exc)

    async def _reject(self, reason: str, call_id: str = "") -> None:
        """拒绝一次通话请求,并**说清原因**。

        只回一个 voice_call_end 而不带原因,设备侧只能显示"通话失败" —— 那正是最难
        排查的一类症状:没装 aiortc、没配 key、SDP 谈崩,处置完全不同。
        """
        logger.info("device=%s 通话被拒: %s", self.device_id, reason)
        await self._reply(
            {
                "type": "voice_call_end",
                "device_id": self.device_id,
                "call_id": call_id,
                "reason": reason,
            }
        )

    # ── 入口 ────────────────────────────────────────────────────────────

    async def handle(self, msg_type: str, payload: Dict[str, Any]) -> None:
        value = getattr(msg_type, "value", msg_type)
        if value not in DEVICE_ORIGINATED:
            logger.warning("device=%s 发来了本该是下行的消息 %s,忽略", self.device_id, value)
            return
        if value == "voice_call_start":
            await self._start(payload)
        elif value == "voice_ice":
            await self._ice(payload)
        elif value == "voice_interrupt":
            await self._interrupt(payload)
        elif value == "voice_call_end":
            await self.hangup(payload.get("reason", "user_hangup"))

    # ── 建立 ────────────────────────────────────────────────────────────

    async def _start(self, payload: Dict[str, Any]) -> None:
        if not voice_calls_enabled():
            await self._reject("语音通话已被运维关闭(GALAXY_VOICE_CALL=0)")
            return

        from core.voice_call_bridge import VoiceCall, get_call_registry, webrtc_available

        unavailable = webrtc_available()
        if unavailable:
            await self._reject(unavailable)
            return

        sdp = (payload.get("sdp") or "").strip()
        if not sdp:
            await self._reject("voice_call_start 缺少 SDP offer")
            return

        session = await self._open_session()
        if session is None:
            await self._reject("没有可用的实时语音后端(未配置 provider key,或建连失败)")
            return

        from aiortc import RTCPeerConnection, RTCSessionDescription

        pc = RTCPeerConnection()
        call = VoiceCall(self.device_id, session, send_event=self._on_session_event)
        self._pc, self._call = pc, call

        @pc.on("track")
        def _on_track(track: Any) -> None:
            if track.kind == "audio":
                logger.info("device=%s 收到上行音频轨", self.device_id)
                call.attach_uplink(track)

        @pc.on("connectionstatechange")
        async def _on_state() -> None:
            # 链路断了必须收尾:否则 provider 那头挂着一条会话继续计费,而且没有
            # 任何报错提示 —— 手表进隧道、Wi-Fi 切换都会走到这里。
            if pc.connectionState in ("failed", "closed", "disconnected"):
                logger.info("device=%s WebRTC 链路 %s,收尾", self.device_id, pc.connectionState)
                await self.hangup(reason=f"webrtc_{pc.connectionState}")

        pc.addTrack(call.downlink_track)

        try:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=sdp, type="offer"))
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
        except Exception as exc:  # noqa: BLE001
            logger.warning("device=%s SDP 协商失败: %s", self.device_id, exc)
            await self.hangup(reason="sdp_negotiation_failed")
            await self._reject(f"SDP 协商失败: {exc}")
            return

        await get_call_registry().put(call)
        call.start_downlink()

        await self._reply(
            {
                "type": "voice_call_accepted",
                "device_id": self.device_id,
                "call_id": call.call_id,
                "sdp": pc.localDescription.sdp,
                "sdp_type": "answer",
                "provider": getattr(getattr(session, "config", None), "provider", ""),
            }
        )
        logger.info("device=%s 通话已接通 call=%s", self.device_id, call.call_id)

    async def _open_session(self) -> Optional[Any]:
        """开一条 provider 双工会话。不可用返回 None(原因已由该模块记日志)。"""
        try:
            from core.voice_duplex_session import DuplexSessionConfig, open_duplex_session

            cfg = DuplexSessionConfig.from_env()
            if cfg is None:
                return None
            return await open_duplex_session(cfg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("device=%s 打开双工会话失败: %s", self.device_id, exc)
            return None

    # ── 过程 ────────────────────────────────────────────────────────────

    async def _ice(self, payload: Dict[str, Any]) -> None:
        if self._pc is None:
            return
        candidate = (payload.get("candidate") or "").strip()
        if not candidate:
            return  # 空串 = 候选收集结束,无需处理
        try:
            from aiortc import RTCIceCandidate
            from aiortc.sdp import candidate_from_sdp

            cand: RTCIceCandidate = candidate_from_sdp(candidate.replace("candidate:", "", 1))
            cand.sdpMid = payload.get("sdp_mid") or None
            cand.sdpMLineIndex = payload.get("sdp_m_line_index")
            await self._pc.addIceCandidate(cand)
        except Exception as exc:  # noqa: BLE001
            # 单个候选加不进去不该毁掉整通电话:ICE 本来就是多候选择优。
            logger.debug("device=%s ICE candidate 忽略: %s", self.device_id, exc)

    async def _interrupt(self, payload: Dict[str, Any]) -> None:
        if self._call is None:
            return
        await self._call.interrupt(payload.get("reason", "user_speech"))

    async def _on_session_event(self, event: str, text: str, error: str) -> None:
        call_id = getattr(self._call, "call_id", "")
        await self._reply(
            {
                "type": "voice_event",
                "device_id": self.device_id,
                "call_id": call_id,
                "event": event,
                "text": text,
                "error": error,
            }
        )

    # ── 收尾 ────────────────────────────────────────────────────────────

    async def hangup(self, reason: str = "user_hangup") -> None:
        """挂断。幂等、永不抛出 —— 连接清理路径上调用,不能反过来把清理弄崩。"""
        call, pc = self._call, self._pc
        self._call, self._pc = None, None
        if call is not None:
            try:
                from core.voice_call_bridge import get_call_registry

                await get_call_registry().end(self.device_id, reason=reason)
            except Exception as exc:  # noqa: BLE001
                logger.warning("device=%s 注销通话失败: %s", self.device_id, exc)
        if pc is not None:
            try:
                await pc.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("device=%s 关闭 PeerConnection 失败: %s", self.device_id, exc)

    @property
    def in_call(self) -> bool:
        return self._call is not None


# ── 连接级注册表 ────────────────────────────────────────────────────────
#
# 通话是**连接级**资源:WebSocket 没了,PeerConnection 和 provider 会话都必须跟着
# 收掉。把这张表放在本模块而不是 GatewayWSManager 里,是因为 ``disconnect()`` 全程
# 持着自己的锁,而挂断要 await 网络关闭 —— 在锁里 await 出网操作是给自己埋死锁。
# 连接清理路径改为在进锁之前先调 :func:`close_voice_route`。

_ROUTES: Dict[str, VoiceCallRoute] = {}


def get_voice_route(connection_id: str, device_id: str, send_json: Any) -> VoiceCallRoute:
    """取(或建)这条连接的通话端点。"""
    route = _ROUTES.get(connection_id)
    if route is None:
        route = VoiceCallRoute(device_id, send_json)
        _ROUTES[connection_id] = route
    return route


async def close_voice_route(connection_id: str, reason: str = "connection_closed") -> bool:
    """连接结束时收掉它的通话。没有通话时是空操作,返回是否真挂断了一通。"""
    route = _ROUTES.pop(connection_id, None)
    if route is None:
        return False
    had_call = route.in_call
    await route.hangup(reason=reason)
    return had_call


def active_route_count() -> int:
    """当前挂着的连接端点数。给测试和运维视图用。"""
    return len(_ROUTES)


async def maybe_handle_voice_message(
    connection_id: str,
    msg_type: Any,
    payload: Dict[str, Any],
    device_id: str,
    send_json: Any,
) -> bool:
    """通话信令的单一入口。认领了返回 True,调用方直接 return。

    做成一个函数而不是在 ``handle_message`` 里摊开写 if/elif:那边已经是一条一千两百
    行的分派链,本模块的全部理由都写在上面的模块说明里,摊进去只会让两处都更难读。
    """
    if not is_voice_call_message(msg_type):
        return False
    route = get_voice_route(connection_id, device_id, send_json)
    await route.handle(getattr(msg_type, "value", msg_type), payload)
    return True
