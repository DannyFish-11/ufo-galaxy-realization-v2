"""
Node 71 - Task Scheduler Tests
任务调度器单元测试
"""
import asyncio
import pytest
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.device import (
    Device, DeviceType, DeviceState, DeviceRegistry, Capability
)
from models.task import (
    Task, TaskState, TaskPriority, TaskType, TaskDependency,
    RetryPolicy, SchedulingStrategy
)
from core.task_scheduler import (
    TaskScheduler, SchedulerConfig, SchedulerEvent, SchedulerEventType,
    DeviceSelector, TaskExecutor, DependencyResolver
)


class TestDeviceSelector:
    """设备选择器测试"""

    @pytest.fixture
    def selector(self, device_registry):
        return DeviceSelector(device_registry)

    def test_select_priority(self, selector, sample_task):
        """测试优先级选择"""
        device = selector.select(
            sample_task, SchedulingStrategy.PRIORITY
        )
        assert device is not None

    def test_select_random(self, selector, sample_task):
        """测试随机选择"""
        device = selector.select(
            sample_task, SchedulingStrategy.RANDOM
        )
        assert device is not None

    def test_select_least_loaded(self, selector, sample_task):
        """测试最少负载选择"""
        device = selector.select(
            sample_task, SchedulingStrategy.LEAST_LOADED
        )
        assert device is not None

    def test_select_fair(self, selector, sample_task):
        """测试公平选择"""
        device = selector.select(
            sample_task, SchedulingStrategy.FAIR
        )
        assert device is not None

    def test_select_with_exclusion(self, selector, sample_task, sample_devices):
        """测试带排除的选择"""
        excluded = {sample_devices[0].device_id, sample_devices[1].device_id}
        device = selector.select(
            sample_task, SchedulingStrategy.RANDOM, excluded=excluded
        )
        if device:
            assert device.device_id not in excluded

    def test_select_by_capability(self, selector):
        """测试按能力选择"""
        task = Task(
            task_id="cap-task",
            name="Capability Task",
            required_capabilities=["cap-sensor"]
        )
        device = selector.select(task, SchedulingStrategy.CAPABILITY)
        if device:
            assert device.has_capability("cap-sensor")


class TestDependencyResolver:
    """依赖解析器测试"""

    @pytest.fixture
    def resolver(self):
        return DependencyResolver()

    def test_add_task(self, resolver):
        """测试添加任务"""
        task = Task(
            task_id="task-1", name="Task 1",
            dependencies=[TaskDependency(task_id="task-0")]
        )
        resolver.add_task(task)
        assert "task-1" in resolver._dependency_graph

    def test_is_ready_no_deps(self, resolver):
        """测试无依赖任务就绪"""
        task = Task(task_id="task-1", name="Task 1")
        resolver.add_task(task)
        assert resolver.is_ready("task-1") is True

    def test_is_ready_with_deps(self, resolver):
        """测试有依赖任务未就绪"""
        task0 = Task(task_id="task-0", name="Task 0")
        task1 = Task(
            task_id="task-1", name="Task 1",
            dependencies=[TaskDependency(task_id="task-0")]
        )
        resolver.add_task(task0)
        resolver.add_task(task1)

        assert resolver.is_ready("task-1") is False

    def test_mark_completed(self, resolver):
        """测试标记完成后依赖任务就绪"""
        task0 = Task(task_id="task-0", name="Task 0")
        task1 = Task(
            task_id="task-1", name="Task 1",
            dependencies=[TaskDependency(task_id="task-0")]
        )
        resolver.add_task(task0)
        resolver.add_task(task1)

        ready_tasks = resolver.mark_completed("task-0")
        assert "task-1" in ready_tasks

    def test_has_cycle_no_cycle(self, resolver):
        """测试无循环"""
        task0 = Task(task_id="task-0", name="Task 0")
        task1 = Task(
            task_id="task-1", name="Task 1",
            dependencies=[TaskDependency(task_id="task-0")]
        )
        resolver.add_task(task0)
        resolver.add_task(task1)

        assert resolver.has_cycle("task-0") is False

    def test_remove_task(self, resolver):
        """测试移除任务"""
        task = Task(task_id="task-1", name="Task 1")
        resolver.add_task(task)
        resolver.remove_task("task-1")
        assert "task-1" not in resolver._dependency_graph


class TestTaskExecutor:
    """任务执行器测试"""

    @pytest.fixture
    def executor(self):
        return TaskExecutor()

    @pytest.mark.asyncio
    async def test_default_execute(self, executor, sample_task, sample_device):
        """测试默认执行"""
        result = await executor.execute(sample_task, sample_device)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_custom_executor(self, executor, sample_task, sample_device):
        """测试自定义执行器"""
        async def custom_exec(task, device):
            return {"custom": True}

        executor.register_executor("command", custom_exec)
        result = await executor.execute(sample_task, sample_device)
        assert result["success"] is True
        assert result["result"]["custom"] is True


class TestTaskScheduler:
    """任务调度器测试"""

    @pytest.fixture
    def scheduler(self, device_registry):
        config = SchedulerConfig(task_timeout=5.0)
        return TaskScheduler(config, device_registry)

    @pytest.mark.asyncio
    async def test_start_stop(self, scheduler):
        """测试调度器启动和停止"""
        success = await scheduler.start()
        assert success is True
        assert scheduler._running_flag is True

        await scheduler.stop()
        assert scheduler._running_flag is False

    @pytest.mark.asyncio
    async def test_submit_task(self, scheduler, sample_task):
        """测试提交任务"""
        await scheduler.start()

        task_id = await scheduler.submit(sample_task)
        assert task_id == sample_task.task_id

        stats = scheduler.get_stats()
        assert stats["scheduled"] == 1

        await scheduler.stop()

    @pytest.mark.asyncio
    async def test_cancel_task(self, scheduler, sample_task):
        """测试取消任务"""
        await scheduler.start()

        await scheduler.submit(sample_task)
        success = await scheduler.cancel(sample_task.task_id)
        assert success is True

        await scheduler.stop()

    def test_get_task(self, scheduler, sample_task):
        """测试同步获取任务"""
        scheduler._queue.enqueue(sample_task)
        task = scheduler.get_task(sample_task.task_id)
        assert task is not None

    def test_get_stats(self, scheduler):
        """测试统计信息"""
        stats = scheduler.get_stats()
        assert "scheduled" in stats
        assert "completed" in stats
        assert "failed" in stats
        assert "queue_size" in stats

    def test_get_status(self, scheduler):
        """测试调度器状态"""
        status = scheduler.get_status()
        assert "running" in status
        assert "config" in status
        assert "stats" in status

    def test_event_handler(self, scheduler):
        """测试事件处理"""
        events = []

        def handler(event):
            events.append(event)

        scheduler.add_event_handler(handler)
        assert len(scheduler._event_handlers) == 1


class TestSchedulerIntegration:
    """调度器集成测试"""

    @pytest.mark.asyncio
    async def test_task_lifecycle(self, device_registry, sample_task):
        """测试任务完整生命周期"""
        config = SchedulerConfig(task_timeout=5.0)
        scheduler = TaskScheduler(config, device_registry)

        events = []

        def handler(event):
            events.append(event)

        scheduler.add_event_handler(handler)
        await scheduler.start()

        # 提交任务
        await scheduler.submit(sample_task)

        # 等待任务被调度和执行
        await asyncio.sleep(1.0)

        # 检查任务状态
        task = scheduler.get_task(sample_task.task_id)
        # 任务可能已完成或仍在运行
        assert task is not None

        await scheduler.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
