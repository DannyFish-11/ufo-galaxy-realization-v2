"""
UFO Galaxy - System & Config Routes
=====================================

Routes:
  GET  /api/v1/system/status   - 系统完整状态
  GET  /api/v1/system/health   - 健康检查
  GET  /api/v1/system/config   - 系统配置(脱敏)
  GET  /api/config             - 前端配置
  POST /api/config/update      - 更新 API Key 配置
"""

import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from core.auth import require_auth

from core.routes._shared import (
    connection_manager,
    registered_devices,
    node_status_cache,
    task_queue,
)

logger = logging.getLogger("UFO-Galaxy.API")

# 支持的 API Key 白名单
ALLOWED_CONFIG_KEYS = {
    "OPENAI_API_KEY", "OPENAI_API_BASE",
    "GEMINI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENROUTER_API_KEY",
    "GROQ_API_KEY",
    "XAI_API_KEY",
    "ZHIPU_API_KEY",
    "ONEAPI_URL", "ONEAPI_API_KEY",
    "PERPLEXITY_API_KEY", "SONAR_API_KEY",
    "DEEPSEEK_OCR2_API_KEY",
    "OLLAMA_URL", "VLLM_URL",
}


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create system & config routes router."""
    router = APIRouter()

    @router.get("/api/v1/system/status")
    async def system_status():
        """获取系统完整状态"""
        services = service_manager.get_status() if service_manager else {}
        return JSONResponse({
            "status": "running",
            "version": "2.0.0",
            "timestamp": datetime.now().isoformat(),
            "services": services,
            "devices": {
                "registered": len(registered_devices),
                "online": len(connection_manager.active_devices),
                "list": [
                    {
                        "device_id": did,
                        "device_name": info.get("device_name", ""),
                        "device_type": info.get("device_type", ""),
                        "online": did in connection_manager.active_devices,
                        "last_seen": info.get("last_seen", "")
                    }
                    for did, info in registered_devices.items()
                ]
            },
            "nodes": {
                "total": len(node_status_cache),
                "active": sum(1 for n in node_status_cache.values() if n.get("status") == "running")
            },
            "tasks": {
                "total": len(task_queue),
                "pending": sum(1 for t in task_queue.values() if t.get("status") == "pending"),
                "running": sum(1 for t in task_queue.values() if t.get("status") == "running"),
                "completed": sum(1 for t in task_queue.values() if t.get("status") == "completed")
            }
        })

    @router.get("/api/v1/system/health")
    async def system_health():
        """健康检查端点"""
        return {"status": "healthy", "timestamp": datetime.now().isoformat()}

    @router.get("/api/v1/system/config")
    async def system_config():
        """获取系统配置（脱敏）"""
        if config:
            status = config.get_status_dict()
            return JSONResponse(status)
        return JSONResponse({"error": "config not available"})

    @router.get("/api/config")
    async def get_frontend_config(request: Request = None):
        """
        返回前端所需的非敏感配置。
        注意：敏感 Key (如 OPENAI_API_KEY) 不应直接返回，除非在受控的本地环境。
        """
        host = "localhost"
        port = "8099"
        if request:
            host = request.url.hostname or "localhost"
            port = str(request.url.port or 8099)

        def _is_configured(key_name: str) -> bool:
            val = os.getenv(key_name, "")
            return bool(val and not val.startswith("your-") and not val.startswith("sk-YOUR"))

        config_data = {
            "api_base_url": f"http://{host}:{port}",
            "ws_url": f"ws://{host}:{port}/ws",
            "status": {
                "openai": _is_configured("OPENAI_API_KEY"),
                "deepseek": _is_configured("DEEPSEEK_API_KEY"),
                "anthropic": _is_configured("ANTHROPIC_API_KEY"),
                "gemini": _is_configured("GEMINI_API_KEY"),
                "groq": _is_configured("GROQ_API_KEY"),
                "openrouter": _is_configured("OPENROUTER_API_KEY"),
                "perplexity": _is_configured("SONAR_API_KEY") or _is_configured("PERPLEXITY_API_KEY"),
                "oneapi": _is_configured("ONEAPI_API_KEY"),
                "ocr": _is_configured("DEEPSEEK_OCR2_API_KEY"),
                "ollama": bool(os.getenv("OLLAMA_URL")),
            }
        }
        return JSONResponse(config_data)

    @router.get("/api/v1/system/mcp")
    async def system_mcp():
        """列出所有 MCP Server 及其工具/资源/状态"""
        try:
            from core.mcp_loader import mcp_loader
            servers = mcp_loader.list_servers()
            return JSONResponse({"servers": servers})
        except Exception as e:
            logger.warning(f"获取 MCP 状态失败: {e}")
            return JSONResponse({"servers": [], "error": str(e)})

    @router.get("/api/v1/system/skills")
    async def system_skills():
        """列出所有已加载 Skill 及执行统计"""
        try:
            from core.skill_loader import skill_loader
            skills = skill_loader.list_skills()
            stats = skill_loader.get_stats()
            return JSONResponse({
                "skills": [s.to_dict() if hasattr(s, 'to_dict') else s for s in skills],
                "stats": stats
            })
        except Exception as e:
            logger.warning(f"获取 Skill 状态失败: {e}")
            return JSONResponse({"skills": [], "stats": {}, "error": str(e)})

    @router.post("/api/config/update")
    async def update_config(request: Request, auth: dict = Depends(require_auth)):
        """
        更新配置 - 支持所有 LLM API Key
        写入 .env 文件并即时热更新到 os.environ
        """
        data = await request.json()
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")

        try:
            # 读取现有 .env
            current_env = {}
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, val = line.split("=", 1)
                            current_env[key.strip()] = val.strip()

            # 支持两种格式:
            # 1. 直接 {KEY: VALUE} (旧格式)
            # 2. {"keys": {KEY: VALUE}} (新格式，来自 Dashboard)
            keys_data = data.get("keys", data) if isinstance(data, dict) else data

            updated_keys = []
            for key, val in keys_data.items():
                if key in ALLOWED_CONFIG_KEYS:
                    val = str(val).strip()
                    if val:
                        current_env[key] = val
                        os.environ[key] = val
                        updated_keys.append(key)
                    else:
                        current_env.pop(key, None)
                        os.environ.pop(key, None)
                        updated_keys.append(f"{key} (removed)")

            # 写回 .env
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("# UFO Galaxy - Environment Configuration\n")
                f.write(f"# Updated: {datetime.now().isoformat()}\n\n")
                for key, val in sorted(current_env.items()):
                    f.write(f"{key}={val}\n")

            # 热重载 LLM Router 以拾取新 API Key
            if updated_keys and any("API_KEY" in k or "URL" in k for k in updated_keys):
                try:
                    from core.multi_llm_router import get_llm_router
                    router = get_llm_router()
                    router._discover_providers()  # 重新发现 providers
                    logger.info(f"LLM Router 已热重载 (更新: {updated_keys})")
                except Exception as e:
                    logger.warning(f"LLM Router 热重载失败: {e}")

                # 同步刷新能力编排器
                try:
                    from core.capability_orchestrator import capability_orchestrator
                    import asyncio
                    await capability_orchestrator.reinitialize()
                    logger.info("CapabilityOrchestrator 已重新加载")
                except Exception as e:
                    logger.debug(f"CapabilityOrchestrator 重载跳过: {e}")

            return {"status": "success", "message": "Configuration updated", "updated": updated_keys}
        except Exception as e:
            return JSONResponse({"status": "error", "message": str(e)}, status_code=500)

    return router
