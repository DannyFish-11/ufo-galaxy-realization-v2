#!/usr/bin/env python3
"""
Galaxy - MCP 和 Skill 系统测试
===================================

测试 MCP 和 Skill 系统是否正常工作
（已迁移到 core.mcp_loader / core.skill_loader）
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def test_mcp_loader():
    """测试 MCP 加载器"""
    print("\n=== 测试 MCP 加载器 ===")

    try:
        from core.mcp_loader import mcp_loader

        # 列出服务器
        servers = mcp_loader.list_servers()
        print(f"已配置服务器: {len(servers)} 个")
        for server in servers:
            print(f"  - {server.get('name', server.get('id', '?'))}: {server.get('status', '?')}")

        print("✅ MCP 加载器测试通过")
        return True
    except Exception as e:
        print(f"❌ MCP 加载器测试失败: {e}")
        return False


async def test_skill_loader():
    """测试 Skill 加载器"""
    print("\n=== 测试 Skill 加载器 ===")

    try:
        from core.skill_loader import skill_loader

        # 列出技能
        skills = skill_loader.list_skills()
        print(f"已注册技能: {len(skills)} 个")
        for skill in skills[:5]:
            print(f"  - {skill.get('id', '?')}: {skill.get('name', '?')}")

        print("✅ Skill 加载器测试通过")
        return True
    except Exception as e:
        print(f"❌ Skill 加载器测试失败: {e}")
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
    print("Galaxy MCP 和 Skill 系统测试")
    print("=" * 60)

    results = []

    results.append(await test_mcp_loader())
    results.append(await test_skill_loader())
    results.append(await test_capability_orchestrator())

    print("\n" + "=" * 60)
    print(f"测试结果: {sum(results)}/{len(results)} 通过")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
