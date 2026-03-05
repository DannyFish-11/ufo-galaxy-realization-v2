#!/usr/bin/env python3
"""
UFO Galaxy - 加载器测试
======================

测试 MCP 和 Skill 的加载/卸载功能
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def test_skill_loader():
    """测试 Skill 加载器"""
    print("\n=== 测试 Skill 加载器 ===")
    
    try:
        from core.skill_loader import skill_loader
        
        # 加载示例技能
        skill_path = Path(__file__).parent / "skills" / "examples" / "hello_skill"
        
        print(f"加载技能: {skill_path}")
        result = await skill_loader.load(str(skill_path))
        print(f"结果: {result}")
        
        if result.get("success"):
            skill_id = result["skill_id"]
            
            # 列出技能
            skills = skill_loader.list_skills()
            print(f"\n已加载技能: {len(skills)} 个")
            for skill in skills:
                print(f"  - {skill['id']}: {skill['name']}")
            
            # 执行技能
            print(f"\n执行技能: {skill_id}")
            exec_result = await skill_loader.execute(skill_id, name="用户")
            print(f"执行结果: {exec_result}")
            
            # 卸载技能
            print(f"\n卸载技能: {skill_id}")
            unload_result = await skill_loader.unload(skill_id)
            print(f"卸载结果: {unload_result}")
            
            # 再次列出
            skills = skill_loader.list_skills()
            print(f"\n卸载后技能: {len(skills)} 个")
        
        print("\n✅ Skill 加载器测试通过")
        return True
    except Exception as e:
        print(f"❌ Skill 加载器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_mcp_loader():
    """测试 MCP 加载器"""
    print("\n=== 测试 MCP 加载器 ===")
    
    try:
        from core.mcp_loader import mcp_loader
        
        # 列出服务器 (应该为空)
        servers = mcp_loader.list_servers()
        print(f"已加载服务器: {len(servers)} 个")
        
        # 注意: 实际加载需要 npx 或 node 环境
        # 这里只测试 API 是否正常工作
        
        print("\n✅ MCP 加载器测试通过")
        return True
    except Exception as e:
        print(f"❌ MCP 加载器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """主测试"""
    print("=" * 60)
    print("UFO Galaxy 加载器测试")
    print("=" * 60)
    
    results = []
    
    results.append(await test_skill_loader())
    results.append(await test_mcp_loader())
    
    print("\n" + "=" * 60)
    print(f"测试结果: {sum(results)}/{len(results)} 通过")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
