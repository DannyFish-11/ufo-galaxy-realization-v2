#!/usr/bin/env python3
"""
UFO Galaxy - 设备注册系统测试
============================

测试设备注册管理器
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def test_device_registry():
    """测试设备注册管理器"""
    print("\n=== 测试设备注册管理器 ===")
    
    try:
        from core.device_registry import device_registry, DeviceType, DeviceStatus
        
        # 1. 注册设备
        print("\n1. 注册设备")
        device1 = await device_registry.register(
            device_id="android_001",
            device_type="android",
            name="测试手机",
            capabilities=["screen", "camera", "microphone"],
            groups=["mobile"],
            tags=["test", "demo"],
        )
        print(f"  注册成功: {device1.device_id} ({device1.name})")
        
        device2 = await device_registry.register(
            device_id="windows_001",
            device_type="windows",
            name="测试电脑",
            capabilities=["screen", "keyboard", "mouse"],
            groups=["desktop"],
            tags=["test"],
        )
        print(f"  注册成功: {device2.device_id} ({device2.name})")
        
        # 2. 列出设备
        print("\n2. 列出设备")
        devices = device_registry.list_devices()
        print(f"  总数: {len(devices)}")
        for d in devices:
            print(f"  - {d.device_id}: {d.name} ({d.device_type.value})")
        
        # 3. 发现设备
        print("\n3. 发现设备")
        android_devices = await device_registry.discover(device_type="android")
        print(f"  Android 设备: {len(android_devices)} 个")
        
        screen_devices = await device_registry.discover(capability="screen")
        print(f"  有屏幕的设备: {len(screen_devices)} 个")
        
        mobile_devices = await device_registry.discover(group="mobile")
        print(f"  mobile 分组设备: {len(mobile_devices)} 个")
        
        # 4. 能力协商
        print("\n4. 能力协商")
        device = device_registry.negotiate_capability("camera")
        if device:
            print(f"  找到有 camera 能力的设备: {device.device_id}")
        else:
            print("  未找到有 camera 能力的设备")
        
        # 5. 分组和标签
        print("\n5. 分组和标签")
        print(f"  分组: {list(device_registry.groups.keys())}")
        print(f"  标签: {list(device_registry.tag_index.keys())}")
        print(f"  能力: {list(device_registry.capability_index.keys())}")
        
        # 6. 统计
        print("\n6. 统计")
        stats = device_registry.get_stats()
        print(f"  总设备: {stats['total']}")
        print(f"  在线: {stats['online']}")
        print(f"  离线: {stats['offline']}")
        print(f"  按类型: {stats['by_type']}")
        
        # 7. 注销设备
        print("\n7. 注销设备")
        success = await device_registry.unregister("android_001")
        print(f"  注销 android_001: {success}")
        
        devices = device_registry.list_devices()
        print(f"  剩余设备: {len(devices)}")
        
        print("\n✅ 设备注册管理器测试通过")
        return True
    except Exception as e:
        print(f"❌ 设备注册管理器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试"""
    print("=" * 60)
    print("UFO Galaxy 设备注册系统测试")
    print("=" * 60)
    
    result = await test_device_registry()
    
    print("\n" + "=" * 60)
    print(f"测试结果: {'通过' if result else '失败'}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
