"""
UFO³ Galaxy Dashboard Backend
可视化界面后端 API

功能：
1. 节点状态监控
2. 任务编排管理
3. 记忆系统查询
4. 日志聚合查看
5. 性能指标统计
"""

import os
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import httpx

# =============================================================================
# Configuration
# =============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# 节点基础 URL
NODE_BASE_URL = os.getenv("NODE_BASE_URL", "http://localhost")
NODE_PORT_START = int(os.getenv("NODE_PORT_START", "8000"))

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="[Dashboard] %(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# Models
# =============================================================================

class NodeStatus(BaseModel):
    node_id: str
    name: str
    status: str  # running, stopped, error
    url: str
    health: Optional[Dict[str, Any]] = None
    last_check: str

class TaskRequest(BaseModel):
    task_type: str  # simple, sequential, parallel, conditional
    description: str
    nodes: List[str]
    parameters: Dict[str, Any] = {}

# =============================================================================
# Dashboard Service
# =============================================================================

class DashboardService:
    """Dashboard 服务"""
    
    def __init__(self):
        self.http_client = httpx.AsyncClient(timeout=10)
        self.node_status_cache: Dict[str, NodeStatus] = {}
        self.websocket_clients: List[WebSocket] = []
        
        # 节点映射（ID -> Name）
        self.node_map = {
            "00": "StateMachine",
            "01": "OneAPI",
            "02": "Tasker",
            "65": "LoggerCentral",
            "67": "HealthMonitor",
            "79": "LocalLLM",
            "80": "MemorySystem",
            "81": "Orchestrator",
            "82": "NetworkGuard",
            "83": "NewsAggregator",
            "84": "StockTracker",
            "85": "PromptLibrary",
        }
    
    async def check_node_health(self, node_id: str) -> NodeStatus:
        """检查节点健康状态"""
        node_name = self.node_map.get(node_id, f"Node{node_id}")
        port = NODE_PORT_START + int(node_id)
        url = f"{NODE_BASE_URL}:{port}"
        
        status = NodeStatus(
            node_id=node_id,
            name=node_name,
            status="unknown",
            url=url,
            last_check=datetime.now().isoformat()
        )
        
        try:
            # 尝试访问 /health 端点
            response = await self.http_client.get(f"{url}/health", timeout=5)
            
            if response.status_code == 200:
                status.status = "running"
                status.health = response.json()
            else:
                status.status = "error"
        
        except httpx.ConnectError:
            status.status = "stopped"
        except Exception as e:
            status.status = "error"
            logger.error(f"Error checking node {node_id}: {e}")
        
        self.node_status_cache[node_id] = status
        return status
    
    async def get_all_nodes_status(self) -> List[NodeStatus]:
        """获取所有节点状态"""
        tasks = [
            self.check_node_health(node_id)
            for node_id in self.node_map.keys()
        ]
        
        statuses = await asyncio.gather(*tasks)
        return list(statuses)
    
    async def call_node_api(
        self,
        node_id: str,
        endpoint: str,
        method: str = "GET",
        data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """调用节点 API"""
        port = NODE_PORT_START + int(node_id)
        url = f"{NODE_BASE_URL}:{port}{endpoint}"
        
        try:
            if method == "GET":
                response = await self.http_client.get(url)
            elif method == "POST":
                response = await self.http_client.post(url, json=data)
            elif method == "PUT":
                response = await self.http_client.put(url, json=data)
            elif method == "DELETE":
                response = await self.http_client.delete(url)
            else:
                raise HTTPException(status_code=400, detail="Invalid method")
            
            response.raise_for_status()
            return response.json()
        
        except Exception as e:
            logger.error(f"Error calling node {node_id} API: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    async def get_system_overview(self) -> Dict[str, Any]:
        """获取系统概览"""
        statuses = await self.get_all_nodes_status()
        
        running_count = sum(1 for s in statuses if s.status == "running")
        stopped_count = sum(1 for s in statuses if s.status == "stopped")
        error_count = sum(1 for s in statuses if s.status == "error")
        
        return {
            "total_nodes": len(statuses),
            "running": running_count,
            "stopped": stopped_count,
            "error": error_count,
            "health_rate": f"{running_count / len(statuses) * 100:.1f}%",
            "timestamp": datetime.now().isoformat()
        }
    
    async def get_memory_stats(self) -> Dict[str, Any]:
        """获取记忆系统统计"""
        try:
            return await self.call_node_api("80", "/stats")
        except Exception:
            return {"error": "Memory system unavailable"}
    
    async def get_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取日志"""
        try:
            response = await self.call_node_api("65", f"/logs?limit={limit}")
            return response.get("logs", [])
        except Exception:
            return []
    
    async def broadcast_update(self, message: Dict[str, Any]):
        """广播更新到所有 WebSocket 客户端"""
        disconnected = []
        
        for client in self.websocket_clients:
            try:
                await client.send_json(message)
            except Exception:
                disconnected.append(client)
        
        # 移除断开的客户端
        for client in disconnected:
            self.websocket_clients.remove(client)
    
    async def close(self):
        """关闭客户端"""
        await self.http_client.aclose()

# =============================================================================
# FastAPI Application
# =============================================================================

dashboard = DashboardService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting UFO³ Galaxy Dashboard")
    
    # 启动后台状态监控
    async def status_monitor():
        while True:
            await asyncio.sleep(30)  # 每 30 秒更新一次
            try:
                overview = await dashboard.get_system_overview()
                await dashboard.broadcast_update({
                    "type": "system_overview",
                    "data": overview
                })
            except Exception as e:
                logger.error(f"Status monitor error: {e}")
    
    task = asyncio.create_task(status_monitor())
    
    yield
    
    task.cancel()
    await dashboard.close()
    logger.info("Dashboard shutdown complete")

app = FastAPI(
    title="UFO³ Galaxy Dashboard",
    description="可视化管理界面",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/")
async def root():
    return {
        "service": "UFO³ Galaxy Dashboard",
        "status": "running",
        "version": "1.0.0"
    }

@app.get("/api/overview")
async def get_overview():
    """获取系统概览"""
    overview = await dashboard.get_system_overview()
    return overview

@app.get("/api/nodes")
async def get_nodes():
    """获取所有节点状态"""
    statuses = await dashboard.get_all_nodes_status()
    return {
        "nodes": [s.dict() for s in statuses],
        "count": len(statuses)
    }

@app.get("/api/nodes/{node_id}")
async def get_node(node_id: str):
    """获取单个节点状态"""
    status = await dashboard.check_node_health(node_id)
    return status.dict()

@app.post("/api/nodes/{node_id}/restart")
async def restart_node(node_id: str):
    """重启节点（通过 Node 67）"""
    try:
        result = await dashboard.call_node_api(
            "67",
            f"/restart/{node_id}",
            method="POST"
        )
        return result
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to restart node")

@app.get("/api/memory/stats")
async def get_memory_stats():
    """获取记忆系统统计"""
    stats = await dashboard.get_memory_stats()
    return stats

@app.get("/api/memory/conversations")
async def get_conversations():
    """获取对话历史"""
    try:
        return await dashboard.call_node_api("80", "/conversations")
    except Exception:
        return {"conversations": []}

@app.get("/api/logs")
async def get_logs(limit: int = 100):
    """获取日志"""
    logs = await dashboard.get_logs(limit)
    return {"logs": logs, "count": len(logs)}

@app.post("/api/tasks")
async def create_task(task: TaskRequest):
    """创建任务（通过 Node 81）"""
    try:
        result = await dashboard.call_node_api(
            "81",
            "/tasks",
            method="POST",
            data=task.dict()
        )
        return result
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create task")

@app.get("/api/tasks")
async def get_tasks():
    """获取任务列表"""
    try:
        return await dashboard.call_node_api("81", "/tasks")
    except Exception:
        return {"tasks": []}

@app.get("/api/prompts")
async def get_prompts():
    """获取提示词库"""
    try:
        return await dashboard.call_node_api("85", "/prompts")
    except Exception:
        return {"prompts": []}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 实时更新"""
    await websocket.accept()
    dashboard.websocket_clients.append(websocket)
    
    try:
        while True:
            # 保持连接
            data = await websocket.receive_text()
            
            # 处理客户端请求
            if data == "ping":
                await websocket.send_json({"type": "pong"})
    
    except WebSocketDisconnect:
        dashboard.websocket_clients.remove(websocket)

# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000)
