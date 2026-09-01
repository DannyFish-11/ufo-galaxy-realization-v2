"""L3 Memory-Agent FastAPI 服务(:8002,BUILD_SPEC M3)。

路由:/chat /memory/add /memory/search /memory/consolidate /healthz。
启动时对 L0/L1/L2 做依赖健康检查,任何一层不可达立即失败并指明层号。
"""

from __future__ import annotations

import contextlib
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from adapters.embedder import RemoteEmbedderAdapter, build_embedder
from adapters.llm import VLLMOpenAIAdapter
from core.agent import MemoryAgent
from core.config import AppConfig, load_config
from core.errors import LayerError
from core.factory import build_memory_store
from core.schemas import (
    ChatRequest,
    ChatResponse,
    ConsolidationReport,
    HealthReport,
    MemoryAddRequest,
    MemoryAddResponse,
    MemoryHit,
    MemorySearchRequest,
    MultimodalInput,
)

logger = logging.getLogger(__name__)


def create_app(
    config: AppConfig | None = None,
    llm=None,
    memory=None,
    skip_dependency_checks: bool = False,
) -> FastAPI:
    cfg = config or load_config()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        _llm = llm or VLLMOpenAIAdapter(
            base_url=cfg.llm.base_url, model=cfg.llm.model,
            api_key=cfg.llm.api_key, timeout_s=cfg.llm.timeout_s,
        )
        if cfg.embedder.backend == "remote":
            _embedder = RemoteEmbedderAdapter(cfg.embedder.base_url, cfg.embedder.effective_dim)
        else:
            _embedder = build_embedder(cfg.embedder)

        # fail-fast 依赖健康检查(BUILD_SPEC §0.2-5)
        if not skip_dependency_checks:
            if hasattr(_llm, "health"):
                await _llm.health()
            if hasattr(_embedder, "health"):
                await _embedder.health()

        _memory = memory if memory is not None else build_memory_store(cfg, embedder=_embedder, llm=_llm)
        app.state.llm = _llm
        app.state.memory = _memory
        app.state.agent = MemoryAgent(_llm, _memory, cfg)
        logger.info("L3 api ready: memory.backend=%s", cfg.memory.backend)
        yield
        await app.state.agent.drain()

    app = FastAPI(title="memory-agent L3 api", lifespan=lifespan)

    @app.exception_handler(LayerError)
    async def layer_error_handler(_req: Request, exc: LayerError):
        return JSONResponse(status_code=502, content={"error": str(exc), "layer": exc.layer})

    @app.get("/healthz", response_model=HealthReport)
    async def healthz():
        layers: dict[str, str] = {"L3": "ok"}
        status = "ok"
        for name, obj in (("L0", app.state.llm), ("L2", app.state.memory)):
            try:
                if hasattr(obj, "health"):
                    await obj.health()
                layers[name] = "ok"
            except LayerError as exc:
                layers[name] = str(exc)
                status = "degraded"
        return HealthReport(status=status, layers=layers)

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest):
        image = None
        if req.image_base64:
            image = MultimodalInput(type="image", content=req.image_base64, mime=req.image_mime)
        return await app.state.agent.chat(
            req.message, session_id=req.session_id, image=image, sync_memory_write=True,
        )

    @app.post("/memory/add", response_model=MemoryAddResponse)
    async def memory_add(req: MemoryAddRequest):
        mem_id = await app.state.memory.add(req.input, req.meta)
        return MemoryAddResponse(ids=[mem_id])

    @app.post("/memory/search", response_model=list[MemoryHit])
    async def memory_search(req: MemorySearchRequest):
        return await app.state.memory.search(req.query, k=req.k)

    @app.post("/memory/consolidate", response_model=ConsolidationReport)
    async def memory_consolidate():
        return await app.state.memory.consolidate()

    return app


def main() -> None:
    import uvicorn

    cfg = load_config()
    uvicorn.run(create_app(cfg), host=cfg.services.api_host, port=cfg.services.api_port)


if __name__ == "__main__":
    main()
