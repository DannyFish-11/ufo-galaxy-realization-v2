"""
Node 91: MultimodalAgent - 多模态 Agent（推理和规划）

功能：
1. 结合视觉和语言理解
2. 推理和规划操作步骤
3. 执行复杂的视觉操控任务
4. 支持多轮对话和上下文管理

版本：1.0.0
日期：2026-01-22
作者：Manus AI
"""

import os
import asyncio
import httpx
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Node 91 - MultimodalAgent", version="1.0.0")
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
NODE_50_NLU_URL = os.getenv("NODE_50_NLU_URL", "http://localhost:8050")
NODE_90_VISION_URL = os.getenv("NODE_90_VISION_URL", "http://localhost:8090")
NODE_92_CONTROL_URL = os.getenv("NODE_92_CONTROL_URL", "http://localhost:8092")

# 多模态 LLM
llm_client = None
try:
    from google import genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if GEMINI_API_KEY:
        llm_client = genai.Client(api_key=GEMINI_API_KEY)
except ImportError:
    pass

# ============================================================================
# 数据模型
# ============================================================================

class ExecuteCommandRequest(BaseModel):
    """执行命令"""
    command: str
    device_id: Optional[str] = None
    platform: str = "windows"
    context: Optional[Dict[str, Any]] = None

class PlanActionsRequest(BaseModel):
    """规划操作"""
    intent: Dict[str, Any]
    visual_context: Dict[str, Any]

class Action(BaseModel):
    """操作"""
    type: str  # click, input, scroll, press_key, etc.
    target: Optional[str] = None
    parameters: Dict[str, Any] = {}
    description: str = ""

# ============================================================================
# 辅助函数
# ============================================================================

async def call_node(url: str, endpoint: str, data: dict) -> dict:
    """调用其他节点"""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{url}{endpoint}", json=data)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# NLU 理解
# ============================================================================

async def understand_command(command: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """理解命令（通过 Node_50 NLU）"""
    # 尝试调用 Node_50_Transformer (NLU)
    try:
        result = await call_node(NODE_50_NLU_URL, "/understand", {
            "text": command,
            "context": context or {}
        })
        
        if result.get("success"):
            # Node_50 成功返回
            return result.get("intent", {})
    except Exception as e:
        print(f"Failed to call Node_50: {e}")
    
    # 降级方案：使用简单的规则匹配
    intent = {
        "command": command,
        "action": "unknown",
        "target": None,
        "parameters": {}
    }
    
    # 简单的规则匹配
    if "打开" in command or "open" in command.lower():
        intent["action"] = "open_app"
        # 提取应用名称
        for app in ["微信", "QQ", "VSCode", "Chrome", "记事本"]:
            if app in command:
                intent["target"] = app
                break
    
    elif "点击" in command or "click" in command.lower():
        intent["action"] = "click"
        # 提取目标
        parts = command.split("点击")
        if len(parts) > 1:
            intent["target"] = parts[1].strip()
    
    elif "输入" in command or "type" in command.lower():
        intent["action"] = "input"
        # 提取文本
        parts = command.split("输入")
        if len(parts) > 1:
            intent["parameters"]["text"] = parts[1].strip()
    
    elif "滚动" in command or "scroll" in command.lower():
        intent["action"] = "scroll"
        if "向下" in command or "down" in command.lower():
            intent["parameters"]["direction"] = "down"
        elif "向上" in command or "up" in command.lower():
            intent["parameters"]["direction"] = "up"
    
    return intent

# ============================================================================
# 视觉理解
# ============================================================================

async def analyze_screen(query: str, device_id: Optional[str] = None) -> Dict[str, Any]:
    """分析屏幕"""
    result = await call_node(NODE_90_VISION_URL, "/analyze_screen", {
        "query": query
    })
    return result

async def find_element(description: str, device_id: Optional[str] = None) -> Dict[str, Any]:
    """查找元素"""
    result = await call_node(NODE_90_VISION_URL, "/find_element", {
        "description": description,
        "method": "auto",
        "confidence": 0.8
    })
    return result

# ============================================================================
# 推理和规划
# ============================================================================

async def plan_actions(intent: Dict[str, Any], visual_context: Optional[Dict[str, Any]] = None) -> List[Action]:
    """规划操作步骤"""
    actions = []
    
    action_type = intent.get("action")
    target = intent.get("target")
    parameters = intent.get("parameters", {})
    
    if action_type == "click":
        # 规划点击操作
        if target:
            # 需要先查找元素
            actions.append(Action(
                type="find_element",
                target=target,
                description=f"查找 {target}"
            ))
            actions.append(Action(
                type="click",
                target=target,
                description=f"点击 {target}"
            ))
    
    elif action_type == "input":
        # 规划输入操作
        text = parameters.get("text", "")
        actions.append(Action(
            type="input",
            parameters={"text": text},
            description=f"输入 {text}"
        ))
    
    elif action_type == "scroll":
        # 规划滚动操作
        direction = parameters.get("direction", "down")
        actions.append(Action(
            type="scroll",
            parameters={"direction": direction},
            description=f"向{direction}滚动"
        ))
    
    elif action_type == "open_app":
        # 规划打开应用
        if target:
            # 1. 查找应用图标
            actions.append(Action(
                type="find_element",
                target=target,
                description=f"查找 {target} 图标"
            ))
            # 2. 点击打开
            actions.append(Action(
                type="click",
                target=target,
                description=f"打开 {target}"
            ))
    
    return actions

# ============================================================================
# 执行操作
# ============================================================================

async def execute_action(action: Action, device_id: Optional[str] = None, platform: str = "windows") -> Dict[str, Any]:
    """执行单个操作"""
    
    if action.type == "find_element":
        # 查找元素
        result = await find_element(action.target, device_id)
        return result
    
    elif action.type == "click":
        # 点击
        # 先查找元素
        find_result = await find_element(action.target, device_id)
        
        if find_result.get("found"):
            position = find_result["position"]
            x = position["x"]
            y = position["y"]
            
            # 执行点击
            result = await call_node(NODE_92_CONTROL_URL, "/click", {
                "device_id": device_id,
                "platform": platform,
                "x": x,
                "y": y
            })
            return result
        else:
            return {"success": False, "error": f"Element not found: {action.target}"}
    
    elif action.type == "input":
        # 输入
        text = action.parameters.get("text", "")
        result = await call_node(NODE_92_CONTROL_URL, "/input", {
            "device_id": device_id,
            "platform": platform,
            "text": text
        })
        return result
    
    elif action.type == "scroll":
        # 滚动
        direction = action.parameters.get("direction", "down")
        amount = 100 if direction == "down" else -100
        result = await call_node(NODE_92_CONTROL_URL, "/scroll", {
            "device_id": device_id,
            "platform": platform,
            "amount": amount
        })
        return result
    
    else:
        return {"success": False, "error": f"Unknown action type: {action.type}"}

async def execute_actions(actions: List[Action], device_id: Optional[str] = None, platform: str = "windows") -> List[Dict[str, Any]]:
    """执行多个操作"""
    results = []
    
    for action in actions:
        result = await execute_action(action, device_id, platform)
        results.append({
            "action": action.dict(),
            "result": result
        })
        
        # 如果失败，停止执行
        if not result.get("success"):
            break
        
        # 等待一下
        await asyncio.sleep(0.5)
    
    return results

# ============================================================================
# API 端点
# ============================================================================

@app.post("/execute_command")
async def execute_command(request: ExecuteCommandRequest) -> Dict[str, Any]:
    """执行命令（完整流程）"""
    
    # 1. 理解命令
    intent = await understand_command(request.command, request.context)
    
    # 2. 分析屏幕（可选）
    visual_context = None
    if intent.get("action") in ["click", "open_app"]:
        visual_result = await analyze_screen(
            f"用户想要：{request.command}。请分析屏幕上的相关元素。",
            request.device_id
        )
        if visual_result.get("success"):
            visual_context = visual_result
    
    # 3. 规划操作
    actions = await plan_actions(intent, visual_context)
    
    # 4. 执行操作
    execution_results = await execute_actions(actions, request.device_id, request.platform)
    
    # 5. 返回结果
    return {
        "success": all(r["result"].get("success") for r in execution_results),
        "command": request.command,
        "intent": intent,
        "actions": [a.dict() for a in actions],
        "execution_results": execution_results
    }

@app.post("/plan_actions")
async def plan_actions_endpoint(request: PlanActionsRequest) -> Dict[str, Any]:
    """规划操作"""
    actions = await plan_actions(request.intent, request.visual_context)
    return {
        "success": True,
        "actions": [a.dict() for a in actions]
    }

# ============================================================================
# 健康检查
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    # 检查依赖节点
    node_90_status = "unknown"
    node_92_status = "unknown"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{NODE_90_VISION_URL}/health")
            if response.status_code == 200:
                node_90_status = "healthy"
    except Exception:
        node_90_status = "unhealthy"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{NODE_92_CONTROL_URL}/health")
            if response.status_code == 200:
                node_92_status = "healthy"
    except Exception:
        node_92_status = "unhealthy"
    
    return {
        "status": "healthy" if (node_90_status == "healthy" and node_92_status == "healthy") else "degraded",
        "node_id": "91",
        "name": "MultimodalAgent",
        "version": "1.0.0",
        "dependencies": {
            "node_90_vision": node_90_status,
            "node_92_control": node_92_status,
            "llm": llm_client is not None
        },
        "timestamp": datetime.now().isoformat()
    }

# ============================================================================
# MCP 调用接口
# ============================================================================

@app.post("/mcp/call")
async def mcp_call(request: dict) -> Dict[str, Any]:
    """MCP 调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if tool == "execute_command":
        return await execute_command(ExecuteCommandRequest(**params))
    elif tool == "plan_actions":
        return await plan_actions_endpoint(PlanActionsRequest(**params))
    else:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8091)
