"""「本地模式」说的是这台电脑（它自己一整套循环在本机闭环、不加入设备网络），不是智能体只能用本地的东西。

所有者的定义：本地模式只是电脑设备的一整套循环是本地的，不是说智能体也是本地；跨设备只是指电脑加入跨设备 / 多设备网络。
原先人和模型读到的说法是「本地模式(只用本机)」「it only uses this computer」—— 读起来像「智能体只能用本机模型、不能上网」。
这里钉住：人看的（面板按钮、启动预检）和模型看的（设备工具的说明）都按这个定义说 —— 而且这个开关从不限制智能体协调已加入的设备。
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


def test_the_model_is_told_the_switch_does_not_limit_it():
    """模型看的设备工具说明里写明:电脑的「跨设备」开关不限制它协调已加入的设备。"""
    import inspect

    from core.device_onboarding import agent_tools

    doc = inspect.getsource(agent_tools)
    assert "不限制智能体协调已加入的设备" in doc
    for t in agent_tools.DEVICES_BUILTIN_TOOLS:
        desc = t["function"]["description"]
        assert not any(w in desc for w in _AMBIGUOUS), t["function"]["name"]
        assert "本地模式" not in desc and "local mode" not in desc.lower(), t["function"]["name"]


def test_preflight_and_index_use_the_same_definition():
    preflight = (REPO / "core" / "config_preflight.py").read_text(encoding="utf-8")
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert not any(w in preflight for w in _AMBIGUOUS), "启动预检又把本地模式说成了「只用本机」"
    assert "「跨设备」开关只说这台设备自己进不进网络，从不限制智能体" in agents
