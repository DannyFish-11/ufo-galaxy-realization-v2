"""
Galaxy Unified Launcher Module

Provides optimized startup with:
- Unified configuration management
- Smart dependency resolution
- Parallel node startup
- Health monitoring
- Auto-recovery
"""

from .config_manager import ConfigManager
from .dependency_resolver import DependencyResolver

__all__ = [
    "ConfigManager",
    "DependencyResolver",
]
