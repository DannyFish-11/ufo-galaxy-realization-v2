#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_new_device_learns_the_current_phase.py

一台**刚接进来**的设备,得知道桌面此刻是什么状态。

为什么这是单独的一件事
======================
相位是**跃迁广播**:只在 silent→liminal 这种时刻才发。设备是在两次跃迁之间连上来
的,所以它永远赶不上任何一次广播 —— 除非有人在它连上时补一次"现在是什么"。

不补的后果不是"暂时没有",而是**显示成错的**:设备侧没有相位就渲染静默。
于是桌面正忙着执行,刚戴上的手表显示"静默",要一直等到下一次相位变化才纠正过来。
而如果桌面就停在 manifest 不动,那就是永远。

Android 的注册路径一直有这一步,WearOS 走的是另一条(``websocket_handler``),漏了。
它没被发现是因为手表自己拿连接态凑了个相位(鉴权成功即 MANIFEST)—— 那个值跟桌面
没有任何关系,只是"看起来有内容"。凑的那份撤掉之后,这一步就成了承重的。
"""

from __future__ import annotations

import pytest

import core.cross_device_sync as cds


class _FakeConnectionManager:
    def __init__(self, *, fail: bool = False):
        self.sent: list = []
        self._fail = fail

    async def send_to_device(self, device_id, msg):
        if self._fail:
            raise ConnectionError("socket closed")
        self.sent.append((device_id, msg))


@pytest.fixture
def wired(monkeypatch):
    """把"当前相位"与"怎么发出去"两个外部依赖都换成可观测的替身。"""

    def _wire(phase, *, fail=False):
        cm = _FakeConnectionManager(fail=fail)

        class _DPR:
            def get_current_phase(self):
                return phase

        import sys
        import types

        fake_rt = types.ModuleType("core.desktop_presence_runtime")
        fake_rt.get_desktop_presence_runtime = lambda: _DPR()  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "core.desktop_presence_runtime", fake_rt)

        fake_ws = types.ModuleType("galaxy_gateway.websocket_handler")
        fake_ws.connection_manager = cm  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "galaxy_gateway.websocket_handler", fake_ws)
        return cm

    return _wire


# ---------------------------------------------------------------------------
# 一、接进来就该拿到当前相位
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["silent", "liminal", "manifest"])
async def test_a_new_device_is_told_the_current_phase(wired, phase):
    cm = wired(phase)
    assert await cds.push_current_phase_to_device("watch-1") is True
    assert len(cm.sent) == 1
    device_id, msg = cm.sent[0]
    assert device_id == "watch-1"
    # 手表读 payload.to_phase,手机读顶层 event_action —— 两处都得对。
    assert msg["payload"]["to_phase"] == phase
    assert msg["event_action"] == phase


@pytest.mark.asyncio
async def test_it_is_marked_as_an_initial_sync_not_a_transition(wired):
    """标成跃迁的话,设备会以为刚发生了一次相变,震动 + 动效全跑一遍。

    人只是把表戴上,不该感觉像是"出事了"。
    """
    cm = wired("manifest")
    await cds.push_current_phase_to_device("watch-1")
    payload = cm.sent[0][1]["payload"]
    assert payload["sync_type"] == "cross_device_initial_sync"
    assert payload["from_phase"] == "unknown"


@pytest.mark.asyncio
async def test_silent_is_pushed_too_rather_than_skipped_as_falsy(wired):
    """``silent`` 是一个**真实答案**,不是"没有答案"。

    区分度:实现里若写成 ``if phase:`` 之外还顺手跳过 silent(或把它当默认值省掉),
    设备就分不清"桌面确实静默"和"我还没被告知" —— 而这两者的正确显示恰好一样,
    所以肉眼永远看不出来。
    """
    cm = wired("silent")
    assert await cds.push_current_phase_to_device("watch-1") is True
    assert cm.sent[0][1]["payload"]["to_phase"] == "silent"


# ---------------------------------------------------------------------------
# 二、拿不到就如实返回 False,别假装推过
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_phase_available_means_no_push_and_says_so(wired):
    cm = wired("")
    assert await cds.push_current_phase_to_device("watch-1") is False
    assert cm.sent == []


@pytest.mark.asyncio
async def test_a_dead_socket_is_reported_not_swallowed_as_success(wired):
    """返回 True 而实际没发出去,会让"设备已同步"成为一句假话。"""
    cm = wired("liminal", fail=True)
    assert await cds.push_current_phase_to_device("watch-1") is False
    assert cm.sent == []


@pytest.mark.asyncio
async def test_presence_runtime_missing_is_non_fatal(monkeypatch):
    """相位来源不可用不该把设备注册整条拖垮 —— 注册成功比相位准确更要紧。"""
    import sys

    monkeypatch.setitem(sys.modules, "core.desktop_presence_runtime", None)
    assert await cds.push_current_phase_to_device("watch-1") is False


# ---------------------------------------------------------------------------
# 三、注册路径真的调了它
# ---------------------------------------------------------------------------


def test_the_wearos_register_path_calls_it():
    """光有函数不算接上 —— 这正是 WearOS 漏掉这一步的方式:能力在,没人调。"""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "galaxy_gateway" / "websocket_handler.py").read_text(
        encoding="utf-8"
    )
    assert "push_current_phase_to_device" in src, "WearOS 注册路径没有补推当前相位"
