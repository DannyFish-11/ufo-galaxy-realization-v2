"""contracts/source_posture_contract.py
========================================
Source Runtime Posture Contract — PR-533 / PR-1 dual-repo unification.

This module defines the **canonical contract schema for source-device runtime
participation posture** as introduced by PR #533
(``Add explicit source runtime posture semantics for multi-device control``).

It is the MAIN-repo half of PR-1 in the post-533 dual-repo runtime-host
unification track.  Its purpose is to:

1. Establish a stable, serialisable contract surface for
   ``source_runtime_posture`` that lives alongside the other execution
   lifecycle contracts in the ``contracts/`` package.
2. Remove ambiguity between posture semantics and unrelated knobs such as
   ``entry_mode`` or ``cross_device_enabled``.
3. Give the Android repo a clear, dependency-free contract module to adopt
   in a subsequent PR without pulling in ``core/`` internals.

The authoritative runtime state is managed by ``core/source_runtime_posture``
(introduced in PR #533).  This module is the **contract layer** — it is
concerned with stable field names, validation rules, serialisation, and
Android adoption readiness.

Two posture values are defined:

control_only
    The originating device is a *control plane* participant only.  It sends
    the task, monitors progress, and receives the result, but it does not
    contribute local execution resources to the runtime pool for this task.

join_runtime
    The originating device *joins the runtime* as an active execution
    participant.  It may receive subtasks, contribute results, or act as a
    co-executor in parallel with the target device.

Policy sentinels
----------------
The module exports three sentinel strings whose presence in an import can be
statically verified in CI to enforce contract invariants:

SOURCE_POSTURE_CONTRACT_AUTHORITY
    Declares this module as the canonical contract authority for
    source-device participation posture.

SOURCE_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY
    Asserts that ``entry_mode`` (execution-path selection) must never be
    overloaded to encode participation posture.

SOURCE_POSTURE_NO_CROSS_DEVICE_ENABLED_OVERLOAD_POLICY
    Asserts that ``cross_device_enabled`` (global feature gate) must never
    be overloaded to encode participation posture.

SOURCE_POSTURE_CONTRACT_PR1_UNIFICATION_SENTINEL
    Confirms that this file is the main-repo deliverable for PR-1 of the
    post-533 dual-repo runtime-host unification track.

Usage::

    from contracts.source_posture_contract import (
        SourcePostureValue,
        SourcePostureContractField,
        validate_source_posture_value,
        resolve_source_posture_value,
        build_source_posture_field,
        SOURCE_POSTURE_CONTRACT_AUTHORITY,
        SOURCE_POSTURE_CONTRACT_PR1_UNIFICATION_SENTINEL,
    )

    # Resolve from an arbitrary string hint (e.g. from an ingress payload)
    posture = resolve_source_posture_value("join_runtime")
    assert posture == SourcePostureValue.JOIN_RUNTIME

    # Embed in a typed contract field
    field = build_source_posture_field(posture_hint="control_only")
    assert field.source_runtime_posture == "control_only"

    # Validate raw string
    ok, err = validate_source_posture_value("join_runtime")
    assert ok
    ok, err = validate_source_posture_value("bad_value")
    assert not ok
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, Field, field_validator

__all__ = [
    # Enum
    "SourcePostureValue",
    # Contract field model
    "SourcePostureContractField",
    # Helpers
    "validate_source_posture_value",
    "resolve_source_posture_value",
    "build_source_posture_field",
    "posture_value_to_str",
    "normalize_posture_for_ingress",
    # Sentinels / policy markers
    "SOURCE_POSTURE_CONTRACT_AUTHORITY",
    "SOURCE_POSTURE_CONTRACT_LAYER_POSITION",
    "SOURCE_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY",
    "SOURCE_POSTURE_NO_CROSS_DEVICE_ENABLED_OVERLOAD_POLICY",
    "SOURCE_POSTURE_CONTRACT_PR1_UNIFICATION_SENTINEL",
    "SOURCE_POSTURE_CONTRACT_PR_PACKAGE_1_CANONICALIZATION_SENTINEL",
    "SOURCE_POSTURE_VALID_VALUES",
    "CANONICAL_POSTURE_ADJACENT_FIELDS",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

SOURCE_POSTURE_CONTRACT_AUTHORITY: str = (
    "SOURCE_POSTURE_CONTRACT::AUTHORITY_V1: "
    "Canonical contract-layer authority for source-device runtime participation "
    "posture.  Separates control-only vs join-runtime semantics from execution-path "
    "routing (entry_mode) and the global cross-device feature gate "
    "(cross_device_enabled).  Main-repo half of PR-1 in the post-533 "
    "dual-repo runtime-host unification track."
)

SOURCE_POSTURE_CONTRACT_LAYER_POSITION: int = 9

SOURCE_POSTURE_NO_ENTRYMODE_OVERLOAD_POLICY: str = (
    "SOURCE_POSTURE_CONTRACT::NO_ENTRYMODE_OVERLOAD_POLICY_V1: "
    "entry_mode remains execution-path selection only (local / cross_device / "
    "hybrid) and must never encode source-device participation posture."
)

SOURCE_POSTURE_NO_CROSS_DEVICE_ENABLED_OVERLOAD_POLICY: str = (
    "SOURCE_POSTURE_CONTRACT::NO_CROSS_DEVICE_ENABLED_OVERLOAD_POLICY_V1: "
    "cross_device_enabled is a global feature gate only and must never encode "
    "control-only vs join-runtime source-device posture."
)

SOURCE_POSTURE_CONTRACT_PR1_UNIFICATION_SENTINEL: str = (
    "SOURCE_POSTURE_CONTRACT::PR1_DUAL_REPO_UNIFICATION_MAIN_REPO_DELIVERED: "
    "This file is the main-repo deliverable for PR-1 of the post-533 dual-repo "
    "runtime-host unification track.  Android-repo adoption in PR-1b must "
    "reference the field names and validation rules defined here."
)

SOURCE_POSTURE_CONTRACT_PR_PACKAGE_1_CANONICALIZATION_SENTINEL: str = (
    "SOURCE_POSTURE_CONTRACT::PR_PACKAGE_1_POSTURE_CONTRACT_CANONICALIZATION: "
    "PR package 1 (MAIN repo side) of the post-533 dual-repo runtime unification "
    "master plan.  This module is the stable contract-layer source of truth for "
    "source_runtime_posture.  All ingress validation, model defaults, and "
    "boundary enforcement MUST use this module, not core/source_runtime_posture.py."
)

#: Fields that are semantically adjacent to ``source_runtime_posture`` but must
#: NEVER be overloaded to encode participation posture.
CANONICAL_POSTURE_ADJACENT_FIELDS: frozenset = frozenset(
    {
        "entry_mode",            # execution-path selection (local/cross_device/hybrid)
        "cross_device_enabled",  # global feature gate — on/off only
        "formation_role",        # multi-device formation assignment
        "coordination_role",     # multi-device coordination role (PR-6)
        "runtime_domain_intent", # high-level domain (cross_device/local)
    }
)


# ---------------------------------------------------------------------------
# Canonical posture enum
# ---------------------------------------------------------------------------


class SourcePostureValue(str, Enum):
    """Canonical source-device runtime participation posture values.

    CONTROL_ONLY
        The originating device participates as a control plane only — it
        dispatches, monitors, and receives results but contributes no local
        execution resources for the current task.

    JOIN_RUNTIME
        The originating device actively joins the runtime as an execution
        participant — it may receive subtasks, produce results, or co-execute
        with the target device.
    """

    CONTROL_ONLY = "control_only"
    JOIN_RUNTIME = "join_runtime"


#: Frozenset of accepted raw string values for ingress validation.
SOURCE_POSTURE_VALID_VALUES: frozenset = frozenset(v.value for v in SourcePostureValue)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_posture_hint(raw: object) -> str:
    """Normalise *raw* to a canonical posture string.

    Returns ``"control_only"`` for any input that is ``None``, empty, or does
    not match one of the two canonical values.  This helper is intentionally
    private; callers that need the full :class:`SourcePostureValue` should use
    :func:`resolve_source_posture_value`.
    """
    if raw is None:
        return SourcePostureValue.CONTROL_ONLY.value
    normalised = str(raw).strip().lower()
    return normalised if normalised in SOURCE_POSTURE_VALID_VALUES else SourcePostureValue.CONTROL_ONLY.value


def posture_value_to_str(posture: SourcePostureValue) -> str:
    """Return the canonical wire-format string for a :class:`SourcePostureValue`.

    This is provided so callers don't need to reach into ``.value`` directly,
    keeping contract consumers decoupled from the Enum internals.
    """
    return posture.value


def normalize_posture_for_ingress(raw: object) -> str:
    """Normalise a raw ingress value to a canonical posture string.

    This is the **public, contract-layer API** for normalising
    ``source_runtime_posture`` values arriving from API payloads, task dicts,
    or any other external source.  It is the recommended replacement for any
    direct import of ``core.source_runtime_posture`` for validation purposes.

    Returns ``"control_only"`` for any input that is ``None``, empty, or does
    not match one of the two canonical values — always choosing the safe,
    conservative default.

    Parameters
    ----------
    raw:
        The raw value from an ingress source.  May be ``None``, a non-string,
        or any arbitrary string.

    Returns
    -------
    str
        One of ``"control_only"`` or ``"join_runtime"``.  Never ``None``.
        Never raises.
    """
    return _normalise_posture_hint(raw)


def validate_source_posture_value(raw: Optional[str]) -> Tuple[bool, Optional[str]]:
    """Validate a raw posture string against the canonical allowed values.

    Parameters
    ----------
    raw:
        The raw string to validate (typically from an API payload or task dict).

    Returns
    -------
    (True, None)
        When *raw* is a valid posture value.
    (False, error_message)
        When *raw* is not a valid posture value.
    """
    if raw is None:
        return False, "source_runtime_posture is None; expected one of: " + ", ".join(
            sorted(SOURCE_POSTURE_VALID_VALUES)
        )
    normalised = str(raw).strip().lower()
    if normalised in SOURCE_POSTURE_VALID_VALUES:
        return True, None
    return False, (
        f"source_runtime_posture '{raw}' is not a valid posture value. "
        f"Expected one of: {', '.join(sorted(SOURCE_POSTURE_VALID_VALUES))}."
    )


def resolve_source_posture_value(
    posture_hint: Optional[str] = None,
    *,
    default: SourcePostureValue = SourcePostureValue.CONTROL_ONLY,
) -> SourcePostureValue:
    """Resolve a raw string hint to a :class:`SourcePostureValue`.

    Unknown or absent hints resolve to *default* (``CONTROL_ONLY``).
    This mirrors the behaviour of ``core.source_runtime_posture.resolve_source_runtime_posture``
    but operates at the contract layer without importing ``core``.

    Parameters
    ----------
    posture_hint:
        Raw string from an API payload, task dict, or session context.
    default:
        Fallback value when *posture_hint* is absent or unrecognised.
    """
    if posture_hint is None:
        return default
    normalised = str(posture_hint).strip().lower()
    if normalised == SourcePostureValue.JOIN_RUNTIME.value:
        return SourcePostureValue.JOIN_RUNTIME
    if normalised == SourcePostureValue.CONTROL_ONLY.value:
        return SourcePostureValue.CONTROL_ONLY
    return default


# ---------------------------------------------------------------------------
# Contract field model — embeddable in other contracts
# ---------------------------------------------------------------------------


class SourcePostureContractField(BaseModel):
    """Canonical, validated container for a ``source_runtime_posture`` field.

    This model is designed to be **embedded** in larger contract models
    (e.g. :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`,
    :class:`~contracts.source_dispatch.SourceDispatchDecision`) or used
    as a stand-alone validated field carrier when passing posture values
    across module boundaries.

    Field
    -----
    source_runtime_posture
        The canonical participation posture of the originating device for
        the current task.  Must be one of ``"control_only"`` or
        ``"join_runtime"``.  Defaults to ``"control_only"`` (the safe
        conservative posture).

    The field name ``source_runtime_posture`` is intentionally identical to
    the name used in the core runtime (``core/source_runtime_posture.py``),
    the chat-ingress model (``galaxy_gateway/routes/chat.py``), and the
    device formation group (``core/device_formation/formation_group.py``)
    so that downstream consumers — including the Android repo — can adopt a
    single stable field name.
    """

    source_runtime_posture: str = Field(
        default=SourcePostureValue.CONTROL_ONLY.value,
        description=(
            "Source-device runtime participation posture for the current task. "
            "Must be 'control_only' or 'join_runtime'. "
            "Defaults to 'control_only' (conservative). "
            "See SOURCE_POSTURE_CONTRACT_AUTHORITY for policy."
        ),
    )

    @field_validator("source_runtime_posture", mode="before")
    @classmethod
    def _validate_posture(cls, value: Any) -> str:
        """Normalise and validate the posture value.

        Accepts the raw string and normalises it to lower-case before
        comparing against the canonical value set.  Unknown values raise a
        ``ValueError`` with a descriptive message.
        """
        normalised = str(value or "").strip().lower()
        if normalised not in SOURCE_POSTURE_VALID_VALUES:
            raise ValueError(
                f"source_runtime_posture must be one of: "
                f"{', '.join(sorted(SOURCE_POSTURE_VALID_VALUES))}. "
                f"Got: '{value}'."
            )
        return normalised

    @property
    def posture_enum(self) -> SourcePostureValue:
        """Return the posture as a :class:`SourcePostureValue` enum member."""
        return SourcePostureValue(self.source_runtime_posture)

    @property
    def is_control_only(self) -> bool:
        """``True`` when the posture is ``control_only``."""
        return self.source_runtime_posture == SourcePostureValue.CONTROL_ONLY.value

    @property
    def is_join_runtime(self) -> bool:
        """``True`` when the posture is ``join_runtime``."""
        return self.source_runtime_posture == SourcePostureValue.JOIN_RUNTIME.value

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable JSON-serialisable dict for this field."""
        return {
            "source_runtime_posture": self.source_runtime_posture,
            "is_control_only": self.is_control_only,
            "is_join_runtime": self.is_join_runtime,
            "contract_authority": SOURCE_POSTURE_CONTRACT_AUTHORITY,
        }

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_source_posture_field(
    posture_hint: Optional[str] = None,
    *,
    default: str = SourcePostureValue.CONTROL_ONLY.value,
) -> SourcePostureContractField:
    """Build a :class:`SourcePostureContractField` from an optional raw hint.

    This is the canonical builder for contract-layer posture fields.  It
    tolerates ``None`` and unknown strings, falling back to *default*.

    Parameters
    ----------
    posture_hint:
        Raw string from an API payload, task dict, or session context.
        ``None`` is treated as absent and resolved to *default*.
    default:
        Fallback posture value string when *posture_hint* is absent or
        unrecognised.  Defaults to ``"control_only"``.

    Returns
    -------
    SourcePostureContractField
        A validated field model.  Never raises.
    """
    resolved = resolve_source_posture_value(posture_hint)
    try:
        return SourcePostureContractField(source_runtime_posture=resolved.value)
    except (ValueError, TypeError):
        # resolve_source_posture_value already guarantees a canonical value, so
        # this branch should never be reached in practice.  Fall back to the
        # explicit default rather than propagating.
        return SourcePostureContractField(source_runtime_posture=default)
