"""core/posture_contract_canonicalization.py
=============================================
Posture Contract Canonicalization — PR package 1 (MAIN repo side).

Post-533 dual-repo runtime unification master plan.

This module is the **canonical enforcement layer** for
``source_runtime_posture`` on the main repo side.  Its purpose is to:

1. Declare ``source_runtime_posture`` as the single, formally centralized
   contract authority for source-device runtime participation semantics.
2. Enforce clear boundaries between ``source_runtime_posture`` and adjacent
   concepts (``entry_mode``, ``cross_device_enabled``, formation roles, etc.).
3. Provide normalisation and validation helpers that operate at the
   *contract layer* (i.e. without importing ``core/source_runtime_posture.py``
   internals), so these routines are safe to call from both ``core/`` and
   ``contracts/`` consumers.
4. Carry policy sentinels that CI / static analysis can verify.

Design principles
-----------------
- This module is **additive only** — it does not modify any existing module.
- All validation logic delegates to ``contracts.source_posture_contract``
  (the canonical schema layer), never to ``core.source_runtime_posture``
  directly.
- Functions are pure or operate on plain dicts; they never mutate objects
  they do not own.
- The module is intentionally side-effect-free at import time.

Policy sentinels exported
--------------------------
POSTURE_CONTRACT_CANONICALIZATION_AUTHORITY
    Declares this module as the canonical enforcement layer for
    ``source_runtime_posture`` on the main repo side (PR package 1).

POSTURE_BOUNDARY_NO_ENTRY_MODE_CONFLATION_POLICY
    Asserts that ``entry_mode`` (execution-path selection) must never be
    used as a proxy or substitute for ``source_runtime_posture``.

POSTURE_BOUNDARY_NO_CROSS_DEVICE_FLAG_CONFLATION_POLICY
    Asserts that ``cross_device_enabled`` (global feature gate) must never
    encode participation posture.

POSTURE_BOUNDARY_NO_FORMATION_ROLE_CONFLATION_POLICY
    Asserts that formation/coordination roles must never substitute for the
    canonical posture value.

POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL
    Confirms this module is the PR package 1 delivery for the post-533
    dual-repo runtime unification master plan (MAIN repo side).

Usage::

    from core.posture_contract_canonicalization import (
        canonicalize_posture_in_payload,
        validate_posture_field_consistency,
        PostureBoundaryViolation,
        assert_posture_boundary_compliance,
        POSTURE_CONTRACT_CANONICALIZATION_AUTHORITY,
        POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL,
    )

    # Normalize posture in an arbitrary API payload dict
    payload = {"source_runtime_posture": "JOIN_RUNTIME", "entry_mode": "cross_device"}
    canonical = canonicalize_posture_in_payload(payload)
    assert canonical["source_runtime_posture"] == "join_runtime"

    # Check that a model dict does not conflate posture with adjacent fields
    ok, violations = validate_posture_field_consistency(payload)
    assert ok  # entry_mode != "join_runtime" so no conflation

    # Assert no boundary violations (raises PostureBoundaryViolation on failure)
    assert_posture_boundary_compliance(canonical)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    # Enforcement helpers
    "canonicalize_posture_in_payload",
    "validate_posture_field_consistency",
    "assert_posture_boundary_compliance",
    # Exception
    "PostureBoundaryViolation",
    # Sentinels / policy markers
    "POSTURE_CONTRACT_CANONICALIZATION_AUTHORITY",
    "POSTURE_BOUNDARY_NO_ENTRY_MODE_CONFLATION_POLICY",
    "POSTURE_BOUNDARY_NO_CROSS_DEVICE_FLAG_CONFLATION_POLICY",
    "POSTURE_BOUNDARY_NO_FORMATION_ROLE_CONFLATION_POLICY",
    "POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL",
    "POSTURE_CONTRACT_LAYER_POSITION",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

POSTURE_CONTRACT_CANONICALIZATION_AUTHORITY: str = (
    "POSTURE_CONTRACT_CANONICALIZATION::AUTHORITY_V1: "
    "Canonical enforcement layer for source_runtime_posture on the main repo side. "
    "All ingress validation, model normalisation, and boundary enforcement MUST "
    "flow through this module or contracts.source_posture_contract — not directly "
    "through core.source_runtime_posture.  PR package 1 of the post-533 dual-repo "
    "runtime unification master plan."
)

POSTURE_CONTRACT_LAYER_POSITION: int = 9

POSTURE_BOUNDARY_NO_ENTRY_MODE_CONFLATION_POLICY: str = (
    "POSTURE_CONTRACT_CANONICALIZATION::NO_ENTRY_MODE_CONFLATION_V1: "
    "entry_mode encodes execution-path selection (local / cross_device / hybrid) "
    "only.  It must never be used as a proxy for source_runtime_posture.  "
    "Posture (control_only vs join_runtime) is orthogonal to execution path."
)

POSTURE_BOUNDARY_NO_CROSS_DEVICE_FLAG_CONFLATION_POLICY: str = (
    "POSTURE_CONTRACT_CANONICALIZATION::NO_CROSS_DEVICE_FLAG_CONFLATION_V1: "
    "cross_device_enabled is a global on/off feature gate.  It must never "
    "encode participation posture.  A device may have cross_device_enabled=True "
    "while still carrying source_runtime_posture='control_only'."
)

POSTURE_BOUNDARY_NO_FORMATION_ROLE_CONFLATION_POLICY: str = (
    "POSTURE_CONTRACT_CANONICALIZATION::NO_FORMATION_ROLE_CONFLATION_V1: "
    "formation_role and coordination_role describe multi-device structural "
    "assignments.  They must never substitute for source_runtime_posture.  "
    "A device's posture is determined before and independently of role assignment."
)

POSTURE_CONTRACT_PR_PACKAGE_1_SENTINEL: str = (
    "POSTURE_CONTRACT_CANONICALIZATION::PR_PACKAGE_1_MAIN_REPO_DELIVERED: "
    "This module is the PR package 1 delivery for the post-533 dual-repo "
    "runtime unification master plan (MAIN repo side).  It establishes the "
    "canonical posture contract enforcement layer so subsequent PR packages "
    "can depend on one stable source of truth."
)

# ---------------------------------------------------------------------------
# Internal: adjacent-field registry
# ---------------------------------------------------------------------------

#: Adjacent fields that encode orthogonal concepts.  Their values must NOT
#: duplicate the canonical posture values (control_only / join_runtime) as a
#: form of overloading.
_ADJACENT_FIELDS_NEVER_POSTURE: Dict[str, str] = {
    "entry_mode": POSTURE_BOUNDARY_NO_ENTRY_MODE_CONFLATION_POLICY,
    "cross_device_enabled": POSTURE_BOUNDARY_NO_CROSS_DEVICE_FLAG_CONFLATION_POLICY,
    "formation_role": POSTURE_BOUNDARY_NO_FORMATION_ROLE_CONFLATION_POLICY,
    "coordination_role": POSTURE_BOUNDARY_NO_FORMATION_ROLE_CONFLATION_POLICY,
    "runtime_domain_intent": POSTURE_BOUNDARY_NO_ENTRY_MODE_CONFLATION_POLICY,
}

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class PostureBoundaryViolation(ValueError):
    """Raised when a payload violates the posture-field boundary contract.

    This exception signals that a field adjacent to ``source_runtime_posture``
    (e.g. ``entry_mode``, ``cross_device_enabled``) has been set to a value
    that encodes participation posture semantics — which is explicitly
    forbidden by the posture contract boundary policies.

    Attributes
    ----------
    violations:
        A list of human-readable violation descriptions.
    """

    def __init__(self, violations: List[str]) -> None:
        self.violations = violations
        super().__init__(
            f"Posture boundary violation(s) detected: {'; '.join(violations)}"
        )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def canonicalize_posture_in_payload(
    payload: Dict[str, Any],
    *,
    key: str = "source_runtime_posture",
) -> Dict[str, Any]:
    """Return a *copy* of *payload* with the posture field normalised.

    The original dict is never mutated.  The returned dict is a shallow copy
    with the posture field replaced by its canonical lower-case value.

    If *payload* does not contain *key*, the returned copy contains
    ``key="control_only"`` (the safe default).

    Parameters
    ----------
    payload:
        Arbitrary dict that may contain a ``source_runtime_posture`` key.
    key:
        Field name to normalise.  Defaults to ``"source_runtime_posture"``.

    Returns
    -------
    dict
        Shallow copy of *payload* with the posture field set to a canonical
        value.  Never raises.
    """
    from contracts.source_posture_contract import normalize_posture_for_ingress

    out = dict(payload)
    raw = out.get(key)
    out[key] = normalize_posture_for_ingress(raw)
    return out


def validate_posture_field_consistency(
    payload: Dict[str, Any],
    *,
    posture_key: str = "source_runtime_posture",
) -> Tuple[bool, List[str]]:
    """Check that adjacent fields in *payload* are not conflated with posture.

    This validates the *boundary contract*: fields such as ``entry_mode`` and
    ``cross_device_enabled`` must not be set to canonical posture values
    (``"control_only"`` / ``"join_runtime"``), which would constitute an
    overloading violation.

    Parameters
    ----------
    payload:
        The model dict or API payload to check.  Inspected but never mutated.
    posture_key:
        The key for the posture field.  Defaults to ``"source_runtime_posture"``.

    Returns
    -------
    (True, [])
        When no conflation violations are found.
    (False, [violation_message, ...])
        When one or more adjacent fields carry posture-like values.
    """
    from contracts.source_posture_contract import SOURCE_POSTURE_VALID_VALUES

    violations: List[str] = []
    for field, policy in _ADJACENT_FIELDS_NEVER_POSTURE.items():
        if field == posture_key:
            continue
        raw_value = payload.get(field)
        if raw_value is None:
            continue
        normalised = str(raw_value).strip().lower()
        if normalised in SOURCE_POSTURE_VALID_VALUES:
            violations.append(
                f"Field '{field}' carries posture-like value '{raw_value}'. "
                f"This violates the boundary policy: {policy}"
            )
    ok = len(violations) == 0
    return ok, violations


def assert_posture_boundary_compliance(
    payload: Dict[str, Any],
    *,
    posture_key: str = "source_runtime_posture",
) -> None:
    """Assert that *payload* contains no posture-boundary violations.

    Raises :exc:`PostureBoundaryViolation` if any adjacent field is found to
    carry a posture-like value.  This is the strict enforcement path —
    use :func:`validate_posture_field_consistency` when you prefer to handle
    violations without raising.

    Parameters
    ----------
    payload:
        The model dict or API payload to check.
    posture_key:
        The key for the posture field.  Defaults to ``"source_runtime_posture"``.

    Raises
    ------
    PostureBoundaryViolation
        When one or more adjacent fields carry posture-like values.
    """
    ok, violations = validate_posture_field_consistency(payload, posture_key=posture_key)
    if not ok:
        raise PostureBoundaryViolation(violations)


def get_posture_from_payload(
    payload: Dict[str, Any],
    *,
    key: str = "source_runtime_posture",
    default: str = "control_only",
) -> str:
    """Extract and normalise the posture value from an arbitrary dict.

    This is the recommended extraction path for any code that needs to read
    ``source_runtime_posture`` from a raw dict (e.g. deserialized JSON,
    task payloads, registration dicts).  It always returns a canonical value
    and never raises.

    Parameters
    ----------
    payload:
        The source dict.
    key:
        Field name to read.  Defaults to ``"source_runtime_posture"``.
    default:
        Fallback value when the field is absent or unrecognised.  Must be a
        canonical posture value string.  Defaults to ``"control_only"``.

    Returns
    -------
    str
        One of ``"control_only"`` or ``"join_runtime"``.
    """
    from contracts.source_posture_contract import normalize_posture_for_ingress

    raw = payload.get(key, default)
    return normalize_posture_for_ingress(raw)
