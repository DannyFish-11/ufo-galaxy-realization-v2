"""统一运行时决策推理合同。

本模块提供 V2 侧统一的 ``RuntimeDecisionReasoningBlock``，用于把 routing、
readiness、acceptance、closure、operator、board、projection 等路径的关键
决策解释收敛到同一个可序列化结构里。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

RUNTIME_DECISION_REASONING_BLOCK_AUTHORITY = (
    "RUNTIME_DECISION_REASONING_BLOCK_V1::"
    "core.runtime_decision_reasoning 提供 V2 侧统一运行时决策推理合同。"
    "routing/readiness/acceptance/closure/operator/board/projection"
    " 应复用同一 reasoning block，而不是各自定义 explanation 结构。"
)

RUNTIME_DECISION_REASONING_BLOCK_CONTRACT_VERSION = "1.0.0"
V2_ANDROID_TRUTH_BLOCK_REF = "core.v2_android_truth_ssot.build_v2_android_truth_block"


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _dedupe_strings(values: Iterable[Any]) -> List[str]:
    deduped: List[str] = []
    seen = set()
    for value in values:
        if value in (None, ""):
            continue
        text = str(value)
        if text not in seen:
            deduped.append(text)
            seen.add(text)
    return deduped


def _normalize_mode_state(value: Any) -> str:
    return str(value or "").strip().lower()


def _derive_selected_runtime_default(
    *,
    current_selected_runtime: str,
    resolved_mode_state: Any,
    selected_device: Optional[str],
) -> str:
    if current_selected_runtime not in ("", "unknown"):
        return current_selected_runtime

    mode = _normalize_mode_state(resolved_mode_state)
    if mode in {"local", "local_only"}:
        return "android_local" if selected_device else "v2_local"
    if mode in {"remote_handoff", "staged_mesh", "cross_device", "android_delegated"}:
        return "android_delegated"
    if selected_device:
        return "android_delegated"
    return "v2_local"


def _truth_get(block: Any, key: str, default: Any = None) -> Any:
    if block is None:
        return default
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _load_android_truth_block(device_id: Optional[str]) -> Any:
    if not device_id:
        return None
    try:
        from core.v2_android_truth_ssot import build_v2_android_truth_block

        return build_v2_android_truth_block(str(device_id))
    except Exception:
        return None


def _build_android_truth_basis(block: Any) -> Dict[str, Any]:
    if block is None:
        return {}
    return {
        "device_id": _truth_get(block, "device_id"),
        "participation_tier": _truth_get(block, "participation_tier", "unknown"),
        "dispatch_eligible": bool(_truth_get(block, "dispatch_eligible", False)),
        "distributed_participant": bool(_truth_get(block, "distributed_participant", False)),
        "device_mode": _truth_get(block, "device_mode"),
        "mode_readiness_state": _truth_get(block, "mode_readiness_state"),
        "model_ready": _truth_get(block, "model_ready"),
        "accessibility_ready": _truth_get(block, "accessibility_ready"),
        "local_loop_ready": _truth_get(block, "local_loop_ready"),
        "local_inference_ready": _truth_get(block, "local_inference_ready"),
        "local_inference_available": _truth_get(block, "local_inference_available"),
        "current_fallback_tier": _truth_get(block, "current_fallback_tier"),
        "execution_mode_state": _truth_get(block, "execution_mode_state"),
        "runtime_constrained": _truth_get(block, "runtime_constrained"),
        "runtime_deferred": _truth_get(block, "runtime_deferred"),
        "local_mode_active": _truth_get(block, "local_mode_active"),
        "local_mode_gate_deferred": _truth_get(block, "local_mode_gate_deferred"),
        "pending_first_download": _truth_get(block, "pending_first_download"),
        "degraded_reasons": list(_truth_get(block, "degraded_reasons", []) or []),
        "participation_blocking_reasons": list(
            _truth_get(block, "participation_blocking_reasons", []) or []
        ),
        "tier_notes": list(_truth_get(block, "participation_tier_notes", []) or []),
        "source_of_truth_ref": V2_ANDROID_TRUTH_BLOCK_REF,
    }


def _build_causal_explanation_zh(
    *,
    selected_runtime: str,
    selected_device: Optional[str],
    participation_tier: str,
    mode_basis: Dict[str, Any],
    readiness_basis: Dict[str, Any],
    acceptance_verdict: str,
    closure_basis: Dict[str, Any],
    blocking_reasons: List[str],
    unified_mode_model: Optional[Dict[str, Any]] = None,
) -> str:
    mode_state = str(mode_basis.get("mode_state") or "unknown")
    readiness_state = str(
        readiness_basis.get("readiness_state")
        or readiness_basis.get("runtime_readiness_verdict")
        or "unknown"
    )
    closed = closure_basis.get("is_fully_closed")
    unified_mode_model = dict(unified_mode_model or {})
    execution_location = str(
        unified_mode_model.get("execution_location") or selected_runtime or "unknown"
    )
    participation_layer = str(
        unified_mode_model.get("participation_layer") or participation_tier or "unknown"
    )
    governance_state = str(
        unified_mode_model.get("governance_state") or "delegated_execution"
    )

    if acceptance_verdict in {"quarantine", "reject"}:
        return (
            f"系统当前执行位置={execution_location}，设备={selected_device or 'none'}，"
            f"参与层级={participation_layer}，治理状态={governance_state}。"
            f"Android participation tier={participation_tier}。"
            f"由于 acceptance_verdict={acceptance_verdict}，closure 未被确认；"
            f"is_fully_closed=False，readiness={readiness_state}，mode={mode_state}。"
            f"阻断原因：{', '.join(blocking_reasons) if blocking_reasons else '无额外阻断原因'}。"
        )
    if acceptance_verdict == "accept_provisional":
        return (
            f"系统当前执行位置={execution_location}，设备={selected_device or 'none'}，"
            f"参与层级={participation_layer}，治理状态={governance_state}。"
            f"Android participation tier={participation_tier}。"
            f"结果处于 accept_provisional，说明 readiness={readiness_state}、mode={mode_state} "
            "已允许传播到 operator/board，但 closure 仍需更强证据。"
        )
    if acceptance_verdict == "accept" and closed is True:
        return (
            f"系统当前执行位置={execution_location}，设备={selected_device or 'none'}，"
            f"参与层级={participation_layer}，治理状态={governance_state}。"
            f"Android participation tier={participation_tier}。"
            f"mode={mode_state}、readiness={readiness_state}，acceptance_verdict=accept，"
            "因此该任务已经形成完整闭环。"
        )
    return (
        f"系统当前执行位置={execution_location}，设备={selected_device or 'none'}，"
        f"参与层级={participation_layer}，治理状态={governance_state}。"
        f"Android participation tier={participation_tier}。"
        f"mode={mode_state}、readiness={readiness_state}、"
        f"acceptance_verdict={acceptance_verdict}、is_fully_closed={closed}。"
    )


@dataclass(frozen=True)
class RuntimeDecisionReasoningBlock:
    task_id: str = ""
    selected_runtime: str = "unknown"
    selected_device: Optional[str] = None
    participation_tier: str = "unknown"
    mode_basis: Dict[str, Any] = field(default_factory=dict)
    readiness_basis: Dict[str, Any] = field(default_factory=dict)
    acceptance_verdict: str = "unknown"
    closure_basis: Dict[str, Any] = field(default_factory=dict)
    blocking_reasons: List[str] = field(default_factory=list)
    evidence_summary: Dict[str, Any] = field(default_factory=dict)
    source_of_truth_refs: List[str] = field(default_factory=list)
    unified_mode_model: Dict[str, Any] = field(default_factory=dict)
    generated_at: float = field(default_factory=time.time)
    authority: str = RUNTIME_DECISION_REASONING_BLOCK_AUTHORITY
    contract_version: str = RUNTIME_DECISION_REASONING_BLOCK_CONTRACT_VERSION

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "RuntimeDecisionReasoningBlock":
        payload = payload or {}
        return cls(
            task_id=str(payload.get("task_id") or ""),
            selected_runtime=str(payload.get("selected_runtime") or "unknown"),
            selected_device=_coalesce(
                payload.get("selected_device"),
                payload.get("selected_device_id"),
                payload.get("device_id"),
            ),
            participation_tier=str(
                payload.get("participation_tier")
                or payload.get("android_participation_tier")
                or "unknown"
            ),
            mode_basis=dict(payload.get("mode_basis") or {}),
            readiness_basis=dict(payload.get("readiness_basis") or {}),
            acceptance_verdict=str(payload.get("acceptance_verdict") or "unknown"),
            closure_basis=dict(payload.get("closure_basis") or {}),
            blocking_reasons=list(payload.get("blocking_reasons") or []),
            evidence_summary=dict(payload.get("evidence_summary") or {}),
            source_of_truth_refs=list(payload.get("source_of_truth_refs") or []),
            unified_mode_model=dict(payload.get("unified_mode_model") or {}),
            generated_at=float(payload.get("generated_at") or time.time()),
            authority=str(payload.get("_source") or payload.get("authority") or cls.authority),
            contract_version=str(
                payload.get("contract_version") or cls.contract_version
            ),
        )

    def to_dict(self) -> Dict[str, Any]:
        causal_explanation_zh = _build_causal_explanation_zh(
            selected_runtime=self.selected_runtime,
            selected_device=self.selected_device,
            participation_tier=self.participation_tier,
            mode_basis=self.mode_basis,
            readiness_basis=self.readiness_basis,
            acceptance_verdict=self.acceptance_verdict,
            closure_basis=self.closure_basis,
            blocking_reasons=self.blocking_reasons,
            unified_mode_model=self.unified_mode_model,
        )
        return {
            "task_id": self.task_id,
            "selected_runtime": self.selected_runtime,
            "selected_device": self.selected_device,
            "selected_device_id": self.selected_device,
            "device_id": self.selected_device,
            "participation_tier": self.participation_tier,
            "android_participation_tier": self.participation_tier,
            "mode_basis": dict(self.mode_basis),
            "readiness_basis": dict(self.readiness_basis),
            "acceptance_verdict": self.acceptance_verdict,
            "closure_basis": dict(self.closure_basis),
            "is_fully_closed": self.closure_basis.get("is_fully_closed"),
            "blocking_reasons": list(self.blocking_reasons),
            "evidence_summary": dict(self.evidence_summary),
            "source_of_truth_refs": list(self.source_of_truth_refs),
            "unified_mode_model": dict(self.unified_mode_model),
            "causal_explanation_zh": causal_explanation_zh,
            "generated_at": self.generated_at,
            "contract_version": self.contract_version,
            "authority": self.authority,
            "_source": self.authority,
        }


def overlay_runtime_decision_reasoning_block(
    base: Optional[Dict[str, Any]] = None,
    *,
    task_id: Optional[str] = None,
    selected_runtime: Optional[str] = None,
    selected_device: Optional[str] = None,
    android_truth_block: Any = None,
    participation_tier: Optional[str] = None,
    mode_state: Optional[str] = None,
    source_runtime_posture: Optional[str] = None,
    ready_to_route: Optional[bool] = None,
    readiness_summary: Optional[Dict[str, Any]] = None,
    readiness_notes: Optional[List[str]] = None,
    acceptance_verdict: Optional[str] = None,
    is_fully_closed: Optional[bool] = None,
    truth_chain_complete: Optional[bool] = None,
    completion_notified: Optional[bool] = None,
    task_completed: Optional[bool] = None,
    problem_solved: Optional[bool] = None,
    evidence_state: Optional[str] = None,
    trust_level: Optional[str] = None,
    operator_warning: Optional[bool] = None,
    source_channel: Optional[str] = None,
    android_proof_class: Optional[str] = None,
    blocking_reasons: Optional[List[str]] = None,
    evidence_summary: Optional[Dict[str, Any]] = None,
    source_of_truth_refs: Optional[List[str]] = None,
    governance_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    current = RuntimeDecisionReasoningBlock.from_dict(base)
    selected_device_value = _coalesce(selected_device, current.selected_device)
    truth_block = android_truth_block or _load_android_truth_block(selected_device_value)
    participation_tier_value = str(
        _coalesce(
            participation_tier,
            _truth_get(truth_block, "participation_tier"),
            current.participation_tier,
            "unknown",
        )
    )
    mode_basis = dict(current.mode_basis)
    resolved_mode_state = _coalesce(
        mode_state,
        mode_basis.get("mode_state"),
        _truth_get(truth_block, "device_mode"),
        "unknown",
    )

    if selected_runtime is None:
        selected_runtime_value = _derive_selected_runtime_default(
            current_selected_runtime=current.selected_runtime,
            resolved_mode_state=resolved_mode_state,
            selected_device=selected_device_value,
        )
    else:
        selected_runtime_value = selected_runtime

    truth_basis = _build_android_truth_basis(truth_block)
    mode_basis.update(
        {
            "mode_state": resolved_mode_state,
            "source_runtime_posture": _coalesce(
                source_runtime_posture,
                mode_basis.get("source_runtime_posture"),
            ),
            "selected_runtime": selected_runtime_value,
        }
    )
    if truth_basis:
        mode_basis.setdefault("android_device_mode", truth_basis.get("device_mode"))
        mode_basis.setdefault("android_mode_readiness_state", truth_basis.get("mode_readiness_state"))
        mode_basis.setdefault(
            "android_execution_mode_state",
            truth_basis.get("execution_mode_state"),
        )
        mode_basis.setdefault(
            "android_runtime_constrained",
            truth_basis.get("runtime_constrained"),
        )
        mode_basis.setdefault(
            "android_runtime_deferred",
            truth_basis.get("runtime_deferred"),
        )
        mode_basis.setdefault(
            "android_local_mode_active",
            truth_basis.get("local_mode_active"),
        )
        mode_basis.setdefault(
            "android_local_mode_gate_deferred",
            truth_basis.get("local_mode_gate_deferred"),
        )

    readiness_summary = dict(readiness_summary or {})
    readiness_basis = dict(current.readiness_basis)
    readiness_basis.update(
        {
            "ready_to_route": (
                ready_to_route
                if ready_to_route is not None
                else readiness_basis.get("ready_to_route")
            ),
            "readiness_state": _coalesce(
                readiness_summary.get("verdict"),
                readiness_summary.get("state"),
                readiness_basis.get("readiness_state"),
            ),
            "runtime_readiness_verdict": _coalesce(
                readiness_summary.get("verdict"),
                readiness_basis.get("runtime_readiness_verdict"),
            ),
            "notes": _dedupe_strings(
                list(readiness_basis.get("notes") or []) + list(readiness_notes or [])
            ),
            "android_truth_basis": truth_basis,
        }
    )
    for key, value in readiness_summary.items():
        if key not in {"verdict", "state"}:
            readiness_basis[key] = value

    closure_basis = dict(current.closure_basis)
    if is_fully_closed is not None:
        closure_basis["is_fully_closed"] = bool(is_fully_closed)
    if truth_chain_complete is not None:
        closure_basis["truth_chain_complete"] = bool(truth_chain_complete)
    if completion_notified is not None:
        closure_basis["completion_notified"] = bool(completion_notified)
    if task_completed is not None:
        closure_basis["task_completed"] = bool(task_completed)
    if problem_solved is not None:
        closure_basis["problem_solved"] = bool(problem_solved)
    if "is_fully_closed" in closure_basis and acceptance_verdict not in (None, ""):
        closure_basis["closure_reflects_acceptance"] = (
            acceptance_verdict == "accept" and bool(closure_basis.get("is_fully_closed"))
        ) or (
            acceptance_verdict in {"accept_provisional", "quarantine", "reject"}
            and not bool(closure_basis.get("is_fully_closed"))
        )

    summary = dict(current.evidence_summary)
    summary.update(evidence_summary or {})
    if evidence_state not in (None, ""):
        summary["evidence_state"] = evidence_state
    if trust_level not in (None, ""):
        summary["trust_level"] = trust_level
    if operator_warning is not None:
        summary["operator_warning"] = bool(operator_warning)
    if source_channel not in (None, ""):
        summary["source_channel"] = source_channel
    if android_proof_class not in (None, ""):
        summary["android_proof_class"] = android_proof_class
    if truth_basis:
        summary.setdefault(
            "android_truth_summary",
            {
                "dispatch_eligible": truth_basis.get("dispatch_eligible"),
                "local_inference_available": truth_basis.get("local_inference_available"),
                "model_ready": truth_basis.get("model_ready"),
                "accessibility_ready": truth_basis.get("accessibility_ready"),
                "current_fallback_tier": truth_basis.get("current_fallback_tier"),
            },
        )

    merged_blocking_reasons = _dedupe_strings(
        list(current.blocking_reasons)
        + list(blocking_reasons or [])
        + list(_truth_get(truth_block, "participation_blocking_reasons", []) or [])
        + list(_truth_get(truth_block, "degraded_reasons", []) or [])
        + list(readiness_notes or [])
    )

    merged_refs = _dedupe_strings(
        list(current.source_of_truth_refs)
        + list(source_of_truth_refs or [])
        + [RUNTIME_DECISION_REASONING_BLOCK_AUTHORITY]
        + ([V2_ANDROID_TRUTH_BLOCK_REF] if truth_block is not None else [])
    )
    from core.v2_unified_mode_model import build_unified_mode_model  # noqa: PLC0415

    unified_mode_model = build_unified_mode_model(
        selected_runtime=selected_runtime_value,
        selected_device=selected_device_value,
        participation_tier=participation_tier_value,
        device_mode=resolved_mode_state,
        mode_readiness_state=_truth_get(truth_block, "mode_readiness_state"),
        android_truth_block=truth_block,
        governance_state=governance_state,
        blocking_reasons=merged_blocking_reasons,
        source_of_truth_refs=merged_refs,
    )
    mode_basis["execution_location"] = unified_mode_model.get("execution_location")
    mode_basis["participation_layer"] = unified_mode_model.get("participation_layer")
    mode_basis["governance_state"] = unified_mode_model.get("governance_state")

    block = RuntimeDecisionReasoningBlock(
        task_id=str(_coalesce(task_id, current.task_id, "")),
        selected_runtime=str(selected_runtime_value or "unknown"),
        selected_device=selected_device_value,
        participation_tier=participation_tier_value,
        mode_basis=mode_basis,
        readiness_basis=readiness_basis,
        acceptance_verdict=str(_coalesce(acceptance_verdict, current.acceptance_verdict, "unknown")),
        closure_basis=closure_basis,
        blocking_reasons=merged_blocking_reasons,
        evidence_summary=summary,
        source_of_truth_refs=merged_refs,
        unified_mode_model=unified_mode_model,
    )
    return block.to_dict()


def build_runtime_decision_reasoning_block(**kwargs: Any) -> Dict[str, Any]:
    """构建新的统一运行时决策推理块。"""
    return overlay_runtime_decision_reasoning_block(None, **kwargs)


__all__ = [
    "RUNTIME_DECISION_REASONING_BLOCK_AUTHORITY",
    "RUNTIME_DECISION_REASONING_BLOCK_CONTRACT_VERSION",
    "RuntimeDecisionReasoningBlock",
    "build_runtime_decision_reasoning_block",
    "overlay_runtime_decision_reasoning_block",
]
