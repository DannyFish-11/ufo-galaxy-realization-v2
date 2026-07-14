"""tests/test_presence_bridge_functions.py
=============================================

锁定一类"东一榔头西一棒子"的真实 bug:core/lumiv_websocket_bridge.py 被
speech_output / voice_loop / routes.chat / voice_conversation_bridge / routes.panel
共 6 处 import 三个模块级名字——set_ai_speaking / emit_conversation /
get_current_phase——但这三个此前【从未定义】,每处 import 都 ImportError 被
try/except 静默吞掉,导致:面板实时对话恒空、AI 说话动画不随播放运转、面板相位
断线重连恒被拉回"待机"。本测试证明三者现已存在且行为正确。
"""

from __future__ import annotations

import asyncio

import pytest

import core.lumiv_websocket_bridge as bridge_mod
from core.lumiv_websocket_bridge import (
    GalaxyPresenceBridge,
    emit_conversation,
    get_current_phase,
    set_ai_speaking,
)


def _fresh():
    GalaxyPresenceBridge._instance = None
    b = GalaxyPresenceBridge.get_instance()
    b._try_ipc_http = lambda msg: _false()  # 抑制真实 IPC
    return b


async def _false():
    return False


class TestNamesExist:
    def test_all_three_importable_and_callable(self):
        # 仅"能 import + 能调用不抛"本身就是修复点（此前 import 即失败）。
        assert callable(set_ai_speaking)
        assert callable(emit_conversation)
        assert callable(get_current_phase)


class TestGetCurrentPhase:
    def test_maps_static_to_silent(self):
        b = _fresh()
        b._current_mode = "static"
        assert get_current_phase() == "silent"

    def test_liminal_manifest_passthrough(self):
        b = _fresh()
        b._current_mode = "liminal"
        assert get_current_phase() == "liminal"
        b._current_mode = "manifest"
        assert get_current_phase() == "manifest"

    def test_unknown_defaults_silent(self):
        b = _fresh()
        b._current_mode = "???"
        assert get_current_phase() == "silent"


class TestEmitConversation:
    def test_broadcasts_conversation_message_over_ws(self):
        async def run():
            b = _fresh()
            captured = []
            b._ws_broadcast = lambda msg: _capture(captured, msg)
            emit_conversation("ai", "你好呀", source="voice", speaking=True, turn_id="t1")
            await asyncio.sleep(0.02)
            return captured

        captured = asyncio.run(run())
        assert captured, "conversation 未广播"
        msg = captured[0]
        assert msg["type"] == "conversation"
        p = msg["payload"]
        assert p["role"] == "ai" and p["text"] == "你好呀"
        assert p["source"] == "voice" and p["speaking"] is True
        assert p["turn_id"] == "t1" and p["final"] is True

    def test_empty_text_not_broadcast(self):
        async def run():
            b = _fresh()
            captured = []
            b._ws_broadcast = lambda msg: _capture(captured, msg)
            emit_conversation("user", "   ")
            await asyncio.sleep(0.02)
            return captured

        assert asyncio.run(run()) == []

    def test_role_normalized(self):
        async def run():
            b = _fresh()
            captured = []
            b._ws_broadcast = lambda msg: _capture(captured, msg)
            emit_conversation("whatever", "hi")
            await asyncio.sleep(0.02)
            return captured

        assert asyncio.run(run())[0]["payload"]["role"] == "user"


class TestSetAiSpeaking:
    def test_sets_flag_and_broadcasts_state(self):
        async def run():
            b = _fresh()
            captured = []
            b._ws_broadcast = lambda msg: _capture(captured, msg)
            set_ai_speaking(True)
            await asyncio.sleep(0.02)
            return b._speaking, captured

        speaking, captured = asyncio.run(run())
        assert speaking is True
        assert captured and captured[0]["payload"]["speaking"] is True


async def _capture(sink, msg):
    sink.append(msg)
