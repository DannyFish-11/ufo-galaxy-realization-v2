"""对话主线只在电脑这边的对话里选 —— 手机、手表各有各的对话。

背景：语音回合、电脑自发开口、自发委托、面板重开读上下文，用的都是「对话主线」
（``core.conversation_mainline`` → ``SessionManager.get_primary_session_id``）。它原先取**所有设备里**
最近活跃的真实对话，不看发起方：手机发一句话，电脑的主线就切到手机那段，之后电脑上说的话记进手机的会话。
与「入口分流」（别的设备发起的请求不进桌面三态，见 ``core/presence_line.py``）是同一条分界的另一面：
三态管表达，这里管上下文。

判据是建会话时记下的 ``metadata["origin_device"]``，而不是事后看 ``devices`` —— 别的设备往一条会话里写话
会被 append 进 ``devices``，电脑起头、手机后来接着聊的那条不该因此变成手机的。
手表走的是 ``wear_voice``（不带 session_id，会话按 ``device::<手表id>`` 另起），与手机同一条路。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from core import presence_line
from core.presence_line import session_is_desktop_thread


@pytest.fixture()
def sm(tmp_path, monkeypatch):
    import core.session_manager as smmod

    monkeypatch.setattr(smmod, "_SESSION_FILE", str(tmp_path / "sessions.json"))
    mgr = smmod.SessionManager()
    monkeypatch.setattr(smmod, "_session_manager", mgr)
    monkeypatch.setenv("GALAXY_DEVICE_ID", "desk-host")
    monkeypatch.setattr(presence_line, "_registered_local_ids", set())
    return mgr


def _say(sm, sid, text, device_id=""):
    asyncio.run(sm.add_message(sid, "user", text, device_id=device_id))
    time.sleep(0.005)  # updated_at 要能分出先后


def _desktop_chat(sm):
    s = asyncio.run(sm.create_session("device::default", ""))  # 面板发起：不带设备号
    _say(sm, s.id, "帮我整理桌面")
    return s


def test_a_phone_that_just_spoke_does_not_become_the_desktop_mainline(sm):
    from core.conversation_mainline import mainline_session_id

    desk = _desktop_chat(sm)
    phone = asyncio.run(sm.create_session("device::phone-1", "phone-1"))
    _say(sm, phone.id, "明天几点的闹钟", "phone-1")

    assert phone.updated_at > desk.updated_at, "前提：手机那段更新"
    assert sm.get_primary_session_id() == desk.id
    assert mainline_session_id() == desk.id


def test_the_watch_gets_its_own_conversation_and_never_becomes_the_mainline(sm):
    """手表语音（``wear_voice``，不带 session_id）走 build_canonical_session_identity，会话按设备另起并复用。"""
    from core.conversation_mainline import mainline_session_id
    from core.session_identity import build_canonical_session_identity

    desk = _desktop_chat(sm)
    first = build_canonical_session_identity(device_id="watch-1")
    _say(sm, first.conversation_session_id, "几点了", "watch-1")
    second = build_canonical_session_identity(device_id="watch-1")
    _say(sm, second.conversation_session_id, "再说一遍", "watch-1")

    assert second.conversation_session_id == first.conversation_session_id, "手表自己的对话跨句续得上"
    assert first.conversation_session_id != desk.id
    assert mainline_session_id() == desk.id, "手表说话不改电脑的主线"


def test_the_watch_can_still_continue_the_desktop_thread_when_it_asks_to(sm):
    """显式带上电脑主线的 session_id（``GET /api/v1/sessions/primary``）：接进来后它仍是电脑起头的那条。"""
    from core.conversation_mainline import mainline_session_id
    from core.session_identity import build_canonical_session_identity

    desk = _desktop_chat(sm)
    ident = build_canonical_session_identity(session_id=mainline_session_id(), device_id="watch-1")
    assert ident.conversation_session_id == desk.id
    _say(sm, desk.id, "（手表接着问）几点了", "watch-1")

    assert "watch-1" in sm.get_session(desk.id).devices, "手表确实进了这条会话"
    assert sm.get_primary_session_id() == desk.id, "但它仍是电脑的主线，不会因为手表进来过就被排除"


def test_a_phone_conversation_the_desktop_joined_counts_as_desktop(sm):
    phone = asyncio.run(sm.create_session("device::phone-1", "phone-1"))
    assert not session_is_desktop_thread(phone)
    asyncio.run(sm.ensure_session(phone.id, device_id="desk-host"))  # 电脑自己也进了这条会话
    assert session_is_desktop_thread(sm.get_session(phone.id))


def test_a_reconciled_phone_session_merges_into_the_desktop_mainline(sm):
    """跨设备统一上下文：手机本地会话经别名认领到电脑主线，之后带着手机本地 id 进来的都归并到电脑那条。"""
    from core.session_identity import build_canonical_session_identity

    desk = _desktop_chat(sm)
    assert sm.register_session_alias("phone_local_7", desk.id)
    ident = build_canonical_session_identity(session_id="phone_local_7", device_id="phone-1")
    assert ident.conversation_session_id == desk.id
    _say(sm, desk.id, "（手机离线时说的）", "phone-1")
    assert sm.get_primary_session_id() == desk.id


def test_who_started_it_survives_a_restart(sm, tmp_path, monkeypatch):
    import core.session_manager as smmod

    phone = asyncio.run(sm.create_session("device::phone-1", "phone-1"))
    desk = _desktop_chat(sm)
    assert phone.metadata["origin_device"] == "phone-1" and desk.metadata["origin_device"] == ""
    restored = smmod.Session.from_dict(phone.to_dict())
    assert restored.metadata["origin_device"] == "phone-1"
    assert not session_is_desktop_thread(restored)


def test_conversations_from_before_the_stamp_keep_the_old_behaviour(sm):
    """落盘时没记起头的老会话：判不出来，按原样算电脑的（不凭空把用户已有的对话排除掉）。"""
    old = asyncio.run(sm.create_session("device::phone-1", "phone-1"))
    old.metadata.pop("origin_device")
    assert session_is_desktop_thread(old)


def test_the_ambient_delegate_and_the_panel_read_the_same_selector(sm):
    """自发委托与面板重开读的是同一份判据 —— 不会一个选电脑的、一个选手机的。"""
    import inspect

    from core import ambient_attention_loop

    assert "get_primary_session_id" in inspect.getsource(ambient_attention_loop)
    desk = _desktop_chat(sm)
    phone = asyncio.run(sm.create_session("device::phone-1", "phone-1"))
    _say(sm, phone.id, "x", "phone-1")
    assert sm.get_primary_session_id() == desk.id
