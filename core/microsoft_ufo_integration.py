# -*- coding: utf-8 -*-
"""
UFO Galaxy - 微软 UFO 深度集成模块
===================================

功能：
1. 深度集成微软 UFO 的 UI 自动化能力
2. 统一的 UI 控制接口
3. 支持 Windows、macOS 的 UI 自动化
4. 与 UFO Galaxy 节点系统无缝对接

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
        self.controller = None
        self.ufo_available = False
    
    async def initialize(self) -> bool:
        """初始化微软 UFO"""
        try:
            # 尝试导入微软 UFO 模块
            from external.microsoft_ufo.automator.puppeteer import Puppeteer
            from external.microsoft_ufo.automator.ui_control.controller import UIController
            
            self.puppeteer = Puppeteer()
            self.controller = UIController()
            self.ufo_available = True
            self.is_initialized = True
            
            logger.info("Microsoft UFO initialized successfully")
            return True
            
        except ImportError as e:
            logger.warning(f"Microsoft UFO not available: {e}")
            # 降级到 pyautogui
            return await self._initialize_fallback()
        except Exception as e:
            logger.error(f"Failed to initialize Microsoft UFO: {e}")
            return False
    
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
        """获取当前活动窗口"""
        if self.ufo_available and self.controller:
            try:
                window_info = self.controller.get_active_window()
                if window_info:
                    return UIElement(
                        element_id=str(window_info.get("handle", "unknown")),
                        element_type=UIElementType.WINDOW,
                        name=window_info.get("title", "Unknown"),
                        bounds=(
                            window_info.get("x", 0),
                            window_info.get("y", 0),
                            window_info.get("width", 0),
                            window_info.get("height", 0)
                        )
                    )
            except Exception as e:
                logger.error(f"Failed to get active window: {e}")
        
        # 降级方案
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
            logger.error(f"Fallback get_active_window failed: {e}")
        
        return None
    
    async def find_element(self, selector: Dict[str, Any]) -> Optional[UIElement]:
        """查找 UI 元素"""
        if self.ufo_available and self.controller:
            try:
                # 使用微软 UFO 的元素查找
                element = self.controller.find_element(
                    name=selector.get("name"),
                    automation_id=selector.get("automation_id"),
                    class_name=selector.get("class_name"),
                    control_type=selector.get("control_type")
                )
                if element:
                    return self._convert_ufo_element(element)
            except Exception as e:
                logger.error(f"UFO find_element failed: {e}")
        
        return None
    
    async def find_elements(self, selector: Dict[str, Any]) -> List[UIElement]:
        """查找多个 UI 元素"""
        if self.ufo_available and self.controller:
            try:
                elements = self.controller.find_elements(
                    name=selector.get("name"),
                    automation_id=selector.get("automation_id"),
                    class_name=selector.get("class_name"),
                    control_type=selector.get("control_type")
                )
                return [self._convert_ufo_element(e) for e in elements]
            except Exception as e:
                logger.error(f"UFO find_elements failed: {e}")
        
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
        """使用微软 UFO 执行动作"""
        try:
            if action == UIAction.CLICK:
                x, y = params.get("x"), params.get("y")
                if x is not None and y is not None:
                    self.puppeteer.click(x, y)
                elif element_id:
                    element = self.controller.find_element_by_id(element_id)
                    if element:
                        element.click()
                return UIActionResult(success=True, action=action, element_id=element_id, message="Click executed")
            
            elif action == UIAction.TYPE:
                text = params.get("text", "")
                self.puppeteer.type_text(text)
                return UIActionResult(success=True, action=action, message=f"Typed: {text[:20]}...")
            
            elif action == UIAction.HOTKEY:
                keys = params.get("keys", [])
                self.puppeteer.hotkey(*keys)
                return UIActionResult(success=True, action=action, message=f"Hotkey: {'+'.join(keys)}")
            
            elif action == UIAction.SCROLL:
                direction = params.get("direction", "down")
                amount = params.get("amount", 3)
                self.puppeteer.scroll(direction, amount)
                return UIActionResult(success=True, action=action, message=f"Scrolled {direction}")
            
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
        """获取 UI 元素树"""
        if self.ufo_available and self.controller:
            try:
                tree = self.controller.get_element_tree(root_id)
                return tree
            except Exception as e:
                logger.error(f"Failed to get element tree: {e}")
        
        return {"error": "Element tree not available"}


# ============================================================================
# UFO Galaxy 集成服务
# ============================================================================

class UFOIntegrationService:
    """
    UFO Galaxy 与微软 UFO 的集成服务
    
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
        
        这是与微软 UFO 最深度的集成点，利用 UFO 的 Agent 能力
        """
        if not self.automator or not self.automator.ufo_available:
            return {"error": "Microsoft UFO not available for task execution"}
        
        try:
            # 使用微软 UFO 的 Agent 执行任务
            from external.microsoft_ufo.agents.agent.app_agent import AppAgent
            
            agent = AppAgent(
                name="ufo_galaxy_agent",
                process_name=app_name or "explorer",
                app_root_name=app_name or "Desktop"
            )
            
            result = await asyncio.to_thread(agent.execute_task, task_description)
            
            return {
                "success": True,
                "task": task_description,
                "result": result
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

ufo_integration = UFOIntegrationService()


# ============================================================================
# FastAPI 路由
# ============================================================================

def create_ufo_api():
    """创建 UFO 集成 API"""
    from fastapi import FastAPI
    from pydantic import BaseModel
    
    app = FastAPI(title="UFO Galaxy - Microsoft UFO Integration", version="2.0")
    
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
