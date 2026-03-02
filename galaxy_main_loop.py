"""
UFO Galaxy 主循环入口
全天候运行模式 - 接收目标、规划、执行、自我反思
"""

import asyncio
import logging
import signal
import time
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
import json


class CycleState(Enum):
    """主循环周期状态"""
    IDLE = auto()
    RECEIVING = auto()
    PLANNING = auto()
    EXECUTING = auto()
    COLLECTING = auto()
    REFLECTING = auto()
    ERROR = auto()


class HealthStatus(Enum):
    """健康状态"""
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    DOWN = "down"


@dataclass
class CycleResult:
    """周期执行结果"""
    cycle_id: str
    state: CycleState
    start_time: datetime
    end_time: Optional[datetime] = None
    success: bool = False
    tasks_completed: int = 0
    tasks_failed: int = 0
    reflections: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthMetrics:
    """健康监控指标"""
    status: HealthStatus = HealthStatus.HEALTHY
    uptime_seconds: float = 0.0
    cycles_completed: int = 0
    cycles_failed: int = 0
    last_cycle_time: Optional[datetime] = None
    average_cycle_duration: float = 0.0
    memory_usage_mb: float = 0.0
    active_tasks: int = 0
    queue_depth: int = 0
    error_rate: float = 0.0


class GalaxyOrchestrator:
    """调度器接口 - 与外部 orchestrator 集成"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.task_queue: asyncio.Queue = asyncio.Queue()
        self.active_tasks: Dict[str, asyncio.Task] = {}
        self.results: Dict[str, Any] = {}

    async def submit_task(self, task: Dict[str, Any]) -> str:
        """提交任务到队列"""
        task_id = f"task_{int(time.time() * 1000)}"
        task["id"] = task_id
        await self.task_queue.put(task)
        return task_id

    async def get_next_task(self) -> Optional[Dict[str, Any]]:
        """获取下一个任务"""
        try:
            return await asyncio.wait_for(
                self.task_queue.get(), 
                timeout=1.0
            )
        except asyncio.TimeoutError:
            return None

    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """执行任务"""
        task_id = task.get("id", "unknown")
        task_type = task.get("type", "default")

        # 模拟任务执行
        await asyncio.sleep(0.1)

        result = {
            "task_id": task_id,
            "status": "completed",
            "type": task_type,
            "output": f"Executed {task_type} task",
            "timestamp": datetime.now().isoformat()
        }
        self.results[task_id] = result
        return result

    def get_queue_depth(self) -> int:
        """获取队列深度"""
        return self.task_queue.qsize()

    async def shutdown(self):
        """关闭调度器"""
        # 取消所有活跃任务
        for task in self.active_tasks.values():
            task.cancel()
        self.active_tasks.clear()


class HealthMonitor:
    """健康监控器"""

    def __init__(self, check_interval: float = 30.0):
        self.check_interval = check_interval
        self.metrics = HealthMetrics()
        self.start_time = datetime.now()
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._callbacks: List[Callable[[HealthMetrics], None]] = []

    def add_callback(self, callback: Callable[[HealthMetrics], None]):
        """添加健康状态回调"""
        self._callbacks.append(callback)

    async def start(self):
        """启动健康监控"""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logging.info("Health monitor started")

    async def _monitor_loop(self):
        """监控循环"""
        while self._running:
            try:
                await self._check_health()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logging.error(f"Health check error: {e}")

    async def _check_health(self):
        """执行健康检查"""
        # 计算运行时间
        self.metrics.uptime_seconds = (
            datetime.now() - self.start_time
        ).total_seconds()

        # 计算错误率
        total_cycles = self.metrics.cycles_completed + self.metrics.cycles_failed
        if total_cycles > 0:
            self.metrics.error_rate = (
                self.metrics.cycles_failed / total_cycles
            )

        # 确定健康状态
        if self.metrics.error_rate > 0.5:
            self.metrics.status = HealthStatus.CRITICAL
        elif self.metrics.error_rate > 0.2:
            self.metrics.status = HealthStatus.WARNING
        else:
            self.metrics.status = HealthStatus.HEALTHY

        # 触发回调
        for callback in self._callbacks:
            try:
                callback(self.metrics)
            except Exception as e:
                logging.error(f"Health callback error: {e}")

    def update_cycle_metrics(self, result: CycleResult):
        """更新周期指标"""
        if result.success:
            self.metrics.cycles_completed += 1
        else:
            self.metrics.cycles_failed += 1

        self.metrics.last_cycle_time = result.end_time

        # 更新平均周期时长
        if result.end_time and result.start_time:
            duration = (result.end_time - result.start_time).total_seconds()
            n = self.metrics.cycles_completed + self.metrics.cycles_failed
            self.metrics.average_cycle_duration = (
                (self.metrics.average_cycle_duration * (n - 1) + duration) / n
            )

    def get_metrics(self) -> HealthMetrics:
        """获取当前健康指标"""
        return self.metrics

    async def stop(self):
        """停止健康监控"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logging.info("Health monitor stopped")


class GalaxyMainLoop:
    """UFO Galaxy 主循环 - 全天候运行模式"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config or {}
        self.orchestrator: Optional[GalaxyOrchestrator] = None
        self.health_monitor: Optional[HealthMonitor] = None
        self.running = False
        self.current_state = CycleState.IDLE
        self.cycle_count = 0
        self.cycle_results: List[CycleResult] = []
        self._shutdown_event = asyncio.Event()
        self._main_task: Optional[asyncio.Task] = None

        # 配置参数
        self.cycle_interval = self.config.get("cycle_interval", 1.0)
        self.max_concurrent_tasks = self.config.get("max_concurrent_tasks", 10)
        self.enable_health_monitor = self.config.get("enable_health_monitor", True)

        # 设置日志
        self._setup_logging()

    def _setup_logging(self):
        """配置日志"""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        self.logger = logging.getLogger("GalaxyMainLoop")

    async def start(self):
        """启动主循环"""
        self.logger.info("Starting UFO Galaxy Main Loop...")

        # 初始化组件
        await self._initialize()

        # 设置信号处理
        self._setup_signal_handlers()

        # 启动健康监控
        if self.enable_health_monitor and self.health_monitor:
            await self.health_monitor.start()

        # 启动主循环
        self.running = True
        self._main_task = asyncio.create_task(self._main_loop())

        self.logger.info("Galaxy Main Loop started successfully")

        # 等待关闭信号
        await self._shutdown_event.wait()

    async def _initialize(self):
        """初始化组件"""
        self.orchestrator = GalaxyOrchestrator(self.config)
        self.health_monitor = HealthMonitor(
            check_interval=self.config.get("health_check_interval", 30.0)
        )

        # 添加健康状态回调
        self.health_monitor.add_callback(self._on_health_change)

    def _setup_signal_handlers(self):
        """设置信号处理器"""
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_event_loop().add_signal_handler(
                sig, 
                lambda: asyncio.create_task(self.stop())
            )

    def _on_health_change(self, metrics: HealthMetrics):
        """健康状态变化回调"""
        if metrics.status == HealthStatus.CRITICAL:
            self.logger.warning(f"Health status critical: {metrics}")

    async def _main_loop(self):
        """主循环"""
        while self.running:
            try:
                await self.run_cycle()
                await asyncio.sleep(self.cycle_interval)
            except Exception as e:
                self.logger.error(f"Main loop error: {e}")
                await asyncio.sleep(1.0)

    async def run_cycle(self) -> CycleResult:
        """运行一个完整周期"""
        cycle_id = f"cycle_{self.cycle_count}_{int(time.time() * 1000)}"
        result = CycleResult(
            cycle_id=cycle_id,
            state=CycleState.IDLE,
            start_time=datetime.now()
        )

        try:
            self.cycle_count += 1
            self.logger.debug(f"Starting cycle {self.cycle_count}")

            # 1. 接收/处理目标
            self.current_state = CycleState.RECEIVING
            goals = await self._receive_goals()

            # 2. 规划任务
            self.current_state = CycleState.PLANNING
            tasks = await self._plan_tasks(goals)

            # 3. 执行任务
            self.current_state = CycleState.EXECUTING
            task_results = await self._execute_tasks(tasks)

            # 4. 收集结果
            self.current_state = CycleState.COLLECTING
            collected = await self._collect_results(task_results)

            # 5. 自我反思
            self.current_state = CycleState.REFLECTING
            reflections = await self._self_reflect(collected)

            # 更新结果
            result.state = CycleState.IDLE
            result.success = True
            result.tasks_completed = len([r for r in task_results if r.get("status") == "completed"])
            result.tasks_failed = len(task_results) - result.tasks_completed
            result.reflections = reflections
            result.metrics = collected

            self.logger.debug(f"Cycle {self.cycle_count} completed")

        except Exception as e:
            result.state = CycleState.ERROR
            result.success = False
            result.errors.append(str(e))
            self.logger.error(f"Cycle {self.cycle_count} failed: {e}")

        finally:
            result.end_time = datetime.now()
            self.cycle_results.append(result)

            # 更新健康指标
            if self.health_monitor:
                self.health_monitor.update_cycle_metrics(result)

            # 清理旧结果
            if len(self.cycle_results) > 100:
                self.cycle_results = self.cycle_results[-100:]

        return result

    async def _receive_goals(self) -> List[Dict[str, Any]]:
        """接收目标"""
        # 从各种来源接收目标
        goals = []

        # 从队列获取任务作为目标
        if self.orchestrator:
            task = await self.orchestrator.get_next_task()
            if task:
                goals.append({
                    "type": "task",
                    "content": task
                })

        # 可以扩展：从API、消息队列等接收目标
        return goals

    async def _plan_tasks(self, goals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """规划任务"""
        tasks = []

        for goal in goals:
            # 简单的任务规划逻辑
            if goal.get("type") == "task":
                task = goal.get("content", {})
                tasks.append(task)
            else:
                # 创建默认任务
                tasks.append({
                    "type": "default",
                    "goal": goal,
                    "priority": 1
                })

        return tasks

    async def _execute_tasks(self, tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """执行任务"""
        results = []

        # 限制并发
        semaphore = asyncio.Semaphore(self.max_concurrent_tasks)

        async def execute_with_limit(task: Dict[str, Any]) -> Dict[str, Any]:
            async with semaphore:
                if self.orchestrator:
                    return await self.orchestrator.execute_task(task)
                return {"status": "failed", "error": "No orchestrator"}

        # 并发执行所有任务
        if tasks:
            results = await asyncio.gather(
                *[execute_with_limit(task) for task in tasks],
                return_exceptions=True
            )
            # 处理异常结果
            results = [
                r if not isinstance(r, Exception) else {"status": "failed", "error": str(r)}
                for r in results
            ]

        return results

    async def _collect_results(self, task_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """收集结果"""
        return {
            "total_tasks": len(task_results),
            "completed": len([r for r in task_results if r.get("status") == "completed"]),
            "failed": len([r for r in task_results if r.get("status") == "failed"]),
            "results": task_results,
            "timestamp": datetime.now().isoformat()
        }

    async def _self_reflect(self, collected: Dict[str, Any]) -> List[str]:
        """自我反思"""
        reflections = []

        # 分析执行结果
        total = collected.get("total_tasks", 0)
        completed = collected.get("completed", 0)
        failed = collected.get("failed", 0)

        if total > 0:
            success_rate = completed / total
            if success_rate < 0.8:
                reflections.append(f"Success rate low ({success_rate:.1%}), need optimization")
            else:
                reflections.append(f"Good success rate ({success_rate:.1%})")

        if failed > 0:
            reflections.append(f"{failed} tasks failed, review error patterns")

        # 性能反思
        if self.health_monitor:
            metrics = self.health_monitor.get_metrics()
            if metrics.average_cycle_duration > 10.0:
                reflections.append(f"Cycle duration high ({metrics.average_cycle_duration:.2f}s)")

        return reflections

    async def submit_goal(self, goal: Dict[str, Any]) -> str:
        """提交外部目标"""
        if self.orchestrator:
            return await self.orchestrator.submit_task(goal)
        raise RuntimeError("Orchestrator not initialized")

    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "running": self.running,
            "state": self.current_state.name,
            "cycle_count": self.cycle_count,
            "health": self.health_monitor.get_metrics().__dict__ if self.health_monitor else None,
            "queue_depth": self.orchestrator.get_queue_depth() if self.orchestrator else 0
        }

    async def stop(self):
        """停止主循环 - 优雅关闭"""
        self.logger.info("Stopping Galaxy Main Loop...")

        self.running = False

        # 停止主循环任务
        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass

        # 停止健康监控
        if self.health_monitor:
            await self.health_monitor.stop()

        # 关闭调度器
        if self.orchestrator:
            await self.orchestrator.shutdown()

        # 触发关闭事件
        self._shutdown_event.set()

        self.logger.info("Galaxy Main Loop stopped gracefully")


async def main():
    """主入口"""
    config = {
        "cycle_interval": 1.0,
        "max_concurrent_tasks": 10,
        "enable_health_monitor": True,
        "health_check_interval": 30.0
    }

    loop = GalaxyMainLoop(config)

    try:
        await loop.start()
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
