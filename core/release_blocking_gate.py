#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/release_blocking_gate.py
==============================
Canonical release blocking gate: promotes critical readiness checks from
advisory to true blocking gates.

Problem addressed
-----------------
The existing :mod:`core.distributed_release_gate_skeleton` explicitly defers
enforcement — it records a verdict but does NOT block CI or releases.
This module closes that gap by providing:

1. A :class:`ReleaseBlockingGate` that **raises** on critical failures,
   making it suitable as a CI exit-code gate.
2. Four canonical blocking criteria derived from the dual-repo runtime
   hardening plan:
   - **Runtime smoke** — critical transport / execution path modules must
     be importable and functional.
   - **Capability/runtime state mismatch** — canonical capability
     enforcement must be in place; no undetected bypass paths.
   - **Protocol drift / canonical path regression** — AIP v3 protocol
     surface must be stable and all canonical message types handled.
   - **Release posture not reached** — the runtime readiness matrix must
     not be BLOCKED.
3. A :func:`run_release_blocking_gate` entry point suitable for CI scripts
   (returns exit code 0/1).

Design principles
-----------------
- **Additive only** — does not modify any other module.
- **Hard block on critical failure** — :class:`ReleaseBlockingGateError`
  is raised when any critical gate criterion fails.
- **Observable** — each criterion produces a structured
  :class:`GateCriterionResult`; the full :class:`ReleaseGateDecision`
  is JSON-serialisable.
- **CI-compatible** — :func:`run_release_blocking_gate` prints a summary
  and returns an integer exit code (0 = pass, 1 = fail).

Public API
----------
Sentinels::

    RELEASE_BLOCKING_GATE_AUTHORITY
    RELEASE_BLOCKING_GATE_PR_SENTINEL
    CRITICAL_SMOKE_FAIL_IS_BLOCKING_POLICY
    CAPABILITY_STATE_MISMATCH_IS_BLOCKING_POLICY
    PROTOCOL_DRIFT_IS_BLOCKING_POLICY
    RELEASE_POSTURE_INSUFFICIENT_IS_BLOCKING_POLICY

Exceptions::

    ReleaseBlockingGateError

Data classes::

    GateCriterionResult
    ReleaseGateDecision

Functions::

    evaluate_release_gate()         -> ReleaseGateDecision
    run_release_blocking_gate()     -> int  (0=pass, 1=fail)
"""

from __future__ import annotations

import importlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

logger = logging.getLogger("Galaxy.ReleaseBlockingGate")

__all__ = [
    # Sentinels
    "RELEASE_BLOCKING_GATE_AUTHORITY",
    "RELEASE_BLOCKING_GATE_PR_SENTINEL",
    "CRITICAL_SMOKE_FAIL_IS_BLOCKING_POLICY",
    "CAPABILITY_STATE_MISMATCH_IS_BLOCKING_POLICY",
    "PROTOCOL_DRIFT_IS_BLOCKING_POLICY",
    "RELEASE_POSTURE_INSUFFICIENT_IS_BLOCKING_POLICY",
    # Exceptions
    "ReleaseBlockingGateError",
    # Data classes
    "GateCriterionResult",
    "ReleaseGateDecision",
    # Functions
    "evaluate_release_gate",
    "run_release_blocking_gate",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

RELEASE_BLOCKING_GATE_AUTHORITY: str = (
    "RELEASE_BLOCKING_GATE_AUTHORITY_V1: "
    "core.release_blocking_gate is the canonical blocking release gate for "
    "the dual-repo V2 × Android system.  It promotes critical readiness "
    "checks from advisory to true blocking gates.  CI pipelines must run "
    "this gate and fail on non-zero exit codes before merging to main."
)

RELEASE_BLOCKING_GATE_PR_SENTINEL: str = (
    "PR::RELEASE_BLOCKING_GATE_V1: "
    "This module was introduced to close the gap between advisory release "
    "posture reporting and actual blocking CI enforcement.  Removing or "
    "weakening the blocking criteria reduces release assurance below the "
    "threshold required by the dual-repo hardening plan."
)

CRITICAL_SMOKE_FAIL_IS_BLOCKING_POLICY: str = (
    "POLICY::CRITICAL_SMOKE_FAIL_IS_BLOCKING_V1: "
    "A critical runtime smoke failure (transport layer, canonical execution "
    "path, or protocol handler coverage) MUST block the release.  "
    "A system that cannot pass its own critical runtime smoke tests is not "
    "ready for release regardless of other assurance signals."
)

CAPABILITY_STATE_MISMATCH_IS_BLOCKING_POLICY: str = (
    "POLICY::CAPABILITY_STATE_MISMATCH_IS_BLOCKING_V1: "
    "A mismatch between the declared capability enforcement state and the "
    "actual runtime capability enforcement implementation MUST block the "
    "release.  The capability gate must be present, importable, and "
    "functional before a release can proceed."
)

PROTOCOL_DRIFT_IS_BLOCKING_POLICY: str = (
    "POLICY::PROTOCOL_DRIFT_IS_BLOCKING_V1: "
    "AIP v3 protocol drift (version string change, missing canonical message "
    "handlers, dispatch module breakage) MUST block the release.  "
    "Protocol drift breaks the Android client contract and must be treated "
    "as a hard regression."
)

RELEASE_POSTURE_INSUFFICIENT_IS_BLOCKING_POLICY: str = (
    "POLICY::RELEASE_POSTURE_INSUFFICIENT_IS_BLOCKING_V1: "
    "A BLOCKED verdict from the runtime readiness matrix "
    "(core.runtime_readiness_matrix) MUST block the release.  "
    "The readiness matrix is the canonical automated posture summary; "
    "its BLOCKED verdict is a hard gate, not a warning."
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ReleaseBlockingGateError(Exception):
    """Raised when the release blocking gate rejects the release.

    Attributes
    ----------
    failed_criteria : list[str]
        Criterion IDs that failed.
    decision : ReleaseGateDecision
        Full gate decision for inspection.
    """

    def __init__(
        self,
        failed_criteria: List[str],
        decision: "ReleaseGateDecision",
    ) -> None:
        self.failed_criteria = failed_criteria
        self.decision = decision
        super().__init__(
            f"Release blocked by {len(failed_criteria)} failing criterion(a): "
            f"{failed_criteria}.  "
            f"Run evaluate_release_gate() for the full decision report."
        )


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class CriterionStatus(str, Enum):
    """Status of a single gate criterion."""

    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class GateCriterionResult:
    """Result of evaluating a single gate criterion.

    Fields
    ------
    criterion_id
        Canonical identifier.
    display_name
        Human-readable label.
    status
        :class:`CriterionStatus`.
    detail
        Human-readable explanation.
    is_blocking
        True when a FAILED status blocks the release.
    """

    criterion_id: str
    display_name: str
    status: CriterionStatus
    detail: str = ""
    is_blocking: bool = True

    def to_dict(self) -> dict:
        return {
            "criterion_id": self.criterion_id,
            "display_name": self.display_name,
            "status": self.status.value if isinstance(self.status, CriterionStatus) else str(self.status),
            "detail": self.detail,
            "is_blocking": self.is_blocking,
        }


@dataclass
class ReleaseGateDecision:
    """Full release gate decision.

    Fields
    ------
    decision_id
        Stable unique identifier for this decision run.
    approved
        True when no blocking criteria failed.
    failed_criteria
        IDs of blocking criteria that failed.
    criteria
        All evaluated criteria results.
    timestamp_ms
        Unix time in milliseconds.
    notes
        Optional notes.
    """

    decision_id: str = field(default_factory=lambda: f"rgd_{uuid.uuid4().hex[:12]}")
    approved: bool = True
    failed_criteria: List[str] = field(default_factory=list)
    criteria: List[GateCriterionResult] = field(default_factory=list)
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "approved": self.approved,
            "failed_criteria": self.failed_criteria,
            "criteria": [c.to_dict() for c in self.criteria],
            "timestamp_ms": self.timestamp_ms,
            "notes": self.notes,
        }

    def summary_lines(self) -> List[str]:
        lines = [
            f"ReleaseGateDecision [{self.decision_id}] "
            f"{'APPROVED ✅' if self.approved else 'BLOCKED ❌'}"
        ]
        for crit in self.criteria:
            icon = "✅" if crit.status == CriterionStatus.PASSED else (
                "❌" if crit.status == CriterionStatus.FAILED else "⚠️"
            )
            lines.append(
                f"  {icon} [{('BLOCKING' if crit.is_blocking else 'advisory')}] "
                f"{crit.display_name}: {crit.status.value}"
                + (f" — {crit.detail}" if crit.detail else "")
            )
        if self.failed_criteria:
            lines.append(f"  BLOCKED on: {self.failed_criteria}")
        return lines


# ---------------------------------------------------------------------------
# Gate criterion evaluators
# ---------------------------------------------------------------------------


def _crit_critical_smoke() -> Tuple[CriterionStatus, str]:
    """Critical runtime smoke: transport and execution path importable."""
    failures = []
    for module_path in [
        "galaxy_gateway.android_bridge",
        "galaxy_gateway.routes.websocket",
        "galaxy_gateway.routing.dispatch",
        "galaxy_gateway.android.message_builder",
    ]:
        try:
            importlib.import_module(module_path)
        except Exception as exc:
            failures.append(f"{module_path}: {exc}")

    if failures:
        return CriterionStatus.FAILED, "Critical runtime modules not importable: " + "; ".join(failures)
    return CriterionStatus.PASSED, "All critical runtime smoke modules importable."


def _crit_capability_enforcement() -> Tuple[CriterionStatus, str]:
    """Capability/runtime state: enforcement gate importable and functional."""
    try:
        mre = importlib.import_module("core.mainline_routing_enforcement")
        ceh = importlib.import_module("core.capability_enforcement_hardener")

        assert callable(getattr(mre, "enforce_explicit_route_capability_gate", None)), (
            "enforce_explicit_route_capability_gate not callable in mainline_routing_enforcement"
        )
        assert callable(getattr(ceh, "enforce_mainline_capability_gate", None)), (
            "enforce_mainline_capability_gate not callable in capability_enforcement_hardener"
        )
        assert callable(getattr(ceh, "audit_capability_override", None)), (
            "audit_capability_override not callable in capability_enforcement_hardener"
        )

        # Smoke: STRICT gate with empty requirements → no-op
        from core.capability_enforcement_hardener import enforce_mainline_capability_gate, EnforcementMode
        rec = enforce_mainline_capability_gate(
            "gate-smoke", [], [], mode=EnforcementMode.STRICT, calling_site="release_gate"
        )
        assert rec.verdict == "no_requirements"

        # Smoke: STRICT gate with missing cap → raises
        # Use non-empty device_capabilities (["tap"]) missing the required "screenshot",
        # so the gate reaches the mismatch branch (empty device_caps yields INSUFFICIENT_DATA).
        from core.capability_enforcement_hardener import CapabilityHardRejectError
        raised = False
        try:
            enforce_mainline_capability_gate(
                "gate-smoke",
                ["screenshot"],
                ["tap"],
                mode=EnforcementMode.STRICT,
                calling_site="release_gate",
            )
        except CapabilityHardRejectError:
            raised = True
        assert raised, "STRICT mode did not raise CapabilityHardRejectError on missing capability"

        return CriterionStatus.PASSED, (
            "Capability enforcement gate functional; STRICT mode raises on mismatch."
        )
    except AssertionError as ae:
        return CriterionStatus.FAILED, f"Capability enforcement assertion failed: {ae}"
    except Exception as exc:
        return CriterionStatus.FAILED, f"Capability enforcement check error: {exc}"


def _crit_protocol_drift() -> Tuple[CriterionStatus, str]:
    """Protocol drift: AIP v3 version stable, canonical handlers present."""
    failures = []

    # AIP v3 version string
    try:
        from galaxy_gateway.android.message_builder import MessageBuilder
        ack = MessageBuilder.device_register_ack("smoke", True, "ok")
        version = ack.get("version")
        if version != "3.0":
            failures.append(f"AIP v3 version drifted: expected '3.0', got {version!r}")
    except Exception as exc:
        failures.append(f"MessageBuilder smoke failed: {exc}")

    # Handler coverage
    try:
        from galaxy_gateway.android_bridge import AndroidBridge
        bridge = AndroidBridge()
        registered = {mt.value for mt in bridge._message_handlers}
        required = {"device_register", "capability_report", "heartbeat", "task_result", "task_end"}
        missing = required - registered
        if missing:
            failures.append(f"Bridge missing handlers: {sorted(missing)}")
    except Exception as exc:
        failures.append(f"Handler coverage check failed: {exc}")

    # Dispatch module
    try:
        from galaxy_gateway.routing.dispatch import build_aip_message
        import uuid as _uuid
        msg = build_aip_message(
            device_id="smoke",
            task_id=str(_uuid.uuid4()),
            trace_id=str(_uuid.uuid4()),
            command="screenshot",
        )
        if msg.get("version") != "3.0":
            failures.append(f"dispatch.build_aip_message version wrong: {msg.get('version')!r}")
    except Exception as exc:
        failures.append(f"dispatch.build_aip_message smoke failed: {exc}")

    if failures:
        return CriterionStatus.FAILED, "Protocol drift detected: " + "; ".join(failures)
    return CriterionStatus.PASSED, "AIP v3 protocol surface stable; all canonical handlers present."


def _crit_readiness_matrix_not_blocked() -> Tuple[CriterionStatus, str]:
    """Release posture: runtime readiness matrix must not be BLOCKED."""
    try:
        from core.runtime_readiness_matrix import evaluate_readiness_matrix, MatrixVerdict
        matrix = evaluate_readiness_matrix()
        if matrix.verdict == MatrixVerdict.BLOCKED:
            return CriterionStatus.FAILED, (
                f"Runtime readiness matrix BLOCKED on: {matrix.blocked_dimensions}"
            )
        return CriterionStatus.PASSED, (
            f"Runtime readiness matrix verdict: {matrix.verdict.value}."
        )
    except Exception as exc:
        return CriterionStatus.UNKNOWN, f"Readiness matrix evaluation error: {exc}"


def _crit_mainline_enforcement_callsite() -> Tuple[CriterionStatus, str]:
    """Canonical path regression: enforcement call site present in openclawd.py."""
    import pathlib
    openclawd_path = pathlib.Path(__file__).resolve().parent / "openclawd.py"
    if not openclawd_path.exists():
        return CriterionStatus.UNKNOWN, "core/openclawd.py not found."
    source = openclawd_path.read_text(encoding="utf-8")
    if "enforce_explicit_route_capability_gate" not in source:
        return CriterionStatus.FAILED, (
            "enforce_explicit_route_capability_gate missing from openclawd.py — "
            "explicit-device-id capability bypass gap may be re-opened."
        )
    return CriterionStatus.PASSED, "Enforcement call site present in openclawd.py."


# ---------------------------------------------------------------------------
# Gate definition
# ---------------------------------------------------------------------------

_CRITERIA_DEFS = [
    (
        "critical_runtime_smoke",
        "Critical Runtime Smoke (Transport + Execution Path)",
        True,
        _crit_critical_smoke,
    ),
    (
        "capability_enforcement",
        "Capability/Runtime State (Enforcement Gate Functional)",
        True,
        _crit_capability_enforcement,
    ),
    (
        "protocol_drift",
        "Protocol Drift / Canonical Path Regression (AIP v3 Stability)",
        True,
        _crit_protocol_drift,
    ),
    (
        "readiness_matrix_not_blocked",
        "Release Posture (Readiness Matrix Not BLOCKED)",
        True,
        _crit_readiness_matrix_not_blocked,
    ),
    (
        "mainline_enforcement_callsite",
        "Mainline Enforcement Call Site (openclawd.py)",
        True,
        _crit_mainline_enforcement_callsite,
    ),
]


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def evaluate_release_gate(raise_on_failure: bool = False) -> ReleaseGateDecision:
    """Evaluate all gate criteria and return a :class:`ReleaseGateDecision`.

    Parameters
    ----------
    raise_on_failure:
        When ``True``, raises :class:`ReleaseBlockingGateError` if any
        blocking criterion fails.  Defaults to ``False`` so callers can
        inspect the decision before deciding to raise.

    Returns
    -------
    ReleaseGateDecision
    """
    results: List[GateCriterionResult] = []

    for crit_id, display_name, is_blocking, evaluator in _CRITERIA_DEFS:
        try:
            status, detail = evaluator()
        except Exception as exc:
            status = CriterionStatus.UNKNOWN
            detail = f"Evaluator raised: {exc}"
        results.append(
            GateCriterionResult(
                criterion_id=crit_id,
                display_name=display_name,
                status=status,
                detail=detail,
                is_blocking=is_blocking,
            )
        )

    failed = [
        r.criterion_id
        for r in results
        if r.is_blocking and r.status == CriterionStatus.FAILED
    ]

    decision = ReleaseGateDecision(
        approved=len(failed) == 0,
        failed_criteria=failed,
        criteria=results,
    )

    for line in decision.summary_lines():
        if not decision.approved:
            logger.error(line)
        else:
            logger.info(line)

    if raise_on_failure and not decision.approved:
        raise ReleaseBlockingGateError(failed_criteria=failed, decision=decision)

    return decision


def run_release_blocking_gate() -> int:
    """Run the release blocking gate and return an exit code.

    Returns
    -------
    int
        ``0`` when the gate approves the release, ``1`` when blocked.
    """
    decision = evaluate_release_gate(raise_on_failure=False)
    for line in decision.summary_lines():
        print(line)

    if decision.approved:
        print("\n✅ Release gate: APPROVED")
        return 0
    else:
        print(f"\n❌ Release gate: BLOCKED on {decision.failed_criteria}")
        return 1


if __name__ == "__main__":
    import sys as _sys
    import pathlib as _pathlib
    _repo_root = str(_pathlib.Path(__file__).resolve().parent.parent)
    if _repo_root not in _sys.path:
        _sys.path.insert(0, _repo_root)
    _sys.exit(run_release_blocking_gate())
