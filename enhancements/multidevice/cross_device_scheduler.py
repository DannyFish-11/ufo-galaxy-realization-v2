"""
UFO Galaxy v5.0 - Cross-Device Scheduler Module
Multi-Device Task Scheduling System

This module provides task scheduling across multiple devices with 6 load balancing
strategies, task queue management, and resource allocation for 500+ TPS.

Features:
- Task scheduling across devices (500 TPS target)
- 6 load balancing strategies
- Task queue management with priority
- Resource allocation and monitoring
- Task retry and timeout handling
- Batch task processing

Load Balancing Strategies:
1. Round Robin - Distribute tasks evenly
2. Least Connections - Assign to least loaded device
3. Weighted Response Time - Based on device response time
4. Resource Based - Based on available resources
5. Geographic - Based on device location
6. Adaptive - Dynamic strategy selection

Author: UFO Galaxy Team
Version: 5.0.0
"""

import asyncio
import time
import uuid
import heapq
import logging
from typing import Dict, List, Optional, Set, Any, Callable, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from collections import deque, defaultdict
from abc import ABC, abstractmethod
import random
import statistics

from device_protocol import TaskInfo, TaskPriority, TaskState, DeviceInfo, DeviceStatus

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LoadBalancingStrategy(Enum):
    """Load balancing strategies"""
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    WEIGHTED_RESPONSE_TIME = "weighted_response_time"
    RESOURCE_BASED = "resource_based"
    GEOGRAPHIC = "geographic"
    ADAPTIVE = "adaptive"


@dataclass(order=True)
class PrioritizedTask:
    """Task wrapper for priority queue"""
    priority: int
    created_at: float = field(compare=False)
    task: TaskInfo = field(compare=False)
    
    def __init__(self, task: TaskInfo):
        self.priority = task.priority.value
        self.created_at = task.created_at
        self.task = task


@dataclass
class DeviceMetrics:
    """Device performance metrics"""
    device_id: str
    active_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    total_tasks: int = 0
    average_response_time: float = 0.0
    response_times: List[float] = field(default_factory=list)
    last_assigned: float = 0.0
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    network_latency: float = 0.0
    success_rate: float = 1.0
    weight: float = 1.0
    
    def record_response_time(self, response_time: float) -> None:
        """Record task response time"""
        self.response_times.append(response_time)
        if len(self.response_times) > 100:
            self.response_times = self.response_times[-100:]
        self.average_response_time = statistics.mean(self.response_times)
    
    def record_task_completion(self, success: bool, response_time: float) -> None:
        """Record task completion"""
        self.active_tasks -= 1
        self.total_tasks += 1
        
        if success:
            self.completed_tasks += 1
        else:
            self.failed_tasks += 1
        
        self.record_response_time(response_time)
        
        # Update success rate
        total = self.completed_tasks + self.failed_tasks
        if total > 0:
            self.success_rate = self.completed_tasks / total
    
    def get_score(self) -> float:
        """Calculate device score (higher is better)"""
        # Consider: success rate, response time, active tasks, resources
        score = self.success_rate * 100
        
        # Penalize high active tasks
        score -= self.active_tasks * 5
        
        # Penalize slow response times
        if self.average_response_time > 0:
            score -= min(self.average_response_time / 100, 20)
        
        # Penalize high resource usage
        score -= (self.cpu_usage + self.memory_usage) / 10
        
        return max(0, score) * self.weight


@dataclass
class TaskBatch:
    """Batch of tasks for efficient processing"""
    batch_id: str
    tasks: List[TaskInfo] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    max_size: int = 100
    max_wait_ms: float = 100.0
    
    def is_full(self) -> bool:
        return len(self.tasks) >= self.max_size
    
    def is_ready(self) -> bool:
        return self.is_full() or (time.time() - self.created_at) * 1000 >= self.max_wait_ms
    
    def add_task(self, task: TaskInfo) -> bool:
        if self.is_full():
            return False
        self.tasks.append(task)
        return True


class LoadBalancer(ABC):
    """Abstract base class for load balancers"""
    
    @abstractmethod
    def select_device(
        self,
        task: TaskInfo,
        available_devices: List[DeviceInfo],
        device_metrics: Dict[str, DeviceMetrics]
    ) -> Optional[str]:
        """Select device for task"""
        pass
    
    @abstractmethod
    def update_metrics(self, device_id: str, metrics: DeviceMetrics) -> None:
        """Update device metrics"""
        pass


class RoundRobinBalancer(LoadBalancer):
    """Round-robin load balancer"""
    
    def __init__(self):
        self._counter = 0
        self._lock = asyncio.Lock()
    
    async def select_device(
        self,
        task: TaskInfo,
        available_devices: List[DeviceInfo],
        device_metrics: Dict[str, DeviceMetrics]
    ) -> Optional[str]:
        if not available_devices:
            return None
        
        async with self._lock:
            device = available_devices[self._counter % len(available_devices)]
            self._counter += 1
            return device.device_id
    
    def update_metrics(self, device_id: str, metrics: DeviceMetrics) -> None:
        pass


class LeastConnectionsBalancer(LoadBalancer):
    """Least connections load balancer"""
    
    def update_metrics(self, device_id: str, metrics: DeviceMetrics) -> None:
        pass
    
    def select_device(
        self,
        task: TaskInfo,
        available_devices: List[DeviceInfo],
        device_metrics: Dict[str, DeviceMetrics]
    ) -> Optional[str]:
        if not available_devices:
            return None
        
        # Find device with least active tasks
        best_device = None
        min_connections = float('inf')
        
        for device in available_devices:
            metrics = device_metrics.get(device.device_id)
            if metrics:
                if metrics.active_tasks < min_connections:
                    min_connections = metrics.active_tasks
                    best_device = device
            else:
                # No metrics yet, prefer this device
                return device.device_id
        
        return best_device.device_id if best_device else available_devices[0].device_id


class WeightedResponseTimeBalancer(LoadBalancer):
    """Weighted response time load balancer"""
    
    def __init__(self):
        self._weights: Dict[str, float] = {}
    
    def update_metrics(self, device_id: str, metrics: DeviceMetrics) -> None:
        # Calculate weight based on response time
        if metrics.average_response_time > 0:
            # Lower response time = higher weight
            self._weights[device_id] = 1000.0 / (metrics.average_response_time + 1)
        else:
            self._weights[device_id] = 1.0
    
    def select_device(
        self,
        task: TaskInfo,
        available_devices: List[DeviceInfo],
        device_metrics: Dict[str, DeviceMetrics]
    ) -> Optional[str]:
        if not available_devices:
            return None
        
        # Calculate weighted selection
        weights = []
        for device in available_devices:
            weight = self._weights.get(device.device_id, 1.0)
            # Adjust by success rate
            metrics = device_metrics.get(device.device_id)
            if metrics:
                weight *= metrics.success_rate
            weights.append(weight)
        
        # Weighted random selection
        total = sum(weights)
        if total == 0:
            return random.choice(available_devices).device_id
        
        r = random.uniform(0, total)
        cumulative = 0
        for device, weight in zip(available_devices, weights):
            cumulative += weight
            if r <= cumulative:
                return device.device_id
        
        return available_devices[-1].device_id


class ResourceBasedBalancer(LoadBalancer):
    """Resource-based load balancer"""
    
    def __init__(self):
        self._resource_scores: Dict[str, float] = {}
    
    def update_metrics(self, device_id: str, metrics: DeviceMetrics) -> None:
        # Calculate resource score
        # Higher score = more available resources
        score = 100.0
        score -= metrics.cpu_usage * 0.5
        score -= metrics.memory_usage * 0.5
        score -= metrics.active_tasks * 2
        self._resource_scores[device_id] = max(0, score)
    
    def select_device(
        self,
        task: TaskInfo,
        available_devices: List[DeviceInfo],
        device_metrics: Dict[str, DeviceMetrics]
    ) -> Optional[str]:
        if not available_devices:
            return None
        
        # Find device with best resource score
        best_device = None
        best_score = -1
        
        for device in available_devices:
            score = self._resource_scores.get(device.device_id, 50)
            metrics = device_metrics.get(device.device_id)
            if metrics:
                score = metrics.get_score()
            
            if score > best_score:
                best_score = score
                best_device = device
        
        return best_device.device_id if best_device else available_devices[0].device_id


class GeographicBalancer(LoadBalancer):
    """Geographic proximity load balancer"""
    
    def __init__(self):
        self._locations: Dict[str, Tuple[float, float]] = {}  # device_id -> (lat, lon)
    
    def set_device_location(self, device_id: str, latitude: float, longitude: float) -> None:
        """Set device geographic location"""
        self._locations[device_id] = (latitude, longitude)
    
    def update_metrics(self, device_id: str, metrics: DeviceMetrics) -> None:
        pass
    
    def _calculate_distance(
        self,
        loc1: Tuple[float, float],
        loc2: Tuple[float, float]
    ) -> float:
        """Calculate distance between two points (simplified)"""
        import math
        lat1, lon1 = loc1
        lat2, lon2 = loc2
        
        # Simplified Euclidean distance (for small distances)
        return math.sqrt((lat2 - lat1) ** 2 + (lon2 - lon1) ** 2)
    
    def select_device(
        self,
        task: TaskInfo,
        available_devices: List[DeviceInfo],
        device_metrics: Dict[str, DeviceMetrics]
    ) -> Optional[str]:
        if not available_devices:
            return None
        
        # Get task location from payload
        task_location = task.payload.get('location')
        if not task_location:
            # No location preference, use round-robin
            return random.choice(available_devices).device_id
        
        # Find closest device
        closest_device = None
        min_distance = float('inf')
        
        for device in available_devices:
            device_loc = self._locations.get(device.device_id)
            if device_loc:
                distance = self._calculate_distance(task_location, device_loc)
                if distance < min_distance:
                    min_distance = distance
                    closest_device = device
        
        return closest_device.device_id if closest_device else available_devices[0].device_id


class AdaptiveBalancer(LoadBalancer):
    """Adaptive load balancer that switches strategies based on conditions"""
    
    def __init__(self):
        self.balancers = {
            LoadBalancingStrategy.ROUND_ROBIN: RoundRobinBalancer(),
            LoadBalancingStrategy.LEAST_CONNECTIONS: LeastConnectionsBalancer(),
            LoadBalancingStrategy.WEIGHTED_RESPONSE_TIME: WeightedResponseTimeBalancer(),
            LoadBalancingStrategy.RESOURCE_BASED: ResourceBasedBalancer(),
        }
        self.current_strategy = LoadBalancingStrategy.ROUND_ROBIN
        self._performance_history: Dict[str, List[float]] = defaultdict(list)
    
    def update_metrics(self, device_id: str, metrics: DeviceMetrics) -> None:
        for balancer in self.balancers.values():
            balancer.update_metrics(device_id, metrics)
        
        # Record performance
        self._performance_history[device_id].append(metrics.average_response_time)
        if len(self._performance_history[device_id]) > 50:
            self._performance_history[device_id] = self._performance_history[device_id][-50:]
    
    def select_device(
        self,
        task: TaskInfo,
        available_devices: List[DeviceInfo],
        device_metrics: Dict[str, DeviceMetrics]
    ) -> Optional[str]:
        if not available_devices:
            return None
        
        # Adapt strategy based on conditions
        self._adapt_strategy(device_metrics)
        
        # Use current strategy
        balancer = self.balancers[self.current_strategy]
        if isinstance(balancer, RoundRobinBalancer):
            # RoundRobinBalancer uses async method
            import asyncio
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(
                balancer.select_device(task, available_devices, device_metrics)
            )
        return balancer.select_device(task, available_devices, device_metrics)
    
    def _adapt_strategy(self, device_metrics: Dict[str, DeviceMetrics]) -> None:
        """Adapt strategy based on current conditions"""
        if not device_metrics:
            return
        
        # Calculate system-wide metrics
        avg_response_time = statistics.mean(
            m.average_response_time for m in device_metrics.values() if m.average_response_time > 0
        ) if device_metrics else 0
        
        total_active = sum(m.active_tasks for m in device_metrics.values())
        
        # Switch strategy based on conditions
        if avg_response_time > 1000:  # High latency
            self.current_strategy = LoadBalancingStrategy.WEIGHTED_RESPONSE_TIME
        elif total_active > len(device_metrics) * 10:  # High load
            self.current_strategy = LoadBalancingStrategy.LEAST_CONNECTIONS
        else:
            self.current_strategy = LoadBalancingStrategy.RESOURCE_BASED


class CrossDeviceScheduler:
    """
    Cross-Device Task Scheduler
    
    Manages task scheduling across multiple devices with load balancing,
    queue management, and resource allocation.
    
    Supports 500+ TPS with efficient batching and prioritization.
    """
    
    def __init__(
        self,
        strategy: LoadBalancingStrategy = LoadBalancingStrategy.ADAPTIVE,
        max_queue_size: int = 10000,
        batch_size: int = 100,
        batch_wait_ms: float = 50.0,
        default_timeout: float = 300.0
    ):
        self.strategy_type = strategy
        self.max_queue_size = max_queue_size
        self.batch_size = batch_size
        self.batch_wait_ms = batch_wait_ms
        self.default_timeout = default_timeout
        
        # Task queues by priority
        self._queues: Dict[TaskPriority, asyncio.PriorityQueue] = {
            priority: asyncio.PriorityQueue(maxsize=max_queue_size // 5)
            for priority in TaskPriority
        }
        
        # Task tracking
        self._tasks: Dict[str, TaskInfo] = {}
        self._task_callbacks: Dict[str, List[Callable]] = defaultdict(list)
        
        # Device tracking
        self._devices: Dict[str, DeviceInfo] = {}
        self._device_metrics: Dict[str, DeviceMetrics] = {}
        
        # Load balancer
        self._balancer = self._create_balancer(strategy)
        
        # Batching
        self._current_batch: Optional[TaskBatch] = None
        self._batch_lock = asyncio.Lock()
        
        # Statistics
        self._stats = {
            'submitted': 0,
            'scheduled': 0,
            'completed': 0,
            'failed': 0,
            'cancelled': 0,
            'timeout': 0
        }
        
        # Control
        self._running = False
        self._scheduler_task: Optional[asyncio.Task] = None
        self._timeout_task: Optional[asyncio.Task] = None
        
        logger.info(f"CrossDeviceScheduler initialized with {strategy.value} strategy")
    
    def _create_balancer(self, strategy: LoadBalancingStrategy) -> LoadBalancer:
        """Create load balancer instance"""
        balancers = {
            LoadBalancingStrategy.ROUND_ROBIN: RoundRobinBalancer(),
            LoadBalancingStrategy.LEAST_CONNECTIONS: LeastConnectionsBalancer(),
            LoadBalancingStrategy.WEIGHTED_RESPONSE_TIME: WeightedResponseTimeBalancer(),
            LoadBalancingStrategy.RESOURCE_BASED: ResourceBasedBalancer(),
            LoadBalancingStrategy.GEOGRAPHIC: GeographicBalancer(),
            LoadBalancingStrategy.ADAPTIVE: AdaptiveBalancer(),
        }
        return balancers.get(strategy, AdaptiveBalancer())
    
    async def start(self) -> None:
        """Start scheduler"""
        self._running = True
        self._scheduler_task = asyncio.create_task(self._schedule_loop())
        self._timeout_task = asyncio.create_task(self._timeout_loop())
        logger.info("CrossDeviceScheduler started")
    
    async def stop(self) -> None:
        """Stop scheduler"""
        self._running = False
        
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        
        if self._timeout_task:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except asyncio.CancelledError:
                pass
        
        logger.info("CrossDeviceScheduler stopped")
    
    async def _schedule_loop(self) -> None:
        """Main scheduling loop"""
        while self._running:
            try:
                # Process task batches
                await self._process_batch()
                
                # Small delay to prevent busy-waiting
                await asyncio.sleep(0.001)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Schedule loop error: {e}")
    
    async def _timeout_loop(self) -> None:
        """Timeout checking loop"""
        while self._running:
            try:
                await self._check_timeouts()
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Timeout loop error: {e}")
    
    async def _check_timeouts(self) -> None:
        """Check and handle timed-out tasks"""
        current_time = time.time()
        timed_out = []
        
        for task_id, task in self._tasks.items():
            if task.state == TaskState.RUNNING:
                if task.started_at and (current_time - task.started_at) > task.timeout_seconds:
                    timed_out.append(task_id)
        
        for task_id in timed_out:
            await self._handle_timeout(task_id)
    
    async def _handle_timeout(self, task_id: str) -> None:
        """Handle task timeout"""
        task = self._tasks.get(task_id)
        if not task:
            return
        
        task.state = TaskState.TIMEOUT
        self._stats['timeout'] += 1
        
        logger.warning(f"Task {task_id} timed out")
        
        # Notify callbacks
        await self._notify_task_complete(task_id, False, error="Task timeout")
    
    async def submit_task(
        self,
        task_type: str,
        payload: Dict[str, Any],
        priority: TaskPriority = TaskPriority.NORMAL,
        target_device: Optional[str] = None,
        timeout: Optional[float] = None,
        max_retries: int = 3
    ) -> str:
        """
        Submit a task for scheduling
        
        Args:
            task_type: Type of task
            payload: Task payload
            priority: Task priority
            target_device: Specific device to assign (optional)
            timeout: Task timeout in seconds
            max_retries: Maximum retry attempts
            
        Returns:
            Task ID
        """
        task_id = str(uuid.uuid4())
        
        task = TaskInfo(
            task_id=task_id,
            task_type=task_type,
            priority=priority,
            payload=payload,
            assigned_device=target_device,
            timeout_seconds=timeout or self.default_timeout,
            max_retries=max_retries
        )
        
        # Add to queue
        prioritized = PrioritizedTask(task)
        
        try:
            self._queues[priority].put_nowait(prioritized)
            self._tasks[task_id] = task
            self._stats['submitted'] += 1
            
            logger.debug(f"Task {task_id} submitted with priority {priority.name}")
            
        except asyncio.QueueFull:
            raise RuntimeError(f"Task queue full for priority {priority.name}")
        
        return task_id
    
    async def submit_batch(
        self,
        tasks: List[Tuple[str, Dict[str, Any], TaskPriority]]
    ) -> List[str]:
        """
        Submit multiple tasks as a batch
        
        Args:
            tasks: List of (task_type, payload, priority) tuples
            
        Returns:
            List of task IDs
        """
        task_ids = []
        for task_type, payload, priority in tasks:
            task_id = await self.submit_task(task_type, payload, priority)
            task_ids.append(task_id)
        return task_ids
    
    async def _process_batch(self) -> None:
        """Process a batch of tasks"""
        async with self._batch_lock:
            # Create new batch if needed
            if self._current_batch is None:
                self._current_batch = TaskBatch(
                    batch_id=str(uuid.uuid4()),
                    max_size=self.batch_size,
                    max_wait_ms=self.batch_wait_ms
                )
            
            # Collect tasks from queues
            for priority in [TaskPriority.CRITICAL, TaskPriority.HIGH, TaskPriority.NORMAL, TaskPriority.LOW]:
                while not self._queues[priority].empty():
                    try:
                        prioritized = self._queues[priority].get_nowait()
                        if not self._current_batch.add_task(prioritized.task):
                            # Batch is full, process it
                            await self._execute_batch()
                            self._current_batch = TaskBatch(
                                batch_id=str(uuid.uuid4()),
                                max_size=self.batch_size,
                                max_wait_ms=self.batch_wait_ms
                            )
                            self._current_batch.add_task(prioritized.task)
                    except asyncio.QueueEmpty:
                        break
            
            # Check if batch is ready
            if self._current_batch and self._current_batch.is_ready() and self._current_batch.tasks:
                await self._execute_batch()
                self._current_batch = None
    
    async def _execute_batch(self) -> None:
        """Execute a batch of tasks"""
        if not self._current_batch or not self._current_batch.tasks:
            return
        
        batch = self._current_batch
        logger.info(f"Executing batch {batch.batch_id} with {len(batch.tasks)} tasks")
        
        # Schedule each task in the batch
        for task in batch.tasks:
            await self._schedule_task(task)
    
    async def _schedule_task(self, task: TaskInfo) -> bool:
        """Schedule a single task"""
        # Get available devices
        available = self._get_available_devices(task)
        
        if not available:
            logger.warning(f"No available devices for task {task.task_id}")
            return False
        
        # Select device using load balancer
        if task.assigned_device:
            device_id = task.assigned_device
        else:
            device_id = self._balancer.select_device(
                task, available, self._device_metrics
            )
        
        if not device_id:
            logger.warning(f"Could not select device for task {task.task_id}")
            return False
        
        # Update task
        task.assigned_device = device_id
        task.scheduled_at = time.time()
        task.state = TaskState.SCHEDULED
        
        # Update device metrics
        metrics = self._device_metrics.get(device_id)
        if metrics:
            metrics.active_tasks += 1
            metrics.last_assigned = time.time()
        
        self._stats['scheduled'] += 1
        
        logger.debug(f"Task {task.task_id} scheduled to device {device_id}")
        
        return True
    
    def _get_available_devices(self, task: TaskInfo) -> List[DeviceInfo]:
        """Get available devices for a task"""
        available = []
        
        for device in self._devices.values():
            # Check device status
            if device.status not in [DeviceStatus.ONLINE, DeviceStatus.BUSY]:
                continue
            
            # Check capabilities if specified
            required_caps = task.payload.get('required_capabilities', [])
            if required_caps:
                caps = device.capabilities
                for cap in required_caps:
                    if cap == 'gpu' and not caps.gpu_available:
                        break
                    if cap == 'screen' and not caps.supports_screen:
                        break
                else:
                    available.append(device)
            else:
                available.append(device)
        
        return available
    
    async def register_device(self, device: DeviceInfo) -> None:
        """Register a device for task scheduling"""
        self._devices[device.device_id] = device
        self._device_metrics[device.device_id] = DeviceMetrics(device_id=device.device_id)
        logger.info(f"Device {device.device_id} registered with scheduler")
    
    async def unregister_device(self, device_id: str) -> None:
        """Unregister a device"""
        self._devices.pop(device_id, None)
        self._device_metrics.pop(device_id, None)
        logger.info(f"Device {device_id} unregistered from scheduler")
    
    async def update_device_status(self, device_id: str, status: DeviceStatus) -> None:
        """Update device status"""
        device = self._devices.get(device_id)
        if device:
            device.status = status
    
    async def update_device_metrics(
        self,
        device_id: str,
        cpu_usage: Optional[float] = None,
        memory_usage: Optional[float] = None,
        network_latency: Optional[float] = None
    ) -> None:
        """Update device performance metrics"""
        metrics = self._device_metrics.get(device_id)
        if metrics:
            if cpu_usage is not None:
                metrics.cpu_usage = cpu_usage
            if memory_usage is not None:
                metrics.memory_usage = memory_usage
            if network_latency is not None:
                metrics.network_latency = network_latency
            
            self._balancer.update_metrics(device_id, metrics)
    
    async def report_task_completion(
        self,
        task_id: str,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        response_time: Optional[float] = None
    ) -> None:
        """Report task completion"""
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found for completion report")
            return
        
        # Update task
        task.completed_at = time.time()
        task.result = result
        task.error_message = error_message
        
        if success:
            task.state = TaskState.COMPLETED
            self._stats['completed'] += 1
        else:
            task.state = TaskState.FAILED
            self._stats['failed'] += 1
            
            # Check for retry
            if task.retry_count < task.max_retries:
                task.retry_count += 1
                task.state = TaskState.PENDING
                # Re-queue the task
                prioritized = PrioritizedTask(task)
                try:
                    self._queues[task.priority].put_nowait(prioritized)
                    logger.info(f"Task {task_id} re-queued for retry ({task.retry_count}/{task.max_retries})")
                    return
                except asyncio.QueueFull:
                    logger.error(f"Could not re-queue task {task_id}, queue full")
        
        # Update device metrics
        if task.assigned_device:
            metrics = self._device_metrics.get(task.assigned_device)
            if metrics:
                metrics.record_task_completion(success, response_time or 0)
                self._balancer.update_metrics(task.assigned_device, metrics)
        
        # Notify callbacks
        await self._notify_task_complete(task_id, success, result, error_message)
        
        logger.debug(f"Task {task_id} completed: success={success}")
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a pending task"""
        task = self._tasks.get(task_id)
        if not task:
            return False
        
        if task.state in [TaskState.PENDING, TaskState.SCHEDULED]:
            task.state = TaskState.CANCELLED
            self._stats['cancelled'] += 1
            await self._notify_task_complete(task_id, False, error="Task cancelled")
            logger.info(f"Task {task_id} cancelled")
            return True
        
        return False
    
    def register_task_callback(self, task_id: str, callback: Callable) -> None:
        """Register callback for task completion"""
        self._task_callbacks[task_id].append(callback)
    
    async def _notify_task_complete(
        self,
        task_id: str,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> None:
        """Notify task completion callbacks"""
        callbacks = self._task_callbacks.get(task_id, [])
        for callback in callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(task_id, success, result, error)
                else:
                    callback(task_id, success, result, error)
            except Exception as e:
                logger.error(f"Task callback error: {e}")
        
        # Clean up callbacks
        if task_id in self._task_callbacks:
            del self._task_callbacks[task_id]
    
    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """Get task by ID"""
        return self._tasks.get(task_id)
    
    def get_tasks_by_state(self, state: TaskState) -> List[TaskInfo]:
        """Get tasks by state"""
        return [t for t in self._tasks.values() if t.state == state]
    
    def get_device_tasks(self, device_id: str) -> List[TaskInfo]:
        """Get tasks assigned to a device"""
        return [
            t for t in self._tasks.values()
            if t.assigned_device == device_id and t.state in [TaskState.SCHEDULED, TaskState.RUNNING]
        ]
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get scheduler statistics"""
        return {
            **self._stats,
            'pending': len(self.get_tasks_by_state(TaskState.PENDING)),
            'scheduled': len(self.get_tasks_by_state(TaskState.SCHEDULED)),
            'running': len(self.get_tasks_by_state(TaskState.RUNNING)),
            'total_active': len([t for t in self._tasks.values() if t.state in [TaskState.PENDING, TaskState.SCHEDULED, TaskState.RUNNING]]),
            'devices_registered': len(self._devices),
            'queue_sizes': {
                priority.name: self._queues[priority].qsize()
                for priority in TaskPriority
            }
        }
    
    def get_device_statistics(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get device statistics"""
        metrics = self._device_metrics.get(device_id)
        if not metrics:
            return None
        
        return {
            'device_id': device_id,
            'active_tasks': metrics.active_tasks,
            'completed_tasks': metrics.completed_tasks,
            'failed_tasks': metrics.failed_tasks,
            'total_tasks': metrics.total_tasks,
            'average_response_time': metrics.average_response_time,
            'success_rate': metrics.success_rate,
            'health_score': metrics.get_score()
        }


# ============================================================================
# Export
# ============================================================================

__all__ = [
    'LoadBalancingStrategy',
    'DeviceMetrics',
    'TaskBatch',
    'LoadBalancer',
    'RoundRobinBalancer',
    'LeastConnectionsBalancer',
    'WeightedResponseTimeBalancer',
    'ResourceBasedBalancer',
    'GeographicBalancer',
    'AdaptiveBalancer',
    'CrossDeviceScheduler'
]
