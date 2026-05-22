#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.reliability_contract
===========================

PR-19 (V4) — Reliability Contract & Delivery Semantics

A focused additive package that formalises **reliability semantics** —
delivery mode, ack posture, deduplication, timeout ownership, and fallback
ownership — across the Galaxy runtime's existing cross-device/runtime/message
paths.

This package answers:
  - Is a given path best-effort, at-least-once, or dedup-required?
  - Which ack stage matters (accepted vs completed)?
  - Which component owns the timeout for this path?
  - Which component owns the fallback decision?
  - How are dedup keys defined and composed?

Source signals consumed (read-only, not modified)
--------------------------------------------------
* :class:`~core.unified.command_envelope.CommandEnvelope` — envelope fields
  (idempotency_key, task_id, trace_id) used as dedup key sources.
* :class:`~core.unified.idempotency.IdempotencyStore` — Block-5 enforcement
  layer; described but not replaced.
* :class:`~galaxy_gateway.agent_bridge.HandoffContract` — trace_id / task_id
  consumed as dedup/correlation key hints.
* :mod:`~core.nats_bus` — NATSTopics topic constants; delivery semantics
  described.
* :class:`~core.command_router.CommandRouter` — dispatch_agent_remote path
  described.
* :mod:`~galaxy_gateway.transport.websocket_server` — WebSocket command
  channel described.

What this package does NOT do
------------------------------
- It does **not** replace WebSocket/NATS/HTTP transport implementations.
- It does **not** create a new retry engine.
- It does **not** introduce a new orchestrator or message bus.
- It does **not** change the actual runtime behaviour of existing delivery
  paths (all integrations are additive read-only annotations).
- Recovery governance is **advisory**; actual fallback logic remains in
  AgentBridge, TaskOrchestrator, and CommandRouter.

Public API
----------
DeliveryMode
    Stable enum: ``best_effort``, ``at_most_once``, ``at_least_once``,
    ``dedup_required``, ``exactly_once``, ``unknown``.

AckStage
    Stable enum: ``no_ack``, ``accepted_ack``, ``completed_ack``, ``unknown``.

AckPolicy
    Serialisable policy capturing ack posture (stage, timeout hint,
    retry behaviour).

DeduplicationKey
    Model describing dedup key fields, composition, and enforcement status.

RetryPolicy
    Serialisable policy describing retry contract (attempts, backoff, owner).

TimeoutOwner
    Stable enum: ``transport``, ``router``, ``runtime``, ``coordinator``,
    ``caller``, ``unspecified``.

FallbackOwner
    Stable enum: ``local_fallback``, ``transport_fallback``, ``reroute_owner``,
    ``coordinator``, ``abort_owner``, ``caller``, ``unspecified``.

ReliabilitySummary
    Compact, public-safe summary combining all reliability dimensions for a
    single runtime path or contract family.

RELIABILITY_PATH_REGISTRY
    Read-only dict of pre-seeded :class:`ReliabilitySummary` instances for
    all known runtime paths.

UNKNOWN_RELIABILITY_SUMMARY
    Safe sentinel returned when a path is not registered.

get_summary_for_path(path_key) → ReliabilitySummary
    Look up a summary; returns sentinel for unknown paths.

list_known_paths() → List[str]
    Return sorted list of all registered path keys.

get_reliability_registry_snapshot() → dict
    Return the full registry as a JSON-serialisable dict.

attach_reliability_to_projection(projection, path_key) → dict
    Attach a reliability summary to a projection dict additively.

make_reliability_summary(…) → ReliabilitySummary
    One-call builder from scalar inputs with graceful enum degradation.

See Also
--------
docs/DELIVERY_SEMANTICS_AND_RELIABILITY_CONTRACT.md — design document.
core/contract_map/ — PR-16 cross-plane contract map (sibling package).
core/device_formation/ — PR-17 device formation (sibling package).
core/agent_governance/ — PR-18 agent governance (sibling package).
"""

from __future__ import annotations

from .delivery_mode import (
    DeliveryMode,
    DELIVERY_MODE_DESCRIPTIONS,
    delivery_mode_description,
)
from .ack_policy import (
    AckStage,
    ACK_STAGE_DESCRIPTIONS,
    ack_stage_description,
    AckPolicy,
    NO_ACK_POLICY,
    ACCEPTED_ACK_POLICY,
    COMPLETED_ACK_POLICY,
)
from .idempotency import (
    DeduplicationKey,
    NO_DEDUP_KEY,
    TASK_ENVELOPE_DEDUP_KEY,
    NATS_TASK_DEDUP_KEY,
    HANDOFF_DEDUP_KEY,
    COMMAND_ROUTER_DEDUP_KEY,
    DEVICE_WEBSOCKET_DEDUP_KEY,
    ANDROID_UPLINK_RESULT_DEDUP_KEY,
    ANDROID_UPLINK_RECONCILIATION_DEDUP_KEY,
    ANDROID_UPLINK_REPLAY_DEDUP_KEY,
)
from .retry_policy import (
    RetryPolicy,
    NO_RETRY_POLICY,
    TRANSPORT_RETRY_POLICY,
    RUNTIME_RETRY_POLICY,
    COORDINATOR_RETRY_POLICY,
)
from .timeout_owner import (
    TimeoutOwner,
    TIMEOUT_OWNER_DESCRIPTIONS,
    timeout_owner_description,
)
from .fallback_owner import (
    FallbackOwner,
    FALLBACK_OWNER_DESCRIPTIONS,
    fallback_owner_description,
)
from .reliability_summary import (
    ReliabilitySummary,
    UNKNOWN_RELIABILITY_SUMMARY,
    RELIABILITY_PATH_REGISTRY,
    get_reliability_registry_snapshot,
    get_summary_for_path,
    list_known_paths,
    attach_reliability_to_projection,
    make_reliability_summary,
)

__all__ = [
    # Delivery mode
    "DeliveryMode",
    "DELIVERY_MODE_DESCRIPTIONS",
    "delivery_mode_description",
    # Ack policy
    "AckStage",
    "ACK_STAGE_DESCRIPTIONS",
    "ack_stage_description",
    "AckPolicy",
    "NO_ACK_POLICY",
    "ACCEPTED_ACK_POLICY",
    "COMPLETED_ACK_POLICY",
    # Idempotency / dedup keys
    "DeduplicationKey",
    "NO_DEDUP_KEY",
    "TASK_ENVELOPE_DEDUP_KEY",
    "NATS_TASK_DEDUP_KEY",
    "HANDOFF_DEDUP_KEY",
    "COMMAND_ROUTER_DEDUP_KEY",
    "DEVICE_WEBSOCKET_DEDUP_KEY",
    "ANDROID_UPLINK_RESULT_DEDUP_KEY",
    "ANDROID_UPLINK_RECONCILIATION_DEDUP_KEY",
    "ANDROID_UPLINK_REPLAY_DEDUP_KEY",
    # Retry policy
    "RetryPolicy",
    "NO_RETRY_POLICY",
    "TRANSPORT_RETRY_POLICY",
    "RUNTIME_RETRY_POLICY",
    "COORDINATOR_RETRY_POLICY",
    # Timeout owner
    "TimeoutOwner",
    "TIMEOUT_OWNER_DESCRIPTIONS",
    "timeout_owner_description",
    # Fallback owner
    "FallbackOwner",
    "FALLBACK_OWNER_DESCRIPTIONS",
    "fallback_owner_description",
    # Reliability summary & registry
    "ReliabilitySummary",
    "UNKNOWN_RELIABILITY_SUMMARY",
    "RELIABILITY_PATH_REGISTRY",
    "get_reliability_registry_snapshot",
    "get_summary_for_path",
    "list_known_paths",
    "attach_reliability_to_projection",
    "make_reliability_summary",
]
