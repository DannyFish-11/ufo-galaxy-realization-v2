#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5_hybrid_execution_policy.py
==========================================
PR-5: Hybrid Execution Policy — test suite.

Coverage
--------
A  — Module sentinels are importable non-empty strings.
B  — HybridExecutionMode enum: all 5 values present.
C  — HybridExecutionMode.from_string: known value.
D  — HybridExecutionMode.from_string: unknown value returns default.
E  — HybridExecutionMode.from_string: unknown with no default returns sequential_degrade.
F  — HybridExecutionMode.is_concurrent: parallel_race only.
G  — HybridExecutionMode.is_degrade_chain: sequential_degrade, local_preferred, remote_preferred.
H  — HybridExecutionDecision: construction with required fields.
I  — HybridExecutionDecision.to_dict round-trip.
J  — HybridExecutionDecision.from_dict.
K  — HybridExecutionDecision.from_dict: non-dict raises ValueError.
L  — HybridExecutionDecision.to_json produces valid JSON.
M  — HybridExecutionPolicy.evaluate: force_mode overrides all rules.
N  — HybridExecutionPolicy.evaluate: staged_actions → staged_hybrid.
O  — HybridExecutionPolicy.evaluate: latency_sensitive + A2A + GUI → parallel_race.
P  — HybridExecutionPolicy.evaluate: prefer_local → local_preferred.
Q  — HybridExecutionPolicy.evaluate: prefer_remote → remote_preferred.
R  — HybridExecutionPolicy.evaluate: default → sequential_degrade.
S  — HybridExecutionPolicy.evaluate: latency_sensitive but no A2A → not parallel_race.
T  — HybridExecutionPolicy.evaluate: latency_sensitive but no GUI → not parallel_race.
U  — HybridExecutionPolicy.evaluate: force_mode takes priority over staged_actions.
V  — HybridExecutionPolicy.evaluate: force_mode takes priority over latency_sensitive.
W  — HybridExecutionPolicy.describe_mode: returns non-empty string for each mode.
X  — HybridExecutionDecision.decision_id is auto-generated and unique.
Y  — HybridExecutionDecision.decided_at is a recent timestamp.
Z  — HybridExecutionDecision.policy_version matches policy.
AA — evaluate_hybrid_execution_mode module-level function.
AB — get_hybrid_execution_policy returns singleton.
AC — reset_hybrid_execution_policy clears singleton.
AD — Context snapshot excludes non-serialisable values.
AE — HybridExecutionDecision.context_snapshot captures context fields.
AF — parallel_race decision has confidence > sequential_degrade default.
AG — staged_hybrid confidence is high.
AH — force_mode with unknown string defaults to sequential_degrade.
AI — HYBRID_EXECUTION_POLICY_PR5_SENTINEL is a non-empty string.
AJ — All 5 modes are described by describe_mode (non-empty, no KeyError).
"""

from __future__ import annotations

import json
import time

import pytest

from core.hybrid_execution_policy import (
    HYBRID_EXECUTION_POLICY_IS_AUTHORITY,
    SEQUENTIAL_DEGRADE_IS_EXPLICIT_POLICY,
    PARALLEL_RACE_IS_REAL_HYBRID_POLICY,
    DECISION_IS_SERIALISABLE_POLICY,
    HYBRID_EXECUTION_POLICY_PR5_SENTINEL,
    HybridExecutionMode,
    HybridExecutionDecision,
    HybridExecutionPolicy,
    evaluate_hybrid_execution_mode,
    get_hybrid_execution_policy,
    reset_hybrid_execution_policy,
)


# ---------------------------------------------------------------------------
# A — Sentinels
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_authority_sentinel(self):
        assert isinstance(HYBRID_EXECUTION_POLICY_IS_AUTHORITY, str)
        assert HYBRID_EXECUTION_POLICY_IS_AUTHORITY

    def test_sequential_degrade_policy_sentinel(self):
        assert isinstance(SEQUENTIAL_DEGRADE_IS_EXPLICIT_POLICY, str)
        assert "sequential_degrade" in SEQUENTIAL_DEGRADE_IS_EXPLICIT_POLICY.lower() \
            or "SEQUENTIAL" in SEQUENTIAL_DEGRADE_IS_EXPLICIT_POLICY

    def test_parallel_race_policy_sentinel(self):
        assert isinstance(PARALLEL_RACE_IS_REAL_HYBRID_POLICY, str)
        assert "parallel_race" in PARALLEL_RACE_IS_REAL_HYBRID_POLICY.lower() \
            or "PARALLEL" in PARALLEL_RACE_IS_REAL_HYBRID_POLICY

    def test_serialisable_policy_sentinel(self):
        assert isinstance(DECISION_IS_SERIALISABLE_POLICY, str)

    def test_pr5_sentinel(self):
        assert isinstance(HYBRID_EXECUTION_POLICY_PR5_SENTINEL, str)
        assert HYBRID_EXECUTION_POLICY_PR5_SENTINEL


# ---------------------------------------------------------------------------
# B–G — HybridExecutionMode
# ---------------------------------------------------------------------------

class TestHybridExecutionMode:
    def test_all_five_modes_present(self):
        modes = {m.value for m in HybridExecutionMode}
        assert "sequential_degrade" in modes
        assert "parallel_race" in modes
        assert "staged_hybrid" in modes
        assert "local_preferred" in modes
        assert "remote_preferred" in modes
        assert len(modes) == 5

    def test_from_string_known(self):
        m = HybridExecutionMode.from_string("parallel_race")
        assert m == HybridExecutionMode.parallel_race

    def test_from_string_unknown_returns_default(self):
        m = HybridExecutionMode.from_string("nonexistent", default=HybridExecutionMode.staged_hybrid)
        assert m == HybridExecutionMode.staged_hybrid

    def test_from_string_unknown_no_default_returns_sequential_degrade(self):
        m = HybridExecutionMode.from_string("nonexistent")
        assert m == HybridExecutionMode.sequential_degrade

    def test_is_concurrent_parallel_race_only(self):
        assert HybridExecutionMode.parallel_race.is_concurrent is True
        for mode in HybridExecutionMode:
            if mode != HybridExecutionMode.parallel_race:
                assert mode.is_concurrent is False

    def test_is_degrade_chain(self):
        assert HybridExecutionMode.sequential_degrade.is_degrade_chain is True
        assert HybridExecutionMode.local_preferred.is_degrade_chain is True
        assert HybridExecutionMode.remote_preferred.is_degrade_chain is True
        assert HybridExecutionMode.parallel_race.is_degrade_chain is False
        assert HybridExecutionMode.staged_hybrid.is_degrade_chain is False


# ---------------------------------------------------------------------------
# H–L — HybridExecutionDecision
# ---------------------------------------------------------------------------

class TestHybridExecutionDecision:
    def test_construction(self):
        dec = HybridExecutionDecision(
            mode=HybridExecutionMode.parallel_race,
            reason="test reason",
        )
        assert dec.mode == HybridExecutionMode.parallel_race
        assert dec.reason == "test reason"
        assert dec.decision_id.startswith("hdec_")

    def test_to_dict_round_trip(self):
        dec = HybridExecutionDecision(
            mode=HybridExecutionMode.staged_hybrid,
            reason="staged",
            confidence=0.9,
        )
        d = dec.to_dict()
        assert d["mode"] == "staged_hybrid"
        assert d["reason"] == "staged"
        assert d["confidence"] == 0.9

        dec2 = HybridExecutionDecision.from_dict(d)
        assert dec2.mode == HybridExecutionMode.staged_hybrid
        assert dec2.reason == dec.reason
        assert dec2.decision_id == dec.decision_id

    def test_from_dict(self):
        d = {
            "decision_id": "hdec_abc",
            "mode": "local_preferred",
            "reason": "prefer local",
            "context_snapshot": {"app_id": "com.example"},
            "confidence": 0.85,
            "decided_at": 1000.0,
            "policy_version": "1.0",
        }
        dec = HybridExecutionDecision.from_dict(d)
        assert dec.mode == HybridExecutionMode.local_preferred
        assert dec.decision_id == "hdec_abc"
        assert dec.confidence == 0.85

    def test_from_dict_non_dict_raises(self):
        with pytest.raises(ValueError):
            HybridExecutionDecision.from_dict("not a dict")

    def test_to_json_valid(self):
        dec = HybridExecutionDecision(
            mode=HybridExecutionMode.remote_preferred,
            reason="json test",
        )
        s = dec.to_json()
        obj = json.loads(s)
        assert obj["mode"] == "remote_preferred"


# ---------------------------------------------------------------------------
# M–V — HybridExecutionPolicy.evaluate
# ---------------------------------------------------------------------------

class TestHybridExecutionPolicyEvaluate:
    def setup_method(self):
        self.policy = HybridExecutionPolicy()

    def test_force_mode_overrides_all(self):
        ctx = {
            "force_mode": "staged_hybrid",
            "latency_sensitive": True,
            "has_a2a": True,
            "has_gui": True,
        }
        dec = self.policy.evaluate(ctx)
        assert dec.mode == HybridExecutionMode.staged_hybrid
        assert "force_mode" in dec.reason.lower() or "force" in dec.reason.lower()

    def test_staged_actions_gives_staged_hybrid(self):
        ctx = {"staged_actions": ["fetch_data", "render_ui"]}
        dec = self.policy.evaluate(ctx)
        assert dec.mode == HybridExecutionMode.staged_hybrid

    def test_latency_sensitive_with_a2a_and_gui_gives_parallel_race(self):
        ctx = {"latency_sensitive": True, "has_a2a": True, "has_gui": True}
        dec = self.policy.evaluate(ctx)
        assert dec.mode == HybridExecutionMode.parallel_race

    def test_prefer_local_gives_local_preferred(self):
        ctx = {"prefer_local": True}
        dec = self.policy.evaluate(ctx)
        assert dec.mode == HybridExecutionMode.local_preferred

    def test_prefer_remote_gives_remote_preferred(self):
        ctx = {"prefer_remote": True}
        dec = self.policy.evaluate(ctx)
        assert dec.mode == HybridExecutionMode.remote_preferred

    def test_default_gives_sequential_degrade(self):
        ctx = {}
        dec = self.policy.evaluate(ctx)
        assert dec.mode == HybridExecutionMode.sequential_degrade

    def test_none_context_gives_sequential_degrade(self):
        dec = self.policy.evaluate(None)
        assert dec.mode == HybridExecutionMode.sequential_degrade

    def test_latency_sensitive_no_a2a_does_not_give_parallel_race(self):
        ctx = {"latency_sensitive": True, "has_a2a": False, "has_gui": True}
        dec = self.policy.evaluate(ctx)
        assert dec.mode != HybridExecutionMode.parallel_race

    def test_latency_sensitive_no_gui_does_not_give_parallel_race(self):
        ctx = {"latency_sensitive": True, "has_a2a": True, "has_gui": False}
        dec = self.policy.evaluate(ctx)
        assert dec.mode != HybridExecutionMode.parallel_race

    def test_force_mode_over_staged_actions(self):
        ctx = {
            "force_mode": "parallel_race",
            "staged_actions": ["stage1", "stage2"],
        }
        dec = self.policy.evaluate(ctx)
        assert dec.mode == HybridExecutionMode.parallel_race

    def test_force_mode_over_latency_sensitive(self):
        ctx = {
            "force_mode": "remote_preferred",
            "latency_sensitive": True,
            "has_a2a": True,
            "has_gui": True,
        }
        dec = self.policy.evaluate(ctx)
        assert dec.mode == HybridExecutionMode.remote_preferred


# ---------------------------------------------------------------------------
# W — describe_mode
# ---------------------------------------------------------------------------

class TestDescribeMode:
    def test_all_modes_described(self):
        policy = HybridExecutionPolicy()
        for mode in HybridExecutionMode:
            desc = policy.describe_mode(mode)
            assert isinstance(desc, str)
            assert desc  # non-empty


# ---------------------------------------------------------------------------
# X–AF — miscellaneous
# ---------------------------------------------------------------------------

class TestMiscellaneous:
    def test_decision_id_is_unique(self):
        d1 = HybridExecutionDecision(mode=HybridExecutionMode.parallel_race, reason="r1")
        d2 = HybridExecutionDecision(mode=HybridExecutionMode.parallel_race, reason="r2")
        assert d1.decision_id != d2.decision_id

    def test_decided_at_is_recent(self):
        before = time.time()
        dec = HybridExecutionDecision(mode=HybridExecutionMode.sequential_degrade, reason="x")
        after = time.time()
        assert before <= dec.decided_at <= after

    def test_policy_version_matches(self):
        policy = HybridExecutionPolicy()
        dec = policy.evaluate({})
        assert dec.policy_version == policy.VERSION

    def test_module_level_evaluate_function(self):
        dec = evaluate_hybrid_execution_mode({"prefer_local": True})
        assert dec.mode == HybridExecutionMode.local_preferred

    def test_get_policy_returns_singleton(self):
        reset_hybrid_execution_policy()
        p1 = get_hybrid_execution_policy()
        p2 = get_hybrid_execution_policy()
        assert p1 is p2

    def test_reset_clears_singleton(self):
        reset_hybrid_execution_policy()
        p1 = get_hybrid_execution_policy()
        reset_hybrid_execution_policy()
        p2 = get_hybrid_execution_policy()
        assert p1 is not p2

    def test_context_snapshot_excludes_non_serialisable(self):
        class _NonSerializable:
            pass
        ctx = {"app_id": "com.test", "bad_key": _NonSerializable(), "has_a2a": True}
        dec = evaluate_hybrid_execution_mode(ctx)
        assert "bad_key" not in dec.context_snapshot
        assert dec.context_snapshot.get("app_id") == "com.test"

    def test_context_snapshot_captures_fields(self):
        ctx = {"app_id": "com.test", "has_a2a": True, "has_gui": False}
        dec = evaluate_hybrid_execution_mode(ctx)
        assert "app_id" in dec.context_snapshot or dec.context_snapshot.get("has_a2a") is True

    def test_parallel_race_higher_confidence_than_default(self):
        policy = HybridExecutionPolicy()
        default_dec = policy.evaluate({})
        race_dec = policy.evaluate({"latency_sensitive": True, "has_a2a": True, "has_gui": True})
        assert race_dec.confidence > default_dec.confidence

    def test_staged_hybrid_high_confidence(self):
        dec = evaluate_hybrid_execution_mode({"staged_actions": ["a", "b"]})
        assert dec.confidence >= 0.9

    def test_force_mode_unknown_string_defaults_to_sequential_degrade(self):
        dec = evaluate_hybrid_execution_mode({"force_mode": "does_not_exist"})
        assert dec.mode == HybridExecutionMode.sequential_degrade

    def test_pr5_sentinel_value(self):
        assert "pr5" in HYBRID_EXECUTION_POLICY_PR5_SENTINEL.lower() \
            or "PR5" in HYBRID_EXECUTION_POLICY_PR5_SENTINEL
