#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr_canonical_authoritative_path_convergence.py
===========================================================

PR-convergence — Enforce Single Authoritative Path and Default-Off Legacy
Behavior.

Validates that:
  1. core.canonical_authoritative_path_convergence is importable and exports
     all required public symbols.
  2. CANONICAL_PATH_INVENTORY is non-empty and contains the canonical dispatch
     spine entries.
  3. CanonicalPathRole has the five required values.
  4. is_legacy_default_off() returns True for deprecated_live and fully_blocked
     paths and False for canonical paths.
  5. get_path_role() returns the correct role for registered paths.
  6. enforce_canonical_selection() produces a CanonicalSelectionRecord with
     enforcement_active=True when legacy paths are present.
  7. enforce_canonical_selection() produces enforcement_active=False when no
     legacy paths are present and the canonical path is selected.
  8. build_convergence_audit_snapshot() produces a ConvergenceAuditSnapshot
     with convergence_healthy=True.
  9. The audit snapshot has at least one canonical path, at least one
     deprecated_live path, and at least one fully_blocked path.
 10. The audit snapshot's default_off_paths list is non-empty.
 11. The audit snapshot's observation_only_paths list is non-empty.
 12. The audit snapshot's android_compat_influence_paths list is non-empty.
 13. Policy sentinels are all non-empty strings.
 14. DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY contains "POLICY::" prefix.
 15. CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_PR_SENTINEL contains
     "PR-convergence".
 16. PURGE_REGISTRY contains PR-convergence entries.
 17. Legacy dispatch paths classified as deprecated_live in the inventory are
     also present in LEGACY_PATH_REGISTRY.
 18. Android compat influence paths all have android_compat_influence=True.
 19. Observation-only paths have role=observation_only (not canonical).
 20. Fully blocked paths are default-off.
 21. Unregistered path_id returns is_legacy_default_off=True (safe default).
 22. Unregistered path_id returns get_path_role=None.
 23. LEGACY_ORCHESTRATOR_PATHS shim contains all PR-convergence registry keys.
 24. CanonicalSelectionRecord.to_dict() is JSON-serialisable (all primitive
     values).
 25. ConvergenceAuditSnapshot.to_dict() is JSON-serialisable.

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ===========================================================================
# 1. Module importable and public symbols exported
# ===========================================================================

class TestModuleImportable:
    """core.canonical_authoritative_path_convergence is importable."""

    def test_module_importable(self):
        import core.canonical_authoritative_path_convergence  # noqa: F401

    def test_authority_sentinel_exported(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_AUTHORITY,
        )
        assert CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_AUTHORITY

    def test_pr_sentinel_exported(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_PR_SENTINEL,
        )
        assert CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_PR_SENTINEL

    def test_path_inventory_exported(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
        )
        assert CANONICAL_PATH_INVENTORY is not None

    def test_enum_exported(self):
        from core.canonical_authoritative_path_convergence import CanonicalPathRole
        assert CanonicalPathRole is not None

    def test_enforce_canonical_selection_exported(self):
        from core.canonical_authoritative_path_convergence import (
            enforce_canonical_selection,
        )
        assert callable(enforce_canonical_selection)

    def test_build_convergence_audit_snapshot_exported(self):
        from core.canonical_authoritative_path_convergence import (
            build_convergence_audit_snapshot,
        )
        assert callable(build_convergence_audit_snapshot)

    def test_is_legacy_default_off_exported(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert callable(is_legacy_default_off)

    def test_get_path_role_exported(self):
        from core.canonical_authoritative_path_convergence import get_path_role
        assert callable(get_path_role)


# ===========================================================================
# 2. CANONICAL_PATH_INVENTORY is non-empty and has canonical entries
# ===========================================================================

class TestCanonicalPathInventory:
    """CANONICAL_PATH_INVENTORY is populated with the expected entries."""

    def test_inventory_non_empty(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
        )
        assert len(CANONICAL_PATH_INVENTORY) >= 10

    def test_command_router_in_inventory(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
            CanonicalPathRole,
        )
        entry = CANONICAL_PATH_INVENTORY.get(
            "core.command_router.CommandRouter.route_envelope"
        )
        assert entry is not None
        assert entry.role == CanonicalPathRole.canonical

    def test_process_user_input_canonical(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
            CanonicalPathRole,
        )
        entry = CANONICAL_PATH_INVENTORY.get(
            "core.e2e_orchestrator.process_user_input"
        )
        assert entry is not None
        assert entry.role == CanonicalPathRole.canonical

    def test_device_router_route_task_canonical(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
            CanonicalPathRole,
        )
        entry = CANONICAL_PATH_INVENTORY.get(
            "galaxy_gateway.device_router.DeviceRouter.route_task"
        )
        assert entry is not None
        assert entry.role == CanonicalPathRole.canonical

    def test_participant_truth_ingress_canonical(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
            CanonicalPathRole,
        )
        entry = CANONICAL_PATH_INVENTORY.get(
            "core.android_participant_truth_ingress"
            ".ingest_android_participant_truth_message"
        )
        assert entry is not None
        assert entry.role == CanonicalPathRole.canonical

    def test_task_router_deprecated_live(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
            CanonicalPathRole,
        )
        entry = CANONICAL_PATH_INVENTORY.get(
            "galaxy_gateway.task_router.TaskRouter"
        )
        assert entry is not None
        assert entry.role == CanonicalPathRole.deprecated_live

    def test_all_entries_have_path_id(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
        )
        for path_id, entry in CANONICAL_PATH_INVENTORY.items():
            assert path_id == entry.path_id, (
                f"path_id key mismatch: key={path_id!r} entry.path_id={entry.path_id!r}"
            )

    def test_all_entries_have_description(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
        )
        for entry in CANONICAL_PATH_INVENTORY.values():
            assert entry.description, (
                f"Missing description on entry {entry.path_id!r}"
            )


# ===========================================================================
# 3. CanonicalPathRole has five required values
# ===========================================================================

class TestCanonicalPathRoleValues:
    """CanonicalPathRole has exactly the five required values."""

    _REQUIRED = {
        "canonical",
        "compat_allowed",
        "observation_only",
        "deprecated_live",
        "fully_blocked",
    }

    def test_all_required_values_present(self):
        from core.canonical_authoritative_path_convergence import CanonicalPathRole
        actual = {member.value for member in CanonicalPathRole}
        assert self._REQUIRED <= actual, (
            f"Missing CanonicalPathRole values: {self._REQUIRED - actual}"
        )


# ===========================================================================
# 4. is_legacy_default_off()
# ===========================================================================

class TestIsLegacyDefaultOff:
    """is_legacy_default_off returns correct values for known paths."""

    def test_deprecated_live_is_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off("galaxy_gateway.task_router.TaskRouter") is True

    def test_fully_blocked_is_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "galaxy_gateway.task_router.TaskRouter.direct_http_dispatch"
        ) is True

    def test_canonical_is_not_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "core.command_router.CommandRouter.route_envelope"
        ) is False

    def test_compat_allowed_is_not_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "core.android_execution_signal_reconciler.compat_extract_signal_kind"
        ) is False

    def test_observation_only_is_not_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "core.android_delegated_runtime_audit.AndroidDelegatedRuntimeAuditRecord"
        ) is False

    def test_unregistered_path_is_default_off(self):
        """Unclassified paths are treated as default-off (safe default)."""
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "some.completely.unknown.path.that.is.not.in.inventory"
        ) is True

    def test_smart_transport_router_is_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "galaxy_gateway.smart_transport_router.SmartTransportRouter"
        ) is True

    def test_enhanced_nlu_v2_is_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "galaxy_gateway.enhanced_nlu_v2.EnhancedNLUEngineV2"
        ) is True

    def test_session_roaming_manager_is_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "galaxy_gateway.session_roaming.SessionRoamingManager"
        ) is True

    def test_task_decomposer_is_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "galaxy_gateway.task_decomposer.TaskDecomposer"
        ) is True

    def test_message_handler_is_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "galaxy_gateway.handlers.message_handler.MessageHandler"
        ) is True


# ===========================================================================
# 5. get_path_role()
# ===========================================================================

class TestGetPathRole:
    """get_path_role returns the correct role for known paths."""

    def test_canonical_path_returns_canonical(self):
        from core.canonical_authoritative_path_convergence import (
            get_path_role,
            CanonicalPathRole,
        )
        role = get_path_role("core.command_router.CommandRouter.route_envelope")
        assert role == CanonicalPathRole.canonical

    def test_deprecated_live_returns_deprecated_live(self):
        from core.canonical_authoritative_path_convergence import (
            get_path_role,
            CanonicalPathRole,
        )
        role = get_path_role("galaxy_gateway.task_router.TaskRouter")
        assert role == CanonicalPathRole.deprecated_live

    def test_fully_blocked_returns_fully_blocked(self):
        from core.canonical_authoritative_path_convergence import (
            get_path_role,
            CanonicalPathRole,
        )
        role = get_path_role(
            "core.android_participant_truth_ingress"
            ".direct_canonical_state_write_from_compat_signal"
        )
        assert role == CanonicalPathRole.fully_blocked

    def test_observation_only_returns_observation_only(self):
        from core.canonical_authoritative_path_convergence import (
            get_path_role,
            CanonicalPathRole,
        )
        role = get_path_role(
            "core.android_delegated_runtime_audit.AndroidDelegatedRuntimeAuditRecord"
        )
        assert role == CanonicalPathRole.observation_only

    def test_compat_allowed_returns_compat_allowed(self):
        from core.canonical_authoritative_path_convergence import (
            get_path_role,
            CanonicalPathRole,
        )
        role = get_path_role(
            "core.android_execution_signal_reconciler.compat_extract_signal_kind"
        )
        assert role == CanonicalPathRole.compat_allowed

    def test_unregistered_path_returns_none(self):
        from core.canonical_authoritative_path_convergence import get_path_role
        role = get_path_role("some.totally.unknown.path")
        assert role is None


# ===========================================================================
# 6 & 7. enforce_canonical_selection()
# ===========================================================================

class TestEnforceCanonicalSelection:
    """enforce_canonical_selection produces correct CanonicalSelectionRecord."""

    def test_produces_record(self):
        from core.canonical_authoritative_path_convergence import (
            enforce_canonical_selection,
            CanonicalSelectionRecord,
        )
        record = enforce_canonical_selection(
            "core.command_router.CommandRouter.route_envelope",
            calling_site="test_site",
        )
        assert isinstance(record, CanonicalSelectionRecord)

    def test_enforcement_active_true_when_legacy_present(self):
        from core.canonical_authoritative_path_convergence import (
            enforce_canonical_selection,
        )
        record = enforce_canonical_selection(
            "core.command_router.CommandRouter.route_envelope",
            calling_site="test_dispatch_surface",
            legacy_paths_present=[
                "galaxy_gateway.task_router.TaskRouter",
                "galaxy_gateway.handlers.message_handler.MessageHandler",
            ],
        )
        assert record.enforcement_active is True

    def test_enforcement_active_false_when_no_legacy(self):
        from core.canonical_authoritative_path_convergence import (
            enforce_canonical_selection,
        )
        record = enforce_canonical_selection(
            "core.command_router.CommandRouter.route_envelope",
            calling_site="test_dispatch_surface",
            legacy_paths_present=[],
        )
        assert record.enforcement_active is False

    def test_selected_path_set_correctly(self):
        from core.canonical_authoritative_path_convergence import (
            enforce_canonical_selection,
        )
        record = enforce_canonical_selection(
            "core.e2e_orchestrator.process_user_input",
            calling_site="user_request_surface",
        )
        assert record.selected_path == "core.e2e_orchestrator.process_user_input"

    def test_calling_site_set_correctly(self):
        from core.canonical_authoritative_path_convergence import (
            enforce_canonical_selection,
        )
        record = enforce_canonical_selection(
            "core.command_router.CommandRouter.route_envelope",
            calling_site="my_dispatch_site",
        )
        assert record.calling_site == "my_dispatch_site"

    def test_legacy_paths_recorded_in_record(self):
        from core.canonical_authoritative_path_convergence import (
            enforce_canonical_selection,
        )
        legacy = [
            "galaxy_gateway.task_router.TaskRouter",
            "galaxy_gateway.task_decomposer.TaskDecomposer",
        ]
        record = enforce_canonical_selection(
            "core.command_router.CommandRouter.route_envelope",
            calling_site="dispatch_surface",
            legacy_paths_present=legacy,
        )
        assert set(legacy) == set(record.legacy_paths_present)

    def test_record_has_unique_id(self):
        from core.canonical_authoritative_path_convergence import (
            enforce_canonical_selection,
        )
        r1 = enforce_canonical_selection(
            "core.command_router.CommandRouter.route_envelope",
            calling_site="site1",
        )
        r2 = enforce_canonical_selection(
            "core.command_router.CommandRouter.route_envelope",
            calling_site="site2",
        )
        assert r1.record_id != r2.record_id


# ===========================================================================
# 8 & 9. build_convergence_audit_snapshot()
# ===========================================================================

class TestConvergenceAuditSnapshot:
    """build_convergence_audit_snapshot produces the expected snapshot."""

    def test_snapshot_is_healthy(self):
        from core.canonical_authoritative_path_convergence import (
            build_convergence_audit_snapshot,
        )
        snapshot = build_convergence_audit_snapshot()
        assert snapshot.convergence_healthy is True

    def test_canonical_count_at_least_one(self):
        from core.canonical_authoritative_path_convergence import (
            build_convergence_audit_snapshot,
        )
        snapshot = build_convergence_audit_snapshot()
        assert snapshot.canonical_count >= 1

    def test_deprecated_live_count_at_least_one(self):
        from core.canonical_authoritative_path_convergence import (
            build_convergence_audit_snapshot,
        )
        snapshot = build_convergence_audit_snapshot()
        assert snapshot.deprecated_live_count >= 1

    def test_fully_blocked_count_at_least_one(self):
        from core.canonical_authoritative_path_convergence import (
            build_convergence_audit_snapshot,
        )
        snapshot = build_convergence_audit_snapshot()
        assert snapshot.fully_blocked_count >= 1

    def test_default_off_paths_non_empty(self):
        from core.canonical_authoritative_path_convergence import (
            build_convergence_audit_snapshot,
        )
        snapshot = build_convergence_audit_snapshot()
        assert len(snapshot.default_off_paths) >= 1

    def test_observation_only_paths_non_empty(self):
        from core.canonical_authoritative_path_convergence import (
            build_convergence_audit_snapshot,
        )
        snapshot = build_convergence_audit_snapshot()
        assert len(snapshot.observation_only_paths) >= 1

    def test_android_compat_influence_paths_non_empty(self):
        from core.canonical_authoritative_path_convergence import (
            build_convergence_audit_snapshot,
        )
        snapshot = build_convergence_audit_snapshot()
        assert len(snapshot.android_compat_influence_paths) >= 1

    def test_policy_sentinels_non_empty(self):
        from core.canonical_authoritative_path_convergence import (
            build_convergence_audit_snapshot,
        )
        snapshot = build_convergence_audit_snapshot()
        assert len(snapshot.policy_sentinels) >= 1
        for s in snapshot.policy_sentinels:
            assert isinstance(s, str) and s.strip()

    def test_total_paths_consistent(self):
        from core.canonical_authoritative_path_convergence import (
            build_convergence_audit_snapshot,
        )
        snapshot = build_convergence_audit_snapshot()
        total = (
            snapshot.canonical_count
            + snapshot.compat_allowed_count
            + snapshot.observation_only_count
            + snapshot.deprecated_live_count
            + snapshot.fully_blocked_count
        )
        assert total == snapshot.total_paths


# ===========================================================================
# 13 & 14. Policy sentinels
# ===========================================================================

class TestPolicySentinels:
    """Policy sentinels are present and have the required format."""

    def test_default_off_policy_has_prefix(self):
        from core.canonical_authoritative_path_convergence import (
            DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY,
        )
        assert DEFAULT_OFF_LEGACY_BEHAVIOR_POLICY.startswith("POLICY::")

    def test_canonical_path_policy_has_prefix(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_IS_DEFAULT_AUTHORITY_POLICY,
        )
        assert CANONICAL_PATH_IS_DEFAULT_AUTHORITY_POLICY.startswith("POLICY::")

    def test_legacy_must_not_mutate_policy_has_prefix(self):
        from core.canonical_authoritative_path_convergence import (
            LEGACY_PATH_MUST_NOT_MUTATE_CANONICAL_STATE_POLICY,
        )
        assert LEGACY_PATH_MUST_NOT_MUTATE_CANONICAL_STATE_POLICY.startswith("POLICY::")

    def test_observation_only_policy_has_prefix(self):
        from core.canonical_authoritative_path_convergence import (
            OBSERVATION_ONLY_PATH_IS_NON_AUTHORITATIVE_POLICY,
        )
        assert OBSERVATION_ONLY_PATH_IS_NON_AUTHORITATIVE_POLICY.startswith("POLICY::")

    def test_android_compat_policy_has_prefix(self):
        from core.canonical_authoritative_path_convergence import (
            ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY,
        )
        assert ANDROID_COMPAT_INFLUENCE_MUST_PASS_INGRESS_GATE_POLICY.startswith(
            "POLICY::"
        )


# ===========================================================================
# 15. PR sentinel contains "PR-convergence"
# ===========================================================================

class TestPRSentinel:
    """CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_PR_SENTINEL contains PR-convergence."""

    def test_pr_sentinel_contains_pr_convergence(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_PR_SENTINEL,
        )
        assert "PR-convergence" in CANONICAL_AUTHORITATIVE_PATH_CONVERGENCE_PR_SENTINEL


# ===========================================================================
# 16. PURGE_REGISTRY contains PR-convergence entries
# ===========================================================================

class TestPurgeRegistryPRConvergence:
    """PURGE_REGISTRY contains PR-convergence entries."""

    def test_pr_convergence_entries_present(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        pr_convergence_entries = [e for e in PURGE_REGISTRY if e.pr == "PR-convergence"]
        assert len(pr_convergence_entries) >= 1, (
            "PURGE_REGISTRY must have at least one PR-convergence entry"
        )

    def test_canonical_path_inventory_entry_present(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        paths = [e.asset_path for e in PURGE_REGISTRY if e.pr == "PR-convergence"]
        assert any("CANONICAL_PATH_INVENTORY" in p for p in paths), (
            "PURGE_REGISTRY must have a PR-convergence entry for CANONICAL_PATH_INVENTORY"
        )

    def test_android_compat_policy_entry_present(self):
        from core.legacy_purge_registry import PURGE_REGISTRY
        paths = [e.asset_path for e in PURGE_REGISTRY if e.pr == "PR-convergence"]
        assert any("ANDROID_COMPAT" in p for p in paths), (
            "PURGE_REGISTRY must have a PR-convergence entry for Android compat policy"
        )

    def test_all_pr_convergence_entries_have_wrapper_hardened_status(self):
        from core.legacy_purge_registry import PURGE_REGISTRY, PurgeStatus
        for entry in PURGE_REGISTRY:
            if entry.pr == "PR-convergence":
                assert entry.status == PurgeStatus.WRAPPER_HARDENED, (
                    f"PR-convergence entry {entry.asset_path!r} should have "
                    f"WRAPPER_HARDENED status"
                )


# ===========================================================================
# 17. Deprecated_live paths are also in LEGACY_PATH_REGISTRY
# ===========================================================================

class TestDeprecatedLiveInLegacyRegistry:
    """deprecated_live paths in CANONICAL_PATH_INVENTORY appear in LEGACY_PATH_REGISTRY."""

    _DEPRECATED_LIVE_PATHS_EXPECTED_IN_REGISTRY = [
        "galaxy_gateway.task_router.TaskRouter",
        "galaxy_gateway.handlers.message_handler.MessageHandler",
        "galaxy_gateway.task_decomposer.TaskDecomposer",
        "galaxy_gateway.task_decomposer.IntelligentTaskPlanner",
        "galaxy_gateway.smart_transport_router.SmartTransportRouter",
        "galaxy_gateway.enhanced_nlu_v2.EnhancedNLUEngineV2",
        "galaxy_gateway.session_roaming.SessionRoamingManager",
    ]

    def test_task_router_in_legacy_registry(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert "galaxy_gateway.task_router.TaskRouter" in LEGACY_PATH_REGISTRY

    def test_message_handler_in_legacy_registry(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.handlers.message_handler.MessageHandler"
            in LEGACY_PATH_REGISTRY
        )

    def test_task_decomposer_in_legacy_registry(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert "galaxy_gateway.task_decomposer.TaskDecomposer" in LEGACY_PATH_REGISTRY

    def test_intelligent_task_planner_in_legacy_registry(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.task_decomposer.IntelligentTaskPlanner"
            in LEGACY_PATH_REGISTRY
        )

    def test_smart_transport_router_in_legacy_registry(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.smart_transport_router.SmartTransportRouter"
            in LEGACY_PATH_REGISTRY
        )

    def test_enhanced_nlu_v2_in_legacy_registry(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.enhanced_nlu_v2.EnhancedNLUEngineV2"
            in LEGACY_PATH_REGISTRY
        )

    def test_session_roaming_manager_in_legacy_registry(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert (
            "galaxy_gateway.session_roaming.SessionRoamingManager"
            in LEGACY_PATH_REGISTRY
        )


# ===========================================================================
# 18. Android compat influence paths have android_compat_influence=True
# ===========================================================================

class TestAndroidCompatInfluence:
    """All android_compat_influence_paths have android_compat_influence=True."""

    def test_android_compat_influence_paths_all_flagged(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
        )
        snapshot_paths = [
            e.path_id for e in CANONICAL_PATH_INVENTORY.values()
            if e.android_compat_influence
        ]
        for path_id in snapshot_paths:
            entry = CANONICAL_PATH_INVENTORY[path_id]
            assert entry.android_compat_influence is True, (
                f"Path {path_id!r} should have android_compat_influence=True"
            )

    def test_participant_truth_ingress_android_flagged(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
        )
        entry = CANONICAL_PATH_INVENTORY.get(
            "core.android_participant_truth_ingress"
            ".ingest_android_participant_truth_message"
        )
        assert entry is not None
        assert entry.android_compat_influence is True

    def test_blocked_android_path_android_flagged(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
        )
        entry = CANONICAL_PATH_INVENTORY.get(
            "core.android_participant_truth_ingress"
            ".direct_canonical_state_write_from_compat_signal"
        )
        assert entry is not None
        assert entry.android_compat_influence is True


# ===========================================================================
# 19. Observation-only paths have role=observation_only (not canonical)
# ===========================================================================

class TestObservationOnlyNonCanonical:
    """Observation-only paths are classified as observation_only, not canonical."""

    def test_audit_record_is_observation_only(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
            CanonicalPathRole,
        )
        entry = CANONICAL_PATH_INVENTORY.get(
            "core.android_delegated_runtime_audit.AndroidDelegatedRuntimeAuditRecord"
        )
        assert entry is not None
        assert entry.role == CanonicalPathRole.observation_only
        assert entry.role != CanonicalPathRole.canonical

    def test_operator_surface_is_observation_only(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
            CanonicalPathRole,
        )
        entry = CANONICAL_PATH_INVENTORY.get("core.operator_surface.OperatorSurface")
        assert entry is not None
        assert entry.role == CanonicalPathRole.observation_only

    def test_replay_foundation_is_observation_only(self):
        from core.canonical_authoritative_path_convergence import (
            CANONICAL_PATH_INVENTORY,
            CanonicalPathRole,
        )
        entry = CANONICAL_PATH_INVENTORY.get("core.replay_foundation.ReplayFoundation")
        assert entry is not None
        assert entry.role == CanonicalPathRole.observation_only


# ===========================================================================
# 20. Fully blocked paths are default-off
# ===========================================================================

class TestFullyBlockedDefaultOff:
    """Fully blocked paths are classified as default-off."""

    def test_fully_blocked_direct_http_dispatch_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "galaxy_gateway.task_router.TaskRouter.direct_http_dispatch"
        ) is True

    def test_fully_blocked_direct_canonical_write_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "core.android_participant_truth_ingress"
            ".direct_canonical_state_write_from_compat_signal"
        ) is True

    def test_fully_blocked_task_orchestrator_direct_dispatch_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        assert is_legacy_default_off(
            "galaxy_gateway.orchestrator.task_orchestrator"
            ".TaskOrchestrator.direct_dispatch"
        ) is True


# ===========================================================================
# 21 & 22. Unregistered path behavior
# ===========================================================================

class TestUnregisteredPath:
    """Unregistered paths are treated as default-off (safe default)."""

    def test_unregistered_is_default_off(self):
        from core.canonical_authoritative_path_convergence import is_legacy_default_off
        result = is_legacy_default_off("not.a.real.path.at.all.xyz")
        assert result is True

    def test_unregistered_role_is_none(self):
        from core.canonical_authoritative_path_convergence import get_path_role
        role = get_path_role("not.a.real.path.at.all.xyz")
        assert role is None


# ===========================================================================
# 23. LEGACY_ORCHESTRATOR_PATHS shim includes PR-convergence registry keys
# ===========================================================================

class TestLegacyOrchestratorPathsShim:
    """LEGACY_ORCHESTRATOR_PATHS shim includes all PR-convergence registry keys."""

    _PR_CONVERGENCE_KEYS = [
        "core.android_participant_truth_ingress.ingest_android_participant_truth_message",
        "core.android_participant_truth_ingress.reconcile_android_participant_truth",
        "core.android_delegated_signal_ingress.ingest_delegated_execution_signal",
        "core.android_execution_signal_reconciler.compat_extract_signal_kind",
        "core.delegated_flow_acceptance_gate.DelegatedFlowAcceptanceGate",
        "core.delegated_flow_readiness_gate.DelegatedFlowReadinessGate",
    ]

    def test_shim_contains_participant_truth_ingress(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "core.android_participant_truth_ingress"
            ".ingest_android_participant_truth_message"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_contains_delegated_signal_ingress(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "core.android_delegated_signal_ingress.ingest_delegated_execution_signal"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_contains_compat_extract_signal_kind(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "core.android_execution_signal_reconciler.compat_extract_signal_kind"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_contains_acceptance_gate(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "core.delegated_flow_acceptance_gate.DelegatedFlowAcceptanceGate"
            in LEGACY_ORCHESTRATOR_PATHS
        )

    def test_shim_contains_readiness_gate(self):
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        assert (
            "core.delegated_flow_readiness_gate.DelegatedFlowReadinessGate"
            in LEGACY_ORCHESTRATOR_PATHS
        )


# ===========================================================================
# 24 & 25. to_dict() is JSON-serialisable
# ===========================================================================

class TestToDict:
    """to_dict() produces JSON-serialisable output."""

    def test_canonical_selection_record_to_dict_serialisable(self):
        from core.canonical_authoritative_path_convergence import (
            enforce_canonical_selection,
        )
        record = enforce_canonical_selection(
            "core.command_router.CommandRouter.route_envelope",
            calling_site="test_site",
            legacy_paths_present=["galaxy_gateway.task_router.TaskRouter"],
        )
        d = record.to_dict()
        # Should not raise
        json_str = json.dumps(d)
        assert json_str

    def test_convergence_audit_snapshot_to_dict_serialisable(self):
        from core.canonical_authoritative_path_convergence import (
            build_convergence_audit_snapshot,
        )
        snapshot = build_convergence_audit_snapshot()
        d = snapshot.to_dict()
        # Should not raise
        json_str = json.dumps(d)
        assert json_str
