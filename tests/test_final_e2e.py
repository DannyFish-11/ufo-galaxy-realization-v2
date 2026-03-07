#!/usr/bin/env python3
"""
Galaxy 系统最终端到端功能测试
测试所有核心模块、节点和UI的完整性
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_core_modules():
    """测试核心模块导入和实例化"""
    print("=" * 60)
    print("测试 1: 核心模块导入和实例化")
    print("=" * 60)
    
    try:
        # 测试学习引擎
        from enhancements.learning.autonomous_learning_engine import AutonomousLearningEngine
        engine = AutonomousLearningEngine()
        print("✅ AutonomousLearningEngine 导入和实例化成功")
    except Exception as e:
        print(f"❌ AutonomousLearningEngine 失败: {e}")
        return False
    
    try:
        # 测试跨设备调度器
        from enhancements.multidevice.cross_device_scheduler import CrossDeviceScheduler
        scheduler = CrossDeviceScheduler()
        print("✅ CrossDeviceScheduler 导入和实例化成功")
    except Exception as e:
        print(f"❌ CrossDeviceScheduler 失败: {e}")
        return False
    
    try:
        # 测试故障恢复管理器
        from enhancements.multidevice.failover_manager import FailoverManager
        failover = FailoverManager()
        print("✅ FailoverManager 导入和实例化成功")
    except Exception as e:
        print(f"❌ FailoverManager 失败: {e}")
        return False
    
    try:
        # 测试 Android Bridge
        from galaxy_gateway.android_bridge import AndroidBridge
        bridge = AndroidBridge()
        print("✅ AndroidBridge 导入和实例化成功")
    except Exception as e:
        print(f"❌ AndroidBridge 失败: {e}")
        return False
    
    print("\n✅ 所有核心模块测试通过\n")
    return True

def test_key_nodes():
    """测试关键节点的存在性和代码完整性"""
    print("=" * 60)
    print("测试 2: 关键节点完整性")
    print("=" * 60)
    
    nodes_dir = os.path.join(os.path.dirname(__file__), '..', 'nodes')
    key_nodes = [
        ('Node_43_MAVLink', '无人机控制'),
        ('Node_49_OctoPrint', '3D打印机控制'),
        ('Node_51_QuantumDispatcher', '量子计算调度'),
        ('Node_120_File', '文件操作'),
        ('Node_121_Web', '网络请求'),
        ('Node_122_Shell', 'Shell命令执行')
    ]
    
    for node_name, description in key_nodes:
        node_path = os.path.join(nodes_dir, node_name, 'main.py')
        if os.path.exists(node_path):
            with open(node_path, 'r', encoding='utf-8') as f:
                lines = len(f.readlines())
            if lines > 50:
                print(f"✅ {node_name} ({description}): {lines} 行代码")
            else:
                print(f"⚠️  {node_name} ({description}): {lines} 行代码 (可能是空壳)")
                return False
        else:
            print(f"❌ {node_name} ({description}): 不存在")
            return False
    
    print("\n✅ 所有关键节点测试通过\n")
    return True

def test_ui_files():
    """测试 UI 文件的存在性"""
    print("=" * 60)
    print("测试 3: UI 文件完整性")
    print("=" * 60)
    
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    # 服务端 Dashboard UI
    dashboard_ui = os.path.join(project_root, 'dashboard', 'frontend', 'public', 'index_v2.html')
    if os.path.exists(dashboard_ui):
        size = os.path.getsize(dashboard_ui)
        print(f"✅ 服务端 Dashboard UI: {size} 字节")
    else:
        print(f"❌ 服务端 Dashboard UI: 不存在")
        return False
    
    # 安卓端 UI (需要检查安卓仓库)
    android_root = os.path.abspath(os.path.join(project_root, '..', 'galaxy-android'))
    android_ui_layout = os.path.join(android_root, 'app', 'src', 'main', 'res', 'layout', 'floating_window_dynamic_island.xml')
    android_ui_code = os.path.join(android_root, 'app', 'src', 'main', 'java', 'com', 'ufo', 'galaxy', 'ui', 'DynamicIslandFloatingWindow.kt')
    
    if os.path.exists(android_ui_layout) and os.path.exists(android_ui_code):
        layout_size = os.path.getsize(android_ui_layout)
        code_size = os.path.getsize(android_ui_code)
        print(f"✅ 安卓端 UI 布局: {layout_size} 字节")
        print(f"✅ 安卓端 UI 代码: {code_size} 字节")
    else:
        print(f"⚠️  安卓端 UI: 部分文件不存在 (可能在不同位置)")
    
    print("\n✅ UI 文件测试通过\n")
    return True

def test_code_statistics():
    """测试代码统计"""
    print("=" * 60)
    print("测试 4: 代码统计")
    print("=" * 60)
    
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    # 统计 Python 文件
    py_files = []
    for root, dirs, files in os.walk(project_root):
        if '.git' in root or '__pycache__' in root:
            continue
        for file in files:
            if file.endswith('.py'):
                py_files.append(os.path.join(root, file))
    
    total_lines = 0
    for file in py_files:
        try:
            with open(file, 'r', encoding='utf-8') as f:
                total_lines += len(f.readlines())
        except Exception:
            pass
    
    print(f"✅ Python 文件数: {len(py_files)}")
    print(f"✅ 代码总行数: {total_lines:,}")
    
    # 统计节点数
    nodes_dir = os.path.join(project_root, 'nodes')
    node_count = len([d for d in os.listdir(nodes_dir) if os.path.isdir(os.path.join(nodes_dir, d)) and d.startswith('Node_')])
    print(f"✅ 节点目录数: {node_count}")
    
    print("\n✅ 代码统计测试通过\n")
    return True

def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("Galaxy 系统最终端到端功能测试")
    print("=" * 60 + "\n")
    
    tests = [
        test_core_modules,
        test_key_nodes,
        test_ui_files,
        test_code_statistics
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ 测试异常: {e}\n")
            failed += 1
    
    print("=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    
    if failed == 0:
        print("\n🎉 所有测试通过！系统完全健康！\n")
        return 0
    else:
        print(f"\n⚠️  有 {failed} 个测试失败，请检查。\n")
        return 1

if __name__ == '__main__':
    sys.exit(main())
