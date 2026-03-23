"""tests/test_pr46_production_baseline_promotion.py
=====================================================
PR-36 (GitHub) — Promote unified canonical control loop to production baseline.

Note: This test file is numbered ``test_pr46`` to avoid conflict with the
existing ``test_pr36_cross_runtime_result_merge.py`` which uses the internal
sequential numbering scheme for a different contract.  The architectural work
described here corresponds to GitHub PR-36.

Tests that the unified canonical control loop is the repository's production
baseline, that projection surfaces consume canonical artifacts rather than
inventing separate truth, that legacy paths are explicitly secondary or
derived-only, and that authority boundaries remain intact.

Coverage (6 acceptance criteria):
  1.  Projection surfaces consume canonical artifacts rather than inventing
      separate truth.
  2.  Legacy summary/bridge paths are clearly derived-only or removed where
      replaced.
  3.  Canonical degraded-operation, override, and explainability artifacts
      remain available to downstream consumers.
  4.  Shell/core authority boundaries remain intact under the new mainline path.
  5.  Contributor-facing/documented architecture matches actual runtime flow.
  6.  Production-baseline path remains stable under representative
      control-loop scenarios.

Module under test: core.production_baseline
Related modules:   core.openclawd, core.desktop_presence_runtime,
                   core.orchestration_authority.legacy_paths
"""

from __future__ import annotations

import pytest
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_canonical_metadata(
    *,
    perception: bool = True,
    model_supply: bool = True,
    control_plan: bool = True,
    degraded: bool = True,
    latency: bool = True,
    permission: bool = True,
    override: bool = True,
    timeline: bool = True,
    desktop_projection: bool = False,
    routing_event: bool = True,
) -> Dict[str, Any]:
    """Build a representative metadata dict with requested canonical artifacts."""
    meta: Dict[str, Any] = {}
    if perception:
        meta["canonical_perception_state"] = {
            "has_multimodal_input": False,
            "active_modalities": [],
            "requires_native_multimodal": False,
        }
    if model_supply:
        meta["canonical_model_supply_state"] = {
            "provider_count": 1,
            "primary_provider": "openai",
            "native_multimodal_providers": [],
        }
    if control_plan:
        meta["unified_control_plan"] = {
            "decision_authority": "subject_decision_authority",
            "chosen_model": "gpt-4o",
            "chosen_provider": "openai",
        }
    if degraded:
        meta["degraded_operation_envelope"] = {
            "overall_severity": "none",
            "failover_chain": [],
        }
    if latency:
        meta["latency_budget_summary"] = {
            "text_only_fast_path": True,
        }
    if permission:
        meta["permission_safety_state"] = {
            "modality_permissions": [],
        }
    if override:
        meta["operator_override_state"] = {
            "active_overrides": [],
        }
    if timeline:
        meta["decision_timeline_snapshot"] = {
            "events": [],
            "snapshot_id": "snap_test",
        }
    if desktop_projection:
        meta["desktop_status_projection"] = {
            "perception": {},
            "model_routing": {},
        }
    if routing_event:
        meta["routing_decision_event"] = {
            "route_kind": "text_only",
        }
    return meta


# ---------------------------------------------------------------------------
# 1. Production baseline module imports
# ---------------------------------------------------------------------------


class TestProductionBaselineModule:
    """Validate that the production_baseline module is importable and complete."""

    def test_module_importable(self):
        from core.production_baseline import build_production_baseline_summary

        assert callable(build_production_baseline_summary)

    def test_production_baseline_version(self):
        from core.production_baseline import PRODUCTION_BASELINE_VERSION

        assert PRODUCTION_BASELINE_VERSION == "1.0.0"

    def test_production_baseline_pr(self):
        from core.production_baseline import PRODUCTION_BASELINE_PR

        assert PRODUCTION_BASELINE_PR == "PR-36"

    def test_baseline_role_enum_values(self):
        from core.production_baseline import BaselineRole

        assert BaselineRole.CANONICAL_PRIMARY.value == "canonical_primary"
        assert BaselineRole.DERIVED_ONLY.value == "derived_only"
        assert BaselineRole.LEGACY_SECONDARY.value == "legacy_secondary"
        assert BaselineRole.TRANSITIONAL.value == "transitional"

    def test_canonical_artifact_enum_values(self):
        from core.production_baseline import CanonicalArtifact

        assert CanonicalArtifact.PERCEPTION_STATE.value == "canonical_perception_state"
        assert CanonicalArtifact.UNIFIED_CONTROL_PLAN.value == "unified_control_plan"
        assert CanonicalArtifact.DEGRADED_OPERATION_ENVELOPE.value == "degraded_operation_envelope"
        assert CanonicalArtifact.PERMISSION_SAFETY_STATE.value == "permission_safety_state"
        assert CanonicalArtifact.OPERATOR_OVERRIDE_STATE.value == "operator_override_state"
        assert CanonicalArtifact.DECISION_TIMELINE_SNAPSHOT.value == "decision_timeline_snapshot"

    def test_artifact_registration_stable_fields(self):
        from core.production_baseline import ArtifactRegistration, BaselineRole, CanonicalArtifact

        reg = ArtifactRegistration(
            artifact=CanonicalArtifact.UNIFIED_CONTROL_PLAN,
            role=BaselineRole.CANONICAL_PRIMARY,
            authority_owner="openclawd",
            response_metadata_key="unified_control_plan",
            pr_introduced="PR-19",
            description="test",
        )
        d = reg.to_dict()
        assert d["artifact"] == "unified_control_plan"
        assert d["role"] == "canonical_primary"
        assert d["authority_owner"] == "openclawd"
        assert d["pr_introduced"] == "PR-19"

    def test_legacy_path_declaration_stable_fields(self):
        from core.production_baseline import LegacyPathDeclaration, BaselineRole

        decl = LegacyPathDeclaration(
            metadata_key="multimodal_context",
            role=BaselineRole.LEGACY_SECONDARY,
            replacement="canonical_perception_state",
            pr_demoted="PR-24",
            notes="test note",
        )
        d = decl.to_dict()
        assert d["metadata_key"] == "multimodal_context"
        assert d["role"] == "legacy_secondary"
        assert d["replacement"] == "canonical_perception_state"
        assert d["pr_demoted"] == "PR-24"


# ---------------------------------------------------------------------------
# 2. Production baseline registry
# ---------------------------------------------------------------------------


class TestProductionBaselineRegistry:
    """Validate the ProductionBaselineRegistry singleton and its contents."""

    def setup_method(self):
        from core.production_baseline import reset_production_baseline_registry
        reset_production_baseline_registry()

    def teardown_method(self):
        from core.production_baseline import reset_production_baseline_registry
        reset_production_baseline_registry()

    def test_registry_singleton(self):
        from core.production_baseline import get_production_baseline_registry

        r1 = get_production_baseline_registry()
        r2 = get_production_baseline_registry()
        assert r1 is r2

    def test_registry_has_canonical_primary_artifacts(self):
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        assert len(reg.canonical_primary_artifacts) >= 8

    def test_registry_has_derived_only_artifacts(self):
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        assert len(reg.derived_only_artifacts) >= 2

    def test_registry_openclawd_owns_core_artifacts(self):
        """Subject core (OpenClawd) must own all control/routing artifacts."""
        from core.production_baseline import get_production_baseline_registry, CanonicalArtifact

        reg = get_production_baseline_registry()
        core_artifacts = {
            CanonicalArtifact.UNIFIED_CONTROL_PLAN,
            CanonicalArtifact.DEGRADED_OPERATION_ENVELOPE,
            CanonicalArtifact.PERMISSION_SAFETY_STATE,
            CanonicalArtifact.OPERATOR_OVERRIDE_STATE,
            CanonicalArtifact.DECISION_TIMELINE_SNAPSHOT,
            CanonicalArtifact.PERCEPTION_STATE,
            CanonicalArtifact.MODEL_SUPPLY_STATE,
        }
        openclawd_keys = {a.artifact for a in reg.openclawd_owned_artifacts}
        missing = core_artifacts - openclawd_keys
        assert missing == set(), f"OpenClawd should own {missing}"

    def test_registry_shell_owns_source_registry_artifacts(self):
        """Runtime shell (DesktopPresenceRuntime) must own source-registry artifacts."""
        from core.production_baseline import get_production_baseline_registry, CanonicalArtifact

        reg = get_production_baseline_registry()
        shell_keys = {a.artifact for a in reg.shell_owned_artifacts}
        assert CanonicalArtifact.DESKTOP_STATUS_PROJECTION in shell_keys

    def test_registry_desktop_projection_is_derived_only(self):
        """desktop_status_projection must be DERIVED_ONLY, not CANONICAL_PRIMARY."""
        from core.production_baseline import get_production_baseline_registry, BaselineRole

        reg = get_production_baseline_registry()
        role = reg.get_artifact_role("desktop_status_projection")
        assert role == BaselineRole.DERIVED_ONLY

    def test_registry_routing_event_is_derived_only(self):
        """routing_decision_event must be DERIVED_ONLY."""
        from core.production_baseline import get_production_baseline_registry, BaselineRole

        reg = get_production_baseline_registry()
        role = reg.get_artifact_role("routing_decision_event")
        assert role == BaselineRole.DERIVED_ONLY

    def test_registry_unified_control_plan_is_canonical_primary(self):
        from core.production_baseline import get_production_baseline_registry, BaselineRole

        reg = get_production_baseline_registry()
        assert reg.is_canonical_primary("unified_control_plan")

    def test_registry_multimodal_context_is_legacy(self):
        """multimodal_context must be explicitly marked as LEGACY_SECONDARY."""
        from core.production_baseline import get_production_baseline_registry, BaselineRole

        reg = get_production_baseline_registry()
        role = reg.get_artifact_role("multimodal_context")
        assert role == BaselineRole.LEGACY_SECONDARY

    def test_registry_multimodal_route_decision_is_legacy(self):
        """top-level multimodal_route_decision must be LEGACY_SECONDARY."""
        from core.production_baseline import get_production_baseline_registry, BaselineRole

        reg = get_production_baseline_registry()
        role = reg.get_artifact_role("multimodal_route_decision")
        assert role == BaselineRole.LEGACY_SECONDARY

    def test_registry_to_dict_stable(self):
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        d = reg.to_dict()
        assert d["production_baseline_version"] == "1.0.0"
        assert d["production_baseline_pr"] == "PR-36"
        assert d["canonical_primary_count"] >= 8
        assert d["derived_only_count"] >= 2
        assert d["legacy_secondary_count"] >= 2

    def test_reset_creates_new_instance(self):
        from core.production_baseline import (
            get_production_baseline_registry,
            reset_production_baseline_registry,
        )

        r1 = get_production_baseline_registry()
        reset_production_baseline_registry()
        r2 = get_production_baseline_registry()
        assert r1 is not r2


# ---------------------------------------------------------------------------
# 3. Canonical artifact coverage checks
# ---------------------------------------------------------------------------


class TestCanonicalArtifactCoverage:
    """Validate canonical coverage checking logic."""

    def setup_method(self):
        from core.production_baseline import reset_production_baseline_registry
        reset_production_baseline_registry()

    def teardown_method(self):
        from core.production_baseline import reset_production_baseline_registry
        reset_production_baseline_registry()

    def test_full_coverage_when_all_present(self):
        from core.production_baseline import get_production_baseline_registry

        meta = _make_canonical_metadata()
        reg = get_production_baseline_registry()
        result = reg.check_canonical_coverage(meta)
        # All primary artifacts that we included should be covered
        assert result["coverage_ratio"] > 0.5
        assert isinstance(result["covered"], list)
        assert isinstance(result["missing"], list)

    def test_empty_metadata_yields_zero_coverage(self):
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        result = reg.check_canonical_coverage({})
        assert result["coverage_ratio"] == 0.0
        assert result["fully_covered"] is False
        assert len(result["missing"]) > 0

    def test_partial_coverage_ratio_between_0_and_1(self):
        from core.production_baseline import get_production_baseline_registry

        meta = _make_canonical_metadata(perception=True, model_supply=False, control_plan=False)
        reg = get_production_baseline_registry()
        result = reg.check_canonical_coverage(meta)
        assert 0.0 < result["coverage_ratio"] < 1.0

    def test_covered_keys_are_subset_of_canonical_primary(self):
        from core.production_baseline import get_production_baseline_registry, BaselineRole

        meta = _make_canonical_metadata()
        reg = get_production_baseline_registry()
        primary_keys = {a.response_metadata_key for a in reg.canonical_primary_artifacts}
        result = reg.check_canonical_coverage(meta)
        assert set(result["covered"]).issubset(primary_keys)

    def test_missing_keys_not_in_metadata(self):
        from core.production_baseline import get_production_baseline_registry

        meta = _make_canonical_metadata(perception=True, model_supply=False)
        reg = get_production_baseline_registry()
        result = reg.check_canonical_coverage(meta)
        assert "canonical_model_supply_state" in result["missing"]


# ---------------------------------------------------------------------------
# 4. Projection surface is downstream (not a truth source)
# ---------------------------------------------------------------------------


class TestProjectionIsDownstream:
    """Acceptance criterion 1: projection surfaces consume canonical artifacts."""

    def setup_method(self):
        from core.production_baseline import reset_production_baseline_registry
        reset_production_baseline_registry()

    def teardown_method(self):
        from core.production_baseline import reset_production_baseline_registry
        reset_production_baseline_registry()

    def test_projection_absent_passes(self):
        """No projection key — no violation."""
        from core.production_baseline import get_production_baseline_registry

        meta = _make_canonical_metadata(desktop_projection=False)
        reg = get_production_baseline_registry()
        assert reg.assert_projection_is_downstream(meta) is True

    def test_projection_present_with_control_plan_passes(self):
        """Projection present and control plan present — downstream relationship satisfied."""
        from core.production_baseline import get_production_baseline_registry

        meta = _make_canonical_metadata(desktop_projection=True, control_plan=True)
        reg = get_production_baseline_registry()
        assert reg.assert_projection_is_downstream(meta) is True

    def test_projection_without_control_plan_fails(self):
        """Projection present but control plan absent — projection has no upstream source."""
        from core.production_baseline import get_production_baseline_registry

        meta = _make_canonical_metadata(desktop_projection=True, control_plan=False)
        reg = get_production_baseline_registry()
        assert reg.assert_projection_is_downstream(meta) is False

    def test_projection_carrying_independent_perception_fails(self):
        """Projection must not carry its own canonical_perception_state."""
        from core.production_baseline import get_production_baseline_registry

        meta = _make_canonical_metadata(desktop_projection=True, control_plan=True)
        # Inject independent perception truth into projection
        meta["desktop_status_projection"]["canonical_perception_state"] = {"bogus": True}
        reg = get_production_baseline_registry()
        assert reg.assert_projection_is_downstream(meta) is False

    def test_projection_carrying_independent_supply_fails(self):
        """Projection must not carry its own canonical_model_supply_state."""
        from core.production_baseline import get_production_baseline_registry

        meta = _make_canonical_metadata(desktop_projection=True, control_plan=True)
        meta["desktop_status_projection"]["canonical_model_supply_state"] = {"bogus": True}
        reg = get_production_baseline_registry()
        assert reg.assert_projection_is_downstream(meta) is False

    def test_desktop_status_projection_is_derived_only_in_registry(self):
        """The registry must classify desktop_status_projection as DERIVED_ONLY."""
        from core.production_baseline import get_production_baseline_registry, BaselineRole

        reg = get_production_baseline_registry()
        assert reg.is_derived_only("desktop_status_projection")

    def test_routing_decision_event_is_derived_only_in_registry(self):
        """routing_decision_event (PR-41) must be DERIVED_ONLY."""
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        assert reg.is_derived_only("routing_decision_event")


# ---------------------------------------------------------------------------
# 5. Legacy paths are explicitly secondary
# ---------------------------------------------------------------------------


class TestLegacyPathsAreSecondary:
    """Acceptance criterion 2: legacy/bridge paths are clearly secondary or removed."""

    def test_multimodal_context_is_legacy_in_registry(self):
        """multimodal_context must be explicitly flagged as LEGACY_SECONDARY."""
        from core.production_baseline import get_production_baseline_registry, BaselineRole

        reg = get_production_baseline_registry()
        assert reg.is_legacy_secondary("multimodal_context")

    def test_multimodal_route_decision_toplevel_is_legacy_in_registry(self):
        """Top-level multimodal_route_decision must be LEGACY_SECONDARY."""
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        assert reg.is_legacy_secondary("multimodal_route_decision")

    def test_legacy_declarations_list_is_non_empty(self):
        from core.production_baseline import LEGACY_PATH_DECLARATIONS

        assert len(LEGACY_PATH_DECLARATIONS) >= 2

    def test_orchestration_authority_registry_includes_pr36_paths(self):
        """PR-36 legacy path entries must be registered in orchestration authority."""
        from core.orchestration_authority.legacy_paths import is_legacy_path

        assert is_legacy_path("response.metadata.multimodal_context")
        assert is_legacy_path("response.metadata.multimodal_route_decision")

    def test_orchestration_authority_pr36_entries_have_correct_pr(self):
        from core.orchestration_authority.legacy_paths import get_legacy_entry

        entry = get_legacy_entry("response.metadata.multimodal_context")
        assert entry is not None
        assert entry.pr_guardrail_added == "PR-36"

    def test_legacy_path_entries_reference_canonical_replacements(self):
        """Each legacy declaration must specify a canonical replacement."""
        from core.production_baseline import LEGACY_PATH_DECLARATIONS

        for decl in LEGACY_PATH_DECLARATIONS:
            assert decl.replacement, (
                f"Legacy declaration for {decl.metadata_key!r} must specify a replacement."
            )
            assert "canonical" in decl.replacement or "unified_control_plan" in decl.replacement


# ---------------------------------------------------------------------------
# 6. Canonical artifacts remain available to downstream consumers
# ---------------------------------------------------------------------------


class TestCanonicalArtifactsAvailable:
    """Acceptance criterion 3: canonical degraded-operation, override, and
    explainability artifacts remain available to downstream consumers."""

    def test_degraded_operation_is_canonical_primary(self):
        from core.production_baseline import get_production_baseline_registry, BaselineRole

        reg = get_production_baseline_registry()
        assert reg.is_canonical_primary("degraded_operation_envelope")

    def test_operator_override_is_canonical_primary(self):
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        assert reg.is_canonical_primary("operator_override_state")

    def test_decision_timeline_is_canonical_primary(self):
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        assert reg.is_canonical_primary("decision_timeline_snapshot")

    def test_permission_safety_is_canonical_primary(self):
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        assert reg.is_canonical_primary("permission_safety_state")

    def test_latency_budget_is_canonical_primary(self):
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        assert reg.is_canonical_primary("latency_budget_summary")

    def test_all_canonical_primary_artifacts_have_response_metadata_keys(self):
        """Every CANONICAL_PRIMARY artifact must specify a response metadata key."""
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        for art in reg.canonical_primary_artifacts:
            assert art.response_metadata_key, (
                f"Artifact {art.artifact.value!r} has no response_metadata_key."
            )

    def test_all_canonical_primary_artifacts_have_pr_reference(self):
        """Every CANONICAL_PRIMARY artifact must reference its introducing PR."""
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        for art in reg.canonical_primary_artifacts:
            assert art.pr_introduced.startswith("PR-"), (
                f"Artifact {art.artifact.value!r} pr_introduced={art.pr_introduced!r}."
            )

    def test_baseline_manifest_includes_degraded_operation(self):
        from core.production_baseline import PRODUCTION_BASELINE_ARTIFACTS, CanonicalArtifact

        artifacts = {a.artifact for a in PRODUCTION_BASELINE_ARTIFACTS}
        assert CanonicalArtifact.DEGRADED_OPERATION_ENVELOPE in artifacts

    def test_baseline_manifest_includes_operator_override(self):
        from core.production_baseline import PRODUCTION_BASELINE_ARTIFACTS, CanonicalArtifact

        artifacts = {a.artifact for a in PRODUCTION_BASELINE_ARTIFACTS}
        assert CanonicalArtifact.OPERATOR_OVERRIDE_STATE in artifacts

    def test_baseline_manifest_includes_decision_timeline(self):
        from core.production_baseline import PRODUCTION_BASELINE_ARTIFACTS, CanonicalArtifact

        artifacts = {a.artifact for a in PRODUCTION_BASELINE_ARTIFACTS}
        assert CanonicalArtifact.DECISION_TIMELINE_SNAPSHOT in artifacts


# ---------------------------------------------------------------------------
# 7. Authority boundaries remain intact
# ---------------------------------------------------------------------------


class TestAuthorityBoundaries:
    """Acceptance criterion 4: shell/core authority boundaries remain intact."""

    def test_openclawd_owns_control_artifacts(self):
        """Subject core must own all decision-critical canonical artifacts."""
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        core_keys = {a.response_metadata_key for a in reg.openclawd_owned_artifacts}
        required_core = {
            "canonical_perception_state",
            "canonical_model_supply_state",
            "unified_control_plan",
            "degraded_operation_envelope",
            "permission_safety_state",
            "operator_override_state",
            "decision_timeline_snapshot",
        }
        missing = required_core - core_keys
        assert missing == set(), f"OpenClawd must own {missing}"

    def test_shell_owns_projection_surface(self):
        """Runtime shell must own desktop_status_projection."""
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        shell_keys = {a.response_metadata_key for a in reg.shell_owned_artifacts}
        assert "desktop_status_projection" in shell_keys, (
            "desktop_status_projection must be owned by the runtime shell."
        )

    def test_no_artifact_owned_by_both_shell_and_core(self):
        """An artifact must not be claimed by both owners simultaneously."""
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        core_keys = {a.response_metadata_key for a in reg.openclawd_owned_artifacts}
        shell_keys = {a.response_metadata_key for a in reg.shell_owned_artifacts}
        overlap = core_keys & shell_keys
        assert overlap == set(), f"Artifacts claimed by both owners: {overlap}"

    def test_derived_only_surfaces_are_not_canonical_primary(self):
        """A derived-only surface must not also be declared canonical primary."""
        from core.production_baseline import get_production_baseline_registry, BaselineRole

        reg = get_production_baseline_registry()
        derived_keys = {a.response_metadata_key for a in reg.derived_only_artifacts}
        primary_keys = {a.response_metadata_key for a in reg.canonical_primary_artifacts}
        overlap = derived_keys & primary_keys
        assert overlap == set(), f"Artifacts marked both derived and primary: {overlap}"

    def test_openclawd_not_in_shell_owned(self):
        """OpenClawd must not appear in the shell-owned artifact list."""
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        shell_owners = {a.authority_owner for a in reg.shell_owned_artifacts}
        assert shell_owners <= {"desktop_presence_runtime"}, (
            f"Shell-owned artifacts must only be owned by 'desktop_presence_runtime'; "
            f"found owners: {shell_owners}"
        )

    def test_architecture_truth_guards_compatible(self):
        """architecture_truth_guards must be importable alongside production_baseline."""
        from core.architecture_truth_guards import (
            CanonicalTruthOwnershipGuard,
            BoundaryInvariantGuard,
            run_all_architecture_guards,
        )
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        # Both modules must co-exist without import errors.
        assert reg.is_canonical_primary("unified_control_plan")
        assert callable(run_all_architecture_guards)


# ---------------------------------------------------------------------------
# 8. Build production baseline summary
# ---------------------------------------------------------------------------


class TestBuildProductionBaselineSummary:
    """Acceptance criterion 5 & 6: documented architecture matches runtime flow;
    production-baseline path is stable."""

    def setup_method(self):
        from core.production_baseline import reset_production_baseline_registry
        reset_production_baseline_registry()

    def teardown_method(self):
        from core.production_baseline import reset_production_baseline_registry
        reset_production_baseline_registry()

    def test_summary_baseline_active_true(self):
        from core.production_baseline import build_production_baseline_summary

        summary = build_production_baseline_summary()
        assert summary["baseline_active"] is True

    def test_summary_has_version(self):
        from core.production_baseline import build_production_baseline_summary

        summary = build_production_baseline_summary()
        assert summary["production_baseline_version"] == "1.0.0"

    def test_summary_has_pr(self):
        from core.production_baseline import build_production_baseline_summary

        summary = build_production_baseline_summary()
        assert summary["production_baseline_pr"] == "PR-36"

    def test_summary_canonical_artifact_count_at_least_8(self):
        from core.production_baseline import build_production_baseline_summary

        summary = build_production_baseline_summary()
        assert summary["canonical_artifact_count"] >= 8

    def test_summary_with_metadata_includes_coverage(self):
        from core.production_baseline import build_production_baseline_summary

        meta = _make_canonical_metadata()
        summary = build_production_baseline_summary(response_metadata=meta)
        assert "coverage" in summary
        assert "coverage_ratio" in summary["coverage"]

    def test_summary_with_metadata_projection_downstream_key(self):
        from core.production_baseline import build_production_baseline_summary

        meta = _make_canonical_metadata()
        summary = build_production_baseline_summary(response_metadata=meta)
        assert "projection_downstream" in summary

    def test_summary_without_metadata_no_coverage_key(self):
        from core.production_baseline import build_production_baseline_summary

        summary = build_production_baseline_summary(response_metadata=None)
        assert "coverage" not in summary

    def test_summary_include_manifest(self):
        from core.production_baseline import build_production_baseline_summary

        summary = build_production_baseline_summary(include_manifest=True)
        assert "manifest" in summary
        assert "canonical_primary_artifacts" in summary["manifest"]

    def test_summary_full_metadata_projection_downstream_true(self):
        """With all canonical artifacts and a valid downstream projection, assertion passes."""
        from core.production_baseline import build_production_baseline_summary

        meta = _make_canonical_metadata(desktop_projection=True, control_plan=True)
        summary = build_production_baseline_summary(response_metadata=meta)
        assert summary["projection_downstream"] is True

    def test_summary_projection_without_control_plan_downstream_false(self):
        """Projection without control plan must yield projection_downstream=False."""
        from core.production_baseline import build_production_baseline_summary

        meta = _make_canonical_metadata(desktop_projection=True, control_plan=False)
        summary = build_production_baseline_summary(response_metadata=meta)
        assert summary["projection_downstream"] is False

    def test_summary_stable_return_type(self):
        from core.production_baseline import build_production_baseline_summary

        summary = build_production_baseline_summary()
        assert isinstance(summary, dict)
        # Required keys always present
        for key in ("baseline_active", "production_baseline_version",
                    "production_baseline_pr", "canonical_artifact_count"):
            assert key in summary, f"Key {key!r} missing from summary."

    def test_summary_derivation_count_fields(self):
        from core.production_baseline import build_production_baseline_summary

        summary = build_production_baseline_summary()
        assert summary.get("derived_surface_count", 0) >= 2
        assert summary.get("legacy_path_count", 0) >= 2


# ---------------------------------------------------------------------------
# 9. DesktopPresenceRuntime production_baseline_summary (shell-facing)
# ---------------------------------------------------------------------------


class TestDesktopPresenceRuntimeBaselineSummary:
    """Validate that the shell exposes a derived-only production baseline summary."""

    def _make_runtime(self):
        """Return a DesktopPresenceRuntime with minimal dependencies mocked."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        rt = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
        rt._active_sessions = {}
        rt._source_registry = None
        rt._ingest_bus = None
        return rt

    def test_runtime_has_production_baseline_summary_method(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        rt = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
        assert hasattr(rt, "production_baseline_summary")
        assert callable(rt.production_baseline_summary)

    def test_runtime_summary_baseline_active(self):
        rt = self._make_runtime()
        summary = rt.production_baseline_summary()
        assert summary.get("baseline_active") is True

    def test_runtime_summary_with_result_dict(self):
        rt = self._make_runtime()
        result = {
            "metadata": _make_canonical_metadata(),
        }
        summary = rt.production_baseline_summary(result=result)
        assert summary["baseline_active"] is True
        assert "coverage" in summary

    def test_runtime_summary_with_none_result(self):
        rt = self._make_runtime()
        summary = rt.production_baseline_summary(result=None)
        assert isinstance(summary, dict)
        assert summary.get("baseline_active") is True


# ---------------------------------------------------------------------------
# 10. OpenClawd _build_production_baseline_summary
# ---------------------------------------------------------------------------


class TestOpenClawdBaselineSummary:
    """Validate that OpenClawd exposes the production baseline summary builder."""

    def test_openclawd_has_baseline_summary_builder(self):
        from core.openclawd import OpenClawd

        oc = OpenClawd()
        assert hasattr(oc, "_build_production_baseline_summary")
        assert callable(oc._build_production_baseline_summary)

    def test_openclawd_baseline_summary_returns_dict(self):
        from core.openclawd import OpenClawd

        oc = OpenClawd()
        result = oc._build_production_baseline_summary()
        assert result is not None
        assert isinstance(result, dict)
        assert result.get("baseline_active") is True

    def test_openclawd_baseline_summary_with_metadata(self):
        from core.openclawd import OpenClawd

        oc = OpenClawd()
        meta = _make_canonical_metadata()
        result = oc._build_production_baseline_summary(response_metadata=meta)
        assert result is not None
        assert "coverage" in result

    def test_openclawd_baseline_summary_version(self):
        from core.openclawd import OpenClawd

        oc = OpenClawd()
        result = oc._build_production_baseline_summary()
        assert result is not None
        assert result["production_baseline_pr"] == "PR-36"


# ---------------------------------------------------------------------------
# 11. Production baseline stable under control-loop scenarios
# ---------------------------------------------------------------------------


class TestProductionBaselineStability:
    """Acceptance criterion 6: production-baseline path remains stable under
    representative control-loop scenarios."""

    def setup_method(self):
        from core.production_baseline import reset_production_baseline_registry
        reset_production_baseline_registry()

    def teardown_method(self):
        from core.production_baseline import reset_production_baseline_registry
        reset_production_baseline_registry()

    def test_text_only_scenario_baseline_stable(self):
        """Text-only scenario: baseline should be active with perception present."""
        from core.production_baseline import build_production_baseline_summary

        meta = _make_canonical_metadata(
            perception=True,
            model_supply=True,
            control_plan=True,
        )
        summary = build_production_baseline_summary(response_metadata=meta)
        assert summary["baseline_active"] is True
        assert summary["coverage"]["coverage_ratio"] > 0.0

    def test_degraded_scenario_baseline_stable(self):
        """Degraded-operation scenario: baseline active; degraded envelope covered."""
        from core.production_baseline import build_production_baseline_summary

        meta = _make_canonical_metadata(
            perception=True,
            model_supply=True,
            control_plan=True,
            degraded=True,
        )
        summary = build_production_baseline_summary(response_metadata=meta)
        assert summary["baseline_active"] is True
        assert "degraded_operation_envelope" in summary["coverage"]["covered"]

    def test_override_scenario_baseline_stable(self):
        """Operator override scenario: override state covered in baseline."""
        from core.production_baseline import build_production_baseline_summary

        meta = _make_canonical_metadata(
            perception=True,
            control_plan=True,
            override=True,
        )
        summary = build_production_baseline_summary(response_metadata=meta)
        assert summary["baseline_active"] is True
        assert "operator_override_state" in summary["coverage"]["covered"]

    def test_explainability_scenario_baseline_stable(self):
        """Explainability scenario: decision timeline covered in baseline."""
        from core.production_baseline import build_production_baseline_summary

        meta = _make_canonical_metadata(
            perception=True,
            control_plan=True,
            timeline=True,
        )
        summary = build_production_baseline_summary(response_metadata=meta)
        assert summary["baseline_active"] is True
        assert "decision_timeline_snapshot" in summary["coverage"]["covered"]

    def test_full_canonical_loop_coverage(self):
        """Full canonical control-loop: all primary artifacts should be covered."""
        from core.production_baseline import build_production_baseline_summary

        meta = _make_canonical_metadata(
            perception=True,
            model_supply=True,
            control_plan=True,
            degraded=True,
            latency=True,
            permission=True,
            override=True,
            timeline=True,
        )
        summary = build_production_baseline_summary(response_metadata=meta)
        assert summary["baseline_active"] is True
        # With all core artifacts present, coverage should be high
        assert summary["coverage"]["coverage_ratio"] >= 0.8

    def test_baseline_registry_survives_multiple_calls(self):
        """Registry singleton must be stable across multiple calls."""
        from core.production_baseline import get_production_baseline_registry

        reg1 = get_production_baseline_registry()
        count1 = len(reg1.canonical_primary_artifacts)

        reg2 = get_production_baseline_registry()
        count2 = len(reg2.canonical_primary_artifacts)

        assert count1 == count2
        assert reg1 is reg2

    def test_summary_deterministic(self):
        """Summary must return the same shape on repeated calls (no randomness)."""
        from core.production_baseline import build_production_baseline_summary

        meta = _make_canonical_metadata()
        s1 = build_production_baseline_summary(response_metadata=meta)
        s2 = build_production_baseline_summary(response_metadata=meta)
        assert s1["canonical_artifact_count"] == s2["canonical_artifact_count"]
        assert s1["coverage"]["coverage_ratio"] == s2["coverage"]["coverage_ratio"]

    def test_legacy_paths_do_not_inflate_canonical_count(self):
        """Legacy path declarations must not increase the canonical_artifact_count."""
        from core.production_baseline import build_production_baseline_summary

        s = build_production_baseline_summary()
        # legacy paths are tracked separately — canonical count unchanged
        assert s["legacy_path_count"] >= 2
        assert s["canonical_artifact_count"] >= 8
        # canonical count must not accidentally include legacy paths
        assert s["canonical_artifact_count"] < 20  # sanity upper bound


# ---------------------------------------------------------------------------
# 12. Documentation / architecture review
# ---------------------------------------------------------------------------


class TestArchitectureDocumentation:
    """Acceptance criterion 5: contributor-facing architecture matches runtime flow."""

    def test_production_baseline_module_docstring(self):
        """core.production_baseline must have a docstring describing PR-36."""
        import core.production_baseline as mod

        assert mod.__doc__ is not None
        assert "PR-36" in mod.__doc__
        assert "production baseline" in mod.__doc__.lower()

    def test_openclawd_docstring_mentions_subject_core(self):
        """core.openclawd module docstring must describe the subject-core role."""
        import core.openclawd as mod

        assert mod.__doc__ is not None
        doc_lower = mod.__doc__.lower()
        assert "subject core" in doc_lower or "openclawd" in doc_lower

    def test_desktop_presence_runtime_docstring_mentions_shell(self):
        """core.desktop_presence_runtime docstring must describe the shell role."""
        import core.desktop_presence_runtime as mod

        assert mod.__doc__ is not None
        assert "shell" in mod.__doc__.lower() or "runtime" in mod.__doc__.lower()

    def test_production_baseline_artifacts_list_non_empty(self):
        """PRODUCTION_BASELINE_ARTIFACTS list must exist and be non-empty."""
        from core.production_baseline import PRODUCTION_BASELINE_ARTIFACTS

        assert len(PRODUCTION_BASELINE_ARTIFACTS) >= 10

    def test_legacy_declarations_list_non_empty(self):
        """LEGACY_PATH_DECLARATIONS list must exist and be non-empty."""
        from core.production_baseline import LEGACY_PATH_DECLARATIONS

        assert len(LEGACY_PATH_DECLARATIONS) >= 2

    def test_artifact_descriptions_present(self):
        """Every CANONICAL_PRIMARY artifact must have a description."""
        from core.production_baseline import get_production_baseline_registry

        reg = get_production_baseline_registry()
        for art in reg.canonical_primary_artifacts:
            assert art.description, (
                f"Artifact {art.artifact.value!r} has no description."
            )
