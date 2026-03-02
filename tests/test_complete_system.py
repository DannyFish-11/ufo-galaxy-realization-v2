#!/usr/bin/env python3
"""
UFO Galaxy 完整系统端到端测试
"""
import sys
sys.path.insert(0, '.')

def test_all_modules():
    """测试所有核心模块"""
    print("=" * 60)
    print("UFO Galaxy 完整系统测试")
    print("=" * 60)
    
    results = {
        "passed": [],
        "failed": []
    }
    
    # 测试 1: 核心模块导入
    print("\n[测试 1] 核心模块导入")
    modules = [
        'enhancements.learning.autonomous_learning_engine',
        'enhancements.multidevice.cross_device_scheduler',
        'enhancements.multidevice.failover_manager',
        'fusion.unified_orchestrator',
        'galaxy_gateway.android_bridge',
    ]
    
    for module in modules:
        try:
            __import__(module)
            print(f"  ✅ {module}")
            results["passed"].append(f"导入: {module}")
        except Exception as e:
            print(f"  ❌ {module}: {str(e)[:50]}")
            results["failed"].append(f"导入: {module}")
    
    # 测试 2: 节点完整性
    print("\n[测试 2] 关键节点完整性")
    import os
    critical_nodes = [
        'Node_12_File',
        'Node_13_Web', 
        'Node_14_Shell',
        'Node_43_MAVLink',
        'Node_49_OctoPrint',
        'Node_51_QuantumDispatcher'
    ]
    
    for node in critical_nodes:
        path = f"nodes/{node}/main.py"
        if os.path.exists(path):
            with open(path) as f:
                lines = len(f.readlines())
            if lines > 100:
                print(f"  ✅ {node}: {lines} 行")
                results["passed"].append(f"节点: {node}")
            else:
                print(f"  ⚠️  {node}: {lines} 行 (可能不完整)")
                results["failed"].append(f"节点: {node}")
        else:
            print(f"  ❌ {node}: 文件不存在")
            results["failed"].append(f"节点: {node}")
    
    # 测试 3: UI 文件完整性
    print("\n[测试 3] UI 文件完整性")
    ui_files = [
        'dashboard/frontend/public/index_v2.html',
    ]
    
    for ui_file in ui_files:
        if os.path.exists(ui_file):
            size = os.path.getsize(ui_file)
            print(f"  ✅ {ui_file}: {size} bytes")
            results["passed"].append(f"UI: {ui_file}")
        else:
            print(f"  ❌ {ui_file}: 文件不存在")
            results["failed"].append(f"UI: {ui_file}")
    
    # 总结
    print("\n" + "=" * 60)
    print(f"测试完成: {len(results['passed'])} 通过, {len(results['failed'])} 失败")
    print("=" * 60)
    
    if results["failed"]:
        print("\n失败项目:")
        for item in results["failed"]:
            print(f"  - {item}")
    
    return len(results["failed"]) == 0

if __name__ == "__main__":
    success = test_all_modules()
    sys.exit(0 if success else 1)
