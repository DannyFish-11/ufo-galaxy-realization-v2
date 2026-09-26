"""声字同文：它说出口的每一句话，同时就在面板那份上下文里。

面板开着，字跟着声音出来；面板关了，字也一句不少 —— 再打开时从后端把**同一条
会话**读回来，前后都齐。所以要钉的是两件事：

* **记在哪儿**：语音、双工、它自己开口，都记进同一条对话主线
  （``core.conversation_mainline``），面板打开时读的也是这一条（``/api/v1/sessions/primary``）；
* **推到哪儿**：说的同时推到面板的对话通道 —— 双工边说边出字、收尾时合上；
  面板自己发起的那一轮带着 ``client_id``，它认得出自己的回声。
"""

from __future__ import annotations

import types

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.conversation_mainline as mainline
import core.lumiv_websocket_bridge as bridge_mod
from core.lumiv_websocket_bridge import GalaxyPresenceBridge, emit_conversation

# ── 主线：判据只有一份 ─────────────────────────────────────────────────────


class _FakeSessions:
    def __init__(self, primary: str = "", created: str = "new-1") -> None:
        self.primary = primary
        self.created = created
        self.create_calls = []

    def get_primary_session_id(self):
        return self.primary

    def get_or_create_session_sync(self, owner, device_id):
        self.create_calls.append((owner, device_id))
        return types.SimpleNamespace(id=self.created)


@pytest.fixture
def sessions(monkeypatch):
    fake = _FakeSessions()
    import core.session_manager as sm_mod

    monkeypatch.setattr(sm_mod, "get_session_manager", lambda: fake)
    return fake


def test_the_mainline_is_the_primary_conversation(sessions):
    sessions.primary = "chat-7"
    assert mainline.mainline_session_id() == "chat-7"
    assert mainline.mainline_session_id(create=True) == "chat-7"
    assert sessions.create_calls == [], "已经有主线时不该另开一条"


def test_no_conversation_yet_is_empty_unless_asked_to_open_one(sessions):
    assert mainline.mainline_session_id() == "", "还没聊过就是空 —— 不能凭空编一个"
    assert mainline.mainline_session_id(create=True) == "new-1"
    assert sessions.create_calls == [(mainline.DEFAULT_MAINLINE_OWNER, "")]


def test_the_new_mainline_is_owned_like_a_panel_conversation():
    """与面板发起对话时的身份同源，才落在同一套记忆里。"""
    assert mainline.DEFAULT_MAINLINE_OWNER == "device::default"


def test_a_broken_session_manager_falls_back_to_empty(monkeypatch):
    import core.session_manager as sm_mod

    def boom():
        raise RuntimeError("down")

    monkeypatch.setattr(sm_mod, "get_session_manager", boom)
    assert mainline.mainline_session_id(create=True) == ""


def test_the_panel_can_ask_which_conversation_is_the_mainline(monkeypatch):
    from core.routes.sessions import create_router

    monkeypatch.setattr(mainline, "mainline_session_id", lambda create=False: "chat-7")
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app)
    resp = client.get("/api/v1/sessions/primary")
    assert resp.status_code == 200
    assert resp.json() == {
        "success": True,
        "session_id": "chat-7",
    }, "「primary」被当成了一个会话 id —— 它必须注册在 /api/v1/sessions/{session_id} 之前"


# ── 推到面板：对话通道的帧 ─────────────────────────────────────────────────


@pytest.fixture
def frames(monkeypatch):
    sent = []
    b = GalaxyPresenceBridge.get_instance()
    monkeypatch.setattr(b, "_broadcast_conversation", lambda msg: sent.append(msg))
    monkeypatch.setattr(bridge_mod, "_schedule", lambda _coro: None)
    return sent


def test_frames_carry_who_started_the_turn(frames):
    emit_conversation("user", "你好", source="text", client_id="hud-1")
    (msg,) = frames
    assert msg["type"] == "conversation"
    assert msg["payload"]["client_id"] == "hud-1", "面板认不出自己的回声，同一句话会画两遍"


def test_a_streamed_reply_is_closed_by_an_empty_final_frame(frames):
    emit_conversation("ai", "我在", source="voice", final=False)
    emit_conversation("ai", "", source="voice", final=True)
    assert [m["payload"]["final"] for m in frames] == [False, True]
    assert frames[1]["payload"]["text"] == ""


def test_other_empty_frames_are_still_dropped(frames):
    emit_conversation("ai", "  ", final=False)
    emit_conversation("user", "", final=True)
    assert frames == [], "空帧只在合上一句 AI 回复时有意义，别的空帧照旧丢掉"


# ── 它自己开口 ─────────────────────────────────────────────────────────────


async def test_what_it_says_on_its_own_reaches_the_panel_and_the_mainline(monkeypatch):
    from core.ambient_attention_loop import AmbientAttentionLoop

    emitted = []
    recorded = []

    async def fake_record(**kwargs):
        recorded.append(kwargs)

    import core.session_memory_facade as facade

    monkeypatch.setattr(bridge_mod, "emit_conversation", lambda role, text, **kw: emitted.append((role, text, kw)))
    monkeypatch.setattr(facade, "record_session_turn", fake_record)
    monkeypatch.setattr(mainline, "mainline_session_id", lambda create=False: "chat-7" if create else "")

    loop = AmbientAttentionLoop.__new__(AmbientAttentionLoop)
    await loop._record_spoken("  你刚才那个文件还没存  ")

    assert emitted == [("ai", "你刚才那个文件还没存", {"source": "ambient"})]
    assert len(recorded) == 1
    turn = recorded[0]
    assert turn["conversation_session_id"] == "chat-7"
    assert turn["role"] == "assistant"
    assert turn["content"] == "你刚才那个文件还没存"
    assert turn["metadata"]["channel"] == "ambient"


async def test_nothing_is_recorded_for_an_empty_utterance(monkeypatch):
    from core.ambient_attention_loop import AmbientAttentionLoop

    emitted = []
    monkeypatch.setattr(bridge_mod, "emit_conversation", lambda *a, **k: emitted.append(a))
    loop = AmbientAttentionLoop.__new__(AmbientAttentionLoop)
    await loop._record_spoken("   ")
    assert emitted == []


# ── 双工：边说边出字，收尾与叫停时合上 ────────────────────────────────────


@pytest.fixture
def voice(monkeypatch):
    from core.voice_loop import VoiceLoop

    emitted = []
    monkeypatch.setattr(
        bridge_mod,
        "emit_conversation",
        lambda role, text, **kw: emitted.append((role, text, kw.get("final"), kw.get("source"))),
    )
    loop = VoiceLoop.__new__(VoiceLoop)
    loop._duplex_ai_open = False
    loop._duplex = None
    loop._duplex_player = None
    return loop, emitted


def test_a_duplex_delta_is_streamed_to_the_panel(voice):
    loop, emitted = voice
    loop._emit_panel("ai", "我看", final=False)
    assert emitted == [("ai", "我看", False, "voice")]


def test_closing_a_reply_sends_exactly_one_final_frame(voice):
    loop, emitted = voice
    loop._close_panel_ai_turn()
    assert emitted == [], "没有在流的那一句，就没有可合上的"

    loop._duplex_ai_open = True
    loop._close_panel_ai_turn()
    loop._close_panel_ai_turn()
    assert emitted == [("ai", "", True, "voice")]


async def test_stopping_duplex_cuts_the_sentence_but_keeps_the_session(voice):
    loop, emitted = voice
    calls = []

    class _Session:
        async def interrupt(self):
            calls.append("interrupt")

    class _Player:
        def flush(self):
            calls.append("flush")

        def unduck(self):
            calls.append("unduck")

        def stop(self):  # 不该被调到：住手不是收摊
            calls.append("stop")

    loop._duplex = _Session()
    loop._duplex_player = _Player()
    loop._duplex_ai_open = True
    await loop._duplex_stop_current()
    assert calls == ["interrupt", "flush", "unduck"], "缓冲里已经下行的半句不丢掉，停了之后它还会念完"
    assert emitted == [("ai", "", True, "voice")]


def test_duplex_turns_are_recorded_into_the_mainline():
    """双工的轮次记进主线，而不是每开一次自建一条 duplex-<时间戳>。"""
    import inspect

    from core.voice_loop import VoiceLoop

    src = inspect.getsource(VoiceLoop)
    assert "conversation_session_id=mainline_session_id()" in src
    assert "on_interrupt=self._duplex_stop_current" in src
