"""
core/system_resource.py
=======================
PR-7 — Governed System Resource Layer.

**Architecture**
----------------
This module provides the **single canonical representation layer** for every
external or system-facing resource integrated into Galaxy.  GitHub, academic
retrieval, device/runtime surfaces, local tools, add-on sources, and
engineering-support resources are all governed through the same model rather
than scattered subsystem-specific adapters.

The layer does **not** replace subsystem implementations.  It standardises how
resources are:

* represented  — :class:`SystemResourceRecord` carries the full canonical
  descriptor.
* registered   — :class:`SystemResourceRegistry` is the single enrollment
  point.
* discovered   — :meth:`SystemResourceRegistry.list_all` /
  :meth:`SystemResourceRegistry.list_by_type`.
* health-checked — :meth:`SystemResourceRegistry.set_health`.
* attributed   — every record carries ``source``, ``origin``, and
  ``trust_level`` fields that survive downstream attribution chains.
* exposed to OpenClawd — via the ``resource__*`` built-in tools registered in
  :data:`~core.openclawd._RESOURCE_BUILTIN_TOOLS`.
* surfaced to capability dispatch — via :meth:`CapabilityBus.register_resource_capability`.
* surfaced to knowledge flows — resource-derived knowledge outputs may carry
  attribution back to their :class:`SystemResourceRecord`.

**Canonical resource types**

+------------------+----------------------------------------------------------+
| Resource type    | Subsystem                                                |
+==================+==========================================================+
| GITHUB           | GitHub add-on source, knowledge source, eng context     |
| ACADEMIC         | Academic search/ingest/recall (arXiv, Semantic Scholar…)|
| DEVICE           | Registered device (Android, desktop, remote runtime)    |
| LOCAL_TOOL       | Local execution tool / native system-call surface       |
| ENGINEERING      | Mediated self-healing engineering loop (SelfHealingLoop)|
| MCP              | Model Context Protocol server tool                      |
| SKILL            | Galaxy Skill loaded via skill_loader                    |
| NODE             | Node-fabric node                                        |
| BUILTIN          | Hardwired system built-in                               |
| UNKNOWN          | Type not determined                                     |
+------------------+----------------------------------------------------------+

**Singletons**::

    system_resource_registry: SystemResourceRegistry  # created at import
    get_system_resource_registry() -> SystemResourceRegistry
    reset_system_resource_registry() -> None          # test helper

**Constraints**
---------------
* C1  — module-level singleton and ``get_system_resource_registry()`` accessor.
* C7  — public methods return ``{"success": bool, ...}`` or typed dataclasses
         with ``to_dict()``.
* C11 — uses stdlib ``logging``.
* No parallel resource authority is introduced; this supplements the existing
  :class:`~core.capability_bus.CapabilityBus`.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.SystemResource")

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SystemResourceType(str, Enum):
    """Origin/type classification of a governed system resource."""

    GITHUB = "github"
    """GitHub add-on source, knowledge source, and engineering-context source."""

    ACADEMIC = "academic"
    """Academic search, ingest, and recall surface."""

    DEVICE = "device"
    """Registered runtime device (Android, desktop, remote)."""

    LOCAL_TOOL = "local_tool"
    """Local execution tool or native system-call surface."""

    ENGINEERING = "engineering"
    """Mediated self-healing engineering loop."""

    MCP = "mcp"
    """Model Context Protocol server tool."""

    SKILL = "skill"
    """Galaxy Skill loaded via skill_loader."""

    NODE = "node"
    """Node-fabric node."""

    BUILTIN = "builtin"
    """Hardwired system built-in."""

    UNKNOWN = "unknown"
    """Type could not be determined."""


class SystemResourceHealth(str, Enum):
    """Runtime health of a governed system resource."""

    HEALTHY = "healthy"
    """Resource is available and responding normally."""

    DEGRADED = "degraded"
    """Resource is available with reduced reliability."""

    UNAVAILABLE = "unavailable"
    """Resource is registered but currently unreachable."""

    UNKNOWN = "unknown"
    """Health has not been assessed yet."""


class TrustLevel(str, Enum):
    """Trust classification of a governed system resource.

    Governs how the resource may be called and whether its output needs
    additional validation before consumption.
    """

    TRUSTED = "trusted"
    """First-party or verified resource — unrestricted use within policy."""

    VERIFIED = "verified"
    """Third-party resource that has passed integrity/schema checks."""

    RESTRICTED = "restricted"
    """Resource requires explicit approval for certain action categories."""

    UNTRUSTED = "untrusted"
    """Origin is unverified; outputs must be sandboxed before use."""


class SystemResourceAvailability(str, Enum):
    """Availability posture of a governed system resource."""

    AVAILABLE = "available"
    """Resource is fully reachable at this time."""

    LIMITED = "limited"
    """Resource is reachable but operating under constraints (rate-limit, etc.)."""

    UNAVAILABLE = "unavailable"
    """Resource is offline or otherwise unreachable."""

    UNKNOWN = "unknown"
    """Availability has not been assessed yet."""


# ---------------------------------------------------------------------------
# SystemResourceRecord — canonical resource descriptor
# ---------------------------------------------------------------------------


@dataclass
class SystemResourceRecord:
    """Canonical descriptor for a governed system resource.

    Every external or semi-external system surface is represented by one
    ``SystemResourceRecord`` enrolled in the :class:`SystemResourceRegistry`.

    Attributes
    ----------
    resource_id : str
        Unique identifier.  Auto-generated (UUID4 prefix) when not supplied.
    resource_type : SystemResourceType
        Categorical type of the resource.
    source : str
        Machine-readable source URI or identifier
        (e.g. ``"github://owner/repo"``, ``"academic://arxiv"``,
        ``"device://android_001"``).
    origin : str
        Human-readable origin description
        (e.g. ``"GitHub add-on source"``, ``"arXiv search engine"``).
    health : SystemResourceHealth
        Last-known health status.
    availability : SystemResourceAvailability
        Last-known availability posture.
    trust_level : TrustLevel
        Trust classification; governs allowed action categories.
    auth_scope : str
        Authorisation scope string (e.g. ``"read"``, ``"read:write"``,
        ``"token:GITHUB_TOKEN"``).  Empty means no auth required.
    capabilities : list[str]
        Canonical capability names exposed by this resource
        (e.g. ``["github__ingest", "github__context"]``).
    tags : list[str]
        Taxonomy tags for discovery (e.g. ``["knowledge", "engineering"]``).
    metadata : dict
        Arbitrary extension metadata.
    registered_at : float
        Unix timestamp when the record was enrolled.
    """

    resource_id: str = field(default_factory=lambda: f"res_{uuid.uuid4().hex[:12]}")
    """Unique identifier.  12 hex characters from a UUID4 provide ~281 trillion
    possible IDs; collision probability is negligible for expected registry
    sizes (hundreds to low thousands of entries)."""
    resource_type: SystemResourceType = SystemResourceType.UNKNOWN
    source: str = ""
    origin: str = ""
    health: SystemResourceHealth = SystemResourceHealth.UNKNOWN
    availability: SystemResourceAvailability = SystemResourceAvailability.UNKNOWN
    trust_level: TrustLevel = TrustLevel.VERIFIED
    auth_scope: str = ""
    """Authorisation scope string (e.g. ``"read"``, ``"read:write"``,
    ``"token:GITHUB_TOKEN"`` — where ``"token:<VAR>"`` names the environment
    variable that holds the credential; it is never the token value itself).
    Empty means no auth required."""
    capabilities: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable plain dict."""
        return {
            "resource_id": self.resource_id,
            "resource_type": (
                self.resource_type.value
                if isinstance(self.resource_type, SystemResourceType)
                else self.resource_type
            ),
            "source": self.source,
            "origin": self.origin,
            "health": (
                self.health.value
                if isinstance(self.health, SystemResourceHealth)
                else self.health
            ),
            "availability": (
                self.availability.value
                if isinstance(self.availability, SystemResourceAvailability)
                else self.availability
            ),
            "trust_level": (
                self.trust_level.value
                if isinstance(self.trust_level, TrustLevel)
                else self.trust_level
            ),
            "auth_scope": self.auth_scope,
            "capabilities": list(self.capabilities),
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "registered_at": self.registered_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SystemResourceRecord":
        """Reconstruct a :class:`SystemResourceRecord` from *data*."""
        try:
            resource_type = SystemResourceType(data.get("resource_type", "unknown"))
        except ValueError:
            resource_type = SystemResourceType.UNKNOWN
        try:
            health = SystemResourceHealth(data.get("health", "unknown"))
        except ValueError:
            health = SystemResourceHealth.UNKNOWN
        try:
            availability = SystemResourceAvailability(data.get("availability", "unknown"))
        except ValueError:
            availability = SystemResourceAvailability.UNKNOWN
        try:
            trust_level = TrustLevel(data.get("trust_level", "verified"))
        except ValueError:
            trust_level = TrustLevel.VERIFIED
        return cls(
            resource_id=data.get("resource_id", f"res_{uuid.uuid4().hex[:12]}"),
            resource_type=resource_type,
            source=data.get("source", ""),
            origin=data.get("origin", ""),
            health=health,
            availability=availability,
            trust_level=trust_level,
            auth_scope=data.get("auth_scope", ""),
            capabilities=list(data.get("capabilities", [])),
            tags=list(data.get("tags", [])),
            metadata=dict(data.get("metadata", {})),
            registered_at=data.get("registered_at", time.time()),
        )


# ---------------------------------------------------------------------------
# SystemResourceSnapshot — point-in-time view
# ---------------------------------------------------------------------------


@dataclass
class SystemResourceSnapshot:
    """Point-in-time view of the entire :class:`SystemResourceRegistry`.

    Attributes
    ----------
    resources : list[SystemResourceRecord]
        All currently registered records.
    total_count : int
        Total number of registered resources.
    healthy_count : int
        Resources with ``health == HEALTHY``.
    unavailable_count : int
        Resources with ``health == UNAVAILABLE``.
    captured_at : float
        Unix timestamp when the snapshot was captured.
    """

    resources: List[SystemResourceRecord] = field(default_factory=list)
    total_count: int = 0
    healthy_count: int = 0
    unavailable_count: int = 0
    captured_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable plain dict."""
        return {
            "resources": [r.to_dict() for r in self.resources],
            "total_count": self.total_count,
            "healthy_count": self.healthy_count,
            "unavailable_count": self.unavailable_count,
            "captured_at": self.captured_at,
        }


# ---------------------------------------------------------------------------
# SystemResourceRegistry — the single enrollment authority
# ---------------------------------------------------------------------------


class SystemResourceRegistry:
    """Single enrollment authority for all governed system resources.

    All external/semi-external system surfaces — GitHub, academic retrieval,
    device/runtime, local tools, engineering loop, MCP/Skill, node fabric, and
    built-ins — are represented here through the canonical
    :class:`SystemResourceRecord` shape.

    The registry is **not** a dispatch authority.  Dispatch still flows through
    :class:`~core.capability_bus.CapabilityBus` /
    :class:`~core.capabilities.canonical_dispatcher.CanonicalDispatcher`.
    This registry is the *directory* that makes OpenClawd and other consumers
    aware of what governed resources exist, their health, and their metadata.

    Thread-safety: a single ``threading.Lock`` guards all mutations.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # resource_id → SystemResourceRecord
        self._records: Dict[str, SystemResourceRecord] = {}

    # ── Enrollment ───────────────────────────────────────────────────────────

    def register(self, record: SystemResourceRecord) -> SystemResourceRecord:
        """Enroll *record* in the registry.

        If a record with the same ``resource_id`` is already present it is
        replaced.

        Returns
        -------
        SystemResourceRecord
            The enrolled record (same object that was passed in).
        """
        with self._lock:
            self._records[record.resource_id] = record
            logger.debug(
                "SystemResourceRegistry: registered %s type=%s source=%s",
                record.resource_id,
                record.resource_type.value,
                record.source,
            )
        return record

    def unregister(self, resource_id: str) -> bool:
        """Remove the resource identified by *resource_id*.

        Returns ``True`` if the record was present and removed, ``False`` if it
        was not found.
        """
        with self._lock:
            if resource_id in self._records:
                del self._records[resource_id]
                logger.debug("SystemResourceRegistry: unregistered %s", resource_id)
                return True
        return False

    # ── Discovery ────────────────────────────────────────────────────────────

    def lookup(self, resource_id: str) -> Optional[SystemResourceRecord]:
        """Return the record for *resource_id*, or ``None`` if not found."""
        with self._lock:
            return self._records.get(resource_id)

    def lookup_by_source(self, source: str) -> Optional[SystemResourceRecord]:
        """Return the first record whose ``source`` matches *source*."""
        with self._lock:
            for record in self._records.values():
                if record.source == source:
                    return record
        return None

    def list_all(self) -> List[SystemResourceRecord]:
        """Return a copy of all registered records."""
        with self._lock:
            return list(self._records.values())

    def list_by_type(
        self, resource_type: SystemResourceType
    ) -> List[SystemResourceRecord]:
        """Return all records of *resource_type*."""
        with self._lock:
            return [
                r
                for r in self._records.values()
                if r.resource_type == resource_type
            ]

    # ── Health management ────────────────────────────────────────────────────

    def set_health(
        self,
        resource_id: str,
        health: SystemResourceHealth,
        availability: Optional[SystemResourceAvailability] = None,
    ) -> bool:
        """Update health (and optionally availability) for *resource_id*.

        Returns ``True`` if the record was found and updated.
        """
        with self._lock:
            record = self._records.get(resource_id)
            if record is None:
                return False
            record.health = health
            if availability is not None:
                record.availability = availability
            return True

    # ── Snapshot ─────────────────────────────────────────────────────────────

    def snapshot(self) -> SystemResourceSnapshot:
        """Return a :class:`SystemResourceSnapshot` of the current state."""
        with self._lock:
            records = list(self._records.values())
        healthy = sum(
            1 for r in records if r.health == SystemResourceHealth.HEALTHY
        )
        unavailable = sum(
            1 for r in records if r.health == SystemResourceHealth.UNAVAILABLE
        )
        return SystemResourceSnapshot(
            resources=records,
            total_count=len(records),
            healthy_count=healthy,
            unavailable_count=unavailable,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

system_resource_registry: SystemResourceRegistry = SystemResourceRegistry()


def get_system_resource_registry() -> SystemResourceRegistry:
    """Return the module-level :class:`SystemResourceRegistry` singleton."""
    return system_resource_registry


def reset_system_resource_registry() -> None:
    """Reset the singleton to a fresh empty state.  **Test helper only.**"""
    global system_resource_registry
    system_resource_registry = SystemResourceRegistry()


# ---------------------------------------------------------------------------
# Built-in seeder helpers — seed well-known resources at startup
# ---------------------------------------------------------------------------


def seed_github_resource(
    *,
    auth_scope: str = "token:GITHUB_TOKEN",
    trust_level: TrustLevel = TrustLevel.VERIFIED,
    metadata: Optional[Dict[str, Any]] = None,
) -> SystemResourceRecord:
    """Enroll the GitHub system resource into the registry.

    Should be called once during system initialisation.  Safe to call
    multiple times — subsequent calls replace the existing record.
    """
    record = SystemResourceRecord(
        resource_id="builtin__github",
        resource_type=SystemResourceType.GITHUB,
        source="github://api.github.com",
        origin="GitHub add-on source / knowledge source / engineering context",
        health=SystemResourceHealth.UNKNOWN,
        availability=SystemResourceAvailability.UNKNOWN,
        trust_level=trust_level,
        auth_scope=auth_scope,
        capabilities=[
            "github__install",
            "github__uninstall",
            "github__list",
            "github__status",
            "github__ingest",
            "github__context",
        ],
        tags=["github", "addon", "knowledge", "engineering"],
        metadata=dict(metadata or {}),
    )
    get_system_resource_registry().register(record)
    return record


def seed_academic_resource(
    *,
    trust_level: TrustLevel = TrustLevel.TRUSTED,
    metadata: Optional[Dict[str, Any]] = None,
) -> SystemResourceRecord:
    """Enroll the academic retrieval system resource into the registry."""
    record = SystemResourceRecord(
        resource_id="builtin__academic",
        resource_type=SystemResourceType.ACADEMIC,
        source="academic://multi-source",
        origin="Academic search / ingest / recall (arXiv, Semantic Scholar, PubMed, IEEE)",
        health=SystemResourceHealth.HEALTHY,
        availability=SystemResourceAvailability.AVAILABLE,
        trust_level=trust_level,
        auth_scope="read",
        capabilities=[
            "academic__search",
            "academic__ingest",
            "academic__recall",
        ],
        tags=["academic", "knowledge", "search"],
        metadata=dict(metadata or {}),
    )
    get_system_resource_registry().register(record)
    return record


def seed_engineering_resource(
    *,
    trust_level: TrustLevel = TrustLevel.TRUSTED,
    metadata: Optional[Dict[str, Any]] = None,
) -> SystemResourceRecord:
    """Enroll the mediated engineering loop resource into the registry."""
    record = SystemResourceRecord(
        resource_id="builtin__engineering",
        resource_type=SystemResourceType.ENGINEERING,
        source="engineering://self-healing-loop",
        origin="Mediated self-healing engineering loop (SelfHealingLoop, PR-6)",
        health=SystemResourceHealth.HEALTHY,
        availability=SystemResourceAvailability.AVAILABLE,
        trust_level=trust_level,
        auth_scope="read:write",
        capabilities=[
            "engineer__diagnose",
            "engineer__context",
            "engineer__plan",
            "engineer__apply",
            "engineer__validate",
            "engineer__record",
            "engineer__status",
        ],
        tags=["engineering", "self-healing", "coding"],
        metadata=dict(metadata or {}),
    )
    get_system_resource_registry().register(record)
    return record


def seed_device_resource(
    device_id: str,
    *,
    capabilities: Optional[List[str]] = None,
    trust_level: TrustLevel = TrustLevel.VERIFIED,
    metadata: Optional[Dict[str, Any]] = None,
) -> SystemResourceRecord:
    """Enroll a runtime device resource into the registry.

    Parameters
    ----------
    device_id:
        Unique device identifier (must match the device registered in
        ``DeviceRegistry`` / ``UnifiedDeviceManager``).
    capabilities:
        List of canonical capability names exposed by this device
        (e.g. ``["device__android_001__take_screenshot"]``).
    trust_level:
        Trust classification; defaults to ``VERIFIED``.
    metadata:
        Optional extension metadata.
    """
    record = SystemResourceRecord(
        resource_id=f"device__{device_id}",
        resource_type=SystemResourceType.DEVICE,
        source=f"device://{device_id}",
        origin=f"Runtime device: {device_id}",
        health=SystemResourceHealth.UNKNOWN,
        availability=SystemResourceAvailability.UNKNOWN,
        trust_level=trust_level,
        auth_scope="device:control",
        capabilities=list(capabilities or []),
        tags=["device", "runtime"],
        metadata=dict(metadata or {}),
    )
    get_system_resource_registry().register(record)
    return record


def seed_local_tool_resource(
    tool_id: str,
    *,
    capabilities: Optional[List[str]] = None,
    trust_level: TrustLevel = TrustLevel.TRUSTED,
    auth_scope: str = "local",
    metadata: Optional[Dict[str, Any]] = None,
) -> SystemResourceRecord:
    """Enroll a local execution tool resource into the registry.

    Parameters
    ----------
    tool_id:
        Unique tool identifier (e.g. ``"file_system"``, ``"process_runner"``).
    capabilities:
        List of canonical capability names exposed by this tool.
    trust_level:
        Trust classification; defaults to ``TRUSTED``.
    auth_scope:
        Authorisation scope string; defaults to ``"local"``.
    metadata:
        Optional extension metadata.
    """
    record = SystemResourceRecord(
        resource_id=f"local_tool__{tool_id}",
        resource_type=SystemResourceType.LOCAL_TOOL,
        source=f"local://{tool_id}",
        origin=f"Local execution tool: {tool_id}",
        health=SystemResourceHealth.HEALTHY,
        availability=SystemResourceAvailability.AVAILABLE,
        trust_level=trust_level,
        auth_scope=auth_scope,
        capabilities=list(capabilities or []),
        tags=["local_tool", "execution"],
        metadata=dict(metadata or {}),
    )
    get_system_resource_registry().register(record)
    return record
