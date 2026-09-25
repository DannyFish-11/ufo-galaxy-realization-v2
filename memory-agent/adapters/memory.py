"""L2 适配层:MemoryStore 协议 + QdrantMemoryStore(兜底) + SimpleMemAdapter。

BUILD_SPEC §3:核心逻辑(core/、services/)只依赖 MemoryStore 协议;
换掉 SimpleMem 只允许波及本目录。
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol, runtime_checkable

from adapters.embedder import Embedder
from adapters.llm import LLMClient
from adapters.vectordb import QdrantAdapter
from core.config import AppConfig
from core.errors import LayerError
from core.prompts import MEMORY_CONSOLIDATION_SYSTEM, MEMORY_EXTRACTION_SYSTEM
from core.schemas import ConsolidationReport, MemoryHit, Message, MultimodalInput


@runtime_checkable
class MemoryStore(Protocol):
    async def add(self, content: MultimodalInput, meta: dict) -> str: ...

    async def search(self, query: MultimodalInput, k: int = 5) -> list[MemoryHit]: ...

    async def consolidate(self) -> ConsolidationReport: ...


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=True))
    da = sum(x * x for x in a) ** 0.5
    db = sum(y * y for y in b) ** 0.5
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


class QdrantMemoryStore:
    """基于 Embedder + LLMClient + Qdrant 的记忆存储(BUILD_SPEC 指定的兜底实现)。

    - add(text): extraction=llm 时先用 L0 抽取原子事实,verbatim 时原文入库
    - add(image/audio): 用 L1 编码原始内容入库;meta.caption 另存一条文本记忆并
      通过 parent_id 关联,使纯文本查询也能召回该多模态记忆
    - consolidate(): 余弦相似聚类 + L0 合并改写
    """

    def __init__(self, embedder: Embedder, llm: LLMClient, db: QdrantAdapter, config: AppConfig) -> None:
        self._embedder = embedder
        self._llm = llm
        self._db = db
        self._config = config
        self._ready = False

    async def _ensure_ready(self) -> None:
        if not self._ready:
            await self._db.ensure_collection()
            self._ready = True

    async def _extract_facts(self, text: str) -> list[str]:
        if self._config.memory.extraction == "verbatim":
            return [text]
        raw = await self._llm.chat(
            [
                Message(role="system", content=MEMORY_EXTRACTION_SYSTEM),
                Message(role="user", content=text),
            ],
            temperature=0.0,
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            cleaned = cleaned[4:] if cleaned.startswith("json") else cleaned
        try:
            facts = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise LayerError("L2", "memory-extraction", f"LLM 输出非 JSON 数组: {raw[:300]}") from exc
        if not isinstance(facts, list) or not all(isinstance(f, str) for f in facts):
            raise LayerError("L2", "memory-extraction", f"LLM 输出结构异常: {raw[:300]}")
        return facts or [text]

    async def add(self, content: MultimodalInput, meta: dict) -> str:
        await self._ensure_ready()
        now = time.time()
        base_payload = {"modality": content.type, "meta": meta, "created_at": now}

        if content.type == "text":
            facts = await self._extract_facts(content.content)
            vectors = await self._embedder.embed([MultimodalInput.text(f) for f in facts])
            payloads = [dict(base_payload, content=f) for f in facts]
            ids = await self._db.upsert(vectors, payloads)
            return ids[0]

        # image / audio:原始内容向量入库
        vectors = await self._embedder.embed([content])
        display = meta.get("caption") or f"[{content.type} memory]"
        payloads = [dict(base_payload, content=display, raw_base64=content.content, mime=content.mime)]
        ids = await self._db.upsert(vectors, payloads)
        # caption 另存文本点,保证纯文本检索(含 fake 后端下的插件化测试)也能命中
        caption = meta.get("caption")
        if caption:
            cap_vec = await self._embedder.embed([MultimodalInput.text(caption)])
            await self._db.upsert(
                cap_vec,
                [{
                    "modality": content.type, "content": caption, "created_at": now,
                    "meta": dict(meta, kind="caption", parent_id=ids[0]),
                }],
            )
        return ids[0]

    async def search(self, query: MultimodalInput, k: int = 5) -> list[MemoryHit]:
        await self._ensure_ready()
        vec = (await self._embedder.embed([query]))[0]
        raw = await self._db.search(vec, k=k)
        hits = []
        for r in raw:
            p = r["payload"]
            hits.append(MemoryHit(
                id=r["id"], score=r["score"],
                content=p.get("content", ""),
                modality=p.get("modality", "text"),
                meta=p.get("meta", {}),
            ))
        return hits

    async def consolidate(self) -> ConsolidationReport:
        await self._ensure_ready()
        points = await self._db.scroll_all()
        text_points = [p for p in points if p["payload"].get("modality") == "text"]
        before = len(points)
        threshold = self._config.memory.consolidation.similarity_threshold

        # 贪心聚类:相似度 >= 阈值的文本记忆归为一组
        groups: list[list[dict[str, Any]]] = []
        used: set[str] = set()
        for i, p in enumerate(text_points):
            if p["id"] in used:
                continue
            group = [p]
            used.add(p["id"])
            for q in text_points[i + 1:]:
                if q["id"] in used:
                    continue
                if _cosine(p["vector"], q["vector"]) >= threshold:
                    group.append(q)
                    used.add(q["id"])
            groups.append(group)

        merged_groups = 0
        pruned = 0
        details: list[str] = []
        for group in groups:
            if len(group) < 2:
                continue
            contents = [g["payload"].get("content", "") for g in group]
            merged = await self._llm.chat(
                [
                    Message(role="system", content=MEMORY_CONSOLIDATION_SYSTEM),
                    Message(role="user", content="\n".join(f"- {c}" for c in contents)),
                ],
                temperature=0.0,
            )
            merged = merged.strip()
            vec = (await self._embedder.embed([MultimodalInput.text(merged)]))[0]
            await self._db.delete([g["id"] for g in group])
            await self._db.upsert(
                [vec],
                [{"modality": "text", "content": merged, "created_at": time.time(),
                  "meta": {"kind": "consolidated", "source_count": len(group)}}],
            )
            merged_groups += 1
            pruned += len(group) - 1
            details.append(f"merged {len(group)} memories -> {merged[:80]}")

        after = await self._db.count()
        return ConsolidationReport(
            total_before=before, total_after=after,
            merged_groups=merged_groups, pruned=pruned, details=details,
        )


class SimpleMemAdapter:
    """Omni-SimpleMem(github.com/aiming-lab/SimpleMem 之 OmniSimpleMem 包)适配器。

    集成方式(读上游源码所得,commit 见 README):
    - LLM 与文本嵌入:上游 OpenAI 客户端统一走 config.llm.api_base_url
      (omni_memory/utils/embedding.py:_get_openai_client),故指向本项目 L1 服务的
      OpenAI 兼容网关(chat→L0 vLLM,embeddings→L1 jina),零上游改动。
    - 上游在 pinned commit 缺失 omni_memory/core/config.py(包无法 import),
      本适配器在 import 上游前注入 simplemem_compat.config_shim 重建的兼容模块
      (据上游 tests/test_config.py 的规范接口逐字段重建),不触碰上游源码。
      ——该 shim 属最小 patch,已按 BUILD_SPEC 停点要求记录于 README 等待人类确认。
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        try:
            from adapters.simplemem_compat import config_shim

            config_shim.install()
            from omni_memory import OmniMemoryOrchestrator  # type: ignore[import-not-found]
            from omni_memory.core.config import OmniMemoryConfig  # shim 提供
        except ImportError as exc:
            raise LayerError(
                "L2", "simplemem",
                "OmniSimpleMem 未安装。克隆 aiming-lab/SimpleMem 并 "
                "pip install -e SimpleMem/OmniSimpleMem,另装 extras: uv sync --extra simplemem。"
                f"原始错误: {exc}",
            ) from exc

        sm_cfg = OmniMemoryConfig()
        sm_cfg.llm.api_base_url = config.memory.simplemem.gateway_base_url
        sm_cfg.llm.api_key = config.llm.api_key
        sm_cfg.set_unified_model(config.llm.model)
        sm_cfg.embedding.model_name = "text-embedding-3-small"  # 走网关→实际由 L1 jina 服务响应
        sm_cfg.embedding.embedding_dim = config.embedder.effective_dim
        self._orch = OmniMemoryOrchestrator(config=sm_cfg, data_dir=config.memory.simplemem.data_dir)

    async def add(self, content: MultimodalInput, meta: dict) -> str:
        import asyncio
        import io

        def _run() -> str:
            tags = meta.get("tags")
            if content.type == "text":
                result = self._orch.add_text(content.content, session_id=meta.get("session_id"), tags=tags)
            elif content.type == "image":
                result = self._orch.add_image(io.BytesIO(content.raw_bytes()).getvalue(),
                                              session_id=meta.get("session_id"), tags=tags)
            else:
                result = self._orch.add_audio(content.raw_bytes(),
                                              session_id=meta.get("session_id"), tags=tags)
            mau_ids = getattr(result, "mau_ids", None) or [getattr(result, "mau_id", "")]
            return str(mau_ids[0]) if mau_ids else ""

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:
            raise LayerError("L2", "simplemem", f"add 失败: {exc}") from exc

    async def search(self, query: MultimodalInput, k: int = 5) -> list[MemoryHit]:
        import asyncio

        if query.type != "text":
            raise LayerError("L2", "simplemem", "上游 query() 仅接受文本查询;多模态查询请用 qdrant 后端")

        def _run() -> list[MemoryHit]:
            result = self._orch.query(query.content, top_k=k)
            hits: list[MemoryHit] = []
            for item in getattr(result, "items", None) or getattr(result, "maus", []) or []:
                hits.append(MemoryHit(
                    id=str(getattr(item, "mau_id", getattr(item, "id", ""))),
                    score=float(getattr(item, "score", 0.0)),
                    content=str(getattr(item, "preview", getattr(item, "content", ""))),
                    modality="text",
                    meta={"source": "simplemem"},
                ))
            return hits

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:
            raise LayerError("L2", "simplemem", f"search 失败: {exc}") from exc

    async def consolidate(self) -> ConsolidationReport:
        import asyncio

        def _run() -> ConsolidationReport:
            report = self._orch.consolidate_memories(force=True)
            return ConsolidationReport(
                total_before=int(report.get("total_before", 0)),
                total_after=int(report.get("total_after", 0)),
                merged_groups=int(report.get("merged", 0)),
                pruned=int(report.get("pruned", 0)),
                details=[json.dumps(report, ensure_ascii=False, default=str)],
            )

        try:
            return await asyncio.to_thread(_run)
        except Exception as exc:
            raise LayerError("L2", "simplemem", f"consolidate 失败: {exc}") from exc
