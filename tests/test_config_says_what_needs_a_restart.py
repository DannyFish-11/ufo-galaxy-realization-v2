"""面板必须说出「改了要重启才生效」的那些键。

此前面板保存之后显示「已保存」、值也确实写进了环境变量和 ``.env``，但读取点在启动（或导入）时的那批键，
已经在跑的进程不会回头看 —— 用户点了、看到已保存，什么都没变，只有下次启动才起作用，而界面上没有任何提示。

单一清单在 ``core/routes/config_restart.py``；这里守：清单里没有错别字（每个键都真登记在 CONFIG_SCHEMA）、
后端把它带给面板（``/api/config/all`` 与 ``/api/config/bundles``）、面板真的把它说出来。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.routes import config as cfg
from core.routes.config_bundles import CONFIG_BUNDLES, member_keys, mirror_keys
from core.routes.config_restart import RESTART_REQUIRED, any_requires_restart, restart_reason
from core.routes.config_schema_registry import CONFIG_SCHEMA

PANEL_SRC = Path(__file__).resolve().parent.parent / "electron" / "renderer" / "panel" / "src"


def test_every_listed_key_is_a_real_registered_key_with_a_reason():
    for key, reason in RESTART_REQUIRED.items():
        assert key in CONFIG_SCHEMA, f"{key} 不在 CONFIG_SCHEMA 里 —— 清单里有错别字"
        assert len(reason) >= 6, f"{key} 没写为什么要重启"


def test_the_reader_sites_that_are_known_to_be_startup_only_are_listed():
    """从读取位置核实过的几个：改了不会立刻生效。"""
    for key in (
        "GALAXY_VOICE",
        "GALAXY_AMBIENT_LOOP",
        "GALAXY_CROSS_DEVICE_ENABLED",
        "GALAXY_MASTER_BRAIN_ENABLED",
        "GALAXY_TS_FUNNEL",
        "GALAXY_DURABLE_EXEC",
    ):
        assert restart_reason(key), key
    # 每次用到时才读的，不能错标成要重启
    for key in ("GALAXY_SPEAK", "GALAXY_COMPUTER_USE", "GALAXY_MOA_ENABLED", "GALAXY_OPENSOURCE_FIRST"):
        assert restart_reason(key) is None, key


def test_all_config_carries_the_hint_for_listed_keys_the_panel_shows():
    listed = asyncio.run(cfg.get_config())
    for key in RESTART_REQUIRED:
        if key in cfg.PANEL_HIDDEN_KEYS:
            assert key not in listed
            continue
        assert listed[key]["restart_required"] == RESTART_REQUIRED[key], key
    assert "restart_required" not in listed["GALAXY_MOA_ENABLED"]


def test_a_bundle_says_so_when_what_it_writes_needs_a_restart():
    states = {b["key"]: cfg._bundle_state(b) for b in CONFIG_BUNDLES}
    assert states["cross_device"]["restart_required"] is True
    assert states["omnimodal"]["restart_required"] is True
    assert states["voice"]["restart_required"] is False, "朗读回复每次开口时才读，即时生效"
    for bundle in CONFIG_BUNDLES:
        written = [bundle["primary"], *member_keys(bundle), *mirror_keys(bundle)]
        assert states[bundle["key"]]["restart_required"] is any_requires_restart(written)


def test_the_panel_actually_says_it():
    dock = (PANEL_SRC / "ui" / "dock.ts").read_text(encoding="utf-8")
    settings = (PANEL_SRC / "ui" / "settings.ts").read_text(encoding="utf-8")
    transport = (PANEL_SRC / "transport.ts").read_text(encoding="utf-8")
    assert "restartRequired" in dock and "重启后生效" in dock
    assert "restartRequired" in settings and "重启后生效" in settings
    assert transport.count("restart_required") >= 2, "两个接口（全部设置 / 整档开关）都要读"
