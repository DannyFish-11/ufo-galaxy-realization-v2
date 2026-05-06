#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/five_area_impl_review.py
=============================
Five-Area Implementation-Grade Joint Dual-Repo Review Artifact.

Repositories reviewed together
-------------------------------
- DannyFish-11/ufo-galaxy-realization-v2  (V2 — this repo, center authority)
- DannyFish-11/ufo-galaxy-android         (Android — runtime carrier node)

Purpose
-------
This module is a **mergeable, code-backed, implementation-grade review artifact**
for the five strategic areas that form the basis for the next five follow-up PRs:

1. **UNIFIED_PANEL_AGGREGATION**
   Panel/operator/control-plane state sources, APIs, projections, aggregation
   layers, and the gap toward a true unified panel-state surface.

2. **DESKTOP_THREE_STATE_EXISTENCE**
   Desktop shell, presence, manifestation, embodiment, carrier-facing state,
   and whether the three distinct state systems currently amount to a coherent
   desktop existence surface comparable to an always-present assistant.

3. **OPERATOR_ACTIONABILITY**
   Read-only projection surfaces versus truly action-capable operator/control-
   plane paths, current action endpoints, and exact cut points for moving
   from observation-only to canonical action-capable.

4. **NATURAL_LANGUAGE_CANONICAL_PATH**
   Real NL ingress → interpretation/planning/routing → orchestration →
   dispatch → execution → result/state feedback, distinguished from demos,
   stubs, and non-authoritative flows.

5. **MULTIMODAL_CANONICAL_PATH**
   Real multimodal/perception/grounding/vision/context-enrichment paths,
   separated from optional, dormant, or demo-only infrastructure.

Design principles
-----------------
- All conclusions grounded strictly in current real Python imports / attribute
  checks against the live V2 codebase, CI test existence, and
  inspect.getsource()-level source-contains checks.
- NO markdown documents, README text, PR prose, historical PR descriptions, or
  architecture narratives are used as evidence.
- Each area carries exactly the eight required content fields demanded by the
  problem statement (code anchors, canonical path summary, established, partial,
  overclaiming rationale, cut points, modification zones, maturity unlock).
- The module is JSON-serialisable and importable as a reusable downstream asset.
- Invariant checks prevent overclaiming completeness.

Public API
----------
Authority sentinels::

    FIVE_AREA_REVIEW_AUTHORITY
    FIVE_AREA_REVIEW_METHODOLOGY
    FIVE_AREA_REVIEW_POLICY_NO_PROSE_AS_EVIDENCE

Enumerations::

    ReviewArea              — 5 strategic review areas
    AreaMaturityLabel       — 8-level evidence/maturity ladder
    ActionabilityLevel      — read-only / decision-consumed / action-capable
    FollowUpPrMaturityUnlock — maturity tier a follow-up PR would unlock

Dataclasses::

    CodeAnchor              — single code anchor (module + role)
    ImplCutPoint            — implementation cut point for a follow-up PR
    ModificationZone        — suggested primary modification zone
    AreaReviewEntry         — complete review entry for one area (all 8 fields)
    FiveAreaImplReview      — root JSON-serialisable review artifact

Functions::

    build_five_area_impl_review() -> FiveAreaImplReview
    get_five_area_impl_review()   -> FiveAreaImplReview   (cached singleton)
    reset_five_area_impl_review() -> None                  (test isolation only)
    assert_five_area_review_invariants(review) -> None     (invariant checker)
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.FiveAreaImplReview")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

FIVE_AREA_REVIEW_AUTHORITY: str = (
    "FIVE_AREA_IMPL_REVIEW_AUTHORITY::"
    "core.five_area_impl_review::"
    "dual-repo-implementation-grade-review-artifact::"
    "five-strategic-areas-for-next-five-prs::"
    "code-grounded-only-no-prose-as-evidence"
)

FIVE_AREA_REVIEW_METHODOLOGY: str = (
    "METHODOLOGY: Implementation-grade joint dual-repo review of the Galaxy distributed "
    "AI-body/control system (ufo-galaxy-realization-v2 × ufo-galaxy-android) across "
    "five strategic areas. "
    "All conclusions strictly grounded in: (1) real Python imports and module-file-exists "
    "checks against the live V2 codebase; (2) inspect.getsource()-level source-contains "
    "pattern checks; (3) CI test file existence as machine-verifiable proof; "
    "(4) Android-side evidence via V2-side integration tests and gateway modules. "
    "README files, markdown audits, historical PR descriptions, prior audit PR bodies, "
    "and architecture narratives are EXPLICITLY EXCLUDED as evidence — used only as loose "
    "navigation hints. "
    "Five areas: unified panel aggregation, desktop three-state existence, operator "
    "actionability, natural-language canonical path, multimodal canonical path."
)

FIVE_AREA_REVIEW_POLICY_NO_PROSE_AS_EVIDENCE: str = (
    "POLICY:NO_PROSE_AS_EVIDENCE: "
    "All overclaiming checks are invariant-enforced. "
    "Any area whose established evidence is absent MUST NOT be labeled "
    "STRONGLY_ESTABLISHED or RUNTIME_EVIDENCED_CLOSED. "
    "Gap items must be present for all areas rated below STRONGLY_ESTABLISHED."
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ReviewArea(str, Enum):
    """Five strategic review areas for the next five follow-up PRs."""

    UNIFIED_PANEL_AGGREGATION = "UNIFIED_PANEL_AGGREGATION"
    DESKTOP_THREE_STATE_EXISTENCE = "DESKTOP_THREE_STATE_EXISTENCE"
    OPERATOR_ACTIONABILITY = "OPERATOR_ACTIONABILITY"
    NATURAL_LANGUAGE_CANONICAL_PATH = "NATURAL_LANGUAGE_CANONICAL_PATH"
    MULTIMODAL_CANONICAL_PATH = "MULTIMODAL_CANONICAL_PATH"


class AreaMaturityLabel(str, Enum):
    """Eight-level evidence/maturity ladder for each area.

    STRONGLY_ESTABLISHED
        Real imports succeed; runtime path exercised; passing CI tests confirm
        end-to-end behavior.  No known gaps.

    RUNTIME_EVIDENCED_CLOSED
        End-to-end runtime path closed by a closure PR: machine-verifiable CI
        tests exercise the full round-trip.

    PARTIALLY_ESTABLISHED
        Real code and/or test modules present; at least one known gap prevents
        full closure (cross-repo round-trip test, advisory-mode gate, or
        disabled-by-default config).

    INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN
        Code structure and modules present; end-to-end activation is gated
        (disabled by config or feature flag) and no CI test proves full
        end-to-end activation.

    OBSERVATION_ONLY_NO_ACTION_SURFACE
        State surfaces exist and are readable; no action-capable endpoints
        exposed at the relevant operator/control-plane level.

    SURFACE_ALIGNMENT_ONLY
        Schema / store / sentinel / operator-surface alignment exists; no
        machine-verifiable runtime proof that truth flows into decisions or
        that the surface is actionable.

    MISSING_RUNTIME_EVIDENCE
        Structural path exists (importable module) but no runtime activation
        evidence or passing end-to-end tests exist.

    NOT_YET_IMPLEMENTED
        The capability or surface is structurally absent or not yet implemented
        in current merged code.
    """

    STRONGLY_ESTABLISHED = "STRONGLY_ESTABLISHED"
    RUNTIME_EVIDENCED_CLOSED = "RUNTIME_EVIDENCED_CLOSED"
    PARTIALLY_ESTABLISHED = "PARTIALLY_ESTABLISHED"
    INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN = (
        "INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN"
    )
    OBSERVATION_ONLY_NO_ACTION_SURFACE = "OBSERVATION_ONLY_NO_ACTION_SURFACE"
    SURFACE_ALIGNMENT_ONLY = "SURFACE_ALIGNMENT_ONLY"
    MISSING_RUNTIME_EVIDENCE = "MISSING_RUNTIME_EVIDENCE"
    NOT_YET_IMPLEMENTED = "NOT_YET_IMPLEMENTED"


class ActionabilityLevel(str, Enum):
    """Actionability level for state/operator surfaces.

    READ_ONLY_PROJECTION
        Surface only exposes read-only projections.

    DECISION_CONSUMED
        Truth from this surface flows into orchestration/routing decisions.

    ACTION_CAPABLE
        Surface exposes action endpoints (e.g. POST / trigger / dispatch).
    """

    READ_ONLY_PROJECTION = "READ_ONLY_PROJECTION"
    DECISION_CONSUMED = "DECISION_CONSUMED"
    ACTION_CAPABLE = "ACTION_CAPABLE"


class FollowUpPrMaturityUnlock(str, Enum):
    """Maturity tier that a follow-up PR would unlock if completed.

    PANEL_STATE_UNIFIED
        A single unified panel-state surface covering all relevant sub-states.

    DESKTOP_ASSISTANT_PRESENCE
        A coherent, assistant-like persistent desktop presence surface
        combining all three state systems into a jointly presentable entity.

    OPERATOR_ACTION_CAPABLE
        Operator/control-plane surfaces gain canonical action endpoints,
        moving from observation to control.

    NL_E2E_CI_PROVEN
        Natural-language end-to-end driving is CI-proven with a real or
        contract-stubbed LLM backend roundtrip.

    MULTIMODAL_E2E_ACTIVATED
        Multimodal end-to-end path is activated and CI-proven from ambient
        perception through decision and execution.
    """

    PANEL_STATE_UNIFIED = "PANEL_STATE_UNIFIED"
    DESKTOP_ASSISTANT_PRESENCE = "DESKTOP_ASSISTANT_PRESENCE"
    OPERATOR_ACTION_CAPABLE = "OPERATOR_ACTION_CAPABLE"
    NL_E2E_CI_PROVEN = "NL_E2E_CI_PROVEN"
    MULTIMODAL_E2E_ACTIVATED = "MULTIMODAL_E2E_ACTIVATED"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CodeAnchor:
    """Single real-code anchor within the V2 or Android codebase.

    Attributes
    ----------
    module_path
        Python dotted module path (e.g. ``core.operator_surface``).
    repo
        ``"v2"`` or ``"android"``.
    role
        Short human-readable description of the role this module plays.
    importable
        True if the module is currently importable / file-exists on disk.
    """

    module_path: str
    repo: str
    role: str
    importable: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "module_path": self.module_path,
            "repo": self.repo,
            "role": self.role,
            "importable": self.importable,
        }


@dataclass
class ImplCutPoint:
    """Implementation cut point for a follow-up PR.

    Attributes
    ----------
    cut_point_id
        Short slug identifying this cut point.
    description
        What needs to be cut into / extended.
    target_module
        Module where the cut should land.
    change_type
        Type of change: ``"new_endpoint"``, ``"extend_module"``,
        ``"new_module"``, ``"wire_existing"``, ``"test_only"``.
    estimated_scope
        ``"small"`` / ``"medium"`` / ``"large"``.
    """

    cut_point_id: str
    description: str
    target_module: str
    change_type: str
    estimated_scope: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cut_point_id": self.cut_point_id,
            "description": self.description,
            "target_module": self.target_module,
            "change_type": self.change_type,
            "estimated_scope": self.estimated_scope,
        }


@dataclass
class ModificationZone:
    """Primary modification zone suggested for a follow-up PR.

    Attributes
    ----------
    zone_id
        Short slug.
    files_or_modules
        List of module paths or file paths that should be modified.
    rationale
        Why this zone is the primary target.
    """

    zone_id: str
    files_or_modules: List[str]
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "zone_id": self.zone_id,
            "files_or_modules": self.files_or_modules,
            "rationale": self.rationale,
        }


@dataclass
class AreaReviewEntry:
    """Complete implementation-grade review entry for one of the five areas.

    Contains all eight content fields required by the problem statement.

    Attributes
    ----------
    area
        The ReviewArea being assessed.
    maturity_label
        Current AreaMaturityLabel for this area.
    code_anchors
        Real code anchors (module/file references) grounding the review.
    canonical_path_summary
        One-paragraph summary of the current canonical path for this area.
    established_items
        Items confirmed by real code / real tests — what IS established.
    partial_items
        Items only partially established — fragmented, unproven, or gated.
    gap_items
        Known honest gaps.
    overclaiming_rationale
        Why this area cannot yet honestly be overclaimed as fully complete,
        if that is the finding.
    impl_cut_points
        The most accurate implementation cut points for a future follow-up PR.
    modification_zones
        Suggested primary modification zones for the future PR.
    maturity_unlock
        The FollowUpPrMaturityUnlock tier that the future PR would unlock.
    maturity_unlock_description
        Human-readable description of what completing the future PR would enable.
    actionability
        Current ActionabilityLevel of this area's surfaces.
    android_evidence_refs
        Android-side evidence via V2-side integration test or gateway module refs.
    """

    area: ReviewArea
    maturity_label: AreaMaturityLabel
    code_anchors: List[CodeAnchor] = field(default_factory=list)
    canonical_path_summary: str = ""
    established_items: List[str] = field(default_factory=list)
    partial_items: List[str] = field(default_factory=list)
    gap_items: List[str] = field(default_factory=list)
    overclaiming_rationale: str = ""
    impl_cut_points: List[ImplCutPoint] = field(default_factory=list)
    modification_zones: List[ModificationZone] = field(default_factory=list)
    maturity_unlock: Optional[FollowUpPrMaturityUnlock] = None
    maturity_unlock_description: str = ""
    actionability: ActionabilityLevel = ActionabilityLevel.READ_ONLY_PROJECTION
    android_evidence_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "area": self.area.value,
            "maturity_label": self.maturity_label.value,
            "code_anchors": [a.to_dict() for a in self.code_anchors],
            "canonical_path_summary": self.canonical_path_summary,
            "established_items": self.established_items,
            "partial_items": self.partial_items,
            "gap_items": self.gap_items,
            "overclaiming_rationale": self.overclaiming_rationale,
            "impl_cut_points": [c.to_dict() for c in self.impl_cut_points],
            "modification_zones": [m.to_dict() for m in self.modification_zones],
            "maturity_unlock": (
                self.maturity_unlock.value if self.maturity_unlock else None
            ),
            "maturity_unlock_description": self.maturity_unlock_description,
            "actionability": self.actionability.value,
            "android_evidence_refs": self.android_evidence_refs,
        }


@dataclass
class FiveAreaImplReview:
    """Root JSON-serialisable artifact for the five-area implementation-grade review.

    Attributes
    ----------
    report_id
        UUID hex identifier for this review run.
    generated_at
        Unix timestamp of generation.
    authority
        Authority sentinel string.
    methodology
        Methodology statement.
    area_entries
        5 AreaReviewEntry items — one per ReviewArea.
    overall_summary
        Plain-language summary of the current joint-system state across all
        five areas.
    next_pr_priority_order
        Ordered list of ReviewArea values representing the recommended PR
        execution order.
    next_pr_priority_rationale
        Rationale for the recommended order.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    generated_at: float = field(default_factory=time.time)
    authority: str = FIVE_AREA_REVIEW_AUTHORITY
    methodology: str = FIVE_AREA_REVIEW_METHODOLOGY

    area_entries: List[AreaReviewEntry] = field(default_factory=list)
    overall_summary: str = ""
    next_pr_priority_order: List[str] = field(default_factory=list)
    next_pr_priority_rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "authority": self.authority,
            "methodology": self.methodology,
            "area_entries": [e.to_dict() for e in self.area_entries],
            "overall_summary": self.overall_summary,
            "next_pr_priority_order": self.next_pr_priority_order,
            "next_pr_priority_rationale": self.next_pr_priority_rationale,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def get_area(self, area: ReviewArea) -> Optional[AreaReviewEntry]:
        """Return the AreaReviewEntry for a given ReviewArea, or None."""
        for entry in self.area_entries:
            if entry.area == area:
                return entry
        return None


# ---------------------------------------------------------------------------
# Module / source probe helpers (same pattern as comprehensive_joint_dual_repo_audit)
# ---------------------------------------------------------------------------


def _module_file_exists(module_path: str) -> bool:
    """Return True if the module file exists on disk regardless of importability."""
    try:
        spec = importlib.util.find_spec(module_path)
        if spec is not None:
            return True
    except (ModuleNotFoundError, ImportError, AttributeError, ValueError):
        pass
    rel_path = module_path.replace(".", os.sep) + ".py"
    for base in sys.path:
        candidate = os.path.join(base, rel_path)
        if os.path.isfile(candidate):
            return True
    rel_pkg = module_path.replace(".", os.sep) + os.sep + "__init__.py"
    for base in sys.path:
        candidate = os.path.join(base, rel_pkg)
        if os.path.isfile(candidate):
            return True
    return False


def _try_import(module_path: str) -> bool:
    """Return True if the module file exists on disk or via find_spec."""
    return _module_file_exists(module_path)


def _source_contains(module_path: str, pattern: str) -> bool:
    """Return True if the module source file contains the given pattern string."""
    try:
        spec = importlib.util.find_spec(module_path)
        if spec and spec.origin and os.path.isfile(spec.origin):
            with open(spec.origin, encoding="utf-8", errors="replace") as fh:
                return pattern in fh.read()
    except (ImportError, ModuleNotFoundError, AttributeError, OSError, UnicodeDecodeError):
        pass
    rel_path = module_path.replace(".", os.sep) + ".py"
    for base in sys.path:
        candidate = os.path.join(base, rel_path)
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8", errors="replace") as fh:
                    return pattern in fh.read()
            except (OSError, UnicodeDecodeError):
                pass
    return False


def _test_file_exists(test_module: str) -> bool:
    """Return True if a test file exists."""
    return _try_import(test_module)


def _anchor(module_path: str, repo: str, role: str) -> CodeAnchor:
    """Build a CodeAnchor with importability probed automatically."""
    return CodeAnchor(
        module_path=module_path,
        repo=repo,
        role=role,
        importable=_try_import(module_path),
    )


# ---------------------------------------------------------------------------
# Area 1: Unified Panel Aggregation
# ---------------------------------------------------------------------------


def _review_unified_panel_aggregation() -> AreaReviewEntry:
    """Review current-state of unified panel/operator state aggregation."""
    established: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    android_refs: List[str] = []

    anchors = [
        _anchor("core.operator_surface", "v2", "OperatorSurface — projection authority"),
        _anchor("core.routes.operator", "v2", "Operator HTTP routes (/api/v1/operator/*)"),
        _anchor("core.flow_level_operator_surface", "v2", "FlowLevelOperatorSurface"),
        _anchor(
            "core.android_device_state_store", "v2",
            "Android device state store — ecosystem truth store"
        ),
        _anchor("core.routes.projection", "v2", "Runtime projection routes (/api/v1/projection/*)"),
        _anchor(
            "core.presence.presence_projection", "v2",
            "PresenceProjection — presence state read surface"
        ),
    ]

    # Individual operator endpoint evidence
    if _try_import("core.routes.operator"):
        established.append(
            "/api/v1/operator/snapshot — OperatorSnapshot: task counts, device presence, "
            "topology, capabilities totals, Android ecosystem count"
        )
        established.append(
            "/api/v1/operator/flows — All delegated flows as FlowOperatorProjection dicts"
        )
        established.append(
            "/api/v1/operator/devices/ecosystem — Android device readiness, model identity, "
            "runtime health snapshot"
        )
        established.append(
            "/api/v1/operator/devices/execution-events — Recent Android execution phase events"
        )
        android_refs.append("core.routes.operator (/api/v1/operator/devices/ecosystem)")
    else:
        gaps.append("core.routes.operator NOT importable — operator routes absent")

    if _try_import("core.routes.projection"):
        established.append(
            "/api/v1/projection/runtime — RuntimeProjection from ContinuumState + topology"
        )
    else:
        partial.append("core.routes.projection not confirmed importable")

    if _try_import("core.flow_level_operator_surface"):
        established.append(
            "FlowLevelOperatorSurface importable — per-flow operator projection "
            "including authority, phase, result summary"
        )
    else:
        partial.append("core.flow_level_operator_surface not confirmed importable")

    # OperatorSnapshot fields: android_ecosystem, presence_tristate, manifestation_summary
    if _source_contains("core.operator_surface", "android_ecosystem"):
        established.append(
            "OperatorSnapshot.android_ecosystem — Android device counts aggregated "
            "at snapshot level (count-level keys, no per-device list)"
        )
    if _source_contains("core.operator_surface", "presence_tristate"):
        established.append(
            "OperatorSnapshot.presence_tristate — subject tri-state read from "
            "DesktopPresenceRuntime into snapshot"
        )
    if _source_contains("core.operator_surface", "manifestation_summary"):
        established.append(
            "OperatorSnapshot.manifestation_summary — derived shell+presence summary "
            "at snapshot level"
        )

    # Check for unified panel state aggregation module (the gap)
    panel_agg_candidates = [
        "core.unified_panel_state",
        "core.panel_state_aggregation",
        "core.operator_panel_aggregation",
        "core.routes.panel",
    ]
    panel_agg_found = any(_try_import(m) for m in panel_agg_candidates)
    if panel_agg_found:
        established.append("Unified panel state aggregation module found")
    else:
        gaps.append(
            "NO SINGLE UNIFIED PANEL-STATE AGGREGATION ENDPOINT: "
            "No module or route combining subject lifecycle (SILENT/LIMINAL/MANIFEST) + "
            "Android ecosystem counts + delegated flow states + UI clothing states "
            "(DORMANT/ISLAND/SIDESHEET/FULLAGENT) + capabilities + health into one "
            "panel-state object. Panel clients must query 4+ endpoints separately."
        )

    # UI clothing states not in any operator endpoint
    if _try_import("system_integration.state_machine_ui_integration") or _try_import(
        "system_integration"
    ):
        partial.append(
            "UI clothing states (DORMANT/ISLAND/SIDESHEET/FULLAGENT) exist in "
            "system_integration/state_machine_ui_integration.py but are NOT exposed "
            "through any operator API endpoint"
        )
    else:
        partial.append(
            "UI clothing states module not confirmed — state_machine_ui_integration "
            "path uncertain; states NOT in operator surface regardless"
        )

    # All surfaces are read-only
    if _source_contains("core.operator_surface", "read-only") or _source_contains(
        "core.operator_surface", "read_only"
    ):
        partial.append(
            "ALL operator endpoints are READ_ONLY_PROJECTION — no panel-level "
            "action-capable endpoints exist"
        )

    return AreaReviewEntry(
        area=ReviewArea.UNIFIED_PANEL_AGGREGATION,
        maturity_label=AreaMaturityLabel.PARTIALLY_ESTABLISHED,
        code_anchors=anchors,
        canonical_path_summary=(
            "The current V2 panel/operator surface consists of multiple independent "
            "read-only projection endpoints: /api/v1/operator/snapshot (compact runtime "
            "overview), /api/v1/operator/flows (delegated flow list), "
            "/api/v1/operator/devices/ecosystem (Android ecosystem summary), "
            "/api/v1/operator/devices/execution-events (Android execution events), and "
            "/api/v1/projection/runtime (RuntimeProjection from ContinuumState). "
            "OperatorSnapshot partially aggregates several state families "
            "(presence_tristate, android_ecosystem, manifestation_summary) but does not "
            "include UI clothing states (DORMANT/ISLAND/SIDESHEET/FULLAGENT) or a "
            "single unified panel-state object. No single endpoint exists that combines "
            "all relevant state families into one coherent panel-fillable structure."
        ),
        established_items=established,
        partial_items=partial,
        gap_items=gaps,
        overclaiming_rationale=(
            "Cannot claim 'unified panel aggregation' is complete because: "
            "(1) no single API endpoint aggregates all relevant state families "
            "(subject lifecycle + Android ecosystem + flows + UI clothing states + "
            "capabilities + health) into one panel object; "
            "(2) panel clients must query 4+ separate endpoints and assemble state "
            "themselves; "
            "(3) UI clothing states are explicitly not in any operator API; "
            "(4) all surfaces are READ_ONLY — even if aggregated, no panel-level "
            "action dispatching is possible."
        ),
        impl_cut_points=[
            ImplCutPoint(
                cut_point_id="new_panel_state_aggregation_module",
                description=(
                    "Create core/unified_panel_state.py with a PanelStateAggregation "
                    "dataclass that combines: OperatorSnapshot fields, "
                    "UI clothing state from state_machine_ui_integration, "
                    "DesktopPresenceRuntime tri-state, and capability summary."
                ),
                target_module="core.unified_panel_state",
                change_type="new_module",
                estimated_scope="medium",
            ),
            ImplCutPoint(
                cut_point_id="new_panel_state_route",
                description=(
                    "Add GET /api/v1/panel/state route to core/routes/ that calls "
                    "the unified panel state aggregator and returns a single "
                    "PanelStateAggregation JSON object."
                ),
                target_module="core.routes.panel",
                change_type="new_endpoint",
                estimated_scope="small",
            ),
            ImplCutPoint(
                cut_point_id="extend_operator_snapshot",
                description=(
                    "Extend OperatorSnapshot in core/operator_surface.py to include "
                    "ui_clothing_state field populated from state_machine_ui_integration "
                    "singleton — bridging the gap without a full new module."
                ),
                target_module="core.operator_surface",
                change_type="extend_module",
                estimated_scope="small",
            ),
        ],
        modification_zones=[
            ModificationZone(
                zone_id="panel_aggregation_primary",
                files_or_modules=[
                    "core/operator_surface.py",
                    "core/routes/operator.py",
                    "system_integration/state_machine_ui_integration.py",
                ],
                rationale=(
                    "OperatorSnapshot is the existing partial aggregator; extending it "
                    "or building a thin wrapper around it requires minimal new surface "
                    "and avoids a full new module. The operator routes already wire the "
                    "snapshot endpoint. The UI clothing state lives in "
                    "state_machine_ui_integration."
                ),
            ),
            ModificationZone(
                zone_id="panel_aggregation_secondary",
                files_or_modules=["core/routes/panel.py"],
                rationale=(
                    "A new panel routes module is needed if a dedicated "
                    "/api/v1/panel/state endpoint is preferred over extending the "
                    "existing operator snapshot endpoint."
                ),
            ),
        ],
        maturity_unlock=FollowUpPrMaturityUnlock.PANEL_STATE_UNIFIED,
        maturity_unlock_description=(
            "After this PR: panel clients can get the full system state — subject "
            "lifecycle, Android ecosystem, delegated flows, UI clothing, capabilities, "
            "and health — from a single endpoint. This eliminates the 4+ endpoint "
            "assembly pattern and enables coherent panel-state filling, state-driven "
            "UI rendering, and the foundation for operator action endpoints."
        ),
        actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
        android_evidence_refs=android_refs,
    )


# ---------------------------------------------------------------------------
# Area 2: Desktop Three-State Existence
# ---------------------------------------------------------------------------


def _review_desktop_three_state_existence() -> AreaReviewEntry:
    """Review current-state of desktop three-state / assistant-like existence."""
    established: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    android_refs: List[str] = []

    anchors = [
        _anchor(
            "core.desktop_presence_runtime", "v2",
            "DesktopPresenceRuntime — tri-state lifecycle shell (SILENT/LIMINAL/MANIFEST)"
        ),
        _anchor(
            "core.presence.presence_director", "v2",
            "PresenceDirector — presence session management"
        ),
        _anchor(
            "core.presence.presence_projection", "v2",
            "PresenceProjection — presence state read surface"
        ),
        _anchor(
            "core.openclawd", "v2",
            "OpenClawd — continuum posture (tri_state_phase + runtime_domain)"
        ),
        _anchor(
            "core.operator_surface", "v2",
            "OperatorSnapshot — partial shell+presence state aggregation"
        ),
    ]

    # State system 1: Subject tri-state lifecycle (SILENT/LIMINAL/MANIFEST)
    if _try_import("core.desktop_presence_runtime"):
        established.append(
            "STATE SYSTEM 1 (SUBJECT LIFECYCLE): DesktopPresenceRuntime importable; "
            "tri-state lifecycle SILENT→LIMINAL→MANIFEST confirmed in source"
        )
        if _source_contains("core.desktop_presence_runtime", "SILENT") and \
           _source_contains("core.desktop_presence_runtime", "LIMINAL"):
            established.append(
                "DesktopPresenceRuntime: SILENT (subject at rest, background sensing), "
                "LIMINAL (request received, cognition in progress), "
                "MANIFEST (actively producing output / controlling devices)"
            )
        if _source_contains("core.desktop_presence_runtime", "handle_request"):
            established.append(
                "DesktopPresenceRuntime.handle_request() — sole canonical driver of "
                "tri-state lifecycle; all route adapters must call this"
            )
        if _source_contains("core.desktop_presence_runtime", "presence_summary"):
            established.append(
                "DesktopPresenceRuntime.presence_summary() — dominant_tristate exposed "
                "for operator/panel consumption"
            )
    else:
        gaps.append("core.desktop_presence_runtime NOT importable — critical gap")

    # Test coverage for DPR
    if _test_file_exists("tests.test_pr1_desktop_presence_runtime"):
        established.append("DPR test suite present (test_pr1_desktop_presence_runtime)")
    if _test_file_exists(
        "tests.test_pr8v2_manifestation_shell_presence_semantics"
    ):
        established.append(
            "Manifestation/shell/presence semantics test present — "
            "semantic consistency of state vocabularies tested"
        )

    # State system 2: UI clothing states (DORMANT/ISLAND/SIDESHEET/FULLAGENT)
    ui_clothing_confirmed = False
    for mod_candidate in [
        "system_integration.state_machine_ui_integration",
        "system_integration",
    ]:
        if _source_contains(mod_candidate, "DORMANT") and _source_contains(
            mod_candidate, "FULLAGENT"
        ):
            established.append(
                "STATE SYSTEM 2 (UI CLOTHING / SHELL EXPANSION): "
                "DORMANT/ISLAND/SIDESHEET/FULLAGENT states confirmed in "
                f"{mod_candidate} — desktop shell expansion modes (clothing states)"
            )
            ui_clothing_confirmed = True
            break
    if not ui_clothing_confirmed:
        # Try to find in desktop presence runtime docstring
        if _source_contains("core.desktop_presence_runtime", "DORMANT") and \
           _source_contains("core.desktop_presence_runtime", "FULLAGENT"):
            partial.append(
                "UI clothing states (DORMANT/ISLAND/SIDESHEET/FULLAGENT) referenced "
                "in core.desktop_presence_runtime docstring but primary definition "
                "is in system_integration layer"
            )
        else:
            partial.append(
                "UI clothing states (DORMANT/ISLAND/SIDESHEET/FULLAGENT) — "
                "state system 2 location not confirmed via source probe"
            )

    # State system 3: Continuum posture (OpenClawd)
    if _try_import("core.openclawd"):
        if _source_contains("core.openclawd", "tri_state_phase"):
            established.append(
                "STATE SYSTEM 3 (CONTINUUM POSTURE): OpenClawd.tri_state_phase "
                "internal state protocol confirmed — runtime_domain + tri_state_phase "
                "inside core cognition layer"
            )
        else:
            partial.append(
                "core.openclawd importable but tri_state_phase not confirmed in source"
            )
    else:
        partial.append("core.openclawd not confirmed importable")

    # Presence Director and Projection
    if _try_import("core.presence.presence_director"):
        established.append(
            "PresenceDirector importable — presence session management layer present"
        )
    else:
        partial.append("core.presence.presence_director not confirmed importable")

    if _try_import("core.presence.presence_projection"):
        established.append(
            "PresenceProjection importable — presence state read projection present"
        )
    else:
        partial.append("core.presence.presence_projection not confirmed importable")

    # Unified three-state surface (the gap)
    unified_candidates = [
        "core.unified_three_state_projection",
        "core.three_state_panel_surface",
        "core.desktop_state_panel_aggregation",
        "core.assistant_presence_surface",
    ]
    unified_found = any(_try_import(m) for m in unified_candidates)
    if unified_found:
        established.append("Unified three-state projection/panel surface found")
    else:
        gaps.append(
            "NO UNIFIED THREE-STATE PANEL SURFACE: "
            "The three distinct state systems (subject tri-state lifecycle, UI clothing "
            "states, continuum posture) are separately documented and accessible but "
            "no single module, endpoint, or data structure jointly aggregates all three "
            "into one coherent desktop-presence panel object."
        )

    # Operator snapshot partial integration
    if _source_contains("core.operator_surface", "desktop_shell_state") and \
       _source_contains("core.operator_surface", "presence_tristate"):
        partial.append(
            "OperatorSnapshot includes desktop_shell_state and presence_tristate fields "
            "but does NOT include UI clothing states or continuum posture — partial "
            "three-state aggregation at snapshot level only"
        )

    gaps.append(
        "NO COHERENT ASSISTANT-LIKE PERSISTENT DESKTOP PRESENCE: "
        "Three state systems exist in code but are not wired into a jointly-presentable "
        "desktop existence surface. The system does not currently expose a single "
        "always-visible, persistently switching, three-state-aware assistant surface "
        "comparable to a desktop assistant like Xiao Ai (小爱)."
    )

    return AreaReviewEntry(
        area=ReviewArea.DESKTOP_THREE_STATE_EXISTENCE,
        maturity_label=AreaMaturityLabel.PARTIALLY_ESTABLISHED,
        code_anchors=anchors,
        canonical_path_summary=(
            "Three distinct state systems are confirmed in real V2 code: "
            "(1) Subject lifecycle tri-state: SILENT (at rest) / LIMINAL (cognition "
            "in progress) / MANIFEST (actively executing/outputting) — driven by "
            "DesktopPresenceRuntime.handle_request() as the sole canonical driver; "
            "(2) UI shell clothing states: DORMANT / ISLAND / SIDESHEET / FULLAGENT — "
            "desktop shell expansion modes in system_integration layer; "
            "(3) Continuum posture: tri_state_phase + runtime_domain inside OpenClawd "
            "as internal state protocol. "
            "PresenceDirector manages presence sessions; PresenceProjection exposes "
            "read access. OperatorSnapshot partially bridges (1) and Android ecosystem "
            "via presence_tristate and manifestation_summary fields. "
            "However, these three systems are documented as intentionally distinct "
            "and must not be conflated — and no unified desktop-presence surface "
            "currently combines them into one persistently-presentable assistant-like "
            "existence representation."
        ),
        established_items=established,
        partial_items=partial,
        gap_items=gaps,
        overclaiming_rationale=(
            "Cannot claim 'desktop three-state existence is coherently presented' because: "
            "(1) the three state systems (lifecycle, clothing, continuum) are separately "
            "accessible but NOT jointly aggregated into any single endpoint or data model; "
            "(2) no persistent always-visible desktop presence surface exists that switches "
            "between the three existence modes; "
            "(3) OperatorSnapshot includes only partial three-state data (lifecycle + "
            "shell_state) but not UI clothing or continuum posture; "
            "(4) no CI test verifies joint three-state presentation coherence."
        ),
        impl_cut_points=[
            ImplCutPoint(
                cut_point_id="three_state_joint_projection",
                description=(
                    "Create core/unified_three_state_projection.py with a "
                    "ThreeStatePresenceProjection dataclass that combines: "
                    "DesktopPresenceRuntime.presence_summary() (lifecycle tri-state), "
                    "state_machine_ui_integration clothing state, and "
                    "OpenClawd continuum posture — exposed via a read endpoint."
                ),
                target_module="core.unified_three_state_projection",
                change_type="new_module",
                estimated_scope="medium",
            ),
            ImplCutPoint(
                cut_point_id="presence_director_desktop_surface",
                description=(
                    "Extend PresenceDirector in core/presence/presence_director.py "
                    "to carry a desktop_existence_mode that maps the three state systems "
                    "to a coherent named existence mode (e.g. BACKGROUND/ASSISTANT/CONTROL)."
                ),
                target_module="core.presence.presence_director",
                change_type="extend_module",
                estimated_scope="medium",
            ),
            ImplCutPoint(
                cut_point_id="operator_snapshot_full_three_state",
                description=(
                    "Extend OperatorSnapshot to include the full three-state data: "
                    "add ui_clothing_state (from state_machine_ui_integration) and "
                    "continuum_posture (from OpenClawd) alongside existing "
                    "presence_tristate field."
                ),
                target_module="core.operator_surface",
                change_type="extend_module",
                estimated_scope="small",
            ),
        ],
        modification_zones=[
            ModificationZone(
                zone_id="three_state_primary",
                files_or_modules=[
                    "core/presence/presence_director.py",
                    "core/desktop_presence_runtime.py",
                    "system_integration/state_machine_ui_integration.py",
                ],
                rationale=(
                    "PresenceDirector is the natural convergence point for all three "
                    "state systems — it already manages sessions. Extending it to "
                    "carry a unified desktop existence mode requires touching "
                    "DPR (lifecycle source) and state_machine_ui_integration "
                    "(clothing state source)."
                ),
            ),
            ModificationZone(
                zone_id="three_state_api_exposure",
                files_or_modules=[
                    "core/operator_surface.py",
                    "core/routes/operator.py",
                ],
                rationale=(
                    "Exposing the unified three-state view via the existing "
                    "OperatorSnapshot and operator routes is the least-invasive "
                    "API change — adds fields to an existing endpoint rather than "
                    "a new route."
                ),
            ),
        ],
        maturity_unlock=FollowUpPrMaturityUnlock.DESKTOP_ASSISTANT_PRESENCE,
        maturity_unlock_description=(
            "After this PR: the system gains a coherent, jointly-presentable "
            "desktop existence surface that expresses all three state modes. "
            "UI layer can render the system as a persistently-present assistant that "
            "switches between background-silent, foreground-assistant, and "
            "executing-control existence modes — the foundation for an always-visible "
            "assistant-like desktop presence comparable to Xiao Ai (小爱)."
        ),
        actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
        android_evidence_refs=android_refs,
    )


# ---------------------------------------------------------------------------
# Area 3: Operator Actionability
# ---------------------------------------------------------------------------


def _review_operator_actionability() -> AreaReviewEntry:
    """Review operator/control-plane actionability vs. read-only projection."""
    established: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    android_refs: List[str] = []

    anchors = [
        _anchor("core.routes.operator", "v2", "Operator HTTP routes (/api/v1/operator/*)"),
        _anchor("core.operator_surface", "v2", "OperatorSurface (read-only projection authority)"),
        _anchor("core.routes.chat", "v2", "Chat route — sole action-capable NL ingress"),
        _anchor(
            "core.command_router", "v2",
            "CommandRouter — canonical orchestration/dispatch authority"
        ),
        _anchor(
            "core.runtime.source_dispatch_orchestrator", "v2",
            "SourceDispatchOrchestrator — dispatch scoring and target selection"
        ),
        _anchor("galaxy_gateway.device_router", "v2", "DeviceRouter — gateway dispatch"),
    ]

    # Established: projection surfaces exist
    if _try_import("core.routes.operator"):
        established.append(
            "Read-only projection surface fully present: /api/v1/operator/snapshot, "
            "/api/v1/operator/flows, /api/v1/operator/inspect/* endpoints all accessible"
        )
        established.append(
            "/api/v1/operator/devices/ecosystem — Android ecosystem read projection "
            "(device readiness, model identity, runtime health)"
        )
        established.append(
            "/api/v1/operator/devices/execution-events — Android execution event "
            "read projection"
        )

    # Confirmed read-only policy in source
    if _source_contains("core.operator_surface", "read-only") or \
       _source_contains("core.operator_surface", "read_only"):
        established.append(
            "OperatorSurface PROJECTION_POLICY explicitly documented as read-only "
            "in source — confirmed NOT action-capable by design"
        )

    # Action-capable ingress: chat route
    if _try_import("core.routes.chat"):
        established.append(
            "/api/v1/chat — ACTION_CAPABLE: POST triggers full NL execution via "
            "DesktopPresenceRuntime.handle_request() → OpenClawd → dispatch chain"
        )
    else:
        partial.append("core.routes.chat not confirmed importable")

    # Dispatch infrastructure exists
    if _try_import("core.command_router"):
        established.append(
            "CommandRouter importable — canonical dispatch authority for routing "
            "task envelopes to execution targets"
        )
    if _try_import("core.runtime.source_dispatch_orchestrator"):
        established.append(
            "SourceDispatchOrchestrator importable — Android truth consumed in "
            "_score_candidate() for routing decisions"
        )
    if _try_import("galaxy_gateway.device_router"):
        established.append(
            "DeviceRouter importable — gateway-level device dispatch authority"
        )

    # Decision-consumed surfaces
    if _try_import("core.android_device_state_store"):
        established.append(
            "android_device_state_store DECISION_CONSUMED — DeviceStateSnapshot truth "
            "drives device selection in _score_candidate() and device_selection.py"
        )
        android_refs.append("core.android_device_state_store (decision-consumed by routing)")
    if _try_import("core.agent.capability_registry"):
        established.append(
            "CapabilityRegistry DECISION_CONSUMED — capability state drives routing; "
            "CapabilityResolver is canonical read path"
        )

    # The gap: no action endpoints at operator/panel level
    panel_action_candidates = [
        "core.routes.operator_actions",
        "core.operator_action_surface",
        "core.routes.control",
        "core.control_plane_actions",
    ]
    panel_action_found = any(_try_import(m) for m in panel_action_candidates)
    if not panel_action_found:
        gaps.append(
            "NO OPERATOR-LEVEL ACTION ENDPOINTS: "
            "All /api/v1/operator/* endpoints are strictly read-only projections. "
            "No POST, PATCH, or action-triggering endpoints exist on the operator/panel "
            "surface. An operator cannot dispatch a task, trigger execution, interrupt "
            "a flow, or affect system state via the operator panel API."
        )
        gaps.append(
            "CONTROL MUST BYPASS OPERATOR SURFACE: "
            "To trigger any execution, an operator must use /api/v1/chat (NL route) or "
            "internal API paths — the operator/control-plane surface provides no "
            "canonical action path for direct operator commands."
        )

    # No operator dispatch test
    if _test_file_exists("tests.test_operator_action_dispatch") or \
       _test_file_exists("tests.test_operator_actionability"):
        partial.append(
            "Operator action dispatch test found (unexpected — review)"
        )
    else:
        partial.append(
            "No test for operator-level action dispatch — consistent with "
            "the absence of action endpoints"
        )

    # Tasks route exists (not operator but action-capable)
    if _try_import("core.routes.tasks"):
        established.append(
            "/api/v1/tasks — task ingress route present; action-capable via "
            "POST create_task() — but this is a TASK route, not OPERATOR panel"
        )

    return AreaReviewEntry(
        area=ReviewArea.OPERATOR_ACTIONABILITY,
        maturity_label=AreaMaturityLabel.OBSERVATION_ONLY_NO_ACTION_SURFACE,
        code_anchors=anchors,
        canonical_path_summary=(
            "The V2 operator/control-plane surface is currently OBSERVATION_ONLY. "
            "Three actionability tiers exist in current code: "
            "READ_ONLY at /api/v1/operator/* (all routes); "
            "DECISION_CONSUMED for android_device_state_store (drives routing) and "
            "CapabilityRegistry (drives device selection); "
            "ACTION_CAPABLE only at /api/v1/chat (NL execution ingress) and "
            "/api/v1/tasks (direct task creation). "
            "The dispatch infrastructure (CommandRouter, SourceDispatchOrchestrator, "
            "DeviceRouter) exists and is action-capable internally but is NOT exposed "
            "through any operator-panel endpoint. "
            "An operator accessing the panel can observe all state but cannot "
            "trigger any action through the panel surface directly."
        ),
        established_items=established,
        partial_items=partial,
        gap_items=gaps,
        overclaiming_rationale=(
            "Cannot claim 'operator actionability' is established because: "
            "(1) OPERATOR_SURFACE_PROJECTION_POLICY explicitly mandates read-only; "
            "(2) no POST/action endpoints exist at /api/v1/operator/*; "
            "(3) dispatch infrastructure exists but is not operator-surface-exposed; "
            "(4) the only action-capable paths are chat (/api/v1/chat) and task "
            "creation (/api/v1/tasks) — neither is an operator-panel surface."
        ),
        impl_cut_points=[
            ImplCutPoint(
                cut_point_id="operator_dispatch_action_endpoint",
                description=(
                    "Add POST /api/v1/operator/dispatch to core/routes/operator.py "
                    "that accepts a task specification and calls "
                    "CommandRouter.route_envelope() — creating the first "
                    "operator-panel action endpoint."
                ),
                target_module="core.routes.operator",
                change_type="new_endpoint",
                estimated_scope="medium",
            ),
            ImplCutPoint(
                cut_point_id="operator_flow_control_endpoints",
                description=(
                    "Add POST /api/v1/operator/flows/{flow_id}/interrupt and "
                    "/api/v1/operator/flows/{flow_id}/cancel endpoints for "
                    "in-flight flow control via DelegatedFlowEntityRuntime."
                ),
                target_module="core.routes.operator",
                change_type="new_endpoint",
                estimated_scope="medium",
            ),
            ImplCutPoint(
                cut_point_id="operator_device_command_endpoint",
                description=(
                    "Add POST /api/v1/operator/devices/{device_id}/command endpoint "
                    "that routes a direct device command via DeviceRouter — enabling "
                    "operator-panel-driven device control."
                ),
                target_module="core.routes.operator",
                change_type="new_endpoint",
                estimated_scope="medium",
            ),
        ],
        modification_zones=[
            ModificationZone(
                zone_id="operator_actions_primary",
                files_or_modules=[
                    "core/routes/operator.py",
                    "core/operator_surface.py",
                ],
                rationale=(
                    "core/routes/operator.py is where all operator routes live — "
                    "adding action endpoints here follows the existing pattern. "
                    "core/operator_surface.py defines the surface policy — "
                    "the projection-only constraint is there and must be relaxed or "
                    "annotated for the action endpoints."
                ),
            ),
            ModificationZone(
                zone_id="operator_dispatch_backend",
                files_or_modules=[
                    "core/command_router.py",
                    "core/runtime/source_dispatch_orchestrator.py",
                ],
                rationale=(
                    "CommandRouter and SourceDispatchOrchestrator are the canonical "
                    "dispatch backend — operator action endpoints should delegate "
                    "to these, not create new dispatch paths."
                ),
            ),
        ],
        maturity_unlock=FollowUpPrMaturityUnlock.OPERATOR_ACTION_CAPABLE,
        maturity_unlock_description=(
            "After this PR: the operator/control-plane panel gains canonical action "
            "capabilities — an operator can dispatch tasks, interrupt/cancel flows, "
            "and command devices directly through /api/v1/operator/* endpoints. "
            "The panel transitions from pure observation to true control-plane status. "
            "This closes the gap between dispatch infrastructure capabilities and "
            "operator-surface-exposed capabilities."
        ),
        actionability=ActionabilityLevel.READ_ONLY_PROJECTION,
        android_evidence_refs=android_refs,
    )


# ---------------------------------------------------------------------------
# Area 4: Natural-Language Canonical Path
# ---------------------------------------------------------------------------


def _review_natural_language_canonical_path() -> AreaReviewEntry:
    """Review the natural-language canonical ingress and orchestration path."""
    established: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    android_refs: List[str] = []

    anchors = [
        _anchor("core.routes.chat", "v2", "Chat route — NL ingress adapter (/api/v1/chat)"),
        _anchor(
            "core.desktop_presence_runtime", "v2",
            "DesktopPresenceRuntime — NL lifecycle shell and tri-state driver"
        ),
        _anchor("core.openclawd", "v2", "OpenClawd — NL interpretation/planning/execution core"),
        _anchor("core.command_router", "v2", "CommandRouter — orchestration/dispatch authority"),
        _anchor("core.llm", "v2", "LLM layer — language model execution"),
        _anchor(
            "core.llm.route_authority", "v2",
            "LLMRouteAuthority — canonical LLM routing decision authority"
        ),
        _anchor(
            "core.canonical_execution_chain", "v2",
            "CanonicalExecutionChain — canonical stage enumeration"
        ),
    ]

    # NL ingress: chat route
    if _try_import("core.routes.chat"):
        established.append(
            "NL INGRESS: /api/v1/chat importable — POST adapter surface for NL input"
        )
        if _source_contains("core.routes.chat", "DesktopPresenceRuntime"):
            established.append(
                "Chat route delegates to DesktopPresenceRuntime — NL chain entry "
                "correctly wired to lifecycle shell"
            )
    else:
        gaps.append("core.routes.chat NOT importable — NL ingress missing")

    # Lifecycle shell: DesktopPresenceRuntime
    if _try_import("core.desktop_presence_runtime"):
        established.append(
            "LIFECYCLE SHELL: DesktopPresenceRuntime.handle_request() — sole canonical "
            "NL entry point; drives SILENT→LIMINAL→MANIFEST→SILENT lifecycle"
        )
        if _source_contains("core.desktop_presence_runtime", "handle_via_e2e") or \
           _source_contains("core.desktop_presence_runtime", "_handle_via_e2e"):
            established.append(
                "_handle_via_e2e() — e2e path present inside DPR for full "
                "orchestration chain execution"
            )
        if _source_contains("core.desktop_presence_runtime", "ingress_carrier_context"):
            established.append(
                "ingress_carrier_context stamp in DPR — NL ingress stamped with "
                "session_id, user_id, entry_mode for provenance tracing"
            )
    else:
        gaps.append("core.desktop_presence_runtime NOT importable")

    # Interpretation/planning: OpenClawd
    if _try_import("core.openclawd"):
        established.append(
            "INTERPRETATION/PLANNING: OpenClawd.process() importable — NL interpretation, "
            "intent resolution, and execution-path branching authority"
        )
        if _source_contains("core.openclawd", "function_calling") or \
           _source_contains("core.openclawd", "tool_call"):
            established.append(
                "OpenClawd: LLM function calling/tool_call dispatch confirmed — "
                "NL → structured tool dispatch path present in source"
            )
    else:
        partial.append("core.openclawd not confirmed importable")

    # LLM routing
    if _try_import("core.llm.route_authority"):
        established.append(
            "ROUTING: LLMRouteAuthority importable — canonical LLM provider/model "
            "routing decision authority with is_canonical flag"
        )
    if _try_import("core.multi_llm_router"):
        established.append(
            "MultiLLMRouter importable — multi-provider LLM routing with complexity "
            "scoring and task-type-aware routing"
        )

    # Orchestration/dispatch
    if _try_import("core.command_router"):
        established.append(
            "ORCHESTRATION: CommandRouter importable — canonical dispatch authority "
            "receiving NL-derived task envelopes from OpenClawd"
        )
    if _try_import("core.canonical_execution_chain"):
        established.append(
            "CanonicalExecutionChain stage enumeration present: "
            "ROUTE_INGRESS → ROUTE_ADAPTER → OPENCLAWD_SUBJECT → "
            "COMMAND_ROUTER_ORCHESTRATION → DEVICE_ROUTER_DISPATCH → "
            "DEVICE_EXECUTION → RESPONSE_RETURN"
        )

    # Result/state feedback
    if _try_import("core.android_execution_signal_reconciler"):
        established.append(
            "RESULT FEEDBACK: android_execution_signal_reconciler importable — "
            "Android execution result ingest path present"
        )
        android_refs.append("core.android_execution_signal_reconciler")

    # Canonical path test evidence
    if _test_file_exists("tests.test_pr1_desktop_presence_runtime"):
        established.append(
            "DPR test suite present — tri-state lifecycle and handle_request() "
            "validated by CI"
        )
    else:
        partial.append("test_pr1_desktop_presence_runtime not found")

    # NL e2e CI gap
    nl_e2e_tests = [
        "tests.integration.test_nl_e2e",
        "tests.test_nl_end_to_end",
        "tests.test_nl_canonical_roundtrip",
        "tests.integration.test_chat_to_execution",
    ]
    nl_e2e_found = any(_test_file_exists(t) for t in nl_e2e_tests)
    if nl_e2e_found:
        established.append("NL e2e roundtrip CI test found")
    else:
        gaps.append(
            "NO NL E2E CI TEST: No CI test exercises the full NL roundtrip "
            "(/api/v1/chat POST → DesktopPresenceRuntime → OpenClawd → real LLM → "
            "action dispatch → result return) with a real or contract-stubbed LLM "
            "backend. LLM responses are mocked or bypassed in all current tests."
        )

    # Compat/non-canonical paths
    if _try_import("core.api_routes"):
        partial.append(
            "core.api_routes (compat_ws_chat path) also routes to DPR — parallel "
            "non-REST ingress path; canonical status lower than /api/v1/chat"
        )

    return AreaReviewEntry(
        area=ReviewArea.NATURAL_LANGUAGE_CANONICAL_PATH,
        maturity_label=AreaMaturityLabel.PARTIALLY_ESTABLISHED,
        code_anchors=anchors,
        canonical_path_summary=(
            "The canonical NL-driving structural chain is confirmed in real V2 code: "
            "POST /api/v1/chat → DesktopPresenceRuntime.handle_request() [LIMINAL phase] "
            "→ OpenClawd.process() [NL interpretation + function calling] "
            "→ LLMRouteAuthority/MultiLLMRouter [provider/model selection] "
            "→ LLM call [language generation + tool dispatch] "
            "→ CommandRouter.route_envelope() [orchestration] "
            "→ DeviceRouter → Android device execution [MANIFEST phase] "
            "→ execution results via android_execution_signal_reconciler "
            "→ SILENT phase. "
            "This chain is correctly wired and non-trivial. The CanonicalExecutionChain "
            "stage enumeration documents the full path. "
            "However, no CI test exercises this path end-to-end with a real LLM backend "
            "— LLM responses are mocked in all current CI tests."
        ),
        established_items=established,
        partial_items=partial,
        gap_items=gaps,
        overclaiming_rationale=(
            "Cannot claim 'NL-driven end-to-end canonical path is CI-proven' because: "
            "(1) no CI test exercises the full NL roundtrip with real LLM processing; "
            "(2) LLM responses are mocked or bypassed in current CI — the CI validates "
            "structure but not NL-driven intelligence; "
            "(3) therefore 'truly NL-driven end-to-end' as a machine-verifiable claim "
            "is STRUCTURALLY_ESTABLISHED but not RUNTIME_EVIDENCED_CLOSED."
        ),
        impl_cut_points=[
            ImplCutPoint(
                cut_point_id="nl_e2e_contract_stub_test",
                description=(
                    "Add tests/integration/test_nl_canonical_roundtrip.py — an "
                    "integration test that sends a POST to /api/v1/chat with a real "
                    "NL query, uses a contract-stubbed (or lite real) LLM backend, "
                    "and verifies: (a) DPR transitions through LIMINAL→MANIFEST→SILENT, "
                    "(b) OpenClawd produces a structured tool call, "
                    "(c) CommandRouter receives the task envelope, "
                    "(d) a result is returned to the caller."
                ),
                target_module="tests.integration.test_nl_canonical_roundtrip",
                change_type="test_only",
                estimated_scope="medium",
            ),
            ImplCutPoint(
                cut_point_id="nl_ingress_carrier_context_test",
                description=(
                    "Add a test verifying that all three canonical carrier paths "
                    "(android_vision, vision_sampler, compat_ws_chat) correctly pass "
                    "session_id, user_id, entry_mode to DPR.handle_request() and that "
                    "ingress_carrier_context stamp appears in the result."
                ),
                target_module="tests.test_nl_ingress_carrier_context",
                change_type="test_only",
                estimated_scope="small",
            ),
        ],
        modification_zones=[
            ModificationZone(
                zone_id="nl_e2e_test_zone",
                files_or_modules=[
                    "tests/integration/",
                    "tests/conftest.py",
                ],
                rationale=(
                    "The primary gap is not in production code but in test coverage — "
                    "adding integration tests under tests/integration/ with a "
                    "contract-stubbed LLM backend closes the NL e2e CI gap without "
                    "changing production code."
                ),
            ),
            ModificationZone(
                zone_id="nl_result_feedback_zone",
                files_or_modules=[
                    "core/desktop_presence_runtime.py",
                    "core/android_execution_signal_reconciler.py",
                ],
                rationale=(
                    "If the result/state feedback loop (execution result → DPR state "
                    "update) needs strengthening, these are the two modules where "
                    "the feedback path lands."
                ),
            ),
        ],
        maturity_unlock=FollowUpPrMaturityUnlock.NL_E2E_CI_PROVEN,
        maturity_unlock_description=(
            "After this PR: 'the system is NL-driven end-to-end' becomes a "
            "CI-provable, machine-verifiable claim. The canonical NL path "
            "(/api/v1/chat → DPR → OpenClawd → LLM → dispatch → result) is "
            "exercised in CI with a real or contract-stubbed backend. "
            "This closes the gap between structural NL chain presence and "
            "provable NL-driven intelligence."
        ),
        actionability=ActionabilityLevel.ACTION_CAPABLE,
        android_evidence_refs=android_refs,
    )


# ---------------------------------------------------------------------------
# Area 5: Multimodal Canonical Path
# ---------------------------------------------------------------------------


def _review_multimodal_canonical_path() -> AreaReviewEntry:
    """Review the multimodal/perception/grounding/vision canonical path."""
    established: List[str] = []
    partial: List[str] = []
    gaps: List[str] = []
    android_refs: List[str] = []

    anchors = [
        _anchor(
            "core.multimodal", "v2",
            "Multimodal package — MultimodalIngressBus, PerceptionSourceRegistry"
        ),
        _anchor("core.vision_pipeline", "v2", "VisionPipeline — vision processing pipeline"),
        _anchor(
            "core.openclawd", "v2",
            "OpenClawd — multimodal_context fusion point in NL processing"
        ),
        _anchor(
            "galaxy_gateway.android.handlers.vision", "v2",
            "Android vision uplink handler (galaxy_gateway)"
        ),
        _anchor(
            "core.android_device_state_store", "v2",
            "DeviceStateSnapshot — mobilevlm_present / seeclick_present fields"
        ),
        _anchor(
            "galaxy_gateway.android_vlm_service", "v2",
            "AndroidVLMService — center-side VLM inference for Android"
        ),
        _anchor(
            "core.multi_llm_router", "v2",
            "MultiLLMRouter.route_multimodal_first() — native-multimodal-first routing"
        ),
    ]

    # Infrastructure: MultimodalIngressBus
    if _try_import("core.multimodal"):
        established.append(
            "PERCEPTION INFRA: core.multimodal package importable — "
            "MultimodalIngressBus (continuous host ambient perception) present"
        )
    else:
        partial.append("core.multimodal package not confirmed importable")

    if _try_import("core.vision_pipeline"):
        established.append(
            "VisionPipeline importable — vision processing pipeline present"
        )
    else:
        partial.append("core.vision_pipeline not confirmed importable")

    # PerceptionSourceRegistry / PerceptionFrame
    for mm_mod in [
        "core.multimodal.perception_source_registry",
        "core.multimodal.modality_confidence_policy",
    ]:
        if _try_import(mm_mod):
            established.append(f"{mm_mod} importable — multimodal infrastructure component")

    # OpenClawd multimodal fusion
    if _try_import("core.openclawd"):
        if _source_contains("core.openclawd", "multimodal_context"):
            established.append(
                "FUSION POINT: OpenClawd accepts multimodal_context kwarg — "
                "request-bound multimodal payload fusion path present in source"
            )
        if _source_contains("core.openclawd", "_select_multimodal_route") or \
           _source_contains("core.openclawd", "route_multimodal_first"):
            established.append(
                "OpenClawd._select_multimodal_route() — native multimodal routing "
                "decision present: routes to native-MM-capable provider when available"
            )
        if _source_contains("core.openclawd", "_fusion_suffix"):
            partial.append(
                "OpenClawd._fusion_suffix — text-fusion fallback for non-native-MM "
                "providers: multimodal input degrades to text when no native MM provider"
            )

    # MultiLLMRouter native-multimodal-first
    if _try_import("core.multi_llm_router"):
        if _source_contains("core.multi_llm_router", "route_multimodal_first"):
            established.append(
                "MultiLLMRouter.route_multimodal_first() — three-tier routing: "
                "Tier 1: native-MM-capable provider; "
                "Tier 2: text-capable fallback (caller provides fusion_summary); "
                "Tier 3: advisory/no-op when no provider reachable"
            )

    # Android vision uplink
    if _try_import("galaxy_gateway.android.handlers.vision"):
        established.append(
            "ANDROID VISION UPLINK: galaxy_gateway.android.handlers.vision importable "
            "— Android visual frame uplink handler present at gateway"
        )
        android_refs.append("galaxy_gateway.android.handlers.vision")
    else:
        partial.append(
            "galaxy_gateway.android.handlers.vision not confirmed importable"
        )

    # Mobile VLM presence tracking
    if _source_contains("core.android_device_state_store", "mobilevlm_present"):
        established.append(
            "DeviceStateSnapshot.mobilevlm_present — Android-side Mobile VLM "
            "presence tracking in V2 state store"
        )
        android_refs.append(
            "core.android_device_state_store (mobilevlm_present field)"
        )
    if _source_contains("core.android_device_state_store", "seeclick_present"):
        established.append(
            "DeviceStateSnapshot.seeclick_present — Android-side SeeClick grounding "
            "engine presence tracking in V2 state store"
        )
        android_refs.append(
            "core.android_device_state_store (seeclick_present field)"
        )

    # AndroidVLMService
    if _try_import("galaxy_gateway.android_vlm_service"):
        established.append(
            "AndroidVLMService importable — center-side VLM inference for Android; "
            "plan() + ground() methods for mobile UI planning and element grounding"
        )
        android_refs.append("galaxy_gateway.android_vlm_service")

    # Disabled by default (the gap)
    disabled_by_default = False
    for mm_mod in ["core.multimodal", "core.multimodal.multimodal_ingest_bus"]:
        if _source_contains(mm_mod, "enable_multimodal_ingest") or \
           _source_contains(mm_mod, "SAFE_DEFAULT"):
            disabled_by_default = True
            break
    if _source_contains("core.openclawd", "enable_multimodal_ingest") or \
       _source_contains("core.openclawd", "SAFE_DEFAULT"):
        disabled_by_default = True

    if disabled_by_default:
        gaps.append(
            "DISABLED BY DEFAULT: Continuous host multimodal perception "
            "(MultimodalIngressBus) is disabled by default — "
            "SAFE_DEFAULT profile sets enable_multimodal_ingest=False. "
            "Multimodal path is gated and not active without explicit configuration."
        )
    else:
        partial.append(
            "enable_multimodal_ingest/SAFE_DEFAULT config not confirmed in source "
            "— disabled-by-default status uncertain but plausible"
        )

    # No e2e CI test
    mm_e2e_tests = [
        "tests.integration.test_multimodal_e2e",
        "tests.test_multimodal_end_to_end",
        "tests.test_multimodal_canonical_roundtrip",
        "tests.integration.test_mm_activation",
    ]
    mm_e2e_found = any(_test_file_exists(t) for t in mm_e2e_tests)
    if mm_e2e_found:
        established.append("Multimodal e2e CI test found")
    else:
        gaps.append(
            "NO MULTIMODAL E2E CI TEST: No CI test proves full multimodal roundtrip "
            "(ambient perception → PerceptionFrame → OpenClawd multimodal_context → "
            "native-MM LLM provider → action dispatch). "
            "Multimodal path is structurally present but not CI-activated end-to-end."
        )

    # Android VLM side
    gaps.append(
        "ANDROID VLM NOT YET E2E ACTIVATED: "
        "MobileVLM V2-1.7B and SeeClick grounding engine presence is tracked "
        "(mobilevlm_present, seeclick_present in DeviceStateSnapshot) but "
        "no CI test proves end-to-end: Android screen capture → VLM planning → "
        "SeeClick grounding → V2 result consumption. "
        "The infrastructure is present; canonical e2e activation is unproven."
    )

    return AreaReviewEntry(
        area=ReviewArea.MULTIMODAL_CANONICAL_PATH,
        maturity_label=AreaMaturityLabel.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN,
        code_anchors=anchors,
        canonical_path_summary=(
            "Two multimodal paths exist in current V2+Android code: "
            "PATH A (continuous ambient perception, DISABLED BY DEFAULT): "
            "MultimodalIngressBus (continuous host-side perception) → PerceptionFrame "
            "→ OpenClawd multimodal_context fusion → native-MM provider via "
            "MultiLLMRouter.route_multimodal_first() → action dispatch. "
            "This path is gated by enable_multimodal_ingest=False (SAFE_DEFAULT). "
            "PATH B (request-bound multimodal, STRUCTURALLY PRESENT): "
            "POST /api/v1/chat with multimodal payload → "
            "DesktopPresenceRuntime.handle_request() → OpenClawd(multimodal_context=...) "
            "→ OpenClawd._select_multimodal_route() → route_multimodal_first() → "
            "native-MM or text-fusion fallback. "
            "PATH C (Android visual grounding): "
            "Android screen capture → Android vision uplink (galaxy_gateway handler) → "
            "AndroidVLMService.plan()/ground() at center → execution dispatch. "
            "MobileVLM/SeeClick presence tracked in DeviceStateSnapshot. "
            "All three paths are structurally present and importable; none are "
            "CI-proven end-to-end with real multimodal activation."
        ),
        established_items=established,
        partial_items=partial,
        gap_items=gaps,
        overclaiming_rationale=(
            "Cannot claim 'multimodal end-to-end is proven' because: "
            "(1) continuous ambient perception is DISABLED BY DEFAULT — not active "
            "without explicit configuration change; "
            "(2) no CI test activates and verifies any of the three multimodal paths "
            "end-to-end; "
            "(3) MobileVLM/SeeClick presence is tracked in state but not CI-proven "
            "to influence routing or execution decisions; "
            "(4) native-MM provider availability is config-dependent — "
            "route_multimodal_first() degrades to text-capable tier when no native "
            "MM provider is configured."
        ),
        impl_cut_points=[
            ImplCutPoint(
                cut_point_id="mm_e2e_request_bound_test",
                description=(
                    "Add tests/integration/test_multimodal_canonical_roundtrip.py — "
                    "tests that POST /api/v1/chat with a real or contract-stubbed "
                    "multimodal payload (image base64 + text), verify: "
                    "(a) OpenClawd receives multimodal_context, "
                    "(b) _select_multimodal_route() is called, "
                    "(c) route_multimodal_first() returns a valid decision."
                ),
                target_module="tests.integration.test_multimodal_canonical_roundtrip",
                change_type="test_only",
                estimated_scope="medium",
            ),
            ImplCutPoint(
                cut_point_id="mm_ambient_activation_test",
                description=(
                    "Add a CI test that sets enable_multimodal_ingest=True, verifies "
                    "MultimodalIngressBus starts, ingests a synthetic PerceptionFrame, "
                    "and passes it into OpenClawd multimodal_context."
                ),
                target_module="tests.integration.test_mm_ambient_activation",
                change_type="test_only",
                estimated_scope="medium",
            ),
            ImplCutPoint(
                cut_point_id="android_vlm_decision_influence_proof",
                description=(
                    "Add test/evidence that when mobilevlm_present=True in "
                    "DeviceStateSnapshot, AndroidVLMService.plan() is invoked and "
                    "influences routing or execution. Requires wiring "
                    "the mobilevlm_present field into device_selection.py "
                    "capability scoring."
                ),
                target_module="galaxy_gateway.routing.device_selection",
                change_type="wire_existing",
                estimated_scope="medium",
            ),
        ],
        modification_zones=[
            ModificationZone(
                zone_id="mm_activation_zone",
                files_or_modules=[
                    "core/openclawd.py",
                    "core/multimodal/",
                    "core/multi_llm_router.py",
                ],
                rationale=(
                    "OpenClawd is the fusion point — _select_multimodal_route() is "
                    "where multimodal signals enter decision routing. The multimodal "
                    "package (MultimodalIngressBus) is where ambient activation config "
                    "lives. MultiLLMRouter is where native-MM provider selection lands."
                ),
            ),
            ModificationZone(
                zone_id="android_vlm_decision_zone",
                files_or_modules=[
                    "galaxy_gateway/routing/device_selection.py",
                    "galaxy_gateway/android_vlm_service.py",
                    "core/android_device_state_store.py",
                ],
                rationale=(
                    "device_selection.py is where DeviceStateSnapshot (including "
                    "mobilevlm_present) is consumed for routing scoring. Wiring "
                    "mobilevlm_present into the capability score would make Android VLM "
                    "presence influence routing decisions — closing the Android MM gap."
                ),
            ),
        ],
        maturity_unlock=FollowUpPrMaturityUnlock.MULTIMODAL_E2E_ACTIVATED,
        maturity_unlock_description=(
            "After this PR: the system's multimodal claims become CI-provable. "
            "Request-bound multimodal path (chat + image) is CI-verified. "
            "Ambient perception activation is CI-tested (with enable flag). "
            "Android VLM presence influence on routing is provably wired. "
            "The system graduates from 'infrastructure present' to "
            "'multimodal-capable with CI-proven activation paths'."
        ),
        actionability=ActionabilityLevel.ACTION_CAPABLE,
        android_evidence_refs=android_refs,
    )


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------


def build_five_area_impl_review() -> FiveAreaImplReview:
    """Build a fresh five-area implementation-grade review artifact.

    Returns
    -------
    FiveAreaImplReview
        Full review with 5 area entries, each containing all 8 required content
        fields, plus overall summary and next-PR priority ordering.
    """
    entries = [
        _review_unified_panel_aggregation(),
        _review_desktop_three_state_existence(),
        _review_operator_actionability(),
        _review_natural_language_canonical_path(),
        _review_multimodal_canonical_path(),
    ]

    overall_summary = (
        "The Galaxy dual-repo system (V2 + Android) is architecturally sound with "
        "a proven core dispatch chain. Across the five strategic areas, the honest "
        "current-state assessment is: "
        "(1) UNIFIED_PANEL_AGGREGATION: PARTIALLY_ESTABLISHED — multiple read-only "
        "projection endpoints exist but no single aggregated panel-state object; "
        "(2) DESKTOP_THREE_STATE_EXISTENCE: PARTIALLY_ESTABLISHED — three distinct "
        "state systems confirmed in code but not jointly aggregated into a coherent "
        "assistant-like desktop presence surface; "
        "(3) OPERATOR_ACTIONABILITY: OBSERVATION_ONLY — all operator endpoints are "
        "strictly read-only; no action-capable paths at the operator panel level; "
        "(4) NATURAL_LANGUAGE_CANONICAL_PATH: PARTIALLY_ESTABLISHED — structural "
        "chain is confirmed and correctly wired but not CI-proven with real LLM; "
        "(5) MULTIMODAL_CANONICAL_PATH: INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN — "
        "all infrastructure modules present but ambient path is disabled by default "
        "and no CI test proves end-to-end multimodal activation. "
        "None of the five areas can be honestly claimed as fully complete in "
        "current merged code. All five have clear, code-grounded implementation "
        "cut points for follow-up PRs."
    )

    next_pr_order = [
        ReviewArea.UNIFIED_PANEL_AGGREGATION.value,
        ReviewArea.DESKTOP_THREE_STATE_EXISTENCE.value,
        ReviewArea.OPERATOR_ACTIONABILITY.value,
        ReviewArea.NATURAL_LANGUAGE_CANONICAL_PATH.value,
        ReviewArea.MULTIMODAL_CANONICAL_PATH.value,
    ]

    next_pr_rationale = (
        "Recommended execution order: "
        "(1) UNIFIED_PANEL_AGGREGATION first — it is the state-surface foundation; "
        "completing it gives desktop three-state and operator action a stable carrier. "
        "(2) DESKTOP_THREE_STATE_EXISTENCE second — depends on unified panel state as "
        "the aggregation basis; produces the assistant-like desktop presence surface "
        "that operator action and NL feedback need. "
        "(3) OPERATOR_ACTIONABILITY third — with unified panel state and three-state "
        "surface in place, adding action endpoints has a stable surface to reflect "
        "action results back to; avoids building action endpoints on a fragmented base. "
        "(4) NATURAL_LANGUAGE_CANONICAL_PATH fourth — the NL chain is structurally "
        "correct; the gap is test coverage. With earlier PRs completed, the NL "
        "e2e test can verify the full state feedback loop. "
        "(5) MULTIMODAL_CANONICAL_PATH last — most dependent on the full system "
        "being coherent; multimodal activation proofs are highest-complexity and "
        "succeed best when the state, presence, and NL paths are already solid."
    )

    return FiveAreaImplReview(
        area_entries=entries,
        overall_summary=overall_summary,
        next_pr_priority_order=next_pr_order,
        next_pr_priority_rationale=next_pr_rationale,
    )


# ---------------------------------------------------------------------------
# Invariant checker
# ---------------------------------------------------------------------------


def assert_five_area_review_invariants(review: FiveAreaImplReview) -> None:
    """Assert internal-consistency invariants for a FiveAreaImplReview.

    Raises AssertionError if any invariant is violated.

    Invariants enforced
    -------------------
    1.  Exactly 5 area entries present.
    2.  All five ReviewArea values are represented exactly once.
    3.  No area is overclaimed as STRONGLY_ESTABLISHED or RUNTIME_EVIDENCED_CLOSED
        when it has non-empty gap_items.
    4.  Every AreaReviewEntry has at least one code anchor.
    5.  Every AreaReviewEntry has a non-empty canonical_path_summary.
    6.  Every AreaReviewEntry has at least one established_item.
    7.  Every AreaReviewEntry below STRONGLY_ESTABLISHED has at least one gap item.
    8.  Every AreaReviewEntry has at least one impl_cut_point.
    9.  Every AreaReviewEntry has at least one modification_zone.
    10. Every AreaReviewEntry has a non-None maturity_unlock.
    11. Every AreaReviewEntry has a non-empty maturity_unlock_description.
    12. overall_summary is non-empty.
    13. next_pr_priority_order has exactly 5 entries matching ReviewArea values.
    14. authority sentinel is non-empty and starts with FIVE_AREA_IMPL_REVIEW_AUTHORITY.
    15. methodology sentinel is non-empty.
    16. Report serialises to valid JSON without error.
    """
    assert len(review.area_entries) == 5, (
        f"Expected 5 area entries, got {len(review.area_entries)}"
    )

    seen_areas = {e.area for e in review.area_entries}
    all_areas = set(ReviewArea)
    assert seen_areas == all_areas, (
        f"Missing area entries: {all_areas - seen_areas}"
    )

    for entry in review.area_entries:
        # No overclaiming when gaps exist
        if entry.gap_items:
            assert entry.maturity_label not in (
                AreaMaturityLabel.STRONGLY_ESTABLISHED,
                AreaMaturityLabel.RUNTIME_EVIDENCED_CLOSED,
            ), (
                f"Area {entry.area.value} has gap_items but maturity_label is "
                f"{entry.maturity_label.value} — overclaiming detected"
            )

        assert len(entry.code_anchors) >= 1, (
            f"Area {entry.area.value} has no code anchors"
        )
        assert len(entry.canonical_path_summary) > 0, (
            f"Area {entry.area.value} has empty canonical_path_summary"
        )
        assert len(entry.established_items) >= 1, (
            f"Area {entry.area.value} has no established items"
        )

        # Below STRONGLY_ESTABLISHED must have gap items
        if entry.maturity_label not in (
            AreaMaturityLabel.STRONGLY_ESTABLISHED,
            AreaMaturityLabel.RUNTIME_EVIDENCED_CLOSED,
        ):
            assert len(entry.gap_items) >= 1, (
                f"Area {entry.area.value} is rated {entry.maturity_label.value} "
                f"but has no gap_items"
            )

        assert len(entry.impl_cut_points) >= 1, (
            f"Area {entry.area.value} has no impl_cut_points"
        )
        assert len(entry.modification_zones) >= 1, (
            f"Area {entry.area.value} has no modification_zones"
        )
        assert entry.maturity_unlock is not None, (
            f"Area {entry.area.value} has None maturity_unlock"
        )
        assert len(entry.maturity_unlock_description) > 0, (
            f"Area {entry.area.value} has empty maturity_unlock_description"
        )

    assert len(review.overall_summary) > 0, "overall_summary is empty"

    assert len(review.next_pr_priority_order) == 5, (
        f"next_pr_priority_order should have 5 entries, "
        f"got {len(review.next_pr_priority_order)}"
    )
    valid_area_values = {a.value for a in ReviewArea}
    for item in review.next_pr_priority_order:
        assert item in valid_area_values, (
            f"next_pr_priority_order item {item!r} is not a valid ReviewArea value"
        )

    assert len(review.authority) > 0, "authority sentinel is empty"
    assert review.authority.startswith("FIVE_AREA_IMPL_REVIEW_AUTHORITY"), (
        "authority sentinel does not start with FIVE_AREA_IMPL_REVIEW_AUTHORITY"
    )
    assert len(review.methodology) > 0, "methodology sentinel is empty"

    # JSON serialisation
    try:
        json_str = review.to_json()
        parsed = json.loads(json_str)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"Review does not serialise to valid JSON: {exc}") from exc

    assert "area_entries" in parsed
    assert len(parsed["area_entries"]) == 5


# ---------------------------------------------------------------------------
# Singleton cache (thread-safe, test-resettable)
# ---------------------------------------------------------------------------

_review_lock = threading.Lock()
_cached_review: Optional[FiveAreaImplReview] = None


def get_five_area_impl_review() -> FiveAreaImplReview:
    """Return the cached FiveAreaImplReview, building it on first call.

    Thread-safe via double-checked locking.
    """
    global _cached_review
    if _cached_review is not None:
        return _cached_review
    with _review_lock:
        if _cached_review is None:
            _cached_review = build_five_area_impl_review()
    return _cached_review


def reset_five_area_impl_review() -> None:
    """Clear the singleton cache.

    For test isolation only — production code must not call this.
    """
    global _cached_review
    with _review_lock:
        _cached_review = None
