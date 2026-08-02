"""
core/legacy_adapters/__init__.py
==================================
PR-1 (Block-1) — Legacy Adapter Layer

This package provides adapters for key legacy entry points so that
old APIs are preserved while logic is delegated to unified core modules.

Available adapters:
    - device_agent_manager_adapter: wraps core.device_agent_manager → core.unified.device_manager

See docs/architecture/module_ownership_map.md for the full mapping.
"""

from .device_agent_manager_adapter import LegacyDeviceAgentManagerAdapter

__all__ = [
    "LegacyDeviceAgentManagerAdapter",
]
