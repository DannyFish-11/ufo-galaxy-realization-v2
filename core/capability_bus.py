#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/capability_bus.py
======================
PR-3 — Canonical Capability Bus.

Single unified registry for all callable resources in Galaxy: node
capabilities, device actions, MCP tools, Skills, GitHub add-ons, and
built-ins.

Design
------
``CapabilityBus`` is **not** a routing authority and owns no dispatch
decisions.  Its sole job is:

1. Provide a single place to *register* and *discover* all capabilities.
2. Surface a coherent :class:`CapabilityBusEntry` shape that carries
   source/role/health/tags/metadata/schema information.
3. Seed entries from ``config/node_registry.json`` *without hardcoding* node
   names — the registry file remains the authoritative source for nodes.
4. Let device-registration paths, runtime-loaded nodes, MCP/Skill loaders, and
   add-ons all register in the *same* way so callers can reason about
   capabilities rather than separate subsystem-specific registries.

All dispatch still goes through :class:`~core.capabilities.CanonicalDispatcher`
— ``CapabilityBus`` is the *directory*, not the *executor*.

Naming convention (aligns with CanonicalDispatcher prefixes)
-------------------------------------------------------------
  ``mcp__<server_id>__<tool_name>``    → :attr:`CapabilityBusRole.MCP`
  ``mcp__gateway__<tool_name>``        → :attr:`CapabilityBusRole.MCP_GW`
  ``skill__<skill_id>``                → :attr:`CapabilityBusRole.SKILL`
  ``node__<node_id>__<action>``        → :attr:`CapabilityBusRole.NODE`
  ``device__<device_id>__<action>``    → :attr:`CapabilityBusRole.DEVICE`
  ``github__<action>``                 → :attr:`CapabilityBusRole.GITHUB`
  ``academic__<action>``               → :attr:`CapabilityBusRole.ACADEMIC`
  ``builtin__<name>``                  → :attr:`CapabilityBusRole.BUILTIN`

Public API
----------
  :func:`get_capability_bus`                — singleton factory
  :func:`reset_capability_bus`              — reset singleton (test helper)
  :meth:`CapabilityBus.register`            — register a :class:`CapabilityBusEntry`
  :meth:`CapabilityBus.unregister`          — remove entry by canonical name
  :meth:`CapabilityBus.lookup`              — lookup by name → entry or ``None``
  :meth:`CapabilityBus.list_all`            — all registered entries
  :meth:`CapabilityBus.list_by_role`        — filter by :class:`CapabilityBusRole`
  :meth:`CapabilityBus.set_health`          — update health status
  :meth:`CapabilityBus.bus_snapshot`        — return a :class:`BusSnapshot`
  :meth:`CapabilityBus.seed_from_node_registry` — seed nodes from JSON registry
  :meth:`CapabilityBus.register_device_capability` — register device action

Usage::

    from core.capability_bus import get_capability_bus, CapabilityBusEntry, CapabilityBusRole

    bus = get_capability_bus()
    bus.seed_from_node_registry()          # populate from config/node_registry.json

    entry = bus.lookup("node__08__execute")
    print(entry.display_name, entry.health)

    bus.register_device_capability(
        device_id="android_001",
        action="take_screenshot",
        description="Capture current screen on the registered Android device.",
    )
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CapabilityBus")

# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------


class CapabilityBusRole(str, Enum):
    """Origin / type classification of a capability registered in the bus."""

    NODE = "node"
    """Node in the node fabric (node__<id>__<action>)."""

    DEVICE = "device"
    """Registered device action (device__<id>__<action>)."""

    SKILL = "skill"
    """Galaxy Skill loaded via skill_loader (skill__<id>)."""

    MCP = "mcp"
    """MCP server tool (mcp__<server_id>__<tool_name>)."""

    MCP_GW = "mcp_gw"
    """MCP gateway built-in (mcp__gateway__<tool_name>)."""

    GITHUB = "github"
    """GitHub add-on action (github__<action>)."""

    ACADEMIC = "academic"
    """Academic search/ingest/recall action (academic__<action>)."""

    ENGINEERING = "engineering"
    """Mediated self-healing engineering loop action (engineer__<action>)."""

    BUILTIN = "builtin"
    """Hardwired system built-in (builtin__<name>)."""

    RESOURCE = "resource"
    """Governed system resource management action (resource__<action>)."""

    UNKNOWN = "unknown"
    """Source could not be determined."""

    @classmethod
    def from_tool_name(cls, tool_name: str) -> "CapabilityBusRole":
        """Infer :class:`CapabilityBusRole` from a canonical tool name."""
        if tool_name.startswith("mcp__gateway__"):
            return cls.MCP_GW
        if tool_name.startswith("mcp__"):
            return cls.MCP
        if tool_name.startswith("skill__"):
            return cls.SKILL
        if tool_name.startswith("node__"):
            return cls.NODE
        if tool_name.startswith("device__"):
            return cls.DEVICE
        if tool_name.startswith("github__"):
            return cls.GITHUB
        if tool_name.startswith("academic__"):
            return cls.ACADEMIC
        if tool_name.startswith("engineer__"):
            return cls.ENGINEERING
        if tool_name.startswith("resource__"):
            return cls.RESOURCE
        if tool_name.startswith("builtin__"):
            return cls.BUILTIN
        return cls.UNKNOWN


# ---------------------------------------------------------------------------
# Health status
# ---------------------------------------------------------------------------


class CapabilityHealthStatus(str, Enum):
    """Runtime health of a registered capability."""

    HEALTHY = "healthy"
    """Capability is available and responding normally."""

    DEGRADED = "degraded"
    """Capability is available but operating with reduced reliability."""

    UNAVAILABLE = "unavailable"
    """Capability is registered but not currently reachable."""

    UNKNOWN = "unknown"
    """Health has not been assessed yet."""


# ---------------------------------------------------------------------------
# CapabilityBusEntry
# ---------------------------------------------------------------------------


@dataclass
class CapabilityBusEntry:
    """Unified capability descriptor stored in the :class:`CapabilityBus`.

    Attributes
    ----------
    name : str
        Canonical dispatch name matching one of the
        :class:`~core.capabilities.CanonicalDispatcher` prefixes
        (e.g. ``node__08__execute``, ``skill__hello``, …).
    display_name : str
        Human-readable label (e.g. ``"Fetch (node 08)"``).
    description : str
        Short description of what the capability does.
    role : CapabilityBusRole
        Origin/type of this capability.
    source_id : str
        Source-specific identifier (node_id, device_id, skill_id, server_id,
        …).
    health : CapabilityHealthStatus
        Last-known health status; defaults to ``UNKNOWN`` until assessed.
    tags : list[str]
        Taxonomy tags for discovery (e.g. ``["http", "fetch"]``).
    metadata : dict
        Arbitrary extension metadata (e.g. ``{"production_ready": True}``).
    schema : dict
        JSON Schema object for accepted parameters (may be ``{}``).
    node_key : str
        For NODE entries: the directory key from ``node_registry.json``
        (e.g. ``"Node_<N>_<Name>"``).  Empty for non-node entries.
    registered_at : float
        Unix timestamp when this entry was registered.
    """

    name: str
    display_name: str
    description: str
    role: CapabilityBusRole
    source_id: str = ""
    health: CapabilityHealthStatus = CapabilityHealthStatus.UNKNOWN
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema: Dict[str, Any] = field(default_factory=dict)
    node_key: str = ""
    registered_at: float = field(default_factory=time.time)

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable plain dict."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "role": self.role.value if isinstance(self.role, CapabilityBusRole) else self.role,
            "source_id": self.source_id,
            "health": self.health.value if isinstance(self.health, CapabilityHealthStatus) else self.health,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "schema": dict(self.schema),
            "node_key": self.node_key,
            "registered_at": self.registered_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CapabilityBusEntry":
        """Reconstruct a :class:`CapabilityBusEntry` from *data*."""
        try:
            role = CapabilityBusRole(data.get("role", "unknown"))
        except ValueError:
            role = CapabilityBusRole.UNKNOWN
        try:
            health = CapabilityHealthStatus(data.get("health", "unknown"))
        except ValueError:
            health = CapabilityHealthStatus.UNKNOWN
        return cls(
            name=data.get("name", ""),
            display_name=data.get("display_name", data.get("name", "")),
            description=data.get("description", ""),
            role=role,
            source_id=data.get("source_id", ""),
            health=health,
            tags=list(data.get("tags", [])),
            metadata=dict(data.get("metadata", {})),
            schema=dict(data.get("schema", {})),
            node_key=data.get("node_key", ""),
            registered_at=float(data.get("registered_at", time.time())),
        )


# ---------------------------------------------------------------------------
# BusSnapshot
# ---------------------------------------------------------------------------


@dataclass
class BusSnapshot:
    """Point-in-time snapshot of the :class:`CapabilityBus` state.

    Attributes
    ----------
    entries : list[CapabilityBusEntry]
        All currently registered entries.
    total_count : int
        Total number of registered capabilities.
    by_role : dict[str, int]
        Count of capabilities per :class:`CapabilityBusRole` value.
    healthy_count : int
        Number of entries with :attr:`CapabilityHealthStatus.HEALTHY`.
    seeded_from_node_registry : bool
        Whether :meth:`CapabilityBus.seed_from_node_registry` has been called.
    snapshot_at : float
        Unix timestamp of snapshot creation.
    """

    entries: List[CapabilityBusEntry]
    total_count: int
    by_role: Dict[str, int]
    healthy_count: int
    seeded_from_node_registry: bool
    snapshot_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_count": self.total_count,
            "by_role": dict(self.by_role),
            "healthy_count": self.healthy_count,
            "seeded_from_node_registry": self.seeded_from_node_registry,
            "snapshot_at": self.snapshot_at,
            "entries": [e.to_dict() for e in self.entries],
        }


# ---------------------------------------------------------------------------
# CapabilityBus
# ---------------------------------------------------------------------------


class CapabilityBus:
    """Single unified capability bus for all callable Galaxy resources.

    All access goes through the singleton returned by :func:`get_capability_bus`.
    Direct instantiation is allowed only in tests (use :func:`reset_capability_bus`
    to obtain a fresh instance).

    Thread-safety
    -------------
    All mutation methods hold ``_lock`` so that concurrent registrations from
    multiple loaders (node fabric, skill loader, device registry) are safe.
    """

    def __init__(self) -> None:
        self._entries: Dict[str, CapabilityBusEntry] = {}
        self._lock = threading.Lock()
        self._seeded_from_node_registry: bool = False

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, entry: CapabilityBusEntry) -> None:
        """Register *entry* in the bus.

        If an entry with the same :attr:`~CapabilityBusEntry.name` already
        exists it is silently replaced (last writer wins).  This allows
        runtime re-registration on node reload or device reconnect without
        creating duplicates.
        """
        if not entry.name:
            raise ValueError("CapabilityBusEntry.name must not be empty")
        with self._lock:
            self._entries[entry.name] = entry
        logger.debug(
            "CapabilityBus.register: %s (role=%s, source_id=%s)",
            entry.name,
            entry.role.value,
            entry.source_id,
        )

    def unregister(self, name: str) -> bool:
        """Remove the entry for *name*.

        Returns ``True`` if the entry existed and was removed, ``False``
        if it was not present.
        """
        with self._lock:
            if name in self._entries:
                del self._entries[name]
                logger.debug("CapabilityBus.unregister: %s", name)
                return True
        return False

    def set_health(
        self, name: str, health: CapabilityHealthStatus
    ) -> bool:
        """Update the :attr:`~CapabilityBusEntry.health` field for *name*.

        Returns ``True`` on success, ``False`` if the entry was not found.
        """
        with self._lock:
            if name not in self._entries:
                return False
            self._entries[name].health = health
        return True

    # ── Lookup / listing ─────────────────────────────────────────────────────

    def lookup(self, name: str) -> Optional[CapabilityBusEntry]:
        """Return the entry for *name* or ``None`` if not registered."""
        with self._lock:
            return self._entries.get(name)

    def list_all(self) -> List[CapabilityBusEntry]:
        """Return a snapshot list of all registered entries."""
        with self._lock:
            return list(self._entries.values())

    def list_by_role(self, role: CapabilityBusRole) -> List[CapabilityBusEntry]:
        """Return entries whose :attr:`~CapabilityBusEntry.role` matches *role*."""
        with self._lock:
            return [e for e in self._entries.values() if e.role == role]

    def contains(self, name: str) -> bool:
        """Return ``True`` iff *name* is registered in the bus."""
        with self._lock:
            return name in self._entries

    # ── Snapshot ─────────────────────────────────────────────────────────────

    def bus_snapshot(self) -> BusSnapshot:
        """Return a :class:`BusSnapshot` of the current bus state."""
        with self._lock:
            entries = list(self._entries.values())
            seeded = self._seeded_from_node_registry

        by_role: Dict[str, int] = {}
        healthy = 0
        for e in entries:
            role_val = e.role.value if isinstance(e.role, CapabilityBusRole) else str(e.role)
            by_role[role_val] = by_role.get(role_val, 0) + 1
            if e.health == CapabilityHealthStatus.HEALTHY:
                healthy += 1

        return BusSnapshot(
            entries=entries,
            total_count=len(entries),
            by_role=by_role,
            healthy_count=healthy,
            seeded_from_node_registry=seeded,
            snapshot_at=time.time(),
        )

    def clear(self) -> None:
        """Remove all entries.  Primarily intended for test isolation."""
        with self._lock:
            self._entries.clear()
            self._seeded_from_node_registry = False

    # ── Node registry seeding ─────────────────────────────────────────────────

    def seed_from_node_registry(
        self,
        registry_path: Optional[str] = None,
        default_action: str = "execute",
        mark_seeded: bool = True,
    ) -> int:
        """Seed :class:`CapabilityBusEntry` records from ``config/node_registry.json``.

        This method reads the registry file and registers one
        ``node__<node_id>__<action>`` entry per node **without hardcoding any
        node names**.  It is safe to call multiple times; existing entries are
        replaced with refreshed data.

        Parameters
        ----------
        registry_path:
            Path to the JSON registry file.  If ``None`` the default
            ``<project_root>/config/node_registry.json`` is used.
        default_action:
            Action name appended to the canonical tool name
            (``node__<id>__<default_action>``).  Defaults to ``"execute"``.
        mark_seeded:
            When ``True`` (default), set the internal
            ``_seeded_from_node_registry`` flag so :meth:`bus_snapshot` can
            report it.

        Returns
        -------
        int
            Number of new entries registered (entries already present are
            counted too, as they are refreshed).
        """
        path = registry_path or _default_registry_path()
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except FileNotFoundError:
            logger.warning("CapabilityBus.seed_from_node_registry: file not found: %s", path)
            return 0
        except Exception as exc:
            logger.warning("CapabilityBus.seed_from_node_registry: error reading %s: %s", path, exc)
            return 0

        nodes_dict: Dict[str, Any] = raw.get("nodes", raw)
        if not isinstance(nodes_dict, dict):
            logger.warning(
                "CapabilityBus.seed_from_node_registry: unexpected format in %s", path
            )
            return 0

        count = 0
        for node_key, node_info in nodes_dict.items():
            if not isinstance(node_info, dict):
                continue
            node_id: str = str(node_info.get("id", ""))
            node_name: str = node_info.get("name", node_key)
            status: str = node_info.get("status", "unknown")
            production_ready: bool = bool(node_info.get("production_ready", False))

            # Build canonical dispatch name
            tool_name = f"node__{node_id}__{default_action}"

            # Derive health from registry status
            if status == "active" and production_ready:
                health = CapabilityHealthStatus.HEALTHY
            elif status == "active":
                health = CapabilityHealthStatus.DEGRADED
            else:
                health = CapabilityHealthStatus.UNAVAILABLE

            # Build tags from registry metadata
            tags: List[str] = ["node"]
            if production_ready:
                tags.append("production_ready")
            if status:
                tags.append(f"status:{status}")

            entry = CapabilityBusEntry(
                name=tool_name,
                display_name=f"{node_name} (node {node_id})",
                description=f"Node {node_name} [{node_id}] — {status}",
                role=CapabilityBusRole.NODE,
                source_id=node_id,
                health=health,
                tags=tags,
                metadata={
                    "node_key": node_key,
                    "status": status,
                    "production_ready": production_ready,
                    "path": node_info.get("path", ""),
                },
                schema={},
                node_key=node_key,
            )
            self.register(entry)
            count += 1

        if mark_seeded:
            with self._lock:
                self._seeded_from_node_registry = True

        logger.info(
            "CapabilityBus.seed_from_node_registry: registered %d node entries from %s",
            count,
            path,
        )
        return count

    # ── Device capability registration ───────────────────────────────────────

    def register_device_capability(
        self,
        device_id: str,
        action: str,
        description: str,
        *,
        display_name: str = "",
        tags: Optional[List[str]] = None,
        schema: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        health: CapabilityHealthStatus = CapabilityHealthStatus.UNKNOWN,
    ) -> CapabilityBusEntry:
        """Register a device action as a first-class capability.

        Parameters
        ----------
        device_id:
            Device identifier (must match the device registered in
            ``DeviceRegistry`` / ``UnifiedDeviceManager``).
        action:
            Action name (e.g. ``"take_screenshot"``, ``"tap"``, …).
        description:
            Human-readable description of the action.
        display_name:
            Optional override for the human-readable label.
        tags / schema / metadata:
            Optional taxonomy, parameter schema, and extension metadata.
        health:
            Initial health status; defaults to ``UNKNOWN``.

        Returns
        -------
        CapabilityBusEntry
            The registered entry.
        """
        tool_name = f"device__{device_id}__{action}"
        entry = CapabilityBusEntry(
            name=tool_name,
            display_name=display_name or f"{action} ({device_id})",
            description=description,
            role=CapabilityBusRole.DEVICE,
            source_id=device_id,
            health=health,
            tags=list(tags or []) + ["device"],
            metadata=dict(metadata or {}),
            schema=dict(schema or {}),
        )
        self.register(entry)
        return entry

    # ── MCP / Skill / GitHub / Builtin registration helpers ──────────────────

    def register_mcp_tool(
        self,
        server_id: str,
        tool_name: str,
        description: str = "",
        *,
        schema: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        health: CapabilityHealthStatus = CapabilityHealthStatus.UNKNOWN,
    ) -> CapabilityBusEntry:
        """Register an MCP server tool in the bus."""
        if server_id == "gateway":
            canonical = f"mcp__gateway__{tool_name}"
            role = CapabilityBusRole.MCP_GW
        else:
            canonical = f"mcp__{server_id}__{tool_name}"
            role = CapabilityBusRole.MCP
        entry = CapabilityBusEntry(
            name=canonical,
            display_name=f"{tool_name} (mcp:{server_id})",
            description=description or f"MCP tool '{tool_name}' from server '{server_id}'",
            role=role,
            source_id=server_id,
            health=health,
            tags=list(tags or []) + ["mcp"],
            metadata=dict(metadata or {}),
            schema=dict(schema or {}),
        )
        self.register(entry)
        return entry

    def register_skill(
        self,
        skill_id: str,
        description: str = "",
        *,
        schema: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        health: CapabilityHealthStatus = CapabilityHealthStatus.UNKNOWN,
    ) -> CapabilityBusEntry:
        """Register a Galaxy Skill in the bus."""
        canonical = f"skill__{skill_id}"
        entry = CapabilityBusEntry(
            name=canonical,
            display_name=f"{skill_id} (skill)",
            description=description or f"Skill '{skill_id}'",
            role=CapabilityBusRole.SKILL,
            source_id=skill_id,
            health=health,
            tags=list(tags or []) + ["skill"],
            metadata=dict(metadata or {}),
            schema=dict(schema or {}),
        )
        self.register(entry)
        return entry

    def register_academic_capability(
        self,
        action: str,
        description: str = "",
        *,
        schema: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        health: CapabilityHealthStatus = CapabilityHealthStatus.HEALTHY,
    ) -> CapabilityBusEntry:
        """Register an academic system resource capability in the bus.

        Canonical name: ``academic__{action}`` (e.g. ``academic__search``).
        """
        canonical = f"academic__{action}"
        entry = CapabilityBusEntry(
            name=canonical,
            display_name=f"{action} (academic)",
            description=description or f"Academic capability '{action}'",
            role=CapabilityBusRole.ACADEMIC,
            source_id=action,
            health=health,
            tags=list(tags or []) + ["academic"],
            metadata=dict(metadata or {}),
            schema=dict(schema or {}),
        )
        self.register(entry)
        return entry

    def register_engineering_capability(
        self,
        action: str,
        description: str = "",
        *,
        schema: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        health: CapabilityHealthStatus = CapabilityHealthStatus.HEALTHY,
    ) -> CapabilityBusEntry:
        """Register a mediated engineering loop capability in the bus.

        Canonical name: ``engineer__{action}`` (e.g. ``engineer__diagnose``).
        """
        canonical = f"engineer__{action}"
        entry = CapabilityBusEntry(
            name=canonical,
            display_name=f"{action} (engineering)",
            description=description or f"Engineering capability '{action}'",
            role=CapabilityBusRole.ENGINEERING,
            source_id=action,
            health=health,
            tags=list(tags or []) + ["engineering"],
            metadata=dict(metadata or {}),
            schema=dict(schema or {}),
        )
        self.register(entry)
        return entry

    def register_resource_capability(
        self,
        action: str,
        description: str = "",
        *,
        schema: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        health: CapabilityHealthStatus = CapabilityHealthStatus.HEALTHY,
    ) -> CapabilityBusEntry:
        """Register a governed system resource management capability in the bus.

        Canonical name: ``resource__{action}``
        (e.g. ``resource__list``, ``resource__status``).

        These capabilities expose the :class:`~core.system_resource.SystemResourceRegistry`
        through the unified capability dispatch path so that OpenClawd and other
        consumers can query the governed resource layer without calling the
        registry directly.
        """
        canonical = f"resource__{action}"
        entry = CapabilityBusEntry(
            name=canonical,
            display_name=f"{action} (resource registry)",
            description=description or f"Governed resource registry capability '{action}'",
            role=CapabilityBusRole.RESOURCE,
            source_id=action,
            health=health,
            tags=list(tags or []) + ["resource", "governance"],
            metadata=dict(metadata or {}),
            schema=dict(schema or {}),
        )
        self.register(entry)
        return entry


def _default_registry_path() -> str:
    """Return the default path to ``config/node_registry.json``."""
    # Walk up from this file: core/ → project_root/ → config/
    this_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(this_dir)
    return os.path.join(project_root, "config", "node_registry.json")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_BUS_INSTANCE: Optional[CapabilityBus] = None
_BUS_LOCK = threading.Lock()


def get_capability_bus() -> CapabilityBus:
    """Return the module-level singleton :class:`CapabilityBus`.

    The bus is created lazily on first call.  It does **not** auto-seed from
    the node registry; callers that need node entries must call
    :meth:`CapabilityBus.seed_from_node_registry` explicitly (or rely on the
    framework bootstrap path doing so).
    """
    global _BUS_INSTANCE
    with _BUS_LOCK:
        if _BUS_INSTANCE is None:
            _BUS_INSTANCE = CapabilityBus()
    return _BUS_INSTANCE


def reset_capability_bus() -> CapabilityBus:
    """Reset and return a fresh :class:`CapabilityBus` singleton.

    Intended exclusively for test isolation.  Call this at the start of each
    test that needs a clean bus state.
    """
    global _BUS_INSTANCE
    with _BUS_LOCK:
        _BUS_INSTANCE = CapabilityBus()
    return _BUS_INSTANCE
