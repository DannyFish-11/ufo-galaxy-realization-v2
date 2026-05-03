"""PR-25: canonical perception fact-boundary tests."""

from __future__ import annotations


def _make_metadata(
    *,
    canonical: bool = True,
    compat: bool = False,
    include_ucp_summary: bool = False,
    include_projection: bool = False,
):
    meta = {}
    if canonical:
        meta["canonical_perception_state"] = {"perception_summary": "ok"}
    if compat:
        meta["multimodal_context"] = {"fusion_summary": "compat"}
    if include_ucp_summary:
        meta["unified_control_plan"] = {
            "canonical_perception_summary": {"perception_summary": "ok"}
        }
    if include_projection:
        meta["desktop_status_projection"] = {"surface": "desktop"}
    return meta


class TestPerceptionSurfaceCatalog:
    def test_canonical_surface_is_authoritative(self):
        from core.perception.perception_fact_boundary import (
            PerceptionSurfaceKind,
            classify_perception_surface,
        )

        record = classify_perception_surface(
            "response.metadata.canonical_perception_state"
        )
        assert record is not None
        assert record.kind == PerceptionSurfaceKind.CANONICAL_FACT
        assert record.authority_owner == "openclawd"

    def test_request_multimodal_context_is_input_only(self):
        from core.perception.perception_fact_boundary import (
            PerceptionSurfaceKind,
            classify_perception_surface,
        )

        record = classify_perception_surface("request.multimodal_context")
        assert record is not None
        assert record.kind == PerceptionSurfaceKind.REQUEST_INPUT
        assert record.replacement == "response.metadata.canonical_perception_state"

    def test_metadata_multimodal_context_is_compat_only(self):
        from core.perception.perception_fact_boundary import (
            PerceptionSurfaceKind,
            classify_perception_surface,
        )

        record = classify_perception_surface("response.metadata.multimodal_context")
        assert record is not None
        assert record.kind == PerceptionSurfaceKind.COMPAT_ONLY


class TestPerceptionFactBoundarySummary:
    def test_summary_prefers_canonical_surface(self):
        from core.perception.perception_fact_boundary import (
            PERCEPTION_FACT_BOUNDARY_IS_AUTHORITY,
            build_perception_fact_boundary_summary,
        )

        summary = build_perception_fact_boundary_summary(
            _make_metadata(canonical=True, compat=True)
        )

        assert summary["authority"] == PERCEPTION_FACT_BOUNDARY_IS_AUTHORITY
        assert summary["canonical_fact_surface"] == (
            "response.metadata.canonical_perception_state"
        )
        assert summary["canonical_fact_present"] is True
        assert summary["compat_surfaces_present"] == [
            "response.metadata.multimodal_context"
        ]

    def test_summary_tracks_derived_surfaces(self):
        from core.perception.perception_fact_boundary import (
            build_perception_fact_boundary_summary,
        )

        summary = build_perception_fact_boundary_summary(
            _make_metadata(
                canonical=True,
                include_ucp_summary=True,
                include_projection=True,
            )
        )

        assert "response.metadata.unified_control_plan.canonical_perception_summary" in (
            summary["derived_surfaces_present"]
        )
        assert "response.metadata.desktop_status_projection" in (
            summary["derived_surfaces_present"]
        )

    def test_summary_flags_compat_only_metadata_for_migration(self):
        from core.perception.perception_fact_boundary import (
            build_perception_fact_boundary_summary,
        )

        summary = build_perception_fact_boundary_summary(
            _make_metadata(canonical=False, compat=True)
        )

        assert summary["canonical_fact_present"] is False
        assert summary["requires_compat_migration"] is True


class TestProductionBaselineIntegration:
    def test_production_baseline_summary_embeds_perception_boundary(self):
        from core.production_baseline import build_production_baseline_summary

        summary = build_production_baseline_summary(
            response_metadata=_make_metadata(
                canonical=True,
                compat=True,
                include_ucp_summary=True,
            )
        )

        assert "perception_boundary" in summary
        assert summary["perception_boundary"]["canonical_fact_present"] is True
        assert summary["perception_boundary"]["compat_surfaces_present"] == [
            "response.metadata.multimodal_context"
        ]


class TestCanonicalStateAdapterIntegration:
    def test_adapter_exposes_perception_boundary_summary(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        adapter = CanonicalStateAdapter(
            _make_metadata(canonical=True, compat=True)
        )

        summary = adapter.perception_boundary_summary()
        assert summary["canonical_fact_present"] is True
        assert summary["compat_surfaces_present"] == [
            "response.metadata.multimodal_context"
        ]

    def test_canonical_state_summary_includes_boundary_snapshot(self):
        from core.perception.canonical_state_adapter import CanonicalStateAdapter

        adapter = CanonicalStateAdapter(
            _make_metadata(canonical=True, compat=False, include_ucp_summary=True)
        )

        summary = adapter.canonical_state_summary()
        assert "perception_boundary" in summary
        assert summary["perception_boundary"]["canonical_fact_present"] is True
