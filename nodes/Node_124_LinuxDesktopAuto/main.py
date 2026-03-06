"""
Node 124: LinuxDesktopAuto - Linux 桌面自动化控制节点

基于 xdotool/xlib 实现 Linux 桌面的 UI 自动化控制，支持：
- 鼠标点击/移动/拖拽
- 键盘输入/快捷键
- 窗口管理
- 屏幕截图
- 进程管理

依赖: xdotool, scrot (截图), xclip (剪贴板)
安装: sudo apt install xdotool scrot xclip
"""
import os
import sys
import asyncio
import base64
import logging
import shutil
import tempfile
from datetime import datetime
from typing import Dict, List, Optional, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from nodes.common.cors_config import get_cors_origins

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Node_124_LinuxDesktopAuto")

app = FastAPI(title="Node 124 - LinuxDesktopAuto", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)


# ========================= 工具检测 =========================

def _check_tool(name: str) -> bool:
    return shutil.which(name) is not None

XDOTOOL_AVAILABLE = _check_tool("xdotool")
SCROT_AVAILABLE = _check_tool("scrot")
XCLIP_AVAILABLE = _check_tool("xclip")
XRANDR_AVAILABLE = _check_tool("xrandr")
WMCTRL_AVAILABLE = _check_tool("wmctrl")

logger.info(f"Linux Desktop Tools: xdotool={XDOTOOL_AVAILABLE}, scrot={SCROT_AVAILABLE}, "
            f"xclip={XCLIP_AVAILABLE}, wmctrl={WMCTRL_AVAILABLE}")


# ========================= 辅助函数 =========================

async def _run_cmd(cmd: str, timeout: float = 10.0) -> str:
    """执行系统命令"""
    try:
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
        if process.returncode != 0:
            err = stderr.decode().strip()
            logger.warning(f"Command failed: {cmd} -> {err}")
            return ""
        return stdout.decode().strip()
    except asyncio.TimeoutError:
        logger.error(f"Command timeout: {cmd}")
        return ""
    except Exception as e:
        logger.error(f"Command error: {cmd} -> {e}")
        return ""


# ========================= 请求模型 =========================

class ClickRequest(BaseModel):
    x: int
    y: int
    button: str = "left"  # left, right, middle
    clicks: int = 1

class TypeRequest(BaseModel):
    text: str
    delay_ms: int = 50

class KeyRequest(BaseModel):
    keys: str  # 如 "ctrl+c", "alt+F4", "Return"

class MoveRequest(BaseModel):
    x: int
    y: int
    duration_ms: int = 0

class DragRequest(BaseModel):
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration_ms: int = 500

class ScrollRequest(BaseModel):
    x: Optional[int] = None
    y: Optional[int] = None
    direction: str = "down"  # up, down, left, right
    amount: int = 5

class WindowRequest(BaseModel):
    action: str  # focus, minimize, maximize, close, resize, move, list
    window_name: Optional[str] = None
    window_id: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    x: Optional[int] = None
    y: Optional[int] = None

class ClipboardRequest(BaseModel):
    action: str = "get"  # get, set
    content: Optional[str] = None

class MCPRequest(BaseModel):
    tool: str
    params: Dict[str, Any] = {}


# ========================= API 端点 =========================

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "node": "Node_124_LinuxDesktopAuto",
        "platform": sys.platform,
        "tools": {
            "xdotool": XDOTOOL_AVAILABLE,
            "scrot": SCROT_AVAILABLE,
            "xclip": XCLIP_AVAILABLE,
            "wmctrl": WMCTRL_AVAILABLE,
        },
        "display": os.environ.get("DISPLAY", "not set"),
        "timestamp": datetime.now().isoformat()
    }


@app.post("/click")
async def click(req: ClickRequest):
    """鼠标点击"""
    if not XDOTOOL_AVAILABLE:
        raise HTTPException(500, "xdotool not installed")

    button_map = {"left": "1", "middle": "2", "right": "3"}
    btn = button_map.get(req.button, "1")

    # 移动鼠标到目标位置
    await _run_cmd(f"xdotool mousemove {req.x} {req.y}")
    # 执行点击
    for _ in range(req.clicks):
        await _run_cmd(f"xdotool click {btn}")

    return {"success": True, "action": "click", "x": req.x, "y": req.y,
            "button": req.button, "clicks": req.clicks}


@app.post("/type")
async def type_text(req: TypeRequest):
    """文本输入"""
    if not XDOTOOL_AVAILABLE:
        raise HTTPException(500, "xdotool not installed")

    # xdotool type 支持 Unicode
    await _run_cmd(f"xdotool type --delay {req.delay_ms} -- '{req.text}'")
    return {"success": True, "action": "type", "text_length": len(req.text)}


@app.post("/key")
async def press_key(req: KeyRequest):
    """按键/快捷键"""
    if not XDOTOOL_AVAILABLE:
        raise HTTPException(500, "xdotool not installed")

    # xdotool key 支持组合键，如 "ctrl+c", "alt+F4"
    # 将常见格式转换为 xdotool 格式
    keys = req.keys.replace("ctrl", "ctrl").replace("alt", "alt").replace("shift", "shift")
    await _run_cmd(f"xdotool key {keys}")
    return {"success": True, "action": "key", "keys": req.keys}


@app.post("/move")
async def move_mouse(req: MoveRequest):
    """移动鼠标"""
    if not XDOTOOL_AVAILABLE:
        raise HTTPException(500, "xdotool not installed")

    await _run_cmd(f"xdotool mousemove {req.x} {req.y}")
    return {"success": True, "action": "move", "x": req.x, "y": req.y}


@app.post("/drag")
async def drag(req: DragRequest):
    """拖拽操作"""
    if not XDOTOOL_AVAILABLE:
        raise HTTPException(500, "xdotool not installed")

    await _run_cmd(f"xdotool mousemove {req.start_x} {req.start_y}")
    await _run_cmd("xdotool mousedown 1")
    # 分步移动实现平滑拖拽
    steps = max(1, req.duration_ms // 50)
    dx = (req.end_x - req.start_x) / steps
    dy = (req.end_y - req.start_y) / steps
    for i in range(steps):
        x = int(req.start_x + dx * (i + 1))
        y = int(req.start_y + dy * (i + 1))
        await _run_cmd(f"xdotool mousemove {x} {y}")
        await asyncio.sleep(0.05)
    await _run_cmd("xdotool mouseup 1")

    return {"success": True, "action": "drag",
            "from": [req.start_x, req.start_y], "to": [req.end_x, req.end_y]}


@app.post("/scroll")
async def scroll(req: ScrollRequest):
    """滚动操作"""
    if not XDOTOOL_AVAILABLE:
        raise HTTPException(500, "xdotool not installed")

    if req.x is not None and req.y is not None:
        await _run_cmd(f"xdotool mousemove {req.x} {req.y}")

    direction_map = {
        "up": f"xdotool click --repeat {req.amount} 4",
        "down": f"xdotool click --repeat {req.amount} 5",
        "left": f"xdotool click --repeat {req.amount} 6",
        "right": f"xdotool click --repeat {req.amount} 7",
    }
    cmd = direction_map.get(req.direction, direction_map["down"])
    await _run_cmd(cmd)

    return {"success": True, "action": "scroll", "direction": req.direction, "amount": req.amount}


@app.post("/screenshot")
async def screenshot():
    """屏幕截图"""
    if not SCROT_AVAILABLE:
        # 回退到 xdotool + import (ImageMagick)
        if _check_tool("import"):
            tmp = tempfile.mktemp(suffix=".png")
            await _run_cmd(f"import -window root {tmp}")
        else:
            raise HTTPException(500, "scrot or ImageMagick not installed")
    else:
        tmp = tempfile.mktemp(suffix=".png")
        await _run_cmd(f"scrot {tmp}")

    try:
        with open(tmp, "rb") as f:
            img_data = base64.b64encode(f.read()).decode("utf-8")
        os.remove(tmp)
        return {"success": True, "action": "screenshot", "image_base64": img_data}
    except FileNotFoundError:
        return {"success": False, "error": "Screenshot failed"}


@app.post("/window")
async def window_action(req: WindowRequest):
    """窗口管理"""
    if not XDOTOOL_AVAILABLE:
        raise HTTPException(500, "xdotool not installed")

    result = {"success": True, "action": f"window_{req.action}"}

    if req.action == "list":
        # 列出所有窗口
        output = await _run_cmd("xdotool search --name ''")
        window_ids = output.strip().split("\n") if output else []
        windows = []
        for wid in window_ids[:50]:  # 限制数量
            if wid.strip():
                name = await _run_cmd(f"xdotool getwindowname {wid.strip()}")
                if name:
                    windows.append({"id": wid.strip(), "name": name})
        result["windows"] = windows
        return result

    # 查找窗口
    window_id = req.window_id
    if not window_id and req.window_name:
        output = await _run_cmd(f"xdotool search --name '{req.window_name}'")
        if output:
            window_id = output.strip().split("\n")[0]

    if not window_id:
        return {"success": False, "error": "Window not found"}

    action_map = {
        "focus": f"xdotool windowactivate {window_id}",
        "minimize": f"xdotool windowminimize {window_id}",
        "maximize": f"wmctrl -i -r {window_id} -b toggle,maximized_vert,maximized_horz" if WMCTRL_AVAILABLE else f"xdotool windowsize {window_id} 100% 100%",
        "close": f"xdotool windowclose {window_id}",
    }

    if req.action == "resize" and req.width and req.height:
        cmd = f"xdotool windowsize {window_id} {req.width} {req.height}"
    elif req.action == "move" and req.x is not None and req.y is not None:
        cmd = f"xdotool windowmove {window_id} {req.x} {req.y}"
    else:
        cmd = action_map.get(req.action)

    if cmd:
        await _run_cmd(cmd)
        result["window_id"] = window_id
    else:
        result = {"success": False, "error": f"Unknown window action: {req.action}"}

    return result


@app.post("/clipboard")
async def clipboard(req: ClipboardRequest):
    """剪贴板操作"""
    if not XCLIP_AVAILABLE:
        raise HTTPException(500, "xclip not installed. Install: sudo apt install xclip")

    if req.action == "get":
        content = await _run_cmd("xclip -selection clipboard -o")
        return {"success": True, "action": "clipboard_get", "content": content}
    elif req.action == "set" and req.content:
        # 使用 echo + pipe 设置剪贴板
        await _run_cmd(f"echo -n '{req.content}' | xclip -selection clipboard")
        return {"success": True, "action": "clipboard_set", "content_length": len(req.content)}
    else:
        return {"success": False, "error": "Invalid clipboard action"}


@app.get("/mouse_position")
async def get_mouse_position():
    """获取鼠标位置"""
    if not XDOTOOL_AVAILABLE:
        raise HTTPException(500, "xdotool not installed")

    output = await _run_cmd("xdotool getmouselocation")
    # 输出格式: x:123 y:456 screen:0 window:12345
    parts = {}
    for part in output.split():
        if ":" in part:
            key, val = part.split(":", 1)
            parts[key] = int(val) if val.isdigit() else val

    return {"success": True, "x": parts.get("x", 0), "y": parts.get("y", 0),
            "screen": parts.get("screen", 0)}


@app.get("/screen_size")
async def get_screen_size():
    """获取屏幕分辨率"""
    if XRANDR_AVAILABLE:
        output = await _run_cmd("xrandr | head -1")
        # 解析 "Screen 0: ... current 1920 x 1080"
        if "current" in output:
            parts = output.split("current")[1].strip().split(",")[0].strip()
            dims = parts.split(" x ")
            if len(dims) == 2:
                return {"success": True, "width": int(dims[0].strip()), "height": int(dims[1].strip())}
    elif XDOTOOL_AVAILABLE:
        output = await _run_cmd("xdotool getdisplaygeometry")
        parts = output.split()
        if len(parts) == 2:
            return {"success": True, "width": int(parts[0]), "height": int(parts[1])}

    return {"success": False, "error": "Cannot determine screen size"}


@app.get("/active_window")
async def get_active_window():
    """获取当前活动窗口信息"""
    if not XDOTOOL_AVAILABLE:
        raise HTTPException(500, "xdotool not installed")

    wid = await _run_cmd("xdotool getactivewindow")
    if wid:
        name = await _run_cmd(f"xdotool getwindowname {wid}")
        pid = await _run_cmd(f"xdotool getwindowpid {wid}")
        geo = await _run_cmd(f"xdotool getwindowgeometry {wid}")
        return {
            "success": True,
            "window_id": wid,
            "window_name": name,
            "pid": pid,
            "geometry": geo
        }
    return {"success": False, "error": "No active window"}


# ========================= MCP 统一接口 =========================

@app.post("/mcp/call")
async def mcp_call(req: MCPRequest):
    """MCP统一调用接口"""
    tool_map = {
        "click": lambda p: click(ClickRequest(**p)),
        "type": lambda p: type_text(TypeRequest(**p)),
        "key": lambda p: press_key(KeyRequest(**p)),
        "move": lambda p: move_mouse(MoveRequest(**p)),
        "drag": lambda p: drag(DragRequest(**p)),
        "scroll": lambda p: scroll(ScrollRequest(**p)),
        "screenshot": lambda p: screenshot(),
        "window": lambda p: window_action(WindowRequest(**p)),
        "clipboard": lambda p: clipboard(ClipboardRequest(**p)),
        "mouse_position": lambda p: get_mouse_position(),
        "screen_size": lambda p: get_screen_size(),
        "active_window": lambda p: get_active_window(),
    }

    handler = tool_map.get(req.tool)
    if handler:
        try:
            return await handler(req.params)
        except Exception as e:
            return {"success": False, "error": str(e)}
    else:
        return {"success": False, "error": f"Unknown tool: {req.tool}",
                "available_tools": list(tool_map.keys())}


@app.get("/tools")
async def list_tools():
    """列出所有可用工具"""
    return {
        "tools": [
            {"name": "click", "description": "鼠标点击", "params": ["x", "y", "button", "clicks"]},
            {"name": "type", "description": "文本输入", "params": ["text", "delay_ms"]},
            {"name": "key", "description": "按键/快捷键", "params": ["keys"]},
            {"name": "move", "description": "移动鼠标", "params": ["x", "y"]},
            {"name": "drag", "description": "鼠标拖拽", "params": ["start_x", "start_y", "end_x", "end_y"]},
            {"name": "scroll", "description": "滚动", "params": ["direction", "amount", "x", "y"]},
            {"name": "screenshot", "description": "屏幕截图", "params": []},
            {"name": "window", "description": "窗口管理", "params": ["action", "window_name"]},
            {"name": "clipboard", "description": "剪贴板操作", "params": ["action", "content"]},
            {"name": "mouse_position", "description": "获取鼠标位置", "params": []},
            {"name": "screen_size", "description": "获取屏幕分辨率", "params": []},
            {"name": "active_window", "description": "获取活动窗口", "params": []},
        ]
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8124"))
    uvicorn.run(app, host="0.0.0.0", port=port)
