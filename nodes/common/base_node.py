"""Shared base utilities for Galaxy nodes."""
import os
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_node_app(
    node_id: str,
    node_name: str,
    description: str = "",
    version: str = "1.0.0",
) -> FastAPI:
    """Create a standard FastAPI app for a Galaxy node with health endpoint and CORS."""
    _start_time = time.time()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(f"Node {node_id} ({node_name}) starting...")
        yield
        logger.info(f"Node {node_id} ({node_name}) shutting down...")

    log_level = os.getenv("GALAXY_LOG_LEVEL", "INFO")
    logger = logging.getLogger(f"Galaxy.{node_name}")
    logging.basicConfig(level=getattr(logging, log_level, logging.INFO))

    app = FastAPI(
        title=f"Galaxy Node {node_id}: {node_name}",
        description=description,
        version=version,
        lifespan=lifespan,
    )

    # CORS
    try:
        from nodes.common.cors_config import get_cors_origins
        origins = get_cors_origins()
    except ImportError:
        origins = ["*"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "node_id": node_id,
            "node_name": node_name,
            "version": version,
            "uptime_seconds": round(time.time() - _start_time, 1),
        }

    return app
