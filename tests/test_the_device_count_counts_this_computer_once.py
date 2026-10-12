"""左下角「设备」那一行:只有这一台电脑时写「1 台」,不是「2 台」。

所有者:「左下角的设备,为啥只有一个设备会显示两个」。

后端发给面板的设备名册里**总有**这台电脑自己那一条(``build_panel_feed`` 插的 ``desktop_local``「本机 Desktop」,
在线);面板那一行原先当它不在、再 +1 —— 于是一台算了两遍。现在面板先把本机那条剔掉再 +1,
名册里有没有它,数都对。灵动岛上「x / y 在线」本来就按名册原样数(本机算一次),两处口径一致。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WIRED = ROOT / "electron" / "renderer" / "panel" / "src" / "ui" / "wired.ts"


def test_the_backend_roster_always_carries_this_computer_once(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    from core.routes.panel import build_panel_feed

    feed = asyncio.run(build_panel_feed())
    ids = [n["id"] for n in feed.get("topology_nodes", [])]
    assert ids.count("desktop_local") == 1, ids


def test_the_left_list_drops_that_entry_before_adding_this_computer():
    ts = WIRED.read_text(encoding="utf-8")
    m = re.search(r"const LOCAL_DEVICE_ID = '([^']+)';", ts)
    assert m and m.group(1) == "desktop_local", "面板认的本机编号与后端插的那一条不是同一个"
    block = ts[ts.index("name: '设备'") - 900 : ts.index("name: '设备'") + 400]
    assert "input.devices.filter((d) => d.id !== LOCAL_DEVICE_ID)" in block
    assert "detail: `${online + 1} 台`" in block
    assert "others.filter((d) => d.state === 'online')" in block, "在线数又直接数了整份名册(本机会算两遍)"
