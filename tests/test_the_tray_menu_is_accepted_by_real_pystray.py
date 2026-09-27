"""托盘菜单要让**真的** pystray 收下,不是只让测试替身收下。

真机(Windows)每次启动:

    托盘起不来 / tray failed to start: <function GalaxyTray._build_logs_menu.<locals>.<lambda>>
      File "windows_service/tray_icon.py", line 453, in _build_logs_menu
        pystray.MenuItem(
      File ".../pystray/_base.py", line 561, in _assert_action
        raise ValueError(action)

pystray 按 ``__code__.co_argcount`` 数动作的参数个数,带默认值的也算,超过 2 个就拒。
日志菜单用 ``lambda _icon, _item, _e=entry:`` 绑 entry —— 3 个参数。

以前的测试一直绿,因为它们用的假 pystray 什么动作都收。这里在**子进程**里 import 真
pystray(dummy 后端,不需要图形界面),把整个托盘菜单构造一遍,并且照 pystray 的方式
**求值那个惰性子菜单** —— 真机就崩在这一步(``bool(menu)`` 触发 ``_build_logs_menu``)。

子进程是为了隔离:别的测试会往 sys.modules 里塞假 pystray,同进程里 import 拿到的
可能根本不是真货。
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_PROBE = textwrap.dedent("""
    import os, sys, json
    sys.path.insert(0, os.environ["ROOT"])
    import pystray
    assert "pystray._dummy" in sys.modules, "没走 dummy 后端"

    import windows_service.tray_icon as t
    assert t._HAVE_TRAY, t.TRAY_UNAVAILABLE_REASON

    tray = t.GalaxyTray.__new__(t.GalaxyTray)
    tray._icon = None
    opened = []
    tray._open_log = lambda entry: opened.append(entry.relpath)
    tray._open_logs_folder = lambda *_a: opened.append("<folder>")

    # 1) 直接构造 —— 旧代码在这一步 ValueError
    items = tray._build_logs_menu()

    # 2) 照 pystray 的方式把它包成惰性子菜单并求值 —— 真机崩在 bool(menu) 这里
    menu = pystray.Menu(lambda: tray._build_logs_menu())
    visible = bool(menu)

    # 3) 用 pystray 自己的调法点每一项
    for it in items:
        if isinstance(it, pystray.MenuItem):
            it(None)   # MenuItem.__call__(icon) —— pystray 点菜单时就这么调

    print(json.dumps({"n": len(items), "visible": visible, "opened": opened}))
    """)


def _pystray_available() -> bool:
    env = {**os.environ, "PYSTRAY_BACKEND": "dummy"}
    r = subprocess.run([sys.executable, "-c", "import pystray, PIL"], env=env, capture_output=True)
    return r.returncode == 0


pytestmark = pytest.mark.skipif(not _pystray_available(), reason="本机没装 pystray / Pillow")


def test_the_whole_logs_menu_is_accepted_by_real_pystray(tmp_path):
    import json

    from core.log_locations import LOG_LOCATIONS

    # 让几条日志"存在",菜单里才有条目(只列存在的那些)
    for e in [e for e in LOG_LOCATIONS if not e.is_dir][:3]:
        f = tmp_path / e.relpath
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", encoding="utf-8")

    env = {**os.environ, "PYSTRAY_BACKEND": "dummy", "ROOT": ROOT, "GALAXY_LOG_DIR": str(tmp_path)}
    r = subprocess.run([sys.executable, "-c", _PROBE], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"真 pystray 不收这个菜单:\n{r.stderr[-2000:]}"

    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["visible"] is True
    # 3 条日志 + 分隔线 + "打开日志文件夹"
    assert out["n"] == 5, out
    # 点每一项打开的是它自己那条(闭包绑对了),最后是文件夹
    expected = [e.relpath for e in LOG_LOCATIONS if not e.is_dir][:3] + ["<folder>"]
    assert out["opened"] == expected, out
