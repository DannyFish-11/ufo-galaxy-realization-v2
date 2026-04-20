"""contracts/android_handoff_response.py
=========================================
PR-H (V2 配套): Android Handoff Response Contract.

Defines the typed contract for Android's ACK / result / failure responses
to a dispatched :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`.
This is the V2-side schema that makes the Android handoff round-trip
traceable and the ACK / result / failure closable without a "black hole"
state where V2 dispatches a handoff but never learns the outcome.

Design
------
- ``handoff_id`` is the primary correlation key.  It is stamped onto every
  outbound :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2` and
  **must** be echoed back in every Android response message so V2 can match
  responses to the originating dispatch.
- ``trace_id``, ``task_id``, and ``session_id`` are secondary correlation
  handles forwarded verbatim from the dispatched envelope.
- ``response_kind`` indicates the phase: ``ack`` (receipt confirmed),
  ``result`` (execution completed successfully), ``failure`` (execution
  failed), ``timeout``, ``cancelled``.
- All fields beyond ``handoff_id`` and ``response_kind`` are optional so
  that Android can produce a minimal ACK without waiting for a full result.

Public API
----------
Enum::

    HandoffResponseKind  — ack / result / failure / timeout / cancelled

Contract::

    AndroidHandoffResponseEnvelope  — typed response carrier

Builders::

    from_android_ack_message(message)    → AndroidHandoffResponseEnvelope
    from_android_result_message(message) → AndroidHandoffResponseEnvelope
    from_android_failure_message(message)→ AndroidHandoffResponseEnvelope

Sentinels::

    ANDROID_HANDOFF_RESPONSE_CONTRACT_PR_H_SENTINEL
    HANDOFF_ID_IS_PRIMARY_CORRELATION_KEY_POLICY
    RESPONSE_KIND_MUST_BE_EXPLICIT_POLICY
    ACK_DOES_NOT_REQUIRE_RESULT_PAYLOAD_POLICY
    FAILURE_MUST_CARRY_ERROR_DETAIL_POLICY
"""

from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sentinels — canonical policy documentation
# ---------------------------------------------------------------------------

ANDROID_HANDOFF_RESPONSE_CONTRACT_PR_H_SENTINEL: str = (
    "ANDROID_HANDOFF_RESPONSE_CONTRACT_PR_H::"
    "contracts.android_handoff_response::"
    "pr-h-v2-companion::android-native-handoff-response-contract::"
    "typed-ack-result-failure-carrier"
)

HANDOFF_ID_IS_PRIMARY_CORRELATION_KEY_POLICY: str = (
    "POLICY::HANDOFF_ID_IS_PRIMARY_CORRELATION_KEY: "
    "Every AndroidHandoffResponseEnvelope MUST carry the handoff_id from the "
    "dispatched HandoffEnvelopeV2.  V2-side ingress resolves the originating "
    "dispatch record by handoff_id before falling back to task_id or session_id."
)

RESPONSE_KIND_MUST_BE_EXPLICIT_POLICY: str = (
    "POLICY::RESPONSE_KIND_MUST_BE_EXPLICIT: "
    "The response_kind field MUST be a known HandoffResponseKind value.  "
    "Unknown values are normalised to HandoffResponseKind.unknown so that "
    "the ingress handler can log and skip without crashing."
)

ACK_DOES_NOT_REQUIRE_RESULT_PAYLOAD_POLICY: str = (
    "POLICY::ACK_DOES_NOT_REQUIRE_RESULT_PAYLOAD: "
    "A response_kind=ack response is a receipt confirmation only; "
    "result_payload and error_detail are expected to be absent.  "
    "V2-side ingress MUST NOT block on missing result for ack responses."
)

FAILURE_MUST_CARRY_ERROR_DETAIL_POLICY: str = (
    "POLICY::FAILURE_MUST_CARRY_ERROR_DETAIL: "
    "A response_kind=failure response SHOULD include at least one of "
    "error_code or error_detail.  V2 ingress logs a warning when both "
    "are absent but does not reject the message."
)

HANDOFF_RESPONSE_IS_CORRELATED_BY_HANDOFF_ID_THEN_TASK_ID_POLICY: str = (
    "POLICY::HANDOFF_RESPONSE_CORRELATION_ORDER: "
    "V2 ingress resolves the originating dispatch in order: "
    "1. handoff_id (preferred, stable, globally unique), "
    "2. task_id (fallback for legacy callers), "
    "3. session_id (last-resort fallback). "
    "If none match, the response is rejected with a descriptive reason."
)


# ---------------------------------------------------------------------------
# HandoffResponseKind enum
# ---------------------------------------------------------------------------


class HandoffResponseKind(str, Enum):
    """Lifecycle phase of an Android handoff response.

    Values align with ``DelegatedSignalKind`` (PR-16) where applicable so
    that the existing reconciler machinery can optionally be re-used.
    """

    ack = "ack"
    """Android confirmed receipt of the HandoffEnvelopeV2; execution has not
    yet started or is just beginning."""

    result = "result"
    """Android completed execution successfully and is returning the result
    payload."""

    failure = "failure"
    """Android encountered an error during execution; error_code /
    error_detail carry the failure reason."""

    timeout = "timeout"
    """Android did not complete execution within the agreed timeout window."""

    cancelled = "cancelled"
    """The handoff was explicitly cancelled (by Android or the host)."""

    unknown = "unknown"
    """Unrecognised response kind; used for forward-compatibility."""

    @classmethod
    def from_string(cls, value: str) -> "HandoffResponseKind":
        """Normalise a raw string to a :class:`HandoffResponseKind`.

        Falls back to :attr:`unknown` for unrecognised values.
        """
        try:
            return cls(value)
        except ValueError:
            return cls.unknown


# ---------------------------------------------------------------------------
# AndroidHandoffResponseEnvelope
# ---------------------------------------------------------------------------


class AndroidHandoffResponseEnvelope(BaseModel):
    """Typed carrier for Android's response to a dispatched HandoffEnvelopeV2.

    This contract is produced by Android after it receives and processes a
    ``handoff_dispatch`` AIP message.  V2 ingress extracts this envelope from
    the inbound ``handoff_ack`` / ``handoff_result`` / ``handoff_failure``
    message and correlates it back to the originating dispatch via
    ``handoff_id``.

    Fields
    ------
    response_id:
        Stable unique identifier for this specific response event.
        Auto-generated if Android does not supply one.
    handoff_id:
        The ``handoff_id`` from the dispatched HandoffEnvelopeV2.
        **Primary correlation key** — always required.
    trace_id:
        Propagated from the dispatched envelope for distributed tracing.
    task_id:
        Propagated from the dispatched envelope.  Secondary correlation key.
    session_id:
        Propagated from the dispatched envelope.  Tertiary correlation key.
    device_id:
        Identifier of the Android device sending this response.
    response_kind:
        Lifecycle phase: ``ack`` | ``result`` | ``failure`` | ``timeout`` |
        ``cancelled`` | ``unknown``.
    success:
        ``True`` for ``result`` responses; ``False`` for ``failure``,
        ``timeout``, ``cancelled``; ``None`` for ``ack`` (not yet determined).
    result_payload:
        Arbitrary result data for ``result`` responses.  None otherwise.
    error_code:
        Short machine-readable error code for ``failure`` responses.
    error_detail:
        Human-readable error description for ``failure`` responses.
    schema_version:
        Schema version marker.  Currently ``"v2"``.
    created_at:
        Unix timestamp when this response was produced on Android.
    """

    response_id: str = Field(
        default_factory=lambda: f"ahr_{uuid.uuid4().hex[:12]}",
        description="Stable unique identifier for this response event.",
    )
    handoff_id: str = Field(
        default="",
        description="handoff_id from the dispatched HandoffEnvelopeV2 (primary correlation key).",
    )
    trace_id: str = Field(
        default="",
        description="Trace identifier propagated from the dispatched envelope.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Task identifier propagated from the dispatched envelope.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier propagated from the dispatched envelope.",
    )
    device_id: str = Field(
        default="",
        description="Identifier of the Android device sending this response.",
    )
    response_kind: HandoffResponseKind = Field(
        default=HandoffResponseKind.unknown,
        description="Lifecycle phase of this response.",
    )
    success: Optional[bool] = Field(
        default=None,
        description=(
            "True for result, False for failure/timeout/cancelled, "
            "None for ack (not yet determined)."
        ),
    )
    result_payload: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Execution result data; present for result responses only.",
    )
    error_code: Optional[str] = Field(
        default=None,
        description="Short machine-readable error code; present for failure responses.",
    )
    error_detail: Optional[str] = Field(
        default=None,
        description="Human-readable error description; present for failure responses.",
    )
    schema_version: str = Field(
        default="v2",
        description="Schema version marker.  Currently 'v2'.",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this response was produced.",
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
    def from_dict(cls, data: Dict[str, Any]) -> "AndroidHandoffResponseEnvelope":
        """Reconstruct from a plain dict."""
        return cls(**data)

    @property
    def is_terminal(self) -> bool:
        """Return True if this response represents a terminal lifecycle phase."""
        return self.response_kind in (
            HandoffResponseKind.result,
            HandoffResponseKind.failure,
            HandoffResponseKind.timeout,
            HandoffResponseKind.cancelled,
        )


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def _extract_identity(message: Dict[str, Any]) -> Dict[str, Any]:
    """Extract correlation identity fields from a raw Android message dict.

    Reads from both the top-level message keys and the nested ``payload``
    sub-dict, with top-level taking precedence for ``device_id`` and
    ``trace_id``, and the nested payload taking precedence for
    ``handoff_id`` / ``task_id`` / ``session_id`` (Android sends these
    as delegated routing fields inside the payload).
    """
    payload = message.get("payload") or {}
    handoff_id = (
        str(payload.get("handoff_id") or message.get("handoff_id") or "")
    )
    trace_id = (
        str(message.get("trace_id") or payload.get("trace_id") or "")
    )
    task_id = (
        payload.get("task_id") or message.get("task_id")
    )
    session_id = (
        payload.get("session_id") or message.get("session_id")
    )
    device_id = str(message.get("device_id") or payload.get("device_id") or "")
    return {
        "handoff_id": handoff_id,
        "trace_id": trace_id,
        "task_id": str(task_id) if task_id else None,
        "session_id": str(session_id) if session_id else None,
        "device_id": device_id,
    }


def from_android_ack_message(message: Dict[str, Any]) -> AndroidHandoffResponseEnvelope:
    """Build an :class:`AndroidHandoffResponseEnvelope` from a raw Android ACK message.

    Handles AIP message type ``handoff_ack`` or any message with
    ``response_kind="ack"``.

    Parameters
    ----------
    message:
        Raw inbound Android message dict.

    Returns
    -------
    AndroidHandoffResponseEnvelope
        Typed ACK envelope with ``response_kind=ack``, ``success=None``.
    """
    identity = _extract_identity(message)
    return AndroidHandoffResponseEnvelope(
        handoff_id=identity["handoff_id"],
        trace_id=identity["trace_id"],
        task_id=identity["task_id"],
        session_id=identity["session_id"],
        device_id=identity["device_id"],
        response_kind=HandoffResponseKind.ack,
        success=None,
    )


def from_android_result_message(message: Dict[str, Any]) -> AndroidHandoffResponseEnvelope:
    """Build an :class:`AndroidHandoffResponseEnvelope` from a raw Android result message.

    Handles AIP message type ``handoff_result`` or any message with
    ``response_kind="result"``.  The ``result_payload`` is extracted from the
    nested ``payload`` dict or the top-level message.

    Parameters
    ----------
    message:
        Raw inbound Android message dict.

    Returns
    -------
    AndroidHandoffResponseEnvelope
        Typed result envelope with ``response_kind=result``, ``success=True``.
    """
    identity = _extract_identity(message)
    payload = message.get("payload") or {}
    result_payload = payload.get("result") or payload.get("result_payload") or {}
    return AndroidHandoffResponseEnvelope(
        handoff_id=identity["handoff_id"],
        trace_id=identity["trace_id"],
        task_id=identity["task_id"],
        session_id=identity["session_id"],
        device_id=identity["device_id"],
        response_kind=HandoffResponseKind.result,
        success=True,
        result_payload=result_payload if result_payload else None,
    )


def from_android_failure_message(message: Dict[str, Any]) -> AndroidHandoffResponseEnvelope:
    """Build an :class:`AndroidHandoffResponseEnvelope` from a raw Android failure message.

    Handles AIP message type ``handoff_failure`` or any message with
    ``response_kind="failure"`` / ``"timeout"`` / ``"cancelled"``.

    Parameters
    ----------
    message:
        Raw inbound Android message dict.

    Returns
    -------
    AndroidHandoffResponseEnvelope
        Typed failure envelope with ``success=False`` and error detail populated.
    """
    identity = _extract_identity(message)
    payload = message.get("payload") or {}
    raw_kind = (
        message.get("response_kind")
        or payload.get("response_kind")
        or message.get("type", "failure")
    )
    # Map AIP type names to HandoffResponseKind
    _type_to_kind = {
        "handoff_failure": "failure",
        "handoff_timeout": "timeout",
        "handoff_cancelled": "cancelled",
    }
    normalised_kind = _type_to_kind.get(str(raw_kind), str(raw_kind))
    response_kind = HandoffResponseKind.from_string(normalised_kind)
    error_code = (
        message.get("error_code")
        or payload.get("error_code")
    )
    error_detail = (
        message.get("error_detail")
        or message.get("error_message")
        or payload.get("error_detail")
        or payload.get("error_message")
    )
    return AndroidHandoffResponseEnvelope(
        handoff_id=identity["handoff_id"],
        trace_id=identity["trace_id"],
        task_id=identity["task_id"],
        session_id=identity["session_id"],
        device_id=identity["device_id"],
        response_kind=response_kind,
        success=False,
        error_code=str(error_code) if error_code else None,
        error_detail=str(error_detail) if error_detail else None,
    )


def extract_handoff_response_envelope(
    message: Dict[str, Any],
) -> AndroidHandoffResponseEnvelope:
    """Dispatch to the correct builder based on the inbound message type / response_kind.

    This is the canonical extraction entry-point for V2-side ingress.  It
    inspects the ``type`` and ``response_kind`` fields and delegates to
    :func:`from_android_ack_message`, :func:`from_android_result_message`, or
    :func:`from_android_failure_message`.

    Parameters
    ----------
    message:
        Raw inbound Android message dict.

    Returns
    -------
    AndroidHandoffResponseEnvelope
        Typed envelope; ``response_kind=unknown`` when the message type
        cannot be classified.
    """
    msg_type = str(message.get("type") or "")
    payload = message.get("payload") or {}
    raw_kind = (
        message.get("response_kind")
        or payload.get("response_kind")
        or ""
    )

    if msg_type == "handoff_ack" or raw_kind == "ack":
        return from_android_ack_message(message)
    if msg_type == "handoff_result" or raw_kind == "result":
        return from_android_result_message(message)
    if msg_type in ("handoff_failure", "handoff_timeout", "handoff_cancelled") or raw_kind in (
        "failure", "timeout", "cancelled"
    ):
        return from_android_failure_message(message)

    # Fallback: produce an unknown envelope so callers can log and continue.
    identity = _extract_identity(message)
    return AndroidHandoffResponseEnvelope(
        handoff_id=identity["handoff_id"],
        trace_id=identity["trace_id"],
        task_id=identity["task_id"],
        session_id=identity["session_id"],
        device_id=identity["device_id"],
        response_kind=HandoffResponseKind.unknown,
    )


__all__ = [
    # Sentinels
    "ANDROID_HANDOFF_RESPONSE_CONTRACT_PR_H_SENTINEL",
    "HANDOFF_ID_IS_PRIMARY_CORRELATION_KEY_POLICY",
    "RESPONSE_KIND_MUST_BE_EXPLICIT_POLICY",
    "ACK_DOES_NOT_REQUIRE_RESULT_PAYLOAD_POLICY",
    "FAILURE_MUST_CARRY_ERROR_DETAIL_POLICY",
    "HANDOFF_RESPONSE_IS_CORRELATED_BY_HANDOFF_ID_THEN_TASK_ID_POLICY",
    # Enum
    "HandoffResponseKind",
    # Contract
    "AndroidHandoffResponseEnvelope",
    # Builders
    "from_android_ack_message",
    "from_android_result_message",
    "from_android_failure_message",
    "extract_handoff_response_envelope",
]
