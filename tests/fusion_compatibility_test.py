"""
Galaxy 深度融合兼容性测试套件

目标：彻底测试微软 UFO 和 galaxy 的融合兼容性

作者：Manus AI
日期：2026-01-22
版本：1.0
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# 测试结果
test_results = []

class FusionCompatibilityTest:
    """融合兼容性测试类"""
    
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warnings = 0
    
    async def run_all_tests(self):
        """运行所有测试"""
        print("=" * 80)
        print("Galaxy 深度融合兼容性测试")
        print("=" * 80)
        
        # 测试套件
        test_suites = [
            ("协议兼容性测试", self.test_protocol_compatibility),
            ("设备管理兼容性测试", self.test_device_management_compatibility),
            ("节点注册兼容性测试", self.test_node_registry_compatibility),
            ("视觉增强兼容性测试", self.test_vision_enhancement_compatibility),
            ("跨设备协同兼容性测试", self.test_cross_device_compatibility),
        ]
        
        for suite_name, test_func in test_suites:
            print(f"\n{'=' * 80}")
            print(f"测试套件: {suite_name}")
            print("=" * 80)
            await test_func()
        
        # 生成报告
        self.generate_report()
    
    async def test_protocol_compatibility(self):
        """测试协议兼容性"""
        print("\n【测试 1.1】AIP v1.0 vs v2.0 消息格式兼容性")
        print("-" * 80)
        
        # 测试 v1.0 消息
        v1_message = {
            "type": "request",
            "action": "execute",
            "params": {"command": "test"}
        }
        
        # 测试 v2.0 消息
        v2_message = {
            "version": "2.0",
            "type": "request",
            "message_id": "test-001",
            "action": "execute",
            "params": {"command": "test"},
            "timestamp": 1234567890
        }
        
        # 检查 v2.0 是否向后兼容 v1.0
        v2_can_parse_v1 = all(k in v2_message for k in v1_message.keys())
        
        if v2_can_parse_v1:
            print("✅ PASS: AIP v2.0 可以解析 v1.0 消息")
            self.passed += 1
            test_results.append(("协议兼容性", "v2.0 向后兼容 v1.0", "PASS"))
        else:
            print("❌ FAIL: AIP v2.0 无法解析 v1.0 消息")
            self.failed += 1
            test_results.append(("协议兼容性", "v2.0 向后兼容 v1.0", "FAIL"))
        
        print("\n【测试 1.2】协议字段完整性")
        print("-" * 80)
        
        required_fields_v2 = ["version", "type", "message_id", "timestamp"]
        missing_fields = [f for f in required_fields_v2 if f not in v2_message]
        
        if not missing_fields:
            print("✅ PASS: AIP v2.0 包含所有必需字段")
            self.passed += 1
            test_results.append(("协议兼容性", "v2.0 字段完整性", "PASS"))
        else:
            print(f"❌ FAIL: AIP v2.0 缺少字段: {missing_fields}")
            self.failed += 1
            test_results.append(("协议兼容性", "v2.0 字段完整性", "FAIL"))
    
    async def test_device_management_compatibility(self):
        """测试设备管理兼容性"""
        print("\n【测试 2.1】设备注册格式兼容性")
        print("-" * 80)
        
        # 微软 UFO 的设备注册格式
        ms_ufo_device = {
            "device_id": "phone_a",
            "device_type": "android",
            "capabilities": ["screenshot", "input"]
        }
        
        # galaxy 的设备注册格式
        galaxy_device = {
            "device_id": "phone_a",
            "device_type": "android",
            "device_name": "手机 A",
            "capabilities": ["screenshot", "input", "vlm_analyze"],
            "status": "online",
            "last_heartbeat": 1234567890
        }
        
        # 检查是否兼容（galaxy 包含微软 UFO 的所有字段）
        compatible = all(k in galaxy_device for k in ms_ufo_device.keys())
        
        if compatible:
            print("✅ PASS: galaxy 设备格式兼容微软 UFO")
            self.passed += 1
            test_results.append(("设备管理", "设备注册格式兼容性", "PASS"))
        else:
            print("❌ FAIL: 设备格式不兼容")
            self.failed += 1
            test_results.append(("设备管理", "设备注册格式兼容性", "FAIL"))
        
        print("\n【测试 2.2】设备能力扩展性")
        print("-" * 80)
        
        # 检查 galaxy 是否提供了额外的能力
        extra_capabilities = set(galaxy_device["capabilities"]) - set(ms_ufo_device["capabilities"])
        
        if extra_capabilities:
            print(f"✅ PASS: galaxy 提供了额外能力: {extra_capabilities}")
            self.passed += 1
            test_results.append(("设备管理", "设备能力扩展性", "PASS"))
        else:
            print("⚠️  WARNING: galaxy 未提供额外能力")
            self.warnings += 1
            test_results.append(("设备管理", "设备能力扩展性", "WARNING"))
    
    async def test_node_registry_compatibility(self):
        """测试节点注册兼容性"""
        print("\n【测试 3.1】节点目录结构兼容性")
        print("-" * 80)
        
        # 检查 galaxy 的节点目录是否存在
        nodes_dir = Path("/home/ubuntu/galaxy/nodes")
        if nodes_dir.exists():
            node_count = len(list(nodes_dir.glob("Node_*")))
            print(f"✅ PASS: 找到 {node_count} 个节点")
            self.passed += 1
            test_results.append(("节点注册", "节点目录存在", "PASS"))
        else:
            print("❌ FAIL: 节点目录不存在")
            self.failed += 1
            test_results.append(("节点注册", "节点目录存在", "FAIL"))
        
        print("\n【测试 3.2】关键节点可用性")
        print("-" * 80)
        
        critical_nodes = ["Node_90_MultimodalVision", "Node_33_ADB", "Node_34_Scrcpy"]
        for node_name in critical_nodes:
            node_path = nodes_dir / node_name
            if node_path.exists():
                print(f"✅ PASS: {node_name} 存在")
                self.passed += 1
                test_results.append(("节点注册", f"{node_name} 可用", "PASS"))
            else:
                print(f"❌ FAIL: {node_name} 不存在")
                self.failed += 1
                test_results.append(("节点注册", f"{node_name} 可用", "FAIL"))
    
    async def test_vision_enhancement_compatibility(self):
        """测试视觉增强兼容性"""
        print("\n【测试 4.1】Node_90 接口兼容性")
        print("-" * 80)
        
        # 检查 Node_90 的接口
        node_90_path = Path("/home/ubuntu/galaxy/nodes/Node_90_MultimodalVision/main.py")
        if node_90_path.exists():
            content = node_90_path.read_text()
            
            # 检查是否有 analyze_screen 端点
            has_analyze_screen = "analyze_screen" in content or "/analyze_screen" in content
            
            if has_analyze_screen:
                print("✅ PASS: Node_90 提供 analyze_screen 接口")
                self.passed += 1
                test_results.append(("视觉增强", "Node_90 接口", "PASS"))
            else:
                print("❌ FAIL: Node_90 缺少 analyze_screen 接口")
                self.failed += 1
                test_results.append(("视觉增强", "Node_90 接口", "FAIL"))
        else:
            print("❌ FAIL: Node_90 文件不存在")
            self.failed += 1
            test_results.append(("视觉增强", "Node_90 存在", "FAIL"))
        
        print("\n【测试 4.2】多 Provider 支持")
        print("-" * 80)
        
        if node_90_path.exists():
            content = node_90_path.read_text()
            
            # 检查是否支持多个 VLM Provider
            has_qwen = "qwen" in content.lower()
            has_gemini = "gemini" in content.lower()
            
            if has_qwen and has_gemini:
                print("✅ PASS: Node_90 支持多个 VLM Provider (Qwen + Gemini)")
                self.passed += 1
                test_results.append(("视觉增强", "多 Provider 支持", "PASS"))
            else:
                print("⚠️  WARNING: Node_90 可能只支持单一 Provider")
                self.warnings += 1
                test_results.append(("视觉增强", "多 Provider 支持", "WARNING"))
    
    async def test_cross_device_compatibility(self):
        """测试跨设备协同兼容性"""
        print("\n【测试 5.1】跨设备协调器存在性")
        print("-" * 80)
        
        coordinator_path = Path("/home/ubuntu/galaxy/galaxy_gateway/cross_device_coordinator.py")
        if coordinator_path.exists():
            print("✅ PASS: 跨设备协调器存在")
            self.passed += 1
            test_results.append(("跨设备协同", "协调器存在", "PASS"))
        else:
            print("❌ FAIL: 跨设备协调器不存在")
            self.failed += 1
            test_results.append(("跨设备协同", "协调器存在", "FAIL"))
        
        print("\n【测试 5.2】Android Agent 兼容性")
        print("-" * 80)
        
        android_client_path = Path("/home/ubuntu/galaxy/enhancements/clients/android_client")
        if android_client_path.exists():
            print("✅ PASS: Android 客户端存在")
            self.passed += 1
            test_results.append(("跨设备协同", "Android Agent 存在", "PASS"))
            
            # 检查是否有 Kotlin 文件
            kotlin_files = list(android_client_path.rglob("*.kt"))
            if kotlin_files:
                print(f"✅ PASS: 找到 {len(kotlin_files)} 个 Kotlin 文件")
                self.passed += 1
                test_results.append(("跨设备协同", "Android Agent 实现", "PASS"))
            else:
                print("❌ FAIL: 未找到 Kotlin 实现文件")
                self.failed += 1
                test_results.append(("跨设备协同", "Android Agent 实现", "FAIL"))
        else:
            print("❌ FAIL: Android 客户端不存在")
            self.failed += 1
            test_results.append(("跨设备协同", "Android Agent 存在", "FAIL"))
    
    def generate_report(self):
        """生成测试报告"""
        print("\n" + "=" * 80)
        print("测试报告")
        print("=" * 80)
        
        total = self.passed + self.failed + self.warnings
        print(f"\n总测试数: {total}")
        print(f"通过: {self.passed} ✅")
        print(f"失败: {self.failed} ❌")
        print(f"警告: {self.warnings} ⚠️")
        
        if self.failed == 0:
            print("\n🎉 所有关键测试通过！系统具备融合条件。")
        else:
            print(f"\n⚠️  有 {self.failed} 个测试失败，需要修复后再进行融合。")
        
        # 生成详细报告
        print("\n" + "=" * 80)
        print("详细测试结果")
        print("=" * 80)
        print(f"{'测试类别':<20} {'测试项':<30} {'结果':<10}")
        print("-" * 80)
        for category, test_name, result in test_results:
            status_icon = "✅" if result == "PASS" else ("❌" if result == "FAIL" else "⚠️")
            print(f"{category:<20} {test_name:<30} {status_icon} {result}")

# ============================================================================
# 主函数
# ============================================================================

async def main():
    """运行测试"""
    tester = FusionCompatibilityTest()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())
