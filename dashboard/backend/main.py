"""
Galaxy Dashboard 后端 - 集成动态 Agent 工厂
==========================================

智能体可以：
- 根据任务复杂度动态选择 LLM
- 创建和管理 Agent
- 使用孪生模型监控
- 解耦和耦合

版本: v2.3.22
"""

import os
import sys
import json
import asyncio
import logging
import httpx
from datetime import datetime
from typing import Dict, List, Optional, Any
import re

# 添加项目路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

# 导入动态 Agent 工厂
try:
    from enhancements.agent_factory.dynamic_factory import (
        DynamicAgentFactory, TaskComplexity, agent_factory
    )
    AGENT_FACTORY_AVAILABLE = True
except ImportError:
    AGENT_FACTORY_AVAILABLE = False
    agent_factory = None

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger("Galaxy")

# 创建应用
app = FastAPI(title="Galaxy Dashboard", version="2.3.22")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "public")

# ============================================================================
# 节点服务地址
# ============================================================================

NODE_SERVICES = {
    "transformer": os.getenv("NODE_50_URL", "http://localhost:8050"),
    "knowledge_base": os.getenv("NODE_72_URL", "http://localhost:8072"),
    "autonomous_learning": os.getenv("NODE_70_URL", "http://localhost:8070"),
    "orchestrator": os.getenv("NODE_110_URL", "http://localhost:8110"),
    "multi_device": os.getenv("NODE_71_URL", "http://localhost:8071"),
    "node_factory": os.getenv("NODE_118_URL", "http://localhost:8118"),
}

# ============================================================================
# 状态存储
# ============================================================================

devices: Dict[str, Dict] = {}
agents: List[Dict] = []
tasks: List[Dict] = []
active_websockets: List[WebSocket] = []

# ============================================================================
# 静态文件路由
# ============================================================================

@app.get("/")
async def root():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "Galaxy Dashboard API", "version": "2.3.22"}

# ============================================================================
# 智能体对话 - 集成动态 Agent 工厂
# ============================================================================

@app.post("/api/v1/chat")
async def chat(request: dict):
    """
    智能体对话 - 动态分配 Agent
    
    流程:
    1. 理解用户意图
    2. 评估任务复杂度
    3. 动态创建 Agent（选择合适的 LLM）
    4. 执行任务
    5. 返回结果
    """
    message = request.get("message", "")
    device_id = request.get("device_id", "")
    
    logger.info(f"Chat: {message[:50]}...")
    
    message_lower = message.lower()
    
    # =========================================================================
    # 1. 设备控制操作
    # =========================================================================
    
    if any(kw in message_lower for kw in ["打开", "启动", "运行", "open", "launch"]):
        app_name = extract_app_name(message)
        if app_name:
            # 低复杂度任务，使用快速 LLM
            if AGENT_FACTORY_AVAILABLE and agent_factory:
                agent = await agent_factory.create_agent(
                    task=f"打开应用: {app_name}",
                    device_id=device_id,
                    complexity=TaskComplexity.LOW
                )
                result = await agent_factory.execute_agent(agent.agent_id)
                return JSONResponse({
                    "response": f"✅ 已执行\n\n正在为你打开 {app_name}...\n\nAgent: {agent.name}\nLLM: {agent.llm_config.provider}",
                    "agent": {"id": agent.agent_id, "llm": agent.llm_config.provider},
                    "timestamp": datetime.now().isoformat()
                })
            
            return JSONResponse({
                "response": f"✅ 已执行\n\n正在为你打开 {app_name}...",
                "timestamp": datetime.now().isoformat()
            })
    
    # =========================================================================
    # 2. 复杂分析任务
    # =========================================================================
    
    if any(kw in message_lower for kw in ["分析", "理解", "推理", "规划", "编程", "代码"]):
        if AGENT_FACTORY_AVAILABLE and agent_factory:
            # 高复杂度任务，使用高质量 LLM
            agent = await agent_factory.create_agent(
                task=message,
                device_id=device_id,
                complexity=TaskComplexity.HIGH
            )
            result = await agent_factory.execute_agent(agent.agent_id)
            
            return JSONResponse({
                "response": f"🤖 Agent 已处理\n\n{result.get('result', '处理完成')}\n\nAgent: {agent.name}\nLLM: {agent.llm_config.provider}\n复杂度: {agent.complexity.value}",
                "agent": {"id": agent.agent_id, "llm": agent.llm_config.provider},
                "timestamp": datetime.now().isoformat()
            })
    
    # =========================================================================
    # 3. Agent 管理命令
    # =========================================================================
    
    if "agent" in message_lower:
        if any(kw in message_lower for kw in ["列表", "状态", "查看"]):
            if AGENT_FACTORY_AVAILABLE and agent_factory:
                agents_list = agent_factory.list_agents()
                response = f"🤖 Agent 列表\n\n共 {len(agents_list)} 个 Agent\n\n"
                for a in agents_list:
                    response += f"• {a['name']} - {a['state']} - {a['llm_provider']}\n"
                return JSONResponse({"response": response})
        
        if any(kw in message_lower for kw in ["创建", "新建"]):
            if AGENT_FACTORY_AVAILABLE and agent_factory:
                agent = await agent_factory.create_agent(task="用户创建的 Agent")
                return JSONResponse({
                    "response": f"✅ Agent 创建成功\n\n名称: {agent.name}\nID: {agent.agent_id}\nLLM: {agent.llm_config.provider}"
                })
    
    # =========================================================================
    # 4. LLM 提供商管理
    # =========================================================================
    
    if any(kw in message_lower for kw in ["llm", "模型", "提供商"]):
        if AGENT_FACTORY_AVAILABLE and agent_factory:
            providers = agent_factory.list_llm_providers()
            response = "📋 LLM 提供商\n\n"
            for p in providers:
                status = "✅" if p["available"] else "❌"
                response += f"{status} {p['provider']}: {p['model']}\n"
                response += f"   速度: {p['speed_score']}/10 | 质量: {p['quality_score']}/10\n"
                response += f"   能力: {', '.join(p['capabilities'])}\n\n"
            return JSONResponse({"response": response})
    
    # =========================================================================
    # 5. 孪生模型管理
    # =========================================================================
    
    if any(kw in message_lower for kw in ["孪生", "twin"]):
        if any(kw in message_lower for kw in ["解耦", "decouple"]):
            if AGENT_FACTORY_AVAILABLE and agent_factory:
                # 解耦最后一个 Agent 的孪生
                if agent_factory.agents:
                    last_agent_id = list(agent_factory.agents.keys())[-1]
                    agent_factory.decouple_twin(last_agent_id)
                    return JSONResponse({"response": f"✅ 已解耦 Agent {last_agent_id} 的孪生模型"})
        
        if any(kw in message_lower for kw in ["耦合", "couple"]):
            if AGENT_FACTORY_AVAILABLE and agent_factory:
                if agent_factory.agents:
                    last_agent_id = list(agent_factory.agents.keys())[-1]
                    agent_factory.couple_twin(last_agent_id)
                    return JSONResponse({"response": f"✅ 已耦合 Agent {last_agent_id} 的孪生模型"})
        
        # 显示孪生状态
        if AGENT_FACTORY_AVAILABLE and agent_factory:
            twins = agent_factory.twins
            response = f"🔄 孪生模型状态\n\n共 {len(twins)} 个孪生\n\n"
            for t in twins.values():
                response += f"• {t.twin_id}\n"
                response += f"  Agent: {t.agent_id}\n"
                response += f"  耦合模式: {t.coupling_mode}\n"
                response += f"  历史记录: {len(t.behavior_history)} 条\n\n"
            return JSONResponse({"response": response})
    
    # =========================================================================
    # 6. 系统状态
    # =========================================================================
    
    if any(kw in message_lower for kw in ["系统状态", "状态", "status"]):
        response = """🖥️ 系统状态

Galaxy - L4 级自主性智能系统
版本: v2.3.22

核心能力:
✅ AI 驱动 - 多 LLM 提供商支持
✅ 动态 Agent 工厂 - 根据任务复杂度分配
✅ 孪生模型 - 状态同步和解耦
✅ 跨设备控制 - 手机、平板、电脑

"""
        if AGENT_FACTORY_AVAILABLE and agent_factory:
            response += f"Agent 数量: {len(agent_factory.agents)}\n"
            response += f"孪生数量: {len(agent_factory.twins)}\n"
            response += f"LLM 提供商: {len(agent_factory.llm_providers)}\n"
        
        return JSONResponse({"response": response})
    
    # =========================================================================
    # 7. 帮助
    # =========================================================================
    
    if any(kw in message_lower for kw in ["帮助", "help"]):
        response = """📖 使用帮助

Galaxy 智能体会根据任务复杂度自动选择合适的 LLM 和 Agent。

设备控制:
• "打开微信" - 打开应用
• "截图" - 截取屏幕

复杂任务:
• "分析这张图片" - 使用高质量 LLM
• "帮我写一段代码" - 使用编程能力强的 LLM

Agent 管理:
• "查看 Agent" - 查看 Agent 列表
• "创建 Agent" - 创建新 Agent

LLM 管理:
• "查看 LLM" - 查看可用的 LLM 提供商

孪生模型:
• "查看孪生" - 查看孪生模型状态
• "解耦孪生" - 解耦孪生模型
• "耦合孪生" - 重新耦合孪生模型

💡 系统会自动评估任务复杂度并选择最佳 LLM！"""
        return JSONResponse({"response": response})
    
    # =========================================================================
    # 8. 默认处理
    # =========================================================================
    
    # 使用 Agent 工厂处理
    if AGENT_FACTORY_AVAILABLE and agent_factory:
        agent = await agent_factory.create_agent(task=message, device_id=device_id)
        result = await agent_factory.execute_agent(agent.agent_id)
        
        return JSONResponse({
            "response": f"{result.get('result', '处理完成')}\n\n[使用 {agent.llm_config.provider} 处理]",
            "agent": {"id": agent.agent_id, "llm": agent.llm_config.provider},
            "timestamp": datetime.now().isoformat()
        })
    
    return JSONResponse({
        "response": f"收到: {message}\n\n正在处理...",
        "timestamp": datetime.now().isoformat()
    })


def extract_app_name(message: str) -> Optional[str]:
    """提取应用名称"""
    apps = {
        "微信": ["微信", "wechat"],
        "淘宝": ["淘宝", "taobao"],
        "抖音": ["抖音", "douyin"],
        "QQ": ["qq", "QQ"],
        "支付宝": ["支付宝", "alipay"],
    }
    
    message_lower = message.lower()
    for app_name, keywords in apps.items():
        for kw in keywords:
            if kw in message_lower:
                return app_name
    return None


# ============================================================================
# Agent API
# ============================================================================

@app.get("/api/v1/agents")
async def list_agents():
    """列出所有 Agent"""
    if AGENT_FACTORY_AVAILABLE and agent_factory:
        return {"agents": agent_factory.list_agents()}
    return {"agents": []}

@app.get("/api/v1/llm/providers")
async def list_llm_providers():
    """列出 LLM 提供商"""
    if AGENT_FACTORY_AVAILABLE and agent_factory:
        return {"providers": agent_factory.list_llm_providers()}
    return {"providers": []}

# ============================================================================
# 设备管理 API
# ============================================================================

@app.get("/api/v1/devices")
async def list_devices():
    return {"devices": list(devices.values()), "total": len(devices)}

@app.post("/api/v1/devices/register")
async def register_device(request: dict):
    device = {
        "id": request.get("device_id", ""),
        "type": request.get("device_type", "android"),
        "name": request.get("device_name", "Device"),
        "status": "online",
        "registered_at": datetime.now().isoformat()
    }
    devices[device["id"]] = device
    return {"status": "success", "device": device}

# ============================================================================
# WebSocket
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
                elif message.get("type") == "chat":
                    result = await chat({"message": message.get("content", "")})
                    await websocket.send_json({
                        "type": "chat_response",
                        "content": result.get("response", "")
                    })
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        active_websockets.remove(websocket)

# ============================================================================
# 启动事件
# ============================================================================

@app.on_event("startup")
async def startup_event():
    logger.info("=" * 60)
    logger.info("Galaxy Dashboard v2.3.22")
    logger.info("=" * 60)
    if AGENT_FACTORY_AVAILABLE:
        logger.info("✅ 动态 Agent 工厂已启用")
        logger.info(f"   LLM 提供商: {len(agent_factory.llm_providers)} 个")
    else:
        logger.info("⚠️ 动态 Agent 工厂未启用")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
