"""托盘图标「出现」不许等菜单里的数算完。

真机日志：``系统托盘 ⚠ 8 秒内没出现在托盘区(后台仍在尝试)``，Windows 冷启动、整机在忙的时候。

根因（读 pystray 0.19.5 的源码得到的，不是猜的）
------------------------------------------------
``Icon.run(setup)`` 里，``setup`` 回调——我们靠它判断「图标真的出现了」，也在里面才把
``icon.visible`` 置真——要等 ``_mark_ready()`` 跑完才会被调用；``_mark_ready()`` 先调
``update_menu()``，而 Windows 后端的 ``_update_menu()`` 把**整棵菜单**建一遍，包括惰性子菜单
（``pystray.Menu(lambda: …)`` 在这时被求值）。

「本机模型实测」那个子菜单一求值就去算整份实测账：探硬件画像、问 Ollama（2 秒超时）、
第一次 import 路由模块。冷机器上这几样排在一起，图标就迟迟不出现——不是托盘坏了，是
**图标在等一张菜单上的数**。

这里用真 pystray（dummy 后端）、并把它的 ``_update_menu`` 换成「像 Windows 后端那样展开整棵菜单」，
再让实测账慢 3 秒，核对：``run_detached`` 在远小于 3 秒的时间里就报告图标已出现。
子进程跑，原因同 ``test_the_tray_menu_is_accepted_by_real_pystray``：别的测试会往 ``sys.modules``
里塞假 pystray。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PROBE = textwrap.dedent("""
    import os, sys, json, time, threading
    sys.path.insert(0, os.environ["ROOT"])
    import pystray
    assert "pystray._dummy" in sys.modules, "没走 dummy 后端"

    # dummy 后端是个空壳（_run 直接 NotImplementedError），这里补成 Windows 后端的形状：
    #   _run：就绪（_mark_ready）后进事件循环；_update_menu：把整棵菜单（含惰性子菜单）建一遍。
    def _walk(menu):
        for item in menu:
            sub = getattr(item, "submenu", None)
            if sub:
                _walk(sub)
    _loop = threading.Event()
    def _run(self):
        self._mark_ready()
        _loop.wait()
    pystray.Icon._run = _run
    pystray.Icon._stop = lambda self: _loop.set()
    pystray.Icon._update_menu = lambda self: _walk(self.menu)
    for _name in ("_show", "_hide", "_update_icon", "_update_title"):
        setattr(pystray.Icon, _name, lambda self, *a, **k: None)

    import core.model_measurements_report as rep
    started = threading.Event()
    release = threading.Event()
    def _slow_rows(budget, has_gpu):
        started.set()
        release.wait(5.0)          # 冷 import + 问 Ollama + 探硬件
        return []
    rep.measurement_rows = _slow_rows

    import windows_service.tray_icon as t
    assert t._HAVE_TRAY, t.TRAY_UNAVAILABLE_REASON
    tray = t.GalaxyTray()

    t0 = time.monotonic()
    why = tray.run_detached(wait_s=2.0)
    came_up_in = time.monotonic() - t0
    slow_numbers_finished = release.is_set()

    # 菜单上这一项在数没算完时要说「正在读取」，不是空白、也不是旧数
    first_items = [str(getattr(i, "text", i)) for i in tray._build_measurements_menu()]

    release.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and getattr(tray, "_measure_rows", None) is None:
        time.sleep(0.02)
    later_items = [str(getattr(i, "text", i)) for i in tray._build_measurements_menu()]
    tray.stop()
    print(json.dumps({
        "why": why, "came_up_in": came_up_in, "numbers_started": started.is_set(),
        "slow_numbers_finished": slow_numbers_finished,
        "first": first_items, "later": later_items,
    }))
    """)


def _pystray_available() -> bool:
    env = {**os.environ, "PYSTRAY_BACKEND": "dummy"}
    r = subprocess.run([sys.executable, "-c", "import pystray, PIL"], env=env, capture_output=True)
    return r.returncode == 0


pytestmark = pytest.mark.skipif(not _pystray_available(), reason="本机没装 pystray / Pillow")


def test_the_icon_appears_while_the_menu_numbers_are_still_being_worked_out():
    env = {**os.environ, "PYSTRAY_BACKEND": "dummy", "ROOT": ROOT}
    r = subprocess.run([sys.executable, "-c", _PROBE], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    out = json.loads(r.stdout.strip().splitlines()[-1])

    assert out["why"] == "", f"图标没在 2 秒内出现：{out['why']}（菜单里的数还没算完它就该先出来）"
    assert out["slow_numbers_finished"] is False, "图标是等数算完才出现的 —— 那 3 秒就是真机上的 8 秒"
    assert out["came_up_in"] < 1.5, out
    # 数在后台照样被算了（不是干脆不算）
    assert out["numbers_started"] is True, out
    # 没算完时菜单上写的是「正在读取」，算完后才是真数据行
    assert any("正在读取" in s for s in out["first"]), out["first"]
    assert not any("正在读取" in s for s in out["later"]), out["later"]
