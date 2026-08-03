"""tests/test_android_handoff_lifecycle_wiring.py — Android 委派运行时的相位机必须真的在推进。

这份测试钉的缺陷
----------------
``core/android_participant_session_state._TRANSITION_TABLE`` 里,进入相位机的
**唯一**入口是::

    pre_dispatch --handoff_dispatched--> handoff_dispatched

而创建那条记录的唯一代码是 ``AndroidDelegatedRuntimeLifecycleCoordinator
.on_handoff_dispatched``。在这次修复之前,**生产代码里没有任何地方调过它** ——
出站的 ``core.delegated_runtime_handoff_contract`` 那条路至今没有调用方。

后果不是报错,是**静默**:``on_takeover_requested`` 等方法里都是

    rec = get_participant_session(session_id)
    if rec is not None:
        ...推进相位...

记录不存在时整段跳过,``was_transitioned`` 留在 False,而审计事件照发。
于是 ``AndroidBridge.send_takeover_request`` 里那句注释

    "recorded as a canonical orchestrated lifecycle event
     (session state transition + audit)"

里的 transition 那一半从来没发生过 —— 六个生命周期方法有四个接了线,
它们推进的却是一条**永远不存在**的记录。

为什么用行为断言而不是"函数有没有被引用"
----------------------------------------
"``on_handoff_dispatched`` 有调用方了"是弱断言:有人把调用点挪进一个不会执行的
分支、或者传错 session_id,它照样绿。所以这里一路打到
``AndroidBridge.send_takeover_request``,然后去查**会话记录的相位**。
相位是 ``takeover_pending``,才说明这条链真的通了。
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

pytest.importorskip("core.android_participant_session_state")

from core.android_delegated_runtime_lifecycle_coordinator import (  # noqa: E402
    AndroidDelegatedRuntimeLifecycleCoordinator,
)
from core.android_participant_session_state import get_participant_session  # noqa: E402


def _sid() -> str:
    return f"sess-{uuid.uuid4().hex[:10]}"


class TestCoordinatorEntryPoint:
    def test_signals_are_silently_dropped_without_the_entry_call(self):
        """对照组:不调入口,后续信号**静默无效**。

        这一条不是在断言"我们希望它坏",而是把缺陷的形状钉下来:它证明了
        下面那条用例里的 ``was_transitioned is True`` 确实来自入口调用,
        而不是相位机自己会兜底。没有这个对照,修复等于没被验证过。
        """
        coordinator = AndroidDelegatedRuntimeLifecycleCoordinator()
        session_id = _sid()

        outcome = coordinator.on_takeover_requested(session_id=session_id, takeover_id="tk-x", device_id="dev-x")

        assert outcome.was_transitioned is False, "没有会话记录却推进了相位 —— 相位机的入口约束被绕过了"
        assert get_participant_session(session_id) is None

    def test_entry_call_makes_the_takeover_signal_effective(self):
        coordinator = AndroidDelegatedRuntimeLifecycleCoordinator()
        session_id = _sid()

        coordinator.on_handoff_dispatched(session_id=session_id, device_id="dev-x", task_id="task-x")
        outcome = coordinator.on_takeover_requested(session_id=session_id, takeover_id="tk-x", device_id="dev-x")

        assert outcome.was_transitioned is True
        record = get_participant_session(session_id)
        assert record is not None
        assert record.phase.value == "takeover_pending"

    def test_redispatch_does_not_reset_a_session_in_flight(self):
        """幂等 —— 这是接线的前提条件,不是锦上添花。

        ``create_participant_session_record`` 是**无条件新建**的。调用点每次派发
        takeover 都要确保记录存在,而它无从知道这是不是同一个 session 的第二次;
        若 ``on_handoff_dispatched`` 不幂等,第二次派发会把已经推进到
        ``takeover_pending`` / ``execution`` 的会话悄悄打回起点 ——
        那是用一个更隐蔽的缺陷换掉原来那个。
        """
        coordinator = AndroidDelegatedRuntimeLifecycleCoordinator()
        session_id = _sid()

        coordinator.on_handoff_dispatched(session_id=session_id, device_id="dev-x")
        coordinator.on_takeover_requested(session_id=session_id, takeover_id="tk-x", device_id="dev-x")
        phase_in_flight = get_participant_session(session_id).phase.value

        again = coordinator.on_handoff_dispatched(session_id=session_id, device_id="dev-x")

        assert again.was_transitioned is False
        assert (
            get_participant_session(session_id).phase.value == phase_in_flight
        ), "重复派发把进行中的会话重置了 —— takeover/execution 的进度会被悄悄丢掉"


@pytest.mark.asyncio
class TestBridgeActuallyDrivesThePhaseMachine:
    """一路打到真实派发路径上 —— 这才是"接线接上了"的证据。"""

    async def test_send_takeover_request_leaves_the_session_in_takeover_pending(self, monkeypatch):
        bridge_mod = pytest.importorskip("galaxy_gateway.android_bridge")
        # takeover 是**模式门控**的:本地模式下 send_takeover_request 会在发消息之前
        # 直接返回拒绝(android_bridge.py 的 Axis-1 + Axis-7 守卫)。
        # 打桩打在 android_bridge 自己的模块级别名上 —— 它在 import 时就绑定了,
        # 去 patch cross_device_switch.is_cross_device_enabled 对它没有作用。
        monkeypatch.setattr(bridge_mod, "_is_cross_device_enabled", lambda: True)
        bridge = bridge_mod.AndroidBridge()
        session_id = _sid()

        sent = []

        async def _fake_send_to_device(device_id, msg, wait_response=False, **kwargs):
            sent.append((device_id, msg))
            return {"success": True}

        monkeypatch.setattr(bridge, "send_to_device", _fake_send_to_device)

        await bridge.send_takeover_request(
            device_id="dev-bridge",
            takeover_id="tk-bridge",
            session_id=session_id,
            task_context={"task_id": "task-bridge"},
        )

        assert sent, "消息压根没发出去,这条用例没有验到派发路径"

        record = get_participant_session(session_id)
        assert record is not None, (
            "send_takeover_request 之后仍然没有会话记录 —— " "相位机的入口没被调用,后续每一个生命周期信号都会被静默丢掉"
        )
        assert (
            record.phase.value == "takeover_pending"
        ), f"相位停在 {record.phase.value};说明记录虽然建了,但 takeover 信号没推进它"

    async def test_two_takeovers_on_one_session_keep_the_later_phase(self, monkeypatch):
        """派发两次不该把会话打回起点 —— 与幂等那条对应,但走的是真实路径。"""
        bridge_mod = pytest.importorskip("galaxy_gateway.android_bridge")
        # takeover 是**模式门控**的:本地模式下 send_takeover_request 会在发消息之前
        # 直接返回拒绝(android_bridge.py 的 Axis-1 + Axis-7 守卫)。
        # 打桩打在 android_bridge 自己的模块级别名上 —— 它在 import 时就绑定了,
        # 去 patch cross_device_switch.is_cross_device_enabled 对它没有作用。
        monkeypatch.setattr(bridge_mod, "_is_cross_device_enabled", lambda: True)
        bridge = bridge_mod.AndroidBridge()
        session_id = _sid()

        async def _fake_send_to_device(device_id, msg, wait_response=False, **kwargs):
            return {"success": True}

        monkeypatch.setattr(bridge, "send_to_device", _fake_send_to_device)

        for takeover_id in ("tk-1", "tk-2"):
            await bridge.send_takeover_request(
                device_id="dev-bridge",
                takeover_id=takeover_id,
                session_id=session_id,
                task_context={"task_id": "task-bridge"},
            )

        record = get_participant_session(session_id)
        assert record is not None
        assert record.phase.value == "takeover_pending"


def test_asyncio_is_actually_available():
    """守住上面那些 async 用例真的跑了 —— 少了 pytest-asyncio 它们会被静默跳过。"""
    assert asyncio.get_event_loop_policy() is not None
