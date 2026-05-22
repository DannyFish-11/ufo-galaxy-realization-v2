#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.reliability_contract.idempotency
========================================

PR-19 (V4) — Reliability Contract & Delivery Semantics

Defines :class:`DeduplicationKey` — a model that captures how deduplication
keys are formed for a given message path.

This module is **not** a dedup enforcement engine.  Enforcement is already
handled by :class:`~core.unified.idempotency.IdempotencyStore` (Block-5).
This module provides the *contract-level description* of what dedup key fields
are defined for each path and how they should be composed.

Design notes
-------------
- All fields are optional so that partial metadata can be expressed for
  paths whose dedup story is not yet fully formalised.
- The ``fields`` list names the envelope/message fields that together
  uniquely identify a message instance for dedup purposes.
- The ``composition`` string describes how the fields are combined
  (e.g. ``"<task_id>:<trace_id>"``).
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

__all__ = [
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
]


@dataclasses.dataclass(frozen=True)
class DeduplicationKey:
    """Model describing the dedup key contract for a message path.

    Attributes
    ----------
    fields:
        Ordered list of message/envelope field names that together form the
        dedup key.  Empty list means no dedup key is defined.
    composition:
        Human-readable description of how *fields* are combined into a single
        key string, e.g. ``"<task_id>:<idempotency_key>"``.
        ``None`` when no key is defined.
    source_component:
        Python module or class responsible for constructing the key, e.g.
        ``"core.unified.idempotency.IdempotencyStore"``.
    enforced:
        ``True`` when dedup is actively enforced at runtime (e.g. via
        :class:`~core.unified.idempotency.IdempotencyStore`).
        ``False`` means the key is defined but enforcement is advisory.
    notes:
        Optional clarification.
    schema_version:
        Schema version integer.
    """

    fields: List[str] = dataclasses.field(default_factory=list)
    composition: Optional[str] = None
    source_component: Optional[str] = None
    enforced: bool = False
    notes: Optional[str] = None
    schema_version: int = 1

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "fields": list(self.fields),
            "composition": self.composition,
            "source_component": self.source_component,
            "enforced": self.enforced,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeduplicationKey":
        """Reconstruct from a serialised dict.  Unknown fields are silently defaulted."""
        return cls(
            fields=list(data.get("fields", [])),
            composition=data.get("composition"),
            source_component=data.get("source_component"),
            enforced=bool(data.get("enforced", False)),
            notes=data.get("notes"),
            schema_version=int(data.get("schema_version", 1)),
        )

    def has_key(self) -> bool:
        """Return ``True`` if this record defines at least one dedup field."""
        return bool(self.fields)


# ---------------------------------------------------------------------------
# Pre-built dedup key sentinels for known runtime paths
# ---------------------------------------------------------------------------

#: No deduplication key — fire-and-forget paths.
NO_DEDUP_KEY = DeduplicationKey(
    fields=[],
    composition=None,
    source_component=None,
    enforced=False,
    notes="No deduplication key defined for this path.",
    schema_version=1,
)

#: TaskEnvelope orchestration — idempotency_key enforced by IdempotencyStore.
TASK_ENVELOPE_DEDUP_KEY = DeduplicationKey(
    fields=["task_id", "idempotency_key"],
    composition="<task_id>:<idempotency_key>",
    source_component="core.unified.idempotency.IdempotencyStore",
    enforced=True,
    notes=(
        "CommandEnvelope carries an idempotency_key field. "
        "IdempotencyStore (Block-5) validates it on acceptance. "
        "Duplicate commands raise DuplicateCommandError."
    ),
    schema_version=1,
)

#: NATS task dispatch — trace_id + task_id as composite dedup key.
NATS_TASK_DEDUP_KEY = DeduplicationKey(
    fields=["task_id", "trace_id"],
    composition="<task_id>:<trace_id>",
    source_component="core.nats_bus.NATSTopics",
    enforced=False,
    notes=(
        "NATS JetStream consumer groups provide at-least-once delivery. "
        "Dedup key is advisory; consumer-side dedup is application responsibility."
    ),
    schema_version=1,
)

#: AgentBridge / HandoffContract — trace_id is the primary correlation key.
HANDOFF_DEDUP_KEY = DeduplicationKey(
    fields=["trace_id", "task_id"],
    composition="<trace_id>:<task_id>",
    source_component="galaxy_gateway.agent_bridge.HandoffContract",
    enforced=False,
    notes=(
        "HandoffContract carries trace_id and task_id. "
        "AgentBridge dedup is advisory; runtime bridge does not enforce strict "
        "exactly-once but traces allow correlation."
    ),
    schema_version=1,
)

#: CommandRouter remote agent dispatch — task_id is the primary key.
COMMAND_ROUTER_DEDUP_KEY = DeduplicationKey(
    fields=["task_id"],
    composition="<task_id>",
    source_component="core.command_router.CommandRouter",
    enforced=False,
    notes=(
        "CommandRouter passes task_id to the remote agent. " "No built-in dedup enforcement; callers are responsible."
    ),
    schema_version=1,
)

#: Device WebSocket — message_id is the per-message identifier.
DEVICE_WEBSOCKET_DEDUP_KEY = DeduplicationKey(
    fields=["message_id"],
    composition="<message_id>",
    source_component="galaxy_gateway.transport.websocket_server",
    enforced=False,
    notes=(
        "WebSocket messages carry a message_id field. " "No dedup enforcement on the transport layer; best-effort path."
    ),
    schema_version=1,
)

#: Android-originated result uplink — task identity + stable delivery identity +
#: terminal emission identity.  Message transport ids alone are NOT canonical.
ANDROID_UPLINK_RESULT_DEDUP_KEY = DeduplicationKey(
    fields=["task_id", "idempotency_key", "completion_emission_id"],
    composition="<task_id>:<idempotency_key>:<completion_emission_id>",
    source_component="core.unified_result_ingress.UnifiedResultIngress",
    enforced=True,
    notes=(
        "Canonical Android result handling requires both a stable delivery "
        "idempotency key and a stable terminal emission identity. "
        "Transport-only identifiers such as message_id are compatibility hints, "
        "not sufficient for full canonical duplicate guarantees."
    ),
    schema_version=1,
)

#: Android-originated reconciliation / runtime truth uplink — stable subject
#: scope plus reconciliation/signal identity.
ANDROID_UPLINK_RECONCILIATION_DEDUP_KEY = DeduplicationKey(
    fields=["contract_id|session_id", "reconciliation_id|signal_id|handoff_id"],
    composition="<contract_id|session_id>:<reconciliation_id|signal_id|handoff_id>",
    source_component="contracts.cross_repo_schema_version_gate",
    enforced=False,
    notes=(
        "Canonical reconciliation dedupe is scoped by delegated contract "
        "identity when available, otherwise by runtime/session identity. "
        "A stable reconciliation or signal identifier is required for full "
        "cross-repo canonical duplicate semantics."
    ),
    schema_version=1,
)

#: Android offline replay uplink — replay session scope, queue item identity,
#: and queue ordering number.
ANDROID_UPLINK_REPLAY_DEDUP_KEY = DeduplicationKey(
    fields=["replay_session_id", "replay_item_id", "replay_seq"],
    composition="<replay_session_id>:<replay_item_id>:<replay_seq>",
    source_component="core.unified_result_ingress.UnifiedResultIngress",
    enforced=True,
    notes=(
        "Replay acceptance depends on both stable per-item identity and queue "
        "ordering semantics. Missing replay_item_id or replay_seq must degrade "
        "or block canonical replay guarantees rather than silently passing as "
        "authoritative duplicate identity."
    ),
    schema_version=1,
)
