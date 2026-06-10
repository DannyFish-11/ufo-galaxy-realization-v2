"""
Lumiv WebSocket Bridge — 桌面覆盖层事件推送

职责：
1. 订阅 DesktopPresenceRuntime 的状态事件
2. 将 DesktopPresenceMode (STATIC/LIMINAL/MANIFEST) 映射为 depth_factor
3. 通过 WebSocket 推送到前端 Electron 渲染器

这是 DesktopPresenceRuntime 与 Electron 外壳之间的唯一桥梁。
前端不做任何状态机，只接收事件并渲染。
"""

import asyncio
import logging
from typing import Optional, Dict, Any, Set

try:
    from fastapi import WebSocket, WebSocketDisconnect
except ImportError:
    WebSocket = Any
    WebSocketDisconnect = Exception

logger = logging.getLogger("Lumiv.WebSocketBridge")


# ── DesktopPresenceMode → depth_factor 映射 ──
# STATIC(休息)    → 0.00-0.05  (Silent 呼吸光环)
# LIMINAL(认知)   → 0.15-0.85  (Liminal 透视空间展开)
# MANIFEST(执行)  → 0.90-0.95  (Manifest 透明)
MODE_DEPTH_MAP = {
    "static":   0.05,
    "liminal":  0.50,
    "manifest": 0.92,
}


class LumivWebSocketBridge:
    """
    单例。订阅 DesktopPresenceRuntime 的 StateEventBus，
    将 presence 模式转换为 depth_factor 推送到前端。
    """

    _instance: Optional["LumivWebSocketBridge"] = None

    # 已连接的 WebSocket 客户端
    _clients: Set[WebSocket] = set()
    _lock = asyncio.Lock()

    # 当前状态
    _current_mode: str = "static"
    _current_depth: float = 0.0
    _intent: float = 0.0
    _speaking: bool = False

    # 桥接已启动
    _started: bool = False

    @classmethod
    def get_instance(cls) -> "LumivWebSocketBridge":
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
            from core.state_event_bus import StateEventBus
            bus = StateEventBus.get_instance()

            # 订阅三态转换事件
            bus.subscribe("phase.silent",   self._on_phase_silent)
            bus.subscribe("phase.liminal",  self._on_phase_liminal)
            bus.subscribe("phase.manifest", self._on_phase_manifest)

            # 订阅 intent 强度更新
            bus.subscribe("intent.update",  self._on_intent_update)

            logger.info("LumivWebSocketBridge started — subscribed to StateEventBus")
        except Exception as exc:
            logger.warning("StateEventBus subscription failed (non-fatal): %s", exc)

    # ── StateEventBus 回调 ──

    def _on_phase_silent(self, payload: Dict[str, Any]) -> None:
        self._current_mode = "static"
        self._current_depth = MODE_DEPTH_MAP["static"]
        self._intent = 0.0
        self._speaking = False
        asyncio.create_task(self._broadcast_state())

    def _on_phase_liminal(self, payload: Dict[str, Any]) -> None:
        self._current_mode = "liminal"
        self._current_depth = MODE_DEPTH_MAP["liminal"]
        # intent 从 payload 中提取，如果没有则默认 0.5
        self._intent = payload.get("intent_strength", 0.5)
        self._speaking = payload.get("speaking", False)
        asyncio.create_task(self._broadcast_state())

    def _on_phase_manifest(self, payload: Dict[str, Any]) -> None:
        self._current_mode = "manifest"
        self._current_depth = MODE_DEPTH_MAP["manifest"]
        self._intent = 1.0
        self._speaking = False
        asyncio.create_task(self._broadcast_state())

    def _on_intent_update(self, payload: Dict[str, Any]) -> None:
        """意图强度持续更新 — Liminal 态下微调 depth。"""
        if self._current_mode != "liminal":
            return
        intent = payload.get("intent_strength", 0.5)
        self._intent = intent
        # depth 在 0.15-0.85 之间随 intent 线性映射
        self._current_depth = 0.15 + intent * 0.70
        self._speaking = payload.get("speaking", False)
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
        """向所有已连接客户端广播当前状态。"""
        msg = self._build_message()
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
            },
        }
