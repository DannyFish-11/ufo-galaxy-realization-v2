"""所有者 Windows 真机日志里又两处在事件循环里干同步活::

    事件循环被卡住 2.2 秒 —— 卡在 core\\ollama_url_sentinel.py:140 _sync_send ← …
        _scan_local_models_sync ← core\\hardware_aware_multimodal_router.py:552 route_hint_sync
    事件循环被卡住 1.3 秒 —— 卡在 windows_service\\tray_icon.py:304 _redraw ← …:259 on_render
        ← core\\presence_fanout.py:45 _call

1. ``OpenClawd._select_multimodal_route`` 是同步的,它问的「本机有没有模型」原先当场同步
   ``httpx.get(…/api/tags, timeout=3)``,首次还要算硬件画像(import torch、问显卡);构造路由器
   时又同步探一次 Ollama(2 秒超时)。现在事件循环里只读缓存,过期由一根后台线程去刷。
2. 托盘那只桌宠跟着在场桥每一拍重画,而回调是在事件循环线程里调的。画一张桌宠 + 改托盘图标
   (Windows 上一次 ``Shell_NotifyIcon``)挪到一根专门的线程,循环里只比一下变没变。
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest


@pytest.fixture
def slow_ollama(monkeypatch):
    """Ollama 每问一次要 1 秒(真机上 3 秒超时、首次加载更久)。"""
    import core.hardware_aware_multimodal_router as H

    calls = []

    def _slow_check():
        calls.append(threading.current_thread().name)
        time.sleep(1.0)
        return False

    monkeypatch.setattr(H.HardwareAwareMultimodalRouter, "_check_ollama", staticmethod(_slow_check))
    import core.hardware_compute_profiler as P

    monkeypatch.setattr(P, "get_compute_profile_sync", lambda: None)
    return H, calls


def test_building_the_router_does_no_io(slow_ollama):
    H, calls = slow_ollama
    t0 = time.perf_counter()
    H.HardwareAwareMultimodalRouter()
    assert time.perf_counter() - t0 < 0.3
    assert calls == [], "构造时又去探 Ollama 了(openclawd 在事件循环里懒加载这个单例)"


def test_the_sync_hint_never_waits_on_the_loop(slow_ollama):
    H, calls = slow_ollama
    router = H.HardwareAwareMultimodalRouter()

    async def on_the_loop():
        t0 = time.perf_counter()
        router.route_hint_sync(task_type="vision", has_multimodal_input=True)
        return time.perf_counter() - t0

    took = asyncio.run(on_the_loop())
    assert took < 0.3, f"事件循环里等了 {took:.2f} 秒"
    deadline = time.monotonic() + 5
    while not calls and time.monotonic() < deadline:
        time.sleep(0.05)
    assert calls and calls[0] == "ha-router-refresh", "缓存过期却没有交给后台线程去刷"


def test_off_the_loop_it_still_scans_right_there(slow_ollama):
    """不在事件循环里(工作线程、脚本)照旧当场扫 —— 那里等得起,也要一个真答案。"""
    H, calls = slow_ollama
    router = H.HardwareAwareMultimodalRouter()
    models = router._scan_local_models_sync()
    assert calls == [threading.current_thread().name]
    assert set(models) >= {"llm", "vlm", "asr", "embedding"}


@pytest.fixture
def tray(monkeypatch):
    import windows_service.tray_icon as T

    monkeypatch.setattr(T, "_HAVE_TRAY", True)
    painted = []

    def _slow_paint(status, pet=None, react=None):
        time.sleep(0.5)
        painted.append(threading.current_thread().name)
        return object()

    monkeypatch.setattr(T, "create_icon_image", _slow_paint)
    t = T.GalaxyTray()
    t._icon = SimpleNamespace(icon=None, title="", stop=lambda: None)
    yield t, painted
    t.stop()


def _frame(sensing: bool) -> dict:
    return {"phase": "silent", "perception": {"source": "desktop", "is_sensing": sensing, "privacy_paused": False}}


def test_the_tray_paints_beside_the_loop(tray):
    t, painted = tray

    async def on_the_loop():
        t0 = time.perf_counter()
        t.on_render(_frame(True))
        return time.perf_counter() - t0

    took = asyncio.run(on_the_loop())
    assert took < 0.2, f"在场桥那一拍在托盘重画上等了 {took:.2f} 秒"
    deadline = time.monotonic() + 5
    while not painted and time.monotonic() < deadline:
        time.sleep(0.05)
    assert painted and painted[0].startswith("TrayPaint"), painted


def test_the_tray_still_paints_in_place_without_a_loop(tray):
    """托盘自己的线程、反应计时器里调:没有事件循环要护,就地画完再返回(顺序最简单)。"""
    t, painted = tray
    t.on_render(_frame(True))
    assert painted == [threading.current_thread().name]


def test_two_paint_paths_never_leave_an_old_picture_on_top(tray):
    """事件循环里来的那一拍交给画图线程、计时器里来的就地画:两条路先后到,最后留在托盘上的必须是最新的样子。"""
    t, painted = tray
    import windows_service.tray_icon as T

    shown = []

    def _paint_what_is_current(status, pet=None, react=None):
        time.sleep(0.3)
        shown.append(bool((pet or {}).get("eyes") == "shut"))
        return object()

    T.create_icon_image = _paint_what_is_current  # tray fixture 的 monkeypatch 收尾时会还原

    async def on_the_loop():
        t.on_render(_frame(True))  # 交给画图线程,慢慢画

    asyncio.run(on_the_loop())
    paused = _frame(True)
    paused["perception"]["privacy_paused"] = True
    t.on_render(paused)  # 不在循环里:就地画最新的
    deadline = time.monotonic() + 5
    while len(shown) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert shown and shown[-1] is True, f"最后画上去的不是最新的样子: {shown}"
