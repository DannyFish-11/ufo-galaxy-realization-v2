"""galaxy_gateway/protocol/normalized_ingress_event.py
=======================================================
Canonical Normalized Ingress Event — PR-56 / Server PRD-02.

This module defines :class:`NormalizedIngressEvent`: the **canonical schema
that all gateway WS/REST ingress produces** after protocol normalization.

Design principle: legacy aliases stay at the edge
-------------------------------------------------
The AIP v1/v2/v3 compatibility logic lives in
:mod:`galaxy_gateway.protocol.compat`.  That layer handles

* version detection (v1, v2, v3)
* type-string aliasing (``register`` → ``device_register``, etc.)
* trace_id / route_mode / idempotency_key injection

Once the compat layer has processed an incoming message it calls
:func:`to_normalized_ingress_event` to produce a
:class:`NormalizedIngressEvent`.  All internal handlers consume *this*
contract rather than raw AIP dicts or transport-level objects.  This means

* **internal code never branches on legacy type strings**
* **internal code never needs to check ``version``**
* **trace_id is always guaranteed to be non-empty**

Relationship to AIPMessage
--------------------------
:class:`~galaxy_gateway.protocol.aip_v3.AIPMessage` is the Pydantic schema
used for *protocol parsing and validation* at the transport layer.
:class:`NormalizedIngressEvent` is the *runtime-internal representation*
consumed by handlers, routers, and service layers.  The two are connected by
:func:`from_aip_message` and :func:`from_normalized_dict`.

Usage::

    from galaxy_gateway.protocol.normalized_ingress_event import (
        NormalizedIngressEvent,
        IngressEventKind,
        to_normalized_ingress_event,
        from_aip_message,
    )
    from galaxy_gateway.protocol.compat import parse_message_compat

    aip_msg = parse_message_compat(raw_text)
    event = from_aip_message(aip_msg)
    # event.kind is always a canonical IngressEventKind
    # event.trace_id is always non-empty

See ``docs/INGRESS_NORMALIZATION_CONTRACT.md`` for the full specification.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# IngressEventKind — canonical message kind vocabulary
# ---------------------------------------------------------------------------


class IngressEventKind:
    """Canonical ingress event kind strings.

    These correspond to the canonical AIP v3 ``MessageType`` wire-format values
    as defined in :class:`~galaxy_gateway.protocol.aip_v3.MessageType`.
    After all legacy aliases have been resolved by the compat layer, internal
    code must only branch on these constants.

    Note: ``DEVICE_HEARTBEAT`` maps to the canonical wire string ``"heartbeat"``
    (not ``"device_heartbeat"``) to match the AIP v3 ``MessageType.DEVICE_HEARTBEAT``
    enum value.
    """

    # Device lifecycle
    DEVICE_REGISTER: str = "device_register"
    DEVICE_HEARTBEAT: str = "heartbeat"       # wire value: MessageType.DEVICE_HEARTBEAT
    DEVICE_STATUS: str = "device_status"
    DEVICE_DISCONNECT: str = "device_unregister"

    # Task lifecycle
    TASK_SUBMIT: str = "task_submit"
    TASK_RESULT: str = "task_result"
    TASK_CANCEL: str = "task_cancel"

    # Commands
    COMMAND: str = "command"
    COMMAND_RESULT: str = "command_result"

    # High-level autonomous tasks
    GOAL_EXECUTION: str = "goal_execution"
    PARALLEL_SUBTASK: str = "parallel_subtask"
    PARALLEL_RESULT: str = "parallel_result"

    # System events
    CAPABILITY_REPORT: str = "capability_report"
    AGENT_STATUS: str = "agent_status"
    DELEGATED_EXECUTION_SIGNAL: str = "delegated_execution_signal"
    FILE_TRANSFER: str = "file_transfer"
    PEER_ANNOUNCE: str = "peer_announce"
    PEER_EXCHANGE: str = "peer_exchange"
    MESH_TOPOLOGY: str = "mesh_topology"
    WAKE_EVENT: str = "wake_event"

    # Goal execution results (Android uplink)
    GOAL_EXECUTION_RESULT: str = "goal_execution_result"
    # Android error-path alias — maps to the same handler as GOAL_EXECUTION_RESULT
    GOAL_RESULT: str = "goal_result"

    # Handoff protocol uplink wire types (Android → V2 gateway)
    # PR-02-V2 / PR-03-V2: these are canonical Android business result messages.
    HANDOFF_ACK: str = "handoff_ack"
    HANDOFF_RESULT: str = "handoff_result"
    HANDOFF_FAILURE: str = "handoff_failure"
    HANDOFF_ENVELOPE_V2_RESULT: str = "handoff_envelope_v2_result"

    # Android Runtime-State Transparency Uplink (PR-RT)
    # Both kinds carry structured Android runtime truth into V2 via the gateway.
    # They are canonical Android domain messages and are routed through
    # android_bridge → core.android_device_state_store.
    DEVICE_STATE_SNAPSHOT: str = "device_state_snapshot"
    DEVICE_EXECUTION_EVENT: str = "device_execution_event"

    # Unknown / unrecognised
    UNKNOWN: str = "unknown"

    _ALL = {
        DEVICE_REGISTER, DEVICE_HEARTBEAT, DEVICE_STATUS, DEVICE_DISCONNECT,
        TASK_SUBMIT, TASK_RESULT, TASK_CANCEL,
        COMMAND, COMMAND_RESULT,
        GOAL_EXECUTION, PARALLEL_SUBTASK, PARALLEL_RESULT,
        CAPABILITY_REPORT, AGENT_STATUS, DELEGATED_EXECUTION_SIGNAL,
        FILE_TRANSFER, PEER_ANNOUNCE, PEER_EXCHANGE, MESH_TOPOLOGY, WAKE_EVENT,
        GOAL_EXECUTION_RESULT, GOAL_RESULT,
        HANDOFF_ACK, HANDOFF_RESULT, HANDOFF_FAILURE, HANDOFF_ENVELOPE_V2_RESULT,
        DEVICE_STATE_SNAPSHOT, DEVICE_EXECUTION_EVENT,
        UNKNOWN,
    }

    @classmethod
    def normalise(cls, raw: Optional[str]) -> str:
        """Return a canonical kind string.

        If *raw* is already a known canonical kind it is returned unchanged.
        Otherwise ``'unknown'`` is returned.
        """
        if raw is None:
            return cls.UNKNOWN
        lower = str(raw).lower()
        return lower if lower in cls._ALL else cls.UNKNOWN


# ---------------------------------------------------------------------------
# Canonical Normalized Ingress Event
# ---------------------------------------------------------------------------


class NormalizedIngressEvent(BaseModel):
    """Canonical ingress event produced by the gateway normalization layer.

    All fields that were injected or normalised by the compat layer are
    guaranteed to be non-None and non-empty.  Handlers that consume this
    contract do not need to handle missing trace_id, missing route_mode, or
    legacy type aliases.

    Required fields
    ---------------
    ``event_id``, ``kind``, ``device_id``, ``trace_id``.

    All other fields have sensible defaults.
    """

    # ── Ingress identity ─────────────────────────────────────────────────────
    event_id: str = Field(
        default_factory=lambda: f"evt_{uuid.uuid4().hex[:16]}",
        description="Unique identifier for this ingress event (generated at normalization).",
    )
    kind: str = Field(
        description=(
            "Canonical ingress event kind — always a known "
            ":class:`IngressEventKind` string after normalization."
        ),
    )
    device_id: str = Field(
        default="unknown",
        description="Stable device identifier from the incoming message.",
    )

    # ── Tracing / routing ────────────────────────────────────────────────────
    trace_id: str = Field(
        description=(
            "Distributed trace identifier injected by the compat layer.  "
            "Always non-empty."
        ),
    )
    route_mode: str = Field(
        default="cross_device",
        description=(
            "Routing mode injected by the compat layer.  "
            "Typical values: 'cross_device', 'local', 'broadcast'."
        ),
    )
    runtime_session_id: Optional[str] = Field(
        default=None,
        description="Runtime session identifier injected by the compat layer.",
    )
    idempotency_key: Optional[str] = Field(
        default=None,
        description="Idempotency key injected by the compat layer.",
    )

    # ── Task / message linkage ───────────────────────────────────────────────
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier carried in the incoming message, if any.",
    )
    message_id: Optional[str] = Field(
        default=None,
        description="Message-level identifier from the incoming message, if any.",
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Correlation identifier for request-response pairing, if any.",
    )

    # ── Protocol provenance ──────────────────────────────────────────────────
    aip_version: str = Field(
        default="3.0",
        description=(
            "Detected AIP protocol version of the original message after "
            "normalization (always '3.0' because the compat layer upgrades "
            "v1/v2 messages)."
        ),
    )
    original_type: Optional[str] = Field(
        default=None,
        description=(
            "Raw 'type' string from the incoming message before normalization.  "
            "Useful for debugging.  Internal code must not branch on this field."
        ),
    )

    # ── Timing ───────────────────────────────────────────────────────────────
    ingress_ts: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this event was normalized at the gateway edge.",
    )

    # ── Payload ──────────────────────────────────────────────────────────────
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Structured payload from the incoming message.  The shape varies "
            "by kind but is always a plain dict (never None)."
        ),
    )
    extra_fields: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Non-schema fields present in the incoming message that are not "
            "covered by the AIPMessage Pydantic schema.  Preserved here so "
            "that downstream handlers can access platform metadata etc."
        ),
    )

    model_config = {"populate_by_name": True}

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
    def from_dict(cls, data: Dict[str, Any]) -> "NormalizedIngressEvent":
        """Construct from a plain dict (e.g. after JSON deserialisation)."""
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Builder: from AIPMessage (primary production adapter)
# ---------------------------------------------------------------------------


def from_aip_message(message: Any, *, extra_fields: Optional[Dict[str, Any]] = None) -> NormalizedIngressEvent:
    """Build a :class:`NormalizedIngressEvent` from an
    :class:`~galaxy_gateway.protocol.aip_v3.AIPMessage`.

    This is the primary production adapter.  It is called by
    :func:`to_normalized_ingress_event` and is also available directly for
    code that has already parsed an AIPMessage.

    Parameters
    ----------
    message:
        An :class:`~galaxy_gateway.protocol.aip_v3.AIPMessage` instance.
    extra_fields:
        Optional dict of non-schema fields captured before Pydantic parsing
        (e.g. from :func:`~galaxy_gateway.protocol.compat.normalise_to_v3_dict`).
    """
    try:
        # kind
        raw_type = getattr(message, "type", None)
        if raw_type is None:
            kind = IngressEventKind.UNKNOWN
            original_type = None
        elif hasattr(raw_type, "value"):
            kind = IngressEventKind.normalise(str(raw_type.value))
            original_type = str(raw_type.value)
        else:
            s = str(raw_type)
            kind = IngressEventKind.normalise(s)
            original_type = s

        device_id = str(getattr(message, "device_id", "") or "unknown")

        # trace/routing fields — may be in message.payload or top-level
        payload_raw = getattr(message, "payload", None) or {}
        if not isinstance(payload_raw, dict):
            payload_raw = {}

        trace_id = (
            str(getattr(message, "trace_id", "") or payload_raw.get("trace_id", "") or "")
        )
        if not trace_id:
            trace_id = f"trace_{uuid.uuid4().hex[:12]}"

        route_mode = (
            str(getattr(message, "route_mode", "") or payload_raw.get("route_mode", "") or "cross_device")
        )

        runtime_session_id = (
            str(getattr(message, "runtime_session_id", "") or payload_raw.get("runtime_session_id", "") or "")
        ) or None

        idempotency_key = (
            str(getattr(message, "idempotency_key", "") or payload_raw.get("idempotency_key", "") or "")
        ) or None

        task_id_raw = getattr(message, "task_id", None) or payload_raw.get("task_id")
        task_id = str(task_id_raw) if task_id_raw else None

        message_id_raw = getattr(message, "message_id", None)
        message_id = str(message_id_raw) if message_id_raw else None

        correlation_id_raw = getattr(message, "correlation_id", None)
        correlation_id = str(correlation_id_raw) if correlation_id_raw else None

        # version
        version_raw = getattr(message, "version", "3.0")
        aip_version = str(version_raw) if version_raw else "3.0"

        # Clean up tracing fields from payload to avoid duplication
        payload = {
            k: v for k, v in payload_raw.items()
            if k not in {"trace_id", "route_mode", "runtime_session_id", "idempotency_key"}
        }

        return NormalizedIngressEvent(
            kind=kind,
            device_id=device_id,
            trace_id=trace_id,
            route_mode=route_mode,
            runtime_session_id=runtime_session_id,
            idempotency_key=idempotency_key,
            task_id=task_id,
            message_id=message_id,
            correlation_id=correlation_id,
            aip_version=aip_version,
            original_type=original_type,
            payload=payload,
            extra_fields=dict(extra_fields or {}),
        )
    except Exception:
        return NormalizedIngressEvent(
            kind=IngressEventKind.UNKNOWN,
            trace_id=f"trace_{uuid.uuid4().hex[:12]}",
        )


# ---------------------------------------------------------------------------
# Builder: from a normalized v3 dict (compat layer output)
# ---------------------------------------------------------------------------


def from_normalized_dict(data: Dict[str, Any]) -> NormalizedIngressEvent:
    """Build a :class:`NormalizedIngressEvent` from a v3-normalised dict as
    produced by
    :func:`~galaxy_gateway.protocol.compat.normalise_to_v3_dict`.

    Use this adapter when you have the raw dict (before Pydantic parsing) and
    want to preserve extra non-schema fields.

    Parameters
    ----------
    data:
        Output of ``normalise_to_v3_dict(raw_message)``.  Must have
        ``version == "3.0"`` and canonical ``type`` strings.
    """
    try:
        raw_type = str(data.get("type", "") or "")
        kind = IngressEventKind.normalise(raw_type)

        device_id = str(data.get("device_id", "unknown") or "unknown")

        trace_id = str(data.get("trace_id", "") or "")
        if not trace_id:
            trace_id = f"trace_{uuid.uuid4().hex[:12]}"

        route_mode = str(data.get("route_mode", "cross_device") or "cross_device")
        runtime_session_id = str(data.get("runtime_session_id", "") or "") or None
        idempotency_key = str(data.get("idempotency_key", "") or "") or None

        task_id_raw = data.get("task_id")
        task_id = str(task_id_raw) if task_id_raw else None

        message_id_raw = data.get("message_id")
        message_id = str(message_id_raw) if message_id_raw else None

        correlation_id_raw = data.get("correlation_id")
        correlation_id = str(correlation_id_raw) if correlation_id_raw else None

        aip_version = str(data.get("version", "3.0") or "3.0")

        payload = dict(data.get("payload") or {})

        # Extra fields: everything not covered by the canonical schema
        _schema_keys = {
            "type", "version", "device_id", "trace_id", "route_mode",
            "runtime_session_id", "idempotency_key", "task_id", "message_id",
            "correlation_id", "timestamp", "payload",
        }
        extra_fields = {k: v for k, v in data.items() if k not in _schema_keys}

        return NormalizedIngressEvent(
            kind=kind,
            device_id=device_id,
            trace_id=trace_id,
            route_mode=route_mode,
            runtime_session_id=runtime_session_id,
            idempotency_key=idempotency_key,
            task_id=task_id,
            message_id=message_id,
            correlation_id=correlation_id,
            aip_version=aip_version,
            original_type=raw_type or None,
            payload=payload,
            extra_fields=extra_fields,
        )
    except Exception:
        return NormalizedIngressEvent(
            kind=IngressEventKind.UNKNOWN,
            trace_id=f"trace_{uuid.uuid4().hex[:12]}",
        )


# ---------------------------------------------------------------------------
# Primary public entry point
# ---------------------------------------------------------------------------


def to_normalized_ingress_event(
    raw: Any,
    *,
    strict: bool = False,
) -> NormalizedIngressEvent:
    """Normalize a raw incoming message (string, dict, or AIPMessage) into a
    :class:`NormalizedIngressEvent`.

    This is the **single entry point** for converting gateway ingress into the
    canonical internal representation.  It calls the compat layer internally
    so callers do not need to import anything from
    :mod:`galaxy_gateway.protocol.compat`.

    Parameters
    ----------
    raw:
        Raw JSON string, already-decoded dict, or an
        :class:`~galaxy_gateway.protocol.aip_v3.AIPMessage` instance.
    strict:
        When ``True``, raise :class:`~galaxy_gateway.protocol.compat.AIPVersionError`
        if the message version is below 3.0.  Defaults to ``False``
        (compat mode: v1/v2 are silently normalised).

    Returns
    -------
    NormalizedIngressEvent
        Always returns a valid event.  On parse failure, returns a minimal
        event with ``kind='unknown'`` and a generated ``trace_id``.
    """
    try:
        from galaxy_gateway.protocol.compat import (
            normalise_to_v3_dict,
            parse_message_strict,
        )

        if hasattr(raw, "type") and hasattr(raw, "device_id"):
            # Already an AIPMessage — no need to reparse
            return from_aip_message(raw)

        if strict:
            # parse_message_strict will raise AIPVersionError for < v3
            aip_msg = parse_message_strict(raw)
            return from_aip_message(aip_msg)

        # Compat path: normalise to v3 dict first (preserves extra fields)
        v3_dict = normalise_to_v3_dict(raw)
        event = from_normalized_dict(v3_dict)
        return event

    except Exception:
        return NormalizedIngressEvent(
            kind=IngressEventKind.UNKNOWN,
            trace_id=f"trace_{uuid.uuid4().hex[:12]}",
        )
