"""
Node 36: UIAWindows - 真实的 Windows 桌面自动化
==============================================
使用 pyautogui 和 pygetwindow 实现真实的桌面自动化操作。

注意: 此节点只能在 Windows 上运行，需要安装:
pip install pyautogui pillow pygetwindow pyperclip
"""

import base64
import os
import sys
import time
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from nodes.common.cors_config import get_cors_origins

app = FastAPI(title="Node 36 - UIAWindows", version="2.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# 检测是否在 Windows 上运行
IS_WINDOWS = sys.platform == "win32"

# 延迟导入 Windows 特定模块
pyautogui = None
pygetwindow = None

if IS_WINDOWS:
    try:
        import pyautogui as _pyautogui

        pyautogui = _pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.1
    except ImportError:
        pass
    try:
        import pygetwindow as _pygetwindow

        pygetwindow = _pygetwindow
    except ImportError:
        pass


# ============ 请求模型 ============
class ClickRequest(BaseModel):
    x: int
    y: int
    button: str = "left"
    clicks: int = 1


class TypeRequest(BaseModel):
    text: str
    interval: float = 0.05


class HotkeyRequest(BaseModel):
    keys: List[str]


class MoveRequest(BaseModel):
    x: int
    y: int
    duration: float = 0.5


class WindowRequest(BaseModel):
    title: str
    action: str = "focus"


class DragRequest(BaseModel):
    start_x: int
    start_y: int
    end_x: int
    end_y: int
    duration: float = 0.5


# ============ 工具类 ============
#: 按住一个键最多多久。上游 hold_key 给到 300 秒,这里按本机风险收紧 ——
#: 一个卡住的 hold 会让后续每一次输入都带着那个修饰键,表现是"键盘坏了"。
HOLD_KEY_MAX_SECONDS = 30.0


class UIATools:
    def __init__(self):
        self.initialized = IS_WINDOWS and pyautogui is not None

    def check(self):
        if not IS_WINDOWS:
            return {"error": "This node only works on Windows", "platform": sys.platform}
        if not pyautogui:
            return {"error": "pyautogui not installed. Run: pip install pyautogui"}
        return None

    def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            pyautogui.click(x=x, y=y, button=button, clicks=clicks)
            return {"success": True, "action": "click", "x": x, "y": y, "button": button, "clicks": clicks}
        except Exception as e:
            return {"error": str(e)}

    def double_click(self, x: int, y: int) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            pyautogui.doubleClick(x=x, y=y)
            return {"success": True, "action": "double_click", "x": x, "y": y}
        except Exception as e:
            return {"error": str(e)}

    def right_click(self, x: int, y: int) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            pyautogui.rightClick(x=x, y=y)
            return {"success": True, "action": "right_click", "x": x, "y": y}
        except Exception as e:
            return {"error": str(e)}

    def type_text(self, text: str, interval: float = 0.05) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            # 对于中文，使用复制粘贴
            if any("\u4e00" <= char <= "\u9fff" for char in text):
                try:
                    import pyperclip

                    pyperclip.copy(text)
                    pyautogui.hotkey("ctrl", "v")
                except ImportError:
                    pyautogui.write(text, interval=interval)
            else:
                pyautogui.write(text, interval=interval)
            return {"success": True, "action": "type", "text": text}
        except Exception as e:
            return {"error": str(e)}

    def press_key(self, key: str) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            pyautogui.press(key)
            return {"success": True, "action": "press", "key": key}
        except Exception as e:
            return {"error": str(e)}

    def hotkey(self, keys: List[str]) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            pyautogui.hotkey(*keys)
            return {"success": True, "action": "hotkey", "keys": keys}
        except Exception as e:
            return {"error": str(e)}

    def move_mouse(self, x: int, y: int, duration: float = 0.5) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            pyautogui.moveTo(x, y, duration=duration)
            return {"success": True, "action": "move", "x": x, "y": y}
        except Exception as e:
            return {"error": str(e)}

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            pyautogui.moveTo(start_x, start_y)
            pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration)
            return {"success": True, "action": "drag", "from": [start_x, start_y], "to": [end_x, end_y]}
        except Exception as e:
            return {"error": str(e)}

    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            pyautogui.scroll(clicks, x=x, y=y)
            return {"success": True, "action": "scroll", "clicks": clicks}
        except Exception as e:
            return {"error": str(e)}

    # ── 对齐厂商动作集补的五个 + zoom(2026-09) ─────────────────────────
    # 此前 computer use 闭环碰到这些动作只能跳过,而模型看不出是自己给错了
    # 还是这边不支持,下一轮常常原样再给一次,白烧一步预算。

    def middle_click(self, x: int, y: int) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            pyautogui.click(x=x, y=y, button="middle")
            return {"success": True, "action": "middle_click", "x": x, "y": y}
        except Exception as e:
            return {"error": str(e)}

    def triple_click(self, x: int, y: int) -> Dict:
        """三击选中整行/整段。连点两次代替不了 —— 间隔一长就成了两次双击。"""
        err = self.check()
        if err:
            return err
        try:
            pyautogui.click(x=x, y=y, clicks=3, interval=0.05)
            return {"success": True, "action": "triple_click", "x": x, "y": y}
        except Exception as e:
            return {"error": str(e)}

    def hold_key(self, key: str, seconds: float = 1.0) -> Dict:
        """按住一个键一段时间再松开。

        ``finally`` 里一定要松:中途抛异常却不松开,那个键会一直是按下状态,
        之后每一次输入都带着它 —— 用起来像键盘坏了,而且看不出是这一步造成的。
        上限也必须有,一个卡住的 hold 会污染后面所有输入。
        """
        err = self.check()
        if err:
            return err
        seconds = max(0.0, min(float(seconds), HOLD_KEY_MAX_SECONDS))
        try:
            pyautogui.keyDown(key)
            try:
                time.sleep(seconds)
            finally:
                pyautogui.keyUp(key)
            return {"success": True, "action": "hold_key", "key": key, "seconds": seconds}
        except Exception as e:
            return {"error": str(e)}

    def mouse_down(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> Dict:
        """按下不放。与 mouse_up 配对,做框选一类 drag 表达不了的动作。"""
        err = self.check()
        if err:
            return err
        try:
            if x is not None and y is not None:
                pyautogui.moveTo(x, y)
            pyautogui.mouseDown(button=button)
            return {"success": True, "action": "mouse_down", "button": button}
        except Exception as e:
            return {"error": str(e)}

    def mouse_up(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> Dict:
        err = self.check()
        if err:
            return err
        try:
            if x is not None and y is not None:
                pyautogui.moveTo(x, y)
            pyautogui.mouseUp(button=button)
            return {"success": True, "action": "mouse_up", "button": button}
        except Exception as e:
            return {"error": str(e)}

    def zoom(self, region: Optional[List[int]] = None) -> Dict:
        """屏幕上某一块的放大图(base64 PNG)。

        模型看整屏时小字常认不出来,zoom 是它自己要求"把这块放大给我看"。
        所以这里**不动界面**,只返回图 —— 它是一次观察,不是一次操作。
        """
        err = self.check()
        if err:
            return err
        box = list(region or [])
        if len(box) != 4:
            return {"error": "region 必须是 [x0, y0, x1, y1] 四个整数"}
        x0, y0, x1, y1 = (int(v) for v in box)
        if x1 <= x0 or y1 <= y0:
            return {"error": f"region 不是一个有面积的矩形: {box}"}
        try:
            import base64 as _b64
            import io as _io

            img = pyautogui.screenshot(region=(x0, y0, x1 - x0, y1 - y0))
            buf = _io.BytesIO()
            img.save(buf, format="PNG")
            return {
                "success": True,
                "action": "zoom",
                "region": [x0, y0, x1, y1],
                "width": img.width,
                "height": img.height,
                "image_b64": _b64.b64encode(buf.getvalue()).decode(),
            }
        except Exception as e:
            return {"error": str(e)}

    def screenshot(self, save_path: Optional[str] = None) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            img = pyautogui.screenshot()
            if save_path:
                img.save(save_path)
                return {
                    "success": True,
                    "action": "screenshot",
                    "path": save_path,
                    "width": img.width,
                    "height": img.height,
                }
            else:
                buffer = BytesIO()
                img.save(buffer, format="PNG")
                img_base64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
                return {
                    "success": True,
                    "action": "screenshot",
                    "width": img.width,
                    "height": img.height,
                    "image_base64": img_base64,
                }
        except Exception as e:
            return {"error": str(e)}

    def get_mouse_position(self) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            pos = pyautogui.position()
            return {"success": True, "x": pos.x, "y": pos.y}
        except Exception as e:
            return {"error": str(e)}

    def get_screen_size(self) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            size = pyautogui.size()
            return {"success": True, "width": size.width, "height": size.height}
        except Exception as e:
            return {"error": str(e)}

    def list_windows(self) -> Dict:
        if not IS_WINDOWS or not pygetwindow:
            return {"error": "pygetwindow not available"}
        try:
            windows = pygetwindow.getAllWindows()
            result = [
                {
                    "title": w.title,
                    "left": w.left,
                    "top": w.top,
                    "width": w.width,
                    "height": w.height,
                    "visible": w.visible,
                    "minimized": w.isMinimized,
                    "maximized": w.isMaximized,
                }
                for w in windows
                if w.title
            ]
            return {"success": True, "windows": result}
        except Exception as e:
            return {"error": str(e)}

    def window_action(self, title: str, action: str) -> Dict:
        if not IS_WINDOWS or not pygetwindow:
            return {"error": "pygetwindow not available"}
        try:
            windows = pygetwindow.getWindowsWithTitle(title)
            if not windows:
                return {"error": f"Window not found: {title}"}
            w = windows[0]
            if action == "focus":
                w.activate()
            elif action == "minimize":
                w.minimize()
            elif action == "maximize":
                w.maximize()
            elif action == "restore":
                w.restore()
            elif action == "close":
                w.close()
            else:
                return {"error": f"Unknown action: {action}"}
            return {"success": True, "action": action, "title": title}
        except Exception as e:
            return {"error": str(e)}

    def locate_on_screen(self, image_path: str, confidence: float = 0.9) -> Dict:
        err = self.check()
        if err:
            return err
        try:
            location = pyautogui.locateOnScreen(image_path, confidence=confidence)
            if location:
                center = pyautogui.center(location)
                return {
                    "success": True,
                    "found": True,
                    "x": center.x,
                    "y": center.y,
                    "left": location.left,
                    "top": location.top,
                    "width": location.width,
                    "height": location.height,
                }
            return {"success": True, "found": False}
        except Exception as e:
            return {"error": str(e)}

    def get_tools(self):
        return [
            {
                "name": "click",
                "description": "点击指定位置",
                "parameters": {"x": "X坐标", "y": "Y坐标", "button": "按钮(left/right/middle)", "clicks": "点击次数"},
            },
            {"name": "double_click", "description": "双击", "parameters": {"x": "X坐标", "y": "Y坐标"}},
            {"name": "right_click", "description": "右键点击", "parameters": {"x": "X坐标", "y": "Y坐标"}},
            {"name": "type_text", "description": "输入文本", "parameters": {"text": "文本内容"}},
            {"name": "press_key", "description": "按键", "parameters": {"key": "按键名称"}},
            {"name": "hotkey", "description": "组合键", "parameters": {"keys": "按键列表"}},
            {"name": "move_mouse", "description": "移动鼠标", "parameters": {"x": "X坐标", "y": "Y坐标"}},
            {
                "name": "drag",
                "description": "拖拽",
                "parameters": {"start_x": "起始X", "start_y": "起始Y", "end_x": "结束X", "end_y": "结束Y"},
            },
            {"name": "scroll", "description": "滚动", "parameters": {"clicks": "滚动量"}},
            {"name": "screenshot", "description": "截图", "parameters": {}},
            {"name": "get_mouse_position", "description": "获取鼠标位置", "parameters": {}},
            {"name": "get_screen_size", "description": "获取屏幕尺寸", "parameters": {}},
            {"name": "list_windows", "description": "列出窗口", "parameters": {}},
            {
                "name": "window_action",
                "description": "窗口操作",
                "parameters": {"title": "窗口标题", "action": "操作(focus/minimize/maximize/close)"},
            },
            {
                "name": "locate_on_screen",
                "description": "定位图像",
                "parameters": {"image_path": "图像路径", "confidence": "置信度"},
            },
        ]

    async def call_tool(self, tool: str, params: dict):
        if tool == "click":
            return self.click(
                params.get("x", 0), params.get("y", 0), params.get("button", "left"), params.get("clicks", 1)
            )
        elif tool == "double_click":
            return self.double_click(params.get("x", 0), params.get("y", 0))
        elif tool == "right_click":
            return self.right_click(params.get("x", 0), params.get("y", 0))
        elif tool == "type_text":
            return self.type_text(params.get("text", ""), params.get("interval", 0.05))
        elif tool == "press_key":
            return self.press_key(params.get("key", "enter"))
        elif tool == "hotkey":
            return self.hotkey(params.get("keys", []))
        elif tool == "move_mouse":
            return self.move_mouse(params.get("x", 0), params.get("y", 0), params.get("duration", 0.5))
        elif tool == "drag":
            return self.drag(
                params.get("start_x", 0),
                params.get("start_y", 0),
                params.get("end_x", 0),
                params.get("end_y", 0),
                params.get("duration", 0.5),
            )
        elif tool == "scroll":
            return self.scroll(params.get("clicks", 0), params.get("x"), params.get("y"))
        elif tool == "screenshot":
            return self.screenshot(params.get("save_path"))
        elif tool == "middle_click":
            return self.middle_click(params.get("x", 0), params.get("y", 0))
        elif tool == "triple_click":
            return self.triple_click(params.get("x", 0), params.get("y", 0))
        elif tool == "hold_key":
            return self.hold_key(params.get("key", ""), params.get("seconds", 1.0))
        elif tool == "mouse_down":
            return self.mouse_down(params.get("x"), params.get("y"), params.get("button", "left"))
        elif tool == "mouse_up":
            return self.mouse_up(params.get("x"), params.get("y"), params.get("button", "left"))
        elif tool == "zoom":
            return self.zoom(params.get("region"))
        elif tool == "get_mouse_position":
            return self.get_mouse_position()
        elif tool == "get_screen_size":
            return self.get_screen_size()
        elif tool == "list_windows":
            return self.list_windows()
        elif tool == "window_action":
            return self.window_action(params.get("title", ""), params.get("action", "focus"))
        elif tool == "locate_on_screen":
            return self.locate_on_screen(params.get("image_path", ""), params.get("confidence", 0.9))
        return {"error": f"Unknown tool: {tool}"}


tools = UIATools()


# ============ API 端点 ============
@app.get("/health")
async def health():
    return {
        "status": "healthy" if tools.initialized else "degraded",
        "node_id": "36",
        "name": "UIAWindows",
        "platform": sys.platform,
        "pyautogui_available": pyautogui is not None,
        "pygetwindow_available": pygetwindow is not None,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/tools")
async def list_tools():
    return {"tools": tools.get_tools()}


@app.post("/click")
async def api_click(request: ClickRequest):
    result = tools.click(request.x, request.y, request.button, request.clicks)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/type")
async def api_type(request: TypeRequest):
    result = tools.type_text(request.text, request.interval)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/hotkey")
async def api_hotkey(request: HotkeyRequest):
    result = tools.hotkey(request.keys)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/move")
async def api_move(request: MoveRequest):
    result = tools.move_mouse(request.x, request.y, request.duration)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/drag")
async def api_drag(request: DragRequest):
    result = tools.drag(request.start_x, request.start_y, request.end_x, request.end_y, request.duration)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/screenshot")
async def api_screenshot():
    result = tools.screenshot()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/mouse_position")
async def api_mouse_position():
    result = tools.get_mouse_position()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/screen_size")
async def api_screen_size():
    result = tools.get_screen_size()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/windows")
async def api_list_windows():
    result = tools.list_windows()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/window")
async def api_window(request: WindowRequest):
    result = tools.window_action(request.title, request.action)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/mcp/call")
async def mcp_call(request: dict):
    try:
        result = await tools.call_tool(request.get("tool"), request.get("params", {}))
        return {"success": True, "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8036)
