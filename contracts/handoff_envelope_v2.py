"""contracts/handoff_envelope_v2.py
====================================
Handoff Envelope v2 — PR-31.

This module defines the **canonical Handoff Envelope v2 contract**: a single,
serialisable schema that answers the question:

    *"What is the canonical cross-device runtime handoff package that one
    runtime host sends to another?"*

It upgrades the narrow bridge payload used by
``galaxy_gateway.agent_bridge.HandoffContract`` into a stable, richly-typed
envelope suitable for:
- mesh membership (PR-32)
- mesh session coordination (PR-33)
- target runtime local takeover (PR-34)
- multi-device orchestration

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — :meth:`HandoffEnvelopeV2.to_dict` and
  :meth:`HandoffEnvelopeV2.to_json` produce stable, round-trippable JSON.
- **Graceful defaults** — all fields beyond ``handoff_id`` and
  ``trace_id`` are optional; adapters catch exceptions and degrade
  gracefully.
- **No UI-specific semantics** — suitable for runtime/projection/handoff/API
  use.
- **Stable field names** — downstream consumers can rely on the field names
  defined here without fear of silent renaming.
- **Compatible with current bridge path** — the legacy
  :class:`~galaxy_gateway.agent_bridge.HandoffContract` can be projected into
  this envelope via :func:`from_legacy_handoff_contract` and back via
  :func:`to_legacy_bridge_payload`.

Usage::

    from contracts.handoff_envelope_v2 import (
        HandoffEnvelopeV2,
        HandoffSourceSummary,
        HandoffTargetSummary,
        HandoffAgentSpec,
        HandoffTaskSpec,
        HandoffSessionContext,
        LocalTakeoverPolicy,
        HandoffReturnContract,
        build_handoff_envelope_v2,
        from_legacy_handoff_contract,
        from_bridge_inputs,
        to_legacy_bridge_payload,
    )

    # Build from legacy HandoffContract
    from galaxy_gateway.agent_bridge import HandoffContract
    legacy = HandoffContract(trace_id="t1", task={"tool_name": "screenshot"})
    envelope = from_legacy_handoff_contract(legacy)
    payload = envelope.to_dict()

    # Build from scratch
    envelope = build_handoff_envelope_v2(
        trace_id="t2",
        source_device_id="phone_001",
        target_device_id="tablet_002",
        task={"tool_name": "open_app", "args": {"app": "Chrome"}},
    )

    # Convert back to legacy payload for bridge POST
    legacy_payload = to_legacy_bridge_payload(envelope)

See ``docs/HANDOFF_ENVELOPE_V2.md`` for the full specification.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from contracts.source_posture_contract import _normalise_posture_hint


# ---------------------------------------------------------------------------
# Sub-contract: source runtime summary
# ---------------------------------------------------------------------------


class HandoffSourceSummary(BaseModel):
    """Summary of the device / runtime that is *initiating* this handoff.

    Fields are all optional to support partially-available metadata
    (e.g. legacy callers that do not yet carry full device identity).
    """

    device_id: Optional[str] = Field(
        default=None,
        description="Stable identifier of the source physical device.",
    )
    runtime_id: Optional[str] = Field(
        default=None,
        description="Identifier of the source runtime instance, if known.",
    )
    platform: Optional[str] = Field(
        default=None,
        description=(
            "Platform family, e.g. 'android', 'windows', 'macos', 'linux'."
        ),
    )
    runtime_version: Optional[str] = Field(
        default=None,
        description="Version string of the source runtime, if known.",
    )
    capability_summary: List[str] = Field(
        default_factory=list,
        description="Flat list of capability names exposed by the source device.",
    )
    source_runtime_posture: str = Field(
        default="control_only",
        description=(
            "Source-device runtime participation posture for this handoff. "
            "Must be 'control_only' or 'join_runtime'. "
            "Mirrors the field defined in contracts.source_posture_contract."
        ),
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra metadata from the source.",
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Sub-contract: target runtime summary
# ---------------------------------------------------------------------------


class HandoffTargetSummary(BaseModel):
    """Summary of the device / runtime that is *receiving* this handoff.

    Fields are all optional to support partially-available metadata.
    """

    device_id: Optional[str] = Field(
        default=None,
        description="Stable identifier of the target physical device.",
    )
    runtime_id: Optional[str] = Field(
        default=None,
        description="Identifier of the target runtime instance, if known.",
    )
    platform: Optional[str] = Field(
        default=None,
        description="Platform family of the target device.",
    )
    runtime_version: Optional[str] = Field(
        default=None,
        description="Version string of the target runtime, if known.",
    )
    capability_summary: List[str] = Field(
        default_factory=list,
        description="Flat list of capability names available on the target.",
    )
    handoff_endpoint: Optional[str] = Field(
        default=None,
        description=(
            "URL of the target's handoff endpoint, e.g. 'http://tablet:9000/handoff'."
        ),
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra metadata for the target.",
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Sub-contract: agent spec
# ---------------------------------------------------------------------------


class HandoffAgentSpec(BaseModel):
    """Specification of the agent being dispatched to the target runtime.

    This describes *which agent* is expected to run on the target device,
    its role, and any participation hints needed to set it up.
    """

    agent_id: Optional[str] = Field(
        default=None,
        description="Stable identifier of the agent being dispatched.",
    )
    agent_type: Optional[str] = Field(
        default=None,
        description=(
            "Type/class of the agent, e.g. 'executor', 'observer', 'coordinator'."
        ),
    )
    agent_role: Optional[str] = Field(
        default=None,
        description="High-level role hint, e.g. 'primary', 'fallback', 'recovery'.",
    )
    required_capabilities: List[str] = Field(
        default_factory=list,
        description="Capabilities the target runtime must provide for this agent.",
    )
    participation_hints: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value hints forwarded to the target agent.",
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Sub-contract: task spec
# ---------------------------------------------------------------------------


class HandoffTaskSpec(BaseModel):
    """Specification of the task being handed off to the target runtime.

    This is the structured representation of the *work* the target agent
    should perform once it has accepted the handoff.
    """

    task_id: Optional[str] = Field(
        default=None,
        description="Stable task identifier (from TaskEnvelope when available).",
    )
    tool_name: Optional[str] = Field(
        default=None,
        description="Name of the tool/skill to invoke on the target.",
    )
    args: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments to pass to the tool.",
    )
    targets: List[str] = Field(
        default_factory=list,
        description="Target resource identifiers (e.g. device IDs, UI elements).",
    )
    source: Optional[str] = Field(
        default=None,
        description="Originating source identifier, forwarded as-is.",
    )
    raw_task: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "The original unmodified task payload from the legacy bridge, "
            "preserved for backward compatibility."
        ),
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Sub-contract: session context
# ---------------------------------------------------------------------------


class HandoffSessionContext(BaseModel):
    """Session and context metadata forwarded to the target runtime.

    Mirrors the ``session`` dict in the legacy bridge but provides a typed,
    stable schema for downstream consumers.
    """

    session_id: Optional[str] = Field(
        default=None,
        description="Active session identifier, if this handoff belongs to a session.",
    )
    turn_id: Optional[str] = Field(
        default=None,
        description="Current conversation/task turn identifier.",
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Authenticated user identifier associated with this session.",
    )
    trace_context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Distributed trace context (trace_id, span_id, parent_span_id, …).",
    )
    raw_session: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "The original unmodified session dict from the legacy bridge, "
            "preserved for backward compatibility."
        ),
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra session metadata.",
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Sub-contract: local takeover policy
# ---------------------------------------------------------------------------


class LocalTakeoverPolicy(BaseModel):
    """Policy hints for local takeover behaviour on the target device.

    These are *advisory* hints; the target runtime is responsible for
    enforcing them.  They are provided here so that the source can express
    its intent clearly without requiring a deep runtime redesign in this PR.
    """

    allow_local_takeover: bool = Field(
        default=True,
        description=(
            "Whether the target runtime may take over the local execution "
            "loop (UI control, sensor access, etc.)."
        ),
    )
    require_ack_before_takeover: bool = Field(
        default=False,
        description=(
            "When True the source expects an acknowledgement from the target "
            "before it begins local execution."
        ),
    )
    max_takeover_duration_s: Optional[float] = Field(
        default=None,
        ge=0.0,
        description=(
            "Maximum wall-clock time the target is permitted to hold the "
            "takeover before releasing, in seconds.  None = no hard limit."
        ),
    )
    release_on_completion: bool = Field(
        default=True,
        description=(
            "When True the target should release local control as soon as "
            "the task completes."
        ),
    )
    fallback_on_timeout: bool = Field(
        default=True,
        description=(
            "When True the target should gracefully fall back to its own "
            "local coordinator if the takeover window expires."
        ),
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Sub-contract: return contract
# ---------------------------------------------------------------------------


class HandoffReturnContract(BaseModel):
    """Contract describing how the target should return results to the source.

    Specifies the expected response format and the channels through which
    results should be delivered.
    """

    callback_channel: str = Field(
        default="ws",
        description=(
            "Preferred channel for the result callback: "
            "'ws' | 'webrtc' | 'nats' | 'http'."
        ),
    )
    callback_url: Optional[str] = Field(
        default=None,
        description=(
            "Explicit callback URL for HTTP-based return paths.  "
            "Used when callback_channel='http'."
        ),
    )
    expect_ack: bool = Field(
        default=False,
        description="When True the source expects an explicit acknowledgement.",
    )
    expect_result: bool = Field(
        default=True,
        description="When True the source expects a structured result payload.",
    )
    result_schema_hint: Optional[str] = Field(
        default=None,
        description=(
            "Optional hint describing the expected result schema, "
            "e.g. 'screenshot_result_v1'."
        ),
    )

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Top-level canonical envelope
# ---------------------------------------------------------------------------


class HandoffEnvelopeV2(BaseModel):
    """Canonical Handoff Envelope v2 contract.

    This is the stable, richly-typed cross-device runtime-handoff package
    that one runtime host sends to another.  It upgrades the narrow bridge
    payload (``galaxy_gateway.agent_bridge.HandoffContract``) with:

    - explicit source / target runtime and device identity
    - structured agent / task / session context as first-class bundles
    - local takeover policy hints
    - structured return expectations

    All fields beyond ``handoff_id`` and ``trace_id`` are optional so that
    adapters from partial data sources can produce a valid envelope.

    Fields
    ------
    handoff_id:
        Stable unique identifier for this handoff event.
        Auto-generated as a UUID-hex if not supplied.
    trace_id:
        Trace identifier propagated from the originating request.  Required
        for deduplication and distributed tracing.
    task_id:
        Optional task identifier when the handoff originates from a
        TaskEnvelope.
    session_id:
        Optional session identifier when the handoff belongs to a
        multi-step session.
    source_device_id:
        Stable identifier of the device *sending* this handoff.
    target_device_id:
        Stable identifier of the device *receiving* this handoff.
    source_runtime_id:
        Optional identifier of the source runtime instance.
    target_runtime_id:
        Optional identifier of the target runtime instance.
    source:
        Structured :class:`HandoffSourceSummary` sub-contract.
    target:
        Structured :class:`HandoffTargetSummary` sub-contract.
    agent_spec:
        Specification of the agent being dispatched.
    task_spec:
        Specification of the task to execute on the target.
    session_context:
        Session and context metadata forwarded to the target.
    capability:
        Primary capability required by the task (legacy bridge field,
        preserved for backward compatibility).
    exec_mode:
        Execution mode hint: "local" | "remote" | "both".
    route_mode:
        AIP v3 route mode: "direct" | "broadcast" | …
    callback_channel:
        Preferred response channel (legacy bridge field, preserved).
    handoff_policy:
        Serialised governance policy dict (from
        ``core.agent_governance.handoff_policy.HandoffPolicy``).
    takeover_policy:
        Local takeover policy hints.
    return_contract:
        Structured return expectations.
    metadata:
        Arbitrary extra metadata; tolerant of partial or missing values.
    schema_version:
        Schema version marker.  Currently ``"v2"``.
    created_at:
        Unix timestamp when this envelope was created.
    """

    # Primary identity
    handoff_id: str = Field(
        default_factory=lambda: f"hev2_{uuid.uuid4().hex[:12]}",
        description="Stable unique identifier for this handoff event.",
    )
    trace_id: str = Field(
        default="",
        description="Trace identifier for deduplication and distributed tracing.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Optional task identifier from the originating TaskEnvelope.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional session identifier for multi-step sessions.",
    )

    # Device / runtime identity
    source_device_id: Optional[str] = Field(
        default=None,
        description="Stable identifier of the device sending this handoff.",
    )
    target_device_id: Optional[str] = Field(
        default=None,
        description="Stable identifier of the device receiving this handoff.",
    )
    source_runtime_id: Optional[str] = Field(
        default=None,
        description="Optional identifier of the source runtime instance.",
    )
    target_runtime_id: Optional[str] = Field(
        default=None,
        description="Optional identifier of the target runtime instance.",
    )

    # Structured sub-contracts
    source: HandoffSourceSummary = Field(
        default_factory=HandoffSourceSummary,
        description="Structured source device / runtime summary.",
    )
    target: HandoffTargetSummary = Field(
        default_factory=HandoffTargetSummary,
        description="Structured target device / runtime summary.",
    )
    agent_spec: HandoffAgentSpec = Field(
        default_factory=HandoffAgentSpec,
        description="Specification of the agent being dispatched.",
    )
    task_spec: HandoffTaskSpec = Field(
        default_factory=HandoffTaskSpec,
        description="Specification of the task to execute on the target.",
    )
    session_context: HandoffSessionContext = Field(
        default_factory=HandoffSessionContext,
        description="Session and context metadata forwarded to the target.",
    )

    # Source posture — stable cross-repo contract field (PR-533 / PR-1 unification)
    source_runtime_posture: str = Field(
        default="control_only",
        description=(
            "Source-device runtime participation posture for this handoff. "
            "Must be 'control_only' or 'join_runtime'. "
            "Canonical field name per SOURCE_POSTURE_CONTRACT_AUTHORITY."
        ),
    )

    # Legacy bridge fields (preserved for backward compatibility)
    capability: str = Field(
        default="",
        description="Primary capability required by the task (legacy bridge field).",
    )
    exec_mode: str = Field(
        default="both",
        description="Execution mode hint: 'local' | 'remote' | 'both'.",
    )
    route_mode: str = Field(
        default="direct",
        description="AIP v3 route mode, e.g. 'direct' or 'broadcast'.",
    )
    callback_channel: str = Field(
        default="ws",
        description="Preferred response channel (legacy bridge field).",
    )

    # Policy / return contracts
    handoff_policy: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Serialised governance policy dict from "
            "core.agent_governance.handoff_policy.HandoffPolicy."
        ),
    )
    takeover_policy: LocalTakeoverPolicy = Field(
        default_factory=LocalTakeoverPolicy,
        description="Local takeover policy hints for the target runtime.",
    )
    return_contract: HandoffReturnContract = Field(
        default_factory=HandoffReturnContract,
        description="Structured return expectations.",
    )

    # Metadata and schema versioning
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra metadata; tolerant of partial/missing values.",
    )
    schema_version: str = Field(
        default="v2",
        description="Schema version marker.  Currently 'v2'.",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this envelope was created.",
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
    def from_dict(cls, data: Dict[str, Any]) -> "HandoffEnvelopeV2":
        """Reconstruct a :class:`HandoffEnvelopeV2` from a plain dict."""
        return cls(**data)

    def to_compact_summary(self) -> Dict[str, Any]:
        """Return a compact projection-safe summary of this envelope.

        Suitable for logging, metrics projection, and bridge result annotation.
        Does not include the full task/session payload.
        """
        return {
            "handoff_id": self.handoff_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "source_device_id": self.source_device_id,
            "target_device_id": self.target_device_id,
            "source_runtime_id": self.source_runtime_id,
            "target_runtime_id": self.target_runtime_id,
            "source_runtime_posture": self.source_runtime_posture,
            "capability": self.capability,
            "exec_mode": self.exec_mode,
            "route_mode": self.route_mode,
            "callback_channel": self.callback_channel,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Adapter / builder functions
# ---------------------------------------------------------------------------


def from_legacy_handoff_contract(contract: Any) -> HandoffEnvelopeV2:
    """Build a :class:`HandoffEnvelopeV2` from a legacy
    ``galaxy_gateway.agent_bridge.HandoffContract``.

    This is the primary backward-compatibility adapter.  All fields that
    exist in the legacy contract are projected into the new envelope.
    Fields absent from the legacy contract are left at their defaults.

    Parameters
    ----------
    contract:
        A ``galaxy_gateway.agent_bridge.HandoffContract`` instance (or any
        object with the same field shape: ``trace_id``, ``task``,
        ``capability``, ``exec_mode``, ``route_mode``, ``session``,
        ``callback_channel``, and optionally ``task_id``).

    Returns
    -------
    HandoffEnvelopeV2
        Fully populated envelope.  Fields that cannot be mapped are left at
        their defaults.
    """
    try:
        trace_id = str(getattr(contract, "trace_id", "") or "")
        task_id = str(getattr(contract, "task_id", "") or "") or None
        capability = str(getattr(contract, "capability", "") or "")
        exec_mode = str(getattr(contract, "exec_mode", "both") or "both")
        route_mode = str(getattr(contract, "route_mode", "direct") or "direct")
        callback_channel = str(getattr(contract, "callback_channel", "ws") or "ws")

        raw_task: Dict[str, Any] = {}
        task_obj = getattr(contract, "task", None)
        if isinstance(task_obj, dict):
            raw_task = dict(task_obj)

        raw_session: Dict[str, Any] = {}
        session_obj = getattr(contract, "session", None)
        if isinstance(session_obj, dict):
            raw_session = dict(session_obj)

        # Project task fields into HandoffTaskSpec
        task_spec = HandoffTaskSpec(
            task_id=task_id or raw_task.get("task_id"),
            tool_name=raw_task.get("tool_name"),
            args=raw_task.get("args") if isinstance(raw_task.get("args"), dict) else {},
            targets=list(raw_task.get("targets") or []),
            source=raw_task.get("source"),
            raw_task=raw_task,
        )

        # Project session into HandoffSessionContext
        session_context = HandoffSessionContext(
            session_id=raw_session.get("session_id"),
            turn_id=raw_session.get("turn_id"),
            user_id=raw_session.get("user_id"),
            raw_session=raw_session,
        )

        return HandoffEnvelopeV2(
            trace_id=trace_id,
            task_id=task_id,
            capability=capability,
            exec_mode=exec_mode,
            route_mode=route_mode,
            callback_channel=callback_channel,
            task_spec=task_spec,
            session_context=session_context,
            return_contract=HandoffReturnContract(callback_channel=callback_channel),
        )
    except Exception:  # noqa: BLE001 — degrade gracefully
        return HandoffEnvelopeV2(
            trace_id=str(getattr(contract, "trace_id", "") or ""),
        )


def from_bridge_inputs(
    *,
    trace_id: str,
    task: Dict[str, Any],
    capability: str = "",
    exec_mode: str = "both",
    route_mode: str = "direct",
    session: Optional[Dict[str, Any]] = None,
    callback_channel: str = "ws",
    task_id: Optional[str] = None,
    source_device_id: Optional[str] = None,
    target_device_id: Optional[str] = None,
    source_runtime_id: Optional[str] = None,
    target_runtime_id: Optional[str] = None,
    source_runtime_posture: Optional[str] = None,
    handoff_policy: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> HandoffEnvelopeV2:
    """Build a :class:`HandoffEnvelopeV2` directly from bridge call-site inputs.

    Intended for use in ``AgentBridge.handoff()`` or any caller that has
    the raw bridge parameters available (e.g. after calling
    ``handoff_contract_from_envelope``).

    Parameters
    ----------
    trace_id:
        Trace identifier for deduplication and logging.
    task:
        The raw task payload dict.
    capability:
        Primary capability required by the task.
    exec_mode:
        Execution mode: "local" | "remote" | "both".
    route_mode:
        AIP v3 route mode.
    session:
        Session context dict forwarded to the runtime.
    callback_channel:
        Preferred response channel.
    task_id:
        Optional task identifier from TaskEnvelope.
    source_device_id:
        Stable identifier of the source device, if known.
    target_device_id:
        Stable identifier of the target device, if known.
    source_runtime_id:
        Optional source runtime instance identifier.
    target_runtime_id:
        Optional target runtime instance identifier.
    source_runtime_posture:
        Source-device runtime participation posture: 'control_only' or
        'join_runtime'.  Defaults to 'control_only'.
    handoff_policy:
        Serialised handoff policy dict.
    metadata:
        Arbitrary extra metadata.

    Returns
    -------
    HandoffEnvelopeV2
    """
    raw_session: Dict[str, Any] = dict(session or {})
    raw_task: Dict[str, Any] = dict(task or {})

    _effective_posture: str = _normalise_posture_hint(source_runtime_posture)

    task_spec = HandoffTaskSpec(
        task_id=task_id or raw_task.get("task_id"),
        tool_name=raw_task.get("tool_name"),
        args=raw_task.get("args") if isinstance(raw_task.get("args"), dict) else {},
        targets=list(raw_task.get("targets") or []),
        source=raw_task.get("source"),
        raw_task=raw_task,
    )

    session_context = HandoffSessionContext(
        session_id=raw_session.get("session_id"),
        turn_id=raw_session.get("turn_id"),
        user_id=raw_session.get("user_id"),
        raw_session=raw_session,
    )

    source_summary = HandoffSourceSummary(
        device_id=source_device_id,
        runtime_id=source_runtime_id,
        source_runtime_posture=_effective_posture,
    )
    target_summary = HandoffTargetSummary(device_id=target_device_id, runtime_id=target_runtime_id)

    return HandoffEnvelopeV2(
        trace_id=trace_id,
        task_id=task_id,
        source_device_id=source_device_id,
        target_device_id=target_device_id,
        source_runtime_id=source_runtime_id,
        target_runtime_id=target_runtime_id,
        source_runtime_posture=_effective_posture,
        source=source_summary,
        target=target_summary,
        task_spec=task_spec,
        session_context=session_context,
        capability=capability,
        exec_mode=exec_mode,
        route_mode=route_mode,
        callback_channel=callback_channel,
        handoff_policy=handoff_policy or {},
        return_contract=HandoffReturnContract(callback_channel=callback_channel),
        metadata=metadata or {},
    )


def to_legacy_bridge_payload(envelope: HandoffEnvelopeV2) -> Dict[str, Any]:
    """Convert a :class:`HandoffEnvelopeV2` back to a legacy bridge payload dict.

    The returned dict is compatible with the ``POST /handoff`` endpoint
    contract and with ``HandoffContract.to_dict()``.

    Parameters
    ----------
    envelope:
        A populated :class:`HandoffEnvelopeV2`.

    Returns
    -------
    dict
        A dict with keys ``trace_id``, ``task``, ``capability``,
        ``exec_mode``, ``route_mode``, ``session``, ``callback_channel``,
        and optionally ``task_id``.
    """
    payload: Dict[str, Any] = {
        "trace_id": envelope.trace_id,
        "task": envelope.task_spec.raw_task or {
            "task_id": envelope.task_spec.task_id,
            "tool_name": envelope.task_spec.tool_name,
            "args": envelope.task_spec.args,
            "targets": envelope.task_spec.targets,
            "source": envelope.task_spec.source,
        },
        "capability": envelope.capability,
        "exec_mode": envelope.exec_mode,
        "route_mode": envelope.route_mode,
        "session": envelope.session_context.raw_session,
        "callback_channel": envelope.callback_channel,
    }
    if envelope.task_id:
        payload["task_id"] = envelope.task_id
    return payload


def build_handoff_envelope_v2(
    *,
    trace_id: str = "",
    task: Optional[Dict[str, Any]] = None,
    capability: str = "",
    exec_mode: str = "both",
    route_mode: str = "direct",
    session: Optional[Dict[str, Any]] = None,
    callback_channel: str = "ws",
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    source_device_id: Optional[str] = None,
    target_device_id: Optional[str] = None,
    source_runtime_id: Optional[str] = None,
    target_runtime_id: Optional[str] = None,
    source_runtime_posture: Optional[str] = None,
    agent_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    agent_role: Optional[str] = None,
    handoff_policy: Optional[Dict[str, Any]] = None,
    allow_local_takeover: bool = True,
    require_ack_before_takeover: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> HandoffEnvelopeV2:
    """Convenience factory for building a :class:`HandoffEnvelopeV2`.

    Covers the most common construction patterns.  For more control,
    construct :class:`HandoffEnvelopeV2` directly.

    Parameters
    ----------
    trace_id:
        Trace identifier for deduplication and logging.
    task:
        The raw task payload dict.
    capability:
        Primary capability required by the task.
    exec_mode:
        Execution mode: "local" | "remote" | "both".
    route_mode:
        AIP v3 route mode.
    session:
        Session context dict forwarded to the runtime.
    callback_channel:
        Preferred response channel.
    task_id:
        Optional task identifier from TaskEnvelope.
    session_id:
        Optional session identifier.
    source_device_id:
        Stable identifier of the source device.
    target_device_id:
        Stable identifier of the target device.
    source_runtime_id:
        Optional source runtime instance identifier.
    target_runtime_id:
        Optional target runtime instance identifier.
    source_runtime_posture:
        Source-device runtime participation posture: 'control_only' or
        'join_runtime'.  Defaults to 'control_only'.
    agent_id:
        Optional agent identifier to dispatch.
    agent_type:
        Optional agent type hint.
    agent_role:
        Optional agent role hint.
    handoff_policy:
        Serialised handoff policy dict.
    allow_local_takeover:
        Whether the target may take over local execution.
    require_ack_before_takeover:
        Whether an ack is required before takeover begins.
    metadata:
        Arbitrary extra metadata.

    Returns
    -------
    HandoffEnvelopeV2
    """
    raw_task: Dict[str, Any] = dict(task or {})
    raw_session: Dict[str, Any] = dict(session or {})

    _effective_posture: str = _normalise_posture_hint(source_runtime_posture)

    task_spec = HandoffTaskSpec(
        task_id=task_id or raw_task.get("task_id"),
        tool_name=raw_task.get("tool_name"),
        args=raw_task.get("args") if isinstance(raw_task.get("args"), dict) else {},
        targets=list(raw_task.get("targets") or []),
        source=raw_task.get("source"),
        raw_task=raw_task,
    )

    session_context = HandoffSessionContext(
        session_id=session_id or raw_session.get("session_id"),
        turn_id=raw_session.get("turn_id"),
        user_id=raw_session.get("user_id"),
        raw_session=raw_session,
    )

    agent_spec = HandoffAgentSpec(
        agent_id=agent_id,
        agent_type=agent_type,
        agent_role=agent_role,
    )

    source_summary = HandoffSourceSummary(
        device_id=source_device_id,
        runtime_id=source_runtime_id,
        source_runtime_posture=_effective_posture,
    )
    target_summary = HandoffTargetSummary(
        device_id=target_device_id,
        runtime_id=target_runtime_id,
    )

    takeover_policy = LocalTakeoverPolicy(
        allow_local_takeover=allow_local_takeover,
        require_ack_before_takeover=require_ack_before_takeover,
    )

    return HandoffEnvelopeV2(
        trace_id=trace_id,
        task_id=task_id,
        session_id=session_id,
        source_device_id=source_device_id,
        target_device_id=target_device_id,
        source_runtime_id=source_runtime_id,
        target_runtime_id=target_runtime_id,
        source_runtime_posture=_effective_posture,
        source=source_summary,
        target=target_summary,
        agent_spec=agent_spec,
        task_spec=task_spec,
        session_context=session_context,
        capability=capability,
        exec_mode=exec_mode,
        route_mode=route_mode,
        callback_channel=callback_channel,
        handoff_policy=handoff_policy or {},
        takeover_policy=takeover_policy,
        return_contract=HandoffReturnContract(callback_channel=callback_channel),
        metadata=metadata or {},
    )


__all__ = [
    # Sub-contracts
    "HandoffSourceSummary",
    "HandoffTargetSummary",
    "HandoffAgentSpec",
    "HandoffTaskSpec",
    "HandoffSessionContext",
    "LocalTakeoverPolicy",
    "HandoffReturnContract",
    # Top-level envelope
    "HandoffEnvelopeV2",
    # Adapters / builders
    "from_legacy_handoff_contract",
    "from_bridge_inputs",
    "to_legacy_bridge_payload",
    "build_handoff_envelope_v2",
]
