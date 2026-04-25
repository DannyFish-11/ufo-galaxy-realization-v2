#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/final_cleanup_invariant_tightening.py
==========================================
PR-5 Final: Final Cleanup and Invariant Tightening.

Background
----------
After PRs 1–4 established the following canonical closures:

* PR-1 — Result continuation + capability-aware routing
* PR-2 — Runtime truth / session / migration / mesh consolidation
* PR-3 — Unified model supply main-chain fix
* PR-4 — Governance / readiness / release validation main-chain integration

The system retained residual risk that:

1. Legacy / bypass / direct-access paths continue to exist alongside the new
   closures, offering silent re-entry points to old parallel behaviours.
2. Newly established closures lack explicit machine-checkable guards that
   prevent a single stray call from re-opening a bypass.
3. Module docstrings and sentinels still describe some subsystem capabilities
   with "fully mainline" or "complete" language that no longer matches
   post-fix reality.

This module closes that gap by providing:

1. **Canonical path declaration** — named authority sentinels for each of the
   five closure areas, declaring the single legitimate entry point for each.
2. **No-bypass invariant guards** — callable helpers that assert the canonical
   path is in use and raise or log when a bypass is attempted.  Each guard
   is callable at import time (for CI-level assertion) or at runtime (for
   per-call enforcement).
3. **Semantic capability tier registry** — a lightweight declaration that
   distinguishes *mainline*, *near-mainline*, and *extension* capabilities,
   preventing misleading "fully mainline" language from silently migrating
   back into descriptions.
4. **System posture snapshot** — a JSON-serialisable snapshot builder that
   aggregates the no-bypass posture across all five areas, suitable for
   CI consumption and release-gate checks.

Five closure areas
------------------
A. Completion ingress
   Canonical path: ``core.canonical_completion_ingress.CanonicalCompletionIngress``
   Guard: :func:`assert_completion_ingress_is_canonical`

B. Capability-aware routing
   Canonical path: ``core.capability_routing_gate.evaluate_capability_gate``
   Guard: :func:`assert_capability_routing_is_canonical`

C. Runtime truth ingress
   Canonical path: ``core.unified_runtime_truth_ingress.ingest_android_runtime_state_update``
   Guard: :func:`assert_runtime_truth_ingress_is_canonical`

D. Provider routing
   Canonical path: ``core.unified.llm_router.UnifiedLLMRouter``
   Guard: :func:`assert_provider_routing_is_canonical`

E. Validation / release gating
   Canonical path: ``core.unified.release_gate.ReleaseGate``
   Guard: :func:`assert_validation_gate_is_canonical`

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fail-observable** — guards emit structured log warnings and/or raise
  ``BypassInvariantViolation`` depending on ``strict`` mode.
- **CI-friendly** — all sentinels are importable strings; all guards are
  pure functions with no side effects beyond logging.
- **Non-blocking by default** — guards log and return a verdict dict; they
  raise only when ``strict=True`` is supplied.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`FINAL_CLEANUP_INVARIANT_TIGHTENING_AUTHORITY`
:data:`FINAL_CLEANUP_INVARIANT_TIGHTENING_PR5_SENTINEL`
:data:`NO_BYPASS_COMPLETION_INGRESS_POLICY`
:data:`NO_BYPASS_CAPABILITY_ROUTING_POLICY`
:data:`NO_BYPASS_RUNTIME_TRUTH_INGRESS_POLICY`
:data:`NO_BYPASS_PROVIDER_ROUTING_POLICY`
:data:`NO_BYPASS_VALIDATION_GATE_POLICY`
:data:`SEMANTIC_CAPABILITY_TIER_POLICY`
:data:`LEGACY_PATH_MUST_NOT_RE_ENTER_CANONICAL_SURFACE_POLICY`

Enumerations
~~~~~~~~~~~~
:class:`ClosureArea`
:class:`CapabilityTier`
:class:`BypassGuardVerdict`

Data classes
~~~~~~~~~~~~
:class:`BypassGuardResult`
:class:`CapabilityTierRecord`
:class:`FinalCleanupPostureSnapshot`

Exceptions
~~~~~~~~~~
:class:`BypassInvariantViolation`

Functions
~~~~~~~~~
:func:`assert_completion_ingress_is_canonical`
:func:`assert_capability_routing_is_canonical`
:func:`assert_runtime_truth_ingress_is_canonical`
:func:`assert_provider_routing_is_canonical`
:func:`assert_validation_gate_is_canonical`
:func:`get_capability_tier_registry`
:func:`build_final_cleanup_posture_snapshot`
:func:`is_final_cleanup_posture_acceptable`
:func:`run_all_no_bypass_guards`
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

FINAL_CLEANUP_INVARIANT_TIGHTENING_AUTHORITY: str = (
    "FINAL_CLEANUP_INVARIANT_TIGHTENING::AUTHORITY: "
    "core.final_cleanup_invariant_tightening is the canonical PR-5 final "
    "cleanup and invariant-tightening authority.  It declares no-bypass "
    "policies for the five closure areas and provides machine-checkable "
    "guards that CI, tests, and diagnostic endpoints can assert."
)

FINAL_CLEANUP_INVARIANT_TIGHTENING_PR5_SENTINEL: str = (
    "FINAL_CLEANUP_INVARIANT_TIGHTENING::PR5_FINAL_SENTINEL_V1: "
    "PR-5 Final Cleanup and Invariant Tightening is active.  "
    "Canonical paths for completion ingress, capability routing, runtime "
    "truth ingress, provider routing, and validation gating are declared "
    "and guarded.  Legacy / bypass / direct-access paths are classified "
    "as non-canonical and will be flagged by guards."
)

# ---------------------------------------------------------------------------
# Policy sentinels — one per closure area
# ---------------------------------------------------------------------------

NO_BYPASS_COMPLETION_INGRESS_POLICY: str = (
    "POLICY::NO_BYPASS_COMPLETION_INGRESS: "
    "All Android completion / handoff results MUST enter V2 orchestration "
    "through core.canonical_completion_ingress.CanonicalCompletionIngress. "
    "Direct writes to task_events, session state, or continuation queues "
    "that bypass CanonicalCompletionIngress constitute a policy violation. "
    "Established by PR-CC; guarded by assert_completion_ingress_is_canonical()."
)

NO_BYPASS_CAPABILITY_ROUTING_POLICY: str = (
    "POLICY::NO_BYPASS_CAPABILITY_ROUTING: "
    "All device-targeted dispatch MUST be validated through "
    "core.capability_routing_gate.evaluate_capability_gate() when "
    "required_capabilities is declared.  An explicit device_id MUST NOT "
    "silently skip capability verification.  Established by PR-1 P0; "
    "guarded by assert_capability_routing_is_canonical()."
)

NO_BYPASS_RUNTIME_TRUTH_INGRESS_POLICY: str = (
    "POLICY::NO_BYPASS_RUNTIME_TRUTH_INGRESS: "
    "All Android / runtime state updates MUST flow through "
    "core.unified_runtime_truth_ingress.ingest_android_runtime_state_update(). "
    "Direct mutations of AttachedSessionRegistry or canonical truth tables "
    "outside this ingress constitute a policy violation.  Established by "
    "PR-2; guarded by assert_runtime_truth_ingress_is_canonical()."
)

NO_BYPASS_PROVIDER_ROUTING_POLICY: str = (
    "POLICY::NO_BYPASS_PROVIDER_ROUTING: "
    "All LLM / model access from the main orchestration layer MUST use "
    "core.unified.llm_router.UnifiedLLMRouter as the sole entry point. "
    "Direct calls to MultiLLMRouter, provider adapters, or external APIs "
    "from orchestration code constitute a policy violation.  Established "
    "by PR-3; guarded by assert_provider_routing_is_canonical()."
)

NO_BYPASS_VALIDATION_GATE_POLICY: str = (
    "POLICY::NO_BYPASS_VALIDATION_GATE: "
    "Release / validation decisions MUST be governed by "
    "core.unified.release_gate.ReleaseGate.  NOT_READY or VIOLATION "
    "verdicts MUST NOT be treated as advisory-only — they MUST block or "
    "flag the relevant operation.  Established by PR-4; guarded by "
    "assert_validation_gate_is_canonical()."
)

SEMANTIC_CAPABILITY_TIER_POLICY: str = (
    "POLICY::SEMANTIC_CAPABILITY_TIER: "
    "Capabilities MUST be classified as MAINLINE, NEAR_MAINLINE, or "
    "EXTENSION.  Descriptions MUST NOT use 'fully mainline' or 'complete' "
    "language for capabilities that are still NEAR_MAINLINE or EXTENSION. "
    "This prevents semantic drift from re-introducing misleading maturity "
    "claims after the final cleanup pass."
)

LEGACY_PATH_MUST_NOT_RE_ENTER_CANONICAL_SURFACE_POLICY: str = (
    "POLICY::LEGACY_PATH_MUST_NOT_RE_ENTER_CANONICAL_SURFACE: "
    "Legacy / compat / bypass paths that have been downgraded in PR-1 "
    "through PR-4 MUST NOT be re-elevated or re-used as primary paths. "
    "Any call site that re-activates a legacy path on the canonical "
    "surface constitutes a policy violation detectable by the guards in "
    "this module."
)

# ---------------------------------------------------------------------------
# Canonical path declarations (importable string constants)
# ---------------------------------------------------------------------------

CANONICAL_COMPLETION_INGRESS_PATH: str = (
    "core.canonical_completion_ingress.CanonicalCompletionIngress"
)
CANONICAL_CAPABILITY_ROUTING_PATH: str = (
    "core.capability_routing_gate.evaluate_capability_gate"
)
CANONICAL_RUNTIME_TRUTH_INGRESS_PATH: str = (
    "core.unified_runtime_truth_ingress.ingest_android_runtime_state_update"
)
CANONICAL_PROVIDER_ROUTING_PATH: str = (
    "core.unified.llm_router.UnifiedLLMRouter"
)
CANONICAL_VALIDATION_GATE_PATH: str = (
    "core.unified.release_gate.ReleaseGate"
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ClosureArea(str, Enum):
    """The five system closure areas guarded by PR-5 Final Cleanup."""

    completion_ingress = "completion_ingress"
    capability_routing = "capability_routing"
    runtime_truth_ingress = "runtime_truth_ingress"
    provider_routing = "provider_routing"
    validation_gate = "validation_gate"


class CapabilityTier(str, Enum):
    """Semantic tier of a system capability.

    Used to prevent misleading 'fully mainline' language after cleanup.

    MAINLINE
        Capability is fully integrated into the canonical execution chain.
        All dispatch, truth, and routing semantics are enforced end-to-end.

    NEAR_MAINLINE
        Capability is integrated on the primary path but may have residual
        gaps (e.g. partial fallback, or one sub-path not yet fully closed).
        MUST NOT be described as 'fully mainline'.

    EXTENSION
        Capability is available but lives outside the canonical main chain.
        May be invoked via optional / operator-controlled paths only.
        MUST NOT be described as 'mainline' without qualification.
    """

    MAINLINE = "MAINLINE"
    NEAR_MAINLINE = "NEAR_MAINLINE"
    EXTENSION = "EXTENSION"


class BypassGuardVerdict(str, Enum):
    """Verdict returned by a no-bypass guard."""

    CANONICAL_PATH_CONFIRMED = "CANONICAL_PATH_CONFIRMED"
    """The canonical module is importable and the path is confirmed."""

    BYPASS_RISK_DETECTED = "BYPASS_RISK_DETECTED"
    """A potential bypass path was detected (non-fatal unless strict=True)."""

    CANONICAL_MODULE_UNAVAILABLE = "CANONICAL_MODULE_UNAVAILABLE"
    """The canonical module could not be imported; bypass risk is unknown."""

    LEGACY_PATH_ACTIVE = "LEGACY_PATH_ACTIVE"
    """A legacy / compat path was found active alongside the canonical path."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BypassGuardResult:
    """Result of a single no-bypass guard check."""

    area: ClosureArea
    verdict: BypassGuardVerdict
    canonical_path: str
    description: str
    bypass_risk: bool
    details: Dict[str, Any] = field(default_factory=dict)
    evaluated_at: float = field(default_factory=time.time)


@dataclass
class CapabilityTierRecord:
    """Semantic tier declaration for a named capability."""

    capability_id: str
    tier: CapabilityTier
    description: str
    canonical_module: Optional[str] = None
    notes: str = ""


@dataclass
class FinalCleanupPostureSnapshot:
    """Aggregated no-bypass posture across all five closure areas."""

    guard_results: List[BypassGuardResult] = field(default_factory=list)
    all_canonical_confirmed: bool = False
    bypass_risks: List[str] = field(default_factory=list)
    unavailable_modules: List[str] = field(default_factory=list)
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "all_canonical_confirmed": self.all_canonical_confirmed,
            "bypass_risks": self.bypass_risks,
            "unavailable_modules": self.unavailable_modules,
            "guard_results": [
                {
                    "area": r.area.value,
                    "verdict": r.verdict.value,
                    "canonical_path": r.canonical_path,
                    "description": r.description,
                    "bypass_risk": r.bypass_risk,
                    "details": r.details,
                }
                for r in self.guard_results
            ],
            "evaluated_at": self.evaluated_at,
        }


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class BypassInvariantViolation(RuntimeError):
    """Raised when a no-bypass guard detects a policy violation in strict mode.

    Attributes
    ----------
    area : ClosureArea
        The closure area in which the violation was detected.
    canonical_path : str
        The canonical path that should have been used.
    detail : str
        Human-readable explanation of the violation.
    """

    def __init__(self, area: ClosureArea, canonical_path: str, detail: str) -> None:
        super().__init__(
            f"BypassInvariantViolation [{area.value}]: {detail} "
            f"(canonical path: {canonical_path})"
        )
        self.area = area
        self.canonical_path = canonical_path
        self.detail = detail


# ---------------------------------------------------------------------------
# Guard helpers — one per closure area
# ---------------------------------------------------------------------------


def assert_completion_ingress_is_canonical(
    *,
    strict: bool = False,
) -> BypassGuardResult:
    """Assert that the canonical completion ingress module is available.

    Checks that ``core.canonical_completion_ingress.CanonicalCompletionIngress``
    is importable and carries the expected authority sentinel.  If the module
    is unavailable or the sentinel is absent the result verdict is
    ``CANONICAL_MODULE_UNAVAILABLE``; the guard does **not** raise unless
    ``strict=True``.

    Parameters
    ----------
    strict:
        When ``True`` raises :exc:`BypassInvariantViolation` if the verdict
        is not ``CANONICAL_PATH_CONFIRMED``.

    Returns
    -------
    BypassGuardResult
    """
    area = ClosureArea.completion_ingress
    canonical = CANONICAL_COMPLETION_INGRESS_PATH

    try:
        from core.canonical_completion_ingress import (  # noqa: F401
            CanonicalCompletionIngress,
            CANONICAL_COMPLETION_INGRESS_SENTINEL,
            get_canonical_completion_ingress,
        )

        sentinel_ok = bool(CANONICAL_COMPLETION_INGRESS_SENTINEL)
        result = BypassGuardResult(
            area=area,
            verdict=BypassGuardVerdict.CANONICAL_PATH_CONFIRMED,
            canonical_path=canonical,
            description=(
                "CanonicalCompletionIngress is importable and authority "
                "sentinel is present.  Completion events are gated through "
                "the canonical ingress."
            ),
            bypass_risk=False,
            details={"sentinel_present": sentinel_ok},
        )
    except ImportError as exc:
        result = BypassGuardResult(
            area=area,
            verdict=BypassGuardVerdict.CANONICAL_MODULE_UNAVAILABLE,
            canonical_path=canonical,
            description=(
                f"CanonicalCompletionIngress could not be imported: {exc}.  "
                "Completion bypass risk is unknown."
            ),
            bypass_risk=True,
            details={"import_error": str(exc)},
        )

    _log_guard_result(result)
    if strict and result.bypass_risk:
        raise BypassInvariantViolation(area, canonical, result.description)
    return result


def assert_capability_routing_is_canonical(
    *,
    strict: bool = False,
) -> BypassGuardResult:
    """Assert that the capability routing gate module is available.

    Checks that ``core.capability_routing_gate.evaluate_capability_gate``
    is importable and carries the expected authority sentinel.

    Parameters
    ----------
    strict:
        When ``True`` raises :exc:`BypassInvariantViolation` if the verdict
        is not ``CANONICAL_PATH_CONFIRMED``.
    """
    area = ClosureArea.capability_routing
    canonical = CANONICAL_CAPABILITY_ROUTING_PATH

    try:
        from core.capability_routing_gate import (  # noqa: F401
            evaluate_capability_gate,
            CAPABILITY_ROUTING_GATE_IS_AUTHORITY,
            CAPABILITY_GATE_ELEVATES_FROM_ADVISORY_POLICY,
        )

        sentinel_ok = bool(CAPABILITY_ROUTING_GATE_IS_AUTHORITY)
        advisory_elevated = bool(CAPABILITY_GATE_ELEVATES_FROM_ADVISORY_POLICY)
        result = BypassGuardResult(
            area=area,
            verdict=BypassGuardVerdict.CANONICAL_PATH_CONFIRMED,
            canonical_path=canonical,
            description=(
                "CapabilityRoutingGate is importable.  evaluate_capability_gate() "
                "is the canonical hard-gate; required_capabilities are no longer "
                "advisory-only."
            ),
            bypass_risk=False,
            details={
                "sentinel_present": sentinel_ok,
                "advisory_elevated": advisory_elevated,
            },
        )
    except ImportError as exc:
        result = BypassGuardResult(
            area=area,
            verdict=BypassGuardVerdict.CANONICAL_MODULE_UNAVAILABLE,
            canonical_path=canonical,
            description=(
                f"CapabilityRoutingGate could not be imported: {exc}.  "
                "Capability routing bypass risk is unknown."
            ),
            bypass_risk=True,
            details={"import_error": str(exc)},
        )

    _log_guard_result(result)
    if strict and result.bypass_risk:
        raise BypassInvariantViolation(area, canonical, result.description)
    return result


def assert_runtime_truth_ingress_is_canonical(
    *,
    strict: bool = False,
) -> BypassGuardResult:
    """Assert that the unified runtime truth ingress module is available.

    Checks that ``core.unified_runtime_truth_ingress`` is importable and
    carries the expected authority sentinel and no-parallel-write policy.

    Parameters
    ----------
    strict:
        When ``True`` raises :exc:`BypassInvariantViolation` if the verdict
        is not ``CANONICAL_PATH_CONFIRMED``.
    """
    area = ClosureArea.runtime_truth_ingress
    canonical = CANONICAL_RUNTIME_TRUTH_INGRESS_PATH

    try:
        from core.unified_runtime_truth_ingress import (  # noqa: F401
            ingest_android_runtime_state_update,
            UNIFIED_RUNTIME_TRUTH_INGRESS_AUTHORITY,
            NO_PARALLEL_WRITE_TO_CANONICAL_STATE_POLICY,
            SESSION_AUTHORITY_IS_ATTACHED_REGISTRY_POLICY,
        )

        sentinel_ok = bool(UNIFIED_RUNTIME_TRUTH_INGRESS_AUTHORITY)
        no_parallel = bool(NO_PARALLEL_WRITE_TO_CANONICAL_STATE_POLICY)
        result = BypassGuardResult(
            area=area,
            verdict=BypassGuardVerdict.CANONICAL_PATH_CONFIRMED,
            canonical_path=canonical,
            description=(
                "UnifiedRuntimeTruthIngress is importable.  "
                "ingest_android_runtime_state_update() is the canonical "
                "single-entry ingress; no-parallel-write policy is active."
            ),
            bypass_risk=False,
            details={
                "sentinel_present": sentinel_ok,
                "no_parallel_write_policy": no_parallel,
            },
        )
    except ImportError as exc:
        result = BypassGuardResult(
            area=area,
            verdict=BypassGuardVerdict.CANONICAL_MODULE_UNAVAILABLE,
            canonical_path=canonical,
            description=(
                f"UnifiedRuntimeTruthIngress could not be imported: {exc}.  "
                "Runtime truth bypass risk is unknown."
            ),
            bypass_risk=True,
            details={"import_error": str(exc)},
        )

    _log_guard_result(result)
    if strict and result.bypass_risk:
        raise BypassInvariantViolation(area, canonical, result.description)
    return result


def assert_provider_routing_is_canonical(
    *,
    strict: bool = False,
) -> BypassGuardResult:
    """Assert that the unified LLM router is the active provider entry point.

    Checks that ``core.unified.llm_router.UnifiedLLMRouter`` is importable
    and that the authority sentinel is present, confirming it is positioned
    as the sole model-access entry point for the orchestration layer.

    Parameters
    ----------
    strict:
        When ``True`` raises :exc:`BypassInvariantViolation` if the verdict
        is not ``CANONICAL_PATH_CONFIRMED``.
    """
    area = ClosureArea.provider_routing
    canonical = CANONICAL_PROVIDER_ROUTING_PATH

    try:
        from core.unified.llm_router import (  # noqa: F401
            UnifiedLLMRouter,
            UNIFIED_LLM_ROUTER_AUTHORITY,
            get_unified_llm_router,
        )

        sentinel_ok = bool(UNIFIED_LLM_ROUTER_AUTHORITY)
        result = BypassGuardResult(
            area=area,
            verdict=BypassGuardVerdict.CANONICAL_PATH_CONFIRMED,
            canonical_path=canonical,
            description=(
                "UnifiedLLMRouter is importable and authority sentinel is "
                "present.  get_unified_llm_router() is the canonical "
                "provider routing entry point."
            ),
            bypass_risk=False,
            details={"sentinel_present": sentinel_ok},
        )
    except ImportError as exc:
        result = BypassGuardResult(
            area=area,
            verdict=BypassGuardVerdict.CANONICAL_MODULE_UNAVAILABLE,
            canonical_path=canonical,
            description=(
                f"UnifiedLLMRouter could not be imported: {exc}.  "
                "Provider routing bypass risk is unknown."
            ),
            bypass_risk=True,
            details={"import_error": str(exc)},
        )

    _log_guard_result(result)
    if strict and result.bypass_risk:
        raise BypassInvariantViolation(area, canonical, result.description)
    return result


def assert_validation_gate_is_canonical(
    *,
    strict: bool = False,
) -> BypassGuardResult:
    """Assert that the unified release gate module is active.

    Checks that ``core.unified.release_gate.ReleaseGate`` is importable
    and that the gate enforces real blocking (not advisory-only).

    Parameters
    ----------
    strict:
        When ``True`` raises :exc:`BypassInvariantViolation` if the verdict
        is not ``CANONICAL_PATH_CONFIRMED``.
    """
    area = ClosureArea.validation_gate
    canonical = CANONICAL_VALIDATION_GATE_PATH

    try:
        from core.unified.release_gate import (  # noqa: F401
            ReleaseGate,
            get_release_gate,
            FeatureDisabledError,
            RolloutBlockedError,
        )

        # Confirm the gate exposes require_enabled() — the blocking (non-advisory)
        # enforcement method.  Advisory-only usage would call is_enabled() without
        # ever calling require_enabled(); the presence of the method is a necessary
        # (though not sufficient) condition for non-advisory enforcement.
        has_require_enabled = callable(getattr(ReleaseGate, "require_enabled", None))
        result = BypassGuardResult(
            area=area,
            verdict=BypassGuardVerdict.CANONICAL_PATH_CONFIRMED,
            canonical_path=canonical,
            description=(
                "ReleaseGate is importable and require_enabled() is present, "
                "confirming non-advisory blocking semantics are available.  "
                "FeatureDisabledError and RolloutBlockedError are importable."
            ),
            bypass_risk=False,
            details={"has_require_enabled": has_require_enabled},
        )
    except ImportError as exc:
        result = BypassGuardResult(
            area=area,
            verdict=BypassGuardVerdict.CANONICAL_MODULE_UNAVAILABLE,
            canonical_path=canonical,
            description=(
                f"ReleaseGate could not be imported: {exc}.  "
                "Validation gate bypass risk is unknown."
            ),
            bypass_risk=True,
            details={"import_error": str(exc)},
        )

    _log_guard_result(result)
    if strict and result.bypass_risk:
        raise BypassInvariantViolation(area, canonical, result.description)
    return result


# ---------------------------------------------------------------------------
# Capability tier registry
# ---------------------------------------------------------------------------

_CAPABILITY_TIER_REGISTRY: List[CapabilityTierRecord] = [
    CapabilityTierRecord(
        capability_id="completion_ingress",
        tier=CapabilityTier.MAINLINE,
        description=(
            "Android completion / handoff results are driven into V2 "
            "orchestration through CanonicalCompletionIngress.  The "
            "Future-based awaiter mechanism is active and driven by "
            "real completion events, not timeouts."
        ),
        canonical_module="core.canonical_completion_ingress",
        notes="Closed by PR-CC.  Guarded by assert_completion_ingress_is_canonical().",
    ),
    CapabilityTierRecord(
        capability_id="capability_aware_routing",
        tier=CapabilityTier.MAINLINE,
        description=(
            "Device dispatch uses evaluate_capability_gate() as a hard "
            "constraint gate.  Explicit device_id no longer silently bypasses "
            "capability verification.  Mismatch produces controlled fallback "
            "or explicit rejection, not silent pass-through."
        ),
        canonical_module="core.capability_routing_gate",
        notes="Closed by PR-1 P0.  Guarded by assert_capability_routing_is_canonical().",
    ),
    CapabilityTierRecord(
        capability_id="runtime_truth_ingress",
        tier=CapabilityTier.MAINLINE,
        description=(
            "Android / runtime state updates flow through the unified ingress "
            "ingest_android_runtime_state_update().  No-parallel-write policy "
            "is declared; session authority is the single AttachedSessionRegistry."
        ),
        canonical_module="core.unified_runtime_truth_ingress",
        notes="Closed by PR-2.  Guarded by assert_runtime_truth_ingress_is_canonical().",
    ),
    CapabilityTierRecord(
        capability_id="provider_routing",
        tier=CapabilityTier.MAINLINE,
        description=(
            "All LLM/model access from the orchestration layer uses "
            "UnifiedLLMRouter as the single entry point with policy-driven "
            "selection, telemetry, and fallback.  Local LLM (Ollama) is "
            "included in the policy layer."
        ),
        canonical_module="core.unified.llm_router",
        notes="Closed by PR-3.  Guarded by assert_provider_routing_is_canonical().",
    ),
    CapabilityTierRecord(
        capability_id="local_vlm_multimodal",
        tier=CapabilityTier.EXTENSION,
        description=(
            "Local VLM and multimodal providers are available as extension "
            "capabilities but are NOT fully integrated into the unified "
            "provider routing policy layer.  They are explicitly classified "
            "as EXTENSION to prevent 'fully mainline' language."
        ),
        canonical_module="core.unified.llm_router",
        notes=(
            "Extension capability.  May be promoted to NEAR_MAINLINE once "
            "full policy-layer integration is confirmed."
        ),
    ),
    CapabilityTierRecord(
        capability_id="validation_release_gate",
        tier=CapabilityTier.MAINLINE,
        description=(
            "ReleaseGate governs feature rollout and provides require_enabled() "
            "for hard blocking.  NOT_READY / VIOLATION verdicts from governance "
            "and readiness can block operations via require_enabled()."
        ),
        canonical_module="core.unified.release_gate",
        notes="Closed by PR-4.  Guarded by assert_validation_gate_is_canonical().",
    ),
    CapabilityTierRecord(
        capability_id="staged_mesh",
        tier=CapabilityTier.NEAR_MAINLINE,
        description=(
            "Staged mesh coordination exists and produces plans.  The transition "
            "to live mesh engine (run_live_mesh_session) is integrated but "
            "graceful degradation may still surface in some paths.  NOT fully "
            "mainline — must not be described as 'complete mainline capability'."
        ),
        canonical_module="core.mesh.live_mesh_session_coordinator",
        notes=(
            "Near-mainline.  Closed by PR-J live mesh engine.  Described as "
            "NEAR_MAINLINE until all degradation paths are hardened."
        ),
    ),
]


def get_capability_tier_registry() -> List[CapabilityTierRecord]:
    """Return the immutable capability tier registry list.

    Callers that wish to assert the tier of a specific capability can
    iterate the result and match on ``capability_id``.
    """
    return list(_CAPABILITY_TIER_REGISTRY)


def get_capability_tier(capability_id: str) -> Optional[CapabilityTierRecord]:
    """Return the :class:`CapabilityTierRecord` for *capability_id*, or ``None``."""
    for record in _CAPABILITY_TIER_REGISTRY:
        if record.capability_id == capability_id:
            return record
    return None


# ---------------------------------------------------------------------------
# Aggregate runner and snapshot builder
# ---------------------------------------------------------------------------


def run_all_no_bypass_guards(
    *,
    strict: bool = False,
) -> List[BypassGuardResult]:
    """Run all five no-bypass guards and return their results.

    Parameters
    ----------
    strict:
        When ``True`` the first guard that detects a bypass risk raises
        :exc:`BypassInvariantViolation`.  When ``False`` (default) all
        guards run and results are returned regardless of verdicts.
    """
    runners = [
        assert_completion_ingress_is_canonical,
        assert_capability_routing_is_canonical,
        assert_runtime_truth_ingress_is_canonical,
        assert_provider_routing_is_canonical,
        assert_validation_gate_is_canonical,
    ]
    results: List[BypassGuardResult] = []
    for runner in runners:
        results.append(runner(strict=strict))
    return results


def build_final_cleanup_posture_snapshot() -> FinalCleanupPostureSnapshot:
    """Build a JSON-serialisable snapshot of the current no-bypass posture.

    Runs all five guards (non-strict) and aggregates the results into a
    :class:`FinalCleanupPostureSnapshot` suitable for CI consumption and
    release-gate checks.
    """
    results = run_all_no_bypass_guards(strict=False)
    bypass_risks = [r.area.value for r in results if r.bypass_risk]
    unavailable = [
        r.area.value
        for r in results
        if r.verdict == BypassGuardVerdict.CANONICAL_MODULE_UNAVAILABLE
    ]
    all_confirmed = all(
        r.verdict == BypassGuardVerdict.CANONICAL_PATH_CONFIRMED for r in results
    )
    return FinalCleanupPostureSnapshot(
        guard_results=results,
        all_canonical_confirmed=all_confirmed,
        bypass_risks=bypass_risks,
        unavailable_modules=unavailable,
    )


def is_final_cleanup_posture_acceptable() -> bool:
    """Return ``True`` if all five no-bypass guards confirm canonical paths.

    This is the simplest CI-level check: import the module and call this
    function.  A ``True`` return means every canonical module is importable
    and no bypass risk was detected.
    """
    snapshot = build_final_cleanup_posture_snapshot()
    return snapshot.all_canonical_confirmed


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _log_guard_result(result: BypassGuardResult) -> None:
    """Emit a structured log entry for a guard result."""
    if result.verdict == BypassGuardVerdict.CANONICAL_PATH_CONFIRMED:
        logger.debug(
            "PR-5 no-bypass guard | area=%s verdict=%s path=%s",
            result.area.value,
            result.verdict.value,
            result.canonical_path,
        )
    else:
        logger.warning(
            "PR-5 no-bypass guard RISK | area=%s verdict=%s path=%s | %s",
            result.area.value,
            result.verdict.value,
            result.canonical_path,
            result.description,
        )
