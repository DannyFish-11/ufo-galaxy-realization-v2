#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/canonical_layer_model.py
==============================
PR-9: Canonical Runtime Layer Model — normalized architecture contract.

Purpose
-------
This module is the **single authoritative declaration** of the Galaxy system's
canonical runtime layer model.  It resolves split-brain architecture
declarations by clearly naming each layer, its scope, the modules that
implement it, and the boundaries it must NOT cross.

This module does NOT invent a new architecture — it normalizes the declarations
that already exist across ``core/unified_orchestration_spine.py``,
``core/release_blocking_gate.py``, ``core/llm/``, ``core/canonical_completion_ingress.py``,
and ``core/openclawd.py`` into one coherent contract surface.

The Five Canonical Runtime Layers
----------------------------------

.. code-block:: text

    ┌──────────────────────────────────────────────────────────────────┐
    │  Layer 5 — Startup / Readiness / Health / Release Integrity      │
    │  (V6 structural boundary; non-hot-path)                          │
    │  core.release_blocking_gate.ReleaseBlockingGate                  │
    └───────────────────┬──────────────────────────────────────────────┘
                        │ initialisation only; not on per-request path
    ┌───────────────────▼──────────────────────────────────────────────┐
    │  Layer 4 — Multi-Step Orchestration Spine                        │
    │  (V4; orchestration sessions only; not per-request gate)         │
    │  core.unified_orchestration_spine.evaluate_orchestration_request │
    └───────────────────┬──────────────────────────────────────────────┘
                        │ called for complex multi-step sessions only
    ┌───────────────────▼──────────────────────────────────────────────┐
    │  Layer 3 — Per-Request Hot Path                                  │
    │  (cognitive / routing / dispatch; every synchronous request)     │
    │  OpenClawd.process() → _determine_execution_path()               │
    │                       → CommandRouter.route_envelope()           │
    └───────────────────┬──────────────────────────────────────────────┘
                        │ LLM calls routed through L1/L2/L3
    ┌───────────────────▼──────────────────────────────────────────────┐
    │  Layer 2 — Router-Level Cognitive Authority (L1/L2/L3)           │
    │  (fused into UnifiedLLMRouter)                                   │
    │  L1: core.llm.route_authority.LLMRouteAuthority                  │
    │  L2: core.llm.supply_authority.LLMSupplyAuthority                │
    │  L3: core.llm.context_authority.CognitiveContextAuthority        │
    │  Facade: core.unified.llm_router.UnifiedLLMRouter                │
    └───────────────────┬──────────────────────────────────────────────┘
                        │ completion truth enforced via canonical chain
    ┌───────────────────▼──────────────────────────────────────────────┐
    │  Layer 1 — Completion Truth Backbone (V2/V5)                     │
    │  (enforced via canonical chain; never optional soft signaling)   │
    │  core.canonical_completion_ingress.CanonicalCompletionIngress    │
    │  core.canonical_group_completion_closure (V5)                    │
    │  core.durable_truth_authority_chain                              │
    └──────────────────────────────────────────────────────────────────┘

Layer Boundary Invariants
--------------------------
The following "NOT" invariants are machine-checkable sentinels.  Each one
resolves a historically observed split-brain declaration:

* V4 ``unified_orchestration_spine`` is **NOT** the universal synchronous
  per-request gate.  Simple requests remain on the per-request hot path
  (OpenClawd → CommandRouter).

* V6 ``release_blocking_gate`` is **NOT** a per-request runtime gate.
  It is evaluated at release/CI time and at system startup; it is never
  inserted into the synchronous request processing path.

* L1/L2/L3 cognitive authority **belongs to the router-level layer** (fused
  into ``UnifiedLLMRouter``).  It is **NOT** a detached shadow stack that
  runs independently alongside the per-request hot path.

* Completion truth is **enforced via the canonical truth chain/backbone**
  (``CanonicalCompletionIngress`` + V5 closure).  It is **NOT** optional
  soft signaling that callers may skip.

Public API
----------
Layer key constants::

    LAYER_COMPLETION_TRUTH_BACKBONE
    LAYER_ROUTER_COGNITIVE_AUTHORITY
    LAYER_PER_REQUEST_HOT_PATH
    LAYER_MULTI_STEP_ORCHESTRATION_SPINE
    LAYER_STARTUP_RELEASE_INTEGRITY

Layer boundary sentinels (NOT-policies)::

    V4_IS_NOT_PER_REQUEST_GATE
    V6_IS_NOT_PER_REQUEST_GATE
    L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK
    COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL

Enumeration::

    CanonicalLayer

Data class::

    LayerDeclaration

Registry::

    CANONICAL_LAYER_REGISTRY   : Dict[CanonicalLayer, LayerDeclaration]
    CANONICAL_LAYER_KEYS       : FrozenSet[str]

Functions::

    get_layer_declaration(layer) -> LayerDeclaration
    check_layer_model_consistent(layer_snapshot) -> List[LayerFinding]
    run_layer_model_invariants(layer_snapshots) -> LayerModelReport
"""

from __future__ import annotations

import dataclasses
import logging
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger("Galaxy.CanonicalLayerModel")

__all__ = [
    # Layer key constants
    "LAYER_COMPLETION_TRUTH_BACKBONE",
    "LAYER_ROUTER_COGNITIVE_AUTHORITY",
    "LAYER_PER_REQUEST_HOT_PATH",
    "LAYER_MULTI_STEP_ORCHESTRATION_SPINE",
    "LAYER_STARTUP_RELEASE_INTEGRITY",
    # NOT-policy sentinels
    "V4_IS_NOT_PER_REQUEST_GATE",
    "V6_IS_NOT_PER_REQUEST_GATE",
    "L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK",
    "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL",
    # Enumeration
    "CanonicalLayer",
    # Data types
    "LayerDeclaration",
    "LayerFinding",
    "LayerModelReport",
    # Registry
    "CANONICAL_LAYER_REGISTRY",
    "CANONICAL_LAYER_KEYS",
    # Functions
    "get_layer_declaration",
    "check_layer_model_consistent",
    "run_layer_model_invariants",
]

# ---------------------------------------------------------------------------
# Module authority sentinel
# ---------------------------------------------------------------------------

CANONICAL_LAYER_MODEL_AUTHORITY: str = (
    "CANONICAL_LAYER_MODEL_AUTHORITY::PR9: "
    "core.canonical_layer_model is the single authoritative declaration of "
    "the Galaxy system's five canonical runtime layers.  It normalizes the "
    "architecture declarations already present across "
    "core.unified_orchestration_spine (V4), core.release_blocking_gate (V6), "
    "core.llm.route_authority/supply_authority/context_authority (L1/L2/L3), "
    "core.unified.llm_router.UnifiedLLMRouter, "
    "core.canonical_completion_ingress (completion truth backbone), and "
    "core.openclawd (per-request hot path).  "
    "This module does NOT introduce new runtime logic; it consolidates existing "
    "declarations into one coherent, machine-checkable contract surface."
)

CANONICAL_LAYER_MODEL_PR9_SENTINEL: str = (
    "PR::CANONICAL_LAYER_MODEL_PR9: "
    "Introduced by PR-9 (Normalize canonical runtime architecture declarations "
    "across layers).  Removing or contradicting this module re-opens the "
    "split-brain architecture declarations that PR-9 resolved."
)

# ---------------------------------------------------------------------------
# Layer key constants (stable string identifiers)
# ---------------------------------------------------------------------------

LAYER_COMPLETION_TRUTH_BACKBONE: str = "completion_truth_backbone"
LAYER_ROUTER_COGNITIVE_AUTHORITY: str = "router_cognitive_authority"
LAYER_PER_REQUEST_HOT_PATH: str = "per_request_hot_path"
LAYER_MULTI_STEP_ORCHESTRATION_SPINE: str = "multi_step_orchestration_spine"
LAYER_STARTUP_RELEASE_INTEGRITY: str = "startup_release_integrity"

# ---------------------------------------------------------------------------
# NOT-policy sentinels — machine-checkable boundary invariants
# ---------------------------------------------------------------------------

V4_IS_NOT_PER_REQUEST_GATE: str = (
    "LAYER_BOUNDARY::V4_IS_NOT_PER_REQUEST_GATE: "
    "core.unified_orchestration_spine (V4) is the multi-step orchestration "
    "spine for complex execution sessions (parallel fan-out, delegated runtime, "
    "wake-routed, handoff/takeover, cross-device, hybrid).  "
    "V4 is NOT the universal synchronous per-request gate.  "
    "Simple per-request execution (LOCAL, SINGLE_DEVICE_REMOTE) continues on "
    "the per-request hot path: OpenClawd.process() → _determine_execution_path() "
    "→ CommandRouter.route_envelope().  "
    "Inserting V4 as a mandatory synchronous gate on every request would "
    "mis-layer the architecture, add unnecessary latency, and produce a false "
    "system model where all execution is described as going through V4."
)

V6_IS_NOT_PER_REQUEST_GATE: str = (
    "LAYER_BOUNDARY::V6_IS_NOT_PER_REQUEST_GATE: "
    "core.release_blocking_gate (V6) is the startup / readiness / health / "
    "release integrity boundary layer.  It is evaluated at CI time, at system "
    "startup, and as a pre-release blocking gate.  "
    "V6 is NOT a per-request runtime gate.  "
    "Inserting V6 into the synchronous request processing path would introduce "
    "structural latency, mis-layer the release-posture contract with the "
    "per-request cognitive path, and produce a false model where release "
    "integrity is re-evaluated on every request."
)

L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK: str = (
    "LAYER_BOUNDARY::L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK: "
    "L1 (core.llm.route_authority.LLMRouteAuthority), "
    "L2 (core.llm.supply_authority.LLMSupplyAuthority), and "
    "L3 (core.llm.context_authority.CognitiveContextAuthority) are the "
    "router-level cognitive authority sub-layers, fused into "
    "core.unified.llm_router.UnifiedLLMRouter.  "
    "L1/L2/L3 belongs to the router cognitive authority layer.  "
    "L1/L2/L3 is NOT a detached shadow stack that runs independently alongside "
    "the per-request hot path.  All LLM routing decisions must flow through "
    "UnifiedLLMRouter (which integrates L1/L2/L3) before reaching provider "
    "supply and execution.  Direct calls that bypass UnifiedLLMRouter and reach "
    "the provider supply layer (MultiLLMRouter) directly from OpenClawd or "
    "other callers are a policy violation."
)

COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL: str = (
    "LAYER_BOUNDARY::COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL: "
    "The completion truth backbone (core.canonical_completion_ingress, "
    "core.canonical_group_completion_closure V5, core.durable_truth_authority_chain) "
    "enforces completion semantics via the canonical truth chain.  "
    "Completion truth is NOT optional soft signaling.  "
    "Callers MUST NOT treat a delegated ACK as delegated terminal completion, "
    "treat a subtask success as group completion, or emit a terminal state "
    "outside the canonical closure.  Bypassing the completion truth backbone "
    "breaks the V2 × Android session continuity and creates incomplete or "
    "inconsistent task lifecycle records."
)

# ---------------------------------------------------------------------------
# CanonicalLayer enumeration
# ---------------------------------------------------------------------------


class CanonicalLayer(str, Enum):
    """The five canonical runtime layers of the Galaxy system.

    Ordered from infrastructure/backbone (lowest, layer 1) to structural
    boundary (highest, layer 5).
    """

    COMPLETION_TRUTH_BACKBONE = LAYER_COMPLETION_TRUTH_BACKBONE
    ROUTER_COGNITIVE_AUTHORITY = LAYER_ROUTER_COGNITIVE_AUTHORITY
    PER_REQUEST_HOT_PATH = LAYER_PER_REQUEST_HOT_PATH
    MULTI_STEP_ORCHESTRATION_SPINE = LAYER_MULTI_STEP_ORCHESTRATION_SPINE
    STARTUP_RELEASE_INTEGRITY = LAYER_STARTUP_RELEASE_INTEGRITY


# ---------------------------------------------------------------------------
# LayerDeclaration data class
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class LayerDeclaration:
    """Declaration of a single canonical runtime layer.

    Attributes
    ----------
    layer:
        The :class:`CanonicalLayer` this declaration describes.
    label:
        Human-readable name for the layer.
    version_tag:
        The version identifier associated with this layer in the codebase
        (e.g. ``"V4"``, ``"V6"``, ``"L1/L2/L3"``).
    scope:
        One-line description of the layer's responsibility scope.
    canonical_modules:
        Tuple of canonical module paths that implement this layer.
    not_policies:
        Tuple of NOT-policy sentinel strings that define the boundary
        invariants this layer must not violate.
    is_hot_path:
        True when this layer is exercised on every synchronous request.
    is_startup_only:
        True when this layer is exercised only at startup / CI / release time,
        never on per-request path.
    """

    layer: CanonicalLayer
    label: str
    version_tag: str
    scope: str
    canonical_modules: Tuple[str, ...]
    not_policies: Tuple[str, ...]
    is_hot_path: bool = False
    is_startup_only: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer.value,
            "label": self.label,
            "version_tag": self.version_tag,
            "scope": self.scope,
            "canonical_modules": list(self.canonical_modules),
            "not_policies": list(self.not_policies),
            "is_hot_path": self.is_hot_path,
            "is_startup_only": self.is_startup_only,
        }


# ---------------------------------------------------------------------------
# Canonical layer registry
# ---------------------------------------------------------------------------

CANONICAL_LAYER_REGISTRY: Dict[CanonicalLayer, LayerDeclaration] = {
    CanonicalLayer.COMPLETION_TRUTH_BACKBONE: LayerDeclaration(
        layer=CanonicalLayer.COMPLETION_TRUTH_BACKBONE,
        label="Completion Truth Backbone",
        version_tag="V2/V5",
        scope=(
            "Canonical task and session completion truth: ties Android handoff "
            "responses to asyncio.Future objects, enforces group completion "
            "closure, and writes completion to durable session truth."
        ),
        canonical_modules=(
            "core.canonical_completion_ingress",
            "core.canonical_group_completion_closure",
            "core.durable_truth_authority_chain",
        ),
        not_policies=(
            COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL,
        ),
        is_hot_path=False,
        is_startup_only=False,
    ),

    CanonicalLayer.ROUTER_COGNITIVE_AUTHORITY: LayerDeclaration(
        layer=CanonicalLayer.ROUTER_COGNITIVE_AUTHORITY,
        label="Router-Level Cognitive Authority (L1/L2/L3)",
        version_tag="L1/L2/L3",
        scope=(
            "LLM routing, model supply, and cognitive context assembly.  "
            "L1=route selection, L2=supply/availability legality, "
            "L3=context enrichment/governance.  Fused into UnifiedLLMRouter."
        ),
        canonical_modules=(
            "core.llm.route_authority",
            "core.llm.supply_authority",
            "core.llm.context_authority",
            "core.unified.llm_router",
        ),
        not_policies=(
            L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK,
        ),
        is_hot_path=True,
        is_startup_only=False,
    ),

    CanonicalLayer.PER_REQUEST_HOT_PATH: LayerDeclaration(
        layer=CanonicalLayer.PER_REQUEST_HOT_PATH,
        label="Per-Request Hot Path",
        version_tag="core",
        scope=(
            "Actual runnable cognitive / routing / dispatch / local execution "
            "path exercised on every synchronous request.  "
            "OpenClawd.process() → _determine_execution_path() → "
            "CommandRouter.route_envelope()."
        ),
        canonical_modules=(
            "core.openclawd",
            "core.command_router",
            "core.agent.kernel",
        ),
        not_policies=(),
        is_hot_path=True,
        is_startup_only=False,
    ),

    CanonicalLayer.MULTI_STEP_ORCHESTRATION_SPINE: LayerDeclaration(
        layer=CanonicalLayer.MULTI_STEP_ORCHESTRATION_SPINE,
        label="Multi-Step Orchestration Spine",
        version_tag="V4",
        scope=(
            "Session authority for multi-step and multi-device execution "
            "sessions: parallel fan-out, delegated runtime, wake-routed, "
            "handoff/takeover, cross-device, and hybrid.  "
            "NOT the universal synchronous per-request gate."
        ),
        canonical_modules=(
            "core.unified_orchestration_spine",
        ),
        not_policies=(
            V4_IS_NOT_PER_REQUEST_GATE,
        ),
        is_hot_path=False,
        is_startup_only=False,
    ),

    CanonicalLayer.STARTUP_RELEASE_INTEGRITY: LayerDeclaration(
        layer=CanonicalLayer.STARTUP_RELEASE_INTEGRITY,
        label="Startup / Readiness / Health / Release Integrity Boundary",
        version_tag="V6",
        scope=(
            "Structural integrity boundary: blocks releases when critical "
            "readiness checks fail.  Evaluated at CI time and system startup.  "
            "NOT a per-request runtime gate."
        ),
        canonical_modules=(
            "core.release_blocking_gate",
        ),
        not_policies=(
            V6_IS_NOT_PER_REQUEST_GATE,
        ),
        is_hot_path=False,
        is_startup_only=True,
    ),
}

#: Frozenset of all valid :class:`CanonicalLayer` string values.
CANONICAL_LAYER_KEYS: FrozenSet[str] = frozenset(
    layer.value for layer in CanonicalLayer
)

# ---------------------------------------------------------------------------
# Finding data types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class LayerFinding:
    """A single finding from a layer model consistency check."""

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


@dataclasses.dataclass
class LayerModelReport:
    """Aggregated result of layer model invariant checks."""

    findings: List[LayerFinding] = dataclasses.field(default_factory=list)
    checks_run: List[str] = dataclasses.field(default_factory=list)
    overall_consistent: bool = True
    error_count: int = 0
    warning_count: int = 0

    def __post_init__(self) -> None:
        self._recompute()

    def _recompute(self) -> None:
        self.error_count = sum(1 for f in self.findings if f.severity == "error")
        self.warning_count = sum(1 for f in self.findings if f.severity == "warning")
        self.overall_consistent = self.error_count == 0

    def add(self, finding: LayerFinding) -> None:
        self.findings.append(finding)
        self._recompute()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_consistent": self.overall_consistent,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "checks_run": list(self.checks_run),
            "findings": [f.to_dict() for f in self.findings],
        }


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _lf_error(check: str, message: str, detail: Optional[Dict[str, Any]] = None) -> LayerFinding:
    return LayerFinding(check=check, severity="error", message=message, detail=detail or {})


def _lf_warn(check: str, message: str, detail: Optional[Dict[str, Any]] = None) -> LayerFinding:
    return LayerFinding(check=check, severity="warning", message=message, detail=detail or {})


def _lf_info(check: str, message: str, detail: Optional[Dict[str, Any]] = None) -> LayerFinding:
    return LayerFinding(check=check, severity="info", message=message, detail=detail or {})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_layer_declaration(layer: CanonicalLayer) -> LayerDeclaration:
    """Return the :class:`LayerDeclaration` for the given *layer*.

    Parameters
    ----------
    layer:
        A :class:`CanonicalLayer` member.

    Returns
    -------
    LayerDeclaration
        The registry entry for *layer*.

    Raises
    ------
    KeyError
        If *layer* is not in :data:`CANONICAL_LAYER_REGISTRY` (should never
        happen for a valid :class:`CanonicalLayer` member).
    """
    return CANONICAL_LAYER_REGISTRY[layer]


def check_layer_model_consistent(
    layer_snapshot: Dict[str, Any],
) -> List[LayerFinding]:
    """Check that a single layer snapshot is consistent with the canonical layer model.

    A ``layer_snapshot`` is a plain dict that describes one layer as
    observed at runtime or in a diagnostic / test context.  It should carry
    at minimum a ``layer_key`` field with a value from :data:`CANONICAL_LAYER_KEYS`.

    The check validates:

    1. ``layer_key`` is a known :class:`CanonicalLayer` value.
    2. If ``is_hot_path`` is present, it matches the declared hot-path status.
    3. If ``is_startup_only`` is present, it matches the declared startup-only status.
    4. V4-specific: if ``is_per_request_gate`` is present and True, emit an error.
    5. V6-specific: if ``is_per_request_gate`` is present and True, emit an error.
    6. L1/L2/L3-specific: if ``is_shadow_stack`` is present and True, emit an error.
    7. Completion truth: if ``is_optional_signaling`` is present and True, emit an error.

    Parameters
    ----------
    layer_snapshot:
        Dict describing an observed layer.

    Returns
    -------
    List[LayerFinding]
        Empty list when all checks pass; findings for each issue.
    """
    check = "LAYER_MODEL_CONSISTENT"
    findings: List[LayerFinding] = []

    layer_key = layer_snapshot.get("layer_key", "")
    if layer_key not in CANONICAL_LAYER_KEYS:
        findings.append(
            _lf_error(
                check,
                f"Unknown layer_key '{layer_key}'. "
                f"Expected one of: {sorted(CANONICAL_LAYER_KEYS)}.",
                {"layer_key": layer_key},
            )
        )
        return findings

    try:
        layer = CanonicalLayer(layer_key)
    except ValueError:
        findings.append(
            _lf_error(check, f"layer_key '{layer_key}' is not a valid CanonicalLayer value.",
                      {"layer_key": layer_key})
        )
        return findings

    declaration = CANONICAL_LAYER_REGISTRY[layer]

    # Check is_hot_path consistency.
    observed_hot_path = layer_snapshot.get("is_hot_path")
    if observed_hot_path is not None and observed_hot_path != declaration.is_hot_path:
        findings.append(
            _lf_error(
                check,
                f"Layer '{layer_key}' declares is_hot_path={observed_hot_path} but "
                f"the canonical model requires is_hot_path={declaration.is_hot_path}.",
                {"layer_key": layer_key, "observed": observed_hot_path,
                 "expected": declaration.is_hot_path},
            )
        )

    # Check is_startup_only consistency.
    observed_startup_only = layer_snapshot.get("is_startup_only")
    if observed_startup_only is not None and observed_startup_only != declaration.is_startup_only:
        findings.append(
            _lf_error(
                check,
                f"Layer '{layer_key}' declares is_startup_only={observed_startup_only} but "
                f"the canonical model requires is_startup_only={declaration.is_startup_only}.",
                {"layer_key": layer_key, "observed": observed_startup_only,
                 "expected": declaration.is_startup_only},
            )
        )

    # V4-specific: must NOT be declared as a per-request gate.
    if layer == CanonicalLayer.MULTI_STEP_ORCHESTRATION_SPINE:
        if layer_snapshot.get("is_per_request_gate") is True:
            findings.append(
                _lf_error(
                    check,
                    "V4 unified_orchestration_spine is declared as is_per_request_gate=True, "
                    "which violates the V4_IS_NOT_PER_REQUEST_GATE boundary invariant.",
                    {"layer_key": layer_key, "violation": "V4_IS_NOT_PER_REQUEST_GATE"},
                )
            )

    # V6-specific: must NOT be declared as a per-request gate.
    if layer == CanonicalLayer.STARTUP_RELEASE_INTEGRITY:
        if layer_snapshot.get("is_per_request_gate") is True:
            findings.append(
                _lf_error(
                    check,
                    "V6 release_blocking_gate is declared as is_per_request_gate=True, "
                    "which violates the V6_IS_NOT_PER_REQUEST_GATE boundary invariant.",
                    {"layer_key": layer_key, "violation": "V6_IS_NOT_PER_REQUEST_GATE"},
                )
            )

    # L1/L2/L3-specific: must NOT be declared as a detached shadow stack.
    if layer == CanonicalLayer.ROUTER_COGNITIVE_AUTHORITY:
        if layer_snapshot.get("is_shadow_stack") is True:
            findings.append(
                _lf_error(
                    check,
                    "L1/L2/L3 router cognitive authority is declared as is_shadow_stack=True, "
                    "which violates the L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK "
                    "boundary invariant.",
                    {"layer_key": layer_key,
                     "violation": "L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK"},
                )
            )

    # Completion truth: must NOT be declared as optional signaling.
    if layer == CanonicalLayer.COMPLETION_TRUTH_BACKBONE:
        if layer_snapshot.get("is_optional_signaling") is True:
            findings.append(
                _lf_error(
                    check,
                    "Completion truth backbone is declared as is_optional_signaling=True, "
                    "which violates the COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL "
                    "boundary invariant.",
                    {"layer_key": layer_key,
                     "violation": "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL"},
                )
            )

    if not findings:
        findings.append(
            _lf_info(
                check,
                f"Layer '{layer_key}' ({declaration.label}) is consistent with "
                "the canonical layer model.",
                {"layer_key": layer_key, "label": declaration.label},
            )
        )

    return findings


def run_layer_model_invariants(
    layer_snapshots: Optional[List[Dict[str, Any]]] = None,
) -> LayerModelReport:
    """Run canonical layer model invariant checks over a list of layer snapshots.

    If *layer_snapshots* is None or empty, the function validates the
    internal consistency of the :data:`CANONICAL_LAYER_REGISTRY` itself
    (all five layers are declared, all NOT-policies are non-empty strings,
    canonical_modules are non-empty).

    Parameters
    ----------
    layer_snapshots:
        Optional list of layer snapshot dicts to check.  Each must have a
        ``layer_key`` field.

    Returns
    -------
    LayerModelReport
        Aggregated report.
    """
    report = LayerModelReport()
    check_name = "LAYER_MODEL_CONSISTENT"
    report.checks_run.append(check_name)

    # Always validate the registry itself first.
    _validate_registry(report)

    # Validate each supplied snapshot.
    if layer_snapshots:
        for snapshot in layer_snapshots:
            for finding in check_layer_model_consistent(snapshot):
                report.add(finding)

    if report.overall_consistent:
        logger.debug(
            "Canonical layer model invariants: all checks passed "
            "(errors=0, warnings=%d)",
            report.warning_count,
        )
    else:
        logger.warning(
            "Canonical layer model invariants: %d error(s) found — "
            "overall_consistent=False",
            report.error_count,
        )

    return report


# ---------------------------------------------------------------------------
# Internal registry validation
# ---------------------------------------------------------------------------


def _validate_registry(report: LayerModelReport) -> None:
    """Validate internal consistency of :data:`CANONICAL_LAYER_REGISTRY`."""
    check = "LAYER_REGISTRY_SELF_CONSISTENT"
    if check not in report.checks_run:
        report.checks_run.append(check)

    # All five CanonicalLayer members must be present.
    for layer in CanonicalLayer:
        if layer not in CANONICAL_LAYER_REGISTRY:
            report.add(
                _lf_error(
                    check,
                    f"CanonicalLayer.{layer.name} is missing from CANONICAL_LAYER_REGISTRY.",
                    {"layer": layer.value},
                )
            )
            continue

        decl = CANONICAL_LAYER_REGISTRY[layer]

        # canonical_modules must be non-empty.
        if not decl.canonical_modules:
            report.add(
                _lf_error(
                    check,
                    f"Layer '{layer.value}' has no canonical_modules declared.",
                    {"layer": layer.value},
                )
            )

        # NOT-policies for boundary layers must be non-empty strings.
        for policy in decl.not_policies:
            if not isinstance(policy, str) or not policy.strip():
                report.add(
                    _lf_error(
                        check,
                        f"Layer '{layer.value}' has an empty or non-string NOT-policy.",
                        {"layer": layer.value},
                    )
                )

    # Hot-path layers: PER_REQUEST_HOT_PATH and ROUTER_COGNITIVE_AUTHORITY.
    hot_path_layers = {CanonicalLayer.PER_REQUEST_HOT_PATH, CanonicalLayer.ROUTER_COGNITIVE_AUTHORITY}
    non_hot_path_layers = set(CanonicalLayer) - hot_path_layers

    for layer in hot_path_layers:
        decl = CANONICAL_LAYER_REGISTRY.get(layer)
        if decl and not decl.is_hot_path:
            report.add(
                _lf_error(
                    check,
                    f"Layer '{layer.value}' should be is_hot_path=True but is False.",
                    {"layer": layer.value},
                )
            )

    for layer in non_hot_path_layers:
        decl = CANONICAL_LAYER_REGISTRY.get(layer)
        if decl and decl.is_hot_path:
            report.add(
                _lf_error(
                    check,
                    f"Layer '{layer.value}' is declared is_hot_path=True but should be False.",
                    {"layer": layer.value},
                )
            )

    # Only STARTUP_RELEASE_INTEGRITY should be is_startup_only=True.
    for layer in CanonicalLayer:
        decl = CANONICAL_LAYER_REGISTRY.get(layer)
        if decl is None:
            continue
        expected_startup_only = layer == CanonicalLayer.STARTUP_RELEASE_INTEGRITY
        if decl.is_startup_only != expected_startup_only:
            report.add(
                _lf_error(
                    check,
                    f"Layer '{layer.value}' has is_startup_only={decl.is_startup_only} "
                    f"but expected {expected_startup_only}.",
                    {"layer": layer.value, "expected_startup_only": expected_startup_only},
                )
            )
