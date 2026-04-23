#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/truth_conflict_enforcement.py
====================================
PR-J — Truth Conflict Enforcement and Canonical Truth Convergence Hardening.

Problem addressed
-----------------
The Galaxy V2 runtime is moving toward a single-authority orchestration and
device-truth model.  Detecting conflict or cataloguing divergence is helpful,
but insufficient if legacy-compatible or parallel truth paths can still reassert
practical write influence over canonical truth surfaces.

This means the system can appear converged while still remaining vulnerable to
truth regression, ambiguous ownership, or drift between canonical state and
compatibility-era writable paths.  In a durable orchestration runtime, truth
convergence must be operationally hardened, not only architecturally intended.

This module strengthens truth conflict enforcement and canonical truth
convergence by:

1. **Declaring canonical write authority per truth surface** — explicit
   ownership records for device, task, and session truth surfaces so any
   deviation is machine-detectable rather than only architecturally implied.

2. **Providing active write-ordering guards** — call-site helpers that enforce
   the invariant that compat/mirror writes must always be preceded by a
   canonical write to the authoritative source (UDM / CanonicalTask /
   CanonicalSessionTruthRuntime).

3. **Asserting no-parallel-authority** — functions that actively block or warn
   when a module outside the canonical write authority attempts to assert
   primary write power over a truth surface.

4. **Providing a convergence health snapshot** — a JSON-serialisable snapshot
   that CI, operator tooling, and regression gates can assert.

5. **Defining structured regression-detection policy** — explicit sentinels
   for truth regression events so log aggregation and CI can alert on
   conflict relapse rather than only observing it after the fact.

Design principles
-----------------
- **Additive only** — does not modify any existing module.  Provides
  vocabulary, guard functions, and a queryable enforcement surface.
- **Non-blocking by default** — guard helpers log and return a verdict;
  they do not raise unless ``strict=True`` is requested.
- **Machine-checkable** — all sentinels and IDs are importable constants
  that CI, tests, and diagnostic endpoints can assert.
- **Explicit over implicit** — every allowed compat write path is documented;
  unlisted write influence constitutes a policy violation.
- **Complement, not replace** — builds on
  :mod:`core.truth_source_lock` (write SSOT declaration),
  :mod:`core.truth_integration_layer` (canonical read resolution), and
  :mod:`core.compat_fallback_authority_guard` (compat influence registry).

Authority hierarchy (quick reference)
--------------------------------------
Device truth:
    Write SSOT  → ``UnifiedDeviceManager`` (UDM)
    Compat mirror → ``core.routes._shared.registered_devices``
                    (COMPAT_MIRROR_WRITE, always secondary)

Task truth:
    Write SSOT  → ``core.canonical_task.CanonicalTask`` /
                  ``core.task_graph_runtime.CanonicalTaskRuntime``
    Compat legacy → ``core.routes._shared.task_queue``
                    (read-only compat surface; no primary write authority)

Session truth:
    Write SSOT  → ``core.canonical_session_truth.CanonicalSessionTruthRuntime``
    Compat fallback → session registry stale-state paths
                      (bounded read-only; must not assert canonical session state)

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`TRUTH_CONFLICT_ENFORCEMENT_IS_AUTHORITY`
:data:`TRUTH_CONFLICT_ENFORCEMENT_PRJ_SENTINEL`
:data:`CANONICAL_WRITE_PRECEDES_COMPAT_WRITE_POLICY`
:data:`NO_PARALLEL_TRUTH_AUTHORITY_POLICY`
:data:`COMPAT_TRUTH_WRITE_MUST_BE_MIRROR_ONLY_POLICY`
:data:`TRUTH_REGRESSION_DETECTION_POLICY`
:data:`TRUTH_CONFLICT_RELAPSE_MUST_BE_FAIL_FAST_POLICY`

Enums
~~~~~
:class:`TruthSurface`
:class:`TruthConflictVerdict`

Data classes
~~~~~~~~~~~~
:class:`TruthOwnershipRecord`
:class:`TruthConflictRecord`
:class:`TruthConflictEnforcementSnapshot`

Functions
~~~~~~~~~
:func:`get_truth_ownership_registry`
:func:`get_write_authority_for_surface`
:func:`assert_canonical_write_precedes_compat_write`
:func:`assert_no_parallel_write_authority`
:func:`check_compat_write_is_mirror_only`
:func:`build_truth_conflict_enforcement_snapshot`
:func:`is_truth_convergence_healthy`
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.TruthConflictEnforcement")

__all__ = [
    # Sentinels
    "TRUTH_CONFLICT_ENFORCEMENT_IS_AUTHORITY",
    "TRUTH_CONFLICT_ENFORCEMENT_PRJ_SENTINEL",
    "CANONICAL_WRITE_PRECEDES_COMPAT_WRITE_POLICY",
    "NO_PARALLEL_TRUTH_AUTHORITY_POLICY",
    "COMPAT_TRUTH_WRITE_MUST_BE_MIRROR_ONLY_POLICY",
    "TRUTH_REGRESSION_DETECTION_POLICY",
    "TRUTH_CONFLICT_RELAPSE_MUST_BE_FAIL_FAST_POLICY",
    # Enums
    "TruthSurface",
    "TruthConflictVerdict",
    # Data classes
    "TruthOwnershipRecord",
    "TruthConflictRecord",
    "TruthConflictEnforcementSnapshot",
    # Functions
    "get_truth_ownership_registry",
    "get_write_authority_for_surface",
    "assert_canonical_write_precedes_compat_write",
    "assert_no_parallel_write_authority",
    "check_compat_write_is_mirror_only",
    "build_truth_conflict_enforcement_snapshot",
    "is_truth_convergence_healthy",
]

# ===========================================================================
# Authority sentinels
# ===========================================================================

TRUTH_CONFLICT_ENFORCEMENT_IS_AUTHORITY: str = (
    "TRUTH_CONFLICT_ENFORCEMENT_IS_AUTHORITY::"
    "core.truth_conflict_enforcement is the PR-J runtime truth conflict "
    "enforcement module for the Galaxy canonical runtime.  It declares "
    "canonical write authority per truth surface, provides active write-ordering "
    "guards, blocks parallel authority claims, and exposes a convergence health "
    "snapshot.  Compat/mirror writes are only permitted as secondary operations "
    "that follow a successful canonical write."
)

TRUTH_CONFLICT_ENFORCEMENT_PRJ_SENTINEL: str = (
    "TRUTH_CONFLICT_ENFORCEMENT_PRJ_SENTINEL::"
    "package=PR-J::profile=truth-conflict-enforcement-v1::"
    "module=core.truth_conflict_enforcement"
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_WRITE_PRECEDES_COMPAT_WRITE_POLICY: str = (
    "POLICY::CANONICAL_WRITE_PRECEDES_COMPAT_WRITE_V1: "
    "For every truth surface (device, task, session), a write to the canonical "
    "authority (UDM / CanonicalTask / CanonicalSessionTruthRuntime) MUST precede "
    "any write to a compat/mirror surface.  A compat write that is not preceded "
    "by a successful canonical write is a policy violation that enables the compat "
    "surface to carry state the canonical authority does not recognise, creating "
    "a dual-truth condition.  All compat write sites must import and honour "
    "COMPAT_MIRROR_WRITE from core.routes._shared as the explicit marker of "
    "secondary write intent."
)

NO_PARALLEL_TRUTH_AUTHORITY_POLICY: str = (
    "POLICY::NO_PARALLEL_TRUTH_AUTHORITY_V1: "
    "Only the declared canonical write authority for a truth surface may claim "
    "primary write power over that surface.  Any module outside the declared "
    "canonical write chain that performs unconditional writes to a truth surface "
    "creates a parallel authority — a policy violation that must be bounded or "
    "retired.  Compat paths may only mirror (secondary write) or read; they must "
    "never be the primary write source for a canonical truth surface."
)

COMPAT_TRUTH_WRITE_MUST_BE_MIRROR_ONLY_POLICY: str = (
    "POLICY::COMPAT_TRUTH_WRITE_MUST_BE_MIRROR_ONLY_V1: "
    "Writes to a compat truth surface (e.g. registered_devices compat cache) "
    "are mirror-only operations.  They replicate a state already committed by "
    "the canonical authority; they do not assert new truth.  Any code path that "
    "writes to a compat surface without a prior canonical write is asserting "
    "independent truth authority and must be refactored.  Mirror writes must be "
    "annotated with the COMPAT_MIRROR_WRITE sentinel from core.routes._shared."
)

TRUTH_REGRESSION_DETECTION_POLICY: str = (
    "POLICY::TRUTH_REGRESSION_DETECTION_V1: "
    "Truth regressions — situations where a compat or legacy surface re-acquires "
    "effective write authority over a truth surface after having been demoted — "
    "must be actively detected and logged as structured events with a "
    "TRUTH_REGRESSION prefix.  Regression events must be reviewable in logs and "
    "exposed via the TruthConflictEnforcementSnapshot so operators and CI can "
    "identify regression trends before they solidify into dual-authority states."
)

TRUTH_CONFLICT_RELAPSE_MUST_BE_FAIL_FAST_POLICY: str = (
    "POLICY::TRUTH_CONFLICT_RELAPSE_MUST_BE_FAIL_FAST_V1: "
    "When a truth conflict relapse is detected at a guarded decision site — "
    "i.e. a compat path is performing a write that would create parallel truth — "
    "the guard must either raise (when strict=True) or emit a structured "
    "TRUTH_CONFLICT_RELAPSE warning that is visible to both log aggregation and "
    "the enforcement snapshot.  Silent tolerance of truth relapses is explicitly "
    "prohibited."
)


# ===========================================================================
# Enumerations
# ===========================================================================


class TruthSurface(str, Enum):
    """Canonical truth surface identifiers for the Galaxy runtime.

    device
        Device identity, registration state, online/offline status, and
        capability truth.  Write SSOT: ``UnifiedDeviceManager`` (UDM).

    task
        Task lifecycle state, dispatch history, and result truth.
        Write SSOT: ``CanonicalTask`` / ``CanonicalTaskRuntime``.

    session
        Session lifecycle, continuity contract, and result merge truth.
        Write SSOT: ``CanonicalSessionTruthRuntime``.
    """

    device = "device"
    task = "task"
    session = "session"


class TruthConflictVerdict(str, Enum):
    """Result of a truth conflict enforcement check.

    CANONICAL_AUTHORITY_CONFIRMED
        The canonical write authority is confirmed as the primary writer for
        this truth surface.  No parallel or compat write conflict detected.

    COMPAT_MIRROR_WRITE_VALID
        A compat/mirror write was detected but it correctly follows a canonical
        write.  This is the expected valid compat path.

    CANONICAL_WRITE_MISSING
        A compat write was attempted without a confirmed prior canonical write.
        This is a policy violation — the compat surface would carry novel truth
        not present in the canonical authority.

    PARALLEL_AUTHORITY_DETECTED
        A module outside the declared canonical write chain is performing an
        unconditional write to the truth surface.  This constitutes a parallel
        truth authority and is a policy violation.

    TRUTH_REGRESSION_DETECTED
        A compat or legacy surface that was previously demoted from write
        authority has re-acquired effective write influence over a truth surface.
        This is a truth regression event.

    UNKNOWN
        Unable to determine the write authority posture for this site.
        Treated as a monitoring gap.
    """

    CANONICAL_AUTHORITY_CONFIRMED = "canonical_authority_confirmed"
    COMPAT_MIRROR_WRITE_VALID = "compat_mirror_write_valid"
    CANONICAL_WRITE_MISSING = "canonical_write_missing"
    PARALLEL_AUTHORITY_DETECTED = "parallel_authority_detected"
    TRUTH_REGRESSION_DETECTED = "truth_regression_detected"
    UNKNOWN = "unknown"


# ===========================================================================
# Data classes
# ===========================================================================


@dataclass(frozen=True)
class TruthOwnershipRecord:
    """Canonical write authority declaration for a single truth surface.

    Declares which module owns write authority for a truth surface, which
    compat/mirror paths are explicitly allowed (as secondary-only writers),
    and how a reviewer can verify canonical ownership at runtime.
    """

    surface: TruthSurface
    """The truth surface this record governs."""

    canonical_write_authority: str
    """Fully-qualified module path of the canonical write authority (SSOT)."""

    allowed_compat_mirror_paths: List[str]
    """
    Module paths that are explicitly permitted to perform mirror-only writes
    to compat surfaces for this truth surface.  These paths must always write
    to the canonical authority FIRST; compat writes are strictly secondary.
    """

    prohibited_write_paths: List[str]
    """
    Module paths that must NOT write to this truth surface.  Any write from
    these paths constitutes a parallel authority violation.
    """

    reviewer_verification: str
    """
    Human-readable description of how a reviewer can verify canonical write
    authority is enforced at runtime (e.g. log events, sentinel assertions).
    """

    pr_reference: str = ""
    """PR where this ownership record was established or last hardened."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface": self.surface.value,
            "canonical_write_authority": self.canonical_write_authority,
            "allowed_compat_mirror_paths": list(self.allowed_compat_mirror_paths),
            "prohibited_write_paths": list(self.prohibited_write_paths),
            "reviewer_verification": self.reviewer_verification,
            "pr_reference": self.pr_reference,
        }


@dataclass
class TruthConflictRecord:
    """A single detected truth conflict or write-ordering violation."""

    surface: TruthSurface
    """The truth surface where the conflict was detected."""

    verdict: TruthConflictVerdict
    """Outcome classification of the conflict."""

    caller_module: str
    """The module/path that triggered the conflict check."""

    canonical_authority: str
    """Declared canonical write authority for this surface."""

    message: str = ""
    """Structured log message describing the conflict."""

    timestamp: float = field(default_factory=time.time)
    """Wall-clock time when the conflict was detected."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface": self.surface.value,
            "verdict": self.verdict.value,
            "caller_module": self.caller_module,
            "canonical_authority": self.canonical_authority,
            "message": self.message,
            "timestamp": self.timestamp,
        }


@dataclass
class TruthConflictEnforcementSnapshot:
    """Aggregate snapshot of the truth conflict enforcement posture.

    Suitable for CI consumption, operator tooling, and regression gate
    assertions.
    """

    generated_at: float
    """Wall-clock time when this snapshot was generated."""

    total_surfaces: int
    """Total number of truth surfaces in the ownership registry."""

    surfaces_with_declared_authority: int
    """Number of surfaces that have an explicit canonical write authority."""

    parallel_authority_violations_detected: int
    """Number of active parallel authority violations (should be 0 in healthy runtime)."""

    compat_write_ordering_violations_detected: int
    """
    Number of compat write ordering violations detected since last snapshot.
    Should be 0 in healthy runtime.
    """

    truth_regression_events_detected: int
    """Number of truth regression events detected since last snapshot."""

    convergence_healthy: bool
    """
    True when no parallel authority violations, no compat write ordering
    violations, and no truth regression events have been detected.
    """

    policy_sentinels: List[str] = field(default_factory=list)
    """Importable policy sentinel strings governing truth convergence."""

    surface_summaries: List[Dict[str, Any]] = field(default_factory=list)
    """Per-surface canonical write authority declarations."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "total_surfaces": self.total_surfaces,
            "surfaces_with_declared_authority": self.surfaces_with_declared_authority,
            "parallel_authority_violations_detected": (
                self.parallel_authority_violations_detected
            ),
            "compat_write_ordering_violations_detected": (
                self.compat_write_ordering_violations_detected
            ),
            "truth_regression_events_detected": self.truth_regression_events_detected,
            "convergence_healthy": self.convergence_healthy,
            "policy_sentinels": list(self.policy_sentinels),
            "surface_summaries": list(self.surface_summaries),
        }


# ===========================================================================
# Truth ownership registry
# ===========================================================================

_TRUTH_OWNERSHIP_REGISTRY: List[TruthOwnershipRecord] = [
    # -------------------------------------------------------------------------
    # Device truth surface
    # -------------------------------------------------------------------------
    TruthOwnershipRecord(
        surface=TruthSurface.device,
        canonical_write_authority=(
            "core.unified.device_manager.UnifiedDeviceManager"
        ),
        allowed_compat_mirror_paths=[
            "core.routes.devices (COMPAT_MIRROR_WRITE after UDM write)",
            "core.routes.compat (COMPAT_MIRROR_WRITE after UDM write)",
            "core.repo_coordinator.RepoCoordinator.register_android_device "
            "(delegates canonical write to UDM first)",
        ],
        prohibited_write_paths=[
            "core.routes._shared.registered_devices (compat cache — mirror-only, "
            "must not be primary write source)",
            "galaxy_gateway.orchestrator.task_orchestrator (legacy orchestrator — "
            "must not write device truth directly)",
            "core.device_participation (enrichment-only — must not write "
            "registered/online/routable independently of Layer-1 readiness)",
        ],
        reviewer_verification=(
            "Verify in logs: every write to registered_devices is preceded by a "
            "UDM write in the same request handler.  Look for 'UDM 写入' log "
            "entries immediately before 'COMPAT_MIRROR_WRITE' entries.  The "
            "COMPAT_MIRROR_WRITE sentinel in core.routes._shared is the machine-"
            "checkable marker that this invariant is declared at every write site.  "
            "truth_source_lock.DEVICE_WRITE_SSOT == "
            "'core.unified.device_manager.UnifiedDeviceManager' is the "
            "authoritative declaration."
        ),
        pr_reference="PR-J / PR-1 (truth_source_lock) / PR-3 (compat demotion)",
    ),
    # -------------------------------------------------------------------------
    # Task truth surface
    # -------------------------------------------------------------------------
    TruthOwnershipRecord(
        surface=TruthSurface.task,
        canonical_write_authority=(
            "core.canonical_task.CanonicalTask / "
            "core.task_graph_runtime.CanonicalTaskRuntime"
        ),
        allowed_compat_mirror_paths=[
            "core.canonical_task_dispatch_chain.CanonicalTaskDispatchChain "
            "(dispatches through CanonicalTask)",
            "core.command_router.CommandRouter.route_envelope() "
            "(canonical task ingress — creates CanonicalTask at boundary)",
        ],
        prohibited_write_paths=[
            "core.routes._shared.task_queue (compat routing only — must not "
            "be used as a truth source for task state)",
            "galaxy_gateway.task_router.TaskRouter (retired — must not write "
            "task truth; INV-001 enforcement)",
            "legacy task status mutation outside CanonicalTaskRuntime",
        ],
        reviewer_verification=(
            "Verify that adapt_to_canonical_task() is called at every API ingress "
            "before any routing or status decision.  Task status queries must use "
            "CanonicalTaskRuntime, not the legacy task_queue.  "
            "INV-001 (runtime_invariant_enforcement) documents CommandRouter as "
            "the sole task ingress; INFL-006 (compat_fallback_authority_guard) "
            "documents the legacy task_queue bounding."
        ),
        pr_reference="PR-J / PR-507 (task canonical) / PR-8 INV-001",
    ),
    # -------------------------------------------------------------------------
    # Session truth surface
    # -------------------------------------------------------------------------
    TruthOwnershipRecord(
        surface=TruthSurface.session,
        canonical_write_authority=(
            "core.canonical_session_truth.CanonicalSessionTruthRuntime"
        ),
        allowed_compat_mirror_paths=[
            "core.attached_runtime_session.AttachedRuntimeSession "
            "(canonical session lifecycle — write-through to CanonicalSessionTruthRuntime)",
            "core.hybrid_orchestration_continuity "
            "(continuity writes go through CanonicalSessionTruthRuntime)",
        ],
        prohibited_write_paths=[
            "Stale session context writes that bypass AttachedSessionRegistry "
            "(INFL-007 / INV-003 enforcement — stale context must not alter "
            "session state transitions)",
            "Legacy session store writes that do not route through "
            "CanonicalSessionTruthRuntime",
        ],
        reviewer_verification=(
            "Verify that record_session_truth() is the only path for writing "
            "CanonicalSessionTruthRecord entries.  Session state transitions must "
            "go through AttachedRuntimeSession.attach/detach/reconnect.  "
            "INV-003 (runtime_invariant_enforcement) documents this invariant.  "
            "canonical_session_truth.SESSION_TRUTH_SOURCE_MUST_BE_CANONICAL_POLICY "
            "enforces truth_source value governance."
        ),
        pr_reference="PR-J / PR-4 (canonical_session_truth) / PR-8 INV-003",
    ),
]


# ===========================================================================
# Runtime conflict tracking
# ===========================================================================

# In-process ring buffer for recent conflict records (diagnostic only).
# Not persisted across process restarts; use durable audit store for long-term.
_MAX_CONFLICT_RING_BUFFER: int = 128
_conflict_ring_buffer: List[TruthConflictRecord] = []


def _record_conflict(record: TruthConflictRecord) -> None:
    """Append a conflict record to the in-process ring buffer."""
    if len(_conflict_ring_buffer) >= _MAX_CONFLICT_RING_BUFFER:
        _conflict_ring_buffer.pop(0)
    _conflict_ring_buffer.append(record)


def _get_recent_conflicts() -> List[TruthConflictRecord]:
    """Return a copy of the in-process conflict ring buffer."""
    return list(_conflict_ring_buffer)


# ===========================================================================
# Query functions
# ===========================================================================


def get_truth_ownership_registry() -> List[TruthOwnershipRecord]:
    """Return the full truth ownership registry.

    Returns
    -------
    list[TruthOwnershipRecord]
        All registered ownership records in surface-definition order.
    """
    return list(_TRUTH_OWNERSHIP_REGISTRY)


def get_write_authority_for_surface(surface: TruthSurface) -> Optional[TruthOwnershipRecord]:
    """Return the ownership record for *surface*, or ``None``.

    Parameters
    ----------
    surface:
        The truth surface to look up.

    Returns
    -------
    TruthOwnershipRecord or None
    """
    return next(
        (r for r in _TRUTH_OWNERSHIP_REGISTRY if r.surface == surface),
        None,
    )


# ===========================================================================
# Active enforcement guards
# ===========================================================================


def assert_canonical_write_precedes_compat_write(
    surface: TruthSurface,
    *,
    canonical_write_confirmed: bool,
    compat_path: str = "",
    context: str = "",
    strict: bool = False,
) -> TruthConflictRecord:
    """Assert that a canonical write has been performed before a compat write.

    Call this guard immediately before any compat/mirror write to enforce the
    ``CANONICAL_WRITE_PRECEDES_COMPAT_WRITE_POLICY``.  The caller must set
    ``canonical_write_confirmed=True`` only when the canonical write to the
    authoritative source (UDM / CanonicalTask / CanonicalSessionTruthRuntime)
    has been confirmed to have succeeded in the same operation.

    Parameters
    ----------
    surface:
        The truth surface for which the compat write is being performed.
    canonical_write_confirmed:
        ``True`` when the canonical write to the authoritative source has been
        confirmed successful before this compat write.  ``False`` indicates
        the compat write would be performed without a prior canonical write —
        a policy violation.
    compat_path:
        Optional description of the compat write path for log context.
    context:
        Optional context string (e.g. request handler name) for log messages.
    strict:
        When ``True``, raise :exc:`RuntimeError` if canonical write is missing.

    Returns
    -------
    TruthConflictRecord

    Raises
    ------
    RuntimeError
        Only when ``strict=True`` and ``canonical_write_confirmed=False``.
    """
    ownership = get_write_authority_for_surface(surface)
    canonical_authority = (
        ownership.canonical_write_authority if ownership else "<unknown>"
    )

    if canonical_write_confirmed:
        msg = (
            f"TRUTH_CONFLICT_ENFORCEMENT [{surface.value}]: "
            "canonical write confirmed before compat mirror write. "
            f"canonical_authority={canonical_authority!r} "
            f"compat_path={compat_path!r}."
        )
        logger.debug(msg)
        record = TruthConflictRecord(
            surface=surface,
            verdict=TruthConflictVerdict.COMPAT_MIRROR_WRITE_VALID,
            caller_module=compat_path or "<unspecified>",
            canonical_authority=canonical_authority,
            message=msg,
        )
        _record_conflict(record)
        return record

    # Canonical write NOT confirmed — policy violation.
    msg = (
        f"TRUTH_CONFLICT_ENFORCEMENT [{surface.value}] "
        "CANONICAL_WRITE_MISSING: compat/mirror write attempted without "
        f"confirmed canonical write to {canonical_authority!r}.  "
        f"compat_path={compat_path!r}  context={context!r}.  "
        "This violates CANONICAL_WRITE_PRECEDES_COMPAT_WRITE_POLICY and "
        "may create a dual-truth condition.  Canonical authority must write "
        "first; compat writes are strictly secondary mirror operations."
    )
    logger.warning(
        "TRUTH_REGRESSION::%s::CANONICAL_WRITE_MISSING compat_path=%r context=%r",
        surface.value,
        compat_path,
        context,
    )
    if strict:
        raise RuntimeError(msg)
    record = TruthConflictRecord(
        surface=surface,
        verdict=TruthConflictVerdict.CANONICAL_WRITE_MISSING,
        caller_module=compat_path or "<unspecified>",
        canonical_authority=canonical_authority,
        message=msg,
    )
    _record_conflict(record)
    return record


def assert_no_parallel_write_authority(
    surface: TruthSurface,
    *,
    writer_module: str,
    context: str = "",
    strict: bool = False,
) -> TruthConflictRecord:
    """Assert that *writer_module* is not acting as a parallel write authority.

    Call this guard when a module performs a write to a truth surface to verify
    that either (a) the module is the declared canonical write authority, or
    (b) the module is in the explicitly allowed compat mirror paths list.
    Any write from a module not in either category is a parallel authority
    violation.

    Parameters
    ----------
    surface:
        The truth surface being written.
    writer_module:
        The module path of the code performing the write.
    context:
        Optional context string for log messages.
    strict:
        When ``True``, raise :exc:`RuntimeError`` if a parallel authority is
        detected.

    Returns
    -------
    TruthConflictRecord

    Raises
    ------
    RuntimeError
        Only when ``strict=True`` and a parallel authority is detected.
    """
    ownership = get_write_authority_for_surface(surface)
    if ownership is None:
        msg = (
            f"TRUTH_CONFLICT_ENFORCEMENT [{surface.value}]: "
            f"no ownership record for surface.  writer_module={writer_module!r}.  "
            "Register this surface in the truth ownership registry."
        )
        logger.warning(msg)
        record = TruthConflictRecord(
            surface=surface,
            verdict=TruthConflictVerdict.UNKNOWN,
            caller_module=writer_module,
            canonical_authority="<unregistered>",
            message=msg,
        )
        _record_conflict(record)
        return record

    # Check if writer is canonical authority.
    if writer_module in ownership.canonical_write_authority:
        msg = (
            f"TRUTH_CONFLICT_ENFORCEMENT [{surface.value}]: "
            f"canonical write authority confirmed: {writer_module!r}."
        )
        logger.debug(msg)
        record = TruthConflictRecord(
            surface=surface,
            verdict=TruthConflictVerdict.CANONICAL_AUTHORITY_CONFIRMED,
            caller_module=writer_module,
            canonical_authority=ownership.canonical_write_authority,
            message=msg,
        )
        _record_conflict(record)
        return record

    # Check if writer is an explicitly allowed compat mirror path.
    is_allowed_compat = any(
        writer_module in allowed_path
        for allowed_path in ownership.allowed_compat_mirror_paths
    )
    if is_allowed_compat:
        msg = (
            f"TRUTH_CONFLICT_ENFORCEMENT [{surface.value}]: "
            f"allowed compat mirror path confirmed: {writer_module!r}."
        )
        logger.debug(msg)
        record = TruthConflictRecord(
            surface=surface,
            verdict=TruthConflictVerdict.COMPAT_MIRROR_WRITE_VALID,
            caller_module=writer_module,
            canonical_authority=ownership.canonical_write_authority,
            message=msg,
        )
        _record_conflict(record)
        return record

    # Check if writer is in the prohibited paths list.
    is_prohibited = any(
        writer_module in prohibited_path
        for prohibited_path in ownership.prohibited_write_paths
    )
    if is_prohibited:
        msg = (
            f"TRUTH_CONFLICT_ENFORCEMENT [{surface.value}] "
            "TRUTH_REGRESSION_DETECTED: prohibited write path "
            f"{writer_module!r} is writing to truth surface "
            f"{surface.value!r}.  Canonical authority: "
            f"{ownership.canonical_write_authority!r}.  context={context!r}.  "
            "This is a truth regression — a previously demoted path has "
            "re-acquired write influence.  Violates "
            "NO_PARALLEL_TRUTH_AUTHORITY_POLICY."
        )
        logger.error(
            "TRUTH_REGRESSION::%s::PROHIBITED_PATH_WRITE writer=%r context=%r",
            surface.value,
            writer_module,
            context,
        )
        if strict:
            raise RuntimeError(msg)
        record = TruthConflictRecord(
            surface=surface,
            verdict=TruthConflictVerdict.TRUTH_REGRESSION_DETECTED,
            caller_module=writer_module,
            canonical_authority=ownership.canonical_write_authority,
            message=msg,
        )
        _record_conflict(record)
        return record

    # Writer is not canonical and not listed — parallel authority.
    msg = (
        f"TRUTH_CONFLICT_ENFORCEMENT [{surface.value}] "
        "PARALLEL_AUTHORITY_DETECTED: unregistered writer "
        f"{writer_module!r} is writing to truth surface {surface.value!r}.  "
        f"Canonical authority: {ownership.canonical_write_authority!r}.  "
        f"context={context!r}.  "
        "This module is not the canonical write authority and is not in the "
        "allowed compat mirror paths.  It must be bounded or retired.  "
        "Violates NO_PARALLEL_TRUTH_AUTHORITY_POLICY."
    )
    logger.warning(
        "TRUTH_CONFLICT_RELAPSE::%s::PARALLEL_AUTHORITY writer=%r context=%r",
        surface.value,
        writer_module,
        context,
    )
    if strict:
        raise RuntimeError(msg)
    record = TruthConflictRecord(
        surface=surface,
        verdict=TruthConflictVerdict.PARALLEL_AUTHORITY_DETECTED,
        caller_module=writer_module,
        canonical_authority=ownership.canonical_write_authority,
        message=msg,
    )
    _record_conflict(record)
    return record


def check_compat_write_is_mirror_only(
    surface: TruthSurface,
    *,
    compat_path: str,
    context: str = "",
    strict: bool = False,
) -> TruthConflictRecord:
    """Check that a compat write to *surface* is a mirror-only operation.

    A mirror-only write is one that replicates state already committed by the
    canonical authority.  This guard verifies that *compat_path* is in the
    allowed compat mirror paths list for *surface*, and emits a structured
    warning if it is not.

    This is a lighter-weight guard than :func:`assert_no_parallel_write_authority`
    for sites where the caller knows they are a compat path and wants to confirm
    their bounding status without providing a ``canonical_write_confirmed`` flag.

    Parameters
    ----------
    surface:
        The truth surface being written.
    compat_path:
        Description or module path of the compat write site.
    context:
        Optional context string for log messages.
    strict:
        When ``True``, raise :exc:`RuntimeError` if the compat write is not
        in the allowed mirror paths list.

    Returns
    -------
    TruthConflictRecord
    """
    ownership = get_write_authority_for_surface(surface)
    if ownership is None:
        msg = (
            f"TRUTH_CONFLICT_ENFORCEMENT [{surface.value}]: "
            f"no ownership record for surface.  compat_path={compat_path!r}.  "
            "Register this surface in the truth ownership registry."
        )
        logger.warning(msg)
        record = TruthConflictRecord(
            surface=surface,
            verdict=TruthConflictVerdict.UNKNOWN,
            caller_module=compat_path,
            canonical_authority="<unregistered>",
            message=msg,
        )
        _record_conflict(record)
        return record

    is_allowed = any(
        compat_path in allowed_path
        for allowed_path in ownership.allowed_compat_mirror_paths
    )
    if is_allowed:
        msg = (
            f"TRUTH_CONFLICT_ENFORCEMENT [{surface.value}]: "
            f"compat write confirmed as mirror-only: {compat_path!r}."
        )
        logger.debug(msg)
        record = TruthConflictRecord(
            surface=surface,
            verdict=TruthConflictVerdict.COMPAT_MIRROR_WRITE_VALID,
            caller_module=compat_path,
            canonical_authority=ownership.canonical_write_authority,
            message=msg,
        )
        _record_conflict(record)
        return record

    # Compat path is not in the allowed list — potential parallel authority.
    msg = (
        f"TRUTH_CONFLICT_ENFORCEMENT [{surface.value}] "
        f"COMPAT_WRITE_NOT_MIRROR_ONLY: {compat_path!r} is performing a write "
        f"to truth surface {surface.value!r} but is not in the allowed compat "
        f"mirror paths list.  Canonical authority: "
        f"{ownership.canonical_write_authority!r}.  context={context!r}.  "
        "This compat write may not be a bounded mirror operation.  "
        "It must be catalogued in TruthOwnershipRecord.allowed_compat_mirror_paths "
        "or refactored to route through the canonical authority.  "
        "Violates COMPAT_TRUTH_WRITE_MUST_BE_MIRROR_ONLY_POLICY."
    )
    logger.warning(
        "TRUTH_CONFLICT_RELAPSE::%s::COMPAT_WRITE_NOT_MIRROR_ONLY "
        "compat_path=%r context=%r",
        surface.value,
        compat_path,
        context,
    )
    if strict:
        raise RuntimeError(msg)
    record = TruthConflictRecord(
        surface=surface,
        verdict=TruthConflictVerdict.PARALLEL_AUTHORITY_DETECTED,
        caller_module=compat_path,
        canonical_authority=ownership.canonical_write_authority,
        message=msg,
    )
    _record_conflict(record)
    return record


# ===========================================================================
# Convergence health
# ===========================================================================


def build_truth_conflict_enforcement_snapshot() -> TruthConflictEnforcementSnapshot:
    """Build an aggregate snapshot of the truth conflict enforcement posture.

    The snapshot is JSON-serialisable and suitable for CI consumption,
    operator tooling, and regression gate assertions.

    Returns
    -------
    TruthConflictEnforcementSnapshot
    """
    registry = _TRUTH_OWNERSHIP_REGISTRY
    recent = _get_recent_conflicts()

    parallel_violations = sum(
        1 for r in recent
        if r.verdict in (
            TruthConflictVerdict.PARALLEL_AUTHORITY_DETECTED,
        )
    )
    ordering_violations = sum(
        1 for r in recent
        if r.verdict == TruthConflictVerdict.CANONICAL_WRITE_MISSING
    )
    regression_events = sum(
        1 for r in recent
        if r.verdict == TruthConflictVerdict.TRUTH_REGRESSION_DETECTED
    )

    convergence_healthy = (
        parallel_violations == 0
        and ordering_violations == 0
        and regression_events == 0
    )

    return TruthConflictEnforcementSnapshot(
        generated_at=time.time(),
        total_surfaces=len(registry),
        surfaces_with_declared_authority=sum(
            1 for r in registry if r.canonical_write_authority
        ),
        parallel_authority_violations_detected=parallel_violations,
        compat_write_ordering_violations_detected=ordering_violations,
        truth_regression_events_detected=regression_events,
        convergence_healthy=convergence_healthy,
        policy_sentinels=[
            CANONICAL_WRITE_PRECEDES_COMPAT_WRITE_POLICY,
            NO_PARALLEL_TRUTH_AUTHORITY_POLICY,
            COMPAT_TRUTH_WRITE_MUST_BE_MIRROR_ONLY_POLICY,
            TRUTH_REGRESSION_DETECTION_POLICY,
            TRUTH_CONFLICT_RELAPSE_MUST_BE_FAIL_FAST_POLICY,
        ],
        surface_summaries=[r.to_dict() for r in registry],
    )


def is_truth_convergence_healthy() -> bool:
    """Return True when the in-process truth conflict enforcement posture is healthy.

    Healthy means: no parallel authority violations, no compat write ordering
    violations, and no truth regression events have been detected in the
    in-process ring buffer since the last reset.

    This is a lightweight check suitable for health endpoints and CI gates.

    Returns
    -------
    bool
    """
    return build_truth_conflict_enforcement_snapshot().convergence_healthy
