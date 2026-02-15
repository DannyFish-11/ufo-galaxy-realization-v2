"""
并发管理器 (ConcurrencyManager)
================================

系统级并发控制，提供：
- 信号量控制：限制全局/每类任务的并发度
- 分布式锁：排他锁 + 共享读写锁
- 死锁检测：基于等待图的环检测
- 资源竞争处理：资源队列 + 公平调度
- 超时与重试：可配置的超时和指数退避
"""

import asyncio
import logging
import time
import uuid
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict

logger = logging.getLogger("UFO-Galaxy.Concurrency")


# ───────────────────── 数据模型 ─────────────────────

class LockType(Enum):
    EXCLUSIVE = "exclusive"
    SHARED = "shared"  # 读锁


class LockState(Enum):
    FREE = "free"
    LOCKED = "locked"
    WAITING = "waiting"


@dataclass
class LockInfo:
    """锁信息"""
    resource_id: str
    lock_type: LockType
    holder_id: str          # 持有者 ID
    acquired_at: float = 0
    timeout: float = 30.0   # 超时秒数
    metadata: Dict = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        return self.acquired_at > 0 and (time.time() - self.acquired_at) > self.timeout


@dataclass
class WaitEntry:
    """等待队列条目"""
    waiter_id: str
    resource_id: str
    lock_type: LockType
    event: asyncio.Event = field(default_factory=asyncio.Event)
    enqueued_at: float = field(default_factory=time.time)
    timeout: float = 30.0


@dataclass
class TaskSlot:
    """并发槽位"""
    task_id: str
    category: str
    started_at: float = field(default_factory=time.time)
    timeout: float = 300.0

    @property
    def is_expired(self) -> bool:
        return (time.time() - self.started_at) > self.timeout


# ───────────────────── 分布式锁管理器 ─────────────────────

class LockManager:
    """
    分布式锁管理器

    支持排他锁和共享锁，带死锁检测。
    """

    def __init__(self):
        self._locks: Dict[str, List[LockInfo]] = {}  # resource → [locks]
        self._wait_queue: Dict[str, List[WaitEntry]] = defaultdict(list)
        self._holder_resources: Dict[str, Set[str]] = defaultdict(set)  # holder → resources
        self._mu = asyncio.Lock()

    async def acquire(self, resource_id: str, holder_id: str,
                      lock_type: LockType = LockType.EXCLUSIVE,
                      timeout: float = 30.0) -> bool:
        """
        获取锁

        Returns: True 如果成功获取
        """
        async with self._mu:
            # 检查是否可以立即获取
            if self._can_acquire(resource_id, lock_type, holder_id):
                self._do_acquire(resource_id, holder_id, lock_type, timeout)
                return True

            # 死锁检测
            if self._would_deadlock(holder_id, resource_id):
                logger.warning(
                    f"[死锁预防] {holder_id} 尝试获取 {resource_id} 会导致死锁，拒绝"
                )
                return False

            # 加入等待队列
            entry = WaitEntry(
                waiter_id=holder_id,
                resource_id=resource_id,
                lock_type=lock_type,
                timeout=timeout,
            )
            self._wait_queue[resource_id].append(entry)

        # 等待（不在 _mu 锁内）
        try:
            await asyncio.wait_for(entry.event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            # 超时，从等待队列移除
            async with self._mu:
                if entry in self._wait_queue.get(resource_id, []):
                    self._wait_queue[resource_id].remove(entry)
            logger.warning(f"锁超时: {holder_id} 等待 {resource_id}")
            return False

    async def release(self, resource_id: str, holder_id: str):
        """释放锁"""
        async with self._mu:
            locks = self._locks.get(resource_id, [])
            self._locks[resource_id] = [
                l for l in locks if l.holder_id != holder_id
            ]
            self._holder_resources[holder_id].discard(resource_id)

            if not self._locks[resource_id]:
                del self._locks[resource_id]

            # 唤醒等待者
            self._wake_waiters(resource_id)

            logger.debug(f"锁已释放: {holder_id} → {resource_id}")

    async def release_all(self, holder_id: str):
        """释放某持有者的所有锁"""
        async with self._mu:
            resources = list(self._holder_resources.get(holder_id, set()))
            for res in resources:
                locks = self._locks.get(res, [])
                self._locks[res] = [l for l in locks if l.holder_id != holder_id]
                if not self._locks.get(res):
                    self._locks.pop(res, None)
                self._wake_waiters(res)
            self._holder_resources.pop(holder_id, None)

    def _can_acquire(self, resource_id: str, lock_type: LockType,
                     holder_id: str) -> bool:
        current_locks = self._locks.get(resource_id, [])
        if not current_locks:
            return True

        # 重入检测
        for l in current_locks:
            if l.holder_id == holder_id:
                return True

        if lock_type == LockType.SHARED:
            # 共享锁：只要没有排他锁就行
            return all(l.lock_type == LockType.SHARED for l in current_locks)

        # 排他锁：必须无锁
        return False

    def _do_acquire(self, resource_id: str, holder_id: str,
                    lock_type: LockType, timeout: float):
        info = LockInfo(
            resource_id=resource_id,
            lock_type=lock_type,
            holder_id=holder_id,
            acquired_at=time.time(),
            timeout=timeout,
        )
        if resource_id not in self._locks:
            self._locks[resource_id] = []
        self._locks[resource_id].append(info)
        self._holder_resources[holder_id].add(resource_id)
        logger.debug(f"锁已获取: {holder_id} → {resource_id} ({lock_type.value})")

    def _wake_waiters(self, resource_id: str):
        waiters = self._wait_queue.get(resource_id, [])
        still_waiting = []
        for entry in waiters:
            if self._can_acquire(resource_id, entry.lock_type, entry.waiter_id):
                self._do_acquire(
                    resource_id, entry.waiter_id,
                    entry.lock_type, entry.timeout,
                )
                entry.event.set()
            else:
                still_waiting.append(entry)
        self._wait_queue[resource_id] = still_waiting

    def _would_deadlock(self, holder_id: str, target_resource: str) -> bool:
        """
        死锁检测：检查 holder_id 等待 target_resource 是否会形成环

        构建等待图 (waiter → holder) 并检测环
        """
        # 构建等待图
        # edge: waiter → holder_of_resource
        graph: Dict[str, Set[str]] = defaultdict(set)

        # 现有等待关系
        for res, waiters in self._wait_queue.items():
            holders = {l.holder_id for l in self._locks.get(res, [])}
            for w in waiters:
                for h in holders:
                    if w.waiter_id != h:
                        graph[w.waiter_id].add(h)

        # 添加新的等待关系
        target_holders = {l.holder_id for l in self._locks.get(target_resource, [])}
        for h in target_holders:
            if holder_id != h:
                graph[holder_id].add(h)

        # DFS 检测环
        visited = set()
        path = set()

        def has_cycle(node: str) -> bool:
            if node in path:
                return True
            if node in visited:
                return False
            visited.add(node)
            path.add(node)
            for neighbor in graph.get(node, set()):
                if has_cycle(neighbor):
                    return True
            path.discard(node)
            return False

        return has_cycle(holder_id)

    def cleanup_expired(self) -> List[str]:
        """清理过期锁"""
        expired = []
        for res, locks in list(self._locks.items()):
            for l in locks:
                if l.is_expired:
                    expired.append(f"{l.holder_id}:{res}")
            self._locks[res] = [l for l in locks if not l.is_expired]
            if not self._locks[res]:
                del self._locks[res]
                self._wake_waiters(res)
        return expired

    def get_status(self) -> Dict:
        total_locks = sum(len(v) for v in self._locks.values())
        total_waiting = sum(len(v) for v in self._wait_queue.values())
        return {
            "active_locks": total_locks,
            "locked_resources": len(self._locks),
            "waiting_requests": total_waiting,
            "holders": len(self._holder_resources),
        }


# ───────────────────── 并发度控制器 ─────────────────────

class ConcurrencyLimiter:
    """
    并发度限制器

    支持全局并发限制和按类别限制。
    """

    def __init__(self, global_max: int = 50,
                 category_limits: Optional[Dict[str, int]] = None):
        self.global_max = global_max
        self.category_limits = category_limits or {}
        self._global_sem = asyncio.Semaphore(global_max)
        self._category_sems: Dict[str, asyncio.Semaphore] = {}
        self._active_slots: Dict[str, TaskSlot] = {}
        self._mu = asyncio.Lock()

        # 初始化类别信号量
        for cat, limit in self.category_limits.items():
            self._category_sems[cat] = asyncio.Semaphore(limit)

    async def acquire_slot(self, task_id: str, category: str = "default",
                           timeout: float = 300.0) -> bool:
        """获取执行槽位"""
        # 确保类别信号量存在
        if category not in self._category_sems:
            self._category_sems[category] = asyncio.Semaphore(
                self.category_limits.get(category, self.global_max)
            )

        try:
            # 先获取全局信号量
            acquired_global = await asyncio.wait_for(
                self._global_sem.acquire(), timeout=timeout
            )
            if not acquired_global:
                return False

            # 再获取类别信号量
            try:
                await asyncio.wait_for(
                    self._category_sems[category].acquire(), timeout=timeout
                )
            except asyncio.TimeoutError:
                self._global_sem.release()
                return False

            # 记录槽位
            async with self._mu:
                self._active_slots[task_id] = TaskSlot(
                    task_id=task_id, category=category, timeout=timeout,
                )

            logger.debug(f"并发槽位已获取: {task_id} ({category})")
            return True

        except asyncio.TimeoutError:
            logger.warning(f"并发槽位超时: {task_id} ({category})")
            return False

    async def release_slot(self, task_id: str):
        """释放执行槽位"""
        async with self._mu:
            slot = self._active_slots.pop(task_id, None)

        if slot:
            cat = slot.category
            if cat in self._category_sems:
                self._category_sems[cat].release()
            self._global_sem.release()
            logger.debug(f"并发槽位已释放: {task_id}")

    async def cleanup_expired(self) -> List[str]:
        """清理超时槽位"""
        expired = []
        async with self._mu:
            for tid, slot in list(self._active_slots.items()):
                if slot.is_expired:
                    expired.append(tid)

        for tid in expired:
            await self.release_slot(tid)
            logger.warning(f"超时槽位已清理: {tid}")

        return expired

    def get_status(self) -> Dict:
        active_by_cat: Dict[str, int] = defaultdict(int)
        for slot in self._active_slots.values():
            active_by_cat[slot.category] += 1

        return {
            "global_max": self.global_max,
            "global_active": len(self._active_slots),
            "global_available": self.global_max - len(self._active_slots),
            "by_category": dict(active_by_cat),
            "category_limits": self.category_limits,
        }


# ───────────────────── 资源竞争处理器 ─────────────────────

class ResourceQueue:
    """
    公平资源队列

    当多个任务竞争同一资源时，按 FIFO + 优先级排队。
    """

    def __init__(self):
        self._queues: Dict[str, asyncio.PriorityQueue] = {}
        self._active: Dict[str, str] = {}  # resource → current_holder

    async def request(self, resource_id: str, requester_id: str,
                      priority: int = 5, timeout: float = 30.0) -> bool:
        """请求资源"""
        if resource_id not in self._queues:
            self._queues[resource_id] = asyncio.PriorityQueue()

        if resource_id not in self._active:
            # 资源空闲，直接获取
            self._active[resource_id] = requester_id
            return True

        # 入队等待
        event = asyncio.Event()
        await self._queues[resource_id].put((priority, time.time(), requester_id, event))

        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def release(self, resource_id: str):
        """释放资源并分配给下一个等待者"""
        self._active.pop(resource_id, None)

        queue = self._queues.get(resource_id)
        if queue and not queue.empty():
            try:
                _, _, next_holder, event = queue.get_nowait()
                self._active[resource_id] = next_holder
                event.set()
            except asyncio.QueueEmpty:
                pass

    def get_status(self) -> Dict:
        return {
            "active_resources": len(self._active),
            "queued_resources": {
                r: q.qsize() for r, q in self._queues.items() if not q.empty()
            },
        }


# ───────────────────── 重试策略 ─────────────────────

class RetryPolicy:
    """指数退避重试策略"""

    def __init__(self, max_retries: int = 3,
                 base_delay: float = 1.0,
                 max_delay: float = 30.0,
                 exponential_base: float = 2.0):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base

    def get_delay(self, attempt: int) -> float:
        delay = self.base_delay * (self.exponential_base ** attempt)
        return min(delay, self.max_delay)

    async def execute(self, coro_factory, *args, **kwargs) -> Any:
        """
        带重试的协程执行

        Args:
            coro_factory: 一个可调用对象，每次调用返回新的协程
        """
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return await coro_factory(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    delay = self.get_delay(attempt)
                    logger.warning(
                        f"重试 {attempt + 1}/{self.max_retries}: {e}, "
                        f"等待 {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"重试耗尽 ({self.max_retries}次): {e}")

        raise last_error


# ───────────────────── 统一并发管理器 ─────────────────────

class ConcurrencyManager:
    """
    统一并发管理器

    整合锁管理、并发限制、资源队列和重试策略。
    """

    def __init__(self, global_max_concurrency: int = 50,
                 category_limits: Optional[Dict[str, int]] = None):
        self.locks = LockManager()
        self.limiter = ConcurrencyLimiter(
            global_max=global_max_concurrency,
            category_limits=category_limits or {
                "llm_call": 10,
                "device_control": 5,
                "file_io": 20,
                "network": 30,
            },
        )
        self.resources = ResourceQueue()
        self.retry = RetryPolicy()
        self._cleanup_task: Optional[asyncio.Task] = None
        logger.info(f"ConcurrencyManager 已初始化 (最大并发: {global_max_concurrency})")

    async def start(self):
        """启动后台清理任务"""
        self._cleanup_task = asyncio.ensure_future(self._cleanup_loop())

    async def stop(self):
        """停止"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def _cleanup_loop(self):
        """定期清理过期锁和槽位"""
        while True:
            try:
                await asyncio.sleep(10)
                expired_locks = self.locks.cleanup_expired()
                expired_slots = await self.limiter.cleanup_expired()
                if expired_locks or expired_slots:
                    logger.info(
                        f"清理: {len(expired_locks)} 过期锁, "
                        f"{len(expired_slots)} 过期槽位"
                    )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理循环异常: {e}")

    # ─── 便捷方法 ───

    async def run_with_concurrency(self, task_id: str, category: str,
                                   coro_factory, *args,
                                   timeout: float = 300.0,
                                   retries: int = 0, **kwargs) -> Any:
        """
        带并发控制的任务执行

        自动获取槽位 → 执行 → 释放槽位
        可选重试。
        """
        acquired = await self.limiter.acquire_slot(task_id, category, timeout)
        if not acquired:
            raise TimeoutError(f"无法获取并发槽位: {task_id} ({category})")

        try:
            if retries > 0:
                policy = RetryPolicy(max_retries=retries)
                return await policy.execute(coro_factory, *args, **kwargs)
            else:
                return await coro_factory(*args, **kwargs)
        finally:
            await self.limiter.release_slot(task_id)

    async def run_with_lock(self, resource_id: str, holder_id: str,
                            coro_factory, *args,
                            lock_type: LockType = LockType.EXCLUSIVE,
                            timeout: float = 30.0, **kwargs) -> Any:
        """
        带锁的任务执行

        自动获取锁 → 执行 → 释放锁
        """
        acquired = await self.locks.acquire(
            resource_id, holder_id, lock_type, timeout
        )
        if not acquired:
            raise TimeoutError(f"无法获取锁: {holder_id} → {resource_id}")

        try:
            return await coro_factory(*args, **kwargs)
        finally:
            await self.locks.release(resource_id, holder_id)

    def get_status(self) -> Dict:
        return {
            "locks": self.locks.get_status(),
            "concurrency": self.limiter.get_status(),
            "resources": self.resources.get_status(),
        }


# ───────────────────── 单例 ─────────────────────

_manager_instance: Optional[ConcurrencyManager] = None


def get_concurrency_manager(
    global_max: int = 50,
    category_limits: Optional[Dict[str, int]] = None,
) -> ConcurrencyManager:
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ConcurrencyManager(global_max, category_limits)
    return _manager_instance
