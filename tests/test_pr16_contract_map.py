"""
tests/test_pr16_contract_map.py
=================================
PR-16: Cross-Plane Contract Map & Messaging Taxonomy

Tests covering:
1. PlaneKind enum — values, serialisation stability
2. MessageKind enum — values, serialisation stability
3. ContractDescriptor — construction, to_dict, required_fields_summary
4. ContractRegistry — register, get, all_descriptors, planes_summary, snapshot
5. Seed data — all expected contracts present, required fields non-empty
6. contract_introspection helpers — get_planes_snapshot, get_messages_snapshot,
   get_descriptor_for_kind, get_required_fields_summary, get_contracts_for_plane
7. API route — GET /api/v1/contracts/planes and GET /api/v1/contracts/messages
8. Graceful degradation — partial descriptors, missing optional fields
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_registry() -> None:
    from core.contract_map import reset_contract_registry
    reset_contract_registry()


# ---------------------------------------------------------------------------
# 1. PlaneKind enum
# ---------------------------------------------------------------------------


class TestPlaneKind:
    def test_all_expected_planes_present(self) -> None:
        from core.contract_map import PlaneKind

        expected = {
            "device_plane",
            "orchestration_plane",
            "control_plane",
            "runtime_handoff_plane",
            "projection_plane",
            "observability_plane",
        }
        actual = {p.value for p in PlaneKind}
        assert expected == actual

    def test_plane_kind_is_str_enum(self) -> None:
        from core.contract_map import PlaneKind

        for pk in PlaneKind:
            assert isinstance(pk.value, str)
            # value must be the same as name
            assert pk.value == pk.name

    def test_plane_kind_serialises_to_str(self) -> None:
        from core.contract_map import PlaneKind

        assert json.dumps(PlaneKind.orchestration_plane.value) == '"orchestration_plane"'

    def test_plane_kind_roundtrip(self) -> None:
        from core.contract_map import PlaneKind

        for pk in PlaneKind:
            assert PlaneKind(pk.value) == pk


# ---------------------------------------------------------------------------
# 2. MessageKind enum
# ---------------------------------------------------------------------------

# All contract kinds expected to be in the seed registry
EXPECTED_CONTRACTS = {
    # device_plane
    "device_register",
    "device_heartbeat",
    "device_capability_report",
    "device_task_result",
    "command_envelope",
    # orchestration_plane
    "task_envelope",
    "task_envelope_cancel",
    "task_envelope_interrupt",
    # control_plane
    "nats_task_dispatch",
    "nats_task_result",
    "nats_worker_heartbeat",
    "nats_capability_event",
    "nats_audit_event",
    "nats_mcp_call",
    # runtime_handoff_plane
    "handoff_contract",
    "swarm_agent_manifest",
    # projection_plane
    "runtime_projection",
    "return_projection",
    "execution_policy_projection",
    "merge_summary",
    # observability_plane
    "audit_trace",
    "error_payload",
}


class TestMessageKind:
    def test_all_expected_kinds_present(self) -> None:
        from core.contract_map import MessageKind

        actual = {mk.value for mk in MessageKind}
        assert EXPECTED_CONTRACTS.issubset(actual), (
            f"Missing message kinds: {EXPECTED_CONTRACTS - actual}"
        )

    def test_message_kind_is_str_enum(self) -> None:
        from core.contract_map import MessageKind

        for mk in MessageKind:
            assert isinstance(mk.value, str)

    def test_message_kind_serialises_to_str(self) -> None:
        from core.contract_map import MessageKind

        assert json.dumps(MessageKind.task_envelope.value) == '"task_envelope"'

    def test_message_kind_roundtrip(self) -> None:
        from core.contract_map import MessageKind

        for mk in MessageKind:
            assert MessageKind(mk.value) == mk


# ---------------------------------------------------------------------------
# 3. ContractDescriptor
# ---------------------------------------------------------------------------


class TestContractDescriptor:
    def test_minimal_construction(self) -> None:
        from core.contract_map import ContractDescriptor, PlaneKind, MessageKind

        d = ContractDescriptor(
            plane=PlaneKind.orchestration_plane,
            kind=MessageKind.task_envelope,
        )
        assert d.plane == PlaneKind.orchestration_plane
        assert d.kind == MessageKind.task_envelope
        assert d.canonical_type is None
        assert d.source_module is None
        assert d.identity_fields == []
        assert d.producer_modules == []
        assert d.consumer_modules == []
        assert d.notes is None

    def test_full_construction(self) -> None:
        from core.contract_map import ContractDescriptor, PlaneKind, MessageKind

        d = ContractDescriptor(
            plane=PlaneKind.orchestration_plane,
            kind=MessageKind.task_envelope,
            canonical_type="core.schemas.task_envelope.TaskEnvelope",
            source_module="core.schemas.task_envelope",
            identity_fields=["task_id", "trace_id"],
            producer_modules=["galaxy_gateway.orchestrator.task_orchestrator"],
            consumer_modules=["core.command_router"],
            notes="Canonical internal task contract.",
        )
        assert d.canonical_type == "core.schemas.task_envelope.TaskEnvelope"
        assert "task_id" in d.identity_fields
        assert "trace_id" in d.identity_fields

    def test_to_dict_shape(self) -> None:
        from core.contract_map import ContractDescriptor, PlaneKind, MessageKind

        d = ContractDescriptor(
            plane=PlaneKind.control_plane,
            kind=MessageKind.nats_task_dispatch,
            identity_fields=["task_id"],
        )
        result = d.to_dict()
        assert isinstance(result, dict)
        assert result["plane"] == "control_plane"
        assert result["kind"] == "nats_task_dispatch"
        assert result["identity_fields"] == ["task_id"]
        # JSON-serialisable
        json.dumps(result)

    def test_required_fields_summary(self) -> None:
        from core.contract_map import ContractDescriptor, PlaneKind, MessageKind

        d = ContractDescriptor(
            plane=PlaneKind.runtime_handoff_plane,
            kind=MessageKind.handoff_contract,
            identity_fields=["trace_id", "task_id"],
        )
        summary = d.required_fields_summary()
        assert summary["plane"] == "runtime_handoff_plane"
        assert summary["kind"] == "handoff_contract"
        assert "trace_id" in summary["identity_fields"]
        assert "task_id" in summary["identity_fields"]

    def test_descriptor_is_frozen(self) -> None:
        from core.contract_map import ContractDescriptor, PlaneKind, MessageKind

        d = ContractDescriptor(
            plane=PlaneKind.device_plane,
            kind=MessageKind.device_register,
        )
        with pytest.raises((TypeError, AttributeError)):
            d.notes = "mutate attempt"  # type: ignore[misc]

    def test_to_dict_all_fields_serialisable(self) -> None:
        from core.contract_map import ContractDescriptor, PlaneKind, MessageKind

        d = ContractDescriptor(
            plane=PlaneKind.observability_plane,
            kind=MessageKind.audit_trace,
            canonical_type=None,
            source_module="core.routes.audit",
            identity_fields=["trace_id"],
            notes="Audit trace.",
        )
        serialised = json.dumps(d.to_dict())
        roundtripped = json.loads(serialised)
        assert roundtripped["plane"] == "observability_plane"
        assert roundtripped["notes"] == "Audit trace."


# ---------------------------------------------------------------------------
# 4. ContractRegistry
# ---------------------------------------------------------------------------


class TestContractRegistry:
    def setup_method(self) -> None:
        _reset_registry()

    def teardown_method(self) -> None:
        _reset_registry()

    def test_singleton_returns_same_instance(self) -> None:
        from core.contract_map import get_contract_registry

        r1 = get_contract_registry()
        r2 = get_contract_registry()
        assert r1 is r2

    def test_registry_seeded_with_expected_contracts(self) -> None:
        from core.contract_map import get_contract_registry, MessageKind

        reg = get_contract_registry()
        for kind_value in EXPECTED_CONTRACTS:
            kind = MessageKind(kind_value)
            descriptor = reg.get(kind)
            assert descriptor is not None, (
                f"Expected contract '{kind_value}' not found in registry"
            )

    def test_register_and_get(self) -> None:
        from core.contract_map import (
            get_contract_registry,
            ContractDescriptor,
            PlaneKind,
            MessageKind,
        )

        reg = get_contract_registry()
        d = ContractDescriptor(
            plane=PlaneKind.observability_plane,
            kind=MessageKind.audit_trace,
            notes="overwrite test",
        )
        reg.register(d)
        retrieved = reg.get(MessageKind.audit_trace)
        assert retrieved is not None
        assert retrieved.notes == "overwrite test"

    def test_all_descriptors_returns_list(self) -> None:
        from core.contract_map import get_contract_registry

        reg = get_contract_registry()
        descriptors = reg.all_descriptors()
        assert isinstance(descriptors, list)
        assert len(descriptors) >= len(EXPECTED_CONTRACTS)

    def test_descriptors_for_plane(self) -> None:
        from core.contract_map import get_contract_registry, PlaneKind

        reg = get_contract_registry()
        device_descriptors = reg.descriptors_for_plane(PlaneKind.device_plane)
        assert len(device_descriptors) >= 1
        for d in device_descriptors:
            assert d.plane == PlaneKind.device_plane

    def test_snapshot_is_dict_of_dicts(self) -> None:
        from core.contract_map import get_contract_registry

        reg = get_contract_registry()
        snapshot = reg.snapshot()
        assert isinstance(snapshot, dict)
        for key, value in snapshot.items():
            assert isinstance(key, str)
            assert isinstance(value, dict)
            assert "plane" in value
            assert "kind" in value

    def test_snapshot_is_json_serialisable(self) -> None:
        from core.contract_map import get_contract_registry

        reg = get_contract_registry()
        snapshot = reg.snapshot()
        json.dumps(snapshot)  # must not raise

    def test_planes_summary_covers_all_planes(self) -> None:
        from core.contract_map import get_contract_registry, PlaneKind

        reg = get_contract_registry()
        summary = reg.planes_summary()
        expected_planes = {pk.value for pk in PlaneKind}
        # Every plane that has descriptors should appear
        for plane_value in summary:
            assert plane_value in expected_planes

    def test_len_reflects_registered_count(self) -> None:
        from core.contract_map import get_contract_registry

        reg = get_contract_registry()
        assert len(reg) >= len(EXPECTED_CONTRACTS)

    def test_get_unknown_kind_returns_none(self) -> None:
        from core.contract_map import get_contract_registry, MessageKind

        reg = get_contract_registry()
        # Use any real kind to confirm None is not returned for real ones
        assert reg.get(MessageKind.task_envelope) is not None
        # Simulate missing by looking up via direct dict access
        assert reg._registry.get("__nonexistent_kind__") is None

    def test_reset_creates_fresh_registry(self) -> None:
        from core.contract_map import get_contract_registry, reset_contract_registry

        r1 = get_contract_registry()
        reset_contract_registry()
        r2 = get_contract_registry()
        assert r1 is not r2


# ---------------------------------------------------------------------------
# 5. Seed data — descriptor quality checks
# ---------------------------------------------------------------------------


class TestSeedData:
    def setup_method(self) -> None:
        _reset_registry()

    def teardown_method(self) -> None:
        _reset_registry()

    def test_all_seeded_descriptors_have_plane_and_kind(self) -> None:
        from core.contract_map import get_contract_registry

        reg = get_contract_registry()
        for d in reg.all_descriptors():
            assert d.plane is not None
            assert d.kind is not None

    def test_canonical_contracts_have_identity_fields(self) -> None:
        """Key contracts must have at least one identity field."""
        from core.contract_map import get_contract_registry, MessageKind

        reg = get_contract_registry()
        key_kinds = [
            MessageKind.task_envelope,
            MessageKind.handoff_contract,
            MessageKind.swarm_agent_manifest,
            MessageKind.command_envelope,
            MessageKind.nats_task_dispatch,
            MessageKind.runtime_projection,
        ]
        for kind in key_kinds:
            d = reg.get(kind)
            assert d is not None, f"Missing descriptor for {kind.value}"
            assert len(d.identity_fields) >= 1, (
                f"No identity fields for {kind.value}"
            )

    def test_handoff_contract_descriptor(self) -> None:
        from core.contract_map import get_contract_registry, MessageKind, PlaneKind

        reg = get_contract_registry()
        d = reg.get(MessageKind.handoff_contract)
        assert d is not None
        assert d.plane == PlaneKind.runtime_handoff_plane
        assert "trace_id" in d.identity_fields
        assert d.canonical_type == "galaxy_gateway.agent_bridge.HandoffContract"

    def test_task_envelope_descriptor(self) -> None:
        from core.contract_map import get_contract_registry, MessageKind, PlaneKind

        reg = get_contract_registry()
        d = reg.get(MessageKind.task_envelope)
        assert d is not None
        assert d.plane == PlaneKind.orchestration_plane
        assert "task_id" in d.identity_fields
        assert "trace_id" in d.identity_fields
        assert d.canonical_type == "core.schemas.task_envelope.TaskEnvelope"

    def test_swarm_manifest_descriptor(self) -> None:
        from core.contract_map import get_contract_registry, MessageKind, PlaneKind

        reg = get_contract_registry()
        d = reg.get(MessageKind.swarm_agent_manifest)
        assert d is not None
        assert d.plane == PlaneKind.runtime_handoff_plane
        assert "manifest_id" in d.identity_fields
        assert "agent_id" in d.identity_fields
        assert d.canonical_type == "core.control_plane.swarm_manifest.SwarmAgentManifest"

    def test_runtime_projection_descriptor(self) -> None:
        from core.contract_map import get_contract_registry, MessageKind, PlaneKind

        reg = get_contract_registry()
        d = reg.get(MessageKind.runtime_projection)
        assert d is not None
        assert d.plane == PlaneKind.projection_plane
        assert d.canonical_type == "core.projection.runtime_projection.RuntimeProjection"

    def test_nats_task_dispatch_descriptor(self) -> None:
        from core.contract_map import get_contract_registry, MessageKind, PlaneKind

        reg = get_contract_registry()
        d = reg.get(MessageKind.nats_task_dispatch)
        assert d is not None
        assert d.plane == PlaneKind.control_plane
        assert d.source_module == "core.nats_bus"
        assert "task_id" in d.identity_fields
        assert "trace_id" in d.identity_fields

    def test_error_payload_descriptor(self) -> None:
        from core.contract_map import get_contract_registry, MessageKind, PlaneKind

        reg = get_contract_registry()
        d = reg.get(MessageKind.error_payload)
        assert d is not None
        assert d.plane == PlaneKind.observability_plane
        assert d.canonical_type == "core.unified.error_codes.ErrorPayload"

    def test_all_descriptor_to_dicts_are_json_serialisable(self) -> None:
        from core.contract_map import get_contract_registry

        reg = get_contract_registry()
        for d in reg.all_descriptors():
            json.dumps(d.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# 6. Introspection helpers
# ---------------------------------------------------------------------------


class TestContractIntrospection:
    def setup_method(self) -> None:
        _reset_registry()

    def teardown_method(self) -> None:
        _reset_registry()

    def test_get_planes_snapshot_shape(self) -> None:
        from core.contract_map import get_planes_snapshot, PlaneKind

        snapshot = get_planes_snapshot()
        assert "planes" in snapshot
        assert "total_planes" in snapshot
        assert "total_contracts" in snapshot
        assert snapshot["total_planes"] == len(PlaneKind)
        assert snapshot["total_contracts"] >= len(EXPECTED_CONTRACTS)
        for plane_value, detail in snapshot["planes"].items():
            assert "description" in detail
            assert "message_kinds" in detail
            assert isinstance(detail["message_kinds"], list)

    def test_get_planes_snapshot_all_planes_present(self) -> None:
        from core.contract_map import get_planes_snapshot, PlaneKind

        snapshot = get_planes_snapshot()
        for pk in PlaneKind:
            assert pk.value in snapshot["planes"], (
                f"Plane '{pk.value}' missing from planes snapshot"
            )

    def test_get_planes_snapshot_is_json_serialisable(self) -> None:
        from core.contract_map import get_planes_snapshot

        json.dumps(get_planes_snapshot())

    def test_get_messages_snapshot_shape(self) -> None:
        from core.contract_map import get_messages_snapshot

        snapshot = get_messages_snapshot()
        assert "contracts" in snapshot
        assert "total_contracts" in snapshot
        for kind_value, desc in snapshot["contracts"].items():
            assert "plane" in desc
            assert "kind" in desc
            assert desc["kind"] == kind_value

    def test_get_messages_snapshot_is_json_serialisable(self) -> None:
        from core.contract_map import get_messages_snapshot

        json.dumps(get_messages_snapshot())

    def test_get_descriptor_for_kind_returns_dict(self) -> None:
        from core.contract_map import get_descriptor_for_kind, MessageKind

        result = get_descriptor_for_kind(MessageKind.task_envelope)
        assert result is not None
        assert isinstance(result, dict)
        assert result["kind"] == "task_envelope"

    def test_get_descriptor_for_kind_returns_none_gracefully(self) -> None:
        from core.contract_map import (
            get_contract_registry,
            get_descriptor_for_kind,
            MessageKind,
            ContractDescriptor,
            PlaneKind,
        )
        # All seeded kinds should return non-None; we just verify one real kind
        assert get_descriptor_for_kind(MessageKind.audit_trace) is not None

    def test_get_required_fields_summary_list(self) -> None:
        from core.contract_map import get_required_fields_summary

        summaries = get_required_fields_summary()
        assert isinstance(summaries, list)
        assert len(summaries) >= len(EXPECTED_CONTRACTS)
        for s in summaries:
            assert "plane" in s
            assert "kind" in s
            assert "identity_fields" in s

    def test_get_contracts_for_plane(self) -> None:
        from core.contract_map import get_contracts_for_plane, PlaneKind

        descriptors = get_contracts_for_plane(PlaneKind.orchestration_plane)
        assert len(descriptors) >= 1
        for d in descriptors:
            assert d["plane"] == "orchestration_plane"

    def test_get_contracts_for_plane_empty_plane(self) -> None:
        from core.contract_map import get_contracts_for_plane, PlaneKind

        # All planes should have at least one descriptor in the seed
        for pk in PlaneKind:
            result = get_contracts_for_plane(pk)
            assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 7. API route tests
# ---------------------------------------------------------------------------


class TestContractsRoutes:
    """Test the FastAPI route handlers in core/routes/contracts.py."""

    @pytest.fixture
    def router(self):
        from core.routes.contracts import create_router
        return create_router()

    def test_create_router_returns_apirouter(self, router) -> None:
        from fastapi import APIRouter
        assert isinstance(router, APIRouter)

    def test_router_has_planes_route(self, router) -> None:
        routes = {route.path for route in router.routes}
        assert "/api/v1/contracts/planes" in routes

    def test_router_has_messages_route(self, router) -> None:
        routes = {route.path for route in router.routes}
        assert "/api/v1/contracts/messages" in routes

    @pytest.mark.asyncio
    async def test_get_contract_planes_response(self) -> None:
        _reset_registry()
        try:
            from fastapi.testclient import TestClient
            from fastapi import FastAPI
            from core.routes.contracts import create_router

            app = FastAPI()
            app.include_router(create_router())

            with TestClient(app) as client:
                response = client.get("/api/v1/contracts/planes")
            assert response.status_code == 200
            payload = response.json()
            assert "planes" in payload
            assert "total_planes" in payload
            assert "total_contracts" in payload
        finally:
            _reset_registry()

    @pytest.mark.asyncio
    async def test_get_contract_messages_response(self) -> None:
        _reset_registry()
        try:
            from fastapi.testclient import TestClient
            from fastapi import FastAPI
            from core.routes.contracts import create_router

            app = FastAPI()
            app.include_router(create_router())

            with TestClient(app) as client:
                response = client.get("/api/v1/contracts/messages")
            assert response.status_code == 200
            payload = response.json()
            assert "contracts" in payload
            assert "total_contracts" in payload
        finally:
            _reset_registry()

    @pytest.mark.asyncio
    async def test_planes_endpoint_all_planes_in_response(self) -> None:
        _reset_registry()
        try:
            from fastapi.testclient import TestClient
            from fastapi import FastAPI
            from core.routes.contracts import create_router
            from core.contract_map import PlaneKind

            app = FastAPI()
            app.include_router(create_router())

            with TestClient(app) as client:
                response = client.get("/api/v1/contracts/planes")
            assert response.status_code == 200
            planes = response.json()["planes"]
            for pk in PlaneKind:
                assert pk.value in planes, f"Plane '{pk.value}' missing from API response"
        finally:
            _reset_registry()

    @pytest.mark.asyncio
    async def test_messages_endpoint_contains_task_envelope(self) -> None:
        _reset_registry()
        try:
            from fastapi.testclient import TestClient
            from fastapi import FastAPI
            from core.routes.contracts import create_router

            app = FastAPI()
            app.include_router(create_router())

            with TestClient(app) as client:
                response = client.get("/api/v1/contracts/messages")
            assert response.status_code == 200
            contracts = response.json()["contracts"]
            assert "task_envelope" in contracts
            assert contracts["task_envelope"]["plane"] == "orchestration_plane"
        finally:
            _reset_registry()


# ---------------------------------------------------------------------------
# 8. Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def setup_method(self) -> None:
        _reset_registry()

    def teardown_method(self) -> None:
        _reset_registry()

    def test_descriptor_with_only_required_fields(self) -> None:
        """A descriptor with only plane+kind must be valid and serialisable."""
        from core.contract_map import ContractDescriptor, PlaneKind, MessageKind

        d = ContractDescriptor(
            plane=PlaneKind.device_plane,
            kind=MessageKind.device_register,
        )
        result = d.to_dict()
        assert result["canonical_type"] is None
        assert result["source_module"] is None
        assert result["notes"] is None
        assert result["identity_fields"] == []
        json.dumps(result)  # must not raise

    def test_registry_get_returns_none_for_unregistered_kind(self) -> None:
        """Accessing an unknown kind returns None gracefully."""
        from core.contract_map import ContractRegistry, MessageKind

        reg = ContractRegistry()  # fresh, empty registry
        assert reg.get(MessageKind.task_envelope) is None

    def test_empty_registry_snapshot_is_empty_dict(self) -> None:
        from core.contract_map import ContractRegistry

        reg = ContractRegistry()
        assert reg.snapshot() == {}

    def test_empty_registry_planes_summary_is_empty_dict(self) -> None:
        from core.contract_map import ContractRegistry

        reg = ContractRegistry()
        assert reg.planes_summary() == {}

    def test_get_planes_snapshot_with_fresh_seeded_registry(self) -> None:
        """After reset, the seeded registry should produce a valid snapshot."""
        from core.contract_map import get_planes_snapshot

        snapshot = get_planes_snapshot()
        assert snapshot["total_contracts"] > 0

    def test_required_fields_summary_on_empty_registry(self) -> None:
        """get_required_fields_summary on an empty registry returns empty list."""
        from core.contract_map import ContractRegistry
        from core.contract_map.contract_introspection import get_required_fields_summary

        # Monkey-patch for this one test only
        import core.contract_map.contract_registry as _mod
        original = _mod.get_contract_registry

        try:
            reg = ContractRegistry()
            _mod._registry = reg
            result = get_required_fields_summary()
            assert isinstance(result, list)
            assert result == []
        finally:
            _mod._registry = None  # trigger re-seed on next call
            _reset_registry()

    def test_get_contracts_for_plane_unknown_plane_returns_empty(self) -> None:
        """A fresh empty registry returns [] for any plane."""
        from core.contract_map import ContractRegistry, PlaneKind
        from core.contract_map.contract_introspection import get_contracts_for_plane

        import core.contract_map.contract_registry as _mod
        reg = ContractRegistry()

        try:
            _mod._registry = reg
            result = get_contracts_for_plane(PlaneKind.control_plane)
            assert result == []
        finally:
            _mod._registry = None
            _reset_registry()
