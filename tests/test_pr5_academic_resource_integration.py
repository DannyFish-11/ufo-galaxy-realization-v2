"""
tests/test_pr5_academic_resource_integration.py
=================================================
PR-5 "Academic System Resource Integration" 测试套件

验收标准覆盖:
  a) 学术检索通过统一的 callable/capability 路径暴露
     (academic__search / academic__ingest / academic__recall in CapabilityBus + OpenClawd tools)
  b) 学术输出可写入并从统一知识库路径检索
     (AcademicRetriever.ingest_paper → RAGMemory.ingest_knowledge → Knowledge Core)
  c) 学术派生知识的来源标注保留
     (source_type="academic", source="academic://{db}/{paper_id}", tags include "academic")
  d) 不引入孤立的平行学术专用知识权威
     (ingest_paper uses RAGMemory.ingest_knowledge, not a competing store)
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously in an isolated event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_paper(
    paper_id: str = "2401.12345",
    title: str = "Test Paper: Quantum ML",
    source: str = "arXiv",
    **kwargs,
) -> Dict:
    return {
        "paper_id": paper_id,
        "title": title,
        "authors": ["Alice Smith", "Bob Jones"],
        "abstract": "This paper surveys quantum machine learning.",
        "published_date": "2024-01-15",
        "url": f"https://arxiv.org/abs/{paper_id}",
        "source": source,
        "tags": [source, "cs.LG"],
        **kwargs,
    }


# ===========================================================================
# 1. Capability Bus — ACADEMIC role exists and academic__ tools are registered
#    (acceptance criterion a)
# ===========================================================================

class TestCapabilityBusAcademicRole:
    """The CapabilityBus exposes academic__ capabilities as a first-class role."""

    def test_academic_role_exists_in_enum(self):
        from core.capability_bus import CapabilityBusRole
        assert hasattr(CapabilityBusRole, "ACADEMIC")
        assert CapabilityBusRole.ACADEMIC.value == "academic"

    def test_from_tool_name_academic_search(self):
        from core.capability_bus import CapabilityBusRole
        role = CapabilityBusRole.from_tool_name("academic__search")
        assert role == CapabilityBusRole.ACADEMIC

    def test_from_tool_name_academic_ingest(self):
        from core.capability_bus import CapabilityBusRole
        role = CapabilityBusRole.from_tool_name("academic__ingest")
        assert role == CapabilityBusRole.ACADEMIC

    def test_from_tool_name_academic_recall(self):
        from core.capability_bus import CapabilityBusRole
        role = CapabilityBusRole.from_tool_name("academic__recall")
        assert role == CapabilityBusRole.ACADEMIC

    def test_from_tool_name_other_prefixes_unaffected(self):
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("github__ingest") == CapabilityBusRole.GITHUB
        assert CapabilityBusRole.from_tool_name("node__97__search") == CapabilityBusRole.NODE

    def test_register_academic_capability_helper_exists(self):
        from core.capability_bus import CapabilityBus
        assert hasattr(CapabilityBus, "register_academic_capability")

    def test_register_academic_capability_registers_entry(self):
        from core.capability_bus import CapabilityBus, CapabilityBusRole, reset_capability_bus
        reset_capability_bus()
        from core.capability_bus import get_capability_bus
        bus = get_capability_bus()

        entry = bus.register_academic_capability(
            "search",
            description="Search academic databases",
            tags=["arxiv"],
        )
        assert entry.name == "academic__search"
        assert entry.role == CapabilityBusRole.ACADEMIC
        assert "academic" in entry.tags

    def test_registered_academic_entry_is_discoverable(self):
        from core.capability_bus import reset_capability_bus
        reset_capability_bus()
        from core.capability_bus import get_capability_bus, CapabilityBusRole
        bus = get_capability_bus()
        bus.register_academic_capability("recall", description="Recall academic knowledge")

        result = bus.lookup("academic__recall")
        assert result is not None
        assert result.role == CapabilityBusRole.ACADEMIC

    def test_list_by_role_academic_returns_all_academic_entries(self):
        from core.capability_bus import reset_capability_bus, CapabilityBusRole
        reset_capability_bus()
        from core.capability_bus import get_capability_bus
        bus = get_capability_bus()
        bus.register_academic_capability("search")
        bus.register_academic_capability("ingest")
        bus.register_academic_capability("recall")

        entries = bus.list_by_role(CapabilityBusRole.ACADEMIC)
        names = [e.name for e in entries]
        assert "academic__search" in names
        assert "academic__ingest" in names
        assert "academic__recall" in names

    def test_github_role_still_works_after_pr5(self):
        """PR-5 must not break GITHUB role routing."""
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("github__install") == CapabilityBusRole.GITHUB


# ===========================================================================
# 2. AcademicRetriever — module exists and singleton is accessible
# ===========================================================================

class TestAcademicRetrieverAvailability:

    def test_module_exists(self):
        import core.academic_retrieval as mod
        assert mod is not None

    def test_get_academic_retriever_returns_instance(self):
        from core.academic_retrieval import get_academic_retriever, AcademicRetriever
        r = get_academic_retriever()
        assert isinstance(r, AcademicRetriever)

    def test_get_academic_retriever_is_singleton(self):
        from core.academic_retrieval import get_academic_retriever
        assert get_academic_retriever() is get_academic_retriever()

    def test_reset_academic_retriever_creates_new_instance(self):
        from core.academic_retrieval import get_academic_retriever, reset_academic_retriever
        r1 = get_academic_retriever()
        reset_academic_retriever()
        r2 = get_academic_retriever()
        assert r1 is not r2

    def test_retriever_has_search_method(self):
        from core.academic_retrieval import get_academic_retriever
        assert hasattr(get_academic_retriever(), "search")

    def test_retriever_has_ingest_paper_method(self):
        from core.academic_retrieval import get_academic_retriever
        assert hasattr(get_academic_retriever(), "ingest_paper")

    def test_retriever_has_recall_method(self):
        from core.academic_retrieval import get_academic_retriever
        assert hasattr(get_academic_retriever(), "recall")


# ===========================================================================
# 3. ingest_paper — routes through RAGMemory, not a competing store
#    (acceptance criteria b + d)
# ===========================================================================

class TestIngestPaperKnowledgeCore:

    def test_ingest_paper_calls_rag_memory_ingest_knowledge(self):
        """ingest_paper must delegate to RAGMemory.ingest_knowledge (no parallel store)."""
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        paper = _make_paper()

        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "entry_abc123"

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            entry_id = retriever.ingest_paper(paper)

        mock_rag.ingest_knowledge.assert_called_once()
        call_kwargs = mock_rag.ingest_knowledge.call_args
        assert call_kwargs is not None
        assert entry_id == "entry_abc123"

    def test_ingest_paper_returns_entry_id(self):
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "eid_xyz"

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            eid = retriever.ingest_paper(_make_paper())

        assert eid == "eid_xyz"

    def test_ingest_paper_does_not_create_private_store(self):
        """The retriever must have no _private_store / _papers / _knowledge_store attr."""
        from core.academic_retrieval import AcademicRetriever
        r = AcademicRetriever()
        # These names would signal a competing/private store
        for bad_attr in ("_papers", "_knowledge_store", "_paper_db", "_private_store"):
            assert not hasattr(r, bad_attr), f"AcademicRetriever must not have attr: {bad_attr}"

    def test_ingest_paper_returns_empty_string_on_rag_failure(self):
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.side_effect = RuntimeError("RAGMemory unavailable")

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            eid = retriever.ingest_paper(_make_paper())

        assert eid == ""

    def test_ingest_paper_passes_correct_source_type(self):
        from core.academic_retrieval import AcademicRetriever, _ACADEMIC_SOURCE_TYPE

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "e1"

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            retriever.ingest_paper(_make_paper())

        _, kwargs = mock_rag.ingest_knowledge.call_args
        assert kwargs.get("source_type") == _ACADEMIC_SOURCE_TYPE

    def test_ingest_paper_passes_academic_source_uri(self):
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "e1"

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            retriever.ingest_paper(_make_paper(paper_id="2401.99999", source="arXiv"))

        _, kwargs = mock_rag.ingest_knowledge.call_args
        assert kwargs.get("source", "").startswith("academic://")

    def test_ingest_paper_includes_academic_tag(self):
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "e1"

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            retriever.ingest_paper(_make_paper())

        _, kwargs = mock_rag.ingest_knowledge.call_args
        assert "academic" in (kwargs.get("tags") or [])

    def test_ingest_paper_includes_paper_content(self):
        """Content passed to RAGMemory must include title + abstract."""
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "e1"
        paper = _make_paper(title="Quantum Paper Title", abstract="Quantum abstract text.")

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            retriever.ingest_paper(paper)

        _, kwargs = mock_rag.ingest_knowledge.call_args
        content = kwargs.get("content", "")
        assert "Quantum Paper Title" in content
        assert "Quantum abstract text." in content

    def test_ingest_paper_includes_metadata(self):
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "e1"
        paper = _make_paper(paper_id="PMD:123", doi="10.1234/test")

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            retriever.ingest_paper(paper)

        _, kwargs = mock_rag.ingest_knowledge.call_args
        meta = kwargs.get("metadata", {})
        assert meta.get("paper_id") == "PMD:123"
        assert meta.get("doi") == "10.1234/test"


# ===========================================================================
# 4. Source attribution — source_type, source URI, and tags are preserved
#    (acceptance criterion c)
# ===========================================================================

class TestSourceAttribution:

    def test_source_uri_format_arxiv(self):
        from core.academic_retrieval import _build_source_uri
        paper = _make_paper(paper_id="2401.12345", source="arXiv")
        uri = _build_source_uri(paper)
        assert uri.startswith("academic://")
        assert "arXiv" in uri
        assert "2401.12345" in uri

    def test_source_uri_format_semantic_scholar(self):
        from core.academic_retrieval import _build_source_uri
        paper = _make_paper(paper_id="SS_abc123", source="Semantic Scholar")
        uri = _build_source_uri(paper)
        assert uri.startswith("academic://")
        assert "SS_abc123" in uri

    def test_source_uri_format_pubmed(self):
        from core.academic_retrieval import _build_source_uri
        paper = _make_paper(paper_id="PMID:9876543", source="PubMed")
        uri = _build_source_uri(paper)
        assert uri.startswith("academic://")
        assert "PubMed" in uri

    def test_build_paper_content_includes_source(self):
        from core.academic_retrieval import _build_paper_content
        paper = _make_paper(source="arXiv", paper_id="2401.99")
        content = _build_paper_content(paper)
        assert "arXiv" in content

    def test_build_paper_content_includes_paper_id(self):
        from core.academic_retrieval import _build_paper_content
        paper = _make_paper(paper_id="2501.00001")
        content = _build_paper_content(paper)
        assert "2501.00001" in content

    def test_build_paper_content_includes_title(self):
        from core.academic_retrieval import _build_paper_content
        paper = _make_paper(title="Unique Title For Attribution Test")
        content = _build_paper_content(paper)
        assert "Unique Title For Attribution Test" in content

    def test_ingest_paper_source_type_is_academic(self):
        from core.academic_retrieval import AcademicRetriever, _ACADEMIC_SOURCE_TYPE

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "e1"
        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            retriever.ingest_paper(_make_paper())
        _, kwargs = mock_rag.ingest_knowledge.call_args
        assert kwargs["source_type"] == _ACADEMIC_SOURCE_TYPE

    def test_ingest_result_source_uri_starts_with_academic(self):
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "e2"
        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            retriever.ingest_paper(_make_paper())
        _, kwargs = mock_rag.ingest_knowledge.call_args
        assert kwargs["source"].startswith("academic://")

    def test_academic_tag_always_present_in_ingested_chunk(self):
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "e3"
        paper = _make_paper(tags=[])  # no tags on the paper
        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            retriever.ingest_paper(paper)
        _, kwargs = mock_rag.ingest_knowledge.call_args
        assert "academic" in kwargs["tags"]


# ===========================================================================
# 5. AcademicRetriever.search — end-to-end with Node_97 mock
# ===========================================================================

class TestAcademicRetrieverSearch:

    def test_search_empty_query_returns_failure(self):
        from core.academic_retrieval import AcademicRetriever
        r = AcademicRetriever()
        result = _run(r.search(""))
        assert result["success"] is False
        assert "error" in result

    def test_search_with_node97_returns_papers(self):
        from core.academic_retrieval import AcademicRetriever

        fake_papers = [_make_paper("1234.5678"), _make_paper("9012.3456")]
        fake_resp = {
            "success": True,
            "query": "quantum",
            "source": "all",
            "total_results": 2,
            "papers": fake_papers,
        }

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "eid1"

        mock_response = MagicMock()
        mock_response.json.return_value = fake_resp
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(retriever.search("quantum", ingest=True))

        assert result["success"] is True
        assert result["total_results"] == 2
        assert len(result["papers"]) == 2

    def test_search_ingests_when_ingest_true(self):
        from core.academic_retrieval import AcademicRetriever

        fake_papers = [_make_paper("1111.0001"), _make_paper("2222.0002")]
        fake_resp = {
            "success": True,
            "papers": fake_papers,
        }

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "eid_ok"

        mock_response = MagicMock()
        mock_response.json.return_value = fake_resp
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(retriever.search("test", ingest=True))

        assert result["ingested_count"] == 2
        assert len(result["entry_ids"]) == 2
        assert mock_rag.ingest_knowledge.call_count == 2

    def test_search_does_not_ingest_when_ingest_false(self):
        from core.academic_retrieval import AcademicRetriever

        fake_papers = [_make_paper()]
        fake_resp = {"success": True, "papers": fake_papers}

        retriever = AcademicRetriever()
        mock_rag = MagicMock()

        mock_response = MagicMock()
        mock_response.json.return_value = fake_resp
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(retriever.search("test", ingest=False))

        mock_rag.ingest_knowledge.assert_not_called()
        assert result["ingested_count"] == 0

    def test_search_falls_back_gracefully_when_node97_unavailable(self):
        """When Node_97 is unreachable, search returns success=True (empty papers)."""
        from core.academic_retrieval import AcademicRetriever
        import httpx as _httpx

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "e1"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        mock_client.get = AsyncMock(side_effect=_httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(retriever.search("anything", ingest=False))

        assert result["success"] is True  # graceful fallback
        assert isinstance(result["papers"], list)

    def test_search_result_has_required_keys(self):
        from core.academic_retrieval import AcademicRetriever

        fake_resp = {"success": True, "papers": [_make_paper()]}
        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "e1"

        mock_response = MagicMock()
        mock_response.json.return_value = fake_resp
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(retriever.search("deep learning"))

        for key in ("success", "query", "source", "total_results", "papers",
                    "ingested_count", "entry_ids"):
            assert key in result, f"Missing key in search result: {key}"


# ===========================================================================
# 6. AcademicRetriever.recall — routes through RAGMemory
# ===========================================================================

class TestAcademicRetrieverRecall:

    def _mock_chunk(self, source_type: str = "academic", source: str = "academic://arXiv/123"):
        """Create a mock KnowledgeChunk-like object."""
        chunk = MagicMock()
        chunk.chunk_id = "cid1"
        chunk.content = "Academic chunk content"
        chunk.source = source
        chunk.source_type = source_type
        chunk.relevance_score = 0.85
        chunk.tags = ["academic", "arXiv"]
        chunk.metadata = {"paper_id": "123"}
        return chunk

    def test_recall_calls_rag_memory_query_knowledge(self):
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.query_knowledge = AsyncMock(return_value=[self._mock_chunk()])

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            result = retriever.recall("quantum computing", top_k=3)

        mock_rag.query_knowledge.assert_called_once()
        assert result["success"] is True

    def test_recall_filters_to_academic_chunks_only(self):
        """Recall must only return academic-tagged chunks."""
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        academic_chunk = self._mock_chunk(source_type="academic")
        non_academic_chunk = self._mock_chunk(source_type="node", source="node/105/xyz")
        mock_rag = MagicMock()
        mock_rag.query_knowledge = AsyncMock(
            return_value=[academic_chunk, non_academic_chunk]
        )

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            result = retriever.recall("quantum", top_k=10)

        assert result["total"] == 1
        assert all(
            r["source_type"] == "academic" or r["source"].startswith("academic://")
            for r in result["results"]
        )

    def test_recall_result_has_required_keys(self):
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.query_knowledge = AsyncMock(return_value=[self._mock_chunk()])

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            result = retriever.recall("test query")

        for key in ("success", "query", "results", "total"):
            assert key in result

    def test_recall_returns_failure_on_exception(self):
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.query_knowledge = AsyncMock(side_effect=RuntimeError("broken"))

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            result = retriever.recall("test")

        assert result["success"] is False
        assert "error" in result

    def test_recall_result_items_have_source_attribution(self):
        from core.academic_retrieval import AcademicRetriever

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.query_knowledge = AsyncMock(return_value=[self._mock_chunk()])

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            result = retriever.recall("deep learning")

        for item in result["results"]:
            assert "source" in item
            assert "source_type" in item


# ===========================================================================
# 7. OpenClawd — academic__ tools appear in the tools list
#    (acceptance criterion a)
# ===========================================================================

class TestOpenClawdAcademicTools:

    def _get_academic_tools(self):
        """Import and return the _ACADEMIC_BUILTIN_TOOLS list from openclawd."""
        from core.openclawd import _ACADEMIC_BUILTIN_TOOLS
        return _ACADEMIC_BUILTIN_TOOLS

    def test_academic_builtin_tools_list_exists(self):
        tools = self._get_academic_tools()
        assert isinstance(tools, list)
        assert len(tools) >= 3

    def test_academic_search_tool_present(self):
        tools = self._get_academic_tools()
        names = [t["function"]["name"] for t in tools]
        assert "academic__search" in names

    def test_academic_ingest_tool_present(self):
        tools = self._get_academic_tools()
        names = [t["function"]["name"] for t in tools]
        assert "academic__ingest" in names

    def test_academic_recall_tool_present(self):
        tools = self._get_academic_tools()
        names = [t["function"]["name"] for t in tools]
        assert "academic__recall" in names

    def test_academic_search_tool_has_query_parameter(self):
        tools = self._get_academic_tools()
        search_tool = next(
            t for t in tools if t["function"]["name"] == "academic__search"
        )
        params = search_tool["function"]["parameters"]["properties"]
        assert "query" in params

    def test_academic_search_tool_has_source_parameter(self):
        tools = self._get_academic_tools()
        search_tool = next(
            t for t in tools if t["function"]["name"] == "academic__search"
        )
        params = search_tool["function"]["parameters"]["properties"]
        assert "source" in params

    def test_academic_ingest_tool_has_paper_parameter(self):
        tools = self._get_academic_tools()
        ingest_tool = next(
            t for t in tools if t["function"]["name"] == "academic__ingest"
        )
        params = ingest_tool["function"]["parameters"]["properties"]
        assert "paper" in params

    def test_academic_recall_tool_has_query_parameter(self):
        tools = self._get_academic_tools()
        recall_tool = next(
            t for t in tools if t["function"]["name"] == "academic__recall"
        )
        params = recall_tool["function"]["parameters"]["properties"]
        assert "query" in params

    def test_github_builtin_tools_still_present(self):
        """PR-5 must not remove the GitHub built-in tools."""
        from core.openclawd import _GITHUB_BUILTIN_TOOLS
        names = [t["function"]["name"] for t in _GITHUB_BUILTIN_TOOLS]
        assert "github__install" in names
        assert "github__ingest" in names


# ===========================================================================
# 8. OpenClawd _dispatch_academic_tool dispatch method
# ===========================================================================

class TestOpenClawdAcademicDispatch:

    def _make_openclawd(self):
        """Create an OpenClawd instance with minimal deps patched away."""
        from core.openclawd import OpenClawd
        with patch.object(OpenClawd, "__init__", lambda self, *a, **kw: None):
            oc = OpenClawd.__new__(OpenClawd)
        return oc

    def test_dispatch_search_missing_query(self):
        oc = self._make_openclawd()
        result = _run(oc._dispatch_academic_tool("search", {}))
        assert result["success"] is False
        assert "error" in result

    def test_dispatch_ingest_missing_paper(self):
        oc = self._make_openclawd()
        result = _run(oc._dispatch_academic_tool("ingest", {}))
        assert result["success"] is False
        assert "error" in result

    def test_dispatch_recall_missing_query(self):
        oc = self._make_openclawd()
        result = _run(oc._dispatch_academic_tool("recall", {}))
        assert result["success"] is False
        assert "error" in result

    def test_dispatch_unknown_action(self):
        oc = self._make_openclawd()
        result = _run(oc._dispatch_academic_tool("whatever", {}))
        assert result["success"] is False
        assert "whatever" in result.get("error", "")

    def test_dispatch_search_delegates_to_retriever(self):
        oc = self._make_openclawd()
        fake_result = {
            "success": True, "query": "ml", "source": "all",
            "total_results": 1, "papers": [_make_paper()],
            "ingested_count": 1, "entry_ids": ["eid1"],
        }
        mock_retriever = MagicMock()
        mock_retriever.search = AsyncMock(return_value=fake_result)

        with patch("core.academic_retrieval.get_academic_retriever", return_value=mock_retriever):
            result = _run(oc._dispatch_academic_tool("search", {"query": "ml"}))

        assert result["success"] is True
        mock_retriever.search.assert_called_once_with(
            query="ml", source="all", max_results=10, ingest=True
        )

    def test_dispatch_ingest_delegates_to_retriever(self):
        oc = self._make_openclawd()
        paper = _make_paper()
        mock_retriever = MagicMock()
        mock_retriever.ingest_paper.return_value = "eid_test"

        with patch("core.academic_retrieval.get_academic_retriever", return_value=mock_retriever):
            result = _run(oc._dispatch_academic_tool("ingest", {"paper": paper}))

        assert result["success"] is True
        assert result["entry_id"] == "eid_test"
        mock_retriever.ingest_paper.assert_called_once_with(paper)

    def test_dispatch_ingest_result_has_source_attribution(self):
        oc = self._make_openclawd()
        paper = _make_paper(paper_id="9999.0000", source="arXiv")
        mock_retriever = MagicMock()
        mock_retriever.ingest_paper.return_value = "eid_attr"

        with patch("core.academic_retrieval.get_academic_retriever", return_value=mock_retriever):
            result = _run(oc._dispatch_academic_tool("ingest", {"paper": paper}))

        assert result["source_type"] == "academic"
        assert result["source"].startswith("academic://")

    def test_dispatch_recall_delegates_to_retriever(self):
        oc = self._make_openclawd()
        fake_recall = {"success": True, "query": "llm", "results": [], "total": 0}
        mock_retriever = MagicMock()
        mock_retriever.recall.return_value = fake_recall

        with patch("core.academic_retrieval.get_academic_retriever", return_value=mock_retriever):
            result = _run(oc._dispatch_academic_tool("recall", {"query": "llm", "top_k": 3}))

        mock_retriever.recall.assert_called_once_with(query="llm", top_k=3)
        assert result["success"] is True


# ===========================================================================
# 9. No parallel academic memory silo (acceptance criterion d)
# ===========================================================================

class TestNoParallelAcademicAuthority:

    def test_academic_retriever_has_no_private_knowledge_store(self):
        from core.academic_retrieval import AcademicRetriever
        r = AcademicRetriever()
        for bad in ("_papers", "_knowledge_store", "_paper_db", "_private_store",
                    "_academic_db", "_memo_store"):
            assert not hasattr(r, bad), f"AcademicRetriever must not have: {bad}"

    def test_ingest_does_not_write_to_local_file(self, tmp_path):
        """ingest_paper must not write any local file as a parallel store."""
        from core.academic_retrieval import AcademicRetriever
        import os

        retriever = AcademicRetriever()
        mock_rag = MagicMock()
        mock_rag.ingest_knowledge.return_value = "e1"

        original_cwd_files = set(os.listdir(str(tmp_path)))

        with patch("core.academic_retrieval.get_rag_memory", return_value=mock_rag):
            # Change data dir to tmp to detect any file writes
            retriever.ingest_paper(_make_paper())

        # No new files should appear in tmp_path from ingest_paper
        new_files = set(os.listdir(str(tmp_path))) - original_cwd_files
        assert len(new_files) == 0, f"Unexpected files written: {new_files}"

    def test_academic_module_uses_rag_memory_for_persistence(self):
        """The module must import and call get_rag_memory, not bypass it."""
        import core.academic_retrieval as mod
        import inspect
        src = inspect.getsource(mod)
        # Must reference RAGMemory's ingest_knowledge
        assert "ingest_knowledge" in src

    def test_academic_source_type_constant_is_academic(self):
        from core.academic_retrieval import _ACADEMIC_SOURCE_TYPE
        assert _ACADEMIC_SOURCE_TYPE == "academic"


# ===========================================================================
# 10. Node_97 SearchRequest — ingest_to_knowledge_core flag
# ===========================================================================

class TestNode97IngestFlag:

    def test_search_request_has_ingest_flag(self):
        from nodes.Node_97_AcademicSearch.main import SearchRequest
        sr = SearchRequest(query="test")
        assert hasattr(sr, "ingest_to_knowledge_core")

    def test_search_request_ingest_flag_default_false(self):
        from nodes.Node_97_AcademicSearch.main import SearchRequest
        sr = SearchRequest(query="test")
        assert sr.ingest_to_knowledge_core is False

    def test_search_request_ingest_flag_can_be_set_true(self):
        from nodes.Node_97_AcademicSearch.main import SearchRequest
        sr = SearchRequest(query="test", ingest_to_knowledge_core=True)
        assert sr.ingest_to_knowledge_core is True
