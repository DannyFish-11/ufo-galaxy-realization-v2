#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/full_system_evidence_closure_gate.py
==========================================
V3 Full-System Evidence Closure Gate — evaluates whether evidence closure
is sufficient to advance the V3 baseline verdict for a given subsystem or
the full system.

Purpose
-------
This module answers a binary question that the V3 baseline report leaves
open-ended:

    *Is the current evidence closure state sufficient to GATE a release or
    merge?  What is the minimum closure level required, and is it met?*

It wraps :func:`~core.full_system_baseline_v3.build_v3_baseline_report`
and applies explicit **closure thresholds** to produce a pass/fail gate
decision with structured reasons.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  V3 EVIDENCE CLOSURE GATE  (this module)                            │
    │                                                                      │
    │  Consumes:                                                          │
    │    • core.full_system_baseline_v3.build_v3_baseline_report()        │
    │                                                                      │
    │  Applies closure thresholds per ClosureLevel                        │
    │                                                                      │
    │  Produces ClosureGateResult:                                        │
    │    • gate_passed   — bool                                           │
    │    • closure_level — required ClosureLevel                          │
    │    • verdict       — V3BaselineVerdict from the underlying report   │
    │    • fail_reasons  — list of reasons gate did not pass              │
    │    • subsystem_failures — per-subsystem list                        │
    └──────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Fail-conservative** — if the baseline report cannot be built, the gate
   fails with an explicit reason.
3. **Stable JSON** — :class:`ClosureGateResult` round-trips through
   ``to_dict`` / ``from_dict``.

Public API
----------
Enumerations::

    ClosureLevel

Data class::

    ClosureGateResult

Functions::

    evaluate_evidence_closure_gate(level) -> ClosureGateResult
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

logger = logging.getLogger("Galaxy.FullSystemEvidenceClosureGate")

__all__ = [
    "ClosureLevel",
    "ClosureGateResult",
    "evaluate_evidence_closure_gate",
]


class ClosureLevel(str, Enum):
    """Required closure level for the gate.

    ``minimum``
        All subsystems must be at least ``implemented_but_not_closed``.
        Android evidence absence is flagged as a warning but does not block.
        Suitable for draft / preview merges.

    ``standard``
        All subsystems must be at least ``implemented_but_not_closed``.
        Android evidence absence IS a blocking failure.
        Suitable for feature-branch merges to main.

    ``strict``
        All subsystems must be ``implemented_and_evidenced``.
        Android evidence must be present.
        No blocking gaps allowed.
        Suitable for production release gating.
    """

    minimum = "minimum"
    standard = "standard"
    strict = "strict"


@dataclass
class ClosureGateResult:
    """Result of the evidence closure gate evaluation.

    Attributes
    ----------
    gate_passed:
        True if all closure requirements for the requested level are met.
    closure_level:
        The :class:`ClosureLevel` that was evaluated.
    verdict:
        The underlying :attr:`V3BaselineVerdict` from the baseline report.
    fail_reasons:
        List of strings explaining why the gate did not pass.  Empty when
        ``gate_passed`` is True.
    subsystem_failures:
        Per-subsystem dict entries for subsystems that failed the gate.
    android_evidence_present:
        Mirrors the value from the underlying baseline report.
    """

    gate_passed: bool = False
    closure_level: str = ClosureLevel.standard.value
    verdict: str = "insufficient_evidence_to_conclude"
    fail_reasons: List[str] = field(default_factory=list)
    subsystem_failures: List[Dict[str, Any]] = field(default_factory=list)
    android_evidence_present: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_passed": self.gate_passed,
            "closure_level": self.closure_level,
            "verdict": self.verdict,
            "fail_reasons": list(self.fail_reasons),
            "subsystem_failures": list(self.subsystem_failures),
            "android_evidence_present": self.android_evidence_present,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def evaluate_evidence_closure_gate(
    level: ClosureLevel = ClosureLevel.standard,
) -> ClosureGateResult:
    """Evaluate the V3 evidence closure gate at the requested *level*.

    Parameters
    ----------
    level:
        One of :class:`ClosureLevel` — minimum, standard, or strict.

    Returns
    -------
    :class:`ClosureGateResult`
        ``gate_passed=True`` if all closure requirements are met.
    """
    from core.full_system_baseline_v3 import (  # noqa: PLC0415
        SubsystemState,
        V3BaselineVerdict,
        build_v3_baseline_report,
    )

    try:
        report = build_v3_baseline_report()
    except (ImportError, ModuleNotFoundError, AttributeError, RuntimeError) as exc:
        logger.error("V3 closure gate: could not build baseline report: %s", exc)
        return ClosureGateResult(
            gate_passed=False,
            closure_level=level.value,
            verdict="insufficient_evidence_to_conclude",
            fail_reasons=[f"baseline report build failed: {exc}"],
        )
    except Exception as exc:  # noqa: BLE001 — catch-all for unexpected but non-critical errors
        logger.error("V3 closure gate: unexpected error building baseline report: %s", exc)
        return ClosureGateResult(
            gate_passed=False,
            closure_level=level.value,
            verdict="insufficient_evidence_to_conclude",
            fail_reasons=[f"baseline report build failed unexpectedly: {exc}"],
        )

    fail_reasons: List[str] = []
    subsystem_failures: List[Dict[str, Any]] = []

    # --- Android evidence check ---
    android_present = report.android_evidence_present
    if level in (ClosureLevel.standard, ClosureLevel.strict) and not android_present:
        fail_reasons.append(
            "Android cross-repo evidence is absent or stale "
            "(policy: ANDROID_EVIDENCE_ABSENCE_DOWNGRADES_VERDICT_POLICY)"
        )

    # --- Subsystem state checks ---
    if level == ClosureLevel.minimum:
        required_min = SubsystemState.implemented_but_not_closed
    elif level == ClosureLevel.standard:
        required_min = SubsystemState.implemented_but_not_closed
    else:  # strict
        required_min = SubsystemState.implemented_and_evidenced

    for entry in report.subsystems:
        if entry.state.ordinal() < required_min.ordinal():
            fail_reasons.append(
                f"Subsystem '{entry.subsystem_id}' is {entry.state.value!r} "
                f"(required: at least {required_min.value!r}): {entry.rationale}"
            )
            subsystem_failures.append(entry.to_dict())

    # --- Verdict check for strict ---
    if level == ClosureLevel.strict:
        if report.overall_verdict != V3BaselineVerdict.closed_and_evidenced:
            fail_reasons.append(
                f"Overall verdict is {report.overall_verdict.value!r}; "
                f"strict level requires 'closed_and_evidenced'"
            )

    gate_passed = len(fail_reasons) == 0

    return ClosureGateResult(
        gate_passed=gate_passed,
        closure_level=level.value,
        verdict=report.overall_verdict.value,
        fail_reasons=fail_reasons,
        subsystem_failures=subsystem_failures,
        android_evidence_present=android_present,
    )
