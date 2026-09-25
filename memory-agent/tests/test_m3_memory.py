"""Milestone 3 验收:L2+L3 记忆核心(BUILD_SPEC §2-M3)。

①写后即查 ②跨会话持久 ③跨模态 ④端到端对话 ⑤MCP 客户端调用。
①-⑤ 全部在离线模式(fake 嵌入 + verbatim 抽取 + 本地 Qdrant)真实执行本项目
逻辑;跨模态的语义检索质量与真实 LLM 对话另有 live 版本(integration)。
"""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

from adapters.embedder import build_embedder
from adapters.memory import QdrantMemoryStore
from adapters.vectordb import QdrantAdapter
from core.schemas import MultimodalInput
from services.api import create_app
from tests.conftest import (
    API_URL,
    FIXTURES,
    PROJECT_ROOT,
    EchoMemoryLLM,
    ScriptedLLM,
    make_fake_config,
    requires_live,
)


def build_store(cfg, llm=None):
    embedder = build_embedder(cfg.embedder)
    db = QdrantAdapter(cfg.vectordb, dim=cfg.embedder.effective_dim)
    return QdrantMemoryStore(embedder, llm or ScriptedLLM(), db, cfg), db


# ---------------------------------------------------------------- ① 写后即查

async def test_m3_write_then_read():
    cfg = make_fake_config()
    store, _ = build_store(cfg)
    await store.add(MultimodalInput.text("今天天气晴朗"), {})
    await store.add(MultimodalInput.text("老板喜欢喝黑咖啡"), {})
    await store.add(MultimodalInput.text("用户的猫叫 Benjamin"), {})

    hits = await store.search(MultimodalInput.text("我的猫叫什么"), k=3)
    assert hits, "写后即查未命中任何记忆"
    assert "Benjamin" in hits[0].content


# ---------------------------------------------------------------- ② 跨会话持久

async def test_m3_persistence_across_restart(tmp_path):
    cfg = make_fake_config(tmp_path, vect_mode="local")

    store, db = build_store(cfg)
    await store.add(MultimodalInput.text("用户的猫叫 Benjamin"), {})
    await db.aclose()  # 模拟服务进程退出

    store2, db2 = build_store(cfg)  # 同一本地存储路径重建 = 进程重启
    hits = await store2.search(MultimodalInput.text("我的猫叫什么"), k=3)
    await db2.aclose()
    assert hits and "Benjamin" in hits[0].content


# ---------------------------------------------------------------- ③ 跨模态

async def test_m3_cross_modal_image_recall():
    """存入图片+描述,用文本查询召回该图片记忆(caption 关联链路)。"""
    cfg = make_fake_config()
    store, _ = build_store(cfg)
    img = MultimodalInput.from_file(FIXTURES / "white_cat.png", "image", "image/png")
    img_id = await store.add(img, {"caption": "一只白色的猫,名字叫 Benjamin"})

    hits = await store.search(MultimodalInput.text("白色的猫"), k=5)
    image_hits = [h for h in hits if h.modality == "image"]
    assert image_hits, "文本查询未召回图片记忆"
    top = image_hits[0]
    assert "白色的猫" in top.content
    assert top.meta.get("parent_id") == img_id or top.id == img_id


@pytest.mark.integration
@requires_live(f"{API_URL}/healthz", "L3 API(真实跨模态)")
def test_m3_spec_cross_modal_live():
    import httpx

    img = MultimodalInput.from_file(FIXTURES / "white_cat.png", "image", "image/png")
    httpx.post(f"{API_URL}/memory/add", json={
        "input": img.model_dump(), "meta": {"caption": "一只白色的猫,名字叫 Benjamin"},
    }, timeout=120).raise_for_status()
    resp = httpx.post(f"{API_URL}/memory/search", json={
        "query": {"type": "text", "content": "白色的猫"}, "k": 5,
    }, timeout=120)
    resp.raise_for_status()
    assert any(h["modality"] == "image" for h in resp.json())


# ---------------------------------------------------------------- ④ 端到端对话

def test_m3_chat_two_rounds_memory_injection():
    """第二轮问第一轮告知的事实;验证检索-注入-生成-写回整条链路。"""
    cfg = make_fake_config()
    store, _ = build_store(cfg)
    llm = EchoMemoryLLM(replies=[])
    app = create_app(cfg, llm=llm, memory=store, skip_dependency_checks=True)

    with TestClient(app) as client:
        r1 = client.post("/chat", json={"message": "我的猫叫 Benjamin,它全身白色", "session_id": "s1"})
        assert r1.status_code == 200

        r2 = client.post("/chat", json={"message": "我的猫叫什么名字?", "session_id": "s1"})
        assert r2.status_code == 200
        body = r2.json()
        assert body["memories_used"], "第二轮未检索到任何记忆"
        assert "Benjamin" in body["reply"], "第一轮告知的事实未注入第二轮回答"

    # 第二轮的 system prompt 必须包含第一轮的事实(注入点断言)
    round2_system = llm.calls[1][0]
    assert "Benjamin" in str(round2_system.content)


@pytest.mark.integration
@requires_live(f"{API_URL}/healthz", "L3 API(真实 LLM 对话)")
def test_m3_spec_chat_live():
    import httpx

    httpx.post(f"{API_URL}/chat", json={
        "message": "记住:我的猫叫 Benjamin", "session_id": "spec-m3",
    }, timeout=300).raise_for_status()
    resp = httpx.post(f"{API_URL}/chat", json={
        "message": "我的猫叫什么名字?", "session_id": "spec-m3",
    }, timeout=300)
    resp.raise_for_status()
    assert "Benjamin" in resp.json()["reply"]


# ---------------------------------------------------------------- ⑤ MCP

async def test_m3_mcp_tools_roundtrip(tmp_path):
    """用官方 mcp client(stdio)调 memory_store / memory_search,校验返回结构。"""
    import json

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env.update({
        "MEMORY_AGENT_CONFIG": str(PROJECT_ROOT / "config.yaml"),
        "MEMORY_AGENT_EMBEDDER__BACKEND": "fake",
        "MEMORY_AGENT_EMBEDDER__DIM": "64",
        "MEMORY_AGENT_MEMORY__EXTRACTION": "verbatim",
        "MEMORY_AGENT_VECTORDB__MODE": "local",
        "MEMORY_AGENT_VECTORDB__PATH": str(tmp_path / "qdrant"),
        "PYTHONPATH": str(PROJECT_ROOT),
    })
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "services.mcp_server"],
        env=env,
        cwd=str(PROJECT_ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            assert {"memory_store", "memory_search", "memory_consolidate"} <= names

            stored = await session.call_tool(
                "memory_store", {"content": "用户的猫叫 Benjamin", "modality": "text"})
            assert not stored.isError
            assert json.loads(stored.content[0].text)["id"]

            result = await session.call_tool("memory_search", {"query": "我的猫叫什么", "k": 3})
            assert not result.isError
            hits = json.loads(result.content[0].text)
            assert isinstance(hits, list) and hits
            for key in ("id", "score", "content", "modality", "meta"):
                assert key in hits[0]
            assert "Benjamin" in hits[0]["content"]
