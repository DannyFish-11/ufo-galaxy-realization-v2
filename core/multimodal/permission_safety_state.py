"""core/multimodal/permission_safety_state.py — Permission Visibility, Trust Surfaces,
and Control Safety for Multimodal Runtime (PR-32)

**Unified-Subject Architecture — Runtime Shell Ownership**
------------------------------------------------------------
Permission visibility and trust/risk labelling are owned by the runtime shell
(:class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`).  OpenClawd
core consumes the canonical safety snapshot when making control decisions; the
execution and projection layers surface it without inventing separate trust
semantics.

This module provides:

- Explicit permission state visibility for each active modality/source
- Trust/risk labels for active sensing and execution modes
- Sensitive-modality guardrails and safety gating metadata
- Remote-execution and elevated-risk execution trust/safety annotations
- Audit-oriented safety state suitable for diagnostics and projection
- Operator-facing shell summaries derived from the canonical state (not
  acting as a separate truth source)

**Behavioural guarantees**

1. **Shell owns presentation** — the runtime shell decides how trust and
   permission state is presented.  This module produces canonical artifacts
   that the shell consumes.
2. **Safety state is canonical** — projection, diagnostics, and policy layers
   all consume the same :class:`PermissionSafetySnapshot`; no shadow state.
3. **Missing/denied permissions surface clearly** — each modality's
   :class:`ModalityPermissionRecord` carries a ``gating_reason`` that
   explains why sensing is unavailable or restricted.
4. **High-risk execution is visible** — :class:`ExecutionTrustAnnotation`
   captures elevated-risk posture so shells and diagnostics can surface it.
5. **Serialisation-safe** — all public dataclasses expose ``to_dict()`` /
   ``from_dict()`` and store only plain Python primitives.

Usage::

    from core.multimodal.permission_safety_state import (
        get_permission_safety_state,
        build_permission_safety_snapshot,
        build_operator_safety_summary,
    )

    state = get_permission_safety_state()
    snap = build_permission_safety_snapshot(
        source_registry_snapshot=registry.snapshot(),
        multimodal_route=route_dict,
        execution_plan=plan_dict,
    )
    summary = build_operator_safety_summary(snap)
    import json; json.dumps(snap.to_dict())  # always safe
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class PermissionStatus(str, Enum):
    """Explicit permission state for a modality or resource.

    These are the only values that should appear in
    :attr:`ModalityPermissionRecord.permission_status`.
    """

    GRANTED = "granted"
    """Permission is present and currently effective."""

    DENIED = "denied"
    """Permission was explicitly refused by the operator or platform."""

    UNAVAILABLE = "unavailable"
    """The resource/hardware is absent or cannot be reached regardless of
    permission (e.g. no microphone device detected)."""

    UNKNOWN = "unknown"
    """Permission state has not been queried or cannot be determined."""

    @classmethod
    def from_string(cls, value: str) -> "PermissionStatus":
        """Return a :class:`PermissionStatus` from a raw string, defaulting to
        :attr:`UNKNOWN` for unrecognised values."""
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN


class TrustLabel(str, Enum):
    """Trust/risk label for an active sensing modality or execution mode.

    Used to annotate the current trust posture of a modality or execution
    decision so that shells and operators can gauge risk at a glance.
    """

    TRUSTED = "trusted"
    """Normal, low-risk operation with full permissions and healthy sources."""

    ELEVATED = "elevated"
    """Moderately elevated trust requirement — e.g. remote execution, cross-
    device data sharing, or a sensitive but permitted modality."""

    SENSITIVE = "sensitive"
    """Modality or action involves sensitive data (microphone, camera, screen
    capture) and requires explicit operator awareness."""

    RESTRICTED = "restricted"
    """Operation is gated: a permission is missing or denied, the source is
    unhealthy, or a policy guard has limited the action."""

    UNKNOWN = "unknown"
    """Trust posture cannot be determined from available information."""

    @classmethod
    def from_string(cls, value: str) -> "TrustLabel":
        """Return a :class:`TrustLabel` from a raw string, defaulting to
        :attr:`UNKNOWN` for unrecognised values."""
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN


class SafetyGatingReason(str, Enum):
    """Stable vocabulary of reasons why a modality or action has been gated.

    Each value is a stable string identifier suitable for serialisation and
    diagnostics.  Shells and projection layers should display the human-readable
    label derived from these values rather than embedding the enum name.
    """

    PERMISSION_DENIED = "permission_denied"
    """The operator or platform explicitly denied the required permission."""

    PERMISSION_UNAVAILABLE = "permission_unavailable"
    """The required permission cannot be granted (hardware absent, platform
    unsupported, etc.)."""

    PERMISSION_UNKNOWN = "permission_unknown"
    """Permission state has not been determined yet."""

    SOURCE_DEGRADED = "source_degraded"
    """The perception source is degraded and cannot provide reliable signal."""

    SOURCE_UNAVAILABLE = "source_unavailable"
    """The perception source is completely unavailable."""

    SOURCE_STALE = "source_stale"
    """The perception source data is stale beyond the freshness threshold."""

    SENSITIVE_MODALITY_UNCONFIRMED = "sensitive_modality_unconfirmed"
    """A sensitive modality (microphone/camera/screen) is active but the
    operator has not explicitly confirmed awareness of it."""

    REMOTE_EXECUTION_UNCONFIRMED = "remote_execution_unconfirmed"
    """A remote or cross-device execution is pending but lacks operator
    confirmation or eligibility metadata."""

    ELEVATED_RISK_UNREVIEWED = "elevated_risk_unreviewed"
    """An elevated-risk action has not been reviewed for its trust posture."""

    POLICY_GUARD = "policy_guard"
    """A policy guard or architecture invariant has blocked the action."""

    NONE = "none"
    """No gating is active; operation is permitted."""

    @classmethod
    def from_string(cls, value: str) -> "SafetyGatingReason":
        """Return a :class:`SafetyGatingReason` from a raw string, defaulting
        to :attr:`NONE` for unrecognised values."""
        try:
            return cls(value)
        except ValueError:
            return cls.NONE


class ExecutionRiskTier(str, Enum):
    """Risk tier for a planned or in-flight execution action.

    Used on :class:`ExecutionTrustAnnotation` to communicate to shells and
    diagnostics layers how much trust posture the current action requires.
    """

    LOCAL_SAFE = "local_safe"
    """Local action with no elevated risk (text response, local display, etc.)."""

    LOCAL_ELEVATED = "local_elevated"
    """Local action with moderate risk (file system mutation, UI automation, etc.)."""

    REMOTE_STANDARD = "remote_standard"
    """Standard remote/cross-device action under normal orchestration."""

    REMOTE_ELEVATED = "remote_elevated"
    """Remote action with elevated trust requirement (privileged command, agent
    deployment, etc.)."""

    UNKNOWN = "unknown"
    """Risk tier cannot be determined from available information."""

    @classmethod
    def from_string(cls, value: str) -> "ExecutionRiskTier":
        """Return an :class:`ExecutionRiskTier` from a raw string, defaulting
        to :attr:`UNKNOWN` for unrecognised values."""
        try:
            return cls(value)
        except ValueError:
            return cls.UNKNOWN


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ModalityPermissionRecord:
    """Permission and trust state for a single active modality/source.

    Attributes
    ----------
    modality:
        Human-readable name of the modality (``"microphone"``, ``"camera"``,
        ``"screen"``, ``"text"``, etc.).
    source_id:
        Optional unique identifier of the backing perception source.
    permission_status:
        Explicit permission state as a :class:`PermissionStatus` value.
    trust_label:
        Derived trust/risk label for this modality's current state.
    is_active:
        Whether the modality is currently producing signal.
    is_sensitive:
        Whether this modality is classified as sensitive (microphone, camera,
        screen capture).
    gating_reason:
        The primary reason if this modality is restricted or gated.
    gating_reasons:
        Full list of gating reasons if multiple apply.
    assessed_at:
        Wall-clock timestamp (seconds) when this record was assessed.
    """

    modality: str = ""
    source_id: Optional[str] = None
    permission_status: PermissionStatus = PermissionStatus.UNKNOWN
    trust_label: TrustLabel = TrustLabel.UNKNOWN
    is_active: bool = False
    is_sensitive: bool = False
    gating_reason: SafetyGatingReason = SafetyGatingReason.NONE
    gating_reasons: List[str] = field(default_factory=list)
    assessed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "modality": self.modality,
            "source_id": self.source_id,
            "permission_status": self.permission_status.value,
            "trust_label": self.trust_label.value,
            "is_active": self.is_active,
            "is_sensitive": self.is_sensitive,
            "gating_reason": self.gating_reason.value,
            "gating_reasons": list(self.gating_reasons),
            "assessed_at": self.assessed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModalityPermissionRecord":
        return cls(
            modality=str(data.get("modality", "")),
            source_id=data.get("source_id"),
            permission_status=PermissionStatus.from_string(
                str(data.get("permission_status", PermissionStatus.UNKNOWN.value))
            ),
            trust_label=TrustLabel.from_string(
                str(data.get("trust_label", TrustLabel.UNKNOWN.value))
            ),
            is_active=bool(data.get("is_active", False)),
            is_sensitive=bool(data.get("is_sensitive", False)),
            gating_reason=SafetyGatingReason.from_string(
                str(data.get("gating_reason", SafetyGatingReason.NONE.value))
            ),
            gating_reasons=list(data.get("gating_reasons") or []),
            assessed_at=float(data.get("assessed_at", time.time())),
        )


@dataclass
class ExecutionTrustAnnotation:
    """Trust/safety annotation for a planned or in-flight execution action.

    Attributes
    ----------
    execution_id:
        Optional correlation ID for the execution action.
    risk_tier:
        Execution risk tier (:class:`ExecutionRiskTier`).
    trust_label:
        Overall trust label for this action.
    is_remote:
        Whether the action involves remote/cross-device execution.
    is_elevated:
        Whether the action requires elevated trust posture.
    requires_confirmation:
        Whether operator confirmation is required before proceeding.
    remote_execution_mode:
        Optional string from ``RemoteExecutionMode`` (``"agent_runtime"`` /
        ``"command_only"``) when applicable.
    eligibility_confirmed:
        Whether eligibility for this execution tier has been confirmed.
    gating_reason:
        Primary safety gating reason if the action is restricted.
    gating_reasons:
        Full list of safety gating reasons.
    annotation_id:
        Unique ID for this annotation record.
    annotated_at:
        Wall-clock timestamp when this annotation was produced.
    """

    execution_id: Optional[str] = None
    risk_tier: ExecutionRiskTier = ExecutionRiskTier.UNKNOWN
    trust_label: TrustLabel = TrustLabel.UNKNOWN
    is_remote: bool = False
    is_elevated: bool = False
    requires_confirmation: bool = False
    remote_execution_mode: Optional[str] = None
    eligibility_confirmed: bool = False
    gating_reason: SafetyGatingReason = SafetyGatingReason.NONE
    gating_reasons: List[str] = field(default_factory=list)
    annotation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    annotated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "risk_tier": self.risk_tier.value,
            "trust_label": self.trust_label.value,
            "is_remote": self.is_remote,
            "is_elevated": self.is_elevated,
            "requires_confirmation": self.requires_confirmation,
            "remote_execution_mode": self.remote_execution_mode,
            "eligibility_confirmed": self.eligibility_confirmed,
            "gating_reason": self.gating_reason.value,
            "gating_reasons": list(self.gating_reasons),
            "annotation_id": self.annotation_id,
            "annotated_at": self.annotated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionTrustAnnotation":
        return cls(
            execution_id=data.get("execution_id"),
            risk_tier=ExecutionRiskTier.from_string(
                str(data.get("risk_tier", ExecutionRiskTier.UNKNOWN.value))
            ),
            trust_label=TrustLabel.from_string(
                str(data.get("trust_label", TrustLabel.UNKNOWN.value))
            ),
            is_remote=bool(data.get("is_remote", False)),
            is_elevated=bool(data.get("is_elevated", False)),
            requires_confirmation=bool(data.get("requires_confirmation", False)),
            remote_execution_mode=data.get("remote_execution_mode"),
            eligibility_confirmed=bool(data.get("eligibility_confirmed", False)),
            gating_reason=SafetyGatingReason.from_string(
                str(data.get("gating_reason", SafetyGatingReason.NONE.value))
            ),
            gating_reasons=list(data.get("gating_reasons") or []),
            annotation_id=str(data.get("annotation_id") or str(uuid.uuid4())),
            annotated_at=float(data.get("annotated_at", time.time())),
        )


@dataclass
class PermissionSafetySnapshot:
    """Canonical safety state snapshot for the current control-loop iteration.

    This is the primary artifact produced by this module.  It is embedded in
    response metadata so that projection, diagnostics, and policy layers can
    consume a consistent, authoritative view of permission and trust state.

    The runtime shell derives :class:`OperatorSafetySummary` from this
    snapshot — the summary is never an independent truth source.

    Attributes
    ----------
    snapshot_id:
        Unique identifier for this snapshot.
    snapshot_at:
        Wall-clock timestamp when the snapshot was produced.
    trace_id:
        Optional correlation trace ID.
    runtime_session_id:
        Optional runtime session ID.
    modality_permissions:
        Per-modality permission and trust records.
    active_sensitive_modalities:
        List of modality names that are currently active *and* sensitive.
    any_permission_denied:
        True if at least one modality has ``DENIED`` permission.
    any_permission_missing:
        True if at least one modality has ``DENIED`` or ``UNAVAILABLE``
        permission.
    execution_trust_annotation:
        Optional trust/safety annotation for the current execution action.
    overall_trust_label:
        Aggregate trust label derived from all active modalities and the
        execution annotation.
    safety_gating_reasons:
        Deduplicated list of all active safety gating reasons (excludes
        ``"none"``).
    is_gated:
        True if any safety gating reason (other than ``NONE``) is active.
    degradation_reasons:
        Safety-related degradation reasons (propagated from perception state
        or generated by this module).
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    snapshot_at: float = field(default_factory=time.time)
    trace_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    modality_permissions: List[ModalityPermissionRecord] = field(default_factory=list)
    active_sensitive_modalities: List[str] = field(default_factory=list)
    any_permission_denied: bool = False
    any_permission_missing: bool = False
    execution_trust_annotation: Optional[ExecutionTrustAnnotation] = None
    overall_trust_label: TrustLabel = TrustLabel.UNKNOWN
    safety_gating_reasons: List[str] = field(default_factory=list)
    is_gated: bool = False
    degradation_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "snapshot_at": self.snapshot_at,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "modality_permissions": [r.to_dict() for r in self.modality_permissions],
            "active_sensitive_modalities": list(self.active_sensitive_modalities),
            "any_permission_denied": self.any_permission_denied,
            "any_permission_missing": self.any_permission_missing,
            "execution_trust_annotation": (
                self.execution_trust_annotation.to_dict()
                if self.execution_trust_annotation is not None
                else None
            ),
            "overall_trust_label": self.overall_trust_label.value,
            "safety_gating_reasons": list(self.safety_gating_reasons),
            "is_gated": self.is_gated,
            "degradation_reasons": list(self.degradation_reasons),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PermissionSafetySnapshot":
        eta_raw = data.get("execution_trust_annotation")
        return cls(
            snapshot_id=str(data.get("snapshot_id") or str(uuid.uuid4())),
            snapshot_at=float(data.get("snapshot_at", time.time())),
            trace_id=data.get("trace_id"),
            runtime_session_id=data.get("runtime_session_id"),
            modality_permissions=[
                ModalityPermissionRecord.from_dict(r)
                for r in (data.get("modality_permissions") or [])
            ],
            active_sensitive_modalities=list(
                data.get("active_sensitive_modalities") or []
            ),
            any_permission_denied=bool(data.get("any_permission_denied", False)),
            any_permission_missing=bool(data.get("any_permission_missing", False)),
            execution_trust_annotation=(
                ExecutionTrustAnnotation.from_dict(eta_raw)
                if isinstance(eta_raw, dict)
                else None
            ),
            overall_trust_label=TrustLabel.from_string(
                str(data.get("overall_trust_label", TrustLabel.UNKNOWN.value))
            ),
            safety_gating_reasons=list(data.get("safety_gating_reasons") or []),
            is_gated=bool(data.get("is_gated", False)),
            degradation_reasons=list(data.get("degradation_reasons") or []),
        )


@dataclass
class OperatorSafetySummary:
    """Shell-facing safety/trust summary derived from a canonical snapshot.

    This is **not** a truth source.  It is a presentation helper that the
    runtime shell renders to operators.  It must always be derived from a
    :class:`PermissionSafetySnapshot` and must never carry state that
    diverges from the canonical snapshot.

    Attributes
    ----------
    overall_trust_label:
        Aggregate trust label (mirrors the snapshot).
    active_sensitive_modalities:
        Human-readable list of currently active sensitive modalities.
    any_permission_missing:
        True if any required permission is absent or denied.
    is_gated:
        True if any safety gating is active.
    primary_gating_reason:
        The most prominent gating reason for operator display.
    remote_execution_pending:
        True if a remote/elevated execution action is annotated and
        awaiting confirmation.
    operator_message:
        Single-line human-readable summary sentence for display.
    derived_from_snapshot_id:
        ID of the :class:`PermissionSafetySnapshot` this was derived from.
    derived_at:
        Wall-clock timestamp when this summary was produced.
    """

    overall_trust_label: TrustLabel = TrustLabel.UNKNOWN
    active_sensitive_modalities: List[str] = field(default_factory=list)
    any_permission_missing: bool = False
    is_gated: bool = False
    primary_gating_reason: str = SafetyGatingReason.NONE.value
    remote_execution_pending: bool = False
    operator_message: str = ""
    derived_from_snapshot_id: Optional[str] = None
    derived_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_trust_label": self.overall_trust_label.value,
            "active_sensitive_modalities": list(self.active_sensitive_modalities),
            "any_permission_missing": self.any_permission_missing,
            "is_gated": self.is_gated,
            "primary_gating_reason": self.primary_gating_reason,
            "remote_execution_pending": self.remote_execution_pending,
            "operator_message": self.operator_message,
            "derived_from_snapshot_id": self.derived_from_snapshot_id,
            "derived_at": self.derived_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OperatorSafetySummary":
        return cls(
            overall_trust_label=TrustLabel.from_string(
                str(data.get("overall_trust_label", TrustLabel.UNKNOWN.value))
            ),
            active_sensitive_modalities=list(
                data.get("active_sensitive_modalities") or []
            ),
            any_permission_missing=bool(data.get("any_permission_missing", False)),
            is_gated=bool(data.get("is_gated", False)),
            primary_gating_reason=str(
                data.get("primary_gating_reason", SafetyGatingReason.NONE.value)
            ),
            remote_execution_pending=bool(data.get("remote_execution_pending", False)),
            operator_message=str(data.get("operator_message", "")),
            derived_from_snapshot_id=data.get("derived_from_snapshot_id"),
            derived_at=float(data.get("derived_at", time.time())),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

#: Modality names considered sensitive — these require clear operator labelling
#: because they involve active capture of audio, visual, or screen content that
#: may contain private information.  Any modality in this set that is active and
#: has granted permission is assigned :attr:`TrustLabel.SENSITIVE`.
_SENSITIVE_MODALITIES: frozenset = frozenset(
    {"microphone", "audio", "camera", "video", "screen", "screen_capture"}
)

#: SourceHealthStatus values that indicate degradation (string comparison to
#: avoid a hard import dependency on perception_source_registry).
#: Must match ``SourceHealthStatus`` enum values in
#: ``core/multimodal/perception_source_registry.py``.
_DEGRADED_HEALTH_VALUES: frozenset = frozenset({"degraded"})
_UNAVAILABLE_HEALTH_VALUES: frozenset = frozenset({"unavailable"})


def _assess_modality_permission(
    modality: str,
    *,
    source_id: Optional[str] = None,
    health_status: str = "unknown",
    is_active: bool = False,
    is_primary: bool = False,
) -> ModalityPermissionRecord:
    """Assess permission and trust state for a single source/modality.

    Derives the permission status from the health state of the source
    (as reported by the shell-owned PerceptionSourceRegistry snapshot),
    then derives the trust label from permission and sensitivity.

    Parameters
    ----------
    modality:
        Canonical modality name (e.g. ``"microphone"``, ``"camera"``).
    source_id:
        Optional perception source ID.
    health_status:
        Raw health status string from the source registry snapshot.
    is_active:
        Whether the source is currently active.
    is_primary:
        Whether this is the primary source for its modality category.
    """
    is_sensitive = modality.lower() in _SENSITIVE_MODALITIES

    # Derive permission status from health
    if health_status in _UNAVAILABLE_HEALTH_VALUES:
        perm = PermissionStatus.UNAVAILABLE
        gating = SafetyGatingReason.PERMISSION_UNAVAILABLE
    elif health_status in _DEGRADED_HEALTH_VALUES:
        # Degraded sources can still have permission but signal is weak
        perm = PermissionStatus.GRANTED
        gating = SafetyGatingReason.SOURCE_DEGRADED
    elif health_status == "healthy":
        perm = PermissionStatus.GRANTED
        gating = SafetyGatingReason.NONE
    elif health_status == "denied":
        perm = PermissionStatus.DENIED
        gating = SafetyGatingReason.PERMISSION_DENIED
    else:
        perm = PermissionStatus.UNKNOWN
        gating = SafetyGatingReason.PERMISSION_UNKNOWN

    gating_reasons: List[str] = []
    if gating != SafetyGatingReason.NONE:
        gating_reasons.append(gating.value)

    # Derive trust label
    if perm in (PermissionStatus.DENIED, PermissionStatus.UNAVAILABLE):
        trust = TrustLabel.RESTRICTED
    elif perm == PermissionStatus.UNKNOWN:
        trust = TrustLabel.UNKNOWN
    elif is_sensitive and is_active:
        trust = TrustLabel.SENSITIVE
    else:
        trust = TrustLabel.TRUSTED

    return ModalityPermissionRecord(
        modality=modality,
        source_id=source_id,
        permission_status=perm,
        trust_label=trust,
        is_active=is_active,
        is_sensitive=is_sensitive,
        gating_reason=gating,
        gating_reasons=gating_reasons,
    )


def _assess_execution_trust(
    *,
    execution_plan: Optional[Dict[str, Any]] = None,
    multimodal_route: Optional[Dict[str, Any]] = None,
    degraded_operation_envelope: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> ExecutionTrustAnnotation:
    """Derive an :class:`ExecutionTrustAnnotation` from available control artifacts.

    Inspects the execution plan (PR-11), multimodal route decision, and
    optional degraded-operation envelope (PR-29) to determine whether the
    current execution involves remote or elevated-risk operations.
    """
    annotation = ExecutionTrustAnnotation(execution_id=trace_id)

    # Detect remote execution from the execution plan
    is_remote = False
    is_elevated = False
    remote_execution_mode: Optional[str] = None
    gating_reasons: List[str] = []

    if isinstance(execution_plan, dict):
        steps = execution_plan.get("steps") or []
        for step in steps:
            step_type = str(step.get("step_type", "")).upper()
            if step_type in ("REMOTE_COMMAND", "REMOTE_AGENT"):
                is_remote = True
                is_elevated = True
            elif step_type == "ORCHESTRATION":
                is_remote = True

        # Remote execution mode from envelope or plan metadata
        remote_execution_mode = execution_plan.get("remote_execution_mode")

    if isinstance(multimodal_route, dict):
        # Degraded routes elevate risk slightly
        route_type = str(multimodal_route.get("route_type", ""))
        if "fallback" in route_type.lower():
            is_elevated = True

    if isinstance(degraded_operation_envelope, dict):
        severity = str(
            degraded_operation_envelope.get("operator_severity", "")
        ).lower()
        if severity in ("critical", "high"):
            is_elevated = True
            gating_reasons.append(SafetyGatingReason.ELEVATED_RISK_UNREVIEWED.value)

    # Derive risk tier
    if is_remote and is_elevated:
        risk_tier = ExecutionRiskTier.REMOTE_ELEVATED
    elif is_remote:
        risk_tier = ExecutionRiskTier.REMOTE_STANDARD
    elif is_elevated:
        risk_tier = ExecutionRiskTier.LOCAL_ELEVATED
    else:
        risk_tier = ExecutionRiskTier.LOCAL_SAFE

    # Derive trust label
    if is_elevated:
        trust = TrustLabel.ELEVATED
    elif is_remote:
        trust = TrustLabel.ELEVATED
    else:
        trust = TrustLabel.TRUSTED

    primary_gating = (
        SafetyGatingReason.from_string(gating_reasons[0])
        if gating_reasons
        else SafetyGatingReason.NONE
    )

    requires_confirmation = is_elevated and is_remote

    annotation.risk_tier = risk_tier
    annotation.trust_label = trust
    annotation.is_remote = is_remote
    annotation.is_elevated = is_elevated
    annotation.requires_confirmation = requires_confirmation
    annotation.remote_execution_mode = remote_execution_mode
    annotation.eligibility_confirmed = not requires_confirmation
    annotation.gating_reason = primary_gating
    annotation.gating_reasons = gating_reasons
    return annotation


def _derive_overall_trust_label(
    modality_records: List[ModalityPermissionRecord],
    execution_annotation: Optional[ExecutionTrustAnnotation],
) -> TrustLabel:
    """Compute an aggregate trust label from all modality records and execution
    annotation.  Follows worst-case semantics (most restrictive wins)."""
    labels: List[TrustLabel] = [r.trust_label for r in modality_records]
    if execution_annotation is not None:
        labels.append(execution_annotation.trust_label)

    # Priority order: RESTRICTED > SENSITIVE > ELEVATED > UNKNOWN > TRUSTED
    priority: Dict[TrustLabel, int] = {
        TrustLabel.RESTRICTED: 5,
        TrustLabel.SENSITIVE: 4,
        TrustLabel.ELEVATED: 3,
        TrustLabel.UNKNOWN: 2,
        TrustLabel.TRUSTED: 1,
    }
    if not labels:
        return TrustLabel.UNKNOWN
    return max(labels, key=lambda lbl: priority.get(lbl, 0))


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def build_permission_safety_snapshot(
    *,
    source_registry_snapshot: Optional[Dict[str, Any]] = None,
    multimodal_route: Optional[Dict[str, Any]] = None,
    execution_plan: Optional[Dict[str, Any]] = None,
    degraded_operation_envelope: Optional[Dict[str, Any]] = None,
    canonical_perception: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
) -> PermissionSafetySnapshot:
    """Build the canonical :class:`PermissionSafetySnapshot` for this iteration.

    Aggregates permission/trust state from:
    - Shell-owned source registry snapshot (source health → permission status)
    - Current multimodal route decision (routing degradation → elevated risk)
    - Execution plan (remote steps → execution risk tier)
    - Degraded-operation envelope (severity → safety gating)
    - Canonical perception state (active modalities / degradation reasons)

    This function is the single integration point for PR-32.  It never raises;
    on any internal error it returns a minimal snapshot with ``overall_trust_label``
    set to :attr:`TrustLabel.UNKNOWN`.

    Parameters
    ----------
    source_registry_snapshot:
        Dict produced by
        :meth:`~core.desktop_presence_runtime.DesktopPresenceRuntime.snapshot_source_registry`.
    multimodal_route:
        Dict produced by :meth:`~core.openclawd.OpenClawd._select_multimodal_route`.
    execution_plan:
        Dict produced by :meth:`~core.openclawd.OpenClawd._build_execution_plan`.
    degraded_operation_envelope:
        Dict produced by :meth:`~core.openclawd.OpenClawd._build_degraded_operation_envelope`.
    canonical_perception:
        Dict produced by :meth:`~core.openclawd.OpenClawd._build_canonical_perception_state`.
    trace_id:
        Optional correlation trace ID.
    runtime_session_id:
        Optional runtime session ID.

    Returns
    -------
    PermissionSafetySnapshot
        Fully populated canonical safety snapshot.
    """
    snap = PermissionSafetySnapshot(
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
    )

    try:
        modality_records: List[ModalityPermissionRecord] = []

        # Build per-source modality permission records from the source registry
        if isinstance(source_registry_snapshot, dict):
            sources: List[Dict[str, Any]] = list(
                source_registry_snapshot.get("sources") or []
            )
            for src in sources:
                modality_name = str(
                    src.get("modality") or src.get("source_type") or "unknown"
                ).lower()
                health = str(src.get("health", "unknown")).lower()
                is_active = bool(src.get("is_active", False))
                source_id = src.get("source_id") or src.get("id")
                record = _assess_modality_permission(
                    modality=modality_name,
                    source_id=source_id,
                    health_status=health,
                    is_active=is_active,
                )
                modality_records.append(record)

        # Supplement with active modalities from canonical perception if not
        # already covered by source registry records.
        if isinstance(canonical_perception, dict):
            active_mods: List[str] = list(
                canonical_perception.get("active_modalities") or []
            )
            covered = {r.modality for r in modality_records}
            for mod in active_mods:
                mod_lower = mod.lower()
                if mod_lower not in covered:
                    record = _assess_modality_permission(
                        modality=mod_lower,
                        health_status="healthy",
                        is_active=True,
                    )
                    modality_records.append(record)

            # Propagate perception degradation reasons
            snap.degradation_reasons = list(
                canonical_perception.get("degradation_reasons") or []
            )

        snap.modality_permissions = modality_records

        # Active sensitive modalities
        snap.active_sensitive_modalities = [
            r.modality
            for r in modality_records
            if r.is_sensitive and r.is_active
        ]

        # Aggregate permission flags
        snap.any_permission_denied = any(
            r.permission_status == PermissionStatus.DENIED for r in modality_records
        )
        snap.any_permission_missing = any(
            r.permission_status
            in (PermissionStatus.DENIED, PermissionStatus.UNAVAILABLE)
            for r in modality_records
        )

        # Build execution trust annotation
        eta = _assess_execution_trust(
            execution_plan=execution_plan,
            multimodal_route=multimodal_route,
            degraded_operation_envelope=degraded_operation_envelope,
            trace_id=trace_id,
        )
        snap.execution_trust_annotation = eta

        # Derive overall trust label (worst-case)
        snap.overall_trust_label = _derive_overall_trust_label(modality_records, eta)

        # Collect all gating reasons
        all_gating: List[str] = []
        for r in modality_records:
            for gr in r.gating_reasons:
                if gr and gr != SafetyGatingReason.NONE.value:
                    all_gating.append(gr)
        for gr in eta.gating_reasons:
            if gr and gr != SafetyGatingReason.NONE.value:
                all_gating.append(gr)

        # Deduplicate preserving insertion order
        seen_gating: set = set()
        deduped_gating: List[str] = []
        for gr in all_gating:
            if gr not in seen_gating:
                seen_gating.add(gr)
                deduped_gating.append(gr)
        snap.safety_gating_reasons = deduped_gating
        snap.is_gated = bool(deduped_gating)

    except Exception as _exc:
        logger.debug("build_permission_safety_snapshot internal error (swallowed): %s", _exc)
        snap.overall_trust_label = TrustLabel.UNKNOWN

    return snap


def build_operator_safety_summary(
    snapshot: PermissionSafetySnapshot,
) -> OperatorSafetySummary:
    """Build a shell-facing :class:`OperatorSafetySummary` from a canonical snapshot.

    The summary is **derived** from the snapshot.  It never acts as an
    independent truth source.

    Parameters
    ----------
    snapshot:
        Canonical :class:`PermissionSafetySnapshot` produced by
        :func:`build_permission_safety_snapshot`.

    Returns
    -------
    OperatorSafetySummary
        Presentation-ready summary for the runtime shell.
    """
    primary_gating = (
        snapshot.safety_gating_reasons[0]
        if snapshot.safety_gating_reasons
        else SafetyGatingReason.NONE.value
    )

    remote_pending = (
        snapshot.execution_trust_annotation is not None
        and snapshot.execution_trust_annotation.is_remote
        and snapshot.execution_trust_annotation.requires_confirmation
    )

    # Compose operator message
    parts: List[str] = []
    if snapshot.active_sensitive_modalities:
        sens = ", ".join(snapshot.active_sensitive_modalities)
        parts.append(f"sensitive:{sens}")
    if snapshot.any_permission_missing:
        parts.append("permission:missing")
    if snapshot.is_gated:
        parts.append(f"gated:{primary_gating}")
    if remote_pending:
        parts.append("remote:pending-confirmation")
    trust_str = snapshot.overall_trust_label.value
    if parts:
        operator_message = f"trust={trust_str} [{' | '.join(parts)}]"
    else:
        operator_message = f"trust={trust_str}"

    return OperatorSafetySummary(
        overall_trust_label=snapshot.overall_trust_label,
        active_sensitive_modalities=list(snapshot.active_sensitive_modalities),
        any_permission_missing=snapshot.any_permission_missing,
        is_gated=snapshot.is_gated,
        primary_gating_reason=primary_gating,
        remote_execution_pending=remote_pending,
        operator_message=operator_message,
        derived_from_snapshot_id=snapshot.snapshot_id,
    )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_permission_safety_state_instance: Optional["PermissionSafetyState"] = None


class PermissionSafetyState:
    """Runtime permission/safety state coordinator (singleton).

    Holds the most recently produced :class:`PermissionSafetySnapshot` so
    that downstream consumers (diagnostics, projection) can access it without
    re-building it.  The snapshot is replaced atomically on each control-loop
    iteration.

    This object is thread-safe for single-writer / multiple-reader access via
    simple attribute replacement (CPython GIL; each write is a single reference
    assignment).
    """

    def __init__(self) -> None:
        self._snapshot: Optional[PermissionSafetySnapshot] = None

    @property
    def latest_snapshot(self) -> Optional[PermissionSafetySnapshot]:
        """The most recently committed :class:`PermissionSafetySnapshot`."""
        return self._snapshot

    def commit(self, snapshot: PermissionSafetySnapshot) -> None:
        """Replace the current snapshot with *snapshot*."""
        self._snapshot = snapshot

    def snapshot_dict(self) -> Optional[Dict[str, Any]]:
        """Return the current snapshot as a plain dict, or ``None``."""
        snap = self._snapshot
        return snap.to_dict() if snap is not None else None


def get_permission_safety_state() -> PermissionSafetyState:
    """Return the process-wide :class:`PermissionSafetyState` singleton."""
    global _permission_safety_state_instance
    if _permission_safety_state_instance is None:
        _permission_safety_state_instance = PermissionSafetyState()
    return _permission_safety_state_instance


def reset_permission_safety_state() -> None:
    """Discard the current singleton (primarily for testing)."""
    global _permission_safety_state_instance
    _permission_safety_state_instance = None
