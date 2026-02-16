"""
Galaxy - 统一主应用
整合群智能核心，提供统一的交互入口
"""

import os
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)

# ============================================================================
# 创建主应用
# ============================================================================

app = FastAPI(
    title="Galaxy",
    description="L4 级群智能系统 - 一个有机的整体",
    version="2.1.10"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# 静态文件
# ============================================================================

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ============================================================================
# 导入并注册路由
# ============================================================================

# 群智能 API (核心)
try:
    from galaxy_gateway.swarm_api import router as swarm_router

# 一体化系统 API
try:
    from galaxy_gateway.integrated_api import router as integrated_router
    app.include_router(integrated_router, prefix="/api/integrated")
    logger.info("一体化系统 API 已加载")
except ImportError as e:
    logger.warning(f"Integrated API not loaded: {e}")
    app.include_router(swarm_router, prefix="/api/swarm")
    logger.info("群智能 API 已加载")
except ImportError as e:
    logger.warning(f"Swarm API not loaded: {e}")

# AI 路由服务
try:
    from galaxy_gateway.router_service import router as ai_router_router
    app.include_router(ai_router_router)
    logger.info("AI 路由服务已加载")
except ImportError as e:
    logger.warning(f"AI router service not loaded: {e}")

# API Key 管理服务
try:
    from galaxy_gateway.api_keys_service import router as api_keys_router
    app.include_router(api_keys_router)
    logger.info("API Key 服务已加载")
except ImportError as e:
    logger.warning(f"API Keys service not loaded: {e}")

# 记忆服务
try:
    from galaxy_gateway.memory_service import router as memory_router
    app.include_router(memory_router)
    logger.info("记忆服务已加载")
except ImportError as e:
    logger.warning(f"Memory service not loaded: {e}")

# 配置服务
try:
    from galaxy_gateway.config_service import app as config_app
    app.mount("/config", config_app)
    logger.info("配置服务已加载")
except ImportError as e:
    logger.warning(f"Config service not loaded: {e}")

# 设备管理服务
try:
    from galaxy_gateway.device_manager_service import app as device_app
    app.mount("/device", device_app)
    logger.info("设备管理服务已加载")
except ImportError as e:
    logger.warning(f"Device manager service not loaded: {e}")

# ============================================================================
# 主页面路由
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """主页面 - 群智能交互界面"""
    index_path = STATIC_DIR / "dashboard.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding='utf-8'))
    return {"message": "Galaxy L4 群智能系统", "version": "2.1.8"}

@app.get("/config", response_class=HTMLResponse)
async def config_page():
    """配置中心"""
    index_path = STATIC_DIR / "config.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding='utf-8'))
    return {"error": "Config page not found"}

@app.get("/memory", response_class=HTMLResponse)
async def memory_page():
    """记忆中心"""
    index_path = STATIC_DIR / "memory.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding='utf-8'))
    return {"error": "Memory page not found"}

@app.get("/router", response_class=HTMLResponse)
async def router_page():
    """AI 路由"""
    index_path = STATIC_DIR / "router.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding='utf-8'))
    return {"error": "Router page not found"}

@app.get("/devices", response_class=HTMLResponse)
async def devices_page():
    """设备管理"""
    index_path = STATIC_DIR / "device_manager.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding='utf-8'))
    return {"error": "Devices page not found"}

@app.get("/api-keys", response_class=HTMLResponse)
async def api_keys_page():
    """API Key 管理"""
    index_path = STATIC_DIR / "api_keys.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding='utf-8'))
    return {"error": "API Keys page not found"}

@app.get("/capabilities", response_class=HTMLResponse)
async def capabilities_page():
    """能力中心"""
    index_path = STATIC_DIR / "capabilities.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding='utf-8'))
    # 返回简单的 HTML
    return HTMLResponse(content="""
<!DOCTYPE html>
<html>
<head>
    <title>Galaxy - 能力中心</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-900 text-white min-h-screen">
    <div id="app" class="container mx-auto p-8">
        <h1 class="text-3xl font-bold mb-8">Galaxy 能力中心</h1>
        <div id="capabilities" class="grid grid-cols-1 md:grid-cols-3 gap-4"></div>
    </div>
    <script>
        fetch('/api/swarm/capabilities')
            .then(r => r.json())
            .then(data => {
                const container = document.getElementById('capabilities');
                data.capabilities.forEach(cap => {
                    container.innerHTML += `
                        <div class="bg-gray-800 rounded-lg p-4">
                            <h3 class="font-bold text-cyan-400">${cap.name}</h3>
                            <p class="text-gray-400 text-sm">${cap.description}</p>
                            <span class="text-xs px-2 py-1 bg-gray-700 rounded">${cap.category}</span>
                        </div>
                    `;
                });
            });
    </script>
</body>
</html>
""")

# ============================================================================
# API 端点
# ============================================================================

@app.get("/api/status")
async def get_status():
    """获取系统状态"""
    try:
        from core.swarm_core import get_swarm_core
        core = get_swarm_core()
        return core.get_status()
    except:
        return {
            "status": "running",
            "version": "2.1.8",
            "state": "active"
        }

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}

@app.get("/api/nodes/status")
async def get_nodes_status():
    """获取节点状态"""
    return {
        "online": 1,
        "total": 1,
        "nodes": [
            {"id": "master", "status": "online", "role": "coordinator"}
        ]
    }

@app.get("/api/info")
async def get_info():
    """获取系统信息"""
    return {
        "name": "Galaxy",
        "version": "2.1.8",
        "description": "L4 级群智能系统",
        "architecture": "Swarm Intelligence",
        "features": [
            "群智能核心",
            "统一交互入口",
            "能力动态发现",
            "AI 驱动决策",
            "实时学习"
        ],
        "endpoints": {
            "interact": "/api/swarm/interact",
            "chat": "/api/swarm/chat",
            "capabilities": "/api/swarm/capabilities",
            "mcp_tools": "/api/swarm/mcp/tools",
            "status": "/api/swarm/status"
        }
    }

# ============================================================================
# 启动函数
# ============================================================================

def run_server(host: str = "0.0.0.0", port: int = 8080):
    """运行服务器"""
    import uvicorn
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    run_server()
