import asyncio
import websockets
import json
import time
import os
from typing import Dict, Any
from pixverse_adapter import run_node_48_main

# --- Configuration ---
TAILSCALE_IP = os.environ.get("TAILSCALE_IP", "100.100.100.100") 
NODE_50_URL = os.environ.get("NODE_50_URL", f"ws://{TAILSCALE_IP}:8050")
DEVICE_ID = os.environ.get("DEVICE_ID", "Node_48_MediaGen")
WS_URL = f"{NODE_50_URL}/ws/ufo3/{DEVICE_ID}"

# --- AIP Communication Functions ---

async def send_aip_message(websocket, message_type: str, payload: dict):
    """异步构造并发送 AIP 消息"""
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

async def handle_aip_message(websocket, message: str):
    """处理接收到的 AIP 消息"""
    try:
        data = json.loads(message)
        msg_type = data.get("type")
        
        if msg_type == "command":
            print(f"<- Received command: {data['payload']['command']}")
            
            # 运行 Node 48 的核心逻辑
            result = run_node_48_main(data)
            
            # 发送执行结果
            await send_aip_message(
                websocket, 
                "command_result", 
                {"command": data['payload']['command'], "status": result.get("status", "success"), "details": result}
            )
            
        elif msg_type == "status_request":
            # 模拟发送 Node 48 状态
            await send_aip_message(
                websocket, 
                "status_update", 
                {"service": "PixVerse.ai", "status": "Ready", "capabilities": ["generate_video", "generate_image"]}
            )
            
        else:
            print(f"   Unhandled message type: {msg_type}")
            
    except json.JSONDecodeError:
        print(f"Error decoding JSON: {message}")
    except Exception as e:
        print(f"Error handling message: {e}")

async def client_main():
    """Node 48 (MediaGen) 客户端主函数"""
    print(f"Node 48 MediaGen connecting to UFO³ Galaxy Node 50 at {WS_URL}...")
    
    while True:
        try:
            async with websockets.connect(WS_URL) as websocket:
                print("Connection established. Sending registration message.")
                
                # 1. 发送注册消息
                await send_aip_message(
                    websocket, 
                    "registration", 
                    {"device_type": "Media_Generator_Agent", "capabilities": ["generate_video", "generate_image"]}
                )
                
                # 2. 持续监听消息
                while True:
                    message = await websocket.recv()
                    await handle_aip_message(websocket, message)
                    
        except websockets.exceptions.ConnectionClosedOK:
            print("Connection closed gracefully. Reconnecting in 5 seconds...")
        except ConnectionRefusedError:
            print("Connection refused. Node 50 might be down. Retrying in 5 seconds...")
        except Exception as e:
            print(f"An unexpected error occurred: {e}. Retrying in 5 seconds...")
            
        await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(client_main())
    except KeyboardInterrupt:
        print("\nClient stopped by user.")
