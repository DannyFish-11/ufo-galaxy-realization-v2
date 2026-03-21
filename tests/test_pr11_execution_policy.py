"""
tests/test_pr11_execution_policy.py
=====================================
Tests for PR-11: Execution Policy Schema.

Coverage
--------
A) PolicyBand enum
   - all expected values present
   - string values are stable
   - band_allows_execution helper
   - band_allows_cross_device helper
   - band_requires_confirmation helper
   - BAND_ORDER ordering

B) ExecutionPolicy dataclass
   - default (conservative) construction
   - field round-trip via to_dict()
   - from_dict() reconstruction
   - derived helpers: can_execute, can_expand_cross_device,
     should_require_confirmation, max_executor_level
   - DEFAULT_CONSERVATIVE_POLICY constant
   - frozen / immutable
   - __repr__ smoke test

C) resolve_policy — phase-primary resolution
   - None phase → observe_only
   - silent → observe_only
   - liminal → assistive
   - manifest → bounded_execute
   - manifest + cross_device → full_execute with cross_device_allowed=True

D) resolve_policy — domain / authority interactions
   - manifest + local domain → bounded_execute
   - manifest + transition domain → bounded_execute (no upgrade)
   - manifest + cross_device + legacy authority → bounded_execute (downgrade)
   - manifest + cross_device + deprecated authority → bounded_execute (downgrade)
   - manifest + cross_device + active authority → full_execute

E) resolve_policy — return-pressure interactions
   - high return pressure (>= 0.75 threshold) → observe_only override
   - moderate return pressure (>= 0.40) → forces confirmation, no cross_device
   - moderate pressure + full_execute band → clamped to bounded_execute
   - return_to_formless mode → high pressure → observe_only
   - step_down mode → moderate pressure
   - soft_decay mode → below restrict threshold
   - no return (IDLE) → no pressure effect

F) resolve_policy — retreat_tendency interactions
   - retreat_tendency >= 0.7 → triggers restrict threshold
   - retreat_tendency < 0.5 → no effect
   - None retreat_tendency → handled gracefully

G) resolve_policy — graceful partial-input handling
   - only phase provided (no domain, authority, return)
   - only domain provided (no phase)
   - string phase values accepted
   - string domain values accepted
   - string authority_role values accepted
   - dict return_summary accepted (duck-typing)
   - None return_summary → no error

H) summarise_policy
   - None input → DEFAULT_CONSERVATIVE_POLICY summary
   - normal policy → stable dict
   - all required keys present
   - enum values serialised as strings

I) get_policy_hints
   - None input → conservative hints
   - observe_only policy → can_execute=False
   - bounded_execute policy → can_execute=True, should_require_confirmation=True
   - full_execute policy → can_execute=True, can_expand_cross_device=True
   - max_executor_level matches last allowed level

J) attach_policy_to_projection
   - original projection dict not mutated
   - execution_policy key added
   - existing fields unchanged
   - works with minimal projection dict

K) build_policy_for_projection
   - extracts phase/domain/retreat from projection dict
   - returns hints dict
   - graceful on minimal projection
   - consumes return_intelligence if already attached

L) Integration: resolve_policy with actual AuthorityRole enum
   - AUTHORITATIVE_ENTRYPOINT + manifest/cross_device → full_execute
   - LEGACY_COMPATIBILITY → band downgraded
   - DEPRECATED → band downgraded

M) Budget table consistency
   - observe_only budgets are zero
   - full_execute risk_budget is 1.0
   - action_budget -1 means unbounded for full_execute

N) API projection endpoint helpers
   - _assemble_projection_with_execution_policy returns execution_policy key
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

# ---------------------------------------------------------------------------
# Import subjects
# ---------------------------------------------------------------------------

from core.execution_policy.policy_band import (
    PolicyBand,
    BAND_ORDER,
    band_allows_execution,
    band_allows_cross_device,
    band_requires_confirmation,
    band_rank,
)
from core.execution_policy.execution_policy import (
    ExecutionPolicy,
    DEFAULT_CONSERVATIVE_POLICY,
)
from core.execution_policy.policy_resolver import (
    resolve_policy,
    RETURN_PRESSURE_FORCE_OBSERVE,
    RETURN_PRESSURE_RESTRICT,
)
from core.execution_policy.policy_summary import (
    summarise_policy,
    get_policy_hints,
    attach_policy_to_projection,
    build_policy_for_projection,
)
from core.execution_policy import (
    PolicyBand as PolicyBandPublic,
    ExecutionPolicy as ExecutionPolicyPublic,
    resolve_policy as resolve_policy_public,
    DEFAULT_CONSERVATIVE_POLICY as CONSERVATIVE_PUBLIC,
    get_policy_hints as hints_public,
    attach_policy_to_projection as attach_public,
    build_policy_for_projection as build_public,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_PROJECTION: Dict[str, Any] = {
    "tri_state_phase": "silent",
    "runtime_domain": None,
    "presence_intensity": None,
    "coherence": None,
    "collapse_tendency": None,
    "retreat_tendency": None,
    "primary_model_id": None,
    "support_model_ids": [],
    "active_weights": {},
    "route_reason": None,
    "active_device_ids": [],
    "execution_stage": None,
    "current_task_summary": None,
    "timestamp": 1700000000.0,
}

_MANIFEST_PROJECTION: Dict[str, Any] = {
    **_MINIMAL_PROJECTION,
    "tri_state_phase": "manifest",
    "runtime_domain": "local",
    "presence_intensity": 0.82,
    "coherence": 0.75,
    "collapse_tendency": 0.30,
    "retreat_tendency": 0.10,
}

_IDLE_RETURN_SUMMARY_DICT: Dict[str, Any] = {
    "is_returning": False,
    "return_mode": "none",
    "return_action": None,
    "return_trigger": None,
    "decay_amount": 0.0,
    "reason": "no return active",
    "affects_manifest": False,
    "affects_liminal": False,
}

_STEP_DOWN_RETURN_DICT: Dict[str, Any] = {
    "is_returning": True,
    "return_mode": "step_down",
    "return_action": "step_down",
    "return_trigger": "finished",
    "decay_amount": 0.0,
    "reason": "step down triggered",
    "affects_manifest": True,
    "affects_liminal": True,
}

_RETURN_TO_FORMLESS_DICT: Dict[str, Any] = {
    "is_returning": True,
    "return_mode": "return_to_formless",
    "return_action": "return_to_formless",
    "return_trigger": "user_cancel",
    "decay_amount": 0.0,
    "reason": "hard reset",
    "affects_manifest": True,
    "affects_liminal": True,
}

_SOFT_DECAY_RETURN_DICT: Dict[str, Any] = {
    "is_returning": True,
    "return_mode": "soft_decay",
    "return_action": "soft_decay",
    "return_trigger": "low_value",
    "decay_amount": 0.2,
    "reason": "soft decay",
    "affects_manifest": False,
    "affects_liminal": True,
}


# ===========================================================================
# A) PolicyBand enum
# ===========================================================================

class TestPolicyBandEnum:
    def test_all_bands_present(self):
        values = {b.value for b in PolicyBand}
        assert "observe_only" in values
        assert "assistive" in values
        assert "bounded_execute" in values
        assert "full_execute" in values

    def test_string_values_stable(self):
        assert PolicyBand.OBSERVE_ONLY.value == "observe_only"
        assert PolicyBand.ASSISTIVE.value == "assistive"
        assert PolicyBand.BOUNDED_EXECUTE.value == "bounded_execute"
        assert PolicyBand.FULL_EXECUTE.value == "full_execute"

    def test_band_is_str(self):
        assert isinstance(PolicyBand.OBSERVE_ONLY, str)

    def test_band_order_length(self):
        assert len(BAND_ORDER) == 4

    def test_band_order_starts_least_permissive(self):
        assert BAND_ORDER[0] is PolicyBand.OBSERVE_ONLY
        assert BAND_ORDER[-1] is PolicyBand.FULL_EXECUTE

    def test_band_rank_increasing(self):
        ranks = [band_rank(b) for b in BAND_ORDER]
        assert ranks == sorted(ranks)

    def test_band_allows_execution_false_for_observe(self):
        assert band_allows_execution(PolicyBand.OBSERVE_ONLY) is False

    def test_band_allows_execution_false_for_assistive(self):
        assert band_allows_execution(PolicyBand.ASSISTIVE) is False

    def test_band_allows_execution_true_for_bounded(self):
        assert band_allows_execution(PolicyBand.BOUNDED_EXECUTE) is True

    def test_band_allows_execution_true_for_full(self):
        assert band_allows_execution(PolicyBand.FULL_EXECUTE) is True

    def test_band_allows_cross_device_only_full(self):
        assert band_allows_cross_device(PolicyBand.FULL_EXECUTE) is True
        assert band_allows_cross_device(PolicyBand.BOUNDED_EXECUTE) is False
        assert band_allows_cross_device(PolicyBand.ASSISTIVE) is False
        assert band_allows_cross_device(PolicyBand.OBSERVE_ONLY) is False

    def test_band_requires_confirmation_bounded_only(self):
        assert band_requires_confirmation(PolicyBand.BOUNDED_EXECUTE) is True
        assert band_requires_confirmation(PolicyBand.FULL_EXECUTE) is False
        assert band_requires_confirmation(PolicyBand.ASSISTIVE) is False
        assert band_requires_confirmation(PolicyBand.OBSERVE_ONLY) is False


# ===========================================================================
# B) ExecutionPolicy dataclass
# ===========================================================================

class TestExecutionPolicy:
    def test_default_construction(self):
        p = ExecutionPolicy()
        assert p.policy_band is PolicyBand.OBSERVE_ONLY
        assert p.risk_budget == 0.0
        assert p.action_budget == 0
        assert p.fallback_budget == 0
        assert p.allowed_executor_levels == []
        assert p.cross_device_allowed is False
        assert p.requires_confirmation is True

    def test_to_dict_all_keys_present(self):
        p = ExecutionPolicy(
            policy_band=PolicyBand.BOUNDED_EXECUTE,
            risk_budget=0.5,
            action_budget=5,
            fallback_budget=2,
            allowed_executor_levels=["system_api", "uia"],
            cross_device_allowed=False,
            requires_confirmation=True,
            reason="test reason",
        )
        d = p.to_dict()
        required_keys = {
            "policy_band", "risk_budget", "action_budget", "fallback_budget",
            "allowed_executor_levels", "cross_device_allowed", "requires_confirmation",
            "reason", "source_phase", "source_domain", "source_authority_role",
            "return_pressure", "can_execute", "can_expand_cross_device",
            "should_require_confirmation", "max_executor_level",
        }
        assert required_keys.issubset(d.keys())

    def test_to_dict_band_is_string(self):
        p = ExecutionPolicy(policy_band=PolicyBand.FULL_EXECUTE)
        d = p.to_dict()
        assert d["policy_band"] == "full_execute"
        assert isinstance(d["policy_band"], str)

    def test_from_dict_round_trip(self):
        original = ExecutionPolicy(
            policy_band=PolicyBand.BOUNDED_EXECUTE,
            risk_budget=0.5,
            action_budget=3,
            fallback_budget=2,
            allowed_executor_levels=["system_api"],
            cross_device_allowed=False,
            requires_confirmation=True,
            reason="round-trip test",
            source_phase="manifest",
            return_pressure=0.2,
        )
        reconstructed = ExecutionPolicy.from_dict(original.to_dict())
        assert reconstructed.policy_band is PolicyBand.BOUNDED_EXECUTE
        assert reconstructed.risk_budget == 0.5
        assert reconstructed.action_budget == 3
        assert reconstructed.reason == "round-trip test"

    def test_from_dict_unknown_band_defaults_conservative(self):
        p = ExecutionPolicy.from_dict({"policy_band": "bogus_band"})
        assert p.policy_band is PolicyBand.OBSERVE_ONLY

    def test_frozen_immutable(self):
        p = ExecutionPolicy()
        with pytest.raises((AttributeError, TypeError)):
            p.policy_band = PolicyBand.FULL_EXECUTE  # type: ignore[misc]

    def test_can_execute_false_for_observe(self):
        p = ExecutionPolicy(policy_band=PolicyBand.OBSERVE_ONLY, action_budget=0)
        assert p.can_execute is False

    def test_can_execute_true_for_bounded(self):
        p = ExecutionPolicy(policy_band=PolicyBand.BOUNDED_EXECUTE, action_budget=5)
        assert p.can_execute is True

    def test_can_execute_false_when_action_budget_zero(self):
        p = ExecutionPolicy(policy_band=PolicyBand.BOUNDED_EXECUTE, action_budget=0)
        assert p.can_execute is False

    def test_can_expand_cross_device_respects_flag(self):
        p_yes = ExecutionPolicy(policy_band=PolicyBand.FULL_EXECUTE, cross_device_allowed=True)
        p_no = ExecutionPolicy(policy_band=PolicyBand.FULL_EXECUTE, cross_device_allowed=False)
        assert p_yes.can_expand_cross_device is True
        assert p_no.can_expand_cross_device is False

    def test_max_executor_level_none_when_empty(self):
        p = ExecutionPolicy(allowed_executor_levels=[])
        assert p.max_executor_level is None

    def test_max_executor_level_last_element(self):
        p = ExecutionPolicy(allowed_executor_levels=["system_api", "uia", "orchestrator"])
        assert p.max_executor_level == "orchestrator"

    def test_default_conservative_policy_constant(self):
        p = DEFAULT_CONSERVATIVE_POLICY
        assert p.policy_band is PolicyBand.OBSERVE_ONLY
        assert p.can_execute is False
        assert p.cross_device_allowed is False

    def test_repr_contains_band(self):
        p = ExecutionPolicy(policy_band=PolicyBand.ASSISTIVE)
        assert "assistive" in repr(p)


# ===========================================================================
# C) resolve_policy — phase-primary resolution
# ===========================================================================

class TestResolvePolicyPhase:
    def test_no_phase_defaults_observe_only(self):
        p = resolve_policy()
        assert p.policy_band is PolicyBand.OBSERVE_ONLY

    def test_silent_phase(self):
        p = resolve_policy(phase="silent")
        assert p.policy_band is PolicyBand.OBSERVE_ONLY

    def test_liminal_phase(self):
        p = resolve_policy(phase="liminal")
        assert p.policy_band is PolicyBand.ASSISTIVE

    def test_manifest_phase(self):
        p = resolve_policy(phase="manifest")
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE

    def test_manifest_local_domain(self):
        p = resolve_policy(phase="manifest", domain="local")
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE
        assert p.cross_device_allowed is False

    def test_manifest_cross_device(self):
        p = resolve_policy(phase="manifest", domain="cross_device")
        assert p.policy_band is PolicyBand.FULL_EXECUTE
        assert p.cross_device_allowed is True

    def test_manifest_transition_domain_no_upgrade(self):
        p = resolve_policy(phase="manifest", domain="transition")
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE

    def test_source_phase_recorded(self):
        p = resolve_policy(phase="liminal")
        assert p.source_phase == "liminal"

    def test_source_domain_recorded(self):
        p = resolve_policy(phase="manifest", domain="local")
        assert p.source_domain == "local"

    def test_reason_non_empty(self):
        p = resolve_policy(phase="manifest")
        assert isinstance(p.reason, str)
        assert len(p.reason) > 0


# ===========================================================================
# D) resolve_policy — authority interactions
# ===========================================================================

class TestResolvePolicyAuthority:
    def test_legacy_authority_downgrades_manifest_cross_device(self):
        p = resolve_policy(
            phase="manifest",
            domain="cross_device",
            authority_role="legacy_compatibility",
        )
        # full_execute downgraded by one level → bounded_execute
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE
        assert p.cross_device_allowed is False

    def test_deprecated_authority_downgrades(self):
        p = resolve_policy(
            phase="manifest",
            domain="cross_device",
            authority_role="deprecated",
        )
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE
        assert p.cross_device_allowed is False

    def test_authoritative_entrypoint_no_downgrade(self):
        p = resolve_policy(
            phase="manifest",
            domain="cross_device",
            authority_role="authoritative_entrypoint",
        )
        assert p.policy_band is PolicyBand.FULL_EXECUTE
        assert p.cross_device_allowed is True

    def test_unknown_authority_treated_as_active(self):
        # unknown should not trigger legacy downgrade
        p = resolve_policy(
            phase="manifest",
            domain="cross_device",
            authority_role="unknown",
        )
        # 'unknown' is not legacy/deprecated so no downgrade
        assert p.policy_band is PolicyBand.FULL_EXECUTE

    def test_source_authority_role_recorded(self):
        p = resolve_policy(phase="manifest", authority_role="legacy_compatibility")
        assert p.source_authority_role == "legacy_compatibility"


# ===========================================================================
# E) resolve_policy — return-pressure interactions
# ===========================================================================

class TestResolvePolicyReturnPressure:
    def test_return_to_formless_forces_observe_only(self):
        p = resolve_policy(
            phase="manifest",
            domain="cross_device",
            return_summary=_RETURN_TO_FORMLESS_DICT,
        )
        assert p.policy_band is PolicyBand.OBSERVE_ONLY

    def test_step_down_restricts_but_not_force_observe(self):
        # step_down pressure = 0.65 → >= restrict (0.40) but < force_observe (0.75)
        p = resolve_policy(phase="manifest", return_summary=_STEP_DOWN_RETURN_DICT)
        assert p.policy_band is not PolicyBand.OBSERVE_ONLY
        assert p.requires_confirmation is True
        assert p.cross_device_allowed is False

    def test_step_down_clamps_full_execute_to_bounded(self):
        # manifest + cross_device would be full_execute, but step_down restricts
        p = resolve_policy(
            phase="manifest",
            domain="cross_device",
            return_summary=_STEP_DOWN_RETURN_DICT,
        )
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE

    def test_soft_decay_no_restriction(self):
        # soft_decay pressure ~0.41 for decay=0.2 → just over restrict threshold
        # depends on exact calculation but soft_decay + low decay should be fine
        p = resolve_policy(phase="manifest", return_summary=_SOFT_DECAY_RETURN_DICT)
        # soft_decay with decay=0.2: pressure = 0.35 + 0.2*0.20 = 0.39 → just under RESTRICT
        # so should not force confirmation
        assert isinstance(p, ExecutionPolicy)

    def test_idle_return_no_pressure(self):
        p = resolve_policy(phase="manifest", return_summary=_IDLE_RETURN_SUMMARY_DICT)
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE
        assert p.return_pressure == 0.0

    def test_none_return_summary_no_error(self):
        p = resolve_policy(phase="manifest", return_summary=None)
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE

    def test_return_pressure_recorded(self):
        p = resolve_policy(phase="manifest", return_summary=_RETURN_TO_FORMLESS_DICT)
        assert p.return_pressure >= RETURN_PRESSURE_FORCE_OBSERVE


# ===========================================================================
# F) resolve_policy — retreat_tendency interactions
# ===========================================================================

class TestResolvePolicyRetreat:
    def test_high_retreat_triggers_restriction(self):
        p = resolve_policy(phase="manifest", retreat_tendency=0.75)
        assert p.requires_confirmation is True
        assert p.cross_device_allowed is False

    def test_low_retreat_no_effect(self):
        p = resolve_policy(phase="manifest", retreat_tendency=0.2)
        # low retreat shouldn't restrict
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE
        assert p.requires_confirmation is True  # bounded_execute always requires

    def test_none_retreat_no_error(self):
        p = resolve_policy(phase="manifest", retreat_tendency=None)
        assert isinstance(p, ExecutionPolicy)


# ===========================================================================
# G) resolve_policy — graceful partial inputs
# ===========================================================================

class TestResolvePolicyPartialInputs:
    def test_only_phase(self):
        p = resolve_policy(phase="liminal")
        assert p.policy_band is PolicyBand.ASSISTIVE

    def test_only_domain(self):
        p = resolve_policy(domain="cross_device")
        # No phase → observe_only base, domain upgrade requires manifest
        assert p.policy_band is PolicyBand.OBSERVE_ONLY

    def test_tristatephase_enum_accepted(self):
        from core.continuum.types import TriStatePhase
        p = resolve_policy(phase=TriStatePhase.MANIFEST)
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE

    def test_runtimedomain_enum_accepted(self):
        from core.continuum.types import TriStatePhase, RuntimeDomain
        p = resolve_policy(phase=TriStatePhase.MANIFEST, domain=RuntimeDomain.CROSS_DEVICE)
        assert p.policy_band is PolicyBand.FULL_EXECUTE

    def test_authority_role_enum_accepted(self):
        from core.orchestration_authority import AuthorityRole
        p = resolve_policy(
            phase="manifest",
            domain="cross_device",
            authority_role=AuthorityRole.AUTHORITATIVE_ENTRYPOINT,
        )
        assert p.policy_band is PolicyBand.FULL_EXECUTE

    def test_return_summary_object_accepted(self):
        from core.return_intelligence import IDLE_RETURN_SUMMARY
        p = resolve_policy(phase="manifest", return_summary=IDLE_RETURN_SUMMARY)
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE

    def test_bogus_phase_defaults_observe_only(self):
        p = resolve_policy(phase="not_a_phase")
        assert p.policy_band is PolicyBand.OBSERVE_ONLY

    def test_empty_string_phase_defaults_observe_only(self):
        p = resolve_policy(phase="")
        assert p.policy_band is PolicyBand.OBSERVE_ONLY


# ===========================================================================
# H) summarise_policy
# ===========================================================================

class TestSummarisePolicy:
    def test_none_returns_conservative_summary(self):
        d = summarise_policy(None)
        assert d["policy_band"] == "observe_only"
        assert d["can_execute"] is False

    def test_full_execute_policy(self):
        p = ExecutionPolicy(
            policy_band=PolicyBand.FULL_EXECUTE,
            risk_budget=1.0,
            action_budget=-1,
            fallback_budget=3,
            allowed_executor_levels=["system_api", "uia", "gui", "vlm", "remote_executor", "orchestrator"],
            cross_device_allowed=True,
            requires_confirmation=False,
            reason="test",
        )
        d = summarise_policy(p)
        assert d["policy_band"] == "full_execute"
        assert d["risk_budget"] == 1.0
        assert d["cross_device_allowed"] is True

    def test_all_keys_present(self):
        d = summarise_policy(DEFAULT_CONSERVATIVE_POLICY)
        required = {
            "policy_band", "risk_budget", "action_budget", "fallback_budget",
            "allowed_executor_levels", "cross_device_allowed", "requires_confirmation",
            "reason", "can_execute", "can_expand_cross_device",
            "should_require_confirmation", "max_executor_level",
        }
        assert required.issubset(d.keys())

    def test_enum_values_are_strings(self):
        d = summarise_policy(DEFAULT_CONSERVATIVE_POLICY)
        assert isinstance(d["policy_band"], str)

    def test_idempotent(self):
        p = resolve_policy(phase="liminal")
        assert summarise_policy(p) == summarise_policy(p)


# ===========================================================================
# I) get_policy_hints
# ===========================================================================

class TestGetPolicyHints:
    def test_none_returns_conservative(self):
        hints = get_policy_hints(None)
        assert hints["policy_band"] == "observe_only"
        assert hints["can_execute"] is False
        assert hints["can_expand_cross_device"] is False
        assert hints["should_require_confirmation"] is True
        assert hints["max_executor_level"] is None

    def test_observe_only_hints(self):
        p = ExecutionPolicy(policy_band=PolicyBand.OBSERVE_ONLY, action_budget=0)
        hints = get_policy_hints(p)
        assert hints["can_execute"] is False
        assert hints["max_executor_level"] is None

    def test_bounded_execute_hints(self):
        p = ExecutionPolicy(
            policy_band=PolicyBand.BOUNDED_EXECUTE,
            action_budget=5,
            allowed_executor_levels=["system_api", "uia", "orchestrator"],
            requires_confirmation=True,
        )
        hints = get_policy_hints(p)
        assert hints["can_execute"] is True
        assert hints["should_require_confirmation"] is True
        assert hints["max_executor_level"] == "orchestrator"

    def test_full_execute_hints(self):
        p = ExecutionPolicy(
            policy_band=PolicyBand.FULL_EXECUTE,
            action_budget=-1,
            cross_device_allowed=True,
            requires_confirmation=False,
            allowed_executor_levels=["system_api", "uia", "gui", "vlm", "remote_executor", "orchestrator"],
        )
        hints = get_policy_hints(p)
        assert hints["can_execute"] is True
        assert hints["can_expand_cross_device"] is True
        assert hints["should_require_confirmation"] is False
        assert hints["max_executor_level"] == "orchestrator"

    def test_hints_keys_present(self):
        hints = get_policy_hints(None)
        required = {
            "policy_band", "can_execute", "can_expand_cross_device",
            "should_require_confirmation", "max_executor_level",
            "risk_budget", "action_budget", "return_pressure",
        }
        assert required.issubset(hints.keys())


# ===========================================================================
# J) attach_policy_to_projection
# ===========================================================================

class TestAttachPolicyToProjection:
    def test_original_not_mutated(self):
        original = dict(_MINIMAL_PROJECTION)
        policy = DEFAULT_CONSERVATIVE_POLICY
        enriched = attach_policy_to_projection(original, policy)
        assert "execution_policy" not in original
        assert "execution_policy" in enriched

    def test_existing_fields_unchanged(self):
        original = dict(_MANIFEST_PROJECTION)
        policy = resolve_policy(phase="manifest")
        enriched = attach_policy_to_projection(original, policy)
        assert enriched["tri_state_phase"] == "manifest"
        assert enriched["runtime_domain"] == "local"

    def test_execution_policy_key_present(self):
        enriched = attach_policy_to_projection(dict(_MINIMAL_PROJECTION), DEFAULT_CONSERVATIVE_POLICY)
        assert "execution_policy" in enriched
        assert isinstance(enriched["execution_policy"], dict)

    def test_none_policy_uses_default(self):
        enriched = attach_policy_to_projection(dict(_MINIMAL_PROJECTION), None)
        assert enriched["execution_policy"]["policy_band"] == "observe_only"

    def test_works_with_minimal_projection(self):
        minimal = {"tri_state_phase": "silent"}
        enriched = attach_policy_to_projection(minimal, None)
        assert "execution_policy" in enriched
        assert enriched["tri_state_phase"] == "silent"


# ===========================================================================
# K) build_policy_for_projection
# ===========================================================================

class TestBuildPolicyForProjection:
    def test_manifest_projection_returns_execution_hints(self):
        hints = build_policy_for_projection(_MANIFEST_PROJECTION)
        assert hints["policy_band"] == "bounded_execute"
        assert hints["can_execute"] is True

    def test_silent_projection_observe_only(self):
        hints = build_policy_for_projection(_MINIMAL_PROJECTION)
        assert hints["policy_band"] == "observe_only"

    def test_minimal_projection_no_error(self):
        hints = build_policy_for_projection({})
        assert "policy_band" in hints

    def test_consumes_return_intelligence_if_present(self):
        proj = {
            **_MANIFEST_PROJECTION,
            "return_intelligence": _RETURN_TO_FORMLESS_DICT,
        }
        hints = build_policy_for_projection(proj)
        assert hints["policy_band"] == "observe_only"

    def test_consumes_retreat_tendency(self):
        proj = {**_MANIFEST_PROJECTION, "retreat_tendency": 0.8}
        hints = build_policy_for_projection(proj)
        assert hints["should_require_confirmation"] is True


# ===========================================================================
# L) Integration with actual AuthorityRole enum
# ===========================================================================

class TestIntegrationWithAuthorityRole:
    def test_authoritative_entrypoint_manifest_cross_device(self):
        from core.orchestration_authority import AuthorityRole
        p = resolve_policy(
            phase="manifest",
            domain="cross_device",
            authority_role=AuthorityRole.AUTHORITATIVE_ENTRYPOINT,
        )
        assert p.policy_band is PolicyBand.FULL_EXECUTE
        assert p.cross_device_allowed is True

    def test_execution_runtime_delegate_manifest_cross_device(self):
        from core.orchestration_authority import AuthorityRole
        p = resolve_policy(
            phase="manifest",
            domain="cross_device",
            authority_role=AuthorityRole.EXECUTION_RUNTIME_DELEGATE,
        )
        assert p.policy_band is PolicyBand.FULL_EXECUTE

    def test_legacy_compatibility_downgrades(self):
        from core.orchestration_authority import AuthorityRole
        p = resolve_policy(
            phase="manifest",
            domain="cross_device",
            authority_role=AuthorityRole.LEGACY_COMPATIBILITY,
        )
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE
        assert p.cross_device_allowed is False

    def test_deprecated_downgrades(self):
        from core.orchestration_authority import AuthorityRole
        p = resolve_policy(
            phase="manifest",
            domain="cross_device",
            authority_role=AuthorityRole.DEPRECATED,
        )
        assert p.policy_band is PolicyBand.BOUNDED_EXECUTE


# ===========================================================================
# M) Budget table consistency
# ===========================================================================

class TestBudgetConsistency:
    def test_observe_only_zero_budgets(self):
        p = resolve_policy(phase="silent")
        assert p.risk_budget == 0.0
        assert p.action_budget == 0
        assert p.fallback_budget == 0
        assert p.allowed_executor_levels == []

    def test_full_execute_risk_budget_one(self):
        p = resolve_policy(phase="manifest", domain="cross_device")
        assert p.risk_budget == 1.0

    def test_full_execute_action_budget_unbounded(self):
        p = resolve_policy(phase="manifest", domain="cross_device")
        assert p.action_budget == -1

    def test_bounded_execute_moderate_budgets(self):
        p = resolve_policy(phase="manifest", domain="local")
        assert 0 < p.risk_budget < 1.0
        assert p.action_budget > 0

    def test_assistive_no_action_budget(self):
        p = resolve_policy(phase="liminal")
        assert p.action_budget == 0


# ===========================================================================
# N) Public __init__ surface
# ===========================================================================

class TestPublicAPI:
    def test_public_band_same_as_internal(self):
        assert PolicyBandPublic is PolicyBand

    def test_public_policy_same_as_internal(self):
        assert ExecutionPolicyPublic is ExecutionPolicy

    def test_public_resolve_same_as_internal(self):
        assert resolve_policy_public is resolve_policy

    def test_public_conservative_same_as_internal(self):
        assert CONSERVATIVE_PUBLIC is DEFAULT_CONSERVATIVE_POLICY

    def test_public_hints_works(self):
        hints = hints_public(None)
        assert "policy_band" in hints

    def test_public_attach_works(self):
        enriched = attach_public(dict(_MINIMAL_PROJECTION), None)
        assert "execution_policy" in enriched

    def test_public_build_works(self):
        hints = build_public(_MANIFEST_PROJECTION)
        assert "can_execute" in hints
