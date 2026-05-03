"""core.production_baseline — Unified Canonical Control Loop: Production Baseline
==================================================================================

PR-36 — Promote unified canonical control loop to production baseline and retire
duplicate legacy truth paths.

**Architectural intent**
------------------------
This module is the architectural "seal" for the current transition: it
establishes the unified canonical control loop as the repository's primary
runtime path and makes authority boundaries explicit to all contributors.

The unified canonical control loop consists of these 12 artifact layers, in
dependency order::

     1. CanonicalPerceptionState          (PR-16)   — perception truth
     2. CanonicalModelSupplyState         (PR-18)   — model supply truth
     3. Native Multimodal Routing         (PR-20)   — route selection
     4. UnifiedControlPlan                (PR-19/21/24) — canonical control artifact
     5. DegradedOperationEnvelope         (PR-29)   — degraded-operation semantics
     6. ControlLoopLatencyBudget          (PR-30)   — latency budget
     7. PermissionSafetyState             (PR-32)   — permission/trust/safety
     8. OperatorOverrideState             (PR-33)   — operator overrides
     9. DecisionTimeline                  (PR-34)   — explainability traces
    10. DesktopStatusProjection           (PR-22)   — shell-facing projection (derived)
    11. RoutingObservability              (PR-41)   — routing observability (derived)
    12. SourceRecoveryPolicy              (PR-45)   — source recovery

Of the 12 layers, 9 are CANONICAL_PRIMARY (owned by OpenClawd or the runtime
shell as primary truth), 2 are DERIVED_ONLY (projection / observability), and
1 is CANONICAL_PRIMARY but shell-owned (source recovery).

**Authority boundaries (enforced)**
------------------------------------
- ``DesktopPresenceRuntime`` (runtime shell) owns: session lifecycle,
  ``runtime_session_id``, tri-state lifecycle, native multimodal ingress,
  shell-owned source registry, and shell-facing projection surfaces.
- ``OpenClawd`` (subject core) owns: all canonical artifact decisions —
  routing, model/provider selection, degraded-operation interpretation,
  override application, execution posture, and explainability.
- Projection / diagnostics / developer surfaces **must** consume canonical
  artifacts rather than recomputing or inventing separate truth.

**Production baseline declaration**
-------------------------------------
The unified canonical control loop is the repository's **production
baseline** as of PR-36.  Prior compatibility shims and bridge paths are
explicitly *secondary* or *derived-only*.  They may remain only when
necessary for backward compatibility, and must not be used as primary truth
sources.

**Roles**
---------
:attr:`BaselineRole.CANONICAL_PRIMARY`
    This artifact/path is the production-baseline primary truth source.
    All downstream consumers must read from it.

:attr:`BaselineRole.DERIVED_ONLY`
    This artifact/path is derived from canonical primary sources.
    It must never be used as an independent truth source.

:attr:`BaselineRole.LEGACY_SECONDARY`
    Retained for backward compatibility only.  Will be removed in a future
    sprint.  No new code should depend on this path.

:attr:`BaselineRole.TRANSITIONAL`
    Currently in transition toward canonical primary.  May still carry
    some legacy semantics.  Follow per-entry guidance.

**Main API**
------------
:func:`get_production_baseline_registry`
    Return the process-wide :class:`ProductionBaselineRegistry` singleton.

:func:`build_production_baseline_summary`
    Build a serialisable snapshot of the current production baseline status
    and all registered canonical artifacts.

:func:`reset_production_baseline_registry`
    Reset the singleton (test isolation only).

Usage::

    from core.production_baseline import (
        build_production_baseline_summary,
        get_production_baseline_registry,
        BaselineRole,
    )

    summary = build_production_baseline_summary(
        response_metadata=result.get("metadata") or {},
    )
    assert summary["baseline_active"] is True
    assert summary["canonical_artifact_count"] >= 9
"""

from __future__ import annotations

import dataclasses
import enum
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ProductionBaseline")

# ---------------------------------------------------------------------------
# Version stamp
# ---------------------------------------------------------------------------

#: Semantic version of the production baseline declaration.
PRODUCTION_BASELINE_VERSION: str = "1.0.0"

#: PR that formally promoted the unified control loop to production baseline.
PRODUCTION_BASELINE_PR: str = "PR-36"

# ---------------------------------------------------------------------------
# Role taxonomy
# ---------------------------------------------------------------------------


class BaselineRole(str, enum.Enum):
    """Describes the canonical-vs-legacy status of an artifact or code path."""

    CANONICAL_PRIMARY = "canonical_primary"
    """Production-baseline primary truth source.  All downstream consumers
    must read from this artifact."""

    DERIVED_ONLY = "derived_only"
    """Derived from canonical primary sources.  Must not be used as an
    independent truth source.  Reads from canonical; does not write truth."""

    LEGACY_SECONDARY = "legacy_secondary"
    """Retained for backward compatibility only.  No new consumers should
    depend on this path.  Scheduled for removal."""

    TRANSITIONAL = "transitional"
    """Currently migrating toward canonical primary.  Follow per-entry
    guidance for current consumers."""


# ---------------------------------------------------------------------------
# Canonical artifact taxonomy
# ---------------------------------------------------------------------------


class CanonicalArtifact(str, enum.Enum):
    """Enumeration of all canonical artifacts in the unified control loop."""

    PERCEPTION_STATE = "canonical_perception_state"
    """PR-16: CanonicalPerceptionState — primary perception truth."""

    MODEL_SUPPLY_STATE = "canonical_model_supply_state"
    """PR-18: CanonicalModelSupplyState — primary model supply truth."""

    MULTIMODAL_ROUTE = "multimodal_route_decision"
    """PR-20: Native multimodal-first routing decision — canonical route
    selection derived from perception state.  DEPRECATED-COMPAT key retained
    for backward compatibility; canonical value is inside unified_control_plan."""

    UNIFIED_CONTROL_PLAN = "unified_control_plan"
    """PR-19/21/24: UnifiedControlPlan — single canonical control artifact
    capturing perception truth, model supply truth, and execution decisions."""

    DEGRADED_OPERATION_ENVELOPE = "degraded_operation_envelope"
    """PR-29: DegradedOperationEnvelope — canonical degraded-operation
    semantics (provider failover chain, fallback ladder, severity)."""

    LATENCY_BUDGET_SUMMARY = "latency_budget_summary"
    """PR-30: ControlLoopLatencyBudget — canonical latency budget (ingest
    cadence, recompute throttling, projection refresh, fast-path)."""

    PERMISSION_SAFETY_STATE = "permission_safety_state"
    """PR-32: PermissionSafetySnapshot — canonical permission/trust/safety
    state (modality permissions, trust labels, safety gating, risk tier)."""

    OPERATOR_OVERRIDE_STATE = "operator_override_state"
    """PR-33: OperatorOverrideSnapshot — canonical operator override state
    (active source/model/execution-policy overrides)."""

    DECISION_TIMELINE_SNAPSHOT = "decision_timeline_snapshot"
    """PR-34: ExplainabilitySnapshot — canonical decision timeline and
    explainability traces (route selection, fallback transitions, operator
    override influence, trust/safety gating — correlated and replayable)."""

    DESKTOP_STATUS_PROJECTION = "desktop_status_projection"
    """PR-22: DesktopStatusProjection — derived shell-facing projection
    assembled from the unified control plan and shell-owned source registry.
    Role: DERIVED_ONLY — downstream-facing surface, not a truth source."""

    ROUTING_OBSERVABILITY = "routing_decision_event"
    """PR-41: RoutingDecisionEvent — structured routing observability event
    derived from the canonical routing decision.  Role: DERIVED_ONLY."""

    SOURCE_RECOVERY_SNAPSHOT = "source_recovery_snapshot"
    """PR-45: SourceRecoverySnapshot — canonical source recovery state
    (recoverability, freshness, recovery events, primary re-election)."""


# ---------------------------------------------------------------------------
# Artifact registration record
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ArtifactRegistration:
    """Metadata record for a single canonical artifact in the production baseline."""

    artifact: CanonicalArtifact
    """The canonical artifact enum value."""

    role: BaselineRole
    """Whether this is a canonical primary truth source, derived surface, etc."""

    authority_owner: str
    """Which architectural component owns/produces this artifact.
    Either ``"openclawd"`` (subject core) or ``"desktop_presence_runtime"``
    (runtime shell)."""

    response_metadata_key: str
    """The key under ``response["metadata"]`` where this artifact appears."""

    pr_introduced: str
    """PR that first introduced this artifact."""

    description: str = ""
    """Human-readable description of this artifact."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact": self.artifact.value,
            "role": self.role.value,
            "authority_owner": self.authority_owner,
            "response_metadata_key": self.response_metadata_key,
            "pr_introduced": self.pr_introduced,
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Legacy path registration record
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class LegacyPathDeclaration:
    """Records a legacy or bridge path that has been explicitly demoted."""

    metadata_key: str
    """The metadata key or code path being declared as legacy/secondary."""

    role: BaselineRole
    """Always LEGACY_SECONDARY or DERIVED_ONLY for entries here."""

    replacement: str
    """The canonical artifact that replaces or supersedes this path."""

    pr_demoted: str
    """PR that formally demoted this path."""

    notes: str = ""
    """Any additional guidance for consumers migrating away from this path."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata_key": self.metadata_key,
            "role": self.role.value,
            "replacement": self.replacement,
            "pr_demoted": self.pr_demoted,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Production baseline manifest
# ---------------------------------------------------------------------------

#: Ordered list of canonical artifact registrations (production baseline).
#: This list defines the authoritative ordering of the unified control loop.
PRODUCTION_BASELINE_ARTIFACTS: List[ArtifactRegistration] = [
    ArtifactRegistration(
        artifact=CanonicalArtifact.PERCEPTION_STATE,
        role=BaselineRole.CANONICAL_PRIMARY,
        authority_owner="openclawd",
        response_metadata_key="canonical_perception_state",
        pr_introduced="PR-16",
        description=(
            "Primary perception truth. Combines continuous host perception "
            "(runtime shell) and request-bound multimodal context fusion."
        ),
    ),
    ArtifactRegistration(
        artifact=CanonicalArtifact.MODEL_SUPPLY_STATE,
        role=BaselineRole.CANONICAL_PRIMARY,
        authority_owner="openclawd",
        response_metadata_key="canonical_model_supply_state",
        pr_introduced="PR-18",
        description=(
            "Primary model supply truth. Assembled from MultiLLMRouter "
            "provider inventory; carries native multimodal capability flags."
        ),
    ),
    ArtifactRegistration(
        artifact=CanonicalArtifact.UNIFIED_CONTROL_PLAN,
        role=BaselineRole.CANONICAL_PRIMARY,
        authority_owner="openclawd",
        response_metadata_key="unified_control_plan",
        pr_introduced="PR-19",
        description=(
            "Single canonical control artifact. Captures perception truth, "
            "model supply truth, route decision, execution decisions, fallback "
            "chain, and lifecycle target in one authoritative structure."
        ),
    ),
    ArtifactRegistration(
        artifact=CanonicalArtifact.DEGRADED_OPERATION_ENVELOPE,
        role=BaselineRole.CANONICAL_PRIMARY,
        authority_owner="openclawd",
        response_metadata_key="degraded_operation_envelope",
        pr_introduced="PR-29",
        description=(
            "Canonical degraded-operation semantics. Normalises provider "
            "failover chain, fallback policy ladder, and degradation severity "
            "into an explicit, replayable artifact."
        ),
    ),
    ArtifactRegistration(
        artifact=CanonicalArtifact.LATENCY_BUDGET_SUMMARY,
        role=BaselineRole.CANONICAL_PRIMARY,
        authority_owner="openclawd",
        response_metadata_key="latency_budget_summary",
        pr_introduced="PR-30",
        description=(
            "Canonical control-loop latency budget. Covers ingest cadence, "
            "recompute throttling, projection refresh budgeting, provider "
            "selection latency, and text-only fast-path detection."
        ),
    ),
    ArtifactRegistration(
        artifact=CanonicalArtifact.PERMISSION_SAFETY_STATE,
        role=BaselineRole.CANONICAL_PRIMARY,
        authority_owner="openclawd",
        response_metadata_key="permission_safety_state",
        pr_introduced="PR-32",
        description=(
            "Canonical permission/trust/safety snapshot. Aggregates source "
            "registry health → permission status, routing degradation → trust "
            "label, and execution plan → risk tier into one artifact."
        ),
    ),
    ArtifactRegistration(
        artifact=CanonicalArtifact.OPERATOR_OVERRIDE_STATE,
        role=BaselineRole.CANONICAL_PRIMARY,
        authority_owner="openclawd",
        response_metadata_key="operator_override_state",
        pr_introduced="PR-33",
        description=(
            "Canonical operator override snapshot. Captures active "
            "source/model/execution-policy overrides and their application "
            "timestamps; consumed by projection and diagnostics."
        ),
    ),
    ArtifactRegistration(
        artifact=CanonicalArtifact.DECISION_TIMELINE_SNAPSHOT,
        role=BaselineRole.CANONICAL_PRIMARY,
        authority_owner="openclawd",
        response_metadata_key="decision_timeline_snapshot",
        pr_introduced="PR-34",
        description=(
            "Canonical decision timeline / explainability snapshot. Captures "
            "route selection, fallback transitions, operator override influence, "
            "and trust/safety gating events — correlated and replayable."
        ),
    ),
    ArtifactRegistration(
        artifact=CanonicalArtifact.ROUTING_OBSERVABILITY,
        role=BaselineRole.DERIVED_ONLY,
        authority_owner="openclawd",
        response_metadata_key="routing_decision_event",
        pr_introduced="PR-41",
        description=(
            "Derived routing observability event. Emitted from the canonical "
            "routing decision; not an independent truth source. Consumed by "
            "metrics and log pipelines."
        ),
    ),
    ArtifactRegistration(
        artifact=CanonicalArtifact.DESKTOP_STATUS_PROJECTION,
        role=BaselineRole.DERIVED_ONLY,
        authority_owner="desktop_presence_runtime",
        response_metadata_key="desktop_status_projection",
        pr_introduced="PR-22",
        description=(
            "Derived shell-facing status projection. Assembled by the runtime "
            "shell from the unified control plan (core-owned) and the "
            "shell-owned source registry snapshot. Never an independent truth "
            "source; consumes canonical artifacts only."
        ),
    ),
    ArtifactRegistration(
        artifact=CanonicalArtifact.SOURCE_RECOVERY_SNAPSHOT,
        role=BaselineRole.CANONICAL_PRIMARY,
        authority_owner="desktop_presence_runtime",
        response_metadata_key="source_recovery_snapshot",
        pr_introduced="PR-45",
        description=(
            "Canonical source recovery state. Captures source recoverability, "
            "freshness, recovery events, and primary source re-election. "
            "Owned by the runtime shell (source registry is shell-owned)."
        ),
    ),
]

#: Explicitly declared legacy / deprecated paths that have been demoted.
LEGACY_PATH_DECLARATIONS: List[LegacyPathDeclaration] = [
    LegacyPathDeclaration(
        metadata_key="multimodal_context",
        role=BaselineRole.LEGACY_SECONDARY,
        replacement="canonical_perception_state",
        pr_demoted="PR-24",
        notes=(
            "Raw fused multimodal context from MultimodalBus.ingest(). "
            "New consumers must prefer canonical_perception_state (PR-16). "
            "Retained only for backward compatibility."
        ),
    ),
    LegacyPathDeclaration(
        metadata_key="multimodal_route_decision",
        role=BaselineRole.LEGACY_SECONDARY,
        replacement="unified_control_plan[multimodal_route_decision]",
        pr_demoted="PR-24",
        notes=(
            "Top-level routing decision dict. The canonical routing decision "
            "is now embedded inside unified_control_plan['multimodal_route_decision']. "
            "This top-level key is retained only for backward compatibility."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Production baseline registry (singleton)
# ---------------------------------------------------------------------------


class ProductionBaselineRegistry:
    """Registry that declares the unified canonical control loop as the
    production baseline and tracks the status of all canonical artifacts.

    This registry is a read-only reference document for downstream consumers
    and for tests that need to assert canonical-vs-derived artifact status.
    It does not affect execution logic.

    Thread-safe for read access (populated once at module load time).
    """

    def __init__(self) -> None:
        self._artifacts: List[ArtifactRegistration] = list(PRODUCTION_BASELINE_ARTIFACTS)
        self._legacy_paths: List[LegacyPathDeclaration] = list(LEGACY_PATH_DECLARATIONS)
        self._promoted_at: float = time.time()

    # ------------------------------------------------------------------
    # Artifact lookups
    # ------------------------------------------------------------------

    @property
    def canonical_primary_artifacts(self) -> List[ArtifactRegistration]:
        """Return all artifacts with role CANONICAL_PRIMARY."""
        return [a for a in self._artifacts if a.role == BaselineRole.CANONICAL_PRIMARY]

    @property
    def derived_only_artifacts(self) -> List[ArtifactRegistration]:
        """Return all artifacts with role DERIVED_ONLY."""
        return [a for a in self._artifacts if a.role == BaselineRole.DERIVED_ONLY]

    @property
    def openclawd_owned_artifacts(self) -> List[ArtifactRegistration]:
        """Return all artifacts owned by the subject core (OpenClawd)."""
        return [a for a in self._artifacts if a.authority_owner == "openclawd"]

    @property
    def shell_owned_artifacts(self) -> List[ArtifactRegistration]:
        """Return all artifacts owned by the runtime shell (DesktopPresenceRuntime)."""
        return [a for a in self._artifacts if a.authority_owner == "desktop_presence_runtime"]

    def get_artifact_role(self, metadata_key: str) -> Optional[BaselineRole]:
        """Return the :class:`BaselineRole` for *metadata_key*, or ``None``."""
        for a in self._artifacts:
            if a.response_metadata_key == metadata_key:
                return a.role
        for lp in self._legacy_paths:
            if lp.metadata_key == metadata_key:
                return lp.role
        return None

    def is_canonical_primary(self, metadata_key: str) -> bool:
        """Return True if *metadata_key* is a CANONICAL_PRIMARY artifact."""
        return self.get_artifact_role(metadata_key) == BaselineRole.CANONICAL_PRIMARY

    def is_derived_only(self, metadata_key: str) -> bool:
        """Return True if *metadata_key* is a DERIVED_ONLY surface."""
        return self.get_artifact_role(metadata_key) == BaselineRole.DERIVED_ONLY

    def is_legacy_secondary(self, metadata_key: str) -> bool:
        """Return True if *metadata_key* is a LEGACY_SECONDARY path."""
        return self.get_artifact_role(metadata_key) == BaselineRole.LEGACY_SECONDARY

    # ------------------------------------------------------------------
    # Canonical artifact availability check
    # ------------------------------------------------------------------

    def check_canonical_coverage(
        self,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Check which canonical primary artifacts are present in *metadata*.

        Parameters
        ----------
        metadata:
            The ``response["metadata"]`` dict produced by
            :meth:`~core.openclawd.OpenClawd.process`.

        Returns
        -------
        dict
            ``{
                "covered": [<artifact_key>, ...],   # present in metadata
                "missing": [<artifact_key>, ...],   # absent from metadata
                "coverage_ratio": float,            # 0.0 – 1.0
                "fully_covered": bool,
            }``
        """
        primary = [a.response_metadata_key for a in self.canonical_primary_artifacts]
        covered = [k for k in primary if metadata.get(k) is not None]
        missing = [k for k in primary if metadata.get(k) is None]
        ratio = len(covered) / len(primary) if primary else 1.0
        return {
            "covered": covered,
            "missing": missing,
            "coverage_ratio": round(ratio, 3),
            "fully_covered": len(missing) == 0,
        }

    # ------------------------------------------------------------------
    # Projection surface validation
    # ------------------------------------------------------------------

    def assert_projection_is_downstream(
        self,
        metadata: Dict[str, Any],
    ) -> bool:
        """Return True when the projection surface in *metadata* is consistent
        with being a *derived* consumer of canonical artifacts rather than an
        independent truth source.

        Checks that:
        1. ``desktop_status_projection`` (when present) does not carry its own
           ``canonical_perception_state`` or ``canonical_model_supply_state``
           keys at the top level (those belong in the canonical artifacts above).
        2. ``desktop_status_projection`` is present only when a
           ``unified_control_plan`` is also present (projection is downstream
           of the control plan).

        Returns True (assertion passes) or False (assertion fails).
        """
        dsp = metadata.get("desktop_status_projection")
        ucp = metadata.get("unified_control_plan")

        if dsp is None:
            # Projection absent — no violation.
            return True

        # Projection must not carry independent perception / supply truth.
        if isinstance(dsp, dict):
            if "canonical_perception_state" in dsp or "canonical_model_supply_state" in dsp:
                logger.warning(
                    "ProductionBaseline: desktop_status_projection carries "
                    "independent truth keys — projection is not purely downstream."
                )
                return False

        # Projection should only appear when the control plan is also present.
        if ucp is None:
            logger.warning(
                "ProductionBaseline: desktop_status_projection present but "
                "unified_control_plan absent — projection has no upstream source."
            )
            return False

        return True

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "production_baseline_version": PRODUCTION_BASELINE_VERSION,
            "production_baseline_pr": PRODUCTION_BASELINE_PR,
            "promoted_at": self._promoted_at,
            "canonical_primary_count": len(self.canonical_primary_artifacts),
            "derived_only_count": len(self.derived_only_artifacts),
            "legacy_secondary_count": len(self._legacy_paths),
            "canonical_primary_artifacts": [
                a.to_dict() for a in self.canonical_primary_artifacts
            ],
            "derived_only_artifacts": [a.to_dict() for a in self.derived_only_artifacts],
            "legacy_path_declarations": [
                lp.to_dict() for lp in self._legacy_paths
            ],
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_registry_instance: Optional[ProductionBaselineRegistry] = None


def get_production_baseline_registry() -> ProductionBaselineRegistry:
    """Return the process-wide :class:`ProductionBaselineRegistry` singleton."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = ProductionBaselineRegistry()
    return _registry_instance


def reset_production_baseline_registry() -> None:
    """Reset the singleton (test isolation only)."""
    global _registry_instance
    _registry_instance = None


# ---------------------------------------------------------------------------
# Summary builder
# ---------------------------------------------------------------------------


def build_production_baseline_summary(
    *,
    response_metadata: Optional[Dict[str, Any]] = None,
    include_manifest: bool = False,
) -> Dict[str, Any]:
    """Build a serialisable production baseline status summary.

    Intended to be embedded in response metadata by OpenClawd and read by
    projection / diagnostics surfaces to verify that the canonical control
    loop is active and complete.

    Parameters
    ----------
    response_metadata:
        The ``response["metadata"]`` dict from a recent OpenClawd.process()
        call.  When provided, canonical artifact coverage is assessed.
        When omitted, only static manifest information is returned.
    include_manifest:
        When True, include the full static manifest (artifact registrations
        and legacy path declarations) in the returned dict.  Defaults to
        False to keep the summary compact for normal response metadata.

    Returns
    -------
    dict
        Serialisable summary::

            {
                "baseline_active": True,
                "production_baseline_version": "1.0.0",
                "production_baseline_pr": "PR-36",
                "canonical_artifact_count": 9,       # CANONICAL_PRIMARY count
                "derived_surface_count": 2,
                "legacy_path_count": 2,
                "coverage": {                         # only when metadata provided
                    "covered": [...],
                    "missing": [...],
                    "coverage_ratio": 0.9,
                    "fully_covered": False,
                },
                "projection_downstream": True,        # only when metadata provided
                "manifest": {...},                    # only when include_manifest=True
            }
    """
    registry = get_production_baseline_registry()
    summary: Dict[str, Any] = {
        "baseline_active": True,
        "production_baseline_version": PRODUCTION_BASELINE_VERSION,
        "production_baseline_pr": PRODUCTION_BASELINE_PR,
        "canonical_artifact_count": len(registry.canonical_primary_artifacts),
        "derived_surface_count": len(registry.derived_only_artifacts),
        "legacy_path_count": len(registry._legacy_paths),
    }

    if response_metadata is not None:
        coverage = registry.check_canonical_coverage(response_metadata)
        summary["coverage"] = coverage
        summary["projection_downstream"] = registry.assert_projection_is_downstream(
            response_metadata
        )

    try:
        from core.perception.perception_fact_boundary import (
            build_perception_fact_boundary_summary,
        )

        summary["perception_boundary"] = build_perception_fact_boundary_summary(
            response_metadata
        )
    except Exception:
        summary["perception_boundary"] = {
            "canonical_fact_surface": "response.metadata.canonical_perception_state",
            "canonical_fact_present": bool(
                response_metadata and response_metadata.get("canonical_perception_state") is not None
            ),
        }

    if include_manifest:
        summary["manifest"] = registry.to_dict()

    return summary
