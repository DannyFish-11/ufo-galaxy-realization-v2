"""实时双工 ↔ 统一主体 的接线 —— 契约测试
============================================

覆盖三条此前**完全断开**的接线:

A1  双工会话开着时,主体持续在场(三态停在 LIMINAL,不随每个语音回合翻转)。
A2  中心能把这条实时通路叫停 —— 统一主体里不该有中心管不着的常驻旁路。
A3  双工里的轮次进同一份会话记忆(旁录),但**不产生第二个回复**。

这里刻意分成"运行时的常驻在场"与"桥的行为"两组:前者是 DesktopPresenceRuntime
自己的新能力(任何长命在场都能用,不只是语音),后者才是双工特有的接法。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture()
def runtime():
    """一个干净的 DesktopPresenceRuntime。

    用 ``__new__`` + 手工装配而不是构造真实例:``__init__`` 会去起多模态摄入总线、
    WebRTC 会话管理器、跨设备注册 —— 那些与本文件要验的东西无关,却会让用例又慢
    又依赖环境。这也顺带验证了常驻在场的惰性登记表(``_ambient_registry``)确实
    能在绕过 ``__init__`` 的实例上工作。
    """
    from core.desktop_presence_runtime import DesktopPresenceRuntime
    from core.desktop_presence_system import DesktopPresenceStateMachine

    rt = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
    rt._active_sessions = {}
    rt._presence_state_machine = DesktopPresenceStateMachine()
    rt._latest_presence_runtime_hint = {}
    rt._latest_subject_projection = {}
    return rt


class TestAmbientPresenceIsContinuous:
    """A1:常驻在场进一次 LIMINAL 就保持,不翻转。"""

    def test_open_enters_liminal_and_stays(self, runtime):
        from core.desktop_presence_runtime import TriState

        handle = runtime.open_ambient_presence("voice_duplex", reason="test")
        session = runtime._active_sessions[handle]

        assert session.tristate is TriState.LIMINAL
        # 只有一次相位变化 —— "持续在场"的字面含义就是这个:不是每回合翻一遍。
        assert [s for s, _ in session.transitions] == [TriState.LIMINAL]

    def test_presence_summary_reports_liminal_while_open(self, runtime):
        runtime.open_ambient_presence("voice_duplex")
        summary = runtime.presence_summary()

        assert summary["dominant_tristate"] == "liminal"
        assert summary["ambient_presence"]["active"] == 1
        assert summary["ambient_presence"]["entries"][0]["source"] == "voice_duplex"

    def test_close_returns_to_silent_and_deregisters(self, runtime):
        from core.desktop_presence_runtime import TriState

        handle = runtime.open_ambient_presence("voice_duplex")
        session = runtime._active_sessions[handle]

        assert runtime.close_ambient_presence(handle) is True
        assert session.tristate is TriState.SILENT
        assert handle not in runtime._active_sessions
        assert runtime.presence_summary()["ambient_presence"]["active"] == 0

    def test_close_is_idempotent_for_unknown_handle(self, runtime):
        assert runtime.close_ambient_presence("never-existed") is False

    def test_multiple_ambient_presences_are_independent(self, runtime):
        """桌面双工 + 手机双工可以同时在场,互不干扰。"""
        h1 = runtime.open_ambient_presence("voice_duplex")
        h2 = runtime.open_ambient_presence("android_duplex")

        assert h1 != h2
        assert runtime.ambient_presence_snapshot()["active"] == 2

        runtime.close_ambient_presence(h1)
        snapshot = runtime.ambient_presence_snapshot()
        assert snapshot["active"] == 1
        assert snapshot["entries"][0]["source"] == "android_duplex"


class TestAmbientPresenceActuallyBreathes:
    """常驻在场必须**真的**在驱动外壳,而不只是把三态字段改成 liminal。

    这一组是补上来的:原先我只断言了 ``tristate is LIMINAL``,而"持续、实时、连贯"
    靠的是 200ms 的 continuum tick 持续发射 ``continuum.state`` / ``intent.update``。
    结果我在给 ``_start_continuum_tick`` 加 running-loop 守卫时把 ``_tick_running
    = True`` 顺手删掉了,tick 一拍都不跑 —— 三态字段照样是 liminal、tick_task 照样
    存在、所有既有用例照样绿,只有外壳彻底不动。**状态对 ≠ 在场活着**,所以这里
    直接断言事件流。
    """

    @pytest.mark.asyncio
    async def test_open_ambient_presence_drives_the_continuum_tick(self, runtime):
        from core.state_event_bus import get_state_event_bus

        bus = get_state_event_bus()
        seen: list = []
        tok = bus.subscribe("intent.update", lambda e: seen.append(getattr(e, "payload", e)))

        handle = runtime.open_ambient_presence("voice_duplex", reason="tick test")
        try:
            await asyncio.sleep(0.45)  # tick 周期 200ms,至少跑两拍
            assert seen, "常驻在场期间必须持续发射 intent.update —— 否则外壳是死的"
            payload = seen[-1] if isinstance(seen[-1], dict) else {}
            assert "intent_strength" in payload
        finally:
            runtime.close_ambient_presence(handle)
            try:
                bus.unsubscribe(tok)
            except Exception:  # noqa: BLE001
                pass

    @pytest.mark.asyncio
    async def test_closing_ambient_presence_stops_the_tick(self, runtime):
        """关掉在场之后必须**停止**发射 —— 否则会留一个永不退出的 200ms 循环。"""
        from core.state_event_bus import get_state_event_bus

        bus = get_state_event_bus()
        handle = runtime.open_ambient_presence("voice_duplex")
        await asyncio.sleep(0.25)
        runtime.close_ambient_presence(handle)

        after: list = []
        tok = bus.subscribe("intent.update", lambda e: after.append(e))
        try:
            await asyncio.sleep(0.45)
            assert after == [], "在场已关闭,tick 仍在发射(泄漏了一个后台循环)"
        finally:
            try:
                bus.unsubscribe(tok)
            except Exception:  # noqa: BLE001
                pass


class TestCentreCanHalt:
    """A2:中心叫得停。"""

    def test_halt_runs_hook_and_reclaims(self, runtime):
        halted = []

        async def _on_halt():
            halted.append(True)

        handle = runtime.open_ambient_presence("voice_duplex", on_halt=_on_halt)
        result = asyncio.run(runtime.halt_ambient_presence(handle, reason="operator_stop"))

        assert halted == [True]
        assert result["halted"] == [handle]
        assert result["errors"] == {}
        assert runtime.ambient_presence_snapshot()["active"] == 0

    def test_halt_accepts_sync_hook(self, runtime):
        """钩子写成同步函数也要能用 —— 不该逼调用方为了接线去改成协程。"""
        halted = []
        handle = runtime.open_ambient_presence("x", on_halt=lambda: halted.append(True))

        asyncio.run(runtime.halt_ambient_presence(handle))
        assert halted == [True]

    def test_halt_reclaims_even_when_hook_raises(self, runtime):
        """钩子炸了也必须停下来。

        否则"中心说停"就变成了"中心请求停,对方可以拒绝" —— 那正是这条接线
        要消灭的状态。
        """

        async def _boom():
            raise RuntimeError("ws already dead")

        handle = runtime.open_ambient_presence("voice_duplex", on_halt=_boom)
        result = asyncio.run(runtime.halt_ambient_presence(handle))

        assert result["halted"] == [handle]
        assert "ws already dead" in result["errors"][handle]
        assert runtime.ambient_presence_snapshot()["active"] == 0

    def test_halt_all_when_no_handle_given(self, runtime):
        runtime.open_ambient_presence("a", on_halt=lambda: None)
        runtime.open_ambient_presence("b", on_halt=lambda: None)

        result = asyncio.run(runtime.halt_ambient_presence(reason="focus_mode"))
        assert len(result["halted"]) == 2
        assert runtime.ambient_presence_snapshot()["active"] == 0

    def test_snapshot_flags_unhaltable_presence(self, runtime):
        """没交叫停钩子的在场必须被标出来 —— 它是接线漏了,不是配置选择。"""
        runtime.open_ambient_presence("mystery_channel")  # 故意不传 on_halt
        snapshot = runtime.ambient_presence_snapshot()

        assert snapshot["entries"][0]["haltable"] is False
        assert snapshot["all_haltable"] is False


class TestRequestCycleDoesNotCancelAmbientPresence:
    """穿插的文字问答结束时,不该把语音在场顺手关掉。"""

    def test_request_end_keeps_task_active_while_ambient_open(self, runtime):
        runtime.open_ambient_presence("voice_duplex")
        # presence_summary 会跑一次状态机收敛;常驻在场仍在 → 主导相位仍是 liminal。
        assert runtime.presence_summary()["dominant_tristate"] == "liminal"

        # 模拟一次请求会话走完整轮并被回收(handle_request 的 finally 所做的事)。
        req = runtime._create_session("chat")
        from core.desktop_presence_runtime import TriState

        req.advance(TriState.LIMINAL)
        req.advance(TriState.SILENT)
        runtime._active_sessions.pop(req.runtime_session_id, None)

        assert runtime.presence_summary()["dominant_tristate"] == "liminal"
        assert runtime.ambient_presence_snapshot()["active"] == 1


class TestBridgeWiring:
    """A3 与桥自身的行为。"""

    @staticmethod
    def _bridge(monkeypatch, runtime, recorded):
        import core.duplex_presence_bridge as mod
        from core.duplex_presence_bridge import DuplexPresenceBridge

        monkeypatch.setattr(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            lambda: runtime,
        )

        async def _fake_record(**kwargs):
            recorded.append(kwargs)

        monkeypatch.setattr(
            "core.session_memory_facade.record_session_turn",
            _fake_record,
        )
        assert mod is not None  # import 成功即证明模块无语法/循环依赖问题
        session = MagicMock()
        session.close = AsyncMock()
        return DuplexPresenceBridge(session, conversation_session_id="sess-1"), session

    def test_open_and_close_drive_tristate(self, monkeypatch, runtime):
        from core.desktop_presence_runtime import TriState

        bridge, _ = self._bridge(monkeypatch, runtime, [])

        handle = asyncio.run(bridge.open())
        assert handle is not None
        assert runtime._active_sessions[handle].tristate is TriState.LIMINAL

        asyncio.run(bridge.close())
        assert runtime.ambient_presence_snapshot()["active"] == 0

    def test_centre_halt_closes_the_websocket(self, monkeypatch, runtime):
        """A2 端到端:中心叫停 → 那条实时 WebSocket 真的被关。"""
        bridge, session = self._bridge(monkeypatch, runtime, [])
        asyncio.run(bridge.open())

        asyncio.run(runtime.halt_ambient_presence(reason="operator_stop"))

        session.close.assert_awaited_once()
        assert runtime.ambient_presence_snapshot()["active"] == 0

    def test_user_turn_is_recorded(self, monkeypatch, runtime):
        recorded: list = []
        bridge, _ = self._bridge(monkeypatch, runtime, recorded)
        asyncio.run(bridge.open())

        asyncio.run(bridge.note_user_turn("帮我把这份报告发给老王"))

        assert len(recorded) == 1
        assert recorded[0]["role"] == "user"
        assert recorded[0]["content"] == "帮我把这份报告发给老王"
        assert recorded[0]["conversation_session_id"] == "sess-1"
        assert recorded[0]["metadata"]["channel"] == "realtime_duplex"

    def test_blank_user_turn_is_ignored(self, monkeypatch, runtime):
        recorded: list = []
        bridge, _ = self._bridge(monkeypatch, runtime, recorded)

        asyncio.run(bridge.note_user_turn("   "))
        assert recorded == []

    def test_assistant_deltas_are_joined_into_one_turn(self, monkeypatch, runtime):
        recorded: list = []
        bridge, _ = self._bridge(monkeypatch, runtime, recorded)

        bridge.note_assistant_delta("好的,")
        bridge.note_assistant_delta("已经发出去了。")
        asyncio.run(bridge.note_assistant_done())

        assert len(recorded) == 1
        assert recorded[0]["role"] == "assistant"
        assert recorded[0]["content"] == "好的,已经发出去了。"

    def test_assistant_done_without_deltas_records_nothing(self, monkeypatch, runtime):
        recorded: list = []
        bridge, _ = self._bridge(monkeypatch, runtime, recorded)

        asyncio.run(bridge.note_assistant_done())
        assert recorded == []

    def test_close_flushes_pending_assistant_text(self, monkeypatch, runtime):
        """用户直接挂断时,最后一段还没等到 RESPONSE_DONE 的回复不能丢。"""
        recorded: list = []
        bridge, _ = self._bridge(monkeypatch, runtime, recorded)
        asyncio.run(bridge.open())

        bridge.note_assistant_delta("我正在查……")
        asyncio.run(bridge.close())

        assert [r["content"] for r in recorded] == ["我正在查……"]

    def test_bridge_survives_runtime_unavailable(self, monkeypatch):
        """外壳起不来时,双工必须照常跑 —— 接线是增益,不是前置条件。"""
        from core.duplex_presence_bridge import DuplexPresenceBridge

        def _boom():
            raise RuntimeError("no display")

        monkeypatch.setattr(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            _boom,
        )
        bridge = DuplexPresenceBridge(MagicMock(), conversation_session_id="s")

        assert asyncio.run(bridge.open()) is None
        asyncio.run(bridge.close())  # 不抛出

    def test_missing_session_id_gets_a_generated_one(self):
        """没有会话 ID 时必须自己造一个。

        ``record_session_turn`` 在 conversation_session_id 为空时直接 return ——
        那样轮次会**静默丢失**,而这正是本模块要修的毛病,不能在自己身上重演。
        """
        from core.duplex_presence_bridge import DuplexPresenceBridge

        bridge = DuplexPresenceBridge(MagicMock())
        assert bridge.conversation_session_id.startswith("duplex-")
