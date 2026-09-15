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

from nodes.common.node_auth import install_node_auth

app = FastAPI(title="Node 36 - UIAWindows", version="2.0.0")
app.add_middleware(
    CORSMiddleware, allow_origins=get_cors_origins(), allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# HTTP 面的身份认证。权限闸回答"这个动作允许吗",这一层回答"调用方是谁"——
# 此前这个节点两个问题都没有答案。实现在 nodes.common.node_auth,
# 判定复用 core.auth(网关与 launcher 早就在用的那一套)。
install_node_auth(app, "Node_36_UIAWindows")

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

    @staticmethod
    def _desktop_uia():
        """拿到只读采集模块。

        相对导入在 `fusion_entry` 那条路上解析不了:它用
        `spec_from_file_location("Node_36_UIAWindows.main", ...)` 加载本文件,于是
        `__package__` 是 "Node_36_UIAWindows",但那个包并不在 sys.modules 里 ——
        `from .desktop_uia import` 会抛 `No module named 'Node_36_UIAWindows'`。

        本节点里 ui_tree.py / ufo_deep_integration.py 早就是这个写法(try 相对、
        except 退绝对)。这里照做,并且只写一处,别让三个方法各自 try 一遍。
        """
        try:
            from . import desktop_uia  # type: ignore[import-not-found]
        except ImportError:
            import desktop_uia  # type: ignore[import-not-found,no-redef]
        return desktop_uia

    # ── 结构化读取(委托给 desktop_uia,不在这里再写一份)────────────────────
    #
    # 这三个动作在 config/node_catalog.json 里**早就声明**给 Node 36 了,但 main.py
    # 一个都没实现 —— 权限白名单声明了节点没有的能力。后果不是报错,是更糟的一种:
    # 走 invoke_node 时权限闸放行,然后撞上 "Unknown tool"。读 manifest 的人会以为
    # 这个节点是 UIA-first 的,而它的动作面全是坐标。
    #
    # 实现放在 nodes.Node_36_UIAWindows.desktop_uia(只读、可接线、有 15 条测试),
    # 这里只做转发。两份实现必然会漂,而漂的时候现场看不出是哪一份抓的树。

    def get_ui_tree(self, window_title: Optional[str] = None, max_depth: int = 40) -> Dict:
        return self._desktop_uia().get_ui_tree(window_title, max_depth)

    def find_element(self, selector: Dict[str, Any]) -> Dict:
        hit = self._desktop_uia().find_element(selector or {})
        return {"success": hit is not None, "element": hit}

    def find_elements(self, selector: Dict[str, Any]) -> Dict:
        hits = self._desktop_uia().find_elements(selector or {})
        return {"success": True, "elements": hits, "count": len(hits)}

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
        # manifest 把这五个声明成了**顶层动作**,而实现是 window_action 的子动作。
        # 于是 invoke_node(action="focus") 过了权限闸却撞上 "Unknown tool" ——
        # 声明与实现对不上的典型后果。这里按 manifest 的形状补上转发。
        elif tool in ("focus", "minimize", "maximize", "restore", "close"):
            return self.window_action(params.get("title", ""), tool)
        elif tool == "get_ui_tree":
            return self.get_ui_tree(params.get("window_title"), params.get("max_depth", 40))
        elif tool == "find_element":
            return self.find_element(params.get("selector", {}))
        elif tool == "find_elements":
            return self.find_elements(params.get("selector", {}))
        elif tool == "locate_on_screen":
            return self.locate_on_screen(params.get("image_path", ""), params.get("confidence", 0.9))
        return {"error": f"Unknown tool: {tool}"}


tools = UIATools()


# ── 统一执行器入口 ────────────────────────────────────────────────────────────
#
# `core.node_invocation.invoke_node` 把动作名转发给节点的 `execute`
# (Golden Path 的 LocalNodeFacade 与 legacy 的 fusion_entry 最终都落到这里)。
# `fusion_entry.FusionNode.execute` 在实例上按顺序找 process / execute / run / handle,
# 一个都找不到就返回 `{"success": False, "error": "No executable method found"}`。
#
# 本节点的动作面叫 `call_tool`,这四个名字一个都没有 —— 于是
# `invoke_node("Node_36_UIAWindows", "click", ...)` **什么都执行不了**,而且报的是
# 一句泛化错误,看不出是接线断了还是动作不支持。实测:
#
#     execute('click') → {'success': False, 'error': 'No executable method found'}
#
# 这条路正是 `core/routes/ui_act.py` 结构化命中之后的派发目标。也就是说:读控件图、
# grounding 命中、算出坐标 —— 全做完了,最后一步掉在地上。
#
# 补这个转发函数把它接上。刻意放在 main.py 而不是 fusion_entry.py:后者头一行写着
# "由系统自动生成",改它会在下次生成时被覆盖。
async def execute(command: str, **params) -> Dict[str, Any]:
    """统一执行器入口:动作名 → `UIATools.call_tool`。"""
    return await tools.call_tool(command, params or {})


# ============ HTTP 动作权限闸 ============
#
# 这个节点有**两条**入口,而门禁此前只装在其中一条上:
#
#   1. 统一执行器 `core.node_invocation.invoke_node` → `execute()` → `call_tool`
#      —— 这条路上有三道门:治理资格门、动作权限门、HITL 审批。
#   2. 下面这些 FastAPI 路由 → 直接调 `tools.*`
#      —— **一道都没有**。
#
# 后果不是抽象的。`config/node_catalog.json` 里给 Node 36 声明的动作白名单,
# 是运维手上唯一能收紧这个节点的旋钮。今天把 `type_text` 从白名单里删掉:
# 统一执行器会拒绝,而 `POST /type` 照常打字。那个旋钮在这条路上是假的。
#
# 同理,往 `call_tool` 里新加一个动作却忘了写进 manifest(最初提的
# `run_powershell` 就是这个形状),统一执行器会拒,HTTP 会执行 —— manifest
# 门禁的腐烂正是这样开始的。
#
# ## 为什么这里 fail-closed,而 `node_invocation` 那边 fail-open
#
# `node_invocation` 在门禁自身抛异常时记一条 warning 然后放行。那在**那条路上**
# 是合理的:它前面还有治理门,后面还有 HITL 审批,权限门只是三层里的一层。
#
# 这条路上**一层都没有**。门禁拿不到就放行,等于这个补丁没打。所以这里相反:
# 拿不到门禁 → 503,不执行。
#
# 还有一个更隐蔽的坑:`_load_permissions()` 读不到目录时返回空表,于是
# `evaluate_action_permission` 把 Node 36 判成"未声明" → legacy **放行**。
# 但 Node 36 是**确定声明了**的(32 个动作)。所以判定回来说它没声明,
# 只可能是目录没读进来 —— 那是门禁坏了,不是 manifest 允许。这条路上按拒绝处理。
NODE_ID = "Node_36_UIAWindows"


def _require_action(action: str) -> None:
    """HTTP 路由的动作权限闸。不通过就抛 HTTPException,通过则静默返回。

    见上面那段注释:这里三种情况都拒 —— 门禁导入不了、判定说未声明、动作不在白名单。
    """
    try:
        from core.node_action_permissions import evaluate_action_permission
    except Exception as exc:  # noqa: BLE001 — 拿不到门禁就不执行,不是放行
        raise HTTPException(
            status_code=503,
            detail=f"action-permission gate unavailable; refusing to act: {exc}",
        ) from exc

    decision = evaluate_action_permission(NODE_ID, action)
    if not decision.declared:
        raise HTTPException(
            status_code=503,
            detail=(
                f"{NODE_ID} is known to declare its actions, but the gate reports it as "
                f"undeclared — the catalog failed to load. Refusing to act on action {action!r}."
            ),
        )
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail=f"action {action!r} denied by declared permission manifest: {decision.reason}",
        )


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
    _require_action("click")
    result = tools.click(request.x, request.y, request.button, request.clicks)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/type")
async def api_type(request: TypeRequest):
    _require_action("type_text")
    result = tools.type_text(request.text, request.interval)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/hotkey")
async def api_hotkey(request: HotkeyRequest):
    _require_action("hotkey")
    result = tools.hotkey(request.keys)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/move")
async def api_move(request: MoveRequest):
    _require_action("move_mouse")
    result = tools.move_mouse(request.x, request.y, request.duration)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/drag")
async def api_drag(request: DragRequest):
    _require_action("drag")
    result = tools.drag(request.start_x, request.start_y, request.end_x, request.end_y, request.duration)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/screenshot")
async def api_screenshot():
    _require_action("screenshot")
    result = tools.screenshot()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/mouse_position")
async def api_mouse_position():
    _require_action("get_mouse_position")
    result = tools.get_mouse_position()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/screen_size")
async def api_screen_size():
    _require_action("get_screen_size")
    result = tools.get_screen_size()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/windows")
async def api_list_windows():
    _require_action("list_windows")
    result = tools.list_windows()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/window")
async def api_window(request: WindowRequest):
    _require_action("window_action")
    result = tools.window_action(request.title, request.action)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/mcp/call")
async def mcp_call(request: dict):
    # 这条路由让调用方**指名**调用任意动作,是整个 HTTP 面上最需要门禁的一个。
    # 先过闸再进 call_tool:不能让"未声明的动作"先执行、再靠 call_tool 的
    # "Unknown tool" 兜底 —— 那个兜底保护的是拼错的名字,不是越权。
    tool = str(request.get("tool") or "")
    _require_action(tool)
    try:
        result = await tools.call_tool(tool, request.get("params", {}))
        return {"success": True, "result": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8036)
