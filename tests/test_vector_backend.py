"""
Tests for core.vector_backend — unified vector retrieval layer.

All tests run in "local" mode (no external services required).
"""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.vector_backend import (
    SearchResult,
    _LocalKeywordBackend,
    create_vector_backend,
    get_shared_backend,
)


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------

def test_search_result_to_dict():
    sr = SearchResult(doc_id="d1", content="hello world " * 20, score=0.75, metadata={"k": "v"})
    d = sr.to_dict()
    assert d["doc_id"] == "d1"
    assert len(d["content"]) <= 200
    assert d["score"] == 0.75
    assert d["metadata"] == {"k": "v"}


# ---------------------------------------------------------------------------
# LocalKeywordBackend
# ---------------------------------------------------------------------------

class TestLocalKeywordBackend:
    def setup_method(self):
        self.backend = _LocalKeywordBackend()

    def test_add_and_search_match(self):
        self.backend.add_document("doc1", "Python programming language", {"type": "tech"})
        results = self.backend.search("Python", top_k=5)
        assert len(results) == 1
        assert results[0].doc_id == "doc1"
        assert results[0].score > 0

    def test_search_no_match(self):
        self.backend.add_document("doc1", "Python programming", {})
        results = self.backend.search("cooking recipe", top_k=5)
        assert results == []

    def test_search_returns_top_k(self):
        for i in range(10):
            self.backend.add_document(f"doc{i}", f"machine learning model {i}", {})
        results = self.backend.search("machine learning", top_k=3)
        assert len(results) <= 3

    def test_delete_document(self):
        self.backend.add_document("doc1", "test content", {})
        assert self.backend.document_count == 1
        self.backend.delete_document("doc1")
        assert self.backend.document_count == 0

    def test_is_vector_mode_false(self):
        assert self.backend.is_vector_mode is False

    def test_overwrite_document(self):
        self.backend.add_document("doc1", "old content", {})
        self.backend.add_document("doc1", "new content", {})
        results = self.backend.search("new", top_k=5)
        assert len(results) == 1
        assert results[0].doc_id == "doc1"

    def test_metadata_preserved(self):
        meta = {"source": "wiki", "category": "science"}
        self.backend.add_document("doc1", "quantum physics", meta)
        results = self.backend.search("quantum", top_k=5)
        assert results[0].metadata == meta


# ---------------------------------------------------------------------------
# create_vector_backend — local mode
# ---------------------------------------------------------------------------

def test_create_local_backend(monkeypatch):
    monkeypatch.delenv("KB_VECTOR_BACKEND", raising=False)
    backend = create_vector_backend(backend="local")
    assert backend.name == "local"
    assert backend.is_vector_mode is False


def test_create_local_backend_env(monkeypatch):
    monkeypatch.setenv("KB_VECTOR_BACKEND", "local")
    backend = create_vector_backend()
    assert backend.name == "local"


def test_create_chroma_backend_falls_back_when_not_installed(monkeypatch):
    """If chromadb is not installed, chroma backend must fall back to local."""
    monkeypatch.setenv("KB_VECTOR_BACKEND", "chroma")
    # Ensure chromadb import fails by temporarily hiding the module
    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "chromadb":
            raise ImportError("chromadb not installed (test mock)")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    backend = create_vector_backend(backend="chroma")
    assert backend.name == "local"


def test_create_qdrant_backend_falls_back_when_url_missing(monkeypatch):
    """If QDRANT_URL is empty, qdrant backend must fall back to local."""
    monkeypatch.delenv("QDRANT_URL", raising=False)
    backend = create_vector_backend(backend="qdrant", qdrant_url="")
    assert backend.name == "local"


def test_create_qdrant_backend_falls_back_when_not_installed(monkeypatch):
    """If qdrant-client is not installed and URL is set, fall back to local."""
    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "qdrant_client":
            raise ImportError("qdrant-client not installed (test mock)")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    backend = create_vector_backend(backend="qdrant", qdrant_url="http://localhost:6333")
    assert backend.name == "local"


# ---------------------------------------------------------------------------
# get_shared_backend — singleton
# ---------------------------------------------------------------------------

def test_get_shared_backend_returns_same_instance():
    import core.vector_backend as vb_module
    # Reset singleton for test isolation
    vb_module._shared_backend = None
    b1 = get_shared_backend()
    b2 = get_shared_backend()
    assert b1 is b2
    vb_module._shared_backend = None  # cleanup


# ---------------------------------------------------------------------------
# Integration: KnowledgeBaseSystem uses vector backend
# ---------------------------------------------------------------------------

def test_knowledge_base_system_local_mode(monkeypatch):
    """Node_72 KnowledgeBaseSystem should work in local mode without vector libs."""
    monkeypatch.setenv("KB_VECTOR_BACKEND", "local")
    # Reset shared backend singleton
    import core.vector_backend as vb_module
    vb_module._shared_backend = None

    from nodes.Node_72_KnowledgeBase.knowledge_base_system import KnowledgeBaseSystem

    kb = KnowledgeBaseSystem()
    entry_id = kb.add_knowledge("Python is a programming language.", {"category": "tech"})
    assert entry_id

    results = kb.search("Python", top_k=5)
    assert len(results) >= 1
    assert any(e.id == entry_id for e in results)

    stats = kb.get_statistics()
    assert stats["vector_backend"] == "local"

    vb_module._shared_backend = None  # cleanup


def test_knowledge_base_system_delete(monkeypatch):
    monkeypatch.setenv("KB_VECTOR_BACKEND", "local")
    import core.vector_backend as vb_module
    vb_module._shared_backend = None

    from nodes.Node_72_KnowledgeBase.knowledge_base_system import KnowledgeBaseSystem

    kb = KnowledgeBaseSystem()
    eid = kb.add_knowledge("delete me", {})
    assert kb.delete_knowledge(eid) is True
    assert kb.delete_knowledge(eid) is False  # second delete returns False

    vb_module._shared_backend = None


# ---------------------------------------------------------------------------
# Integration: SemanticSearch uses vector backend
# ---------------------------------------------------------------------------

def test_semantic_search_index_and_search(monkeypatch):
    """SemanticSearch.index_document / .search should work in local mode."""
    monkeypatch.setenv("KB_VECTOR_BACKEND", "local")
    import core.vector_backend as vb_module
    vb_module._shared_backend = None

    from core.ai_intent import SemanticSearch

    ss = SemanticSearch()
    ss.index_document("doc1", "neural network deep learning", {"domain": "AI"})
    results = ss.search("deep learning", top_k=5)
    assert len(results) >= 1
    assert results[0]["doc_id"] == "doc1"
    assert results[0]["score"] > 0

    vb_module._shared_backend = None


# ---------------------------------------------------------------------------
# Integration: MCP/Skill load_from_config creates template
# ---------------------------------------------------------------------------

def test_mcp_loader_singleton():
    """MCPLoader 单例应可用且有 list_servers 方法。"""
    from core.mcp_loader import mcp_loader

    servers = mcp_loader.list_servers()
    assert isinstance(servers, list)


def test_skill_loader_singleton():
    """SkillLoader 单例应可用且有 list_skills / get_stats 方法。"""
    from core.skill_loader import skill_loader

    skills = skill_loader.list_skills()
    assert isinstance(skills, list)
    stats = skill_loader.get_stats()
    assert isinstance(stats, dict)
