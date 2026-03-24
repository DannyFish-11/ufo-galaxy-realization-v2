"""
Node_XXX_YourNodeName — <short one-line description>

Replace all occurrences of:
  Node_XXX_YourNodeName  → your actual node ID and name  (e.g. Node_042_Scheduler)
  <PORT>                  → the port this node listens on (must be unique; declare in node_dependencies.json)
  <DESCRIPTION>           → what this node does

Usage
-----
    uvicorn main:app --host 0.0.0.0 --port <PORT>

Health surface (required for active nodes)
-------------------------------------------
    GET /health  → {"status": "healthy", "node": "Node_XXX_YourNodeName"}
    GET /status  → {"node": "Node_XXX_YourNodeName", "port": <PORT>, ...}
"""

# ---------------------------------------------------------------------------
# sys.path fix — keeps the project-root `core/` package visible while
# preventing the local node directory from shadowing it.
# ---------------------------------------------------------------------------
import sys as _sys
import os as _os

_project_root = _os.path.dirname(
    _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
)
if not _sys.path or _sys.path[0] != _project_root:
    _sys.path.insert(0, _project_root)

# ---------------------------------------------------------------------------
# Standard imports
# ---------------------------------------------------------------------------
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Shared CORS helper (nodes/common/cors_config.py)
try:
    from nodes.common.cors_config import get_cors_origins
except ImportError:  # running in isolation without the full project tree
    def get_cors_origins():
        return ["*"]

logger = logging.getLogger("Node_XXX_YourNodeName")

# ---------------------------------------------------------------------------
# Node state (replace with your actual data structures)
# ---------------------------------------------------------------------------

NODE_ID = "Node_XXX_YourNodeName"
NODE_PORT = 0  # Replace with the real port declared in node_dependencies.json


class NodeState:
    """Holds runtime state for this node.  Replace with real implementation."""

    def __init__(self) -> None:
        self.ready: bool = False

    def initialise(self) -> None:
        # TODO: open DB connections, load models, etc.
        self.ready = True
        logger.info(f"✅ {NODE_ID} initialised")

    def teardown(self) -> None:
        # TODO: close connections, flush buffers, etc.
        logger.info(f"🛑 {NODE_ID} shutting down")


_state = NodeState()


# ---------------------------------------------------------------------------
# FastAPI lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    _state.initialise()
    yield
    _state.teardown()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title=NODE_ID,
    description="<DESCRIPTION>",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Required health / status surface (active-node contract)
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> Dict[str, Any]:
    """Liveness probe — always returns HTTP 200 when the process is alive."""
    return {"status": "healthy", "node": NODE_ID}


@app.get("/status")
async def status() -> Dict[str, Any]:
    """Readiness probe — exposes operational state of this node."""
    return {
        "node": NODE_ID,
        "port": NODE_PORT,
        "ready": _state.ready,
    }


# ---------------------------------------------------------------------------
# Business endpoints — add your own routes below
# ---------------------------------------------------------------------------

# Example:
# @app.post("/run")
# async def run(payload: dict) -> dict:
#     ...


# ---------------------------------------------------------------------------
# Module-level accessor used by fusion_entry.py
# ---------------------------------------------------------------------------

def get_instance():
    """Return the node state object for use by the fusion layer."""
    return _state


# ---------------------------------------------------------------------------
# Direct execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=NODE_PORT, reload=False)
