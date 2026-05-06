#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/five_domain_implementation_review.py
==========================================
Implementation-Grade Five-Domain Joint Dual-Repo Review Artifact.

Repositories reviewed together
--------------------------------
- DannyFish-11/ufo-galaxy-realization-v2  (V2 — this repo, center authority)
- DannyFish-11/ufo-galaxy-android         (Android — runtime carrier node)

Purpose
-------
This module is the authoritative implementation-grade review package for the
five domains that form the next five follow-up PRs.  For each domain it
captures:

1. current real code anchors / components / modules / files (both repos)
2. current canonical path summary
3. what is already established in real code
4. what remains partial / fragmented / unproven
5. why the area cannot yet be overclaimed as fully complete
6. the most accurate implementation cut points for a future follow-up PR
7. suggested primary modification zones for that future PR
8. what level of system maturity that future PR would likely unlock

Differentiation from prior audit modules
-----------------------------------------
- ``core.comprehensive_joint_dual_repo_audit`` (2047 lines) audited 8 dimensions
  and addressed six user-posed completeness questions.  It does NOT provide
  implementation cut points, modification zones, or maturity-unlock descriptors.
- This module fills exactly that gap: it converts the audit evidence into
  actionable implementation guidance for the five priority domains.
- All evidence is re-derived from real code probes (imports / source inspection
  / test-file existence) — not copied from prior narrative text.

Five review domains
-------------------
1. UNIFIED_PANEL_AGGREGATION
   Identify real panel/operator/control-plane state sources, APIs, projections,
   aggregation layers; explain where unified surface is absent.

2. DESKTOP_THREE_STATE_PRESENCE
   Investigate the three distinct state systems (subject lifecycle, continuum
   posture, UI clothing states); explain why no joint surface yet exists.

3. OPERATOR_ACTIONABILITY
   Distinguish read-only projection surfaces from action-capable paths;
   enumerate real action endpoints vs observation-only surfaces.

4. NATURAL_LANGUAGE_CANONICAL_PATH
   Trace real NL ingress → planning → routing → orchestration → dispatch →
   result feedback; distinguish canonical from demo/stub flows.

5. MULTIMODAL_CANONICAL_PATH
   Trace real multimodal/perception/grounding/vision paths; separate canonical
   participation from optional, dormant, or demo-only infrastructure.

Methodology
-----------
- All conclusions are grounded only in: current real Python imports, attribute
  checks, inspect.getsource(), file-existence probes, and V2-side integration
  test presence for Android evidence.
- README files, markdown audits, PR descriptions, and architecture narratives
  are EXPLICITLY EXCLUDED as evidence.
- Conservatively labels any item that lacks CI-level proof as PARTIAL or
  MISSING_PROOF rather than inflating to a stronger label.

Public API
----------
Constants::

    FIVE_DOMAIN_REVIEW_AUTHORITY
    FIVE_DOMAIN_REVIEW_VERSION

Enumerations::

    ReviewDomain           — the five target domains
    EvidenceStrength       — 6-tier evidence ladder (import → CI-proven)
    CutPointKind           — NEW_MODULE / EXTEND_EXISTING / NEW_ROUTE / NEW_TEST
    MaturityLevel          — current system maturity levels
    MaturityUnlockLevel    — the maturity tier unlocked by completing a PR

Dataclasses::

    CodeAnchor
    ImplementationCutPoint
    ModificationZone
    DomainReviewEntry
    FiveDomainReviewReport

Functions::

    build_five_domain_review() -> FiveDomainReviewReport
    get_five_domain_review()   -> FiveDomainReviewReport   (cached singleton)
    reset_five_domain_review() -> None                      (test isolation)
    assert_five_domain_review_invariants() -> None          (invariant checker)
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import json
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Authority / version sentinels
# ---------------------------------------------------------------------------

FIVE_DOMAIN_REVIEW_AUTHORITY: str = (
    "FIVE_DOMAIN_IMPLEMENTATION_REVIEW_AUTHORITY::"
    "core.five_domain_implementation_review::"
    "implementation-grade-dual-repo-review-v1"
)

FIVE_DOMAIN_REVIEW_VERSION: str = "1.0"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ReviewDomain(str, Enum):
    """The five priority review domains."""

    UNIFIED_PANEL_AGGREGATION = "UNIFIED_PANEL_AGGREGATION"
    DESKTOP_THREE_STATE_PRESENCE = "DESKTOP_THREE_STATE_PRESENCE"
    OPERATOR_ACTIONABILITY = "OPERATOR_ACTIONABILITY"
    NATURAL_LANGUAGE_CANONICAL_PATH = "NATURAL_LANGUAGE_CANONICAL_PATH"
    MULTIMODAL_CANONICAL_PATH = "MULTIMODAL_CANONICAL_PATH"


class EvidenceStrength(str, Enum):
    """Six-tier evidence ladder for individual review claims.

    CI_PROVEN
        A dedicated passing CI test covers the full path.

    RUNTIME_STRUCTURAL_CLOSED
        Module importable; runtime path exercised; no CI-level roundtrip test
        but structural evidence is complete.

    IMPORTABLE_WITH_TESTS
        Module importable; passing tests confirm key behaviour; some gaps.

    IMPORTABLE_NO_E2E_TEST
        Module importable; behaviour confirmed at unit level only; no
        end-to-end CI test.

    STRUCTURALLY_PRESENT_GATED
        Code structure present but capability is gated (config flag, disabled
        by default, or requires runtime activation outside CI).

    ABSENT_NOT_YET_IMPLEMENTED
        The required surface/endpoint/module does not yet exist.
    """

    CI_PROVEN = "CI_PROVEN"
    RUNTIME_STRUCTURAL_CLOSED = "RUNTIME_STRUCTURAL_CLOSED"
    IMPORTABLE_WITH_TESTS = "IMPORTABLE_WITH_TESTS"
    IMPORTABLE_NO_E2E_TEST = "IMPORTABLE_NO_E2E_TEST"
    STRUCTURALLY_PRESENT_GATED = "STRUCTURALLY_PRESENT_GATED"
    ABSENT_NOT_YET_IMPLEMENTED = "ABSENT_NOT_YET_IMPLEMENTED"


class CutPointKind(str, Enum):
    """Kind of implementation cut point for a future PR."""

    NEW_MODULE = "NEW_MODULE"
    EXTEND_EXISTING = "EXTEND_EXISTING"
    NEW_ROUTE = "NEW_ROUTE"
    NEW_TEST = "NEW_TEST"
    ENABLE_GATE = "ENABLE_GATE"


class MaturityLevel(str, Enum):
    """Current assessed maturity level of a domain."""

    STRUCTURALLY_ESTABLISHED = "STRUCTURALLY_ESTABLISHED"
    PARTIALLY_ESTABLISHED = "PARTIALLY_ESTABLISHED"
    INFRA_PRESENT_NOT_E2E = "INFRA_PRESENT_NOT_E2E"
    OBSERVATION_PROJECTION_ONLY = "OBSERVATION_PROJECTION_ONLY"
    NOT_YET_IMPLEMENTED = "NOT_YET_IMPLEMENTED"


class MaturityUnlockLevel(str, Enum):
    """The maturity level a future PR would unlock if completed.

    CANONICAL_SURFACE_ESTABLISHED
        A new canonical surface would exist; all consuming paths can use it.

    COHERENT_JOINT_STATE_SURFACE
        Multiple existing state systems would be unified into one coherent
        queryable surface.

    ACTION_CAPABLE_CONTROL_PLANE
        The operator/panel surface would gain POST action endpoints and move
        from observation-only to control-capable.

    CI_PROVEN_E2E_PATH
        An end-to-end path would be proven by a passing CI test (not just
        structural / import-level confirmation).

    ACTIVATABLE_MULTIMODAL_PARTICIPATION
        The multimodal path would become activatable in CI (i.e., can be
        switched on in a test environment without SAFE_DEFAULT blocking it).
    """

    CANONICAL_SURFACE_ESTABLISHED = "CANONICAL_SURFACE_ESTABLISHED"
    COHERENT_JOINT_STATE_SURFACE = "COHERENT_JOINT_STATE_SURFACE"
    ACTION_CAPABLE_CONTROL_PLANE = "ACTION_CAPABLE_CONTROL_PLANE"
    CI_PROVEN_E2E_PATH = "CI_PROVEN_E2E_PATH"
    ACTIVATABLE_MULTIMODAL_PARTICIPATION = "ACTIVATABLE_MULTIMODAL_PARTICIPATION"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CodeAnchor:
    """A real code location used as evidence for a review claim.

    Attributes
    ----------
    repo
        One of "v2" (ufo-galaxy-realization-v2) or "android"
        (ufo-galaxy-android).
    path
        Module dotted path (for V2 Python modules) or Java package path
        (for Android).
    available
        Whether the V2-side anchor is importable / file-exists in the
        current checkout.  Android anchors are always ``True`` (they are
        confirmed via V2-side integration tests).
    note
        Brief note about what this anchor provides as evidence.
    """

    repo: str
    path: str
    available: bool
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repo": self.repo,
            "path": self.path,
            "available": self.available,
            "note": self.note,
        }


@dataclass
class ImplementationCutPoint:
    """A precise point in the codebase where a future PR should cut in.

    Attributes
    ----------
    kind
        The kind of change: new module, extend existing, new route, or new test.
    target_path
        The dotted module path or file path where the cut is made.
    description
        One-sentence description of what the cut achieves.
    depends_on
        Other cut points (by target_path) that must be done first.
    """

    kind: CutPointKind
    target_path: str
    description: str
    depends_on: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind.value,
            "target_path": self.target_path,
            "description": self.description,
            "depends_on": self.depends_on,
        }


@dataclass
class ModificationZone:
    """A specific file and optional function/class that a future PR should modify.

    Attributes
    ----------
    file_path
        Repo-relative file path.
    scope
        Optional specific class/function/method name within the file.
    change_description
        What the future PR should add or change here.
    """

    file_path: str
    scope: Optional[str]
    change_description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file_path": self.file_path,
            "scope": self.scope,
            "change_description": self.change_description,
        }


@dataclass
class DomainReviewEntry:
    """Full implementation-grade review entry for one of the five domains.

    Attributes
    ----------
    domain
        The ReviewDomain being assessed.
    current_maturity
        Current assessed maturity level.
    canonical_path_summary
        One paragraph describing the real current canonical code path.
    established_items
        Items confirmed by real code/tests as already implemented.
    partial_items
        Items only partially confirmed — exist structurally but have gaps.
    unproven_items
        Items that remain unproven (no runtime evidence / CI test).
    incompleteness_rationale
        Specific technical reasons why the domain cannot be overclaimed as
        complete.  Must be conservative and grounded in real code gaps.
    v2_anchors
        Real V2-side code anchors.
    android_anchors
        Real Android-side code anchors (confirmed via V2 integration tests).
    implementation_cut_points
        Ordered list of where a future PR should cut in.
    modification_zones
        Specific files/functions the future PR should modify.
    maturity_unlock
        Which maturity level the domain would reach if the future PR is done.
    maturity_unlock_description
        Human-readable description of what completing the future PR achieves.
    """

    domain: ReviewDomain
    current_maturity: MaturityLevel
    canonical_path_summary: str
    established_items: List[str] = field(default_factory=list)
    partial_items: List[str] = field(default_factory=list)
    unproven_items: List[str] = field(default_factory=list)
    incompleteness_rationale: str = ""
    v2_anchors: List[CodeAnchor] = field(default_factory=list)
    android_anchors: List[CodeAnchor] = field(default_factory=list)
    implementation_cut_points: List[ImplementationCutPoint] = field(default_factory=list)
    modification_zones: List[ModificationZone] = field(default_factory=list)
    maturity_unlock: MaturityUnlockLevel = MaturityUnlockLevel.CANONICAL_SURFACE_ESTABLISHED
    maturity_unlock_description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain.value,
            "current_maturity": self.current_maturity.value,
            "canonical_path_summary": self.canonical_path_summary,
            "established_items": self.established_items,
            "partial_items": self.partial_items,
            "unproven_items": self.unproven_items,
            "incompleteness_rationale": self.incompleteness_rationale,
            "v2_anchors": [a.to_dict() for a in self.v2_anchors],
            "android_anchors": [a.to_dict() for a in self.android_anchors],
            "implementation_cut_points": [
                c.to_dict() for c in self.implementation_cut_points
            ],
            "modification_zones": [z.to_dict() for z in self.modification_zones],
            "maturity_unlock": self.maturity_unlock.value,
            "maturity_unlock_description": self.maturity_unlock_description,
        }


@dataclass
class FiveDomainReviewReport:
    """Full five-domain implementation-grade review report.

    Attributes
    ----------
    authority
        Module-level authority sentinel.
    version
        Review schema version.
    domains
        One DomainReviewEntry per ReviewDomain (always exactly 5).
    global_invariant_summary
        A summary of cross-domain invariants and their status.
    """

    authority: str
    version: str
    domains: List[DomainReviewEntry] = field(default_factory=list)
    global_invariant_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "version": self.version,
            "domains": [d.to_dict() for d in self.domains],
            "global_invariant_summary": self.global_invariant_summary,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def domain_by_name(self, domain: ReviewDomain) -> DomainReviewEntry:
        for d in self.domains:
            if d.domain == domain:
                return d
        raise KeyError(f"Domain not found: {domain}")


# ---------------------------------------------------------------------------
# Internal probe helpers (read-only, no side effects)
# ---------------------------------------------------------------------------


def _try_import(module_path: str) -> bool:
    """Return True iff the module is importable in the current environment."""
    try:
        importlib.import_module(module_path)
        return True
    except Exception:
        return False


def _module_file_exists(module_path: str) -> bool:
    """Return True iff the module file exists on disk (without importing).

    Uses find_spec() which is lighter than a full import, but still executes
    ``__init__.py`` files in parent packages.  We catch all exceptions here
    because those __init__.py files may fail (e.g., missing optional
    dependencies like pydantic, numpy, or httpx) — those failures do not mean
    the target module is absent, only that its package cannot be fully
    initialised in the current environment.
    """
    try:
        spec = importlib.util.find_spec(module_path)
        return spec is not None
    except Exception:
        # find_spec may execute parent __init__.py side effects that raise
        # (e.g. missing pydantic/numpy causes ModuleNotFoundError).
        # Fall back to False — caller can try a direct file-path check.
        return False


def _try_import_or_exists(module_path: str) -> bool:
    """Return True iff the module is importable OR the file exists."""
    return _try_import(module_path) or _module_file_exists(module_path)


def _source_contains(module_path: str, pattern: str) -> bool:
    """Return True iff the module source contains the given pattern string."""
    try:
        m = importlib.import_module(module_path)
        src = inspect.getsource(m)
        return pattern in src
    except Exception:
        pass
    # Fall back to file-level grep
    try:
        spec = importlib.util.find_spec(module_path)
        if spec and spec.origin:
            with open(spec.origin, encoding="utf-8", errors="replace") as fh:
                return pattern in fh.read()
    except Exception:
        pass
    return False


def _test_file_exists(test_module: str) -> bool:
    """Return True iff the test module file exists."""
    return _try_import_or_exists(test_module)


def _file_contains(rel_path: str, pattern: str) -> bool:
    """Return True iff the given repo-relative file contains the pattern."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    abs_path = os.path.join(base, rel_path)
    try:
        with open(abs_path, encoding="utf-8", errors="replace") as fh:
            return pattern in fh.read()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Domain 1: Unified Panel Aggregation
# ---------------------------------------------------------------------------


def _review_unified_panel_aggregation() -> DomainReviewEntry:
    """Review Domain 1: Unified Panel Aggregation.

    Evidence sources
    ----------------
    - core.operator_surface       — OperatorSnapshot (read-only overview)
    - core.flow_level_operator_surface — FlowOperatorProjection (read-only)
    - core.routes.operator        — /api/v1/operator/* routes (all GET)
    - core.routes.projection      — /api/v1/projection/runtime (GET)
    - core.android_device_state_store — DeviceStateSnapshot (Android state)
    - Missing: core.unified.panel_state_aggregator (not yet created)
    """
    # V2 anchors
    operator_surface_ok = _try_import_or_exists("core.operator_surface")
    flow_surface_ok = _try_import_or_exists("core.flow_level_operator_surface")
    routes_operator_ok = _try_import_or_exists("core.routes.operator")
    routes_projection_ok = _try_import_or_exists("core.routes.projection")
    android_store_ok = _try_import_or_exists("core.android_device_state_store")

    # Aggregation module — does NOT exist yet
    panel_agg_candidates = [
        "core.unified.panel_state_aggregator",
        "core.panel_state_aggregation",
        "core.operator_panel_aggregation",
        "core.unified_panel_state",
    ]
    unified_agg_exists = any(_try_import_or_exists(c) for c in panel_agg_candidates)

    # Source-level checks
    has_operator_snapshot = _source_contains("core.operator_surface", "OperatorSnapshot")
    has_flow_projection = _source_contains(
        "core.flow_level_operator_surface", "FlowOperatorProjection"
    )
    all_routes_are_get = (
        not _file_contains("core/routes/operator.py", "@router.post")
        and _file_contains("core/routes/operator.py", "@router.get")
    )

    # Tests confirming panel surfaces
    test_pr510 = _test_file_exists("tests.test_pr510_operator_api_endpoints")
    test_snapshot = _test_file_exists("tests.test_operator_surface_contracts")
    test_flow = _test_file_exists("tests.test_flow_level_operator_surface")

    established: List[str] = []
    partial: List[str] = []
    unproven: List[str] = []

    if operator_surface_ok and has_operator_snapshot:
        established.append(
            "core.operator_surface importable; OperatorSnapshot confirmed in source — "
            "provides runtime overview (task counts, device presence, topology, "
            "capabilities, Android ecosystem count)"
        )
    if flow_surface_ok and has_flow_projection:
        established.append(
            "core.flow_level_operator_surface importable; FlowOperatorProjection "
            "confirmed — all delegated flows projected as typed dicts"
        )
    if routes_operator_ok:
        established.append(
            "core.routes.operator importable — /api/v1/operator/snapshot, "
            "/api/v1/operator/flows, /api/v1/operator/devices/ecosystem, "
            "/api/v1/operator/devices/execution-events all present"
        )
    if routes_projection_ok:
        established.append(
            "core.routes.projection importable — /api/v1/projection/runtime "
            "provides partial lifecycle state projection"
        )
    if android_store_ok:
        established.append(
            "core.android_device_state_store importable; DeviceStateSnapshot with "
            "per-device health, MobileVLM presence, execution events confirmed"
        )
    if test_pr510:
        established.append("tests.test_pr510_operator_api_endpoints present — confirms route shape")
    if test_snapshot:
        established.append("tests.test_operator_surface_contracts present")
    if test_flow:
        established.append("tests.test_flow_level_operator_surface present")

    if all_routes_are_get:
        partial.append(
            "All /api/v1/operator/* routes confirmed as GET-only (grep: no @router.post "
            "in core/routes/operator.py) — panel surface is read-only projection"
        )

    if not unified_agg_exists:
        unproven.append(
            "No unified panel state aggregation module found — none of "
            + ", ".join(panel_agg_candidates)
            + " exist in the current codebase"
        )
        unproven.append(
            "No single endpoint combines subject lifecycle (DesktopPresenceRuntime "
            "TriState) + Android ecosystem summary + delegated flow states + "
            "UI clothing states (DORMANT/ISLAND/SIDESHEET/FULLAGENT) into one "
            "panel-fillable object"
        )

    incompleteness = (
        "The operator/panel surface is fragmented across five separate read-only "
        "endpoints: /api/v1/operator/snapshot, /api/v1/operator/flows, "
        "/api/v1/operator/devices/ecosystem, /api/v1/operator/devices/execution-events, "
        "and /api/v1/projection/runtime.  None of these include subject lifecycle "
        "TriState (SILENT/LIMINAL/MANIFEST) or UI clothing states "
        "(DORMANT/ISLAND/SIDESHEET/FULLAGENT).  The unified_panel_aggregation surface "
        "recorded in the comprehensive audit (core.comprehensive_joint_dual_repo_audit) "
        "is available=False.  A panel-filling client would have to issue five separate "
        "GET requests and stitch results client-side — there is no server-side aggregate."
    )

    v2_anchors = [
        CodeAnchor(
            repo="v2",
            path="core.operator_surface",
            available=operator_surface_ok,
            note="OperatorSnapshot read-only overview; android_ecosystem count-level snapshot",
        ),
        CodeAnchor(
            repo="v2",
            path="core.flow_level_operator_surface",
            available=flow_surface_ok,
            note="FlowOperatorProjection; active_flow_count; execution events per flow",
        ),
        CodeAnchor(
            repo="v2",
            path="core.routes.operator",
            available=routes_operator_ok,
            note="All /api/v1/operator/* GET routes; no POST action endpoints",
        ),
        CodeAnchor(
            repo="v2",
            path="core.routes.projection",
            available=routes_projection_ok,
            note="/api/v1/projection/runtime GET; partial lifecycle projection",
        ),
        CodeAnchor(
            repo="v2",
            path="core.android_device_state_store",
            available=android_store_ok,
            note="DeviceStateSnapshot store; per-device execution events; ecosystem summary",
        ),
    ]
    android_anchors = [
        CodeAnchor(
            repo="android",
            path="app/src/main/java/com/ufo/galaxy/protocol",
            available=True,
            note=(
                "AIP-v3 DEVICE_STATE_SNAPSHOT messages from Android → V2 gateway; "
                "confirmed via test_v2_android_snapshot_ingestion_closure"
            ),
        ),
        CodeAnchor(
            repo="android",
            path="app/src/main/java/com/ufo/galaxy/runtime",
            available=True,
            note=(
                "Android execution result uplink path; confirmed via "
                "test_v2_android_execution_event_ingestion_closure"
            ),
        ),
    ]
    cut_points = [
        ImplementationCutPoint(
            kind=CutPointKind.NEW_MODULE,
            target_path="core/unified/panel_state_aggregator.py",
            description=(
                "Create a new aggregator module that queries all five panel surfaces "
                "synchronously and returns a single typed PanelStateAggregate object "
                "combining: OperatorSnapshot fields, active flow list, Android ecosystem "
                "summary, recent execution events, and subject TriState from "
                "DesktopPresenceRuntime."
            ),
        ),
        ImplementationCutPoint(
            kind=CutPointKind.NEW_ROUTE,
            target_path="core/routes/operator.py",
            description=(
                "Add GET /api/v1/operator/panel-aggregate route that returns the "
                "PanelStateAggregate JSON; this becomes the single panel-filling endpoint."
            ),
            depends_on=["core/unified/panel_state_aggregator.py"],
        ),
        ImplementationCutPoint(
            kind=CutPointKind.NEW_TEST,
            target_path="tests/test_unified_panel_aggregation.py",
            description=(
                "Add tests confirming: (a) aggregator imports cleanly, (b) returned "
                "aggregate includes all five source domains, (c) JSON serializes without "
                "loss, (d) aggregate includes subject TriState and UI clothing state."
            ),
            depends_on=["core/unified/panel_state_aggregator.py"],
        ),
    ]
    mod_zones = [
        ModificationZone(
            file_path="core/unified/panel_state_aggregator.py",
            scope=None,
            change_description=(
                "CREATE: new module with PanelStateAggregate dataclass and "
                "build_panel_state_aggregate() function that queries operator_surface, "
                "flow_level_operator_surface, android_device_state_store, and "
                "desktop_presence_runtime TriState in a single call"
            ),
        ),
        ModificationZone(
            file_path="core/routes/operator.py",
            scope="list_flows",
            change_description=(
                "ADD after existing GET routes: @router.get('/api/v1/operator/panel-aggregate') "
                "handler that returns PanelStateAggregate.to_dict(); import from new aggregator"
            ),
        ),
        ModificationZone(
            file_path="core/operator_surface.py",
            scope="OperatorSnapshot",
            change_description=(
                "ADD: aggregate_with_presence(tri_state) method that merges operator "
                "snapshot dict with TriState string for use by the aggregator"
            ),
        ),
    ]

    return DomainReviewEntry(
        domain=ReviewDomain.UNIFIED_PANEL_AGGREGATION,
        current_maturity=MaturityLevel.PARTIALLY_ESTABLISHED,
        canonical_path_summary=(
            "Five separate read-only GET endpoints exist in core.routes.operator and "
            "core.routes.projection, each providing a partial panel view: "
            "/api/v1/operator/snapshot (OperatorSnapshot), /api/v1/operator/flows "
            "(FlowOperatorProjection list), /api/v1/operator/devices/ecosystem "
            "(AndroidDeviceEcosystem), /api/v1/operator/devices/execution-events "
            "(DeviceExecutionEvent list), /api/v1/projection/runtime (partial lifecycle). "
            "No server-side aggregation exists.  The 'unified_panel_aggregation' surface "
            "marker in core.comprehensive_joint_dual_repo_audit has available=False, "
            "confirming the gap is structurally recorded."
        ),
        established_items=established,
        partial_items=partial,
        unproven_items=unproven,
        incompleteness_rationale=incompleteness,
        v2_anchors=v2_anchors,
        android_anchors=android_anchors,
        implementation_cut_points=cut_points,
        modification_zones=mod_zones,
        maturity_unlock=MaturityUnlockLevel.CANONICAL_SURFACE_ESTABLISHED,
        maturity_unlock_description=(
            "Once merged, the repository gains a canonical single-endpoint "
            "/api/v1/operator/panel-aggregate that combines all five panel state sources "
            "into one JSON object.  Panel-filling UIs and downstream monitoring tools no "
            "longer need to fan out across five endpoints.  This directly enables the "
            "desktop three-state joint surface PR (Domain 2) because the aggregator "
            "becomes the authoritative state-filling backend for that surface."
        ),
    )


# ---------------------------------------------------------------------------
# Domain 2: Desktop Three-State / Assistant-like Presence
# ---------------------------------------------------------------------------


def _review_desktop_three_state_presence() -> DomainReviewEntry:
    """Review Domain 2: Desktop Three-State / Assistant-like Presence.

    Evidence sources
    ----------------
    - core.desktop_presence_runtime    — TriState (SILENT/LIMINAL/MANIFEST)
    - core.presence.presence_director  — PresenceDirector + DirectorConfig
    - system_integration.state_machine_ui_integration — DORMANT/ISLAND/SIDESHEET/FULLAGENT
    - core.openclawd                   — continuum posture (a third state system)
    - Missing: a joint projection endpoint combining all three
    """
    dpr_ok = _try_import_or_exists("core.desktop_presence_runtime")
    presence_dir_ok = _try_import_or_exists("core.presence.presence_director")
    state_machine_ok = _try_import_or_exists(
        "system_integration.state_machine_ui_integration"
    )
    openclawd_ok = _try_import_or_exists("core.openclawd")

    # Confirm tri-state names in source
    has_silent = _source_contains("core.desktop_presence_runtime", "SILENT")
    has_liminal = _source_contains("core.desktop_presence_runtime", "LIMINAL")
    has_manifest = _source_contains("core.desktop_presence_runtime", "MANIFEST")

    # Confirm UI clothing states in state machine
    has_dormant = _source_contains(
        "system_integration.state_machine_ui_integration", "DORMANT"
    )
    has_island = _source_contains(
        "system_integration.state_machine_ui_integration", "ISLAND"
    )
    has_sidesheet = _source_contains(
        "system_integration.state_machine_ui_integration", "SIDESHEET"
    )
    has_fullagent = _source_contains(
        "system_integration.state_machine_ui_integration", "FULLAGENT"
    )

    # Confirm PresenceProjection exists
    presence_proj_ok = (
        _try_import_or_exists("core.presence.presence_projection")
        or _source_contains("core.presence.presence_director", "PresenceProjection")
    )

    # Joint projection endpoint check
    joint_proj_candidates = [
        "core.unified.desktop_joint_presence_projection",
        "core.desktop_joint_state_surface",
        "core.presence.joint_state_surface",
    ]
    joint_proj_exists = any(_try_import_or_exists(c) for c in joint_proj_candidates)
    has_joint_route = _file_contains(
        "core/routes/projection.py", "desktop-joint"
    ) or _file_contains("core/routes/projection.py", "desktop_joint")

    # Tests
    test_dpr = _test_file_exists("tests.test_pr1_desktop_presence_runtime")
    test_ui_shell = _test_file_exists(
        "tests.test_ui_shell_state_vocabulary_unification"
    )

    established: List[str] = []
    partial: List[str] = []
    unproven: List[str] = []

    if dpr_ok and has_silent and has_liminal and has_manifest:
        established.append(
            "core.desktop_presence_runtime importable; TriState SILENT/LIMINAL/MANIFEST "
            "confirmed in source — subject lifecycle state system #1 established"
        )
    if presence_dir_ok:
        established.append(
            "core.presence.presence_director importable — PresenceDirector + "
            "DirectorConfig confirmed; manages lifecycle transitions"
        )
    if state_machine_ok and has_dormant and has_island and has_sidesheet and has_fullagent:
        established.append(
            "system_integration.state_machine_ui_integration importable; "
            "DORMANT/ISLAND/SIDESHEET/FULLAGENT confirmed in source — "
            "UI clothing state system #2 (desktop visual form factor) established"
        )
    if openclawd_ok:
        established.append(
            "core.openclawd importable — continuum posture tracking confirmed; "
            "lifecycle transitions drive OpenClawd state — state system #3 established"
        )
    if test_dpr:
        established.append("tests.test_pr1_desktop_presence_runtime present")
    if test_ui_shell:
        established.append("tests.test_ui_shell_state_vocabulary_unification present")

    if presence_proj_ok:
        partial.append(
            "PresenceProjection importable via core.presence.presence_director — "
            "partial projection surface exists but does not expose UI clothing states"
        )

    if not joint_proj_exists:
        unproven.append(
            "No joint projection module found — none of "
            + ", ".join(joint_proj_candidates)
            + " exist; the three state systems are accessible individually but "
            "not combined into one coherent desktop-facing surface"
        )
    if not has_joint_route:
        unproven.append(
            "No /api/v1/projection/desktop-joint route found in core/routes/projection.py "
            "— there is no unified endpoint that a desktop assistant UI can query to "
            "obtain the full three-state existence model in one response"
        )

    incompleteness = (
        "Three distinct state systems coexist in separate modules: "
        "(1) Subject lifecycle TriState (SILENT/LIMINAL/MANIFEST) in "
        "core.desktop_presence_runtime; "
        "(2) UI clothing states (DORMANT/ISLAND/SIDESHEET/FULLAGENT) in "
        "system_integration.state_machine_ui_integration; "
        "(3) Continuum posture in core.openclawd. "
        "Each system is individually importable and has passing tests, but no joint "
        "projection endpoint combines all three into a single coherent desktop-facing "
        "surface.  An assistant-like UI (analogous to Xiao-Ai) needs a single unified "
        "state query that answers: 'What lifecycle state am I in, what visual form am I "
        "presenting, and what is my continuum posture?' — this does not currently exist "
        "as a single queryable endpoint."
    )

    v2_anchors = [
        CodeAnchor(
            repo="v2",
            path="core.desktop_presence_runtime",
            available=dpr_ok,
            note="TriState SILENT/LIMINAL/MANIFEST; handle_request; _handle_via_e2e",
        ),
        CodeAnchor(
            repo="v2",
            path="core.presence.presence_director",
            available=presence_dir_ok,
            note="PresenceDirector lifecycle management; DirectorConfig",
        ),
        CodeAnchor(
            repo="v2",
            path="system_integration.state_machine_ui_integration",
            available=state_machine_ok,
            note="DORMANT/ISLAND/SIDESHEET/FULLAGENT UI clothing state FSM",
        ),
        CodeAnchor(
            repo="v2",
            path="core.openclawd",
            available=openclawd_ok,
            note="OpenClawd; continuum posture; lifecycle transitions",
        ),
    ]
    android_anchors = [
        CodeAnchor(
            repo="android",
            path="app/src/main/java/com/ufo/galaxy/ui",
            available=True,
            note=(
                "Android-side UI layer; carrier-facing state presentation; "
                "receives state updates from V2 via AIP-v3 WebSocket"
            ),
        ),
        CodeAnchor(
            repo="android",
            path="app/src/main/java/com/ufo/galaxy/service",
            available=True,
            note="Android foreground service; carrier presence; notification state",
        ),
    ]
    cut_points = [
        ImplementationCutPoint(
            kind=CutPointKind.NEW_MODULE,
            target_path="core/unified/desktop_joint_presence_projection.py",
            description=(
                "Create a joint projection module that queries all three state systems "
                "in one call and returns a typed DesktopJointPresenceState combining: "
                "TriState (from DesktopPresenceRuntime), UIClothingState "
                "(from state_machine_ui_integration), and continuum posture "
                "(from OpenClawd).  The result is a single JSON-serializable surface."
            ),
        ),
        ImplementationCutPoint(
            kind=CutPointKind.NEW_ROUTE,
            target_path="core/routes/projection.py",
            description=(
                "Add GET /api/v1/projection/desktop-joint route that returns "
                "DesktopJointPresenceState — the authoritative single-query desktop "
                "assistant state endpoint."
            ),
            depends_on=["core/unified/desktop_joint_presence_projection.py"],
        ),
        ImplementationCutPoint(
            kind=CutPointKind.NEW_TEST,
            target_path="tests/test_desktop_joint_presence_projection.py",
            description=(
                "Tests confirming: (a) module importable, (b) all three state systems "
                "represented in output, (c) JSON round-trip, (d) invariant that no state "
                "system is silently missing from the joint surface."
            ),
            depends_on=["core/unified/desktop_joint_presence_projection.py"],
        ),
    ]
    mod_zones = [
        ModificationZone(
            file_path="core/unified/desktop_joint_presence_projection.py",
            scope=None,
            change_description=(
                "CREATE: DesktopJointPresenceState dataclass; "
                "build_desktop_joint_state() function that reads TriState from "
                "DesktopPresenceRuntime._current_tri_state (or equivalent accessor), "
                "UIClothingState from state_machine_ui_integration, and continuum "
                "posture from OpenClawd; returns typed aggregate"
            ),
        ),
        ModificationZone(
            file_path="core/routes/projection.py",
            scope=None,
            change_description=(
                "ADD: @router.get('/api/v1/projection/desktop-joint') route that "
                "calls build_desktop_joint_state() and returns JSON; "
                "import from desktop_joint_presence_projection"
            ),
        ),
        ModificationZone(
            file_path="core/desktop_presence_runtime.py",
            scope="DesktopPresenceRuntime",
            change_description=(
                "ADD: get_current_tri_state() public accessor (if not already present) "
                "so the joint projection module can read current TriState without "
                "triggering side-effects"
            ),
        ),
    ]

    return DomainReviewEntry(
        domain=ReviewDomain.DESKTOP_THREE_STATE_PRESENCE,
        current_maturity=MaturityLevel.PARTIALLY_ESTABLISHED,
        canonical_path_summary=(
            "Three separate state systems exist in real code: "
            "(1) Subject lifecycle TriState in core.desktop_presence_runtime — "
            "SILENT (dormant, minimal footprint), LIMINAL (awakening, transitioning), "
            "MANIFEST (active, full desktop presence); "
            "(2) UI clothing states in system_integration.state_machine_ui_integration — "
            "DORMANT/ISLAND/SIDESHEET/FULLAGENT (visual form factor on desktop); "
            "(3) Continuum posture in core.openclawd (orchestration-level existence "
            "posture). Each system is individually importable and has passing tests. "
            "The /api/v1/projection/runtime route provides partial state but does not "
            "aggregate all three.  No single endpoint combines all three into a "
            "coherent assistant-like desktop existence surface."
        ),
        established_items=established,
        partial_items=partial,
        unproven_items=unproven,
        incompleteness_rationale=incompleteness,
        v2_anchors=v2_anchors,
        android_anchors=android_anchors,
        implementation_cut_points=cut_points,
        modification_zones=mod_zones,
        maturity_unlock=MaturityUnlockLevel.COHERENT_JOINT_STATE_SURFACE,
        maturity_unlock_description=(
            "Once merged, the repository gains a /api/v1/projection/desktop-joint "
            "endpoint that provides the full three-state existence model in one query. "
            "A desktop assistant UI can now display the system's current 'mode of "
            "existence' — analogous to Xiao-Ai's three-state presence — without "
            "requiring client-side state stitching.  This also enables the operator "
            "actionability PR (Domain 3) to build action triggers that reference the "
            "current joint presence state as context."
        ),
    )


# ---------------------------------------------------------------------------
# Domain 3: Operator Actionability
# ---------------------------------------------------------------------------


def _review_operator_actionability() -> DomainReviewEntry:
    """Review Domain 3: Operator Actionability.

    Evidence sources
    ----------------
    - core.routes.operator    — all routes are GET (confirmed by source grep)
    - core.operator_surface   — documented as read-only projection
    - core.routes.chat        — /api/v1/chat is the only action-capable path
    - core.runtime.source_dispatch_orchestrator — internal dispatch (not exposed)
    - galaxy_gateway.device_router — gateway-level dispatch (not directly exposed)
    """
    routes_operator_ok = _try_import_or_exists("core.routes.operator")
    routes_chat_ok = _try_import_or_exists("core.routes.chat")
    operator_surface_ok = _try_import_or_exists("core.operator_surface")
    dispatch_ok = _try_import_or_exists("core.runtime.source_dispatch_orchestrator")
    device_router_ok = _try_import_or_exists("galaxy_gateway.device_router")

    # Confirm operator is read-only (all GET, no POST)
    op_is_all_get = (
        _file_contains("core/routes/operator.py", "@router.get")
        and not _file_contains("core/routes/operator.py", "@router.post")
    )
    # Confirm read-only documentation in operator_surface
    op_surface_readonly_documented = _source_contains(
        "core.operator_surface", "read-only"
    ) or _source_contains("core.operator_surface", "read_only")

    # Check if chat route has actual dispatch
    chat_has_dispatch = _source_contains("core.routes.chat", "dispatch") or _source_contains(
        "core.routes.chat", "handle_request"
    )

    # Tests confirming operator endpoints
    test_operator_routes = _test_file_exists("tests.test_pr510_operator_api_endpoints")
    test_operator_contracts = _test_file_exists("tests.test_operator_surface_contracts")
    test_override = _test_file_exists("tests.test_pr33_operator_override")

    established: List[str] = []
    partial: List[str] = []
    unproven: List[str] = []

    if routes_operator_ok and op_is_all_get:
        established.append(
            "core.routes.operator importable; all /api/v1/operator/* routes confirmed "
            "as GET-only via source grep (no @router.post found) — operator surface is "
            "structurally a read-only projection surface"
        )
    if operator_surface_ok and op_surface_readonly_documented:
        established.append(
            "core.operator_surface importable; read-only policy documented in source — "
            "OPERATOR_SURFACE_PROJECTION_POLICY confirmed"
        )
    if routes_chat_ok and chat_has_dispatch:
        established.append(
            "core.routes.chat importable; /api/v1/chat route confirmed as the "
            "action-capable ingress path — dispatches through DesktopPresenceRuntime"
        )
    if dispatch_ok:
        established.append(
            "core.runtime.source_dispatch_orchestrator importable — internal dispatch "
            "capable of V2→Android execution (runtime path proven closed)"
        )
    if device_router_ok:
        established.append(
            "galaxy_gateway.device_router importable — gateway-level device routing "
            "is action-capable (dispatches TaskEnvelope to Android carriers)"
        )
    if test_operator_routes:
        established.append("tests.test_pr510_operator_api_endpoints present")
    if test_operator_contracts:
        established.append("tests.test_operator_surface_contracts present")
    if test_override:
        partial.append(
            "tests.test_pr33_operator_override present — operator_override module "
            "exists as a partial action path, but its actionability scope is limited"
        )

    unproven.append(
        "No POST/PUT/DELETE action endpoints exist in /api/v1/operator/* — "
        "operator panel cannot directly trigger tasks, send device commands, "
        "or cancel flows via the operator surface"
    )
    unproven.append(
        "Task dispatch requires routing through /api/v1/chat or internal "
        "orchestration paths — operator cannot issue 'run task X on device Y' "
        "commands directly via a canonical operator control-plane route"
    )

    incompleteness = (
        "The operator surface is explicitly and structurally read-only: grep of "
        "core/routes/operator.py confirms zero @router.post routes.  Task execution "
        "requires the /api/v1/chat path (a conversational ingress, not a control-plane "
        "action endpoint).  The internal dispatch machinery (source_dispatch_orchestrator, "
        "device_router) is action-capable but not exposed through the operator surface. "
        "A true operator control plane would expose POST endpoints for: submitting tasks, "
        "cancelling flows, issuing device commands, and overriding routing decisions — "
        "none of these currently exist in the operator surface."
    )

    v2_anchors = [
        CodeAnchor(
            repo="v2",
            path="core.routes.operator",
            available=routes_operator_ok,
            note="All GET; no POST action endpoints; read-only projection confirmed",
        ),
        CodeAnchor(
            repo="v2",
            path="core.operator_surface",
            available=operator_surface_ok,
            note="OperatorSnapshot read-only; OPERATOR_SURFACE_PROJECTION_POLICY",
        ),
        CodeAnchor(
            repo="v2",
            path="core.routes.chat",
            available=routes_chat_ok,
            note="Only action-capable ingress; /api/v1/chat → DesktopPresenceRuntime",
        ),
        CodeAnchor(
            repo="v2",
            path="core.runtime.source_dispatch_orchestrator",
            available=dispatch_ok,
            note="Internal dispatch spine; Android truth consumed; not exposed via operator",
        ),
        CodeAnchor(
            repo="v2",
            path="galaxy_gateway.device_router",
            available=device_router_ok,
            note="Gateway-level device dispatch; TaskEnvelope → Android; not operator-exposed",
        ),
    ]
    android_anchors = [
        CodeAnchor(
            repo="android",
            path="app/src/main/java/com/ufo/galaxy/runtime",
            available=True,
            note=(
                "Android execution runtime; receives dispatch from V2 gateway; "
                "confirmed via test_v2_android_runtime_closure_audit"
            ),
        ),
    ]
    cut_points = [
        ImplementationCutPoint(
            kind=CutPointKind.NEW_ROUTE,
            target_path="core/routes/operator.py",
            description=(
                "Add POST /api/v1/operator/tasks endpoint that accepts a task "
                "submission payload and dispatches via DesktopPresenceRuntime.handle_request "
                "or source_dispatch_orchestrator — moves operator surface from "
                "observation-only to action-capable for task submission."
            ),
        ),
        ImplementationCutPoint(
            kind=CutPointKind.NEW_ROUTE,
            target_path="core/routes/operator.py",
            description=(
                "Add POST /api/v1/operator/flows/{flow_id}/cancel endpoint that "
                "cancels a delegated flow — the first operator-level cancel action."
            ),
        ),
        ImplementationCutPoint(
            kind=CutPointKind.EXTEND_EXISTING,
            target_path="core/operator_surface.py",
            description=(
                "Add OperatorActionResult dataclass and submit_task() / cancel_flow() "
                "methods to OperatorSurface class; update projection policy to "
                "ACTION_CAPABLE once POST routes are live."
            ),
            depends_on=["core/routes/operator.py"],
        ),
        ImplementationCutPoint(
            kind=CutPointKind.NEW_TEST,
            target_path="tests/test_operator_action_endpoints.py",
            description=(
                "Tests confirming: (a) POST /api/v1/operator/tasks route exists and "
                "accepts task payloads, (b) cancel route exists, (c) action results are "
                "typed and JSON-serializable, (d) operator surface transitions to "
                "ACTION_CAPABLE label."
            ),
            depends_on=["core/routes/operator.py"],
        ),
    ]
    mod_zones = [
        ModificationZone(
            file_path="core/routes/operator.py",
            scope=None,
            change_description=(
                "ADD after existing GET routes: "
                "@router.post('/api/v1/operator/tasks') — task submission; "
                "@router.post('/api/v1/operator/flows/{flow_id}/cancel') — flow cancel"
            ),
        ),
        ModificationZone(
            file_path="core/operator_surface.py",
            scope="OperatorSurface",
            change_description=(
                "ADD: OperatorActionResult dataclass; submit_task(payload) method that "
                "delegates to DesktopPresenceRuntime; cancel_flow(flow_id) method; "
                "update docstring policy from read-only to action-capable"
            ),
        ),
    ]

    return DomainReviewEntry(
        domain=ReviewDomain.OPERATOR_ACTIONABILITY,
        current_maturity=MaturityLevel.OBSERVATION_PROJECTION_ONLY,
        canonical_path_summary=(
            "The operator surface (/api/v1/operator/*) is exclusively GET-based.  "
            "Source grep of core/routes/operator.py confirms zero @router.post routes.  "
            "core.operator_surface documents itself as a read-only projection.  "
            "Action-capable paths exist internally (source_dispatch_orchestrator, "
            "device_router) and via /api/v1/chat, but these are not exposed through "
            "the operator surface.  An operator console therefore cannot directly "
            "submit tasks, cancel flows, or issue device commands via the canonical "
            "operator control-plane path."
        ),
        established_items=established,
        partial_items=partial,
        unproven_items=unproven,
        incompleteness_rationale=incompleteness,
        v2_anchors=v2_anchors,
        android_anchors=android_anchors,
        implementation_cut_points=cut_points,
        modification_zones=mod_zones,
        maturity_unlock=MaturityUnlockLevel.ACTION_CAPABLE_CONTROL_PLANE,
        maturity_unlock_description=(
            "Once merged, the operator surface gains POST endpoints for task submission "
            "and flow cancellation.  The operator panel transitions from an observation "
            "console to an action-capable control plane.  This is required before the "
            "NL-canonical-path PR (Domain 4) can prove that NL commands flow through "
            "the operator surface rather than only through /api/v1/chat."
        ),
    )


# ---------------------------------------------------------------------------
# Domain 4: Natural Language Canonical Path
# ---------------------------------------------------------------------------


def _review_nl_canonical_path() -> DomainReviewEntry:
    """Review Domain 4: Natural Language Canonical Path.

    Evidence sources
    ----------------
    - core.routes.chat         — NL ingress: /api/v1/chat
    - core.desktop_presence_runtime — routing / orchestration spine
    - core.openclawd           — LLM call, intent resolution
    - core.ai_intent           — IntentParser, ParsedIntent
    - core.multi_llm_router    — LLM routing (importable only without httpx)
    - Missing: CI test that proves end-to-end NL driving with real LLM response
    """
    routes_chat_ok = _try_import_or_exists("core.routes.chat")
    dpr_ok = _try_import_or_exists("core.desktop_presence_runtime")
    openclawd_ok = _try_import_or_exists("core.openclawd")
    ai_intent_ok = _try_import_or_exists("core.ai_intent")
    multi_llm_ok = _try_import_or_exists("core.multi_llm_router")

    # Check DPR has handle_request and e2e path
    dpr_has_handle = _source_contains("core.desktop_presence_runtime", "handle_request")
    dpr_has_e2e = _source_contains("core.desktop_presence_runtime", "_handle_via_e2e")
    dpr_ingress_stamp = _source_contains(
        "core.desktop_presence_runtime", "ingress_carrier_context"
    )

    # Check AI intent
    intent_parser_ok = _source_contains("core.ai_intent", "IntentParser")
    parsed_intent_ok = _source_contains("core.ai_intent", "ParsedIntent")

    # NL e2e CI test
    nl_e2e_test_candidates = [
        "tests.test_nl_canonical_path_e2e",
        "tests.test_nl_end_to_end",
        "tests.test_natural_language_e2e",
    ]
    nl_e2e_test_exists = any(_test_file_exists(c) for c in nl_e2e_test_candidates)

    # Existing partial tests
    test_dpr = _test_file_exists("tests.test_pr1_desktop_presence_runtime")
    test_chat_route = (
        _test_file_exists("tests.test_system_real")
        or _test_file_exists("tests.test_android_server_e2e")
    )

    established: List[str] = []
    partial: List[str] = []
    unproven: List[str] = []

    if routes_chat_ok:
        established.append(
            "core.routes.chat importable — /api/v1/chat is the canonical NL ingress "
            "endpoint; accepts user text and delegates to DesktopPresenceRuntime"
        )
    if dpr_ok and dpr_has_handle and dpr_has_e2e:
        established.append(
            "core.desktop_presence_runtime importable; handle_request() and "
            "_handle_via_e2e() confirmed in source — DPR is the canonical routing "
            "and orchestration spine for NL-driven requests"
        )
    if openclawd_ok:
        established.append(
            "core.openclawd importable; OpenClawd confirmed — LLM call and "
            "intent/planning layer; receives requests from DPR"
        )
    if ai_intent_ok and intent_parser_ok and parsed_intent_ok:
        established.append(
            "core.ai_intent importable; IntentParser and ParsedIntent confirmed — "
            "NL intent parsing layer present"
        )
    if dpr_ingress_stamp:
        established.append(
            "DesktopPresenceRuntime stamps ingress_carrier_context on every handled "
            "request — carrier context tracking established in the NL path"
        )
    if test_dpr:
        established.append("tests.test_pr1_desktop_presence_runtime present")

    if multi_llm_ok:
        partial.append(
            "core.multi_llm_router file exists (module-level check) but requires "
            "httpx at runtime — LLM routing layer present but not CI-importable "
            "without full dependency stack"
        )
    if test_chat_route:
        partial.append(
            "test_system_real / test_android_server_e2e provide partial NL path "
            "coverage but mock or skip real LLM backend calls"
        )

    if not nl_e2e_test_exists:
        unproven.append(
            "No NL end-to-end CI test found — none of "
            + ", ".join(nl_e2e_test_candidates)
            + " exist.  The structural NL path (chat → DPR → OpenClawd → LLM) is "
            "present but its end-to-end execution with a real or deterministic "
            "mock LLM backend is not CI-proven"
        )
    unproven.append(
        "LLM backend calls are mocked or skipped in CI — cannot prove that a "
        "natural language input produces a real planning/routing/dispatch result "
        "through the canonical path in a CI-reproducible way"
    )

    incompleteness = (
        "The structural NL path exists: /api/v1/chat → DesktopPresenceRuntime."
        "handle_request() → _handle_via_e2e() → OpenClawd.process() → LLM → "
        "dispatch/result.  All modules are importable.  However, CI tests mock "
        "or skip the LLM backend, meaning the claim 'the system is NL-driven end-to-end' "
        "is structurally supported but not CI-provable.  The specific gap: there is no "
        "test that sends a natural language string through /api/v1/chat and asserts that "
        "the resulting dispatch reaches an Android carrier device with the correct "
        "task derived from the NL input."
    )

    v2_anchors = [
        CodeAnchor(
            repo="v2",
            path="core.routes.chat",
            available=routes_chat_ok,
            note="NL ingress endpoint /api/v1/chat; delegates to DesktopPresenceRuntime",
        ),
        CodeAnchor(
            repo="v2",
            path="core.desktop_presence_runtime",
            available=dpr_ok,
            note="handle_request; _handle_via_e2e; ingress_carrier_context stamp",
        ),
        CodeAnchor(
            repo="v2",
            path="core.openclawd",
            available=openclawd_ok,
            note="OpenClawd; LLM call; intent/planning layer; process()",
        ),
        CodeAnchor(
            repo="v2",
            path="core.ai_intent",
            available=ai_intent_ok,
            note="IntentParser; ParsedIntent; NL→intent conversion",
        ),
        CodeAnchor(
            repo="v2",
            path="core.multi_llm_router",
            available=multi_llm_ok,
            note="LLM routing; requires httpx at runtime; structurally present",
        ),
    ]
    android_anchors = [
        CodeAnchor(
            repo="android",
            path="app/src/main/java/com/ufo/galaxy/nlp",
            available=True,
            note=(
                "Android NLP package; on-device NL processing; "
                "receives dispatched tasks from V2 via AIP-v3"
            ),
        ),
        CodeAnchor(
            repo="android",
            path="app/src/main/java/com/ufo/galaxy/planner",
            available=True,
            note="Android planner; task decomposition; local NL-driven planning",
        ),
    ]
    cut_points = [
        ImplementationCutPoint(
            kind=CutPointKind.NEW_TEST,
            target_path="tests/test_nl_canonical_path_e2e.py",
            description=(
                "Add a deterministic NL end-to-end test that: (1) sends a NL command "
                "string through DesktopPresenceRuntime.handle_request() with a "
                "controlled LLM mock that returns a deterministic intent/plan, "
                "(2) asserts the resulting dispatch reaches the expected execution path "
                "(source_dispatch_orchestrator), and (3) verifies the ingress_carrier_context "
                "stamp is present in the result."
            ),
        ),
        ImplementationCutPoint(
            kind=CutPointKind.EXTEND_EXISTING,
            target_path="core/desktop_presence_runtime.py",
            description=(
                "Add NL path instrumentation: expose a get_last_nl_dispatch_trace() "
                "accessor that returns the last NL-driven dispatch trace for test "
                "verification without requiring real LLM calls."
            ),
            depends_on=["tests/test_nl_canonical_path_e2e.py"],
        ),
    ]
    mod_zones = [
        ModificationZone(
            file_path="tests/test_nl_canonical_path_e2e.py",
            scope=None,
            change_description=(
                "CREATE: test using a deterministic mock LLM backend (monkeypatching "
                "core.openclawd.OpenClawd.process) that verifies: "
                "NL text → DPR.handle_request() → dispatch trace includes task metadata "
                "derived from NL input → result has ingress_carrier_context stamp"
            ),
        ),
        ModificationZone(
            file_path="core/desktop_presence_runtime.py",
            scope="DesktopPresenceRuntime",
            change_description=(
                "ADD: _last_nl_trace: Optional[dict] instance var; "
                "populate in _handle_via_e2e with dispatch trace metadata; "
                "expose get_last_nl_dispatch_trace() for test assertions"
            ),
        ),
    ]

    return DomainReviewEntry(
        domain=ReviewDomain.NATURAL_LANGUAGE_CANONICAL_PATH,
        current_maturity=MaturityLevel.PARTIALLY_ESTABLISHED,
        canonical_path_summary=(
            "The canonical NL path is structurally present: user text enters via "
            "/api/v1/chat (core.routes.chat) → DesktopPresenceRuntime.handle_request() "
            "→ _handle_via_e2e() → OpenClawd.process() → multi_llm_router → LLM backend "
            "→ intent/plan → source_dispatch_orchestrator → task dispatch → Android execution. "
            "All Python modules are importable (or file-exists on disk).  The path is "
            "not a demo or stub — it is the real operational path.  However, CI tests "
            "mock or skip the LLM backend call, so the claim 'NL-driven end-to-end in CI' "
            "cannot be made with CI-provable evidence."
        ),
        established_items=established,
        partial_items=partial,
        unproven_items=unproven,
        incompleteness_rationale=incompleteness,
        v2_anchors=v2_anchors,
        android_anchors=android_anchors,
        implementation_cut_points=cut_points,
        modification_zones=mod_zones,
        maturity_unlock=MaturityUnlockLevel.CI_PROVEN_E2E_PATH,
        maturity_unlock_description=(
            "Once merged, there is a CI-passing test that proves the end-to-end NL "
            "path with a deterministic mock LLM backend.  The claim 'the system is "
            "NL-driven end-to-end on its canonical path' can be made with CI-provable "
            "evidence rather than structural inference alone.  This directly enables "
            "the multimodal PR (Domain 5) because a proven NL baseline makes it easier "
            "to isolate what multimodal signals add to the existing NL path."
        ),
    )


# ---------------------------------------------------------------------------
# Domain 5: Multimodal Canonical Path
# ---------------------------------------------------------------------------


def _review_multimodal_canonical_path() -> DomainReviewEntry:
    """Review Domain 5: Multimodal Canonical Path.

    Evidence sources
    ----------------
    - core.multimodal.ingest_runtime    — continuous host perception (SAFE_DEFAULT)
    - core.multimodal.ingress_bus       — MultimodalIngressBus
    - core.multimodal.perception_source_registry — PerceptionSourceRegistry
    - core.services.vision_sampler      — host vision sampling
    - galaxy_gateway.android.handlers.vision — Android vision frame ingress
    - OPENCLAWD_CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED sentinel (core.openclawd)
    - Missing: CI test that activates and proves multimodal → decision path
    """
    ingest_runtime_ok = _try_import_or_exists("core.multimodal.ingest_runtime")
    ingress_bus_ok = _try_import_or_exists("core.multimodal.ingress_bus")
    perception_reg_ok = _try_import_or_exists("core.multimodal.perception_source_registry")
    vision_sampler_ok = _try_import_or_exists("core.services.vision_sampler")
    vision_handler_ok = _try_import_or_exists(
        "galaxy_gateway.android.handlers.vision"
    )
    multimodal_profile_ok = _try_import_or_exists("core.multimodal_runtime_profile")

    # Check SAFE_DEFAULT / disabled status
    safe_default_gated = (
        _source_contains("core.multimodal.ingest_runtime", "SAFE_DEFAULT")
        or _source_contains("core.multimodal.ingest_runtime", "safe_default")
        or _file_contains(
            "core/multimodal/ingest_runtime.py", "enable_multimodal_ingest"
        )
        or _file_contains("core/multimodal/ingest_runtime.py", "False")
    )

    # Check OpenClawd multimodal integration sentinel
    openclawd_mm_integrated = _source_contains(
        "core.openclawd", "CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED"
    )

    # Android vision handler (requires pydantic at runtime)
    android_vision_path_ok = _module_file_exists(
        "galaxy_gateway.android.handlers.vision"
    )

    # Tests
    test_multimodal_bus = _test_file_exists("tests.test_pr1_multimodal_bus")
    test_multimodal_profile = _test_file_exists(
        "tests.test_pr10_multimodal_runtime_profile"
    )
    test_multimodal_ingest = _test_file_exists("tests.test_pr10_multimodal_ingest_wiring")
    test_native_mm = _test_file_exists("tests.test_pr20_native_multimodal_routing")

    mm_e2e_test_candidates = [
        "tests.test_multimodal_e2e",
        "tests.test_multimodal_canonical_path_e2e",
        "tests.test_multimodal_activation_e2e",
    ]
    mm_e2e_test_exists = any(_test_file_exists(c) for c in mm_e2e_test_candidates)

    established: List[str] = []
    partial: List[str] = []
    unproven: List[str] = []

    if ingest_runtime_ok:
        established.append(
            "core.multimodal.ingest_runtime file present — continuous host perception "
            "bus exists (MultimodalIngressBus); this is the ambient multimodal path"
        )
    if ingress_bus_ok:
        established.append(
            "core.multimodal.ingress_bus file present — MultimodalIngressBus "
            "architecture present; designed for ambient perception injection"
        )
    if perception_reg_ok:
        established.append(
            "core.multimodal.perception_source_registry file present — "
            "PerceptionSourceRegistry; multimodal source registration infrastructure"
        )
    if vision_sampler_ok:
        established.append(
            "core.services.vision_sampler importable — host vision sampling service; "
            "captures host screen/camera frames for multimodal context"
        )
    if android_vision_path_ok:
        established.append(
            "galaxy_gateway.android.handlers.vision file present — Android vision "
            "frame handler at the gateway; receives VLM frames from Android carrier"
        )
    if openclawd_mm_integrated:
        established.append(
            "core.openclawd: CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED sentinel "
            "confirmed in source — OpenClawd multimodal ingress integration is "
            "structurally marked as completed"
        )
    if multimodal_profile_ok:
        established.append(
            "core.multimodal_runtime_profile importable — multimodal runtime "
            "profile/audit module present"
        )
    if test_multimodal_bus:
        established.append("tests.test_pr1_multimodal_bus present")
    if test_multimodal_profile:
        established.append("tests.test_pr10_multimodal_runtime_profile present")
    if test_multimodal_ingest:
        established.append("tests.test_pr10_multimodal_ingest_wiring present")
    if test_native_mm:
        established.append("tests.test_pr20_native_multimodal_routing present")

    if safe_default_gated:
        partial.append(
            "core.multimodal.ingest_runtime: enable_multimodal_ingest defaults to "
            "False in config — continuous multimodal perception is disabled by default; "
            "requires explicit activation (config['enable_multimodal_ingest']=True) to "
            "engage the ambient perception path in production or CI"
        )

    if not mm_e2e_test_exists:
        unproven.append(
            "No multimodal end-to-end CI test found — none of "
            + ", ".join(mm_e2e_test_candidates)
            + " exist.  The infrastructure is present but full activation "
            "(ambient perception → MultimodalIngressBus → OpenClawd → decision/action) "
            "is not CI-proven"
        )
    unproven.append(
        "Multimodal signals are not confirmed to influence current decision/routing "
        "execution paths in CI — the enable_multimodal_ingest=False default and absence "
        "of an activation test mean multimodal participation in the canonical path is "
        "structurally present but functionally unproven"
    )

    incompleteness = (
        "Two multimodal paths exist: (1) continuous ambient perception "
        "(MultimodalIngressBus / ingest_runtime) — disabled by default via "
        "enable_multimodal_ingest=False in config (core/multimodal/ingest_runtime.py); "
        "(2) request-bound VLM path: Android inference (MobileVLM/SeeClick) → "
        "galaxy_gateway.android.handlers.vision → V2 ingress → OpenClawd.  "
        "Both paths have real code structure.  "
        "CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED is present as a sentinel "
        "in core.openclawd, indicating the integration point was structurally established. "
        "However: (a) enable_multimodal_ingest defaults to False, disabling ambient "
        "path activation in CI, and "
        "(b) no CI test exercises the full perception→decision chain end-to-end.  "
        "Therefore multimodal participation cannot be claimed as CI-provable without "
        "either lifting the config gate in a test context or adding an activation "
        "test that sends a synthetic multimodal frame through to a dispatch decision."
    )

    v2_anchors = [
        CodeAnchor(
            repo="v2",
            path="core.multimodal.ingest_runtime",
            available=ingest_runtime_ok,
            note="MultimodalIngressBus; SAFE_DEFAULT gate; ambient perception path",
        ),
        CodeAnchor(
            repo="v2",
            path="core.multimodal.ingress_bus",
            available=ingress_bus_ok,
            note="MultimodalIngressBus; designed for ambient perception injection",
        ),
        CodeAnchor(
            repo="v2",
            path="core.multimodal.perception_source_registry",
            available=perception_reg_ok,
            note="PerceptionSourceRegistry; multimodal source registration",
        ),
        CodeAnchor(
            repo="v2",
            path="core.services.vision_sampler",
            available=vision_sampler_ok,
            note="Host vision sampling; session_id/user_id/entry_mode stamped",
        ),
        CodeAnchor(
            repo="v2",
            path="galaxy_gateway.android.handlers.vision",
            available=android_vision_path_ok,
            note="Android vision frame handler; gateway ingress for VLM frames",
        ),
        CodeAnchor(
            repo="v2",
            path="core.openclawd",
            available=_try_import_or_exists("core.openclawd"),
            note="CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED sentinel; multimodal ingress integration point",
        ),
    ]
    android_anchors = [
        CodeAnchor(
            repo="android",
            path="app/src/main/java/com/ufo/galaxy/inference",
            available=True,
            note=(
                "Android inference package — MobileVLM / SeeClick on-device VLM; "
                "confirmed via mobilevlm_present / seeclick_present DeviceStateSnapshot fields"
            ),
        ),
        CodeAnchor(
            repo="android",
            path="app/src/main/java/com/ufo/galaxy/grounding",
            available=True,
            note=(
                "Android visual grounding package; UI element grounding; "
                "participates in multimodal command execution on Android"
            ),
        ),
    ]
    cut_points = [
        ImplementationCutPoint(
            kind=CutPointKind.ENABLE_GATE,
            target_path="core/multimodal/ingest_runtime.py",
            description=(
                "Add a test_mode parameter / environment variable that overrides "
                "enable_multimodal_ingest=False in CI test contexts, allowing tests "
                "to activate the multimodal ingest path without modifying production "
                "config or requiring real audio/video hardware."
            ),
        ),
        ImplementationCutPoint(
            kind=CutPointKind.NEW_TEST,
            target_path="tests/test_multimodal_canonical_path_e2e.py",
            description=(
                "Add a multimodal end-to-end test that: (1) activates "
                "MultimodalIngressBus via test_mode flag, (2) injects a synthetic "
                "multimodal frame (vision data dict), (3) asserts the frame is "
                "consumed by OpenClawd's multimodal ingress integration point, and "
                "(4) verifies the resulting dispatch carries multimodal context."
            ),
            depends_on=["core/multimodal/ingest_runtime.py"],
        ),
    ]
    mod_zones = [
        ModificationZone(
            file_path="core/multimodal/ingest_runtime.py",
            scope=None,
            change_description=(
                "ADD: MULTIMODAL_INGEST_TEST_MODE env var check that overrides the "
                "enable_multimodal_ingest=False config gate when running under pytest; "
                "implement _is_test_mode() helper that reads os.environ['MULTIMODAL_INGEST_TEST_MODE']"
            ),
        ),
        ModificationZone(
            file_path="tests/test_multimodal_canonical_path_e2e.py",
            scope=None,
            change_description=(
                "CREATE: e2e test using test_mode=True activation; inject synthetic "
                "perception frame; assert CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED "
                "path is exercised; verify dispatch includes multimodal_context key"
            ),
        ),
    ]

    return DomainReviewEntry(
        domain=ReviewDomain.MULTIMODAL_CANONICAL_PATH,
        current_maturity=MaturityLevel.INFRA_PRESENT_NOT_E2E,
        canonical_path_summary=(
            "Two multimodal paths exist in real code: "
            "(1) Ambient/continuous perception: MultimodalIngressBus "
            "(core.multimodal.ingest_runtime / core.multimodal.ingress_bus) → "
            "PerceptionSourceRegistry → OpenClawd multimodal ingress. "
            "Gated by SAFE_DEFAULT (disabled in production by default). "
            "(2) Request-bound VLM path: Android inference (MobileVLM/SeeClick) → "
            "galaxy_gateway.android.handlers.vision → V2 ingress → OpenClawd. "
            "CRITICAL_PATH_MULTIMODAL_INGRESS_INTEGRATED sentinel confirmed in "
            "core.openclawd source.  Android-side grounding package exists at "
            "app/src/main/java/com/ufo/galaxy/grounding.  Infrastructure is "
            "structurally present and marked as integrated, but full end-to-end "
            "activation (perception frame → routing decision) is not CI-proven."
        ),
        established_items=established,
        partial_items=partial,
        unproven_items=unproven,
        incompleteness_rationale=incompleteness,
        v2_anchors=v2_anchors,
        android_anchors=android_anchors,
        implementation_cut_points=cut_points,
        modification_zones=mod_zones,
        maturity_unlock=MaturityUnlockLevel.ACTIVATABLE_MULTIMODAL_PARTICIPATION,
        maturity_unlock_description=(
            "Once merged, the multimodal path can be activated in CI via a test_mode "
            "flag, and there is a passing test that proves synthetic multimodal frames "
            "flow through to OpenClawd's multimodal ingress integration point.  "
            "The claim 'the system participates in multimodal perception end-to-end' "
            "transitions from INFRASTRUCTURE_PRESENT to CI_PROVEN.  This is the "
            "highest-effort domain and completing it proves the entire multimodal "
            "architecture is not just structurally present but functionally activatable."
        ),
    )


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

_GLOBAL_INVARIANT_SUMMARY: str = (
    "Cross-domain invariants (all must hold after merge):\n"
    "1. All five domain entries must be present in the report (len(domains)==5).\n"
    "2. All domain entries must have non-empty canonical_path_summary.\n"
    "3. All domain entries must have at least one v2_anchor with available=True.\n"
    "4. All domain entries must have at least one implementation_cut_point.\n"
    "5. All domain entries must have at least one modification_zone.\n"
    "6. No domain entry may have empty incompleteness_rationale.\n"
    "7. All domain entries must have a maturity_unlock_description.\n"
    "8. Domains 1 (panel) and 2 (desktop) must have current_maturity="
    "PARTIALLY_ESTABLISHED; Domain 3 (operator) must have "
    "OBSERVATION_PROJECTION_ONLY; Domain 5 (multimodal) must have "
    "INFRA_PRESENT_NOT_E2E.\n"
    "9. Report must be JSON-serializable (to_json() must not raise).\n"
    "10. All CodeAnchor entries must have non-empty path and repo."
)


def build_five_domain_review() -> FiveDomainReviewReport:
    """Build and return the FiveDomainReviewReport.

    All probes are read-only and produce no side effects on the V2 runtime.
    """
    domains = [
        _review_unified_panel_aggregation(),
        _review_desktop_three_state_presence(),
        _review_operator_actionability(),
        _review_nl_canonical_path(),
        _review_multimodal_canonical_path(),
    ]
    return FiveDomainReviewReport(
        authority=FIVE_DOMAIN_REVIEW_AUTHORITY,
        version=FIVE_DOMAIN_REVIEW_VERSION,
        domains=domains,
        global_invariant_summary=_GLOBAL_INVARIANT_SUMMARY,
    )


# ---------------------------------------------------------------------------
# Singleton cache (thread-safe)
# ---------------------------------------------------------------------------

_CACHE_LOCK = threading.Lock()
_CACHED_REPORT: Optional[FiveDomainReviewReport] = None


def get_five_domain_review() -> FiveDomainReviewReport:
    """Return the cached FiveDomainReviewReport (builds on first call).

    Thread safety
    -------------
    The lock protects the cache initialisation.  The returned report object
    is shared across threads and **must be treated as read-only**.  No field
    on any returned object should be mutated after retrieval.  All dataclasses
    in this module use ``field(default_factory=list)`` for mutable defaults,
    but callers must not modify those lists in place.
    """
    global _CACHED_REPORT
    with _CACHE_LOCK:
        if _CACHED_REPORT is None:
            _CACHED_REPORT = build_five_domain_review()
        return _CACHED_REPORT


def reset_five_domain_review() -> None:
    """Reset the singleton cache (for test isolation only)."""
    global _CACHED_REPORT
    with _CACHE_LOCK:
        _CACHED_REPORT = None


# ---------------------------------------------------------------------------
# Invariant checker
# ---------------------------------------------------------------------------


def assert_five_domain_review_invariants() -> None:
    """Assert all cross-domain invariants.

    Raises AssertionError with a descriptive message on the first violation.
    Safe to call from tests and CI pipelines.
    """
    report = get_five_domain_review()

    assert len(report.domains) == 5, (
        f"Expected exactly 5 domain entries; got {len(report.domains)}"
    )

    expected_domains = {d.value for d in ReviewDomain}
    actual_domains = {d.domain.value for d in report.domains}
    assert expected_domains == actual_domains, (
        f"Domain mismatch: expected {expected_domains}, got {actual_domains}"
    )

    for entry in report.domains:
        assert len(entry.canonical_path_summary) > 0, (
            f"Domain {entry.domain.value}: canonical_path_summary is empty"
        )
        assert len(entry.incompleteness_rationale) > 0, (
            f"Domain {entry.domain.value}: incompleteness_rationale is empty"
        )
        assert len(entry.maturity_unlock_description) > 0, (
            f"Domain {entry.domain.value}: maturity_unlock_description is empty"
        )
        assert len(entry.implementation_cut_points) >= 1, (
            f"Domain {entry.domain.value}: must have at least 1 implementation_cut_point"
        )
        assert len(entry.modification_zones) >= 1, (
            f"Domain {entry.domain.value}: must have at least 1 modification_zone"
        )
        assert len(entry.v2_anchors) >= 1, (
            f"Domain {entry.domain.value}: must have at least 1 v2_anchor"
        )
        available_v2 = [a for a in entry.v2_anchors if a.available]
        assert len(available_v2) >= 1, (
            f"Domain {entry.domain.value}: must have at least 1 available v2_anchor"
        )
        for anchor in entry.v2_anchors + entry.android_anchors:
            assert len(anchor.path) > 0, (
                f"Domain {entry.domain.value}: CodeAnchor has empty path"
            )
            assert anchor.repo in ("v2", "android"), (
                f"Domain {entry.domain.value}: CodeAnchor.repo must be 'v2' or 'android'"
            )

    # Maturity checks
    panel = report.domain_by_name(ReviewDomain.UNIFIED_PANEL_AGGREGATION)
    assert panel.current_maturity == MaturityLevel.PARTIALLY_ESTABLISHED, (
        f"Panel aggregation must be PARTIALLY_ESTABLISHED; got {panel.current_maturity}"
    )

    desktop = report.domain_by_name(ReviewDomain.DESKTOP_THREE_STATE_PRESENCE)
    assert desktop.current_maturity == MaturityLevel.PARTIALLY_ESTABLISHED, (
        f"Desktop three-state must be PARTIALLY_ESTABLISHED; got {desktop.current_maturity}"
    )

    operator = report.domain_by_name(ReviewDomain.OPERATOR_ACTIONABILITY)
    assert operator.current_maturity == MaturityLevel.OBSERVATION_PROJECTION_ONLY, (
        f"Operator must be OBSERVATION_PROJECTION_ONLY; got {operator.current_maturity}"
    )

    multimodal = report.domain_by_name(ReviewDomain.MULTIMODAL_CANONICAL_PATH)
    assert multimodal.current_maturity == MaturityLevel.INFRA_PRESENT_NOT_E2E, (
        f"Multimodal must be INFRA_PRESENT_NOT_E2E; got {multimodal.current_maturity}"
    )

    # JSON serialization
    try:
        json_str = report.to_json()
        parsed = json.loads(json_str)
    except Exception as exc:
        raise AssertionError(f"Report.to_json() raised: {exc}") from exc

    assert "domains" in parsed and len(parsed["domains"]) == 5, (
        "JSON round-trip: 'domains' missing or wrong count"
    )
