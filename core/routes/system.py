"""
Galaxy - System & Config Routes
=====================================

Routes:
  GET  /api/v1/system/status       - 系统完整状态（含子系统详情）
  GET  /api/v1/system/health       - 健康检查
  GET  /api/v1/system/config       - 系统配置(脱敏)
  GET  /api/v1/agents/status       - 所有活跃 Agent 状态
  GET  /api/v1/nodes/status        - 所有节点注册状态
  GET  /api/config                 - 前端配置
  POST /api/config/update          - 更新 API Key 配置
"""

import logging
import os
import time
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

logger = logging.getLogger("Galaxy.API")

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

    @router.get("/api/v1/system/subsystems")
    async def system_subsystems():
        """获取所有子系统详细状态"""
        subsystems = {}

        # Agent Factory
        try:
            from core.agent_factory import get_agent_factory
            factory = get_agent_factory()
            agents = factory.list_agents() if hasattr(factory, 'list_agents') else {}
            subsystems["agent_factory"] = {
                "status": "running",
                "agent_count": len(agents),
                "max_agents": getattr(factory, 'MAX_AGENTS', None),
            }
        except Exception as e:
            subsystems["agent_factory"] = {"status": "error", "error": str(e)}

        # LLM Router
        try:
            from core.multi_llm_router import get_llm_router
            router_inst = get_llm_router()
            router_status = router_inst.get_status() if hasattr(router_inst, 'get_status') else {}
            subsystems["llm_router"] = {
                "status": "running",
                "details": router_status,
            }
        except Exception as e:
            subsystems["llm_router"] = {"status": "error", "error": str(e)}

        # Node Registry
        try:
            from core.node_registry import get_node_registry
            registry = get_node_registry()
            meta = registry.metadata if hasattr(registry, 'metadata') else {}
            subsystems["node_registry"] = {
                "status": "running",
                "registered_nodes": len(meta),
            }
        except Exception as e:
            subsystems["node_registry"] = {"status": "error", "error": str(e)}

        # Monitoring
        try:
            from core.monitoring import get_monitoring_manager
            mon = get_monitoring_manager()
            subsystems["monitoring"] = {
                "status": "running",
                "details": mon.get_status() if hasattr(mon, 'get_status') else {},
            }
        except Exception as e:
            subsystems["monitoring"] = {"status": "error", "error": str(e)}

        # Cache
        try:
            import core.cache as _cache_mod
            instance = getattr(_cache_mod, '_cache_instance', None)
            subsystems["cache"] = {
                "status": "running" if instance else "not_initialized",
            }
        except Exception as e:
            subsystems["cache"] = {"status": "error", "error": str(e)}

        return JSONResponse({
            "timestamp": datetime.now().isoformat(),
            "subsystems": subsystems,
        })

    @router.get("/api/v1/agents/status")
    async def agents_status():
        """获取所有活跃 Agent 状态"""
        try:
            from core.agent_factory import get_agent_factory
            factory = get_agent_factory()
            agents = factory.list_agents() if hasattr(factory, 'list_agents') else {}
            agent_list = []
            for agent_id, agent in agents.items():
                agent_info = {
                    "agent_id": agent_id,
                    "state": agent.state.value if hasattr(agent.state, 'value') else str(agent.state),
                    "role": getattr(agent, 'role', None),
                    "parent_id": getattr(agent, 'parent_id', None),
                    "created_at": getattr(agent, 'created_at', None),
                }
                if hasattr(agent, 'metrics') and agent.metrics:
                    agent_info["metrics"] = {
                        k: v for k, v in agent.metrics.items()
                        if isinstance(v, (int, float, str, bool))
                    }
                agent_list.append(agent_info)
            return JSONResponse({
                "timestamp": datetime.now().isoformat(),
                "total": len(agent_list),
                "agents": agent_list,
            })
        except Exception as e:
            return JSONResponse({
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "agents": [],
            }, status_code=500)

    @router.get("/api/v1/nodes/status")
    async def nodes_status():
        """获取所有节点注册状态"""
        try:
            from core.node_registry import get_node_registry
            registry = get_node_registry()
            meta = registry.metadata if hasattr(registry, 'metadata') else {}
            node_list = []
            for node_id, m in meta.items():
                node_list.append({
                    "node_id": node_id,
                    "name": getattr(m, 'name', node_id),
                    "status": m.status.value if hasattr(m.status, 'value') else str(getattr(m, 'status', 'unknown')),
                    "error_message": getattr(m, 'error_message', None),
                    "version": getattr(m, 'version', None),
                })
            # Sort: ERROR nodes first, then READY
            node_list.sort(key=lambda n: (0 if n["status"] == "error" else 1, n["node_id"]))
            return JSONResponse({
                "timestamp": datetime.now().isoformat(),
                "total": len(node_list),
                "by_status": _count_by_status(node_list),
                "nodes": node_list,
            })
        except Exception as e:
            return JSONResponse({
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "nodes": [],
            }, status_code=500)

    def _count_by_status(node_list):
        counts = {}
        for n in node_list:
            s = n.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1
        return counts

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
                f.write("# Galaxy - Environment Configuration\n")
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
