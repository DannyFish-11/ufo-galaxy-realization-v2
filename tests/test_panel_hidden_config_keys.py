"""tests/test_panel_hidden_config_keys.py — 登记了、但不列在面板上的键。

仓库所有者的决定:元层与入口分流这一组,面板「全部设置」里只留自我改进循环
(``GALAXY_META_RSI``)一个开关,其余的默认即生效、藏起来。

本仓栽过的坑是「代码里接好了,面板上看不见也改不了」—— 所以「藏起来」必须和
「没接上」分得开。这里钉住的就是这条分界:

* 藏起来的键仍在 ``CONFIG_SCHEMA`` 里:POST /api/config 照收、.env 照写;
* 只是 GET /api/config/all 不列,面板的顺序提示里也不写它们;
* 藏起来的**开关**默认必须在「开」的一侧,且与代码里的默认值一致 —— 否则就是一个
  用户找不到、又默认关着的功能;
* ``GALAXY_META_RSI`` 永远不许藏 —— 它是自我改进循环的总闸。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.routes.config import CONFIG_SCHEMA, PANEL_HIDDEN_KEYS, get_config

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY = REPO_ROOT / "electron" / "renderer" / "panel" / "src" / "settings_inventory.ts"


def _config_all() -> dict:
    return asyncio.run(get_config())


def test_every_hidden_key_is_still_registered():
    missing = sorted(PANEL_HIDDEN_KEYS - set(CONFIG_SCHEMA))
    assert (
        not missing
    ), f"藏起来的键必须仍在 CONFIG_SCHEMA 里,否则 POST /api/config 会把它当 unknown_keys 拒掉: {missing}"


def test_config_all_lists_the_self_improvement_switch_and_nothing_hidden():
    listed = _config_all()
    assert not PANEL_HIDDEN_KEYS & set(listed), "GET /api/config/all 仍列出了藏起来的键"
    meta = listed["GALAXY_META_RSI"]
    assert meta["category"] == "meta" and meta["options"] == ["off", "shadow", "on"]
    assert [k for k, v in listed.items() if v["category"] == "meta"] == ["GALAXY_META_RSI"]


def test_the_self_improvement_switch_is_never_hidden():
    assert "GALAXY_META_RSI" not in PANEL_HIDDEN_KEYS


def test_hidden_switches_default_to_on_and_match_the_code():
    from core.agent_supply import DEFAULT_SUPPLY_MODE

    for key in PANEL_HIDDEN_KEYS:
        meta = CONFIG_SCHEMA[key]
        if meta["type"] == "boolean":
            assert meta["default"] == "true", f"{key} 藏起来了却默认关 —— 用户找不到它,也就永远打不开"
        elif meta["type"] == "select":
            assert meta["default"] == "on", f"{key} 藏起来了却默认不是 on"
    assert CONFIG_SCHEMA["GALAXY_AGENT_SUPPLY"]["default"] == DEFAULT_SUPPLY_MODE


def test_presence_line_is_on_when_nothing_is_set(monkeypatch):
    from core.presence_line import presence_line_enabled

    monkeypatch.delenv("GALAXY_PRESENCE_LINE", raising=False)
    assert presence_line_enabled() is True


def test_hidden_keys_can_still_be_saved(tmp_path, monkeypatch):
    """藏起来 ≠ 没接上:POST /api/config 照收、.env 照写。"""
    import core.config_store as config_store_module
    import core.routes.config as config_module

    monkeypatch.setattr(config_module, "ENV_FILE", tmp_path / ".env.test")
    monkeypatch.setattr(
        config_store_module,
        "_singleton",
        config_store_module.ConfigStore(
            config_path=tmp_path / "config.json.test",
            secrets_path=tmp_path / "secrets.env.test",
        ),
    )
    # update_config 会写 os.environ;先登记,测试结束时由 monkeypatch 还原。
    monkeypatch.setenv("GALAXY_PRESENCE_LINE", "true")
    monkeypatch.setenv("GALAXY_ENGINEERING_VERIFY_TIMEOUT_S", "600")
    app = FastAPI()
    app.include_router(config_module.router)
    resp = TestClient(app).post(
        "/api/config",
        json={"config": {"GALAXY_PRESENCE_LINE": "false", "GALAXY_ENGINEERING_VERIFY_TIMEOUT_S": "900"}},
    )
    assert resp.status_code == 200, resp.text
    env_text = (tmp_path / ".env.test").read_text(encoding="utf-8")
    assert "GALAXY_PRESENCE_LINE=false" in env_text and "GALAXY_ENGINEERING_VERIFY_TIMEOUT_S=900" in env_text


def test_the_panel_order_hint_does_not_list_hidden_keys():
    """面板拿不到这些键,顺序提示里写它们就是一张查不到的表。"""
    src = INVENTORY.read_text(encoding="utf-8")
    start = src.index("export const KEY_ORDER_HINT")
    block = src[start : src.index("\n};", start)]
    listed = set(re.findall(r"'(GALAXY_[A-Z0-9_]+)'", block))
    assert not PANEL_HIDDEN_KEYS & listed, sorted(PANEL_HIDDEN_KEYS & listed)
    assert "GALAXY_META_RSI" in listed
