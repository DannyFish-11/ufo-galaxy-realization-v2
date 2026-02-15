"""
Node_108_MetaCognition 测试文件
"""

import pytest
import requests
import time
from typing import Dict, Any

# 测试配置
NODE_URL = "http://localhost:9100"
TIMEOUT = 5


class TestNode108MetaCognition:
    """Node_108_MetaCognition 测试类"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """测试前检查节点是否运行"""
        try:
            response = requests.get(f"{NODE_URL}/health", timeout=TIMEOUT)
            assert response.status_code == 200
        except requests.exceptions.ConnectionError:
            pytest.skip("Node_108_MetaCognition is not running")
    
    def test_root_endpoint(self):
        """测试根端点"""
        response = requests.get(f"{NODE_URL}/", timeout=TIMEOUT)
        assert response.status_code == 200
        data = response.json()
        assert data["node"] == "Node_108_MetaCognition"
        assert data["status"] == "running"
    
    def test_health_check(self):
        """测试健康检查"""
        response = requests.get(f"{NODE_URL}/health", timeout=TIMEOUT)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "cognitive_state" in data
    
    def test_track_thought(self):
        """测试追踪思维"""
        payload = {
            "thought_type": "analysis",
            "content": "分析用户需求，发现需要元认知能力",
            "context": {
                "task": "system_enhancement",
                "user_query": "系统能否反思自己？"
            }
        }
        
        response = requests.post(
            f"{NODE_URL}/api/v1/track_thought",
            json=payload,
            timeout=TIMEOUT
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "thought_id" in data
        assert data["thought_type"] == "analysis"
        assert "quality_score" in data
        assert 0 <= data["quality_score"] <= 1
        assert isinstance(data["biases_detected"], list)
    
    def test_track_thought_invalid_type(self):
        """测试追踪思维 - 无效类型"""
        payload = {
            "thought_type": "invalid_type",
            "content": "测试内容",
            "context": {}
        }
        
        response = requests.post(
            f"{NODE_URL}/api/v1/track_thought",
            json=payload,
            timeout=TIMEOUT
        )
        
        assert response.status_code == 400
    
    def test_track_decision(self):
        """测试追踪决策"""
        payload = {
            "decision_content": "开发 Node_108_MetaCognition",
            "alternatives": [
                "使用现有 LLM",
                "外部服务"
            ],
            "reasoning": "需要深度集成到系统中，提供实时元认知能力",
            "confidence": 0.85
        }
        
        response = requests.post(
            f"{NODE_URL}/api/v1/track_decision",
            json=payload,
            timeout=TIMEOUT
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "decision_id" in data
        assert data["decision_content"] == payload["decision_content"]
        assert data["confidence"] == 0.85
        
        # 返回 decision_id 供后续测试使用
        return data["decision_id"]
    
    def test_evaluate_decision(self):
        """测试评估决策"""
        # 先创建一个决策
        decision_id = self.test_track_decision()
        
        # 评估决策
        payload = {
            "decision_id": decision_id,
            "outcome": {
                "success_score": 0.9,
                "actual_result": "成功开发并部署",
                "time_taken": 7200
            }
        }
        
        response = requests.post(
            f"{NODE_URL}/api/v1/evaluate_decision",
            json=payload,
            timeout=TIMEOUT
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["decision_id"] == decision_id
        assert "overall_quality" in data
        assert 0 <= data["overall_quality"] <= 1
        assert "success_score" in data
        assert "confidence_match" in data
        assert "reasoning_quality" in data
    
    def test_evaluate_decision_not_found(self):
        """测试评估决策 - 决策不存在"""
        payload = {
            "decision_id": "nonexistent_decision",
            "outcome": {
                "success_score": 0.9
            }
        }
        
        response = requests.post(
            f"{NODE_URL}/api/v1/evaluate_decision",
            json=payload,
            timeout=TIMEOUT
        )
        
        assert response.status_code == 404
    
    def test_evaluate_decision_missing_success_score(self):
        """测试评估决策 - 缺少 success_score"""
        decision_id = self.test_track_decision()
        
        payload = {
            "decision_id": decision_id,
            "outcome": {
                "actual_result": "成功"
            }
        }
        
        response = requests.post(
            f"{NODE_URL}/api/v1/evaluate_decision",
            json=payload,
            timeout=TIMEOUT
        )
        
        assert response.status_code == 400
    
    def test_reflect(self):
        """测试反思"""
        # 先创建一些思维和决策
        self.test_track_thought()
        self.test_track_decision()
        
        # 反思最近的活动
        payload = {
            "time_window": 60  # 最近60秒
        }
        
        response = requests.post(
            f"{NODE_URL}/api/v1/reflect",
            json=payload,
            timeout=TIMEOUT
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "timestamp" in data
        assert "thought_patterns" in data
        assert "decision_patterns" in data
        assert "improvement_opportunities" in data
        assert "cognitive_state" in data
    
    def test_reflect_all_history(self):
        """测试反思 - 所有历史"""
        payload = {
            "time_window": None
        }
        
        response = requests.post(
            f"{NODE_URL}/api/v1/reflect",
            json=payload,
            timeout=TIMEOUT
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["time_window"] is None
    
    def test_optimize_strategy(self):
        """测试优化策略"""
        payload = {
            "task_description": "集成外部开发工具",
            "current_strategy": {
                "approach": "逐个工具开发专用节点",
                "priority": "OpenCode 优先",
                "timeline": "2周"
            }
        }
        
        response = requests.post(
            f"{NODE_URL}/api/v1/optimize_strategy",
            json=payload,
            timeout=TIMEOUT
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "original_strategy" in data
        assert "analysis" in data
        assert "recommended_changes" in data
        assert "expected_improvements" in data
    
    def test_get_cognitive_state(self):
        """测试获取认知状态"""
        response = requests.get(
            f"{NODE_URL}/api/v1/cognitive_state",
            timeout=TIMEOUT
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "total_thoughts" in data
        assert "total_decisions" in data
        assert "average_decision_quality" in data
        assert "detected_biases" in data
    
    def test_get_thought_history(self):
        """测试获取思维历史"""
        response = requests.get(
            f"{NODE_URL}/api/v1/thought_history?limit=10",
            timeout=TIMEOUT
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_get_decision_history(self):
        """测试获取决策历史"""
        response = requests.get(
            f"{NODE_URL}/api/v1/decision_history?limit=10",
            timeout=TIMEOUT
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    def test_cognitive_bias_detection(self):
        """测试认知偏差检测"""
        # 测试确认偏差
        payload = {
            "thought_type": "analysis",
            "content": "这个证据证实了我的假设，验证了我的想法",
            "context": {}
        }
        
        response = requests.post(
            f"{NODE_URL}/api/v1/track_thought",
            json=payload,
            timeout=TIMEOUT
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "confirmation_bias" in data["biases_detected"]
        
        # 测试过度自信
        payload = {
            "thought_type": "decision",
            "content": "我肯定这个方案一定会成功，绝对没问题",
            "context": {}
        }
        
        response = requests.post(
            f"{NODE_URL}/api/v1/track_thought",
            json=payload,
            timeout=TIMEOUT
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "overconfidence" in data["biases_detected"]
    
    def test_complete_workflow(self):
        """测试完整工作流"""
        # 1. 追踪思维
        thought_response = requests.post(
            f"{NODE_URL}/api/v1/track_thought",
            json={
                "thought_type": "perception",
                "content": "用户询问系统能否自主学习工具",
                "context": {"user_query": "能用 OpenCode 吗？"}
            },
            timeout=TIMEOUT
        )
        assert thought_response.status_code == 200
        
        # 2. 追踪决策
        decision_response = requests.post(
            f"{NODE_URL}/api/v1/track_decision",
            json={
                "decision_content": "开发通用工具包装器",
                "alternatives": ["专用节点", "手动脚本"],
                "reasoning": "通用方案扩展性最强",
                "confidence": 0.8
            },
            timeout=TIMEOUT
        )
        assert decision_response.status_code == 200
        decision_id = decision_response.json()["decision_id"]
        
        # 3. 评估决策
        eval_response = requests.post(
            f"{NODE_URL}/api/v1/evaluate_decision",
            json={
                "decision_id": decision_id,
                "outcome": {"success_score": 0.85}
            },
            timeout=TIMEOUT
        )
        assert eval_response.status_code == 200
        
        # 4. 反思
        reflect_response = requests.post(
            f"{NODE_URL}/api/v1/reflect",
            json={"time_window": 60},
            timeout=TIMEOUT
        )
        assert reflect_response.status_code == 200
        
        # 5. 优化策略
        optimize_response = requests.post(
            f"{NODE_URL}/api/v1/optimize_strategy",
            json={
                "task_description": "工具集成",
                "current_strategy": {"approach": "通用包装器"}
            },
            timeout=TIMEOUT
        )
        assert optimize_response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
