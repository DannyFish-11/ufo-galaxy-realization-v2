"""
core/capability — Capability Subsystem Consolidated Entry Point
===============================================================

Batch PR-6: Capability subsystem consolidation and responsibility separation.

This package provides a single canonical entry point for the capability
subsystem and documents the clear responsibility boundaries between its
components.  It does NOT introduce new logic — it re-exports the canonical
public APIs from their authoritative locations.

Capability subsystem architecture (Batch PR-6)
----------------------------------------------

.. code-block:: text

                          ┌─────────────────────────────────────┐
                          │        Capability Subsystem          │
                          └─────────────────────────────────────┘
                                            │
               ┌────────────────────────────┼────────────────────────────┐
               │                            │                            │
               ▼                            ▼                            ▼
   ┌─────────────────────┐    ┌──────────────────────┐    ┌────────────────────────┐
   │  CapabilityRegistry  │    │   CapabilityBus       │    │  CapabilityResolver    │
   │  (Inventory SSOT)   │    │   (Discovery Bus)     │    │  (Consumer Read Path)  │
   │  core.agent.        │    │   core.capability_bus │    │  core.unified.         │
   │  capability_registry│    │                       │    │  capability_resolver   │
   └─────────────────────┘    └──────────────────────┘    └────────────────────────┘
               │                                                        │
               │  (validates at write)           (validates at read)    │
               ▼                                                        │
   ┌─────────────────────┐                                              │
   │  CapabilityContract  │◄─────────────────────────────────────────── ┘
   │  (Schema Validator) │
   │  core.unified.      │
   │  capability_contract│
   └─────────────────────┘
               │
               ▼
   ┌─────────────────────┐
   │ CapabilityRuntime   │
   │ Registry            │
   │ (Live Health/State) │
   │ core.capability_    │
   │ runtime             │
   └─────────────────────┘

               ╔══════════════════════════════╗
               ║  DEPRECATED COMPAT FACADES   ║
               ║  (Batch PR-6: SECONDARY)     ║
               ╠══════════════════════════════╣
               ║ CapabilityManager            ║
               ║ core.capability_manager      ║
               ╠══════════════════════════════╣
               ║ CapabilityOrchestrator       ║
               ║ core.capability_orchestrator ║
               ╚══════════════════════════════╝

Responsibility separation (Batch PR-6)
---------------------------------------
1. **CapabilityRegistry** (``core.agent.capability_registry``)
   - *Role*: canonical in-process capability **inventory SSOT**.
   - *Writers*: ``mcp_loader``, ``skill_loader``, ``NodeFabricRegistry``,
     device-registration paths.
   - *Consumers*: read via ``CapabilityResolver`` — do NOT access directly.
   - *Authority sentinel*: ``CAPABILITY_REGISTRY_AUTHORITY``

2. **CapabilityBus** (``core.capability_bus``)
   - *Role*: unified **registration and discovery bus** across all sources
     (MCP, Skill, Node, Device, Built-in, GitHub, Academic).
   - *Not* a dispatch authority (dispatch → ``CanonicalDispatcher``).
   - *Not* a live state monitor (health → ``CapabilityRuntimeRegistry``).
   - *Authority sentinel*: ``CAPABILITY_BUS_AUTHORITY``

3. **CapabilityResolver** (``core.unified.capability_resolver``)
   - *Role*: validated **consumer read path** — applies contract validation
     and converts ``CapabilityItem`` → ``CapabilityContract`` for consumers.
   - *Preferred interface* for ``OpenClawd`` and other consumers.
   - *Authority sentinel*: ``CAPABILITY_RESOLVER_AUTHORITY``

4. **CapabilityContract** (``core.unified.capability_contract``)
   - *Role*: canonical **schema validator** for all capability entries.
   - Called at registration (write) and at resolution (read).
   - *Authority sentinel*: ``CAPABILITY_CONTRACT_AUTHORITY``

5. **CapabilityRuntimeRegistry** (``core.capability_runtime``)
   - *Role*: **live runtime state** tracker (health, availability, last-seen).
   - Additive alongside the static inventory; answers "is it healthy now?"
   - *Authority sentinel*: ``CAPABILITY_RUNTIME_REGISTRY_AUTHORITY``

6. **CapabilityManager** (``core.capability_manager``) — DEPRECATED
   - *Status*: legacy compatibility facade (COMPAT_SECONDARY).
   - Do NOT use for new code; migrate to ``CapabilityBus`` / ``CapabilityResolver``.
   - Remove-after: Batch PR-8.
   - *Legacy sentinel*: ``CAPABILITY_MANAGER_LEGACY_SURFACE``

7. **CapabilityOrchestrator** (``core.capability_orchestrator``) — DEPRECATED
   - *Status*: legacy compatibility facade (COMPAT_SECONDARY).
   - Do NOT use for new code; migrate to ``CapabilityBus`` / ``CapabilityResolver``.
   - Remove-after: Batch PR-8.
   - *Legacy sentinel*: ``CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE``

Quick-start (canonical paths)
------------------------------
Registration::

    from core.capability_bus import get_capability_bus, CapabilityBusEntry, CapabilityBusRole
    bus = get_capability_bus()
    bus.register_device_capability(device_id, action, description)

Discovery (bus)::

    from core.capability import get_capability_bus
    bus = get_capability_bus()
    entries = bus.list_all()

Consumption (canonical resolver)::

    from core.capability import get_capability_resolver
    schemas = get_capability_resolver().collect_tool_schemas()
"""
from __future__ import annotations

import warnings as _warnings

# ---------------------------------------------------------------------------
# Package authority sentinel
# ---------------------------------------------------------------------------

CAPABILITY_PACKAGE_AUTHORITY = "core.capability"
"""Sentinel: ``core.capability`` is the canonical consolidated entry point for
the Galaxy capability subsystem (Batch PR-6).

Import from this package to access the canonical capability APIs without
needing to know the exact sub-module layout.
"""

# ---------------------------------------------------------------------------
# Authority sentinel re-exports (static strings — no heavy imports needed)
# ---------------------------------------------------------------------------

CAPABILITY_REGISTRY_AUTHORITY = "core.agent.capability_registry.CapabilityRegistry"
"""Re-exported from core.agent.capability_registry for convenient single-import access."""

CAPABILITY_BUS_AUTHORITY = "core.capability_bus.CapabilityBus"
"""Re-exported from core.capability_bus for convenient single-import access."""

CAPABILITY_CONTRACT_AUTHORITY = "core.unified.capability_contract.CapabilityContract"
"""Re-exported from core.unified.capability_contract for convenient single-import access."""

CAPABILITY_RESOLVER_AUTHORITY = "core.unified.capability_resolver.CapabilityResolver"
"""Re-exported from core.unified.capability_resolver for convenient single-import access."""

CAPABILITY_MANAGER_LEGACY_SURFACE = (
    "core.capability_manager.CapabilityManager:LEGACY_SURFACE"
)
"""Legacy surface marker — re-exported from core.capability_manager."""

CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE = (
    "core.capability_orchestrator.CapabilityOrchestrator:LEGACY_SURFACE"
)
"""Legacy surface marker — re-exported from core.capability_orchestrator."""

# ---------------------------------------------------------------------------
# Re-export canonical APIs for convenient import
# Lazy imports to avoid transitive fastapi/websocket dependencies when
# this package is imported in lightweight contexts (tests, diagnostics).
# ---------------------------------------------------------------------------


def get_capability_registry():
    """Return the canonical CapabilityRegistry singleton.

    Lazy import to avoid pulling in fastapi transitive dependencies.
    """
    from core.agent.capability_registry import get_capability_registry as _f
    return _f()


def get_capability_bus():
    """Return the canonical CapabilityBus singleton.

    Lazy import to avoid pulling in fastapi transitive dependencies.
    """
    from core.capability_bus import get_capability_bus as _f
    return _f()


def get_capability_resolver():
    """Return the canonical CapabilityResolver singleton.

    Lazy import to avoid pulling in fastapi transitive dependencies.
    """
    from core.unified.capability_resolver import get_capability_resolver as _f
    return _f()


def _get_class(module_path: str, class_name: str):
    """Lazy class accessor helper."""
    import importlib
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


@property  # type: ignore[misc]
def CapabilityRegistry():
    """Lazy class accessor (use get_capability_registry() for the singleton)."""
    return _get_class("core.agent.capability_registry", "CapabilityRegistry")


@property  # type: ignore[misc]
def CapabilityItem():
    """Lazy class accessor."""
    return _get_class("core.agent.capability_registry", "CapabilityItem")


@property  # type: ignore[misc]
def CapabilityBus():
    """Lazy class accessor (use get_capability_bus() for the singleton)."""
    return _get_class("core.capability_bus", "CapabilityBus")


@property  # type: ignore[misc]
def CapabilityBusEntry():
    """Lazy class accessor."""
    return _get_class("core.capability_bus", "CapabilityBusEntry")


@property  # type: ignore[misc]
def CapabilityBusRole():
    """Lazy class accessor."""
    return _get_class("core.capability_bus", "CapabilityBusRole")


@property  # type: ignore[misc]
def CapabilityHealthStatus():
    """Lazy class accessor."""
    return _get_class("core.capability_bus", "CapabilityHealthStatus")


@property  # type: ignore[misc]
def BusSnapshot():
    """Lazy class accessor."""
    return _get_class("core.capability_bus", "BusSnapshot")


@property  # type: ignore[misc]
def CapabilityContract():
    """Lazy class accessor."""
    return _get_class("core.unified.capability_contract", "CapabilityContract")


@property  # type: ignore[misc]
def CapabilitySource():
    """Lazy class accessor."""
    return _get_class("core.unified.capability_contract", "CapabilitySource")


@property  # type: ignore[misc]
def CapabilityContractError():
    """Lazy class accessor."""
    return _get_class("core.unified.capability_contract", "CapabilityContractError")


@property  # type: ignore[misc]
def CapabilityResolver():
    """Lazy class accessor (use get_capability_resolver() for the singleton)."""
    return _get_class("core.unified.capability_resolver", "CapabilityResolver")


def validate_capability_contract(contract):
    """Lazy wrapper around core.unified.capability_contract.validate_capability_contract."""
    from core.unified.capability_contract import validate_capability_contract as _f
    return _f(contract)


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Package authority
    "CAPABILITY_PACKAGE_AUTHORITY",
    # Registry
    "CapabilityRegistry",
    "CapabilityItem",
    "get_capability_registry",
    "CAPABILITY_REGISTRY_AUTHORITY",
    # Bus
    "CapabilityBus",
    "CapabilityBusEntry",
    "CapabilityBusRole",
    "CapabilityHealthStatus",
    "BusSnapshot",
    "get_capability_bus",
    "CAPABILITY_BUS_AUTHORITY",
    # Contract
    "CapabilityContract",
    "CapabilitySource",
    "CapabilityContractError",
    "validate_capability_contract",
    "CAPABILITY_CONTRACT_AUTHORITY",
    # Resolver
    "CapabilityResolver",
    "get_capability_resolver",
    "CAPABILITY_RESOLVER_AUTHORITY",
    # Legacy sentinels (diagnostics / migration guard)
    "CAPABILITY_MANAGER_LEGACY_SURFACE",
    "CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE",
]
