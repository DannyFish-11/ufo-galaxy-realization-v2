"""Cross-repo schema/contract version gate for critical V2↔Android boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional

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
ANDROID_COMPLETION_CLOSURE_CONTRACT_VERSION: str = "1"

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


@dataclass
class AndroidUplinkSchemaGateDecision:
    action: str
    message_type: str
    observed_schema_version: str = ""
    observed_contract_version: str = ""
    reason: str = ""
    expected_schema_version: str = ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION
    expected_contract_version: str = ANDROID_COMPLETION_CLOSURE_CONTRACT_VERSION
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "message_type": self.message_type,
            "observed_schema_version": self.observed_schema_version,
            "observed_contract_version": self.observed_contract_version,
            "expected_schema_version": self.expected_schema_version,
            "expected_contract_version": self.expected_contract_version,
            "reason": self.reason,
            "evidence": dict(self.evidence),
            "authority": CROSS_REPO_SCHEMA_GATE_AUTHORITY,
            "gate_version": CROSS_REPO_SCHEMA_GATE_VERSION,
        }


STRICT_ANDROID_UPLINK_SCHEMA_GATE_MESSAGE_TYPES: FrozenSet[str] = frozenset(
    {
        "handoff_result",
        "handoff_failure",
        "handoff_envelope_v2_result",
        "goal_execution_result",
        "goal_result",
    }
)

COMPAT_ANDROID_UPLINK_SCHEMA_GATE_MESSAGE_TYPES: FrozenSet[str] = frozenset(
    {
        "device_state_snapshot",
        "device_execution_event",
        "reconciliation_signal",
    }
)

COMPLETION_CONTRACT_ENFORCED_MESSAGE_TYPES: FrozenSet[str] = frozenset(
    {
        "handoff_result",
        "handoff_failure",
        "handoff_envelope_v2_result",
    }
)

_LEGACY_COMPAT_SCHEMA_VERSIONS: FrozenSet[str] = frozenset({"0"})


def _extract_uplink_schema_version(message: Mapping[str, Any]) -> str:
    payload = message.get("payload")
    payload_mapping = payload if isinstance(payload, Mapping) else {}
    schema_gate = payload_mapping.get("schema_gate")
    schema_gate_mapping = schema_gate if isinstance(schema_gate, Mapping) else {}
    lineage = payload_mapping.get("lineage")
    lineage_mapping = lineage if isinstance(lineage, Mapping) else {}
    candidates = (
        message.get("android_completion_closure_uplink_schema_version"),
        message.get("schema_version"),
        message.get("uplink_schema_version"),
        payload_mapping.get("android_completion_closure_uplink_schema_version"),
        payload_mapping.get("schema_version"),
        payload_mapping.get("uplink_schema_version"),
        schema_gate_mapping.get("android_completion_closure_uplink_schema_version"),
        schema_gate_mapping.get("schema_version"),
        lineage_mapping.get("android_completion_closure_uplink_schema_version"),
        lineage_mapping.get("schema_version"),
    )
    for candidate in candidates:
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()
    return ""


def _extract_completion_contract_version(message: Mapping[str, Any]) -> str:
    payload = message.get("payload")
    payload_mapping = payload if isinstance(payload, Mapping) else {}
    schema_gate = payload_mapping.get("schema_gate")
    schema_gate_mapping = schema_gate if isinstance(schema_gate, Mapping) else {}
    candidates = (
        message.get("completion_closure_contract_version"),
        payload_mapping.get("completion_closure_contract_version"),
        schema_gate_mapping.get("completion_closure_contract_version"),
    )
    for candidate in candidates:
        if candidate is not None and str(candidate).strip():
            return str(candidate).strip()
    return ""


def _to_int_or_none(raw: str) -> Optional[int]:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def evaluate_android_uplink_schema_gate(
    *,
    message_type: str,
    message: Mapping[str, Any],
) -> Optional[AndroidUplinkSchemaGateDecision]:
    normalized_type = str(message_type or "").strip().lower()
    if normalized_type in STRICT_ANDROID_UPLINK_SCHEMA_GATE_MESSAGE_TYPES:
        compatibility_mode = "strict_reject"
    elif normalized_type in COMPAT_ANDROID_UPLINK_SCHEMA_GATE_MESSAGE_TYPES:
        compatibility_mode = "compat_degrade"
    else:
        return None

    observed_schema_version = _extract_uplink_schema_version(message)
    observed_contract_version = _extract_completion_contract_version(message)
    evidence = {
        "compatibility_mode": compatibility_mode,
        "required_by_cross_repo_gate": True,
    }

    if not observed_schema_version:
        action = "reject" if compatibility_mode == "strict_reject" else "degrade"
        return AndroidUplinkSchemaGateDecision(
            action=action,
            message_type=normalized_type,
            observed_schema_version="",
            observed_contract_version=observed_contract_version,
            reason="missing_schema_version_metadata",
            evidence=evidence,
        )

    if observed_schema_version == ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION:
        pass
    elif (
        compatibility_mode == "compat_degrade"
        and observed_schema_version in _LEGACY_COMPAT_SCHEMA_VERSIONS
    ):
        return AndroidUplinkSchemaGateDecision(
            action="degrade",
            message_type=normalized_type,
            observed_schema_version=observed_schema_version,
            observed_contract_version=observed_contract_version,
            reason="legacy_schema_version_compat",
            evidence=evidence,
        )
    else:
        observed_num = _to_int_or_none(observed_schema_version)
        expected_num = _to_int_or_none(ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION)
        if (
            compatibility_mode == "compat_degrade"
            and observed_num is not None
            and expected_num is not None
            and observed_num < expected_num
        ):
            return AndroidUplinkSchemaGateDecision(
                action="degrade",
                message_type=normalized_type,
                observed_schema_version=observed_schema_version,
                observed_contract_version=observed_contract_version,
                reason="older_schema_version_compat",
                evidence=evidence,
            )
        return AndroidUplinkSchemaGateDecision(
            action="reject",
            message_type=normalized_type,
            observed_schema_version=observed_schema_version,
            observed_contract_version=observed_contract_version,
            reason="schema_version_mismatch",
            evidence=evidence,
        )

    if normalized_type in COMPLETION_CONTRACT_ENFORCED_MESSAGE_TYPES:
        if not observed_contract_version:
            return AndroidUplinkSchemaGateDecision(
                action="reject",
                message_type=normalized_type,
                observed_schema_version=observed_schema_version,
                observed_contract_version="",
                reason="missing_completion_closure_contract_version",
                evidence=evidence,
            )
        if observed_contract_version != ANDROID_COMPLETION_CLOSURE_CONTRACT_VERSION:
            return AndroidUplinkSchemaGateDecision(
                action="reject",
                message_type=normalized_type,
                observed_schema_version=observed_schema_version,
                observed_contract_version=observed_contract_version,
                reason="completion_closure_contract_mismatch",
                evidence=evidence,
            )

    return AndroidUplinkSchemaGateDecision(
        action="accept",
        message_type=normalized_type,
        observed_schema_version=observed_schema_version,
        observed_contract_version=observed_contract_version,
        reason="schema_version_gate_matched",
        evidence=evidence,
    )


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
