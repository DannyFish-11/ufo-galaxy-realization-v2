#!/usr/bin/env python3
"""
UFO Galaxy - 设备通信测试
========================

测试设备通信管理器
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def test_device_communication():
    """测试设备通信管理器"""
    print("\n=== 测试设备通信管理器 ===")
    
    try:
        from core.device_communication import device_comm, DeviceMessage, MessageType
        
        # 1. 测试消息格式
        print("\n1. 测试消息格式")
        msg = DeviceMessage(
            type=MessageType.COMMAND,
            action="click",
            payload={"x": 100, "y": 200},
        )
        print(f"  消息: {msg.to_json()}")
        
        parsed = DeviceMessage.from_json(msg.to_json())
        print(f"  解析: type={parsed.type.value}, action={parsed.action}")
        
        # 2. 测试连接管理
        print("\n2. 测试连接管理")
        print(f"  已连接设备: {device_comm.list_connected_devices()}")
        
        # 3. 测试统计
        print("\n3. 测试统计")
        stats = device_comm.get_stats()
        print(f"  统计: {stats}")
        
        print("\n✅ 设备通信管理器测试通过")
        return True
    except Exception as e:
        print(f"❌ 设备通信管理器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试"""
    print("=" * 60)
    print("UFO Galaxy 设备通信测试")
    print("=" * 60)
    
    result = await test_device_communication()
    
    print("\n" + "=" * 60)
    print(f"测试结果: {'通过' if result else '失败'}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
