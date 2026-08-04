"""
Galaxy Unified Launcher Module

Provides optimized startup with:
- Unified configuration management
- Smart dependency resolution
- Parallel node startup
- Health monitoring
- Auto-recovery

Sub-module responsibilities
---------------------------
bootstrap        — SystemState/ServiceType enums, SystemConfig, _write_entrypoint,
                   print_status/print_section display helpers
service_manager  — ServiceInfo dataclass, ServiceManager lifecycle controller
core_services    — CoreServiceLauncher (Device Agent, Device Status API, UFO)
node_startup     — NodeSystemLauncher (node discovery, health polling, registry)
health_checks    — run_startup_health_check (post-startup probe)
shutdown         — async_shutdown (graceful NATS + subsystem teardown)

dependency_resolver — 拓扑排序助手(纯算法,按 NodeSpec 结构协议收节点表)

配置层去向
----------
``config_manager`` 已按其在 ``core/compat_surface_retirement.py`` 登记的退役
条件物理删除(全仓无生产 importer + 端口消费方已迁至 ``core.port_config``)。
需要配置权威时用 ``core.unified.config_manager``;需要端口时用
``core.port_config``(权威源 ``config/unified_ports.yaml``)。

``dependency_resolver`` **不是**弃用件:它不发 DeprecationWarning,也没有退役
登记 —— 它是统一启动器的节点编排要用的能力。此前它唯一的 importer 是
config_manager,所以看着像"没人用",那是引用计数而非能力判断。

之所以仍不在包导入期加载它:启动路径不该为一个按需能力付 import 代价。
需要时显式 ``from launcher.dependency_resolver import DependencyResolver``。
"""

# Bootstrap / config layer
from .bootstrap import (
    PROJECT_ROOT,
    ServiceType,
    SystemConfig,
    SystemState,
    _write_entrypoint,
    print_section,
    print_status,
)

# Startup sub-launchers
from .core_services import CoreServiceLauncher

# Post-startup health checks
from .health_checks import run_startup_health_check
from .node_startup import NodeSystemLauncher

# Service lifecycle
from .service_manager import ServiceInfo, ServiceManager

# Graceful shutdown
from .shutdown import async_shutdown

__all__ = [
    # Bootstrap
    "PROJECT_ROOT",
    "SystemState",
    "ServiceType",
    "SystemConfig",
    "_write_entrypoint",
    "print_status",
    "print_section",
    # Service management
    "ServiceInfo",
    "ServiceManager",
    # Startup
    "CoreServiceLauncher",
    "NodeSystemLauncher",
    # Health + shutdown
    "run_startup_health_check",
    "async_shutdown",
]
