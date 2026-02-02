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

async def handle_aip_message(message: str):
    """处理接收到的 AIP 消息"""
    try:
        data = json.loads(message)
        msg_type = data.get("type")
        payload = data.get("payload", {})
        
        print(f"<- Received {msg_type}")
        
        if msg_type == "command":
            command = payload.get("command")
            params = payload.get("params", {})
            print(f"   Executing command: {command} with params: {params}")
            
            # 模拟执行 Windows 上的操作
            if command == "execute_script":
                script_path = params.get("script_path")
                print(f"   [Windows Action] Running script: {script_path}")
                # 实际应用中，这里会调用 subprocess.run() 等执行本地脚本
                
            elif command == "send_notification":
                title = params.get("title")
                body = params.get("body")
                print(f"   [Windows Action] Displaying notification: {title} - {body}")
                # 实际应用中，这里会调用 Windows API 显示通知
                
            # 模拟发送执行结果
            await send_aip_message(
                websocket, 
                "command_result", 
                {"command": command, "status": "success", "details": f"Command {command} executed on Windows."}
            )
            
        elif msg_type == "display_media":
            # 新增：显示媒体文件（视频/图片）
            media_url = payload.get("url")
            media_type = payload.get("media_type", "video")
            print(f"   [Windows Action] Displaying {media_type} from URL: {media_url}")
            # 实际应用中，这里会调用默认浏览器或媒体播放器打开 URL
            
            await send_aip_message(
                websocket, 
                "command_result", 
                {"command": "display_media", "status": "success", "details": f"Displayed {media_type} from {media_url} on Windows."}
            )
            
        elif msg_type == "visual_action":
            # 新增：基于视觉的桌面操作
            prompt = payload.get("prompt", "请执行默认操作")
            print(f"   Executing visual action for prompt: {prompt}")
            
            # 调用桌面自动化模块处理视觉命令
            result = process_visual_command(prompt)
            
            # 发送视觉操作结果
            await send_aip_message(
                websocket, 
                "command_result", 
                {"command": "visual_action", "status": result["status"], "details": result["details"]}
            )
            
        elif msg_type == "status_request":
            # 模拟发送 Windows 状态
            await send_aip_message(
                websocket, 
                "status_update", 
                {"os": "Windows 11", "cpu_load": 0.45, "memory_usage": 0.60, "is_active": True}
            )
            
        else:
            print(f"   Unhandled message type: {msg_type}")
            
    except json.JSONDecodeError:
        print(f"Error decoding JSON: {message}")
    except Exception as e:
        print(f"Error handling message: {e}")

async def aip_client_logic(node50_url, client_id, ui_app):
    """Windows UFO 客户端主函数"""
    global websocket
    ws_url = f"{node50_url}/ws/ufo3/{client_id}"
    print(f"Connecting to UFO³ Galaxy at {ws_url}...")
    
    while True:
        try:
            async with websockets.connect(ws_url) as websocket:
                print("Connection established. Sending registration...")
                
                # 1. 发送注册消息
                await send_aip_message(
                    websocket, 
                    "registration", 
                    {"device_type": "Windows_Client", "capabilities": ["execute_script", "send_notification", "status_update"]}
                )
                
                # 2. 持续监听消息
                while True:
                    message = await websocket.recv()
                    await handle_aip_message(message)
                    
        except websockets.exceptions.ConnectionClosedOK:
            print("Connection closed gracefully. Reconnecting in 5 seconds...")
        except ConnectionRefusedError:
            print("Connection refused. Node 50 might be down. Retrying in 5 seconds...")
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
