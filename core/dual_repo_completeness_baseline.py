"""双仓（V2 + Android）系统完整性基线（可执行快照）。"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

DUAL_REPO_COMPLETENESS_BASELINE_AUTHORITY = (
    "DUAL_REPO_COMPLETENESS_BASELINE_AUTHORITY::"
    "core.dual_repo_completeness_baseline.build_dual_repo_completeness_baseline "
    "是 V2 + Android 从 clone 到端到端观测面的阶段化完整性基线入口。"
)

CAPABILITY_CLASS_FULLY_WIRED = "fully_wired"
CAPABILITY_CLASS_PARTIALLY_WIRED = "partially_wired"
CAPABILITY_CLASS_NOMINAL_ONLY = "nominal_only"
CAPABILITY_CLASS_MISSING = "missing"

_STAGE_ORDER = (
    "clone",
    "setup",
    "config",
    "startup",
    "device_ingress_auth",
    "registration",
    "dispatch_participation",
    "mesh",
    "result_return",
    "truth_panel_surface",
)

_SETUP_FILES = (
    "requirements.txt",
    "requirements-dev.txt",
    "pyproject.toml",
    "main.py",
)


@dataclass(frozen=True)
class _CapabilitySignal:
    capability_id: str
    label_zh: str
    classification: str
    evidence: List[str]
    gaps: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "label_zh": self.label_zh,
            "classification": self.classification,
            "evidence": list(self.evidence),
            "gaps": list(self.gaps),
        }


def build_dual_repo_completeness_baseline(
    *,
    truth_payload: Optional[Dict[str, Any]] = None,
    board_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构建从 clone 到端态可观测的双仓完整性基线快照。"""
    truth_payload = dict(truth_payload or {})
    board_payload = dict(board_payload or {})
    acceptance_chain = _build_acceptance_chain(
        truth_payload=truth_payload,
        board_payload=board_payload,
    )

    chain_by_stage = {entry.get("stage"): entry for entry in acceptance_chain.get("stages", [])}
    startup_readiness = _ensure_dict(truth_payload.get("startup_readiness"))
    runtime_reasoning = _ensure_dict(truth_payload.get("runtime_decision_reasoning"))
    participation_truth = _ensure_dict(truth_payload.get("participation_truth_consumption"))
    shared_execution_visibility = _ensure_dict(truth_payload.get("shared_execution_visibility"))
    board_participation = _ensure_dict(board_payload.get("participation_truth_consumption"))
    board_visibility = _ensure_dict(board_payload.get("shared_execution_visibility"))

    clone_passed, clone_details = _check_clone_stage()
    setup_passed, setup_details = _check_setup_stage()
    config_passed, config_details = _check_config_stage()
    startup_passed = bool(startup_readiness.get("ready_to_route"))
    startup_details = {
        "ready_to_route": bool(startup_readiness.get("ready_to_route")),
        "dispatch_mode": startup_readiness.get("dispatch_mode"),
        "readiness_notes": list(startup_readiness.get("readiness_notes") or []),
    }
    ingress_stage = _rename_chain_stage(_stage_from_chain(chain_by_stage, "android_entry"), "device_ingress_auth")
    registration_stage = _rename_chain_stage(_stage_from_chain(chain_by_stage, "registration"), "registration")
    participation_stage = _rename_chain_stage(
        _stage_from_chain(chain_by_stage, "participation_dispatchability"),
        "dispatch_participation",
    )
    mesh_stage = _rename_chain_stage(_stage_from_chain(chain_by_stage, "mesh_lifecycle"), "mesh")
    result_stage = _rename_chain_stage(_stage_from_chain(chain_by_stage, "result_backflow"), "result_return")
    surface_stage = _rename_chain_stage(_stage_from_chain(chain_by_stage, "surface_visibility"), "truth_panel_surface")

    stages = [
        _stage_entry("clone", clone_passed, "clone_baseline", clone_details),
        _stage_entry("setup", setup_passed, "setup_baseline", setup_details),
        _stage_entry("config", config_passed, "config_baseline", config_details),
        _stage_entry("startup", startup_passed, "startup_readiness", startup_details),
        ingress_stage,
        registration_stage,
        _merge_stage_details(
            participation_stage,
            {"runtime_selected_device": runtime_reasoning.get("selected_device")},
        ),
        mesh_stage,
        result_stage,
        _merge_stage_details(
            surface_stage,
            {
                "runtime_truth_visible": bool(shared_execution_visibility and participation_truth),
                "board_visible": bool(board_visibility and board_participation),
            },
        ),
    ]

    blocking_stages = [item for item in stages if item["status"] != "passed"]
    capability_inventory = _build_capability_inventory(
        clone_passed=clone_passed,
        setup_passed=setup_passed,
        config_passed=config_passed,
        startup_passed=startup_passed,
        acceptance_chain=acceptance_chain,
        participation_truth=participation_truth,
        board_participation=board_participation,
        shared_execution_visibility=shared_execution_visibility,
        board_visibility=board_visibility,
    )
    classification_counts = _classification_counts(capability_inventory)
    explicit_gaps = _collect_explicit_gaps(stages=stages, capabilities=capability_inventory)

    return {
        "baseline_id": f"dual_repo_baseline_{uuid.uuid4().hex[:12]}",
        "authority": DUAL_REPO_COMPLETENESS_BASELINE_AUTHORITY,
        "overall_status": "passed" if not blocking_stages else "failed",
        "regression_ready": not blocking_stages,
        "stage_order": list(_STAGE_ORDER),
        "stage_count": len(stages),
        "passed_stage_count": sum(1 for item in stages if item["status"] == "passed"),
        "blocking_stage_ids": [item["stage"] for item in blocking_stages],
        "current_stage": blocking_stages[0]["stage"] if blocking_stages else stages[-1]["stage"],
        "acceptance_chain_status": acceptance_chain.get("overall_status"),
        "capability_inventory": [capability.to_dict() for capability in capability_inventory],
        "classification_counts": classification_counts,
        "explicit_gaps": explicit_gaps,
        "acceptance_chain": acceptance_chain,
        "stages": stages,
        "summary_zh": _build_summary(
            blocking_stages=blocking_stages,
            classification_counts=classification_counts,
            explicit_gaps=explicit_gaps,
        ),
        "_source": "core.dual_repo_completeness_baseline.build_dual_repo_completeness_baseline",
        "_timestamp": time.time(),
    }


def _build_acceptance_chain(*, truth_payload: Dict[str, Any], board_payload: Dict[str, Any]) -> Dict[str, Any]:
    from core.cross_repo_acceptance_chain import build_cross_repo_acceptance_chain

    return build_cross_repo_acceptance_chain(
        truth_payload=truth_payload,
        board_payload=board_payload,
    )


def _check_clone_stage() -> tuple[bool, Dict[str, Any]]:
    root_dir = _repo_root()
    required_paths = ["README.md", "main.py", "core/routes/projection.py"]
    resolved = [path for path in required_paths if os.path.isfile(os.path.join(root_dir, path))]
    missing = [path for path in required_paths if path not in resolved]
    return not missing, {
        "repo_root": root_dir,
        "required_paths": required_paths,
        "resolved_paths": resolved,
        "missing_paths": missing,
    }


def _check_setup_stage() -> tuple[bool, Dict[str, Any]]:
    root_dir = _repo_root()
    present = [name for name in _SETUP_FILES if os.path.isfile(os.path.join(root_dir, name))]
    missing = [name for name in _SETUP_FILES if name not in present]
    return not missing, {
        "required_setup_files": list(_SETUP_FILES),
        "present_setup_files": present,
        "missing_setup_files": missing,
    }


def _check_config_stage() -> tuple[bool, Dict[str, Any]]:
    root_dir = _repo_root()
    config_path = os.path.join(root_dir, "config.json")
    parsed = False
    parse_error: Optional[str] = None
    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as fp:
                json.load(fp)
            parsed = True
        except Exception as exc:  # noqa: BLE001
            parse_error = str(exc)
    has_unified_config = False
    try:
        import core.unified_config  # noqa: F401

        has_unified_config = True
    except Exception:
        has_unified_config = False
    passed = bool(parsed and has_unified_config)
    return passed, {
        "config_path": config_path,
        "config_exists": os.path.isfile(config_path),
        "config_json_valid": parsed,
        "config_parse_error": parse_error,
        "unified_config_importable": has_unified_config,
    }


def _build_capability_inventory(
    *,
    clone_passed: bool,
    setup_passed: bool,
    config_passed: bool,
    startup_passed: bool,
    acceptance_chain: Dict[str, Any],
    participation_truth: Dict[str, Any],
    board_participation: Dict[str, Any],
    shared_execution_visibility: Dict[str, Any],
    board_visibility: Dict[str, Any],
) -> List[_CapabilitySignal]:
    chain_stages = {entry.get("stage"): entry for entry in acceptance_chain.get("stages", [])}
    capabilities: List[_CapabilitySignal] = []
    capabilities.append(
        _classify_capability(
            capability_id="clone_setup_config_startup",
            label_zh="clone/setup/config/startup 可达性",
            passed_flags=[clone_passed, setup_passed, config_passed, startup_passed],
            evidence=[
                f"clone={clone_passed}",
                f"setup={setup_passed}",
                f"config={config_passed}",
                f"startup={startup_passed}",
            ],
            gap_labels=[
                "clone 缺失关键文件",
                "setup 依赖入口不完整",
                "config 无法解析或 unified_config 不可用",
                "startup_readiness 未就绪",
            ],
        )
    )
    capabilities.append(
        _from_chain_stage(
            capability_id="device_ingress_registration_auth",
            label_zh="设备接入/注册/鉴权边界",
            stage_entries=[
                chain_stages.get("android_entry"),
                chain_stages.get("registration"),
            ],
        )
    )
    capabilities.append(
        _from_chain_stage(
            capability_id="dispatch_participation",
            label_zh="调度参与闭环",
            stage_entries=[chain_stages.get("participation_dispatchability")],
        )
    )
    capabilities.append(
        _from_chain_stage(
            capability_id="mesh_result_return",
            label_zh="mesh + result return",
            stage_entries=[
                chain_stages.get("mesh_lifecycle"),
                chain_stages.get("result_backflow"),
            ],
        )
    )
    surface_pass = bool(
        participation_truth and board_participation and shared_execution_visibility and board_visibility
    )
    capabilities.append(
        _classify_capability(
            capability_id="truth_panel_surfaces",
            label_zh="truth/panel 端态观测面",
            passed_flags=[surface_pass, chain_stages.get("surface_visibility", {}).get("status") == "passed"],
            evidence=[
                f"runtime_truth_blocks={bool(participation_truth and shared_execution_visibility)}",
                f"board_blocks={bool(board_participation and board_visibility)}",
                f"surface_visibility_stage={chain_stages.get('surface_visibility', {}).get('status')}",
            ],
            gap_labels=[
                "runtime-truth 关键块缺失",
                "surface_visibility stage 未通过",
            ],
        )
    )
    return capabilities


def _from_chain_stage(
    *,
    capability_id: str,
    label_zh: str,
    stage_entries: Sequence[Optional[Dict[str, Any]]],
) -> _CapabilitySignal:
    checks = [entry for entry in stage_entries if isinstance(entry, dict)]
    passed_flags = [entry.get("status") == "passed" for entry in checks]
    evidence = [f"{entry.get('stage')}={entry.get('status')}" for entry in checks]
    gaps = [f"{entry.get('stage')}:{entry.get('summary')}" for entry in checks if entry.get("status") != "passed"]
    if not checks:
        return _CapabilitySignal(
            capability_id=capability_id,
            label_zh=label_zh,
            classification=CAPABILITY_CLASS_MISSING,
            evidence=["missing stage evidence"],
            gaps=["stage evidence missing"],
        )
    return _classify_capability(
        capability_id=capability_id,
        label_zh=label_zh,
        passed_flags=passed_flags,
        evidence=evidence,
        gap_labels=gaps or ["no explicit stage gaps"],
    )


def _classify_capability(
    *,
    capability_id: str,
    label_zh: str,
    passed_flags: Sequence[bool],
    evidence: Sequence[str],
    gap_labels: Sequence[str],
) -> _CapabilitySignal:
    total = len(passed_flags)
    passed = sum(1 for item in passed_flags if item)
    if total == 0:
        classification = CAPABILITY_CLASS_MISSING
    elif passed == total:
        classification = CAPABILITY_CLASS_FULLY_WIRED
    elif passed > 0:
        classification = CAPABILITY_CLASS_PARTIALLY_WIRED
    elif any(evidence):
        classification = CAPABILITY_CLASS_NOMINAL_ONLY
    else:
        classification = CAPABILITY_CLASS_MISSING
    return _CapabilitySignal(
        capability_id=capability_id,
        label_zh=label_zh,
        classification=classification,
        evidence=list(evidence),
        gaps=list(gap_labels if classification != CAPABILITY_CLASS_FULLY_WIRED else []),
    )


def _classification_counts(capabilities: Sequence[_CapabilitySignal]) -> Dict[str, int]:
    counts = {
        CAPABILITY_CLASS_FULLY_WIRED: 0,
        CAPABILITY_CLASS_PARTIALLY_WIRED: 0,
        CAPABILITY_CLASS_NOMINAL_ONLY: 0,
        CAPABILITY_CLASS_MISSING: 0,
    }
    for item in capabilities:
        counts[item.classification] = counts.get(item.classification, 0) + 1
    return counts


def _collect_explicit_gaps(
    *,
    stages: Sequence[Dict[str, Any]],
    capabilities: Sequence[_CapabilitySignal],
) -> List[Dict[str, Any]]:
    gaps: List[Dict[str, Any]] = []
    for stage in stages:
        if stage.get("status") == "passed":
            continue
        gaps.append(
            {
                "type": "stage",
                "stage": stage.get("stage"),
                "failure_boundary": stage.get("failure_boundary"),
                "summary": stage.get("summary"),
            }
        )
    for capability in capabilities:
        if capability.classification == CAPABILITY_CLASS_FULLY_WIRED:
            continue
        gaps.append(
            {
                "type": "capability",
                "capability_id": capability.capability_id,
                "classification": capability.classification,
                "gaps": list(capability.gaps),
            }
        )
    return gaps


def _build_summary(
    *,
    blocking_stages: Sequence[Dict[str, Any]],
    classification_counts: Dict[str, int],
    explicit_gaps: Sequence[Dict[str, Any]],
) -> str:
    if not blocking_stages:
        return (
            "双仓完整性基线通过：clone→setup→config→startup→ingress→registration→"
            "dispatch/participation→mesh→result_return→truth_panel_surface 全阶段可验证。"
        )
    stage_names = ",".join(stage.get("stage", "unknown") for stage in blocking_stages)
    return (
        f"双仓完整性基线未通过，阻断阶段={stage_names}；"
        f"分类统计={classification_counts}；显式缺口数={len(explicit_gaps)}。"
    )


def _stage_from_chain(chain_by_stage: Dict[str, Dict[str, Any]], stage_name: str) -> Dict[str, Any]:
    stage = chain_by_stage.get(stage_name)
    if isinstance(stage, dict):
        return dict(stage)
    return _stage_entry(stage_name, False, "chain_stage_missing", {"reason": "stage missing from acceptance chain"})


def _merge_stage_details(stage: Dict[str, Any], extra_details: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(stage)
    details = _ensure_dict(stage.get("details"))
    details.update(extra_details)
    merged["details"] = details
    return merged


def _rename_chain_stage(stage: Dict[str, Any], stage_name: str) -> Dict[str, Any]:
    renamed = dict(stage)
    original_name = stage.get("stage")
    renamed["stage"] = stage_name
    details = _ensure_dict(renamed.get("details"))
    details["source_stage"] = original_name
    renamed["details"] = details
    return renamed


def _stage_entry(stage: str, passed: bool, failure_boundary: str, details: Dict[str, Any]) -> Dict[str, Any]:
    status = "passed" if passed else "failed"
    return {
        "stage": stage,
        "status": status,
        "failure_boundary": failure_boundary,
        "summary": f"{stage} {'ok' if passed else 'not_ready'}",
        "details": dict(details),
    }


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ensure_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


__all__ = [
    "DUAL_REPO_COMPLETENESS_BASELINE_AUTHORITY",
    "CAPABILITY_CLASS_FULLY_WIRED",
    "CAPABILITY_CLASS_PARTIALLY_WIRED",
    "CAPABILITY_CLASS_NOMINAL_ONLY",
    "CAPABILITY_CLASS_MISSING",
    "build_dual_repo_completeness_baseline",
]
