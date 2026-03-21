"""contracts/local_runtime_host.py
====================================
Local Runtime Host Contract — PR-30.

This module defines the **canonical Local Runtime Host contract**: a single,
serialisable schema that answers the question:

    *"Given a registered runtime-capable device, what standard contract
    describes its local runtime-host behaviour?"*

It is the host-side counterpart to PR-29 (``RegisteredRuntimeDevice``):

- **PR-29** defines what a runtime-capable device *is*.
- **PR-30** defines what a device hosting a local runtime must *expose*.

This contract formalises local runtime-host posture including:
- whether the device accepts runtime participation;
- the device's local autonomy posture (can it run local inference / planning);
- support for receiving cross-device handoff;
- local execution and session lifecycle in a standard way.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — :meth:`LocalRuntimeHost.to_dict` and
  :meth:`LocalRuntimeHost.to_json` produce stable, round-trippable JSON.
- **Graceful defaults** — all fields beyond ``host_id`` and ``device_id`` are
  optional; adapters catch exceptions and degrade gracefully.
- **No UI-specific semantics** — suitable for runtime/projection/handoff/API
  use.
- **Stable field names** — downstream consumers can rely on the field names
  defined here without fear of silent renaming.

Usage::

    from contracts.local_runtime_host import (
        LocalRuntimeHost,
        LocalRuntimeHostStatus,
        LocalRuntimeHostCapabilities,
        LocalRuntimeSessionSupport,
        LocalRuntimeHandoffSupport,
        LocalRuntimeExecutionSupport,
        from_registered_runtime_device,
        from_runtime_bridge_config,
        build_local_runtime_host,
        summarize_local_runtime_host,
    )

    # Build from a RegisteredRuntimeDevice (PR-29)
    from contracts.registered_runtime_device import build_registered_runtime_device
    rrd = build_registered_runtime_device(
        device_id="phone_001",
        runtime_enabled=True,
        supports_local_autonomy=True,
    )
    host = from_registered_runtime_device(rrd)
    payload = host.to_dict()

    # Build from scratch
    host = build_local_runtime_host(
        device_id="pc_001",
        host_enabled=True,
        supports_local_execution=True,
    )

See ``docs/LOCAL_RUNTIME_HOST_CONTRACT.md`` for the full specification.
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


class LocalRuntimeHostStatus(str, Enum):
    """Operational status of a local runtime host.

    Tracks whether the host runtime is currently accepting participation.
    """

    INACTIVE = "inactive"
    STARTING = "starting"
    ACTIVE = "active"
    DEGRADED = "degraded"
    STOPPING = "stopping"
    ERROR = "error"

    @classmethod
    def from_string(cls, value: str) -> "LocalRuntimeHostStatus":
        """Return a :class:`LocalRuntimeHostStatus` from a raw string,
        defaulting to :attr:`INACTIVE` on unrecognised values.
        """
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.INACTIVE


class LocalRuntimeExecutionMode(str, Enum):
    """Supported execution modes for a local runtime host."""

    LOCAL = "local"
    REMOTE = "remote"
    HYBRID = "hybrid"
    FALLBACK = "fallback"

    @classmethod
    def from_string(cls, value: str) -> "LocalRuntimeExecutionMode":
        try:
            return cls(value.lower())
        except (ValueError, AttributeError):
            return cls.LOCAL


# ---------------------------------------------------------------------------
# Sub-contract models
# ---------------------------------------------------------------------------


class LocalRuntimeHostCapabilities(BaseModel):
    """Capability posture of the local runtime host.

    Captures what the host can do in terms of autonomous local execution,
    planning, fallback and remote handoff receive.
    """

    supports_local_autonomy: bool = Field(
        default=False,
        description=(
            "Whether this host can operate an autonomous local loop "
            "(voice-in → inference → action → output) without remote assistance."
        ),
    )
    supports_local_execution: bool = Field(
        default=False,
        description="Whether this host can execute tasks locally.",
    )
    supports_local_planning: bool = Field(
        default=False,
        description="Whether this host can run a local planning/reasoning step.",
    )
    supports_local_fallback: bool = Field(
        default=False,
        description=(
            "Whether this host will accept tasks as a fallback when "
            "primary execution paths are unavailable."
        ),
    )
    supports_remote_handoff_receive: bool = Field(
        default=False,
        description=(
            "Whether this host can receive a cross-device handoff "
            "(i.e. another device can dispatch a runtime agent to this host)."
        ),
    )
    supports_remote_handoff_callback: bool = Field(
        default=False,
        description=(
            "Whether this host can send handoff-completion callbacks "
            "back to the originating device."
        ),
    )
    supports_runtime_sessions: bool = Field(
        default=False,
        description="Whether this host supports multi-step runtime sessions.",
    )

    model_config = {"extra": "allow", "use_enum_values": True}


class LocalRuntimeSessionSupport(BaseModel):
    """Session-lifecycle support posture for a local runtime host."""

    supports_runtime_sessions: bool = Field(
        default=False,
        description="Whether the host supports runtime sessions.",
    )
    max_concurrent_tasks: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum number of tasks that can run concurrently (None = unlimited).",
    )
    current_load: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Normalised current load [0.0, 1.0] where 1.0 is fully saturated.",
    )
    active_session_ids: List[str] = Field(
        default_factory=list,
        description="IDs of sessions currently hosted on this runtime.",
    )

    model_config = {"extra": "allow"}


class LocalRuntimeHandoffSupport(BaseModel):
    """Handoff-receive posture for a local runtime host.

    Captures whether the host can act as a cross-device handoff *target*
    (receiving an agent dispatched from another device).
    """

    supports_remote_handoff_receive: bool = Field(
        default=False,
        description="Whether this host can receive a cross-device runtime handoff.",
    )
    supports_remote_handoff_callback: bool = Field(
        default=False,
        description="Whether this host sends callbacks on handoff completion.",
    )
    callback_channels: List[str] = Field(
        default_factory=list,
        description=(
            "Supported callback channels, e.g. ['ws', 'nats', 'webrtc']. "
            "Empty when handoff callbacks are not supported."
        ),
    )

    model_config = {"extra": "allow"}


class LocalRuntimeExecutionSupport(BaseModel):
    """Execution-capability posture for a local runtime host."""

    supports_local_execution: bool = Field(
        default=False,
        description="Whether this host can execute tasks locally.",
    )
    supports_local_planning: bool = Field(
        default=False,
        description="Whether this host can perform local planning/reasoning.",
    )
    supports_local_autonomy: bool = Field(
        default=False,
        description="Whether this host can operate a fully autonomous local loop.",
    )
    supports_local_fallback: bool = Field(
        default=False,
        description="Whether this host accepts tasks in fallback mode.",
    )
    execution_modes: List[str] = Field(
        default_factory=list,
        description="Supported execution modes, e.g. ['local', 'remote', 'hybrid'].",
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Top-level canonical contract
# ---------------------------------------------------------------------------


class LocalRuntimeHost(BaseModel):
    """Canonical Local Runtime Host contract.

    Describes the runtime-host posture of a physical device that has been
    registered as a ``RegisteredRuntimeDevice`` (PR-29) and is eligible to
    host a local runtime.

    This is the stable contract that PR-31 (Handoff Envelope v2), PR-32 (Mesh
    Membership), and PR-33 (Mesh Session) will target.

    All fields beyond ``host_id`` and ``device_id`` are optional so that
    adapters from partial data sources can produce a valid contract.

    Fields
    ------
    host_id:
        Stable unique identifier for this local-runtime-host record.
        Auto-generated as a UUID-hex if not supplied.
    device_id:
        Stable identifier of the underlying physical device.
    runtime_id:
        Optional identifier of the active runtime instance on this host.
    runtime_version:
        Optional version string for the runtime (e.g. ``"1.4.2"``).
    host_enabled:
        Whether this device is actively enabled as a runtime host.
    host_status:
        Current operational status of the local runtime.
    capabilities:
        Capability posture sub-contract.
    sessions:
        Session-lifecycle support sub-contract.
    handoff:
        Handoff-receive support sub-contract.
    execution:
        Execution-capability sub-contract.
    capability_summary:
        Flat list of capability name strings for quick filtering.
    execution_modes:
        Flat list of supported execution mode strings.
    callback_channels:
        Flat list of supported callback channel strings.
    active_session_ids:
        IDs of sessions currently active on this host (flat list mirror of
        ``sessions.active_session_ids``).
    max_concurrent_tasks:
        Mirror of ``sessions.max_concurrent_tasks`` for convenience.
    current_load:
        Mirror of ``sessions.current_load`` for convenience.
    metadata:
        Arbitrary extra metadata; tolerant of partial or missing values.
    recorded_at:
        Unix timestamp when this host record was created/snapshotted.
    """

    # Identity
    host_id: str = Field(
        default_factory=lambda: f"lrh_{uuid.uuid4().hex[:12]}",
        description="Stable unique identifier for this local-runtime-host record.",
    )
    device_id: str = Field(
        default="",
        description="Stable identifier of the underlying physical device.",
    )
    runtime_id: Optional[str] = Field(
        default=None,
        description="Optional identifier of the active runtime instance.",
    )
    runtime_version: Optional[str] = Field(
        default=None,
        description="Version string of the runtime, if known.",
    )

    # Enable / status
    host_enabled: bool = Field(
        default=False,
        description="Whether this device is actively enabled as a local runtime host.",
    )
    host_status: LocalRuntimeHostStatus = Field(
        default=LocalRuntimeHostStatus.INACTIVE,
        description="Current operational status of the local runtime host.",
    )

    # Top-level posture flags (mirrors of sub-contract fields for convenience)
    supports_local_autonomy: bool = Field(
        default=False,
        description="Whether this host can operate a fully autonomous local loop.",
    )
    supports_local_execution: bool = Field(
        default=False,
        description="Whether this host can execute tasks locally.",
    )
    supports_local_planning: bool = Field(
        default=False,
        description="Whether this host can perform local planning/reasoning.",
    )
    supports_local_fallback: bool = Field(
        default=False,
        description="Whether this host accepts tasks in fallback mode.",
    )
    supports_remote_handoff_receive: bool = Field(
        default=False,
        description="Whether this host can receive a cross-device runtime handoff.",
    )
    supports_remote_handoff_callback: bool = Field(
        default=False,
        description="Whether this host sends callbacks on handoff completion.",
    )
    supports_runtime_sessions: bool = Field(
        default=False,
        description="Whether this host supports multi-step runtime sessions.",
    )

    # Flat convenience lists
    active_session_ids: List[str] = Field(
        default_factory=list,
        description="IDs of sessions currently active on this host.",
    )
    execution_modes: List[str] = Field(
        default_factory=list,
        description="Supported execution mode strings, e.g. ['local', 'hybrid'].",
    )
    callback_channels: List[str] = Field(
        default_factory=list,
        description="Supported callback channel strings, e.g. ['ws', 'nats'].",
    )
    capability_summary: List[str] = Field(
        default_factory=list,
        description="Flat list of capability name strings for quick filtering.",
    )

    # Optional load / concurrency
    max_concurrent_tasks: Optional[int] = Field(
        default=None,
        ge=0,
        description="Maximum concurrent tasks (None = unlimited).",
    )
    current_load: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Normalised current load [0.0, 1.0].",
    )

    # Sub-contracts (structured, optional)
    capabilities: LocalRuntimeHostCapabilities = Field(
        default_factory=LocalRuntimeHostCapabilities,
        description="Structured capability posture sub-contract.",
    )
    sessions: LocalRuntimeSessionSupport = Field(
        default_factory=LocalRuntimeSessionSupport,
        description="Session-lifecycle support sub-contract.",
    )
    handoff: LocalRuntimeHandoffSupport = Field(
        default_factory=LocalRuntimeHandoffSupport,
        description="Handoff-receive support sub-contract.",
    )
    execution: LocalRuntimeExecutionSupport = Field(
        default_factory=LocalRuntimeExecutionSupport,
        description="Execution-capability support sub-contract.",
    )

    # Metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra metadata; tolerant of partial/missing values.",
    )
    recorded_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this host record was created/snapshotted.",
    )

    model_config = {"extra": "allow", "use_enum_values": True}

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return self.model_dump()

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict(), default=str, **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalRuntimeHost":
        """Reconstruct a :class:`LocalRuntimeHost` from a plain dict."""
        return cls(**data)


# ---------------------------------------------------------------------------
# Adapter / builder functions
# ---------------------------------------------------------------------------


def from_registered_runtime_device(device: Any) -> LocalRuntimeHost:
    """Build a :class:`LocalRuntimeHost` from a :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`.

    This is the primary adapter; PR-29 device records are the canonical source
    of truth for device identity and capability flags.

    Parameters
    ----------
    device:
        A ``contracts.registered_runtime_device.RegisteredRuntimeDevice``
        instance (or any object with the same field shape).

    Returns
    -------
    LocalRuntimeHost
        Fully populated host contract.  Fields that cannot be mapped are
        left at their defaults.
    """
    try:
        device_id = str(getattr(device, "device_id", "") or "")
        if not device_id:
            device_id = f"dev_{uuid.uuid4().hex[:8]}"

        # Pull autonomy summary sub-object if available
        autonomy = getattr(device, "autonomy", None)
        runtime_enabled = False
        supports_local_autonomy = False
        supports_remote_handoff = False
        runtime_id: Optional[str] = None
        runtime_version: Optional[str] = None

        if autonomy is not None:
            runtime_enabled = bool(getattr(autonomy, "runtime_enabled", False))
            supports_local_autonomy = bool(getattr(autonomy, "supports_local_autonomy", False))
            supports_remote_handoff = bool(getattr(autonomy, "supports_remote_handoff", False))
            runtime_id = getattr(autonomy, "runtime_id", None)
            runtime_version = getattr(autonomy, "runtime_version", None)
        else:
            # Flat fields fallback
            runtime_enabled = bool(getattr(device, "runtime_enabled", False))
            supports_local_autonomy = bool(getattr(device, "supports_local_autonomy", False))
            supports_remote_handoff = bool(getattr(device, "supports_remote_handoff", False))
            runtime_id = getattr(device, "runtime_id", None)
            runtime_version = getattr(device, "runtime_version", None)

        # Session presence
        session_presence = getattr(device, "session_presence", None)
        active_session_ids: List[str] = []
        if session_presence is not None:
            active_session_ids = list(getattr(session_presence, "active_session_ids", []) or [])

        # Capability summary
        cap_profile = getattr(device, "capabilities", None)
        cap_summary: List[str] = []
        if cap_profile is not None and hasattr(cap_profile, "capabilities"):
            cap_summary = list(getattr(cap_profile, "capabilities", []) or [])
        elif hasattr(device, "capability_summary"):
            cap_summary = list(getattr(device, "capability_summary", []) or [])

        # Status → host_status
        raw_status = str(getattr(device, "status", "offline") or "offline")
        online = bool(getattr(device, "online", False))
        if runtime_enabled and online:
            host_status = LocalRuntimeHostStatus.ACTIVE
        elif runtime_enabled:
            host_status = LocalRuntimeHostStatus.INACTIVE
        else:
            host_status = LocalRuntimeHostStatus.INACTIVE

        host_enabled = runtime_enabled and online

        # Execution modes
        execution_modes: List[str] = []
        if supports_local_autonomy or runtime_enabled:
            execution_modes.append(LocalRuntimeExecutionMode.LOCAL.value)
        if supports_remote_handoff:
            execution_modes.append(LocalRuntimeExecutionMode.REMOTE.value)
        if execution_modes:
            execution_modes.append(LocalRuntimeExecutionMode.HYBRID.value)

        # Callback channels from participation hints
        hints = getattr(device, "participation_hints", None)
        callback_channels: List[str] = []
        if hints is not None:
            preferred_channel = getattr(hints, "preferred_callback_channel", "")
            if preferred_channel:
                callback_channels = [preferred_channel]

        metadata: Dict[str, Any] = {}
        raw_meta = getattr(device, "metadata", None)
        if isinstance(raw_meta, dict):
            metadata = raw_meta

        caps = LocalRuntimeHostCapabilities(
            supports_local_autonomy=supports_local_autonomy,
            supports_local_execution=runtime_enabled,
            supports_local_planning=supports_local_autonomy,
            supports_local_fallback=runtime_enabled,
            supports_remote_handoff_receive=supports_remote_handoff,
            supports_remote_handoff_callback=supports_remote_handoff and bool(callback_channels),
            supports_runtime_sessions=runtime_enabled,
        )
        sessions = LocalRuntimeSessionSupport(
            supports_runtime_sessions=runtime_enabled,
            active_session_ids=active_session_ids,
        )
        handoff = LocalRuntimeHandoffSupport(
            supports_remote_handoff_receive=supports_remote_handoff,
            supports_remote_handoff_callback=supports_remote_handoff and bool(callback_channels),
            callback_channels=callback_channels,
        )
        execution = LocalRuntimeExecutionSupport(
            supports_local_execution=runtime_enabled,
            supports_local_planning=supports_local_autonomy,
            supports_local_autonomy=supports_local_autonomy,
            supports_local_fallback=runtime_enabled,
            execution_modes=execution_modes,
        )

        return LocalRuntimeHost(
            device_id=device_id,
            runtime_id=runtime_id,
            runtime_version=runtime_version,
            host_enabled=host_enabled,
            host_status=host_status,
            supports_local_autonomy=supports_local_autonomy,
            supports_local_execution=runtime_enabled,
            supports_local_planning=supports_local_autonomy,
            supports_local_fallback=runtime_enabled,
            supports_remote_handoff_receive=supports_remote_handoff,
            supports_remote_handoff_callback=supports_remote_handoff and bool(callback_channels),
            supports_runtime_sessions=runtime_enabled,
            active_session_ids=active_session_ids,
            execution_modes=execution_modes,
            callback_channels=callback_channels,
            capability_summary=cap_summary,
            capabilities=caps,
            sessions=sessions,
            handoff=handoff,
            execution=execution,
            metadata=metadata,
        )
    except Exception:
        # Graceful degradation: return a minimal contract rather than raise.
        try:
            fallback_id = str(getattr(device, "device_id", "") or f"dev_{uuid.uuid4().hex[:8]}")
        except Exception:
            fallback_id = f"dev_{uuid.uuid4().hex[:8]}"
        return LocalRuntimeHost(device_id=fallback_id)


def from_runtime_bridge_config(config: Any) -> LocalRuntimeHost:
    """Build a :class:`LocalRuntimeHost` from an ``AgentBridgeConfig`` or
    compatible runtime-bridge configuration object.

    This adapter targets the ``galaxy_gateway.agent_bridge.AgentBridgeConfig``
    shape (or any dict/object with compatible fields).

    Parameters
    ----------
    config:
        An ``AgentBridgeConfig`` instance or a plain dict with bridge config
        fields such as ``runtime_url``, ``runtime_enabled``,
        ``cross_device_enabled``, ``timeout``.

    Returns
    -------
    LocalRuntimeHost
        A host contract populated from bridge-config data.  The ``device_id``
        will be a synthetic identifier unless provided explicitly.
    """
    try:
        if isinstance(config, dict):
            runtime_url: str = str(config.get("runtime_url", "") or "")
            runtime_enabled: bool = bool(config.get("runtime_enabled", True))
            cross_device_enabled: bool = bool(config.get("cross_device_enabled", True))
            device_id: str = str(config.get("device_id", "") or "")
            runtime_id: Optional[str] = config.get("runtime_id")
            runtime_version: Optional[str] = config.get("runtime_version")
            metadata: Dict[str, Any] = {k: v for k, v in config.items()
                                         if k not in {"device_id", "runtime_id",
                                                       "runtime_version", "runtime_url",
                                                       "runtime_enabled", "cross_device_enabled"}}
        else:
            runtime_url = str(getattr(config, "runtime_url", "") or "")
            runtime_enabled = bool(getattr(config, "runtime_enabled", True))
            cross_device_enabled = bool(getattr(config, "cross_device_enabled", True))
            device_id = str(getattr(config, "device_id", "") or "")
            runtime_id = getattr(config, "runtime_id", None)
            runtime_version = getattr(config, "runtime_version", None)
            metadata = {"runtime_url": runtime_url}

        if not device_id:
            device_id = f"bridge_{uuid.uuid4().hex[:8]}"

        execution_modes: List[str] = [LocalRuntimeExecutionMode.LOCAL.value]
        if cross_device_enabled:
            execution_modes.append(LocalRuntimeExecutionMode.REMOTE.value)
            execution_modes.append(LocalRuntimeExecutionMode.HYBRID.value)

        callback_channels: List[str] = ["ws"] if runtime_url else []

        host_status = (
            LocalRuntimeHostStatus.ACTIVE
            if runtime_enabled and cross_device_enabled
            else LocalRuntimeHostStatus.INACTIVE
        )

        caps = LocalRuntimeHostCapabilities(
            supports_local_autonomy=runtime_enabled,
            supports_local_execution=runtime_enabled,
            supports_local_planning=runtime_enabled,
            supports_local_fallback=runtime_enabled,
            supports_remote_handoff_receive=cross_device_enabled,
            supports_remote_handoff_callback=cross_device_enabled and bool(callback_channels),
            supports_runtime_sessions=runtime_enabled,
        )
        sessions = LocalRuntimeSessionSupport(
            supports_runtime_sessions=runtime_enabled,
        )
        handoff = LocalRuntimeHandoffSupport(
            supports_remote_handoff_receive=cross_device_enabled,
            supports_remote_handoff_callback=cross_device_enabled and bool(callback_channels),
            callback_channels=callback_channels,
        )
        execution = LocalRuntimeExecutionSupport(
            supports_local_execution=runtime_enabled,
            supports_local_planning=runtime_enabled,
            supports_local_autonomy=runtime_enabled,
            supports_local_fallback=runtime_enabled,
            execution_modes=execution_modes,
        )

        return LocalRuntimeHost(
            device_id=device_id,
            runtime_id=runtime_id,
            runtime_version=runtime_version,
            host_enabled=runtime_enabled,
            host_status=host_status,
            supports_local_autonomy=runtime_enabled,
            supports_local_execution=runtime_enabled,
            supports_local_planning=runtime_enabled,
            supports_local_fallback=runtime_enabled,
            supports_remote_handoff_receive=cross_device_enabled,
            supports_remote_handoff_callback=cross_device_enabled and bool(callback_channels),
            supports_runtime_sessions=runtime_enabled,
            execution_modes=execution_modes,
            callback_channels=callback_channels,
            capabilities=caps,
            sessions=sessions,
            handoff=handoff,
            execution=execution,
            metadata=metadata,
        )
    except Exception:
        return LocalRuntimeHost(
            device_id=f"bridge_{uuid.uuid4().hex[:8]}",
        )


def build_local_runtime_host(
    device_id: str,
    host_id: Optional[str] = None,
    runtime_id: Optional[str] = None,
    runtime_version: Optional[str] = None,
    host_enabled: bool = False,
    host_status: str = "inactive",
    supports_local_autonomy: bool = False,
    supports_local_execution: bool = False,
    supports_local_planning: bool = False,
    supports_local_fallback: bool = False,
    supports_remote_handoff_receive: bool = False,
    supports_remote_handoff_callback: bool = False,
    supports_runtime_sessions: bool = False,
    max_concurrent_tasks: Optional[int] = None,
    current_load: Optional[float] = None,
    active_session_ids: Optional[List[str]] = None,
    execution_modes: Optional[List[str]] = None,
    callback_channels: Optional[List[str]] = None,
    capability_summary: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> LocalRuntimeHost:
    """Generic builder for a :class:`LocalRuntimeHost`.

    Downstream code that constructs ad hoc host-posture dicts should prefer
    this function (or one of the typed adapters above) so that all callers
    target the canonical contract.

    Parameters
    ----------
    device_id:
        Required.  Stable unique device identifier.
    host_id:
        Optional stable host-record identifier; auto-generated if omitted.
    runtime_id:
        Optional runtime instance identifier.
    runtime_version:
        Optional runtime version string.
    host_enabled:
        Whether the host is actively enabled.
    host_status:
        Operational status string (see :class:`LocalRuntimeHostStatus`).
    supports_local_autonomy:
        Whether the host supports a fully autonomous local loop.
    supports_local_execution:
        Whether the host can execute tasks locally.
    supports_local_planning:
        Whether the host can perform local planning/reasoning.
    supports_local_fallback:
        Whether the host accepts tasks as a fallback.
    supports_remote_handoff_receive:
        Whether the host can receive a cross-device runtime handoff.
    supports_remote_handoff_callback:
        Whether the host can send handoff callbacks.
    supports_runtime_sessions:
        Whether the host supports multi-step runtime sessions.
    max_concurrent_tasks:
        Maximum concurrent tasks (None = unlimited).
    current_load:
        Normalised current load [0.0, 1.0].
    active_session_ids:
        Currently active session IDs.
    execution_modes:
        Supported execution mode strings.
    callback_channels:
        Supported callback channel strings.
    capability_summary:
        Flat list of capability name strings.
    metadata:
        Arbitrary extra metadata.
    """
    parsed_status = LocalRuntimeHostStatus.from_string(host_status)
    _active_sessions = list(active_session_ids or [])
    _exec_modes = list(execution_modes or [])
    _channels = list(callback_channels or [])
    _cap_summary = list(capability_summary or [])
    _metadata = dict(metadata or {})

    caps = LocalRuntimeHostCapabilities(
        supports_local_autonomy=supports_local_autonomy,
        supports_local_execution=supports_local_execution,
        supports_local_planning=supports_local_planning,
        supports_local_fallback=supports_local_fallback,
        supports_remote_handoff_receive=supports_remote_handoff_receive,
        supports_remote_handoff_callback=supports_remote_handoff_callback,
        supports_runtime_sessions=supports_runtime_sessions,
    )
    sessions = LocalRuntimeSessionSupport(
        supports_runtime_sessions=supports_runtime_sessions,
        max_concurrent_tasks=max_concurrent_tasks,
        current_load=current_load,
        active_session_ids=_active_sessions,
    )
    handoff = LocalRuntimeHandoffSupport(
        supports_remote_handoff_receive=supports_remote_handoff_receive,
        supports_remote_handoff_callback=supports_remote_handoff_callback,
        callback_channels=_channels,
    )
    execution = LocalRuntimeExecutionSupport(
        supports_local_execution=supports_local_execution,
        supports_local_planning=supports_local_planning,
        supports_local_autonomy=supports_local_autonomy,
        supports_local_fallback=supports_local_fallback,
        execution_modes=_exec_modes,
    )

    kwargs: Dict[str, Any] = dict(
        device_id=device_id,
        runtime_id=runtime_id,
        runtime_version=runtime_version,
        host_enabled=host_enabled,
        host_status=parsed_status,
        supports_local_autonomy=supports_local_autonomy,
        supports_local_execution=supports_local_execution,
        supports_local_planning=supports_local_planning,
        supports_local_fallback=supports_local_fallback,
        supports_remote_handoff_receive=supports_remote_handoff_receive,
        supports_remote_handoff_callback=supports_remote_handoff_callback,
        supports_runtime_sessions=supports_runtime_sessions,
        max_concurrent_tasks=max_concurrent_tasks,
        current_load=current_load,
        active_session_ids=_active_sessions,
        execution_modes=_exec_modes,
        callback_channels=_channels,
        capability_summary=_cap_summary,
        capabilities=caps,
        sessions=sessions,
        handoff=handoff,
        execution=execution,
        metadata=_metadata,
    )
    if host_id is not None:
        kwargs["host_id"] = host_id

    return LocalRuntimeHost(**kwargs)


def summarize_local_runtime_host(host: LocalRuntimeHost) -> Dict[str, Any]:
    """Return a compact summary dict of a :class:`LocalRuntimeHost`.

    Suitable for lightweight projection payloads, API list responses, and
    future mesh-membership hints without serialising the full sub-contracts.

    Parameters
    ----------
    host:
        The host contract to summarise.

    Returns
    -------
    dict
        A flat dict with key posture flags and identity fields.
    """
    return {
        "host_id": host.host_id,
        "device_id": host.device_id,
        "runtime_id": host.runtime_id,
        "runtime_version": host.runtime_version,
        "host_enabled": host.host_enabled,
        "host_status": host.host_status.value if hasattr(host.host_status, "value") else host.host_status,
        "supports_local_autonomy": host.supports_local_autonomy,
        "supports_local_execution": host.supports_local_execution,
        "supports_local_planning": host.supports_local_planning,
        "supports_local_fallback": host.supports_local_fallback,
        "supports_remote_handoff_receive": host.supports_remote_handoff_receive,
        "supports_remote_handoff_callback": host.supports_remote_handoff_callback,
        "supports_runtime_sessions": host.supports_runtime_sessions,
        "active_session_count": len(host.active_session_ids),
        "execution_modes": host.execution_modes,
        "callback_channels": host.callback_channels,
        "capability_summary": host.capability_summary,
        "max_concurrent_tasks": host.max_concurrent_tasks,
        "current_load": host.current_load,
        "recorded_at": host.recorded_at,
    }
