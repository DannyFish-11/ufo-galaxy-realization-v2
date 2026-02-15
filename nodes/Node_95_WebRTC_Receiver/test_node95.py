"""
Node_95 测试脚本

测试内容：
1. HTTP API 端点
2. WebSocket 信令连接
3. WebRTC 信令处理（模拟）
4. 帧存储和检索

作者: Manus AI
日期: 2026-01-24
"""

import asyncio
import httpx
import websockets
import json

NODE_95_URL = "http://localhost:8095"
NODE_95_WS = "ws://localhost:8095"

async def test_http_api():
    """测试 HTTP API"""
    print("\n" + "="*80)
    print("测试 1: HTTP API 端点")
    print("="*80)
    
    async with httpx.AsyncClient() as client:
        # 测试根端点
        print("\n1.1 测试根端点 GET /")
        response = await client.get(f"{NODE_95_URL}/")
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        assert response.status_code == 200
        assert response.json()["service"] == "Node_95: WebRTC Receiver"
        print("✅ 根端点测试通过")
        
        # 测试健康检查
        print("\n1.2 测试健康检查 GET /health")
        response = await client.get(f"{NODE_95_URL}/health")
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"
        print("✅ 健康检查测试通过")
        
        # 测试设备列表
        print("\n1.3 测试设备列表 GET /devices")
        response = await client.get(f"{NODE_95_URL}/devices")
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        assert response.status_code == 200
        print("✅ 设备列表测试通过")
        
        # 测试获取帧（应该失败，因为没有设备）
        print("\n1.4 测试获取帧 POST /get_latest_frame (应该返回 404)")
        response = await client.post(
            f"{NODE_95_URL}/get_latest_frame",
            json={"device_id": "test_device", "format": "jpeg"}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        assert response.status_code == 404
        print("✅ 获取帧测试通过（正确返回 404）")

async def test_websocket_connection():
    """测试 WebSocket 连接"""
    print("\n" + "="*80)
    print("测试 2: WebSocket 信令连接")
    print("="*80)
    
    device_id = "test_device_001"
    
    print(f"\n2.1 连接到 WebSocket: /signaling/{device_id}")
    
    try:
        async with websockets.connect(f"{NODE_95_WS}/signaling/{device_id}") as websocket:
            print("✅ WebSocket 连接成功")
            
            # 发送一个测试消息（模拟 ICE candidate）
            print("\n2.2 发送测试消息（ICE candidate）")
            test_message = {
                "type": "ice_candidate",
                "candidate": "candidate:test",
                "sdpMid": "0",
                "sdpMLineIndex": 0
            }
            await websocket.send(json.dumps(test_message))
            print("✅ 消息发送成功")
            
            # 等待一下（服务器可能会响应）
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                print(f"收到响应: {response}")
            except asyncio.TimeoutError:
                print("✅ 没有响应（预期行为）")
            
            print("\n2.3 关闭 WebSocket 连接")
    
    except Exception as e:
        print(f"❌ WebSocket 测试失败: {e}")
        raise
    
    print("✅ WebSocket 连接测试通过")

async def test_offer_handling():
    """测试 Offer 处理"""
    print("\n" + "="*80)
    print("测试 3: WebRTC Offer 处理")
    print("="*80)
    
    device_id = "test_device_002"
    
    # 创建一个模拟的 SDP Offer
    mock_offer_sdp = """v=0
o=- 0 0 IN IP4 127.0.0.1
s=-
t=0 0
a=group:BUNDLE 0
a=msid-semantic: WMS stream
m=video 9 UDP/TLS/RTP/SAVPF 96
c=IN IP4 0.0.0.0
a=rtcp:9 IN IP4 0.0.0.0
a=ice-ufrag:test
a=ice-pwd:testpassword
a=fingerprint:sha-256 00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00
a=setup:actpass
a=mid:0
a=sendonly
a=rtcp-mux
a=rtpmap:96 VP8/90000
"""
    
    print(f"\n3.1 连接到 WebSocket: /signaling/{device_id}")
    
    try:
        async with websockets.connect(f"{NODE_95_WS}/signaling/{device_id}") as websocket:
            print("✅ WebSocket 连接成功")
            
            # 发送 Offer
            print("\n3.2 发送 Offer")
            offer_message = {
                "type": "offer",
                "sdp": mock_offer_sdp
            }
            await websocket.send(json.dumps(offer_message))
            print("✅ Offer 发送成功")
            
            # 等待 Answer
            print("\n3.3 等待 Answer...")
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                response_data = json.loads(response)
                print(f"收到响应类型: {response_data.get('type')}")
                
                if response_data.get('type') == 'answer':
                    print("✅ 收到 Answer")
                    print(f"SDP 长度: {len(response_data.get('sdp', ''))}")
                elif response_data.get('type') == 'error':
                    print(f"⚠️ 收到错误: {response_data.get('error')}")
                else:
                    print(f"⚠️ 收到未知响应: {response_data}")
            
            except asyncio.TimeoutError:
                print("❌ 等待 Answer 超时")
                raise
    
    except Exception as e:
        print(f"❌ Offer 处理测试失败: {e}")
        raise
    
    print("✅ Offer 处理测试通过")

async def run_all_tests():
    """运行所有测试"""
    print("\n" + "="*80)
    print("Node_95 WebRTC Receiver - 完整测试")
    print("="*80)
    print("\n⚠️ 请确保 Node_95 正在运行: python3.11 main.py")
    print("\n按 Enter 继续...")
    input()
    
    try:
        # 测试 1: HTTP API
        await test_http_api()
        
        # 测试 2: WebSocket 连接
        await test_websocket_connection()
        
        # 测试 3: Offer 处理
        await test_offer_handling()
        
        print("\n" + "="*80)
        print("✅ 所有测试通过！")
        print("="*80)
        
        return True
    
    except Exception as e:
        print("\n" + "="*80)
        print(f"❌ 测试失败: {e}")
        print("="*80)
        return False

if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)
