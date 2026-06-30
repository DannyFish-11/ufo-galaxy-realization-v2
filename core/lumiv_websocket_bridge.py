"""
Lumiv Presence Bridge — 桌面覆盖层事件推送

职责：
1. 订阅 DesktopPresenceRuntime 的状态事件
2. 将 DesktopPresenceMode (STATIC/LIMINAL/MANIFEST) 映射为 depth_factor
3. 优先通过 IPC HTTP POST 推送到 Electron main.js (默认 localhost:9231, 见 GALAXY_IPC_PORT)
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

# Electron IPC 接收端口。必须与 electron/main.js 的 GALAXY_IPC_PORT 保持一致。
# 默认 9231（避开 Node/V8 inspector 默认端口 9229，否则会与调试器/第二实例冲突）。
IPC_PORT = int(os.getenv("GALAXY_IPC_PORT", "9231"))
IPC_PRESENCE_URL = f"http://localhost:{IPC_PORT}/ipc/presence-state"


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
    1. 优先 HTTP POST 到 Electron main.js: http://localhost:${GALAXY_IPC_PORT:-9231}/ipc/presence-state
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

    # 桥接已启动
    _started: bool = False

    # 主事件循环引用 —— 在 start() 中捕获。
    # StateEventBus 的相位回调是**同步**的、且 desktop_presence_runtime.advance()
    # 也是同步方法；若它从无运行 loop 的线程/同步上下文触发，直接 asyncio.create_task
    # 会抛 RuntimeError，并被 StateEventBus.publish 的 try/except 静默吞掉 —— 唤醒
    # 推送从此无声失效。捕获 loop 后用 _schedule() 做跨线程安全调度即可根治。
    _loop: Optional["asyncio.AbstractEventLoop"] = None

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

        # 捕获主事件循环，供同步/跨线程回调安全调度 _broadcast_state。
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        try:
            from core.state_event_bus import get_state_event_bus
            bus = get_state_event_bus()

            # 订阅三态转换事件
            bus.subscribe("phase.silent",   self._on_phase_silent)
            bus.subscribe("phase.liminal",  self._on_phase_liminal)
            bus.subscribe("phase.manifest", self._on_phase_manifest)

            # 订阅 intent 强度更新
            bus.subscribe("intent.update",  self._on_intent_update)

            logger.info("GalaxyPresenceBridge started — subscribed to StateEventBus (IPC HTTP + WS fallback)")
        except Exception as exc:
            logger.warning("StateEventBus subscription failed (non-fatal): %s", exc)

    # ── 安全调度 ──

    def _schedule_broadcast(self) -> None:
        """跨线程/同步上下文安全调度 _broadcast_state()。

        - 当前线程有运行 loop → 直接 create_task。
        - 无运行 loop 但已捕获主 loop → run_coroutine_threadsafe 投递到主 loop。
        - 都没有 → 记 debug 并放弃（不产生 "coroutine never awaited" 泄漏）。
        永不抛出，避免被 StateEventBus.publish 的 try/except 静默吞掉。
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._broadcast_state())
            return
        except RuntimeError:
            pass  # 本线程无运行 loop —— 尝试投递到主 loop
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(self._broadcast_state(), loop)
                return
            except Exception as exc:  # noqa: BLE001
                logger.debug("run_coroutine_threadsafe failed: %s", exc)
        logger.debug("presence broadcast skipped — no usable event loop")

    # ── StateEventBus 回调 ──

    def _on_phase_silent(self, event) -> None:
        self._current_mode = "static"
        self._current_depth = MODE_DEPTH_MAP["static"]
        self._intent = 0.0
        self._speaking = False
        self._schedule_broadcast()

    def _on_phase_liminal(self, event) -> None:
        self._current_mode = "liminal"
        self._current_depth = MODE_DEPTH_MAP["liminal"]
        # StateEventBus delivers a StateEvent object; extract the inner payload dict.
        p: Dict[str, Any] = event.payload if hasattr(event, "payload") else (event if isinstance(event, dict) else {})
        self._intent = p.get("intent_strength", 0.5)
        self._speaking = p.get("speaking", False)
        self._schedule_broadcast()

    def _on_phase_manifest(self, event) -> None:
        self._current_mode = "manifest"
        self._current_depth = MODE_DEPTH_MAP["manifest"]
        self._intent = 1.0
        self._speaking = False
        self._schedule_broadcast()

    def _on_intent_update(self, event) -> None:
        """意图强度持续更新 — Liminal 态下微调 depth。"""
        if self._current_mode != "liminal":
            return
        p: Dict[str, Any] = event.payload if hasattr(event, "payload") else (event if isinstance(event, dict) else {})
        intent = p.get("intent_strength", 0.5)
        self._intent = intent
        # depth 在 0.15-0.85 之间随 intent 线性映射
        self._current_depth = 0.15 + intent * 0.70
        self._speaking = p.get("speaking", False)
        self._schedule_broadcast()

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
        """广播状态到前端。

        同时推送两条通道，而非二选一：
        - IPC HTTP → Electron 主进程 → 三态全屏覆盖层（主窗口经 IPC 接收）。
        - WebSocket → 已注册客户端（控制面板经 /ws/desktop-presence，以及浏览器预览）。

        二者面向不同的消费者：主覆盖层只听 IPC，控制面板只听 WebSocket。
        早期实现里 IPC 成功就 return，导致面板永远收不到状态更新。
        """
        msg = self._build_message()

        # 桌面主覆盖层（Electron 主进程内存级 IPC 转发）
        await self._try_ipc_http(msg)

        # 控制面板 / 浏览器预览（WebSocket 广播）
        await self._ws_broadcast(msg)

    async def _try_ipc_http(self, msg: Dict[str, Any]) -> bool:
        """尝试 HTTP POST 到 Electron。返回是否成功。"""
        if aiohttp is None:
            return False
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    IPC_PRESENCE_URL,
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
            },
        }


# 兼容旧类名
LumivWebSocketBridge = GalaxyPresenceBridge
