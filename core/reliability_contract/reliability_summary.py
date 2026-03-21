#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.reliability_contract.reliability_summary
================================================

PR-19 (V4) — Reliability Contract & Delivery Semantics

Provides :class:`ReliabilitySummary` — a compact, public-safe,
JSON-serialisable summary that expresses the full reliability contract for a
given runtime message path or contract family.

Also provides:

* :data:`RELIABILITY_PATH_REGISTRY` — seed mappings for all known runtime
  paths (read-only dict from path key → :class:`ReliabilitySummary`).
* :func:`get_reliability_registry_snapshot` — return all summaries as a
  JSON-serialisable dict, degrading gracefully for unknown fields.
* :func:`get_summary_for_path` — look up a summary by path key.
* :func:`attach_reliability_to_projection` — attach the most-relevant
  summary to a projection dict additively.
* :func:`make_reliability_summary` — one-call builder from scalar inputs.

Seeded paths
-------------
The following representative real paths are seeded:

``task_envelope``
    :class:`~core.schemas.task_envelope.TaskEnvelope` orchestration dispatch.
    Delivery: DEDUP_REQUIRED; Ack: ACCEPTED; Timeout: COORDINATOR;
    Fallback: COORDINATOR.

``nats_task``
    NATS task dispatch/result path (``galaxy.task.*`` topics).
    Delivery: AT_LEAST_ONCE; Ack: ACCEPTED; Timeout: TRANSPORT;
    Fallback: COORDINATOR.

``agent_bridge_handoff``
    :class:`~galaxy_gateway.agent_bridge.HandoffContract` /
    :class:`~galaxy_gateway.agent_bridge.AgentBridge` runtime handoff.
    Delivery: AT_LEAST_ONCE; Ack: COMPLETED; Timeout: RUNTIME;
    Fallback: LOCAL_FALLBACK.

``command_router_remote``
    Remote agent dispatch via :class:`~core.command_router.CommandRouter`.
    Delivery: AT_LEAST_ONCE; Ack: ACCEPTED; Timeout: ROUTER;
    Fallback: REROUTE_OWNER.

``device_websocket``
    Device WebSocket execution path (device command channel).
    Delivery: BEST_EFFORT; Ack: NO_ACK; Timeout: TRANSPORT;
    Fallback: LOCAL_FALLBACK.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

from .ack_policy import AckPolicy, AckStage, NO_ACK_POLICY, ACCEPTED_ACK_POLICY, COMPLETED_ACK_POLICY
from .delivery_mode import DeliveryMode
from .fallback_owner import FallbackOwner
from .idempotency import (
    DeduplicationKey,
    NO_DEDUP_KEY,
    TASK_ENVELOPE_DEDUP_KEY,
    NATS_TASK_DEDUP_KEY,
    HANDOFF_DEDUP_KEY,
    COMMAND_ROUTER_DEDUP_KEY,
    DEVICE_WEBSOCKET_DEDUP_KEY,
)
from .retry_policy import (
    RetryPolicy,
    NO_RETRY_POLICY,
    TRANSPORT_RETRY_POLICY,
    RUNTIME_RETRY_POLICY,
    COORDINATOR_RETRY_POLICY,
)
from .timeout_owner import TimeoutOwner

__all__ = [
    "ReliabilitySummary",
    "UNKNOWN_RELIABILITY_SUMMARY",
    "RELIABILITY_PATH_REGISTRY",
    "get_reliability_registry_snapshot",
    "get_summary_for_path",
    "attach_reliability_to_projection",
    "make_reliability_summary",
    "list_known_paths",
]

SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# ReliabilitySummary dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ReliabilitySummary:
    """Compact, public-safe summary of the reliability contract for a path.

    This is the preferred type for API responses, projection payloads, and
    architectural documentation.  All fields degrade gracefully to safe
    sentinel values when metadata is unknown.

    Attributes
    ----------
    path_key:
        Stable identifier for the path or contract family, e.g.
        ``"task_envelope"`` or ``"nats_task"``.
    description:
        Human-readable description of what this path does.
    delivery_mode:
        The :class:`~.delivery_mode.DeliveryMode` for this path.
    ack_policy:
        The :class:`~.ack_policy.AckPolicy` governing ack posture.
    dedup_key:
        The :class:`~.idempotency.DeduplicationKey` defining dedup fields.
    retry_policy:
        The :class:`~.retry_policy.RetryPolicy` governing retry behaviour.
    timeout_owner:
        The :class:`~.timeout_owner.TimeoutOwner` responsible for timeouts.
    fallback_owner:
        The :class:`~.fallback_owner.FallbackOwner` responsible for fallback.
    source_module:
        Dotted Python module path that owns the primary implementation.
    notes:
        Optional caveats, known gaps, or future work items.
    schema_version:
        Schema version integer.
    """

    path_key: str = "unknown"
    description: str = ""
    delivery_mode: DeliveryMode = DeliveryMode.UNKNOWN
    ack_policy: AckPolicy = dataclasses.field(default_factory=lambda: NO_ACK_POLICY)
    dedup_key: DeduplicationKey = dataclasses.field(default_factory=lambda: NO_DEDUP_KEY)
    retry_policy: RetryPolicy = dataclasses.field(default_factory=lambda: NO_RETRY_POLICY)
    timeout_owner: TimeoutOwner = TimeoutOwner.UNSPECIFIED
    fallback_owner: FallbackOwner = FallbackOwner.UNSPECIFIED
    source_module: Optional[str] = None
    notes: Optional[str] = None
    schema_version: int = SCHEMA_VERSION

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "path_key": self.path_key,
            "description": self.description,
            "delivery_mode": self.delivery_mode.value,
            "ack_policy": self.ack_policy.to_dict(),
            "dedup_key": self.dedup_key.to_dict(),
            "retry_policy": self.retry_policy.to_dict(),
            "timeout_owner": self.timeout_owner.value,
            "fallback_owner": self.fallback_owner.value,
            "source_module": self.source_module,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReliabilitySummary":
        """Reconstruct from a serialised dict.  Unknown fields are silently defaulted."""
        raw_mode = data.get("delivery_mode", DeliveryMode.UNKNOWN.value)
        try:
            delivery_mode = DeliveryMode(raw_mode)
        except ValueError:
            delivery_mode = DeliveryMode.UNKNOWN

        raw_timeout = data.get("timeout_owner", TimeoutOwner.UNSPECIFIED.value)
        try:
            timeout_owner = TimeoutOwner(raw_timeout)
        except ValueError:
            timeout_owner = TimeoutOwner.UNSPECIFIED

        raw_fallback = data.get("fallback_owner", FallbackOwner.UNSPECIFIED.value)
        try:
            fallback_owner = FallbackOwner(raw_fallback)
        except ValueError:
            fallback_owner = FallbackOwner.UNSPECIFIED

        raw_ack = data.get("ack_policy", {})
        ack_policy = AckPolicy.from_dict(raw_ack) if raw_ack else NO_ACK_POLICY

        raw_dedup = data.get("dedup_key", {})
        dedup_key = DeduplicationKey.from_dict(raw_dedup) if raw_dedup else NO_DEDUP_KEY

        raw_retry = data.get("retry_policy", {})
        retry_policy = RetryPolicy.from_dict(raw_retry) if raw_retry else NO_RETRY_POLICY

        return cls(
            path_key=str(data.get("path_key", "unknown")),
            description=str(data.get("description", "")),
            delivery_mode=delivery_mode,
            ack_policy=ack_policy,
            dedup_key=dedup_key,
            retry_policy=retry_policy,
            timeout_owner=timeout_owner,
            fallback_owner=fallback_owner,
            source_module=data.get("source_module"),
            notes=data.get("notes"),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )


# ---------------------------------------------------------------------------
# Unknown / sentinel
# ---------------------------------------------------------------------------

#: Sentinel summary for paths whose reliability has not been classified.
UNKNOWN_RELIABILITY_SUMMARY = ReliabilitySummary(
    path_key="unknown",
    description="Reliability contract not yet classified for this path.",
    delivery_mode=DeliveryMode.UNKNOWN,
    ack_policy=NO_ACK_POLICY,
    dedup_key=NO_DEDUP_KEY,
    retry_policy=NO_RETRY_POLICY,
    timeout_owner=TimeoutOwner.UNSPECIFIED,
    fallback_owner=FallbackOwner.UNSPECIFIED,
    source_module=None,
    notes="Treat as BEST_EFFORT until classified.",
    schema_version=SCHEMA_VERSION,
)


# ---------------------------------------------------------------------------
# Seed path registry
# ---------------------------------------------------------------------------

#: Read-only mapping from stable path key to ReliabilitySummary.
#: Covers the five representative runtime paths required by PR-19.
RELIABILITY_PATH_REGISTRY: Dict[str, ReliabilitySummary] = {
    # ------------------------------------------------------------------
    # 1. TaskEnvelope orchestration dispatch
    # ------------------------------------------------------------------
    "task_envelope": ReliabilitySummary(
        path_key="task_envelope",
        description=(
            "TaskEnvelope / CommandEnvelope orchestration dispatch. "
            "The primary task ingestion path used by OpenClawd and the "
            "e2e orchestrator.  CommandEnvelope carries an idempotency_key "
            "which is validated by IdempotencyStore (Block-5) before the "
            "task is accepted."
        ),
        delivery_mode=DeliveryMode.DEDUP_REQUIRED,
        ack_policy=ACCEPTED_ACK_POLICY,
        dedup_key=TASK_ENVELOPE_DEDUP_KEY,
        retry_policy=COORDINATOR_RETRY_POLICY,
        timeout_owner=TimeoutOwner.COORDINATOR,
        fallback_owner=FallbackOwner.COORDINATOR,
        source_module="core.unified.command_envelope",
        notes=(
            "IdempotencyStore raises DuplicateCommandError on duplicate "
            "idempotency_key within the TTL window.  Retry is coordinator-owned "
            "via e2e_orchestrator / GlobalArbiter."
        ),
        schema_version=SCHEMA_VERSION,
    ),

    # ------------------------------------------------------------------
    # 2. NATS task dispatch / result path
    # ------------------------------------------------------------------
    "nats_task": ReliabilitySummary(
        path_key="nats_task",
        description=(
            "NATS task dispatch and result path (galaxy.task.* topics). "
            "Used by NATSTopics.publish_task_event() and consumed by "
            "gateway_nats_adapter.  NATS JetStream consumer groups provide "
            "at-least-once delivery within the broker."
        ),
        delivery_mode=DeliveryMode.AT_LEAST_ONCE,
        ack_policy=ACCEPTED_ACK_POLICY,
        dedup_key=NATS_TASK_DEDUP_KEY,
        retry_policy=TRANSPORT_RETRY_POLICY,
        timeout_owner=TimeoutOwner.TRANSPORT,
        fallback_owner=FallbackOwner.COORDINATOR,
        source_module="core.nats_bus",
        notes=(
            "NATS JetStream provides at-least-once at the broker level. "
            "Consumer-side dedup is application-layer responsibility. "
            "Fallback escalation to coordinator when NATS is unavailable."
        ),
        schema_version=SCHEMA_VERSION,
    ),

    # ------------------------------------------------------------------
    # 3. AgentBridge / HandoffContract runtime handoff
    # ------------------------------------------------------------------
    "agent_bridge_handoff": ReliabilitySummary(
        path_key="agent_bridge_handoff",
        description=(
            "HandoffContract / AgentBridge runtime handoff path. "
            "Used when an agent transfers execution ownership to a remote "
            "agent or device.  Carries trace_id + task_id for correlation. "
            "On failure, AgentBridge executes a local_fallback."
        ),
        delivery_mode=DeliveryMode.AT_LEAST_ONCE,
        ack_policy=COMPLETED_ACK_POLICY,
        dedup_key=HANDOFF_DEDUP_KEY,
        retry_policy=RUNTIME_RETRY_POLICY,
        timeout_owner=TimeoutOwner.RUNTIME,
        fallback_owner=FallbackOwner.LOCAL_FALLBACK,
        source_module="galaxy_gateway.agent_bridge",
        notes=(
            "AgentBridge.handoff() returns a result dict; on timeout or error, "
            "local_fallback() is invoked.  HandoffPolicy.handoff_timeout_hint_ms "
            "is the advisory timeout source (PR-18)."
        ),
        schema_version=SCHEMA_VERSION,
    ),

    # ------------------------------------------------------------------
    # 4. CommandRouter remote agent dispatch
    # ------------------------------------------------------------------
    "command_router_remote": ReliabilitySummary(
        path_key="command_router_remote",
        description=(
            "Remote agent dispatch via CommandRouter.dispatch_agent_remote(). "
            "Executes agent_deploy + agent_execute on a remote physical device. "
            "TaskRouter / CommandRouter owns the routing decision."
        ),
        delivery_mode=DeliveryMode.AT_LEAST_ONCE,
        ack_policy=ACCEPTED_ACK_POLICY,
        dedup_key=COMMAND_ROUTER_DEDUP_KEY,
        retry_policy=RUNTIME_RETRY_POLICY,
        timeout_owner=TimeoutOwner.ROUTER,
        fallback_owner=FallbackOwner.REROUTE_OWNER,
        source_module="core.command_router",
        notes=(
            "CommandRouter issues agent_deploy + agent_execute via "
            "DeviceCommunication.  On failure, reroute_owner (CommandRouter) "
            "may attempt an alternative device.  No built-in dedup enforcement."
        ),
        schema_version=SCHEMA_VERSION,
    ),

    # ------------------------------------------------------------------
    # 5. Device WebSocket execution path
    # ------------------------------------------------------------------
    "device_websocket": ReliabilitySummary(
        path_key="device_websocket",
        description=(
            "Device WebSocket execution command channel. "
            "Used to dispatch commands to connected Android / desktop devices "
            "over WebSocket.  Fire-and-forget semantics at the transport layer."
        ),
        delivery_mode=DeliveryMode.BEST_EFFORT,
        ack_policy=NO_ACK_POLICY,
        dedup_key=DEVICE_WEBSOCKET_DEDUP_KEY,
        retry_policy=NO_RETRY_POLICY,
        timeout_owner=TimeoutOwner.TRANSPORT,
        fallback_owner=FallbackOwner.LOCAL_FALLBACK,
        source_module="galaxy_gateway.transport.websocket_server",
        notes=(
            "WebSocket commands are fire-and-forget at the transport level. "
            "Device heartbeat / ack responses are application-layer signals; "
            "they do not constitute a transport-layer ack. "
            "Local fallback is initiated by AgentBridge if device is unreachable."
        ),
        schema_version=SCHEMA_VERSION,
    ),
}


# ---------------------------------------------------------------------------
# Registry access helpers
# ---------------------------------------------------------------------------


def get_summary_for_path(path_key: str) -> ReliabilitySummary:
    """Return the :class:`ReliabilitySummary` for *path_key*.

    Returns :data:`UNKNOWN_RELIABILITY_SUMMARY` when *path_key* is not
    registered, so callers never receive ``None``.

    Parameters
    ----------
    path_key:
        Stable path identifier, e.g. ``"task_envelope"``.

    Returns
    -------
    ReliabilitySummary
        The registered summary, or the unknown sentinel.
    """
    return RELIABILITY_PATH_REGISTRY.get(path_key, UNKNOWN_RELIABILITY_SUMMARY)


def list_known_paths() -> List[str]:
    """Return a sorted list of all registered path keys."""
    return sorted(RELIABILITY_PATH_REGISTRY.keys())


def get_reliability_registry_snapshot() -> Dict[str, Any]:
    """Return the full registry as a JSON-serialisable dict.

    Response shape
    --------------
    ::

        {
          "paths": {
            "<path_key>": { <ReliabilitySummary.to_dict() fields> },
            ...
          },
          "total_paths": <int>,
          "schema_version": 1
        }

    Degrades gracefully — individual path serialisation errors are caught
    and represented as ``{"error": "<message>"}`` entries so the snapshot
    always returns a complete payload.
    """
    paths: Dict[str, Any] = {}
    for key, summary in RELIABILITY_PATH_REGISTRY.items():
        try:
            paths[key] = summary.to_dict()
        except Exception as exc:  # pragma: no cover
            paths[key] = {"error": str(exc), "path_key": key}
    return {
        "paths": paths,
        "total_paths": len(paths),
        "schema_version": SCHEMA_VERSION,
    }


# ---------------------------------------------------------------------------
# Projection integration
# ---------------------------------------------------------------------------


def attach_reliability_to_projection(
    projection: Dict[str, Any],
    path_key: str = "task_envelope",
) -> Dict[str, Any]:
    """Attach a reliability summary to a projection dict additively.

    Follows the PR-13/PR-14/PR-17/PR-18 projection enrichment pattern.
    The original projection dict is **not** mutated; a new dict is returned.

    Parameters
    ----------
    projection:
        Existing projection payload (any dict).
    path_key:
        Path key to look up in the registry.  Defaults to
        ``"task_envelope"`` (the primary orchestration path).

    Returns
    -------
    dict
        A shallow copy of *projection* with a ``"reliability"`` key added.
    """
    summary = get_summary_for_path(path_key)
    result = dict(projection)
    result["reliability"] = summary.to_dict()
    return result


# ---------------------------------------------------------------------------
# One-call builder
# ---------------------------------------------------------------------------


def make_reliability_summary(
    path_key: str,
    description: str = "",
    delivery_mode: str = "unknown",
    ack_stage: str = "no_ack",
    timeout_owner: str = "unspecified",
    fallback_owner: str = "unspecified",
    dedup_fields: Optional[List[str]] = None,
    notes: Optional[str] = None,
    source_module: Optional[str] = None,
) -> ReliabilitySummary:
    """Build a :class:`ReliabilitySummary` from minimal scalar inputs.

    Unknown enum values are silently mapped to their ``UNKNOWN`` /
    ``UNSPECIFIED`` sentinels, enabling graceful degradation.

    Parameters
    ----------
    path_key:
        Stable identifier for the path.
    description:
        Human-readable description.
    delivery_mode:
        String value of :class:`~.delivery_mode.DeliveryMode`.
    ack_stage:
        String value of :class:`~.ack_policy.AckStage`.
    timeout_owner:
        String value of :class:`~.timeout_owner.TimeoutOwner`.
    fallback_owner:
        String value of :class:`~.fallback_owner.FallbackOwner`.
    dedup_fields:
        Optional list of field names for the dedup key.
    notes:
        Optional caveats.
    source_module:
        Optional dotted module path.

    Returns
    -------
    ReliabilitySummary
    """
    try:
        dm = DeliveryMode(delivery_mode)
    except ValueError:
        dm = DeliveryMode.UNKNOWN

    try:
        ack = AckStage(ack_stage)
    except ValueError:
        ack = AckStage.UNKNOWN

    try:
        to = TimeoutOwner(timeout_owner)
    except ValueError:
        to = TimeoutOwner.UNSPECIFIED

    try:
        fo = FallbackOwner(fallback_owner)
    except ValueError:
        fo = FallbackOwner.UNSPECIFIED

    dedup = DeduplicationKey(fields=list(dedup_fields or []))
    ack_policy = AckPolicy(stage=ack)

    return ReliabilitySummary(
        path_key=path_key,
        description=description,
        delivery_mode=dm,
        ack_policy=ack_policy,
        dedup_key=dedup,
        retry_policy=NO_RETRY_POLICY,
        timeout_owner=to,
        fallback_owner=fo,
        source_module=source_module,
        notes=notes,
        schema_version=SCHEMA_VERSION,
    )
