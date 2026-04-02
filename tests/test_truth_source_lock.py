#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_truth_source_lock.py
=================================
PR-B: Contract / Truth / Policy Closure — Truth Source Lock tests.

Validates that ``core.truth_source_lock`` correctly declares and governs the
canonical device truth source boundaries.

Test classes
------------
1. TestTruthSourceLockSentinels
       Authority sentinels are importable, non-empty, and stable.

2. TestDeviceWriteSSOT
       DEVICE_WRITE_SSOT points to UnifiedDeviceManager.
       get_write_ssot() returns the same value.

3. TestReadContracts
       CANONICAL_SINGLE_DEVICE_READ_CONTRACT points to RegisteredRuntimeDevice.
       CANONICAL_MULTI_DEVICE_READ_PROJECTION points to resolve_all_device_truth.
       get_single_device_read_contract() and get_multi_device_read_projection()
       return the correct paths.

4. TestCompatCacheReadOnly
       COMPAT_CACHE_READ_ONLY is True.

5. TestModelClassification
       MODEL_CLASSIFICATION contains all required models.
       classify_model_role() returns correct roles for each model.
       UnifiedDeviceManager has role "write".
       RegisteredRuntimeDevice has role "read".
       ParticipationSummary has role "enrich".
       TaskDispatchModel has role "adapter".
       registered_devices has role "compat".

6. TestWriteReadSeparation
       Write models are distinct from read models.
       Adapter models are distinct from canonical read models.
       Compat models are not write models.

7. TestDescribeTruthSourceLock
       describe_truth_source_lock() returns a JSON-serialisable dict.
       Contains all required keys.
       Invariants mention participation cannot override truth.
"""

from __future__ import annotations

import json
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.truth_source_lock import (
    TRUTH_SOURCE_LOCK_AUTHORITY,
    TRUTH_SOURCE_LOCK_LAYER_POSITION,
    DEVICE_WRITE_SSOT,
    CANONICAL_SINGLE_DEVICE_READ_CONTRACT,
    CANONICAL_MULTI_DEVICE_READ_PROJECTION,
    COMPAT_CACHE_READ_ONLY,
    MODEL_CLASSIFICATION,
    get_write_ssot,
    get_single_device_read_contract,
    get_multi_device_read_projection,
    classify_model_role,
    describe_truth_source_lock,
)


# ---------------------------------------------------------------------------
# 1. Sentinels
# ---------------------------------------------------------------------------


class TestTruthSourceLockSentinels(unittest.TestCase):
    def test_authority_is_string(self) -> None:
        assert isinstance(TRUTH_SOURCE_LOCK_AUTHORITY, str)
        assert TRUTH_SOURCE_LOCK_AUTHORITY

    def test_authority_value(self) -> None:
        assert TRUTH_SOURCE_LOCK_AUTHORITY == "TRUTH_SOURCE_LOCK_V1"

    def test_layer_position_is_zero(self) -> None:
        assert TRUTH_SOURCE_LOCK_LAYER_POSITION == 0


# ---------------------------------------------------------------------------
# 2. Device write SSOT
# ---------------------------------------------------------------------------


class TestDeviceWriteSSOT(unittest.TestCase):
    def test_ssot_contains_unified_device_manager(self) -> None:
        assert "UnifiedDeviceManager" in DEVICE_WRITE_SSOT

    def test_ssot_is_module_path(self) -> None:
        # Should contain at least one dot (module.ClassName)
        assert "." in DEVICE_WRITE_SSOT

    def test_get_write_ssot_matches_constant(self) -> None:
        assert get_write_ssot() == DEVICE_WRITE_SSOT


# ---------------------------------------------------------------------------
# 3. Read contracts
# ---------------------------------------------------------------------------


class TestReadContracts(unittest.TestCase):
    def test_single_device_contract_contains_registered_runtime_device(self) -> None:
        assert "RegisteredRuntimeDevice" in CANONICAL_SINGLE_DEVICE_READ_CONTRACT

    def test_multi_device_projection_contains_resolve_all(self) -> None:
        assert "resolve_all_device_truth" in CANONICAL_MULTI_DEVICE_READ_PROJECTION

    def test_get_single_device_read_contract_matches_constant(self) -> None:
        assert get_single_device_read_contract() == CANONICAL_SINGLE_DEVICE_READ_CONTRACT

    def test_get_multi_device_read_projection_matches_constant(self) -> None:
        assert get_multi_device_read_projection() == CANONICAL_MULTI_DEVICE_READ_PROJECTION

    def test_single_and_multi_device_contracts_differ(self) -> None:
        assert (
            CANONICAL_SINGLE_DEVICE_READ_CONTRACT != CANONICAL_MULTI_DEVICE_READ_PROJECTION
        )


# ---------------------------------------------------------------------------
# 4. Compat cache governance
# ---------------------------------------------------------------------------


class TestCompatCacheReadOnly(unittest.TestCase):
    def test_compat_cache_read_only_is_true(self) -> None:
        assert COMPAT_CACHE_READ_ONLY is True


# ---------------------------------------------------------------------------
# 5. Model classification
# ---------------------------------------------------------------------------


class TestModelClassification(unittest.TestCase):
    _EXPECTED_MODELS = {
        "UnifiedDeviceManager": "write",
        "UnifiedConnectionManager": "read",
        "RegisteredRuntimeDevice": "read",
        "CanonicalDeviceTruth": "read",
        "DeviceReadinessSummary": "read",
        "ParticipationSummary": "enrich",
        "TaskDispatchModel": "adapter",
        "TaskResultModel": "adapter",
        "registered_devices": "compat",
        "UnifiedDevice": "write",
    }

    def test_all_expected_models_present(self) -> None:
        for name in self._EXPECTED_MODELS:
            assert name in MODEL_CLASSIFICATION, (
                f"Expected model {name!r} in MODEL_CLASSIFICATION"
            )

    def test_each_entry_has_required_keys(self) -> None:
        for name, entry in MODEL_CLASSIFICATION.items():
            for key in ("role", "module", "description"):
                assert key in entry, (
                    f"Model {name!r} is missing key {key!r}"
                )

    def test_expected_roles(self) -> None:
        for name, expected_role in self._EXPECTED_MODELS.items():
            actual = MODEL_CLASSIFICATION[name]["role"]
            assert actual == expected_role, (
                f"Model {name!r}: expected role {expected_role!r}, got {actual!r}"
            )

    def test_classify_model_role_by_short_name(self) -> None:
        for name, expected_role in self._EXPECTED_MODELS.items():
            assert classify_model_role(name) == expected_role, (
                f"classify_model_role({name!r}) should return {expected_role!r}"
            )

    def test_classify_model_role_unknown(self) -> None:
        assert classify_model_role("NonExistentModel") == "unknown"

    def test_classify_model_role_by_qualified_name(self) -> None:
        result = classify_model_role(
            "contracts.registered_runtime_device.RegisteredRuntimeDevice"
        )
        assert result == "read"

    def test_all_valid_roles(self) -> None:
        valid_roles = {"write", "read", "adapter", "compat", "enrich"}
        for name, entry in MODEL_CLASSIFICATION.items():
            assert entry["role"] in valid_roles, (
                f"Model {name!r} has unexpected role {entry['role']!r}"
            )


# ---------------------------------------------------------------------------
# 6. Write/read separation
# ---------------------------------------------------------------------------


class TestWriteReadSeparation(unittest.TestCase):
    def _models_by_role(self, role: str) -> set:
        return {
            name for name, entry in MODEL_CLASSIFICATION.items()
            if entry["role"] == role
        }

    def test_write_models_do_not_overlap_with_read_models(self) -> None:
        write_models = self._models_by_role("write")
        read_models = self._models_by_role("read")
        overlap = write_models & read_models
        assert not overlap, (
            f"Models cannot be both write and read: {overlap}"
        )

    def test_adapter_models_do_not_overlap_with_canonical_read_models(self) -> None:
        adapter_models = self._models_by_role("adapter")
        read_models = self._models_by_role("read")
        overlap = adapter_models & read_models
        assert not overlap, (
            f"Adapter models cannot be canonical read models: {overlap}"
        )

    def test_compat_models_do_not_overlap_with_write_models(self) -> None:
        compat_models = self._models_by_role("compat")
        write_models = self._models_by_role("write")
        overlap = compat_models & write_models
        assert not overlap, (
            f"Compat (read-only) models cannot be write models: {overlap}"
        )

    def test_participation_is_enrich_not_write(self) -> None:
        assert classify_model_role("ParticipationSummary") == "enrich"
        assert classify_model_role("ParticipationSummary") != "write"
        assert classify_model_role("ParticipationSummary") != "read"

    def test_task_dispatch_model_is_adapter_not_canonical(self) -> None:
        assert classify_model_role("TaskDispatchModel") == "adapter"
        assert classify_model_role("TaskDispatchModel") != "read"
        assert classify_model_role("TaskDispatchModel") != "write"


# ---------------------------------------------------------------------------
# 7. describe_truth_source_lock
# ---------------------------------------------------------------------------


class TestDescribeTruthSourceLock(unittest.TestCase):
    def setUp(self) -> None:
        self.desc = describe_truth_source_lock()

    def test_returns_dict(self) -> None:
        assert isinstance(self.desc, dict)

    def test_json_serialisable(self) -> None:
        serialised = json.dumps(self.desc)
        assert serialised

    def test_has_authority(self) -> None:
        assert self.desc["authority"] == TRUTH_SOURCE_LOCK_AUTHORITY

    def test_has_write_ssot(self) -> None:
        assert "UnifiedDeviceManager" in self.desc["device_write_ssot"]

    def test_has_read_contracts(self) -> None:
        assert "RegisteredRuntimeDevice" in self.desc[
            "canonical_single_device_read_contract"
        ]
        assert "resolve_all_device_truth" in self.desc[
            "canonical_multi_device_read_projection"
        ]

    def test_compat_cache_read_only_true(self) -> None:
        assert self.desc["compat_cache_read_only"] is True

    def test_has_model_roles(self) -> None:
        roles = self.desc["model_roles"]
        assert isinstance(roles, dict)
        assert roles.get("UnifiedDeviceManager") == "write"
        assert roles.get("RegisteredRuntimeDevice") == "read"
        assert roles.get("ParticipationSummary") == "enrich"

    def test_invariants_mention_participation(self) -> None:
        invariants = self.desc["invariants"]
        combined = " ".join(invariants)
        assert "ParticipationSummary" in combined or "participation" in combined.lower()

    def test_invariants_mention_compat_cache(self) -> None:
        invariants = self.desc["invariants"]
        combined = " ".join(invariants)
        assert "READ-ONLY" in combined or "read-only" in combined.lower()


if __name__ == "__main__":
    unittest.main()
