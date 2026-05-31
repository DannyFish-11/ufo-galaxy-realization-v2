"""Dual-repo progress report (V2 + Android) — real-code derived snapshot.

This module provides a single read-only aggregation surface that answers:
- The current dual-repo closure/completion status (operator-facing)
- The joint cognitive review stage + completion scores (evidence-based)
- The next closure execution plan summary (machine-readable)

All fields degrade gracefully: when an upstream audit module cannot be imported
or evaluated, the report includes an explicit *_error field rather than raising.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

DUAL_REPO_PROGRESS_REPORT_AUTHORITY: str = (
    "DUAL_REPO_PROGRESS_REPORT::core.dual_repo_progress_report::v1"
)


def _safe_get(dct: Dict[str, Any], *keys: str) -> Optional[Any]:
    cur: Any = dct
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _build_summary_zh(payload: Dict[str, Any]) -> str:
    status = payload.get("system_completion_status") or {}
    review = payload.get("complete_joint_system_review") or {}
    plan = payload.get("closure_phase_execution_plan") or {}

    closure_pct = _safe_get(status, "system_closure_pct")
    completeness_verdict = _safe_get(status, "completeness_verdict")
    final_acceptance = _safe_get(status, "final_acceptance_verdict")
    blocking_gaps = _safe_get(status, "blocking_gap_count")

    stage = _safe_get(review, "stage")
    weighted_completion = _safe_get(review, "weighted_completion_pct")
    android_ref = _safe_get(review, "android_audited_ref")

    remaining_issue_count = _safe_get(plan, "remaining_issue_count")
    next_prs: List[str] = list(_safe_get(plan, "next_prs") or [])

    parts: List[str] = []
    if closure_pct is not None:
        parts.append(f"系统收口度约 {closure_pct:.2f}%（completeness={completeness_verdict}）")
    if final_acceptance:
        parts.append(f"最终接受度判定={final_acceptance}")
    if blocking_gaps is not None:
        parts.append(f"阻塞项数量={blocking_gaps}")

    if stage:
        if weighted_completion is not None:
            parts.append(f"双仓联合审查阶段={stage}（加权完成度 {weighted_completion:.2f}%）")
        else:
            parts.append(f"双仓联合审查阶段={stage}")
    if android_ref:
        parts.append(f"Android 审计参考提交={android_ref}")

    if remaining_issue_count is not None:
        parts.append(f"下一阶段剩余问题数={remaining_issue_count}")
    if next_prs:
        parts.append(f"优先 PR 序列（前{min(len(next_prs), 5)}个）={', '.join(next_prs[:5])}")

    if not parts:
        return "双仓进度报告不可用（上游审计模块均未能生成可用快照）。"
    return "；".join(parts)


def build_dual_repo_progress_report(*, force_rebuild: bool = True) -> Dict[str, Any]:
    """Build a real-code derived dual-repo progress report snapshot."""
    generated_at = time.time()
    payload: Dict[str, Any] = {
        "authority": DUAL_REPO_PROGRESS_REPORT_AUTHORITY,
        "generated_at": generated_at,
    }

    try:
        from core.system_completion_status import get_system_completion_status

        status = get_system_completion_status(force_rebuild=force_rebuild)
        payload["system_completion_status"] = status.to_dict()
    except Exception as exc:  # pragma: no cover
        logger.debug("Fallback triggered: %s", exc)
        payload["system_completion_status_error"] = str(exc)

    try:
        from core.complete_joint_system_review import build_complete_joint_system_review

        review = build_complete_joint_system_review()
        payload["complete_joint_system_review"] = {
            "authority": review.authority,
            "generated_at": review.generated_at,
            "android_audited_ref": review.android_audited_ref,
            "stage": review.stage.value,
            "overall_completion_pct": review.overall_completion_pct,
            "weighted_completion_pct": review.weighted_completion_pct,
            "remaining_issue_count": len(review.remaining_issues),
            "domain_count": len(review.domain_statuses),
        }
    except Exception as exc:  # pragma: no cover
        logger.debug("Fallback triggered: %s", exc)
        payload["complete_joint_system_review_error"] = str(exc)

    try:
        from core.closure_phase_execution_plan import build_closure_phase_execution_plan

        plan = build_closure_phase_execution_plan()
        payload["closure_phase_execution_plan"] = {
            "authority": plan.authority,
            "generated_at": plan.generated_at,
            "baseline_stage": plan.baseline_stage.value,
            "baseline_android_audited_ref": plan.baseline_android_audited_ref,
            "remaining_issue_count": len(plan.remaining_issue_ids),
            "closure_block_count": len(plan.closure_blocks),
            "next_prs": [entry.pr_key for entry in plan.pr_sequence[:10]],
        }
    except Exception as exc:  # pragma: no cover
        logger.debug("Fallback triggered: %s", exc)
        payload["closure_phase_execution_plan_error"] = str(exc)

    payload["summary_zh"] = _build_summary_zh(payload)
    return payload

