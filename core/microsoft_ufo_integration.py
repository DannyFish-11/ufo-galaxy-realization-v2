# -*- coding: utf-8 -*-
"""
Galaxy - 微软 UFO 集成(旧接口)
================================

微软 UFO 现在是**桌面自动化整体**(:mod:`core.desktop_automation`)控件级的一个后端,不再自成一套。
本模块保留旧的类与方法名,供既有调用方(启动服务、``core.get_microsoft_ufo_integration``)用,
里面的每一个动作都交给那个整体去做(经 Windows 执行仲裁器,按现场挑方式):

* ``click`` / ``type_text`` / ``hotkey`` / ``find_and_click`` → 仲裁器(只走结构化三级,不进视觉级);
* ``execute_task``(一句自然语言的任务) → Computer Use 闭环,它是这一整体的「脑子」。

原先这里自己把 ``external/microsoft_ufo`` 塞进 ``sys.path``(那份源码不完整、导不进来),失败后又自己用
pyautogui 做一遍点击输入 —— 与坐标级重复的第二份。都去掉了:UFO 装没装、为什么用不了,由整体照实说
(:func:`core.desktop_automation.ufo_installed`)。
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# UI 元素和动作定义
# ============================================================================


class UIElementType(Enum):
    """UI 元素类型"""

    BUTTON = "button"
    TEXT_FIELD = "text_field"
    CHECKBOX = "checkbox"
    RADIO_BUTTON = "radio_button"
    DROPDOWN = "dropdown"
    LIST_ITEM = "list_item"
    MENU_ITEM = "menu_item"
    TAB = "tab"
    WINDOW = "window"
    DIALOG = "dialog"
    SCROLL_BAR = "scroll_bar"
    SLIDER = "slider"
    TREE_ITEM = "tree_item"
    TABLE_CELL = "table_cell"
    LINK = "link"
    IMAGE = "image"
    CUSTOM = "custom"


class UIAction(Enum):
    """UI 动作类型"""

    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    TYPE = "type"
    CLEAR = "clear"
    SELECT = "select"
    CHECK = "check"
    UNCHECK = "uncheck"
    SCROLL = "scroll"
    DRAG = "drag"
    DROP = "drop"
    HOVER = "hover"
    FOCUS = "focus"
    PRESS_KEY = "press_key"
    HOTKEY = "hotkey"
    WAIT = "wait"


@dataclass
class UIElement:
    """UI 元素数据类"""

    element_id: str
    element_type: UIElementType
    name: str
    text: str = ""
    bounds: Tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, width, height
    is_enabled: bool = True
    is_visible: bool = True
    is_focused: bool = False
    parent_id: Optional[str] = None
    children_ids: List[str] = None
    properties: Dict[str, Any] = None

    def __post_init__(self):
        if self.children_ids is None:
            self.children_ids = []
        if self.properties is None:
            self.properties = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "element_id": self.element_id,
            "element_type": self.element_type.value,
            "name": self.name,
            "text": self.text,
            "bounds": self.bounds,
            "is_enabled": self.is_enabled,
            "is_visible": self.is_visible,
            "is_focused": self.is_focused,
            "parent_id": self.parent_id,
            "children_ids": self.children_ids,
            "properties": self.properties,
        }


@dataclass
class UIActionResult:
    """UI 动作执行结果"""

    success: bool
    action: UIAction
    element_id: Optional[str] = None
    message: str = ""
    screenshot: Optional[str] = None  # Base64 编码的截图
    duration_ms: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "action": self.action.value,
            "element_id": self.element_id,
            "message": self.message,
            "screenshot": self.screenshot,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


# ============================================================================
# UI 自动化基类
# ============================================================================


class BaseUIAutomator(ABC):
    """UI 自动化基类"""

    def __init__(self):
        self.is_initialized = False
        self.current_window = None
        self.element_cache: Dict[str, UIElement] = {}

    @abstractmethod
    async def initialize(self) -> bool:
        """初始化自动化引擎"""

    @abstractmethod
    async def get_active_window(self) -> Optional[UIElement]:
        """获取当前活动窗口"""

    @abstractmethod
    async def find_element(self, selector: Dict[str, Any]) -> Optional[UIElement]:
        """查找 UI 元素"""

    @abstractmethod
    async def find_elements(self, selector: Dict[str, Any]) -> List[UIElement]:
        """查找多个 UI 元素"""

    @abstractmethod
    async def execute_action(
        self, action: UIAction, element_id: Optional[str], params: Dict[str, Any]
    ) -> UIActionResult:
        """执行 UI 动作"""

    @abstractmethod
    async def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Optional[str]:
        """截取屏幕"""

    @abstractmethod
    async def get_element_tree(self, root_id: Optional[str] = None) -> Dict[str, Any]:
        """获取 UI 元素树"""


# ============================================================================
# 微软 UFO 集成
# ============================================================================


def _import_pyautogui() -> Optional[Exception]:
    """在工作线程里 import pyautogui;成功返回 None,失败把异常交回来(三种状态由调用方分开说)。"""
    try:
        import pyautogui  # noqa: F401
    except Exception as exc:  # noqa: BLE001 — KeyError("DISPLAY") 之类也要原样交回
        return exc
    return None


class MicrosoftUFOAutomator(BaseUIAutomator):
    """旧接口:动作交给桌面自动化整体(微软 UFO 是其中控件级的一个后端)。"""

    def __init__(self):
        super().__init__()
        self.ufo_available = False
        self.ufo_unavailable_reason = ""

    async def initialize(self, process_name: str = "explorer.exe", app_root_name: str = "Desktop") -> bool:
        """说清这台机器上微软 UFO 与键鼠能不能用。``process_name`` / ``app_root_name`` 留给旧调用方,不再用。"""
        from core.desktop_automation import ufo_installed

        why = ufo_installed()
        self.ufo_available = not why
        self.ufo_unavailable_reason = why
        if why:
            logger.info("微软 UFO 没接进桌面自动化:%s", why)
        else:
            logger.info("微软 UFO 已作为控件级后端接进桌面自动化")
        gui_ok = await self._initialize_fallback()
        self.is_initialized = self.ufo_available or gui_ok
        return self.is_initialized

    async def _initialize_fallback(self) -> bool:
        """pyautogui 能不能用(坐标级的本进程后端)。

        这里必须把**三种状态分开**说,不能只有"装了/没装":

        1. 没装             → ImportError
        2. 装了但**没有桌面**  → 无头机器上 ``import pyautogui`` 抛的是
                              ``KeyError: 'DISPLAY'``(它 import 期就去连 X11),
                              **不是 ImportError**
        3. 好了

        原来只 ``except ImportError``,于是第 2 种会**穿透出去**:真跑实测,
        装上 pyautogui 之后无头机上这个 KeyError 直接从降级路径里逃出来 ——
        本该"可选功能不可用"的事变成异常上抛。更早的日志还会把第 2 种说成
        "pyautogui 未安装",而它明明装着 —— 说的和现实相反。
        """
        # import 期就去连 X11 / 装钩子,真跑实测要好几秒 —— 不在事件循环里做(曾卡住循环 6.9 秒)
        exc = await asyncio.to_thread(_import_pyautogui)
        if isinstance(exc, ImportError):
            # 可选依赖缺失属正常(非致命),降为 warning,别让新克隆启动刷红。
            logger.warning("pyautogui 没装,GUI 自动化回退用不了(可选功能,不影响启动)。装法: pip install pyautogui")
            return False
        if exc is not None:
            # 装了,但这台机器上用不起来(最常见:无头/没有 X11 DISPLAY)。
            # 照实说是哪一种,不要说成"没装"。
            _headless = isinstance(exc, KeyError) and "DISPLAY" in str(exc)
            logger.warning(
                "pyautogui 装了但在这台机器上起不来(%s),GUI 自动化回退不可用%s",
                f"{type(exc).__name__}: {exc}",
                "。这台机器没有桌面(无 DISPLAY),无头部署下属正常" if _headless else "",
            )
            return False

        self.is_initialized = True
        logger.info("Fallback to pyautogui")
        return True

    async def get_active_window(self) -> Optional[UIElement]:
        """获取当前活动窗口(pygetwindow)。"""
        try:
            import pygetwindow as gw

            active = gw.getActiveWindow()
            if active:
                return UIElement(
                    element_id=str(active._hWnd) if hasattr(active, "_hWnd") else "unknown",
                    element_type=UIElementType.WINDOW,
                    name=active.title,
                    bounds=(active.left, active.top, active.width, active.height),
                )
        except Exception as e:
            logger.error(f"get_active_window failed: {e}")

        return None

    async def find_element(self, selector: Dict[str, Any]) -> Optional[UIElement]:
        """不单独查找:按名字 / automation_id 的点击与输入直接用 ``find_and_click`` / ``find_and_type``,控件级会去找。"""
        return None

    async def find_elements(self, selector: Dict[str, Any]) -> List[UIElement]:
        return []

    async def execute_action(
        self, action: UIAction, element_id: Optional[str], params: Dict[str, Any]
    ) -> UIActionResult:
        """交给桌面自动化整体做(经仲裁器,只走结构化三级)。"""
        start_time = time.time()
        try:
            from core.windows_execution_arbiter import get_windows_arbiter

            res = await get_windows_arbiter().execute(
                action=action.value, params=dict(params or {}), device_id="local", structural_only=True
            )
        except Exception as e:  # noqa: BLE001
            return UIActionResult(
                success=False,
                action=action,
                element_id=element_id,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000),
            )
        detail = res.result or {}
        via = f"{res.final_level.value}/{detail.get('backend', '')}".rstrip("/")
        return UIActionResult(
            success=bool(res.success),
            action=action,
            element_id=element_id,
            message=f"桌面自动化:{via}",
            error=None if res.success else str(detail.get("error") or "桌面自动化各级都没做成"),
            duration_ms=int((time.time() - start_time) * 1000),
        )

    async def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Optional[str]:
        """截取屏幕"""
        try:
            import base64
            from io import BytesIO

            import pyautogui

            if region:
                screenshot = pyautogui.screenshot(region=region)
            else:
                screenshot = pyautogui.screenshot()

            buffer = BytesIO()
            screenshot.save(buffer, format="PNG")
            return base64.b64encode(buffer.getvalue()).decode("utf-8")

        except Exception as e:
            logger.error(f"Failed to capture screen: {e}")
            return None

    async def get_element_tree(self, root_id: Optional[str] = None) -> Dict[str, Any]:
        """控件树由桌面 UIA 采集(``nodes.Node_36_UIAWindows.desktop_uia``)提供,这里不另起一份。"""
        return {"error": "控件树请用 GET /api/v1/ui/perception 与桌面 UIA 采集"}


# ============================================================================
# Galaxy 集成服务
# ============================================================================


class GalaxyIntegrationService:
    """旧接口:点击 / 输入 / 快捷键交给桌面自动化整体;一句话的任务交给 Computer Use。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.automator: Optional[MicrosoftUFOAutomator] = None
        self._initialized = True

    async def initialize(self) -> bool:
        """初始化集成服务"""
        self.automator = MicrosoftUFOAutomator()
        return await self.automator.initialize()

    async def click(self, x: int, y: int) -> Dict[str, Any]:
        """点击指定位置"""
        if not self.automator:
            return {"error": "Automator not initialized"}

        result = await self.automator.execute_action(UIAction.CLICK, None, {"x": x, "y": y})
        return result.to_dict()

    async def type_text(self, text: str) -> Dict[str, Any]:
        """输入文本"""
        if not self.automator:
            return {"error": "Automator not initialized"}

        result = await self.automator.execute_action(UIAction.TYPE, None, {"text": text})
        return result.to_dict()

    async def hotkey(self, *keys: str) -> Dict[str, Any]:
        """执行快捷键"""
        if not self.automator:
            return {"error": "Automator not initialized"}

        result = await self.automator.execute_action(UIAction.HOTKEY, None, {"keys": list(keys)})
        return result.to_dict()

    async def find_and_click(self, selector: Dict[str, Any]) -> Dict[str, Any]:
        """按名字 / automation_id 找控件并点击(控件级:本仓 UIA、微软 UFO)。"""
        params = {k: selector[k] for k in ("name", "automation_id", "control_type", "window") if selector.get(k)}
        if not (params.get("name") or params.get("automation_id")):
            return {"error": "要给控件名字(name)或 automation_id", "selector": selector}
        try:
            from core.windows_execution_arbiter import get_windows_arbiter

            res = await get_windows_arbiter().execute(
                action="find_and_click", params=params, device_id="local", structural_only=True
            )
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e), "selector": selector}
        detail = res.result or {}
        return {
            "success": bool(res.success),
            "via": f"{res.final_level.value}/{detail.get('backend', '')}".rstrip("/"),
            **({} if res.success else {"error": str(detail.get("error") or "没找到或没点成")}),
        }

    async def get_screen_info(self) -> Dict[str, Any]:
        """获取屏幕信息"""
        if not self.automator:
            return {"error": "Automator not initialized"}

        from core.desktop_automation import describe

        window = await self.automator.get_active_window()
        screenshot = await self.automator.capture_screen()

        return {
            "active_window": window.to_dict() if window else None,
            "screenshot": screenshot,
            "ufo_available": self.automator.ufo_available,
            "desktop": describe(),
        }

    async def execute_task(self, task_description: str, app_name: str = None) -> Dict[str, Any]:
        """一句自然语言的任务 → Computer Use 闭环(这一整体的「脑子」)。``app_name`` 并进任务描述。"""
        from core.computer_use_loop import computer_use_enabled, run_computer_use_task

        if not computer_use_enabled():
            return {"success": False, "task": task_description, "error": "Computer Use 关着(GALAXY_COMPUTER_USE)"}
        instruction = f"在 {app_name} 里:{task_description}" if app_name else task_description
        result = await run_computer_use_task(instruction)
        return {"task": task_description, **(result if isinstance(result, dict) else {"result": result})}


# ============================================================================
# 全局实例
# ============================================================================

ufo_integration = GalaxyIntegrationService()


async def main():
    """示例:看这台机器上桌面自动化能用什么。"""
    success = await ufo_integration.initialize()
    print(f"Initialization: {'Success' if success else 'Failed'}")
    if success:
        info = await ufo_integration.get_screen_info()
        print(f"UFO available: {info.get('ufo_available', False)}")


if __name__ == "__main__":
    asyncio.run(main())
