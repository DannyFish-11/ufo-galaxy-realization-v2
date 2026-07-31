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


@pytest.fixture(autouse=True)
def _restore_bridge_singleton():
    """跑完把 ``GalaxyPresenceBridge`` 单例还原掉 —— 本文件会往它身上挂桩。

    ``_fresh()`` 每次都重建单例,所以**本文件内部**互不干扰;问题出在**跑完之后**:
    单例停在最后一条用例留下的那个实例上,而它的 ``_try_ipc_http`` / ``_ws_broadcast``
    已经被换成了写进**局部 list** 的 lambda。下一个文件 ``get_instance()`` 拿到的就是它,
    于是它的每一次广播都掉进一个再也没人看的列表里。

    实测受害者:``tests/test_tts_speaking_overlay_sync.py`` 的
    ``test_speak_response_toggles_overlay_speaking_during_playback`` ——
    ``覆盖层应先后收到 speaking=True/False; got [False]``。那唯一的 ``False`` 帧是
    ``register_client()`` 里 ``_send_to()`` **直接**发的,没走 ``_ws_broadcast``;真正
    要验的 ``True`` 脉冲则全被泄漏的 lambda 吞掉。它单跑一直是绿的,只在全量套件里红。

    置 ``_instance = None`` 而不是逐个恢复方法:下一个使用者会拿到一个干净新建的实例,
    不必去猜本文件到底挂了哪几个桩。
    """
    GalaxyPresenceBridge._instance = None
    try:
        yield
    finally:
        GalaxyPresenceBridge._instance = None


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


class TestBroadcastStateDualChannel:
    """回归锁定:_broadcast_state 必须【总是】同时推 IPC 与 WS,不能因 IPC 成功就跳过 WS。

    背景真 bug:此前 IPC 成功即 return、跳过 WS 广播(注释假设两条通道是互斥的部署
    形态)。但面板窗口自身还会直连 /ws/desktop-presence(与 IPC→main.js 转发给面板
    是同一 App 内并存的两条独立通道,不是二选一)。之前 IPC 端口错配时它恒失败,才
    "意外"让 WS 广播兜底工作;端口对齐后 IPC 稳定成功,WS 广播被跳过,面板直连 WS
    上的相位只在连接瞬间收到一次快照、之后再收不到任何状态更新——表现为"卡住不动、
    行为怪异"。此测试锁定:无论 IPC 成功与否,WS 广播都必须被调用。
    """

    def test_ws_broadcast_still_called_when_ipc_succeeds(self):
        async def run():
            b = _fresh()
            b._try_ipc_http = lambda msg: _true()  # 模拟 IPC 成功
            captured = []
            b._ws_broadcast = lambda msg: _capture(captured, msg)
            await b._broadcast_state()
            return captured

        captured = asyncio.run(run())
        assert captured, "IPC 成功时 WS 广播被跳过——面板直连 WS 通道会失去实时状态更新"

    def test_ws_broadcast_still_called_when_ipc_fails(self):
        async def run():
            b = _fresh()  # _fresh() 默认 _try_ipc_http 返回 False
            captured = []
            b._ws_broadcast = lambda msg: _capture(captured, msg)
            await b._broadcast_state()
            return captured

        captured = asyncio.run(run())
        assert captured, "IPC 失败时 WS 广播理应作为唯一通道正常工作"


async def _true():
    return True
