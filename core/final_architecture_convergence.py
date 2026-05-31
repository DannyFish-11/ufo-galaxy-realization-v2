#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/final_architecture_convergence.py
========================================
PR-11: Final Architecture Convergence — capstone convergence pass after
PR-6 through PR-10.

Purpose
-------
This module is the **terminal convergence declaration** for the Galaxy
architecture alignment sequence (PR-6 through PR-10).  It does not introduce
new runtime logic; it:

1. Consolidates residual edge inconsistencies that survived the earlier
   targeted structural corrections.
2. Strengthens final boundary clarity by naming each boundary in a single
   importable contract.
3. Removes remaining split-brain terminology by establishing one authoritative
   vocabulary for every architecture surface.
4. Refines existing validation surfaces (builds on
   ``core.terminal_architecture_audit_guards`` and
   ``core.canonical_layer_model``) without adding redundant mechanisms.
5. Leaves the repository in a reviewable terminal state.

Architecture surfaces covered
-------------------------------
* **Per-request hot path** — ``OpenClawd.process()`` →
  ``CommandRouter.route_envelope()``; every synchronous request; L1/L2/L3
  cognitive authority always engaged via ``UnifiedLLMRouter``.

* **Router-level cognitive authority** — L1 (``LLMRouteAuthority``),
  L2 (``LLMSupplyAuthority``), L3 (``CognitiveContextAuthority``) fused
  into ``UnifiedLLMRouter``; never a detached shadow stack.

* **Orchestration-session scope** — V4 (``unified_orchestration_spine``)
  governs multi-step sessions only; never the universal per-request gate.

* **Participant-generic interface vs. Android concrete** —
  ``core.participant_authority_interfaces`` defines the participant contract;
  Android modules are the first concrete implementation below that layer.

* **Startup / readiness / health / release integrity** — V6
  (``release_blocking_gate`` / ``center_authority_boundary``) is evaluated
  at CI time and system startup; it is never inserted into the synchronous
  request path.

Design principles
-----------------
* **Additive only** — does not modify any existing module.
* **Extends existing surfaces** — convergence checks delegate to
  ``core.canonical_layer_model``, ``core.terminal_architecture_audit_guards``,
  and ``core.participant_authority_interfaces`` rather than duplicating them.
* **Lightweight** — each check returns a list of
  :class:`ConvergenceFinding` dicts; callers decide whether to assert or log.
* **Terminal** — this module is the final authority declaration for the
  architecture alignment sequence; it supersedes any prior conflicting
  architectural statement.

Public API
----------
Authority sentinels::

    FINAL_ARCHITECTURE_CONVERGENCE_AUTHORITY
    FINAL_ARCHITECTURE_CONVERGENCE_PR11_SENTINEL

Boundary clarity sentinels::

    PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL
    ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL
    ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL
    PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL
    STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL

Convergence policy sentinels::

    CONVERGENCE_PASS_DOES_NOT_REDESIGN_RUNTIME_POLICY
    SINGLE_COHERENT_ARCHITECTURE_STORY_POLICY
    BOUNDARY_CLARITY_PRESERVED_POLICY

Data classes::

    ConvergenceFinding
    ConvergenceReport

Check functions::

    check_boundary_sentinel_completeness() -> List[ConvergenceFinding]
    check_terminal_guard_integrity() -> List[ConvergenceFinding]
    check_participant_layer_consistency() -> List[ConvergenceFinding]
    check_canonical_layer_model_reachable() -> List[ConvergenceFinding]
    run_final_convergence_checks() -> ConvergenceReport
"""

from __future__ import annotations

import dataclasses
import importlib
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.FinalArchitectureConvergence")

__all__ = [
    # Authority sentinels
    "FINAL_ARCHITECTURE_CONVERGENCE_AUTHORITY",
    "FINAL_ARCHITECTURE_CONVERGENCE_PR11_SENTINEL",
    # Boundary clarity sentinels
    "PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL",
    "ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL",
    "ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL",
    "PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL",
    "STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL",
    # Convergence policy sentinels
    "CONVERGENCE_PASS_DOES_NOT_REDESIGN_RUNTIME_POLICY",
    "SINGLE_COHERENT_ARCHITECTURE_STORY_POLICY",
    "BOUNDARY_CLARITY_PRESERVED_POLICY",
    # Data classes
    "ConvergenceFinding",
    "ConvergenceReport",
    # Check functions
    "check_boundary_sentinel_completeness",
    "check_terminal_guard_integrity",
    "check_participant_layer_consistency",
    "check_canonical_layer_model_reachable",
    "run_final_convergence_checks",
]

# ---------------------------------------------------------------------------
# Module authority sentinels
# ---------------------------------------------------------------------------

FINAL_ARCHITECTURE_CONVERGENCE_AUTHORITY: str = (
    "FINAL_ARCHITECTURE_CONVERGENCE_AUTHORITY::PR11: "
    "core.final_architecture_convergence is the terminal convergence "
    "declaration for the Galaxy architecture alignment sequence (PR-6 "
    "through PR-10).  It consolidates residual edge inconsistencies, "
    "strengthens final boundary clarity, and leaves the repository in a "
    "single coherent terminal architecture state.  This module does NOT "
    "redesign the runtime or create new architecture layers."
)

FINAL_ARCHITECTURE_CONVERGENCE_PR11_SENTINEL: str = (
    "PR::FINAL_ARCHITECTURE_CONVERGENCE_PR11: "
    "Introduced by PR-11 (Final architecture convergence — capstone "
    "convergence pass after PR-6 through PR-10).  Removing or contradicting "
    "this module re-opens the edge inconsistencies and naming drift that the "
    "PR-6 through PR-10 alignment sequence resolved."
)

# ---------------------------------------------------------------------------
# Boundary clarity sentinels — one per architecture surface
# ---------------------------------------------------------------------------

PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL: str = (
    "BOUNDARY::PER_REQUEST_HOT_PATH: "
    "The per-request hot path is the synchronous execution spine exercised on "
    "every request: ``OpenClawd.process()`` → ``_determine_execution_path()`` "
    "→ ``CommandRouter.route_envelope()``.  "
    "Key properties: (1) Every synchronous user request passes through this "
    "path.  (2) LLM calls are routed through ``UnifiedLLMRouter`` "
    "(L1/L2/L3 cognitive authority) on this path.  (3) V4 "
    "(``unified_orchestration_spine``) is NOT inserted into this path for "
    "simple requests — it is only engaged for multi-step orchestration "
    "sessions.  (4) V6 (``release_blocking_gate``) is NEVER inserted into "
    "this path — V6 is startup/CI only."
)

ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL: str = (
    "BOUNDARY::ROUTER_COGNITIVE_AUTHORITY: "
    "Router-level cognitive authority is implemented by three sub-layers "
    "fused into ``core.unified.llm_router.UnifiedLLMRouter``: "
    "L1 (``LLMRouteAuthority``, route selection), "
    "L2 (``LLMSupplyAuthority``, supply/availability legality), "
    "L3 (``CognitiveContextAuthority``, context enrichment/governance).  "
    "Key properties: (1) L1/L2/L3 belong to the router layer — they are NOT "
    "a detached shadow stack that operates independently alongside the hot "
    "path.  (2) All LLM routing decisions must flow through ``UnifiedLLMRouter`` "
    "before reaching the provider supply layer.  (3) Direct calls that bypass "
    "``UnifiedLLMRouter`` and reach ``MultiLLMRouter`` directly from "
    "``OpenClawd`` or other callers are a policy violation."
)

ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL: str = (
    "BOUNDARY::ORCHESTRATION_SESSION_SCOPE: "
    "Multi-step orchestration is governed by V4 "
    "(``core.unified_orchestration_spine``).  "
    "V4 scope is bounded to: parallel fan-out, delegated runtime, "
    "wake-routed tasks, handoff/takeover, cross-device execution, and hybrid "
    "multi-step sessions.  "
    "Key properties: (1) V4 is NOT the universal synchronous per-request "
    "gate — simple LOCAL or single-device requests remain on the per-request "
    "hot path without engaging V4.  (2) V4 authority is orchestration-session "
    "scoped, not per-call scoped.  (3) The ``ORCHESTRATION_SPINE_MULTI_STEP"
    "_SESSION_SCOPE_POLICY`` sentinel in ``core.unified_orchestration_spine`` "
    "is the machine-checkable expression of this boundary."
)

PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL: str = (
    "BOUNDARY::PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE: "
    "Participant authority contracts are defined at the participant-generic "
    "level in ``core.participant_authority_interfaces``.  The Android runtime "
    "is the first concrete participant implementation; its modules implement "
    "the participant-generic interfaces.  "
    "Key properties: (1) Authority interfaces, sentinels, docstrings, and "
    "architectural comments MUST reference participant-generic concepts, not "
    "Android-specific ones, at the contract layer.  (2) Android concrete "
    "modules (``core.android_participant_session_state``, "
    "``core.android_runtime_dispatch_binding``, etc.) implement the generic "
    "contracts — they are NOT removed or renamed.  (3) Future non-Android "
    "participant runtimes can implement the same generic interfaces without "
    "requiring knowledge of Android modules.  (4) The participant-generic "
    "layer does NOT add runtime dependencies on Android modules; the "
    "dependency direction runs Android → generic, not generic → Android."
)

STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL: str = (
    "BOUNDARY::STARTUP_RELEASE_INTEGRITY: "
    "The startup / readiness / health / release integrity boundary is "
    "implemented by V6 (``core.release_blocking_gate`` / "
    "``core.center_authority_boundary``).  "
    "Key properties: (1) V6 is evaluated at CI time and at system startup, "
    "as a pre-release blocking gate.  (2) V6 is NEVER inserted into the "
    "synchronous per-request path — doing so would introduce structural "
    "latency and mis-layer release-posture with cognitive processing.  "
    "(3) V6 does NOT gate individual user requests; it gates the system's "
    "readiness to serve requests as a whole.  (4) The ``V6_IS_NOT_PER_REQUEST"
    "_GATE`` sentinel in ``core.canonical_layer_model`` is the "
    "machine-checkable expression of this boundary."
)

# ---------------------------------------------------------------------------
# Convergence policy sentinels
# ---------------------------------------------------------------------------

CONVERGENCE_PASS_DOES_NOT_REDESIGN_RUNTIME_POLICY: str = (
    "POLICY::CONVERGENCE_PASS_DOES_NOT_REDESIGN_RUNTIME: "
    "PR-11 (final architecture convergence) does NOT redesign the runtime, "
    "does NOT create new major architecture layers, and does NOT undo the "
    "scoping decisions established in PR-6 through PR-10.  "
    "Its scope is: consolidating residual edge inconsistencies, strengthening "
    "final boundary clarity, removing remaining split-brain terminology, and "
    "refining existing validation surfaces.  "
    "Any future change that introduces a new authority layer, reorders the "
    "five canonical layers, or re-scopes V4/V6/L1-L3 must be treated as a "
    "new architectural decision, not a continuation of PR-11."
)

SINGLE_COHERENT_ARCHITECTURE_STORY_POLICY: str = (
    "POLICY::SINGLE_COHERENT_ARCHITECTURE_STORY: "
    "After PR-11, the repository presents exactly ONE coherent canonical "
    "architecture story.  The five canonical runtime layers, the four NOT-"
    "policy boundary invariants, the participant-generic interface contract, "
    "and the terminal regression guards collectively express this single story.  "
    "Any documentation, docstring, sentinel, or comment that contradicts "
    "this story is stale architecture drift and must be removed or corrected."
)

BOUNDARY_CLARITY_PRESERVED_POLICY: str = (
    "POLICY::BOUNDARY_CLARITY_PRESERVED: "
    "The five boundary clarity sentinels introduced by PR-11 "
    "(PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL, "
    "ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL, "
    "ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL, "
    "PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL, "
    "STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL) must remain importable, "
    "non-empty, and consistent with the corresponding NOT-policy sentinels "
    "in ``core.canonical_layer_model`` and the guard policies in "
    "``core.terminal_architecture_audit_guards``.  "
    "Weakening or removing any of these sentinels is an architecture "
    "convergence regression."
)

# ---------------------------------------------------------------------------
# ConvergenceFinding data class
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ConvergenceFinding:
    """A single finding from a final convergence check.

    Attributes
    ----------
    check:
        Short machine-readable check identifier.
    severity:
        ``"error"`` for a confirmed inconsistency, ``"warning"`` for a
        degraded-but-not-broken state, ``"info"`` for a passing check.
    message:
        Human-readable description, actionable for future contributors.
    detail:
        Optional mapping of supplementary context.
    """

    check: str
    severity: str  # "error" | "warning" | "info"
    message: str
    detail: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.check,
            "severity": self.severity,
            "message": self.message,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# ConvergenceReport data class
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ConvergenceReport:
    """Aggregated result of all final convergence checks.

    Attributes
    ----------
    findings:
        All findings collected from every check that ran.
    checks_run:
        Names of the checks that ran.
    overall_converged:
        True when no ERROR findings are present.
    error_count:
        Number of ERROR findings.
    warning_count:
        Number of WARNING findings.
    generated_at:
        Unix timestamp when the report was built.
    """

    findings: List[ConvergenceFinding] = dataclasses.field(default_factory=list)
    checks_run: List[str] = dataclasses.field(default_factory=list)
    overall_converged: bool = True
    error_count: int = 0
    warning_count: int = 0
    generated_at: float = dataclasses.field(default_factory=time.time)

    def _recompute(self) -> None:
        self.error_count = sum(1 for f in self.findings if f.severity == "error")
        self.warning_count = sum(1 for f in self.findings if f.severity == "warning")
        self.overall_converged = self.error_count == 0

    def add(self, finding: ConvergenceFinding) -> None:
        self.findings.append(finding)
        self._recompute()

    def extend(self, findings: List[ConvergenceFinding]) -> None:
        self.findings.extend(findings)
        self._recompute()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_converged": self.overall_converged,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "checks_run": list(self.checks_run),
            "findings": [f.to_dict() for f in self.findings],
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CHECK_BOUNDARIES = "BOUNDARY_SENTINEL_COMPLETENESS"
_CHECK_TERMINAL_GUARDS = "TERMINAL_GUARD_INTEGRITY"
_CHECK_PARTICIPANT = "PARTICIPANT_LAYER_CONSISTENCY"
_CHECK_LAYER_MODEL = "CANONICAL_LAYER_MODEL_REACHABLE"

_OWN_BOUNDARY_SENTINELS = [
    ("PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL", "hot-path boundary"),
    ("ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL", "router cognitive authority boundary"),
    ("ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL", "orchestration session scope boundary"),
    ("PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL", "participant generic/concrete boundary"),
    ("STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL", "startup/release integrity boundary"),
]

_OWN_POLICY_SENTINELS = [
    ("CONVERGENCE_PASS_DOES_NOT_REDESIGN_RUNTIME_POLICY", "convergence non-redesign policy"),
    ("SINGLE_COHERENT_ARCHITECTURE_STORY_POLICY", "single coherent story policy"),
    ("BOUNDARY_CLARITY_PRESERVED_POLICY", "boundary clarity preservation policy"),
]


def _try_import(module_path: str) -> Tuple[bool, Any, Optional[str]]:
    """Attempt to import *module_path*.  Return (importable, module, error)."""
    try:
        mod = importlib.import_module(module_path)
        return True, mod, None
    except Exception as exc:
        return False, None, str(exc)


def _has_nonempty_str(mod: Any, name: str) -> bool:
    """Return True if *mod* has a non-empty string attribute *name*."""
    val = getattr(mod, name, None)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    return True


def _cfinding(
    check: str,
    severity: str,
    message: str,
    detail: Optional[Dict[str, Any]] = None,
) -> ConvergenceFinding:
    return ConvergenceFinding(
        check=check,
        severity=severity,
        message=message,
        detail=detail or {},
    )


def _cerror(check: str, message: str, detail: Optional[Dict[str, Any]] = None) -> ConvergenceFinding:
    return _cfinding(check, "error", message, detail)


def _cwarn(check: str, message: str, detail: Optional[Dict[str, Any]] = None) -> ConvergenceFinding:
    return _cfinding(check, "warning", message, detail)


def _cinfo(check: str, message: str, detail: Optional[Dict[str, Any]] = None) -> ConvergenceFinding:
    return _cfinding(check, "info", message, detail)


# ---------------------------------------------------------------------------
# Check 1 — Boundary sentinel completeness
# ---------------------------------------------------------------------------

def check_boundary_sentinel_completeness() -> List[ConvergenceFinding]:
    """Verify that all five boundary clarity sentinels in this module are
    present, non-empty, and contain the expected boundary keyword.

    Checks performed
    ----------------
    a. Each boundary sentinel is importable from this module and non-empty.
    b. Each boundary sentinel contains ``"NOT"`` (expressing a boundary
       invariant, not merely a description).
    c. Each policy sentinel is importable from this module and non-empty.

    Returns
    -------
    List[ConvergenceFinding]
        One ``info`` finding per passing sentinel; one ``error`` finding per
        missing or weakened sentinel.
    """
    findings: List[ConvergenceFinding] = []
    import sys
    this_module = sys.modules[__name__]

    for sentinel_name, description in _OWN_BOUNDARY_SENTINELS:
        val = getattr(this_module, sentinel_name, None)
        if not val or not isinstance(val, str) or not val.strip():
            findings.append(_cerror(
                _CHECK_BOUNDARIES,
                f"Boundary sentinel {sentinel_name!r} ({description}) is absent "
                f"or empty in core.final_architecture_convergence — "
                "boundary clarity convergence regression.",
                {"sentinel": sentinel_name},
            ))
        elif "NOT" not in val:
            findings.append(_cwarn(
                _CHECK_BOUNDARIES,
                f"Boundary sentinel {sentinel_name!r} ({description}) does not "
                f"contain 'NOT' — it may have lost its boundary-invariant "
                "expression.",
                {"sentinel": sentinel_name},
            ))
        else:
            findings.append(_cinfo(
                _CHECK_BOUNDARIES,
                f"Boundary sentinel {sentinel_name!r} ({description}) present "
                "and contains boundary-invariant 'NOT' expression.",
            ))

    for sentinel_name, description in _OWN_POLICY_SENTINELS:
        val = getattr(this_module, sentinel_name, None)
        if not val or not isinstance(val, str) or not val.strip():
            findings.append(_cerror(
                _CHECK_BOUNDARIES,
                f"Policy sentinel {sentinel_name!r} ({description}) is absent "
                f"or empty in core.final_architecture_convergence — "
                "convergence policy regression.",
                {"sentinel": sentinel_name},
            ))
        else:
            findings.append(_cinfo(
                _CHECK_BOUNDARIES,
                f"Policy sentinel {sentinel_name!r} ({description}) present.",
            ))

    return findings


# ---------------------------------------------------------------------------
# Check 2 — Terminal guard integrity
# ---------------------------------------------------------------------------

def check_terminal_guard_integrity() -> List[ConvergenceFinding]:
    """Verify that ``core.terminal_architecture_audit_guards`` (PR-10) is
    intact and its aggregate guard still passes on the clean system.

    Checks performed
    ----------------
    a. ``core.terminal_architecture_audit_guards`` is importable.
    b. ``run_terminal_audit_guards`` is callable.
    c. ``run_terminal_audit_guards()`` returns a report with
       ``overall_passed=True`` (no regressions on clean system).
    d. Five guard policy sentinels are importable and non-empty.

    Returns
    -------
    List[ConvergenceFinding]
    """
    findings: List[ConvergenceFinding] = []

    importable, mod, err = _try_import("core.terminal_architecture_audit_guards")
    if not importable:
        findings.append(_cerror(
            _CHECK_TERMINAL_GUARDS,
            f"core.terminal_architecture_audit_guards is not importable: {err} — "
            "PR-10 terminal regression guards have been lost.",
        ))
        return findings

    findings.append(_cinfo(
        _CHECK_TERMINAL_GUARDS,
        "core.terminal_architecture_audit_guards is importable.",
    ))

    # Check the five policy sentinels exist
    guard_sentinels = [
        "V4_SCOPE_REGRESSION_GUARD_POLICY",
        "V6_HOT_PATH_REGRESSION_GUARD_POLICY",
        "L1_L2_L3_ROUTER_DETACHMENT_REGRESSION_GUARD_POLICY",
        "COMPLETION_TRUTH_BYPASS_REGRESSION_GUARD_POLICY",
        "ARCHITECTURE_DECLARATION_COHERENCE_GUARD_POLICY",
    ]
    for sname in guard_sentinels:
        if not _has_nonempty_str(mod, sname):
            findings.append(_cerror(
                _CHECK_TERMINAL_GUARDS,
                f"Guard policy sentinel {sname!r} is absent or empty in "
                "core.terminal_architecture_audit_guards — PR-10 guard "
                "policies have been weakened.",
                {"sentinel": sname},
            ))
        else:
            findings.append(_cinfo(
                _CHECK_TERMINAL_GUARDS,
                f"Guard policy sentinel {sname!r} present and non-empty.",
            ))

    # Run the aggregate guard
    runner = getattr(mod, "run_terminal_audit_guards", None)
    if not callable(runner):
        findings.append(_cerror(
            _CHECK_TERMINAL_GUARDS,
            "run_terminal_audit_guards is not callable in "
            "core.terminal_architecture_audit_guards — PR-10 aggregate "
            "guard function has been removed.",
        ))
        return findings

    try:
        report = runner()
        if not getattr(report, "overall_passed", True):
            error_count = getattr(report, "error_count", "unknown")
            findings.append(_cerror(
                _CHECK_TERMINAL_GUARDS,
                f"run_terminal_audit_guards() reports overall_passed=False "
                f"({error_count} error(s)) — an architectural regression has "
                "been introduced.",
                {"error_count": error_count},
            ))
        else:
            findings.append(_cinfo(
                _CHECK_TERMINAL_GUARDS,
                "run_terminal_audit_guards() passed — no terminal guard "
                "regressions detected on clean system.",
            ))
    except Exception as exc:  # noqa: BLE001
        findings.append(_cwarn(
            _CHECK_TERMINAL_GUARDS,
            f"run_terminal_audit_guards() raised an exception: {exc} — "
            "guard execution may be impaired.",
            {"exception": str(exc)},
        ))

    return findings


# ---------------------------------------------------------------------------
# Check 3 — Participant layer consistency
# ---------------------------------------------------------------------------

def check_participant_layer_consistency() -> List[ConvergenceFinding]:
    """Verify that the participant-generic interface layer (PR-8) is intact
    and consistently above the Android concrete implementations.

    Checks performed
    ----------------
    a. ``core.participant_authority_interfaces`` is importable.
    b. The three authority sentinels are present and non-empty.
    c. The generic-above-Android policy sentinel is present.
    d. At least one concrete Android participant module is importable,
       confirming Android implementations were not removed.

    Returns
    -------
    List[ConvergenceFinding]
    """
    findings: List[ConvergenceFinding] = []

    importable, mod, err = _try_import("core.participant_authority_interfaces")
    if not importable:
        findings.append(_cerror(
            _CHECK_PARTICIPANT,
            f"core.participant_authority_interfaces is not importable: {err} — "
            "PR-8 participant-generic interface layer has been lost.",
        ))
        return findings

    findings.append(_cinfo(
        _CHECK_PARTICIPANT,
        "core.participant_authority_interfaces is importable.",
    ))

    # Check authority sentinels
    auth_sentinels = [
        "PARTICIPANT_AUTHORITY_INTERFACES_SENTINEL",
        "PARTICIPANT_AUTHORITY_PR8_SENTINEL",
        "ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL",
    ]
    for sname in auth_sentinels:
        if not _has_nonempty_str(mod, sname):
            findings.append(_cerror(
                _CHECK_PARTICIPANT,
                f"Participant authority sentinel {sname!r} is absent or empty — "
                "PR-8 participant-generic layer authority has been weakened.",
                {"sentinel": sname},
            ))
        else:
            findings.append(_cinfo(
                _CHECK_PARTICIPANT,
                f"Participant authority sentinel {sname!r} present.",
            ))

    # Check the generic-above-Android policy
    policy_name = "PARTICIPANT_GENERIC_LAYER_IS_ABOVE_ANDROID_CONCRETE_POLICY"
    if not _has_nonempty_str(mod, policy_name):
        findings.append(_cerror(
            _CHECK_PARTICIPANT,
            f"Policy sentinel {policy_name!r} is absent or empty in "
            "core.participant_authority_interfaces — the participant-generic "
            "above Android-concrete boundary is no longer machine-checked.",
            {"sentinel": policy_name},
        ))
    else:
        findings.append(_cinfo(
            _CHECK_PARTICIPANT,
            f"Policy sentinel {policy_name!r} present — participant-generic "
            "above Android boundary is expressed.",
        ))

    # Verify Android concrete modules still exist (Android must not be removed)
    android_modules = [
        "core.android_participant_session_state",
        "core.android_runtime_dispatch_binding",
    ]
    for android_mod in android_modules:
        importable_android, _, _ = _try_import(android_mod)
        if not importable_android:
            findings.append(_cwarn(
                _CHECK_PARTICIPANT,
                f"Android concrete module {android_mod!r} is not importable — "
                "Android participant implementation may have been removed.  "
                "The participant-generic layer must have at least one concrete "
                "implementation.",
                {"module": android_mod},
            ))
        else:
            findings.append(_cinfo(
                _CHECK_PARTICIPANT,
                f"Android concrete module {android_mod!r} is importable — "
                "concrete implementation preserved.",
            ))

    return findings


# ---------------------------------------------------------------------------
# Check 4 — Canonical layer model reachable
# ---------------------------------------------------------------------------

def check_canonical_layer_model_reachable() -> List[ConvergenceFinding]:
    """Verify that ``core.canonical_layer_model`` (PR-9) is intact, all five
    layers are declared, and the four NOT-policy sentinels are present.

    Checks performed
    ----------------
    a. ``core.canonical_layer_model`` is importable.
    b. ``CANONICAL_LAYER_KEYS`` contains all five expected layer keys.
    c. The four NOT-policy sentinels are present and non-empty.
    d. ``run_layer_model_invariants()`` returns ``overall_consistent=True``.

    Returns
    -------
    List[ConvergenceFinding]
    """
    findings: List[ConvergenceFinding] = []

    importable, mod, err = _try_import("core.canonical_layer_model")
    if not importable:
        findings.append(_cerror(
            _CHECK_LAYER_MODEL,
            f"core.canonical_layer_model is not importable: {err} — "
            "PR-9 canonical layer model has been lost.",
        ))
        return findings

    findings.append(_cinfo(
        _CHECK_LAYER_MODEL,
        "core.canonical_layer_model is importable.",
    ))

    # Check all five layer keys
    expected_keys = {
        "completion_truth_backbone",
        "router_cognitive_authority",
        "per_request_hot_path",
        "multi_step_orchestration_spine",
        "startup_release_integrity",
    }
    actual_keys = getattr(mod, "CANONICAL_LAYER_KEYS", frozenset())
    missing = expected_keys - frozenset(actual_keys)
    if missing:
        findings.append(_cerror(
            _CHECK_LAYER_MODEL,
            f"CANONICAL_LAYER_KEYS is missing expected layer keys: {sorted(missing)} — "
            "the five-layer canonical model has been partially removed.",
            {"missing_keys": sorted(missing)},
        ))
    else:
        findings.append(_cinfo(
            _CHECK_LAYER_MODEL,
            "All five canonical layer keys present in CANONICAL_LAYER_KEYS.",
        ))

    # Check the four NOT-policy sentinels
    not_sentinels = [
        "V4_IS_NOT_PER_REQUEST_GATE",
        "V6_IS_NOT_PER_REQUEST_GATE",
        "L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK",
        "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL",
    ]
    for sname in not_sentinels:
        if not _has_nonempty_str(mod, sname):
            findings.append(_cerror(
                _CHECK_LAYER_MODEL,
                f"NOT-policy sentinel {sname!r} is absent or empty in "
                "core.canonical_layer_model — a canonical layer boundary "
                "invariant has been removed.",
                {"sentinel": sname},
            ))
        else:
            findings.append(_cinfo(
                _CHECK_LAYER_MODEL,
                f"NOT-policy sentinel {sname!r} present.",
            ))

    # Run the layer model invariants
    runner = getattr(mod, "run_layer_model_invariants", None)
    if not callable(runner):
        findings.append(_cerror(
            _CHECK_LAYER_MODEL,
            "run_layer_model_invariants is not callable in "
            "core.canonical_layer_model — PR-9 invariant runner removed.",
        ))
        return findings

    try:
        report = runner()
        if not getattr(report, "overall_consistent", True):
            findings.append(_cerror(
                _CHECK_LAYER_MODEL,
                "run_layer_model_invariants() reports overall_consistent=False — "
                "the canonical layer model has an internal inconsistency.",
                {"report": getattr(report, "to_dict", lambda: {})()},
            ))
        else:
            findings.append(_cinfo(
                _CHECK_LAYER_MODEL,
                "run_layer_model_invariants() passed — canonical layer model "
                "is internally consistent.",
            ))
    except Exception as exc:  # noqa: BLE001
        findings.append(_cwarn(
            _CHECK_LAYER_MODEL,
            f"run_layer_model_invariants() raised an exception: {exc}",
            {"exception": str(exc)},
        ))

    return findings


# ---------------------------------------------------------------------------
# Aggregate runner
# ---------------------------------------------------------------------------

def run_final_convergence_checks() -> ConvergenceReport:
    """Run all four final convergence checks and aggregate the results.

    Returns
    -------
    ConvergenceReport
        Aggregated report with ``overall_converged=True`` when no ERROR
        findings are present.
    """
    report = ConvergenceReport(generated_at=time.time())

    checks = [
        (_CHECK_BOUNDARIES, check_boundary_sentinel_completeness),
        (_CHECK_TERMINAL_GUARDS, check_terminal_guard_integrity),
        (_CHECK_PARTICIPANT, check_participant_layer_consistency),
        (_CHECK_LAYER_MODEL, check_canonical_layer_model_reachable),
    ]

    for check_name, check_fn in checks:
        try:
            findings = check_fn()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Fallback triggered: %s", exc)
            findings = [_cerror(
                check_name,
                f"Check {check_name!r} raised an unexpected exception: {exc}",
                {"exception": str(exc)},
            )]
        report.checks_run.append(check_name)
        report.extend(findings)
        logger.debug(
            "Convergence check %r: %d finding(s)",
            check_name,
            len(findings),
        )

    if report.overall_converged:
        logger.info(
            "Final architecture convergence checks passed (%d checks, %d info findings).",
            len(report.checks_run),
            sum(1 for f in report.findings if f.severity == "info"),
        )
    else:
        logger.warning(
            "Final architecture convergence checks FAILED: %d error(s), %d warning(s).",
            report.error_count,
            report.warning_count,
        )

    return report
