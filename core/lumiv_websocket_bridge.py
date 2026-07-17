"""
Lumiv Presence Bridge — 桌面覆盖层事件推送

职责：
1. 订阅 DesktopPresenceRuntime 的状态事件
2. 将 DesktopPresenceMode (STATIC/LIMINAL/MANIFEST) 映射为 depth_factor
3. 优先通过 IPC HTTP POST 推送到 Electron main.js (localhost:9231，与 GALAXY_IPC_PORT 同源)
4. Fallback 到 WebSocket 广播（浏览器预览模式）

这是 DesktopPresenceRuntime 与 Electron 外壳之间的唯一桥梁。
前端不做任何状态机，只接收事件并渲染。
"""

import asyncio
import logging
import os
from typing import Any, Dict, Optional, Set

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

# PR-IPC: Electron HTTP 接收端端口。【必须与 Electron 侧同源】——electron/main.js 读
# GALAXY_IPC_PORT(默认 9231)。此前本侧默认 9229 与之【错配】:overlay 只走 IPC、无 WS 兜底,
# 收不到任何后端状态 → 冻在硬编码 SILENT 默认(所有者反馈"第二态说话动画换不起来"的真凶)。
# 故这里【同读 GALAXY_IPC_PORT、同默认 9231】;保留 GALAXY_ELECTRON_PORT 作显式覆盖以兼容。
# 端口契约:overlay(electron/main.js)与本桥【唯一真源】都是 GALAXY_IPC_PORT,默认 9231。
ELECTRON_IPC_PORT_DEFAULT = 9231


def resolve_electron_ipc_port(environ: Optional[Dict[str, str]] = None) -> int:
    """解析 Electron IPC 接收端口,须与 electron/main.js 的 GALAXY_IPC_PORT 同源。

    优先级:GALAXY_ELECTRON_PORT(旧显式覆盖)→ GALAXY_IPC_PORT(规范,与 Electron 同名)
    → 9231(与 electron/main.js 默认一致)。
    """
    e = environ if environ is not None else os.environ
    raw = e.get("GALAXY_ELECTRON_PORT") or e.get("GALAXY_IPC_PORT")
    try:
        return int(raw) if raw else ELECTRON_IPC_PORT_DEFAULT
    except (TypeError, ValueError):
        return ELECTRON_IPC_PORT_DEFAULT


_ELECTRON_PORT = resolve_electron_ipc_port()
_ELECTRON_IPC_URL = f"http://127.0.0.1:{_ELECTRON_PORT}/ipc/presence-state"

# 单个 WS 客户端 send_json 的封顶时长:一个卡死/龟速的客户端绝不能拖垮
# 对其它客户端的广播(尤其是"说话中=True"这种瞬时脉冲)。超时即判死、清理。
_WS_SEND_TIMEOUT_S: float = 2.0


# ── DesktopPresenceMode → depth_factor 映射 ──
# STATIC(休息)    → 0.00-0.05  (Silent 呼吸光环)
# LIMINAL(认知)   → 0.15-0.85  (Liminal 透视空间展开)
# MANIFEST(执行)  → 0.90-0.95  (Manifest 透明)
#
# liminal 稳态取 0.62:着色器空间展开曲线是 smoothstep(0.40, 0.85),
# 旧值 0.50 只展开 ~13%(阈限空间几乎不可见);0.62 展开 ~44%,且仍低于
# 灵动岛淡出线 0.65,岛保持全亮。前端穿越编排带时由渲染层限速播出
# 收回→灵动岛→展开的完整秩序(见 electron/renderer/app.js _springUpdate)。
MODE_DEPTH_MAP = {
    "static": 0.05,
    "liminal": 0.62,
    "manifest": 0.92,
}


class GalaxyPresenceBridge:
    """
    单例。订阅 DesktopPresenceRuntime 的 StateEventBus，
    将 presence 模式转换为 depth_factor 推送到前端。

    推送策略（PR-IPC）：
    1. 优先 HTTP POST 到 Electron main.js: http://localhost:9231/ipc/presence-state
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
    _ambient_action: str = ""  # speak | silent | delegate
    _ambient_rationale: str = ""
    _ambient_ts: float = 0.0

    # 桥接已启动
    _started: bool = False

    # 推代替拉:panel feed 推送的防抖状态(同一时刻至多一个待推任务;
    # 两次推送最小间隔可经 GALAXY_PANEL_PUSH_MIN_INTERVAL 调,默认 1s)
    _push_pending: bool = False
    _last_push_ts: float = 0.0

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
            bus.subscribe("phase.silent", self._on_phase_silent)
            bus.subscribe("phase.liminal", self._on_phase_liminal)
            bus.subscribe("phase.manifest", self._on_phase_manifest)

            # 订阅 intent 强度更新
            bus.subscribe("intent.update", self._on_intent_update)

            # 订阅自发注意力事件 → 面板在场栏实时显示"在看/在听 + 决策理由"。
            bus.subscribe("ambient.observed", self._on_ambient_observed)
            bus.subscribe("ambient.decision", self._on_ambient_decision)

            # 推代替拉:通配订阅全部状态事件(None=wildcard)。任何影响面板数据的
            # 事件(设备/任务/技能/mesh/模型…)发生时,防抖后把【整份 panel feed】
            # 主动推给已连接的面板客户端——事件→UI 毫秒级,不再等 Electron 主进程
            # 的 5s 慢轮询(慢轮询降频保留为断线兜底)。相位/意图/ambient 已有上面
            # 的专用低延迟通道,在回调里跳过以免高频 tick 触发整份 feed 重推。
            bus.subscribe(None, self._on_any_event)

            logger.info("GalaxyPresenceBridge started — subscribed to StateEventBus (IPC HTTP + WS fallback)")
        except Exception as exc:
            logger.warning("StateEventBus subscription failed (non-fatal): %s", exc)

    # ── StateEventBus 回调 ──

    # 注:speaking 的生命周期由 core.speech_output 的 set_ai_speaking(播放起止)
    # 全权管理——相位切换【绝不】把它踩掉。此前 phase.silent/manifest 一到就强制
    # _speaking=False:响应文本一好 runtime 就回 SILENT,而 TTS 还在播,结果
    # "嘴在动、动画已灭"。相位事件只管相位。

    def _on_phase_silent(self, payload: Dict[str, Any]) -> None:
        self._current_mode = "static"
        self._current_depth = MODE_DEPTH_MAP["static"]
        self._intent = 0.0
        asyncio.create_task(self._broadcast_state())

    def _on_phase_liminal(self, event: Any) -> None:
        p = self._payload_of(event)
        self._current_mode = "liminal"
        self._current_depth = MODE_DEPTH_MAP["liminal"]
        # intent 从 payload 中提取，如果没有则默认 0.5
        self._intent = p.get("intent_strength", 0.5)
        self._speaking = p.get("speaking", self._speaking)
        asyncio.create_task(self._broadcast_state())

    def _on_phase_manifest(self, payload: Dict[str, Any]) -> None:
        self._current_mode = "manifest"
        self._current_depth = MODE_DEPTH_MAP["manifest"]
        self._intent = 1.0
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

    # ── 推代替拉:任意状态事件 → 防抖推送整份 panel feed ──

    def _on_any_event(self, event: Any) -> None:
        """通配回调:面板数据相关的事件发生时,安排一次防抖 feed 推送。

        - 相位/意图/ambient 已有上面的专用低延迟通道(且 intent 高频),跳过;
        - 没有面板客户端连接时零开销直接返回;
        - 回调可能来自无事件循环的线程(如 HA 桥线程),拿不到 loop 就静默放弃
          ——下一个来自 loop 线程的事件会补上,慢轮询兜底也仍在。
        """
        try:
            # StateEvent 的字段名是 .type(存的是枚举的字符串值),不是 event_type。
            # 用【正向白名单】而非黑名单:系统里有周期性心跳类事件(如多模态
            # ingress 总线 200ms tick),黑名单挡不全会退化成"每秒必推"。只有
            # 真正改变面板数据的事件族才触发推送。
            et = str(getattr(event, "type", "") or getattr(event, "event_type", "") or "")
            if not et.startswith(
                (
                    "device.",
                    "task.",
                    "skill.",
                    "executor.",
                    "mesh.",
                    "hitl.",
                    "shell.",
                    "entry_mode.",
                )
            ):
                return
            if not self._clients:
                return
            asyncio.get_running_loop()
        except Exception:  # noqa: BLE001
            return
        try:
            asyncio.create_task(self._debounced_feed_push())
        except Exception:  # noqa: BLE001
            pass

    async def _debounced_feed_push(self) -> None:
        """防抖:同一时刻至多一个待推任务;攒一小撮突发事件合并成一次推送,
        且两次推送至少间隔 GALAXY_PANEL_PUSH_MIN_INTERVAL(默认 1s)。"""
        cls = type(self)
        if cls._push_pending:
            return
        cls._push_pending = True
        try:
            import os as _os
            import time as _t

            try:
                min_iv = float(_os.environ.get("GALAXY_PANEL_PUSH_MIN_INTERVAL", "1.0") or "1.0")
            except ValueError:
                min_iv = 1.0
            wait = max(0.3, min_iv - (_t.time() - cls._last_push_ts))
            await asyncio.sleep(wait)
            await self._push_panel_feed()
            cls._last_push_ts = _t.time()
        except Exception as exc:  # noqa: BLE001
            logger.debug("panel feed 防抖推送失败(非致命): %s", exc)
        finally:
            cls._push_pending = False

    async def _push_panel_feed(self) -> None:
        """构建整份 panel feed 并推给全部已连接面板客户端(与 HTTP 路由共用同一
        构建器,推/拉两条通道数据形状恒一致)。orjson 可用时用它序列化提速。"""
        if not self._clients:
            return
        try:
            from core.routes.panel import build_panel_feed

            feed = await build_panel_feed()
        except Exception as exc:  # noqa: BLE001
            logger.debug("panel feed 构建失败(不推送): %s", exc)
            return
        text: Optional[str] = None
        try:
            import orjson

            text = orjson.dumps({"type": "panel_feed", "feed": feed}).decode()
        except Exception:  # noqa: BLE001
            pass
        # 内容哈希去重:feed 没实质变化就不发帧(触发事件≠数据一定变了,
        # 例如 heartbeat 型 device.updated;也天然抑制任何漏网的高频源)。
        try:
            import hashlib
            import json as _json

            basis = text if text is not None else _json.dumps(feed, sort_keys=True, default=str)
            digest = hashlib.sha1(basis.encode()).hexdigest()
            if digest == getattr(type(self), "_last_feed_hash", ""):
                return
            type(self)._last_feed_hash = digest
        except Exception:  # noqa: BLE001
            pass
        for ws in list(self._clients):
            try:
                if text is not None:
                    await ws.send_text(text)
                else:
                    await ws.send_json({"type": "panel_feed", "feed": feed})
            except Exception:  # noqa: BLE001
                self._clients.discard(ws)

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

    async def _broadcast_state(self, speaking_override: Optional[bool] = None) -> None:
        """广播状态到前端 —— 同时推 IPC HTTP 与 WebSocket，两条通道并发、非互斥。

        speaking_override 透传给 _build_message,保证 set_ai_speaking 的 True 脉冲
        携带调用时快照值,不被后到的 False 覆盖(见 _build_message 说明)。

        REGRESSION-FIX(本会话早前的 IPC 端口对齐修复引出的副作用):此前 IPC 成功就
        `return`、跳过 WS 广播 —— 注释写的是"优先 IPC / WS 是浏览器预览模式的 fallback",
        隐含假设两条通道是【互斥的部署形态】(要么整个 Electron App、要么裸浏览器预览)。
        但实测面板窗口自己本身还会直连 `/ws/desktop-presence`(useWebSocket.ts,喂
        usePhase 的 wsPhase),与 IPC→main.js→webContents.send 转发给面板的通道
        (usePanelData.ts 的 IPC 监听)是【同一个运行中的 App 内并存的两条独立通道】,
        不是二选一的部署模式。之前 IPC 端口错配(9229≠9231)时 `_try_ipc_http` 恒失败,
        才"意外"让 WS 广播兜底工作,面板才收得到实时 state_event。端口对齐(9231)后
        IPC 稳定成功,WS 广播被跳过,面板自己那条直连 WS 上的 wsPhase 就只在连接瞬间
        拿到一次快照、之后再收不到任何后续状态,而 App.tsx 又优先取 wsPhase —— 面板表现
        为"卡在某个相位不再跟随、行为怪异"。两条通道各自成本都很低(IPC POST 1s 超时；
        WS 广播对空 clients 集合是纯本地 no-op),改成【总是两条都推】,不再依赖谁先成功。
        """
        msg = self._build_message(speaking_override=speaking_override)
        # 两条通道【并发】推,互不阻塞:IPC 探测最长 1s(对着可能不存在的 Electron),
        # 绝不能挡在 WS 广播前面——否则面板/覆盖层那条直连 WS 要等 IPC 超时才更新,
        # "说话中=True"这类瞬时脉冲会被拖过消费端时间窗(全量 CI 里 tts 覆盖层偶发
        # 只收到 False 的根因)。return_exceptions 保证一条挂了不连累另一条。
        await asyncio.gather(
            self._try_ipc_http(msg),
            self._ws_broadcast(msg),
            return_exceptions=True,
        )

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
        """WebSocket 广播——【并发】发给所有客户端,单个客户端封顶超时。

        此前是逐个 `await ws.send_json`:一个卡死/龟速客户端(如全量测试里前面
        用例遗留、事件循环已换的僵尸连接)会顺序阻塞其后所有健康客户端,让"说话中"
        脉冲迟迟到不了真正在看的覆盖层。改为并发发送 + 每客户端 _WS_SEND_TIMEOUT_S
        封顶,超时/报错即判死清理,互不拖累。
        """
        async with self._lock:
            clients = list(self._clients)
        if not clients:
            return

        async def _send(ws: Any) -> Optional[Any]:
            try:
                await asyncio.wait_for(ws.send_json(msg), timeout=_WS_SEND_TIMEOUT_S)
                return None
            except Exception:  # noqa: BLE001 — 含 TimeoutError:慢/死客户端一律判死
                return ws

        results = await asyncio.gather(*(_send(ws) for ws in clients), return_exceptions=True)
        dead = [r for r in results if r is not None and not isinstance(r, BaseException)]
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    async def _send_to(self, websocket: WebSocket) -> None:
        """向单个客户端发送当前状态(封顶超时:注册时若客户端卡死不阻塞调用方)。"""
        try:
            await asyncio.wait_for(websocket.send_json(self._build_message()), timeout=_WS_SEND_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 — 含 TimeoutError
            logger.debug("Send to single client failed: %s", exc)

    def _build_message(self, speaking_override: Optional[bool] = None) -> Dict[str, Any]:
        """构建与前端兼容的 state_event 消息。

        speaking_override:set_ai_speaking 的广播用【调用时快照值】而非任务运行时
        的 live self._speaking —— 否则 True→播放→False 两次快速切换下,若 True 的
        广播任务被事件循环饿过了后面的 _speaking=False,它会读到 False,True 脉冲
        丢失(说话动画偶发不起 + CI flaky)。默认 None → 沿用 live 值,其它调用点不变。
        """
        _speaking = self._speaking if speaking_override is None else speaking_override
        # 说话地板:TTS 还在播时即使相位已回 SILENT(depth 0.05),也维持一个
        # 可见的在场深度——说完(set_ai_speaking(False) 广播)才落回相位深度,
        # 由渲染端弹簧自然缓落。消除"话没说完、画面先睡"的割裂。
        _depth = self._current_depth
        _phase = self._current_mode
        if _speaking:
            _depth = max(_depth, MODE_DEPTH_MAP["liminal"])
            # 说话即"阈限在场":TTS 在相位已回 SILENT 之后才发声,若仍报 static,只认 phase 的
            # 消费者(React 面板 usePhase)不会显示第二态。说话时把 phase/mode 报成 liminal,
            # 与 overlay(读 depth+speaking)语义一致、面板与 overlay 同步显示第二态。
            if _phase == "static":
                _phase = "liminal"
        return {
            "type": "state_event",
            "event_category": "ambient_tick",
            "payload": {
                "phase": _phase,
                "depth_factor": round(_depth, 4),
                "intent": round(self._intent, 4),
                "speaking": _speaking,
                "mode": _phase,
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
    return {"static": "silent", "silent": "silent", "liminal": "liminal", "manifest": "manifest"}.get(mode, "silent")


def set_ai_speaking(speaking: bool) -> None:
    """标记 AI 是否正在朗读，并广播到三态覆盖层（说话时动画随之运转）。

    非阻塞、降级安全。集中式 TTS(core.speech_output)在播放起止各调一次。
    """
    try:
        bridge = GalaxyPresenceBridge.get_instance()
        v = bool(speaking)
        bridge._speaking = v
        # 快照 v 随广播:True 帧永远携带 True,不被后到的 False 覆盖(修偶发丢脉冲)。
        _schedule(bridge._broadcast_state(speaking_override=v))
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
