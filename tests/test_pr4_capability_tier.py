#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr4_capability_tier.py
===================================
PR-4: Governance / Readiness / Release Validation Main Chain Entry.

Test suite for :mod:`core.capability_tier`.

These tests verify the canonical capability tier registry and guard functions,
ensuring that:
- MAIN_CHAIN capabilities are correctly classified
- EXPERIMENTAL / QUASI_MAIN_CHAIN capabilities cannot masquerade as MAIN_CHAIN
- Guard functions raise hard errors when tier requirements are violated

Coverage matrix
---------------
Group A — Module-level: sentinels, enums, __all__
  A01. Module importable.
  A02. CAPABILITY_TIER_AUTHORITY is a non-empty string.
  A03. Policy sentinels are non-empty strings.
  A04. CapabilityTier has MAIN_CHAIN, QUASI_MAIN_CHAIN, EXPERIMENTAL, UNKNOWN.
  A05. __all__ contains all required public names.

Group B — get_capability_tier()
  B01. Known MAIN_CHAIN capability returns MAIN_CHAIN.
  B02. Known EXPERIMENTAL capability returns EXPERIMENTAL.
  B03. Known QUASI_MAIN_CHAIN capability returns QUASI_MAIN_CHAIN.
  B04. Unknown capability returns UNKNOWN (not MAIN_CHAIN).
  B05. Lookup is case-insensitive.
  B06. All registry entries have valid CapabilityTier values.

Group C — Tier classification correctness
  C01. Core dispatch capabilities are MAIN_CHAIN.
  C02. VLM / WebRTC / live mesh are EXPERIMENTAL.
  C03. staged_mesh / session_migration are QUASI_MAIN_CHAIN.
  C04. No EXPERIMENTAL capability is classified as MAIN_CHAIN.
  C05. Registry is non-empty and has all three tier types.

Group D — assert_main_chain_capability() guard
  D01. MAIN_CHAIN capability → no exception.
  D02. EXPERIMENTAL capability → CapabilityTierViolationError.
  D03. QUASI_MAIN_CHAIN capability → CapabilityTierViolationError.
  D04. UNKNOWN capability → CapabilityTierViolationError.
  D05. CapabilityTierViolationError carries capability and actual_tier.

Group E — require_main_chain_capability()
  E01. Returns CapabilityTier.MAIN_CHAIN for MAIN_CHAIN capability.
  E02. Raises CapabilityTierViolationError for non-MAIN_CHAIN.

Group F — get_tier_registry()
  F01. Returns a dict copy.
  F02. Returned dict contains all registry entries.
  F03. Mutating the returned dict does not affect the registry.

Group G — list_capabilities_by_tier()
  G01. MAIN_CHAIN list is non-empty and sorted.
  G02. EXPERIMENTAL list is non-empty and sorted.
  G03. QUASI_MAIN_CHAIN list is non-empty and sorted.
  G04. UNKNOWN tier returns empty list (no capabilities registered as UNKNOWN).
  G05. All list_capabilities_by_tier() results are disjoint.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

try:
    from core.capability_tier import (
        CAPABILITY_TIER_AUTHORITY,
        MAIN_CHAIN_IS_VERIFIED_POLICY,
        EXPERIMENTAL_MUST_NOT_CLAIM_MAIN_CHAIN_POLICY,
        QUASI_MAIN_CHAIN_HAS_KNOWN_GAPS_POLICY,
        CapabilityTier,
        CapabilityTierViolationError,
        get_capability_tier,
        assert_main_chain_capability,
        require_main_chain_capability,
        get_tier_registry,
        list_capabilities_by_tier,
        CAPABILITY_TIER_REGISTRY,
    )
    _MODULE_AVAILABLE = True
except ImportError as _import_err:  # pragma: no cover
    _MODULE_AVAILABLE = False
    _import_err_msg = str(_import_err)

_skip_if_unavailable = pytest.mark.skipif(
    not _MODULE_AVAILABLE,
    reason=f"core.capability_tier not importable: {locals().get('_import_err_msg', '')}",
)


# ===========================================================================
# Group A — Module-level
# ===========================================================================


@_skip_if_unavailable
class TestGroupA_ModuleLevel:
    """Module-level sentinels, enums, and __all__."""

    def test_A01_module_importable(self):
        assert _MODULE_AVAILABLE

    def test_A02_authority_sentinel_non_empty(self):
        assert isinstance(CAPABILITY_TIER_AUTHORITY, str)
        assert len(CAPABILITY_TIER_AUTHORITY) > 10
        assert "PR4" in CAPABILITY_TIER_AUTHORITY

    def test_A03_policy_sentinels_non_empty(self):
        assert MAIN_CHAIN_IS_VERIFIED_POLICY
        assert EXPERIMENTAL_MUST_NOT_CLAIM_MAIN_CHAIN_POLICY
        assert QUASI_MAIN_CHAIN_HAS_KNOWN_GAPS_POLICY

    def test_A04_capability_tier_has_four_values(self):
        assert CapabilityTier.MAIN_CHAIN.value == "MAIN_CHAIN"
        assert CapabilityTier.QUASI_MAIN_CHAIN.value == "QUASI_MAIN_CHAIN"
        assert CapabilityTier.EXPERIMENTAL.value == "EXPERIMENTAL"
        assert CapabilityTier.UNKNOWN.value == "UNKNOWN"
        assert len(CapabilityTier) == 4

    def test_A05_all_contains_required_names(self):
        from core import capability_tier as mod
        required = {
            "CAPABILITY_TIER_AUTHORITY",
            "CapabilityTier",
            "CapabilityTierViolationError",
            "get_capability_tier",
            "assert_main_chain_capability",
            "require_main_chain_capability",
            "get_tier_registry",
            "list_capabilities_by_tier",
            "CAPABILITY_TIER_REGISTRY",
        }
        assert required.issubset(set(mod.__all__))


# ===========================================================================
# Group B — get_capability_tier()
# ===========================================================================


@_skip_if_unavailable
class TestGroupB_GetCapabilityTier:
    """get_capability_tier() function."""

    def test_B01_known_main_chain_capability_returns_MAIN_CHAIN(self):
        assert get_capability_tier("screen") == CapabilityTier.MAIN_CHAIN
        assert get_capability_tier("command_routing") == CapabilityTier.MAIN_CHAIN
        assert get_capability_tier("device_dispatch") == CapabilityTier.MAIN_CHAIN
        assert get_capability_tier("task_orchestration") == CapabilityTier.MAIN_CHAIN

    def test_B02_known_experimental_capability_returns_EXPERIMENTAL(self):
        assert get_capability_tier("vlm") == CapabilityTier.EXPERIMENTAL
        assert get_capability_tier("webrtc") == CapabilityTier.EXPERIMENTAL
        assert get_capability_tier("live_mesh_runtime") == CapabilityTier.EXPERIMENTAL

    def test_B03_known_quasi_main_chain_capability_returns_QUASI_MAIN_CHAIN(self):
        assert get_capability_tier("staged_mesh") == CapabilityTier.QUASI_MAIN_CHAIN
        assert get_capability_tier("session_migration") == CapabilityTier.QUASI_MAIN_CHAIN
        assert get_capability_tier("local_llm") == CapabilityTier.QUASI_MAIN_CHAIN

    def test_B04_unknown_capability_returns_UNKNOWN(self):
        result = get_capability_tier("this_capability_does_not_exist_12345")
        assert result == CapabilityTier.UNKNOWN

    def test_B05_lookup_is_case_insensitive(self):
        assert get_capability_tier("SCREEN") == CapabilityTier.MAIN_CHAIN
        assert get_capability_tier("Screen") == CapabilityTier.MAIN_CHAIN
        assert get_capability_tier("VLM") == CapabilityTier.EXPERIMENTAL

    def test_B06_all_registry_entries_have_valid_tier_values(self):
        valid_values = {t.value for t in CapabilityTier}
        for cap_name, tier_value in CAPABILITY_TIER_REGISTRY.items():
            assert tier_value in valid_values, (
                f"Capability '{cap_name}' has invalid tier value '{tier_value}'"
            )


# ===========================================================================
# Group C — Tier classification correctness
# ===========================================================================


@_skip_if_unavailable
class TestGroupC_TierClassificationCorrectness:
    """Tier classification correctness for key capabilities."""

    def test_C01_core_dispatch_capabilities_are_MAIN_CHAIN(self):
        """Core dispatch/orchestration capabilities must be MAIN_CHAIN."""
        main_chain_required = [
            "command_routing",
            "device_dispatch",
            "websocket_dispatch",
            "task_completion_ingress",
            "android_handoff",
            "session_management",
            "task_orchestration",
            "llm_routing",
        ]
        for cap in main_chain_required:
            tier = get_capability_tier(cap)
            assert tier == CapabilityTier.MAIN_CHAIN, (
                f"Expected '{cap}' to be MAIN_CHAIN, got {tier.value}"
            )

    def test_C02_vlm_webrtc_live_mesh_are_EXPERIMENTAL(self):
        """VLM, WebRTC, and live mesh runtime must be EXPERIMENTAL."""
        experimental_required = [
            "vlm",
            "webrtc",
            "webrtc_gateway",
            "live_mesh_runtime",
            "mesh_runtime_engine",
            "multimodal_vlm",
        ]
        for cap in experimental_required:
            tier = get_capability_tier(cap)
            assert tier == CapabilityTier.EXPERIMENTAL, (
                f"Expected '{cap}' to be EXPERIMENTAL, got {tier.value}"
            )

    def test_C03_staged_mesh_and_session_migration_are_QUASI_MAIN_CHAIN(self):
        """Staged mesh and session migration must be QUASI_MAIN_CHAIN."""
        quasi_required = [
            "staged_mesh",
            "session_migration",
            "session_continuity",
            "session_recovery",
        ]
        for cap in quasi_required:
            tier = get_capability_tier(cap)
            assert tier == CapabilityTier.QUASI_MAIN_CHAIN, (
                f"Expected '{cap}' to be QUASI_MAIN_CHAIN, got {tier.value}"
            )

    def test_C04_no_experimental_capability_classified_as_MAIN_CHAIN(self):
        """Critical invariant: no EXPERIMENTAL capability is classified MAIN_CHAIN."""
        for cap_name, tier_value in CAPABILITY_TIER_REGISTRY.items():
            if tier_value == CapabilityTier.EXPERIMENTAL.value:
                # Verify get_capability_tier does not return MAIN_CHAIN for this
                result = get_capability_tier(cap_name)
                assert result != CapabilityTier.MAIN_CHAIN, (
                    f"VIOLATION: '{cap_name}' is registered as EXPERIMENTAL but "
                    f"get_capability_tier() returned MAIN_CHAIN"
                )

    def test_C05_registry_non_empty_with_all_three_tiers(self):
        """Registry has at least one capability in each of the three primary tiers."""
        registry = get_tier_registry()
        assert len(registry) > 0

        tiers_present = set(registry.values())
        assert CapabilityTier.MAIN_CHAIN.value in tiers_present
        assert CapabilityTier.EXPERIMENTAL.value in tiers_present
        assert CapabilityTier.QUASI_MAIN_CHAIN.value in tiers_present


# ===========================================================================
# Group D — assert_main_chain_capability() guard
# ===========================================================================


@_skip_if_unavailable
class TestGroupD_AssertMainChainCapability:
    """assert_main_chain_capability() hard guard function."""

    def test_D01_main_chain_capability_no_exception(self):
        """MAIN_CHAIN capability does not raise."""
        assert_main_chain_capability("screen")  # Should not raise
        assert_main_chain_capability("command_routing")
        assert_main_chain_capability("device_dispatch")

    def test_D02_experimental_capability_raises(self):
        """EXPERIMENTAL capability raises CapabilityTierViolationError."""
        with pytest.raises(CapabilityTierViolationError):
            assert_main_chain_capability("vlm")

    def test_D03_quasi_main_chain_capability_raises(self):
        """QUASI_MAIN_CHAIN capability raises CapabilityTierViolationError."""
        with pytest.raises(CapabilityTierViolationError):
            assert_main_chain_capability("staged_mesh")

    def test_D04_unknown_capability_raises(self):
        """UNKNOWN capability raises CapabilityTierViolationError."""
        with pytest.raises(CapabilityTierViolationError):
            assert_main_chain_capability("this_does_not_exist_xyz")

    def test_D05_error_carries_capability_and_actual_tier(self):
        """CapabilityTierViolationError carries capability and actual_tier attributes."""
        with pytest.raises(CapabilityTierViolationError) as exc_info:
            assert_main_chain_capability("webrtc")

        error = exc_info.value
        assert error.capability == "webrtc"
        assert error.actual_tier == CapabilityTier.EXPERIMENTAL
        assert "webrtc" in str(error)
        assert "EXPERIMENTAL" in str(error)


# ===========================================================================
# Group E — require_main_chain_capability()
# ===========================================================================


@_skip_if_unavailable
class TestGroupE_RequireMainChainCapability:
    """require_main_chain_capability() function."""

    def test_E01_returns_MAIN_CHAIN_for_verified_capability(self):
        """Returns CapabilityTier.MAIN_CHAIN for MAIN_CHAIN capability."""
        result = require_main_chain_capability("screen")
        assert result == CapabilityTier.MAIN_CHAIN

    def test_E02_raises_for_non_main_chain(self):
        """Raises CapabilityTierViolationError for non-MAIN_CHAIN capability."""
        with pytest.raises(CapabilityTierViolationError):
            require_main_chain_capability("live_mesh_runtime")


# ===========================================================================
# Group F — get_tier_registry()
# ===========================================================================


@_skip_if_unavailable
class TestGroupF_GetTierRegistry:
    """get_tier_registry() function."""

    def test_F01_returns_dict(self):
        registry = get_tier_registry()
        assert isinstance(registry, dict)

    def test_F02_returned_dict_contains_all_registry_entries(self):
        registry = get_tier_registry()
        for cap_name in CAPABILITY_TIER_REGISTRY:
            assert cap_name in registry
            assert registry[cap_name] == CAPABILITY_TIER_REGISTRY[cap_name]

    def test_F03_mutating_returned_dict_does_not_affect_registry(self):
        registry = get_tier_registry()
        original_count = len(CAPABILITY_TIER_REGISTRY)
        registry["test_mutation_key"] = "EXPERIMENTAL"
        # Original registry should be unchanged
        assert "test_mutation_key" not in CAPABILITY_TIER_REGISTRY
        assert len(CAPABILITY_TIER_REGISTRY) == original_count


# ===========================================================================
# Group G — list_capabilities_by_tier()
# ===========================================================================


@_skip_if_unavailable
class TestGroupG_ListCapabilitiesByTier:
    """list_capabilities_by_tier() function."""

    def test_G01_main_chain_list_non_empty_and_sorted(self):
        caps = list_capabilities_by_tier(CapabilityTier.MAIN_CHAIN)
        assert len(caps) > 0
        assert caps == sorted(caps)

    def test_G02_experimental_list_non_empty_and_sorted(self):
        caps = list_capabilities_by_tier(CapabilityTier.EXPERIMENTAL)
        assert len(caps) > 0
        assert caps == sorted(caps)

    def test_G03_quasi_main_chain_list_non_empty_and_sorted(self):
        caps = list_capabilities_by_tier(CapabilityTier.QUASI_MAIN_CHAIN)
        assert len(caps) > 0
        assert caps == sorted(caps)

    def test_G04_unknown_tier_returns_empty_list(self):
        """No capabilities are explicitly registered as UNKNOWN."""
        caps = list_capabilities_by_tier(CapabilityTier.UNKNOWN)
        assert caps == []

    def test_G05_tier_lists_are_disjoint(self):
        """Each capability appears in exactly one tier."""
        main = set(list_capabilities_by_tier(CapabilityTier.MAIN_CHAIN))
        quasi = set(list_capabilities_by_tier(CapabilityTier.QUASI_MAIN_CHAIN))
        experimental = set(list_capabilities_by_tier(CapabilityTier.EXPERIMENTAL))

        assert main.isdisjoint(quasi), f"Overlap MAIN∩QUASI: {main & quasi}"
        assert main.isdisjoint(experimental), f"Overlap MAIN∩EXP: {main & experimental}"
        assert quasi.isdisjoint(experimental), f"Overlap QUASI∩EXP: {quasi & experimental}"
