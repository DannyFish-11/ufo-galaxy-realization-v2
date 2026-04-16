#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""core/canonical_task_dispatch_chain.py
=========================================
PR-7 (12-PR governance plan, MAIN repo side):
Canonical Task Dispatch and Delegated Execution Chain Definition.

Background
----------
The Galaxy runtime already contains a meaningful execution chain spanning
source dispatch orchestration, local execution, remote handoff,
fallback-local behavior, staged mesh coordination, Android inbound dispatch,
delegated signal ingress, execution tracking, signal reconciliation, and
result handling.

However, these paths are still understood more through accumulated
implementation knowledge than through a single canonical definition of the
execution chain across both repositories.

Purpose
-------
This module provides the **single canonical definition** of the task dispatch
and delegated execution chain across all paths:

* **Primary local path** — ``SourceDispatchMode.local``: source device
  executes the task directly via ``OpenClawd._run_execution()``.  This is
  the default, lowest-latency path and the one all other paths fall back to.

* **Remote handoff path** — ``SourceDispatchMode.remote_handoff``: source
  device builds a ``HandoffEnvelopeV2`` and forwards it to a target runtime
  via ``galaxy_gateway.agent_bridge.forward_handoff()``.  The target adopts
  the envelope and executes locally via
  ``core.runtime.target_takeover.execute_local_takeover()``.

* **Fallback-local path** — ``SourceDispatchMode.fallback_local``: used
  when a remote handoff attempt fails (network error, target rejection, etc).
  Execution falls back to local with the failure reason recorded so it is
  distinguishable from a planned local dispatch.

* **Staged mesh path** — ``SourceDispatchMode.staged_mesh``: used when 2+
  mesh participants are active and no explicit single target is specified.
  ``core.mesh.mesh_session_coordinator.coordinate_mesh_session()`` manages
  staged multi-device coordination.

* **Android inbound path** — ``delegated_execution_signal`` message type:
  Android runtimes emit first-class delegated execution signals that are
  ingested by ``core.android_delegated_signal_ingress.ingest_delegated_execution_signal()``
  and reconciled by
  ``core.android_execution_signal_reconciler.reconcile_android_execution_signal()``.
  This path is part of the same governed execution system — it is the
  **target-side** result/signal leg for tasks originally dispatched from a
  PC source via the remote handoff path.

* **Blocked path** — ``SourceDispatchMode.blocked``: governance or policy
  prevents execution.  No local or remote execution is attempted.

This module is **governance/inspection only** — it does NOT introduce new
routing logic or change any core behavior.  Its public API lets any subsystem
reason about dispatch paths as a single governed taxonomy.

Public API summary
------------------
Enums::

    DispatchPathKind     — primary_local / remote_handoff / fallback_local /
                           staged_mesh / android_inbound / blocked
    DispatchPathRole     — canonical / fallback / staged_coordination /
                           android_delegated / blocked
    DispatchResultOwner  — source / target / reconciled / governance

Dataclasses::

    DispatchChainRecord   — one record per dispatch path kind
    DispatchChainSnapshot — full catalogue snapshot

Functions::

    get_dispatch_path_catalogue()      — all DispatchChainRecord objects
    classify_dispatch_path(path_kind)  — record for one path kind
    is_canonical_path(path_kind)       — True for the primary_local path
    is_fallback_path(path_kind)        — True for fallback_local
    is_android_inbound_path(path_kind) — True for android_inbound
    get_primary_dispatch_path()        — record for primary_local
    build_dispatch_chain_snapshot()    — DispatchChainSnapshot

Policy sentinels (machine-checkable governance):

    DISPATCH_CHAIN_PRIMARY_PATH_IS_LOCAL_POLICY
    DISPATCH_CHAIN_REMOTE_HANDOFF_BLOCKS_LOCAL_POLICY
    DISPATCH_CHAIN_FALLBACK_IS_DISTINGUISHABLE_POLICY
    DISPATCH_CHAIN_ANDROID_INBOUND_IS_SAME_SYSTEM_POLICY
    DISPATCH_CHAIN_STAGED_MESH_IS_COORDINATION_ONLY_POLICY
    DISPATCH_CHAIN_BLOCKED_PATH_IS_FINAL_POLICY

Design principles
-----------------
- **Single definition** — this is the one canonical document of what the
  dispatch system contains, intended to replace scattered implementation
  knowledge.
- **Additive only** — no existing behavior is changed.  All existing modules
  continue to operate exactly as before.
- **Governance-oriented** — enums, records, and policy sentinels give
  reviewers and automated gates a stable vocabulary to reason about.
- **Android is first-class** — the Android inbound path is explicitly placed
  inside the same execution model, not treated as a special case.
"""

from __future__ import annotations

import dataclasses
import time
from enum import Enum
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Module authority marker
# ---------------------------------------------------------------------------

CANONICAL_TASK_DISPATCH_CHAIN_IS_AUTHORITY: str = (
    "core.canonical_task_dispatch_chain::PR7-governance-plan::"
    "canonical-definition-of-task-dispatch-and-delegated-execution-chain::"
    "post-533-dual-repo-runtime-unification"
)

CANONICAL_TASK_DISPATCH_CHAIN_PR7_SENTINEL: str = (
    "CANONICAL_TASK_DISPATCH_CHAIN_PR7::governance-plan-7::"
    "dispatch-chain-is-single-governed-taxonomy::"
    "primary-remote-fallback-staged-android-blocked-paths-all-classified"
)

# ---------------------------------------------------------------------------
# Policy sentinels — machine-checkable governance rules
# ---------------------------------------------------------------------------

DISPATCH_CHAIN_PRIMARY_PATH_IS_LOCAL_POLICY: str = (
    "DISPATCH_CHAIN_POLICY::PRIMARY_PATH_IS_LOCAL: "
    "The primary dispatch path is local execution via OpenClawd._run_execution().  "
    "All other paths (remote handoff, fallback_local, staged_mesh) MUST ultimately "
    "fall back to local execution or explicitly record why local execution did not "
    "occur.  The primary local path is the canonical, lowest-latency baseline."
)

DISPATCH_CHAIN_REMOTE_HANDOFF_BLOCKS_LOCAL_POLICY: str = (
    "DISPATCH_CHAIN_POLICY::REMOTE_HANDOFF_BLOCKS_LOCAL: "
    "When remote handoff mode is selected and a dispatch target has been chosen, "
    "local execution MUST NOT run concurrently.  Local execution is only permitted "
    "after the remote handoff path has been fully resolved (success or failure).  "
    "This rule prevents duplicate execution and session-truth divergence between "
    "source and target runtimes."
)

DISPATCH_CHAIN_FALLBACK_IS_DISTINGUISHABLE_POLICY: str = (
    "DISPATCH_CHAIN_POLICY::FALLBACK_IS_DISTINGUISHABLE: "
    "A fallback_local dispatch result MUST carry a stable, human-readable "
    "decision_reason that identifies the remote failure origin.  The fallback "
    "MUST NOT silently swallow the remote failure — it MUST be recorded so "
    "that diagnostics can distinguish planned local execution from fallback "
    "local execution."
)

DISPATCH_CHAIN_ANDROID_INBOUND_IS_SAME_SYSTEM_POLICY: str = (
    "DISPATCH_CHAIN_POLICY::ANDROID_INBOUND_IS_SAME_SYSTEM: "
    "Android inbound delegated execution signals are part of the same governed "
    "execution system.  The android_inbound path is the target-side result/signal "
    "leg for tasks originally dispatched from a source device via the remote "
    "handoff path.  Gateway handlers MUST route delegated_execution_signal messages "
    "through core.android_delegated_signal_ingress.ingest_delegated_execution_signal(), "
    "not through legacy compatibility paths."
)

DISPATCH_CHAIN_STAGED_MESH_IS_COORDINATION_ONLY_POLICY: str = (
    "DISPATCH_CHAIN_POLICY::STAGED_MESH_IS_COORDINATION_ONLY: "
    "The staged_mesh dispatch path produces a coordination plan via "
    "core.mesh.mesh_session_coordinator.coordinate_mesh_session().  It does NOT "
    "independently hold execution authority.  Full mesh execution is governed by "
    "the mesh session coordinator and the canonical source/target runtime pair.  "
    "A staged_mesh dispatch result MUST carry coordinator_status so the outcome "
    "is inspectable."
)

DISPATCH_CHAIN_BLOCKED_PATH_IS_FINAL_POLICY: str = (
    "DISPATCH_CHAIN_POLICY::BLOCKED_PATH_IS_FINAL: "
    "When dispatch mode is blocked (governance or policy refusal), NEITHER local "
    "NOR remote execution may be attempted.  The blocked result MUST carry a "
    "stable reason string so the blocking decision is explainable.  No fallback "
    "execution is permitted after a blocked decision."
)

# ---------------------------------------------------------------------------
# DispatchPathKind — taxonomy of all dispatch paths
# ---------------------------------------------------------------------------


class DispatchPathKind(str, Enum):
    """All dispatch path kinds in the Galaxy task dispatch system.

    These align directly to ``contracts.source_dispatch.SourceDispatchMode``
    on the source side, plus the dedicated ``android_inbound`` path that
    represents the target-side inbound leg for Android runtimes.
    """

    primary_local = "primary_local"
    """Default path.  Source device executes locally via OpenClawd.
    This is the canonical, lowest-latency baseline.
    Authority module: ``core.openclawd`` (subject_decision_authority)."""

    remote_handoff = "remote_handoff"
    """Source device delegates to a remote target runtime.
    A ``HandoffEnvelopeV2`` is forwarded via
    ``galaxy_gateway.agent_bridge.forward_handoff()``.
    The target adopts via ``core.runtime.target_takeover``."""

    fallback_local = "fallback_local"
    """Local execution after a failed remote handoff.
    Distinguishable from planned local by a recorded failure reason.
    Authority: same local modules as primary_local."""

    staged_mesh = "staged_mesh"
    """Staged multi-device coordination for 2+ active mesh participants.
    Authority: ``core.mesh.mesh_session_coordinator``."""

    android_inbound = "android_inbound"
    """Android runtime inbound delegated execution signal.
    This is the target-side result/signal leg within the same governed
    execution system.
    Authority: ``core.android_delegated_signal_ingress`` +
    ``core.android_execution_signal_reconciler``."""

    blocked = "blocked"
    """Governance or policy refusal.  No execution is attempted."""


# ---------------------------------------------------------------------------
# DispatchPathRole — role classification for each path
# ---------------------------------------------------------------------------


class DispatchPathRole(str, Enum):
    """Role classification for a dispatch path."""

    canonical = "canonical"
    """The primary, preferred, lowest-latency path."""

    fallback = "fallback"
    """Recovery path used when the preferred path is unavailable or failed."""

    staged_coordination = "staged_coordination"
    """Multi-device staged coordination path."""

    android_delegated = "android_delegated"
    """Target-side inbound path for Android delegated execution signals."""

    blocked = "blocked"
    """No execution permitted; governance/policy refusal."""


# ---------------------------------------------------------------------------
# DispatchResultOwner — who owns result handling for each path
# ---------------------------------------------------------------------------


class DispatchResultOwner(str, Enum):
    """Who owns result/signal handling for a dispatch path."""

    source = "source"
    """Result is assembled and owned on the source (PC) side.
    Applies to: primary_local, fallback_local."""

    target = "target"
    """Result is produced by the target runtime and returned to source.
    Applies to: remote_handoff (target executes, result comes back)."""

    reconciled = "reconciled"
    """Result comes from reconciliation of inbound Android signals on the
    source side.  Applies to: android_inbound."""

    coordinator = "coordinator"
    """Result is assembled by the mesh session coordinator.
    Applies to: staged_mesh."""

    governance = "governance"
    """Result is a governance refusal; no execution occurred.
    Applies to: blocked."""


# ---------------------------------------------------------------------------
# DispatchChainRecord — one record per dispatch path
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class DispatchChainRecord:
    """Canonical record describing one dispatch path in the execution chain.

    Each record captures the governance-relevant attributes of one dispatch
    path so that the full taxonomy is inspectable without reading source code.
    """

    path_kind: DispatchPathKind
    """Which dispatch path this record describes."""

    role: DispatchPathRole
    """Role classification for this path."""

    result_owner: DispatchResultOwner
    """Who owns result/signal handling for this path."""

    primary_module: str
    """The single canonical authority module that owns this path."""

    signal_modules: List[str]
    """Modules that emit or consume signals along this path."""

    reconciliation_module: Optional[str]
    """Module responsible for reconciliation on this path (if any)."""

    description: str
    """Human-readable description of the path and its governance role."""

    policy_sentinel: str
    """The policy sentinel that governs this path."""

    def to_dict(self) -> Dict:
        """Serialise to a plain dict."""
        return {
            "path_kind": self.path_kind.value,
            "role": self.role.value,
            "result_owner": self.result_owner.value,
            "primary_module": self.primary_module,
            "signal_modules": list(self.signal_modules),
            "reconciliation_module": self.reconciliation_module,
            "description": self.description,
            "policy_sentinel": self.policy_sentinel,
        }


# ---------------------------------------------------------------------------
# DispatchChainSnapshot — full catalogue snapshot
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class DispatchChainSnapshot:
    """Snapshot of the full canonical dispatch chain catalogue.

    Produced by :func:`build_dispatch_chain_snapshot`.  Suitable for
    projection surfaces and observability endpoints.
    """

    generated_at: float
    """Unix timestamp when this snapshot was assembled."""

    authority: str
    """The module authority sentinel."""

    sentinel: str
    """The PR sentinel confirming this snapshot is from the canonical module."""

    path_count: int
    """Total number of dispatch path kinds in the catalogue."""

    canonical_path_count: int
    """Number of paths with role == DispatchPathRole.canonical."""

    fallback_path_count: int
    """Number of paths with role == DispatchPathRole.fallback."""

    paths: List[Dict]
    """Serialised DispatchChainRecord for every path kind."""

    primary_dispatch_path: str
    """The path_kind value of the primary dispatch path."""

    def to_dict(self) -> Dict:
        """Serialise to a plain dict."""
        return {
            "generated_at": self.generated_at,
            "authority": self.authority,
            "sentinel": self.sentinel,
            "path_count": self.path_count,
            "canonical_path_count": self.canonical_path_count,
            "fallback_path_count": self.fallback_path_count,
            "paths": list(self.paths),
            "primary_dispatch_path": self.primary_dispatch_path,
        }


# ---------------------------------------------------------------------------
# Catalogue — authoritative list of all dispatch path records
# ---------------------------------------------------------------------------

_DISPATCH_PATH_CATALOGUE: List[DispatchChainRecord] = [
    DispatchChainRecord(
        path_kind=DispatchPathKind.primary_local,
        role=DispatchPathRole.canonical,
        result_owner=DispatchResultOwner.source,
        primary_module="core.openclawd",
        signal_modules=[
            "core.openclawd",
            "core.agent.kernel",
            "core.command_router",
            "core.local_execution_chain",
        ],
        reconciliation_module=None,
        description=(
            "Primary local execution path.  OpenClawd acts as subject decision "
            "authority and calls _run_execution() to execute locally.  "
            "Result flows back synchronously through CommandRouter.route_envelope() "
            "and is normalised into a LocalExecutionResult.  This is the canonical, "
            "lowest-latency baseline path that all other paths ultimately fall back to."
        ),
        policy_sentinel=DISPATCH_CHAIN_PRIMARY_PATH_IS_LOCAL_POLICY,
    ),
    DispatchChainRecord(
        path_kind=DispatchPathKind.remote_handoff,
        role=DispatchPathRole.canonical,
        result_owner=DispatchResultOwner.target,
        primary_module="core.runtime.source_dispatch_orchestrator",
        signal_modules=[
            "core.runtime.source_dispatch_orchestrator",
            "galaxy_gateway.agent_bridge",
            "core.runtime.target_takeover",
            "contracts.source_dispatch",
        ],
        reconciliation_module="core.runtime.source_dispatch_orchestrator",
        description=(
            "Remote handoff path.  SourceDispatchOrchestrator selects a target "
            "device and forwards a HandoffEnvelopeV2 via "
            "galaxy_gateway.agent_bridge.forward_handoff().  The target runtime "
            "adopts the envelope and executes locally via "
            "core.runtime.target_takeover.execute_local_takeover().  "
            "When remote handoff is selected and a target has been chosen, local "
            "execution on the source MUST NOT run concurrently."
        ),
        policy_sentinel=DISPATCH_CHAIN_REMOTE_HANDOFF_BLOCKS_LOCAL_POLICY,
    ),
    DispatchChainRecord(
        path_kind=DispatchPathKind.fallback_local,
        role=DispatchPathRole.fallback,
        result_owner=DispatchResultOwner.source,
        primary_module="core.runtime.source_dispatch_orchestrator",
        signal_modules=[
            "core.runtime.source_dispatch_orchestrator",
            "core.openclawd",
            "core.local_execution_chain",
        ],
        reconciliation_module=None,
        description=(
            "Fallback local execution path.  Used when a remote handoff attempt "
            "fails (network error, target rejection, timeout, or other error).  "
            "The effective_mode is recorded as fallback_local with a stable "
            "decision_reason that identifies the remote failure origin.  "
            "Distinguishable from planned local execution so diagnostics can "
            "track fallback frequency and root causes."
        ),
        policy_sentinel=DISPATCH_CHAIN_FALLBACK_IS_DISTINGUISHABLE_POLICY,
    ),
    DispatchChainRecord(
        path_kind=DispatchPathKind.staged_mesh,
        role=DispatchPathRole.staged_coordination,
        result_owner=DispatchResultOwner.coordinator,
        primary_module="core.mesh.mesh_session_coordinator",
        signal_modules=[
            "core.runtime.source_dispatch_orchestrator",
            "core.mesh.mesh_session_coordinator",
            "contracts.mesh_session",
        ],
        reconciliation_module="core.mesh.mesh_session_coordinator",
        description=(
            "Staged multi-device mesh coordination path.  Used when 2+ mesh "
            "participants are active and no explicit single target device is "
            "specified.  SourceDispatchOrchestrator invokes "
            "core.mesh.mesh_session_coordinator.coordinate_mesh_session() to "
            "manage staged execution across the mesh.  The result carries "
            "coordinator_status and coordinator_summary for inspectability.  "
            "The staged_mesh path does NOT independently hold execution authority; "
            "it delegates to the canonical source/target runtime pair."
        ),
        policy_sentinel=DISPATCH_CHAIN_STAGED_MESH_IS_COORDINATION_ONLY_POLICY,
    ),
    DispatchChainRecord(
        path_kind=DispatchPathKind.android_inbound,
        role=DispatchPathRole.android_delegated,
        result_owner=DispatchResultOwner.reconciled,
        primary_module="core.android_delegated_signal_ingress",
        signal_modules=[
            "galaxy_gateway.android.handlers.delegated_signal",
            "core.android_delegated_signal_ingress",
            "core.android_execution_signal_reconciler",
            "core.attached_runtime_recovery_readiness",
            "core.attached_runtime_session_registry",
        ],
        reconciliation_module="core.android_execution_signal_reconciler",
        description=(
            "Android inbound delegated execution signal path.  Android runtimes "
            "emit delegated_execution_signal messages carrying explicit signal_kind "
            "(ack/progress/result/timeout/cancelled) and result_kind fields.  "
            "These signals are ingested by "
            "core.android_delegated_signal_ingress.ingest_delegated_execution_signal() "
            "and reconciled by "
            "core.android_execution_signal_reconciler.reconcile_android_execution_signal().  "
            "This path is the target-side result/signal leg for tasks originally "
            "dispatched from a source device via the remote_handoff path.  "
            "It is part of the same governed execution system — NOT a separate "
            "or special-case path."
        ),
        policy_sentinel=DISPATCH_CHAIN_ANDROID_INBOUND_IS_SAME_SYSTEM_POLICY,
    ),
    DispatchChainRecord(
        path_kind=DispatchPathKind.blocked,
        role=DispatchPathRole.blocked,
        result_owner=DispatchResultOwner.governance,
        primary_module="core.runtime.source_dispatch_orchestrator",
        signal_modules=[
            "core.runtime.source_dispatch_orchestrator",
            "contracts.source_dispatch",
        ],
        reconciliation_module=None,
        description=(
            "Blocked dispatch path.  Governance or policy prevents execution.  "
            "No local or remote execution is attempted.  The result carries a "
            "stable reason string so the blocking decision is explainable.  "
            "No fallback execution is permitted after a blocked decision."
        ),
        policy_sentinel=DISPATCH_CHAIN_BLOCKED_PATH_IS_FINAL_POLICY,
    ),
]

#: Index from DispatchPathKind → DispatchChainRecord (built once at import time)
_CATALOGUE_INDEX: Dict[DispatchPathKind, DispatchChainRecord] = {
    r.path_kind: r for r in _DISPATCH_PATH_CATALOGUE
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_dispatch_path_catalogue() -> List[DispatchChainRecord]:
    """Return all canonical dispatch path records.

    The list is ordered: primary_local, remote_handoff, fallback_local,
    staged_mesh, android_inbound, blocked.

    Returns
    -------
    list[DispatchChainRecord]
        One record per :class:`DispatchPathKind` value.
    """
    return list(_DISPATCH_PATH_CATALOGUE)


def classify_dispatch_path(path_kind: DispatchPathKind) -> DispatchChainRecord:
    """Return the :class:`DispatchChainRecord` for *path_kind*.

    Parameters
    ----------
    path_kind:
        The dispatch path kind to look up.

    Returns
    -------
    DispatchChainRecord
        The canonical record for *path_kind*.

    Raises
    ------
    KeyError
        If *path_kind* is not in the catalogue (should never happen if the
        enum is complete).
    """
    return _CATALOGUE_INDEX[path_kind]


def is_canonical_path(path_kind: DispatchPathKind) -> bool:
    """Return ``True`` when *path_kind* has role :attr:`DispatchPathRole.canonical`.

    Both ``primary_local`` and ``remote_handoff`` are canonical paths.
    """
    record = _CATALOGUE_INDEX.get(path_kind)
    return record is not None and record.role == DispatchPathRole.canonical


def is_fallback_path(path_kind: DispatchPathKind) -> bool:
    """Return ``True`` when *path_kind* has role :attr:`DispatchPathRole.fallback`."""
    record = _CATALOGUE_INDEX.get(path_kind)
    return record is not None and record.role == DispatchPathRole.fallback


def is_android_inbound_path(path_kind: DispatchPathKind) -> bool:
    """Return ``True`` when *path_kind* is :attr:`DispatchPathKind.android_inbound`."""
    return path_kind == DispatchPathKind.android_inbound


def get_primary_dispatch_path() -> DispatchChainRecord:
    """Return the canonical record for the primary (local) dispatch path.

    This is always :attr:`DispatchPathKind.primary_local` — the lowest-latency
    baseline that all other paths fall back to.
    """
    return _CATALOGUE_INDEX[DispatchPathKind.primary_local]


def build_dispatch_chain_snapshot() -> DispatchChainSnapshot:
    """Build and return a :class:`DispatchChainSnapshot`.

    The snapshot is suitable for projection surfaces and observability
    endpoints.  It is generated fresh each call (no caching) so that it
    always reflects the current catalogue.
    """
    canonical_count = sum(
        1 for r in _DISPATCH_PATH_CATALOGUE if r.role == DispatchPathRole.canonical
    )
    fallback_count = sum(
        1 for r in _DISPATCH_PATH_CATALOGUE if r.role == DispatchPathRole.fallback
    )
    return DispatchChainSnapshot(
        generated_at=time.time(),
        authority=CANONICAL_TASK_DISPATCH_CHAIN_IS_AUTHORITY,
        sentinel=CANONICAL_TASK_DISPATCH_CHAIN_PR7_SENTINEL,
        path_count=len(_DISPATCH_PATH_CATALOGUE),
        canonical_path_count=canonical_count,
        fallback_path_count=fallback_count,
        paths=[r.to_dict() for r in _DISPATCH_PATH_CATALOGUE],
        primary_dispatch_path=DispatchPathKind.primary_local.value,
    )


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Authority sentinels
    "CANONICAL_TASK_DISPATCH_CHAIN_IS_AUTHORITY",
    "CANONICAL_TASK_DISPATCH_CHAIN_PR7_SENTINEL",
    # Policy sentinels
    "DISPATCH_CHAIN_PRIMARY_PATH_IS_LOCAL_POLICY",
    "DISPATCH_CHAIN_REMOTE_HANDOFF_BLOCKS_LOCAL_POLICY",
    "DISPATCH_CHAIN_FALLBACK_IS_DISTINGUISHABLE_POLICY",
    "DISPATCH_CHAIN_ANDROID_INBOUND_IS_SAME_SYSTEM_POLICY",
    "DISPATCH_CHAIN_STAGED_MESH_IS_COORDINATION_ONLY_POLICY",
    "DISPATCH_CHAIN_BLOCKED_PATH_IS_FINAL_POLICY",
    # Enums
    "DispatchPathKind",
    "DispatchPathRole",
    "DispatchResultOwner",
    # Dataclasses
    "DispatchChainRecord",
    "DispatchChainSnapshot",
    # Functions
    "get_dispatch_path_catalogue",
    "classify_dispatch_path",
    "is_canonical_path",
    "is_fallback_path",
    "is_android_inbound_path",
    "get_primary_dispatch_path",
    "build_dispatch_chain_snapshot",
]
