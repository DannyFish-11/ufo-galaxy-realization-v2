"""治理接进了常驻注意力循环之后，**循环整体**该有的样子。

``test_ambient_governance.py`` 钉的是治理层自己；这里钉的是接缝：

1. **额度**：超额的自发开口 / 委托降级为沉默，**写着理由**；被 hold / 手表压下的不扣额度；
2. **期限**：一次永不返回的委托被叫停，循环**还活着**；这一次叫停真的走完整条取消通道 ——
   运行时回到静默、不再「在动手」、叫停键还回去、正在飞的那一步记成「结果不明」；
3. **唤醒规则**（借自 Comma：只有显式 notify 才唤醒会话）：循环里只有 SPEAK 会出声、进对话；
   沉默的一拍、被压下的一拍、委托、委托失败，一概不会 —— 这条本来就是设计，这里把它写成测试。
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import threading
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

import core.stop_key as stop_key
from core.action_journal import OUTCOME_UNKNOWN_CANCEL, get_action_journal, journaled, reset_action_journal
from core.ambient_attention_loop import AmbientAction, AmbientAttentionLoop, AmbientDecision
from core.ambient_governance import AmbientGovernor, AmbientLimits
from core.desktop_presence_runtime import DesktopPresenceRuntime


def _jpeg(color: int) -> str:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("L", (64, 64), color).save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


_BLACK, _WHITE = _jpeg(0), _jpeg(255)


class FakeStore:
    """每次取快照就把画面翻一下 —— 帧差门控每一拍都放行，测的是后面的路由与治理。"""

    def __init__(self) -> None:
        self._flip = False

    def snapshot_media(self) -> Dict[str, Any]:
        self._flip = not self._flip
        return {"camera_b64": _WHITE if self._flip else _BLACK}


class FakeWM:
    def __init__(self) -> None:
        self.adds: List[Dict[str, Any]] = []

    def add(self, *, session_id, role, content, trace_id="", metadata=None):
        self.adds.append({"role": role, "content": content})


class FakeBus:
    def __init__(self) -> None:
        self.events: List[str] = []

    def publish(self, event_type, *, source, payload=None, **kw):
        self.events.append(event_type)


class Scripted:
    """按脚本逐拍给决策；脚本用完就一直沉默。同时记下每一拍决策脑看到的「最近注意到」。"""

    def __init__(self, *decisions: AmbientDecision) -> None:
        self.script = list(decisions)
        self.seen_memory: List[List[str]] = []
        self.last_obs: Any = None

    async def decide(self, obs):
        self.last_obs = obs
        self.seen_memory.append(list(obs.recent_memory))
        if self.script:
            return self.script.pop(0)
        return AmbientDecision(AmbientAction.SILENT, rationale="无事")


def _speak(text: str = "要帮忙吗？") -> AmbientDecision:
    return AmbientDecision(AmbientAction.SPEAK, rationale="卡住了", utterance=text, salient=True)


def _delegate(task: str = "查错误日志") -> AmbientDecision:
    return AmbientDecision(AmbientAction.DELEGATE, rationale="反复报错", task=task, salient=True)


def _silent() -> AmbientDecision:
    return AmbientDecision(AmbientAction.SILENT, rationale="用户在正常操作")


def _loop(decider, *, governor: AmbientGovernor | None = None, wm=None, bus=None) -> AmbientAttentionLoop:
    return AmbientAttentionLoop(
        decider=decider,
        perception_store=FakeStore(),
        working_memory=wm if wm is not None else FakeWM(),
        unified_memory=None,
        event_bus=bus if bus is not None else FakeBus(),
        cooldown_s=0.0,
        governor=governor,
    )


def _limits(**kw) -> AmbientLimits:
    return AmbientLimits(**kw)


@pytest.fixture
def spoken():
    """替掉朗读与「说给面板」「记进主线」—— 谁被调用了，一目了然。"""
    calls: Dict[str, List[Any]] = {"tts": [], "panel": [], "mainline": []}

    async def _record_turn(**kw):
        calls["mainline"].append(kw)

    with (
        patch("core.speech_output.speak_response", lambda text, source="": calls["tts"].append((text, source))),
        patch("core.lumiv_websocket_bridge.emit_conversation", lambda *a, **k: calls["panel"].append((a, k))),
        patch("core.session_memory_facade.record_session_turn", _record_turn),
        patch("core.conversation_mainline.mainline_session_id", lambda create=False: "main-1"),
    ):
        yield calls


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    reset_action_journal()
    yield get_action_journal()
    reset_action_journal()


# ── 1. 额度 ───────────────────────────────────────────────────────────────


async def test_an_over_budget_remark_is_silent_and_the_reason_is_on_record(spoken):
    wm = FakeWM()
    loop = _loop(
        Scripted(_speak("第一句"), _speak("第二句")), governor=AmbientGovernor(_limits(speak_per_hour=1)), wm=wm
    )

    first = await loop.tick()
    second = await loop.tick()

    assert first.action == AmbientAction.SPEAK and second.action == AmbientAction.SILENT
    assert spoken["tts"] == [("第一句", "ambient")], "第二句没有出声"
    assert len(spoken["panel"]) == 1 and len(spoken["mainline"]) == 1, "也没有进面板 / 对话主线"
    assert "已用完（1/1）" in wm.adds[-1]["content"] and "第二句" in wm.adds[-1]["content"], "理由与原拟都写下了"
    s = loop.status()["budget"]["speak"]
    assert (s["used"], s["limit"], s["suppressed"]) == (1, 1, 1)


async def test_a_remark_held_back_by_the_user_is_not_charged(spoken):
    """用户说了「等一下别说话」—— 这期间判出的 SPEAK 没出声，不能扣额度。"""

    class Holding:
        def is_holding(self) -> bool:
            return True

    loop = _loop(Scripted(*[_speak() for _ in range(5)]), governor=AmbientGovernor(_limits(speak_per_hour=2)))
    with patch("core.voice_dialog_policy.get_dialog_policy", lambda: Holding()):
        for _ in range(5):
            await loop.tick()

    assert spoken["tts"] == []
    assert loop.status()["budget"]["speak"]["used"] == 0


async def test_a_remark_the_watch_blocked_is_not_a_budget_suppression(spoken):
    loop = _loop(Scripted(_speak()), governor=AmbientGovernor(_limits(speak_per_hour=1)))
    with patch("core.ambient_attention_loop._interruptibility_blocked", lambda: True):
        decision = await loop.tick()

    assert decision.action == AmbientAction.SILENT and "手表" in decision.rationale
    assert loop.status()["budget"]["speak"]["suppressed"] == 0 and loop.status()["incidents"] == []


async def test_an_over_budget_delegate_is_silent_and_explained(spoken):
    ran: List[str] = []

    class Runtime:
        async def handle_request(self, *, message, **kw):
            ran.append(message)
            return {"success": True}

    wm = FakeWM()
    loop = _loop(
        Scripted(_delegate("任务一"), _delegate("任务二")),
        governor=AmbientGovernor(_limits(delegate_per_hour=1)),
        wm=wm,
    )
    with patch("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: Runtime()):
        await loop.tick()
        second = await loop.tick()

    assert ran == ["任务一"], "第二个委托没有真的派出去"
    assert second.action == AmbientAction.SILENT and "已用完（1/1）" in wm.adds[-1]["content"]


# ── 2. 期限 ───────────────────────────────────────────────────────────────


async def test_a_delegate_that_never_returns_is_stopped_and_the_loop_lives_on(spoken):
    class Hanging:
        async def handle_request(self, **kw):
            await asyncio.sleep(3600)

    decider = Scripted(_delegate("整理下载文件夹"))
    loop = _loop(decider, governor=AmbientGovernor(_limits(delegate_deadline_s=0.1)))
    with patch("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: Hanging()):
        decision = await asyncio.wait_for(loop.tick(), 5)

    assert decision.action == AmbientAction.DELEGATE
    (incident,) = loop.status()["incidents"]
    assert incident["kind"] == "delegate_timeout" and incident["task"] == "整理下载文件夹"
    assert loop.governor.delegate_in_flight is False

    # 循环没死：下一拍照常看、照常决策，而且决策脑知道上一次没做完（不是当它成了）
    await asyncio.wait_for(loop.tick(), 5)
    assert any("上一次委托没做完" in line and "整理下载文件夹" in line for line in decider.seen_memory[-1])


async def test_a_delegate_that_fails_is_told_to_the_next_decision(spoken):
    class Broken:
        async def handle_request(self, **kw):
            raise RuntimeError("model offline")

    decider = Scripted(_delegate("查错误日志"))
    loop = _loop(decider)
    with patch("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: Broken()):
        await loop.tick()
    await loop.tick()

    (incident,) = loop.status()["incidents"]
    assert incident["kind"] == "delegate_failed" and "model offline" not in str(incident)
    assert any("上一次委托没做完" in line for line in decider.seen_memory[-1])


async def test_a_stuck_decider_costs_one_beat_not_the_loop(spoken):
    class Stuck:
        calls = 0

        async def decide(self, obs):
            Stuck.calls += 1
            if Stuck.calls == 1:
                await asyncio.sleep(3600)
            return _silent()

    loop = _loop(Stuck(), governor=AmbientGovernor(_limits(decide_deadline_s=0.05)))
    first = await asyncio.wait_for(loop.tick(), 5)
    second = await asyncio.wait_for(loop.tick(), 5)

    assert first.action == AmbientAction.SILENT and "没有回应" in first.rationale
    assert second.rationale == "用户在正常操作"
    assert [i["kind"] for i in loop.status()["incidents"]] == ["decide_timeout"]


class _SlowDecider:
    """决策调用一直不返回；被取消时记下 —— 到点 / 让路都得**真的**把这次调用取消掉，不是放着它占着模型。"""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def decide(self, obs):
        self.started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


async def test_a_stuck_decision_is_cut_at_the_deadline_and_the_call_is_really_cancelled(spoken):
    """治理（期限）与让路（core/ambient_yield.py）叠在同一拍里：期限到点时，让路层正在等的那次模型调用要被取消。"""
    slow = _SlowDecider()
    loop = _loop(slow, governor=AmbientGovernor(_limits(decide_deadline_s=0.1)))
    with patch("core.ambient_yield._foreground_busy", lambda: False):
        decision = await asyncio.wait_for(loop.tick(), 5)

    assert decision.action == AmbientAction.SILENT and "没有回应" in decision.rationale
    assert slow.cancelled, "期限到了，那次模型调用没被取消 —— 它会一直占着模型"
    assert [i["kind"] for i in loop.status()["incidents"]] == ["decide_timeout"]


async def test_the_user_arriving_mid_decision_abandons_the_call_and_nothing_is_charged(spoken):
    """让路放弃的那一拍：调用被取消、tick 返回 None，不出声、不进主线、不扣额度、不留「故障」痕迹 —— 那不是失败。"""
    busy = {"now": False}
    slow = _SlowDecider()
    loop = _loop(slow, governor=AmbientGovernor(_limits(speak_per_hour=1)))
    with patch("core.ambient_yield._foreground_busy", lambda: busy["now"]):
        ticking = asyncio.create_task(loop.tick())
        await asyncio.wait_for(slow.started.wait(), 2)
        busy["now"] = True  # 用户的请求到了
        result = await asyncio.wait_for(ticking, 5)

    assert result is None and slow.cancelled
    assert spoken == {"tts": [], "panel": [], "mainline": []}
    status = loop.status()
    assert status["budget"]["speak"]["used"] == 0 and status["incidents"] == []
    assert loop.decisions == 0


async def test_a_stuck_transcription_costs_the_beat_its_voice_not_the_loop(spoken):
    class WithAudio(FakeStore):
        def snapshot_media(self) -> Dict[str, Any]:
            return {**super().snapshot_media(), "audio_b64": "QUJD", "audio_mime": "audio/webm"}

    release = threading.Event()

    def stuck(*_a, **_k):
        release.wait(5)
        return "太晚了"

    decider = Scripted(_silent())
    loop = AmbientAttentionLoop(
        decider=decider,
        perception_store=WithAudio(),
        working_memory=FakeWM(),
        unified_memory=None,
        event_bus=FakeBus(),
        cooldown_s=0.0,
        governor=AmbientGovernor(_limits(listen_deadline_s=0.1)),
    )
    try:
        with patch("core.modality_bridge.transcribe_b64", stuck):
            decision = await asyncio.wait_for(loop.tick(), 3)
    finally:
        release.set()

    assert decision.action == AmbientAction.SILENT
    assert decider.last_obs.audio_transcript is None, "超时那一拍不带声音内容"
    assert [i["kind"] for i in loop.status()["incidents"]] == ["listen_timeout"]


async def test_a_delegate_cut_off_at_the_deadline_leaves_the_runtime_clean_and_the_step_unknown(
    spoken, journal, monkeypatch
):
    """整条取消通道：期限到点 → 这一次委托被取消 → 运行时里它的那一次请求落回干净的静默，
    正在飞的那一步记成「结果不明」。这是 E 与 A / B 接上的地方。"""
    from core.liminal_activity import _current_runtime_session, acting, commit_to_manifest

    keys: List[str] = []
    monkeypatch.setattr(stop_key, "acquire", lambda cb: keys.append("acquire"))
    monkeypatch.setattr(stop_key, "release", lambda: keys.append("release"))

    rt = DesktopPresenceRuntime()
    held: Dict[str, Any] = {}
    reached = asyncio.Event()

    async def _dispatch(*_a, **_k):
        held["session"] = _current_runtime_session.get()
        commit_to_manifest()
        with acting("computer_use"), journaled("computer_use", "click", {"x": 7, "y": 8}):
            reached.set()
            await asyncio.sleep(3600)

    rt._dispatch = _dispatch
    loop = _loop(Scripted(_delegate("点一下确定")), governor=AmbientGovernor(_limits(delegate_deadline_s=0.3)))
    with patch("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: rt):
        ticking = asyncio.create_task(loop.tick())
        await asyncio.wait_for(reached.wait(), 5)
        await asyncio.wait_for(ticking, 5)

    session = held["session"]
    assert [i["kind"] for i in loop.status()["incidents"]] == ["delegate_timeout"]
    assert session.tristate.value == "silent", "叫停之后这一次请求没有回到静默"
    assert session.acting is False and session.runtime_session_id not in rt._active_sessions
    assert rt._inflight_registry() == {}
    assert keys.count("acquire") == keys.count("release") == 1, f"叫停键没还干净: {keys}"
    (unknown,) = journal.unknown_for(session.runtime_session_id)
    assert unknown["outcome"] == OUTCOME_UNKNOWN_CANCEL and unknown["summary"] == "click(x=7, y=8)"


# ── 3. 循环自己的生死 ─────────────────────────────────────────────────────


async def test_running_is_only_true_while_the_task_is_alive_and_start_revives_a_dead_one():
    loop = AmbientAttentionLoop(
        decider=Scripted(),
        perception_store=type("S", (), {"snapshot_media": lambda self: {}})(),
        working_memory=FakeWM(),
        unified_memory=None,
        event_bus=FakeBus(),
        interval_s=0.01,
    )
    await loop.start()
    assert loop.running is True

    loop._task.cancel()  # 任务意外死了，而 _running 标志还开着
    await asyncio.sleep(0.05)
    assert loop.running is False, "任务都死了，不能说「在跑」"

    await loop.start()
    assert loop.running is True, "标志还开着不该让 start() 直接返回、永远起不来"
    await loop.stop()
    assert loop.running is False


# ── 4. 唤醒规则：只有 SPEAK 会出声、进对话 ────────────────────────────────


async def test_quiet_beats_touch_nothing_the_user_can_see(spoken):
    bus = FakeBus()
    loop = _loop(Scripted(*[_silent() for _ in range(5)]), bus=bus)
    with patch("core.desktop_presence_runtime.get_desktop_presence_runtime") as runtime:
        # 「用户的请求在不在跑」是只读的查询（循环给用户让路用，core/ambient_yield.py），不算「碰」运行时 ——
        # 要钉的是沉默的一拍不往运行时里**派活**。
        runtime.return_value.foreground_request_active.return_value = False
        for _ in range(5):
            await loop.tick()

    assert spoken == {"tts": [], "panel": [], "mainline": []}
    runtime.return_value.handle_request.assert_not_called()
    assert set(bus.events) == {"ambient.observed", "ambient.decision"}


async def test_the_beats_governance_suppresses_are_just_as_quiet(spoken):
    """被额度压下的 SPEAK 不能「漏」出去一点点 —— 不出声、不进面板、不进主线、不派活。"""
    loop = _loop(Scripted(*[_speak() for _ in range(4)]), governor=AmbientGovernor(_limits(speak_per_hour=1)))
    for _ in range(4):
        await loop.tick()
    assert len(spoken["tts"]) == len(spoken["panel"]) == len(spoken["mainline"]) == 1


async def test_a_delegate_is_silent_work_it_never_speaks_or_pushes_conversation(spoken):
    class Runtime:
        async def handle_request(self, **kw):
            return {"success": True, "response": "已经查完了，一切正常"}

    loop = _loop(Scripted(_delegate(), _delegate()))
    with patch("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: Runtime()):
        await loop.tick()
        await loop.tick()
    assert spoken == {"tts": [], "panel": [], "mainline": []}


async def test_the_real_runtime_does_not_read_an_ambient_reply_aloud():
    """委托的回复是「闭嘴干活」的产物：真运行时对 source=ambient 抑制自动朗读，对话来源则照念。
    对照放在同一条测试里 —— 替身没接上的话，下面两条断言会一起变，不会是假绿。"""
    read: List[str] = []

    async def reply(*_a, **_k):
        return {"success": True, "response": "查完了"}

    rt = DesktopPresenceRuntime()
    rt._dispatch = reply
    with patch("core.speech_output.speak_response", lambda text, source="": read.append(source)):
        await rt.handle_request("查一下", source="ambient")
        assert read == [], "自发委托的回复不该被念出来"
        await rt.handle_request("查一下", source="chat")
    assert read == ["chat"], "对照：对话来源照常朗读（替身确实接上了）"


async def test_every_incident_is_logged_not_swallowed(spoken, caplog):
    class Broken:
        async def handle_request(self, **kw):
            raise RuntimeError("x")

    loop = _loop(Scripted(_delegate()))
    with caplog.at_level(logging.WARNING, logger="Galaxy.Ambient"):
        with patch("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: Broken()):
            await loop.tick()
    assert any("后台任务没跑完" in r.getMessage() for r in caplog.records), "失败只在状态里、日志里没有"


# ── 5. 面板能问到：额度用了多少、哪些事没做完 ─────────────────────────────


@pytest.fixture
def fresh_loop():
    from core.ambient_attention_loop import get_ambient_loop, reset_ambient_loop

    reset_ambient_loop()
    yield get_ambient_loop()
    reset_ambient_loop()


def _client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.routes.panel import create_router

    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app)


async def test_the_panel_can_ask_how_much_is_left_and_what_did_not_finish(fresh_loop, monkeypatch):
    monkeypatch.delenv("GALAXY_AMBIENT_LOOP", raising=False)

    async def failed():
        return False

    fresh_loop.governor.charge(AmbientAction.SPEAK)
    await fresh_loop.governor.run_delegate(failed(), _delegate("整理下载文件夹"))

    body = _client().get("/api/v1/presence/ambient-status").json()

    assert body["success"] is True and body["enabled"] is True and body["running"] is False
    assert body["budget"]["speak"]["used"] == 1 and body["budget"]["speak"]["limit"] == 12
    assert body["budget"]["delegate"]["used"] == 1 and body["budget"]["delegate"]["limit"] == 6
    (incident,) = body["incidents"]
    assert incident["kind"] == "delegate_failed" and incident["task"] == "整理下载文件夹"
    assert "不会自动重试" in incident["explanation"]


async def test_the_status_route_filters_incidents_by_the_moment_the_panel_last_saw(fresh_loop):
    import time

    async def failed():
        return False

    await fresh_loop.governor.run_delegate(failed(), _delegate())
    client = _client()
    assert len(client.get("/api/v1/presence/ambient-status", params={"since": 0}).json()["incidents"]) == 1
    later = client.get("/api/v1/presence/ambient-status", params={"since": time.time() + 5}).json()
    assert later["incidents"] == [], "提示过的时刻之后没有新事，就不该再给"
    assert later["budget"]["delegate"]["used"] == 1, "过滤只管留痕，额度照常报"


def test_the_status_route_says_so_when_the_loop_is_switched_off(fresh_loop, monkeypatch):
    monkeypatch.setenv("GALAXY_AMBIENT_LOOP", "0")
    assert _client().get("/api/v1/presence/ambient-status").json()["enabled"] is False


def test_the_two_budgets_are_real_config_keys_with_the_defaults_the_code_uses():
    """面板「全部设置」里的默认值必须就是治理层真用的默认值 —— 否则面板显示的「默认」是假的。"""
    from core.ambient_governance import DEFAULT_DELEGATE_PER_HOUR, DEFAULT_SPEAK_PER_HOUR
    from core.routes.config import CONFIG_SCHEMA

    assert CONFIG_SCHEMA["GALAXY_AMBIENT_SPEAK_PER_HOUR"]["default"] == str(DEFAULT_SPEAK_PER_HOUR)
    assert CONFIG_SCHEMA["GALAXY_AMBIENT_DELEGATE_PER_HOUR"]["default"] == str(DEFAULT_DELEGATE_PER_HOUR)
