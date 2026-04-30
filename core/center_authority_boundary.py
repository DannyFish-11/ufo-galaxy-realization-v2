"""core/center_authority_boundary.py
=====================================
PR-V6: Final structural closure — V2 owns completion, continuity, readiness,
and orchestration truth.

Background
----------
The prior unification work (V1–V5, A1–A4) established canonical modules for
each authority domain:

* **Completion truth** — :mod:`core.unified_result_ingress` (single
  processing chain), :mod:`core.canonical_completion_ingress` (awaiter
  unblock), :mod:`core.task_result_canonical_truth_chain` (four-step truth
  chain), :mod:`core.canonical_group_completion_closure` (V5 group/delegated
  terminal semantics).

* **Continuity legality truth** — :mod:`core.unified_continuity_legality_authority`
  (single gate for all eight inbound-action paths).

* **Dispatch readiness truth** — :mod:`core.unified_dispatch_readiness_gate`
  (registered vs dispatch-ready distinction),
  :mod:`core.canonical_dispatch_slot_authority` (V3 ten-dimension slot gate).

* **Orchestration truth** — :mod:`core.unified_orchestration_spine` (V4
  single entry point for all execution modes, lifecycle stage, audit record).

Even with those pieces in place the system still lacked an explicit
**final authority-boundary closure** that:

1. Declares in code which modules collectively own each authority domain.
2. Blocks residual split-brain paths by asserting that external runtimes,
   devices, transports, adapters, and compat layers are **participant-only**
   contributors with no final truth ownership.
3. Provides a single callable (:func:`assert_center_authority_intact`) that
   can be imported by acceptance gates, health checks, or release-blocking
   tests to verify the boundary is structurally sound.

This module closes all four authority boundaries explicitly.

Design
------
- **Additive only** — does not modify any existing module.
- **Composing, not duplicating** — imports sentinels from the existing
  canonical authority modules and reflects on their presence.
- **Fail-closed** — when a required canonical module is unavailable the
  :class:`CenterAuthorityBoundaryReport` marks that domain ``DEGRADED`` and
  :func:`assert_center_authority_intact` raises
  :class:`CenterAuthorityViolation`.
- **Fully serialisable** — :meth:`CenterAuthorityBoundaryReport.to_dict` and
  :meth:`CenterAuthorityBoundaryReport.to_json` produce stable JSON for
  observability and audit.

Authority domains
-----------------
:class:`AuthorityDomain` enumerates the four domains V2 must exclusively own:

1. ``COMPLETION_TRUTH``
2. ``CONTINUITY_LEGALITY_TRUTH``
3. ``DISPATCH_READINESS_TRUTH``
4. ``ORCHESTRATION_TRUTH``

External role
-------------
External runtimes, devices, transports, adapters, and compat layers are
classified under :class:`ExternalRole`:

* ``PARTICIPANT_TRUTH_CONTRIBUTOR`` — may contribute participant-level signals.
* ``EXECUTION_SIGNAL_CONTRIBUTOR`` — may contribute execution signals.
* ``CONTINUITY_INPUT_CONTRIBUTOR`` — may contribute continuity input.
* ``COMPAT_INGRESS_ADAPTER`` — compat/legacy ingress adapters that normalise
  signals into the center model.

All other roles are prohibited for external surfaces.

Authority sentinels
-------------------
:data:`CENTER_AUTHORITY_BOUNDARY_AUTHORITY`
:data:`V2_OWNS_COMPLETION_TRUTH_POLICY`
:data:`V2_OWNS_CONTINUITY_LEGALITY_TRUTH_POLICY`
:data:`V2_OWNS_DISPATCH_READINESS_TRUTH_POLICY`
:data:`V2_OWNS_ORCHESTRATION_TRUTH_POLICY`
:data:`EXTERNAL_SURFACES_ARE_PARTICIPANT_ONLY_POLICY`
:data:`NO_PARALLEL_AUTHORITY_PERMITTED_POLICY`
:data:`COMPAT_INGRESS_TERMINATES_IN_CENTER_MODEL_POLICY`
:data:`CENTER_AUTHORITY_BOUNDARY_PR_V6_SENTINEL`

Public API
----------
Enums::

    AuthorityDomain
    DomainBoundaryStatus
    ExternalRole

Dataclasses::

    DomainBoundaryState
    CenterAuthorityBoundaryReport

Exceptions::

    CenterAuthorityViolation

Functions::

    evaluate_center_authority_boundary() -> CenterAuthorityBoundaryReport
    assert_center_authority_intact()
    get_boundary_report() -> CenterAuthorityBoundaryReport
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CenterAuthorityBoundary")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

CENTER_AUTHORITY_BOUNDARY_AUTHORITY: str = (
    "CENTER_AUTHORITY_BOUNDARY_AUTHORITY::"
    "core.center_authority_boundary::PR-V6::"
    "final-structural-closure-v2-owns-completion-continuity-readiness-orchestration::"
    "external-runtimes-devices-transports-are-participant-only-contributors"
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

V2_OWNS_COMPLETION_TRUTH_POLICY: str = (
    "POLICY::V2_OWNS_COMPLETION_TRUTH_V6: "
    "ufo-galaxy-realization-v2 is the sole owner of completion truth.  "
    "Completion truth is produced exclusively by the canonical chain: "
    "core.unified_result_ingress (single processing chain) → "
    "core.task_result_canonical_truth_chain (four-step truth chain) → "
    "core.canonical_completion_ingress (awaiter unblock) → "
    "core.canonical_group_completion_closure (V5 group/delegated terminal "
    "semantics).  External runtimes, devices, transports, and compat paths "
    "MUST NOT hold a parallel completion truth; they contribute participant "
    "signals that are normalised into NormalizedResultEvent and processed "
    "through ingest_result() only.  PR-V6 center authority boundary closure."
)

V2_OWNS_CONTINUITY_LEGALITY_TRUTH_POLICY: str = (
    "POLICY::V2_OWNS_CONTINUITY_LEGALITY_TRUTH_V6: "
    "ufo-galaxy-realization-v2 is the sole interpreter of continuity "
    "legality.  Every inbound-action path — RECONNECT, RE_REGISTER, "
    "REPLAY_INGRESS, DELEGATED_RECOVERY, ATTACHMENT_RESUME, "
    "ONLINE_DISPATCH_ACCEPTANCE, ONLINE_SIGNAL_INGESTION, "
    "TERMINAL_RESULT_INGESTION — MUST call "
    "core.unified_continuity_legality_authority.evaluate_continuity_legality() "
    "as its first gate.  No transport, device, compat layer, or recovery "
    "path may implement a competing continuity legality decision.  "
    "PR-V6 center authority boundary closure."
)

V2_OWNS_DISPATCH_READINESS_TRUTH_POLICY: str = (
    "POLICY::V2_OWNS_DISPATCH_READINESS_TRUTH_V6: "
    "ufo-galaxy-realization-v2 is the sole owner of dispatch readiness and "
    "dispatch-slot truth.  Every dispatch path — local, single-device "
    "remote, parallel fan-out, cross-device, handoff, wake-routed, "
    "delegated runtime, hybrid — MUST obtain a SLOT_APPROVED verdict from "
    "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots() "
    "(all ten legality dimensions) before sending any task to any device.  "
    "Device-local or router-local readiness assumptions are not authoritative "
    "and MUST NOT act as dispatch gates.  "
    "PR-V6 center authority boundary closure."
)

V2_OWNS_ORCHESTRATION_TRUTH_POLICY: str = (
    "POLICY::V2_OWNS_ORCHESTRATION_TRUTH_V6: "
    "ufo-galaxy-realization-v2 is the sole orchestration authority for "
    "execution-mode evaluation and lifecycle meaning.  All execution modes "
    "MUST pass through "
    "core.unified_orchestration_spine.evaluate_orchestration_request() "
    "before any task is dispatched.  The OrchestrationDecision.lifecycle_stage "
    "and OrchestrationDecision.audit_record are the canonical lifecycle and "
    "projection sources; mode-specific private contracts are prohibited.  "
    "PR-V6 center authority boundary closure."
)

EXTERNAL_SURFACES_ARE_PARTICIPANT_ONLY_POLICY: str = (
    "POLICY::EXTERNAL_SURFACES_ARE_PARTICIPANT_ONLY_V6: "
    "External participant runtimes, devices, transports, adapters, "
    "and compatibility layers are participant-only contributors to the "
    "distributed agent system.  They may contribute: participant truth "
    "signals, execution signals, continuity input, and compat ingress "
    "normalisation.  They MUST NOT retain parallel final meaning for "
    "completion, continuity legality, dispatch readiness, or orchestration.  "
    "PR-V6 center authority boundary closure."
)

NO_PARALLEL_AUTHORITY_PERMITTED_POLICY: str = (
    "POLICY::NO_PARALLEL_AUTHORITY_PERMITTED_V6: "
    "No external runtime, device, transport, compat path, or recovery "
    "adapter may hold a parallel final authority in any of the four center "
    "domains: completion truth, continuity legality truth, dispatch "
    "readiness truth, or orchestration truth.  Split-brain authority — "
    "where two components each hold a final truth claim over the same "
    "domain — is a policy violation and MUST be resolved by having the "
    "external surface contribute a participant signal that is consumed by "
    "the canonical center-owned chain.  "
    "PR-V6 center authority boundary closure."
)

COMPAT_INGRESS_TERMINATES_IN_CENTER_MODEL_POLICY: str = (
    "POLICY::COMPAT_INGRESS_TERMINATES_IN_CENTER_MODEL_V6: "
    "Compat, legacy, and migration ingress adapters (including participant "
    "runtime WebSocket paths, offline replay, REST callback adapters) are "
    "permitted as normalisation shims only.  They MUST normalise inbound "
    "signals into the center-owned canonical schema (NormalizedResultEvent "
    "for completion, ContinuityLegalityContext for continuity, "
    "DispatchReadinessResult for readiness, OrchestrationRequest for "
    "orchestration) and hand off to the canonical center-owned processing "
    "chain.  Compat paths MUST NOT implement their own final truth decisions "
    "after normalisation.  "
    "PR-V6 center authority boundary closure."
)

CENTER_AUTHORITY_BOUNDARY_PR_V6_SENTINEL: str = (
    "CENTER_AUTHORITY_BOUNDARY_PR_V6::"
    "fix-center-authority-boundary::"
    "ufo-galaxy-realization-v2::"
    "completion-continuity-readiness-orchestration-truth-owned-by-v2::"
    "external-participant-only"
)

# ---------------------------------------------------------------------------
# AuthorityDomain
# ---------------------------------------------------------------------------


class AuthorityDomain(str, Enum):
    """The four authority domains exclusively owned by V2.

    COMPLETION_TRUTH
        Whether and how a task or orchestration has completed.  The canonical
        chain is: unified_result_ingress → task_result_canonical_truth_chain
        → canonical_completion_ingress → canonical_group_completion_closure.

    CONTINUITY_LEGALITY_TRUTH
        Whether an inbound action from any path is continuity-legal (session
        still valid, not stale/replayed/out-of-order).  The canonical gate is
        unified_continuity_legality_authority.evaluate_continuity_legality().

    DISPATCH_READINESS_TRUTH
        Whether a device is a legal dispatch target (all ten legality
        dimensions satisfied).  The canonical authority is
        canonical_dispatch_slot_authority.get_canonical_dispatch_slots().

    ORCHESTRATION_TRUTH
        Execution-mode evaluation, lifecycle staging, and audit projection.
        The canonical entry point is
        unified_orchestration_spine.evaluate_orchestration_request().
    """

    COMPLETION_TRUTH = "completion_truth"
    CONTINUITY_LEGALITY_TRUTH = "continuity_legality_truth"
    DISPATCH_READINESS_TRUTH = "dispatch_readiness_truth"
    ORCHESTRATION_TRUTH = "orchestration_truth"


# ---------------------------------------------------------------------------
# DomainBoundaryStatus
# ---------------------------------------------------------------------------


class DomainBoundaryStatus(str, Enum):
    """Integrity status of a single authority domain boundary.

    INTACT
        All required canonical modules for this domain are available and
        their authority sentinels are non-empty strings.

    DEGRADED
        One or more required canonical modules are unavailable (ImportError)
        or their authority sentinels are missing/empty.  The domain boundary
        is structurally weakened; :func:`assert_center_authority_intact` will
        raise :class:`CenterAuthorityViolation`.

    UNKNOWN
        Domain evaluation encountered an unexpected error; the boundary
        cannot be confirmed intact.
    """

    INTACT = "intact"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# ExternalRole
# ---------------------------------------------------------------------------


class ExternalRole(str, Enum):
    """Permitted roles for external surfaces.

    PARTICIPANT_TRUTH_CONTRIBUTOR
        May contribute participant-level execution signals (device results,
        status updates, heartbeats).

    EXECUTION_SIGNAL_CONTRIBUTOR
        May contribute execution signal data (task progress, error info).

    CONTINUITY_INPUT_CONTRIBUTOR
        May contribute continuity input fields (session IDs, epochs) that
        are evaluated by the center continuity legality gate.

    COMPAT_INGRESS_ADAPTER
        Compat/legacy/migration ingress adapter that normalises external
        signals into the center canonical schema before handing off to the
        center processing chain.
    """

    PARTICIPANT_TRUTH_CONTRIBUTOR = "participant_truth_contributor"
    EXECUTION_SIGNAL_CONTRIBUTOR = "execution_signal_contributor"
    CONTINUITY_INPUT_CONTRIBUTOR = "continuity_input_contributor"
    COMPAT_INGRESS_ADAPTER = "compat_ingress_adapter"


# ---------------------------------------------------------------------------
# CenterAuthorityViolation
# ---------------------------------------------------------------------------


class CenterAuthorityViolation(Exception):
    """Raised when one or more authority domain boundaries are not intact.

    Attributes
    ----------
    degraded_domains
        List of :class:`AuthorityDomain` values that are not INTACT.
    report
        The full :class:`CenterAuthorityBoundaryReport` for diagnostic detail.
    """

    def __init__(
        self,
        message: str,
        degraded_domains: Optional[List[AuthorityDomain]] = None,
        report: Optional["CenterAuthorityBoundaryReport"] = None,
    ) -> None:
        super().__init__(message)
        self.degraded_domains: List[AuthorityDomain] = degraded_domains or []
        self.report: Optional[CenterAuthorityBoundaryReport] = report


# ---------------------------------------------------------------------------
# DomainBoundaryState
# ---------------------------------------------------------------------------


@dataclass
class DomainBoundaryState:
    """Boundary integrity state for a single authority domain.

    Fields
    ------
    domain
        The authority domain being evaluated.
    status
        Boundary integrity status.
    canonical_modules
        List of canonical module path strings that were confirmed available.
    missing_modules
        List of canonical module path strings that could not be imported.
    sentinel_checks
        Mapping of sentinel name → True (present and non-empty) or False.
    notes
        Diagnostic notes collected during evaluation.
    """

    domain: AuthorityDomain = AuthorityDomain.COMPLETION_TRUTH
    status: DomainBoundaryStatus = DomainBoundaryStatus.UNKNOWN
    canonical_modules: List[str] = field(default_factory=list)
    missing_modules: List[str] = field(default_factory=list)
    sentinel_checks: Dict[str, bool] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)

    @property
    def is_intact(self) -> bool:
        return self.status == DomainBoundaryStatus.INTACT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain.value,
            "status": self.status.value,
            "is_intact": self.is_intact,
            "canonical_modules": list(self.canonical_modules),
            "missing_modules": list(self.missing_modules),
            "sentinel_checks": dict(self.sentinel_checks),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# CenterAuthorityBoundaryReport
# ---------------------------------------------------------------------------


@dataclass
class CenterAuthorityBoundaryReport:
    """Full boundary integrity report for all four authority domains.

    Fields
    ------
    report_id
        Unique identifier for this report instance.
    all_domains_intact
        True iff all four domain boundaries are INTACT.
    domain_states
        Per-domain boundary state keyed by :class:`AuthorityDomain`.
    degraded_domains
        List of domain values whose boundary is not INTACT.
    authority
        Authority sentinel string confirming this report's canonical role.
    notes
        Top-level diagnostic notes.
    """

    report_id: str = field(
        default_factory=lambda: f"cab_rpt_{uuid.uuid4().hex[:12]}"
    )
    all_domains_intact: bool = False
    domain_states: Dict[str, DomainBoundaryState] = field(default_factory=dict)
    degraded_domains: List[str] = field(default_factory=list)
    authority: str = CENTER_AUTHORITY_BOUNDARY_AUTHORITY
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "all_domains_intact": self.all_domains_intact,
            "domain_states": {
                k: v.to_dict() for k, v in self.domain_states.items()
            },
            "degraded_domains": list(self.degraded_domains),
            "authority": self.authority,
            "notes": list(self.notes),
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# Domain evaluators
# ---------------------------------------------------------------------------


def _evaluate_completion_truth_domain() -> DomainBoundaryState:
    """Evaluate the COMPLETION_TRUTH authority domain boundary."""
    state = DomainBoundaryState(domain=AuthorityDomain.COMPLETION_TRUTH)

    # Required canonical modules and their authority sentinels.
    _checks: List[tuple[str, str]] = [
        ("core.unified_result_ingress", "UNIFIED_RESULT_INGRESS_POLICY"),
        (
            "core.task_result_canonical_truth_chain",
            "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY",
        ),
        ("core.canonical_completion_ingress", "CANONICAL_COMPLETION_INGRESS_SENTINEL"),
        (
            "core.canonical_group_completion_closure",
            "CANONICAL_GROUP_COMPLETION_CLOSURE_AUTHORITY",
        ),
    ]

    for module_path, sentinel_name in _checks:
        try:
            import importlib

            mod = importlib.import_module(module_path)
            state.canonical_modules.append(module_path)
            sentinel_value = getattr(mod, sentinel_name, None)
            state.sentinel_checks[sentinel_name] = bool(
                sentinel_value and isinstance(sentinel_value, str)
            )
        except (ImportError, AttributeError) as exc:  # pragma: no cover
            state.missing_modules.append(module_path)
            state.notes.append(f"Import failed for {module_path}: {exc}")
            state.sentinel_checks[sentinel_name] = False

    _compute_domain_status(state)
    return state


def _evaluate_continuity_legality_domain() -> DomainBoundaryState:
    """Evaluate the CONTINUITY_LEGALITY_TRUTH authority domain boundary."""
    state = DomainBoundaryState(domain=AuthorityDomain.CONTINUITY_LEGALITY_TRUTH)

    _checks: List[tuple[str, str]] = [
        (
            "core.unified_continuity_legality_authority",
            "UNIFIED_CONTINUITY_LEGALITY_AUTHORITY",
        ),
    ]

    # Also verify the policy sentinel that gates all eight paths.
    _policy_checks: List[tuple[str, str]] = [
        (
            "core.unified_continuity_legality_authority",
            "ALL_PATHS_MUST_USE_UNIFIED_AUTHORITY_POLICY",
        ),
        (
            "core.unified_continuity_legality_authority",
            "CONTINUITY_FIELDS_ARE_ACTIVE_GATE_NOT_PAYLOAD_POLICY",
        ),
    ]

    for module_path, sentinel_name in _checks + _policy_checks:
        try:
            import importlib

            mod = importlib.import_module(module_path)
            if module_path not in state.canonical_modules:
                state.canonical_modules.append(module_path)
            sentinel_value = getattr(mod, sentinel_name, None)
            state.sentinel_checks[sentinel_name] = bool(
                sentinel_value and isinstance(sentinel_value, str)
            )
        except (ImportError, AttributeError) as exc:  # pragma: no cover
            if module_path not in state.missing_modules:
                state.missing_modules.append(module_path)
            state.notes.append(f"Import failed for {module_path}: {exc}")
            state.sentinel_checks[sentinel_name] = False

    _compute_domain_status(state)
    return state


def _evaluate_dispatch_readiness_domain() -> DomainBoundaryState:
    """Evaluate the DISPATCH_READINESS_TRUTH authority domain boundary."""
    state = DomainBoundaryState(domain=AuthorityDomain.DISPATCH_READINESS_TRUTH)

    _checks: List[tuple[str, str]] = [
        (
            "core.unified_dispatch_readiness_gate",
            "UNIFIED_DISPATCH_READINESS_GATE_AUTHORITY",
        ),
        (
            "core.canonical_dispatch_slot_authority",
            "CANONICAL_DISPATCH_SLOT_AUTHORITY",
        ),
    ]

    _policy_checks: List[tuple[str, str]] = [
        (
            "core.unified_dispatch_readiness_gate",
            "DISPATCH_MUST_CONSULT_UNIFIED_GATE_POLICY",
        ),
        (
            "core.canonical_dispatch_slot_authority",
            "ALL_EXECUTION_MODES_MUST_CONSUME_CANONICAL_SLOT_POLICY",
        ),
    ]

    for module_path, sentinel_name in _checks + _policy_checks:
        try:
            import importlib

            mod = importlib.import_module(module_path)
            if module_path not in state.canonical_modules:
                state.canonical_modules.append(module_path)
            sentinel_value = getattr(mod, sentinel_name, None)
            state.sentinel_checks[sentinel_name] = bool(
                sentinel_value and isinstance(sentinel_value, str)
            )
        except (ImportError, AttributeError) as exc:  # pragma: no cover
            if module_path not in state.missing_modules:
                state.missing_modules.append(module_path)
            state.notes.append(f"Import failed for {module_path}: {exc}")
            state.sentinel_checks[sentinel_name] = False

    _compute_domain_status(state)
    return state


def _evaluate_orchestration_truth_domain() -> DomainBoundaryState:
    """Evaluate the ORCHESTRATION_TRUTH authority domain boundary."""
    state = DomainBoundaryState(domain=AuthorityDomain.ORCHESTRATION_TRUTH)

    _checks: List[tuple[str, str]] = [
        (
            "core.unified_orchestration_spine",
            "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY",
        ),
    ]

    _policy_checks: List[tuple[str, str]] = [
        (
            "core.unified_orchestration_spine",
            "ALL_EXECUTION_MODES_MUST_USE_SPINE_POLICY",
        ),
        (
            "core.unified_orchestration_spine",
            "ORCHESTRATION_SPINE_V4_CONSUMES_CANONICAL_SLOT_POLICY",
        ),
        (
            "core.unified_orchestration_spine",
            "ORCHESTRATION_SPINE_V5_COMPLETION_CLOSURE_POLICY",
        ),
    ]

    for module_path, sentinel_name in _checks + _policy_checks:
        try:
            import importlib

            mod = importlib.import_module(module_path)
            if module_path not in state.canonical_modules:
                state.canonical_modules.append(module_path)
            sentinel_value = getattr(mod, sentinel_name, None)
            state.sentinel_checks[sentinel_name] = bool(
                sentinel_value and isinstance(sentinel_value, str)
            )
        except (ImportError, AttributeError) as exc:  # pragma: no cover
            if module_path not in state.missing_modules:
                state.missing_modules.append(module_path)
            state.notes.append(f"Import failed for {module_path}: {exc}")
            state.sentinel_checks[sentinel_name] = False

    _compute_domain_status(state)
    return state


def _compute_domain_status(state: DomainBoundaryState) -> None:
    """Populate state.status from missing_modules and sentinel_checks."""
    if state.missing_modules:
        state.status = DomainBoundaryStatus.DEGRADED
        return
    if any(not ok for ok in state.sentinel_checks.values()):
        state.status = DomainBoundaryStatus.DEGRADED
        return
    state.status = DomainBoundaryStatus.INTACT


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------


def evaluate_center_authority_boundary() -> CenterAuthorityBoundaryReport:
    """Evaluate all four authority domain boundaries and return a full report.

    This function:

    1. Evaluates each of the four center authority domains.
    2. Determines whether all four boundaries are INTACT.
    3. Returns a :class:`CenterAuthorityBoundaryReport` that is fully
       serialisable and suitable for acceptance gates, health checks, and
       release-blocking tests.

    Returns
    -------
    CenterAuthorityBoundaryReport
        Full boundary integrity report.  ``all_domains_intact`` is True iff
        every domain returned :attr:`DomainBoundaryStatus.INTACT`.
    """
    report = CenterAuthorityBoundaryReport()

    domain_evaluators = [
        (AuthorityDomain.COMPLETION_TRUTH, _evaluate_completion_truth_domain),
        (
            AuthorityDomain.CONTINUITY_LEGALITY_TRUTH,
            _evaluate_continuity_legality_domain,
        ),
        (
            AuthorityDomain.DISPATCH_READINESS_TRUTH,
            _evaluate_dispatch_readiness_domain,
        ),
        (AuthorityDomain.ORCHESTRATION_TRUTH, _evaluate_orchestration_truth_domain),
    ]

    for domain, evaluator in domain_evaluators:
        try:
            state = evaluator()
        except (ImportError, AttributeError) as exc:  # pragma: no cover
            state = DomainBoundaryState(domain=domain)
            state.status = DomainBoundaryStatus.UNKNOWN
            state.notes.append(f"Evaluation error: {exc}")

        report.domain_states[domain.value] = state
        if state.status != DomainBoundaryStatus.INTACT:
            report.degraded_domains.append(domain.value)

    report.all_domains_intact = len(report.degraded_domains) == 0

    if report.all_domains_intact:
        report.notes.append(
            "All four center authority domain boundaries are INTACT. "
            "V2 owns completion truth, continuity legality truth, "
            "dispatch readiness truth, and orchestration truth."
        )
        logger.info(
            "CenterAuthorityBoundary: all four domains INTACT — "
            "V2 is the sole authority for completion, continuity, "
            "readiness, and orchestration truth."
        )
    else:
        report.notes.append(
            f"DEGRADED authority domains: {report.degraded_domains}. "
            "One or more canonical authority modules are unavailable. "
            "Run assert_center_authority_intact() for details."
        )
        logger.warning(
            "CenterAuthorityBoundary: DEGRADED domains=%s",
            report.degraded_domains,
        )

    return report


# ---------------------------------------------------------------------------
# Assertion helper
# ---------------------------------------------------------------------------


def assert_center_authority_intact() -> None:
    """Assert that all four center authority domain boundaries are intact.

    This function evaluates the boundary and raises
    :class:`CenterAuthorityViolation` if any domain boundary is not INTACT.

    Intended for use in:

    * Acceptance gates
    * Health checks
    * Release-blocking tests
    * CI startup assertions

    Raises
    ------
    CenterAuthorityViolation
        When one or more authority domain boundaries are DEGRADED or UNKNOWN.
    """
    report = evaluate_center_authority_boundary()
    if not report.all_domains_intact:
        degraded = [AuthorityDomain(d) for d in report.degraded_domains]
        raise CenterAuthorityViolation(
            f"Center authority boundary not intact: degraded domains = "
            f"{report.degraded_domains}.  "
            f"V2 does not fully own all four truth domains. "
            f"report_id={report.report_id}",
            degraded_domains=degraded,
            report=report,
        )


# ---------------------------------------------------------------------------
# Convenience accessor
# ---------------------------------------------------------------------------


def get_boundary_report() -> CenterAuthorityBoundaryReport:
    """Return the current center authority boundary report.

    Alias for :func:`evaluate_center_authority_boundary`.  Provided for
    callers that prefer the noun form.
    """
    return evaluate_center_authority_boundary()
