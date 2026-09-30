"""Milestone 2 验收:L1 嵌入服务(BUILD_SPEC §2-M2)+ 嵌入层单元用例。

规格断言(同义句 cos>0.8 / 无关句 cos<0.4 / 跨模态排序 / 维度一致)针对真实
jina-v5-omni 服务,离线时显式 SKIP;fake 后端仅用于服务自身接口逻辑的验证。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from adapters.embedder import FakeDeterministicEmbedder, truncate_and_normalize
from core.errors import LayerError
from core.schemas import MultimodalInput
from services.embed_service import create_app
from tests.conftest import EMBED_URL, FIXTURES, cosine, make_fake_config, requires_live


# ---------------------------------------------------------------- 规格验收(live)

def _live_embed(client_inputs: list[dict]) -> dict:
    import httpx

    resp = httpx.post(f"{EMBED_URL}/embed", json={"inputs": client_inputs}, timeout=120)
    resp.raise_for_status()
    return resp.json()


@pytest.mark.integration
@requires_live(f"{EMBED_URL}/healthz", "L1 嵌入服务")
def test_m2_spec_text_text_similarity():
    """①同义句 cos>0.8,无关句 cos<0.4。"""
    data = _live_embed([
        {"type": "text", "content": "今天的天气非常好"},
        {"type": "text", "content": "今天天气很不错"},
        {"type": "text", "content": "量子场论中的重整化群方程"},
    ])
    v = data["vectors"]
    assert cosine(v[0], v[1]) > 0.8
    assert cosine(v[0], v[2]) < 0.4


@pytest.mark.integration
@requires_live(f"{EMBED_URL}/healthz", "L1 嵌入服务")
def test_m2_spec_cross_modal_retrieval():
    """②文本-图像跨模态:正确描述的 cos 高于错误描述。"""
    img = MultimodalInput.from_file(FIXTURES / "white_cat.png", "image", "image/png")
    data = _live_embed([
        img.model_dump(),
        {"type": "text", "content": "一只白色的猫"},
        {"type": "text", "content": "一辆红色的汽车"},
    ])
    v = data["vectors"]
    assert cosine(v[0], v[1]) > cosine(v[0], v[2])


@pytest.mark.integration
@requires_live(f"{EMBED_URL}/healthz", "L1 嵌入服务")
def test_m2_spec_dim_matches_config():
    """③向量维度与 config 一致。"""
    import httpx

    from core.config import load_config

    cfg = load_config()
    health = httpx.get(f"{EMBED_URL}/healthz", timeout=10).json()
    data = _live_embed([{"type": "text", "content": "维度检查"}])
    assert data["dim"] == cfg.embedder.effective_dim == health["dim"]
    assert len(data["vectors"][0]) == cfg.embedder.effective_dim


# ---------------------------------------------------------------- 单元用例

def test_truncate_and_normalize():
    vec = [3.0, 4.0, 0.0, 0.0]
    out = truncate_and_normalize(vec, 2)
    assert len(out) == 2
    assert abs(sum(x * x for x in out) - 1.0) < 1e-9
    with pytest.raises(LayerError):
        truncate_and_normalize([1.0], 8)


async def test_fake_embedder_deterministic_and_discriminative():
    emb = FakeDeterministicEmbedder(dim=64)
    v1 = await emb.embed([MultimodalInput.text("用户的猫叫 Benjamin")])
    v2 = await emb.embed([MultimodalInput.text("用户的猫叫 Benjamin")])
    v3 = await emb.embed([MultimodalInput.text("完全无关的另一句话")])
    assert v1[0] == v2[0]
    assert cosine(v1[0], v3[0]) < cosine(v1[0], v2[0])


@pytest.fixture()
def embed_client():
    cfg = make_fake_config()
    app = create_app(cfg)
    with TestClient(app) as client:
        yield client


def test_embed_endpoint_contract(embed_client):
    img = MultimodalInput.from_file(FIXTURES / "white_cat.png", "image", "image/png")
    audio = MultimodalInput.from_file(FIXTURES / "tone_440hz.wav", "audio", "audio/wav")
    resp = embed_client.post("/embed", json={"inputs": [
        {"type": "text", "content": "你好"},
        img.model_dump(),
        audio.model_dump(),
    ]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["dim"] == 64
    assert len(data["vectors"]) == 3
    assert all(len(v) == 64 for v in data["vectors"])


def test_embed_endpoint_rejects_empty(embed_client):
    assert embed_client.post("/embed", json={"inputs": []}).status_code == 422


def test_openai_compat_embeddings(embed_client):
    resp = embed_client.post("/v1/embeddings", json={"input": ["a", "b"], "model": "x"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert [d["index"] for d in data["data"]] == [0, 1]
    assert len(data["data"][0]["embedding"]) == 64


def test_healthz(embed_client):
    data = embed_client.get("/healthz").json()
    assert data["status"] == "ok"
    assert data["layer"] == "L1"
    assert data["dim"] == 64
