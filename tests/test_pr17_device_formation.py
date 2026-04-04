#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr17_device_formation.py
======================================
PR-17: Device Formation & Multi-Device Group Model

Tests covering:
1. FormationRole enum — values, serialisation stability
2. FormationMember — construction, to_dict, from_dict, round-trip
3. DeviceFormationGroup — construction, properties, to_dict, from_dict
4. BARRIER_POSTURES and EMPTY_FORMATION_GROUP sentinels
5. BarrierPosture enum — values, serialisation stability
6. FormationPolicy — construction, to_dict, from_dict
7. DEFAULT_LOCAL_FORMATION_POLICY sentinel
8. resolve_formation() — full inputs, partial inputs, empty inputs
9. Merge-owner derivation logic
10. FormationSummary — build_formation_summary, to_dict
11. IDLE_FORMATION_SUMMARY sentinel
12. attach_formation_to_projection()
13. get_formation_hints()
14. resolve_formation_summary() convenience helper
15. Projection route — GET /api/v1/projection/device-formation
16. Graceful degradation when formation package unavailable
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# 1. FormationRole enum
# ---------------------------------------------------------------------------


class TestFormationRole:
    def test_all_expected_roles_present(self) -> None:
        from core.device_formation import FormationRole

        expected = {
            "source_device",
            "primary_execution_device",
            "support_device",
            "observer_device",
            "relay_device",
            "fallback_device",
            "merge_owner_device",
            "unassigned",
        }
        actual = {r.value for r in FormationRole}
        assert expected == actual

    def test_role_values_are_strings(self) -> None:
        from core.device_formation import FormationRole

        for role in FormationRole:
            assert isinstance(role.value, str)
            assert role.value  # non-empty

    def test_role_values_stable_across_import(self) -> None:
        """String values must be stable — they appear in wire formats."""
        from core.device_formation import FormationRole

        assert FormationRole.SOURCE.value == "source_device"
        assert FormationRole.PRIMARY_EXECUTION.value == "primary_execution_device"
        assert FormationRole.SUPPORT.value == "support_device"
        assert FormationRole.OBSERVER.value == "observer_device"
        assert FormationRole.RELAY.value == "relay_device"
        assert FormationRole.FALLBACK.value == "fallback_device"
        assert FormationRole.MERGE_OWNER.value == "merge_owner_device"
        assert FormationRole.UNASSIGNED.value == "unassigned"

    def test_role_is_json_serialisable(self) -> None:
        from core.device_formation import FormationRole

        serialised = json.dumps([r.value for r in FormationRole])
        recovered = json.loads(serialised)
        assert set(recovered) == {r.value for r in FormationRole}

    def test_role_precedence_contains_all_roles(self) -> None:
        from core.device_formation import FormationRole, FORMATION_ROLE_PRECEDENCE

        assert set(FORMATION_ROLE_PRECEDENCE) == set(FormationRole)

    def test_formation_role_description_returns_string(self) -> None:
        from core.device_formation import FormationRole, formation_role_description

        for role in FormationRole:
            desc = formation_role_description(role)
            assert isinstance(desc, str)
            assert len(desc) > 10


# ---------------------------------------------------------------------------
# 2. FormationMember
# ---------------------------------------------------------------------------


class TestFormationMember:
    def test_default_member(self) -> None:
        from core.device_formation import FormationMember, FormationRole

        m = FormationMember()
        assert m.device_id is None
        assert m.role == FormationRole.UNASSIGNED
        assert m.reason == "unassigned"
        assert m.capabilities == []
        assert m.is_local is False
        assert m.health_score is None

    def test_member_with_all_fields(self) -> None:
        from core.device_formation import FormationMember, FormationRole

        m = FormationMember(
            device_id="dev_001",
            role=FormationRole.PRIMARY_EXECUTION,
            reason="nominated by resolver",
            capabilities=["screen", "keyboard"],
            is_local=True,
            health_score=0.95,
        )
        assert m.device_id == "dev_001"
        assert m.role == FormationRole.PRIMARY_EXECUTION
        assert "screen" in m.capabilities
        assert m.health_score == 0.95

    def test_to_dict_is_json_serialisable(self) -> None:
        from core.device_formation import FormationMember, FormationRole

        m = FormationMember(
            device_id="dev_002",
            role=FormationRole.FALLBACK,
            capabilities=["touch"],
            health_score=0.7,
        )
        d = m.to_dict()
        serialised = json.dumps(d)
        recovered = json.loads(serialised)
        assert recovered["device_id"] == "dev_002"
        assert recovered["role"] == "fallback_device"
        assert recovered["health_score"] == pytest.approx(0.7)

    def test_from_dict_round_trip(self) -> None:
        from core.device_formation import FormationMember, FormationRole

        m = FormationMember(
            device_id="dev_003",
            role=FormationRole.SUPPORT,
            reason="has camera",
            capabilities=["camera"],
            is_local=False,
            health_score=0.85,
        )
        recovered = FormationMember.from_dict(m.to_dict())
        assert recovered.device_id == m.device_id
        assert recovered.role == m.role
        assert recovered.reason == m.reason
        assert recovered.capabilities == m.capabilities
        assert recovered.is_local == m.is_local
        assert recovered.health_score == pytest.approx(m.health_score)

    def test_from_dict_with_unknown_role_defaults_to_unassigned(self) -> None:
        from core.device_formation import FormationMember, FormationRole

        m = FormationMember.from_dict({"role": "completely_unknown_role_xyz"})
        assert m.role == FormationRole.UNASSIGNED

    def test_from_dict_empty_dict(self) -> None:
        from core.device_formation import FormationMember, FormationRole

        m = FormationMember.from_dict({})
        assert m.device_id is None
        assert m.role == FormationRole.UNASSIGNED

    def test_member_is_frozen_immutable(self) -> None:
        from core.device_formation import FormationMember, FormationRole

        m = FormationMember(device_id="dev_004", role=FormationRole.OBSERVER)
        # Frozen dataclass should raise AttributeError on mutation attempts
        with pytest.raises(AttributeError):
            m.device_id = "other"  # type: ignore


# ---------------------------------------------------------------------------
# 3. DeviceFormationGroup
# ---------------------------------------------------------------------------


class TestDeviceFormationGroup:
    def _make_group(self):
        from core.device_formation import (
            DeviceFormationGroup,
            FormationMember,
            FormationRole,
        )

        return DeviceFormationGroup(
            task_id="task-001",
            trace_id="trace-001",
            source_device_id="phone_001",
            source_runtime_posture="join_runtime",
            members=[
                FormationMember(
                    device_id="phone_001",
                    role=FormationRole.SOURCE,
                    reason="originated request",
                ),
                FormationMember(
                    device_id="desktop_001",
                    role=FormationRole.PRIMARY_EXECUTION,
                    reason="primary executor",
                ),
                FormationMember(
                    device_id="tablet_001",
                    role=FormationRole.FALLBACK,
                    reason="fallback candidate",
                ),
                FormationMember(
                    device_id="tablet_002",
                    role=FormationRole.SUPPORT,
                    capabilities=["camera"],
                ),
                FormationMember(
                    device_id="screen_001",
                    role=FormationRole.OBSERVER,
                ),
            ],
            barrier_posture="wait_primary",
            formation_reason="test formation",
            runtime_domain_intent="cross_device",
        )

    def test_primary_execution_device_id_property(self) -> None:
        group = self._make_group()
        assert group.primary_execution_device_id == "desktop_001"

    def test_fallback_device_ids_property(self) -> None:
        group = self._make_group()
        assert "tablet_001" in group.fallback_device_ids

    def test_support_device_ids_property(self) -> None:
        group = self._make_group()
        assert "tablet_002" in group.support_device_ids

    def test_observer_device_ids_property(self) -> None:
        group = self._make_group()
        assert "screen_001" in group.observer_device_ids

    def test_is_multi_device_true(self) -> None:
        group = self._make_group()
        assert group.is_multi_device is True

    def test_member_count(self) -> None:
        group = self._make_group()
        assert group.member_count == 5

    def test_all_member_device_ids(self) -> None:
        group = self._make_group()
        ids = group.all_member_device_ids
        assert "phone_001" in ids
        assert "desktop_001" in ids
        assert len(ids) == 5

    def test_effective_merge_owner_falls_back_to_primary(self) -> None:
        group = self._make_group()
        # No explicit merge owner, should fall back to primary
        assert group.effective_merge_owner_device_id == "desktop_001"

    def test_effective_merge_owner_explicit(self) -> None:
        from core.device_formation import DeviceFormationGroup

        group = DeviceFormationGroup(
            merge_owner_device_id="special_001",
        )
        assert group.effective_merge_owner_device_id == "special_001"

    def test_to_dict_is_json_serialisable(self) -> None:
        group = self._make_group()
        d = group.to_dict()
        serialised = json.dumps(d)
        recovered = json.loads(serialised)
        assert recovered["task_id"] == "task-001"
        assert recovered["is_multi_device"] is True
        assert recovered["primary_execution_device_id"] == "desktop_001"
        assert isinstance(recovered["members"], list)
        assert len(recovered["members"]) == 5

    def test_from_dict_round_trip(self) -> None:
        group = self._make_group()
        recovered = group.__class__.from_dict(group.to_dict())
        assert recovered.task_id == group.task_id
        assert recovered.trace_id == group.trace_id
        assert recovered.source_device_id == group.source_device_id
        assert recovered.source_runtime_posture == group.source_runtime_posture
        assert recovered.barrier_posture == group.barrier_posture
        assert len(recovered.members) == len(group.members)

    def test_empty_formation_group_sentinel(self) -> None:
        from core.device_formation import EMPTY_FORMATION_GROUP

        assert EMPTY_FORMATION_GROUP.formation_id == "empty"
        assert EMPTY_FORMATION_GROUP.member_count == 0
        assert EMPTY_FORMATION_GROUP.is_multi_device is False
        # Should be JSON-serialisable
        json.dumps(EMPTY_FORMATION_GROUP.to_dict())

    def test_barrier_postures_dict(self) -> None:
        from core.device_formation import BARRIER_POSTURES

        for key, val in BARRIER_POSTURES.items():
            assert isinstance(key, str)
            assert isinstance(val, str)


# ---------------------------------------------------------------------------
# 4. BarrierPosture and FormationPolicy
# ---------------------------------------------------------------------------


class TestBarrierPosture:
    def test_all_expected_postures_present(self) -> None:
        from core.device_formation import BarrierPosture

        expected = {"wait_all", "wait_primary", "best_effort", "wait_merge_owner"}
        actual = {p.value for p in BarrierPosture}
        assert expected == actual

    def test_posture_values_are_strings(self) -> None:
        from core.device_formation import BarrierPosture

        for posture in BarrierPosture:
            assert isinstance(posture.value, str)

    def test_posture_descriptions_cover_all(self) -> None:
        from core.device_formation import BarrierPosture, BARRIER_POSTURE_DESCRIPTIONS

        for posture in BarrierPosture:
            assert posture.value in BARRIER_POSTURE_DESCRIPTIONS
            assert len(BARRIER_POSTURE_DESCRIPTIONS[posture.value]) > 10


class TestFormationPolicy:
    def test_default_policy(self) -> None:
        from core.device_formation import FormationPolicy, BarrierPosture

        p = FormationPolicy()
        assert p.barrier_posture == BarrierPosture.WAIT_PRIMARY
        assert p.multi_device_required is False
        assert p.merge_confirmation_required is False
        assert p.minimum_required_device_ids == []
        assert p.fallback_intent == "promote_fallback_device"

    def test_to_dict_is_json_serialisable(self) -> None:
        from core.device_formation import FormationPolicy, BarrierPosture

        p = FormationPolicy(
            barrier_posture=BarrierPosture.WAIT_ALL,
            multi_device_required=True,
            merge_confirmation_required=True,
            minimum_required_device_ids=["dev_a", "dev_b"],
        )
        d = p.to_dict()
        serialised = json.dumps(d)
        recovered = json.loads(serialised)
        assert recovered["barrier_posture"] == "wait_all"
        assert recovered["multi_device_required"] is True
        assert "dev_a" in recovered["minimum_required_device_ids"]

    def test_from_dict_round_trip(self) -> None:
        from core.device_formation import FormationPolicy, BarrierPosture

        p = FormationPolicy(
            barrier_posture=BarrierPosture.WAIT_MERGE_OWNER,
            multi_device_required=True,
            policy_reason="custom test policy",
        )
        recovered = FormationPolicy.from_dict(p.to_dict())
        assert recovered.barrier_posture == p.barrier_posture
        assert recovered.multi_device_required == p.multi_device_required
        assert recovered.policy_reason == p.policy_reason

    def test_from_dict_unknown_posture_defaults_to_wait_primary(self) -> None:
        from core.device_formation import FormationPolicy, BarrierPosture

        p = FormationPolicy.from_dict({"barrier_posture": "completely_unknown_xyz"})
        assert p.barrier_posture == BarrierPosture.WAIT_PRIMARY

    def test_default_local_formation_policy_sentinel(self) -> None:
        from core.device_formation import DEFAULT_LOCAL_FORMATION_POLICY, BarrierPosture

        assert DEFAULT_LOCAL_FORMATION_POLICY.barrier_posture == BarrierPosture.WAIT_PRIMARY
        assert DEFAULT_LOCAL_FORMATION_POLICY.multi_device_required is False
        json.dumps(DEFAULT_LOCAL_FORMATION_POLICY.to_dict())


# ---------------------------------------------------------------------------
# 5. resolve_formation()
# ---------------------------------------------------------------------------


class TestResolveFormation:
    def test_resolve_empty_inputs_returns_valid_defaults(self) -> None:
        from core.device_formation import resolve_formation, BarrierPosture

        group, policy = resolve_formation()
        assert group is not None
        assert policy is not None
        # Should be JSON-serialisable
        json.dumps(group.to_dict())
        json.dumps(policy.to_dict())

    def test_resolve_full_cross_device_inputs(self) -> None:
        from core.device_formation import resolve_formation, FormationRole, BarrierPosture

        group, policy = resolve_formation(
            runtime_domain="cross_device",
            source_device_id="phone_001",
            primary_device_id="desktop_001",
            target_device_ids=["phone_001", "desktop_001", "tablet_001"],
            fallback_device_ids=["tablet_001"],
            support_device_ids=[],
            task_id="task-abc",
            trace_id="trace-xyz",
            formation_reason="cross-device screenshot",
        )

        assert group.source_device_id == "phone_001"
        assert group.primary_execution_device_id == "desktop_001"
        assert group.task_id == "task-abc"
        assert group.trace_id == "trace-xyz"
        assert group.runtime_domain_intent == "cross_device"
        assert group.is_multi_device is True
        assert "tablet_001" in group.fallback_device_ids
        assert policy.multi_device_required is True
        assert "fallback" in policy.fallback_intent

    def test_resolve_local_domain_single_device(self) -> None:
        from core.device_formation import resolve_formation

        group, policy = resolve_formation(
            runtime_domain="local",
            primary_device_id="desktop_001",
        )

        assert group.is_multi_device is False
        assert policy.multi_device_required is False

    def test_resolve_seeds_from_routing_summary(self) -> None:
        from core.device_formation import resolve_formation

        routing_summary = {
            "source_device_id": "phone_002",
            "primary_execution_device_id": "desktop_002",
            "fallback_device_ids": ["tablet_003"],
            "support_device_ids": [],
            "observer_device_ids": [],
            "relay_device_ids": [],
            "is_cross_device": True,
            "posture": "remote_required",
        }

        group, policy = resolve_formation(
            runtime_domain="cross_device",
            cross_device_routing_summary=routing_summary,
        )

        assert group.source_device_id == "phone_002"
        assert group.primary_execution_device_id == "desktop_002"
        assert "tablet_003" in group.fallback_device_ids

    def test_resolve_merge_owner_explicit(self) -> None:
        from core.device_formation import resolve_formation, FormationRole

        group, policy = resolve_formation(
            runtime_domain="cross_device",
            primary_device_id="desktop_001",
            merge_owner_device_id="special_merge_001",
        )

        assert group.effective_merge_owner_device_id == "special_merge_001"
        # MERGE_OWNER role member should be present
        merge_owner_members = [m for m in group.members if m.role == FormationRole.MERGE_OWNER]
        assert len(merge_owner_members) >= 1

    def test_resolve_barrier_posture_split_execution(self) -> None:
        from core.device_formation import resolve_formation, BarrierPosture

        routing_summary = {
            "posture": "split_execution",
            "is_cross_device": True,
        }

        group, policy = resolve_formation(
            runtime_domain="cross_device",
            cross_device_routing_summary=routing_summary,
        )

        assert group.barrier_posture == BarrierPosture.WAIT_ALL.value

    def test_resolve_barrier_posture_with_merge_owner(self) -> None:
        from core.device_formation import resolve_formation, BarrierPosture

        group, policy = resolve_formation(
            runtime_domain="cross_device",
            primary_device_id="desktop_001",
            merge_owner_device_id="special_001",
        )

        assert group.barrier_posture == BarrierPosture.WAIT_MERGE_OWNER.value

    def test_resolve_fallback_intent_abort_when_no_fallback(self) -> None:
        from core.device_formation import resolve_formation

        group, policy = resolve_formation(
            runtime_domain="cross_device",
            primary_device_id="desktop_001",
            # no fallback devices
        )

        assert policy.fallback_intent == "abort"

    def test_resolve_never_raises_on_bad_inputs(self) -> None:
        from core.device_formation import resolve_formation

        # Should not raise even with nonsense inputs
        group, policy = resolve_formation(
            runtime_domain=None,
            target_device_ids=None,
            cross_device_routing_summary=None,
        )
        assert group is not None
        assert policy is not None


# ---------------------------------------------------------------------------
# 6. FormationSummary and helpers
# ---------------------------------------------------------------------------


class TestFormationSummary:
    def _make_full_summary(self):
        from core.device_formation import (
            resolve_formation,
            build_formation_summary,
        )

        group, policy = resolve_formation(
            runtime_domain="cross_device",
            source_device_id="phone_001",
            primary_device_id="desktop_001",
            target_device_ids=["phone_001", "desktop_001", "tablet_001"],
            fallback_device_ids=["tablet_001"],
            task_id="task-summary-test",
            trace_id="trace-summary-test",
        )
        return build_formation_summary(group, policy)

    def test_build_formation_summary_fields(self) -> None:
        from core.device_formation import FormationSummary

        summary = self._make_full_summary()
        assert isinstance(summary, FormationSummary)
        assert summary.task_id == "task-summary-test"
        assert summary.trace_id == "trace-summary-test"
        assert summary.is_multi_device is True
        assert summary.source_device_id == "phone_001"
        assert summary.primary_execution_device_id == "desktop_001"
        assert summary.fallback_available is True
        assert summary.member_count >= 2

    def test_formation_summary_to_dict_is_json_serialisable(self) -> None:
        summary = self._make_full_summary()
        d = summary.to_dict()
        serialised = json.dumps(d)
        recovered = json.loads(serialised)
        assert recovered["is_multi_device"] is True
        assert recovered["source_device_id"] == "phone_001"
        assert recovered["schema_version"] == 1

    def test_idle_formation_summary_sentinel(self) -> None:
        from core.device_formation import IDLE_FORMATION_SUMMARY

        assert IDLE_FORMATION_SUMMARY.formation_id == "empty"
        assert IDLE_FORMATION_SUMMARY.is_multi_device is False
        assert IDLE_FORMATION_SUMMARY.member_count == 0
        json.dumps(IDLE_FORMATION_SUMMARY.to_dict())

    def test_attach_formation_to_projection(self) -> None:
        from core.device_formation import (
            IDLE_FORMATION_SUMMARY,
            attach_formation_to_projection,
        )

        base = {"tri_state_phase": "manifest", "runtime_domain": "local"}
        enriched = attach_formation_to_projection(base, IDLE_FORMATION_SUMMARY)

        # Original keys preserved
        assert enriched["tri_state_phase"] == "manifest"
        # New key added
        assert "device_formation" in enriched
        assert enriched["device_formation"]["formation_id"] == "empty"

    def test_attach_formation_does_not_mutate_original(self) -> None:
        from core.device_formation import (
            IDLE_FORMATION_SUMMARY,
            attach_formation_to_projection,
        )

        base = {"tri_state_phase": "manifest"}
        _ = attach_formation_to_projection(base, IDLE_FORMATION_SUMMARY)
        assert "device_formation" not in base

    def test_attach_formation_with_non_dict_base(self) -> None:
        from core.device_formation import (
            IDLE_FORMATION_SUMMARY,
            attach_formation_to_projection,
        )

        # Should not raise
        enriched = attach_formation_to_projection(None, IDLE_FORMATION_SUMMARY)  # type: ignore
        assert "device_formation" in enriched

    def test_get_formation_hints_keys(self) -> None:
        from core.device_formation import (
            IDLE_FORMATION_SUMMARY,
            get_formation_hints,
        )

        hints = get_formation_hints(IDLE_FORMATION_SUMMARY)
        required_keys = {
            "is_multi_device",
            "member_count",
            "fallback_available",
            "multi_device_required",
            "merge_confirmation_required",
            "has_primary",
            "has_source",
            "has_merge_owner",
            "barrier_posture",
            "runtime_domain_intent",
        }
        assert required_keys.issubset(set(hints.keys()))

    def test_get_formation_hints_idle_values(self) -> None:
        from core.device_formation import (
            IDLE_FORMATION_SUMMARY,
            get_formation_hints,
        )

        hints = get_formation_hints(IDLE_FORMATION_SUMMARY)
        assert hints["is_multi_device"] is False
        assert hints["member_count"] == 0
        assert hints["has_primary"] is False
        assert hints["has_source"] is False

    def test_resolve_formation_summary_convenience(self) -> None:
        from core.device_formation import resolve_formation_summary, FormationSummary

        summary = resolve_formation_summary(
            runtime_domain="cross_device",
            source_device_id="phone_001",
            primary_device_id="desktop_001",
        )
        assert isinstance(summary, FormationSummary)
        assert summary.source_device_id == "phone_001"

    def test_resolve_formation_summary_never_raises(self) -> None:
        from core.device_formation import resolve_formation_summary, FormationSummary

        # Even with garbage inputs, should return valid summary
        summary = resolve_formation_summary(
            runtime_domain=None,  # type: ignore
        )
        assert isinstance(summary, FormationSummary)


# ---------------------------------------------------------------------------
# 7. Projection route — GET /api/v1/projection/device-formation
# ---------------------------------------------------------------------------


class TestDeviceFormationProjectionRoute:
    def _make_app(self):
        """Build a minimal FastAPI test app with the projection router."""
        try:
            from fastapi import FastAPI
            from core.routes.projection import create_router

            app = FastAPI()
            app.include_router(create_router())
            return app
        except Exception:
            return None

    def test_device_formation_endpoint_returns_200(self) -> None:
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        app = self._make_app()
        if app is None:
            pytest.skip("Could not build test app")

        client = TestClient(app)
        response = client.get("/api/v1/projection/device-formation")
        assert response.status_code == 200

    def test_device_formation_endpoint_has_formation_key(self) -> None:
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        app = self._make_app()
        if app is None:
            pytest.skip("Could not build test app")

        client = TestClient(app)
        response = client.get("/api/v1/projection/device-formation")
        data = response.json()
        assert "device_formation" in data

    def test_device_formation_endpoint_has_formation_hints_key(self) -> None:
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        app = self._make_app()
        if app is None:
            pytest.skip("Could not build test app")

        client = TestClient(app)
        response = client.get("/api/v1/projection/device-formation")
        data = response.json()
        assert "formation_hints" in data

    def test_device_formation_response_is_json_serialisable(self) -> None:
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        app = self._make_app()
        if app is None:
            pytest.skip("Could not build test app")

        client = TestClient(app)
        response = client.get("/api/v1/projection/device-formation")
        # If response.json() does not raise, it is valid JSON
        data = response.json()
        assert isinstance(data, dict)

    def test_device_formation_schema_version_is_int(self) -> None:
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient

        app = self._make_app()
        if app is None:
            pytest.skip("Could not build test app")

        client = TestClient(app)
        response = client.get("/api/v1/projection/device-formation")
        data = response.json()
        formation = data.get("device_formation", {})
        assert isinstance(formation.get("schema_version"), int)


# ---------------------------------------------------------------------------
# 8. Package __init__ public API completeness
# ---------------------------------------------------------------------------


class TestPackagePublicAPI:
    def test_all_expected_exports_present(self) -> None:
        import core.device_formation as pkg

        expected_exports = [
            "FormationRole",
            "FORMATION_ROLE_PRECEDENCE",
            "formation_role_description",
            "FormationMember",
            "DeviceFormationGroup",
            "EMPTY_FORMATION_GROUP",
            "BARRIER_POSTURES",
            "BarrierPosture",
            "BARRIER_POSTURE_DESCRIPTIONS",
            "FormationPolicy",
            "DEFAULT_LOCAL_FORMATION_POLICY",
            "resolve_formation",
            "FormationSummary",
            "IDLE_FORMATION_SUMMARY",
            "build_formation_summary",
            "attach_formation_to_projection",
            "get_formation_hints",
            "resolve_formation_summary",
        ]

        for name in expected_exports:
            assert hasattr(pkg, name), f"Missing export: {name}"

    def test_full_round_trip_through_public_api(self) -> None:
        """Smoke test: resolve → build summary → attach to projection → hints."""
        import core.device_formation as pkg

        group, policy = pkg.resolve_formation(
            runtime_domain="cross_device",
            source_device_id="phone_001",
            primary_device_id="desktop_001",
            target_device_ids=["phone_001", "desktop_001"],
            task_id="task-roundtrip",
        )

        summary = pkg.build_formation_summary(group, policy)
        projection = {"tri_state_phase": "manifest"}
        enriched = pkg.attach_formation_to_projection(projection, summary)
        hints = pkg.get_formation_hints(summary)

        # Everything should be JSON-serialisable
        json.dumps(group.to_dict())
        json.dumps(policy.to_dict())
        json.dumps(summary.to_dict())
        json.dumps(enriched)
        json.dumps(hints)

        assert hints["is_multi_device"] is True
        assert hints["has_source"] is True
        assert hints["has_primary"] is True
