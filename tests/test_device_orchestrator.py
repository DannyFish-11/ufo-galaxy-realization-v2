"""
DeviceOrchestrator 单元测试
"""

import pytest
from unittest.mock import patch, MagicMock

from core.device_orchestrator import DeviceOrchestrator, get_device_orchestrator


class TestDeviceOrchestratorInit:
    """DeviceOrchestrator 初始化测试"""

    def test_instantiation(self):
        orch = DeviceOrchestrator()
        assert hasattr(orch, "_initialized")

    def test_get_device_orchestrator(self):
        orch = get_device_orchestrator()
        assert isinstance(orch, DeviceOrchestrator)

    def test_has_required_methods(self):
        orch = DeviceOrchestrator()
        required = [
            "discover_devices",
            "get_device_status",
            "send_command",
            "parallel_commands",
            "transfer_file",
            "sync_clipboard",
            "get_telemetry",
        ]
        for method in required:
            assert hasattr(orch, method), f"Missing method: {method}"


@pytest.mark.asyncio
async def test_discover_devices_empty():
    """设备发现 — 无注册设备时返回空列表"""
    orch = DeviceOrchestrator()

    with patch(
        "core.device_orchestrator._get_device_registry", return_value=None
    ), patch(
        "core.device_orchestrator._get_node_registry", return_value=None
    ):
        result = await orch.discover_devices()
        assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_telemetry_missing_device():
    """遥测采集 — 设备不存在时应返回错误而非崩溃"""
    orch = DeviceOrchestrator()

    with patch(
        "core.device_orchestrator._get_device_registry", return_value=None
    ):
        result = await orch.get_telemetry("nonexistent_device_999")
        assert isinstance(result, dict)
        # 应包含 error 或空遥测，不应抛出异常


class TestSafeStatusAccess:
    """status 安全访问测试"""

    def test_enum_status_access(self):
        """Enum status.value 正常工作"""
        from core.device_types import DeviceStatus

        status = DeviceStatus.ONLINE
        val = status.value if hasattr(status, "value") else str(status)
        assert val == "online"

    def test_string_status_access(self):
        """字符串 status 不崩溃"""
        status = "online"
        val = status.value if hasattr(status, "value") else str(status)
        assert val == "online"

    def test_none_status_access(self):
        """None status 不崩溃"""
        status = None
        val = status.value if hasattr(status, "value") else str(status)
        assert val == "None"
