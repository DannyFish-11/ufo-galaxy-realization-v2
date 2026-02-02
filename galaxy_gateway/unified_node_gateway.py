#!/usr/bin/env python3
"""
UFO Galaxy Fusion - Unified Node Gateway (Standardized)

统一节点网关（标准化版）

核心职责:
1. 动态加载 102 个节点的标准化入口 (fusion_entry.py)
2. 提供统一的 HTTP API 路由 (/api/nodes/{node_id}/execute)
3. 隔离节点执行环境，提供统一的错误处理

作者: Manus AI
日期: 2026-01-26
版本: 1.1.0 (标准化版)
"""

import os
import sys
import importlib
import logging
import asyncio
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("UnifiedGateway")

app = FastAPI(title="UFO Galaxy Unified Node Gateway")

# 节点实例缓存
node_instances: Dict[str, Any] = {}

class ExecuteRequest(BaseModel):
    command: str
    params: Dict[str, Any] = {}

def load_nodes():
    """动态扫描并加载 nodes/ 目录下的所有标准化节点"""
    nodes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes")
    if not os.path.exists(nodes_dir):
        logger.error(f"❌ Nodes directory not found: {nodes_dir}")
        return

    if nodes_dir not in sys.path:
        sys.path.append(nodes_dir)
    
    # 扫描 Node_XX 格式的目录
    for item in os.listdir(nodes_dir):
        if item.startswith("Node_") and os.path.isdir(os.path.join(nodes_dir, item)):
            node_id = "_".join(item.split('_')[:2])
            try:
                # 优先加载标准化入口 fusion_entry.py
                module_path = f"{item}.fusion_entry"
                try:
                    module = importlib.import_module(module_path)
                    if hasattr(module, "get_node_instance"):
                        node_instances[node_id] = module.get_node_instance()
                        logger.info(f"✅ Loaded standardized node: {node_id}")
                        continue
                except ImportError:
                    logger.debug(f"ℹ️  No fusion_entry found for {node_id}, trying legacy load...")

                # 备选：尝试直接加载 main.py (旧逻辑)
                module_path = f"{item}.main"
                module = importlib.import_module(module_path)
                instance = None
                if hasattr(module, "get_instance"):
                    instance = module.get_instance()
                elif hasattr(module, "Node"):
                    instance = module.Node()
                
                if instance:
                    node_instances[node_id] = instance
                    logger.info(f"✅ Loaded legacy node: {node_id}")
                else:
                    logger.warning(f"⚠️  Node {node_id} has no valid entry point")
            except Exception as e:
                logger.error(f"❌ Failed to load node {node_id}: {e}")

@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting Unified Node Gateway...")
    load_nodes()
    logger.info(f"✨ Total nodes online: {len(node_instances)}")

@app.get("/health")
async def global_health():
    return {"status": "healthy", "online_nodes": len(node_instances)}

@app.post("/api/nodes/{node_id}/execute")
async def execute_on_node(node_id: str, request: ExecuteRequest):
    if node_id not in node_instances:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    
    instance = node_instances[node_id]
    
    try:
        # 统一调用接口
        if hasattr(instance, "execute"):
            method = instance.execute
        elif hasattr(instance, "process"):
            method = instance.process
        else:
            raise HTTPException(status_code=500, detail=f"Node {node_id} has no executable method")
            
        if asyncio.iscoroutinefunction(method):
            result = await method(request.command, **request.params)
        else:
            result = method(request.command, **request.params)
            
        # 如果返回的是字典且包含 success 键，则直接返回
        if isinstance(result, dict) and "success" in result:
            return result
        return {"success": True, "node_id": node_id, "data": result}
        
    except Exception as e:
        logger.error(f"❌ Error executing on {node_id}: {e}")
        return {"success": False, "node_id": node_id, "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
