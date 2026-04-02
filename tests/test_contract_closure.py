#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_contract_closure.py
================================
PR-B: Contract / Truth / Policy Closure — Internal Contract Closure tests.

Validates that ``core.contract_closure`` correctly declares and governs the
internal canonical contract boundaries.

Test classes
------------
1. TestContractClosureSentinels
       Authority sentinels and version strings are importable and stable.

2. TestCanonicalContractDeclarations
       INTERNAL_DISPATCH_CONTRACT and INTERNAL_RESULT_CONTRACT point to the
       correct canonical classes.

3. TestBoundaryDeclarations
       PUBLIC_API_BOUNDARY, EDGE_ADAPTER_BOUNDARY, INTERNAL_CANONICAL_BOUNDARY
       are distinct, non-empty strings.

4. TestCanonicalAdapterRegistry
       CANONICAL_ADAPTER_REGISTRY contains all expected adapters.
       Each entry has the required keys (module, produces, boundary, description).

5. TestIsCanonicalDispatchContract
       is_canonical_dispatch_contract() returns True for TaskEnvelope
       (or mock with that class name) and False for other types.

6. TestIsCanonicalResultContract
       is_canonical_result_contract() returns True for ResultEnvelope
       (or mock with that class name) and False for other types.

7. TestGetContractBoundary
       get_contract_boundary() maps keywords to the correct boundary constant.

8. TestDescribeContractClosure
       describe_contract_closure() returns a complete, JSON-serialisable dict.
"""

from __future__ import annotations

import json
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.contract_closure import (
    INTERNAL_CONTRACT_CLOSURE_AUTHORITY,
    CONTRACT_CLOSURE_LAYER_POSITION,
    CONTRACT_CLOSURE_VERSION,
    INTERNAL_DISPATCH_CONTRACT,
    INTERNAL_RESULT_CONTRACT,
    PUBLIC_API_BOUNDARY,
    EDGE_ADAPTER_BOUNDARY,
    INTERNAL_CANONICAL_BOUNDARY,
    CANONICAL_ADAPTER_REGISTRY,
    is_canonical_dispatch_contract,
    is_canonical_result_contract,
    get_contract_boundary,
    describe_contract_closure,
)


# ---------------------------------------------------------------------------
# 1. Sentinels
# ---------------------------------------------------------------------------


class TestContractClosureSentinels(unittest.TestCase):
    def test_authority_is_string(self) -> None:
        assert isinstance(INTERNAL_CONTRACT_CLOSURE_AUTHORITY, str)
        assert INTERNAL_CONTRACT_CLOSURE_AUTHORITY

    def test_authority_value(self) -> None:
        assert INTERNAL_CONTRACT_CLOSURE_AUTHORITY == "INTERNAL_CONTRACT_CLOSURE_V1"

    def test_layer_position_is_zero(self) -> None:
        assert CONTRACT_CLOSURE_LAYER_POSITION == 0

    def test_version_is_string(self) -> None:
        assert isinstance(CONTRACT_CLOSURE_VERSION, str)
        assert CONTRACT_CLOSURE_VERSION


# ---------------------------------------------------------------------------
# 2. Canonical contract declarations
# ---------------------------------------------------------------------------


class TestCanonicalContractDeclarations(unittest.TestCase):
    def test_dispatch_contract_points_to_task_envelope(self) -> None:
        assert "TaskEnvelope" in INTERNAL_DISPATCH_CONTRACT
        assert "task_envelope" in INTERNAL_DISPATCH_CONTRACT

    def test_result_contract_points_to_result_envelope(self) -> None:
        assert "ResultEnvelope" in INTERNAL_RESULT_CONTRACT
        assert "command_envelope" in INTERNAL_RESULT_CONTRACT

    def test_dispatch_and_result_differ(self) -> None:
        assert INTERNAL_DISPATCH_CONTRACT != INTERNAL_RESULT_CONTRACT


# ---------------------------------------------------------------------------
# 3. Boundary declarations
# ---------------------------------------------------------------------------


class TestBoundaryDeclarations(unittest.TestCase):
    def test_all_boundaries_are_strings(self) -> None:
        for boundary in (
            PUBLIC_API_BOUNDARY,
            EDGE_ADAPTER_BOUNDARY,
            INTERNAL_CANONICAL_BOUNDARY,
        ):
            assert isinstance(boundary, str)
            assert boundary

    def test_all_boundaries_are_distinct(self) -> None:
        boundaries = [
            PUBLIC_API_BOUNDARY,
            EDGE_ADAPTER_BOUNDARY,
            INTERNAL_CANONICAL_BOUNDARY,
        ]
        assert len(set(boundaries)) == len(boundaries)

    def test_public_api_boundary_value(self) -> None:
        assert PUBLIC_API_BOUNDARY == "PUBLIC_API_BOUNDARY"

    def test_edge_adapter_boundary_value(self) -> None:
        assert EDGE_ADAPTER_BOUNDARY == "EDGE_ADAPTER_BOUNDARY"

    def test_internal_canonical_boundary_value(self) -> None:
        assert INTERNAL_CANONICAL_BOUNDARY == "INTERNAL_CANONICAL_BOUNDARY"


# ---------------------------------------------------------------------------
# 4. Canonical adapter registry
# ---------------------------------------------------------------------------


class TestCanonicalAdapterRegistry(unittest.TestCase):
    _REQUIRED_ADAPTERS = {
        "AntiCorruptionLayer",
        "normalize_to_task_envelope",
        "normalize_ingress_to_envelope",
        "TaskAdapterLayer",
        "normalize_to_result_envelope",
        "envelope_from_command_request",
        "envelope_from_relay_request",
        "envelope_from_mcp_call",
    }

    def test_all_required_adapters_present(self) -> None:
        for name in self._REQUIRED_ADAPTERS:
            assert name in CANONICAL_ADAPTER_REGISTRY, (
                f"Expected adapter {name!r} in CANONICAL_ADAPTER_REGISTRY"
            )

    def test_each_entry_has_required_keys(self) -> None:
        for name, entry in CANONICAL_ADAPTER_REGISTRY.items():
            for key in ("module", "produces", "boundary", "description"):
                assert key in entry, (
                    f"Adapter {name!r} is missing key {key!r}"
                )

    def test_dispatch_adapters_produce_task_envelope(self) -> None:
        dispatch_adapters = {
            "normalize_to_task_envelope",
            "normalize_ingress_to_envelope",
            "TaskAdapterLayer",
            "envelope_from_command_request",
            "envelope_from_relay_request",
            "envelope_from_mcp_call",
        }
        for name in dispatch_adapters:
            entry = CANONICAL_ADAPTER_REGISTRY[name]
            assert "TaskEnvelope" in entry["produces"], (
                f"Adapter {name!r} should produce TaskEnvelope"
            )

    def test_result_adapter_produces_result_envelope(self) -> None:
        entry = CANONICAL_ADAPTER_REGISTRY["normalize_to_result_envelope"]
        assert "ResultEnvelope" in entry["produces"]

    def test_all_adapters_at_edge_boundary(self) -> None:
        for name, entry in CANONICAL_ADAPTER_REGISTRY.items():
            assert entry["boundary"] == EDGE_ADAPTER_BOUNDARY, (
                f"Adapter {name!r} should be at EDGE_ADAPTER_BOUNDARY"
            )


# ---------------------------------------------------------------------------
# 5. is_canonical_dispatch_contract
# ---------------------------------------------------------------------------


class TestIsCanonicalDispatchContract(unittest.TestCase):
    def test_false_for_plain_class(self) -> None:
        class SomeClass:
            pass

        assert not is_canonical_dispatch_contract(SomeClass())

    def test_false_for_result_name(self) -> None:
        class ResultEnvelope:
            pass

        assert not is_canonical_dispatch_contract(ResultEnvelope())

    def test_true_for_task_envelope_class_name(self) -> None:
        """Create a dummy class named TaskEnvelope and verify detection."""

        class TaskEnvelope:
            pass

        assert is_canonical_dispatch_contract(TaskEnvelope())

    def test_true_for_task_envelope_type(self) -> None:
        class TaskEnvelope:
            pass

        assert is_canonical_dispatch_contract(TaskEnvelope)


# ---------------------------------------------------------------------------
# 6. is_canonical_result_contract
# ---------------------------------------------------------------------------


class TestIsCanonicalResultContract(unittest.TestCase):
    def test_false_for_plain_class(self) -> None:
        class SomeClass:
            pass

        assert not is_canonical_result_contract(SomeClass())

    def test_false_for_task_name(self) -> None:
        class TaskEnvelope:
            pass

        assert not is_canonical_result_contract(TaskEnvelope())

    def test_true_for_result_envelope_class_name(self) -> None:
        class ResultEnvelope:
            pass

        assert is_canonical_result_contract(ResultEnvelope())

    def test_true_for_result_envelope_type(self) -> None:
        class ResultEnvelope:
            pass

        assert is_canonical_result_contract(ResultEnvelope)


# ---------------------------------------------------------------------------
# 7. get_contract_boundary
# ---------------------------------------------------------------------------


class TestGetContractBoundary(unittest.TestCase):
    def test_public_keywords(self) -> None:
        for hint in ("public", "api", "external", "PUBLIC", "API"):
            result = get_contract_boundary(hint)
            assert result == PUBLIC_API_BOUNDARY, (
                f"hint={hint!r} expected PUBLIC_API_BOUNDARY, got {result!r}"
            )

    def test_edge_keywords(self) -> None:
        for hint in ("edge", "adapter", "acl", "gateway", "EDGE", "ADAPTER"):
            result = get_contract_boundary(hint)
            assert result == EDGE_ADAPTER_BOUNDARY, (
                f"hint={hint!r} expected EDGE_ADAPTER_BOUNDARY, got {result!r}"
            )

    def test_internal_keywords(self) -> None:
        for hint in ("internal", "canonical", "spine", "INTERNAL"):
            result = get_contract_boundary(hint)
            assert result == INTERNAL_CANONICAL_BOUNDARY

    def test_none_returns_internal(self) -> None:
        assert get_contract_boundary(None) == INTERNAL_CANONICAL_BOUNDARY

    def test_empty_string_returns_internal(self) -> None:
        assert get_contract_boundary("") == INTERNAL_CANONICAL_BOUNDARY

    def test_unknown_returns_internal(self) -> None:
        assert get_contract_boundary("xyz_unknown_layer") == INTERNAL_CANONICAL_BOUNDARY


# ---------------------------------------------------------------------------
# 8. describe_contract_closure
# ---------------------------------------------------------------------------


class TestDescribeContractClosure(unittest.TestCase):
    def setUp(self) -> None:
        self.desc = describe_contract_closure()

    def test_returns_dict(self) -> None:
        assert isinstance(self.desc, dict)

    def test_json_serialisable(self) -> None:
        serialised = json.dumps(self.desc)
        assert serialised

    def test_has_authority(self) -> None:
        assert self.desc["authority"] == INTERNAL_CONTRACT_CLOSURE_AUTHORITY

    def test_has_version(self) -> None:
        assert self.desc["version"] == CONTRACT_CLOSURE_VERSION

    def test_has_layer_position(self) -> None:
        assert self.desc["layer_position"] == CONTRACT_CLOSURE_LAYER_POSITION

    def test_has_contracts(self) -> None:
        contracts = self.desc["contracts"]
        assert "internal_dispatch_contract" in contracts
        assert "internal_result_contract" in contracts
        assert "TaskEnvelope" in contracts["internal_dispatch_contract"]
        assert "ResultEnvelope" in contracts["internal_result_contract"]

    def test_has_boundaries(self) -> None:
        boundaries = self.desc["boundaries"]
        assert "public_api" in boundaries
        assert "edge_adapter" in boundaries
        assert "internal_canonical" in boundaries

    def test_has_canonical_adapters(self) -> None:
        adapters = self.desc["canonical_adapters"]
        assert isinstance(adapters, list)
        assert len(adapters) > 0
        assert "AntiCorruptionLayer" in adapters
        assert "normalize_to_task_envelope" in adapters

    def test_has_invariants(self) -> None:
        invariants = self.desc["invariants"]
        assert isinstance(invariants, list)
        assert len(invariants) > 0
        # Check that at least one invariant mentions TaskEnvelope
        combined = " ".join(invariants)
        assert "TaskEnvelope" in combined
        assert "ResultEnvelope" in combined


if __name__ == "__main__":
    unittest.main()
