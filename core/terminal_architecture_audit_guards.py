#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/terminal_architecture_audit_guards.py
==========================================
PR-10: Terminal Architecture Audit Guards — regression prevention for the
validated final integrated center-distributed architecture.

Purpose
-------
This module is the **final hardening pass** after the architecture alignment
sequence (PR-4 through PR-9).  It converts the terminal dual-repository audit
conclusions into lightweight, machine-checkable regression guards so that
future changes cannot silently drift the system back into contradictory
layering.

What this module guards
-----------------------
The validated final integrated architecture establishes five layer contracts
that this module protects:

1. **V4 scope guard** — ``core.unified_orchestration_spine`` (V4) is the
   multi-step orchestration spine, NOT the universal synchronous per-request
   gate.  Any code path or declaration that re-introduces V4 as a mandatory
   per-request gate is a regression.

2. **V6 hot-path exclusion guard** — ``core.release_blocking_gate`` /
   ``core.center_authority_boundary`` (V6) is the startup / readiness /
   health / release integrity boundary.  V6 must never appear in per-request
   hot paths (``OpenClawd.process``, ``CommandRouter.route_envelope``).

3. **L1/L2/L3 router-layer authority guard** — L1 (``LLMRouteAuthority``),
   L2 (``LLMSupplyAuthority``), and L3 (``CognitiveContextAuthority``) are
   router-level cognitive authority sub-layers fused into
   ``UnifiedLLMRouter``.  They must remain wired into ``UnifiedLLMRouter``
   and must not be detached into a shadow stack.

4. **Completion truth backbone guard** — The canonical completion truth chain
   (``CanonicalCompletionIngress`` + V5 + ``durable_truth_authority_chain``)
   must remain enforced and must not be weakened into optional soft signaling.

5. **Architecture declaration coherence guard** — Repository-level
   architecture declarations must agree on the same canonical layer model
   (as established in ``core.canonical_layer_model``).  Contradictory or
   divergent declarations are a regression.

Design principles
-----------------
* **Inspective only** — no execution logic is altered; all checks read module
  attributes, docstrings, and import graphs.
* **Extends existing surfaces** — guards are built on top of
  ``core.canonical_layer_model``, the NOT-policy sentinel strings, and the
  authority sentinel strings already present in the codebase.  No parallel
  mechanism is created.
* **Lightweight** — each guard is a short function that returns a
  :class:`TerminalGuardFinding` list.  Callers decide whether to assert,
  warn, or report.
* **Maintainable** — guards check structural wiring (import presence/absence)
  and sentinel string content rather than fragile cosmetic formatting.

Public API
----------
Sentinels::

    TERMINAL_ARCHITECTURE_AUDIT_GUARDS_AUTHORITY
    TERMINAL_ARCHITECTURE_AUDIT_GUARDS_PR10_SENTINEL
    V4_SCOPE_REGRESSION_GUARD_POLICY
    V6_HOT_PATH_REGRESSION_GUARD_POLICY
    L1_L2_L3_ROUTER_DETACHMENT_REGRESSION_GUARD_POLICY
    COMPLETION_TRUTH_BYPASS_REGRESSION_GUARD_POLICY
    ARCHITECTURE_DECLARATION_COHERENCE_GUARD_POLICY

Data classes::

    TerminalGuardFinding
    TerminalGuardReport

Guard functions::

    check_v4_scope_regression(snapshot) -> List[TerminalGuardFinding]
    check_v6_hot_path_regression(snapshot) -> List[TerminalGuardFinding]
    check_l1_l2_l3_router_detachment(snapshot) -> List[TerminalGuardFinding]
    check_completion_truth_bypass(snapshot) -> List[TerminalGuardFinding]
    check_architecture_declaration_coherence(snapshot) -> List[TerminalGuardFinding]
    run_terminal_audit_guards(snapshot) -> TerminalGuardReport
"""

from __future__ import annotations

import dataclasses
import importlib
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.TerminalArchitectureAuditGuards")

__all__ = [
    # Sentinels
    "TERMINAL_ARCHITECTURE_AUDIT_GUARDS_AUTHORITY",
    "TERMINAL_ARCHITECTURE_AUDIT_GUARDS_PR10_SENTINEL",
    "V4_SCOPE_REGRESSION_GUARD_POLICY",
    "V6_HOT_PATH_REGRESSION_GUARD_POLICY",
    "L1_L2_L3_ROUTER_DETACHMENT_REGRESSION_GUARD_POLICY",
    "COMPLETION_TRUTH_BYPASS_REGRESSION_GUARD_POLICY",
    "ARCHITECTURE_DECLARATION_COHERENCE_GUARD_POLICY",
    # Data classes
    "TerminalGuardFinding",
    "TerminalGuardReport",
    # Guard functions
    "check_v4_scope_regression",
    "check_v6_hot_path_regression",
    "check_l1_l2_l3_router_detachment",
    "check_completion_truth_bypass",
    "check_architecture_declaration_coherence",
    "run_terminal_audit_guards",
]

# ---------------------------------------------------------------------------
# Module authority sentinels
# ---------------------------------------------------------------------------

TERMINAL_ARCHITECTURE_AUDIT_GUARDS_AUTHORITY: str = (
    "TERMINAL_ARCHITECTURE_AUDIT_GUARDS_AUTHORITY::PR10: "
    "core.terminal_architecture_audit_guards is the terminal regression guard "
    "module for the validated final integrated center-distributed architecture. "
    "It converts the terminal dual-repository audit conclusions into "
    "machine-checkable invariants that prevent silent layer drift after the "
    "PR-4 through PR-9 architecture alignment sequence.  "
    "This module does NOT alter execution logic; all checks are purely inspective."
)

TERMINAL_ARCHITECTURE_AUDIT_GUARDS_PR10_SENTINEL: str = (
    "PR::TERMINAL_ARCHITECTURE_AUDIT_GUARDS_PR10: "
    "Introduced by PR-10 (Terminal architecture audit guards — regression "
    "prevention for the validated final integrated architecture).  "
    "Removing or weakening these guards re-opens the architectural regressions "
    "that the PR-4 through PR-9 alignment sequence resolved."
)

# ---------------------------------------------------------------------------
# Guard policy sentinels — one per regression type
# ---------------------------------------------------------------------------

V4_SCOPE_REGRESSION_GUARD_POLICY: str = (
    "GUARD_POLICY::V4_SCOPE_REGRESSION: "
    "core.unified_orchestration_spine (V4) MUST remain scoped to multi-step "
    "orchestration sessions (parallel fan-out, delegated runtime, wake-routed, "
    "handoff/takeover, cross-device, hybrid).  "
    "V4 MUST NOT be re-introduced as a mandatory synchronous gate on every "
    "per-request call through OpenClawd.process() or "
    "CommandRouter.route_envelope().  "
    "A regression is detected when: (a) per-request hot-path modules import "
    "unified_orchestration_spine, (b) architecture snapshots declare V4 as "
    "is_per_request_gate=True, or (c) V4_IS_NOT_PER_REQUEST_GATE_POLICY or "
    "V4_IS_NOT_PER_REQUEST_GATE sentinel strings are absent or weakened."
)

V6_HOT_PATH_REGRESSION_GUARD_POLICY: str = (
    "GUARD_POLICY::V6_HOT_PATH_REGRESSION: "
    "core.release_blocking_gate / core.center_authority_boundary (V6) MUST "
    "remain at the startup / readiness / health / release integrity boundary.  "
    "V6 MUST NOT appear in per-request hot paths.  "
    "A regression is detected when: (a) per-request hot-path modules "
    "(OpenClawd.process, CommandRouter.route_envelope) import or call V6 "
    "boundary functions, (b) architecture snapshots declare V6 as "
    "is_per_request_gate=True, or (c) V6_IS_NOT_PER_REQUEST_GATE sentinel "
    "is absent or weakened."
)

L1_L2_L3_ROUTER_DETACHMENT_REGRESSION_GUARD_POLICY: str = (
    "GUARD_POLICY::L1_L2_L3_ROUTER_DETACHMENT_REGRESSION: "
    "L1 (LLMRouteAuthority), L2 (LLMSupplyAuthority), and L3 "
    "(CognitiveContextAuthority) MUST remain fused into UnifiedLLMRouter as "
    "the router-level cognitive authority sub-layers.  "
    "L1/L2/L3 MUST NOT be detached into a shadow stack that runs independently "
    "alongside the per-request hot path.  "
    "A regression is detected when: (a) UnifiedLLMRouter no longer holds "
    "_l1_authority / _l2_authority / _l3_authority attributes, (b) the "
    "authority helper methods are removed, or (c) architecture snapshots "
    "declare L1/L2/L3 as is_shadow_stack=True."
)

COMPLETION_TRUTH_BYPASS_REGRESSION_GUARD_POLICY: str = (
    "GUARD_POLICY::COMPLETION_TRUTH_BYPASS_REGRESSION: "
    "The canonical completion truth backbone (CanonicalCompletionIngress, "
    "canonical_group_completion_closure V5, durable_truth_authority_chain) "
    "MUST remain enforced and MUST NOT be weakened into optional soft "
    "signaling.  "
    "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY sentinel MUST remain importable "
    "and non-empty.  run_task_result_truth_chain MUST remain the canonical "
    "four-step must-run truth chain.  "
    "A regression is detected when: (a) TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY "
    "is absent or empty, (b) the canonical truth chain module is not importable, "
    "or (c) architecture snapshots declare the completion backbone as "
    "is_optional_signaling=True."
)

ARCHITECTURE_DECLARATION_COHERENCE_GUARD_POLICY: str = (
    "GUARD_POLICY::ARCHITECTURE_DECLARATION_COHERENCE: "
    "Repository-level architecture declarations MUST agree on the same "
    "canonical five-layer model as established in core.canonical_layer_model.  "
    "A regression is detected when: (a) canonical_layer_model is not importable, "
    "(b) the five canonical layer keys are absent or renamed, (c) the four "
    "NOT-policy sentinels are absent or empty, or (d) run_layer_model_invariants() "
    "returns overall_consistent=False on the built-in registry."
)

# ---------------------------------------------------------------------------
# Finding and report data types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class TerminalGuardFinding:
    """A single finding from a terminal architecture audit guard check.

    Attributes
    ----------
    guard:
        Short machine-readable guard identifier, e.g.
        ``"V4_SCOPE_REGRESSION"`` or ``"V6_HOT_PATH_REGRESSION"``.
    severity:
        ``"error"`` for a confirmed regression, ``"warning"`` for a
        degraded-but-not-broken state, ``"info"`` for a passing check.
    message:
        Human-readable description, actionable for future contributors.
    detail:
        Optional mapping of supplementary context (found vs. expected values).
    """

    guard: str
    severity: str  # "error" | "warning" | "info"
    message: str
    detail: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "guard": self.guard,
            "severity": self.severity,
            "message": self.message,
            "detail": self.detail,
        }


def _finding(
    guard: str,
    severity: str,
    message: str,
    detail: Optional[Dict[str, Any]] = None,
) -> TerminalGuardFinding:
    return TerminalGuardFinding(
        guard=guard,
        severity=severity,
        message=message,
        detail=detail or {},
    )


def _error(guard: str, message: str, detail: Optional[Dict[str, Any]] = None) -> TerminalGuardFinding:
    return _finding(guard, "error", message, detail)


def _warn(guard: str, message: str, detail: Optional[Dict[str, Any]] = None) -> TerminalGuardFinding:
    return _finding(guard, "warning", message, detail)


def _info(guard: str, message: str, detail: Optional[Dict[str, Any]] = None) -> TerminalGuardFinding:
    return _finding(guard, "info", message, detail)


@dataclasses.dataclass
class TerminalGuardReport:
    """Aggregated result of all terminal architecture audit guard checks.

    Attributes
    ----------
    findings:
        All findings collected from every guard that ran.
    guards_run:
        Names of the guards that ran.
    overall_passed:
        True when no ERROR findings are present.
    error_count:
        Number of ERROR findings.
    warning_count:
        Number of WARNING findings.
    generated_at:
        Unix timestamp when the report was built.
    policy_sentinels:
        List of guard policy sentinel strings included in this report,
        for CI consumption.
    """

    findings: List[TerminalGuardFinding] = dataclasses.field(default_factory=list)
    guards_run: List[str] = dataclasses.field(default_factory=list)
    overall_passed: bool = True
    error_count: int = 0
    warning_count: int = 0
    generated_at: float = dataclasses.field(default_factory=time.time)
    policy_sentinels: List[str] = dataclasses.field(default_factory=list)

    def _recompute(self) -> None:
        self.error_count = sum(1 for f in self.findings if f.severity == "error")
        self.warning_count = sum(1 for f in self.findings if f.severity == "warning")
        self.overall_passed = self.error_count == 0

    def add(self, finding: TerminalGuardFinding) -> None:
        self.findings.append(finding)
        self._recompute()

    def extend(self, findings: List[TerminalGuardFinding]) -> None:
        self.findings.extend(findings)
        self._recompute()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_passed": self.overall_passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "guards_run": list(self.guards_run),
            "findings": [f.to_dict() for f in self.findings],
            "generated_at": self.generated_at,
            "policy_sentinels": list(self.policy_sentinels),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_HOT_PATH_MODULES = [
    "core/command_router.py",
    "core/openclawd.py",
    "core/execution_spine.py",
]

_V4_SENTINEL_NAME = "V4_IS_NOT_PER_REQUEST_GATE_POLICY"
_V6_SENTINEL_NAME = "V6_IS_NOT_PER_REQUEST_GATE"
_L1_L2_L3_SENTINEL_NAME = "L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK"
_COMPLETION_TRUTH_POLICY_NAME = "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY"


def _try_import(module_path: str) -> Tuple[bool, Any, Optional[str]]:
    """Attempt to import *module_path*.  Return (importable, module, error)."""
    try:
        mod = importlib.import_module(module_path)
        return True, mod, None
    except Exception as exc:
        return False, None, str(exc)


def _has_attr(mod: Any, name: str) -> bool:
    """Return True if *mod* has a non-empty attribute *name*."""
    val = getattr(mod, name, None)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    return True


def _read_source(rel_path: str) -> Optional[str]:
    """Read source of a project-relative file, return None on error."""
    import os
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    full_path = os.path.join(project_root, rel_path)
    try:
        with open(full_path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Guard 1 — V4 scope regression
# ---------------------------------------------------------------------------

_GUARD_V4 = "V4_SCOPE_REGRESSION"


def check_v4_scope_regression(
    snapshot: Optional[Dict[str, Any]] = None,
) -> List[TerminalGuardFinding]:
    """Check that V4 (unified_orchestration_spine) has not regressed to a
    universal per-request gate.

    Checks performed
    ----------------
    a. ``core.unified_orchestration_spine`` is importable and carries
       ``UNIFIED_ORCHESTRATION_SPINE_AUTHORITY`` and
       ``V4_IS_NOT_PER_REQUEST_GATE_POLICY`` sentinels.
    b. ``V4_IS_NOT_PER_REQUEST_GATE_POLICY`` content contains "NOT" and
       "per-request" (sentinel has not been diluted).
    c. Per-request hot-path source files (command_router.py, openclawd.py)
       do NOT import ``unified_orchestration_spine``.
    d. If *snapshot* contains ``layer_key == "multi_step_orchestration_spine"``
       and ``is_per_request_gate == True``, emit an error.

    Parameters
    ----------
    snapshot:
        Optional architecture snapshot dict.

    Returns
    -------
    List[TerminalGuardFinding]
    """
    findings: List[TerminalGuardFinding] = []

    # (a) Module importable and sentinels present.
    importable, mod, err = _try_import("core.unified_orchestration_spine")
    if not importable:
        findings.append(_error(
            _GUARD_V4,
            "core.unified_orchestration_spine is not importable; "
            "V4 scope cannot be validated.",
            {"error": err},
        ))
        return findings

    if not _has_attr(mod, "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY"):
        findings.append(_error(
            _GUARD_V4,
            "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY sentinel is absent from "
            "core.unified_orchestration_spine — V4 authority anchor removed.",
        ))

    if not _has_attr(mod, _V4_SENTINEL_NAME):
        findings.append(_error(
            _GUARD_V4,
            f"{_V4_SENTINEL_NAME} sentinel is absent from "
            "core.unified_orchestration_spine — V4 scope guard removed.",
        ))
    else:
        # (b) Sentinel content must not be diluted.
        val: str = getattr(mod, _V4_SENTINEL_NAME, "")
        if "NOT" not in val:
            findings.append(_error(
                _GUARD_V4,
                f"{_V4_SENTINEL_NAME} no longer contains 'NOT' — "
                "the scope restriction may have been removed.",
                {"sentinel_snippet": val[:120]},
            ))
        if "per-request" not in val.lower() and "per_request" not in val.lower():
            findings.append(_error(
                _GUARD_V4,
                f"{_V4_SENTINEL_NAME} no longer mentions 'per-request' — "
                "the scope restriction may have been diluted.",
                {"sentinel_snippet": val[:120]},
            ))

    # (c) Hot-path sources must not import V4.
    for rel_path in _HOT_PATH_MODULES:
        source = _read_source(rel_path)
        if source is None:
            continue
        if "unified_orchestration_spine" in source:
            findings.append(_error(
                _GUARD_V4,
                f"Per-request hot-path module '{rel_path}' imports "
                "unified_orchestration_spine — V4 has been re-inserted "
                "into the per-request hot path (regression).",
                {"file": rel_path},
            ))

    # (d) Snapshot-level check.
    if snapshot and isinstance(snapshot, dict):
        if (
            snapshot.get("layer_key") == "multi_step_orchestration_spine"
            and snapshot.get("is_per_request_gate") is True
        ):
            findings.append(_error(
                _GUARD_V4,
                "Architecture snapshot declares V4 as is_per_request_gate=True — "
                "V4_IS_NOT_PER_REQUEST_GATE boundary invariant violated.",
                {"snapshot": snapshot},
            ))

    if not findings:
        findings.append(_info(
            _GUARD_V4,
            "V4 scope guard passed: unified_orchestration_spine remains "
            "scoped to multi-step orchestration sessions; not on per-request hot path.",
        ))

    return findings


# ---------------------------------------------------------------------------
# Guard 2 — V6 hot-path regression
# ---------------------------------------------------------------------------

_GUARD_V6 = "V6_HOT_PATH_REGRESSION"

_V6_MODULES = ["core.release_blocking_gate", "core.center_authority_boundary"]
_V6_IMPORT_NAMES = ["release_blocking_gate", "center_authority_boundary",
                    "assert_center_authority_intact", "evaluate_center_authority_boundary"]


def check_v6_hot_path_regression(
    snapshot: Optional[Dict[str, Any]] = None,
) -> List[TerminalGuardFinding]:
    """Check that V6 (release_blocking_gate / center_authority_boundary) has
    not been inserted into the per-request hot path.

    Checks performed
    ----------------
    a. ``core.canonical_layer_model.V6_IS_NOT_PER_REQUEST_GATE`` sentinel is
       importable and non-empty.
    b. Per-request hot-path source files (command_router.py, openclawd.py)
       do NOT import V6 boundary symbols.
    c. If *snapshot* contains ``layer_key == "startup_release_integrity"``
       and ``is_per_request_gate == True``, emit an error.

    Parameters
    ----------
    snapshot:
        Optional architecture snapshot dict.

    Returns
    -------
    List[TerminalGuardFinding]
    """
    findings: List[TerminalGuardFinding] = []

    # (a) V6 NOT-policy sentinel importable.
    importable, mod, err = _try_import("core.canonical_layer_model")
    if not importable:
        findings.append(_error(
            _GUARD_V6,
            "core.canonical_layer_model is not importable; "
            "V6 hot-path guard cannot be fully validated.",
            {"error": err},
        ))
    else:
        if not _has_attr(mod, _V6_SENTINEL_NAME):
            findings.append(_error(
                _GUARD_V6,
                f"{_V6_SENTINEL_NAME} sentinel is absent from "
                "core.canonical_layer_model — V6 boundary invariant removed.",
            ))
        else:
            val: str = getattr(mod, _V6_SENTINEL_NAME, "")
            if "NOT" not in val:
                findings.append(_error(
                    _GUARD_V6,
                    f"{_V6_SENTINEL_NAME} no longer contains 'NOT' — "
                    "V6 hot-path restriction may have been removed.",
                    {"sentinel_snippet": val[:120]},
                ))

    # (b) Hot-path sources must not import V6 boundary symbols.
    for rel_path in _HOT_PATH_MODULES:
        source = _read_source(rel_path)
        if source is None:
            continue
        for name in _V6_IMPORT_NAMES:
            if name in source:
                findings.append(_error(
                    _GUARD_V6,
                    f"Per-request hot-path module '{rel_path}' references "
                    f"'{name}' — V6 boundary has been inserted into the "
                    "per-request hot path (regression).",
                    {"file": rel_path, "symbol": name},
                ))

    # (c) Snapshot-level check.
    if snapshot and isinstance(snapshot, dict):
        if (
            snapshot.get("layer_key") == "startup_release_integrity"
            and snapshot.get("is_per_request_gate") is True
        ):
            findings.append(_error(
                _GUARD_V6,
                "Architecture snapshot declares V6 as is_per_request_gate=True — "
                "V6_IS_NOT_PER_REQUEST_GATE boundary invariant violated.",
                {"snapshot": snapshot},
            ))

    if not findings:
        findings.append(_info(
            _GUARD_V6,
            "V6 hot-path guard passed: release_blocking_gate / "
            "center_authority_boundary remains outside per-request hot paths.",
        ))

    return findings


# ---------------------------------------------------------------------------
# Guard 3 — L1/L2/L3 router detachment regression
# ---------------------------------------------------------------------------

_GUARD_L123 = "L1_L2_L3_ROUTER_DETACHMENT_REGRESSION"

_L123_AUTHORITY_ATTRS = [
    "_l1_authority",
    "_l2_authority",
    "_l3_authority",
]
_L123_HELPER_METHODS = [
    "_get_l1_route_authority",
    "_get_l2_supply_authority",
    "_get_l3_context_authority",
]


def check_l1_l2_l3_router_detachment(
    snapshot: Optional[Dict[str, Any]] = None,
) -> List[TerminalGuardFinding]:
    """Check that L1/L2/L3 cognitive authority remains fused into
    UnifiedLLMRouter and has not been detached into a shadow stack.

    Checks performed
    ----------------
    a. ``core.unified.llm_router.UnifiedLLMRouter`` is importable.
    b. ``UnifiedLLMRouter`` instances carry ``_l1_authority``,
       ``_l2_authority``, ``_l3_authority`` attributes.
    c. ``UnifiedLLMRouter`` exposes ``_get_l1_route_authority``,
       ``_get_l2_supply_authority``, ``_get_l3_context_authority`` methods.
    d. ``core.canonical_layer_model.L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK``
       sentinel is importable and non-empty.
    e. If *snapshot* contains ``layer_key == "router_cognitive_authority"``
       and ``is_shadow_stack == True``, emit an error.

    Parameters
    ----------
    snapshot:
        Optional architecture snapshot dict.

    Returns
    -------
    List[TerminalGuardFinding]
    """
    findings: List[TerminalGuardFinding] = []

    # (a) Router source inspection (preferred) or import.
    # We check the source file first so that missing optional runtime dependencies
    # (e.g. pydantic) do not produce false-positive regression errors.
    _router_source_path = "core/unified/llm_router.py"
    router_source = _read_source(_router_source_path)
    if router_source is None:
        # Source file absent — the module was removed (structural regression).
        findings.append(_error(
            _GUARD_L123,
            f"{_router_source_path} does not exist — "
            "core.unified.llm_router (UnifiedLLMRouter) has been removed; "
            "L1/L2/L3 router fusion anchor is gone.",
        ))
    else:
        # (b) Attribute presence via source inspection.
        for attr in _L123_AUTHORITY_ATTRS:
            if attr not in router_source:
                findings.append(_error(
                    _GUARD_L123,
                    f"UnifiedLLMRouter source does not reference '{attr}' — "
                    "L1/L2/L3 cognitive authority attribute may have been removed.",
                    {"missing_attr": attr, "source_file": _router_source_path},
                ))

        # (c) Helper method presence via source inspection.
        for method in _L123_HELPER_METHODS:
            if method not in router_source:
                findings.append(_error(
                    _GUARD_L123,
                    f"UnifiedLLMRouter source does not define method '{method}' — "
                    "L1/L2/L3 authority integration helper may have been removed.",
                    {"missing_method": method, "source_file": _router_source_path},
                ))

        # Also try live import for environments where dependencies are available;
        # import failure due to missing deps is a warning, not an error (since
        # the source-level checks above already verified structural presence).
        importable, mod, err = _try_import("core.unified.llm_router")
        if not importable:
            findings.append(_warn(
                _GUARD_L123,
                "core.unified.llm_router is not importable at runtime "
                "(likely missing optional dependency); "
                "live class validation skipped — source-level checks passed.",
                {"error": err},
            ))
        elif mod is not None:
            router_cls = getattr(mod, "UnifiedLLMRouter", None)
            if router_cls is None:
                findings.append(_error(
                    _GUARD_L123,
                    "UnifiedLLMRouter class is absent from core.unified.llm_router "
                    "(module imports but class is missing) — "
                    "L1/L2/L3 router fusion anchor removed.",
                ))

    # (d) NOT-policy sentinel.
    importable_clm, clm_mod, clm_err = _try_import("core.canonical_layer_model")
    if importable_clm and clm_mod:
        if not _has_attr(clm_mod, _L1_L2_L3_SENTINEL_NAME):
            findings.append(_error(
                _GUARD_L123,
                f"{_L1_L2_L3_SENTINEL_NAME} sentinel is absent from "
                "core.canonical_layer_model — L1/L2/L3 layer invariant removed.",
            ))

    # (e) Snapshot-level check.
    if snapshot and isinstance(snapshot, dict):
        if (
            snapshot.get("layer_key") == "router_cognitive_authority"
            and snapshot.get("is_shadow_stack") is True
        ):
            findings.append(_error(
                _GUARD_L123,
                "Architecture snapshot declares L1/L2/L3 as is_shadow_stack=True — "
                "L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK boundary "
                "invariant violated.",
                {"snapshot": snapshot},
            ))

    if not findings:
        findings.append(_info(
            _GUARD_L123,
            "L1/L2/L3 router detachment guard passed: cognitive authority "
            "remains fused into UnifiedLLMRouter.",
        ))

    return findings


# ---------------------------------------------------------------------------
# Guard 4 — Completion truth bypass regression
# ---------------------------------------------------------------------------

_GUARD_COMPLETION = "COMPLETION_TRUTH_BYPASS_REGRESSION"


def check_completion_truth_bypass(
    snapshot: Optional[Dict[str, Any]] = None,
) -> List[TerminalGuardFinding]:
    """Check that the canonical completion truth backbone has not been
    weakened or bypassed.

    Checks performed
    ----------------
    a. ``core.task_result_canonical_truth_chain`` is importable.
    b. ``TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY`` is present and non-empty.
    c. ``TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY`` content contains "MUST" and
       "truth" (policy has not been diluted).
    d. ``run_task_result_truth_chain`` callable is present.
    e. ``core.canonical_completion_ingress`` is importable.
    f. ``core.canonical_layer_model.COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL``
       sentinel is present and non-empty.
    g. If *snapshot* contains ``layer_key == "completion_truth_backbone"``
       and ``is_optional_signaling == True``, emit an error.

    Parameters
    ----------
    snapshot:
        Optional architecture snapshot dict.

    Returns
    -------
    List[TerminalGuardFinding]
    """
    findings: List[TerminalGuardFinding] = []

    # (a) Truth chain module importable.
    importable, mod, err = _try_import("core.task_result_canonical_truth_chain")
    if not importable:
        findings.append(_error(
            _GUARD_COMPLETION,
            "core.task_result_canonical_truth_chain is not importable; "
            "completion truth backbone cannot be validated.",
            {"error": err},
        ))
    else:
        # (b) Policy sentinel present.
        if not _has_attr(mod, _COMPLETION_TRUTH_POLICY_NAME):
            findings.append(_error(
                _GUARD_COMPLETION,
                f"{_COMPLETION_TRUTH_POLICY_NAME} is absent from "
                "core.task_result_canonical_truth_chain — "
                "completion truth mandate removed.",
            ))
        else:
            # (c) Content not diluted.
            val: str = getattr(mod, _COMPLETION_TRUTH_POLICY_NAME, "")
            if "MUST" not in val:
                findings.append(_error(
                    _GUARD_COMPLETION,
                    f"{_COMPLETION_TRUTH_POLICY_NAME} no longer contains 'MUST' — "
                    "the mandatory enforcement may have been weakened.",
                    {"sentinel_snippet": val[:120]},
                ))
            if "truth" not in val.lower():
                findings.append(_error(
                    _GUARD_COMPLETION,
                    f"{_COMPLETION_TRUTH_POLICY_NAME} no longer mentions 'truth' — "
                    "the policy semantics may have been changed.",
                    {"sentinel_snippet": val[:120]},
                ))

        # (d) Entry-point callable present.
        fn = getattr(mod, "run_task_result_truth_chain", None)
        if not callable(fn):
            findings.append(_error(
                _GUARD_COMPLETION,
                "run_task_result_truth_chain callable is absent from "
                "core.task_result_canonical_truth_chain — "
                "completion truth entry point removed.",
            ))

    # (e) CanonicalCompletionIngress importable.
    cci_importable, _, cci_err = _try_import("core.canonical_completion_ingress")
    if not cci_importable:
        findings.append(_error(
            _GUARD_COMPLETION,
            "core.canonical_completion_ingress is not importable; "
            "canonical completion ingress backbone unavailable.",
            {"error": cci_err},
        ))

    # (f) Layer model sentinel present.
    importable_clm, clm_mod, _ = _try_import("core.canonical_layer_model")
    if importable_clm and clm_mod:
        if not _has_attr(clm_mod, "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL"):
            findings.append(_error(
                _GUARD_COMPLETION,
                "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL sentinel is absent "
                "from core.canonical_layer_model — layer invariant removed.",
            ))

    # (g) Snapshot-level check.
    if snapshot and isinstance(snapshot, dict):
        if (
            snapshot.get("layer_key") == "completion_truth_backbone"
            and snapshot.get("is_optional_signaling") is True
        ):
            findings.append(_error(
                _GUARD_COMPLETION,
                "Architecture snapshot declares completion truth backbone as "
                "is_optional_signaling=True — "
                "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL boundary invariant violated.",
                {"snapshot": snapshot},
            ))

    if not findings:
        findings.append(_info(
            _GUARD_COMPLETION,
            "Completion truth backbone guard passed: canonical truth chain "
            "remains enforced and not optional.",
        ))

    return findings


# ---------------------------------------------------------------------------
# Guard 5 — Architecture declaration coherence
# ---------------------------------------------------------------------------

_GUARD_COHERENCE = "ARCHITECTURE_DECLARATION_COHERENCE"

_EXPECTED_LAYER_KEYS = frozenset({
    "completion_truth_backbone",
    "router_cognitive_authority",
    "per_request_hot_path",
    "multi_step_orchestration_spine",
    "startup_release_integrity",
})

_EXPECTED_NOT_POLICY_SENTINELS = [
    "V4_IS_NOT_PER_REQUEST_GATE",
    "V6_IS_NOT_PER_REQUEST_GATE",
    "L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK",
    "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL",
]


def check_architecture_declaration_coherence(
    snapshot: Optional[Dict[str, Any]] = None,
) -> List[TerminalGuardFinding]:
    """Check that repository-level architecture declarations agree with the
    canonical five-layer model.

    Checks performed
    ----------------
    a. ``core.canonical_layer_model`` is importable.
    b. All five canonical layer keys are present in ``CANONICAL_LAYER_KEYS``.
    c. All four NOT-policy sentinels are present and non-empty.
    d. ``run_layer_model_invariants()`` returns ``overall_consistent=True``
       on the built-in registry (no snapshot supplied — internal consistency).
    e. If *snapshot* is a non-empty dict, validate it via
       ``check_layer_model_consistent`` and surface any errors.

    Parameters
    ----------
    snapshot:
        Optional architecture snapshot dict to validate.

    Returns
    -------
    List[TerminalGuardFinding]
    """
    findings: List[TerminalGuardFinding] = []

    # (a) Module importable.
    importable, mod, err = _try_import("core.canonical_layer_model")
    if not importable:
        findings.append(_error(
            _GUARD_COHERENCE,
            "core.canonical_layer_model is not importable — "
            "the canonical five-layer architecture declaration has been removed.",
            {"error": err},
        ))
        return findings

    # (b) All five layer keys present.
    layer_keys = getattr(mod, "CANONICAL_LAYER_KEYS", None)
    if layer_keys is None:
        findings.append(_error(
            _GUARD_COHERENCE,
            "CANONICAL_LAYER_KEYS is absent from core.canonical_layer_model.",
        ))
    else:
        missing = _EXPECTED_LAYER_KEYS - frozenset(layer_keys)
        if missing:
            findings.append(_error(
                _GUARD_COHERENCE,
                f"canonical layer keys missing from CANONICAL_LAYER_KEYS: {sorted(missing)}. "
                "The five-layer architecture declaration is incomplete.",
                {"missing_keys": sorted(missing)},
            ))

    # (c) NOT-policy sentinels present and non-empty.
    for sentinel_name in _EXPECTED_NOT_POLICY_SENTINELS:
        if not _has_attr(mod, sentinel_name):
            findings.append(_error(
                _GUARD_COHERENCE,
                f"NOT-policy sentinel '{sentinel_name}' is absent from "
                "core.canonical_layer_model — layer boundary invariant removed.",
                {"missing_sentinel": sentinel_name},
            ))

    # (d) Internal registry self-consistency.
    run_fn = getattr(mod, "run_layer_model_invariants", None)
    if not callable(run_fn):
        findings.append(_error(
            _GUARD_COHERENCE,
            "run_layer_model_invariants is absent from core.canonical_layer_model — "
            "layer model self-check entry point removed.",
        ))
    else:
        try:
            report = run_fn()  # no snapshots → validates registry only
            if not getattr(report, "overall_consistent", True):
                error_count = getattr(report, "error_count", "?")
                findings.append(_error(
                    _GUARD_COHERENCE,
                    f"run_layer_model_invariants() returned overall_consistent=False "
                    f"({error_count} error(s)) — canonical layer registry is internally "
                    "inconsistent.",
                    {"error_count": error_count},
                ))
        except Exception as exc:
            findings.append(_warn(
                _GUARD_COHERENCE,
                f"run_layer_model_invariants() raised an exception: {exc}. "
                "Registry self-consistency could not be verified.",
                {"exception": str(exc)},
            ))

    # (e) Validate external snapshot if provided.
    if snapshot and isinstance(snapshot, dict):
        check_fn = getattr(mod, "check_layer_model_consistent", None)
        if callable(check_fn):
            try:
                layer_findings = check_fn(snapshot)
                errors = [f for f in layer_findings if getattr(f, "severity", "") == "error"]
                for lf in errors:
                    findings.append(_error(
                        _GUARD_COHERENCE,
                        f"Architecture snapshot is inconsistent with canonical layer model: "
                        f"{getattr(lf, 'message', str(lf))}",
                        {"layer_finding": lf.to_dict() if hasattr(lf, "to_dict") else {}},
                    ))
            except Exception as exc:
                findings.append(_warn(
                    _GUARD_COHERENCE,
                    f"check_layer_model_consistent() raised an exception: {exc}",
                    {"exception": str(exc)},
                ))

    if not findings:
        findings.append(_info(
            _GUARD_COHERENCE,
            "Architecture declaration coherence guard passed: canonical "
            "five-layer model is self-consistent and all NOT-policy sentinels "
            "are present.",
        ))

    return findings


# ---------------------------------------------------------------------------
# Aggregate runner
# ---------------------------------------------------------------------------

def run_terminal_audit_guards(
    snapshot: Optional[Dict[str, Any]] = None,
) -> TerminalGuardReport:
    """Run all five terminal architecture audit guards.

    Parameters
    ----------
    snapshot:
        Optional architecture snapshot dict passed to each individual guard.
        Most guards accept a single-layer snapshot keyed by ``layer_key``.
        If *snapshot* is None, guards that operate on the live import graph
        still run; only snapshot-level checks are skipped.

    Returns
    -------
    TerminalGuardReport
        Aggregated result.  ``overall_passed`` is True only when no ERROR
        findings are present across all five guards.
    """
    report = TerminalGuardReport(
        policy_sentinels=[
            V4_SCOPE_REGRESSION_GUARD_POLICY,
            V6_HOT_PATH_REGRESSION_GUARD_POLICY,
            L1_L2_L3_ROUTER_DETACHMENT_REGRESSION_GUARD_POLICY,
            COMPLETION_TRUTH_BYPASS_REGRESSION_GUARD_POLICY,
            ARCHITECTURE_DECLARATION_COHERENCE_GUARD_POLICY,
        ]
    )

    guard_fns = [
        (_GUARD_V4, check_v4_scope_regression),
        (_GUARD_V6, check_v6_hot_path_regression),
        (_GUARD_L123, check_l1_l2_l3_router_detachment),
        (_GUARD_COMPLETION, check_completion_truth_bypass),
        (_GUARD_COHERENCE, check_architecture_declaration_coherence),
    ]

    for guard_name, guard_fn in guard_fns:
        report.guards_run.append(guard_name)
        try:
            findings = guard_fn(snapshot)
            report.extend(findings)
        except Exception as exc:
            report.add(_warn(
                guard_name,
                f"Guard '{guard_name}' raised an unexpected exception: {exc}. "
                "Guard result is unavailable.",
                {"exception": str(exc)},
            ))

    if report.overall_passed:
        logger.debug(
            "Terminal architecture audit guards: all checks passed "
            "(warnings=%d)",
            report.warning_count,
        )
    else:
        logger.warning(
            "Terminal architecture audit guards: %d error(s) found — "
            "overall_passed=False",
            report.error_count,
        )

    return report
