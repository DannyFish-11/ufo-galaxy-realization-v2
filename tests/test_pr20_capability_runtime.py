#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr20_capability_runtime.py
=======================================

PR-20 (V4) — Capability Runtime State

Tests covering:
1.  CapabilityAvailability enum — values, serialisation stability
2.  CapabilityRuntimeState — construction, to_dict, from_dict round-trip
3.  CapabilityRuntimeState — is_routable / is_healthy helpers
4.  CapabilityConstraintFlags — construction, to_dict, from_dict round-trip
5.  CapabilityConstraintFlags — has_any_constraint / active_constraints
6.  CapabilityConstraintFlags — pre-built sentinels
7.  CapabilityPreference — construction, to_dict, from_dict round-trip
8.  CapabilityPreference — has_preference / NO_PREFERENCE sentinel
9.  CapabilityRuntimeRegistry — singleton identity
10. CapabilityRuntimeRegistry — register / get_state / deregister
11. CapabilityRuntimeRegistry — update partial fields
12. CapabilityRuntimeRegistry — get_summary for known & unknown names
13. CapabilityRuntimeRegistry — list_states / list_summaries
14. CapabilityRuntimeRegistry — stats shape
15. CapabilityRuntimeSummary — construction, to_dict, from_dict round-trip
16. CapabilityRuntimeSummary — from_dict unknown availability degrades gracefully
17. UNKNOWN_CAPABILITY_SUMMARY — sentinel field values
18. make_capability_summary — valid inputs
19. make_capability_summary — unknown/partial inputs degrade gracefully
20. get_capability_runtime_snapshot — shape, total_capabilities
21. attach_runtime_summary_to_projection — additive, non-mutating
22. Read-only endpoint output shape — GET /api/v1/capabilities/runtime
23. Read-only endpoint — GET /api/v1/capabilities/runtime/{name} not found
24. availability_description — returns non-empty string for all postures
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_registry() -> None:
    """Reset the CapabilityRuntimeRegistry singleton between tests."""
    from core.capability_runtime.capability_registry_runtime import CapabilityRuntimeRegistry
    with CapabilityRuntimeRegistry._instance_lock:
        CapabilityRuntimeRegistry._instance = None


@pytest.fixture(autouse=True)
def clean_registry():
    """Ensure each test gets a fresh registry."""
    _reset_registry()
    yield
    _reset_registry()


# ---------------------------------------------------------------------------
# 1. CapabilityAvailability enum
# ---------------------------------------------------------------------------


class TestCapabilityAvailability:
    def test_all_expected_postures_present(self) -> None:
        from core.capability_runtime import CapabilityAvailability

        expected = {"available", "degraded", "unavailable", "unknown"}
        actual = {p.value for p in CapabilityAvailability}
        assert expected == actual

    def test_values_are_strings(self) -> None:
        from core.capability_runtime import CapabilityAvailability

        for posture in CapabilityAvailability:
            assert isinstance(posture.value, str)
            assert posture.value

    def test_values_stable(self) -> None:
        from core.capability_runtime import CapabilityAvailability

        assert CapabilityAvailability.AVAILABLE.value == "available"
        assert CapabilityAvailability.DEGRADED.value == "degraded"
        assert CapabilityAvailability.UNAVAILABLE.value == "unavailable"
        assert CapabilityAvailability.UNKNOWN.value == "unknown"

    def test_is_json_serialisable(self) -> None:
        from core.capability_runtime import CapabilityAvailability

        serialised = json.dumps([p.value for p in CapabilityAvailability])
        restored = json.loads(serialised)
        assert set(restored) == {p.value for p in CapabilityAvailability}

    def test_roundtrip(self) -> None:
        from core.capability_runtime import CapabilityAvailability

        for posture in CapabilityAvailability:
            assert CapabilityAvailability(posture.value) == posture

    def test_description_returns_string_for_all(self) -> None:
        from core.capability_runtime import CapabilityAvailability, availability_description

        for posture in CapabilityAvailability:
            desc = availability_description(posture)
            assert isinstance(desc, str)
            assert len(desc) > 10

    def test_descriptions_dict_covers_all_postures(self) -> None:
        from core.capability_runtime import CapabilityAvailability, AVAILABILITY_DESCRIPTIONS

        for posture in CapabilityAvailability:
            assert posture.value in AVAILABILITY_DESCRIPTIONS


# ---------------------------------------------------------------------------
# 2-3. CapabilityRuntimeState
# ---------------------------------------------------------------------------


class TestCapabilityRuntimeState:
    def test_basic_construction(self) -> None:
        from core.capability_runtime import CapabilityRuntimeState, CapabilityAvailability

        state = CapabilityRuntimeState(name="cap_a")
        assert state.name == "cap_a"
        assert state.availability == CapabilityAvailability.UNKNOWN
        assert state.device_bindings == []
        assert state.preferred_device_ids == []

    def test_to_dict_keys(self) -> None:
        from core.capability_runtime import CapabilityRuntimeState

        state = CapabilityRuntimeState(name="cap_b")
        d = state.to_dict()
        for key in ("state_id", "name", "availability", "device_bindings",
                    "preferred_device_ids", "constraint_flags", "reliability_flags",
                    "last_updated", "metadata"):
            assert key in d

    def test_to_dict_availability_is_string(self) -> None:
        from core.capability_runtime import CapabilityRuntimeState, CapabilityAvailability

        state = CapabilityRuntimeState(
            name="cap_c", availability=CapabilityAvailability.AVAILABLE
        )
        d = state.to_dict()
        assert d["availability"] == "available"
        assert isinstance(d["availability"], str)

    def test_roundtrip(self) -> None:
        from core.capability_runtime import CapabilityRuntimeState, CapabilityAvailability

        state = CapabilityRuntimeState(
            name="cap_rt",
            availability=CapabilityAvailability.DEGRADED,
            device_bindings=["dev_1"],
            preferred_device_ids=["dev_1", "dev_2"],
            constraint_flags={"latency_sensitive": True},
            reliability_flags={"health_score": 0.7},
            metadata={"note": "test"},
        )
        d = state.to_dict()
        restored = CapabilityRuntimeState.from_dict(d)
        assert restored.name == state.name
        assert restored.availability == state.availability
        assert restored.device_bindings == state.device_bindings
        assert restored.preferred_device_ids == state.preferred_device_ids
        assert restored.constraint_flags == state.constraint_flags
        assert restored.reliability_flags == state.reliability_flags

    def test_from_dict_unknown_availability_degrades(self) -> None:
        from core.capability_runtime import CapabilityRuntimeState, CapabilityAvailability

        d = {"name": "cap_x", "availability": "totally_unknown_value"}
        state = CapabilityRuntimeState.from_dict(d)
        assert state.availability == CapabilityAvailability.UNKNOWN

    def test_is_routable(self) -> None:
        from core.capability_runtime import CapabilityRuntimeState, CapabilityAvailability

        assert CapabilityRuntimeState(name="a", availability=CapabilityAvailability.AVAILABLE).is_routable()
        assert CapabilityRuntimeState(name="b", availability=CapabilityAvailability.DEGRADED).is_routable()
        assert not CapabilityRuntimeState(name="c", availability=CapabilityAvailability.UNAVAILABLE).is_routable()
        assert not CapabilityRuntimeState(name="d", availability=CapabilityAvailability.UNKNOWN).is_routable()

    def test_is_healthy(self) -> None:
        from core.capability_runtime import CapabilityRuntimeState, CapabilityAvailability

        assert CapabilityRuntimeState(name="a", availability=CapabilityAvailability.AVAILABLE).is_healthy()
        assert not CapabilityRuntimeState(name="b", availability=CapabilityAvailability.DEGRADED).is_healthy()
        assert not CapabilityRuntimeState(name="c", availability=CapabilityAvailability.UNAVAILABLE).is_healthy()
        assert not CapabilityRuntimeState(name="d", availability=CapabilityAvailability.UNKNOWN).is_healthy()

    def test_json_serialisable(self) -> None:
        from core.capability_runtime import CapabilityRuntimeState, CapabilityAvailability

        state = CapabilityRuntimeState(
            name="cap_json",
            availability=CapabilityAvailability.AVAILABLE,
            device_bindings=["d1"],
        )
        json.dumps(state.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# 4-6. CapabilityConstraintFlags
# ---------------------------------------------------------------------------


class TestCapabilityConstraintFlags:
    def test_all_false_by_default(self) -> None:
        from core.capability_runtime import CapabilityConstraintFlags

        cf = CapabilityConstraintFlags()
        assert not cf.requires_confirmation
        assert not cf.cross_device_restricted
        assert not cf.latency_sensitive
        assert not cf.device_exclusive
        assert not cf.requires_elevated_privilege

    def test_to_dict_keys(self) -> None:
        from core.capability_runtime import CapabilityConstraintFlags

        cf = CapabilityConstraintFlags()
        d = cf.to_dict()
        for key in ("requires_confirmation", "cross_device_restricted",
                    "latency_sensitive", "device_exclusive", "requires_elevated_privilege"):
            assert key in d

    def test_roundtrip(self) -> None:
        from core.capability_runtime import CapabilityConstraintFlags

        cf = CapabilityConstraintFlags(
            requires_confirmation=True,
            latency_sensitive=True,
        )
        restored = CapabilityConstraintFlags.from_dict(cf.to_dict())
        assert restored == cf

    def test_from_dict_unknown_keys_ignored(self) -> None:
        from core.capability_runtime import CapabilityConstraintFlags

        d = {"requires_confirmation": True, "future_flag": True}
        cf = CapabilityConstraintFlags.from_dict(d)
        assert cf.requires_confirmation is True

    def test_has_any_constraint_false_when_all_false(self) -> None:
        from core.capability_runtime import CapabilityConstraintFlags

        assert not CapabilityConstraintFlags().has_any_constraint()

    def test_has_any_constraint_true_when_any_set(self) -> None:
        from core.capability_runtime import CapabilityConstraintFlags

        assert CapabilityConstraintFlags(requires_confirmation=True).has_any_constraint()

    def test_active_constraints_empty_when_all_false(self) -> None:
        from core.capability_runtime import CapabilityConstraintFlags

        assert CapabilityConstraintFlags().active_constraints() == []

    def test_active_constraints_lists_set_flags(self) -> None:
        from core.capability_runtime import CapabilityConstraintFlags

        cf = CapabilityConstraintFlags(cross_device_restricted=True, latency_sensitive=True)
        active = cf.active_constraints()
        assert "cross_device_restricted" in active
        assert "latency_sensitive" in active
        assert len(active) == 2

    def test_sentinels(self) -> None:
        from core.capability_runtime import (
            NO_CONSTRAINTS,
            CONFIRMATION_REQUIRED,
            LOCAL_ONLY,
            LATENCY_CRITICAL,
            EXCLUSIVE_LOCAL,
        )
        assert not NO_CONSTRAINTS.has_any_constraint()
        assert CONFIRMATION_REQUIRED.requires_confirmation
        assert LOCAL_ONLY.cross_device_restricted
        assert LATENCY_CRITICAL.latency_sensitive
        assert EXCLUSIVE_LOCAL.cross_device_restricted and EXCLUSIVE_LOCAL.device_exclusive

    def test_json_serialisable(self) -> None:
        from core.capability_runtime import CapabilityConstraintFlags

        json.dumps(CapabilityConstraintFlags(requires_confirmation=True).to_dict())


# ---------------------------------------------------------------------------
# 7-8. CapabilityPreference
# ---------------------------------------------------------------------------


class TestCapabilityPreference:
    def test_default_construction(self) -> None:
        from core.capability_runtime import CapabilityPreference

        pref = CapabilityPreference()
        assert pref.preferred_device_ids == []
        assert pref.preferred_executor == ""
        assert pref.weight == 1.0
        assert pref.sticky is False

    def test_roundtrip(self) -> None:
        from core.capability_runtime import CapabilityPreference

        pref = CapabilityPreference(
            preferred_device_ids=["dev_1"],
            preferred_executor="executor_a",
            weight=0.8,
            sticky=True,
            notes="prefer fast device",
        )
        restored = CapabilityPreference.from_dict(pref.to_dict())
        assert restored == pref

    def test_from_dict_clamps_weight(self) -> None:
        from core.capability_runtime import CapabilityPreference

        pref = CapabilityPreference.from_dict({"weight": 99.9})
        assert pref.weight == 1.0

        pref2 = CapabilityPreference.from_dict({"weight": -1.0})
        assert pref2.weight == 0.0

    def test_from_dict_invalid_weight_defaults_to_one(self) -> None:
        from core.capability_runtime import CapabilityPreference

        pref = CapabilityPreference.from_dict({"weight": "not_a_number"})
        assert pref.weight == 1.0

    def test_has_preference_false_for_defaults(self) -> None:
        from core.capability_runtime import CapabilityPreference

        assert not CapabilityPreference().has_preference()

    def test_has_preference_true_with_device_ids(self) -> None:
        from core.capability_runtime import CapabilityPreference

        assert CapabilityPreference(preferred_device_ids=["dev_1"]).has_preference()

    def test_no_preference_sentinel(self) -> None:
        from core.capability_runtime import NO_PREFERENCE, CapabilityPreference

        assert NO_PREFERENCE == CapabilityPreference()
        assert not NO_PREFERENCE.has_preference()

    def test_json_serialisable(self) -> None:
        from core.capability_runtime import CapabilityPreference

        json.dumps(CapabilityPreference(preferred_device_ids=["d1"]).to_dict())


# ---------------------------------------------------------------------------
# 9-14. CapabilityRuntimeRegistry
# ---------------------------------------------------------------------------


class TestCapabilityRuntimeRegistry:
    def test_singleton_identity(self) -> None:
        from core.capability_runtime import CapabilityRuntimeRegistry

        a = CapabilityRuntimeRegistry.get_instance()
        b = CapabilityRuntimeRegistry.get_instance()
        assert a is b

    def test_register_and_get_state(self) -> None:
        from core.capability_runtime import (
            CapabilityRuntimeRegistry,
            CapabilityRuntimeState,
            CapabilityAvailability,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        state = CapabilityRuntimeState(
            name="cap_reg",
            availability=CapabilityAvailability.AVAILABLE,
        )
        registry.register(state)
        retrieved = registry.get_state("cap_reg")
        assert retrieved is not None
        assert retrieved.name == "cap_reg"
        assert retrieved.availability == CapabilityAvailability.AVAILABLE

    def test_register_empty_name_ignored(self) -> None:
        from core.capability_runtime import CapabilityRuntimeRegistry, CapabilityRuntimeState

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(CapabilityRuntimeState(name=""))
        assert registry.get_state("") is None

    def test_get_state_unknown_returns_none(self) -> None:
        from core.capability_runtime import CapabilityRuntimeRegistry

        registry = CapabilityRuntimeRegistry.get_instance()
        assert registry.get_state("does_not_exist") is None

    def test_deregister(self) -> None:
        from core.capability_runtime import (
            CapabilityRuntimeRegistry,
            CapabilityRuntimeState,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(CapabilityRuntimeState(name="cap_del"))
        assert registry.deregister("cap_del") is True
        assert registry.get_state("cap_del") is None

    def test_deregister_nonexistent_returns_false(self) -> None:
        from core.capability_runtime import CapabilityRuntimeRegistry

        registry = CapabilityRuntimeRegistry.get_instance()
        assert registry.deregister("no_such_cap") is False

    def test_update_existing_availability(self) -> None:
        from core.capability_runtime import (
            CapabilityRuntimeRegistry,
            CapabilityRuntimeState,
            CapabilityAvailability,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(CapabilityRuntimeState(name="cap_upd"))
        registry.update("cap_upd", availability=CapabilityAvailability.DEGRADED.value)
        state = registry.get_state("cap_upd")
        assert state is not None
        assert state.availability == CapabilityAvailability.DEGRADED

    def test_update_creates_unknown_state_if_missing(self) -> None:
        from core.capability_runtime import (
            CapabilityRuntimeRegistry,
            CapabilityAvailability,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.update("cap_new_via_update", availability=CapabilityAvailability.AVAILABLE.value)
        state = registry.get_state("cap_new_via_update")
        assert state is not None

    def test_update_unknown_field_ignored(self) -> None:
        from core.capability_runtime import (
            CapabilityRuntimeRegistry,
            CapabilityRuntimeState,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(CapabilityRuntimeState(name="cap_unk"))
        registry.update("cap_unk", future_field="x")  # should not raise

    def test_get_summary_returns_summary_type(self) -> None:
        from core.capability_runtime import (
            CapabilityRuntimeRegistry,
            CapabilityRuntimeState,
            CapabilityAvailability,
            CapabilityRuntimeSummary,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(
            CapabilityRuntimeState(
                name="cap_sum",
                availability=CapabilityAvailability.AVAILABLE,
                preferred_device_ids=["dev_1"],
                constraint_flags={"latency_sensitive": True},
                reliability_flags={"health_score": 0.9},
            )
        )
        summary = registry.get_summary("cap_sum")
        assert isinstance(summary, CapabilityRuntimeSummary)
        assert summary.capability_name == "cap_sum"
        assert summary.availability == "available"
        assert "latency_sensitive" in summary.constraint_flags
        assert "health_score=0.9" in summary.reliability_notes

    def test_get_summary_unknown_returns_sentinel(self) -> None:
        from core.capability_runtime import (
            CapabilityRuntimeRegistry,
            UNKNOWN_CAPABILITY_SUMMARY,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        summary = registry.get_summary("no_such_cap")
        assert summary is UNKNOWN_CAPABILITY_SUMMARY

    def test_list_states(self) -> None:
        from core.capability_runtime import CapabilityRuntimeRegistry, CapabilityRuntimeState

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(CapabilityRuntimeState(name="ls_1"))
        registry.register(CapabilityRuntimeState(name="ls_2"))
        states = registry.list_states()
        names = {s.name for s in states}
        assert "ls_1" in names
        assert "ls_2" in names

    def test_list_summaries(self) -> None:
        from core.capability_runtime import (
            CapabilityRuntimeRegistry,
            CapabilityRuntimeState,
            CapabilityRuntimeSummary,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(CapabilityRuntimeState(name="lsum_1"))
        summaries = registry.list_summaries()
        assert all(isinstance(s, CapabilityRuntimeSummary) for s in summaries)
        assert any(s.capability_name == "lsum_1" for s in summaries)

    def test_stats_shape(self) -> None:
        from core.capability_runtime import (
            CapabilityRuntimeRegistry,
            CapabilityRuntimeState,
            CapabilityAvailability,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(
            CapabilityRuntimeState(name="st_a", availability=CapabilityAvailability.AVAILABLE)
        )
        registry.register(
            CapabilityRuntimeState(name="st_b", availability=CapabilityAvailability.DEGRADED)
        )
        stats = registry.stats()
        assert "total_registered" in stats
        assert "available_count" in stats
        assert "degraded_count" in stats
        assert "unavailable_count" in stats
        assert "unknown_count" in stats
        assert stats["total_registered"] >= 2
        assert stats["available_count"] >= 1
        assert stats["degraded_count"] >= 1


# ---------------------------------------------------------------------------
# 15-17. CapabilityRuntimeSummary
# ---------------------------------------------------------------------------


class TestCapabilityRuntimeSummary:
    def test_basic_construction(self) -> None:
        from core.capability_runtime import CapabilityRuntimeSummary, CapabilityAvailability

        s = CapabilityRuntimeSummary(capability_name="my_cap")
        assert s.capability_name == "my_cap"
        assert s.availability == CapabilityAvailability.UNKNOWN.value
        assert s.preferred_device_ids == []
        assert s.constraint_flags == []
        assert s.schema_version == 1

    def test_to_dict_keys(self) -> None:
        from core.capability_runtime import CapabilityRuntimeSummary

        s = CapabilityRuntimeSummary(capability_name="c")
        d = s.to_dict()
        for key in ("capability_name", "availability", "preferred_device_ids",
                    "constraint_flags", "reliability_notes", "device_bindings",
                    "last_updated", "metadata", "schema_version"):
            assert key in d

    def test_roundtrip(self) -> None:
        from core.capability_runtime import CapabilityRuntimeSummary

        s = CapabilityRuntimeSummary(
            capability_name="rt_cap",
            availability="available",
            preferred_device_ids=["d1"],
            constraint_flags=["latency_sensitive"],
            reliability_notes="health_score=0.9",
            device_bindings=["d1"],
            metadata={"src": "test"},
        )
        restored = CapabilityRuntimeSummary.from_dict(s.to_dict())
        assert restored.capability_name == s.capability_name
        assert restored.availability == s.availability
        assert restored.preferred_device_ids == s.preferred_device_ids
        assert restored.constraint_flags == s.constraint_flags

    def test_from_dict_unknown_availability_degrades(self) -> None:
        from core.capability_runtime import CapabilityRuntimeSummary, CapabilityAvailability

        s = CapabilityRuntimeSummary.from_dict({
            "capability_name": "x",
            "availability": "totally_bogus",
        })
        assert s.availability == CapabilityAvailability.UNKNOWN.value

    def test_json_serialisable(self) -> None:
        from core.capability_runtime import CapabilityRuntimeSummary

        s = CapabilityRuntimeSummary(capability_name="j", availability="available")
        json.dumps(s.to_dict())

    def test_unknown_sentinel_fields(self) -> None:
        from core.capability_runtime import UNKNOWN_CAPABILITY_SUMMARY, CapabilityAvailability

        assert UNKNOWN_CAPABILITY_SUMMARY.capability_name == "__unknown__"
        assert UNKNOWN_CAPABILITY_SUMMARY.availability == CapabilityAvailability.UNKNOWN.value
        assert isinstance(UNKNOWN_CAPABILITY_SUMMARY.reliability_notes, str)
        assert len(UNKNOWN_CAPABILITY_SUMMARY.reliability_notes) > 0


# ---------------------------------------------------------------------------
# 18-19. make_capability_summary
# ---------------------------------------------------------------------------


class TestMakeCapabilitySummary:
    def test_valid_inputs(self) -> None:
        from core.capability_runtime import make_capability_summary

        s = make_capability_summary(
            capability_name="cap_mk",
            availability="available",
            preferred_device_ids=["dev_1"],
            constraint_flags=["requires_confirmation"],
            reliability_notes="ok",
            device_bindings=["dev_1"],
            metadata={"k": "v"},
        )
        assert s.capability_name == "cap_mk"
        assert s.availability == "available"
        assert s.preferred_device_ids == ["dev_1"]
        assert "requires_confirmation" in s.constraint_flags
        assert s.reliability_notes == "ok"
        assert s.metadata == {"k": "v"}

    def test_unknown_availability_coerced(self) -> None:
        from core.capability_runtime import make_capability_summary, CapabilityAvailability

        s = make_capability_summary("cap_bad_avail", availability="not_valid")
        assert s.availability == CapabilityAvailability.UNKNOWN.value

    def test_none_lists_become_empty(self) -> None:
        from core.capability_runtime import make_capability_summary

        s = make_capability_summary("cap_none_lists")
        assert s.preferred_device_ids == []
        assert s.constraint_flags == []
        assert s.device_bindings == []
        assert s.metadata == {}


# ---------------------------------------------------------------------------
# 20. get_capability_runtime_snapshot
# ---------------------------------------------------------------------------


class TestGetCapabilityRuntimeSnapshot:
    def test_empty_registry_snapshot_shape(self) -> None:
        from core.capability_runtime import get_capability_runtime_snapshot

        snap = get_capability_runtime_snapshot()
        assert "capabilities" in snap
        assert "total_capabilities" in snap
        assert "schema_version" in snap
        assert snap["total_capabilities"] == 0
        assert snap["schema_version"] == 1

    def test_snapshot_includes_registered_capabilities(self) -> None:
        from core.capability_runtime import (
            get_capability_runtime_snapshot,
            CapabilityRuntimeRegistry,
            CapabilityRuntimeState,
            CapabilityAvailability,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(
            CapabilityRuntimeState(
                name="snap_cap",
                availability=CapabilityAvailability.AVAILABLE,
            )
        )
        snap = get_capability_runtime_snapshot()
        assert "snap_cap" in snap["capabilities"]
        assert snap["total_capabilities"] >= 1

    def test_snapshot_is_json_serialisable(self) -> None:
        from core.capability_runtime import (
            get_capability_runtime_snapshot,
            CapabilityRuntimeRegistry,
            CapabilityRuntimeState,
            CapabilityAvailability,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(
            CapabilityRuntimeState(
                name="json_snap",
                availability=CapabilityAvailability.DEGRADED,
                preferred_device_ids=["dev_1"],
            )
        )
        snap = get_capability_runtime_snapshot()
        json.dumps(snap)  # must not raise

    def test_capability_entry_has_expected_fields(self) -> None:
        from core.capability_runtime import (
            get_capability_runtime_snapshot,
            CapabilityRuntimeRegistry,
            CapabilityRuntimeState,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(CapabilityRuntimeState(name="field_check"))
        snap = get_capability_runtime_snapshot()
        entry = snap["capabilities"]["field_check"]
        for key in ("capability_name", "availability", "preferred_device_ids",
                    "constraint_flags", "reliability_notes", "device_bindings",
                    "last_updated", "metadata", "schema_version"):
            assert key in entry


# ---------------------------------------------------------------------------
# 21. attach_runtime_summary_to_projection
# ---------------------------------------------------------------------------


class TestAttachRuntimeSummaryToProjection:
    def test_additive(self) -> None:
        from core.capability_runtime import (
            attach_runtime_summary_to_projection,
            CapabilityRuntimeRegistry,
            CapabilityRuntimeState,
            CapabilityAvailability,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(
            CapabilityRuntimeState(
                name="proj_cap",
                availability=CapabilityAvailability.AVAILABLE,
            )
        )
        projection = {"task_id": "t_abc", "result": "ok"}
        enriched = attach_runtime_summary_to_projection(projection, "proj_cap")
        assert "capability_runtime" in enriched
        assert enriched["task_id"] == "t_abc"  # original fields preserved

    def test_non_mutating(self) -> None:
        from core.capability_runtime import attach_runtime_summary_to_projection

        projection = {"x": 1}
        attach_runtime_summary_to_projection(projection, "unknown_cap")
        assert "capability_runtime" not in projection  # original not mutated

    def test_unknown_capability_uses_sentinel(self) -> None:
        from core.capability_runtime import (
            attach_runtime_summary_to_projection,
            CapabilityAvailability,
        )

        enriched = attach_runtime_summary_to_projection({}, "no_such_cap")
        cap_rt = enriched["capability_runtime"]
        assert cap_rt["availability"] == CapabilityAvailability.UNKNOWN.value


# ---------------------------------------------------------------------------
# 22-23. Read-only endpoint output shape
# ---------------------------------------------------------------------------


class TestCapabilitiesRuntimeEndpoint:
    def _get_router(self):
        from core.routes.capabilities_runtime import create_router
        return create_router()

    def test_router_creates_without_error(self) -> None:
        router = self._get_router()
        assert router is not None

    def test_runtime_snapshot_endpoint_registered(self) -> None:
        router = self._get_router()
        paths = [r.path for r in router.routes]
        assert "/api/v1/capabilities/runtime" in paths

    def test_single_capability_endpoint_registered(self) -> None:
        router = self._get_router()
        paths = [r.path for r in router.routes]
        assert "/api/v1/capabilities/runtime/{capability_name}" in paths

    @pytest.mark.asyncio
    async def test_snapshot_endpoint_returns_expected_shape(self) -> None:
        from core.routes.capabilities_runtime import create_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(create_router())

        with TestClient(app) as client:
            resp = client.get("/api/v1/capabilities/runtime")
        assert resp.status_code == 200
        data = resp.json()
        assert "capabilities" in data
        assert "total_capabilities" in data
        assert "schema_version" in data
        assert data["schema_version"] == 1

    @pytest.mark.asyncio
    async def test_single_endpoint_returns_404_for_unknown(self) -> None:
        from core.routes.capabilities_runtime import create_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(create_router())

        with TestClient(app) as client:
            resp = client.get("/api/v1/capabilities/runtime/no_such_capability")
        assert resp.status_code == 404
        data = resp.json()
        assert data.get("not_found") is True

    @pytest.mark.asyncio
    async def test_single_endpoint_returns_200_for_registered(self) -> None:
        from core.routes.capabilities_runtime import create_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.capability_runtime import (
            CapabilityRuntimeRegistry,
            CapabilityRuntimeState,
            CapabilityAvailability,
        )

        registry = CapabilityRuntimeRegistry.get_instance()
        registry.register(
            CapabilityRuntimeState(
                name="ep_cap",
                availability=CapabilityAvailability.AVAILABLE,
            )
        )

        app = FastAPI()
        app.include_router(create_router())

        with TestClient(app) as client:
            resp = client.get("/api/v1/capabilities/runtime/ep_cap")
        assert resp.status_code == 200
        data = resp.json()
        assert data["capability_name"] == "ep_cap"
        assert data["availability"] == "available"


# ---------------------------------------------------------------------------
# 24. availability_description helper
# ---------------------------------------------------------------------------


class TestAvailabilityDescription:
    def test_all_postures_have_description(self) -> None:
        from core.capability_runtime import CapabilityAvailability, availability_description

        for posture in CapabilityAvailability:
            desc = availability_description(posture)
            assert isinstance(desc, str)
            assert len(desc) > 10

    def test_string_input_works(self) -> None:
        from core.capability_runtime import availability_description

        desc = availability_description("available")  # type: ignore[arg-type]
        assert isinstance(desc, str)
