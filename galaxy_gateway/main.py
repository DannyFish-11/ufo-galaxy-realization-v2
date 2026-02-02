"""
UFO³ Galaxy Gateway - 超级网关
统一调用 One-API、本地 LLM 和所有节点功能
"""

import sys
sys.path.append("/home/ubuntu/ufo-galaxy-check")

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Dict, Optional, Any
import uvicorn

from shared.llm_client import UnifiedLLMClient, TaskType
from shared.node_registry import NodeRegistry, NodeCategory, NodeInfo
from websocket_handler import handle_websocket, connection_manager
from device_router import device_router
import uuid


app = FastAPI(
    title="UFO³ Galaxy Gateway",
    description="统一调用 One-API、本地 LLM 和所有节点功能的超级网关",
    version="1.0.0"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化客户端
llm_client = UnifiedLLMClient()
node_registry = NodeRegistry()


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
        "service": "UFO³ Galaxy Gateway",
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
        response = await llm_client.chat(
            messages=request.messages,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=request.stream
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/llm/ask")
async def llm_ask(request: SimpleAskRequest):
    """
    简单问答接口
    快速单轮对话
    """
    try:
        answer = await llm_client.simple_ask(
            question=request.question,
            model=request.model,
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
        code = await llm_client.code_generation(
            prompt=request.prompt,
            language=request.language
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
        result = await llm_client.real_time_search(question)
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
        cat = NodeCategory(category) if category else None
        nodes = node_registry.list_nodes(category=cat, status=status)
        return {
            "count": len(nodes),
            "nodes": [
                {
                    "node_id": n.node_id,
                    "name": n.name,
                    "description": n.description,
                    "category": n.category.value,
                    "url": n.url,
                    "port": n.port,
                    "methods": n.methods,
                    "status": n.status,
                    "priority": n.priority
                }
                for n in nodes
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/node/{node_id}")
async def get_node_info(node_id: str):
    """
    获取节点信息
    """
    node = node_registry.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Node {node_id} not found")
    
    return {
        "node_id": node.node_id,
        "name": node.name,
        "description": node.description,
        "category": node.category.value,
        "url": node.url,
        "port": node.port,
        "methods": node.methods,
        "status": node.status,
        "priority": node.priority
    }


@app.get("/api/node/{node_id}/health")
async def check_node_health(node_id: str):
    """
    检查节点健康状态
    """
    is_healthy = await node_registry.check_node_health(node_id)
    return {
        "node_id": node_id,
        "healthy": is_healthy,
        "status": "online" if is_healthy else "offline"
    }


@app.post("/api/node/call")
async def call_node(request: NodeCallRequest):
    """
    调用节点方法
    """
    try:
        result = await node_registry.call_node(
            node_id=request.node_id,
            method=request.method,
            params=request.params
        )
        return result
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
        
        analysis = await llm_client.simple_ask(
            question=analysis_prompt,
            model="auto"
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
    
    for task in request.tasks:
        try:
            node_id = task.get("node")
            method = task.get("method")
            params = task.get("params", {})
            
            result = await node_registry.call_node(
                node_id=node_id,
                method=method,
                params=params
            )
            
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
    all_nodes = node_registry.list_nodes()
    
    # 统计各类别节点数量
    category_counts = {}
    for node in all_nodes:
        cat = node.category.value
        category_counts[cat] = category_counts.get(cat, 0) + 1
    
    # 统计节点状态
    status_counts = {
        "online": len([n for n in all_nodes if n.status == "online"]),
        "offline": len([n for n in all_nodes if n.status == "offline"]),
        "unknown": len([n for n in all_nodes if n.status == "unknown"])
    }
    
    return {
        "total_nodes": len(all_nodes),
        "categories": category_counts,
        "status": status_counts,
        "llm_client": {
            "one_api_url": llm_client.one_api_url,
            "local_llm_url": llm_client.local_llm_url
        }
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

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="galaxy_gateway/static"), name="static")

@app.get("/")
async def dashboard():
    """Galaxy Gateway Dashboard"""
    return FileResponse("galaxy_gateway/static/dashboard.html")

@app.websocket("/ws/dashboard")
async def dashboard_websocket(websocket: WebSocket):
    """Dashboard WebSocket 连接"""
    await connection_manager.connect(websocket, "dashboard")
    try:
        while True:
            data = await websocket.receive_json()
            # 处理 Dashboard 消息
            if data.get("type") == "refresh_devices":
                devices = device_router.get_device_status()
                await websocket.send_json({
                    "type": "device_update",
                    "devices": devices
                })
    except Exception as e:
        print(f"Dashboard WebSocket 错误: {e}")
    finally:
        connection_manager.disconnect(websocket)

# ===== 启动服务 =====
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=9000,  # Galaxy Gateway 使用 9000 端口
        log_level="info"
    )
