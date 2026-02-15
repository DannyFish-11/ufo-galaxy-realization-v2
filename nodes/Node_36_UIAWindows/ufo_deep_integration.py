# -*- coding: utf-8 -*-
"""
Node 36: UIAWindows - 微软 UFO 深度集成模块
==========================================

功能：
1. 深度集成微软 UFO 的 UI 自动化能力
2. 提供统一的 Windows UI 控制接口
3. 支持自然语言任务执行
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
import base64
from io import BytesIO
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
from dataclasses import dataclass
from enum import Enum

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 添加微软 UFO 路径
UFO_ROOT = Path(__file__).parent.parent.parent / "external" / "microsoft_ufo"
if UFO_ROOT.exists():
    sys.path.insert(0, str(UFO_ROOT))


# ============================================================================
# 微软 UFO 组件加载器
# ============================================================================

class UFOComponentLoader:
    """微软 UFO 组件加载器"""
    
    def __init__(self):
        self.puppeteer = None
        self.controller = None
        self.app_agent = None
        self.host_agent = None
        self.is_loaded = False
        self.load_errors = []
    
    def load_all(self) -> bool:
        """加载所有微软 UFO 组件"""
        success = True
        
        # 加载 Puppeteer
        try:
            from automator.puppeteer import Puppeteer
            self.puppeteer = Puppeteer
            logger.info("✅ Loaded Microsoft UFO Puppeteer")
        except ImportError as e:
            self.load_errors.append(f"Puppeteer: {e}")
            success = False
        
        # 加载 UIController
        try:
            from automator.ui_control.controller import UIController
            self.controller = UIController
            logger.info("✅ Loaded Microsoft UFO UIController")
        except ImportError as e:
            self.load_errors.append(f"UIController: {e}")
            success = False
        
        # 加载 AppAgent
        try:
            from agents.agent.app_agent import AppAgent
            self.app_agent = AppAgent
            logger.info("✅ Loaded Microsoft UFO AppAgent")
        except ImportError as e:
            self.load_errors.append(f"AppAgent: {e}")
        
        # 加载 HostAgent
        try:
            from agents.agent.host_agent import HostAgent
            self.host_agent = HostAgent
            logger.info("✅ Loaded Microsoft UFO HostAgent")
        except ImportError as e:
            self.load_errors.append(f"HostAgent: {e}")
        
        self.is_loaded = success
        return success
    
    def get_status(self) -> Dict[str, Any]:
        """获取加载状态"""
        return {
            "is_loaded": self.is_loaded,
            "puppeteer_available": self.puppeteer is not None,
            "controller_available": self.controller is not None,
            "app_agent_available": self.app_agent is not None,
            "host_agent_available": self.host_agent is not None,
            "errors": self.load_errors
        }


# ============================================================================
# UFO 深度集成服务
# ============================================================================

class UFODeepIntegration:
    """
    微软 UFO 深度集成服务
    
    提供与微软 UFO 的深度集成，包括：
    1. UI 元素识别和操作
    2. 应用程序控制
    3. 自然语言任务执行
    4. 屏幕分析和理解
    """
    
    def __init__(self):
        self.loader = UFOComponentLoader()
        self.puppeteer_instance = None
        self.controller_instance = None
        self.is_initialized = False
        
        # 降级方案
        self.pyautogui = None
        self.pygetwindow = None
    
    async def initialize(self) -> Dict[str, Any]:
        """初始化集成服务"""
        result = {
            "success": False,
            "ufo_available": False,
            "fallback_available": False,
            "message": ""
        }
        
        # 尝试加载微软 UFO
        if self.loader.load_all():
            result["ufo_available"] = True
            
            # 创建实例
            try:
                if self.loader.puppeteer:
                    self.puppeteer_instance = self.loader.puppeteer()
                if self.loader.controller:
                    self.controller_instance = self.loader.controller()
                
                result["message"] = "Microsoft UFO initialized successfully"
            except Exception as e:
                result["message"] = f"UFO instance creation failed: {e}"
        else:
            result["message"] = f"UFO load failed: {self.loader.load_errors}"
        
        # 加载降级方案
        try:
            import pyautogui
            self.pyautogui = pyautogui
            self.pyautogui.FAILSAFE = True
            self.pyautogui.PAUSE = 0.1
            result["fallback_available"] = True
        except ImportError:
            pass
        
        try:
            import pygetwindow
            self.pygetwindow = pygetwindow
        except ImportError:
            pass
        
        self.is_initialized = result["ufo_available"] or result["fallback_available"]
        result["success"] = self.is_initialized
        
        return result
    
    # ========================================================================
    # UI 元素操作
    # ========================================================================
    
    async def find_element(self, selector: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        查找 UI 元素
        
        Args:
            selector: 选择器，支持：
                - name: 元素名称
                - automation_id: 自动化 ID
                - class_name: 类名
                - control_type: 控件类型
        
        Returns:
            元素信息字典
        """
        if self.controller_instance:
            try:
                element = self.controller_instance.find_element(
                    name=selector.get("name"),
                    automation_id=selector.get("automation_id"),
                    class_name=selector.get("class_name"),
                    control_type=selector.get("control_type")
                )
                if element:
                    return self._element_to_dict(element)
            except Exception as e:
                logger.error(f"UFO find_element failed: {e}")
        
        return None
    
    async def find_elements(self, selector: Dict[str, Any]) -> List[Dict[str, Any]]:
        """查找多个 UI 元素"""
        if self.controller_instance:
            try:
                elements = self.controller_instance.find_elements(
                    name=selector.get("name"),
                    automation_id=selector.get("automation_id"),
                    class_name=selector.get("class_name"),
                    control_type=selector.get("control_type")
                )
                return [self._element_to_dict(e) for e in elements]
            except Exception as e:
                logger.error(f"UFO find_elements failed: {e}")
        
        return []
    
    def _element_to_dict(self, element) -> Dict[str, Any]:
        """将 UFO 元素转换为字典"""
        try:
            rect = element.rectangle() if hasattr(element, 'rectangle') else None
            return {
                "name": element.name if hasattr(element, 'name') else "",
                "text": element.window_text() if hasattr(element, 'window_text') else "",
                "control_type": element.control_type() if hasattr(element, 'control_type') else "",
                "automation_id": element.automation_id() if hasattr(element, 'automation_id') else "",
                "bounds": {
                    "x": rect.left if rect else 0,
                    "y": rect.top if rect else 0,
                    "width": rect.width() if rect else 0,
                    "height": rect.height() if rect else 0
                } if rect else None,
                "is_enabled": element.is_enabled() if hasattr(element, 'is_enabled') else True,
                "is_visible": element.is_visible() if hasattr(element, 'is_visible') else True
            }
        except Exception as e:
            return {"error": str(e)}
    
    # ========================================================================
    # 基本操作
    # ========================================================================
    
    async def click(self, x: int, y: int, button: str = "left", clicks: int = 1) -> Dict[str, Any]:
        """点击操作"""
        try:
            if self.puppeteer_instance:
                self.puppeteer_instance.click(x, y, button=button, clicks=clicks)
            elif self.pyautogui:
                self.pyautogui.click(x, y, button=button, clicks=clicks)
            else:
                return {"success": False, "error": "No automation backend available"}
            
            return {"success": True, "action": "click", "x": x, "y": y, "button": button}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def double_click(self, x: int, y: int) -> Dict[str, Any]:
        """双击操作"""
        return await self.click(x, y, clicks=2)
    
    async def right_click(self, x: int, y: int) -> Dict[str, Any]:
        """右键点击"""
        return await self.click(x, y, button="right")
    
    async def type_text(self, text: str, interval: float = 0.05) -> Dict[str, Any]:
        """输入文本"""
        try:
            if self.puppeteer_instance:
                self.puppeteer_instance.type_text(text)
            elif self.pyautogui:
                # 处理中文
                if any('\u4e00' <= char <= '\u9fff' for char in text):
                    try:
                        import pyperclip
                        pyperclip.copy(text)
                        self.pyautogui.hotkey('ctrl', 'v')
                    except ImportError:
                        self.pyautogui.write(text, interval=interval)
                else:
                    self.pyautogui.write(text, interval=interval)
            else:
                return {"success": False, "error": "No automation backend available"}
            
            return {"success": True, "action": "type", "text_length": len(text)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def press_key(self, key: str) -> Dict[str, Any]:
        """按键操作"""
        try:
            if self.puppeteer_instance:
                self.puppeteer_instance.press_key(key)
            elif self.pyautogui:
                self.pyautogui.press(key)
            else:
                return {"success": False, "error": "No automation backend available"}
            
            return {"success": True, "action": "press_key", "key": key}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def hotkey(self, *keys: str) -> Dict[str, Any]:
        """快捷键操作"""
        try:
            if self.puppeteer_instance:
                self.puppeteer_instance.hotkey(*keys)
            elif self.pyautogui:
                self.pyautogui.hotkey(*keys)
            else:
                return {"success": False, "error": "No automation backend available"}
            
            return {"success": True, "action": "hotkey", "keys": list(keys)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def scroll(self, direction: str = "down", amount: int = 3) -> Dict[str, Any]:
        """滚动操作"""
        try:
            scroll_amount = -amount if direction == "down" else amount
            
            if self.puppeteer_instance:
                self.puppeteer_instance.scroll(direction, amount)
            elif self.pyautogui:
                self.pyautogui.scroll(scroll_amount)
            else:
                return {"success": False, "error": "No automation backend available"}
            
            return {"success": True, "action": "scroll", "direction": direction, "amount": amount}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5) -> Dict[str, Any]:
        """拖拽操作"""
        try:
            if self.pyautogui:
                self.pyautogui.moveTo(start_x, start_y)
                self.pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration)
            else:
                return {"success": False, "error": "No automation backend available"}
            
            return {"success": True, "action": "drag", "start": (start_x, start_y), "end": (end_x, end_y)}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ========================================================================
    # 窗口操作
    # ========================================================================
    
    async def get_active_window(self) -> Dict[str, Any]:
        """获取当前活动窗口"""
        try:
            if self.controller_instance:
                window = self.controller_instance.get_active_window()
                if window:
                    return self._element_to_dict(window)
            
            if self.pygetwindow:
                active = self.pygetwindow.getActiveWindow()
                if active:
                    return {
                        "title": active.title,
                        "bounds": {
                            "x": active.left,
                            "y": active.top,
                            "width": active.width,
                            "height": active.height
                        }
                    }
            
            return {"error": "Could not get active window"}
        except Exception as e:
            return {"error": str(e)}
    
    async def get_all_windows(self) -> List[Dict[str, Any]]:
        """获取所有窗口"""
        try:
            if self.pygetwindow:
                windows = self.pygetwindow.getAllWindows()
                return [
                    {
                        "title": w.title,
                        "bounds": {
                            "x": w.left,
                            "y": w.top,
                            "width": w.width,
                            "height": w.height
                        },
                        "visible": w.visible,
                        "minimized": w.isMinimized,
                        "maximized": w.isMaximized
                    }
                    for w in windows if w.title
                ]
            return []
        except Exception as e:
            return [{"error": str(e)}]
    
    async def focus_window(self, title: str) -> Dict[str, Any]:
        """聚焦窗口"""
        try:
            if self.pygetwindow:
                windows = self.pygetwindow.getWindowsWithTitle(title)
                if windows:
                    windows[0].activate()
                    return {"success": True, "window": title}
            return {"success": False, "error": f"Window not found: {title}"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ========================================================================
    # 屏幕截图
    # ========================================================================
    
    async def capture_screen(self, region: Optional[Tuple[int, int, int, int]] = None) -> Dict[str, Any]:
        """截取屏幕"""
        try:
            if self.pyautogui:
                if region:
                    screenshot = self.pyautogui.screenshot(region=region)
                else:
                    screenshot = self.pyautogui.screenshot()
                
                buffer = BytesIO()
                screenshot.save(buffer, format='PNG')
                image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                
                return {
                    "success": True,
                    "width": screenshot.width,
                    "height": screenshot.height,
                    "image_base64": image_base64
                }
            
            return {"success": False, "error": "Screenshot not available"}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ========================================================================
    # 自然语言任务执行（深度集成微软 UFO Agent）
    # ========================================================================
    
    async def execute_task(self, task: str, app_name: Optional[str] = None) -> Dict[str, Any]:
        """
        执行自然语言描述的任务
        
        这是与微软 UFO 最深度的集成点，利用 UFO 的 Agent 能力
        
        Args:
            task: 自然语言任务描述
            app_name: 目标应用程序名称（可选）
        
        Returns:
            执行结果
        """
        if not self.loader.app_agent:
            return {
                "success": False,
                "error": "Microsoft UFO AppAgent not available",
                "fallback": "Please use basic UI operations instead"
            }
        
        try:
            # 创建 AppAgent 实例
            agent = self.loader.app_agent(
                name="ufo_galaxy_task_agent",
                process_name=app_name or "explorer",
                app_root_name=app_name or "Desktop"
            )
            
            # 执行任务
            result = await asyncio.to_thread(agent.execute_task, task)
            
            return {
                "success": True,
                "task": task,
                "app_name": app_name,
                "result": result
            }
        except Exception as e:
            logger.error(f"Task execution failed: {e}")
            return {
                "success": False,
                "task": task,
                "error": str(e)
            }
    
    # ========================================================================
    # 应用程序控制
    # ========================================================================
    
    async def launch_app(self, app_path: str) -> Dict[str, Any]:
        """启动应用程序"""
        try:
            import subprocess
            subprocess.Popen(app_path, shell=True)
            return {"success": True, "app": app_path}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def close_app(self, process_name: str) -> Dict[str, Any]:
        """关闭应用程序"""
        try:
            import subprocess
            subprocess.run(f"taskkill /f /im {process_name}", shell=True, capture_output=True)
            return {"success": True, "process": process_name}
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    # ========================================================================
    # 状态查询
    # ========================================================================
    
    def get_status(self) -> Dict[str, Any]:
        """获取集成状态"""
        return {
            "is_initialized": self.is_initialized,
            "ufo_status": self.loader.get_status(),
            "fallback_available": self.pyautogui is not None,
            "window_manager_available": self.pygetwindow is not None
        }


# ============================================================================
# FastAPI 路由
# ============================================================================

def create_ufo_integration_api():
    """创建 UFO 集成 API"""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
    
    app = FastAPI(title="UFO Galaxy - Microsoft UFO Deep Integration", version="2.0")
    integration = UFODeepIntegration()
    
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
    
    class ScrollRequest(BaseModel):
        direction: str = "down"
        amount: int = 3
    
    class DragRequest(BaseModel):
        start_x: int
        start_y: int
        end_x: int
        end_y: int
        duration: float = 0.5
    
    class FindElementRequest(BaseModel):
        name: Optional[str] = None
        automation_id: Optional[str] = None
        class_name: Optional[str] = None
        control_type: Optional[str] = None
    
    class TaskRequest(BaseModel):
        task: str
        app_name: Optional[str] = None
    
    class LaunchAppRequest(BaseModel):
        app_path: str
    
    class CloseAppRequest(BaseModel):
        process_name: str
    
    @app.on_event("startup")
    async def startup():
        await integration.initialize()
    
    @app.get("/status")
    async def get_status():
        return integration.get_status()
    
    @app.post("/click")
    async def click(request: ClickRequest):
        return await integration.click(request.x, request.y, request.button, request.clicks)
    
    @app.post("/double_click")
    async def double_click(request: ClickRequest):
        return await integration.double_click(request.x, request.y)
    
    @app.post("/right_click")
    async def right_click(request: ClickRequest):
        return await integration.right_click(request.x, request.y)
    
    @app.post("/type")
    async def type_text(request: TypeRequest):
        return await integration.type_text(request.text, request.interval)
    
    @app.post("/press_key/{key}")
    async def press_key(key: str):
        return await integration.press_key(key)
    
    @app.post("/hotkey")
    async def hotkey(request: HotkeyRequest):
        return await integration.hotkey(*request.keys)
    
    @app.post("/scroll")
    async def scroll(request: ScrollRequest):
        return await integration.scroll(request.direction, request.amount)
    
    @app.post("/drag")
    async def drag(request: DragRequest):
        return await integration.drag(
            request.start_x, request.start_y,
            request.end_x, request.end_y,
            request.duration
        )
    
    @app.get("/window/active")
    async def get_active_window():
        return await integration.get_active_window()
    
    @app.get("/window/all")
    async def get_all_windows():
        return await integration.get_all_windows()
    
    @app.post("/window/focus/{title}")
    async def focus_window(title: str):
        return await integration.focus_window(title)
    
    @app.post("/find_element")
    async def find_element(request: FindElementRequest):
        selector = request.dict(exclude_none=True)
        return await integration.find_element(selector)
    
    @app.post("/find_elements")
    async def find_elements(request: FindElementRequest):
        selector = request.dict(exclude_none=True)
        return await integration.find_elements(selector)
    
    @app.get("/screenshot")
    async def capture_screen():
        return await integration.capture_screen()
    
    @app.post("/task")
    async def execute_task(request: TaskRequest):
        return await integration.execute_task(request.task, request.app_name)
    
    @app.post("/app/launch")
    async def launch_app(request: LaunchAppRequest):
        return await integration.launch_app(request.app_path)
    
    @app.post("/app/close")
    async def close_app(request: CloseAppRequest):
        return await integration.close_app(request.process_name)
    
    return app


# ============================================================================
# 全局实例
# ============================================================================

ufo_deep = UFODeepIntegration()


# ============================================================================
# 示例使用
# ============================================================================

async def main():
    """示例：如何使用 UFO 深度集成"""
    
    # 初始化
    result = await ufo_deep.initialize()
    print(f"Initialization: {json.dumps(result, indent=2)}")
    
    # 获取状态
    status = ufo_deep.get_status()
    print(f"Status: {json.dumps(status, indent=2)}")
    
    if result["success"]:
        # 获取活动窗口
        window = await ufo_deep.get_active_window()
        print(f"Active window: {json.dumps(window, indent=2)}")
        
        # 截图
        screenshot = await ufo_deep.capture_screen()
        print(f"Screenshot: {screenshot['width']}x{screenshot['height']}")


if __name__ == "__main__":
    asyncio.run(main())
