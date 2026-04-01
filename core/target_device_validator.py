"""
core/target_device_validator.py
================================
Canonical target-device validation layer for cross-device execution readiness.

Turns ``target_device`` from a raw string hint into a validated device target
checked against canonical readiness and capability requirements.  All source
lookups degrade gracefully so this module never raises.

Public API
----------
Models:
    TargetDeviceValidationResult
    CanonicalValidationInput

Helpers:
    validate_target_device(
        device_id, *, required_capabilities=None,
        require_orchestration_eligible=False
    ) -> TargetDeviceValidationResult

    validate_target_device_from_canonical(
        canonical_input
    ) -> TargetDeviceValidationResult

Authority sentinels:
    TARGET_DEVICE_VALIDATOR_AUTHORITY
    VALIDATOR_CANONICAL_INPUTS_ONLY
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.TargetDeviceValidator")

__all__ = [
    "TargetDeviceValidationResult",
    "CanonicalValidationInput",
    "validate_target_device",
    "validate_target_device_from_canonical",
    "TARGET_DEVICE_VALIDATOR_AUTHORITY",
    "TARGET_DEVICE_VALIDATOR_CHAIN_POSITION",
    "VALIDATOR_TRUTH_SOURCE",
    "VALIDATOR_CANONICAL_INPUTS_ONLY",
]

TARGET_DEVICE_VALIDATOR_AUTHORITY: str = "TARGET_DEVICE_VALIDATOR_V2"

# Chain position annotation — this module operates at Layer 3 of the
# canonical admissibility chain (core.admissibility_chain).
TARGET_DEVICE_VALIDATOR_CHAIN_POSITION: int = 3

# PR-1: Affirms that this validator reads device truth from
# core.device_readiness (Layer 1) and core.device_participation (Layer 2),
# both of which are TIL-aligned (TRUTH_INTEGRATION_LAYER_BACKED=True).
# The compat cache is NOT consulted by any layer in this chain.
VALIDATOR_TRUTH_SOURCE: str = (
    "READINESS(UCM+UDM) + PARTICIPATION via TRUTH_INTEGRATION_LAYER_BACKED=True; "
    "compat-cache excluded"
)

# PR-5: Affirms that this validator only consumes canonical resolved truth
# (Layer-1 readiness + Layer-2 participation) and policy output.
# Legacy or compat inputs must be normalised through CanonicalValidationInput
# (the adapter/interop path) before being passed to this validator.
VALIDATOR_CANONICAL_INPUTS_ONLY: bool = True


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class TargetDeviceValidationResult:
    """Serialisable result of a single target-device validation pass.

    Fields
    ------
    device_id
        The device identifier that was validated.
    valid
        Overall verdict — ``True`` only when *all* requested checks pass.
    registered
        The device is known to the canonical registry.
    ready
        The device satisfies cross-device readiness (registered, online,
        connected, routable).
    capability_match
        All ``required_capabilities`` are satisfied.  ``True`` by default
        when no capabilities were requested.
    orchestration_eligible
        The device is eligible for multi-device orchestration.  ``True`` by
        default when ``require_orchestration_eligible`` is ``False``.
    reasons
        Human-readable strings describing why a check failed or degraded.
    sources
        Structured data from each subsystem consulted during validation.
    """

    device_id: str
    valid: bool = False
    registered: bool = False
    ready: bool = False
    capability_match: bool = False
    orchestration_eligible: bool = False
    reasons: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "valid": self.valid,
            "registered": self.registered,
            "ready": self.ready,
            "capability_match": self.capability_match,
            "orchestration_eligible": self.orchestration_eligible,
            "reasons": list(self.reasons),
            "sources": dict(self.sources),
        }


# ---------------------------------------------------------------------------
# PR-5: Canonical validation input adapter / interop
# ---------------------------------------------------------------------------


@dataclass
class CanonicalValidationInput:
    """Interop adapter for normalising legacy or non-canonical validation inputs.

    PR-5 governance: the validator must only consume canonical resolved truth.
    Any caller passing raw/legacy data must first normalise it through this
    adapter.  The adapter records the original source so that observability
    tools can distinguish canonical from adapted inputs.

    Fields
    ------
    device_id
        The canonical device identifier.
    required_capabilities
        Optional list of capability strings.
    require_orchestration_eligible
        When True the orchestration-eligibility check is applied.
    source_label
        Identifies where the input originated (e.g. ``"canonical"``,
        ``"legacy_compat"``, ``"api_request"``).  Used for observability.
    """

    device_id: str
    required_capabilities: Optional[List[str]] = None
    require_orchestration_eligible: bool = False
    source_label: str = "canonical"

    @classmethod
    def from_legacy(
        cls,
        device_id: str,
        *,
        capabilities: Optional[List[str]] = None,
        orchestration_eligible: bool = False,
        legacy_source: str = "legacy_compat",
    ) -> "CanonicalValidationInput":
        """Build a CanonicalValidationInput from legacy/compat caller data.

        This is the interop path required by PR-5: all non-canonical inputs
        must pass through this factory before being consumed by the validator.
        """
        return cls(
            device_id=device_id,
            required_capabilities=capabilities,
            require_orchestration_eligible=orchestration_eligible,
            source_label=legacy_source,
        )


# ---------------------------------------------------------------------------
# Defensive subsystem accessors
# ---------------------------------------------------------------------------


def _check_readiness(device_id: str) -> tuple[bool, bool, Dict[str, Any], List[str]]:
    """Return (registered, ready, sources_dict, reasons_list) via device_readiness.

    Degrades to (False, False, {}, [reason]) if the module is unavailable.
    """
    try:
        from core.device_readiness import get_device_readiness  # type: ignore
        rs = get_device_readiness(device_id)
        registered = bool(getattr(rs, "registered", False))
        ready = bool(
            registered
            and getattr(rs, "online", False)
            and getattr(rs, "connected", False)
            and getattr(rs, "routable", False)
        )
        src: Dict[str, Any] = {}
        if hasattr(rs, "to_dict"):
            src["readiness"] = rs.to_dict()
        else:
            src["readiness"] = {"registered": registered, "ready": ready}
        return registered, ready, src, []
    except ImportError:
        return False, False, {}, ["readiness-module-unavailable"]
    except Exception as exc:
        logger.warning(
            "TargetDeviceValidator: readiness check failed for %s — %s",
            device_id,
            exc,
            extra={"event": "target_validation_readiness_error", "device_id": device_id},
        )
        return False, False, {}, [f"readiness-error:{exc}"]


def _check_capabilities(
    device_id: str,
    required_capabilities: List[str],
) -> tuple[bool, Dict[str, Any], List[str]]:
    """Return (capability_match, sources_dict, reasons_list).

    Attempts to validate *required_capabilities* against the canonical UDM
    device record.  Degrades gracefully when UDM is unavailable.
    """
    if not required_capabilities:
        return True, {}, []

    # Try UDM as the canonical capability source.
    try:
        from core.unified.device_manager import get_unified_device_manager  # type: ignore
        udm = get_unified_device_manager()
        if udm is None:
            return True, {}, ["capability-check-skipped:udm-returned-none"]

        device = None
        get_fn = getattr(udm, "get_device", None)
        if callable(get_fn):
            device = get_fn(device_id)

        if device is None:
            # Device not found — already handled by registered flag; skip cap check.
            return False, {}, ["capability-check-skipped:device-not-found"]

        device_caps = set(getattr(device, "capabilities", None) or [])
        required_set = set(required_capabilities)
        missing = required_set - device_caps
        if missing:
            return (
                False,
                {"device_capabilities": list(device_caps), "required": list(required_set)},
                [f"capability-mismatch:missing={','.join(sorted(missing))}"],
            )
        return (
            True,
            {"device_capabilities": list(device_caps), "required": list(required_set)},
            [],
        )
    except ImportError:
        # Capability subsystem unavailable — degrade gracefully.
        logger.debug(
            "TargetDeviceValidator: UDM unavailable for capability check on %s", device_id
        )
        return (
            True,
            {},
            ["capability-check-degraded:udm-import-error"],
        )
    except Exception as exc:
        logger.warning(
            "TargetDeviceValidator: capability check failed for %s — %s",
            device_id,
            exc,
            extra={
                "event": "target_validation_capability_error",
                "device_id": device_id,
            },
        )
        return (
            True,
            {},
            [f"capability-check-degraded:{exc}"],
        )


def _check_orchestration(device_id: str) -> tuple[bool, Dict[str, Any], List[str]]:
    """Return (orchestration_eligible, sources_dict, reasons_list).

    Uses device_participation if available; degrades gracefully otherwise.
    """
    try:
        from core.device_participation import get_device_participation  # type: ignore
        ps = get_device_participation(device_id)
        eligible = bool(getattr(ps, "orchestration_eligible", False))
        src: Dict[str, Any] = {}
        if hasattr(ps, "to_dict"):
            src["participation"] = ps.to_dict()
        else:
            src["participation"] = {"orchestration_eligible": eligible}
        reasons: List[str] = []
        if not eligible:
            reasons.append("not-eligible")
        return eligible, src, reasons
    except ImportError:
        return False, {}, ["participation-unavailable:import-error"]
    except Exception as exc:
        logger.warning(
            "TargetDeviceValidator: orchestration check failed for %s — %s",
            device_id,
            exc,
            extra={
                "event": "target_validation_orchestration_error",
                "device_id": device_id,
            },
        )
        return False, {}, [f"orchestration-check-error:{exc}"]


# ---------------------------------------------------------------------------
# Public validator
# ---------------------------------------------------------------------------


def validate_target_device(
    device_id: str,
    *,
    required_capabilities: Optional[List[str]] = None,
    require_orchestration_eligible: bool = False,
) -> TargetDeviceValidationResult:
    """Validate *device_id* as a cross-device execution target.

    Parameters
    ----------
    device_id:
        The device identifier to validate.
    required_capabilities:
        Optional list of capability strings the device must possess.
        When ``None`` or empty the capability check is skipped (passes).
    require_orchestration_eligible:
        When ``True`` the device must also be assessed as orchestration-
        eligible via :func:`core.device_participation.get_device_participation`.

    Returns
    -------
    TargetDeviceValidationResult
        Always returns a result; never raises.  ``valid=True`` only when
        every requested check passes.
    """
    result = TargetDeviceValidationResult(device_id=device_id)

    # ── Guard: empty device_id ──────────────────────────────────────────
    if not device_id or not device_id.strip():
        result.valid = False
        result.reasons.append("empty-device-id")
        logger.warning(
            "TargetDeviceValidator: validation called with empty device_id",
            extra={"event": "target_validation_failed", "reason": "empty-device-id"},
        )
        return result

    # ── 1. Readiness check ──────────────────────────────────────────────
    try:
        registered, ready, readiness_src, readiness_reasons = _check_readiness(device_id)
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "TargetDeviceValidator: unexpected readiness error for %s — %s",
            device_id,
            exc,
        )
        registered, ready, readiness_src, readiness_reasons = False, False, {}, [f"readiness-unexpected-error:{exc}"]
    result.registered = registered
    result.ready = ready
    result.sources.update(readiness_src)
    result.reasons.extend(readiness_reasons)

    if not registered:
        result.reasons.append("not-registered")
    if registered and not ready:
        result.reasons.append("not-ready")

    # ── 2. Capability check ─────────────────────────────────────────────
    cap_match, cap_src, cap_reasons = _check_capabilities(
        device_id, required_capabilities or []
    )
    result.capability_match = cap_match
    result.sources.update(cap_src)
    result.reasons.extend(cap_reasons)

    # ── 3. Orchestration eligibility check (optional) ───────────────────
    if require_orchestration_eligible:
        orch_eligible, orch_src, orch_reasons = _check_orchestration(device_id)
        result.orchestration_eligible = orch_eligible
        result.sources.update(orch_src)
        result.reasons.extend(orch_reasons)
    else:
        # Not required — mark as eligible by default.
        result.orchestration_eligible = True

    # ── Derive overall verdict ──────────────────────────────────────────
    result.valid = (
        result.registered
        and result.ready
        and result.capability_match
        and result.orchestration_eligible
    )

    if not result.valid:
        logger.warning(
            "TargetDeviceValidator: device=%s valid=False registered=%s ready=%s "
            "capability_match=%s orchestration_eligible=%s reasons=%s",
            device_id,
            result.registered,
            result.ready,
            result.capability_match,
            result.orchestration_eligible,
            result.reasons,
            extra={
                "event": "target_validation_failed",
                "device_id": device_id,
                "registered": result.registered,
                "ready": result.ready,
                "capability_match": result.capability_match,
                "orchestration_eligible": result.orchestration_eligible,
            },
        )
    else:
        logger.debug(
            "TargetDeviceValidator: device=%s valid=True",
            device_id,
            extra={"event": "target_validation_passed", "device_id": device_id},
        )

    return result


# ---------------------------------------------------------------------------
# PR-5: validate_target_device_from_canonical
# ---------------------------------------------------------------------------


def validate_target_device_from_canonical(
    canonical_input: "CanonicalValidationInput",
) -> TargetDeviceValidationResult:
    """Validate a target device from a pre-normalised :class:`CanonicalValidationInput`.

    This is the PR-5 governance entry-point for callers that have already
    normalised their inputs through the canonical interop adapter.  It
    delegates to :func:`validate_target_device` and annotates the result
    sources with the input's ``source_label`` for observability.

    Parameters
    ----------
    canonical_input:
        A :class:`CanonicalValidationInput` produced either by direct
        construction (canonical callers) or via
        :meth:`CanonicalValidationInput.from_legacy` (compat callers).

    Returns
    -------
    TargetDeviceValidationResult
        Always returns a result; never raises.
    """
    result = validate_target_device(
        canonical_input.device_id,
        required_capabilities=canonical_input.required_capabilities,
        require_orchestration_eligible=canonical_input.require_orchestration_eligible,
    )
    # Annotate sources so observability can trace the interop path.
    result.sources["canonical_input_source"] = canonical_input.source_label
    return result
