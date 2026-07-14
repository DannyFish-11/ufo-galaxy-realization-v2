"""tests/test_presence_bridge_ambient.py
==========================================

GalaxyPresenceBridge 把 StateEventBus 的自发注意力事件转成面板消息。

同时锁定一个此前潜伏的真 bug：bridge.start() 里用的是
``StateEventBus.get_instance()`` —— 这个 classmethod 根本不存在（单例入口是
模块级 ``get_state_event_bus()``）。于是 start() 每次都在这里抛 AttributeError
被 except 吞掉，桥【从未真正订阅到任何事件】。修复后订阅生效，ambient 事件才
能流到面板。
"""

from __future__ import annotations

import asyncio

import pytest

from core.lumiv_websocket_bridge import GalaxyPresenceBridge
from core.state_event_bus import get_state_event_bus


def _fresh_bridge():
    # 每个用例用干净单例，避免跨用例状态残留。
    GalaxyPresenceBridge._instance = None
    b = GalaxyPresenceBridge.get_instance()
    # 抑制真实 IPC/WS 广播（无 Electron、无客户端）——只验证内部状态与消息构建。
    b._try_ipc_http = lambda msg: _async_false()  # type: ignore[assignment]
    return b


async def _async_false():
    return False


class TestBridgeSubscriptionFix:
    def test_start_actually_subscribes(self):
        """start() 后，事件总线上必须真的多出订阅者（证明不再抛 get_instance）。"""

        async def run():
            bus = get_state_event_bus()
            before = bus.subscriber_count("ambient.decision")
            b = _fresh_bridge()
            await b.start()
            after = bus.subscriber_count("ambient.decision")
            return before, after

        before, after = asyncio.run(run())
        assert after > before, "bridge.start() 没有真正订阅 ambient.decision"


class TestAmbientToMessage:
    def test_observed_then_decision_flow_into_message(self):
        async def run():
            b = _fresh_bridge()
            await b.start()
            bus = get_state_event_bus()
            bus.publish(
                "ambient.observed", source="ambient_attention_loop", payload={"has_frame": True, "has_audio": True}
            )
            bus.publish(
                "ambient.decision",
                source="ambient_attention_loop",
                payload={"action": "speak", "rationale": "用户回来了", "utterance": "欢迎回来"},
            )
            await asyncio.sleep(0.05)
            return b._build_message()

        msg = asyncio.run(run())
        amb = msg["payload"]["ambient"]
        assert amb["seeing"] is True and amb["hearing"] is True
        assert amb["action"] == "speak"
        assert "回来" in amb["rationale"]

    def test_delegate_decision(self):
        async def run():
            b = _fresh_bridge()
            await b.start()
            bus = get_state_event_bus()
            bus.publish(
                "ambient.decision",
                source="ambient_attention_loop",
                payload={"action": "delegate", "task": "查错误日志"},
            )
            await asyncio.sleep(0.05)
            return b._build_message()

        amb = asyncio.run(run())["payload"]["ambient"]
        assert amb["action"] == "delegate"
        assert "日志" in amb["rationale"]

    def test_payload_of_handles_event_and_dict(self):
        b = _fresh_bridge()
        from core.state_event_bus import StateEvent

        ev = StateEvent(type="ambient.decision", source="x", payload={"action": "silent"})
        assert b._payload_of(ev) == {"action": "silent"}
        assert b._payload_of({"action": "speak"}) == {"action": "speak"}
        assert b._payload_of(None) == {}
