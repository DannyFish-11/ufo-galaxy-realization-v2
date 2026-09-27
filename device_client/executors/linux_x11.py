"""Linux(X11)执行插件:复用 Node_124 的动作实现(``nodes/Node_124_LinuxDesktopAuto/x11_actions.py``)。

动作名与参数尽量和 Windows 那边一致(click / type / press_key / scroll / screenshot),
智能体对哪台电脑都用同一套叫法;Linux 多出来的(拖拽、窗口、剪贴板……)照实报上去。

Wayland 会话里 xdotool 操作不了别的程序的窗口 —— ``available()`` 会如实说,而不是报可用然后每次失败。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple

from device_client.executors import DesktopExecutor


def _x11():
    from nodes.Node_124_LinuxDesktopAuto import x11_actions

    return x11_actions


class LinuxX11Executor(DesktopExecutor):
    name = "linux-x11"
    platform = "linux"

    _ACTIONS = [
        "click",
        "type",
        "press_key",
        "move",
        "drag",
        "scroll",
        "screenshot",
        "clipboard",
        "window",
        "active_window",
        "screen_size",
        "mouse_position",
        "open_url",
    ]

    def available(self) -> Tuple[bool, str]:
        if not os.environ.get("DISPLAY"):
            if os.environ.get("WAYLAND_DISPLAY"):
                return False, "这是 Wayland 会话,xdotool 操作不了别的窗口;请登录时选「X11/Xorg」会话"
            return False, "没有图形会话(DISPLAY 没设置)"
        missing = _x11().missing_tools()
        if "xdotool" in missing:
            return False, "没装 xdotool:sudo apt install xdotool scrot xclip"
        return True, ""

    def supported_actions(self) -> List[str]:
        return list(self._ACTIONS)

    def _do(self, action: str, p: Dict[str, Any]) -> Dict[str, Any]:
        x = _x11()
        if action == "click":
            return x.click(int(p["x"]), int(p["y"]), p.get("button", "left"), int(p.get("clicks", 1)))
        if action == "type":
            return x.type_text(str(p.get("text", "")), int(p.get("delay_ms", 12)))
        if action == "press_key":
            return x.press_key(str(p.get("keys") or p.get("key") or ""))
        if action == "move":
            return x.move(int(p["x"]), int(p["y"]))
        if action == "drag":
            return x.drag(
                int(p["start_x"]), int(p["start_y"]), int(p["end_x"]), int(p["end_y"]), int(p.get("duration_ms", 500))
            )
        if action == "scroll":
            return x.scroll(str(p.get("direction", "down")), int(p.get("amount", 5)), p.get("x"), p.get("y"))
        if action == "screenshot":
            return x.screenshot()
        if action == "clipboard":
            return x.clipboard(str(p.get("action", "get")), p.get("content"))
        if action == "window":
            return x.window(
                str(p.get("action", "list")),
                p.get("window_name"),
                p.get("window_id"),
                p.get("width"),
                p.get("height"),
                p.get("x"),
                p.get("y"),
            )
        if action == "active_window":
            return x.active_window()
        if action == "screen_size":
            return x.screen_size()
        if action == "mouse_position":
            return x.mouse_position()
        if action == "open_url":
            return x.open_url(str(p.get("url", "")))
        return {"success": False, "error": f"不支持 {action}"}
