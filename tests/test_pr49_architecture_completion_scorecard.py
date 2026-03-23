#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr49_architecture_completion_scorecard.py
=====================================================

PR-9 — Formalize architecture completion evaluation dimensions and scorecard.

Note on file naming: test files in this repository use a sequential numbering
scheme (e.g. ``test_pr47``, ``test_pr48``) that does not map 1-to-1 to PR
numbers.  This file is numbered ``test_pr49`` to follow that sequence; it
corresponds to PR-9 in the issue tracker.

Validates:
  1.  MaturityLevel enum has all five expected values.
  2.  MaturityLevel.LEGACY_AMBIGUITY is the lowest tier (ordinal 0).
  3.  MaturityLevel.COMPLETE is the highest tier (ordinal 4).
  4.  MaturityLevel.is_blocking() is True for LEGACY_AMBIGUITY.
  5.  MaturityLevel.is_blocking() is True for IN_PROGRESS.
  6.  MaturityLevel.is_blocking() is False for PARTIAL.
  7.  MaturityLevel.is_blocking() is False for CANONICALIZED.
  8.  MaturityLevel.is_blocking() is False for COMPLETE.
  9.  CompletionDimension enum has exactly 10 values.
  10. CompletionDimension.AUTHORITY_CLARITY value is "authority_clarity".
  11. CompletionDimension.LEGACY_SURFACE_DEMOTION value is "legacy_surface_demotion".
  12. ALL_DIMENSIONS contains all 10 CompletionDimension values.
  13. DIMENSION_DESCRIPTIONS has an entry for every CompletionDimension.
  14. Every DIMENSION_DESCRIPTIONS value is a non-empty string.
  15. DimensionScorecard is a frozen dataclass (immutable).
  16. DimensionScorecard.to_dict() returns a dict with "dimension" key.
  17. DimensionScorecard.to_dict() "maturity_level" is a string, not enum.
  18. DimensionScorecard.to_dict() includes "canonical_path_established".
  19. DimensionScorecard.to_dict() includes "legacy_ambiguity_remains".
  20. DimensionScorecard.to_dict() includes "rationale".
  21. DimensionScorecard.to_dict() includes "evidence_modules" as a list.
  22. DimensionScorecard.to_dict() includes "blockers" as a list.
  23. DimensionScorecard.to_dict() includes "recommended_next_actions" as a list.
  24. DimensionScorecard.to_dict() includes "pr_last_updated".
  25. build_dimension_scorecard() returns a DimensionScorecard.
  26. build_dimension_scorecard() preserves evidence_modules.
  27. build_dimension_scorecard() preserves blockers.
  28. build_dimension_scorecard() preserves recommended_next_actions.
  29. build_dimension_scorecard() preserves pr_last_updated.
  30. ArchitectureCompletionScorecard has a dimensions list.
  31. ArchitectureCompletionScorecard has overall_completion_pct.
  32. ArchitectureCompletionScorecard has canonical_count.
  33. ArchitectureCompletionScorecard has legacy_ambiguity_count.
  34. ArchitectureCompletionScorecard has blocking_count.
  35. ArchitectureCompletionScorecard has total_dimensions == 10.
  36. ArchitectureCompletionScorecard.overall_completion_pct is in [0.0, 100.0].
  37. ArchitectureCompletionScorecard.to_dict() is JSON-serialisable.
  38. ArchitectureCompletionScorecard.to_json() returns a valid JSON string.
  39. ArchitectureCompletionScorecard.to_dict() includes "scorecard_version".
  40. ArchitectureCompletionScorecard.to_dict() includes "generated_by_pr".
  41. ArchitectureCompletionScorecard.to_dict() "dimensions" is a list of dicts.
  42. ArchitectureCompletionScorecard.dimension_by_name() returns correct record.
  43. ArchitectureCompletionScorecard.dimension_by_name() returns None for unknown dim.
  44. ArchitectureCompletionScorecard.legacy_ambiguity_dimensions() returns subset.
  45. ArchitectureCompletionScorecard.canonicalized_dimensions() returns subset.
  46. ArchitectureCompletionScorecard.blocking_dimensions() returns subset.
  47. ArchitectureCompletionScorecard.summary_lines() returns non-empty list.
  48. ArchitectureCompletionScorecard.summary_lines() contains scorecard_version.
  49. build_architecture_completion_scorecard() returns a scorecard with 10 dims.
  50. build_architecture_completion_scorecard() generated_by_pr defaults to "PR-9".
  51. build_architecture_completion_scorecard() accepts custom generated_by_pr.
  52. build_architecture_completion_scorecard() accepts dimension overrides.
  53. build_architecture_completion_scorecard() override replaces target dim.
  54. build_architecture_completion_scorecard() non-overridden dims are unchanged.
  55. get_architecture_completion_scorecard() returns an ArchitectureCompletionScorecard.
  56. get_architecture_completion_scorecard() is idempotent (same object on repeat call).
  57. get_architecture_completion_scorecard(force_rebuild=True) returns fresh scorecard.
  58. reset_architecture_completion_scorecard() clears cached singleton.
  59. Default scorecard AUTHORITY_CLARITY is CANONICALIZED.
  60. Default scorecard CANONICAL_PATH_COVERAGE is CANONICALIZED.
  61. Default scorecard LEGACY_SURFACE_DEMOTION is CANONICALIZED.
  62. Default scorecard CONTRACT_SCHEMA_NORMALIZATION is CANONICALIZED.
  63. Default scorecard CAPABILITY_INTEGRATION_COMPLETENESS is PARTIAL.
  64. Default scorecard PROJECTION_OUTWARD_TRUTH_ALIGNMENT is CANONICALIZED.
  65. Default scorecard CROSS_DEVICE_EXECUTION_CONSISTENCY is CANONICALIZED.
  66. Default scorecard INSTALLABILITY_ECOSYSTEM_READINESS is PARTIAL.
  67. Default scorecard DIAGNOSTICS_OBSERVABILITY_MATURITY is COMPLETE.
  68. Default scorecard TEST_COVERAGE_ARCHITECTURE_INVARIANTS is CANONICALIZED.
  69. CAPABILITY_INTEGRATION_COMPLETENESS has legacy_ambiguity_remains=True.
  70. INSTALLABILITY_ECOSYSTEM_READINESS has legacy_ambiguity_remains=True.
  71. DIAGNOSTICS_OBSERVABILITY_MATURITY has canonical_path_established=True.
  72. AUTHORITY_CLARITY has canonical_path_established=True.
  73. Default scorecard legacy_ambiguity_count == 2 (CAPABILITY + INSTALLABILITY).
  74. Default scorecard canonical_count >= 7.
  75. Default scorecard blocking_count == 0 (no LEGACY_AMBIGUITY or IN_PROGRESS).
  76. All dimension scorecards have non-empty rationale.
  77. All dimension scorecards have non-empty evidence_modules.
  78. All dimension scorecards have pr_last_updated set.
  79. CAPABILITY_INTEGRATION_COMPLETENESS has non-empty blockers.
  80. INSTALLABILITY_ECOSYSTEM_READINESS has non-empty blockers.
  81. Serialized scorecard round-trips cleanly via JSON.
  82. DimensionScorecard.to_dict() "dimension" value is a string.
  83. Default scorecard total_dimensions == 10.
  84. ArchitectureCompletionScorecard recomputes stats after dimension list changes.
  85. MaturityLevel ordinals are strictly ordered (0 < 1 < 2 < 3 < 4).
  86. CompletionDimension values are all lowercase_with_underscores strings.
  87. summary_lines() contains at least one line per dimension.
  88. build_architecture_completion_scorecard() with empty overrides = default.
  89. scorecard_version defaults to "1.0".
  90. generated_by_pr can be read from scorecard.to_dict().
"""

from __future__ import annotations

import importlib
import json
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------


def _import_module():
    return importlib.import_module("core.architecture_completion")


# ===========================================================================
# 1–8: MaturityLevel enum
# ===========================================================================


class TestMaturityLevel:
    def test_01_has_five_values(self):
        m = _import_module()
        values = list(m.MaturityLevel)
        assert len(values) == 5

    def test_02_legacy_ambiguity_ordinal_is_zero(self):
        m = _import_module()
        assert m.MaturityLevel.LEGACY_AMBIGUITY.ordinal() == 0

    def test_03_complete_ordinal_is_four(self):
        m = _import_module()
        assert m.MaturityLevel.COMPLETE.ordinal() == 4

    def test_04_is_blocking_true_for_legacy_ambiguity(self):
        m = _import_module()
        assert m.MaturityLevel.LEGACY_AMBIGUITY.is_blocking() is True

    def test_05_is_blocking_true_for_in_progress(self):
        m = _import_module()
        assert m.MaturityLevel.IN_PROGRESS.is_blocking() is True

    def test_06_is_blocking_false_for_partial(self):
        m = _import_module()
        assert m.MaturityLevel.PARTIAL.is_blocking() is False

    def test_07_is_blocking_false_for_canonicalized(self):
        m = _import_module()
        assert m.MaturityLevel.CANONICALIZED.is_blocking() is False

    def test_08_is_blocking_false_for_complete(self):
        m = _import_module()
        assert m.MaturityLevel.COMPLETE.is_blocking() is False


# ===========================================================================
# 9–14: CompletionDimension enum + supporting constants
# ===========================================================================


class TestCompletionDimension:
    def test_09_has_ten_values(self):
        m = _import_module()
        assert len(list(m.CompletionDimension)) == 10

    def test_10_authority_clarity_value(self):
        m = _import_module()
        assert m.CompletionDimension.AUTHORITY_CLARITY.value == "authority_clarity"

    def test_11_legacy_surface_demotion_value(self):
        m = _import_module()
        assert m.CompletionDimension.LEGACY_SURFACE_DEMOTION.value == "legacy_surface_demotion"

    def test_12_all_dimensions_contains_all_ten(self):
        m = _import_module()
        assert set(m.ALL_DIMENSIONS) == set(m.CompletionDimension)

    def test_13_dimension_descriptions_has_entry_for_every_dimension(self):
        m = _import_module()
        for dim in m.CompletionDimension:
            assert dim in m.DIMENSION_DESCRIPTIONS, f"Missing description for {dim}"

    def test_14_dimension_descriptions_values_are_non_empty_strings(self):
        m = _import_module()
        for dim, desc in m.DIMENSION_DESCRIPTIONS.items():
            assert isinstance(desc, str) and len(desc) > 0, f"Empty description for {dim}"


# ===========================================================================
# 15–29: DimensionScorecard dataclass
# ===========================================================================


class TestDimensionScorecard:
    def _make(self, **kwargs):
        m = _import_module()
        defaults = dict(
            dimension=m.CompletionDimension.AUTHORITY_CLARITY,
            maturity_level=m.MaturityLevel.CANONICALIZED,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale="Test rationale",
        )
        defaults.update(kwargs)
        return m.DimensionScorecard(**defaults)

    def test_15_is_frozen(self):
        import dataclasses
        m = _import_module()
        fields = dataclasses.fields(m.DimensionScorecard)
        assert any(f.name == "dimension" for f in fields)
        sc = self._make()
        try:
            sc.dimension = m.CompletionDimension.LEGACY_SURFACE_DEMOTION  # type: ignore[misc]
            assert False, "Expected FrozenInstanceError"
        except Exception:
            pass  # frozen as expected

    def test_16_to_dict_has_dimension_key(self):
        d = self._make().to_dict()
        assert "dimension" in d

    def test_17_to_dict_maturity_level_is_string(self):
        d = self._make().to_dict()
        assert isinstance(d["maturity_level"], str)

    def test_18_to_dict_has_canonical_path_established(self):
        d = self._make(canonical_path_established=True).to_dict()
        assert d["canonical_path_established"] is True

    def test_19_to_dict_has_legacy_ambiguity_remains(self):
        d = self._make(legacy_ambiguity_remains=False).to_dict()
        assert d["legacy_ambiguity_remains"] is False

    def test_20_to_dict_has_rationale(self):
        d = self._make(rationale="Some rationale").to_dict()
        assert d["rationale"] == "Some rationale"

    def test_21_to_dict_evidence_modules_is_list(self):
        d = self._make(evidence_modules=["core.foo"]).to_dict()
        assert isinstance(d["evidence_modules"], list)
        assert "core.foo" in d["evidence_modules"]

    def test_22_to_dict_blockers_is_list(self):
        d = self._make(blockers=["blocker1"]).to_dict()
        assert isinstance(d["blockers"], list)
        assert "blocker1" in d["blockers"]

    def test_23_to_dict_recommended_next_actions_is_list(self):
        d = self._make(recommended_next_actions=["do this"]).to_dict()
        assert isinstance(d["recommended_next_actions"], list)

    def test_24_to_dict_pr_last_updated(self):
        d = self._make(pr_last_updated="PR-9").to_dict()
        assert d["pr_last_updated"] == "PR-9"

    def test_82_to_dict_dimension_is_string(self):
        d = self._make().to_dict()
        assert isinstance(d["dimension"], str)


# ===========================================================================
# 25–29: build_dimension_scorecard
# ===========================================================================


class TestBuildDimensionScorecard:
    def test_25_returns_dimension_scorecard(self):
        m = _import_module()
        sc = m.build_dimension_scorecard(
            m.CompletionDimension.AUTHORITY_CLARITY,
            m.MaturityLevel.COMPLETE,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale="Test",
        )
        assert isinstance(sc, m.DimensionScorecard)

    def test_26_preserves_evidence_modules(self):
        m = _import_module()
        sc = m.build_dimension_scorecard(
            m.CompletionDimension.AUTHORITY_CLARITY,
            m.MaturityLevel.COMPLETE,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale="Test",
            evidence_modules=["core.mod1", "core.mod2"],
        )
        assert "core.mod1" in sc.evidence_modules
        assert "core.mod2" in sc.evidence_modules

    def test_27_preserves_blockers(self):
        m = _import_module()
        sc = m.build_dimension_scorecard(
            m.CompletionDimension.AUTHORITY_CLARITY,
            m.MaturityLevel.IN_PROGRESS,
            canonical_path_established=False,
            legacy_ambiguity_remains=True,
            rationale="Test",
            blockers=["Need canonical path"],
        )
        assert sc.blockers is not None
        assert "Need canonical path" in sc.blockers

    def test_28_preserves_recommended_next_actions(self):
        m = _import_module()
        sc = m.build_dimension_scorecard(
            m.CompletionDimension.AUTHORITY_CLARITY,
            m.MaturityLevel.PARTIAL,
            canonical_path_established=True,
            legacy_ambiguity_remains=True,
            rationale="Test",
            recommended_next_actions=["Step A", "Step B"],
        )
        assert sc.recommended_next_actions is not None
        assert "Step A" in sc.recommended_next_actions

    def test_29_preserves_pr_last_updated(self):
        m = _import_module()
        sc = m.build_dimension_scorecard(
            m.CompletionDimension.LEGACY_SURFACE_DEMOTION,
            m.MaturityLevel.CANONICALIZED,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale="Test",
            pr_last_updated="PR-8",
        )
        assert sc.pr_last_updated == "PR-8"


# ===========================================================================
# 30–48: ArchitectureCompletionScorecard
# ===========================================================================


class TestArchitectureCompletionScorecard:
    def _make_simple_scorecard(self):
        m = _import_module()
        dims = [
            m.build_dimension_scorecard(
                d,
                m.MaturityLevel.CANONICALIZED,
                canonical_path_established=True,
                legacy_ambiguity_remains=False,
                rationale="Test",
            )
            for d in m.CompletionDimension
        ]
        return m.ArchitectureCompletionScorecard(dimensions=dims)

    def test_30_has_dimensions_list(self):
        sc = self._make_simple_scorecard()
        assert isinstance(sc.dimensions, list)

    def test_31_has_overall_completion_pct(self):
        sc = self._make_simple_scorecard()
        assert hasattr(sc, "overall_completion_pct")

    def test_32_has_canonical_count(self):
        sc = self._make_simple_scorecard()
        assert hasattr(sc, "canonical_count")

    def test_33_has_legacy_ambiguity_count(self):
        sc = self._make_simple_scorecard()
        assert hasattr(sc, "legacy_ambiguity_count")

    def test_34_has_blocking_count(self):
        sc = self._make_simple_scorecard()
        assert hasattr(sc, "blocking_count")

    def test_35_total_dimensions_is_10(self):
        sc = self._make_simple_scorecard()
        assert sc.total_dimensions == 10

    def test_36_overall_completion_pct_in_range(self):
        sc = self._make_simple_scorecard()
        assert 0.0 <= sc.overall_completion_pct <= 100.0

    def test_37_to_dict_is_json_serialisable(self):
        sc = self._make_simple_scorecard()
        d = sc.to_dict()
        # Should not raise
        serialized = json.dumps(d)
        assert isinstance(serialized, str)

    def test_38_to_json_returns_valid_json(self):
        sc = self._make_simple_scorecard()
        result = sc.to_json()
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_39_to_dict_has_scorecard_version(self):
        sc = self._make_simple_scorecard()
        d = sc.to_dict()
        assert "scorecard_version" in d

    def test_40_to_dict_has_generated_by_pr(self):
        sc = self._make_simple_scorecard()
        d = sc.to_dict()
        assert "generated_by_pr" in d

    def test_41_to_dict_dimensions_is_list_of_dicts(self):
        sc = self._make_simple_scorecard()
        d = sc.to_dict()
        assert isinstance(d["dimensions"], list)
        for item in d["dimensions"]:
            assert isinstance(item, dict)

    def test_42_dimension_by_name_returns_correct_record(self):
        m = _import_module()
        sc = self._make_simple_scorecard()
        rec = sc.dimension_by_name(m.CompletionDimension.AUTHORITY_CLARITY)
        assert rec is not None
        assert rec.dimension == m.CompletionDimension.AUTHORITY_CLARITY

    def test_43_dimension_by_name_returns_none_for_unknown(self):
        m = _import_module()
        sc = self._make_simple_scorecard()
        # We can't pass an unknown value directly, so we test by passing None
        # which will never match a real dimension
        result = sc.dimension_by_name(None)  # type: ignore[arg-type]
        assert result is None

    def test_44_legacy_ambiguity_dimensions_returns_subset(self):
        m = _import_module()
        dims = [
            m.build_dimension_scorecard(
                m.CompletionDimension.AUTHORITY_CLARITY,
                m.MaturityLevel.CANONICALIZED,
                canonical_path_established=True,
                legacy_ambiguity_remains=False,
                rationale="Clean",
            ),
            m.build_dimension_scorecard(
                m.CompletionDimension.CAPABILITY_INTEGRATION_COMPLETENESS,
                m.MaturityLevel.PARTIAL,
                canonical_path_established=True,
                legacy_ambiguity_remains=True,
                rationale="Partial",
            ),
        ]
        # Pad to 10 dimensions
        for d in m.CompletionDimension:
            if d not in (
                m.CompletionDimension.AUTHORITY_CLARITY,
                m.CompletionDimension.CAPABILITY_INTEGRATION_COMPLETENESS,
            ):
                dims.append(
                    m.build_dimension_scorecard(
                        d,
                        m.MaturityLevel.CANONICALIZED,
                        canonical_path_established=True,
                        legacy_ambiguity_remains=False,
                        rationale="Test",
                    )
                )
        sc = m.ArchitectureCompletionScorecard(dimensions=dims)
        ambiguous = sc.legacy_ambiguity_dimensions()
        assert len(ambiguous) == 1
        assert ambiguous[0].dimension == m.CompletionDimension.CAPABILITY_INTEGRATION_COMPLETENESS

    def test_45_canonicalized_dimensions_returns_subset(self):
        m = _import_module()
        sc = self._make_simple_scorecard()
        canon = sc.canonicalized_dimensions()
        assert len(canon) == 10  # All are CANONICALIZED in this test

    def test_46_blocking_dimensions_returns_subset(self):
        m = _import_module()
        dims = [
            m.build_dimension_scorecard(
                m.CompletionDimension.AUTHORITY_CLARITY,
                m.MaturityLevel.LEGACY_AMBIGUITY,
                canonical_path_established=False,
                legacy_ambiguity_remains=True,
                rationale="Blocking",
            )
        ]
        for d in m.CompletionDimension:
            if d != m.CompletionDimension.AUTHORITY_CLARITY:
                dims.append(
                    m.build_dimension_scorecard(
                        d,
                        m.MaturityLevel.CANONICALIZED,
                        canonical_path_established=True,
                        legacy_ambiguity_remains=False,
                        rationale="Test",
                    )
                )
        sc = m.ArchitectureCompletionScorecard(dimensions=dims)
        blocking = sc.blocking_dimensions()
        assert len(blocking) == 1
        assert blocking[0].dimension == m.CompletionDimension.AUTHORITY_CLARITY

    def test_47_summary_lines_non_empty(self):
        sc = self._make_simple_scorecard()
        lines = sc.summary_lines()
        assert isinstance(lines, list)
        assert len(lines) > 0

    def test_48_summary_lines_contains_scorecard_version(self):
        sc = self._make_simple_scorecard()
        lines = sc.summary_lines()
        combined = "\n".join(lines)
        assert "1.0" in combined


# ===========================================================================
# 49–58: build_architecture_completion_scorecard and get_
# ===========================================================================


class TestBuildAndGetScorecard:
    def test_49_returns_scorecard_with_10_dims(self):
        m = _import_module()
        sc = m.build_architecture_completion_scorecard()
        assert len(sc.dimensions) == 10

    def test_50_generated_by_pr_defaults_to_pr9(self):
        m = _import_module()
        sc = m.build_architecture_completion_scorecard()
        assert sc.generated_by_pr == "PR-9"

    def test_51_accepts_custom_generated_by_pr(self):
        m = _import_module()
        sc = m.build_architecture_completion_scorecard(generated_by_pr="PR-10")
        assert sc.generated_by_pr == "PR-10"

    def test_52_accepts_dimension_overrides(self):
        m = _import_module()
        override = m.build_dimension_scorecard(
            m.CompletionDimension.AUTHORITY_CLARITY,
            m.MaturityLevel.COMPLETE,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale="Override rationale",
        )
        sc = m.build_architecture_completion_scorecard(
            overrides={m.CompletionDimension.AUTHORITY_CLARITY: override}
        )
        rec = sc.dimension_by_name(m.CompletionDimension.AUTHORITY_CLARITY)
        assert rec is not None
        assert rec.maturity_level == m.MaturityLevel.COMPLETE

    def test_53_override_replaces_target_dim(self):
        m = _import_module()
        override = m.build_dimension_scorecard(
            m.CompletionDimension.CANONICAL_PATH_COVERAGE,
            m.MaturityLevel.LEGACY_AMBIGUITY,
            canonical_path_established=False,
            legacy_ambiguity_remains=True,
            rationale="Degraded",
        )
        sc = m.build_architecture_completion_scorecard(
            overrides={m.CompletionDimension.CANONICAL_PATH_COVERAGE: override}
        )
        rec = sc.dimension_by_name(m.CompletionDimension.CANONICAL_PATH_COVERAGE)
        assert rec is not None
        assert rec.maturity_level == m.MaturityLevel.LEGACY_AMBIGUITY

    def test_54_non_overridden_dims_unchanged(self):
        m = _import_module()
        default_sc = m.build_architecture_completion_scorecard()
        default_rec = default_sc.dimension_by_name(m.CompletionDimension.LEGACY_SURFACE_DEMOTION)
        override = m.build_dimension_scorecard(
            m.CompletionDimension.AUTHORITY_CLARITY,
            m.MaturityLevel.COMPLETE,
            canonical_path_established=True,
            legacy_ambiguity_remains=False,
            rationale="Override",
        )
        sc = m.build_architecture_completion_scorecard(
            overrides={m.CompletionDimension.AUTHORITY_CLARITY: override}
        )
        rec = sc.dimension_by_name(m.CompletionDimension.LEGACY_SURFACE_DEMOTION)
        assert rec is not None
        assert rec.maturity_level == default_rec.maturity_level  # type: ignore[union-attr]

    def test_55_get_returns_scorecard(self):
        m = _import_module()
        m.reset_architecture_completion_scorecard()
        sc = m.get_architecture_completion_scorecard()
        assert isinstance(sc, m.ArchitectureCompletionScorecard)

    def test_56_get_is_idempotent(self):
        m = _import_module()
        m.reset_architecture_completion_scorecard()
        sc1 = m.get_architecture_completion_scorecard()
        sc2 = m.get_architecture_completion_scorecard()
        assert sc1 is sc2

    def test_57_force_rebuild_returns_fresh(self):
        m = _import_module()
        m.reset_architecture_completion_scorecard()
        sc1 = m.get_architecture_completion_scorecard()
        sc2 = m.get_architecture_completion_scorecard(force_rebuild=True)
        assert sc1 is not sc2

    def test_58_reset_clears_singleton(self):
        m = _import_module()
        m.reset_architecture_completion_scorecard()
        sc1 = m.get_architecture_completion_scorecard()
        m.reset_architecture_completion_scorecard()
        sc2 = m.get_architecture_completion_scorecard()
        assert sc1 is not sc2

    def test_88_empty_overrides_equals_default(self):
        m = _import_module()
        sc_default = m.build_architecture_completion_scorecard()
        sc_empty = m.build_architecture_completion_scorecard(overrides={})
        assert sc_default.total_dimensions == sc_empty.total_dimensions
        assert sc_default.canonical_count == sc_empty.canonical_count


# ===========================================================================
# 59–68: Default scorecard dimension maturity levels
# ===========================================================================


class TestDefaultDimensionLevels:
    def _sc(self):
        m = _import_module()
        m.reset_architecture_completion_scorecard()
        return m.get_architecture_completion_scorecard(), m

    def test_59_authority_clarity_is_canonicalized(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.AUTHORITY_CLARITY)
        assert rec.maturity_level == m.MaturityLevel.CANONICALIZED

    def test_60_canonical_path_coverage_is_canonicalized(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.CANONICAL_PATH_COVERAGE)
        assert rec.maturity_level == m.MaturityLevel.CANONICALIZED

    def test_61_legacy_surface_demotion_is_canonicalized(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.LEGACY_SURFACE_DEMOTION)
        assert rec.maturity_level == m.MaturityLevel.CANONICALIZED

    def test_62_contract_schema_normalization_is_canonicalized(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.CONTRACT_SCHEMA_NORMALIZATION)
        assert rec.maturity_level == m.MaturityLevel.CANONICALIZED

    def test_63_capability_integration_is_partial(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.CAPABILITY_INTEGRATION_COMPLETENESS)
        assert rec.maturity_level == m.MaturityLevel.PARTIAL

    def test_64_projection_outward_truth_is_canonicalized(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.PROJECTION_OUTWARD_TRUTH_ALIGNMENT)
        assert rec.maturity_level == m.MaturityLevel.CANONICALIZED

    def test_65_cross_device_execution_is_canonicalized(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.CROSS_DEVICE_EXECUTION_CONSISTENCY)
        assert rec.maturity_level == m.MaturityLevel.CANONICALIZED

    def test_66_installability_is_partial(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.INSTALLABILITY_ECOSYSTEM_READINESS)
        assert rec.maturity_level == m.MaturityLevel.PARTIAL

    def test_67_diagnostics_observability_is_complete(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.DIAGNOSTICS_OBSERVABILITY_MATURITY)
        assert rec.maturity_level == m.MaturityLevel.COMPLETE

    def test_68_test_coverage_invariants_is_canonicalized(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.TEST_COVERAGE_ARCHITECTURE_INVARIANTS)
        assert rec.maturity_level == m.MaturityLevel.CANONICALIZED


# ===========================================================================
# 69–80: Default scorecard flags and blockers
# ===========================================================================


class TestDefaultDimensionFlags:
    def _sc(self):
        m = _import_module()
        m.reset_architecture_completion_scorecard()
        return m.get_architecture_completion_scorecard(), m

    def test_69_capability_integration_legacy_ambiguity_true(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.CAPABILITY_INTEGRATION_COMPLETENESS)
        assert rec.legacy_ambiguity_remains is True

    def test_70_installability_legacy_ambiguity_true(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.INSTALLABILITY_ECOSYSTEM_READINESS)
        assert rec.legacy_ambiguity_remains is True

    def test_71_diagnostics_canonical_path_established(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.DIAGNOSTICS_OBSERVABILITY_MATURITY)
        assert rec.canonical_path_established is True

    def test_72_authority_clarity_canonical_path_established(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.AUTHORITY_CLARITY)
        assert rec.canonical_path_established is True

    def test_73_legacy_ambiguity_count_is_2(self):
        sc, _ = self._sc()
        assert sc.legacy_ambiguity_count == 2

    def test_74_canonical_count_gte_7(self):
        sc, _ = self._sc()
        assert sc.canonical_count >= 7

    def test_75_blocking_count_is_0(self):
        sc, _ = self._sc()
        assert sc.blocking_count == 0

    def test_76_all_dimensions_have_nonempty_rationale(self):
        sc, _ = self._sc()
        for d in sc.dimensions:
            assert d.rationale, f"Empty rationale for {d.dimension}"

    def test_77_all_dimensions_have_nonempty_evidence_modules(self):
        sc, _ = self._sc()
        for d in sc.dimensions:
            assert d.evidence_modules, f"Empty evidence_modules for {d.dimension}"

    def test_78_all_dimensions_have_pr_last_updated(self):
        sc, _ = self._sc()
        for d in sc.dimensions:
            assert d.pr_last_updated, f"Missing pr_last_updated for {d.dimension}"

    def test_79_capability_integration_has_blockers(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.CAPABILITY_INTEGRATION_COMPLETENESS)
        assert rec.blockers and len(rec.blockers) > 0

    def test_80_installability_has_blockers(self):
        sc, m = self._sc()
        rec = sc.dimension_by_name(m.CompletionDimension.INSTALLABILITY_ECOSYSTEM_READINESS)
        assert rec.blockers and len(rec.blockers) > 0


# ===========================================================================
# 81–90: Serialization and structural invariants
# ===========================================================================


class TestSerialization:
    def test_81_serialized_scorecard_round_trips(self):
        m = _import_module()
        m.reset_architecture_completion_scorecard()
        sc = m.get_architecture_completion_scorecard()
        as_json = sc.to_json()
        parsed = json.loads(as_json)
        assert parsed["total_dimensions"] == 10
        assert len(parsed["dimensions"]) == 10
        for d in parsed["dimensions"]:
            assert "dimension" in d
            assert "maturity_level" in d
            assert "canonical_path_established" in d
            assert "legacy_ambiguity_remains" in d

    def test_83_default_total_dimensions_is_10(self):
        m = _import_module()
        m.reset_architecture_completion_scorecard()
        sc = m.get_architecture_completion_scorecard()
        assert sc.total_dimensions == 10

    def test_84_recompute_stats_on_construction(self):
        m = _import_module()
        # Build a scorecard with 5 canonicalized and 5 in-progress dims
        dims = []
        all_dims = list(m.CompletionDimension)
        for i, d in enumerate(all_dims):
            level = m.MaturityLevel.CANONICALIZED if i < 5 else m.MaturityLevel.IN_PROGRESS
            dims.append(
                m.build_dimension_scorecard(
                    d, level,
                    canonical_path_established=(i < 5),
                    legacy_ambiguity_remains=False,
                    rationale="Test",
                )
            )
        sc = m.ArchitectureCompletionScorecard(dimensions=dims)
        assert sc.canonical_count == 5
        assert sc.blocking_count == 5
        assert abs(sc.overall_completion_pct - 50.0) < 0.01

    def test_85_maturity_level_ordinals_strictly_ordered(self):
        m = _import_module()
        levels = [
            m.MaturityLevel.LEGACY_AMBIGUITY,
            m.MaturityLevel.IN_PROGRESS,
            m.MaturityLevel.PARTIAL,
            m.MaturityLevel.CANONICALIZED,
            m.MaturityLevel.COMPLETE,
        ]
        for i in range(len(levels) - 1):
            assert levels[i].ordinal() < levels[i + 1].ordinal()

    def test_86_completion_dimension_values_are_lowercase_underscore(self):
        m = _import_module()
        import re
        pattern = re.compile(r"^[a-z][a-z0-9_]*$")
        for dim in m.CompletionDimension:
            assert pattern.match(dim.value), f"Value '{dim.value}' is not lowercase_underscore"

    def test_87_summary_lines_has_line_per_dimension(self):
        m = _import_module()
        m.reset_architecture_completion_scorecard()
        sc = m.get_architecture_completion_scorecard()
        lines = sc.summary_lines()
        # Each dimension should appear somewhere in the summary lines
        for d in sc.dimensions:
            dim_val = d.dimension.value if hasattr(d.dimension, "value") else str(d.dimension)
            found = any(dim_val in line for line in lines)
            assert found, f"Dimension {dim_val} not found in summary_lines"

    def test_89_scorecard_version_defaults_to_1_0(self):
        m = _import_module()
        m.reset_architecture_completion_scorecard()
        sc = m.get_architecture_completion_scorecard()
        assert sc.scorecard_version == "1.0"

    def test_90_generated_by_pr_readable_from_to_dict(self):
        m = _import_module()
        m.reset_architecture_completion_scorecard()
        sc = m.get_architecture_completion_scorecard()
        d = sc.to_dict()
        assert d["generated_by_pr"] == "PR-9"
