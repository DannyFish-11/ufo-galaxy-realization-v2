"""tests/test_pr22_post533_authoritative_attached_runtime_registry_consolidation.py
===================================================================================
Tests for PR package 22 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Authoritative Attached Runtime Registry Consolidation.

This test suite verifies that the attached runtime session registry (PR-19) is
now the single authoritative gate for dispatch, reuse, and delegated-signal
reconciliation decisions:

1. PR-22 consolidation sentinels are present in all four affected modules and
   are re-exported from ``core.runtime``.
2. ``resolve_reuse_dispatch_surface()`` and ``dispatch_with_reuse_binding()``
   reject requests for sessions that are in a non-active registry state
   (replaced / detached / invalidated).
3. ``reconcile_android_execution_signal()`` blocks signals for sessions that
   are in a non-active registry state.
4. ``ingest_delegated_execution_signal()`` blocks signals for sessions that
   are in a non-active registry state.
5. Active-session requests flow through all three paths without registry-based
   rejection.
6. Unregistered sessions (no registry entry) are allowed through (backward
   compatibility — the gate only blocks KNOWN non-active sessions).
7. Replaced / superseded session semantics are stable and consistent.
8. Side-channel session truth (residual reuse binding, live execution tracker)
   cannot drive execution decisions when the registry says a session is
   non-active.

Coverage groups
---------------
A  — PR-22 sentinels present in core modules.
B  — core.runtime re-exports all PR-22 symbols.
C  — Sentinel content / shape correctness.
D  — Projection sentinel present and not UNAVAILABLE (skipped without fastapi).
E  — resolve_reuse_dispatch_surface: registry gate for replaced session.
F  — resolve_reuse_dispatch_surface: registry gate for detached session.
G  — resolve_reuse_dispatch_surface: registry gate for invalidated session.
H  — resolve_reuse_dispatch_surface: active session allowed through.
I  — resolve_reuse_dispatch_surface: unregistered session allowed through.
J  — dispatch_with_reuse_binding: registry gate blocks non-active session.
K  — dispatch_with_reuse_binding: active session allowed (reuses or new_binding).
L  — reconcile_android_execution_signal: registry gate for replaced session.
M  — reconcile_android_execution_signal: registry gate for detached session.
N  — reconcile_android_execution_signal: registry gate for invalidated session.
O  — reconcile_android_execution_signal: active session reconciles.
P  — reconcile_android_execution_signal: unregistered session reconciles.
Q  — reconcile_android_execution_signal: no session_id (no registry check).
R  — ingest_delegated_execution_signal: registry gate for replaced session.
S  — ingest_delegated_execution_signal: registry gate for detached session.
T  — ingest_delegated_execution_signal: registry gate for invalidated session.
U  — ingest_delegated_execution_signal: active session flows through.
V  — ingest_delegated_execution_signal: unregistered session flows through.
W  — Side-channel truth cannot override registry: replaced session with live
     reuse binding still rejected by dispatch.
X  — Side-channel truth cannot override registry: replaced session with live
     tracker record still rejected by reconciler.
Y  — Session lifecycle semantics: register → active → replace → replaced /
     register → active → detach → detached / register → active → invalidate →
     invalidated.
Z  — Two independent sessions are completely isolated from each other's
     registry gate decisions.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

import pytest

from core.attached_runtime_session_registry import (
    ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL,
    REGISTRY_DISPATCH_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY,
    REGISTRY_RECONCILIATION_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY,
    REGISTRY_REPLACED_SESSION_IS_NOT_ELIGIBLE_POLICY,
    REGISTRY_REUSE_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY,
    REGISTRY_SIDE_CHANNEL_TRUTH_IS_BLOCKED_POLICY,
    AttachedSessionRegistry,
    AttachedSessionRegistryEntry,
    InvalidationReason,
    RegistryEntryState,
    RegistryTransition,
    detach_session,
    invalidate_session,
    lookup_active_session,
    register_session,
)
from core.attached_runtime_reuse_dispatch import (
    REUSE_DISPATCH_NON_ACTIVE_REGISTRY_SESSION_IS_HARD_REJECTED_POLICY,
    REUSE_DISPATCH_PR22_SENTINEL,
    REUSE_DISPATCH_REGISTRY_GATE_PRECEDES_BINDING_CHECK_POLICY,
    ReuseDispatchResolutionKind,
    dispatch_with_reuse_binding,
    resolve_reuse_dispatch_surface,
)
from core.android_execution_signal_reconciler import (
    RECONCILER_NON_ACTIVE_SESSION_IS_HARD_REJECTED_POLICY,
    RECONCILER_PR22_SENTINEL,
    RECONCILER_REGISTRY_GATE_PRECEDES_TRACKER_LOOKUP_POLICY,
    AndroidSignalKind,
    reconcile_android_execution_signal,
)
from core.android_delegated_signal_ingress import (
    INGRESS_NON_ACTIVE_SESSION_IS_DROPPED_POLICY,
    INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL,
    INGRESS_REGISTRY_GATE_PRECEDES_RECONCILE_POLICY,
    ingest_delegated_execution_signal,
)
from core.android_execution_signal_reconciler import AndroidExecutionSignalEnvelope
from core.attached_runtime_reuse_binding import (
    AttachedRuntimeReuseBindingRuntime,
    establish_reuse_binding,
)
from core.delegated_runtime_execution_tracker import (
    DelegatedExecutionTrackingRuntime,
    create_execution_tracking_record,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SESSION_POSTURE = "join_runtime"
_SESSION_HOST_ROLE = "android"


def _fresh_registry() -> AttachedSessionRegistry:
    """Return a fresh isolated session registry (not the process singleton)."""
    return AttachedSessionRegistry()


def _register(
    registry: AttachedSessionRegistry,
    *,
    session_id: str = "",
    device_id: str = "",
) -> AttachedSessionRegistryEntry:
    sid = session_id or f"ses-{uuid.uuid4().hex[:8]}"
    did = device_id or f"dev-{uuid.uuid4().hex[:8]}"
    return register_session(
        did,
        session_id=sid,
        posture=_SESSION_POSTURE,
        host_role=_SESSION_HOST_ROLE,
        registry=registry,
    )


def _make_android_envelope(
    session_id: str = "",
    contract_id: str = "",
    device_id: str = "",
    signal_kind: AndroidSignalKind = AndroidSignalKind.ack,
) -> AndroidExecutionSignalEnvelope:
    return AndroidExecutionSignalEnvelope(
        signal_kind=signal_kind,
        contract_id=contract_id or f"ctr-{uuid.uuid4().hex[:8]}",
        session_id=session_id or f"ses-{uuid.uuid4().hex[:8]}",
        device_id=device_id or f"dev-{uuid.uuid4().hex[:8]}",
        trace_id=f"trace-{uuid.uuid4().hex[:8]}",
        task_id=f"task-{uuid.uuid4().hex[:8]}",
        signal_id=f"sig-{uuid.uuid4().hex[:8]}",
        emission_seq=1,
        payload={},
    )


def _make_delegated_signal_message(
    session_id: str = "",
    contract_id: str = "",
    device_id: str = "",
    signal_kind: str = "ack",
) -> Dict[str, Any]:
    return {
        "type": "delegated_execution_signal",
        "session_id": session_id or f"ses-{uuid.uuid4().hex[:8]}",
        "device_id": device_id or f"dev-{uuid.uuid4().hex[:8]}",
        "payload": {
            "contract_id": contract_id or f"ctr-{uuid.uuid4().hex[:8]}",
            "session_id": session_id or "",
            "device_id": device_id or "",
            "trace_id": f"trace-{uuid.uuid4().hex[:8]}",
            "task_id": f"task-{uuid.uuid4().hex[:8]}",
            "signal_kind": signal_kind,
            "signal_id": f"sig-{uuid.uuid4().hex[:8]}",
            "emission_seq": 1,
        },
    }


def _detach(
    entry: AttachedSessionRegistryEntry,
    registry: AttachedSessionRegistry,
) -> AttachedSessionRegistryEntry:
    """Helper: detach a registry entry."""
    return detach_session(entry, registry=registry)


def _invalidate(
    entry: AttachedSessionRegistryEntry,
    registry: AttachedSessionRegistry,
) -> AttachedSessionRegistryEntry:
    """Helper: invalidate a registry entry."""
    return invalidate_session(entry, InvalidationReason.invalidated, registry=registry)


def _make_fresh_tracker_runtime() -> DelegatedExecutionTrackingRuntime:
    return DelegatedExecutionTrackingRuntime()


def _make_fresh_reuse_runtime() -> AttachedRuntimeReuseBindingRuntime:
    return AttachedRuntimeReuseBindingRuntime()


# ---------------------------------------------------------------------------
# Group A — PR-22 sentinels present in core modules
# ---------------------------------------------------------------------------


class TestGroupA_SentinelsPresent:
    def test_A01_registry_pr22_sentinel_present(self):
        assert ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL
        assert "PR22" in ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL

    def test_A02_registry_dispatch_gate_policy_present(self):
        assert REGISTRY_DISPATCH_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY
        assert "active" in REGISTRY_DISPATCH_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY.lower()

    def test_A03_registry_reuse_gate_policy_present(self):
        assert REGISTRY_REUSE_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY
        assert "active" in REGISTRY_REUSE_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY.lower()

    def test_A04_registry_reconciliation_gate_policy_present(self):
        assert REGISTRY_RECONCILIATION_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY
        assert "reconcil" in REGISTRY_RECONCILIATION_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY.lower()

    def test_A05_registry_replaced_session_policy_present(self):
        assert REGISTRY_REPLACED_SESSION_IS_NOT_ELIGIBLE_POLICY
        assert "replaced" in REGISTRY_REPLACED_SESSION_IS_NOT_ELIGIBLE_POLICY.lower()

    def test_A06_registry_side_channel_blocked_policy_present(self):
        assert REGISTRY_SIDE_CHANNEL_TRUTH_IS_BLOCKED_POLICY
        assert "side-channel" in REGISTRY_SIDE_CHANNEL_TRUTH_IS_BLOCKED_POLICY.lower()

    def test_A07_reuse_dispatch_pr22_sentinel_present(self):
        assert REUSE_DISPATCH_PR22_SENTINEL
        assert "22" in REUSE_DISPATCH_PR22_SENTINEL

    def test_A08_reuse_dispatch_registry_gate_policy_present(self):
        assert REUSE_DISPATCH_REGISTRY_GATE_PRECEDES_BINDING_CHECK_POLICY
        assert "registry" in REUSE_DISPATCH_REGISTRY_GATE_PRECEDES_BINDING_CHECK_POLICY.lower()

    def test_A09_reuse_dispatch_non_active_rejected_policy_present(self):
        assert REUSE_DISPATCH_NON_ACTIVE_REGISTRY_SESSION_IS_HARD_REJECTED_POLICY
        assert "rejected" in REUSE_DISPATCH_NON_ACTIVE_REGISTRY_SESSION_IS_HARD_REJECTED_POLICY.lower()

    def test_A10_reconciler_pr22_sentinel_present(self):
        assert RECONCILER_PR22_SENTINEL
        assert "22" in RECONCILER_PR22_SENTINEL

    def test_A11_reconciler_registry_gate_policy_present(self):
        assert RECONCILER_REGISTRY_GATE_PRECEDES_TRACKER_LOOKUP_POLICY
        assert "registry" in RECONCILER_REGISTRY_GATE_PRECEDES_TRACKER_LOOKUP_POLICY.lower()

    def test_A12_reconciler_non_active_rejected_policy_present(self):
        assert RECONCILER_NON_ACTIVE_SESSION_IS_HARD_REJECTED_POLICY
        assert "rejected" in RECONCILER_NON_ACTIVE_SESSION_IS_HARD_REJECTED_POLICY.lower()

    def test_A13_ingress_pr22_sentinel_present(self):
        assert INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL
        assert "22" in INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL

    def test_A14_ingress_registry_gate_policy_present(self):
        assert INGRESS_REGISTRY_GATE_PRECEDES_RECONCILE_POLICY
        assert "registry" in INGRESS_REGISTRY_GATE_PRECEDES_RECONCILE_POLICY.lower()

    def test_A15_ingress_non_active_dropped_policy_present(self):
        assert INGRESS_NON_ACTIVE_SESSION_IS_DROPPED_POLICY
        assert "dropped" in INGRESS_NON_ACTIVE_SESSION_IS_DROPPED_POLICY.lower()


# ---------------------------------------------------------------------------
# Group B — core.runtime re-exports all PR-22 symbols
# ---------------------------------------------------------------------------


class TestGroupB_CoreRuntimeReexports:
    def test_B01_registry_pr22_symbols_accessible_from_core_runtime(self):
        pytest.importorskip("pydantic", reason="core.runtime requires pydantic")
        import core.runtime as rt

        assert hasattr(rt, "ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL")
        assert hasattr(rt, "REGISTRY_DISPATCH_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY")
        assert hasattr(rt, "REGISTRY_REUSE_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY")
        assert hasattr(rt, "REGISTRY_RECONCILIATION_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY")
        assert hasattr(rt, "REGISTRY_REPLACED_SESSION_IS_NOT_ELIGIBLE_POLICY")
        assert hasattr(rt, "REGISTRY_SIDE_CHANNEL_TRUTH_IS_BLOCKED_POLICY")

    def test_B02_reuse_dispatch_pr22_symbols_accessible_from_core_runtime(self):
        pytest.importorskip("pydantic", reason="core.runtime requires pydantic")
        import core.runtime as rt

        assert hasattr(rt, "REUSE_DISPATCH_PR22_SENTINEL")
        assert hasattr(rt, "REUSE_DISPATCH_REGISTRY_GATE_PRECEDES_BINDING_CHECK_POLICY")
        assert hasattr(rt, "REUSE_DISPATCH_NON_ACTIVE_REGISTRY_SESSION_IS_HARD_REJECTED_POLICY")

    def test_B03_reconciler_pr22_symbols_accessible_from_core_runtime(self):
        pytest.importorskip("pydantic", reason="core.runtime requires pydantic")
        import core.runtime as rt

        assert hasattr(rt, "RECONCILER_PR22_SENTINEL")
        assert hasattr(rt, "RECONCILER_REGISTRY_GATE_PRECEDES_TRACKER_LOOKUP_POLICY")
        assert hasattr(rt, "RECONCILER_NON_ACTIVE_SESSION_IS_HARD_REJECTED_POLICY")

    def test_B04_ingress_pr22_symbols_accessible_from_core_runtime(self):
        pytest.importorskip("pydantic", reason="core.runtime requires pydantic")
        import core.runtime as rt

        assert hasattr(rt, "INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL")
        assert hasattr(rt, "INGRESS_REGISTRY_GATE_PRECEDES_RECONCILE_POLICY")
        assert hasattr(rt, "INGRESS_NON_ACTIVE_SESSION_IS_DROPPED_POLICY")


# ---------------------------------------------------------------------------
# Group C — Sentinel content correctness
# ---------------------------------------------------------------------------


class TestGroupC_SentinelContent:
    def test_C01_registry_pr22_sentinel_identifies_consolidation(self):
        s = ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL
        assert "consolidation" in s.lower() or "PR22" in s

    def test_C02_registry_dispatch_gate_policy_mentions_replaced(self):
        assert "replaced" in REGISTRY_DISPATCH_GATE_IS_HARD_STOP_FOR_NON_ACTIVE_POLICY

    def test_C03_reuse_dispatch_pr22_sentinel_identifies_registry(self):
        assert "registry" in REUSE_DISPATCH_PR22_SENTINEL.lower()

    def test_C04_reconciler_pr22_sentinel_identifies_registry(self):
        assert "registry" in RECONCILER_PR22_SENTINEL.lower()

    def test_C05_ingress_pr22_sentinel_identifies_registry(self):
        assert "registry" in INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL.lower()


# ---------------------------------------------------------------------------
# Group D — Projection sentinel (requires fastapi)
# ---------------------------------------------------------------------------


class TestGroupD_ProjectionSentinel:
    def test_D01_projection_pr22_sentinel_present_and_not_unavailable(self):
        pytest.importorskip("fastapi", reason="projection route requires fastapi")
        from core.routes.projection import AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22

        assert AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22
        assert "UNAVAILABLE" not in AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22


# ---------------------------------------------------------------------------
# Group E — resolve_reuse_dispatch_surface: replaced session is rejected
# ---------------------------------------------------------------------------


class TestGroupE_ReuseDispatch_ReplacedSession:
    def test_E01_replaced_session_is_rejected_at_registry_gate(self):
        """A session that has been replaced (superseded) must be hard-rejected."""
        registry = _fresh_registry()
        session_id = f"ses-e01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-e01-{uuid.uuid4().hex[:6]}"

        # Register the session as active
        entry = _register(registry, session_id=session_id, device_id=device_id)

        # Simulate replace: register a NEW session for the same device, which
        # marks the first session as 'replaced'.
        _register(registry, device_id=device_id)

        # Old session should now be 'replaced' in the registry
        old_entry = lookup_active_session(session_id, active_only=False, registry=registry)
        assert old_entry is not None
        assert old_entry.attachment_state == RegistryEntryState.replaced

        # resolve_reuse_dispatch_surface should hard-reject
        resolution = resolve_reuse_dispatch_surface(
            session_id,
            device_id,
            registry=registry,
        )
        assert resolution.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert "non-active" in resolution.reject_reason or "registry" in resolution.reject_reason

    def test_E02_replaced_session_reject_reason_contains_registry_marker(self):
        registry = _fresh_registry()
        session_id = f"ses-e02-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-e02-{uuid.uuid4().hex[:6]}"
        _register(registry, session_id=session_id, device_id=device_id)
        _register(registry, device_id=device_id)  # supersedes

        resolution = resolve_reuse_dispatch_surface(session_id, device_id, registry=registry)
        assert "registry" in resolution.reject_reason.lower()


# ---------------------------------------------------------------------------
# Group F — resolve_reuse_dispatch_surface: detached session is rejected
# ---------------------------------------------------------------------------


class TestGroupF_ReuseDispatch_DetachedSession:
    def test_F01_detached_session_is_rejected_at_registry_gate(self):
        registry = _fresh_registry()
        session_id = f"ses-f01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-f01-{uuid.uuid4().hex[:6]}"

        entry = _register(registry, session_id=session_id, device_id=device_id)
        _detach(entry, registry)

        # Verify registry state
        detached = lookup_active_session(session_id, active_only=False, registry=registry)
        assert detached is not None
        assert detached.attachment_state == RegistryEntryState.detached

        resolution = resolve_reuse_dispatch_surface(session_id, device_id, registry=registry)
        assert resolution.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert "registry" in resolution.reject_reason.lower()

    def test_F02_detached_session_no_reuse_binding_still_rejected_by_gate(self):
        """Even with no reuse binding, a detached session is blocked at registry gate."""
        registry = _fresh_registry()
        session_id = f"ses-f02-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-f02-{uuid.uuid4().hex[:6]}"
        entry = _register(registry, session_id=session_id, device_id=device_id)
        _detach(entry, registry)

        # No reuse binding exists — without PR22, this would return no_binding.
        # With PR22 registry gate, it should return rejected.
        resolution = resolve_reuse_dispatch_surface(session_id, device_id, registry=registry)
        assert resolution.resolution_kind == ReuseDispatchResolutionKind.rejected


# ---------------------------------------------------------------------------
# Group G — resolve_reuse_dispatch_surface: invalidated session is rejected
# ---------------------------------------------------------------------------


class TestGroupG_ReuseDispatch_InvalidatedSession:
    def test_G01_invalidated_session_is_rejected_at_registry_gate(self):
        registry = _fresh_registry()
        session_id = f"ses-g01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-g01-{uuid.uuid4().hex[:6]}"
        entry = _register(registry, session_id=session_id, device_id=device_id)
        _invalidate(entry, registry)

        invalidated = lookup_active_session(session_id, active_only=False, registry=registry)
        assert invalidated is not None
        assert invalidated.attachment_state == RegistryEntryState.invalidated

        resolution = resolve_reuse_dispatch_surface(session_id, device_id, registry=registry)
        assert resolution.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert "registry" in resolution.reject_reason.lower()


# ---------------------------------------------------------------------------
# Group H — resolve_reuse_dispatch_surface: active session allowed through
# ---------------------------------------------------------------------------


class TestGroupH_ReuseDispatch_ActiveSession:
    def test_H01_active_session_with_no_binding_returns_no_binding(self):
        """Active sessions in the registry should not be blocked; no binding → no_binding."""
        registry = _fresh_registry()
        session_id = f"ses-h01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-h01-{uuid.uuid4().hex[:6]}"
        _register(registry, session_id=session_id, device_id=device_id)

        resolution = resolve_reuse_dispatch_surface(session_id, device_id, registry=registry)
        # Active session with no reuse binding → should return no_binding (not rejected)
        assert resolution.resolution_kind == ReuseDispatchResolutionKind.no_binding

    def test_H02_active_session_with_eligible_binding_returns_reused(self):
        """Active sessions with an eligible binding should be allowed to reuse."""
        registry = _fresh_registry()
        reuse_runtime = _make_fresh_reuse_runtime()
        session_id = f"ses-h02-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-h02-{uuid.uuid4().hex[:6]}"

        _register(registry, session_id=session_id, device_id=device_id)

        # Establish a reuse binding
        establish_reuse_binding(
            session_id=session_id,
            device_id=device_id,
            source_runtime_posture="join_runtime",
            runtime=reuse_runtime,
        )

        resolution = resolve_reuse_dispatch_surface(
            session_id, device_id, registry=registry, reuse_runtime=reuse_runtime
        )
        assert resolution.resolution_kind == ReuseDispatchResolutionKind.reused


# ---------------------------------------------------------------------------
# Group I — resolve_reuse_dispatch_surface: unregistered session allowed
# ---------------------------------------------------------------------------


class TestGroupI_ReuseDispatch_UnregisteredSession:
    def test_I01_unregistered_session_with_no_binding_returns_no_binding(self):
        """Sessions not in the registry should not be blocked (backward compat)."""
        registry = _fresh_registry()  # empty registry
        session_id = f"ses-i01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-i01-{uuid.uuid4().hex[:6]}"

        resolution = resolve_reuse_dispatch_surface(session_id, device_id, registry=registry)
        # Not in registry at all → pass through; no binding → no_binding
        assert resolution.resolution_kind == ReuseDispatchResolutionKind.no_binding

    def test_I02_empty_session_id_with_no_binding_returns_no_binding(self):
        """Empty session_id with no binding returns no_binding; no registry check needed."""
        registry = _fresh_registry()
        resolution = resolve_reuse_dispatch_surface("", "dev-i02", registry=registry)
        assert resolution.resolution_kind == ReuseDispatchResolutionKind.no_binding


# ---------------------------------------------------------------------------
# Group J — dispatch_with_reuse_binding: registry gate blocks non-active
# ---------------------------------------------------------------------------


class TestGroupJ_DispatchWithReuseBinding_RegistryGate:
    def test_J01_dispatch_blocks_replaced_session(self):
        """dispatch_with_reuse_binding must block replaced sessions via registry gate."""
        registry = _fresh_registry()
        session_id = f"ses-j01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-j01-{uuid.uuid4().hex[:6]}"

        _register(registry, session_id=session_id, device_id=device_id)
        # Supersede the session
        _register(registry, device_id=device_id)

        result = dispatch_with_reuse_binding(
            session_id,
            device_id,
            attached_session=None,
            handoff_contract=None,
            execution_tracker=None,
            registry=registry,
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert "registry" in result.reject_reason.lower()

    def test_J02_dispatch_blocks_detached_session(self):
        registry = _fresh_registry()
        session_id = f"ses-j02-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-j02-{uuid.uuid4().hex[:6]}"
        entry = _register(registry, session_id=session_id, device_id=device_id)
        _detach(entry, registry)

        result = dispatch_with_reuse_binding(
            session_id,
            device_id,
            attached_session=None,
            handoff_contract=None,
            execution_tracker=None,
            registry=registry,
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected

    def test_J03_dispatch_blocks_invalidated_session(self):
        registry = _fresh_registry()
        session_id = f"ses-j03-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-j03-{uuid.uuid4().hex[:6]}"
        entry = _register(registry, session_id=session_id, device_id=device_id)
        _invalidate(entry, registry)

        result = dispatch_with_reuse_binding(
            session_id,
            device_id,
            attached_session=None,
            handoff_contract=None,
            execution_tracker=None,
            registry=registry,
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected


# ---------------------------------------------------------------------------
# Group K — dispatch_with_reuse_binding: active session allowed
# ---------------------------------------------------------------------------


class TestGroupK_DispatchWithReuseBinding_ActiveSession:
    def test_K01_active_unregistered_session_not_blocked(self):
        """Session not in registry (unregistered) passes through."""
        registry = _fresh_registry()
        session_id = f"ses-k01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-k01-{uuid.uuid4().hex[:6]}"

        # dispatch_with_reuse_binding calls resolve_reuse_dispatch_surface,
        # which for an unregistered session returns no_binding.
        # Then the function tries to create a new dispatch binding via
        # resolve_dispatch_binding(). We can verify it's not rejected.
        result = dispatch_with_reuse_binding(
            session_id,
            device_id,
            attached_session=None,
            handoff_contract=None,
            execution_tracker=None,
            registry=registry,
        )
        # Should not be rejected (either new_binding or errors from downstream are ok;
        # the key is it must not be rejected due to registry gate)
        assert result.resolution_kind != ReuseDispatchResolutionKind.rejected or \
               "registry" not in result.reject_reason.lower()


# ---------------------------------------------------------------------------
# Group L/M/N — reconcile_android_execution_signal: non-active sessions
# ---------------------------------------------------------------------------


class TestGroupL_Reconciler_ReplacedSession:
    def test_L01_replaced_session_signal_is_hard_rejected(self):
        """reconcile_android_execution_signal blocks signals for replaced sessions."""
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-l01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-l01-{uuid.uuid4().hex[:6]}"

        entry = _register(registry, session_id=session_id, device_id=device_id)
        # Create tracking record for the session
        create_execution_tracking_record(
            session_id=session_id,
            contract_id=f"ctr-{uuid.uuid4().hex[:8]}",
            device_id=device_id,
            trace_id=f"trace-{uuid.uuid4().hex[:8]}",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )
        # Supersede the session
        _register(registry, device_id=device_id)

        envelope = _make_android_envelope(session_id=session_id, device_id=device_id)
        outcome = reconcile_android_execution_signal(
            envelope, runtime=tracker_runtime, registry=registry
        )

        assert outcome.was_updated is False
        assert "registry" in outcome.reject_reason.lower()
        assert "non-active" in outcome.reject_reason.lower() or "not active" in outcome.reject_reason.lower() or "replaced" in outcome.reject_reason.lower()

    def test_L02_replaced_session_tracker_record_not_mutated(self):
        """The tracker record must NOT be updated when the registry rejects the session."""
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-l02-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-l02-{uuid.uuid4().hex[:6]}"
        contract_id = f"ctr-l02-{uuid.uuid4().hex[:6]}"

        _register(registry, session_id=session_id, device_id=device_id)
        record = create_execution_tracking_record(
            session_id=session_id,
            contract_id=contract_id,
            device_id=device_id,
            trace_id=f"trace-l02",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )
        initial_phase = record.phase

        # Supersede the session
        _register(registry, device_id=device_id)

        # Send a final_result signal — should be blocked
        envelope = _make_android_envelope(
            session_id=session_id,
            contract_id=contract_id,
            signal_kind=AndroidSignalKind.final_result,
        )
        outcome = reconcile_android_execution_signal(
            envelope, runtime=tracker_runtime, registry=registry
        )
        assert outcome.was_updated is False

        # Record should still be in initial phase (look up by session_id)
        from core.delegated_runtime_execution_tracker import get_execution_tracking_record
        current_record = get_execution_tracking_record(session_id, runtime=tracker_runtime)
        assert current_record is not None
        assert current_record.phase == initial_phase


class TestGroupM_Reconciler_DetachedSession:
    def test_M01_detached_session_signal_is_hard_rejected(self):
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-m01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-m01-{uuid.uuid4().hex[:6]}"

        entry = _register(registry, session_id=session_id, device_id=device_id)
        create_execution_tracking_record(
            session_id=session_id,
            contract_id=f"ctr-{uuid.uuid4().hex[:8]}",
            device_id=device_id,
            trace_id="trace-m01",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )
        _detach(entry, registry)

        envelope = _make_android_envelope(session_id=session_id)
        outcome = reconcile_android_execution_signal(
            envelope, runtime=tracker_runtime, registry=registry
        )
        assert outcome.was_updated is False
        assert "registry" in outcome.reject_reason.lower()


class TestGroupN_Reconciler_InvalidatedSession:
    def test_N01_invalidated_session_signal_is_hard_rejected(self):
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-n01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-n01-{uuid.uuid4().hex[:6]}"

        entry = _register(registry, session_id=session_id, device_id=device_id)
        create_execution_tracking_record(
            session_id=session_id,
            contract_id=f"ctr-{uuid.uuid4().hex[:8]}",
            device_id=device_id,
            trace_id="trace-n01",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )
        _invalidate(entry, registry)

        envelope = _make_android_envelope(session_id=session_id)
        outcome = reconcile_android_execution_signal(
            envelope, runtime=tracker_runtime, registry=registry
        )
        assert outcome.was_updated is False
        assert "registry" in outcome.reject_reason.lower()


# ---------------------------------------------------------------------------
# Group O/P/Q — reconcile: active / unregistered / no-session-id
# ---------------------------------------------------------------------------


class TestGroupO_Reconciler_ActiveSession:
    def test_O01_active_session_reconciles_normally(self):
        """Active session signals must not be blocked by registry gate."""
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-o01-{uuid.uuid4().hex[:6]}"
        contract_id = f"ctr-o01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-o01-{uuid.uuid4().hex[:6]}"

        _register(registry, session_id=session_id, device_id=device_id)
        create_execution_tracking_record(
            session_id=session_id,
            contract_id=contract_id,
            device_id=device_id,
            trace_id="trace-o01",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )

        envelope = _make_android_envelope(
            session_id=session_id,
            contract_id=contract_id,
            device_id=device_id,
        )
        outcome = reconcile_android_execution_signal(
            envelope, runtime=tracker_runtime, registry=registry
        )
        assert outcome.was_updated is True


class TestGroupP_Reconciler_UnregisteredSession:
    def test_P01_unregistered_session_reconciles_normally(self):
        """Sessions not in the registry are allowed through (backward compat)."""
        registry = _fresh_registry()  # empty
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-p01-{uuid.uuid4().hex[:6]}"
        contract_id = f"ctr-p01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-p01-{uuid.uuid4().hex[:6]}"

        # Create a tracker record without registering the session
        create_execution_tracking_record(
            session_id=session_id,
            contract_id=contract_id,
            device_id=device_id,
            trace_id="trace-p01",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )

        envelope = _make_android_envelope(
            session_id=session_id,
            contract_id=contract_id,
        )
        outcome = reconcile_android_execution_signal(
            envelope, runtime=tracker_runtime, registry=registry
        )
        # Not rejected at registry gate; reconciled against tracker
        assert outcome.was_updated is True


class TestGroupQ_Reconciler_NoSessionId:
    def test_Q01_no_session_id_no_registry_check_uses_contract_id(self):
        """When session_id is empty the registry gate is skipped; contract_id drives lookup."""
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-q01-{uuid.uuid4().hex[:6]}"
        contract_id = f"ctr-q01-{uuid.uuid4().hex[:6]}"

        # Create tracking record with a session_id so it's in pending_ack phase
        create_execution_tracking_record(
            session_id=session_id,
            contract_id=contract_id,
            device_id="dev-q01",
            trace_id="trace-q01",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )

        # Envelope with empty session_id but valid contract_id
        # The registry gate should be skipped (no session_id to check).
        envelope = AndroidExecutionSignalEnvelope(
            signal_kind=AndroidSignalKind.ack,
            contract_id=contract_id,
            session_id="",  # empty → no registry check
            device_id="dev-q01",
            trace_id="trace-q01",
            task_id="task-q01",
            signal_id="sig-q01",
            emission_seq=1,
            payload={},
        )
        outcome = reconcile_android_execution_signal(
            envelope, runtime=tracker_runtime, registry=registry
        )
        # Registry gate skipped (empty session_id); lookup by contract_id succeeds
        assert outcome.was_updated is True


# ---------------------------------------------------------------------------
# Group R/S/T — ingest: non-active sessions blocked
# ---------------------------------------------------------------------------


class TestGroupR_Ingress_ReplacedSession:
    def test_R01_replaced_session_signal_dropped_at_ingress(self):
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-r01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-r01-{uuid.uuid4().hex[:6]}"
        contract_id = f"ctr-r01-{uuid.uuid4().hex[:6]}"

        _register(registry, session_id=session_id, device_id=device_id)
        create_execution_tracking_record(
            session_id=session_id,
            contract_id=contract_id,
            device_id=device_id,
            trace_id="trace-r01",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )
        # Supersede the session
        _register(registry, device_id=device_id)

        msg = _make_delegated_signal_message(
            session_id=session_id,
            contract_id=contract_id,
            device_id=device_id,
        )
        outcome = ingest_delegated_execution_signal(
            msg, runtime=tracker_runtime, registry=registry
        )
        assert outcome.was_updated is False
        assert "registry" in outcome.reject_reason.lower()

    def test_R02_replaced_session_reject_reason_identifies_policy(self):
        registry = _fresh_registry()
        session_id = f"ses-r02-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-r02-{uuid.uuid4().hex[:6]}"
        _register(registry, session_id=session_id, device_id=device_id)
        _register(registry, device_id=device_id)  # supersede

        msg = _make_delegated_signal_message(session_id=session_id, device_id=device_id)
        outcome = ingest_delegated_execution_signal(
            msg, runtime=_make_fresh_tracker_runtime(), registry=registry
        )
        assert outcome.was_updated is False
        assert "non-active" in outcome.reject_reason.lower() or "not active" in outcome.reject_reason.lower() or "replaced" in outcome.reject_reason.lower() or "registry" in outcome.reject_reason.lower()


class TestGroupS_Ingress_DetachedSession:
    def test_S01_detached_session_signal_dropped_at_ingress(self):
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-s01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-s01-{uuid.uuid4().hex[:6]}"

        entry = _register(registry, session_id=session_id, device_id=device_id)
        _detach(entry, registry)

        msg = _make_delegated_signal_message(session_id=session_id, device_id=device_id)
        outcome = ingest_delegated_execution_signal(
            msg, runtime=tracker_runtime, registry=registry
        )
        assert outcome.was_updated is False
        assert "registry" in outcome.reject_reason.lower()


class TestGroupT_Ingress_InvalidatedSession:
    def test_T01_invalidated_session_signal_dropped_at_ingress(self):
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-t01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-t01-{uuid.uuid4().hex[:6]}"

        entry = _register(registry, session_id=session_id, device_id=device_id)
        _invalidate(entry, registry)

        msg = _make_delegated_signal_message(session_id=session_id, device_id=device_id)
        outcome = ingest_delegated_execution_signal(
            msg, runtime=tracker_runtime, registry=registry
        )
        assert outcome.was_updated is False
        assert "registry" in outcome.reject_reason.lower()


# ---------------------------------------------------------------------------
# Group U/V — ingest: active / unregistered sessions pass through
# ---------------------------------------------------------------------------


class TestGroupU_Ingress_ActiveSession:
    def test_U01_active_session_signal_flows_through_ingress(self):
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-u01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-u01-{uuid.uuid4().hex[:6]}"
        contract_id = f"ctr-u01-{uuid.uuid4().hex[:6]}"

        _register(registry, session_id=session_id, device_id=device_id)
        create_execution_tracking_record(
            session_id=session_id,
            contract_id=contract_id,
            device_id=device_id,
            trace_id="trace-u01",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )

        msg = _make_delegated_signal_message(
            session_id=session_id,
            contract_id=contract_id,
            device_id=device_id,
        )
        outcome = ingest_delegated_execution_signal(
            msg, runtime=tracker_runtime, registry=registry
        )
        assert outcome.was_updated is True


class TestGroupV_Ingress_UnregisteredSession:
    def test_V01_unregistered_session_signal_passes_through(self):
        """Sessions not in registry are not blocked at ingress (backward compat)."""
        registry = _fresh_registry()  # empty
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-v01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-v01-{uuid.uuid4().hex[:6]}"
        contract_id = f"ctr-v01-{uuid.uuid4().hex[:6]}"

        # Create tracker record without registering in the registry
        create_execution_tracking_record(
            session_id=session_id,
            contract_id=contract_id,
            device_id=device_id,
            trace_id="trace-v01",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )

        msg = _make_delegated_signal_message(
            session_id=session_id,
            contract_id=contract_id,
            device_id=device_id,
        )
        outcome = ingest_delegated_execution_signal(
            msg, runtime=tracker_runtime, registry=registry
        )
        assert outcome.was_updated is True


# ---------------------------------------------------------------------------
# Group W — Side-channel truth: residual reuse binding with replaced session
# ---------------------------------------------------------------------------


class TestGroupW_SideChannelBlocked_ReuseBinding:
    def test_W01_replaced_session_reuse_binding_cannot_override_registry(self):
        """Even with an eligible reuse binding, a replaced session must be rejected."""
        registry = _fresh_registry()
        reuse_runtime = _make_fresh_reuse_runtime()
        session_id = f"ses-w01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-w01-{uuid.uuid4().hex[:6]}"

        _register(registry, session_id=session_id, device_id=device_id)
        # Establish a reuse binding while the session is active
        establish_reuse_binding(
            session_id=session_id,
            device_id=device_id,
            source_runtime_posture="join_runtime",
            runtime=reuse_runtime,
        )

        # Now supersede the session
        _register(registry, device_id=device_id)

        # The reuse binding still exists in the reuse runtime, but registry gate
        # should block before ever consulting the reuse binding.
        resolution = resolve_reuse_dispatch_surface(
            session_id,
            device_id,
            registry=registry,
            reuse_runtime=reuse_runtime,
        )
        assert resolution.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert "registry" in resolution.reject_reason.lower()

    def test_W02_detached_session_reuse_binding_blocked_by_registry_gate(self):
        registry = _fresh_registry()
        reuse_runtime = _make_fresh_reuse_runtime()
        session_id = f"ses-w02-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-w02-{uuid.uuid4().hex[:6]}"

        entry = _register(registry, session_id=session_id, device_id=device_id)
        establish_reuse_binding(
            session_id=session_id,
            device_id=device_id,
            source_runtime_posture="join_runtime",
            runtime=reuse_runtime,
        )
        _detach(entry, registry)

        resolution = resolve_reuse_dispatch_surface(
            session_id, device_id, registry=registry, reuse_runtime=reuse_runtime
        )
        assert resolution.resolution_kind == ReuseDispatchResolutionKind.rejected


# ---------------------------------------------------------------------------
# Group X — Side-channel truth: live tracker record with replaced session
# ---------------------------------------------------------------------------


class TestGroupX_SideChannelBlocked_TrackerRecord:
    def test_X01_replaced_session_tracker_record_cannot_be_updated(self):
        """Even with a live tracker record, a replaced session must be blocked."""
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()
        session_id = f"ses-x01-{uuid.uuid4().hex[:6]}"
        device_id = f"dev-x01-{uuid.uuid4().hex[:6]}"
        contract_id = f"ctr-x01-{uuid.uuid4().hex[:6]}"

        _register(registry, session_id=session_id, device_id=device_id)
        record = create_execution_tracking_record(
            session_id=session_id,
            contract_id=contract_id,
            device_id=device_id,
            trace_id="trace-x01",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )
        initial_phase = record.phase

        # Supersede the session — this is the "side-channel truth" scenario:
        # the tracker record still exists and is non-terminal, but the registry
        # says the session is replaced.
        _register(registry, device_id=device_id)

        envelope = _make_android_envelope(
            session_id=session_id,
            contract_id=contract_id,
            signal_kind=AndroidSignalKind.final_result,
        )
        outcome = reconcile_android_execution_signal(
            envelope, runtime=tracker_runtime, registry=registry
        )

        # Side-channel tracker record must NOT be mutated
        assert outcome.was_updated is False
        assert "registry" in outcome.reject_reason.lower()

        # Verify tracker phase unchanged (look up by session_id)
        from core.delegated_runtime_execution_tracker import get_execution_tracking_record
        still_same = get_execution_tracking_record(session_id, runtime=tracker_runtime)
        assert still_same is not None
        assert still_same.phase == initial_phase


# ---------------------------------------------------------------------------
# Group Y — Session lifecycle semantics
# ---------------------------------------------------------------------------


class TestGroupY_SessionLifecycleSemantics:
    def test_Y01_register_to_active_state(self):
        """Newly registered session is in active state."""
        registry = _fresh_registry()
        entry = _register(registry)
        assert entry.attachment_state == RegistryEntryState.active

    def test_Y02_register_supersedes_to_replaced_state(self):
        """Second registration for same device sets first session to replaced."""
        registry = _fresh_registry()
        device_id = f"dev-y02-{uuid.uuid4().hex[:6]}"
        first = _register(registry, device_id=device_id)
        _register(registry, device_id=device_id)

        first_in_registry = lookup_active_session(
            first.session_id, active_only=False, registry=registry
        )
        assert first_in_registry is not None
        assert first_in_registry.attachment_state == RegistryEntryState.replaced

    def test_Y03_detach_sets_detached_state(self):
        registry = _fresh_registry()
        session_id = f"ses-y03-{uuid.uuid4().hex[:6]}"
        entry = _register(registry, session_id=session_id)
        _detach(entry, registry)

        updated = lookup_active_session(session_id, active_only=False, registry=registry)
        assert updated is not None
        assert updated.attachment_state == RegistryEntryState.detached

    def test_Y04_invalidate_sets_invalidated_state(self):
        registry = _fresh_registry()
        session_id = f"ses-y04-{uuid.uuid4().hex[:6]}"
        entry = _register(registry, session_id=session_id)
        _invalidate(entry, registry)

        updated = lookup_active_session(session_id, active_only=False, registry=registry)
        assert updated is not None
        assert updated.attachment_state == RegistryEntryState.invalidated

    def test_Y05_active_session_active_only_lookup_succeeds(self):
        registry = _fresh_registry()
        session_id = f"ses-y05-{uuid.uuid4().hex[:6]}"
        _register(registry, session_id=session_id)

        active = lookup_active_session(session_id, active_only=True, registry=registry)
        assert active is not None
        assert active.attachment_state == RegistryEntryState.active

    def test_Y06_detached_session_active_only_lookup_returns_none(self):
        registry = _fresh_registry()
        session_id = f"ses-y06-{uuid.uuid4().hex[:6]}"
        entry = _register(registry, session_id=session_id)
        _detach(entry, registry)

        active = lookup_active_session(session_id, active_only=True, registry=registry)
        assert active is None

    def test_Y07_replaced_session_active_only_lookup_returns_none(self):
        registry = _fresh_registry()
        device_id = f"dev-y07-{uuid.uuid4().hex[:6]}"
        first = _register(registry, device_id=device_id)
        _register(registry, device_id=device_id)

        active = lookup_active_session(first.session_id, active_only=True, registry=registry)
        assert active is None

    def test_Y08_invalidated_session_active_only_lookup_returns_none(self):
        registry = _fresh_registry()
        session_id = f"ses-y08-{uuid.uuid4().hex[:6]}"
        entry = _register(registry, session_id=session_id)
        _invalidate(entry, registry)

        active = lookup_active_session(session_id, active_only=True, registry=registry)
        assert active is None


# ---------------------------------------------------------------------------
# Group Z — Two independent sessions are completely isolated
# ---------------------------------------------------------------------------


class TestGroupZ_SessionIsolation:
    def test_Z01_active_session_not_affected_by_sibling_replacement(self):
        """Replacing one session must not affect another independent session."""
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()

        # Session A (to be replaced)
        device_a = f"dev-z01-a-{uuid.uuid4().hex[:4]}"
        session_a_id = f"ses-z01-a-{uuid.uuid4().hex[:4]}"
        _register(registry, session_id=session_a_id, device_id=device_a)
        _register(registry, device_id=device_a)  # replace session A

        # Session B (stays active, different device)
        device_b = f"dev-z01-b-{uuid.uuid4().hex[:4]}"
        session_b_id = f"ses-z01-b-{uuid.uuid4().hex[:4]}"
        contract_b = f"ctr-z01-b-{uuid.uuid4().hex[:4]}"
        _register(registry, session_id=session_b_id, device_id=device_b)
        create_execution_tracking_record(
            session_id=session_b_id,
            contract_id=contract_b,
            device_id=device_b,
            trace_id="trace-z01-b",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )

        # Session B signal should reconcile normally
        env_b = _make_android_envelope(session_id=session_b_id, contract_id=contract_b)
        outcome_b = reconcile_android_execution_signal(
            env_b, runtime=tracker_runtime, registry=registry
        )
        assert outcome_b.was_updated is True

        # Session A signal should be rejected
        env_a = _make_android_envelope(session_id=session_a_id)
        outcome_a = reconcile_android_execution_signal(
            env_a, runtime=tracker_runtime, registry=registry
        )
        assert outcome_a.was_updated is False
        assert "registry" in outcome_a.reject_reason.lower()

    def test_Z02_ingress_isolation_between_active_and_replaced_sessions(self):
        """Active session signals flow; replaced session signals are blocked."""
        registry = _fresh_registry()
        tracker_runtime = _make_fresh_tracker_runtime()

        # Replaced session
        device_a = f"dev-z02-a-{uuid.uuid4().hex[:4]}"
        session_a = f"ses-z02-a-{uuid.uuid4().hex[:4]}"
        _register(registry, session_id=session_a, device_id=device_a)
        _register(registry, device_id=device_a)  # replace

        # Active session
        device_b = f"dev-z02-b-{uuid.uuid4().hex[:4]}"
        session_b = f"ses-z02-b-{uuid.uuid4().hex[:4]}"
        contract_b = f"ctr-z02-b-{uuid.uuid4().hex[:4]}"
        _register(registry, session_id=session_b, device_id=device_b)
        create_execution_tracking_record(
            session_id=session_b,
            contract_id=contract_b,
            device_id=device_b,
            trace_id="trace-z02-b",
            source_runtime_posture=_SESSION_POSTURE,
            runtime=tracker_runtime,
        )

        # Active session should pass ingress
        msg_b = _make_delegated_signal_message(
            session_id=session_b, contract_id=contract_b, device_id=device_b
        )
        out_b = ingest_delegated_execution_signal(
            msg_b, runtime=tracker_runtime, registry=registry
        )
        assert out_b.was_updated is True

        # Replaced session should be blocked
        msg_a = _make_delegated_signal_message(session_id=session_a, device_id=device_a)
        out_a = ingest_delegated_execution_signal(
            msg_a, runtime=tracker_runtime, registry=registry
        )
        assert out_a.was_updated is False
        assert "registry" in out_a.reject_reason.lower()
