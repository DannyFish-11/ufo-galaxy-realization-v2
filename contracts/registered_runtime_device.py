"""contracts/registered_runtime_device.py
==========================================
Registered Runtime Device Contract — PR-5 (canonical) / PR-29 (introduced).

**Canonical position (PR-5):**
``RegisteredRuntimeDevice`` is the **sole canonical external single-device
read contract** for the Galaxy / OpenClawd system.  Every consumer that needs
the state of a single device — whether for APIs, orchestration, governance, or
future UI surfaces — must project into or read from this contract.

No parallel single-device external schema should be created.  The authority
chain is:

    UnifiedDeviceManager (write SSOT)
      └── all registration paths converge here
    ──────────────────────────────────────────
    RegisteredRuntimeDevice              ← sole canonical single-device read
      (this module)                         contract  (PR-5 / PR-29)
    ──────────────────────────────────────────
    MultiDeviceRuntimeProjection         ← canonical top-level multi-device
      (contracts/multi_device_runtime_projection.py)  read projection

Source projections
------------------
All major device sources provide a stable adapter into this contract:

- :func:`from_udm_device` — from ``core.unified.models.UnifiedDevice`` (UDM SSOT)
- :func:`from_router_device` — from ``galaxy_gateway.device_router.Device``
- :func:`from_android_registration` — from ``galaxy_gateway.android_bridge`` payloads
- :func:`from_device_registry_record` — from ``core.schemas.device.DeviceModel``
- :func:`from_device_agent_manager_record` — from ``core.device_agent_manager.DeviceInfo``
- :func:`build_registered_runtime_device` — generic keyword-argument builder

Information domains
-------------------
The contract covers the six canonical single-device information domains:

1. **identity** — ``device_id``, ``device_name``, ``owner_id``
2. **registration** — ``platform``, ``form_factor``, ``device_type``
3. **runtime presence** — ``status``, ``online``, ``last_seen``,
   ``connection`` (:class:`RuntimeConnectionSummary`)
4. **capability** — ``capabilities`` (:class:`RuntimeCapabilityProfile`)
5. **participation** — ``participation_hints``
   (:class:`RuntimeParticipationHints`),
   ``session_presence`` (:class:`RuntimeSessionPresence`)
6. **topology / runtime hints** — ``autonomy`` (:class:`RuntimeAutonomySummary`)

Design principles
-----------------
- **Sole canonical external view** — downstream consumers must not build
  parallel single-device schemas.
- **Fully serialisable** — :meth:`RegisteredRuntimeDevice.to_dict` and
  :meth:`RegisteredRuntimeDevice.to_json` produce stable, round-trippable JSON.
- **Graceful defaults** — all fields beyond the minimal required set are
  optional.  Adapters catch exceptions and degrade gracefully.
- **No UI-specific semantics** — suitable for runtime/projection/API use.
- **Stable field names** — downstream consumers can rely on the field names
  defined here without fear of silent renaming.

Usage::

    from contracts.registered_runtime_device import (
        RegisteredRuntimeDevice,
        RuntimeConnectionSummary,
        RuntimeCapabilityProfile,
        RuntimeAutonomySummary,
        RuntimeSessionPresence,
        RuntimeParticipationHints,
        RuntimeDeviceStatus,
        from_udm_device,
        from_router_device,
        from_android_registration,
        from_device_registry_record,
        from_device_agent_manager_record,
        build_registered_runtime_device,
    )

    # Build from a UnifiedDevice (UDM SSOT)
    contract = from_udm_device(unified_device)
    payload   = contract.to_dict()

    # Build from a DeviceAgentManager DeviceInfo record
    contract = from_device_agent_manager_record(device_info)

    # Build from a raw registration dict
    contract = build_registered_runtime_device(
        device_id="phone_001",
        device_name="My Phone",
        platform="android",
        capabilities=["screen", "camera"],
    )

See ``docs/REGISTERED_RUNTIME_DEVICE_CONTRACT.md`` for the full specification.
"""

from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RuntimeDevicePlatform(str, Enum):
    """High-level platform family for a registered runtime device.

    Maps to ``core.device_types.DeviceType`` values.  Kept as a separate
    enum so that the contract layer remains independent of internal enums.
    """

    ANDROID = "android"
    IOS = "ios"
    WINDOWS = "windows"
    MACOS = "macos"
    LINUX = "linux"
    BROWSER = "browser"
    CLOUD = "cloud"
    IOT = "iot"
    ROBOT = "robot"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "RuntimeDevicePlatform":
        """Return a :class:`RuntimeDevicePlatform` from a raw string, defaulting to
        :attr:`UNKNOWN` on unrecognised values.
        """
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.UNKNOWN


class RuntimeDeviceFormFactor(str, Enum):
    """Physical form-factor classification for a runtime device."""

    PHONE = "phone"
    TABLET = "tablet"
    DESKTOP = "desktop"
    LAPTOP = "laptop"
    WATCH = "watch"
    TV = "tv"
    HEADSET = "headset"
    EMBEDDED = "embedded"
    SERVER = "server"
    VIRTUAL = "virtual"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "RuntimeDeviceFormFactor":
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.UNKNOWN


class RuntimeDeviceStatus(str, Enum):
    """Operational status of a registered runtime device.

    Maps to ``core.device_types.DeviceStatus`` / ``core.unified.models.UnifiedDeviceStatus``.
    """

    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    ERROR = "error"
    INITIALIZING = "initializing"
    DISCONNECTED = "disconnected"

    @classmethod
    def from_string(cls, value: str) -> "RuntimeDeviceStatus":
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.OFFLINE


class RuntimeConnectionState(str, Enum):
    """Low-level connection state for a runtime device's active transport."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"

    @classmethod
    def from_string(cls, value: str) -> "RuntimeConnectionState":
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.DISCONNECTED


# ---------------------------------------------------------------------------
# Sub-contract models
# ---------------------------------------------------------------------------


class RuntimeConnectionSummary(BaseModel):
    """Summary of the device's current connection to the runtime fabric.

    This covers transport-level presence (WebSocket connected / disconnected)
    rather than logical online/offline status.
    """

    state: RuntimeConnectionState = Field(
        default=RuntimeConnectionState.DISCONNECTED,
        description="Current transport connection state.",
    )
    transport: str = Field(
        default="",
        description="Transport mechanism in use, e.g. 'websocket', 'http', 'nats'.",
    )
    endpoint: str = Field(
        default="",
        description="Connection endpoint URL or address.",
    )
    ip_address: str = Field(default="", description="Remote IP address.")
    port: int = Field(default=0, ge=0, le=65535, description="Remote port.")
    connected_at: Optional[float] = Field(
        default=None,
        description="Unix timestamp when the current connection was established.",
    )
    reconnect_count: int = Field(
        default=0,
        ge=0,
        description="Number of reconnection attempts in the current session.",
    )

    model_config = {"use_enum_values": True}

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class RuntimeCapabilityProfile(BaseModel):
    """Declared capability surface of a runtime device.

    Capability entries are stored as simple strings (e.g. ``"screen"``,
    ``"camera"``) so that the contract remains stable across capability-system
    changes.  Rich capability metadata can be carried in
    :attr:`RegisteredRuntimeDevice.metadata` when needed.
    """

    capabilities: List[str] = Field(
        default_factory=list,
        description="List of capability names declared by the device.",
    )
    capability_flags: int = Field(
        default=0,
        ge=0,
        description=(
            "Optional bitmask encoding capabilities (Android-bridge convention). "
            "0 means not set or not applicable."
        ),
    )
    supported_actions: List[str] = Field(
        default_factory=list,
        description="List of discrete action verbs the device can execute (e.g. 'click', 'swipe').",
    )

    model_config = {"use_enum_values": True}

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class RuntimeAutonomySummary(BaseModel):
    """Summary of the device's local-autonomy and remote-handoff readiness.

    These fields capture *intent/support* rather than live activation state.
    The actual runtime-host contract (PR-30) will carry the live state.
    """

    supports_local_autonomy: bool = Field(
        default=False,
        description=(
            "Whether the device has a local runtime capable of autonomous "
            "task execution without constant server involvement."
        ),
    )
    supports_remote_handoff: bool = Field(
        default=False,
        description=(
            "Whether the device can participate in cross-device handoff as "
            "either source or target."
        ),
    )
    runtime_enabled: bool = Field(
        default=False,
        description=(
            "Whether the Galaxy/OpenClawd runtime is currently activated "
            "on this device."
        ),
    )
    runtime_id: Optional[str] = Field(
        default=None,
        description="Identifier of the local runtime instance, if active.",
    )
    runtime_version: Optional[str] = Field(
        default=None,
        description="Version string of the device-side runtime client.",
    )

    model_config = {"use_enum_values": True}

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class RuntimeSessionPresence(BaseModel):
    """References to active sessions this device is participating in.

    This is intentionally lightweight — it does not carry full session
    objects, only stable IDs.  The Mesh Session contract (PR-33) will
    define the full session graph.
    """

    active_session_ids: List[str] = Field(
        default_factory=list,
        description="IDs of runtime sessions this device is currently active in.",
    )
    current_task_id: Optional[str] = Field(
        default=None,
        description="ID of the task currently being executed on this device, if any.",
    )
    pending_task_ids: List[str] = Field(
        default_factory=list,
        description="IDs of tasks queued on this device.",
    )

    model_config = {"use_enum_values": True}

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class RuntimeParticipationHints(BaseModel):
    """Lightweight hints about the device's expected participation roles.

    These are *hints* derived from available metadata.  The full Mesh
    Membership contract (PR-32) will define binding role assignments.
    """

    body_mesh_roles: List[str] = Field(
        default_factory=list,
        description=(
            "Body-mesh roles this device has been assigned or is capable of "
            "(e.g. 'perception', 'action', 'presence').  Sourced from "
            "core.mesh.body_mesh_registry when available."
        ),
    )
    is_primary_body: bool = Field(
        default=False,
        description=(
            "Whether this device is currently acting as the primary body "
            "in its mesh session."
        ),
    )
    groups: List[str] = Field(
        default_factory=list,
        description="Device groups this device belongs to.",
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Freeform classification tags.",
    )

    model_config = {"use_enum_values": True}

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ---------------------------------------------------------------------------
# Top-level canonical contract
# ---------------------------------------------------------------------------


class RegisteredRuntimeDevice(BaseModel):
    """Sole canonical external single-device read contract (PR-5).

    This is the single authoritative answer to:
    *"What is a runtime-capable device in the Galaxy/OpenClawd system?"*

    All device-surface views — device registry, gateway router, Android bridge,
    UDM, device agent manager — must normalise into this contract before being
    consumed by runtime, projection, governance, or API layers.  No parallel
    single-device external schema should be created outside this module.

    The contract covers six canonical information domains:
    1. **identity** — ``device_id``, ``device_name``, ``owner_id``
    2. **registration** — ``platform``, ``form_factor``, ``device_type``
    3. **runtime presence** — ``status``, ``online``, ``last_seen``, ``connection``
    4. **capability** — ``capabilities``
    5. **participation** — ``participation_hints``, ``session_presence``
    6. **topology / runtime hints** — ``autonomy``

    Required fields
    ---------------
    :attr:`device_id` — the only truly required field; all others default.

    Serialisation
    -------------
    :meth:`to_dict` and :meth:`to_json` produce stable, round-trippable
    representations.  The :meth:`from_dict` class method reconstructs the
    contract from such a dict.
    """

    # -- Identity --
    device_id: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Stable unique identifier for this device.",
    )
    device_name: str = Field(
        default="",
        description="Human-readable display name.",
    )
    owner_id: Optional[str] = Field(
        default=None,
        description="Identifier of the owner / user account, if known.",
    )

    # -- Classification --
    platform: RuntimeDevicePlatform = Field(
        default=RuntimeDevicePlatform.UNKNOWN,
        description="High-level platform family.",
    )
    form_factor: RuntimeDeviceFormFactor = Field(
        default=RuntimeDeviceFormFactor.UNKNOWN,
        description="Physical form-factor classification.",
    )
    device_type: str = Field(
        default="",
        description=(
            "Fine-grained device type string (e.g. 'android_phone', "
            "'windows_desktop').  Corresponds to AIPDeviceType values."
        ),
    )

    # -- Status --
    status: RuntimeDeviceStatus = Field(
        default=RuntimeDeviceStatus.OFFLINE,
        description="Operational status.",
    )
    online: bool = Field(
        default=False,
        description="Convenience flag: True when status is ONLINE or BUSY.",
    )
    last_seen: Optional[float] = Field(
        default=None,
        description="Unix timestamp of last observed activity.",
    )

    # -- Sub-contracts --
    connection: RuntimeConnectionSummary = Field(
        default_factory=RuntimeConnectionSummary,
        description="Transport-level connection summary.",
    )
    capabilities: RuntimeCapabilityProfile = Field(
        default_factory=RuntimeCapabilityProfile,
        description="Declared capability surface.",
    )
    autonomy: RuntimeAutonomySummary = Field(
        default_factory=RuntimeAutonomySummary,
        description="Local-autonomy and remote-handoff readiness.",
    )
    session_presence: RuntimeSessionPresence = Field(
        default_factory=RuntimeSessionPresence,
        description="Active session and task references.",
    )
    participation_hints: RuntimeParticipationHints = Field(
        default_factory=RuntimeParticipationHints,
        description="Lightweight mesh participation hints.",
    )

    # -- Runtime-host identity (PR-5 / post-533 dual-repo unification) --
    source_runtime_posture: str = Field(
        default="control_only",
        description=(
            "Source-device runtime participation posture as established by PR-533. "
            "Canonical values: 'control_only' (device only controls/observes), "
            "'join_runtime' (device joins as a first-class runtime host). "
            "Defaults to 'control_only' for safety.  Populated from the "
            "registration payload when available."
        ),
    )
    is_runtime_host: bool = Field(
        default=False,
        description=(
            "Whether this device is classified as a first-class runtime host "
            "(PR-5).  True when the device's autonomy posture and "
            "source_runtime_posture indicate it can host autonomous local "
            "execution, not merely act as a connected control surface.  "
            "Distinct from 'runtime_enabled' which captures whether the "
            "runtime is currently activated; is_runtime_host captures the "
            "structural role classification."
        ),
    )

    # -- Open metadata --
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extension fields. Should not carry UI-specific data.",
    )

    model_config = {"use_enum_values": True}

    # ------------------------------------------------------------------
    # Computed helpers
    # ------------------------------------------------------------------

    def is_online(self) -> bool:
        """Return ``True`` if the device is in an active operational state."""
        return self.status in (
            RuntimeDeviceStatus.ONLINE,
            RuntimeDeviceStatus.ONLINE.value,
            RuntimeDeviceStatus.BUSY,
            RuntimeDeviceStatus.BUSY.value,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string.  Extra *kwargs* are forwarded to
        :func:`json.dumps`."""
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegisteredRuntimeDevice":
        """Construct a :class:`RegisteredRuntimeDevice` from a serialised dict."""
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Adapter / builder functions
# ---------------------------------------------------------------------------


def from_udm_device(device: Any) -> RegisteredRuntimeDevice:
    """Build a :class:`RegisteredRuntimeDevice` from a
    :class:`~core.unified.models.UnifiedDevice` (UDM SSOT).

    Parameters
    ----------
    device:
        A ``core.unified.models.UnifiedDevice`` instance (or any object with
        the same field shape).

    Returns
    -------
    RegisteredRuntimeDevice
        The normalised canonical contract.  Fields that cannot be mapped
        are left at their defaults.
    """
    try:
        device_id: str = str(getattr(device, "device_id", "") or "")
        if not device_id:
            device_id = f"dev_{uuid.uuid4().hex[:8]}"

        # Status
        raw_status = str(getattr(device, "status", "offline"))
        status = RuntimeDeviceStatus.from_string(raw_status)
        online = status in (RuntimeDeviceStatus.ONLINE, RuntimeDeviceStatus.BUSY)

        # Platform from device_type
        raw_type = str(getattr(device, "device_type", "") or "")
        platform = RuntimeDevicePlatform.from_string(raw_type)

        # Capabilities — UDM stores them as List[str]
        raw_caps: List[str] = list(getattr(device, "capabilities", []) or [])

        # Last seen
        lh = getattr(device, "last_heartbeat", None)
        last_seen: Optional[float] = None
        if lh is not None:
            try:
                last_seen = lh.timestamp() if hasattr(lh, "timestamp") else float(lh)
            except Exception:
                pass

        meta: Dict[str, Any] = dict(getattr(device, "metadata", {}) or {})

        return RegisteredRuntimeDevice(
            device_id=device_id,
            device_name=str(getattr(device, "device_name", "") or ""),
            platform=platform,
            device_type=raw_type,
            status=status,
            online=online,
            last_seen=last_seen,
            capabilities=RuntimeCapabilityProfile(capabilities=raw_caps),
            autonomy=RuntimeAutonomySummary(runtime_enabled=online),
            metadata=meta,
        )
    except Exception:
        # Graceful degradation: return a minimal contract rather than raise.
        return RegisteredRuntimeDevice(
            device_id=str(getattr(device, "device_id", "") or f"dev_{uuid.uuid4().hex[:8]}"),
        )


def from_router_device(device: Any) -> RegisteredRuntimeDevice:
    """Build a :class:`RegisteredRuntimeDevice` from a
    ``galaxy_gateway.device_router.Device`` gateway wrapper.

    Parameters
    ----------
    device:
        A ``galaxy_gateway.device_router.Device`` instance.
    """
    try:
        device_id: str = str(getattr(device, "device_id", "") or "")
        if not device_id:
            device_id = f"dev_{uuid.uuid4().hex[:8]}"

        raw_type = str(getattr(device, "device_type", "") or "")
        platform = RuntimeDevicePlatform.from_string(raw_type)

        # Capabilities may be a list of strings or DeviceCapabilityModel objects
        raw_caps_obj = getattr(device, "capabilities", []) or []
        capabilities_str: List[str] = []
        for c in raw_caps_obj:
            if isinstance(c, str):
                capabilities_str.append(c)
            elif hasattr(c, "name"):
                capabilities_str.append(str(c.name))

        # Websocket connectivity hint
        ws = getattr(device, "websocket", None)
        conn_state = (
            RuntimeConnectionState.CONNECTED if ws is not None
            else RuntimeConnectionState.DISCONNECTED
        )

        meta: Dict[str, Any] = dict(getattr(device, "metadata", {}) or {})

        return RegisteredRuntimeDevice(
            device_id=device_id,
            device_name=str(getattr(device, "device_name", device_id) or device_id),
            platform=platform,
            device_type=raw_type,
            status=RuntimeDeviceStatus.ONLINE if ws is not None else RuntimeDeviceStatus.OFFLINE,
            online=ws is not None,
            connection=RuntimeConnectionSummary(state=conn_state),
            capabilities=RuntimeCapabilityProfile(capabilities=capabilities_str),
            autonomy=RuntimeAutonomySummary(runtime_enabled=ws is not None),
            metadata=meta,
        )
    except Exception:
        return RegisteredRuntimeDevice(
            device_id=str(getattr(device, "device_id", "") or f"dev_{uuid.uuid4().hex[:8]}"),
        )


def from_android_registration(data: Dict[str, Any]) -> RegisteredRuntimeDevice:
    """Build a :class:`RegisteredRuntimeDevice` from an Android registration
    message dict (as handled by ``galaxy_gateway.android_bridge``).

    Parameters
    ----------
    data:
        Raw registration payload from the Android client.  Expected keys
        include ``device_id``, ``name``, ``model``, ``os_version``,
        ``platform``, ``capabilities`` (int bitmask), etc.
    """
    try:
        device_id: str = str(data.get("device_id") or f"android_{uuid.uuid4().hex[:8]}")

        # Capability bitmask → string list via android_bridge helper
        cap_flags: int = 0
        raw_caps = data.get("capabilities", 0)
        if isinstance(raw_caps, int):
            cap_flags = raw_caps
            try:
                from galaxy_gateway.android_bridge import DeviceCapability as AndroidCapability
                caps_str = AndroidCapability.to_list(cap_flags)
            except Exception:
                caps_str = []
        elif isinstance(raw_caps, list):
            caps_str = [str(c) for c in raw_caps]
        else:
            caps_str = []

        meta: Dict[str, Any] = {
            "model": data.get("model", ""),
            "os_version": data.get("os_version", ""),
            "sdk_version": data.get("sdk_version"),
            "screen_width": data.get("screen_width"),
            "screen_height": data.get("screen_height"),
        }
        # Remove None values
        meta = {k: v for k, v in meta.items() if v is not None}

        # Resolve source_runtime_posture from payload (PR-5 / post-533).
        # Android devices joining as runtime hosts set 'join_runtime'; devices
        # that only remote-control use 'control_only'.  Unknown/missing values
        # fall back safely to 'control_only'.
        _raw_posture = str(data.get("source_runtime_posture", "") or "").strip().lower()
        if _raw_posture == "join_runtime":
            _posture = "join_runtime"
        else:
            _posture = "control_only"

        # Android is classified as a first-class runtime host when:
        # - it explicitly declares join_runtime posture, OR
        # - it declares app_version (Galaxy app installed) with remote handoff support
        _is_runtime_host: bool = (
            _posture == "join_runtime"
            or bool(str(data.get("app_version", "") or "").strip())
        )

        return RegisteredRuntimeDevice(
            device_id=device_id,
            device_name=str(data.get("name") or "Android Device"),
            platform=RuntimeDevicePlatform.ANDROID,
            form_factor=RuntimeDeviceFormFactor.PHONE,
            device_type=str(data.get("device_type", "android_phone")),
            status=RuntimeDeviceStatus.ONLINE,
            online=True,
            last_seen=time.time(),
            connection=RuntimeConnectionSummary(
                state=RuntimeConnectionState.CONNECTED,
                transport="websocket",
            ),
            capabilities=RuntimeCapabilityProfile(
                capabilities=caps_str,
                capability_flags=cap_flags,
            ),
            autonomy=RuntimeAutonomySummary(
                runtime_enabled=True,
                supports_remote_handoff=True,
                runtime_version=str(data.get("app_version", "") or ""),
            ),
            source_runtime_posture=_posture,
            is_runtime_host=_is_runtime_host,
            metadata=meta,
        )
    except Exception:
        return RegisteredRuntimeDevice(
            device_id=str(data.get("device_id") or f"android_{uuid.uuid4().hex[:8]}"),
            platform=RuntimeDevicePlatform.ANDROID,
            source_runtime_posture="control_only",
            is_runtime_host=False,
        )


def from_device_registry_record(device: Any) -> RegisteredRuntimeDevice:
    """Build a :class:`RegisteredRuntimeDevice` from a
    ``core.schemas.device.DeviceModel`` record (as stored in
    ``core.device_registry.DeviceRegistry``).

    Parameters
    ----------
    device:
        A ``core.schemas.device.DeviceModel`` instance.
    """
    try:
        device_id: str = str(getattr(device, "device_id", "") or "")
        if not device_id:
            device_id = f"dev_{uuid.uuid4().hex[:8]}"

        # device_type is a DeviceType enum or string
        raw_type_obj = getattr(device, "device_type", None)
        if raw_type_obj is None:
            raw_type = ""
        elif hasattr(raw_type_obj, "value"):
            raw_type = str(raw_type_obj.value)
        else:
            raw_type = str(raw_type_obj)

        platform = RuntimeDevicePlatform.from_string(raw_type)

        # Status
        raw_status_obj = getattr(device, "status", None)
        if raw_status_obj is None:
            raw_status = "offline"
        elif hasattr(raw_status_obj, "value"):
            raw_status = str(raw_status_obj.value)
        else:
            raw_status = str(raw_status_obj)
        status = RuntimeDeviceStatus.from_string(raw_status)
        online = status in (RuntimeDeviceStatus.ONLINE, RuntimeDeviceStatus.BUSY)

        # Capabilities — DeviceCapabilityModel list
        caps_raw = getattr(device, "capabilities", []) or []
        caps_str: List[str] = []
        for c in caps_raw:
            if isinstance(c, str):
                caps_str.append(c)
            elif hasattr(c, "name"):
                caps_str.append(str(c.name))

        last_seen: Optional[float] = getattr(device, "last_seen", None) or getattr(device, "last_heartbeat", None)
        if last_seen is not None and not isinstance(last_seen, float):
            try:
                last_seen = float(last_seen)
            except Exception:
                last_seen = None

        meta: Dict[str, Any] = dict(getattr(device, "metadata", {}) or {})

        groups: List[str] = list(getattr(device, "groups", []) or [])
        tags: List[str] = list(getattr(device, "tags", []) or [])

        return RegisteredRuntimeDevice(
            device_id=device_id,
            device_name=str(getattr(device, "name", "") or ""),
            platform=platform,
            device_type=raw_type,
            status=status,
            online=online,
            last_seen=last_seen,
            capabilities=RuntimeCapabilityProfile(capabilities=caps_str),
            autonomy=RuntimeAutonomySummary(runtime_enabled=online),
            participation_hints=RuntimeParticipationHints(groups=groups, tags=tags),
            metadata=meta,
        )
    except Exception:
        return RegisteredRuntimeDevice(
            device_id=str(getattr(device, "device_id", "") or f"dev_{uuid.uuid4().hex[:8]}"),
        )


def from_device_agent_manager_record(device: Any) -> RegisteredRuntimeDevice:
    """Build a :class:`RegisteredRuntimeDevice` from a
    ``core.device_agent_manager.DeviceInfo`` record.

    This adapter covers the agent-backed device source so that
    ``DeviceAgentManager``-originated device state can be projected into the
    canonical single-device read contract without coupling to the internal
    dataclass.

    Parameters
    ----------
    device:
        A ``core.device_agent_manager.DeviceInfo`` instance (or any object
        with the same field shape: ``device_id``, ``device_type``,
        ``device_name``, ``status``, ``capabilities``, ``metadata``,
        ``last_heartbeat``, ``registered_at``).

    Returns
    -------
    RegisteredRuntimeDevice
        The normalised canonical contract.  Fields that cannot be mapped are
        left at their defaults.
    """
    try:
        device_id: str = str(getattr(device, "device_id", "") or "")
        if not device_id:
            device_id = f"dev_{uuid.uuid4().hex[:8]}"

        # device_type — DeviceType enum or plain string
        raw_type_obj = getattr(device, "device_type", None)
        if raw_type_obj is None:
            raw_type = ""
        elif hasattr(raw_type_obj, "value"):
            raw_type = str(raw_type_obj.value)
        else:
            raw_type = str(raw_type_obj)

        platform = RuntimeDevicePlatform.from_string(raw_type)

        # status — DeviceStatus enum or plain string
        raw_status_obj = getattr(device, "status", None)
        if raw_status_obj is None:
            raw_status = "offline"
        elif hasattr(raw_status_obj, "value"):
            raw_status = str(raw_status_obj.value)
        else:
            raw_status = str(raw_status_obj)
        status = RuntimeDeviceStatus.from_string(raw_status)
        online = status in (RuntimeDeviceStatus.ONLINE, RuntimeDeviceStatus.BUSY)

        # capabilities — List[DeviceCapability] enums or plain strings
        caps_raw = getattr(device, "capabilities", []) or []
        caps_str: List[str] = []
        for c in caps_raw:
            if isinstance(c, str):
                caps_str.append(c)
            elif hasattr(c, "value"):
                caps_str.append(str(c.value))
            elif hasattr(c, "name"):
                caps_str.append(str(c.name))

        # last_heartbeat — datetime or float
        lh = getattr(device, "last_heartbeat", None)
        last_seen: Optional[float] = None
        if lh is not None:
            try:
                last_seen = lh.timestamp() if hasattr(lh, "timestamp") else float(lh)
            except Exception:
                pass

        meta: Dict[str, Any] = dict(getattr(device, "metadata", {}) or {})

        # Carry registered_at in metadata if present (it is agent-manager-specific)
        registered_at = getattr(device, "registered_at", None)
        if registered_at is not None and "registered_at" not in meta:
            try:
                meta["registered_at"] = (
                    registered_at.isoformat()
                    if hasattr(registered_at, "isoformat")
                    else str(registered_at)
                )
            except Exception:
                pass

        return RegisteredRuntimeDevice(
            device_id=device_id,
            device_name=str(getattr(device, "device_name", "") or ""),
            platform=platform,
            device_type=raw_type,
            status=status,
            online=online,
            last_seen=last_seen,
            capabilities=RuntimeCapabilityProfile(capabilities=caps_str),
            autonomy=RuntimeAutonomySummary(runtime_enabled=online),
            metadata=meta,
        )
    except Exception:
        try:
            fallback_id = str(device.device_id) or f"dev_{uuid.uuid4().hex[:8]}"
        except Exception:
            fallback_id = f"dev_{uuid.uuid4().hex[:8]}"
        return RegisteredRuntimeDevice(device_id=fallback_id)


def build_registered_runtime_device(
    device_id: str,
    device_name: str = "",
    owner_id: Optional[str] = None,
    platform: str = "unknown",
    form_factor: str = "unknown",
    device_type: str = "",
    runtime_id: Optional[str] = None,
    runtime_version: Optional[str] = None,
    runtime_enabled: bool = False,
    supports_local_autonomy: bool = False,
    supports_remote_handoff: bool = False,
    capabilities: Optional[List[str]] = None,
    capability_flags: int = 0,
    supported_actions: Optional[List[str]] = None,
    status: str = "offline",
    online: Optional[bool] = None,
    last_seen: Optional[float] = None,
    active_session_ids: Optional[List[str]] = None,
    current_task_id: Optional[str] = None,
    pending_task_ids: Optional[List[str]] = None,
    body_mesh_roles: Optional[List[str]] = None,
    is_primary_body: bool = False,
    groups: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    connection_state: str = "disconnected",
    transport: str = "",
    endpoint: str = "",
    ip_address: str = "",
    port: int = 0,
    source_runtime_posture: str = "control_only",
    is_runtime_host: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> RegisteredRuntimeDevice:
    """Generic builder for a :class:`RegisteredRuntimeDevice`.

    All downstream code that hand-rolls ad hoc device-normalisation dicts
    should prefer this function (or one of the typed adapters above) instead.

    Parameters
    ----------
    device_id:
        Required.  Stable unique device identifier.
    device_name:
        Human-readable display name.
    owner_id:
        Optional owner/user account identifier.
    platform:
        Platform string (e.g. ``"android"``, ``"windows"``).
    form_factor:
        Form-factor string (e.g. ``"phone"``, ``"desktop"``).
    device_type:
        Fine-grained device type string (e.g. ``"android_phone"``).
    runtime_id:
        Optional runtime instance identifier.
    runtime_version:
        Optional runtime client version string.
    runtime_enabled:
        Whether the Galaxy runtime is activated on this device.
    supports_local_autonomy:
        Whether the device can run tasks locally without the server.
    supports_remote_handoff:
        Whether the device supports cross-device handoff.
    capabilities:
        List of capability name strings.
    capability_flags:
        Android-bridge style integer bitmask (0 if not applicable).
    supported_actions:
        List of discrete action verb strings.
    status:
        Operational status string.
    online:
        Convenience flag; derived from *status* if not provided.
    last_seen:
        Unix timestamp of last activity.
    active_session_ids:
        List of active runtime session IDs.
    current_task_id:
        Currently executing task ID, if any.
    pending_task_ids:
        Queued task IDs.
    body_mesh_roles:
        Body-mesh role strings (e.g. ``["action", "presence"]``).
    is_primary_body:
        Whether this device is the primary body in its session.
    groups:
        Device group memberships.
    tags:
        Freeform classification tags.
    connection_state:
        Transport connection state string.
    transport:
        Transport mechanism name (e.g. ``"websocket"``).
    endpoint:
        Connection endpoint URL.
    ip_address:
        Remote IP address.
    port:
        Remote port.
    metadata:
        Arbitrary extension fields.
    source_runtime_posture:
        Source-device runtime posture (PR-5 / post-533).  'control_only' or
        'join_runtime'.  Defaults to 'control_only'.
    is_runtime_host:
        Whether this device is a first-class runtime host (PR-5).

    Returns
    -------
    RegisteredRuntimeDevice
    """
    resolved_status = RuntimeDeviceStatus.from_string(status)
    resolved_online: bool = (
        online
        if online is not None
        else resolved_status in (RuntimeDeviceStatus.ONLINE, RuntimeDeviceStatus.BUSY)
    )

    return RegisteredRuntimeDevice(
        device_id=device_id,
        device_name=device_name,
        owner_id=owner_id,
        platform=RuntimeDevicePlatform.from_string(platform),
        form_factor=RuntimeDeviceFormFactor.from_string(form_factor),
        device_type=device_type,
        status=resolved_status,
        online=resolved_online,
        last_seen=last_seen,
        connection=RuntimeConnectionSummary(
            state=RuntimeConnectionState.from_string(connection_state),
            transport=transport,
            endpoint=endpoint,
            ip_address=ip_address,
            port=port,
        ),
        capabilities=RuntimeCapabilityProfile(
            capabilities=list(capabilities or []),
            capability_flags=capability_flags,
            supported_actions=list(supported_actions or []),
        ),
        autonomy=RuntimeAutonomySummary(
            runtime_enabled=runtime_enabled,
            supports_local_autonomy=supports_local_autonomy,
            supports_remote_handoff=supports_remote_handoff,
            runtime_id=runtime_id,
            runtime_version=runtime_version,
        ),
        session_presence=RuntimeSessionPresence(
            active_session_ids=list(active_session_ids or []),
            current_task_id=current_task_id,
            pending_task_ids=list(pending_task_ids or []),
        ),
        participation_hints=RuntimeParticipationHints(
            body_mesh_roles=list(body_mesh_roles or []),
            is_primary_body=is_primary_body,
            groups=list(groups or []),
            tags=list(tags or []),
        ),
        source_runtime_posture=source_runtime_posture,
        is_runtime_host=is_runtime_host,
        metadata=dict(metadata or {}),
    )


# ---------------------------------------------------------------------------
# PR-5 / post-533 policy sentinels — Android first-class runtime host
# ---------------------------------------------------------------------------

# Sentinel confirming that RegisteredRuntimeDevice carries source_runtime_posture
# and is_runtime_host as first-class fields (PR-5, main-repo half).
ANDROID_FIRST_CLASS_RUNTIME_HOST_REGISTRATION_PR5 = (
    "ANDROID_FIRST_CLASS_RUNTIME_HOST_REGISTRATION_PR5"
)

# Sentinel confirming that from_android_registration() resolves posture from the
# registration payload and classifies Android as a runtime host where appropriate.
ANDROID_REGISTRATION_POSTURE_AWARE_PR5 = (
    "ANDROID_REGISTRATION_POSTURE_AWARE_PR5"
)

