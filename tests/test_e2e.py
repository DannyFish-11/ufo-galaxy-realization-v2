"""
UFO Galaxy - 端到端测试脚本

测试内容：
1. 核心模块导入测试
2. 节点服务启动测试
3. Android Bridge 功能测试
4. 协议消息构建测试
5. 工具节点功能测试

Author: UFO Galaxy Team
Version: 5.0.0
"""

import sys
import os
import asyncio
import json
import time
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 测试结果
test_results = {
    "passed": 0,
    "failed": 0,
    "skipped": 0,
    "details": []
}


def log_test(name: str, passed: bool, message: str = ""):
    """记录测试结果"""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status}: {name}")
    if message:
        print(f"       {message}")
    
    if passed:
        test_results["passed"] += 1
    else:
        test_results["failed"] += 1
    
    test_results["details"].append({
        "name": name,
        "passed": passed,
        "message": message
    })


def log_skip(name: str, reason: str):
    """记录跳过的测试"""
    print(f"⏭️ SKIP: {name}")
    print(f"       {reason}")
    test_results["skipped"] += 1
    test_results["details"].append({
        "name": name,
        "passed": None,
        "message": f"Skipped: {reason}"
    })


# =============================================================================
# 测试 1: 核心模块导入
# =============================================================================

def test_core_imports():
    """测试核心模块导入"""
    print("\n" + "=" * 60)
    print("测试 1: 核心模块导入")
    print("=" * 60)
    
    # 测试 Android Bridge
    try:
        from galaxy_gateway.android_bridge import (
            AndroidBridge, AndroidDevice, MessageBuilder,
            DeviceType, DevicePlatform, MessageType, DeviceCapability
        )
        log_test("Android Bridge 模块", True, f"设备类型: {len(DeviceType)}, 消息类型: {len(MessageType)}")
    except Exception as e:
        log_test("Android Bridge 模块", False, str(e))
    
    # 测试 Fusion 编排器
    try:
        from fusion.topology_manager import TopologyManager
        log_test("Fusion TopologyManager", True)
    except Exception as e:
        log_test("Fusion TopologyManager", False, str(e))
    
    try:
        from fusion.unified_orchestrator import UnifiedOrchestrator
        log_test("Fusion UnifiedOrchestrator", True)
    except Exception as e:
        log_test("Fusion UnifiedOrchestrator", False, str(e))
    
    # 测试增强模块
    try:
        from enhancements.learning.autonomous_learning_engine import AutonomousLearningEngine
        log_test("AutonomousLearningEngine", True)
    except Exception as e:
        log_test("AutonomousLearningEngine", False, str(e))
    
    try:
        from enhancements.learning.knowledge_graph import KnowledgeGraph
        log_test("KnowledgeGraph", True)
    except Exception as e:
        log_test("KnowledgeGraph", False, str(e))
    
    try:
        from enhancements.multidevice.cross_device_scheduler import CrossDeviceScheduler
        log_test("CrossDeviceScheduler", True)
    except Exception as e:
        log_test("CrossDeviceScheduler", False, str(e))


# =============================================================================
# 测试 2: 协议消息构建
# =============================================================================

def test_protocol_messages():
    """测试协议消息构建"""
    print("\n" + "=" * 60)
    print("测试 2: 协议消息构建")
    print("=" * 60)
    
    try:
        from galaxy_gateway.android_bridge import MessageBuilder, MessageType
        
        # 测试设备注册确认
        msg = MessageBuilder.device_register_ack(
            device_id="test_device",
            success=True,
            session_id="session_123"
        )
        assert msg["type"] == "device_register_ack"
        assert msg["success"] == True
        assert msg["version"] == "3.0"
        log_test("设备注册确认消息", True)
        
        # 测试心跳确认
        msg = MessageBuilder.heartbeat_ack("test_device")
        assert msg["type"] == "heartbeat_ack"
        log_test("心跳确认消息", True)
        
        # 测试 GUI 点击
        msg = MessageBuilder.gui_click("test_device", 100, 200)
        assert msg["type"] == "gui_click"
        assert msg["x"] == 100
        assert msg["y"] == 200
        log_test("GUI 点击消息", True)
        
        # 测试 GUI 滑动
        msg = MessageBuilder.gui_swipe("test_device", 100, 200, 300, 400, 500)
        assert msg["type"] == "gui_swipe"
        assert msg["start_x"] == 100
        assert msg["end_y"] == 400
        log_test("GUI 滑动消息", True)
        
        # 测试 GUI 输入
        msg = MessageBuilder.gui_input("test_device", "Hello World", clear_first=True)
        assert msg["type"] == "gui_input"
        assert msg["text"] == "Hello World"
        assert msg["clear_first"] == True
        log_test("GUI 输入消息", True)
        
        # 测试任务分配
        msg = MessageBuilder.task_assign(
            device_id="test_device",
            task_id="task_001",
            task_type="gui_automation",
            payload={"action": "click_button"},
            priority=3
        )
        assert msg["type"] == "task_assign"
        assert msg["task_id"] == "task_001"
        assert msg["priority"] == 3
        log_test("任务分配消息", True)
        
        # 测试错误消息
        msg = MessageBuilder.error(
            device_id="test_device",
            error_code="E001",
            error_message="Test error"
        )
        assert msg["type"] == "error"
        assert msg["error_code"] == "E001"
        log_test("错误消息", True)
        
    except Exception as e:
        log_test("协议消息构建", False, str(e))


# =============================================================================
# 测试 3: 设备能力
# =============================================================================

def test_device_capabilities():
    """测试设备能力"""
    print("\n" + "=" * 60)
    print("测试 3: 设备能力")
    print("=" * 60)
    
    try:
        from galaxy_gateway.android_bridge import DeviceCapability
        
        # 获取 Android 默认能力
        caps = DeviceCapability.get_android_default()
        assert caps > 0
        log_test("Android 默认能力", True, f"能力值: {caps}")
        
        # 检查具体能力
        assert DeviceCapability.has_capability(caps, DeviceCapability.NETWORK)
        assert DeviceCapability.has_capability(caps, DeviceCapability.GUI_READ)
        assert DeviceCapability.has_capability(caps, DeviceCapability.INPUT_TOUCH)
        log_test("能力检查", True, "NETWORK, GUI_READ, INPUT_TOUCH")
        
        # 转换为列表
        caps_list = DeviceCapability.to_list(caps)
        assert len(caps_list) > 0
        assert "network" in caps_list
        assert "gui_read" in caps_list
        log_test("能力列表转换", True, f"能力数量: {len(caps_list)}")
        
    except Exception as e:
        log_test("设备能力测试", False, str(e))


# =============================================================================
# 测试 4: Android Bridge 实例化
# =============================================================================

def test_android_bridge():
    """测试 Android Bridge 实例化"""
    print("\n" + "=" * 60)
    print("测试 4: Android Bridge 实例化")
    print("=" * 60)
    
    try:
        from galaxy_gateway.android_bridge import AndroidBridge, AndroidDevice, DeviceType
        
        # 创建实例
        bridge = AndroidBridge()
        log_test("AndroidBridge 实例化", True)
        
        # 检查初始状态
        devices = bridge.get_all_devices()
        assert isinstance(devices, list)
        log_test("获取设备列表", True, f"设备数量: {len(devices)}")
        
        # 创建模拟设备
        device = AndroidDevice(
            device_id="test_android_001",
            device_type=DeviceType.ANDROID_PHONE,
            name="Test Phone",
            model="Pixel 6"
        )
        assert device.device_id == "test_android_001"
        log_test("AndroidDevice 创建", True, f"设备: {device.model}")
        
        # 转换为字典
        device_dict = device.to_dict()
        assert "device_id" in device_dict
        assert "capabilities_list" in device_dict
        log_test("AndroidDevice 序列化", True)
        
    except Exception as e:
        log_test("Android Bridge 测试", False, str(e))


# =============================================================================
# 测试 5: 工具节点功能
# =============================================================================

def test_tool_nodes():
    """测试工具节点功能"""
    print("\n" + "=" * 60)
    print("测试 5: 工具节点功能")
    print("=" * 60)
    
    # 测试 File 节点
    try:
        # 读取并执行 Node_12_File 的核心类
        file_path = PROJECT_ROOT / "nodes" / "Node_12_File" / "main.py"
        if file_path.exists():
            # 只导入核心类，不启动服务
            code = file_path.read_text()
            # 提取 FileService 类定义
            exec_globals = {"__name__": "__test__"}
            exec(code.split("if __name__")[0], exec_globals)
            
            FileService = exec_globals.get("FileService")
            if FileService:
                fs = FileService("/tmp/ufo_test")
                log_test("Node_12_File (FileService)", True)
            else:
                log_test("Node_12_File (FileService)", False, "FileService 类未找到")
        else:
            log_skip("Node_12_File", "文件不存在")
    except Exception as e:
        log_test("Node_12_File", False, str(e))
    
    # 测试 Web 节点
    try:
        file_path = PROJECT_ROOT / "nodes" / "Node_13_Web" / "main.py"
        if file_path.exists():
            code = file_path.read_text()
            exec_globals = {"__name__": "__test__"}
            exec(code.split("if __name__")[0], exec_globals)
            
            WebService = exec_globals.get("WebService")
            if WebService:
                ws = WebService("/tmp/ufo_downloads")
                log_test("Node_13_Web (WebService)", True)
            else:
                log_test("Node_13_Web (WebService)", False, "WebService 类未找到")
        else:
            log_skip("Node_13_Web", "文件不存在")
    except Exception as e:
        log_test("Node_13_Web", False, str(e))
    
    # 测试 Shell 节点
    try:
        file_path = PROJECT_ROOT / "nodes" / "Node_14_Shell" / "main.py"
        if file_path.exists():
            code = file_path.read_text()
            exec_globals = {"__name__": "__test__"}
            exec(code.split("if __name__")[0], exec_globals)
            
            ShellService = exec_globals.get("ShellService")
            if ShellService:
                ss = ShellService("/tmp")
                log_test("Node_14_Shell (ShellService)", True)
            else:
                log_test("Node_14_Shell (ShellService)", False, "ShellService 类未找到")
        else:
            log_skip("Node_14_Shell", "文件不存在")
    except Exception as e:
        log_test("Node_14_Shell", False, str(e))


# =============================================================================
# 测试 6: 节点目录完整性
# =============================================================================

def test_node_directories():
    """测试节点目录完整性"""
    print("\n" + "=" * 60)
    print("测试 6: 节点目录完整性")
    print("=" * 60)
    
    nodes_dir = PROJECT_ROOT / "nodes"
    
    if not nodes_dir.exists():
        log_test("节点目录存在", False, "nodes 目录不存在")
        return
    
    node_dirs = [d for d in nodes_dir.iterdir() if d.is_dir() and d.name.startswith("Node_")]
    log_test("节点目录数量", True, f"共 {len(node_dirs)} 个节点目录")
    
    # 检查每个节点是否有 main.py
    nodes_with_main = 0
    nodes_without_main = []
    
    for node_dir in node_dirs:
        main_py = node_dir / "main.py"
        if main_py.exists():
            nodes_with_main += 1
        else:
            nodes_without_main.append(node_dir.name)
    
    log_test("节点 main.py 存在", 
             nodes_with_main == len(node_dirs),
             f"{nodes_with_main}/{len(node_dirs)} 个节点有 main.py")
    
    if nodes_without_main and len(nodes_without_main) <= 5:
        print(f"       缺少 main.py: {', '.join(nodes_without_main)}")


# =============================================================================
# 测试 7: 配置文件完整性
# =============================================================================

def test_config_files():
    """测试配置文件完整性"""
    print("\n" + "=" * 60)
    print("测试 7: 配置文件完整性")
    print("=" * 60)
    
    config_files = [
        "config/unified_config.json",
        "config/node_registry.json",
        "requirements.txt",
        "docker-compose.yml",
        ".env.example"
    ]
    
    for config_file in config_files:
        file_path = PROJECT_ROOT / config_file
        if file_path.exists():
            size = file_path.stat().st_size
            log_test(f"配置文件: {config_file}", True, f"大小: {size} bytes")
        else:
            log_test(f"配置文件: {config_file}", False, "文件不存在")


# =============================================================================
# 测试 8: 异步功能测试
# =============================================================================

async def test_async_functions():
    """测试异步功能"""
    print("\n" + "=" * 60)
    print("测试 8: 异步功能测试")
    print("=" * 60)
    
    try:
        from galaxy_gateway.android_bridge import AndroidBridge
        
        bridge = AndroidBridge()
        
        # 测试获取设备列表（异步安全）
        devices = bridge.get_connected_devices()
        log_test("异步获取设备列表", True, f"已连接设备: {len(devices)}")
        
        # 测试清理超时设备
        await bridge.cleanup_stale_devices(timeout_seconds=0.1)
        log_test("异步清理超时设备", True)
        
    except Exception as e:
        log_test("异步功能测试", False, str(e))


# =============================================================================
# 主函数
# =============================================================================

def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("UFO Galaxy - 端到端测试")
    print("=" * 60)
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 运行同步测试
    test_core_imports()
    test_protocol_messages()
    test_device_capabilities()
    test_android_bridge()
    test_tool_nodes()
    test_node_directories()
    test_config_files()
    
    # 运行异步测试
    asyncio.run(test_async_functions())
    
    # 打印总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"✅ 通过: {test_results['passed']}")
    print(f"❌ 失败: {test_results['failed']}")
    print(f"⏭️ 跳过: {test_results['skipped']}")
    print(f"总计: {test_results['passed'] + test_results['failed'] + test_results['skipped']}")
    
    # 计算通过率
    total = test_results['passed'] + test_results['failed']
    if total > 0:
        pass_rate = (test_results['passed'] / total) * 100
        print(f"通过率: {pass_rate:.1f}%")
    
    # 返回退出码
    return 0 if test_results['failed'] == 0 else 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
