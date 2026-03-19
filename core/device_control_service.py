"""
设备控制服务
============

封装 Node_92_AutoControl 的调用，提供统一的设备控制接口。

真正能操控设备：
- Windows: 通过 Node_45_Desktop → pyautogui
- Android: 通过 Node_33_ADB 或 WebSocket → 无障碍服务

版本: v2.3.22
"""

import os
import json
import asyncio
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum
import httpx

logger = logging.getLogger(__name__)


class DevicePlatform(Enum):
    """设备平台"""
    WINDOWS = "windows"
    ANDROID = "android"
    MACOS = "macos"
    LINUX = "linux"


@dataclass
class DeviceInfo:
    """设备信息"""
    device_id: str
    platform: DevicePlatform
    name: str
    status: str = "offline"
    capabilities: List[str] = None
    
    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = []


class DeviceControlService:
    """设备控制服务"""
    
    def __init__(self):
        # 节点服务地址
        self.node_urls = {
            "auto_control": os.getenv("NODE_92_URL", "http://localhost:8092"),
            "desktop": os.getenv("NODE_45_URL", "http://localhost:8045"),
            "adb": os.getenv("NODE_33_URL", "http://localhost:8033"),
            "multi_device": os.getenv("NODE_71_URL", "http://localhost:8071"),
        }
        
        # 已注册的设备
        self.devices: Dict[str, DeviceInfo] = {}
        
        # HTTP 客户端
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取 HTTP 客户端"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client
    
    # =========================================================================
    # 设备管理
    # =========================================================================
    
    async def register_device(
        self,
        device_id: str,
        platform: str,
        name: str,
        capabilities: List[str] = None
    ) -> bool:
        """注册设备"""
        device = DeviceInfo(
            device_id=device_id,
            platform=DevicePlatform(platform.lower()),
            name=name,
            status="online",
            capabilities=capabilities or []
        )
        self.devices[device_id] = device
        logger.info(f"Device registered: {device_id} ({platform})")
        return True
    
    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """获取设备信息"""
        return self.devices.get(device_id)
    
    def list_devices(self) -> List[DeviceInfo]:
        """列出所有设备"""
        return list(self.devices.values())
    
    # =========================================================================
    # 统一控制接口 - 真正执行操作
    # =========================================================================
    
    async def click(
        self,
        device_id: str,
        x: int,
        y: int,
        clicks: int = 1
    ) -> Dict[str, Any]:
        """
        点击屏幕
        
        真正执行：
        - Windows: pyautogui.click(x, y)
        - Android: AccessibilityService.performClick(x, y)
        """
        device = self.get_device(device_id)
        if not device:
            return {"success": False, "error": "Device not found"}
        
        try:
            client = await self._get_client()
            
            if device.platform == DevicePlatform.WINDOWS:
                # 调用 Node_92 AutoControl
                response = await client.post(
                    f"{self.node_urls['auto_control']}/click",
                    json={
                        "device_id": device_id,
                        "platform": "windows",
                        "x": x,
                        "y": y,
                        "clicks": clicks
                    }
                )
                result = response.json()
                logger.info(f"Windows click: ({x}, {y}) -> {result}")
                return result
            
            elif device.platform == DevicePlatform.ANDROID:
                # 调用 Node_92 AutoControl (Android)
                response = await client.post(
                    f"{self.node_urls['auto_control']}/click",
                    json={
                        "device_id": device_id,
                        "platform": "android",
                        "x": x,
                        "y": y
                    }
                )
                result = response.json()
                logger.info(f"Android click: ({x}, {y}) -> {result}")
                return result
            
            else:
                return {"success": False, "error": f"Unsupported platform: {device.platform}"}
        
        except Exception as e:
            logger.error(f"Click failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def input_text(
        self,
        device_id: str,
        text: str
    ) -> Dict[str, Any]:
        """
        输入文本
        
        真正执行：
        - Windows: pyautogui.typewrite(text)
        - Android: AccessibilityService.inputText(text)
        """
        device = self.get_device(device_id)
        if not device:
            return {"success": False, "error": "Device not found"}
        
        try:
            client = await self._get_client()
            
            if device.platform == DevicePlatform.WINDOWS:
                response = await client.post(
                    f"{self.node_urls['auto_control']}/input",
                    json={
                        "device_id": device_id,
                        "platform": "windows",
                        "text": text
                    }
                )
                result = response.json()
                logger.info(f"Windows input: {text[:20]}... -> {result}")
                return result
            
            elif device.platform == DevicePlatform.ANDROID:
                response = await client.post(
                    f"{self.node_urls['auto_control']}/input",
                    json={
                        "device_id": device_id,
                        "platform": "android",
                        "text": text
                    }
                )
                result = response.json()
                logger.info(f"Android input: {text[:20]}... -> {result}")
                return result
            
            else:
                return {"success": False, "error": f"Unsupported platform: {device.platform}"}
        
        except Exception as e:
            logger.error(f"Input failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def scroll(
        self,
        device_id: str,
        direction: str = "down",
        amount: int = 500
    ) -> Dict[str, Any]:
        """
        滚动屏幕
        
        真正执行：
        - Windows: pyautogui.scroll(amount)
        - Android: AccessibilityService.swipe()
        """
        device = self.get_device(device_id)
        if not device:
            return {"success": False, "error": "Device not found"}
        
        try:
            client = await self._get_client()
            
            if device.platform == DevicePlatform.WINDOWS:
                scroll_amount = amount if direction == "down" else -amount
                response = await client.post(
                    f"{self.node_urls['auto_control']}/scroll",
                    json={
                        "device_id": device_id,
                        "platform": "windows",
                        "amount": scroll_amount
                    }
                )
                result = response.json()
                logger.info(f"Windows scroll: {direction} -> {result}")
                return result
            
            elif device.platform == DevicePlatform.ANDROID:
                response = await client.post(
                    f"{self.node_urls['auto_control']}/scroll",
                    json={
                        "device_id": device_id,
                        "platform": "android",
                        "direction": direction
                    }
                )
                result = response.json()
                logger.info(f"Android scroll: {direction} -> {result}")
                return result
            
            else:
                return {"success": False, "error": f"Unsupported platform: {device.platform}"}
        
        except Exception as e:
            logger.error(f"Scroll failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def screenshot(self, device_id: str) -> Dict[str, Any]:
        """
        截图
        
        真正执行：
        - Windows: pyautogui.screenshot()
        - Android: AccessibilityService.takeScreenshot()
        """
        device = self.get_device(device_id)
        if not device:
            return {"success": False, "error": "Device not found"}
        
        try:
            client = await self._get_client()
            
            # 尝试调用截图接口
            response = await client.post(
                f"{self.node_urls['auto_control']}/screenshot",
                json={
                    "device_id": device_id,
                    "platform": device.platform.value
                }
            )
            result = response.json()
            logger.info(f"Screenshot: {device_id} -> {result.get('success', False)}")
            return result
        
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def open_app(
        self,
        device_id: str,
        app_name: str
    ) -> Dict[str, Any]:
        """
        打开应用

        Windows path: prefer System API facade (launch_app) before
        falling back to the Node_45_Desktop HTTP API.
        Android path: adb shell am start / Intent (unchanged).
        """
        device = self.get_device(device_id)
        if not device:
            return {"success": False, "error": "Device not found"}

        try:
            # ----------------------------------------------------------------
            # Windows fast-path: use System API facade
            # ----------------------------------------------------------------
            if device.platform == DevicePlatform.WINDOWS:
                try:
                    from core.system_api.windows_system_api import (  # type: ignore[import]
                        get_windows_system_api,
                    )
                    facade = get_windows_system_api()
                    if facade.is_available:
                        resp = facade.dispatch(
                            "launch_app",
                            {"target": app_name},
                            device_id=device_id,
                        )
                        if resp.handled:
                            logger.info(
                                "device_control | open_app via system_api | "
                                "device=%s app=%s success=%s",
                                device_id, app_name, resp.success,
                            )
                            return {"success": resp.success, "error": resp.error, **resp.data}
                except Exception as _sapi_err:
                    logger.debug(
                        "device_control | system_api open_app fallback | %s", _sapi_err
                    )

                # Fallback: Node_45_Desktop HTTP API
                client = await self._get_client()
                app_paths = {
                    "微信": "C:\\Program Files\\Tencent\\WeChat\\WeChat.exe",
                    "浏览器": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                }
                app_path = app_paths.get(app_name)
                if app_path:
                    response = await client.post(
                        f"{self.node_urls['desktop']}/open_app",
                        json={"app_path": app_path}
                    )
                    result = response.json()
                else:
                    result = {"success": True, "message": f"App {app_name} not configured"}
                logger.info("Windows open_app (node fallback): %s -> %s", app_name, result)
                return result

            # ----------------------------------------------------------------
            # Android path (unchanged)
            # ----------------------------------------------------------------
            client = await self._get_client()
            app_packages = {
                "微信": "com.tencent.mm",
                "淘宝": "com.taobao.taobao",
                "抖音": "com.ss.android.ugc.aweme",
                "QQ": "com.tencent.mobileqq",
                "支付宝": "com.eg.android.AlipayGphone",
                "浏览器": "com.android.browser",
                "设置": "com.android.settings",
            }
            if device.platform == DevicePlatform.ANDROID:
                package = app_packages.get(app_name, app_name)
                response = await client.post(
                    f"{self.node_urls['adb']}/start_app",
                    json={"device_id": device_id, "package": package}
                )
                result = response.json()
                logger.info("Android open_app: %s (%s) -> %s", app_name, package, result)
                return result

            return {"success": False, "error": f"Unsupported platform: {device.platform}"}

        except Exception as e:
            logger.error(f"Open app failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def press_key(
        self,
        device_id: str,
        key: str
    ) -> Dict[str, Any]:
        """
        按键
        
        真正执行：
        - Windows: pyautogui.press(key)
        - Android: adb shell input keyevent
        """
        device = self.get_device(device_id)
        if not device:
            return {"success": False, "error": "Device not found"}
        
        try:
            client = await self._get_client()
            
            response = await client.post(
                f"{self.node_urls['auto_control']}/press_key",
                json={
                    "device_id": device_id,
                    "platform": device.platform.value,
                    "key": key
                }
            )
            result = response.json()
            logger.info(f"Press key: {key} -> {result}")
            return result
        
        except Exception as e:
            logger.error(f"Press key failed: {e}")
            return {"success": False, "error": str(e)}
    
    # =========================================================================
    # 跨设备控制
    # =========================================================================
    
    async def control_device(
        self,
        from_device_id: str,
        to_device_id: str,
        action: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        跨设备控制
        
        从一个设备控制另一个设备：
        - 从 Android 控制 Windows
        - 从 Windows 控制 Android
        - 从任何设备控制任何设备
        """
        # 获取目标设备
        to_device = self.get_device(to_device_id)
        if not to_device:
            return {"success": False, "error": "Target device not found"}
        
        # 执行操作
        if action == "click":
            return await self.click(
                to_device_id,
                params.get("x", 0),
                params.get("y", 0),
                params.get("clicks", 1)
            )
        elif action == "input":
            return await self.input_text(
                to_device_id,
                params.get("text", "")
            )
        elif action == "scroll":
            return await self.scroll(
                to_device_id,
                params.get("direction", "down"),
                params.get("amount", 500)
            )
        elif action == "screenshot":
            return await self.screenshot(to_device_id)
        elif action == "open_app":
            return await self.open_app(
                to_device_id,
                params.get("app_name", "")
            )
        else:
            return {"success": False, "error": f"Unknown action: {action}"}


# 全局实例
device_control = DeviceControlService()
