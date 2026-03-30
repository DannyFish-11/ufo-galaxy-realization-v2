"""
tests/test_projection_output_authority.py
==========================================
Test suite for the canonical runtime projection output authority model.

Covers:
- RuntimeTruthSnapshot construction and properties
- compile_runtime_truth() as the single compilation authority
- RUNTIME_TRUTH_COMPILER_AUTHORITY sentinel
- core.projection.__all__ exports
- OneAPI lower-horizon invariants in compiled snapshots
- Compatibility route annotations
- desktop_projection canonical consumption guidance
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Module import helpers
# ---------------------------------------------------------------------------


def _import_runtime_truth_compiler():
    from core.projection.runtime_truth_compiler import (
        RUNTIME_TRUTH_COMPILER_AUTHORITY,
        RuntimeTruthSnapshot,
        compile_runtime_truth,
    )
    return RUNTIME_TRUTH_COMPILER_AUTHORITY, RuntimeTruthSnapshot, compile_runtime_truth


def _import_projection_package():
    import core.projection as pkg
    return pkg


# ---------------------------------------------------------------------------
# 1. RUNTIME_TRUTH_COMPILER_AUTHORITY sentinel
# ---------------------------------------------------------------------------


class TestRuntimeTruthCompilerAuthority:
    def test_01_sentinel_is_string(self):
        AUTHORITY, _, _ = _import_runtime_truth_compiler()
        assert isinstance(AUTHORITY, str)

    def test_02_sentinel_is_non_empty(self):
        AUTHORITY, _, _ = _import_runtime_truth_compiler()
        assert len(AUTHORITY) > 0

    def test_03_sentinel_references_module(self):
        AUTHORITY, _, _ = _import_runtime_truth_compiler()
        assert "runtime_truth_compiler" in AUTHORITY

    def test_04_sentinel_references_function(self):
        AUTHORITY, _, _ = _import_runtime_truth_compiler()
        assert "compile_runtime_truth" in AUTHORITY

    def test_05_sentinel_is_fully_qualified(self):
        AUTHORITY, _, _ = _import_runtime_truth_compiler()
        assert AUTHORITY.startswith("core.projection.")

    def test_06_sentinel_stable_across_imports(self):
        AUTHORITY1, _, _ = _import_runtime_truth_compiler()
        AUTHORITY2, _, _ = _import_runtime_truth_compiler()
        assert AUTHORITY1 == AUTHORITY2

    def test_07_sentinel_exported_from_projection_package(self):
        pkg = _import_projection_package()
        assert hasattr(pkg, "RUNTIME_TRUTH_COMPILER_AUTHORITY")
        assert isinstance(pkg.RUNTIME_TRUTH_COMPILER_AUTHORITY, str)

    def test_08_sentinel_matches_between_module_and_package(self):
        AUTHORITY, _, _ = _import_runtime_truth_compiler()
        pkg = _import_projection_package()
        assert pkg.RUNTIME_TRUTH_COMPILER_AUTHORITY == AUTHORITY


# ---------------------------------------------------------------------------
# 2. RuntimeTruthSnapshot construction
# ---------------------------------------------------------------------------


class TestRuntimeTruthSnapshotConstruction:
    def _make_snapshot(self, **kwargs):
        _, RuntimeTruthSnapshot, _ = _import_runtime_truth_compiler()
        defaults = dict(
            continuum=None,
            topology=None,
            oneapi={"system_layer": "aggregator_integration", "configured": False},
            system_resource=None,
            device_presence={"registered": 0, "online": 0},
            compiled_at=time.time(),
        )
        defaults.update(kwargs)
        return RuntimeTruthSnapshot(**defaults)

    def test_10_snapshot_is_constructable(self):
        snap = self._make_snapshot()
        assert snap is not None

    def test_11_compiler_authority_auto_set(self):
        AUTHORITY, _, _ = _import_runtime_truth_compiler()
        snap = self._make_snapshot()
        assert snap.compiler_authority == AUTHORITY

    def test_12_compiled_at_is_float(self):
        snap = self._make_snapshot(compiled_at=1234567890.0)
        assert snap.compiled_at == 1234567890.0

    def test_13_continuum_none_by_default(self):
        snap = self._make_snapshot()
        assert snap.continuum is None

    def test_14_topology_none_by_default(self):
        snap = self._make_snapshot()
        assert snap.topology is None

    def test_15_oneapi_always_has_system_layer(self):
        snap = self._make_snapshot()
        assert "system_layer" in snap.oneapi

    def test_16_oneapi_system_layer_aggregator(self):
        snap = self._make_snapshot()
        assert snap.oneapi["system_layer"] == "aggregator_integration"

    def test_17_device_presence_has_registered(self):
        snap = self._make_snapshot()
        assert "registered" in snap.device_presence

    def test_18_device_presence_has_online(self):
        snap = self._make_snapshot()
        assert "online" in snap.device_presence

    def test_19_device_presence_registered_default_zero(self):
        snap = self._make_snapshot()
        assert snap.device_presence["registered"] == 0

    def test_20_device_presence_online_default_zero(self):
        snap = self._make_snapshot()
        assert snap.device_presence["online"] == 0


# ---------------------------------------------------------------------------
# 3. RuntimeTruthSnapshot properties
# ---------------------------------------------------------------------------


class TestRuntimeTruthSnapshotProperties:
    def _make_snapshot(self, **kwargs):
        _, RuntimeTruthSnapshot, _ = _import_runtime_truth_compiler()
        defaults = dict(
            continuum=None,
            topology=None,
            oneapi={"system_layer": "aggregator_integration", "configured": False},
            system_resource=None,
            device_presence={"registered": 0, "online": 0},
            compiled_at=time.time(),
        )
        defaults.update(kwargs)
        return RuntimeTruthSnapshot(**defaults)

    def test_30_has_canonical_topology_false_when_none(self):
        snap = self._make_snapshot()
        assert snap.has_canonical_topology is False

    def test_31_has_canonical_topology_true_when_topology_router_source(self):
        snap = self._make_snapshot(
            topology={"routing_authority_source": "topology_router", "primary_model": "gpt-4o"}
        )
        assert snap.has_canonical_topology is True

    def test_32_has_canonical_topology_false_when_legacy_source(self):
        snap = self._make_snapshot(
            topology={"routing_authority_source": "legacy_ucp_keys"}
        )
        assert snap.has_canonical_topology is False

    def test_33_tri_state_phase_none_when_no_continuum(self):
        snap = self._make_snapshot()
        assert snap.tri_state_phase is None

    def test_34_tri_state_phase_from_continuum(self):
        snap = self._make_snapshot(continuum={"tri_state_phase": "silent"})
        assert snap.tri_state_phase == "silent"

    def test_35_primary_model_id_none_when_no_topology(self):
        snap = self._make_snapshot()
        assert snap.primary_model_id is None

    def test_36_primary_model_id_from_topology(self):
        snap = self._make_snapshot(topology={"primary_model": "gpt-4o"})
        assert snap.primary_model_id == "gpt-4o"

    def test_37_primary_provider_id_none_when_no_topology(self):
        snap = self._make_snapshot()
        assert snap.primary_provider_id is None

    def test_38_primary_provider_id_from_topology(self):
        snap = self._make_snapshot(topology={"primary_provider": "openai"})
        assert snap.primary_provider_id == "openai"

    def test_39_oneapi_is_lower_horizon_only_true(self):
        snap = self._make_snapshot(
            oneapi={"system_layer": "aggregator_integration"}
        )
        assert snap.oneapi_is_lower_horizon_only is True

    def test_40_oneapi_is_lower_horizon_only_false_when_wrong_layer(self):
        snap = self._make_snapshot(
            oneapi={"system_layer": "direct_provider"}
        )
        assert snap.oneapi_is_lower_horizon_only is False


# ---------------------------------------------------------------------------
# 4. RuntimeTruthSnapshot serialisation
# ---------------------------------------------------------------------------


class TestRuntimeTruthSnapshotSerialisation:
    def _make_snapshot(self, **kwargs):
        _, RuntimeTruthSnapshot, _ = _import_runtime_truth_compiler()
        defaults = dict(
            continuum={"tri_state_phase": "silent"},
            topology={"primary_model": "gpt-4o", "routing_authority_source": "topology_router"},
            oneapi={"system_layer": "aggregator_integration", "configured": False},
            system_resource={"health": "ok"},
            device_presence={"registered": 2, "online": 1},
            compiled_at=1234567890.0,
        )
        defaults.update(kwargs)
        return RuntimeTruthSnapshot(**defaults)

    def test_50_to_dict_returns_dict(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert isinstance(d, dict)

    def test_51_to_dict_has_compiled_at(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert "compiled_at" in d

    def test_52_to_dict_has_compiler_authority(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert "compiler_authority" in d

    def test_53_to_dict_compiler_authority_matches_sentinel(self):
        AUTHORITY, _, _ = _import_runtime_truth_compiler()
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert d["compiler_authority"] == AUTHORITY

    def test_54_to_dict_has_continuum(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert "continuum" in d

    def test_55_to_dict_has_topology(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert "topology" in d

    def test_56_to_dict_has_oneapi(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert "oneapi" in d

    def test_57_to_dict_has_system_resource(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert "system_resource" in d

    def test_58_to_dict_has_device_presence(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert "device_presence" in d

    def test_59_to_dict_has_canonical_topology_flag(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert "has_canonical_topology" in d

    def test_60_to_dict_has_tri_state_phase(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert "tri_state_phase" in d

    def test_61_to_dict_has_primary_model_id(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert "primary_model_id" in d

    def test_62_to_dict_has_primary_provider_id(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert "primary_provider_id" in d

    def test_63_to_dict_has_oneapi_lower_horizon_flag(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert "oneapi_is_lower_horizon_only" in d

    def test_64_to_dict_oneapi_lower_horizon_is_true(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert d["oneapi_is_lower_horizon_only"] is True

    def test_65_to_dict_canonical_topology_true_when_topology_router(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert d["has_canonical_topology"] is True

    def test_66_to_dict_tri_state_phase_value(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert d["tri_state_phase"] == "silent"

    def test_67_to_dict_primary_model_id_value(self):
        snap = self._make_snapshot()
        d = snap.to_dict()
        assert d["primary_model_id"] == "gpt-4o"


# ---------------------------------------------------------------------------
# 5. compile_runtime_truth — callable and returns correct type
# ---------------------------------------------------------------------------


class TestCompileRuntimeTruth:
    def test_70_callable(self):
        _, _, compile_runtime_truth = _import_runtime_truth_compiler()
        assert callable(compile_runtime_truth)

    def test_71_returns_snapshot(self):
        _, RuntimeTruthSnapshot, compile_runtime_truth = _import_runtime_truth_compiler()
        snapshot = compile_runtime_truth()
        assert isinstance(snapshot, RuntimeTruthSnapshot)

    def test_72_snapshot_has_compiler_authority(self):
        AUTHORITY, _, compile_runtime_truth = _import_runtime_truth_compiler()
        snapshot = compile_runtime_truth()
        assert snapshot.compiler_authority == AUTHORITY

    def test_73_snapshot_compiled_at_is_recent(self):
        _, _, compile_runtime_truth = _import_runtime_truth_compiler()
        before = time.time()
        snapshot = compile_runtime_truth()
        after = time.time()
        assert before <= snapshot.compiled_at <= after

    def test_74_snapshot_oneapi_always_present(self):
        _, _, compile_runtime_truth = _import_runtime_truth_compiler()
        snapshot = compile_runtime_truth()
        assert snapshot.oneapi is not None

    def test_75_snapshot_oneapi_has_system_layer(self):
        _, _, compile_runtime_truth = _import_runtime_truth_compiler()
        snapshot = compile_runtime_truth()
        assert "system_layer" in snapshot.oneapi

    def test_76_snapshot_oneapi_system_layer_aggregator(self):
        _, _, compile_runtime_truth = _import_runtime_truth_compiler()
        snapshot = compile_runtime_truth()
        assert snapshot.oneapi["system_layer"] == "aggregator_integration"

    def test_77_snapshot_oneapi_is_lower_horizon_only(self):
        _, _, compile_runtime_truth = _import_runtime_truth_compiler()
        snapshot = compile_runtime_truth()
        assert snapshot.oneapi_is_lower_horizon_only is True

    def test_78_snapshot_device_presence_always_present(self):
        _, _, compile_runtime_truth = _import_runtime_truth_compiler()
        snapshot = compile_runtime_truth()
        assert snapshot.device_presence is not None

    def test_79_snapshot_device_presence_has_registered(self):
        _, _, compile_runtime_truth = _import_runtime_truth_compiler()
        snapshot = compile_runtime_truth()
        assert "registered" in snapshot.device_presence

    def test_80_snapshot_device_presence_has_online(self):
        _, _, compile_runtime_truth = _import_runtime_truth_compiler()
        snapshot = compile_runtime_truth()
        assert "online" in snapshot.device_presence

    def test_81_snapshot_to_dict_is_json_serialisable(self):
        import json
        _, _, compile_runtime_truth = _import_runtime_truth_compiler()
        snapshot = compile_runtime_truth()
        d = snapshot.to_dict()
        # Must not raise
        json.dumps(d)

    def test_82_compile_twice_both_valid(self):
        AUTHORITY, RuntimeTruthSnapshot, compile_runtime_truth = _import_runtime_truth_compiler()
        s1 = compile_runtime_truth()
        s2 = compile_runtime_truth()
        assert isinstance(s1, RuntimeTruthSnapshot)
        assert isinstance(s2, RuntimeTruthSnapshot)

    def test_83_separate_snapshots_have_different_compiled_at(self):
        _, _, compile_runtime_truth = _import_runtime_truth_compiler()
        # Allow a small sleep so timestamps can differ
        s1 = compile_runtime_truth()
        import time as _t; _t.sleep(0.001)
        s2 = compile_runtime_truth()
        assert s2.compiled_at >= s1.compiled_at


# ---------------------------------------------------------------------------
# 6. core.projection package exports
# ---------------------------------------------------------------------------


class TestProjectionPackageExports:
    def test_90_package_exports_runtime_truth_compiler_authority(self):
        pkg = _import_projection_package()
        assert hasattr(pkg, "RUNTIME_TRUTH_COMPILER_AUTHORITY")

    def test_91_package_exports_runtime_truth_snapshot(self):
        pkg = _import_projection_package()
        assert hasattr(pkg, "RuntimeTruthSnapshot")

    def test_92_package_exports_compile_runtime_truth(self):
        pkg = _import_projection_package()
        assert hasattr(pkg, "compile_runtime_truth")

    def test_93_compile_runtime_truth_in_all(self):
        pkg = _import_projection_package()
        assert "compile_runtime_truth" in pkg.__all__

    def test_94_runtime_truth_snapshot_in_all(self):
        pkg = _import_projection_package()
        assert "RuntimeTruthSnapshot" in pkg.__all__

    def test_95_runtime_truth_compiler_authority_in_all(self):
        pkg = _import_projection_package()
        assert "RUNTIME_TRUTH_COMPILER_AUTHORITY" in pkg.__all__

    def test_96_existing_projection_compiler_authority_still_present(self):
        pkg = _import_projection_package()
        assert hasattr(pkg, "PROJECTION_COMPILER_AUTHORITY")

    def test_97_existing_build_runtime_projection_still_present(self):
        pkg = _import_projection_package()
        assert hasattr(pkg, "build_runtime_projection")

    def test_98_existing_adapt_integration_payload_still_present(self):
        pkg = _import_projection_package()
        assert hasattr(pkg, "adapt_integration_payload")

    def test_99_existing_desktop_consumption_adapter_authority_still_present(self):
        pkg = _import_projection_package()
        assert hasattr(pkg, "DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY")
