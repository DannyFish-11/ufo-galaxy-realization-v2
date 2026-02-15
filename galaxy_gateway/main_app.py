"""
Galaxy - 统一主应用
整合所有服务：配置、记忆、路由、设备管理
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
    description="L4 级自主性智能系统",
    version="2.1.2"
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
# 导入并注册子路由
# ============================================================================

# 配置服务
from galaxy_gateway.config_service import app as config_app
app.mount("/config", config_app)

# 记忆服务
try:
    from galaxy_gateway.memory_service import router as memory_router
    app.include_router(memory_router)
except ImportError as e:
    logger.warning(f"Memory service not loaded: {e}")

# AI 路由服务
try:
    from galaxy_gateway.router_service import router as ai_router_router
from galaxy_gateway.api_keys_service import router as api_keys_router
    app.include_router(api_keys_router)
app.include_router(ai_router_router)
except ImportError as e:
    logger.warning(f"AI router service not loaded: {e}")

# 设备管理服务
try:
    from galaxy_gateway.device_manager_service import app as device_app
    app.mount("/device", device_app)
except ImportError as e:
    logger.warning(f"Device manager service not loaded: {e}")

# ============================================================================
# 静态文件
# ============================================================================

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ============================================================================
# 主页面路由
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """主页面 - 控制面板"""
    index_path = STATIC_DIR / "dashboard.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding='utf-8'))
    return {"message": "Galaxy L4 AI System", "version": "2.1.2"}

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

@app.get("/api-keys")
    async def api_keys_page():
        """API Key 管理"""
        static_path = STATIC_DIR / "api_keys.html"
        if static_path.exists():
            return HTMLResponse(content=static_path.read_text(encoding='utf-8'))
        return {"error": "API Keys page not found"}

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

# ============================================================================
# API 端点
# ============================================================================

@app.get("/api/status")
async def get_status():
    """获取系统状态"""
    return {
        "status": "running",
        "version": "2.1.2",
        "services": {
            "config": True,
            "memory": True,
            "router": True,
            "devices": True
        }
    }

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy"}

# ============================================================================
# 启动函数
# ============================================================================

def run_server(host: str = "0.0.0.0", port: int = 8080):
    """运行服务器"""
    import uvicorn
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    run_server()
