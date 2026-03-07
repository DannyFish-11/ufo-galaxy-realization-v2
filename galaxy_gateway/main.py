"""
Galaxy Gateway - 超级网关
统一调用 One-API、本地 LLM 和所有节点功能
"""

import os
import sys

# 确保项目根目录在 Python 路径中
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import uvicorn
import uuid
import logging

from core.llm_manager import LLMManager
from galaxy_gateway.websocket_handler import handle_websocket, connection_manager
from galaxy_gateway.device_router import device_router
from nodes.common.cors_config import get_cors_origins

logger = logging.getLogger(__name__)


app = FastAPI(
    title="Galaxy Gateway",
    description="统一调用 One-API、本地 LLM 和所有节点功能的超级网关",
    version="1.0.0"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化 LLM 客户端
llm_client = LLMManager()


# ===== 数据模型 =====

class ChatRequest(BaseModel):
    """LLM 聊天请求"""
    messages: List[Dict[str, str]]
    model: str = "auto"
    temperature: float = 0.7
    max_tokens: int = 2000
    stream: bool = False


class SimpleAskRequest(BaseModel):
    """简单问答请求"""
    question: str
    model: str = "auto"
    system_prompt: Optional[str] = None


class CodeGenerationRequest(BaseModel):
    """代码生成请求"""
    prompt: str
    language: str = "python"


class NodeCallRequest(BaseModel):
    """节点调用请求"""
    node_id: str
    method: str
    params: Optional[Dict[str, Any]] = None


class BatchTaskRequest(BaseModel):
    """批量任务请求"""
    tasks: List[Dict[str, Any]]


class SmartTaskRequest(BaseModel):
    """智能任务请求"""
    task: str
    auto_route: bool = True
    context: Optional[Dict[str, Any]] = None


# ===== LLM 相关接口 =====

@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "Galaxy Gateway",
        "version": "1.0.0",
        "status": "online",
        "endpoints": {
            "llm": {
                "chat": "/api/llm/chat",
                "ask": "/api/llm/ask",
                "code": "/api/llm/code",
                "search": "/api/llm/search"
            },
            "node": {
                "list": "/api/node/list",
                "info": "/api/node/{node_id}",
                "call": "/api/node/call",
                "health": "/api/node/{node_id}/health"
            },
            "task": {
                "execute": "/api/task/execute",
                "batch": "/api/task/batch"
            }
        }
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "healthy"}


@app.post("/api/llm/chat")
async def llm_chat(request: ChatRequest):
    """
    LLM 聊天接口
    支持所有 One-API 和本地 LLM 模型
    """
    try:
        response = await llm_client.chat_completion(
            messages=request.messages,
            model_alias=request.model if request.model != "auto" else None,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        content = response.choices[0].message.content if response.choices else ""
        return {"content": content, "model": response.model, "usage": dict(response.usage) if response.usage else {}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm/ask")
async def llm_ask(request: SimpleAskRequest):
    """
    简单问答接口
    快速单轮对话
    """
    try:
        answer = await llm_client.simple_chat(
            user_message=request.question,
            system_prompt=request.system_prompt
        )
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm/code")
async def llm_code(request: CodeGenerationRequest):
    """
    代码生成接口
    自动使用 DeepSeek-Coder
    """
    try:
        code = await llm_client.simple_chat(
            user_message=f"Generate {request.language} code for: {request.prompt}\n\nReturn ONLY the code, no explanation.",
            system_prompt=f"You are a {request.language} code generator. Output only valid code."
        )
        return {"code": code}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm/search")
async def llm_search(question: str):
    """
    实时搜索接口
    自动使用 Perplexity
    """
    try:
        result = await llm_client.simple_chat(
            user_message=question,
            system_prompt="Answer the question based on your knowledge. Be concise and factual."
        )
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== 节点相关接口 =====

@app.get("/api/node/list")
async def list_nodes(
    category: Optional[str] = None,
    status: Optional[str] = None
):
    """
    列出所有节点
    可按类别和状态筛选
    """
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get("http://127.0.0.1:8000/api/v1/nodes", timeout=5.0)
            return resp.json()
    except Exception as e:
        logger.warning(f"Failed to proxy node list: {e}")
        return {"count": 0, "nodes": [], "error": str(e)}


@app.get("/api/node/{node_id}")
async def get_node_info(node_id: str):
    """
    获取节点信息
    """
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://127.0.0.1:8000/api/v1/nodes/{node_id}", timeout=5.0)
            if resp.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
            return resp.json()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/node/{node_id}/health")
async def check_node_health(node_id: str):
    """
    检查节点健康状态
    """
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"http://127.0.0.1:8000/api/v1/nodes/{node_id}", timeout=5.0)
            data = resp.json()
            is_healthy = data.get("status") == "active" if resp.status_code == 200 else False
            return {"node_id": node_id, "healthy": is_healthy, "status": "online" if is_healthy else "offline"}
    except Exception as e:
        return {"node_id": node_id, "healthy": False, "status": "offline", "error": str(e)}


@app.post("/api/node/call")
async def call_node(request: NodeCallRequest):
    """
    调用节点方法
    """
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "http://127.0.0.1:8000/api/v1/nodes/call",
                json={"node_id": request.node_id, "action": request.method, "params": request.params or {}},
                timeout=30.0,
            )
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ===== 任务相关接口 =====

@app.post("/api/task/execute")
async def execute_smart_task(request: SmartTaskRequest):
    """
    智能任务执行
    自动分析任务并选择合适的节点和模型
    """
    try:
        # 使用 LLM 分析任务
        analysis_prompt = f"""
分析以下任务，确定需要调用哪些节点和使用什么模型：

任务：{request.task}

请以 JSON 格式返回：
{{
    "task_type": "code|search|communication|hardware|general",
    "nodes_needed": ["node_id1", "node_id2"],
    "model_recommended": "model_name",
    "steps": ["step1", "step2"]
}}
"""
        
        analysis = await llm_client.simple_chat(
            user_message=analysis_prompt
        )
        
        # 这里应该解析 analysis 并执行相应的步骤
        # 为简化，直接返回分析结果
        
        return {
            "task": request.task,
            "analysis": analysis,
            "status": "analyzed",
            "message": "任务分析完成，请查看 analysis 字段"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/task/batch")
async def execute_batch_tasks(request: BatchTaskRequest):
    """
    批量执行任务
    """
    results = []
    
    import httpx
    for task in request.tasks:
        node_id = task.get("node", "")
        method = task.get("method", "")
        params = task.get("params", {})
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "http://127.0.0.1:8000/api/v1/nodes/call",
                    json={"node_id": node_id, "action": method, "params": params},
                    timeout=30.0,
                )
                result = resp.json()
            results.append({
                "node": node_id,
                "method": method,
                "status": "success",
                "result": result
            })
        except Exception as e:
            results.append({
                "node": node_id,
                "method": method,
                "status": "error",
                "error": str(e)
            })
    
    return {
        "total": len(request.tasks),
        "success": len([r for r in results if r["status"] == "success"]),
        "failed": len([r for r in results if r["status"] == "error"]),
        "results": results
    }


# ===== 统计和监控接口 =====

@app.get("/api/stats")
async def get_stats():
    """
    获取系统统计信息
    """
    devices = device_router.get_device_status()
    providers = llm_client.get_provider_status()

    return {
        "devices": devices,
        "llm_providers": providers,
        "llm_available": llm_client.is_available(),
        "usage": llm_client.get_usage_summary(),
    }


## ===== WebSocket 端点 =====

@app.websocket("/ws/agent")
async def websocket_agent_endpoint(websocket: WebSocket):
    """
    Agent WebSocket 连接端点
    用于 Android Agent 和其他设备连接
    """
    connection_id = str(uuid.uuid4())
    await handle_websocket(websocket, connection_id)


# ===== 设备管理 API =====

@app.get("/api/devices")
async def get_devices():
    """获取所有设备状态"""
    return device_router.get_device_status()


@app.post("/api/command")
async def send_command(request: Dict[str, Any]):
    """
    发送命令到设备
    支持语音和文本命令
    """
    command = request.get("command", "")
    context = request.get("context", {})
    
    if not command:
        raise HTTPException(status_code=400, detail="命令不能为空")
    
    # 路由任务到合适的设备
    result = await device_router.route_task(command, context)
    
    return result


# ===== Dashboard 路由 =====

_static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

@app.get("/dashboard")
async def dashboard():
    """Galaxy Gateway Dashboard"""
    dashboard_html = os.path.join(_static_dir, "dashboard.html")
    if os.path.exists(dashboard_html):
        return FileResponse(dashboard_html)
    return {"message": "Dashboard HTML not found", "path": dashboard_html}

@app.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    """Dashboard WebSocket 连接"""
    await connection_manager.connect(websocket, "dashboard")
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "refresh_devices":
                devices = device_router.get_device_status()
                await websocket.send_json({
                    "type": "device_update",
                    "devices": devices
                })
    except Exception as e:
        logger.warning(f"Dashboard WebSocket error: {e}")
    finally:
        connection_manager.disconnect("dashboard")

# ===== 启动服务 =====
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=9000,  # Galaxy Gateway 使用 9000 端口
        log_level="info"
    )
