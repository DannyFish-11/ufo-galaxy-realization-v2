"""contracts/canonical_device_identity.py
==========================================
Canonical Device Identity Contract — PR-56.

This module defines :class:`CanonicalDeviceIdentity`: the **pure identity
contract** for a Galaxy runtime device.

Design principle: identity is separate from presence
-----------------------------------------------------
:class:`CanonicalDeviceIdentity` captures *what the device is* — its stable
identifier, platform, capabilities, autonomy posture, and owner metadata.
It intentionally carries **no transport references, no WebSocket objects, no
connection state, and no session-scoped task pointers**.  Those concerns
belong to :class:`~contracts.runtime_presence_record.RuntimePresenceRecord`.

Relationship to :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`
--------------------------------------------------------------------------------------
``RegisteredRuntimeDevice`` (PR-5 / PR-29) remains the **sole canonical
external single-device read contract**.  ``CanonicalDeviceIdentity`` is a
*narrower, presence-free projection* of that contract, suitable for

* device-eligibility evaluation (can this device run task X?)
* capability-driven routing and scheduling
* cross-device formation and group membership decisions
* identity authority services that must remain free of ephemeral state

Adapters
--------
* :func:`from_registered_runtime_device` — from a ``RegisteredRuntimeDevice``
* :func:`from_android_registration` — from a raw Android registration dict
* :func:`build_canonical_device_identity` — generic keyword-argument builder

Usage::

    from contracts.canonical_device_identity import (
        CanonicalDeviceIdentity,
        build_canonical_device_identity,
        from_registered_runtime_device,
        from_android_registration,
    )

    identity = build_canonical_device_identity(
        device_id="phone_001",
        platform="android",
        capabilities=["screen", "camera"],
        supports_local_autonomy=True,
    )
    payload = identity.to_dict()

See ``docs/CANONICAL_DEVICE_IDENTITY_CONTRACT.md`` for the full specification.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Canonical Device Identity contract
# ---------------------------------------------------------------------------


class CanonicalDeviceIdentity(BaseModel):
    """Pure device identity contract — no transport or session references.

    This contract answers *"what is this device and what can it do?"* without
    carrying any ephemeral presence or connection state.

    Required fields
    ---------------
    ``device_id`` — must be a non-empty string.

    All other fields have sensible defaults and are optional so that partial
    construction from legacy sources remains convenient.
    """

    # ── Stable identity ─────────────────────────────────────────────────────
    device_id: str = Field(
        description="Globally stable identifier for this device.",
    )
    device_name: str = Field(
        default="",
        description="Human-readable device name.",
    )
    owner_id: str = Field(
        default="",
        description="Identifier of the owner account or principal.",
    )

    # ── Classification ───────────────────────────────────────────────────────
    platform: str = Field(
        default="unknown",
        description=(
            "Operating-system / platform family: 'android', 'ios', "
            "'windows', 'linux', 'macos', 'cloud', 'embedded', 'unknown'."
        ),
    )
    device_type: str = Field(
        default="",
        description=(
            "Fine-grained device type, e.g. 'android_phone', "
            "'windows_desktop', 'cloud_aws'."
        ),
    )
    form_factor: str = Field(
        default="",
        description="Physical form factor: 'phone', 'tablet', 'desktop', etc.",
    )

    # ── Capability profile ───────────────────────────────────────────────────
    capabilities: List[str] = Field(
        default_factory=list,
        description="List of named capabilities this device supports.",
    )
    supported_actions: List[str] = Field(
        default_factory=list,
        description="Canonical action names this device can execute.",
    )
    capability_schemas: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional JSON schema fragments describing individual capability "
            "parameter contracts, keyed by capability name."
        ),
    )

    # ── Autonomy posture ────────────────────────────────────────────────────
    supports_local_autonomy: bool = Field(
        default=False,
        description="True when the device can execute tasks using local inference.",
    )
    supports_remote_handoff: bool = Field(
        default=False,
        description="True when the device can receive a cross-device handoff.",
    )

    # ── Membership / grouping hints ─────────────────────────────────────────
    groups: List[str] = Field(
        default_factory=list,
        description="Group or formation labels this device participates in.",
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Arbitrary searchable tags attached to this device.",
    )

    # ── Open metadata ────────────────────────────────────────────────────────
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arbitrary extension fields.  Must not carry transport objects, "
            "WebSocket references, or session-scoped state."
        ),
    )

    model_config = {"populate_by_name": True}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def has_capability(self, cap: str) -> bool:
        """Return ``True`` if *cap* is in :attr:`capabilities`."""
        return cap in self.capabilities

    def supports_action(self, action: str) -> bool:
        """Return ``True`` if *action* is in :attr:`supported_actions`."""
        return action in self.supported_actions

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return self.model_dump(mode="json")

    def to_json(self) -> str:
        """Return a compact JSON string representation."""
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CanonicalDeviceIdentity":
        """Construct from a plain dict (e.g. after JSON deserialisation)."""
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Adapter: from RegisteredRuntimeDevice (PR-29)
# ---------------------------------------------------------------------------


def from_registered_runtime_device(device: Any) -> CanonicalDeviceIdentity:
    """Build a :class:`CanonicalDeviceIdentity` from a
    :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`.

    This is the primary production adapter.  All fields that carry ephemeral
    presence or transport state are intentionally excluded.

    Parameters
    ----------
    device:
        A ``contracts.registered_runtime_device.RegisteredRuntimeDevice``
        instance (or any object with the same field shape).
    """
    try:
        device_id = str(getattr(device, "device_id", "") or "")
        if not device_id:
            device_id = f"dev_{uuid.uuid4().hex[:8]}"

        device_name = str(getattr(device, "device_name", "") or "")
        owner_id = str(getattr(device, "owner_id", "") or "")

        # platform / device_type / form_factor
        platform_raw = getattr(device, "platform", None)
        if platform_raw is None:
            platform = "unknown"
        elif hasattr(platform_raw, "value"):
            platform = str(platform_raw.value)
        else:
            platform = str(platform_raw)

        device_type_raw = getattr(device, "device_type", None)
        if device_type_raw is None:
            device_type = ""
        elif hasattr(device_type_raw, "value"):
            device_type = str(device_type_raw.value)
        else:
            device_type = str(device_type_raw)

        form_factor_raw = getattr(device, "form_factor", None)
        if form_factor_raw is None:
            form_factor = ""
        elif hasattr(form_factor_raw, "value"):
            form_factor = str(form_factor_raw.value)
        else:
            form_factor = str(form_factor_raw)

        # capabilities sub-object
        cap_obj = getattr(device, "capabilities", None)
        if cap_obj is None:
            capabilities: List[str] = []
            supported_actions: List[str] = []
            capability_schemas: Dict[str, Any] = {}
        elif isinstance(cap_obj, list):
            capabilities = [str(c) for c in cap_obj]
            supported_actions = []
            capability_schemas = {}
        else:
            raw_caps = getattr(cap_obj, "capabilities", None) or []
            capabilities = [str(c) for c in raw_caps]
            raw_actions = getattr(cap_obj, "supported_actions", None) or []
            supported_actions = [str(a) for a in raw_actions]
            cap_schemas = getattr(cap_obj, "capability_schemas", None) or {}
            capability_schemas = dict(cap_schemas) if isinstance(cap_schemas, dict) else {}

        # autonomy sub-object
        autonomy = getattr(device, "autonomy", None)
        supports_local_autonomy = False
        supports_remote_handoff = False
        if autonomy is not None:
            supports_local_autonomy = bool(getattr(autonomy, "supports_local_autonomy", False))
            supports_remote_handoff = bool(getattr(autonomy, "supports_remote_handoff", False))

        # participation hints
        hints = getattr(device, "participation_hints", None)
        groups: List[str] = []
        tags: List[str] = []
        if hints is not None:
            raw_groups = getattr(hints, "groups", None) or []
            groups = [str(g) for g in raw_groups]
            raw_tags = getattr(hints, "tags", None) or []
            tags = [str(t) for t in raw_tags]

        metadata = dict(getattr(device, "metadata", None) or {})

        return CanonicalDeviceIdentity(
            device_id=device_id,
            device_name=device_name,
            owner_id=owner_id,
            platform=platform,
            device_type=device_type,
            form_factor=form_factor,
            capabilities=capabilities,
            supported_actions=supported_actions,
            capability_schemas=capability_schemas,
            supports_local_autonomy=supports_local_autonomy,
            supports_remote_handoff=supports_remote_handoff,
            groups=groups,
            tags=tags,
            metadata=metadata,
        )
    except Exception:
        dev_id = str(getattr(device, "device_id", "") or f"dev_{uuid.uuid4().hex[:8]}")
        return CanonicalDeviceIdentity(device_id=dev_id)


# ---------------------------------------------------------------------------
# Adapter: from raw Android registration dict
# ---------------------------------------------------------------------------


def from_android_registration(data: Dict[str, Any]) -> CanonicalDeviceIdentity:
    """Build a :class:`CanonicalDeviceIdentity` from a raw Android
    ``device_register`` / ``registration`` AIP payload.

    Parameters
    ----------
    data:
        The ``payload`` dict from an Android AIP registration message, or any
        flat dict that contains at minimum a ``device_id`` key.
    """
    try:
        device_id = str(data.get("device_id", "") or "")
        if not device_id:
            device_id = f"dev_{uuid.uuid4().hex[:8]}"

        device_name = str(data.get("device_name", data.get("name", "")) or "")
        owner_id = str(data.get("owner_id", data.get("user_id", "")) or "")

        # platform detection
        platform = str(data.get("platform", data.get("os", "unknown")) or "unknown").lower()
        if not platform:
            platform = "unknown"
        device_type = str(data.get("device_type", data.get("type", "")) or "")
        form_factor = str(data.get("form_factor", "") or "")

        # capabilities
        raw_caps = data.get("capabilities", [])
        if isinstance(raw_caps, list):
            capabilities = [str(c) for c in raw_caps]
        elif isinstance(raw_caps, dict):
            capabilities = list(raw_caps.keys())
        else:
            capabilities = []

        supported_actions = [str(a) for a in data.get("supported_actions", [])]
        capability_schemas = data.get("capability_schemas", {})
        if not isinstance(capability_schemas, dict):
            capability_schemas = {}

        supports_local_autonomy = bool(data.get("supports_local_autonomy", False))
        supports_remote_handoff = bool(data.get("supports_remote_handoff", False))

        groups = [str(g) for g in data.get("groups", [])]
        tags = [str(t) for t in data.get("tags", [])]

        # Carry metadata keys that are not part of the canonical fields
        _known = {
            "device_id", "device_name", "name", "owner_id", "user_id",
            "platform", "os", "device_type", "type", "form_factor",
            "capabilities", "supported_actions", "capability_schemas",
            "supports_local_autonomy", "supports_remote_handoff",
            "groups", "tags",
        }
        metadata = {k: v for k, v in data.items() if k not in _known}

        return CanonicalDeviceIdentity(
            device_id=device_id,
            device_name=device_name,
            owner_id=owner_id,
            platform=platform,
            device_type=device_type,
            form_factor=form_factor,
            capabilities=capabilities,
            supported_actions=supported_actions,
            capability_schemas=capability_schemas,
            supports_local_autonomy=supports_local_autonomy,
            supports_remote_handoff=supports_remote_handoff,
            groups=groups,
            tags=tags,
            metadata=metadata,
        )
    except Exception:
        dev_id = str(data.get("device_id", "") or f"dev_{uuid.uuid4().hex[:8]}")
        return CanonicalDeviceIdentity(device_id=dev_id)


# ---------------------------------------------------------------------------
# Generic builder
# ---------------------------------------------------------------------------


def build_canonical_device_identity(
    *,
    device_id: str,
    device_name: str = "",
    owner_id: str = "",
    platform: str = "unknown",
    device_type: str = "",
    form_factor: str = "",
    capabilities: Optional[List[str]] = None,
    supported_actions: Optional[List[str]] = None,
    capability_schemas: Optional[Dict[str, Any]] = None,
    supports_local_autonomy: bool = False,
    supports_remote_handoff: bool = False,
    groups: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> CanonicalDeviceIdentity:
    """Build a :class:`CanonicalDeviceIdentity` from keyword arguments.

    This is the preferred way to construct a contract when source data is
    already decomposed into individual fields (e.g. from a DB record or an
    API request body).
    """
    return CanonicalDeviceIdentity(
        device_id=device_id,
        device_name=device_name,
        owner_id=owner_id,
        platform=platform,
        device_type=device_type,
        form_factor=form_factor,
        capabilities=list(capabilities or []),
        supported_actions=list(supported_actions or []),
        capability_schemas=dict(capability_schemas or {}),
        supports_local_autonomy=supports_local_autonomy,
        supports_remote_handoff=supports_remote_handoff,
        groups=list(groups or []),
        tags=list(tags or []),
        metadata=dict(metadata or {}),
    )
