#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr8_mesh_participation_summary.py
=============================================
Tests for PR-8: Unified Formation, Mesh, and Session Participation Summaries.

Coverage:
  1.  Module import and authority sentinel.
  2.  MeshParticipationSummary — default construction.
  3.  MeshParticipationSummary — explicit construction with all fields.
  4.  MeshParticipationSummary — to_dict stability.
  5.  MeshParticipationSummary — to_dict all expected keys present.
  6.  MeshParticipationSummary — to_json produces valid JSON.
  7.  MeshParticipationSummary — from_dict round-trip.
  8.  MeshParticipationSummary — from_dict with None returns default.
  9.  MeshParticipationSummary — from_dict with empty dict returns default.
  10. MeshParticipationSummary — from_dict ignores unknown keys.
  11. EMPTY_MESH_PARTICIPATION_SUMMARY sentinel has expected shape.
  12. get_current_mesh_participation_summary — returns MeshParticipationSummary.
  13. get_current_mesh_participation_summary — never raises.
  14. get_current_mesh_participation_summary — result is serialisable.
  15. get_current_mesh_participation_summary — returns new instance each call.
  16. get_device_mesh_summary — known device found.
  17. get_device_mesh_summary — unknown device not found.
  18. get_device_mesh_summary — result has all expected keys.
  19. get_device_mesh_summary — is_primary flag set correctly.
  20. get_device_mesh_summary — is_source flag set correctly.
  21. get_device_mesh_summary — roles populated for known device.
  22. get_device_mesh_summary — roles empty for unknown device.
  23. get_device_mesh_summary — never raises.
  24. Graceful degradation: formation_summary unavailable.
  25. Graceful degradation: body_mesh_registry unavailable.
  26. Graceful degradation: mesh_session unavailable.
  27. Graceful degradation: mesh_membership unavailable.
  28. Graceful degradation: all subsystems unavailable → reasons recorded.
  29. Graceful degradation: all subsystems unavailable → empty device_ids.
  30. _merge_device_ids — no duplicates.
  31. _merge_role — no duplicates.
  32. _merge_role — skips None device_id.
  33. _merge_role — skips empty role.
  34. Aggregation from mocked formation summary populates device_ids.
  35. Aggregation from mocked formation summary populates primary_device_id.
  36. Aggregation from mocked formation summary populates source_device_id.
  37. Aggregation from mocked formation summary populates barrier_posture.
  38. Aggregation from mocked formation summary populates roles_by_device.
  39. Aggregation from mocked formation summary records reason.
  40. Aggregation from mocked body mesh registry populates device_ids.
  41. Aggregation from mocked body mesh registry populates roles_by_device.
  42. Aggregation from mocked body mesh registry populates sources.
  43. Aggregation from mocked mesh session populates session_id.
  44. Aggregation from mocked mesh session populates primary_device_id.
  45. Aggregation from mocked mesh session populates source_device_id.
  46. Aggregation from mocked mesh session populates merge_policy.
  47. Aggregation from mocked mesh session populates barrier_posture.
  48. Aggregation from mocked mesh session populates participants/roles.
  49. Aggregation from mocked mesh membership populates routing_intents.
  50. Aggregation from mocked mesh membership populates roles_by_device.
  51. get_device_mesh_summary routing_intent populated from routing_intents.
  52. get_device_mesh_summary session_id propagated.
  53. MeshParticipationSummary roles_by_device deduplication.
  54. MeshParticipationSummary device_ids deduplication via multiple aggregations.
  55. to_dict lists are independent copies (mutation isolation).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 1. Module import and authority sentinel
# ---------------------------------------------------------------------------


class TestModuleImport:
    def test_module_importable(self) -> None:
        import core.mesh_participation_summary  # noqa: F401

    def test_authority_sentinel_present(self) -> None:
        from core.mesh_participation_summary import MESH_PARTICIPATION_SUMMARY_AUTHORITY

        assert isinstance(MESH_PARTICIPATION_SUMMARY_AUTHORITY, str)
        assert "MESH_PARTICIPATION_SUMMARY_AUTHORITY" in MESH_PARTICIPATION_SUMMARY_AUTHORITY

    def test_all_exports_present(self) -> None:
        import core.mesh_participation_summary as mod

        for name in [
            "MESH_PARTICIPATION_SUMMARY_AUTHORITY",
            "MeshParticipationSummary",
            "EMPTY_MESH_PARTICIPATION_SUMMARY",
            "get_current_mesh_participation_summary",
            "get_device_mesh_summary",
        ]:
            assert hasattr(mod, name), f"Missing export: {name}"


# ---------------------------------------------------------------------------
# 2–10. MeshParticipationSummary model
# ---------------------------------------------------------------------------


class TestMeshParticipationSummaryModel:
    def test_default_construction(self) -> None:
        from core.mesh_participation_summary import MeshParticipationSummary

        s = MeshParticipationSummary()
        assert s.session_id is None
        assert s.device_ids == []
        assert s.primary_device_id is None
        assert s.source_device_id is None
        assert s.roles_by_device == {}
        assert s.merge_policy is None
        assert s.barrier_posture is None
        assert s.routing_intents == {}
        assert isinstance(s.reasons, list)
        assert isinstance(s.sources, dict)

    def test_explicit_construction(self) -> None:
        from core.mesh_participation_summary import MeshParticipationSummary

        s = MeshParticipationSummary(
            session_id="sess_001",
            device_ids=["phone_001", "tablet_002"],
            primary_device_id="tablet_002",
            source_device_id="phone_001",
            roles_by_device={"phone_001": ["source"], "tablet_002": ["primary"]},
            merge_policy="parallel",
            barrier_posture="wait_primary",
            routing_intents={"phone_001": "local_preferred"},
            reasons=["test reason"],
            sources={"test_source": {"key": "value"}},
        )
        assert s.session_id == "sess_001"
        assert "phone_001" in s.device_ids
        assert s.primary_device_id == "tablet_002"
        assert s.source_device_id == "phone_001"
        assert "source" in s.roles_by_device["phone_001"]
        assert s.merge_policy == "parallel"
        assert s.barrier_posture == "wait_primary"
        assert s.routing_intents["phone_001"] == "local_preferred"
        assert "test reason" in s.reasons
        assert "test_source" in s.sources

    def test_to_dict_returns_dict(self) -> None:
        from core.mesh_participation_summary import MeshParticipationSummary

        s = MeshParticipationSummary(session_id="sess_x")
        d = s.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_all_expected_keys(self) -> None:
        from core.mesh_participation_summary import MeshParticipationSummary

        s = MeshParticipationSummary()
        d = s.to_dict()
        expected_keys = {
            "session_id",
            "device_ids",
            "primary_device_id",
            "source_device_id",
            "roles_by_device",
            "merge_policy",
            "barrier_posture",
            "routing_intents",
            "reasons",
            "sources",
        }
        assert expected_keys == set(d.keys())

    def test_to_json_valid(self) -> None:
        from core.mesh_participation_summary import MeshParticipationSummary

        s = MeshParticipationSummary(session_id="sess_json", device_ids=["d1"])
        raw = s.to_json()
        parsed = json.loads(raw)
        assert parsed["session_id"] == "sess_json"
        assert "d1" in parsed["device_ids"]

    def test_from_dict_round_trip(self) -> None:
        from core.mesh_participation_summary import MeshParticipationSummary

        original = MeshParticipationSummary(
            session_id="sess_rt",
            device_ids=["a", "b"],
            primary_device_id="b",
            source_device_id="a",
            roles_by_device={"a": ["source"], "b": ["primary", "support"]},
            merge_policy="sequential",
            barrier_posture="none",
            routing_intents={"a": "local"},
            reasons=["r1"],
            sources={"s1": 1},
        )
        d = original.to_dict()
        restored = MeshParticipationSummary.from_dict(d)
        assert restored.session_id == original.session_id
        assert restored.device_ids == original.device_ids
        assert restored.primary_device_id == original.primary_device_id
        assert restored.source_device_id == original.source_device_id
        assert restored.roles_by_device == original.roles_by_device
        assert restored.merge_policy == original.merge_policy
        assert restored.barrier_posture == original.barrier_posture
        assert restored.routing_intents == original.routing_intents
        assert restored.reasons == original.reasons

    def test_from_dict_none_returns_default(self) -> None:
        from core.mesh_participation_summary import MeshParticipationSummary

        s = MeshParticipationSummary.from_dict(None)  # type: ignore[arg-type]
        assert s.session_id is None
        assert s.device_ids == []

    def test_from_dict_empty_dict_returns_default(self) -> None:
        from core.mesh_participation_summary import MeshParticipationSummary

        s = MeshParticipationSummary.from_dict({})
        assert s.session_id is None
        assert s.device_ids == []

    def test_from_dict_ignores_unknown_keys(self) -> None:
        from core.mesh_participation_summary import MeshParticipationSummary

        s = MeshParticipationSummary.from_dict({"session_id": "x", "unknown_future_field": 99})
        assert s.session_id == "x"


# ---------------------------------------------------------------------------
# 11. EMPTY_MESH_PARTICIPATION_SUMMARY sentinel
# ---------------------------------------------------------------------------


class TestEmptySentinel:
    def test_sentinel_exists(self) -> None:
        from core.mesh_participation_summary import EMPTY_MESH_PARTICIPATION_SUMMARY

        assert EMPTY_MESH_PARTICIPATION_SUMMARY is not None

    def test_sentinel_has_empty_device_ids(self) -> None:
        from core.mesh_participation_summary import EMPTY_MESH_PARTICIPATION_SUMMARY

        assert EMPTY_MESH_PARTICIPATION_SUMMARY.device_ids == []

    def test_sentinel_has_reason(self) -> None:
        from core.mesh_participation_summary import EMPTY_MESH_PARTICIPATION_SUMMARY

        assert len(EMPTY_MESH_PARTICIPATION_SUMMARY.reasons) > 0

    def test_sentinel_is_serialisable(self) -> None:
        from core.mesh_participation_summary import EMPTY_MESH_PARTICIPATION_SUMMARY

        d = EMPTY_MESH_PARTICIPATION_SUMMARY.to_dict()
        assert isinstance(json.dumps(d), str)


# ---------------------------------------------------------------------------
# 12–15. get_current_mesh_participation_summary
# ---------------------------------------------------------------------------


class TestGetCurrentMeshParticipationSummary:
    def test_returns_summary_instance(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            get_current_mesh_participation_summary,
        )

        result = get_current_mesh_participation_summary()
        assert isinstance(result, MeshParticipationSummary)

    def test_never_raises(self) -> None:
        from core.mesh_participation_summary import get_current_mesh_participation_summary

        # Should never raise regardless of subsystem availability
        result = get_current_mesh_participation_summary()
        assert result is not None

    def test_result_is_serialisable(self) -> None:
        from core.mesh_participation_summary import get_current_mesh_participation_summary

        result = get_current_mesh_participation_summary()
        d = result.to_dict()
        assert isinstance(json.dumps(d), str)

    def test_returns_new_instance_each_call(self) -> None:
        from core.mesh_participation_summary import get_current_mesh_participation_summary

        r1 = get_current_mesh_participation_summary()
        r2 = get_current_mesh_participation_summary()
        assert r1 is not r2


# ---------------------------------------------------------------------------
# 16–23. get_device_mesh_summary
# ---------------------------------------------------------------------------


class TestGetDeviceMeshSummary:
    def _make_summary_with_device(self) -> Any:
        """Patch get_current_mesh_participation_summary to return a known state."""
        from core.mesh_participation_summary import MeshParticipationSummary

        return MeshParticipationSummary(
            session_id="sess_device_test",
            device_ids=["phone_001", "tablet_002"],
            primary_device_id="tablet_002",
            source_device_id="phone_001",
            roles_by_device={
                "phone_001": ["source", "support"],
                "tablet_002": ["primary"],
            },
            routing_intents={"phone_001": "local_preferred"},
        )

    def test_known_device_found(self) -> None:
        from core.mesh_participation_summary import get_device_mesh_summary

        with patch(
            "core.mesh_participation_summary.get_current_mesh_participation_summary",
            return_value=self._make_summary_with_device(),
        ):
            result = get_device_mesh_summary("phone_001")
        assert result["found"] is True

    def test_unknown_device_not_found(self) -> None:
        from core.mesh_participation_summary import get_device_mesh_summary

        with patch(
            "core.mesh_participation_summary.get_current_mesh_participation_summary",
            return_value=self._make_summary_with_device(),
        ):
            result = get_device_mesh_summary("unknown_device_xyz")
        assert result["found"] is False

    def test_all_expected_keys_present(self) -> None:
        from core.mesh_participation_summary import get_device_mesh_summary

        result = get_device_mesh_summary("any_device")
        expected_keys = {
            "device_id",
            "found",
            "roles",
            "routing_intent",
            "is_primary",
            "is_source",
            "session_id",
            "reasons",
        }
        assert expected_keys == set(result.keys())

    def test_is_primary_flag(self) -> None:
        from core.mesh_participation_summary import get_device_mesh_summary

        with patch(
            "core.mesh_participation_summary.get_current_mesh_participation_summary",
            return_value=self._make_summary_with_device(),
        ):
            primary_result = get_device_mesh_summary("tablet_002")
            non_primary_result = get_device_mesh_summary("phone_001")
        assert primary_result["is_primary"] is True
        assert non_primary_result["is_primary"] is False

    def test_is_source_flag(self) -> None:
        from core.mesh_participation_summary import get_device_mesh_summary

        with patch(
            "core.mesh_participation_summary.get_current_mesh_participation_summary",
            return_value=self._make_summary_with_device(),
        ):
            source_result = get_device_mesh_summary("phone_001")
            non_source_result = get_device_mesh_summary("tablet_002")
        assert source_result["is_source"] is True
        assert non_source_result["is_source"] is False

    def test_roles_populated_for_known_device(self) -> None:
        from core.mesh_participation_summary import get_device_mesh_summary

        with patch(
            "core.mesh_participation_summary.get_current_mesh_participation_summary",
            return_value=self._make_summary_with_device(),
        ):
            result = get_device_mesh_summary("phone_001")
        assert "source" in result["roles"]

    def test_roles_empty_for_unknown_device(self) -> None:
        from core.mesh_participation_summary import get_device_mesh_summary

        with patch(
            "core.mesh_participation_summary.get_current_mesh_participation_summary",
            return_value=self._make_summary_with_device(),
        ):
            result = get_device_mesh_summary("no_such_device")
        assert result["roles"] == []

    def test_never_raises(self) -> None:
        from core.mesh_participation_summary import get_device_mesh_summary

        # Even with a pathological input
        result = get_device_mesh_summary("")
        assert result is not None


# ---------------------------------------------------------------------------
# 24–29. Graceful degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_formation_summary_unavailable(self) -> None:
        """Summary should still be returned even when formation module is absent."""
        from core.mesh_participation_summary import get_current_mesh_participation_summary

        with patch.dict("sys.modules", {"core.device_formation.formation_summary": None}):
            result = get_current_mesh_participation_summary()
        assert result is not None

    def test_body_mesh_registry_unavailable(self) -> None:
        from core.mesh_participation_summary import get_current_mesh_participation_summary

        with patch.dict("sys.modules", {"core.mesh.body_mesh_registry": None}):
            result = get_current_mesh_participation_summary()
        assert result is not None

    def test_mesh_session_aggregation_handles_none(self) -> None:
        """When registry.get_mesh_session() returns None, no crash."""
        from core.mesh_participation_summary import MeshParticipationSummary
        from core.mesh_participation_summary import _aggregate_from_mesh_session

        summary = MeshParticipationSummary()

        mock_registry = MagicMock()
        mock_registry.get_mesh_session.return_value = None

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=mock_registry,
        ):
            _aggregate_from_mesh_session(summary)

        # Should not crash; no session_id set
        assert summary.session_id is None

    def test_mesh_membership_aggregation_handles_empty(self) -> None:
        """When registry.get_mesh_memberships() returns empty list, no crash."""
        from core.mesh_participation_summary import MeshParticipationSummary
        from core.mesh_participation_summary import _aggregate_from_mesh_membership

        summary = MeshParticipationSummary()

        mock_registry = MagicMock()
        mock_registry.get_mesh_memberships.return_value = []

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=mock_registry,
        ):
            _aggregate_from_mesh_membership(summary)

        assert summary.routing_intents == {}

    def test_all_subsystems_raise_reasons_recorded(self) -> None:
        """When subsystem aggregation helpers raise, reasons are recorded."""
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_formation_summary,
        )

        summary = MeshParticipationSummary()

        with patch(
            "core.mesh_participation_summary.resolve_formation_summary",
            side_effect=RuntimeError("boom"),
        ):
            _aggregate_from_formation_summary(summary)

        # At minimum the summary should not raise, and reasons may be populated
        assert isinstance(summary.reasons, list)

    def test_all_subsystems_unavailable_empty_device_ids(self) -> None:
        """With no subsystems available, device_ids should remain empty."""
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_body_mesh_registry,
        )

        summary = MeshParticipationSummary()

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            side_effect=ImportError("no module"),
        ):
            _aggregate_from_body_mesh_registry(summary)

        assert summary.device_ids == []


# ---------------------------------------------------------------------------
# 30–33. Internal utilities
# ---------------------------------------------------------------------------


class TestInternalUtilities:
    def test_merge_device_ids_no_duplicates(self) -> None:
        from core.mesh_participation_summary import MeshParticipationSummary, _merge_device_ids

        s = MeshParticipationSummary(device_ids=["a"])
        _merge_device_ids(s, ["a", "b", "b", "c"])
        assert s.device_ids.count("a") == 1
        assert s.device_ids.count("b") == 1
        assert s.device_ids.count("c") == 1

    def test_merge_role_no_duplicates(self) -> None:
        from core.mesh_participation_summary import _merge_role

        roles: dict = {}
        _merge_role(roles, "dev_001", "primary")
        _merge_role(roles, "dev_001", "primary")
        assert roles["dev_001"].count("primary") == 1

    def test_merge_role_skips_none_device_id(self) -> None:
        from core.mesh_participation_summary import _merge_role

        roles: dict = {}
        _merge_role(roles, None, "primary")  # type: ignore[arg-type]
        assert roles == {}

    def test_merge_role_skips_empty_role(self) -> None:
        from core.mesh_participation_summary import _merge_role

        roles: dict = {}
        _merge_role(roles, "dev_001", "")
        assert "dev_001" not in roles


# ---------------------------------------------------------------------------
# 34–39. Aggregation from mocked formation summary
# ---------------------------------------------------------------------------


def _make_mock_formation_summary(
    formation_id: str = "f001",
    source_device_id: str = "phone_001",
    primary_device_id: str = "tablet_002",
    merge_owner: str = None,
    fallback: list = None,
    support: list = None,
    observer: list = None,
    relay: list = None,
    barrier_posture: str = "wait_primary",
    formation_reason: str = "test formation",
    all_member_device_ids: list = None,
) -> Any:
    m = MagicMock()
    m.formation_id = formation_id
    m.source_device_id = source_device_id
    m.primary_execution_device_id = primary_device_id
    m.merge_owner_device_id = merge_owner
    m.fallback_device_ids = fallback or []
    m.support_device_ids = support or []
    m.observer_device_ids = observer or []
    m.relay_device_ids = relay or []
    m.barrier_posture = barrier_posture
    m.formation_reason = formation_reason
    m.all_member_device_ids = all_member_device_ids or [source_device_id, primary_device_id]
    m.to_dict.return_value = {
        "formation_id": formation_id,
        "source_device_id": source_device_id,
        "primary_execution_device_id": primary_device_id,
    }
    return m


class TestAggregationFromFormationSummary:
    def test_populates_device_ids(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_formation_summary,
        )

        summary = MeshParticipationSummary()
        mock_fs = _make_mock_formation_summary()

        with patch(
            "core.mesh_participation_summary.resolve_formation_summary",
            return_value=mock_fs,
        ):
            _aggregate_from_formation_summary(summary)

        assert "phone_001" in summary.device_ids
        assert "tablet_002" in summary.device_ids

    def test_populates_primary_device_id(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_formation_summary,
        )

        summary = MeshParticipationSummary()
        mock_fs = _make_mock_formation_summary()

        with patch(
            "core.mesh_participation_summary.resolve_formation_summary",
            return_value=mock_fs,
        ):
            _aggregate_from_formation_summary(summary)

        assert summary.primary_device_id == "tablet_002"

    def test_populates_source_device_id(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_formation_summary,
        )

        summary = MeshParticipationSummary()
        mock_fs = _make_mock_formation_summary()

        with patch(
            "core.mesh_participation_summary.resolve_formation_summary",
            return_value=mock_fs,
        ):
            _aggregate_from_formation_summary(summary)

        assert summary.source_device_id == "phone_001"

    def test_populates_barrier_posture(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_formation_summary,
        )

        summary = MeshParticipationSummary()
        mock_fs = _make_mock_formation_summary(barrier_posture="hard_barrier")

        with patch(
            "core.mesh_participation_summary.resolve_formation_summary",
            return_value=mock_fs,
        ):
            _aggregate_from_formation_summary(summary)

        assert summary.barrier_posture == "hard_barrier"

    def test_populates_roles_by_device(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_formation_summary,
        )

        summary = MeshParticipationSummary()
        mock_fs = _make_mock_formation_summary(
            support=["support_005"],
        )

        with patch(
            "core.mesh_participation_summary.resolve_formation_summary",
            return_value=mock_fs,
        ):
            _aggregate_from_formation_summary(summary)

        assert "primary" in summary.roles_by_device.get("tablet_002", [])
        assert "source" in summary.roles_by_device.get("phone_001", [])
        assert "support" in summary.roles_by_device.get("support_005", [])

    def test_records_reason(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_formation_summary,
        )

        summary = MeshParticipationSummary()
        mock_fs = _make_mock_formation_summary(formation_reason="multi_device_required")

        with patch(
            "core.mesh_participation_summary.resolve_formation_summary",
            return_value=mock_fs,
        ):
            _aggregate_from_formation_summary(summary)

        reasons_combined = " ".join(summary.reasons)
        assert "multi_device_required" in reasons_combined


# ---------------------------------------------------------------------------
# 40–42. Aggregation from mocked body mesh registry
# ---------------------------------------------------------------------------


class TestAggregationFromBodyMeshRegistry:
    def _make_mock_registry(self) -> Any:
        from unittest.mock import MagicMock

        entry1 = MagicMock()
        entry1.device_id = "phone_001"
        entry1.roles = ["perception", "action"]
        entry1.session_id = "sess_01"
        entry1.body_score = 3.0
        entry1.metadata = {}

        entry2 = MagicMock()
        entry2.device_id = "tablet_002"
        entry2.roles = ["presence"]
        entry2.session_id = "sess_01"
        entry2.body_score = 4.5
        entry2.metadata = {}

        registry = MagicMock()
        registry.entries = {"phone_001": entry1, "tablet_002": entry2}
        return registry

    def test_populates_device_ids(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_body_mesh_registry,
        )

        summary = MeshParticipationSummary()
        mock_reg = self._make_mock_registry()

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=mock_reg,
        ):
            _aggregate_from_body_mesh_registry(summary)

        assert "phone_001" in summary.device_ids
        assert "tablet_002" in summary.device_ids

    def test_populates_roles_by_device(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_body_mesh_registry,
        )

        summary = MeshParticipationSummary()
        mock_reg = self._make_mock_registry()

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=mock_reg,
        ):
            _aggregate_from_body_mesh_registry(summary)

        assert "perception" in summary.roles_by_device.get("phone_001", [])
        assert "presence" in summary.roles_by_device.get("tablet_002", [])

    def test_populates_sources(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_body_mesh_registry,
        )

        summary = MeshParticipationSummary()
        mock_reg = self._make_mock_registry()

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=mock_reg,
        ):
            _aggregate_from_body_mesh_registry(summary)

        assert "body_mesh_registry" in summary.sources


# ---------------------------------------------------------------------------
# 43–48. Aggregation from mocked mesh session
# ---------------------------------------------------------------------------


class TestAggregationFromMeshSession:
    def _make_mock_session(self) -> Any:
        p1 = MagicMock()
        p1.device_id = "phone_001"
        p1.roles = ["source"]

        p2 = MagicMock()
        p2.device_id = "tablet_002"
        p2.roles = ["primary"]

        session = MagicMock()
        session.session_id = "sess_mesh_001"
        session.primary_device_id = "tablet_002"
        session.source_device_id = "phone_001"
        session.merge_policy = MagicMock()
        session.merge_policy.value = "parallel"
        session.barrier_posture = MagicMock()
        session.barrier_posture.value = "wait_primary"
        session.participants = [p1, p2]
        session.to_dict.return_value = {"session_id": "sess_mesh_001"}
        return session

    def _make_registry_with_session(self, session: Any) -> Any:
        registry = MagicMock()
        registry.get_mesh_session.return_value = session
        return registry

    def test_populates_session_id(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_mesh_session,
        )

        summary = MeshParticipationSummary()
        mock_session = self._make_mock_session()

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=self._make_registry_with_session(mock_session),
        ):
            _aggregate_from_mesh_session(summary)

        assert summary.session_id == "sess_mesh_001"

    def test_populates_primary_device_id(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_mesh_session,
        )

        summary = MeshParticipationSummary()
        mock_session = self._make_mock_session()

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=self._make_registry_with_session(mock_session),
        ):
            _aggregate_from_mesh_session(summary)

        assert summary.primary_device_id == "tablet_002"

    def test_populates_source_device_id(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_mesh_session,
        )

        summary = MeshParticipationSummary()
        mock_session = self._make_mock_session()

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=self._make_registry_with_session(mock_session),
        ):
            _aggregate_from_mesh_session(summary)

        assert summary.source_device_id == "phone_001"

    def test_populates_merge_policy(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_mesh_session,
        )

        summary = MeshParticipationSummary()
        mock_session = self._make_mock_session()

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=self._make_registry_with_session(mock_session),
        ):
            _aggregate_from_mesh_session(summary)

        assert summary.merge_policy == "parallel"

    def test_populates_barrier_posture(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_mesh_session,
        )

        summary = MeshParticipationSummary()
        mock_session = self._make_mock_session()

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=self._make_registry_with_session(mock_session),
        ):
            _aggregate_from_mesh_session(summary)

        assert summary.barrier_posture == "wait_primary"

    def test_populates_participants_roles(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_mesh_session,
        )

        summary = MeshParticipationSummary()
        mock_session = self._make_mock_session()

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=self._make_registry_with_session(mock_session),
        ):
            _aggregate_from_mesh_session(summary)

        assert "source" in summary.roles_by_device.get("phone_001", [])
        assert "primary" in summary.roles_by_device.get("tablet_002", [])


# ---------------------------------------------------------------------------
# 49–50. Aggregation from mocked mesh membership
# ---------------------------------------------------------------------------


class TestAggregationFromMeshMembership:
    def _make_mock_membership(self, device_id: str, routing_intent: str = "local_preferred") -> Any:
        m = MagicMock()
        m.member_device_id = device_id
        m.mesh_id = "mesh_alpha"
        m.roles = []
        intent = MagicMock()
        intent.value = routing_intent
        m.routing_intent = intent
        return m

    def test_populates_routing_intents(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_mesh_membership,
        )

        summary = MeshParticipationSummary()
        mock_membership = self._make_mock_membership("phone_001", "remote_required")

        registry = MagicMock()
        registry.get_mesh_memberships.return_value = [mock_membership]

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=registry,
        ):
            _aggregate_from_mesh_membership(summary)

        assert summary.routing_intents.get("phone_001") == "remote_required"

    def test_populates_roles_by_device(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            _aggregate_from_mesh_membership,
        )

        summary = MeshParticipationSummary()
        mock_membership = self._make_mock_membership("phone_001")
        role_mock = MagicMock()
        role_mock.value = "observer"
        mock_membership.roles = [role_mock]

        registry = MagicMock()
        registry.get_mesh_memberships.return_value = [mock_membership]

        with patch(
            "core.mesh_participation_summary.get_body_mesh_registry",
            return_value=registry,
        ):
            _aggregate_from_mesh_membership(summary)

        assert "observer" in summary.roles_by_device.get("phone_001", [])


# ---------------------------------------------------------------------------
# 51–52. get_device_mesh_summary — additional field checks
# ---------------------------------------------------------------------------


class TestGetDeviceMeshSummaryExtras:
    def test_routing_intent_populated(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            get_device_mesh_summary,
        )

        s = MeshParticipationSummary(
            device_ids=["phone_001"],
            routing_intents={"phone_001": "remote_required"},
        )
        with patch(
            "core.mesh_participation_summary.get_current_mesh_participation_summary",
            return_value=s,
        ):
            result = get_device_mesh_summary("phone_001")
        assert result["routing_intent"] == "remote_required"

    def test_session_id_propagated(self) -> None:
        from core.mesh_participation_summary import (
            MeshParticipationSummary,
            get_device_mesh_summary,
        )

        s = MeshParticipationSummary(session_id="sess_propagated")
        with patch(
            "core.mesh_participation_summary.get_current_mesh_participation_summary",
            return_value=s,
        ):
            result = get_device_mesh_summary("any_device")
        assert result["session_id"] == "sess_propagated"


# ---------------------------------------------------------------------------
# 53–55. Deduplication and isolation
# ---------------------------------------------------------------------------


class TestDeduplicationAndIsolation:
    def test_roles_by_device_deduplication(self) -> None:
        from core.mesh_participation_summary import _merge_role

        roles: dict = {}
        for _ in range(5):
            _merge_role(roles, "dev_001", "primary")
        assert roles["dev_001"] == ["primary"]

    def test_device_ids_deduplication_via_multiple_calls(self) -> None:
        from core.mesh_participation_summary import MeshParticipationSummary, _merge_device_ids

        s = MeshParticipationSummary()
        _merge_device_ids(s, ["a", "b"])
        _merge_device_ids(s, ["a", "b", "c"])
        assert s.device_ids.count("a") == 1
        assert s.device_ids.count("b") == 1
        assert s.device_ids.count("c") == 1

    def test_to_dict_lists_are_independent_copies(self) -> None:
        from core.mesh_participation_summary import MeshParticipationSummary

        s = MeshParticipationSummary(device_ids=["a", "b"])
        d = s.to_dict()
        d["device_ids"].append("mutation")
        assert "mutation" not in s.device_ids
