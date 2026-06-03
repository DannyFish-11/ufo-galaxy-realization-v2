"""
Wake Event Bus - 统一唤醒事件总线

核心功能：
- 事件收集：从所有设备的 WebSocket 连接收集 WAKE_EVENT 消息
- 事件去重：同一时间窗口(500ms)内来自不同设备的相同唤醒词事件合并为一个
- 事件分发：将去重后的唤醒事件发送给 WakeRouter 进行路由决策
- 事件日志：记录所有唤醒事件用于分析和优化

Author: UFO Galaxy Team
Version: 1.0
"""

import asyncio
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any

logger = logging.getLogger("UFO-Galaxy.WakeEventBus")

# 导入 WakeRouter 类型（延迟导入避免循环引用）
# from galaxy_gateway.wake_router import WakeEvent, WakeTaskType, wake_router


# =============================================================================
# 数据模型
# =============================================================================

@dataclass
class RawWakeEvent:
    """
    从 WebSocket 或内部触发器收到的原始唤醒事件，
    尚未经过去重处理。
    """
    source_device_id: str
    wake_word: str
    timestamp: float = field(default_factory=time.time)
    task_type: str = "general"       # "voice" | "visual" | "general"
    confidence: float = 1.0
    extra: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# 唤醒事件总线
# =============================================================================

class WakeEventBus:
    """
    统一唤醒事件总线

    统一收集来自所有设备的唤醒事件，在 DEDUP_WINDOW_MS 毫秒内对相同唤醒词去重，
    然后将唯一事件转发给 WakeRouter 进行路由决策。
    """

    # 去重时间窗口（毫秒）
    DEDUP_WINDOW_MS: float = 500.0
    # 最大事件日志条数
    MAX_LOG_SIZE: int = 1000
    # 去重缓冲区最大条目数（防止无限增长）
    MAX_DEDUP_BUFFER_SIZE: int = 500
    # 去重缓冲区条目过期时间（毫秒）
    DEDUP_EXPIRY_MS: float = 30000.0  # 30秒

    def __init__(self):
        # 去重缓冲区：wake_word -> (first_timestamp_ms, event_id)
        self._dedup_buffer: Dict[str, tuple] = {}
        # 原始事件日志（包括被去重的）
        self._event_log: List[Dict] = []
        # 去重后分发的事件日志
        self._dispatched_log: List[Dict] = []
        # 额外的订阅者回调（除 WakeRouter 外）
        self._subscribers: List[Callable[[Any], Any]] = []
        # 线程池用于同步发布（单例模式，延迟创建）
        self._executor: Optional[ThreadPoolExecutor] = None
        # 保护 _executor 创建和 _dedup_buffer 操作的锁
        self._lock = threading.Lock()

        logger.info("WakeEventBus initialized")

    def _get_executor(self) -> ThreadPoolExecutor:
        """线程安全地获取或创建 ThreadPoolExecutor（单例模式）。"""
        if self._executor is None:
            with self._lock:
                # 双重检查，防止并发创建
                if self._executor is None:
                    self._executor = ThreadPoolExecutor(
                        max_workers=2, thread_name_prefix="wake_event_bus"
                    )
        return self._executor

    def shutdown(self):
        """关闭 ThreadPoolExecutor，释放线程资源。"""
        with self._lock:
            if self._executor is not None:
                self._executor.shutdown(wait=True)
                self._executor = None
                logger.info("WakeEventBus ThreadPoolExecutor shut down")

    def __del__(self):
        """析构时确保关闭 executor。"""
        try:
            self.shutdown()
        except Exception:
            pass

    def _cleanup_dedup_buffer(self):
        """定期清理过期的去重缓冲区条目，防止无限增长。"""
        with self._lock:
            now_ms = time.time() * 1000
            # 使用 list() 复制后再遍历，避免在迭代时修改字典
            expired_keys = [
                key for key, (ts_ms, _) in list(self._dedup_buffer.items())
                if now_ms - ts_ms > self.DEDUP_EXPIRY_MS
            ]
            for key in expired_keys:
                del self._dedup_buffer[key]
            # 如果缓冲区仍超出最大限制，移除最旧的条目
            if len(self._dedup_buffer) > self.MAX_DEDUP_BUFFER_SIZE:
                sorted_items = sorted(self._dedup_buffer.items(), key=lambda x: x[1][0])
                to_remove = len(self._dedup_buffer) - self.MAX_DEDUP_BUFFER_SIZE
                for key, _ in sorted_items[:to_remove]:
                    del self._dedup_buffer[key]

    # ------------------------------------------------------------------
    # 事件提交接口
    # ------------------------------------------------------------------

    async def publish(self, raw_event: RawWakeEvent) -> bool:
        """
        发布原始唤醒事件

        1. 记录到日志
        2. 去重检查
        3. 转换并转发给 WakeRouter

        Args:
            raw_event: 原始唤醒事件

        Returns:
            True 表示事件已分发（未被去重），False 表示被去重丢弃
        """
        # 记录原始事件
        self._log_raw(raw_event)

        # 清理过期去重条目，防止无限增长
        self._cleanup_dedup_buffer()

        # 去重检查
        now_ms = time.time() * 1000
        key = raw_event.wake_word.strip().lower()

        if key in self._dedup_buffer:
            last_ts_ms, existing_event_id = self._dedup_buffer[key]
            if now_ms - last_ts_ms < self.DEDUP_WINDOW_MS:
                logger.debug(
                    f"[WakeEventBus] 事件去重: wake_word='{raw_event.wake_word}' "
                    f"from device={raw_event.source_device_id} "
                    f"elapsed_ms={now_ms - last_ts_ms:.1f}"
                )
                return False

        # 记录去重时间戳
        event_id = str(uuid.uuid4())[:8]
        self._dedup_buffer[key] = (now_ms, event_id)

        # 转换为 WakeEvent 并路由
        wake_event = self._to_wake_event(raw_event, event_id)
        await self._dispatch(wake_event)
        return True

    def publish_sync(self, raw_event: RawWakeEvent):
        """
        同步接口（兼容非异步调用方），使用线程池或 asyncio.create_task 调度
        """
        try:
            loop = asyncio.get_running_loop()
            if loop.is_running():
                # 事件循环正在运行，使用 create_task 调度
                loop.create_task(self.publish(raw_event))
            else:
                # 事件循环存在但未运行，使用线程池提交
                self._get_executor().submit(asyncio.run, self.publish(raw_event))
        except RuntimeError:
            # 没有 event loop，在线程池中运行
            self._get_executor().submit(asyncio.run, self.publish(raw_event))

    # ------------------------------------------------------------------
    # 从 WebSocket 消息解析并发布
    # ------------------------------------------------------------------

    async def handle_websocket_message(
        self,
        device_id: str,
        message: Dict[str, Any],
    ) -> bool:
        """
        处理来自 WebSocket 的消息，若为 WAKE_EVENT 类型则发布到总线

        Args:
            device_id: 发送消息的设备 ID
            message: 解析后的消息字典

        Returns:
            True 表示是 WAKE_EVENT 且已处理
        """
        msg_type = message.get("type", "")
        if msg_type not in ("WAKE_EVENT", "wake_event"):
            return False

        payload = message.get("payload", {})
        wake_word = payload.get("wake_word", "")
        if not wake_word:
            logger.warning(f"[WakeEventBus] WAKE_EVENT 缺少 wake_word: device={device_id}")
            return False

        raw = RawWakeEvent(
            source_device_id=device_id,
            wake_word=wake_word,
            timestamp=message.get("timestamp", time.time()),
            task_type=payload.get("task_type", "general"),
            confidence=payload.get("confidence", 1.0),
            extra=payload.get("extra", {}),
        )
        await self.publish(raw)
        return True

    # ------------------------------------------------------------------
    # 订阅者管理
    # ------------------------------------------------------------------

    def subscribe(self, callback: Callable[[Any], Any]):
        """
        添加订阅者，在每次分发唤醒事件时调用

        callback 签名: (wake_event: WakeEvent) -> Any
        """
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Any], Any]):
        """移除订阅者"""
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _to_wake_event(self, raw: RawWakeEvent, event_id: str) -> Any:
        """将 RawWakeEvent 转换为 WakeEvent"""
        try:
            from galaxy_gateway.wake_router import WakeEvent, WakeTaskType
            task_type_map = {
                "voice": WakeTaskType.VOICE,
                "visual": WakeTaskType.VISUAL,
                "general": WakeTaskType.GENERAL,
            }
            task_type = task_type_map.get(raw.task_type, WakeTaskType.GENERAL)
            return WakeEvent(
                event_id=event_id,
                source_device_id=raw.source_device_id,
                wake_word=raw.wake_word,
                timestamp=raw.timestamp,
                task_type=task_type,
                confidence=raw.confidence,
                extra=raw.extra,
            )
        except ImportError:
            # Fallback：返回 RawWakeEvent 本身
            return raw

    async def _dispatch(self, wake_event: Any):
        """将唤醒事件分发给 WakeRouter 和其他订阅者"""
        # 记录分发日志
        event_dict = (
            wake_event.to_dict()
            if hasattr(wake_event, "to_dict")
            else {"source_device_id": getattr(wake_event, "source_device_id", "unknown")}
        )
        self._dispatched_log.append(event_dict)
        if len(self._dispatched_log) > self.MAX_LOG_SIZE:
            self._dispatched_log = self._dispatched_log[-self.MAX_LOG_SIZE:]

        logger.info(
            f"[WakeEventBus] 分发唤醒事件: wake_word='{getattr(wake_event, 'wake_word', '?')}' "
            f"from device={getattr(wake_event, 'source_device_id', '?')}"
        )

        # 转发给 WakeRouter
        try:
            from galaxy_gateway.wake_router import wake_router
            await wake_router.route(wake_event)
        except Exception as e:
            logger.error(f"[WakeEventBus] WakeRouter 路由失败: {e}")

        # 通知其他订阅者
        for subscriber in self._subscribers:
            try:
                result = subscriber(wake_event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"[WakeEventBus] 订阅者回调异常: {e}")

    def _log_raw(self, raw: RawWakeEvent):
        """记录原始事件到日志"""
        entry = {
            "source_device_id": raw.source_device_id,
            "wake_word": raw.wake_word,
            "timestamp": raw.timestamp,
            "task_type": raw.task_type,
            "confidence": raw.confidence,
        }
        self._event_log.append(entry)
        if len(self._event_log) > self.MAX_LOG_SIZE:
            self._event_log = self._event_log[-self.MAX_LOG_SIZE:]

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def get_event_log(self, limit: int = 100) -> List[Dict]:
        """获取原始事件日志（包含被去重的）"""
        return self._event_log[-limit:]

    def get_dispatched_log(self, limit: int = 100) -> List[Dict]:
        """获取已分发事件日志（去重后）"""
        return self._dispatched_log[-limit:]

    def clear_dedup_buffer(self):
        """手动清除去重缓冲区"""
        self._dedup_buffer.clear()

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            "total_received": len(self._event_log),
            "total_dispatched": len(self._dispatched_log),
            "total_deduplicated": len(self._event_log) - len(self._dispatched_log),
            "dedup_buffer_size": len(self._dedup_buffer),
        }


# 模块级单例
wake_event_bus = WakeEventBus()

__all__ = [
    "WakeEventBus",
    "RawWakeEvent",
    "wake_event_bus",
]
