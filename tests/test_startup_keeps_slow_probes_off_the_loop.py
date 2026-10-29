"""启动时两件慢事不在事件循环里做 —— 第 8 轮真跑(无头 Linux,`python main.py --backend -v`)的 loop_stall_watch 两行:

* ``事件循环被卡住 6.9 秒 —— 卡在 core/microsoft_ufo_integration.py:228 _initialize_fallback …〔正在 import pyautogui〕``:
  pyautogui import 期就去连 X11 / 装钩子;
* ``事件循环被卡住 10.7 秒 —— 卡在 galaxy_gateway/mdns_announcer.py:125 start …〔最里面:threading.py wait〕``,
  接着 ``mDNS: failed to start: EventLoopBlocked``:zeroconf 建在事件循环线程上,会把注册排进同一个循环、再同步等它
  —— 循环被自己堵住,10 秒后超时,广播也没发出去(同一 Wi-Fi 下的手表 / 手机找不到电脑)。
"""

from __future__ import annotations

import asyncio
import threading
import types


def test_the_pyautogui_probe_runs_off_the_event_loop(monkeypatch):
    import core.microsoft_ufo_integration as ufo

    seen = {}

    def probe():
        seen["thread"] = threading.current_thread()
        return ImportError("no pyautogui")

    monkeypatch.setattr(ufo, "_import_pyautogui", probe)
    inst = ufo.MicrosoftUFOAutomator.__new__(ufo.MicrosoftUFOAutomator)

    async def run():
        seen["loop_thread"] = threading.current_thread()
        return await ufo.MicrosoftUFOAutomator._initialize_fallback(inst)

    assert asyncio.run(run()) is False
    assert seen["thread"] is not seen["loop_thread"], "import pyautogui 不能在事件循环线程上做"


def test_lan_discovery_starts_off_the_event_loop():
    from launcher.bus_phase import _network_rows

    seen = {}

    def start_lan_discovery():
        seen["thread"] = threading.current_thread()
        return ("局域网发现", "已发布 _galaxy._tcp", "ok")

    svc = types.SimpleNamespace(
        tailnet=types.SimpleNamespace(wanted=lambda: False, start_lan_discovery=start_lan_discovery)
    )

    async def run():
        seen["loop_thread"] = threading.current_thread()
        return await _network_rows(svc, cross_device=False)

    rows = asyncio.run(run())
    assert rows[-1] == ("局域网发现", "已发布 _galaxy._tcp", "ok")
    assert seen["thread"] is not seen["loop_thread"], "zeroconf 建在事件循环线程上会自己等自己"
