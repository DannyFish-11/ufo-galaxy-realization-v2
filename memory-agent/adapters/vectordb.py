"""Qdrant 适配层(L2 兜底向量存储,BUILD_SPEC §0.2-1)。"""

from __future__ import annotations

import uuid
from typing import Any

from core.config import VectorDBSettings
from core.errors import LayerError


class QdrantAdapter:
    """对 qdrant-client 的薄封装;支持 server / 本地文件 / 纯内存三种模式。"""

    def __init__(self, settings: VectorDBSettings, dim: int) -> None:
        from qdrant_client import AsyncQdrantClient

        self._settings = settings
        self._dim = dim
        try:
            if settings.mode == "server":
                self._client = AsyncQdrantClient(url=settings.url)
            elif settings.mode == "local":
                self._client = AsyncQdrantClient(path=settings.path)
            else:
                self._client = AsyncQdrantClient(location=":memory:")
        except Exception as exc:
            raise LayerError("L2", "qdrant", f"初始化失败(mode={settings.mode}): {exc}") from exc

    @property
    def collection(self) -> str:
        return self._settings.collection

    async def ensure_collection(self) -> None:
        from qdrant_client import models

        try:
            if not await self._client.collection_exists(self.collection):
                await self._client.create_collection(
                    collection_name=self.collection,
                    vectors_config=models.VectorParams(
                        size=self._dim, distance=models.Distance.COSINE
                    ),
                )
        except Exception as exc:
            raise LayerError("L2", "qdrant", f"建集合失败(检查 Qdrant 是否可达): {exc}") from exc

    async def upsert(self, vectors: list[list[float]], payloads: list[dict[str, Any]],
                     ids: list[str] | None = None) -> list[str]:
        from qdrant_client import models

        ids = ids or [str(uuid.uuid4()) for _ in vectors]
        points = [
            models.PointStruct(id=pid, vector=vec, payload=payload)
            for pid, vec, payload in zip(ids, vectors, payloads, strict=True)
        ]
        try:
            await self._client.upsert(collection_name=self.collection, points=points, wait=True)
        except Exception as exc:
            raise LayerError("L2", "qdrant", f"写入失败: {exc}") from exc
        return ids

    async def search(self, vector: list[float], k: int = 5) -> list[dict[str, Any]]:
        try:
            res = await self._client.query_points(
                collection_name=self.collection, query=vector, limit=k, with_payload=True
            )
        except Exception as exc:
            raise LayerError("L2", "qdrant", f"检索失败: {exc}") from exc
        return [
            {"id": str(p.id), "score": float(p.score), "payload": p.payload or {}}
            for p in res.points
        ]

    async def scroll_all(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        offset = None
        try:
            while True:
                points, offset = await self._client.scroll(
                    collection_name=self.collection, limit=256, offset=offset,
                    with_payload=True, with_vectors=True,
                )
                for p in points:
                    out.append({"id": str(p.id), "vector": p.vector, "payload": p.payload or {}})
                if offset is None:
                    break
        except Exception as exc:
            raise LayerError("L2", "qdrant", f"scroll 失败: {exc}") from exc
        return out

    async def delete(self, ids: list[str]) -> None:
        from qdrant_client import models

        try:
            await self._client.delete(
                collection_name=self.collection,
                points_selector=models.PointIdsList(points=ids), wait=True,
            )
        except Exception as exc:
            raise LayerError("L2", "qdrant", f"删除失败: {exc}") from exc

    async def count(self) -> int:
        try:
            res = await self._client.count(collection_name=self.collection, exact=True)
        except Exception as exc:
            raise LayerError("L2", "qdrant", f"count 失败: {exc}") from exc
        return res.count

    async def health(self) -> bool:
        try:
            await self._client.get_collections()
        except Exception as exc:
            raise LayerError("L2", "qdrant", f"健康检查失败(mode={self._settings.mode}): {exc}") from exc
        return True

    async def aclose(self) -> None:
        await self._client.close()
