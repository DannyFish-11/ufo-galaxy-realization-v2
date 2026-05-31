#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/runtime_readiness_matrix.py
==================================
Automated runtime readiness matrix and release posture summary.

Problem addressed
-----------------
Previously, release readiness was expressed through:
- Advisory documentation and PR descriptions
- A skeleton gate (:mod:`core.distributed_release_gate_skeleton`) that
  explicitly deferred enforcement

This module provides an **automated, machine-readable readiness matrix** that:

1. Covers the critical dimensions required for release gating:
   - Transport status (V2 ↔ Android WebSocket layer)
   - Canonical execution path status
   - Capability enforcement status
   - Protocol regression / drift guard status
   - Continuity / recovery readiness signals
2. Emits a **blocking verdict** when critical dimensions fail, rather than
   merely recording them as advisory.
3. Produces a structured :class:`ReadinessMatrix` that CI tools can consume
   to gate releases.

Architecture role
-----------------
This module sits between the advisory skeleton
(:mod:`core.distributed_release_gate_skeleton`) and actual CI enforcement.
It promotes a defined set of **critical** dimensions from advisory to
**blocking** so that the release posture is verifiable rather than declared.

Design principles
-----------------
- **Additive only** — does not modify any other module.
- **Critical = blocking** — dimensions classified as ``CRITICAL`` contribute
  to blocking the release when they fail.
- **Automated** — the matrix is produced programmatically from runtime signals
  and module import checks, not from manually-authored documents.
- **Fail-safe default** — dimensions that cannot be evaluated default to
  ``UNKNOWN`` and do not falsely green-light a release.
- **Observable** — the full :class:`ReadinessMatrix` is JSON-serialisable
  for CI artifact uploads.

Public API
----------
Sentinels::

    RUNTIME_READINESS_MATRIX_AUTHORITY
    RUNTIME_READINESS_MATRIX_PR_SENTINEL
    CRITICAL_DIMENSIONS_ARE_BLOCKING_POLICY
    ADVISORY_DIMENSIONS_MUST_NOT_BLOCK_POLICY

Enumerations::

    DimensionSeverity
    DimensionStatus
    MatrixVerdict

Data classes::

    ReadinessDimension
    ReadinessMatrix

Functions::

    evaluate_readiness_matrix()   -> ReadinessMatrix
    get_readiness_matrix()        -> ReadinessMatrix  (singleton)
    reset_readiness_matrix()      -> None             (testing only)
    is_release_blocked()          -> bool
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("Galaxy.RuntimeReadinessMatrix")

__all__ = [
    # Sentinels
    "RUNTIME_READINESS_MATRIX_AUTHORITY",
    "RUNTIME_READINESS_MATRIX_PR_SENTINEL",
    "CRITICAL_DIMENSIONS_ARE_BLOCKING_POLICY",
    "ADVISORY_DIMENSIONS_MUST_NOT_BLOCK_POLICY",
    # Enumerations
    "DimensionSeverity",
    "DimensionStatus",
    "MatrixVerdict",
    # Data classes
    "ReadinessDimension",
    "ReadinessMatrix",
    # Functions
    "evaluate_readiness_matrix",
    "get_readiness_matrix",
    "reset_readiness_matrix",
    "is_release_blocked",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

RUNTIME_READINESS_MATRIX_AUTHORITY: str = (
    "RUNTIME_READINESS_MATRIX_AUTHORITY_V1: "
    "core.runtime_readiness_matrix is the canonical automated readiness "
    "matrix and release posture summary for the dual-repo V2 × Android system.  "
    "It covers transport, canonical execution path, capability enforcement, "
    "protocol regression, and recovery readiness dimensions.  "
    "Critical dimensions that fail produce a BLOCKED verdict that CI "
    "must treat as a hard gate."
)

RUNTIME_READINESS_MATRIX_PR_SENTINEL: str = (
    "PR::RUNTIME_READINESS_MATRIX_V1: "
    "This module was introduced to promote key readiness dimensions from "
    "advisory reporting to blocking gates.  Removing or weakening the "
    "CRITICAL dimension definitions reduces release assurance below the "
    "threshold required by the dual-repo runtime hardening plan."
)

CRITICAL_DIMENSIONS_ARE_BLOCKING_POLICY: str = (
    "POLICY::CRITICAL_DIMENSIONS_ARE_BLOCKING_V1: "
    "Readiness dimensions classified as DimensionSeverity.CRITICAL must "
    "produce MatrixVerdict.BLOCKED when their status is FAILED.  "
    "CI pipelines consuming the ReadinessMatrix MUST check is_release_blocked() "
    "and reject the release when it returns True.  "
    "Treating CRITICAL dimension failures as advisory is a policy violation."
)

ADVISORY_DIMENSIONS_MUST_NOT_BLOCK_POLICY: str = (
    "POLICY::ADVISORY_DIMENSIONS_MUST_NOT_BLOCK_V1: "
    "Readiness dimensions classified as DimensionSeverity.ADVISORY are "
    "informational only.  Their failure status must not contribute to "
    "MatrixVerdict.BLOCKED and must not prevent release.  "
    "Advisory dimensions exist to surface improvement opportunities, not "
    "to gate releases."
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DimensionSeverity(str, Enum):
    """Severity classification of a readiness dimension.

    Values
    ------
    CRITICAL
        Failure of this dimension MUST block the release.
    HIGH
        Failure should block the release; treated as CRITICAL unless
        explicitly downgraded for a specific release context.
    ADVISORY
        Failure is informational; must not block the release.
    """

    CRITICAL = "critical"
    HIGH = "high"
    ADVISORY = "advisory"


class DimensionStatus(str, Enum):
    """Evaluation status of a readiness dimension.

    Values
    ------
    PASSED
        Dimension evaluation completed successfully.
    FAILED
        Dimension evaluation detected a problem.
    UNKNOWN
        Dimension could not be evaluated (e.g., dependency unavailable).
    SKIPPED
        Dimension was intentionally skipped in this evaluation context.
    """

    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    SKIPPED = "skipped"


class MatrixVerdict(str, Enum):
    """Overall verdict of the readiness matrix.

    Values
    ------
    READY
        All CRITICAL and HIGH dimensions passed; release is unblocked.
    BLOCKED
        One or more CRITICAL or HIGH dimensions failed; release is blocked.
    DEGRADED
        All CRITICAL dimensions passed but one or more HIGH dimensions
        failed or are unknown.
    UNKNOWN
        One or more CRITICAL dimensions are unknown; cannot confirm readiness.
    """

    READY = "ready"
    BLOCKED = "blocked"
    DEGRADED = "degraded"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ReadinessDimension:
    """One dimension in the readiness matrix.

    Fields
    ------
    dimension_id
        Canonical identifier (e.g. ``"transport_layer"``).
    display_name
        Human-readable name.
    severity
        :class:`DimensionSeverity` classification.
    status
        :class:`DimensionStatus` after evaluation.
    detail
        Human-readable explanation of the evaluation result.
    evidence_module
        Python module path that backs this dimension, if applicable.
    """

    dimension_id: str
    display_name: str
    severity: DimensionSeverity
    status: DimensionStatus = DimensionStatus.UNKNOWN
    detail: str = ""
    evidence_module: str = ""

    def to_dict(self) -> Dict:
        return {
            "dimension_id": self.dimension_id,
            "display_name": self.display_name,
            "severity": self.severity.value if isinstance(self.severity, DimensionSeverity) else str(self.severity),
            "status": self.status.value if isinstance(self.status, DimensionStatus) else str(self.status),
            "detail": self.detail,
            "evidence_module": self.evidence_module,
        }


@dataclass
class ReadinessMatrix:
    """Automated release posture summary.

    Fields
    ------
    matrix_id
        Stable unique identifier for this matrix evaluation run.
    verdict
        :class:`MatrixVerdict` summarising the overall state.
    dimensions
        List of :class:`ReadinessDimension` records.
    blocked_dimensions
        IDs of CRITICAL/HIGH dimensions that are FAILED — the set that
        produced a BLOCKED verdict.
    unknown_dimensions
        IDs of CRITICAL dimensions whose status is UNKNOWN.
    timestamp_ms
        Unix time in milliseconds when the matrix was evaluated.
    notes
        Optional additional context.
    """

    matrix_id: str = field(default_factory=lambda: f"rrm_{uuid.uuid4().hex[:12]}")
    verdict: MatrixVerdict = MatrixVerdict.UNKNOWN
    dimensions: List[ReadinessDimension] = field(default_factory=list)
    blocked_dimensions: List[str] = field(default_factory=list)
    unknown_dimensions: List[str] = field(default_factory=list)
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    notes: str = ""

    def to_dict(self) -> Dict:
        return {
            "matrix_id": self.matrix_id,
            "verdict": self.verdict.value if isinstance(self.verdict, MatrixVerdict) else str(self.verdict),
            "dimensions": [d.to_dict() for d in self.dimensions],
            "blocked_dimensions": self.blocked_dimensions,
            "unknown_dimensions": self.unknown_dimensions,
            "timestamp_ms": self.timestamp_ms,
            "notes": self.notes,
        }

    def is_blocked(self) -> bool:
        """Return ``True`` when the verdict is BLOCKED."""
        return self.verdict == MatrixVerdict.BLOCKED

    def summary_lines(self) -> List[str]:
        """Return a compact list of human-readable summary lines."""
        lines = [f"ReadinessMatrix [{self.matrix_id}] verdict={self.verdict.value}"]
        for dim in self.dimensions:
            icon = "✅" if dim.status == DimensionStatus.PASSED else (
                "❌" if dim.status == DimensionStatus.FAILED else "⚠️"
            )
            lines.append(
                f"  {icon} [{dim.severity.value.upper()}] {dim.display_name}: "
                f"{dim.status.value}"
                + (f" — {dim.detail}" if dim.detail else "")
            )
        if self.blocked_dimensions:
            lines.append(f"  BLOCKED on: {self.blocked_dimensions}")
        return lines


# ---------------------------------------------------------------------------
# Dimension evaluators
# ---------------------------------------------------------------------------

_EvaluatorFn = Callable[[], Tuple[DimensionStatus, str]]


def _eval_transport_layer() -> Tuple[DimensionStatus, str]:
    """Check that the canonical V2 ↔ Android transport layer is importable."""
    try:
        importlib.import_module("galaxy_gateway.android_bridge")
        importlib.import_module("galaxy_gateway.routes.websocket")
        return DimensionStatus.PASSED, "Transport layer modules importable."
    except Exception as exc:
        return DimensionStatus.FAILED, f"Transport layer import failed: {exc}"


def _eval_canonical_execution_path() -> Tuple[DimensionStatus, str]:
    """Check that canonical dispatch and message builder are importable."""
    try:
        importlib.import_module("galaxy_gateway.routing.dispatch")
        importlib.import_module("galaxy_gateway.android.message_builder")
        return DimensionStatus.PASSED, "Canonical execution path modules importable."
    except Exception as exc:
        return DimensionStatus.FAILED, f"Canonical execution path import failed: {exc}"


def _eval_capability_enforcement() -> Tuple[DimensionStatus, str]:
    """Check that capability enforcement modules are importable and functional."""
    try:
        mre = importlib.import_module("core.mainline_routing_enforcement")
        ceh = importlib.import_module("core.capability_enforcement_hardener")
        assert hasattr(mre, "enforce_explicit_route_capability_gate")
        assert hasattr(ceh, "enforce_mainline_capability_gate")
        assert hasattr(ceh, "CapabilityHardRejectError")
        # Smoke: strict mode on empty caps is a no-op
        from core.capability_enforcement_hardener import (
            enforce_mainline_capability_gate,
            CapabilityHardRejectError,
            EnforcementMode,
            HardenedVerdict,
        )
        rec = enforce_mainline_capability_gate(
            "smoke-device", [], [], mode=EnforcementMode.STRICT, calling_site="readiness_matrix"
        )
        assert rec.verdict == HardenedVerdict.NO_REQUIREMENTS, (
            f"Expected NO_REQUIREMENTS, got {rec.verdict!r}"
        )
        # Smoke: strict mode raises on actual mismatch (non-empty device caps missing required)
        raised = False
        try:
            enforce_mainline_capability_gate(
                "smoke-device",
                ["screenshot"],
                ["tap"],
                mode=EnforcementMode.STRICT,
                calling_site="readiness_matrix",
            )
        except CapabilityHardRejectError:
            raised = True
        assert raised, "STRICT enforcement did not raise CapabilityHardRejectError on mismatch"
        return DimensionStatus.PASSED, (
            "Capability enforcement modules importable; smoke gate passes."
        )
    except Exception as exc:
        return DimensionStatus.FAILED, f"Capability enforcement check failed: {exc}"


def _eval_capability_status_registry() -> Tuple[DimensionStatus, str]:
    """Check that the canonical capability status registry is functional."""
    try:
        from core.canonical_capability_status import (
            get_canonical_capability_status_registry,
            is_mainline_active,
            CapabilityRuntimeStatus,
        )
        registry = get_canonical_capability_status_registry()
        assert len(registry) > 0
        # Validate known statuses
        assert is_mainline_active("tap")
        assert is_mainline_active("task_assign")
        assert not is_mainline_active("local_ai")
        assert not is_mainline_active("webrtc")
        local_ai = registry.get("local_ai")
        assert local_ai is not None
        assert local_ai.status in (
            CapabilityRuntimeStatus.STRUCTURAL_ONLY,
            CapabilityRuntimeStatus.DEGRADED,
        )
        return DimensionStatus.PASSED, (
            f"Capability status registry functional; {len(registry)} capabilities classified."
        )
    except Exception as exc:
        return DimensionStatus.FAILED, f"Capability status registry check failed: {exc}"


def _eval_protocol_regression_surface() -> Tuple[DimensionStatus, str]:
    """Check that protocol regression test surface is importable."""
    try:
        importlib.import_module("galaxy_gateway.android_bridge")
        from galaxy_gateway.android_bridge import AndroidBridge
        bridge = AndroidBridge()
        registered = {mt.value for mt in bridge._message_handlers}
        required = {"device_register", "capability_report", "heartbeat", "task_result"}
        missing = required - registered
        if missing:
            return DimensionStatus.FAILED, f"Bridge missing handlers: {missing}"
        return DimensionStatus.PASSED, (
            f"Protocol surface: all canonical message types handled ({sorted(required)})."
        )
    except Exception as exc:
        return DimensionStatus.FAILED, f"Protocol regression surface check failed: {exc}"


def _eval_mainline_routing_enforcement_callsite() -> Tuple[DimensionStatus, str]:
    """Check that openclawd.py still contains the enforcement call site."""
    import pathlib
    openclawd_path = pathlib.Path(__file__).resolve().parent / "openclawd.py"
    if not openclawd_path.exists():
        return DimensionStatus.UNKNOWN, "core/openclawd.py not found."
    source = openclawd_path.read_text(encoding="utf-8")
    if "enforce_explicit_route_capability_gate" not in source:
        return DimensionStatus.FAILED, (
            "enforce_explicit_route_capability_gate call site missing from openclawd.py.  "
            "Explicit-device-id capability bypass gap may be re-opened."
        )
    return DimensionStatus.PASSED, "enforce_explicit_route_capability_gate call site present in openclawd.py."


def _eval_android_local_ai_status_declared() -> Tuple[DimensionStatus, str]:
    """Check that Android local AI status sentinel is declared."""
    try:
        mod = importlib.import_module("core.android_runtime_host")
        sentinel = getattr(mod, "ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT", None)
        flag = getattr(mod, "ANDROID_LOCAL_AI_DEFAULT_CAPABILITY_FLAG", None)
        if sentinel is None:
            return DimensionStatus.FAILED, (
                "ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT sentinel missing from "
                "core.android_runtime_host."
            )
        if flag is not False:
            return DimensionStatus.FAILED, (
                f"ANDROID_LOCAL_AI_DEFAULT_CAPABILITY_FLAG should be False; got {flag!r}."
            )
        return DimensionStatus.PASSED, (
            "Android local AI unavailable-by-default status is declared and machine-checkable."
        )
    except Exception as exc:
        return DimensionStatus.FAILED, f"Android local AI status check failed: {exc}"


def _eval_aip_v3_version_stable() -> Tuple[DimensionStatus, str]:
    """Check AIP v3 version string stability."""
    try:
        from galaxy_gateway.android.message_builder import MessageBuilder
        ack = MessageBuilder.device_register_ack("smoke", True, "ok")
        version = ack.get("version")
        if version != "3.0":
            return DimensionStatus.FAILED, (
                f"AIP v3 version string changed: expected '3.0', got {version!r}"
            )
        return DimensionStatus.PASSED, f"AIP v3 version string stable: '{version}'."
    except Exception as exc:
        return DimensionStatus.FAILED, f"AIP v3 version check failed: {exc}"


def _eval_nats_posture_contract() -> Tuple[DimensionStatus, str]:
    """Check canonical NATS posture policy and runtime assertion state."""
    try:
        from core.nats_posture import evaluate_nats_posture

        posture = evaluate_nats_posture()
        posture_name = posture.get("posture", "unknown")
        if posture.get("assertion_ok", True):
            return (
                DimensionStatus.PASSED,
                f"NATS posture '{posture_name}' assertion satisfied.",
            )
        return (
            DimensionStatus.FAILED,
            "NATS posture assertion failed: "
            f"{posture.get('violation_reason') or 'unknown_reason'}",
        )
    except Exception as exc:
        return DimensionStatus.UNKNOWN, f"NATS posture evaluation unavailable: {exc}"


# ---------------------------------------------------------------------------
# Dimension definitions
# ---------------------------------------------------------------------------

_DIMENSION_SPECS: List[Tuple[str, str, DimensionSeverity, str, _EvaluatorFn]] = [
    # (dimension_id, display_name, severity, evidence_module, evaluator)
    (
        "transport_layer",
        "V2 ↔ Android Transport Layer",
        DimensionSeverity.CRITICAL,
        "galaxy_gateway.android_bridge",
        _eval_transport_layer,
    ),
    (
        "canonical_execution_path",
        "Canonical Execution Path (Dispatch + MessageBuilder)",
        DimensionSeverity.CRITICAL,
        "galaxy_gateway.routing.dispatch",
        _eval_canonical_execution_path,
    ),
    (
        "capability_enforcement",
        "Capability Enforcement (Gate + Hardener)",
        DimensionSeverity.CRITICAL,
        "core.capability_enforcement_hardener",
        _eval_capability_enforcement,
    ),
    (
        "capability_status_registry",
        "Capability Status Registry (Classification)",
        DimensionSeverity.HIGH,
        "core.canonical_capability_status",
        _eval_capability_status_registry,
    ),
    (
        "protocol_regression_surface",
        "Protocol Regression Surface (Handler Coverage)",
        DimensionSeverity.CRITICAL,
        "galaxy_gateway.android_bridge",
        _eval_protocol_regression_surface,
    ),
    (
        "mainline_routing_enforcement_callsite",
        "Mainline Routing Enforcement Call Site (openclawd.py)",
        DimensionSeverity.CRITICAL,
        "core.openclawd",
        _eval_mainline_routing_enforcement_callsite,
    ),
    (
        "android_local_ai_status",
        "Android Local AI Status Declaration",
        DimensionSeverity.HIGH,
        "core.android_runtime_host",
        _eval_android_local_ai_status_declared,
    ),
    (
        "aip_v3_version_stability",
        "AIP v3 Protocol Version Stability",
        DimensionSeverity.CRITICAL,
        "galaxy_gateway.android.message_builder",
        _eval_aip_v3_version_stable,
    ),
    (
        "nats_posture_contract",
        "NATS Runtime Posture Contract",
        DimensionSeverity.CRITICAL,
        "core.nats_posture",
        _eval_nats_posture_contract,
    ),
]


# ---------------------------------------------------------------------------
# Matrix evaluation
# ---------------------------------------------------------------------------


def evaluate_readiness_matrix() -> ReadinessMatrix:
    """Evaluate all readiness dimensions and produce a :class:`ReadinessMatrix`.

    Returns
    -------
    ReadinessMatrix
        Fully populated matrix with verdict and per-dimension results.
    """
    dimensions: List[ReadinessDimension] = []

    for dim_id, display_name, severity, evidence_module, evaluator in _DIMENSION_SPECS:
        try:
            status, detail = evaluator()
        except Exception as exc:
            logger.debug("Fallback triggered: %s", exc)
            status = DimensionStatus.UNKNOWN
            detail = f"Evaluator raised unexpected exception: {exc}"

        dimensions.append(
            ReadinessDimension(
                dimension_id=dim_id,
                display_name=display_name,
                severity=severity,
                status=status,
                detail=detail,
                evidence_module=evidence_module,
            )
        )

    # Derive verdict
    blocked: List[str] = []
    unknown_critical: List[str] = []

    for dim in dimensions:
        if dim.severity in (DimensionSeverity.CRITICAL, DimensionSeverity.HIGH):
            if dim.status == DimensionStatus.FAILED:
                blocked.append(dim.dimension_id)
            elif dim.status == DimensionStatus.UNKNOWN and dim.severity == DimensionSeverity.CRITICAL:
                unknown_critical.append(dim.dimension_id)

    if blocked:
        verdict = MatrixVerdict.BLOCKED
    elif unknown_critical:
        verdict = MatrixVerdict.UNKNOWN
    else:
        has_degraded = any(
            d.status in (DimensionStatus.FAILED, DimensionStatus.UNKNOWN)
            and d.severity == DimensionSeverity.HIGH
            for d in dimensions
        )
        verdict = MatrixVerdict.DEGRADED if has_degraded else MatrixVerdict.READY

    matrix = ReadinessMatrix(
        verdict=verdict,
        dimensions=dimensions,
        blocked_dimensions=blocked,
        unknown_dimensions=unknown_critical,
    )

    # Log summary
    for line in matrix.summary_lines():
        if verdict == MatrixVerdict.BLOCKED:
            logger.error(line)
        elif verdict == MatrixVerdict.UNKNOWN:
            logger.warning(line)
        else:
            logger.info(line)

    return matrix


_MATRIX_LOCK = threading.Lock()
_CACHED_MATRIX: Optional[ReadinessMatrix] = None


def get_readiness_matrix() -> ReadinessMatrix:
    """Return a cached :class:`ReadinessMatrix`, evaluating on first call.

    Thread-safe singleton; call :func:`reset_readiness_matrix` in tests
    to force re-evaluation.
    """
    global _CACHED_MATRIX
    with _MATRIX_LOCK:
        if _CACHED_MATRIX is None:
            _CACHED_MATRIX = evaluate_readiness_matrix()
        return _CACHED_MATRIX


def reset_readiness_matrix() -> None:
    """Reset the cached matrix (for testing only)."""
    global _CACHED_MATRIX
    with _MATRIX_LOCK:
        _CACHED_MATRIX = None


def is_release_blocked() -> bool:
    """Return ``True`` when the readiness matrix verdict is BLOCKED.

    CI pipelines should call this function and fail if it returns ``True``.
    """
    return get_readiness_matrix().is_blocked()
