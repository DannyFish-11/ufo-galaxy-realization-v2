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
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any

from .bootstrap import PROJECT_ROOT, print_status, ServiceType, SystemConfig
from .service_manager import ServiceManager

logger = logging.getLogger("Galaxy")


class NodeSystemLauncher:
    """节点系统启动器"""

    def __init__(self, service_manager: ServiceManager, config: SystemConfig) -> None:
        self.service_manager = service_manager
        self.config = config
        self.nodes_dir = PROJECT_ROOT / "nodes"
        self.node_configs = self._load_node_configs()

    def _load_node_configs(self) -> Dict[str, Any]:
        """加载节点配置

        优先从 node_dependencies.json 的 "nodes" 键读取；
        若文件不存在则回退到 config/node_registry.json。
        两个文件都不存在时记录可观测诊断日志并返回空字典。
        """
        primary = PROJECT_ROOT / "node_dependencies.json"
        fallback = PROJECT_ROOT / "config" / "node_registry.json"

        for cfg_path in (primary, fallback):
            if cfg_path.exists():
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    nodes = data.get("nodes", data) if isinstance(data, dict) else {}
                    if nodes:
                        logger.info("节点配置已加载: %s (%d 个节点)", cfg_path, len(nodes))
                        return nodes
                    logger.warning("节点配置文件为空或格式异常: %s", cfg_path)
                except Exception as exc:
                    logger.warning("读取节点配置失败 %s: %s", cfg_path, exc)

        logger.error(
            "未找到节点配置文件。已检查路径: %s, %s。"
            "请确保 node_dependencies.json 存在于项目根目录，"
            "或在 config/node_registry.json 中提供备用配置。",
            primary,
            fallback,
        )
        return {}

    # ── Startup-policy helpers (PR-7) ─────────────────────────────────────────

    _POLICY_SKIP = "skip"
    _POLICY_OPTIONAL = "optional"
    _POLICY_ACTIVE = "active"

    def get_startup_policy(self, node_name: str) -> str:
        """Return the startup_policy for *node_name* from the loaded config.

        Falls back to ``"active"`` when the node is absent from config or
        the field is not set, preserving backward-compatibility with legacy
        ``node_registry.json`` entries that pre-date the PR-7 policy field.
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
            return False

        logger.info("节点 %s 已启动（无端口，跳过健康检查）", node_name)
        await self._register_node_with_runtime_registry(node_name, port)
        return True

    async def _register_node_with_runtime_registry(
        self, node_name: str, port: Optional[int]
    ) -> None:
        """向运行时节点注册表注册已启动的节点（失败时静默忽略）。

        注册端点来自 core/api_routes.py（权威 API 层）。
        dashboard/backend 的 /api/v1/nodes/register 已降级为遗留路由，
        由 core.api_routes 的同路径路由覆盖。
        """
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
        return results
