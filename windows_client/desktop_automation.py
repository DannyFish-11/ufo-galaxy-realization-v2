# DEPRECATED — Legacy pyautogui-based desktop automation
#
# This module is no longer an active primary path.  Coordinate-based GUI
# automation is handled as a fallback level inside WindowsExecutionArbiter.
#
# Active Windows execution path:
#   windows_aip_client.py → WindowsExecutionArbiter → WindowsAutonomyManager
#
# See docs/WINDOWS_EXECUTION_PIPELINE.md.
import warnings
warnings.warn(
    "desktop_automation.py is deprecated.  GUI automation is now a fallback "
    "level inside WindowsExecutionArbiter.  Use windows_aip_client.py.  "
    "See docs/WINDOWS_EXECUTION_PIPELINE.md.",
    DeprecationWarning,
    stacklevel=1,
)

import pyautogui
import time
import os
import io
import base64
from typing import Dict, Any

# pyautogui 安全配置: 允许操作全屏幕
pyautogui.FAILSAFE = True  # 鼠标移到左上角可紧急停止


def capture_screen_and_encode(filename: str = "screenshot.png") -> str:
    """
    捕获整个屏幕，保存为 PNG 文件，并返回 Base64 编码字符串。
    依赖: pyautogui + Pillow (PIL)
    """
    print("[Desktop Automation] Capturing screen...")
    try:
        screenshot = pyautogui.screenshot()
        screenshot.save(filename)
        # 编码为 base64
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        encoded = base64.b64encode(buf.getvalue()).decode("utf-8")
        print(f"[Desktop Automation] Screen captured: {screenshot.size[0]}x{screenshot.size[1]}, "
              f"file={filename}, base64 len={len(encoded)}")
        return encoded
    except Exception as e:
        print(f"[Desktop Automation] Screenshot failed ({e}), returning empty string")
        return ""


def execute_desktop_action(action_data: Dict) -> Dict:
    """
    根据 AI 返回的指令执行桌面操作。
    使用 pyautogui 执行真实的鼠标/键盘操作。
    """
    action = action_data.get("action")
    target = action_data.get("target")
    coordinates = action_data.get("coordinates")

    print(f"[Desktop Automation] Executing action: {action} on {target} at {coordinates}")

    try:
        if action == "click" and coordinates:
            x, y = int(coordinates[0]), int(coordinates[1])
            pyautogui.click(x, y)
            print(f"[PyAutoGUI] Clicked at ({x}, {y})")
            return {"status": "success", "details": f"Clicked on {target} at ({x}, {y})"}

        elif action == "type" and action_data.get("text"):
            text = action_data["text"]
            # 如果有坐标，先点击聚焦
            if coordinates:
                pyautogui.click(int(coordinates[0]), int(coordinates[1]))
                time.sleep(0.2)
            pyautogui.typewrite(text, interval=0.03) if text.isascii() else \
                pyautogui.write(text)
            print(f"[PyAutoGUI] Typed '{text}' into {target}")
            return {"status": "success", "details": f"Typed text into {target}"}

        elif action == "hotkey" and action_data.get("keys"):
            keys = action_data["keys"]
            pyautogui.hotkey(*keys)
            print(f"[PyAutoGUI] Hotkey {'+'.join(keys)}")
            return {"status": "success", "details": f"Hotkey {'+'.join(keys)}"}

        elif action == "drag" and coordinates and action_data.get("end_coordinates"):
            sx, sy = int(coordinates[0]), int(coordinates[1])
            ex, ey = int(action_data["end_coordinates"][0]), int(action_data["end_coordinates"][1])
            pyautogui.moveTo(sx, sy)
            pyautogui.dragTo(ex, ey, duration=0.5)
            print(f"[PyAutoGUI] Dragged from ({sx},{sy}) to ({ex},{ey})")
            return {"status": "success", "details": "Drag operation complete."}

        elif action == "scroll" and action_data.get("amount"):
            amount = int(action_data["amount"])
            if coordinates:
                pyautogui.click(int(coordinates[0]), int(coordinates[1]))
            pyautogui.scroll(amount)
            return {"status": "success", "details": f"Scrolled {amount}"}

        elif action == "none":
            return {"status": "success", "details": action_data.get("reason", "No action required by AI.")}

        else:
            return {"status": "failure", "details": f"Unknown or incomplete action data: {action_data}"}

    except Exception as e:
        return {"status": "failure", "details": f"PyAutoGUI execution failed: {e}"}


def process_visual_command(prompt: str, server_url: str = None) -> Dict:
    """
    处理一个需要视觉理解的命令。
    1. 截图并编码
    2. 发送到 Galaxy 服务端 /api/v1/vision/understand 获取 AI 分析
    3. 执行 AI 返回的动作

    如果服务端不可达，降级到本地规则匹配。
    """
    screenshot_b64 = capture_screen_and_encode()

    # 尝试发送到服务端 AI 分析
    if server_url and screenshot_b64:
        try:
            import requests
            resp = requests.post(
                f"{server_url}/api/v1/vision/understand",
                json={"image_base64": screenshot_b64, "prompt": prompt},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success") and data.get("result"):
                    action_data = data["result"].get("action", {})
                    if action_data and action_data.get("action") != "none":
                        print(f"[Desktop Automation] Server AI returned action: {action_data}")
                        return execute_desktop_action(action_data)
        except Exception as e:
            print(f"[Desktop Automation] Server analysis failed ({e}), falling back to local rules")

    # 本地保底规则
    if "浏览器" in prompt or "browser" in prompt.lower():
        action_data = {
            "action": "hotkey",
            "target": "browser",
            "keys": ["win", "r"]  # 先打开运行，后续可改为直接打开
        }
    elif "记事本" in prompt or "notepad" in prompt.lower():
        action_data = {
            "action": "hotkey",
            "target": "notepad",
            "keys": ["win", "r"]
        }
    else:
        action_data = {"action": "none", "reason": f"Could not identify target from: {prompt}"}

    return execute_desktop_action(action_data)


if __name__ == "__main__":
    print("--- Test: Capture Screen ---")
    b64 = capture_screen_and_encode()
    print(f"Screenshot base64 length: {len(b64)}")

    print("\n--- Test: Open Browser ---")
    result = process_visual_command("请帮我点击桌面上的浏览器图标")
    print(f"Final Result: {result}")
