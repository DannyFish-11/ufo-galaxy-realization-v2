"""托盘起不来时,退出那一刻不该再冒一段回溯。

真机(托盘菜单那个 ValueError 修好之前)退出时:

    Exception ignored in: <function Icon.__del__ ...>
      File ".../pystray/_win32.py", line 53, in __del__
    AttributeError: 'Icon' object has no attribute '_thread'

pystray 的 Windows 后端在 ``_mark_ready()`` 里建菜单,之后才赋 ``_thread``;
``_mark_ready()`` 一抛,图标就停在"``_running`` 真、``_thread`` 不存在",``__del__`` 再炸一次。
下面的假图标照抄那段 ``__del__``。
"""

import threading

from windows_service import tray_icon as t


class _Win32LikeIcon:
    """``run()`` 的行为照 pystray._win32:置 _running → _mark_ready 抛 → 永远到不了赋 _thread。"""

    def __init__(self):
        self._running = False

    def run(self, setup=None):
        self._running = True
        raise ValueError("<function GalaxyTray._build_logs_menu.<locals>.<lambda>>")

    def _release_icon(self):
        pass

    def __del__(self):  # 与 pystray/_win32.py 的 __del__ 同形
        if self._running:
            if self._thread.ident != threading.current_thread().ident:
                self._thread.join()
        self._release_icon()


def test_a_tray_that_fails_to_start_is_discarded_cleanly():
    tray = t.GalaxyTray.__new__(t.GalaxyTray)
    icon = _Win32LikeIcon()
    tray._icon = icon
    tray._thread = None

    reason = tray.run_detached(wait_s=5)

    assert "ValueError" in reason, "失败原因要照实报出来"
    assert tray._icon is None, "半初始化的图标不该留着,stop() 以后还会去碰它"
    assert icon._running is False
    icon.__del__()  # 退出时解释器会调它 —— 不许再抛
