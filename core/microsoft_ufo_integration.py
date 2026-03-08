# -*- coding: utf-8 -*-
"""
Galaxy - 微软 UFO 深度集成模块
===================================

功能：
1. 深度集成微软 UFO 的 UI 自动化能力
2. 统一的 UI 控制接口
3. 支持 Windows、macOS 的 UI 自动化
4. 与 Galaxy 节点系统无缝对接

作者：Manus AI
日期：2026-02-06
版本：2.0
"""

import asyncio
import logging
import os
import sys
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 添加微软 UFO 路径
UFO_PATH = Path(__file__).parent.parent / "external" / "microsoft_ufo"
if UFO_PATH.exists():
    sys.path.insert(0, str(UFO_PATH))


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
            "properties": self.properties
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
            "error": self.error
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
        pass
    
    @abstractmethod
    async def get_active_window(self) -> Optional[UIElement]:
        """获取当前活动窗口"""
        pass
    
    @abstractmethod
    async def find_element(self, selector: Dict[str, Any]) -> Optional[UIElement]:
        """查找 UI 元素"""
        pass
    
    @abstractmethod
    async def find_elements(self, selector: Dict[str, Any]) -> List[UIElement]:
        """查找多个 UI 元素"""
        pass
    
    @abstractmethod
    async def execute_action(self, action: UIAction, element_id: Optional[str], params: Dict[str, Any]) -> UIActionResult:
        """执行 UI 动作"""
        pass
    
    @abstractmethod
    async def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Optional[str]:
        """截取屏幕"""
        pass
    
    @abstractmethod
    async def get_element_tree(self, root_id: Optional[str] = None) -> Dict[str, Any]:
        """获取 UI 元素树"""
        pass


# ============================================================================
# 微软 UFO 集成
# ============================================================================

class MicrosoftUFOAutomator(BaseUIAutomator):
    """
    微软 UFO UI 自动化器
    
    深度集成微软 UFO 的 UI 控制能力
    """
    
    def __init__(self):
        super().__init__()
        self.puppeteer = None
        self._ControlReceiver = None
        self.ufo_available = False
    
    async def initialize(self, process_name: str = "explorer.exe",
                         app_root_name: str = "Desktop") -> bool:
        """初始化微软 UFO

        Args:
            process_name: 目标应用进程名 (AppPuppeteer 构造必需)
            app_root_name: 应用根窗口名
        """
        try:
            # 正确的类名: AppPuppeteer (非 Puppeteer), ControlReceiver (非 UIController)
            from automator.puppeteer import AppPuppeteer
            from automator.ui_control.controller import ControlReceiver

            # AppPuppeteer 构造需要 process_name 和 app_root_name
            self.puppeteer = AppPuppeteer(process_name, app_root_name)
            # ControlReceiver 需要 pywinauto 控件实例, 延迟到具体操作时创建
            self._ControlReceiver = ControlReceiver
            self.ufo_available = True
            self.is_initialized = True

            logger.info("Microsoft UFO initialized (AppPuppeteer + ControlReceiver)")
            return True

        except ImportError as e:
            logger.warning(f"Microsoft UFO not available: {e}")
            # 降级到 pyautogui
            return await self._initialize_fallback()
        except Exception as e:
            logger.error(f"Failed to initialize Microsoft UFO: {e}")
            return await self._initialize_fallback()
    
    async def _initialize_fallback(self) -> bool:
        """初始化降级方案"""
        try:
            import pyautogui
            self.is_initialized = True
            logger.info("Fallback to pyautogui")
            return True
        except ImportError:
            logger.error("pyautogui not available")
            return False
    
    async def get_active_window(self) -> Optional[UIElement]:
        """获取当前活动窗口

        ControlReceiver 不提供窗口枚举, 直接使用 pygetwindow。
        """
        # pygetwindow 方案（跨后端通用）
        try:
            import pygetwindow as gw
            active = gw.getActiveWindow()
            if active:
                return UIElement(
                    element_id=str(active._hWnd) if hasattr(active, '_hWnd') else "unknown",
                    element_type=UIElementType.WINDOW,
                    name=active.title,
                    bounds=(active.left, active.top, active.width, active.height)
                )
        except Exception as e:
            logger.error(f"get_active_window failed: {e}")

        return None

    async def find_element(self, selector: Dict[str, Any]) -> Optional[UIElement]:
        """查找 UI 元素

        注意: ControlReceiver 需要已有的 pywinauto 控件句柄，不提供
        按属性搜索功能。此方法作为占位，完整实现需要 pywinauto 直接集成。
        """
        logger.warning("find_element: ControlReceiver does not support search by selector; "
                        "use pywinauto directly for element discovery")
        return None

    async def find_elements(self, selector: Dict[str, Any]) -> List[UIElement]:
        """查找多个 UI 元素（同上限制）"""
        logger.warning("find_elements: ControlReceiver does not support search by selector")
        return []
    
    def _convert_ufo_element(self, ufo_element) -> UIElement:
        """转换微软 UFO 元素为统一格式"""
        try:
            rect = ufo_element.rectangle() if hasattr(ufo_element, 'rectangle') else None
            bounds = (rect.left, rect.top, rect.width(), rect.height()) if rect else (0, 0, 0, 0)
            
            return UIElement(
                element_id=str(ufo_element.control_id()) if hasattr(ufo_element, 'control_id') else "unknown",
                element_type=UIElementType.CUSTOM,
                name=ufo_element.name if hasattr(ufo_element, 'name') else "",
                text=ufo_element.window_text() if hasattr(ufo_element, 'window_text') else "",
                bounds=bounds,
                is_enabled=ufo_element.is_enabled() if hasattr(ufo_element, 'is_enabled') else True,
                is_visible=ufo_element.is_visible() if hasattr(ufo_element, 'is_visible') else True
            )
        except Exception as e:
            logger.error(f"Failed to convert UFO element: {e}")
            return UIElement(
                element_id="unknown",
                element_type=UIElementType.CUSTOM,
                name="Unknown"
            )
    
    async def execute_action(self, action: UIAction, element_id: Optional[str], params: Dict[str, Any]) -> UIActionResult:
        """执行 UI 动作"""
        import time
        start_time = time.time()
        
        try:
            if self.ufo_available and self.puppeteer:
                result = await self._execute_with_ufo(action, element_id, params)
            else:
                result = await self._execute_with_fallback(action, element_id, params)
            
            duration_ms = int((time.time() - start_time) * 1000)
            result.duration_ms = duration_ms
            return result
            
        except Exception as e:
            return UIActionResult(
                success=False,
                action=action,
                element_id=element_id,
                error=str(e),
                duration_ms=int((time.time() - start_time) * 1000)
            )
    
    async def _execute_with_ufo(self, action: UIAction, element_id: Optional[str], params: Dict[str, Any]) -> UIActionResult:
        """使用微软 UFO AppPuppeteer 的 execute_command 执行动作"""
        try:
            if action == UIAction.CLICK:
                x, y = params.get("x"), params.get("y")
                if x is not None and y is not None:
                    # AppPuppeteer 正确接口: execute_command(command_name, params)
                    self.puppeteer.execute_command(
                        "click_on_coordinates",
                        {"x": float(x), "y": float(y), "button": "left", "double": False}
                    )
                elif element_id and self._ControlReceiver:
                    # 通过 ControlReceiver 点击控件
                    self.puppeteer.execute_command("click_input", {})
                return UIActionResult(success=True, action=action, element_id=element_id, message="Click executed")

            elif action == UIAction.DOUBLE_CLICK:
                x, y = params.get("x"), params.get("y")
                if x is not None and y is not None:
                    self.puppeteer.execute_command(
                        "click_on_coordinates",
                        {"x": float(x), "y": float(y), "button": "left", "double": True}
                    )
                return UIActionResult(success=True, action=action, message="Double-click executed")

            elif action == UIAction.TYPE:
                text = params.get("text", "")
                self.puppeteer.execute_command("set_edit_text", {"text": text})
                return UIActionResult(success=True, action=action, message=f"Typed: {text[:20]}...")

            elif action == UIAction.PRESS_KEY:
                keys = params.get("keys", params.get("key", ""))
                key_str = keys if isinstance(keys, str) else " ".join(keys)
                self.puppeteer.execute_command("keyboard_input", {"keys": key_str})
                return UIActionResult(success=True, action=action, message=f"Key: {key_str}")

            elif action == UIAction.HOTKEY:
                keys = params.get("keys", [])
                key_str = "+".join(f"{{{k}}}" for k in keys)
                self.puppeteer.execute_command("keyboard_input", {"keys": key_str})
                return UIActionResult(success=True, action=action, message=f"Hotkey: {'+'.join(keys)}")

            elif action == UIAction.SCROLL:
                direction = params.get("direction", "down")
                amount = params.get("amount", 3)
                scroll_y = -amount if direction == "down" else amount
                self.puppeteer.execute_command(
                    "scroll",
                    {"x": 0, "y": 0, "scroll_x": 0, "scroll_y": scroll_y}
                )
                return UIActionResult(success=True, action=action, message=f"Scrolled {direction}")

            elif action == UIAction.DRAG:
                self.puppeteer.execute_command(
                    "drag_on_coordinates",
                    {
                        "start_x": float(params.get("start_x", 0)),
                        "start_y": float(params.get("start_y", 0)),
                        "end_x": float(params.get("end_x", 0)),
                        "end_y": float(params.get("end_y", 0)),
                        "button": "left",
                    }
                )
                return UIActionResult(success=True, action=action, message="Drag executed")

            else:
                return UIActionResult(success=False, action=action, error=f"Unsupported action: {action.value}")

        except Exception as e:
            return UIActionResult(success=False, action=action, error=str(e))
    
    async def _execute_with_fallback(self, action: UIAction, element_id: Optional[str], params: Dict[str, Any]) -> UIActionResult:
        """使用 pyautogui 执行动作（降级方案）"""
        try:
            import pyautogui
            
            if action == UIAction.CLICK:
                x, y = params.get("x"), params.get("y")
                if x is not None and y is not None:
                    pyautogui.click(x, y)
                    return UIActionResult(success=True, action=action, message=f"Clicked at ({x}, {y})")
            
            elif action == UIAction.TYPE:
                text = params.get("text", "")
                pyautogui.write(text)
                return UIActionResult(success=True, action=action, message=f"Typed: {text[:20]}...")
            
            elif action == UIAction.HOTKEY:
                keys = params.get("keys", [])
                pyautogui.hotkey(*keys)
                return UIActionResult(success=True, action=action, message=f"Hotkey: {'+'.join(keys)}")
            
            elif action == UIAction.SCROLL:
                amount = params.get("amount", 3)
                direction = params.get("direction", "down")
                scroll_amount = -amount if direction == "down" else amount
                pyautogui.scroll(scroll_amount)
                return UIActionResult(success=True, action=action, message=f"Scrolled {direction}")
            
            return UIActionResult(success=False, action=action, error=f"Unsupported action: {action.value}")
            
        except Exception as e:
            return UIActionResult(success=False, action=action, error=str(e))
    
    async def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Optional[str]:
        """截取屏幕"""
        try:
            import pyautogui
            import base64
            from io import BytesIO
            
            if region:
                screenshot = pyautogui.screenshot(region=region)
            else:
                screenshot = pyautogui.screenshot()
            
            buffer = BytesIO()
            screenshot.save(buffer, format='PNG')
            return base64.b64encode(buffer.getvalue()).decode('utf-8')
            
        except Exception as e:
            logger.error(f"Failed to capture screen: {e}")
            return None
    
    async def get_element_tree(self, root_id: Optional[str] = None) -> Dict[str, Any]:
        """获取 UI 元素树

        ControlReceiver 不提供 get_element_tree, 需要直接使用 pywinauto。
        """
        return {"error": "Element tree requires direct pywinauto integration"}


# ============================================================================
# Galaxy 集成服务
# ============================================================================

class GalaxyIntegrationService:
    """
    Galaxy 与微软 UFO 的集成服务
    
    提供统一的 UI 自动化接口，供节点系统调用
    """
    
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
        
        result = await self.automator.execute_action(
            UIAction.CLICK,
            None,
            {"x": x, "y": y}
        )
        return result.to_dict()
    
    async def type_text(self, text: str) -> Dict[str, Any]:
        """输入文本"""
        if not self.automator:
            return {"error": "Automator not initialized"}
        
        result = await self.automator.execute_action(
            UIAction.TYPE,
            None,
            {"text": text}
        )
        return result.to_dict()
    
    async def hotkey(self, *keys: str) -> Dict[str, Any]:
        """执行快捷键"""
        if not self.automator:
            return {"error": "Automator not initialized"}
        
        result = await self.automator.execute_action(
            UIAction.HOTKEY,
            None,
            {"keys": list(keys)}
        )
        return result.to_dict()
    
    async def find_and_click(self, selector: Dict[str, Any]) -> Dict[str, Any]:
        """查找元素并点击"""
        if not self.automator:
            return {"error": "Automator not initialized"}
        
        element = await self.automator.find_element(selector)
        if not element:
            return {"error": "Element not found", "selector": selector}
        
        # 计算元素中心点
        x = element.bounds[0] + element.bounds[2] // 2
        y = element.bounds[1] + element.bounds[3] // 2
        
        result = await self.automator.execute_action(
            UIAction.CLICK,
            element.element_id,
            {"x": x, "y": y}
        )
        return result.to_dict()
    
    async def get_screen_info(self) -> Dict[str, Any]:
        """获取屏幕信息"""
        if not self.automator:
            return {"error": "Automator not initialized"}
        
        window = await self.automator.get_active_window()
        screenshot = await self.automator.capture_screen()
        
        return {
            "active_window": window.to_dict() if window else None,
            "screenshot": screenshot,
            "ufo_available": self.automator.ufo_available
        }
    
    async def execute_task(self, task_description: str, app_name: str = None) -> Dict[str, Any]:
        """
        执行自然语言描述的任务

        注意: AppAgent 需要 is_visual, main_prompt, example_prompt 等参数以及完整
        的 UFO 配置环境。此方法使用 AppPuppeteer 的命令队列模式作为轻量级替代。
        完整的 Agent 驱动任务执行需要独立的 UFO 环境配置。
        """
        if not self.automator or not self.automator.ufo_available:
            return {"error": "Microsoft UFO not available for task execution"}

        try:
            # 轻量级路径: 用 AppPuppeteer 命令队列
            # 重新初始化 puppeteer 指向目标应用
            process = app_name or "explorer.exe"
            await self.automator.initialize(process_name=process, app_root_name=process)

            # 列出可用命令
            available = self.automator.puppeteer.list_commands() if self.automator.puppeteer else set()

            return {
                "success": True,
                "task": task_description,
                "mode": "puppeteer_command_queue",
                "target_app": process,
                "available_commands": list(available),
                "note": "Use /ufo/click, /ufo/type etc. to execute individual steps. "
                        "Full AppAgent-based NL task execution requires UFO environment setup."
            }

        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            return {
                "success": False,
                "task": task_description,
                "error": str(e)
            }


# ============================================================================
# 全局实例
# ============================================================================

ufo_integration = GalaxyIntegrationService()


# ============================================================================
# FastAPI 路由
# ============================================================================

def create_ufo_api():
    """创建 UFO 集成 API"""
    from fastapi import FastAPI
    from pydantic import BaseModel
    
    app = FastAPI(title="Galaxy - Microsoft UFO Integration", version="2.0")
    
    class ClickRequest(BaseModel):
        x: int
        y: int
    
    class TypeRequest(BaseModel):
        text: str
    
    class HotkeyRequest(BaseModel):
        keys: List[str]
    
    class FindAndClickRequest(BaseModel):
        name: Optional[str] = None
        automation_id: Optional[str] = None
        class_name: Optional[str] = None
        control_type: Optional[str] = None
    
    class TaskRequest(BaseModel):
        task: str
        app_name: Optional[str] = None
    
    @app.post("/ufo/initialize")
    async def initialize():
        success = await ufo_integration.initialize()
        return {"success": success}
    
    @app.post("/ufo/click")
    async def click(request: ClickRequest):
        return await ufo_integration.click(request.x, request.y)
    
    @app.post("/ufo/type")
    async def type_text(request: TypeRequest):
        return await ufo_integration.type_text(request.text)
    
    @app.post("/ufo/hotkey")
    async def hotkey(request: HotkeyRequest):
        return await ufo_integration.hotkey(*request.keys)
    
    @app.post("/ufo/find_and_click")
    async def find_and_click(request: FindAndClickRequest):
        selector = request.dict(exclude_none=True)
        return await ufo_integration.find_and_click(selector)
    
    @app.get("/ufo/screen")
    async def get_screen():
        return await ufo_integration.get_screen_info()
    
    @app.post("/ufo/task")
    async def execute_task(request: TaskRequest):
        return await ufo_integration.execute_task(request.task, request.app_name)
    
    return app


# ============================================================================
# 示例使用
# ============================================================================

async def main():
    """示例：如何使用 UFO 集成服务"""
    
    # 初始化
    success = await ufo_integration.initialize()
    print(f"Initialization: {'Success' if success else 'Failed'}")
    
    if success:
        # 获取屏幕信息
        screen_info = await ufo_integration.get_screen_info()
        print(f"Active window: {screen_info.get('active_window', {}).get('name', 'Unknown')}")
        print(f"UFO available: {screen_info.get('ufo_available', False)}")
        
        # 执行点击
        result = await ufo_integration.click(100, 100)
        print(f"Click result: {result}")
        
        # 执行快捷键
        result = await ufo_integration.hotkey("ctrl", "c")
        print(f"Hotkey result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
