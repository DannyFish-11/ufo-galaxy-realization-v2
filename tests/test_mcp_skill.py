#!/usr/bin/env python3
"""
UFO Galaxy - MCP 和 Skill 系统测试
===================================

测试 MCP 和 Skill 系统是否正常工作
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def test_mcp_manager():
    """测试 MCP 管理器"""
    print("\n=== 测试 MCP 管理器 ===")
    
    try:
        from core.mcp_manager import mcp_manager
        
        # 列出服务器
        servers = mcp_manager.list_servers()
        print(f"已配置服务器: {len(servers)} 个")
        for server in servers:
            print(f"  - {server['name']}: {server['status']}")
        
        # 列出工具
        tools = mcp_manager.list_tools()
        print(f"已注册工具: {len(tools)} 个")
        
        print("✅ MCP 管理器测试通过")
        return True
    except Exception as e:
        print(f"❌ MCP 管理器测试失败: {e}")
        return False


async def test_skill_manager():
    """测试 Skill 管理器"""
    print("\n=== 测试 Skill 管理器 ===")
    
    try:
        from core.skill_manager import skill_manager
        
        # 注册内置技能
        skill_manager.register_builtin_skills()
        
        # 列出技能
        skills = skill_manager.list_skills()
        print(f"已注册技能: {len(skills)} 个")
        for skill in skills[:5]:
            print(f"  - {skill['id']}: {skill['name']}")
        
        print("✅ Skill 管理器测试通过")
        return True
    except Exception as e:
        print(f"❌ Skill 管理器测试失败: {e}")
        return False


async def test_capability_orchestrator():
    """测试能力编排器"""
    print("\n=== 测试能力编排器 ===")
    
    try:
        from core.capability_orchestrator import capability_orchestrator
        
        # 初始化
        await capability_orchestrator.initialize()
        
        # 列出能力
        capabilities = capability_orchestrator.list_capabilities()
        print(f"已注册能力: {len(capabilities)} 个")
        
        # 发现能力
        results = await capability_orchestrator.discover("搜索", limit=3)
        print(f"\n发现能力 '搜索':")
        for cap in results:
            print(f"  - {cap['id']}: {cap['name']} (类型: {cap['type']})")
        
        print("\n✅ 能力编排器测试通过")
        return True
    except Exception as e:
        print(f"❌ 能力编排器测试失败: {e}")
        return False


async def main():
    """主测试"""
    print("=" * 60)
    print("UFO Galaxy MCP 和 Skill 系统测试")
    print("=" * 60)
    
    results = []
    
    results.append(await test_mcp_manager())
    results.append(await test_skill_manager())
    results.append(await test_capability_orchestrator())
    
    print("\n" + "=" * 60)
    print(f"测试结果: {sum(results)}/{len(results)} 通过")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
