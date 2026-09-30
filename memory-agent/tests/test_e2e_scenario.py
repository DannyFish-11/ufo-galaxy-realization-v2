"""全局验收:多模态端到端场景(BUILD_SPEC §2-全局验收)。

场景:发送图片「这是我的白色猫 Benjamin」→ 关闭会话 → 新会话文本问
「我给你看过什么动物的照片?」→ 回答须包含 猫/白色/Benjamin 中至少两项。

离线版:fake 嵌入 + EchoMemoryLLM,验证整条管线(图像入库、caption 关联、
跨会话检索、注入生成);live 版按规格原文跑真实模型(服务不可达时 SKIP)。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from adapters.embedder import build_embedder
from adapters.memory import QdrantMemoryStore
from adapters.vectordb import QdrantAdapter
from core.schemas import MultimodalInput
from services.api import create_app
from tests.conftest import API_URL, FIXTURES, EchoMemoryLLM, make_fake_config, requires_live


def _count_keywords(text: str) -> int:
    return sum(1 for kw in ("猫", "白色", "Benjamin") if kw in text)


async def test_e2e_multimodal_scenario_offline(tmp_path):
    cfg = make_fake_config(tmp_path, vect_mode="local")
    img = MultimodalInput.from_file(FIXTURES / "white_cat.png", "image", "image/png")

    # 会话 1:发送图片
    embedder = build_embedder(cfg.embedder)
    db = QdrantAdapter(cfg.vectordb, dim=cfg.embedder.effective_dim)
    store = QdrantMemoryStore(embedder, EchoMemoryLLM(), db, cfg)
    app1 = create_app(cfg, llm=EchoMemoryLLM(), memory=store, skip_dependency_checks=True)
    with TestClient(app1) as client:
        r = client.post("/chat", json={
            "message": "这是我的白色猫 Benjamin",
            "session_id": "session-1",
            "image_base64": img.content,
            "image_mime": "image/png",
        })
        assert r.status_code == 200
    await db.aclose()  # 关闭会话/进程

    # 会话 2:全新进程语义(同一持久化路径重建全栈)
    embedder2 = build_embedder(cfg.embedder)
    db2 = QdrantAdapter(cfg.vectordb, dim=cfg.embedder.effective_dim)
    store2 = QdrantMemoryStore(embedder2, EchoMemoryLLM(), db2, cfg)
    app2 = create_app(cfg, llm=EchoMemoryLLM(), memory=store2, skip_dependency_checks=True)
    with TestClient(app2) as client:
        r = client.post("/chat", json={
            "message": "我给你看过什么动物的照片?",
            "session_id": "session-2",
        })
        assert r.status_code == 200
        reply = r.json()["reply"]
    await db2.aclose()

    assert _count_keywords(reply) >= 2, f"回答未包含至少两项关键词: {reply!r}"


@pytest.mark.integration
@requires_live(f"{API_URL}/healthz", "L3 API(真实全栈)")
def test_e2e_multimodal_scenario_live():
    import httpx

    img = MultimodalInput.from_file(FIXTURES / "white_cat.png", "image", "image/png")
    httpx.post(f"{API_URL}/chat", json={
        "message": "这是我的白色猫 Benjamin",
        "session_id": "e2e-live-1",
        "image_base64": img.content,
        "image_mime": "image/png",
    }, timeout=300).raise_for_status()

    resp = httpx.post(f"{API_URL}/chat", json={
        "message": "我给你看过什么动物的照片?",
        "session_id": "e2e-live-2",
    }, timeout=300)
    resp.raise_for_status()
    assert _count_keywords(resp.json()["reply"]) >= 2
