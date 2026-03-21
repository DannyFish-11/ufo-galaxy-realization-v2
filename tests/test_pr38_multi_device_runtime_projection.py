"""tests/test_pr38_multi_device_runtime_projection.py
=======================================================
Tests for PR-38: Unified Multi-Device Runtime Projection.

Coverage:
  1.  MultiDeviceRuntimeProjection — serialisation stability (to_dict/to_json/from_dict).
  2.  MultiDeviceRuntimeProjection — stable field names.
  3.  MultiDeviceRuntimeProjection — projection_id auto-generated.
  4.  MultiDeviceRuntimeProjection — generated_at populated.
  5.  MultiDeviceRuntimeProjection — empty construction always valid.
  6.  MultiDeviceRuntimeProjection — to_compact_summary fields.
  7.  RuntimeProjectionDeviceEntry — serialisation stability.
  8.  RuntimeProjectionDeviceEntry — stable field names.
  9.  RuntimeProjectionHostEntry — serialisation stability.
  10. RuntimeProjectionHostEntry — stable field names.
  11. RuntimeProjectionMeshSessionEntry — serialisation stability.
  12. RuntimeProjectionMeshSessionEntry — stable field names.
  13. RuntimeProjectionDispatchEntry — serialisation stability.
  14. RuntimeProjectionDispatchEntry — stable field names.
  15. RuntimeProjectionHandoffEntry — serialisation stability.
  16. RuntimeProjectionHandoffEntry — stable field names.
  17. RuntimeProjectionTakeoverEntry — serialisation stability.
  18. RuntimeProjectionTakeoverEntry — stable field names.
  19. RuntimeProjectionCoordinatorEntry — serialisation stability.
  20. RuntimeProjectionCoordinatorEntry — stable field names.
  21. RuntimeProjectionResultEntry — serialisation stability.
  22. RuntimeProjectionResultEntry — stable field names.
  23. build_multi_device_runtime_projection — empty inputs.
  24. build_multi_device_runtime_projection — full inputs.
  25. build_multi_device_runtime_projection — never raises on bad input.
  26. build_multi_device_runtime_projection — None inputs.
  27. project_runtime_devices — from device dict list.
  28. project_runtime_devices — graceful with None.
  29. project_runtime_devices — graceful with empty list.
  30. project_runtime_devices — skips bad items.
  31. project_runtime_hosts — from host dict list.
  32. project_runtime_hosts — graceful with None.
  33. project_mesh_sessions — from session dict list.
  34. project_mesh_sessions — participant count populated.
  35. project_mesh_sessions — graceful with None.
  36. project_source_dispatches — from dispatch dict list.
  37. project_source_dispatches — target nested dict extracted.
  38. project_source_dispatches — graceful with None.
  39. project_handoffs — from handoff dict list.
  40. project_handoffs — source/target nested dicts extracted.
  41. project_handoffs — graceful with None.
  42. project_takeovers — from takeover dict list.
  43. project_takeovers — session_context nested dict extracted.
  44. project_takeovers — graceful with None.
  45. project_coordinator_state — from coordinator summary dict list.
  46. project_coordinator_state — pending/completed/failed counts.
  47. project_coordinator_state — graceful with None.
  48. project_merged_results — from result summary dict list.
  49. project_merged_results — result_unit_count populated.
  50. project_merged_results — graceful with None.
  51. Full projection build — all blocks combined.
  52. Full projection round-trip — to_dict/from_dict.
  53. Full projection — governance_snapshot propagated.
  54. Full projection — policy_alignment propagated.
  55. Full projection — metadata propagated.
  56. Partial projection — missing blocks produce empty lists.
  57. Partial projection — never raises on partial data.
  58. contracts package root re-exports.
  59. core.unified package re-exports.
  60. Projection endpoint — GET /api/v1/projection/runtime/multi-device (additive).
  61. Projection endpoint — returns valid JSON.
  62. Projection endpoint — stable top-level keys present.
  63. Projection endpoint — graceful when registry unavailable.
  64. build_multi_device_runtime_projection — with Pydantic model objects.
  65. MultiDeviceRuntimeProjection — repr is informative.
  66. MultiDeviceRuntimeProjection — projection_ids are unique per instance.
  67. project_runtime_devices — health_score propagated.
  68. project_mesh_sessions — merge_policy propagated.
  69. project_coordinator_state — has_result_merge_summary flag.
  70. project_merged_results — merge_policy propagated.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_device_dict(
    device_id: str = "dev_001",
    platform: str = "android",
    form_factor: str = "phone",
    status: str = "online",
    connection_state: str = "connected",
    health_score: float = 0.9,
) -> Dict[str, Any]:
    return {
        "device_id": device_id,
        "platform": platform,
        "form_factor": form_factor,
        "status": status,
        "connection_state": connection_state,
        "runtime_capable": True,
        "health_score": health_score,
        "metadata": {},
    }


def _make_host_dict(
    host_id: str = "host_001",
    device_id: str = "dev_001",
    status: str = "active",
    execution_mode: str = "local",
    accepts_handoff: bool = True,
    can_delegate: bool = False,
) -> Dict[str, Any]:
    return {
        "host_id": host_id,
        "device_id": device_id,
        "status": status,
        "execution_mode": execution_mode,
        "accepts_handoff": accepts_handoff,
        "can_delegate": can_delegate,
        "capabilities": {
            "accepts_handoff": accepts_handoff,
            "can_delegate": can_delegate,
        },
        "metadata": {},
    }


def _make_session_dict(
    session_id: str = "msess_001",
    mesh_id: str = "mesh_alpha",
    status: str = "active",
    source_device_id: str = "dev_001",
    primary_device_id: str = "dev_002",
    multi_device_required: bool = True,
    merge_policy: str = "parallel",
    participants: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "mesh_id": mesh_id,
        "status": status,
        "source_device_id": source_device_id,
        "primary_device_id": primary_device_id,
        "multi_device_required": multi_device_required,
        "merge_policy": merge_policy,
        "participants": participants or [
            {"device_id": "dev_001", "roles": ["source"]},
            {"device_id": "dev_002", "roles": ["primary"]},
        ],
        "metadata": {},
    }


def _make_dispatch_dict(
    dispatch_id: str = "disp_001",
    mode: str = "remote_handoff",
    status: str = "success",
    source_device_id: str = "dev_001",
    target_device_id: str = "dev_002",
    mesh_session_id: str = "msess_001",
) -> Dict[str, Any]:
    return {
        "dispatch_id": dispatch_id,
        "mode": mode,
        "status": status,
        "source_device_id": source_device_id,
        "target": {
            "target_device_id": target_device_id,
            "mesh_session_id": mesh_session_id,
        },
        "metadata": {},
    }


def _make_handoff_dict(
    handoff_id: str = "hoff_001",
    source_device_id: str = "dev_001",
    target_device_id: str = "dev_002",
    task_id: str = "task_001",
    session_id: str = "msess_001",
) -> Dict[str, Any]:
    return {
        "handoff_id": handoff_id,
        "source": {"device_id": source_device_id},
        "target": {"device_id": target_device_id},
        "task": {"task_id": task_id},
        "session_context": {"session_id": session_id},
        "metadata": {},
    }


def _make_takeover_dict(
    result_id: str = "tkov_001",
    status: str = "success",
    device_id: str = "dev_002",
    handoff_id: str = "hoff_001",
    session_id: str = "msess_001",
    task_id: str = "task_001",
) -> Dict[str, Any]:
    return {
        "result_id": result_id,
        "status": status,
        "session_context": {
            "device_id": device_id,
            "handoff_id": handoff_id,
            "session_id": session_id,
            "task_id": task_id,
        },
        "metadata": {},
    }


def _make_coordinator_dict(
    coordinator_id: str = "mcoord_001",
    session_id: str = "msess_001",
    mesh_id: str = "mesh_alpha",
    status: str = "active",
    participant_count: int = 2,
    pending_count: int = 1,
    completed_count: int = 1,
    failed_count: int = 0,
    has_result_merge_summary: bool = False,
) -> Dict[str, Any]:
    return {
        "coordinator_id": coordinator_id,
        "session_id": session_id,
        "mesh_id": mesh_id,
        "status": status,
        "participant_count": participant_count,
        "pending_count": pending_count,
        "completed_count": completed_count,
        "failed_count": failed_count,
        "has_result_merge_summary": has_result_merge_summary,
        "metadata": {},
    }


def _make_result_dict(
    merge_id: str = "mrg_001",
    status: str = "success",
    result_unit_count: int = 2,
    merge_policy: str = "last_write_wins",
    session_id: str = "msess_001",
) -> Dict[str, Any]:
    return {
        "merge_id": merge_id,
        "status": status,
        "result_unit_count": result_unit_count,
        "merge_policy": merge_policy,
        "session_id": session_id,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# 1. MultiDeviceRuntimeProjection — serialisation stability
# ---------------------------------------------------------------------------


class TestMultiDeviceRuntimeProjectionSerialization:
    def test_to_dict_round_trip(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        p = MultiDeviceRuntimeProjection()
        d = p.to_dict()
        p2 = MultiDeviceRuntimeProjection.from_dict(d)
        assert p2.projection_id == p.projection_id
        assert p2.generated_at == p.generated_at

    def test_to_json_valid(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        p = MultiDeviceRuntimeProjection()
        j = p.to_json()
        parsed = json.loads(j)
        assert "projection_id" in parsed

    def test_to_json_indent(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        p = MultiDeviceRuntimeProjection()
        j = p.to_json(indent=2)
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_from_dict_ignores_extra_fields(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        d = {"projection_id": "test_id", "unknown_field": "ignored", "generated_at": time.time()}
        p = MultiDeviceRuntimeProjection.from_dict(d)
        assert p.projection_id == "test_id"


# ---------------------------------------------------------------------------
# 2. MultiDeviceRuntimeProjection — stable field names
# ---------------------------------------------------------------------------


class TestMultiDeviceRuntimeProjectionFieldNames:
    def test_required_fields_present(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        p = MultiDeviceRuntimeProjection()
        d = p.to_dict()
        required_fields = [
            "projection_id",
            "generated_at",
            "runtime_devices",
            "runtime_hosts",
            "mesh_memberships",
            "mesh_sessions",
            "source_dispatches",
            "handoff_summaries",
            "takeover_summaries",
            "coordinator_summaries",
            "merged_results",
            "governance_snapshot",
            "policy_alignment",
            "metadata",
        ]
        for field in required_fields:
            assert field in d, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# 3. MultiDeviceRuntimeProjection — projection_id auto-generated
# ---------------------------------------------------------------------------


class TestMultiDeviceRuntimeProjectionAutoId:
    def test_projection_id_generated(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        p = MultiDeviceRuntimeProjection()
        assert p.projection_id is not None
        assert p.projection_id.startswith("mdrt_proj_")

    def test_projection_id_can_be_overridden(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        p = MultiDeviceRuntimeProjection(projection_id="custom_id_001")
        assert p.projection_id == "custom_id_001"


# ---------------------------------------------------------------------------
# 4. MultiDeviceRuntimeProjection — generated_at populated
# ---------------------------------------------------------------------------


class TestMultiDeviceRuntimeProjectionGeneratedAt:
    def test_generated_at_is_recent(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        before = time.time()
        p = MultiDeviceRuntimeProjection()
        after = time.time()
        assert before <= p.generated_at <= after


# ---------------------------------------------------------------------------
# 5. MultiDeviceRuntimeProjection — empty construction always valid
# ---------------------------------------------------------------------------


class TestMultiDeviceRuntimeProjectionEmptyConstruction:
    def test_empty_lists(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        p = MultiDeviceRuntimeProjection()
        assert p.runtime_devices == []
        assert p.runtime_hosts == []
        assert p.mesh_memberships == []
        assert p.mesh_sessions == []
        assert p.source_dispatches == []
        assert p.handoff_summaries == []
        assert p.takeover_summaries == []
        assert p.coordinator_summaries == []
        assert p.merged_results == []

    def test_optional_none_fields(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        p = MultiDeviceRuntimeProjection()
        assert p.governance_snapshot is None
        assert p.policy_alignment is None


# ---------------------------------------------------------------------------
# 6. MultiDeviceRuntimeProjection — to_compact_summary fields
# ---------------------------------------------------------------------------


class TestMultiDeviceRuntimeProjectionCompactSummary:
    def test_compact_summary_fields(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        p = MultiDeviceRuntimeProjection()
        s = p.to_compact_summary()
        assert "projection_id" in s
        assert "generated_at" in s
        assert "device_count" in s
        assert "host_count" in s
        assert "mesh_session_count" in s
        assert s["device_count"] == 0
        assert s["host_count"] == 0

    def test_compact_summary_counts(self):
        from contracts.multi_device_runtime_projection import (
            MultiDeviceRuntimeProjection,
            RuntimeProjectionDeviceEntry,
        )

        p = MultiDeviceRuntimeProjection(
            runtime_devices=[RuntimeProjectionDeviceEntry(device_id="d1")],
        )
        s = p.to_compact_summary()
        assert s["device_count"] == 1


# ---------------------------------------------------------------------------
# 7-8. RuntimeProjectionDeviceEntry — serialisation + field names
# ---------------------------------------------------------------------------


class TestRuntimeProjectionDeviceEntry:
    def test_serialisation(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionDeviceEntry

        e = RuntimeProjectionDeviceEntry(device_id="phone_001", platform="android")
        d = e.to_dict()
        assert d["device_id"] == "phone_001"
        assert d["platform"] == "android"

    def test_stable_field_names(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionDeviceEntry

        e = RuntimeProjectionDeviceEntry(device_id="dev_01")
        d = e.to_dict()
        for field in ["device_id", "platform", "form_factor", "status",
                      "connection_state", "runtime_capable", "health_score", "metadata"]:
            assert field in d, f"Missing: {field}"


# ---------------------------------------------------------------------------
# 9-10. RuntimeProjectionHostEntry — serialisation + field names
# ---------------------------------------------------------------------------


class TestRuntimeProjectionHostEntry:
    def test_serialisation(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionHostEntry

        e = RuntimeProjectionHostEntry(host_id="host_001", device_id="dev_001")
        d = e.to_dict()
        assert d["host_id"] == "host_001"
        assert d["device_id"] == "dev_001"

    def test_stable_field_names(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionHostEntry

        e = RuntimeProjectionHostEntry(host_id="h1")
        d = e.to_dict()
        for field in ["host_id", "device_id", "status", "execution_mode",
                      "accepts_handoff", "can_delegate", "metadata"]:
            assert field in d


# ---------------------------------------------------------------------------
# 11-12. RuntimeProjectionMeshSessionEntry — serialisation + field names
# ---------------------------------------------------------------------------


class TestRuntimeProjectionMeshSessionEntry:
    def test_serialisation(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionMeshSessionEntry

        e = RuntimeProjectionMeshSessionEntry(session_id="msess_001", status="active")
        d = e.to_dict()
        assert d["session_id"] == "msess_001"
        assert d["status"] == "active"

    def test_stable_field_names(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionMeshSessionEntry

        e = RuntimeProjectionMeshSessionEntry(session_id="s1")
        d = e.to_dict()
        for field in ["session_id", "mesh_id", "status", "source_device_id",
                      "primary_device_id", "participant_count", "multi_device_required",
                      "merge_policy", "metadata"]:
            assert field in d


# ---------------------------------------------------------------------------
# 13-14. RuntimeProjectionDispatchEntry — serialisation + field names
# ---------------------------------------------------------------------------


class TestRuntimeProjectionDispatchEntry:
    def test_serialisation(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionDispatchEntry

        e = RuntimeProjectionDispatchEntry(dispatch_id="disp_001", mode="remote_handoff")
        d = e.to_dict()
        assert d["dispatch_id"] == "disp_001"
        assert d["mode"] == "remote_handoff"

    def test_stable_field_names(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionDispatchEntry

        e = RuntimeProjectionDispatchEntry(dispatch_id="d1")
        d = e.to_dict()
        for field in ["dispatch_id", "mode", "status", "source_device_id",
                      "target_device_id", "mesh_session_id", "metadata"]:
            assert field in d


# ---------------------------------------------------------------------------
# 15-16. RuntimeProjectionHandoffEntry — serialisation + field names
# ---------------------------------------------------------------------------


class TestRuntimeProjectionHandoffEntry:
    def test_serialisation(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionHandoffEntry

        e = RuntimeProjectionHandoffEntry(handoff_id="hoff_001")
        d = e.to_dict()
        assert d["handoff_id"] == "hoff_001"

    def test_stable_field_names(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionHandoffEntry

        e = RuntimeProjectionHandoffEntry(handoff_id="h1")
        d = e.to_dict()
        for field in ["handoff_id", "source_device_id", "target_device_id",
                      "task_id", "session_id", "metadata"]:
            assert field in d


# ---------------------------------------------------------------------------
# 17-18. RuntimeProjectionTakeoverEntry — serialisation + field names
# ---------------------------------------------------------------------------


class TestRuntimeProjectionTakeoverEntry:
    def test_serialisation(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionTakeoverEntry

        e = RuntimeProjectionTakeoverEntry(result_id="tkov_001", status="success")
        d = e.to_dict()
        assert d["result_id"] == "tkov_001"
        assert d["status"] == "success"

    def test_stable_field_names(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionTakeoverEntry

        e = RuntimeProjectionTakeoverEntry(result_id="r1")
        d = e.to_dict()
        for field in ["result_id", "status", "device_id", "handoff_id",
                      "session_id", "task_id", "metadata"]:
            assert field in d


# ---------------------------------------------------------------------------
# 19-20. RuntimeProjectionCoordinatorEntry — serialisation + field names
# ---------------------------------------------------------------------------


class TestRuntimeProjectionCoordinatorEntry:
    def test_serialisation(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionCoordinatorEntry

        e = RuntimeProjectionCoordinatorEntry(coordinator_id="mcoord_001", status="active")
        d = e.to_dict()
        assert d["coordinator_id"] == "mcoord_001"
        assert d["status"] == "active"

    def test_stable_field_names(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionCoordinatorEntry

        e = RuntimeProjectionCoordinatorEntry()
        d = e.to_dict()
        for field in ["coordinator_id", "session_id", "mesh_id", "status",
                      "participant_count", "pending_count", "completed_count",
                      "failed_count", "has_result_merge_summary", "metadata"]:
            assert field in d


# ---------------------------------------------------------------------------
# 21-22. RuntimeProjectionResultEntry — serialisation + field names
# ---------------------------------------------------------------------------


class TestRuntimeProjectionResultEntry:
    def test_serialisation(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionResultEntry

        e = RuntimeProjectionResultEntry(merge_id="mrg_001", status="success")
        d = e.to_dict()
        assert d["merge_id"] == "mrg_001"
        assert d["status"] == "success"

    def test_stable_field_names(self):
        from contracts.multi_device_runtime_projection import RuntimeProjectionResultEntry

        e = RuntimeProjectionResultEntry(merge_id="m1")
        d = e.to_dict()
        for field in ["merge_id", "status", "result_unit_count", "merge_policy",
                      "session_id", "metadata"]:
            assert field in d


# ---------------------------------------------------------------------------
# 23. build_multi_device_runtime_projection — empty inputs
# ---------------------------------------------------------------------------


class TestBuildMultiDeviceRuntimeProjectionEmpty:
    def test_empty_returns_valid(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        p = build_multi_device_runtime_projection()
        assert p is not None
        assert p.runtime_devices == []
        assert p.runtime_hosts == []
        assert p.mesh_sessions == []
        assert p.coordinator_summaries == []

    def test_empty_projection_id_prefixed(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        p = build_multi_device_runtime_projection()
        assert p.projection_id.startswith("mdrt_proj_")


# ---------------------------------------------------------------------------
# 24. build_multi_device_runtime_projection — full inputs
# ---------------------------------------------------------------------------


class TestBuildMultiDeviceRuntimeProjectionFull:
    def test_full_inputs(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        p = build_multi_device_runtime_projection(
            runtime_devices=[_make_device_dict("dev_01")],
            runtime_hosts=[_make_host_dict("host_01", "dev_01")],
            mesh_memberships=[{"mesh_id": "mesh_a", "device_id": "dev_01"}],
            mesh_sessions=[_make_session_dict("msess_001")],
            source_dispatches=[_make_dispatch_dict("disp_001")],
            handoff_summaries=[_make_handoff_dict("hoff_001")],
            takeover_summaries=[_make_takeover_dict("tkov_001")],
            coordinator_summaries=[_make_coordinator_dict("mcoord_001")],
            merged_results=[_make_result_dict("mrg_001")],
            governance_snapshot={"snapshot_id": "snap_001"},
            policy_alignment={"alignment_id": "aln_001"},
            metadata={"origin": "test"},
        )
        assert len(p.runtime_devices) == 1
        assert len(p.runtime_hosts) == 1
        assert len(p.mesh_memberships) == 1
        assert len(p.mesh_sessions) == 1
        assert len(p.source_dispatches) == 1
        assert len(p.handoff_summaries) == 1
        assert len(p.takeover_summaries) == 1
        assert len(p.coordinator_summaries) == 1
        assert len(p.merged_results) == 1
        assert p.governance_snapshot is not None
        assert p.policy_alignment is not None
        assert p.metadata["origin"] == "test"


# ---------------------------------------------------------------------------
# 25. build_multi_device_runtime_projection — never raises on bad input
# ---------------------------------------------------------------------------


class TestBuildMultiDeviceRuntimeProjectionRobust:
    def test_never_raises_on_garbage(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        result = build_multi_device_runtime_projection(
            runtime_devices=["not_a_dict", None, 42, object()],
            mesh_sessions=[None, 123, "invalid"],
            coordinator_summaries=[object(), None],
        )
        assert result is not None

    def test_never_raises_on_all_none(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        result = build_multi_device_runtime_projection(
            runtime_devices=None,
            runtime_hosts=None,
            mesh_memberships=None,
            mesh_sessions=None,
            source_dispatches=None,
            handoff_summaries=None,
            takeover_summaries=None,
            coordinator_summaries=None,
            merged_results=None,
            governance_snapshot=None,
            policy_alignment=None,
            metadata=None,
        )
        assert result is not None


# ---------------------------------------------------------------------------
# 26. build_multi_device_runtime_projection — None inputs
# ---------------------------------------------------------------------------


class TestBuildMultiDeviceRuntimeProjectionNoneInputs:
    def test_none_devices_gives_empty_list(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        p = build_multi_device_runtime_projection(runtime_devices=None)
        assert p.runtime_devices == []

    def test_none_governance_gives_none(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        p = build_multi_device_runtime_projection(governance_snapshot=None)
        assert p.governance_snapshot is None


# ---------------------------------------------------------------------------
# 27. project_runtime_devices — from device dict list
# ---------------------------------------------------------------------------


class TestProjectRuntimeDevices:
    def test_basic(self):
        from contracts.multi_device_runtime_projection import project_runtime_devices

        result = project_runtime_devices([_make_device_dict("dev_01")])
        assert len(result) == 1
        assert result[0].device_id == "dev_01"
        assert result[0].platform == "android"

    def test_multiple(self):
        from contracts.multi_device_runtime_projection import project_runtime_devices

        result = project_runtime_devices([
            _make_device_dict("dev_01"),
            _make_device_dict("dev_02", platform="windows"),
        ])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# 28. project_runtime_devices — graceful with None
# ---------------------------------------------------------------------------


class TestProjectRuntimeDevicesNone:
    def test_none_returns_empty(self):
        from contracts.multi_device_runtime_projection import project_runtime_devices

        result = project_runtime_devices(None)
        assert result == []


# ---------------------------------------------------------------------------
# 29. project_runtime_devices — graceful with empty list
# ---------------------------------------------------------------------------


class TestProjectRuntimeDevicesEmpty:
    def test_empty_returns_empty(self):
        from contracts.multi_device_runtime_projection import project_runtime_devices

        result = project_runtime_devices([])
        assert result == []


# ---------------------------------------------------------------------------
# 30. project_runtime_devices — skips bad items
# ---------------------------------------------------------------------------


class TestProjectRuntimeDevicesSkipsBadItems:
    def test_skips_none(self):
        from contracts.multi_device_runtime_projection import project_runtime_devices

        # "None" as a list item has no device_id, will get auto-generated
        result = project_runtime_devices([_make_device_dict("dev_01"), None])
        # dev_01 should appear (None may or may not be skipped based on implementation)
        assert any(e.device_id == "dev_01" for e in result)


# ---------------------------------------------------------------------------
# 31. project_runtime_hosts — from host dict list
# ---------------------------------------------------------------------------


class TestProjectRuntimeHosts:
    def test_basic(self):
        from contracts.multi_device_runtime_projection import project_runtime_hosts

        result = project_runtime_hosts([_make_host_dict("host_01", "dev_01")])
        assert len(result) == 1
        assert result[0].host_id == "host_01"
        assert result[0].device_id == "dev_01"

    def test_accepts_handoff_from_capabilities(self):
        from contracts.multi_device_runtime_projection import project_runtime_hosts

        result = project_runtime_hosts([_make_host_dict(accepts_handoff=True)])
        assert result[0].accepts_handoff is True


# ---------------------------------------------------------------------------
# 32. project_runtime_hosts — graceful with None
# ---------------------------------------------------------------------------


class TestProjectRuntimeHostsNone:
    def test_none_returns_empty(self):
        from contracts.multi_device_runtime_projection import project_runtime_hosts

        assert project_runtime_hosts(None) == []


# ---------------------------------------------------------------------------
# 33. project_mesh_sessions — from session dict list
# ---------------------------------------------------------------------------


class TestProjectMeshSessions:
    def test_basic(self):
        from contracts.multi_device_runtime_projection import project_mesh_sessions

        result = project_mesh_sessions([_make_session_dict("msess_001")])
        assert len(result) == 1
        assert result[0].session_id == "msess_001"
        assert result[0].mesh_id == "mesh_alpha"


# ---------------------------------------------------------------------------
# 34. project_mesh_sessions — participant count populated
# ---------------------------------------------------------------------------


class TestProjectMeshSessionsParticipantCount:
    def test_participant_count(self):
        from contracts.multi_device_runtime_projection import project_mesh_sessions

        session = _make_session_dict(participants=[
            {"device_id": "d1"}, {"device_id": "d2"}, {"device_id": "d3"},
        ])
        result = project_mesh_sessions([session])
        assert result[0].participant_count == 3


# ---------------------------------------------------------------------------
# 35. project_mesh_sessions — graceful with None
# ---------------------------------------------------------------------------


class TestProjectMeshSessionsNone:
    def test_none_returns_empty(self):
        from contracts.multi_device_runtime_projection import project_mesh_sessions

        assert project_mesh_sessions(None) == []


# ---------------------------------------------------------------------------
# 36. project_source_dispatches — from dispatch dict list
# ---------------------------------------------------------------------------


class TestProjectSourceDispatches:
    def test_basic(self):
        from contracts.multi_device_runtime_projection import project_source_dispatches

        result = project_source_dispatches([_make_dispatch_dict("disp_001")])
        assert len(result) == 1
        assert result[0].dispatch_id == "disp_001"
        assert result[0].mode == "remote_handoff"


# ---------------------------------------------------------------------------
# 37. project_source_dispatches — target nested dict extracted
# ---------------------------------------------------------------------------


class TestProjectSourceDispatchesTarget:
    def test_target_device_extracted(self):
        from contracts.multi_device_runtime_projection import project_source_dispatches

        result = project_source_dispatches([_make_dispatch_dict(target_device_id="dev_002")])
        assert result[0].target_device_id == "dev_002"

    def test_mesh_session_id_extracted(self):
        from contracts.multi_device_runtime_projection import project_source_dispatches

        result = project_source_dispatches([_make_dispatch_dict(mesh_session_id="msess_001")])
        assert result[0].mesh_session_id == "msess_001"


# ---------------------------------------------------------------------------
# 38. project_source_dispatches — graceful with None
# ---------------------------------------------------------------------------


class TestProjectSourceDispatchesNone:
    def test_none_returns_empty(self):
        from contracts.multi_device_runtime_projection import project_source_dispatches

        assert project_source_dispatches(None) == []


# ---------------------------------------------------------------------------
# 39. project_handoffs — from handoff dict list
# ---------------------------------------------------------------------------


class TestProjectHandoffs:
    def test_basic(self):
        from contracts.multi_device_runtime_projection import project_handoffs

        result = project_handoffs([_make_handoff_dict("hoff_001")])
        assert len(result) == 1
        assert result[0].handoff_id == "hoff_001"


# ---------------------------------------------------------------------------
# 40. project_handoffs — source/target nested dicts extracted
# ---------------------------------------------------------------------------


class TestProjectHandoffsNested:
    def test_source_device_extracted(self):
        from contracts.multi_device_runtime_projection import project_handoffs

        result = project_handoffs([_make_handoff_dict(source_device_id="dev_001")])
        assert result[0].source_device_id == "dev_001"

    def test_target_device_extracted(self):
        from contracts.multi_device_runtime_projection import project_handoffs

        result = project_handoffs([_make_handoff_dict(target_device_id="dev_002")])
        assert result[0].target_device_id == "dev_002"

    def test_task_id_extracted(self):
        from contracts.multi_device_runtime_projection import project_handoffs

        result = project_handoffs([_make_handoff_dict(task_id="task_001")])
        assert result[0].task_id == "task_001"

    def test_session_id_extracted(self):
        from contracts.multi_device_runtime_projection import project_handoffs

        result = project_handoffs([_make_handoff_dict(session_id="msess_001")])
        assert result[0].session_id == "msess_001"


# ---------------------------------------------------------------------------
# 41. project_handoffs — graceful with None
# ---------------------------------------------------------------------------


class TestProjectHandoffsNone:
    def test_none_returns_empty(self):
        from contracts.multi_device_runtime_projection import project_handoffs

        assert project_handoffs(None) == []


# ---------------------------------------------------------------------------
# 42. project_takeovers — from takeover dict list
# ---------------------------------------------------------------------------


class TestProjectTakeovers:
    def test_basic(self):
        from contracts.multi_device_runtime_projection import project_takeovers

        result = project_takeovers([_make_takeover_dict("tkov_001")])
        assert len(result) == 1
        assert result[0].result_id == "tkov_001"
        assert result[0].status == "success"


# ---------------------------------------------------------------------------
# 43. project_takeovers — session_context nested dict extracted
# ---------------------------------------------------------------------------


class TestProjectTakeoversContext:
    def test_device_id_extracted(self):
        from contracts.multi_device_runtime_projection import project_takeovers

        result = project_takeovers([_make_takeover_dict(device_id="dev_002")])
        assert result[0].device_id == "dev_002"

    def test_handoff_id_extracted(self):
        from contracts.multi_device_runtime_projection import project_takeovers

        result = project_takeovers([_make_takeover_dict(handoff_id="hoff_001")])
        assert result[0].handoff_id == "hoff_001"

    def test_session_id_extracted(self):
        from contracts.multi_device_runtime_projection import project_takeovers

        result = project_takeovers([_make_takeover_dict(session_id="msess_001")])
        assert result[0].session_id == "msess_001"


# ---------------------------------------------------------------------------
# 44. project_takeovers — graceful with None
# ---------------------------------------------------------------------------


class TestProjectTakeoversNone:
    def test_none_returns_empty(self):
        from contracts.multi_device_runtime_projection import project_takeovers

        assert project_takeovers(None) == []


# ---------------------------------------------------------------------------
# 45. project_coordinator_state — from coordinator summary dict list
# ---------------------------------------------------------------------------


class TestProjectCoordinatorState:
    def test_basic(self):
        from contracts.multi_device_runtime_projection import project_coordinator_state

        result = project_coordinator_state([_make_coordinator_dict("mcoord_001")])
        assert len(result) == 1
        assert result[0].coordinator_id == "mcoord_001"
        assert result[0].session_id == "msess_001"


# ---------------------------------------------------------------------------
# 46. project_coordinator_state — pending/completed/failed counts
# ---------------------------------------------------------------------------


class TestProjectCoordinatorStateCounts:
    def test_counts_propagated(self):
        from contracts.multi_device_runtime_projection import project_coordinator_state

        result = project_coordinator_state([_make_coordinator_dict(
            pending_count=2,
            completed_count=3,
            failed_count=1,
        )])
        assert result[0].pending_count == 2
        assert result[0].completed_count == 3
        assert result[0].failed_count == 1

    def test_counts_from_device_id_lists(self):
        from contracts.multi_device_runtime_projection import project_coordinator_state

        # Simulate coordinator state with device ID lists instead of counts
        result = project_coordinator_state([{
            "coordinator_id": "c1",
            "pending_device_ids": ["d1", "d2"],
            "completed_device_ids": ["d3"],
            "failed_device_ids": [],
        }])
        assert result[0].pending_count == 2
        assert result[0].completed_count == 1
        assert result[0].failed_count == 0


# ---------------------------------------------------------------------------
# 47. project_coordinator_state — graceful with None
# ---------------------------------------------------------------------------


class TestProjectCoordinatorStateNone:
    def test_none_returns_empty(self):
        from contracts.multi_device_runtime_projection import project_coordinator_state

        assert project_coordinator_state(None) == []


# ---------------------------------------------------------------------------
# 48. project_merged_results — from result summary dict list
# ---------------------------------------------------------------------------


class TestProjectMergedResults:
    def test_basic(self):
        from contracts.multi_device_runtime_projection import project_merged_results

        result = project_merged_results([_make_result_dict("mrg_001")])
        assert len(result) == 1
        assert result[0].merge_id == "mrg_001"
        assert result[0].status == "success"


# ---------------------------------------------------------------------------
# 49. project_merged_results — result_unit_count populated
# ---------------------------------------------------------------------------


class TestProjectMergedResultsCount:
    def test_count_propagated(self):
        from contracts.multi_device_runtime_projection import project_merged_results

        result = project_merged_results([_make_result_dict(result_unit_count=5)])
        assert result[0].result_unit_count == 5

    def test_count_from_units_list(self):
        from contracts.multi_device_runtime_projection import project_merged_results

        result = project_merged_results([{
            "merge_id": "mrg_001",
            "status": "success",
            "result_units": [{"unit_id": "u1"}, {"unit_id": "u2"}, {"unit_id": "u3"}],
        }])
        assert result[0].result_unit_count == 3


# ---------------------------------------------------------------------------
# 50. project_merged_results — graceful with None
# ---------------------------------------------------------------------------


class TestProjectMergedResultsNone:
    def test_none_returns_empty(self):
        from contracts.multi_device_runtime_projection import project_merged_results

        assert project_merged_results(None) == []


# ---------------------------------------------------------------------------
# 51. Full projection build — all blocks combined
# ---------------------------------------------------------------------------


class TestFullProjectionBuild:
    def test_all_blocks(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        p = build_multi_device_runtime_projection(
            runtime_devices=[_make_device_dict("d1"), _make_device_dict("d2")],
            runtime_hosts=[_make_host_dict("h1", "d1")],
            mesh_memberships=[{"mesh_id": "mesh_a", "device_id": "d1"}],
            mesh_sessions=[_make_session_dict("s1")],
            source_dispatches=[_make_dispatch_dict("disp_1")],
            handoff_summaries=[_make_handoff_dict("ho1")],
            takeover_summaries=[_make_takeover_dict("tk1")],
            coordinator_summaries=[_make_coordinator_dict("co1")],
            merged_results=[_make_result_dict("mr1")],
        )
        assert len(p.runtime_devices) == 2
        assert len(p.runtime_hosts) == 1
        assert len(p.mesh_memberships) == 1
        assert len(p.mesh_sessions) == 1
        assert len(p.source_dispatches) == 1
        assert len(p.handoff_summaries) == 1
        assert len(p.takeover_summaries) == 1
        assert len(p.coordinator_summaries) == 1
        assert len(p.merged_results) == 1


# ---------------------------------------------------------------------------
# 52. Full projection round-trip — to_dict/from_dict
# ---------------------------------------------------------------------------


class TestFullProjectionRoundTrip:
    def test_round_trip(self):
        from contracts.multi_device_runtime_projection import (
            build_multi_device_runtime_projection,
            MultiDeviceRuntimeProjection,
        )

        p = build_multi_device_runtime_projection(
            runtime_devices=[_make_device_dict("d1")],
            mesh_sessions=[_make_session_dict("s1")],
            coordinator_summaries=[_make_coordinator_dict("c1")],
            merged_results=[_make_result_dict("m1")],
        )
        d = p.to_dict()
        p2 = MultiDeviceRuntimeProjection.from_dict(d)

        assert p2.projection_id == p.projection_id
        assert len(p2.runtime_devices) == len(p.runtime_devices)
        assert len(p2.mesh_sessions) == len(p.mesh_sessions)
        assert len(p2.coordinator_summaries) == len(p.coordinator_summaries)
        assert len(p2.merged_results) == len(p.merged_results)


# ---------------------------------------------------------------------------
# 53. Full projection — governance_snapshot propagated
# ---------------------------------------------------------------------------


class TestFullProjectionGovernanceSnapshot:
    def test_governance_snapshot_propagated(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        snap = {"snapshot_id": "snap_001", "posture": "nominal"}
        p = build_multi_device_runtime_projection(governance_snapshot=snap)
        assert p.governance_snapshot is not None
        assert p.governance_snapshot["snapshot_id"] == "snap_001"

    def test_none_governance_snapshot(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        p = build_multi_device_runtime_projection(governance_snapshot=None)
        assert p.governance_snapshot is None


# ---------------------------------------------------------------------------
# 54. Full projection — policy_alignment propagated
# ---------------------------------------------------------------------------


class TestFullProjectionPolicyAlignment:
    def test_policy_alignment_propagated(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        alignment = {"alignment_id": "aln_001", "aligned": True}
        p = build_multi_device_runtime_projection(policy_alignment=alignment)
        assert p.policy_alignment is not None
        assert p.policy_alignment["aligned"] is True

    def test_none_policy_alignment(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        p = build_multi_device_runtime_projection(policy_alignment=None)
        assert p.policy_alignment is None


# ---------------------------------------------------------------------------
# 55. Full projection — metadata propagated
# ---------------------------------------------------------------------------


class TestFullProjectionMetadata:
    def test_metadata_propagated(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        p = build_multi_device_runtime_projection(metadata={"origin": "test", "version": "38"})
        assert p.metadata["origin"] == "test"
        assert p.metadata["version"] == "38"

    def test_empty_metadata_default(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        p = build_multi_device_runtime_projection()
        assert p.metadata == {}


# ---------------------------------------------------------------------------
# 56. Partial projection — missing blocks produce empty lists
# ---------------------------------------------------------------------------


class TestPartialProjection:
    def test_only_devices_provided(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        p = build_multi_device_runtime_projection(
            runtime_devices=[_make_device_dict("d1")],
        )
        assert len(p.runtime_devices) == 1
        assert len(p.runtime_hosts) == 0
        assert len(p.mesh_sessions) == 0
        assert len(p.merged_results) == 0

    def test_only_sessions_provided(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        p = build_multi_device_runtime_projection(
            mesh_sessions=[_make_session_dict("s1")],
        )
        assert len(p.runtime_devices) == 0
        assert len(p.mesh_sessions) == 1


# ---------------------------------------------------------------------------
# 57. Partial projection — never raises on partial data
# ---------------------------------------------------------------------------


class TestPartialProjectionRobust:
    def test_never_raises(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

        for _ in range(5):
            result = build_multi_device_runtime_projection(
                runtime_devices=[_make_device_dict("d1"), "bad"],
                mesh_sessions=[None, _make_session_dict("s1"), 42],
                coordinator_summaries=[None, "bad_input"],
            )
            assert result is not None


# ---------------------------------------------------------------------------
# 58. contracts package root re-exports
# ---------------------------------------------------------------------------


class TestContractsPackageReExports:
    def test_top_level_projection_exported(self):
        from contracts import MultiDeviceRuntimeProjection
        assert MultiDeviceRuntimeProjection is not None

    def test_builder_exported(self):
        from contracts import build_multi_device_runtime_projection
        assert callable(build_multi_device_runtime_projection)

    def test_all_entry_types_exported(self):
        from contracts import (
            RuntimeProjectionDeviceEntry,
            RuntimeProjectionHostEntry,
            RuntimeProjectionMeshSessionEntry,
            RuntimeProjectionDispatchEntry,
            RuntimeProjectionHandoffEntry,
            RuntimeProjectionTakeoverEntry,
            RuntimeProjectionCoordinatorEntry,
            RuntimeProjectionResultEntry,
        )
        for cls in [
            RuntimeProjectionDeviceEntry,
            RuntimeProjectionHostEntry,
            RuntimeProjectionMeshSessionEntry,
            RuntimeProjectionDispatchEntry,
            RuntimeProjectionHandoffEntry,
            RuntimeProjectionTakeoverEntry,
            RuntimeProjectionCoordinatorEntry,
            RuntimeProjectionResultEntry,
        ]:
            assert cls is not None

    def test_all_adapter_functions_exported(self):
        from contracts import (
            project_runtime_devices,
            project_runtime_hosts,
            project_mesh_sessions,
            project_source_dispatches,
            project_handoffs,
            project_takeovers,
            project_coordinator_state,
            project_merged_results,
        )
        for fn in [
            project_runtime_devices,
            project_runtime_hosts,
            project_mesh_sessions,
            project_source_dispatches,
            project_handoffs,
            project_takeovers,
            project_coordinator_state,
            project_merged_results,
        ]:
            assert callable(fn)


# ---------------------------------------------------------------------------
# 59. core.unified package re-exports
# ---------------------------------------------------------------------------


class TestCoreUnifiedReExports:
    def test_projection_exported(self):
        from core.unified import MultiDeviceRuntimeProjection
        assert MultiDeviceRuntimeProjection is not None

    def test_builder_exported(self):
        from core.unified import build_multi_device_runtime_projection
        assert callable(build_multi_device_runtime_projection)

    def test_entry_types_exported(self):
        from core.unified import (
            RuntimeProjectionDeviceEntry,
            RuntimeProjectionHostEntry,
            RuntimeProjectionMeshSessionEntry,
            RuntimeProjectionDispatchEntry,
            RuntimeProjectionHandoffEntry,
            RuntimeProjectionTakeoverEntry,
            RuntimeProjectionCoordinatorEntry,
            RuntimeProjectionResultEntry,
        )
        assert RuntimeProjectionDeviceEntry is not None
        assert RuntimeProjectionHostEntry is not None

    def test_adapter_functions_exported(self):
        from core.unified import (
            project_runtime_devices,
            project_runtime_hosts,
            project_mesh_sessions,
            project_source_dispatches,
            project_handoffs,
            project_takeovers,
            project_coordinator_state,
            project_merged_results,
        )
        assert callable(project_runtime_devices)
        assert callable(project_merged_results)


# ---------------------------------------------------------------------------
# 60. Projection endpoint — GET /api/v1/projection/runtime/multi-device (additive)
# ---------------------------------------------------------------------------


class TestMultiDeviceProjectionEndpointAdditive:
    def test_endpoint_exists_in_router(self):
        from core.routes.projection import create_router

        router = create_router()
        routes = [r.path for r in router.routes]
        assert "/api/v1/projection/runtime/multi-device" in routes


# ---------------------------------------------------------------------------
# 61. Projection endpoint — returns valid JSON
# ---------------------------------------------------------------------------


class TestMultiDeviceProjectionEndpointResponse:
    def test_endpoint_returns_json(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/projection/runtime/multi-device")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


# ---------------------------------------------------------------------------
# 62. Projection endpoint — stable top-level keys present
# ---------------------------------------------------------------------------


class TestMultiDeviceProjectionEndpointKeys:
    def test_stable_keys_present(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/projection/runtime/multi-device")
        data = response.json()
        required_keys = [
            "projection_id",
            "generated_at",
            "runtime_devices",
            "runtime_hosts",
            "mesh_memberships",
            "mesh_sessions",
            "source_dispatches",
            "handoff_summaries",
            "takeover_summaries",
            "coordinator_summaries",
            "merged_results",
            "metadata",
        ]
        for key in required_keys:
            assert key in data, f"Missing key in response: {key}"


# ---------------------------------------------------------------------------
# 63. Projection endpoint — graceful when registry unavailable
# ---------------------------------------------------------------------------


class TestMultiDeviceProjectionEndpointGraceful:
    def test_graceful_degradation(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from core.routes.projection import create_router

        # Even if internals fail, endpoint should return 200 with a valid dict
        with patch(
            "core.mesh.body_mesh_registry.get_body_mesh_registry",
            side_effect=RuntimeError("registry unavailable"),
        ):
            app = FastAPI()
            app.include_router(create_router())
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/v1/projection/runtime/multi-device")
            assert response.status_code == 200
            data = response.json()
            assert "projection_id" in data


# ---------------------------------------------------------------------------
# 64. build_multi_device_runtime_projection — with Pydantic model objects
# ---------------------------------------------------------------------------


class TestBuildWithPydanticModels:
    def test_with_mesh_session_pydantic_model(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        from contracts.mesh_session import build_mesh_session

        session = build_mesh_session(
            source_device_id="phone_001",
            primary_device_id="tablet_002",
        )
        p = build_multi_device_runtime_projection(mesh_sessions=[session])
        assert len(p.mesh_sessions) == 1
        assert p.mesh_sessions[0].source_device_id == "phone_001"
        assert p.mesh_sessions[0].primary_device_id == "tablet_002"

    def test_with_coordinator_pydantic_model(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        from contracts.mesh_session_coordinator import build_coordinator_summary

        summary = build_coordinator_summary(
            mesh_id="mesh_alpha",
            session_id="msess_001",
        )
        p = build_multi_device_runtime_projection(coordinator_summaries=[summary])
        assert len(p.coordinator_summaries) == 1


# ---------------------------------------------------------------------------
# 65. MultiDeviceRuntimeProjection — repr is informative
# ---------------------------------------------------------------------------


class TestMultiDeviceRuntimeProjectionRepr:
    def test_repr_contains_id(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        p = MultiDeviceRuntimeProjection(projection_id="test_repr_id")
        r = repr(p)
        assert "test_repr_id" in r

    def test_repr_contains_counts(self):
        from contracts.multi_device_runtime_projection import (
            MultiDeviceRuntimeProjection,
            RuntimeProjectionDeviceEntry,
        )

        p = MultiDeviceRuntimeProjection(
            projection_id="test_repr_id",
            runtime_devices=[RuntimeProjectionDeviceEntry(device_id="d1")],
        )
        r = repr(p)
        assert "devices=1" in r


# ---------------------------------------------------------------------------
# 66. MultiDeviceRuntimeProjection — projection_ids are unique per instance
# ---------------------------------------------------------------------------


class TestProjectionIdsUnique:
    def test_unique_ids(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

        ids = {MultiDeviceRuntimeProjection().projection_id for _ in range(10)}
        assert len(ids) == 10


# ---------------------------------------------------------------------------
# 67. project_runtime_devices — health_score propagated
# ---------------------------------------------------------------------------


class TestProjectRuntimeDevicesHealthScore:
    def test_health_score(self):
        from contracts.multi_device_runtime_projection import project_runtime_devices

        result = project_runtime_devices([_make_device_dict(health_score=0.75)])
        assert result[0].health_score == pytest.approx(0.75)

    def test_missing_health_score_is_none(self):
        from contracts.multi_device_runtime_projection import project_runtime_devices

        result = project_runtime_devices([{"device_id": "dev_x"}])
        # health_score not in dict → should be None
        assert result[0].health_score is None


# ---------------------------------------------------------------------------
# 68. project_mesh_sessions — merge_policy propagated
# ---------------------------------------------------------------------------


class TestProjectMeshSessionsMergePolicy:
    def test_merge_policy(self):
        from contracts.multi_device_runtime_projection import project_mesh_sessions

        result = project_mesh_sessions([_make_session_dict(merge_policy="parallel")])
        assert result[0].merge_policy == "parallel"


# ---------------------------------------------------------------------------
# 69. project_coordinator_state — has_result_merge_summary flag
# ---------------------------------------------------------------------------


class TestProjectCoordinatorStateFlag:
    def test_flag_true(self):
        from contracts.multi_device_runtime_projection import project_coordinator_state

        result = project_coordinator_state([_make_coordinator_dict(has_result_merge_summary=True)])
        assert result[0].has_result_merge_summary is True

    def test_flag_false(self):
        from contracts.multi_device_runtime_projection import project_coordinator_state

        result = project_coordinator_state([_make_coordinator_dict(has_result_merge_summary=False)])
        assert result[0].has_result_merge_summary is False

    def test_flag_inferred_from_result_merge_summary(self):
        from contracts.multi_device_runtime_projection import project_coordinator_state

        result = project_coordinator_state([{
            "coordinator_id": "c1",
            "result_merge_summary": {"merge_id": "m1"},
        }])
        assert result[0].has_result_merge_summary is True


# ---------------------------------------------------------------------------
# 70. project_merged_results — merge_policy propagated
# ---------------------------------------------------------------------------


class TestProjectMergedResultsMergePolicy:
    def test_merge_policy(self):
        from contracts.multi_device_runtime_projection import project_merged_results

        result = project_merged_results([_make_result_dict(merge_policy="last_write_wins")])
        assert result[0].merge_policy == "last_write_wins"

    def test_session_id_propagated(self):
        from contracts.multi_device_runtime_projection import project_merged_results

        result = project_merged_results([_make_result_dict(session_id="msess_001")])
        assert result[0].session_id == "msess_001"
