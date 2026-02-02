"""
Stale Lock Reaper for Node 00: State Machine
过期锁清理器 - 防止系统死锁

功能：
1. 每 60 秒扫描一次所有锁
2. 如果锁持有时间超过 300 秒（5 分钟），自动删除
3. 记录清理日志到 Node 65
4. 支持 Redis 和内存存储两种模式
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

class StaleLockReaper:
    """过期锁清理器"""
    
    def __init__(
        self,
        store,  # MemoryStore 实例
        scan_interval: int = 60,  # 扫描间隔（秒）
        max_lock_age: int = 300,  # 最大锁持有时间（秒）
        audit_log_url: Optional[str] = "http://localhost:8065/log"
    ):
        self.store = store
        self.scan_interval = scan_interval
        self.max_lock_age = max_lock_age
        self.audit_log_url = audit_log_url
        self.running = False
        self.http_client = httpx.AsyncClient(timeout=5)
        
        # 统计信息
        self.stats = {
            "total_scans": 0,
            "locks_reaped": 0,
            "last_scan_time": None,
            "last_reap_time": None
        }
    
    async def start(self):
        """启动清理器"""
        if self.running:
            logger.warning("Stale Lock Reaper already running")
            return
        
        self.running = True
        logger.info(f"Starting Stale Lock Reaper (scan_interval={self.scan_interval}s, max_age={self.max_lock_age}s)")
        
        asyncio.create_task(self._reaper_loop())
    
    async def stop(self):
        """停止清理器"""
        self.running = False
        await self.http_client.aclose()
        logger.info("Stale Lock Reaper stopped")
    
    async def _reaper_loop(self):
        """清理循环"""
        while self.running:
            try:
                await self._scan_and_reap()
                await asyncio.sleep(self.scan_interval)
            except Exception as e:
                logger.error(f"Error in reaper loop: {e}")
                await asyncio.sleep(self.scan_interval)
    
    async def _scan_and_reap(self):
        """扫描并清理过期锁"""
        self.stats["total_scans"] += 1
        self.stats["last_scan_time"] = datetime.now().isoformat()
        
        now = datetime.now()
        stale_locks: List[Dict] = []
        
        # 扫描所有锁
        async with self.store._lock:
            for resource_id, lock in list(self.store.locks.items()):
                try:
                    acquired_at = datetime.fromisoformat(lock["acquired_at"])
                    age_seconds = (now - acquired_at).total_seconds()
                    
                    # 检查是否过期
                    if age_seconds > self.max_lock_age:
                        stale_locks.append({
                            "resource_id": resource_id,
                            "node_id": lock["node_id"],
                            "acquired_at": lock["acquired_at"],
                            "age_seconds": age_seconds,
                            "token": lock["token"]
                        })
                        
                        # 删除过期锁
                        del self.store.locks[resource_id]
                        logger.warning(
                            f"Reaped stale lock: resource={resource_id}, "
                            f"node={lock['node_id']}, age={age_seconds:.1f}s"
                        )
                        
                except Exception as e:
                    logger.error(f"Error processing lock {resource_id}: {e}")
        
        # 更新统计
        if stale_locks:
            self.stats["locks_reaped"] += len(stale_locks)
            self.stats["last_reap_time"] = datetime.now().isoformat()
            
            # 发送审计日志
            await self._send_audit_logs(stale_locks)
    
    async def _send_audit_logs(self, stale_locks: List[Dict]):
        """发送审计日志到 Node 65"""
        if not self.audit_log_url:
            return
        
        for lock in stale_locks:
            try:
                log_entry = {
                    "node_id": "Node_00_StateMachine",
                    "action": "stale_lock_reaped",
                    "session_id": "reaper",
                    "resource": lock["resource_id"],
                    "caller": "StaleLockReaper",
                    "parameters": {
                        "original_node": lock["node_id"],
                        "acquired_at": lock["acquired_at"],
                        "age_seconds": lock["age_seconds"],
                        "max_age": self.max_lock_age
                    },
                    "result": {
                        "status": "reaped",
                        "reason": "exceeded_max_age"
                    },
                    "latency_ms": 0,
                    "level": "warning",
                    "category": "system"
                }
                
                response = await self.http_client.post(
                    self.audit_log_url,
                    json=log_entry
                )
                
                if response.status_code != 200:
                    logger.error(f"Failed to send audit log: {response.status_code}")
                    
            except Exception as e:
                logger.error(f"Error sending audit log: {e}")
    
    def get_stats(self) -> Dict:
        """获取统计信息"""
        return {
            **self.stats,
            "running": self.running,
            "scan_interval": self.scan_interval,
            "max_lock_age": self.max_lock_age
        }
    
    async def force_scan(self) -> Dict:
        """强制执行一次扫描"""
        logger.info("Force scan triggered")
        await self._scan_and_reap()
        return self.get_stats()


# =============================================================================
# 集成到 Node 00 的辅助函数
# =============================================================================

def integrate_reaper(app, store):
    """
    将 Stale Lock Reaper 集成到 FastAPI 应用
    
    使用方法：
    在 Node 00 的 main.py 中添加：
    
    from stale_lock_reaper import integrate_reaper
    
    # 在 lifespan 函数中
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # 现有的启动代码...
        
        # 启动 Reaper
        from stale_lock_reaper import integrate_reaper
        reaper = integrate_reaper(app, store)
        await reaper.start()
        
        yield
        
        # 停止 Reaper
        await reaper.stop()
    """
    
    # 创建 Reaper 实例
    reaper = StaleLockReaper(
        store=store,
        scan_interval=60,  # 每 60 秒扫描一次
        max_lock_age=300,  # 锁最多持有 300 秒
        audit_log_url="http://localhost:8065/log"
    )
    
    # 添加 API 端点
    @app.get("/reaper/stats")
    async def get_reaper_stats():
        """获取 Reaper 统计信息"""
        return reaper.get_stats()
    
    @app.post("/reaper/scan")
    async def force_reaper_scan():
        """强制执行一次扫描"""
        return await reaper.force_scan()
    
    return reaper


# =============================================================================
# 独立运行模式（用于测试）
# =============================================================================

if __name__ == "__main__":
    import sys
    
    # 模拟 MemoryStore
    class MockStore:
        def __init__(self):
            self.locks = {}
            self._lock = asyncio.Lock()
    
    async def test_reaper():
        """测试 Reaper"""
        store = MockStore()
        
        # 添加一些测试锁
        now = datetime.now()
        store.locks["test_lock_1"] = {
            "node_id": "Node_33_ADB",
            "token": "test-token-1",
            "acquired_at": (now - timedelta(seconds=400)).isoformat(),
            "expires_at": (now + timedelta(seconds=100)).isoformat()
        }
        store.locks["test_lock_2"] = {
            "node_id": "Node_50_Transformer",
            "token": "test-token-2",
            "acquired_at": (now - timedelta(seconds=100)).isoformat(),
            "expires_at": (now + timedelta(seconds=200)).isoformat()
        }
        
        print(f"Initial locks: {len(store.locks)}")
        
        # 创建 Reaper
        reaper = StaleLockReaper(
            store=store,
            scan_interval=5,
            max_lock_age=300,
            audit_log_url=None  # 测试时不发送审计日志
        )
        
        # 启动 Reaper
        await reaper.start()
        
        # 等待一次扫描
        await asyncio.sleep(6)
        
        print(f"Locks after scan: {len(store.locks)}")
        print(f"Stats: {reaper.get_stats()}")
        
        # 停止 Reaper
        await reaper.stop()
    
    # 运行测试
    asyncio.run(test_reaper())
