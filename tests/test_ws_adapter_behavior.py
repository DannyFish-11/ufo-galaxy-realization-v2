"""tests/test_ws_adapter_behavior.py
====================================
``core/adapters/websocket_adapter.py`` 的行为测试。

为什么单开一个文件:这个适配器此前**全仓没有任何测试引用**,三个缺陷因此长期
存活 —— 投递失败被报成成功、可用性探测恒为假、兜底从一个不存在的模块取实例。
这里按【真实 producer 的签名】构造替身,锁定修复后的行为,避免同类回归。

真实签名依据(galaxy_gateway/transport/websocket_server.py):
    async def send_message(self, device_id: str, message: AIPMessage) -> bool   # :158
    def is_device_connected(self, device_id: str) -> bool                        # :337(同步)
"""

from __future__ import annotations

import asyncio

import pytest

from core.adapters.websocket_adapter import WebSocketAdapter


class _FakeManager:
    """按真实签名构造的替身:send_message 是 async->bool,is_device_connected 是同步。"""

    def __init__(self, deliver: bool = True, connected: bool = True) -> None:
        self._deliver = deliver
        self._connected = connected
        self.sent: list = []

    async def send_message(self, device_id, message):
        self.sent.append((device_id, message))
        return self._deliver

    def is_device_connected(self, device_id):
        return self._connected


class _AsyncConnectedManager:
    """将来若把 is_device_connected 改成 async,适配器应当仍然可用。"""

    async def is_device_connected(self, device_id):
        return True


def _run(coro):
    return asyncio.run(coro)


class TestSendReportsDeliveryTruthfully:
    """send() 必须如实反映 send_message 的返回值。"""

    def test_delivery_failure_is_not_reported_as_success(self):
        # 回归锁定:此前只 await 不看返回值,一律回 success=True —— 投递失败被当成
        # 成功,上层于是不重试、也不改走别的传输,消息无声丢失。
        adapter = WebSocketAdapter(_FakeManager(deliver=False))
        result = _run(adapter.send({"x": 1}, "dev1"))
        assert result["success"] is False
        assert "not delivered" in result["error"].lower()

    def test_successful_delivery_reports_success(self):
        adapter = WebSocketAdapter(_FakeManager(deliver=True))
        result = _run(adapter.send({"x": 1}, "dev1"))
        assert result["success"] is True
        assert result["via"] == "websocket"

    def test_message_actually_reaches_manager(self):
        mgr = _FakeManager(deliver=True)
        _run(WebSocketAdapter(mgr).send({"payload": "hello"}, "dev1"))
        assert mgr.sent == [("dev1", {"payload": "hello"})]

    def test_no_manager_reports_unavailable_not_success(self):
        result = _run(WebSocketAdapter().send({"x": 1}, "dev1"))
        assert result["success"] is False


class TestIsAvailableDoesNotAwaitSyncMethod:
    """is_device_connected 是同步方法,await 它会抛 TypeError 并被吞成 False。"""

    def test_connected_device_reports_available(self):
        # 回归锁定:此前写成 await ws.is_device_connected(...),
        # 抛 TypeError: object bool can't be used in 'await' expression,
        # 被 except 吞成 False —— 于是无论设备在不在线都报"不可用",选路时被跳过。
        adapter = WebSocketAdapter(_FakeManager(connected=True))
        assert _run(adapter.is_available("dev1")) is True

    def test_disconnected_device_reports_unavailable(self):
        adapter = WebSocketAdapter(_FakeManager(connected=False))
        assert _run(adapter.is_available("dev1")) is False

    def test_tolerates_future_async_implementation(self):
        # inspect.isawaitable 分支:将来把该方法改成 async 也不应退化。
        adapter = WebSocketAdapter(_AsyncConnectedManager())
        assert _run(adapter.is_available("dev1")) is True

    def test_no_manager_is_unavailable(self):
        assert _run(WebSocketAdapter().is_available("dev1")) is False


class TestInertWithoutExplicitInjection:
    """不显式注入 ws_manager 时保持惰性,且不触发任何隐式导入。"""

    def test_get_ws_returns_none_without_injection(self):
        # 原兜底 import 的 galaxy_gateway.connection_manager 根本不存在(ImportError
        # 被静默吞),等于兜底从未生效;后来改成解析真实 manager 又会把一个收不到
        # 连接的 manager 接上去(其 connect() 的唯一调用方全仓无人调用)。
        # 现契约:只认显式注入。
        assert WebSocketAdapter()._get_ws() is None

    def test_explicit_injection_is_used(self):
        mgr = _FakeManager()
        assert WebSocketAdapter(mgr)._get_ws() is mgr


@pytest.mark.parametrize("deliver,expected", [(True, True), (False, False)])
def test_send_success_flag_tracks_delivery(deliver, expected):
    adapter = WebSocketAdapter(_FakeManager(deliver=deliver))
    assert _run(adapter.send({"x": 1}, "d"))["success"] is expected
