#!/usr/bin/env python3
"""
Galaxy - 配置管理服务
提供系统配置的 API 接口
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# ============================================================================
# 配置模型
# ============================================================================

class APIKeysConfig(BaseModel):
    openai: str = ""
    deepseek: str = ""
    anthropic: str = ""
    google: str = ""
    groq: str = ""
    openrouter: str = ""

class OneAPIConfig(BaseModel):
    url: str = ""
    key: str = ""

class PriorityModelConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    weight: int = 60
    enabled: bool = True

class RouterConfig(BaseModel):
    priority1: PriorityModelConfig = PriorityModelConfig()
    priority2: PriorityModelConfig = PriorityModelConfig(provider="deepseek", model="deepseek-chat", weight=30)
    priority3: PriorityModelConfig = PriorityModelConfig(provider="groq", model="llama-3.1-70b-versatile", weight=10)
    failoverStrategy: str = "priority"
    retryCount: int = 3
    timeout: int = 30

class SystemConfig(BaseModel):
    name: str = "Galaxy"
    nodeId: str = "master"
    httpPort: int = 8080
    websocketPort: int = 8765
    logLevel: str = "INFO"
    environment: str = "production"

class DaemonConfig(BaseModel):
    autoStart: bool = True
    autoRestart: bool = True
    healthCheck: bool = True
    heartbeat: bool = True
    healthCheckInterval: int = 60
    maxRestarts: int = 5

class DatabaseConfig(BaseModel):
    redisUrl: str = "redis://localhost:6379"
    qdrantUrl: str = "http://localhost:6333"

class GalaxyConfig(BaseModel):
    apiKeys: APIKeysConfig = APIKeysConfig()
    oneapi: OneAPIConfig = OneAPIConfig()
    router: RouterConfig = RouterConfig()
    system: SystemConfig = SystemConfig()
    daemon: DaemonConfig = DaemonConfig()
    database: DatabaseConfig = DatabaseConfig()

# ============================================================================
# 配置管理器
# ============================================================================

class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_file: str = "config/galaxy_config.json"):
        self.config_file = Path(config_file)
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config = self._load_config()
    
    def _load_config(self) -> GalaxyConfig:
        """加载配置"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return GalaxyConfig(**data)
            except Exception as e:
                logger.error(f"Failed to load config: {e}")
        
        # 从环境变量加载
        config = GalaxyConfig()
        config.apiKeys.openai = os.getenv("OPENAI_API_KEY", "")
        config.apiKeys.deepseek = os.getenv("DEEPSEEK_API_KEY", "")
        config.apiKeys.anthropic = os.getenv("ANTHROPIC_API_KEY", "")
        config.apiKeys.google = os.getenv("GEMINI_API_KEY", "")
        config.apiKeys.groq = os.getenv("GROQ_API_KEY", "")
        config.oneapi.url = os.getenv("ONEAPI_URL", "")
        config.oneapi.key = os.getenv("ONEAPI_API_KEY", "")
        
        return config
    
    def save_config(self, config: GalaxyConfig):
        """保存配置"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config.model_dump(), f, indent=2, ensure_ascii=False)
            logger.info(f"Config saved to {self.config_file}")
            return True
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False
    
    def save_to_env(self, config: GalaxyConfig):
        """保存到 .env 文件"""
        env_file = Path(".env")
        
        lines = []
        lines.append("# Galaxy 系统配置")
        lines.append(f"# 更新时间: {datetime.now().isoformat()}")
        lines.append("")
        
        # API Keys
        lines.append("# ============ API Keys ============")
        if config.apiKeys.openai:
            lines.append(f"OPENAI_API_KEY={config.apiKeys.openai}")
        if config.apiKeys.deepseek:
            lines.append(f"DEEPSEEK_API_KEY={config.apiKeys.deepseek}")
        if config.apiKeys.anthropic:
            lines.append(f"ANTHROPIC_API_KEY={config.apiKeys.anthropic}")
        if config.apiKeys.google:
            lines.append(f"GEMINI_API_KEY={config.apiKeys.google}")
        if config.apiKeys.groq:
            lines.append(f"GROQ_API_KEY={config.apiKeys.groq}")
        
        # OneAPI
        lines.append("")
        lines.append("# ============ OneAPI ============")
        if config.oneapi.url:
            lines.append(f"ONEAPI_URL={config.oneapi.url}")
        if config.oneapi.key:
            lines.append(f"ONEAPI_API_KEY={config.oneapi.key}")
        
        # System
        lines.append("")
        lines.append("# ============ System ============")
        lines.append(f"GALAXY_NAME={config.system.name}")
        lines.append(f"UFO_NODE_ID={config.system.nodeId}")
        lines.append(f"WEB_UI_PORT={config.system.httpPort}")
        lines.append(f"WEBSOCKET_PORT={config.system.websocketPort}")
        lines.append(f"LOG_LEVEL={config.system.logLevel}")
        lines.append(f"ENVIRONMENT={config.system.environment}")
        
        # Router
        lines.append("")
        lines.append("# ============ LLM Router ============")
        lines.append(f"LLM_PRIORITY1_PROVIDER={config.router.priority1.provider}")
        lines.append(f"LLM_PRIORITY1_MODEL={config.router.priority1.model}")
        lines.append(f"LLM_PRIORITY2_PROVIDER={config.router.priority2.provider}")
        lines.append(f"LLM_PRIORITY2_MODEL={config.router.priority2.model}")
        lines.append(f"LLM_PRIORITY3_PROVIDER={config.router.priority3.provider}")
        lines.append(f"LLM_PRIORITY3_MODEL={config.router.priority3.model}")
        lines.append(f"LLM_FAILOVER_STRATEGY={config.router.failoverStrategy}")
        
        # Database
        lines.append("")
        lines.append("# ============ Database ============")
        lines.append(f"REDIS_URL={config.database.redisUrl}")
        lines.append(f"QDRANT_URL={config.database.qdrantUrl}")
        
        # Daemon
        lines.append("")
        lines.append("# ============ Daemon ============")
        lines.append(f"AUTO_START={str(config.daemon.autoStart).lower()}")
        lines.append(f"AUTO_RESTART={str(config.daemon.autoRestart).lower()}")
        lines.append(f"HEALTH_CHECK={str(config.daemon.healthCheck).lower()}")
        
        try:
            with open(env_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            logger.info(f".env file saved")
            return True
        except Exception as e:
            logger.error(f"Failed to save .env: {e}")
            return False

# ============================================================================
# FastAPI 应用
# ============================================================================

config_manager = ConfigManager()

app = FastAPI(title="Galaxy Config Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================================
# API 端点
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def config_page():
    """配置页面"""
    static_path = Path(__file__).parent / "static" / "config.html"
    if static_path.exists():
        return HTMLResponse(content=static_path.read_text(encoding='utf-8'))
    return {"error": "Config page not found"}

@app.get("/api/config")
async def get_config():
    """获取配置"""
    return config_manager.config.model_dump()

@app.post("/api/config")
async def update_config(config: GalaxyConfig):
    """更新配置"""
    if config_manager.save_config(config):
        config_manager.config = config
        return {"success": True, "message": "配置已保存"}
    raise HTTPException(status_code=500, detail="保存配置失败")

@app.post("/api/config/save-env")
async def save_to_env(config: GalaxyConfig):
    """保存到 .env 文件"""
    if config_manager.save_to_env(config):
        return {"success": True, "message": ".env 文件已更新"}
    raise HTTPException(status_code=500, detail="保存 .env 失败")

@app.get("/api/status")
async def get_status():
    """获取系统状态"""
    return {
        "status": "running",
        "name": config_manager.config.system.name,
        "node_id": config_manager.config.system.nodeId,
        "timestamp": datetime.now().isoformat()
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
