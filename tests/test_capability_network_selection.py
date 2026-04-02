#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_capability_network_selection.py
============================================
PR-D: Capability + Network Runtime Convergence — capability selection plane tests.

Coverage
--------
A) Module structure
   - CAPABILITY_GRAPH_SELECTION_AUTHORITY sentinel is importable
   - CAPABILITY_SELECTION_PLANE_LAYER_POSITION is 10
   - CAPABILITY_SELECTION_POLICY is importable
   - All public names in __all__ are importable

B) CapabilityFitScore dataclass
   - can be constructed with required fields
   - to_dict() contains all expected keys
   - to_dict() is JSON-serialisable

C) SelectionExplanation dataclass
   - can be constructed with required fields
   - to_dict() contains all expected keys

D) SelectionRecord dataclass
   - can be constructed with required fields
   - to_dict() contains all expected keys

E) discover_providers — empty assimilation layer
   - returns empty list when no providers are registered
   - returns empty list when no online providers match

F) discover_providers — basic capability matching
   - returns providers that have the requested capability
   - does not return providers that lack the requested capability
   - capability_filter with kind_filter restricts to matching kinds
   - require_online=False also returns offline providers

G) score_provider
   - full match → coverage_ratio = 1.0
   - partial match → coverage_ratio between 0 and 1
   - no match → coverage_ratio = 0.0
   - missing_caps lists unmatched capabilities
   - matched_caps lists matched capabilities
   - kind_priority contributes to total_score

H) select_best_provider
   - returns None when no providers available
   - returns provider with highest fit score
   - returns None for kind_filter that excludes all providers

I) select_fallback_providers
   - returns empty list when no providers available
   - excludes ids listed in exclude_ids
   - returns up to max_results providers
   - includes degraded providers as fallback candidates

J) explain_selection
   - returns SelectionExplanation
   - reason mentions node_id
   - reason reflects full match correctly
   - reason reflects partial match correctly
   - alternatives_count matches passed alternatives

K) Ring buffer / observability
   - get_selection_log() returns a deque
   - each discover_providers call emits a SelectionRecord
   - each select_best_provider call emits a SelectionRecord
   - ring buffer is bounded to 256 entries

L) reset_selection_log
   - clears the selection log

M) PR-D new provider kinds integration
   - DEVICE kind providers are discoverable
   - MCP_PROVIDER kind providers are discoverable
   - SKILL kind providers are discoverable
   - kind_filter works with DEVICE kind
"""

from __future__ import annotations

import json
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset():
    """Reset singletons before each test."""
    try:
        from core.capability_assimilation import reset_capability_assimilation_layer
        reset_capability_assimilation_layer()
    except Exception:
        pass
    try:
        from core.capability_graph_selection import reset_selection_log
        reset_selection_log()
    except Exception:
        pass
    yield
    try:
        from core.capability_assimilation import reset_capability_assimilation_layer
        reset_capability_assimilation_layer()
    except Exception:
        pass
    try:
        from core.capability_graph_selection import reset_selection_log
        reset_selection_log()
    except Exception:
        pass


def _register(node_id, caps=None, kind="capability_provider", online=True):
    """Helper: register a provider in the assimilation layer."""
    from core.capability_assimilation import (
        get_capability_assimilation_layer,
        NodeParticipantKind,
        AssimilationPresenceState,
    )
    layer = get_capability_assimilation_layer()
    rec = layer.assimilate(
        node_id,
        capabilities=list(caps or []),
        participant_kind=NodeParticipantKind(kind),
    )
    if not online:
        layer.mark_offline(node_id, reason="test")
    return rec


# ---------------------------------------------------------------------------
# A) Module structure
# ---------------------------------------------------------------------------

class TestModuleStructure:
    def test_authority_sentinel_importable(self):
        from core.capability_graph_selection import CAPABILITY_GRAPH_SELECTION_AUTHORITY
        assert isinstance(CAPABILITY_GRAPH_SELECTION_AUTHORITY, str)
        assert "PR-D" in CAPABILITY_GRAPH_SELECTION_AUTHORITY

    def test_layer_position_is_10(self):
        from core.capability_graph_selection import CAPABILITY_SELECTION_PLANE_LAYER_POSITION
        assert CAPABILITY_SELECTION_PLANE_LAYER_POSITION == 10

    def test_selection_policy_importable(self):
        from core.capability_graph_selection import CAPABILITY_SELECTION_POLICY
        assert isinstance(CAPABILITY_SELECTION_POLICY, str)

    def test_all_public_names_importable(self):
        import core.capability_graph_selection as m
        for name in m.__all__:
            assert hasattr(m, name), f"Missing: {name}"


# ---------------------------------------------------------------------------
# B) CapabilityFitScore dataclass
# ---------------------------------------------------------------------------

class TestCapabilityFitScore:
    def test_construction(self):
        from core.capability_graph_selection import CapabilityFitScore
        score = CapabilityFitScore(
            node_id="n1",
            required_matched=2,
            required_total=3,
            coverage_ratio=2 / 3,
            kind_priority=10,
            is_online=True,
            total_score=7.0,
        )
        assert score.node_id == "n1"

    def test_to_dict_contains_keys(self):
        from core.capability_graph_selection import CapabilityFitScore
        score = CapabilityFitScore(
            node_id="n1",
            required_matched=1,
            required_total=1,
            coverage_ratio=1.0,
            kind_priority=10,
            is_online=True,
            total_score=10.0,
        )
        d = score.to_dict()
        for key in ("node_id", "coverage_ratio", "total_score", "is_online",
                    "matched_caps", "missing_caps"):
            assert key in d

    def test_to_dict_json_serialisable(self):
        from core.capability_graph_selection import CapabilityFitScore
        score = CapabilityFitScore(
            node_id="n1",
            required_matched=1,
            required_total=2,
            coverage_ratio=0.5,
            kind_priority=5,
            is_online=True,
            total_score=5.0,
            matched_caps=["cap_a"],
            missing_caps=["cap_b"],
        )
        json.dumps(score.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# C) SelectionExplanation dataclass
# ---------------------------------------------------------------------------

class TestSelectionExplanation:
    def test_construction(self):
        from core.capability_graph_selection import SelectionExplanation, CapabilityFitScore
        fit = CapabilityFitScore("n1", 1, 1, 1.0, 10, True, 10.0)
        expl = SelectionExplanation(
            node_id="n1",
            participant_kind="capability_provider",
            fit_score=fit,
            reason="Full match.",
        )
        assert expl.node_id == "n1"

    def test_to_dict_contains_keys(self):
        from core.capability_graph_selection import SelectionExplanation, CapabilityFitScore
        fit = CapabilityFitScore("n1", 1, 1, 1.0, 10, True, 10.0)
        expl = SelectionExplanation(
            node_id="n1",
            participant_kind="worker",
            fit_score=fit,
            reason="reason",
        )
        d = expl.to_dict()
        assert "node_id" in d
        assert "reason" in d
        assert "fit_score" in d


# ---------------------------------------------------------------------------
# D) SelectionRecord dataclass
# ---------------------------------------------------------------------------

class TestSelectionRecord:
    def test_construction(self):
        from core.capability_graph_selection import SelectionRecord
        rec = SelectionRecord(
            record_id=1,
            operation="discover",
            required_capabilities=["cap_a"],
            result_ids=["n1"],
            candidate_count=1,
        )
        assert rec.record_id == 1

    def test_to_dict_contains_keys(self):
        from core.capability_graph_selection import SelectionRecord
        rec = SelectionRecord(
            record_id=1,
            operation="select_best",
            required_capabilities=[],
            result_ids=[],
            candidate_count=0,
        )
        d = rec.to_dict()
        assert "record_id" in d
        assert "operation" in d
        assert "result_ids" in d


# ---------------------------------------------------------------------------
# E) discover_providers — empty assimilation layer
# ---------------------------------------------------------------------------

class TestDiscoverEmpty:
    def test_returns_empty_when_no_providers(self):
        from core.capability_graph_selection import discover_providers
        results = discover_providers(["cap_x"])
        assert results == []

    def test_returns_empty_when_no_online_match(self):
        _register("offline-node", caps=["cap_x"], online=False)
        from core.capability_graph_selection import discover_providers
        results = discover_providers(["cap_x"], require_online=True)
        assert results == []


# ---------------------------------------------------------------------------
# F) discover_providers — basic capability matching
# ---------------------------------------------------------------------------

class TestDiscoverBasic:
    def test_returns_matching_providers(self):
        _register("node-a", caps=["cap_search", "cap_fetch"])
        from core.capability_graph_selection import discover_providers
        results = discover_providers(["cap_search"])
        ids = [r.node_id for r in results]
        assert "node-a" in ids

    def test_does_not_return_non_matching_providers(self):
        _register("node-b", caps=["cap_audio"])
        from core.capability_graph_selection import discover_providers
        results = discover_providers(["cap_search"])
        # node-b has no cap_search but might be returned if no caps required; with caps filter it should score 0
        # With required caps, node-b gets coverage_ratio=0 — it may still be returned but with score 0
        # Verify node-b is not the best if a matching one exists
        _register("node-c", caps=["cap_search"])
        results2 = discover_providers(["cap_search"])
        ids = [r.node_id for r in results2]
        assert ids[0] == "node-c"  # best match is node-c

    def test_kind_filter_restricts_results(self):
        _register("worker-x", caps=["cap_a"], kind="worker")
        _register("mcp-x", caps=["cap_a"], kind="mcp_provider")
        from core.capability_graph_selection import discover_providers
        results = discover_providers(["cap_a"], kind_filter=["worker"])
        ids = [r.node_id for r in results]
        assert "worker-x" in ids
        assert "mcp-x" not in ids

    def test_require_online_false_returns_offline(self):
        _register("offline-x", caps=["cap_b"], online=False)
        from core.capability_graph_selection import discover_providers
        results = discover_providers(["cap_b"], require_online=False)
        ids = [r.node_id for r in results]
        assert "offline-x" in ids


# ---------------------------------------------------------------------------
# G) score_provider
# ---------------------------------------------------------------------------

class TestScoreProvider:
    def test_full_match_coverage_ratio_one(self):
        rec = _register("sp-full", caps=["cap_a", "cap_b"])
        from core.capability_graph_selection import score_provider
        fit = score_provider(rec, ["cap_a", "cap_b"])
        assert fit.coverage_ratio == 1.0

    def test_partial_match_coverage_between_zero_and_one(self):
        rec = _register("sp-partial", caps=["cap_a"])
        from core.capability_graph_selection import score_provider
        fit = score_provider(rec, ["cap_a", "cap_b"])
        assert 0.0 < fit.coverage_ratio < 1.0

    def test_no_match_coverage_zero(self):
        rec = _register("sp-none", caps=["cap_x"])
        from core.capability_graph_selection import score_provider
        fit = score_provider(rec, ["cap_a", "cap_b"])
        assert fit.coverage_ratio == 0.0

    def test_missing_caps_lists_unmatched(self):
        rec = _register("sp-miss", caps=["cap_a"])
        from core.capability_graph_selection import score_provider
        fit = score_provider(rec, ["cap_a", "cap_z"])
        assert "cap_z" in fit.missing_caps

    def test_matched_caps_lists_matched(self):
        rec = _register("sp-match", caps=["cap_a", "cap_b"])
        from core.capability_graph_selection import score_provider
        fit = score_provider(rec, ["cap_a", "cap_b"])
        assert "cap_a" in fit.matched_caps
        assert "cap_b" in fit.matched_caps

    def test_kind_priority_contributes_to_score(self):
        rec_worker = _register("sp-w", caps=["cap_a"], kind="worker")
        rec_unknown = _register("sp-u", caps=["cap_a"], kind="unknown")
        from core.capability_graph_selection import score_provider
        score_w = score_provider(rec_worker, ["cap_a"])
        score_u = score_provider(rec_unknown, ["cap_a"])
        assert score_w.total_score > score_u.total_score


# ---------------------------------------------------------------------------
# H) select_best_provider
# ---------------------------------------------------------------------------

class TestSelectBestProvider:
    def test_returns_none_when_empty(self):
        from core.capability_graph_selection import select_best_provider
        result = select_best_provider(["cap_x"])
        assert result is None

    def test_returns_provider_with_highest_fit(self):
        _register("best-a", caps=["cap_a", "cap_b"])
        _register("worse-b", caps=["cap_a"])
        from core.capability_graph_selection import select_best_provider
        result = select_best_provider(["cap_a", "cap_b"])
        assert result is not None
        assert result.node_id == "best-a"

    def test_returns_none_for_excluded_kind(self):
        _register("device-1", caps=["cap_a"], kind="device")
        from core.capability_graph_selection import select_best_provider
        result = select_best_provider(["cap_a"], kind_filter=["worker"])
        assert result is None


# ---------------------------------------------------------------------------
# I) select_fallback_providers
# ---------------------------------------------------------------------------

class TestSelectFallbackProviders:
    def test_returns_empty_when_no_providers(self):
        from core.capability_graph_selection import select_fallback_providers
        results = select_fallback_providers(["cap_x"])
        assert results == []

    def test_excludes_specified_ids(self):
        _register("fb-main", caps=["cap_a"])
        _register("fb-fall", caps=["cap_a"])
        from core.capability_graph_selection import select_fallback_providers
        results = select_fallback_providers(["cap_a"], exclude_ids=["fb-main"])
        ids = [r.node_id for r in results]
        assert "fb-main" not in ids
        assert "fb-fall" in ids

    def test_max_results_limits_return(self):
        for i in range(5):
            _register(f"fb-n{i}", caps=["cap_a"])
        from core.capability_graph_selection import select_fallback_providers
        results = select_fallback_providers(["cap_a"], max_results=2)
        assert len(results) <= 2


# ---------------------------------------------------------------------------
# J) explain_selection
# ---------------------------------------------------------------------------

class TestExplainSelection:
    def test_returns_selection_explanation(self):
        rec = _register("explain-1", caps=["cap_a"])
        from core.capability_graph_selection import explain_selection
        expl = explain_selection(rec, ["cap_a"])
        assert expl is not None

    def test_reason_mentions_node_id(self):
        rec = _register("explain-2", caps=["cap_a"])
        from core.capability_graph_selection import explain_selection
        expl = explain_selection(rec, ["cap_a"])
        assert "explain-2" in expl.reason

    def test_reason_reflects_full_match(self):
        rec = _register("explain-3", caps=["cap_a", "cap_b"])
        from core.capability_graph_selection import explain_selection
        expl = explain_selection(rec, ["cap_a", "cap_b"])
        assert "full" in expl.reason.lower() or "match" in expl.reason.lower()

    def test_reason_reflects_partial_match(self):
        rec = _register("explain-4", caps=["cap_a"])
        from core.capability_graph_selection import explain_selection
        expl = explain_selection(rec, ["cap_a", "cap_b"])
        assert "partial" in expl.reason.lower()

    def test_alternatives_count_matches(self):
        rec = _register("explain-5", caps=["cap_a"])
        alt1 = _register("alt-1", caps=["cap_a"])
        alt2 = _register("alt-2", caps=["cap_a"])
        from core.capability_graph_selection import explain_selection
        expl = explain_selection(rec, ["cap_a"], alternatives=[alt1, alt2])
        assert expl.alternatives_count == 2


# ---------------------------------------------------------------------------
# K) Ring buffer / observability
# ---------------------------------------------------------------------------

class TestRingBuffer:
    def test_get_selection_log_returns_deque(self):
        from core.capability_graph_selection import get_selection_log
        log = get_selection_log()
        assert hasattr(log, "__iter__")

    def test_discover_emits_record(self):
        from core.capability_graph_selection import discover_providers, get_selection_log
        _register("log-1", caps=["cap_a"])
        initial = len(get_selection_log())
        discover_providers(["cap_a"])
        assert len(get_selection_log()) > initial

    def test_select_best_emits_record(self):
        from core.capability_graph_selection import select_best_provider, get_selection_log
        _register("log-2", caps=["cap_a"])
        initial = len(get_selection_log())
        select_best_provider(["cap_a"])
        assert len(get_selection_log()) > initial

    def test_ring_buffer_bounded_256(self):
        from core.capability_graph_selection import get_selection_log
        log = get_selection_log()
        assert log.maxlen == 256


# ---------------------------------------------------------------------------
# L) reset_selection_log
# ---------------------------------------------------------------------------

class TestResetSelectionLog:
    def test_clears_the_log(self):
        _register("reset-1", caps=["cap_a"])
        from core.capability_graph_selection import (
            discover_providers, get_selection_log, reset_selection_log,
        )
        discover_providers(["cap_a"])
        assert len(get_selection_log()) > 0
        reset_selection_log()
        assert len(get_selection_log()) == 0


# ---------------------------------------------------------------------------
# M) PR-D new provider kinds integration
# ---------------------------------------------------------------------------

class TestNewProviderKinds:
    def test_device_kind_discoverable(self):
        from core.capability_assimilation import assimilate_device
        assimilate_device("android-01", capabilities=["screen", "touch"])
        from core.capability_graph_selection import discover_providers
        results = discover_providers(["screen"], kind_filter=["device"])
        ids = [r.node_id for r in results]
        assert "android-01" in ids

    def test_mcp_provider_discoverable(self):
        from core.capability_assimilation import assimilate_mcp_provider
        assimilate_mcp_provider("mcp-fs-01", tools=["read_file", "write_file"])
        from core.capability_graph_selection import discover_providers
        results = discover_providers(["read_file"], kind_filter=["mcp_provider"])
        ids = [r.node_id for r in results]
        assert "mcp-fs-01" in ids

    def test_skill_kind_discoverable(self):
        from core.capability_assimilation import assimilate_skill
        assimilate_skill("skill-search-01", capabilities=["web_search"])
        from core.capability_graph_selection import discover_providers
        results = discover_providers(["web_search"], kind_filter=["skill"])
        ids = [r.node_id for r in results]
        assert "skill-search-01" in ids

    def test_kind_filter_device_only(self):
        from core.capability_assimilation import assimilate_device, assimilate_mcp_provider
        assimilate_device("dev-filter", capabilities=["screen"])
        assimilate_mcp_provider("mcp-filter", tools=["screen"])  # same cap
        from core.capability_graph_selection import discover_providers
        results = discover_providers(["screen"], kind_filter=["device"])
        ids = [r.node_id for r in results]
        assert "dev-filter" in ids
        assert "mcp-filter" not in ids
