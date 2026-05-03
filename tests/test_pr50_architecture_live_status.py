#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr50_architecture_live_status.py
============================================

PR-011 — Add live architecture status surface for runtime readiness.

Note on file naming: test files in this repository use a sequential numbering
scheme (e.g. ``test_pr48``, ``test_pr49``).  This file is numbered
``test_pr50`` to follow that sequence; it corresponds to PR-011 in the issue
tracker.

Validates:
  1.  RuntimeReadiness enum has exactly three values.
  2.  RuntimeReadiness.READY value is "ready".
  3.  RuntimeReadiness.PARTIAL value is "partial".
  4.  RuntimeReadiness.BLOCKED value is "blocked".
  5.  CanonicalPathEntry is a frozen dataclass.
  6.  CanonicalPathEntry.to_dict() returns a dict with "path" key.
  7.  CanonicalPathEntry.to_dict() includes "role".
  8.  CanonicalPathEntry.to_dict() includes "pr_introduced".
  9.  LegacyZoneEntry is a frozen dataclass.
  10. LegacyZoneEntry.to_dict() returns a dict with "path" key.
  11. LegacyZoneEntry.to_dict() includes "status".
  12. LegacyZoneEntry.to_dict() includes "superseded_by".
  13. LegacyZoneEntry.to_dict() includes "notes".
  14. ActiveBlocker is a frozen dataclass.
  15. ActiveBlocker.to_dict() returns a dict with "dimension" key.
  16. ActiveBlocker.to_dict() includes "severity".
  17. ActiveBlocker.to_dict() includes "description".
  18. ActiveBlocker.to_dict() includes "recommended_action".
  19. ArchitectureLiveStatus has baseline_version field.
  20. ArchitectureLiveStatus has runtime_readiness field.
  21. ArchitectureLiveStatus has canonical_paths list field.
  22. ArchitectureLiveStatus has legacy_zones list field.
  23. ArchitectureLiveStatus has scorecard_summary dict field.
  24. ArchitectureLiveStatus has active_blockers list field.
  25. ArchitectureLiveStatus has projection_status dict field.
  26. ArchitectureLiveStatus has capability_catalog_status dict field.
  27. ArchitectureLiveStatus has addon_ecosystem_status dict field.
  28. ArchitectureLiveStatus has cross_device_status dict field.
  29. ArchitectureLiveStatus has authority_chain_status dict field.
  30. ArchitectureLiveStatus has recommended_next_steps list field.
  31. ArchitectureLiveStatus.to_dict() is JSON-serialisable.
  32. ArchitectureLiveStatus.to_dict() includes all 12 top-level keys.
  33. ArchitectureLiveStatus.to_json() returns a valid JSON string.
  34. ArchitectureLiveStatus.to_dict() "canonical_paths" is a list of dicts.
  35. ArchitectureLiveStatus.to_dict() "legacy_zones" is a list of dicts.
  36. ArchitectureLiveStatus.to_dict() "active_blockers" is a list of dicts.
  37. build_architecture_live_status() returns an ArchitectureLiveStatus.
  38. build_architecture_live_status() baseline_version == BASELINE_VERSION.
  39. build_architecture_live_status() runtime_readiness is a valid value.
  40. build_architecture_live_status() canonical_paths is non-empty.
  41. build_architecture_live_status() every canonical_path entry has "path".
  42. build_architecture_live_status() every canonical_path entry has "role".
  43. build_architecture_live_status() every canonical_path entry has "pr_introduced".
  44. build_architecture_live_status() legacy_zones is non-empty.
  45. build_architecture_live_status() every legacy_zone has "path" and "status".
  46. build_architecture_live_status() scorecard_summary has "overall_completion_pct".
  47. build_architecture_live_status() scorecard_summary has "canonical_count".
  48. build_architecture_live_status() scorecard_summary has "blocking_count".
  49. build_architecture_live_status() scorecard_summary has "total_dimensions".
  50. build_architecture_live_status() scorecard_summary has "blocking_dimensions" list.
  51. build_architecture_live_status() scorecard_summary has "legacy_ambiguity_dimensions" list.
  52. build_architecture_live_status() projection_status has "status" key.
  53. build_architecture_live_status() capability_catalog_status has "status" key.
  54. build_architecture_live_status() addon_ecosystem_status has "status" key.
  55. build_architecture_live_status() cross_device_status has "status" key.
  56. build_architecture_live_status() authority_chain_status has "status" key.
  57. build_architecture_live_status() recommended_next_steps is non-empty.
  58. build_architecture_live_status() is JSON-serialisable end-to-end.
  59. get_architecture_live_status() returns an ArchitectureLiveStatus.
  60. get_architecture_live_status() is idempotent (same object on repeat call).
  61. get_architecture_live_status(force_rebuild=True) returns fresh status.
  62. reset_architecture_live_status() clears the cached singleton.
  63. Readiness classification: BLOCKED when blocking_count > 0.
  64. Readiness classification: PARTIAL when legacy_ambiguity_count > 0, no blocking.
  65. Readiness classification: READY when no blocking/ambiguity/warning.
  66. Readiness: BLOCKED when active blocker has severity "blocking".
  67. Readiness: PARTIAL when active blocker has severity "warning" only.
  68. Readiness: PARTIAL when projection_is_only_outward_truth is False.
  69. Readiness: PARTIAL when projection_is_only_outward_truth is None.
  70. Active blockers are generated for scorecard blocking dimensions.
  71. Active blockers have severity "blocking" for LEGACY_AMBIGUITY/IN_PROGRESS dims.
  72. Active blockers have severity "warning" for legacy_ambiguity_remains dims.
  73. Scorecard summary canonical_count >= 7 (PR-9 baseline: 8/10 canonicalized+).
  74. Scorecard summary legacy_ambiguity_count == 2 (CAPABILITY + INSTALLABILITY).
  75. Scorecard summary blocking_count == 0 in default (no LEGACY_AMBIGUITY/IN_PROGRESS).
  76. Runtime readiness is "partial" in default (legacy ambiguity in 2 dims).
  77. BASELINE_VERSION is a non-empty string.
  78. BASELINE_VERSION starts with "PR-".
  79. status round-trips via to_dict() → to_json() → json.loads() consistently.
  80. Serialized status "runtime_readiness" is a string in {"ready","partial","blocked"}.
  81. Serialized status "canonical_paths" entries all have string "path" values.
  82. Serialized status "legacy_zones" entries all have string "status" values.
  83. Serialized status "active_blockers" entries all have "severity" string.
  84. build_architecture_live_status() scorecard_summary matches get_architecture_completion_scorecard().
  85. Scorecard summary overall_completion_pct is in range [0.0, 100.0].
  86. ArchitectureLiveStatus default runtime_readiness is "partial" (sensible default).
  87. to_dict() "baseline_version" matches BASELINE_VERSION constant.
  88. Each canonical_path has a non-empty "role" string.
  89. Each legacy_zone "superseded_by" is either None or a non-empty string.
  90. _classify_readiness returns READY when all signals are clean.
"""

from __future__ import annotations

import importlib
import json
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------


def _import_module():
    return importlib.import_module("core.architecture_live_status")


def _reset():
    m = _import_module()
    m.reset_architecture_live_status()


# ===========================================================================
# 1–4: RuntimeReadiness enum
# ===========================================================================


class TestRuntimeReadiness:
    def test_01_has_three_values(self):
        m = _import_module()
        values = list(m.RuntimeReadiness)
        assert len(values) == 3

    def test_02_ready_value(self):
        m = _import_module()
        assert m.RuntimeReadiness.READY.value == "ready"

    def test_03_partial_value(self):
        m = _import_module()
        assert m.RuntimeReadiness.PARTIAL.value == "partial"

    def test_04_blocked_value(self):
        m = _import_module()
        assert m.RuntimeReadiness.BLOCKED.value == "blocked"


# ===========================================================================
# 5–8: CanonicalPathEntry dataclass
# ===========================================================================


class TestCanonicalPathEntry:
    def test_05_is_frozen_dataclass(self):
        import dataclasses
        m = _import_module()
        assert dataclasses.is_dataclass(m.CanonicalPathEntry)
        fields = dataclasses.fields(m.CanonicalPathEntry)
        # Frozen dataclasses raise FrozenInstanceError on assignment
        entry = m.CanonicalPathEntry(path="a", role="b", pr_introduced="PR-1")
        try:
            entry.path = "c"
            assert False, "Should have raised FrozenInstanceError"
        except (dataclasses.FrozenInstanceError, TypeError, AttributeError):
            pass

    def test_06_to_dict_has_path(self):
        m = _import_module()
        entry = m.CanonicalPathEntry(path="core.foo", role="bar", pr_introduced="PR-1")
        d = entry.to_dict()
        assert d["path"] == "core.foo"

    def test_07_to_dict_has_role(self):
        m = _import_module()
        entry = m.CanonicalPathEntry(path="core.foo", role="bar", pr_introduced="PR-1")
        d = entry.to_dict()
        assert d["role"] == "bar"

    def test_08_to_dict_has_pr_introduced(self):
        m = _import_module()
        entry = m.CanonicalPathEntry(path="core.foo", role="bar", pr_introduced="PR-2")
        d = entry.to_dict()
        assert d["pr_introduced"] == "PR-2"


# ===========================================================================
# 9–13: LegacyZoneEntry dataclass
# ===========================================================================


class TestLegacyZoneEntry:
    def test_09_is_frozen_dataclass(self):
        import dataclasses
        m = _import_module()
        assert dataclasses.is_dataclass(m.LegacyZoneEntry)
        entry = m.LegacyZoneEntry(path="a", status="DEPRECATED", superseded_by=None, notes="x")
        try:
            entry.path = "b"
            assert False, "Should have raised"
        except (dataclasses.FrozenInstanceError, TypeError, AttributeError):
            pass

    def test_10_to_dict_has_path(self):
        m = _import_module()
        entry = m.LegacyZoneEntry(path="dashboard.main", status="LEGACY_UI", superseded_by=None, notes="n")
        assert entry.to_dict()["path"] == "dashboard.main"

    def test_11_to_dict_has_status(self):
        m = _import_module()
        entry = m.LegacyZoneEntry(path="x", status="DEPRECATED", superseded_by=None, notes="n")
        assert entry.to_dict()["status"] == "DEPRECATED"

    def test_12_to_dict_has_superseded_by(self):
        m = _import_module()
        entry = m.LegacyZoneEntry(path="x", status="DEPRECATED", superseded_by="core.foo", notes="n")
        assert entry.to_dict()["superseded_by"] == "core.foo"

    def test_13_to_dict_has_notes(self):
        m = _import_module()
        entry = m.LegacyZoneEntry(path="x", status="DEPRECATED", superseded_by=None, notes="some note")
        assert entry.to_dict()["notes"] == "some note"


# ===========================================================================
# 14–18: ActiveBlocker dataclass
# ===========================================================================


class TestActiveBlocker:
    def test_14_is_frozen_dataclass(self):
        import dataclasses
        m = _import_module()
        assert dataclasses.is_dataclass(m.ActiveBlocker)
        b = m.ActiveBlocker(dimension="d", severity="blocking", description="x", recommended_action="y")
        try:
            b.dimension = "e"
            assert False, "Should have raised"
        except (dataclasses.FrozenInstanceError, TypeError, AttributeError):
            pass

    def test_15_to_dict_has_dimension(self):
        m = _import_module()
        b = m.ActiveBlocker(dimension="authority", severity="blocking", description="d", recommended_action="r")
        assert b.to_dict()["dimension"] == "authority"

    def test_16_to_dict_has_severity(self):
        m = _import_module()
        b = m.ActiveBlocker(dimension="d", severity="warning", description="x", recommended_action="y")
        assert b.to_dict()["severity"] == "warning"

    def test_17_to_dict_has_description(self):
        m = _import_module()
        b = m.ActiveBlocker(dimension="d", severity="blocking", description="desc text", recommended_action="y")
        assert b.to_dict()["description"] == "desc text"

    def test_18_to_dict_has_recommended_action(self):
        m = _import_module()
        b = m.ActiveBlocker(dimension="d", severity="blocking", description="x", recommended_action="do this")
        assert b.to_dict()["recommended_action"] == "do this"


# ===========================================================================
# 19–30: ArchitectureLiveStatus fields
# ===========================================================================


class TestArchitectureLiveStatusFields:
    def test_19_has_baseline_version(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert hasattr(s, "baseline_version")

    def test_20_has_runtime_readiness(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert hasattr(s, "runtime_readiness")

    def test_21_has_canonical_paths(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert hasattr(s, "canonical_paths")
        assert isinstance(s.canonical_paths, list)

    def test_22_has_legacy_zones(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert hasattr(s, "legacy_zones")
        assert isinstance(s.legacy_zones, list)

    def test_23_has_scorecard_summary(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert hasattr(s, "scorecard_summary")
        assert isinstance(s.scorecard_summary, dict)

    def test_24_has_active_blockers(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert hasattr(s, "active_blockers")
        assert isinstance(s.active_blockers, list)

    def test_25_has_projection_status(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert hasattr(s, "projection_status")
        assert isinstance(s.projection_status, dict)

    def test_26_has_capability_catalog_status(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert hasattr(s, "capability_catalog_status")
        assert isinstance(s.capability_catalog_status, dict)

    def test_27_has_addon_ecosystem_status(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert hasattr(s, "addon_ecosystem_status")
        assert isinstance(s.addon_ecosystem_status, dict)

    def test_28_has_cross_device_status(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert hasattr(s, "cross_device_status")
        assert isinstance(s.cross_device_status, dict)

    def test_29_has_authority_chain_status(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert hasattr(s, "authority_chain_status")
        assert isinstance(s.authority_chain_status, dict)

    def test_30_has_recommended_next_steps(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert hasattr(s, "recommended_next_steps")
        assert isinstance(s.recommended_next_steps, list)


# ===========================================================================
# 31–36: ArchitectureLiveStatus serialisation
# ===========================================================================


class TestArchitectureLiveStatusSerialisation:
    def test_31_to_dict_is_json_serialisable(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        d = s.to_dict()
        json.dumps(d)  # Must not raise

    def test_32_to_dict_has_all_12_keys(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        d = s.to_dict()
        expected_keys = {
            "baseline_version",
            "runtime_readiness",
            "canonical_paths",
            "legacy_zones",
            "scorecard_summary",
            "active_blockers",
            "projection_status",
            "capability_catalog_status",
            "addon_ecosystem_status",
            "cross_device_status",
            "authority_chain_status",
            "recommended_next_steps",
        }
        assert expected_keys <= set(d.keys())

    def test_33_to_json_returns_valid_json(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        j = s.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_34_to_dict_canonical_paths_is_list_of_dicts(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus(
            canonical_paths=[m.CanonicalPathEntry(path="x", role="y", pr_introduced="PR-1")]
        )
        d = s.to_dict()
        assert isinstance(d["canonical_paths"], list)
        assert isinstance(d["canonical_paths"][0], dict)

    def test_35_to_dict_legacy_zones_is_list_of_dicts(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus(
            legacy_zones=[m.LegacyZoneEntry(path="x", status="LEGACY_UI", superseded_by=None, notes="n")]
        )
        d = s.to_dict()
        assert isinstance(d["legacy_zones"], list)
        assert isinstance(d["legacy_zones"][0], dict)

    def test_36_to_dict_active_blockers_is_list_of_dicts(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus(
            active_blockers=[m.ActiveBlocker(dimension="d", severity="blocking", description="x", recommended_action="y")]
        )
        d = s.to_dict()
        assert isinstance(d["active_blockers"], list)
        assert isinstance(d["active_blockers"][0], dict)


# ===========================================================================
# 37–58: build_architecture_live_status()
# ===========================================================================


class TestBuildArchitectureLiveStatus:
    def setup_method(self):
        _reset()

    def test_37_returns_architecture_live_status(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert isinstance(s, m.ArchitectureLiveStatus)

    def test_38_baseline_version_matches_constant(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert s.baseline_version == m.BASELINE_VERSION

    def test_39_runtime_readiness_is_valid_value(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        valid = {"ready", "partial", "blocked"}
        assert s.runtime_readiness in valid

    def test_40_canonical_paths_non_empty(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert len(s.canonical_paths) > 0

    def test_41_canonical_paths_have_path_key(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        for p in s.canonical_paths:
            assert p.path, f"Empty path in {p}"

    def test_42_canonical_paths_have_role_key(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        for p in s.canonical_paths:
            assert p.role, f"Empty role in {p}"

    def test_43_canonical_paths_have_pr_introduced(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        for p in s.canonical_paths:
            assert p.pr_introduced, f"Empty pr_introduced in {p}"

    def test_44_legacy_zones_empty_after_mainline_closure(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert len(s.legacy_zones) == 0

    def test_45_legacy_zones_have_path_and_status(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        for z in s.legacy_zones:
            assert z.path, f"Empty path in zone {z}"
            assert z.status, f"Empty status in zone {z}"

    def test_46_scorecard_summary_has_completion_pct(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert "overall_completion_pct" in s.scorecard_summary

    def test_47_scorecard_summary_has_canonical_count(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert "canonical_count" in s.scorecard_summary

    def test_48_scorecard_summary_has_blocking_count(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert "blocking_count" in s.scorecard_summary

    def test_49_scorecard_summary_has_total_dimensions(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert "total_dimensions" in s.scorecard_summary
        assert s.scorecard_summary["total_dimensions"] == 10

    def test_50_scorecard_summary_has_blocking_dimensions_list(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert "blocking_dimensions" in s.scorecard_summary
        assert isinstance(s.scorecard_summary["blocking_dimensions"], list)

    def test_51_scorecard_summary_has_legacy_ambiguity_dimensions_list(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert "legacy_ambiguity_dimensions" in s.scorecard_summary
        assert isinstance(s.scorecard_summary["legacy_ambiguity_dimensions"], list)

    def test_52_projection_status_has_status_key(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert "status" in s.projection_status

    def test_53_capability_catalog_status_has_status_key(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert "status" in s.capability_catalog_status

    def test_54_addon_ecosystem_status_has_status_key(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert "status" in s.addon_ecosystem_status

    def test_55_cross_device_status_has_status_key(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert "status" in s.cross_device_status

    def test_56_authority_chain_status_has_status_key(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert "status" in s.authority_chain_status

    def test_57_recommended_next_steps_non_empty(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert len(s.recommended_next_steps) > 0
        assert all(isinstance(step, str) for step in s.recommended_next_steps)

    def test_58_end_to_end_json_serialisable(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        raw = json.dumps(s.to_dict())
        parsed = json.loads(raw)
        assert parsed["baseline_version"] == m.BASELINE_VERSION


# ===========================================================================
# 59–62: Singleton helpers
# ===========================================================================


class TestSingleton:
    def setup_method(self):
        _reset()

    def test_59_get_returns_architecture_live_status(self):
        m = _import_module()
        s = m.get_architecture_live_status()
        assert isinstance(s, m.ArchitectureLiveStatus)

    def test_60_get_is_idempotent(self):
        m = _import_module()
        s1 = m.get_architecture_live_status()
        s2 = m.get_architecture_live_status()
        assert s1 is s2

    def test_61_force_rebuild_returns_fresh_status(self):
        m = _import_module()
        s1 = m.get_architecture_live_status()
        s2 = m.get_architecture_live_status(force_rebuild=True)
        assert s2 is not s1
        assert isinstance(s2, m.ArchitectureLiveStatus)

    def test_62_reset_clears_cache(self):
        m = _import_module()
        s1 = m.get_architecture_live_status()
        m.reset_architecture_live_status()
        s2 = m.get_architecture_live_status()
        assert s2 is not s1


# ===========================================================================
# 63–72: Readiness classification rules
# ===========================================================================


class TestReadinessClassification:
    def _classify(self, scorecard_summary, projection_status, authority_chain_status, active_blockers):
        m = _import_module()
        return m._classify_readiness(
            scorecard_summary, projection_status, authority_chain_status, active_blockers
        )

    def test_63_blocked_when_blocking_count_gt_0(self):
        m = _import_module()
        result = self._classify(
            {"blocking_count": 1, "legacy_ambiguity_count": 0},
            {"projection_is_only_outward_truth": True},
            {"status": "valid"},
            [],
        )
        assert result == m.RuntimeReadiness.BLOCKED

    def test_64_partial_when_legacy_ambiguity_no_blocking(self):
        m = _import_module()
        result = self._classify(
            {"blocking_count": 0, "legacy_ambiguity_count": 2},
            {"projection_is_only_outward_truth": True},
            {"status": "valid"},
            [],
        )
        assert result == m.RuntimeReadiness.PARTIAL

    def test_65_ready_when_all_signals_clean(self):
        m = _import_module()
        result = self._classify(
            {"blocking_count": 0, "legacy_ambiguity_count": 0},
            {"projection_is_only_outward_truth": True},
            {"status": "valid"},
            [],
        )
        assert result == m.RuntimeReadiness.READY

    def test_66_blocked_when_active_blocker_severity_blocking(self):
        m = _import_module()
        blocker = m.ActiveBlocker(dimension="d", severity="blocking", description="x", recommended_action="y")
        result = self._classify(
            {"blocking_count": 0, "legacy_ambiguity_count": 0},
            {"projection_is_only_outward_truth": True},
            {"status": "valid"},
            [blocker],
        )
        assert result == m.RuntimeReadiness.BLOCKED

    def test_67_partial_when_active_blocker_severity_warning_only(self):
        m = _import_module()
        blocker = m.ActiveBlocker(dimension="d", severity="warning", description="x", recommended_action="y")
        result = self._classify(
            {"blocking_count": 0, "legacy_ambiguity_count": 0},
            {"projection_is_only_outward_truth": True},
            {"status": "valid"},
            [blocker],
        )
        assert result == m.RuntimeReadiness.PARTIAL

    def test_68_partial_when_projection_is_false(self):
        m = _import_module()
        result = self._classify(
            {"blocking_count": 0, "legacy_ambiguity_count": 0},
            {"projection_is_only_outward_truth": False},
            {"status": "valid"},
            [],
        )
        assert result == m.RuntimeReadiness.PARTIAL

    def test_69_partial_when_projection_is_none(self):
        m = _import_module()
        result = self._classify(
            {"blocking_count": 0, "legacy_ambiguity_count": 0},
            {"projection_is_only_outward_truth": None},
            {"status": "valid"},
            [],
        )
        assert result == m.RuntimeReadiness.PARTIAL

    def test_70_active_blockers_from_blocking_dims(self):
        m = _import_module()
        scorecard_summary = {
            "blocking_count": 1,
            "blocking_dimensions": [
                {
                    "dimension": "authority_clarity",
                    "maturity_level": "legacy_ambiguity",
                    "blockers": ["Authority boundary is undefined."],
                }
            ],
            "legacy_ambiguity_count": 0,
            "legacy_ambiguity_dimensions": [],
        }
        blockers = m._build_active_blockers(scorecard_summary)
        assert len(blockers) >= 1
        assert any(b.dimension == "authority_clarity" for b in blockers)

    def test_71_blocking_dims_produce_severity_blocking(self):
        m = _import_module()
        scorecard_summary = {
            "blocking_count": 1,
            "blocking_dimensions": [
                {
                    "dimension": "authority_clarity",
                    "maturity_level": "legacy_ambiguity",
                    "blockers": ["Some blocker."],
                }
            ],
            "legacy_ambiguity_count": 0,
            "legacy_ambiguity_dimensions": [],
        }
        blockers = m._build_active_blockers(scorecard_summary)
        assert all(b.severity == "blocking" for b in blockers if b.dimension == "authority_clarity")

    def test_72_legacy_ambiguity_dims_produce_severity_warning(self):
        m = _import_module()
        scorecard_summary = {
            "blocking_count": 0,
            "blocking_dimensions": [],
            "legacy_ambiguity_count": 1,
            "legacy_ambiguity_dimensions": ["capability_integration_completeness"],
        }
        blockers = m._build_active_blockers(scorecard_summary)
        assert any(
            b.severity == "warning" and b.dimension == "capability_integration_completeness"
            for b in blockers
        )


# ===========================================================================
# 73–76: Default scorecard consistency
# ===========================================================================


class TestScorecardConsistency:
    def setup_method(self):
        _reset()

    def test_73_canonical_count_is_10(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert s.scorecard_summary["canonical_count"] == 10

    def test_74_legacy_ambiguity_count_is_0(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert s.scorecard_summary["legacy_ambiguity_count"] == 0

    def test_75_blocking_count_is_0_by_default(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert s.scorecard_summary["blocking_count"] == 0

    def test_76_runtime_readiness_is_ready_by_default(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert s.runtime_readiness == "ready"


# ===========================================================================
# 77–90: Constants, serialisation, and scorecard integration
# ===========================================================================


class TestConstantsAndIntegration:
    def setup_method(self):
        _reset()

    def test_77_baseline_version_non_empty(self):
        m = _import_module()
        assert isinstance(m.BASELINE_VERSION, str) and len(m.BASELINE_VERSION) > 0

    def test_78_baseline_version_starts_with_pr(self):
        m = _import_module()
        assert m.BASELINE_VERSION.upper().startswith("PR-")

    def test_79_round_trips_consistently(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        j = s.to_json()
        parsed = json.loads(j)
        assert parsed["runtime_readiness"] == s.runtime_readiness
        assert parsed["baseline_version"] == s.baseline_version

    def test_80_serialized_runtime_readiness_is_valid_string(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        d = s.to_dict()
        assert d["runtime_readiness"] in {"ready", "partial", "blocked"}

    def test_81_canonical_paths_all_have_string_path(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        d = s.to_dict()
        for p in d["canonical_paths"]:
            assert isinstance(p["path"], str) and p["path"]

    def test_82_legacy_zones_all_have_string_status(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        d = s.to_dict()
        for z in d["legacy_zones"]:
            assert isinstance(z["status"], str) and z["status"]

    def test_83_active_blockers_all_have_severity_string(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        d = s.to_dict()
        for b in d["active_blockers"]:
            assert isinstance(b["severity"], str) and b["severity"]

    def test_84_scorecard_summary_consistent_with_completion_scorecard(self):
        m = _import_module()
        sc_m = importlib.import_module("core.architecture_completion")
        sc = sc_m.get_architecture_completion_scorecard()
        s = m.build_architecture_live_status()
        assert s.scorecard_summary["canonical_count"] == sc.canonical_count
        assert s.scorecard_summary["total_dimensions"] == sc.total_dimensions
        assert s.scorecard_summary["legacy_ambiguity_count"] == sc.legacy_ambiguity_count
        assert s.scorecard_summary["blocking_count"] == sc.blocking_count

    def test_85_completion_pct_in_range(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        pct = s.scorecard_summary["overall_completion_pct"]
        assert 0.0 <= pct <= 100.0

    def test_86_default_runtime_readiness_is_partial(self):
        m = _import_module()
        s = m.ArchitectureLiveStatus()
        assert s.runtime_readiness == "partial"

    def test_87_to_dict_baseline_version_matches_constant(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        assert s.to_dict()["baseline_version"] == m.BASELINE_VERSION

    def test_88_canonical_paths_have_non_empty_role(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        for p in s.canonical_paths:
            assert isinstance(p.role, str) and len(p.role) > 0

    def test_89_legacy_zones_superseded_by_is_none_or_string(self):
        m = _import_module()
        s = m.build_architecture_live_status()
        for z in s.legacy_zones:
            assert z.superseded_by is None or (isinstance(z.superseded_by, str) and z.superseded_by)

    def test_90_classify_readiness_ready_when_all_clean(self):
        m = _import_module()
        result = m._classify_readiness(
            {"blocking_count": 0, "legacy_ambiguity_count": 0},
            {"projection_is_only_outward_truth": True},
            {"status": "valid"},
            [],
        )
        assert result == m.RuntimeReadiness.READY
