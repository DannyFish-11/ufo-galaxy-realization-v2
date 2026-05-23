"""Cross-repo schema/contract version gate for critical V2↔Android boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional

from core.reliability_contract import (
    ANDROID_UPLINK_RECONCILIATION_DEDUP_KEY,
    ANDROID_UPLINK_REPLAY_DEDUP_KEY,
    ANDROID_UPLINK_RESULT_DEDUP_KEY,
)

CROSS_REPO_SCHEMA_GATE_AUTHORITY: str = (
    "CROSS_REPO_SCHEMA_GATE_AUTHORITY::contracts.cross_repo_schema_version_gate::"
    "minimal critical gate for AIP message types + projection/closure truth contract"
)
CROSS_REPO_SCHEMA_GATE_VERSION: str = "1.0.0"

CLOSURE_GRADE_REQUIRES_CANONICAL_SCHEMA_GATE_POLICY: str = (
    "CLOSURE_GRADE_REQUIRES_CANONICAL_SCHEMA_GATE_V1: "
    "Only Android runtime payloads whose uplink schema gate decision is action='accept' "
    "are eligible for closure-grade canonical credit.  Payloads with action='degrade' "
    "(compat/legacy path) or action='reject' MUST have closure_grade_eligible=False and "
    "MUST NOT be promoted to is_fully_closed=True in the unified result ingress.  "
    "The degrade path exists for operational compatibility only; it does not confer "
    "the same canonical truthfulness as a strict schema-validated accept."
)

ANDROID_AUDITED_REF: str = "3258b09b25d5279773122e86a7b1945586ff470b"
ANDROID_AIP_MODELS_SOURCE_SHA: str = "3404657c7eda895978ec672e1e176152161b8fe1"
ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA: str = "7838103668a19800ed74d3133f4f5e671359d65a"
ANDROID_AIP_MODELS_ANCHOR: str = "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/protocol/AipModels.kt"
ANDROID_COMPLETION_CLOSURE_ANCHOR: str = (
    "ufo-galaxy-android/app/src/main/java/com/ufo/galaxy/runtime/" "AndroidCompletionClosureUplinkContract.kt"
)
ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION: str = "1"
ANDROID_COMPLETION_CLOSURE_CONTRACT_VERSION: str = "1"
ANDROID_CANONICAL_DEDUPE_CONTRACT_VERSION: str = "1"

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

REQUIRED_ACCEPTANCE_CLOSURE_SEMANTIC_FIELDS: FrozenSet[str] = frozenset(
    {
        "acceptance_verdict",
        "closure_quality",
        "evidence_completeness",
        "evidence_provenance",
        "advisory_evidence_only",
        "canonical_confirmation_present",
        "repo_mutation_completion_truth",
        "is_fully_closed",
    }
)

REQUIRED_SHARED_EXECUTION_VISIBILITY_FIELDS: FrozenSet[str] = frozenset(
    {
        "completion_state",
        "closure_candidate_state",
        "authority_completion_truth",
        "acceptance_completion_truth",
        "advisory_evidence_only",
        "canonical_confirmation_present",
        "evidence_provenance",
        "evidence_completeness",
        "surface_execution_stage",
    }
)

REQUIRED_STARTUP_READINESS_FIELDS: FrozenSet[str] = frozenset(
    {
        "ready_to_route",
        "readiness_notes",
    }
)

REQUIRED_PARTICIPATION_TRUTH_FIELDS: FrozenSet[str] = frozenset(
    {
        "participation_tier",
        "device_lifecycle_stage",
        "all_device_participation_matrix",
        "completion_state",
    }
)

REQUIRED_DIAGNOSTICS_SNAPSHOT_FIELDS: FrozenSet[str] = frozenset(
    {
        "chain_overall_status",
        "failure_boundaries",
    }
)

REQUIRED_SCHEMA_GATE_METADATA_FIELDS: FrozenSet[str] = frozenset(
    {
        "authority",
        "gate_version",
        "android_completion_closure_uplink_schema_version",
        "android_aip_models_source_sha",
        "android_completion_closure_source_sha",
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
    original_action: str = ""
    expected_schema_version: str = ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION
    expected_contract_version: str = ANDROID_COMPLETION_CLOSURE_CONTRACT_VERSION
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def closure_grade_eligible(self) -> bool:
        """True iff this payload may be credited as closure-grade canonical.

        Only gate decisions with ``action='accept'`` are closure-grade eligible.
        Payloads that entered via the compat/degrade path (``action='degrade'``)
        or were hard-rejected (``action='reject'``) are NOT eligible for
        closure-grade canonical credit per
        ``CLOSURE_GRADE_REQUIRES_CANONICAL_SCHEMA_GATE_POLICY``.
        """
        return self.action == "accept"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "message_type": self.message_type,
            "observed_schema_version": self.observed_schema_version,
            "observed_contract_version": self.observed_contract_version,
            "expected_schema_version": self.expected_schema_version,
            "expected_contract_version": self.expected_contract_version,
            "reason": self.reason,
            "original_action": self.original_action,
            "closure_grade_eligible": self.closure_grade_eligible,
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
        "task_result",
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

_LEGACY_SAFE_RESULT_COMPAT_MESSAGE_TYPES: FrozenSet[str] = frozenset(
    {
        "goal_execution_result",
        "goal_result",
        "task_result",
    }
)

_LEGACY_SAFE_RESULT_STATUS_VALUES: FrozenSet[str] = frozenset(
    {
        # Accept both spellings because Android/runtime surfaces have emitted both
        # variants historically and this compat path is intentionally narrow.
        "cancelled",
        "canceled",
        "completed",
        "degraded",
        "error",
        "failed",
        "success",
    }
)

ANDROID_RESULT_DEDUPE_MESSAGE_TYPES: FrozenSet[str] = frozenset(
    {
        "task_result",
        "goal_result",
        "goal_execution_result",
    }
)

ANDROID_RECONCILIATION_DEDUPE_MESSAGE_TYPES: FrozenSet[str] = frozenset(
    {
        "reconciliation_signal",
        "handoff_result",
        "handoff_failure",
        "handoff_envelope_v2_result",
        "device_state_snapshot",
        "device_execution_event",
    }
)


@dataclass
class AndroidUplinkDedupeContractDecision:
    action: str
    message_type: str
    contract_class: str = ""
    reason: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    expected_contract_version: str = ANDROID_CANONICAL_DEDUPE_CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "message_type": self.message_type,
            "contract_class": self.contract_class,
            "reason": self.reason,
            "evidence": dict(self.evidence),
            "expected_contract_version": self.expected_contract_version,
            "authority": CROSS_REPO_SCHEMA_GATE_AUTHORITY,
            "gate_version": CROSS_REPO_SCHEMA_GATE_VERSION,
        }


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


def _extract_text_field(message: Mapping[str, Any], *field_names: str) -> str:
    payload = message.get("payload")
    payload_mapping = payload if isinstance(payload, Mapping) else {}
    schema_gate = payload_mapping.get("schema_gate")
    schema_gate_mapping = schema_gate if isinstance(schema_gate, Mapping) else {}
    for field_name in field_names:
        for candidate in (
            message.get(field_name),
            payload_mapping.get(field_name),
            schema_gate_mapping.get(field_name),
        ):
            if candidate is not None and str(candidate).strip():
                return str(candidate).strip()
    return ""


def _to_int_or_none(raw: str) -> Optional[int]:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _build_legacy_safe_result_identity(
    normalized_type: str,
    message: Mapping[str, Any],
) -> Dict[str, Any]:
    payload = message.get("payload")
    payload_mapping = payload if isinstance(payload, Mapping) else {}
    raw_task_id = _extract_text_field(message, "task_id", "goal_id")
    if not raw_task_id and normalized_type == "goal_execution_result":
        raw_task_id = _extract_text_field(message, "correlation_id")
    raw_status = _extract_text_field(message, "status", "result_kind")
    normalized_status = str(raw_status or "").strip().lower()
    return {
        "task_id": str(raw_task_id or "").strip(),
        "status": normalized_status,
        "device_id": _extract_text_field(message, "device_id"),
        "trace_id": _extract_text_field(message, "trace_id"),
        "payload_present": isinstance(payload_mapping, Mapping),
    }


def _can_degrade_missing_schema_for_legacy_result(
    normalized_type: str,
    message: Mapping[str, Any],
) -> bool:
    if normalized_type not in _LEGACY_SAFE_RESULT_COMPAT_MESSAGE_TYPES:
        return False
    identity = _build_legacy_safe_result_identity(normalized_type, message)
    return bool(identity["task_id"] and identity["status"] in _LEGACY_SAFE_RESULT_STATUS_VALUES)


def _build_legacy_safe_result_degrade_decision(
    *,
    normalized_type: str,
    message: Mapping[str, Any],
    observed_contract_version: str,
    evidence: Mapping[str, Any],
) -> AndroidUplinkSchemaGateDecision:
    identity = _build_legacy_safe_result_identity(normalized_type, message)
    compat_evidence = dict(evidence)
    compat_evidence.update(
        {
            "compat_degrade_path": "legacy_safe_result_missing_schema_version",
            "legacy_safe_result_envelope": True,
            "canonical_identity": identity,
        }
    )
    return AndroidUplinkSchemaGateDecision(
        action="degrade",
        original_action="reject",
        message_type=normalized_type,
        observed_schema_version="",
        observed_contract_version=observed_contract_version,
        reason=f"legacy_{normalized_type}_missing_schema_version_compat",
        evidence=compat_evidence,
    )


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
        if (
            compatibility_mode == "strict_reject"
            and _can_degrade_missing_schema_for_legacy_result(normalized_type, message)
        ):
            return _build_legacy_safe_result_degrade_decision(
                normalized_type=normalized_type,
                message=message,
                observed_contract_version=observed_contract_version,
                evidence=evidence,
            )
        action = "reject" if compatibility_mode == "strict_reject" else "degrade"
        return AndroidUplinkSchemaGateDecision(
            action=action,
            message_type=normalized_type,
            observed_schema_version="",
            observed_contract_version=observed_contract_version,
            reason="missing_schema_version_metadata",
            evidence=evidence,
        )

    if observed_schema_version != ANDROID_COMPLETION_CLOSURE_UPLINK_SCHEMA_VERSION:
        if compatibility_mode == "compat_degrade" and observed_schema_version in _LEGACY_COMPAT_SCHEMA_VERSIONS:
            return AndroidUplinkSchemaGateDecision(
                action="degrade",
                message_type=normalized_type,
                observed_schema_version=observed_schema_version,
                observed_contract_version=observed_contract_version,
                reason="legacy_schema_version_compat",
                evidence=evidence,
            )
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


def evaluate_android_uplink_dedupe_contract(
    *,
    message_type: str,
    message: Mapping[str, Any],
) -> Optional[AndroidUplinkDedupeContractDecision]:
    normalized_type = str(message_type or "").strip().lower()

    if normalized_type in ANDROID_RESULT_DEDUPE_MESSAGE_TYPES:
        task_id = _extract_text_field(message, "task_id", "goal_id")
        idempotency_key = _extract_text_field(message, "idempotency_key")
        completion_emission_id = _extract_text_field(
            message,
            "completion_emission_id",
            "emission_id",
            "completion_id",
            "result_id",
        )
        missing_fields = []
        if not task_id:
            missing_fields.append("task_id")
        if not idempotency_key:
            missing_fields.append("idempotency_key")
        if not completion_emission_id:
            missing_fields.append("completion_emission_id")
        action = "accept" if not missing_fields else "degrade"
        reason = (
            "canonical_dedupe_contract_satisfied" if not missing_fields else "missing_canonical_result_dedupe_fields"
        )
        return AndroidUplinkDedupeContractDecision(
            action=action,
            message_type=normalized_type,
            contract_class="result",
            reason=reason,
            evidence={
                "task_id_present": bool(task_id),
                "idempotency_key_present": bool(idempotency_key),
                "completion_emission_id_present": bool(completion_emission_id),
                "missing_fields": missing_fields,
                "dedup_key_contract": ANDROID_UPLINK_RESULT_DEDUP_KEY.to_dict(),
            },
        )

    if normalized_type in ANDROID_RECONCILIATION_DEDUPE_MESSAGE_TYPES:
        subject_identity = _extract_text_field(message, "contract_id", "session_id", "runtime_session_id")
        reconciliation_identity = _extract_text_field(
            message,
            "reconciliation_id",
            "signal_id",
            "handoff_id",
            "event_id",
            "result_id",
            "completion_emission_id",
        )
        missing_fields = []
        if not subject_identity:
            missing_fields.append("contract_id|session_id")
        if not reconciliation_identity:
            missing_fields.append("reconciliation_id|signal_id|handoff_id")
        action = "accept" if not missing_fields else "degrade"
        reason = (
            "canonical_dedupe_contract_satisfied"
            if not missing_fields
            else "missing_canonical_reconciliation_dedupe_fields"
        )
        return AndroidUplinkDedupeContractDecision(
            action=action,
            message_type=normalized_type,
            contract_class="reconciliation",
            reason=reason,
            evidence={
                "subject_identity_present": bool(subject_identity),
                "reconciliation_identity_present": bool(reconciliation_identity),
                "missing_fields": missing_fields,
                "dedup_key_contract": ANDROID_UPLINK_RECONCILIATION_DEDUP_KEY.to_dict(),
            },
        )

    return None


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
        issues.append(f"runtime-truth projection is missing required top-level fields: {missing_top_level}.")

    startup_readiness = payload.get("startup_readiness")
    if not isinstance(startup_readiness, Mapping):
        issues.append("startup_readiness must be a mapping.")
    else:
        missing_startup_readiness = sorted(k for k in REQUIRED_STARTUP_READINESS_FIELDS if k not in startup_readiness)
        if missing_startup_readiness:
            issues.append(f"startup_readiness is missing required fields: {missing_startup_readiness}.")

    shared_visibility = payload.get("shared_execution_visibility")
    if not isinstance(shared_visibility, Mapping):
        issues.append("shared_execution_visibility must be a mapping.")
    else:
        missing_shared_visibility_fields = sorted(
            k for k in REQUIRED_SHARED_EXECUTION_VISIBILITY_FIELDS if k not in shared_visibility
        )
        if missing_shared_visibility_fields:
            issues.append(
                f"shared_execution_visibility is missing required fields: {missing_shared_visibility_fields}."
            )

    participation_truth = payload.get("participation_truth_consumption")
    if not isinstance(participation_truth, Mapping):
        issues.append("participation_truth_consumption must be a mapping.")
    else:
        missing_participation_truth = sorted(k for k in REQUIRED_PARTICIPATION_TRUTH_FIELDS if k not in participation_truth)
        if missing_participation_truth:
            issues.append(f"participation_truth_consumption is missing required fields: {missing_participation_truth}.")

    contract = payload.get("truth_acceptance_closure_contract")
    if not isinstance(contract, Mapping):
        issues.append("truth_acceptance_closure_contract must be a mapping.")
    else:
        missing_contract = sorted(k for k in REQUIRED_TRUTH_ACCEPTANCE_CONTRACT_FIELDS if k not in contract)
        if missing_contract:
            issues.append(f"truth_acceptance_closure_contract is missing required fields: {missing_contract}.")

        acceptance = contract.get("acceptance_closure_truth")
        if isinstance(acceptance, Mapping):
            missing_acceptance = sorted(k for k in REQUIRED_ACCEPTANCE_CLOSURE_FIELDS if k not in acceptance)
            if missing_acceptance:
                issues.append(f"acceptance_closure_truth is missing required fields: {missing_acceptance}.")
            missing_acceptance_semantics = sorted(
                k for k in REQUIRED_ACCEPTANCE_CLOSURE_SEMANTIC_FIELDS if k not in acceptance
            )
            if missing_acceptance_semantics:
                issues.append(f"acceptance_closure_truth is missing required semantic fields: {missing_acceptance_semantics}.")
        else:
            issues.append("acceptance_closure_truth must be a mapping.")

        diagnostics_snapshot = contract.get("diagnostics_snapshot")
        if not isinstance(diagnostics_snapshot, Mapping):
            issues.append("truth_acceptance_closure_contract.diagnostics_snapshot must be a mapping.")
        else:
            missing_diagnostics = sorted(k for k in REQUIRED_DIAGNOSTICS_SNAPSHOT_FIELDS if k not in diagnostics_snapshot)
            if missing_diagnostics:
                issues.append(f"diagnostics_snapshot is missing required fields: {missing_diagnostics}.")

        gate_candidate = contract.get("gate_candidate")
        if not isinstance(gate_candidate, Mapping):
            issues.append("truth_acceptance_closure_contract.gate_candidate must be a mapping.")

        schema_gate = contract.get("schema_gate")
        if isinstance(schema_gate, Mapping):
            missing_schema_gate_fields = sorted(k for k in REQUIRED_SCHEMA_GATE_METADATA_FIELDS if k not in schema_gate)
            if missing_schema_gate_fields:
                issues.append(f"schema_gate is missing required metadata fields: {missing_schema_gate_fields}.")
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
            observed_aip_models_sha = str(schema_gate.get("android_aip_models_source_sha") or "")
            if observed_aip_models_sha != ANDROID_AIP_MODELS_SOURCE_SHA:
                issues.append(
                    "schema_gate.android_aip_models_source_sha drift detected: "
                    f"expected {ANDROID_AIP_MODELS_SOURCE_SHA!r}, got {observed_aip_models_sha!r}."
                )
            observed_closure_sha = str(schema_gate.get("android_completion_closure_source_sha") or "")
            if observed_closure_sha != ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA:
                issues.append(
                    "schema_gate.android_completion_closure_source_sha drift detected: "
                    f"expected {ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA!r}, got {observed_closure_sha!r}."
                )
        else:
            issues.append("truth_acceptance_closure_contract.schema_gate must be a mapping.")

    return CrossRepoSchemaGateReport(passed=not issues, issues=issues)


def build_cross_repo_schema_gate_manifest() -> Dict[str, Any]:
    return {
        "authority": CROSS_REPO_SCHEMA_GATE_AUTHORITY,
        "gate_version": CROSS_REPO_SCHEMA_GATE_VERSION,
        "android_canonical_dedupe_contract_version": ANDROID_CANONICAL_DEDUPE_CONTRACT_VERSION,
        "android_audited_ref": ANDROID_AUDITED_REF,
        "android_aip_models_source_sha": ANDROID_AIP_MODELS_SOURCE_SHA,
        "android_completion_closure_source_sha": ANDROID_COMPLETION_CLOSURE_CONTRACT_SOURCE_SHA,
        "android_anchors": {
            "aip_models": ANDROID_AIP_MODELS_ANCHOR,
            "completion_closure_uplink_contract": ANDROID_COMPLETION_CLOSURE_ANCHOR,
        },
        "android_dedupe_contracts": {
            "result": {
                "message_types": sorted(ANDROID_RESULT_DEDUPE_MESSAGE_TYPES),
                "dedup_key": ANDROID_UPLINK_RESULT_DEDUP_KEY.to_dict(),
            },
            "reconciliation": {
                "message_types": sorted(ANDROID_RECONCILIATION_DEDUPE_MESSAGE_TYPES),
                "dedup_key": ANDROID_UPLINK_RECONCILIATION_DEDUP_KEY.to_dict(),
            },
            "replay": {
                "message_types": ["offline_replay_result"],
                "dedup_key": ANDROID_UPLINK_REPLAY_DEDUP_KEY.to_dict(),
            },
        },
        "required_aip_message_types": sorted(REQUIRED_AIP_MESSAGE_TYPES),
        "required_runtime_truth_top_level_fields": sorted(REQUIRED_RUNTIME_TRUTH_TOP_LEVEL_FIELDS),
        "required_truth_acceptance_contract_fields": sorted(REQUIRED_TRUTH_ACCEPTANCE_CONTRACT_FIELDS),
        "required_acceptance_closure_fields": sorted(REQUIRED_ACCEPTANCE_CLOSURE_FIELDS),
        "required_acceptance_closure_semantic_fields": sorted(REQUIRED_ACCEPTANCE_CLOSURE_SEMANTIC_FIELDS),
        "required_shared_execution_visibility_fields": sorted(REQUIRED_SHARED_EXECUTION_VISIBILITY_FIELDS),
        "required_startup_readiness_fields": sorted(REQUIRED_STARTUP_READINESS_FIELDS),
        "required_participation_truth_fields": sorted(REQUIRED_PARTICIPATION_TRUTH_FIELDS),
        "required_diagnostics_snapshot_fields": sorted(REQUIRED_DIAGNOSTICS_SNAPSHOT_FIELDS),
        "required_schema_gate_metadata_fields": sorted(REQUIRED_SCHEMA_GATE_METADATA_FIELDS),
        "projection_schema_gate_metadata": build_projection_schema_gate_metadata(),
    }
