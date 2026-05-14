"""V2 统一模式模型。

把当前运行状态拆成三层：

* execution_location —— 执行发生在哪里
* participation_layer —— Android 当前参与到了哪一层
* governance_state —— 当前治理/接管/约束处于什么状态

该模块是只读聚合层，不引入新存储。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

UNIFIED_MODE_MODEL_AUTHORITY = (
    "UNIFIED_MODE_MODEL_V1::core.v2_unified_mode_model is the canonical "
    "V2-side layered mode model for execution location, participation layer, "
    "and governance state."
)
UNIFIED_MODE_MODEL_CONTRACT_VERSION = "1.0.0"

EXECUTION_LOCATION_VALUES: tuple[str, ...] = (
    "v2_local",
    "android_local",
    "android_delegated",
)
PARTICIPATION_LAYER_VALUES: tuple[str, ...] = (
    "offline_local_only",
    "session_attached",
    "cross_device_enabled",
    "dispatch_eligible",
    "distributed_participant",
)
GOVERNANCE_LAYER_VALUES: tuple[str, ...] = (
    "delegated_execution",
    "takeover_pending",
    "takeover_active",
    "governance_blocked",
    "deferred",
    "constrained",
)

_PARTICIPATION_LAYER_MAP: Dict[str, str] = {
    "local_only": "offline_local_only",
    # control_only / cross_device_capable / fully_attached 仍然保留细粒度 tier，
    # 但在 owner-facing 分层模型里都属于“已接入会话、尚未进入可派发层”的同一层。
    "control_only": "session_attached",
    "cross_device_capable": "session_attached",
    "fully_attached": "session_attached",
    "cross_device_enabled": "cross_device_enabled",
    "dispatch_eligible": "dispatch_eligible",
    "distributed_participant": "distributed_participant",
}


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _dedupe(values: Iterable[Any]) -> List[str]:
    result: List[str] = []
    seen = set()
    for value in values:
        if value in (None, ""):
            continue
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _truth_get(block: Any, key: str, default: Any = None) -> Any:
    if block is None:
        return default
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def map_participation_tier_to_layer(participation_tier: Optional[str]) -> str:
    return _PARTICIPATION_LAYER_MAP.get(
        str(participation_tier or "").strip(),
        "offline_local_only",
    )


def _select_governance_device_entry(
    governance_state: Optional[Dict[str, Any]],
    selected_device: Optional[str],
) -> Dict[str, Any]:
    governance_state = dict(governance_state or {})
    devices = list(governance_state.get("devices") or [])
    if not devices:
        return {}
    if selected_device:
        for item in devices:
            if str(item.get("device_id") or "") == str(selected_device):
                return dict(item)
    return dict(devices[0])


def _select_governance_policy(
    governance_state: Optional[Dict[str, Any]],
    selected_device: Optional[str],
    device_entry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if device_entry and isinstance(device_entry.get("governance_policy"), dict):
        return dict(device_entry.get("governance_policy") or {})
    governance_state = dict(governance_state or {})
    policy_layer = dict(governance_state.get("policy_layer") or {})
    devices = list(policy_layer.get("devices") or [])
    if selected_device:
        for item in devices:
            if str(item.get("device_id") or "") == str(selected_device):
                return dict(item.get("policy_outcome") or {})
    if devices:
        return dict((devices[0] or {}).get("policy_outcome") or {})
    return {}


def derive_execution_location(
    *,
    selected_runtime: Optional[str],
    selected_device: Optional[str],
    device_mode: Optional[str],
) -> str:
    runtime = str(selected_runtime or "").strip()
    mode = str(device_mode or "").strip()
    if runtime == "android_delegated":
        return "android_delegated"
    if runtime == "android_local":
        return "android_local"
    if mode == "local" and selected_device:
        return "android_local"
    return "v2_local"


def derive_governance_state(
    *,
    selected_runtime: Optional[str],
    selected_device: Optional[str],
    blocking_reasons: Optional[List[str]] = None,
    android_truth_block: Any = None,
    governance_state: Optional[Dict[str, Any]] = None,
    governance_policy: Optional[Dict[str, Any]] = None,
) -> tuple[str, Dict[str, Any]]:
    device_entry = _select_governance_device_entry(governance_state, selected_device)
    policy = dict(
        governance_policy
        or _select_governance_policy(governance_state, selected_device, device_entry)
        or {}
    )
    reasons = _dedupe(
        list(blocking_reasons or [])
        + list(policy.get("dependency_classification", {}).get("reasons") or [])
        + list(_truth_get(android_truth_block, "degraded_reasons", []) or [])
        + list(_truth_get(android_truth_block, "participation_blocking_reasons", []) or [])
    )
    operation_state = str(policy.get("operation_state") or "").strip().lower()
    automatic_decision = str(policy.get("automatic_decision") or "").strip().lower()
    primary_path = str(policy.get("primary_path") or "").strip().lower()
    takeover_active = bool(
        _coalesce(
            device_entry.get("takeover_active") if device_entry else None,
            False,
        )
    )
    mode_readiness_state = str(
        _truth_get(android_truth_block, "mode_readiness_state", "") or ""
    ).strip().lower()
    if operation_state == "hard_block":
        return "governance_blocked", {
            "operation_state": operation_state,
            "automatic_decision": automatic_decision,
            "primary_path": primary_path,
            "takeover_active": takeover_active,
            "reasons": reasons,
        }
    if takeover_active:
        return "takeover_active", {
            "operation_state": operation_state,
            "automatic_decision": automatic_decision,
            "primary_path": primary_path,
            "takeover_active": takeover_active,
            "reasons": reasons,
        }
    if primary_path == "takeover":
        return "takeover_pending", {
            "operation_state": operation_state,
            "automatic_decision": automatic_decision,
            "primary_path": primary_path,
            "takeover_active": takeover_active,
            "reasons": reasons,
        }
    if automatic_decision == "hold" or any(
        "defer" in reason
        for reason in reasons
    ):
        return "deferred", {
            "operation_state": operation_state,
            "automatic_decision": automatic_decision,
            "primary_path": primary_path,
            "takeover_active": takeover_active,
            "reasons": reasons,
        }
    degraded_reason_tokens = ("constrained", "degraded", "stale", "blocked_no_proof")
    if (
        operation_state == "soft_degraded"
        or mode_readiness_state in {"degraded", "transitioning"}
        or any(
            any(token in reason for token in degraded_reason_tokens)
            for reason in reasons
        )
    ):
        return "constrained", {
            "operation_state": operation_state,
            "automatic_decision": automatic_decision,
            "primary_path": primary_path,
            "takeover_active": takeover_active,
            "reasons": reasons,
        }
    if selected_runtime == "android_delegated" or selected_device:
        return "delegated_execution", {
            "operation_state": operation_state,
            "automatic_decision": automatic_decision,
            "primary_path": primary_path or "delegated_execution",
            "takeover_active": takeover_active,
            "reasons": reasons,
        }
    return "delegated_execution", {
        "operation_state": operation_state,
        "automatic_decision": automatic_decision,
        "primary_path": primary_path or "delegated_execution",
        "takeover_active": takeover_active,
        "reasons": reasons,
    }


@dataclass(frozen=True)
class UnifiedModeModel:
    execution_location: str = "v2_local"
    participation_layer: str = "offline_local_only"
    governance_state: str = "delegated_execution"
    selected_runtime: str = "unknown"
    selected_device: Optional[str] = None
    participation_tier: str = "unknown"
    device_mode: str = "unknown"
    mode_readiness_state: Optional[str] = None
    governance_basis: Dict[str, Any] = field(default_factory=dict)
    blocking_reasons: List[str] = field(default_factory=list)
    source_of_truth_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_location": self.execution_location,
            "participation_layer": self.participation_layer,
            "governance_state": self.governance_state,
            "selected_runtime": self.selected_runtime,
            "selected_device": self.selected_device,
            "participation_tier": self.participation_tier,
            "device_mode": self.device_mode,
            "mode_readiness_state": self.mode_readiness_state,
            "governance_basis": dict(self.governance_basis),
            "blocking_reasons": list(self.blocking_reasons),
            "source_of_truth_refs": list(self.source_of_truth_refs),
            "owner_summary_zh": (
                f"执行位置={self.execution_location}；"
                f"参与层级={self.participation_layer}；"
                f"治理状态={self.governance_state}。"
            ),
            "authority": UNIFIED_MODE_MODEL_AUTHORITY,
            "contract_version": UNIFIED_MODE_MODEL_CONTRACT_VERSION,
            "_source": UNIFIED_MODE_MODEL_AUTHORITY,
        }


def build_unified_mode_model(
    *,
    selected_runtime: Optional[str] = None,
    selected_device: Optional[str] = None,
    participation_tier: Optional[str] = None,
    device_mode: Optional[str] = None,
    mode_readiness_state: Optional[str] = None,
    android_truth_block: Any = None,
    governance_state: Optional[Dict[str, Any]] = None,
    governance_policy: Optional[Dict[str, Any]] = None,
    blocking_reasons: Optional[List[str]] = None,
    source_of_truth_refs: Optional[List[str]] = None,
) -> Dict[str, Any]:
    truth_participation_tier = _truth_get(android_truth_block, "participation_tier")
    truth_device_mode = _truth_get(android_truth_block, "device_mode")
    truth_mode_readiness = _truth_get(android_truth_block, "mode_readiness_state")
    resolved_participation_tier = str(
        _coalesce(participation_tier, truth_participation_tier, "local_only")
    )
    resolved_device_mode = str(_coalesce(device_mode, truth_device_mode, "unknown"))
    resolved_mode_readiness = _coalesce(
        mode_readiness_state,
        truth_mode_readiness,
    )
    execution_location = derive_execution_location(
        selected_runtime=selected_runtime,
        selected_device=selected_device,
        device_mode=resolved_device_mode,
    )
    participation_layer = map_participation_tier_to_layer(resolved_participation_tier)
    governance_value, governance_basis = derive_governance_state(
        selected_runtime=selected_runtime,
        selected_device=selected_device,
        blocking_reasons=blocking_reasons,
        android_truth_block=android_truth_block,
        governance_state=governance_state,
        governance_policy=governance_policy,
    )
    model = UnifiedModeModel(
        execution_location=execution_location,
        participation_layer=participation_layer,
        governance_state=governance_value,
        selected_runtime=str(selected_runtime or "unknown"),
        selected_device=selected_device,
        participation_tier=resolved_participation_tier,
        device_mode=resolved_device_mode,
        mode_readiness_state=(
            str(resolved_mode_readiness) if resolved_mode_readiness not in (None, "") else None
        ),
        governance_basis=governance_basis,
        blocking_reasons=_dedupe(
            list(blocking_reasons or [])
            + list(_truth_get(android_truth_block, "participation_blocking_reasons", []) or [])
            + list(_truth_get(android_truth_block, "degraded_reasons", []) or [])
        ),
        source_of_truth_refs=_dedupe(
            list(source_of_truth_refs or []) + [UNIFIED_MODE_MODEL_AUTHORITY]
        ),
    )
    return model.to_dict()


def build_unified_mode_model_catalog() -> Dict[str, Any]:
    return {
        "execution_location_layer": list(EXECUTION_LOCATION_VALUES),
        "participation_layer": list(PARTICIPATION_LAYER_VALUES),
        "governance_layer": list(GOVERNANCE_LAYER_VALUES),
        "owner_summary_zh": (
            "统一模式模型现在固定分成三层：执行位置、参与层级、治理状态；"
            "不再要求 owner/operator 自行从 mode、tier、takeover、deferred 等字段中重建语义。"
        ),
        "authority": UNIFIED_MODE_MODEL_AUTHORITY,
        "contract_version": UNIFIED_MODE_MODEL_CONTRACT_VERSION,
        "_source": UNIFIED_MODE_MODEL_AUTHORITY,
    }


__all__ = [
    "UNIFIED_MODE_MODEL_AUTHORITY",
    "UNIFIED_MODE_MODEL_CONTRACT_VERSION",
    "EXECUTION_LOCATION_VALUES",
    "PARTICIPATION_LAYER_VALUES",
    "GOVERNANCE_LAYER_VALUES",
    "UnifiedModeModel",
    "map_participation_tier_to_layer",
    "derive_execution_location",
    "derive_governance_state",
    "build_unified_mode_model",
    "build_unified_mode_model_catalog",
]
