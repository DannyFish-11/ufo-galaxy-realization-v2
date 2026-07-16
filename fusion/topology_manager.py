"""
Galaxy Fusion - Topology Manager

三层球体拓扑管理器

功能:
1. 加载和管理三层球体拓扑 (Core, Cognitive, Perception)
2. 提供拓扑查询接口
3. 计算最优路由路径
4. 负载均衡
5. 拓扑可视化

作者: Manus AI
日期: 2026-01-25
"""

import json
import logging
import math
import os
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import networkx as nx
    NX_AVAILABLE = True
except ImportError:
    nx = None  # type: ignore
    NX_AVAILABLE = False

try:
    from pydantic import BaseModel, Field, field_validator, model_validator
    PYDANTIC_AVAILABLE = True
except ImportError:
    BaseModel = Field = field_validator = model_validator = None  # type: ignore
    PYDANTIC_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOPOLOGY_CONFIG_VERSION: str = "1.0"
DEFAULT_TOPOLOGY_CONFIG_PATH_ENV: str = "FUSION_TOPOLOGY_CONFIG"

# Layer identifiers
LAYER_CORE: str = "core"
LAYER_COGNITIVE: str = "cognitive"
LAYER_PERCEPTION: str = "perception"
VALID_LAYERS: Set[str] = {LAYER_CORE, LAYER_COGNITIVE, LAYER_PERCEPTION}

# Visualization colors
LAYER_COLORS: Dict[str, str] = {
    LAYER_CORE: "red",
    LAYER_COGNITIVE: "blue",
    LAYER_PERCEPTION: "green"
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_FORMAT: str = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic configuration validation
# ---------------------------------------------------------------------------

class TopologyNodeConfig(BaseModel if PYDANTIC_AVAILABLE else object):
    """Validated topology node configuration."""

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    layer: str = Field(...)
    domain: str = Field(..., min_length=1)
    coordinates: Dict[str, float] = Field(...)
    capabilities: List[str] = Field(default_factory=list)
    neighbors: List[str] = Field(default_factory=list)
    api_url: str = Field(default="")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    if PYDANTIC_AVAILABLE:
        @field_validator("layer")
        @classmethod
        def validate_layer(cls, value: str) -> str:
            """Validate that the layer is one of the supported values."""
            if value not in VALID_LAYERS:
                raise ValueError(f"layer must be one of {VALID_LAYERS}, got '{value}'")
            return value

        @field_validator("coordinates")
        @classmethod
        def validate_coordinates(cls, value: Dict[str, float]) -> Dict[str, float]:
            """Validate that coordinates contain required keys."""
            required_keys: Set[str] = {"theta", "phi", "radius"}
            missing: Set[str] = required_keys - set(value.keys())
            if missing:
                raise ValueError(f"coordinates missing required keys: {missing}")
            return value

    def __init__(self, **data: Any):
        if not PYDANTIC_AVAILABLE:
            self.id = data.get("id", "")
            self.name = data.get("name", "")
            self.layer = data.get("layer", "")
            self.domain = data.get("domain", "")
            self.coordinates = data.get("coordinates", {})
            self.capabilities = data.get("capabilities", [])
            self.neighbors = data.get("neighbors", [])
            self.api_url = data.get("api_url", "")
            self.metadata = data.get("metadata", {})
        else:
            super().__init__(**data)


class TopologyConfigModel(BaseModel if PYDANTIC_AVAILABLE else object):
    """Validated topology configuration model."""

    version: str = Field(default=TOPOLOGY_CONFIG_VERSION)
    nodes: List[Any] = Field(..., min_length=1)

    if PYDANTIC_AVAILABLE:
        @model_validator(mode="after")
        def validate_nodes(self) -> "TopologyConfigModel":
            """Validate all nodes in the topology."""
            for node_data in self.nodes:
                if isinstance(node_data, dict):
                    TopologyNodeConfig(**node_data)
            return self

    def __init__(self, **data: Any):
        if not PYDANTIC_AVAILABLE:
            self.version = data.get("version", TOPOLOGY_CONFIG_VERSION)
            self.nodes = data.get("nodes", [])
        else:
            super().__init__(**data)


# ---------------------------------------------------------------------------
# Enums and dataclasses
# ---------------------------------------------------------------------------

class RoutingStrategy(Enum):
    """路由策略枚举"""
    LOAD_BALANCED = "load_balanced"       # 负载均衡
    SHORTEST_PATH = "shortest_path"       # 最短路径
    DOMAIN_AFFINITY = "domain_affinity"   # 域亲和
    LAYER_PRIORITY = "layer_priority"     # 层级优先


@dataclass
class NodeInfo:
    """节点信息数据类"""
    node_id: str
    node_name: str
    layer: str                                    # "core", "cognitive", "perception"
    domain: str                                   # "vision", "nlu", "state_management", etc.
    coordinates: Tuple[float, float, float]       # (theta, phi, radius) 球面坐标
    capabilities: List[str]
    neighbors: List[str]
    api_url: str
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


class TopologyManager:
    """
    三层球体拓扑管理器

    管理 103 个节点的三层球体拓扑结构:
    - Core Layer (16 nodes): 核心层 - 系统管理和协调
    - Cognitive Layer (46 nodes): 认知层 - 智能处理和分析
    - Perception Layer (31 nodes): 感知层 - 数据采集和感知

    使用 NetworkX 构建拓扑图，支持:
    - 最短路径算法
    - 负载均衡
    - 域亲和路由
    - 拓扑可视化
    """

    def __init__(self, topology_config_path: Optional[str] = None) -> None:
        """
        初始化拓扑管理器

        Args:
            topology_config_path: 拓扑配置文件路径 (JSON)，
                如果为 None，从环境变量 FUSION_TOPOLOGY_CONFIG 读取
        """
        if not NX_AVAILABLE:
            raise ImportError(
                "networkx is required for TopologyManager. "
                "Install it with: pip install networkx"
            )
        # Resolve config path from argument or environment variable
        if topology_config_path is None:
            topology_config_path = os.environ.get(DEFAULT_TOPOLOGY_CONFIG_PATH_ENV)
        if not topology_config_path:
            raise ValueError(
                "topology_config_path is required (or set FUSION_TOPOLOGY_CONFIG env var)"
            )
        self.config_path: Path = Path(topology_config_path)
        self.graph: Any = nx.DiGraph()  # 有向图
        self.nodes: Dict[str, NodeInfo] = {}

        # 层级索引
        self.layers: Dict[str, List[str]] = {
            LAYER_CORE: [],
            LAYER_COGNITIVE: [],
            LAYER_PERCEPTION: []
        }

        # 域索引
        self.domains: Dict[str, List[str]] = {}

        # 负载跟踪
        self.load_tracker: Dict[str, float] = {}

        # 能力索引
        self.capability_index: Dict[str, List[str]] = {}

        # 加载拓扑
        self._load_topology()

        logger.info("TopologyManager initialized with %d nodes", len(self.nodes))

    def _load_topology(self) -> None:
        """加载并验证拓扑配置"""
        logger.info("Loading topology from %s", self.config_path)

        if not self.config_path.exists():
            raise FileNotFoundError(f"Topology config not found: {self.config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            raw_config: Dict[str, Any] = json.load(f)

        # 验证配置
        try:
            config_model = TopologyConfigModel(**raw_config)
            logger.info("Topology config validated (version: %s)", config_model.version)
        except Exception as exc:
            logger.warning("Topology config validation warning: %s", exc)

        # 验证配置版本
        version: str = raw_config.get('version', TOPOLOGY_CONFIG_VERSION)
        logger.info("Topology config version: %s", version)

        # 加载节点
        for node_data in raw_config['nodes']:
            node: NodeInfo = NodeInfo(
                node_id=node_data['id'],
                node_name=node_data['name'],
                layer=node_data['layer'],
                domain=node_data['domain'],
                coordinates=(
                    node_data['coordinates']['theta'],
                    node_data['coordinates']['phi'],
                    node_data['coordinates']['radius']
                ),
                capabilities=node_data.get('capabilities', []),
                neighbors=node_data.get('neighbors', []),
                api_url=node_data.get('api_url', ''),
                metadata=node_data.get('metadata', {})
            )

            # 添加到节点字典
            self.nodes[node.node_id] = node

            # 添加到层级索引
            if node.layer not in self.layers:
                self.layers[node.layer] = []
            self.layers[node.layer].append(node.node_id)

            # 添加到域索引
            if node.domain not in self.domains:
                self.domains[node.domain] = []
            self.domains[node.domain].append(node.node_id)

            # 添加到能力索引
            for cap in node.capabilities:
                if cap not in self.capability_index:
                    self.capability_index[cap] = []
                self.capability_index[cap].append(node.node_id)

            # 添加到图
            self.graph.add_node(
                node.node_id,
                layer=node.layer,
                domain=node.domain,
                coordinates=node.coordinates,
                capabilities=node.capabilities
            )

            # 初始化负载
            self.load_tracker[node.node_id] = 0.0

        # 添加边 (基于邻居关系)
        for node_id, node in self.nodes.items():
            for neighbor_id in node.neighbors:
                if neighbor_id in self.nodes:
                    # 计算边权重 (基于球面距离)
                    weight: float = self._calculate_distance(node_id, neighbor_id)
                    self.graph.add_edge(node_id, neighbor_id, weight=weight)

        logger.info("Topology loaded: %d nodes, %d edges", len(self.nodes), len(self.graph.edges))
        logger.info("Layers: %s", [(k, len(v)) for k, v in self.layers.items()])
        logger.info("Domains: %s", list(self.domains.keys()))

    def _calculate_distance(self, node_id_1: str, node_id_2: str) -> float:
        """
        计算两个节点之间的球面距离

        使用球面坐标 (theta, phi, radius)
        """
        node1: NodeInfo = self.nodes[node_id_1]
        node2: NodeInfo = self.nodes[node_id_2]

        theta1, phi1, r1 = node1.coordinates
        theta2, phi2, r2 = node2.coordinates

        # 转换为笛卡尔坐标
        x1: float = r1 * math.sin(theta1) * math.cos(phi1)
        y1: float = r1 * math.sin(theta1) * math.sin(phi1)
        z1: float = r1 * math.cos(theta1)

        x2: float = r2 * math.sin(theta2) * math.cos(phi2)
        y2: float = r2 * math.sin(theta2) * math.sin(phi2)
        z2: float = r2 * math.cos(theta2)

        distance: float = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)

        return distance

    def find_best_node(
        self,
        domain: Optional[str] = None,
        layer: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        source_node: Optional[str] = None,
        strategy: RoutingStrategy = RoutingStrategy.LOAD_BALANCED,
        exclude_nodes: Optional[List[str]] = None
    ) -> Optional[str]:
        """
        查找最佳节点

        Args:
            domain: 目标域
            layer: 目标层级
            capabilities: 所需能力列表
            source_node: 源节点 (用于路径优化)
            strategy: 路由策略
            exclude_nodes: 排除的节点列表

        Returns:
            最佳节点 ID，如果没有找到则返回 None
        """
        # 1. 筛选候选节点
        candidates: List[str] = self._filter_candidates(
            domain=domain,
            layer=layer,
            capabilities=capabilities,
            exclude_nodes=exclude_nodes or []
        )

        if not candidates:
            logger.warning(
                "No candidates found for domain=%s, layer=%s, capabilities=%s",
                domain, layer, capabilities
            )
            return None

        logger.debug("Found %d candidate nodes", len(candidates))

        # 2. 根据策略选择
        if strategy == RoutingStrategy.LOAD_BALANCED:
            selected: str = self._select_by_load(candidates)
        elif strategy == RoutingStrategy.SHORTEST_PATH and source_node:
            selected = self._select_by_path(candidates, source_node)
        elif strategy == RoutingStrategy.DOMAIN_AFFINITY:
            selected = self._select_by_domain(candidates, domain)
        elif strategy == RoutingStrategy.LAYER_PRIORITY:
            selected = self._select_by_layer(candidates, layer)
        else:
            # 默认: 负载均衡
            selected = self._select_by_load(candidates)

        logger.info(
            "Selected node: %s (strategy=%s, load=%.2f)",
            selected, strategy.value, self.load_tracker.get(selected, 0.0)
        )

        return selected

    def _filter_candidates(
        self,
        domain: Optional[str],
        layer: Optional[str],
        capabilities: Optional[List[str]],
        exclude_nodes: List[str]
    ) -> List[str]:
        """筛选候选节点"""
        candidates: Set[str] = set(self.nodes.keys())

        # 排除节点
        if exclude_nodes:
            candidates -= set(exclude_nodes)

        # 按域筛选
        if domain and domain in self.domains:
            candidates &= set(self.domains[domain])

        # 按层级筛选
        if layer and layer in self.layers:
            candidates &= set(self.layers[layer])

        # 按能力筛选
        if capabilities:
            for cap in capabilities:
                if cap in self.capability_index:
                    candidates &= set(self.capability_index[cap])
                else:
                    # 如果某个能力不存在，返回空集
                    return []

        return list(candidates)

    def _select_by_load(self, candidates: List[str]) -> str:
        """按负载选择 (选择负载最低的)"""
        return min(candidates, key=lambda n: self.load_tracker.get(n, 0.0))

    def _select_by_path(self, candidates: List[str], source_node: str) -> str:
        """按路径长度选择 (选择最短路径)"""
        if source_node not in self.graph:
            logger.warning("Source node %s not in graph, fallback to load balancing", source_node)
            return self._select_by_load(candidates)

        # 计算到每个候选节点的最短路径
        paths: Dict[str, float] = {}
        for candidate in candidates:
            try:
                path_length: float = nx.shortest_path_length(
                    self.graph, source_node, candidate, weight='weight'
                )
                paths[candidate] = path_length
            except nx.NetworkXNoPath:
                paths[candidate] = float('inf')

        # 选择最短路径
        return min(paths, key=paths.get)

    def _select_by_domain(self, candidates: List[str], domain: Optional[str]) -> str:
        """按域亲和选择 (优先选择同域节点)"""
        if domain:
            # 优先选择同域节点
            same_domain: List[str] = [n for n in candidates if self.nodes[n].domain == domain]
            if same_domain:
                return self._select_by_load(same_domain)

        return self._select_by_load(candidates)

    def _select_by_layer(self, candidates: List[str], layer: Optional[str]) -> str:
        """按层级优先选择"""
        if layer:
            # 优先选择指定层级
            same_layer: List[str] = [n for n in candidates if self.nodes[n].layer == layer]
            if same_layer:
                return self._select_by_load(same_layer)

        return self._select_by_load(candidates)

    def get_node_info(self, node_id: str) -> Optional[NodeInfo]:
        """获取节点信息"""
        return self.nodes.get(node_id)

    def get_layer_nodes(self, layer: str) -> List[str]:
        """获取指定层级的所有节点"""
        return self.layers.get(layer, [])

    def get_domain_nodes(self, domain: str) -> List[str]:
        """获取指定域的所有节点"""
        return self.domains.get(domain, [])

    def get_nodes_by_capability(self, capability: str) -> List[str]:
        """获取具有指定能力的所有节点"""
        return self.capability_index.get(capability, [])

    def update_load(self, node_id: str, load_delta: float) -> None:
        """
        更新节点负载

        Args:
            node_id: 节点 ID
            load_delta: 负载变化量（正数增加，负数减少）
        """
        if node_id in self.load_tracker:
            self.load_tracker[node_id] += load_delta
            self.load_tracker[node_id] = max(0.0, self.load_tracker[node_id])
            logger.debug("Node %s load updated: %.2f", node_id, self.load_tracker[node_id])
        else:
            logger.warning("Node %s not found in load tracker", node_id)

    def get_load(self, node_id: str) -> float:
        """获取节点负载"""
        return self.load_tracker.get(node_id, 0.0)

    def get_topology_stats(self) -> Dict[str, Any]:
        """获取拓扑统计信息"""
        total_nodes: int = len(self.nodes)
        avg_load: float = (sum(self.load_tracker.values()) / len(self.load_tracker)
                           if self.load_tracker else 0.0)
        max_load: float = max(self.load_tracker.values()) if self.load_tracker else 0.0
        min_load: float = min(self.load_tracker.values()) if self.load_tracker else 0.0
        return {
            "total_nodes": total_nodes,
            "layers": {k: len(v) for k, v in self.layers.items()},
            "domains": {k: len(v) for k, v in self.domains.items()},
            "total_edges": len(self.graph.edges),
            "average_load": avg_load,
            "max_load": max_load,
            "min_load": min_load
        }

    def get_shortest_path(self, source: str, target: str) -> Optional[List[str]]:
        """
        获取两个节点之间的最短路径

        Args:
            source: 源节点 ID
            target: 目标节点 ID

        Returns:
            路径节点列表，如果不存在路径则返回 None
        """
        try:
            path: List[str] = nx.shortest_path(self.graph, source, target, weight='weight')
            return path
        except nx.NetworkXNoPath:
            logger.warning("No path found between %s and %s", source, target)
            return None

    def export_topology(self, output_path: str) -> None:
        """
        导出拓扑为 JSON 文件

        Args:
            output_path: 输出文件路径
        """
        data: Dict[str, Any] = {
            "version": TOPOLOGY_CONFIG_VERSION,
            "nodes": [node.to_dict() for node in self.nodes.values()],
            "edges": [
                {
                    "source": u,
                    "target": v,
                    "weight": self.graph[u][v].get('weight', 1.0)
                }
                for u, v in self.graph.edges()
            ],
            "stats": self.get_topology_stats()
        }

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Topology exported to %s", output_path)

    def visualize_topology(self, output_path: str) -> None:
        """
        可视化拓扑 (生成图片)

        Args:
            output_path: 输出图片路径
        """
        try:
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D

            fig = plt.figure(figsize=(12, 10))
            ax = fig.add_subplot(111, projection='3d')

            # 绘制节点
            for node_id, node in self.nodes.items():
                theta, phi, r = node.coordinates

                # 转换为笛卡尔坐标
                x: float = r * math.sin(theta) * math.cos(phi)
                y: float = r * math.sin(theta) * math.sin(phi)
                z: float = r * math.cos(theta)

                color: str = LAYER_COLORS.get(node.layer, "gray")
                ax.scatter(x, y, z, c=color, s=100, alpha=0.6)
                ax.text(x, y, z, node.node_id, fontsize=6)

            # 绘制边
            for u, v in self.graph.edges():
                node_u: NodeInfo = self.nodes[u]
                node_v: NodeInfo = self.nodes[v]

                theta_u, phi_u, r_u = node_u.coordinates
                theta_v, phi_v, r_v = node_v.coordinates

                x_u: float = r_u * math.sin(theta_u) * math.cos(phi_u)
                y_u: float = r_u * math.sin(theta_u) * math.sin(phi_u)
                z_u: float = r_u * math.cos(theta_u)

                x_v: float = r_v * math.sin(theta_v) * math.cos(phi_v)
                y_v: float = r_v * math.sin(theta_v) * math.sin(phi_v)
                z_v: float = r_v * math.cos(theta_v)

                ax.plot([x_u, x_v], [y_u, y_v], [z_u, z_v], 'k-', alpha=0.2)

            ax.set_xlabel('X')
            ax.set_ylabel('Y')
            ax.set_zlabel('Z')
            ax.set_title('Galaxy - Three-Layer Sphere Topology')

            plt.savefig(output_path, dpi=300, bbox_inches='tight')
            plt.close()

            logger.info("Topology visualization saved to %s", output_path)

        except ImportError:
            logger.warning("matplotlib not available, skipping visualization")
