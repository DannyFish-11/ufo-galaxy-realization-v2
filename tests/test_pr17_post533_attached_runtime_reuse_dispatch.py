"""tests/test_pr17_post533_attached_runtime_reuse_dispatch.py
==============================================================
Tests for PR package 17 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Dispatch Consumption of Attached-Runtime Reuse
Bindings.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — DispatchReuseDecision enum: all values, from_string(), defaults.
C  — ReuseSurfaceResolution: construction, defaults, convenience predicates,
     to_dict().
D  — ReuseDispatchOutcome: construction, defaults, to_dict().
E  — resolve_reuse_surface: no binding found → new_binding decision.
F  — resolve_reuse_surface: eligible binding → reuse decision.
G  — resolve_reuse_surface: ineligible binding → rejected decision.
H  — resolve_reuse_surface: session_id lookup priority over device_id.
I  — resolve_reuse_surface: device_id fallback when session_id yields nothing.
J  — resolve_reuse_surface: live attached_session forwarded to eligibility gate.
K  — resolve_reuse_surface: invalidated binding (detach) → rejected.
L  — resolve_reuse_surface: invalidated binding (disconnect) → rejected.
M  — resolve_reuse_surface: invalidated binding (disable) → rejected.
N  — resolve_reuse_surface: invalidated binding (invalidate) → rejected.
O  — resolve_reuse_surface: identity fields preserved from binding in resolution.
P  — execute_reuse_dispatch: no binding → new_binding outcome, no dispatch binding.
Q  — execute_reuse_dispatch: eligible binding → reuse outcome, dispatch binding created.
R  — execute_reuse_dispatch: ineligible binding → rejected, no dispatch binding.
S  — execute_reuse_dispatch: dispatch binding uses identity from reuse binding.
T  — execute_reuse_dispatch: dispatch_binding_id written back to reuse binding.
U  — execute_reuse_dispatch: updated_reuse_binding.dispatch_binding_id matches.
V  — execute_reuse_dispatch: was_reused=True only on reuse decision.
W  — execute_reuse_dispatch: was_reused=False on rejected decision.
X  — execute_reuse_dispatch: was_reused=False on new_binding decision.
Y  — execute_reuse_dispatch: session_id / device_id in outcome from reuse binding.
Z  — execute_reuse_dispatch: contract_id / tracker_id forwarded to dispatch binding.

AA — Integration: same session multi-dispatch reuse (consecutive dispatches
     all reuse the same surface; each updates the reuse binding's
     dispatch_binding_id).
AB — Integration: invalidated binding rejection (detach → dispatch rejected).
AC — Integration: disconnect → dispatch rejected.
AD — Integration: disable → dispatch rejected.
AE — Integration: re-establish after reattach (invalidate → new establish →
     dispatch succeeds again).
AF — Integration: eligible binding → dispatch binding is in unbound state
     (freshly created, not yet advanced).
AG — execute_reuse_dispatch: trace_id auto-generated when not provided.
AH — execute_reuse_dispatch: provided trace_id forwarded to dispatch binding.
AI — execute_reuse_dispatch: caller coordination_role used when binding has none.
AJ — execute_reuse_dispatch: reuse binding coordination_role takes precedence.
AK — core.runtime re-exports: all PR-17 symbols accessible from core.runtime.
AL — projection.py sentinel: ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17
     present and not UNAVAILABLE.
AM — All 10 policy sentinels are non-empty strings.
AN — ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL contains 'package=17'.
AO — resolve_reuse_surface: empty session_id and device_id → new_binding.
AP — execute_reuse_dispatch: empty session_id and device_id → new_binding.
AQ — ReuseSurfaceResolution: is_reuse() / is_rejected() / is_new_binding().
AR — ReuseDispatchOutcome: to_dict() contains all expected keys.
AS — execute_reuse_dispatch: reuse binding runtime isolation (separate runtimes).
AT — execute_reuse_dispatch: dispatch binding uses join_runtime posture from binding.
AU — Integration: two separate sessions do not interfere with each other.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import pytest

from core.attached_runtime_reuse_dispatch import (
    ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY,
    ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL,
    REUSE_DISPATCH_LOOKUP_BEFORE_DISPATCH_POLICY,
    REUSE_DISPATCH_ELIGIBILITY_GATE_IS_UNCONDITIONAL_POLICY,
    REUSE_DISPATCH_ELIGIBLE_REUSES_SURFACE_POLICY,
    REUSE_DISPATCH_INELIGIBLE_DOES_NOT_DISPATCH_POLICY,
    REUSE_DISPATCH_WRITE_BACK_DISPATCH_BINDING_ID_POLICY,
    REUSE_DISPATCH_FALLBACK_ON_MISSING_BINDING_POLICY,
    REUSE_DISPATCH_INVALIDATED_BINDING_NOT_CONSUMED_POLICY,
    REUSE_DISPATCH_SESSION_LOOKUP_PRIORITY_POLICY,
    REUSE_DISPATCH_DISPATCH_BINDING_USES_REUSE_IDENTITY_POLICY,
    REUSE_DISPATCH_OUTCOME_IS_INSPECTABLE_POLICY,
    DispatchReuseDecision,
    ReuseSurfaceResolution,
    ReuseDispatchOutcome,
    resolve_reuse_surface,
    execute_reuse_dispatch,
)
from core.attached_runtime_reuse_binding import (
    AttachedRuntimeReuseBindingRuntime,
    establish_reuse_binding,
    invalidate_reuse_binding,
    get_reuse_binding,
    reset_reuse_binding_runtime,
)
from core.android_runtime_dispatch_binding import (
    AndroidRuntimeDispatchBindingRuntime,
    AndroidRuntimeBindingState,
    reset_dispatch_binding_runtime,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_reuse_rt() -> AttachedRuntimeReuseBindingRuntime:
    """Return a fresh isolated reuse binding runtime for test isolation."""
    return AttachedRuntimeReuseBindingRuntime()


def _fresh_dispatch_rt() -> AndroidRuntimeDispatchBindingRuntime:
    """Return a fresh isolated dispatch binding runtime for test isolation."""
    return AndroidRuntimeDispatchBindingRuntime()


def _eligible_session(session_id: str = "s1", device_id: str = "d1", reuse_rt=None):
    """Establish and return an eligible reuse binding record."""
    rt = reuse_rt or _fresh_reuse_rt()
    rec = establish_reuse_binding(
        session_id=session_id,
        device_id=device_id,
        source_runtime_posture="join_runtime",
        runtime=rt,
    )
    return rec, rt


class _AttachedSession:
    """Minimal attached session stub for evaluate_reuse_eligibility."""

    def __init__(self, state: str = "attached", posture: str = "join_runtime"):
        self.attachment_state = state
        self.source_runtime_posture = posture


# ---------------------------------------------------------------------------
# Group A — Authority / policy sentinel presence
# ---------------------------------------------------------------------------


class TestGroupA_Authority:
    def test_A01_authority_sentinel_non_empty(self):
        assert ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY
        assert isinstance(ATTACHED_RUNTIME_REUSE_DISPATCH_AUTHORITY, str)

    def test_A02_pr17_sentinel_contains_package_17(self):
        assert "package=17" in ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL

    def test_A03_pr17_sentinel_non_empty(self):
        assert ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL
        assert isinstance(ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL, str)


# ---------------------------------------------------------------------------
# Group B — DispatchReuseDecision enum
# ---------------------------------------------------------------------------


class TestGroupB_DispatchReuseDecision:
    def test_B01_reuse_value(self):
        assert DispatchReuseDecision.reuse == "reuse"

    def test_B02_new_binding_value(self):
        assert DispatchReuseDecision.new_binding == "new_binding"

    def test_B03_rejected_value(self):
        assert DispatchReuseDecision.rejected == "rejected"

    def test_B04_from_string_reuse(self):
        assert DispatchReuseDecision.from_string("reuse") == DispatchReuseDecision.reuse

    def test_B05_from_string_new_binding(self):
        assert DispatchReuseDecision.from_string("new_binding") == DispatchReuseDecision.new_binding

    def test_B06_from_string_rejected(self):
        assert DispatchReuseDecision.from_string("rejected") == DispatchReuseDecision.rejected

    def test_B07_from_string_case_insensitive(self):
        assert DispatchReuseDecision.from_string("REUSE") == DispatchReuseDecision.reuse

    def test_B08_from_string_unknown_defaults_to_rejected(self):
        assert DispatchReuseDecision.from_string("unknown_xyz") == DispatchReuseDecision.rejected

    def test_B09_from_string_non_string_defaults_to_rejected(self):
        assert DispatchReuseDecision.from_string(42) == DispatchReuseDecision.rejected  # type: ignore[arg-type]

    def test_B10_all_three_values_present(self):
        values = {e.value for e in DispatchReuseDecision}
        assert values == {"reuse", "new_binding", "rejected"}


# ---------------------------------------------------------------------------
# Group C — ReuseSurfaceResolution
# ---------------------------------------------------------------------------


class TestGroupC_ReuseSurfaceResolution:
    def test_C01_default_decision_is_rejected(self):
        r = ReuseSurfaceResolution()
        assert r.decision == DispatchReuseDecision.rejected

    def test_C02_is_reuse_true_when_reuse(self):
        r = ReuseSurfaceResolution(decision=DispatchReuseDecision.reuse)
        assert r.is_reuse()
        assert not r.is_rejected()
        assert not r.is_new_binding()

    def test_C03_is_rejected_true_when_rejected(self):
        r = ReuseSurfaceResolution(decision=DispatchReuseDecision.rejected)
        assert r.is_rejected()
        assert not r.is_reuse()
        assert not r.is_new_binding()

    def test_C04_is_new_binding_true_when_new_binding(self):
        r = ReuseSurfaceResolution(decision=DispatchReuseDecision.new_binding)
        assert r.is_new_binding()
        assert not r.is_reuse()
        assert not r.is_rejected()

    def test_C05_to_dict_has_expected_keys(self):
        r = ReuseSurfaceResolution(
            decision=DispatchReuseDecision.reuse,
            session_id="s1",
            device_id="d1",
        )
        d = r.to_dict()
        assert "decision" in d
        assert "session_id" in d
        assert "device_id" in d
        assert "rejection_reason" in d
        assert "resolved_at" in d

    def test_C06_to_dict_decision_is_string(self):
        r = ReuseSurfaceResolution(decision=DispatchReuseDecision.reuse)
        assert r.to_dict()["decision"] == "reuse"

    def test_C07_reuse_binding_id_none_when_no_binding(self):
        r = ReuseSurfaceResolution(decision=DispatchReuseDecision.new_binding, reuse_binding=None)
        assert r.to_dict()["reuse_binding_id"] is None


# ---------------------------------------------------------------------------
# Group D — ReuseDispatchOutcome
# ---------------------------------------------------------------------------


class TestGroupD_ReuseDispatchOutcome:
    def test_D01_default_decision_is_rejected(self):
        o = ReuseDispatchOutcome()
        assert o.decision == DispatchReuseDecision.rejected

    def test_D02_was_reused_default_false(self):
        assert not ReuseDispatchOutcome().was_reused

    def test_D03_to_dict_has_expected_keys(self):
        o = ReuseDispatchOutcome(
            decision=DispatchReuseDecision.reuse,
            was_reused=True,
            session_id="s1",
            device_id="d1",
        )
        d = o.to_dict()
        for key in ("decision", "was_reused", "session_id", "device_id",
                    "reuse_binding_id", "dispatch_binding_id",
                    "updated_dispatch_binding_id", "rejection_reason",
                    "dispatched_at"):
            assert key in d, f"missing key: {key}"

    def test_D04_to_dict_decision_is_string(self):
        o = ReuseDispatchOutcome(decision=DispatchReuseDecision.new_binding)
        assert o.to_dict()["decision"] == "new_binding"

    def test_D05_dispatch_binding_id_none_when_no_binding(self):
        o = ReuseDispatchOutcome(dispatch_binding=None)
        assert o.to_dict()["dispatch_binding_id"] is None


# ---------------------------------------------------------------------------
# Group E — resolve_reuse_surface: no binding found
# ---------------------------------------------------------------------------


class TestGroupE_ResolveNoBinding:
    def test_E01_no_binding_returns_new_binding_decision(self):
        rt = _fresh_reuse_rt()
        res = resolve_reuse_surface("unknown-session", "unknown-device", reuse_runtime=rt)
        assert res.decision == DispatchReuseDecision.new_binding

    def test_E02_no_binding_rejection_reason_non_empty(self):
        rt = _fresh_reuse_rt()
        res = resolve_reuse_surface("missing-s", reuse_runtime=rt)
        assert res.rejection_reason

    def test_E03_no_binding_applied_policy_set(self):
        rt = _fresh_reuse_rt()
        res = resolve_reuse_surface("missing-s", reuse_runtime=rt)
        assert REUSE_DISPATCH_FALLBACK_ON_MISSING_BINDING_POLICY in res.applied_policy

    def test_E04_no_binding_reuse_binding_is_none(self):
        rt = _fresh_reuse_rt()
        res = resolve_reuse_surface("missing-s", reuse_runtime=rt)
        assert res.reuse_binding is None

    def test_E05_is_new_binding_true(self):
        rt = _fresh_reuse_rt()
        res = resolve_reuse_surface("missing-s", reuse_runtime=rt)
        assert res.is_new_binding()


# ---------------------------------------------------------------------------
# Group F — resolve_reuse_surface: eligible binding
# ---------------------------------------------------------------------------


class TestGroupF_ResolveEligible:
    def test_F01_eligible_binding_returns_reuse_decision(self):
        _, rt = _eligible_session("s1", "d1")
        res = resolve_reuse_surface("s1", "d1", reuse_runtime=rt)
        assert res.decision == DispatchReuseDecision.reuse

    def test_F02_eligible_reuse_binding_set(self):
        _, rt = _eligible_session("s1", "d1")
        res = resolve_reuse_surface("s1", "d1", reuse_runtime=rt)
        assert res.reuse_binding is not None

    def test_F03_eligible_rejection_reason_empty(self):
        _, rt = _eligible_session("s1", "d1")
        res = resolve_reuse_surface("s1", "d1", reuse_runtime=rt)
        assert res.rejection_reason == ""

    def test_F04_eligible_session_id_from_binding(self):
        _, rt = _eligible_session("sess-abc", "dev-xyz")
        res = resolve_reuse_surface("sess-abc", reuse_runtime=rt)
        assert res.session_id == "sess-abc"

    def test_F05_eligible_device_id_from_binding(self):
        _, rt = _eligible_session("sess-abc", "dev-xyz")
        res = resolve_reuse_surface("sess-abc", reuse_runtime=rt)
        assert res.device_id == "dev-xyz"

    def test_F06_is_reuse_true(self):
        _, rt = _eligible_session()
        res = resolve_reuse_surface("s1", reuse_runtime=rt)
        assert res.is_reuse()


# ---------------------------------------------------------------------------
# Group G — resolve_reuse_surface: ineligible binding
# ---------------------------------------------------------------------------


class TestGroupG_ResolveIneligible:
    def test_G01_ineligible_returns_rejected_decision(self):
        rec, rt = _eligible_session()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        res = resolve_reuse_surface("s1", reuse_runtime=rt)
        assert res.decision == DispatchReuseDecision.rejected

    def test_G02_ineligible_reuse_binding_set(self):
        rec, rt = _eligible_session()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        res = resolve_reuse_surface("s1", reuse_runtime=rt)
        assert res.reuse_binding is not None

    def test_G03_ineligible_rejection_reason_non_empty(self):
        rec, rt = _eligible_session()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        res = resolve_reuse_surface("s1", reuse_runtime=rt)
        assert res.rejection_reason

    def test_G04_ineligible_applied_policy_set(self):
        rec, rt = _eligible_session()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        res = resolve_reuse_surface("s1", reuse_runtime=rt)
        assert REUSE_DISPATCH_INELIGIBLE_DOES_NOT_DISPATCH_POLICY in res.applied_policy

    def test_G05_is_rejected_true(self):
        rec, rt = _eligible_session()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        res = resolve_reuse_surface("s1", reuse_runtime=rt)
        assert res.is_rejected()


# ---------------------------------------------------------------------------
# Group H — resolve_reuse_surface: session_id lookup priority
# ---------------------------------------------------------------------------


class TestGroupH_SessionLookupPriority:
    def test_H01_session_id_takes_priority_over_device_id(self):
        rt = _fresh_reuse_rt()
        # Establish binding for session s1/d1
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        # Establish binding for session s2/d2
        establish_reuse_binding(session_id="s2", device_id="d2", runtime=rt)
        # Lookup by s1 should return s1 binding even if d2 is provided
        res = resolve_reuse_surface("s1", "d2", reuse_runtime=rt)
        assert res.session_id == "s1"

    def test_H02_session_lookup_found_skips_device_fallback(self):
        rt = _fresh_reuse_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        # Even if device fallback would find something, session takes priority
        res = resolve_reuse_surface("s1", "d1", reuse_runtime=rt)
        assert res.is_reuse()
        assert res.device_id == "d1"


# ---------------------------------------------------------------------------
# Group I — resolve_reuse_surface: device_id fallback
# ---------------------------------------------------------------------------


class TestGroupI_DeviceFallback:
    def test_I01_device_fallback_used_when_session_not_found(self):
        rt = _fresh_reuse_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt)
        # Lookup by unknown session but known device
        res = resolve_reuse_surface("no-such-session", "d1", reuse_runtime=rt)
        # Device fallback should find s1
        assert res.is_reuse()
        assert res.device_id == "d1"

    def test_I02_no_session_no_device_returns_new_binding(self):
        rt = _fresh_reuse_rt()
        res = resolve_reuse_surface("", "", reuse_runtime=rt)
        assert res.is_new_binding()


# ---------------------------------------------------------------------------
# Group J — resolve_reuse_surface: attached_session forwarding
# ---------------------------------------------------------------------------


class TestGroupJ_AttachedSession:
    def test_J01_attached_session_attached_and_join_runtime_stays_reuse(self):
        _, rt = _eligible_session()
        res = resolve_reuse_surface("s1", attached_session=_AttachedSession(), reuse_runtime=rt)
        assert res.is_reuse()

    def test_J02_attached_session_detached_makes_ineligible(self):
        _, rt = _eligible_session()
        # Pass a session whose attachment_state is "detached"
        res = resolve_reuse_surface(
            "s1",
            attached_session=_AttachedSession(state="detached"),
            reuse_runtime=rt,
        )
        assert res.is_rejected()


# ---------------------------------------------------------------------------
# Groups K-N — resolve_reuse_surface: invalidation lifecycle signals
# ---------------------------------------------------------------------------


class TestGroupKN_InvalidationSignals:
    @pytest.mark.parametrize("signal", ["detach", "disconnect", "disable", "invalidate"])
    def test_invalidated_binding_rejected(self, signal):
        rec, rt = _eligible_session()
        invalidate_reuse_binding(rec, lifecycle_signal=signal, runtime=rt)
        res = resolve_reuse_surface("s1", reuse_runtime=rt)
        assert res.is_rejected(), f"signal={signal} should produce rejected"


# ---------------------------------------------------------------------------
# Group O — resolve_reuse_surface: identity field preservation
# ---------------------------------------------------------------------------


class TestGroupO_IdentityPreservation:
    def test_O01_session_id_preserved_from_binding(self):
        _, rt = _eligible_session("my-session", "my-device")
        res = resolve_reuse_surface("my-session", reuse_runtime=rt)
        assert res.session_id == "my-session"

    def test_O02_device_id_preserved_from_binding(self):
        _, rt = _eligible_session("my-session", "my-device")
        res = resolve_reuse_surface("my-session", reuse_runtime=rt)
        assert res.device_id == "my-device"

    def test_O03_reuse_binding_id_accessible(self):
        rec, rt = _eligible_session("my-session", "my-device")
        res = resolve_reuse_surface("my-session", reuse_runtime=rt)
        assert res.reuse_binding is not None
        assert res.reuse_binding.identity.reuse_binding_id == rec.identity.reuse_binding_id


# ---------------------------------------------------------------------------
# Group P — execute_reuse_dispatch: no binding → new_binding
# ---------------------------------------------------------------------------


class TestGroupP_ExecuteNoBinding:
    def test_P01_no_binding_decision_is_new_binding(self):
        rt = _fresh_reuse_rt()
        outcome = execute_reuse_dispatch("no-such-s", "no-such-d", reuse_runtime=rt)
        assert outcome.decision == DispatchReuseDecision.new_binding

    def test_P02_no_binding_dispatch_binding_is_none(self):
        rt = _fresh_reuse_rt()
        outcome = execute_reuse_dispatch("no-such-s", reuse_runtime=rt)
        assert outcome.dispatch_binding is None

    def test_P03_no_binding_updated_reuse_binding_is_none(self):
        rt = _fresh_reuse_rt()
        outcome = execute_reuse_dispatch("no-such-s", reuse_runtime=rt)
        assert outcome.updated_reuse_binding is None

    def test_P04_no_binding_was_reused_false(self):
        rt = _fresh_reuse_rt()
        outcome = execute_reuse_dispatch("no-such-s", reuse_runtime=rt)
        assert not outcome.was_reused


# ---------------------------------------------------------------------------
# Group Q — execute_reuse_dispatch: eligible binding → reuse
# ---------------------------------------------------------------------------


class TestGroupQ_ExecuteReuse:
    def test_Q01_eligible_decision_is_reuse(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.decision == DispatchReuseDecision.reuse

    def test_Q02_eligible_was_reused_true(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.was_reused

    def test_Q03_eligible_dispatch_binding_not_none(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.dispatch_binding is not None

    def test_Q04_eligible_reuse_binding_set(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.reuse_binding is not None

    def test_Q05_eligible_rejection_reason_empty(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.rejection_reason == ""


# ---------------------------------------------------------------------------
# Group R — execute_reuse_dispatch: ineligible binding → rejected
# ---------------------------------------------------------------------------


class TestGroupR_ExecuteRejected:
    def test_R01_ineligible_decision_is_rejected(self):
        rec, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.decision == DispatchReuseDecision.rejected

    def test_R02_ineligible_dispatch_binding_is_none(self):
        rec, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.dispatch_binding is None

    def test_R03_ineligible_updated_reuse_binding_is_none(self):
        rec, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.updated_reuse_binding is None

    def test_R04_ineligible_was_reused_false(self):
        rec, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert not outcome.was_reused


# ---------------------------------------------------------------------------
# Group S — execute_reuse_dispatch: dispatch binding uses identity from reuse
# ---------------------------------------------------------------------------


class TestGroupS_DispatchBindingIdentity:
    def test_S01_dispatch_binding_session_id_from_reuse(self):
        establish_reuse_binding(session_id="sess-xyz", device_id="dev-abc",
                                source_runtime_posture="join_runtime", runtime=(rt := _fresh_reuse_rt()))
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("sess-xyz", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.dispatch_binding.identity.session_id == "sess-xyz"

    def test_S02_dispatch_binding_device_id_from_reuse(self):
        establish_reuse_binding(session_id="sess-xyz", device_id="dev-abc",
                                source_runtime_posture="join_runtime", runtime=(rt := _fresh_reuse_rt()))
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("sess-xyz", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.dispatch_binding.identity.device_id == "dev-abc"

    def test_S03_dispatch_binding_posture_from_reuse(self):
        establish_reuse_binding(session_id="s1", device_id="d1",
                                source_runtime_posture="join_runtime", runtime=(rt := _fresh_reuse_rt()))
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.dispatch_binding.source_runtime_posture == "join_runtime"


# ---------------------------------------------------------------------------
# Group T-U — execute_reuse_dispatch: dispatch_binding_id write-back
# ---------------------------------------------------------------------------


class TestGroupTU_WriteBack:
    def test_T01_updated_reuse_binding_not_none_on_reuse(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.updated_reuse_binding is not None

    def test_T02_updated_reuse_binding_dispatch_binding_id_set(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.updated_reuse_binding.dispatch_binding_id != ""

    def test_U01_updated_dispatch_binding_id_matches_dispatch_binding(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert (
            outcome.updated_reuse_binding.dispatch_binding_id
            == outcome.dispatch_binding.identity.binding_id
        )

    def test_U02_latest_reuse_binding_in_ring_buffer_updated(self):
        _, rt = _eligible_session("s1", "d1")
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        # The ring-buffer entry should now carry the new dispatch_binding_id
        latest = get_reuse_binding("s1", runtime=rt)
        assert latest is not None
        assert latest.dispatch_binding_id == outcome.dispatch_binding.identity.binding_id


# ---------------------------------------------------------------------------
# Groups V-X — was_reused flag semantics
# ---------------------------------------------------------------------------


class TestGroupVX_WasReused:
    def test_V01_was_reused_true_only_on_reuse(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.was_reused

    def test_W01_was_reused_false_on_rejected(self):
        rec, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert not outcome.was_reused

    def test_X01_was_reused_false_on_new_binding(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("no-binding", reuse_runtime=rt, dispatch_runtime=drt)
        assert not outcome.was_reused


# ---------------------------------------------------------------------------
# Group Y — session_id / device_id in outcome
# ---------------------------------------------------------------------------


class TestGroupY_OutcomeIdentity:
    def test_Y01_session_id_in_outcome_on_reuse(self):
        _, rt = _eligible_session("sess-one", "dev-one")
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("sess-one", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.session_id == "sess-one"

    def test_Y02_device_id_in_outcome_on_reuse(self):
        _, rt = _eligible_session("sess-one", "dev-one")
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("sess-one", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.device_id == "dev-one"

    def test_Y03_session_id_in_outcome_on_rejected(self):
        rec, rt = _eligible_session("sess-two", "dev-two")
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        outcome = execute_reuse_dispatch("sess-two", reuse_runtime=rt)
        assert outcome.session_id == "sess-two"


# ---------------------------------------------------------------------------
# Group Z — contract_id / tracker_id forwarding
# ---------------------------------------------------------------------------


class TestGroupZ_ContractTracker:
    def test_Z01_contract_id_forwarded_to_dispatch_binding(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch(
            "s1", contract_id="contract-99", reuse_runtime=rt, dispatch_runtime=drt
        )
        assert outcome.dispatch_binding.identity.contract_id == "contract-99"

    def test_Z02_tracker_id_forwarded_to_dispatch_binding(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch(
            "s1", tracker_id="tracker-88", reuse_runtime=rt, dispatch_runtime=drt
        )
        assert outcome.dispatch_binding.identity.tracker_id == "tracker-88"


# ---------------------------------------------------------------------------
# Group AA — Integration: same session multi-dispatch reuse
# ---------------------------------------------------------------------------


class TestGroupAA_MultiDispatchReuse:
    def test_AA01_same_session_multiple_dispatches_all_reuse(self):
        _, rt = _eligible_session("multi-s", "multi-d")
        drt = _fresh_dispatch_rt()

        outcome1 = execute_reuse_dispatch("multi-s", reuse_runtime=rt, dispatch_runtime=drt)
        outcome2 = execute_reuse_dispatch("multi-s", reuse_runtime=rt, dispatch_runtime=drt)
        outcome3 = execute_reuse_dispatch("multi-s", reuse_runtime=rt, dispatch_runtime=drt)

        assert outcome1.was_reused
        assert outcome2.was_reused
        assert outcome3.was_reused

    def test_AA02_each_dispatch_creates_distinct_dispatch_binding(self):
        _, rt = _eligible_session("multi-s", "multi-d")
        drt = _fresh_dispatch_rt()

        outcome1 = execute_reuse_dispatch("multi-s", reuse_runtime=rt, dispatch_runtime=drt)
        outcome2 = execute_reuse_dispatch("multi-s", reuse_runtime=rt, dispatch_runtime=drt)

        assert (
            outcome1.dispatch_binding.identity.binding_id
            != outcome2.dispatch_binding.identity.binding_id
        )

    def test_AA03_latest_dispatch_binding_id_in_reuse_binding_after_multi_dispatch(self):
        _, rt = _eligible_session("multi-s", "multi-d")
        drt = _fresh_dispatch_rt()

        outcome1 = execute_reuse_dispatch("multi-s", reuse_runtime=rt, dispatch_runtime=drt)
        outcome2 = execute_reuse_dispatch("multi-s", reuse_runtime=rt, dispatch_runtime=drt)
        outcome3 = execute_reuse_dispatch("multi-s", reuse_runtime=rt, dispatch_runtime=drt)

        latest = get_reuse_binding("multi-s", runtime=rt)
        assert latest is not None
        # The latest dispatch_binding_id should be from outcome3
        assert latest.dispatch_binding_id == outcome3.dispatch_binding.identity.binding_id


# ---------------------------------------------------------------------------
# Group AB-AD — Integration: invalidated binding rejection
# ---------------------------------------------------------------------------


class TestGroupABACAD_InvalidatedRejection:
    def test_AB01_detach_then_dispatch_is_rejected(self):
        rec, rt = _eligible_session("s-detach", "d-detach")
        drt = _fresh_dispatch_rt()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        outcome = execute_reuse_dispatch("s-detach", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.decision == DispatchReuseDecision.rejected
        assert outcome.dispatch_binding is None

    def test_AC01_disconnect_then_dispatch_is_rejected(self):
        rec, rt = _eligible_session("s-disc", "d-disc")
        drt = _fresh_dispatch_rt()
        invalidate_reuse_binding(rec, lifecycle_signal="disconnect", runtime=rt)
        outcome = execute_reuse_dispatch("s-disc", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.decision == DispatchReuseDecision.rejected
        assert outcome.dispatch_binding is None

    def test_AD01_disable_then_dispatch_is_rejected(self):
        rec, rt = _eligible_session("s-dis", "d-dis")
        drt = _fresh_dispatch_rt()
        invalidate_reuse_binding(rec, lifecycle_signal="disable", runtime=rt)
        outcome = execute_reuse_dispatch("s-dis", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.decision == DispatchReuseDecision.rejected
        assert outcome.dispatch_binding is None


# ---------------------------------------------------------------------------
# Group AE — Integration: re-establish after reattach
# ---------------------------------------------------------------------------


class TestGroupAE_ReestablishAfterReattach:
    def test_AE01_invalidate_then_new_establish_then_reuse_succeeds(self):
        rec, rt = _eligible_session("s-reattach", "d-reattach")
        drt = _fresh_dispatch_rt()

        # First dispatch succeeds
        outcome1 = execute_reuse_dispatch("s-reattach", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome1.was_reused

        # Detach → binding invalidated
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        outcome_bad = execute_reuse_dispatch("s-reattach", reuse_runtime=rt, dispatch_runtime=drt)
        assert not outcome_bad.was_reused
        assert outcome_bad.decision == DispatchReuseDecision.rejected

        # Reattach: establish a new reuse binding for same session
        establish_reuse_binding(
            session_id="s-reattach", device_id="d-reattach",
            source_runtime_posture="join_runtime", runtime=rt
        )
        outcome_new = execute_reuse_dispatch("s-reattach", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome_new.was_reused
        assert outcome_new.decision == DispatchReuseDecision.reuse

    def test_AE02_after_reattach_dispatch_binding_id_is_written_back(self):
        rec, rt = _eligible_session("s-re2", "d-re2")
        drt = _fresh_dispatch_rt()
        invalidate_reuse_binding(rec, lifecycle_signal="detach", runtime=rt)
        # Re-establish
        establish_reuse_binding(
            session_id="s-re2", device_id="d-re2",
            source_runtime_posture="join_runtime", runtime=rt
        )
        outcome = execute_reuse_dispatch("s-re2", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.was_reused
        assert outcome.updated_reuse_binding.dispatch_binding_id != ""


# ---------------------------------------------------------------------------
# Group AF — dispatch binding state on reuse
# ---------------------------------------------------------------------------


class TestGroupAF_DispatchBindingState:
    def test_AF01_dispatch_binding_is_unbound_state_initially(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.dispatch_binding.binding_state == AndroidRuntimeBindingState.unbound


# ---------------------------------------------------------------------------
# Groups AG-AH — trace_id handling
# ---------------------------------------------------------------------------


class TestGroupAGAH_TraceId:
    def test_AG01_trace_id_auto_generated(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt)
        # Dispatch binding should carry a non-empty trace_id
        assert outcome.dispatch_binding.identity.trace_id

    def test_AH01_provided_trace_id_forwarded(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        tid = str(uuid.uuid4())
        outcome = execute_reuse_dispatch("s1", trace_id=tid, reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.dispatch_binding.identity.trace_id == tid


# ---------------------------------------------------------------------------
# Groups AI-AJ — coordination_role handling
# ---------------------------------------------------------------------------


class TestGroupAIAJ_CoordinationRole:
    def test_AI01_caller_coordination_role_used_when_binding_has_none(self):
        _, rt = _eligible_session()
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch(
            "s1", coordination_role="source_controller",
            reuse_runtime=rt, dispatch_runtime=drt
        )
        assert outcome.dispatch_binding.coordination_role == "source_controller"

    def test_AJ01_reuse_binding_coordination_role_takes_precedence(self):
        rt = _fresh_reuse_rt()
        establish_reuse_binding(
            session_id="s-role", device_id="d-role",
            source_runtime_posture="join_runtime",
            coordination_role="joined_runtime_participant",
            runtime=rt,
        )
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch(
            "s-role", coordination_role="source_controller",
            reuse_runtime=rt, dispatch_runtime=drt
        )
        assert outcome.dispatch_binding.coordination_role == "joined_runtime_participant"


# ---------------------------------------------------------------------------
# Group AK — core.runtime re-exports
# ---------------------------------------------------------------------------


class TestGroupAK_CoreRuntimeReexports:
    def test_AK01_dispatch_reuse_decision_accessible_from_core_runtime(self):
        from core.runtime import DispatchReuseDecision as _D
        assert _D.reuse == "reuse"

    def test_AK02_resolve_reuse_surface_accessible_from_core_runtime(self):
        from core.runtime import resolve_reuse_surface as _f
        assert callable(_f)

    def test_AK03_execute_reuse_dispatch_accessible_from_core_runtime(self):
        from core.runtime import execute_reuse_dispatch as _f
        assert callable(_f)

    def test_AK04_pr17_sentinel_accessible_from_core_runtime(self):
        from core.runtime import ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL as s
        assert "package=17" in s

    def test_AK05_reuse_surface_resolution_accessible_from_core_runtime(self):
        from core.runtime import ReuseSurfaceResolution as _R
        assert _R is not None

    def test_AK06_reuse_dispatch_outcome_accessible_from_core_runtime(self):
        from core.runtime import ReuseDispatchOutcome as _O
        assert _O is not None


# ---------------------------------------------------------------------------
# Group AL — projection.py sentinel
# ---------------------------------------------------------------------------


class TestGroupAL_ProjectionSentinel:
    def test_AL01_projection_sentinel_not_unavailable(self):
        from core.routes.projection import ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17 as s
        assert "UNAVAILABLE" not in s

    def test_AL02_projection_sentinel_non_empty(self):
        from core.routes.projection import ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17 as s
        assert s

    def test_AL03_projection_sentinel_contains_pr17(self):
        from core.routes.projection import ATTACHED_RUNTIME_REUSE_DISPATCH_ALIGNED_PR17 as s
        assert "PR17" in s


# ---------------------------------------------------------------------------
# Group AM — All 10 policy sentinels
# ---------------------------------------------------------------------------


class TestGroupAM_PolicySentinels:
    _sentinels = [
        REUSE_DISPATCH_LOOKUP_BEFORE_DISPATCH_POLICY,
        REUSE_DISPATCH_ELIGIBILITY_GATE_IS_UNCONDITIONAL_POLICY,
        REUSE_DISPATCH_ELIGIBLE_REUSES_SURFACE_POLICY,
        REUSE_DISPATCH_INELIGIBLE_DOES_NOT_DISPATCH_POLICY,
        REUSE_DISPATCH_WRITE_BACK_DISPATCH_BINDING_ID_POLICY,
        REUSE_DISPATCH_FALLBACK_ON_MISSING_BINDING_POLICY,
        REUSE_DISPATCH_INVALIDATED_BINDING_NOT_CONSUMED_POLICY,
        REUSE_DISPATCH_SESSION_LOOKUP_PRIORITY_POLICY,
        REUSE_DISPATCH_DISPATCH_BINDING_USES_REUSE_IDENTITY_POLICY,
        REUSE_DISPATCH_OUTCOME_IS_INSPECTABLE_POLICY,
    ]

    def test_AM01_all_10_sentinels_non_empty(self):
        for s in self._sentinels:
            assert s, f"Empty sentinel: {s!r}"

    def test_AM02_all_10_sentinels_are_strings(self):
        for s in self._sentinels:
            assert isinstance(s, str), f"Not a string: {s!r}"

    def test_AM03_exactly_10_sentinels(self):
        assert len(self._sentinels) == 10


# ---------------------------------------------------------------------------
# Group AN — PR17 sentinel structure
# ---------------------------------------------------------------------------


class TestGroupAN_PR17Sentinel:
    def test_AN01_contains_package_17(self):
        assert "package=17" in ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL

    def test_AN02_is_string(self):
        assert isinstance(ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL, str)

    def test_AN03_is_non_empty(self):
        assert ATTACHED_RUNTIME_REUSE_DISPATCH_PR17_SENTINEL


# ---------------------------------------------------------------------------
# Groups AO-AP — empty inputs
# ---------------------------------------------------------------------------


class TestGroupAOAP_EmptyInputs:
    def test_AO01_empty_session_and_device_returns_new_binding(self):
        rt = _fresh_reuse_rt()
        res = resolve_reuse_surface("", "", reuse_runtime=rt)
        assert res.is_new_binding()

    def test_AP01_execute_empty_inputs_returns_new_binding(self):
        rt = _fresh_reuse_rt()
        outcome = execute_reuse_dispatch("", "", reuse_runtime=rt)
        assert outcome.decision == DispatchReuseDecision.new_binding
        assert not outcome.was_reused


# ---------------------------------------------------------------------------
# Group AQ — ReuseSurfaceResolution predicates
# ---------------------------------------------------------------------------


class TestGroupAQ_ResolutionPredicates:
    def test_AQ01_is_reuse_false_on_rejected(self):
        r = ReuseSurfaceResolution(decision=DispatchReuseDecision.rejected)
        assert not r.is_reuse()

    def test_AQ02_is_rejected_false_on_new_binding(self):
        r = ReuseSurfaceResolution(decision=DispatchReuseDecision.new_binding)
        assert not r.is_rejected()

    def test_AQ03_is_new_binding_false_on_reuse(self):
        r = ReuseSurfaceResolution(decision=DispatchReuseDecision.reuse)
        assert not r.is_new_binding()


# ---------------------------------------------------------------------------
# Group AR — ReuseDispatchOutcome.to_dict()
# ---------------------------------------------------------------------------


class TestGroupAR_OutcomeToDict:
    def test_AR01_to_dict_has_all_expected_keys(self):
        o = ReuseDispatchOutcome()
        d = o.to_dict()
        expected_keys = {
            "decision", "was_reused", "session_id", "device_id",
            "reuse_binding_id", "dispatch_binding_id",
            "updated_dispatch_binding_id", "rejection_reason", "dispatched_at",
        }
        for k in expected_keys:
            assert k in d, f"missing key: {k}"

    def test_AR02_to_dict_dispatched_at_is_float(self):
        o = ReuseDispatchOutcome()
        assert isinstance(o.to_dict()["dispatched_at"], float)


# ---------------------------------------------------------------------------
# Group AS — Runtime isolation
# ---------------------------------------------------------------------------


class TestGroupAS_RuntimeIsolation:
    def test_AS01_separate_reuse_runtimes_do_not_share_bindings(self):
        rt1 = _fresh_reuse_rt()
        rt2 = _fresh_reuse_rt()
        establish_reuse_binding(session_id="s1", device_id="d1", runtime=rt1)
        # rt2 should not see the binding established in rt1
        res = resolve_reuse_surface("s1", reuse_runtime=rt2)
        assert res.is_new_binding()

    def test_AS02_separate_dispatch_runtimes_do_not_share_bindings(self):
        _, rt = _eligible_session()
        drt1 = _fresh_dispatch_rt()
        drt2 = _fresh_dispatch_rt()
        o1 = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt1)
        o2 = execute_reuse_dispatch("s1", reuse_runtime=rt, dispatch_runtime=drt2)
        # Both should succeed and produce distinct binding IDs
        assert o1.was_reused and o2.was_reused
        assert o1.dispatch_binding.identity.binding_id != o2.dispatch_binding.identity.binding_id


# ---------------------------------------------------------------------------
# Group AT — dispatch binding posture
# ---------------------------------------------------------------------------


class TestGroupAT_DispatchBindingPosture:
    def test_AT01_dispatch_binding_uses_join_runtime_posture(self):
        establish_reuse_binding(
            session_id="s-p", device_id="d-p",
            source_runtime_posture="join_runtime",
            runtime=(rt := _fresh_reuse_rt()),
        )
        drt = _fresh_dispatch_rt()
        outcome = execute_reuse_dispatch("s-p", reuse_runtime=rt, dispatch_runtime=drt)
        assert outcome.dispatch_binding.source_runtime_posture == "join_runtime"


# ---------------------------------------------------------------------------
# Group AU — Two separate sessions do not interfere
# ---------------------------------------------------------------------------


class TestGroupAU_SeparateSessions:
    def test_AU01_two_sessions_independent(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        establish_reuse_binding(session_id="sa", device_id="da", runtime=rt)
        establish_reuse_binding(session_id="sb", device_id="db", runtime=rt)

        oa = execute_reuse_dispatch("sa", reuse_runtime=rt, dispatch_runtime=drt)
        ob = execute_reuse_dispatch("sb", reuse_runtime=rt, dispatch_runtime=drt)

        assert oa.was_reused
        assert ob.was_reused
        assert oa.session_id == "sa"
        assert ob.session_id == "sb"
        assert oa.device_id == "da"
        assert ob.device_id == "db"

    def test_AU02_invalidating_session_a_does_not_affect_session_b(self):
        rt = _fresh_reuse_rt()
        drt = _fresh_dispatch_rt()
        rec_a = establish_reuse_binding(session_id="sa2", device_id="da2", runtime=rt)
        establish_reuse_binding(session_id="sb2", device_id="db2", runtime=rt)

        invalidate_reuse_binding(rec_a, lifecycle_signal="detach", runtime=rt)

        oa = execute_reuse_dispatch("sa2", reuse_runtime=rt, dispatch_runtime=drt)
        ob = execute_reuse_dispatch("sb2", reuse_runtime=rt, dispatch_runtime=drt)

        assert not oa.was_reused  # sa2 invalidated
        assert ob.was_reused      # sb2 still eligible
