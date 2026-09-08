"""
Node 45: DesktopAuto - 跨平台桌面自动化
"""

import asyncio
import base64
import logging
import os
import sys
import time
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from nodes.common.cors_config import get_cors_origins

app = FastAPI(title="Node 45 - DesktopAuto", version="2.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

logger = logging.getLogger("Galaxy.Node45.DesktopAuto")


def _safe_error(action: str, exc: Exception) -> dict:
    """异常 → 给调用方的错误。**完整细节只进日志,不出网。**

    这个节点的每个端点都是 HTTP 接口,``str(e)`` 直接回给调用方等于把内部路径、
    库版本、有时甚至栈信息一起送出去(CodeQL 的 py/stack-trace-exposure)。

    但也不能只回一句"失败了" —— computer use 闭环靠这句话决定下一步怎么走,
    含糊的错误会让模型原样重试一遍。所以折中:**带上异常类名**(``ValueError``
    跟 ``OSError`` 指向的下一步完全不同),内容留在日志里。

    这是本文件里同一类问题的**第三轮**。前两轮是逐个端点单独修的,修一个漏一堆;
    这次收成一处,新加端点直接用它,不必每次重新想一遍该怎么措辞。
    """
    logger.exception("[%s] 执行失败", action)
    return {"success": False, "error": f"{action} 执行失败: {type(exc).__name__}(详情见节点日志)"}


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


class DragRequest(BaseModel):
    """按下 → 移动 → 松开。GUI-VLA 类模型的动作空间里 drag 是独立一等动作
    (拖文件、拖滑块、框选),用 move + click 拼不出来 —— 中间的按住状态没有。"""

    from_x: int
    from_y: int
    to_x: int
    to_y: int
    duration: float = 0.5
    button: str = "left"


class WaitRequest(BaseModel):
    """等界面自己变(加载/动画/弹窗)。

    没有它,模型只能靠连发无意义动作来"拖时间",那会真的点到东西。
    """

    seconds: float = 1.0


class LaunchAppRequest(BaseModel):
    """按名字或路径拉起一个程序。"""

    target: str


class OpenUrlRequest(BaseModel):
    """用系统默认浏览器打开一个 URL。"""

    url: str


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
        return _safe_error("click", e)


@app.post("/double_click")
async def double_click(x: int, y: int):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.doubleClick(x=x, y=y)
        return {"success": True, "x": x, "y": y}
    except Exception as e:
        return _safe_error("double_click", e)


@app.post("/type")
async def type_text(request: TypeRequest):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.write(request.text, interval=request.interval)
        return {"success": True, "typed": len(request.text)}
    except Exception as e:
        return _safe_error("type_text", e)


@app.post("/hotkey")
async def press_hotkey(request: KeyRequest):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        keys = request.keys.split("+")
        pyautogui.hotkey(*keys)
        return {"success": True, "keys": keys}
    except Exception as e:
        return _safe_error("press_hotkey", e)


@app.post("/press")
async def press_key(key: str):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.press(key)
        return {"success": True, "key": key}
    except Exception as e:
        return _safe_error("press_key", e)


@app.post("/move")
async def move_mouse(request: MoveRequest):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.moveTo(request.x, request.y, duration=request.duration)
        return {"success": True, "x": request.x, "y": request.y}
    except Exception as e:
        return _safe_error("move_mouse", e)


@app.post("/scroll")
async def scroll(amount: int, x: Optional[int] = None, y: Optional[int] = None):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.scroll(amount, x=x, y=y)
        return {"success": True, "amount": amount}
    except Exception as e:
        return _safe_error("scroll", e)


@app.post("/drag")
async def drag(request: DragRequest):
    """拖拽:按下 → 移动 → 松开。"""
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.moveTo(request.from_x, request.from_y)
        pyautogui.dragTo(
            request.to_x,
            request.to_y,
            duration=request.duration,
            button=request.button,
        )
        return {
            "success": True,
            "from": {"x": request.from_x, "y": request.from_y},
            "to": {"x": request.to_x, "y": request.to_y},
        }
    except Exception as e:
        return _safe_error("drag", e)


@app.post("/wait")
async def wait(request: WaitRequest):
    """等待界面自己变化。

    这一个**不需要 pyautogui** —— 等待跟有没有桌面无关。无头机器上其余动作都
    降级了,它照样该能用:模型的一串动作里夹着 wait,不该因为这一步"不可用"
    而整条中断。
    """
    import asyncio as _asyncio

    # 给上限:模型给出一个离谱的秒数时,不该把这条 HTTP 请求挂死。
    seconds = max(0.0, min(float(request.seconds), 60.0))
    await _asyncio.sleep(seconds)
    return {"success": True, "waited_seconds": seconds, "requested_seconds": request.seconds}


#: 允许启动哪些程序 —— 由**部署方**在环境变量里声明,逗号分隔。
#:
#: 例:``GALAXY_LAUNCH_APP_ALLOWLIST=notepad,chrome,code``
#:
#: 不设 = 这个端点整个关着。这是**默认安全**,不是不方便:见下面 why。
_LAUNCH_ALLOWLIST_ENV = "GALAXY_LAUNCH_APP_ALLOWLIST"


def _launch_allowlist() -> "List[str]":
    """读允许清单。每次现读 —— 改了配置不必重启才生效。"""
    import os as _os

    raw = _os.environ.get(_LAUNCH_ALLOWLIST_ENV, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _resolve_launch_target(target: str) -> "tuple[Optional[str], str]":
    """把 target 解析成一个**允许启动的**可执行文件路径。

    返回 ``(路径, 出错原因)``;不允许或找不到就 ``(None, 原因)``。

    这里改过两版,两版都不够,记下来免得再走回头路:

    **第一版**(Windows 分支)::

        subprocess.Popen(["cmd", "/c", "start", "", target], shell=False)

    ``shell=False`` 是障眼法 —— cmd.exe 自己就是 shell,``/c`` 后面由它解析。
    ``target`` 来自 HTTP 请求体,``foo & calc`` 就是任意命令执行
    (CodeQL py/command-line-injection,critical)。

    **第二版**:去掉 shell、过滤 shell 元字符、先把名字解析成真实文件再用 argv 启动。
    挡住了命令**拼接**,但没挡住命令**本身** —— ``os.path.isfile(target)`` 放行任意
    绝对路径,``shutil.which(target)`` 放行 PATH 里的任意程序(``sh`` / ``python`` /
    ``curl`` 都在里面)。**还是远程任意代码执行**,只是要求那个文件已经存在。
    CodeQL 第二轮照旧报 critical,而且多报了一条 path-injection —— 它是对的。

    **想明白的事**:"按名字启动任意程序"作为一个 HTTP 端点,本质上不是过滤字符能
    解决的,只能靠**授权**。所以:

    1. **默认整个关着**。不设 :data:`_LAUNCH_ALLOWLIST_ENV` 就一律拒绝;
    2. 开启时,调用方给的字符串只用来**在清单里查表**;
    3. 命中之后,拿去解析和启动的是**清单里的那一项**(部署方写的),
       不是调用方给的字符串 —— 用户输入到此为止,不进 path、不进命令行。

    与刚从 ``device_control_service`` 删掉的那张 app_paths 表**不是一回事**:
    那张表是代码里写死"微信 → C:\\Program Files\\..."的**猜测**,只对某一台机器
    成立、必然过时;这张清单是部署方对自己机器做的**授权声明**,由知情者决定。
    """
    import os as _os
    import shutil as _shutil

    allowlist = _launch_allowlist()
    if not allowlist:
        return None, (
            f"启动程序的能力默认是关着的。要开:设 {_LAUNCH_ALLOWLIST_ENV}=<允许的程序名,逗号分隔>。"
            "这是个能在本机起进程的接口,不做白名单就等于把机器交出去。"
        )

    if not target:
        return None, "target 不能为空"

    # **精确**匹配,不做前缀/包含 —— 那两种都能被绕。
    if target not in allowlist:
        return None, "这个程序不在允许清单里"

    # 关键:下面用的是 allowlist 里的那一项(部署方写的),不是调用方传来的字符串。
    approved = allowlist[allowlist.index(target)]

    if _os.path.isabs(approved) and _os.path.isfile(approved):
        return _os.path.abspath(approved), ""
    found = _shutil.which(approved)
    if found:
        return _os.path.abspath(found), ""
    return None, "清单里有这一项,但这台机器上找不到它;请在清单里写完整路径"


@app.post("/launch_app")
async def launch_app(request: LaunchAppRequest):
    """拉起一个程序 —— **需要部署方显式授权**。

    刻意不在代码里放"应用名 → 绝对路径"的字典(那种表只对写它的那台机器成立)。
    允许启动什么由 :data:`_LAUNCH_ALLOWLIST_ENV` 声明,默认什么都不许。
    安全立场与两版历史见 :func:`_resolve_launch_target`。
    """
    import subprocess

    target = (request.target or "").strip()
    resolved, why = _resolve_launch_target(target)
    if resolved is None:
        return {"success": False, "error": why}

    try:
        # argv 数组 + 无 shell + 路径来自允许清单:三重都占住。
        subprocess.Popen([resolved])  # noqa: S603
        return {"success": True, "target": target, "resolved": resolved}
    except Exception as e:
        # 异常详情只进日志(CodeQL py/stack-trace-exposure)。
        logger.warning("launch_app 启动失败 target=%r resolved=%r: %s", target, resolved, e)
        return {"success": False, "error": "启动失败,详情见服务端日志"}


@app.post("/open_url")
async def open_url(request: OpenUrlRequest):
    """用系统默认浏览器打开 URL。"""
    import webbrowser

    url = (request.url or "").strip()
    # 只放行 http/https:webbrowser 会把 file:// 之类也照开,那是本地文件读取面。
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"success": False, "error": "只接受 http:// 或 https:// 开头的地址"}
    try:
        opened = webbrowser.open(url)
        # webbrowser.open 返回 False 表示**没有可用浏览器**(无头机器上常见)。
        # 这里必须如实回 False,不能一律报成功 —— 那就是"看起来打开了,其实没有"。
        return {"success": bool(opened), "url": url, "error": "" if opened else "这台机器上没有可用的浏览器"}
    except Exception as e:
        logger.warning("open_url 失败 url=%r: %s", url, e)
        return {"success": False, "error": "打开失败,详情见服务端日志"}


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
        return _safe_error("take_screenshot", e)


@app.get("/position")
async def get_position():
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        x, y = pyautogui.position()
        return {"success": True, "x": x, "y": y}
    except Exception as e:
        return _safe_error("get_position", e)


@app.get("/screen_size")
async def get_screen_size():
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        width, height = pyautogui.size()
        return {"success": True, "width": width, "height": height}
    except Exception as e:
        return _safe_error("get_screen_size", e)


@app.post("/middle_click")
async def middle_click(request: ClickRequest):
    """中键点击。厂商动作集里一直有,本仓此前没有 —— 补上。"""
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.click(x=request.x, y=request.y, button="middle")
        return {"success": True, "x": request.x, "y": request.y}
    except Exception as e:
        return _safe_error("middle_click", e)


@app.post("/triple_click")
async def triple_click(request: ClickRequest):
    """三击 —— 选中整行/整段,靠连点两次代替不了(间隔一长就变成两次双击)。"""
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        pyautogui.click(x=request.x, y=request.y, clicks=3, interval=0.05)
        return {"success": True, "x": request.x, "y": request.y, "clicks": 3}
    except Exception as e:
        return _safe_error("triple_click", e)


class HoldKeyRequest(BaseModel):
    key: str
    seconds: float = 1.0


#: 按住一个键最多多久。上游给到 300 秒,这里按本机风险收紧 ——
#: 一个卡住的 hold 会让后续每一次输入都带着那个修饰键,表现是"键盘坏了"。
HOLD_KEY_MAX_SECONDS = 30.0


@app.post("/hold_key")
async def hold_key(request: HoldKeyRequest):
    """按住某个键一段时间再松开。

    ``finally`` 里一定要松:中途抛异常却不松开,那个键会一直是按下状态,
    之后每一次输入都带着它 —— 用起来像键盘坏了,而且看不出是这一步造成的。
    """
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    seconds = max(0.0, min(float(request.seconds), HOLD_KEY_MAX_SECONDS))
    try:
        pyautogui.keyDown(request.key)
        try:
            await asyncio.sleep(seconds)
        finally:
            pyautogui.keyUp(request.key)
        return {"success": True, "key": request.key, "seconds": seconds}
    except Exception as e:
        return _safe_error("hold_key", e)


class MouseButtonRequest(BaseModel):
    x: Optional[int] = None
    y: Optional[int] = None
    button: str = "left"


@app.post("/mouse_down")
async def mouse_down(request: MouseButtonRequest):
    """按下不放。与 mouse_up 配对,用来做框选一类 drag 表达不了的动作。"""
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        if request.x is not None and request.y is not None:
            pyautogui.moveTo(request.x, request.y)
        pyautogui.mouseDown(button=request.button)
        return {"success": True, "button": request.button}
    except Exception as e:
        return _safe_error("mouse_down", e)


@app.post("/mouse_up")
async def mouse_up(request: MouseButtonRequest):
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    try:
        if request.x is not None and request.y is not None:
            pyautogui.moveTo(request.x, request.y)
        pyautogui.mouseUp(button=request.button)
        return {"success": True, "button": request.button}
    except Exception as e:
        return _safe_error("mouse_up", e)


class ZoomRequest(BaseModel):
    region: List[int]  # [x0, y0, x1, y1]


@app.post("/zoom")
async def zoom(request: ZoomRequest):
    """截屏中某一块的放大图,base64 PNG 返回。

    模型看整屏时小字常常认不出来,zoom 是它自己要求"把这块放大给我看"。
    所以这里**不动界面**,只返回图 —— 它是一次观察,不是一次操作。
    """
    if not pyautogui:
        return {"success": False, "error": pyautogui_unavailable_reason or REASON_BROKEN}

    region = list(request.region or [])
    if len(region) != 4:
        return {"success": False, "error": "region 必须是 [x0, y0, x1, y1] 四个整数"}
    x0, y0, x1, y1 = (int(v) for v in region)
    if x1 <= x0 or y1 <= y0:
        return {"success": False, "error": f"region 不是一个有面积的矩形: {region}"}

    try:
        import io as _io

        shot = pyautogui.screenshot(region=(x0, y0, x1 - x0, y1 - y0))
        buf = _io.BytesIO()
        shot.save(buf, format="PNG")
        return {
            "success": True,
            "region": [x0, y0, x1, y1],
            "width": shot.width,
            "height": shot.height,
            "image_b64": base64.b64encode(buf.getvalue()).decode(),
        }
    except Exception as e:
        return _safe_error("zoom", e)


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
        return _safe_error("locate_on_screen", e)


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
    elif tool == "middle_click":
        return await middle_click(ClickRequest(**params))
    elif tool == "triple_click":
        return await triple_click(ClickRequest(**params))
    elif tool == "hold_key":
        return await hold_key(HoldKeyRequest(**params))
    elif tool == "mouse_down":
        return await mouse_down(MouseButtonRequest(**params))
    elif tool == "mouse_up":
        return await mouse_up(MouseButtonRequest(**params))
    elif tool == "zoom":
        return await zoom(ZoomRequest(**params))
    elif tool == "locate":
        return await locate_on_screen(LocateRequest(**params))
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8045)
