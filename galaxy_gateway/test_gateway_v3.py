"""
UFO³ Galaxy Gateway v3.0 - 综合测试脚本

测试内容：
1. AIP v2.0 协议
2. 多模态传输
3. P2P 通信
4. 断点续传
5. 完整的端到端流程

作者：Manus AI
日期：2026-01-22
版本：1.0
"""

import asyncio
import json
import time
from pathlib import Path

# 导入测试模块
from aip_protocol_v2 import MessageBuilder, DeviceInfo, MessageCodec
from multimodal_transfer import MultimodalTransferManager
from p2p_connector import P2PConnector, PeerInfo
from resumable_transfer import ResumableTransferManager

# ============================================================================
# 测试结果
# ============================================================================

class TestResults:
    """测试结果"""
    
    def __init__(self):
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.errors = []
    
    def add_result(self, test_name: str, passed: bool, error: str = None):
        """添加测试结果"""
        self.total += 1
        if passed:
            self.passed += 1
            print(f"✅ {test_name}")
        else:
            self.failed += 1
            print(f"❌ {test_name}")
            if error:
                print(f"   错误: {error}")
                self.errors.append(f"{test_name}: {error}")
    
    def print_summary(self):
        """打印汇总"""
        print("\n" + "="*80)
        print("测试汇总")
        print("="*80)
        print(f"总测试数: {self.total}")
        print(f"通过: {self.passed}")
        print(f"失败: {self.failed}")
        print(f"成功率: {self.passed/self.total*100:.1f}%")
        
        if self.errors:
            print("\n错误列表:")
            for error in self.errors:
                print(f"  - {error}")

# ============================================================================
# 测试函数
# ============================================================================

async def test_aip_protocol(results: TestResults):
    """测试 AIP v2.0 协议"""
    print("\n" + "="*80)
    print("测试 AIP v2.0 协议")
    print("="*80)
    
    # 测试 1: 创建控制消息
    try:
        phone_a = DeviceInfo(
            device_id="phone_a",
            device_name="手机A",
            device_type="android",
            ip_address="192.168.1.100"
        )
        
        pc = DeviceInfo(
            device_id="pc",
            device_name="电脑",
            device_type="windows",
            ip_address="192.168.1.10"
        )
        
        msg = MessageBuilder.create_control_message(
            from_device=phone_a,
            to_device=pc,
            command="open_app",
            parameters={"app": "chrome"}
        )
        
        assert msg.message_id is not None
        assert msg.from_device.device_id == "phone_a"
        assert msg.to_device.device_id == "pc"
        
        results.add_result("AIP: 创建控制消息", True)
    except Exception as e:
        results.add_result("AIP: 创建控制消息", False, str(e))
    
    # 测试 2: 消息编解码
    try:
        encoded = MessageCodec.encode(msg)
        decoded = MessageCodec.decode(encoded)
        
        assert decoded.message_id == msg.message_id
        assert decoded.from_device.device_id == msg.from_device.device_id
        
        results.add_result("AIP: 消息编解码", True)
    except Exception as e:
        results.add_result("AIP: 消息编解码", False, str(e))
    
    # 测试 3: 消息验证
    try:
        valid, error = MessageCodec.validate(msg)
        assert valid
        
        results.add_result("AIP: 消息验证", True)
    except Exception as e:
        results.add_result("AIP: 消息验证", False, str(e))

async def test_multimodal_transfer(results: TestResults):
    """测试多模态传输"""
    print("\n" + "="*80)
    print("测试多模态传输")
    print("="*80)
    
    manager = MultimodalTransferManager()
    
    phone_a = DeviceInfo(
        device_id="phone_a",
        device_name="手机A",
        device_type="android",
        ip_address="192.168.1.100"
    )
    
    pc = DeviceInfo(
        device_id="pc",
        device_name="电脑",
        device_type="windows",
        ip_address="192.168.1.10"
    )
    
    # 测试 1: 图片传输
    try:
        from PIL import Image
        import io
        
        # 创建测试图片
        img = Image.new('RGB', (100, 100), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        img_data = img_bytes.getvalue()
        
        msg = await manager.send_image(
            from_device=phone_a,
            to_device=pc,
            image_data=img_data
        )
        
        assert msg.message_type.value == "image"
        assert msg.payload.size > 0
        
        results.add_result("多模态: 图片传输", True)
    except Exception as e:
        results.add_result("多模态: 图片传输", False, str(e))
    
    # 测试 2: 音频传输
    try:
        audio_data = b"fake_audio_data" * 100
        
        msg = await manager.send_audio(
            from_device=phone_a,
            to_device=pc,
            audio_data=audio_data,
            format="mp3"
        )
        
        assert msg.message_type.value == "audio"
        assert msg.payload.size > 0
        
        results.add_result("多模态: 音频传输", True)
    except Exception as e:
        results.add_result("多模态: 音频传输", False, str(e))
    
    # 测试 3: 文件传输
    try:
        import tempfile
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"x" * (5 * 1024 * 1024))  # 5MB
            temp_file = f.name
        
        msg = await manager.send_file(
            from_device=phone_a,
            to_device=pc,
            file_path=temp_file
        )
        
        assert msg.message_type.value == "file"
        assert msg.payload.chunks > 0
        
        # 清理
        import os
        os.remove(temp_file)
        
        results.add_result("多模态: 文件传输", True)
    except Exception as e:
        results.add_result("多模态: 文件传输", False, str(e))

async def test_p2p_connection(results: TestResults):
    """测试 P2P 连接"""
    print("\n" + "="*80)
    print("测试 P2P 连接")
    print("="*80)
    
    # 测试 1: 创建 P2P 连接器
    try:
        device_a = PeerInfo(
            device_id="device_a",
            device_name="设备A",
            local_ip="127.0.0.1",
            local_port=9001
        )
        
        connector = P2PConnector(device_a)
        await connector.start()
        
        # 等待启动
        await asyncio.sleep(0.5)
        
        await connector.stop()
        
        results.add_result("P2P: 创建连接器", True)
    except Exception as e:
        results.add_result("P2P: 创建连接器", False, str(e))
    
    # 测试 2: 局域网连接
    try:
        device_a = PeerInfo(
            device_id="device_a",
            device_name="设备A",
            local_ip="127.0.0.1",
            local_port=9001
        )
        
        device_b = PeerInfo(
            device_id="device_b",
            device_name="设备B",
            local_ip="127.0.0.1",
            local_port=9002
        )
        
        connector_a = P2PConnector(device_a)
        connector_b = P2PConnector(device_b)
        
        await connector_a.start()
        await connector_b.start()
        
        # 等待启动
        await asyncio.sleep(0.5)
        
        # 连接
        success = await connector_a.connect(device_b)
        
        assert success
        
        # 清理
        await connector_a.stop()
        await connector_b.stop()
        
        results.add_result("P2P: 局域网连接", True)
    except Exception as e:
        results.add_result("P2P: 局域网连接", False, str(e))

async def test_resumable_transfer(results: TestResults):
    """测试断点续传"""
    print("\n" + "="*80)
    print("测试断点续传")
    print("="*80)
    
    manager = ResumableTransferManager()
    
    # 测试 1: 创建传输会话
    try:
        import tempfile
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"x" * (10 * 1024 * 1024))  # 10MB
            temp_file = f.name
        
        session = manager.create_session(
            session_id="test_session",
            file_path=temp_file
        )
        
        assert session.session_id == "test_session"
        assert session.file_size == 10 * 1024 * 1024
        assert len(session.chunks) > 0
        
        # 清理
        import os
        os.remove(temp_file)
        manager.delete_session("test_session")
        
        results.add_result("断点续传: 创建会话", True)
    except Exception as e:
        results.add_result("断点续传: 创建会话", False, str(e))
    
    # 测试 2: 文件传输
    try:
        import tempfile
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            f.write(b"x" * (5 * 1024 * 1024))  # 5MB
            temp_file = f.name
        
        session = manager.create_session(
            session_id="test_transfer",
            file_path=temp_file
        )
        
        # 模拟发送
        async def mock_send(chunk_index: int, chunk_data: bytes):
            await asyncio.sleep(0.001)
        
        success = await manager.send_file(
            session_id="test_transfer",
            send_chunk_callback=mock_send
        )
        
        assert success
        assert session.state.value == "completed"
        
        # 清理
        import os
        os.remove(temp_file)
        manager.delete_session("test_transfer")
        
        results.add_result("断点续传: 文件传输", True)
    except Exception as e:
        results.add_result("断点续传: 文件传输", False, str(e))

# ============================================================================
# 主测试函数
# ============================================================================

async def run_all_tests():
    """运行所有测试"""
    print("="*80)
    print("UFO³ Galaxy Gateway v3.0 - 综合测试")
    print("="*80)
    print(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    results = TestResults()
    
    # 运行测试
    await test_aip_protocol(results)
    await test_multimodal_transfer(results)
    await test_p2p_connection(results)
    await test_resumable_transfer(results)
    
    # 打印汇总
    results.print_summary()
    
    return results

# ============================================================================
# 主函数
# ============================================================================

if __name__ == "__main__":
    results = asyncio.run(run_all_tests())
    
    # 退出码
    exit(0 if results.failed == 0 else 1)
