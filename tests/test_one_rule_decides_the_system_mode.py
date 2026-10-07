"""系统只有两个模式 —— 本地模式(默认,只用本机)与跨设备模式 —— 而且「现在是哪个」只有一条规则、一个出处。

规则(``core/system_mode.py::cross_device_requested``):``GALAXY_CROSS_DEVICE_ENABLED`` 为真,**或** ``GALAXY_SYSTEM_MODE``
写的是 ``desktop-cross-device`` —— 任一即是。「local」「false」是出厂默认(``.env.example`` 带着、保存设置会写),
不是一次选择,盖不过别处明确的选择。

此前同一个问题有好几个各自推导的答案:网关只看 ``CROSS_DEVICE_ENABLED``;启动流程额外把「NATS 地址非空」当成跨设备;
``system_mode.py`` 又让写着 ``desktop-local`` 的 ``GALAXY_SYSTEM_MODE`` 盖过按钮。于是面板按钮开着、.env 里躺着
``desktop-local``(``.env.example`` 就有这行)时,网关说开、启动流程说跨设备、模式接口说本地;「保存设置」把登记默认
``nats://localhost:4222`` 写进 .env,下次启动只想用本机的人被悄悄切成了跨设备。
"""

from __future__ import annotations

import asyncio
import itertools
import os

import pytest

from core.routes import config as cfg
from core.routes.config_bundles import CONFIG_BUNDLES, owned_keys
from core.routes.config_schema_registry import CONFIG_SCHEMA
from core.system_mode import (
    SystemMode,
    cross_device_requested,
    nats_url_points_elsewhere,
    resolve_fabric_config,
)

MODES = (None, "desktop-local", "desktop-cross-device", "garbage")
BUTTONS = (None, "true", "false", "1", "0", "yes", "on")


def _env(mode, button, url=None) -> dict:
    env = {}
    if mode is not None:
        env["GALAXY_SYSTEM_MODE"] = mode
    if button is not None:
        env["GALAXY_CROSS_DEVICE_ENABLED"] = button
    if url is not None:
        env["GALAXY_NATS_URL"] = url
    return env


def _expected(mode, button) -> bool:
    return mode == "desktop-cross-device" or (button or "").lower() in ("true", "1", "yes", "on")


@pytest.mark.parametrize("mode,button", list(itertools.product(MODES, BUTTONS)))
def test_the_rule_is_either_one_says_cross_device(mode, button):
    assert cross_device_requested(_env(mode, button)) is _expected(mode, button)


@pytest.mark.parametrize("mode,button", list(itertools.product(MODES, BUTTONS)))
def test_the_fabric_config_agrees_with_the_rule(mode, button):
    cfg_ = resolve_fabric_config(_env(mode, button))
    want = _expected(mode, button)
    assert cfg_.is_cross_device is want
    assert cfg_.cross_device_enabled is want
    assert cfg_.mode == (SystemMode.DESKTOP_CROSS_DEVICE if want else SystemMode.DESKTOP_LOCAL)


@pytest.mark.parametrize("mode,button", list(itertools.product(MODES, BUTTONS)))
def test_every_layer_gives_the_same_answer(monkeypatch, mode, button):
    """网关开关、启动流程、桌面在场、模式接口 —— 同一份环境,同一个答案。"""
    for k in ("GALAXY_SYSTEM_MODE", "GALAXY_CROSS_DEVICE_ENABLED", "GALAXY_NATS_URL"):
        monkeypatch.delenv(k, raising=False)
    for k, v in _env(mode, button).items():
        monkeypatch.setenv(k, v)
    want = _expected(mode, button)

    from galaxy_gateway.cross_device_switch import is_cross_device_enabled

    assert is_cross_device_enabled() is want

    from core.system_orchestrator import SystemOrchestrator

    phase = SystemOrchestrator()._run_phase_2_resolve_mode()
    assert phase.data["cross_device"] is want
    assert phase.data["system_mode"] == ("desktop-cross-device" if want else "desktop-local")


@pytest.mark.parametrize("url", ["nats://localhost:4222", "nats://127.0.0.1:4222", "nats://10.0.0.7:4222", ""])
def test_a_nats_address_never_changes_the_mode(url):
    assert cross_device_requested(_env(None, None, url)) is False
    assert resolve_fabric_config(_env(None, None, url)).is_cross_device is False


def test_which_addresses_count_as_pointing_elsewhere():
    assert nats_url_points_elsewhere("nats://192.168.1.50:4222")
    assert nats_url_points_elsewhere("nats://user:pw@bus.example.com:4222")
    assert not nats_url_points_elsewhere("")
    assert not nats_url_points_elsewhere("nats://localhost:4222")
    assert not nats_url_points_elsewhere("nats://127.0.0.1:4222")
    assert not nats_url_points_elsewhere("nats://[::1]:4222")


def test_the_registry_does_not_write_an_address_nobody_filled_in():
    """「保存设置」把登记默认整体写进 .env:地址登记成非空,就是替人填了一个。"""
    assert CONFIG_SCHEMA["GALAXY_NATS_URL"]["default"] == ""


def test_the_mode_key_is_not_a_second_control_on_the_panel():
    assert "GALAXY_SYSTEM_MODE" in cfg.PANEL_HIDDEN_KEYS
    listed = asyncio.run(cfg.get_config())
    assert "GALAXY_SYSTEM_MODE" not in listed
    assert "GALAXY_CROSS_DEVICE_ENABLED" in listed, "切换点只有「跨设备」这一个按钮"


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    saved = dict(os.environ)
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / ".env")
    for bundle in CONFIG_BUNDLES:
        for key in owned_keys(bundle, CONFIG_SCHEMA.keys()):
            os.environ.pop(key, None)
    for key in ("GALAXY_SYSTEM_MODE", "GALAXY_NATS_URL"):
        os.environ.pop(key, None)
    yield tmp_path / ".env"
    os.environ.clear()
    os.environ.update(saved)


def _press(value: str) -> dict:
    return asyncio.run(cfg.set_bundle(cfg.BundleUpdateRequest(key="cross_device", value=value)))["bundle"]


def test_the_button_writes_the_mode_with_it(isolated_env):
    state = _press("true")
    assert os.environ["GALAXY_CROSS_DEVICE_ENABLED"] == "true"
    assert os.environ["GALAXY_SYSTEM_MODE"] == "desktop-cross-device"
    assert "GALAXY_SYSTEM_MODE=desktop-cross-device" in isolated_env.read_text(encoding="utf-8")
    assert state["overrides"] == 0, "按钮自己写的不算「手改过」"
    assert cross_device_requested() is True

    state = _press("false")
    assert os.environ["GALAXY_SYSTEM_MODE"] == "desktop-local"
    assert state["overrides"] == 0
    assert cross_device_requested() is False, "按钮关了就是关了:手写的跨设备模式也一并被它改回"


def test_the_button_says_it_needs_a_restart(isolated_env):
    assert _press("true")["restart_required"] is True


def test_a_hand_edited_mode_against_the_button_shows_up_as_a_deviation(isolated_env, monkeypatch):
    _press("true")
    monkeypatch.setenv("GALAXY_SYSTEM_MODE", "desktop-local")  # .env.example 带来的旧行:按钮开着,它写着 local
    assert cross_device_requested() is True, "按钮开着就是跨设备"
    state = asyncio.run(cfg.get_bundles())["bundles"]
    assert next(b for b in state if b["key"] == "cross_device")["overrides"] == 1


def test_saving_settings_never_turns_local_mode_into_cross_device(isolated_env):
    """保存任何一个无关的设置 = 把登记默认整体写进 .env。写完再启动,模式不能变。"""
    cfg._write_env_file_with({})
    written = isolated_env.read_text(encoding="utf-8")
    assert "GALAXY_NATS_URL=" not in written.replace("# ", ""), "没填过的地址不写"
    parsed = dict(line.split("=", 1) for line in written.splitlines() if "=" in line and not line.startswith("#"))
    assert cross_device_requested(parsed) is False


def test_saving_settings_keeps_a_hand_written_cross_device_mode(isolated_env, monkeypatch):
    monkeypatch.setenv("GALAXY_SYSTEM_MODE", "desktop-cross-device")
    cfg._write_env_file_with({})
    written = isolated_env.read_text(encoding="utf-8")
    parsed = dict(line.split("=", 1) for line in written.splitlines() if "=" in line and not line.startswith("#"))
    assert parsed["GALAXY_SYSTEM_MODE"] == "desktop-cross-device"
    assert cross_device_requested(parsed) is True, "保存设置不能把手写的跨设备模式悄悄改回本地"
