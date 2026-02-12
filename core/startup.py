"""
UFO Galaxy - 系统启动引导
==========================

统一初始化所有核心子系统，供 unified_launcher.py 调用。

初始化顺序：
  1. 缓存层（Redis / 内存降级）
  2. 监控系统（健康检查、告警、指标）
  3. 性能中间件（压缩、限流、缓存、计时）
  4. 命令路由引擎
  5. AI 意图引擎（解析器、记忆、推荐）

所有模块均支持优雅降级：缺少 Redis → 内存缓存，缺少 LLM → 规则引擎。
"""

import asyncio
import logging
import os
from typing import Any, Optional

from fastapi import FastAPI

logger = logging.getLogger("UFO-Galaxy.Startup")


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

        # 注册 Redis 连接检查
        if cache and cache.backend_type == "redis":
            monitoring.health.register_check("redis", lambda: {"status": "healthy", "type": "redis"})

        await monitoring.start()
        results["monitoring"] = {"status": "ok"}
        logger.info("监控系统已启动")
    except Exception as e:
        results["monitoring"] = {"status": "degraded", "error": str(e)}
        logger.warning(f"监控系统启动失败: {e}")

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

        # 3a. API 响应缓存（最接近 Handler）
        if cache:
            default_ttl = int(os.environ.get("REDIS_HTTP_CACHE_TTL", "30"))
            app.add_middleware(CachingMiddleware, cache_backend=cache, default_ttl=default_ttl)
            logger.info("API 缓存中间件已加载")

        # 3b. 响应压缩
        min_size = int(os.environ.get("GZIP_MIN_SIZE", "1024"))
        app.add_middleware(ResponseCompressor, min_size=min_size)
        logger.info("gzip 压缩中间件已加载")

        # 3c. 限流
        max_req = int(os.environ.get("RATE_LIMIT_MAX_REQUESTS", "200"))
        window = int(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))
        app.add_middleware(RateLimitMiddleware, max_requests=max_req, window_seconds=window)
        logger.info(f"限流中间件已加载: {max_req} req / {window}s")

        # 3d. 请求计时（最先执行）
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
    # 汇总
    # ====================================================================
    ok_count = sum(1 for v in results.values() if v.get("status") == "ok")
    total = len(results)
    logger.info(f"子系统启动完成: {ok_count}/{total} 正常")

    return results
