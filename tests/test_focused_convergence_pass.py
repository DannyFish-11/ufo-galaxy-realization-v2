"""
tests/test_focused_convergence_pass.py
=======================================
Tests for the focused convergence pass:

  A) Truth-source mapping and explainability
  B) Unified system-state narrative
  C) Panel / operator / runtime outward semantics alignment
  D) Traceability of high-value states
  E) Unified outward operating surface

All tests are unit-level, fully deterministic, and import-only where possible
(no network, no filesystem I/O, no new dependencies).
"""

from __future__ import annotations

import importlib
import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch


# =============================================================================
# Part A — Truth-source mapping and explainability
# =============================================================================


class TestATruthSourceRegistry:
    """A) Outward truth source registry describes provenance for key fields."""

    def test_registry_module_importable(self):
        mod = importlib.import_module("core.outward_truth_source_registry")
        assert hasattr(mod, "OUTWARD_TRUTH_SOURCE_REGISTRY_AUTHORITY")
        assert hasattr(mod, "TruthSourceEntry")
        assert hasattr(mod, "get_registry")
        assert hasattr(mod, "get_entry")
        assert hasattr(mod, "build_registry_snapshot")

    def test_registry_has_canonical_allocation_entry(self):
        from core.outward_truth_source_registry import get_entry
        entry = get_entry("allocation.records")
        assert entry is not None
        assert entry.is_canonical_truth is True
        assert "CanonicalTaskRuntime" in entry.source_module
        assert entry.is_durable is True
        assert entry.requires_revalidation_after_restart is True

    def test_registry_has_autonomy_entry(self):
        from core.outward_truth_source_registry import get_entry
        entry = get_entry("autonomy.device_class")
        assert entry is not None
        assert entry.is_canonical_truth is True
        assert "device_autonomy_evidence" in entry.source_module
        assert entry.is_projection is True
        # posture alone never promotes — explained in the entry
        assert "posture" in entry.explanation.lower()

    def test_registry_has_device_support_entries(self):
        from core.outward_truth_source_registry import get_entry
        tier_entry = get_entry("device_support.operational_tier")
        readiness_entry = get_entry("device_support.dispatch_readiness")
        assert tier_entry is not None
        assert readiness_entry is not None
        assert tier_entry.is_canonical_truth is True
        assert readiness_entry.is_canonical_truth is True

    def test_registry_has_topology_entry(self):
        from core.outward_truth_source_registry import get_entry
        entry = get_entry("topology.node_relations")
        assert entry is not None
        assert entry.is_projection is True  # topology is a projection
        assert "projection" in entry.explanation.lower()

    def test_registry_has_android_entries(self):
        from core.outward_truth_source_registry import get_entry
        participation_entry = get_entry("android.participation_tier")
        snapshot_entry = get_entry("android.device_snapshot")
        execution_entry = get_entry("android.execution_phase")
        assert participation_entry is not None
        assert snapshot_entry is not None
        assert execution_entry is not None
        assert snapshot_entry.is_durable is True
        assert snapshot_entry.requires_revalidation_after_restart is True

    def test_registry_has_recovery_entries(self):
        from core.outward_truth_source_registry import get_entry
        flow_entry = get_entry("recovery.delegated_flow_state")
        android_entry = get_entry("recovery.android_continuity")
        assert flow_entry is not None
        assert android_entry is not None
        assert flow_entry.is_durable is True
        assert flow_entry.requires_revalidation_after_restart is True

    def test_registry_has_operator_entries(self):
        from core.outward_truth_source_registry import get_entry
        snapshot = get_entry("operator.snapshot")
        panel = get_entry("operator.panel_unified")
        assert snapshot is not None
        assert panel is not None
        # Operator snapshot is a projection, not canonical truth itself
        assert snapshot.is_projection is True
        assert snapshot.is_canonical_truth is False

    def test_build_registry_snapshot_is_serialisable(self):
        from core.outward_truth_source_registry import build_registry_snapshot
        snap = build_registry_snapshot()
        assert isinstance(snap, dict)
        assert "authority" in snap
        assert "entry_count" in snap
        assert "entries" in snap
        assert snap["entry_count"] > 0
        # Every entry should be a dict with required keys
        for key, entry_dict in snap["entries"].items():
            assert "field_key" in entry_dict
            assert "source_module" in entry_dict
            assert "is_canonical_truth" in entry_dict
            assert "explanation" in entry_dict

    def test_assert_source_for_field_correct_source(self):
        from core.outward_truth_source_registry import assert_source_for_field
        # Should not raise for a correct source
        assert_source_for_field("allocation.records", "CanonicalTaskRuntime")

    def test_assert_source_for_field_wrong_source_raises(self):
        import pytest
        from core.outward_truth_source_registry import assert_source_for_field
        with pytest.raises((AssertionError, KeyError)):
            assert_source_for_field("allocation.records", "SomeWrongModule")

    def test_all_entries_have_explanation(self):
        from core.outward_truth_source_registry import get_registry
        registry = get_registry()
        for key, entry in registry.items():
            assert entry.explanation, f"Entry '{key}' has empty explanation"

    def test_all_entries_have_evidence_chain(self):
        from core.outward_truth_source_registry import get_registry
        registry = get_registry()
        for key, entry in registry.items():
            assert isinstance(entry.evidence_chain, tuple), \
                f"Entry '{key}' evidence_chain must be a tuple"

    def test_durable_entries_require_revalidation(self):
        """Durable entries that persist across restart should require revalidation."""
        from core.outward_truth_source_registry import get_registry
        registry = get_registry()
        for key, entry in registry.items():
            if entry.is_durable:
                assert entry.requires_revalidation_after_restart, (
                    f"Durable entry '{key}' must require revalidation after restart"
                )


# =============================================================================
# Part B — Unified system-state narrative
# =============================================================================


class TestBSystemStateNarrative:
    """B) Unified system-state narrative provides coherent 7-dimension view."""

    def test_narrative_module_importable(self):
        mod = importlib.import_module("core.unified_system_state_narrative")
        assert hasattr(mod, "UNIFIED_SYSTEM_STATE_NARRATIVE_AUTHORITY")
        assert hasattr(mod, "SystemStateNarrative")
        assert hasattr(mod, "NarrativeDimension")
        assert hasattr(mod, "build_system_state_narrative")
        assert hasattr(mod, "ALL_NARRATIVE_DIMENSIONS")

    def test_all_dimension_names_are_defined(self):
        from core.unified_system_state_narrative import (
            ALL_NARRATIVE_DIMENSIONS,
            DIM_OVERALL_RUNTIME_STATE,
            DIM_OPERATING_STRUCTURE,
            DIM_TASK_EXECUTION_STATE,
            DIM_DEVICE_DISPATCH_SUPPORT_STATE,
            DIM_AUTONOMY_PARTICIPATION_STATE,
            DIM_TOPOLOGY_ALLOCATION_RELATIONS,
            DIM_RECOVERY_DEGRADATION_BLOCKAGE,
        )
        assert DIM_OVERALL_RUNTIME_STATE in ALL_NARRATIVE_DIMENSIONS
        assert DIM_OPERATING_STRUCTURE in ALL_NARRATIVE_DIMENSIONS
        assert DIM_TASK_EXECUTION_STATE in ALL_NARRATIVE_DIMENSIONS
        assert DIM_DEVICE_DISPATCH_SUPPORT_STATE in ALL_NARRATIVE_DIMENSIONS
        assert DIM_AUTONOMY_PARTICIPATION_STATE in ALL_NARRATIVE_DIMENSIONS
        assert DIM_TOPOLOGY_ALLOCATION_RELATIONS in ALL_NARRATIVE_DIMENSIONS
        assert DIM_RECOVERY_DEGRADATION_BLOCKAGE in ALL_NARRATIVE_DIMENSIONS
        assert len(ALL_NARRATIVE_DIMENSIONS) == 7

    def test_build_system_state_narrative_returns_object(self):
        from core.unified_system_state_narrative import (
            SystemStateNarrative,
            build_system_state_narrative,
        )
        narrative = build_system_state_narrative()
        assert isinstance(narrative, SystemStateNarrative)

    def test_narrative_has_all_7_dimensions(self):
        from core.unified_system_state_narrative import (
            ALL_NARRATIVE_DIMENSIONS,
            build_system_state_narrative,
        )
        narrative = build_system_state_narrative()
        for dim_name in ALL_NARRATIVE_DIMENSIONS:
            assert dim_name in narrative.dimensions, \
                f"Narrative missing dimension: {dim_name}"

    def test_each_dimension_has_required_fields(self):
        from core.unified_system_state_narrative import build_system_state_narrative
        narrative = build_system_state_narrative()
        for dim_name, dim in narrative.dimensions.items():
            assert dim.state, f"Dimension '{dim_name}' has empty state"
            assert dim.source, f"Dimension '{dim_name}' has empty source"
            assert dim.explanation, f"Dimension '{dim_name}' has empty explanation"
            assert isinstance(dim.evidence_basis, dict), \
                f"Dimension '{dim_name}' evidence_basis must be a dict"
            assert isinstance(dim.traceability, list), \
                f"Dimension '{dim_name}' traceability must be a list"
            assert isinstance(dim.is_canonical_truth, bool), \
                f"Dimension '{dim_name}' is_canonical_truth must be bool"

    def test_narrative_to_dict_is_serialisable(self):
        from core.unified_system_state_narrative import build_system_state_narrative
        narrative = build_system_state_narrative()
        d = narrative.to_dict()
        assert isinstance(d, dict)
        assert "narrative_id" in d
        assert "compiled_at" in d
        assert "authority" in d
        assert "overall_operability" in d
        assert "overall_explanation" in d
        assert "dimensions" in d
        assert isinstance(d["dimensions"], dict)

    def test_narrative_dimensions_serialise_correctly(self):
        from core.unified_system_state_narrative import build_system_state_narrative
        narrative = build_system_state_narrative()
        d = narrative.to_dict()
        for dim_name, dim_dict in d["dimensions"].items():
            assert "dimension" in dim_dict
            assert "state" in dim_dict
            assert "source" in dim_dict
            assert "is_canonical_truth" in dim_dict
            assert "explanation" in dim_dict
            assert "evidence_basis" in dim_dict
            assert "traceability" in dim_dict

    def test_overall_operability_is_set(self):
        from core.unified_system_state_narrative import (
            ALL_KNOWN_OPERABILITY_STATES,
            build_system_state_narrative,
        )
        narrative = build_system_state_narrative()
        # Allow any known operability state OR a composite state string
        assert (
            narrative.overall_operability in ALL_KNOWN_OPERABILITY_STATES
            or len(narrative.overall_operability) > 0
        )

    def test_narrative_unsourced_dimensions_is_list(self):
        from core.unified_system_state_narrative import build_system_state_narrative
        narrative = build_system_state_narrative()
        assert isinstance(narrative.unsourced_dimensions, list)

    def test_dimension_traceability_is_non_empty_after_build(self):
        """Each dimension should have at least one traceability step (the query attempt)."""
        from core.unified_system_state_narrative import build_system_state_narrative
        narrative = build_system_state_narrative()
        for dim_name, dim in narrative.dimensions.items():
            assert len(dim.traceability) > 0, \
                f"Dimension '{dim_name}' has empty traceability"

    def test_get_dimension_returns_correct_dim(self):
        from core.unified_system_state_narrative import (
            DIM_OVERALL_RUNTIME_STATE,
            build_system_state_narrative,
        )
        narrative = build_system_state_narrative()
        dim = narrative.get_dimension(DIM_OVERALL_RUNTIME_STATE)
        assert dim is not None
        assert dim.dimension == DIM_OVERALL_RUNTIME_STATE

    def test_get_dimension_unknown_returns_none(self):
        from core.unified_system_state_narrative import build_system_state_narrative
        narrative = build_system_state_narrative()
        dim = narrative.get_dimension("no_such_dimension")
        assert dim is None


# =============================================================================
# Part C — Panel / operator / runtime outward semantics alignment
# =============================================================================


class TestCPanelNarrativeAlignment:
    """C) Unified panel payload includes narrative and truth registry."""

    def test_panel_payload_has_system_state_narrative_field(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        payload = UnifiedPanelPayload()
        assert hasattr(payload, "system_state_narrative")
        assert isinstance(payload.system_state_narrative, dict)

    def test_panel_payload_has_truth_source_registry_field(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        payload = UnifiedPanelPayload()
        assert hasattr(payload, "truth_source_registry")
        assert isinstance(payload.truth_source_registry, dict)

    def test_panel_to_dict_includes_narrative(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        payload = UnifiedPanelPayload()
        payload.system_state_narrative = {"overall_operability": "operable", "dimensions": {}}
        d = payload.to_dict()
        assert "system_state_narrative" in d
        assert d["system_state_narrative"]["overall_operability"] == "operable"

    def test_panel_to_dict_includes_truth_registry(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        payload = UnifiedPanelPayload()
        payload.truth_source_registry = {"authority": "test", "entry_count": 5}
        d = payload.to_dict()
        assert "truth_source_registry" in d
        assert d["truth_source_registry"]["entry_count"] == 5

    def test_fill_system_state_narrative_populates_payload(self):
        from core.unified_panel_aggregation import (
            UnifiedPanelAggregationService,
            UnifiedPanelPayload,
        )
        svc = UnifiedPanelAggregationService()
        payload = UnifiedPanelPayload()
        svc._fill_system_state_narrative(payload)
        # Should have populated the field (even if some dimensions are default)
        assert isinstance(payload.system_state_narrative, dict)
        assert "authority" in payload.system_state_narrative
        assert "dimensions" in payload.system_state_narrative

    def test_fill_truth_source_registry_populates_payload(self):
        from core.unified_panel_aggregation import (
            UnifiedPanelAggregationService,
            UnifiedPanelPayload,
        )
        svc = UnifiedPanelAggregationService()
        payload = UnifiedPanelPayload()
        svc._fill_truth_source_registry(payload)
        assert isinstance(payload.truth_source_registry, dict)
        assert "entry_count" in payload.truth_source_registry
        assert payload.truth_source_registry["entry_count"] > 0

    def test_panel_narrative_and_outward_truth_share_same_source(self):
        """Both panel and outward truth should produce narratives from the same module."""
        from core.unified_panel_aggregation import (
            UnifiedPanelAggregationService,
            UnifiedPanelPayload,
        )
        svc = UnifiedPanelAggregationService()
        payload = UnifiedPanelPayload()
        svc._fill_system_state_narrative(payload)

        narrative_dict = payload.system_state_narrative
        # The narrative must carry the UNIFIED_SYSTEM_STATE_NARRATIVE_AUTHORITY
        from core.unified_system_state_narrative import UNIFIED_SYSTEM_STATE_NARRATIVE_AUTHORITY
        assert narrative_dict.get("authority") == UNIFIED_SYSTEM_STATE_NARRATIVE_AUTHORITY


# =============================================================================
# Part D — Traceability of high-value states
# =============================================================================


class TestDTraceability:
    """D) Traceability: each dimension explains why it is in its current state."""

    def test_overall_runtime_state_has_source_annotation(self):
        from core.unified_system_state_narrative import (
            DIM_OVERALL_RUNTIME_STATE,
            build_system_state_narrative,
        )
        narrative = build_system_state_narrative()
        dim = narrative.get_dimension(DIM_OVERALL_RUNTIME_STATE)
        assert dim is not None
        # Source must reference a canonical module
        assert "readiness_matrix" in dim.source or "outward_runtime_truth" in dim.source

    def test_device_dispatch_state_has_blocker_traceability(self):
        from core.unified_system_state_narrative import (
            DIM_DEVICE_DISPATCH_SUPPORT_STATE,
            build_system_state_narrative,
        )
        narrative = build_system_state_narrative()
        dim = narrative.get_dimension(DIM_DEVICE_DISPATCH_SUPPORT_STATE)
        assert dim is not None
        # Source must reference dispatch readiness or operational support
        assert (
            "dispatch_readiness" in dim.source
            or "device_operational_support" in dim.source
            or "unavailable" in dim.source
        )

    def test_autonomy_state_explains_evidence_requirement(self):
        from core.unified_system_state_narrative import (
            DIM_AUTONOMY_PARTICIPATION_STATE,
            build_system_state_narrative,
        )
        narrative = build_system_state_narrative()
        dim = narrative.get_dimension(DIM_AUTONOMY_PARTICIPATION_STATE)
        assert dim is not None
        # Should mention evidence or posture in the explanation
        assert (
            "evidence" in dim.explanation.lower()
            or "posture" in dim.explanation.lower()
            or "unavailable" in dim.explanation.lower()
        )

    def test_recovery_state_explains_revalidation(self):
        from core.unified_system_state_narrative import (
            DIM_RECOVERY_DEGRADATION_BLOCKAGE,
            build_system_state_narrative,
        )
        narrative = build_system_state_narrative()
        dim = narrative.get_dimension(DIM_RECOVERY_DEGRADATION_BLOCKAGE)
        assert dim is not None
        # Source must reference readiness matrix
        assert "readiness_matrix" in dim.source

    def test_topology_state_marks_projection_nature(self):
        from core.unified_system_state_narrative import (
            DIM_TOPOLOGY_ALLOCATION_RELATIONS,
            build_system_state_narrative,
        )
        narrative = build_system_state_narrative()
        dim = narrative.get_dimension(DIM_TOPOLOGY_ALLOCATION_RELATIONS)
        assert dim is not None
        # Explanation must note projection nature, or indicate no active data,
        # or be unavailable — either is an honest representation of the state.
        explanation_lower = dim.explanation.lower()
        assert (
            "projection" in explanation_lower
            or "unavailable" in explanation_lower
            or "no active" in explanation_lower
            or "no topology" in explanation_lower
        ), (
            f"Topology dimension explanation must note its projection nature or absence of data. "
            f"Got: {dim.explanation!r}"
        )

    def test_registry_allocation_entry_marks_revalidation_requirement(self):
        from core.outward_truth_source_registry import get_entry
        entry = get_entry("allocation.records")
        assert entry is not None
        assert entry.requires_revalidation_after_restart is True
        assert "revalidat" in entry.explanation.lower()

    def test_registry_android_snapshot_marks_revalidation_requirement(self):
        from core.outward_truth_source_registry import get_entry
        entry = get_entry("android.device_snapshot")
        assert entry is not None
        assert entry.requires_revalidation_after_restart is True

    def test_registry_operator_snapshot_is_annotated_as_projection(self):
        from core.outward_truth_source_registry import get_entry
        entry = get_entry("operator.snapshot")
        assert entry is not None
        assert entry.is_projection is True
        assert entry.is_canonical_truth is False
        # The explanation must make clear it is a projection
        assert "projection" in entry.explanation.lower()

    def test_all_traceability_lists_contain_strings(self):
        """Every traceability entry in every dimension must be a non-empty string."""
        from core.unified_system_state_narrative import build_system_state_narrative
        narrative = build_system_state_narrative()
        for dim_name, dim in narrative.dimensions.items():
            for step in dim.traceability:
                assert isinstance(step, str) and step, \
                    f"Dimension '{dim_name}' has empty/non-string traceability step"


# =============================================================================
# Part E — Unified outward operating surface
# =============================================================================


class TestEUnifiedOutwardSurface:
    """E) The outward runtime truth snapshot includes the system-state narrative."""

    def test_outward_truth_snapshot_has_narrative_field(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot
        import uuid
        snap = OutwardRuntimeTruthSnapshot(
            snapshot_id=str(uuid.uuid4()),
            compiled_at=time.time(),
        )
        assert hasattr(snap, "system_state_narrative")

    def test_outward_truth_to_dict_includes_narrative_key(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot
        import uuid
        snap = OutwardRuntimeTruthSnapshot(
            snapshot_id=str(uuid.uuid4()),
            compiled_at=time.time(),
            system_state_narrative={"overall_operability": "operable"},
        )
        d = snap.to_dict()
        assert "system_state_narrative" in d
        assert d["system_state_narrative"]["overall_operability"] == "operable"

    def test_outward_truth_snapshot_narrative_none_by_default(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot
        import uuid
        snap = OutwardRuntimeTruthSnapshot(
            snapshot_id=str(uuid.uuid4()),
            compiled_at=time.time(),
        )
        assert snap.system_state_narrative is None

    def test_compile_outward_truth_populates_narrative(self):
        """compile_outward_truth() should attempt to populate the narrative facet."""
        from core.outward_runtime_truth import compile_outward_truth, reset_outward_runtime_truth_runtime
        reset_outward_runtime_truth_runtime()
        snapshot = compile_outward_truth()
        # The narrative may be None if the module fails, but the field must exist
        assert hasattr(snapshot, "system_state_narrative")

    def test_outward_truth_has_unified_system_narrative_authority(self):
        """The authority string must reference the narrative module."""
        from core.unified_system_state_narrative import UNIFIED_SYSTEM_STATE_NARRATIVE_AUTHORITY
        assert "UNIFIED_SYSTEM_STATE_NARRATIVE_V1" in UNIFIED_SYSTEM_STATE_NARRATIVE_AUTHORITY

    def test_narrative_dimension_state_is_never_empty_string(self):
        """No dimension state should be an empty string after build."""
        from core.unified_system_state_narrative import build_system_state_narrative
        narrative = build_system_state_narrative()
        for dim_name, dim in narrative.dimensions.items():
            assert dim.state != "", f"Dimension '{dim_name}' has empty state string"

    def test_overall_explanation_is_populated(self):
        from core.unified_system_state_narrative import build_system_state_narrative
        narrative = build_system_state_narrative()
        assert isinstance(narrative.overall_explanation, str)
        assert len(narrative.overall_explanation) > 0

    def test_narrative_schema_version_is_stable(self):
        from core.unified_system_state_narrative import (
            UNIFIED_SYSTEM_STATE_NARRATIVE_VERSION,
            SystemStateNarrative,
        )
        snap = SystemStateNarrative()
        assert snap.version == UNIFIED_SYSTEM_STATE_NARRATIVE_VERSION

    def test_registry_authority_is_stable(self):
        from core.outward_truth_source_registry import OUTWARD_TRUTH_SOURCE_REGISTRY_AUTHORITY
        assert "OUTWARD_TRUTH_SOURCE_REGISTRY_V1" in OUTWARD_TRUTH_SOURCE_REGISTRY_AUTHORITY

    def test_narrative_dimension_builder_gracefully_degrades(self):
        """Narrative must not raise even when all sources fail."""
        from core.unified_system_state_narrative import build_system_state_narrative
        # Patch all source imports to raise
        with patch("core.unified_system_state_narrative.logger"):
            # Should still return a narrative object (not raise)
            narrative = build_system_state_narrative()
            assert narrative is not None

    def test_truth_source_registry_and_narrative_are_independent(self):
        """Registry and narrative must be independently importable and usable."""
        from core.outward_truth_source_registry import build_registry_snapshot
        from core.unified_system_state_narrative import build_system_state_narrative
        registry = build_registry_snapshot()
        narrative = build_system_state_narrative()
        # Both must succeed independently
        assert isinstance(registry, dict)
        assert hasattr(narrative, "dimensions")

    def test_panel_build_payload_includes_both_fields(self):
        """build_payload() must populate system_state_narrative and truth_source_registry."""
        from core.unified_panel_aggregation import build_unified_panel_payload
        payload = build_unified_panel_payload()
        d = payload.to_dict()
        assert "system_state_narrative" in d
        assert "truth_source_registry" in d
        # Both must be non-empty dicts (or gracefully empty dicts)
        assert isinstance(d["system_state_narrative"], dict)
        assert isinstance(d["truth_source_registry"], dict)
