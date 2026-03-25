"""contracts/runtime_presence_record.py
=========================================
Runtime Presence Record Contract — PR-56.

This module defines :class:`RuntimePresenceRecord`: the **canonical runtime
presence and connection-state contract** for a Galaxy device.

Design principle: presence is separate from identity
-----------------------------------------------------
:class:`RuntimePresenceRecord` captures *how the device is currently
connected* — its active transport, connection state, session pointers,
online flag, heartbeat timestamp, routability, and degraded flag.  It
intentionally carries **no long-term capability truth and no owner / platform
classification**.  Those concerns belong to
:class:`~contracts.canonical_device_identity.CanonicalDeviceIdentity`.

Relationship to :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`
--------------------------------------------------------------------------------------
``RegisteredRuntimeDevice`` (PR-5 / PR-29) remains the **sole canonical
external single-device read contract**.  ``RuntimePresenceRecord`` is a
*narrower, identity-free projection* of that contract, suitable for

* online/offline routing decisions
* heartbeat and reconnect logic
* task assignment gating (is the device currently reachable?)
* presence-authority services (RuntimePresenceService, future PRD-04)

Adapters
--------
* :func:`from_registered_runtime_device` — from a ``RegisteredRuntimeDevice``
* :func:`build_runtime_presence_record` — generic keyword-argument builder

Usage::

    from contracts.runtime_presence_record import (
        RuntimePresenceRecord,
        RuntimeTransport,
        build_runtime_presence_record,
        from_registered_runtime_device,
    )

    record = build_runtime_presence_record(
        device_id="phone_001",
        online=True,
        transport="websocket",
        connection_state="connected",
    )
    payload = record.to_dict()

See ``docs/RUNTIME_PRESENCE_RECORD_CONTRACT.md`` for the full specification.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Transport enum (string literals)
# ---------------------------------------------------------------------------

class RuntimeTransport:
    """Well-known transport identifiers.

    These are plain string constants rather than an enum so that unknown
    transport strings degrade gracefully (they are stored as-is).
    """

    WEBSOCKET: str = "websocket"
    HTTP: str = "http"
    WEBRTC: str = "webrtc"
    LOCAL: str = "local"
    BRIDGE: str = "bridge"
    UNKNOWN: str = "unknown"

    _ALL = {WEBSOCKET, HTTP, WEBRTC, LOCAL, BRIDGE, UNKNOWN}

    @classmethod
    def normalise(cls, raw: Optional[str]) -> str:
        """Return a known transport string, defaulting to ``'unknown'``."""
        if raw is None:
            return cls.UNKNOWN
        lower = str(raw).lower()
        if lower in cls._ALL:
            return lower
        # Accept common aliases
        aliases = {
            "ws": cls.WEBSOCKET,
            "wss": cls.WEBSOCKET,
            "rest": cls.HTTP,
            "rtc": cls.WEBRTC,
            "peer": cls.WEBRTC,
        }
        return aliases.get(lower, lower)  # preserve unknown strings


# ---------------------------------------------------------------------------
# Canonical Runtime Presence Record
# ---------------------------------------------------------------------------


class RuntimePresenceRecord(BaseModel):
    """Ephemeral connection/session presence record for a runtime device.

    This contract answers *"is this device reachable right now, and how?"*
    without carrying any long-term identity or capability state.

    Fields are intentionally limited to transport, session, and liveness
    concerns so that this contract can be maintained by a lightweight presence
    authority without needing to duplicate the full device registry.

    Required fields
    ---------------
    ``device_id`` — must be a non-empty string.

    All other fields have sensible defaults.
    """

    # ── Device reference ────────────────────────────────────────────────────
    device_id: str = Field(
        description="Stable identifier of the device this record belongs to.",
    )

    # ── Session / connection pointers ───────────────────────────────────────
    connection_id: Optional[str] = Field(
        default=None,
        description=(
            "Ephemeral identifier of the current transport connection "
            "(e.g. WebSocket connection object ID).  Changes on reconnect."
        ),
    )
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "Runtime session identifier.  May persist across short "
            "disconnects for session-roaming scenarios."
        ),
    )

    # ── Transport ────────────────────────────────────────────────────────────
    transport: str = Field(
        default=RuntimeTransport.UNKNOWN,
        description=(
            "Active transport channel: 'websocket', 'http', 'webrtc', "
            "'local', 'bridge', or 'unknown'."
        ),
    )
    connection_state: str = Field(
        default="disconnected",
        description=(
            "Low-level connection state: 'connected', 'connecting', "
            "'reconnecting', 'disconnecting', 'disconnected'."
        ),
    )

    # ── Liveness ─────────────────────────────────────────────────────────────
    online: bool = Field(
        default=False,
        description="True when the device has an active, healthy connection.",
    )
    last_seen: float = Field(
        default=0.0,
        description="Unix timestamp of the most recent heartbeat or message.",
    )

    # ── Routing / health ─────────────────────────────────────────────────────
    routable: bool = Field(
        default=False,
        description=(
            "True when the device can currently receive dispatched tasks.  "
            "May be False even when online during graceful drain or overload."
        ),
    )
    degraded: bool = Field(
        default=False,
        description=(
            "True when the device is online but operating in a degraded mode "
            "(e.g. limited capability set, reduced throughput)."
        ),
    )

    # ── Active task pointers ─────────────────────────────────────────────────
    current_task_id: Optional[str] = Field(
        default=None,
        description="ID of the task currently being executed on this device, if any.",
    )
    pending_task_ids: List[str] = Field(
        default_factory=list,
        description="IDs of tasks queued on this device, in submission order.",
    )

    model_config = {"populate_by_name": True}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_connected(self) -> bool:
        """Return ``True`` when the connection state is 'connected'."""
        return self.connection_state == "connected"

    def is_available_for_dispatch(self) -> bool:
        """Return ``True`` when the device is online, routable, and not degraded."""
        return self.online and self.routable and not self.degraded

    def seconds_since_seen(self) -> float:
        """Return elapsed seconds since :attr:`last_seen` (or ``float('inf')``
        when ``last_seen`` is zero)."""
        if self.last_seen <= 0:
            return float("inf")
        return max(0.0, time.time() - self.last_seen)

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
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimePresenceRecord":
        """Construct from a plain dict (e.g. after JSON deserialisation)."""
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Adapter: from RegisteredRuntimeDevice (PR-29)
# ---------------------------------------------------------------------------


def from_registered_runtime_device(device: Any) -> RuntimePresenceRecord:
    """Build a :class:`RuntimePresenceRecord` from a
    :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`.

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

        online = bool(getattr(device, "online", False))

        # connection sub-object
        conn = getattr(device, "connection", None)
        connection_id: Optional[str] = None
        session_id: Optional[str] = None
        transport = RuntimeTransport.UNKNOWN
        connection_state = "disconnected"

        if conn is not None:
            raw_conn_id = getattr(conn, "connection_id", None)
            connection_id = str(raw_conn_id) if raw_conn_id else None

            raw_sess_id = getattr(conn, "session_id", None)
            session_id = str(raw_sess_id) if raw_sess_id else None

            raw_transport = getattr(conn, "transport", None)
            if raw_transport is not None:
                transport_str = (
                    raw_transport.value
                    if hasattr(raw_transport, "value")
                    else str(raw_transport)
                )
                transport = RuntimeTransport.normalise(transport_str)

            raw_state = getattr(conn, "connection_state", None)
            if raw_state is not None:
                connection_state = (
                    raw_state.value
                    if hasattr(raw_state, "value")
                    else str(raw_state)
                )

        # last_seen
        last_seen_raw = getattr(device, "last_seen", 0.0)
        try:
            last_seen = float(last_seen_raw) if last_seen_raw else 0.0
        except (TypeError, ValueError):
            last_seen = 0.0

        # routable / degraded: derive from connection_state and online flag
        routable = online and connection_state == "connected"
        degraded_raw = getattr(device, "degraded", None)
        degraded = bool(degraded_raw) if degraded_raw is not None else False

        # session presence — task pointers
        session_presence = getattr(device, "session_presence", None)
        current_task_id: Optional[str] = None
        pending_task_ids: List[str] = []
        if session_presence is not None:
            raw_ctask = getattr(session_presence, "current_task_id", None)
            current_task_id = str(raw_ctask) if raw_ctask else None
            raw_pending = getattr(session_presence, "pending_task_ids", None) or []
            pending_task_ids = [str(t) for t in raw_pending]
            # session_id from session_presence if not already set
            if session_id is None:
                raw_sess_ids = getattr(session_presence, "active_session_ids", None) or []
                if raw_sess_ids:
                    session_id = str(raw_sess_ids[0])

        return RuntimePresenceRecord(
            device_id=device_id,
            connection_id=connection_id,
            session_id=session_id,
            transport=transport,
            connection_state=connection_state,
            online=online,
            last_seen=last_seen,
            routable=routable,
            degraded=degraded,
            current_task_id=current_task_id,
            pending_task_ids=pending_task_ids,
        )
    except Exception:
        dev_id = str(getattr(device, "device_id", "") or f"dev_{uuid.uuid4().hex[:8]}")
        return RuntimePresenceRecord(device_id=dev_id)


# ---------------------------------------------------------------------------
# Generic builder
# ---------------------------------------------------------------------------


def build_runtime_presence_record(
    *,
    device_id: str,
    connection_id: Optional[str] = None,
    session_id: Optional[str] = None,
    transport: str = RuntimeTransport.UNKNOWN,
    connection_state: str = "disconnected",
    online: bool = False,
    last_seen: float = 0.0,
    routable: bool = False,
    degraded: bool = False,
    current_task_id: Optional[str] = None,
    pending_task_ids: Optional[List[str]] = None,
) -> RuntimePresenceRecord:
    """Build a :class:`RuntimePresenceRecord` from keyword arguments.

    This is the preferred way to construct a presence record when source data
    is already decomposed into individual fields (e.g. from a heartbeat event
    or a WebSocket on-connect callback).
    """
    return RuntimePresenceRecord(
        device_id=device_id,
        connection_id=connection_id,
        session_id=session_id,
        transport=RuntimeTransport.normalise(transport),
        connection_state=connection_state,
        online=online,
        last_seen=last_seen if last_seen > 0 else 0.0,
        routable=routable,
        degraded=degraded,
        current_task_id=current_task_id,
        pending_task_ids=list(pending_task_ids or []),
    )
