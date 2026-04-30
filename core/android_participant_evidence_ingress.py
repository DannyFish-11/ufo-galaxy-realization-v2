#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/android_participant_evidence_ingress.py
============================================
Android participant runtime evidence ingestion and normalization layer.

Purpose
-------
This module provides a structured, file-based evidence contract mechanism that
allows the V2 system to ingest Android participant runtime evidence without
requiring a direct Python import of Android-side modules.

The Android side produces a JSON artifact file conforming to the
ANDROID_PARTICIPANT_EVIDENCE_CONTRACT_VERSION schema.  This module reads,
validates, normalizes, and exposes that evidence to
``system_final_acceptance_verdict`` and related governance layers.

Key design principles
---------------------
1. **Fail-conservative**: any missing, malformed, or stale evidence yields a
   precise non-ready status rather than an optimistic upgrade.
2. **No hard-coded constants**: participant status is derived exclusively from
   evidence content; ready/degraded/unavailable are never written in as
   constants.
3. **Testable and auditable**: every code path produces a typed result that
   can be inspected in tests and audit reports.
4. **File-path configurable**: the evidence artifact path is controlled via the
   ``ANDROID_PARTICIPANT_EVIDENCE_PATH`` environment variable, with a sensible
   default for CI drop-in usage.

Evidence JSON schema (version "1.0")
-------------------------------------
::

    {
      "schema_version": "1.0",
      "authority": "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1",
      "generated_at": <unix_timestamp_float>,
      "device_id": "<string>",
      "session_id": "<string>",
      "participant_status": "ready" | "degraded" | "unavailable" | "recovered",
      "is_operational": <bool>,
      "audit_event_count": <int ≥ 0>,
      "lifecycle_phase": "<string>",
      "last_heartbeat_at": <unix_timestamp_float>,
      "capability_declarations": {<opaque dict>},
      "evidence_notes": "<string>"
    }

Required fields: schema_version, authority, generated_at, participant_status,
                 is_operational, audit_event_count.

All other fields are optional but recommended.

AndroidParticipantStatus states
--------------------------------
ready
    Evidence is present, structurally valid, fresh, and the Android participant
    reports itself as operational with at least one audit event.

degraded
    Evidence is valid and fresh, but the participant explicitly reports
    ``participant_status = "degraded"`` or ``is_operational = false`` with
    audit events present.

unavailable
    Evidence is valid and fresh, but the participant explicitly reports
    ``participant_status = "unavailable"`` or ``is_operational = false`` with
    no audit events.

recovered
    Evidence is valid and fresh, and the participant reports
    ``participant_status = "recovered"``.

missing_evidence
    No evidence file was found at the configured path.

malformed_evidence
    An evidence file was found but could not be parsed as JSON, or it is
    missing required fields, or its ``authority`` sentinel does not match
    the expected value, or its ``schema_version`` is unsupported.

stale_evidence
    An evidence file was found and is structurally valid, but its
    ``generated_at`` timestamp is older than the configured maximum age
    (``ANDROID_PARTICIPANT_EVIDENCE_MAX_AGE_SECONDS``, default 3600 s).

unverified
    Evidence is valid and fresh, but the content is insufficient to reach a
    ready/degraded/unavailable conclusion (e.g. ``is_operational`` is missing,
    ``audit_event_count`` = 0 with an ambiguous ``participant_status``).

Authority sentinels
-------------------
``ANDROID_PARTICIPANT_EVIDENCE_INGRESS_AUTHORITY``
    Import this sentinel to assert that the canonical Android evidence ingress
    layer is available.

``ANDROID_PARTICIPANT_EVIDENCE_CONTRACT_VERSION``
    The schema version string this module was designed to consume.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.AndroidParticipantEvidenceIngress")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

ANDROID_PARTICIPANT_EVIDENCE_INGRESS_AUTHORITY: str = (
    "ANDROID_PARTICIPANT_EVIDENCE_INGRESS_V1::"
    "concrete-android-implementation-of-participant-generic-availability-"
    "contract-defined-in-core.participant_authority_interfaces-PR-8::"
    "AndroidParticipantStatus-implements-ParticipantAvailabilityStatus"
)
"""Sentinel: import to assert the canonical Android participant evidence ingress
layer is available.  Must be a non-empty string.

This module is the CONCRETE Android implementation of the participant-generic
availability/health contract defined in core.participant_authority_interfaces
(PR-8).  AndroidParticipantStatus maps 1-to-1 onto ParticipantAvailabilityStatus.
"""

ANDROID_PARTICIPANT_EVIDENCE_CONTRACT_VERSION: str = "1.0"
"""Expected ``schema_version`` field value in Android participant evidence
artifacts.  Artifacts with a different version are treated as malformed."""

EXPECTED_AUTHORITY_SENTINEL: str = "ANDROID_PARTICIPANT_RUNTIME_EVIDENCE_V1"
"""Expected ``authority`` field value in Android participant evidence
artifacts.  Artifacts with a different authority are treated as malformed."""

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

EVIDENCE_PATH_IS_CONFIGURABLE_POLICY: str = (
    "POLICY::EVIDENCE_PATH_IS_CONFIGURABLE: "
    "The Android participant evidence artifact path is controlled via the "
    "ANDROID_PARTICIPANT_EVIDENCE_PATH environment variable.  This allows CI, "
    "staging, and production to supply different artifacts without code changes."
)

FAIL_CONSERVATIVE_ON_MISSING_EVIDENCE_POLICY: str = (
    "POLICY::FAIL_CONSERVATIVE_ON_MISSING_EVIDENCE: "
    "When no evidence file is found, the status is missing_evidence and the "
    "verdict is NOT upgraded to ready.  Evidence absence is never treated as "
    "implicit readiness."
)

STALE_EVIDENCE_IS_NOT_READY_POLICY: str = (
    "POLICY::STALE_EVIDENCE_IS_NOT_READY: "
    "Evidence older than ANDROID_PARTICIPANT_EVIDENCE_MAX_AGE_SECONDS is "
    "classified as stale_evidence and MUST NOT be mapped to ready, degraded, "
    "or unavailable.  Staleness is a blocking quality defect."
)

MALFORMED_EVIDENCE_IS_NOT_READY_POLICY: str = (
    "POLICY::MALFORMED_EVIDENCE_IS_NOT_READY: "
    "Evidence that fails JSON parsing, schema validation, or authority/version "
    "checks is classified as malformed_evidence and MUST NOT be mapped to any "
    "positive status.  Structural correctness is a prerequisite for consumption."
)

PARTICIPANT_STATUS_DERIVED_FROM_EVIDENCE_POLICY: str = (
    "POLICY::PARTICIPANT_STATUS_DERIVED_FROM_EVIDENCE: "
    "AndroidParticipantStatus is computed exclusively from evidence content. "
    "No status value is hard-coded as a constant.  ready/degraded/unavailable "
    "all require a valid, fresh artifact to be produced."
)

EVIDENCE_VISIBLE_IN_SUMMARY_POLICY: str = (
    "POLICY::EVIDENCE_VISIBLE_IN_SUMMARY: "
    "Every evidence ingestion attempt produces an AndroidParticipantEvidenceResult "
    "with a non-empty evidence_summary field that can be surfaced in audit reports "
    "and governance summaries."
)

# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------

_ENV_EVIDENCE_PATH = "ANDROID_PARTICIPANT_EVIDENCE_PATH"
_ENV_MAX_AGE = "ANDROID_PARTICIPANT_EVIDENCE_MAX_AGE_SECONDS"

_DEFAULT_EVIDENCE_FILENAME = "android_participant_evidence.json"
_DEFAULT_MAX_AGE_SECONDS = 3600  # 1 hour

# ---------------------------------------------------------------------------
# AndroidParticipantStatus enum
# ---------------------------------------------------------------------------


class AndroidParticipantStatus(str, Enum):
    """Precise status of the Android participant as derived from evidence.

    Values
    ------
    ready
        Evidence is present, valid, fresh, and the participant is operational.

    degraded
        Evidence is valid and fresh, but the participant reports a degraded
        state (``participant_status = "degraded"`` or ``is_operational = false``
        with audit events present).

    unavailable
        Evidence is valid and fresh, but the participant is explicitly
        unavailable (``participant_status = "unavailable"`` or
        ``is_operational = false`` with no audit events).

    recovered
        Evidence is valid and fresh, and the participant reports a recovered
        state (``participant_status = "recovered"``).

    missing_evidence
        No evidence artifact file was found.

    malformed_evidence
        An evidence file was found but failed parsing or schema validation.

    stale_evidence
        An evidence file was found and parsed, but its ``generated_at``
        timestamp exceeds the configured maximum age.

    unverified
        Evidence is valid and fresh, but insufficient to reach a conclusive
        determination.
    """

    ready = "ready"
    degraded = "degraded"
    unavailable = "unavailable"
    recovered = "recovered"
    missing_evidence = "missing_evidence"
    malformed_evidence = "malformed_evidence"
    stale_evidence = "stale_evidence"
    unverified = "unverified"

    @property
    def is_positive(self) -> bool:
        """Return True for statuses that indicate the participant is operational."""
        return self in (
            AndroidParticipantStatus.ready,
            AndroidParticipantStatus.recovered,
        )

    @property
    def is_negative(self) -> bool:
        """Return True for statuses that indicate the participant is not ready."""
        return self in (
            AndroidParticipantStatus.degraded,
            AndroidParticipantStatus.unavailable,
            AndroidParticipantStatus.missing_evidence,
            AndroidParticipantStatus.malformed_evidence,
            AndroidParticipantStatus.stale_evidence,
            AndroidParticipantStatus.unverified,
        )

    @property
    def has_evidence(self) -> bool:
        """Return True when an evidence artifact was found and parsed."""
        return self not in (
            AndroidParticipantStatus.missing_evidence,
            AndroidParticipantStatus.malformed_evidence,
        )


# ---------------------------------------------------------------------------
# AndroidParticipantEvidenceResult dataclass
# ---------------------------------------------------------------------------

_REQUIRED_EVIDENCE_FIELDS = frozenset(
    {"schema_version", "authority", "generated_at", "participant_status",
     "is_operational", "audit_event_count"}
)


@dataclass(frozen=True)
class AndroidParticipantEvidenceResult:
    """Typed, immutable result of one Android participant evidence ingestion attempt.

    Attributes
    ----------
    result_id
        Unique identifier for this result (``aper_`` prefix + UUID4 hex).
    status
        The :class:`AndroidParticipantStatus` derived from the evidence.
    evidence_summary
        Human-readable summary of the evidence ingestion outcome.
    gap_description
        Non-empty description of the gap when ``status`` is not ready/recovered.
    raw_evidence
        The parsed evidence dict as loaded from the JSON artifact, or ``{}``
        when the artifact was absent or malformed.
    evidence_path
        The file path that was probed for evidence.
    ingested_at
        Unix timestamp when this ingestion attempt was performed.
    age_seconds
        Age of the evidence in seconds (``ingested_at - generated_at``), or
        ``-1.0`` when not computable.
    participant_status_raw
        The raw ``participant_status`` string from the evidence, or ``""``
        when absent.
    is_operational
        The ``is_operational`` boolean from the evidence, or ``None`` when absent.
    audit_event_count
        The ``audit_event_count`` int from the evidence, or ``0`` when absent.
    reject_reason
        Machine-readable reject reason tag (e.g. ``"file_not_found"``,
        ``"json_parse_error"``, ``"schema_version_mismatch"``).
    """

    result_id: str = field(
        default_factory=lambda: f"aper_{uuid.uuid4().hex[:12]}"
    )
    status: AndroidParticipantStatus = AndroidParticipantStatus.missing_evidence
    evidence_summary: str = ""
    gap_description: str = ""
    raw_evidence: Dict[str, Any] = field(default_factory=dict)
    evidence_path: str = ""
    ingested_at: float = field(default_factory=time.time)
    age_seconds: float = -1.0
    participant_status_raw: str = ""
    is_operational: Optional[bool] = None
    audit_event_count: int = 0
    reject_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "result_id": self.result_id,
            "status": self.status.value,
            "evidence_summary": self.evidence_summary,
            "gap_description": self.gap_description,
            "raw_evidence": dict(self.raw_evidence),
            "evidence_path": self.evidence_path,
            "ingested_at": self.ingested_at,
            "age_seconds": self.age_seconds,
            "participant_status_raw": self.participant_status_raw,
            "is_operational": self.is_operational,
            "audit_event_count": self.audit_event_count,
            "reject_reason": self.reject_reason,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict(), default=str)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_evidence_path() -> str:
    """Return the configured Android participant evidence file path.

    Resolution order:
    1. ``ANDROID_PARTICIPANT_EVIDENCE_PATH`` environment variable.
    2. ``android_participant_evidence.json`` in the current working directory.
    """
    env_path = os.environ.get(_ENV_EVIDENCE_PATH, "").strip()
    if env_path:
        return env_path
    return os.path.join(os.getcwd(), _DEFAULT_EVIDENCE_FILENAME)


def _get_max_age_seconds() -> float:
    """Return the configured maximum evidence age in seconds."""
    raw = os.environ.get(_ENV_MAX_AGE, "").strip()
    if raw:
        try:
            val = float(raw)
            if val > 0:
                return val
        except ValueError:
            pass
    return float(_DEFAULT_MAX_AGE_SECONDS)


def _validate_schema(data: Dict[str, Any]) -> Optional[str]:
    """Validate the evidence dict schema.

    Returns ``None`` on success, or a reject-reason string on failure.
    """
    # Check required fields
    missing = _REQUIRED_EVIDENCE_FIELDS - set(data.keys())
    if missing:
        return f"missing_required_fields:{','.join(sorted(missing))}"

    # Check authority
    authority = str(data.get("authority", "")).strip()
    if authority != EXPECTED_AUTHORITY_SENTINEL:
        return f"authority_mismatch:got={authority!r}"

    # Check schema_version
    version = str(data.get("schema_version", "")).strip()
    if version != ANDROID_PARTICIPANT_EVIDENCE_CONTRACT_VERSION:
        return f"schema_version_mismatch:got={version!r}"

    # Check generated_at is a number
    generated_at = data.get("generated_at")
    if not isinstance(generated_at, (int, float)):
        return "generated_at_not_numeric"

    # Check is_operational is bool
    is_op = data.get("is_operational")
    if not isinstance(is_op, bool):
        return "is_operational_not_bool"

    # Check audit_event_count is non-negative int
    count = data.get("audit_event_count")
    if not isinstance(count, int) or count < 0:
        return "audit_event_count_invalid"

    return None  # valid


def _derive_status(
    data: Dict[str, Any],
    age_seconds: float,
    max_age: float,
) -> tuple[AndroidParticipantStatus, str, str]:
    """Derive the status, evidence_summary, and gap_description from valid, fresh evidence.

    Parameters
    ----------
    data:
        Validated evidence dict.
    age_seconds:
        Evidence age in seconds.
    max_age:
        Maximum allowed age in seconds.

    Returns
    -------
    (status, evidence_summary, gap_description)
    """
    raw_ps = str(data.get("participant_status", "")).strip().lower()
    is_op: bool = bool(data.get("is_operational", False))
    count: int = int(data.get("audit_event_count", 0))
    device_id = str(data.get("device_id", "")).strip() or "<unknown>"
    session_id = str(data.get("session_id", "")).strip() or "<unknown>"

    # --- recovered ---
    if raw_ps == "recovered":
        return (
            AndroidParticipantStatus.recovered,
            (
                f"Android participant recovered: device={device_id} "
                f"session={session_id} is_operational={is_op} "
                f"audit_events={count} age={age_seconds:.1f}s."
            ),
            (
                "Android participant reports recovered status. "
                "Operational continuity should be verified if recovery was recent."
            ) if not is_op else "",
        )

    # --- unavailable (explicit) ---
    if raw_ps == "unavailable":
        return (
            AndroidParticipantStatus.unavailable,
            (
                f"Android participant unavailable: device={device_id} "
                f"session={session_id} audit_events={count} age={age_seconds:.1f}s."
            ),
            (
                "Android participant explicitly reports unavailable status. "
                "Platform cannot be accepted as fully-operational."
            ),
        )

    # --- degraded (explicit) ---
    if raw_ps == "degraded":
        return (
            AndroidParticipantStatus.degraded,
            (
                f"Android participant degraded: device={device_id} "
                f"session={session_id} is_operational={is_op} "
                f"audit_events={count} age={age_seconds:.1f}s."
            ),
            (
                "Android participant explicitly reports degraded status. "
                "Acceptance verdict will reflect degraded participant state."
            ),
        )

    # --- ready (explicit or inferred) ---
    if raw_ps == "ready" and is_op and count > 0:
        return (
            AndroidParticipantStatus.ready,
            (
                f"Android participant ready: device={device_id} "
                f"session={session_id} is_operational=True "
                f"audit_events={count} age={age_seconds:.1f}s."
            ),
            "",
        )

    # --- inferred ready (is_operational + events, even without explicit "ready") ---
    if is_op and count > 0:
        return (
            AndroidParticipantStatus.ready,
            (
                f"Android participant ready (inferred): device={device_id} "
                f"session={session_id} is_operational=True "
                f"audit_events={count} age={age_seconds:.1f}s."
            ),
            "",
        )

    # --- inferred unavailable (is_operational=false, no events, no explicit status) ---
    if not is_op and count == 0:
        return (
            AndroidParticipantStatus.unavailable,
            (
                f"Android participant unavailable (inferred): device={device_id} "
                f"session={session_id} is_operational=False "
                f"audit_events=0 age={age_seconds:.1f}s."
            ),
            (
                "Android participant is not operational and has no audit events. "
                "Treated as unavailable."
            ),
        )

    # --- inferred degraded (is_operational=false but has events) ---
    if not is_op and count > 0:
        return (
            AndroidParticipantStatus.degraded,
            (
                f"Android participant degraded (inferred): device={device_id} "
                f"session={session_id} is_operational=False "
                f"audit_events={count} age={age_seconds:.1f}s."
            ),
            (
                "Android participant has audit events but is not operational. "
                "Treated as degraded."
            ),
        )

    # --- fallback: unverified ---
    return (
        AndroidParticipantStatus.unverified,
        (
            f"Android participant unverified: device={device_id} "
            f"session={session_id} participant_status={raw_ps!r} "
            f"is_operational={is_op} audit_events={count} age={age_seconds:.1f}s."
        ),
        (
            f"Android evidence is valid and fresh but cannot be conclusively "
            f"classified. participant_status={raw_ps!r} is_operational={is_op} "
            f"audit_event_count={count}. Treat as unverified."
        ),
    )


# ---------------------------------------------------------------------------
# Public ingestion function
# ---------------------------------------------------------------------------


def ingest_android_participant_evidence(
    *,
    evidence_path: Optional[str] = None,
    max_age_seconds: Optional[float] = None,
    _now: Optional[float] = None,
) -> AndroidParticipantEvidenceResult:
    """Ingest Android participant runtime evidence from a JSON artifact file.

    This is the primary entry-point for the Android participant evidence
    ingestion layer.  It performs the following steps:

    1. Resolve the evidence file path (parameter → env var → default).
    2. Attempt to load and parse the JSON artifact.
    3. Validate the schema (required fields, authority, version, types).
    4. Check evidence freshness (``generated_at`` vs current time).
    5. Derive a precise :class:`AndroidParticipantStatus` from the content.
    6. Return a typed :class:`AndroidParticipantEvidenceResult`.

    Parameters
    ----------
    evidence_path:
        Optional override for the evidence file path.  Defaults to the
        ``ANDROID_PARTICIPANT_EVIDENCE_PATH`` env var or CWD default.
    max_age_seconds:
        Optional override for the maximum evidence age in seconds.  Defaults
        to the ``ANDROID_PARTICIPANT_EVIDENCE_MAX_AGE_SECONDS`` env var or
        3600 s.
    _now:
        Optional override for the current time (for testing only).

    Returns
    -------
    AndroidParticipantEvidenceResult
        Never raises; all error paths return a typed result with a non-ready
        status.
    """
    resolved_path = evidence_path or _get_evidence_path()
    resolved_max_age = max_age_seconds if max_age_seconds is not None else _get_max_age_seconds()
    now = _now if _now is not None else time.time()
    ingested_at = now

    # ------------------------------------------------------------------
    # Step 1: Read the file
    # ------------------------------------------------------------------
    try:
        with open(resolved_path, "r", encoding="utf-8") as fh:
            raw_text = fh.read()
    except FileNotFoundError:
        logger.debug(
            "AndroidParticipantEvidenceIngress: evidence file not found: %s",
            resolved_path,
        )
        return AndroidParticipantEvidenceResult(
            status=AndroidParticipantStatus.missing_evidence,
            evidence_summary=(
                f"Android participant evidence file not found: {resolved_path}"
            ),
            gap_description=(
                "No Android participant evidence artifact was found at the "
                f"configured path ({resolved_path}).  The Android participant "
                "dimension cannot be evaluated without evidence.  Produce a "
                "valid android_participant_evidence.json artifact and set "
                f"ANDROID_PARTICIPANT_EVIDENCE_PATH to its path."
            ),
            evidence_path=resolved_path,
            ingested_at=ingested_at,
            reject_reason="file_not_found",
        )
    except OSError as exc:
        return AndroidParticipantEvidenceResult(
            status=AndroidParticipantStatus.missing_evidence,
            evidence_summary=(
                f"Android participant evidence file unreadable: {exc}"
            ),
            gap_description=(
                f"Evidence file at {resolved_path!r} could not be read: {exc}"
            ),
            evidence_path=resolved_path,
            ingested_at=ingested_at,
            reject_reason=f"file_read_error:{type(exc).__name__}",
        )

    # ------------------------------------------------------------------
    # Step 2: Parse JSON
    # ------------------------------------------------------------------
    try:
        data: Dict[str, Any] = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        logger.debug(
            "AndroidParticipantEvidenceIngress: JSON parse error: %s", exc
        )
        return AndroidParticipantEvidenceResult(
            status=AndroidParticipantStatus.malformed_evidence,
            evidence_summary=(
                f"Android participant evidence file is not valid JSON: {exc}"
            ),
            gap_description=(
                f"Evidence file at {resolved_path!r} failed JSON parsing: {exc}.  "
                "Malformed evidence cannot be used to assess Android participant "
                "status.  Fix the artifact and re-ingest."
            ),
            evidence_path=resolved_path,
            ingested_at=ingested_at,
            reject_reason=f"json_parse_error:{exc.msg}",
        )

    if not isinstance(data, dict):
        return AndroidParticipantEvidenceResult(
            status=AndroidParticipantStatus.malformed_evidence,
            evidence_summary=(
                "Android participant evidence is not a JSON object."
            ),
            gap_description=(
                "Evidence file must contain a JSON object (dict) at the top level."
            ),
            evidence_path=resolved_path,
            ingested_at=ingested_at,
            reject_reason="not_a_dict",
        )

    # ------------------------------------------------------------------
    # Step 3: Validate schema
    # ------------------------------------------------------------------
    validation_error = _validate_schema(data)
    if validation_error:
        logger.debug(
            "AndroidParticipantEvidenceIngress: schema validation failed: %s",
            validation_error,
        )
        return AndroidParticipantEvidenceResult(
            status=AndroidParticipantStatus.malformed_evidence,
            evidence_summary=(
                f"Android participant evidence failed schema validation: "
                f"{validation_error}"
            ),
            gap_description=(
                f"Evidence schema validation failed ({validation_error}).  "
                "Malformed evidence is treated as non-ready.  Ensure the "
                "Android side produces artifacts conforming to schema_version "
                f"{ANDROID_PARTICIPANT_EVIDENCE_CONTRACT_VERSION!r} and "
                f"authority {EXPECTED_AUTHORITY_SENTINEL!r}."
            ),
            raw_evidence=data,
            evidence_path=resolved_path,
            ingested_at=ingested_at,
            reject_reason=validation_error,
        )

    # ------------------------------------------------------------------
    # Step 4: Check staleness
    # ------------------------------------------------------------------
    generated_at = float(data["generated_at"])
    age_seconds = now - generated_at

    if age_seconds > resolved_max_age:
        return AndroidParticipantEvidenceResult(
            status=AndroidParticipantStatus.stale_evidence,
            evidence_summary=(
                f"Android participant evidence is stale: age={age_seconds:.1f}s "
                f"(max={resolved_max_age:.0f}s)."
            ),
            gap_description=(
                f"Evidence generated_at={generated_at} is "
                f"{age_seconds:.1f}s old, exceeding the maximum age of "
                f"{resolved_max_age:.0f}s.  Stale evidence cannot be used to "
                "confirm current Android participant readiness.  Refresh the "
                "evidence artifact."
            ),
            raw_evidence=data,
            evidence_path=resolved_path,
            ingested_at=ingested_at,
            age_seconds=age_seconds,
            participant_status_raw=str(data.get("participant_status", "")),
            is_operational=bool(data.get("is_operational", False)),
            audit_event_count=int(data.get("audit_event_count", 0)),
            reject_reason="stale_evidence",
        )

    # ------------------------------------------------------------------
    # Step 5: Derive status
    # ------------------------------------------------------------------
    status, evidence_summary, gap_description = _derive_status(
        data, age_seconds, resolved_max_age
    )

    return AndroidParticipantEvidenceResult(
        status=status,
        evidence_summary=evidence_summary,
        gap_description=gap_description,
        raw_evidence=data,
        evidence_path=resolved_path,
        ingested_at=ingested_at,
        age_seconds=age_seconds,
        participant_status_raw=str(data.get("participant_status", "")),
        is_operational=bool(data.get("is_operational", False)),
        audit_event_count=int(data.get("audit_event_count", 0)),
    )


# ---------------------------------------------------------------------------
# Convenience summary builder (for governance / audit surfaces)
# ---------------------------------------------------------------------------


def build_android_participant_evidence_summary(
    result: Optional[AndroidParticipantEvidenceResult] = None,
) -> Dict[str, Any]:
    """Build a governance/audit summary dict for the Android participant evidence.

    If *result* is ``None``, a fresh ingestion attempt is performed.

    Returns
    -------
    dict
        A JSON-safe dict suitable for inclusion in governance reports,
        evidence surfaces, and audit outputs.
    """
    if result is None:
        result = ingest_android_participant_evidence()
    return {
        "android_participant_status": result.status.value,
        "evidence_summary": result.evidence_summary,
        "gap_description": result.gap_description,
        "evidence_path": result.evidence_path,
        "age_seconds": result.age_seconds,
        "is_operational": result.is_operational,
        "audit_event_count": result.audit_event_count,
        "participant_status_raw": result.participant_status_raw,
        "reject_reason": result.reject_reason,
        "ingested_at": result.ingested_at,
        "result_id": result.result_id,
    }


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Authority sentinels
    "ANDROID_PARTICIPANT_EVIDENCE_INGRESS_AUTHORITY",
    "ANDROID_PARTICIPANT_EVIDENCE_CONTRACT_VERSION",
    "EXPECTED_AUTHORITY_SENTINEL",
    # Policy sentinels
    "EVIDENCE_PATH_IS_CONFIGURABLE_POLICY",
    "FAIL_CONSERVATIVE_ON_MISSING_EVIDENCE_POLICY",
    "STALE_EVIDENCE_IS_NOT_READY_POLICY",
    "MALFORMED_EVIDENCE_IS_NOT_READY_POLICY",
    "PARTICIPANT_STATUS_DERIVED_FROM_EVIDENCE_POLICY",
    "EVIDENCE_VISIBLE_IN_SUMMARY_POLICY",
    # Enum
    "AndroidParticipantStatus",
    # Dataclass
    "AndroidParticipantEvidenceResult",
    # Functions
    "ingest_android_participant_evidence",
    "build_android_participant_evidence_summary",
]
