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

# RUF006: retain fire-and-forget create_task results so the event loop's weak
# reference can't let them be garbage-collected mid-execution.
_BACKGROUND_TASKS: set = set()

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
# 锚点的唯一事实源是 core.phase_contract.PHASE_ANCHORS —— 这里只做别名，
# 避免同一组数字在两处各写一份、改一处忘另一处。
from core.phase_contract import PHASE_ANCHORS as MODE_DEPTH_MAP  # noqa: E402


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
    #: 上一次**镜像到网格**的相位。网格按相位去重(见 _mirror_presence_to_mesh):
    #: 本机那两条通道要连续量做平滑动画,网格只要"翻档了"这件事。
    _last_mirrored_phase: str = ""
    # 最近一次相位事件解算出的姿态（相位 + 连续量）。类属性给个 None 兜底：
    # 首帧广播可能发生在任何相位事件之前，那时按"只有锚点"处理。
    _posture: Any = None
    _intent: float = 0.0
    _speaking: bool = False

    # 自发注意力（ambient）最近一拍：供面板在场栏显示"它正在看什么/刚才为何开口"。
    _ambient_seeing: bool = False
    _ambient_hearing: bool = False
    _ambient_action: str = ""  # speak | silent | delegate
    _ambient_rationale: str = ""
    _ambient_ts: float = 0.0

    # 阈限态的内容：过渡里正在干嘛 + 沙盘推演摘要。
    # 由 RuntimeSession 登记（note_liminal_activity），经 continuum.state 的 200ms
    # tick 送到这里。此前阈限相位在面板上只有一个空标签，就是因为这两项没有链路。
    _liminal_activity: str = "none"
    _liminal_simulation: Optional[Dict[str, Any]] = None

    # 桥接已启动
    _started: bool = False

    # 共享的 IPC HTTP 会话及其所属事件循环（见 _ipc_session 的说明）。
    _ipc_http_session: Any = None
    _ipc_http_loop: Any = None

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
            # 阈限内容：RuntimeSession 的 200ms tick 把「正在推演什么」带上来。
            bus.subscribe("continuum.state", self._on_continuum_state)

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

    def _apply_posture(self, token: str) -> None:
        """按相位取一份姿态，深度由**实算的连续量**导出而非查表。

        改造前这里是 ``self._current_depth = MODE_DEPTH_MAP[token]`` —— 三个
        硬编码常数。而后端的 ContinuumState 一直在算 collapse_tendency /
        retreat_tendency（"推向相位塌缩/回撤的概率质量"），也就是"离翻到下一档
        还有多远"，那正是三态**边缘**的定义。这份连续量此前到这一步就被丢掉了。

        现在深度在本相位的带内按倾向漂移（见 core.phase_contract）。相位本身
        仍由事件决定 —— 连续量只描述"在这一档里的哪个位置"，绝不改变是哪一档。

        取不到 ContinuumState 时 posture.source 为 ``anchor_only``，深度等于
        原来的锚点：行为与改造前完全一致，只是如实标注了这是估计值。
        """
        from core.phase_contract import resolve_phase_posture

        self._posture = resolve_phase_posture(token)
        self._current_depth = self._posture.depth

    def _posture_payload(self, effective_phase: str) -> Dict[str, Any]:
        """广播用的姿态字典。

        ``effective_phase`` 是 payload 里实际报出的相位（说话期 static 会被报成
        liminal）。姿态必须跟着它走，否则会出现"相位说 liminal、姿态说 static"
        这种自相矛盾的帧——面板同时读这两处。

        没有缓存姿态（首帧早于任何相位事件）时按 effective_phase 现算一份，
        自然会走 anchor_only 分支。
        """
        from core.phase_contract import resolve_phase_posture

        posture = self._posture
        if posture is None or getattr(posture, "phase", None) != effective_phase:
            posture = resolve_phase_posture(effective_phase)
        return posture.to_dict()

    def _render_payload(self, effective_phase: str) -> Dict[str, Any]:
        """广播用的**忠实**渲染契约（见 core.phase_contract.RenderPosture）。

        与上面的 ``_posture_payload`` 并存而不是取代它：那份是一维遗留投影，既有
        覆盖层 presence_motion.js 按它的三个锚点调过参；这份是双轴契约，新代码
        应当消费这一份。两份同时广播的成本只是几十字节。

        主轴（lifecycle）用 ``effective_phase`` —— 它就是桥一路维护的 TriState
        语义（且已含"说话地板"修正：TTS 还在播时 static 会被报成 liminal）。
        副轴、表达参数、连续量由 RenderPosture 自己从 ContinuumState 读。

        阈限内容（在推演什么）来自 ``continuum.state`` tick 带上来的字段 ——
        那是 RuntimeSession 登记的，见 desktop_presence_runtime.note_liminal_activity。
        """
        from core.phase_contract import SimulationSummary, resolve_render_posture

        # 桥内部用 "static" 表示静息，契约主轴用 "silent"（TriState 的词汇）。
        life = "silent" if effective_phase == "static" else effective_phase

        # 一致性守卫：阈限活动只在阈限相位里成立。
        #
        # tick 每 200ms 才推一次，主体已经进 MANIFEST 而下一拍还没到时，这里会
        # 残留上一拍的 "rehearsing"，广播出去就是 lifecycle=manifest 且
        # activity=rehearsing 这种自相矛盾的帧——本文件已经为同类问题栽过跟头
        # （见 _posture_payload 的注释："相位说 liminal、姿态说 static"）。
        # 摘要不跟着清：进表达期后面板仍要能显示"按哪条候选提交的"，那是结果不是活动。
        activity = self._liminal_activity if life == "liminal" else "none"

        sim = None
        raw = self._liminal_simulation
        if raw:
            paths = raw.get("candidate_paths") or []
            committed = raw.get("committed_path")
            sim = SimulationSummary(
                is_active=bool(raw.get("is_active", False)),
                simulation_kind=str(raw.get("simulation_kind", "none") or "none"),
                candidate_paths=tuple(str(p) for p in paths),
                committed_path=committed,
                # is_committed 取上游算好的那份，**不在这里重推**。
                # 规范推导在 core.liminal_space_mapping.build_simulation_summary()
                # （openclawd 侧已统一过它），这里再写一遍 `committed is not None`
                # 就是同一件事两处推导，改一处便分叉。缺字段时才退回本地推导，
                # 那是老 payload 的兼容路径。
                is_committed=bool(raw["is_committed"]) if "is_committed" in raw else committed is not None,
                step_count=int(raw.get("step_count", 0) or 0),
                scenario_label=raw.get("scenario_label"),
            )
        return resolve_render_posture(
            life,
            liminal_activity=activity,
            simulation=sim,
        ).to_dict()

    def _on_continuum_state(self, event: Any) -> None:
        """吸收 ``continuum.state`` tick 里的阈限内容。

        只取 ``liminal_activity`` / ``simulation`` 两项。这条 tick 里的其它字段
        （presence_intensity、coherence 等）刻意**不取**：它们的权威来源是
        ContinuumState 本身，``RenderPosture`` 已经直接从那里读，从这里再抄一份
        只会制造两个可能不一致的副本。

        摘要**不因缺席而清空**：tick 在纯思考期不带 simulation 字段，若那时把
        缓存抹掉，「刚才推演了哪几条候选」在进入表达期之前就消失了。真正的清空
        由 RuntimeSession 回到 SILENT 时驱动（那一拍 tick 已经停了，靠下面的
        相位回落兜底）。
        """
        try:
            payload = getattr(event, "payload", None)
            if not isinstance(payload, dict):
                payload = event if isinstance(event, dict) else {}
            # 取值域读契约，不手抄：抄一份就多一个会漂的定义。
            from core.phase_contract import LIMINAL_ACTIVITIES

            act = payload.get("liminal_activity")
            if isinstance(act, str) and act in LIMINAL_ACTIVITIES:
                self._liminal_activity = act
            sim = payload.get("simulation")
            if isinstance(sim, dict):
                self._liminal_simulation = sim
        except Exception:  # noqa: BLE001 — 可见性绝不该拖垮桥
            logger.debug("_on_continuum_state failed (non-fatal)", exc_info=True)

    def _on_phase_silent(self, payload: Dict[str, Any]) -> None:
        self._current_mode = "static"
        self._apply_posture("static")
        self._intent = 0.0
        # 主体回到静息：阈限内容随之归零。这里是它唯一的清空点 ——
        # continuum tick 在 SILENT 时已经停了，不会再送 liminal_activity="none" 过来，
        # 不在这清就会把上一次请求的候选路径一直挂到下一次请求。
        self._liminal_activity = "none"
        self._liminal_simulation = None
        _bt = asyncio.create_task(self._broadcast_state())
        _BACKGROUND_TASKS.add(_bt)
        _bt.add_done_callback(_BACKGROUND_TASKS.discard)

    def _on_phase_liminal(self, event: Any) -> None:
        p = self._payload_of(event)
        self._current_mode = "liminal"
        self._apply_posture("liminal")
        # intent 从 payload 中提取，如果没有则默认 0.5
        self._intent = p.get("intent_strength", 0.5)
        self._speaking = p.get("speaking", self._speaking)
        _bt = asyncio.create_task(self._broadcast_state())
        _BACKGROUND_TASKS.add(_bt)
        _bt.add_done_callback(_BACKGROUND_TASKS.discard)

    def _on_phase_manifest(self, payload: Dict[str, Any]) -> None:
        self._current_mode = "manifest"
        self._apply_posture("manifest")
        self._intent = 1.0
        _bt = asyncio.create_task(self._broadcast_state())
        _BACKGROUND_TASKS.add(_bt)
        _bt.add_done_callback(_BACKGROUND_TASKS.discard)

    def _on_intent_update(self, event: Any) -> None:
        """意图强度持续更新 —— 刷新意图与姿态，**不再自己算深度**。

        改造前这里是 ``self._current_depth = 0.15 + intent * 0.70``。两个问题：

        1. **它违反相位权威**。这条线性映射能把一个 liminal 帧的深度放到 0.15
           （着色器的纯静默区）或 0.85（空间收回区）。面板读 phase 说"阈限"，
           覆盖层读 depth 画的却是静默 —— 正是 phase_contract 存在要防的那种
           自相矛盾的帧。liminal 带按契约只允许 [0.3635, 0.755]。
        2. **它绕开了契约、还不更新 _posture**。而本回调是三个相位事件里
           **频率最高**的那个（见 _on_any_event 的注释：intent 高频），所以
           #1573 刚接上的连续深度会在进入 liminal 后立刻被它盖掉，广播出去的
           ``depth_factor`` 与 ``posture.depth`` 还会互相打架。

        intent 并没有因此消失：它一直是 payload 里**自己那一维**
        （``payload.intent``），渲染端读它来决定过渡速度
        （electron/renderer/presence_motion.js）。这里只是不再把它和深度混为
        一谈 —— 深度归相位契约管，强度归 intent 管。
        """
        if self._current_mode != "liminal":
            return
        p = self._payload_of(event)
        self._intent = p.get("intent_strength", 0.5)
        # 走与三个相位事件同一条路：深度由实算的连续量导出，姿态同步更新。
        self._apply_posture("liminal")
        self._speaking = p.get("speaking", False)
        _bt = asyncio.create_task(self._broadcast_state())
        _BACKGROUND_TASKS.add(_bt)
        _bt.add_done_callback(_BACKGROUND_TASKS.discard)

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
            _bt = asyncio.create_task(self._debounced_feed_push())
            _BACKGROUND_TASKS.add(_bt)
            _bt.add_done_callback(_BACKGROUND_TASKS.discard)
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
        _bt = asyncio.create_task(self._broadcast_state())
        _BACKGROUND_TASKS.add(_bt)
        _bt.add_done_callback(_BACKGROUND_TASKS.discard)

    def _on_ambient_decision(self, event: Any) -> None:
        """自发注意力：三选一决策（speak/silent/delegate）+ 理由。"""
        import time as _t

        p = self._payload_of(event)
        self._ambient_action = str(p.get("action", ""))
        self._ambient_rationale = str(p.get("rationale") or p.get("utterance") or p.get("task") or "")
        self._ambient_ts = _t.time()
        _bt = asyncio.create_task(self._broadcast_state())
        _BACKGROUND_TASKS.add(_bt)
        _bt.add_done_callback(_BACKGROUND_TASKS.discard)

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
        # 第三条通道:网格。上面两条都是**本机**的(IPC 到 Electron、WS 到面板),
        # 网格里其它节点看不到这台机器的在场相位。
        self._mirror_presence_to_mesh(msg)

    def _mirror_presence_to_mesh(self, msg: Dict[str, Any]) -> None:
        """相位**发生变化**时,把在场状态发到 ``galaxy.presence.state``。

        为什么只在变化时发,而不是每次广播都发
        --------------------------------------
        这条广播在阈限期由 200ms 的 continuum tick 驱动 —— **每秒 5 次**。每次都
        往网格发,等于每个节点常态 5 Hz 灌流;节点一多,这一条就能把总线压满,而
        网格里的消费方要的根本不是连续流,是"这个节点的在场相位变了"这件事。

        本机那两条通道需要连续量(面板要平滑动画),网格不需要 —— 同一份数据,
        两种消费节奏。所以这里按相位去重,只在真的翻档时发一条。

        best-effort:发不出去不影响本机那两条通道,它们已经在上面 gather 完了。
        """
        try:
            payload = msg.get("payload") or {}
            phase = str(payload.get("phase") or "")
            if not phase or phase == self._last_mirrored_phase:
                return

            from core.nats_bus import get_nats_bus  # noqa: PLC0415

            bus = get_nats_bus()
            if not bus.is_usable():
                return
            self._last_mirrored_phase = phase
            task = asyncio.get_running_loop().create_task(
                bus.publish_presence_event(
                    "state",
                    {
                        "phase": phase,
                        "speaking": bool(payload.get("speaking")),
                        "source": payload.get("source", "DesktopPresenceRuntime"),
                    },
                )
            )
            _BACKGROUND_TASKS.add(task)
            task.add_done_callback(_BACKGROUND_TASKS.discard)
        except RuntimeError:
            pass  # 不在事件循环里
        except Exception as exc:  # pragma: no cover - 镜像绝不能影响本机广播
            logger.debug("在场网格镜像跳过:%s", exc)

    @classmethod
    def _ipc_session(cls) -> Any:
        """取共享的 IPC HTTP 会话；按事件循环缓存。

        为什么要共享
        ------------
        这条 POST 不是偶发的：阈限期由 200ms 的 continuum tick 发 ``intent.update``
        驱动广播，也就是**每秒 5 次**。原先每次都 ``async with
        aiohttp.ClientSession()``，等于每 200ms 新建一个连接器 + 一条到
        127.0.0.1 的 TCP 连接再拆掉。同机实测（200 次 POST 到真实本地服务端）：

            每次新建 Session   中位 0.83 ms   p95 1.15 ms
            复用 Session       中位 0.28 ms   p95 0.41 ms

        省下的是**事件循环上的时间**，而那条循环同时在服务正在处理的那个请求 ——
        阈限期恰恰是循环最忙的时候。

        为什么按事件循环缓存
        --------------------
        aiohttp 的 Session 绑死创建它的循环。全量测试里每个用例一个循环，缓存一个
        跨循环的 Session 会在下一个用例里抛 "Event loop is closed"；而本函数的
        调用方吞异常返回 ``False``，症状会是「IPC 从某个时刻起永远失败、WS 兜底
        默默顶上」——指不回这里。所以循环一换就丢弃重建。

        旧 Session 不 ``await close()``：循环都没了，close 也没处 await。直接丢引用，
        随旧循环一起被回收。
        """
        loop = asyncio.get_running_loop()
        session = cls._ipc_http_session
        if session is not None and (cls._ipc_http_loop is not loop or session.closed):
            session = None
        if session is None:
            session = aiohttp.ClientSession()
            cls._ipc_http_session = session
            cls._ipc_http_loop = loop
        return session

    async def _try_ipc_http(self, msg: Dict[str, Any]) -> bool:
        """尝试 HTTP POST 到 Electron。返回是否成功。"""
        if aiohttp is None:
            return False
        try:
            async with self._ipc_session().post(
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
                # 相位姿态：离散相位之外，把后端【一直在算却从没送出来】的连续量
                # 带给面板（在场强度 / 塌缩与回撤倾向 / 稳定度）。契约与生成的
                # TS 类型见 core/phase_contract.py 与 panel/src/types/phase_contract.gen.ts。
                #
                # 与上面 depth_factor 的关系：depth_factor 是姿态里的 depth 经过
                # "说话地板"修正后的最终渲染值；posture.depth 是未修正的原值。
                # 两者刻意都给：前者是渲染直接用的，后者是判断"它现在离翻档有多近"
                # 的依据。只给前者的话，说话期的地板会把倾向信息盖掉。
                "posture": self._posture_payload(_phase),
                # 忠实契约（core.phase_contract.RenderPosture）。与上面的 posture
                # 并存：那份是一维遗留投影，覆盖层 presence_motion.js 按它调过参；
                # 这份是双轴 —— 主轴 lifecycle（用户能感知的节奏）+ 副轴 continuum
                # 四相（含 receding 返回弧），外加阈限态的可视内容（在推演哪几条
                # 候选、提交了哪条）。新代码应当消费这一份。
                "render": self._render_payload(_phase),
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
        _bt = loop.create_task(coro)
        _BACKGROUND_TASKS.add(_bt)
        _bt.add_done_callback(_BACKGROUND_TASKS.discard)
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
