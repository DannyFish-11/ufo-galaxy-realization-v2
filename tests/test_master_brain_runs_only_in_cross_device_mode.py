"""主脑与 worker 只在跨设备模式里起 —— 跨设备是多设备的前提。

此前主脑开关与跨设备开关在代码里互相独立：只开主脑、不开跨设备，主脑照样起，
而网关的跨设备路由却关着，两边各说各话。现在主脑开着、却在本地模式 → 不起，而且**说出来**
（启动日志里一句话），不悄悄忽略一个写了的配置。
"""

from __future__ import annotations

import asyncio
import itertools
import types
from pathlib import Path

import pytest

from core.system_mode import master_brain_requested, master_brain_waiting_for_mode, master_brain_wanted

REPO = Path(__file__).resolve().parent.parent

FLAGS = (None, "true", "false", "1", "0")
MODES = (None, "desktop-local", "desktop-cross-device")
BUTTONS = (None, "true", "false")


def _env(flag, mode, button) -> dict:
    env = {}
    if flag is not None:
        env["GALAXY_MASTER_BRAIN_ENABLED"] = flag
    if mode is not None:
        env["GALAXY_SYSTEM_MODE"] = mode
    if button is not None:
        env["GALAXY_CROSS_DEVICE_ENABLED"] = button
    return env


@pytest.mark.parametrize("flag,mode,button", list(itertools.product(FLAGS, MODES, BUTTONS)))
def test_the_brain_starts_exactly_when_it_is_asked_for_and_the_system_is_cross_device(flag, mode, button):
    env = _env(flag, mode, button)
    wanted = flag in ("true", "1")
    cross = mode == "desktop-cross-device" or button == "true"
    assert master_brain_wanted(env) is wanted
    assert master_brain_requested(env) is (wanted and cross)
    assert master_brain_waiting_for_mode(env) is (wanted and not cross)


@pytest.fixture
def clean(monkeypatch):
    for k in ("GALAXY_MASTER_BRAIN_ENABLED", "GALAXY_SYSTEM_MODE", "GALAXY_CROSS_DEVICE_ENABLED"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_every_reader_of_the_switch_agrees(clean):
    from core.master_brain import get_master_brain, master_brain_enabled
    from core.worker_runtime import start_worker_runtime, worker_enabled

    clean.setenv("GALAXY_MASTER_BRAIN_ENABLED", "true")
    assert master_brain_enabled() is False and worker_enabled() is False
    assert get_master_brain() is None
    assert asyncio.run(start_worker_runtime()) == {"started": False, "reason": "disabled"}

    clean.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
    assert master_brain_enabled() is True and worker_enabled() is True

    clean.setenv("GALAXY_MASTER_BRAIN_ENABLED", "false")
    assert master_brain_enabled() is False and worker_enabled() is False


def test_a_go_worker_task_in_local_mode_fails_closed_instead_of_reaching_a_brain(clean):
    from core.command_router import CommandRouter

    clean.setenv("GALAXY_MASTER_BRAIN_ENABLED", "true")  # 开了,但在本地模式
    envelope = types.SimpleNamespace(task_id="t1", trace_id="tr1", target="worker-1", tool_name="shell")
    out = asyncio.run(CommandRouter._route_worker_envelope(types.SimpleNamespace(), envelope, "c1", "r1"))
    assert out["success"] is False
    assert out["error_code"] == "WORKER_DISPATCH_UNAVAILABLE"
    assert out["dispatch_attempted"] is False


def test_a_device_task_in_local_mode_is_refused_by_the_gateway_router_not_just_by_the_switch(clean):
    """核心的 /devices/parallel 与 CommandRouter 自己不查跨设备开关,拦在更下面:
    网关 DeviceRouter 两处入口都用同一个开关(同一条模式规则),本地模式一律 cross_device_disabled。"""
    from galaxy_gateway.cross_device_switch import is_cross_device_enabled, make_disabled_response

    assert is_cross_device_enabled() is False
    assert make_disabled_response("t")["error"] == "cross_device_disabled"
    src = (REPO / "galaxy_gateway" / "device_router.py").read_text(encoding="utf-8")
    assert src.count("if not is_cross_device_enabled():") >= 2


def test_the_startup_sequence_says_so_when_the_brain_is_on_but_the_mode_is_local(clean):
    import inspect

    import core.startup as startup

    clean.setenv("GALAXY_MASTER_BRAIN_ENABLED", "true")
    assert master_brain_waiting_for_mode() is True
    src = inspect.getsource(startup)
    assert "master_brain_waiting_for_mode()" in src and "当前是本地模式" in src
