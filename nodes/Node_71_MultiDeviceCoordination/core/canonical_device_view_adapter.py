"""
Node 71 - Canonical Device View Adapter
========================================
Normalisation layer between canonical projected device views
(``contracts.registered_runtime_device.RegisteredRuntimeDevice``) and the
Node_71 internal coordination ``Device`` model.

Architecture position
---------------------
Node_71 is an **orchestration / coordination consumer**.  It must not act as a
peer canonical registration authority.  Device identity and canonical state
ownership live exclusively in ``UnifiedDeviceManager`` (UDM).  The contract
surface for individual devices is ``RegisteredRuntimeDevice`` (PR-5).

This adapter provides the bridge so that Node_71 can:

1. Accept canonical projected device views as its **sole device intake model**.
2. Build a local ``CoordinationDeviceView`` from those projections for
   task-scheduling and group-management purposes.
3. Preserve a clear separation between *canonical read* (``RegisteredRuntimeDevice``)
   and *coordination-local runtime state* (``CoordinationDeviceView``).

Usage::

    from core.canonical_device_view_adapter import (
        CoordinationDeviceView,
        CoordinationDeviceStatus,
        adapt_registered_runtime_device,
        adapt_registered_runtime_device_dict,
    )

    # From a canonical projected view
    rrd = build_registered_runtime_device(device_id="phone_001", ...)
    view = adapt_registered_runtime_device(rrd)

    # From a dict representation of a RegisteredRuntimeDevice
    view = adapt_registered_runtime_device_dict(rrd.to_dict())
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class CoordinationDeviceStatus(str, Enum):
    """Local coordination-layer device status.

    This enum represents the device's **coordination-visible** state as
    observed by Node_71's scheduler / grouping / task-dispatch runtime.
    It is derived from the canonical ``RuntimeDeviceStatus`` (from
    ``contracts.registered_runtime_device``) and must not be written back
    to UDM or treated as the canonical device state.
    """

    AVAILABLE = "available"    # online and eligible for new tasks
    BUSY = "busy"              # online but currently executing a task
    UNAVAILABLE = "unavailable"  # offline or in error — not schedulable


@dataclass
class CoordinationDeviceView:
    """Local coordination view of a single device.

    This is the **Node_71-internal** representation of a device.  It is
    populated from canonical ``RegisteredRuntimeDevice`` projections and
    enriched with coordination-local runtime state (current task, group
    membership, liveness for scheduling).

    **Authority boundary:**
    - This class carries *coordination-local* state only.
    - It does NOT represent canonical device truth.
    - Writes to fields here (e.g. ``coordination_status``, ``current_task_id``)
      are scoped to Node_71's coordination runtime and must never be
      propagated back to UDM as canonical state mutations.

    Fields
    ------
    device_id: str
        Canonical stable device identifier (read from ``RegisteredRuntimeDevice``).
    device_name: str
        Human-readable name (read from canonical projection, not locally authoritative).
    device_type: str
        Device type string (read from canonical projection).
    capabilities: List[str]
        Capability names from the canonical projection.
    coordination_status: CoordinationDeviceStatus
        Coordination-local status for scheduling decisions.
    current_task_id: Optional[str]
        Coordination-local: ID of the task currently assigned by Node_71.
    assigned_task_ids: List[str]
        Coordination-local: IDs of tasks assigned to this device.
    group_ids: List[str]
        Coordination-local: device-group memberships within Node_71.
    ingested_at: float
        Unix timestamp when this view was last populated from a canonical
        projection.
    canonical_status: str
        The status string as read from the canonical projection (preserved for
        diagnostics; not used for write-back).
    metadata: Dict[str, Any]
        Passthrough from the canonical projection's metadata field.
    """

    # -- Canonical projection fields (read-only, sourced from RRD) --
    device_id: str
    device_name: str = ""
    device_type: str = ""
    capabilities: List[str] = field(default_factory=list)
    canonical_status: str = "offline"
    metadata: Dict[str, Any] = field(default_factory=dict)

    # -- Coordination-local runtime state --
    coordination_status: CoordinationDeviceStatus = CoordinationDeviceStatus.UNAVAILABLE
    current_task_id: Optional[str] = None
    assigned_task_ids: List[str] = field(default_factory=list)
    group_ids: List[str] = field(default_factory=list)
    ingested_at: float = field(default_factory=time.time)

    # ------------------------------------------------------------------ #
    # Coordination helpers                                                 #
    # ------------------------------------------------------------------ #

    def is_available_for_task(self) -> bool:
        """Return True if this device can accept a new coordination task."""
        return self.coordination_status == CoordinationDeviceStatus.AVAILABLE

    def mark_task_assigned(self, task_id: str) -> None:
        """Record a coordination-local task assignment.

        Sets ``coordination_status`` to BUSY and records the task ID.
        This is a local coordination state change — it must not be written
        back to UDM as a canonical status mutation.
        """
        self.current_task_id = task_id
        if task_id not in self.assigned_task_ids:
            self.assigned_task_ids.append(task_id)
        self.coordination_status = CoordinationDeviceStatus.BUSY

    def mark_task_released(self, task_id: str) -> None:
        """Record that a task has been released from this device.

        Restores ``coordination_status`` to AVAILABLE if the canonical
        projection indicates the device is online.
        """
        if self.current_task_id == task_id:
            self.current_task_id = None
        if task_id in self.assigned_task_ids:
            self.assigned_task_ids.remove(task_id)
        if self.canonical_status in ("online", "idle"):
            self.coordination_status = CoordinationDeviceStatus.AVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        """Return a dict representation of this coordination view."""
        return {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "device_type": self.device_type,
            "capabilities": list(self.capabilities),
            "canonical_status": self.canonical_status,
            "coordination_status": self.coordination_status.value,
            "current_task_id": self.current_task_id,
            "assigned_task_ids": list(self.assigned_task_ids),
            "group_ids": list(self.group_ids),
            "ingested_at": self.ingested_at,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Status mapping helpers
# ---------------------------------------------------------------------------

_CANONICAL_STATUS_TO_COORDINATION: Dict[str, CoordinationDeviceStatus] = {
    "online": CoordinationDeviceStatus.AVAILABLE,
    "idle": CoordinationDeviceStatus.AVAILABLE,
    "busy": CoordinationDeviceStatus.BUSY,
    "offline": CoordinationDeviceStatus.UNAVAILABLE,
    "error": CoordinationDeviceStatus.UNAVAILABLE,
    "maintenance": CoordinationDeviceStatus.UNAVAILABLE,
    "unknown": CoordinationDeviceStatus.UNAVAILABLE,
}


def _map_canonical_status(canonical_status: str) -> CoordinationDeviceStatus:
    """Map a canonical ``RuntimeDeviceStatus`` string to a ``CoordinationDeviceStatus``."""
    return _CANONICAL_STATUS_TO_COORDINATION.get(
        str(canonical_status).lower(),
        CoordinationDeviceStatus.UNAVAILABLE,
    )


def _extract_capability_names(capabilities_obj: Any) -> List[str]:
    """Extract a flat list of capability name strings from a canonical capabilities value.

    Handles:
    - ``RuntimeCapabilityProfile`` Pydantic model (has ``.names`` list)
    - list of strings
    - list of dicts with ``"name"`` key
    - None / empty
    """
    if capabilities_obj is None:
        return []

    # RuntimeCapabilityProfile or similar: has a .names attribute
    if hasattr(capabilities_obj, "names"):
        return list(capabilities_obj.names or [])

    # Already a list
    if isinstance(capabilities_obj, list):
        result = []
        for item in capabilities_obj:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict):
                name = item.get("name", "")
                if name:
                    result.append(name)
        return result

    # Dict representation from to_dict() — look for "names" key
    if isinstance(capabilities_obj, dict):
        names = capabilities_obj.get("names", [])
        if isinstance(names, list):
            return [n for n in names if isinstance(n, str)]

    return []


# ---------------------------------------------------------------------------
# Primary adapter functions
# ---------------------------------------------------------------------------


def adapt_registered_runtime_device(rrd: Any) -> CoordinationDeviceView:
    """Build a :class:`CoordinationDeviceView` from a canonical
    :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice` projection.

    This is the **primary device intake path** for Node_71.  All devices
    entering the coordination runtime should be admitted through this function
    rather than through ad-hoc local ``Device`` construction.

    Parameters
    ----------
    rrd:
        A ``contracts.registered_runtime_device.RegisteredRuntimeDevice``
        instance (or any object with compatible field shape).

    Returns
    -------
    CoordinationDeviceView
        A coordination-local view populated from the canonical projection.
        The ``ingested_at`` timestamp is set to the current time.

    Raises
    ------
    ValueError
        If *rrd* does not carry a non-empty ``device_id``.
    """
    device_id = getattr(rrd, "device_id", None)
    if not device_id:
        raise ValueError(
            "adapt_registered_runtime_device: canonical projection must carry a non-empty device_id"
        )

    raw_status = getattr(rrd, "status", "offline")
    canonical_status_str = str(raw_status).lower()

    capabilities_obj = getattr(rrd, "capabilities", None)
    capability_names = _extract_capability_names(capabilities_obj)

    device_name = getattr(rrd, "device_name", "") or ""
    device_type = getattr(rrd, "device_type", "") or ""

    raw_metadata = getattr(rrd, "metadata", {})
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}

    return CoordinationDeviceView(
        device_id=str(device_id),
        device_name=str(device_name),
        device_type=str(device_type),
        capabilities=capability_names,
        canonical_status=canonical_status_str,
        coordination_status=_map_canonical_status(canonical_status_str),
        metadata=metadata,
        ingested_at=time.time(),
    )


def adapt_registered_runtime_device_dict(data: Dict[str, Any]) -> CoordinationDeviceView:
    """Build a :class:`CoordinationDeviceView` from a dict representation of a
    canonical ``RegisteredRuntimeDevice`` projection.

    This is a convenience wrapper for callers that receive serialised
    projection payloads (e.g. from an API response or message queue).

    Parameters
    ----------
    data:
        A dict as produced by ``RegisteredRuntimeDevice.to_dict()`` /
        ``RegisteredRuntimeDevice.model_dump()``.

    Returns
    -------
    CoordinationDeviceView
    """
    device_id = data.get("device_id", "")
    if not device_id:
        raise ValueError(
            "adapt_registered_runtime_device_dict: dict must carry a non-empty device_id"
        )

    raw_status = data.get("status", "offline")
    canonical_status_str = str(raw_status).lower()

    capabilities_obj = data.get("capabilities", {})
    capability_names = _extract_capability_names(capabilities_obj)

    device_name = data.get("device_name", "") or ""
    device_type = data.get("device_type", "") or ""
    raw_metadata = data.get("metadata", {})
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}

    return CoordinationDeviceView(
        device_id=str(device_id),
        device_name=str(device_name),
        device_type=str(device_type),
        capabilities=capability_names,
        canonical_status=canonical_status_str,
        coordination_status=_map_canonical_status(canonical_status_str),
        metadata=metadata,
        ingested_at=time.time(),
    )


def refresh_coordination_view(
    existing_view: CoordinationDeviceView,
    updated_rrd: Any,
) -> CoordinationDeviceView:
    """Refresh the canonical-projection fields of an existing
    :class:`CoordinationDeviceView` from an updated
    ``RegisteredRuntimeDevice``.

    Coordination-local state (``current_task_id``, ``assigned_task_ids``,
    ``group_ids``, ``coordination_status`` if BUSY) is preserved so that
    an in-progress task assignment is not lost on a routine refresh.

    Parameters
    ----------
    existing_view:
        The view held in Node_71's local coordination store.
    updated_rrd:
        The refreshed canonical projection.

    Returns
    -------
    CoordinationDeviceView
        Updated view with canonical fields refreshed and coordination-local
        state preserved.
    """
    new_view = adapt_registered_runtime_device(updated_rrd)
    new_view.current_task_id = existing_view.current_task_id
    new_view.assigned_task_ids = list(existing_view.assigned_task_ids)
    new_view.group_ids = list(existing_view.group_ids)
    # Preserve BUSY status if there is an active task assignment
    if existing_view.current_task_id is not None:
        new_view.coordination_status = CoordinationDeviceStatus.BUSY
    return new_view
