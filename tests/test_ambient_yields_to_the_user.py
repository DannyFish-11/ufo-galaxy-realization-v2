"""自发注意力给用户让路：用户的请求在跑时不碰模型、调用进行中用户来了就放弃、用时长就多歇。

真机启动日志：本地 gemma 一次决策 38~48 秒；SILENT 决策不打冷却，屏幕一直在变就是一个调用接一个调用。
Ollama 一次只算一个 —— 用户发的「你好」排在自发观察后面，90 秒超时（``chat_stream 超时(90s)``）。
"""

from __future__ import annotations

import asyncio
import time

import pytest

import core.ambient_yield as ay
from core.ambient_attention_loop import AmbientAction, AmbientAttentionLoop, AmbientDecision
from core.presence_line import foreground_request_active
from tests.test_ambient_attention_loop import _BLACK, _WHITE, FakeBus, FakeDecider, FakeStore, FakeUM, FakeWM


def _loop(store, decider, **kw):
    return AmbientAttentionLoop(
        decider=decider,
        perception_store=store,
        working_memory=FakeWM(),
        unified_memory=FakeUM(),
        event_bus=FakeBus(),
        cooldown_s=0.0,
        **kw,
    )


SILENT = AmbientDecision(action=AmbientAction.SILENT, rationale="没事")


class _S:
    def __init__(self, source, rid):
        self.source = source
        self.runtime_session_id = rid


class TestForegroundRequestActive:
    def test_a_user_chat_counts(self):
        assert foreground_request_active([_S("chat", "r1")]) is True

    def test_background_sources_do_not_count(self):
        assert (
            foreground_request_active([_S("ambient", "r1"), _S("heartbeat", "r2"), _S("active_perception", "r3")])
            is False
        )

    def test_a_persistent_presence_is_presence_not_a_request_someone_waits_on(self):
        assert foreground_request_active([_S("voice_duplex", "p1")], persistent_handles=["p1"]) is False

    def test_voice_and_nothing_at_all(self):
        assert foreground_request_active([_S("voice", "r1")]) is True
        assert foreground_request_active([]) is False

    def test_the_runtime_exposes_it_over_its_own_sessions(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        rt = DesktopPresenceRuntime()
        assert rt.foreground_request_active() is False
        s = rt._create_session("chat")
        assert rt.foreground_request_active() is True
        rt._active_sessions.pop(s.runtime_session_id)
        handle = rt.open_ambient_presence("voice_duplex", reason="t")
        assert rt.foreground_request_active() is False  # 常驻在场不算
        rt.close_ambient_presence(handle)


class TestYielding:
    @pytest.mark.asyncio
    async def test_tick_does_not_call_the_model_while_a_user_request_runs(self, monkeypatch):
        monkeypatch.setattr(ay, "_foreground_busy", lambda: True)
        decider = FakeDecider(SILENT)
        loop = _loop(FakeStore({"screen_b64": _BLACK}), decider)
        assert await loop.tick() is None
        assert decider.calls == 0 and loop.yielded == 1

    @pytest.mark.asyncio
    async def test_the_look_that_was_given_up_is_made_up_once_the_user_is_done(self, monkeypatch):
        busy = {"v": True}
        monkeypatch.setattr(ay, "_foreground_busy", lambda: busy["v"])
        decider = FakeDecider(SILENT)
        store = FakeStore({"screen_b64": _BLACK})
        loop = _loop(store, decider)
        await loop.tick()  # 用户在等：让路；门控已经把这一帧当看过了
        busy["v"] = False
        # 画面没再变，但上一拍是让路挡下的 → 这一拍要补看
        assert await loop.tick() is not None
        assert decider.calls == 1
        # 补看过就不再重复
        assert await loop.tick() is None
        assert decider.calls == 1

    @pytest.mark.asyncio
    async def test_a_decision_in_flight_is_abandoned_when_the_user_arrives(self, monkeypatch):
        cancelled = asyncio.Event()

        class SlowDecider:
            async def decide(self, obs):
                try:
                    await asyncio.sleep(30)  # 本地模型一次算 40 秒
                except asyncio.CancelledError:
                    cancelled.set()
                    raise

        busy = {"v": False}
        monkeypatch.setattr(ay, "_foreground_busy", lambda: busy["v"])
        monkeypatch.setattr(ay, "_FOREGROUND_POLL_S", 0.02)
        loop = _loop(FakeStore({"screen_b64": _BLACK}), SlowDecider())

        async def user_arrives():
            await asyncio.sleep(0.1)
            busy["v"] = True

        arrival = asyncio.create_task(user_arrives())
        t0 = time.monotonic()
        result = await loop.tick()
        await arrival
        assert result is None
        assert cancelled.is_set(), "进行中的模型调用必须被取消，Ollama 才会停下来"
        assert time.monotonic() - t0 < 2.0
        assert loop.yielded == 1 and loop._deferred is True

    @pytest.mark.asyncio
    async def test_a_long_call_makes_the_loop_rest_in_proportion(self, monkeypatch):
        monkeypatch.setattr(ay, "_foreground_busy", lambda: False)

        class Slowish:
            calls = 0

            async def decide(self, obs):
                self.calls += 1
                await asyncio.sleep(0.2)
                return SILENT

        decider = Slowish()
        store = FakeStore({"screen_b64": _BLACK})
        loop = _loop(store, decider)
        assert await loop.tick() is not None
        assert loop._rest_until - time.time() > 0.3  # 用了 0.2 秒 → 至少歇 3 倍

        store.set(screen_b64=_WHITE)  # 画面又变了，但还在歇
        assert await loop.tick() is None
        assert decider.calls == 1 and loop._deferred is True

    @pytest.mark.asyncio
    async def test_a_fast_decision_barely_rests_so_cloud_brains_are_not_slowed(self, monkeypatch):
        monkeypatch.setattr(ay, "_foreground_busy", lambda: False)
        decider = FakeDecider(SILENT)
        loop = _loop(FakeStore({"screen_b64": _BLACK}), decider)
        await loop.tick()
        assert loop._rest_until - time.time() < 0.1
