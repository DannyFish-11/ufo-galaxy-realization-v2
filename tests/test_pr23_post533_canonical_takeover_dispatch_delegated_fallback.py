"""tests/test_pr23_post533_canonical_takeover_dispatch_delegated_fallback.py
============================================================================
Tests for PR package 23 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Attached-Runtime Takeover Dispatch and Delegated
Fallback Canonicalization.

This test suite verifies that:

1. All PR-23 policy/authority sentinels are present in each module.
2. ``resolve_takeover_or_fallback_route()`` consults the registry as the
   single first authority before making a takeover vs fallback decision.
3. An active attached-runtime session with an eligible reuse binding produces
   ``TakeoverRouteOutcome.active_attached_takeover``.
4. Invalidated, detached, and replaced sessions produce
   ``TakeoverRouteOutcome.delegated_fallback``.
5. A session absent from the registry defers to the reuse-binding layer; if
   no reuse binding exists the result is ``delegated_fallback``.
6. Stale / replayed execution contexts do not produce inconsistent route
   selection — the registry gate (PR-22) and recovery guard ensure
   deterministic outcomes.
7. The projection sentinel is importable and is not UNAVAILABLE.
8. ``core.runtime`` re-exports all PR-23 symbols.

Coverage groups
---------------
A  — Reuse-dispatch module: PR-23 sentinel and policy sentinels present.
B  — Session-registry module: PR-23 sentinel and policy sentinels present.
C  — Ingress module: PR-23 sentinel and policy sentinels present.
D  — Reconciler module: PR-23 sentinel and policy sentinels present.
E  — Projection PR-23 sentinel present (not UNAVAILABLE).
F  — TakeoverRouteOutcome enum has correct values.
G  — TakeoverDispatchDecision dataclass: helpers work correctly.
H  — Active session + eligible reuse binding → active_attached_takeover.
I  — Replaced session → delegated_fallback (registry gate blocks).
J  — Detached session → delegated_fallback (registry gate blocks).
K  — Invalidated session → delegated_fallback (registry gate blocks).
L  — Absent registry entry, no reuse binding → delegated_fallback.
M  — Absent registry entry with eligible reuse binding → active_attached_takeover.
N  — Decision is deterministic: same inputs always produce same outcome.
O  — Stale execution context (replaced session) cannot win takeover.
P  — Superseded session is blocked across takeover routing.
Q  — core.runtime re-exports all PR-23 symbols.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.attached_runtime_reuse_dispatch import (
        ReuseDispatchResolutionKind,
        ReuseDispatchResolution,
        resolve_reuse_dispatch_surface,
        REUSE_DISPATCH_PR23_SENTINEL,
        TAKEOVER_DISPATCH_CONSULTS_REGISTRY_FIRST_PR23_POLICY,
        DELEGATED_FALLBACK_REQUIRES_INELIGIBLE_CANONICAL_PATH_PR23_POLICY,
        TAKEOVER_DISPATCH_DECISION_IS_DETERMINISTIC_PR23_POLICY,
        REPLACED_SESSION_CANNOT_WIN_TAKEOVER_DISPATCH_PR23_POLICY,
        STALE_EXECUTION_CONTEXT_CANNOT_ALTER_TAKEOVER_DECISION_PR23_POLICY,
        TakeoverRouteOutcome,
        TakeoverDispatchDecision,
        resolve_takeover_or_fallback_route,
    )

    _REUSE_DISPATCH_AVAILABLE = True
except ImportError:
    _REUSE_DISPATCH_AVAILABLE = False

try:
    from core.attached_runtime_session_registry import (
        AttachedSessionRegistry,
        RegistryEntryState,
        InvalidationReason,
        register_session,
        detach_session,
        invalidate_session,
        lookup_active_session,
        ATTACHED_RUNTIME_REGISTRY_TAKEOVER_DISPATCH_PR23_SENTINEL,
        REGISTRY_IS_CANONICAL_TAKEOVER_DISPATCH_AUTHORITY_PR23_POLICY,
        REGISTRY_TAKEOVER_ELIGIBILITY_REQUIRES_ACTIVE_STATE_PR23_POLICY,
        REGISTRY_REPLACED_SESSION_IS_INELIGIBLE_FOR_TAKEOVER_PR23_POLICY,
    )

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

try:
    from core.android_delegated_signal_ingress import (
        INGRESS_DELEGATED_FALLBACK_PR23_SENTINEL,
        INGRESS_FALLBACK_IS_LAST_RESORT_PR23_POLICY,
        INGRESS_STALE_CONTEXT_DOES_NOT_ALTER_FALLBACK_SELECTION_PR23_POLICY,
    )

    _INGRESS_AVAILABLE = True
except ImportError:
    _INGRESS_AVAILABLE = False

try:
    from core.android_execution_signal_reconciler import (
        RECONCILER_PR23_SENTINEL,
        RECONCILER_FALLBACK_CONTEXT_IS_DETERMINISTIC_PR23_POLICY,
        RECONCILER_STALE_SESSION_IS_BLOCKED_BEFORE_TRACKER_MUTATION_PR23_POLICY,
    )

    _RECONCILER_AVAILABLE = True
except ImportError:
    _RECONCILER_AVAILABLE = False

try:
    from core.attached_runtime_reuse_binding import (
        establish_reuse_binding,
        AttachedRuntimeReuseBindingRuntime,
    )

    _REUSE_BINDING_AVAILABLE = True
except ImportError:
    _REUSE_BINDING_AVAILABLE = False

# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------

_SKIP_REUSE = pytest.mark.skipif(
    not _REUSE_DISPATCH_AVAILABLE, reason="attached_runtime_reuse_dispatch unavailable"
)
_SKIP_REGISTRY = pytest.mark.skipif(
    not _REGISTRY_AVAILABLE, reason="attached_runtime_session_registry unavailable"
)
_SKIP_INGRESS = pytest.mark.skipif(
    not _INGRESS_AVAILABLE, reason="android_delegated_signal_ingress unavailable"
)
_SKIP_RECONCILER = pytest.mark.skipif(
    not _RECONCILER_AVAILABLE, reason="android_execution_signal_reconciler unavailable"
)
_SKIP_ALL = pytest.mark.skipif(
    not (
        _REUSE_DISPATCH_AVAILABLE
        and _REGISTRY_AVAILABLE
        and _REUSE_BINDING_AVAILABLE
    ),
    reason="one or more PR-23 core modules unavailable",
)
_SKIP_RUNTIME = pytest.mark.skipif(
    not (
        _REUSE_DISPATCH_AVAILABLE and _REGISTRY_AVAILABLE
    ),
    reason="core.runtime re-export test requires reuse_dispatch and registry",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_registry(
    *,
    session_id: str = "sess-pr23",
    device_id: str = "dev-pr23",
    state: "RegistryEntryState" = None,
) -> "AttachedSessionRegistry":
    """Create an isolated registry with one entry in *state*."""
    reg = AttachedSessionRegistry()
    entry = register_session(
        session_id=session_id,
        device_id=device_id,
        registry=reg,
    )

    if state == RegistryEntryState.replaced:
        # Register a new session for the same device — replaces the old one.
        register_session(
            session_id=session_id + "-new",
            device_id=device_id,
            registry=reg,
        )
    elif state == RegistryEntryState.detached:
        detach_session(entry, registry=reg)
    elif state == RegistryEntryState.invalidated:
        invalidate_session(
            entry,
            InvalidationReason.invalidated,
            registry=reg,
        )
    # active — no further transition needed
    return reg


def _make_reuse_binding(session_id: str, device_id: str):
    """Create an eligible reuse binding for (session_id, device_id)."""
    rt = AttachedRuntimeReuseBindingRuntime()
    establish_reuse_binding(
        session_id=session_id,
        device_id=device_id,
        trace_id="trace-pr23",
        runtime=rt,
    )
    return rt


# ===========================================================================
# Group A — Reuse-dispatch module: PR-23 sentinels present
# ===========================================================================


class TestGroupA_ReuseDispatchSentinels:
    @_SKIP_REUSE
    def test_pr23_sentinel_present(self):
        assert "package=23" in REUSE_DISPATCH_PR23_SENTINEL

    @_SKIP_REUSE
    def test_consults_registry_first_policy_present(self):
        assert "CONSULTS_REGISTRY_FIRST" in TAKEOVER_DISPATCH_CONSULTS_REGISTRY_FIRST_PR23_POLICY

    @_SKIP_REUSE
    def test_fallback_requires_ineligible_path_policy_present(self):
        assert "DELEGATED_FALLBACK" in DELEGATED_FALLBACK_REQUIRES_INELIGIBLE_CANONICAL_PATH_PR23_POLICY

    @_SKIP_REUSE
    def test_decision_is_deterministic_policy_present(self):
        assert "DETERMINISTIC" in TAKEOVER_DISPATCH_DECISION_IS_DETERMINISTIC_PR23_POLICY

    @_SKIP_REUSE
    def test_replaced_session_cannot_win_policy_present(self):
        assert "REPLACED" in REPLACED_SESSION_CANNOT_WIN_TAKEOVER_DISPATCH_PR23_POLICY

    @_SKIP_REUSE
    def test_stale_context_policy_present(self):
        assert "STALE" in STALE_EXECUTION_CONTEXT_CANNOT_ALTER_TAKEOVER_DECISION_PR23_POLICY


# ===========================================================================
# Group B — Session-registry module: PR-23 sentinels present
# ===========================================================================


class TestGroupB_RegistrySentinels:
    @_SKIP_REGISTRY
    def test_takeover_dispatch_sentinel_present(self):
        assert "package=23" in ATTACHED_RUNTIME_REGISTRY_TAKEOVER_DISPATCH_PR23_SENTINEL

    @_SKIP_REGISTRY
    def test_canonical_takeover_authority_policy_present(self):
        assert "CANONICAL_TAKEOVER_DISPATCH_AUTHORITY" in REGISTRY_IS_CANONICAL_TAKEOVER_DISPATCH_AUTHORITY_PR23_POLICY

    @_SKIP_REGISTRY
    def test_takeover_eligibility_requires_active_state_policy_present(self):
        assert "ACTIVE_STATE" in REGISTRY_TAKEOVER_ELIGIBILITY_REQUIRES_ACTIVE_STATE_PR23_POLICY

    @_SKIP_REGISTRY
    def test_replaced_session_ineligible_policy_present(self):
        assert "INELIGIBLE_FOR_TAKEOVER" in REGISTRY_REPLACED_SESSION_IS_INELIGIBLE_FOR_TAKEOVER_PR23_POLICY


# ===========================================================================
# Group C — Ingress module: PR-23 sentinels present
# ===========================================================================


class TestGroupC_IngressSentinels:
    @_SKIP_INGRESS
    def test_fallback_sentinel_present(self):
        assert "package=23" in INGRESS_DELEGATED_FALLBACK_PR23_SENTINEL

    @_SKIP_INGRESS
    def test_fallback_is_last_resort_policy_present(self):
        assert "LAST_RESORT" in INGRESS_FALLBACK_IS_LAST_RESORT_PR23_POLICY

    @_SKIP_INGRESS
    def test_stale_context_does_not_alter_selection_policy_present(self):
        assert "STALE" in INGRESS_STALE_CONTEXT_DOES_NOT_ALTER_FALLBACK_SELECTION_PR23_POLICY


# ===========================================================================
# Group D — Reconciler module: PR-23 sentinels present
# ===========================================================================


class TestGroupD_ReconcilerSentinels:
    @_SKIP_RECONCILER
    def test_pr23_sentinel_present(self):
        assert "package=23" in RECONCILER_PR23_SENTINEL

    @_SKIP_RECONCILER
    def test_fallback_context_deterministic_policy_present(self):
        assert "DETERMINISTIC" in RECONCILER_FALLBACK_CONTEXT_IS_DETERMINISTIC_PR23_POLICY

    @_SKIP_RECONCILER
    def test_stale_session_blocked_policy_present(self):
        assert "STALE_SESSION" in RECONCILER_STALE_SESSION_IS_BLOCKED_BEFORE_TRACKER_MUTATION_PR23_POLICY


# ===========================================================================
# Group E — Projection sentinel present and not UNAVAILABLE
# ===========================================================================


class TestGroupE_ProjectionSentinel:
    def test_projection_sentinel_importable(self):
        try:
            from core.routes.projection import (  # noqa: F401
                CANONICAL_TAKEOVER_DISPATCH_DELEGATED_FALLBACK_ALIGNED_PR23,
            )
        except ImportError:
            pytest.skip("fastapi/projection unavailable")

    def test_projection_sentinel_not_unavailable(self):
        try:
            from core.routes.projection import (
                CANONICAL_TAKEOVER_DISPATCH_DELEGATED_FALLBACK_ALIGNED_PR23,
            )
        except ImportError:
            pytest.skip("fastapi/projection unavailable")
        assert "UNAVAILABLE" not in CANONICAL_TAKEOVER_DISPATCH_DELEGATED_FALLBACK_ALIGNED_PR23

    def test_projection_sentinel_contains_pr23(self):
        try:
            from core.routes.projection import (
                CANONICAL_TAKEOVER_DISPATCH_DELEGATED_FALLBACK_ALIGNED_PR23,
            )
        except ImportError:
            pytest.skip("fastapi/projection unavailable")
        assert "PR23" in CANONICAL_TAKEOVER_DISPATCH_DELEGATED_FALLBACK_ALIGNED_PR23 or "PR-23" in CANONICAL_TAKEOVER_DISPATCH_DELEGATED_FALLBACK_ALIGNED_PR23


# ===========================================================================
# Group F — TakeoverRouteOutcome enum
# ===========================================================================


class TestGroupF_TakeoverRouteOutcomeEnum:
    @_SKIP_REUSE
    def test_active_attached_takeover_value(self):
        assert TakeoverRouteOutcome.active_attached_takeover.value == "active_attached_takeover"

    @_SKIP_REUSE
    def test_delegated_fallback_value(self):
        assert TakeoverRouteOutcome.delegated_fallback.value == "delegated_fallback"

    @_SKIP_REUSE
    def test_from_string_known_value(self):
        assert TakeoverRouteOutcome.from_string("active_attached_takeover") == TakeoverRouteOutcome.active_attached_takeover

    @_SKIP_REUSE
    def test_from_string_fallback_default(self):
        assert TakeoverRouteOutcome.from_string("unknown_value") == TakeoverRouteOutcome.delegated_fallback

    @_SKIP_REUSE
    def test_is_takeover_helper(self):
        assert TakeoverRouteOutcome.active_attached_takeover.is_takeover()
        assert not TakeoverRouteOutcome.delegated_fallback.is_takeover()

    @_SKIP_REUSE
    def test_is_fallback_helper(self):
        assert TakeoverRouteOutcome.delegated_fallback.is_fallback()
        assert not TakeoverRouteOutcome.active_attached_takeover.is_fallback()


# ===========================================================================
# Group G — TakeoverDispatchDecision dataclass helpers
# ===========================================================================


class TestGroupG_TakeoverDispatchDecisionHelpers:
    @_SKIP_REUSE
    def test_is_takeover_on_takeover_decision(self):
        d = TakeoverDispatchDecision(
            outcome=TakeoverRouteOutcome.active_attached_takeover,
            session_id="s1",
            device_id="d1",
        )
        assert d.is_takeover()
        assert not d.is_fallback()

    @_SKIP_REUSE
    def test_is_fallback_on_fallback_decision(self):
        d = TakeoverDispatchDecision(
            outcome=TakeoverRouteOutcome.delegated_fallback,
            session_id="s1",
            device_id="d1",
            reject_reason="no binding",
        )
        assert d.is_fallback()
        assert not d.is_takeover()

    @_SKIP_REUSE
    def test_to_dict_contains_expected_keys(self):
        d = TakeoverDispatchDecision(
            outcome=TakeoverRouteOutcome.delegated_fallback,
            session_id="s2",
            device_id="d2",
            reject_reason="test",
        )
        dct = d.to_dict()
        assert dct["outcome"] == "delegated_fallback"
        assert dct["session_id"] == "s2"
        assert dct["device_id"] == "d2"
        assert "reject_reason" in dct
        assert "decided_at" in dct
        assert "decision_id" in dct

    @_SKIP_REUSE
    def test_decision_id_is_uuid_string(self):
        d = TakeoverDispatchDecision(
            outcome=TakeoverRouteOutcome.active_attached_takeover,
            session_id="s3",
            device_id="d3",
        )
        import uuid
        uuid.UUID(d.decision_id)  # should not raise


# ===========================================================================
# Group H — Active session + eligible reuse binding → active_attached_takeover
# ===========================================================================


class TestGroupH_ActiveSessionTakeover:
    @_SKIP_ALL
    def test_active_session_with_eligible_reuse_binding_wins_takeover(self):
        reg = _make_registry(session_id="sess-h", device_id="dev-h", state=RegistryEntryState.active)
        rt = _make_reuse_binding("sess-h", "dev-h")

        decision = resolve_takeover_or_fallback_route(
            "sess-h",
            "dev-h",
            reuse_runtime=rt,
            registry=reg,
        )

        assert decision.is_takeover(), (
            f"Expected active_attached_takeover but got {decision.outcome!r}: "
            f"{decision.reject_reason!r}"
        )
        assert decision.reject_reason == ""
        assert decision.reuse_resolution is not None
        assert decision.reuse_resolution.resolution_kind == ReuseDispatchResolutionKind.reused

    @_SKIP_ALL
    def test_active_session_takeover_outcome_value(self):
        reg = _make_registry(session_id="sess-h2", device_id="dev-h2")
        rt = _make_reuse_binding("sess-h2", "dev-h2")

        decision = resolve_takeover_or_fallback_route(
            "sess-h2", "dev-h2", reuse_runtime=rt, registry=reg
        )
        assert decision.outcome == TakeoverRouteOutcome.active_attached_takeover

    @_SKIP_ALL
    def test_active_session_takeover_populates_reuse_resolution(self):
        reg = _make_registry(session_id="sess-h3", device_id="dev-h3")
        rt = _make_reuse_binding("sess-h3", "dev-h3")

        decision = resolve_takeover_or_fallback_route(
            "sess-h3", "dev-h3", reuse_runtime=rt, registry=reg
        )
        assert decision.reuse_resolution is not None
        assert decision.reuse_resolution.session_id == "sess-h3"


# ===========================================================================
# Group I — Replaced session → delegated_fallback
# ===========================================================================


class TestGroupI_ReplacedSessionFallback:
    @_SKIP_ALL
    def test_replaced_session_produces_delegated_fallback(self):
        reg = _make_registry(
            session_id="sess-i", device_id="dev-i", state=RegistryEntryState.replaced
        )
        # Give the replaced session an eligible reuse binding — it should still lose.
        rt = _make_reuse_binding("sess-i", "dev-i")

        decision = resolve_takeover_or_fallback_route(
            "sess-i", "dev-i", reuse_runtime=rt, registry=reg
        )

        assert decision.is_fallback(), (
            f"Replaced session MUST NOT win takeover; got {decision.outcome!r}"
        )

    @_SKIP_ALL
    def test_replaced_session_reject_reason_mentions_registry(self):
        reg = _make_registry(
            session_id="sess-i2", device_id="dev-i2", state=RegistryEntryState.replaced
        )
        decision = resolve_takeover_or_fallback_route(
            "sess-i2", "dev-i2", registry=reg
        )
        assert "registry gate" in decision.reject_reason or "non-active" in decision.reject_reason

    @_SKIP_ALL
    def test_replaced_session_reuse_resolution_is_none(self):
        """When the registry gate blocks, we return early before reuse resolution."""
        reg = _make_registry(
            session_id="sess-i3", device_id="dev-i3", state=RegistryEntryState.replaced
        )
        decision = resolve_takeover_or_fallback_route(
            "sess-i3", "dev-i3", registry=reg
        )
        # The registry gate fires before reuse resolution; reuse_resolution is None.
        assert decision.reuse_resolution is None


# ===========================================================================
# Group J — Detached session → delegated_fallback
# ===========================================================================


class TestGroupJ_DetachedSessionFallback:
    @_SKIP_ALL
    def test_detached_session_produces_delegated_fallback(self):
        reg = _make_registry(
            session_id="sess-j", device_id="dev-j", state=RegistryEntryState.detached
        )
        rt = _make_reuse_binding("sess-j", "dev-j")

        decision = resolve_takeover_or_fallback_route(
            "sess-j", "dev-j", reuse_runtime=rt, registry=reg
        )
        assert decision.is_fallback()

    @_SKIP_ALL
    def test_detached_session_reject_reason_is_set(self):
        reg = _make_registry(
            session_id="sess-j2", device_id="dev-j2", state=RegistryEntryState.detached
        )
        decision = resolve_takeover_or_fallback_route(
            "sess-j2", "dev-j2", registry=reg
        )
        assert decision.reject_reason != ""


# ===========================================================================
# Group K — Invalidated session → delegated_fallback
# ===========================================================================


class TestGroupK_InvalidatedSessionFallback:
    @_SKIP_ALL
    def test_invalidated_session_produces_delegated_fallback(self):
        reg = _make_registry(
            session_id="sess-k", device_id="dev-k", state=RegistryEntryState.invalidated
        )
        rt = _make_reuse_binding("sess-k", "dev-k")

        decision = resolve_takeover_or_fallback_route(
            "sess-k", "dev-k", reuse_runtime=rt, registry=reg
        )
        assert decision.is_fallback()

    @_SKIP_ALL
    def test_invalidated_session_reuse_resolution_is_none(self):
        reg = _make_registry(
            session_id="sess-k2", device_id="dev-k2", state=RegistryEntryState.invalidated
        )
        decision = resolve_takeover_or_fallback_route(
            "sess-k2", "dev-k2", registry=reg
        )
        assert decision.reuse_resolution is None


# ===========================================================================
# Group L — Absent registry entry, no reuse binding → delegated_fallback
# ===========================================================================


class TestGroupL_AbsentRegistryNoBinding:
    @_SKIP_ALL
    def test_absent_registry_no_reuse_binding_produces_fallback(self):
        # Empty registry (no entry for this session).
        reg = AttachedSessionRegistry()
        rt = AttachedRuntimeReuseBindingRuntime()  # empty — no binding

        decision = resolve_takeover_or_fallback_route(
            "sess-l-unknown", "dev-l-unknown", reuse_runtime=rt, registry=reg
        )
        assert decision.is_fallback()

    @_SKIP_ALL
    def test_absent_registry_no_reuse_binding_sets_reject_reason(self):
        reg = AttachedSessionRegistry()
        rt = AttachedRuntimeReuseBindingRuntime()

        decision = resolve_takeover_or_fallback_route(
            "sess-l2", "dev-l2", reuse_runtime=rt, registry=reg
        )
        assert decision.reject_reason != ""

    @_SKIP_ALL
    def test_absent_registry_no_reuse_resolution_kind_is_no_binding(self):
        reg = AttachedSessionRegistry()
        rt = AttachedRuntimeReuseBindingRuntime()

        decision = resolve_takeover_or_fallback_route(
            "sess-l3", "dev-l3", reuse_runtime=rt, registry=reg
        )
        assert decision.reuse_resolution is not None
        assert decision.reuse_resolution.resolution_kind == ReuseDispatchResolutionKind.no_binding


# ===========================================================================
# Group M — Absent registry entry with eligible reuse binding → takeover
# ===========================================================================


class TestGroupM_AbsentRegistryWithEligibleBinding:
    @_SKIP_ALL
    def test_absent_registry_with_eligible_reuse_produces_takeover(self):
        """
        When the registry has no entry (cannot assert non-active) and a valid
        eligible reuse binding exists, the takeover path wins.
        Per REGISTRY_ABSENT_ENTRY_PASSES_THROUGH_PR22_POLICY the absent entry
        is not a block; the downstream reuse-binding layer determines the outcome.
        """
        reg = AttachedSessionRegistry()  # no entry for this session
        rt = _make_reuse_binding("sess-m", "dev-m")

        decision = resolve_takeover_or_fallback_route(
            "sess-m", "dev-m", reuse_runtime=rt, registry=reg
        )
        assert decision.is_takeover(), (
            f"Absent registry entry with eligible binding should produce takeover; "
            f"got {decision.outcome!r}: {decision.reject_reason!r}"
        )

    @_SKIP_ALL
    def test_absent_registry_with_eligible_reuse_no_reject_reason(self):
        reg = AttachedSessionRegistry()
        rt = _make_reuse_binding("sess-m2", "dev-m2")

        decision = resolve_takeover_or_fallback_route(
            "sess-m2", "dev-m2", reuse_runtime=rt, registry=reg
        )
        assert decision.reject_reason == ""


# ===========================================================================
# Group N — Decision is deterministic: same inputs → same outcome
# ===========================================================================


class TestGroupN_DeterministicDecision:
    @_SKIP_ALL
    def test_active_session_always_produces_takeover(self):
        """Multiple calls with the same active-session state produce the same outcome."""
        reg = _make_registry(session_id="sess-n", device_id="dev-n", state=RegistryEntryState.active)
        rt = _make_reuse_binding("sess-n", "dev-n")

        outcomes = [
            resolve_takeover_or_fallback_route(
                "sess-n", "dev-n", reuse_runtime=rt, registry=reg
            ).outcome
            for _ in range(5)
        ]
        assert all(o == TakeoverRouteOutcome.active_attached_takeover for o in outcomes)

    @_SKIP_ALL
    def test_replaced_session_always_produces_fallback(self):
        reg = _make_registry(
            session_id="sess-n2", device_id="dev-n2", state=RegistryEntryState.replaced
        )
        rt = _make_reuse_binding("sess-n2", "dev-n2")

        outcomes = [
            resolve_takeover_or_fallback_route(
                "sess-n2", "dev-n2", reuse_runtime=rt, registry=reg
            ).outcome
            for _ in range(5)
        ]
        assert all(o == TakeoverRouteOutcome.delegated_fallback for o in outcomes)

    @_SKIP_ALL
    def test_no_binding_always_produces_fallback(self):
        reg = AttachedSessionRegistry()
        rt = AttachedRuntimeReuseBindingRuntime()

        outcomes = [
            resolve_takeover_or_fallback_route(
                "sess-n3", "dev-n3", reuse_runtime=rt, registry=reg
            ).outcome
            for _ in range(5)
        ]
        assert all(o == TakeoverRouteOutcome.delegated_fallback for o in outcomes)


# ===========================================================================
# Group O — Stale execution context (replaced session) cannot win takeover
# ===========================================================================


class TestGroupO_StaleContextCannotWinTakeover:
    @_SKIP_ALL
    def test_stale_session_with_old_reuse_binding_blocked_by_registry(self):
        """
        A replaced session that still has an (eligible) reuse binding in the
        ring buffer MUST be blocked by the registry gate before the reuse
        binding is evaluated.
        """
        reg = AttachedSessionRegistry()
        rt = _make_reuse_binding("sess-o", "dev-o")

        # Register and then immediately replace by a new session.
        register_session(session_id="sess-o", device_id="dev-o", registry=reg)
        register_session(session_id="sess-o-new", device_id="dev-o", registry=reg)

        # The old session should now be replaced in the registry.
        old_entry = lookup_active_session("sess-o", active_only=False, registry=reg)
        assert old_entry is not None
        assert old_entry.attachment_state == RegistryEntryState.replaced

        # Despite having an eligible reuse binding, the old session MUST fail.
        decision = resolve_takeover_or_fallback_route(
            "sess-o", "dev-o", reuse_runtime=rt, registry=reg
        )
        assert decision.is_fallback(), (
            "Replaced session with stale reuse binding MUST NOT win takeover"
        )
        assert decision.reuse_resolution is None  # gate fired before reuse lookup

    @_SKIP_ALL
    def test_new_session_can_still_win_after_replacement(self):
        """
        After a session is replaced, the new session for the same device
        should be able to win takeover if it has an eligible reuse binding.
        """
        reg = AttachedSessionRegistry()
        rt = _make_reuse_binding("sess-o-new2", "dev-o2")

        register_session(session_id="sess-o-old2", device_id="dev-o2", registry=reg)
        register_session(session_id="sess-o-new2", device_id="dev-o2", registry=reg)

        # New session is active; it should win.
        decision = resolve_takeover_or_fallback_route(
            "sess-o-new2", "dev-o2", reuse_runtime=rt, registry=reg
        )
        assert decision.is_takeover(), (
            f"New (active) session should win takeover; got {decision.outcome!r}"
        )


# ===========================================================================
# Group P — Superseded session is blocked across takeover routing
# ===========================================================================


class TestGroupP_SupersededSessionBlocked:
    @_SKIP_ALL
    def test_superseded_session_delegated_fallback_regardless_of_reuse(self):
        """Consistency test: replaced session → fallback in all call variants."""
        reg = _make_registry(
            session_id="sess-p", device_id="dev-p", state=RegistryEntryState.replaced
        )
        rt = _make_reuse_binding("sess-p", "dev-p")

        # With reuse binding provided
        d1 = resolve_takeover_or_fallback_route("sess-p", "dev-p", reuse_runtime=rt, registry=reg)
        # Without reuse binding
        d2 = resolve_takeover_or_fallback_route("sess-p", "dev-p", registry=reg)
        # With empty device_id
        d3 = resolve_takeover_or_fallback_route("sess-p", "", registry=reg)

        assert d1.is_fallback()
        assert d2.is_fallback()
        assert d3.is_fallback()

    @_SKIP_ALL
    def test_invalidated_session_delegated_fallback_regardless_of_reuse(self):
        reg = _make_registry(
            session_id="sess-p2", device_id="dev-p2", state=RegistryEntryState.invalidated
        )
        rt = _make_reuse_binding("sess-p2", "dev-p2")

        d = resolve_takeover_or_fallback_route("sess-p2", "dev-p2", reuse_runtime=rt, registry=reg)
        assert d.is_fallback()

    @_SKIP_ALL
    def test_detached_session_delegated_fallback_regardless_of_reuse(self):
        reg = _make_registry(
            session_id="sess-p3", device_id="dev-p3", state=RegistryEntryState.detached
        )
        rt = _make_reuse_binding("sess-p3", "dev-p3")

        d = resolve_takeover_or_fallback_route("sess-p3", "dev-p3", reuse_runtime=rt, registry=reg)
        assert d.is_fallback()


# ===========================================================================
# Group Q — core.runtime re-exports all PR-23 symbols
# ===========================================================================


class TestGroupQ_CoreRuntimeReexports:
    @_SKIP_RUNTIME
    def test_runtime_reexports_pr23_reuse_dispatch_sentinel(self):
        try:
            from core.runtime import REUSE_DISPATCH_PR23_SENTINEL as s
        except ImportError:
            pytest.skip("core.runtime unavailable")
        assert "package=23" in s

    @_SKIP_RUNTIME
    def test_runtime_reexports_takeover_route_outcome(self):
        try:
            from core.runtime import TakeoverRouteOutcome as T
        except ImportError:
            pytest.skip("core.runtime unavailable")
        assert T.active_attached_takeover.value == "active_attached_takeover"

    @_SKIP_RUNTIME
    def test_runtime_reexports_takeover_dispatch_decision(self):
        try:
            from core.runtime import TakeoverDispatchDecision
        except ImportError:
            pytest.skip("core.runtime unavailable")
        d = TakeoverDispatchDecision(
            outcome=TakeoverRouteOutcome.delegated_fallback,
            session_id="s",
            device_id="d",
        )
        assert d.is_fallback()

    @_SKIP_RUNTIME
    def test_runtime_reexports_resolve_takeover_or_fallback_route(self):
        try:
            from core.runtime import resolve_takeover_or_fallback_route as fn
        except ImportError:
            pytest.skip("core.runtime unavailable")
        assert callable(fn)

    @_SKIP_RUNTIME
    def test_runtime_reexports_registry_pr23_sentinels(self):
        try:
            from core.runtime import (
                ATTACHED_RUNTIME_REGISTRY_TAKEOVER_DISPATCH_PR23_SENTINEL,
                REGISTRY_IS_CANONICAL_TAKEOVER_DISPATCH_AUTHORITY_PR23_POLICY,
            )
        except ImportError:
            pytest.skip("core.runtime unavailable")
        assert "package=23" in ATTACHED_RUNTIME_REGISTRY_TAKEOVER_DISPATCH_PR23_SENTINEL
        assert "CANONICAL_TAKEOVER" in REGISTRY_IS_CANONICAL_TAKEOVER_DISPATCH_AUTHORITY_PR23_POLICY
