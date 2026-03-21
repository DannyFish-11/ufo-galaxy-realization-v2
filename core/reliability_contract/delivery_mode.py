#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.reliability_contract.delivery_mode
==========================================

PR-19 (V4) — Reliability Contract & Delivery Semantics

Defines the :class:`DeliveryMode` enum, which classifies the delivery
guarantee offered by a particular cross-device/runtime message path.

Delivery Mode Definitions
--------------------------
+---------------------+----------------------------------------------------------+
| Mode                | Meaning                                                  |
+=====================+==========================================================+
| BEST_EFFORT         | Message may be dropped without retransmission.           |
|                     | No ack, no persistence, no dedup required.               |
|                     | Suitable for high-frequency telemetry / heartbeats.      |
+---------------------+----------------------------------------------------------+
| AT_MOST_ONCE        | Message delivered at most once.  May be dropped; will    |
|                     | not be retried.  Stronger than BEST_EFFORT because        |
|                     | transport-layer errors are surfaced (not silently         |
|                     | swallowed) but no retry is attempted.                    |
+---------------------+----------------------------------------------------------+
| AT_LEAST_ONCE       | Message will be delivered one or more times.  Transport   |
|                     | or runtime retries are permitted.  Consumers must be      |
|                     | idempotent or dedup-aware.                               |
+---------------------+----------------------------------------------------------+
| DEDUP_REQUIRED      | At-least-once delivery with an explicit deduplication     |
|                     | contract: a stable dedup key is defined, and the          |
|                     | consumer is expected to detect and discard duplicates     |
|                     | using that key.  The higher-level guarantee is            |
|                     | effectively exactly-once from the consumer's perspective. |
+---------------------+----------------------------------------------------------+
| EXACTLY_ONCE        | Full exactly-once end-to-end guarantee — transactional    |
|                     | or idempotency is enforced at every hop.  The most        |
|                     | expensive mode; reserved for financial/audit paths.       |
+---------------------+----------------------------------------------------------+
| UNKNOWN             | Delivery mode has not been classified.  Used for          |
|                     | graceful degradation when metadata is unavailable.        |
+---------------------+----------------------------------------------------------+

Relationship to existing runtime paths
----------------------------------------
These modes are **read-only annotations** — they describe the delivery
guarantee that already exists (or is absent) in the runtime.  They do not
replace or modify transport implementations.

Mapping guidance:

* Device WebSocket execution → ``BEST_EFFORT`` (fire-and-forget command channel)
* NATS task dispatch/result → ``AT_LEAST_ONCE`` (NATS JetStream or queue group)
* ``HandoffContract`` / ``AgentBridge`` handoff → ``AT_LEAST_ONCE``
* ``CommandRouter`` remote agent dispatch → ``AT_LEAST_ONCE``
* ``TaskEnvelope`` orchestration dispatch → ``DEDUP_REQUIRED``
  (envelope carries ``idempotency_key``; dispatcher validates via
  :class:`~core.unified.idempotency.IdempotencyStore`)
"""

from __future__ import annotations

from enum import Enum
from typing import Dict

__all__ = [
    "DeliveryMode",
    "DELIVERY_MODE_DESCRIPTIONS",
    "delivery_mode_description",
]


class DeliveryMode(str, Enum):
    """Taxonomy of delivery guarantees for Galaxy runtime message paths.

    String values are stable identifiers safe for serialisation, logging, and
    API responses.
    """

    BEST_EFFORT = "best_effort"
    """No ack, no persistence, no retry — message may be silently dropped."""

    AT_MOST_ONCE = "at_most_once"
    """At most one delivery attempt; errors surfaced but not retried."""

    AT_LEAST_ONCE = "at_least_once"
    """One or more delivery attempts; consumers must be idempotent."""

    DEDUP_REQUIRED = "dedup_required"
    """At-least-once with explicit dedup key; consumer discards duplicates."""

    EXACTLY_ONCE = "exactly_once"
    """Full end-to-end exactly-once; transactional or enforced idempotency."""

    UNKNOWN = "unknown"
    """Delivery mode not yet classified; graceful-degradation sentinel."""


# ---------------------------------------------------------------------------
# Human-readable descriptions
# ---------------------------------------------------------------------------

DELIVERY_MODE_DESCRIPTIONS: Dict[str, str] = {
    DeliveryMode.BEST_EFFORT.value: (
        "Message may be silently dropped. No ack, no persistence, no retry. "
        "Appropriate for high-frequency heartbeats or optional telemetry."
    ),
    DeliveryMode.AT_MOST_ONCE.value: (
        "At most one delivery attempt. Transport errors are surfaced to the "
        "caller but no retry is attempted. Message may be lost."
    ),
    DeliveryMode.AT_LEAST_ONCE.value: (
        "Message will be delivered one or more times. Transport or runtime "
        "retries are permitted. Consumers must be idempotent or dedup-aware."
    ),
    DeliveryMode.DEDUP_REQUIRED.value: (
        "At-least-once delivery with an explicit deduplication contract. "
        "A stable dedup key is defined; consumers detect and discard duplicates. "
        "Effectively exactly-once from the consumer perspective."
    ),
    DeliveryMode.EXACTLY_ONCE.value: (
        "Full end-to-end exactly-once guarantee. Transactional or idempotency "
        "enforced at every hop. Reserved for critical/audit paths."
    ),
    DeliveryMode.UNKNOWN.value: (
        "Delivery mode not yet classified. Used when metadata is unavailable. "
        "Treat as BEST_EFFORT for safety."
    ),
}


def delivery_mode_description(mode: "DeliveryMode") -> str:
    """Return the human-readable description for *mode*."""
    return DELIVERY_MODE_DESCRIPTIONS.get(mode.value, "Unknown delivery mode.")
