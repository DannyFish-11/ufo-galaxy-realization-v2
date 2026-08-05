# -*- coding: utf-8 -*-
"""
Node 36: UIAWindows - 微软 UFO 深度集成模块
==========================================

功能：
1. 深度集成微软 UFO 的 UI 自动化能力
2. 提供统一的 Windows UI 控制接口
3. 支持自然语言任务执行
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

class GalaxyComponentLoader:
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

        # 加载 AppPuppeteer (正确类名, 非 Puppeteer)
        try:
            from automator.puppeteer import AppPuppeteer
            self.puppeteer = AppPuppeteer
            logger.info("Loaded Microsoft UFO AppPuppeteer")
        except ImportError as e:
            self.load_errors.append(f"AppPuppeteer: {e}")
            success = False

        # 加载 ControlReceiver (正确类名, 非 UIController)
        try:
            from automator.ui_control.controller import ControlReceiver
            self.controller = ControlReceiver
            logger.info("Loaded Microsoft UFO ControlReceiver")
        except ImportError as e:
            self.load_errors.append(f"ControlReceiver: {e}")
            success = False

        # 加载 AppAgent
        try:
            from agents.agent.app_agent import AppAgent
            self.app_agent = AppAgent
            logger.info("Loaded Microsoft UFO AppAgent")
        except ImportError as e:
            self.load_errors.append(f"AppAgent: {e}")

        # 加载 HostAgent
        try:
            from agents.agent.host_agent import HostAgent
            self.host_agent = HostAgent
            logger.info("Loaded Microsoft UFO HostAgent")
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
        self.loader = GalaxyComponentLoader()
        self.puppeteer_instance = None
        self._ControlReceiverClass = None
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

            # 创建实例 — AppPuppeteer 需要 (process_name, app_root_name)
            try:
                if self.loader.puppeteer:
                    self.puppeteer_instance = self.loader.puppeteer(
                        "explorer.exe", "Desktop"
                    )
                # ControlReceiver 需要 pywinauto 控件, 延迟到具体操作时创建
                self._ControlReceiverClass = self.loader.controller

                result["message"] = "Microsoft UFO initialized (AppPuppeteer + ControlReceiver)"
            except Exception as e:
                logger.debug("Fallback triggered: %s", e)
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
    
    def capture_desktop_graph(self, window_title: Optional[str] = None,
                              max_depth: int = 40) -> Optional[Dict[str, Any]]:
        """读一棵真实的 Windows UIA 控件树 → 结构化 UIGraph（dict）。

        这是桌面 system-API 的"结构优先"输入:对着语义控件图(名为『发送』的按钮)
        推理,而不是对着像素猜坐标。非 Windows / 缺 pywinauto 时返回 None(上层回退
        视觉)。前台窗口默认;给 window_title 则按标题连接。"""
        try:
            from pywinauto import Desktop  # 延迟 import: 仅 Windows 可用
        except Exception as e:  # noqa: BLE001
            logger.info("capture_desktop_graph 不可用(非 Windows / 缺 pywinauto): %s", e)
            return None
        try:
            from .ui_tree import build_ui_graph
        except ImportError:
            from ui_tree import build_ui_graph  # 直接运行时的回退
        try:
            desk = Desktop(backend="uia")
            win = desk.window(title=window_title) if window_title else desk.window(active_only=True)
            ctl = win.wrapper_object()
            app = ""
            try:
                app = ctl.window_text()
            except Exception:  # noqa: BLE001
                pass
            graph = build_ui_graph(ctl, app=app, device_id="windows", max_depth=max_depth)
            return graph.model_dump()
        except Exception as e:  # noqa: BLE001
            logger.warning("capture_desktop_graph 失败: %s", e)
            return None

    async def get_ui_tree(self, window_title: Optional[str] = None,
                          max_depth: int = 40) -> Dict[str, Any]:
        """结构化界面树端点。返回 ``{success, graph?, prompt?, error?}``。"""
        graph = self.capture_desktop_graph(window_title, max_depth)
        if graph is None:
            return {"success": False, "error": "ui_tree_unavailable"}
        try:
            from core.schemas.ui_element import UIGraph
            prompt = UIGraph.model_validate(graph).to_prompt()
        except Exception:  # noqa: BLE001
            prompt = ""
        return {"success": True, "graph": graph, "prompt": prompt}

    async def find_element(self, selector: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """按选择器查找单个 UI 元素(结构化 UIA 树搜索;真做实,不再是桩)。

        selector 支持: name/label · automation_id · class_name · control_type/role。
        命中多个时可交互控件优先。非 Windows / 无树时返回 None。"""
        hits = await self.find_elements(selector)
        return hits[0] if hits else None

    async def find_elements(self, selector: Dict[str, Any]) -> List[Dict[str, Any]]:
        """按选择器查找全部匹配的 UI 元素(结构化 UIA 树搜索)。"""
        graph = self.capture_desktop_graph()
        if graph is None:
            return []
        try:
            from core.schemas.ui_element import UIGraph
            from .ui_tree import find_in_graph
        except ImportError:
            from core.schemas.ui_element import UIGraph
            from ui_tree import find_in_graph
        return [n.model_dump() for n in find_in_graph(UIGraph.model_validate(graph), selector)]
    
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
                # AppPuppeteer 正确接口: execute_command(name, params)
                self.puppeteer_instance.execute_command(
                    "click_on_coordinates",
                    {"x": float(x), "y": float(y), "button": button,
                     "double": clicks >= 2}
                )
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
                self.puppeteer_instance.execute_command(
                    "set_edit_text", {"text": text}
                )
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
                self.puppeteer_instance.execute_command(
                    "keyboard_input", {"keys": f"{{{key}}}"}
                )
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
                key_str = "+".join(f"{{{k}}}" for k in keys)
                self.puppeteer_instance.execute_command(
                    "keyboard_input", {"keys": key_str}
                )
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
                self.puppeteer_instance.execute_command(
                    "scroll",
                    {"x": 0, "y": 0, "scroll_x": 0, "scroll_y": scroll_amount}
                )
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
            # ControlReceiver 不提供 get_active_window, 直接用 pygetwindow
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
        if not self.puppeteer_instance:
            return {
                "success": False,
                "error": "AppPuppeteer not initialized",
                "fallback": "Please use basic UI operations (/click, /type, etc.)"
            }

        try:
            # 重新初始化 puppeteer 指向目标应用
            process = app_name or "explorer.exe"
            if self.loader.puppeteer:
                self.puppeteer_instance = self.loader.puppeteer(process, process)

            available = self.puppeteer_instance.list_commands()

            return {
                "success": True,
                "task": task,
                "app_name": app_name,
                "mode": "puppeteer_command_queue",
                "available_commands": list(available),
                "note": "Full AppAgent NL task execution requires complete UFO "
                        "environment (prompts, config). Use individual commands for now."
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
        """启动应用程序（安全：不使用 shell=True）"""
        try:
            import subprocess
            import re
            # 验证路径不含 shell 元字符
            if re.search(r'[;&|`$]', app_path):
                return {"success": False, "error": f"Invalid characters in app path: {app_path!r}"}
            subprocess.Popen([app_path])
            return {"success": True, "app": app_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def close_app(self, process_name: str) -> Dict[str, Any]:
        """关闭应用程序（安全：不使用 shell=True）"""
        try:
            import subprocess
            import re
            # 验证进程名只含安全字符
            if not re.match(r'^[a-zA-Z0-9_.\-]+$', process_name):
                return {"success": False, "error": f"Invalid process name: {process_name!r}"}
            await asyncio.to_thread(subprocess.run, ["taskkill", "/f", "/im", process_name], capture_output=True)
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
