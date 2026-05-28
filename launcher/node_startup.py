"""
launcher/node_startup.py — Node system startup.

Responsibilities:
- NodeSystemLauncher: discover, configure, and start Galaxy nodes,
  including per-node health polling and runtime-registry registration.

Startup policy semantics (PR-7 node unification):
  "active"   — healthy, orchestrated node; started unconditionally.
  "optional" — runnable node with a valid role but needing work;
                started if available, failure does not abort the system.
  "skip"     — archived, deleted, or stub node; never included in any
                startup path.

The ``startup_policy`` field in ``node_dependencies.json`` is the canonical
authority for these distinctions.  Nodes whose policy is absent default to
``"active"``.

Callable-node baseline integration (PR-529 consolidation)
----------------------------------------------------------
:meth:`NodeSystemLauncher.get_callable_node_classification` queries the live
:class:`~core.nodes.node_fabric_registry.NodeFabricRegistry` (populated after
nodes register themselves) and cross-references it with
:func:`~core.callable_node_baseline.is_callable_by_openclawd` to separate:

- ``callable_nodes``    — Registered nodes that are truly callable by OpenClawd
                          (``CAPABILITY_NODE`` architectural class).
- ``service_nodes``     — Registered nodes with ``SERVICE_NODE`` class;
                          they run but do not expose capability tools.
- ``legacy_nodes``      — ``LEGACY_ORCHESTRATOR_NODE``; demoted facade nodes.
- ``non_callable_nodes``— ``EXPERIMENTAL_NODE`` or ``ARCHIVED_NODE``; not
                          surfaced into the tool catalog.
- ``unregistered_startup_nodes`` — Nodes in the startup config that have not
                          yet registered with NodeFabricRegistry (e.g. still
                          starting up or failed to connect).

Sentinel: :data:`CALLABLE_BASELINE_STARTUP_INTEGRATION`
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

# PR-FIX: relative imports changed to absolute imports so this module
# can be imported standalone (e.g. by validate_runtime.py).
# Previous: from .bootstrap import ... (failed with "attempted relative import with no known parent package")
try:
    from launcher.bootstrap import PROJECT_ROOT, print_status, ServiceType, SystemConfig
    from launcher.service_manager import ServiceManager
except ImportError:
    from .bootstrap import PROJECT_ROOT, print_status, ServiceType, SystemConfig
    from .service_manager import ServiceManager

logger = logging.getLogger("Galaxy")

# ---------------------------------------------------------------------------
# Phase-B consolidation sentinel
# ---------------------------------------------------------------------------

#: PR-529 callable-node baseline integration.
#:
#: Confirms that :meth:`NodeSystemLauncher.get_callable_node_classification`
#: is present and integrates :func:`~core.callable_node_baseline.is_callable_by_openclawd`
#: to programmatically distinguish startup-ready nodes from callable-capability
#: nodes, service-only nodes, and non-callable nodes.
#:
#: This sentinel is the programmatic assertion that the callable-node baseline
#: (defined in ``core/callable_node_baseline.py``) is wired into the startup
#: layer, not merely documented.
CALLABLE_BASELINE_STARTUP_INTEGRATION: str = (
    "CALLABLE_BASELINE_STARTUP_INTEGRATION_V1: "
    "NodeSystemLauncher.get_callable_node_classification() integrates "
    "core.callable_node_baseline.is_callable_by_openclawd() to separate "
    "startup-ready nodes from callable-capability nodes at runtime."
)

#: Sentinel confirming that canonical NodeFabricRegistry lifecycle hooks are
#: wired into NodeSystemLauncher.
#:
#: Confirms that node start success, start failure, health-check timeout, and
#: stop transitions all write directly into
#: :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry` via the
#: in-process helper ``_register_node_in_canonical_registry()``.  The HTTP
#: runtime registry call is retained as a secondary notification only.
CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS: str = (
    "CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS_V1: "
    "NodeSystemLauncher writes node lifecycle events (start success, start "
    "failure, health-check timeout, stop) directly into NodeFabricRegistry "
    "via _register_node_in_canonical_registry() as the primary canonical path. "
    "HTTP-based runtime registry notification is a secondary fallback only."
)

#: PR-7 discovery integration sentinel.
#:
#: Confirms that NodeSystemLauncher announces every successfully started node
#: into NodeDiscoveryService via announce_node_to_discovery() so the discovery
#: plane stays in sync with the fabric registry as nodes come online.
NODE_DISCOVERY_STARTUP_WIRED_PR7: str = (
    "NODE_DISCOVERY_STARTUP_WIRED_PR7_V1: "
    "NodeSystemLauncher._register_node_with_runtime_registry() calls "
    "core.node_discovery_runtime.announce_node_to_discovery() after every "
    "successful node health-check so that NodeDiscoveryService reflects the "
    "real startup state.  initialize_discovery_after_startup() seeds all "
    "healthy fabric-registry nodes into discovery after the initial batch completes."
)

#: PR-12 discovery startup seeding closure sentinel.
#:
#: Confirms that NodeSystemLauncher.start_all() calls
#: initialize_discovery_after_startup() after the node batch completes.
#: This closes the gap where the bulk seeding path was defined but never
#: invoked by real startup orchestration.
NODE_DISCOVERY_STARTUP_SEEDING_WIRED_PR12: str = (
    "NODE_DISCOVERY_STARTUP_SEEDING_WIRED_PR12_V1: "
    "NodeSystemLauncher.start_all() calls self.initialize_discovery_after_startup() "
    "after the node startup batch has completed.  This guarantees that "
    "NodeDiscoveryService is bulk-seeded from NodeFabricRegistry state at the "
    "end of every startup run, closing the integration gap from PR-7."
)


class NodeSystemLauncher:
    """节点系统启动器"""

    def __init__(self, service_manager: ServiceManager, config: SystemConfig) -> None:
        self.service_manager = service_manager
        self.config = config
        self.nodes_dir = PROJECT_ROOT / "nodes"
        self.node_configs = self._load_node_configs()

    def _load_node_configs(self) -> Dict[str, Any]:
        """加载节点配置

        从 node_dependencies.json 的 "nodes" 键读取（唯一权威来源）。
        config/node_registry.json 是生成的兼容性制品，不作为回退源。
        """
        primary = PROJECT_ROOT / "node_dependencies.json"

        if primary.exists():
            try:
                with open(primary, "r", encoding="utf-8") as f:
                    data = json.load(f)
                nodes = data.get("nodes", data) if isinstance(data, dict) else {}
                if nodes:
                    logger.info("节点配置已加载: %s (%d 个节点)", primary, len(nodes))
                    return nodes
                logger.warning("节点配置文件为空或格式异常: %s", primary)
            except Exception as exc:
                logger.warning("读取节点配置失败 %s: %s", primary, exc)

        logger.error(
            "未找到节点配置文件。已检查路径: %s。"
            "请确保 node_dependencies.json 存在于项目根目录。",
            primary,
        )
        return {}

    # ── Startup-policy helpers (PR-7) ─────────────────────────────────────────

    _POLICY_SKIP = "skip"
    _POLICY_OPTIONAL = "optional"
    _POLICY_ACTIVE = "active"

    def get_startup_policy(self, node_name: str) -> str:
        """Return the startup_policy for *node_name* from the loaded config.

        Falls back to ``"active"`` when the node is absent from config or
        the field is not set, for nodes that pre-date the PR-7 policy field.
        """
        cfg = self.node_configs.get(node_name)
        if isinstance(cfg, dict):
            return cfg.get("startup_policy", self._POLICY_ACTIVE)
        return self._POLICY_ACTIVE

    def should_skip(self, node_name: str) -> bool:
        """Return True when a node must be excluded from all startup paths.

        Nodes with ``startup_policy: "skip"`` are archived, deleted, or
        unfinished stubs.  They are registered in ``node_dependencies.json``
        for audit tracking only and must never be started by the launcher.
        """
        return self.get_startup_policy(node_name) == self._POLICY_SKIP

    def get_active_nodes(self) -> List[str]:
        """Return nodes eligible for startup — policy is 'active' or 'optional'.

        Nodes whose ``startup_policy`` is ``"skip"`` (Reserved placeholders,
        stubs, archived/deleted entries introduced by PR-7) are excluded.
        The result is sorted by config priority then name.
        """
        eligible = [
            name for name in self.node_configs
            if not self.should_skip(name)
            and (self.nodes_dir / name / "main.py").exists()
        ]

        def _sort_key(name: str):
            cfg = self.node_configs.get(name, {})
            priority = cfg.get("priority", 99) if isinstance(cfg, dict) else 99
            return (priority, name)

        return sorted(eligible, key=_sort_key)

    # ── Startup-tier model (PR-startup-tiers) ────────────────────────────────
    #
    # Three canonical tiers, derived from existing startup_policy + group
    # metadata.  No new governance authority is introduced; tiers are a
    # read-only view over node_dependencies.json.
    #
    # Core     — startup_policy="active" AND group="core"       (~13 nodes)
    # Standard — startup_policy="active" AND group in           (~30 nodes)
    #            {"core", "development"}
    # Full     — startup_policy in {"active", "optional"}       (~124 nodes)
    #            (same as get_active_nodes(); explicit for clarity)

    STARTUP_TIER_CORE = "Core"
    STARTUP_TIER_STANDARD = "Standard"
    STARTUP_TIER_FULL = "Full"

    _TIER_GROUPS: Dict[str, Optional[List[str]]] = {
        "Core": ["core"],
        "Standard": ["core", "development"],
        "Full": None,  # None = all non-skip (active + optional)
    }

    def get_tier_nodes(self, tier: str) -> List[str]:
        """Return the node list for the named startup tier.

        Tier semantics (derived from existing metadata — no new authority):

        - ``"Core"``     — ``startup_policy="active"`` AND ``group="core"``
        - ``"Standard"`` — ``startup_policy="active"`` AND
          ``group`` in ``{"core", "development"}``
        - ``"Full"``     — ``startup_policy`` in ``{"active", "optional"}``
          (equivalent to :meth:`get_active_nodes`)

        Args:
            tier: One of :attr:`STARTUP_TIER_CORE`, :attr:`STARTUP_TIER_STANDARD`,
                  or :attr:`STARTUP_TIER_FULL`.

        Returns:
            Sorted node list (by priority then name), filtered to nodes that
            have a ``main.py`` on disk.

        Raises:
            ValueError: If *tier* is not one of the three canonical values.
        """
        allowed_groups = self._TIER_GROUPS.get(tier)
        if tier not in self._TIER_GROUPS:
            raise ValueError(
                f"Unknown startup tier {tier!r}. "
                f"Valid tiers: {list(self._TIER_GROUPS)}"
            )

        result: List[str] = []
        for name, cfg in self.node_configs.items():
            if not isinstance(cfg, dict):
                continue
            policy = cfg.get("startup_policy", self._POLICY_ACTIVE)
            group = cfg.get("group")
            node_path = self.nodes_dir / name / "main.py"
            if not node_path.exists():
                continue
            if tier == self.STARTUP_TIER_FULL:
                if policy in (self._POLICY_ACTIVE, self._POLICY_OPTIONAL):
                    result.append(name)
            else:
                # Core / Standard: must be active policy AND in allowed group(s)
                if policy == self._POLICY_ACTIVE and group in allowed_groups:
                    result.append(name)

        def _sort_key(name: str):
            cfg = self.node_configs.get(name, {})
            priority = cfg.get("priority", 99) if isinstance(cfg, dict) else 99
            return (priority, name)

        return sorted(result, key=_sort_key)

    def get_readiness_baseline(self) -> Dict[str, Any]:
        """Return a compact active-node runtime-readiness baseline snapshot.

        The baseline distinguishes three node sets:
        - ``core_tier``     — Core tier nodes (structural runtime baseline)
        - ``standard_tier`` — Standard tier nodes (development baseline)
        - ``active_baseline`` — All active nodes that pass the minimum
          readiness bar (main.py + fusion_entry.py present)
        - ``optional_governed`` — Optional nodes with main.py and fusion_entry.py
          (governed; tracked toward active)
        - ``readiness_gaps`` — Active nodes missing fusion_entry.py
          (governance gap requiring remediation)

        Returns:
            dict with the above keys plus ``summary`` counts.
        """
        nodes_dir = self.nodes_dir
        core_tier = self.get_tier_nodes(self.STARTUP_TIER_CORE)
        standard_tier = self.get_tier_nodes(self.STARTUP_TIER_STANDARD)

        active_baseline: List[str] = []
        optional_governed: List[str] = []
        readiness_gaps: List[str] = []

        for name, cfg in self.node_configs.items():
            if not isinstance(cfg, dict):
                continue
            policy = cfg.get("startup_policy", self._POLICY_ACTIVE)
            node_dir = nodes_dir / name
            has_main = (node_dir / "main.py").exists()
            has_fusion = (node_dir / "fusion_entry.py").exists()

            if policy == self._POLICY_ACTIVE and has_main:
                if has_fusion:
                    active_baseline.append(name)
                else:
                    readiness_gaps.append(name)
            elif policy == self._POLICY_OPTIONAL and has_main and has_fusion:
                optional_governed.append(name)

        return {
            "core_tier": sorted(core_tier),
            "standard_tier": sorted(standard_tier),
            "active_baseline": sorted(active_baseline),
            "optional_governed": sorted(optional_governed),
            "readiness_gaps": sorted(readiness_gaps),
            "summary": {
                "core_tier_count": len(core_tier),
                "standard_tier_count": len(standard_tier),
                "active_baseline_count": len(active_baseline),
                "optional_governed_count": len(optional_governed),
                "readiness_gap_count": len(readiness_gaps),
            },
        }

    def get_callable_node_classification(self) -> Dict[str, Any]:
        """Return a runtime classification of nodes by callability.

        Queries the live :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry`
        and applies the callable-node baseline
        (:func:`~core.callable_node_baseline.is_callable_by_openclawd`) to
        classify each registered node into one of four buckets:

        - ``callable_nodes``    — Nodes with ``CAPABILITY_NODE`` architectural
          class; these are the only nodes surfaced as tools by OpenClawd.
        - ``service_nodes``     — Nodes with ``SERVICE_NODE`` class; they run
          but do not expose capability tools to OpenClawd.
        - ``legacy_nodes``      — Nodes with ``LEGACY_ORCHESTRATOR_NODE`` class;
          demoted facade nodes not surfaced in the tool catalog.
        - ``non_callable_nodes``— Nodes with ``EXPERIMENTAL_NODE`` or
          ``ARCHIVED_NODE`` class; excluded from tool exposure by design.
        - ``unregistered_startup_nodes`` — Nodes in the startup config (active
          or optional policy) that have not yet registered with
          NodeFabricRegistry (may still be starting or failed to connect).
        - ``classification_available`` — ``True`` when the NodeFabricRegistry
          and callable baseline were reachable; ``False`` when one or both
          imports failed (e.g. lightweight test environment).

        This method is the programmatic assertion that the callable-node
        baseline is wired into the startup layer, not merely documented.
        It satisfies the :data:`CALLABLE_BASELINE_STARTUP_INTEGRATION` sentinel.

        Returns:
            dict with the keys described above plus a ``summary`` sub-dict.
        """
        # Determine which nodes the startup config considers active.
        startup_node_names: set = set(
            name for name, cfg in self.node_configs.items()
            if isinstance(cfg, dict)
            and cfg.get("startup_policy", self._POLICY_ACTIVE) in (
                self._POLICY_ACTIVE, self._POLICY_OPTIONAL
            )
            and (self.nodes_dir / name / "main.py").exists()
        )

        callable_nodes: List[str] = []
        service_nodes: List[str] = []
        legacy_nodes: List[str] = []
        non_callable_nodes: List[str] = []
        classification_available = False

        try:
            from core.nodes.node_fabric_registry import (  # type: ignore[import]
                get_node_fabric_registry,
                NodeArchitecturalClass,
            )
            from core.callable_node_baseline import (  # type: ignore[import]
                is_callable_by_openclawd,
            )

            fabric = get_node_fabric_registry()
            registered_node_ids: set = set()

            for node_info in fabric.list_nodes():
                nid = node_info.node_id
                registered_node_ids.add(nid)
                arch = node_info.architectural_class

                if is_callable_by_openclawd(arch):
                    callable_nodes.append(nid)
                elif arch == NodeArchitecturalClass.SERVICE_NODE:
                    service_nodes.append(nid)
                elif arch == NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE:
                    legacy_nodes.append(nid)
                else:
                    # EXPERIMENTAL_NODE, ARCHIVED_NODE, or unknown
                    non_callable_nodes.append(nid)

            # Nodes that the startup config expects but haven't registered yet.
            unregistered_startup_nodes = sorted(
                startup_node_names - registered_node_ids
            )
            classification_available = True

        except Exception as exc:
            logger.debug(
                "get_callable_node_classification: "
                "callable baseline unavailable (%s); "
                "returning startup config names as unregistered.",
                exc,
            )
            unregistered_startup_nodes = sorted(startup_node_names)

        return {
            "callable_nodes": sorted(callable_nodes),
            "service_nodes": sorted(service_nodes),
            "legacy_nodes": sorted(legacy_nodes),
            "non_callable_nodes": sorted(non_callable_nodes),
            "unregistered_startup_nodes": unregistered_startup_nodes,
            "classification_available": classification_available,
            "summary": {
                "callable_count": len(callable_nodes),
                "service_count": len(service_nodes),
                "legacy_count": len(legacy_nodes),
                "non_callable_count": len(non_callable_nodes),
                "unregistered_startup_count": len(unregistered_startup_nodes),
            },
        }

    # ── Node-list accessors ────────────────────────────────────────────────────

    def get_core_nodes(self) -> List[str]:
        """Return core-group nodes eligible for startup.

        Returns nodes marked ``"group": "core"`` in config, excluding any with
        ``startup_policy: "skip"``.  Falls back to the first 10 nodes from
        ``get_active_nodes()`` (by priority then name) when no core-group
        entries are found, ensuring the system can always bootstrap.
        """
        import re as _re
        core_nodes = [
            name for name, cfg in self.node_configs.items()
            if isinstance(cfg, dict)
            and cfg.get("group") == "core"
            and not self.should_skip(name)
            and (self.nodes_dir / name / "main.py").exists()
        ]
        if core_nodes:
            return sorted(
                core_nodes,
                key=lambda x: self.node_configs.get(x, {}).get("priority", 99),
            )

        all_active = self.get_active_nodes()
        if not all_active:
            return []

        fundamental = all_active[:10]
        logger.info(
            "节点配置中未找到 'group': 'core' 标记，"
            "自动回退为前 10 个活跃节点: %s",
            fundamental,
        )
        return fundamental

    def get_all_nodes(self) -> List[str]:
        """Return all nodes that have a ``main.py`` on disk.

        This is a filesystem scan — it does NOT filter by startup policy.
        Use :meth:`get_active_nodes` when you need only startup-eligible nodes.
        """
        if not self.nodes_dir.exists():
            return []
        return sorted(
            d.name for d in self.nodes_dir.iterdir()
            if d.is_dir() and (d / "main.py").exists()
        )

    async def start_node(self, node_name: str) -> bool:
        """启动单个节点，传递关键环境变量并轮询健康检查。"""
        import aiohttp
        node_dir = self.nodes_dir / node_name
        main_py = node_dir / "main.py"

        if not main_py.exists():
            logger.warning("节点 %s 缺少 main.py，跳过启动", node_name)
            return False

        node_cfg = self.node_configs.get(node_name, {})
        port: Optional[int] = node_cfg.get("port") if isinstance(node_cfg, dict) else None
        if port is None:
            try:
                from core.port_config import get_node_port
                port = get_node_port(node_name)
            except Exception:
                port = None

        state_machine_url = os.environ.get(
            "STATE_MACHINE_URL",
            (
                f"http://127.0.0.1:{self.node_configs.get('Node_00_StateMachine', {}).get('port', 8000)}"
                if isinstance(self.node_configs.get("Node_00_StateMachine"), dict)
                else "http://127.0.0.1:8000"
            ),
        )
        extra_env: Dict[str, str] = {
            "NODE_ID": node_name,
            "NODE_NAME": node_name,
            "STATE_MACHINE_URL": state_machine_url,
            "LOG_LEVEL": os.environ.get("LOG_LEVEL", "INFO"),
            "USE_MEMORY_STORE": os.environ.get("USE_MEMORY_STORE", "true"),
            "USE_MOCK_DRIVERS": os.environ.get("USE_MOCK_DRIVERS", "false"),
        }
        if port is not None:
            extra_env["PORT"] = str(port)

        self.service_manager.register_service(node_name, ServiceType.NODE, port)

        ok = await self.service_manager.start_service(
            node_name,
            [sys.executable, str(main_py)],
            cwd=node_dir,
            extra_env=extra_env,
        )
        if not ok:
            logger.error("节点 %s 进程启动失败", node_name)
            self._register_node_in_canonical_registry(node_name, port, "offline")
            return False

        if port is not None:
            health_url = f"http://127.0.0.1:{port}/health"
            for attempt in range(1, 11):
                await asyncio.sleep(1)
                try:
                    async with aiohttp.ClientSession(
                        timeout=aiohttp.ClientTimeout(total=2)
                    ) as session:
                        async with session.get(health_url) as resp:
                            if resp.status < 400:
                                try:
                                    body = await resp.json()
                                    node_status_val = body.get("status", "healthy")
                                except Exception:
                                    node_status_val = "healthy"

                                if node_status_val in ("degraded", "skipped"):
                                    logger.warning(
                                        "节点 %s 以 %s 模式启动 (尝试 %d/10, 端口 %d) — "
                                        "部分功能可能受限，但不影响系统启动",
                                        node_name, node_status_val, attempt, port,
                                    )
                                else:
                                    logger.info(
                                        "节点 %s 健康检查通过 (尝试 %d/10, 端口 %d)",
                                        node_name, attempt, port,
                                    )
                                await self._register_node_with_runtime_registry(node_name, port)
                                return True
                except Exception:
                    pass
                logger.debug("节点 %s 健康检查等待 (尝试 %d/10)", node_name, attempt)

            svc = self.service_manager.services.get(node_name)
            if svc and svc.process and svc.process.stderr:
                try:
                    import select as _select
                    if _select.select([svc.process.stderr], [], [], 0.5)[0]:
                        stderr_out = svc.process.stderr.read1(4096)  # type: ignore[attr-defined]
                        if stderr_out:
                            logger.error(
                                "节点 %s 健康检查失败，stderr:\n%s",
                                node_name,
                                stderr_out.decode(errors="replace"),
                            )
                except Exception:
                    pass
            logger.warning("节点 %s 健康检查超时（10 次），视为启动失败", node_name)
            self._register_node_in_canonical_registry(node_name, port, "offline")
            return False

        logger.info("节点 %s 已启动（无端口，跳过健康检查）", node_name)
        await self._register_node_with_runtime_registry(node_name, port)
        return True

    async def _register_node_with_runtime_registry(
        self, node_name: str, port: Optional[int]
    ) -> None:
        """向运行时节点注册表注册已启动的节点（失败时静默忽略）。

        先通过 _register_node_in_canonical_registry() 直接写入
        NodeFabricRegistry（进程内，规范路径）。
        再通过 HTTP 向 /api/v1/nodes/register 发送次级通知（兼容 dashboard）。
        注册端点来自 core/api_routes.py（权威 API 层）。
        dashboard/backend 的 /api/v1/nodes/register 已降级为遗留路由，
        由 core.api_routes 的同路径路由覆盖。
        """
        # Primary: write directly into the in-process canonical registry.
        self._register_node_in_canonical_registry(node_name, port, "healthy")

        # Discovery: announce to NodeDiscoveryService so it reflects runtime state.
        self._announce_node_to_discovery(node_name, port)

        # Secondary: HTTP notification for dashboard/legacy consumers.
        try:
            import aiohttp
            api_host = os.environ.get("GALAXY_API_HOST", "127.0.0.1")
            api_port = self.config.web_ui_port
            url = f"http://{api_host}:{api_port}/api/v1/nodes/register"
            payload = {
                "node_id": node_name,
                "name": node_name,
                "port": port,
                "status": "running",
            }
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=2)
            ) as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status < 400:
                        logger.debug("节点 %s 已注册到运行时注册表", node_name)
        except Exception as _exc:
            logger.debug("注册节点 %s 到运行时注册表失败（可忽略）: %s", node_name, _exc)

    def _register_node_in_canonical_registry(
        self,
        node_name: str,
        port: Optional[int],
        status_str: str,
    ) -> None:
        """直接写入 NodeFabricRegistry（进程内，规范路径，失败时静默忽略）。

        This is the **primary canonical registration path** for launcher-managed
        nodes.  It runs in-process so it always succeeds regardless of whether
        the HTTP API is available.

        Args:
            node_name:  Canonical node name (key in ``node_dependencies.json``).
            port:       Listening port, or ``None`` when unknown.
            status_str: Target status string — ``"healthy"``, ``"offline"``, or
                        ``"starting"``.  Mapped to :class:`NodeStatus` internally.
        """
        try:
            from core.nodes.node_fabric_registry import (  # type: ignore[import]
                get_node_fabric_registry,
                NodeInfo,
                NodeRole,
                NodeStatus,
                NodeArchitecturalClass,
            )

            _status_map = {
                "healthy": NodeStatus.HEALTHY,
                "offline": NodeStatus.OFFLINE,
                "starting": NodeStatus.STARTING,
                "unhealthy": NodeStatus.UNHEALTHY,
                "degraded": NodeStatus.DEGRADED,
            }
            node_status = _status_map.get(status_str, NodeStatus.HEALTHY)

            fabric = get_node_fabric_registry()

            # If already registered, update status + heartbeat only.
            existing = fabric.get(node_name)
            if existing is not None:
                fabric.update_status(node_name, node_status)
                if node_status not in (NodeStatus.OFFLINE, NodeStatus.UNHEALTHY):
                    fabric.heartbeat(node_name)
                logger.debug(
                    "节点 %s 已在 NodeFabricRegistry 中，更新状态为 %s",
                    node_name, node_status.value,
                )
                return

            # Build NodeInfo from launcher configuration.
            node_cfg = self.node_configs.get(node_name, {})
            deps = (
                node_cfg.get("dependencies", [])
                if isinstance(node_cfg, dict) else []
            )
            description = (
                node_cfg.get("description", "")
                if isinstance(node_cfg, dict) else ""
            )
            group = (
                node_cfg.get("group", "")
                if isinstance(node_cfg, dict) else ""
            )

            _group_role_map = {
                "core": NodeRole.WORKER,
                "development": NodeRole.TOOL,
                "extended": NodeRole.WORKER,
                "academic": NodeRole.WORKER,
            }
            role = _group_role_map.get(group, NodeRole.WORKER)

            node_info = NodeInfo(
                node_id=node_name,
                role=role,
                architectural_class=NodeArchitecturalClass.CAPABILITY_NODE,
                host="localhost",
                port=port or 0,
                status=node_status,
                dependencies=list(deps),
                metadata={
                    "name": node_name,
                    "description": description,
                    "group": group,
                    "launcher_managed": True,
                },
            )
            fabric.register(node_info)
            logger.debug(
                "节点 %s 已直接注册到 NodeFabricRegistry (status=%s)",
                node_name, node_status.value,
            )
        except Exception as exc:
            logger.debug(
                "直接注册节点 %s 到 NodeFabricRegistry 失败（可忽略）: %s",
                node_name, exc,
            )

    def _announce_node_to_discovery(
        self,
        node_name: str,
        port: Optional[int],
    ) -> None:
        """Announce a successfully started node to NodeDiscoveryService.

        PR-7: Wires each healthy node into the discovery plane so that callers
        can locate nodes by capability or role without depending on UDP broadcast.

        Args:
            node_name: Canonical node name.
            port:      Node HTTP port, or ``None`` when unknown.
        """
        try:
            from core.node_discovery import get_node_discovery
            from core.node_discovery_runtime import announce_node_to_discovery

            discovery = get_node_discovery()
            node_cfg = self.node_configs.get(node_name, {})
            description = (
                node_cfg.get("description", "")
                if isinstance(node_cfg, dict) else ""
            )
            capabilities = [node_name]
            if description:
                capabilities.append(description)

            announce_node_to_discovery(
                discovery=discovery,
                node_id=node_name,
                host="localhost",
                port=port or 0,
                capabilities=capabilities,
                role_str="worker",
            )
        except Exception as exc:
            logger.debug(
                "NodeSystemLauncher: announce %s to discovery failed (non-fatal): %s",
                node_name, exc,
            )

    async def initialize_discovery_after_startup(self) -> int:
        """Seed all healthy fabric-registry nodes into NodeDiscoveryService.

        PR-7: Called after the initial node batch has been started so that
        the discovery plane immediately reflects the real set of running nodes.
        This makes :class:`~core.node_discovery.NodeDiscoveryService` a
        meaningful participant in the startup path rather than an isolated
        capability.

        Returns:
            Number of nodes seeded (0 when either subsystem is unavailable).
        """
        try:
            from core.node_discovery import get_node_discovery
            from core.nodes.node_fabric_registry import get_node_fabric_registry
            from core.node_discovery_runtime import initialize_discovery_from_startup

            discovery = get_node_discovery()
            fabric = get_node_fabric_registry()
            seeded = initialize_discovery_from_startup(discovery, fabric)
            logger.info(
                "NodeSystemLauncher: discovery startup seed complete — %d node(s) seeded",
                seeded,
            )
            return seeded
        except Exception as exc:
            logger.debug(
                "NodeSystemLauncher: initialize_discovery_after_startup failed (non-fatal): %s",
                exc,
            )
            return 0

    def stop_node(self, node_name: str) -> bool:
        """停止单个节点并将其在 NodeFabricRegistry 中标记为 OFFLINE。

        Args:
            node_name: Canonical node name.

        Returns:
            ``True`` if the service was found and stopped; ``False`` otherwise.
        """
        # Mark OFFLINE in canonical registry first.
        self._register_node_in_canonical_registry(node_name, None, "offline")
        # Stop the underlying process via ServiceManager.
        stopped = self.service_manager.stop_service(node_name)
        if stopped:
            logger.info("节点 %s 已停止", node_name)
        else:
            logger.debug("stop_node: 未找到服务 %s（可能已停止）", node_name)
        return stopped

    async def start_nodes(
        self, nodes: List[str], parallel: bool = True
    ) -> Dict[str, bool]:
        """启动多个节点"""
        results: Dict[str, bool] = {}

        if parallel:
            tasks = [self.start_node(node) for node in nodes]
            results_list = await asyncio.gather(*tasks, return_exceptions=True)
            for node, result in zip(nodes, results_list):
                results[node] = result is True
        else:
            for node in nodes:
                results[node] = await self.start_node(node)
                await asyncio.sleep(0.05)

        return results

    async def start_all(self, minimal: bool = False) -> Dict[str, bool]:
        """Start the active node set.

        Uses :meth:`get_core_nodes` as the default startup surface.  When that
        list is empty (legacy config without group annotations) the launcher
        falls back to :meth:`get_active_nodes` — the full set of startup-
        eligible nodes — and emits a warning so operators know why.

        Nodes with ``startup_policy: "skip"`` are **never** started regardless
        of the ``minimal`` flag; they are excluded at the source by
        :meth:`get_core_nodes` and :meth:`get_active_nodes`.

        Args:
            minimal: When True, limit the startup batch to the first 10 nodes
                     from the resolved list (by priority then name).
        """
        nodes = self.get_core_nodes()

        if not nodes:
            fallback = self.get_active_nodes()
            if fallback:
                logger.warning(
                    "核心节点列表为空（node_dependencies.json 中无 'group': 'core' 标记），"
                    "自动回退为全量活跃节点列表（共 %d 个）。"
                    "注意：startup_policy='skip' 的节点已被排除。",
                    len(fallback),
                )
                nodes = fallback
            else:
                logger.error(
                    "核心节点与活跃节点列表均为空，节点系统将不会启动。"
                    "请确认 nodes/ 目录下存在包含 main.py 的子目录，"
                    "且对应节点的 startup_policy 不为 'skip'。"
                )
                return {}

        if minimal:
            nodes = nodes[:10]
            logger.info("最小启动模式：将启动前 %d 个节点", len(nodes))

        logger.info("即将启动 %d 个节点: %s", len(nodes), nodes)
        print_status(f"启动 {len(nodes)} 个节点...", "step")
        results = await self.start_nodes(nodes, parallel=True)

        success_nodes = [n for n, ok in results.items() if ok]
        failed_nodes = [n for n, ok in results.items() if not ok]
        logger.info(
            "节点启动完成: %d 成功 / %d 失败%s",
            len(success_nodes),
            len(failed_nodes),
            f"  失败节点: {failed_nodes}" if failed_nodes else "",
        )

        # PR-12: Bulk-seed all healthy fabric-registry nodes into
        # NodeDiscoveryService now that the startup batch has completed.
        # This closes the gap where initialize_discovery_after_startup() was
        # defined but never invoked by the real startup orchestration.
        await self.initialize_discovery_after_startup()

        return results
