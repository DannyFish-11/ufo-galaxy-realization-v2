"""L1 嵌入服务(:8001,BUILD_SPEC M2)。

路由:
- POST /embed            本项目契约接口 {"inputs":[{"type":..,"content":..}]}
- GET  /healthz          启动即完成加载(fail-fast),健康即可服务
- POST /v1/embeddings    OpenAI 兼容(SimpleMem 等上游可直接对接)
- POST /v1/chat/completions  网关:反代到 L0 vLLM —— SimpleMem 的 LLM 与嵌入
  共用同一个 base_url(上游 _get_openai_client 的限制),把它指到本服务即可
  同时命中 L0 与 L1,零上游改动。
- GET  /v1/models        反代 L0(健康检查兼容)
"""

from __future__ import annotations

import contextlib
import logging

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from adapters.embedder import Embedder, build_embedder
from core.config import AppConfig, load_config
from core.errors import LayerError
from core.schemas import EmbedRequest, EmbedResponse, MultimodalInput

logger = logging.getLogger(__name__)


def create_app(config: AppConfig | None = None, embedder: Embedder | None = None) -> FastAPI:
    cfg = config or load_config()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        emb = embedder or build_embedder(cfg.embedder)
        # fail-fast:启动时跑一次探针嵌入,加载失败立即崩,不静默降级
        probe = await emb.embed([MultimodalInput.text("healthcheck probe")])
        if len(probe[0]) != cfg.embedder.effective_dim:
            raise LayerError(
                "L1", "embed-service",
                f"探针维度 {len(probe[0])} != config 期望 {cfg.embedder.effective_dim}",
            )
        app.state.embedder = emb
        app.state.proxy = httpx.AsyncClient(base_url=cfg.llm.base_url.rstrip("/"), timeout=cfg.llm.timeout_s)
        logger.info("L1 embed service ready: backend=%s dim=%d", cfg.embedder.backend, emb.dim)
        yield
        await app.state.proxy.aclose()

    app = FastAPI(title="memory-agent L1 embed service", lifespan=lifespan)

    @app.exception_handler(LayerError)
    async def layer_error_handler(_req: Request, exc: LayerError):
        return JSONResponse(status_code=502, content={"error": str(exc), "layer": exc.layer})

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "layer": "L1", "backend": cfg.embedder.backend,
                "model": cfg.embedder.model_name, "dim": cfg.embedder.effective_dim}

    @app.post("/embed", response_model=EmbedResponse)
    async def embed(req: EmbedRequest):
        if not req.inputs:
            raise HTTPException(status_code=422, detail="inputs 不能为空")
        vectors = await app.state.embedder.embed(req.inputs)
        return EmbedResponse(vectors=vectors, dim=app.state.embedder.dim, model=cfg.embedder.model_name)

    # ---- OpenAI 兼容层 ----

    @app.post("/v1/embeddings")
    async def openai_embeddings(payload: dict):
        raw = payload.get("input", [])
        texts = [raw] if isinstance(raw, str) else list(raw)
        if not texts or not all(isinstance(t, str) for t in texts):
            raise HTTPException(status_code=422, detail="input 须为字符串或字符串数组")
        vectors = await app.state.embedder.embed([MultimodalInput.text(t) for t in texts])
        return {
            "object": "list",
            "model": cfg.embedder.model_name,
            "data": [
                {"object": "embedding", "index": i, "embedding": v}
                for i, v in enumerate(vectors)
            ],
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }

    @app.post("/v1/chat/completions")
    async def proxy_chat(request: Request):
        body = await request.body()
        try:
            resp = await app.state.proxy.post(
                "/chat/completions", content=body,
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise LayerError("L0", "gateway", f"vLLM 不可达 {cfg.llm.base_url}: {exc}") from exc
        return JSONResponse(status_code=resp.status_code, content=resp.json())

    @app.get("/v1/models")
    async def proxy_models():
        try:
            resp = await app.state.proxy.get("/models")
        except httpx.HTTPError as exc:
            raise LayerError("L0", "gateway", f"vLLM 不可达 {cfg.llm.base_url}: {exc}") from exc
        return JSONResponse(status_code=resp.status_code, content=resp.json())

    return app


def main() -> None:
    import uvicorn

    cfg = load_config()
    uvicorn.run(create_app(cfg), host=cfg.services.embed_host, port=cfg.services.embed_port)


if __name__ == "__main__":
    main()
