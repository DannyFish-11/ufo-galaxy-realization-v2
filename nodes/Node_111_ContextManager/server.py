"""
Node_111_ContextManager - FastAPI 服务器

提供上下文管理的 REST API
"""

import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
import uvicorn

from core.context_engine import ContextManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Node_111_ContextManager",
    description="上下文管理引擎 - 跨会话持久化、用户画像、智能检索",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

context_manager_config = {
    "node_01_url": "http://localhost:8001",
    "node_13_url": "http://localhost:8013",
    "node_20_url": "http://localhost:8020",
    "node_73_url": "http://localhost:8073",
    "node_100_url": "http://localhost:8100",
    "db_path": "context_manager.db"
}
context_manager = ContextManager(context_manager_config)


class SaveContextRequest(BaseModel):
    """保存上下文请求"""
    session_id: str = Field(..., description="会话 ID")
    user_id: str = Field(..., description="用户 ID")
    messages: List[Dict[str, str]] = Field(..., description="消息列表")
    metadata: Optional[Dict[str, Any]] = Field(None, description="元数据")


class SearchContextRequest(BaseModel):
    """搜索上下文请求"""
    query: str = Field(..., description="搜索查询")
    user_id: Optional[str] = Field(None, description="用户 ID（可选）")
    limit: int = Field(5, description="返回结果数量")


@app.get("/")
async def root():
    return {
        "service": "Node_111_ContextManager",
        "version": "1.0.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "Node_111_ContextManager"}


@app.post("/api/v1/context/save")
async def save_context(request: SaveContextRequest):
    """保存上下文"""
    try:
        result = await context_manager.save_context(
            session_id=request.session_id,
            user_id=request.user_id,
            messages=request.messages,
            metadata=request.metadata
        )
        return result
    except Exception as e:
        logger.error(f"Save context failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/context/{session_id}")
async def get_context(session_id: str, limit: Optional[int] = None):
    """获取上下文"""
    try:
        result = await context_manager.get_context(session_id, limit)
        if not result.get("success", True):
            raise HTTPException(status_code=404, detail=result.get("error"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get context failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/context/search")
async def search_context(request: SearchContextRequest):
    """搜索相关上下文"""
    try:
        result = await context_manager.search_context(
            query=request.query,
            user_id=request.user_id,
            limit=request.limit
        )
        return result
    except Exception as e:
        logger.error(f"Search context failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/user/profile/{user_id}")
async def get_user_profile(user_id: str):
    """获取用户画像"""
    try:
        result = await context_manager.get_user_profile(user_id)
        return result
    except Exception as e:
        logger.error(f"Get user profile failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/stats")
async def get_stats():
    """获取统计信息"""
    try:
        stats = context_manager.get_stats()
        return stats
    except Exception as e:
        logger.error(f"Get stats failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Node_111_ContextManager Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8111, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    
    args = parser.parse_args()
    
    logger.info(f"Starting Node_111_ContextManager on {args.host}:{args.port}")
    
    uvicorn.run(
        "server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )
