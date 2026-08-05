#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_presence_ipc_session_is_shared.py

钉住在场桥那条 IPC 通道的会话复用，以及它的两个**必须重建**的时机。

背景
====
``GalaxyPresenceBridge._try_ipc_http`` 是本机 Python → Electron 的推送通道
（``POST http://127.0.0.1:<port>/ipc/presence-state``）。它不是偶发调用：阈限期由
200ms 的 continuum tick 发 ``intent.update`` 驱动广播，**每秒 5 次**。

原先每次广播都 ``async with aiohttp.ClientSession()``，等于每 200ms 新建一个
连接器 + 一条到本机的 TCP 连接再拆掉。同机实测（200 次 POST 到真实本地服务端）：

    每次新建 Session   中位 0.83 ms   p95 1.15 ms
    复用 Session       中位 0.28 ms   p95 0.41 ms

省下的是**事件循环上的时间**，而那条循环同时在服务正在处理的那个请求。

但"缓存一个 Session"有个会咬人的前提：aiohttp 的 Session 绑死创建它的事件循环。
缓存跨循环会在下一个循环里抛 "Event loop is closed"，而调用方吞异常返回 ``False``，
症状是「IPC 从某个时刻起永远失败、WS 兜底默默顶上」——指不回缓存这里。所以
**复用**与**按循环重建**这两条必须一起钉。

这里用一个替身 ClientSession：被测的是缓存逻辑，不是 aiohttp，真开 socket 只会让
判据变糊。
"""

from __future__ import annotations

import asyncio
import types

import pytest

from core.lumiv_websocket_bridge import GalaxyPresenceBridge


class _FakeSession:
    """只提供缓存逻辑用得到的两件事：``closed`` 与 ``close()``。"""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _stub_aiohttp(monkeypatch):
    """把桥模块里的 aiohttp 换成替身，并在每个用例前后清空缓存。"""
    import core.lumiv_websocket_bridge as bridge_mod

    monkeypatch.setattr(bridge_mod, "aiohttp", types.SimpleNamespace(ClientSession=_FakeSession))
    GalaxyPresenceBridge._ipc_http_session = None
    GalaxyPresenceBridge._ipc_http_loop = None
    yield
    GalaxyPresenceBridge._ipc_http_session = None
    GalaxyPresenceBridge._ipc_http_loop = None


async def _grab():
    return GalaxyPresenceBridge._ipc_session()


def _in_fresh_loop(coro_factory):
    """在一个全新的事件循环里跑一次，返回结果。循环随即关闭。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro_factory())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# 一、同一个循环里复用
# ---------------------------------------------------------------------------


def test_session_is_reused_within_one_event_loop():
    """连续取两次必须是**同一个对象**。

    钉同一性而不是"不报错"：每次新建也不会报错，只是慢 3 倍 —— 那种退化没有任何
    可观测症状，只有身份断言抓得住。
    """

    async def twice():
        return GalaxyPresenceBridge._ipc_session(), GalaxyPresenceBridge._ipc_session()

    first, second = _in_fresh_loop(twice)
    assert first is second, "IPC 会话每次都在新建 —— 200ms 一拍的广播上这是 3 倍开销"


# ---------------------------------------------------------------------------
# 二、两个必须重建的时机
# ---------------------------------------------------------------------------


def test_session_is_rebuilt_when_the_event_loop_changes():
    """换了事件循环必须换 Session。

    这一条是缓存能不能成立的前提：aiohttp 的 Session 绑死创建它的循环，跨循环复用
    会抛 "Event loop is closed"，而调用方吞异常返回 False —— 表现为 IPC 从某刻起
    永远失败，故障现场什么都不剩。
    """
    first = _in_fresh_loop(_grab)
    assert not first.closed, "前置条件：第一个会话没被关闭，所以重建只可能是因为换了循环"
    second = _in_fresh_loop(_grab)
    assert first is not second, "换了事件循环还在复用旧 Session —— 下一拍就会 'Event loop is closed'"


def test_closed_session_is_rebuilt():
    """会话被关掉之后必须重建，不能把一个已关闭的 Session 一直发下去。"""

    async def close_then_grab():
        first = GalaxyPresenceBridge._ipc_session()
        await first.close()
        return first, GalaxyPresenceBridge._ipc_session()

    first, second = _in_fresh_loop(close_then_grab)
    assert first.closed
    assert first is not second


# ---------------------------------------------------------------------------
# 三、aiohttp 缺席时不炸
# ---------------------------------------------------------------------------


def test_ipc_push_degrades_quietly_without_aiohttp(monkeypatch):
    """aiohttp 装不上时 IPC 推送返回 False，由 WS 广播兜底 —— 不该抛。"""
    import core.lumiv_websocket_bridge as bridge_mod

    monkeypatch.setattr(bridge_mod, "aiohttp", None)
    bridge = GalaxyPresenceBridge.get_instance()

    async def push():
        return await bridge._try_ipc_http({"type": "state_event"})

    assert _in_fresh_loop(push) is False
