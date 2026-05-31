#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/mesh/device_role_allocator.py
====================================
Block-4 (PR-4) — Device Role Allocator

Allocates :class:`~core.mesh.body_mesh_registry.DeviceRole` values to
devices based on their declared capabilities and current health scores, then
keeps the :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry` up-to-date.

Design
------
- Reads capabilities from :class:`~core.unified.device_manager.UnifiedDeviceManager`.
- Reads health scores from :class:`~core.unified.device_health.DeviceHealthScorer`.
- Writes role assignments + body_score into :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry`.
- Singleton via :func:`get_device_role_allocator` / :func:`reset_device_role_allocator`.

Capability → Role mapping
--------------------------
The allocator uses a simple capability-keyword → role mapping that can be
extended via :meth:`DeviceRoleAllocator.register_capability_rule`.

Default rules:
  ``camera / microphone / sensor / gps / accelerometer / gyroscope``
    → :attr:`~DeviceRole.PERCEPTION`
  ``touch / keyboard / mouse / automation / actuator / motor / robot``
    → :attr:`~DeviceRole.ACTION`
  ``screen / display / speaker / notification / bluetooth / nfc``
    → :attr:`~DeviceRole.PRESENCE`
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .body_mesh_registry import BodyMeshRegistry, DeviceRole, get_body_mesh_registry

logger = logging.getLogger("Galaxy.Mesh.DeviceRoleAllocator")

# ---------------------------------------------------------------------------
# Default capability → role rules (keyword substring match)
# ---------------------------------------------------------------------------

_DEFAULT_CAPABILITY_RULES: List[Tuple[str, DeviceRole]] = [
    # Perception capabilities
    ("camera",        DeviceRole.PERCEPTION),
    ("microphone",    DeviceRole.PERCEPTION),
    ("sensor",        DeviceRole.PERCEPTION),
    ("gps",           DeviceRole.PERCEPTION),
    ("accelerometer", DeviceRole.PERCEPTION),
    ("gyroscope",     DeviceRole.PERCEPTION),
    ("lidar",         DeviceRole.PERCEPTION),
    # Action capabilities
    ("touch",         DeviceRole.ACTION),
    ("keyboard",      DeviceRole.ACTION),
    ("mouse",         DeviceRole.ACTION),
    ("automation",    DeviceRole.ACTION),
    ("actuator",      DeviceRole.ACTION),
    ("motor",         DeviceRole.ACTION),
    ("robot",         DeviceRole.ACTION),
    ("printer",       DeviceRole.ACTION),
    ("drone",         DeviceRole.ACTION),
    # Presence capabilities
    ("screen",        DeviceRole.PRESENCE),
    ("display",       DeviceRole.PRESENCE),
    ("speaker",       DeviceRole.PRESENCE),
    ("notification",  DeviceRole.PRESENCE),
    ("bluetooth",     DeviceRole.PRESENCE),
    ("nfc",           DeviceRole.PRESENCE),
    ("audio",         DeviceRole.PRESENCE),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AllocationResult:
    """Result of a single device role allocation pass.

    Attributes
    ----------
    device_id:
        Device that was allocated.
    roles_assigned:
        Roles assigned in this run.
    body_score:
        Body score written to the registry.
    session_id:
        Session used for the assignment computation.
    """

    device_id: str
    roles_assigned: List[DeviceRole]
    body_score: float
    session_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "roles_assigned": [r.value for r in self.roles_assigned],
            "body_score": self.body_score,
            "session_id": self.session_id,
        }


# ---------------------------------------------------------------------------
# DeviceRoleAllocator
# ---------------------------------------------------------------------------


class DeviceRoleAllocator:
    """Allocates device roles and keeps :class:`BodyMeshRegistry` current.

    Parameters
    ----------
    registry:
        Body-mesh registry to write into.  Defaults to the global singleton.
    capability_rules:
        Initial list of ``(capability_keyword, role)`` tuples.  The default
        rules are always applied first; these extend them.
    """

    def __init__(
        self,
        registry: Optional[BodyMeshRegistry] = None,
        capability_rules: Optional[List[Tuple[str, DeviceRole]]] = None,
    ) -> None:
        self._registry = registry or get_body_mesh_registry()
        self._rules: List[Tuple[str, DeviceRole]] = list(_DEFAULT_CAPABILITY_RULES)
        if capability_rules:
            self._rules.extend(capability_rules)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def register_capability_rule(self, keyword: str, role: DeviceRole) -> None:
        """Add a custom capability keyword → role mapping.

        Args:
            keyword:  Lowercase substring to match in a capability string.
            role:     Role to assign when the keyword is found.
        """
        with self._lock:
            self._rules.append((keyword.lower(), role))

    # ------------------------------------------------------------------
    # Role inference
    # ------------------------------------------------------------------

    def infer_roles(self, capabilities: List[str]) -> List[DeviceRole]:
        """Infer roles from a list of capability strings.

        Uses substring matching against :attr:`_rules` (case-insensitive).
        Each unique role is returned at most once.

        Args:
            capabilities:  List of capability keyword strings.

        Returns:
            Deduplicated list of inferred :class:`DeviceRole` values.
        """
        caps_lower = [c.lower() for c in capabilities]
        found: set = set()
        with self._lock:
            rules = list(self._rules)
        for cap in caps_lower:
            for keyword, role in rules:
                if keyword in cap:
                    found.add(role)
        return list(found)

    # ------------------------------------------------------------------
    # Allocation
    # ------------------------------------------------------------------

    def allocate(
        self,
        device_id: str,
        capabilities: List[str],
        health_score: float = 1.0,
        session_id: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> AllocationResult:
        """Allocate roles for a single device and update the registry.

        1. Infer roles from *capabilities*.
        2. Register the device + roles in the :class:`BodyMeshRegistry`.
        3. Update the body_score using *health_score*.

        Args:
            device_id:       Device identifier.
            capabilities:    Capability strings (from UnifiedDevice.capabilities).
            health_score:    Current health score in ``[0.0, 1.0]``.
            session_id:      Optional session the device belongs to.
            extra_metadata:  Additional metadata to store in the entry.

        Returns:
            :class:`AllocationResult` describing what was assigned.
        """
        roles = self.infer_roles(capabilities)
        if not roles:
            logger.debug(
                "DeviceRoleAllocator: no roles inferred for device=%s caps=%s",
                device_id,
                capabilities,
            )

        self._registry.register(
            device_id=device_id,
            roles=roles,
            session_id=session_id,
            metadata=extra_metadata or {},
        )
        self._registry.score_entry(device_id, health_score)

        entry = self._registry.get(device_id)
        score = entry.body_score if entry else 0.0

        result = AllocationResult(
            device_id=device_id,
            roles_assigned=roles,
            body_score=score,
            session_id=session_id,
        )
        logger.info(
            "DeviceRoleAllocator: allocated device=%s roles=%s body_score=%.3f session=%s",
            device_id,
            [r.value for r in roles],
            score,
            session_id,
        )
        return result

    def allocate_all(
        self,
        session_id: Optional[str] = None,
    ) -> List[AllocationResult]:
        """Allocate roles for all online devices in UnifiedDeviceManager.

        Iterates over all registered devices, retrieves their capabilities and
        health scores, and calls :meth:`allocate` for each.

        Args:
            session_id:  Optional session filter for body assignments.

        Returns:
            List of :class:`AllocationResult` for every processed device.
        """
        results: List[AllocationResult] = []
        try:
            from core.unified.device_manager import UnifiedDeviceManager
            udm = UnifiedDeviceManager()
            devices = udm.list_devices()
        except Exception as exc:
            logger.warning("DeviceRoleAllocator.allocate_all: cannot reach UDM — %s", exc)
            return results

        try:
            from core.unified.device_health import DeviceHealthScorer
            scorer = DeviceHealthScorer()
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            scorer = None

        for device in devices:
            health = 1.0
            if scorer is not None:
                try:
                    health = scorer.score(device.device_id).total_score
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)

            result = self.allocate(
                device_id=device.device_id,
                capabilities=list(device.capabilities),
                health_score=health,
                session_id=session_id,
                extra_metadata={"device_type": device.device_type},
            )
            results.append(result)

        return results


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_allocator: Optional[DeviceRoleAllocator] = None
_allocator_lock = threading.Lock()


def get_device_role_allocator() -> DeviceRoleAllocator:
    """Return (or lazily create) the process-level :class:`DeviceRoleAllocator`."""
    global _allocator
    with _allocator_lock:
        if _allocator is None:
            _allocator = DeviceRoleAllocator()
    return _allocator


def reset_device_role_allocator() -> None:
    """Reset the singleton (intended for tests only)."""
    global _allocator
    with _allocator_lock:
        _allocator = None
