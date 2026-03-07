"""
Fused Wake Decision - 多模态融合唤醒决策

核心功能：
- 时间窗口聚合：在 2 秒时间窗口内聚合来自不同触发器的事件
- 融合置信度计算：语音+拿起手机→高置信度; 仅语音→中置信度需二次确认
- 置信度阈值控制：可配置唤醒灵敏度
- 防误唤醒：电视/广播中的唤醒词→低置信度→不触发

与 system_integration/hardware_trigger.py 集成：
- 作为 HardwareTriggerManager.on_trigger 的下游处理器
- 使用 TriggerType、TriggerEvent、TriggerPriority 数据类

Author: UFO Galaxy Team
Version: 1.0
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Callable, Any, Tuple

logger = logging.getLogger("UFO-Galaxy.FusedWakeDecision")

# 延迟导入以避免循环依赖，在运行时从 system_integration.hardware_trigger 导入
try:
    from system_integration.hardware_trigger import (
        TriggerType,
        TriggerEvent,
        TriggerPriority,
    )
except ImportError:  # pragma: no cover
    logger.warning("[FusedWakeDecision] 无法导入 hardware_trigger，使用占位符类型")
    TriggerType = None  # type: ignore
    TriggerEvent = None  # type: ignore
    TriggerPriority = None  # type: ignore


# =============================================================================
# 融合规则定义
# =============================================================================

@dataclass
class FusionRule:
    """
    融合规则：定义一组触发器类型组合对应的置信度及原因

    Attributes:
        required_types: 必须同时出现的触发器类型集合
        optional_types: 可选触发器类型集合（出现则加分）
        base_confidence: 基础置信度 [0, 1]
        optional_bonus: 每个可选触发器的置信度加成
        description: 规则描述
    """
    required_types: frozenset
    base_confidence: float
    description: str
    optional_types: frozenset = field(default_factory=frozenset)
    optional_bonus: float = 0.1


# 默认融合规则表（按 base_confidence 降序，优先匹配高置信度规则）
def _build_default_rules() -> List[FusionRule]:
    if TriggerType is None:
        return []
    return [
        # 语音 + 运动（拿起手机/走近）→ 最高置信度
        FusionRule(
            required_types=frozenset({TriggerType.VOICE, TriggerType.MOTION}),
            base_confidence=0.95,
            description="语音唤醒词 + 运动传感器（拿起设备）",
        ),
        # 语音 + 触摸 → 高置信度
        FusionRule(
            required_types=frozenset({TriggerType.VOICE, TriggerType.TOUCH}),
            base_confidence=0.90,
            description="语音唤醒词 + 触摸屏幕",
        ),
        # 语音 + 接近传感器 → 高置信度（用户靠近设备）
        FusionRule(
            required_types=frozenset({TriggerType.VOICE, TriggerType.PROXIMITY}),
            base_confidence=0.85,
            description="语音唤醒词 + 接近传感器",
        ),
        # 语音 + 硬件按键 → 高置信度
        FusionRule(
            required_types=frozenset({TriggerType.VOICE, TriggerType.HARDWARE_KEY}),
            base_confidence=0.85,
            description="语音唤醒词 + 硬件按键",
        ),
        # 仅语音 → 中置信度
        FusionRule(
            required_types=frozenset({TriggerType.VOICE}),
            base_confidence=0.60,
            description="仅语音唤醒词（可能为背景噪声）",
        ),
        # 手势 + 热键 → 中高置信度
        FusionRule(
            required_types=frozenset({TriggerType.GESTURE, TriggerType.HOTKEY}),
            base_confidence=0.80,
            description="手势 + 快捷键组合",
        ),
        # 仅手势 → 中置信度
        FusionRule(
            required_types=frozenset({TriggerType.GESTURE}),
            base_confidence=0.70,
            description="手势唤醒",
        ),
        # 仅热键 → 中高置信度（明确的用户操作）
        FusionRule(
            required_types=frozenset({TriggerType.HOTKEY}),
            base_confidence=0.85,
            description="键盘快捷键",
        ),
        # 仅硬件按键 → 中置信度
        FusionRule(
            required_types=frozenset({TriggerType.HARDWARE_KEY}),
            base_confidence=0.75,
            description="硬件按键",
        ),
        # 外部设备（蓝牙/USB 连接）→ 中置信度
        FusionRule(
            required_types=frozenset({TriggerType.EXTERNAL_DEVICE}),
            base_confidence=0.65,
            description="外部设备连接事件",
        ),
    ]


# =============================================================================
# 融合决策结果
# =============================================================================

@dataclass
class FusedWakeResult:
    """融合决策结果"""
    should_wake: bool
    confidence: float
    matched_rule: Optional[str]
    trigger_events: List[Any]   # List[TriggerEvent]
    timestamp: float = field(default_factory=time.time)
    reason: str = ""

    def to_dict(self) -> Dict:
        return {
            "should_wake": self.should_wake,
            "confidence": self.confidence,
            "matched_rule": self.matched_rule,
            "trigger_count": len(self.trigger_events),
            "timestamp": self.timestamp,
            "reason": self.reason,
        }


# =============================================================================
# 多模态融合唤醒决策器
# =============================================================================

class FusedWakeDecision:
    """
    多模态融合唤醒决策器

    在时间窗口内聚合多个硬件触发器事件，
    根据触发器组合计算融合置信度，决定是否真正唤醒系统。

    用法示例::

        fused = FusedWakeDecision(wake_threshold=0.7)

        # 注册为 HardwareTriggerManager 的回调
        trigger_manager.on_trigger = fused.on_trigger_event

        # 注册唤醒决策回调
        async def handle_wake(result: FusedWakeResult):
            if result.should_wake:
                await wake_router.route(wake_event)

        fused.set_wake_callback(handle_wake)
    """

    # 默认时间窗口（秒）：窗口内的触发器事件视为同一次交互
    DEFAULT_WINDOW_SECONDS: float = 2.0
    # 默认唤醒置信度阈值
    DEFAULT_WAKE_THRESHOLD: float = 0.65

    def __init__(
        self,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        wake_threshold: float = DEFAULT_WAKE_THRESHOLD,
        custom_rules: Optional[List[FusionRule]] = None,
    ):
        """
        Args:
            window_seconds: 聚合时间窗口（秒）
            wake_threshold: 唤醒置信度阈值，超过该值才触发唤醒
            custom_rules: 自定义融合规则，若为 None 则使用默认规则
        """
        self.window_seconds = window_seconds
        self.wake_threshold = wake_threshold
        self._rules: List[FusionRule] = (
            custom_rules if custom_rules is not None else _build_default_rules()
        )
        # 排序：base_confidence 降序，优先匹配高置信度规则
        self._rules.sort(key=lambda r: r.base_confidence, reverse=True)

        # 当前时间窗口内的事件缓冲区（device_id → events）
        self._window_events: List[Any] = []
        self._window_start: float = 0.0

        # 唤醒决策回调
        self._on_wake: Optional[Callable[[FusedWakeResult], Any]] = None
        # 决策历史
        self._decision_history: List[FusedWakeResult] = []
        self._max_history: int = 200

        # 用于 asyncio 场景的事件队列
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._processing_task: Optional[asyncio.Task] = None

        logger.info(
            f"FusedWakeDecision initialized: window={window_seconds}s "
            f"threshold={wake_threshold} rules={len(self._rules)}"
        )

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def set_wake_callback(self, callback: Callable[[FusedWakeResult], Any]):
        """设置唤醒决策完成后的回调函数"""
        self._on_wake = callback

    def on_trigger_event(self, event: Any):
        """
        同步接口：作为 HardwareTriggerManager.on_trigger 的回调

        将事件放入异步队列，由后台任务统一处理。
        """
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("[FusedWakeDecision] 事件队列已满，丢弃事件")

    async def process_event(self, event: Any) -> Optional[FusedWakeResult]:
        """
        异步接口：直接处理单个触发器事件

        将事件加入当前时间窗口，然后尝试评估是否应当唤醒。

        Returns:
            若触发唤醒决策则返回 FusedWakeResult，否则返回 None
        """
        now = time.time()

        # 时间窗口重置：若上一次事件距今超过窗口时间，清空缓冲区
        if now - self._window_start > self.window_seconds:
            self._window_events = []
            self._window_start = now

        self._window_events.append(event)
        logger.debug(
            f"[FusedWakeDecision] 事件入窗口: type={getattr(event, 'trigger_type', '?')} "
            f"window_size={len(self._window_events)}"
        )

        # 尝试计算融合置信度
        result = self._evaluate(self._window_events)
        if result is None:
            return None

        # 记录历史
        self._decision_history.append(result)
        if len(self._decision_history) > self._max_history:
            self._decision_history = self._decision_history[-self._max_history:]

        if result.should_wake:
            # 清空时间窗口，防止同一批事件触发多次唤醒
            self._window_events = []
            self._window_start = 0.0

        logger.info(
            f"[FusedWakeDecision] 决策: should_wake={result.should_wake} "
            f"confidence={result.confidence:.2f} rule='{result.matched_rule}' "
            f"reason='{result.reason}'"
        )

        # 触发回调
        if self._on_wake:
            try:
                cb_result = self._on_wake(result)
                if asyncio.iscoroutine(cb_result):
                    await cb_result
            except Exception as e:
                logger.error(f"[FusedWakeDecision] 唤醒回调异常: {e}")

        return result

    async def start_processing_loop(self):
        """启动后台事件处理循环（消费 on_trigger_event 放入的事件）"""
        logger.info("[FusedWakeDecision] 启动事件处理循环")
        while True:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                await self.process_event(event)
            except asyncio.TimeoutError:
                # 超时检查：清理过期窗口
                self._maybe_expire_window()
            except asyncio.CancelledError:
                logger.info("[FusedWakeDecision] 事件处理循环已停止")
                break
            except Exception as e:
                logger.error(f"[FusedWakeDecision] 处理循环异常: {e}")

    def get_decision_history(self, limit: int = 50) -> List[Dict]:
        """获取决策历史记录"""
        return [d.to_dict() for d in self._decision_history[-limit:]]

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _evaluate(self, events: List[Any]) -> Optional[FusedWakeResult]:
        """
        根据当前时间窗口内的事件计算融合置信度，并决定是否唤醒

        Returns:
            FusedWakeResult，若置信度超过阈值则 should_wake=True
        """
        if not events:
            return None

        present_types = frozenset(
            getattr(e, "trigger_type", None) for e in events
            if getattr(e, "trigger_type", None) is not None
        )

        # 匹配最高置信度的规则
        best_rule: Optional[FusionRule] = None
        best_confidence: float = 0.0

        for rule in self._rules:
            if not rule.required_types.issubset(present_types):
                continue
            # 计算可选触发器加成
            optional_matched = len(rule.optional_types & present_types)
            confidence = rule.base_confidence + optional_matched * rule.optional_bonus
            confidence = min(confidence, 1.0)
            if confidence > best_confidence:
                best_confidence = confidence
                best_rule = rule
                if confidence >= 0.99:
                    break  # 不可能更高了

        if best_rule is None:
            # 没有规则匹配，默认最低置信度
            best_confidence = 0.3
            rule_desc = "无规则匹配"
        else:
            rule_desc = best_rule.description

        should_wake = best_confidence >= self.wake_threshold

        # 防误唤醒检查
        if should_wake and self._is_false_positive(events):
            best_confidence *= 0.4  # 大幅降低置信度
            should_wake = best_confidence >= self.wake_threshold
            rule_desc = f"防误唤醒修正: {rule_desc}"

        return FusedWakeResult(
            should_wake=should_wake,
            confidence=best_confidence,
            matched_rule=rule_desc,
            trigger_events=list(events),
            reason=(
                f"confidence={best_confidence:.2f} threshold={self.wake_threshold:.2f}"
            ),
        )

    def _is_false_positive(self, events: List[Any]) -> bool:
        """
        防误唤醒：检测是否为电视/广播等背景音源

        启发式规则：
        - 仅有 VOICE 类型事件，且没有任何其他传感器事件
        - 事件来源标记为 "background" 或置信度极低
        """
        # 如果只有一个事件且是 VOICE 类型
        if len(events) != 1:
            return False
        event = events[0]
        if TriggerType is not None and getattr(event, "trigger_type", None) != TriggerType.VOICE:
            return False
        # 检查事件数据中是否有低置信度标记
        data = getattr(event, "data", {}) or {}
        voice_confidence = data.get("confidence", 1.0)
        source = data.get("source", "")
        if voice_confidence < 0.3 or "background" in str(source).lower():
            return True
        return False

    def _maybe_expire_window(self):
        """检查并过期超时的时间窗口"""
        if self._window_events and time.time() - self._window_start > self.window_seconds * 2:
            logger.debug("[FusedWakeDecision] 时间窗口过期，清空缓冲区")
            self._window_events = []
            self._window_start = 0.0


# 模块级单例（可被 hardware_trigger.py 直接使用）
fused_wake_decision = FusedWakeDecision()

__all__ = [
    "FusedWakeDecision",
    "FusedWakeResult",
    "FusionRule",
    "fused_wake_decision",
]
