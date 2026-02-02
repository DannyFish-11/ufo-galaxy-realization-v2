"""
Galaxy Gateway v4.0 - 完整的视觉操控系统

集成功能：
1. NLU v2.0（自然语言理解）
2. AIP v2.0（通信协议）
3. 多模态传输
4. P2P 通信
5. 断点续传
6. 视觉理解（Node_90）
7. 多模态 Agent（Node_91）
8. 自动操控（Node_92）

版本：4.0.0
日期：2026-01-22
作者：Manus AI
"""

import os
import asyncio
import httpx
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 导入之前的模块
import sys
sys.path.append(os.path.dirname(__file__))

try:
    from enhanced_nlu_v2 import EnhancedNLU
    from aip_protocol_v2 import AIPMessage, AIPProtocol
    from multimodal_transfer import MultimodalTransfer
    from p2p_connector import P2PConnector
    from resumable_transfer import ResumableTransfer
except ImportError as e:
    print(f"Warning: Failed to import modules: {e}")

app = FastAPI(title="Galaxy Gateway v4.0", version="4.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================================
# 配置
# ============================================================================

# 节点地址
NODE_90_VISION_URL = os.getenv("NODE_90_VISION_URL", "http://localhost:8090")
NODE_91_AGENT_URL = os.getenv("NODE_91_AGENT_URL", "http://localhost:8091")
NODE_92_CONTROL_URL = os.getenv("NODE_92_CONTROL_URL", "http://localhost:8092")

# 初始化模块
nlu = None
aip_protocol = None
multimodal_transfer = None

try:
    nlu = EnhancedNLU()
    aip_protocol = AIPProtocol()
    multimodal_transfer = MultimodalTransfer()
except Exception as e:
    print(f"Warning: Failed to initialize modules: {e}")

# ============================================================================
# 数据模型
# ============================================================================

class CommandRequest(BaseModel):
    """命令请求"""
    command: str
    device_id: Optional[str] = None
    platform: str = "windows"
    context: Optional[Dict[str, Any]] = None

class VisionCommandRequest(BaseModel):
    """视觉命令请求"""
    command: str
    device_id: Optional[str] = None
    platform: str = "windows"
    use_vision: bool = True

# ============================================================================
# 辅助函数
# ============================================================================

async def call_node(url: str, endpoint: str, data: dict) -> dict:
    """调用节点"""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{url}{endpoint}", json=data)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# API 端点 - 基础功能
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    # 检查所有节点
    node_90_status = "unknown"
    node_91_status = "unknown"
    node_92_status = "unknown"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{NODE_90_VISION_URL}/health")
            if response.status_code == 200:
                node_90_status = "healthy"
    except:
        node_90_status = "unhealthy"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{NODE_91_AGENT_URL}/health")
            if response.status_code == 200:
                node_91_status = "healthy"
    except:
        node_91_status = "unhealthy"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{NODE_92_CONTROL_URL}/health")
            if response.status_code == 200:
                node_92_status = "healthy"
    except:
        node_92_status = "unhealthy"
    
    return {
        "status": "healthy",
        "version": "4.0.0",
        "name": "Galaxy Gateway",
        "modules": {
            "nlu": nlu is not None,
            "aip_protocol": aip_protocol is not None,
            "multimodal_transfer": multimodal_transfer is not None
        },
        "nodes": {
            "node_90_vision": node_90_status,
            "node_91_agent": node_91_status,
            "node_92_control": node_92_status
        },
        "timestamp": datetime.now().isoformat()
    }

# ============================================================================
# API 端点 - 命令执行
# ============================================================================

@app.post("/execute_command")
async def execute_command(request: CommandRequest) -> Dict[str, Any]:
    """执行命令（基础版，不使用视觉）"""
    
    # 1. NLU 理解
    if nlu:
        nlu_result = nlu.understand(request.command, request.context)
    else:
        nlu_result = {"intent": "unknown", "entities": []}
    
    # 2. 调用 Node_91_MultimodalAgent
    result = await call_node(NODE_91_AGENT_URL, "/execute_command", {
        "command": request.command,
        "device_id": request.device_id,
        "platform": request.platform,
        "context": request.context
    })
    
    return {
        "success": result.get("success", False),
        "command": request.command,
        "nlu_result": nlu_result,
        "execution_result": result
    }

@app.post("/execute_vision_command")
async def execute_vision_command(request: VisionCommandRequest) -> Dict[str, Any]:
    """执行视觉命令（完整版，使用视觉理解）"""
    
    # 1. NLU 理解
    if nlu:
        nlu_result = nlu.understand(request.command, None)
    else:
        nlu_result = {"intent": "unknown", "entities": []}
    
    # 2. 截取屏幕
    screenshot_result = await call_node(NODE_90_VISION_URL, "/capture_screen", {
        "device_id": request.device_id,
        "platform": request.platform
    })
    
    if not screenshot_result.get("success"):
        return {
            "success": False,
            "error": "Failed to capture screen",
            "details": screenshot_result
        }
    
    # 3. 分析屏幕
    analysis_result = await call_node(NODE_90_VISION_URL, "/analyze_screen", {
        "query": f"用户想要：{request.command}。请分析屏幕上的相关元素。",
        "image_base64": screenshot_result.get("image")
    })
    
    # 4. 执行命令
    execution_result = await call_node(NODE_91_AGENT_URL, "/execute_command", {
        "command": request.command,
        "device_id": request.device_id,
        "platform": request.platform,
        "context": {
            "nlu": nlu_result,
            "screen_analysis": analysis_result
        }
    })
    
    return {
        "success": execution_result.get("success", False),
        "command": request.command,
        "nlu_result": nlu_result,
        "screen_analysis": analysis_result,
        "execution_result": execution_result
    }

# ============================================================================
# API 端点 - 视觉功能
# ============================================================================

@app.post("/capture_screen")
async def capture_screen(device_id: Optional[str] = None, platform: str = "windows") -> Dict[str, Any]:
    """截取屏幕"""
    result = await call_node(NODE_90_VISION_URL, "/capture_screen", {
        "device_id": device_id,
        "platform": platform
    })
    return result

@app.post("/find_element")
async def find_element(description: str, device_id: Optional[str] = None, platform: str = "windows") -> Dict[str, Any]:
    """查找元素"""
    result = await call_node(NODE_90_VISION_URL, "/find_element", {
        "description": description,
        "method": "auto",
        "confidence": 0.8
    })
    return result

@app.post("/analyze_screen")
async def analyze_screen(query: str, device_id: Optional[str] = None, platform: str = "windows") -> Dict[str, Any]:
    """分析屏幕"""
    result = await call_node(NODE_90_VISION_URL, "/analyze_screen", {
        "query": query
    })
    return result

# ============================================================================
# API 端点 - 操控功能
# ============================================================================

@app.post("/click")
async def click(x: int, y: int, device_id: Optional[str] = None, platform: str = "windows") -> Dict[str, Any]:
    """点击"""
    result = await call_node(NODE_92_CONTROL_URL, "/click", {
        "device_id": device_id,
        "platform": platform,
        "x": x,
        "y": y
    })
    return result

@app.post("/input")
async def input_text(text: str, device_id: Optional[str] = None, platform: str = "windows") -> Dict[str, Any]:
    """输入"""
    result = await call_node(NODE_92_CONTROL_URL, "/input", {
        "device_id": device_id,
        "platform": platform,
        "text": text
    })
    return result

@app.post("/scroll")
async def scroll(amount: int, device_id: Optional[str] = None, platform: str = "windows") -> Dict[str, Any]:
    """滚动"""
    result = await call_node(NODE_92_CONTROL_URL, "/scroll", {
        "device_id": device_id,
        "platform": platform,
        "amount": amount
    })
    return result

# ============================================================================
# WebSocket 端点
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接"""
    await websocket.accept()
    
    try:
        while True:
            # 接收消息
            data = await websocket.receive_json()
            
            # 处理消息
            command = data.get("command", "")
            device_id = data.get("device_id")
            platform = data.get("platform", "windows")
            
            # 执行命令
            result = await execute_vision_command(VisionCommandRequest(
                command=command,
                device_id=device_id,
                platform=platform,
                use_vision=True
            ))
            
            # 发送结果
            await websocket.send_json(result)
    
    except WebSocketDisconnect:
        print("WebSocket disconnected")

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
