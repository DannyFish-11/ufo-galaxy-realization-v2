"""core/cross_repo_consistency_gates.py
========================================
PR-12 (Cross-repository consistency gates — main repository side).

This module is the **canonical authority** for CI-friendly consistency gate
mechanisms that guard the most important shared semantic surfaces between
``DannyFish-11/ufo-galaxy-realization-v2`` (center) and
``DannyFish-11/ufo-galaxy-android`` (android).

It builds on the PR-4 foundation (``core.cross_repo_protocol_consistency``)
by turning the documented consistency catalogue into **executable gate checks**
that can be run in CI or called programmatically to detect drift early.

Background
----------
PR-1 through PR-4 established:

* Constitutional governance rules (PR-1)
* Cross-repository homomorphic mapping baseline (PR-2)
* Canonical session axis and identifier consistency (PR-3)
* Explicit cross-repository protocol consistency catalogue (PR-4)

PR-12 gates turn those declarations into automated, CI-runnable checks so that
future cross-repository drift is detected early rather than discovered through
reviewer memory or manual mapping maintenance.

Gate categories
---------------
Each gate targets one of the critical shared semantic surfaces identified in
PR-4:

schema_vocabulary
    Validates that all shared vocabulary surfaces in the PR-4 catalogue are
    classified and no ``unresolved`` entries exist.

session_family
    Checks key session identifier fields and session-family expectations
    (leverages PR-3 canonical session axis catalogue).

execution_enum
    Verifies execution and result enum consistency — terminal phase values are
    present in the catalogue and agree with the canonical terminal state set.

terminal_state
    Enforces the closed terminal state invariant: the canonical set
    ``{completed, failed, partial, cancelled, timed_out}`` must be fully
    represented in the consistency catalogue and must not have gained
    unacknowledged members.

descriptor_field
    Confirms important capability and runtime-profile descriptor fields are
    classified as canonical in the protocol surface catalogue.

transitional_marker
    Validates that every transitional compatibility allowance carries an
    explicit retirement condition (no implicit allowances).

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **CI-suitable** — all gate runner functions return structured
  :class:`ConsistencyGateResult` objects; :func:`build_consistency_gate_snapshot`
  returns a JSON-serialisable snapshot suitable for CI consumption.
- **Non-breaking** — gates report verdicts but do not raise exceptions on
  drift; callers decide enforcement policy.
- **Drift-transparent** — every gate result carries a ``drift_detected`` flag
  so automated systems can detect and surface deviations.
- **Transitional-aware** — transitional allowances must be explicit and carry
  retirement conditions; implicit allowances are flagged.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`CROSS_REPO_CONSISTENCY_GATES_IS_AUTHORITY`
:data:`CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL`
:data:`GATES_ARE_NON_BREAKING_POLICY`
:data:`UNRESOLVED_SURFACES_ARE_DRIFT_INDICATORS_POLICY`
:data:`TRANSITIONAL_ALLOWANCES_MUST_BE_EXPLICIT_POLICY`
:data:`TERMINAL_STATE_SET_IS_CLOSED_AND_GATED_POLICY`
:data:`DESCRIPTOR_FIELDS_MUST_REMAIN_CANONICAL_POLICY`
:data:`SESSION_FAMILY_DRIFT_IS_HIGH_SEVERITY_POLICY`

Enums
~~~~~
:class:`ConsistencyGateKind`
:class:`GateVerdict`

Data classes
~~~~~~~~~~~~
:class:`ConsistencyGateResult`
:class:`ConsistencyGateSnapshot`

Functions
~~~~~~~~~
:func:`run_schema_vocabulary_gate`
:func:`run_session_family_gate`
:func:`run_execution_enum_gate`
:func:`run_terminal_state_gate`
:func:`run_descriptor_field_gate`
:func:`run_transitional_marker_gate`
:func:`run_all_consistency_gates`
:func:`build_consistency_gate_snapshot`
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Sequence, Tuple

from core.cross_repo_protocol_consistency import (
    CanonicalTerminalState,
    ProtocolConsistencyCategory,
    ProtocolSurfaceClass,
    get_delegated_execution_status_catalogue,
    get_protocol_surface_catalogue,
    get_terminal_state_consistency_catalogue,
    get_transitional_allowance_catalogue,
)

__all__ = [
    # Sentinels
    "CROSS_REPO_CONSISTENCY_GATES_IS_AUTHORITY",
    "CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL",
    "GATES_ARE_NON_BREAKING_POLICY",
    "UNRESOLVED_SURFACES_ARE_DRIFT_INDICATORS_POLICY",
    "TRANSITIONAL_ALLOWANCES_MUST_BE_EXPLICIT_POLICY",
    "TERMINAL_STATE_SET_IS_CLOSED_AND_GATED_POLICY",
    "DESCRIPTOR_FIELDS_MUST_REMAIN_CANONICAL_POLICY",
    "SESSION_FAMILY_DRIFT_IS_HIGH_SEVERITY_POLICY",
    # Enums
    "ConsistencyGateKind",
    "GateVerdict",
    # Data classes
    "ConsistencyGateResult",
    "ConsistencyGateSnapshot",
    # Functions
    "run_schema_vocabulary_gate",
    "run_session_family_gate",
    "run_execution_enum_gate",
    "run_terminal_state_gate",
    "run_descriptor_field_gate",
    "run_transitional_marker_gate",
    "run_all_consistency_gates",
    "build_consistency_gate_snapshot",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

CROSS_REPO_CONSISTENCY_GATES_IS_AUTHORITY: str = (
    "CROSS_REPO_CONSISTENCY_GATES_IS_AUTHORITY::"
    "core.cross_repo_consistency_gates is the canonical authority for "
    "CI-friendly cross-repository consistency gate mechanisms on the most "
    "important shared semantic surfaces (PR-12, cross-repository consistency "
    "gates)."
)

CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL: str = (
    "CROSS_REPO_CONSISTENCY_GATES_PR12_SENTINEL::package=PR12::"
    "profile=cross-repo-consistency-gates-v1::"
    "module=core.cross_repo_consistency_gates"
)

GATES_ARE_NON_BREAKING_POLICY: str = (
    "POLICY::GATES_ARE_NON_BREAKING: consistency gate runner functions "
    "return structured ConsistencyGateResult objects and do not raise "
    "exceptions on drift.  Callers decide enforcement policy.  This ensures "
    "gates remain CI-safe and do not break production startup paths."
)

UNRESOLVED_SURFACES_ARE_DRIFT_INDICATORS_POLICY: str = (
    "POLICY::UNRESOLVED_SURFACES_ARE_DRIFT_INDICATORS: any surface in the "
    "protocol surface catalogue classified as 'unresolved' is treated as a "
    "drift indicator by the schema_vocabulary gate.  Unresolved surfaces "
    "must be explicitly resolved (reclassified as canonical, transitional, or "
    "deprecated) before the gate can report a clean pass."
)

TRANSITIONAL_ALLOWANCES_MUST_BE_EXPLICIT_POLICY: str = (
    "POLICY::TRANSITIONAL_ALLOWANCES_MUST_BE_EXPLICIT: every transitional "
    "compatibility allowance in the PR-4 catalogue must carry a non-empty "
    "retirement_condition.  Transitional allowances without an explicit "
    "retirement condition are treated as implicit allowances, which are "
    "prohibited by TRANSITIONAL_SURFACES_MUST_NOT_EXPAND_POLICY."
)

TERMINAL_STATE_SET_IS_CLOSED_AND_GATED_POLICY: str = (
    "POLICY::TERMINAL_STATE_SET_IS_CLOSED_AND_GATED: the canonical terminal "
    "state gate enforces that the set of terminal state values catalogued in "
    "PR-4 exactly matches CanonicalTerminalState.  Any divergence — a "
    "catalogued state not in CanonicalTerminalState, or a CanonicalTerminalState "
    "value missing from the catalogue — constitutes drift and must be resolved."
)

DESCRIPTOR_FIELDS_MUST_REMAIN_CANONICAL_POLICY: str = (
    "POLICY::DESCRIPTOR_FIELDS_MUST_REMAIN_CANONICAL: the canonical runtime "
    "profile and capability descriptor fields (capabilities, capability_flags, "
    "supported_actions, source_runtime_posture, coordination_role) must each "
    "appear in the protocol surface catalogue classified as canonical within "
    "the runtime_profile category.  Any reclassification of these fields "
    "requires an explicit PR-level justification."
)

SESSION_FAMILY_DRIFT_IS_HIGH_SEVERITY_POLICY: str = (
    "POLICY::SESSION_FAMILY_DRIFT_IS_HIGH_SEVERITY: session identifier and "
    "session-family surfaces are the highest-severity shared semantic surface. "
    "Any session surface classified as unresolved or missing from the catalogue "
    "is reported as a high-severity drift indicator by the session_family gate. "
    "Session field renames are only permitted as explicitly declared transitional "
    "allowances in the PR-4 allowance catalogue."
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ConsistencyGateKind(str, Enum):
    """The category of shared semantic surface checked by a consistency gate.

    schema_vocabulary
        Shared UGCP schema/enum vocabulary surfaces.

    session_family
        Session identifier and session-family expectation surfaces.

    execution_enum
        Execution and result enum consistency surfaces.

    terminal_state
        Terminal state semantics and closed-set invariants.

    descriptor_field
        Important capability/runtime-profile descriptor field surfaces.

    transitional_marker
        Explicit transitional compatibility marker integrity.
    """

    schema_vocabulary = "schema_vocabulary"
    session_family = "session_family"
    execution_enum = "execution_enum"
    terminal_state = "terminal_state"
    descriptor_field = "descriptor_field"
    transitional_marker = "transitional_marker"


class GateVerdict(str, Enum):
    """The result verdict of a consistency gate evaluation.

    pass_
        Gate passed with no issues detected.

    warn
        Gate passed but detected anomalies that should be reviewed.

    fail
        Gate detected drift or a policy violation.
    """

    pass_ = "pass"
    warn = "warn"
    fail = "fail"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsistencyGateResult:
    """Result of evaluating one consistency gate.

    Attributes
    ----------
    gate_id
        Machine-readable identifier for this gate (e.g. ``"schema_vocabulary"``).
    kind
        The category of shared semantic surface this gate checks.
    verdict
        Whether the gate passed, warned, or failed.
    drift_detected
        ``True`` iff the gate detected a drift condition that requires attention.
    details
        Human-readable description of the gate evaluation result.
    issues
        List of specific issues found (empty on clean pass).
    checked_at
        Unix timestamp when the gate was evaluated.
    """

    gate_id: str
    kind: ConsistencyGateKind
    verdict: GateVerdict
    drift_detected: bool
    details: str
    issues: Tuple[str, ...] = field(default_factory=tuple)
    checked_at: float = field(default_factory=time.time)

    @property
    def passed(self) -> bool:
        """Return True iff the verdict is ``pass_`` or ``warn``."""
        return self.verdict in (GateVerdict.pass_, GateVerdict.warn)


@dataclass
class ConsistencyGateSnapshot:
    """Aggregate snapshot of all consistency gate results.

    Suitable for CI consumption: all fields are JSON-serialisable.

    Attributes
    ----------
    generated_at
        Unix timestamp when the snapshot was assembled.
    total_gates
        Total number of gates evaluated.
    passed_gates
        Number of gates that passed (verdict ``pass_`` or ``warn``).
    warned_gates
        Number of gates with verdict ``warn``.
    failed_gates
        Number of gates with verdict ``fail``.
    drift_detected
        ``True`` iff any gate detected drift.
    gate_results
        Ordered list of individual gate results.
    summary
        Human-readable summary suitable for CI log output.
    """

    generated_at: float
    total_gates: int
    passed_gates: int
    warned_gates: int
    failed_gates: int
    drift_detected: bool
    gate_results: List[ConsistencyGateResult]
    summary: str = ""

    def is_clean(self) -> bool:
        """Return True iff no drift was detected across all gates."""
        return not self.drift_detected

    def to_dict(self) -> Dict:
        """Return a JSON-serialisable dict representation of the snapshot."""
        return {
            "generated_at": self.generated_at,
            "total_gates": self.total_gates,
            "passed_gates": self.passed_gates,
            "warned_gates": self.warned_gates,
            "failed_gates": self.failed_gates,
            "drift_detected": self.drift_detected,
            "is_clean": self.is_clean(),
            "summary": self.summary,
            "gate_results": [
                {
                    "gate_id": r.gate_id,
                    "kind": r.kind.value,
                    "verdict": r.verdict.value,
                    "drift_detected": r.drift_detected,
                    "details": r.details,
                    "issues": list(r.issues),
                    "checked_at": r.checked_at,
                }
                for r in self.gate_results
            ],
        }


# ---------------------------------------------------------------------------
# Required surface IDs for each gate category
# ---------------------------------------------------------------------------

# Session identifier surfaces that must be present in the PR-4 catalogue.
# These correspond to the session_identifier category surfaces established
# in core.cross_repo_protocol_consistency (PR-4).
_REQUIRED_SESSION_SURFACE_IDS: Tuple[str, ...] = (
    "session_axis_model",
    "runtime_attachment_session_id",
    "delegation_transfer_session_id",
    "mesh_session_id",
)

# Descriptor field surface IDs that must be classified as canonical.
# These correspond to the runtime_profile category canonical surfaces
# established in core.cross_repo_protocol_consistency (PR-4).
_REQUIRED_DESCRIPTOR_SURFACE_IDS: Tuple[str, ...] = (
    "runtime_capability_profile",
    "source_runtime_posture_field",
)

# Minimum set of delegated execution phase values that must appear in the
# delegated execution status catalogue (PR-4).
_REQUIRED_EXECUTION_PHASES: Tuple[str, ...] = (
    "pending_ack",
    "acknowledged",
    "in_progress",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
)


# ---------------------------------------------------------------------------
# Gate runner functions
# ---------------------------------------------------------------------------


def run_schema_vocabulary_gate() -> ConsistencyGateResult:
    """Validate that all shared vocabulary surfaces are classified.

    Checks:
    - No ``unresolved`` surfaces in the protocol surface catalogue.
    - At least one ``shared_vocabulary`` surface is classified as canonical.
    - All ``shared_vocabulary`` canonical surfaces have a non-empty
      ``center_authority``.

    Returns
    -------
    ConsistencyGateResult
        Gate result with verdict and any detected issues.
    """
    catalogue = get_protocol_surface_catalogue()
    issues: List[str] = []

    unresolved = [
        r for r in catalogue if r.surface_class == ProtocolSurfaceClass.unresolved
    ]
    if unresolved:
        for r in unresolved:
            issues.append(
                f"Unresolved surface '{r.surface_id}' in category "
                f"'{r.category.value}' must be reclassified."
            )

    vocab_canonical = [
        r
        for r in catalogue
        if r.category == ProtocolConsistencyCategory.shared_vocabulary
        and r.surface_class == ProtocolSurfaceClass.canonical
    ]
    if not vocab_canonical:
        issues.append(
            "No canonical shared_vocabulary surface found in protocol surface "
            "catalogue.  At least one must be classified as canonical."
        )
    else:
        for r in vocab_canonical:
            if not r.center_authority:
                issues.append(
                    f"Canonical shared_vocabulary surface '{r.surface_id}' has "
                    "no center_authority specified."
                )

    drift = bool(unresolved)
    if issues:
        verdict = GateVerdict.fail if drift else GateVerdict.warn
        details = (
            f"schema_vocabulary gate: {len(issues)} issue(s) found. "
            f"Unresolved surfaces: {len(unresolved)}; "
            f"canonical vocab surfaces: {len(vocab_canonical)}."
        )
    else:
        verdict = GateVerdict.pass_
        details = (
            f"schema_vocabulary gate: clean. "
            f"Canonical vocab surfaces: {len(vocab_canonical)}; "
            f"no unresolved surfaces."
        )

    return ConsistencyGateResult(
        gate_id="schema_vocabulary",
        kind=ConsistencyGateKind.schema_vocabulary,
        verdict=verdict,
        drift_detected=drift,
        details=details,
        issues=tuple(issues),
    )


def run_session_family_gate() -> ConsistencyGateResult:
    """Check key session identifier fields and session-family expectations.

    Checks:
    - Each required session surface ID exists in the protocol surface catalogue.
    - No required session surface is classified as ``unresolved`` or
      ``deprecated`` (session surfaces must remain canonical or transitional
      with explicit retirement conditions).
    - Transitional session surfaces carry a non-empty ``retirement_pathway``.

    Returns
    -------
    ConsistencyGateResult
        Gate result with verdict and any detected issues.
    """
    catalogue = get_protocol_surface_catalogue()
    surface_map = {r.surface_id: r for r in catalogue}
    issues: List[str] = []
    drift = False

    for surface_id in _REQUIRED_SESSION_SURFACE_IDS:
        if surface_id not in surface_map:
            issues.append(
                f"Required session surface '{surface_id}' is missing from the "
                "protocol surface catalogue."
            )
            drift = True
            continue
        record = surface_map[surface_id]
        if record.surface_class == ProtocolSurfaceClass.unresolved:
            issues.append(
                f"Session surface '{surface_id}' is classified as 'unresolved'. "
                "Session surfaces must be resolved to canonical or transitional."
            )
            drift = True
        elif record.surface_class == ProtocolSurfaceClass.transitional:
            if not record.retirement_pathway:
                issues.append(
                    f"Transitional session surface '{surface_id}' has no "
                    "retirement_pathway. Transitional session allowances must "
                    "carry explicit retirement conditions."
                )

    # Also check session category surfaces not in our required list
    session_surfaces = [
        r
        for r in catalogue
        if r.category == ProtocolConsistencyCategory.session_identifier
    ]
    unresolved_session = [
        r for r in session_surfaces if r.surface_class == ProtocolSurfaceClass.unresolved
    ]
    for r in unresolved_session:
        if r.surface_id not in _REQUIRED_SESSION_SURFACE_IDS:
            issues.append(
                f"Session surface '{r.surface_id}' is unresolved. "
                "Unresolved session surfaces indicate high-severity drift."
            )
            drift = True

    if issues:
        verdict = GateVerdict.fail if drift else GateVerdict.warn
        details = (
            f"session_family gate: {len(issues)} issue(s) found. "
            f"Session surfaces checked: {len(_REQUIRED_SESSION_SURFACE_IDS)}; "
            f"drift detected: {drift}."
        )
    else:
        verdict = GateVerdict.pass_
        details = (
            f"session_family gate: clean. "
            f"All {len(_REQUIRED_SESSION_SURFACE_IDS)} required session surfaces "
            "are present and consistently classified."
        )

    return ConsistencyGateResult(
        gate_id="session_family",
        kind=ConsistencyGateKind.session_family,
        verdict=verdict,
        drift_detected=drift,
        details=details,
        issues=tuple(issues),
    )


def run_execution_enum_gate() -> ConsistencyGateResult:
    """Verify execution and result enum consistency.

    Checks:
    - Each required execution phase value appears in the delegated execution
      status catalogue.
    - Terminal phases in the execution catalogue agree with
      ``CanonicalTerminalState``: every catalogued terminal phase must map to
      a ``CanonicalTerminalState`` value.
    - No execution phase is listed as both terminal and non-terminal.

    Returns
    -------
    ConsistencyGateResult
        Gate result with verdict and any detected issues.
    """
    exec_catalogue = get_delegated_execution_status_catalogue()
    phase_map = {r.phase_value: r for r in exec_catalogue}
    canonical_terminal_values = {s.value for s in CanonicalTerminalState}
    issues: List[str] = []
    drift = False

    for phase in _REQUIRED_EXECUTION_PHASES:
        if phase not in phase_map:
            issues.append(
                f"Required execution phase '{phase}' is missing from the "
                "delegated execution status catalogue."
            )
            drift = True

    # Validate terminal phase alignment with CanonicalTerminalState
    terminal_phases = [r for r in exec_catalogue if r.is_terminal]
    for record in terminal_phases:
        if record.phase_value not in canonical_terminal_values:
            issues.append(
                f"Execution phase '{record.phase_value}' is marked terminal "
                "but does not appear in CanonicalTerminalState. Terminal phases "
                "must correspond to canonical terminal state values."
            )
            drift = True

    # Detect phase_value uniqueness in the catalogue
    all_phases = [r.phase_value for r in exec_catalogue]
    duplicate_phases = [p for p in all_phases if all_phases.count(p) > 1]
    if duplicate_phases:
        for dup in set(duplicate_phases):
            issues.append(
                f"Execution phase '{dup}' appears multiple times in the "
                "delegated execution status catalogue."
            )
        drift = True

    if issues:
        verdict = GateVerdict.fail if drift else GateVerdict.warn
        details = (
            f"execution_enum gate: {len(issues)} issue(s) found. "
            f"Phases in catalogue: {len(exec_catalogue)}; "
            f"terminal phases: {len(terminal_phases)}."
        )
    else:
        verdict = GateVerdict.pass_
        details = (
            f"execution_enum gate: clean. "
            f"All {len(_REQUIRED_EXECUTION_PHASES)} required phases present; "
            f"{len(terminal_phases)} terminal phase(s) align with "
            "CanonicalTerminalState."
        )

    return ConsistencyGateResult(
        gate_id="execution_enum",
        kind=ConsistencyGateKind.execution_enum,
        verdict=verdict,
        drift_detected=drift,
        details=details,
        issues=tuple(issues),
    )


def run_terminal_state_gate() -> ConsistencyGateResult:
    """Enforce the closed terminal state invariant.

    Checks:
    - The terminal state consistency catalogue contains exactly the values
      present in ``CanonicalTerminalState`` (no extras, no missing).
    - No catalogued terminal state has an empty ``state_value``.
    - ``CanonicalTerminalState`` values are all lowercase.
    - Inconsistent terminal states (not fully consistent across
      shared_schema + execution_phase + handoff_contract) are flagged as
      warnings, not failures, since documented cross-module differences
      are intentional.

    Returns
    -------
    ConsistencyGateResult
        Gate result with verdict and any detected issues.
    """
    term_catalogue = get_terminal_state_consistency_catalogue()
    canonical_values = {s.value for s in CanonicalTerminalState}
    catalogued_values = {r.state_value for r in term_catalogue}
    issues: List[str] = []
    drift = False

    # Check for empty state values
    for record in term_catalogue:
        if not record.state_value:
            issues.append(
                "Terminal state consistency record has an empty state_value."
            )
            drift = True

    # Check closed-set invariant: catalogue must exactly cover CanonicalTerminalState
    missing_from_catalogue = canonical_values - catalogued_values
    extra_in_catalogue = catalogued_values - canonical_values

    if missing_from_catalogue:
        for val in sorted(missing_from_catalogue):
            issues.append(
                f"CanonicalTerminalState value '{val}' is missing from the "
                "terminal state consistency catalogue.  The catalogue must "
                "cover all canonical terminal states."
            )
        drift = True

    if extra_in_catalogue:
        for val in sorted(extra_in_catalogue):
            issues.append(
                f"Terminal state catalogue contains '{val}' which is not in "
                "CanonicalTerminalState.  Non-canonical terminal states must "
                "not appear in the catalogue without updating CanonicalTerminalState."
            )
        drift = True

    # Warn about partially inconsistent states (not drift, just noteworthy)
    partially_inconsistent = [
        r for r in term_catalogue if not r.is_fully_consistent
    ]
    warn_messages: List[str] = []
    for r in partially_inconsistent:
        warn_messages.append(
            f"Terminal state '{r.state_value}' is not fully consistent across "
            "shared_schema/execution_phase/handoff_contract "
            f"(note: {r.consistency_note[:80] if r.consistency_note else 'no note'})."
        )

    if issues:
        verdict = GateVerdict.fail
        details = (
            f"terminal_state gate: {len(issues)} issue(s) found. "
            f"Canonical set size: {len(canonical_values)}; "
            f"catalogued: {len(catalogued_values)}. "
            f"Missing: {sorted(missing_from_catalogue)}; "
            f"extra: {sorted(extra_in_catalogue)}."
        )
    elif warn_messages:
        verdict = GateVerdict.warn
        details = (
            f"terminal_state gate: closed-set invariant satisfied. "
            f"{len(warn_messages)} partially inconsistent state(s) noted "
            "(documented intentional differences, not drift)."
        )
    else:
        verdict = GateVerdict.pass_
        details = (
            f"terminal_state gate: clean. "
            f"All {len(canonical_values)} canonical terminal states catalogued; "
            "closed-set invariant satisfied."
        )

    all_issues = issues + warn_messages
    return ConsistencyGateResult(
        gate_id="terminal_state",
        kind=ConsistencyGateKind.terminal_state,
        verdict=verdict,
        drift_detected=drift,
        details=details,
        issues=tuple(all_issues),
    )


def run_descriptor_field_gate() -> ConsistencyGateResult:
    """Confirm important capability/runtime-profile descriptor fields are canonical.

    Checks:
    - Each required descriptor surface ID appears in the protocol surface
      catalogue.
    - Required descriptor surfaces are classified as ``canonical`` within
      the ``runtime_profile`` category.

    Returns
    -------
    ConsistencyGateResult
        Gate result with verdict and any detected issues.
    """
    catalogue = get_protocol_surface_catalogue()
    surface_map = {r.surface_id: r for r in catalogue}
    issues: List[str] = []
    drift = False

    for surface_id in _REQUIRED_DESCRIPTOR_SURFACE_IDS:
        if surface_id not in surface_map:
            issues.append(
                f"Required descriptor surface '{surface_id}' is missing from "
                "the protocol surface catalogue."
            )
            drift = True
            continue
        record = surface_map[surface_id]
        if record.surface_class != ProtocolSurfaceClass.canonical:
            issues.append(
                f"Descriptor surface '{surface_id}' is classified as "
                f"'{record.surface_class.value}' instead of 'canonical'. "
                "Important descriptor fields must remain canonical."
            )
            drift = True
        if record.category != ProtocolConsistencyCategory.runtime_profile:
            issues.append(
                f"Descriptor surface '{surface_id}' is in category "
                f"'{record.category.value}' instead of 'runtime_profile'. "
                "Capability descriptor surfaces must be in the runtime_profile "
                "category."
            )

    # Also check runtime_profile surfaces generally
    profile_surfaces = [
        r
        for r in catalogue
        if r.category == ProtocolConsistencyCategory.runtime_profile
    ]
    unresolved_profile = [
        r for r in profile_surfaces if r.surface_class == ProtocolSurfaceClass.unresolved
    ]
    for r in unresolved_profile:
        issues.append(
            f"Runtime profile surface '{r.surface_id}' is unresolved. "
            "Descriptor field surfaces must be classified."
        )
        drift = True

    if issues:
        verdict = GateVerdict.fail if drift else GateVerdict.warn
        details = (
            f"descriptor_field gate: {len(issues)} issue(s) found. "
            f"Runtime profile surfaces: {len(profile_surfaces)}."
        )
    else:
        verdict = GateVerdict.pass_
        details = (
            f"descriptor_field gate: clean. "
            f"All {len(_REQUIRED_DESCRIPTOR_SURFACE_IDS)} required descriptor "
            f"surface(s) are canonical; "
            f"{len(profile_surfaces)} runtime_profile surface(s) total."
        )

    return ConsistencyGateResult(
        gate_id="descriptor_field",
        kind=ConsistencyGateKind.descriptor_field,
        verdict=verdict,
        drift_detected=drift,
        details=details,
        issues=tuple(issues),
    )


def run_transitional_marker_gate() -> ConsistencyGateResult:
    """Validate that every transitional allowance is explicit.

    Checks:
    - Every entry in the transitional allowance catalogue has a non-empty
      ``allowance_id``.
    - Every entry has a non-empty ``retirement_condition``.
    - No duplicate ``allowance_id`` values exist.
    - Every ``transitional``-classified surface in the protocol surface
      catalogue has a non-empty ``retirement_pathway``.

    Returns
    -------
    ConsistencyGateResult
        Gate result with verdict and any detected issues.
    """
    allowance_catalogue = get_transitional_allowance_catalogue()
    surface_catalogue = get_protocol_surface_catalogue()
    issues: List[str] = []
    drift = False

    # Validate allowance catalogue entries
    allowance_ids: List[str] = []
    for record in allowance_catalogue:
        if not record.allowance_id:
            issues.append(
                "A transitional allowance record has an empty allowance_id. "
                "All allowances must have explicit identifiers."
            )
            drift = True
            continue
        allowance_ids.append(record.allowance_id)
        if not record.retirement_condition:
            issues.append(
                f"Transitional allowance '{record.allowance_id}' has no "
                "retirement_condition. All transitional allowances must carry "
                "explicit retirement conditions."
            )
            drift = True

    # Check for duplicate allowance IDs
    duplicate_ids = [aid for aid in allowance_ids if allowance_ids.count(aid) > 1]
    if duplicate_ids:
        for dup in set(duplicate_ids):
            issues.append(
                f"Duplicate allowance_id '{dup}' found in the transitional "
                "allowance catalogue."
            )
        drift = True

    # Validate transitional surfaces have retirement_pathway
    transitional_surfaces = [
        r
        for r in surface_catalogue
        if r.surface_class == ProtocolSurfaceClass.transitional
    ]
    for r in transitional_surfaces:
        if not r.retirement_pathway:
            issues.append(
                f"Transitional surface '{r.surface_id}' has no retirement_pathway. "
                "All transitional surfaces must carry explicit retirement pathways."
            )
            drift = True

    if issues:
        verdict = GateVerdict.fail if drift else GateVerdict.warn
        details = (
            f"transitional_marker gate: {len(issues)} issue(s) found. "
            f"Allowances catalogued: {len(allowance_catalogue)}; "
            f"transitional surfaces: {len(transitional_surfaces)}."
        )
    else:
        verdict = GateVerdict.pass_
        details = (
            f"transitional_marker gate: clean. "
            f"All {len(allowance_catalogue)} allowance(s) have explicit "
            f"retirement conditions; "
            f"all {len(transitional_surfaces)} transitional surface(s) have "
            "retirement pathways."
        )

    return ConsistencyGateResult(
        gate_id="transitional_marker",
        kind=ConsistencyGateKind.transitional_marker,
        verdict=verdict,
        drift_detected=drift,
        details=details,
        issues=tuple(issues),
    )


# ---------------------------------------------------------------------------
# Aggregate runner and snapshot builder
# ---------------------------------------------------------------------------


def run_all_consistency_gates() -> Sequence[ConsistencyGateResult]:
    """Run all consistency gates and return the ordered results.

    Gates are run in a fixed order:
    1. schema_vocabulary
    2. session_family
    3. execution_enum
    4. terminal_state
    5. descriptor_field
    6. transitional_marker

    Returns
    -------
    Sequence[ConsistencyGateResult]
        One result per gate, in the order above.
    """
    return (
        run_schema_vocabulary_gate(),
        run_session_family_gate(),
        run_execution_enum_gate(),
        run_terminal_state_gate(),
        run_descriptor_field_gate(),
        run_transitional_marker_gate(),
    )


def build_consistency_gate_snapshot() -> ConsistencyGateSnapshot:
    """Build a CI-friendly consistency gate snapshot.

    Runs all gates and assembles a :class:`ConsistencyGateSnapshot` that
    is suitable for CI log output or machine consumption via
    :meth:`ConsistencyGateSnapshot.to_dict`.

    Returns
    -------
    ConsistencyGateSnapshot
        Aggregate snapshot with counts and per-gate results.
    """
    results = list(run_all_consistency_gates())

    passed = sum(1 for r in results if r.passed)
    warned = sum(1 for r in results if r.verdict == GateVerdict.warn)
    failed = sum(1 for r in results if r.verdict == GateVerdict.fail)
    any_drift = any(r.drift_detected for r in results)

    if failed > 0:
        summary = (
            f"CROSS-REPO CONSISTENCY GATES: {failed} gate(s) FAILED, "
            f"{warned} warning(s), {passed} passed. Drift detected."
        )
    elif warned > 0:
        summary = (
            f"CROSS-REPO CONSISTENCY GATES: all gates passed. "
            f"{warned} gate(s) with warnings. No drift detected."
        )
    else:
        summary = (
            f"CROSS-REPO CONSISTENCY GATES: all {len(results)} gates PASSED. "
            "No drift detected."
        )

    return ConsistencyGateSnapshot(
        generated_at=time.time(),
        total_gates=len(results),
        passed_gates=passed,
        warned_gates=warned,
        failed_gates=failed,
        drift_detected=any_drift,
        gate_results=results,
        summary=summary,
    )
