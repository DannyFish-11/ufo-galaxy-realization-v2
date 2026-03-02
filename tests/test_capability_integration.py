#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
能力注册和连接管理集成测试
============================

测试能力注册、发现和连接管理的完整流程

作者：Manus AI (Round 2 - R-4)
日期：2026-02-11
"""

import sys
import asyncio
import unittest
from pathlib import Path

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestCapabilityIntegration(unittest.IsolatedAsyncioTestCase):
    """能力集成测试"""
    
    async def asyncSetUp(self):
        """测试设置"""
        from core.capability_manager import get_capability_manager
        from core.connection_manager import get_connection_manager
        
        self.capability_manager = get_capability_manager()
        self.connection_manager = get_connection_manager()
    
    async def test_capability_registration(self):
        """测试能力注册"""
        # 注册能力
        success = await self.capability_manager.register_capability(
            name="test_http_get",
            description="HTTP GET 请求",
            node_id="08",
            node_name="Fetch",
            category="http"
        )
        
        self.assertTrue(success, "能力注册应该成功")
        
        # 验证能力存在
        capability = self.capability_manager.get_capability("test_http_get")
        self.assertIsNotNone(capability, "应该能获取已注册的能力")
        self.assertEqual(capability.name, "test_http_get")
        self.assertEqual(capability.node_id, "08")
    
    async def test_capability_discovery(self):
        """测试能力发现"""
        # 注册多个能力
        await self.capability_manager.register_capability(
            "test_cap_1", "测试能力1", "node1", "Node1", "test"
        )
        await self.capability_manager.register_capability(
            "test_cap_2", "测试能力2", "node2", "Node2", "test"
        )
        
        # 发现所有测试类别的能力
        capabilities = self.capability_manager.discover_capabilities(category="test")
        
        self.assertGreaterEqual(len(capabilities), 2, "应该至少找到2个测试能力")
        
        # 按节点查找
        node1_caps = self.capability_manager.get_node_capabilities("node1")
        self.assertEqual(len(node1_caps), 1, "节点1应该有1个能力")
    
    async def test_capability_status_update(self):
        """测试能力状态更新"""
        from core.capability_manager import CapabilityStatus
        
        # 注册能力
        await self.capability_manager.register_capability(
            "test_status", "状态测试", "node_test", "TestNode", "test"
        )
        
        # 更新状态
        success = await self.capability_manager.update_capability_status(
            "test_status", CapabilityStatus.OFFLINE
        )
        
        self.assertTrue(success, "状态更新应该成功")
        
        # 验证状态
        capability = self.capability_manager.get_capability("test_status")
        self.assertEqual(capability.status, CapabilityStatus.OFFLINE)
    
    async def test_connection_registration(self):
        """测试连接注册"""
        # 注册连接
        success = await self.connection_manager.register_connection(
            connection_id="test_node_08",
            url="http://localhost:8008"
        )
        
        self.assertTrue(success, "连接注册应该成功")
        
        # 验证连接存在
        conn_info = self.connection_manager.get_connection("test_node_08")
        self.assertIsNotNone(conn_info, "应该能获取已注册的连接")
        self.assertEqual(conn_info.url, "http://localhost:8008")
    
    async def test_connection_lifecycle(self):
        """测试连接生命周期"""
        from core.connection_manager import ConnectionState
        
        # 注册连接
        conn_id = "test_lifecycle"
        await self.connection_manager.register_connection(
            conn_id, "http://localhost:8000"
        )
        
        # 检查初始状态
        conn_info = self.connection_manager.get_connection(conn_id)
        self.assertEqual(conn_info.state, ConnectionState.DISCONNECTED)
        
        # 断开连接（测试断开流程）
        await self.connection_manager.disconnect(conn_id)
        conn_info = self.connection_manager.get_connection(conn_id)
        self.assertEqual(conn_info.state, ConnectionState.CLOSED)
    
    async def test_stats_reporting(self):
        """测试统计报告"""
        # 能力统计
        cap_stats = self.capability_manager.get_stats()
        self.assertIn("total_capabilities", cap_stats)
        self.assertIn("online", cap_stats)
        self.assertGreaterEqual(cap_stats["total_capabilities"], 0)
        
        # 连接统计
        conn_stats = self.connection_manager.get_stats()
        self.assertIn("total_connections", conn_stats)
        self.assertIn("connected", conn_stats)
        self.assertGreaterEqual(conn_stats["total_connections"], 0)
    
    async def asyncTearDown(self):
        """测试清理"""
        # 清理测试数据
        test_capabilities = [
            "test_http_get", "test_cap_1", "test_cap_2", "test_status"
        ]
        
        for cap_name in test_capabilities:
            try:
                await self.capability_manager.unregister_capability(cap_name)
            except:
                pass
        
        # 清理测试连接
        test_connections = ["test_node_08", "test_lifecycle"]
        for conn_id in test_connections:
            try:
                await self.connection_manager.disconnect(conn_id)
            except:
                pass


class TestSystemIntegration(unittest.TestCase):
    """系统集成测试"""
    
    def test_capability_manager_singleton(self):
        """测试能力管理器单例"""
        from core.capability_manager import get_capability_manager
        
        manager1 = get_capability_manager()
        manager2 = get_capability_manager()
        
        self.assertIs(manager1, manager2, "应该返回同一个实例")
    
    def test_connection_manager_singleton(self):
        """测试连接管理器单例"""
        from core.connection_manager import get_connection_manager
        
        manager1 = get_connection_manager()
        manager2 = get_connection_manager()
        
        self.assertIs(manager1, manager2, "应该返回同一个实例")
    
    def test_imports(self):
        """测试模块导入"""
        # 测试能力管理器导入
        try:
            from core.capability_manager import (
                CapabilityManager, 
                Capability, 
                CapabilityStatus,
                get_capability_manager
            )
            self.assertTrue(True, "能力管理器模块导入成功")
        except ImportError as e:
            self.fail(f"能力管理器模块导入失败: {e}")
        
        # 测试连接管理器导入
        try:
            from core.connection_manager import (
                ConnectionManager,
                ConnectionInfo,
                ConnectionState,
                get_connection_manager
            )
            self.assertTrue(True, "连接管理器模块导入成功")
        except ImportError as e:
            self.fail(f"连接管理器模块导入失败: {e}")


def run_tests():
    """运行测试"""
    # 创建测试套件
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestCapabilityIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestSystemIntegration))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 返回结果
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    print("""
╔═══════════════════════════════════════════════════════════════╗
║   能力注册和连接管理 - 集成测试                              ║
║   Capability & Connection Management Integration Tests        ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    exit_code = run_tests()
    sys.exit(exit_code)
