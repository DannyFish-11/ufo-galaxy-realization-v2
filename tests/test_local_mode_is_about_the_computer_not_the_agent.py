"""「本地模式」说的是这台电脑（它自己一整套循环在本机闭环、不加入设备网络），不是智能体只能用本地的东西。

所有者的定义：本地模式只是电脑设备的一整套循环是本地的，不是说智能体也是本地；跨设备只是指电脑加入跨设备 / 多设备网络。
原先人和模型读到的说法是「本地模式(只用本机)」「it only uses this computer」—— 读起来像「智能体只能用本机模型、不能上网」。
这里钉住：人看的（面板按钮、启动预检）和模型看的（请求打开跨设备的工具、往别的设备下发被拒时的回话）都按这个定义说。
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_AMBIGUOUS = ("只用本机", "只用这台电脑", "only uses this computer", "只在这一台机器")


def test_the_panel_button_says_the_computer_joins_the_network():
    from core.routes.config_bundles import CONFIG_BUNDLES

    note = next(b for b in CONFIG_BUNDLES if b["key"] == "cross_device")["note"]
    assert "加入多设备网络" in note and not any(w in note for w in _AMBIGUOUS), note
    main_ts = (REPO / "electron" / "renderer" / "panel" / "src" / "main.ts").read_text(encoding="utf-8")
    assert f"note: '{note}'" in main_ts, "面板那份说明与后端登记表不一致"


def test_the_model_is_told_its_own_capabilities_are_not_limited():
    from core.device_onboarding.mode_request import MODE_BUILTIN_TOOLS

    desc = MODE_BUILTIN_TOOLS[0]["function"]["description"]
    assert "has not joined the user's device network" in desc
    assert "models, cloud APIs, web access and MCP tools work as usual" in desc
    assert not any(w in desc for w in _AMBIGUOUS)


def test_the_refusal_names_the_device_network(monkeypatch):
    monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "false")
    monkeypatch.setenv("GALAXY_SYSTEM_MODE", "desktop-local")
    from core.system_mode import cross_device_refusal

    out = cross_device_refusal()
    assert out and out["error"] == "cross_device_disabled"
    assert "没加入设备网络" in out["message"] and not any(w in out["message"] for w in _AMBIGUOUS)


def test_preflight_and_index_use_the_same_definition():
    preflight = (REPO / "core" / "config_preflight.py").read_text(encoding="utf-8")
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert not any(w in preflight for w in _AMBIGUOUS), "启动预检又把本地模式说成了「只用本机」"
    assert "模式说的是设备，不是智能体" in agents
