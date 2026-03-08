"""
Galaxy Daemon Module

24/7 operation support with:
- Automatic restart
- Health monitoring
- Resource management
- Graceful shutdown
"""

from .galaxy_daemon import (
    GalaxyDaemon,
    ProcessManager,
    HealthMetrics,
    ServiceStatus,
    DaemonState,
    start_daemon,
    stop_daemon
)

__all__ = [
    "GalaxyDaemon",
    "ProcessManager",
    "HealthMetrics",
    "ServiceStatus",
    "DaemonState",
    "start_daemon",
    "stop_daemon"
]
