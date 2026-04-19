"""contracts/contract_compatibility.py
=========================================
Contract Validation and Compatibility Coverage — PR-H.

This module provides **canonical validation and backward-compatibility
checking** for the evolved multi-device runtime dispatch contracts.  It
answers the architectural question:

    *"Can the runtime's canonical envelopes, dispatch plans, and
    execution contracts evolve safely without silent semantic breakage
    during staged migration?"*

As the runtime expands across:

- **PR-A** — device lifecycle integration
- **PR-B** — mesh session lifecycle
- **PR-D** — source dispatch orchestration
- **PR-E** — explicit executor target typing
- **PR-F** — continuity/recovery metadata
- **PR-G** — observability/tracing metadata

… each dimension adds optional fields to the canonical contracts.  The
goal of this module is to make those additions **testable and explicit**,
not relying on informal assumptions.

This module provides:

- Sentinel constants affirming the compatibility policy (see below).
- :func:`validate_task_envelope_contract` — validates that a serialised
  ``TaskEnvelope`` dict conforms to the canonical shape expected by
  multi-device runtime participants.
- :func:`validate_source_dispatch_plan_contract` — validates that a
  serialised ``SourceDispatchPlan`` dict conforms to the canonical shape.
- :func:`validate_source_dispatch_result_contract` — validates that a
  serialised ``SourceDispatchResult`` dict conforms to the canonical shape.
- :func:`check_envelope_backward_compatibility` — returns a structured
  :class:`EvolutionCompatibilityReport` indicating which evolved fields
  are present and which are absent (absent is not an error — it means
  the envelope was produced by an older participant).
- :func:`check_dispatch_plan_backward_compatibility` — equivalent check
  for ``SourceDispatchPlan``.
- :func:`check_dispatch_result_backward_compatibility` — equivalent check
  for ``SourceDispatchResult``.
- :class:`EvolutionCompatibilityReport` — structured compatibility report
  produced by the check functions.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Never raises** — all public functions tolerate missing / malformed
  inputs and return structured reports rather than raising.
- **Backward compatible** — absent evolved fields are reported as
  ``absent`` (not errors); only structurally invalid values are flagged.
- **Fully serialisable** — :class:`EvolutionCompatibilityReport` round-trips
  through ``to_dict`` / ``from_dict``.

Sentinels
---------
:data:`CONTRACT_VALIDATION_IS_AUTHORITY`
    Affirms this module as the canonical contract validation and
    backward-compatibility authority for PR-H.
:data:`EVOLVED_FIELDS_ARE_OPTIONAL_BACKWARD_COMPAT_POLICY`
    Affirms that all fields added after the initial contract baseline
    (PR-E, PR-F, PR-G) are optional and MUST be tolerated as absent by
    all runtime participants.
:data:`CONTRACT_EVOLUTION_IS_EXPLICIT_POLICY`
    Affirms that contract evolution is made explicit via validation
    functions and compatibility reports rather than informal assumptions.
:data:`STAGED_MIGRATION_IS_SAFE_POLICY`
    Affirms that participants at different migration stages can exchange
    envelopes safely because all evolved fields default to ``None`` /
    empty and unknown extra fields are ignored.

Usage::

    from contracts.contract_compatibility import (
        check_envelope_backward_compatibility,
        check_dispatch_plan_backward_compatibility,
        validate_task_envelope_contract,
        EvolutionCompatibilityReport,
    )

    # Validate a freshly-built envelope dict
    report = check_envelope_backward_compatibility(env.model_dump())
    assert report.is_compatible

    # Or validate the shape explicitly
    result = validate_task_envelope_contract(env.model_dump())
    assert result["valid"]
"""

from __future__ import annotations

import json
import uuid
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

CONTRACT_VALIDATION_IS_AUTHORITY: str = (
    "CONTRACT_VALIDATION_IS_AUTHORITY: "
    "contracts/contract_compatibility.py is the canonical contract validation "
    "and backward-compatibility checking authority for PR-H.  It provides "
    "structured EvolutionCompatibilityReport records for all evolved runtime "
    "contracts (TaskEnvelope, SourceDispatchPlan, SourceDispatchResult) so that "
    "contract evolution becomes testable and explicit rather than relying on "
    "informal assumptions.  PR-H."
)

EVOLVED_FIELDS_ARE_OPTIONAL_BACKWARD_COMPAT_POLICY: str = (
    "POLICY::EVOLVED_FIELDS_ARE_OPTIONAL_BACKWARD_COMPAT_PR-H: "
    "All fields added to canonical runtime contracts after the initial baseline "
    "(executor_target_type from PR-E, continuity_context from PR-F, "
    "observability/tracing metadata from PR-G) MUST be optional with safe "
    "defaults (None / empty dict / empty list).  A payload that omits these "
    "fields is VALID and represents a pre-evolution participant.  Runtime "
    "components MUST NOT reject or fail on payloads that omit evolved fields.  "
    "PR-H."
)

CONTRACT_EVOLUTION_IS_EXPLICIT_POLICY: str = (
    "POLICY::CONTRACT_EVOLUTION_IS_EXPLICIT_PR-H: "
    "Contract evolution MUST be made explicit via validation functions and "
    "EvolutionCompatibilityReport records rather than relying on informal "
    "assumptions.  Each evolved field (executor_target_type, continuity_context, "
    "observability_metadata, dispatch metadata enrichments) MUST be individually "
    "tracked in compatibility reports so that operators and automated tests can "
    "determine which capabilities a payload carries and which it does not.  PR-H."
)

STAGED_MIGRATION_IS_SAFE_POLICY: str = (
    "POLICY::STAGED_MIGRATION_IS_SAFE_PR-H: "
    "Runtime participants at different migration stages (some with PR-E/F/G "
    "evolved fields, some without) MUST be able to exchange envelopes, dispatch "
    "plans, and results without error.  This is guaranteed by: "
    "(1) all evolved fields defaulting to None/empty; "
    "(2) Pydantic extra='allow' on all canonical models; "
    "(3) from_dict/model_validate ignoring unknown extra fields.  "
    "PR-H validates these guarantees explicitly."
)

CONTRACT_COMPATIBILITY_PR_H_SENTINEL: str = (
    "CONTRACT_COMPATIBILITY_PR_H_SENTINEL: "
    "PR-H contract validation and compatibility coverage contracts are present "
    "and active.  EvolutionCompatibilityReport, validate_* and check_* functions "
    "are ready for use by runtime participants and automated contract tests."
)


# ---------------------------------------------------------------------------
# EvolutionCompatibilityReport — structured compatibility report
# ---------------------------------------------------------------------------

# Fields introduced after the baseline that are tracked for compatibility.

# PR-E evolved fields (added by the executor target typing PR)
_PR_E_EVOLVED_FIELDS = ("executor_target_type",)

# PR-F evolved fields (added by the continuity/recovery context PR)
_PR_F_EVOLVED_FIELDS = ("continuity_context",)

# PR-G evolved fields — stored inside the metadata dict rather than at top level
_PR_G_OBSERVABILITY_META_KEY = "observability_metadata"

# All evolved field names tracked for compatibility reports (top-level keys only)
_ALL_EVOLVED_FIELD_NAMES = list(_PR_E_EVOLVED_FIELDS) + list(_PR_F_EVOLVED_FIELDS)

# Canonical required shape keys for TaskEnvelope
_TASK_ENVELOPE_REQUIRED_SHAPE_KEYS = ("task_id", "trace_id")

# Canonical required shape keys for SourceDispatchPlan
_DISPATCH_PLAN_REQUIRED_SHAPE_KEYS = ("plan_id", "mode")

# Canonical required shape keys for SourceDispatchResult
_DISPATCH_RESULT_REQUIRED_SHAPE_KEYS = ("result_id", "mode", "success")


@dataclass
class EvolutionCompatibilityReport:
    """Structured report produced by backward-compatibility check functions.

    Fields
    ------
    report_id
        Unique identifier for this report (hex UUID).
    contract_kind
        The kind of contract that was checked:
        ``'task_envelope'``, ``'source_dispatch_plan'``, or
        ``'source_dispatch_result'``.
    is_compatible
        ``True`` when the payload is structurally valid and backward-
        compatible.  Absent evolved fields do not affect this flag.
    has_executor_target_type
        ``True`` when the payload carries the PR-E ``executor_target_type``
        field with a non-``None`` value.
    has_continuity_context
        ``True`` when the payload carries the PR-F ``continuity_context``
        field with a non-``None`` value.
    has_observability_metadata
        ``True`` when the payload carries a PR-G ``observability_metadata``
        dict in its top-level ``metadata``.
    has_source_runtime_posture
        ``True`` when the payload carries the ``source_runtime_posture`` field
        with a non-empty value.
    missing_evolved_fields
        List of evolved field names that are absent from this payload.
        Absence is not an error — it marks a pre-evolution participant.
    present_evolved_fields
        List of evolved field names that are present in this payload.
    validation_errors
        List of structural validation errors.  Empty when ``is_compatible``
        is ``True``.
    notes
        Human-readable compatibility notes for operators / test output.
    timestamp
        Unix timestamp when this report was generated.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    contract_kind: str = "unknown"
    is_compatible: bool = True
    has_executor_target_type: bool = False
    has_continuity_context: bool = False
    has_observability_metadata: bool = False
    has_source_runtime_posture: bool = False
    missing_evolved_fields: List[str] = field(default_factory=list)
    present_evolved_fields: List[str] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe dictionary representation."""
        return {
            "report_id": self.report_id,
            "contract_kind": self.contract_kind,
            "is_compatible": self.is_compatible,
            "has_executor_target_type": self.has_executor_target_type,
            "has_continuity_context": self.has_continuity_context,
            "has_observability_metadata": self.has_observability_metadata,
            "has_source_runtime_posture": self.has_source_runtime_posture,
            "missing_evolved_fields": list(self.missing_evolved_fields),
            "present_evolved_fields": list(self.present_evolved_fields),
            "validation_errors": list(self.validation_errors),
            "notes": list(self.notes),
            "timestamp": self.timestamp,
        }

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Return a stable JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvolutionCompatibilityReport":
        """Construct from a dictionary.  Tolerates unknown extra fields."""
        return cls(
            report_id=data.get("report_id", uuid.uuid4().hex),
            contract_kind=data.get("contract_kind", "unknown"),
            is_compatible=bool(data.get("is_compatible", True)),
            has_executor_target_type=bool(data.get("has_executor_target_type", False)),
            has_continuity_context=bool(data.get("has_continuity_context", False)),
            has_observability_metadata=bool(data.get("has_observability_metadata", False)),
            has_source_runtime_posture=bool(data.get("has_source_runtime_posture", False)),
            missing_evolved_fields=list(data.get("missing_evolved_fields", [])),
            present_evolved_fields=list(data.get("present_evolved_fields", [])),
            validation_errors=list(data.get("validation_errors", [])),
            notes=list(data.get("notes", [])),
            timestamp=float(data.get("timestamp", time.time())),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _check_evolved_fields(
    payload: Dict[str, Any],
    report: EvolutionCompatibilityReport,
) -> None:
    """Populate ``present_evolved_fields`` / ``missing_evolved_fields`` on *report*.

    Iterates over all known evolved field names and classifies each as
    present or missing.  PR-G observability metadata is detected separately
    because it lives inside the top-level ``metadata`` dict rather than as
    its own top-level key.
    """
    # Top-level evolved fields (PR-E and PR-F)
    for fname in _ALL_EVOLVED_FIELD_NAMES:
        if payload.get(fname) is not None:
            report.present_evolved_fields.append(fname)
        else:
            report.missing_evolved_fields.append(fname)

    # Derived boolean flags for convenience
    report.has_executor_target_type = payload.get("executor_target_type") is not None
    report.has_continuity_context = payload.get("continuity_context") is not None

    # source_runtime_posture (introduced by PR-D posture contract)
    posture = payload.get("source_runtime_posture")
    report.has_source_runtime_posture = bool(posture)

    # PR-G observability metadata — lives inside the ``metadata`` dict
    meta = payload.get("metadata")
    has_obs_meta = (
        isinstance(meta, dict)
        and meta.get(_PR_G_OBSERVABILITY_META_KEY) is not None
    )
    report.has_observability_metadata = has_obs_meta
    if has_obs_meta:
        report.present_evolved_fields.append(_PR_G_OBSERVABILITY_META_KEY)
    else:
        report.missing_evolved_fields.append(_PR_G_OBSERVABILITY_META_KEY)


# ---------------------------------------------------------------------------
# validate_task_envelope_contract
# ---------------------------------------------------------------------------


def validate_task_envelope_contract(payload: Any) -> Dict[str, Any]:
    """Validate a serialised ``TaskEnvelope`` dict against the canonical shape.

    This validator checks:
    - ``payload`` is a dict (not None, not a list).
    - Required identity keys (``task_id``, ``trace_id``) are present and
      non-empty strings.
    - ``executor_target_type``, if present, is one of the known values
      (``android_device``, ``node_service``, ``go_worker``, ``local``) or
      ``None``.
    - ``continuity_context``, if present, is a dict or ``None``.
    - ``lifecycle_status``, if present, is one of the known lifecycle values.
    - Extra unknown fields are tolerated (graceful evolution).

    Returns
    -------
    dict
        ``{"valid": bool, "errors": [str], "warnings": [str]}``
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(payload, dict):
        errors.append(
            f"validate_task_envelope_contract: payload must be a dict, got {type(payload).__name__}"
        )
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Required identity fields
    for key in _TASK_ENVELOPE_REQUIRED_SHAPE_KEYS:
        val = payload.get(key)
        if val is None:
            errors.append(f"Missing required field: '{key}'")
        elif not isinstance(val, str) or not val:
            errors.append(f"Field '{key}' must be a non-empty string; got {val!r}")

    # executor_target_type (PR-E) — optional; if present must be known or None
    _valid_executor_types = {"android_device", "node_service", "go_worker", "local"}
    ett = payload.get("executor_target_type")
    if ett is not None and ett not in _valid_executor_types:
        errors.append(
            f"Field 'executor_target_type' has unknown value {ett!r}; "
            f"expected one of {sorted(_valid_executor_types)} or None"
        )

    # continuity_context (PR-F) — optional; if present must be dict or None
    cc = payload.get("continuity_context")
    if cc is not None and not isinstance(cc, dict):
        errors.append(
            f"Field 'continuity_context' must be a dict or None; got {type(cc).__name__}"
        )

    # lifecycle_status — optional; if present should be known value
    _valid_lifecycle = {"created", "running", "done", "failed"}
    ls = payload.get("lifecycle_status")
    if ls is not None and ls not in _valid_lifecycle:
        warnings.append(
            f"Field 'lifecycle_status' has unexpected value {ls!r}; "
            f"expected one of {sorted(_valid_lifecycle)}"
        )

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# validate_source_dispatch_plan_contract
# ---------------------------------------------------------------------------


def validate_source_dispatch_plan_contract(payload: Any) -> Dict[str, Any]:
    """Validate a serialised ``SourceDispatchPlan`` dict.

    Checks:
    - ``payload`` is a dict.
    - Required keys (``plan_id``, ``mode``) are present.
    - ``mode`` is one of the known ``SourceDispatchMode`` values or ``unknown``.
    - ``continuity_context``, if present, is a dict or ``None``.
    - ``source_runtime_posture``, if present, is ``'control_only'`` or
      ``'join_runtime'``.
    - Extra unknown fields are tolerated.

    Returns
    -------
    dict
        ``{"valid": bool, "errors": [str], "warnings": [str]}``
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(payload, dict):
        errors.append(
            f"validate_source_dispatch_plan_contract: payload must be a dict, got {type(payload).__name__}"
        )
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Required fields
    for key in _DISPATCH_PLAN_REQUIRED_SHAPE_KEYS:
        val = payload.get(key)
        if val is None:
            errors.append(f"Missing required field: '{key}'")

    # mode — must be known dispatch mode
    _valid_modes = {"local", "remote_handoff", "staged_mesh", "blocked", "fallback_local", "unknown"}
    mode = payload.get("mode")
    if mode is not None and mode not in _valid_modes:
        errors.append(
            f"Field 'mode' has unknown value {mode!r}; expected one of {sorted(_valid_modes)}"
        )

    # continuity_context (PR-F) — optional; if present must be dict
    cc = payload.get("continuity_context")
    if cc is not None and not isinstance(cc, dict):
        errors.append(
            f"Field 'continuity_context' must be a dict or None; got {type(cc).__name__}"
        )

    # source_runtime_posture — optional; if present should be canonical value
    posture = payload.get("source_runtime_posture")
    if posture is not None and posture not in ("control_only", "join_runtime"):
        warnings.append(
            f"Field 'source_runtime_posture' has non-canonical value {posture!r}; "
            "expected 'control_only' or 'join_runtime'"
        )

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# validate_source_dispatch_result_contract
# ---------------------------------------------------------------------------


def validate_source_dispatch_result_contract(payload: Any) -> Dict[str, Any]:
    """Validate a serialised ``SourceDispatchResult`` dict.

    Checks:
    - ``payload`` is a dict.
    - Required keys (``result_id``, ``mode``, ``success``) are present.
    - ``mode`` is a known dispatch mode.
    - ``success`` is a bool.
    - ``continuity_context``, if present, is a dict or ``None``.
    - Extra unknown fields are tolerated.

    Returns
    -------
    dict
        ``{"valid": bool, "errors": [str], "warnings": [str]}``
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(payload, dict):
        errors.append(
            f"validate_source_dispatch_result_contract: payload must be a dict, got {type(payload).__name__}"
        )
        return {"valid": False, "errors": errors, "warnings": warnings}

    # Required fields
    for key in _DISPATCH_RESULT_REQUIRED_SHAPE_KEYS:
        val = payload.get(key)
        if val is None and key == "result_id":
            errors.append(f"Missing required field: '{key}'")
        elif key == "success" and not isinstance(val, bool):
            errors.append(f"Field 'success' must be a bool; got {type(val).__name__}")
        elif key == "mode" and val is None:
            errors.append(f"Missing required field: '{key}'")

    # mode — must be known
    _valid_modes = {"local", "remote_handoff", "staged_mesh", "blocked", "fallback_local", "unknown"}
    mode = payload.get("mode")
    if mode is not None and mode not in _valid_modes:
        errors.append(
            f"Field 'mode' has unknown value {mode!r}; expected one of {sorted(_valid_modes)}"
        )

    # continuity_context (PR-F) — optional; if present must be dict
    cc = payload.get("continuity_context")
    if cc is not None and not isinstance(cc, dict):
        errors.append(
            f"Field 'continuity_context' must be a dict or None; got {type(cc).__name__}"
        )

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


# ---------------------------------------------------------------------------
# Backward-compatibility check functions
# ---------------------------------------------------------------------------


def check_envelope_backward_compatibility(
    payload: Any,
    *,
    strict: bool = False,
) -> EvolutionCompatibilityReport:
    """Check backward compatibility of a serialised ``TaskEnvelope`` payload.

    Returns an :class:`EvolutionCompatibilityReport` indicating which evolved
    fields are present and whether the payload is structurally valid.

    Parameters
    ----------
    payload:
        A serialised ``TaskEnvelope`` dict (e.g. from ``model_dump()``).
    strict:
        When ``True``, missing evolved fields are counted as warnings in
        ``notes``.  When ``False`` (default) absence of evolved fields is
        silently recorded in ``missing_evolved_fields`` only.
    """
    report = EvolutionCompatibilityReport(contract_kind="task_envelope")

    if not isinstance(payload, dict):
        report.is_compatible = False
        report.validation_errors.append(
            "check_envelope_backward_compatibility: payload is not a dict"
        )
        return report

    # Run structural validation
    result = validate_task_envelope_contract(payload)
    if not result["valid"]:
        report.is_compatible = False
        report.validation_errors.extend(result["errors"])

    # Check evolved fields
    _check_evolved_fields(payload, report)

    if strict and report.missing_evolved_fields:
        report.notes.append(
            f"Strict mode: missing evolved fields: {report.missing_evolved_fields}"
        )

    return report


def check_dispatch_plan_backward_compatibility(
    payload: Any,
    *,
    strict: bool = False,
) -> EvolutionCompatibilityReport:
    """Check backward compatibility of a serialised ``SourceDispatchPlan`` payload.

    Parameters
    ----------
    payload:
        A serialised ``SourceDispatchPlan`` dict (e.g. from ``to_dict()``).
    strict:
        When ``True``, missing evolved fields are recorded as notes.
    """
    report = EvolutionCompatibilityReport(contract_kind="source_dispatch_plan")

    if not isinstance(payload, dict):
        report.is_compatible = False
        report.validation_errors.append(
            "check_dispatch_plan_backward_compatibility: payload is not a dict"
        )
        return report

    result = validate_source_dispatch_plan_contract(payload)
    if not result["valid"]:
        report.is_compatible = False
        report.validation_errors.extend(result["errors"])

    _check_evolved_fields(payload, report)

    if strict and report.missing_evolved_fields:
        report.notes.append(
            f"Strict mode: missing evolved fields: {report.missing_evolved_fields}"
        )

    return report


def check_dispatch_result_backward_compatibility(
    payload: Any,
    *,
    strict: bool = False,
) -> EvolutionCompatibilityReport:
    """Check backward compatibility of a serialised ``SourceDispatchResult`` payload.

    Parameters
    ----------
    payload:
        A serialised ``SourceDispatchResult`` dict (e.g. from ``to_dict()``).
    strict:
        When ``True``, missing evolved fields are recorded as notes.
    """
    report = EvolutionCompatibilityReport(contract_kind="source_dispatch_result")

    if not isinstance(payload, dict):
        report.is_compatible = False
        report.validation_errors.append(
            "check_dispatch_result_backward_compatibility: payload is not a dict"
        )
        return report

    result = validate_source_dispatch_result_contract(payload)
    if not result["valid"]:
        report.is_compatible = False
        report.validation_errors.extend(result["errors"])

    _check_evolved_fields(payload, report)

    if strict and report.missing_evolved_fields:
        report.notes.append(
            f"Strict mode: missing evolved fields: {report.missing_evolved_fields}"
        )

    return report
