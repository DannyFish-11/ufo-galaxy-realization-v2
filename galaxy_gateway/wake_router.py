"""
Wake Router - 智能唤醒路由器

核心功能：
- 就近唤醒路由：接收任意设备的唤醒事件，根据多维评分选择最佳响应设备
- 设备活跃度评分：基于 last_heartbeat、last_message 时间、屏幕状态等
- 能力匹配评分：语音任务→扬声器优先；视觉任务→屏幕优先
- 注意力焦点评分：屏幕亮着的设备 > 屏幕灭的设备；最近有用户交互的设备优先
- 唤醒事件去重：多设备同时检测到唤醒词时只选择一个设备响应

Stage 10: Scoring and task-graph convergence
- Device scoring now delegates to DeviceScoringEngine (core.control_plane.smart_scheduler)
  as the primary scoring authority, falling back to the local heuristic only when the
  engine is unavailable.  This aligns WakeRouter selection with the canonical scheduling
  scoring path used by SwarmCoordinator and the rest of the orchestration layer.
- Routing decisions are registered in TaskGraphRuntime so that wake-initiated task paths
  participate in graph tracking rather than remaining invisible to the runtime.

Author: UFO Galaxy Team
"""

# Stage 10 sentinels — importable by tests and monitoring tooling.
WAKE_ROUTER_USES_CANONICAL_SCORING: str = (
    "WAKE_ROUTER_CANONICAL_SCORING_V1: WakeRouter delegates device selection to "
    "DeviceScoringEngine (core.control_plane.smart_scheduler) as primary authority; "
    "local heuristic is used only as fallback when engine is unavailable."
)
WAKE_ROUTER_TASK_GRAPH_REGISTERED: str = (
    "WAKE_ROUTER_TASK_GRAPH_V1: WakeRouter.route() registers routing decisions in "
    "TaskGraphRuntime so that wake-initiated execution paths are tracked in the "
    "canonical task graph."
)

import asyncio
import logging
import time
import uuid as _uuid_mod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Callable, Any

logger = logging.getLogger("UFO-Galaxy.WakeRouter")


# =============================================================================
# 数据模型
# =============================================================================

class WakeTaskType(Enum):
    """唤醒后任务类型，用于能力匹配评分"""
    VOICE = "voice"         # 语音任务，优先有扬声器的设备
    VISUAL = "visual"       # 视觉任务，优先有屏幕的设备
    GENERAL = "general"     # 通用任务，按活跃度选择


@dataclass
class WakeEvent:
    """唤醒事件"""
    event_id: str
    source_device_id: str
    wake_word: str
    timestamp: float = field(default_factory=time.time)
    task_type: WakeTaskType = WakeTaskType.GENERAL
    confidence: float = 1.0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "event_id": self.event_id,
            "source_device_id": self.source_device_id,
            "wake_word": self.wake_word,
            "timestamp": self.timestamp,
            "task_type": self.task_type.value,
            "confidence": self.confidence,
            "extra": self.extra,
        }


@dataclass
class RouteDecision:
    """路由决策结果"""
    selected_device_id: str
    score: float
    reason: str
    wake_event: WakeEvent
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict:
        return {
            "selected_device_id": self.selected_device_id,
            "score": self.score,
            "reason": self.reason,
            "wake_event": self.wake_event.to_dict(),
            "timestamp": self.timestamp,
        }


# =============================================================================
# 唤醒路由器
# =============================================================================

class WakeRouter:
    """
    智能唤醒路由器

    根据设备活跃度、能力匹配和注意力焦点三个维度综合评分，
    将唤醒事件路由到最合适的设备。
    同时对多设备同时产生的相同唤醒事件进行去重。
    """

    # 去重时间窗口（秒）：在此窗口内认为是同一次唤醒
    DEDUP_WINDOW_SECONDS: float = 2.0

    # 评分权重
    WEIGHT_ACTIVITY: float = 0.4     # 活跃度权重
    WEIGHT_CAPABILITY: float = 0.3   # 能力匹配权重
    WEIGHT_ATTENTION: float = 0.3    # 注意力焦点权重

    def __init__(self):
        # 已处理的唤醒事件：wake_word -> (timestamp, event_id)
        self._recent_wake_events: Dict[str, tuple] = {}
        # 路由决策回调：当路由决策完成后调用
        self._on_decision: Optional[Callable[[RouteDecision], Any]] = None
        # 路由历史记录
        self._route_history: List[RouteDecision] = []
        self._max_history: int = 200

        logger.info("WakeRouter initialized")

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def set_decision_callback(self, callback: Callable[[RouteDecision], Any]):
        """设置路由决策完成后的回调函数"""
        self._on_decision = callback

    async def route(self, wake_event: WakeEvent) -> Optional[RouteDecision]:
        """
        处理唤醒事件并路由到最合适的设备

        Stage 10: Uses DeviceScoringEngine as the primary device scoring authority
        (canonical scheduling path) and registers the routing decision in
        TaskGraphRuntime so that wake-initiated task paths are tracked in the
        canonical task graph.

        Args:
            wake_event: 唤醒事件

        Returns:
            路由决策结果，若去重后被丢弃则返回 None
        """
        # 去重检查
        if self._is_duplicate(wake_event):
            logger.info(
                f"[WakeRouter] 唤醒事件去重: wake_word='{wake_event.wake_word}' "
                f"from device={wake_event.source_device_id}"
            )
            return None

        # 记录本次唤醒词时间戳，防止后续重复
        self._recent_wake_events[wake_event.wake_word] = (
            wake_event.timestamp,
            wake_event.event_id,
        )

        # 获取在线设备列表
        devices = self._get_online_devices()
        if not devices:
            logger.warning("[WakeRouter] 没有可用设备，无法路由唤醒事件")
            return None

        # Stage 10: Attempt canonical device scoring via DeviceScoringEngine.
        # The engine provides the same capability/latency/load/health scoring
        # used by SwarmCoordinator and the orchestration layer, converging the
        # WakeRouter onto the canonical selection path.
        best_device_id: Optional[str] = None
        best_score: float = 0.0
        best_reason: str = ""
        _canonical_scoring_used = False

        try:
            from core.control_plane.smart_scheduler import (
                DeviceScoreInput,
                DeviceScoringEngine,
            )

            # Map task_type → required capability hints for the scoring engine.
            _required_caps: List[str] = []
            if wake_event.task_type == WakeTaskType.VOICE:
                _required_caps = ["speaker"]
            elif wake_event.task_type == WakeTaskType.VISUAL:
                _required_caps = ["screen"]

            _candidates = []
            for device_id, device_info in devices.items():
                _now = time.time()
                _last_active = max(
                    device_info.get("last_heartbeat", 0),
                    device_info.get("last_message", 0),
                )
                _elapsed = _now - _last_active
                # Map device recency (seconds since last seen) to a synthetic
                # ping latency in milliseconds for DeviceScoringEngine.
                # Scale factor 10×: 1 second idle ≈ 10 ms latency proxy, so a
                # device silent for 200 s hits the 2 000 ms ceiling and scores 0.
                _synthetic_ping_ms = min(_elapsed * 10.0, 2000.0)
                # Map screen_on + last_interaction to a synthetic load proxy.
                # Screen-on devices are assumed less loaded (−30 pp).
                # Devices with a very recent interaction (within 30 s) get up to
                # an additional −50 pp, proportional to how recent the interaction
                # was.  Combined floor is 0 (minimum synthetic load).
                _screen_on = device_info.get("screen_on", False)
                _last_interaction = device_info.get("last_interaction", 0)
                _interaction_recency = max(0.0, 30.0 - (_now - _last_interaction)) if _last_interaction > 0 else 0.0
                _load_pct = max(0.0, 100.0 - (_interaction_recency / 30.0) * 50.0 - (30.0 if _screen_on else 0.0))

                _candidates.append(
                    DeviceScoreInput(
                        device_id=device_id,
                        ping_latency_ms=_synthetic_ping_ms,
                        load_pct=_load_pct,
                        capabilities=list(device_info.get("capabilities", [])),
                        health_score=max(0.0, 100.0 - _elapsed),
                    )
                )

            _engine = DeviceScoringEngine(require_all_capabilities=False)
            _best = _engine.select_best_device(_candidates, _required_caps or None)
            if _best is not None:
                best_device_id = _best.device_id
                best_score = _best.total
                best_reason = (
                    f"canonical_scoring: cap={_best.capability_score:.2f} "
                    f"latency={_best.latency_score:.2f} "
                    f"load={_best.load_score:.2f} "
                    f"health={_best.health_score:.2f}"
                )
                _canonical_scoring_used = True
                logger.debug(
                    "[WakeRouter] canonical DeviceScoringEngine selected device=%s score=%.3f",
                    best_device_id, best_score,
                )
        except Exception as _scoring_err:
            logger.debug(
                "[WakeRouter] canonical scoring unavailable (%s); falling back to local heuristic",
                _scoring_err,
            )

        # Fallback: use local heuristic scoring when canonical engine is unavailable.
        if best_device_id is None:
            scored = []
            for device_id, device_info in devices.items():
                score, reason_parts = self._score_device(
                    device_id, device_info, wake_event
                )
                scored.append((device_id, score, " | ".join(reason_parts)))
            scored.sort(key=lambda x: x[1], reverse=True)
            best_device_id, best_score, best_reason = scored[0]

        decision = RouteDecision(
            selected_device_id=best_device_id,
            score=best_score,
            reason=best_reason,
            wake_event=wake_event,
        )

        # 记录路由历史
        self._route_history.append(decision)
        if len(self._route_history) > self._max_history:
            self._route_history = self._route_history[-self._max_history:]

        logger.info(
            "[WakeRouter] 路由决策: device=%s score=%.2f reason='%s' canonical_scoring=%s",
            best_device_id, best_score, best_reason, _canonical_scoring_used,
        )

        # Stage 10: Register routing decision in TaskGraphRuntime so that
        # wake-initiated task paths are tracked in the canonical task graph.
        try:
            from core.task_graph_runtime import (
                get_task_graph_runtime as _get_tgr,
                WorkflowContributorKind as _WCK,
            )
            _task_id = f"wake_{_uuid_mod.uuid4().hex[:16]}"
            _get_tgr().register_node_raw(
                task_id=_task_id,
                tool_name="wake_route",
                session_id="",
                trace_id=wake_event.event_id,
                device_id=best_device_id,
                contributor=_WCK.COMMAND_ROUTER,
            )
            logger.debug(
                "[WakeRouter] registered wake routing in TaskGraphRuntime task_id=%s device=%s",
                _task_id, best_device_id,
            )
        except Exception as _tgr_err:
            logger.debug(
                "[WakeRouter] TaskGraphRuntime registration skipped: %s", _tgr_err
            )

        # 触发回调
        if self._on_decision:
            try:
                result = self._on_decision(decision)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"[WakeRouter] 决策回调异常: {e}")

        return decision

    def get_route_history(self, limit: int = 50) -> List[Dict]:
        """获取路由历史记录"""
        return [d.to_dict() for d in self._route_history[-limit:]]

    def clear_dedup_cache(self):
        """清除去重缓存（用于测试或手动重置）"""
        self._recent_wake_events.clear()

    # ------------------------------------------------------------------
    # 内部方法：去重
    # ------------------------------------------------------------------

    def _is_duplicate(self, wake_event: WakeEvent) -> bool:
        """
        检查唤醒事件是否是已处理事件的重复

        在 DEDUP_WINDOW_SECONDS 时间窗口内，相同唤醒词视为重复。
        """
        if wake_event.wake_word not in self._recent_wake_events:
            return False

        last_ts, last_event_id = self._recent_wake_events[wake_event.wake_word]
        # 同一个事件 ID 不算重复（幂等）
        if last_event_id == wake_event.event_id:
            return False

        elapsed = wake_event.timestamp - last_ts
        return elapsed < self.DEDUP_WINDOW_SECONDS

    # ------------------------------------------------------------------
    # 内部方法：设备评分
    # ------------------------------------------------------------------

    def _score_device(
        self,
        device_id: str,
        device_info: Dict,
        wake_event: WakeEvent,
    ) -> tuple:
        """
        对单个设备进行综合评分

        Returns:
            (score: float, reason_parts: List[str])
        """
        reason_parts = []

        activity_score = self._score_activity(device_id, device_info)
        capability_score = self._score_capability(device_id, device_info, wake_event)
        attention_score = self._score_attention(device_id, device_info)

        reason_parts.append(f"activity={activity_score:.2f}")
        reason_parts.append(f"capability={capability_score:.2f}")
        reason_parts.append(f"attention={attention_score:.2f}")

        total = (
            self.WEIGHT_ACTIVITY * activity_score
            + self.WEIGHT_CAPABILITY * capability_score
            + self.WEIGHT_ATTENTION * attention_score
        )
        return total, reason_parts

    def _score_activity(self, device_id: str, device_info: Dict) -> float:
        """
        设备活跃度评分 [0, 1]

        基于 last_heartbeat 和 last_message 时间计算，越近越高。
        """
        now = time.time()
        last_heartbeat = device_info.get("last_heartbeat", 0)
        last_message = device_info.get("last_message", 0)

        # 取两者中最近的时间
        last_active = max(last_heartbeat, last_message)
        elapsed = now - last_active

        # 60 秒内线性衰减，60 秒后为 0
        if elapsed <= 0:
            return 1.0
        elif elapsed >= 60.0:
            return 0.0
        else:
            return 1.0 - elapsed / 60.0

    def _score_capability(
        self,
        device_id: str,
        device_info: Dict,
        wake_event: WakeEvent,
    ) -> float:
        """
        能力匹配评分 [0, 1]

        根据唤醒后任务类型匹配设备能力：
        - VOICE → 扬声器（speaker）优先
        - VISUAL → 屏幕（screen）优先
        - GENERAL → 无偏好，统一返回 0.5
        """
        capabilities: List[str] = device_info.get("capabilities", [])

        if wake_event.task_type == WakeTaskType.VOICE:
            return 1.0 if "speaker" in capabilities else 0.3
        elif wake_event.task_type == WakeTaskType.VISUAL:
            return 1.0 if "screen" in capabilities else 0.3
        else:
            # GENERAL：有屏幕和扬声器的设备加分
            score = 0.5
            if "screen" in capabilities:
                score += 0.25
            if "speaker" in capabilities:
                score += 0.25
            return min(score, 1.0)

    def _score_attention(self, device_id: str, device_info: Dict) -> float:
        """
        注意力焦点评分 [0, 1]

        屏幕亮着 > 屏幕灭；最近有用户交互的设备优先。
        """
        screen_on: bool = device_info.get("screen_on", False)
        # 最近一次用户交互时间（秒级时间戳，0 表示未知）
        last_interaction: float = device_info.get("last_interaction", 0)

        base = 0.7 if screen_on else 0.3

        # 如果有最近交互记录，根据距离现在的时间加分
        if last_interaction > 0:
            elapsed = time.time() - last_interaction
            # 30 秒内的交互获得满分加成
            interaction_bonus = max(0.0, 0.3 * (1.0 - elapsed / 30.0))
            return min(base + interaction_bonus, 1.0)

        return base

    # ------------------------------------------------------------------
    # 外部注入（用于测试或特殊场景）
    # ------------------------------------------------------------------

    def inject_device_info(self, device_id: str, device_info: Dict):
        """
        注入设备信息（主要用于测试）

        device_info 格式::

            {
                "capabilities": ["screen", "speaker"],
                "last_heartbeat": <timestamp>,
                "last_message": <timestamp>,
                "screen_on": True,
                "last_interaction": <timestamp>,
            }
        """
        if not hasattr(self, "_injected_devices"):
            self._injected_devices: Dict[str, Dict] = {}
        self._injected_devices[device_id] = device_info

    # ------------------------------------------------------------------
    # 内部方法：设备列表获取
    # ------------------------------------------------------------------

    def _get_online_devices(self) -> Dict[str, Dict]:
        """
        从 device_router、device_comm 及注入设备中汇总在线设备信息。
        注入设备（用于测试）优先级最高，不会被覆盖。

        Returns:
            dict: {device_id: device_info}
        """
        devices: Dict[str, Dict] = {}

        # 注入设备（用于测试）
        injected = getattr(self, "_injected_devices", {})
        devices.update(injected)

        # 从 galaxy_gateway.device_router 获取注册设备
        try:
            from galaxy_gateway.device_router import device_router
            for device_id, device in device_router.devices.items():
                if device.status == "online":
                    last_ts = (
                        device.last_seen.timestamp() if device.last_seen else 0
                    )
                    entry = {
                        "capabilities": device.capabilities,
                        "last_heartbeat": last_ts,
                        "last_message": last_ts,
                        "screen_on": "screen" in device.capabilities,
                        "last_interaction": 0,
                    }
                    # 注入的数据优先级更高，不覆盖
                    if device_id not in devices:
                        devices[device_id] = entry
        except Exception as e:
            logger.debug(f"[WakeRouter] 获取 device_router 设备失败: {e}")

        # 从 core.device_communication 补充心跳/消息时间
        try:
            from core.device_communication import device_comm
            for device_id, conn in device_comm._connections.items():
                if device_id not in devices:
                    devices[device_id] = {
                        "capabilities": [],
                        "last_heartbeat": conn.last_heartbeat,
                        "last_message": conn.last_message,
                        "screen_on": False,
                        "last_interaction": conn.last_message,
                    }
                else:
                    # 更新更精确的心跳/消息时间（不覆盖注入设备）
                    if device_id not in injected:
                        devices[device_id].setdefault("last_heartbeat", conn.last_heartbeat)
                        devices[device_id].setdefault("last_message", conn.last_message)
                        if not devices[device_id].get("last_interaction"):
                            devices[device_id]["last_interaction"] = conn.last_message
        except Exception as e:
            logger.debug(f"[WakeRouter] 获取 device_comm 连接失败: {e}")

        return devices


# 模块级单例
wake_router = WakeRouter()

__all__ = ["WakeRouter", "WakeEvent", "WakeTaskType", "RouteDecision", "wake_router"]
