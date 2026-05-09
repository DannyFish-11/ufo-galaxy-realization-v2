"""Authoritative closure execution plan derived from complete joint system review.

This module does not implement runtime fixes. It converts the remaining issues
from ``core.complete_joint_system_review`` (R1-R13) into a machine-readable
execution program for the next closure phase across:
- DannyFish-11/ufo-galaxy-realization-v2
- DannyFish-11/ufo-galaxy-android
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

from core.complete_joint_system_review import (
    REVIEW_AUTHORITY,
    REVIEW_PR_TITLE,
    CompleteJointSystemReport,
    RemainingIssue,
    StageGate,
    StageVerdict,
    build_complete_joint_system_review,
)

V2_REPOSITORY = "DannyFish-11/ufo-galaxy-realization-v2"
ANDROID_REPOSITORY = "DannyFish-11/ufo-galaxy-android"

CLOSURE_PLAN_AUTHORITY = (
    "COMPLETE_JOINT_CLOSURE_EXECUTION_PLAN::"
    "core.closure_phase_execution_plan::derived-from-core.complete_joint_system_review"
)


class RepoOwnership(str, Enum):
    V2 = "v2"
    ANDROID = "android"
    DUAL = "dual-repo"


@dataclass
class PlannedPR:
    sequence: int
    pr_key: str
    title: str
    ownership: RepoOwnership
    repositories: List[str]
    issue_ids: List[str]
    block_id: str
    depends_on_prs: List[str] = field(default_factory=list)
    v2_anchors: List[str] = field(default_factory=list)
    android_anchors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sequence": self.sequence,
            "pr_key": self.pr_key,
            "title": self.title,
            "ownership": self.ownership.value,
            "repositories": list(self.repositories),
            "issue_ids": list(self.issue_ids),
            "block_id": self.block_id,
            "depends_on_prs": list(self.depends_on_prs),
            "v2_anchors": list(self.v2_anchors),
            "android_anchors": list(self.android_anchors),
        }


@dataclass
class ClosureBlock:
    block_id: str
    stage_gate: StageGate
    summary: str
    issue_ids: List[str]
    pr_keys: List[str]
    repositories: List[str]
    depends_on_blocks: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "block_id": self.block_id,
            "stage_gate": self.stage_gate.value,
            "summary": self.summary,
            "issue_ids": list(self.issue_ids),
            "pr_keys": list(self.pr_keys),
            "repositories": list(self.repositories),
            "depends_on_blocks": list(self.depends_on_blocks),
        }


@dataclass
class StageTransitionCondition:
    from_stage: StageVerdict
    to_stage: StageVerdict
    required_block_ids: List[str]
    required_issue_ids: List[str]
    acceptance_conditions: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_stage": self.from_stage.value,
            "to_stage": self.to_stage.value,
            "required_block_ids": list(self.required_block_ids),
            "required_issue_ids": list(self.required_issue_ids),
            "acceptance_conditions": list(self.acceptance_conditions),
        }


@dataclass
class ClosureExecutionPlan:
    authority: str = CLOSURE_PLAN_AUTHORITY
    baseline_authority: str = REVIEW_AUTHORITY
    baseline_pr_title: str = REVIEW_PR_TITLE
    generated_at: float = field(default_factory=time.time)
    baseline_stage: StageVerdict = StageVerdict.MID_STAGE_CONSOLIDATION
    baseline_android_audited_ref: str = ""
    remaining_issue_ids: List[str] = field(default_factory=list)
    issue_to_prs: Dict[str, List[str]] = field(default_factory=dict)
    pr_sequence: List[PlannedPR] = field(default_factory=list)
    closure_blocks: List[ClosureBlock] = field(default_factory=list)
    stage_transitions: List[StageTransitionCondition] = field(default_factory=list)
    dependency_graph: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "baseline_authority": self.baseline_authority,
            "baseline_pr_title": self.baseline_pr_title,
            "generated_at": self.generated_at,
            "baseline_stage": self.baseline_stage.value,
            "baseline_android_audited_ref": self.baseline_android_audited_ref,
            "remaining_issue_ids": list(self.remaining_issue_ids),
            "issue_to_prs": {k: list(v) for k, v in self.issue_to_prs.items()},
            "pr_sequence": [p.to_dict() for p in self.pr_sequence],
            "closure_blocks": [b.to_dict() for b in self.closure_blocks],
            "stage_transitions": [s.to_dict() for s in self.stage_transitions],
            "dependency_graph": {k: list(v) for k, v in self.dependency_graph.items()},
        }


def _ensure_all_issues_are_planned(
    report: CompleteJointSystemReport, issue_to_prs: Dict[str, List[str]]
) -> None:
    baseline_ids = {issue.issue_id for issue in report.remaining_issues}
    planned_ids = set(issue_to_prs.keys())
    if baseline_ids != planned_ids:
        missing = sorted(baseline_ids - planned_ids)
        extra = sorted(planned_ids - baseline_ids)
        raise ValueError(
            "Closure execution plan must map exactly to baseline remaining issues. "
            f"missing={missing}, extra={extra}"
        )


def _collect_issue_anchors(issue_index: Dict[str, RemainingIssue], issue_ids: List[str]) -> Dict[str, List[str]]:
    v2_seen = set()
    android_seen = set()
    v2: List[str] = []
    android: List[str] = []
    for issue_id in issue_ids:
        issue = issue_index[issue_id]
        for anchor in issue.v2_anchors:
            if anchor not in v2_seen:
                v2_seen.add(anchor)
                v2.append(anchor)
        for anchor in issue.android_anchors:
            if anchor not in android_seen:
                android_seen.add(anchor)
                android.append(anchor)
    return {"v2": v2, "android": android}


def build_closure_phase_execution_plan() -> ClosureExecutionPlan:
    """Build authoritative closure execution plan from R1-R13 baseline."""
    report = build_complete_joint_system_review()
    issue_index = {issue.issue_id: issue for issue in report.remaining_issues}

    issue_to_prs = {
        "R1": ["CP-01"],
        "R2": ["CP-02"],
        "R3": ["CP-03"],
        "R4": ["CP-06"],
        "R5": ["CP-07"],
        "R6": ["CP-12"],
        "R7": ["CP-09"],
        "R8": ["CP-08"],
        "R9": ["CP-11"],
        "R10": ["CP-04"],
        "R11": ["CP-10"],
        "R12": ["CP-05"],
        "R13": ["CP-13"],
    }
    _ensure_all_issues_are_planned(report, issue_to_prs)

    blueprints = [
        (1, "CP-01", "R1 orchestration truth-consumption closure", RepoOwnership.V2, [V2_REPOSITORY], ["R1"],
         "B-P0-RUNTIME-CLOSURE", []),
        (
            2,
            "CP-02",
            "R2 Android→V2 runtime-state transparency closure",
            RepoOwnership.DUAL,
            [V2_REPOSITORY, ANDROID_REPOSITORY],
            ["R2"],
            "B-P0-RUNTIME-CLOSURE",
            ["CP-01"],
        ),
        (
            3,
            "CP-03",
            "R3 cross-repo gate unification closure",
            RepoOwnership.DUAL,
            [V2_REPOSITORY, ANDROID_REPOSITORY],
            ["R3"],
            "B-P0-RUNTIME-CLOSURE",
            ["CP-01", "CP-02"],
        ),
        (
            4,
            "CP-04",
            "R10 local inference availability into canonical gate",
            RepoOwnership.DUAL,
            [V2_REPOSITORY, ANDROID_REPOSITORY],
            ["R10"],
            "B-P1-GOVERNANCE-AND-ORCHESTRATION",
            ["CP-03"],
        ),
        (
            5,
            "CP-05",
            "R12 busy/queue_depth orchestration consumption closure",
            RepoOwnership.V2,
            [V2_REPOSITORY],
            ["R12"],
            "B-P1-GOVERNANCE-AND-ORCHESTRATION",
            ["CP-01", "CP-03"],
        ),
        (
            6,
            "CP-06",
            "R4 mesh/hybrid/delegated runtime closure",
            RepoOwnership.DUAL,
            [V2_REPOSITORY, ANDROID_REPOSITORY],
            ["R4"],
            "B-P1-RUNTIME-COLLABORATION",
            ["CP-03", "CP-05"],
        ),
        (
            7,
            "CP-07",
            "R5 operator/panel/control single-source closure",
            RepoOwnership.V2,
            [V2_REPOSITORY],
            ["R5"],
            "B-P1-CONTROL-MANIFESTATION",
            ["CP-01", "CP-02"],
        ),
        (
            8,
            "CP-08",
            "R8 desktop/tablet/android carrier semantics unification",
            RepoOwnership.DUAL,
            [V2_REPOSITORY, ANDROID_REPOSITORY],
            ["R8"],
            "B-P1-CONTROL-MANIFESTATION",
            ["CP-07"],
        ),
        (
            9,
            "CP-09",
            "R7 ingress causality consistency regression closure",
            RepoOwnership.V2,
            [V2_REPOSITORY],
            ["R7"],
            "B-P1-INGRESS-AND-CONTRACT",
            ["CP-03"],
        ),
        (
            10,
            "CP-10",
            "R11 cross-repo contract schema/version governance closure",
            RepoOwnership.DUAL,
            [V2_REPOSITORY, ANDROID_REPOSITORY],
            ["R11"],
            "B-P1-INGRESS-AND-CONTRACT",
            ["CP-09"],
        ),
        (
            11,
            "CP-11",
            "R9 session continuity restart/rebuild closure",
            RepoOwnership.DUAL,
            [V2_REPOSITORY, ANDROID_REPOSITORY],
            ["R9"],
            "B-P1-CONTINUITY-AND-PROOF",
            ["CP-02", "CP-10"],
        ),
        (
            12,
            "CP-12",
            "R6 live runtime proof-thickness closure",
            RepoOwnership.DUAL,
            [V2_REPOSITORY, ANDROID_REPOSITORY],
            ["R6"],
            "B-P1-CONTINUITY-AND-PROOF",
            ["CP-04", "CP-06", "CP-07", "CP-10", "CP-11"],
        ),
        (
            13,
            "CP-13",
            "R13 cross-repo combined failure/regression enhancement",
            RepoOwnership.DUAL,
            [V2_REPOSITORY, ANDROID_REPOSITORY],
            ["R13"],
            "B-P2-ENHANCEMENT",
            ["CP-12"],
        ),
    ]

    pr_sequence: List[PlannedPR] = []
    for seq, pr_key, title, ownership, repos, issue_ids, block_id, deps in blueprints:
        anchors = _collect_issue_anchors(issue_index, issue_ids)
        pr_sequence.append(
            PlannedPR(
                sequence=seq,
                pr_key=pr_key,
                title=title,
                ownership=ownership,
                repositories=repos,
                issue_ids=issue_ids,
                block_id=block_id,
                depends_on_prs=deps,
                v2_anchors=anchors["v2"],
                android_anchors=anchors["android"],
            )
        )

    closure_blocks = [
        ClosureBlock(
            block_id="B-P0-RUNTIME-CLOSURE",
            stage_gate=StageGate.P0_BEFORE_RUNTIME_CLOSURE,
            summary="P0 before runtime closure: close R1-R3 without introducing new feature logic.",
            issue_ids=["R1", "R2", "R3"],
            pr_keys=["CP-01", "CP-02", "CP-03"],
            repositories=[V2_REPOSITORY, ANDROID_REPOSITORY],
        ),
        ClosureBlock(
            block_id="B-P1-GOVERNANCE-AND-ORCHESTRATION",
            stage_gate=StageGate.P1_BEFORE_NEAR_CLOSURE,
            summary="P1 governance/orchestration deepening tied to R10 and R12.",
            issue_ids=["R10", "R12"],
            pr_keys=["CP-04", "CP-05"],
            repositories=[V2_REPOSITORY, ANDROID_REPOSITORY],
            depends_on_blocks=["B-P0-RUNTIME-CLOSURE"],
        ),
        ClosureBlock(
            block_id="B-P1-RUNTIME-COLLABORATION",
            stage_gate=StageGate.P1_BEFORE_NEAR_CLOSURE,
            summary="P1 runtime collaboration closure for mesh/hybrid/delegated path (R4).",
            issue_ids=["R4"],
            pr_keys=["CP-06"],
            repositories=[V2_REPOSITORY, ANDROID_REPOSITORY],
            depends_on_blocks=["B-P1-GOVERNANCE-AND-ORCHESTRATION"],
        ),
        ClosureBlock(
            block_id="B-P1-CONTROL-MANIFESTATION",
            stage_gate=StageGate.P1_BEFORE_NEAR_CLOSURE,
            summary="P1 single-source control/manifestation closure for operator and carrier surfaces (R5, R8).",
            issue_ids=["R5", "R8"],
            pr_keys=["CP-07", "CP-08"],
            repositories=[V2_REPOSITORY, ANDROID_REPOSITORY],
            depends_on_blocks=["B-P0-RUNTIME-CLOSURE"],
        ),
        ClosureBlock(
            block_id="B-P1-INGRESS-AND-CONTRACT",
            stage_gate=StageGate.P1_BEFORE_NEAR_CLOSURE,
            summary="P1 ingress causality and cross-repo contract governance closure (R7, R11).",
            issue_ids=["R7", "R11"],
            pr_keys=["CP-09", "CP-10"],
            repositories=[V2_REPOSITORY, ANDROID_REPOSITORY],
            depends_on_blocks=["B-P0-RUNTIME-CLOSURE"],
        ),
        ClosureBlock(
            block_id="B-P1-CONTINUITY-AND-PROOF",
            stage_gate=StageGate.P1_BEFORE_NEAR_CLOSURE,
            summary="P1 continuity and runtime-proof thickening closure (R9, R6).",
            issue_ids=["R9", "R6"],
            pr_keys=["CP-11", "CP-12"],
            repositories=[V2_REPOSITORY, ANDROID_REPOSITORY],
            depends_on_blocks=[
                "B-P1-GOVERNANCE-AND-ORCHESTRATION",
                "B-P1-RUNTIME-COLLABORATION",
                "B-P1-CONTROL-MANIFESTATION",
                "B-P1-INGRESS-AND-CONTRACT",
            ],
        ),
        ClosureBlock(
            block_id="B-P2-ENHANCEMENT",
            stage_gate=StageGate.P2_ENHANCEMENT,
            summary="P2 enhancement for combined cross-repo abnormal-scenario regression closure (R13).",
            issue_ids=["R13"],
            pr_keys=["CP-13"],
            repositories=[V2_REPOSITORY, ANDROID_REPOSITORY],
            depends_on_blocks=["B-P1-CONTINUITY-AND-PROOF"],
        ),
    ]

    stage_transitions = [
        StageTransitionCondition(
            from_stage=StageVerdict.MID_STAGE_CONSOLIDATION,
            to_stage=StageVerdict.LATE_INTEGRATION,
            required_block_ids=["B-P0-RUNTIME-CLOSURE"],
            required_issue_ids=["R1", "R2", "R3"],
            acceptance_conditions=[
                "All P0 issues from complete_joint_system_review are assigned to merged closure PRs.",
                "No remaining issue with stage_gate=P0-before-runtime-closure is open.",
                "Stage recalculation from the baseline review can advance beyond mid-stage consolidation.",
            ],
        ),
        StageTransitionCondition(
            from_stage=StageVerdict.LATE_INTEGRATION,
            to_stage=StageVerdict.NEAR_CLOSURE,
            required_block_ids=[
                "B-P1-GOVERNANCE-AND-ORCHESTRATION",
                "B-P1-RUNTIME-COLLABORATION",
                "B-P1-CONTROL-MANIFESTATION",
                "B-P1-INGRESS-AND-CONTRACT",
                "B-P1-CONTINUITY-AND-PROOF",
            ],
            required_issue_ids=["R4", "R5", "R6", "R7", "R8", "R9", "R10", "R11", "R12"],
            acceptance_conditions=[
                "All P1 issues from complete_joint_system_review are assigned to merged closure PRs.",
                "No remaining issue with stage_gate=P1-before-near-closure is open.",
                "Only P2-enhancement issues may remain for near-closure readiness.",
            ],
        ),
    ]

    dependency_graph = {block.block_id: list(block.depends_on_blocks) for block in closure_blocks}

    return ClosureExecutionPlan(
        baseline_stage=report.stage,
        baseline_android_audited_ref=report.android_audited_ref,
        remaining_issue_ids=[issue.issue_id for issue in report.remaining_issues],
        issue_to_prs=issue_to_prs,
        pr_sequence=pr_sequence,
        closure_blocks=closure_blocks,
        stage_transitions=stage_transitions,
        dependency_graph=dependency_graph,
    )


__all__ = [
    "ANDROID_REPOSITORY",
    "CLOSURE_PLAN_AUTHORITY",
    "RepoOwnership",
    "PlannedPR",
    "ClosureBlock",
    "StageTransitionCondition",
    "ClosureExecutionPlan",
    "V2_REPOSITORY",
    "build_closure_phase_execution_plan",
]
