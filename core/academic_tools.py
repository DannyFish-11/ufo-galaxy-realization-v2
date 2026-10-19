"""学术检索给智能体的工具:定义 + 新增那三个(本机 arXiv 文献库)的执行。

``academic__search / ingest / recall`` 三个原先写在 ``core/openclawd.py`` 里(那个文件有行数预算,
挪到这里,openclawd 只 import 这一份)。它们的执行仍在 ``OpenClawd._dispatch_academic_tool``。

新增三个,都落在本机 arXiv 文献库(``core/arxiv_library.py``):

* ``academic__arxiv_search``  —— 在本机 314 万篇的目录里检索(BM25 + 分类 / 日期字段过滤),离线、毫秒级;
  目录还没建时自动退回在线检索(守 arXiv 的限速),并说一句「要建库就说」。
* ``academic__arxiv_read``    —— 读一篇的全文:本机缓存 → 本机全文分片 → 向 arXiv 要这一篇。
* ``academic__arxiv_library`` —— 看文献库状态 / 建库(下 1.6 GB 元数据)/ 补新论文 / 下 70 GB 全文分片。
  **会下东西的动作只在人自己发起的回合里做**(后台自发的回合连提都不行),70 GB 那个还要人明确点头。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List

# Academic 内置工具定义（供 LLM function calling 使用）
ACADEMIC_BUILTIN_TOOLS: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "academic__search",
            "description": (
                "在学术数据库（arXiv、Semantic Scholar、PubMed、IEEE Xplore）中搜索论文。"
                "默认将搜索结果摄取到统一知识库（Knowledge Core），以便后续回检与推理引用。"
                "返回论文元数据列表，包括标题、作者、摘要、来源、标签和摘取的条目 ID。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词或自然语言问题",
                    },
                    "source": {
                        "type": "string",
                        "enum": ["all", "arxiv", "semantic_scholar", "pubmed", "ieee"],
                        "description": "数据源，默认为 all（全部来源）",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "每个数据源最多返回的论文数量（默认 10）",
                    },
                    "ingest": {
                        "type": "boolean",
                        "description": "是否将搜索结果摄取到统一知识库（默认 true）",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "academic__ingest",
            "description": (
                "将单篇论文的元数据和摘要摄取到统一知识库（Knowledge Core）。"
                "来源标注为 academic://{source}/{paper_id}，source_type 为 'academic'。"
                "用于把已检索到的论文持久化为可回检的知识片段。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paper": {
                        "type": "object",
                        "description": (
                            "论文元数据对象，至少包含 paper_id、title、abstract、source 字段。"
                            "其他可选字段：authors、published_date、url、tags、notes、doi、citation_count。"
                        ),
                    },
                },
                "required": ["paper"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "academic__recall",
            "description": (
                "从统一知识库（Knowledge Core）中回检之前摄取的学术知识片段。"
                "仅返回 source_type='academic' 或 source 以 academic:// 开头的知识条目。"
                "可与 academic__search 配合使用：先搜索并摄取，后续对话中通过此工具回检。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "回检查询（自然语言）",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "最多返回的知识片段数量（默认 5）",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "academic__arxiv_search",
            "description": (
                "在本机 arXiv 文献库(全部约 314 万篇论文的标题、作者、摘要、分类、日期)里检索,离线、很快。"
                "关键词用英文效果最好(论文是英文的;中文问题先译成英文关键词)。可按分类与日期过滤。"
                "本机文献库还没建时自动改为在线检索,并在结果里说明。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "英文关键词或短语,如 'retrieval augmented generation'"},
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "只要这些分类,如 ['cs.CL'] 或 ['cs'](cs 下全部)",
                    },
                    "since": {"type": "string", "description": "首次提交不早于(YYYY-MM-DD)"},
                    "until": {"type": "string", "description": "首次提交不晚于(YYYY-MM-DD)"},
                    "limit": {"type": "integer", "description": "最多返回几篇(默认 10,最多 50)"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "academic__arxiv_read",
            "description": (
                "读一篇 arXiv 论文的全文(编号如 2401.01234)。先用本机缓存,没有再向 arXiv 取这一篇并缓存。"
                "ingest=true 时把全文分段存进统一知识库,之后用 academic__recall 能回检到。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "string", "description": "arXiv 编号或链接"},
                    "max_chars": {"type": "integer", "description": "返回的全文最多多少字(默认 20000)"},
                    "offset": {"type": "integer", "description": "从第几个字开始返回(分段读长论文用)"},
                    "ingest": {"type": "boolean", "description": "是否把全文存进统一知识库(默认 false)"},
                },
                "required": ["paper_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "academic__arxiv_library",
            "description": (
                "本机 arXiv 文献库的状态与维护。action: status=看现状与同步进度; "
                "build=建库(从 Hugging Face 下 1.6 GB 元数据,导入约需几十分钟,可只要部分分类); "
                "update=补上快照之后的新论文; download_fulltext=把 70 GB 全文分片整份下到本机(需 confirm=true)。"
                "建库、补新、下全文只在用户自己要求时做。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["status", "build", "update", "download_fulltext"]},
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "build 时只导这些分类(如 ['cs','stat.ML']);不填 = 全部",
                    },
                    "confirm": {"type": "boolean", "description": "download_fulltext 要用户明确同意(70 GB)"},
                },
                "required": ["action"],
            },
        },
    },
]


#: 读全文默认返回多少字 —— 整篇常有十几万字,一次全塞进上下文只会把对话挤爆。
READ_CHARS = 20000
#: 存进知识库时每段多长、最多几段。
_CHUNK = 4000
_MAX_CHUNKS = 40


def _human_turn() -> bool:
    """这一回合是不是人自己发起的(文字 / 语音 / 手表)。后台自发的回合不下东西。"""
    try:
        from core.device_onboarding.conversation import HUMAN_REQUEST_SOURCES, _current_turn

        turn_id, source, _text = _current_turn()
        return bool(turn_id) and source in HUMAN_REQUEST_SOURCES
    except Exception:  # noqa: BLE001 — 判断不了就当不是:宁可不下
        return False


def _trim(paper: Dict[str, Any], n: int = 900) -> Dict[str, Any]:
    abstract = paper.get("abstract") or ""
    return {**paper, "abstract": abstract[:n] + ("…" if len(abstract) > n else "")}


def _search(args: Dict[str, Any]) -> Dict[str, Any]:
    from core.arxiv_library import get_library
    from core.arxiv_sync import describe, maybe_refresh

    query = str(args.get("query") or "").strip()
    if not query:
        return {"success": False, "error": "academic__arxiv_search 需要 query"}
    limit = int(args.get("limit") or 10)
    lib = get_library()
    if lib.ready():
        maybe_refresh()
        papers = lib.search(
            query,
            categories=[str(c) for c in (args.get("categories") or [])],
            since=str(args.get("since") or ""),
            until=str(args.get("until") or ""),
            limit=limit,
        )
        return {"success": True, "origin": "local", "papers": [_trim(p) for p in papers], "total": len(papers)}
    from core.arxiv_client import search_or_why

    papers, why = search_or_why(query, limit)
    if why:
        # 没连上 ≠ 没搜到:照实说没查成,别让模型据此告诉人「没有相关论文」
        return {"success": False, "origin": "online", "papers": [], "total": 0, "error": why, "note": describe()}
    return {
        "success": True,
        "origin": "online",
        "papers": [_trim(p) for p in papers],
        "total": len(papers),
        "note": describe() + ";这次是在线检索(arXiv 限速每 3 秒一次)",
    }


def _ingest_fulltext(paper_id: str, text: str) -> int:
    from core.academic_retrieval import get_academic_retriever
    from core.arxiv_library import get_library

    meta = get_library().get(paper_id) or {"paper_id": paper_id, "source": "arXiv", "title": paper_id}
    retriever = get_academic_retriever()
    stored = 0
    for k in range(min(_MAX_CHUNKS, (len(text) + _CHUNK - 1) // _CHUNK)):
        part = {**meta, "paper_id": f"{paper_id}#{k + 1}", "abstract": text[k * _CHUNK : (k + 1) * _CHUNK]}
        stored += 1 if retriever.ingest_paper(part) else 0
    return stored


def _read(args: Dict[str, Any]) -> Dict[str, Any]:
    from core.arxiv_library import read_fulltext

    pid = str(args.get("paper_id") or "").strip()
    if not pid:
        return {"success": False, "error": "academic__arxiv_read 需要 paper_id"}
    got = read_fulltext(pid)
    if not got.get("success"):
        return got
    text = got.pop("text")
    offset = max(0, int(args.get("offset") or 0))
    n = max(500, min(int(args.get("max_chars") or READ_CHARS), 100000))
    out = {**got, "text": text[offset : offset + n], "offset": offset, "total_chars": len(text)}
    if offset + n < len(text):
        out["next_offset"] = offset + n
    if args.get("ingest"):
        out["ingested_chunks"] = _ingest_fulltext(got["paper_id"], text)
    return out


def _library(args: Dict[str, Any]) -> Dict[str, Any]:
    from core import arxiv_sync

    action = str(args.get("action") or "status")
    if action == "status":
        st = arxiv_sync.status()
        return {"success": True, "said": arxiv_sync.describe(st), **st}
    if action not in ("build", "update", "download_fulltext"):
        return {"success": False, "error": f"不认识的 action:{action}"}
    if not _human_turn():
        return {"success": False, "error": "要下东西的维护只在用户自己要求时做(这是后台自发的回合)"}
    if action == "download_fulltext" and not args.get("confirm"):
        return {
            "success": False,
            "error": "全文分片整份有 70 GB。先问用户要不要;用户同意了再带 confirm=true 调一次",
        }
    part = {"build": "metadata", "update": "update", "download_fulltext": "paper_text"}[action]
    res = arxiv_sync.start(part, categories=[str(c) for c in (args.get("categories") or [])])
    return {**res, "said": arxiv_sync.describe()}


async def dispatch_arxiv_tool(action: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """执行 ``academic__arxiv_*``。都是同步、会碰硬盘或网络的活:放到工作线程里,不压事件循环。"""
    handler = {"arxiv_search": _search, "arxiv_read": _read, "arxiv_library": _library}.get(action)
    if handler is None:
        return {"success": False, "error": f"Unknown academic action: '{action}'"}
    try:
        return await asyncio.to_thread(handler, dict(arguments or {}))
    except Exception as exc:  # noqa: BLE001 — 工具失败要回到对话里说清楚,不抛
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}
