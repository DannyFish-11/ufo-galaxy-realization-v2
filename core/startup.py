"""
Galaxy - 系统启动引导
==========================

统一初始化所有核心子系统，供 unified_launcher.py 调用。

初始化顺序：
  1. 缓存层（Redis / 内存降级）
  2. 统一错误处理框架
  3. 并发管理器
  4. 监控系统（健康检查、告警、指标）
  5. 性能中间件（压缩、限流、缓存、计时）
  6. 命令路由引擎
  7. AI 意图引擎（解析器、记忆、推荐）
  8. 向量数据库（Qdrant）
  9. 事件桥接（EventBus ↔ 所有子系统）
  10. 多 LLM 智能路由器
  11. 动态 Agent 工厂 + 分形执行器
  12. 数字孪生引擎
  13. 三位一体世界模型
  14. 节点发现服务
  15. 健康检查整合层
  16. Galaxy Gateway

所有模块均支持优雅降级：缺少 Redis → 内存缓存，缺少 LLM → 规则引擎。
"""

import asyncio
import logging
import os
import signal
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI

logger = logging.getLogger("Galaxy.Startup")


# ───────────────────── 启动依赖图 ─────────────────────

# 子系统名称 → 依赖列表（启动前必须先成功的子系统）
_SUBSYSTEM_DEPS: Dict[str, List[str]] = {
    "cache": [],
    "monitoring": [],
    "error_framework": [],
    "concurrency_manager": [],
    "config_hot_reload": [],
    "security_middleware": [],
    "performance": ["cache"],  # 缓存中间件需要 cache
    "command_router": ["cache"],
    "ai_intent": ["cache"],
    "qdrant": [],
    "event_bridge": ["command_router"],  # 事件桥接依赖命令路由
    "llm_router": [],
    "agent_system": ["llm_router"],  # Agent 依赖 LLM 路由
    "mcp_loader": [],
    "capability_orchestrator": ["mcp_loader"],  # 能力编排需要 MCP 工具
    "digital_twin": [],
    "world_model": [],
    "node_discovery": [],
    "health_integration": ["monitoring", "concurrency_manager", "node_discovery"],
    "galaxy_gateway": [],
    "device_router": ["command_router", "event_bridge"],
    "orchestrator": ["device_router", "ai_intent"],
}


def _check_circular_deps(deps: Dict[str, List[str]]) -> List[str]:
    """检测循环依赖，返回发现的环路径列表"""
    cycles = []
    WHITE, GRAY, BLACK = 0, 1, 2
    colors: Dict[str, int] = {k: WHITE for k in deps}
    path: List[str] = []

    def dfs(node: str):
        colors[node] = GRAY
        path.append(node)
        for dep in deps.get(node, []):
            if dep not in colors:
                continue
            if colors[dep] == GRAY:
                idx = path.index(dep)
                cycle = path[idx:] + [dep]
                cycles.append(" → ".join(cycle))
            elif colors[dep] == WHITE:
                dfs(dep)
        path.pop()
        colors[node] = BLACK

    for node in deps:
        if colors[node] == WHITE:
            dfs(node)

    return cycles


def _validate_startup_deps() -> List[str]:
    """验证启动依赖图的完整性"""
    errors = []
    # 检测循环依赖
    cycles = _check_circular_deps(_SUBSYSTEM_DEPS)
    for c in cycles:
        errors.append(f"循环依赖: {c}")
    # 检测引用了不存在的依赖
    all_names = set(_SUBSYSTEM_DEPS.keys())
    for name, deps in _SUBSYSTEM_DEPS.items():
        for dep in deps:
            if dep not in all_names:
                errors.append(f"子系统 '{name}' 依赖不存在的 '{dep}'")
    return errors


def _check_pip_dependencies() -> dict:
    """检查关键 pip 依赖是否已安装"""
    import importlib.metadata as _meta

    core_packages = ["fastapi", "uvicorn", "pydantic"]
    optional_packages = [
        "aiohttp",
        "psutil",
        "python-multipart",
        "cryptography",
        "Pillow",
        "feedparser",
        "bleak",
        "asyncssh",
    ]

    missing_core = []
    missing_optional = []

    for pkg in core_packages:
        try:
            _meta.version(pkg)
        except _meta.PackageNotFoundError:
            missing_core.append(pkg)

    for pkg in optional_packages:
        try:
            _meta.version(pkg)
        except _meta.PackageNotFoundError:
            missing_optional.append(pkg)

    return {
        "status": "ok" if not missing_core else "degraded",
        "missing_core": missing_core,
        "missing_optional": missing_optional,
    }


async def _handle_signal(sig):
    """处理 SIGTERM/SIGINT 信号，优雅关闭"""
    logger.info(f"收到信号 {sig.name}，开始优雅关闭...")
    await shutdown_subsystems()
    logger.info("优雅关闭完成")


def wire_durable_audit_store(store_path: Optional[str] = None) -> dict:
    """Wire the process-level :class:`DurableAuditStore` to all audit sinks.

    Attaches the singleton :class:`~core.replay_audit_persistence.DurableAuditStore`
    to:

    * :class:`~core.replay_foundation.ReplayFoundation` — replay / execution /
      route / fallback records become durably stored.
    * :class:`~core.audit_event_semantics.AuditEventSemantics` — canonical
      dispatch-spine audit events become durably stored.
    * :class:`~core.canonical_session_truth.CanonicalSessionTruthRuntime` —
      truth-merge evidence becomes durably stored (best-effort; skipped when
      the import is unavailable).

    The store is **observational only** and does NOT alter any runtime
    authority or routing decisions.  In-memory ring buffers remain the
    authoritative live read surfaces.

    This function is idempotent: calling it multiple times re-attaches the
    same singleton store.

    Parameters
    ----------
    store_path:
        Optional path override forwarded to
        :func:`~core.replay_audit_persistence.get_replay_audit_store`.
        Respected only before the singleton is first created.

    Returns
    -------
    dict
        A status dict suitable for inclusion in the ``bootstrap_subsystems``
        results.  Keys: ``status``, ``store_path``,
        ``replay_foundation_wired``, ``audit_event_semantics_wired``,
        ``canonical_truth_wired``.  On failure: ``status="degraded"`` with
        ``error``.
    """
    try:
        from core.audit_event_semantics import get_audit_event_semantics
        from core.replay_audit_persistence import get_replay_audit_store
        from core.replay_foundation import get_replay_foundation

        _store = get_replay_audit_store(store_path=store_path)

        # Wire ReplayFoundation (execution / route / fallback / retry records)
        get_replay_foundation().set_audit_store(_store)

        # Wire AuditEventSemantics (canonical dispatch-spine audit vocabulary)
        get_audit_event_semantics().set_audit_store(_store)

        # Wire CanonicalSessionTruthRuntime (truth merge / conflict evidence)
        _truth_wired = False
        try:
            from core.canonical_session_truth import get_canonical_session_truth_runtime

            get_canonical_session_truth_runtime().set_audit_store(_store)
            _truth_wired = True
        except Exception as _truth_exc:  # noqa: BLE001
            logger.warning(
                "wire_durable_audit_store: CanonicalSessionTruthRuntime wiring skipped "
                "(truth-merge evidence will not be durable this session): %s",
                _truth_exc,
            )

        return {
            "status": "ok",
            "store_path": _store.store_path,
            "replay_foundation_wired": True,
            "audit_event_semantics_wired": True,
            "canonical_truth_wired": _truth_wired,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("wire_durable_audit_store failed: %s", exc)
        return {"status": "degraded", "error": str(exc)}


async def bootstrap_subsystems(app: FastAPI, config: Any = None) -> dict:
    """
    启动所有核心子系统并挂载中间件

    增强：
    - 启动前验证依赖图（循环依赖检测）
    - 依赖项失败时跳过下游子系统并记录原因
    - 启动耗时追踪

    Args:
        app: FastAPI 应用实例
        config: SystemConfig 或 None

    Returns:
        各子系统的初始化结果
    """
    results = {}
    t0 = time.monotonic()

    # Step 0a: 观测追踪(OpenTelemetry)一次性初始化 —— 默认关(GALAXY_OTEL_ENABLED=1
    # 才启用)、未装 opentelemetry 时纯 no-op,绝不影响启动。放在最前,使随后所有
    # span 都在 provider 就绪后创建。
    try:
        from core.otel_tracing import init_tracing

        results["otel_tracing_active"] = init_tracing()
    except Exception as _e:  # noqa: BLE001 — 观测初始化绝不阻断启动
        logger.debug("OTel 追踪初始化跳过: %s", _e)
        results["otel_tracing_active"] = False

    # Step 0: pip 依赖可用性检查
    try:
        dep_report = _check_pip_dependencies()
        if dep_report["missing_core"]:
            logger.error(f"缺少核心依赖: {dep_report['missing_core']}")
            logger.error("安装命令: pip install " + " ".join(dep_report["missing_core"]))
        for pkg in dep_report.get("missing_optional", []):
            logger.warning(f"可选依赖未安装: {pkg}")
        results["dependency_check"] = dep_report
    except Exception as e:
        logger.warning(f"依赖检查跳过: {e}")
        results["dependency_check"] = {"status": "skipped", "error": str(e)}

    # 注册信号处理器
    # 注:asyncio 的 loop.add_signal_handler 在 Windows(ProactorEventLoop)上
    # 本就【不支持】,必然抛 NotImplementedError——这是平台预期行为,不是故障。
    # Windows 下 Ctrl+C 仍能通过 KeyboardInterrupt 正常停止。之前这里打 WARNING
    # 让用户以为出了问题,现在按平台区分:Windows/非主线程用 info 级如实说明。
    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(_handle_signal(s)))
        logger.info("已注册 SIGTERM/SIGINT 信号处理器")
    except (RuntimeError, NotImplementedError):
        logger.info("跳过 asyncio 信号处理器注册（Windows 或非主线程下不支持,属预期;" "Ctrl+C 仍可正常停止）")

    # 启动前校验依赖图
    dep_errors = _validate_startup_deps()
    if dep_errors:
        for err in dep_errors:
            logger.error(f"依赖图校验失败: {err}")
        results["_dep_validation"] = {"status": "error", "errors": dep_errors}
    else:
        results["_dep_validation"] = {"status": "ok"}
        logger.info("启动依赖图校验通过")

    def _deps_ok(subsystem: str) -> bool:
        """检查子系统的依赖是否全部成功初始化"""
        for dep in _SUBSYSTEM_DEPS.get(subsystem, []):
            dep_result = results.get(dep, {})
            if dep_result.get("status") not in ("ok", "degraded"):
                logger.warning(
                    f"跳过 {subsystem}: 依赖 '{dep}' 未成功 " f"(status={dep_result.get('status', 'missing')})"
                )
                results[subsystem] = {
                    "status": "skipped",
                    "reason": f"依赖 '{dep}' 未就绪",
                }
                return False
        return True

    # ====================================================================
    # 1. 缓存层
    # ====================================================================
    cache = None
    try:
        from core.cache import get_cache

        redis_url = os.environ.get("REDIS_URL", "")
        if config and hasattr(config, "redis_url"):
            redis_url = config.redis_url or redis_url
        cache = await get_cache(redis_url)
        results["cache"] = {"status": "ok", "backend": cache.backend_type}
        logger.info(f"缓存已初始化: {cache.backend_type}")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["cache"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"缓存初始化失败（降级到内存）: {e}")

    # ====================================================================
    # 2. 监控系统
    # ====================================================================
    try:
        from core.monitoring import get_monitoring_manager

        monitoring = get_monitoring_manager()

        # 注册内建健康检查
        monitoring.health.register_check("api_server", lambda: {"status": "healthy"})

        if cache:

            async def _check_cache():
                info = await cache.info()
                return {"status": "healthy", **info}

            monitoring.health.register_check("cache", _check_cache)

        if cache and cache.backend_type == "redis":
            monitoring.health.register_check("redis", lambda: {"status": "healthy", "type": "redis"})

        await monitoring.start()
        results["monitoring"] = {"status": "ok"}
        logger.info("监控系统已启动")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["monitoring"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"监控系统启动失败: {e}")

    # ====================================================================
    # 2b. 统一错误处理框架
    # ====================================================================
    error_tracker = None
    try:
        from core.error_framework import create_error_handlers, get_error_tracker

        error_tracker = get_error_tracker()
        create_error_handlers(app)
        results["error_framework"] = {"status": "ok"}
        logger.info("统一错误处理框架已初始化")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["error_framework"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"错误处理框架初始化失败: {e}")

    # ====================================================================
    # 2c. 并发管理器
    # ====================================================================
    concurrency_mgr = None
    try:
        from core.concurrency_manager import get_concurrency_manager

        concurrency_mgr = get_concurrency_manager(
            global_max=int(os.environ.get("CONCURRENCY_GLOBAL_MAX", "50")),
        )
        await concurrency_mgr.start()
        results["concurrency_manager"] = {"status": "ok"}
        logger.info("并发管理器已启动")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["concurrency_manager"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"并发管理器启动失败: {e}")

    # ====================================================================
    # 2d. 配置热更新管理器
    # ====================================================================
    try:
        from core.config_hot_reload import get_config_manager

        config_path = os.environ.get(
            "GALAXY_CONFIG_PATH",
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "unified_config.json"),
        )
        config_mgr = get_config_manager(config_path=config_path)
        if os.path.exists(config_path):
            errors = config_mgr.load_from_file()
            if errors:
                logger.warning(f"配置加载有误: {errors}")
            await config_mgr.start_watching()
        results["config_hot_reload"] = {"status": "ok", "path": config_path}
        logger.info(f"配置热更新管理器已启动: {config_path}")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["config_hot_reload"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"配置热更新管理器启动失败: {e}")

    # ====================================================================
    # 2e. 安全中间件
    # ====================================================================
    try:
        from core.security_middleware import get_security_manager

        security_mgr = get_security_manager()
        # HTTP 限流收口到下面步骤 3 的性能中间件链(唯一权威限流层),这里不再重复
        # 安装本管理器自带的 RateLimiter——否则同一请求被两个独立限流器双重计数
        # (双层限流叠加,阈值/分桶键还不一致)。审计/安全头/IP黑名单/输入验证照装。
        security_mgr.setup_middleware(app, include_rate_limit=False)
        results["security_middleware"] = {"status": "ok"}
        logger.info("安全中间件已安装 (审计日志 + 安全头 + IP 黑名单 + 输入验证;HTTP 限流收口到性能层)")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["security_middleware"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"安全中间件安装失败: {e}")

    # ====================================================================
    # 3. 性能中间件链
    # ====================================================================
    try:
        from core.performance import (
            CachingMiddleware,
            RateLimitMiddleware,
            RequestTimerMiddleware,
            ResponseCompressor,
        )

        # 中间件按添加的逆序执行（最后添加的最先执行）
        # 执行顺序：Timer → RateLimit → Compress → Cache → Handler

        if cache:
            default_ttl = int(os.environ.get("REDIS_HTTP_CACHE_TTL", "30"))
            app.add_middleware(CachingMiddleware, cache_backend=cache, default_ttl=default_ttl)
            logger.info("API 缓存中间件已加载")

        min_size = int(os.environ.get("GZIP_MIN_SIZE", "1024"))
        app.add_middleware(ResponseCompressor, min_size=min_size)
        logger.info("gzip 压缩中间件已加载")

        max_req = int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "200"))
        window = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
        app.add_middleware(RateLimitMiddleware, max_requests=max_req, window_seconds=window)
        logger.info(f"限流中间件已加载: {max_req} req / {window}s")

        slow_threshold = float(os.environ.get("SLOW_REQUEST_THRESHOLD_MS", "500"))
        app.add_middleware(RequestTimerMiddleware, slow_threshold_ms=slow_threshold)
        logger.info("请求计时中间件已加载")

        results["performance"] = {"status": "ok", "middlewares": 4 if cache else 3}
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["performance"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"性能中间件加载失败: {e}")

    # ====================================================================
    # 4. 命令路由引擎
    # ====================================================================
    try:
        from core.command_router import get_command_router

        cmd_router = get_command_router(
            cache_backend=cache,
            max_concurrent=int(os.environ.get("CMD_MAX_CONCURRENT", "20")),
        )

        # 设置默认执行器 — 通过 DeviceCommunication 发送命令到目标设备
        try:
            from core.device_communication import device_comm

            async def _default_executor(target: str, command: str, params: dict):
                return await device_comm.send_command(target, command, params)

            cmd_router.set_executor(_default_executor)
            logger.info("命令路由引擎执行器已绑定 DeviceCommunication")
        except Exception as exec_err:
            logger.warning(f"命令路由引擎执行器绑定失败（降级）: {exec_err}")

        results["command_router"] = {"status": "ok"}
        logger.info("命令路由引擎已初始化")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["command_router"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"命令路由引擎初始化失败: {e}")

    # ====================================================================
    # 5. AI 意图引擎
    # ====================================================================
    try:
        from core.ai_intent import (
            get_conversation_memory,
            get_intent_parser,
            get_smart_recommender,
        )

        get_intent_parser()
        memory = get_conversation_memory(cache_backend=cache)
        get_smart_recommender(memory=memory)

        results["ai_intent"] = {"status": "ok"}
        logger.info("AI 意图引擎已初始化")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["ai_intent"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"AI 意图引擎初始化失败: {e}")

    # ====================================================================
    # 6. 向量数据库（Qdrant）连接检查
    # ====================================================================
    qdrant_url = os.environ.get("QDRANT_URL", "")
    if qdrant_url:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{qdrant_url}/healthz")
                if resp.status_code == 200:
                    results["qdrant"] = {"status": "ok", "url": qdrant_url}
                    logger.info(f"Qdrant 向量数据库已连接: {qdrant_url}")
                else:
                    results["qdrant"] = {"status": "unreachable"}
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            results["qdrant"] = {"status": "not_available"}
            logger.info("Qdrant 不可用（语义搜索将使用本地模式）")

    # ====================================================================
    # 7. 事件桥接（最后连接，因为它依赖上面所有子系统）
    # ====================================================================
    try:
        from core.event_bridge import get_event_bridge

        bridge = get_event_bridge()
        await bridge.wire()
        results["event_bridge"] = {"status": "ok"}
        logger.info("事件桥接已建立")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["event_bridge"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"事件桥接建立失败: {e}")

    # ====================================================================
    # 8. 多 LLM 智能路由器
    # ====================================================================
    llm_router = None
    try:
        from core.multi_llm_router import get_llm_router

        llm_router = get_llm_router()
        status = llm_router.get_status()
        results["llm_router"] = {
            "status": "ok",
            "providers": status["total_providers"],
            "healthy": status["healthy_providers"],
        }
        logger.info(
            f"多 LLM 路由器已初始化: " f"{status['total_providers']} 提供商, " f"{status['healthy_providers']} 可用"
        )
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["llm_router"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"多 LLM 路由器初始化失败: {e}")

    # ====================================================================
    # 9. 动态 Agent 工厂 + 分形执行器
    # ====================================================================
    if not _deps_ok("agent_system"):
        logger.warning("跳过 Agent 系统初始化：依赖未满足，已标记为 skipped")
    else:
        try:
            from core.agent_factory import get_agent_factory
            from core.fractal_agent import get_fractal_executor

            agent_factory = get_agent_factory(llm_router=llm_router)
            get_fractal_executor(llm_router=llm_router, agent_factory=agent_factory)
            # 启动 Agent TTL 清理循环
            await agent_factory.start_cleanup_loop()
            results["agent_system"] = {
                "status": "ok",
                "llm_enabled": llm_router is not None,
                "restored_agents": len(agent_factory.agents),
            }
            logger.info(
                f"Agent 系统已初始化 (工厂 + 分形执行器, "
                f"LLM: {'启用' if llm_router else '降级'}, "
                f"恢复 {len(agent_factory.agents)} 个 Agent)"
            )
        except Exception as e:
            logger.debug("Fallback triggered: %s", e)
            results["agent_system"] = {"status": "degraded", "error": str(e)}
            logger.warning(f"Agent 系统初始化失败: {e}")

    # ====================================================================
    # 9a. 统一会话管理 + 全链路编排器
    # ====================================================================
    try:
        from core.e2e_pipeline import init_pipeline
        from core.routes._shared import connection_manager as _conn_mgr
        from core.session_manager import get_session_manager

        session_mgr = get_session_manager()
        init_pipeline(
            session_manager=session_mgr,
            llm_router=llm_router,
            agent_factory=agent_factory if "agent_factory" in dir() else None,
            connection_manager=_conn_mgr,
        )
        results["session_manager"] = {
            "status": "ok",
            "sessions_restored": len(session_mgr._sessions),
        }
        results["e2e_pipeline"] = {"status": "ok"}
        logger.info(f"统一会话管理器已初始化 (恢复 {len(session_mgr._sessions)} 个会话), " f"全链路编排器就绪")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["session_manager"] = {"status": "degraded", "error": str(e)}
        results["e2e_pipeline"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"会话管理/全链路编排器初始化失败: {e}")

    # ====================================================================
    # 9a-2. SessionRoaming + WakeEventBus + WakeRouter 初始化
    # ====================================================================
    try:
        from galaxy_gateway.session_roaming import session_roaming

        results["session_roaming"] = {
            "status": "ok",
            "active_sessions": len(session_roaming._sessions),
        }
        results["wake_event_bus"] = {"status": "ok"}
        results["wake_router"] = {"status": "ok"}
        logger.info(
            "SessionRoaming + WakeEventBus + WakeRouter 已初始化 " f"(活跃会话: {len(session_roaming._sessions)})"
        )
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["session_roaming"] = {"status": "degraded", "error": str(e)}
        results["wake_event_bus"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"SessionRoaming/WakeEventBus 初始化失败: {e}")

    # ====================================================================
    # 9b. MCP 工具加载（从 config/mcp_servers.json 读取并加载）
    # ====================================================================
    try:
        import json as _json

        from core.mcp_loader import mcp_loader

        mcp_config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "mcp_servers.json")
        auto_started = 0
        if os.path.exists(mcp_config_path):
            with open(mcp_config_path, "r", encoding="utf-8") as f:
                mcp_config = _json.load(f)
            for srv in mcp_config.get("servers", []):
                if not srv.get("auto_start", False):
                    continue
                try:
                    # 解析环境变量引用 (${VAR_NAME} → os.environ)
                    env = {}
                    for k, v in (srv.get("env") or {}).items():
                        if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                            env[k] = os.environ.get(v[2:-1], "")
                        else:
                            env[k] = v
                    await mcp_loader.load(
                        name=srv["name"],
                        command=srv["command"],
                        env=env if env else None,
                        auto_start=True,
                    )
                    auto_started += 1
                except Exception as e:
                    logger.debug(f"MCP server '{srv['name']}' 跳过: {e}")

        results["mcp_loader"] = {
            "status": "ok",
            "servers_loaded": len(mcp_loader.servers),
            "auto_started": auto_started,
        }
        logger.info(f"MCP 工具加载器就绪: {len(mcp_loader.servers)} 服务器, " f"{auto_started} 个自动启动")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["mcp_loader"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"MCP 加载器初始化失败: {e}")

    # ====================================================================
    # 9c. 能力编排器（统一 MCP + Skill + Node 能力注册表）
    # ====================================================================
    try:
        from core.capability_orchestrator import capability_orchestrator

        await capability_orchestrator.initialize()
        cap_count = len(capability_orchestrator.capabilities)
        results["capability_orchestrator"] = {
            "status": "ok",
            "capabilities_loaded": cap_count,
        }
        logger.info(f"能力编排器就绪: {cap_count} 个能力已注册")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["capability_orchestrator"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"能力编排器初始化失败: {e}")

    # ====================================================================
    # 10. 数字孪生引擎
    # ====================================================================
    try:
        from core.digital_twin_engine import get_digital_twin_engine

        get_digital_twin_engine()
        results["digital_twin"] = {"status": "ok"}
        logger.info("数字孪生引擎已初始化")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["digital_twin"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"数字孪生引擎初始化失败: {e}")

    # ====================================================================
    # 11. 三位一体世界模型
    # ====================================================================
    try:
        from enhancements.reasoning.world_model import WorldModel

        WorldModel()
        results["world_model"] = {"status": "ok", "pillars": ["ontology", "epistemology", "information"]}
        logger.info("三位一体世界模型已初始化 (本体论 + 认知论 + 信息论)")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["world_model"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"世界模型初始化失败: {e}")

    # ====================================================================
    # 14. 节点发现服务
    # ====================================================================
    discovery = None
    try:
        from core.node_discovery import get_node_discovery

        node_id = os.environ.get("GALAXY_NODE_ID", "master")
        discovery = get_node_discovery(node_id=node_id)
        await discovery.start()
        results["node_discovery"] = {"status": "ok", "node_id": node_id}
        logger.info(f"节点发现服务已启动: {node_id}")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["node_discovery"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"节点发现服务启动失败: {e}")

    # ====================================================================
    # 15. 健康检查整合层
    # ====================================================================
    try:
        from core.health_integration import get_unified_health_manager
        from core.system_load_monitor import get_monitor as get_load_monitor

        load_monitor = get_load_monitor()
        uhm = get_unified_health_manager()

        # 获取上面已初始化的 monitoring 实例（可能为 None）
        _monitoring = None
        try:
            from core.monitoring import get_monitoring_manager

            _monitoring = get_monitoring_manager()
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

        uhm.wire(
            monitoring=_monitoring,
            load_monitor=load_monitor,
            error_tracker=error_tracker,
            concurrency=concurrency_mgr,
            discovery=discovery,
        )
        await uhm.start()

        # 真机复现过:/metrics、/health/deep 每次命中都要卡 2-5 秒——根因是
        # get_system_load() 要枚举全部进程(psutil.process_iter),Windows 上
        # 单次就要这么久，而这个共享单例的后台采样循环从来没人启动过，导致
        # health_check.py/health_integration.py 里每个消费点都在各自的请求
        # 路径上同步触发一次全新采集。这里把循环真正跑起来，采样间隔放宽到
        # 10 秒(默认 1 秒对这种耗时的扫描没必要),后续消费点改读
        # get_cached_load() 就不再需要现算。
        load_monitor.sample_interval = max(load_monitor.sample_interval, 10.0)
        await load_monitor.start_monitoring()

        results["health_integration"] = {"status": "ok"}
        logger.info("健康检查整合层已启动（含系统负载后台采样）")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["health_integration"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"健康检查整合层启动失败: {e}")

    # ====================================================================
    # 15a. 常驻注意力循环（自发在场 / Ambient Attention Loop）
    # ====================================================================
    # 给三态 SILENT 补上"自发注意力":持续消费桌面感知(摄像头/屏幕/麦克风),
    # 帧差门控放行后让主脑做 SPEAK/SILENT/DELEGATE 三选一,把系统从"对话驱动"
    # 升级为"在场主体"。默认关闭(GALAXY_AMBIENT_LOOP=1 开启),不破坏既有行为;
    # 隐私跟随现有感知授权。
    try:
        from core.ambient_attention_loop import ambient_loop_enabled, get_ambient_loop

        if ambient_loop_enabled():
            _ambient = get_ambient_loop()
            await _ambient.start()
            results["ambient_attention_loop"] = {"status": "ok"}
            logger.info("常驻注意力循环已启动（自发在场）")
        else:
            results["ambient_attention_loop"] = {"status": "disabled"}
            logger.info("常驻注意力循环未启用（GALAXY_AMBIENT_LOOP=1 开启）")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["ambient_attention_loop"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"常驻注意力循环启动失败(非致命): {e}")

    # ====================================================================
    # 15a-2. Home Assistant 桥（Matter 阶段0:设备镜像 + 事件流上行）
    # ====================================================================
    # 把 HA 里的智能设备(含经 HA 配网的 Matter 设备)镜像进统一设备模型,
    # 并订阅 state_changed 事件流喂状态事件总线。仅在 HOME_ASSISTANT_URL
    # + HOME_ASSISTANT_TOKEN 配置齐时启动(GALAXY_HA_BRIDGE=0 可关),
    # 未配置零影响。下行控制走既有 Node_27 HA REST。
    try:
        from core.ha_bridge import get_ha_bridge, ha_bridge_enabled

        if ha_bridge_enabled():
            _ha_info = await get_ha_bridge().start()
            results["ha_bridge"] = {"status": "ok", **_ha_info}
            logger.info("HA 桥已启动(镜像 %s 个实体,事件流上行)", _ha_info.get("mirrored"))
        else:
            results["ha_bridge"] = {"status": "disabled"}
    except Exception as e:
        results["ha_bridge"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"HA 桥启动失败(非致命): {e}")

    # ====================================================================
    # 15a-3. LAN mDNS 发现（Matter 阶段1:_matter._tcp 等服务浏览进 UDM）
    # ====================================================================
    # Node_71 发现栈的接线落地版:多服务类型 mDNS 浏览(自家 _galaxy._tcp +
    # Matter/_hap/_googlecast),发现即镜像进统一设备模型并发 DEVICE_UPDATED。
    # zeroconf 缺失或 GALAXY_LAN_DISCOVERY=0 时优雅跳过。
    try:
        from core.lan_discovery import get_lan_discovery, lan_discovery_enabled

        if lan_discovery_enabled():
            _lan_info = get_lan_discovery().start()
            results["lan_discovery"] = {"status": "ok", **_lan_info}
            logger.info("LAN mDNS 发现已启动")
        else:
            results["lan_discovery"] = {"status": "disabled"}
    except Exception as e:
        results["lan_discovery"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"LAN mDNS 发现启动失败(非致命): {e}")

    # ====================================================================
    # 15b. MCP Bridge（外部语言 MCP 服务器桥接）
    # ====================================================================
    try:
        from mcp_bridge.bridge import MCPBridgeLoader

        mcp_bridge = MCPBridgeLoader.get_instance()
        # Bridge loader is ready; actual servers are loaded on-demand or via config.
        # Log availability so operators know the bridge subsystem is active.
        results["mcp_bridge"] = {"status": "ok", "servers": len(mcp_bridge.list_servers())}
        logger.info("MCP Bridge started successfully")
    except ImportError:
        logger.debug("mcp_bridge package not available — skipping")
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["mcp_bridge"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"MCP Bridge startup failed (non-fatal): {e}")

    # ====================================================================
    # 16. Galaxy Gateway 挂载（作为子应用）
    # ====================================================================
    try:
        from galaxy_gateway.app import app as gateway_app

        app.mount("/gateway", gateway_app)

        # Starlette 不会为【被挂载的子应用】运行其 lifespan —— 而 galaxy_gateway 的
        # lifespan 负责创建 DeviceManager / WebSocketManager / TaskOrchestrator 并写入
        # gateway_app.state。父应用又是命令式启动、根本没有自己的 lifespan(见
        # unified_launcher 里 FastAPI(...) 无 lifespan 参数),所以子应用 lifespan 永不
        # 触发。后果:/gateway/* 下所有走 Depends(get_device_manager/...) 的 REST 路由,
        # 会因 app.state.X 为 None 被 dependencies._get_state 判定 503 "Service not ready"
        # ——真机可复现的"/gateway/* 恒 503"。
        # 修复:只补齐【必需的四个核心服务】(dependencies 里会抛 503 的那批),复用
        # lifecycle.init_gateway_core_services()。**刻意不跑完整 lifespan**——完整 lifespan
        # 还会连 NATS、起 TCP/UDP 监听(绑端口)、注册 AIPTransport 适配器、起 MasterBrain
        # 等,这些要么重、要么会与主 app 已启动的同类服务【双绑端口/重复注册】。可选服务
        # (openclawd/llm_router/nats_adapter)缺失时 dependencies 返回 None、不报 503,
        # 所以只补必需项即可精确消除 503,不引入端口冲突。
        # 注:设备 WebSocket(/ws/device/{id})走根路径、由 unified_launcher 独立注册,
        # 不受此影响;本修复只补活 /gateway/* 的 REST 面。
        try:
            from galaxy_gateway.bootstrap.lifecycle import init_gateway_core_services

            (
                _gw_dm,
                _gw_mh,
                _gw_wsm,
                _gw_to,
            ) = await init_gateway_core_services(gateway_app)

            # 到这里【必需核心服务已就绪、/gateway/* 已不再 503】——这才是本修复的实质。
            # 下面注册进程退出时的清理钩子只是【尽力而为】:不同 Starlette/FastAPI 版本
            # 注册 shutdown 的接口不一(部分版本 app.add_event_handler 已被移除,只有
            # app.router.on_shutdown),真机上就因 'FastAPI' object has no attribute
            # 'add_event_handler' 抛错,把明明已修好的网关误报成 degraded。故把钩子注册
            # 单独 try 掉,任何失败都不得回退核心服务"已就绪"的结论。
            def _register_gateway_shutdown() -> None:
                async def _shutdown_gateway_core() -> None:
                    import contextlib as _ctx

                    with _ctx.suppress(Exception):
                        await _gw_to.stop()
                    with _ctx.suppress(Exception):
                        await _gw_wsm.stop()

                if hasattr(app, "add_event_handler"):
                    app.add_event_handler("shutdown", _shutdown_gateway_core)
                elif hasattr(getattr(app, "router", None), "on_shutdown"):
                    app.router.on_shutdown.append(_shutdown_gateway_core)

            try:
                _register_gateway_shutdown()
            except Exception as _she:  # noqa: BLE001
                logger.debug("gateway shutdown 钩子注册跳过(非致命,不影响 /gateway/* 已就绪): %s", _she)

            results["galaxy_gateway"] = {"status": "ok", "core_services": "started"}
            logger.info("Galaxy Gateway 已挂载到 /gateway(必需核心服务已就绪,/gateway/* 不再 503)")
        except Exception as _le:
            # 核心服务启动失败不应阻断整体:挂载仍在,只是 /gateway/* 可能仍 503。
            results["galaxy_gateway"] = {"status": "degraded", "error": str(_le)}
            logger.warning("Galaxy Gateway 已挂载,但核心服务启动失败: %s", _le)
    except Exception as e:
        logger.debug("Fallback triggered: %s", e)
        results["galaxy_gateway"] = {"status": "not_available", "error": str(e)}
        logger.info(f"Galaxy Gateway 未加载: {e}")

    # ── 多设备/Mesh 启用(opt-in,默认关=单机零变化)────────────────────────────
    # 完整 gateway lifespan 被刻意跳过(会绑 TCP/UDP 端口、双注册,见上文)。这里
    # 补上【真正启用 worker/Mesh 但不绑端口】的窄路径:仅当 GALAXY_MASTER_BRAIN_ENABLED
    # 打开(面板"网格"分类的多设备总开关)时——① 起 MasterBrain(连 NATS + 订阅
    # task_results/worker 生命周期,NATS 客户端连接+JetStream 订阅不绑本地监听端口)、
    # ② 起 worker 消费循环(订阅派发 → 规范执行器执行 → 回传结果)。全 best-effort,
    # 任何失败都不阻断启动。默认关时整段跳过,桌面单机行为一字未变。
    try:
        from core.master_brain import get_master_brain, master_brain_enabled

        if master_brain_enabled():
            brain = get_master_brain()
            if brain is not None:
                _mb = await brain.start()
                results["master_brain"] = {
                    "status": "started",
                    "nats_connected": bool((_mb or {}).get("nats_connected")),
                }
                logger.info("MasterBrain 已启用(多设备总开关开)")
            from core.worker_runtime import start_worker_runtime

            _wk = await start_worker_runtime()
            results["worker_runtime"] = _wk
            if _wk.get("started"):
                logger.info("Worker 消费循环已启用 worker_id=%s", _wk.get("worker_id"))
        else:
            results["master_brain"] = {"status": "disabled"}
    except Exception as _mbe:  # noqa: BLE001 — 启用失败不阻断单机启动
        logger.warning("多设备/Mesh 启用失败(单机不受影响): %s", _mbe)
        results["master_brain"] = {"status": "error", "error": str(_mbe)}

    # ====================================================================
    # 17. 设备路由器
    # ====================================================================
    if _deps_ok("device_router"):
        try:
            results["device_router"] = {"status": "ok", "instance": "device_router"}
            logger.info("设备路由器就绪")
        except Exception as e:
            logger.debug("Fallback triggered: %s", e)
            results["device_router"] = {"status": "degraded", "error": str(e)}
            logger.warning(f"设备路由器降级: {e}")

    # ====================================================================
    # 18. 编排器
    # ====================================================================
    if _deps_ok("orchestrator"):
        try:
            results["orchestrator"] = {"status": "ok"}
            logger.info("GalaxyOrchestrator 就绪")
        except Exception as e:
            logger.debug("Fallback triggered: %s", e)
            results["orchestrator"] = {"status": "degraded", "error": str(e)}
            logger.warning(f"编排器降级: {e}")

    # ====================================================================
    # 19. 持久化审计存储挂载（Durable Audit Store wiring）
    # Attach the process-level DurableAuditStore to ReplayFoundation,
    # CanonicalSessionTruthRuntime, and AuditEventSemantics so that all
    # key runtime paths emit durable audit evidence across process lifetimes.
    # The store is observational only; it does NOT alter runtime authority.
    # ====================================================================
    results["durable_audit_store"] = wire_durable_audit_store()
    if results["durable_audit_store"]["status"] == "ok":
        logger.info(
            "持久化审计存储已挂载: path=%s truth_wired=%s",
            results["durable_audit_store"].get("store_path"),
            results["durable_audit_store"].get("canonical_truth_wired"),
        )
    else:
        logger.warning(
            "持久化审计存储挂载失败（降级到内存 ring buffer）: %s",
            results["durable_audit_store"].get("error"),
        )

    # ====================================================================
    # 19b. Session truth snapshot store 挂载与恢复
    # Wire the SessionTruthSnapshotStore to CanonicalSessionTruthRuntime and
    # reload the most recent session truth records from the snapshot file.
    # This is the default-on durable session truth recovery path: V2 restart
    # no longer loses all session truth context.
    # ====================================================================
    try:
        from core.canonical_session_truth import get_canonical_session_truth_runtime
        from core.session_truth_snapshot import (
            get_session_truth_snapshot_store,
            restore_session_truth_from_snapshot,
        )

        _stt_store = get_session_truth_snapshot_store()
        get_canonical_session_truth_runtime().set_snapshot_store(_stt_store)
        _stt_restored = restore_session_truth_from_snapshot(store=_stt_store)
        results["session_truth_snapshot"] = {
            "status": "ok",
            "store_path": _stt_store.store_path,
            "restored_records": _stt_restored,
        }
        logger.info(
            "Session truth 快照存储已挂载: path=%s restored=%d",
            _stt_store.store_path,
            _stt_restored,
        )
    except Exception as _exc:
        logger.debug("Fallback triggered: %s", _exc)
        results["session_truth_snapshot"] = {"status": "degraded", "error": str(_exc)}
        logger.warning("Session truth 快照存储挂载失败（降级）: %s", _exc)

    # ====================================================================
    # 20. 启动恢复（Runtime Restart Recovery）
    # Run the canonical RuntimeRestartRecoveryCoordinator so that durable
    # lifecycle state — BodyMeshRegistry, hybrid orchestration continuity,
    # and in-flight task lifecycle records — is recovered before the
    # runtime begins processing new work.  This step is default-on and
    # runs unconditionally; individual recovery sub-steps degrade
    # gracefully when their backing stores are absent.
    # ====================================================================
    try:
        from core.runtime_restart_recovery import run_startup_recovery

        _recovery_report = run_startup_recovery()
        results["startup_recovery"] = {
            "status": "ok",
            "recovery_id": _recovery_report.recovery_id,
            "mesh_sessions_recovered": _recovery_report.mesh_sessions_recovered,
            "body_mesh_entries_restored": _recovery_report.body_mesh_entries_restored,
            "inflight_tasks_recovered": _recovery_report.inflight_tasks_recovered,
            "inflight_tasks_resumable": _recovery_report.inflight_tasks_resumable,
            "has_errors": _recovery_report.has_errors,
        }
        if _recovery_report.has_errors:
            logger.warning(
                "启动恢复完成（含错误）: recovery_id=%s errors=%s",
                _recovery_report.recovery_id,
                list(_recovery_report.errors),
            )
        else:
            logger.info(
                "启动恢复完成: recovery_id=%s mesh=%d body=%d inflight=%d(resumable=%d)",
                _recovery_report.recovery_id,
                _recovery_report.mesh_sessions_recovered,
                _recovery_report.body_mesh_entries_restored,
                _recovery_report.inflight_tasks_recovered,
                _recovery_report.inflight_tasks_resumable,
            )
    except Exception as _exc:
        logger.debug("Fallback triggered: %s", _exc)
        results["startup_recovery"] = {"status": "degraded", "error": str(_exc)}
        logger.warning("启动恢复跳过（降级）: %s", _exc)

    # ====================================================================
    # 21. 持久化结果幂等性存储初始化（Durable Result Idempotency Store）
    # Eagerly initialise the durable result-ID dedup store so that
    # duplicate result handling is safe immediately after startup.
    # ====================================================================
    try:
        from core.durable_result_idempotency import get_durable_result_id_store

        _rid_store = get_durable_result_id_store()
        results["durable_result_idempotency"] = {
            "status": "ok",
            "store_path": _rid_store.store_path,
            "loaded_count": _rid_store.size(),
        }
        logger.info(
            "持久化结果幂等性存储已初始化: path=%s loaded=%d",
            _rid_store.store_path,
            _rid_store.size(),
        )
    except Exception as _exc:
        logger.debug("Fallback triggered: %s", _exc)
        results["durable_result_idempotency"] = {"status": "degraded", "error": str(_exc)}
        logger.warning("持久化结果幂等性存储初始化失败（降级）: %s", _exc)

    # ====================================================================
    # 汇总
    # ====================================================================
    elapsed = time.monotonic() - t0
    ok_count = sum(1 for v in results.values() if v.get("status") == "ok")
    degraded_count = sum(1 for v in results.values() if v.get("status") == "degraded")
    skipped_count = sum(1 for v in results.values() if v.get("status") == "skipped")
    total = len(results)
    logger.info(
        f"子系统启动完成: {ok_count}/{total} 正常, "
        f"{degraded_count} 降级, {skipped_count} 跳过, "
        f"耗时 {elapsed:.2f}s"
    )

    # 记录失败/降级的子系统以便运维排查
    for name, result in results.items():
        if name.startswith("_"):
            continue
        status = result.get("status")
        if status in ("degraded", "skipped", "error"):
            logger.warning(f"  ⚠ {name}: {status} - {result.get('error', result.get('reason', ''))}")

    # 结构化启动摘要（便于 ELK/Loki 等日志系统收集）
    import json as _json

    startup_summary = {
        "event": "bootstrap_complete",
        "elapsed_s": round(elapsed, 3),
        "ok": ok_count,
        "degraded": degraded_count,
        "skipped": skipped_count,
        "total": total,
        "subsystems": {k: v.get("status", "unknown") for k, v in results.items() if not k.startswith("_")},
    }
    logger.info(f"STARTUP_SUMMARY: {_json.dumps(startup_summary, ensure_ascii=False)}")

    return results


async def _shutdown_with_timeout(name: str, coro, timeout: float = 5.0):
    """带超时的子系统关闭"""
    try:
        await asyncio.wait_for(coro, timeout=timeout)
        logger.info(f"{name}已停止")
    except asyncio.TimeoutError:
        logger.warning(f"{name}关闭超时 ({timeout}s)")
    except Exception as e:
        logger.warning(f"{name}关闭失败: {e}")


async def shutdown_subsystems():
    """
    优雅关闭所有核心子系统

    调用顺序与启动相反。每个子系统最多等待 5 秒。
    """
    logger.info("开始关闭核心子系统...")
    t0 = time.monotonic()

    # 0. Agent 清理循环
    try:
        from core.agent_factory import get_agent_factory

        factory = get_agent_factory()
        await _shutdown_with_timeout("Agent 清理循环", factory.stop_cleanup_loop())
        factory._persist_state()  # 关闭前持久化状态
    except Exception as e:
        logger.warning(f"Agent 系统关闭失败: {e}")

    # 0-pre. 在关闭任何子系统前，持久化任务生命周期快照
    # This must happen before any subsystem stops so that inflight task state
    # captured in the registry is snapshotted while it is still valid.
    try:
        from core.task_envelope_lifecycle_registry import get_lifecycle_registry

        _registry = get_lifecycle_registry()
        _saved = _registry.persist_snapshot()
        if _saved:
            logger.info("任务生命周期快照已持久化（关闭前）")
        else:
            logger.warning("任务生命周期快照持久化失败（关闭前）")
    except Exception as e:
        logger.warning(f"任务生命周期快照持久化失败: {e}")

    # 0-worker. Worker 消费循环(融合·域7:此前 start_worker_runtime 在 bootstrap
    # 里启动却从未被本函数停止——NATS 订阅/后台任务在关机时泄漏,循环生命周期
    # 不对称。仅 mesh opt-in 启用时才在跑;stop() 对未启动实例是安全空操作)。
    try:
        from core.worker_runtime import get_worker_runtime

        _wk_rt = get_worker_runtime()
        if getattr(_wk_rt, "running", False):
            await _shutdown_with_timeout("Worker 消费循环", _wk_rt.stop())
    except Exception as e:
        logger.warning(f"Worker 消费循环停止失败: {e}")

    # 0a. 健康检查整合层
    try:
        from core.health_integration import get_unified_health_manager

        uhm = get_unified_health_manager()
        await _shutdown_with_timeout("健康检查整合层", uhm.stop())
    except Exception as e:
        logger.warning(f"健康检查整合层停止失败: {e}")

    # 0a-1. 系统负载后台采样循环（bootstrap_subsystems 里启动，uhm.stop() 不管它）
    try:
        from core.system_load_monitor import get_monitor as get_load_monitor

        await _shutdown_with_timeout("系统负载采样循环", get_load_monitor().stop_monitoring())
    except Exception as e:
        logger.warning(f"系统负载采样循环停止失败: {e}")

    # 0a-2. 常驻注意力循环（bootstrap 15a 里启动，需在关闭序列显式停掉后台任务）
    try:
        from core.ambient_attention_loop import get_ambient_loop

        await _shutdown_with_timeout("常驻注意力循环", get_ambient_loop().stop())
    except Exception as e:
        logger.warning(f"常驻注意力循环停止失败: {e}")

    # 0a-3. HA 桥（bootstrap 15a-2 里启动，事件流后台任务需显式停）
    try:
        from core.ha_bridge import get_ha_bridge

        await _shutdown_with_timeout("HA 桥", get_ha_bridge().stop())
    except Exception as e:
        logger.warning(f"HA 桥停止失败: {e}")

    # 0a-4. LAN mDNS 发现（bootstrap 15a-3 里启动;同步 close,不需 await）
    try:
        from core.lan_discovery import get_lan_discovery

        get_lan_discovery().stop()
    except Exception as e:
        logger.warning(f"LAN mDNS 发现停止失败: {e}")

    # 0b. 节点发现服务
    try:
        from core.node_discovery import get_node_discovery

        discovery = get_node_discovery()
        await _shutdown_with_timeout("节点发现服务", discovery.stop())
    except Exception as e:
        logger.warning(f"节点发现服务停止失败: {e}")

    # 0c. 数字孪生引擎
    try:
        from core.digital_twin_engine import get_digital_twin_engine

        twin_engine = get_digital_twin_engine()
        await _shutdown_with_timeout("数字孪生引擎", twin_engine.shutdown())
    except Exception as e:
        logger.warning(f"数字孪生引擎关闭失败: {e}")

    # 0d. LLM 路由器
    try:
        from core.multi_llm_router import get_llm_router

        router = get_llm_router()
        await _shutdown_with_timeout("LLM 路由器", router.close())
    except Exception as e:
        logger.warning(f"LLM 路由器关闭失败: {e}")

    # 1. 事件桥接
    try:
        from core.event_bridge import get_event_bridge

        bridge = get_event_bridge()
        await _shutdown_with_timeout("事件桥接", bridge.shutdown())
    except Exception as e:
        logger.warning(f"事件桥接关闭失败: {e}")

    # 2. 命令路由清理
    try:
        from core.command_router import get_command_router

        cmd_router = get_command_router()
        await _shutdown_with_timeout("命令路由", cmd_router.cleanup(max_age_seconds=0))
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    # 3. 监控系统
    try:
        from core.monitoring import get_monitoring_manager

        monitoring = get_monitoring_manager()
        await _shutdown_with_timeout("监控系统", monitoring.stop())
    except Exception as e:
        logger.warning(f"监控系统关闭失败: {e}")

    # 3b. 并发管理器
    try:
        from core.concurrency_manager import get_concurrency_manager

        concurrency = get_concurrency_manager()
        await _shutdown_with_timeout("并发管理器", concurrency.stop())
    except Exception as e:
        logger.warning(f"并发管理器停止失败: {e}")

    # 3c. 配置热更新管理器
    try:
        from core.config_hot_reload import get_config_manager

        config_mgr = get_config_manager()
        await _shutdown_with_timeout("配置热更新", config_mgr.stop_watching())
    except Exception as e:
        logger.warning(f"配置热更新停止失败: {e}")

    # 4. 缓存
    try:
        import core.cache as _cache_mod

        instance = getattr(_cache_mod, "_cache_instance", None)
        if instance:
            await _shutdown_with_timeout("缓存连接", instance.close())
    except Exception as e:
        logger.warning(f"缓存关闭失败: {e}")

    elapsed = time.monotonic() - t0
    logger.info(f"核心子系统已全部关闭 (耗时 {elapsed:.2f}s)")
