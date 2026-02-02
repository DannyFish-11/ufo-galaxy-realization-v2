"""
UFO³ Galaxy Gateway - 主服务 v2.0（集成增强 NLU）

功能：
1. WebSocket 服务器 - 接收来自各节点的连接
2. 设备注册和管理 - 管理所有设备的注册和状态
3. 自然语言理解 - 使用增强的 NLU 引擎理解用户指令
4. 任务路由和调度 - 将任务路由到目标设备并管理执行
5. 跨设备协同 - 支持跨设备的复杂任务
6. HTTP API - 提供 REST API 接口

作者：Manus AI
日期：2026-01-22
版本：2.0
"""

import asyncio
import json
import os
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

# 导入增强的 NLU 组件
from enhanced_nlu_v2 import (
    DeviceRegistry, Device, DeviceType, DeviceStatus,
    EnhancedNLUEngineV2, LLMClient, ContextManager
)
from task_router import TaskRouter, ResultAggregator
from task_decomposer import TaskDecomposer, CrossDeviceCoordinator, IntelligentTaskPlanner

# ============================================================================
# FastAPI 应用
# ============================================================================

app = FastAPI(
    title="UFO³ Galaxy Gateway v2.0",
    description="增强版 Galaxy Gateway，支持多设备智能操控",
    version="2.0.0"
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# 全局状态
# ============================================================================

class GatewayState:
    """Gateway 全局状态"""
    
    def __init__(self):
        # 设备管理
        self.device_registry = DeviceRegistry()
        
        # LLM 客户端（默认使用 Ollama）
        self.llm_client = LLMClient(
            provider=os.getenv("LLM_PROVIDER", "ollama"),
            api_base=os.getenv("LLM_API_BASE"),
            api_key=os.getenv("LLM_API_KEY")
        )
        
        # NLU 引擎
        self.nlu_engine = EnhancedNLUEngineV2(
            device_registry=self.device_registry,
            llm_client=self.llm_client,
            use_llm=True,
            confidence_threshold=0.7
        )
        
        # 任务路由器
        self.task_router = TaskRouter(self.device_registry)
        
        # 结果聚合器
        self.result_aggregator = ResultAggregator()
        
        # 任务分解器
        self.task_decomposer = TaskDecomposer(self.device_registry)
        
        # 跨设备协同管理器
        self.cross_device_coordinator = CrossDeviceCoordinator(self.device_registry)
        
        # 智能任务规划器
        self.intelligent_planner = IntelligentTaskPlanner(
            self.device_registry,
            self.llm_client
        )
        
        # WebSocket 连接管理
        self.active_connections: Dict[str, WebSocket] = {}
        
        # 统计信息
        self.stats = {
            "total_requests": 0,
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "start_time": datetime.now()
        }

# 全局状态实例
gateway_state = GatewayState()

# ============================================================================
# Pydantic 模型
# ============================================================================

class CommandRequest(BaseModel):
    """命令请求"""
    user_input: str
    session_id: str = "default"
    user_id: str = "default"
    source_device_id: Optional[str] = None

class DeviceRegistrationRequest(BaseModel):
    """设备注册请求"""
    device_id: str
    device_name: str
    device_type: str
    aliases: List[str] = []
    capabilities: List[str] = []
    ip_address: str

class TaskExecutionRequest(BaseModel):
    """任务执行请求"""
    tasks: List[Dict[str, Any]]

# ============================================================================
# HTTP API 端点
# ============================================================================

@app.get("/")
async def root():
    """根端点"""
    return {
        "service": "UFO³ Galaxy Gateway",
        "version": "2.0.0",
        "status": "running",
        "features": [
            "Enhanced NLU with LLM",
            "Multi-device control",
            "Complex task decomposition",
            "Cross-device coordination",
            "Context management"
        ]
    }

@app.get("/api/status")
async def get_status():
    """获取 Gateway 状态"""
    uptime = (datetime.now() - gateway_state.stats["start_time"]).total_seconds()
    
    return {
        "status": "online",
        "uptime_seconds": uptime,
        "devices": {
            "total": len(gateway_state.device_registry.devices),
            "online": len(gateway_state.device_registry.get_online_devices())
        },
        "connections": len(gateway_state.active_connections),
        "stats": gateway_state.stats
    }

@app.get("/api/devices")
async def list_devices():
    """列出所有设备"""
    devices = []
    for device in gateway_state.device_registry.devices.values():
        devices.append({
            "device_id": device.device_id,
            "device_name": device.device_name,
            "device_type": device.device_type.value,
            "status": device.status.value,
            "aliases": device.aliases,
            "capabilities": device.capabilities,
            "ip_address": device.ip_address,
            "last_seen": device.last_seen.isoformat()
        })
    return {"devices": devices}

@app.post("/api/devices/register")
async def register_device(request: DeviceRegistrationRequest):
    """注册设备"""
    device = Device(
        device_id=request.device_id,
        device_name=request.device_name,
        device_type=DeviceType(request.device_type),
        status=DeviceStatus.ONLINE,
        aliases=request.aliases,
        capabilities=request.capabilities,
        ip_address=request.ip_address,
        last_seen=datetime.now()
    )
    
    gateway_state.device_registry.register_device(device)
    
    return {
        "success": True,
        "message": f"设备 {request.device_name} 注册成功",
        "device_id": request.device_id
    }

@app.post("/api/command")
async def execute_command(request: CommandRequest):
    """执行用户命令（主要 API）"""
    gateway_state.stats["total_requests"] += 1
    
    try:
        # 1. 使用 NLU 理解用户输入
        nlu_result = await gateway_state.nlu_engine.understand(
            user_input=request.user_input,
            session_id=request.session_id,
            user_id=request.user_id
        )
        
        # 2. 检查是否需要澄清
        if nlu_result.clarifications:
            return {
                "success": False,
                "need_clarification": True,
                "clarifications": nlu_result.clarifications,
                "confidence": nlu_result.confidence
            }
        
        # 3. 执行任务
        if nlu_result.tasks:
            gateway_state.stats["total_tasks"] += len(nlu_result.tasks)
            
            # 优化任务放置
            optimized_tasks = gateway_state.cross_device_coordinator.optimize_task_placement(
                nlu_result.tasks
            )
            
            # 执行任务
            results = await gateway_state.task_router.execute_tasks(optimized_tasks)
            
            # 聚合结果
            summary = gateway_state.result_aggregator.aggregate(results)
            
            # 更新统计
            gateway_state.stats["successful_tasks"] += summary["summary"]["completed"]
            gateway_state.stats["failed_tasks"] += summary["summary"]["failed"]
            
            return {
                "success": True,
                "nlu": {
                    "confidence": nlu_result.confidence,
                    "method": nlu_result.method,
                    "processing_time": nlu_result.processing_time,
                    "context_used": nlu_result.context_used
                },
                "execution": summary
            }
        else:
            return {
                "success": False,
                "error": "无法理解用户输入",
                "confidence": nlu_result.confidence
            }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/tasks/execute")
async def execute_tasks(request: TaskExecutionRequest):
    """直接执行任务列表（高级 API）"""
    from enhanced_nlu_v2 import Task, IntentType
    
    try:
        # 解析任务
        tasks = []
        for task_data in request.tasks:
            task = Task(
                task_id=task_data["task_id"],
                device_id=task_data["device_id"],
                intent_type=IntentType(task_data["intent_type"]),
                action=task_data["action"],
                target=task_data.get("target"),
                parameters=task_data.get("parameters", {}),
                depends_on=task_data.get("depends_on", []),
                confidence=task_data.get("confidence", 0.9),
                estimated_duration=task_data.get("estimated_duration", 2.0)
            )
            tasks.append(task)
        
        # 执行任务
        results = await gateway_state.task_router.execute_tasks(tasks)
        
        # 聚合结果
        summary = gateway_state.result_aggregator.aggregate(results)
        
        return {
            "success": True,
            "execution": summary
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

# ============================================================================
# WebSocket 端点
# ============================================================================

@app.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    """WebSocket 端点 - 设备连接"""
    await websocket.accept()
    gateway_state.active_connections[device_id] = websocket
    
    # 更新设备状态为在线
    gateway_state.device_registry.update_device_status(device_id, DeviceStatus.ONLINE)
    
    print(f"设备 {device_id} 已连接")
    
    try:
        while True:
            # 接收消息
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # 处理消息
            if message.get("type") == "heartbeat":
                # 心跳消息
                gateway_state.device_registry.update_device_status(device_id, DeviceStatus.ONLINE)
                await websocket.send_json({"type": "heartbeat_ack"})
            
            elif message.get("type") == "task_result":
                # 任务结果
                print(f"收到设备 {device_id} 的任务结果: {message.get('task_id')}")
                # 这里可以存储结果或通知其他设备
            
            elif message.get("type") == "command":
                # 设备发送的命令（设备间互相操控）
                user_input = message.get("user_input")
                session_id = message.get("session_id", device_id)
                
                # 使用 NLU 理解并执行
                nlu_result = await gateway_state.nlu_engine.understand(
                    user_input=user_input,
                    session_id=session_id,
                    user_id=device_id
                )
                
                if nlu_result.tasks:
                    results = await gateway_state.task_router.execute_tasks(nlu_result.tasks)
                    summary = gateway_state.result_aggregator.aggregate(results)
                    
                    await websocket.send_json({
                        "type": "command_result",
                        "success": True,
                        "summary": summary
                    })
                else:
                    await websocket.send_json({
                        "type": "command_result",
                        "success": False,
                        "clarifications": nlu_result.clarifications
                    })
    
    except WebSocketDisconnect:
        print(f"设备 {device_id} 已断开连接")
        gateway_state.active_connections.pop(device_id, None)
        gateway_state.device_registry.update_device_status(device_id, DeviceStatus.OFFLINE)
    
    except Exception as e:
        print(f"WebSocket 错误: {e}")
        gateway_state.active_connections.pop(device_id, None)
        gateway_state.device_registry.update_device_status(device_id, DeviceStatus.OFFLINE)

# ============================================================================
# 测试端点
# ============================================================================

@app.post("/api/test/nlu")
async def test_nlu(request: CommandRequest):
    """测试 NLU（不执行任务）"""
    try:
        nlu_result = await gateway_state.nlu_engine.understand(
            user_input=request.user_input,
            session_id=request.session_id,
            user_id=request.user_id
        )
        
        return {
            "success": nlu_result.success,
            "confidence": nlu_result.confidence,
            "method": nlu_result.method,
            "processing_time": nlu_result.processing_time,
            "context_used": nlu_result.context_used,
            "tasks": [
                {
                    "task_id": task.task_id,
                    "device_id": task.device_id,
                    "intent_type": task.intent_type.value,
                    "action": task.action,
                    "target": task.target,
                    "parameters": task.parameters,
                    "depends_on": task.depends_on,
                    "confidence": task.confidence
                }
                for task in nlu_result.tasks
            ],
            "clarifications": nlu_result.clarifications
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

# ============================================================================
# 启动服务
# ============================================================================

def main():
    """启动 Gateway 服务"""
    print("="*80)
    print("UFO³ Galaxy Gateway v2.0")
    print("="*80)
    print(f"启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"LLM 提供商: {os.getenv('LLM_PROVIDER', 'ollama')}")
    print(f"设备数量: {len(gateway_state.device_registry.devices)}")
    print("="*80)
    
    # 启动服务
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )

if __name__ == "__main__":
    main()
