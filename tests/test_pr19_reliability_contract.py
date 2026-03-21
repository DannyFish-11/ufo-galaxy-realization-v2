#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr19_reliability_contract.py
==========================================

PR-19 (V4) — Reliability Contract & Delivery Semantics

Tests covering:
1.  DeliveryMode enum — values, serialisation stability
2.  AckStage enum — values, serialisation stability
3.  AckPolicy — construction, to_dict, from_dict round-trip
4.  DeduplicationKey — construction, to_dict, from_dict, has_key
5.  RetryPolicy — construction, to_dict, from_dict, has_retries
6.  TimeoutOwner enum — values, serialisation stability
7.  FallbackOwner enum — values, serialisation stability
8.  Pre-built policy sentinels — field values
9.  Pre-built dedup key sentinels — field values
10. ReliabilitySummary — construction, to_dict, from_dict round-trip
11. UNKNOWN_RELIABILITY_SUMMARY sentinel — field values
12. RELIABILITY_PATH_REGISTRY — all five paths present, required fields
13. get_summary_for_path — known paths, unknown path degradation
14. list_known_paths — returns sorted list, covers all five paths
15. get_reliability_registry_snapshot — shape, total_paths
16. make_reliability_summary — valid inputs, unknown/partial inputs
17. attach_reliability_to_projection — additive, non-mutating
18. Partial/unknown metadata handling — graceful degradation
19. ReliabilitySummary.from_dict — unknown enum values degrade gracefully
20. Introspection/read surface — GET /api/v1/contracts/reliability
21. contract-map integration — reliability endpoint beside planes/messages
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# 1. DeliveryMode enum
# ---------------------------------------------------------------------------


class TestDeliveryMode:
    def test_all_expected_modes_present(self) -> None:
        from core.reliability_contract import DeliveryMode

        expected = {
            "best_effort",
            "at_most_once",
            "at_least_once",
            "dedup_required",
            "exactly_once",
            "unknown",
        }
        actual = {m.value for m in DeliveryMode}
        assert expected == actual

    def test_values_are_strings(self) -> None:
        from core.reliability_contract import DeliveryMode

        for mode in DeliveryMode:
            assert isinstance(mode.value, str)
            assert mode.value  # non-empty

    def test_values_stable(self) -> None:
        from core.reliability_contract import DeliveryMode

        assert DeliveryMode.BEST_EFFORT.value == "best_effort"
        assert DeliveryMode.AT_MOST_ONCE.value == "at_most_once"
        assert DeliveryMode.AT_LEAST_ONCE.value == "at_least_once"
        assert DeliveryMode.DEDUP_REQUIRED.value == "dedup_required"
        assert DeliveryMode.EXACTLY_ONCE.value == "exactly_once"
        assert DeliveryMode.UNKNOWN.value == "unknown"

    def test_is_json_serialisable(self) -> None:
        from core.reliability_contract import DeliveryMode

        serialised = json.dumps([m.value for m in DeliveryMode])
        restored = json.loads(serialised)
        assert set(restored) == {m.value for m in DeliveryMode}

    def test_roundtrip(self) -> None:
        from core.reliability_contract import DeliveryMode

        for mode in DeliveryMode:
            assert DeliveryMode(mode.value) == mode

    def test_description_returns_string(self) -> None:
        from core.reliability_contract import DeliveryMode, delivery_mode_description

        for mode in DeliveryMode:
            desc = delivery_mode_description(mode)
            assert isinstance(desc, str)
            assert len(desc) > 10

    def test_descriptions_dict_covers_all_modes(self) -> None:
        from core.reliability_contract import DeliveryMode, DELIVERY_MODE_DESCRIPTIONS

        for mode in DeliveryMode:
            assert mode.value in DELIVERY_MODE_DESCRIPTIONS


# ---------------------------------------------------------------------------
# 2. AckStage enum
# ---------------------------------------------------------------------------


class TestAckStage:
    def test_all_expected_stages_present(self) -> None:
        from core.reliability_contract import AckStage

        expected = {"no_ack", "accepted_ack", "completed_ack", "unknown"}
        actual = {s.value for s in AckStage}
        assert expected == actual

    def test_values_stable(self) -> None:
        from core.reliability_contract import AckStage

        assert AckStage.NO_ACK.value == "no_ack"
        assert AckStage.ACCEPTED_ACK.value == "accepted_ack"
        assert AckStage.COMPLETED_ACK.value == "completed_ack"
        assert AckStage.UNKNOWN.value == "unknown"

    def test_is_json_serialisable(self) -> None:
        from core.reliability_contract import AckStage

        serialised = json.dumps([s.value for s in AckStage])
        restored = json.loads(serialised)
        assert set(restored) == {s.value for s in AckStage}

    def test_description_returns_string(self) -> None:
        from core.reliability_contract import AckStage, ack_stage_description

        for stage in AckStage:
            desc = ack_stage_description(stage)
            assert isinstance(desc, str)
            assert len(desc) > 5

    def test_descriptions_dict_covers_all_stages(self) -> None:
        from core.reliability_contract import AckStage, ACK_STAGE_DESCRIPTIONS

        for stage in AckStage:
            assert stage.value in ACK_STAGE_DESCRIPTIONS


# ---------------------------------------------------------------------------
# 3. AckPolicy
# ---------------------------------------------------------------------------


class TestAckPolicy:
    def test_default_construction(self) -> None:
        from core.reliability_contract import AckPolicy, AckStage

        policy = AckPolicy()
        assert policy.stage == AckStage.NO_ACK
        assert policy.ack_timeout_hint_ms == 0
        assert policy.ack_required_for_retry is False
        assert policy.schema_version == 1

    def test_to_dict_keys(self) -> None:
        from core.reliability_contract import AckPolicy, AckStage

        policy = AckPolicy(stage=AckStage.ACCEPTED_ACK, ack_timeout_hint_ms=5000)
        d = policy.to_dict()
        assert d["stage"] == "accepted_ack"
        assert d["ack_timeout_hint_ms"] == 5000
        assert "schema_version" in d

    def test_to_dict_is_json_serialisable(self) -> None:
        from core.reliability_contract import ACCEPTED_ACK_POLICY

        serialised = json.dumps(ACCEPTED_ACK_POLICY.to_dict())
        assert "accepted_ack" in serialised

    def test_from_dict_roundtrip(self) -> None:
        from core.reliability_contract import AckPolicy, AckStage

        original = AckPolicy(
            stage=AckStage.COMPLETED_ACK,
            ack_timeout_hint_ms=30_000,
            ack_required_for_retry=True,
            notes="test note",
        )
        restored = AckPolicy.from_dict(original.to_dict())
        assert restored.stage == original.stage
        assert restored.ack_timeout_hint_ms == original.ack_timeout_hint_ms
        assert restored.ack_required_for_retry == original.ack_required_for_retry
        assert restored.notes == original.notes

    def test_from_dict_unknown_stage_degrades(self) -> None:
        from core.reliability_contract import AckPolicy, AckStage

        policy = AckPolicy.from_dict({"stage": "nonexistent_stage"})
        assert policy.stage == AckStage.UNKNOWN

    def test_pre_built_sentinels(self) -> None:
        from core.reliability_contract import (
            NO_ACK_POLICY,
            ACCEPTED_ACK_POLICY,
            COMPLETED_ACK_POLICY,
            AckStage,
        )
        assert NO_ACK_POLICY.stage == AckStage.NO_ACK
        assert ACCEPTED_ACK_POLICY.stage == AckStage.ACCEPTED_ACK
        assert COMPLETED_ACK_POLICY.stage == AckStage.COMPLETED_ACK


# ---------------------------------------------------------------------------
# 4. DeduplicationKey
# ---------------------------------------------------------------------------


class TestDeduplicationKey:
    def test_default_construction(self) -> None:
        from core.reliability_contract import DeduplicationKey

        key = DeduplicationKey()
        assert key.fields == []
        assert key.composition is None
        assert key.enforced is False
        assert not key.has_key()

    def test_has_key_true_when_fields_present(self) -> None:
        from core.reliability_contract import DeduplicationKey

        key = DeduplicationKey(fields=["task_id"])
        assert key.has_key()

    def test_to_dict_keys(self) -> None:
        from core.reliability_contract import DeduplicationKey

        key = DeduplicationKey(
            fields=["task_id", "trace_id"],
            composition="<task_id>:<trace_id>",
            enforced=True,
        )
        d = key.to_dict()
        assert d["fields"] == ["task_id", "trace_id"]
        assert d["composition"] == "<task_id>:<trace_id>"
        assert d["enforced"] is True
        assert "schema_version" in d

    def test_from_dict_roundtrip(self) -> None:
        from core.reliability_contract import DeduplicationKey

        original = DeduplicationKey(
            fields=["task_id", "idempotency_key"],
            composition="<task_id>:<idempotency_key>",
            enforced=True,
            notes="enforced by IdempotencyStore",
        )
        restored = DeduplicationKey.from_dict(original.to_dict())
        assert restored.fields == original.fields
        assert restored.composition == original.composition
        assert restored.enforced == original.enforced
        assert restored.notes == original.notes

    def test_pre_built_task_envelope_dedup_key(self) -> None:
        from core.reliability_contract import TASK_ENVELOPE_DEDUP_KEY

        assert "task_id" in TASK_ENVELOPE_DEDUP_KEY.fields
        assert "idempotency_key" in TASK_ENVELOPE_DEDUP_KEY.fields
        assert TASK_ENVELOPE_DEDUP_KEY.enforced is True
        assert TASK_ENVELOPE_DEDUP_KEY.has_key()

    def test_pre_built_no_dedup_key(self) -> None:
        from core.reliability_contract import NO_DEDUP_KEY

        assert not NO_DEDUP_KEY.has_key()
        assert NO_DEDUP_KEY.enforced is False

    def test_pre_built_path_dedup_keys_have_fields(self) -> None:
        from core.reliability_contract import (
            NATS_TASK_DEDUP_KEY,
            HANDOFF_DEDUP_KEY,
            COMMAND_ROUTER_DEDUP_KEY,
            DEVICE_WEBSOCKET_DEDUP_KEY,
        )
        for key in [
            NATS_TASK_DEDUP_KEY,
            HANDOFF_DEDUP_KEY,
            COMMAND_ROUTER_DEDUP_KEY,
            DEVICE_WEBSOCKET_DEDUP_KEY,
        ]:
            assert key.has_key()
            assert key.fields


# ---------------------------------------------------------------------------
# 5. RetryPolicy
# ---------------------------------------------------------------------------


class TestRetryPolicy:
    def test_default_construction(self) -> None:
        from core.reliability_contract import RetryPolicy

        policy = RetryPolicy()
        assert policy.max_attempts == 1
        assert not policy.has_retries()
        assert policy.schema_version == 1

    def test_has_retries_true(self) -> None:
        from core.reliability_contract import RetryPolicy

        policy = RetryPolicy(max_attempts=3)
        assert policy.has_retries()

    def test_to_dict_keys(self) -> None:
        from core.reliability_contract import RetryPolicy

        policy = RetryPolicy(max_attempts=3, backoff_base_ms=500, owner="transport")
        d = policy.to_dict()
        assert d["max_attempts"] == 3
        assert d["backoff_base_ms"] == 500
        assert d["owner"] == "transport"
        assert "schema_version" in d

    def test_from_dict_roundtrip(self) -> None:
        from core.reliability_contract import RetryPolicy

        original = RetryPolicy(
            max_attempts=3,
            backoff_base_ms=500,
            backoff_multiplier=2.0,
            owner="transport",
            retry_on_timeout=True,
        )
        restored = RetryPolicy.from_dict(original.to_dict())
        assert restored.max_attempts == original.max_attempts
        assert restored.backoff_base_ms == original.backoff_base_ms
        assert restored.backoff_multiplier == original.backoff_multiplier
        assert restored.owner == original.owner
        assert restored.retry_on_timeout == original.retry_on_timeout

    def test_pre_built_no_retry(self) -> None:
        from core.reliability_contract import NO_RETRY_POLICY

        assert NO_RETRY_POLICY.max_attempts == 1
        assert not NO_RETRY_POLICY.has_retries()

    def test_pre_built_transport_retry(self) -> None:
        from core.reliability_contract import TRANSPORT_RETRY_POLICY

        assert TRANSPORT_RETRY_POLICY.max_attempts > 1
        assert TRANSPORT_RETRY_POLICY.owner == "transport"
        assert TRANSPORT_RETRY_POLICY.has_retries()

    def test_pre_built_coordinator_retry(self) -> None:
        from core.reliability_contract import COORDINATOR_RETRY_POLICY

        assert COORDINATOR_RETRY_POLICY.owner == "coordinator"
        assert COORDINATOR_RETRY_POLICY.has_retries()


# ---------------------------------------------------------------------------
# 6. TimeoutOwner enum
# ---------------------------------------------------------------------------


class TestTimeoutOwner:
    def test_all_expected_owners_present(self) -> None:
        from core.reliability_contract import TimeoutOwner

        expected = {"transport", "router", "runtime", "coordinator", "caller", "unspecified"}
        actual = {o.value for o in TimeoutOwner}
        assert expected == actual

    def test_values_stable(self) -> None:
        from core.reliability_contract import TimeoutOwner

        assert TimeoutOwner.TRANSPORT.value == "transport"
        assert TimeoutOwner.ROUTER.value == "router"
        assert TimeoutOwner.RUNTIME.value == "runtime"
        assert TimeoutOwner.COORDINATOR.value == "coordinator"
        assert TimeoutOwner.CALLER.value == "caller"
        assert TimeoutOwner.UNSPECIFIED.value == "unspecified"

    def test_is_json_serialisable(self) -> None:
        from core.reliability_contract import TimeoutOwner

        serialised = json.dumps([o.value for o in TimeoutOwner])
        restored = json.loads(serialised)
        assert set(restored) == {o.value for o in TimeoutOwner}

    def test_description_returns_string(self) -> None:
        from core.reliability_contract import TimeoutOwner, timeout_owner_description

        for owner in TimeoutOwner:
            desc = timeout_owner_description(owner)
            assert isinstance(desc, str)
            assert len(desc) > 10

    def test_descriptions_dict_covers_all_owners(self) -> None:
        from core.reliability_contract import TimeoutOwner, TIMEOUT_OWNER_DESCRIPTIONS

        for owner in TimeoutOwner:
            assert owner.value in TIMEOUT_OWNER_DESCRIPTIONS


# ---------------------------------------------------------------------------
# 7. FallbackOwner enum
# ---------------------------------------------------------------------------


class TestFallbackOwner:
    def test_all_expected_owners_present(self) -> None:
        from core.reliability_contract import FallbackOwner

        expected = {
            "local_fallback",
            "transport_fallback",
            "reroute_owner",
            "coordinator",
            "abort_owner",
            "caller",
            "unspecified",
        }
        actual = {o.value for o in FallbackOwner}
        assert expected == actual

    def test_values_stable(self) -> None:
        from core.reliability_contract import FallbackOwner

        assert FallbackOwner.LOCAL_FALLBACK.value == "local_fallback"
        assert FallbackOwner.TRANSPORT_FALLBACK.value == "transport_fallback"
        assert FallbackOwner.REROUTE_OWNER.value == "reroute_owner"
        assert FallbackOwner.COORDINATOR.value == "coordinator"
        assert FallbackOwner.ABORT_OWNER.value == "abort_owner"
        assert FallbackOwner.CALLER.value == "caller"
        assert FallbackOwner.UNSPECIFIED.value == "unspecified"

    def test_is_json_serialisable(self) -> None:
        from core.reliability_contract import FallbackOwner

        serialised = json.dumps([o.value for o in FallbackOwner])
        restored = json.loads(serialised)
        assert set(restored) == {o.value for o in FallbackOwner}

    def test_description_returns_string(self) -> None:
        from core.reliability_contract import FallbackOwner, fallback_owner_description

        for owner in FallbackOwner:
            desc = fallback_owner_description(owner)
            assert isinstance(desc, str)
            assert len(desc) > 5

    def test_descriptions_dict_covers_all_owners(self) -> None:
        from core.reliability_contract import FallbackOwner, FALLBACK_OWNER_DESCRIPTIONS

        for owner in FallbackOwner:
            assert owner.value in FALLBACK_OWNER_DESCRIPTIONS


# ---------------------------------------------------------------------------
# 10. ReliabilitySummary
# ---------------------------------------------------------------------------


class TestReliabilitySummary:
    def test_default_construction(self) -> None:
        from core.reliability_contract import (
            ReliabilitySummary,
            DeliveryMode,
            TimeoutOwner,
            FallbackOwner,
        )
        summary = ReliabilitySummary()
        assert summary.path_key == "unknown"
        assert summary.delivery_mode == DeliveryMode.UNKNOWN
        assert summary.timeout_owner == TimeoutOwner.UNSPECIFIED
        assert summary.fallback_owner == FallbackOwner.UNSPECIFIED
        assert summary.schema_version == 1

    def test_to_dict_keys(self) -> None:
        from core.reliability_contract import ReliabilitySummary

        summary = ReliabilitySummary(path_key="test_path", description="A test path")
        d = summary.to_dict()
        expected_keys = {
            "path_key",
            "description",
            "delivery_mode",
            "ack_policy",
            "dedup_key",
            "retry_policy",
            "timeout_owner",
            "fallback_owner",
            "source_module",
            "notes",
            "schema_version",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_to_dict_is_json_serialisable(self) -> None:
        from core.reliability_contract import ReliabilitySummary

        summary = ReliabilitySummary(path_key="test_path")
        serialised = json.dumps(summary.to_dict())
        assert "test_path" in serialised

    def test_from_dict_roundtrip(self) -> None:
        from core.reliability_contract import (
            ReliabilitySummary,
            DeliveryMode,
            TimeoutOwner,
            FallbackOwner,
        )
        original = ReliabilitySummary(
            path_key="roundtrip_test",
            description="Round-trip test",
            delivery_mode=DeliveryMode.AT_LEAST_ONCE,
            timeout_owner=TimeoutOwner.RUNTIME,
            fallback_owner=FallbackOwner.LOCAL_FALLBACK,
            notes="test",
        )
        restored = ReliabilitySummary.from_dict(original.to_dict())
        assert restored.path_key == original.path_key
        assert restored.delivery_mode == original.delivery_mode
        assert restored.timeout_owner == original.timeout_owner
        assert restored.fallback_owner == original.fallback_owner
        assert restored.notes == original.notes

    def test_from_dict_unknown_delivery_mode_degrades(self) -> None:
        from core.reliability_contract import ReliabilitySummary, DeliveryMode

        summary = ReliabilitySummary.from_dict({"delivery_mode": "nonexistent_mode"})
        assert summary.delivery_mode == DeliveryMode.UNKNOWN

    def test_from_dict_unknown_timeout_owner_degrades(self) -> None:
        from core.reliability_contract import ReliabilitySummary, TimeoutOwner

        summary = ReliabilitySummary.from_dict({"timeout_owner": "nonexistent_owner"})
        assert summary.timeout_owner == TimeoutOwner.UNSPECIFIED

    def test_from_dict_unknown_fallback_owner_degrades(self) -> None:
        from core.reliability_contract import ReliabilitySummary, FallbackOwner

        summary = ReliabilitySummary.from_dict({"fallback_owner": "nonexistent_owner"})
        assert summary.fallback_owner == FallbackOwner.UNSPECIFIED

    def test_from_dict_empty_dict_degrades_gracefully(self) -> None:
        from core.reliability_contract import ReliabilitySummary, DeliveryMode

        summary = ReliabilitySummary.from_dict({})
        assert summary.path_key == "unknown"
        assert summary.delivery_mode == DeliveryMode.UNKNOWN

    def test_ack_policy_nested_roundtrip(self) -> None:
        from core.reliability_contract import ReliabilitySummary, AckStage, ACCEPTED_ACK_POLICY

        original = ReliabilitySummary(path_key="ack_test", ack_policy=ACCEPTED_ACK_POLICY)
        restored = ReliabilitySummary.from_dict(original.to_dict())
        assert restored.ack_policy.stage == AckStage.ACCEPTED_ACK


# ---------------------------------------------------------------------------
# 11. UNKNOWN_RELIABILITY_SUMMARY sentinel
# ---------------------------------------------------------------------------


class TestUnknownReliabilitySummary:
    def test_sentinel_field_values(self) -> None:
        from core.reliability_contract import (
            UNKNOWN_RELIABILITY_SUMMARY,
            DeliveryMode,
            TimeoutOwner,
            FallbackOwner,
        )
        s = UNKNOWN_RELIABILITY_SUMMARY
        assert s.path_key == "unknown"
        assert s.delivery_mode == DeliveryMode.UNKNOWN
        assert s.timeout_owner == TimeoutOwner.UNSPECIFIED
        assert s.fallback_owner == FallbackOwner.UNSPECIFIED
        assert s.notes is not None

    def test_sentinel_is_serialisable(self) -> None:
        from core.reliability_contract import UNKNOWN_RELIABILITY_SUMMARY

        serialised = json.dumps(UNKNOWN_RELIABILITY_SUMMARY.to_dict())
        assert "unknown" in serialised


# ---------------------------------------------------------------------------
# 12. RELIABILITY_PATH_REGISTRY — all five paths present
# ---------------------------------------------------------------------------

EXPECTED_PATHS = {
    "task_envelope",
    "nats_task",
    "agent_bridge_handoff",
    "command_router_remote",
    "device_websocket",
}


class TestReliabilityPathRegistry:
    def test_all_five_paths_present(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY

        assert EXPECTED_PATHS.issubset(set(RELIABILITY_PATH_REGISTRY.keys()))

    def test_all_paths_have_non_empty_description(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY

        for key, summary in RELIABILITY_PATH_REGISTRY.items():
            assert summary.description, f"Path {key!r} has empty description"

    def test_all_paths_have_known_delivery_mode(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY, DeliveryMode

        for key, summary in RELIABILITY_PATH_REGISTRY.items():
            assert summary.delivery_mode != DeliveryMode.UNKNOWN, (
                f"Path {key!r} has UNKNOWN delivery mode"
            )

    def test_all_paths_have_known_timeout_owner(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY, TimeoutOwner

        for key, summary in RELIABILITY_PATH_REGISTRY.items():
            assert summary.timeout_owner != TimeoutOwner.UNSPECIFIED, (
                f"Path {key!r} has UNSPECIFIED timeout owner"
            )

    def test_all_paths_have_known_fallback_owner(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY, FallbackOwner

        for key, summary in RELIABILITY_PATH_REGISTRY.items():
            assert summary.fallback_owner != FallbackOwner.UNSPECIFIED, (
                f"Path {key!r} has UNSPECIFIED fallback owner"
            )

    def test_all_paths_have_source_module(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY

        for key, summary in RELIABILITY_PATH_REGISTRY.items():
            assert summary.source_module, f"Path {key!r} has no source_module"

    def test_task_envelope_is_dedup_required(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY, DeliveryMode

        summary = RELIABILITY_PATH_REGISTRY["task_envelope"]
        assert summary.delivery_mode == DeliveryMode.DEDUP_REQUIRED
        assert summary.dedup_key.enforced is True

    def test_nats_task_is_at_least_once(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY, DeliveryMode

        summary = RELIABILITY_PATH_REGISTRY["nats_task"]
        assert summary.delivery_mode == DeliveryMode.AT_LEAST_ONCE

    def test_agent_bridge_has_runtime_timeout(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY, TimeoutOwner

        summary = RELIABILITY_PATH_REGISTRY["agent_bridge_handoff"]
        assert summary.timeout_owner == TimeoutOwner.RUNTIME

    def test_agent_bridge_has_local_fallback(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY, FallbackOwner

        summary = RELIABILITY_PATH_REGISTRY["agent_bridge_handoff"]
        assert summary.fallback_owner == FallbackOwner.LOCAL_FALLBACK

    def test_device_websocket_is_best_effort(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY, DeliveryMode

        summary = RELIABILITY_PATH_REGISTRY["device_websocket"]
        assert summary.delivery_mode == DeliveryMode.BEST_EFFORT

    def test_all_paths_serialisable(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY

        for key, summary in RELIABILITY_PATH_REGISTRY.items():
            serialised = json.dumps(summary.to_dict())
            assert key in serialised


# ---------------------------------------------------------------------------
# 13. get_summary_for_path
# ---------------------------------------------------------------------------


class TestGetSummaryForPath:
    def test_known_path_returns_correct_summary(self) -> None:
        from core.reliability_contract import get_summary_for_path

        for path_key in EXPECTED_PATHS:
            summary = get_summary_for_path(path_key)
            assert summary.path_key == path_key

    def test_unknown_path_returns_sentinel(self) -> None:
        from core.reliability_contract import (
            get_summary_for_path,
            UNKNOWN_RELIABILITY_SUMMARY,
        )
        summary = get_summary_for_path("completely_unknown_path_xyz")
        assert summary is UNKNOWN_RELIABILITY_SUMMARY

    def test_never_returns_none(self) -> None:
        from core.reliability_contract import get_summary_for_path

        result = get_summary_for_path("")
        assert result is not None


# ---------------------------------------------------------------------------
# 14. list_known_paths
# ---------------------------------------------------------------------------


class TestListKnownPaths:
    def test_returns_sorted_list(self) -> None:
        from core.reliability_contract import list_known_paths

        paths = list_known_paths()
        assert paths == sorted(paths)

    def test_covers_all_five_paths(self) -> None:
        from core.reliability_contract import list_known_paths

        paths = set(list_known_paths())
        assert EXPECTED_PATHS.issubset(paths)

    def test_returns_list_of_strings(self) -> None:
        from core.reliability_contract import list_known_paths

        paths = list_known_paths()
        assert all(isinstance(p, str) for p in paths)


# ---------------------------------------------------------------------------
# 15. get_reliability_registry_snapshot
# ---------------------------------------------------------------------------


class TestGetReliabilityRegistrySnapshot:
    def test_snapshot_has_correct_shape(self) -> None:
        from core.reliability_contract import get_reliability_registry_snapshot

        snapshot = get_reliability_registry_snapshot()
        assert "paths" in snapshot
        assert "total_paths" in snapshot
        assert "schema_version" in snapshot

    def test_total_paths_matches_registry(self) -> None:
        from core.reliability_contract import (
            get_reliability_registry_snapshot,
            RELIABILITY_PATH_REGISTRY,
        )
        snapshot = get_reliability_registry_snapshot()
        assert snapshot["total_paths"] == len(RELIABILITY_PATH_REGISTRY)

    def test_all_paths_present_in_snapshot(self) -> None:
        from core.reliability_contract import get_reliability_registry_snapshot

        snapshot = get_reliability_registry_snapshot()
        for path_key in EXPECTED_PATHS:
            assert path_key in snapshot["paths"]

    def test_snapshot_is_json_serialisable(self) -> None:
        from core.reliability_contract import get_reliability_registry_snapshot

        snapshot = get_reliability_registry_snapshot()
        serialised = json.dumps(snapshot)
        assert "task_envelope" in serialised

    def test_schema_version_is_int(self) -> None:
        from core.reliability_contract import get_reliability_registry_snapshot

        snapshot = get_reliability_registry_snapshot()
        assert isinstance(snapshot["schema_version"], int)


# ---------------------------------------------------------------------------
# 16. make_reliability_summary
# ---------------------------------------------------------------------------


class TestMakeReliabilitySummary:
    def test_valid_inputs(self) -> None:
        from core.reliability_contract import (
            make_reliability_summary,
            DeliveryMode,
            AckStage,
            TimeoutOwner,
            FallbackOwner,
        )
        summary = make_reliability_summary(
            path_key="test_path",
            description="Test",
            delivery_mode="at_least_once",
            ack_stage="accepted_ack",
            timeout_owner="runtime",
            fallback_owner="local_fallback",
            dedup_fields=["task_id"],
            notes="Test notes",
        )
        assert summary.path_key == "test_path"
        assert summary.delivery_mode == DeliveryMode.AT_LEAST_ONCE
        assert summary.ack_policy.stage == AckStage.ACCEPTED_ACK
        assert summary.timeout_owner == TimeoutOwner.RUNTIME
        assert summary.fallback_owner == FallbackOwner.LOCAL_FALLBACK
        assert summary.dedup_key.fields == ["task_id"]
        assert summary.notes == "Test notes"

    def test_unknown_delivery_mode_degrades(self) -> None:
        from core.reliability_contract import make_reliability_summary, DeliveryMode

        summary = make_reliability_summary(
            path_key="test",
            delivery_mode="completely_invalid_value",
        )
        assert summary.delivery_mode == DeliveryMode.UNKNOWN

    def test_unknown_ack_stage_degrades(self) -> None:
        from core.reliability_contract import make_reliability_summary, AckStage

        summary = make_reliability_summary(
            path_key="test",
            ack_stage="completely_invalid_stage",
        )
        assert summary.ack_policy.stage == AckStage.UNKNOWN

    def test_unknown_timeout_owner_degrades(self) -> None:
        from core.reliability_contract import make_reliability_summary, TimeoutOwner

        summary = make_reliability_summary(
            path_key="test",
            timeout_owner="completely_invalid_owner",
        )
        assert summary.timeout_owner == TimeoutOwner.UNSPECIFIED

    def test_unknown_fallback_owner_degrades(self) -> None:
        from core.reliability_contract import make_reliability_summary, FallbackOwner

        summary = make_reliability_summary(
            path_key="test",
            fallback_owner="completely_invalid_owner",
        )
        assert summary.fallback_owner == FallbackOwner.UNSPECIFIED

    def test_minimal_inputs_work(self) -> None:
        from core.reliability_contract import make_reliability_summary

        summary = make_reliability_summary(path_key="minimal")
        assert summary.path_key == "minimal"

    def test_none_dedup_fields_gives_empty_list(self) -> None:
        from core.reliability_contract import make_reliability_summary

        summary = make_reliability_summary(path_key="test", dedup_fields=None)
        assert summary.dedup_key.fields == []

    def test_result_is_json_serialisable(self) -> None:
        from core.reliability_contract import make_reliability_summary

        summary = make_reliability_summary(
            path_key="serialise_test",
            delivery_mode="best_effort",
        )
        serialised = json.dumps(summary.to_dict())
        assert "serialise_test" in serialised


# ---------------------------------------------------------------------------
# 17. attach_reliability_to_projection
# ---------------------------------------------------------------------------


class TestAttachReliabilityToProjection:
    def test_adds_reliability_key(self) -> None:
        from core.reliability_contract import attach_reliability_to_projection

        projection = {"status": "ok", "task_id": "abc"}
        enriched = attach_reliability_to_projection(projection, path_key="task_envelope")
        assert "reliability" in enriched

    def test_does_not_mutate_original(self) -> None:
        from core.reliability_contract import attach_reliability_to_projection

        projection = {"status": "ok"}
        original_copy = dict(projection)
        attach_reliability_to_projection(projection, path_key="task_envelope")
        assert projection == original_copy

    def test_returns_new_dict(self) -> None:
        from core.reliability_contract import attach_reliability_to_projection

        projection = {"status": "ok"}
        enriched = attach_reliability_to_projection(projection)
        assert enriched is not projection

    def test_original_keys_preserved(self) -> None:
        from core.reliability_contract import attach_reliability_to_projection

        projection = {"status": "ok", "task_id": "abc", "device": "phone"}
        enriched = attach_reliability_to_projection(projection, path_key="device_websocket")
        assert enriched["status"] == "ok"
        assert enriched["task_id"] == "abc"
        assert enriched["device"] == "phone"

    def test_reliability_section_is_dict(self) -> None:
        from core.reliability_contract import attach_reliability_to_projection

        enriched = attach_reliability_to_projection({}, path_key="nats_task")
        assert isinstance(enriched["reliability"], dict)

    def test_unknown_path_attaches_sentinel(self) -> None:
        from core.reliability_contract import attach_reliability_to_projection

        enriched = attach_reliability_to_projection({}, path_key="completely_unknown_xyz")
        assert enriched["reliability"]["path_key"] == "unknown"

    def test_reliability_section_is_json_serialisable(self) -> None:
        from core.reliability_contract import attach_reliability_to_projection

        enriched = attach_reliability_to_projection({}, path_key="agent_bridge_handoff")
        serialised = json.dumps(enriched)
        assert "agent_bridge_handoff" in serialised


# ---------------------------------------------------------------------------
# 18. Partial/unknown metadata handling
# ---------------------------------------------------------------------------


class TestPartialMetadataHandling:
    def test_from_dict_with_partial_ack_policy(self) -> None:
        from core.reliability_contract import ReliabilitySummary

        data = {
            "path_key": "partial_test",
            "ack_policy": {"stage": "accepted_ack"},  # missing other fields
        }
        summary = ReliabilitySummary.from_dict(data)
        assert summary.ack_policy is not None

    def test_from_dict_with_partial_dedup_key(self) -> None:
        from core.reliability_contract import ReliabilitySummary

        data = {
            "path_key": "partial_test",
            "dedup_key": {"fields": ["task_id"]},  # missing composition etc.
        }
        summary = ReliabilitySummary.from_dict(data)
        assert "task_id" in summary.dedup_key.fields

    def test_from_dict_with_partial_retry_policy(self) -> None:
        from core.reliability_contract import ReliabilitySummary

        data = {
            "path_key": "partial_test",
            "retry_policy": {"max_attempts": 2},
        }
        summary = ReliabilitySummary.from_dict(data)
        assert summary.retry_policy.max_attempts == 2

    def test_snapshot_includes_all_dimensions(self) -> None:
        from core.reliability_contract import get_reliability_registry_snapshot

        snapshot = get_reliability_registry_snapshot()
        for path_key in EXPECTED_PATHS:
            path_data = snapshot["paths"][path_key]
            assert "delivery_mode" in path_data
            assert "ack_policy" in path_data
            assert "dedup_key" in path_data
            assert "retry_policy" in path_data
            assert "timeout_owner" in path_data
            assert "fallback_owner" in path_data


# ---------------------------------------------------------------------------
# 20. Introspection / read surface — GET /api/v1/contracts/reliability
# ---------------------------------------------------------------------------


class TestReliabilityContractApiRoute:
    def test_route_returns_200(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi not available")

        from fastapi import FastAPI
        from core.routes.contracts import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)

        response = client.get("/api/v1/contracts/reliability")
        assert response.status_code == 200

    def test_route_returns_expected_shape(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi not available")

        from fastapi import FastAPI
        from core.routes.contracts import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)

        response = client.get("/api/v1/contracts/reliability")
        data = response.json()
        assert "paths" in data
        assert "total_paths" in data
        assert "schema_version" in data

    def test_route_includes_all_five_paths(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi not available")

        from fastapi import FastAPI
        from core.routes.contracts import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)

        response = client.get("/api/v1/contracts/reliability")
        data = response.json()
        for path_key in EXPECTED_PATHS:
            assert path_key in data["paths"], f"{path_key!r} missing from response"

    def test_route_total_paths_is_correct(self) -> None:
        try:
            from fastapi.testclient import TestClient
        except ImportError:
            pytest.skip("fastapi not available")

        from fastapi import FastAPI
        from core.routes.contracts import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)

        response = client.get("/api/v1/contracts/reliability")
        data = response.json()
        assert data["total_paths"] == len(data["paths"])


# ---------------------------------------------------------------------------
# 21. Contract-map integration — reliability endpoint alongside planes/messages
# ---------------------------------------------------------------------------


class TestContractMapIntegration:
    def test_reliability_registry_snapshot_is_json_serialisable(self) -> None:
        from core.reliability_contract import get_reliability_registry_snapshot

        snapshot = get_reliability_registry_snapshot()
        serialised = json.dumps(snapshot)
        # Verify all five known path keys appear in the serialised output
        for path_key in EXPECTED_PATHS:
            assert path_key in serialised

    def test_reliability_path_keys_are_strings(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY

        for key in RELIABILITY_PATH_REGISTRY:
            assert isinstance(key, str)

    def test_all_summaries_have_schema_version_1(self) -> None:
        from core.reliability_contract import RELIABILITY_PATH_REGISTRY

        for key, summary in RELIABILITY_PATH_REGISTRY.items():
            assert summary.schema_version == 1, f"Path {key!r} has wrong schema_version"
