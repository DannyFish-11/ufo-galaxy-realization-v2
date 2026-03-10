"""EventBridge wire() 连接验证和事件类型完整性测试"""

import pytest
import logging


class TestEventTypeCompleteness:
    """验证 EventBridge 引用的所有事件类型在 EventType 枚举中存在"""

    def test_all_bridge_event_types_exist(self):
        from integration.event_bus import EventType

        required = [
            "DEVICE_CONNECTED",
            "DEVICE_DISCONNECTED",
            "DEVICE_REGISTERED",
            "DEVICE_UNREGISTERED",
            "DEVICE_HEARTBEAT",
            "COMMAND_RESULT",
            "COMMAND_PROGRESS",
            "COMMAND_DISPATCHED",
            "ORCHESTRATION_STARTED",
            "ORCHESTRATION_COMPLETED",
            "ORCHESTRATION_PROGRESS",
            "TASK_COMPLETED",
            "ERROR_OCCURRED",
            "SESSION_MIGRATED",
            "SESSION_CREATED",
            "SESSION_CLOSED",
        ]
        for name in required:
            assert hasattr(EventType, name), f"EventType.{name} missing"

    def test_event_bus_singleton(self):
        from integration.event_bus import event_bus, EventBus
        assert isinstance(event_bus, EventBus)


@pytest.mark.asyncio
class TestEventBridgeWire:
    """验证 EventBridge.wire() 不会崩溃"""

    async def test_wire_idempotent(self):
        """wire() 调用两次不应报错"""
        from core.event_bridge import EventBridge
        bridge = EventBridge()
        await bridge.wire()
        await bridge.wire()  # 第二次应为 no-op

    async def test_wire_completes_without_error(self):
        """wire() 应在所有服务不可用时仍能完成（graceful degradation）"""
        from core.event_bridge import EventBridge
        bridge = EventBridge.__new__(EventBridge)
        bridge._wired = False
        bridge.logger = logging.getLogger("test_bridge")
        # Should not raise even if services are unavailable
        await bridge.wire()
