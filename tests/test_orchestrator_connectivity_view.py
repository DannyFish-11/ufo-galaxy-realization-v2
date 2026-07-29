"""TaskOrchestrator 连通性视图的行为回归锁。

锁定的真实缺陷(修复前 100% 复现):

``galaxy_gateway/bootstrap/lifecycle.py`` 会完整装配一个 ``WebSocketManager``
并 ``start()`` 它,再注入 ``TaskOrchestrator``、写进 ``app.state``;
``galaxy_gateway/routes/tasks.py`` 则把 orchestrator 的任务端点对外暴露。

但这个 WebSocketManager 的 ``connections`` 永远是空的 —— 唯一调用
``WebSocketManager.connect()`` 的是同文件的 ``handle_connection()``
(``galaxy_gateway/transport/websocket_server.py:209``),而 PR-25 之后所有设备
WS 入口都收敛到 ``routes/websocket.py::_handle_android_ws`` → ``android_bridge``
(见该文件 162-228 行的 ``register_websocket_routes``),没有任何路由再调用
``handle_connection``。

于是修复前:
  * ``get_connected_devices()`` 恒为 ``[]``
  * ``is_device_connected()`` 恒为 ``False``
  * ``_select_device()`` 对**任何**任务都返回 ``None``
  * ``broadcast_command()`` 永远广播给零台设备

而且设备类型偏好那段挂在 ``hasattr(websocket_manager, "get_device_type")`` 上,
WebSocketManager 从来没有这个方法,所以"安卓/手机/windows/桌面"关键词偏好
也是死代码。

正确修法不是把 ``handle_connection`` 挂成第二个 ingress(违反 PR-25
"exactly one canonical ingress"),而是让编排器读权威在线视图(UDM),
并与传输层视图取并集 —— 后者保证注入假 manager 的既有测试仍然有效。
"""

from __future__ import annotations

import asyncio

import pytest

from core.unified.device_manager import get_unified_device_manager
from core.unified.models import UnifiedDevice, UnifiedDeviceStatus, UnifiedDeviceType
from galaxy_gateway.handlers import DeviceManager, MessageHandler
from galaxy_gateway.orchestrator.task_orchestrator import Task, TaskOrchestrator
from galaxy_gateway.transport import WebSocketManager

ANDROID_ID = "test-conn-view-phone"
WINDOWS_ID = "test-conn-view-pc"


@pytest.fixture
def orchestrator_with_udm_devices():
    """真实的(即生产实况:connections 为空的)WebSocketManager + UDM 里两台在线设备。"""
    device_manager = DeviceManager()
    ws_manager = WebSocketManager()
    orch = TaskOrchestrator(device_manager, MessageHandler(device_manager), ws_manager)

    udm = get_unified_device_manager()
    for device_id, device_type in (
        (ANDROID_ID, UnifiedDeviceType.ANDROID),
        (WINDOWS_ID, UnifiedDeviceType.WINDOWS),
    ):
        udm.register_device(
            UnifiedDevice(
                device_id=device_id,
                name=device_id,
                device_type=device_type,
                status=UnifiedDeviceStatus.ONLINE,
            )
        )
    try:
        yield orch, ws_manager
    finally:
        for device_id in (ANDROID_ID, WINDOWS_ID):
            try:
                udm.unregister_device(device_id)
            except Exception:
                udm._devices.pop(device_id, None)


class TestTransportViewIsEmptyInProduction:
    """先把前提本身钉死:传输层视图确实是空的,不是测试环境的偶然。"""

    def test_websocket_manager_sees_no_devices(self, orchestrator_with_udm_devices):
        _orch, ws_manager = orchestrator_with_udm_devices
        assert ws_manager.get_connected_devices() == []
        assert ws_manager.is_device_connected(ANDROID_ID) is False

    def test_handle_connection_is_the_only_caller_of_connect(self):
        """若将来有人把 connect() 接到别处,这条会提醒重新评估上面的前提。"""
        import inspect

        from galaxy_gateway.transport import websocket_server

        source = inspect.getsource(websocket_server)
        # 只统计真正的调用点(self.connect(...)),不含定义本身
        assert source.count("self.connect(") == 1


class TestOrchestratorSeesAuthoritativeDevices:
    def test_connected_ids_include_udm_online_devices(self, orchestrator_with_udm_devices):
        orch, _ = orchestrator_with_udm_devices
        ids = orch._connected_device_ids()
        assert ANDROID_ID in ids
        assert WINDOWS_ID in ids

    def test_is_device_connected_falls_back_to_udm(self, orchestrator_with_udm_devices):
        orch, _ = orchestrator_with_udm_devices
        assert orch._is_device_connected(ANDROID_ID) is True
        assert orch._is_device_connected("device-that-does-not-exist") is False

    def test_select_device_no_longer_returns_none(self, orchestrator_with_udm_devices):
        """修复前这里必然是 None —— 这是本文件锁定的核心缺陷。"""
        orch, _ = orchestrator_with_udm_devices
        selected = asyncio.run(orch._select_device(Task(task_id="t", user_request="随便做点什么")))
        assert selected in {ANDROID_ID, WINDOWS_ID}

    def test_explicitly_assigned_device_is_honoured(self, orchestrator_with_udm_devices):
        orch, _ = orchestrator_with_udm_devices
        task = Task(task_id="t", user_request="随便做点什么")
        task.assigned_device = WINDOWS_ID
        assert asyncio.run(orch._select_device(task)) == WINDOWS_ID


class TestDeviceTypePreferenceActuallyApplies:
    """修复前这段是死代码(hasattr 守卫恒为 False),两条都会失败。"""

    def test_android_keyword_prefers_android_device(self, orchestrator_with_udm_devices):
        orch, _ = orchestrator_with_udm_devices
        task = Task(task_id="t", user_request="帮我在安卓手机上点一下")
        assert asyncio.run(orch._select_device(task)) == ANDROID_ID

    def test_windows_keyword_prefers_windows_device(self, orchestrator_with_udm_devices):
        orch, _ = orchestrator_with_udm_devices
        task = Task(task_id="t", user_request="在 windows 桌面打开记事本")
        assert asyncio.run(orch._select_device(task)) == WINDOWS_ID

    def test_device_type_resolves_from_udm(self, orchestrator_with_udm_devices):
        orch, _ = orchestrator_with_udm_devices
        assert orch._device_type_of(ANDROID_ID) == "android"
        assert orch._device_type_of(WINDOWS_ID) == "windows"
        assert orch._device_type_of("device-that-does-not-exist") is None


class TestInjectedTransportManagerStillWins:
    """并集语义:注入的假 manager 必须仍然有效,否则会打断既有测试的注入约定。"""

    def test_injected_manager_devices_are_included_and_ordered_first(self):
        class _FakeManager:
            def get_connected_devices(self):
                return ["injected-a", "injected-b"]

            def is_device_connected(self, device_id):
                return device_id in {"injected-a", "injected-b"}

            def get_device_type(self, device_id):
                return "android" if device_id == "injected-a" else "windows"

        device_manager = DeviceManager()
        orch = TaskOrchestrator(device_manager, MessageHandler(device_manager), _FakeManager())

        ids = orch._connected_device_ids()
        assert ids[:2] == ["injected-a", "injected-b"]
        assert orch._is_device_connected("injected-a") is True
        # manager 自带 get_device_type 时优先用它,不去查 UDM
        assert orch._device_type_of("injected-a") == "android"
        assert orch._device_type_of("injected-b") == "windows"

    def test_broken_transport_manager_degrades_to_udm(self, orchestrator_with_udm_devices):
        """传输层探测抛异常时不能整体崩掉,应退回权威视图。"""

        class _BrokenManager:
            def get_connected_devices(self):
                raise RuntimeError("transport exploded")

            def is_device_connected(self, device_id):
                raise RuntimeError("transport exploded")

        device_manager = DeviceManager()
        orch = TaskOrchestrator(device_manager, MessageHandler(device_manager), _BrokenManager())

        assert ANDROID_ID in orch._connected_device_ids()
        assert orch._is_device_connected(ANDROID_ID) is True
