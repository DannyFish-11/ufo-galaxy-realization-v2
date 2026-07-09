"""
Lumiv Presence Bridge — 桌面覆盖层事件推送

职责：
1. 订阅 DesktopPresenceRuntime 的状态事件
2. 将 DesktopPresenceMode (STATIC/LIMINAL/MANIFEST) 映射为 depth_factor
3. 优先通过 IPC HTTP POST 推送到 Electron main.js (localhost:9229)
4. Fallback 到 WebSocket 广播（浏览器预览模式）

这是 DesktopPresenceRuntime 与 Electron 外壳之间的唯一桥梁。
前端不做任何状态机，只接收事件并渲染。
"""

import asyncio
import logging
import os
from typing import Optional, Dict, Any, Set

try:
    from fastapi import WebSocket, WebSocketDisconnect
except ImportError:
    WebSocket = Any
    WebSocketDisconnect = Exception

try:
    import aiohttp
except ImportError:
    aiohttp = None  # type: ignore

logger = logging.getLogger("Lumiv.PresenceBridge")

# PR-IPC: Electron HTTP 接收端端口（从环境变量读取，兼容用户自定义端口）
_ELECTRON_PORT = int(os.environ.get("GALAXY_ELECTRON_PORT",
                                   os.environ.get("GATEWAY_PORT", "9229")))
_ELECTRON_IPC_URL = f"http://127.0.0.1:{_ELECTRON_PORT}/ipc/presence-state"


# ── DesktopPresenceMode → depth_factor 映射 ──
# STATIC(休息)    → 0.00-0.05  (Silent 呼吸光环)
# LIMINAL(认知)   → 0.15-0.85  (Liminal 透视空间展开)
# MANIFEST(执行)  → 0.90-0.95  (Manifest 透明)
MODE_DEPTH_MAP = {
    "static":   0.05,
    "liminal":  0.50,
    "manifest": 0.92,
}


class GalaxyPresenceBridge:
    """
    单例。订阅 DesktopPresenceRuntime 的 StateEventBus，
    将 presence 模式转换为 depth_factor 推送到前端。

    推送策略（PR-IPC）：
    1. 优先 HTTP POST 到 Electron main.js: http://localhost:9229/ipc/presence-state
    2. Electron 不可用时 fallback 到 WebSocket 广播（浏览器预览模式）
    """

    _instance: Optional["GalaxyPresenceBridge"] = None

    # 已连接的 WebSocket 客户端（fallback 模式）
    _clients: Set[WebSocket] = set()
    _lock = asyncio.Lock()

    # 当前状态
    _current_mode: str = "static"
    _current_depth: float = 0.0
    _intent: float = 0.0
    _speaking: bool = False

    # 自发注意力（ambient）最近一拍：供面板在场栏显示"它正在看什么/刚才为何开口"。
    _ambient_seeing: bool = False
    _ambient_hearing: bool = False
    _ambient_action: str = ""       # speak | silent | delegate
    _ambient_rationale: str = ""
    _ambient_ts: float = 0.0

    # 桥接已启动
    _started: bool = False

    @classmethod
    def get_instance(cls) -> "GalaxyPresenceBridge":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── 启动 / 停止 ──

    async def start(self) -> None:
        """启动桥接：订阅 StateEventBus。"""
        if self._started:
            return
        self._started = True

        try:
            # 修复:此前用 StateEventBus.get_instance() —— 该类【没有】这个
            # classmethod（单例入口是模块级 get_state_event_bus()）。于是 start()
            # 每次都在这里抛 AttributeError 被下面 except 吞掉，桥【从未真正订阅
            # 到任何事件】：连三态相位订阅都是死的（面板相位靠另一条 IPC feed
            # 才没露馅）。改用正确的模块级单例入口，让订阅真正生效。
            from core.state_event_bus import get_state_event_bus
            bus = get_state_event_bus()

            # 订阅三态转换事件
            bus.subscribe("phase.silent",   self._on_phase_silent)
            bus.subscribe("phase.liminal",  self._on_phase_liminal)
            bus.subscribe("phase.manifest", self._on_phase_manifest)

            # 订阅 intent 强度更新
            bus.subscribe("intent.update",  self._on_intent_update)

            # 订阅自发注意力事件 → 面板在场栏实时显示"在看/在听 + 决策理由"。
            bus.subscribe("ambient.observed", self._on_ambient_observed)
            bus.subscribe("ambient.decision", self._on_ambient_decision)

            logger.info("GalaxyPresenceBridge started — subscribed to StateEventBus (IPC HTTP + WS fallback)")
        except Exception as exc:
            logger.warning("StateEventBus subscription failed (non-fatal): %s", exc)

    # ── StateEventBus 回调 ──

    def _on_phase_silent(self, payload: Dict[str, Any]) -> None:
        self._current_mode = "static"
        self._current_depth = MODE_DEPTH_MAP["static"]
        self._intent = 0.0
        self._speaking = False
        asyncio.create_task(self._broadcast_state())

    def _on_phase_liminal(self, event: Any) -> None:
        p = self._payload_of(event)
        self._current_mode = "liminal"
        self._current_depth = MODE_DEPTH_MAP["liminal"]
        # intent 从 payload 中提取，如果没有则默认 0.5
        self._intent = p.get("intent_strength", 0.5)
        self._speaking = p.get("speaking", False)
        asyncio.create_task(self._broadcast_state())

    def _on_phase_manifest(self, payload: Dict[str, Any]) -> None:
        self._current_mode = "manifest"
        self._current_depth = MODE_DEPTH_MAP["manifest"]
        self._intent = 1.0
        self._speaking = False
        asyncio.create_task(self._broadcast_state())

    def _on_intent_update(self, event: Any) -> None:
        """意图强度持续更新 — Liminal 态下微调 depth。"""
        if self._current_mode != "liminal":
            return
        p = self._payload_of(event)
        intent = p.get("intent_strength", 0.5)
        self._intent = intent
        # depth 在 0.15-0.85 之间随 intent 线性映射
        self._current_depth = 0.15 + intent * 0.70
        self._speaking = p.get("speaking", False)
        asyncio.create_task(self._broadcast_state())

    @staticmethod
    def _payload_of(event: Any) -> Dict[str, Any]:
        """StateEventBus 回调收到的是 StateEvent 对象；取其 .payload（兼容裸 dict）。"""
        p = getattr(event, "payload", None)
        if isinstance(p, dict):
            return p
        return event if isinstance(event, dict) else {}

    def _on_ambient_observed(self, event: Any) -> None:
        """自发注意力：门控放行、正在观察一帧（看/听）。"""
        import time as _t
        p = self._payload_of(event)
        self._ambient_seeing = bool(p.get("has_frame"))
        self._ambient_hearing = bool(p.get("has_audio"))
        self._ambient_ts = _t.time()
        asyncio.create_task(self._broadcast_state())

    def _on_ambient_decision(self, event: Any) -> None:
        """自发注意力：三选一决策（speak/silent/delegate）+ 理由。"""
        import time as _t
        p = self._payload_of(event)
        self._ambient_action = str(p.get("action", ""))
        self._ambient_rationale = str(p.get("rationale") or p.get("utterance") or p.get("task") or "")
        self._ambient_ts = _t.time()
        asyncio.create_task(self._broadcast_state())

    # ── WebSocket 客户端管理 ──

    async def register_client(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.add(websocket)
        logger.info("Desktop presence client registered | total=%d", len(self._clients))
        # 立即推送当前状态
        await self._send_to(websocket)

    async def unregister_client(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)
        logger.info("Desktop presence client unregistered | total=%d", len(self._clients))

    # ── 广播 ──

    async def _broadcast_state(self) -> None:
        """广播状态到前端。优先 IPC HTTP，fallback WebSocket。"""
        msg = self._build_message()

        # PR-IPC: 优先推送到 Electron main.js HTTP 接收端
        if await self._try_ipc_http(msg):
            return

        # Fallback: 传统 WebSocket 广播（浏览器预览模式）
        await self._ws_broadcast(msg)

    async def _try_ipc_http(self, msg: Dict[str, Any]) -> bool:
        """尝试 HTTP POST 到 Electron。返回是否成功。"""
        if aiohttp is None:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _ELECTRON_IPC_URL,
                    json=msg,
                    timeout=aiohttp.ClientTimeout(total=1),
                ) as resp:
                    return resp.status == 200
        except Exception:
            return False

    async def _ws_broadcast(self, msg: Dict[str, Any]) -> None:
        """WebSocket fallback 广播。"""
        dead: list = []
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    async def _send_to(self, websocket: WebSocket) -> None:
        """向单个客户端发送当前状态。"""
        try:
            await websocket.send_json(self._build_message())
        except Exception as exc:
            logger.debug("Send to single client failed: %s", exc)

    def _build_message(self) -> Dict[str, Any]:
        """构建与前端兼容的 state_event 消息。"""
        return {
            "type": "state_event",
            "event_category": "ambient_tick",
            "payload": {
                "phase": self._current_mode,
                "depth_factor": round(self._current_depth, 4),
                "intent": round(self._intent, 4),
                "speaking": self._speaking,
                "mode": self._current_mode,
                "source": "DesktopPresenceRuntime",
                # 自发注意力最近一拍（面板在场栏展示"在看/在听 + 决策"）。
                "ambient": {
                    "seeing": self._ambient_seeing,
                    "hearing": self._ambient_hearing,
                    "action": self._ambient_action,
                    "rationale": self._ambient_rationale[:120],
                    "ts": round(self._ambient_ts, 3),
                },
            },
        }


    async def _broadcast_conversation(self, msg: Dict[str, Any]) -> None:
        """对话消息只走 WebSocket（useConversation 的通道）。

        刻意【不】走 IPC /ipc/presence-state —— 那条路被 main.js 当作
        presence-state 转给 usePanelData，若把 {type:"conversation"} 塞进去会污染
        面板在场状态（每来一句就把其它字段重置/闪烁）。对话与在场共用同一条
        /ws/desktop-presence，但用不同 type 区分，由前端各自的 hook 分流。
        """
        await self._ws_broadcast(msg)


# ---------------------------------------------------------------------------
# 模块级便捷函数
# ---------------------------------------------------------------------------
# 修复:此前 speech_output / voice_loop / routes.chat
# 四处都 `from core.lumiv_websocket_bridge import set_ai_speaking / emit_conversation`,
# 但本模块【从未定义过这两个函数】——每处 import 都抛 ImportError 被 try/except
# 静默吞掉,于是:①"AI 正在说话"同步到三态覆盖层的信号一直是死的;②语音/文字
# 对话推送到面板"实时上下文"一直是死的(PresencePanel 的 turns 永远空)。这两个
# 用户可见功能名义上接了、实际从没生效。这里补齐定义。

def _schedule(coro) -> None:
    """在当前事件循环里调度协程；无运行循环时同步兜底跑一次。"""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        try:
            asyncio.run(coro)
        except Exception:  # noqa: BLE001
            pass


def get_current_phase() -> str:
    """返回 GalaxyPresenceBridge 的真实实时相位，规范化为 silent/liminal/manifest。

    core/routes/panel.py 用它覆盖 build_unified_panel_payload() 那个恒为 "silent"
    的死值（走的是从未赋值的 _continuum_state → 模块路径写错的 cognitive_field_engine
    兜底）。此前此函数缺失 → import 失败 → 覆盖不生效 → WS 断线重连期间面板相位
    被错误拉回"待机"。内部态 "static" 对外即三态的 SILENT。
    """
    try:
        mode = GalaxyPresenceBridge.get_instance()._current_mode
    except Exception:  # noqa: BLE001
        return "silent"
    return {"static": "silent", "silent": "silent",
            "liminal": "liminal", "manifest": "manifest"}.get(mode, "silent")


def set_ai_speaking(speaking: bool) -> None:
    """标记 AI 是否正在朗读，并广播到三态覆盖层（说话时动画随之运转）。

    非阻塞、降级安全。集中式 TTS(core.speech_output)在播放起止各调一次。
    """
    try:
        bridge = GalaxyPresenceBridge.get_instance()
        bridge._speaking = bool(speaking)
        _schedule(bridge._broadcast_state())
    except Exception as exc:  # noqa: BLE001
        logger.debug("set_ai_speaking 跳过(非致命): %s", exc)


def emit_conversation(
    role: str,
    text: str,
    *,
    source: str = "text",
    speaking: bool = False,
    turn_id: str = "",
    final: bool = True,
) -> None:
    """把一轮对话（"听到的"/"AI 说的"）实时推给面板的"实时上下文"视图。

    与前端 useConversation 的契约对齐：type="conversation"，payload 含
    role/text/source/speaking/turn_id/final。非阻塞、降级安全、永不抛出。
    """
    try:
        if not (text or "").strip():
            return
        bridge = GalaxyPresenceBridge.get_instance()
        if speaking:
            bridge._speaking = True
        msg = {
            "type": "conversation",
            "payload": {
                "role": "ai" if role == "ai" else "user",
                "text": text,
                "source": source or "text",
                "speaking": bool(speaking),
                "turn_id": str(turn_id or ""),
                "final": bool(final),
            },
        }
        _schedule(bridge._broadcast_conversation(msg))
    except Exception as exc:  # noqa: BLE001
        logger.debug("emit_conversation 跳过(非致命): %s", exc)


# 兼容旧类名
LumivWebSocketBridge = GalaxyPresenceBridge
