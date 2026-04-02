"""
core/admissibility_policy_convergence.py
=========================================
PR-5: Admissibility & Policy Convergence layer.

Unifies the three-layer admissibility chain (readiness / participation /
target-validation) with a standardised policy-output contract so that
selection and routing code always consumes the same canonically-shaped
output regardless of which layer produced it.

Governance boundaries
---------------------
* **Layer 1 — Readiness** (``core.device_readiness``)
  Canonical authority for ``registered``, ``online``, ``connected``,
  ``routable``, and the PR-5 live-route-truth fields
  (``transport_present``, ``transport_usable``, ``device_routable``,
  ``effective_path``).

* **Layer 2 — Participation** (``core.device_participation``)
  Enrich-only layer.  Provides role/session/mesh context.
  Must NOT override Layer-1 canonical truth.
  Governed by ``PARTICIPATION_ENRICH_ONLY = True``.

* **Layer 3 — Target Validation** (``core.target_device_validator``)
  Consumes canonical resolved truth from Layers 1 + 2 and policy output.
  Legacy inputs must be normalised via ``CanonicalValidationInput``
  before reaching this layer.
  Governed by ``VALIDATOR_CANONICAL_INPUTS_ONLY = True``.

Policy/selection output contract (PR-5)
----------------------------------------
All evaluation functions return a :class:`PolicyConvergenceOutput` with the
following standardised fields:

``eligibility``
    Boolean — overall policy verdict: is the device eligible for selection?

``capability_fit``
    Boolean — does the device satisfy all required capabilities?

``policy_score``
    Float [0.0, 1.0] — normalised policy score used for ranking/selection.
    Higher is better.  0.0 means not eligible or not scoreable.

``route_preference``
    String — canonical name of the preferred delivery path
    (``"direct_ws"``, ``"ucm"``, ``"relay"``, ``"none"``).

Public API
----------
Models:
    PolicyConvergenceOutput

Helpers:
    evaluate_policy_convergence(
        device_id, *, required_capabilities=None,
        require_orchestration_eligible=False
    ) -> PolicyConvergenceOutput

Authority sentinels:
    ADMISSIBILITY_POLICY_CONVERGENCE_AUTHORITY
    POLICY_CONVERGENCE_LAYER_POSITION
    POLICY_OUTPUT_CONTRACT_VERSION
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.AdmissibilityPolicyConvergence")

__all__ = [
    "PolicyConvergenceOutput",
    "evaluate_policy_convergence",
    "ADMISSIBILITY_POLICY_CONVERGENCE_AUTHORITY",
    "POLICY_CONVERGENCE_LAYER_POSITION",
    "POLICY_OUTPUT_CONTRACT_VERSION",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Identifies this module as the canonical PR-5 policy convergence authority.
ADMISSIBILITY_POLICY_CONVERGENCE_AUTHORITY: str = "ADMISSIBILITY_POLICY_CONVERGENCE_V1"

#: This module sits above Layer 3 (target-validation) in the chain — it is
#: the convergence point that produces a unified policy output.
POLICY_CONVERGENCE_LAYER_POSITION: int = 4

#: Version string for the policy output contract so that downstream
#: consumers can detect schema changes.
POLICY_OUTPUT_CONTRACT_VERSION: str = "POLICY_CONTRACT_V1"


# ---------------------------------------------------------------------------
# Policy output model
# ---------------------------------------------------------------------------


@dataclass
class PolicyConvergenceOutput:
    """Standardised policy/selection output for a single device evaluation.

    Fields
    ------
    device_id
        The device that was evaluated.

    eligibility
        Overall policy verdict.  ``True`` only when the device is registered,
        ready, capability-matched, and (if required) orchestration-eligible.

    capability_fit
        Whether the device satisfies all requested capabilities.  ``True`` by
        default when no capabilities were requested.

    policy_score
        Normalised score in [0.0, 1.0] used for ranking / candidate selection.
        Derived from readiness quality, transport path, and eligibility flags.
        ``0.0`` when ``eligibility`` is ``False``.

    route_preference
        Canonical name of the preferred delivery path:
        ``"direct_ws"``, ``"ucm"``, ``"relay"``, or ``"none"``.

    transport_present
        Whether any transport mechanism is physically connected.

    transport_usable
        Whether the present transport can actively deliver messages.

    device_routable
        Whether there is a valid end-to-end canonical route to the device.

    effective_path
        The canonical path that will be used for delivery.

    reasons
        Human-readable failure/degradation reason strings propagated from all
        layers consulted.

    sources
        Structured layer-output data for observability / debugging.

    contract_version
        Always ``POLICY_OUTPUT_CONTRACT_VERSION`` — lets consumers detect schema changes.
    """

    device_id: str
    # --- Core policy verdict ---
    eligibility: bool = False
    capability_fit: bool = False
    policy_score: float = 0.0
    route_preference: str = "none"
    # --- Live route truth (from Layer-1 readiness) ---
    transport_present: bool = False
    transport_usable: bool = False
    device_routable: bool = False
    effective_path: str = "none"
    # --- PR-B standardised fields ---
    degradation_reason: Optional[str] = None
    """Human-readable reason why this device was degraded or fell back.
    ``None`` when no degradation occurred."""
    selected_target_reason: Optional[str] = None
    """Human-readable reason why this device was (or was not) selected as the
    preferred target.  Supports operator explanation and debugging."""
    failure_domain: Optional[str] = None
    """Canonical :class:`~core.failure_domains.FailureDomain` value string
    when ``eligibility`` is ``False`` or when a policy failure occurred.
    ``None`` when the device is fully eligible."""
    # --- Provenance ---
    reasons: List[str] = field(default_factory=list)
    sources: Dict[str, Any] = field(default_factory=dict)
    contract_version: str = POLICY_OUTPUT_CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "eligibility": self.eligibility,
            "capability_fit": self.capability_fit,
            "policy_score": self.policy_score,
            "route_preference": self.route_preference,
            "transport_present": self.transport_present,
            "transport_usable": self.transport_usable,
            "device_routable": self.device_routable,
            "effective_path": self.effective_path,
            "degradation_reason": self.degradation_reason,
            "selected_target_reason": self.selected_target_reason,
            "failure_domain": self.failure_domain,
            "reasons": list(self.reasons),
            "sources": dict(self.sources),
            "contract_version": self.contract_version,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_readiness(device_id: str) -> Optional[Any]:
    """Return a DeviceReadinessSummary, or None on failure."""
    try:
        from core.device_readiness import get_device_readiness  # type: ignore
        return get_device_readiness(device_id)
    except ImportError:
        logger.debug("PolicyConvergence: device_readiness unavailable")
        return None
    except Exception as exc:
        logger.warning(
            "PolicyConvergence: readiness error for %s — %s",
            device_id,
            exc,
            extra={"event": "policy_convergence_readiness_error", "device_id": device_id},
        )
        return None


def _get_participation(device_id: str) -> Optional[Any]:
    """Return a ParticipationSummary, or None on failure."""
    try:
        from core.device_participation import get_device_participation  # type: ignore
        return get_device_participation(device_id)
    except ImportError:
        logger.debug("PolicyConvergence: device_participation unavailable")
        return None
    except Exception as exc:
        logger.warning(
            "PolicyConvergence: participation error for %s — %s",
            device_id,
            exc,
            extra={"event": "policy_convergence_participation_error", "device_id": device_id},
        )
        return None


def _get_validation(
    device_id: str,
    required_capabilities: Optional[List[str]],
    require_orchestration_eligible: bool,
) -> Optional[Any]:
    """Return a TargetDeviceValidationResult, or None on failure."""
    try:
        from core.target_device_validator import validate_target_device  # type: ignore
        return validate_target_device(
            device_id,
            required_capabilities=required_capabilities,
            require_orchestration_eligible=require_orchestration_eligible,
        )
    except ImportError:
        logger.debug("PolicyConvergence: target_device_validator unavailable")
        return None
    except Exception as exc:
        logger.warning(
            "PolicyConvergence: validation error for %s — %s",
            device_id,
            exc,
            extra={"event": "policy_convergence_validation_error", "device_id": device_id},
        )
        return None


def _compute_policy_score(
    readiness: Any,
    transport_present: bool,
    transport_usable: bool,
    device_routable: bool,
    effective_path: str,
    eligibility: bool,
) -> float:
    """Compute a normalised [0.0, 1.0] policy score for a device.

    Scoring heuristic:
    - 0.0 if not eligible
    - Base 0.4 for eligibility (registered + ready)
    - +0.2 if transport_present
    - +0.2 if transport_usable
    - +0.1 if effective_path == "direct_ws" (best path)
    - +0.1 if online (readiness.online)
    """
    if not eligibility:
        return 0.0

    score = 0.4
    if transport_present:
        score += 0.2
    if transport_usable:
        score += 0.2
    if effective_path == "direct_ws":
        score += 0.1
    elif effective_path in ("ucm", "relay"):
        score += 0.05
    if readiness is not None and getattr(readiness, "online", False):
        score += 0.1

    return min(1.0, round(score, 3))


# ---------------------------------------------------------------------------
# PR-B: Failure domain classification helpers
# ---------------------------------------------------------------------------


def _classify_failure_domain(output: "PolicyConvergenceOutput") -> str:
    """Classify the primary failure domain for an ineligible device.

    Uses the reason strings and output flags to select the most appropriate
    PR-B canonical failure domain.  Returns the domain value string.
    """
    try:
        from core.failure_domains import FailureDomain
    except ImportError:
        return "unknown_failure"

    reasons_str = " ".join(output.reasons).lower()

    # Empty device ID
    if "empty-device-id" in reasons_str:
        return FailureDomain.VALIDATION_FAILURE.value

    # Readiness / registration unavailability
    if "readiness-unavailable" in reasons_str:
        return FailureDomain.ROUTING_FAILURE.value

    # Validation unavailability / validation failure
    if "validation-unavailable" in reasons_str or "not-registered" in reasons_str:
        return FailureDomain.ROUTING_FAILURE.value

    # Capability mismatch
    if not output.capability_fit and output.reasons:
        for r in output.reasons:
            if "capability" in r.lower() or "mismatch" in r.lower():
                return FailureDomain.SEMANTIC_FAILURE.value

    # Transport not present / not usable
    if not output.transport_present:
        return FailureDomain.TRANSPORT_FAILURE.value
    if not output.transport_usable:
        return FailureDomain.TRANSPORT_FAILURE.value

    # Device not routable
    if not output.device_routable:
        return FailureDomain.ROUTING_FAILURE.value

    # Policy / eligibility failure (catch-all for validation layer rejection)
    if output.reasons:
        return FailureDomain.POLICY_FAILURE.value

    return FailureDomain.UNKNOWN_FAILURE.value


def _build_degradation_reason(output: "PolicyConvergenceOutput") -> str:
    """Build a human-readable degradation reason string for an ineligible device.

    Returns a concise, operator-readable explanation of why the device is
    not eligible.
    """
    if not output.transport_present:
        return "transport not present"
    if not output.transport_usable:
        return "transport not usable"
    if not output.device_routable:
        return "device not routable"
    if not output.capability_fit:
        return "capability mismatch"
    if output.reasons:
        # Return the first non-generic reason
        for r in output.reasons:
            if r not in (
                "readiness-unavailable",
                "participation-unavailable",
                "validation-unavailable",
            ):
                return r
        return output.reasons[0]
    return "ineligible"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_policy_convergence(
    device_id: str,
    *,
    required_capabilities: Optional[List[str]] = None,
    require_orchestration_eligible: bool = False,
) -> PolicyConvergenceOutput:
    """Evaluate device admissibility and produce a unified policy output.

    This function is the PR-5 convergence point.  It:

    1. Queries Layer-1 canonical readiness for live-route-truth fields.
    2. Queries Layer-2 participation for enrichment (does NOT allow
       participation to override Layer-1 truth).
    3. Queries Layer-3 target-validation for the overall eligibility verdict
       and capability-fit assessment.
    4. Computes a policy score and assembles a :class:`PolicyConvergenceOutput`
       with standardised fields.

    All sub-layer calls degrade gracefully.  The function never raises.

    Parameters
    ----------
    device_id:
        The canonical device identifier.
    required_capabilities:
        Optional list of capability strings the device must possess.
    require_orchestration_eligible:
        When ``True`` orchestration-eligibility is required for eligibility.

    Returns
    -------
    PolicyConvergenceOutput
        Always returns a valid output record.
    """
    output = PolicyConvergenceOutput(device_id=device_id)

    # ── Guard ──────────────────────────────────────────────────────────
    if not device_id or not device_id.strip():
        output.reasons.append("empty-device-id")
        output.failure_domain = "validation_failure"
        output.degradation_reason = "empty device_id"
        output.selected_target_reason = "device not selected: empty device_id"
        return output

    # ── Layer 1: Canonical readiness ───────────────────────────────────
    readiness = _get_readiness(device_id)
    if readiness is not None:
        # Populate live route truth from readiness routability sub-summary
        routability = getattr(readiness, "routability", None)
        if routability is not None:
            output.transport_present = bool(
                getattr(routability, "transport_present", False)
            )
            output.transport_usable = bool(
                getattr(routability, "transport_usable", False)
            )
            output.device_routable = bool(
                getattr(routability, "device_routable", False)
                or getattr(routability, "effective_routable", False)
            )
            output.effective_path = str(
                getattr(routability, "effective_path", None)
                or getattr(routability, "preferred_path", "none")
            )
            output.route_preference = output.effective_path
        output.sources["readiness"] = (
            readiness.to_dict() if hasattr(readiness, "to_dict") else {}
        )
    else:
        output.reasons.append("readiness-unavailable")

    # ── Layer 2: Participation enrichment (enrich only, no override) ───
    participation = _get_participation(device_id)
    if participation is not None:
        # Participation may only contribute enrichment data to sources.
        # It must NOT override transport_present/transport_usable/device_routable
        # which came from Layer-1 canonical readiness.
        output.sources["participation"] = (
            participation.to_dict() if hasattr(participation, "to_dict") else {}
        )
    else:
        output.reasons.append("participation-unavailable")

    # ── Layer 3: Target validation ─────────────────────────────────────
    validation = _get_validation(
        device_id, required_capabilities, require_orchestration_eligible
    )
    if validation is not None:
        output.eligibility = bool(getattr(validation, "valid", False))
        output.capability_fit = bool(getattr(validation, "capability_match", False))
        val_reasons = list(getattr(validation, "reasons", []) or [])
        output.reasons.extend(val_reasons)
        output.sources["validation"] = (
            validation.to_dict() if hasattr(validation, "to_dict") else {}
        )
    else:
        output.reasons.append("validation-unavailable")

    # ── Policy score ───────────────────────────────────────────────────
    output.policy_score = _compute_policy_score(
        readiness=readiness,
        transport_present=output.transport_present,
        transport_usable=output.transport_usable,
        device_routable=output.device_routable,
        effective_path=output.effective_path,
        eligibility=output.eligibility,
    )

    if output.eligibility:
        output.selected_target_reason = (
            f"device eligible: score={output.policy_score:.3f} "
            f"path={output.effective_path}"
        )
        logger.debug(
            "PolicyConvergence: device=%s eligible=True score=%.3f path=%s",
            device_id,
            output.policy_score,
            output.effective_path,
            extra={
                "event": "policy_convergence_eligible",
                "device_id": device_id,
                "policy_score": output.policy_score,
            },
        )
    else:
        # Derive failure domain from primary ineligibility reason
        _fd = _classify_failure_domain(output)
        output.failure_domain = _fd
        output.degradation_reason = _build_degradation_reason(output)
        output.selected_target_reason = (
            f"device not selected: {output.degradation_reason or 'ineligible'}"
        )
        logger.debug(
            "PolicyConvergence: device=%s eligible=False "
            "failure_domain=%s reasons=%s",
            device_id,
            output.failure_domain,
            output.reasons,
            extra={
                "event": "policy_convergence_ineligible",
                "device_id": device_id,
                "failure_domain": output.failure_domain,
                "reasons": output.reasons,
            },
        )

    return output
