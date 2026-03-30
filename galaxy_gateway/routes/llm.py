"""
galaxy_gateway/routes/llm.py — LLM cost/performance tracking endpoint.

Routes:
  GET /api/v1/llm/stats   - LLM router statistics (cost, latency, provider status)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from galaxy_gateway.dependencies import get_llm_router_instance

try:
    from core.auth import require_auth as _require_auth
except ImportError:
    async def _require_auth():  # type: ignore[misc]
        return {"authenticated": True, "dev_mode": True}

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/v1/llm/stats")
async def llm_stats(
    auth: dict = Depends(_require_auth),
    llm=Depends(get_llm_router_instance),
):
    """LLM router statistics — cost, latency, provider status."""
    if llm is None:
        raise HTTPException(status_code=503, detail="LLM Router not available")
    try:
        return llm.get_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
