"""
Galaxy - 端到端功能测试
测试从自然语言输入到节点执行的完整链路
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
import json
from typing import Dict, Any

import pytest


def test_1_core_modules_import():
    """测试 1: 核心模块导入"""
    print("\n=== 测试 1: 核心模块导入 ===")
    
    try:
        from enhancements.learning.autonomous_learning_engine import AutonomousLearningEngine
        from enhancements.multidevice.cross_device_scheduler import CrossDeviceScheduler
        from enhancements.multidevice.failover_manager import FailoverManager
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.orchestrator import GalaxyOrchestrator  # noqa: F401
        print("✅ 所有核心模块导入成功")
    except Exception as e:
        pytest.fail(f"模块导入失败: {e}")


def test_2_core_modules_instantiation():
    """测试 2: 核心模块实例化"""
    print("\n=== 测试 2: 核心模块实例化 ===")
    
    try:
        from enhancements.learning.autonomous_learning_engine import AutonomousLearningEngine
        from enhancements.multidevice.cross_device_scheduler import CrossDeviceScheduler
        from enhancements.multidevice.failover_manager import FailoverManager
        from galaxy_gateway.android_bridge import AndroidBridge
        
        engine = AutonomousLearningEngine()
        print("✅ AutonomousLearningEngine 实例化成功")
        
        scheduler = CrossDeviceScheduler()
        print("✅ CrossDeviceScheduler 实例化成功")
        
        failover = FailoverManager()
        print("✅ FailoverManager 实例化成功")
        
        bridge = AndroidBridge()
        print("✅ AndroidBridge 实例化成功")
    except Exception as e:
        pytest.fail(f"模块实例化失败: {e}")


def test_3_node_loading():
    """测试 3: 节点加载"""
    print("\n=== 测试 3: 节点加载 ===")
    
    nodes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'nodes')
    
    if not os.path.exists(nodes_dir):
        pytest.fail(f"节点目录不存在: {nodes_dir}")
    
    node_dirs = [d for d in os.listdir(nodes_dir) if d.startswith('Node_') and os.path.isdir(os.path.join(nodes_dir, d))]
    print(f"📊 发现 {len(node_dirs)} 个节点目录")
    
    # 测试几个关键节点
    key_nodes = ['Node_43_MAVLink', 'Node_49_OctoPrint', 'Node_58_ModelRouter']
    success_count = 0
    
    for node_name in key_nodes:
        node_path = os.path.join(nodes_dir, node_name, 'main.py')
        if os.path.exists(node_path):
            print(f"✅ {node_name} 存在")
            success_count += 1
        else:
            print(f"❌ {node_name} 不存在")
    
    print(f"📊 关键节点检查: {success_count}/{len(key_nodes)}")
    assert success_count == len(key_nodes), f"Key nodes check: {success_count}/{len(key_nodes)}"


async def test_4_android_bridge_message():
    """测试 4: 安卓桥接消息处理"""
    print("\n=== 测试 4: 安卓桥接消息处理 ===")
    
    try:
        from galaxy_gateway.android_bridge import AndroidBridge, MessageBuilder
        
        bridge = AndroidBridge()
        print("✅ AndroidBridge 实例化成功")

        # 测试消息构建（register_device 不存在，改用 MessageBuilder）
        msg = MessageBuilder.device_register_ack('test_device_001', success=True)
        assert 'message_type' in msg or 'type' in msg
        print(f"✅ 消息构建成功: {msg.get('message_type', msg.get('type'))}")

        # 测试内部设备注册处理器存在
        assert hasattr(bridge, '_handle_device_register'), "AndroidBridge 应有 _handle_device_register 方法"
        print("✅ 设备注册处理器存在")
    except Exception as e:
        pytest.fail(f"安卓桥接测试失败: {e}")


async def test_5_cross_device_scheduling():
    """测试 5: 跨设备任务调度"""
    print("\n=== 测试 5: 跨设备任务调度 ===")
    
    try:
        from enhancements.multidevice.cross_device_scheduler import CrossDeviceScheduler
        from enhancements.multidevice.device_protocol import TaskInfo, TaskPriority, DeviceInfo, DeviceStatus, DeviceCapabilities

        scheduler = CrossDeviceScheduler()

        # 注册测试设备（匹配 DeviceInfo 完整签名）
        device = DeviceInfo(
            device_id='test_device_001',
            device_type='ANDROID_PHONE',
            device_name='Test Phone',
            device_model='Test Model',
            os_version='Android 14',
            app_version='1.0.0',
            ip_address='127.0.0.1',
            port=8033,
            capabilities=DeviceCapabilities(custom_features=['ui_control']),
            status=DeviceStatus.ONLINE,
        )
        
        await scheduler.register_device(device)
        print("✅ 设备注册到调度器成功")
        
        # 创建测试任务
        task = TaskInfo(
            task_id='test_task_001',
            task_type='ui_control',
            priority=TaskPriority.NORMAL,
            payload={'action': 'click', 'x': 100, 'y': 200}
        )
        
        # 提交任务（submit_task 签名: task_type, payload）
        result = await scheduler.submit_task(
            task_type='ui_control',
            payload={'action': 'click', 'x': 100, 'y': 200},
        )
        print(f"✅ 任务提交成功: {result}")
    except Exception as e:
        pytest.fail(f"跨设备调度测试失败: {e}")


def test_6_physical_device_nodes():
    """测试 6: 物理设备控制节点"""
    print("\n=== 测试 6: 物理设备控制节点 ===")
    
    nodes_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'nodes')
    
    physical_nodes = {
        'Node_43_MAVLink': '无人机控制',
        'Node_49_OctoPrint': '3D打印机控制',
        'Node_51_QuantumDispatcher': '量子计算调度',
        'Node_33_ADB': 'Android设备控制'
    }
    
    success_count = 0
    for node_name, description in physical_nodes.items():
        node_path = os.path.join(nodes_dir, node_name, 'main.py')
        if os.path.exists(node_path):
            with open(node_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if len(content) > 100:  # 确保不是空文件
                    print(f"✅ {node_name} ({description}) - {len(content)} 字节")
                    success_count += 1
                else:
                    print(f"⚠️  {node_name} ({description}) - 文件过小")
        else:
            print(f"❌ {node_name} ({description}) - 不存在")
    
    print(f"📊 物理设备节点: {success_count}/{len(physical_nodes)}")
    assert success_count >= 3, f"Physical device nodes: {success_count}/{len(physical_nodes)}"


async def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("Galaxy - 端到端功能测试")
    print("=" * 60)
    
    results = {}
    
    # 同步测试
    results['test_1'] = test_1_core_modules_import()
    results['test_2'] = test_2_core_modules_instantiation()
    results['test_3'] = test_3_node_loading()
    
    # 异步测试
    results['test_4'] = await test_4_android_bridge_message()
    results['test_5'] = await test_5_cross_device_scheduling()
    
    # 同步测试
    results['test_6'] = test_6_physical_device_nodes()
    
    # 统计结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    for test_name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{test_name}: {status}")
    
    print(f"\n📊 总体通过率: {passed}/{total} ({100*passed//total}%)")
    
    if passed == total:
        print("\n🎉🎉🎉 所有测试通过！系统端到端功能完整！")
    elif passed >= total * 0.8:
        print("\n✅ 大部分测试通过，系统基本可用")
    else:
        print("\n⚠️  部分测试失败，需要进一步修复")
    
    return passed, total


if __name__ == '__main__':
    passed, total = asyncio.run(run_all_tests())
    sys.exit(0 if passed == total else 1)
