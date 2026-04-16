#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/runtime_truth_output_chain.py
====================================
PR-9 (realization-v2 convergence plan): Explicit runtime-truth to
outward-truth compilation and output chain.

This module is the canonical authority for documenting and enforcing the
ordered chain from internal runtime-truth compilation to external outward-truth
assembly and projection output.

Problem addressed
-----------------
After PRs #6–#8 (authority boundary, truth/projection separation, and
conformance scaffolding), the internal canonical pipeline is well-governed.
However, both the runtime truth compiler and the outward truth assembler still
present themselves as broadly authoritative, creating:

- Ambiguity about which layer is responsible at each stage of the output chain.
- Risk of *repeated assembly*: a single request may invoke
  ``compile_runtime_truth()`` and ``compile_outward_truth()`` independently,
  causing duplicate subsystem queries.
- *Multi-layer single-authority inflation*: both layers claim "single
  compilation point" responsibility, making it unclear which claim takes
  precedence for outward consumers.
- *Projection-layer bloat*: route handlers may bypass the outward truth layer
  and re-assemble directly from ``compile_runtime_truth()``, duplicating logic.
- Long-term maintainability degradation: the absence of an explicit chain
  contract makes it hard to reason about output correctness.

This module resolves that ambiguity by:

1. Establishing an explicit, ordered chain with distinct stage roles.
2. Providing policy sentinels that prevent out-of-order or repeated assembly.
3. Documenting the canonical dependency order so future work can verify
   compliance.
4. Classifying known surfaces into their correct chain stage.

Chain
-----
::

    ┌────────────────────────────────────────────────────────────────────┐
    │  STAGE 3 — PROJECTION / OUTPUT SURFACES (consumers)               │
    │  core.routes.projection._assemble_runtime_truth_payload()         │
    │  GET /api/v1/projection/runtime-truth                             │
    │  desktop_status_board · operator_snapshot                         │
    │                                                                    │
    │  Rule: MUST read from compile_outward_truth() (Stage 2).          │
    │        MUST NOT call compile_runtime_truth() (Stage 1) directly   │
    │        when Stage 2 is available.                                  │
    └──────────────────────────────┬─────────────────────────────────────┘
                                   │  READS COMPILED OUTWARD TRUTH
                                   ▼
    ┌────────────────────────────────────────────────────────────────────┐
    │  STAGE 2 — OUTWARD TRUTH ASSEMBLER (outward-facing)               │
    │  core.outward_runtime_truth.compile_outward_truth()               │
    │  OutwardRuntimeTruthSnapshot                                      │
    │                                                                    │
    │  Rule: Calls Stage 1 ONCE as its primary subsystem input.         │
    │        Adds operator/bridge/ACE context enrichment.               │
    │        Is the single outward compilation point.                    │
    └──────────────────────────────┬─────────────────────────────────────┘
                                   │  READS COMPILED RUNTIME TRUTH
                                   ▼
    ┌────────────────────────────────────────────────────────────────────┐
    │  STAGE 1 — RUNTIME TRUTH COMPILER (internal)                      │
    │  core.projection.runtime_truth_compiler.compile_runtime_truth()   │
    │  RuntimeTruthSnapshot                                             │
    │                                                                    │
    │  Rule: Gathers state from all canonical subsystems ONCE.          │
    │        Produces an internal-only snapshot.                         │
    │        MUST NOT be called directly by Stage 3 surfaces when        │
    │        Stage 2 is available.                                       │
    └────────────────────────────────────────────────────────────────────┘

Governance invariants
---------------------
1. **Stage ordering is unidirectional.** The chain flows Stage 1 → Stage 2 →
   Stage 3.  No stage may depend on a stage downstream of itself.
   Governed by: :data:`STAGE_ORDERING_IS_UNIDIRECTIONAL_POLICY`.

2. **Outward assembler is the sole output authority.** Stage 3 surfaces MUST
   source from Stage 2 (``compile_outward_truth()``) rather than calling Stage 1
   (``compile_runtime_truth()``) directly.
   Governed by: :data:`OUTWARD_ASSEMBLER_IS_SOLE_OUTPUT_AUTHORITY_POLICY`.

3. **No repeated compilation within a single request.** Each stage MUST be
   invoked at most once per outward output cycle; repeated invocations produce
   duplicate subsystem queries and inflate latency.
   Governed by: :data:`NO_REPEATED_STAGE_COMPILATION_WITHIN_REQUEST_POLICY`.

4. **Stage role inflation is prohibited.** Each stage has a distinct, bounded
   role.  A stage MUST NOT claim authority beyond its defined scope.
   Governed by: :data:`STAGE_ROLE_INFLATION_IS_PROHIBITED_POLICY`.

Public API
----------
Authority sentinels::

    RUNTIME_TRUTH_OUTPUT_CHAIN_IS_AUTHORITY
    RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL

Policy sentinels::

    STAGE_ORDERING_IS_UNIDIRECTIONAL_POLICY
    OUTWARD_ASSEMBLER_IS_SOLE_OUTPUT_AUTHORITY_POLICY
    NO_REPEATED_STAGE_COMPILATION_WITHIN_REQUEST_POLICY
    STAGE_ROLE_INFLATION_IS_PROHIBITED_POLICY

Enums::

    TruthOutputStage

Dataclasses::

    ChainStageRecord
    OutputChainSnapshot

Functions::

    build_output_chain_catalog() -> List[ChainStageRecord]
    classify_output_stage(surface_ref) -> str
    find_stage_ordering_violations() -> List[ChainStageRecord]
    build_output_chain_snapshot() -> OutputChainSnapshot
    get_stage_record(stage) -> ChainStageRecord
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    # Authority sentinels
    "RUNTIME_TRUTH_OUTPUT_CHAIN_IS_AUTHORITY",
    "RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL",
    # Policy sentinels
    "STAGE_ORDERING_IS_UNIDIRECTIONAL_POLICY",
    "OUTWARD_ASSEMBLER_IS_SOLE_OUTPUT_AUTHORITY_POLICY",
    "NO_REPEATED_STAGE_COMPILATION_WITHIN_REQUEST_POLICY",
    "STAGE_ROLE_INFLATION_IS_PROHIBITED_POLICY",
    # Enums
    "TruthOutputStage",
    # Dataclasses
    "ChainStageRecord",
    "OutputChainSnapshot",
    # Functions
    "build_output_chain_catalog",
    "classify_output_stage",
    "find_stage_ordering_violations",
    "build_output_chain_snapshot",
    "get_stage_record",
]

# ===========================================================================
# Authority sentinels
# ===========================================================================

#: Identifies this module as the canonical authority for the runtime-truth to
#: outward-truth compilation and output chain.
RUNTIME_TRUTH_OUTPUT_CHAIN_IS_AUTHORITY: str = (
    "RUNTIME_TRUTH_OUTPUT_CHAIN_IS_AUTHORITY_V1: "
    "core.runtime_truth_output_chain is the canonical governance module for the "
    "ordered runtime-truth → outward-truth → projection output chain.  "
    "PR-9 (realization-v2 convergence plan).  "
    "Stage roles, directionality, and single-output expectations are explicit here."
)

#: PR-9 sentinel confirming the chain is explicitly classified and governed.
RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL: str = (
    "RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL_V1: "
    "PR-9 runtime-truth output chain is explicitly ordered as "
    "Stage 1 (RuntimeTruthCompiler) → Stage 2 (OutwardRuntimeTruth) → "
    "Stage 3 (Projection/Output Surfaces).  "
    "Repeated assembly and stage-role inflation are policy-prohibited."
)

# ===========================================================================
# Policy sentinels
# ===========================================================================

STAGE_ORDERING_IS_UNIDIRECTIONAL_POLICY: str = (
    "STAGE_ORDERING_IS_UNIDIRECTIONAL_POLICY_V1: "
    "The runtime-truth output chain flows strictly Stage 1 → Stage 2 → Stage 3.  "
    "No stage may read from or depend on a downstream stage.  "
    "Backward dependencies cause circular authority and must not be introduced."
)

OUTWARD_ASSEMBLER_IS_SOLE_OUTPUT_AUTHORITY_POLICY: str = (
    "OUTWARD_ASSEMBLER_IS_SOLE_OUTPUT_AUTHORITY_V1: "
    "Stage 3 projection and output surfaces MUST source outward runtime state from "
    "compile_outward_truth() (Stage 2).  Calling compile_runtime_truth() (Stage 1) "
    "directly from Stage 3 when Stage 2 is available bypasses the outward assembler "
    "and risks divergent output.  The outward assembler is the sole output authority "
    "for downstream consumers."
)

NO_REPEATED_STAGE_COMPILATION_WITHIN_REQUEST_POLICY: str = (
    "NO_REPEATED_STAGE_COMPILATION_WITHIN_REQUEST_V1: "
    "Each chain stage MUST be invoked at most once per outward output cycle "
    "(e.g. per HTTP request or per desktop projection tick).  Invoking "
    "compile_runtime_truth() multiple times or compile_outward_truth() multiple "
    "times within the same request produces duplicate subsystem queries, inflates "
    "latency, and may surface inconsistent snapshots."
)

STAGE_ROLE_INFLATION_IS_PROHIBITED_POLICY: str = (
    "STAGE_ROLE_INFLATION_IS_PROHIBITED_V1: "
    "Each stage has a distinct, bounded role and MUST NOT claim authority beyond "
    "its defined scope.  Stage 1 is an internal subsystem aggregator.  "
    "Stage 2 is the single outward assembler.  Stage 3 surfaces are read-only "
    "consumers.  Stages MUST NOT self-promote into neighbouring roles."
)

# ===========================================================================
# Enums
# ===========================================================================


class TruthOutputStage(str, Enum):
    """Ordered stage in the runtime-truth to outward-truth output chain."""

    INTERNAL_COMPILER = "internal_compiler"
    """Stage 1: RuntimeTruthCompiler — internal subsystem aggregator.

    Responsible for gathering state from all canonical subsystems once and
    producing a ``RuntimeTruthSnapshot``.  This snapshot is internal-facing
    and MUST NOT be consumed directly by projection surfaces when Stage 2 is
    available.
    """

    OUTWARD_ASSEMBLER = "outward_assembler"
    """Stage 2: OutwardRuntimeTruth — single outward compilation point.

    Responsible for calling Stage 1 once, enriching the result with operator,
    bridge, and ACE context, and producing an ``OutwardRuntimeTruthSnapshot``
    that is the canonical data source for all downstream consumers.
    """

    PROJECTION_SURFACE = "projection_surface"
    """Stage 3: Projection / output surfaces — read-only consumers.

    Route handlers, desktop status boards, operator snapshots, and monitoring
    integrations that read from Stage 2 and expose state externally.  MUST
    NOT bypass Stage 2 by calling Stage 1 directly.
    """


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass(frozen=True)
class ChainStageRecord:
    """Description of a single stage in the runtime-truth output chain."""

    stage: TruthOutputStage
    """The stage this record describes."""

    stage_index: int
    """Numeric position in the chain (1, 2, 3)."""

    display_name: str
    """Human-readable label for the stage."""

    primary_module: str
    """Canonical module path for the primary implementation of this stage."""

    primary_function: str
    """Canonical function name that implements this stage."""

    output_type: str
    """Name of the output object produced by this stage."""

    responsibility_summary: str
    """One-sentence description of this stage's bounded role."""

    may_call_stages: Tuple[int, ...]
    """Stage indices this stage is permitted to call (always upstream only)."""

    known_surface_ids: Tuple[str, ...]
    """Known surface IDs classified as belonging to this stage."""

    governance_constraint: str
    """The policy sentinel governing this stage's boundaries."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "stage_index": self.stage_index,
            "display_name": self.display_name,
            "primary_module": self.primary_module,
            "primary_function": self.primary_function,
            "output_type": self.output_type,
            "responsibility_summary": self.responsibility_summary,
            "may_call_stages": list(self.may_call_stages),
            "known_surface_ids": list(self.known_surface_ids),
            "governance_constraint": self.governance_constraint,
        }


@dataclass(frozen=True)
class OutputChainSnapshot:
    """Diagnostic snapshot of the full runtime-truth output chain."""

    authority: str
    sentinel: str
    policies: Tuple[str, ...]
    stages: Tuple[ChainStageRecord, ...]
    ordering_violations: Tuple[ChainStageRecord, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "sentinel": self.sentinel,
            "policies": list(self.policies),
            "stage_count": len(self.stages),
            "stages": [s.to_dict() for s in self.stages],
            "ordering_violations": [s.to_dict() for s in self.ordering_violations],
            "chain_is_clean": len(self.ordering_violations) == 0,
        }


# ===========================================================================
# Catalog
# ===========================================================================

_CHAIN_CATALOG: Optional[List[ChainStageRecord]] = None


def build_output_chain_catalog() -> List[ChainStageRecord]:
    """Return the ordered list of chain stage records (Stage 1 → 2 → 3).

    The returned list is stable and ordered by :attr:`ChainStageRecord.stage_index`.
    Callers may iterate this list to inspect the full chain contract without
    importing any of the implementation modules.

    Returns
    -------
    List[ChainStageRecord]
        Three entries, one per :class:`TruthOutputStage`.
    """
    global _CHAIN_CATALOG
    if _CHAIN_CATALOG is not None:
        return list(_CHAIN_CATALOG)
    catalog = [
        ChainStageRecord(
            stage=TruthOutputStage.INTERNAL_COMPILER,
            stage_index=1,
            display_name="RuntimeTruthCompiler",
            primary_module="core.projection.runtime_truth_compiler",
            primary_function="compile_runtime_truth",
            output_type="RuntimeTruthSnapshot",
            responsibility_summary=(
                "Gather state from all canonical subsystems once and produce an "
                "internal-only RuntimeTruthSnapshot; Must not be called directly "
                "from Stage 3 when Stage 2 is available."
            ),
            may_call_stages=(),
            known_surface_ids=(
                "runtime_truth_compiler",
                "core.projection.runtime_truth_compiler.compile_runtime_truth",
                "RuntimeTruthSnapshot",
            ),
            governance_constraint=STAGE_ORDERING_IS_UNIDIRECTIONAL_POLICY,
        ),
        ChainStageRecord(
            stage=TruthOutputStage.OUTWARD_ASSEMBLER,
            stage_index=2,
            display_name="OutwardRuntimeTruth",
            primary_module="core.outward_runtime_truth",
            primary_function="compile_outward_truth",
            output_type="OutwardRuntimeTruthSnapshot",
            responsibility_summary=(
                "Call Stage 1 once, enrich with operator/bridge/ACE context, and "
                "produce an OutwardRuntimeTruthSnapshot that serves as the sole "
                "authoritative data source for all downstream consumers."
            ),
            may_call_stages=(1,),
            known_surface_ids=(
                "outward_runtime_truth",
                "core.outward_runtime_truth.compile_outward_truth",
                "OutwardRuntimeTruthSnapshot",
                "OutwardRuntimeTruthRuntime",
            ),
            governance_constraint=OUTWARD_ASSEMBLER_IS_SOLE_OUTPUT_AUTHORITY_POLICY,
        ),
        ChainStageRecord(
            stage=TruthOutputStage.PROJECTION_SURFACE,
            stage_index=3,
            display_name="ProjectionOutputSurfaces",
            primary_module="core.routes.projection",
            primary_function="_assemble_runtime_truth_payload",
            output_type="RuntimeTruthPayload",
            responsibility_summary=(
                "Read from Stage 2 (compile_outward_truth) and surface compiled state "
                "via API endpoints, desktop status board, and operator snapshots; "
                "Must not call Stage 1 directly when Stage 2 is available."
            ),
            may_call_stages=(2,),
            known_surface_ids=(
                "projection_runtime_truth_route",
                "core.routes.projection._assemble_runtime_truth_payload",
                "GET /api/v1/projection/runtime-truth",
                "desktop_status_board_payload",
                "operator_snapshot_surface",
            ),
            governance_constraint=STAGE_ROLE_INFLATION_IS_PROHIBITED_POLICY,
        ),
    ]
    _CHAIN_CATALOG = catalog
    return list(catalog)


# ===========================================================================
# Query helpers
# ===========================================================================


def get_stage_record(stage: TruthOutputStage) -> ChainStageRecord:
    """Return the :class:`ChainStageRecord` for the given *stage*.

    Parameters
    ----------
    stage:
        The :class:`TruthOutputStage` to look up.

    Returns
    -------
    ChainStageRecord
        The record for the requested stage.

    Raises
    ------
    KeyError
        If *stage* is not found in the catalog (should not happen in normal use).
    """
    for record in build_output_chain_catalog():
        if record.stage is stage:
            return record
    raise KeyError(f"Stage not found in catalog: {stage!r}")


def classify_output_stage(surface_ref: str) -> str:
    """Classify *surface_ref* into its chain stage value.

    Parameters
    ----------
    surface_ref:
        A surface ID or module path string to look up.

    Returns
    -------
    str
        The :attr:`TruthOutputStage.value` of the matching stage, or
        ``"unknown"`` if no match is found.
    """
    normalised = (surface_ref or "").strip()
    if not normalised:
        return "unknown"
    for record in build_output_chain_catalog():
        if normalised in record.known_surface_ids:
            return record.stage.value
        if normalised == record.primary_module or normalised == record.primary_function:
            return record.stage.value
    return "unknown"


def find_stage_ordering_violations() -> List[ChainStageRecord]:
    """Return any chain stage records whose ``may_call_stages`` include downstream indices.

    In a correctly ordered chain, :attr:`ChainStageRecord.may_call_stages` must
    only contain indices strictly less than :attr:`ChainStageRecord.stage_index`
    (upstream only).  This helper detects any misconfigured records.

    Returns
    -------
    List[ChainStageRecord]
        Records that violate the unidirectional ordering constraint.  An empty
        list means the chain is clean.
    """
    violations: List[ChainStageRecord] = []
    for record in build_output_chain_catalog():
        for called_index in record.may_call_stages:
            if called_index >= record.stage_index:
                violations.append(record)
                break
    return violations


def build_output_chain_snapshot() -> OutputChainSnapshot:
    """Build a full diagnostic snapshot of the runtime-truth output chain.

    Returns
    -------
    OutputChainSnapshot
        Contains the authority/sentinel/policies, all stage records, and any
        ordering violations detected.
    """
    stages = build_output_chain_catalog()
    violations = find_stage_ordering_violations()
    return OutputChainSnapshot(
        authority=RUNTIME_TRUTH_OUTPUT_CHAIN_IS_AUTHORITY,
        sentinel=RUNTIME_TRUTH_OUTPUT_CHAIN_PR9_SENTINEL,
        policies=(
            STAGE_ORDERING_IS_UNIDIRECTIONAL_POLICY,
            OUTWARD_ASSEMBLER_IS_SOLE_OUTPUT_AUTHORITY_POLICY,
            NO_REPEATED_STAGE_COMPILATION_WITHIN_REQUEST_POLICY,
            STAGE_ROLE_INFLATION_IS_PROHIBITED_POLICY,
        ),
        stages=tuple(stages),
        ordering_violations=tuple(violations),
    )
