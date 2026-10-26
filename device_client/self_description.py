"""device_client/self_description.py — 电脑客户端 / Agent 载体的设备自述(``device_self/1``)。

中心在 ``core/device_self.py`` 读,设计见 ``docs/DEVICE_SELF_DESCRIPTION_DESIGN.md`` 第 3 节;手机、手表用安卓仓
``shared-protocol`` 的 ``DeviceSelfDescription.kt`` 拼同一个形状。

每个动作说明做了会怎样(``effect``):只看的(截屏、读窗口、读文件、列目录、读状态)是 ``read``,其余都是
``act``(在这台机器上改变状态)。载体跑代码也算 ``act``:它只在不联网、限资源、跑完即删的沙箱里跑。
没有不可逆或对外发出的动作 —— 有了就照实标 ``danger`` / ``send``,中心按高风险确认。
"""

from __future__ import annotations

import platform
from typing import Any, Dict, List

SCHEMA = "device_self/1"

#: 桌面执行插件常见动作的一句话说明(说效果,不说实现)。
DESCRIPTIONS: Dict[str, str] = {
    "click": "点屏幕上的一个位置(x、y)",
    "type": "往当前输入框里输入文字",
    "press_key": "按一个键或组合键",
    "press_keys": "依次按几个键或组合键",
    "move": "把鼠标移到一个位置",
    "drag": "从一个位置拖到另一个位置",
    "scroll": "滚动当前界面",
    "screenshot": "截一张当前屏幕",
    "clipboard": "读或写剪贴板",
    "window": "切换、最小化、关闭窗口",
    "active_window": "看当前前台是哪个窗口",
    "screen_size": "读屏幕分辨率",
    "mouse_position": "读鼠标现在在哪",
    "get_screen_state": "读当前屏幕上有哪些窗口和控件",
    "find_and_click": "按文字或控件名找到它并点一下",
    "find_and_type": "按控件名找到输入框并输入文字",
}

#: 只看、不改变任何东西的动作。
READS = frozenset(
    {
        "screenshot",
        "active_window",
        "screen_size",
        "mouse_position",
        "get_screen_state",
        "get_status",
        "read_file",
        "list_files",
    }
)


def effect_for(action: str) -> str:
    return "read" if action in READS else "act"


def _actions(executor: Any, actions: List[str]) -> List[Dict[str, Any]]:
    schemas = getattr(executor, "capability_schemas", None)
    by_action = {s["action"]: s for s in (schemas() if callable(schemas) else []) if isinstance(s, dict)}
    out = []
    for a in actions:
        s = by_action.get(a, {})
        params = s.get("params") or s.get("parameters") or {"type": "object", "properties": {}}
        out.append(
            {
                "name": a,
                "description": str(s.get("description") or DESCRIPTIONS.get(a) or a)[:300],
                "effect": effect_for(a),
                "params": params,
            }
        )
    return out


def about(carrier: bool) -> str:
    system = platform.system() or "这台"
    if carrier:
        return (
            f"一台 {system} 机器上的 Agent 载体。整段目标交给它自己的 Agent 做(devices__delegate);"
            "代码只在不联网的沙箱里跑,文件只在它的工作目录里。"
        )
    return f"一台 {system} 电脑,接受截图、点击、输入这类单个动作。"


def build(
    executor: Any, actions: List[str], *, name: str, kind: str, carrier: bool, hosts_agent: str
) -> Dict[str, Any]:
    """这台机器的设备自述。``actions`` 是此刻做得了的动作(执行插件不可用时是空表)。"""
    return {
        "schema": SCHEMA,
        "name": str(name or "")[:80],
        "kind": str(kind or "")[:40],
        "about": about(carrier),
        "actions": _actions(executor, actions),
        "declares": {
            # 电脑客户端没有回答提问的界面,也不显示请求进度
            "answers_decisions": False,
            "shows_request_progress": False,
            "hosts_agent": hosts_agent,
            # 配对时声明靠系统里的 Tailscale 进自建内网(device_client/pairing.py)
            "tailnet": "system",
        },
    }
