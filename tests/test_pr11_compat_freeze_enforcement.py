"""PR-11: compat freeze enforcement tests."""

from __future__ import annotations


def test_default_snapshot_matches_frozen_budgets() -> None:
    from core.compat_freeze_enforcement import (
        FROZEN_COMPAT_SURFACE_BUDGET,
        FROZEN_LEGACY_PATH_BUDGET,
        FROZEN_PRODUCTION_BASELINE_LEGACY_BUDGET,
        build_compat_freeze_snapshot,
    )

    snapshot = build_compat_freeze_snapshot()

    assert snapshot.compat_surface_count == FROZEN_COMPAT_SURFACE_BUDGET
    assert snapshot.legacy_path_count == FROZEN_LEGACY_PATH_BUDGET
    assert (
        snapshot.production_baseline_legacy_count
        == FROZEN_PRODUCTION_BASELINE_LEGACY_BUDGET
    )
    assert snapshot.violations == []


def test_snapshot_flags_budget_growth_as_violation() -> None:
    from core.compat_freeze_enforcement import build_compat_freeze_snapshot

    snapshot = build_compat_freeze_snapshot(
        compat_surface_count=11,
        legacy_path_count=82,
        production_baseline_legacy_count=2,
    )

    assert snapshot.violations
    assert snapshot.to_dict()["is_frozen"] is False


def test_summary_contains_policy_sentinels() -> None:
    from core.compat_freeze_enforcement import build_compat_freeze_summary

    summary = build_compat_freeze_summary()
    assert len(summary["policy_sentinels"]) == 3
    assert summary["is_frozen"] is True


def test_production_baseline_summary_embeds_compat_freeze() -> None:
    from core.production_baseline import build_production_baseline_summary

    summary = build_production_baseline_summary()
    assert "compat_freeze" in summary
    assert summary["compat_freeze"]["is_frozen"] is True
