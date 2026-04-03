#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_startup_tier_model.py
=================================

Validates the canonical 3-tier startup model and active-node runtime-readiness
baseline introduced by PR-startup-tiers.

Validates:
  1.  core.startup_tier_model is importable.
  2.  STARTUP_TIER_MODEL_AUTHORITY sentinel is set.
  3.  STARTUP_TIER_MODEL_GROUNDED_IN_EXISTING_GOVERNANCE sentinel is True.
  4.  ACTIVE_NODE_READINESS_BASELINE_DEFINED sentinel is True.
  5.  TIER_CORE constant equals "Core".
  6.  TIER_STANDARD constant equals "Standard".
  7.  TIER_FULL constant equals "Full".
  8.  TIER_DESCRIPTIONS contains all three tier keys.
  9.  TIER_SELECTION_RULES contains all three tier keys.
  10. TIER_ACCEPTANCE_CRITERIA contains all three tier keys.
  11. ActiveNodeReadinessBaseline dataclass is importable.
  12. ActiveNodeReadinessBaseline can be instantiated with default fields.
  13. ActiveNodeReadinessBaseline.summary() returns expected keys.
  14. ActiveNodeReadinessBaseline.is_core_complete() returns True when no gaps overlap core.
  15. ActiveNodeReadinessBaseline.is_core_complete() returns False when core overlaps gap.
  16. build_readiness_baseline() returns an ActiveNodeReadinessBaseline instance.
  17. build_readiness_baseline() core_tier count >= 1.
  18. build_readiness_baseline() standard_tier count >= core_tier count.
  19. build_readiness_baseline() Core ⊆ Standard (subset invariant).
  20. build_readiness_baseline() active_baseline count >= 1.
  21. build_readiness_baseline() readiness_gap_count is an int >= 0.
  22. check_tier_model_metadata() returns True for metadata_key_present.
  23. check_tier_model_metadata() returns True for all_three_tiers_defined.
  24. check_tier_model_metadata() returns True for core_tier_has_selection_rule.
  25. check_tier_model_metadata() returns True for standard_tier_has_selection_rule.
  26. check_tier_model_metadata() returns True for full_tier_has_selection_rule.
  27. check_tier_model_metadata() returns True for invariants_listed.
  28. node_dependencies.json contains _startup_tier_model key.
  29. _startup_tier_model has "tiers" sub-key.
  30. _startup_tier_model["tiers"] contains "Core", "Standard", "Full".
  31. _startup_tier_model["invariants"] is a non-empty list.
  32. NodeSystemLauncher.STARTUP_TIER_CORE == "Core".
  33. NodeSystemLauncher.STARTUP_TIER_STANDARD == "Standard".
  34. NodeSystemLauncher.STARTUP_TIER_FULL == "Full".
  35. NodeSystemLauncher has get_tier_nodes method.
  36. NodeSystemLauncher has get_readiness_baseline method.
  37. NodeSystemLauncher.get_tier_nodes("Core") returns non-empty list.
  38. NodeSystemLauncher.get_tier_nodes("Standard") returns non-empty list.
  39. NodeSystemLauncher.get_tier_nodes("Full") returns non-empty list.
  40. NodeSystemLauncher.get_tier_nodes("Core") ⊆ get_tier_nodes("Standard").
  41. NodeSystemLauncher.get_tier_nodes("Standard") ⊆ get_tier_nodes("Full").
  42. NodeSystemLauncher.get_tier_nodes raises ValueError for unknown tier.
  43. NodeSystemLauncher.get_tier_nodes("Core") is sorted.
  44. NodeSystemLauncher.get_tier_nodes("Full") excludes skip-policy nodes.
  45. NodeSystemLauncher.get_readiness_baseline() returns dict with expected keys.
  46. NodeSystemLauncher.get_readiness_baseline() summary has readiness_gap_count.
  47. NodeSystemLauncher.get_tier_nodes("Core") matches get_core_nodes() (same set).
  48. NodeSystemLauncher.get_tier_nodes("Full") matches get_active_nodes() (same set).
  49. docs/STARTUP_TIER_MODEL.md exists.
  50. docs/STARTUP_TIER_MODEL.md references all three tier names.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ── Constants ─────────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
NDJ_PATH = PROJECT_ROOT / "node_dependencies.json"
TIER_DOC_PATH = PROJECT_ROOT / "docs" / "STARTUP_TIER_MODEL.md"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def ndj() -> Dict[str, Any]:
    assert NDJ_PATH.exists(), f"node_dependencies.json not found at {NDJ_PATH}"
    with NDJ_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def tier_meta(ndj) -> Dict[str, Any]:
    return ndj.get("_startup_tier_model", {})


@pytest.fixture(scope="session")
def launcher(ndj):
    """Return a NodeSystemLauncher instance backed by the real node_dependencies.json."""
    from launcher.node_startup import NodeSystemLauncher

    service_manager = MagicMock()
    config = MagicMock()
    config.web_ui_port = 9000

    instance = NodeSystemLauncher.__new__(NodeSystemLauncher)
    instance.service_manager = service_manager
    instance.config = config
    instance.nodes_dir = PROJECT_ROOT / "nodes"
    instance.node_configs = ndj.get("nodes", {})
    return instance


# ── 1–10: core.startup_tier_model module ─────────────────────────────────────

def test_module_importable():
    """1. core.startup_tier_model is importable."""
    import core.startup_tier_model  # noqa: F401


def test_authority_sentinel():
    """2. STARTUP_TIER_MODEL_AUTHORITY sentinel is set."""
    from core.startup_tier_model import STARTUP_TIER_MODEL_AUTHORITY
    assert STARTUP_TIER_MODEL_AUTHORITY == "core.startup_tier_model"


def test_grounded_sentinel():
    """3. STARTUP_TIER_MODEL_GROUNDED_IN_EXISTING_GOVERNANCE is True."""
    from core.startup_tier_model import STARTUP_TIER_MODEL_GROUNDED_IN_EXISTING_GOVERNANCE
    assert STARTUP_TIER_MODEL_GROUNDED_IN_EXISTING_GOVERNANCE is True


def test_readiness_baseline_sentinel():
    """4. ACTIVE_NODE_READINESS_BASELINE_DEFINED is True."""
    from core.startup_tier_model import ACTIVE_NODE_READINESS_BASELINE_DEFINED
    assert ACTIVE_NODE_READINESS_BASELINE_DEFINED is True


def test_tier_core_constant():
    """5. TIER_CORE == "Core"."""
    from core.startup_tier_model import TIER_CORE
    assert TIER_CORE == "Core"


def test_tier_standard_constant():
    """6. TIER_STANDARD == "Standard"."""
    from core.startup_tier_model import TIER_STANDARD
    assert TIER_STANDARD == "Standard"


def test_tier_full_constant():
    """7. TIER_FULL == "Full"."""
    from core.startup_tier_model import TIER_FULL
    assert TIER_FULL == "Full"


def test_tier_descriptions_complete():
    """8. TIER_DESCRIPTIONS contains all three tier keys."""
    from core.startup_tier_model import TIER_DESCRIPTIONS, TIER_CORE, TIER_STANDARD, TIER_FULL
    for tier in (TIER_CORE, TIER_STANDARD, TIER_FULL):
        assert tier in TIER_DESCRIPTIONS, f"Missing tier in TIER_DESCRIPTIONS: {tier}"


def test_tier_selection_rules_complete():
    """9. TIER_SELECTION_RULES contains all three tier keys."""
    from core.startup_tier_model import TIER_SELECTION_RULES, TIER_CORE, TIER_STANDARD, TIER_FULL
    for tier in (TIER_CORE, TIER_STANDARD, TIER_FULL):
        assert tier in TIER_SELECTION_RULES, f"Missing tier in TIER_SELECTION_RULES: {tier}"


def test_tier_acceptance_criteria_complete():
    """10. TIER_ACCEPTANCE_CRITERIA contains all three tier keys."""
    from core.startup_tier_model import TIER_ACCEPTANCE_CRITERIA, TIER_CORE, TIER_STANDARD, TIER_FULL
    for tier in (TIER_CORE, TIER_STANDARD, TIER_FULL):
        assert tier in TIER_ACCEPTANCE_CRITERIA


# ── 11–15: ActiveNodeReadinessBaseline dataclass ─────────────────────────────

def test_readiness_baseline_importable():
    """11. ActiveNodeReadinessBaseline dataclass is importable."""
    from core.startup_tier_model import ActiveNodeReadinessBaseline  # noqa: F401


def test_readiness_baseline_default_instantiation():
    """12. ActiveNodeReadinessBaseline can be instantiated with defaults."""
    from core.startup_tier_model import ActiveNodeReadinessBaseline
    b = ActiveNodeReadinessBaseline()
    assert b.core_tier == []
    assert b.standard_tier == []
    assert b.active_baseline == []
    assert b.optional_governed == []
    assert b.readiness_gaps == []


def test_readiness_baseline_summary_keys():
    """13. ActiveNodeReadinessBaseline.summary() returns expected keys."""
    from core.startup_tier_model import ActiveNodeReadinessBaseline
    b = ActiveNodeReadinessBaseline()
    s = b.summary()
    expected_keys = {
        "core_tier_count",
        "standard_tier_count",
        "active_baseline_count",
        "optional_governed_count",
        "readiness_gap_count",
    }
    assert expected_keys.issubset(set(s.keys()))


def test_readiness_baseline_is_core_complete_true():
    """14. is_core_complete() returns True when no gaps overlap core."""
    from core.startup_tier_model import ActiveNodeReadinessBaseline
    b = ActiveNodeReadinessBaseline(
        core_tier=["Node_A", "Node_B"],
        readiness_gaps=["Node_C"],
    )
    assert b.is_core_complete() is True


def test_readiness_baseline_is_core_complete_false():
    """15. is_core_complete() returns False when core overlaps gap."""
    from core.startup_tier_model import ActiveNodeReadinessBaseline
    b = ActiveNodeReadinessBaseline(
        core_tier=["Node_A", "Node_B"],
        readiness_gaps=["Node_A"],
    )
    assert b.is_core_complete() is False


# ── 16–21: build_readiness_baseline() ────────────────────────────────────────

def test_build_readiness_baseline_returns_instance():
    """16. build_readiness_baseline() returns an ActiveNodeReadinessBaseline."""
    from core.startup_tier_model import build_readiness_baseline, ActiveNodeReadinessBaseline
    b = build_readiness_baseline()
    assert isinstance(b, ActiveNodeReadinessBaseline)


def test_build_readiness_baseline_core_count(ndj):
    """17. build_readiness_baseline() core_tier count >= 1."""
    from core.startup_tier_model import build_readiness_baseline
    b = build_readiness_baseline(node_configs=ndj.get("nodes", {}))
    assert b.core_tier_count >= 1, f"Expected >= 1 core-tier nodes, got {b.core_tier_count}"


def test_build_readiness_baseline_standard_gte_core(ndj):
    """18. standard_tier count >= core_tier count."""
    from core.startup_tier_model import build_readiness_baseline
    b = build_readiness_baseline(node_configs=ndj.get("nodes", {}))
    assert b.standard_tier_count >= b.core_tier_count


def test_build_readiness_baseline_core_subset_standard(ndj):
    """19. Core ⊆ Standard (subset invariant)."""
    from core.startup_tier_model import build_readiness_baseline
    b = build_readiness_baseline(node_configs=ndj.get("nodes", {}))
    assert set(b.core_tier).issubset(set(b.standard_tier)), (
        f"Core nodes not a subset of Standard: "
        f"{set(b.core_tier) - set(b.standard_tier)}"
    )


def test_build_readiness_baseline_active_count(ndj):
    """20. build_readiness_baseline() active_baseline count >= 1."""
    from core.startup_tier_model import build_readiness_baseline
    b = build_readiness_baseline(node_configs=ndj.get("nodes", {}))
    assert b.active_baseline_count >= 1


def test_build_readiness_baseline_gap_count_non_negative(ndj):
    """21. readiness_gap_count is an int >= 0."""
    from core.startup_tier_model import build_readiness_baseline
    b = build_readiness_baseline(node_configs=ndj.get("nodes", {}))
    assert isinstance(b.readiness_gap_count, int)
    assert b.readiness_gap_count >= 0


# ── 22–27: check_tier_model_metadata() ───────────────────────────────────────

def test_check_metadata_key_present(ndj):
    """22. check_tier_model_metadata() returns True for metadata_key_present."""
    from core.startup_tier_model import check_tier_model_metadata
    result = check_tier_model_metadata(ndj)
    assert result["metadata_key_present"] is True


def test_check_metadata_all_three_tiers(ndj):
    """23. check_tier_model_metadata() returns True for all_three_tiers_defined."""
    from core.startup_tier_model import check_tier_model_metadata
    result = check_tier_model_metadata(ndj)
    assert result["all_three_tiers_defined"] is True


def test_check_metadata_core_rule(ndj):
    """24. check_tier_model_metadata() returns True for core_tier_has_selection_rule."""
    from core.startup_tier_model import check_tier_model_metadata
    result = check_tier_model_metadata(ndj)
    assert result["core_tier_has_selection_rule"] is True


def test_check_metadata_standard_rule(ndj):
    """25. check_tier_model_metadata() returns True for standard_tier_has_selection_rule."""
    from core.startup_tier_model import check_tier_model_metadata
    result = check_tier_model_metadata(ndj)
    assert result["standard_tier_has_selection_rule"] is True


def test_check_metadata_full_rule(ndj):
    """26. check_tier_model_metadata() returns True for full_tier_has_selection_rule."""
    from core.startup_tier_model import check_tier_model_metadata
    result = check_tier_model_metadata(ndj)
    assert result["full_tier_has_selection_rule"] is True


def test_check_metadata_invariants(ndj):
    """27. check_tier_model_metadata() returns True for invariants_listed."""
    from core.startup_tier_model import check_tier_model_metadata
    result = check_tier_model_metadata(ndj)
    assert result["invariants_listed"] is True


# ── 28–31: node_dependencies.json _startup_tier_model key ────────────────────

def test_ndj_contains_startup_tier_model_key(ndj):
    """28. node_dependencies.json contains _startup_tier_model key."""
    assert "_startup_tier_model" in ndj


def test_ndj_tier_meta_has_tiers(tier_meta):
    """29. _startup_tier_model has 'tiers' sub-key."""
    assert "tiers" in tier_meta


def test_ndj_tier_meta_all_three_tiers(tier_meta):
    """30. _startup_tier_model['tiers'] contains 'Core', 'Standard', 'Full'."""
    tiers = tier_meta.get("tiers", {})
    assert "Core" in tiers
    assert "Standard" in tiers
    assert "Full" in tiers


def test_ndj_tier_meta_invariants(tier_meta):
    """31. _startup_tier_model['invariants'] is a non-empty list."""
    invariants = tier_meta.get("invariants", [])
    assert isinstance(invariants, list)
    assert len(invariants) >= 1


# ── 32–48: NodeSystemLauncher tier helpers ────────────────────────────────────

def test_launcher_tier_core_constant():
    """32. NodeSystemLauncher.STARTUP_TIER_CORE == 'Core'."""
    from launcher.node_startup import NodeSystemLauncher
    assert NodeSystemLauncher.STARTUP_TIER_CORE == "Core"


def test_launcher_tier_standard_constant():
    """33. NodeSystemLauncher.STARTUP_TIER_STANDARD == 'Standard'."""
    from launcher.node_startup import NodeSystemLauncher
    assert NodeSystemLauncher.STARTUP_TIER_STANDARD == "Standard"


def test_launcher_tier_full_constant():
    """34. NodeSystemLauncher.STARTUP_TIER_FULL == 'Full'."""
    from launcher.node_startup import NodeSystemLauncher
    assert NodeSystemLauncher.STARTUP_TIER_FULL == "Full"


def test_launcher_has_get_tier_nodes():
    """35. NodeSystemLauncher has get_tier_nodes method."""
    from launcher.node_startup import NodeSystemLauncher
    assert callable(getattr(NodeSystemLauncher, "get_tier_nodes", None))


def test_launcher_has_get_readiness_baseline():
    """36. NodeSystemLauncher has get_readiness_baseline method."""
    from launcher.node_startup import NodeSystemLauncher
    assert callable(getattr(NodeSystemLauncher, "get_readiness_baseline", None))


def test_launcher_get_tier_core_non_empty(launcher):
    """37. get_tier_nodes('Core') returns non-empty list."""
    nodes = launcher.get_tier_nodes(launcher.STARTUP_TIER_CORE)
    assert isinstance(nodes, list)
    assert len(nodes) >= 1


def test_launcher_get_tier_standard_non_empty(launcher):
    """38. get_tier_nodes('Standard') returns non-empty list."""
    nodes = launcher.get_tier_nodes(launcher.STARTUP_TIER_STANDARD)
    assert isinstance(nodes, list)
    assert len(nodes) >= 1


def test_launcher_get_tier_full_non_empty(launcher):
    """39. get_tier_nodes('Full') returns non-empty list."""
    nodes = launcher.get_tier_nodes(launcher.STARTUP_TIER_FULL)
    assert isinstance(nodes, list)
    assert len(nodes) >= 1


def test_launcher_core_subset_standard(launcher):
    """40. get_tier_nodes('Core') ⊆ get_tier_nodes('Standard')."""
    core = set(launcher.get_tier_nodes(launcher.STARTUP_TIER_CORE))
    standard = set(launcher.get_tier_nodes(launcher.STARTUP_TIER_STANDARD))
    assert core.issubset(standard), (
        f"Core nodes not a subset of Standard: {core - standard}"
    )


def test_launcher_standard_subset_full(launcher):
    """41. get_tier_nodes('Standard') ⊆ get_tier_nodes('Full')."""
    standard = set(launcher.get_tier_nodes(launcher.STARTUP_TIER_STANDARD))
    full = set(launcher.get_tier_nodes(launcher.STARTUP_TIER_FULL))
    assert standard.issubset(full), (
        f"Standard nodes not a subset of Full: {standard - full}"
    )


def test_launcher_get_tier_raises_for_unknown(launcher):
    """42. get_tier_nodes raises ValueError for unknown tier."""
    with pytest.raises(ValueError, match="Unknown startup tier"):
        launcher.get_tier_nodes("Unknown")


def test_launcher_core_tier_sorted(launcher):
    """43. get_tier_nodes('Core') is sorted (by priority then name)."""
    nodes = launcher.get_tier_nodes(launcher.STARTUP_TIER_CORE)
    # Verify it returns the same list in sorted order by priority+name
    def _key(n):
        cfg = launcher.node_configs.get(n, {})
        return (cfg.get("priority", 99) if isinstance(cfg, dict) else 99, n)
    assert nodes == sorted(nodes, key=_key)


def test_launcher_full_tier_excludes_skip(launcher):
    """44. get_tier_nodes('Full') excludes skip-policy nodes."""
    full = launcher.get_tier_nodes(launcher.STARTUP_TIER_FULL)
    for node in full:
        cfg = launcher.node_configs.get(node, {})
        policy = cfg.get("startup_policy", "active") if isinstance(cfg, dict) else "active"
        assert policy != "skip", f"skip node {node} found in Full tier"


def test_launcher_readiness_baseline_keys(launcher):
    """45. get_readiness_baseline() returns dict with expected keys."""
    result = launcher.get_readiness_baseline()
    assert isinstance(result, dict)
    for key in ("core_tier", "standard_tier", "active_baseline",
                "optional_governed", "readiness_gaps", "summary"):
        assert key in result, f"Missing key in readiness baseline: {key}"


def test_launcher_readiness_baseline_summary_gap_count(launcher):
    """46. get_readiness_baseline() summary has readiness_gap_count."""
    result = launcher.get_readiness_baseline()
    summary = result.get("summary", {})
    assert "readiness_gap_count" in summary
    assert isinstance(summary["readiness_gap_count"], int)


def test_launcher_tier_core_matches_get_core_nodes(launcher):
    """47. get_tier_nodes('Core') matches get_core_nodes() (same set, disk-filtered)."""
    tier_core = set(launcher.get_tier_nodes(launcher.STARTUP_TIER_CORE))
    get_core = set(launcher.get_core_nodes())
    # get_core_nodes() may fall back to first-10 if no 'core' group entries found;
    # when core groups exist, the sets should be equal.
    has_core_group = any(
        isinstance(cfg, dict) and cfg.get("group") == "core"
        for cfg in launcher.node_configs.values()
    )
    if has_core_group:
        assert tier_core == get_core, (
            f"get_tier_nodes('Core') and get_core_nodes() differ: "
            f"tier_only={tier_core - get_core}, core_only={get_core - tier_core}"
        )


def test_launcher_tier_full_matches_get_active_nodes(launcher):
    """48. get_tier_nodes('Full') matches get_active_nodes() (same set)."""
    tier_full = set(launcher.get_tier_nodes(launcher.STARTUP_TIER_FULL))
    active = set(launcher.get_active_nodes())
    assert tier_full == active, (
        f"get_tier_nodes('Full') and get_active_nodes() differ: "
        f"tier_only={tier_full - active}, active_only={active - tier_full}"
    )


# ── 49–50: Documentation ──────────────────────────────────────────────────────

def test_startup_tier_model_doc_exists():
    """49. docs/STARTUP_TIER_MODEL.md exists."""
    assert TIER_DOC_PATH.exists(), f"Missing: {TIER_DOC_PATH}"


def test_startup_tier_model_doc_references_tiers():
    """50. docs/STARTUP_TIER_MODEL.md references all three tier names."""
    content = TIER_DOC_PATH.read_text(encoding="utf-8")
    for tier in ("Core", "Standard", "Full"):
        assert tier in content, f"Tier '{tier}' not mentioned in STARTUP_TIER_MODEL.md"
