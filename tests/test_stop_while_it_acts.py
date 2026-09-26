"""它在动手时，人能叫停。

三件事，各钉各的：

1. **停止通路**（``DesktopPresenceRuntime.stop_current_activity``）：取消在跑的请求，
   调用方拿到的是一个 ``stopped=True`` 的正常返回值 —— 自发注意力循环、语音回路都是
   inline await ``handle_request`` 的，把 CancelledError 抛回去，停掉的就是整条循环。
2. **「在动手」这一位**（``core.liminal_activity.acting`` → ``RuntimeSession``）：
   进出成对、可嵌套；回静息时兜底清零；占着的叫停键一份不多、一份不少地还回去。
3. **叫停键**（``core.stop_key``）：只认真人按下的 Esc（它自己注入的不算），只在动手
   期间监听；分不清人按的和注入的平台上不占 —— 岛上也就不写「Esc 停止」。
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
import types

import pytest

import core.lumiv_websocket_bridge as bridge_mod
import core.stop_key as stop_key
from core.desktop_presence_runtime import (
    DesktopPresenceRuntime,
    RuntimeSession,
    TriState,
    get_desktop_presence_runtime,
)
from core.lumiv_websocket_bridge import GalaxyPresenceBridge


def _until(pred, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return bool(pred())


# ── 1. 停止通路 ────────────────────────────────────────────────────────────


def _blocking_body(started: asyncio.Event, runtime_session_id: str = "rs-1"):
    async def body(message, **kwargs):
        kwargs["_inflight"].runtime_session_id = runtime_session_id
        started.set()
        await asyncio.sleep(3600)
        return {"success": True, "response": "never"}

    return body


async def test_stop_cancels_the_request_but_the_caller_keeps_running():
    rt = DesktopPresenceRuntime()
    started = asyncio.Event()
    rt._handle_request_body = _blocking_body(started)

    async def caller_loop():
        # 自发注意力循环的形状：在自己的 tick 里 inline await，然后接着转。
        first = await rt.handle_request("看一眼", source="ambient")
        return [first, "循环还在"]

    loop_task = asyncio.create_task(caller_loop())
    await asyncio.wait_for(started.wait(), 2)

    out = await rt.stop_current_activity(reason="panel")
    assert out["stopped"] == [{"source": "ambient", "runtime_session_id": "rs-1"}]
    assert out["reason"] == "panel"

    first, after = await asyncio.wait_for(loop_task, 2)
    assert first["stopped"] is True, "被停下的请求要以 stopped=True 正常返回，不能抛进调用方"
    assert first["stop_reason"] == "panel"
    assert first["response"] == ""
    assert first["runtime_session_id"] == "rs-1"
    assert after == "循环还在", "停掉的应该是这一件事，不是整条循环"
    assert rt._inflight_registry() == {}, "停完之后登记表里不该还挂着它"


async def test_the_caller_being_cancelled_still_propagates():
    """反方向不变：调用方自己被取消（客户端断连、超时）时照旧取消到底。"""
    rt = DesktopPresenceRuntime()
    started = asyncio.Event()
    rt._handle_request_body = _blocking_body(started)

    task = asyncio.create_task(rt.handle_request("hi", source="chat"))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert rt._inflight_registry() == {}


async def test_stop_is_idempotent_when_nothing_is_running():
    rt = DesktopPresenceRuntime()
    out = await rt.stop_current_activity(reason="hotkey")
    assert out["stopped"] == []
    assert out["presences_interrupted"] == []
    assert out["errors"] == {}


async def test_stop_interrupts_what_an_ambient_presence_is_saying():
    """常驻在场（双工）登记的打断钩子被调到 —— 只停正在说的这一句，会话留着。"""
    rt = DesktopPresenceRuntime()
    hits = []

    async def on_interrupt():
        hits.append("interrupt")

    handle = rt.open_ambient_presence("voice_duplex", on_interrupt=on_interrupt)
    try:
        out = await rt.stop_current_activity(reason="panel")
        assert hits == ["interrupt"]
        assert out["presences_interrupted"] == [handle]
        assert handle in rt._ambient_registry(), "住手不是收摊：常驻在场本身不该被关掉"
    finally:
        await rt.halt_ambient_presence(handle)


# ── 2. 「在动手」这一位 ────────────────────────────────────────────────────


@pytest.fixture
def recorded_key(monkeypatch):
    calls = []
    captured = {}

    def acquire(cb):
        calls.append("acquire")
        captured["cb"] = cb

    monkeypatch.setattr(stop_key, "acquire", acquire)
    monkeypatch.setattr(stop_key, "release", lambda: calls.append("release"))
    return calls, captured


async def test_acting_nests_and_holds_the_stop_key_exactly_once(recorded_key):
    calls, _ = recorded_key
    s = RuntimeSession("chat")
    s.enter_acting("computer_use")
    s.enter_acting("hybrid_executor")  # 闭环里再调一次应用自动化：同一段
    assert s.acting and s.acting_reason == "computer_use"

    s.exit_acting()
    assert s.acting, "内层先退出时不能把它报成停了"
    assert calls == ["acquire"]

    s.exit_acting()
    assert not s.acting and s.acting_reason == ""
    assert calls == ["acquire", "release"]

    s.exit_acting()  # 多退一次：不出错、不多还
    assert calls == ["acquire", "release"]


async def test_back_to_silent_clears_acting_and_returns_the_key_once(recorded_key):
    """被停止 / 被取消那种没走完的路径：回静息时兜底清零，之后迟到的 finally 不再多还。"""
    calls, _ = recorded_key
    s = RuntimeSession("chat")
    s.advance(TriState.LIMINAL)
    s.advance(TriState.MANIFEST)
    s.enter_acting("computer_use")
    s.advance(TriState.SILENT)
    assert not s.acting
    assert calls == ["acquire", "release"]

    s.exit_acting()  # acting() 的 finally 晚到
    assert calls == ["acquire", "release"]


def test_outside_an_event_loop_there_is_nothing_to_stop(recorded_key):
    calls, _ = recorded_key
    s = RuntimeSession("chat")
    s.enter_acting("computer_use")
    assert s.acting
    s.exit_acting()
    assert calls == [], "没有事件循环就没有能停的东西 —— 不该占键"


async def test_pressing_the_key_stops_it_from_the_listener_thread(recorded_key, monkeypatch):
    _, captured = recorded_key
    rt = get_desktop_presence_runtime()
    stopped = asyncio.Event()
    seen = {}

    async def fake_stop(*, reason="user_stop"):
        seen["reason"] = reason
        stopped.set()
        return {}

    monkeypatch.setattr(rt, "stop_current_activity", fake_stop)
    s = RuntimeSession("chat")
    s.enter_acting("computer_use")
    try:
        # 回调跑在键盘监听线程里：它只能把「停」投递回事件循环。
        threading.Thread(target=captured["cb"]).start()
        await asyncio.wait_for(stopped.wait(), 2)
        assert seen["reason"] == "stop_key"
    finally:
        s.exit_acting()


async def test_tick_payload_reports_acting():
    from core.liminal_activity import acting, bind_runtime_session, unbind_runtime_session

    s = RuntimeSession("chat")
    token = bind_runtime_session(s)
    try:
        with acting("computer_use") as entered:
            assert entered is True
            assert s.acting
        assert not s.acting
    finally:
        unbind_runtime_session(token)

    with acting("computer_use") as entered:  # 不在一次请求里：空操作
        assert entered is False


# ── 3. 叫停键 ──────────────────────────────────────────────────────────────


class _FakeListener:
    def __init__(self, on_key, gate=None):
        self.on_key = on_key
        self.gate = gate
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def wait(self):
        if self.gate is not None:
            self.gate.wait(2)

    def stop(self):
        self.stopped = True


@pytest.fixture
def fake_keyboard(monkeypatch):
    made = []
    gate = {"event": None}

    def factory(on_key):
        listener = _FakeListener(on_key, gate["event"])
        made.append(listener)
        return listener

    monkeypatch.setattr(stop_key, "_make_listener", factory)
    monkeypatch.setattr(stop_key, "availability", lambda: "")
    yield made, gate
    while stop_key._holders:
        stop_key.release()


def test_only_a_person_pressing_esc_stops_it(fake_keyboard):
    made, _ = fake_keyboard
    presses = []
    stop_key.acquire(lambda: presses.append(1))
    assert _until(lambda: stop_key.label() == "Esc"), "占到了就该报出键名"
    (listener,) = made
    assert listener.started

    listener.on_key(True, True)  # 它自己注入的 Esc
    listener.on_key(False, False)  # 人按了别的键
    assert presses == [], "注入的 Esc、别的键都不该停它"

    listener.on_key(True, False)  # 人按的 Esc
    assert presses == [1]
    stop_key.release()


def test_the_listener_lives_only_while_something_acts(fake_keyboard):
    made, _ = fake_keyboard
    stop_key.acquire(lambda: None)
    stop_key.acquire(lambda: None)  # 两个请求同时在动手
    assert _until(lambda: stop_key.label() == "Esc")
    assert len(made) == 1, "同一时刻只该有一个监听"

    stop_key.release()
    assert stop_key.label() == "Esc", "一个停手不能把另一个的叫停键也撤了"
    assert not made[0].stopped

    stop_key.release()
    assert stop_key.label() == ""
    assert made[0].stopped, "没人在动手了，监听必须停掉"

    stop_key.release()  # 多还：按 0 算
    assert stop_key._holders == 0


def test_a_listener_that_comes_up_too_late_is_put_away(fake_keyboard):
    made, gate = fake_keyboard
    gate["event"] = threading.Event()
    stop_key.acquire(lambda: None)
    assert _until(lambda: len(made) == 1)
    stop_key.release()  # 监听还没起来，动手已经结束了
    gate["event"].set()
    assert _until(lambda: made[0].stopped), "起来得太晚的监听要原样收掉，不能一直挂着"
    assert stop_key.label() == ""


def test_no_claim_where_it_cannot_tell_a_person_from_itself(monkeypatch):
    made = []
    monkeypatch.setattr(stop_key, "_make_listener", lambda on_key: made.append(on_key))
    monkeypatch.setattr(stop_key, "availability", lambda: "分不清")
    try:
        stop_key.acquire(lambda: None)
        time.sleep(0.05)
        assert made == [], "分不清人按的和注入的，就不该开监听"
        assert stop_key.label() == "", "没占到就不能让岛上写「Esc 停止」"
    finally:
        stop_key.release()


class TestAvailability:
    def test_linux_is_refused(self, monkeypatch):
        monkeypatch.delenv("GALAXY_STOP_KEY", raising=False)
        monkeypatch.setattr(sys, "platform", "linux")
        assert stop_key.availability(), "X11 上 XTest 注入的键与真按的一样 —— 不该占"

    def test_switch_off(self, monkeypatch):
        monkeypatch.setenv("GALAXY_STOP_KEY", "0")
        monkeypatch.setattr(sys, "platform", "win32")
        assert "GALAXY_STOP_KEY" in stop_key.availability()

    def _fake_pynput(self, monkeypatch, version):
        pkg = types.ModuleType("pynput")
        info = types.ModuleType("pynput._info")
        info.__version__ = version
        pkg._info = info
        monkeypatch.setitem(sys.modules, "pynput", pkg)
        monkeypatch.setitem(sys.modules, "pynput._info", info)

    def test_old_pynput_cannot_tell_injected_keys(self, monkeypatch):
        monkeypatch.delenv("GALAXY_STOP_KEY", raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        self._fake_pynput(monkeypatch, (1, 7, 6))
        assert "1.8" in stop_key.availability()

    def test_windows_with_new_pynput_is_available(self, monkeypatch):
        monkeypatch.delenv("GALAXY_STOP_KEY", raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        self._fake_pynput(monkeypatch, (1, 8, 2))
        assert stop_key.availability() == ""


# ── 渲染契约：stop_key 只在动手期间、而且占到了才有值 ─────────────────────


def test_render_reports_the_stop_key_only_while_acting(monkeypatch):
    b = GalaxyPresenceBridge.get_instance()
    monkeypatch.setattr(bridge_mod, "_stop_key_label", lambda: "Esc")

    monkeypatch.setattr(b, "_acting_sessions", frozenset())
    render = b._build_message(consume_edge=False)["payload"]["render"]
    assert render["acting"] is False
    assert render["stop_key"] == ""

    monkeypatch.setattr(b, "_acting_sessions", frozenset({"rs-1"}))
    render = b._build_message(consume_edge=False)["payload"]["render"]
    assert render["acting"] is True
    assert render["stop_key"] == "Esc"


def test_render_does_not_claim_a_key_it_did_not_get(monkeypatch):
    b = GalaxyPresenceBridge.get_instance()
    monkeypatch.setattr(bridge_mod, "_stop_key_label", lambda: "")
    monkeypatch.setattr(b, "_acting_sessions", frozenset({"rs-1"}))
    render = b._build_message(consume_edge=False)["payload"]["render"]
    assert render["acting"] is True
    assert render["stop_key"] == "", "动手期间没占到键，也不能报一个键名出去"


async def test_the_bridge_broadcasts_when_acting_or_the_key_changes(monkeypatch):
    b = GalaxyPresenceBridge.get_instance()
    sent = []

    async def fake_broadcast(*_a, **_k):
        sent.append(1)

    label = {"v": ""}
    monkeypatch.setattr(b, "_broadcast_state", fake_broadcast)
    monkeypatch.setattr(b, "_acting_sessions", frozenset())
    monkeypatch.setattr(b, "_stop_key_sent", "")
    monkeypatch.setattr(bridge_mod, "_stop_key_label", lambda: label["v"])

    async def note(acting):
        b._note_acting("rs-1", acting)
        await asyncio.sleep(0)

    await note(True)
    assert len(sent) == 1, "开始动手要送出去"
    await note(True)
    assert len(sent) == 1, "没变不发"
    label["v"] = "Esc"
    await note(True)
    assert len(sent) == 2, "叫停键占到的那一下也要送出去"
    await note(False)
    assert len(sent) == 3, "停手要送出去"


@pytest.mark.parametrize(("device_id", "expect"), [("local", True), ("", True), ("phone-3", False)])
async def test_hybrid_execution_counts_as_acting_only_on_this_machine(recorded_key, device_id, expect):
    """「正在操作」说的是眼前这块屏幕、这副键鼠 —— 它在操作手机时这么说就是假话。"""
    from core.hybrid_executor import HybridExecutionArbiter
    from core.liminal_activity import bind_runtime_session, unbind_runtime_session

    s = RuntimeSession("chat")
    seen = {}

    async def body(*_a, **_k):
        seen["acting"] = s.acting
        return "done"

    arbiter = HybridExecutionArbiter.__new__(HybridExecutionArbiter)
    arbiter._execute_body = body
    token = bind_runtime_session(s)
    try:
        assert await arbiter.execute(device_id, "app", "noop") == "done"
    finally:
        unbind_runtime_session(token)
    assert seen["acting"] is expect
    assert not s.acting


def test_a_stopped_chat_stream_ends_with_a_done_frame_that_says_so(monkeypatch):
    """面板据 done 帧的 stopped 说「停下了」，而不是把空回复报成「后端什么都没给」。"""
    import json
    from unittest.mock import patch

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import core.desktop_presence_runtime as dpr
    import core.routes.chat as chat_mod
    from core.desktop_presence_runtime import _InflightRequest

    class _StoppedRuntime:
        async def handle_request(self, *a, **k):
            handle = _InflightRequest(source="chat", runtime_session_id="rs-9", stopped=True, stop_reason="panel")
            return DesktopPresenceRuntime._stopped_result(handle)

    app = FastAPI()
    app.include_router(chat_mod.create_router(service_manager=None, config=None))
    client = TestClient(app)
    with patch.object(dpr, "get_desktop_presence_runtime", lambda: _StoppedRuntime()):
        with client.stream("POST", "/api/v1/chat/stream", json={"message": "帮我整理桌面"}) as r:
            frames = [json.loads(line[6:]) for line in r.iter_lines() if line and line.startswith("data: ")]

    done = [f for f in frames if f.get("type") == "done"]
    assert done, f"被叫停的那一轮没有收尾帧 —— 面板的气泡会一直闪光标: {[f.get('type') for f in frames]}"
    assert done[-1].get("stopped") is True
    assert not [f for f in frames if f.get("type") == "error"], "叫停不是出错"


async def test_a_broken_locality_check_never_blocks_execution(recorded_key, monkeypatch):
    """判不出目标是不是本机时照常执行，只是不报「在动手」—— 可见性绝不该拖垮执行。"""
    from core.hybrid_executor import HybridExecutionArbiter
    from core.liminal_activity import bind_runtime_session, unbind_runtime_session

    monkeypatch.setitem(sys.modules, "core.orchestration", None)  # 再 import 就是 ImportError
    s = RuntimeSession("chat")
    seen = {}

    async def body(*_a, **_k):
        seen["acting"] = s.acting
        return "done"

    arbiter = HybridExecutionArbiter.__new__(HybridExecutionArbiter)
    arbiter._execute_body = body
    token = bind_runtime_session(s)
    try:
        assert await arbiter.execute("local", "app", "noop") == "done", "判不出本机就不执行了"
    finally:
        unbind_runtime_session(token)
    assert seen["acting"] is False
