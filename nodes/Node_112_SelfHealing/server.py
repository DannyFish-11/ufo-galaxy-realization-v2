"""
Node_112_SelfHealing - FastAPI 服务器

提供节点自愈的 REST API
"""

import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import uvicorn

from core.healing_engine import SelfHealingEngine

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Node_112_SelfHealing",
    description="节点自愈引擎 - 异常检测、自动诊断、自动修复",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

healing_config = {
    "node_02_url": "http://localhost:8002",
    "node_65_url": "http://localhost:8065",
    "node_67_url": "http://localhost:8067",
    "node_73_url": "http://localhost:8073"
}
healing_engine = SelfHealingEngine(healing_config)


class HealNodeRequest(BaseModel):
    """修复节点请求"""
    node_id: str = Field(..., description="节点 ID")
    action: Optional[str] = Field(None, description="修复动作（可选）")


@app.get("/")
async def root():
    return {
        "service": "Node_112_SelfHealing",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "Node_112_SelfHealing"}


@app.get("/api/v1/health/status")
async def get_health_status():
    """获取系统健康状态"""
    try:
        result = await healing_engine.get_health_status()
        return result
    except Exception as e:
        logger.error(f"Get health status failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/diagnose/{node_id}")
async def diagnose_node(node_id: str):
    """诊断节点故障"""
    try:
        result = await healing_engine.diagnose_node(node_id)
        if not result.get("success"):
            raise HTTPException(status_code=404, detail=result.get("error"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Diagnose node failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/heal")
async def heal_node(request: HealNodeRequest):
    """修复节点"""
    try:
        result = await healing_engine.heal_node(request.node_id, request.action)
        return result
    except Exception as e:
        logger.error(f"Heal node failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/predict/failures")
async def predict_failures():
    """预测潜在故障"""
    try:
        result = await healing_engine.predict_failures()
        return result
    except Exception as e:
        logger.error(f"Predict failures failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/stats")
async def get_stats():
    """获取统计信息"""
    try:
        stats = healing_engine.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Get stats failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Node_112_SelfHealing Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8112, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    
    args = parser.parse_args()
    
    logger.info(f"Starting Node_112_SelfHealing on {args.host}:{args.port}")
    
    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )
