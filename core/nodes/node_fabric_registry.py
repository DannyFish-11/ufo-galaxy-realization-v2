"""
core/nodes/node_fabric_registry.py
=====================================
Galaxy Node Fabric Registry — Block-6 / PR-6

单一注册表统一管理 100+ 节点的生命周期、健康状态、依赖关系和可发现性。

设计原则：
  - 纯内存，线程安全，进程级单例
  - 节点注册/注销/心跳/状态更新
  - 依赖声明与依赖图查询
  - 健康评分（基于心跳 + 错误率）
  - 节点能力声明 → 同步到 CapabilityRegistry
  - 可发现：按类型 / 能力 / 健康状态查询

与 SSOT（UnifiedDeviceManager）的关系：
  NodeFabricRegistry 管理"计算/服务节点"（worker / service / agent 节点），
  UnifiedDeviceManager 管理"物理/虚拟设备"（手机、平板、电脑等终端设备）。
  两者相互补充，不重叠。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("Galaxy.Nodes.NodeFabricRegistry")

# ─────────────────────────────────────────────────────────────────────────────
# 枚举 / 常量
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_HEARTBEAT_TTL: float = 60.0      # 节点心跳超时（秒）
_DEFAULT_STALE_CAP_TTL: float = 300.0     # 能力条目过期（秒）；0 = 永不过期


class NodeStatus(str, Enum):
    """节点运行状态。"""

    STARTING = "starting"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    OFFLINE = "offline"
    DRAINING = "draining"


class NodeRole(str, Enum):
    """节点角色分类。"""

    WORKER = "worker"          # 通用工作节点
    AGENT = "agent"            # Agent 推理节点
    GATEWAY = "gateway"        # 网关节点
    SCHEDULER = "scheduler"    # 调度节点
    STORAGE = "storage"        # 存储/向量节点
    TOOL = "tool"              # MCP/Tool 服务节点
    MONITOR = "monitor"        # 监控/告警节点
    CUSTOM = "custom"          # 自定义角色


class NodeArchitecturalClass(str, Enum):
    """Node architectural classification for the OpenClawd capability architecture.

    Every registered node must carry one of these classes so that the fabric
    registry—and downstream consumers such as OpenClawd—can determine how to
    treat the node without inspecting its name or role heuristically.

    ``CAPABILITY_NODE``
        Healthy nodes that expose callable capabilities/actions to OpenClawd.
        These are the *only* nodes whose capabilities are surfaced into the
        CapabilityRegistry (capability bus).  They are represented as
        ``node__<node_id>__<action>`` entries and serve OpenClawd directly.

    ``SERVICE_NODE``
        Specialised backend providers (e.g. OCR, vision, knowledge retrieval,
        embedding engines).  They may be invoked through internal service
        adapters but must **not** be treated as capability sources or
        orchestration authorities.  New code should access them through an
        explicit service/provider interface, not via direct node imports.

    ``LEGACY_ORCHESTRATOR_NODE``
        Historical multi-node orchestrator entrypoints that previously acted
        as parallel system brains (e.g. Node_110, Node_81, Node_50).
        These are explicitly demoted: they must not be primary entry surfaces,
        and their orchestration paths are guarded by
        ``core.orchestration_authority.legacy_paths``.  Kept for thin-wrapper
        compatibility only; no new work should depend on them.

    ``EXPERIMENTAL_NODE``
        In-development or prototype nodes not yet promoted to a stable class.
        These are excluded from capability sync until explicitly promoted.

    ``ARCHIVED_NODE``
        Nodes that are kept for historical reference only and should never be
        invoked in a live system.  Capability sync is always skipped.
    """

    CAPABILITY_NODE = "capability_node"
    SERVICE_NODE = "service_node"
    LEGACY_ORCHESTRATOR_NODE = "legacy_orchestrator_node"
    EXPERIMENTAL_NODE = "experimental_node"
    ARCHIVED_NODE = "archived_node"


#: Set of architectural classes whose capabilities are eligible for injection
#: into the CapabilityRegistry (OpenClawd capability bus).
#: Only CAPABILITY_NODE nodes are surfaced as capabilities.
_CAPABILITY_SYNC_ELIGIBLE: frozenset = frozenset({
    NodeArchitecturalClass.CAPABILITY_NODE,
})


# ─────────────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class NodeCapability:
    """节点声明的单项能力。"""

    name: str
    """能力标识符（如 "llm_inference"、"vision"、"tool_execution"）"""

    description: str = ""
    """能力功能描述"""

    parameters: Dict[str, Any] = field(default_factory=dict)
    """JSON Schema 参数声明（可选）"""

    registered_at: float = field(default_factory=time.monotonic)
    """注册时间戳（monotonic）"""


@dataclass
class NodeInfo:
    """节点注册信息（主记录）。"""

    node_id: str
    """唯一节点 ID（建议格式：<role>-<hostname>-<port> 或 UUID）"""

    role: NodeRole = NodeRole.WORKER
    """节点角色"""

    architectural_class: NodeArchitecturalClass = NodeArchitecturalClass.CAPABILITY_NODE
    """Architectural classification of this node.

    Determines how OpenClawd and the capability bus treat the node:
    - CAPABILITY_NODE: capabilities surfaced to OpenClawd via CapabilityRegistry.
    - SERVICE_NODE: backend-only; not exposed as capabilities.
    - LEGACY_ORCHESTRATOR_NODE: demoted; not exposed as capabilities; guarded.
    - EXPERIMENTAL_NODE / ARCHIVED_NODE: excluded from capability sync.

    Contributors: set this field explicitly when registering a node so that
    its architectural role is unambiguous.  Use CAPABILITY_NODE only if the
    node genuinely exposes actions for OpenClawd to invoke.
    """

    host: str = "localhost"
    """节点主机地址"""

    port: int = 0
    """节点监听端口（0 = 未知）"""

    status: NodeStatus = NodeStatus.STARTING
    """当前运行状态"""

    capabilities: List[NodeCapability] = field(default_factory=list)
    """节点声明的能力列表"""

    dependencies: List[str] = field(default_factory=list)
    """依赖的其他节点 ID 列表"""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """附加元数据（版本、标签等）"""

    # 运行时字段（不由注册者填写）
    registered_at: float = field(default_factory=time.monotonic)
    last_heartbeat: float = field(default_factory=time.monotonic)
    error_count: int = 0
    heartbeat_count: int = 0

    # ──────────────────────────────────────────────
    # 计算属性
    # ──────────────────────────────────────────────

    def heartbeat_age_secs(self) -> float:
        """距上次心跳的秒数。"""
        return time.monotonic() - self.last_heartbeat

    def health_score(self, heartbeat_ttl: float = _DEFAULT_HEARTBEAT_TTL) -> float:
        """
        健康评分 [0.0, 1.0]。

        算法：
          base = 1.0
          - 心跳超时 → 0.0
          - error_count 扣分：每 error 扣 0.05，最多扣到 0.5
        """
        if self.heartbeat_age_secs() > heartbeat_ttl:
            return 0.0
        error_penalty = min(self.error_count * 0.05, 0.5)
        return max(0.0, 1.0 - error_penalty)

    def is_healthy(self, heartbeat_ttl: float = _DEFAULT_HEARTBEAT_TTL) -> bool:
        return self.health_score(heartbeat_ttl) >= 0.5

    def capability_names(self) -> List[str]:
        return [c.name for c in self.capabilities]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "role": self.role.value if isinstance(self.role, NodeRole) else self.role,
            "architectural_class": (
                self.architectural_class.value
                if isinstance(self.architectural_class, NodeArchitecturalClass)
                else self.architectural_class
            ),
            "host": self.host,
            "port": self.port,
            "status": self.status.value if isinstance(self.status, NodeStatus) else self.status,
            "capabilities": [c.name for c in self.capabilities],
            "dependencies": list(self.dependencies),
            "metadata": dict(self.metadata),
            "registered_at": self.registered_at,
            "last_heartbeat": self.last_heartbeat,
            "heartbeat_age_secs": round(self.heartbeat_age_secs(), 2),
            "health_score": round(self.health_score(), 4),
            "error_count": self.error_count,
            "heartbeat_count": self.heartbeat_count,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 注册表主体
# ─────────────────────────────────────────────────────────────────────────────


class NodeFabricRegistry:
    """
    Node Fabric 统一注册表（进程级单例，线程安全）。

    公开 API：
        register(node_info)          — 注册节点
        unregister(node_id)          — 注销节点
        heartbeat(node_id, ...)      — 更新心跳
        update_status(node_id, ...)  — 更新状态
        record_error(node_id)        — 记录错误
        get(node_id)                 — 获取节点
        list_nodes()                 — 列出所有节点
        list_by_role(role)           — 按角色查询
        list_by_capability(cap)      — 按能力查询
        list_healthy()               — 列出健康节点
        get_dependency_graph()       — 获取依赖图
        sync_capabilities()          — 同步能力到 CapabilityRegistry
        expire_stale_capabilities()  — 清理过期能力
        get_metrics()                — 获取统计指标
    """

    _instance: Optional["NodeFabricRegistry"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "NodeFabricRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(
        self,
        heartbeat_ttl: float = _DEFAULT_HEARTBEAT_TTL,
        stale_cap_ttl: float = _DEFAULT_STALE_CAP_TTL,
    ) -> None:
        if self._initialized:  # type: ignore[has-type]
            return

        self._nodes: Dict[str, NodeInfo] = {}
        self._rw_lock = threading.RLock()
        self._heartbeat_ttl = heartbeat_ttl
        self._stale_cap_ttl = stale_cap_ttl
        self._initialized = True

        logger.info(
            "NodeFabricRegistry initialized",
            extra={"event": "init", "heartbeat_ttl": heartbeat_ttl},
        )

    # ──────────────────────────────────────────────────────────────────
    # 生命周期管理
    # ──────────────────────────────────────────────────────────────────

    def register(self, node_info: NodeInfo) -> None:
        """注册一个节点（幂等：重复注册将覆盖）。"""
        with self._rw_lock:
            is_update = node_info.node_id in self._nodes
            self._nodes[node_info.node_id] = node_info
            logger.info(
                "Node %s: %s",
                "updated" if is_update else "registered",
                node_info.node_id,
                extra={
                    "event": "node_register",
                    "node_id": node_info.node_id,
                    "role": str(node_info.role),
                    "capabilities": node_info.capability_names(),
                },
            )

    def unregister(self, node_id: str) -> bool:
        """注销节点。返回 True 表示节点存在并已移除。"""
        with self._rw_lock:
            removed = self._nodes.pop(node_id, None)
            if removed:
                logger.info(
                    "Node unregistered: %s", node_id,
                    extra={"event": "node_unregister", "node_id": node_id},
                )
                return True
            logger.debug("unregister: node not found: %s", node_id)
            return False

    def heartbeat(
        self,
        node_id: str,
        status: Optional[NodeStatus] = None,
        metadata_patch: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        更新节点心跳时间戳。

        Args:
            node_id: 目标节点 ID。
            status: 可选 — 同时更新节点状态。
            metadata_patch: 可选 — 深度合并到节点 metadata。

        Returns:
            True = 节点存在且已更新；False = 节点不存在。
        """
        with self._rw_lock:
            node = self._nodes.get(node_id)
            if node is None:
                logger.debug("heartbeat: unknown node %s", node_id)
                return False
            node.last_heartbeat = time.monotonic()
            node.heartbeat_count += 1
            if status is not None:
                node.status = status
            elif node.status in (NodeStatus.OFFLINE, NodeStatus.UNHEALTHY):
                node.status = NodeStatus.HEALTHY
            if metadata_patch:
                merged = dict(node.metadata)
                merged.update(metadata_patch)
                node.metadata = merged
            return True

    def update_status(self, node_id: str, status: NodeStatus) -> bool:
        """显式更新节点状态。"""
        with self._rw_lock:
            node = self._nodes.get(node_id)
            if node is None:
                return False
            node.status = status
            return True

    def record_error(self, node_id: str) -> None:
        """为节点累加错误计数（影响健康评分）。"""
        with self._rw_lock:
            node = self._nodes.get(node_id)
            if node:
                node.error_count += 1
                if node.error_count >= 10:
                    node.status = NodeStatus.UNHEALTHY

    def mark_offline_if_stale(self) -> List[str]:
        """扫描所有节点，心跳超时的标记为 OFFLINE。返回被标记的节点 ID 列表。"""
        stale: List[str] = []
        with self._rw_lock:
            for node_id, node in self._nodes.items():
                if (
                    node.status not in (NodeStatus.OFFLINE, NodeStatus.DRAINING)
                    and node.heartbeat_age_secs() > self._heartbeat_ttl
                ):
                    node.status = NodeStatus.OFFLINE
                    stale.append(node_id)
        if stale:
            logger.warning(
                "Marked %d stale node(s) as OFFLINE: %s", len(stale), stale,
                extra={"event": "nodes_offline", "node_ids": stale},
            )
        return stale

    # ──────────────────────────────────────────────────────────────────
    # 查询接口
    # ──────────────────────────────────────────────────────────────────

    def get(self, node_id: str) -> Optional[NodeInfo]:
        """按 ID 获取节点信息。"""
        with self._rw_lock:
            return self._nodes.get(node_id)

    def list_nodes(self) -> List[NodeInfo]:
        """返回所有已注册节点的列表副本。"""
        with self._rw_lock:
            return list(self._nodes.values())

    def list_by_role(self, role: NodeRole) -> List[NodeInfo]:
        """按角色过滤节点。"""
        with self._rw_lock:
            return [n for n in self._nodes.values() if n.role == role]

    def list_by_capability(self, capability: str) -> List[NodeInfo]:
        """返回具有指定能力的节点列表。"""
        with self._rw_lock:
            return [
                n for n in self._nodes.values()
                if any(c.name == capability for c in n.capabilities)
            ]

    def list_healthy(self) -> List[NodeInfo]:
        """返回所有健康节点（health_score >= 0.5）。"""
        with self._rw_lock:
            return [
                n for n in self._nodes.values()
                if n.is_healthy(self._heartbeat_ttl)
            ]

    def list_by_architectural_class(
        self, architectural_class: NodeArchitecturalClass
    ) -> List[NodeInfo]:
        """Return all nodes with the given :class:`NodeArchitecturalClass`.

        Use this to find, for example, all CAPABILITY_NODE nodes that are
        eligible for capability-bus surfacing, or all LEGACY_ORCHESTRATOR_NODE
        nodes that need guardrail enforcement.
        """
        with self._rw_lock:
            return [
                n for n in self._nodes.values()
                if n.architectural_class == architectural_class
            ]

    def count(self) -> int:
        """返回当前注册节点总数。"""
        with self._rw_lock:
            return len(self._nodes)

    # ──────────────────────────────────────────────────────────────────
    # 依赖图
    # ──────────────────────────────────────────────────────────────────

    def get_dependency_graph(self) -> Dict[str, List[str]]:
        """
        返回节点依赖关系图（邻接表）。

        Returns:
            {node_id: [dep_node_id, ...]}
        """
        with self._rw_lock:
            return {n.node_id: list(n.dependencies) for n in self._nodes.values()}

    def get_dependents(self, node_id: str) -> List[str]:
        """返回所有依赖 node_id 的节点（反向依赖）。"""
        with self._rw_lock:
            return [
                n.node_id for n in self._nodes.values()
                if node_id in n.dependencies
            ]

    # ──────────────────────────────────────────────────────────────────
    # 能力同步
    # ──────────────────────────────────────────────────────────────────

    def sync_capabilities_to_registry(self) -> int:
        """
        将所有健康的 CAPABILITY_NODE 节点的能力同步注入 CapabilityRegistry（OpenClawd capability bus）。

        Only nodes with ``architectural_class == CAPABILITY_NODE`` are
        synchronised.  SERVICE_NODE, LEGACY_ORCHESTRATOR_NODE, EXPERIMENTAL_NODE,
        and ARCHIVED_NODE nodes are intentionally excluded:

        - SERVICE_NODE   → accessed through explicit service/provider adapters.
        - LEGACY_ORCHESTRATOR_NODE → demoted; guarded by legacy_paths; no
          new capability entries should be created for them.
        - EXPERIMENTAL_NODE / ARCHIVED_NODE → not ready / not active.

        Returns:
            注入的能力条目数量。
        """
        try:
            from core.agent.capability_registry import CapabilityRegistry, CapabilityItem  # noqa: PLC0415
        except ImportError:
            logger.warning("CapabilityRegistry not available; skipping capability sync")
            return 0

        registry = CapabilityRegistry.get_instance()
        injected = 0
        skipped_non_capability = 0

        with self._rw_lock:
            for node in self._nodes.values():
                # Only CAPABILITY_NODE nodes are surfaced to OpenClawd.
                if node.architectural_class not in _CAPABILITY_SYNC_ELIGIBLE:
                    skipped_non_capability += 1
                    logger.debug(
                        "Skipping capability sync for node %s "
                        "(architectural_class=%s; not a CAPABILITY_NODE)",
                        node.node_id,
                        node.architectural_class.value
                        if isinstance(node.architectural_class, NodeArchitecturalClass)
                        else node.architectural_class,
                    )
                    continue
                if not node.is_healthy(self._heartbeat_ttl):
                    continue
                for cap in node.capabilities:
                    key = f"node__{node.node_id}__{cap.name}"
                    item = CapabilityItem(
                        name=key,
                        description=(
                            f"[Node:{node.node_id}:{node.role}] "
                            f"{cap.description or cap.name}"
                        ),
                        source="node",
                        source_id=node.node_id,
                        parameters=cap.parameters,
                        available=True,
                        metadata={
                            "node_id": node.node_id,
                            "node_role": str(node.role),
                            "node_architectural_class": (
                                node.architectural_class.value
                                if isinstance(node.architectural_class, NodeArchitecturalClass)
                                else node.architectural_class
                            ),
                            "host": node.host,
                            "port": node.port,
                            "registered_at": cap.registered_at,
                        },
                    )
                    registry.inject_item(item)
                    injected += 1

        if injected:
            logger.info(
                "Node capability sync: injected %d items into CapabilityRegistry "
                "(skipped %d non-capability nodes)",
                injected,
                skipped_non_capability,
                extra={
                    "event": "node_capability_sync",
                    "injected": injected,
                    "skipped_non_capability": skipped_non_capability,
                },
            )
        return injected

    def expire_stale_capabilities(self, ttl: Optional[float] = None) -> int:
        """
        从 CapabilityRegistry 中移除来源为 "node" 且超过 TTL 的节点能力条目。

        Args:
            ttl: 过期阈值（秒），默认使用实例配置的 stale_cap_ttl。

        Returns:
            移除的条目数量。
        """
        effective_ttl = ttl if ttl is not None else self._stale_cap_ttl
        if effective_ttl <= 0:
            return 0

        try:
            from core.agent.capability_registry import CapabilityRegistry  # noqa: PLC0415
        except ImportError:
            return 0

        registry = CapabilityRegistry.get_instance()
        now = time.monotonic()
        expired_keys: List[str] = []

        with registry._lock:
            for key, item in list(registry._items.items()):
                if item.source != "node":
                    continue
                registered_at = item.metadata.get("registered_at", now)
                if (now - registered_at) > effective_ttl:
                    expired_keys.append(key)
            for k in expired_keys:
                registry._items.pop(k, None)

        if expired_keys:
            logger.info(
                "Expired %d stale node capability items (ttl=%.0fs)",
                len(expired_keys), effective_ttl,
                extra={"event": "capability_expire", "count": len(expired_keys)},
            )
        return len(expired_keys)

    # ──────────────────────────────────────────────────────────────────
    # 指标
    # ──────────────────────────────────────────────────────────────────

    def get_metrics(self) -> Dict[str, Any]:
        """返回节点织物注册表的运行时指标快照。"""
        with self._rw_lock:
            total = len(self._nodes)
            by_status: Dict[str, int] = {}
            by_role: Dict[str, int] = {}
            by_architectural_class: Dict[str, int] = {}
            health_scores: List[float] = []

            for node in self._nodes.values():
                s = str(node.status.value if isinstance(node.status, NodeStatus) else node.status)
                by_status[s] = by_status.get(s, 0) + 1
                r = str(node.role.value if isinstance(node.role, NodeRole) else node.role)
                by_role[r] = by_role.get(r, 0) + 1
                ac = str(
                    node.architectural_class.value
                    if isinstance(node.architectural_class, NodeArchitecturalClass)
                    else node.architectural_class
                )
                by_architectural_class[ac] = by_architectural_class.get(ac, 0) + 1
                health_scores.append(node.health_score(self._heartbeat_ttl))

            healthy_count = sum(1 for s in health_scores if s >= 0.5)
            avg_health = (sum(health_scores) / len(health_scores)) if health_scores else 1.0

        return {
            "total_nodes": total,
            "healthy_nodes": healthy_count,
            "avg_health_score": round(avg_health, 4),
            "by_status": by_status,
            "by_role": by_role,
            "by_architectural_class": by_architectural_class,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 权威标记 / 哨兵 — 规范运行时节点注册表
# Authority sentinels — canonical runtime node registry
# ─────────────────────────────────────────────────────────────────────────────

#: Declares NodeFabricRegistry as the single canonical runtime node registry.
#: All runtime-facing node presence and status reads must converge on this
#: registry.  core.node_registry.NodeRegistry is a legacy compatibility facade.
CANONICAL_RUNTIME_NODE_REGISTRY_AUTHORITY: str = (
    "core.nodes.node_fabric_registry.NodeFabricRegistry is the single canonical "
    "runtime node registry for the Galaxy system.  All runtime-facing node presence "
    "and status reads must converge on this registry.  "
    "core.node_registry.NodeRegistry is a legacy compatibility facade only."
)

#: Machine-checkable sentinel confirming NodeFabricRegistry is the canonical
#: runtime node registry.  Import this symbol from test and integration code
#: to assert the canonical registry is available.
NODE_FABRIC_IS_CANONICAL_RUNTIME_REGISTRY_SENTINEL: str = (
    "NODE_FABRIC_REGISTRY::CANONICAL_RUNTIME_REGISTRY_AUTHORITY_V1"
)

#: Policy: system status endpoints must derive node runtime truth from
#: NodeFabricRegistry, not from legacy NodeRegistry.metadata dicts.
STATUS_ENDPOINTS_READ_FROM_CANONICAL_REGISTRY_POLICY: str = (
    "NODE_FABRIC_REGISTRY::STATUS_ENDPOINTS_READ_FROM_CANONICAL_REGISTRY_POLICY: "
    "system status endpoints must derive node runtime truth from NodeFabricRegistry, "
    "not from legacy NodeRegistry.metadata dicts.  The /api/v1/nodes/status endpoint "
    "reads from NodeFabricRegistry as the primary source and supplements with legacy "
    "metadata only for nodes not present in the canonical registry."
)

#: Policy: NodeRegistry (core.node_registry) is retained only as a backward-compat
#: facade.  No new runtime-authority logic should be added to NodeRegistry.
LEGACY_NODE_REGISTRY_IS_COMPAT_FACADE_ONLY_POLICY: str = (
    "NODE_FABRIC_REGISTRY::LEGACY_NODE_REGISTRY_IS_COMPAT_FACADE_ONLY_POLICY: "
    "core.node_registry.NodeRegistry is retained as a backward-compat facade. "
    "No new runtime-authority logic should be added to NodeRegistry.  "
    "New code must use NodeFabricRegistry for node runtime presence and status."
)


# ─────────────────────────────────────────────────────────────────────────────
# 模块级便捷函数
# ─────────────────────────────────────────────────────────────────────────────


def get_node_fabric_registry() -> NodeFabricRegistry:
    """返回全局 NodeFabricRegistry 单例。"""
    return NodeFabricRegistry()


def reset_node_fabric_registry() -> None:
    """重置 NodeFabricRegistry 单例（测试用）。"""
    NodeFabricRegistry._instance = None
