"""
Node 45: DesktopAuto - 跨平台桌面自动化
"""

import base64
import logging
import os
import sys
import time
from datetime import datetime
from typing import Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from nodes.common.cors_config import get_cors_origins

app = FastAPI(title="Node 45 - DesktopAuto", version="2.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

logger = logging.getLogger("Galaxy.Node45.DesktopAuto")

pyautogui = None

#: 三种"用不了"各自的**常量**说法。
#:
#: 为什么必须是常量:这几句会原样进 HTTP 响应体。一旦把异常文本(哪怕只是
#: ``f"{type(e).__name__}: {e}"``)拼进去,就是 CodeQL 那条
#: py/stack-trace-exposure —— 服务端内部信息经异常泄露给外部调用方。
#: 本文件此前正是这么写的,11 个端点全中。
#:
#: 详情不是不要,是**只进日志**(见 pyautogui_unavailable_detail),与
#: core/routes/c_stage.py 里那处同一个处理法:对外一句固定的话,对内留全。
REASON_NOT_INSTALLED = "pyautogui 没装,桌面自动化用不了。装法: pip install pyautogui"
REASON_HEADLESS = "pyautogui 装了,但这台机器没有桌面(无 DISPLAY),桌面自动化用不了"
REASON_BROKEN = "pyautogui 装了,但在这台机器上起不来,桌面自动化用不了(详情见服务端日志)"

#: 给调用方看的那一句(常量之一)。空 = 能用。
pyautogui_unavailable_reason = ""
#: 给排障看的那一句,带异常类型与消息。**不许进响应**,只进日志。
pyautogui_unavailable_detail = ""

try:
    import pyautogui as _pyautogui

    _pyautogui.FAILSAFE = True
    _pyautogui.PAUSE = 0.1
    pyautogui = _pyautogui
except ImportError as _exc:
    pyautogui_unavailable_reason = REASON_NOT_INSTALLED
    pyautogui_unavailable_detail = f"ImportError: {_exc}"
    logger.warning("%s(%s)", pyautogui_unavailable_reason, pyautogui_unavailable_detail)
except Exception as _exc:  # noqa: BLE001
    # 只 except ImportError 是不够的:**装了但没有桌面**时,pyautogui 在 import 期就
    # 去连 X11,抛的是 `KeyError: 'DISPLAY'` —— 不是 ImportError,于是它会穿透出去
    # 把整个节点的导入带崩。真跑实测:装上 pyautogui 之后,`python main.py --check-only`
    # 的节点导入检查从 125/125 掉到 124/125,报 `Node_45_DesktopAuto KeyError: 'DISPLAY'`。
    # 无头机器上这属正常,该降级,不该崩。
    _headless = isinstance(_exc, KeyError) and "DISPLAY" in str(_exc)
    pyautogui_unavailable_reason = REASON_HEADLESS if _headless else REASON_BROKEN
    pyautogui_unavailable_detail = f"{type(_exc).__name__}: {_exc}"
    logger.warning("%s(%s)", pyautogui_unavailable_reason, pyautogui_unavailable_detail)


class ClickRequest(BaseModel):
    x: int
    y: int
    clicks: int = 1
    button: str = "left"


class TypeRequest(BaseModel):
    text: str
    interval: float = 0.05


class KeyRequest(BaseModel):
    keys: str


class MoveRequest(BaseModel):
    x: int
    y: int
    duration: float = 0.5


class LocateRequest(BaseModel):
    image_path: str
    confidence: float = 0.9


@app.get("/health")
async def health():
    return {
        "status": "healthy" if pyautogui else "degraded",
        "node_id": "45",
        "name": "DesktopAuto",
        "pyautogui_available": pyautogui is not None,
        "platform": sys.platform,
        "timestamp": datetime.now().isoformat(),
    }


@app.post("/click")
async def click(request: ClickRequest):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.click(x=request.x, y=request.y, clicks=request.clicks, button=request.button)
        return {"success": True, "x": request.x, "y": request.y, "clicks": request.clicks}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/double_click")
async def double_click(x: int, y: int):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.doubleClick(x=x, y=y)
        return {"success": True, "x": x, "y": y}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/type")
async def type_text(request: TypeRequest):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.write(request.text, interval=request.interval)
        return {"success": True, "typed": len(request.text)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/hotkey")
async def press_hotkey(request: KeyRequest):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        keys = request.keys.split("+")
        pyautogui.hotkey(*keys)
        return {"success": True, "keys": keys}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/press")
async def press_key(key: str):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.press(key)
        return {"success": True, "key": key}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/move")
async def move_mouse(request: MoveRequest):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.moveTo(request.x, request.y, duration=request.duration)
        return {"success": True, "x": request.x, "y": request.y}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/scroll")
async def scroll(amount: int, x: Optional[int] = None, y: Optional[int] = None):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.scroll(amount, x=x, y=y)
        return {"success": True, "amount": amount}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/screenshot")
async def take_screenshot():
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        import io

        screenshot = pyautogui.screenshot()
        buffer = io.BytesIO()
        screenshot.save(buffer, format="PNG")
        img_base64 = base64.b64encode(buffer.getvalue()).decode()
        return {"success": True, "image": img_base64, "width": screenshot.width, "height": screenshot.height}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/position")
async def get_position():
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        x, y = pyautogui.position()
        return {"success": True, "x": x, "y": y}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/screen_size")
async def get_screen_size():
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        width, height = pyautogui.size()
        return {"success": True, "width": width, "height": height}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/locate")
async def locate_on_screen(request: LocateRequest):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        location = pyautogui.locateOnScreen(request.image_path, confidence=request.confidence)
        if location:
            center = pyautogui.center(location)
            return {
                "success": True,
                "found": True,
                "x": center.x,
                "y": center.y,
                "region": {
                    "left": location.left,
                    "top": location.top,
                    "width": location.width,
                    "height": location.height,
                },
            }
        return {"success": True, "found": False}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    if tool == "click":
        return await click(ClickRequest(**params))
    elif tool == "double_click":
        return await double_click(params.get("x", 0), params.get("y", 0))
    elif tool == "type":
        return await type_text(TypeRequest(**params))
    elif tool == "hotkey":
        return await press_hotkey(KeyRequest(**params))
    elif tool == "press":
        return await press_key(params.get("key", ""))
    elif tool == "move":
        return await move_mouse(MoveRequest(**params))
    elif tool == "scroll":
        return await scroll(params.get("amount", 0), params.get("x"), params.get("y"))
    elif tool == "screenshot":
        return await take_screenshot()
    elif tool == "position":
        return await get_position()
    elif tool == "screen_size":
        return await get_screen_size()
    elif tool == "locate":
        return await locate_on_screen(LocateRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8045)
