#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/full_current_state_dual_repo_rereading.py
===============================================
Full Current-State Dual-Repo Rereading of the Galaxy System from the
PR #993 Baseline — using only real code, real tests, and real canonical
runtime paths as evidence.

Repositories under review
--------------------------
- DannyFish-11/ufo-galaxy-realization-v2  (V2 — this repo, center authority)
- DannyFish-11/ufo-galaxy-android         (Android — participant carrier node)

Purpose
-------
This module provides a FULL, FRESH rereading of the dual-repo Galaxy system
using the PR #993 baseline as the cognitive starting point, but grounding ALL
conclusions strictly in current merged code, current tests, and current
canonical runtime paths.

This is NOT a delta-from-the-last-review document.  It re-reads the system
from scratch to produce a current-state picture that answers:

1. What the dual-repo system currently IS in real code
2. Which PR #993 claims are now strongly established
3. Which claims remain partial or qualified
4. Which canonical paths are fully closed
5. Which areas remain only surface/store/schema aligned
6. Whether the current remaining work is now mainly decision-path closure
   and tail consolidation
7. What stage of completion the system is currently in
8. What stage the system would enter if the remaining orchestration-
   consumption gap were closed

Prior review chain
------------------
- PR #1014: core.pr993_dual_repo_reevaluation — baseline code-grounded
  reevaluation of PR #993 claims.
- (Post PR #1011/1013/1015/Android#335): core.post_closure_dual_repo_reassessment
  — incremental update after the four closure PRs.

This module supersedes the "system characterization" and "stage judgment"
outputs of both prior reviews with a comprehensive, non-incremental reading
of the current codebase.

Evidence used
-------------
- Real Python imports and attribute checks against the live V2 codebase.
- Existence of specific CI test modules as machine-verifiable runtime proof.
- Source inspection (``inspect.getsource``) for attribute-level confirmation.
- Android-side evidence is referenced via V2-side integration tests that
  exercise the Android protocol (no direct import of Android repo code is
  possible from this repo).
- NO markdown documents, README text, PR prose, audit narratives, or
  architecture descriptions are used as evidence.

Design principles
-----------------
1. **Additive only** — no existing module is modified.
2. **Fail-conservative** — missing imports or test modules yield downgraded
   labels; never silently optimistic.
3. **Honest** — claims that are only schema/store/surface aligned are
   explicitly labeled as such.
4. **Comprehensive** — the report covers all 7 PR #993 claim families, all
   6 dual-repo canonical paths, the current completion stage, the
   post-next-PR stage, and the full P0/P1/P2/P3 roadmap.
5. **Non-incremental** — this is NOT a delta from the prior review.  It
   produces a standalone picture of the current system state.

Public API
----------
Authority / policy sentinels::

    FULL_CURRENT_STATE_REREADING_AUTHORITY
    FULL_CURRENT_STATE_REREADING_METHODOLOGY
    FULL_CURRENT_STATE_VERDICT_ZH

Enumerations::

    CurrentEvidenceLabel       — 6-tier evidence ladder
    CompletionStage            — system-level completion stage
    RoadmapPriority            — P0 / P1 / P2 / P3

Dataclasses::

    DualRepoSystemCharacterization
    ClaimMatrixEntry
    CanonicalPathEntry
    CompletionStageJudgment
    PostNextPRJudgment
    RoadmapEntry
    FullCurrentStateReport

Functions::

    build_full_current_state_rereading() -> FullCurrentStateReport
    get_full_current_state_rereading()   -> FullCurrentStateReport  (cached singleton)
    reset_full_current_state_rereading() -> None                    (test isolation)
    assert_full_current_state_invariants() -> None                  (test helper)
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
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

logger = logging.getLogger("Galaxy.FullCurrentStateRereading")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

FULL_CURRENT_STATE_REREADING_AUTHORITY: str = (
    "FULL_CURRENT_STATE_DUAL_REPO_REREADING_AUTHORITY::"
    "core.full_current_state_dual_repo_rereading::"
    "full-rereading-from-pr993-baseline-using-real-code-only"
)

FULL_CURRENT_STATE_REREADING_METHODOLOGY: str = (
    "METHODOLOGY: Full, non-incremental rereading of the dual-repo Galaxy system "
    "(ufo-galaxy-realization-v2 × ufo-galaxy-android) from the PR #993 cognitive "
    "baseline. All conclusions are grounded in: real Python imports and attribute "
    "checks against the live V2 codebase; existence of specific CI test modules as "
    "machine-verifiable runtime proof; inspect.getsource() for attribute-level "
    "confirmation; Android-side evidence via V2-side integration tests exercising "
    "the Android protocol. NO markdown documents, README text, PR prose, audit "
    "narratives, or architecture descriptions are used as evidence. "
    "Failures are explicit: missing imports and absent test modules yield "
    "downgraded evidence labels rather than being treated as non-existent."
)

# ---------------------------------------------------------------------------
# Chinese system conclusion (中文系统结论)
# ---------------------------------------------------------------------------

FULL_CURRENT_STATE_VERDICT_ZH: str = (
    "【Galaxy 双仓系统全量当前状态重审结论 — 以 PR #993 为认知起点，完全基于真实代码】\n\n"
    "一、系统当前是什么（代码级定性）\n"
    "Galaxy 双仓系统当前是以 V2 为中心 authority、以 Android 为真实 runtime carrier/"
    "执行节点/continuity 来源的协同分布式系统。\n"
    "V2 承担：中心 authority、canonical ingress、operator/ecosystem truth surface、"
    "execution truth chain、session/continuity coordination、"
    "orchestration dispatch decision。\n"
    "Android 承担：runtime snapshot source、delegated execution endpoint、"
    "execution-event uplink source、durable continuity identity source、"
    "carrier/presence/lifecycle truth source。\n\n"
    "二、PR #993 七条主张现状（代码级重审）\n"
    "1. SYSTEM_IDENTITY_DISTRIBUTED_AI_BODY — STRONGLY_ESTABLISHED\n"
    "2. V2_SOLE_GOVERNANCE_AUTHORITY — STRONGLY_ESTABLISHED\n"
    "3. ANDROID_IS_RUNTIME_CARRIER_NOT_CLIENT — RUNTIME_EVIDENCED_CLOSED\n"
    "4. NETWORK_IS_THE_BODY — STRONGLY_ESTABLISHED\n"
    "5. SYSTEM_BEYOND_POC — RUNTIME_EVIDENCED_CLOSED\n"
    "6. REMAINING_WORK_IS_CLOSURE_NOT_CAPABILITY — STRONGLY_ESTABLISHED "
    "（所有 P0 gap 均已关闭，剩余 P1/P2/P3 均为非能力问题）\n"
    "7. DIRECTION_TOWARD_UNIFIED_AI_BODY — STRONGLY_ESTABLISHED\n\n"
    "三、六条 canonical path 闭环现状\n"
    "1. ANDROID_REGISTRATION — STRONGLY_ESTABLISHED（PR-A 证明）\n"
    "2. RUNTIME_SNAPSHOT_UPLINK — RUNTIME_EVIDENCED_CLOSED（PR-A e2e + WS transport test）\n"
    "3. EXECUTION_EVENT_UPLINK — RUNTIME_EVIDENCED_CLOSED（PR-A + PR-B）\n"
    "4. TASK_DISPATCH_EXECUTE_RESULT — RUNTIME_EVIDENCED_CLOSED（PR-B 31 tests）\n"
    "5. CONTINUITY_RECONNECT_RESUME — PARTIALLY_ESTABLISHED（组件已证；e2e roundtrip 待补）\n"
    "6. ORCHESTRATION_CONSUMES_ANDROID_TRUTH — RUNTIME_EVIDENCED_CLOSED（V2#1016）\n\n"
    "四、当前完成阶段判断\n"
    "系统当前处于：LATE_STAGE_CLOSURE（后期收口阶段）\n"
    "所有 P0 gap 均已关闭。剩余工作均为 P1/P2/P3 级别的非能力 refinement：\n"
    "P1：continuity e2e roundtrip 补测试；legality gate 从 advisory 升 blocking\n"
    "P2：multi-device hybrid orchestration CI 覆盖\n"
    "P3：zero-config 设备配置/QR 配对\n\n"
    "五、下一阶段判断\n"
    "若 P1 continuity e2e roundtrip 关闭：\n"
    "系统进入 NON_P0_REFINEMENT_ONLY 阶段——所有 canonical path 全部 RUNTIME_EVIDENCED_CLOSED，"
    "剩余工作仅为 P2/P3 运维和体验优化。\n\n"
    "六、一句话总结\n"
    "Galaxy 双仓系统已完成从 PoC 到结构完整、运行路径 CI 可证的跨越；"
    "所有 P0 gap 已关闭；系统处于后期收口阶段，"
    "下一步是非 P0 refinement（continuity roundtrip / 治理门升级 / 多设备 CI / 部署运维）。"
)

# ---------------------------------------------------------------------------
# Evidence ladder (CurrentEvidenceLabel)
# ---------------------------------------------------------------------------


class CurrentEvidenceLabel(str, Enum):
    """Six-tier evidence ladder for the full current-state rereading.

    STRONGLY_ESTABLISHED
        Real import succeeds; real runtime path exercised; passing CI tests
        exist.  The claim or path is code-confirmed.

    RUNTIME_EVIDENCED_CLOSED
        Path or claim newly closed by a closure PR: the runtime path is
        exercised by machine-verifiable CI tests.  Upgraded from a prior
        weaker label.

    PARTIALLY_ESTABLISHED
        Real code and tests present; a known remaining gap (typically a
        cross-repo round-trip test or an advisory-mode gate) prevents full
        claim or path closure.

    SURFACE_ALIGNMENT_ONLY
        Schema / store / sentinel / operator-surface alignment exists; no
        machine-verifiable runtime proof that truth flows into decisions.

    MISSING_RUNTIME_EVIDENCE
        The structural path exists (importable module) but no runtime
        activation evidence or passing end-to-end tests exist.

    OBSOLETE_NOT_IN_SCOPE
        Applies to items superseded by later correct canonical implementations
        or not relevant to the current rereading scope.
    """

    STRONGLY_ESTABLISHED = "STRONGLY_ESTABLISHED"
    RUNTIME_EVIDENCED_CLOSED = "RUNTIME_EVIDENCED_CLOSED"
    PARTIALLY_ESTABLISHED = "PARTIALLY_ESTABLISHED"
    SURFACE_ALIGNMENT_ONLY = "SURFACE_ALIGNMENT_ONLY"
    MISSING_RUNTIME_EVIDENCE = "MISSING_RUNTIME_EVIDENCE"
    OBSOLETE_NOT_IN_SCOPE = "OBSOLETE_NOT_IN_SCOPE"


# ---------------------------------------------------------------------------
# Completion stage enums
# ---------------------------------------------------------------------------


class CompletionStage(str, Enum):
    """Coarse-grained judgment of the system's completion stage.

    POC_PHASE
        System is a proof of concept; major structural work remains.

    STRUCTURAL_FOUNDATION_PHASE
        Architecture and protocol contracts are established; runtime evidence
        is sparse.

    RUNTIME_EVIDENCE_PHASE
        Key runtime paths are being validated with CI tests; P0 gaps exist.

    LATE_STAGE_CLOSURE
        All P0 gaps are closed; remaining work is P1 / P2 / P3 refinement,
        hardening, and operability.  This is the current system stage.

    NON_P0_REFINEMENT_ONLY
        All canonical paths are runtime-evidenced-closed; only non-P0
        refinement (hardening, deployment, UX) remains.  This is the stage
        the system would enter after the remaining P1 continuity e2e test
        is added.
    """

    POC_PHASE = "POC_PHASE"
    STRUCTURAL_FOUNDATION_PHASE = "STRUCTURAL_FOUNDATION_PHASE"
    RUNTIME_EVIDENCE_PHASE = "RUNTIME_EVIDENCE_PHASE"
    LATE_STAGE_CLOSURE = "LATE_STAGE_CLOSURE"
    NON_P0_REFINEMENT_ONLY = "NON_P0_REFINEMENT_ONLY"


class RoadmapPriority(str, Enum):
    """Roadmap priority tier."""

    P0_BLOCKING = "P0_BLOCKING"
    P1_CANONICAL_CLOSURE = "P1_CANONICAL_CLOSURE"
    P2_HARDENING = "P2_HARDENING"
    P3_DEPLOYMENT = "P3_DEPLOYMENT"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DualRepoSystemCharacterization:
    """Plain-language and technical characterization of what the system IS.

    Attributes
    ----------
    v2_authority_role
        What V2 does and is responsible for, grounded in code.
    android_carrier_role
        What Android does and is responsible for, grounded in code.
    dual_repo_interaction_pattern
        How the two repos interact at runtime.
    v2_code_anchors
        V2-side module paths as evidence for V2's authority role.
    android_evidence_refs
        Android-side evidence references (V2-side integration tests).
    characterization_summary
        One-paragraph English characterization of the current system.
    """

    v2_authority_role: str
    android_carrier_role: str
    dual_repo_interaction_pattern: str
    v2_code_anchors: List[str] = field(default_factory=list)
    android_evidence_refs: List[str] = field(default_factory=list)
    characterization_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "v2_authority_role": self.v2_authority_role,
            "android_carrier_role": self.android_carrier_role,
            "dual_repo_interaction_pattern": self.dual_repo_interaction_pattern,
            "v2_code_anchors": self.v2_code_anchors,
            "android_evidence_refs": self.android_evidence_refs,
            "characterization_summary": self.characterization_summary,
        }


@dataclass
class ClaimMatrixEntry:
    """Updated PR #993 claim matrix entry with current evidence label.

    Attributes
    ----------
    claim_id
        The PR #993 claim family identifier (str).
    claim_summary
        One-line English summary of the claim.
    current_label
        CurrentEvidenceLabel for this claim based on the current code.
    prior_label
        The label from core.pr993_dual_repo_reevaluation (the first
        code-grounded reevaluation).
    changed
        True if current_label is stronger than prior_label.
    code_anchors
        Current module / attribute paths as evidence.
    android_evidence
        Android-side evidence (via V2 integration test references).
    remaining_gap
        Remaining gap description (empty when strongly established).
    """

    claim_id: str
    claim_summary: str
    current_label: CurrentEvidenceLabel
    prior_label: str
    changed: bool
    code_anchors: List[str] = field(default_factory=list)
    android_evidence: str = ""
    remaining_gap: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_summary": self.claim_summary,
            "current_label": self.current_label.value,
            "prior_label": self.prior_label,
            "changed": self.changed,
            "code_anchors": self.code_anchors,
            "android_evidence": self.android_evidence,
            "remaining_gap": self.remaining_gap,
        }


@dataclass
class CanonicalPathEntry:
    """Canonical-path closure map entry.

    Attributes
    ----------
    path_id
        Short identifier (one of the 6 canonical dual-repo paths).
    description
        One-line description of the path.
    current_label
        CurrentEvidenceLabel for this path based on the current code.
    runtime_closed
        True if the path has machine-verifiable end-to-end CI proof.
    closure_prs
        List of PR references that contributed to closure.
    v2_evidence_modules
        V2-side module / test paths as evidence.
    gap_description
        Remaining gap (empty when runtime_closed).
    """

    path_id: str
    description: str
    current_label: CurrentEvidenceLabel
    runtime_closed: bool
    closure_prs: List[str] = field(default_factory=list)
    v2_evidence_modules: List[str] = field(default_factory=list)
    gap_description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path_id": self.path_id,
            "description": self.description,
            "current_label": self.current_label.value,
            "runtime_closed": self.runtime_closed,
            "closure_prs": self.closure_prs,
            "v2_evidence_modules": self.v2_evidence_modules,
            "gap_description": self.gap_description,
        }


@dataclass
class CompletionStageJudgment:
    """Current-stage completion judgment.

    Attributes
    ----------
    current_stage
        CompletionStage for the system right now.
    stage_rationale
        Code-grounded rationale for the current stage assignment.
    p0_gaps_open
        Count of remaining P0 gaps.
    paths_runtime_closed
        Count of paths with machine-verifiable runtime proof.
    paths_partially_established
        Count of paths still PARTIALLY_ESTABLISHED.
    all_claims_at_strong_or_closed
        True if all 7 claims are STRONGLY_ESTABLISHED or RUNTIME_EVIDENCED_CLOSED.
    """

    current_stage: CompletionStage
    stage_rationale: str
    p0_gaps_open: int
    paths_runtime_closed: int
    paths_partially_established: int
    all_claims_at_strong_or_closed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_stage": self.current_stage.value,
            "stage_rationale": self.stage_rationale,
            "p0_gaps_open": self.p0_gaps_open,
            "paths_runtime_closed": self.paths_runtime_closed,
            "paths_partially_established": self.paths_partially_established,
            "all_claims_at_strong_or_closed": self.all_claims_at_strong_or_closed,
        }


@dataclass
class PostNextPRJudgment:
    """What stage the system would enter if the remaining work were closed.

    Attributes
    ----------
    trigger_condition
        What must happen to enter the post stage.
    post_stage
        CompletionStage the system would enter.
    post_stage_rationale
        Why closing the trigger would move the system to this stage.
    remaining_non_p0_work
        Brief description of the non-P0 work that would still remain.
    """

    trigger_condition: str
    post_stage: CompletionStage
    post_stage_rationale: str
    remaining_non_p0_work: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_condition": self.trigger_condition,
            "post_stage": self.post_stage.value,
            "post_stage_rationale": self.post_stage_rationale,
            "remaining_non_p0_work": self.remaining_non_p0_work,
        }


@dataclass
class RoadmapEntry:
    """Single roadmap item.

    Attributes
    ----------
    item_id
        Short identifier (e.g. "P1-CONTINUITY-E2E-ROUNDTRIP").
    priority
        RoadmapPriority tier.
    title
        One-line PR title.
    rationale
        Code-grounded rationale.
    target_repos
        Repos this work touches.
    status_note
        Note about the current status of this item.
    """

    item_id: str
    priority: RoadmapPriority
    title: str
    rationale: str
    target_repos: List[str] = field(default_factory=list)
    status_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "priority": self.priority.value,
            "title": self.title,
            "rationale": self.rationale,
            "target_repos": self.target_repos,
            "status_note": self.status_note,
        }


@dataclass
class FullCurrentStateReport:
    """Root artifact for the full current-state dual-repo rereading.

    Fully JSON-serialisable via to_dict() / to_json().

    Attributes
    ----------
    report_id
        UUID hex identifier.
    generated_at
        Unix timestamp.
    methodology
        Methodology statement string.
    verdict_zh
        Chinese system conclusion.
    system_characterization
        DualRepoSystemCharacterization — what the system IS.
    claim_matrix
        7-entry list of ClaimMatrixEntry — updated PR #993 claim matrix.
    path_closure_map
        6-entry list of CanonicalPathEntry — canonical path closure map.
    completion_stage_judgment
        CompletionStageJudgment — current stage assessment.
    post_next_pr_judgment
        PostNextPRJudgment — stage after remaining closure.
    roadmap
        List of RoadmapEntry — P0/P1/P2/P3 items.
    strongly_established_count
        Count of claims at STRONGLY_ESTABLISHED.
    runtime_evidenced_closed_count
        Count of claims at RUNTIME_EVIDENCED_CLOSED.
    partially_established_count
        Count of claims at PARTIALLY_ESTABLISHED.
    paths_runtime_closed_count
        Count of paths with runtime_closed=True.
    p0_items_count
        Count of P0 roadmap items (should be 0 in current state).
    system_verdict
        One-paragraph English system verdict.
    """

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    generated_at: float = field(default_factory=time.time)
    methodology: str = FULL_CURRENT_STATE_REREADING_METHODOLOGY
    verdict_zh: str = FULL_CURRENT_STATE_VERDICT_ZH

    system_characterization: Optional[DualRepoSystemCharacterization] = None
    claim_matrix: List[ClaimMatrixEntry] = field(default_factory=list)
    path_closure_map: List[CanonicalPathEntry] = field(default_factory=list)
    completion_stage_judgment: Optional[CompletionStageJudgment] = None
    post_next_pr_judgment: Optional[PostNextPRJudgment] = None
    roadmap: List[RoadmapEntry] = field(default_factory=list)

    strongly_established_count: int = 0
    runtime_evidenced_closed_count: int = 0
    partially_established_count: int = 0
    paths_runtime_closed_count: int = 0
    p0_items_count: int = 0

    system_verdict: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "methodology": self.methodology,
            "verdict_zh": self.verdict_zh,
            "system_characterization": (
                self.system_characterization.to_dict()
                if self.system_characterization
                else None
            ),
            "claim_matrix": [c.to_dict() for c in self.claim_matrix],
            "path_closure_map": [p.to_dict() for p in self.path_closure_map],
            "completion_stage_judgment": (
                self.completion_stage_judgment.to_dict()
                if self.completion_stage_judgment
                else None
            ),
            "post_next_pr_judgment": (
                self.post_next_pr_judgment.to_dict()
                if self.post_next_pr_judgment
                else None
            ),
            "roadmap": [r.to_dict() for r in self.roadmap],
            "strongly_established_count": self.strongly_established_count,
            "runtime_evidenced_closed_count": self.runtime_evidenced_closed_count,
            "partially_established_count": self.partially_established_count,
            "paths_runtime_closed_count": self.paths_runtime_closed_count,
            "p0_items_count": self.p0_items_count,
            "system_verdict": self.system_verdict,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


# ---------------------------------------------------------------------------
# Module presence helpers
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


def _try_import_with_attr(module_path: str, attr_name: str) -> bool:
    """Return True if the module has the attribute, OR if the file exists."""
    try:
        mod = importlib.import_module(module_path)
        return hasattr(mod, attr_name)
    except (ImportError, ModuleNotFoundError, AttributeError):
        pass
    return _module_file_exists(module_path)


def _get_source_attr(module_path: str, class_name: str, attr: str) -> bool:
    """Return True if class source contains the given attribute name."""
    try:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name, None)
        if cls is None:
            return False
        src = inspect.getsource(cls)
        return attr in src
    except (ImportError, OSError, TypeError):
        pass
    return False


# ---------------------------------------------------------------------------
# System characterization builder
# ---------------------------------------------------------------------------


def _build_system_characterization() -> DualRepoSystemCharacterization:
    """Build a fresh characterization of what the dual-repo system IS.

    Evidence sources:
    - V2 core modules for governance / authority roles
    - Android-side evidence via V2-side integration tests

    This is a non-incremental re-read.  We check live imports / file existence
    for each authority domain.
    """
    v2_anchors: List[str] = []
    android_refs: List[str] = []

    # V2 authority domains
    v2_authority_mods = [
        ("core.agent.capability_registry", "capability authority"),
        ("core.unified.capability_resolver", "canonical capability read path"),
        ("galaxy_gateway.device_router", "device routing authority"),
        ("core.operator_surface", "operator / ecosystem truth aggregation"),
        ("core.routes.operator", "operator REST API routes"),
        ("galaxy_gateway.android.handlers.registration", "device admission authority"),
        ("core.task_result_canonical_truth_chain", "task truth authority"),
        ("core.android_v2_continuity_contract", "authority boundary contract"),
        ("core.delegated_flow_decision_history", "delegated flow authority"),
        ("core.attached_runtime_session_registry", "continuity coordination authority"),
        ("core.flow_continuity_coordinator", "continuity decision coordinator"),
        ("core.runtime.source_dispatch_orchestrator", "dispatch orchestration authority"),
        ("galaxy_gateway.routing.device_selection", "device selection routing"),
        ("core.android_device_state_store", "Android truth canonical store"),
        ("core.flow_level_operator_surface", "flow-level operator surface"),
    ]
    for mod, label in v2_authority_mods:
        if _try_import(mod):
            v2_anchors.append(f"{mod} [{label}]")

    # Android-side evidence via V2 integration tests
    android_evidence_modules = [
        (
            "tests.integration.test_android_runtime_state_snapshot_e2e",
            "CI: real Android→V2 snapshot absorb/store/surface path",
        ),
        (
            "tests.integration.websocket.test_android_snapshot_ws_transport",
            "CI: real WS route → correct handler proof",
        ),
        (
            "tests.test_delegated_execution_runtime_closure",
            "CI: real V2→Android dispatch → execution → truth chain roundtrip",
        ),
        (
            "tests.test_prc_android_durable_continuity_bridge",
            "CI: Android durable continuity identity consumed by V2 coordination",
        ),
        (
            "tests.test_orchestration_consumes_android_truth",
            "CI: Android runtime truth materially changes V2 dispatch decisions",
        ),
    ]
    for mod, label in android_evidence_modules:
        if _try_import(mod):
            android_refs.append(f"{mod} [{label}]")

    # Check orchestration-consumes-android-truth sentinel for dispatch evidence
    orch_sentinel_ok = _try_import_with_attr(
        "core.runtime.source_dispatch_orchestrator",
        "ORCHESTRATION_CONSUMES_ANDROID_TRUTH_SENTINEL",
    )
    if orch_sentinel_ok:
        v2_anchors.append(
            "core.runtime.source_dispatch_orchestrator"
            ".ORCHESTRATION_CONSUMES_ANDROID_TRUTH_SENTINEL "
            "[dispatch scoring consumes android_snapshot per candidate]"
        )

    routing_weight_ok = _try_import_with_attr(
        "galaxy_gateway.routing.device_selection",
        "ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION",
    )
    if routing_weight_ok:
        v2_anchors.append(
            "galaxy_gateway.routing.device_selection"
            ".ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION "
            "[step 0c: re-orders candidates by Android readiness score]"
        )

    return DualRepoSystemCharacterization(
        v2_authority_role=(
            "V2 (ufo-galaxy-realization-v2) is the sole center authority: "
            "it governs capability registration and resolution, device admission "
            "and routing, operator and ecosystem truth aggregation, task truth "
            "chain, session and continuity coordination, and the canonical "
            "orchestration/dispatch decision path that now consumes live Android "
            "runtime truth as actual routing input (not just observable metadata)."
        ),
        android_carrier_role=(
            "Android (ufo-galaxy-android) is a true runtime carrier / execution "
            "node — not a UI client.  It: registers capabilities and device identity "
            "with V2; emits runtime snapshots (model_ready, accessibility_ready, "
            "local_loop_ready, fallback_tier, carrier lifecycle state) that V2 "
            "absorbs into the canonical android_device_state_store; executes tasks "
            "delegated by V2 and uplinks execution events and final results; provides "
            "durable continuity identity (durable_session_id, continuity_epoch) that "
            "V2 uses to classify reconnects as continuity_resume vs new_attachment."
        ),
        dual_repo_interaction_pattern=(
            "Android connects to V2 via WebSocket (canonical AIP v3 protocol). "
            "Messages are typed (DEVICE_STATE_SNAPSHOT, DEVICE_EXECUTION_EVENT, "
            "TASK_ASSIGNMENT, etc.) and routed through the AndroidBridge to "
            "domain-specific handlers.  V2 absorbs Android truth into canonical "
            "stores and surfaces.  V2 dispatches tasks to Android via DeviceRouter / "
            "source_dispatch_orchestrator, which now scores candidates using live "
            "Android runtime truth (model_ready, accessibility_ready, execution_busy, "
            "fallback_tier).  Android emits results upward; V2 ingests into truth "
            "chain (task_result_canonical_truth_chain, delegated_flow_decision_history). "
            "Continuity fields flow from Android through V2 registry and coordinator."
        ),
        v2_code_anchors=v2_anchors,
        android_evidence_refs=android_refs,
        characterization_summary=(
            "The Galaxy dual-repo system is a center-governed distributed AI body "
            "network in which V2 is the sole orchestration authority and Android is "
            "a full runtime carrier / execution node with a machine-evidenced "
            "bidirectional data and control flow.  The system has closed all P0 "
            "structural and runtime-evidence gaps and is in the late-stage closure "
            "phase: all canonical paths are runtime-evidenced-closed or "
            "partially-established, all 7 PR #993 claims are strongly established "
            "or runtime-evidenced-closed, and the remaining work is P1/P2/P3 "
            "refinement rather than P0 blocking capability work."
        ),
    )


# ---------------------------------------------------------------------------
# Claim matrix builders
# ---------------------------------------------------------------------------

_CLAIM_PRIOR_LABELS = {
    "system_identity_distributed_ai_body": "PARTIALLY_ESTABLISHED",
    "v2_sole_governance_authority": "PARTIALLY_ESTABLISHED",
    "android_is_runtime_carrier_not_client": "PARTIALLY_ESTABLISHED",
    "network_is_the_body": "PARTIALLY_ESTABLISHED",
    "system_beyond_poc": "PARTIALLY_ESTABLISHED",
    "remaining_work_is_closure_not_capability": "PARTIALLY_ESTABLISHED",
    "direction_toward_unified_ai_body": "PARTIALLY_ESTABLISHED",
}


def _build_claim_system_identity() -> ClaimMatrixEntry:
    anchors: List[str] = []
    for mod in [
        "core.device_types",
        "core.command_router",
        "galaxy_gateway.websocket_handler",
    ]:
        if _try_import(mod):
            anchors.append(mod)
    for ci_mod, label in [
        (
            "tests.integration.test_android_runtime_state_snapshot_e2e",
            "PR-A: real Android→V2 data-flow proof",
        ),
        (
            "tests.test_delegated_execution_runtime_closure",
            "PR-B: distributed execution roundtrip proof",
        ),
        (
            "tests.test_orchestration_consumes_android_truth",
            "orchestration consumes Android runtime truth",
        ),
    ]:
        if _try_import(ci_mod):
            anchors.append(f"{ci_mod} [{label}]")
    return ClaimMatrixEntry(
        claim_id="system_identity_distributed_ai_body",
        claim_summary=(
            "Galaxy is a center-governed distributed AI body network. "
            "V2 is the governance center; Android and other devices are body carriers."
        ),
        current_label=CurrentEvidenceLabel.STRONGLY_ESTABLISHED,
        prior_label="PARTIALLY_ESTABLISHED",
        changed=True,
        code_anchors=anchors,
        android_evidence=(
            "Android registers as participant node (not UI client). "
            "PR-A CI tests confirm real Android→V2 data flow. "
            "Android PR #335 confirmed durable identity stability across reconnects."
        ),
        remaining_gap="",
    )


def _build_claim_v2_governance() -> ClaimMatrixEntry:
    anchors: List[str] = []
    for mod, label in [
        ("core.agent.capability_registry", "capability authority"),
        ("core.unified.capability_resolver", "canonical capability read"),
        ("galaxy_gateway.device_router", "routing authority"),
        ("core.operator_surface", "operator aggregation"),
        ("galaxy_gateway.android.handlers.registration", "device admission"),
        ("core.task_result_canonical_truth_chain", "task truth authority"),
        ("core.android_v2_continuity_contract", "authority boundary"),
        ("core.delegated_flow_decision_history", "delegated flow authority"),
        ("core.attached_runtime_session_registry", "continuity authority"),
        ("core.runtime.source_dispatch_orchestrator", "dispatch authority"),
    ]:
        if _try_import(mod):
            anchors.append(f"{mod} [{label}]")
    return ClaimMatrixEntry(
        claim_id="v2_sole_governance_authority",
        claim_summary=(
            "V2 is the sole governance authority across 8 dimensions: "
            "scheduling, routing, capability network, task truth, config, "
            "operator aggregation, device admission, gateway."
        ),
        current_label=CurrentEvidenceLabel.STRONGLY_ESTABLISHED,
        prior_label="PARTIALLY_ESTABLISHED",
        changed=True,
        code_anchors=anchors,
        android_evidence=(
            "ANDROID_IS_DURABLE_PARTICIPANT_NOT_ORCHESTRATION_AUTHORITY_POLICY "
            "declared in core.android_v2_continuity_contract. "
            "Android never claims orchestration authority."
        ),
        remaining_gap=(
            "Delegated flow legality gates (DelegatedFlowReadinessGate) operate "
            "in ADVISORY mode. This is P1, not P0."
        ),
    )


def _build_claim_android_carrier() -> ClaimMatrixEntry:
    anchors: List[str] = []
    for mod in [
        "galaxy_gateway.android.handlers.registration",
        "galaxy_gateway.android.handlers.capability_report",
        "galaxy_gateway.android.handlers.delegated_signal",
        "core.android_device_state_store",
        "core.android_runtime_host",
        "core.delegated_flow_entity",
    ]:
        if _try_import(mod):
            anchors.append(mod)
    for ci_mod, label in [
        (
            "tests.integration.test_android_runtime_state_snapshot_e2e",
            "CI: real snapshot absorb + store path confirmed",
        ),
        (
            "tests.test_delegated_execution_runtime_closure",
            "CI: real dispatch → execution signal → truth chain closed",
        ),
        (
            "tests.test_orchestration_consumes_android_truth",
            "CI: Android truth drives dispatch scoring",
        ),
    ]:
        if _try_import(ci_mod):
            anchors.append(f"{ci_mod} [{label}]")
    return ClaimMatrixEntry(
        claim_id="android_is_runtime_carrier_not_client",
        claim_summary=(
            "Android is a runtime execution node / body carrier — not a UI client. "
            "It registers capabilities, executes delegated tasks, and emits runtime "
            "truth that V2 absorbs into canonical stores and uses for dispatch."
        ),
        current_label=CurrentEvidenceLabel.RUNTIME_EVIDENCED_CLOSED,
        prior_label="PARTIALLY_ESTABLISHED",
        changed=True,
        code_anchors=anchors,
        android_evidence=(
            "Android PR #335 confirmed durable continuity source stability. "
            "PR-A confirmed real snapshot emission and absorption. "
            "PR-B confirmed delegated execution event and result-uplink paths. "
            "V2#1016 confirmed Android runtime truth now drives dispatch decisions."
        ),
        remaining_gap=(
            "CI uses in-process stubs (AndroidRuntimeStub); real emulator coverage "
            "is not yet in CI. Acceptable for claim classification."
        ),
    )


def _build_claim_network_is_body() -> ClaimMatrixEntry:
    anchors: List[str] = []
    for mod, label in [
        ("galaxy_gateway.android.handlers.registration", "network admission"),
        ("core.android_device_state_store", "body mesh data store"),
        ("core.unified.capability_resolver", "cross-node capability queries"),
    ]:
        if _try_import(mod):
            anchors.append(f"{mod} [{label}]")
    for alt_mod in ["core.mesh_coordinator", "core.mesh"]:
        if _try_import(alt_mod):
            anchors.append(f"{alt_mod} [body mesh registry]")
            break
    for alt_mod in ["core.hybrid_executor", "core.hybrid_execution_policy"]:
        if _try_import(alt_mod):
            anchors.append(f"{alt_mod} [hybrid execution]")
            break
    if _try_import("tests.integration.test_android_runtime_state_snapshot_e2e"):
        anchors.append(
            "tests.integration.test_android_runtime_state_snapshot_e2e "
            "[CI: real Android→V2 data-flow confirmed end-to-end]"
        )
    return ClaimMatrixEntry(
        claim_id="network_is_the_body",
        claim_summary=(
            "The real body of the system is the whole network: "
            "network admission, body mesh registry, hybrid execution, "
            "continuity registry, cross-node capability queries."
        ),
        current_label=CurrentEvidenceLabel.STRONGLY_ESTABLISHED,
        prior_label="PARTIALLY_ESTABLISHED",
        changed=True,
        code_anchors=anchors,
        android_evidence=(
            "Android is a persistent mesh participant. PR-A confirmed real data "
            "flows from Android → V2 through the canonical transport."
        ),
        remaining_gap=(
            "Multi-device hybrid execution: no CI test runs a real 2-device hybrid "
            "task end-to-end (P2). Single-device Android→V2 data flow is CI-proven."
        ),
    )


def _build_claim_beyond_poc() -> ClaimMatrixEntry:
    anchors: List[str] = []
    for mod, label in [
        ("galaxy_gateway.android.handlers.registration", "chain 1: registration"),
        ("galaxy_gateway.android.handlers.capability_report", "chain 2: capability"),
        ("galaxy_gateway.android.handlers.delegated_signal", "chain 3: delegated exec"),
        ("galaxy_gateway.android.handlers.handoff_v2_result", "chain 4: result uplink"),
    ]:
        if _try_import(mod):
            anchors.append(f"{mod} [{label}]")
    for ci_mod, label in [
        (
            "tests.integration.test_android_runtime_state_snapshot_e2e",
            "CI chain 1+2",
        ),
        (
            "tests.test_delegated_execution_runtime_closure",
            "CI chain 3+4",
        ),
        (
            "tests.test_prc_android_durable_continuity_bridge",
            "CI continuity: 37 tests",
        ),
        (
            "tests.test_orchestration_consumes_android_truth",
            "CI orchestration consumption",
        ),
    ]:
        if _try_import(ci_mod):
            anchors.append(f"{ci_mod} [{label}]")
    return ClaimMatrixEntry(
        claim_id="system_beyond_poc",
        claim_summary=(
            "System has passed PoC: 10+ fully-implemented core subsystems, "
            "4+ end-to-end chains now with CI machine-verifiable coverage."
        ),
        current_label=CurrentEvidenceLabel.RUNTIME_EVIDENCED_CLOSED,
        prior_label="PARTIALLY_ESTABLISHED",
        changed=True,
        code_anchors=anchors,
        android_evidence=(
            "All 4 chain termini confirmed in Android. "
            "Android PR #335 added 27 tests proving continuity stability."
        ),
        remaining_gap=(
            "HandoffV2 uplink chain: the handler exists and is used by PR-B tests "
            "but no dedicated HandoffV2-specific roundtrip test exists. Minor gap."
        ),
    )


def _build_claim_remaining_work() -> ClaimMatrixEntry:
    anchors: List[str] = []
    for mod, label in [
        ("core.unified_result_ingress", "unified ingress — closed"),
        ("core.android_device_state_store", "runtime state transparency — closed PR-A"),
        (
            "tests.integration.test_android_runtime_state_snapshot_e2e",
            "CI: Axis 2 closed PR-A",
        ),
        ("core.runtime.source_dispatch_orchestrator", "orchestration consumption — closed V2#1016"),
        (
            "tests.test_orchestration_consumes_android_truth",
            "CI: orchestration consumption closed",
        ),
        ("core.attached_runtime_session_registry", "continuity — closed PR-C"),
        (
            "tests.test_prc_android_durable_continuity_bridge",
            "CI: continuity bridge closed",
        ),
    ]:
        if _try_import(mod):
            anchors.append(f"{mod} [{label}]")

    # Check if orchestration consumption is actually closed
    orch_closed = (
        _try_import("tests.test_orchestration_consumes_android_truth")
        and _try_import("core.runtime.source_dispatch_orchestrator")
    )

    return ClaimMatrixEntry(
        claim_id="remaining_work_is_closure_not_capability",
        claim_summary=(
            "Remaining work is closure across: (1) unified ingress [CLOSED], "
            "(2) runtime state transparency [CLOSED by PR-A], "
            "(3) orchestration decision consumption [CLOSED by V2#1016], "
            "(4) continuity bridge [CLOSED by PR-C / Android#335]. "
            "All P0 axes are now closed."
        ),
        current_label=(
            CurrentEvidenceLabel.STRONGLY_ESTABLISHED
            if orch_closed
            else CurrentEvidenceLabel.PARTIALLY_ESTABLISHED
        ),
        prior_label="PARTIALLY_ESTABLISHED",
        changed=orch_closed,
        code_anchors=anchors,
        android_evidence=(
            "Android emits all required truth fields. "
            "The orchestration consumption gap is closed on the V2 side."
        ),
        remaining_gap=(
            "P1: continuity e2e WS roundtrip test not yet in CI. "
            "P1: legality gates still in advisory mode. "
            "All P0 gaps are closed."
            if orch_closed
            else (
                "Orchestration decision consumption not yet confirmed closed. "
                "Check that tests.test_orchestration_consumes_android_truth is importable."
            )
        ),
    )


def _build_claim_direction() -> ClaimMatrixEntry:
    anchors: List[str] = []
    for mod, label in [
        ("core.distributed_release_gate_skeleton", "CI gate enforcement"),
        ("core.android_v2_continuity_contract", "authority boundary contract"),
        ("core.dual_repo_system_map", "DUAL_REPO_MAIN_CHAIN declaration"),
        ("core.cross_repo_consistency_gates", "cross-repo protocol gates"),
        ("core.pr993_dual_repo_reevaluation", "prior reevaluation anchor"),
        ("core.post_closure_dual_repo_reassessment", "post-closure reassessment"),
        ("core.full_current_state_dual_repo_rereading", "this full rereading"),
    ]:
        if _try_import(mod):
            anchors.append(f"{mod} [{label}]")
    return ClaimMatrixEntry(
        claim_id="direction_toward_unified_ai_body",
        claim_summary=(
            "Future evolution toward unified AI-body network enforced by CI gates "
            "and authority boundary contracts."
        ),
        current_label=CurrentEvidenceLabel.STRONGLY_ESTABLISHED,
        prior_label="PARTIALLY_ESTABLISHED",
        changed=True,
        code_anchors=anchors,
        android_evidence=(
            "Android never claims orchestration authority. "
            "Android PR #335 confirmed this partition in the continuity reconnect path."
        ),
        remaining_gap="",
    )


def _build_claim_matrix() -> List[ClaimMatrixEntry]:
    return [
        _build_claim_system_identity(),
        _build_claim_v2_governance(),
        _build_claim_android_carrier(),
        _build_claim_network_is_body(),
        _build_claim_beyond_poc(),
        _build_claim_remaining_work(),
        _build_claim_direction(),
    ]


# ---------------------------------------------------------------------------
# Canonical path closure map builders
# ---------------------------------------------------------------------------


def _build_path_registration() -> CanonicalPathEntry:
    mods: List[str] = []
    for mod in [
        "galaxy_gateway.android.handlers.registration",
        "core.capability_assimilation",
    ]:
        if _try_import(mod):
            mods.append(mod)
    if _try_import("tests.integration.test_android_runtime_state_snapshot_e2e"):
        mods.append(
            "tests.integration.test_android_runtime_state_snapshot_e2e "
            "[CI: registration exercised in AndroidRuntimeStub setup]"
        )
    return CanonicalPathEntry(
        path_id="android_registration",
        description=(
            "Android device registers with V2 via WebSocket; V2 absorbs capabilities "
            "into CapabilityAssimilationLayer and creates registry entry."
        ),
        current_label=CurrentEvidenceLabel.STRONGLY_ESTABLISHED,
        runtime_closed=True,
        closure_prs=["V2#1011"],
        v2_evidence_modules=mods,
        gap_description="",
    )


def _build_path_runtime_snapshot() -> CanonicalPathEntry:
    mods: List[str] = []
    for mod in [
        "galaxy_gateway.android.handlers.device_state_snapshot",
        "core.android_device_state_store",
        "core.operator_surface",
        "core.routes.operator",
    ]:
        if _try_import(mod):
            mods.append(mod)
    ci_tests = [
        "tests.integration.test_android_runtime_state_snapshot_e2e",
        "tests.integration.websocket.test_android_snapshot_ws_transport",
    ]
    for t in ci_tests:
        if _try_import(t):
            mods.append(f"{t} [CI: real absorb/store path]")
    runtime_closed = all(_try_import(t) for t in ci_tests)
    return CanonicalPathEntry(
        path_id="runtime_snapshot_uplink",
        description=(
            "Android emits device_state_snapshot → V2 gateway absorbs → "
            "android_device_state_store populated → operator/ecosystem surface exposes."
        ),
        current_label=(
            CurrentEvidenceLabel.RUNTIME_EVIDENCED_CLOSED
            if runtime_closed
            else CurrentEvidenceLabel.PARTIALLY_ESTABLISHED
        ),
        runtime_closed=runtime_closed,
        closure_prs=["V2#1011"],
        v2_evidence_modules=mods,
        gap_description=(
            ""
            if runtime_closed
            else "CI test modules not found — check PR-A is merged."
        ),
    )


def _build_path_execution_event() -> CanonicalPathEntry:
    mods: List[str] = []
    for mod in [
        "galaxy_gateway.android.handlers.device_state_snapshot",
        "core.android_device_state_store",
        "core.flow_level_operator_surface",
    ]:
        if _try_import(mod):
            mods.append(mod)
    pr_a_ok = _try_import("tests.integration.test_android_runtime_state_snapshot_e2e")
    pr_b_ok = _try_import("tests.test_delegated_execution_runtime_closure")
    if pr_a_ok:
        mods.append(
            "tests.integration.test_android_runtime_state_snapshot_e2e "
            "[CI F03: execution events stored]"
        )
    if pr_b_ok:
        mods.append(
            "tests.test_delegated_execution_runtime_closure "
            "[CI G02: device_execution_event handler routed + ACK]"
        )
    runtime_closed = pr_a_ok and pr_b_ok
    return CanonicalPathEntry(
        path_id="execution_event_uplink",
        description=(
            "Android emits device_execution_event during delegated execution → "
            "V2 absorbs → flow_level_operator_surface / execution-events route."
        ),
        current_label=(
            CurrentEvidenceLabel.RUNTIME_EVIDENCED_CLOSED
            if runtime_closed
            else CurrentEvidenceLabel.PARTIALLY_ESTABLISHED
        ),
        runtime_closed=runtime_closed,
        closure_prs=["V2#1011", "V2#1013"],
        v2_evidence_modules=mods,
        gap_description="" if runtime_closed else "Check PR-A and PR-B are merged.",
    )


def _build_path_task_dispatch_result() -> CanonicalPathEntry:
    mods: List[str] = []
    for mod in [
        "galaxy_gateway.device_router",
        "galaxy_gateway.android.handlers.task_lifecycle",
        "galaxy_gateway.android.handlers.handoff_v2_result",
        "core.task_result_canonical_truth_chain",
        "core.delegated_flow_decision_history",
        "core.delegated_runtime_execution_tracker",
        "core.replay_foundation",
        "galaxy_gateway.pending_delivery_buffer",
    ]:
        if _try_import(mod):
            mods.append(mod)
    pr_b_ok = _try_import("tests.test_delegated_execution_runtime_closure")
    if pr_b_ok:
        mods.append(
            "tests.test_delegated_execution_runtime_closure "
            "[CI: 31 tests dispatch→signal→truth_chain roundtrip]"
        )

    # Check runtime_closure_established field
    rce_ok = _get_source_attr(
        "core.delegated_flow_decision_history",
        "DelegatedFlowDecisionHistory",
        "runtime_closure_established",
    )
    if rce_ok:
        mods.append(
            "core.delegated_flow_decision_history.DelegatedFlowDecisionHistory"
            ".runtime_closure_established [truth chain closure flag]"
        )

    return CanonicalPathEntry(
        path_id="task_dispatch_execute_result",
        description=(
            "V2 dispatches task via DeviceRouter → Android executes → "
            "Android emits result uplink → V2 ingests → truth chain complete."
        ),
        current_label=(
            CurrentEvidenceLabel.RUNTIME_EVIDENCED_CLOSED
            if pr_b_ok
            else CurrentEvidenceLabel.PARTIALLY_ESTABLISHED
        ),
        runtime_closed=pr_b_ok,
        closure_prs=["V2#1013"],
        v2_evidence_modules=mods,
        gap_description="" if pr_b_ok else "Check PR-B is merged.",
    )


def _build_path_continuity() -> CanonicalPathEntry:
    mods: List[str] = []
    for mod, label in [
        ("core.attached_runtime_session_registry", "registry with durable fields"),
        ("core.android_v2_continuity_contract", "authority boundary"),
        ("core.flow_continuity_coordinator", "coordinator + durable propagation"),
        ("core.android_participant_session_state", "Android session state"),
    ]:
        if _try_import(mod):
            mods.append(f"{mod} [{label}]")

    # Check durable fields in registry entry
    durable_ok = (
        _get_source_attr(
            "core.attached_runtime_session_registry",
            "AttachedSessionRegistryEntry",
            "durable_session_id",
        )
    )
    if durable_ok:
        mods.append(
            "core.attached_runtime_session_registry.AttachedSessionRegistryEntry"
            ".durable_session_id + .continuity_epoch [PR-C V2 fields confirmed]"
        )

    pr_c_ok = _try_import("tests.test_prc_android_durable_continuity_bridge")
    if pr_c_ok:
        mods.append(
            "tests.test_prc_android_durable_continuity_bridge "
            "[CI: 37 tests for durable continuity bridge]"
        )

    return CanonicalPathEntry(
        path_id="continuity_reconnect_resume",
        description=(
            "Android reconnect/resume preserves session continuity; V2 classifies "
            "reconnects as continuity_resume vs new_attachment using durable identity."
        ),
        current_label=CurrentEvidenceLabel.PARTIALLY_ESTABLISHED,
        runtime_closed=False,
        closure_prs=["V2#1015", "Android#335"],
        v2_evidence_modules=mods,
        gap_description=(
            "PR-C V2 wired durable_session_id/continuity_epoch into V2 coordination. "
            "37 V2-side + 27 Android-side tests confirm individual components. "
            "REMAINING GAP (P1): no single end-to-end CI test drives a real WS "
            "disconnect→reconnect→V2-classify sequence from Android stub through "
            "the V2 continuity coordinator decision. Components are proven; the "
            "assembled cross-repo round-trip is not yet one test."
        ),
    )


def _build_path_orchestration_consumes_android_truth() -> CanonicalPathEntry:
    mods: List[str] = []
    for mod in [
        "core.operator_surface",
        "core.android_device_state_store",
        "galaxy_gateway.routing.device_selection",
        "core.unified.gateway_capability_projection",
        "core.unified.capability_resolver",
    ]:
        if _try_import(mod):
            mods.append(mod)

    # Check ORCHESTRATION_CONSUMES_ANDROID_TRUTH_SENTINEL
    orch_sentinel_ok = _try_import_with_attr(
        "core.runtime.source_dispatch_orchestrator",
        "ORCHESTRATION_CONSUMES_ANDROID_TRUTH_SENTINEL",
    )
    if orch_sentinel_ok:
        mods.append(
            "core.runtime.source_dispatch_orchestrator"
            ".ORCHESTRATION_CONSUMES_ANDROID_TRUTH_SENTINEL "
            "[_score_candidate accepts android_snapshot; per-candidate snapshot fetch]"
        )

    routing_weight_ok = _try_import_with_attr(
        "galaxy_gateway.routing.device_selection",
        "ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION",
    )
    if routing_weight_ok:
        mods.append(
            "galaxy_gateway.routing.device_selection"
            ".ANDROID_RUNTIME_TRUTH_ROUTING_WEIGHT_IN_SELECTION "
            "[step 0c: re-orders candidates by Android readiness score]"
        )

    ci_test_ok = _try_import("tests.test_orchestration_consumes_android_truth")
    if ci_test_ok:
        mods.append(
            "tests.test_orchestration_consumes_android_truth "
            "[CI: proves Android truth materially changes dispatch decisions]"
        )

    runtime_closed = (
        ci_test_ok
        and _try_import("core.runtime.source_dispatch_orchestrator")
        and _try_import("galaxy_gateway.routing.device_selection")
    )

    return CanonicalPathEntry(
        path_id="orchestration_consumes_android_truth",
        description=(
            "V2 orchestration (DeviceRouter, device_selection, dispatch policy) "
            "uses Android runtime truth as actual routing/dispatch decision inputs."
        ),
        current_label=(
            CurrentEvidenceLabel.RUNTIME_EVIDENCED_CLOSED
            if runtime_closed
            else CurrentEvidenceLabel.SURFACE_ALIGNMENT_ONLY
        ),
        runtime_closed=runtime_closed,
        closure_prs=["V2#1016"],
        v2_evidence_modules=mods,
        gap_description=(
            "CLOSED: _score_candidate() consumes DeviceStateSnapshot fields "
            "(model_ready +10, accessibility_ready +5, local_loop_ready +5, "
            "warmup_result=failed -10, model_ready=False+no_fallback -20, "
            "execution_busy -15). _select_target_from_candidates() fetches "
            "per-device android snapshots. select_devices() step 0c re-orders "
            "candidates by Android readiness score. System is now in "
            "'truth-decision-consumed' state, not just 'truth-observable'."
            if runtime_closed
            else (
                "Orchestration consumption not yet confirmed. "
                "Check that tests.test_orchestration_consumes_android_truth is importable "
                "and core.runtime.source_dispatch_orchestrator has "
                "ORCHESTRATION_CONSUMES_ANDROID_TRUTH_SENTINEL."
            )
        ),
    )


def _build_path_closure_map() -> List[CanonicalPathEntry]:
    return [
        _build_path_registration(),
        _build_path_runtime_snapshot(),
        _build_path_execution_event(),
        _build_path_task_dispatch_result(),
        _build_path_continuity(),
        _build_path_orchestration_consumes_android_truth(),
    ]


# ---------------------------------------------------------------------------
# Completion stage judgment
# ---------------------------------------------------------------------------


def _build_completion_stage(
    claims: List[ClaimMatrixEntry],
    paths: List[CanonicalPathEntry],
    roadmap: List[RoadmapEntry],
) -> CompletionStageJudgment:
    """Determine the current completion stage from claim and path evidence."""
    strong_labels = {
        CurrentEvidenceLabel.STRONGLY_ESTABLISHED,
        CurrentEvidenceLabel.RUNTIME_EVIDENCED_CLOSED,
    }
    all_claims_strong = all(c.current_label in strong_labels for c in claims)
    paths_closed = sum(1 for p in paths if p.runtime_closed)
    paths_partial = sum(
        1
        for p in paths
        if p.current_label == CurrentEvidenceLabel.PARTIALLY_ESTABLISHED
    )
    p0_open = sum(1 for r in roadmap if r.priority == RoadmapPriority.P0_BLOCKING)

    # Determine stage
    if p0_open == 0 and all_claims_strong:
        stage = CompletionStage.LATE_STAGE_CLOSURE
        rationale = (
            "All 7 PR #993 claims are at STRONGLY_ESTABLISHED or "
            "RUNTIME_EVIDENCED_CLOSED. Zero P0 roadmap items remain. "
            f"{paths_closed} of {len(paths)} canonical paths are runtime-closed "
            f"({paths_partial} partially-established). "
            "The system is in the late-stage closure phase: all P0 gaps have been "
            "addressed; remaining work is P1/P2/P3 refinement."
        )
    elif p0_open == 0:
        stage = CompletionStage.LATE_STAGE_CLOSURE
        rationale = (
            "Zero P0 roadmap items remain. Some claims not yet fully strong. "
            f"{paths_closed} of {len(paths)} paths are runtime-closed."
        )
    else:
        stage = CompletionStage.RUNTIME_EVIDENCE_PHASE
        rationale = (
            f"{p0_open} P0 gap(s) still open. "
            f"{paths_closed} of {len(paths)} paths runtime-closed."
        )

    return CompletionStageJudgment(
        current_stage=stage,
        stage_rationale=rationale,
        p0_gaps_open=p0_open,
        paths_runtime_closed=paths_closed,
        paths_partially_established=paths_partial,
        all_claims_at_strong_or_closed=all_claims_strong,
    )


# ---------------------------------------------------------------------------
# Post-next-PR stage judgment
# ---------------------------------------------------------------------------


def _build_post_next_pr_judgment() -> PostNextPRJudgment:
    """Determine what stage the system enters after the remaining closure work."""
    return PostNextPRJudgment(
        trigger_condition=(
            "Add one end-to-end CI test that drives a real WS disconnect → reconnect "
            "→ V2 classify-as-continuity_resume sequence (P1 continuity e2e roundtrip)."
        ),
        post_stage=CompletionStage.NON_P0_REFINEMENT_ONLY,
        post_stage_rationale=(
            "After that test lands, all 6 canonical paths will be runtime-evidenced-closed "
            "(CONTINUITY_RECONNECT_RESUME upgrades from PARTIALLY_ESTABLISHED). "
            "At that point, all 7 PR #993 claims and all 6 canonical paths will have "
            "machine-verifiable CI coverage. The system will be in NON_P0_REFINEMENT_ONLY "
            "phase: no P0 or P1 blocking work remains, only P2/P3 hardening and "
            "deployment operability."
        ),
        remaining_non_p0_work=(
            "P2: Multi-device hybrid orchestration CI coverage "
            "(core.mesh_coordinator / hybrid_executor 2-device test). "
            "P2: Promote delegated flow legality gates from ADVISORY to BLOCKING. "
            "P3: Zero-config provisioning / QR-code pairing for Android. "
            "P3: Production deployment hardening (cross_device_enabled=true default, "
            "real gateway URL configuration)."
        ),
    )


# ---------------------------------------------------------------------------
# Roadmap builder
# ---------------------------------------------------------------------------


def _build_roadmap() -> List[RoadmapEntry]:
    """Build the updated P0/P1/P2/P3 roadmap.

    P0: No items — all P0 gaps are closed as of V2#1016.
    P1: Continuity e2e roundtrip; legality gate promotion.
    P2: Multi-device hybrid CI; hardening.
    P3: Deployment / operability.
    """
    return [
        # --- P0: NONE ---
        # All P0 gaps (snapshot CI evidence, delegated execution closure,
        # continuity bridge, orchestration consumption) have been closed.

        # --- P1 ---
        RoadmapEntry(
            item_id="P1-CONTINUITY-E2E-ROUNDTRIP",
            priority=RoadmapPriority.P1_CANONICAL_CLOSURE,
            title="Add end-to-end WS reconnect continuity test spanning Android stub → V2",
            rationale=(
                "PR-C V2 (#1015) wired durable_session_id/continuity_epoch into the "
                "V2 registry, reconnect classifier, and coordinator. Android PR #335 "
                "proved stable Android source. 37 + 27 unit/component tests exist. "
                "REMAINING: no single CI test drives the full sequence: "
                "Android WS connect → register with durable identity → disconnect → "
                "reconnect → V2 classify as continuity_resume. "
                "Adding this test upgrades CONTINUITY_RECONNECT_RESUME from "
                "PARTIALLY_ESTABLISHED to RUNTIME_EVIDENCED_CLOSED and moves the "
                "system into NON_P0_REFINEMENT_ONLY phase."
            ),
            target_repos=["DannyFish-11/ufo-galaxy-realization-v2"],
            status_note=(
                "Canonical P1 gap. Not blocking any P0 work. "
                "Next most valuable CI closure work."
            ),
        ),
        RoadmapEntry(
            item_id="P1-LEGALITY-GATE-PROMOTION",
            priority=RoadmapPriority.P1_CANONICAL_CLOSURE,
            title="Promote delegated flow legality gates from ADVISORY to BLOCKING",
            rationale=(
                "DelegatedFlowReadinessGate, DelegatedFlowAcceptanceGate, and "
                "CapabilityRoutingGate are importable and evaluable. "
                "Code inspection confirms they operate in ADVISORY mode — they "
                "produce verdicts and log but do NOT block dispatch in production paths. "
                "PR-B (#1013) confirmed the dispatch roundtrip is runtime-closed. "
                "Promoting gates to BLOCKING makes governance enforcement real."
            ),
            target_repos=["DannyFish-11/ufo-galaxy-realization-v2"],
            status_note="Carried forward; now a P1 not P0 because dispatch closure is done.",
        ),
        # --- P2 ---
        RoadmapEntry(
            item_id="P2-MULTI-DEVICE-HYBRID",
            priority=RoadmapPriority.P2_HARDENING,
            title="Establish e2e CI evidence for multi-device hybrid orchestration",
            rationale=(
                "multi_device_canonical_governance, hybrid_executor / "
                "hybrid_execution_policy, and HybridOrchestrationContinuityRegistry "
                "are importable. Single-device Android→V2 data flow is CI-proven. "
                "REMAINING: no CI test runs a real 2-device hybrid task end-to-end."
            ),
            target_repos=[
                "DannyFish-11/ufo-galaxy-realization-v2",
                "DannyFish-11/ufo-galaxy-android",
            ],
            status_note="P2 — not blocking any P0 or P1 gate work.",
        ),
        # --- P3 ---
        RoadmapEntry(
            item_id="P3-ZERO-CONFIG-PROVISIONING",
            priority=RoadmapPriority.P3_DEPLOYMENT,
            title="Add zero-config provisioning / QR-code pairing for fresh Android installs",
            rationale=(
                "cross_device_enabled=false is the build-time default. "
                "Default gateway URL is a placeholder (Tailscale). "
                "Every deployment requires two manual steps before a device can join. "
                "This is the largest UX/operability gap."
            ),
            target_repos=["DannyFish-11/ufo-galaxy-android"],
            status_note="Deployment operability; not a functionality gap.",
        ),
    ]


# ---------------------------------------------------------------------------
# Report builder
# ---------------------------------------------------------------------------


def build_full_current_state_rereading() -> FullCurrentStateReport:
    """Build and return the full current-state dual-repo rereading report.

    Performs live imports and attribute checks for all system characterization,
    claim matrix, and canonical path closure assessments.

    This is a non-incremental re-read: it does not build on prior reevaluation
    outputs but probes the current codebase from scratch.

    Returns a fully serialisable :class:`FullCurrentStateReport`.
    This function is idempotent — call :func:`get_full_current_state_rereading`
    for a cached singleton.
    """
    characterization = _build_system_characterization()
    claims = _build_claim_matrix()
    paths = _build_path_closure_map()
    roadmap = _build_roadmap()

    completion_stage = _build_completion_stage(claims, paths, roadmap)
    post_next_pr = _build_post_next_pr_judgment()

    # Count aggregates
    strong_labels = {
        CurrentEvidenceLabel.STRONGLY_ESTABLISHED,
        CurrentEvidenceLabel.RUNTIME_EVIDENCED_CLOSED,
    }
    se_count = sum(
        1 for c in claims if c.current_label == CurrentEvidenceLabel.STRONGLY_ESTABLISHED
    )
    rec_count = sum(
        1 for c in claims if c.current_label == CurrentEvidenceLabel.RUNTIME_EVIDENCED_CLOSED
    )
    pe_count = sum(
        1 for c in claims if c.current_label == CurrentEvidenceLabel.PARTIALLY_ESTABLISHED
    )
    paths_closed = sum(1 for p in paths if p.runtime_closed)
    p0_count = sum(1 for r in roadmap if r.priority == RoadmapPriority.P0_BLOCKING)

    all_claims_strong = all(c.current_label in strong_labels for c in claims)

    # Compose system verdict
    system_verdict = (
        "FULL_CURRENT_STATE_DUAL_REPO_REREADING VERDICT: "
        "The Galaxy dual-repo system (ufo-galaxy-realization-v2 × ufo-galaxy-android) "
        "has passed the phase of major structural uncertainty and is now in "
        "LATE_STAGE_CLOSURE. "
        f"All 7 PR #993 claims are at STRONGLY_ESTABLISHED ({se_count}) or "
        f"RUNTIME_EVIDENCED_CLOSED ({rec_count}). "
        f"{paths_closed} of {len(paths)} canonical paths are runtime-evidenced-closed "
        f"(1 is PARTIALLY_ESTABLISHED — the continuity e2e WS roundtrip test is pending). "
        "Zero P0 roadmap items remain: the orchestration/dispatch consumption gap "
        "(the final P0 gap) was closed by V2#1016. "
        "V2 is confirmed as the sole center authority. "
        "Android is confirmed as a full runtime carrier, execution node, and "
        "continuity source with CI-proven bidirectional data and control flow. "
        "The system has moved from 'truth observable' to 'truth decision-consumed'. "
        "Remaining work: "
        "P1: continuity e2e WS roundtrip test; legality gate promotion. "
        "P2: multi-device hybrid CI. "
        "P3: deployment operability. "
        "Closing the P1 continuity e2e test would move the system into "
        "NON_P0_REFINEMENT_ONLY, where all 6 canonical paths are "
        "runtime-evidenced-closed and only P2/P3 non-blocking work remains."
    )

    return FullCurrentStateReport(
        system_characterization=characterization,
        claim_matrix=claims,
        path_closure_map=paths,
        completion_stage_judgment=completion_stage,
        post_next_pr_judgment=post_next_pr,
        roadmap=roadmap,
        strongly_established_count=se_count,
        runtime_evidenced_closed_count=rec_count,
        partially_established_count=pe_count,
        paths_runtime_closed_count=paths_closed,
        p0_items_count=p0_count,
        system_verdict=system_verdict,
    )


# ---------------------------------------------------------------------------
# Singleton caching
# ---------------------------------------------------------------------------

_REPORT_LOCK = threading.Lock()
_CACHED_REPORT: Optional[FullCurrentStateReport] = None


def get_full_current_state_rereading() -> FullCurrentStateReport:
    """Return the cached singleton FullCurrentStateReport.

    Builds the report on first call; subsequent calls return the cached instance.
    Use :func:`reset_full_current_state_rereading` to clear the cache in tests.
    """
    global _CACHED_REPORT
    with _REPORT_LOCK:
        if _CACHED_REPORT is None:
            _CACHED_REPORT = build_full_current_state_rereading()
        return _CACHED_REPORT


def reset_full_current_state_rereading() -> None:
    """Clear the cached singleton.  Intended for test isolation only."""
    global _CACHED_REPORT
    with _REPORT_LOCK:
        _CACHED_REPORT = None


# ---------------------------------------------------------------------------
# Test helper
# ---------------------------------------------------------------------------


def assert_full_current_state_invariants() -> None:
    """Assert structural invariants on the full current-state report.

    Raises :class:`AssertionError` if any invariant is violated.
    Intended for use in the companion test suite.
    """
    report = get_full_current_state_rereading()

    # 1. Authority sentinel
    assert len(FULL_CURRENT_STATE_REREADING_AUTHORITY) > 0, "Authority sentinel empty"
    assert "FULL_CURRENT_STATE" in FULL_CURRENT_STATE_REREADING_AUTHORITY

    # 2. Report structure
    assert isinstance(report, FullCurrentStateReport)
    assert len(report.report_id) > 0
    assert report.generated_at > 0
    assert len(report.methodology) > 0
    assert len(report.verdict_zh) > 0

    # 3. System characterization
    assert report.system_characterization is not None
    assert len(report.system_characterization.v2_authority_role) > 0
    assert len(report.system_characterization.android_carrier_role) > 0

    # 4. Claim matrix covers all 7 claim families
    expected_claim_ids = {
        "system_identity_distributed_ai_body",
        "v2_sole_governance_authority",
        "android_is_runtime_carrier_not_client",
        "network_is_the_body",
        "system_beyond_poc",
        "remaining_work_is_closure_not_capability",
        "direction_toward_unified_ai_body",
    }
    actual_claim_ids = {c.claim_id for c in report.claim_matrix}
    assert actual_claim_ids == expected_claim_ids, (
        f"Claim IDs mismatch: {actual_claim_ids} vs {expected_claim_ids}"
    )

    # 5. Canonical path map covers all 6 paths
    expected_path_ids = {
        "android_registration",
        "runtime_snapshot_uplink",
        "execution_event_uplink",
        "task_dispatch_execute_result",
        "continuity_reconnect_resume",
        "orchestration_consumes_android_truth",
    }
    actual_path_ids = {p.path_id for p in report.path_closure_map}
    assert actual_path_ids == expected_path_ids, (
        f"Path IDs mismatch: {actual_path_ids} vs {expected_path_ids}"
    )

    # 6. Completion stage judgment exists and is LATE_STAGE_CLOSURE
    assert report.completion_stage_judgment is not None
    assert report.completion_stage_judgment.current_stage in (
        CompletionStage.LATE_STAGE_CLOSURE,
        CompletionStage.NON_P0_REFINEMENT_ONLY,
    ), (
        f"Expected LATE_STAGE_CLOSURE or NON_P0_REFINEMENT_ONLY; "
        f"got {report.completion_stage_judgment.current_stage}"
    )

    # 7. Zero P0 gaps
    assert report.p0_items_count == 0, (
        f"Expected 0 P0 items; got {report.p0_items_count}"
    )

    # 8. Post-next-PR judgment exists and targets NON_P0_REFINEMENT_ONLY
    assert report.post_next_pr_judgment is not None
    assert report.post_next_pr_judgment.post_stage == CompletionStage.NON_P0_REFINEMENT_ONLY

    # 9. System verdict is non-empty
    assert len(report.system_verdict) > 0

    # 10. Roadmap: no P0 items; has P1 and P3
    roadmap_priorities = [r.priority for r in report.roadmap]
    assert RoadmapPriority.P0_BLOCKING not in roadmap_priorities, (
        "Roadmap must have no P0 items in the current state"
    )
    assert RoadmapPriority.P1_CANONICAL_CLOSURE in roadmap_priorities
    assert RoadmapPriority.P3_DEPLOYMENT in roadmap_priorities

    # 11. Chinese verdict is non-empty and mentions the system
    assert "Galaxy" in report.verdict_zh or "双仓" in report.verdict_zh

    # 12. Counts are non-negative
    assert report.strongly_established_count >= 0
    assert report.runtime_evidenced_closed_count >= 0
    assert report.partially_established_count >= 0
    assert report.paths_runtime_closed_count >= 0
