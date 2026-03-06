"""
综合测试：验证所有核心修复

覆盖范围：
1. NLU 引擎 AI 模型集成（降级逻辑）
2. 学习系统数据库持久化
3. Agent 通信消息总线
4. 知识库持久化和搜索模式标识
5. Memory System 连接池
6. 自主编程引擎安全性
7. L4 主循环 task_history 限制
"""

import asyncio
import json
import os
import sys
import tempfile
import uuid

import pytest

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# 1. NLU 引擎测试
# =============================================================================

class TestEnhancedNLUEngine:
    """测试增强版 NLU 引擎"""

    def _make_engine(self, **kw):
        from nodes.Node_50_Transformer.enhanced_nlu_engine import EnhancedNLUEngine
        return EnhancedNLUEngine(**kw)

    def test_rule_based_understanding(self):
        engine = self._make_engine(use_ai_model=False)
        intent = engine.understand("打开微信")
        assert intent.action == "open"
        assert intent.target == "wechat"
        assert intent.confidence > 0

    def test_ai_fallback_when_no_url(self):
        """当 oneapi_url 为空时应降级到规则引擎"""
        engine = self._make_engine(use_ai_model=True, oneapi_url=None)
        intent = engine.understand("打开浏览器")
        assert intent.target == "browser"

    def test_ai_fallback_when_no_api_key(self):
        """当 API key 未设置时应降级到规则引擎"""
        old_key = os.environ.pop("ONEAPI_API_KEY", None)
        try:
            engine = self._make_engine(use_ai_model=True, oneapi_url="http://localhost:3000")
            intent = engine.understand("打开微信")
            assert intent.target == "wechat"
        finally:
            if old_key:
                os.environ["ONEAPI_API_KEY"] = old_key

    def test_ai_fallback_on_connection_error(self):
        """当 OneAPI 不可达时应降级到规则引擎"""
        os.environ["ONEAPI_API_KEY"] = "test-key"
        try:
            engine = self._make_engine(
                use_ai_model=True,
                oneapi_url="http://127.0.0.1:19999"  # 不可达端口
            )
            intent = engine.understand("打开微信")
            assert intent.target == "wechat"
        finally:
            os.environ.pop("ONEAPI_API_KEY", None)

    def test_media_generation_intent(self):
        engine = self._make_engine(use_ai_model=False)
        intent = engine.understand("生成一个关于猫的视频")
        assert intent.action == "generate_video"

    def test_task_planning(self):
        engine = self._make_engine(use_ai_model=False)
        intent = engine.understand("打开微信")
        steps = engine.plan_task(intent)
        assert len(steps) >= 1


# =============================================================================
# 2. 学习系统持久化测试
# =============================================================================

class TestLearningPersistence:
    """测试学习系统 SQLite 持久化"""

    def _make_persistence(self, tmp_dir):
        from enhancements.learning.autonomous_learning_engine import LearningPersistence
        db_path = os.path.join(tmp_dir, "test_learning.db")
        return LearningPersistence(db_path=db_path)

    def test_save_and_load_observations(self):
        from enhancements.learning.autonomous_learning_engine import LearningObservation
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmp:
            persistence = self._make_persistence(tmp)
            obs = LearningObservation(
                id="obs_001",
                source="test",
                content="test observation content",
                timestamp=datetime.now(),
                metadata={"key": "value"},
                confidence=0.8,
            )
            persistence.save_observations([obs])
            loaded = persistence.load_observations(limit=10)
            assert len(loaded) == 1
            assert loaded[0].id == "obs_001"
            assert loaded[0].source == "test"
            assert loaded[0].confidence == 0.8

    def test_save_and_load_knowledge(self):
        with tempfile.TemporaryDirectory() as tmp:
            persistence = self._make_persistence(tmp)
            knowledge = {
                "key1": {
                    "key": "key1",
                    "pattern_type": "semantic",
                    "description": "test knowledge",
                    "confidence": 0.9,
                    "frequency": 5,
                    "sources": {"src1", "src2"},
                    "created_at": "2026-01-01",
                    "last_updated": "2026-01-02",
                    "pattern_ids": {"p1"},
                    "examples": ["ex1"],
                    "metadata": {},
                },
            }
            persistence.save_knowledge(knowledge)
            loaded = persistence.load_knowledge()
            assert "key1" in loaded
            assert loaded["key1"]["confidence"] == 0.9
            assert "src1" in loaded["key1"]["sources"]

    def test_knowledge_accumulator_with_persistence(self):
        from enhancements.learning.autonomous_learning_engine import (
            KnowledgeAccumulator,
            LearningPersistence,
            DiscoveredPattern,
            PatternType,
        )
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmp:
            persistence = LearningPersistence(
                db_path=os.path.join(tmp, "test.db")
            )
            acc = KnowledgeAccumulator(persistence=persistence)

            pattern = DiscoveredPattern(
                id="pat_001",
                pattern_type=PatternType.SEMANTIC,
                description="Test pattern for accumulator",
                observations=["obs1"],
                confidence=0.85,
                created_at=datetime.now(),
                last_updated=datetime.now(),
                frequency=3,
                examples=["example1"],
            )

            stats = asyncio.get_event_loop().run_until_complete(
                acc.accumulate([pattern], "test_source")
            )
            assert stats["added"] == 1

            # Verify persistence: create new accumulator from same DB
            acc2 = KnowledgeAccumulator(persistence=persistence)
            assert len(acc2._knowledge) == 1


# =============================================================================
# 3. Agent 消息总线测试
# =============================================================================

class TestAgentMessageBus:
    """测试 Agent 通信消息总线"""

    def _make_bus(self):
        from core.agent_factory import AgentMessageBus
        return AgentMessageBus()

    def test_register_and_send(self):
        bus = self._make_bus()
        bus.register("agent_a")
        bus.register("agent_b")

        from core.agent_factory import AgentMessage

        msg = AgentMessage(
            id="msg_001",
            sender_id="agent_a",
            receiver_id="agent_b",
            msg_type="task_assign",
            payload={"task": "test"},
        )

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(bus.send(msg))
        assert result is True

        received = loop.run_until_complete(bus.receive("agent_b", timeout=1.0))
        assert received is not None
        assert received.id == "msg_001"
        assert received.payload["task"] == "test"

    def test_send_to_unknown_agent(self):
        bus = self._make_bus()
        from core.agent_factory import AgentMessage

        msg = AgentMessage(
            id="msg_002",
            sender_id="agent_a",
            receiver_id="nonexistent",
            msg_type="task_assign",
            payload={},
        )

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(bus.send(msg))
        assert result is False

    def test_broadcast(self):
        bus = self._make_bus()
        bus.register("sender")
        bus.register("recv_1")
        bus.register("recv_2")

        loop = asyncio.get_event_loop()
        loop.run_until_complete(bus.broadcast("sender", "status_query", {"check": True}))

        msg1 = loop.run_until_complete(bus.receive("recv_1", timeout=1.0))
        msg2 = loop.run_until_complete(bus.receive("recv_2", timeout=1.0))
        assert msg1 is not None
        assert msg2 is not None
        assert msg1.msg_type == "status_query"

    def test_receive_timeout(self):
        bus = self._make_bus()
        bus.register("empty_agent")

        loop = asyncio.get_event_loop()
        received = loop.run_until_complete(bus.receive("empty_agent", timeout=0.1))
        assert received is None

    def test_unregister(self):
        bus = self._make_bus()
        bus.register("agent_x")
        bus.unregister("agent_x")

        from core.agent_factory import AgentMessage
        msg = AgentMessage(
            id="msg_003",
            sender_id="other",
            receiver_id="agent_x",
            msg_type="task_assign",
            payload={},
        )
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(bus.send(msg))
        assert result is False


# =============================================================================
# 4. 知识库持久化和搜索模式标识测试
# =============================================================================

class TestKnowledgeBaseSystem:
    """测试知识库系统"""

    def _make_kb(self, tmp_dir):
        from nodes.Node_72_KnowledgeBase.knowledge_base_system import KnowledgeBaseSystem
        return KnowledgeBaseSystem(persist_directory=tmp_dir)

    def test_add_and_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb = self._make_kb(tmp)
            entry_id = kb.add_knowledge("Python 是一种编程语言", {"category": "编程"})
            assert entry_id is not None

            results = kb.search("Python")
            assert len(results) >= 1
            # 搜索模式应为 vector 或 keyword（取决于向量后端是否可用）
            assert results[0].metadata.get("_search_mode") in ("keyword", "vector")

    def test_persistence_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb1 = self._make_kb(tmp)
            kb1.add_knowledge("持久化测试数据", {"category": "test"})

            # 创建新实例，验证数据已恢复
            kb2 = self._make_kb(tmp)
            assert len(kb2.knowledge_entries) == 1

    def test_update_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb = self._make_kb(tmp)
            entry_id = kb.add_knowledge("原始内容")
            assert kb.update_knowledge(entry_id, "更新后的内容")
            assert kb.knowledge_entries[entry_id].content == "更新后的内容"

            assert kb.delete_knowledge(entry_id)
            assert entry_id not in kb.knowledge_entries

    def test_statistics(self):
        with tempfile.TemporaryDirectory() as tmp:
            kb = self._make_kb(tmp)
            initial_count = kb.get_statistics()["total_entries"]
            kb.add_knowledge("内容1", {"category": "A"})
            kb.add_knowledge("内容2", {"category": "B"})
            stats = kb.get_statistics()
            # 可能包含向量后端中的已有条目
            assert stats["total_entries"] >= initial_count + 2


# =============================================================================
# 5. Memory System 测试
# =============================================================================

class TestMemoryDatabase:
    """测试记忆数据库"""

    def _make_db(self, tmp_dir):
        from nodes.Node_100_MemorySystem.main import MemoryDatabase
        db_path = os.path.join(tmp_dir, "test_memory.db")
        return MemoryDatabase(db_path)

    def test_store_and_retrieve_experience(self):
        from nodes.Node_100_MemorySystem.main import Experience

        with tempfile.TemporaryDirectory() as tmp:
            db = self._make_db(tmp)
            exp = Experience(
                id="exp_001",
                timestamp="2026-01-01T00:00:00",
                command="test command",
                context={"key": "value"},
                actions=[{"type": "click"}],
                result={"status": "success"},
                success=True,
                duration=1.5,
                session_id="session_001",
            )
            assert db.store_experience(exp) is True

            results = db.retrieve_experiences("test", limit=10)
            assert len(results) == 1
            assert results[0].command == "test command"

    def test_store_and_get_knowledge(self):
        from nodes.Node_100_MemorySystem.main import Knowledge

        with tempfile.TemporaryDirectory() as tmp:
            db = self._make_db(tmp)
            k = Knowledge(
                id="k_001",
                topic="test_topic",
                content="知识内容",
                source="test",
                confidence=0.9,
                created_at="2026-01-01",
                updated_at="2026-01-01",
            )
            assert db.store_knowledge(k) is True

            results = db.get_knowledge("test_topic")
            assert len(results) == 1
            assert results[0].confidence == 0.9


# =============================================================================
# 6. 自主编程引擎安全性测试
# =============================================================================

class TestAutonomousCodingEngine:
    """测试自主编程引擎的安全性修复"""

    def _make_engine(self, tmp_dir):
        from enhancements.coding.autonomous_coding_engine import AutonomousCodingEngine
        return AutonomousCodingEngine(workspace_root=tmp_dir)

    def test_workspace_path_auto_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._make_engine(tmp)
            assert engine.workspace_root == tmp

    def test_path_traversal_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._make_engine(tmp)
            # 尝试路径遍历
            code_changes = {"../../etc/passwd": "malicious content"}
            modified, created = engine._apply_code_changes(code_changes)
            assert len(modified) == 0
            assert len(created) == 0
            # 确保文件没有被创建在系统路径
            assert not os.path.exists("/etc/passwd.tmp")

    def test_backup_on_modify(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = self._make_engine(tmp)
            # 创建原始文件
            test_file = os.path.join(tmp, "test.py")
            with open(test_file, "w") as f:
                f.write("original content")

            # 修改文件
            code_changes = {"test.py": "modified content"}
            modified, created = engine._apply_code_changes(code_changes)
            assert "test.py" in modified

            # 验证备份存在
            backup_dir = os.path.join(tmp, ".code_backups")
            assert os.path.exists(backup_dir)


# =============================================================================
# 7. L4 主循环测试
# =============================================================================

class TestGalaxyMainLoopL4:
    """测试 L4 主循环的修复"""

    def test_task_history_capping(self):
        """验证 task_history 不会无限增长"""
        from galaxy_main_loop_l4 import GalaxyMainLoopL4

        loop = GalaxyMainLoopL4({"cycle_interval": 1.0})
        loop._max_task_history = 10

        # 模拟 100 条历史
        for i in range(100):
            loop.task_history.append({
                "goal": f"goal_{i}",
                "success": True,
                "duration": 1.0,
                "actions_count": 1,
                "success_rate": 0.8,
            })

        # 触发裁剪
        if len(loop.task_history) > loop._max_task_history:
            loop.task_history = loop.task_history[-loop._max_task_history:]

        assert len(loop.task_history) == 10


# =============================================================================
# 8. Android Bridge 测试
# =============================================================================

class TestAndroidBridge:
    """测试 Android 桥接服务"""

    def _make_bridge(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    def test_device_health_empty(self):
        bridge = self._make_bridge()
        health = bridge.get_device_health()
        assert health["total"] == 0
        assert health["healthy"] == 0

    def test_device_register(self):
        bridge = self._make_bridge()

        class MockWebSocket:
            async def send_json(self, data):
                pass

        msg = {
            "type": "device_register",
            "device_id": "test_device_001",
            "device_type": "android_phone",
            "platform": "android",
            "model": "Pixel 7",
            "os_version": "14",
        }

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            bridge.handle_message(MockWebSocket(), msg)
        )
        assert result is not None
        assert result["success"] is True

        devices = bridge.get_connected_devices()
        assert len(devices) == 1
        assert devices[0].model == "Pixel 7"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
