#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr8_compat_legacy_path_blocking_canonicalization.py
==============================================================

PR-8 — Compat / Legacy Path Blocking Canonicalization — test suite.

Coverage areas
--------------
A.  Module importable; authority sentinel and PR-8 sentinel are non-empty strings.
B.  All policy sentinels are non-empty strings with expected keywords.
C.  CompatLegacyBlockingDecision enum has the five expected decision values.
D.  CompatLegacyPathKind enum has the expected path kind values.
E.  CompatLegacyBlockingOutcome enum has allowed / blocked / quarantined values.
F.  CompatLegacyBlockingRecord dataclass constructs correctly and to_dict() has
    required keys.
G.  CompatLegacyBlockingRecord.is_blocked / is_quarantined / is_allowed properties.
H.  CompatLegacyBlockingSnapshot constructs correctly and to_dict() has required keys.
I.  CompatLegacyPathBlockingEnforcer.evaluate() returns canonical_path_confirmed
    when compat_influence_active=False.
J.  evaluate() returns allow_for_observation_only for a whitelisted path.
K.  evaluate() returns block_due_to_legacy_dispatch for path_kind=legacy_dispatch.
L.  evaluate() returns block_due_to_compat_truth_influence for path_kind=compat_truth.
M.  evaluate() returns block_due_to_legacy_dispatch for path_kind=handoff_bypass.
N.  evaluate() returns block_due_to_legacy_dispatch for path_kind=route_bypass.
O.  evaluate() returns block_due_to_legacy_dispatch for path_kind=recovery_injection.
P.  evaluate() returns quarantine_due_to_ambiguous_contract for
    path_kind=observation_candidate with an unlisted compat_path.
Q.  evaluate() with raise_on_block=True raises CompatLegacyBlockingError on block.
R.  evaluate() with raise_on_block=True raises CompatLegacyBlockingError on quarantine.
S.  evaluate() with raise_on_block=True does NOT raise when decision is allowed.
T.  CompatLegacyBlockingError carries the blocking_record attribute.
U.  enforce_canonical_gate() convenience function delegates to the singleton enforcer.
V.  get_blocking_enforcer() returns singleton; reset_blocking_enforcer() resets it.
W.  Decision history is accumulated across evaluate() calls.
X.  snapshot() counts are consistent with decision history.
Y.  snapshot() blocking_canonicalization_healthy is False when quarantine_count > 0.
Z.  build_blocking_canonicalization_snapshot() returns CompatLegacyBlockingSnapshot.
AA. CompatFallbackAuthorityGuard PR-8 sentinel and blocking policy importable.
AB. block_compat_influence_at_decision_site() returns a blocking record.
AC. block_compat_influence_at_decision_site() with path_kind='compat_truth' blocks.
AD. LegacyDispatchRegistry PR-8 sentinel and blocking policy importable.
AE. check_dispatch_blocked() returns block_due_to_legacy_dispatch for a registered module.
AF. check_dispatch_blocked() returns quarantine for an unregistered module.
AG. check_dispatch_blocked() with raise_on_block=True raises on block.
AH. All new public names appear in __all__.
AI. INFL-011, INFL-012, INFL-013 are present in the influence registry.
AJ. INFL-011, INFL-012, INFL-013 all have bounding_status EXPLICITLY_BOUNDED.
AK. INFL-011, INFL-012, INFL-013 all reference PR-8 in pr_addressed.
"""

from __future__ import annotations

import pytest

import core.compat_legacy_path_blocking_canonicalization as _blocking_mod


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def fresh_enforcer():
    """Reset the blocking enforcer singleton before and after each test."""
    _blocking_mod.reset_blocking_enforcer()
    yield
    _blocking_mod.reset_blocking_enforcer()


# ===========================================================================
# A. Module importable; sentinels present
# ===========================================================================


class TestModuleSentinels:
    def test_module_importable(self):
        import core.compat_legacy_path_blocking_canonicalization  # noqa: F401

    def test_authority_sentinel_non_empty(self):
        assert isinstance(
            _blocking_mod.COMPAT_LEGACY_BLOCKING_CANONICALIZATION_AUTHORITY, str
        )
        assert len(_blocking_mod.COMPAT_LEGACY_BLOCKING_CANONICALIZATION_AUTHORITY) > 0
        assert "PR-8" in _blocking_mod.COMPAT_LEGACY_BLOCKING_CANONICALIZATION_AUTHORITY

    def test_pr8_sentinel_non_empty(self):
        s = _blocking_mod.COMPAT_LEGACY_BLOCKING_CANONICALIZATION_PR8_SENTINEL
        assert isinstance(s, str)
        assert "PR8" in s
        assert "blocking-canonicalization" in s


# ===========================================================================
# B. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    def _sentinels(self):
        return [
            _blocking_mod.BLOCKING_FIRST_ENFORCEMENT_ACTIVE_POLICY,
            _blocking_mod.CANONICAL_PATH_IS_SOLE_ROUTING_TRUTH_HANDOFF_AUTHORITY_POLICY,
            _blocking_mod.COMPAT_SILENT_PASS_THROUGH_IS_PROHIBITED_POLICY,
            _blocking_mod.LEGACY_DISPATCH_BLOCKING_FIRST_POLICY,
            _blocking_mod.COMPAT_TRUTH_INFLUENCE_BLOCKING_FIRST_POLICY,
            _blocking_mod.QUARANTINE_AMBIGUOUS_CONTRACT_POLICY,
            _blocking_mod.OBSERVATION_ONLY_REQUIRES_EXPLICIT_WHITELIST_POLICY,
        ]

    def test_all_sentinels_non_empty_strings(self):
        for s in self._sentinels():
            assert isinstance(s, str) and len(s) > 0

    def test_blocking_first_policy_contains_keyword(self):
        assert "blocking" in _blocking_mod.BLOCKING_FIRST_ENFORCEMENT_ACTIVE_POLICY.lower()

    def test_quarantine_policy_contains_keyword(self):
        assert "quarantine" in _blocking_mod.QUARANTINE_AMBIGUOUS_CONTRACT_POLICY.lower()

    def test_observation_whitelist_policy_contains_keyword(self):
        assert "whitelist" in _blocking_mod.OBSERVATION_ONLY_REQUIRES_EXPLICIT_WHITELIST_POLICY.lower()


# ===========================================================================
# C. CompatLegacyBlockingDecision enum
# ===========================================================================


class TestCompatLegacyBlockingDecision:
    def test_has_canonical_path_confirmed(self):
        d = _blocking_mod.CompatLegacyBlockingDecision
        assert d.canonical_path_confirmed.value == "canonical_path_confirmed"

    def test_has_allow_for_observation_only(self):
        assert _blocking_mod.CompatLegacyBlockingDecision.allow_for_observation_only.value == "allow_for_observation_only"

    def test_has_block_due_to_legacy_dispatch(self):
        assert _blocking_mod.CompatLegacyBlockingDecision.block_due_to_legacy_dispatch.value == "block_due_to_legacy_dispatch"

    def test_has_block_due_to_compat_truth_influence(self):
        assert _blocking_mod.CompatLegacyBlockingDecision.block_due_to_compat_truth_influence.value == "block_due_to_compat_truth_influence"

    def test_has_quarantine_due_to_ambiguous_contract(self):
        assert _blocking_mod.CompatLegacyBlockingDecision.quarantine_due_to_ambiguous_contract.value == "quarantine_due_to_ambiguous_contract"

    def test_five_members(self):
        assert len(_blocking_mod.CompatLegacyBlockingDecision) == 5


# ===========================================================================
# D. CompatLegacyPathKind enum
# ===========================================================================


class TestCompatLegacyPathKind:
    def test_has_legacy_dispatch(self):
        assert _blocking_mod.CompatLegacyPathKind.legacy_dispatch.value == "legacy_dispatch"

    def test_has_compat_truth(self):
        assert _blocking_mod.CompatLegacyPathKind.compat_truth.value == "compat_truth"

    def test_has_handoff_bypass(self):
        assert _blocking_mod.CompatLegacyPathKind.handoff_bypass.value == "handoff_bypass"

    def test_has_route_bypass(self):
        assert _blocking_mod.CompatLegacyPathKind.route_bypass.value == "route_bypass"

    def test_has_recovery_injection(self):
        assert _blocking_mod.CompatLegacyPathKind.recovery_injection.value == "recovery_injection"

    def test_has_observation_candidate(self):
        assert _blocking_mod.CompatLegacyPathKind.observation_candidate.value == "observation_candidate"


# ===========================================================================
# E. CompatLegacyBlockingOutcome enum
# ===========================================================================


class TestCompatLegacyBlockingOutcome:
    def test_has_allowed(self):
        assert _blocking_mod.CompatLegacyBlockingOutcome.allowed.value == "allowed"

    def test_has_blocked(self):
        assert _blocking_mod.CompatLegacyBlockingOutcome.blocked.value == "blocked"

    def test_has_quarantined(self):
        assert _blocking_mod.CompatLegacyBlockingOutcome.quarantined.value == "quarantined"

    def test_three_members(self):
        assert len(_blocking_mod.CompatLegacyBlockingOutcome) == 3


# ===========================================================================
# F. CompatLegacyBlockingRecord construction and to_dict
# ===========================================================================


class TestCompatLegacyBlockingRecord:
    def test_construction_defaults(self):
        r = _blocking_mod.CompatLegacyBlockingRecord()
        assert r.record_id
        assert r.decision == _blocking_mod.CompatLegacyBlockingDecision.canonical_path_confirmed

    def test_to_dict_has_required_keys(self):
        r = _blocking_mod.CompatLegacyBlockingRecord(
            decision=_blocking_mod.CompatLegacyBlockingDecision.block_due_to_legacy_dispatch,
            outcome=_blocking_mod.CompatLegacyBlockingOutcome.blocked,
            path_kind=_blocking_mod.CompatLegacyPathKind.legacy_dispatch,
            calling_site="test.site",
            compat_path="legacy.module",
            canonical_path="canonical.module",
            rationale="test rationale",
        )
        d = r.to_dict()
        required_keys = {
            "record_id", "decision", "outcome", "path_kind",
            "calling_site", "compat_path", "canonical_path",
            "rationale", "influence_id", "operator_note", "timestamp",
        }
        assert required_keys.issubset(d.keys())

    def test_to_dict_decision_is_string(self):
        r = _blocking_mod.CompatLegacyBlockingRecord(
            decision=_blocking_mod.CompatLegacyBlockingDecision.block_due_to_legacy_dispatch,
            outcome=_blocking_mod.CompatLegacyBlockingOutcome.blocked,
        )
        assert isinstance(r.to_dict()["decision"], str)
        assert r.to_dict()["decision"] == "block_due_to_legacy_dispatch"


# ===========================================================================
# G. is_blocked / is_quarantined / is_allowed properties
# ===========================================================================


class TestBlockingRecordProperties:
    def test_is_blocked_true(self):
        r = _blocking_mod.CompatLegacyBlockingRecord(
            outcome=_blocking_mod.CompatLegacyBlockingOutcome.blocked
        )
        assert r.is_blocked is True
        assert r.is_quarantined is False
        assert r.is_allowed is False

    def test_is_quarantined_true(self):
        r = _blocking_mod.CompatLegacyBlockingRecord(
            outcome=_blocking_mod.CompatLegacyBlockingOutcome.quarantined
        )
        assert r.is_quarantined is True
        assert r.is_blocked is False
        assert r.is_allowed is False

    def test_is_allowed_true(self):
        r = _blocking_mod.CompatLegacyBlockingRecord(
            outcome=_blocking_mod.CompatLegacyBlockingOutcome.allowed
        )
        assert r.is_allowed is True
        assert r.is_blocked is False
        assert r.is_quarantined is False


# ===========================================================================
# H. CompatLegacyBlockingSnapshot construction and to_dict
# ===========================================================================


class TestCompatLegacyBlockingSnapshot:
    def test_construction_defaults(self):
        s = _blocking_mod.CompatLegacyBlockingSnapshot()
        assert s.total_evaluations == 0
        assert s.blocking_canonicalization_healthy is True

    def test_to_dict_has_required_keys(self):
        s = _blocking_mod.CompatLegacyBlockingSnapshot(
            total_evaluations=5,
            blocked_legacy_dispatch_count=2,
        )
        d = s.to_dict()
        assert "total_evaluations" in d
        assert "by_decision" in d
        assert "invisible_flow_count" in d
        assert "blocking_canonicalization_healthy" in d
        assert "policy_sentinels" in d
        assert "recent_records" in d
        assert "generated_at" in d

    def test_by_decision_keys(self):
        s = _blocking_mod.CompatLegacyBlockingSnapshot()
        d = s.to_dict()["by_decision"]
        assert "canonical_path_confirmed" in d
        assert "allow_for_observation_only" in d
        assert "block_due_to_legacy_dispatch" in d
        assert "block_due_to_compat_truth_influence" in d
        assert "quarantine_due_to_ambiguous_contract" in d


# ===========================================================================
# I–P. CompatLegacyPathBlockingEnforcer.evaluate() decisions
# ===========================================================================


class TestEnforcerEvaluate:
    def _enforcer(self):
        return _blocking_mod.CompatLegacyPathBlockingEnforcer()

    def test_I_canonical_path_confirmed_when_no_compat_influence(self):
        e = self._enforcer()
        r = e.evaluate(
            calling_site="test.site",
            compat_path="legacy.module",
            canonical_path="canonical.module",
            path_kind=_blocking_mod.CompatLegacyPathKind.legacy_dispatch,
            compat_influence_active=False,
        )
        assert r.decision == _blocking_mod.CompatLegacyBlockingDecision.canonical_path_confirmed
        assert r.is_allowed

    def test_J_allow_observation_for_whitelisted_path(self):
        e = self._enforcer()
        r = e.evaluate(
            calling_site="test.audit",
            compat_path="core.runtime_closure_audit",
            canonical_path="canonical.module",
            path_kind=_blocking_mod.CompatLegacyPathKind.observation_candidate,
            compat_influence_active=True,
        )
        assert r.decision == _blocking_mod.CompatLegacyBlockingDecision.allow_for_observation_only
        assert r.is_allowed

    def test_K_block_legacy_dispatch(self):
        e = self._enforcer()
        r = e.evaluate(
            calling_site="test.dispatch",
            compat_path="galaxy_gateway.task_router",
            canonical_path="core.command_router.CommandRouter.route_envelope",
            path_kind=_blocking_mod.CompatLegacyPathKind.legacy_dispatch,
            compat_influence_active=True,
        )
        assert r.decision == _blocking_mod.CompatLegacyBlockingDecision.block_due_to_legacy_dispatch
        assert r.is_blocked

    def test_L_block_compat_truth(self):
        e = self._enforcer()
        r = e.evaluate(
            calling_site="test.truth",
            compat_path="legacy.task_queue",
            canonical_path="core.canonical_task.CanonicalTask",
            path_kind=_blocking_mod.CompatLegacyPathKind.compat_truth,
            compat_influence_active=True,
        )
        assert r.decision == _blocking_mod.CompatLegacyBlockingDecision.block_due_to_compat_truth_influence
        assert r.is_blocked

    def test_M_block_handoff_bypass(self):
        e = self._enforcer()
        r = e.evaluate(
            calling_site="test.handoff",
            compat_path="galaxy_gateway.cross_device_coordinator",
            canonical_path="galaxy_gateway.agent_bridge.AgentBridge.handoff",
            path_kind=_blocking_mod.CompatLegacyPathKind.handoff_bypass,
            compat_influence_active=True,
        )
        assert r.decision == _blocking_mod.CompatLegacyBlockingDecision.block_due_to_legacy_dispatch
        assert r.is_blocked

    def test_N_block_route_bypass(self):
        e = self._enforcer()
        r = e.evaluate(
            calling_site="test.route",
            compat_path="fusion.unified_orchestrator",
            canonical_path="core.command_router.CommandRouter.route_envelope",
            path_kind=_blocking_mod.CompatLegacyPathKind.route_bypass,
            compat_influence_active=True,
        )
        assert r.decision == _blocking_mod.CompatLegacyBlockingDecision.block_due_to_legacy_dispatch
        assert r.is_blocked

    def test_O_block_recovery_injection(self):
        e = self._enforcer()
        r = e.evaluate(
            calling_site="test.recovery",
            compat_path="legacy.recovery_path",
            canonical_path="core.hybrid_orchestration_continuity",
            path_kind=_blocking_mod.CompatLegacyPathKind.recovery_injection,
            compat_influence_active=True,
        )
        assert r.decision == _blocking_mod.CompatLegacyBlockingDecision.block_due_to_legacy_dispatch
        assert r.is_blocked

    def test_P_quarantine_observation_candidate_unlisted(self):
        e = self._enforcer()
        r = e.evaluate(
            calling_site="test.obs",
            compat_path="some.unlisted.compat.module",
            canonical_path="canonical.module",
            path_kind=_blocking_mod.CompatLegacyPathKind.observation_candidate,
            compat_influence_active=True,
        )
        assert r.decision == _blocking_mod.CompatLegacyBlockingDecision.quarantine_due_to_ambiguous_contract
        assert r.is_quarantined


# ===========================================================================
# Q–T. raise_on_block and CompatLegacyBlockingError
# ===========================================================================


class TestRaiseOnBlock:
    def test_Q_raises_on_block(self):
        e = _blocking_mod.CompatLegacyPathBlockingEnforcer()
        with pytest.raises(_blocking_mod.CompatLegacyBlockingError):
            e.evaluate(
                calling_site="test",
                compat_path="legacy.dispatch",
                canonical_path="canonical",
                path_kind=_blocking_mod.CompatLegacyPathKind.legacy_dispatch,
                compat_influence_active=True,
                raise_on_block=True,
            )

    def test_R_raises_on_quarantine(self):
        e = _blocking_mod.CompatLegacyPathBlockingEnforcer()
        with pytest.raises(_blocking_mod.CompatLegacyBlockingError):
            e.evaluate(
                calling_site="test",
                compat_path="unlisted.module",
                canonical_path="canonical",
                path_kind=_blocking_mod.CompatLegacyPathKind.observation_candidate,
                compat_influence_active=True,
                raise_on_block=True,
            )

    def test_S_no_raise_when_allowed(self):
        e = _blocking_mod.CompatLegacyPathBlockingEnforcer()
        # Should not raise
        r = e.evaluate(
            calling_site="test",
            compat_path="core.runtime_closure_audit",
            canonical_path="canonical",
            path_kind=_blocking_mod.CompatLegacyPathKind.observation_candidate,
            compat_influence_active=True,
            raise_on_block=True,
        )
        assert r.is_allowed

    def test_T_blocking_error_carries_record(self):
        e = _blocking_mod.CompatLegacyPathBlockingEnforcer()
        with pytest.raises(_blocking_mod.CompatLegacyBlockingError) as exc_info:
            e.evaluate(
                calling_site="test",
                compat_path="legacy.dispatch",
                canonical_path="canonical",
                path_kind=_blocking_mod.CompatLegacyPathKind.legacy_dispatch,
                compat_influence_active=True,
                raise_on_block=True,
            )
        assert hasattr(exc_info.value, "blocking_record")
        assert exc_info.value.blocking_record.is_blocked


# ===========================================================================
# U. enforce_canonical_gate() convenience function
# ===========================================================================


class TestEnforceCanonicalGate:
    def test_U_delegates_to_singleton(self):
        r = _blocking_mod.enforce_canonical_gate(
            calling_site="test.gate",
            compat_path="legacy.dispatch",
            canonical_path="canonical",
            path_kind=_blocking_mod.CompatLegacyPathKind.legacy_dispatch,
            compat_influence_active=True,
        )
        assert r.decision == _blocking_mod.CompatLegacyBlockingDecision.block_due_to_legacy_dispatch
        # History should contain this record
        history = _blocking_mod.get_blocking_enforcer().decision_history()
        assert len(history) >= 1


# ===========================================================================
# V. Singleton management
# ===========================================================================


class TestSingletonManagement:
    def test_V_get_enforcer_returns_singleton(self):
        e1 = _blocking_mod.get_blocking_enforcer()
        e2 = _blocking_mod.get_blocking_enforcer()
        assert e1 is e2

    def test_V_reset_changes_singleton(self):
        e1 = _blocking_mod.get_blocking_enforcer()
        _blocking_mod.reset_blocking_enforcer()
        e2 = _blocking_mod.get_blocking_enforcer()
        assert e1 is not e2


# ===========================================================================
# W. Decision history accumulation
# ===========================================================================


class TestDecisionHistory:
    def test_W_history_accumulates(self):
        e = _blocking_mod.CompatLegacyPathBlockingEnforcer()
        for i in range(5):
            e.evaluate(
                calling_site=f"site{i}",
                compat_path="legacy.module",
                canonical_path="canonical",
                path_kind=_blocking_mod.CompatLegacyPathKind.legacy_dispatch,
                compat_influence_active=True,
            )
        assert len(e.decision_history()) == 5

    def test_W_history_is_copy(self):
        e = _blocking_mod.CompatLegacyPathBlockingEnforcer()
        e.evaluate(
            calling_site="site",
            compat_path="legacy",
            canonical_path="canonical",
            path_kind=_blocking_mod.CompatLegacyPathKind.legacy_dispatch,
            compat_influence_active=True,
        )
        h1 = e.decision_history()
        h2 = e.decision_history()
        assert h1 is not h2


# ===========================================================================
# X–Z. Snapshot consistency and health
# ===========================================================================


class TestSnapshot:
    def test_X_snapshot_counts_consistent(self):
        e = _blocking_mod.CompatLegacyPathBlockingEnforcer()
        # 1 canonical, 1 observation allow, 1 block_dispatch, 1 block_truth, 1 quarantine
        e.evaluate(
            calling_site="s1", compat_path="l", canonical_path="c",
            path_kind=_blocking_mod.CompatLegacyPathKind.legacy_dispatch,
            compat_influence_active=False,
        )
        e.evaluate(
            calling_site="s2", compat_path="core.runtime_closure_audit", canonical_path="c",
            path_kind=_blocking_mod.CompatLegacyPathKind.observation_candidate,
            compat_influence_active=True,
        )
        e.evaluate(
            calling_site="s3", compat_path="l", canonical_path="c",
            path_kind=_blocking_mod.CompatLegacyPathKind.legacy_dispatch,
            compat_influence_active=True,
        )
        e.evaluate(
            calling_site="s4", compat_path="l", canonical_path="c",
            path_kind=_blocking_mod.CompatLegacyPathKind.compat_truth,
            compat_influence_active=True,
        )
        e.evaluate(
            calling_site="s5", compat_path="unlisted.module", canonical_path="c",
            path_kind=_blocking_mod.CompatLegacyPathKind.observation_candidate,
            compat_influence_active=True,
        )
        snap = e.snapshot()
        total = (
            snap.canonical_confirmed_count
            + snap.observation_allowed_count
            + snap.blocked_legacy_dispatch_count
            + snap.blocked_compat_truth_count
            + snap.quarantined_count
        )
        assert snap.total_evaluations == 5
        assert total == 5
        assert snap.invisible_flow_count == 0

    def test_Y_unhealthy_when_quarantine(self):
        e = _blocking_mod.CompatLegacyPathBlockingEnforcer()
        e.evaluate(
            calling_site="s1", compat_path="unlisted.module", canonical_path="c",
            path_kind=_blocking_mod.CompatLegacyPathKind.observation_candidate,
            compat_influence_active=True,
        )
        snap = e.snapshot()
        assert snap.quarantined_count == 1
        assert snap.blocking_canonicalization_healthy is False

    def test_Z_build_snapshot_returns_snapshot(self):
        snap = _blocking_mod.build_blocking_canonicalization_snapshot()
        assert isinstance(snap, _blocking_mod.CompatLegacyBlockingSnapshot)


# ===========================================================================
# AA–AC. CompatFallbackAuthorityGuard PR-8 integration
# ===========================================================================


class TestCompatFallbackAuthorityGuardPR8:
    def test_AA_pr8_sentinel_importable(self):
        from core.compat_fallback_authority_guard import (
            COMPAT_FALLBACK_AUTHORITY_GUARD_PR8_SENTINEL,
        )
        assert isinstance(COMPAT_FALLBACK_AUTHORITY_GUARD_PR8_SENTINEL, str)
        assert "PR8" in COMPAT_FALLBACK_AUTHORITY_GUARD_PR8_SENTINEL

    def test_AA_blocking_first_policy_importable(self):
        from core.compat_fallback_authority_guard import (
            BLOCKING_FIRST_ENFORCEMENT_ACTIVE_POLICY,
        )
        assert isinstance(BLOCKING_FIRST_ENFORCEMENT_ACTIVE_POLICY, str)
        assert "blocking" in BLOCKING_FIRST_ENFORCEMENT_ACTIVE_POLICY.lower()

    def test_AB_block_compat_influence_returns_record(self):
        from core.compat_fallback_authority_guard import (
            block_compat_influence_at_decision_site,
        )
        record = block_compat_influence_at_decision_site(
            "INFL-011",
            calling_site="test.truth_ingress",
            compat_path="legacy.task_queue",
            canonical_path="core.canonical_task.CanonicalTask",
            path_kind="legacy_dispatch",
            compat_influence_active=True,
        )
        # Should produce a blocking record
        assert record is not None
        assert hasattr(record, "decision")
        assert hasattr(record, "is_blocked")

    def test_AC_block_compat_truth_influence(self):
        from core.compat_fallback_authority_guard import (
            block_compat_influence_at_decision_site,
        )
        record = block_compat_influence_at_decision_site(
            "INFL-011",
            calling_site="test.truth",
            compat_path="android.compat.truth.injection",
            canonical_path="core.canonical_task.CanonicalTask",
            path_kind="compat_truth",
            compat_influence_active=True,
        )
        assert record.is_blocked
        assert record.decision == _blocking_mod.CompatLegacyBlockingDecision.block_due_to_compat_truth_influence

    def test_AC_no_block_when_compat_inactive(self):
        from core.compat_fallback_authority_guard import (
            block_compat_influence_at_decision_site,
        )
        record = block_compat_influence_at_decision_site(
            "INFL-001",
            calling_site="test.clean",
            compat_path="legacy.module",
            canonical_path="canonical.module",
            path_kind="legacy_dispatch",
            compat_influence_active=False,
        )
        assert record.is_allowed
        assert record.decision == _blocking_mod.CompatLegacyBlockingDecision.canonical_path_confirmed


# ===========================================================================
# AD–AG. LegacyDispatchRegistry PR-8 integration
# ===========================================================================


class TestLegacyDispatchRegistryPR8:
    @pytest.fixture(autouse=True)
    def reset_registry(self):
        from core.legacy_dispatch_registry import reset_registry
        reset_registry()
        yield
        reset_registry()

    def test_AD_pr8_sentinel_importable(self):
        from core.legacy_dispatch_registry import (
            LEGACY_DISPATCH_REGISTRY_PR8_SENTINEL,
        )
        assert isinstance(LEGACY_DISPATCH_REGISTRY_PR8_SENTINEL, str)
        assert "PR8" in LEGACY_DISPATCH_REGISTRY_PR8_SENTINEL

    def test_AD_blocking_first_policy_importable(self):
        from core.legacy_dispatch_registry import (
            LEGACY_DISPATCH_BLOCKING_FIRST_ENFORCEMENT_POLICY,
        )
        assert isinstance(LEGACY_DISPATCH_BLOCKING_FIRST_ENFORCEMENT_POLICY, str)
        assert "blocking" in LEGACY_DISPATCH_BLOCKING_FIRST_ENFORCEMENT_POLICY.lower()

    def test_AE_check_dispatch_blocked_registered_module(self):
        from core.legacy_dispatch_registry import check_dispatch_blocked
        record = check_dispatch_blocked(
            "galaxy_gateway.task_router",
            calling_site="test.dispatch_gate",
        )
        assert record is not None
        # Registered legacy module → block_due_to_legacy_dispatch
        assert record.decision == _blocking_mod.CompatLegacyBlockingDecision.block_due_to_legacy_dispatch
        assert record.is_blocked

    def test_AF_check_dispatch_blocked_unregistered_module(self):
        from core.legacy_dispatch_registry import check_dispatch_blocked
        record = check_dispatch_blocked(
            "some.completely.unknown.module",
            calling_site="test.unknown_gate",
        )
        # Unregistered → quarantine
        assert record.decision == _blocking_mod.CompatLegacyBlockingDecision.quarantine_due_to_ambiguous_contract
        assert record.is_quarantined

    def test_AG_check_dispatch_blocked_raises_on_block(self):
        from core.legacy_dispatch_registry import check_dispatch_blocked
        with pytest.raises(_blocking_mod.CompatLegacyBlockingError):
            check_dispatch_blocked(
                "galaxy_gateway.task_router",
                calling_site="test.dispatch_gate",
                raise_on_block=True,
            )


# ===========================================================================
# AH. __all__ completeness
# ===========================================================================


class TestAllCompleteness:
    def test_AH_all_public_names_in_all(self):
        public = [
            "COMPAT_LEGACY_BLOCKING_CANONICALIZATION_AUTHORITY",
            "COMPAT_LEGACY_BLOCKING_CANONICALIZATION_PR8_SENTINEL",
            "BLOCKING_FIRST_ENFORCEMENT_ACTIVE_POLICY",
            "CANONICAL_PATH_IS_SOLE_ROUTING_TRUTH_HANDOFF_AUTHORITY_POLICY",
            "COMPAT_SILENT_PASS_THROUGH_IS_PROHIBITED_POLICY",
            "LEGACY_DISPATCH_BLOCKING_FIRST_POLICY",
            "COMPAT_TRUTH_INFLUENCE_BLOCKING_FIRST_POLICY",
            "QUARANTINE_AMBIGUOUS_CONTRACT_POLICY",
            "OBSERVATION_ONLY_REQUIRES_EXPLICIT_WHITELIST_POLICY",
            "CompatLegacyBlockingDecision",
            "CompatLegacyPathKind",
            "CompatLegacyBlockingOutcome",
            "CompatLegacyBlockingRecord",
            "CompatLegacyBlockingSnapshot",
            "CompatLegacyPathBlockingEnforcer",
            "get_blocking_enforcer",
            "enforce_canonical_gate",
            "build_blocking_canonicalization_snapshot",
            "reset_blocking_enforcer",
        ]
        for name in public:
            assert name in _blocking_mod.__all__, f"{name!r} not in __all__"


# ===========================================================================
# AI–AK. INFL-011, INFL-012, INFL-013 in influence registry
# ===========================================================================


class TestInfluenceRegistryPR8Records:
    def _registry(self):
        from core.compat_fallback_authority_guard import get_influence_registry
        return get_influence_registry()

    def test_AI_infl_011_present(self):
        ids = {r.influence_id for r in self._registry()}
        assert "INFL-011" in ids

    def test_AI_infl_012_present(self):
        ids = {r.influence_id for r in self._registry()}
        assert "INFL-012" in ids

    def test_AI_infl_013_present(self):
        ids = {r.influence_id for r in self._registry()}
        assert "INFL-013" in ids

    def test_AJ_infl_011_explicitly_bounded(self):
        from core.compat_fallback_authority_guard import (
            get_influence_record,
            CompatInfluenceBoundingStatus,
        )
        r = get_influence_record("INFL-011")
        assert r is not None
        assert r.bounding_status == CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED

    def test_AJ_infl_012_explicitly_bounded(self):
        from core.compat_fallback_authority_guard import (
            get_influence_record,
            CompatInfluenceBoundingStatus,
        )
        r = get_influence_record("INFL-012")
        assert r is not None
        assert r.bounding_status == CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED

    def test_AJ_infl_013_explicitly_bounded(self):
        from core.compat_fallback_authority_guard import (
            get_influence_record,
            CompatInfluenceBoundingStatus,
        )
        r = get_influence_record("INFL-013")
        assert r is not None
        assert r.bounding_status == CompatInfluenceBoundingStatus.EXPLICITLY_BOUNDED

    def test_AK_infl_011_pr8(self):
        from core.compat_fallback_authority_guard import get_influence_record
        r = get_influence_record("INFL-011")
        assert r is not None
        assert "PR-8" in r.pr_addressed

    def test_AK_infl_012_pr8(self):
        from core.compat_fallback_authority_guard import get_influence_record
        r = get_influence_record("INFL-012")
        assert r is not None
        assert "PR-8" in r.pr_addressed

    def test_AK_infl_013_pr8(self):
        from core.compat_fallback_authority_guard import get_influence_record
        r = get_influence_record("INFL-013")
        assert r is not None
        assert "PR-8" in r.pr_addressed
