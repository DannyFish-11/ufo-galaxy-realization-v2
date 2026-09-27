"""macOS 执行插件:尽量只用系统自带的命令。

* 截图:``screencapture``
* 打字 / 按键 / 前台应用:``osascript``(System Events)。文字**作为 argv 传进脚本**,
  不拼进 AppleScript 源码 —— 带引号、反斜杠、换行的内容都原样打出,也注入不了脚本。
* 剪贴板:``pbcopy`` / ``pbpaste``;打开应用或链接:``open``
* 鼠标:优先 ``cliclick``(brew install cliclick),没有就退到 pyautogui,都没有就如实说。

macOS 要求给「运行这个客户端的终端」开两项权限,否则动作会被系统静默拒绝:
系统设置 → 隐私与安全性 → **辅助功能**(点击、打字)与 **屏幕录制**(截图)。
出错时把这句话带给用户,而不是只回一个退出码。
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple

from device_client.executors import DesktopExecutor

PERMISSION_HINT = "系统设置 → 隐私与安全性 → 辅助功能 / 屏幕录制,给运行本客户端的终端打开"

#: 特殊键 → macOS key code(System Events ``key code``)
_KEY_CODES = {
    "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "backspace": 51,
    "escape": 53, "esc": 53, "left": 123, "right": 124, "down": 125, "up": 126,
    "home": 115, "end": 119, "pageup": 116, "pagedown": 121, "forwarddelete": 117,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
    "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}  # fmt: skip
_MODIFIERS = {
    "cmd": "command down", "command": "command down", "ctrl": "control down", "control": "control down",
    "alt": "option down", "option": "option down", "shift": "shift down",
}  # fmt: skip

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _default_run(
    argv: List[str], input: Optional[str] = None, timeout: float = 15.0
) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout)  # noqa: S603


def key_script(keys: str) -> Tuple[List[str], List[str]]:
    """``cmd+shift+s`` / ``Return`` / ``ctrl+c`` → (osascript -e 参数, argv)。

    普通字符键用 ``keystroke (item 1 of argv)``,特殊键用 ``key code N``;修饰键拼成 ``using {...}``。
    """
    parts = [p for p in str(keys).replace(" ", "").split("+") if p]
    if not parts:
        raise ValueError("没有按键")
    *mods, key = parts
    using = []
    for m in mods:
        if m.lower() not in _MODIFIERS:
            raise ValueError(f"不认识的修饰键 {m!r}(可用:cmd ctrl alt/option shift)")
        using.append(_MODIFIERS[m.lower()])
    suffix = f" using {{{', '.join(using)}}}" if using else ""
    if key.lower() in _KEY_CODES:
        body = f'tell application "System Events" to key code {_KEY_CODES[key.lower()]}{suffix}'
        return ["on run argv", body, "end run"], []
    if len(key) != 1:
        raise ValueError(f"不认识的键 {key!r}")
    body = f'tell application "System Events" to keystroke (item 1 of argv){suffix}'
    return ["on run argv", body, "end run"], [key]


class MacOSExecutor(DesktopExecutor):
    name = "macos"
    platform = "macos"

    def __init__(self, run: Optional[Runner] = None, which: Optional[Callable[[str], Optional[str]]] = None) -> None:
        self._run = run or _default_run
        self._which = which or shutil.which

    # ── 能力 ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _has_pyautogui() -> bool:
        try:
            import pyautogui  # type: ignore  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False

    def _mouse_backend(self) -> str:
        if self._which("cliclick"):
            return "cliclick"
        return "pyautogui" if self._has_pyautogui() else ""

    def available(self) -> Tuple[bool, str]:
        if sys.platform != "darwin" and not os.environ.get("GALAXY_MACOS_EXECUTOR_FORCE"):
            return False, "只在 macOS 上可用"
        if not self._which("osascript"):
            return False, "找不到 osascript"
        return True, ""

    def supported_actions(self) -> List[str]:
        acts = ["type", "press_key", "screenshot", "clipboard", "active_window", "open_app", "open_url"]
        if self._mouse_backend():
            acts += ["click", "move", "drag"]
        if self._has_pyautogui():  # cliclick 不会滚动
            acts.append("scroll")
        return acts

    # ── 执行 ─────────────────────────────────────────────────────────────────

    def _x(self, argv: List[str], input: Optional[str] = None, timeout: float = 15.0) -> Dict[str, Any]:
        try:
            r = self._run(argv, input=input, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"{argv[0]} 超时"}
        except FileNotFoundError:
            return {"success": False, "error": f"找不到 {argv[0]}"}
        if r.returncode != 0:
            err = (r.stderr or r.stdout or f"{argv[0]} 失败").strip()[:300]
            if "not allowed" in err or "1002" in err or "assistive" in err.lower():
                return {"success": False, "error": err, "how_to_fix": PERMISSION_HINT}
            return {"success": False, "error": err}
        return {"success": True, "stdout": (r.stdout or "").strip()}

    def _osa(self, lines: List[str], argv: List[str]) -> Dict[str, Any]:
        cmd = ["osascript"]
        for line in lines:
            cmd += ["-e", line]
        return self._x(cmd + ["--", *argv])

    def _mouse(self, action: str, p: Dict[str, Any]) -> Dict[str, Any]:
        backend = self._mouse_backend()
        if backend == "cliclick" and action != "scroll":
            if action == "click":
                verb = {"left": "c", "right": "rc"}.get(p.get("button", "left"), "c")
                verb = "dc" if int(p.get("clicks", 1)) == 2 and verb == "c" else verb
                return self._x(["cliclick", f"{verb}:{int(p['x'])},{int(p['y'])}"])
            if action == "move":
                return self._x(["cliclick", f"m:{int(p['x'])},{int(p['y'])}"])
            if action == "drag":
                return self._x(
                    [
                        "cliclick",
                        f"dd:{int(p['start_x'])},{int(p['start_y'])}",
                        f"du:{int(p['end_x'])},{int(p['end_y'])}",
                    ]
                )
        import pyautogui  # type: ignore

        if action == "click":
            pyautogui.click(int(p["x"]), int(p["y"]), clicks=int(p.get("clicks", 1)), button=p.get("button", "left"))
        elif action == "move":
            pyautogui.moveTo(int(p["x"]), int(p["y"]))
        elif action == "drag":
            pyautogui.moveTo(int(p["start_x"]), int(p["start_y"]))
            pyautogui.dragTo(int(p["end_x"]), int(p["end_y"]), duration=int(p.get("duration_ms", 500)) / 1000)
        elif action == "scroll":
            amount = int(p.get("amount", 5))
            pyautogui.scroll(amount if p.get("direction", "down") == "up" else -amount)
        return {"success": True}

    def _do(self, action: str, p: Dict[str, Any]) -> Dict[str, Any]:
        if action == "type":
            text = str(p.get("text", ""))
            return {
                **self._osa(
                    ["on run argv", 'tell application "System Events" to keystroke (item 1 of argv)', "end run"], [text]
                ),
                "text_length": len(text),
            }
        if action == "press_key":
            try:
                lines, argv = key_script(str(p.get("keys") or p.get("key") or ""))
            except ValueError as exc:
                return {"success": False, "error": str(exc)}
            return self._osa(lines, argv)
        if action == "screenshot":
            tmpdir = tempfile.mkdtemp(prefix="galaxy-screenshot-")
            path = os.path.join(tmpdir, "screen.png")
            try:
                r = self._x(["screencapture", "-x", "-t", "png", path])
                if not r["success"]:
                    return r
                if not os.path.exists(path) or os.path.getsize(path) == 0:
                    return {"success": False, "error": "截图是空的", "how_to_fix": PERMISSION_HINT}
                with open(path, "rb") as f:
                    return {
                        "success": True,
                        "image_base64": base64.b64encode(f.read()).decode("ascii"),
                        "mime": "image/png",
                    }
            finally:
                shutil.rmtree(tmpdir, ignore_errors=True)
        if action == "clipboard":
            if p.get("action", "get") == "get":
                r = self._x(["pbpaste"])
                return {"success": True, "content": r.get("stdout", "")} if r["success"] else r
            return self._x(["pbcopy"], input=str(p.get("content", "")))
        if action == "active_window":
            r = self._osa(
                ['tell application "System Events" to get name of first application process whose frontmost is true'],
                [],
            )
            return {"success": True, "app": r.get("stdout", "")} if r["success"] else r
        if action == "open_app":
            name = str(p.get("name") or p.get("app") or "")
            if not name or name.startswith("-"):
                return {"success": False, "error": "需要应用名,例如 Safari"}
            return self._x(["open", "-a", name])
        if action == "open_url":
            url = str(p.get("url", ""))
            if not url.startswith(("http://", "https://")):
                return {"success": False, "error": "只打开 http/https 链接"}
            return self._x(["open", url])
        if action in ("click", "move", "drag", "scroll"):
            return self._mouse(action, p)
        return {"success": False, "error": f"不支持 {action}"}
