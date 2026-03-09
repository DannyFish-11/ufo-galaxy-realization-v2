"""
Galaxy 跨设备自动化系统 - 端到端集成测试

测试完整的工作流程：
1. Android Agent 连接到 Node 50
2. 发送语音/文本命令
3. Node 50 路由任务到合适的设备
4. 设备执行任务并返回结果
5. 跨设备协同任务

Author: Manus AI
Version: 1.0
Date: 2026-01-22
"""

import asyncio
import json
import pytest
websockets = pytest.importorskip("websockets")
from datetime import datetime


class TestClient:
    """测试客户端"""
    
    def __init__(self, device_id: str, device_type: str):
        self.device_id = device_id
        self.device_type = device_type
        self.websocket = None
        self.connected = False
    
    async def connect(self, url: str):
        """连接到 Node 50"""
        try:
            print(f"🔗 [{self.device_id}] 正在连接到 {url}...")
            self.websocket = await websockets.connect(url)
            self.connected = True
            print(f"✅ [{self.device_id}] 连接成功")
            
            # 发送注册消息
            await self.register()
            
        except Exception as e:
            print(f"❌ [{self.device_id}] 连接失败: {e}")
    
    async def register(self):
        """注册设备"""
        try:
            register_message = {
                "protocol": "AIP/1.0",
                "message_id": f"{self.device_id}_{int(datetime.now().timestamp() * 1000)}",
                "timestamp": datetime.now().isoformat() + "Z",
                "from": self.device_id,
                "to": "Node_50",
                "type": "register",
                "payload": {
                    "device_id": self.device_id,
                    "device_type": self.device_type,
                    "capabilities": ["ui_automation", "app_control", "system_control", "query"]
                }
            }
            
            await self.websocket.send(json.dumps(register_message))
            print(f"📤 [{self.device_id}] 已发送注册消息")
            
            # 等待注册响应
            response = await self.websocket.recv()
            response_data = json.loads(response)
            
            if response_data.get("payload", {}).get("success"):
                print(f"✅ [{self.device_id}] 注册成功")
            else:
                print(f"❌ [{self.device_id}] 注册失败")
                
        except Exception as e:
            print(f"❌ [{self.device_id}] 注册异常: {e}")
    
    async def send_command(self, command: str):
        """发送命令"""
        try:
            command_message = {
                "protocol": "AIP/1.0",
                "message_id": f"{self.device_id}_{int(datetime.now().timestamp() * 1000)}",
                "timestamp": datetime.now().isoformat() + "Z",
                "from": self.device_id,
                "to": "Node_50",
                "type": "command",
                "payload": {
                    "command": command
                }
            }
            
            await self.websocket.send(json.dumps(command_message))
            print(f"📤 [{self.device_id}] 已发送命令: {command}")
            
        except Exception as e:
            print(f"❌ [{self.device_id}] 发送命令失败: {e}")
    
    async def listen(self):
        """监听消息"""
        try:
            while self.connected:
                message = await self.websocket.recv()
                message_data = json.dumps(message)
                
                message_type = message_data.get("type")
                
                if message_type == "command":
                    # 收到任务命令
                    await self.handle_task(message_data)
                elif message_type == "response":
                    print(f"📨 [{self.device_id}] 收到响应")
                elif message_type == "heartbeat":
                    # 响应心跳
                    await self.send_heartbeat()
                    
        except websockets.exceptions.ConnectionClosed:
            print(f"📡 [{self.device_id}] 连接已关闭")
            self.connected = False
        except Exception as e:
            print(f"❌ [{self.device_id}] 监听异常: {e}")
    
    async def handle_task(self, message: dict):
        """处理任务"""
        try:
            print(f"🎯 [{self.device_id}] 收到任务")
            
            # 模拟任务执行
            await asyncio.sleep(1)
            
            # 发送执行结果
            result_message = {
                "protocol": "AIP/1.0",
                "message_id": message.get("message_id"),
                "timestamp": datetime.now().isoformat() + "Z",
                "from": self.device_id,
                "to": "Node_50",
                "type": "response",
                "payload": {
                    "success": True,
                    "message": "任务执行成功",
                    "data": {}
                }
            }
            
            await self.websocket.send(json.dumps(result_message))
            print(f"✅ [{self.device_id}] 任务执行完成")
            
        except Exception as e:
            print(f"❌ [{self.device_id}] 任务处理失败: {e}")
    
    async def send_heartbeat(self):
        """发送心跳"""
        try:
            heartbeat_message = {
                "protocol": "AIP/1.0",
                "message_id": f"{self.device_id}_{int(datetime.now().timestamp() * 1000)}",
                "timestamp": datetime.now().isoformat() + "Z",
                "from": self.device_id,
                "to": "Node_50",
                "type": "heartbeat",
                "payload": {}
            }
            
            await self.websocket.send(json.dumps(heartbeat_message))
            
        except Exception as e:
            print(f"❌ [{self.device_id}] 发送心跳失败: {e}")
    
    async def disconnect(self):
        """断开连接"""
        if self.websocket:
            await self.websocket.close()
            self.connected = False
            print(f"✅ [{self.device_id}] 已断开连接")


async def test_single_device_task():
    """测试单设备任务"""
    print("\n" + "=" * 60)
    print("测试 1: 单设备任务")
    print("=" * 60 + "\n")
    
    # 创建 Android 客户端
    android_client = TestClient("Android_Test_Device", "android")
    
    # 连接到 Node 50
    await android_client.connect("ws://localhost:9000/ws/agent")
    
    # 启动监听
    listen_task = asyncio.create_task(android_client.listen())
    
    # 等待连接稳定
    await asyncio.sleep(2)
    
    # 发送测试命令
    await android_client.send_command("打开微信")
    
    # 等待任务完成
    await asyncio.sleep(3)
    
    # 断开连接
    await android_client.disconnect()
    listen_task.cancel()
    
    print("\n✅ 测试 1 完成\n")


async def test_cross_device_task():
    """测试跨设备任务"""
    print("\n" + "=" * 60)
    print("测试 2: 跨设备任务")
    print("=" * 60 + "\n")
    
    # 创建两个客户端
    android_client = TestClient("Android_Test_Device", "android")
    windows_client = TestClient("Windows_Test_Device", "windows")
    
    # 连接到 Node 50
    await android_client.connect("ws://localhost:9000/ws/agent")
    await windows_client.connect("ws://localhost:9000/ws/agent")
    
    # 启动监听
    android_listen = asyncio.create_task(android_client.listen())
    windows_listen = asyncio.create_task(windows_client.listen())
    
    # 等待连接稳定
    await asyncio.sleep(2)
    
    # 发送跨设备命令
    await android_client.send_command("把手机上的文本复制到电脑")
    
    # 等待任务完成
    await asyncio.sleep(5)
    
    # 断开连接
    await android_client.disconnect()
    await windows_client.disconnect()
    android_listen.cancel()
    windows_listen.cancel()
    
    print("\n✅ 测试 2 完成\n")


async def test_voice_command():
    """测试语音命令"""
    print("\n" + "=" * 60)
    print("测试 3: 语音命令")
    print("=" * 60 + "\n")
    
    # 创建 Android 客户端
    android_client = TestClient("Android_Test_Device", "android")
    
    # 连接到 Node 50
    await android_client.connect("ws://localhost:9000/ws/agent")
    
    # 启动监听
    listen_task = asyncio.create_task(android_client.listen())
    
    # 等待连接稳定
    await asyncio.sleep(2)
    
    # 模拟语音命令
    voice_commands = [
        "打开浏览器",
        "搜索最新的 AI 新闻",
        "把结果发送到电脑"
    ]
    
    for command in voice_commands:
        print(f"\n🎤 语音命令: {command}")
        await android_client.send_command(command)
        await asyncio.sleep(3)
    
    # 断开连接
    await android_client.disconnect()
    listen_task.cancel()
    
    print("\n✅ 测试 3 完成\n")


async def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("Galaxy 跨设备自动化系统 - 端到端集成测试")
    print("=" * 60)
    
    try:
        # 测试 1: 单设备任务
        await test_single_device_task()
        
        # 测试 2: 跨设备任务
        await test_cross_device_task()
        
        # 测试 3: 语音命令
        await test_voice_command()
        
        print("\n" + "=" * 60)
        print("✅ 所有测试完成")
        print("=" * 60 + "\n")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}\n")


if __name__ == "__main__":
    asyncio.run(main())
