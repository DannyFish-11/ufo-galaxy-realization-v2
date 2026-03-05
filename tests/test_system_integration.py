#!/usr/bin/env python3
"""
UFO Galaxy - 系统集成测试
========================

测试系统集成层
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def test_system_integration():
    """测试系统集成"""
    print("\n=== 测试系统集成 ===")
    
    try:
        from core.system_integration import system, CapabilityType
        
        # 1. 初始化
        print("\n1. 初始化系统")
        await system.initialize()
        
        # 2. 列出能力
        print("\n2. 列出能力")
        caps = system.list_capabilities()
        print(f"  总数: {len(caps)}")
        
        # 按类型统计
        stats = system.get_stats()
        print(f"  按类型: {stats['by_type']}")
        
        # 3. 注册自定义能力
        print("\n3. 注册自定义能力")
        
        async def my_handler(**params):
            return {"result": f"处理完成: {params}"}
        
        cap = system.register_capability(
            id="custom_test",
            name="test_capability",
            type=CapabilityType.BUILTIN,
            description="测试能力",
            handler=my_handler,
        )
        print(f"  注册成功: {cap.id}")
        
        # 4. 发现能力
        print("\n4. 发现能力")
        found = await system.discover_capability("test_capability")
        if found:
            print(f"  找到: {found.id} ({found.type.value})")
        else:
            print("  未找到")
        
        # 5. 执行能力
        print("\n5. 执行能力")
        try:
            result = await system.execute("test_capability", param1="value1")
            print(f"  结果: {result}")
        except Exception as e:
            print(f"  执行失败: {e}")
        
        # 6. 统计
        print("\n6. 统计")
        stats = system.get_stats()
        print(f"  总能力: {stats['total_capabilities']}")
        print(f"  按类型: {stats['by_type']}")
        
        print("\n✅ 系统集成测试通过")
        return True
    except Exception as e:
        print(f"❌ 系统集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试"""
    print("=" * 60)
    print("UFO Galaxy 系统集成测试")
    print("=" * 60)
    
    result = await test_system_integration()
    
    print("\n" + "=" * 60)
    print(f"测试结果: {'通过' if result else '失败'}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
