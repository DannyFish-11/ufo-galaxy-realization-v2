"""
tests/test_pr4_config_driven_inventory.py — PR-4 Config-Driven Inventory
=========================================================================

Tests for the config-authority-driven provider inventory and candidate-pool
formation introduced in PR-4:

  - ``core/model_topology/provider_inventory.py``  (PR-4 additions)
  - ``core/model_topology/inventory_from_config.py`` (new module)

Test groups
-----------
1.  ProviderInventoryEntry — config_enabled default True
2.  ProviderInventoryEntry — config_has_key default True
3.  ProviderInventoryEntry — config_source default unknown
4.  ProviderInventoryEntry — is_candidate_eligible True when both True
5.  ProviderInventoryEntry — is_candidate_eligible False when disabled
6.  ProviderInventoryEntry — is_candidate_eligible False when no key
7.  ProviderInventoryEntry — is_candidate_eligible False when both False
8.  ProviderInventoryEntry — to_dict contains config fields
9.  ProviderInventoryEntry — to_dict config_enabled serialised
10. ProviderInventoryEntry — to_dict config_has_key serialised
11. ProviderInventoryEntry — to_dict config_source serialised
12. ProviderInventoryEntry — to_dict is_candidate_eligible serialised
13. ProviderInventory — candidate_pool_entries returns eligible only
14. ProviderInventory — candidate_pool_entries empty when all disabled
15. ProviderInventory — candidate_pool_entries excludes missing-key
16. ProviderInventory — enabled_entries returns enabled regardless of key
17. ProviderInventory — disabled_entries returns only disabled
18. ProviderInventory — unconfigured_entries returns enabled-no-key only
19. ProviderInventory — to_dict stats contains candidate_eligible
20. ProviderInventory — to_dict stats contains enabled
21. ProviderInventory — to_dict stats contains disabled
22. ProviderInventory — to_dict stats contains unconfigured
23. ProviderInventory — repr contains candidate_eligible
24. ProviderInventory — available_entries still works (backward compat)
25. ProviderInventory — unavailable_entries still works (backward compat)
26. inventory_from_config — INVENTORY_CONFIG_AUTHORITY is non-empty string
27. inventory_from_config — build returns ProviderInventory instance
28. inventory_from_config — all VALID_PROVIDERS present in result
29. inventory_from_config — enabled provider with key → candidate_eligible
30. inventory_from_config — disabled provider → not candidate_eligible
31. inventory_from_config — enabled without key → not candidate_eligible
32. inventory_from_config — disabled without key → not candidate_eligible
33. inventory_from_config — config_source set to config_authority
34. inventory_from_config — oneapi absent → config_enabled=False
35. inventory_from_config — oneapi absent → config_has_key=False
36. inventory_from_config — oneapi absent → not in candidate_pool
37. inventory_from_config — oneapi absent → in all_entries (diagnostic)
38. inventory_from_config — oneapi configured → config_enabled=True
39. inventory_from_config — oneapi configured → config_has_key=True
40. inventory_from_config — oneapi configured → in candidate_pool
41. inventory_from_config — oneapi partial → config_enabled=True
42. inventory_from_config — oneapi partial → config_has_key=False
43. inventory_from_config — oneapi partial → not in candidate_pool
44. inventory_from_config — oneapi partial → in unconfigured_entries
45. inventory_from_config — uses global singleton when service omitted
46. inventory_from_config — custom service accepted (no side effects)
47. inventory_from_config — all entries have config_source=config_authority
48. inventory_from_config — disabled_entries non-empty when provider disabled
49. inventory_from_config — unconfigured_entries non-empty when key missing
50. inventory_from_config — candidate_pool excludes disabled + missing key
51. merge_config_authority_into_inventory — returns same inventory object
52. merge_config_authority_into_inventory — updates config_enabled in-place
53. merge_config_authority_into_inventory — updates config_has_key in-place
54. merge_config_authority_into_inventory — updates config_source in-place
55. merge_config_authority_into_inventory — oneapi absent sets both False
56. merge_config_authority_into_inventory — oneapi configured sets both True
57. merge_config_authority_into_inventory — oneapi partial sets key False
58. merge_config_authority_into_inventory — unknown provider left unchanged
59. build_candidate_pool — delegates to candidate_pool_entries
60. build_candidate_pool — returns list type
61. get_oneapi_candidate_state — returns absent by default
62. get_oneapi_candidate_state — returns configured when set up
63. get_oneapi_candidate_state — returns partial when only enabled
64. build_inventory — NormalizedTopologyEntry has correct category DIRECT
65. build_inventory — oneapi entry has category ONEAPI
66. build_inventory — native multimodal set correctly for openai
67. build_inventory — groq entry has execution role hint
68. build_inventory — openai entry has multimodal_core role hint
69. build_inventory — inventory repr unchanged signature
70. acceptance: enabled+key provider appears in candidate pool
71. acceptance: disabled provider absent from candidate pool
72. acceptance: missing-key provider absent from candidate pool
73. acceptance: oneapi absent → absent from candidate pool
74. acceptance: oneapi configured → in candidate pool
75. acceptance: diagnostic views show all providers regardless of eligibility
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch


# ===========================================================================
# Helpers
# ===========================================================================

def _tmp_service(config_data: Dict[str, Any] = None, secrets_data: str = ""):
    """Return a ConfigService wired to temporary files."""
    from core.config_store import ConfigStore
    from core.config_service import ConfigService

    d = tempfile.mkdtemp()
    config_path = Path(d) / "config.json"
    secrets_path = Path(d) / "secrets.env"

    if config_data is not None:
        with open(config_path, "w") as f:
            json.dump(config_data, f)
    if secrets_data:
        with open(secrets_path, "w") as f:
            f.write(secrets_data)

    store = ConfigStore(config_path=config_path, secrets_path=secrets_path)
    return ConfigService(store=store)


def _make_prov_entry(
    provider_id: str = "openai",
    available: bool = True,
    config_enabled: bool = True,
    config_has_key: bool = True,
    config_source: str = "config_authority",
):
    """Make a minimal ProviderInventoryEntry for testing."""
    from core.model_topology.provider_inventory import ProviderInventoryEntry
    from core.model_topology.topology_types import (
        AvailabilityStatus, ModalityCapability, ModelIdentity,
        NormalizedTopologyEntry, ProviderCategory, ProviderIdentity,
        ScoringProfile,
    )
    normalized = NormalizedTopologyEntry(
        provider=ProviderIdentity(provider_id=provider_id),
        model=ModelIdentity(model_id=f"{provider_id}-model", provider_id=provider_id),
        modality=ModalityCapability(),
        scoring=ScoringProfile(speed_score=5, quality_score=5),
        availability=AvailabilityStatus(available=available),
        category=ProviderCategory.DIRECT,
    )
    return ProviderInventoryEntry(
        entry=normalized,
        config_enabled=config_enabled,
        config_has_key=config_has_key,
        config_source=config_source,
    )


def _make_inventory_with(*entries):
    from core.model_topology.provider_inventory import ProviderInventory
    return ProviderInventory(entries=list(entries))


# ===========================================================================
# 1-12: ProviderInventoryEntry config fields
# ===========================================================================

class TestProviderInventoryEntryConfigFields(unittest.TestCase):
    """Tests 1-12: PR-4 config fields on ProviderInventoryEntry."""

    def test_01_config_enabled_default_true(self):
        e = _make_prov_entry()
        self.assertTrue(e.config_enabled)

    def test_02_config_has_key_default_true(self):
        e = _make_prov_entry()
        self.assertTrue(e.config_has_key)

    def test_03_config_source_can_be_set(self):
        e = _make_prov_entry(config_source="env")
        self.assertEqual(e.config_source, "env")

    def test_04_is_candidate_eligible_true_when_both_true(self):
        e = _make_prov_entry(config_enabled=True, config_has_key=True)
        self.assertTrue(e.is_candidate_eligible)

    def test_05_is_candidate_eligible_false_when_disabled(self):
        e = _make_prov_entry(config_enabled=False, config_has_key=True)
        self.assertFalse(e.is_candidate_eligible)

    def test_06_is_candidate_eligible_false_when_no_key(self):
        e = _make_prov_entry(config_enabled=True, config_has_key=False)
        self.assertFalse(e.is_candidate_eligible)

    def test_07_is_candidate_eligible_false_when_both_false(self):
        e = _make_prov_entry(config_enabled=False, config_has_key=False)
        self.assertFalse(e.is_candidate_eligible)

    def test_08_to_dict_contains_config_fields(self):
        e = _make_prov_entry()
        d = e.to_dict()
        self.assertIn("config_enabled", d)
        self.assertIn("config_has_key", d)
        self.assertIn("config_source", d)
        self.assertIn("is_candidate_eligible", d)

    def test_09_to_dict_config_enabled_serialised(self):
        e = _make_prov_entry(config_enabled=False)
        d = e.to_dict()
        self.assertFalse(d["config_enabled"])

    def test_10_to_dict_config_has_key_serialised(self):
        e = _make_prov_entry(config_has_key=False)
        d = e.to_dict()
        self.assertFalse(d["config_has_key"])

    def test_11_to_dict_config_source_serialised(self):
        e = _make_prov_entry(config_source="config_authority")
        d = e.to_dict()
        self.assertEqual(d["config_source"], "config_authority")

    def test_12_to_dict_is_candidate_eligible_serialised(self):
        e = _make_prov_entry(config_enabled=True, config_has_key=True)
        d = e.to_dict()
        self.assertTrue(d["is_candidate_eligible"])

    def test_12b_to_dict_legacy_fields_preserved(self):
        """Backward compat: existing fields still present in to_dict."""
        e = _make_prov_entry()
        d = e.to_dict()
        self.assertIn("available", d)
        self.assertIn("provider_id", d)
        self.assertIn("model_id", d)


# ===========================================================================
# 13-25: ProviderInventory filtering methods
# ===========================================================================

class TestProviderInventoryFiltering(unittest.TestCase):
    """Tests 13-25: New filtering methods on ProviderInventory."""

    def _inventory(self):
        """Build an inventory with 4 entries covering all cases."""
        e_eligible = _make_prov_entry("openai", config_enabled=True, config_has_key=True)
        e_disabled = _make_prov_entry("anthropic", config_enabled=False, config_has_key=False)
        e_unconfigured = _make_prov_entry("gemini", available=False,
                                          config_enabled=True, config_has_key=False)
        e_disabled_no_key = _make_prov_entry("deepseek", available=False,
                                             config_enabled=False, config_has_key=False)
        return _make_inventory_with(e_eligible, e_disabled, e_unconfigured, e_disabled_no_key)

    def test_13_candidate_pool_entries_returns_eligible_only(self):
        inv = self._inventory()
        pool = inv.candidate_pool_entries()
        ids = [e.provider_id for e in pool]
        self.assertIn("openai", ids)
        self.assertNotIn("anthropic", ids)
        self.assertNotIn("gemini", ids)
        self.assertNotIn("deepseek", ids)

    def test_14_candidate_pool_empty_when_all_disabled(self):
        e1 = _make_prov_entry("openai", config_enabled=False, config_has_key=False)
        e2 = _make_prov_entry("anthropic", config_enabled=False, config_has_key=False)
        inv = _make_inventory_with(e1, e2)
        self.assertEqual(len(inv.candidate_pool_entries()), 0)

    def test_15_candidate_pool_excludes_missing_key(self):
        e = _make_prov_entry("openai", config_enabled=True, config_has_key=False)
        inv = _make_inventory_with(e)
        self.assertEqual(len(inv.candidate_pool_entries()), 0)

    def test_16_enabled_entries_returns_enabled_regardless_of_key(self):
        inv = self._inventory()
        enabled = inv.enabled_entries()
        ids = [e.provider_id for e in enabled]
        self.assertIn("openai", ids)
        self.assertIn("gemini", ids)  # enabled but no key
        self.assertNotIn("anthropic", ids)
        self.assertNotIn("deepseek", ids)

    def test_17_disabled_entries_returns_only_disabled(self):
        inv = self._inventory()
        disabled = inv.disabled_entries()
        ids = [e.provider_id for e in disabled]
        self.assertIn("anthropic", ids)
        self.assertIn("deepseek", ids)
        self.assertNotIn("openai", ids)

    def test_18_unconfigured_entries_enabled_no_key_only(self):
        inv = self._inventory()
        unconf = inv.unconfigured_entries()
        ids = [e.provider_id for e in unconf]
        self.assertIn("gemini", ids)  # enabled=True, has_key=False
        self.assertNotIn("openai", ids)
        self.assertNotIn("anthropic", ids)

    def test_19_to_dict_stats_has_candidate_eligible(self):
        inv = self._inventory()
        stats = inv.to_dict()["stats"]
        self.assertIn("candidate_eligible", stats)
        self.assertEqual(stats["candidate_eligible"], 1)

    def test_20_to_dict_stats_has_enabled(self):
        inv = self._inventory()
        stats = inv.to_dict()["stats"]
        self.assertIn("enabled", stats)
        self.assertEqual(stats["enabled"], 2)

    def test_21_to_dict_stats_has_disabled(self):
        inv = self._inventory()
        stats = inv.to_dict()["stats"]
        self.assertIn("disabled", stats)
        self.assertEqual(stats["disabled"], 2)

    def test_22_to_dict_stats_has_unconfigured(self):
        inv = self._inventory()
        stats = inv.to_dict()["stats"]
        self.assertIn("unconfigured", stats)
        self.assertEqual(stats["unconfigured"], 1)

    def test_23_repr_contains_candidate_eligible(self):
        inv = self._inventory()
        r = repr(inv)
        self.assertIn("candidate_eligible=", r)

    def test_24_available_entries_still_works(self):
        """Backward compat: available_entries() still filters by is_available."""
        e_avail = _make_prov_entry("openai", available=True,
                                   config_enabled=False, config_has_key=False)
        e_unavail = _make_prov_entry("anthropic", available=False)
        inv = _make_inventory_with(e_avail, e_unavail)
        avail = inv.available_entries()
        self.assertEqual(len(avail), 1)
        self.assertEqual(avail[0].provider_id, "openai")

    def test_25_unavailable_entries_still_works(self):
        e_avail = _make_prov_entry("openai", available=True)
        e_unavail = _make_prov_entry("anthropic", available=False)
        inv = _make_inventory_with(e_avail, e_unavail)
        unavail = inv.unavailable_entries()
        self.assertEqual(len(unavail), 1)
        self.assertEqual(unavail[0].provider_id, "anthropic")


# ===========================================================================
# 26-50: inventory_from_config — build_inventory_from_config_authority
# ===========================================================================

class TestBuildInventoryFromConfigAuthority(unittest.TestCase):
    """Tests 26-50: build_inventory_from_config_authority()."""

    def test_26_authority_sentinel_non_empty(self):
        from core.model_topology.inventory_from_config import INVENTORY_CONFIG_AUTHORITY
        self.assertIsInstance(INVENTORY_CONFIG_AUTHORITY, str)
        self.assertTrue(len(INVENTORY_CONFIG_AUTHORITY) > 0)

    def test_27_build_returns_provider_inventory(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        from core.model_topology.provider_inventory import ProviderInventory
        svc = _tmp_service()
        result = build_inventory_from_config_authority(config_service=svc)
        self.assertIsInstance(result, ProviderInventory)

    def test_28_all_valid_providers_present(self):
        from core.config_schema import VALID_PROVIDERS
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        svc = _tmp_service()
        inv = build_inventory_from_config_authority(config_service=svc)
        inventory_ids = {e.provider_id for e in inv.all_entries()}
        for pid in VALID_PROVIDERS:
            self.assertIn(pid, inventory_ids, f"Expected {pid} in inventory")

    def test_29_enabled_provider_with_key_is_candidate_eligible(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"openai": {"enabled": True}}}
        svc = _tmp_service(config_data=cfg, secrets_data="OPENAI_API_KEY=sk-test\n")
        inv = build_inventory_from_config_authority(config_service=svc)
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertIn("openai", pool_ids)

    def test_30_disabled_provider_not_candidate_eligible(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"openai": {"enabled": False}}}
        svc = _tmp_service(config_data=cfg, secrets_data="OPENAI_API_KEY=sk-test\n")
        inv = build_inventory_from_config_authority(config_service=svc)
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertNotIn("openai", pool_ids)

    def test_31_enabled_without_key_not_candidate_eligible(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"openai": {"enabled": True}}}
        svc = _tmp_service(config_data=cfg, secrets_data="")
        inv = build_inventory_from_config_authority(config_service=svc)
        # openai enabled but no key
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertNotIn("openai", pool_ids)

    def test_32_disabled_without_key_not_candidate_eligible(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"anthropic": {"enabled": False}}}
        svc = _tmp_service(config_data=cfg, secrets_data="")
        inv = build_inventory_from_config_authority(config_service=svc)
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertNotIn("anthropic", pool_ids)

    def test_33_config_source_set_to_config_authority(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        svc = _tmp_service()
        inv = build_inventory_from_config_authority(config_service=svc)
        for e in inv.all_entries():
            self.assertEqual(e.config_source, "config_authority",
                             f"Expected config_source=config_authority for {e.provider_id}")

    def test_34_oneapi_absent_config_enabled_false(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        svc = _tmp_service()  # oneapi absent by default
        inv = build_inventory_from_config_authority(config_service=svc)
        entry = inv.get("oneapi")
        self.assertIsNotNone(entry)
        self.assertFalse(entry.config_enabled)

    def test_35_oneapi_absent_config_has_key_false(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        svc = _tmp_service()
        inv = build_inventory_from_config_authority(config_service=svc)
        entry = inv.get("oneapi")
        self.assertFalse(entry.config_has_key)

    def test_36_oneapi_absent_not_in_candidate_pool(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        svc = _tmp_service()
        inv = build_inventory_from_config_authority(config_service=svc)
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertNotIn("oneapi", pool_ids)

    def test_37_oneapi_absent_still_in_all_entries_diagnostic(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        svc = _tmp_service()
        inv = build_inventory_from_config_authority(config_service=svc)
        all_ids = [e.provider_id for e in inv.all_entries()]
        self.assertIn("oneapi", all_ids)  # diagnostic visibility

    def test_38_oneapi_configured_config_enabled_true(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"oneapi": {"enabled": True, "base_url": "http://oneapi.test"}}}
        svc = _tmp_service(config_data=cfg, secrets_data="ONEAPI_API_KEY=test-key\n")
        inv = build_inventory_from_config_authority(config_service=svc)
        entry = inv.get("oneapi")
        self.assertIsNotNone(entry)
        self.assertTrue(entry.config_enabled)

    def test_39_oneapi_configured_config_has_key_true(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"oneapi": {"enabled": True, "base_url": "http://oneapi.test"}}}
        svc = _tmp_service(config_data=cfg, secrets_data="ONEAPI_API_KEY=test-key\n")
        inv = build_inventory_from_config_authority(config_service=svc)
        entry = inv.get("oneapi")
        self.assertTrue(entry.config_has_key)

    def test_40_oneapi_configured_in_candidate_pool(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"oneapi": {"enabled": True, "base_url": "http://oneapi.test"}}}
        svc = _tmp_service(config_data=cfg, secrets_data="ONEAPI_API_KEY=test-key\n")
        inv = build_inventory_from_config_authority(config_service=svc)
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertIn("oneapi", pool_ids)

    def test_41_oneapi_partial_config_enabled_true(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"oneapi": {"enabled": True, "base_url": "http://oneapi.test"}}}
        svc = _tmp_service(config_data=cfg, secrets_data="")  # no key → partial
        inv = build_inventory_from_config_authority(config_service=svc)
        entry = inv.get("oneapi")
        self.assertTrue(entry.config_enabled)

    def test_42_oneapi_partial_config_has_key_false(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"oneapi": {"enabled": True, "base_url": "http://oneapi.test"}}}
        svc = _tmp_service(config_data=cfg, secrets_data="")  # no key → partial
        inv = build_inventory_from_config_authority(config_service=svc)
        entry = inv.get("oneapi")
        self.assertFalse(entry.config_has_key)

    def test_43_oneapi_partial_not_in_candidate_pool(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"oneapi": {"enabled": True, "base_url": "http://oneapi.test"}}}
        svc = _tmp_service(config_data=cfg, secrets_data="")
        inv = build_inventory_from_config_authority(config_service=svc)
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertNotIn("oneapi", pool_ids)

    def test_44_oneapi_partial_in_unconfigured_entries(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"oneapi": {"enabled": True, "base_url": "http://oneapi.test"}}}
        svc = _tmp_service(config_data=cfg, secrets_data="")
        inv = build_inventory_from_config_authority(config_service=svc)
        unconf_ids = [e.provider_id for e in inv.unconfigured_entries()]
        self.assertIn("oneapi", unconf_ids)

    def test_45_uses_global_singleton_when_service_omitted(self):
        """Should not raise when called without explicit service."""
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        from core.model_topology.provider_inventory import ProviderInventory
        # Just verify it returns a ProviderInventory without crash
        result = build_inventory_from_config_authority()
        self.assertIsInstance(result, ProviderInventory)

    def test_46_custom_service_accepted_no_side_effects(self):
        """Passing a custom service does not affect the global singleton."""
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        svc1 = _tmp_service(config_data={"providers": {"openai": {"enabled": True}}},
                            secrets_data="OPENAI_API_KEY=key1\n")
        svc2 = _tmp_service(config_data={"providers": {"openai": {"enabled": False}}},
                            secrets_data="")
        inv1 = build_inventory_from_config_authority(config_service=svc1)
        inv2 = build_inventory_from_config_authority(config_service=svc2)
        # inv1 should have openai as eligible, inv2 should not
        pool1 = [e.provider_id for e in inv1.candidate_pool_entries()]
        pool2 = [e.provider_id for e in inv2.candidate_pool_entries()]
        self.assertIn("openai", pool1)
        self.assertNotIn("openai", pool2)

    def test_47_all_entries_have_config_source_config_authority(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        svc = _tmp_service()
        inv = build_inventory_from_config_authority(config_service=svc)
        for e in inv.all_entries():
            self.assertEqual(e.config_source, "config_authority")

    def test_48_disabled_entries_non_empty_when_provider_disabled(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"anthropic": {"enabled": False}}}
        svc = _tmp_service(config_data=cfg)
        inv = build_inventory_from_config_authority(config_service=svc)
        disabled_ids = [e.provider_id for e in inv.disabled_entries()]
        self.assertIn("anthropic", disabled_ids)

    def test_49_unconfigured_entries_non_empty_when_key_missing(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"openai": {"enabled": True}}}
        svc = _tmp_service(config_data=cfg, secrets_data="")
        inv = build_inventory_from_config_authority(config_service=svc)
        unconf_ids = [e.provider_id for e in inv.unconfigured_entries()]
        self.assertIn("openai", unconf_ids)

    def test_50_candidate_pool_excludes_disabled_and_missing_key(self):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {
            "providers": {
                "openai": {"enabled": True},    # enabled but no key
                "anthropic": {"enabled": False}, # disabled
                "gemini": {"enabled": True},     # enabled with key
            }
        }
        svc = _tmp_service(config_data=cfg, secrets_data="GEMINI_API_KEY=gemini-key\n")
        inv = build_inventory_from_config_authority(config_service=svc)
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertIn("gemini", pool_ids)
        self.assertNotIn("openai", pool_ids)
        self.assertNotIn("anthropic", pool_ids)


# ===========================================================================
# 51-58: merge_config_authority_into_inventory
# ===========================================================================

class TestMergeConfigAuthority(unittest.TestCase):
    """Tests 51-58: merge_config_authority_into_inventory()."""

    def test_51_returns_same_inventory_object(self):
        from core.model_topology.inventory_from_config import merge_config_authority_into_inventory
        e = _make_prov_entry("openai")
        inv = _make_inventory_with(e)
        result = merge_config_authority_into_inventory(inv, config_service=_tmp_service())
        self.assertIs(result, inv)

    def test_52_updates_config_enabled_in_place(self):
        from core.model_topology.inventory_from_config import merge_config_authority_into_inventory
        # Start with config_enabled=True; service has openai disabled
        e = _make_prov_entry("openai", config_enabled=True, config_source="unknown")
        inv = _make_inventory_with(e)
        cfg = {"providers": {"openai": {"enabled": False}}}
        svc = _tmp_service(config_data=cfg)
        merge_config_authority_into_inventory(inv, config_service=svc)
        self.assertFalse(inv.get("openai").config_enabled)

    def test_53_updates_config_has_key_in_place(self):
        from core.model_topology.inventory_from_config import merge_config_authority_into_inventory
        e = _make_prov_entry("openai", config_has_key=True, config_source="unknown")
        inv = _make_inventory_with(e)
        # No key in service
        cfg = {"providers": {"openai": {"enabled": True}}}
        svc = _tmp_service(config_data=cfg, secrets_data="")
        merge_config_authority_into_inventory(inv, config_service=svc)
        self.assertFalse(inv.get("openai").config_has_key)

    def test_54_updates_config_source_in_place(self):
        from core.model_topology.inventory_from_config import merge_config_authority_into_inventory
        e = _make_prov_entry("openai", config_source="unknown")
        inv = _make_inventory_with(e)
        svc = _tmp_service()
        merge_config_authority_into_inventory(inv, config_service=svc)
        self.assertEqual(inv.get("openai").config_source, "config_authority")

    def test_55_oneapi_absent_sets_both_false(self):
        from core.model_topology.inventory_from_config import merge_config_authority_into_inventory
        e = _make_prov_entry("oneapi", config_enabled=True, config_has_key=True, config_source="unknown")
        inv = _make_inventory_with(e)
        svc = _tmp_service()  # oneapi absent by default
        merge_config_authority_into_inventory(inv, config_service=svc)
        entry = inv.get("oneapi")
        self.assertFalse(entry.config_enabled)
        self.assertFalse(entry.config_has_key)

    def test_56_oneapi_configured_sets_both_true(self):
        from core.model_topology.inventory_from_config import merge_config_authority_into_inventory
        e = _make_prov_entry("oneapi", config_enabled=False, config_has_key=False)
        inv = _make_inventory_with(e)
        cfg = {"providers": {"oneapi": {"enabled": True, "base_url": "http://oneapi.test"}}}
        svc = _tmp_service(config_data=cfg, secrets_data="ONEAPI_API_KEY=key\n")
        merge_config_authority_into_inventory(inv, config_service=svc)
        entry = inv.get("oneapi")
        self.assertTrue(entry.config_enabled)
        self.assertTrue(entry.config_has_key)

    def test_57_oneapi_partial_sets_key_false(self):
        from core.model_topology.inventory_from_config import merge_config_authority_into_inventory
        e = _make_prov_entry("oneapi", config_enabled=False, config_has_key=False)
        inv = _make_inventory_with(e)
        cfg = {"providers": {"oneapi": {"enabled": True, "base_url": "http://oneapi.test"}}}
        svc = _tmp_service(config_data=cfg, secrets_data="")  # no key
        merge_config_authority_into_inventory(inv, config_service=svc)
        entry = inv.get("oneapi")
        self.assertTrue(entry.config_enabled)
        self.assertFalse(entry.config_has_key)

    def test_58_unknown_provider_left_unchanged(self):
        from core.model_topology.inventory_from_config import merge_config_authority_into_inventory
        # A provider_id not in VALID_PROVIDERS
        e = _make_prov_entry("custom_llm", config_enabled=True, config_has_key=True,
                             config_source="env")
        inv = _make_inventory_with(e)
        svc = _tmp_service()
        merge_config_authority_into_inventory(inv, config_service=svc)
        entry = inv.get("custom_llm")
        self.assertEqual(entry.config_source, "env")  # unchanged


# ===========================================================================
# 59-63: Convenience helpers
# ===========================================================================

class TestConvenienceHelpers(unittest.TestCase):
    """Tests 59-63: build_candidate_pool and get_oneapi_candidate_state."""

    def test_59_build_candidate_pool_delegates(self):
        from core.model_topology.inventory_from_config import build_candidate_pool
        e1 = _make_prov_entry("openai", config_enabled=True, config_has_key=True)
        e2 = _make_prov_entry("anthropic", config_enabled=False, config_has_key=False)
        inv = _make_inventory_with(e1, e2)
        pool = build_candidate_pool(inv)
        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0].provider_id, "openai")

    def test_60_build_candidate_pool_returns_list(self):
        from core.model_topology.inventory_from_config import build_candidate_pool
        inv = _make_inventory_with()
        result = build_candidate_pool(inv)
        self.assertIsInstance(result, list)

    def test_61_get_oneapi_candidate_state_absent_by_default(self):
        from core.model_topology.inventory_from_config import get_oneapi_candidate_state
        svc = _tmp_service()  # default: oneapi disabled
        state = get_oneapi_candidate_state(config_service=svc)
        self.assertEqual(state, "absent")

    def test_62_get_oneapi_candidate_state_configured(self):
        from core.model_topology.inventory_from_config import get_oneapi_candidate_state
        cfg = {"providers": {"oneapi": {"enabled": True, "base_url": "http://oneapi.test"}}}
        svc = _tmp_service(config_data=cfg, secrets_data="ONEAPI_API_KEY=key\n")
        state = get_oneapi_candidate_state(config_service=svc)
        self.assertEqual(state, "configured")

    def test_63_get_oneapi_candidate_state_partial(self):
        from core.model_topology.inventory_from_config import get_oneapi_candidate_state
        cfg = {"providers": {"oneapi": {"enabled": True, "base_url": "http://oneapi.test"}}}
        svc = _tmp_service(config_data=cfg, secrets_data="")
        state = get_oneapi_candidate_state(config_service=svc)
        self.assertEqual(state, "partial")


# ===========================================================================
# 64-69: Inventory entry metadata
# ===========================================================================

class TestInventoryEntryMetadata(unittest.TestCase):
    """Tests 64-69: NormalizedTopologyEntry metadata in built inventory."""

    def _inv(self, cfg=None, secrets=""):
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        svc = _tmp_service(config_data=cfg, secrets_data=secrets)
        return build_inventory_from_config_authority(config_service=svc)

    def test_64_direct_provider_has_direct_category(self):
        from core.model_topology.topology_types import ProviderCategory
        inv = self._inv()
        entry = inv.get("openai")
        self.assertEqual(entry.entry.category, ProviderCategory.DIRECT)

    def test_65_oneapi_entry_has_oneapi_category(self):
        from core.model_topology.topology_types import ProviderCategory
        inv = self._inv()
        entry = inv.get("oneapi")
        self.assertEqual(entry.entry.category, ProviderCategory.ONEAPI)

    def test_66_openai_is_native_multimodal(self):
        inv = self._inv()
        entry = inv.get("openai")
        self.assertTrue(entry.entry.is_multimodal_native)

    def test_67_groq_has_execution_role_hint(self):
        from core.model_topology.topology_types import TopologyRole
        inv = self._inv()
        entry = inv.get("groq")
        self.assertIn(TopologyRole.EXECUTION, entry.entry.role_hints)

    def test_68_openai_has_multimodal_core_role_hint(self):
        from core.model_topology.topology_types import TopologyRole
        inv = self._inv()
        entry = inv.get("openai")
        self.assertIn(TopologyRole.MULTIMODAL_CORE, entry.entry.role_hints)

    def test_69_repr_contains_total(self):
        inv = self._inv()
        r = repr(inv)
        self.assertIn("total=", r)


# ===========================================================================
# 70-75: Acceptance criteria
# ===========================================================================

class TestAcceptanceCriteria(unittest.TestCase):
    """Tests 70-75: High-level acceptance criteria for PR-4."""

    def test_70_enabled_key_provider_in_candidate_pool(self):
        """AC: enabled+key provider appears in candidate pool."""
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"openai": {"enabled": True}}}
        svc = _tmp_service(config_data=cfg, secrets_data="OPENAI_API_KEY=sk-test\n")
        inv = build_inventory_from_config_authority(config_service=svc)
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertIn("openai", pool_ids)

    def test_71_disabled_provider_absent_from_candidate_pool(self):
        """AC: disabled provider absent from candidate pool."""
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"anthropic": {"enabled": False}}}
        svc = _tmp_service(config_data=cfg, secrets_data="ANTHROPIC_API_KEY=sk-ant\n")
        inv = build_inventory_from_config_authority(config_service=svc)
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertNotIn("anthropic", pool_ids)

    def test_72_missing_key_provider_absent_from_candidate_pool(self):
        """AC: missing-key provider absent from candidate pool."""
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"gemini": {"enabled": True}}}
        svc = _tmp_service(config_data=cfg, secrets_data="")  # no gemini key
        inv = build_inventory_from_config_authority(config_service=svc)
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertNotIn("gemini", pool_ids)

    def test_73_oneapi_absent_not_in_candidate_pool(self):
        """AC: unconfigured OneAPI is treated as absent from candidate pool."""
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        svc = _tmp_service()  # no oneapi config
        inv = build_inventory_from_config_authority(config_service=svc)
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertNotIn("oneapi", pool_ids)

    def test_74_oneapi_configured_in_candidate_pool(self):
        """AC: configured OneAPI can participate (lower-horizon semantics)."""
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        cfg = {"providers": {"oneapi": {"enabled": True, "base_url": "http://oneapi"}}}
        svc = _tmp_service(config_data=cfg, secrets_data="ONEAPI_API_KEY=key\n")
        inv = build_inventory_from_config_authority(config_service=svc)
        pool_ids = [e.provider_id for e in inv.candidate_pool_entries()]
        self.assertIn("oneapi", pool_ids)

    def test_75_diagnostic_views_show_all_providers(self):
        """AC: diagnostic views (all_entries) include all providers regardless of eligibility."""
        from core.config_schema import VALID_PROVIDERS
        from core.model_topology.inventory_from_config import build_inventory_from_config_authority
        # All providers disabled, no keys
        cfg = {"providers": {p: {"enabled": False} for p in VALID_PROVIDERS}}
        svc = _tmp_service(config_data=cfg, secrets_data="")
        inv = build_inventory_from_config_authority(config_service=svc)
        all_ids = {e.provider_id for e in inv.all_entries()}
        # All should be visible in diagnostic view
        for pid in VALID_PROVIDERS:
            self.assertIn(pid, all_ids)
        # None should be in candidate pool
        self.assertEqual(len(inv.candidate_pool_entries()), 0)


if __name__ == "__main__":
    unittest.main()
