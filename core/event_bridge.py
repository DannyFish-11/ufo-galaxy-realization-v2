"""
UFO Galaxy - 事件桥接层
========================

将独立的核心子系统通过事件总线连接成一个有机整体。

连接：
  EventBus <─────> CommandRouter
  EventBus <─────> Monitoring (Alerts / CircuitBreaker)
  EventBus <─────> AI Intent Parser
  EventBus <─────> PerformanceMonitor
  EventBus <─────> WebSocket ConnectionManager

每个子系统既是事件发布者、也是事件订阅者。
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("UFO-Galaxy.EventBridge")


class EventBridge:
    """
    事件桥接器

    在 bootstrap 阶段调用 wire()，
    将所有子系统通过事件总线粘合在一起。
    """

    def __init__(self):
        self._wired = False
        self._cleanup_task: Optional[asyncio.Task] = None

    async def wire(self):
        """
        连接所有子系统到事件总线

        幂等：多次调用安全。
        """
        if self._wired:
            return
        self._wired = True

        try:
            from integration.event_bus import event_bus, EventType, UIGalaxyEvent
        except ImportError:
            logger.info("event_bus 模块不可用，跳过事件桥接")
            return

        # ====================================================================
        # 1. CommandRouter → EventBus
        # ====================================================================
        try:
            from core.command_router import get_command_router

            cmd_router = get_command_router()

            # 保存原始回调
            _original_on_status = cmd_router._on_status_change

            async def _cmd_to_event_bus(cmd_result):
                """命令结果 → 事件总线"""
                try:
                    event_bus.publish_sync(
                        EventType.COMMAND_RESULT,
                        source="command_router",
                        data={
                            "request_id": cmd_result.request_id,
                            "status": cmd_result.status.value,
                            "total_latency_ms": cmd_result.total_latency_ms,
                            "targets": list(cmd_result.targets.keys()),
                        },
                    )
                except Exception as pub_err:
                    logger.warning(f"EventBridge: 发布命令结果事件失败: {pub_err}")

                # 链式调用原有回调（WebSocket 推送）
                if _original_on_status:
                    try:
                        if asyncio.iscoroutinefunction(_original_on_status):
                            await _original_on_status(cmd_result)
                        elif asyncio.iscoroutine(_original_on_status):
                            await _original_on_status
                        else:
                            _original_on_status(cmd_result)
                    except Exception as cb_err:
                        logger.warning(f"EventBridge: 原始回调执行失败: {cb_err}")

            cmd_router._on_status_change = _cmd_to_event_bus
            logger.info("EventBridge: CommandRouter → EventBus 已连接")
        except Exception as e:
            logger.warning(f"EventBridge: CommandRouter 连接失败: {e}")

        # ====================================================================
        # 2. Monitoring Alerts → EventBus
        # ====================================================================
        try:
            from core.monitoring import get_monitoring_manager, AlertSeverity

            monitoring = get_monitoring_manager()

            _original_on_alert = monitoring.alerts._on_alert

            async def _alert_to_event_bus(alert):
                """告警 → 事件总线"""
                try:
                    event_bus.publish_sync(
                        EventType.PERFORMANCE_ALERT,
                        source="monitoring",
                        data={
                            "alert_id": alert.alert_id,
                            "severity": alert.severity.value,
                            "component": alert.component,
                            "message": alert.message,
                        },
                    )
                except Exception as pub_err:
                    logger.warning(f"EventBridge: 发布告警事件失败: {pub_err}")

                if _original_on_alert:
                    try:
                        if asyncio.iscoroutinefunction(_original_on_alert):
                            await _original_on_alert(alert)
                        else:
                            _original_on_alert(alert)
                    except Exception as cb_err:
                        logger.warning(f"EventBridge: 原始告警回调失败: {cb_err}")

            monitoring.alerts._on_alert = _alert_to_event_bus
            logger.info("EventBridge: Monitoring Alerts → EventBus 已连接")
        except Exception as e:
            logger.warning(f"EventBridge: Monitoring 连接失败: {e}")

        # ====================================================================
        # 3. EventBus → CommandRouter (COMMAND_RECEIVED → dispatch)
        # ====================================================================
        try:
            from core.command_router import (
                get_command_router, CommandRequest, CommandMode,
            )

            async def _event_to_command(event: UIGalaxyEvent):
                """事件总线命令 → CommandRouter dispatch"""
                data = event.data
                if not data.get("command"):
                    return

                cmd_req = CommandRequest(
                    source=f"event_bus:{event.source}",
                    targets=data.get("targets", ["system"]),
                    command=data["command"],
                    params=data.get("params", {}),
                    mode=CommandMode(data.get("mode", "async")),
                )
                router = get_command_router()
                await router.dispatch(cmd_req)

            event_bus.subscribe(EventType.COMMAND_RECEIVED, _event_to_command, async_callback=True)
            logger.info("EventBridge: EventBus COMMAND_RECEIVED → CommandRouter 已连接")
        except Exception as e:
            logger.warning(f"EventBridge: COMMAND_RECEIVED 连接失败: {e}")

        # ====================================================================
        # 4. EventBus → AI Intent (GOAL_SUBMITTED → IntentParser)
        # ====================================================================
        try:
            from core.ai_intent import get_intent_parser

            async def _goal_to_intent(event: UIGalaxyEvent):
                """用户目标 → AI 意图解析"""
                text = event.data.get("goal_description", "")
                if not text:
                    return

                parser = get_intent_parser()
                parsed = await parser.parse(text)

                # 发布解析结果
                event_bus.publish_sync(
                    EventType.AI_INTENT_PARSED,
                    source="ai_intent",
                    data=parsed.to_dict(),
                )

            event_bus.subscribe(EventType.GOAL_SUBMITTED, _goal_to_intent, async_callback=True)
            logger.info("EventBridge: EventBus GOAL_SUBMITTED → AI Intent 已连接")
        except Exception as e:
            logger.warning(f"EventBridge: GOAL_SUBMITTED 连接失败: {e}")

        # ====================================================================
        # 5. Slow request → Monitoring Alert
        # ====================================================================
        try:
            from core.monitoring import get_monitoring_manager, AlertSeverity

            async def _perf_alert_handler(event: UIGalaxyEvent):
                """性能告警 → Monitoring Alert"""
                monitoring = get_monitoring_manager()
                monitoring.alerts.fire(
                    AlertSeverity.WARNING,
                    event.data.get("component", "performance"),
                    event.data.get("message", "Performance alert"),
                )

            event_bus.subscribe(EventType.PERFORMANCE_ALERT, _perf_alert_handler, async_callback=True)
        except Exception:
            pass

        # ====================================================================
        # 6. 启动事件总线 + 周期清理任务
        # ====================================================================
        await event_bus.start()
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

        logger.info("EventBridge: 所有连接已建立，事件总线已启动")

    async def _periodic_cleanup(self):
        """周期性清理任务：命令结果 + 缓存过期条目 + 限流窗口"""
        while True:
            try:
                await asyncio.sleep(300)  # 每 5 分钟

                # 清理过期命令结果
                try:
                    from core.command_router import get_command_router
                    router = get_command_router()
                    await router.cleanup(max_age_seconds=3600)
                except Exception:
                    pass

                # 清理事件历史
                try:
                    from integration.event_bus import event_bus
                    history = event_bus.get_event_history()
                    if len(history) > 800:
                        event_bus.clear_history()
                except Exception:
                    pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Periodic cleanup error: {e}")

    async def shutdown(self):
        """关闭事件桥接"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        try:
            from integration.event_bus import event_bus
            await event_bus.stop()
        except Exception:
            pass

        logger.info("EventBridge: 已关闭")


# 全局实例
_event_bridge: Optional[EventBridge] = None


def get_event_bridge() -> EventBridge:
    """获取全局事件桥接器"""
    global _event_bridge
    if _event_bridge is None:
        _event_bridge = EventBridge()
    return _event_bridge
