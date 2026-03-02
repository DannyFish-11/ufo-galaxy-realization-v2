"""
UFO Galaxy Unified Launcher Module

Provides optimized startup with:
- Unified configuration management
- Smart dependency resolution
- Parallel node startup
- Health monitoring
- Auto-recovery
"""

from .unified_launcher import UnifiedLauncher, LaunchConfig, NodeStatus
from .config_manager import ConfigManager
from .dependency_resolver import DependencyResolver

__all__ = [
    "UnifiedLauncher",
    "LaunchConfig",
    "NodeStatus",
    "ConfigManager",
    "DependencyResolver"
]
