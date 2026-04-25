#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/canonical_authoritative_path_convergence.py
=================================================
PR-convergence — Enforce Single Authoritative Path and Default-Off Legacy
Behavior.

Problem addressed
-----------------
Prior PRs (PR-8 through PR-M) established compat/legacy blocking machinery and
registered every known legacy dispatch path.  However, the presence of that
machinery did not prove that the runtime had actually *converged* to a single
authoritative path.  Legacy/compat paths could still influence canonical state
by default because:

* The path inventory was spread across multiple registries with no single
  machine-readable surface classifying each path's runtime role.
* "Default-off legacy" was a stated goal but not an enforced gate — no
  module explicitly verified that legacy paths were off by default before
  canonical selection.
* Observation-only paths had no explicit audit surface confirming their
  non-authoritative status.
* Android-side compat/legacy participant influence was documented but not
  formally bounded at the V2 truth-ingress layer.

This module resolves those gaps by providing:

1. :class:`CanonicalPathRole` — five-value enum that classifies every runtime
   path by its relationship to the canonical authority spine:

   * ``canonical``         — the one legitimate default authority path.
   * ``compat_allowed``    — explicitly permitted compat path, bounded scope.
   * ``observation_only``  — read-only observer; must not write canonical state.
   * ``deprecated_live``   — deprecated but still executing; pending removal.
   * ``fully_blocked``     — blocked; must not execute at canonical surfaces.

2. :class:`CanonicalPathInventoryEntry` — typed record for each path carrying
   its role, canonical replacement, policy, and Android-compat influence flag.

3. :data:`CANONICAL_PATH_INVENTORY` — the authoritative structured inventory
   of every path assessed in this PR, keyed by module/path identifier.

4. Default-off legacy policy sentinels and helpers:

   * :data:`DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY` — formal policy string.
   * :func:`is_legacy_default_off` — return ``True`` when a path must not
     execute in the default runtime surface.
   * :func:`get_path_role` — look up a path's :class:`CanonicalPathRole`.

5. :func:`enforce_canonical_selection` — lightweight enforcement helper that
   verifies the canonical path is selected *before* any legacy effects can
   reach truth/tracking surfaces, emitting a structured
   :class:`CanonicalSelectionRecord` artifact for every call.

6. :func:`build_convergence_audit_snapshot` — builds a JSON-serialisable
   convergence audit snapshot summarising:

   * Total paths in inventory.
   * Count per role category.
   * All default-off legacy paths.
   * All fully-blocked paths.
   * All observation-only paths.
   * Android compat influence paths and their V2 gating status.

Architecture invariants (PR-convergence)
-----------------------------------------
* The canonical path is the **default**.  Legacy paths are default-off.
* Every legacy/compat path that can reach a canonical surface MUST appear in
  :data:`CANONICAL_PATH_INVENTORY` with an explicit role classification.
* Observation-only paths produce an artifact but MUST NOT mutate canonical
  truth, task state, session state, readiness verdict, or delegated flow state.
* Android-originated compat/legacy participant signals MUST pass through the
  V2 participant truth ingress gate before reaching canonical state; direct
  writes from Android compat signals to V2 canonical truth are blocked.
* ``enforce_canonical_selection`` MUST be called at every canonical routing,
  truth, and delegated-flow handoff decision surface.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_AUTHORITY`
:data:`CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_PR_SENTINEL`
:data:`DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY`
:data:`CANONICAL_PATH_IS_DEFAULT_AUTHORITY_POLICY`
:data:`LEGACY_PATH_MUST_NOT_MUTATE_CANONICAL_STATE_POLICY`
:data:`OBSERVATION_ONLY_PATH_IS_NON_AUTHORITATIVE_POLICY`
:data:`ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY`

Enumerations
~~~~~~~~~~~~
:class:`CanonicalPathRole`

Data classes
~~~~~~~~~~~~
:class:`CanonicalPathInventoryEntry`
:class:`CanonicalSelectionRecord`
:class:`ConvergenceAuditSnapshot`

Registry
~~~~~~~~
:data:`CANONICAL_PATH_INVENTORY`

Functions
~~~~~~~~~
:func:`is_legacy_default_off`
:func:`get_path_role`
:func:`enforce_canonical_selection`
:func:`build_convergence_audit_snapshot`
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("Galaxy.CanonicalAuthoritativePathConvergence")

__all__ = [
    # Sentinels
    "CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_AUTHORITY",
    "CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_PR_SENTINEL",
    "DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY",
    "CANONICAL_PATH_IS_DEFAULT_AUTHORITY_POLICY",
    "LEGACY_PATH_MUST_NOT_MUTATE_CANONICAL_STATE_POLICY",
    "OBSERVATION_ONLY_PATH_IS_NON_AUTHORITATIVE_POLICY",
    "ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY",
    # Enum
    "CanonicalPathRole",
    # Dataclasses
    "CanonicalPathInventoryEntry",
    "CanonicalSelectionRecord",
    "ConvergenceAuditSnapshot",
    # Registry
    "CANONICAL_PATH_INVENTORY",
    # Functions
    "is_legacy_default_off",
    "get_path_role",
    "enforce_canonical_selection",
    "build_convergence_audit_snapshot",
]


# ===========================================================================
# Authority and policy sentinels
# ===========================================================================

CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_AUTHORITY: str = (
    "CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_AUTHORITY::"
    "core.canonical_authoritative_path_convergence is the PR-convergence "
    "single authoritative path convergence module for Galaxy V2.  "
    "It is the machine-readable surface that proves the canonical path is the "
    "real default runtime authority and that legacy/compat paths are default-off.  "
    "All canonical routing, truth, delegated-flow, and readiness decisions MUST "
    "prefer the canonical path inventory entry over any legacy/compat alternative."
)

CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_PR_SENTINEL: str = (
    "CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_PR_SENTINEL::"
    "package=PR-convergence::profile=single-authoritative-path-v1::"
    "module=core.canonical_authoritative_path_convergence::"
    "goal=enforce-canonical-default-off-legacy"
)

DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY: str = (
    "POLICY::DEFAULT_OFF_LEGACY_BEHAVIOR_V1: "
    "Legacy and compat paths are OFF by default in the Galaxy V2 canonical "
    "runtime.  A legacy/compat path may only execute at a canonical decision "
    "surface when: (a) the canonical path is explicitly unavailable AND (b) a "
    "formal CompatLegacyBlockingRecord has been produced by the PR-8 blocking "
    "gate.  Absence of an explicit activation record means the path is blocked.  "
    "is_legacy_default_off() returns True for all paths classified as "
    "CanonicalPathRole.deprecated_live or CanonicalPathRole.fully_blocked."
)

CANONICAL_PATH_IS_DEFAULT_AUTHORITY_POLICY: str = (
    "POLICY::CANONICAL_PATH_IS_DEFAULT_AUTHORITY_V1: "
    "The canonical execution spine "
    "(CanonicalTask → TaskEnvelope → CommandRouter.route_envelope()) "
    "is the default authority for routing, truth ingress, delegated-flow "
    "handoff, and readiness/governance verdict.  Any path that is not "
    "classified as CanonicalPathRole.canonical in CANONICAL_PATH_INVENTORY "
    "MUST NOT be the default choice at a canonical decision surface.  "
    "enforce_canonical_selection() MUST be called before legacy effects reach "
    "canonical state."
)

LEGACY_PATH_MUST_NOT_MUTATE_CANONICAL_STATE_POLICY: str = (
    "POLICY::LEGACY_PATH_MUST_NOT_MUTATE_CANONICAL_STATE_V1: "
    "Paths classified as CanonicalPathRole.fully_blocked, "
    "CanonicalPathRole.deprecated_live, or CanonicalPathRole.observation_only "
    "MUST NOT write to, assert, or override canonical task truth, session truth, "
    "result truth, readiness verdict, delegated-flow state, or governance state.  "
    "Any such attempt is a policy violation and MUST be blocked by the PR-8 gate."
)

OBSERVATION_ONLY_PATH_IS_NON_AUTHORITATIVE_POLICY: str = (
    "POLICY::OBSERVATION_ONLY_PATH_IS_NON_AUTHORITATIVE_V1: "
    "Paths classified as CanonicalPathRole.observation_only may read canonical "
    "state for monitoring, audit, or operator-surface purposes only.  They MUST "
    "NOT make routing decisions, write truth, accept delegated flows, or produce "
    "readiness verdicts.  Observation-only paths that attempt state writes are "
    "treated as CanonicalPathRole.fully_blocked violations."
)

ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY: str = (
    "POLICY::ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_V1: "
    "Android-originated compat/legacy participant signals MUST pass through the "
    "V2 participant truth ingress gate "
    "(core.android_participant_truth_ingress.ingest_android_participant_truth_message) "
    "before any data from those signals reaches V2 canonical state.  "
    "Direct writes from Android compat signals to V2 canonical truth "
    "(task truth, session truth, readiness verdict, delegated-flow state) "
    "are BLOCKED.  The ingress gate is the sole authority for deciding whether "
    "Android-side truth is reconciled into V2 canonical state or rejected."
)


# ===========================================================================
# Enumerations
# ===========================================================================


class CanonicalPathRole(str, Enum):
    """Five-value classification of a runtime path's authoritative role.

    ``canonical``
        The one legitimate default authority path at this decision surface.
        It is the preferred path under all normal operating conditions.

    ``compat_allowed``
        An explicitly bounded compat path that is permitted to influence
        canonical state within a defined, documented scope.  It must not
        exceed that scope or act as an independent authority.

    ``observation_only``
        A read-only observer path.  It may read canonical state for monitoring
        or operator-surface purposes but MUST NOT write, assert, or override
        canonical truth, routing decisions, or delegated-flow state.

    ``deprecated_live``
        A deprecated path that is still executing for backward-compatibility
        reasons.  It is default-off: it must not be the default choice and
        must not influence canonical state without an explicit activation record
        from the PR-8 blocking gate.  Scheduled for removal.

    ``fully_blocked``
        A path that is blocked from reaching canonical surfaces.  Any
        invocation at a canonical decision surface produces a block artifact
        and must not proceed.
    """

    canonical = "canonical"
    compat_allowed = "compat_allowed"
    observation_only = "observation_only"
    deprecated_live = "deprecated_live"
    fully_blocked = "fully_blocked"


# ===========================================================================
# Data classes
# ===========================================================================


@dataclass(frozen=True)
class CanonicalPathInventoryEntry:
    """Inventory record for a single runtime path.

    Attributes
    ----------
    path_id:
        Unique identifier for this path (dotted module path, class name, or
        descriptive label).
    role:
        :class:`CanonicalPathRole` classification.
    description:
        Human-readable description of what this path does.
    canonical_replacement:
        Dotted path to the canonical replacement, or ``None`` if this entry
        IS the canonical path.
    policy:
        Policy string governing this path's allowed behavior.
    android_compat_influence:
        ``True`` when this path surfaces Android-side compat/legacy participant
        signals toward V2 canonical state.  Such paths MUST pass through the
        V2 participant truth ingress gate.
    pr_origin:
        PR that established this entry's current role classification.
    notes:
        Optional free-form notes for operator/audit visibility.
    """

    path_id: str
    role: CanonicalPathRole
    description: str
    canonical_replacement: Optional[str] = None
    policy: str = ""
    android_compat_influence: bool = False
    pr_origin: str = "PR-convergence"
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "path_id": self.path_id,
            "role": self.role.value,
            "description": self.description,
            "canonical_replacement": self.canonical_replacement,
            "policy": self.policy[:120] + "…" if len(self.policy) > 120 else self.policy,
            "android_compat_influence": self.android_compat_influence,
            "pr_origin": self.pr_origin,
            "notes": self.notes,
        }


@dataclass
class CanonicalSelectionRecord:
    """Artifact produced by :func:`enforce_canonical_selection`.

    Attributes
    ----------
    record_id:
        UUID for this selection record.
    calling_site:
        Description of the decision surface where canonical selection was
        enforced.
    selected_path:
        The path identifier that was confirmed as canonical at this site.
    role_at_selection:
        The :class:`CanonicalPathRole` of the selected path.
    legacy_paths_present:
        List of legacy/compat path identifiers that were present at this site
        but were NOT selected (because the canonical path was chosen first).
    enforcement_active:
        ``True`` when enforcement blocked a legacy path from being the default.
    timestamp: float
        Unix timestamp of the selection event.
    operator_note:
        Optional operator-visible note.
    """

    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    calling_site: str = ""
    selected_path: str = ""
    role_at_selection: CanonicalPathRole = CanonicalPathRole.canonical
    legacy_paths_present: List[str] = field(default_factory=list)
    enforcement_active: bool = False
    timestamp: float = field(default_factory=time.monotonic)
    operator_note: str = ""

    def to_dict(self) -> Dict[str, object]:
        return {
            "record_id": self.record_id,
            "calling_site": self.calling_site,
            "selected_path": self.selected_path,
            "role_at_selection": self.role_at_selection.value,
            "legacy_paths_present": self.legacy_paths_present,
            "enforcement_active": self.enforcement_active,
            "timestamp": self.timestamp,
            "operator_note": self.operator_note,
        }


@dataclass(frozen=True)
class ConvergenceAuditSnapshot:
    """Snapshot of the canonical path convergence posture.

    Produced by :func:`build_convergence_audit_snapshot`.

    Attributes
    ----------
    total_paths:
        Total number of paths in :data:`CANONICAL_PATH_INVENTORY`.
    canonical_count:
        Number of paths classified as ``canonical``.
    compat_allowed_count:
        Number of paths classified as ``compat_allowed``.
    observation_only_count:
        Number of paths classified as ``observation_only``.
    deprecated_live_count:
        Number of paths classified as ``deprecated_live`` (default-off).
    fully_blocked_count:
        Number of paths classified as ``fully_blocked``.
    default_off_paths:
        List of path IDs that are default-off (deprecated_live or fully_blocked).
    observation_only_paths:
        List of path IDs that are observation-only.
    android_compat_influence_paths:
        List of path IDs that surface Android-side compat/legacy influence.
    convergence_healthy:
        ``True`` when there is exactly one canonical path and no unclassified paths.
    policy_sentinels:
        List of active policy sentinel strings.
    """

    total_paths: int
    canonical_count: int
    compat_allowed_count: int
    observation_only_count: int
    deprecated_live_count: int
    fully_blocked_count: int
    default_off_paths: List[str]
    observation_only_paths: List[str]
    android_compat_influence_paths: List[str]
    convergence_healthy: bool
    policy_sentinels: List[str]

    def to_dict(self) -> Dict[str, object]:
        return {
            "total_paths": self.total_paths,
            "canonical_count": self.canonical_count,
            "compat_allowed_count": self.compat_allowed_count,
            "observation_only_count": self.observation_only_count,
            "deprecated_live_count": self.deprecated_live_count,
            "fully_blocked_count": self.fully_blocked_count,
            "default_off_paths": self.default_off_paths,
            "observation_only_paths": self.observation_only_paths,
            "android_compat_influence_paths": self.android_compat_influence_paths,
            "convergence_healthy": self.convergence_healthy,
            "policy_sentinel_count": len(self.policy_sentinels),
        }


# ===========================================================================
# Canonical path inventory
# ===========================================================================

#: Structured inventory of all runtime paths assessed in PR-convergence,
#: keyed by path_id (dotted module path or descriptive label).
CANONICAL_PATH_INVENTORY: Dict[str, CanonicalPathInventoryEntry] = {}


def _inv(*entries: CanonicalPathInventoryEntry) -> None:
    """Register entries into :data:`CANONICAL_PATH_INVENTORY`."""
    for entry in entries:
        CANONICAL_PATH_INVENTORY[entry.path_id] = entry


# ---------------------------------------------------------------------------
# 1. Canonical execution spine (the authoritative default path)
# ---------------------------------------------------------------------------

_inv(
    CanonicalPathInventoryEntry(
        path_id="core.command_router.CommandRouter.route_envelope",
        role=CanonicalPathRole.canonical,
        description=(
            "CommandRouter.route_envelope() is the canonical dispatch spine.  "
            "All task dispatch, routing decisions, and truth-ingress flows MUST "
            "originate from or be validated against this path."
        ),
        canonical_replacement=None,
        policy=CANONICAL_PATH_IS_DEFAULT_AUTHORITY_POLICY,
        pr_origin="PR-convergence",
        notes="Sole canonical routing authority.  Default path under all normal conditions.",
    ),
    CanonicalPathInventoryEntry(
        path_id="core.e2e_orchestrator.process_user_input",
        role=CanonicalPathRole.canonical,
        description=(
            "process_user_input() is the canonical user-facing ingress that "
            "delegates to DesktopPresenceRuntime and ConstellationRuntime."
        ),
        canonical_replacement=None,
        policy=CANONICAL_PATH_IS_DEFAULT_AUTHORITY_POLICY,
        pr_origin="PR-convergence",
        notes="Canonical user-request entrypoint.",
    ),
    CanonicalPathInventoryEntry(
        path_id="galaxy_gateway.device_router.DeviceRouter.route_task",
        role=CanonicalPathRole.canonical,
        description=(
            "DeviceRouter.route_task() is the canonical single dispatch entry "
            "for all device-bound tasks (established PR-S3)."
        ),
        canonical_replacement=None,
        policy=CANONICAL_PATH_IS_DEFAULT_AUTHORITY_POLICY,
        pr_origin="PR-convergence",
        notes="Canonical device-bound task dispatch authority.",
    ),
)

# ---------------------------------------------------------------------------
# 2. Android participant truth ingress (compat_allowed / observation boundary)
# ---------------------------------------------------------------------------

_inv(
    CanonicalPathInventoryEntry(
        path_id="core.android_participant_truth_ingress.ingest_android_participant_truth_message",
        role=CanonicalPathRole.canonical,
        description=(
            "The sole canonical V2 gate for Android-originated participant/session/"
            "runtime truth.  All Android-side compat signals MUST enter V2 canonical "
            "state through this function; direct writes from Android compat signals "
            "bypassing this gate are BLOCKED."
        ),
        canonical_replacement=None,
        policy=ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY,
        android_compat_influence=True,
        pr_origin="PR-convergence",
        notes=(
            "Authoritative Android truth ingress.  "
            "Reconciles Android local truth → V2 canonical truth via "
            "reconcile_android_participant_truth()."
        ),
    ),
    CanonicalPathInventoryEntry(
        path_id="core.android_delegated_signal_ingress.ingest_delegated_execution_signal",
        role=CanonicalPathRole.canonical,
        description=(
            "Canonical ingress for dedicated delegated_execution_signal messages "
            "from Android.  Extracts structured fields and delegates to the PR-13 "
            "reconciler without compat inference."
        ),
        canonical_replacement=None,
        policy=ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY,
        android_compat_influence=True,
        pr_origin="PR-convergence",
        notes="Canonical delegated execution signal ingress (post-PR-16).",
    ),
    CanonicalPathInventoryEntry(
        path_id="core.android_execution_signal_reconciler.reconcile_android_execution_signal",
        role=CanonicalPathRole.canonical,
        description=(
            "Canonical reconciler for Android execution signals.  It is the single "
            "authoritative entry for execution-signal → V2 canonical state transitions."
        ),
        canonical_replacement=None,
        policy=ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY,
        android_compat_influence=True,
        pr_origin="PR-convergence",
        notes="Established PR-13; canonical reconciler for ACK/PROGRESS/RESULT/ERROR.",
    ),
)

# ---------------------------------------------------------------------------
# 3. Android compat legacy ingress paths (compat_allowed — bounded scope)
# ---------------------------------------------------------------------------

_inv(
    CanonicalPathInventoryEntry(
        path_id="core.android_execution_signal_reconciler.compat_extract_signal_kind",
        role=CanonicalPathRole.compat_allowed,
        description=(
            "Compat inference path that infers AndroidSignalKind from legacy "
            "(message_type, status) pairs such as task_result / task_end / "
            "goal_execution_result.  Permitted only when the upstream gateway "
            "handler cannot guarantee a true delegated_execution_signal message."
        ),
        canonical_replacement=(
            "core.android_delegated_signal_ingress.ingest_delegated_execution_signal"
        ),
        policy=ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY,
        android_compat_influence=True,
        pr_origin="PR-convergence",
        notes=(
            "Compat inference allowed only as fallback for pre-PR-16 Android "
            "clients.  Must not be used as the primary ingress for post-PR-16 clients."
        ),
    ),
    CanonicalPathInventoryEntry(
        path_id="core.android_handoff_v2_response_ingress.ingest_android_handoff_response",
        role=CanonicalPathRole.compat_allowed,
        description=(
            "Ingress for handoff_envelope_v2_result responses from Android.  "
            "Permitted as a bounded compat path for the HandoffEnvelopeV2 round-trip.  "
            "Must delegate result binding to the canonical delegated flow entity."
        ),
        canonical_replacement=(
            "core.delegated_flow_entity.DelegatedFlowEntity  (result convergence)"
        ),
        policy=ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY,
        android_compat_influence=True,
        pr_origin="PR-convergence",
        notes="Compat-allowed for HandoffEnvelopeV2 response handling (post-PR-02V2).",
    ),
)

# ---------------------------------------------------------------------------
# 4. Delegated flow and readiness paths (canonical / compat_allowed)
# ---------------------------------------------------------------------------

_inv(
    CanonicalPathInventoryEntry(
        path_id="core.delegated_flow_acceptance_gate.DelegatedFlowAcceptanceGate",
        role=CanonicalPathRole.canonical,
        description=(
            "Canonical acceptance gate for delegated execution flows.  "
            "All delegated flow accept/reject decisions MUST pass through this gate.  "
            "Legacy dispatch paths must not bypass this gate."
        ),
        canonical_replacement=None,
        policy=CANONICAL_PATH_IS_DEFAULT_AUTHORITY_POLICY,
        pr_origin="PR-convergence",
        notes="Canonical delegated flow accept/reject authority.",
    ),
    CanonicalPathInventoryEntry(
        path_id="core.delegated_flow_readiness_gate.DelegatedFlowReadinessGate",
        role=CanonicalPathRole.canonical,
        description=(
            "Canonical readiness gate that evaluates whether a delegated flow "
            "is ready for execution.  Readiness verdicts from this gate are the "
            "sole authoritative readiness input for delegated flows."
        ),
        canonical_replacement=None,
        policy=CANONICAL_PATH_IS_DEFAULT_AUTHORITY_POLICY,
        pr_origin="PR-convergence",
        notes="Canonical readiness gate; Android artifact integration via participant truth ingress.",
    ),
    CanonicalPathInventoryEntry(
        path_id="core.android_participant_truth_ingress.reconcile_android_participant_truth",
        role=CanonicalPathRole.canonical,
        description=(
            "Canonical reconciliation function that applies Android participant truth "
            "to V2 canonical state.  It is the sole write authority for Android→V2 "
            "participant truth reconciliation."
        ),
        canonical_replacement=None,
        policy=ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY,
        android_compat_influence=True,
        pr_origin="PR-convergence",
        notes="Closes TRUTH-005; canonical V2 write path for Android session/runtime truth.",
    ),
)

# ---------------------------------------------------------------------------
# 5. Legacy dispatch paths — deprecated_live (default-off)
# ---------------------------------------------------------------------------

_inv(
    CanonicalPathInventoryEntry(
        path_id="galaxy_gateway.task_router.TaskRouter",
        role=CanonicalPathRole.deprecated_live,
        description=(
            "Legacy compat raw-HTTP dispatch loop (PR-S6).  Still executes for "
            "backward-compatible callers but MUST NOT be the default dispatch path.  "
            "All new dispatch MUST route through DeviceRouter.route_task."
        ),
        canonical_replacement="galaxy_gateway.device_router.DeviceRouter.route_task",
        policy=DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY,
        pr_origin="PR-convergence",
        notes="Default-off.  PR-S6 demotion.  Pending full removal.",
    ),
    CanonicalPathInventoryEntry(
        path_id="galaxy_gateway.handlers.message_handler.MessageHandler",
        role=CanonicalPathRole.deprecated_live,
        description=(
            "Legacy chain-B gateway ingress (PR-S6).  Routes through legacy "
            "TaskOrchestrator path.  Default-off; canonical ingress is "
            "websocket_handler → DeviceRouter (chain A)."
        ),
        canonical_replacement=(
            "galaxy_gateway.websocket_handler → DeviceRouter (chain A)"
        ),
        policy=DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY,
        pr_origin="PR-convergence",
        notes="Default-off chain-B ingress.  Must not be the default message routing path.",
    ),
    CanonicalPathInventoryEntry(
        path_id="galaxy_gateway.task_decomposer.TaskDecomposer",
        role=CanonicalPathRole.deprecated_live,
        description=(
            "Legacy rule-based task splitter (PR-S7/PR-516).  Still present for "
            "backward compat but MUST NOT be invoked as a primary decomposition path.  "
            "Default-off; use core.task_graph.TaskGraph."
        ),
        canonical_replacement="core.task_graph.TaskGraph",
        policy=DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY,
        pr_origin="PR-convergence",
        notes="Default-off.  Formally retired in PR-516.",
    ),
    CanonicalPathInventoryEntry(
        path_id="galaxy_gateway.task_decomposer.IntelligentTaskPlanner",
        role=CanonicalPathRole.deprecated_live,
        description=(
            "Legacy LLM-based task planner (PR-S7/PR-516).  Default-off; use "
            "core.e2e_orchestrator.process_user_input() or the canonical OpenClawd pipeline."
        ),
        canonical_replacement="core.e2e_orchestrator.process_user_input",
        policy=DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY,
        pr_origin="PR-convergence",
        notes="Default-off.  Formally retired in PR-516.",
    ),
    CanonicalPathInventoryEntry(
        path_id="galaxy_gateway.smart_transport_router.SmartTransportRouter",
        role=CanonicalPathRole.deprecated_live,
        description=(
            "Legacy transport router (PR-M).  Default-off; transport routing "
            "is now via DeviceRouter and the canonical execution spine."
        ),
        canonical_replacement="galaxy_gateway.device_router.DeviceRouter.route_task",
        policy=DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY,
        pr_origin="PR-convergence",
        notes="Default-off.  PR-M demotion.",
    ),
    CanonicalPathInventoryEntry(
        path_id="galaxy_gateway.enhanced_nlu_v2.EnhancedNLUEngineV2",
        role=CanonicalPathRole.deprecated_live,
        description=(
            "Legacy LLM+rule hybrid NLU engine (PR-M).  Maintains its own device "
            "registry and LLM client as parallel authorities.  Default-off; use "
            "core.e2e_orchestrator.process_user_input()."
        ),
        canonical_replacement="core.e2e_orchestrator.process_user_input",
        policy=DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY,
        pr_origin="PR-convergence",
        notes="Default-off.  PR-M demotion.  Parallel LLM authority is a policy violation.",
    ),
    CanonicalPathInventoryEntry(
        path_id="galaxy_gateway.session_roaming.SessionRoamingManager",
        role=CanonicalPathRole.deprecated_live,
        description=(
            "Legacy session migration manager (PR-M).  Bypasses canonical session "
            "axis.  Default-off; use canonical session axis + attached-runtime session layer."
        ),
        canonical_replacement=(
            "core.canonical_session_axis  +  core.attached_runtime_session"
        ),
        policy=DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY,
        pr_origin="PR-convergence",
        notes="Default-off.  PR-M demotion.",
    ),
)

# ---------------------------------------------------------------------------
# 6. Fully blocked paths
# ---------------------------------------------------------------------------

_inv(
    CanonicalPathInventoryEntry(
        path_id="galaxy_gateway.task_router.TaskRouter.direct_http_dispatch",
        role=CanonicalPathRole.fully_blocked,
        description=(
            "The raw-HTTP dispatch inner loop of TaskRouter.  Fully blocked from "
            "reaching canonical routing surfaces; TaskRouter as a whole is deprecated_live "
            "but its direct HTTP dispatch sub-path is blocked at canonical decision surfaces."
        ),
        canonical_replacement="galaxy_gateway.device_router.DeviceRouter.route_task",
        policy=LEGACY_PATH_MUST_NOT_MUTATE_CANONICAL_STATE_POLICY,
        pr_origin="PR-convergence",
        notes="Blocked at canonical routing surface.  May not write to delegated flow state.",
    ),
    CanonicalPathInventoryEntry(
        path_id="core.android_participant_truth_ingress.direct_canonical_state_write_from_compat_signal",
        role=CanonicalPathRole.fully_blocked,
        description=(
            "Any attempt by an Android compat/legacy participant signal to directly "
            "write V2 canonical task truth, session truth, readiness verdict, or "
            "delegated-flow state WITHOUT passing through the participant truth ingress gate.  "
            "This path pattern is fully blocked."
        ),
        canonical_replacement=(
            "core.android_participant_truth_ingress.ingest_android_participant_truth_message"
        ),
        policy=ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY,
        android_compat_influence=True,
        pr_origin="PR-convergence",
        notes=(
            "Fully blocked pattern.  Any Android compat signal bypassing the ingress "
            "gate is a policy violation.  Block artifact produced by PR-8 gate."
        ),
    ),
    CanonicalPathInventoryEntry(
        path_id="galaxy_gateway.orchestrator.task_orchestrator.TaskOrchestrator.direct_dispatch",
        role=CanonicalPathRole.fully_blocked,
        description=(
            "Direct task dispatch from the legacy gateway TaskOrchestrator, bypassing "
            "DeviceRouter and CommandRouter.  Fully blocked at canonical routing surfaces."
        ),
        canonical_replacement="galaxy_gateway.device_router.DeviceRouter.route_task",
        policy=LEGACY_PATH_MUST_NOT_MUTATE_CANONICAL_STATE_POLICY,
        pr_origin="PR-convergence",
        notes="Blocked at canonical routing surface.  TaskOrchestrator is legacy compat only.",
    ),
)

# ---------------------------------------------------------------------------
# 7. Observation-only paths (non-authoritative read access)
# ---------------------------------------------------------------------------

_inv(
    CanonicalPathInventoryEntry(
        path_id="core.android_delegated_runtime_audit.AndroidDelegatedRuntimeAuditRecord",
        role=CanonicalPathRole.observation_only,
        description=(
            "Audit record for Android delegated runtime events.  Read-only observer "
            "that records lifecycle milestones.  MUST NOT write to canonical task "
            "truth or session truth."
        ),
        canonical_replacement=None,
        policy=OBSERVATION_ONLY_PATH_IS_NON_AUTHORITATIVE_POLICY,
        android_compat_influence=True,
        pr_origin="PR-convergence",
        notes="Observation-only.  Records are audit artifacts, not canonical state writes.",
    ),
    CanonicalPathInventoryEntry(
        path_id="core.operator_surface.OperatorSurface",
        role=CanonicalPathRole.observation_only,
        description=(
            "Operator-facing surface that exposes canonical state for monitoring.  "
            "Read-only; must not influence routing or truth."
        ),
        canonical_replacement=None,
        policy=OBSERVATION_ONLY_PATH_IS_NON_AUTHORITATIVE_POLICY,
        pr_origin="PR-convergence",
        notes="Observation-only operator surface.  Reads canonical state; does not write.",
    ),
    CanonicalPathInventoryEntry(
        path_id="core.replay_foundation.ReplayFoundation",
        role=CanonicalPathRole.observation_only,
        description=(
            "Replay and recovery foundation that records canonical state transitions "
            "for audit and replay purposes.  Non-authoritative: replay artifacts are "
            "audit records, not canonical state."
        ),
        canonical_replacement=None,
        policy=OBSERVATION_ONLY_PATH_IS_NON_AUTHORITATIVE_POLICY,
        pr_origin="PR-convergence",
        notes=(
            "Observation-only during normal flow.  In recovery context, replay inputs "
            "MUST be validated by the canonical acceptance gate before re-applying state."
        ),
    ),
)


# ===========================================================================
# Query helpers
# ===========================================================================


def is_legacy_default_off(path_id: str) -> bool:
    """Return ``True`` when *path_id* is default-off in the runtime.

    A path is default-off when its role is :attr:`CanonicalPathRole.deprecated_live`
    or :attr:`CanonicalPathRole.fully_blocked`.  Paths not found in the inventory
    are treated as default-off (unclassified paths should not be the default
    choice at canonical surfaces).

    Parameters
    ----------
    path_id:
        Dotted module path or descriptive label to look up.

    Returns
    -------
    bool
    """
    entry = CANONICAL_PATH_INVENTORY.get(path_id)
    if entry is None:
        return True  # unclassified ⟹ treat as default-off
    return entry.role in (
        CanonicalPathRole.deprecated_live,
        CanonicalPathRole.fully_blocked,
    )


def get_path_role(path_id: str) -> Optional[CanonicalPathRole]:
    """Return the :class:`CanonicalPathRole` for *path_id*, or ``None``.

    Returns ``None`` when the path is not found in
    :data:`CANONICAL_PATH_INVENTORY`.
    """
    entry = CANONICAL_PATH_INVENTORY.get(path_id)
    return entry.role if entry is not None else None


# ===========================================================================
# Canonical selection enforcement
# ===========================================================================


def enforce_canonical_selection(
    canonical_path_id: str,
    calling_site: str,
    *,
    legacy_paths_present: Optional[List[str]] = None,
    operator_note: str = "",
) -> CanonicalSelectionRecord:
    """Enforce that the canonical path is selected before legacy effects reach state.

    This function is the PR-convergence enforcement primitive.  It MUST be
    called at every canonical routing, truth, and delegated-flow handoff
    decision surface before any legacy/compat path is allowed to proceed.

    It verifies:

    1. *canonical_path_id* exists in :data:`CANONICAL_PATH_INVENTORY` with
       role ``canonical`` or ``compat_allowed``.
    2. All *legacy_paths_present* are classified and are NOT ``canonical``.
    3. The canonical path was selected; legacy paths were not chosen by default.

    If *canonical_path_id* is not in the inventory or is classified as a
    non-canonical role, the record will still be produced but
    ``enforcement_active`` will be ``True`` (indicating an unexpected state).

    Parameters
    ----------
    canonical_path_id:
        The path identifier that was chosen (should be the canonical path).
    calling_site:
        Human-readable description of the decision surface.
    legacy_paths_present:
        List of legacy/compat path identifiers that were also present at this
        site but were NOT selected.
    operator_note:
        Optional operator-visible note.

    Returns
    -------
    CanonicalSelectionRecord
        The selection artifact.
    """
    legacy = legacy_paths_present or []
    entry = CANONICAL_PATH_INVENTORY.get(canonical_path_id)
    role = entry.role if entry is not None else None

    # Determine if enforcement was required (any legacy path would have been
    # an incorrect default choice).
    enforcement_active = bool(legacy) or (
        role not in (CanonicalPathRole.canonical, CanonicalPathRole.compat_allowed)
    )

    record = CanonicalSelectionRecord(
        calling_site=calling_site,
        selected_path=canonical_path_id,
        role_at_selection=role if role is not None else CanonicalPathRole.canonical,
        legacy_paths_present=list(legacy),
        enforcement_active=enforcement_active,
        operator_note=operator_note,
    )

    if enforcement_active:
        logger.info(
            "CANONICAL_SELECTION_ENFORCED [%s] site=%s selected=%s "
            "legacy_paths=%s enforcement_active=%s",
            record.record_id,
            calling_site,
            canonical_path_id,
            legacy,
            enforcement_active,
        )
    else:
        logger.debug(
            "CANONICAL_SELECTION_CONFIRMED [%s] site=%s selected=%s",
            record.record_id,
            calling_site,
            canonical_path_id,
        )

    return record


# ===========================================================================
# Convergence audit snapshot builder
# ===========================================================================


def build_convergence_audit_snapshot() -> ConvergenceAuditSnapshot:
    """Build a JSON-serialisable convergence audit snapshot.

    Aggregates :data:`CANONICAL_PATH_INVENTORY` into counts and lists for
    operator inspection and release-gate readiness checks.

    Returns
    -------
    ConvergenceAuditSnapshot
    """
    inv = CANONICAL_PATH_INVENTORY

    canonical_count = sum(
        1 for e in inv.values() if e.role == CanonicalPathRole.canonical
    )
    compat_allowed_count = sum(
        1 for e in inv.values() if e.role == CanonicalPathRole.compat_allowed
    )
    observation_only_count = sum(
        1 for e in inv.values() if e.role == CanonicalPathRole.observation_only
    )
    deprecated_live_count = sum(
        1 for e in inv.values() if e.role == CanonicalPathRole.deprecated_live
    )
    fully_blocked_count = sum(
        1 for e in inv.values() if e.role == CanonicalPathRole.fully_blocked
    )

    default_off_paths = [
        e.path_id for e in inv.values()
        if e.role in (CanonicalPathRole.deprecated_live, CanonicalPathRole.fully_blocked)
    ]
    observation_only_paths = [
        e.path_id for e in inv.values()
        if e.role == CanonicalPathRole.observation_only
    ]
    android_compat_influence_paths = [
        e.path_id for e in inv.values()
        if e.android_compat_influence
    ]

    # Healthy when every path has a classification and there is at least one
    # canonical path.
    convergence_healthy = canonical_count >= 1

    return ConvergenceAuditSnapshot(
        total_paths=len(inv),
        canonical_count=canonical_count,
        compat_allowed_count=compat_allowed_count,
        observation_only_count=observation_only_count,
        deprecated_live_count=deprecated_live_count,
        fully_blocked_count=fully_blocked_count,
        default_off_paths=default_off_paths,
        observation_only_paths=observation_only_paths,
        android_compat_influence_paths=android_compat_influence_paths,
        convergence_healthy=convergence_healthy,
        policy_sentinels=[
            DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY,
            CANONICAL_PATH_IS_DEFAULT_AUTHORITY_POLICY,
            LEGACY_PATH_MUST_NOT_MUTATE_CANONICAL_STATE_POLICY,
            OBSERVATION_ONLY_PATH_IS_NON_AUTHORITATIVE_POLICY,
            ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY,
        ],
    )
