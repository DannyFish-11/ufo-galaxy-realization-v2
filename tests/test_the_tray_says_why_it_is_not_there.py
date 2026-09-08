"""托盘用不了的时候,得说**真正的**原因。

真跑实测(全新克隆冷启动,无头机器):托盘失败时抛的是 ``Bad display name ""``
—— pystray 连不上 X11,包**装着**。而屏幕上那一行写死的是

    ⚠ 系统托盘    不可用 (pip install pystray Pillow)

照着它装十遍也好不了:说的和现实相反。与 pyautogui 那两处同一类毛病。
"""

import asyncio
import logging

import pytest

from launcher.services import GalaxyUnified


def _tray(monkeypatch, exc):
    """让 start_system_tray 走到指定的失败分支,返回 (ok, reason)。

    桩必须打在 ``windows_service.tray_icon.start_tray_in_thread`` 上,并且先把那个
    模块塞进 sys.modules —— 无头机器上 ``from windows_service.tray_icon import …``
    这一行**本身**就会抛(模块 import 期就去连 X11),桩在 asyncio.to_thread 上的话
    根本轮不到它被调用,测的就不是我们想测的那条分支了。
    """
    import sys
    import types

    fake = types.ModuleType("windows_service.tray_icon")

    def _start():
        if exc is not None:
            raise exc
        return object()

    fake.start_tray_in_thread = _start
    monkeypatch.setitem(sys.modules, "windows_service.tray_icon", fake)

    inst = GalaxyUnified.__new__(GalaxyUnified)
    ok = asyncio.run(GalaxyUnified.start_system_tray(inst))
    return ok, getattr(inst, "_tray_unavailable_reason", "")


def test_missing_package_says_missing_package(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        ok, reason = _tray(monkeypatch, ImportError("No module named 'pystray'"))
    assert ok is False
    assert "pystray" in reason


def test_headless_does_not_claim_the_package_is_missing(monkeypatch, caplog):
    """装着却说"缺 pystray / Pillow" —— 这正是真跑里那句假话。"""
    with caplog.at_level(logging.WARNING):
        ok, reason = _tray(monkeypatch, Exception('Bad display name ""'))
    assert ok is False
    assert "没有图形环境" in reason
    assert "pystray" not in reason, f"装着却让人去装:{reason}"
    assert "Pillow" not in reason, f"装着却让人去装:{reason}"


def test_other_failures_do_not_get_mislabelled_as_headless(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        ok, reason = _tray(monkeypatch, RuntimeError("something else entirely"))
    assert ok is False
    assert reason
    assert "没有图形环境" not in reason, "不是无头,就别硬说是无头"


def test_success_leaves_no_reason_behind(monkeypatch):
    ok, reason = _tray(monkeypatch, None)
    assert ok is True
    assert reason == ""


def test_the_summary_line_no_longer_hardcodes_the_install_hint():
    """源码判据:那一行必须读 _tray_unavailable_reason,不能再写死装包提示。"""
    import inspect

    src = inspect.getsource(GalaxyUnified.start)
    assert "_tray_unavailable_reason" in src, "总结行没读真实原因"
    assert "不可用 (pip install pystray Pillow)" not in src, "那句写死的假话又回来了"


@pytest.mark.parametrize("msg", ['Bad display name ""', "cannot open DISPLAY", "no Display available"])
def test_display_detection_is_case_insensitive(monkeypatch, msg):
    ok, reason = _tray(monkeypatch, Exception(msg))
    assert ok is False
    assert "没有图形环境" in reason
