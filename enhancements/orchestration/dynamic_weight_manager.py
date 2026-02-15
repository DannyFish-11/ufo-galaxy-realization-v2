"""
UFO Galaxy - 动态权重调整和负载均衡管理器
==========================================

实现真实的动态权重调整、负载均衡和智能任务分配

功能:
1. 动态权重调整 - 根据节点性能实时调整权重
2. 负载均衡 - 智能分配任务到最优节点
3. 健康监控 - 实时监控节点健康状态
4. 故障转移 - 自动故障检测和转移
"""

import asyncio
import json
import time
import logging
import statistics
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime, timedelta
from collections import defaultdict
import heapq
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class NodeStatus(str, Enum):
    """节点状态"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"
    STARTING = "starting"
    STOPPING = "stopping"


class LoadBalanceStrategy(str, Enum):
    """负载均衡策略"""
    ROUND_ROBIN = "round_robin"           # 轮询
    WEIGHTED_ROUND_ROBIN = "weighted_rr"  # 加权轮询
    LEAST_CONNECTIONS = "least_conn"      # 最少连接
    WEIGHTED_LEAST_CONN = "weighted_lc"   # 加权最少连接
    RANDOM = "random"                      # 随机
    WEIGHTED_RANDOM = "weighted_random"    # 加权随机
    RESPONSE_TIME = "response_time"        # 响应时间优先
    RESOURCE_BASED = "resource_based"      # 资源使用优先


@dataclass
class NodeMetrics:
    """节点指标"""
    node_id: str
    cpu_usage: float = 0.0           # CPU 使用率 (0-100)
    memory_usage: float = 0.0        # 内存使用率 (0-100)
    disk_usage: float = 0.0          # 磁盘使用率 (0-100)
    network_latency: float = 0.0     # 网络延迟 (ms)
    active_connections: int = 0      # 活跃连接数
    requests_per_second: float = 0.0 # 每秒请求数
    error_rate: float = 0.0          # 错误率 (0-100)
    avg_response_time: float = 0.0   # 平均响应时间 (ms)
    last_updated: datetime = field(default_factory=datetime.now)
    
    def health_score(self) -> float:
        """计算健康分数 (0-100)"""
        # 各指标权重
        weights = {
            'cpu': 0.2,
            'memory': 0.15,
            'disk': 0.1,
            'latency': 0.15,
            'error_rate': 0.25,
            'response_time': 0.15
        }
        
        # 计算各项得分 (越低越好的指标需要反转)
        cpu_score = max(0, 100 - self.cpu_usage)
        memory_score = max(0, 100 - self.memory_usage)
        disk_score = max(0, 100 - self.disk_usage)
        latency_score = max(0, 100 - min(self.network_latency / 10, 100))
        error_score = max(0, 100 - self.error_rate * 10)
        response_score = max(0, 100 - min(self.avg_response_time / 10, 100))
        
        total_score = (
            cpu_score * weights['cpu'] +
            memory_score * weights['memory'] +
            disk_score * weights['disk'] +
            latency_score * weights['latency'] +
            error_score * weights['error_rate'] +
            response_score * weights['response_time']
        )
        
        return round(total_score, 2)


@dataclass
class NodeWeight:
    """节点权重"""
    node_id: str
    static_weight: int = 100         # 静态权重 (配置的基础权重)
    dynamic_weight: float = 100.0    # 动态权重 (根据性能调整)
    effective_weight: float = 100.0  # 有效权重 (实际使用的权重)
    current_weight: float = 0.0      # 当前权重 (用于加权轮询)
    last_adjusted: datetime = field(default_factory=datetime.now)
    adjustment_history: List[Tuple[datetime, float]] = field(default_factory=list)
    
    def adjust(self, new_dynamic_weight: float):
        """调整动态权重"""
        old_weight = self.dynamic_weight
        self.dynamic_weight = max(1.0, min(200.0, new_dynamic_weight))  # 限制范围
        self.effective_weight = self.static_weight * (self.dynamic_weight / 100.0)
        self.last_adjusted = datetime.now()
        self.adjustment_history.append((self.last_adjusted, self.dynamic_weight))
        
        # 只保留最近 100 条历史
        if len(self.adjustment_history) > 100:
            self.adjustment_history = self.adjustment_history[-100:]
        
        logger.debug(f"Node {self.node_id} weight adjusted: {old_weight:.2f} -> {self.dynamic_weight:.2f}")


@dataclass
class NodeInfo:
    """节点完整信息"""
    node_id: str
    name: str
    layer: str                       # core, cognitive, perception
    domain: str                      # 功能域
    capabilities: List[str]          # 能力列表
    api_url: str                     # API 地址
    status: NodeStatus = NodeStatus.HEALTHY
    metrics: NodeMetrics = None
    weight: NodeWeight = None
    max_connections: int = 100       # 最大连接数
    priority: str = "normal"         # critical, high, normal, low
    
    def __post_init__(self):
        if self.metrics is None:
            self.metrics = NodeMetrics(node_id=self.node_id)
        if self.weight is None:
            self.weight = NodeWeight(node_id=self.node_id)


class DynamicWeightManager:
    """动态权重管理器"""
    
    def __init__(
        self,
        adjustment_interval: int = 30,      # 权重调整间隔 (秒)
        health_check_interval: int = 10,    # 健康检查间隔 (秒)
        weight_smoothing: float = 0.3,      # 权重平滑系数 (0-1)
        min_weight: float = 10.0,           # 最小权重
        max_weight: float = 200.0           # 最大权重
    ):
        self.adjustment_interval = adjustment_interval
        self.health_check_interval = health_check_interval
        self.weight_smoothing = weight_smoothing
        self.min_weight = min_weight
        self.max_weight = max_weight
        
        self.nodes: Dict[str, NodeInfo] = {}
        self.metrics_history: Dict[str, List[NodeMetrics]] = defaultdict(list)
        
        self._running = False
        self._adjustment_task: Optional[asyncio.Task] = None
        self._health_check_task: Optional[asyncio.Task] = None
        
        # 回调函数
        self.on_weight_changed: Optional[Callable[[str, float, float], None]] = None
        self.on_node_status_changed: Optional[Callable[[str, NodeStatus, NodeStatus], None]] = None
    
    def register_node(self, node_info: NodeInfo):
        """注册节点"""
        self.nodes[node_info.node_id] = node_info
        logger.info(f"Registered node: {node_info.node_id} ({node_info.name})")
    
    def unregister_node(self, node_id: str):
        """注销节点"""
        if node_id in self.nodes:
            del self.nodes[node_id]
            logger.info(f"Unregistered node: {node_id}")
    
    def update_metrics(self, node_id: str, metrics: NodeMetrics):
        """更新节点指标"""
        if node_id not in self.nodes:
            logger.warning(f"Unknown node: {node_id}")
            return
        
        node = self.nodes[node_id]
        node.metrics = metrics
        
        # 保存历史
        self.metrics_history[node_id].append(metrics)
        if len(self.metrics_history[node_id]) > 1000:
            self.metrics_history[node_id] = self.metrics_history[node_id][-1000:]
        
        # 更新节点状态
        self._update_node_status(node)
    
    def _update_node_status(self, node: NodeInfo):
        """更新节点状态"""
        health_score = node.metrics.health_score()
        old_status = node.status
        
        if health_score >= 80:
            new_status = NodeStatus.HEALTHY
        elif health_score >= 50:
            new_status = NodeStatus.DEGRADED
        elif health_score >= 20:
            new_status = NodeStatus.UNHEALTHY
        else:
            new_status = NodeStatus.OFFLINE
        
        if old_status != new_status:
            node.status = new_status
            logger.info(f"Node {node.node_id} status changed: {old_status} -> {new_status}")
            
            if self.on_node_status_changed:
                self.on_node_status_changed(node.node_id, old_status, new_status)
    
    def adjust_weight(self, node_id: str):
        """调整单个节点的权重"""
        if node_id not in self.nodes:
            return
        
        node = self.nodes[node_id]
        old_weight = node.weight.dynamic_weight
        
        # 基于健康分数计算新权重
        health_score = node.metrics.health_score()
        target_weight = health_score
        
        # 考虑历史趋势
        history = self.metrics_history.get(node_id, [])
        if len(history) >= 5:
            recent_scores = [m.health_score() for m in history[-5:]]
            trend = recent_scores[-1] - recent_scores[0]
            
            # 如果趋势向好，略微提高权重
            if trend > 5:
                target_weight *= 1.1
            # 如果趋势变差，略微降低权重
            elif trend < -5:
                target_weight *= 0.9
        
        # 平滑调整
        new_weight = old_weight * (1 - self.weight_smoothing) + target_weight * self.weight_smoothing
        new_weight = max(self.min_weight, min(self.max_weight, new_weight))
        
        node.weight.adjust(new_weight)
        
        if self.on_weight_changed and abs(new_weight - old_weight) > 1:
            self.on_weight_changed(node_id, old_weight, new_weight)
    
    def adjust_all_weights(self):
        """调整所有节点的权重"""
        for node_id in self.nodes:
            self.adjust_weight(node_id)
    
    async def start(self):
        """启动权重管理器"""
        self._running = True
        self._adjustment_task = asyncio.create_task(self._adjustment_loop())
        self._health_check_task = asyncio.create_task(self._health_check_loop())
        logger.info("DynamicWeightManager started")
    
    async def stop(self):
        """停止权重管理器"""
        self._running = False
        
        if self._adjustment_task:
            self._adjustment_task.cancel()
            try:
                await self._adjustment_task
            except asyncio.CancelledError:
                pass
        
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
        
        logger.info("DynamicWeightManager stopped")
    
    async def _adjustment_loop(self):
        """权重调整循环"""
        while self._running:
            try:
                await asyncio.sleep(self.adjustment_interval)
                self.adjust_all_weights()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Weight adjustment error: {e}")
    
    async def _health_check_loop(self):
        """健康检查循环"""
        while self._running:
            try:
                await asyncio.sleep(self.health_check_interval)
                await self._perform_health_checks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check error: {e}")
    
    async def _perform_health_checks(self):
        """执行健康检查"""
        for node_id, node in self.nodes.items():
            try:
                # 模拟健康检查（实际应该调用节点的健康检查 API）
                # 这里使用模拟数据，实际部署时替换为真实 API 调用
                metrics = await self._check_node_health(node)
                self.update_metrics(node_id, metrics)
            except Exception as e:
                logger.error(f"Health check failed for {node_id}: {e}")
                # 标记节点为不健康
                node.status = NodeStatus.UNHEALTHY
    
    async def _check_node_health(self, node: NodeInfo) -> NodeMetrics:
        """检查节点健康状态（实际实现）"""
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                start_time = time.time()
                async with session.get(
                    f"{node.api_url}/health",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    latency = (time.time() - start_time) * 1000
                    
                    if response.status == 200:
                        data = await response.json()
                        return NodeMetrics(
                            node_id=node.node_id,
                            cpu_usage=data.get('cpu_usage', 0),
                            memory_usage=data.get('memory_usage', 0),
                            disk_usage=data.get('disk_usage', 0),
                            network_latency=latency,
                            active_connections=data.get('active_connections', 0),
                            requests_per_second=data.get('rps', 0),
                            error_rate=data.get('error_rate', 0),
                            avg_response_time=data.get('avg_response_time', latency)
                        )
                    else:
                        return NodeMetrics(
                            node_id=node.node_id,
                            error_rate=100,
                            network_latency=latency
                        )
        except Exception as e:
            logger.warning(f"Health check failed for {node.node_id}: {e}")
            return NodeMetrics(
                node_id=node.node_id,
                error_rate=100,
                network_latency=9999
            )
    
    def get_node_weights(self) -> Dict[str, float]:
        """获取所有节点的有效权重"""
        return {
            node_id: node.weight.effective_weight
            for node_id, node in self.nodes.items()
        }
    
    def get_healthy_nodes(self) -> List[NodeInfo]:
        """获取所有健康的节点"""
        return [
            node for node in self.nodes.values()
            if node.status in [NodeStatus.HEALTHY, NodeStatus.DEGRADED]
        ]
    
    def export_state(self) -> Dict[str, Any]:
        """导出当前状态"""
        return {
            'timestamp': datetime.now().isoformat(),
            'nodes': {
                node_id: {
                    'name': node.name,
                    'status': node.status.value,
                    'health_score': node.metrics.health_score(),
                    'static_weight': node.weight.static_weight,
                    'dynamic_weight': node.weight.dynamic_weight,
                    'effective_weight': node.weight.effective_weight
                }
                for node_id, node in self.nodes.items()
            }
        }


class LoadBalancer:
    """负载均衡器"""
    
    def __init__(
        self,
        weight_manager: DynamicWeightManager,
        strategy: LoadBalanceStrategy = LoadBalanceStrategy.WEIGHTED_LEAST_CONN
    ):
        self.weight_manager = weight_manager
        self.strategy = strategy
        
        # 轮询计数器
        self._rr_index = 0
        
        # 连接计数
        self._connection_counts: Dict[str, int] = defaultdict(int)
        
        # 响应时间记录
        self._response_times: Dict[str, List[float]] = defaultdict(list)
    
    def select_node(
        self,
        required_capabilities: Optional[List[str]] = None,
        preferred_layer: Optional[str] = None,
        exclude_nodes: Optional[List[str]] = None
    ) -> Optional[NodeInfo]:
        """选择最优节点"""
        # 获取候选节点
        candidates = self._get_candidates(required_capabilities, preferred_layer, exclude_nodes)
        
        if not candidates:
            logger.warning("No available nodes for selection")
            return None
        
        # 根据策略选择节点
        if self.strategy == LoadBalanceStrategy.ROUND_ROBIN:
            return self._round_robin(candidates)
        elif self.strategy == LoadBalanceStrategy.WEIGHTED_ROUND_ROBIN:
            return self._weighted_round_robin(candidates)
        elif self.strategy == LoadBalanceStrategy.LEAST_CONNECTIONS:
            return self._least_connections(candidates)
        elif self.strategy == LoadBalanceStrategy.WEIGHTED_LEAST_CONN:
            return self._weighted_least_connections(candidates)
        elif self.strategy == LoadBalanceStrategy.RANDOM:
            return self._random(candidates)
        elif self.strategy == LoadBalanceStrategy.WEIGHTED_RANDOM:
            return self._weighted_random(candidates)
        elif self.strategy == LoadBalanceStrategy.RESPONSE_TIME:
            return self._response_time_based(candidates)
        elif self.strategy == LoadBalanceStrategy.RESOURCE_BASED:
            return self._resource_based(candidates)
        else:
            return self._weighted_least_connections(candidates)
    
    def _get_candidates(
        self,
        required_capabilities: Optional[List[str]],
        preferred_layer: Optional[str],
        exclude_nodes: Optional[List[str]]
    ) -> List[NodeInfo]:
        """获取候选节点"""
        candidates = self.weight_manager.get_healthy_nodes()
        
        # 排除指定节点
        if exclude_nodes:
            candidates = [n for n in candidates if n.node_id not in exclude_nodes]
        
        # 过滤能力
        if required_capabilities:
            candidates = [
                n for n in candidates
                if all(cap in n.capabilities for cap in required_capabilities)
            ]
        
        # 优先选择指定层级
        if preferred_layer:
            layer_candidates = [n for n in candidates if n.layer == preferred_layer]
            if layer_candidates:
                candidates = layer_candidates
        
        return candidates
    
    def _round_robin(self, candidates: List[NodeInfo]) -> NodeInfo:
        """轮询选择"""
        self._rr_index = (self._rr_index + 1) % len(candidates)
        return candidates[self._rr_index]
    
    def _weighted_round_robin(self, candidates: List[NodeInfo]) -> NodeInfo:
        """加权轮询选择"""
        total_weight = sum(n.weight.effective_weight for n in candidates)
        
        # 更新当前权重
        for node in candidates:
            node.weight.current_weight += node.weight.effective_weight
        
        # 选择当前权重最高的节点
        selected = max(candidates, key=lambda n: n.weight.current_weight)
        selected.weight.current_weight -= total_weight
        
        return selected
    
    def _least_connections(self, candidates: List[NodeInfo]) -> NodeInfo:
        """最少连接选择"""
        return min(candidates, key=lambda n: self._connection_counts[n.node_id])
    
    def _weighted_least_connections(self, candidates: List[NodeInfo]) -> NodeInfo:
        """加权最少连接选择"""
        def score(node: NodeInfo) -> float:
            connections = self._connection_counts[node.node_id]
            weight = node.weight.effective_weight
            # 连接数/权重，越小越好
            return connections / max(weight, 1)
        
        return min(candidates, key=score)
    
    def _random(self, candidates: List[NodeInfo]) -> NodeInfo:
        """随机选择"""
        return random.choice(candidates)
    
    def _weighted_random(self, candidates: List[NodeInfo]) -> NodeInfo:
        """加权随机选择"""
        weights = [n.weight.effective_weight for n in candidates]
        total = sum(weights)
        
        r = random.uniform(0, total)
        cumulative = 0
        
        for node, weight in zip(candidates, weights):
            cumulative += weight
            if r <= cumulative:
                return node
        
        return candidates[-1]
    
    def _response_time_based(self, candidates: List[NodeInfo]) -> NodeInfo:
        """响应时间优先选择"""
        def avg_response_time(node: NodeInfo) -> float:
            times = self._response_times.get(node.node_id, [])
            if times:
                return statistics.mean(times[-10:])  # 最近 10 次的平均值
            return node.metrics.avg_response_time
        
        return min(candidates, key=avg_response_time)
    
    def _resource_based(self, candidates: List[NodeInfo]) -> NodeInfo:
        """资源使用优先选择"""
        def resource_score(node: NodeInfo) -> float:
            # 综合考虑 CPU、内存、连接数
            return (
                node.metrics.cpu_usage * 0.4 +
                node.metrics.memory_usage * 0.3 +
                (self._connection_counts[node.node_id] / max(node.max_connections, 1)) * 100 * 0.3
            )
        
        return min(candidates, key=resource_score)
    
    def record_connection_start(self, node_id: str):
        """记录连接开始"""
        self._connection_counts[node_id] += 1
    
    def record_connection_end(self, node_id: str, response_time: float):
        """记录连接结束"""
        self._connection_counts[node_id] = max(0, self._connection_counts[node_id] - 1)
        
        self._response_times[node_id].append(response_time)
        if len(self._response_times[node_id]) > 100:
            self._response_times[node_id] = self._response_times[node_id][-100:]
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取负载均衡统计"""
        return {
            'strategy': self.strategy.value,
            'connection_counts': dict(self._connection_counts),
            'avg_response_times': {
                node_id: statistics.mean(times) if times else 0
                for node_id, times in self._response_times.items()
            }
        }


class SmartTaskDistributor:
    """智能任务分配器"""
    
    def __init__(
        self,
        weight_manager: DynamicWeightManager,
        load_balancer: LoadBalancer
    ):
        self.weight_manager = weight_manager
        self.load_balancer = load_balancer
        
        # 任务队列
        self._task_queue: List[Tuple[int, str, Dict]] = []  # (priority, task_id, task_info)
        
        # 任务分配历史
        self._assignment_history: Dict[str, List[str]] = defaultdict(list)  # node_id -> [task_ids]
    
    async def distribute_task(
        self,
        task_id: str,
        task_type: str,
        required_capabilities: List[str],
        priority: int = 5,
        preferred_layer: Optional[str] = None,
        timeout: int = 30
    ) -> Optional[Tuple[NodeInfo, str]]:
        """
        分配任务到最优节点
        
        Returns:
            (NodeInfo, assignment_id) 或 None
        """
        # 选择节点
        node = self.load_balancer.select_node(
            required_capabilities=required_capabilities,
            preferred_layer=preferred_layer
        )
        
        if not node:
            logger.error(f"No available node for task {task_id}")
            return None
        
        # 记录连接
        self.load_balancer.record_connection_start(node.node_id)
        
        # 生成分配 ID
        assignment_id = f"{task_id}_{node.node_id}_{int(time.time())}"
        
        # 记录历史
        self._assignment_history[node.node_id].append(task_id)
        
        logger.info(f"Task {task_id} assigned to {node.node_id} ({node.name})")
        
        return (node, assignment_id)
    
    def complete_task(self, node_id: str, task_id: str, response_time: float, success: bool):
        """完成任务"""
        self.load_balancer.record_connection_end(node_id, response_time)
        
        if not success:
            # 降低节点权重
            node = self.weight_manager.nodes.get(node_id)
            if node:
                node.weight.adjust(node.weight.dynamic_weight * 0.9)
    
    def get_distribution_stats(self) -> Dict[str, Any]:
        """获取分配统计"""
        return {
            'total_assignments': sum(len(tasks) for tasks in self._assignment_history.values()),
            'assignments_per_node': {
                node_id: len(tasks)
                for node_id, tasks in self._assignment_history.items()
            },
            'load_balancer_stats': self.load_balancer.get_statistics()
        }


# 便捷函数
def create_weight_manager_from_topology(topology_file: str) -> DynamicWeightManager:
    """从拓扑配置文件创建权重管理器"""
    with open(topology_file, 'r') as f:
        topology = json.load(f)
    
    manager = DynamicWeightManager()
    
    for node_config in topology.get('nodes', []):
        node_info = NodeInfo(
            node_id=node_config['id'],
            name=node_config['name'],
            layer=node_config['layer'],
            domain=node_config['domain'],
            capabilities=node_config.get('capabilities', []),
            api_url=node_config.get('api_url', f"http://localhost:{8000 + int(node_config['id'].split('_')[1])}"),
            priority=node_config.get('metadata', {}).get('priority', 'normal')
        )
        
        # 设置静态权重
        priority_weights = {
            'critical': 150,
            'high': 120,
            'normal': 100,
            'low': 80
        }
        node_info.weight.static_weight = priority_weights.get(node_info.priority, 100)
        node_info.weight.effective_weight = node_info.weight.static_weight
        
        manager.register_node(node_info)
    
    return manager


# 测试代码
async def test_weight_manager():
    """测试权重管理器"""
    print("=== 测试动态权重管理器 ===")
    
    # 创建管理器
    manager = DynamicWeightManager(
        adjustment_interval=5,
        health_check_interval=3
    )
    
    # 注册测试节点
    for i in range(5):
        node = NodeInfo(
            node_id=f"Node_{i:02d}",
            name=f"TestNode{i}",
            layer="core" if i < 2 else "cognitive",
            domain="test",
            capabilities=["test", "compute"],
            api_url=f"http://localhost:{8000 + i}"
        )
        manager.register_node(node)
    
    # 模拟指标更新
    for node_id in manager.nodes:
        metrics = NodeMetrics(
            node_id=node_id,
            cpu_usage=random.uniform(20, 80),
            memory_usage=random.uniform(30, 70),
            error_rate=random.uniform(0, 5),
            avg_response_time=random.uniform(10, 100)
        )
        manager.update_metrics(node_id, metrics)
    
    # 调整权重
    manager.adjust_all_weights()
    
    # 输出状态
    state = manager.export_state()
    print(json.dumps(state, indent=2, default=str))
    
    # 测试负载均衡
    print("\n=== 测试负载均衡器 ===")
    balancer = LoadBalancer(manager, LoadBalanceStrategy.WEIGHTED_LEAST_CONN)
    
    for i in range(10):
        node = balancer.select_node()
        if node:
            print(f"Selected: {node.node_id} ({node.name}), weight: {node.weight.effective_weight:.2f}")
            balancer.record_connection_start(node.node_id)
            await asyncio.sleep(0.1)
            balancer.record_connection_end(node.node_id, random.uniform(10, 50))
    
    print("\nLoad balancer stats:")
    print(json.dumps(balancer.get_statistics(), indent=2))
    
    print("\n✅ 测试完成")


if __name__ == "__main__":
    asyncio.run(test_weight_manager())
