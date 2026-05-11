"""core/unified_governance_semantics.py
========================================
Unified governance semantics between V2 authority and Android autonomy.

This module defines one stable contract that expresses:

1. Android autonomy scope differences between local vs cross-device mode.
2. Unified authority precedence across local planning, local grounding,
   local execution, delegated execution, takeover, and multimodal participation.
3. A panel/operator-consumable governance state snapshot.

Android truth hardening series
-------------------------------
This module has been progressively hardened across the Android-truth PR series:

- PR-5  / ``core.unified_execution_governance`` — Execution lifecycle truth
         quality (``android_remote_confirmed``, ``missing_remote``, etc.) is
         now embedded in ``decision_causality`` via
         ``get_execution_lifecycle_truth_binding()``.
- PR-7A / ``core.android_mode_gate_policy`` — Absent, stale, conflicting, or
         downgraded Android capability truth now degrades the canonical gate
         decision to ``deny`` via
         ``ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY``.
         ``proof_input_diagnosis`` is computed *before* the gate call so that
         truth quality drives the decision rather than only observability.
- PR-8  / ``core.android_evidence_integration_pipeline`` — A single end-to-end
         integration verdict (capability truth + lifecycle truth + audit
         authority + closed-loop invariants) is now threaded into every device
         entry in the governance state under ``android_evidence_integration``
         and mirrored in ``decision_causality`` as
         ``android_evidence_integration_*`` fields.
- PR-9  / ``core.unified_execution_governance`` — Canonical
         ``classify_canonical_proof_input_diagnosis()`` distinguishes all eight
         proof-input classes (``complete``, ``stale``, ``conflicting``,
         ``malformed``, ``unknown``, ``downgraded``, ``partial``, ``missing``).
         Only ``complete`` is a passing classification.
- PR-16 / ``core.ownership_transfer_proof_quality`` — Proof-quality-aware
         ownership-transfer semantics.  Resumed ownership transfer is not
         treated as complete unless supported by sufficient evidence.  Explicit
         ``degraded_stale_evidence``, ``degraded_partial``,
         ``degraded_conflicting``, ``degraded_unresolved``, and ``incomplete``
         classes surface via ``decision_causality`` fields
         ``ownership_transfer_proof_class``,
         ``ownership_transfer_is_sufficient_for_closure``, and
         ``ownership_transfer_proof_degraded``.

Primary regression suites covering this module
-----------------------------------------------
- ``tests/test_pr5_execution_runtime_truth_binding.py``
- ``tests/test_pr7a_android_governance_truth_hardening.py``
- ``tests/test_pr8_android_evidence_integration_e2e.py``
- ``tests/test_pr9_canonical_proof_input_diagnosis.py``
- ``tests/test_pr11a_android_truth_followup_verification.py``
- ``tests/test_pr12_android_truth_final_audit.py``
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import importlib
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Re-export so consumers can import from this module without knowing the
# internal source module.
try:
    from core.unified_execution_governance import (  # noqa: F401
        CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY,
        EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL,
        EXECUTION_LIFECYCLE_TRUTH_BINDING_CONTRACT_VERSION,
        ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS,
        AndroidExecutionLifecycleTruthQuality,
        ExecutionLifecycleTruthBinding,
        classify_canonical_proof_input_diagnosis,
        get_execution_lifecycle_truth_binding,
    )
except ImportError:  # pragma: no cover
    # Graceful degradation when unified_execution_governance is unavailable.
    CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY = (  # type: ignore[assignment]
        "CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY::unavailable"
    )
    ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY = (  # type: ignore[assignment]
        "ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY::unavailable"
    )
    EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL = (  # type: ignore[assignment]
        "EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL::unavailable"
    )
    EXECUTION_LIFECYCLE_TRUTH_BINDING_CONTRACT_VERSION = "unavailable"  # type: ignore[assignment]
    ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS = 60.0  # type: ignore[assignment]

    def classify_canonical_proof_input_diagnosis(  # type: ignore[misc]
        snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "proof_input_class": "missing",
            "proof_input_detail": "classify_canonical_proof_input_diagnosis unavailable",
            "proof_input_conflicts": [],
            "proof_input_degradation_causes": ["diagnosis_module_unavailable"],
            "_policy": CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        }

    def get_execution_lifecycle_truth_binding(  # type: ignore[misc]
        device_id: str,
    ) -> Any:
        return None

# PR-16: Re-export ownership-transfer proof quality so consumers only need
# one import target.
try:
    from core.ownership_transfer_proof_quality import (  # noqa: F401
        OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL,
        OWNERSHIP_TRANSFER_PROOF_QUALITY_CONTRACT_VERSION,
        RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF_POLICY,
        OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY,
        STALE_OWNERSHIP_EVIDENCE_THRESHOLD_SECONDS,
        OwnershipTransferProofClass,
        OwnershipTransferProofQualityResult,
        classify_ownership_transfer_proof_quality,
        get_latest_ownership_transfer_proof_quality_for_device,
    )
    _OWNERSHIP_TRANSFER_PROOF_QUALITY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _OWNERSHIP_TRANSFER_PROOF_QUALITY_AVAILABLE = False
    OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL = (  # type: ignore[assignment]
        "OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL::unavailable"
    )
    OWNERSHIP_TRANSFER_PROOF_QUALITY_CONTRACT_VERSION = "unavailable"  # type: ignore[assignment]
    RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF_POLICY = (  # type: ignore[assignment]
        "POLICY::RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF::unavailable"
    )
    OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY = (  # type: ignore[assignment]
        "POLICY::OWNERSHIP_TRANSFER_PROOF_QUALITY::unavailable"
    )
    STALE_OWNERSHIP_EVIDENCE_THRESHOLD_SECONDS = 300.0  # type: ignore[assignment]

    def classify_ownership_transfer_proof_quality(  # type: ignore[misc]
        verdict: Any,
        *,
        now: Optional[float] = None,
        stale_threshold_seconds: float = 300.0,
    ) -> Any:
        return None

    def get_latest_ownership_transfer_proof_quality_for_device(  # type: ignore[misc]
        device_id: str,
        *,
        session_id: str = "",
        now: Optional[float] = None,
        stale_threshold_seconds: float = 300.0,
    ) -> Any:
        return None

UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY: str = (
    "UNIFIED_GOVERNANCE_SEMANTICS_V1: "
    "core.unified_governance_semantics is the canonical governance contract for "
    "V2 authority vs Android autonomy across local/cross-device mode and "
    "execution participation precedence."
)

UNIFIED_GOVERNANCE_SEMANTICS_CONTRACT_VERSION: str = "1.0.0"
ANDROID_ORIGINATED_CANONICAL_DIAGNOSIS_CONTRACT_VERSION: str = "17.0.0"
ANDROID_ORIGINATED_CANONICAL_DIAGNOSIS_POLICY: str = (
    "POLICY::ANDROID_ORIGINATED_CANONICAL_DIAGNOSIS_V1: "
    "V2 canonical diagnosis surfaces MUST reconcile Android-originated runtime, "
    "capability, recovery, takeover, and mesh diagnostics into stable per-domain "
    "canonical diagnosis classes with preserved Android-local reason tokens. "
    "Panel/operator/audit paths MUST expose these canonicalized diagnostics via "
    "decision_causality so Android-local causes remain visible rather than only "
    "center-inferred summaries."
)
MESH_RUNTIME_STATUS_POLICY: str = (
    "MESH_RUNTIME_STATUS_POLICY_V1: "
    "multi-device mesh runtime status must be surfaced as explicit "
    "partial/runtime/deferred facts instead of implicit structural claims."
)
MESH_RUNTIME_STATUS_RUNTIME_PROVEN: str = "runtime_proven"
MESH_RUNTIME_STATUS_PARTIAL: str = "partial"
MESH_RUNTIME_STATUS_CONTRACT_ONLY: str = "contract_only"
MESH_RUNTIME_STATUS_UNAVAILABLE: str = "unavailable"

# ---------------------------------------------------------------------------
# Mesh runtime proof quality levels
# ---------------------------------------------------------------------------
# These distinguish the *quality* of existing runtime proof from the coarser
# status field so governance can degrade decisions proportionally.

MESH_RUNTIME_PROOF_QUALITY_LIVE: str = "live"
# runtime_proven and fresh: live execution ran recently enough to be trusted.

MESH_RUNTIME_PROOF_QUALITY_STALE: str = "stale"
# runtime_proven in a prior session but last_live_run_at exceeds the staleness
# threshold; proof exists but may not reflect current runtime conditions.

MESH_RUNTIME_PROOF_QUALITY_PARTIAL: str = "partial"
# Some execution-level proof exists (e.g. dispatch attempted) but a full
# live mesh run has never been recorded.

MESH_RUNTIME_PROOF_QUALITY_STRUCTURALLY_INFERRED: str = "structurally_inferred"
# Only sentinel/module-presence proofs are available.  No execution-path
# evidence at all — purely structural inference from code presence.

MESH_RUNTIME_PROOF_QUALITY_MISSING: str = "missing"
# No proofs of any kind are present.

MESH_RUNTIME_PROOF_STALE_AFTER_SECONDS: float = 300.0
# Live mesh execution evidence is considered stale after this many seconds.

MESH_RUNTIME_PROOF_QUALITY_POLICY: str = (
    "MESH_RUNTIME_PROOF_QUALITY_POLICY_V1: "
    "governance must not treat partial, stale, missing, or structurally-inferred "
    "mesh runtime proof as equivalent to live runtime-proven readiness. "
    "The proof_quality field is authoritative; governance_readiness_impact surfaces "
    "the downstream effect on canonical decisions."
)

UNIFIED_GOVERNANCE_POLICY_LAYER_POLICY: str = (
    "UNIFIED_GOVERNANCE_POLICY_LAYER_POLICY_V1: "
    "policy-layer outcomes are derived from unified governance precedence and "
    "decision causality, and are authoritative for hard-block vs degraded "
    "operation, minimum viable access, retry/resume/recovery eligibility, "
    "closure acceptability thresholds, and automatic/manual action routing."
)
UNIFIED_GOVERNANCE_POLICY_LAYER_CONTRACT_VERSION: str = "1.0.0"
_POLICY_HARD_BLOCK_REASONS: frozenset[str] = frozenset(
    {
        "canonical_execution_gate:deny",
        "dispatch_gate",
        "takeover_gate",
        "unknown_mode",
        "execution_runtime_blocked:goal_execution",
    }
)
_POLICY_RESUMABLE_PHASES: frozenset[str] = frozenset({"planning", "manifest", "execution"})
_POLICY_INVALID_RECOVERY_QUALITIES: frozenset[str] = frozenset({"", "none", "missing", "not_provided"})
_POLICY_ESCALATION_SEVERITIES: frozenset[str] = frozenset({"critical", "high"})
_POLICY_ESCALATION_MANUAL_DECISIONS: frozenset[str] = frozenset({"manual_review", "suspend"})


def _is_hard_block_reason(blocked_by: str) -> bool:
    normalized = str(blocked_by or "").strip()
    return normalized in _POLICY_HARD_BLOCK_REASONS or normalized.startswith("mesh_proof_quality:")


class GovernancePath(str, Enum):
    local_planning = "local_planning"
    local_grounding = "local_grounding"
    local_execution = "local_execution"
    delegated_execution = "delegated_execution"
    takeover = "takeover"
    multimodal_participation = "multimodal_participation"


@dataclass
class GovernancePathDecision:
    path: GovernancePath
    precedence_rank: int
    authority_owner: str
    android_scope: str
    eligible: bool
    blocked_by: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path.value,
            "precedence_rank": self.precedence_rank,
            "authority_owner": self.authority_owner,
            "android_scope": self.android_scope,
            "eligible": self.eligible,
            "blocked_by": self.blocked_by,
        }


def _autonomy_scope_for_mode(mode: str) -> str:
    if mode == "local":
        return "local_autonomy"
    if mode == "cross_device":
        return "subordinate_participation"
    if mode == "transitioning":
        return "transition_limited"
    return "unknown"


def _rank_for_path(path: GovernancePath) -> int:
    rank_map = {
        GovernancePath.takeover: 1,
        GovernancePath.delegated_execution: 2,
        GovernancePath.local_execution: 3,
        GovernancePath.local_grounding: 4,
        GovernancePath.local_planning: 5,
        GovernancePath.multimodal_participation: 6,
    }
    return rank_map[path]


def _snapshot_continuity_state(
    *,
    status: Optional[str],
    conflict: bool,
) -> str:
    """Classify reconciliation facts into a stable continuity state bucket."""
    normalized_status = str(status or "").strip().lower()
    if conflict or normalized_status == "conflict_center_truth_retained":
        return "conflict_retained"
    if normalized_status in {
        "stale_rejected",
        "out_of_order_rejected",
        "reconnect_delayed_rejected",
        "duplicate_ignored",
    }:
        return "rejected"
    if normalized_status == "accepted":
        return "accepted"
    return "unavailable"


def _extract_primary_execution_id(runtime_state: Dict[str, Any]) -> str:
    """Extract the first usable execution_id from runtime state."""
    for item in runtime_state.get("active_executions", []) or []:
        if not isinstance(item, dict):
            continue
        execution_id = item.get("execution_id")
        if isinstance(execution_id, str) and execution_id.strip():
            return execution_id.strip()
    return ""


def _normalize_cross_repo_truth_report(raw_report: Any) -> Dict[str, Any]:
    """Normalize cross-repo evidence report object/dict to a stable shape."""
    report_dict: Dict[str, Any] = {}
    if isinstance(raw_report, dict):
        report_dict = dict(raw_report)
    elif hasattr(raw_report, "to_dict"):
        try:
            report_dict = dict(raw_report.to_dict())  # type: ignore[union-attr]
        except Exception:
            report_dict = {}

    normalized_sources: List[Dict[str, Any]] = []
    for source in report_dict.get("sources") or []:
        if not isinstance(source, dict):
            continue
        normalized_sources.append(
            {
                "source_id": str(source.get("source_id") or ""),
                # Canonical trust level is the source authority class from PR-05
                # (primary/secondary/advisory) plus concrete ingestion status.
                "source_trust_level": str(source.get("authority") or "unknown"),
                "status": str(source.get("status") or "unknown"),
                "freshness_secs": source.get("freshness_secs"),
                "is_stale": bool(source.get("is_stale", False)),
            }
        )

    return {
        "pipeline_verdict": str(report_dict.get("pipeline_verdict") or "insufficient"),
        "is_complete": bool(report_dict.get("is_complete", False)),
        "primary_sources_complete": bool(
            report_dict.get("primary_sources_complete", False)
        ),
        "primary_sources_fresh": bool(report_dict.get("primary_sources_fresh", False)),
        "downgrade_reasons": list(report_dict.get("downgrade_reasons") or []),
        "source_provenance": normalized_sources,
    }


def _derive_canonical_truth_basis(
    *,
    runtime_state_for_device: Dict[str, Any],
    proof_input_diagnosis: Dict[str, Any],
    cross_repo_truth_report: Dict[str, Any],
) -> Dict[str, Any]:
    """Classify canonical decision truth basis for audit/provenance surfaces.

    Parameters
    ----------
    runtime_state_for_device:
        Device-level runtime truth snapshot used by canonical decisions.
    proof_input_diagnosis:
        Canonical proof-input diagnosis result (includes proof_input_class).
    cross_repo_truth_report:
        Normalized PR-05 cross-repo evidence report summary.

    Returns
    -------
    dict
        Stable audit-facing fields:
        ``canonical_truth_provenance``,
        ``canonical_truth_source_trust_level``,
        ``canonical_truth_freshness_state``,
        ``canonical_truth_freshness_reason``,
        ``canonical_truth_confirmed``, and
        ``canonical_truth_inferred``.
    """
    lifecycle_truth_quality = str(
        runtime_state_for_device.get("android_lifecycle_truth_quality") or "v2_local_only"
    ).strip().lower() or "v2_local_only"
    freshness_state = str(
        runtime_state_for_device.get("android_semantics_freshness_state") or ""
    ).strip().lower()
    proof_input_class = str(
        proof_input_diagnosis.get("proof_input_class") or "missing"
    ).strip().lower() or "missing"
    snapshot_reconciliation_status = str(
        runtime_state_for_device.get("snapshot_reconciliation_status") or ""
    ).strip().lower()
    cross_repo_verdict = str(
        cross_repo_truth_report.get("pipeline_verdict") or "insufficient"
    ).strip().lower() or "insufficient"
    cross_repo_primary_fresh = bool(
        cross_repo_truth_report.get("primary_sources_fresh", False)
    )

    stale_remote = (
        freshness_state == "stale"
        or lifecycle_truth_quality == "stale_remote"
        or proof_input_class == "stale"
        or cross_repo_verdict == "stale"
    )
    if stale_remote:
        provenance = "stale_remote_evidence"
    elif lifecycle_truth_quality == "android_remote_confirmed":
        provenance = "android_confirmed_truth"
    elif snapshot_reconciliation_status not in {"", "missing", "unavailable"}:
        provenance = "inferred_reconciliation"
    else:
        provenance = "v2_local_state"

    freshness_reason = runtime_state_for_device.get("android_semantics_freshness_reason")
    if not freshness_reason:
        freshness_reason = (
            f"cross_repo_pipeline_verdict:{cross_repo_verdict};"
            f"runtime_freshness_state:{freshness_state or 'unknown'};"
            f"lifecycle_truth_quality:{lifecycle_truth_quality}"
        )

    if provenance == "android_confirmed_truth":
        trust_level = "high" if cross_repo_primary_fresh else "medium"
    elif provenance == "v2_local_state":
        trust_level = "medium"
    else:
        trust_level = "low"

    if freshness_state:
        canonical_freshness = freshness_state
    elif cross_repo_primary_fresh:
        canonical_freshness = "fresh"
    elif cross_repo_verdict == "stale":
        canonical_freshness = "stale"
    else:
        canonical_freshness = "unknown"

    return {
        "canonical_truth_provenance": provenance,
        "canonical_truth_source_trust_level": trust_level,
        "canonical_truth_freshness_state": canonical_freshness,
        "canonical_truth_freshness_reason": freshness_reason,
        "canonical_truth_confirmed": provenance == "android_confirmed_truth",
        "canonical_truth_inferred": provenance == "inferred_reconciliation",
    }


def _normalize_reason_tokens(raw_value: Any) -> List[str]:
    """Normalize arbitrary reason payloads into a stable token list."""
    if raw_value is None:
        return []
    if isinstance(raw_value, str):
        token = raw_value.strip()
        return [token] if token else []
    if isinstance(raw_value, (list, tuple, set)):
        normalized: List[str] = []
        for item in raw_value:
            token = str(item).strip()
            if token and token not in normalized:
                normalized.append(token)
        return normalized
    token = str(raw_value).strip()
    return [token] if token else []


def _build_android_originated_canonical_diagnosis(
    *,
    runtime_state_for_device: Dict[str, Any],
    proof_input_diagnosis: Dict[str, Any],
    android_evidence_integration: Dict[str, Any],
    ownership_transfer_proof_class: Optional[str],
    ownership_transfer_proof_diagnosis: List[str],
    mesh_runtime_state: Dict[str, Any],
    mesh_proof_quality: Optional[str],
) -> Dict[str, Any]:
    """Reconcile Android-originated diagnostics into stable canonical domains."""
    runtime_class = str(
        runtime_state_for_device.get("android_lifecycle_truth_quality") or "missing_remote"
    ).strip().lower() or "missing_remote"
    runtime_reasons = _normalize_reason_tokens(
        runtime_state_for_device.get("android_lifecycle_truth_reason")
    )
    runtime_reasons.extend(
        _normalize_reason_tokens(runtime_state_for_device.get("snapshot_reconciliation_reason"))
    )
    runtime_reasons = list(dict.fromkeys(runtime_reasons))

    capability_class = str(
        proof_input_diagnosis.get("proof_input_class") or "missing"
    ).strip().lower() or "missing"
    capability_reasons = _normalize_reason_tokens(
        proof_input_diagnosis.get("proof_input_degradation_causes")
    )
    capability_reasons.extend(
        _normalize_reason_tokens(proof_input_diagnosis.get("proof_input_conflicts"))
    )
    capability_reasons.extend(
        _normalize_reason_tokens(runtime_state_for_device.get("android_semantics_contract_diagnosis"))
    )
    capability_reasons.extend(
        _normalize_reason_tokens(runtime_state_for_device.get("android_semantics_downgraded_reasons"))
    )
    capability_reasons = list(dict.fromkeys(capability_reasons))

    recovery_class = str(
        android_evidence_integration.get("recovery_truth_quality") or "not_provided"
    ).strip().lower() or "not_provided"
    recovery_reasons = _normalize_reason_tokens(
        android_evidence_integration.get("recovery_truth_gap_types")
    )
    recovery_reasons.extend(
        _normalize_reason_tokens(android_evidence_integration.get("recovery_truth_diagnosis"))
    )
    recovery_reasons = list(dict.fromkeys(recovery_reasons))

    takeover_class = str(ownership_transfer_proof_class or "incomplete").strip().lower() or "incomplete"
    takeover_reasons = _normalize_reason_tokens(ownership_transfer_proof_diagnosis)

    mesh_class = str(
        mesh_runtime_state.get("proof_quality") or mesh_proof_quality or "missing"
    ).strip().lower() or "missing"
    mesh_reasons = _normalize_reason_tokens(mesh_runtime_state.get("proof_quality_reason"))
    mesh_reasons.extend(
        _normalize_reason_tokens(mesh_runtime_state.get("governance_readiness_impact"))
    )
    mesh_reasons = list(dict.fromkeys(mesh_reasons))

    return {
        "runtime": {
            "canonical_class": runtime_class,
            "android_local_reasons": runtime_reasons,
        },
        "capability": {
            "canonical_class": capability_class,
            "android_local_reasons": capability_reasons,
        },
        "recovery": {
            "canonical_class": recovery_class,
            "android_local_reasons": recovery_reasons,
        },
        "takeover": {
            "canonical_class": takeover_class,
            "android_local_reasons": takeover_reasons,
        },
        "mesh": {
            "canonical_class": mesh_class,
            "android_local_reasons": mesh_reasons,
        },
        "_policy": ANDROID_ORIGINATED_CANONICAL_DIAGNOSIS_POLICY,
        "_contract_version": ANDROID_ORIGINATED_CANONICAL_DIAGNOSIS_CONTRACT_VERSION,
    }


def _has_sentinel(module_path: str, sentinel_name: str) -> bool:
    """Return True when a sentinel constant can be imported and is truthy."""
    try:
        module = importlib.import_module(module_path)
        return bool(getattr(module, sentinel_name, None))
    except (ImportError, AttributeError) as exc:
        logger.debug("_has_sentinel: unavailable %s.%s: %s", module_path, sentinel_name, exc)
        return False


def _compute_mesh_proof_quality(
    *,
    has_live_runtime_path_execution: bool,
    last_live_run_at: Optional[float],
    runtime_proof_count: int,
    live_mesh_run_count: int,
    stale_after_seconds: float = MESH_RUNTIME_PROOF_STALE_AFTER_SECONDS,
) -> tuple[str, str]:
    """Compute mesh runtime proof quality and its governance-readable reason.

    Returns
    -------
    tuple[str, str]
        ``(proof_quality, proof_quality_reason)`` where *proof_quality* is one
        of the ``MESH_RUNTIME_PROOF_QUALITY_*`` constants and *proof_quality_reason*
        is a human-readable diagnostic token.
    """
    if not has_live_runtime_path_execution:
        if live_mesh_run_count > 0:
            # Counters indicate past runs but this session reset them; treat as
            # structurally inferred since no live path execution this session.
            pass
        if runtime_proof_count > 0:
            return (
                MESH_RUNTIME_PROOF_QUALITY_STRUCTURALLY_INFERRED,
                "no_live_execution_only_sentinel_presence",
            )
        return (
            MESH_RUNTIME_PROOF_QUALITY_MISSING,
            "no_proof_of_any_kind",
        )

    # has_live_runtime_path_execution is True — check staleness
    if last_live_run_at is None:
        # Live run happened but no timestamp available; cannot verify freshness
        return (
            MESH_RUNTIME_PROOF_QUALITY_STALE,
            "live_run_recorded_but_timestamp_unavailable",
        )

    age_s = max(0.0, time.time() - last_live_run_at)
    if age_s > stale_after_seconds:
        return (
            MESH_RUNTIME_PROOF_QUALITY_STALE,
            f"live_proof_age_{age_s:.0f}s_exceeds_threshold_{stale_after_seconds:.0f}s",
        )

    return (
        MESH_RUNTIME_PROOF_QUALITY_LIVE,
        "live_execution_within_freshness_window",
    )


def _mesh_proof_quality_to_governance_readiness_impact(proof_quality: str) -> str:
    """Map proof quality to its canonical governance readiness impact token.

    Returns
    -------
    str
        A stable token describing how the proof quality degrades canonical
        governance readiness.  Consumers MUST NOT treat any value other than
        ``"none"`` as equivalent to live runtime-proven readiness.
    """
    if proof_quality == MESH_RUNTIME_PROOF_QUALITY_LIVE:
        return "none"
    if proof_quality == MESH_RUNTIME_PROOF_QUALITY_STALE:
        return "degraded_stale_proof"
    if proof_quality == MESH_RUNTIME_PROOF_QUALITY_PARTIAL:
        return "degraded_partial_proof"
    if proof_quality == MESH_RUNTIME_PROOF_QUALITY_STRUCTURALLY_INFERRED:
        return "degraded_structurally_inferred"
    # MISSING or unknown
    return "blocked_no_proof"


def build_mesh_runtime_state(
    coordinator_state: Any = None,
) -> Dict[str, Any]:
    """Build a compact operator/panel-safe mesh runtime status snapshot.

    This snapshot distinguishes what is runtime-proven in the V2 codebase from
    what still depends on Android-side authority/runtime closure.

    As of PR-03, this function also integrates the center-side mesh runtime
    state machine (via :mod:`core.mesh.mesh_runtime_center_state`) so that the
    snapshot expresses a real center-side runtime contract rather than only a
    sentinel-presence projection.

    Parameters
    ----------
    coordinator_state:
        Optional coordinator state to pass to the center state machine for
        real state derivation.  If ``None``, falls back to sentinel-based
        presence checks.
    """
    has_staged_mesh_dispatch = _has_sentinel(
        "core.runtime.source_dispatch_orchestrator",
        "LIVE_MESH_RUNTIME_ENGINE_ORCHESTRATOR_PR_J_SENTINEL",
    )
    has_live_mesh_engine = _has_sentinel(
        "core.mesh.live_mesh_runtime_engine",
        "LIVE_MESH_RUNTIME_ENGINE_PR_J_SENTINEL",
    )
    has_live_mesh_coordinator = _has_sentinel(
        "core.mesh.live_mesh_session_coordinator",
        "LIVE_MESH_SESSION_COORDINATOR_PR_J_SENTINEL",
    )
    has_center_state_machine = _has_sentinel(
        "core.mesh.mesh_runtime_center_state",
        "MESH_RUNTIME_CENTER_STATE_PR03_SENTINEL",
    )

    def _safe_counter_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    recoverable_mesh_sessions = 0
    live_runtime_proof_snapshot: Dict[str, Any] = {}
    live_runtime_dispatch_count = 0
    live_runtime_run_count = 0

    try:
        from core.mesh.mesh_session_persistence import recover_mesh_sessions

        recoverable_mesh_sessions = len(recover_mesh_sessions())
    except Exception as exc:
        logger.debug("build_mesh_runtime_state: recoverable mesh sessions unavailable: %s", exc)
        recoverable_mesh_sessions = 0

    try:
        from core.runtime.source_dispatch_orchestrator import (
            get_live_mesh_runtime_proof_snapshot,
        )

        live_runtime_proof_snapshot = get_live_mesh_runtime_proof_snapshot()
    except Exception as exc:
        logger.debug("build_mesh_runtime_state: live runtime proof snapshot unavailable: %s", exc)
        live_runtime_proof_snapshot = {}

    # None-safe coercion protects against unexpected/legacy snapshot values.
    live_runtime_dispatch_count = _safe_counter_int(
        live_runtime_proof_snapshot.get("staged_mesh_dispatch_count", 0)
    )
    live_runtime_run_count = _safe_counter_int(
        live_runtime_proof_snapshot.get("live_mesh_run_count", 0)
    )
    has_live_runtime_path_execution = live_runtime_run_count > 0

    # Extract last_live_run_at for staleness detection (added by PR-08v2).
    _raw_last_live_run_at = live_runtime_proof_snapshot.get("last_live_run_at")
    last_live_run_at: Optional[float]
    try:
        last_live_run_at = float(_raw_last_live_run_at) if _raw_last_live_run_at is not None else None
    except (TypeError, ValueError):
        logger.debug(
            "build_mesh_runtime_state: malformed last_live_run_at value=%r — treating as None",
            _raw_last_live_run_at,
        )
        last_live_run_at = None

    runtime_proof_count = sum(
        (
            int(has_staged_mesh_dispatch),
            int(has_live_mesh_engine),
            int(has_live_mesh_coordinator),
            int(has_center_state_machine),
            int(has_live_runtime_path_execution),
        )
    )
    if has_live_runtime_path_execution:
        status = MESH_RUNTIME_STATUS_RUNTIME_PROVEN
    elif runtime_proof_count > 0:
        status = MESH_RUNTIME_STATUS_PARTIAL
    else:
        status = MESH_RUNTIME_STATUS_CONTRACT_ONLY

    # Compute explicit proof quality — finer-grained than status so that
    # governance can degrade decisions proportionally (PR-08v2 requirement).
    proof_quality, proof_quality_reason = _compute_mesh_proof_quality(
        has_live_runtime_path_execution=has_live_runtime_path_execution,
        last_live_run_at=last_live_run_at,
        runtime_proof_count=runtime_proof_count,
        live_mesh_run_count=live_runtime_run_count,
    )
    governance_readiness_impact = _mesh_proof_quality_to_governance_readiness_impact(
        proof_quality
    )

    # Build center-side state machine snapshot (PR-03)
    center_state_snapshot: Dict[str, Any] = {}
    try:
        from core.mesh.mesh_runtime_center_state import build_mesh_runtime_center_state

        center_state_snapshot = build_mesh_runtime_center_state(coordinator_state)
    except Exception as exc:
        logger.debug("build_mesh_runtime_state: center state machine unavailable: %s", exc)
        center_state_snapshot = {
            "status": MESH_RUNTIME_STATUS_UNAVAILABLE,
            "errors": [f"center_state_machine_unavailable:{exc}"],
        }

    return {
        "status": status,
        "proof_quality": proof_quality,
        "proof_quality_reason": proof_quality_reason,
        "governance_readiness_impact": governance_readiness_impact,
        "runtime_proof_count": runtime_proof_count,
        "runtime_proofs": {
            "staged_mesh_dispatch_orchestration": has_staged_mesh_dispatch,
            "live_mesh_runtime_engine": has_live_mesh_engine,
            "live_mesh_session_coordinator": has_live_mesh_coordinator,
            "mesh_runtime_center_state_machine": has_center_state_machine,
            "live_mesh_runtime_path_execution": has_live_runtime_path_execution,
        },
        "runtime_observability": {
            "recoverable_mesh_session_count": recoverable_mesh_sessions,
            "live_mesh_runtime_proof": {
                "staged_mesh_dispatch_count": live_runtime_dispatch_count,
                "live_mesh_run_count": live_runtime_run_count,
                "live_mesh_completed_count": _safe_counter_int(
                    live_runtime_proof_snapshot.get("live_mesh_completed_count", 0)
                ),
                "live_mesh_partial_count": _safe_counter_int(
                    live_runtime_proof_snapshot.get("live_mesh_partial_count", 0)
                ),
                "live_mesh_failed_count": _safe_counter_int(
                    live_runtime_proof_snapshot.get("live_mesh_failed_count", 0)
                ),
                "last_live_outcome": live_runtime_proof_snapshot.get("last_live_outcome"),
                "last_mesh_session_id": live_runtime_proof_snapshot.get("last_mesh_session_id"),
                "last_live_run_at": last_live_run_at,
                "proof_stale_after_seconds": MESH_RUNTIME_PROOF_STALE_AFTER_SECONDS,
            },
        },
        "center_runtime_state": center_state_snapshot,
        "runtime_relationships": [
            {
                "link": "dispatch_to_delegation",
                "source": "SourceDispatchOrchestrator(staged_mesh)",
                "target": "Android delegated execution(goal_execution/parallel_subtask)",
                "status": "v2_dispatch_proven_android_execution_external",
            },
            {
                "link": "delegation_to_parallel_subtask",
                "source": "delegated execution envelope",
                "target": "parallel_subtask handling path",
                "status": "message_path_proven",
            },
            {
                "link": "parallel_subtask_to_local_collaboration_agent",
                "source": "parallel_subtask",
                "target": "Android LocalCollaborationAgent",
                "status": "android_repo_authority_external_to_v2_runtime",
            },
        ],
        "deferred_or_constrained": [
            "cross-repo authority contract closure (V2<->Android) remains required",
            "multi-Android-device live mesh closure remains constrained without Android-side runtime proof",
        ],
        "_policy": MESH_RUNTIME_STATUS_POLICY,
        "_proof_quality_policy": MESH_RUNTIME_PROOF_QUALITY_POLICY,
        "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
    }


def resolve_governance_path_decision(
    *,
    mode: str,
    path: GovernancePath,
    dispatch_eligible: bool,
    takeover_eligible: bool,
    takeover_active: bool,
    highest_priority_execution_type: Optional[str] = None,
    blocked_execution_types: Optional[List[str]] = None,
    canonical_execution_gate_decision: str = "allow",
    mesh_proof_quality: Optional[str] = None,
) -> GovernancePathDecision:
    _blocked_execution_types: List[str] = []
    for value in blocked_execution_types or []:
        normalized_value = str(value).strip()
        if normalized_value:
            _blocked_execution_types.append(normalized_value)
    blocked_execution_types = _blocked_execution_types
    highest_priority_execution_type = str(highest_priority_execution_type or "").strip()
    canonical_execution_gate_decision = str(canonical_execution_gate_decision or "allow").strip().lower()
    if takeover_active and path != GovernancePath.takeover:
        return GovernancePathDecision(
            path=path,
            precedence_rank=_rank_for_path(path),
            authority_owner="v2_authority",
            android_scope="blocked_by_takeover",
            eligible=False,
            blocked_by="takeover",
        )

    if mode == "local":
        if path in (
            GovernancePath.local_planning,
            GovernancePath.local_grounding,
            GovernancePath.local_execution,
        ):
            return GovernancePathDecision(
                path=path,
                precedence_rank=_rank_for_path(path),
                authority_owner="android_local_autonomy",
                android_scope="autonomous",
                eligible=True,
            )
        if path == GovernancePath.multimodal_participation:
            return GovernancePathDecision(
                path=path,
                precedence_rank=_rank_for_path(path),
                authority_owner="v2_authority",
                android_scope="participatory_signal",
                eligible=True,
            )
        return GovernancePathDecision(
            path=path,
            precedence_rank=_rank_for_path(path),
            authority_owner="v2_authority",
            android_scope="not_allowed_in_local_mode",
            eligible=False,
            blocked_by="local_mode_boundary",
        )

    if mode == "cross_device":
        if path == GovernancePath.takeover:
            return GovernancePathDecision(
                path=path,
                precedence_rank=_rank_for_path(path),
                authority_owner="v2_authority",
                android_scope="subordinate_target",
                eligible=bool(takeover_eligible),
                blocked_by=None if takeover_eligible else "takeover_gate",
            )
        if path == GovernancePath.delegated_execution:
            if "goal_execution" in blocked_execution_types:
                return GovernancePathDecision(
                    path=path,
                    precedence_rank=_rank_for_path(path),
                    authority_owner="v2_authority",
                    android_scope="blocked_by_execution_runtime",
                    eligible=False,
                    blocked_by="execution_runtime_blocked:goal_execution",
                )
            if canonical_execution_gate_decision == "defer":
                return GovernancePathDecision(
                    path=path,
                    precedence_rank=_rank_for_path(path),
                    authority_owner="v2_authority",
                    android_scope="deferred_by_canonical_execution_gate",
                    eligible=False,
                    blocked_by="canonical_execution_gate:defer",
                )
            if canonical_execution_gate_decision == "deny":
                return GovernancePathDecision(
                    path=path,
                    precedence_rank=_rank_for_path(path),
                    authority_owner="v2_authority",
                    android_scope="blocked_by_canonical_execution_gate",
                    eligible=False,
                    blocked_by="canonical_execution_gate:deny",
                )
            return GovernancePathDecision(
                path=path,
                precedence_rank=_rank_for_path(path),
                authority_owner="v2_authority",
                android_scope="subordinate_executor",
                eligible=bool(dispatch_eligible),
                blocked_by=None if dispatch_eligible else "dispatch_gate",
            )
        if path in (
            GovernancePath.local_planning,
            GovernancePath.local_grounding,
            GovernancePath.local_execution,
        ):
            if highest_priority_execution_type == "takeover_request":
                return GovernancePathDecision(
                    path=path,
                    precedence_rank=_rank_for_path(path),
                    authority_owner="v2_authority",
                    android_scope="blocked_by_takeover_runtime_priority",
                    eligible=False,
                    blocked_by="execution_runtime_priority:takeover_request",
                )
            return GovernancePathDecision(
                path=path,
                precedence_rank=_rank_for_path(path),
                authority_owner="v2_authority",
                android_scope="bounded_local_participation",
                eligible=True,
            )
        if path == GovernancePath.multimodal_participation:
            # Multimodal participation requires live mesh runtime proof.
            # Partial, stale, structurally-inferred, or missing proof must
            # degrade this decision so governance does not overstate readiness.
            _mesh_proof_quality_normalized = str(mesh_proof_quality or "").strip().lower()
            if _mesh_proof_quality_normalized and _mesh_proof_quality_normalized != MESH_RUNTIME_PROOF_QUALITY_LIVE:
                return GovernancePathDecision(
                    path=path,
                    precedence_rank=_rank_for_path(path),
                    authority_owner="v2_authority",
                    android_scope="mesh_proof_degraded",
                    eligible=False,
                    blocked_by=f"mesh_proof_quality:{_mesh_proof_quality_normalized}",
                )
        return GovernancePathDecision(
            path=path,
            precedence_rank=_rank_for_path(path),
            authority_owner="v2_authority",
            android_scope="participatory_signal",
            eligible=True,
        )

    return GovernancePathDecision(
        path=path,
        precedence_rank=_rank_for_path(path),
        authority_owner="v2_authority",
        android_scope="unknown_mode",
        eligible=False,
        blocked_by="unknown_mode",
    )


def _derive_device_policy_outcome(
    *,
    mode: str,
    takeover_active: bool,
    paths: Dict[str, Dict[str, Any]],
    runtime_state_for_device: Dict[str, Any],
    canonical_truth_basis: Dict[str, Any],
    android_evidence_integration: Dict[str, Any],
    ownership_transfer_proof_sufficient: bool,
    ownership_transfer_proof_degraded: bool,
    mesh_governance_readiness_impact: str,
) -> Dict[str, Any]:
    """Derive executable governance-policy outcomes from unified governance state."""
    if mode == "local":
        primary_path = "local_execution"
    elif takeover_active:
        primary_path = "takeover"
    else:
        primary_path = "delegated_execution"
    primary_decision = dict(paths.get(primary_path, {}))
    blocked_by = str(primary_decision.get("blocked_by") or "").strip()
    eligible = bool(primary_decision.get("eligible", False))

    hard_block = _is_hard_block_reason(blocked_by)
    deferred = blocked_by == "canonical_execution_gate:defer"

    runtime_health_status = str(runtime_state_for_device.get("runtime_health_status") or "").strip().lower()
    freshness_state = str(
        canonical_truth_basis.get("canonical_truth_freshness_state") or ""
    ).strip().lower()
    integration_allowed = bool(android_evidence_integration.get("integration_allowed", False))
    recovery_truth_quality = str(
        android_evidence_integration.get("recovery_truth_quality") or ""
    ).strip().lower()
    recovery_truth_degraded = bool(android_evidence_integration.get("recovery_truth_degraded", False))
    degraded_signals = (
        runtime_health_status == "degraded"
        or freshness_state == "stale"
        or recovery_truth_degraded
        or ownership_transfer_proof_degraded
        or mesh_governance_readiness_impact != "none"
    )

    if hard_block:
        operation_state = "hard_block"
        automatic_decision = "block"
    elif deferred or (not eligible):
        operation_state = "soft_degraded"
        automatic_decision = "hold"
    elif degraded_signals:
        operation_state = "soft_degraded"
        automatic_decision = "allow_degraded"
    else:
        operation_state = "admissible"
        automatic_decision = "allow"

    minimum_viable_access_met = eligible and not hard_block
    retryable = blocked_by not in {"unknown_mode", "local_mode_boundary"}
    latest_phase = str(runtime_state_for_device.get("latest_execution_event_phase") or "").strip().lower()
    resumable = latest_phase in _POLICY_RESUMABLE_PHASES or (
        recovery_truth_quality not in _POLICY_INVALID_RECOVERY_QUALITIES
    )
    recovery_eligible = operation_state != "admissible" and (
        recovery_truth_quality not in _POLICY_INVALID_RECOVERY_QUALITIES
    )

    closure_acceptable = (
        ownership_transfer_proof_sufficient
        and integration_allowed
        and freshness_state != "stale"
    )
    if closure_acceptable and not degraded_signals:
        closure_quality_threshold = "meets_canonical"
    elif closure_acceptable:
        closure_quality_threshold = "meets_minimum"
    else:
        closure_quality_threshold = "below_minimum"

    if hard_block:
        dependency_severity = "critical"
    elif automatic_decision == "hold":
        dependency_severity = "high"
    elif operation_state == "soft_degraded":
        dependency_severity = "medium"
    else:
        dependency_severity = "low"

    if hard_block and not retryable:
        manual_decision = "suspend"
    elif hard_block or automatic_decision == "hold":
        manual_decision = "manual_review"
    elif not closure_acceptable:
        manual_decision = "override_eligible"
    else:
        manual_decision = "none"

    escalation_required = (
        dependency_severity in _POLICY_ESCALATION_SEVERITIES
        or manual_decision in _POLICY_ESCALATION_MANUAL_DECISIONS
    )
    escalation_level = (
        "immediate"
        if dependency_severity == "critical"
        else "operator_review" if escalation_required else "none"
    )

    reasons: List[str] = []
    if blocked_by:
        reasons.append(f"blocked_by:{blocked_by}")
    if runtime_health_status:
        reasons.append(f"runtime_health_status:{runtime_health_status}")
    if freshness_state:
        reasons.append(f"canonical_truth_freshness:{freshness_state}")
    if mesh_governance_readiness_impact and mesh_governance_readiness_impact != "none":
        reasons.append(f"mesh_readiness_impact:{mesh_governance_readiness_impact}")
    if recovery_truth_quality:
        reasons.append(f"recovery_truth_quality:{recovery_truth_quality}")

    return {
        "policy_authoritative": True,
        "operation_state": operation_state,
        "primary_path": primary_path,
        "automatic_decision": automatic_decision,
        "manual_decision": manual_decision,
        "minimum_viable_access": {
            "met": minimum_viable_access_met,
            "authoritative_stage": "admission",
        },
        "retryability": {
            "retryable": retryable,
            "resumable": resumable,
            "deferral_eligible": automatic_decision == "hold",
        },
        "recovery_eligibility": {
            "eligible": recovery_eligible,
            "mode": "automatic" if recovery_eligible and manual_decision == "none" else "manual",
        },
        "closure_policy": {
            "acceptable": closure_acceptable,
            "quality_threshold": closure_quality_threshold,
            "authoritative_stage": "closure",
        },
        "dependency_classification": {
            "severity": dependency_severity,
            "reasons": reasons,
        },
        "escalation": {
            "required": escalation_required,
            "level": escalation_level,
            "defer_allowed": dependency_severity == "medium" or automatic_decision == "hold",
        },
        "_policy": UNIFIED_GOVERNANCE_POLICY_LAYER_POLICY,
        "_contract_version": UNIFIED_GOVERNANCE_POLICY_LAYER_CONTRACT_VERSION,
    }


def build_unified_governance_state(
    device_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    try:
        from core.attached_runtime_session_registry import list_active_sessions
        from core.android_mode_gate_policy import (
            build_mode_state_for_device,
            evaluate_android_mode_readiness,
            resolve_android_execution_gate_decision,
        )
        from core.unified_execution_governance import (
            classify_canonical_proof_input_diagnosis,
            get_execution_runtime_snapshot,
            is_takeover_active,
        )
    except Exception:
        return {
            "devices": [],
            "local_mode_count": 0,
            "cross_device_mode_count": 0,
            "takeover_active_count": 0,
            "execution_runtime_state": {
                "devices": [],
                "active_device_count": 0,
                "active_execution_total_count": 0,
                "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
            },
            "mesh_runtime_state": {
                "status": MESH_RUNTIME_STATUS_UNAVAILABLE,
                "runtime_proof_count": 0,
                "runtime_relationships": [],
                "deferred_or_constrained": ["governance dependencies unavailable"],
                "_policy": MESH_RUNTIME_STATUS_POLICY,
                "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
            },
            "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
            "_contract_version": UNIFIED_GOVERNANCE_SEMANTICS_CONTRACT_VERSION,
        }
    try:
        from core.android_evidence_integration_pipeline import (
            get_android_evidence_integration_summary,
        )
        android_evidence_integration_summary_fn = get_android_evidence_integration_summary
    except Exception:
        def _fallback_get_android_evidence_integration_summary(  # type: ignore[misc]
            device_id: str,
            execution_id: str = "",
            *,
            runtime_state: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            return {
                "device_id": device_id,
                "execution_id": execution_id,
                "integration_decision": "deny",
                "integration_allowed": False,
                "overall_grade": "absent",
                "dimension_results": [],
                "degradation_causes": [
                    "android_evidence_integration_summary_unavailable"
                ],
                "recovery_truth_quality": "not_provided",
                "recovery_truth_degraded": False,
                "recovery_truth_gap_types": [],
                "recovery_truth_diagnosis": "recovery_truth_not_provided",
            }
        android_evidence_integration_summary_fn = _fallback_get_android_evidence_integration_summary

    try:
        from core.canonical_cross_repo_evidence_pipeline import (
            get_canonical_cross_repo_evidence_report,
        )
        canonical_cross_repo_report_fn = get_canonical_cross_repo_evidence_report
    except Exception:
        def _fallback_get_canonical_cross_repo_evidence_report() -> Dict[str, Any]:  # type: ignore[misc]
            return {
                "pipeline_verdict": "insufficient",
                "is_complete": False,
                "primary_sources_complete": False,
                "primary_sources_fresh": False,
                "downgrade_reasons": [
                    "canonical_cross_repo_evidence_report_unavailable"
                ],
                "sources": [],
            }

        canonical_cross_repo_report_fn = _fallback_get_canonical_cross_repo_evidence_report

    cross_repo_truth_report = _normalize_cross_repo_truth_report(
        canonical_cross_repo_report_fn()
    )

    if device_ids is None:
        try:
            device_ids = [e.device_id for e in list_active_sessions()]
        except Exception:
            device_ids = []
    # Deduplicate while preserving the previously collected session order.
    device_ids = list(dict.fromkeys(device_ids or []))
    execution_runtime_state = get_execution_runtime_snapshot(device_ids=device_ids)
    runtime_by_device = {
        entry["device_id"]: entry
        for entry in execution_runtime_state.get("devices", [])
        if isinstance(entry.get("device_id"), str) and entry.get("device_id")
    }

    # Build mesh runtime state once up-front so proof quality can be threaded
    # into every per-device path decision (PR-08v2 degradation requirement).
    mesh_runtime_state = build_mesh_runtime_state()
    mesh_proof_quality: Optional[str] = mesh_runtime_state.get("proof_quality")
    mesh_governance_readiness_impact: str = str(
        mesh_runtime_state.get("governance_readiness_impact", "blocked_no_proof")
    )

    devices: List[Dict[str, Any]] = []
    policy_devices: List[Dict[str, Any]] = []
    local_mode_count = 0
    cross_device_mode_count = 0
    takeover_active_count = 0

    for device_id in list(device_ids):
        try:
            mode_state = build_mode_state_for_device(device_id)
            readiness = evaluate_android_mode_readiness(device_id)
            takeover_active = is_takeover_active(device_id)
        except Exception:
            continue

        mode = getattr(mode_state.mode, "value", str(mode_state.mode))
        dispatch_eligible = bool(getattr(readiness, "is_dispatch_eligible", False))
        takeover_eligible = bool(getattr(readiness, "is_takeover_eligible", False))
        runtime_state_for_device = dict(runtime_by_device.get(device_id, {}))

        # PR-7A: Compute proof_input_diagnosis BEFORE the canonical gate so
        # that Android capability truth quality can degrade the gate decision.
        # Absent/stale/conflicting/downgraded Android truth must NOT be treated
        # as positive evidence — the gate decision must reflect this explicitly.
        proof_input_diagnosis = classify_canonical_proof_input_diagnosis(
            runtime_state_for_device
        )
        android_capability_truth_quality: Optional[str] = str(
            proof_input_diagnosis.get("proof_input_class") or ""
        ).strip() or None
        primary_execution_id = _extract_primary_execution_id(runtime_state_for_device)
        android_evidence_integration = android_evidence_integration_summary_fn(
            device_id,
            primary_execution_id,
            runtime_state=runtime_state_for_device,
        )
        if not isinstance(android_evidence_integration, dict):
            android_evidence_integration = {
                "device_id": device_id,
                "execution_id": primary_execution_id,
                "integration_decision": "deny",
                "integration_allowed": False,
                "overall_grade": "absent",
                "dimension_results": [],
                "degradation_causes": [
                    "android_evidence_integration_summary_invalid_shape"
                ],
                "recovery_truth_quality": "not_provided",
                "recovery_truth_degraded": False,
                "recovery_truth_gap_types": [],
                "recovery_truth_diagnosis": "recovery_truth_not_provided",
            }

        canonical_gate = resolve_android_execution_gate_decision(
            policy_eligible=dispatch_eligible,
            readiness_ready=bool(getattr(readiness, "is_cross_device_ready", False)),
            execution_busy=bool(runtime_state_for_device.get("execution_busy", False)),
            local_inference_available=bool(
                runtime_state_for_device.get("local_inference_available", False)
            ),
            fallback_tier=runtime_state_for_device.get("current_fallback_tier"),
            android_capability_truth_quality=android_capability_truth_quality,
        )
        if mode == "local":
            local_mode_count += 1
        elif mode == "cross_device":
            cross_device_mode_count += 1

        if takeover_active:
            takeover_active_count += 1

        # PR-16: Classify ownership-transfer proof quality for this device so
        # that governance state carries explicit degraded/confirmed classification
        # rather than only raw ownership_state strings.  This ensures resumed
        # ownership transfer is never silently treated as confirmed closure
        # based on insufficient evidence.
        ownership_transfer_proof_result: Optional[Any] = None
        ownership_transfer_proof_class: Optional[str] = None
        ownership_transfer_proof_sufficient: bool = False
        ownership_transfer_proof_degraded: bool = True
        ownership_transfer_proof_diagnosis: List[str] = []
        if _OWNERSHIP_TRANSFER_PROOF_QUALITY_AVAILABLE:
            try:
                ownership_transfer_proof_result = (
                    get_latest_ownership_transfer_proof_quality_for_device(device_id)
                )
                if ownership_transfer_proof_result is not None:
                    _pq = ownership_transfer_proof_result
                    ownership_transfer_proof_class = str(
                        getattr(_pq.proof_class, "value", str(_pq.proof_class))
                    )
                    ownership_transfer_proof_sufficient = bool(
                        _pq.is_sufficient_for_closure
                    )
                    ownership_transfer_proof_degraded = bool(_pq.degraded)
                    ownership_transfer_proof_diagnosis = list(_pq.diagnosis)
            except Exception:
                ownership_transfer_proof_diagnosis = [
                    "ownership_transfer_proof_quality_lookup_failed"
                ]

        android_originated_canonical_diagnosis = _build_android_originated_canonical_diagnosis(
            runtime_state_for_device=runtime_state_for_device,
            proof_input_diagnosis=proof_input_diagnosis,
            android_evidence_integration=android_evidence_integration,
            ownership_transfer_proof_class=ownership_transfer_proof_class,
            ownership_transfer_proof_diagnosis=ownership_transfer_proof_diagnosis,
            mesh_runtime_state=mesh_runtime_state,
            mesh_proof_quality=mesh_proof_quality,
        )
        canonical_truth_basis = _derive_canonical_truth_basis(
            runtime_state_for_device=runtime_state_for_device,
            proof_input_diagnosis=proof_input_diagnosis,
            cross_repo_truth_report=cross_repo_truth_report,
        )

        paths: Dict[str, Dict[str, Any]] = {}
        for path in GovernancePath:
            decision = resolve_governance_path_decision(
                mode=mode,
                path=path,
                dispatch_eligible=dispatch_eligible,
                takeover_eligible=takeover_eligible,
                takeover_active=takeover_active,
                highest_priority_execution_type=runtime_state_for_device.get(
                    "highest_priority_execution_type"
                ),
                blocked_execution_types=list(
                    runtime_state_for_device.get("blocked_execution_types", [])
                ),
                canonical_execution_gate_decision=canonical_gate.decision,
                mesh_proof_quality=mesh_proof_quality,
            )
            decision_dict = decision.to_dict()
            decision_dict["decision_causality"] = {
                "mode": mode,
                "dispatch_eligible": dispatch_eligible,
                "takeover_eligible": takeover_eligible,
                "takeover_active": takeover_active,
                "active_execution_count": int(
                    runtime_state_for_device.get("active_execution_count", 0)
                ),
                "highest_priority_execution_type": runtime_state_for_device.get(
                    "highest_priority_execution_type"
                ),
                "blocked_execution_types": list(
                    runtime_state_for_device.get("blocked_execution_types", [])
                ),
                "offline_queue_depth": int(
                    runtime_state_for_device.get("offline_queue_depth", 0) or 0
                ),
                "execution_busy": bool(
                    runtime_state_for_device.get("execution_busy", False)
                ),
                "local_inference_available": bool(
                    runtime_state_for_device.get("local_inference_available", False)
                ),
                "android_reported_mode": runtime_state_for_device.get(
                    "android_reported_mode"
                ),
                "android_reported_mode_state": runtime_state_for_device.get(
                    "android_reported_mode_state"
                ),
                "android_reported_mode_readiness_state": runtime_state_for_device.get(
                    "android_reported_mode_readiness_state"
                ),
                "android_reported_cross_device_eligibility": runtime_state_for_device.get(
                    "android_reported_cross_device_eligibility"
                ),
                "android_reported_goal_execution_eligibility": runtime_state_for_device.get(
                    "android_reported_goal_execution_eligibility"
                ),
                "android_reported_parallel_execution_eligibility": runtime_state_for_device.get(
                    "android_reported_parallel_execution_eligibility"
                ),
                "android_reported_local_intelligence_status": runtime_state_for_device.get(
                    "android_reported_local_intelligence_status"
                ),
                "android_reported_local_inference_ready": runtime_state_for_device.get(
                    "android_reported_local_inference_ready"
                ),
                "android_reported_local_inference_available": runtime_state_for_device.get(
                    "android_reported_local_inference_available"
                ),
                "android_semantics_contract_state": runtime_state_for_device.get(
                    "android_semantics_contract_state"
                ),
                "android_semantics_contract_complete": bool(
                    runtime_state_for_device.get("android_semantics_contract_complete", False)
                ),
                "android_semantics_missing_keys": list(
                    runtime_state_for_device.get("android_semantics_missing_keys", [])
                ),
                "android_semantics_malformed_keys": list(
                    runtime_state_for_device.get("android_semantics_malformed_keys", [])
                ),
                "android_semantics_unknown_keys": list(
                    runtime_state_for_device.get("android_semantics_unknown_keys", [])
                ),
                "android_semantics_conflicts": list(
                    runtime_state_for_device.get("android_semantics_conflicts", [])
                ),
                "android_semantics_downgraded_reasons": list(
                    runtime_state_for_device.get(
                        "android_semantics_downgraded_reasons", []
                    )
                ),
                "android_semantics_governance_readiness_impact": runtime_state_for_device.get(
                    "android_semantics_governance_readiness_impact"
                ),
                "android_semantics_contract_diagnosis": runtime_state_for_device.get(
                    "android_semantics_contract_diagnosis"
                ),
                "android_semantics_absorbed_at": float(
                    runtime_state_for_device.get("android_semantics_absorbed_at", 0.0)
                ),
                "android_semantics_reported_at": (
                    float(runtime_state_for_device.get("android_semantics_reported_at"))
                    if runtime_state_for_device.get("android_semantics_reported_at") is not None
                    else None
                ),
                "android_semantics_age_s": (
                    float(runtime_state_for_device.get("android_semantics_age_s"))
                    if runtime_state_for_device.get("android_semantics_age_s") is not None
                    else None
                ),
                "android_semantics_freshness_threshold_s": float(
                    runtime_state_for_device.get("android_semantics_freshness_threshold_s", 0.0)
                    or 0.0
                ),
                "android_semantics_freshness_state": runtime_state_for_device.get(
                    "android_semantics_freshness_state"
                ),
                "android_semantics_freshness_reason": runtime_state_for_device.get(
                    "android_semantics_freshness_reason"
                ),
                "android_runtime_truth_authority": runtime_state_for_device.get(
                    "android_runtime_truth_authority"
                ),
                "android_runtime_truth_usable": bool(
                    runtime_state_for_device.get("android_runtime_truth_usable", False)
                ),
                "runtime_health_status": runtime_state_for_device.get(
                    "runtime_health_status"
                ),
                "current_fallback_tier": runtime_state_for_device.get(
                    "current_fallback_tier"
                ),
                "canonical_execution_gate_decision": canonical_gate.decision,
                "canonical_execution_gate_reasons": list(canonical_gate.reasons),
                "capability_ready": canonical_gate.capability_ready,
                "snapshot_reconciliation_status": runtime_state_for_device.get(
                    "snapshot_reconciliation_status"
                ),
                "snapshot_reconciliation_reason": runtime_state_for_device.get(
                    "snapshot_reconciliation_reason"
                ),
                "snapshot_conflict": bool(
                    runtime_state_for_device.get("snapshot_conflict", False)
                ),
                "snapshot_ordering_basis": runtime_state_for_device.get(
                    "snapshot_ordering_basis"
                ),
                "snapshot_last_updated_at": float(
                    runtime_state_for_device.get("snapshot_last_updated_at", 0.0) or 0.0
                ),
                "snapshot_reconciliation_applied": bool(
                    runtime_state_for_device.get("snapshot_reconciliation_applied", False)
                ),
                "snapshot_continuity_state": _snapshot_continuity_state(
                    status=runtime_state_for_device.get("snapshot_reconciliation_status"),
                    conflict=bool(runtime_state_for_device.get("snapshot_conflict", False)),
                ),
                "latest_execution_event_phase": runtime_state_for_device.get(
                    "latest_execution_event_phase"
                ),
                "latest_execution_event_absorbed_at": float(
                    runtime_state_for_device.get("latest_execution_event_absorbed_at", 0.0)
                    or 0.0
                ),
                "latest_execution_event_age_s": (
                    float(runtime_state_for_device.get("latest_execution_event_age_s"))
                    if runtime_state_for_device.get("latest_execution_event_age_s") is not None
                    else None
                ),
                "execution_busy_window_seconds": float(
                    runtime_state_for_device.get("execution_busy_window_seconds", 60.0)
                    or 60.0
                ),
                "mesh_proof_quality": mesh_proof_quality,
                "mesh_governance_readiness_impact": mesh_governance_readiness_impact,
                # PR-7A: use the pre-computed proof_input_diagnosis (computed
                # before the canonical gate so truth quality affects the
                # gate decision, not only observability).
                "proof_input_diagnosis": proof_input_diagnosis,
                # PR-7A: Android capability truth quality fields.
                # These expose whether the gate decision was degraded due to
                # absent/stale/conflicting Android capability evidence, so
                # operators can distinguish truth-driven denials from
                # eligibility-driven denials.
                "android_capability_truth_quality": android_capability_truth_quality,
                "android_capability_truth_degraded": bool(
                    canonical_gate.android_capability_truth_degraded
                ),
                # ── PR-5: Android execution lifecycle truth quality ───────────
                # Reflects Android-remote-confirmed vs V2-local-only vs
                # stale/missing/conflicting remote state.  These fields ensure
                # decision_causality reflects Android truth quality rather than
                # only V2-local bookkeeping.
                "android_lifecycle_truth_quality": runtime_state_for_device.get(
                    "android_lifecycle_truth_quality"
                ),
                "android_lifecycle_truth_reason": runtime_state_for_device.get(
                    "android_lifecycle_truth_reason"
                ),
                "android_lifecycle_truth_degraded": bool(
                    runtime_state_for_device.get("android_lifecycle_truth_degraded", False)
                ),
                "android_lifecycle_truth_governance_impact": runtime_state_for_device.get(
                    "android_lifecycle_truth_governance_impact"
                ),
                "android_evidence_integration_execution_id": primary_execution_id,
                "android_evidence_integration_decision": android_evidence_integration.get(
                    "integration_decision"
                ),
                "android_evidence_integration_allowed": bool(
                    android_evidence_integration.get("integration_allowed", False)
                ),
                "android_evidence_integration_grade": android_evidence_integration.get(
                    "overall_grade"
                ),
                "android_evidence_integration_degradation_causes": list(
                    android_evidence_integration.get("degradation_causes", [])
                ),
                "android_evidence_recovery_truth_quality": android_evidence_integration.get(
                    "recovery_truth_quality"
                ),
                "android_evidence_recovery_truth_degraded": bool(
                    android_evidence_integration.get("recovery_truth_degraded", False)
                ),
                "android_evidence_recovery_truth_gap_types": list(
                    android_evidence_integration.get("recovery_truth_gap_types", [])
                ),
                "android_evidence_recovery_truth_diagnosis": android_evidence_integration.get(
                    "recovery_truth_diagnosis"
                ),
                # PR-16: Ownership-transfer proof quality.  Consumers MUST
                # check ownership_transfer_proof_sufficient before treating
                # any ownership-transfer state as confirmed closure.
                "ownership_transfer_proof_class": ownership_transfer_proof_class,
                "ownership_transfer_proof_sufficient": ownership_transfer_proof_sufficient,
                "ownership_transfer_proof_degraded": ownership_transfer_proof_degraded,
                "ownership_transfer_proof_diagnosis": list(
                    ownership_transfer_proof_diagnosis
                ),
                "android_originated_canonical_diagnosis": android_originated_canonical_diagnosis,
                **canonical_truth_basis,
                "cross_repo_truth_pipeline_verdict": cross_repo_truth_report.get(
                    "pipeline_verdict"
                ),
                "cross_repo_truth_is_complete": bool(
                    cross_repo_truth_report.get("is_complete", False)
                ),
                "cross_repo_truth_primary_sources_complete": bool(
                    cross_repo_truth_report.get("primary_sources_complete", False)
                ),
                "cross_repo_truth_primary_sources_fresh": bool(
                    cross_repo_truth_report.get("primary_sources_fresh", False)
                ),
                "cross_repo_truth_downgrade_reasons": list(
                    cross_repo_truth_report.get("downgrade_reasons", [])
                ),
                "cross_repo_truth_source_provenance": list(
                    cross_repo_truth_report.get("source_provenance", [])
                ),
            }
            paths[path.value] = decision_dict

        devices.append(
            {
                "device_id": device_id,
                "mode": mode,
                "android_autonomy_scope": _autonomy_scope_for_mode(mode),
                "dispatch_eligible": dispatch_eligible,
                "takeover_eligible": takeover_eligible,
                "takeover_active": takeover_active,
                "runtime_execution_state": runtime_state_for_device,
                "android_evidence_integration": android_evidence_integration,
                "android_originated_canonical_diagnosis": android_originated_canonical_diagnosis,
                "governance_policy": _derive_device_policy_outcome(
                    mode=mode,
                    takeover_active=takeover_active,
                    paths=paths,
                    runtime_state_for_device=runtime_state_for_device,
                    canonical_truth_basis=canonical_truth_basis,
                    android_evidence_integration=android_evidence_integration,
                    ownership_transfer_proof_sufficient=ownership_transfer_proof_sufficient,
                    ownership_transfer_proof_degraded=ownership_transfer_proof_degraded,
                    mesh_governance_readiness_impact=mesh_governance_readiness_impact,
                ),
                "governance_precedence": paths,
                "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
            }
        )
        policy_devices.append(
            {
                "device_id": device_id,
                "policy_outcome": devices[-1]["governance_policy"],
            }
        )

    hard_block_count = sum(
        1 for item in policy_devices if item["policy_outcome"].get("operation_state") == "hard_block"
    )
    soft_degraded_count = sum(
        1 for item in policy_devices if item["policy_outcome"].get("operation_state") == "soft_degraded"
    )
    manual_decision_count = sum(
        1 for item in policy_devices if item["policy_outcome"].get("manual_decision") != "none"
    )

    return {
        "devices": devices,
        "local_mode_count": local_mode_count,
        "cross_device_mode_count": cross_device_mode_count,
        "takeover_active_count": takeover_active_count,
        "execution_runtime_state": execution_runtime_state,
        "mesh_runtime_state": mesh_runtime_state,
        "policy_layer": {
            "devices": policy_devices,
            "summary": {
                "hard_block_count": hard_block_count,
                "soft_degraded_count": soft_degraded_count,
                "manual_decision_count": manual_decision_count,
            },
            "_policy": UNIFIED_GOVERNANCE_POLICY_LAYER_POLICY,
            "_contract_version": UNIFIED_GOVERNANCE_POLICY_LAYER_CONTRACT_VERSION,
            "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
        },
        "authority": "v2_semantic_orchestration_authority",
        "_source": UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY,
        "_contract_version": UNIFIED_GOVERNANCE_SEMANTICS_CONTRACT_VERSION,
    }


__all__ = [
    "UNIFIED_GOVERNANCE_SEMANTICS_AUTHORITY",
    "UNIFIED_GOVERNANCE_SEMANTICS_CONTRACT_VERSION",
    "GovernancePath",
    "GovernancePathDecision",
    "MESH_RUNTIME_STATUS_POLICY",
    "MESH_RUNTIME_STATUS_RUNTIME_PROVEN",
    "MESH_RUNTIME_STATUS_PARTIAL",
    "MESH_RUNTIME_STATUS_CONTRACT_ONLY",
    "MESH_RUNTIME_STATUS_UNAVAILABLE",
    "MESH_RUNTIME_PROOF_QUALITY_LIVE",
    "MESH_RUNTIME_PROOF_QUALITY_STALE",
    "MESH_RUNTIME_PROOF_QUALITY_PARTIAL",
    "MESH_RUNTIME_PROOF_QUALITY_STRUCTURALLY_INFERRED",
    "MESH_RUNTIME_PROOF_QUALITY_MISSING",
    "MESH_RUNTIME_PROOF_STALE_AFTER_SECONDS",
    "MESH_RUNTIME_PROOF_QUALITY_POLICY",
    "UNIFIED_GOVERNANCE_POLICY_LAYER_POLICY",
    "UNIFIED_GOVERNANCE_POLICY_LAYER_CONTRACT_VERSION",
    "ANDROID_ORIGINATED_CANONICAL_DIAGNOSIS_CONTRACT_VERSION",
    "ANDROID_ORIGINATED_CANONICAL_DIAGNOSIS_POLICY",
    "build_mesh_runtime_state",
    "resolve_governance_path_decision",
    "build_unified_governance_state",
    # Proof-input diagnosis (re-exported from unified_execution_governance for
    # convenience so consumers only need one import target).
    "classify_canonical_proof_input_diagnosis",
    # PR-5: Android execution lifecycle truth quality (re-exported).
    "ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY",
    "EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL",
    "EXECUTION_LIFECYCLE_TRUTH_BINDING_CONTRACT_VERSION",
    "ANDROID_EXECUTION_LIFECYCLE_TRUTH_STALE_AFTER_SECONDS",
    "AndroidExecutionLifecycleTruthQuality",
    "ExecutionLifecycleTruthBinding",
    "get_execution_lifecycle_truth_binding",
    # PR-16: Ownership-transfer proof quality (re-exported from
    # core.ownership_transfer_proof_quality for convenience).
    "OWNERSHIP_TRANSFER_PROOF_QUALITY_SENTINEL",
    "OWNERSHIP_TRANSFER_PROOF_QUALITY_CONTRACT_VERSION",
    "RESUMED_OWNERSHIP_TRANSFER_REQUIRES_PROOF_POLICY",
    "OWNERSHIP_TRANSFER_PROOF_QUALITY_POLICY",
    "STALE_OWNERSHIP_EVIDENCE_THRESHOLD_SECONDS",
    "OwnershipTransferProofClass",
    "OwnershipTransferProofQualityResult",
    "classify_ownership_transfer_proof_quality",
    "get_latest_ownership_transfer_proof_quality_for_device",
]
