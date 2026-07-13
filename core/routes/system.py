"""
Galaxy - System & Config Routes
=====================================

**Output authority notice**
----------------------------
The endpoints in this module are **operational / management endpoints**.  They
expose service lifecycle, node registration, task queue state, and
configuration — information that is useful for operators but is NOT the
canonical projection truth for desktop consumers or status boards.

Canonical runtime truth (topology, routing, OneAPI, continuum posture) is
assembled in one place and exposed through a dedicated projection endpoint:

    GET /api/v1/projection/runtime-truth
        ← core.projection.runtime_truth_compiler.compile_runtime_truth()
        ← RUNTIME_TRUTH_COMPILER_AUTHORITY sentinel

Desktop status board consumers should prefer:
    GET /api/v1/projection/desktop-status-board   (PR-8 integrated payload)
    GET /api/v1/projection/runtime-truth          (canonical truth snapshot)

Routes in this module:
  GET  /api/v1/system/status       - 服务运行状态（管理用途）
  GET  /api/v1/system/health       - 健康检查
  GET  /api/v1/system/config       - 系统配置(脱敏)
  GET  /api/v1/system/mode-status  - 系统模式状态（本地 vs 跨设备，接管能力可用性）
  GET  /api/v1/agents/status       - 所有活跃 Agent 状态
  GET  /api/v1/nodes/status        - 所有节点注册状态
  GET  /api/config                 - 前端配置
  POST /api/config/update          - 更新 API Key 配置

See ``docs/PROJECTION_OUTPUT_AUTHORITY.md`` for the full canonical output
authority model and endpoint directory.
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

logger = logging.getLogger("Galaxy.API")

# PR-13 (node track): Import canonical node-count helper so that
# /api/v1/system/status derives node counts from NodeFabricRegistry
# rather than the legacy node_status_cache compat store.
try:
    from core.node_final_boundary_enforcement import (  # noqa: F401
        get_node_count_from_canonical_source as _get_node_count_from_canonical_source,
        SYSTEM_STATUS_NODES_COUNT_MUST_PREFER_CANONICAL_REGISTRY_POLICY as _NODE_COUNT_POLICY,
    )
    _CANONICAL_NODE_COUNT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _CANONICAL_NODE_COUNT_AVAILABLE = False
    _get_node_count_from_canonical_source = None  # type: ignore[assignment]


# 支持的 API Key 白名单
def create_router(service_manager=None, config=None) -> APIRouter:
    """Create system & config routes router."""
    router = APIRouter()

    @router.get("/api/v1/system/status")
    async def system_status():
        """获取系统完整状态"""
        services = service_manager.get_status() if service_manager else {}

        # PR-13 (node track): Derive node counts from the canonical
        # NodeFabricRegistry rather than the legacy node_status_cache
        # compat store.  The response includes a node_count_source key
        # so operators can see which authority was used.
        if _CANONICAL_NODE_COUNT_AVAILABLE:
            _node_counts = _get_node_count_from_canonical_source()
        else:
            _node_counts = {
                "total": len(node_status_cache),
                "active": sum(1 for n in node_status_cache.values() if n.get("status") == "running"),
                "node_count_source": "compat_fallback:node_status_cache",
            }

        return JSONResponse({
            "status": "running",
            "version": "2.0.0",
            "timestamp": datetime.now().isoformat(),
            "services": services,
            "devices": {
                "registered": len(registered_devices),
                "online": len(connection_manager.online_device_ids()),
                "list": [
                    {
                        "device_id": did,
                        "device_name": info.get("device_name", ""),
                        "device_type": info.get("device_type", ""),
                        "online": connection_manager.is_online(did),
                        "last_seen": info.get("last_seen", "")
                    }
                    for did, info in registered_devices.items()
                ]
            },
            "nodes": {
                "total": _node_counts["total"],
                "active": _node_counts["active"],
                "node_count_source": _node_counts.get("node_count_source", "unknown"),
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
            logger.debug("Fallback triggered: %s", e)
            subsystems["agent_factory"] = {"status": "error", "error": str(e)}

        # LLM Router
        try:
            from core.llm.route_authority import get_llm_route_authority
            router_inst = get_llm_route_authority().execution_router
            router_status = router_inst.get_status() if hasattr(router_inst, 'get_status') else {}
            subsystems["llm_router"] = {
                "status": "running",
                "details": router_status,
            }
        except Exception as e:
            logger.debug("Fallback triggered: %s", e)
            subsystems["llm_router"] = {"status": "error", "error": str(e)}

        # Node Registry — canonical runtime authority only.
        try:
            from core.nodes.node_fabric_registry import get_node_fabric_registry
            fab = get_node_fabric_registry()
            canonical_count = fab.count()
            subsystems["node_registry"] = {
                "status": "running",
                "registered_nodes": canonical_count,
                "registry_authority": "canonical:NodeFabricRegistry",
            }
        except Exception as e:
            logger.debug("Fallback triggered: %s", e)
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
            logger.debug("Fallback triggered: %s", e)
            subsystems["monitoring"] = {"status": "error", "error": str(e)}

        # Cache
        try:
            import core.cache as _cache_mod
            instance = getattr(_cache_mod, '_cache_instance', None)
            subsystems["cache"] = {
                "status": "running" if instance else "not_initialized",
            }
        except Exception as e:
            logger.debug("Fallback triggered: %s", e)
            subsystems["cache"] = {"status": "error", "error": str(e)}

        return JSONResponse({
            "timestamp": datetime.now().isoformat(),
            "subsystems": subsystems,
        })

    @router.get("/api/v1/system/completion-status")
    async def system_completion_status():
        """获取统一的系统完成度/收口状态"""
        try:
            from core.system_completion_status import get_system_completion_status

            report = get_system_completion_status(force_rebuild=True)
            return JSONResponse(report.to_dict())
        except Exception as e:
            logger.exception("system completion status build failed: %s", e)
            return JSONResponse(
                {
                    "status": "error",
                    "timestamp": datetime.now().isoformat(),
                    "error": str(e),
                },
                status_code=500,
            )

    @router.get("/api/v1/system/dual-repo-progress")
    async def dual_repo_progress():
        """获取双仓（V2+Android）推进进度快照（中文摘要 + 收口/审查/计划汇总）"""
        try:
            from core.dual_repo_progress_report import build_dual_repo_progress_report

            payload = build_dual_repo_progress_report(force_rebuild=True)
            payload["timestamp"] = datetime.now().isoformat()
            return JSONResponse(payload)
        except Exception as e:
            logger.exception("dual repo progress build failed: %s", e)
            return JSONResponse(
                {
                    "status": "error",
                    "timestamp": datetime.now().isoformat(),
                    "error": str(e),
                },
                status_code=500,
            )

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
            node_list = []

            # Primary: read from canonical NodeFabricRegistry
            try:
                from core.nodes.node_fabric_registry import get_node_fabric_registry
                fab = get_node_fabric_registry()
                for n in fab.list_nodes():
                    node_list.append({
                        "node_id": n.node_id,
                        "name": n.metadata.get("name", n.node_id) if isinstance(n.metadata, dict) else n.node_id,
                        "status": n.status.value if hasattr(n.status, "value") else str(n.status),
                        "error_message": None,
                        "version": n.metadata.get("version") if isinstance(n.metadata, dict) else None,
                        "role": n.role.value if hasattr(n.role, "value") else str(n.role),
                        "health_score": round(n.health_score(), 4),
                        "source": "canonical",
                    })
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

            # Sort: ERROR nodes first, then by node_id
            node_list.sort(key=lambda n: (0 if str(n["status"]).lower() == "error" else 1, n["node_id"]))
            return JSONResponse({
                "timestamp": datetime.now().isoformat(),
                "total": len(node_list),
                "by_status": _count_by_status(node_list),
                "nodes": node_list,
                "registry_authority": "canonical:NodeFabricRegistry",
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

        # 模型 tab / 设置 tab 需要"每个 env key 是否已配置"来渲染状态,以及少量
        # 非敏感值(地址/模型名)用于回填。密钥值一律不下发(只给布尔),地址与
        # 模型名等非敏感项回填明文。以下均为对既有响应的"增量"字段,不改动
        # api_base_url / ws_url / status(test_routes_import.test_api_config 依赖之)。
        _SECRET_MODEL_KEYS = [
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY",
            "GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
            "OPENROUTER_API_KEY", "PERPLEXITY_API_KEY", "SONAR_API_KEY",
            "XAI_API_KEY", "ZHIPU_API_KEY", "QWEN_API_KEY", "DASHSCOPE_API_KEY",
            "MOONSHOT_API_KEY", "MINIMAX_API_KEY", "STEP_API_KEY", "MIMO_API_KEY",
            "MISTRAL_API_KEY", "HF_API_TOKEN", "ONEAPI_API_KEY",
            "DEEPSEEK_OCR2_API_KEY",
        ]
        _NON_SECRET_MODEL_KEYS = [
            "OLLAMA_URL", "OLLAMA_MODEL", "ONEAPI_URL",
            "LOCAL_VLLM_URL", "VLLM_URL", "OPENAI_API_BASE",
        ]
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
            },
            # 每个密钥 env key 是否已配置(不下发密钥值本身)
            "configured": {k: _is_configured(k) for k in _SECRET_MODEL_KEYS},
            # 非敏感项(地址/模型名)明文回填
            "values": {k: os.getenv(k, "") for k in _NON_SECRET_MODEL_KEYS},
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

    # 注:此处曾有第二个写配置端点 POST /api/config/update(配 ALLOWED_CONFIG_KEYS
    # 白名单)。全仓库排查确认它【零真实调用方】——前端(ModelsTab/SettingsTab)、
    # Electron IPC、Android、dashboard 全都走 core/routes/config.py 的
    # POST /api/config;唯一提及它的只有一处测试的文档字符串。两份并存的写配置
    # 实现 + 两份互不同步的键白名单(这份 ALLOWED_CONFIG_KEYS vs config.py 的
    # CONFIG_SCHEMA)正是之前"填了 Key 保存失败"一类配置漂移 bug 的温床。已删除
    # 本冗余端点,写配置收口到 core/routes/config.py 这一处唯一实现。

    @router.get("/api/v1/system/mode-status")
    async def system_mode_status():
        """Axis-6: 全端系统模式状态快照。

        暴露当前系统运行模式（desktop-local vs desktop-cross-device）、跨设备能力
        可用性、接管能力状态以及已连接 Android 设备数量，供 operator 面和客户端判断
        当前系统所处的运行态。

        Returns
        -------
        JSON 对象，包含以下字段：

        mode
            当前系统模式字符串（``"desktop-local"`` 或 ``"desktop-cross-device"``）。
        cross_device_enabled
            跨设备路由是否启用（由 ``GALAXY_CROSS_DEVICE_ENABLED`` 或
            ``GALAXY_SYSTEM_MODE`` 派生）。
        takeover_available
            接管（takeover）能力是否可用（仅在 cross_device_enabled=true 时为 true）。
        android_devices_online
            当前在线 Android 设备数量。
        nats_enabled
            NATS 总线是否启用。
        fabric_strict
            是否处于严格启动模式（缺少 fabric 依赖时是否硬失败）。
        schema_version
            响应 schema 版本，便于客户端进行版本适配。
        """
        try:
            from core.system_mode import resolve_fabric_config
            fabric = resolve_fabric_config()
            cross_device_on = fabric.cross_device_enabled
            current_mode = fabric.mode.value
            nats_enabled = fabric.nats_enabled
            fabric_strict = fabric.fabric_strict
        except Exception as _e:
            logger.warning("system_mode_status: resolve_fabric_config failed: %s", _e)
            cross_device_on = False
            current_mode = "desktop-local"
            nats_enabled = False
            fabric_strict = False

        # Cross-device switch may override the fabric config at runtime
        try:
            from galaxy_gateway.cross_device_switch import is_cross_device_enabled
            cross_device_on = is_cross_device_enabled()
        except Exception as exc:
            logger.debug("Suppressed: %s", exc)

        # Count connected Android devices from the active connection manager
        android_online = 0
        try:
            android_online = len([
                did for did in connection_manager.online_device_ids()
                if did in registered_devices
                and registered_devices[did].get("device_type", "").startswith("android")
            ])
        except Exception as exc:
            logger.debug("Suppressed: %s", exc)

        return JSONResponse({
            "mode": current_mode,
            "cross_device_enabled": cross_device_on,
            "takeover_available": cross_device_on,
            "android_devices_online": android_online,
            "nats_enabled": nats_enabled,
            "fabric_strict": fabric_strict,
            "schema_version": "1.0",
        })

    return router
