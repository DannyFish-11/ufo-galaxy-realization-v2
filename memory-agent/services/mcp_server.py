"""MCP Server(官方 mcp Python SDK,stdio 传输)。

工具:memory_store / memory_search / memory_consolidate。
与 FastAPI 服务通过 core.factory.get_shared_memory_store 复用同一 MemoryStore:
同进程时为同一实例;独立进程时经同一 Qdrant collection(或 SimpleMem data_dir)
共享持久状态。

Omnigent(L4)通过 tools/mcp/memory.yaml 以 stdio 方式拉起本服务。
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from core.factory import get_config, get_shared_memory_store
from core.schemas import Modality, MultimodalInput

mcp = FastMCP("memory-agent")


@mcp.tool()
async def memory_store(content: str, modality: Modality = "text", meta: dict[str, Any] | None = None) -> str:
    """存入一条记忆。modality=text 时 content 为原文;image/audio 时为 base64。

    返回 JSON: {"id": "..."}
    """
    store = get_shared_memory_store()
    mem_id = await store.add(MultimodalInput(type=modality, content=content), meta or {})
    return json.dumps({"id": mem_id}, ensure_ascii=False)


@mcp.tool()
async def memory_search(query: str, k: int = 5) -> str:
    """按文本查询检索记忆。返回 JSON 数组,每项含 id/score/content/modality/meta。"""
    store = get_shared_memory_store()
    hits = await store.search(MultimodalInput.text(query), k=k)
    return json.dumps([h.model_dump() for h in hits], ensure_ascii=False)


@mcp.tool()
async def memory_consolidate() -> str:
    """触发记忆整合(合并语义重复项)。返回 JSON 整合报告。"""
    store = get_shared_memory_store()
    report = await store.consolidate()
    return json.dumps(report.model_dump(), ensure_ascii=False)


def main() -> None:
    get_config()  # 提前加载配置,配置错误在启动时即暴露(fail-fast)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
