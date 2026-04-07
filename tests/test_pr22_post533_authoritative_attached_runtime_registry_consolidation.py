"""tests/test_pr22_post533_authoritative_attached_runtime_registry_consolidation.py
==================================================================================
Tests for PR package 22 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Authoritative Attached Runtime Registry Consolidation.

This test suite verifies that:

1. The registry module exports all PR-22 policy/authority sentinels.
2. The reuse-dispatch module exports all PR-22 sentinels and that
   ``resolve_reuse_dispatch_surface()`` and ``dispatch_with_reuse_binding()``
   consult the registry gate before evaluating the reuse binding.
3. The reconciler module exports all PR-22 sentinels and that
   ``reconcile_android_execution_signal()`` and ``reconcile_inbound_message()``
   consult the registry gate before mutating the execution tracker.
4. The ingress module exports all PR-22 sentinels and that
   ``ingest_delegated_execution_signal()`` consults the registry gate before
   forwarding the signal to the recovery guard and reconciler.
5. The projection sentinel ``AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22``
   is importable from ``core.routes.projection`` and is not UNAVAILABLE.
6. Lifecycle semantics are stable across active / detached / invalidated /
   replaced states for all three entry-points.
7. Absent registry entries (unknown session_id) pass through to the downstream
   layer.
8. Active registry entries are not blocked by the gate.
9. No conflicting side-channel session truth drives execution decisions.

Coverage groups
---------------
A  — Registry PR-22 sentinel and policy sentinel presence.
B  — Reuse-dispatch PR-22 sentinel and policy sentinel presence.
C  — Reconciler PR-22 sentinel and policy sentinel presence.
D  — Ingress PR-22 sentinel and policy sentinel presence.
E  — Projection PR-22 sentinel presence (not UNAVAILABLE).
F  — Registry gate in resolve_reuse_dispatch_surface(): absent entry passes.
G  — Registry gate in resolve_reuse_dispatch_surface(): active entry passes.
H  — Registry gate in resolve_reuse_dispatch_surface(): replaced → rejected.
I  — Registry gate in resolve_reuse_dispatch_surface(): detached → rejected.
J  — Registry gate in resolve_reuse_dispatch_surface(): invalidated → rejected.
K  — Registry gate in dispatch_with_reuse_binding(): replaced → rejected.
L  — Registry gate in dispatch_with_reuse_binding(): absent entry passes.
M  — Registry gate in reconcile_android_execution_signal(): absent entry passes.
N  — Registry gate in reconcile_android_execution_signal(): active entry passes.
O  — Registry gate in reconcile_android_execution_signal(): replaced → blocked.
P  — Registry gate in reconcile_android_execution_signal(): detached → blocked.
Q  — Registry gate in reconcile_android_execution_signal(): invalidated → blocked.
R  — Registry gate in reconcile_inbound_message(): replaced → blocked.
S  — Registry gate in reconcile_inbound_message(): absent entry passes.
T  — Registry gate in ingest_delegated_execution_signal(): absent entry passes.
U  — Registry gate in ingest_delegated_execution_signal(): active entry passes.
V  — Registry gate in ingest_delegated_execution_signal(): replaced → blocked.
W  — Registry gate in ingest_delegated_execution_signal(): detached → blocked.
X  — Registry gate in ingest_delegated_execution_signal(): invalidated → blocked.
Y  — Superseded session (replaced) is blocked across all three entry-points.
Z  — core.runtime re-exports key PR-22 symbols.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.attached_runtime_session_registry import (
        AttachedSessionRegistry,
        RegistryEntryState,
        RegistryTransition,
        InvalidationReason,
        register_session,
        reconnect_session,
        detach_session,
        invalidate_session,
        lookup_active_session,
        ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL,
        REGISTRY_IS_AUTHORITATIVE_DISPATCH_GATE_PR22_POLICY,
        REGISTRY_IS_AUTHORITATIVE_REUSE_GATE_PR22_POLICY,
        REGISTRY_IS_AUTHORITATIVE_RECONCILIATION_GATE_PR22_POLICY,
        REGISTRY_KNOWN_NON_ACTIVE_BLOCKS_EXECUTION_PR22_POLICY,
        REGISTRY_ABSENT_ENTRY_PASSES_THROUGH_PR22_POLICY,
    )

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

try:
    from core.attached_runtime_reuse_dispatch import (
        ReuseDispatchResolutionKind,
        ReuseDispatchResolution,
        resolve_reuse_dispatch_surface,
        dispatch_with_reuse_binding,
        REUSE_DISPATCH_PR22_SENTINEL,
        REUSE_DISPATCH_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY,
        REUSE_DISPATCH_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY,
    )

    _REUSE_DISPATCH_AVAILABLE = True
except ImportError:
    _REUSE_DISPATCH_AVAILABLE = False

try:
    from core.android_execution_signal_reconciler import (
        AndroidExecutionSignalEnvelope,
        AndroidSignalKind,
        AndroidSignalReconcileOutcome,
        reconcile_android_execution_signal,
        reconcile_inbound_message,
        RECONCILER_PR22_SENTINEL,
        RECONCILER_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY,
        RECONCILER_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY,
    )

    _RECONCILER_AVAILABLE = True
except ImportError:
    _RECONCILER_AVAILABLE = False

try:
    from core.android_delegated_signal_ingress import (
        ingest_delegated_execution_signal,
        INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL,
        INGRESS_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY,
        INGRESS_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY,
    )

    _INGRESS_AVAILABLE = True
except ImportError:
    _INGRESS_AVAILABLE = False

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SKIP_REGISTRY = pytest.mark.skipif(
    not _REGISTRY_AVAILABLE, reason="attached_runtime_session_registry unavailable"
)
_SKIP_REUSE = pytest.mark.skipif(
    not _REUSE_DISPATCH_AVAILABLE, reason="attached_runtime_reuse_dispatch unavailable"
)
_SKIP_RECONCILER = pytest.mark.skipif(
    not _RECONCILER_AVAILABLE, reason="android_execution_signal_reconciler unavailable"
)
_SKIP_INGRESS = pytest.mark.skipif(
    not _INGRESS_AVAILABLE, reason="android_delegated_signal_ingress unavailable"
)
_SKIP_ALL = pytest.mark.skipif(
    not (
        _REGISTRY_AVAILABLE
        and _REUSE_DISPATCH_AVAILABLE
        and _RECONCILER_AVAILABLE
        and _INGRESS_AVAILABLE
    ),
    reason="one or more PR-22 modules unavailable",
)


def _make_registry(
    *,
    session_id: str = "sess-1",
    device_id: str = "dev-1",
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
    # RegistryEntryState.active — no further transition needed

    return reg


def _make_signal_envelope(session_id: str = "sess-1") -> "AndroidExecutionSignalEnvelope":
    """Return a minimal :class:`AndroidExecutionSignalEnvelope` for *session_id*."""
    return AndroidExecutionSignalEnvelope(
        signal_kind=AndroidSignalKind.ack,
        contract_id="contract-1",
        session_id=session_id,
        device_id="dev-1",
        trace_id="trace-1",
        task_id="task-1",
    )


def _make_inbound_message(session_id: str = "sess-1") -> dict:
    """Return a minimal delegated_execution_signal message dict for *session_id*."""
    return {
        "type": "delegated_execution_signal",
        "payload": {
            "signal_kind": "ack",
            "contract_id": "contract-1",
            "session_id": session_id,
            "device_id": "dev-1",
            "trace_id": "trace-1",
            "task_id": "task-1",
            "signal_id": "sig-1",
            "emission_seq": 1,
        },
    }


# ===========================================================================
# Group A — Registry PR-22 sentinel and policy sentinel presence
# ===========================================================================


@_SKIP_REGISTRY
class TestGroupA_RegistrySentinels:
    def test_consolidation_pr22_sentinel_is_nonempty(self):
        assert isinstance(ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL, str)
        assert len(ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL) > 0

    def test_dispatch_gate_policy_is_nonempty(self):
        assert isinstance(REGISTRY_IS_AUTHORITATIVE_DISPATCH_GATE_PR22_POLICY, str)
        assert len(REGISTRY_IS_AUTHORITATIVE_DISPATCH_GATE_PR22_POLICY) > 0

    def test_reuse_gate_policy_is_nonempty(self):
        assert isinstance(REGISTRY_IS_AUTHORITATIVE_REUSE_GATE_PR22_POLICY, str)
        assert len(REGISTRY_IS_AUTHORITATIVE_REUSE_GATE_PR22_POLICY) > 0

    def test_reconciliation_gate_policy_is_nonempty(self):
        assert isinstance(REGISTRY_IS_AUTHORITATIVE_RECONCILIATION_GATE_PR22_POLICY, str)
        assert len(REGISTRY_IS_AUTHORITATIVE_RECONCILIATION_GATE_PR22_POLICY) > 0

    def test_known_non_active_blocks_execution_policy_is_nonempty(self):
        assert isinstance(REGISTRY_KNOWN_NON_ACTIVE_BLOCKS_EXECUTION_PR22_POLICY, str)
        assert len(REGISTRY_KNOWN_NON_ACTIVE_BLOCKS_EXECUTION_PR22_POLICY) > 0

    def test_absent_entry_passes_through_policy_is_nonempty(self):
        assert isinstance(REGISTRY_ABSENT_ENTRY_PASSES_THROUGH_PR22_POLICY, str)
        assert len(REGISTRY_ABSENT_ENTRY_PASSES_THROUGH_PR22_POLICY) > 0

    def test_pr22_sentinel_contains_package_number(self):
        assert "22" in ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL


# ===========================================================================
# Group B — Reuse-dispatch PR-22 sentinel and policy sentinel presence
# ===========================================================================


@_SKIP_REUSE
class TestGroupB_ReuseDispatchSentinels:
    def test_reuse_dispatch_pr22_sentinel_is_nonempty(self):
        assert isinstance(REUSE_DISPATCH_PR22_SENTINEL, str)
        assert len(REUSE_DISPATCH_PR22_SENTINEL) > 0

    def test_registry_gate_policy_is_nonempty(self):
        assert isinstance(REUSE_DISPATCH_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY, str)
        assert len(REUSE_DISPATCH_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY) > 0

    def test_blocks_non_active_session_policy_is_nonempty(self):
        assert isinstance(REUSE_DISPATCH_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY, str)
        assert len(REUSE_DISPATCH_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY) > 0

    def test_pr22_sentinel_contains_package_number(self):
        assert "22" in REUSE_DISPATCH_PR22_SENTINEL


# ===========================================================================
# Group C — Reconciler PR-22 sentinel and policy sentinel presence
# ===========================================================================


@_SKIP_RECONCILER
class TestGroupC_ReconcilerSentinels:
    def test_reconciler_pr22_sentinel_is_nonempty(self):
        assert isinstance(RECONCILER_PR22_SENTINEL, str)
        assert len(RECONCILER_PR22_SENTINEL) > 0

    def test_registry_gate_policy_is_nonempty(self):
        assert isinstance(RECONCILER_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY, str)
        assert len(RECONCILER_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY) > 0

    def test_blocks_non_active_session_policy_is_nonempty(self):
        assert isinstance(RECONCILER_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY, str)
        assert len(RECONCILER_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY) > 0

    def test_pr22_sentinel_contains_package_number(self):
        assert "22" in RECONCILER_PR22_SENTINEL


# ===========================================================================
# Group D — Ingress PR-22 sentinel and policy sentinel presence
# ===========================================================================


@_SKIP_INGRESS
class TestGroupD_IngressSentinels:
    def test_ingress_pr22_sentinel_is_nonempty(self):
        assert isinstance(INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL, str)
        assert len(INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL) > 0

    def test_registry_gate_policy_is_nonempty(self):
        assert isinstance(INGRESS_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY, str)
        assert len(INGRESS_REGISTRY_GATE_IS_AUTHORITATIVE_PR22_POLICY) > 0

    def test_blocks_non_active_session_policy_is_nonempty(self):
        assert isinstance(INGRESS_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY, str)
        assert len(INGRESS_REGISTRY_BLOCKS_NON_ACTIVE_SESSION_PR22_POLICY) > 0

    def test_pr22_sentinel_contains_package_number(self):
        assert "22" in INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL


# ===========================================================================
# Group E — Projection PR-22 sentinel presence
# ===========================================================================


class TestGroupE_ProjectionSentinel:
    def test_projection_sentinel_is_importable_and_not_unavailable(self):
        try:
            from core.routes.projection import (
                AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22,
            )
        except ImportError:
            pytest.skip("projection module requires fastapi")

        assert isinstance(AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22, str)
        assert len(AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22) > 0
        assert "UNAVAILABLE" not in AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22

    def test_projection_sentinel_references_pr22(self):
        try:
            from core.routes.projection import (
                AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22,
            )
        except ImportError:
            pytest.skip("projection module requires fastapi")

        assert "PR22" in AUTHORITATIVE_ATTACHED_RUNTIME_REGISTRY_CONSOLIDATED_PR22


# ===========================================================================
# Group F — resolve_reuse_dispatch_surface: absent entry passes through
# ===========================================================================


@_SKIP_ALL
class TestGroupF_ResolveAbsentEntryPassesThrough:
    def test_absent_session_no_binding_result(self):
        """No registry entry for session_id → gate passes, returns no_binding."""
        reg = AttachedSessionRegistry()  # empty registry
        result = resolve_reuse_dispatch_surface(
            "unknown-session",
            "unknown-device",
            registry=reg,
        )
        # No reuse binding either → no_binding (gate did not block)
        assert result.resolution_kind == ReuseDispatchResolutionKind.no_binding

    def test_absent_session_empty_session_id_passes(self):
        """Empty session_id → gate has nothing to look up → no_binding."""
        reg = AttachedSessionRegistry()
        result = resolve_reuse_dispatch_surface(
            "",
            "dev-99",
            registry=reg,
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.no_binding


# ===========================================================================
# Group G — resolve_reuse_dispatch_surface: active entry passes
# ===========================================================================


@_SKIP_ALL
class TestGroupG_ResolveActiveEntryPassesThrough:
    def test_active_session_not_blocked_by_gate(self):
        """Active registry entry → gate passes → returns no_binding (no reuse binding)."""
        reg = _make_registry(session_id="sess-active", state=RegistryEntryState.active)
        result = resolve_reuse_dispatch_surface(
            "sess-active",
            "dev-1",
            registry=reg,
        )
        # Gate did not block; no reuse binding → no_binding
        assert result.resolution_kind == ReuseDispatchResolutionKind.no_binding
        assert result.reject_reason == ""


# ===========================================================================
# Group H — resolve_reuse_dispatch_surface: replaced → rejected
# ===========================================================================


@_SKIP_ALL
class TestGroupH_ResolveReplacedRejected:
    def test_replaced_session_is_rejected(self):
        reg = _make_registry(session_id="sess-old", state=RegistryEntryState.replaced)
        result = resolve_reuse_dispatch_surface(
            "sess-old",
            "dev-1",
            registry=reg,
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert "PR-22" in result.reject_reason or "registry gate" in result.reject_reason.lower()

    def test_replaced_session_reject_reason_mentions_state(self):
        reg = _make_registry(session_id="sess-r", state=RegistryEntryState.replaced)
        result = resolve_reuse_dispatch_surface("sess-r", "dev-1", registry=reg)
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected
        # The reject reason should mention the state value
        assert "replaced" in result.reject_reason


# ===========================================================================
# Group I — resolve_reuse_dispatch_surface: detached → rejected
# ===========================================================================


@_SKIP_ALL
class TestGroupI_ResolveDetachedRejected:
    def test_detached_session_is_rejected(self):
        reg = _make_registry(session_id="sess-det", state=RegistryEntryState.detached)
        result = resolve_reuse_dispatch_surface(
            "sess-det",
            "dev-1",
            registry=reg,
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert "detached" in result.reject_reason

    def test_detached_has_no_reuse_binding_field(self):
        reg = _make_registry(session_id="sess-det2", state=RegistryEntryState.detached)
        result = resolve_reuse_dispatch_surface("sess-det2", "dev-1", registry=reg)
        assert result.reuse_binding is None


# ===========================================================================
# Group J — resolve_reuse_dispatch_surface: invalidated → rejected
# ===========================================================================


@_SKIP_ALL
class TestGroupJ_ResolveInvalidatedRejected:
    def test_invalidated_session_is_rejected(self):
        reg = _make_registry(session_id="sess-inv", state=RegistryEntryState.invalidated)
        result = resolve_reuse_dispatch_surface(
            "sess-inv",
            "dev-1",
            registry=reg,
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert "invalidated" in result.reject_reason

    def test_invalidated_session_session_id_preserved(self):
        reg = _make_registry(session_id="sess-inv2", state=RegistryEntryState.invalidated)
        result = resolve_reuse_dispatch_surface("sess-inv2", "dev-1", registry=reg)
        assert result.session_id == "sess-inv2"


# ===========================================================================
# Group K — dispatch_with_reuse_binding: replaced → rejected
# ===========================================================================


@_SKIP_ALL
class TestGroupK_DispatchReplacedRejected:
    def test_dispatch_replaced_session_is_rejected(self):
        reg = _make_registry(session_id="sess-rep", state=RegistryEntryState.replaced)
        result = dispatch_with_reuse_binding(
            "sess-rep",
            "dev-1",
            attached_session=None,
            handoff_contract=None,
            execution_tracker=None,
            registry=reg,
        )
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected
        assert "replaced" in result.reject_reason

    def test_dispatch_replaced_does_not_create_dispatch_binding(self):
        reg = _make_registry(session_id="sess-rep2", state=RegistryEntryState.replaced)
        result = dispatch_with_reuse_binding(
            "sess-rep2",
            "dev-1",
            attached_session=None,
            handoff_contract=None,
            execution_tracker=None,
            registry=reg,
        )
        assert result.dispatch_binding is None


# ===========================================================================
# Group L — dispatch_with_reuse_binding: absent entry passes
# ===========================================================================


@_SKIP_ALL
class TestGroupL_DispatchAbsentEntryPasses:
    def test_dispatch_absent_entry_no_binding(self):
        """No registry entry for session_id → gate passes through (no reuse binding)."""
        reg = AttachedSessionRegistry()
        result = dispatch_with_reuse_binding(
            "unknown-sess",
            "unknown-dev",
            attached_session=None,
            handoff_contract=None,
            execution_tracker=None,
            registry=reg,
        )
        # No reuse binding found → new_binding path attempted; but since
        # attached_session/handoff_contract/execution_tracker are None the
        # downstream resolve_dispatch_binding may raise. We expect the gate
        # itself not to block (kind != rejected due to registry).
        assert result.resolution_kind != ReuseDispatchResolutionKind.rejected or (
            "registry gate" not in (result.reject_reason or "")
        )


# ===========================================================================
# Group M — reconcile_android_execution_signal: absent entry passes
# ===========================================================================


@_SKIP_ALL
class TestGroupM_ReconcileAbsentEntryPasses:
    def test_absent_session_gate_passes_to_tracker_miss(self):
        """No registry entry → gate passes → reconcile returns no record found."""
        reg = AttachedSessionRegistry()
        envelope = _make_signal_envelope(session_id="unknown-sess")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = reconcile_android_execution_signal(envelope, runtime=rt, registry=reg)
        # Gate did not block; tracker has no record → was_updated=False
        assert result.was_updated is False
        assert "registry gate" not in (result.reject_reason or "").lower()


# ===========================================================================
# Group N — reconcile_android_execution_signal: active entry passes
# ===========================================================================


@_SKIP_ALL
class TestGroupN_ReconcileActiveEntryPasses:
    def test_active_session_not_blocked(self):
        reg = _make_registry(session_id="sess-active", state=RegistryEntryState.active)
        envelope = _make_signal_envelope(session_id="sess-active")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = reconcile_android_execution_signal(envelope, runtime=rt, registry=reg)
        # Active → not blocked; tracker has no record → was_updated=False
        assert result.was_updated is False
        assert "registry gate" not in (result.reject_reason or "").lower()


# ===========================================================================
# Group O — reconcile_android_execution_signal: replaced → blocked
# ===========================================================================


@_SKIP_ALL
class TestGroupO_ReconcileReplacedBlocked:
    def test_replaced_session_is_blocked(self):
        reg = _make_registry(session_id="sess-rep", state=RegistryEntryState.replaced)
        envelope = _make_signal_envelope(session_id="sess-rep")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = reconcile_android_execution_signal(envelope, runtime=rt, registry=reg)
        assert result.was_updated is False
        assert "registry gate" in result.reject_reason.lower() or "replaced" in result.reject_reason

    def test_replaced_block_does_not_mutate_tracker(self):
        reg = _make_registry(session_id="sess-rep2", state=RegistryEntryState.replaced)
        envelope = _make_signal_envelope(session_id="sess-rep2")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = reconcile_android_execution_signal(envelope, runtime=rt, registry=reg)
        assert result.record is None
        assert result.was_updated is False


# ===========================================================================
# Group P — reconcile_android_execution_signal: detached → blocked
# ===========================================================================


@_SKIP_ALL
class TestGroupP_ReconcileDetachedBlocked:
    def test_detached_session_is_blocked(self):
        reg = _make_registry(session_id="sess-det", state=RegistryEntryState.detached)
        envelope = _make_signal_envelope(session_id="sess-det")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = reconcile_android_execution_signal(envelope, runtime=rt, registry=reg)
        assert result.was_updated is False
        assert "detached" in result.reject_reason


# ===========================================================================
# Group Q — reconcile_android_execution_signal: invalidated → blocked
# ===========================================================================


@_SKIP_ALL
class TestGroupQ_ReconcileInvalidatedBlocked:
    def test_invalidated_session_is_blocked(self):
        reg = _make_registry(session_id="sess-inv", state=RegistryEntryState.invalidated)
        envelope = _make_signal_envelope(session_id="sess-inv")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = reconcile_android_execution_signal(envelope, runtime=rt, registry=reg)
        assert result.was_updated is False
        assert "invalidated" in result.reject_reason


# ===========================================================================
# Group R — reconcile_inbound_message: replaced → blocked
# ===========================================================================


@_SKIP_ALL
class TestGroupR_ReconcileInboundReplacedBlocked:
    def test_replaced_session_inbound_message_blocked(self):
        reg = _make_registry(session_id="sess-rep", state=RegistryEntryState.replaced)
        msg = {
            "type": "task_result",
            "payload": {"session_id": "sess-rep", "contract_id": "c1"},
        }
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = reconcile_inbound_message(msg, runtime=rt, registry=reg)
        assert result.was_updated is False
        assert "replaced" in result.reject_reason


# ===========================================================================
# Group S — reconcile_inbound_message: absent entry passes
# ===========================================================================


@_SKIP_ALL
class TestGroupS_ReconcileInboundAbsentPasses:
    def test_absent_session_inbound_message_passes_gate(self):
        reg = AttachedSessionRegistry()
        msg = {
            "type": "task_result",
            "payload": {"session_id": "unknown-s", "contract_id": "c1"},
        }
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = reconcile_inbound_message(msg, runtime=rt, registry=reg)
        # Gate did not block; tracker miss → was_updated=False
        assert result.was_updated is False
        assert "registry gate" not in (result.reject_reason or "").lower()


# ===========================================================================
# Group T — ingest_delegated_execution_signal: absent entry passes
# ===========================================================================


@_SKIP_ALL
class TestGroupT_IngestAbsentEntryPasses:
    def test_absent_session_ingest_passes_gate(self):
        reg = AttachedSessionRegistry()
        msg = _make_inbound_message(session_id="unknown-sess")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = ingest_delegated_execution_signal(msg, runtime=rt, registry=reg)
        # Gate did not block; tracker miss → was_updated=False
        assert result.was_updated is False
        assert "registry gate" not in (result.reject_reason or "").lower()


# ===========================================================================
# Group U — ingest_delegated_execution_signal: active entry passes
# ===========================================================================


@_SKIP_ALL
class TestGroupU_IngestActiveEntryPasses:
    def test_active_session_not_blocked(self):
        reg = _make_registry(session_id="sess-active", state=RegistryEntryState.active)
        msg = _make_inbound_message(session_id="sess-active")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = ingest_delegated_execution_signal(msg, runtime=rt, registry=reg)
        assert result.was_updated is False
        assert "registry gate" not in (result.reject_reason or "").lower()


# ===========================================================================
# Group V — ingest_delegated_execution_signal: replaced → blocked
# ===========================================================================


@_SKIP_ALL
class TestGroupV_IngestReplacedBlocked:
    def test_replaced_session_ingest_blocked(self):
        reg = _make_registry(session_id="sess-rep", state=RegistryEntryState.replaced)
        msg = _make_inbound_message(session_id="sess-rep")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = ingest_delegated_execution_signal(msg, runtime=rt, registry=reg)
        assert result.was_updated is False
        assert "replaced" in result.reject_reason

    def test_replaced_block_does_not_reach_reconciler(self):
        """Replaced session must be blocked before reaching the reconciler."""
        reg = _make_registry(session_id="sess-rep2", state=RegistryEntryState.replaced)
        msg = _make_inbound_message(session_id="sess-rep2")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = ingest_delegated_execution_signal(msg, runtime=rt, registry=reg)
        # Block must carry the PR-22 registry gate reason
        assert "registry gate" in result.reject_reason.lower() or "replaced" in result.reject_reason


# ===========================================================================
# Group W — ingest_delegated_execution_signal: detached → blocked
# ===========================================================================


@_SKIP_ALL
class TestGroupW_IngestDetachedBlocked:
    def test_detached_session_ingest_blocked(self):
        reg = _make_registry(session_id="sess-det", state=RegistryEntryState.detached)
        msg = _make_inbound_message(session_id="sess-det")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = ingest_delegated_execution_signal(msg, runtime=rt, registry=reg)
        assert result.was_updated is False
        assert "detached" in result.reject_reason


# ===========================================================================
# Group X — ingest_delegated_execution_signal: invalidated → blocked
# ===========================================================================


@_SKIP_ALL
class TestGroupX_IngestInvalidatedBlocked:
    def test_invalidated_session_ingest_blocked(self):
        reg = _make_registry(session_id="sess-inv", state=RegistryEntryState.invalidated)
        msg = _make_inbound_message(session_id="sess-inv")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = ingest_delegated_execution_signal(msg, runtime=rt, registry=reg)
        assert result.was_updated is False
        assert "invalidated" in result.reject_reason


# ===========================================================================
# Group Y — Superseded session blocked across all three entry-points
# ===========================================================================


@_SKIP_ALL
class TestGroupY_SupersededSessionConsistency:
    """A replaced (superseded) session must be blocked at all three surfaces."""

    def _setup(self):
        reg = _make_registry(session_id="sess-super", state=RegistryEntryState.replaced)
        return reg

    def test_dispatch_surface_rejects_superseded(self):
        reg = self._setup()
        result = resolve_reuse_dispatch_surface("sess-super", "dev-1", registry=reg)
        assert result.resolution_kind == ReuseDispatchResolutionKind.rejected

    def test_reconciler_blocks_superseded(self):
        reg = self._setup()
        envelope = _make_signal_envelope(session_id="sess-super")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = reconcile_android_execution_signal(envelope, runtime=rt, registry=reg)
        assert result.was_updated is False
        assert "replaced" in result.reject_reason

    def test_ingress_blocks_superseded(self):
        reg = self._setup()
        msg = _make_inbound_message(session_id="sess-super")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        result = ingest_delegated_execution_signal(msg, runtime=rt, registry=reg)
        assert result.was_updated is False
        assert "replaced" in result.reject_reason

    def test_same_reject_semantics_across_surfaces(self):
        """All three surfaces return was_updated=False for superseded session."""
        reg_d = self._setup()
        reg_r = self._setup()
        reg_i = self._setup()

        dispatch_result = resolve_reuse_dispatch_surface(
            "sess-super", "dev-1", registry=reg_d
        )
        assert dispatch_result.resolution_kind == ReuseDispatchResolutionKind.rejected

        envelope = _make_signal_envelope(session_id="sess-super")
        from core.delegated_runtime_execution_tracker import DelegatedExecutionTrackingRuntime

        rt = DelegatedExecutionTrackingRuntime()
        rec_result = reconcile_android_execution_signal(
            envelope, runtime=rt, registry=reg_r
        )
        assert rec_result.was_updated is False

        msg = _make_inbound_message(session_id="sess-super")
        rt2 = DelegatedExecutionTrackingRuntime()
        ing_result = ingest_delegated_execution_signal(
            msg, runtime=rt2, registry=reg_i
        )
        assert ing_result.was_updated is False


# ===========================================================================
# Group Z — core.runtime re-exports
# ===========================================================================


class TestGroupZ_CoreRuntimeReexports:
    def test_runtime_reexports_pr22_registry_sentinel(self):
        try:
            from core.runtime import ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL

            assert isinstance(ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL, str)
            assert len(ATTACHED_RUNTIME_REGISTRY_CONSOLIDATION_PR22_SENTINEL) > 0
        except ImportError:
            pytest.skip("core.runtime does not yet export PR-22 sentinel")

    def test_runtime_reexports_reuse_dispatch_pr22_sentinel(self):
        try:
            from core.runtime import REUSE_DISPATCH_PR22_SENTINEL

            assert isinstance(REUSE_DISPATCH_PR22_SENTINEL, str)
        except ImportError:
            pytest.skip("core.runtime does not yet export REUSE_DISPATCH_PR22_SENTINEL")

    def test_runtime_reexports_reconciler_pr22_sentinel(self):
        try:
            from core.runtime import RECONCILER_PR22_SENTINEL

            assert isinstance(RECONCILER_PR22_SENTINEL, str)
        except ImportError:
            pytest.skip("core.runtime does not yet export RECONCILER_PR22_SENTINEL")

    def test_runtime_reexports_ingress_pr22_sentinel(self):
        try:
            from core.runtime import INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL

            assert isinstance(INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL, str)
        except ImportError:
            pytest.skip("core.runtime does not yet export INGRESS_REGISTRY_CONSOLIDATION_PR22_SENTINEL")
