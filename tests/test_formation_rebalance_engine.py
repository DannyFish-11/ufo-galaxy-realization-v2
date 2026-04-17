#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_formation_rebalance_engine.py
==========================================
Tests for core/device_formation/formation_rebalance_engine.py

Coverage:
  1.  Module sentinels are importable strings.
  2.  FormationHealthSignal construction and helpers.
  3.  FormationHealthSignal is_healthy / is_degraded.
  4.  MemberRebalanceAction enum values.
  5.  RebalanceDecision construction and to_dict.
  6.  FormationRebalanceEngine — no rebalance needed when all healthy.
  7.  FormationRebalanceEngine — primary unhealthy triggers promotion.
  8.  FormationRebalanceEngine — unhealthy support device is removed.
  9.  FormationRebalanceEngine — degraded device gets WARN action.
  10. FormationRebalanceEngine — SOURCE is never removed.
  11. FormationRebalanceEngine — empty formation returns no-op decision.
  12. FormationRebalanceEngine — reshape with promote action.
  13. FormationRebalanceEngine — reshape with remove action.
  14. FormationRebalanceEngine — reshape always has a PRIMARY after rebalance.
  15. FormationRebalanceEngine — reshape with no rebalance needed returns original.
  16. evaluate_formation_health — convenience function.
  17. apply_rebalance — convenience function.
  18. maybe_promote_fallback — targeted surgery.
  19. maybe_remove_unhealthy — targeted surgery.
  20. apply_rebalance — graceful on empty formation.
  21. core.device_formation __init__ exports rebalance engine symbols.
  22. FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL references formation_resolver.
  23. RebalanceDecision rebalance_needed False when all healthy.
  24. RebalanceDecision reason populated.
  25. FormationRebalanceEngine — custom thresholds.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_group(
    *,
    source_id: Optional[str] = "source-dev",
    primary_id: Optional[str] = "primary-dev",
    fallback_ids: Optional[List[str]] = None,
    support_ids: Optional[List[str]] = None,
    domain: str = "cross_device",
):
    from core.device_formation.formation_group import DeviceFormationGroup
    from core.device_formation.formation_role import FormationMember, FormationRole

    members = []
    if source_id:
        members.append(FormationMember(device_id=source_id, role=FormationRole.SOURCE,
                                        reason="source"))
    if primary_id:
        members.append(FormationMember(device_id=primary_id, role=FormationRole.PRIMARY_EXECUTION,
                                        reason="primary"))
    for fid in (fallback_ids or []):
        members.append(FormationMember(device_id=fid, role=FormationRole.FALLBACK, reason="fallback"))
    for sid in (support_ids or []):
        members.append(FormationMember(device_id=sid, role=FormationRole.SUPPORT, reason="support"))

    return DeviceFormationGroup(
        source_device_id=source_id,
        members=members,
        runtime_domain_intent=domain,
    )


def _health_map(*device_score_pairs):
    from core.device_formation.formation_rebalance_engine import FormationHealthSignal
    return {
        dev_id: FormationHealthSignal(
            device_id=dev_id,
            health_score=score,
            is_reachable=(score > 0),
        )
        for dev_id, score in device_score_pairs
    }


# ---------------------------------------------------------------------------
# 1: Sentinels
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_authority_sentinel(self):
        from core.device_formation.formation_rebalance_engine import FORMATION_REBALANCE_ENGINE_IS_AUTHORITY
        assert isinstance(FORMATION_REBALANCE_ENGINE_IS_AUTHORITY, str)
        assert "FORMATION_REBALANCE_ENGINE" in FORMATION_REBALANCE_ENGINE_IS_AUTHORITY

    def test_gap_closure_sentinel(self):
        from core.device_formation.formation_rebalance_engine import FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL
        assert isinstance(FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL, str)
        assert "formation_resolver" in FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL

    def test_preserve_source_policy(self):
        from core.device_formation.formation_rebalance_engine import REBALANCE_MUST_PRESERVE_SOURCE_POLICY
        assert isinstance(REBALANCE_MUST_PRESERVE_SOURCE_POLICY, str)

    def test_maintain_primary_policy(self):
        from core.device_formation.formation_rebalance_engine import REBALANCE_MUST_MAINTAIN_PRIMARY_POLICY
        assert isinstance(REBALANCE_MUST_MAINTAIN_PRIMARY_POLICY, str)

    def test_health_threshold_policy(self):
        from core.device_formation.formation_rebalance_engine import HEALTH_THRESHOLD_GOVERNS_REMOVAL_POLICY
        assert isinstance(HEALTH_THRESHOLD_GOVERNS_REMOVAL_POLICY, str)


# ---------------------------------------------------------------------------
# 2–3: FormationHealthSignal
# ---------------------------------------------------------------------------

class TestFormationHealthSignal:
    def test_construction(self):
        from core.device_formation.formation_rebalance_engine import FormationHealthSignal
        sig = FormationHealthSignal(device_id="dev-1", health_score=0.9, is_reachable=True)
        assert sig.device_id == "dev-1"
        assert sig.health_score == 0.9

    def test_is_healthy_above_threshold(self):
        from core.device_formation.formation_rebalance_engine import FormationHealthSignal
        sig = FormationHealthSignal(device_id="d", health_score=0.8, is_reachable=True)
        assert sig.is_healthy() is True

    def test_is_healthy_below_threshold(self):
        from core.device_formation.formation_rebalance_engine import FormationHealthSignal
        sig = FormationHealthSignal(device_id="d", health_score=0.1, is_reachable=True)
        assert sig.is_healthy() is False

    def test_is_healthy_unreachable(self):
        from core.device_formation.formation_rebalance_engine import FormationHealthSignal
        sig = FormationHealthSignal(device_id="d", health_score=0.9, is_reachable=False)
        assert sig.is_healthy() is False

    def test_is_degraded(self):
        from core.device_formation.formation_rebalance_engine import FormationHealthSignal
        sig = FormationHealthSignal(device_id="d", health_score=0.5, is_reachable=True)
        assert sig.is_degraded() is True

    def test_to_dict(self):
        from core.device_formation.formation_rebalance_engine import FormationHealthSignal
        sig = FormationHealthSignal(device_id="d", health_score=0.7)
        d = sig.to_dict()
        assert d["device_id"] == "d"
        assert d["health_score"] == 0.7


# ---------------------------------------------------------------------------
# 4: MemberRebalanceAction enum
# ---------------------------------------------------------------------------

class TestMemberRebalanceAction:
    def test_all_expected_values(self):
        from core.device_formation.formation_rebalance_engine import MemberRebalanceAction
        expected = {"keep", "promote_to_primary", "demote_to_fallback", "remove", "warn"}
        actual = {a.value for a in MemberRebalanceAction}
        assert expected == actual


# ---------------------------------------------------------------------------
# 5: RebalanceDecision
# ---------------------------------------------------------------------------

class TestRebalanceDecision:
    def test_construction(self):
        from core.device_formation.formation_rebalance_engine import RebalanceDecision
        d = RebalanceDecision(original_formation_id="f1", rebalance_needed=False)
        assert d.original_formation_id == "f1"
        assert d.rebalance_needed is False

    def test_to_dict(self):
        from core.device_formation.formation_rebalance_engine import (
            RebalanceDecision, MemberRebalanceAction
        )
        d = RebalanceDecision(
            original_formation_id="f2",
            rebalance_needed=True,
            actions={"dev": MemberRebalanceAction.KEEP},
        )
        out = d.to_dict()
        assert out["rebalance_needed"] is True
        assert out["actions"]["dev"] == "keep"


# ---------------------------------------------------------------------------
# 6–15: FormationRebalanceEngine
# ---------------------------------------------------------------------------

class TestFormationRebalanceEngine:
    def test_no_rebalance_when_all_healthy(self):
        from core.device_formation.formation_rebalance_engine import FormationRebalanceEngine
        group = _make_group(fallback_ids=["fallback-1"])
        engine = FormationRebalanceEngine()
        decision = engine.evaluate(group, _health_map(
            ("source-dev", 1.0),
            ("primary-dev", 0.9),
            ("fallback-1", 0.8),
        ))
        assert decision.rebalance_needed is False

    def test_primary_unhealthy_triggers_promotion(self):
        from core.device_formation.formation_rebalance_engine import (
            FormationRebalanceEngine, MemberRebalanceAction
        )
        group = _make_group(fallback_ids=["fallback-1"])
        engine = FormationRebalanceEngine()
        decision = engine.evaluate(group, _health_map(
            ("primary-dev", 0.0),
            ("fallback-1", 0.9),
        ))
        assert decision.rebalance_needed is True
        assert "fallback-1" in decision.promoted_device_ids

    def test_unhealthy_support_removed(self):
        from core.device_formation.formation_rebalance_engine import (
            FormationRebalanceEngine, MemberRebalanceAction
        )
        group = _make_group(support_ids=["support-1"])
        engine = FormationRebalanceEngine()
        decision = engine.evaluate(group, _health_map(
            ("support-1", 0.0),
        ))
        assert decision.rebalance_needed is True
        assert "support-1" in decision.removed_device_ids

    def test_degraded_device_gets_warn(self):
        from core.device_formation.formation_rebalance_engine import (
            FormationRebalanceEngine, MemberRebalanceAction
        )
        group = _make_group(fallback_ids=["fallback-1"])
        engine = FormationRebalanceEngine()
        decision = engine.evaluate(group, _health_map(
            ("fallback-1", 0.5),
        ))
        assert decision.actions.get("fallback-1") == MemberRebalanceAction.WARN

    def test_source_never_removed(self):
        from core.device_formation.formation_rebalance_engine import (
            FormationRebalanceEngine, MemberRebalanceAction
        )
        group = _make_group()
        engine = FormationRebalanceEngine()
        decision = engine.evaluate(group, _health_map(
            ("source-dev", 0.0),
        ))
        assert "source-dev" not in decision.removed_device_ids
        assert decision.actions.get("source-dev") == MemberRebalanceAction.KEEP

    def test_empty_formation_returns_noop(self):
        from core.device_formation.formation_rebalance_engine import (
            FormationRebalanceEngine, EMPTY_FORMATION_GROUP
        )
        from core.device_formation.formation_group import EMPTY_FORMATION_GROUP
        engine = FormationRebalanceEngine()
        decision = engine.evaluate(EMPTY_FORMATION_GROUP, {})
        assert decision.rebalance_needed is False

    def test_reshape_with_promote(self):
        from core.device_formation.formation_rebalance_engine import (
            FormationRebalanceEngine, MemberRebalanceAction
        )
        from core.device_formation.formation_role import FormationRole
        group = _make_group(fallback_ids=["fb-1"])
        engine = FormationRebalanceEngine()
        decision = engine.evaluate(group, _health_map(("primary-dev", 0.0), ("fb-1", 0.9)))
        new_group, policy = engine.reshape(group, decision)
        primary_ids = [
            getattr(m, "device_id", None)
            for m in getattr(new_group, "members", [])
            if getattr(m, "role", None) == FormationRole.PRIMARY_EXECUTION
        ]
        assert "fb-1" in primary_ids

    def test_reshape_with_remove(self):
        from core.device_formation.formation_rebalance_engine import FormationRebalanceEngine
        from core.device_formation.formation_role import FormationRole
        group = _make_group(support_ids=["sup-1"])
        engine = FormationRebalanceEngine()
        decision = engine.evaluate(group, _health_map(("sup-1", 0.0)))
        new_group, _ = engine.reshape(group, decision)
        member_ids = [getattr(m, "device_id", None) for m in getattr(new_group, "members", [])]
        assert "sup-1" not in member_ids

    def test_reshape_always_has_primary(self):
        from core.device_formation.formation_rebalance_engine import FormationRebalanceEngine
        from core.device_formation.formation_role import FormationRole
        # All members unhealthy except source
        group = _make_group(fallback_ids=["fb-only"])
        engine = FormationRebalanceEngine()
        decision = engine.evaluate(group, _health_map(
            ("primary-dev", 0.0),
            ("fb-only", 0.9),
        ))
        new_group, _ = engine.reshape(group, decision)
        roles = [getattr(m, "role", None) for m in getattr(new_group, "members", [])]
        assert FormationRole.PRIMARY_EXECUTION in roles

    def test_reshape_no_rebalance_returns_original(self):
        from core.device_formation.formation_rebalance_engine import FormationRebalanceEngine, RebalanceDecision
        group = _make_group()
        engine = FormationRebalanceEngine()
        no_op = RebalanceDecision(original_formation_id="f", rebalance_needed=False)
        new_group, _ = engine.reshape(group, no_op)
        assert new_group is group


# ---------------------------------------------------------------------------
# 16–19: Convenience functions
# ---------------------------------------------------------------------------

class TestConvenienceFunctions:
    def test_evaluate_formation_health(self):
        from core.device_formation.formation_rebalance_engine import evaluate_formation_health
        group = _make_group()
        result = evaluate_formation_health(group)
        assert result is not None
        assert hasattr(result, "rebalance_needed")

    def test_apply_rebalance(self):
        from core.device_formation.formation_rebalance_engine import apply_rebalance
        group = _make_group(fallback_ids=["fb-1"])
        new_group, decision = apply_rebalance(group, _health_map(("primary-dev", 0.0)))
        assert new_group is not None
        assert decision is not None

    def test_maybe_promote_fallback(self):
        from core.device_formation.formation_rebalance_engine import maybe_promote_fallback
        from core.device_formation.formation_role import FormationRole
        group = _make_group(fallback_ids=["fb-promo"])
        new_group = maybe_promote_fallback(group, "primary-dev", "fb-promo")
        roles = {
            getattr(m, "device_id", None): getattr(m, "role", None)
            for m in getattr(new_group, "members", [])
        }
        assert roles.get("fb-promo") == FormationRole.PRIMARY_EXECUTION

    def test_maybe_remove_unhealthy(self):
        from core.device_formation.formation_rebalance_engine import maybe_remove_unhealthy
        group = _make_group(support_ids=["sick-sup"])
        new_group = maybe_remove_unhealthy(group, ["sick-sup"])
        member_ids = [getattr(m, "device_id", None) for m in getattr(new_group, "members", [])]
        assert "sick-sup" not in member_ids

    def test_apply_rebalance_graceful_empty(self):
        from core.device_formation.formation_rebalance_engine import apply_rebalance
        from core.device_formation.formation_group import EMPTY_FORMATION_GROUP
        new_group, decision = apply_rebalance(EMPTY_FORMATION_GROUP, {})
        assert new_group is not None


# ---------------------------------------------------------------------------
# 21: core.device_formation __init__ exports
# ---------------------------------------------------------------------------

class TestDeviceFormationInit:
    def test_rebalance_symbols_exported(self):
        from core.device_formation import (
            FormationHealthSignal,
            MemberRebalanceAction,
            RebalanceDecision,
            FormationRebalanceEngine,
            evaluate_formation_health,
            apply_rebalance,
            maybe_promote_fallback,
            maybe_remove_unhealthy,
            FORMATION_REBALANCE_ENGINE_IS_AUTHORITY,
            FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL,
        )
        assert FormationRebalanceEngine is not None
        assert isinstance(FORMATION_REBALANCE_ENGINE_IS_AUTHORITY, str)


# ---------------------------------------------------------------------------
# 22: Gap closure sentinel references formation_resolver
# ---------------------------------------------------------------------------

class TestGapClosureSentinel:
    def test_sentinel_mentions_formation_resolver(self):
        from core.device_formation.formation_rebalance_engine import FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL
        assert "formation_resolver" in FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL


# ---------------------------------------------------------------------------
# 23–25: Additional edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_rebalance_not_needed_when_all_healthy(self):
        from core.device_formation.formation_rebalance_engine import FormationRebalanceEngine
        group = _make_group(fallback_ids=["fb"])
        decision = FormationRebalanceEngine().evaluate(
            group, _health_map(("source-dev", 1.0), ("primary-dev", 1.0), ("fb", 0.8))
        )
        assert decision.rebalance_needed is False
        assert decision.reason is not None

    def test_custom_thresholds(self):
        from core.device_formation.formation_rebalance_engine import FormationRebalanceEngine
        # Use a high threshold so 0.7 is considered unhealthy
        engine = FormationRebalanceEngine(unhealthy_threshold=0.8, degraded_threshold=0.95)
        group = _make_group(support_ids=["low-health"])
        decision = engine.evaluate(group, _health_map(("low-health", 0.7)))
        assert decision.actions.get("low-health") is not None
        # 0.7 is below unhealthy_threshold of 0.8 → remove
        from core.device_formation.formation_rebalance_engine import MemberRebalanceAction
        assert decision.actions["low-health"] == MemberRebalanceAction.REMOVE
