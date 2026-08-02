#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
能力注册系统验证脚本
=====================

验证能力注册、发现和连接管理功能

作者：Manus AI (Round 2 - R-4)
日期：2026-02-11
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.capability_manager import CapabilityStatus, get_capability_manager
from core.connection_manager import ConnectionState, get_connection_manager


def print_section(title: str):
    """打印章节标题"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}\n")


async def verify_capability_manager():
    """验证能力管理器"""
    print_section("1. 验证能力管理器")

    manager = get_capability_manager()

    # 测试注册能力
    print("📝 注册测试能力...")
    success = await manager.register_capability(
        name="test_capability", description="测试能力", node_id="test_node", node_name="TestNode", category="test"
    )

    if success:
        print("✅ 能力注册成功")
    else:
        print("❌ 能力注册失败")
        return False

    # 测试发现能力
    print("\n🔍 发现所有能力...")
    capabilities = manager.discover_capabilities()
    print(f"发现 {len(capabilities)} 个能力")

    for cap in capabilities:
        print(f"  - {cap.name}: {cap.description} (节点: {cap.node_name}, 状态: {cap.status.value})")

    # 测试获取统计
    print("\n📊 能力统计:")
    stats = manager.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # 测试状态更新
    print("\n🔄 更新能力状态...")
    await manager.update_capability_status("test_capability", CapabilityStatus.ONLINE)
    cap = manager.get_capability("test_capability")
    print(f"✅ 能力状态已更新: {cap.status.value}")

    # 测试持久化
    print("\n💾 测试持久化...")
    config_file = manager.config_file
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"✅ 配置文件已保存: {config_file}")
        print(f"   包含 {len(data.get('capabilities', []))} 个能力")
    else:
        print(f"⚠️  配置文件不存在: {config_file}")

    # 清理测试数据
    await manager.unregister_capability("test_capability")
    print("\n🧹 测试数据已清理")

    return True


async def verify_connection_manager():
    """验证连接管理器"""
    print_section("2. 验证连接管理器")

    manager = get_connection_manager()

    # 测试注册连接
    print("📝 注册测试连接...")
    success = await manager.register_connection(connection_id="test_connection", url="http://localhost:8000")

    if success:
        print("✅ 连接注册成功")
    else:
        print("❌ 连接注册失败")
        return False

    # 获取连接信息
    print("\n🔍 获取连接信息...")
    conn_info = manager.get_connection("test_connection")
    if conn_info:
        print(f"  连接ID: {conn_info.connection_id}")
        print(f"  URL: {conn_info.url}")
        print(f"  状态: {conn_info.state.value}")

    # 测试统计
    print("\n📊 连接统计:")
    stats = manager.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")

    # 测试健康报告
    print("\n🏥 生成健康报告...")
    report = manager.get_health_report()
    print(f"✅ 报告生成时间: {report['timestamp']}")
    print(f"   总连接数: {report['stats']['total_connections']}")

    # 清理测试数据
    await manager.disconnect("test_connection")
    print("\n🧹 测试数据已清理")

    return True


async def verify_integration():
    """验证集成"""
    print_section("3. 验证系统集成")

    # 检查配置文件
    print("📁 检查配置文件...")
    config_dir = PROJECT_ROOT / "config"

    files_to_check = ["capabilities.json", "connection_state.json", "node_dependencies.json", "unified_config.json"]

    for filename in files_to_check:
        filepath = config_dir / filename
        if filepath.exists():
            print(f"  ✅ {filename} 存在")
        else:
            print(f"  ⚠️  {filename} 不存在（将在运行时创建）")

    # 检查核心模块
    print("\n📦 检查核心模块...")
    core_modules = ["capability_manager", "connection_manager", "node_registry"]

    for module_name in core_modules:
        try:
            __import__(f"core.{module_name}")
            print(f"  ✅ core.{module_name} 可导入")
        except Exception as e:
            print(f"  ❌ core.{module_name} 导入失败: {e}")
            return False

    return True


async def main():
    """主函数"""
    print("""
╔═══════════════════════════════════════════════════════════════╗
║   Galaxy - 能力注册系统验证                              ║
║   Capability Registration & Connection Management (R-4)       ║
╚═══════════════════════════════════════════════════════════════╝
    """)

    results = []

    # 验证能力管理器
    try:
        result = await verify_capability_manager()
        results.append(("能力管理器", result))
    except Exception as e:
        print(f"❌ 能力管理器验证失败: {e}")
        results.append(("能力管理器", False))

    # 验证连接管理器
    try:
        result = await verify_connection_manager()
        results.append(("连接管理器", result))
    except Exception as e:
        print(f"❌ 连接管理器验证失败: {e}")
        results.append(("连接管理器", False))

    # 验证集成
    try:
        result = await verify_integration()
        results.append(("系统集成", result))
    except Exception as e:
        print(f"❌ 系统集成验证失败: {e}")
        results.append(("系统集成", False))

    # 打印总结
    print_section("验证总结")

    all_passed = True
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {name}: {status}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("🎉 所有验证通过！系统已准备就绪。")
        return 0
    else:
        print("⚠️  部分验证失败，请检查日志。")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
