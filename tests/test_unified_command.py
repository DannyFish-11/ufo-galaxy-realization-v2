"""
Galaxy - 统一命令端点测试
================================

测试 /api/v1/command 端点的各项功能：
- 同步/异步执行
- 多目标支持
- 鉴权机制
- 状态查询
- 超时控制
"""

import asyncio
import os
import sys
import unittest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi.testclient import TestClient
from fastapi import FastAPI

# 导入要测试的模块
from core.auth import verify_api_token, verify_device_id, require_auth
from core.api_routes import (
    create_api_routes,
    CommandStatus,
    UnifiedCommandRequest,
    UnifiedCommandResponse,
    TargetResult
)


class TestAuthModule(unittest.TestCase):
    """测试鉴权模块"""
    
    def setUp(self):
        """设置测试环境"""
        # 保存原始环境变量
        self.original_token = os.environ.get("Galaxy_API_TOKEN")
    
    def tearDown(self):
        """清理测试环境"""
        # 恢复原始环境变量
        if self.original_token is not None:
            os.environ["Galaxy_API_TOKEN"] = self.original_token
        elif "Galaxy_API_TOKEN" in os.environ:
            del os.environ["Galaxy_API_TOKEN"]
    
    def test_verify_api_token_dev_mode(self):
        """测试开发模式（未设置 Token）"""
        # 移除环境变量
        if "Galaxy_API_TOKEN" in os.environ:
            del os.environ["Galaxy_API_TOKEN"]
        
        # 开发模式下应该跳过鉴权
        self.assertTrue(verify_api_token("any-token"))
    
    def test_verify_api_token_valid(self):
        """测试有效 Token"""
        test_token = "test-token-12345"
        os.environ["Galaxy_API_TOKEN"] = test_token
        
        self.assertTrue(verify_api_token(test_token))
    
    def test_verify_api_token_invalid(self):
        """测试无效 Token"""
        os.environ["Galaxy_API_TOKEN"] = "correct-token"
        
        self.assertFalse(verify_api_token("wrong-token"))
    
    def test_verify_device_id_valid(self):
        """测试有效 Device ID"""
        self.assertTrue(verify_device_id("device-001"))
        self.assertTrue(verify_device_id("android-device-12345"))
    
    def test_verify_device_id_invalid(self):
        """测试无效 Device ID"""
        self.assertFalse(verify_device_id(""))
        self.assertFalse(verify_device_id("ab"))
        self.assertFalse(verify_device_id(None))


class TestPydanticModels(unittest.TestCase):
    """测试 Pydantic 模型"""
    
    def test_command_status_enum(self):
        """测试命令状态枚举"""
        self.assertEqual(CommandStatus.QUEUED, "queued")
        self.assertEqual(CommandStatus.RUNNING, "running")
        self.assertEqual(CommandStatus.DONE, "done")
        self.assertEqual(CommandStatus.FAILED, "failed")
    
    def test_target_result_model(self):
        """测试 TargetResult 模型"""
        result = TargetResult(
            status=CommandStatus.DONE,
            output={"message": "success"},
            error=None,
            started_at="2026-02-12T10:00:00Z",
            completed_at="2026-02-12T10:00:05Z"
        )
        
        self.assertEqual(result.status, CommandStatus.DONE)
        self.assertEqual(result.output["message"], "success")
        self.assertIsNone(result.error)
    
    def test_unified_command_request_defaults(self):
        """测试 UnifiedCommandRequest 默认值"""
        request = UnifiedCommandRequest(
            command="test_command",
            targets=["device_1"]
        )
        
        self.assertIsNone(request.request_id)
        self.assertEqual(request.mode, "sync")
        self.assertEqual(request.timeout, 30)
        self.assertEqual(request.params, {})
    
    def test_unified_command_request_custom(self):
        """测试 UnifiedCommandRequest 自定义值"""
        request_id = str(uuid.uuid4())
        request = UnifiedCommandRequest(
            request_id=request_id,
            command="screenshot",
            targets=["device_1", "device_2"],
            params={"quality": 90},
            mode="async",
            timeout=60
        )
        
        self.assertEqual(request.request_id, request_id)
        self.assertEqual(request.command, "screenshot")
        self.assertEqual(len(request.targets), 2)
        self.assertEqual(request.params["quality"], 90)
        self.assertEqual(request.mode, "async")
        self.assertEqual(request.timeout, 60)


@pytest.mark.asyncio
class TestUnifiedCommandEndpoint:
    """测试统一命令端点（使用 pytest）"""
    
    @pytest.fixture
    def app(self):
        """创建测试应用"""
        app = FastAPI()
        router = create_api_routes()
        app.include_router(router)
        return app
    
    @pytest.fixture
    def client(self, app):
        """创建测试客户端"""
        return TestClient(app)
    
    @pytest.fixture(autouse=True)
    def setup_env(self):
        """设置测试环境"""
        # 清除 Token 以使用开发模式
        original_token = os.environ.get("Galaxy_API_TOKEN")
        if "Galaxy_API_TOKEN" in os.environ:
            del os.environ["Galaxy_API_TOKEN"]
        
        yield
        
        # 恢复环境变量
        if original_token is not None:
            os.environ["Galaxy_API_TOKEN"] = original_token
    
    def test_unified_command_sync_mode_basic(self, client):
        """测试同步模式基本功能"""
        payload = {
            "command": "test_command",
            "targets": ["device_1"],
            "mode": "sync",
            "timeout": 10
        }
        
        # 注意：由于没有真实的设备连接，这个测试会返回失败状态
        # 但我们可以验证端点的基本功能
        response = client.post("/api/v1/command", json=payload)
        
        # 应该返回 200 或 408（超时）
        assert response.status_code in [200, 408]
        
        if response.status_code == 200:
            data = response.json()
            assert "request_id" in data
            assert "status" in data
            assert "results" in data
    
    def test_unified_command_async_mode_basic(self, client):
        """测试异步模式基本功能"""
        payload = {
            "command": "test_command",
            "targets": ["device_1"],
            "mode": "async"
        }
        
        response = client.post("/api/v1/command", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert "request_id" in data
        assert data["status"] == "queued"
        assert "created_at" in data
    
    def test_unified_command_multi_target(self, client):
        """测试多目标支持"""
        payload = {
            "command": "get_status",
            "targets": ["device_1", "device_2", "device_3"],
            "mode": "sync",
            "timeout": 5
        }
        
        response = client.post("/api/v1/command", json=payload)
        
        # 验证响应格式
        assert response.status_code in [200, 408]
        
        if response.status_code == 200:
            data = response.json()
            assert "results" in data
            # 结果应该包含所有目标
            assert len(data["results"]) == 3
    
    def test_unified_command_invalid_mode(self, client):
        """测试无效的执行模式"""
        payload = {
            "command": "test_command",
            "targets": ["device_1"],
            "mode": "invalid_mode"
        }
        
        response = client.post("/api/v1/command", json=payload)
        
        assert response.status_code == 400
        assert "Invalid mode" in response.json()["detail"]
    
    def test_unified_command_empty_targets(self, client):
        """测试空目标列表"""
        payload = {
            "command": "test_command",
            "targets": [],
            "mode": "sync"
        }
        
        response = client.post("/api/v1/command", json=payload)
        
        assert response.status_code == 400
        assert "cannot be empty" in response.json()["detail"]
    
    def test_unified_command_request_id_generation(self, client):
        """测试 request_id 自动生成"""
        payload = {
            "command": "test_command",
            "targets": ["device_1"],
            "mode": "async"
        }
        
        response = client.post("/api/v1/command", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        
        # 验证 request_id 是有效的 UUID
        request_id = data["request_id"]
        try:
            uuid.UUID(request_id)
            valid_uuid = True
        except ValueError:
            valid_uuid = False
        
        assert valid_uuid
    
    def test_unified_command_custom_request_id(self, client):
        """测试自定义 request_id"""
        custom_id = str(uuid.uuid4())
        payload = {
            "request_id": custom_id,
            "command": "test_command",
            "targets": ["device_1"],
            "mode": "async"
        }
        
        response = client.post("/api/v1/command", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["request_id"] == custom_id
    
    def test_get_command_status_not_found(self, client):
        """测试查询不存在的命令状态"""
        fake_id = str(uuid.uuid4())
        response = client.get(f"/api/v1/command/{fake_id}/status")
        
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
    
    def test_get_command_status_after_async_submit(self, client):
        """测试异步提交后查询状态"""
        # 提交异步命令
        payload = {
            "command": "test_command",
            "targets": ["device_1"],
            "mode": "async"
        }
        
        submit_response = client.post("/api/v1/command", json=payload)
        assert submit_response.status_code == 200
        
        request_id = submit_response.json()["request_id"]
        
        # 查询状态
        status_response = client.get(f"/api/v1/command/{request_id}/status")
        assert status_response.status_code == 200
        
        data = status_response.json()
        assert data["request_id"] == request_id
        assert "status" in data
        assert "created_at" in data


class TestUnifiedCommandEndpointWithAuth(unittest.TestCase):
    """测试带鉴权的统一命令端点"""
    
    def setUp(self):
        """设置测试环境"""
        # 设置 Token
        os.environ["Galaxy_API_TOKEN"] = "test-token-12345"
        
        # 创建测试应用
        self.app = FastAPI()
        router = create_api_routes()
        self.app.include_router(router)
        self.client = TestClient(self.app)
    
    def tearDown(self):
        """清理测试环境"""
        if "Galaxy_API_TOKEN" in os.environ:
            del os.environ["Galaxy_API_TOKEN"]
    
    def test_command_without_auth(self):
        """测试未提供鉴权信息"""
        payload = {
            "command": "test_command",
            "targets": ["device_1"],
            "mode": "sync"
        }
        
        response = self.client.post("/api/v1/command", json=payload)
        
        # 应该返回 401 未授权
        self.assertEqual(response.status_code, 401)
    
    def test_command_with_invalid_auth(self):
        """测试无效的鉴权信息"""
        payload = {
            "command": "test_command",
            "targets": ["device_1"],
            "mode": "sync"
        }
        
        headers = {
            "Authorization": "Bearer wrong-token"
        }
        
        response = self.client.post("/api/v1/command", json=payload, headers=headers)
        
        # 应该返回 401 未授权
        self.assertEqual(response.status_code, 401)
    
    def test_command_with_valid_auth(self):
        """测试有效的鉴权信息"""
        payload = {
            "command": "test_command",
            "targets": ["device_1"],
            "mode": "async"
        }
        
        headers = {
            "Authorization": "Bearer test-token-12345"
        }
        
        response = self.client.post("/api/v1/command", json=payload, headers=headers)
        
        # 应该返回 200
        self.assertEqual(response.status_code, 200)
    
    def test_command_with_device_id_header(self):
        """测试 X-Device-ID header"""
        payload = {
            "command": "test_command",
            "targets": ["device_1"],
            "mode": "async"
        }
        
        headers = {
            "Authorization": "Bearer test-token-12345",
            "X-Device-ID": "my-device-001"
        }
        
        response = self.client.post("/api/v1/command", json=payload, headers=headers)
        
        # 应该返回 200
        self.assertEqual(response.status_code, 200)


def run_tests():
    """运行所有测试"""
    print("=" * 70)
    print("运行统一命令端点测试套件")
    print("=" * 70)
    
    # 运行 unittest 测试
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestAuthModule))
    suite.addTests(loader.loadTestsFromTestCase(TestPydanticModels))
    suite.addTests(loader.loadTestsFromTestCase(TestUnifiedCommandEndpointWithAuth))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 70)
    print(f"测试完成: {result.testsRun} 个测试")
    print(f"成功: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    print("=" * 70)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    # 运行测试
    success = run_tests()
    
    # 如果所有测试通过，退出码为 0；否则为 1
    sys.exit(0 if success else 1)
