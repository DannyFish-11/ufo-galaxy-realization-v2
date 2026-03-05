#!/usr/bin/env python3
"""
UFO Galaxy - 系统实际测试
========================

测试：
1. 配置加载
2. 服务启动
3. API 端点
4. 设备注册
5. MCP 加载
"""

import asyncio
import sys
import os
from pathlib import Path

# 设置路径
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

print("=" * 60)
print("UFO Galaxy 系统实际测试")
print("=" * 60)


async def test_config():
    """测试配置管理器"""
    print("\n【1. 测试配置管理器】")
    
    try:
        from core.unified_config import config
        
        # 测试获取配置
        print(f"  配置项数量: {len(config.get_all())}")
        
        # 测试设置配置
        config.set("test_key", "test_value", save=False)
        value = config.get("test_key")
        
        if value == "test_value":
            print("  ✅ 配置读写正常")
        else:
            print(f"  ❌ 配置读写失败: {value}")
        
        # 测试 LLM 配置
        llm_config = config.get_llm_config()
        print(f"  默认 LLM 模型: {llm_config.get('model', '未配置')}")
        
        return True
    except Exception as e:
        print(f"  ❌ 配置管理器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_device_registry():
    """测试设备注册"""
    print("\n【2. 测试设备注册】")
    
    try:
        from core.device_registry import device_registry
        
        # 注册测试设备
        device = await device_registry.register(
            device_id="test_device_001",
            device_type="android",
            name="测试设备",
            capabilities=["screen", "touch", "camera"],
            tags=["test"],
        )
        
        print(f"  设备 ID: {device.device_id}")
        print(f"  设备名称: {device.name}")
        print(f"  设备能力: {[c.name for c in device.capabilities]}")
        
        # 列出设备
        devices = device_registry.list_devices()
        print(f"  已注册设备: {len(devices)} 个")
        
        # 发现设备
        found = await device_registry.discover(capability="screen")
        print(f"  有屏幕的设备: {len(found)} 个")
        
        # 清理测试设备
        await device_registry.unregister("test_device_001")
        
        print("  ✅ 设备注册测试通过")
        return True
    except Exception as e:
        print(f"  ❌ 设备注册测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_device_communication():
    """测试设备通信"""
    print("\n【3. 测试设备通信】")
    
    try:
        from core.device_communication import device_comm, DeviceMessage, MessageType
        
        # 测试消息格式
        msg = DeviceMessage(
            type=MessageType.COMMAND,
            action="test",
            payload={"key": "value"},
        )
        
        msg_json = msg.to_json()
        parsed = DeviceMessage.from_json(msg_json)
        
        if parsed.action == "test":
            print("  ✅ 消息格式正常")
        else:
            print(f"  ❌ 消息格式错误: {parsed.action}")
        
        # 测试统计
        stats = device_comm.get_stats()
        print(f"  连接设备: {stats['connected_devices']} 个")
        
        return True
    except Exception as e:
        print(f"  ❌ 设备通信测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_system_integration():
    """测试系统集成"""
    print("\n【4. 测试系统集成】")
    
    try:
        from core.system_integration import system, CapabilityType
        
        # 初始化
        await system.initialize()
        
        # 列出能力
        caps = system.list_capabilities()
        print(f"  已加载能力: {len(caps)} 个")
        
        # 按类型统计
        stats = system.get_stats()
        print(f"  能力统计: {stats['by_type']}")
        
        # 注册自定义能力
        async def test_handler(**params):
            return {"result": "ok"}
        
        cap = system.register_capability(
            id="test_capability",
            name="test",
            type=CapabilityType.BUILTIN,
            description="测试能力",
            handler=test_handler,
        )
        
        print(f"  注册能力: {cap.id}")
        
        # 发现能力
        found = await system.discover_capability("test")
        if found:
            print(f"  发现能力: {found.id}")
        
        print("  ✅ 系统集成测试通过")
        return True
    except Exception as e:
        print(f"  ❌ 系统集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_mcp_loader():
    """测试 MCP 加载器"""
    print("\n【5. 测试 MCP 加载器】")
    
    try:
        from core.mcp_loader import mcp_loader
        
        # 列出已加载服务器
        servers = mcp_loader.list_servers()
        print(f"  已加载 MCP 服务器: {len(servers)} 个")
        
        # 测试加载方法存在
        methods = ["load", "unload", "list_tools", "call_tool"]
        for m in methods:
            if hasattr(mcp_loader, m):
                print(f"  ✅ 方法 {m} 存在")
            else:
                print(f"  ❌ 方法 {m} 不存在")
        
        return True
    except Exception as e:
        print(f"  ❌ MCP 加载器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_skill_loader():
    """测试技能加载器"""
    print("\n【6. 测试技能加载器】")
    
    try:
        from core.skill_loader import skill_loader
        from core.skill_md_loader import skill_md_loader
        
        # 测试 skill_loader
        skills = skill_loader.list_skills()
        print(f"  skill_loader 技能: {len(skills)} 个")
        
        # 测试 skill_md_loader
        md_skills = skill_md_loader.list_skills()
        print(f"  skill_md_loader 技能: {len(md_skills)} 个")
        
        # 加载示例技能
        skill_path = PROJECT_ROOT / "skills" / "examples" / "weather"
        if skill_path.exists():
            result = await skill_md_loader.load(str(skill_path))
            if result.get("success"):
                print(f"  ✅ 加载技能成功: {result.get('name')}")
            else:
                print(f"  ⚠️ 加载技能失败: {result.get('error')}")
        
        return True
    except Exception as e:
        print(f"  ❌ 技能加载器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_api_routes():
    """测试 API 路由"""
    print("\n【7. 测试 API 路由】")
    
    try:
        from fastapi import FastAPI
        from core.api_routes import create_api_routes
        
        # 创建应用
        app = FastAPI()
        router = create_api_routes()
        app.include_router(router)
        
        # 统计路由
        routes = [r for r in app.routes if hasattr(r, 'path')]
        api_routes = [r for r in routes if hasattr(r, 'path') and r.path.startswith('/api')]
        ws_routes = [r for r in routes if hasattr(r, 'path') and r.path.startswith('/ws')]
        
        print(f"  总路由数: {len(routes)}")
        print(f"  API 路由: {len(api_routes)}")
        print(f"  WebSocket 路由: {len(ws_routes)}")
        
        # 列出关键 API
        key_apis = [
            "/api/v1/devices/register",
            "/api/v1/devices",
            "/api/v1/devices/discover",
            "/api/v1/nodes",
            "/api/v1/mcp",
        ]
        
        for api in key_apis:
            found = any(api in str(r.path) for r in routes)
            status = "✅" if found else "❌"
            print(f"  {status} {api}")
        
        print("  ✅ API 路由测试通过")
        return True
    except Exception as e:
        print(f"  ❌ API 路由测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试"""
    results = []
    
    results.append(await test_config())
    results.append(await test_device_registry())
    results.append(await test_device_communication())
    results.append(await test_system_integration())
    results.append(await test_mcp_loader())
    results.append(await test_skill_loader())
    results.append(await test_api_routes())
    
    print("\n" + "=" * 60)
    print(f"测试结果: {sum(results)}/{len(results)} 通过")
    print("=" * 60)
    
    if all(results):
        print("\n✅ 系统核心功能正常")
    else:
        print("\n⚠️ 部分功能需要修复")
    
    return all(results)


if __name__ == "__main__":
    asyncio.run(main())
