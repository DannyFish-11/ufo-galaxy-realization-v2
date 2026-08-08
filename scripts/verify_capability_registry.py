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
import os
import shutil
import sys
import tempfile
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# 沙箱化配置目录 —— 必须在 import core.capability_manager **之前**。
#
# 这个脚本会 register_capability("test_capability", node_id="test_node") 往真实
# 注册表里写东西，而 CapabilityManager 的默认 config_dir 是**仓库内的绝对路径**
# （基于 __file__，换 CWD 也躲不掉），register 又会同步落盘 —— 于是跑一次"验证"
# 就改写一次 git 跟踪的 config/capabilities.json。
#
# 实测：脚本自己会把测试能力注销掉，所以不会留下垃圾条目，但顶层 timestamp 每跑一次
# 就变一次，文件必然变脏。一个**验证**脚本去修改它要验证的东西，本身就是错的：
# 验证的前提是被验证对象不被观测行为改变。
#
# pytest 那边已经在 conftest 里用 GALAXY_CONFIG_DIR 指到临时目录堵上了，但脚本不走
# conftest，所以要在这里自己做同一件事：拷一份真实配置进临时目录，让所有读写都落在
# 那份拷贝上 —— 读到的内容不变，写出去的落不到仓库里。
# ---------------------------------------------------------------------------
if not os.environ.get("GALAXY_CONFIG_DIR"):
    _sandbox = Path(tempfile.mkdtemp(prefix="galaxy-verify-config-"))
    _real_config = PROJECT_ROOT / "config"
    for _name in ("capabilities.json", "connection_state.json", "node_dependencies.json", "unified_config.json"):
        _src = _real_config / _name
        if _src.exists():
            shutil.copy2(_src, _sandbox / _name)
    os.environ["GALAXY_CONFIG_DIR"] = str(_sandbox)

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
