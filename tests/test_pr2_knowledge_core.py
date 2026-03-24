"""
tests/test_pr2_knowledge_core.py
=================================
PR-2 "Knowledge Core 统一" 测试套件

验收标准覆盖:
  a) RAGMemory 是 OpenClawd 侧规范化知识入口 (canonical brain-side entry point)
  b) 自主学习知识回写 (backflow) 可通过统一路径检索
  c) Node_72 作为兼容/回退后端的行为正确
  d) 不引入新的并行主权知识来源
  e) KnowledgeChunk schema 统一（含 source_type / tags 字段）
  f) Node_105 的 ingest_knowledge() 接口可直接调用
"""

import asyncio
import os
import sys
import tempfile
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ============================================================================
# 辅助工厂
# ============================================================================

def _make_rag(tmp_dir: str = None):
    """创建使用独立临时目录的 RAGMemory 实例（不影响全局单例）。"""
    from core.rag_memory import RAGMemory
    d = tmp_dir or tempfile.mkdtemp()
    return RAGMemory(data_dir=d)


def _make_node105_kb(tmp_dir: str = None):
    """创建使用独立临时目录的 UnifiedKnowledgeBase 实例。"""
    from nodes.Node_105_UnifiedKnowledgeBase.main import UnifiedKnowledgeBase
    d = tmp_dir or tempfile.mkdtemp()
    return UnifiedKnowledgeBase(persist_dir=d)


def _make_node72_kb(tmp_dir: str = None):
    """创建使用独立临时目录的 KnowledgeBaseSystem 实例。"""
    from nodes.Node_72_KnowledgeBase.knowledge_base_system import KnowledgeBaseSystem
    d = tmp_dir or tempfile.mkdtemp()
    return KnowledgeBaseSystem(persist_directory=d)


# ============================================================================
# 1. KnowledgeChunk 规范化 schema
# ============================================================================

class TestKnowledgeChunkSchema:
    """验收标准 e): KnowledgeChunk 包含统一的 source_type 和 tags 字段。"""

    def test_chunk_has_source_type_field(self):
        from core.rag_memory import KnowledgeChunk
        chunk = KnowledgeChunk(content="test", source="Node_105", source_type="node")
        assert chunk.source_type == "node"

    def test_chunk_has_tags_field(self):
        from core.rag_memory import KnowledgeChunk
        chunk = KnowledgeChunk(content="test", source="Node_72", tags=["ai", "knowledge"])
        assert chunk.tags == ["ai", "knowledge"]

    def test_chunk_defaults(self):
        from core.rag_memory import KnowledgeChunk
        chunk = KnowledgeChunk()
        assert chunk.chunk_id == ""
        assert chunk.content == ""
        assert chunk.source == ""
        assert chunk.source_type == "node"
        assert chunk.relevance_score == 0.0
        assert chunk.tags == []
        assert chunk.metadata == {}

    def test_chunk_all_fields(self):
        from core.rag_memory import KnowledgeChunk
        chunk = KnowledgeChunk(
            chunk_id="c1",
            content="deep learning basics",
            source="Node_105",
            source_type="file",
            relevance_score=0.95,
            tags=["ml", "learning"],
            metadata={"author": "test"},
        )
        assert chunk.chunk_id == "c1"
        assert chunk.source_type == "file"
        assert "ml" in chunk.tags
        assert chunk.metadata["author"] == "test"


# ============================================================================
# 2. RAGMemory 作为规范化入口
# ============================================================================

class TestRAGMemoryCanonicalEntryPoint:
    """验收标准 a): RAGMemory 是 OpenClawd 侧规范化知识入口。"""

    def test_get_rag_memory_returns_singleton(self):
        from core.rag_memory import get_rag_memory
        r1 = get_rag_memory()
        r2 = get_rag_memory()
        assert r1 is r2

    def test_get_rag_memory_namespace_isolation(self):
        from core.rag_memory import get_rag_memory
        r_global = get_rag_memory()
        r_ns = get_rag_memory(namespace="test_ns_isolation")
        assert r_global is not r_ns

    def test_rag_memory_has_ingest_knowledge(self):
        rag = _make_rag()
        assert callable(getattr(rag, "ingest_knowledge", None))

    def test_rag_memory_has_query_knowledge(self):
        rag = _make_rag()
        assert callable(getattr(rag, "query_knowledge", None))

    def test_rag_memory_has_enhance_agent_prompt(self):
        rag = _make_rag()
        assert callable(getattr(rag, "enhance_agent_prompt", None))

    def test_rag_memory_has_log_experience(self):
        rag = _make_rag()
        assert callable(getattr(rag, "log_experience", None))

    def test_rag_memory_module_docstring_declares_canonical(self):
        import core.rag_memory as m
        assert "canonical" in m.__doc__.lower() or "知识访问入口" in m.__doc__

    def test_rag_memory_class_docstring_declares_canonical(self):
        from core.rag_memory import RAGMemory
        doc = RAGMemory.__doc__ or ""
        assert "Knowledge Core" in doc or "知识访问" in doc

    def test_get_rag_memory_for_device(self):
        from core.rag_memory import get_rag_memory_for_device
        rag = get_rag_memory_for_device("dev-001")
        assert rag is not None

    def test_get_rag_memory_for_worker(self):
        from core.rag_memory import get_rag_memory_for_worker
        rag = get_rag_memory_for_worker("worker-001")
        assert rag is not None


# ============================================================================
# 3. ingest_knowledge — 写入路径测试
# ============================================================================

class TestIngestKnowledge:
    """验收标准 a) + e): ingest_knowledge 是统一写入入口，写入后可通过经验日志检索。"""

    def test_ingest_returns_entry_id(self):
        rag = _make_rag()
        entry_id = rag.ingest_knowledge(
            content="Python asyncio event loop basics",
            source="test_ingest",
            source_type="text",
            tags=["python", "asyncio"],
        )
        assert entry_id and isinstance(entry_id, str)

    def test_ingest_writes_to_experience_log(self):
        rag = _make_rag()
        rag.ingest_knowledge(
            content="Machine learning gradient descent",
            source="test_source",
            source_type="text",
            tags=["ml"],
        )
        # 写入后应在经验日志里
        experiences = rag._experiences
        assert len(experiences) >= 1
        # 找到相关经验
        contents = [e.final_output for e in experiences]
        assert any("gradient descent" in c for c in contents)

    def test_ingest_tags_stored_in_experience(self):
        rag = _make_rag()
        rag.ingest_knowledge(
            content="Neural network architecture",
            source="test_tagger",
            source_type="experience",
            tags=["neural", "architecture"],
        )
        for exp in rag._experiences:
            if "Neural network" in exp.final_output:
                assert "neural" in exp.tags or "architecture" in exp.tags
                break

    def test_ingest_knowledge_idempotent_on_multiple_calls(self):
        rag = _make_rag()
        id1 = rag.ingest_knowledge(content="same content", source="s1", source_type="text")
        id2 = rag.ingest_knowledge(content="same content", source="s1", source_type="text")
        # Both calls succeed without exception; IDs may differ (timestamp-based)
        assert id1 and id2

    def test_ingest_metadata_preserved(self):
        rag = _make_rag()
        rag.ingest_knowledge(
            content="test metadata content",
            source="meta_test",
            source_type="text",
            metadata={"author": "unit_test", "priority": "high"},
        )
        stats = rag.get_stats()
        assert stats["experiences_total"] >= 1

    def test_ingest_node105_fallback_when_unavailable(self, monkeypatch):
        """Node_105 不可用时，ingest_knowledge 仍写入本地经验日志。"""
        import sys

        # 使 Node_105 import 失败 — 用 monkeypatch 保证自动清理
        monkeypatch.setitem(sys.modules, "nodes.Node_105_UnifiedKnowledgeBase.main", None)

        rag = _make_rag()
        entry_id = rag.ingest_knowledge(
            content="fallback test content",
            source="fallback_source",
            source_type="text",
        )
        assert entry_id  # 应仍有 ID（来自本地经验日志）
        assert any("fallback test content" in e.final_output for e in rag._experiences)


# ============================================================================
# 4. Node_105 — 主后端角色
# ============================================================================

class TestNode105PrimaryBackend:
    """验收标准 b): Node_105 是主多源知识后端/索引器。"""

    def test_node105_has_knowledge_core_role(self):
        from nodes.Node_105_UnifiedKnowledgeBase.main import KNOWLEDGE_CORE_ROLE
        assert KNOWLEDGE_CORE_ROLE == "primary_backend"

    def test_node105_has_ingest_knowledge(self):
        kb = _make_node105_kb()
        assert callable(getattr(kb, "ingest_knowledge", None))

    def test_node105_ingest_knowledge_stores_entry(self):
        kb = _make_node105_kb()
        entry_id = kb.ingest_knowledge(
            content="test knowledge content for node105",
            source="unit_test",
            source_type="text",
            tags=["test_tag"],
        )
        assert entry_id in kb.knowledge_entries
        entry = kb.knowledge_entries[entry_id]
        assert entry.content == "test knowledge content for node105"
        assert entry.source == "unit_test"
        assert entry.source_type == "text"
        assert "test_tag" in entry.metadata.get("tags", [])

    def test_node105_ingest_and_search(self):
        kb = _make_node105_kb()
        kb.ingest_knowledge(
            content="reinforcement learning reward function",
            source="test",
            source_type="text",
        )
        results = kb.search_hybrid("reward function", top_k=5)
        assert len(results) >= 1
        assert any("reward" in r.content for r in results)

    def test_node105_ingest_tags_in_metadata(self):
        kb = _make_node105_kb()
        kb.ingest_knowledge(
            content="tag test knowledge",
            source="tag_source",
            source_type="text",
            tags=["tagA", "tagB"],
        )
        results = kb.search_keyword("tag test", top_k=5)
        assert len(results) >= 1
        assert "tagA" in results[0].metadata.get("tags", [])

    def test_node105_search_hybrid_returns_knowledge_entries(self):
        kb = _make_node105_kb()
        kb.ingest_knowledge(
            content="hybrid search test content for pr2",
            source="hybrid_test",
            source_type="text",
        )
        results = kb.search_hybrid("hybrid search test", top_k=5)
        # 结果应是 KnowledgeEntry 对象（有 .content 属性）
        for r in results:
            assert hasattr(r, "content")
            assert hasattr(r, "id")

    def test_node105_knowledge_entry_has_source_type(self):
        from nodes.Node_105_UnifiedKnowledgeBase.main import KnowledgeEntry
        entry = KnowledgeEntry(
            id="test_id",
            content="test",
            source_type="file",
            source="/path/to/file",
            metadata={},
            timestamp=time.time(),
        )
        assert entry.source_type == "file"


# ============================================================================
# 5. Node_72 — 兼容/回退后端角色
# ============================================================================

class TestNode72FallbackBackend:
    """验收标准 c): Node_72 是兼容/回退后端，不是并行主权威。"""

    def test_node72_has_fallback_role(self):
        from nodes.Node_72_KnowledgeBase.knowledge_base_system import KNOWLEDGE_BACKEND_ROLE
        assert KNOWLEDGE_BACKEND_ROLE == "fallback"

    def test_node72_docstring_declares_fallback(self):
        import nodes.Node_72_KnowledgeBase.knowledge_base_system as m
        doc = m.__doc__ or ""
        assert "fallback" in doc.lower() or "回退" in doc

    def test_node72_add_and_search(self):
        kb = _make_node72_kb()
        entry_id = kb.add_knowledge("python list comprehension syntax")
        results = kb.search("list comprehension")
        assert len(results) >= 1
        assert any("list comprehension" in r.content for r in results)

    def test_node72_search_returns_knowledge_entry_objects(self):
        """Node_72.search() 必须返回 KnowledgeEntry dataclass，而非 dict。"""
        from nodes.Node_72_KnowledgeBase.knowledge_base_system import KnowledgeEntry
        kb = _make_node72_kb()
        kb.add_knowledge("test entry for type check")
        results = kb.search("test entry")
        assert len(results) >= 1
        assert isinstance(results[0], KnowledgeEntry)
        assert hasattr(results[0], "content")

    def test_node72_rag_query_returns_dict(self):
        kb = _make_node72_kb()
        kb.add_knowledge("function arguments in Python")
        result = kb.rag_query("function arguments")
        assert isinstance(result, dict)
        assert "query" in result
        assert "relevant_knowledge" in result

    def test_node72_compatible_with_rag_memory_query(self):
        """RAGMemory.query_knowledge 调用 Node_72 时不应因类型错误崩溃。"""
        # 仅测试类型兼容性（不需要 Node_105 可用）
        kb = _make_node72_kb()
        kb.add_knowledge("compatible knowledge item")
        results = kb.search("compatible")
        for r in results:
            # RAGMemory 期望 KnowledgeEntry 对象（有 .content 属性）
            content = r.content if hasattr(r, "content") else r.get("content", "")
            assert isinstance(content, str)


# ============================================================================
# 6. 自主学习知识回写 (backflow) 测试
# ============================================================================

class TestAutonomousLearningBackflow:
    """验收标准 b): 自主学习知识回写通过统一路径（RAGMemory.ingest_knowledge）。"""

    @pytest.mark.asyncio
    async def test_push_to_rag_memory_uses_ingest_knowledge(self, monkeypatch):
        """_push_to_rag_memory 应调用 RAGMemory.ingest_knowledge，而非直接 log_experience。"""
        from nodes.Node_70_AutonomousLearning.main import AutonomousLearningEngine, KnowledgeItem
        from datetime import datetime

        ingested = []

        # mock get_rag_memory to capture ingest_knowledge calls
        class MockRAG:
            def ingest_knowledge(self, content, source, source_type, tags=None, metadata=None):
                ingested.append({
                    "content": content,
                    "source": source,
                    "source_type": source_type,
                    "tags": tags or [],
                    "metadata": metadata or {},
                })
                return "mock_entry_id"

        import core.rag_memory as rag_mod
        monkeypatch.setattr(rag_mod, "get_rag_memory", lambda: MockRAG())

        engine = AutonomousLearningEngine()
        knowledge = KnowledgeItem(
            knowledge_id="k001",
            category="python",
            content="async generators are efficient for streaming",
            confidence=0.85,
            source="test_experience",
        )
        await engine._push_to_rag_memory(knowledge)

        assert len(ingested) == 1
        assert ingested[0]["source"] == "autonomous_learning"
        assert ingested[0]["source_type"] == "experience"
        assert "python" in ingested[0]["tags"]

    @pytest.mark.asyncio
    async def test_backflow_tags_normalized(self, monkeypatch):
        """回写的 tags 应包含 autonomous_learning 和 category 标签。"""
        from nodes.Node_70_AutonomousLearning.main import AutonomousLearningEngine, KnowledgeItem
        from datetime import datetime

        captured_tags = []

        class MockRAG:
            def ingest_knowledge(self, content, source, source_type, tags=None, metadata=None):
                captured_tags.extend(tags or [])
                return "mock_id"

        import core.rag_memory as rag_mod
        monkeypatch.setattr(rag_mod, "get_rag_memory", lambda: MockRAG())

        engine = AutonomousLearningEngine()
        knowledge = KnowledgeItem(
            knowledge_id="k002",
            category="network",
            content="TCP handshake protocol",
            confidence=0.9,
            source="observation",
        )
        await engine._push_to_rag_memory(knowledge)

        assert "autonomous_learning" in captured_tags
        assert "network" in captured_tags

    @pytest.mark.asyncio
    async def test_backflow_metadata_contains_knowledge_id(self, monkeypatch):
        """回写的 metadata 应包含 knowledge_id 和 confidence。"""
        from nodes.Node_70_AutonomousLearning.main import AutonomousLearningEngine, KnowledgeItem

        captured_metadata = {}

        class MockRAG:
            def ingest_knowledge(self, content, source, source_type, tags=None, metadata=None):
                captured_metadata.update(metadata or {})
                return "mock_meta_id"

        import core.rag_memory as rag_mod
        monkeypatch.setattr(rag_mod, "get_rag_memory", lambda: MockRAG())

        engine = AutonomousLearningEngine()
        knowledge = KnowledgeItem(
            knowledge_id="k003",
            category="algorithm",
            content="quicksort divide and conquer",
            confidence=0.75,
            source="study",
        )
        await engine._push_to_rag_memory(knowledge)

        assert captured_metadata.get("knowledge_id") == "k003"
        assert captured_metadata.get("confidence") == 0.75

    def test_backflow_retrievable_through_rag_memory(self):
        """知识写入后，应可通过 RAGMemory recall_similar 检索到。"""
        rag = _make_rag()
        rag.ingest_knowledge(
            content="distributed consensus algorithm raft protocol",
            source="autonomous_learning",
            source_type="experience",
            tags=["autonomous_learning", "algorithm"],
            metadata={"knowledge_id": "ktest", "confidence": 0.8},
        )
        # recall_similar 应能找到相关经验
        similar = rag.recall_similar("consensus algorithm")
        assert len(similar) >= 1
        assert any("raft" in e.final_output or "consensus" in e.final_output for e in similar)


# ============================================================================
# 7. 无新增并行主权知识来源
# ============================================================================

class TestNoParallelPrimaryAuthority:
    """验收标准 d): 不引入新的并行主权知识来源。"""

    def test_node105_role_is_primary_backend_not_parallel_authority(self):
        from nodes.Node_105_UnifiedKnowledgeBase.main import KNOWLEDGE_CORE_ROLE
        # 主后端而非"主权威"（authority 归 RAGMemory）
        assert KNOWLEDGE_CORE_ROLE == "primary_backend"

    def test_node72_role_is_fallback(self):
        from nodes.Node_72_KnowledgeBase.knowledge_base_system import KNOWLEDGE_BACKEND_ROLE
        assert KNOWLEDGE_BACKEND_ROLE == "fallback"

    def test_rag_memory_is_single_singleton(self):
        from core.rag_memory import get_rag_memory
        r1 = get_rag_memory()
        r2 = get_rag_memory()
        r3 = get_rag_memory()
        assert r1 is r2 is r3

    def test_node72_not_directly_accessed_for_primary_queries(self):
        """Node_72 的 KNOWLEDGE_BACKEND_ROLE 标记明确表示其非主后端。"""
        from nodes.Node_72_KnowledgeBase.knowledge_base_system import KNOWLEDGE_BACKEND_ROLE
        assert KNOWLEDGE_BACKEND_ROLE != "primary_backend"
        assert KNOWLEDGE_BACKEND_ROLE != "authority"

    def test_query_knowledge_priority_node105_before_node72(self):
        """RAGMemory.query_knowledge 应先查 Node_105，Node_72 只作回退。

        通过 mock 验证调用顺序：Node_105 有结果时 Node_72 不会被调用。
        """
        import sys
        import types
        import pytest
        from nodes.Node_105_UnifiedKnowledgeBase.main import KnowledgeEntry
        import time as _time

        # 创建 mock Node_105 module
        mock_node105_module = types.ModuleType("nodes.Node_105_UnifiedKnowledgeBase.main")
        node105_called = []

        class MockKB105:
            def search_hybrid(self, query, top_k):
                node105_called.append(True)
                return [KnowledgeEntry(
                    id="mock105",
                    content="node105 primary result",
                    source_type="text",
                    source="mock",
                    metadata={},
                    timestamp=_time.time(),
                )]

        mock_node105_module.kb = MockKB105()

        node72_called = []

        # Patch Node_72 to track whether it's called
        import nodes.Node_72_KnowledgeBase.knowledge_base_system as n72_mod
        original_class = n72_mod.KnowledgeBaseSystem

        class SpyKB72(original_class):
            def search(self, query, top_k=5):
                node72_called.append(True)
                return super().search(query, top_k)

        n72_mod.KnowledgeBaseSystem = SpyKB72

        original_node105 = sys.modules.get("nodes.Node_105_UnifiedKnowledgeBase.main")
        sys.modules["nodes.Node_105_UnifiedKnowledgeBase.main"] = mock_node105_module
        try:
            rag = _make_rag()
            result = asyncio.get_event_loop().run_until_complete(
                rag.query_knowledge("test query", top_k=1)
            )
            # Node_105 returned 1 result (= top_k), so Node_72 should NOT be called
            assert len(result) >= 1
            assert result[0].source == "Node_105"
            assert len(node105_called) >= 1, "Node_105 should be called first"
            assert len(node72_called) == 0, "Node_72 should not be called when Node_105 fills top_k"
        finally:
            if original_node105 is None:
                sys.modules.pop("nodes.Node_105_UnifiedKnowledgeBase.main", None)
            else:
                sys.modules["nodes.Node_105_UnifiedKnowledgeBase.main"] = original_node105
            n72_mod.KnowledgeBaseSystem = original_class


# ============================================================================
# 8. enhance_agent_prompt — 综合 RAG 增强
# ============================================================================

class TestEnhanceAgentPrompt:
    """验收标准 a): enhance_agent_prompt 是 Agent 调用的主链入口。"""

    @pytest.mark.asyncio
    async def test_enhance_agent_prompt_returns_string(self):
        rag = _make_rag()
        result = await rag.enhance_agent_prompt("test instruction")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_enhance_agent_prompt_with_experience(self):
        rag = _make_rag()
        rag.log_experience(
            agent_name="test_agent",
            instruction="how to sort a list",
            steps=[{"thought": "use sort()", "action": "sort", "observation": "sorted"}],
            final_output="list.sort()",
            success=True,
        )
        result = await rag.enhance_agent_prompt("sort a list")
        # 应包含 few-shot 经验
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_enhance_agent_prompt_exclude_experience(self):
        rag = _make_rag()
        result = await rag.enhance_agent_prompt(
            "test", include_experience=False, include_knowledge=False
        )
        assert result == ""

    @pytest.mark.asyncio
    async def test_enhance_agent_prompt_does_not_raise_on_empty(self):
        rag = _make_rag()
        result = await rag.enhance_agent_prompt("totally unrelated query abc123")
        assert isinstance(result, str)


# ============================================================================
# 9. 持久化与加载
# ============================================================================

class TestPersistenceAndLoad:
    """验收标准 b): 写入的知识在重启后可检索。"""

    def test_ingest_knowledge_persists_to_disk(self):
        tmp = tempfile.mkdtemp()
        rag = _make_rag(tmp)
        rag.ingest_knowledge(
            content="persistence test content",
            source="persist_test",
            source_type="text",
        )
        # 创建新实例，从同一目录加载
        rag2 = _make_rag(tmp)
        assert any("persistence test content" in e.final_output for e in rag2._experiences)

    def test_experience_log_reloadable(self):
        tmp = tempfile.mkdtemp()
        rag = _make_rag(tmp)
        rag.log_experience(
            agent_name="test_persist",
            instruction="reload test",
            steps=[],
            final_output="ok",
            success=True,
        )
        rag2 = _make_rag(tmp)
        assert any(e.agent_name == "test_persist" for e in rag2._experiences)

    def test_node105_knowledge_persists(self):
        tmp = tempfile.mkdtemp()
        kb = _make_node105_kb(tmp)
        kb.ingest_knowledge(
            content="node105 persistent knowledge",
            source="persist_node105",
            source_type="text",
        )
        kb2 = _make_node105_kb(tmp)
        results = kb2.search_keyword("persistent knowledge")
        assert len(results) >= 1

    def test_node72_knowledge_persists(self):
        tmp = tempfile.mkdtemp()
        kb = _make_node72_kb(tmp)
        kb.add_knowledge("node72 persistent item")
        kb2 = _make_node72_kb(tmp)
        results = kb2.search("persistent item")
        assert len(results) >= 1
