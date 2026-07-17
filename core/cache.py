"""
Galaxy - 缓存层
====================

提供统一的缓存接口，支持 Redis 后端和内存降级。
用于节点状态缓存、会话缓存、任务队列等。
"""

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.Cache")


class MemoryCache:
    """内存缓存实现（Redis 不可用时的降级方案）"""

    def __init__(self):
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[str]:
        async with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            if item["expires_at"] and time.time() > item["expires_at"]:
                del self._store[key]
                return None
            return item["value"]

    async def set(self, key: str, value: str, ttl: Optional[int] = None):
        async with self._lock:
            self._store[key] = {
                "value": value,
                "expires_at": time.time() + ttl if ttl else None,
                "created_at": time.time(),
            }

    async def delete(self, key: str) -> bool:
        async with self._lock:
            return self._store.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        result = await self.get(key)
        return result is not None

    async def keys(self, pattern: str = "*") -> list:
        """简单的模式匹配（仅支持前缀匹配 prefix*）"""
        async with self._lock:
            now = time.time()
            if pattern == "*":
                return [k for k, v in self._store.items() if not v["expires_at"] or now <= v["expires_at"]]
            prefix = pattern.rstrip("*")
            return [
                k
                for k, v in self._store.items()
                if k.startswith(prefix) and (not v["expires_at"] or now <= v["expires_at"])
            ]

    async def flush(self):
        async with self._lock:
            self._store.clear()

    async def info(self) -> Dict[str, Any]:
        async with self._lock:
            now = time.time()
            active = sum(1 for v in self._store.values() if not v["expires_at"] or now <= v["expires_at"])
            return {
                "backend": "memory",
                "total_keys": len(self._store),
                "active_keys": active,
            }

    async def close(self):
        pass


class RedisCache:
    """Redis 缓存实现"""

    def __init__(self, url: str = "redis://localhost:6379"):
        self.url = url
        self._redis = None

    async def connect(self):
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                self.url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
            )
            await self._redis.ping()
            logger.info(f"Redis 已连接: {self.url}")
            return True
        except Exception as e:
            # Redis 在桌面单机模式是可选项:连不上会安静降级到内存缓存(见
            # CacheManager.initialize)。用 info 陈述,不用 warning 吓人。
            logger.info("Redis 未连接(降级到内存缓存,桌面单机属正常): %s", e)
            self._redis = None
            return False

    async def get(self, key: str) -> Optional[str]:
        if not self._redis:
            return None
        try:
            return await self._redis.get(key)
        except Exception as e:
            logger.error(f"Redis GET 失败: {e}")
            return None

    async def set(self, key: str, value: str, ttl: Optional[int] = None):
        if not self._redis:
            return
        try:
            if ttl:
                await self._redis.setex(key, ttl, value)
            else:
                await self._redis.set(key, value)
        except Exception as e:
            logger.error(f"Redis SET 失败: {e}")

    async def delete(self, key: str) -> bool:
        if not self._redis:
            return False
        try:
            return bool(await self._redis.delete(key))
        except Exception:
            return False

    async def exists(self, key: str) -> bool:
        if not self._redis:
            return False
        try:
            return bool(await self._redis.exists(key))
        except Exception:
            return False

    async def keys(self, pattern: str = "*") -> list:
        if not self._redis:
            return []
        try:
            return await self._redis.keys(pattern)
        except Exception:
            return []

    async def flush(self):
        if self._redis:
            try:
                await self._redis.flushdb()
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

    async def info(self) -> Dict[str, Any]:
        if not self._redis:
            return {"backend": "redis", "connected": False}
        try:
            info = await self._redis.info("memory")
            return {
                "backend": "redis",
                "connected": True,
                "used_memory_human": info.get("used_memory_human", ""),
                "connected_clients": info.get("connected_clients", 0),
            }
        except Exception:
            return {"backend": "redis", "connected": False}

    async def close(self):
        if self._redis:
            await self._redis.close()


class CacheManager:
    """
    统一缓存管理器

    自动检测 Redis 可用性，不可用时降级到内存缓存。
    提供 JSON 序列化的高级接口。
    """

    def __init__(self, redis_url: str = ""):
        self.redis_url = redis_url
        self._backend: Any = None
        self._is_redis = False

    async def initialize(self) -> str:
        """初始化缓存后端，返回后端类型"""
        url = (self.redis_url or "").strip()
        if url:
            # 容错:允许 .env 里只写 host:port(如 REDIS_HOST/REDIS_PORT 拼出的
            # "localhost:6379")而漏掉 scheme —— 否则 aioredis.from_url 会直接抛
            # "Redis URL must specify one of the following schemes"。补默认
            # redis:// 再连。真机复现过此告警,根因即 .env 里 REDIS_URL 半配置。
            if "://" not in url:
                url = "redis://" + url
            redis_cache = RedisCache(url)
            if await redis_cache.connect():
                self._backend = redis_cache
                self._is_redis = True
                return "redis"

        # 降级到内存缓存
        self._backend = MemoryCache()
        self._is_redis = False
        logger.info("使用内存缓存（Redis 不可用或未配置）")
        return "memory"

    @property
    def backend_type(self) -> str:
        return "redis" if self._is_redis else "memory"

    # --- 基础操作 ---

    async def get(self, key: str) -> Optional[str]:
        return await self._backend.get(key)

    async def set(self, key: str, value: str, ttl: Optional[int] = None):
        await self._backend.set(key, value, ttl)

    async def delete(self, key: str) -> bool:
        return await self._backend.delete(key)

    # --- JSON 高级接口 ---

    async def get_json(self, key: str) -> Optional[Any]:
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw

    async def set_json(self, key: str, value: Any, ttl: Optional[int] = None):
        await self.set(key, json.dumps(value, ensure_ascii=False), ttl)

    # --- 节点状态缓存 ---

    async def cache_node_status(self, node_id: str, status: Dict[str, Any]):
        await self.set_json(f"node:{node_id}:status", status, ttl=300)

    async def get_node_status(self, node_id: str) -> Optional[Dict]:
        return await self.get_json(f"node:{node_id}:status")

    async def get_all_node_statuses(self) -> Dict[str, Any]:
        keys = await self._backend.keys("node:*:status")
        result = {}
        for key in keys:
            node_id = key.split(":")[1]
            status = await self.get_json(key)
            if status:
                result[node_id] = status
        return result

    # --- 会话缓存 ---

    async def cache_session(self, session_id: str, data: Dict[str, Any], ttl: int = 3600):
        await self.set_json(f"session:{session_id}", data, ttl)

    async def get_session(self, session_id: str) -> Optional[Dict]:
        return await self.get_json(f"session:{session_id}")

    # --- 信息 ---

    async def info(self) -> Dict[str, Any]:
        return await self._backend.info()

    async def close(self):
        await self._backend.close()


# 全局缓存实例
_cache_instance: Optional[CacheManager] = None


_cache_init_lock: Optional[asyncio.Lock] = None


async def get_cache(redis_url: str = "") -> CacheManager:
    """获取全局缓存实例。

    修复竞态:原来先把实例发布到全局、再 await initialize()——并发首调时
    另一个协程会拿到【未初始化】的实例直接用。现在初始化完成后才发布,
    并用 asyncio.Lock 防止并发双初始化。
    """
    global _cache_instance, _cache_init_lock
    if _cache_instance is not None:
        return _cache_instance
    if _cache_init_lock is None:
        _cache_init_lock = asyncio.Lock()
    async with _cache_init_lock:
        if _cache_instance is None:
            candidate = CacheManager(redis_url)
            backend = await candidate.initialize()
            logger.info(f"缓存已初始化: {backend}")
            _cache_instance = candidate
    return _cache_instance
