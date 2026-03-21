#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.reliability_contract.ack_policy
=======================================

PR-19 (V4) — Reliability Contract & Delivery Semantics

Defines :class:`AckStage` — the stage at which acknowledgement is expected —
and :class:`AckPolicy` — a serialisable policy capturing the full ack posture
for a message path.

Ack Stage Definitions
----------------------
+-------------------+----------------------------------------------------------+
| Stage             | Meaning                                                  |
+===================+==========================================================+
| NO_ACK            | No acknowledgement is expected or sent.  Caller is       |
|                   | fire-and-forget.                                         |
+-------------------+----------------------------------------------------------+
| ACCEPTED_ACK      | Ack is sent when the message is *accepted* by the        |
|                   | receiver — i.e. the receiver confirms receipt and        |
|                   | validates the envelope, but has not yet completed the    |
|                   | requested operation.                                     |
+-------------------+----------------------------------------------------------+
| COMPLETED_ACK     | Ack is sent only when the *operation* is fully           |
|                   | completed — i.e. the result is available or the final    |
|                   | state has been reached.                                  |
+-------------------+----------------------------------------------------------+
| UNKNOWN           | Ack stage not yet classified.  Graceful-degradation      |
|                   | sentinel.                                                |
+-------------------+----------------------------------------------------------+

Design notes
-------------
:class:`AckPolicy` is intentionally **advisory** — it describes the ack
semantics that already exist on a path.  Enforcement is the responsibility
of the transport and runtime layers.
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Dict, Optional

__all__ = [
    "AckStage",
    "ACK_STAGE_DESCRIPTIONS",
    "ack_stage_description",
    "AckPolicy",
    "NO_ACK_POLICY",
    "ACCEPTED_ACK_POLICY",
    "COMPLETED_ACK_POLICY",
]


# ---------------------------------------------------------------------------
# AckStage enum
# ---------------------------------------------------------------------------


class AckStage(str, Enum):
    """Stage at which acknowledgement is expected on a message path.

    String values are stable identifiers safe for serialisation.
    """

    NO_ACK = "no_ack"
    """No acknowledgement expected or sent.  Fire-and-forget."""

    ACCEPTED_ACK = "accepted_ack"
    """Ack on receipt/acceptance — before the operation completes."""

    COMPLETED_ACK = "completed_ack"
    """Ack on full operation completion — result or terminal state."""

    UNKNOWN = "unknown"
    """Ack stage not yet classified.  Graceful-degradation sentinel."""


# ---------------------------------------------------------------------------
# Human-readable descriptions
# ---------------------------------------------------------------------------

ACK_STAGE_DESCRIPTIONS: Dict[str, str] = {
    AckStage.NO_ACK.value: (
        "No acknowledgement is expected. The sender is fire-and-forget. "
        "Suitable for best-effort telemetry and heartbeat paths."
    ),
    AckStage.ACCEPTED_ACK.value: (
        "Acknowledgement sent when the receiver has accepted and validated "
        "the message envelope, but before the operation completes. "
        "Provides early failure detection without waiting for full completion."
    ),
    AckStage.COMPLETED_ACK.value: (
        "Acknowledgement sent only when the full operation is complete. "
        "Ensures the caller knows the operation has reached a terminal state. "
        "Higher latency than ACCEPTED_ACK."
    ),
    AckStage.UNKNOWN.value: (
        "Ack stage not yet classified. Treat as NO_ACK for safety."
    ),
}


def ack_stage_description(stage: AckStage) -> str:
    """Return the human-readable description for *stage*."""
    return ACK_STAGE_DESCRIPTIONS.get(stage.value, "Unknown ack stage.")


# ---------------------------------------------------------------------------
# AckPolicy dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class AckPolicy:
    """Serialisable policy capturing the ack posture for a message path.

    Attributes
    ----------
    stage:
        The :class:`AckStage` expected on this path.
    ack_timeout_hint_ms:
        Advisory timeout (milliseconds) for receiving the ack.
        ``0`` means no timeout hint is given.
    ack_required_for_retry:
        When ``True``, a missing ack triggers a retry (combined with the
        delivery mode).
    notes:
        Optional human-readable clarification.
    schema_version:
        Schema version integer for forward-compatibility.
    """

    stage: AckStage = AckStage.NO_ACK
    ack_timeout_hint_ms: int = 0
    ack_required_for_retry: bool = False
    notes: Optional[str] = None
    schema_version: int = 1

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "stage": self.stage.value,
            "ack_timeout_hint_ms": self.ack_timeout_hint_ms,
            "ack_required_for_retry": self.ack_required_for_retry,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AckPolicy":
        """Reconstruct from a serialised dict.  Unknown fields are silently defaulted."""
        raw_stage = data.get("stage", AckStage.UNKNOWN.value)
        try:
            stage = AckStage(raw_stage)
        except ValueError:
            stage = AckStage.UNKNOWN
        return cls(
            stage=stage,
            ack_timeout_hint_ms=int(data.get("ack_timeout_hint_ms", 0)),
            ack_required_for_retry=bool(data.get("ack_required_for_retry", False)),
            notes=data.get("notes"),
            schema_version=int(data.get("schema_version", 1)),
        )


# ---------------------------------------------------------------------------
# Pre-built policy sentinels
# ---------------------------------------------------------------------------

#: Fire-and-forget — no ack expected.
NO_ACK_POLICY = AckPolicy(
    stage=AckStage.NO_ACK,
    ack_timeout_hint_ms=0,
    ack_required_for_retry=False,
    notes="Fire-and-forget; no ack expected.",
    schema_version=1,
)

#: Accepted-ack posture — ack on receipt, 5-second hint.
ACCEPTED_ACK_POLICY = AckPolicy(
    stage=AckStage.ACCEPTED_ACK,
    ack_timeout_hint_ms=5_000,
    ack_required_for_retry=True,
    notes="Ack expected on envelope acceptance; 5 s advisory timeout.",
    schema_version=1,
)

#: Completed-ack posture — ack on full operation completion, 30-second hint.
COMPLETED_ACK_POLICY = AckPolicy(
    stage=AckStage.COMPLETED_ACK,
    ack_timeout_hint_ms=30_000,
    ack_required_for_retry=True,
    notes="Ack expected on full operation completion; 30 s advisory timeout.",
    schema_version=1,
)
