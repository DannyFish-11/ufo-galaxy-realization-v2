"""
Galaxy — Academic System Resource Integration
=============================================

Academic search/retrieval is a **first-class system resource** with three
roles:

1. **Search source** — query arXiv, Semantic Scholar, PubMed, and IEEE Xplore
   for papers on demand (original Node_97 responsibility, fully preserved via
   :class:`AcademicRetriever`).
2. **Knowledge source** — ingest paper metadata, abstracts, notes, and
   research artifacts into the unified Knowledge Core via
   :func:`~core.rag_memory.RAGMemory.ingest_knowledge`.
3. **Recall source** — retrieve previously-ingested academic knowledge through
   the unified RAG retrieval path so planners / agents can reuse research.

Design
------
:class:`AcademicRetriever` exposes three canonical entry-points:

``search(query, source, max_results, ingest)``
    Search one or more academic databases and optionally ingest all returned
    papers into the Knowledge Core.  Returns a standardised result dict
    identical in shape to Node_97's ``/search`` response.

``ingest_paper(paper)``
    Ingest a single paper dict into the Knowledge Core.  Called internally by
    ``search(..., ingest=True)`` and available for external callers who already
    hold a paper dict.  Source attribution: ``source_type="academic"``,
    ``source="academic://{source}/{paper_id}"``.

``recall(query, top_k)``
    Query the unified Knowledge Core for academic knowledge that was previously
    ingested.  Returns :class:`~core.rag_memory.KnowledgeChunk` objects tagged
    with ``source_type="academic"``.

Naming convention (capability bus)
-----------------------------------
  ``academic__search``   — search academic databases
  ``academic__ingest``   — ingest a single paper into Knowledge Core
  ``academic__recall``   — recall academic knowledge from Knowledge Core

Singletons
----------
Module-level singletons mirror the ``github_installer`` pattern::

    academic_retriever: AcademicRetriever   # created at import time
    get_academic_retriever() -> AcademicRetriever

Constraints
-----------
* C1  — module-level singleton ``academic_retriever`` and
         ``get_academic_retriever()`` accessor.
* C7  — all public methods return ``{"success": bool, ...}``.
* C11 — uses stdlib ``logging``.
* No parallel/competing knowledge store is introduced; all persistence routes
  through :func:`~core.rag_memory.RAGMemory.ingest_knowledge`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.AcademicRetrieval")

# ---------------------------------------------------------------------------
# Lazy module-level accessor for RAGMemory — imported at module level so
# tests can patch ``core.academic_retrieval.get_rag_memory`` directly.
# ---------------------------------------------------------------------------

try:
    from core.rag_memory import get_rag_memory  # noqa: F401 — re-exported for patching
except ImportError:
    def get_rag_memory():  # type: ignore[misc]
        raise ImportError("core.rag_memory is not available")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_NODE_97_URL = os.getenv("NODE_97_URL", "http://localhost:8097")

# source_type written into every ingested knowledge chunk
_ACADEMIC_SOURCE_TYPE = "academic"

# Maximum characters of abstract to include in a single ingested chunk
_MAX_ABSTRACT_CHARS = 2000


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_paper_content(paper: Dict) -> str:
    """Build the text content ingested into the Knowledge Core for one paper."""
    title = paper.get("title", "")
    authors = paper.get("authors", [])
    abstract = paper.get("abstract", "") or ""
    source = paper.get("source", "")
    paper_id = paper.get("paper_id", "")
    published_date = paper.get("published_date", "")
    url = paper.get("url", "")
    tags = paper.get("tags", [])
    notes = paper.get("notes", "")
    citation_count = paper.get("citation_count")
    doi = paper.get("doi", "")

    lines: List[str] = [
        f"Title: {title}",
        f"Source: {source}",
        f"ID: {paper_id}",
    ]
    if published_date:
        lines.append(f"Published: {published_date}")
    if authors:
        lines.append(f"Authors: {', '.join(authors[:10])}")
    if doi:
        lines.append(f"DOI: {doi}")
    if url:
        lines.append(f"URL: {url}")
    if citation_count is not None:
        lines.append(f"Citations: {citation_count}")
    if tags:
        lines.append(f"Tags: {', '.join(tags)}")

    abstract_trimmed = abstract[:_MAX_ABSTRACT_CHARS]
    if abstract_trimmed:
        lines.append(f"\nAbstract:\n{abstract_trimmed}")

    if notes:
        lines.append(f"\nNotes:\n{notes}")

    return "\n".join(lines)


def _build_source_uri(paper: Dict) -> str:
    """Build the canonical ``source`` URI for a paper knowledge chunk."""
    source = (paper.get("source") or "unknown").replace(" ", "_")
    paper_id = (paper.get("paper_id") or "").replace("/", "_")
    return f"academic://{source}/{paper_id}"


# ---------------------------------------------------------------------------
# AcademicRetriever
# ---------------------------------------------------------------------------


class AcademicRetriever:
    """
    Academic System Resource — search, ingest, recall.

    This class is the canonical access point for academic knowledge in Galaxy.
    Agents, planners, and OpenClawd should use this class (or the
    ``academic__*`` capability bus tools) rather than invoking Node_97 or
    Node_80 directly.

    Methods
    -------
    search(query, source, max_results, ingest)
        Search academic databases and optionally ingest results into the
        unified Knowledge Core.

    ingest_paper(paper)
        Ingest a single paper dict into the unified Knowledge Core.

    recall(query, top_k)
        Recall previously-ingested academic knowledge from the unified
        Knowledge Core via RAGMemory.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        source: str = "all",
        max_results: int = 10,
        ingest: bool = True,
    ) -> Dict[str, Any]:
        """Search academic databases and optionally ingest into Knowledge Core.

        Args:
            query:       Search terms.
            source:      Database to query: ``"all"``, ``"arxiv"``,
                         ``"semantic_scholar"``, ``"pubmed"``, ``"ieee"``.
            max_results: Maximum papers to return per source.
            ingest:      When ``True`` (default), each returned paper is
                         ingested into the unified Knowledge Core via
                         :func:`~core.rag_memory.RAGMemory.ingest_knowledge`.

        Returns:
            ``{"success": bool, "query": str, "source": str,
               "total_results": int, "papers": [...],
               "ingested_count": int, "entry_ids": [...]}``
        """
        if not query or not query.strip():
            return {"success": False, "error": "academic__search requires non-empty 'query'"}

        papers: List[Dict] = []

        # ── Try Node_97 first (full-featured search) ─────────────────────
        papers = await self._search_via_node97(query, source, max_results)

        # ── Fall back to direct arXiv if Node_97 is unavailable ──────────
        if not papers:
            logger.debug("Node_97 unavailable — falling back to direct arXiv search")
            papers = await self._search_arxiv_direct(query, max_results)

        # ── Optional: ingest into Knowledge Core ─────────────────────────
        entry_ids: List[str] = []
        if ingest:
            for paper in papers:
                eid = self.ingest_paper(paper)
                if eid:
                    entry_ids.append(eid)

        return {
            "success": True,
            "query": query,
            "source": source,
            "total_results": len(papers),
            "papers": papers,
            "ingested_count": len(entry_ids),
            "entry_ids": entry_ids,
        }

    def ingest_paper(self, paper: Dict) -> str:
        """Ingest a single paper dict into the unified Knowledge Core.

        Source attribution is set to:
          * ``source_type = "academic"``
          * ``source      = "academic://{source}/{paper_id}"``

        Args:
            paper: A paper dict with keys matching Node_97's ``/search``
                   response (``paper_id``, ``title``, ``authors``,
                   ``abstract``, ``published_date``, ``url``, ``source``,
                   ``tags``).

        Returns:
            The entry ID assigned by the Knowledge Core, or ``""`` on failure.
        """
        try:
            rag = get_rag_memory()

            content = _build_paper_content(paper)
            source_uri = _build_source_uri(paper)

            tags = list(paper.get("tags") or [])
            if _ACADEMIC_SOURCE_TYPE not in tags:
                tags = [_ACADEMIC_SOURCE_TYPE] + tags

            metadata: Dict = {
                "paper_id": paper.get("paper_id", ""),
                "title": paper.get("title", ""),
                "authors": paper.get("authors", []),
                "published_date": paper.get("published_date", ""),
                "url": paper.get("url", ""),
                "citation_count": paper.get("citation_count"),
                "doi": paper.get("doi", ""),
                "source_db": paper.get("source", ""),
            }

            entry_id = rag.ingest_knowledge(
                content=content,
                source=source_uri,
                source_type=_ACADEMIC_SOURCE_TYPE,
                tags=tags,
                metadata=metadata,
            )
            logger.info(
                "Paper ingested into Knowledge Core: %s (entry_id=%s)",
                paper.get("title", "")[:60],
                entry_id,
            )
            return entry_id

        except Exception as exc:
            logger.warning("ingest_paper failed: %s", exc)
            return ""

    def recall(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """Recall academic knowledge from the unified Knowledge Core.

        Queries :class:`~core.rag_memory.RAGMemory` and filters for chunks
        with ``source_type="academic"``.

        Args:
            query:  Natural-language query.
            top_k:  Maximum number of chunks to return.

        Returns:
            ``{"success": bool, "query": str, "results": [...],
               "total": int}``
        """
        try:
            rag = get_rag_memory()

            # Run the async query_knowledge via a new event loop if needed
            chunks = self._run_maybe_async(
                rag.query_knowledge(query, top_k=top_k * 3)
            )

            # Filter to academic-origin chunks
            academic_chunks = [
                c for c in chunks
                if getattr(c, "source_type", "") == _ACADEMIC_SOURCE_TYPE
                   or (getattr(c, "source", "").startswith("academic://"))
            ][:top_k]

            return {
                "success": True,
                "query": query,
                "results": [
                    {
                        "chunk_id": c.chunk_id,
                        "content": c.content,
                        "source": c.source,
                        "source_type": c.source_type,
                        "relevance_score": c.relevance_score,
                        "tags": c.tags,
                        "metadata": c.metadata,
                    }
                    for c in academic_chunks
                ],
                "total": len(academic_chunks),
            }

        except Exception as exc:
            logger.warning("recall failed: %s", exc)
            return {"success": False, "error": str(exc), "results": [], "total": 0}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _search_via_node97(
        self, query: str, source: str, max_results: int
    ) -> List[Dict]:
        """Call Node_97's /search endpoint.  Returns [] on failure."""
        try:
            import httpx

            payload = {
                "query": query,
                "source": source,
                "max_results": max_results,
                "save_to_memos": False,  # we ingest through RAGMemory instead
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{_NODE_97_URL}/search", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("papers", [])
        except Exception as exc:
            logger.debug("Node_97 /search unavailable (%s)", exc)
            return []

    async def _search_arxiv_direct(
        self, query: str, max_results: int
    ) -> List[Dict]:
        """Minimal direct arXiv fallback (no external deps beyond stdlib)."""
        try:
            import httpx
            import xml.etree.ElementTree as ET

            params = {
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": min(max_results, 10),
                "sortBy": "relevance",
                "sortOrder": "descending",
            }
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    "http://export.arxiv.org/api/query", params=params
                )
                resp.raise_for_status()

            ns = {"atom": "http://www.w3.org/2005/Atom"}
            root = ET.fromstring(resp.text)
            papers: List[Dict] = []
            for entry in root.findall("atom:entry", ns):
                pid = (entry.find("atom:id", ns).text or "").split("/")[-1]
                title_el = entry.find("atom:title", ns)
                summary_el = entry.find("atom:summary", ns)
                published_el = entry.find("atom:published", ns)
                tags = ["arXiv"]
                for cat in entry.findall("atom:category", ns):
                    term = cat.get("term")
                    if term:
                        tags.append(term)
                papers.append(
                    {
                        "paper_id": pid,
                        "title": (title_el.text or "").strip() if title_el is not None else "",
                        "authors": [
                            (a.find("atom:name", ns).text or "")
                            for a in entry.findall("atom:author", ns)
                        ],
                        "abstract": (summary_el.text or "").strip() if summary_el is not None else "",
                        "published_date": (published_el.text or "")[:10]
                        if published_el is not None
                        else "",
                        "url": (entry.find("atom:id", ns).text or ""),
                        "source": "arXiv",
                        "tags": tags,
                    }
                )
            return papers
        except Exception as exc:
            logger.debug("Direct arXiv search failed: %s", exc)
            return []

    @staticmethod
    def _run_maybe_async(coro):
        """Run *coro* synchronously, regardless of whether there is a running loop."""
        try:
            # Python 3.10+: get_running_loop() raises RuntimeError when not in a loop
            running_loop = asyncio.get_running_loop()
            # We're inside an async context — run in a separate thread to avoid
            # blocking the event loop.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=30)
        except RuntimeError:
            # No running event loop — safe to use asyncio.run()
            return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Module-level singleton (mirrors github_installer pattern)
# ---------------------------------------------------------------------------

academic_retriever: AcademicRetriever = AcademicRetriever()


def get_academic_retriever() -> AcademicRetriever:
    """Return the module-level :class:`AcademicRetriever` singleton."""
    return academic_retriever


def reset_academic_retriever() -> None:
    """Reset the module-level singleton (test helper)."""
    global academic_retriever
    academic_retriever = AcademicRetriever()
