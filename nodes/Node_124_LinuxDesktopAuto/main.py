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
import asyncio
import logging
import os
import shutil
import sys
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from nodes.common.cors_config import get_cors_origins

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Node_124_LinuxDesktopAuto")

from nodes.common.action_gate import action_guard

try:  # 作为包导入(nodes.Node_124_LinuxDesktopAuto.main)与直接运行两种方式都要能找到
    from nodes.Node_124_LinuxDesktopAuto import x11_actions as x11
except ImportError:  # pragma: no cover
    import x11_actions as x11  # type: ignore

from nodes.common.node_auth import install_node_auth

app = FastAPI(title="Node 124 - LinuxDesktopAuto", version="1.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

# HTTP 面的身份认证。权限闸回答"这个动作允许吗",这一层回答"调用方是谁"——
# 此前这个节点两个问题都没有答案。实现在 nodes.common.node_auth,
# 判定复用 core.auth(网关与 launcher 早就在用的那一套)。
install_node_auth(app, "Node_124_LinuxDesktopAuto")

# HTTP 面的动作权限闸。判定在 core.node_action_permissions,接线在
# nodes.common.action_gate —— 此前这一面一道门都没有,manifest 只对
# 统一执行器那条路生效。
_require = action_guard("Node_124_LinuxDesktopAuto")


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


# 动作本体都在 x11_actions(与笔记本客户端的 Linux 执行插件共用一份):命令按参数列表
# 执行、不拼字符串。这里只管 HTTP 面:先过动作权限闸,再把活交出去。


async def _do(fn, *args, **kwargs):
    return await asyncio.to_thread(fn, *args, **kwargs)


@app.post("/click")
async def click(req: ClickRequest):
    """鼠标点击"""
    _require("click")
    return await _do(x11.click, req.x, req.y, req.button, req.clicks)


@app.post("/type")
async def type_text(req: TypeRequest):
    """文本输入(文字经 stdin 交给 xdotool,任何引号都原样打出)"""
    _require("type_text")
    return await _do(x11.type_text, req.text, req.delay_ms)


@app.post("/key")
async def press_key(req: KeyRequest):
    """按键/快捷键,如 ctrl+c、alt+F4、Return"""
    _require("press_key")
    return await _do(x11.press_key, req.keys)


@app.post("/move")
async def move_mouse(req: MoveRequest):
    """移动鼠标"""
    _require("move_mouse")
    return await _do(x11.move, req.x, req.y)


@app.post("/drag")
async def drag(req: DragRequest):
    """拖拽"""
    _require("drag")
    return await _do(x11.drag, req.start_x, req.start_y, req.end_x, req.end_y, req.duration_ms)


@app.post("/scroll")
async def scroll(req: ScrollRequest):
    """滚动"""
    _require("scroll")
    return await _do(x11.scroll, req.direction, req.amount, req.x, req.y)


@app.post("/screenshot")
async def screenshot():
    """整屏截图(临时文件在 0700 私有目录里,见 x11_actions.screenshot)"""
    _require("screenshot")
    return await _do(x11.screenshot)


@app.post("/window")
async def window_action(req: WindowRequest):
    """窗口管理:focus / minimize / maximize / close / resize / move / list"""
    _require("window_action")
    return await _do(
        x11.window, req.action, req.window_name, req.window_id, req.width, req.height, req.x, req.y
    )


@app.post("/clipboard")
async def clipboard(req: ClipboardRequest):
    """剪贴板 get / set"""
    _require("clipboard")
    return await _do(x11.clipboard, req.action, req.content)


@app.get("/mouse_position")
async def get_mouse_position():
    """鼠标位置"""
    _require("get_mouse_position")
    return await _do(x11.mouse_position)


@app.get("/screen_size")
async def get_screen_size():
    """屏幕分辨率"""
    _require("get_screen_size")
    return await _do(x11.screen_size)


@app.get("/active_window")
async def get_active_window():
    """当前活动窗口"""
    _require("get_active_window")
    return await _do(x11.active_window)


# ========================= MCP 统一接口 =========================


_MCP_TOOL_ACTIONS = {
    "click": "click",
    "type": "type_text",
    "key": "press_key",
    "move": "move_mouse",
    "drag": "drag",
    "scroll": "scroll",
    "screenshot": "screenshot",
    "window": "window_action",
    "clipboard": "clipboard",
    "mouse_position": "get_mouse_position",
    "screen_size": "get_screen_size",
    "active_window": "get_active_window",
}


@app.post("/mcp/call")
async def mcp_call(req: MCPRequest):
    """MCP统一调用接口"""
    # 工具名 → manifest 里的动作名(两者不同:type ↔ type_text 等),先按动作名过闸;
    # 不认识的工具名照样过闸 —— 闸对未声明的动作 fail closed。
    # 此前这一行引用了一个不存在的变量 request,每次调用都 NameError。
    _require(_MCP_TOOL_ACTIONS.get(req.tool, req.tool))
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
