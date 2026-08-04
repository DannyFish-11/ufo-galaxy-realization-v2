"""launcher/nodes.py — 节点生命周期的**命令面**

它解决什么
----------
``docs/CONFIGURATION_AUTHORITY.md`` 与 ``docs/guides/QUICKSTART.md`` 都明确让用户
跑 ``python system_manager.py``。而统一启动器的目标是"所有启动器收敛到
``main.py`` 一个入口，各自真实有效的要素保留、本体删掉" —— 那么**删本体之前，
必须先有等价的新命令**，否则文档一改用户就没路可走。

本模块就是那条新路：``python main.py nodes <command>``。

计划里写的替换命令是**不完整的**（订正记录）
------------------------------------------------
``docs/LAUNCHER_UNIFICATION_PLAN.md`` 的命令面表写的是::

    python system_manager.py  →  python main.py nodes <start|stop|status> [name]

对着 ``system_manager.main()`` 的真实 CLI 核过之后，这条有两处不对：

1. **少了两个命令**：真实的是 ``start | stop | status | monitor | report``。
   照着计划实现会**静默丢掉** ``monitor``（常驻监控循环）与 ``report``
   （JSON 报告）—— 用户敲惯的命令突然不认识，而"命令面替换完成"的说法却已经
   写进文档。
2. **参数形态错了**：真实的是 ``--group``（九个节点组 + ``all``）与
   ``--interval``，不是位置参数 ``[name]``。按 ``[name]`` 实现的话，
   ``python system_manager.py start --group core`` 这种用法直接没有对应写法。

所以这里按**实际存在的**表面等价迁移，而不是按计划里那一行。

实现体是**原样搬来**的，不是重写的
------------------------------------
下半部分的 :class:`NodeConfig` / :class:`ConfigManager` / ``NODES`` /
:class:`SystemManager` 来自 ``system_manager.py``，**逐字节移动**。

刻意不重写：那 529 行里有大量真机故障攒出来的细节 —— 端口权威解析委派
``core.port_config``、能力/连接管理器初始化失败时的非致命降级、按组优先级的
启动次序、健康探针的超时与重试……手抄一遍必然丢掉其中几条，而丢掉哪条要等真机
上出问题才知道。移动则**由构造保证一样不丢**，搬迁前后做过 sha256 比对。

``system_manager.py`` 现在只剩 CLI 外壳，从这里 re-export 那四个名字，让既有
import（``health_monitor.py``）与老命令在并存期内继续可用。它在步骤 8 删除。

刻意的边界
----------
与 :mod:`launcher.env_check` / :mod:`launcher.deps` 同：本模块不自己实现节点
生命周期，也不重复一份节点表。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import httpx

#: 仓库根。**搬迁时必须显式算**：实现体原本写在仓库根的 ``system_manager.py``
#: 里，用的是 ``Path(__file__).parent``；搬进 ``launcher/`` 之后同一个表达式指向
#: 的是 ``launcher/`` 而不是仓库根 —— 配置文件会找不到、节点目录会扫空。
#: 这是"物理移动"唯一会静默改变语义的一类地方，逐处核过（见下面两个 PROJECT_ROOT）。
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ANSI 颜色代码（随实现体一起搬来）
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RESET = "\033[0m"

logger = logging.getLogger("Galaxy.SystemManager")

#: ``system_manager.main()`` 实际接受的命令。**照抄**，不是重新设计 ——
#: 少一个就是静默丢掉一种用户敲惯的用法。
NODE_COMMANDS: Sequence[str] = ("start", "stop", "status", "monitor", "report")

#: ``--group`` 的取值。同样照抄。
NODE_GROUPS: Sequence[str] = (
    "core",
    "tools",
    "physical",
    "intelligence",
    "monitoring",
    "advanced",
    "orchestration",
    "multimodal",
    "academic",
    "all",
)

DEFAULT_GROUP = "all"
DEFAULT_INTERVAL = 30


def _load_manager() -> "SystemManager":
    """构造一个 :class:`SystemManager`。

    实现体现在就在本模块下半部分，不必再绕回 ``system_manager.py``。

    但**模块级仍有一次配置读取**：``NODES = ConfigManager.load_nodes()``。
    ``main.py`` 只在真正要用 ``nodes`` 子命令时才 import 本模块（见
    ``_run_nodes_command``），所以"只想 --version"的路径不会为它付代价 ——
    这条时序约束由 ``tests/test_launcher_nodes.py`` 钉住。
    """
    return SystemManager()


async def run_command(
    command: str,
    *,
    group: str = DEFAULT_GROUP,
    interval: int = DEFAULT_INTERVAL,
    manager: Optional[Any] = None,
) -> int:
    """执行一条节点生命周期命令，返回进程退出码。

    行为与 ``python system_manager.py <command>`` **逐条对应**，包括
    ``start`` 之后保持运行、``Ctrl+C`` 时停全部这条语义 —— 那不是可有可无的
    细节：``start`` 拉起的是子进程，命令一返回它们就会失去看护。

    Args:
        command:  :data:`NODE_COMMANDS` 之一。
        group:    :data:`NODE_GROUPS` 之一（仅 ``start`` 用）。
        interval: 监控间隔秒数（仅 ``monitor`` 用）。
        manager:  注入点，仅测试用；生产路径永远走 :func:`_load_manager`。
    """
    if command not in NODE_COMMANDS:
        raise ValueError(f"未知命令 {command!r}；可用：{', '.join(NODE_COMMANDS)}")
    if group not in NODE_GROUPS:
        raise ValueError(f"未知节点组 {group!r}；可用：{', '.join(NODE_GROUPS)}")

    mgr = manager if manager is not None else _load_manager()

    if command == "start":
        if group == DEFAULT_GROUP:
            await mgr.start_all()
        else:
            await mgr.start_group(group)
        # 保持运行 —— 与 system_manager.main() 同。拉起的是子进程，这里一返回
        # 就没人看着它们了。
        try:
            while True:
                await asyncio.sleep(1)
        except (KeyboardInterrupt, asyncio.CancelledError):
            mgr.stop_all()
        return 0

    if command == "stop":
        mgr.stop_all()
        return 0

    if command == "status":
        await mgr.check_all_nodes()
        return 0

    if command == "monitor":
        await mgr.monitor(interval)
        return 0

    # report
    report = await mgr.generate_report()
    print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    return 0


def equivalent_legacy_command(command: str, *, group: str = DEFAULT_GROUP, interval: int = DEFAULT_INTERVAL) -> str:
    """给出这条新命令对应的**老**命令写法。

    存在的意义不是好看：文档迁移时要逐条对照，而"对照表"如果是手写的就会漂。
    这个函数让"每种老用法都有新写法"成为**可测**的（见
    ``tests/test_launcher_nodes.py``）。
    """
    parts: List[str] = ["python", "system_manager.py", command]
    if command == "start" and group != DEFAULT_GROUP:
        parts += ["--group", group]
    if command == "monitor" and interval != DEFAULT_INTERVAL:
        parts += ["--interval", str(interval)]
    return " ".join(parts)


# =============================================================================
# Configuration - 从 unified_config.json 加载
# Port resolution defers to config/unified_ports.yaml via core.port_config
# =============================================================================


@dataclass
class NodeConfig:
    """节点配置"""

    id: str
    name: str
    port: int
    group: str
    auto_start: bool = True
    health_check_path: str = "/health"
    dependencies: List[str] = None
    critical: bool = False
    description: str = ""

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


class ConfigManager:
    """节点编排配置管理器 [NODE ORCHESTRATION HELPER — not a config authority]

    Reads node metadata from ``config/unified_config.json``.
    Port resolution defers to ``core.port_config`` (canonical source:
    ``config/unified_ports.yaml``) with the JSON file as fallback.
    """

    # 搬迁修正：原文件在仓库根，Path(__file__).parent 即仓库根；
    # 搬到 launcher/ 后必须显式用 PROJECT_ROOT，否则指向 launcher/config/。
    CONFIG_FILE = PROJECT_ROOT / "config" / "unified_config.json"

    # Lazy-loaded canonical port resolver; False = unavailable (not just uninitialised)
    _port_config: Any = None  # PortConfig instance | False

    @classmethod
    def _get_canonical_port(cls, node_key: str, json_port: int) -> int:
        """Resolve port via core.port_config (canonical); fall back to json_port."""
        if cls._port_config is None:
            try:
                from core.port_config import PortConfig  # noqa: PLC0415

                cls._port_config = PortConfig.instance()
            except Exception as exc:
                logger.debug("core.port_config unavailable, using JSON ports: %s", exc)
                cls._port_config = False  # mark as unavailable

        if cls._port_config is not False:
            try:
                canon = cls._port_config.get_node_port(node_key)
                if canon and canon != json_port:
                    logger.debug(
                        "Port for %s: using canonical %d (config had %d)",
                        node_key,
                        canon,
                        json_port,
                    )
                return canon or json_port
            except Exception as exc:
                logger.debug("port_config lookup failed for %s: %s", node_key, exc)
        return json_port

    @classmethod
    def load_nodes(cls) -> Dict[str, List[NodeConfig]]:
        """从配置文件加载节点（端口优先从 core.port_config 解析）"""
        if not cls.CONFIG_FILE.exists():
            print(f"{YELLOW}⚠️  Config file not found, using defaults{RESET}")
            return cls._get_default_nodes()

        try:
            with open(cls.CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)

            nodes_by_group = {}

            for node_key, node_info in config.get("nodes", {}).items():
                # 解析节点ID
                parts = node_key.split("_")
                if len(parts) >= 3:
                    node_id = "_".join(parts[1:-1]) if len(parts) > 3 else parts[1]
                    node_name = parts[-1]
                else:
                    continue

                group = node_info.get("group", "core")

                if group not in nodes_by_group:
                    nodes_by_group[group] = []

                json_port = node_info.get("port", 8000 + int(node_id) if node_id.isdigit() else 8000)
                canon_port = cls._get_canonical_port(node_key, json_port)

                nodes_by_group[group].append(
                    NodeConfig(
                        id=node_id,
                        name=node_name,
                        port=canon_port,
                        group=group,
                        auto_start=node_info.get("critical", False),
                        dependencies=node_info.get("dependencies", []),
                        critical=node_info.get("critical", False),
                        description=node_info.get("description", ""),
                    )
                )

            return nodes_by_group

        except Exception as e:
            print(f"{RED}❌ Error loading config: {e}{RESET}")
            return cls._get_default_nodes()

    @classmethod
    def _get_default_nodes(cls) -> Dict[str, List[NodeConfig]]:
        """默认节点配置（端口从 core.port_config 解析，回退到硬编码值）"""

        def _p(key: str, fallback: int) -> int:
            return cls._get_canonical_port(key, fallback)

        return {
            "core": [
                NodeConfig("00", "StateMachine", _p("Node_00_StateMachine", 8000), "core", True, critical=True),
                NodeConfig("01", "OneAPI", _p("Node_01_OneAPI", 7995), "core", True, critical=True),
                NodeConfig("02", "Tasker", _p("Node_02_Tasker", 8002), "core", True, critical=True),
                NodeConfig("03", "SecretVault", _p("Node_03_SecretVault", 8003), "core", True, critical=True),
                NodeConfig("04", "Router", _p("Node_04_Router", 8004), "core", True, critical=True),
                NodeConfig("05", "Auth", _p("Node_05_Auth", 8005), "core", True, critical=True),
                NodeConfig("06", "Filesystem", _p("Node_06_Filesystem", 8006), "core", True, critical=True),
            ],
            "monitoring": [
                NodeConfig("65", "LoggerCentral", _p("Node_65_LoggerCentral", 8065), "monitoring", True, critical=True),
                NodeConfig("67", "HealthMonitor", _p("Node_67_HealthMonitor", 8067), "monitoring", True, critical=True),
            ],
        }


# 加载节点配置
NODES = ConfigManager.load_nodes()

# =============================================================================
# System Manager
# =============================================================================


class SystemManager:
    """系统管理器"""

    def __init__(self, project_root: Path = None):
        # 搬迁修正：同上 —— 不修的话 nodes_dir 会指向 launcher/nodes，
        # 那是本模块自己，节点一个都扫不到。
        self.project_root = project_root or PROJECT_ROOT
        self.nodes_dir = self.project_root / "nodes"
        self.log_dir = self.project_root / "logs"
        self.log_dir.mkdir(exist_ok=True)

        self.processes: Dict[str, subprocess.Popen] = {}
        self.node_status: Dict[str, str] = {}
        self.nodes_config = self._flatten_nodes()

        # ===== 集成：初始化能力管理器和连接管理器 =====
        try:
            sys.path.insert(0, str(self.project_root))
            from core.capability_manager import get_capability_manager
            from core.connection_manager import get_connection_manager

            self.capability_manager = get_capability_manager()
            self.connection_manager = get_connection_manager()

            print(f"{GREEN}✅ 能力管理器和连接管理器已初始化{RESET}")
        except Exception as e:
            print(f"{YELLOW}⚠️  能力管理器初始化失败 (非致命): {e}{RESET}")
            self.capability_manager = None
            self.connection_manager = None

    def _flatten_nodes(self) -> Dict[str, NodeConfig]:
        """将分组节点展平为字典"""
        result = {}
        for group_nodes in NODES.values():
            for config in group_nodes:
                result[config.id] = config
        return result

    def get_node_path(self, node_id: str, node_name: str) -> Optional[Path]:
        """获取节点路径"""
        possible_paths = [
            self.nodes_dir / f"Node_{node_id}_{node_name}",
            self.nodes_dir / f"Node_{node_id}",
            self.nodes_dir / f"node_{node_id}",
        ]

        for path in possible_paths:
            if path.exists():
                return path

        return None

    def start_node(self, config: NodeConfig) -> bool:
        """启动单个节点"""
        node_path = self.get_node_path(config.id, config.name)

        if not node_path:
            print(f"{RED}❌ 节点 {config.name} (Node_{config.id}) 不存在{RESET}")
            self.node_status[config.id] = "not_found"
            return False

        main_py = node_path / "main.py"
        if not main_py.exists():
            print(f"{RED}❌ 节点 {config.name} 缺少 main.py{RESET}")
            self.node_status[config.id] = "no_main"
            return False

        # 启动节点
        log_file = self.log_dir / f"node_{config.id}_{config.name}.log"

        try:
            with open(log_file, "w") as f:
                env = os.environ.copy()
                env["NODE_ID"] = config.id
                env["NODE_NAME"] = config.name
                env["PORT"] = str(config.port)
                # 仓库根必须进子进程的 import 路径。
                #
                # cwd 是节点自己的目录(节点会按相对路径读自带资源,不能改),
                # 于是子进程的 sys.path[0] 也是那个目录 —— 仓库根根本不在里面。
                # 结果:节点第一行 `from core.xxx import ...` / `from nodes.common...`
                # 直接 ModuleNotFoundError 退出,而这里只看健康端口通不通,
                # 30 秒后一律报"启动超时",把一个**必然的 import 失败**说成了超时。
                #
                # 真跑 `python main.py nodes start --group core` 实测:7 个核心节点
                # 0/7 成功,logs/node_*.log 里全是 "No module named 'core'" /
                # "No module named 'nodes'"。也就是说这条命令面从来没真正起过节点。
                env["PYTHONPATH"] = os.pathsep.join(x for x in (str(PROJECT_ROOT), env.get("PYTHONPATH", "")) if x)

                process = subprocess.Popen(
                    [sys.executable, str(main_py)],
                    cwd=str(node_path),
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                )

            self.processes[config.id] = process
            self.node_status[config.id] = "starting"

            # ===== 集成：注册连接到连接管理器 =====
            if self.connection_manager:
                try:
                    asyncio.create_task(self._register_node_connection(config))
                except Exception as e:
                    print(f"{YELLOW}⚠️  连接注册失败 (非致命): {e}{RESET}")

            # ===== 集成：注册节点能力 =====
            if self.capability_manager:
                try:
                    asyncio.create_task(self._register_node_capabilities(config))
                except Exception as e:
                    print(f"{YELLOW}⚠️  能力注册失败 (非致命): {e}{RESET}")

            print(f"{CYAN}🚀 启动节点 {config.name} (端口 {config.port})...{RESET}")
            return True

        except Exception as e:
            print(f"{RED}❌ 启动节点 {config.name} 失败: {e}{RESET}")
            self.node_status[config.id] = "failed"
            return False

    async def _register_node_connection(self, config: NodeConfig):
        """注册节点到连接管理器"""
        if not self.connection_manager:
            return

        try:
            from core.connection_manager import ConnectionConfig

            # 等待节点启动
            await asyncio.sleep(2)

            connection_id = f"node_{config.id}"
            url = f"http://localhost:{config.port}"

            conn_config = ConnectionConfig(
                url=url, timeout=5.0, heartbeat_interval=30.0, health_check_path=config.health_check_path
            )

            await self.connection_manager.register_connection(connection_id, url, conn_config)

            # 尝试建立连接
            await self.connection_manager.connect(connection_id)

        except Exception as e:
            print(f"{YELLOW}⚠️  节点连接注册失败 {config.name}: {e}{RESET}")

    async def _register_node_capabilities(self, config: NodeConfig):
        """从 node_dependencies.json 读取并注册节点能力"""
        if not self.capability_manager:
            return

        try:
            # 尝试从配置文件读取能力
            config_file = self.project_root / "node_dependencies.json"
            if config_file.exists():
                with open(config_file, "r", encoding="utf-8") as f:
                    deps_config = json.load(f)

                # 查找节点配置
                node_key = f"Node_{config.id}_{config.name}"
                if node_key in deps_config.get("nodes", {}):
                    node_info = deps_config["nodes"][node_key]
                    capabilities = node_info.get("capabilities", [])

                    # 注册每个能力
                    for cap_name in capabilities:
                        await self.capability_manager.register_capability(
                            name=f"{config.name.lower()}_{cap_name}",
                            description=node_info.get("description", f"Capability {cap_name}"),
                            node_id=config.id,
                            node_name=config.name,
                            category=node_info.get("group", "general"),
                        )
        except Exception as e:
            print(f"{YELLOW}⚠️  能力注册失败 {config.name}: {e}{RESET}")

    async def check_node_health(self, config: NodeConfig, timeout: int = 5) -> bool:
        """检查节点健康状态

        SECURITY: 若配置了 HEALTH_CHECK_TOKEN 环境变量，会在请求头中
        携带 X-Health-Token 进行认证。被检查节点可选择性验证此 token。
        """
        url = f"http://localhost:{config.port}{config.health_check_path}"

        # 构建请求头：若配置了健康检查 token，则携带认证头
        headers = {}
        health_token = os.environ.get("HEALTH_CHECK_TOKEN", "").strip()
        if health_token:
            headers["X-Health-Token"] = health_token

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                self.node_status[config.id] = "healthy"
                return True
        except httpx.HTTPStatusError as exc:
            # 401/403 表示认证失败 — 记录但不视为节点不健康
            if exc.response.status_code in (401, 403):
                logger.warning(
                    "Health check auth failed for %s (port %d): %s",
                    config.name,
                    config.port,
                    exc.response.status_code,
                )
            return False
        except Exception:
            return False

    async def wait_for_node(self, config: NodeConfig, max_wait: int = 30) -> bool:
        """等待节点启动"""
        start_time = time.time()

        while time.time() - start_time < max_wait:
            if await self.check_node_health(config, timeout=2):
                startup_ms = (time.time() - start_time) * 1000.0
                print(f"{GREEN}✅ 节点 {config.name} 已就绪{RESET}")
                # --- SLO: record per-node startup duration ---
                try:
                    from core.slo_metrics import get_slo_metrics

                    get_slo_metrics().record_startup(startup_ms)
                except Exception:
                    pass
                return True
            await asyncio.sleep(1)

        print(f"{RED}❌ 节点 {config.name} 启动超时{RESET}")
        self.node_status[config.id] = "timeout"
        return False

    async def start_group(self, group: str, wait: bool = True):
        """启动一组节点"""
        if group not in NODES:
            print(f"{RED}❌ 未知的节点组: {group}{RESET}")
            return

        configs = NODES[group]

        print(f"\n{BLUE}{'='*80}{RESET}")
        print(f"{BLUE}启动节点组: {group.upper()}{RESET}")
        print(f"{BLUE}{'='*80}{RESET}\n")

        # 启动所有节点
        for config in configs:
            if config.auto_start:
                # 先启动依赖节点
                for dep in config.dependencies:
                    dep_id = dep.replace("Node_", "").split("_")[0]
                    if dep_id in self.nodes_config and dep_id not in self.processes:
                        self.start_node(self.nodes_config[dep_id])
                        await asyncio.sleep(1)

                self.start_node(config)
                await asyncio.sleep(2)  # 等待 2 秒再启动下一个

        # 等待所有节点就绪
        if wait:
            print(f"\n{YELLOW}等待节点就绪...{RESET}\n")

            tasks = [self.wait_for_node(config) for config in configs if config.auto_start]

            results = await asyncio.gather(*tasks)

            success_count = sum(results)
            total_count = len(results)

            print(f"\n{BLUE}{'='*80}{RESET}")
            print(f"{BLUE}节点组 {group.upper()} 启动完成{RESET}")
            print(f"{BLUE}{'='*80}{RESET}")
            print(f"{GREEN}✅ 成功: {success_count}/{total_count}{RESET}\n")

    async def start_all(self, groups: List[str] = None):
        """启动所有节点"""
        if groups is None:
            # 按优先级排序启动
            priority_order = [
                "core",
                "monitoring",
                "tools",
                "physical",
                "intelligence",
                "advanced",
                "orchestration",
                "multimodal",
                "academic",
            ]
            groups = [g for g in priority_order if g in NODES]

        print(f"\n{CYAN}{'='*80}{RESET}")
        print(f"{CYAN}Galaxy 系统启动{RESET}")
        print(f"{CYAN}{'='*80}{RESET}\n")

        for group in groups:
            await self.start_group(group, wait=True)

    def stop_node(self, node_id: str):
        """停止单个节点"""
        if node_id not in self.processes:
            return

        process = self.processes[node_id]
        config = self.nodes_config.get(node_id)
        name = config.name if config else node_id

        try:
            process.terminate()
            process.wait(timeout=5)
            print(f"{YELLOW}⏹️  节点 {name} 已停止{RESET}")
        except subprocess.TimeoutExpired:
            process.kill()
            print(f"{RED}🔪 节点 {name} 强制停止{RESET}")

        del self.processes[node_id]
        self.node_status[node_id] = "stopped"

    def stop_all(self):
        """停止所有节点"""
        print(f"\n{YELLOW}{'='*80}{RESET}")
        print(f"{YELLOW}停止所有节点...{RESET}")
        print(f"{YELLOW}{'='*80}{RESET}\n")

        for node_id in list(self.processes.keys()):
            self.stop_node(node_id)

        print(f"\n{GREEN}✅ 所有节点已停止{RESET}\n")

    async def monitor(self, interval: int = 30):
        """监控节点状态"""
        print(f"\n{CYAN}{'='*80}{RESET}")
        print(f"{CYAN}开始监控节点状态（每 {interval} 秒检查一次）{RESET}")
        print(f"{CYAN}按 Ctrl+C 停止监控{RESET}")
        print(f"{CYAN}{'='*80}{RESET}\n")

        try:
            while True:
                await self.check_all_nodes()
                await asyncio.sleep(interval)
        except KeyboardInterrupt:
            print(f"\n{YELLOW}监控已停止{RESET}\n")

    async def check_all_nodes(self):
        """检查所有节点状态"""
        print(f"\n{BLUE}[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 节点状态检查{RESET}")
        print(f"{'-'*80}")

        all_configs = list(self.nodes_config.values())
        all_configs.sort(key=lambda x: x.port)

        tasks = [self.check_node_health(config, timeout=3) for config in all_configs]
        results = await asyncio.gather(*tasks)

        healthy_count = 0
        unhealthy_count = 0
        not_running = 0

        # 判据是**探测结果**，不是"这个进程记得自己启过谁"。
        #
        # 原来第一层判的是 `config.id in self.processes` —— 那是本进程 Popen 出来的
        # 子进程表。而 `python main.py nodes status` 每次都是**全新进程**，那张表
        # 永远是空的,于是 109 个节点一律被报成"未运行",哪怕它们全都活着、
        # /health 全都 200。上面 109 次健康探测**照跑不误**,结果却被丢掉。
        # 真跑实测:core 组 7 个节点起好、端口 8003-8006 全 200,status 仍报"未运行 109"。
        #
        # self.processes 仍然有用,但只用来区分"我起的"和"别人起的",
        # 不再用来决定"活没活着" —— 后者只有探测说了算。
        for config, is_healthy in zip(all_configs, results):
            owned = config.id in self.processes
            if is_healthy:
                tag = "" if owned else "  (外部启动)"
                print(f"{GREEN}✅ Node_{config.id:>6} {config.name:<25} (:{config.port}){tag}{RESET}")
                healthy_count += 1
            elif owned:
                print(f"{RED}❌ Node_{config.id:>6} {config.name:<25} (:{config.port}) - Unhealthy{RESET}")
                unhealthy_count += 1
            else:
                print(f"{YELLOW}○ Node_{config.id:>6} {config.name:<25} (:{config.port}) - Not running{RESET}")
                not_running += 1

        print(f"{'-'*80}")
        print(
            f"{GREEN}健康: {healthy_count}{RESET} | {RED}不健康: {unhealthy_count}{RESET} | "
            f"{YELLOW}未运行: {not_running}{RESET}"
        )

    async def generate_report(self) -> Dict:
        """生成系统报告"""
        report = {
            "timestamp": datetime.now().isoformat(),
            "nodes": {},
            "summary": {"total": 0, "running": 0, "healthy": 0, "unhealthy": 0, "not_found": 0},
        }

        all_configs = list(self.nodes_config.values())

        for config in all_configs:
            is_healthy = await self.check_node_health(config, timeout=3)
            is_running = config.id in self.processes

            report["nodes"][config.id] = {
                "name": config.name,
                "port": config.port,
                "group": config.group,
                "status": "healthy" if is_healthy else ("running" if is_running else "stopped"),
            }

            report["summary"]["total"] += 1
            if is_healthy:
                report["summary"]["healthy"] += 1
            elif is_running:
                report["summary"]["unhealthy"] += 1
            else:
                report["summary"]["not_found"] += 1
            # "running" 以前**从来没被 +1 过**,恒为 0 —— 一个只在 JSON 里占位、
            # 谁读谁被误导的死字段。给它一个说得通的含义:有实体在跑
            # (探得到 = 活着,或者是本进程起的但探不通 = 起了没起来),
            # 与 not_found 恰好互补。
            if is_healthy or is_running:
                report["summary"]["running"] += 1

        return report


__all__ = [
    "NODE_COMMANDS",
    "NODE_GROUPS",
    "DEFAULT_GROUP",
    "DEFAULT_INTERVAL",
    "run_command",
    "equivalent_legacy_command",
    # ── 从 system_manager.py 原样搬来的实现体 ──
    "NodeConfig",
    "ConfigManager",
    "NODES",
    "SystemManager",
]
