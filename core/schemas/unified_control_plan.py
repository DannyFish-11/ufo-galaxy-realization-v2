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
        The canonical execution path decision.
    fallback_level:
        The fallback level applied (``FallbackLevel.NONE`` for primary path).
    fallback_reason:
        Human-readable explanation of why fallback was applied.
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

    fallback_level: str = FallbackLevel.NONE.value
    fallback_reason: Optional[str] = None

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
            "fallback_level": self.fallback_level,
            "fallback_reason": self.fallback_reason,
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
            fallback_level=_safe_fallback(d.get("fallback_level")),
            fallback_reason=d.get("fallback_reason"),
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

    exec_decision = ChosenExecutionDecision(
        execution_path=execution_path or "local",
        delegation_point=delegation_point,
        remote_execution_mode=remote_execution_mode,
        target_device_ids=list(target_device_ids or []),
        orchestration_active=orchestration_active,
    )

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
        fallback_level=safe_fallback,
        fallback_reason=fallback_reason,
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
    * ``fallback_level`` — fallback level
    * ``lifecycle_target`` — lifecycle target
    * ``authority_role`` — always ``"subject_decision_authority"``
    * ``has_perception`` — whether perception state was present
    * ``has_model_supply`` — whether model supply state was present
    """
    if plan is None:
        return None
    return {
        "plan_id": plan.plan_id,
        "decision_posture": plan.decision_posture,
        "chosen_model": plan.chosen_model_decision.model_id,
        "chosen_provider": plan.chosen_model_decision.provider_id,
        "is_native_multimodal": plan.chosen_model_decision.is_native_multimodal,
        "execution_path": plan.chosen_execution_decision.execution_path,
        "fallback_level": plan.fallback_level,
        "lifecycle_target": plan.lifecycle_target,
        "authority_role": plan.authority_chain.decision_authority,
        "has_perception": plan.canonical_perception_summary is not None,
        "has_model_supply": plan.canonical_model_supply_summary is not None,
    }
