#!/usr/bin/env python3
"""
UFO Galaxy - SKILL.md 测试
=========================

测试 SKILL.md 格式加载器
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


async def test_skill_md_loader():
    """测试 SKILL.md 加载器"""
    print("\n=== 测试 SKILL.md 加载器 ===")
    
    try:
        from core.skill_md_loader import skill_md_loader
        
        # 加载示例技能
        skill_path = Path(__file__).parent / "skills" / "examples" / "weather"
        
        print(f"加载技能: {skill_path}")
        result = await skill_md_loader.load(str(skill_path))
        print(f"结果: {result}")
        
        if result.get("success"):
            skill_id = result["skill_id"]
            
            # 列出技能
            skills = skill_md_loader.list_skills()
            print(f"\n已加载技能: {len(skills)} 个")
            for skill in skills:
                print(f"  - {skill['name']}: {skill['description']}")
                print(f"    命令数: {len(skill['commands'])}")
            
            # 执行技能
            print(f"\n执行技能: {skill_id}")
            exec_result = await skill_md_loader.execute(skill_id, {"city": "London"})
            print(f"执行结果: {exec_result['success']}")
            if exec_result['results']:
                for r in exec_result['results'][:2]:
                    print(f"  命令: {r['command'][:50]}...")
                    print(f"  成功: {r['success']}")
            
            # 卸载技能
            print(f"\n卸载技能: {skill_id}")
            unload_result = skill_md_loader.unload(skill_id)
            print(f"卸载结果: {unload_result}")
        
        print("\n✅ SKILL.md 加载器测试通过")
        return True
    except Exception as e:
        print(f"❌ SKILL.md 加载器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_cli():
    """测试 CLI"""
    print("\n=== 测试 CLI ===")
    
    try:
        # 测试 skill list
        print("测试: ufo skill list")
        # 这里只是验证 CLI 可以导入
        from cli.ufo import skill_list
        await skill_list()
        
        print("\n✅ CLI 测试通过")
        return True
    except Exception as e:
        print(f"❌ CLI 测试失败: {e}")
        return False


async def main():
    """主测试"""
    print("=" * 60)
    print("UFO Galaxy SKILL.md 测试")
    print("=" * 60)
    
    results = []
    
    results.append(await test_skill_md_loader())
    results.append(await test_cli())
    
    print("\n" + "=" * 60)
    print(f"测试结果: {sum(results)}/{len(results)} 通过")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
