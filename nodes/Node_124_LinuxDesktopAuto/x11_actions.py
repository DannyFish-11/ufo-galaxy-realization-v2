"""Linux(X11)桌面动作的唯一实现:xdotool / scrot / xclip / xrandr / wmctrl。

Node_124 的 HTTP 面和笔记本客户端的 Linux 执行插件(``device_client/executors/linux_x11.py``)
都调这里,不各写一份。

规则只有一条:**命令一律按参数列表执行,不拼字符串**。此前 Node_124 把用户给的文字
拼进命令串再 ``shlex.split``:文字里带一个单引号就解析失败,函数静默返回空、接口照样报
成功;``xrandr | head -1`` 这种管道在不经 shell 的执行方式下根本不成立。

每个函数返回 ``{"success": bool, ...}``,失败带 ``error``,不抛异常。``run`` 可注入(测试)。
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def _default_run(
    argv: List[str], input: Optional[str] = None, timeout: float = 10.0, capture: bool = True
) -> "subprocess.CompletedProcess[str]":
    if capture:
        return subprocess.run(argv, input=input, capture_output=True, text=True, timeout=timeout)  # noqa: S603
    # 不接输出:xclip 设剪贴板后会留一个后台进程持有选区,它继承的输出管道不关,
    # 接着输出的调用方就一直等到超时(实测:剪贴板其实设上了,接口却报超时)。
    return subprocess.run(  # noqa: S603
        argv, input=input, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, timeout=timeout
    )


_run: Runner = _default_run
_which: Callable[[str], Optional[str]] = shutil.which


def _set_runner(run: Optional[Runner] = None, which: Optional[Callable[[str], Optional[str]]] = None) -> None:
    """测试用:替换执行命令与查找命令的实现。传 None 复原。"""
    global _run, _which
    _run = run or _default_run
    _which = which or shutil.which


def has(tool: str) -> bool:
    return _which(tool) is not None


def _x(argv: List[str], input: Optional[str] = None, timeout: float = 10.0, capture: bool = True) -> Dict[str, Any]:
    try:
        r = _run(argv, input=input, timeout=timeout, capture=capture)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"{argv[0]} 超时"}
    except FileNotFoundError:
        return {"success": False, "error": f"没装 {argv[0]}"}
    if r.returncode != 0:
        return {"success": False, "error": (r.stderr or r.stdout or f"{argv[0]} 失败").strip()[:300]}
    return {"success": True, "stdout": (r.stdout or "").strip()}


def _need(tool: str, pkg: str = "") -> Optional[Dict[str, Any]]:
    if has(tool):
        return None
    return {"success": False, "error": f"没装 {tool}", "how_to_fix": f"sudo apt install {pkg or tool}"}


def missing_tools() -> List[str]:
    return [t for t in ("xdotool", "scrot", "xclip") if not has(t)]


_BUTTONS = {"left": "1", "middle": "2", "right": "3"}


def click(x: int, y: int, button: str = "left", clicks: int = 1) -> Dict[str, Any]:
    if e := _need("xdotool"):
        return e
    r = _x(["xdotool", "mousemove", str(int(x)), str(int(y))])
    if not r["success"]:
        return r
    r = _x(["xdotool", "click", "--repeat", str(max(1, int(clicks))), _BUTTONS.get(button, "1")])
    return {**r, "action": "click", "x": x, "y": y, "button": button, "clicks": clicks} if r["success"] else r


def type_text(text: str, delay_ms: int = 12) -> Dict[str, Any]:
    if e := _need("xdotool"):
        return e
    # 文字经 stdin 交给 xdotool(``type --file -``):不进命令行,任何引号、换行、以 - 开头的内容都原样打出
    r = _x(["xdotool", "type", "--delay", str(int(delay_ms)), "--file", "-"], input=text, timeout=30.0 + len(text) / 20)
    return {**r, "action": "type", "text_length": len(text)} if r["success"] else r


def press_key(keys: str) -> Dict[str, Any]:
    if e := _need("xdotool"):
        return e
    combos = [k for k in str(keys).replace(" ", "").split(",") if k]
    if not combos or any(k.startswith("-") for k in combos):
        return {"success": False, "error": f"按键写法不对:{keys!r}(例:ctrl+c、alt+F4、Return)"}
    r = _x(["xdotool", "key", "--", *combos])
    return {**r, "action": "key", "keys": keys} if r["success"] else r


def move(x: int, y: int) -> Dict[str, Any]:
    if e := _need("xdotool"):
        return e
    r = _x(["xdotool", "mousemove", str(int(x)), str(int(y))])
    return {**r, "action": "move", "x": x, "y": y} if r["success"] else r


def drag(start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 500) -> Dict[str, Any]:
    if e := _need("xdotool"):
        return e
    steps = max(1, int(duration_ms) // 50)
    seq = [["xdotool", "mousemove", str(int(start_x)), str(int(start_y))], ["xdotool", "mousedown", "1"]]
    for i in range(steps):
        x = int(start_x + (end_x - start_x) * (i + 1) / steps)
        y = int(start_y + (end_y - start_y) * (i + 1) / steps)
        seq.append(["xdotool", "mousemove", str(x), str(y)])
    seq.append(["xdotool", "mouseup", "1"])
    for argv in seq:
        r = _x(argv)
        if not r["success"]:
            _x(["xdotool", "mouseup", "1"])  # 别把鼠标键卡在按下状态
            return r
        if argv[1] == "mousemove" and len(seq) > 3:
            time.sleep(0.05)
    return {"success": True, "action": "drag", "from": [start_x, start_y], "to": [end_x, end_y]}


_SCROLL = {"up": "4", "down": "5", "left": "6", "right": "7"}


def scroll(
    direction: str = "down", amount: int = 5, x: Optional[int] = None, y: Optional[int] = None
) -> Dict[str, Any]:
    if e := _need("xdotool"):
        return e
    if direction not in _SCROLL:
        return {"success": False, "error": f"方向只能是 {sorted(_SCROLL)}"}
    if x is not None and y is not None:
        r = _x(["xdotool", "mousemove", str(int(x)), str(int(y))])
        if not r["success"]:
            return r
    r = _x(["xdotool", "click", "--repeat", str(max(1, int(amount))), _SCROLL[direction]])
    return {**r, "action": "scroll", "direction": direction, "amount": amount} if r["success"] else r


def screenshot() -> Dict[str, Any]:
    """整屏截图,返回 base64 PNG。临时文件放在 0700 私有目录里(见 Node_124 原注释:防抢占路径)。"""
    tool = "scrot" if has("scrot") else ("import" if has("import") else "")
    if not tool:
        return {"success": False, "error": "没装截图工具", "how_to_fix": "sudo apt install scrot"}
    tmpdir = tempfile.mkdtemp(prefix="galaxy-screenshot-")
    path = os.path.join(tmpdir, "screen.png")
    try:
        argv = ["scrot", path] if tool == "scrot" else ["import", "-window", "root", path]
        r = _x(argv, timeout=15.0)
        if not r["success"]:
            return r
        try:
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode("ascii")
        except FileNotFoundError:
            return {"success": False, "error": "截图没有生成文件"}
        return {"success": True, "action": "screenshot", "image_base64": data, "mime": "image/png"}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def clipboard(action: str = "get", content: Optional[str] = None) -> Dict[str, Any]:
    if e := _need("xclip"):
        return e
    if action == "get":
        r = _x(["xclip", "-selection", "clipboard", "-o"])
        return {"success": True, "action": "clipboard_get", "content": r.get("stdout", "")} if r["success"] else r
    if action == "set" and content is not None:
        r = _x(["xclip", "-selection", "clipboard"], input=content, capture=False)
        return {**r, "action": "clipboard_set", "content_length": len(content)} if r["success"] else r
    return {"success": False, "error": "剪贴板动作只能是 get,或带 content 的 set"}


def mouse_position() -> Dict[str, Any]:
    if e := _need("xdotool"):
        return e
    r = _x(["xdotool", "getmouselocation"])
    if not r["success"]:
        return r
    parts = dict(p.split(":", 1) for p in r["stdout"].split() if ":" in p)
    return {
        "success": True,
        "x": int(parts.get("x", 0)),
        "y": int(parts.get("y", 0)),
        "screen": int(parts.get("screen", 0)),
    }


def screen_size() -> Dict[str, Any]:
    if has("xdotool"):
        r = _x(["xdotool", "getdisplaygeometry"])
        dims = r.get("stdout", "").split()
        if r["success"] and len(dims) == 2:
            return {"success": True, "width": int(dims[0]), "height": int(dims[1])}
    if has("xrandr"):
        r = _x(["xrandr", "--current"])
        first = (r.get("stdout", "").splitlines() or [""])[0]
        if r["success"] and "current" in first:
            w, h = first.split("current", 1)[1].split(",")[0].split(" x ")
            return {"success": True, "width": int(w.strip()), "height": int(h.strip())}
    return {"success": False, "error": "取不到屏幕分辨率(需要 xdotool 或 xrandr,并且有 DISPLAY)"}


def active_window() -> Dict[str, Any]:
    if e := _need("xdotool"):
        return e
    r = _x(["xdotool", "getactivewindow"])
    if not r["success"] or not r["stdout"]:
        return {"success": False, "error": "没有活动窗口"}
    wid = r["stdout"]
    return {
        "success": True,
        "window_id": wid,
        "window_name": _x(["xdotool", "getwindowname", wid]).get("stdout", ""),
        "pid": _x(["xdotool", "getwindowpid", wid]).get("stdout", ""),
        "geometry": _x(["xdotool", "getwindowgeometry", wid]).get("stdout", ""),
    }


def window(
    action: str,
    window_name: Optional[str] = None,
    window_id: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    x: Optional[int] = None,
    y: Optional[int] = None,
) -> Dict[str, Any]:
    if e := _need("xdotool"):
        return e
    if action == "list":
        r = _x(["xdotool", "search", "--onlyvisible", "--name", "."])
        ids = [w for w in r.get("stdout", "").split("\n") if w.strip()][:50]
        wins = []
        for wid in ids:
            name = _x(["xdotool", "getwindowname", wid]).get("stdout", "")
            if name:
                wins.append({"id": wid, "name": name})
        return {"success": True, "action": "window_list", "windows": wins}
    wid = str(window_id or "")
    if not wid and window_name:
        r = _x(["xdotool", "search", "--name", "--", str(window_name)])
        found = [w for w in r.get("stdout", "").split("\n") if w.strip()]
        wid = found[0] if found else ""
    if not wid or not wid.isdigit():
        return {"success": False, "error": "找不到这个窗口"}
    if action == "resize" and width and height:
        argv = ["xdotool", "windowsize", wid, str(int(width)), str(int(height))]
    elif action == "move" and x is not None and y is not None:
        argv = ["xdotool", "windowmove", wid, str(int(x)), str(int(y))]
    elif action == "maximize" and has("wmctrl"):
        argv = ["wmctrl", "-i", "-r", wid, "-b", "toggle,maximized_vert,maximized_horz"]
    else:
        verbs = {"focus": "windowactivate", "minimize": "windowminimize", "close": "windowclose", "maximize": None}
        if action not in verbs:
            return {"success": False, "error": f"不认识的窗口动作:{action}"}
        argv = (
            ["xdotool", "windowsize", wid, "100%", "100%"] if verbs[action] is None else ["xdotool", verbs[action], wid]
        )
    r = _x(argv)
    return {**r, "action": f"window_{action}", "window_id": wid} if r["success"] else r


def open_url(url: str) -> Dict[str, Any]:
    if not str(url).startswith(("http://", "https://")):
        return {"success": False, "error": "只打开 http/https 链接"}
    if e := _need("xdg-open", "xdg-utils"):
        return e
    r = _x(["xdg-open", str(url)])
    return {**r, "action": "open_url", "url": url} if r["success"] else r
