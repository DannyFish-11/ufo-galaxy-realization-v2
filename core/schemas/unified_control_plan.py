#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.schemas.unified_control_plan — Canonical Unified Control Plan
===================================================================

PR-19 — OpenClawd Unified Control Core

Defines :class:`UnifiedControlPlan`: the **single canonical control artifact**
produced by :class:`~core.openclawd.OpenClawd` during every request lifecycle.

Architecture
------------

.. code-block:: text

    RUNTIME SHELL (DesktopPresenceRuntime)
        Owns: session lifecycle, tri-state, continuous multimodal ingress,
              shell-facing status projection
        Provides to OpenClawd: runtime_session_id, PerceptionFrame

    OPENCLAWD — UNIFIED CONTROL CORE  ← authority_role = subject_decision_authority
        Owns: perception interpretation, model selection, execution planning,
              fallback, diagnostics, lifecycle decisions
        Produces: UnifiedControlPlan  ← the canonical control artifact

    EXECUTION / SUBSTRATE / ORCHESTRATION LAYERS
        Execute plans produced by OpenClawd; they do NOT become decision authority
        CommandRouter, SwarmCoordinator, AgentKernel remain submodules

The :class:`UnifiedControlPlan` is the stable contract that:

* captures perception truth (from :class:`~core.perception.canonical_perception_state.CanonicalPerceptionState`)
* captures model supply truth (from :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`)
* records the chosen model decision and execution decision
* records fallback intent, lifecycle target, and diagnostics summary
* preserves the authority chain so every downstream consumer can verify
  that OpenClawd was the decision authority
* provides shell-facing projection hints for desktop status display

The plan is serialisable via :meth:`UnifiedControlPlan.to_dict` and is safe
for logging, diagnostics, and test assertion.

Main public API
---------------
:class:`UnifiedControlPlan`
    The canonical control plan dataclass.

:func:`build_unified_control_plan`
    Primary builder — construct a plan from the structured inputs OpenClawd
    has available at the point of decision.

:func:`unified_control_plan_summary`
    Compact serialisable summary for embedding in response metadata.

:data:`AUTHORITY_ROLE`
    String constant confirming OpenClawd's decision authority role.

Usage::

    from core.schemas.unified_control_plan import (
        UnifiedControlPlan,
        build_unified_control_plan,
        unified_control_plan_summary,
        AUTHORITY_ROLE,
    )

    plan = build_unified_control_plan(
        runtime_session_id=runtime_session_id,
        trace_id=trace_id,
        canonical_perception=perception_dict,
        canonical_model_supply=supply_dict,
        chosen_model=model_name,
        chosen_provider=provider_name,
        execution_path=execution_path,
        fallback_intent=None,
        lifecycle_target="succeeded",
        diagnostics_summary=diag_dict,
    )
    response["metadata"]["unified_control_plan"] = plan.to_dict()

PR-21 — Unified Execution Decision, Remote Mode Policy, and Fallback Governance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Adds :class:`UnifiedExecutionDecision` and :class:`FallbackDecisionRecord` as
canonical control-core-owned representations of execution direction and
fallback/downgrade governance.  These complement :class:`ChosenExecutionDecision`
(preserved for backward compatibility) with enriched rationale and explicit
downgrade tracking.

* :class:`ExecutionPath` — stable enum for local/cross_device/hybrid/none.
* :class:`FallbackKind` — enum covering all recognised downgrade/fallback types.
* :class:`UnifiedExecutionDecision` — canonical execution direction record owned
  by OpenClawd; includes execution rationale and fallback intent fields.
* :class:`FallbackDecisionRecord` — canonical governance record capturing every
  downgrade decision in a single serialisable structure.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Authority constants
# ---------------------------------------------------------------------------

#: OpenClawd's canonical decision authority role.  This constant is the
#: stable string value embedded in every :class:`UnifiedControlPlan` to
#: make the authority chain explicit and testable.
AUTHORITY_ROLE: str = "subject_decision_authority"

#: Human-readable description of OpenClawd's role in the architecture.
AUTHORITY_DESCRIPTION: str = (
    "OpenClawd is the unified control core: the final decision authority for "
    "perception interpretation, model selection, execution planning, fallback, "
    "diagnostics, and lifecycle decisions."
)

#: The runtime shell's role designation (owned by DesktopPresenceRuntime).
SHELL_ROLE: str = "runtime_shell_authority"

#: The execution substrate's role designation (owned by CommandRouter).
SUBSTRATE_ROLE: str = "execution_substrate"

#: The orchestration layer's role designation (owned by SwarmCoordinator).
ORCHESTRATION_ROLE: str = "orchestration_layer"


# ---------------------------------------------------------------------------
# DecisionPosture enum
# ---------------------------------------------------------------------------


class DecisionPosture(str, Enum):
    """High-level intent/continuum posture resolved by OpenClawd.

    Maps onto the continuum ``tri_state_phase`` vocabulary while adding
    unified control plan-level semantics.

    Values are stable lowercase strings safe for serialisation.
    """

    #: Normal autonomous operation — standard execution.
    AUTONOMOUS = "autonomous"
    #: Human-in-the-loop requested or required.
    HUMAN_IN_LOOP = "human_in_loop"
    #: Advisory / observe-only — no execution; observation and reporting only.
    ADVISORY = "advisory"
    #: Degraded / fallback mode — primary path unavailable; using downgrade path.
    DEGRADED = "degraded"
    #: Unknown posture — used when continuum is unavailable.
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# FallbackLevel enum
# ---------------------------------------------------------------------------


class FallbackLevel(str, Enum):
    """Fallback level indicating how far the execution path was downgraded.

    Levels are ordered from no fallback (``NONE``) through progressive
    downgrades to full skip (``NO_OP``).
    """

    #: No fallback — primary path executed normally.
    NONE = "none"
    #: Minor fallback — secondary provider or model used.
    MODEL_FALLBACK = "model_fallback"
    #: Text-only fallback — multimodal context dropped; text-only execution.
    TEXT_ONLY_FALLBACK = "text_only_fallback"
    #: Local fallback — remote execution unavailable; local path used.
    LOCAL_FALLBACK = "local_fallback"
    #: Advisory fallback — execution skipped; advisory/observe-only response.
    ADVISORY_FALLBACK = "advisory_fallback"
    #: Full no-op — all execution paths unavailable.
    NO_OP = "no_op"
    #: Unknown fallback state.
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# ExecutionPath enum  (PR-21)
# ---------------------------------------------------------------------------


class ExecutionPath(str, Enum):
    """Canonical execution path resolved by OpenClawd.

    Stable wire-format strings suitable for serialisation and comparison.
    """

    #: Execution confined to the local Windows host device.
    LOCAL = "local"
    #: Execution expanded to a single remote device via the cross-device substrate.
    CROSS_DEVICE = "cross_device"
    #: Both local and cross-device delegation ran for this request.
    HYBRID = "hybrid"
    #: No execution — observe/advisory/no-op path taken.
    NONE = "none"


# ---------------------------------------------------------------------------
# FallbackKind enum  (PR-21)
# ---------------------------------------------------------------------------


class FallbackKind(str, Enum):
    """Enumeration of recognised downgrade/fallback event types.

    Each value identifies the *category* of a single fallback decision that
    OpenClawd recorded in a :class:`FallbackDecisionRecord`.  Multiple
    ``FallbackKind`` entries may be present in one record when a chain of
    downgrades occurred (e.g. model fallback followed by remote→local).

    Values are stable lowercase strings safe for serialisation and comparison.
    """

    #: A secondary/fallback model or provider was used because the preferred
    #: model was unavailable or produced a capability mismatch.
    MODEL_CAPABILITY_FALLBACK = "model_capability_fallback"
    #: Native multimodal API was unavailable; fell back to text/summary input.
    NATIVE_MULTIMODAL_TO_TEXT = "native_multimodal_to_text"
    #: ``agent_runtime`` remote mode was unavailable; fell back to ``command_only``.
    AGENT_RUNTIME_TO_COMMAND_ONLY = "agent_runtime_to_command_only"
    #: Remote execution was unavailable; fell back to local execution.
    REMOTE_TO_LOCAL = "remote_to_local"
    #: Multi-device orchestration plan was simplified or omitted.
    ORCHESTRATION_DOWNGRADE = "orchestration_downgrade"
    #: Execution was blocked; only observe/advisory/no-op result allowed.
    BLOCKED_NO_OP = "blocked_no_op"
    #: Unclassified fallback — details in the human-readable reason field.
    OTHER = "other"


# ---------------------------------------------------------------------------
# ChosenModelDecision
# ---------------------------------------------------------------------------


@dataclass
class ChosenModelDecision:
    """Canonical record of the model/provider selected by OpenClawd.

    This is a placeholder-enrichable structure: at a minimum it records
    the ``provider_id`` and ``model_id`` selected.  Future enrichment may
    add cost, latency, and capability-match details.

    Attributes
    ----------
    provider_id:
        Canonical provider identifier (e.g. ``"openai"``, ``"anthropic"``).
        ``None`` when model selection was skipped or unavailable.
    model_id:
        Canonical model identifier within the provider.
        ``None`` when model selection was skipped or unavailable.
    is_native_multimodal:
        ``True`` when the selected model supports native multimodal API
        (images/audio without pre-summarisation fallback).
    selection_reason:
        Human-readable explanation of why this model was selected.
    fallback_chain:
        Ordered list of fallback provider/model strings considered.
    """

    provider_id: Optional[str] = None
    model_id: Optional[str] = None
    is_native_multimodal: bool = False
    selection_reason: Optional[str] = None
    fallback_chain: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "is_native_multimodal": self.is_native_multimodal,
            "selection_reason": self.selection_reason,
            "fallback_chain": list(self.fallback_chain),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChosenModelDecision":
        return cls(
            provider_id=d.get("provider_id"),
            model_id=d.get("model_id"),
            is_native_multimodal=bool(d.get("is_native_multimodal", False)),
            selection_reason=d.get("selection_reason"),
            fallback_chain=list(d.get("fallback_chain") or []),
        )


# ---------------------------------------------------------------------------
# ChosenExecutionDecision
# ---------------------------------------------------------------------------


@dataclass
class ChosenExecutionDecision:
    """Canonical record of the execution path selected by OpenClawd.

    This is a placeholder-enrichable structure recording how execution was
    dispatched.  It complements the existing :class:`~core.schemas.execution_plan.ExecutionPlan`
    by providing a high-level summary that captures the *decision* (not the
    detailed execution steps).

    Attributes
    ----------
    execution_path:
        Resolved execution path string: ``"local"``, ``"cross_device"``,
        ``"hybrid"``, or ``"none"``.
    delegation_point:
        Label of the delegation boundary used (e.g. ``"local"``,
        ``"single_remote"``, ``"multi_device"``).
    remote_execution_mode:
        For remote paths: ``"agent_runtime"`` or ``"command_only"``.
        ``None`` for local paths.
    target_device_ids:
        List of target device IDs for cross-device / hybrid paths.
    orchestration_active:
        ``True`` when multi-device orchestration was invoked.
    """

    execution_path: str = "local"
    delegation_point: Optional[str] = None
    remote_execution_mode: Optional[str] = None
    target_device_ids: List[str] = field(default_factory=list)
    orchestration_active: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_path": self.execution_path,
            "delegation_point": self.delegation_point,
            "remote_execution_mode": self.remote_execution_mode,
            "target_device_ids": list(self.target_device_ids),
            "orchestration_active": self.orchestration_active,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ChosenExecutionDecision":
        return cls(
            execution_path=str(d.get("execution_path") or "local"),
            delegation_point=d.get("delegation_point"),
            remote_execution_mode=d.get("remote_execution_mode"),
            target_device_ids=list(d.get("target_device_ids") or []),
            orchestration_active=bool(d.get("orchestration_active", False)),
        )


# ---------------------------------------------------------------------------
# UnifiedExecutionDecision  (PR-21)
# ---------------------------------------------------------------------------


@dataclass
class UnifiedExecutionDecision:
    """Canonical execution direction record owned by OpenClawd.

    PR-21 — Unified Execution Decision, Remote Mode Policy, and Fallback
    Governance.

    This is the **authoritative** representation of *how* OpenClawd decided to
    execute a request.  It extends :class:`ChosenExecutionDecision` (which is
    preserved for backward compatibility) with explicit rationale and fallback
    intent fields so that downstream consumers and diagnostics tools never need
    to infer the decision from scattered metadata.

    **OpenClawd is the sole producer of this record.**  Execution and substrate
    layers (``CommandRouter``, ``SwarmCoordinator``) consume it; they do not
    produce it.

    Attributes
    ----------
    execution_path:
        Resolved execution branch.  One of the :class:`ExecutionPath` values
        as a string: ``"local"``, ``"cross_device"``, ``"hybrid"``, or
        ``"none"``.
    delegation_point:
        Label of the delegation boundary activated.  Typical values:
        ``"local"``, ``"single_remote"``, ``"multi_device_orchestration"``.
        ``None`` for no-op/advisory paths.
    remote_execution_mode:
        For cross-device and hybrid paths: ``"agent_runtime"`` or
        ``"command_only"``.  ``None`` for local paths.
    target_device_ids:
        Target device identifiers for cross-device / hybrid paths.
    orchestration_active:
        ``True`` when multi-device orchestration (``SwarmCoordinator``) was
        invoked as an upper coordination layer.
    execution_reason:
        Human-readable rationale explaining *why* this execution path was
        selected (e.g. ``"device_id specified → single_remote delegation"``).
    fallback_intent:
        Human-readable description of any downgrade from the preferred path
        (e.g. ``"agent_runtime unavailable → command_only"``).  ``None`` when
        no fallback occurred.
    is_downgrade:
        ``True`` when this execution decision represents a downgrade from a
        richer preferred path.
    preferred_path:
        The execution path that would have been taken without any downgrade.
        ``None`` when no downgrade occurred (``is_downgrade=False``).
    """

    execution_path: str = ExecutionPath.LOCAL.value
    delegation_point: Optional[str] = None
    remote_execution_mode: Optional[str] = None
    target_device_ids: List[str] = field(default_factory=list)
    orchestration_active: bool = False
    execution_reason: Optional[str] = None
    fallback_intent: Optional[str] = None
    is_downgrade: bool = False
    preferred_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "execution_path": self.execution_path,
            "delegation_point": self.delegation_point,
            "remote_execution_mode": self.remote_execution_mode,
            "target_device_ids": list(self.target_device_ids),
            "orchestration_active": self.orchestration_active,
            "execution_reason": self.execution_reason,
            "fallback_intent": self.fallback_intent,
            "is_downgrade": self.is_downgrade,
            "preferred_path": self.preferred_path,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UnifiedExecutionDecision":
        """Reconstruct from a serialised dict; unknown keys degrade gracefully."""
        return cls(
            execution_path=_safe_execution_path(d.get("execution_path")),
            delegation_point=d.get("delegation_point"),
            remote_execution_mode=d.get("remote_execution_mode"),
            target_device_ids=list(d.get("target_device_ids") or []),
            orchestration_active=bool(d.get("orchestration_active", False)),
            execution_reason=d.get("execution_reason"),
            fallback_intent=d.get("fallback_intent"),
            is_downgrade=bool(d.get("is_downgrade", False)),
            preferred_path=d.get("preferred_path"),
        )


# ---------------------------------------------------------------------------
# FallbackDecisionRecord  (PR-21)
# ---------------------------------------------------------------------------


@dataclass
class FallbackDecisionRecord:
    """Canonical fallback / downgrade governance record owned by OpenClawd.

    PR-21 — Unified Execution Decision, Remote Mode Policy, and Fallback
    Governance.

    Captures every downgrade decision that occurred during a single control
    loop iteration.  OpenClawd is the **final policy authority**: it produces
    this record *before* handing off to execution/substrate layers, so that
    downstream consumers always have a single authoritative explanation of
    what was downgraded and why.

    A request with no downgrades produces a record whose ``fallback_kinds``
    list is empty and ``has_fallback`` is ``False``.

    Attributes
    ----------
    has_fallback:
        ``True`` when *any* downgrade occurred for this request.
    fallback_kinds:
        Ordered list of :class:`FallbackKind` values (as strings) representing
        the sequence of downgrade events.  Empty when no fallback occurred.
    model_fallback_reason:
        Human-readable reason for a model/capability fallback, when
        :attr:`FallbackKind.MODEL_CAPABILITY_FALLBACK` is present.
    multimodal_downgrade_reason:
        Human-readable reason for a native-multimodal→text downgrade, when
        :attr:`FallbackKind.NATIVE_MULTIMODAL_TO_TEXT` is present.
    agent_to_command_reason:
        Human-readable reason for an ``agent_runtime``→``command_only``
        downgrade, when :attr:`FallbackKind.AGENT_RUNTIME_TO_COMMAND_ONLY`
        is present.
    remote_to_local_reason:
        Human-readable reason for a remote→local fallback, when
        :attr:`FallbackKind.REMOTE_TO_LOCAL` is present.
    orchestration_downgrade_reason:
        Human-readable reason for an orchestration plan simplification, when
        :attr:`FallbackKind.ORCHESTRATION_DOWNGRADE` is present.
    blocked_reason:
        Human-readable reason why execution was blocked (observe-only /
        no-op), when :attr:`FallbackKind.BLOCKED_NO_OP` is present.
    human_readable_summary:
        Single human-readable sentence summarising all fallbacks in this
        record.  Auto-derived if not supplied explicitly.
    machine_readable_codes:
        Machine-readable list of string codes for programmatic consumption.
        Defaults to the contents of :attr:`fallback_kinds`.
    """

    has_fallback: bool = False
    fallback_kinds: List[str] = field(default_factory=list)

    model_fallback_reason: Optional[str] = None
    multimodal_downgrade_reason: Optional[str] = None
    agent_to_command_reason: Optional[str] = None
    remote_to_local_reason: Optional[str] = None
    orchestration_downgrade_reason: Optional[str] = None
    blocked_reason: Optional[str] = None

    human_readable_summary: Optional[str] = None
    machine_readable_codes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Derive has_fallback from fallback_kinds OR any populated reason field.
        _has_reasons = any([
            self.model_fallback_reason,
            self.multimodal_downgrade_reason,
            self.agent_to_command_reason,
            self.remote_to_local_reason,
            self.orchestration_downgrade_reason,
            self.blocked_reason,
        ])
        if (self.fallback_kinds or _has_reasons) and not self.has_fallback:
            self.has_fallback = True
        # Populate machine_readable_codes from fallback_kinds when absent.
        if not self.machine_readable_codes and self.fallback_kinds:
            self.machine_readable_codes = list(self.fallback_kinds)
        # Auto-derive summary.
        if not self.human_readable_summary and self.fallback_kinds:
            self.human_readable_summary = "Fallback(s): " + ", ".join(self.fallback_kinds)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "has_fallback": self.has_fallback,
            "fallback_kinds": list(self.fallback_kinds),
            "model_fallback_reason": self.model_fallback_reason,
            "multimodal_downgrade_reason": self.multimodal_downgrade_reason,
            "agent_to_command_reason": self.agent_to_command_reason,
            "remote_to_local_reason": self.remote_to_local_reason,
            "orchestration_downgrade_reason": self.orchestration_downgrade_reason,
            "blocked_reason": self.blocked_reason,
            "human_readable_summary": self.human_readable_summary,
            "machine_readable_codes": list(self.machine_readable_codes),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "FallbackDecisionRecord":
        """Reconstruct from a serialised dict; unknown keys degrade gracefully."""
        return cls(
            has_fallback=bool(d.get("has_fallback", False)),
            fallback_kinds=list(d.get("fallback_kinds") or []),
            model_fallback_reason=d.get("model_fallback_reason"),
            multimodal_downgrade_reason=d.get("multimodal_downgrade_reason"),
            agent_to_command_reason=d.get("agent_to_command_reason"),
            remote_to_local_reason=d.get("remote_to_local_reason"),
            orchestration_downgrade_reason=d.get("orchestration_downgrade_reason"),
            blocked_reason=d.get("blocked_reason"),
            human_readable_summary=d.get("human_readable_summary"),
            machine_readable_codes=list(d.get("machine_readable_codes") or []),
        )


# ---------------------------------------------------------------------------
# AuthorityChain
# ---------------------------------------------------------------------------


@dataclass
class AuthorityChain:
    """Explicit record of the authority chain for this control plan.

    Preserves the shell/core/execution boundary in a way that is testable
    and serialisable.  The chain is:

    .. code-block:: text

        runtime_shell (DesktopPresenceRuntime)
            ↓ provides session/perception context
        openclawd_core (OpenClawd) ← DECISION AUTHORITY
            ↓ produces UnifiedControlPlan
        execution_substrate (CommandRouter / SwarmCoordinator)

    Attributes
    ----------
    decision_authority:
        The layer that made the control decision.
        Always :data:`AUTHORITY_ROLE` (``"subject_decision_authority"``).
    shell_role:
        The runtime shell's role designation.
        Always :data:`SHELL_ROLE` (``"runtime_shell_authority"``).
    substrate_role:
        The execution substrate's role designation.
        Always :data:`SUBSTRATE_ROLE` (``"execution_substrate"``).
    orchestration_role:
        The orchestration layer's role designation.
    canonical_module:
        The Python module path of the decision authority.
    canonical_class:
        The class name of the decision authority.
    """

    decision_authority: str = AUTHORITY_ROLE
    shell_role: str = SHELL_ROLE
    substrate_role: str = SUBSTRATE_ROLE
    orchestration_role: str = ORCHESTRATION_ROLE
    canonical_module: str = "core.openclawd"
    canonical_class: str = "OpenClawd"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_authority": self.decision_authority,
            "shell_role": self.shell_role,
            "substrate_role": self.substrate_role,
            "orchestration_role": self.orchestration_role,
            "canonical_module": self.canonical_module,
            "canonical_class": self.canonical_class,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AuthorityChain":
        return cls(
            decision_authority=str(d.get("decision_authority") or AUTHORITY_ROLE),
            shell_role=str(d.get("shell_role") or SHELL_ROLE),
            substrate_role=str(d.get("substrate_role") or SUBSTRATE_ROLE),
            orchestration_role=str(d.get("orchestration_role") or ORCHESTRATION_ROLE),
            canonical_module=str(d.get("canonical_module") or "core.openclawd"),
            canonical_class=str(d.get("canonical_class") or "OpenClawd"),
        )


# ---------------------------------------------------------------------------
# ShellProjectionHints
# ---------------------------------------------------------------------------


@dataclass
class ShellProjectionHints:
    """Shell-facing projection hints for desktop status projection.

    These hints are produced by OpenClawd and consumed by the runtime shell
    (DesktopPresenceRuntime) for desktop status panel display.  They are
    not yet fully wired to the UI — this structure establishes the stable
    contract for future projection.

    Attributes
    ----------
    perception_summary:
        One-line human-readable summary of the perception state.
    model_summary:
        One-line summary of the selected model.
    execution_summary:
        One-line summary of the execution path.
    fallback_note:
        Human-readable note about any fallback that occurred.
    lifecycle_label:
        Current lifecycle state label for display.
    authority_label:
        Label confirming OpenClawd is the decision authority.
    diagnostics_note:
        Any diagnostics note to surface to the operator.
    """

    perception_summary: Optional[str] = None
    model_summary: Optional[str] = None
    execution_summary: Optional[str] = None
    fallback_note: Optional[str] = None
    lifecycle_label: Optional[str] = None
    authority_label: str = "OpenClawd (Unified Control Core)"
    diagnostics_note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "perception_summary": self.perception_summary,
            "model_summary": self.model_summary,
            "execution_summary": self.execution_summary,
            "fallback_note": self.fallback_note,
            "lifecycle_label": self.lifecycle_label,
            "authority_label": self.authority_label,
            "diagnostics_note": self.diagnostics_note,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ShellProjectionHints":
        return cls(
            perception_summary=d.get("perception_summary"),
            model_summary=d.get("model_summary"),
            execution_summary=d.get("execution_summary"),
            fallback_note=d.get("fallback_note"),
            lifecycle_label=d.get("lifecycle_label"),
            authority_label=str(d.get("authority_label") or "OpenClawd (Unified Control Core)"),
            diagnostics_note=d.get("diagnostics_note"),
        )


# ---------------------------------------------------------------------------
# UnifiedControlPlan
# ---------------------------------------------------------------------------


@dataclass
class UnifiedControlPlan:
    """Canonical unified control plan produced by OpenClawd.

    This is the **single canonical control artifact** that captures:

    * the correlation/session identity for this control loop iteration
    * the canonical perception input / perception summary
    * the canonical model supply input / model supply summary
    * the decision posture (autonomous, human-in-loop, advisory, degraded)
    * the chosen model decision
    * the chosen execution decision
    * the fallback level and intent
    * the lifecycle target / lifecycle state progression hints
    * a diagnostics summary
    * the authority chain (explicit, testable)
    * shell-facing projection hints for desktop status projection

    **Authority invariant**: ``authority_chain.decision_authority`` must
    always equal :data:`AUTHORITY_ROLE` (``"subject_decision_authority"``).
    OpenClawd is the only module that produces this plan.

    Attributes
    ----------
    plan_id:
        Unique identifier for this control plan instance.
    runtime_session_id:
        Correlation ID from :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`.
    trace_id:
        Trace ID for the current request (equals ``runtime_session_id`` when
        routed through the runtime shell).
    created_at:
        Unix timestamp when this plan was created.
    schema_version:
        Schema version string for future migration compatibility.
    decision_posture:
        High-level decision posture resolved by OpenClawd.
    canonical_perception_summary:
        Serialisable summary of the canonical perception state (from
        :class:`~core.perception.canonical_perception_state.CanonicalPerceptionState`).
        ``None`` for text-only requests where no perception state was built.
    canonical_model_supply_summary:
        Serialisable summary of the canonical model supply state (from
        :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`).
        ``None`` when model supply was not built for this request.
    chosen_model_decision:
        The canonical model selection decision.
    chosen_execution_decision:
        The canonical execution path decision (backward-compatible record).
    unified_execution_decision:
        PR-21 enriched execution direction record including rationale,
        fallback intent, and downgrade tracking.  ``None`` for text-only
        requests processed without PR-21 integration.
    fallback_level:
        The fallback level applied (``FallbackLevel.NONE`` for primary path).
    fallback_reason:
        Human-readable explanation of why fallback was applied.
    fallback_decision_record:
        PR-21 canonical fallback/downgrade governance record.  Explicit
        record of every downgrade that occurred during this control loop
        iteration.  ``None`` when no fallback decision was produced.
    lifecycle_target:
        The lifecycle state this plan is targeting (e.g. ``"succeeded"``,
        ``"failed"``, ``"degraded"``).
    execution_plan_summary:
        Serialisable summary of the associated :class:`~core.schemas.execution_plan.ExecutionPlan`
        (if one was built by OpenClawd for this request).
    diagnostics_summary:
        Serialisable diagnostics snapshot (may include architecture diagnostic findings).
    authority_chain:
        Explicit authority chain record.
    shell_projection_hints:
        Shell-facing projection hints for desktop status panel.
    """

    plan_id: str = field(default_factory=lambda: f"ucp_{uuid.uuid4().hex[:16]}")
    runtime_session_id: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    schema_version: str = "1.0"

    decision_posture: str = DecisionPosture.UNKNOWN.value

    canonical_perception_summary: Optional[Dict[str, Any]] = None
    canonical_model_supply_summary: Optional[Dict[str, Any]] = None

    chosen_model_decision: ChosenModelDecision = field(default_factory=ChosenModelDecision)
    chosen_execution_decision: ChosenExecutionDecision = field(default_factory=ChosenExecutionDecision)
    unified_execution_decision: Optional[UnifiedExecutionDecision] = None

    fallback_level: str = FallbackLevel.NONE.value
    fallback_reason: Optional[str] = None
    fallback_decision_record: Optional[FallbackDecisionRecord] = None

    lifecycle_target: Optional[str] = None
    execution_plan_summary: Optional[Dict[str, Any]] = None
    diagnostics_summary: Optional[Dict[str, Any]] = None

    authority_chain: AuthorityChain = field(default_factory=AuthorityChain)
    shell_projection_hints: ShellProjectionHints = field(default_factory=ShellProjectionHints)

    def to_dict(self) -> Dict[str, Any]:
        """Return a fully serialisable dict representation of this plan.

        The returned dict is safe for JSON serialisation, logging,
        diagnostics, and desktop status projection.
        """
        return {
            "plan_id": self.plan_id,
            "runtime_session_id": self.runtime_session_id,
            "trace_id": self.trace_id,
            "created_at": self.created_at,
            "schema_version": self.schema_version,
            "decision_posture": self.decision_posture,
            "canonical_perception_summary": self.canonical_perception_summary,
            "canonical_model_supply_summary": self.canonical_model_supply_summary,
            "chosen_model_decision": self.chosen_model_decision.to_dict(),
            "chosen_execution_decision": self.chosen_execution_decision.to_dict(),
            "unified_execution_decision": (
                self.unified_execution_decision.to_dict()
                if self.unified_execution_decision is not None
                else None
            ),
            "fallback_level": self.fallback_level,
            "fallback_reason": self.fallback_reason,
            "fallback_decision_record": (
                self.fallback_decision_record.to_dict()
                if self.fallback_decision_record is not None
                else None
            ),
            "lifecycle_target": self.lifecycle_target,
            "execution_plan_summary": self.execution_plan_summary,
            "diagnostics_summary": self.diagnostics_summary,
            "authority_chain": self.authority_chain.to_dict(),
            "shell_projection_hints": self.shell_projection_hints.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "UnifiedControlPlan":
        """Reconstruct a :class:`UnifiedControlPlan` from a serialised dict.

        Unknown or missing keys degrade gracefully to defaults.
        """
        cmd_raw = d.get("chosen_model_decision")
        ced_raw = d.get("chosen_execution_decision")
        ued_raw = d.get("unified_execution_decision")
        fdr_raw = d.get("fallback_decision_record")
        ac_raw = d.get("authority_chain")
        sp_raw = d.get("shell_projection_hints")

        return cls(
            plan_id=str(d.get("plan_id") or f"ucp_{uuid.uuid4().hex[:16]}"),
            runtime_session_id=d.get("runtime_session_id"),
            trace_id=d.get("trace_id"),
            created_at=float(d.get("created_at") or time.time()),
            schema_version=str(d.get("schema_version") or "1.0"),
            decision_posture=_safe_posture(d.get("decision_posture")),
            canonical_perception_summary=d.get("canonical_perception_summary"),
            canonical_model_supply_summary=d.get("canonical_model_supply_summary"),
            chosen_model_decision=(
                ChosenModelDecision.from_dict(cmd_raw) if isinstance(cmd_raw, dict) else ChosenModelDecision()
            ),
            chosen_execution_decision=(
                ChosenExecutionDecision.from_dict(ced_raw) if isinstance(ced_raw, dict) else ChosenExecutionDecision()
            ),
            unified_execution_decision=(
                UnifiedExecutionDecision.from_dict(ued_raw) if isinstance(ued_raw, dict) else None
            ),
            fallback_level=_safe_fallback(d.get("fallback_level")),
            fallback_reason=d.get("fallback_reason"),
            fallback_decision_record=(
                FallbackDecisionRecord.from_dict(fdr_raw) if isinstance(fdr_raw, dict) else None
            ),
            lifecycle_target=d.get("lifecycle_target"),
            execution_plan_summary=d.get("execution_plan_summary"),
            diagnostics_summary=d.get("diagnostics_summary"),
            authority_chain=(
                AuthorityChain.from_dict(ac_raw) if isinstance(ac_raw, dict) else AuthorityChain()
            ),
            shell_projection_hints=(
                ShellProjectionHints.from_dict(sp_raw) if isinstance(sp_raw, dict) else ShellProjectionHints()
            ),
        )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _safe_posture(value: Any) -> str:
    """Return a valid :class:`DecisionPosture` value, degrading to UNKNOWN."""
    try:
        return DecisionPosture(value).value
    except (ValueError, TypeError):
        return DecisionPosture.UNKNOWN.value


def _safe_fallback(value: Any) -> str:
    """Return a valid :class:`FallbackLevel` value, degrading to UNKNOWN."""
    try:
        return FallbackLevel(value).value
    except (ValueError, TypeError):
        return FallbackLevel.UNKNOWN.value


def _safe_execution_path(value: Any) -> str:
    """Return a valid :class:`ExecutionPath` value, degrading to LOCAL."""
    try:
        return ExecutionPath(value).value
    except (ValueError, TypeError):
        return ExecutionPath.LOCAL.value


def _derive_posture(continuum_state: Optional[Dict[str, Any]]) -> str:
    """Derive :class:`DecisionPosture` from an existing continuum state dict."""
    if not continuum_state:
        return DecisionPosture.UNKNOWN.value
    tri_state = continuum_state.get("tri_state_phase", "")
    if tri_state == "liminal":
        return DecisionPosture.HUMAN_IN_LOOP.value
    if tri_state == "observer":
        return DecisionPosture.ADVISORY.value
    return DecisionPosture.AUTONOMOUS.value


def _perception_summary(canonical_perception: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract a compact perception summary safe for embedding in the plan."""
    if not canonical_perception:
        return None
    return {
        "has_continuous_perception": canonical_perception.get("has_continuous_perception", False),
        "has_request_multimodal": canonical_perception.get("has_request_multimodal", False),
        "active_modalities": canonical_perception.get("active_modalities") or [],
        "source_summary": canonical_perception.get("source_summary"),
        "fusion_summary": canonical_perception.get("fusion_summary"),
    }


def _model_supply_summary(canonical_model_supply: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Extract a compact model supply summary safe for embedding in the plan."""
    if not canonical_model_supply:
        return None
    return {
        "available_provider_count": canonical_model_supply.get("available_provider_count", 0),
        "native_multimodal_count": canonical_model_supply.get("native_multimodal_count", 0),
        "preferred_multimodal_provider_id": canonical_model_supply.get("preferred_multimodal_provider_id"),
        "supply_summary": canonical_model_supply.get("supply_summary"),
    }


def _build_shell_projection(
    perception_summary: Optional[Dict[str, Any]],
    model_decision: ChosenModelDecision,
    execution_decision: ChosenExecutionDecision,
    fallback_level: str,
    fallback_reason: Optional[str],
    lifecycle_target: Optional[str],
    diagnostics_summary: Optional[Dict[str, Any]],
) -> ShellProjectionHints:
    """Build shell-facing projection hints from control plan components."""
    modalities = (perception_summary or {}).get("active_modalities") or []
    has_multimodal = bool(modalities)
    perc_label = f"modalities={modalities}" if has_multimodal else "text-only"

    model_label = None
    if model_decision.provider_id or model_decision.model_id:
        nm_flag = " [native-multimodal]" if model_decision.is_native_multimodal else ""
        model_label = f"{model_decision.provider_id}/{model_decision.model_id}{nm_flag}"

    exec_label = execution_decision.execution_path
    if execution_decision.remote_execution_mode:
        exec_label = f"{exec_label}:{execution_decision.remote_execution_mode}"

    fallback_note = None
    if fallback_level not in (FallbackLevel.NONE.value, FallbackLevel.UNKNOWN.value):
        fallback_note = f"{fallback_level}"
        if fallback_reason:
            fallback_note = f"{fallback_note}: {fallback_reason}"

    diag_note = None
    if diagnostics_summary:
        error_count = diagnostics_summary.get("error_count", 0)
        warning_count = diagnostics_summary.get("warning_count", 0)
        if error_count:
            diag_note = f"errors={error_count} warnings={warning_count}"
        elif warning_count:
            diag_note = f"warnings={warning_count}"

    return ShellProjectionHints(
        perception_summary=perc_label,
        model_summary=model_label,
        execution_summary=exec_label,
        fallback_note=fallback_note,
        lifecycle_label=lifecycle_target,
        authority_label="OpenClawd (Unified Control Core)",
        diagnostics_note=diag_note,
    )


# ---------------------------------------------------------------------------
# Primary builder
# ---------------------------------------------------------------------------


def build_unified_control_plan(
    *,
    runtime_session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    canonical_perception: Optional[Dict[str, Any]] = None,
    canonical_model_supply: Optional[Dict[str, Any]] = None,
    continuum_state: Optional[Dict[str, Any]] = None,
    chosen_model: Optional[str] = None,
    chosen_provider: Optional[str] = None,
    is_native_multimodal: bool = False,
    model_selection_reason: Optional[str] = None,
    fallback_chain: Optional[List[str]] = None,
    execution_path: str = "local",
    delegation_point: Optional[str] = None,
    remote_execution_mode: Optional[str] = None,
    target_device_ids: Optional[List[str]] = None,
    orchestration_active: bool = False,
    fallback_level: str = FallbackLevel.NONE.value,
    fallback_reason: Optional[str] = None,
    lifecycle_target: Optional[str] = None,
    execution_plan_summary: Optional[Dict[str, Any]] = None,
    diagnostics_summary: Optional[Dict[str, Any]] = None,
    # PR-21 — enriched execution decision parameters
    execution_reason: Optional[str] = None,
    fallback_intent: Optional[str] = None,
    is_execution_downgrade: bool = False,
    preferred_execution_path: Optional[str] = None,
    # PR-21 — fallback governance record parameters
    fallback_kinds: Optional[List[str]] = None,
    model_fallback_reason: Optional[str] = None,
    multimodal_downgrade_reason: Optional[str] = None,
    agent_to_command_reason: Optional[str] = None,
    remote_to_local_reason: Optional[str] = None,
    orchestration_downgrade_reason: Optional[str] = None,
    blocked_reason: Optional[str] = None,
) -> UnifiedControlPlan:
    """Build a :class:`UnifiedControlPlan` from the inputs available to OpenClawd.

    This is the **primary builder**.  All parameters are keyword-only and
    optional so that the function degrades gracefully in partial-state
    scenarios (text-only requests, missing model supply, etc.).

    Parameters
    ----------
    runtime_session_id:
        Correlation ID from the runtime shell.
    trace_id:
        Trace ID for the current request.
    canonical_perception:
        Serialised :class:`~core.perception.canonical_perception_state.CanonicalPerceptionState`
        dict, as returned by ``OpenClawd._build_canonical_perception_state()``.
    canonical_model_supply:
        Serialised :class:`~core.model_topology.canonical_model_supply_state.CanonicalModelSupplyState`
        dict, or a compact supply summary dict.
    continuum_state:
        The ``state_continuum`` dict produced by ContinuumOrchestrator, used to
        derive the :class:`DecisionPosture`.
    chosen_model:
        The model ID selected by OpenClawd for this request.
    chosen_provider:
        The provider ID for the selected model.
    is_native_multimodal:
        Whether the selected model supports native multimodal API calls.
    model_selection_reason:
        Human-readable explanation of the model selection.
    fallback_chain:
        Ordered list of fallback provider/model strings considered.
    execution_path:
        Resolved execution path: ``"local"``, ``"cross_device"``, ``"hybrid"``,
        or ``"none"``.
    delegation_point:
        Delegation boundary label used for execution.
    remote_execution_mode:
        For remote paths: ``"agent_runtime"`` or ``"command_only"``.
    target_device_ids:
        Target device IDs for cross-device paths.
    orchestration_active:
        Whether multi-device orchestration was invoked.
    fallback_level:
        The fallback level applied (default: ``FallbackLevel.NONE``).
    fallback_reason:
        Human-readable explanation of the fallback.
    lifecycle_target:
        The lifecycle state this plan targets.
    execution_plan_summary:
        Compact summary of the associated ExecutionPlan.
    diagnostics_summary:
        Architecture diagnostics snapshot dict.
    execution_reason:
        PR-21: Human-readable rationale for the chosen execution path.
    fallback_intent:
        PR-21: Description of execution downgrade from preferred path.
    is_execution_downgrade:
        PR-21: ``True`` when this execution is a downgrade from a richer path.
    preferred_execution_path:
        PR-21: The path that would have been taken without the downgrade.
    fallback_kinds:
        PR-21: Ordered list of :class:`FallbackKind` values for the governance
        record.
    model_fallback_reason:
        PR-21: Reason for a model/capability fallback.
    multimodal_downgrade_reason:
        PR-21: Reason for a native-multimodal→text downgrade.
    agent_to_command_reason:
        PR-21: Reason for an ``agent_runtime``→``command_only`` downgrade.
    remote_to_local_reason:
        PR-21: Reason for a remote→local fallback.
    orchestration_downgrade_reason:
        PR-21: Reason for an orchestration plan simplification.
    blocked_reason:
        PR-21: Reason why execution was blocked (observe-only / no-op).

    Returns
    -------
    UnifiedControlPlan
        A fully populated canonical control plan.  Never raises.
    """
    posture = _derive_posture(continuum_state)

    perc_summary = _perception_summary(canonical_perception)
    supply_summary = _model_supply_summary(canonical_model_supply)

    model_decision = ChosenModelDecision(
        provider_id=chosen_provider,
        model_id=chosen_model,
        is_native_multimodal=is_native_multimodal,
        selection_reason=model_selection_reason,
        fallback_chain=list(fallback_chain or []),
    )

    safe_path = execution_path or "local"
    exec_decision = ChosenExecutionDecision(
        execution_path=safe_path,
        delegation_point=delegation_point,
        remote_execution_mode=remote_execution_mode,
        target_device_ids=list(target_device_ids or []),
        orchestration_active=orchestration_active,
    )

    # PR-21 — build UnifiedExecutionDecision (enriched, authoritative record)
    unified_exec_decision = UnifiedExecutionDecision(
        execution_path=_safe_execution_path(safe_path),
        delegation_point=delegation_point,
        remote_execution_mode=remote_execution_mode,
        target_device_ids=list(target_device_ids or []),
        orchestration_active=orchestration_active,
        execution_reason=execution_reason,
        fallback_intent=fallback_intent,
        is_downgrade=is_execution_downgrade,
        preferred_path=preferred_execution_path,
    )

    # PR-21 — build FallbackDecisionRecord (governance record)
    _fk = list(fallback_kinds or [])
    if _fk or any([
        model_fallback_reason,
        multimodal_downgrade_reason,
        agent_to_command_reason,
        remote_to_local_reason,
        orchestration_downgrade_reason,
        blocked_reason,
    ]):
        fdr = FallbackDecisionRecord(
            fallback_kinds=_fk,
            model_fallback_reason=model_fallback_reason,
            multimodal_downgrade_reason=multimodal_downgrade_reason,
            agent_to_command_reason=agent_to_command_reason,
            remote_to_local_reason=remote_to_local_reason,
            orchestration_downgrade_reason=orchestration_downgrade_reason,
            blocked_reason=blocked_reason,
        )
    else:
        fdr = None

    safe_fallback = _safe_fallback(fallback_level)

    projection = _build_shell_projection(
        perception_summary=perc_summary,
        model_decision=model_decision,
        execution_decision=exec_decision,
        fallback_level=safe_fallback,
        fallback_reason=fallback_reason,
        lifecycle_target=lifecycle_target,
        diagnostics_summary=diagnostics_summary,
    )

    return UnifiedControlPlan(
        runtime_session_id=runtime_session_id,
        trace_id=trace_id,
        decision_posture=posture,
        canonical_perception_summary=perc_summary,
        canonical_model_supply_summary=supply_summary,
        chosen_model_decision=model_decision,
        chosen_execution_decision=exec_decision,
        unified_execution_decision=unified_exec_decision,
        fallback_level=safe_fallback,
        fallback_reason=fallback_reason,
        fallback_decision_record=fdr,
        lifecycle_target=lifecycle_target,
        execution_plan_summary=execution_plan_summary,
        diagnostics_summary=diagnostics_summary,
        authority_chain=AuthorityChain(),
        shell_projection_hints=projection,
    )


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------


def unified_control_plan_summary(plan: Optional["UnifiedControlPlan"]) -> Optional[Dict[str, Any]]:
    """Return a compact, JSON-safe summary of a :class:`UnifiedControlPlan`.

    Returns ``None`` if ``plan`` is ``None``.  The summary is suitable for
    embedding in response ``metadata`` dicts without carrying the full plan.

    Fields in the summary:

    * ``plan_id`` — plan identifier
    * ``decision_posture`` — resolved posture
    * ``chosen_model`` — selected model ID
    * ``chosen_provider`` — selected provider ID
    * ``is_native_multimodal`` — native multimodal flag
    * ``execution_path`` — execution path
    * ``remote_execution_mode`` — remote execution mode (PR-21)
    * ``execution_reason`` — rationale for the chosen execution path (PR-21)
    * ``is_execution_downgrade`` — whether execution is a downgrade (PR-21)
    * ``fallback_level`` — fallback level
    * ``has_fallback`` — whether any fallback/downgrade occurred (PR-21)
    * ``fallback_kinds`` — ordered list of fallback kind codes (PR-21)
    * ``lifecycle_target`` — lifecycle target
    * ``authority_role`` — always ``"subject_decision_authority"``
    * ``has_perception`` — whether perception state was present
    * ``has_model_supply`` — whether model supply state was present
    """
    if plan is None:
        return None
    ued = plan.unified_execution_decision
    fdr = plan.fallback_decision_record
    return {
        "plan_id": plan.plan_id,
        "decision_posture": plan.decision_posture,
        "chosen_model": plan.chosen_model_decision.model_id,
        "chosen_provider": plan.chosen_model_decision.provider_id,
        "is_native_multimodal": plan.chosen_model_decision.is_native_multimodal,
        "execution_path": plan.chosen_execution_decision.execution_path,
        "remote_execution_mode": ued.remote_execution_mode if ued is not None else None,
        "execution_reason": ued.execution_reason if ued is not None else None,
        "is_execution_downgrade": ued.is_downgrade if ued is not None else False,
        "fallback_level": plan.fallback_level,
        "has_fallback": fdr.has_fallback if fdr is not None else False,
        "fallback_kinds": fdr.fallback_kinds if fdr is not None else [],
        "lifecycle_target": plan.lifecycle_target,
        "authority_role": plan.authority_chain.decision_authority,
        "has_perception": plan.canonical_perception_summary is not None,
        "has_model_supply": plan.canonical_model_supply_summary is not None,
    }
