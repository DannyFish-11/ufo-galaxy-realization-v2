#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/system_completion_status.py
================================

统一系统收口状态聚合面。

这个模块解决一个真实存在的可观测性缺口：仓库里已经有
architecture_completion / architecture_live_status /
dual_repo_system_completeness_review / system_final_acceptance_verdict
等多个评估面，但它们分别回答的是“架构迁移完成度”“架构运行态”
“双仓完整性审查”“系统接受度”这些不同问题。调用方如果只看其中
一个，很容易把“架构已 100%”误解成“整系统已 100% 收口”。

因此这里提供一个**代码级统一出口**，把这些真实代码产物汇总为：

1. 系统是什么（双仓分布式智能体系统）
2. 架构完成度是多少
3. 整系统真实收口度是多少
4. 距离 100% 还差哪些阻塞项 / 已接受的延期项
5. 当前是否存在“架构已完成，但系统未真正收口”的状态错位
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.dual_repo_system_completeness_review import (
    CompletenessLabel,
    CompletenessReviewReport,
    CompletenessVerdict,
    build_completeness_review,
)
from core.dual_repo_system_map import DUAL_REPO_MAIN_CHAIN, build_system_map_snapshot
from core.system_final_acceptance_verdict import (
    SystemAcceptanceReport,
    evaluate_system_acceptance,
)
from tools.architecture.architecture_completion import (
    get_architecture_completion_scorecard,
)
from tools.architecture.architecture_live_status import get_architecture_live_status

__all__ = [
    "SYSTEM_COMPLETION_STATUS_AUTHORITY",
    "SYSTEM_COMPLETION_STATUS_SENTINEL",
    "RemainingClosureItem",
    "SystemCompletionStatus",
    "build_system_completion_status",
    "get_system_completion_status",
    "reset_system_completion_status",
]


SYSTEM_COMPLETION_STATUS_AUTHORITY = (
    "SYSTEM_COMPLETION_STATUS_AUTHORITY::"
    "core.system_completion_status::"
    "unified-dual-repo-system-closure-surface"
)

SYSTEM_COMPLETION_STATUS_SENTINEL = (
    "SYSTEM_COMPLETION_STATUS_SENTINEL::"
    "profile=system-closure-status-v1::"
    "module=core.system_completion_status"
)

_LABEL_COMPLETION_PCT = {
    CompletenessLabel.not_present: 0.0,
    CompletenessLabel.nominally_present: 20.0,
    CompletenessLabel.structure_only: 40.0,
    CompletenessLabel.evidence_gap: 60.0,
    CompletenessLabel.deferred: 80.0,
    CompletenessLabel.complete: 100.0,
}


@dataclass(frozen=True)
class RemainingClosureItem:
    """单个尚未收口的问题条目。"""

    title: str
    severity: str
    source: str
    evidence: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {
            "title": self.title,
            "severity": self.severity,
            "source": self.source,
            "evidence": self.evidence,
        }


@dataclass
class SystemCompletionStatus:
    """统一的系统完成度/收口状态快照。"""

    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    generated_at: float = field(default_factory=time.time)
    system_kind: str = "dual_repo_distributed_agent_system"
    repositories: List[Dict[str, str]] = field(default_factory=list)
    main_chain: List[str] = field(default_factory=list)
    architecture_completion_pct: float = 0.0
    architecture_runtime_readiness: str = "unknown"
    system_closure_pct: float = 0.0
    remaining_pct_to_full_closure: float = 100.0
    completeness_verdict: str = CompletenessVerdict.insufficient_evidence.value
    final_acceptance_verdict: str = "acceptance_unknown_insufficient_evidence"
    is_fully_closed: bool = False
    is_fully_operational: bool = False
    blocking_gap_count: int = 0
    deferred_count: int = 0
    unresolved_acceptance_risk_count: int = 0
    status_alignment: Dict[str, Any] = field(default_factory=dict)
    remaining_to_100: List[RemainingClosureItem] = field(default_factory=list)
    accepted_limitations: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "system_kind": self.system_kind,
            "repositories": self.repositories,
            "main_chain": self.main_chain,
            "architecture_completion_pct": self.architecture_completion_pct,
            "architecture_runtime_readiness": self.architecture_runtime_readiness,
            "system_closure_pct": self.system_closure_pct,
            "remaining_pct_to_full_closure": self.remaining_pct_to_full_closure,
            "completeness_verdict": self.completeness_verdict,
            "final_acceptance_verdict": self.final_acceptance_verdict,
            "is_fully_closed": self.is_fully_closed,
            "is_fully_operational": self.is_fully_operational,
            "blocking_gap_count": self.blocking_gap_count,
            "deferred_count": self.deferred_count,
            "unresolved_acceptance_risk_count": self.unresolved_acceptance_risk_count,
            "status_alignment": self.status_alignment,
            "remaining_to_100": [item.to_dict() for item in self.remaining_to_100],
            "accepted_limitations": self.accepted_limitations,
            "summary": self.summary,
        }

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def _compute_system_closure_pct(completeness_review: CompletenessReviewReport) -> float:
    if not completeness_review.dimensions:
        return 0.0

    pct = round(
        sum(
            _LABEL_COMPLETION_PCT.get(entry.label, 0.0)
            for entry in completeness_review.dimensions
        )
        / len(completeness_review.dimensions),
        2,
    )

    if (
        completeness_review.verdict != CompletenessVerdict.fully_closed
        and pct >= 100.0
    ):
        return 99.0

    return pct


def _append_unique_item(
    bucket: List[RemainingClosureItem],
    seen: set[str],
    *,
    title: str,
    severity: str,
    source: str,
    evidence: str = "",
) -> None:
    key = f"{severity}|{source}|{title}"
    if key in seen:
        return
    seen.add(key)
    bucket.append(
        RemainingClosureItem(
            title=title,
            severity=severity,
            source=source,
            evidence=evidence,
        )
    )


def _build_remaining_to_100(
    completeness_review: CompletenessReviewReport,
    acceptance_report: SystemAcceptanceReport,
    system_map: Dict[str, Any],
) -> List[RemainingClosureItem]:
    items: List[RemainingClosureItem] = []
    seen: set[str] = set()

    for gap in completeness_review.blocking_gaps:
        _append_unique_item(
            items,
            seen,
            title=gap,
            severity="blocking",
            source="dual_repo_system_completeness_review",
            evidence="core.dual_repo_system_completeness_review",
        )

    for risk in acceptance_report.unresolved_risk_summary:
        dimension = risk.get("dimension", "unknown")
        description = risk.get("risk_description", "").strip()
        if not description:
            continue
        _append_unique_item(
            items,
            seen,
            title=f"[{dimension}] {description}",
            severity="acceptance_risk",
            source="system_final_acceptance_verdict",
            evidence="core.system_final_acceptance_verdict",
        )

    for severity, entries in system_map.get("open_gaps", {}).items():
        for entry in entries:
            title = entry.get("title")
            gap_id = entry.get("id", "")
            if not title:
                continue
            _append_unique_item(
                items,
                seen,
                title=title,
                severity=severity,
                source="dual_repo_system_map",
                evidence=gap_id,
            )

    return items


def _build_summary(
    *,
    architecture_pct: float,
    runtime_readiness: str,
    closure_pct: float,
    completeness_review: CompletenessReviewReport,
    acceptance_report: SystemAcceptanceReport,
    remaining_items: List[RemainingClosureItem],
) -> str:
    lines = [
        "系统统一收口状态",
        f"- 架构完成度: {architecture_pct:.2f}%",
        f"- 架构运行态: {runtime_readiness}",
        f"- 整系统真实收口度: {closure_pct:.2f}%",
        f"- 双仓完整性结论: {completeness_review.verdict.value}",
        f"- 系统最终验收结论: {acceptance_report.verdict.value}",
        f"- 阻塞项数量: {len(completeness_review.blocking_gaps)}",
        f"- 延期项数量: {len(completeness_review.deferred_acknowledged)}",
    ]

    if (
        architecture_pct >= 100.0
        and completeness_review.verdict != CompletenessVerdict.fully_closed
    ):
        lines.append("- 状态错位: 架构面已显示 100%，但整系统仍未真正 100% 收口。")

    if remaining_items:
        lines.append("- 距离 100% 还差的关键项:")
        for item in remaining_items[:8]:
            lines.append(f"  • [{item.severity}] {item.title}")

    return "\n".join(lines)


def build_system_completion_status() -> SystemCompletionStatus:
    """构建统一系统收口状态。"""

    scorecard = get_architecture_completion_scorecard()
    live_status = get_architecture_live_status(force_rebuild=True)
    review = build_completeness_review()
    acceptance = evaluate_system_acceptance()
    system_map = build_system_map_snapshot()

    architecture_pct = round(float(scorecard.overall_completion_pct), 2)
    closure_pct = _compute_system_closure_pct(review)
    remaining_pct = round(max(0.0, 100.0 - closure_pct), 2)
    remaining_items = _build_remaining_to_100(review, acceptance, system_map)

    status_alignment = {
        "architecture_complete_but_system_not_closed": (
            architecture_pct >= 100.0 and review.verdict != CompletenessVerdict.fully_closed
        ),
        "runtime_ready_but_acceptance_not_full": (
            live_status.runtime_readiness == "ready" and not acceptance.is_fully_operational
        ),
        "runtime_ready_but_completeness_not_full": (
            live_status.runtime_readiness == "ready" and review.verdict != CompletenessVerdict.fully_closed
        ),
    }

    summary = _build_summary(
        architecture_pct=architecture_pct,
        runtime_readiness=live_status.runtime_readiness,
        closure_pct=closure_pct,
        completeness_review=review,
        acceptance_report=acceptance,
        remaining_items=remaining_items,
    )

    return SystemCompletionStatus(
        repositories=[
            {
                "name": "ufo-galaxy-realization-v2",
                "role": "control_plane_orchestration_and_truth",
            },
            {
                "name": "ufo-galaxy-android",
                "role": "persistent_execution_participant",
            },
        ],
        main_chain=list(DUAL_REPO_MAIN_CHAIN),
        architecture_completion_pct=architecture_pct,
        architecture_runtime_readiness=live_status.runtime_readiness,
        system_closure_pct=closure_pct,
        remaining_pct_to_full_closure=remaining_pct,
        completeness_verdict=review.verdict.value,
        final_acceptance_verdict=acceptance.verdict.value,
        is_fully_closed=review.is_fully_closed,
        is_fully_operational=acceptance.is_fully_operational,
        blocking_gap_count=len(review.blocking_gaps),
        deferred_count=len(review.deferred_acknowledged),
        unresolved_acceptance_risk_count=len(acceptance.unresolved_risk_summary),
        status_alignment=status_alignment,
        remaining_to_100=remaining_items,
        accepted_limitations=list(review.deferred_acknowledged),
        summary=summary,
    )


_CACHED_STATUS: Optional[SystemCompletionStatus] = None


def get_system_completion_status(*, force_rebuild: bool = False) -> SystemCompletionStatus:
    global _CACHED_STATUS
    if _CACHED_STATUS is None or force_rebuild:
        _CACHED_STATUS = build_system_completion_status()
    return _CACHED_STATUS


def reset_system_completion_status() -> None:
    global _CACHED_STATUS
    _CACHED_STATUS = None
