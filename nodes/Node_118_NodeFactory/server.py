"""
Node_115_NodeFactory - FastAPI Server
节点工厂服务器
"""

import os
import sys
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
import uvicorn

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.node_factory_engine import (
    NodeFactoryEngine,
    NodeSpecification,
    NodeType
)

# ========== 配置 ==========
NODE_PORT = int(os.getenv("NODE_115_PORT", "9104"))
NODE_HOST = os.getenv("NODE_HOST", "0.0.0.0")

# ========== FastAPI 应用 ==========
app = FastAPI(
    title="Node_115_NodeFactory",
    description="节点工厂 - 动态生成和部署新节点",
    version="0.1.0"
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ========== 全局引擎实例 ==========
engine = NodeFactoryEngine()

# ========== Pydantic 模型 ==========

class GenerateNodeRequest(BaseModel):
    """生成节点请求"""
    node_number: int = Field(..., description="节点编号")
    node_name: str = Field(..., description="节点名称")
    node_type: str = Field(..., description="节点类型: perception/cognition/action/learning/integration")
    description: str = Field(..., description="节点描述")
    port: int = Field(..., description="端口")
    capabilities: Optional[List[str]] = Field(default_factory=list, description="能力列表")
    dependencies: Optional[List[int]] = Field(default_factory=list, description="依赖节点编号列表")
    api_endpoints: Optional[List[Dict[str, str]]] = Field(default_factory=list, description="API 端点列表")
    auto_deploy: Optional[bool] = Field(False, description="是否自动部署")

class GenerateNodeFromDescriptionRequest(BaseModel):
    """从描述生成节点请求"""
    description: str = Field(..., description="节点描述")
    node_number: int = Field(..., description="节点编号")
    port: int = Field(..., description="端口")
    auto_deploy: Optional[bool] = Field(False, description="是否自动部署")

# ========== API 端点 ==========

@app.get("/")
async def root():
    """根端点"""
    return {
        "node": "Node_115_NodeFactory",
        "status": "running",
        "version": "0.1.0",
        "description": "节点工厂 - 动态生成和部署新节点"
    }

@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "generated_nodes_count": len(engine.generation_history)
    }

@app.post("/api/v1/generate_node", response_model=Dict[str, Any])
async def generate_node(request: GenerateNodeRequest):
    """
    生成节点
    
    Args:
        request: 生成节点请求
        
    Returns:
        Dict: 生成结果
    """
    try:
        # 验证节点类型
        try:
            node_type = NodeType(request.node_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid node_type. Must be one of: {[t.value for t in NodeType]}"
            )
        
        # 创建节点规格
        node_spec = NodeSpecification(
            node_number=request.node_number,
            node_name=request.node_name,
            node_type=node_type,
            description=request.description,
            port=request.port,
            capabilities=request.capabilities or [],
            dependencies=request.dependencies or [],
            api_endpoints=request.api_endpoints or []
        )
        
        # 生成节点
        result = engine.generate_node(node_spec, auto_deploy=request.auto_deploy)
        
        return result.to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/v1/generate_node_from_description", response_model=Dict[str, Any])
async def generate_node_from_description(request: GenerateNodeFromDescriptionRequest):
    """
    从自然语言描述生成节点
    
    Args:
        request: 从描述生成节点请求
        
    Returns:
        Dict: 生成结果
    """
    try:
        result = engine.generate_node_from_description(
            description=request.description,
            node_number=request.node_number,
            port=request.port,
            auto_deploy=request.auto_deploy
        )
        
        return result.to_dict()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/generation_history", response_model=List[Dict[str, Any]])
async def get_generation_history(limit: int = 100):
    """
    获取生成历史
    
    Args:
        limit: 返回数量限制
        
    Returns:
        List[Dict]: 生成历史
    """
    try:
        history = engine.get_generation_history(limit=limit)
        return [r.to_dict() for r in history]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ========== 主函数 ==========

if __name__ == "__main__":
    print(f"🚀 Starting Node_115_NodeFactory on {NODE_HOST}:{NODE_PORT}")
    print(f"📚 API Documentation: http://{NODE_HOST}:{NODE_PORT}/docs")
    
    uvicorn.run(
        app,
        host=NODE_HOST,
        port=NODE_PORT,
        log_level="info"
    )
