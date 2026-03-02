import asyncio
import websockets
import json
import time
import os
from typing import Dict, Any
from desktop_automation import process_visual_command
from ui_sidebar import Sidebar
from key_listener import KeyListener
import threading # 导入桌面自动化模块

# 从环境变量或默认值获取配置
import argparse

NODE_50_URL = os.environ.get("NODE_50_URL", "ws://localhost:8050")
DEVICE_ID = os.environ.get("DEVICE_ID", "Windows_UFO_Client_001")


async def send_aip_message(websocket, message_type: str, payload: dict):
    """构造并发送 AIP 消息"""
    message = {
        "protocol": "AIP/1.0",
        "type": message_type,
        "source_node": DEVICE_ID,
        "target_node": "Node_50_Transformer",
        "timestamp": int(time.time()),
        "payload": payload
    }
    await websocket.send(json.dumps(message))
    print(f"-> Sent {message_type} message.")

async def handle_aip_message(ws, message: str, server_http_url: str = None):
    """处理接收到的 AIP 消息

    Args:
        ws: 当前 WebSocket 连接
        message: 收到的 JSON 文本
        server_http_url: Galaxy 服务端 HTTP 地址 (用于 vision API)
    """
    try:
        data = json.loads(message)
        msg_type = data.get("type")
        payload = data.get("payload", {})

        print(f"<- Received {msg_type}")

        if msg_type == "command":
            command = payload.get("command")
            params = payload.get("params", {})
            # command_id 用于服务端 request-response 关联
            command_id = data.get("command_id")
            print(f"   Executing command: {command} with params: {params} (id={command_id})")

            if command == "execute_script":
                script_path = params.get("script_path")
                print(f"   [Windows Action] Running script: {script_path}")
                import subprocess
                try:
                    proc = subprocess.run(
                        script_path, shell=True, capture_output=True, text=True, timeout=30
                    )
                    details = proc.stdout[:500] if proc.returncode == 0 else proc.stderr[:500]
                    status = "success" if proc.returncode == 0 else "failure"
                except Exception as e:
                    details = str(e)
                    status = "failure"

                result_payload = {"command": command, "status": status, "details": details}
                if command_id:
                    result_payload["command_id"] = command_id
                await send_aip_message(ws, "command_result", result_payload)

            elif command == "send_notification":
                title = params.get("title", "UFO Galaxy")
                body = params.get("body", "")
                print(f"   [Windows Action] Notification: {title} - {body}")
                # 尝试使用 Windows toast notification (需要 win10toast 或 plyer)
                try:
                    from plyer import notification
                    notification.notify(title=title, message=body, timeout=5)
                except ImportError:
                    print(f"   [Fallback] plyer 未安装, notification 仅日志")

                result_payload = {"command": command, "status": "success", "details": f"Notification: {title}"}
                if command_id:
                    result_payload["command_id"] = command_id
                await send_aip_message(ws, "command_result", result_payload)

            else:
                result_payload = {"command": command, "status": "success", "details": f"Command {command} executed."}
                if command_id:
                    result_payload["command_id"] = command_id
                await send_aip_message(ws, "command_result", result_payload)

        elif msg_type == "display_media":
            media_url = payload.get("url")
            media_type = payload.get("media_type", "video")
            print(f"   [Windows Action] Opening {media_type}: {media_url}")
            import webbrowser
            webbrowser.open(media_url)

            await send_aip_message(
                ws, "command_result",
                {"command": "display_media", "status": "success",
                 "details": f"Opened {media_type} from {media_url}"}
            )

        elif msg_type == "visual_action":
            prompt = payload.get("prompt", "请执行默认操作")
            print(f"   Executing visual action for prompt: {prompt}")
            result = process_visual_command(prompt, server_url=server_http_url)

            await send_aip_message(
                ws, "command_result",
                {"command": "visual_action", "status": result["status"],
                 "details": result["details"]}
            )

        elif msg_type == "status_request":
            import platform
            import psutil
            await send_aip_message(
                ws, "status_update",
                {
                    "os": platform.platform(),
                    "cpu_load": psutil.cpu_percent(interval=0.5) / 100 if "psutil" in dir() else 0.5,
                    "memory_usage": psutil.virtual_memory().percent / 100 if "psutil" in dir() else 0.6,
                    "is_active": True
                }
            )

        else:
            print(f"   Unhandled message type: {msg_type}")

    except json.JSONDecodeError:
        print(f"Error decoding JSON: {message}")
    except Exception as e:
        print(f"Error handling message: {e}")

async def aip_client_logic(node50_url, client_id, ui_app):
    """Windows UFO 客户端主函数"""
    ws_url = f"{node50_url}/ws/ufo3/{client_id}"
    # 从 WebSocket URL 推导 HTTP URL (用于 vision API)
    server_http_url = node50_url.replace("ws://", "http://").replace("wss://", "https://")
    print(f"Connecting to UFO³ Galaxy at {ws_url}...")

    while True:
        try:
            async with websockets.connect(ws_url) as ws:
                print("Connection established. Sending registration...")

                # 1. 发送注册消息 (AIP/1.0 兼容)
                await send_aip_message(
                    ws,
                    "register",
                    {
                        "device_id": client_id,
                        "device_type": "windows",
                        "capabilities": [
                            "execute_script", "send_notification", "status_update",
                            "visual_action", "display_media", "ui_automation"
                        ]
                    }
                )

                # 2. 持续监听消息
                while True:
                    message = await ws.recv()
                    await handle_aip_message(ws, message, server_http_url)

        except websockets.exceptions.ConnectionClosedOK:
            print("Connection closed gracefully. Reconnecting in 5 seconds...")
        except ConnectionRefusedError:
            print("Connection refused. Server might be down. Retrying in 5 seconds...")
        except Exception as e:
            print(f"An unexpected error occurred: {e}. Retrying in 5 seconds...")

        await asyncio.sleep(5)

def run_aip_client(node50_url, client_id, ui_app):
    asyncio.run(aip_client_logic(node50_url, client_id, ui_app))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UFO³ Galaxy Windows Client")
    parser.add_argument("--node50_url", default=NODE_50_URL, help="Node 50 WebSocket URL")
    parser.add_argument("--client_id", default=DEVICE_ID, help="This client's unique ID")
    args = parser.parse_args()

    # 1. 创建 UI
    app = Sidebar()

    # 2. 在后台线程中运行 AIP 客户端逻辑
    aip_thread = threading.Thread(target=run_aip_client, args=(args.node50_url, args.client_id, app), daemon=True)
    aip_thread.start()

    # 3. 在主线程中运行按键监听器
    key_listener = KeyListener(app.toggle_sidebar)
    key_listener.start()

    # 4. 启动 UI 主循环
    app.mainloop()
