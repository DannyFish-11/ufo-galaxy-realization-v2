"""Cross-repo schema/contract version gate for critical V2↔Android boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping

CROSS_REPO_SCHEMA_GATE_AUTHORITY: str = (
    "CROSS_REPO_SCHEMA_GATE_AUTHORITY::contracts.cross_repo_schema_version_gate::"
    "minimal critical gate for AIP message types + projection/closure truth contract"
)
CROSS_REPO_SCHEMA_GATE_VERSION: str = "1.0.0"

ANDROID_AUDITED_REF: str = "3258b09b25d5279773122e86a7b1945586ff470b"
ANDROID_AIP_MODELS_SOURCE_SHA: str = "3404657c7eda895978ec672e1e176152161b8fe1"
ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA: str = "7838103668a19800ed74d3133f4f5e671359d65a"
ANDROID_AIP_MODELS_ANCHOR: str = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/protocol/AipModels.kt"
)
ANDROID_COMPLETION_CLOSURE_ANCHOR: str = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/"
    "AndroidCompletionClosureUplinkContract.kt"
)
ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION: str = "1"

REQUIRED_AIP_MESSAGE_TYPES: FrozenSet[str] = frozenset(
    {
        "reconciliation_signal",
        "handoff_envelope_v2",
        "handoff_envelope_v2_result",
        "takeover_request",
        "takeover_response",
        "mesh_join",
        "mesh_result",
        "mesh_leave",
        "device_state_snapshot",
        "device_execution_event",
        "device_acceptance_report",
    }
)

REQUIRED_RUNTIME_TRUTH_TOP_LEVEL_FIELDS: FrozenSet[str] = frozenset(
    {
        "outward_truth",
        "task_truth",
        "startup_readiness",
        "runtime_decision_reasoning",
        "shared_execution_visibility",
        "participation_truth_consumption",
        "truth_acceptance_closure_contract",
    }
)

REQUIRED_TRUTH_ACCEPTANCE_CONTRACT_FIELDS: FrozenSet[str] = frozenset(
    {
        "authority_truth_source",
        "acceptance_closure_truth",
        "outward_projection_truth",
        "diagnostics_snapshot",
        "gate_candidate",
        "schema_gate",
    }
)

REQUIRED_ACCEPTANCE_CLOSURE_FIELDS: FrozenSet[str] = frozenset(
    {
        "authority_completion_truth",
        "acceptance_completion_truth",
        "closure_candidate_state",
        "completion_state",
    }
)


@dataclass
class CrossRepoSchemaGateReport:
    passed: bool
    issues: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "issues": list(self.issues),
            "gate_version": CROSS_REPO_SCHEMA_GATE_VERSION,
            "android_audited_ref": ANDROID_AUDITED_REF,
            "android_aip_models_source_sha": ANDROID_AIP_MODELS_SOURCE_SHA,
            "android_completion_closure_source_sha": ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA,
        }


def build_projection_schema_gate_metadata() -> Dict[str, str]:
    return {
        "authority": CROSS_REPO_SCHEMA_GATE_AUTHORITY,
        "gate_version": CROSS_REPO_SCHEMA_GATE_VERSION,
        "android_completion_closure_uplink_schema_version": ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION,
        "android_aip_models_source_sha": ANDROID_AIP_MODELS_SOURCE_SHA,
        "android_completion_closure_source_sha": ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA,
    }


def verify_cross_repo_schema_gate(
    *,
    message_type_values: Iterable[str],
    runtime_truth_payload: Mapping[str, Any],
) -> CrossRepoSchemaGateReport:
    issues: List[str] = []
    message_type_set = set(message_type_values)
    missing_msg_types = sorted(REQUIRED_AIP_MESSAGE_TYPES - message_type_set)
    if missing_msg_types:
        issues.append(
            f"Missing required cross-repo AIP message types: {missing_msg_types}. "
            "If this is intentional, update both repositories and bump CROSS_REPO_SCHEMA_GATE_VERSION."
        )

    payload = dict(runtime_truth_payload or {})
    missing_top_level = sorted(k for k in REQUIRED_RUNTIME_TRUTH_TOP_LEVEL_FIELDS if k not in payload)
    if missing_top_level:
        issues.append(
            f"runtime-truth projection is missing required top-level fields: {missing_top_level}."
        )

    contract = payload.get("truth_acceptance_closure_contract")
    if not isinstance(contract, Mapping):
        issues.append("truth_acceptance_closure_contract must be a mapping.")
    else:
        missing_contract = sorted(k for k in REQUIRED_TRUTH_ACCEPTANCE_CONTRACT_FIELDS if k not in contract)
        if missing_contract:
            issues.append(
                "truth_acceptance_closure_contract is missing required fields: "
                f"{missing_contract}."
            )

        acceptance = contract.get("acceptance_closure_truth")
        if isinstance(acceptance, Mapping):
            missing_acceptance = sorted(k for k in REQUIRED_ACCEPTANCE_CLOSURE_FIELDS if k not in acceptance)
            if missing_acceptance:
                issues.append(
                    "acceptance_closure_truth is missing required fields: "
                    f"{missing_acceptance}."
                )
        else:
            issues.append("acceptance_closure_truth must be a mapping.")

        schema_gate = contract.get("schema_gate")
        if isinstance(schema_gate, Mapping):
            observed_gate_version = str(schema_gate.get("gate_version") or "")
            if observed_gate_version != CROSS_REPO_SCHEMA_GATE_VERSION:
                issues.append(
                    "schema_gate.gate_version drift detected: "
                    f"expected {CROSS_REPO_SCHEMA_GATE_VERSION!r}, got {observed_gate_version!r}."
                )
            observed_android_schema_version = str(
                schema_gate.get("android_completion_closure_uplink_schema_version") or ""
            )
            if observed_android_schema_version != ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION:
                issues.append(
                    "schema_gate.android_completion_closure_uplink_schema_version drift detected: "
                    f"expected {ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION!r}, "
                    f"got {observed_android_schema_version!r}."
                )
        else:
            issues.append("truth_acceptance_closure_contract.schema_gate must be a mapping.")

    return CrossRepoSchemaGateReport(passed=not issues, issues=issues)


def build_cross_repo_schema_gate_manifest() -> Dict[str, Any]:
    return {
        "authority": CROSS_REPO_SCHEMA_GATE_AUTHORITY,
        "gate_version": CROSS_REPO_SCHEMA_GATE_VERSION,
        "android_audited_ref": ANDROID_AUDITED_REF,
        "android_aip_models_source_sha": ANDROID_AIP_MODELS_SOURCE_SHA,
        "android_completion_closure_source_sha": ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA,
        "android_anchors": {
            "aip_models": ANDROID_AIP_MODELS_ANCHOR,
            "completion_closure_uplink_contract": ANDROID_COMPLETION_CLOSURE_ANCHOR,
        },
        "required_aip_message_types": sorted(REQUIRED_AIP_MESSAGE_TYPES),
        "required_runtime_truth_top_level_fields": sorted(REQUIRED_RUNTIME_TRUTH_TOP_LEVEL_FIELDS),
        "required_truth_acceptance_contract_fields": sorted(REQUIRED_TRUTH_ACCEPTANCE_CONTRACT_FIELDS),
        "required_acceptance_closure_fields": sorted(REQUIRED_ACCEPTANCE_CLOSURE_FIELDS),
        "projection_schema_gate_metadata": build_projection_schema_gate_metadata(),
    }
