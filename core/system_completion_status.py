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

# 防止在“均分刚好 100，但 verdict 仍未 fully_closed”的情况下对外输出虚假的
# 100% 收口信号。此时最多只展示为“接近完成但尚未真正闭环”。
MAX_CLOSURE_PCT_WITHOUT_FULL_VERDICT = 99.0


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
    # PR-10 V2 final consolidation evidence: tracks whether the five canonical
    # V2 consolidation paths (ingress, continuity, orchestration, manifestation,
    # operator truth) are structurally coherent in the current code.
    v2_consolidation_evidence: Dict[str, Any] = field(default_factory=dict)
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
            "v2_consolidation_evidence": self.v2_consolidation_evidence,
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
        return MAX_CLOSURE_PCT_WITHOUT_FULL_VERDICT

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


def _build_v2_consolidation_evidence() -> Dict[str, Any]:
    """Build the PR-10 V2 final consolidation evidence dict.

    Probes the five canonical V2 consolidation paths introduced by the
    prior PR work (ingress, continuity, orchestration, manifestation,
    operator truth) and returns a coherence summary.  All probes are
    read-only import/file checks — no runtime state is mutated.
    """
    import importlib
    import os

    def _can_import(mod: str) -> bool:
        try:
            importlib.import_module(mod)
            return True
        except Exception:
            return False

    def _file_present(rel: str) -> bool:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.isfile(os.path.join(root, rel))

    # 1. Ingress truth — unified_runtime_truth_ingress (PR-2)
    ingress_available = _can_import("core.unified_runtime_truth_ingress")

    # 2. Continuity — flow_continuity_coordinator (PR-3V2)
    continuity_available = _can_import("core.flow_continuity_coordinator")

    # 3. Orchestration — orchestration_review_surface (PR-10 observability)
    orchestration_review_available = _can_import("core.orchestration_review_surface")

    # 4. Manifestation / shell / presence — desktop_presence_runtime (PR-8V2)
    manifestation_available = _can_import("core.desktop_presence_runtime")

    # 5. Operator truth — flow_level_operator_surface + operator_surface
    operator_surface_available = _can_import("core.operator_surface")
    flow_operator_available = _can_import("core.flow_level_operator_surface")

    # Orchestration review surface — check if it can produce a snapshot
    orchestration_snapshot_ok = False
    orchestration_partial = None
    if orchestration_review_available:
        try:
            from core.orchestration_review_surface import (  # type: ignore[import]
                build_orchestration_review_snapshot,
            )
            snap = build_orchestration_review_snapshot()
            orchestration_snapshot_ok = True
            orchestration_partial = snap._partial
        except Exception:
            pass

    # Continuity coordinator — can it be constructed?
    continuity_coordinator_ok = False
    if continuity_available:
        try:
            from core.flow_continuity_coordinator import (  # type: ignore[import]
                get_flow_continuity_coordinator,
            )
            coord = get_flow_continuity_coordinator()
            continuity_coordinator_ok = coord is not None
        except Exception:
            pass

    chain_paths = {
        "ingress": ingress_available,
        "continuity": continuity_available,
        "orchestration_review": orchestration_review_available,
        "manifestation": manifestation_available,
        "operator_surface": operator_surface_available,
        "flow_operator_surface": flow_operator_available,
    }
    chain_coherent = all(chain_paths.values())
    available_count = sum(1 for v in chain_paths.values() if v)
    total_count = len(chain_paths)

    return {
        "chain_paths_available": chain_paths,
        "chain_coherent": chain_coherent,
        "available_count": available_count,
        "total_count": total_count,
        "orchestration_snapshot_ok": orchestration_snapshot_ok,
        "orchestration_review_partial": orchestration_partial,
        "continuity_coordinator_ok": continuity_coordinator_ok,
        "consolidation_verdict": (
            "coherent"
            if chain_coherent
            else f"partial ({available_count}/{total_count} paths available)"
        ),
    }


def _build_summary(
    *,
    architecture_pct: float,
    runtime_readiness: str,
    closure_pct: float,
    completeness_review: CompletenessReviewReport,
    acceptance_report: SystemAcceptanceReport,
    remaining_items: List[RemainingClosureItem],
    consolidation_evidence: Optional[Dict[str, Any]] = None,
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

    if consolidation_evidence:
        verdict = consolidation_evidence.get("consolidation_verdict", "unknown")
        lines.append(f"- V2 统一体验收口链路状态: {verdict}")

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
    consolidation_evidence = _build_v2_consolidation_evidence()

    architecture_pct = round(float(scorecard.overall_completion_pct), 2)
    closure_pct = _compute_system_closure_pct(review)
    remaining_pct = round(max(0.0, 100.0 - closure_pct), 2)
    remaining_items = _build_remaining_to_100(review, acceptance, system_map)

    consolidation_coherent = consolidation_evidence.get("chain_coherent", False)
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
        # PR-10 V2 final consolidation: are all five canonical paths coherent?
        "v2_consolidation_chain_coherent": consolidation_coherent,
    }

    summary = _build_summary(
        architecture_pct=architecture_pct,
        runtime_readiness=live_status.runtime_readiness,
        closure_pct=closure_pct,
        completeness_review=review,
        acceptance_report=acceptance,
        remaining_items=remaining_items,
        consolidation_evidence=consolidation_evidence,
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
        v2_consolidation_evidence=consolidation_evidence,
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
