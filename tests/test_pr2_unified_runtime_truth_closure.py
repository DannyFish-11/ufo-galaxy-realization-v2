#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pr2_unified_runtime_truth_closure.py
===================================================
PR-2: Unified Runtime Truth / Session / Migration / Mesh Closure Tests.

This test suite verifies that:

A. Single Runtime Truth Ingress
   A1.  UNIFIED_RUNTIME_TRUTH_INGRESS_AUTHORITY is importable and non-empty.
   A2.  UNIFIED_RUNTIME_TRUTH_INGRESS_PR2_SENTINEL is importable and non-empty.
   A3.  All no-parallel-write policy sentinels are importable and non-empty.
   A4.  RuntimeTruthIngressOutcome is importable as a dataclass.
   A5.  RuntimeTruthIngressOutcome.to_dict() includes all required keys.
   A6.  get_session_authority() returns a non-None object (registry available).
   A7.  ingest_android_runtime_state_update() routes handoff_result to 'handoff' path.
   A8.  ingest_android_runtime_state_update() routes handoff_ack to 'handoff' path.
   A9.  ingest_android_runtime_state_update() routes handoff_failure to 'handoff' path.
   A10. ingest_android_runtime_state_update() routes 'result' signal to 'execution_signal' path.
   A11. ingest_android_runtime_state_update() routes 'ack' signal to 'execution_signal' path.
   A12. ingest_android_runtime_state_update() routes 'progress' signal to 'execution_signal' path.
   A13. ingest_android_runtime_state_update() routes 'error' signal to 'execution_signal' path.
   A14. ingest_android_runtime_state_update() routes 'timeout' signal to 'execution_signal' path.
   A15. ingest_android_runtime_state_update() routes 'cancelled' signal to 'execution_signal' path.
   A16. ingest_android_runtime_state_update() routes session_snapshot to 'participant_truth' path.
   A17. ingest_android_runtime_state_update() routes runtime_state to 'participant_truth' path.
   A18. ingest_android_runtime_state_update() rejects empty-type message with no identity fields.
   A19. ingest_android_runtime_state_update() never raises even with bad input.
   A20. ingest_android_runtime_state_update() returns RuntimeTruthIngressOutcome (not None).
   A21. Non-dict message input returns rejected outcome without raising.

B. Single Session Authority Contract
   B1.  SESSION_AUTHORITY_CONTRACT_AUTHORITY is importable and non-empty.
   B2.  SESSION_AUTHORITY_CONTRACT_PR2_SENTINEL is importable and non-empty.
   B3.  All 8 policy sentinels are importable and non-empty strings.
   B4.  ATTACHED_SESSION_REGISTRY_IS_SINGLE_SESSION_AUTHORITY_POLICY mentions registry.
   B5.  FLOW_CONTINUITY_COORDINATOR_IS_DECISION_AUTHORITY_POLICY mentions coordinator.
   B6.  SHARED_IDENTITY_CONTRACT_POLICY mentions runtime_session_id.
   B7.  RECONNECT_MUST_PRESERVE_RUNTIME_SESSION_ID_POLICY mentions reconnect_session.
   B8.  MIGRATION_MUST_USE_REGISTRY_SUPERSESSION_POLICY mentions register_session.
   B9.  HANDOFF_IDENTITY_MUST_CORRELATE_TO_REGISTRY_POLICY mentions session_id.
   B10. STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY mentions non-destructive.
   B11. NO_BYPASS_CONTINUITY_DECISION_POLICY mentions FlowContinuityCoordinator.
   B12. SessionAuthoritySnapshot is importable as a dataclass.
   B13. SessionAuthoritySnapshot.to_dict() includes all required keys.
   B14. get_session_authority_registry() returns non-None object (registry available).
   B15. get_continuity_coordinator() returns non-None object (coordinator available).
   B16. build_session_authority_snapshot() returns a SessionAuthoritySnapshot.
   B17. build_session_authority_snapshot() never raises.
   B18. Snapshot.registry_available is True when registry is accessible.
   B19. Snapshot.coordinator_available is True when coordinator is accessible.
   B20. Snapshot.authority_policy_count > 0.

C. Session Authority — Reconnect Identity Preservation
   C1.  AttachedSessionRegistry reconnect_session preserves runtime_session_id.
   C2.  AttachedSessionRegistry register_session creates a new runtime_session_id.
   C3.  Two register_session calls for same device create supersession.
   C4.  reconnect_session on active entry keeps active state.
   C5.  detach_session followed by reconnect_session restores active state.
   C6.  invalidate_session makes entry terminal (further reconnect is no-op).

D. Session Authority — Migration Identity Contract
   D1.  register_session for new device does not create a duplicate active entry.
   D2.  After supersession the old entry is in 'replaced' state.
   D3.  lookup_active_session returns None for replaced entry.
   D4.  New entry after migration has different session_id from old entry.
   D5.  Old runtime_session_id is preserved in registry history (active_only=False).

E. Mesh Role Contract
   E1.  STAGED_MESH_ROLE_CONTRACT_AUTHORITY is importable and non-empty.
   E2.  STAGED_MESH_ROLE_CONTRACT_PR2_SENTINEL is importable and non-empty.
   E3.  STAGED_MESH_MAIN_CHAIN_ROLE equals 'main_chain_live_execution'.
   E4.  STAGED_MESH_IS_CONNECTED_TO_LIVE_ENGINE is True.
   E5.  STAGED_MESH_LIVE_ENGINE_MODULE references live_mesh_runtime_engine.
   E6.  STAGED_MESH_ORCHESTRATOR_MODULE references source_dispatch_orchestrator.
   E7.  All 4 policy sentinels are importable and non-empty strings.
   E8.  STAGED_MESH_LIVE_CONNECTION_POLICY mentions run_live_mesh_session.
   E9.  STAGED_MESH_ROLE_DOWNGRADE_POLICY mentions 'deferred'.
   E10. get_staged_mesh_role() returns 'main_chain_live_execution'.
   E11. verify_staged_mesh_live_connection() returns a dict.
   E12. verify_staged_mesh_live_connection() live_engine_importable is True.
   E13. verify_staged_mesh_live_connection() run_live_mesh_session_callable is True.
   E14. verify_staged_mesh_live_connection() coordinator_importable is True.
   E15. verify_staged_mesh_live_connection() orchestrator_importable is True.
   E16. verify_staged_mesh_live_connection() role equals 'main_chain_live_execution'.
   E17. verify_staged_mesh_live_connection() is_connected is True.

F. Mesh Live Engine — Staged Mesh Integration
   F1.  LiveMeshRuntimeEngine is importable.
   F2.  run_live_mesh_session is importable and callable.
   F3.  run_live_mesh_session with no participants returns a LiveMeshRunResult.
   F4.  LiveMeshRunResult has outcome, coordinator_state, errors attributes.
   F5.  LiveMeshRunResult.to_dict() includes 'outcome' key.
   F6.  Source dispatch orchestrator sentinel LIVE_MESH_RUNTIME_ENGINE_ORCHESTRATOR_PR_J_SENTINEL importable.
   F7.  LIVE_MESH_STAGED_TO_ACTIVE_DISPATCH_PR_J_POLICY importable and non-empty.
   F8.  LIVE_MESH_RESULT_CONVERGENCE_PR_J_POLICY importable and non-empty.

G. Cross-module consistency
   G1.  UNIFIED_RUNTIME_TRUTH_INGRESS_AUTHORITY contains 'SINGLE_CANONICAL'.
   G2.  SESSION_AUTHORITY_CONTRACT_PR2_SENTINEL contains 'PR2'.
   G3.  STAGED_MESH_ROLE_CONTRACT_PR2_SENTINEL contains 'PR2'.
   G4.  All three modules importable simultaneously without conflict.
   G5.  get_session_authority() and get_session_authority_registry() return same type.
"""

from __future__ import annotations

import unittest


# ===========================================================================
# A. Single Runtime Truth Ingress
# ===========================================================================

class TestUnifiedRuntimeTruthIngressSentinels(unittest.TestCase):
    """Tests A1–A3: Sentinel presence and non-emptiness."""

    def test_A1_authority_importable(self):
        from core.unified_runtime_truth_ingress import (
            UNIFIED_RUNTIME_TRUTH_INGRESS_AUTHORITY,
        )
        self.assertIsInstance(UNIFIED_RUNTIME_TRUTH_INGRESS_AUTHORITY, str)
        self.assertTrue(len(UNIFIED_RUNTIME_TRUTH_INGRESS_AUTHORITY) > 0)

    def test_A2_pr2_sentinel_importable(self):
        from core.unified_runtime_truth_ingress import (
            UNIFIED_RUNTIME_TRUTH_INGRESS_PR2_SENTINEL,
        )
        self.assertIsInstance(UNIFIED_RUNTIME_TRUTH_INGRESS_PR2_SENTINEL, str)
        self.assertTrue(len(UNIFIED_RUNTIME_TRUTH_INGRESS_PR2_SENTINEL) > 0)

    def test_A3_all_policy_sentinels_non_empty(self):
        from core.unified_runtime_truth_ingress import (
            ANDROID_RUNTIME_STATE_MUST_FLOW_THROUGH_INGRESS_POLICY,
            NO_PARALLEL_WRITE_TO_CANONICAL_STATE_POLICY,
            SESSION_AUTHORITY_IS_ATTACHED_REGISTRY_POLICY,
            INGRESS_ROUTES_TO_CORRECT_SUB_PATH_POLICY,
            INGRESS_FAIL_CLOSED_ON_UNKNOWN_TYPE_POLICY,
            INGRESS_IS_GRACEFUL_ON_SUBMODULE_UNAVAILABILITY_POLICY,
        )
        for sentinel in [
            ANDROID_RUNTIME_STATE_MUST_FLOW_THROUGH_INGRESS_POLICY,
            NO_PARALLEL_WRITE_TO_CANONICAL_STATE_POLICY,
            SESSION_AUTHORITY_IS_ATTACHED_REGISTRY_POLICY,
            INGRESS_ROUTES_TO_CORRECT_SUB_PATH_POLICY,
            INGRESS_FAIL_CLOSED_ON_UNKNOWN_TYPE_POLICY,
            INGRESS_IS_GRACEFUL_ON_SUBMODULE_UNAVAILABILITY_POLICY,
        ]:
            with self.subTest(sentinel=sentinel[:30]):
                self.assertIsInstance(sentinel, str)
                self.assertGreater(len(sentinel), 0)


class TestRuntimeTruthIngressOutcome(unittest.TestCase):
    """Tests A4–A5: RuntimeTruthIngressOutcome dataclass."""

    def test_A4_outcome_importable(self):
        from core.unified_runtime_truth_ingress import RuntimeTruthIngressOutcome
        self.assertTrue(callable(RuntimeTruthIngressOutcome))

    def test_A5_to_dict_includes_required_keys(self):
        from core.unified_runtime_truth_ingress import RuntimeTruthIngressOutcome
        outcome = RuntimeTruthIngressOutcome(
            routed_path="handoff",
            was_reconciled=True,
            degraded=False,
            reject_reason="",
            message_type="handoff_result",
        )
        d = outcome.to_dict()
        for key in ("routed_path", "was_reconciled", "degraded", "reject_reason", "message_type"):
            self.assertIn(key, d, f"to_dict() missing key: {key}")


class TestGetSessionAuthority(unittest.TestCase):
    """Test A6: get_session_authority() returns a non-None object."""

    def test_A6_get_session_authority_non_none(self):
        from core.unified_runtime_truth_ingress import get_session_authority
        result = get_session_authority()
        self.assertIsNotNone(result)


class TestIngestRouting(unittest.TestCase):
    """Tests A7–A20: Routing logic of ingest_android_runtime_state_update."""

    def _ingest(self, message):
        from core.unified_runtime_truth_ingress import ingest_android_runtime_state_update
        return ingest_android_runtime_state_update(message)

    def test_A7_handoff_result_routes_to_handoff(self):
        outcome = self._ingest({"type": "handoff_result", "handoff_id": "hid1", "task_id": "t1"})
        self.assertEqual(outcome.routed_path, "handoff")
        self.assertEqual(outcome.message_type, "handoff_result")

    def test_A8_handoff_ack_routes_to_handoff(self):
        outcome = self._ingest({"type": "handoff_ack", "handoff_id": "hid2"})
        self.assertEqual(outcome.routed_path, "handoff")

    def test_A9_handoff_failure_routes_to_handoff(self):
        outcome = self._ingest({"type": "handoff_failure", "handoff_id": "hid3"})
        self.assertEqual(outcome.routed_path, "handoff")

    def test_A10_result_routes_to_execution_signal(self):
        outcome = self._ingest({"type": "result", "task_id": "t2"})
        self.assertEqual(outcome.routed_path, "execution_signal")

    def test_A11_ack_routes_to_execution_signal(self):
        outcome = self._ingest({"type": "ack", "task_id": "t3"})
        self.assertEqual(outcome.routed_path, "execution_signal")

    def test_A12_progress_routes_to_execution_signal(self):
        outcome = self._ingest({"type": "progress", "task_id": "t4"})
        self.assertEqual(outcome.routed_path, "execution_signal")

    def test_A13_error_routes_to_execution_signal(self):
        outcome = self._ingest({"type": "error", "task_id": "t5"})
        self.assertEqual(outcome.routed_path, "execution_signal")

    def test_A14_timeout_routes_to_execution_signal(self):
        outcome = self._ingest({"type": "timeout", "task_id": "t6"})
        self.assertEqual(outcome.routed_path, "execution_signal")

    def test_A15_cancelled_routes_to_execution_signal(self):
        outcome = self._ingest({"type": "cancelled", "task_id": "t7"})
        self.assertEqual(outcome.routed_path, "execution_signal")

    def test_A16_session_snapshot_routes_to_participant_truth(self):
        outcome = self._ingest({
            "type": "session_snapshot",
            "device_id": "dev1",
            "session_id": "sess1",
        })
        self.assertEqual(outcome.routed_path, "participant_truth")

    def test_A17_runtime_state_routes_to_participant_truth(self):
        outcome = self._ingest({
            "type": "runtime_state",
            "device_id": "dev2",
        })
        self.assertEqual(outcome.routed_path, "participant_truth")

    def test_A18_empty_type_no_identity_rejected(self):
        outcome = self._ingest({})
        self.assertEqual(outcome.routed_path, "rejected")
        self.assertFalse(outcome.was_reconciled)

    def test_A19_never_raises_with_bad_input(self):
        from core.unified_runtime_truth_ingress import ingest_android_runtime_state_update
        # Should not raise
        try:
            ingest_android_runtime_state_update({"type": "handoff_result"})
            ingest_android_runtime_state_update({})
            ingest_android_runtime_state_update({"type": ""})
        except Exception as exc:
            self.fail(f"ingest_android_runtime_state_update raised unexpectedly: {exc}")

    def test_A20_returns_outcome_not_none(self):
        from core.unified_runtime_truth_ingress import ingest_android_runtime_state_update
        result = ingest_android_runtime_state_update({"type": "ack", "task_id": "t8"})
        self.assertIsNotNone(result)

    def test_A21_non_dict_input_returns_rejected(self):
        from core.unified_runtime_truth_ingress import ingest_android_runtime_state_update
        try:
            outcome = ingest_android_runtime_state_update("not a dict")  # type: ignore[arg-type]
        except Exception as exc:
            self.fail(f"Should not raise on non-dict: {exc}")
        self.assertEqual(outcome.routed_path, "rejected")


# ===========================================================================
# B. Single Session Authority Contract
# ===========================================================================

class TestSessionAuthorityContractSentinels(unittest.TestCase):
    """Tests B1–B11: Sentinel presence and content."""

    def test_B1_authority_importable(self):
        from core.session_authority_contract import SESSION_AUTHORITY_CONTRACT_AUTHORITY
        self.assertIsInstance(SESSION_AUTHORITY_CONTRACT_AUTHORITY, str)
        self.assertGreater(len(SESSION_AUTHORITY_CONTRACT_AUTHORITY), 0)

    def test_B2_pr2_sentinel_importable(self):
        from core.session_authority_contract import SESSION_AUTHORITY_CONTRACT_PR2_SENTINEL
        self.assertIsInstance(SESSION_AUTHORITY_CONTRACT_PR2_SENTINEL, str)
        self.assertIn("PR2", SESSION_AUTHORITY_CONTRACT_PR2_SENTINEL)

    def test_B3_all_policy_sentinels_non_empty(self):
        from core.session_authority_contract import (
            ATTACHED_SESSION_REGISTRY_IS_SINGLE_SESSION_AUTHORITY_POLICY,
            FLOW_CONTINUITY_COORDINATOR_IS_DECISION_AUTHORITY_POLICY,
            SHARED_IDENTITY_CONTRACT_POLICY,
            RECONNECT_MUST_PRESERVE_RUNTIME_SESSION_ID_POLICY,
            MIGRATION_MUST_USE_REGISTRY_SUPERSESSION_POLICY,
            HANDOFF_IDENTITY_MUST_CORRELATE_TO_REGISTRY_POLICY,
            STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY,
            NO_BYPASS_CONTINUITY_DECISION_POLICY,
        )
        policies = [
            ATTACHED_SESSION_REGISTRY_IS_SINGLE_SESSION_AUTHORITY_POLICY,
            FLOW_CONTINUITY_COORDINATOR_IS_DECISION_AUTHORITY_POLICY,
            SHARED_IDENTITY_CONTRACT_POLICY,
            RECONNECT_MUST_PRESERVE_RUNTIME_SESSION_ID_POLICY,
            MIGRATION_MUST_USE_REGISTRY_SUPERSESSION_POLICY,
            HANDOFF_IDENTITY_MUST_CORRELATE_TO_REGISTRY_POLICY,
            STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY,
            NO_BYPASS_CONTINUITY_DECISION_POLICY,
        ]
        for p in policies:
            with self.subTest(policy=p[:30]):
                self.assertIsInstance(p, str)
                self.assertGreater(len(p), 0)

    def test_B4_registry_policy_mentions_registry(self):
        from core.session_authority_contract import (
            ATTACHED_SESSION_REGISTRY_IS_SINGLE_SESSION_AUTHORITY_POLICY,
        )
        self.assertIn("registry", ATTACHED_SESSION_REGISTRY_IS_SINGLE_SESSION_AUTHORITY_POLICY.lower())

    def test_B5_coordinator_policy_mentions_coordinator(self):
        from core.session_authority_contract import (
            FLOW_CONTINUITY_COORDINATOR_IS_DECISION_AUTHORITY_POLICY,
        )
        self.assertIn("coordinator", FLOW_CONTINUITY_COORDINATOR_IS_DECISION_AUTHORITY_POLICY.lower())

    def test_B6_shared_identity_policy_mentions_runtime_session_id(self):
        from core.session_authority_contract import SHARED_IDENTITY_CONTRACT_POLICY
        self.assertIn("runtime_session_id", SHARED_IDENTITY_CONTRACT_POLICY)

    def test_B7_reconnect_policy_mentions_reconnect_session(self):
        from core.session_authority_contract import (
            RECONNECT_MUST_PRESERVE_RUNTIME_SESSION_ID_POLICY,
        )
        self.assertIn("reconnect_session", RECONNECT_MUST_PRESERVE_RUNTIME_SESSION_ID_POLICY)

    def test_B8_migration_policy_mentions_register_session(self):
        from core.session_authority_contract import (
            MIGRATION_MUST_USE_REGISTRY_SUPERSESSION_POLICY,
        )
        self.assertIn("register_session", MIGRATION_MUST_USE_REGISTRY_SUPERSESSION_POLICY)

    def test_B9_handoff_policy_mentions_session_id(self):
        from core.session_authority_contract import (
            HANDOFF_IDENTITY_MUST_CORRELATE_TO_REGISTRY_POLICY,
        )
        self.assertIn("session_id", HANDOFF_IDENTITY_MUST_CORRELATE_TO_REGISTRY_POLICY)

    def test_B10_stale_identity_policy_mentions_non_destructive(self):
        from core.session_authority_contract import (
            STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY,
        )
        self.assertIn("non-destructive", STALE_IDENTITY_REJECTION_IS_NON_DESTRUCTIVE_POLICY.lower())

    def test_B11_no_bypass_policy_mentions_coordinator(self):
        from core.session_authority_contract import NO_BYPASS_CONTINUITY_DECISION_POLICY
        self.assertIn("FlowContinuityCoordinator", NO_BYPASS_CONTINUITY_DECISION_POLICY)


class TestSessionAuthoritySnapshot(unittest.TestCase):
    """Tests B12–B20: SessionAuthoritySnapshot dataclass and accessors."""

    def test_B12_snapshot_importable(self):
        from core.session_authority_contract import SessionAuthoritySnapshot
        self.assertTrue(callable(SessionAuthoritySnapshot))

    def test_B13_snapshot_to_dict_keys(self):
        from core.session_authority_contract import SessionAuthoritySnapshot
        snap = SessionAuthoritySnapshot()
        d = snap.to_dict()
        for key in (
            "registry_available",
            "coordinator_available",
            "active_session_count",
            "pending_continuity_count",
            "authority_policy_count",
        ):
            self.assertIn(key, d)

    def test_B14_get_session_authority_registry_non_none(self):
        from core.session_authority_contract import get_session_authority_registry
        result = get_session_authority_registry()
        self.assertIsNotNone(result)

    def test_B15_get_continuity_coordinator_non_none(self):
        from core.session_authority_contract import get_continuity_coordinator
        result = get_continuity_coordinator()
        self.assertIsNotNone(result)

    def test_B16_build_snapshot_returns_snapshot(self):
        from core.session_authority_contract import (
            build_session_authority_snapshot,
            SessionAuthoritySnapshot,
        )
        snap = build_session_authority_snapshot()
        self.assertIsInstance(snap, SessionAuthoritySnapshot)

    def test_B17_build_snapshot_never_raises(self):
        from core.session_authority_contract import build_session_authority_snapshot
        try:
            build_session_authority_snapshot()
        except Exception as exc:
            self.fail(f"build_session_authority_snapshot raised: {exc}")

    def test_B18_snapshot_registry_available_true(self):
        from core.session_authority_contract import build_session_authority_snapshot
        snap = build_session_authority_snapshot()
        self.assertTrue(snap.registry_available)

    def test_B19_snapshot_coordinator_available_true(self):
        from core.session_authority_contract import build_session_authority_snapshot
        snap = build_session_authority_snapshot()
        self.assertTrue(snap.coordinator_available)

    def test_B20_snapshot_authority_policy_count_positive(self):
        from core.session_authority_contract import build_session_authority_snapshot
        snap = build_session_authority_snapshot()
        self.assertGreater(snap.authority_policy_count, 0)


# ===========================================================================
# C. Session Authority — Reconnect Identity Preservation
# ===========================================================================

class TestReconnectIdentityPreservation(unittest.TestCase):
    """Tests C1–C6: Reconnect preserves runtime_session_id."""

    def _make_registry(self):
        from core.attached_runtime_session_registry import AttachedSessionRegistry
        return AttachedSessionRegistry()

    def _register(self, registry, device_id, session_id=None):
        from core.attached_runtime_session_registry import register_session
        import uuid
        sid = session_id or str(uuid.uuid4())
        return register_session(device_id=device_id, session_id=sid, registry=registry)

    def _reconnect(self, registry, entry):
        from core.attached_runtime_session_registry import reconnect_session
        return reconnect_session(entry, registry=registry)

    def _detach(self, registry, entry):
        from core.attached_runtime_session_registry import detach_session
        return detach_session(entry, registry=registry)

    def _invalidate(self, registry, entry):
        from core.attached_runtime_session_registry import invalidate_session
        return invalidate_session(entry, registry=registry)

    def test_C1_reconnect_preserves_runtime_session_id(self):
        registry = self._make_registry()
        entry = self._register(registry, "device_C1")
        original_runtime_id = entry.runtime_session_id
        reconnected = self._reconnect(registry, entry)
        self.assertEqual(
            reconnected.runtime_session_id,
            original_runtime_id,
            "reconnect_session MUST preserve runtime_session_id",
        )

    def test_C2_register_session_creates_new_runtime_session_id(self):
        registry = self._make_registry()
        entry1 = self._register(registry, "device_C2")
        entry2 = self._register(registry, "device_C2")
        self.assertNotEqual(
            entry1.runtime_session_id,
            entry2.runtime_session_id,
            "register_session for same device should create a new runtime_session_id",
        )

    def test_C3_two_registers_for_same_device_creates_supersession(self):
        from core.attached_runtime_session_registry import RegistryEntryState
        registry = self._make_registry()
        entry1 = self._register(registry, "device_C3")
        self._register(registry, "device_C3")
        old = registry.get_by_session_id(entry1.session_id, active_only=False)
        self.assertIsNotNone(old)
        self.assertEqual(old.attachment_state, RegistryEntryState.replaced)

    def test_C4_reconnect_on_active_keeps_active_state(self):
        from core.attached_runtime_session_registry import RegistryEntryState
        registry = self._make_registry()
        entry = self._register(registry, "device_C4")
        reconnected = self._reconnect(registry, entry)
        self.assertEqual(reconnected.attachment_state, RegistryEntryState.active)

    def test_C5_detach_then_reconnect_restores_active(self):
        from core.attached_runtime_session_registry import RegistryEntryState
        registry = self._make_registry()
        entry = self._register(registry, "device_C5")
        detached = self._detach(registry, entry)
        reconnected = self._reconnect(registry, detached)
        self.assertEqual(reconnected.attachment_state, RegistryEntryState.active)

    def test_C6_invalidate_makes_entry_terminal(self):
        from core.attached_runtime_session_registry import RegistryEntryState
        registry = self._make_registry()
        entry = self._register(registry, "device_C6")
        invalidated = self._invalidate(registry, entry)
        self.assertEqual(invalidated.attachment_state, RegistryEntryState.invalidated)
        # Further reconnect should be a no-op (still terminal)
        after_reconnect = self._reconnect(registry, invalidated)
        self.assertEqual(
            after_reconnect.attachment_state,
            RegistryEntryState.invalidated,
            "reconnect on invalidated (terminal) entry must be a no-op",
        )


# ===========================================================================
# D. Session Authority — Migration Identity Contract
# ===========================================================================

class TestMigrationIdentityContract(unittest.TestCase):
    """Tests D1–D5: Migration uses registry supersession."""

    def _make_registry(self):
        from core.attached_runtime_session_registry import AttachedSessionRegistry
        return AttachedSessionRegistry()

    def _register(self, registry, device_id):
        from core.attached_runtime_session_registry import register_session
        import uuid
        return register_session(
            device_id=device_id,
            session_id=str(uuid.uuid4()),
            registry=registry,
        )

    def test_D1_register_new_device_no_duplicate_active(self):
        registry = self._make_registry()
        entry1 = self._register(registry, "device_D1")
        entry2 = self._register(registry, "device_D1")
        active_all = registry.list_all_active()
        # Only the newest entry should be active for device_D1
        active_for_device = [
            e for e in active_all if e.device_id == "device_D1"
        ]
        self.assertEqual(len(active_for_device), 1)
        self.assertEqual(active_for_device[0].session_id, entry2.session_id)

    def test_D2_old_entry_is_replaced_after_migration(self):
        from core.attached_runtime_session_registry import RegistryEntryState
        registry = self._make_registry()
        entry1 = self._register(registry, "device_D2")
        self._register(registry, "device_D2")
        old = registry.get_by_session_id(entry1.session_id, active_only=False)
        self.assertIsNotNone(old)
        self.assertEqual(old.attachment_state, RegistryEntryState.replaced)

    def test_D3_lookup_active_returns_none_for_replaced(self):
        from core.attached_runtime_session_registry import lookup_active_session
        registry = self._make_registry()
        entry1 = self._register(registry, "device_D3")
        self._register(registry, "device_D3")
        result = lookup_active_session(entry1.session_id, registry=registry)
        self.assertIsNone(result)

    def test_D4_new_entry_has_different_session_id(self):
        registry = self._make_registry()
        entry1 = self._register(registry, "device_D4")
        entry2 = self._register(registry, "device_D4")
        self.assertNotEqual(entry1.session_id, entry2.session_id)

    def test_D5_old_runtime_session_id_preserved_in_history(self):
        registry = self._make_registry()
        entry1 = self._register(registry, "device_D5")
        old_runtime_id = entry1.runtime_session_id
        self._register(registry, "device_D5")
        # The old entry should still be in the registry with active_only=False
        old_entry = registry.get_by_session_id(entry1.session_id, active_only=False)
        self.assertIsNotNone(old_entry)
        self.assertEqual(old_entry.runtime_session_id, old_runtime_id)


# ===========================================================================
# E. Mesh Role Contract
# ===========================================================================

class TestStagedMeshRoleContractSentinels(unittest.TestCase):
    """Tests E1–E9: Sentinel presence and content."""

    def test_E1_authority_importable(self):
        from core.mesh.staged_mesh_role_contract import STAGED_MESH_ROLE_CONTRACT_AUTHORITY
        self.assertIsInstance(STAGED_MESH_ROLE_CONTRACT_AUTHORITY, str)
        self.assertGreater(len(STAGED_MESH_ROLE_CONTRACT_AUTHORITY), 0)

    def test_E2_pr2_sentinel_importable(self):
        from core.mesh.staged_mesh_role_contract import STAGED_MESH_ROLE_CONTRACT_PR2_SENTINEL
        self.assertIsInstance(STAGED_MESH_ROLE_CONTRACT_PR2_SENTINEL, str)
        self.assertIn("PR2", STAGED_MESH_ROLE_CONTRACT_PR2_SENTINEL)

    def test_E3_main_chain_role_is_live_execution(self):
        from core.mesh.staged_mesh_role_contract import STAGED_MESH_MAIN_CHAIN_ROLE
        self.assertEqual(STAGED_MESH_MAIN_CHAIN_ROLE, "main_chain_live_execution")

    def test_E4_is_connected_to_live_engine_is_true(self):
        from core.mesh.staged_mesh_role_contract import STAGED_MESH_IS_CONNECTED_TO_LIVE_ENGINE
        self.assertTrue(STAGED_MESH_IS_CONNECTED_TO_LIVE_ENGINE)

    def test_E5_live_engine_module_references_correct_path(self):
        from core.mesh.staged_mesh_role_contract import STAGED_MESH_LIVE_ENGINE_MODULE
        self.assertIn("live_mesh_runtime_engine", STAGED_MESH_LIVE_ENGINE_MODULE)

    def test_E6_orchestrator_module_references_correct_path(self):
        from core.mesh.staged_mesh_role_contract import STAGED_MESH_ORCHESTRATOR_MODULE
        self.assertIn("source_dispatch_orchestrator", STAGED_MESH_ORCHESTRATOR_MODULE)

    def test_E7_all_policy_sentinels_non_empty(self):
        from core.mesh.staged_mesh_role_contract import (
            STAGED_MESH_LIVE_CONNECTION_POLICY,
            STAGED_MESH_ROLE_DOWNGRADE_POLICY,
            STAGED_MESH_RESULT_SHAPE_POLICY,
            STAGED_MESH_GRACEFUL_DEGRADATION_POLICY,
        )
        for p in [
            STAGED_MESH_LIVE_CONNECTION_POLICY,
            STAGED_MESH_ROLE_DOWNGRADE_POLICY,
            STAGED_MESH_RESULT_SHAPE_POLICY,
            STAGED_MESH_GRACEFUL_DEGRADATION_POLICY,
        ]:
            with self.subTest(policy=p[:30]):
                self.assertIsInstance(p, str)
                self.assertGreater(len(p), 0)

    def test_E8_live_connection_policy_mentions_run_live_mesh_session(self):
        from core.mesh.staged_mesh_role_contract import STAGED_MESH_LIVE_CONNECTION_POLICY
        self.assertIn("run_live_mesh_session", STAGED_MESH_LIVE_CONNECTION_POLICY)

    def test_E9_downgrade_policy_mentions_deferred(self):
        from core.mesh.staged_mesh_role_contract import STAGED_MESH_ROLE_DOWNGRADE_POLICY
        self.assertIn("deferred", STAGED_MESH_ROLE_DOWNGRADE_POLICY)


class TestStagedMeshRoleHelpers(unittest.TestCase):
    """Tests E10–E17: Role helper functions."""

    def test_E10_get_staged_mesh_role_returns_live_execution(self):
        from core.mesh.staged_mesh_role_contract import get_staged_mesh_role
        self.assertEqual(get_staged_mesh_role(), "main_chain_live_execution")

    def test_E11_verify_returns_dict(self):
        from core.mesh.staged_mesh_role_contract import verify_staged_mesh_live_connection
        result = verify_staged_mesh_live_connection()
        self.assertIsInstance(result, dict)

    def test_E12_live_engine_importable(self):
        from core.mesh.staged_mesh_role_contract import verify_staged_mesh_live_connection
        result = verify_staged_mesh_live_connection()
        self.assertTrue(result.get("live_engine_importable"), result.get("errors"))

    def test_E13_run_live_mesh_session_callable(self):
        from core.mesh.staged_mesh_role_contract import verify_staged_mesh_live_connection
        result = verify_staged_mesh_live_connection()
        self.assertTrue(result.get("run_live_mesh_session_callable"), result.get("errors"))

    def test_E14_coordinator_importable(self):
        from core.mesh.staged_mesh_role_contract import verify_staged_mesh_live_connection
        result = verify_staged_mesh_live_connection()
        self.assertTrue(result.get("coordinator_importable"), result.get("errors"))

    def test_E15_orchestrator_importable(self):
        from core.mesh.staged_mesh_role_contract import verify_staged_mesh_live_connection
        result = verify_staged_mesh_live_connection()
        self.assertTrue(result.get("orchestrator_importable"), result.get("errors"))

    def test_E16_verify_role_is_main_chain_live_execution(self):
        from core.mesh.staged_mesh_role_contract import verify_staged_mesh_live_connection
        result = verify_staged_mesh_live_connection()
        self.assertEqual(result.get("role"), "main_chain_live_execution")

    def test_E17_verify_is_connected_is_true(self):
        from core.mesh.staged_mesh_role_contract import verify_staged_mesh_live_connection
        result = verify_staged_mesh_live_connection()
        self.assertTrue(result.get("is_connected"))


# ===========================================================================
# F. Mesh Live Engine — Staged Mesh Integration
# ===========================================================================

class TestMeshLiveEngineIntegration(unittest.TestCase):
    """Tests F1–F8: Live mesh engine importability and basic functionality."""

    def test_F1_live_mesh_runtime_engine_importable(self):
        from core.mesh.live_mesh_runtime_engine import LiveMeshRuntimeEngine
        self.assertTrue(callable(LiveMeshRuntimeEngine))

    def test_F2_run_live_mesh_session_importable_callable(self):
        from core.mesh.live_mesh_runtime_engine import run_live_mesh_session
        self.assertTrue(callable(run_live_mesh_session))

    def test_F3_run_with_no_participants_returns_result(self):
        from core.mesh.live_mesh_runtime_engine import run_live_mesh_session
        # Create a minimal coordinator state using the coordinator module
        try:
            from core.mesh.mesh_session_coordinator import coordinate_mesh_session
            coord_state = coordinate_mesh_session(
                mesh_session={"mesh_id": "test-mesh-F3", "participants": []},
                trace_id="trace_F3",
                task_id="task_F3",
                session_id="session_F3",
                mesh_id="test-mesh-F3",
            )
        except Exception:
            coord_state = None

        result = run_live_mesh_session(
            coord_state,
            participant_results={},
            metadata={"trace_id": "trace_F3", "task_id": "task_F3"},
        )
        self.assertIsNotNone(result)

    def test_F4_live_mesh_run_result_has_required_attributes(self):
        from core.mesh.live_mesh_runtime_engine import LiveMeshRunResult
        # Construct with minimal fields
        result = LiveMeshRunResult(
            outcome="failure",
            coordinator_state=None,
            errors=["promotion_failed"],
        )
        self.assertTrue(hasattr(result, "outcome"))
        self.assertTrue(hasattr(result, "coordinator_state"))
        self.assertTrue(hasattr(result, "errors"))

    def test_F5_live_mesh_run_result_to_dict_has_outcome(self):
        from core.mesh.live_mesh_runtime_engine import LiveMeshRunResult
        result = LiveMeshRunResult(outcome="failure", coordinator_state=None, errors=[])
        d = result.to_dict()
        self.assertIn("outcome", d)

    def test_F6_orchestrator_pr_j_sentinel_importable(self):
        from core.runtime.source_dispatch_orchestrator import (
            LIVE_MESH_RUNTIME_ENGINE_ORCHESTRATOR_PR_J_SENTINEL,
        )
        self.assertIsInstance(LIVE_MESH_RUNTIME_ENGINE_ORCHESTRATOR_PR_J_SENTINEL, str)
        self.assertGreater(len(LIVE_MESH_RUNTIME_ENGINE_ORCHESTRATOR_PR_J_SENTINEL), 0)

    def test_F7_live_mesh_staged_to_active_dispatch_policy_importable(self):
        from core.runtime.source_dispatch_orchestrator import (
            LIVE_MESH_STAGED_TO_ACTIVE_DISPATCH_PR_J_POLICY,
        )
        self.assertIsInstance(LIVE_MESH_STAGED_TO_ACTIVE_DISPATCH_PR_J_POLICY, str)
        self.assertGreater(len(LIVE_MESH_STAGED_TO_ACTIVE_DISPATCH_PR_J_POLICY), 0)

    def test_F8_live_mesh_result_convergence_policy_importable(self):
        from core.runtime.source_dispatch_orchestrator import (
            LIVE_MESH_RESULT_CONVERGENCE_PR_J_POLICY,
        )
        self.assertIsInstance(LIVE_MESH_RESULT_CONVERGENCE_PR_J_POLICY, str)
        self.assertGreater(len(LIVE_MESH_RESULT_CONVERGENCE_PR_J_POLICY), 0)


# ===========================================================================
# G. Cross-module consistency
# ===========================================================================

class TestCrossModuleConsistency(unittest.TestCase):
    """Tests G1–G5: All three PR-2 modules are consistent with each other."""

    def test_G1_truth_ingress_authority_contains_single_canonical(self):
        from core.unified_runtime_truth_ingress import UNIFIED_RUNTIME_TRUTH_INGRESS_AUTHORITY
        self.assertIn("SINGLE_CANONICAL", UNIFIED_RUNTIME_TRUTH_INGRESS_AUTHORITY)

    def test_G2_session_contract_sentinel_contains_pr2(self):
        from core.session_authority_contract import SESSION_AUTHORITY_CONTRACT_PR2_SENTINEL
        self.assertIn("PR2", SESSION_AUTHORITY_CONTRACT_PR2_SENTINEL)

    def test_G3_mesh_role_sentinel_contains_pr2(self):
        from core.mesh.staged_mesh_role_contract import STAGED_MESH_ROLE_CONTRACT_PR2_SENTINEL
        self.assertIn("PR2", STAGED_MESH_ROLE_CONTRACT_PR2_SENTINEL)

    def test_G4_all_three_modules_importable_simultaneously(self):
        try:
            import core.unified_runtime_truth_ingress  # noqa: F401
            import core.session_authority_contract  # noqa: F401
            import core.mesh.staged_mesh_role_contract  # noqa: F401
        except Exception as exc:
            self.fail(f"Import conflict between PR-2 modules: {exc}")

    def test_G5_get_session_authority_and_registry_return_same_type(self):
        from core.unified_runtime_truth_ingress import get_session_authority
        from core.session_authority_contract import get_session_authority_registry
        auth = get_session_authority()
        reg = get_session_authority_registry()
        self.assertIsNotNone(auth)
        self.assertIsNotNone(reg)
        self.assertIs(type(auth), type(reg))


if __name__ == "__main__":
    unittest.main()
