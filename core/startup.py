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
from typing import Any, Optional

from fastapi import FastAPI

logger = logging.getLogger("Galaxy.Startup")


async def bootstrap_subsystems(app: FastAPI, config: Any = None) -> dict:
    """
    启动所有核心子系统并挂载中间件

    Args:
        app: FastAPI 应用实例
        config: SystemConfig 或 None

    Returns:
        各子系统的初始化结果
    """
    results = {}

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
        results["monitoring"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"监控系统启动失败: {e}")

    # ====================================================================
    # 2b. 统一错误处理框架
    # ====================================================================
    error_tracker = None
    try:
        from core.error_framework import get_error_tracker, create_error_handlers

        error_tracker = get_error_tracker()
        create_error_handlers(app)
        results["error_framework"] = {"status": "ok"}
        logger.info("统一错误处理框架已初始化")
    except Exception as e:
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
        results["concurrency_manager"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"并发管理器启动失败: {e}")

    # ====================================================================
    # 2d. 配置热更新管理器
    # ====================================================================
    try:
        from core.config_hot_reload import get_config_manager

        config_path = os.environ.get(
            "Galaxy_CONFIG_PATH",
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
        results["config_hot_reload"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"配置热更新管理器启动失败: {e}")

    # ====================================================================
    # 2e. 安全中间件
    # ====================================================================
    try:
        from core.security_middleware import get_security_manager

        security_mgr = get_security_manager()
        security_mgr.setup_middleware(app)
        results["security_middleware"] = {"status": "ok"}
        logger.info("安全中间件已安装 (审计日志 + 安全头 + IP 黑名单)")
    except Exception as e:
        results["security_middleware"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"安全中间件安装失败: {e}")

    # ====================================================================
    # 3. 性能中间件链
    # ====================================================================
    try:
        from core.performance import (
            RequestTimerMiddleware,
            RateLimitMiddleware,
            ResponseCompressor,
            CachingMiddleware,
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
        results["command_router"] = {"status": "ok"}
        logger.info("命令路由引擎已初始化")
    except Exception as e:
        results["command_router"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"命令路由引擎初始化失败: {e}")

    # ====================================================================
    # 5. AI 意图引擎
    # ====================================================================
    try:
        from core.ai_intent import (
            get_intent_parser, get_conversation_memory, get_smart_recommender,
        )

        intent_parser = get_intent_parser()
        memory = get_conversation_memory(cache_backend=cache)
        recommender = get_smart_recommender(memory=memory)

        results["ai_intent"] = {"status": "ok"}
        logger.info("AI 意图引擎已初始化")
    except Exception as e:
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
        except Exception:
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
            f"多 LLM 路由器已初始化: "
            f"{status['total_providers']} 提供商, "
            f"{status['healthy_providers']} 可用"
        )
    except Exception as e:
        results["llm_router"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"多 LLM 路由器初始化失败: {e}")

    # ====================================================================
    # 9. 动态 Agent 工厂 + 分形执行器
    # ====================================================================
    try:
        from core.agent_factory import get_agent_factory
        from core.fractal_agent import get_fractal_executor

        agent_factory = get_agent_factory(llm_router=llm_router)
        fractal_executor = get_fractal_executor(
            llm_router=llm_router, agent_factory=agent_factory
        )
        results["agent_system"] = {"status": "ok", "llm_enabled": llm_router is not None}
        logger.info(
            f"Agent 系统已初始化 (工厂 + 分形执行器, "
            f"LLM: {'启用' if llm_router else '降级'})"
        )
    except Exception as e:
        results["agent_system"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"Agent 系统初始化失败: {e}")

    # ====================================================================
    # 10. 数字孪生引擎
    # ====================================================================
    try:
        from core.digital_twin_engine import get_digital_twin_engine

        twin_engine = get_digital_twin_engine()
        results["digital_twin"] = {"status": "ok"}
        logger.info("数字孪生引擎已初始化")
    except Exception as e:
        results["digital_twin"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"数字孪生引擎初始化失败: {e}")

    # ====================================================================
    # 11. 三位一体世界模型
    # ====================================================================
    try:
        from enhancements.reasoning.world_model import WorldModel

        world_model = WorldModel()
        results["world_model"] = {"status": "ok", "pillars": ["ontology", "epistemology", "information"]}
        logger.info("三位一体世界模型已初始化 (本体论 + 认知论 + 信息论)")
    except Exception as e:
        results["world_model"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"世界模型初始化失败: {e}")

    # ====================================================================
    # 14. 节点发现服务
    # ====================================================================
    discovery = None
    try:
        from core.node_discovery import get_node_discovery

        node_id = os.environ.get("Galaxy_NODE_ID", "master")
        discovery = get_node_discovery(node_id=node_id)
        await discovery.start()
        results["node_discovery"] = {"status": "ok", "node_id": node_id}
        logger.info(f"节点发现服务已启动: {node_id}")
    except Exception as e:
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
        except Exception:
            pass

        uhm.wire(
            monitoring=_monitoring,
            load_monitor=load_monitor,
            error_tracker=error_tracker,
            concurrency=concurrency_mgr,
            discovery=discovery,
        )
        await uhm.start()
        results["health_integration"] = {"status": "ok"}
        logger.info("健康检查整合层已启动")
    except Exception as e:
        results["health_integration"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"健康检查整合层启动失败: {e}")

    # ====================================================================
    # 16. Galaxy Gateway 挂载（作为子应用）
    # ====================================================================
    try:
        from galaxy_gateway.app import app as gateway_app
        app.mount("/gateway", gateway_app)
        results["galaxy_gateway"] = {"status": "ok"}
        logger.info("Galaxy Gateway 已挂载到 /gateway")
    except Exception as e:
        results["galaxy_gateway"] = {"status": "not_available", "error": str(e)}
        logger.info(f"Galaxy Gateway 未加载: {e}")

    # ====================================================================
    # 汇总
    # ====================================================================
    ok_count = sum(1 for v in results.values() if v.get("status") == "ok")
    total = len(results)
    logger.info(f"子系统启动完成: {ok_count}/{total} 正常")

    return results


async def shutdown_subsystems():
    """
    优雅关闭所有核心子系统

    调用顺序与启动相反。
    """
    logger.info("开始关闭核心子系统...")

    # 0a. 健康检查整合层
    try:
        from core.health_integration import get_unified_health_manager
        uhm = get_unified_health_manager()
        await uhm.stop()
        logger.info("健康检查整合层已停止")
    except Exception as e:
        logger.warning(f"健康检查整合层停止失败: {e}")

    # 0b. 节点发现服务
    try:
        from core.node_discovery import get_node_discovery
        discovery = get_node_discovery()
        await discovery.stop()
        logger.info("节点发现服务已停止")
    except Exception as e:
        logger.warning(f"节点发现服务停止失败: {e}")

    # 0c. 数字孪生引擎
    try:
        from core.digital_twin_engine import get_digital_twin_engine
        twin_engine = get_digital_twin_engine()
        await twin_engine.shutdown()
        logger.info("数字孪生引擎已关闭")
    except Exception as e:
        logger.warning(f"数字孪生引擎关闭失败: {e}")

    # 0b. LLM 路由器
    try:
        from core.multi_llm_router import get_llm_router
        router = get_llm_router()
        await router.close()
        logger.info("LLM 路由器已关闭")
    except Exception as e:
        logger.warning(f"LLM 路由器关闭失败: {e}")

    # 1. 事件桥接
    try:
        from core.event_bridge import get_event_bridge
        bridge = get_event_bridge()
        await bridge.shutdown()
        logger.info("事件桥接已关闭")
    except Exception as e:
        logger.warning(f"事件桥接关闭失败: {e}")

    # 2. 命令路由清理
    try:
        from core.command_router import get_command_router
        router = get_command_router()
        await router.cleanup(max_age_seconds=0)
        logger.info("命令路由已清理")
    except Exception:
        pass

    # 3. 监控系统
    try:
        from core.monitoring import get_monitoring_manager
        monitoring = get_monitoring_manager()
        await monitoring.stop()
        logger.info("监控系统已停止")
    except Exception as e:
        logger.warning(f"监控系统关闭失败: {e}")

    # 3b. 并发管理器
    try:
        from core.concurrency_manager import get_concurrency_manager
        concurrency = get_concurrency_manager()
        await concurrency.stop()
        logger.info("并发管理器已停止")
    except Exception as e:
        logger.warning(f"并发管理器停止失败: {e}")

    # 3c. 配置热更新管理器
    try:
        from core.config_hot_reload import get_config_manager
        config_mgr = get_config_manager()
        await config_mgr.stop_watching()
        logger.info("配置热更新已停止")
    except Exception as e:
        logger.warning(f"配置热更新停止失败: {e}")

    # 4. 缓存
    try:
        from core.cache import get_cache as _get_cache_ref
        # 通过模块级变量安全获取已初始化的实例
        import core.cache as _cache_mod
        instance = getattr(_cache_mod, '_cache_instance', None)
        if instance:
            await instance.close()
            logger.info("缓存连接已关闭")
    except Exception as e:
        logger.warning(f"缓存关闭失败: {e}")

    logger.info("核心子系统已全部关闭")
