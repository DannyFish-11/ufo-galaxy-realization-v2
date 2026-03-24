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

Legacy sub-modules (kept for backward compatibility)
----------------------------------------------------
config_manager   — DEPRECATED; use core.unified.config_manager
dependency_resolver — topology-sort helper
"""

# Legacy helpers (preserved for existing callers)
from .config_manager import ConfigManager
from .dependency_resolver import DependencyResolver

# Bootstrap / config layer
from .bootstrap import (
    PROJECT_ROOT,
    SystemState,
    ServiceType,
    SystemConfig,
    _write_entrypoint,
    print_status,
    print_section,
)

# Service lifecycle
from .service_manager import ServiceInfo, ServiceManager

# Startup sub-launchers
from .core_services import CoreServiceLauncher
from .node_startup import NodeSystemLauncher

# Post-startup health checks
from .health_checks import run_startup_health_check

# Graceful shutdown
from .shutdown import async_shutdown

__all__ = [
    # Legacy
    "ConfigManager",
    "DependencyResolver",
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
