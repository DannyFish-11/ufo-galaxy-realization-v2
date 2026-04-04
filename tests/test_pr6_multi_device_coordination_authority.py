"""tests/test_pr6_multi_device_coordination_authority.py
============================================================
Tests for PR-6 (post-533 dual-repo runtime host unification, MAIN repo side):
Align multi-device coordination with canonical OpenClawd runtime authority.

Coverage groups
---------------
A  — Authority and policy sentinel presence and non-empty values.
B  — CoordinationRole enum: all four canonical values plus UNRESOLVED present.
C  — derive_coordination_role: source device + control_only → source_controller.
D  — derive_coordination_role: source device + join_runtime → joined_runtime_participant.
E  — derive_coordination_role: observer formation role → observer_only.
F  — derive_coordination_role: target-only executor path.
G  — derive_coordination_role: unknown/None posture falls back to control_only semantics.
H  — derive_coordination_role: unresolved fallback when no disambiguating signals.
I  — CoordinationRoleRecord: construction, has_control_authority, has_execution_responsibility.
J  — CoordinationRoleRecord.to_dict(): all expected keys present.
K  — build_coordination_role_record: calls derive internally, returns correct role.
L  — build_coordination_role_snapshot: source_controller_device_id extracted.
M  — build_coordination_role_snapshot: has_joined_runtime_participant flag.
N  — build_coordination_role_snapshot: target_only and observer lists populated.
O  — build_coordination_role_snapshot: is_authority_clear when one controller, no unresolved.
P  — build_coordination_role_snapshot: authority NOT clear when unresolved present.
Q  — CoordinationRoleSnapshot.to_dict(): all expected keys and PR6 sentinel present.
R  — get_source_controller_device_id: returns correct device ID.
S  — CoordinationRoleRuntime: record() and snapshot() with ring eviction.
T  — get/reset_coordination_role_runtime: singleton identity and reset.
U  — record_coordination_role: fire-and-forget, never raises.
V  — core.runtime re-exports: all PR-6 symbols accessible from core.runtime.
W  — multi_device_control_integrity: PR6 sentinel present and non-empty.
X  — multi_device_projection_canonicalization: PR6 sentinel present.
Y  — enrich_multi_device_projection: coordination_role_snapshot in output.
Z  — Backwards safety: derive_coordination_role with no arguments returns UNRESOLVED.
AA — Mixed formation: source controller present alongside multiple other roles.
AB — observer_only has no control authority and no execution responsibility.
AC — target_only_executor has no control authority but has execution responsibility.
AD — joined_runtime_participant has control authority and execution responsibility.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    *,
    device_id: Optional[str] = None,
    task_id: str = "task_pr6_001",
    source_runtime_posture: Optional[str] = None,
    formation_role: Optional[str] = None,
    is_source_device: bool = False,
    is_target_device: bool = False,
) -> Any:
    from core.multi_device_coordination_authority import build_coordination_role_record

    return build_coordination_role_record(
        device_id=device_id or str(uuid.uuid4()),
        task_id=task_id,
        source_runtime_posture=source_runtime_posture,
        formation_role=formation_role,
        is_source_device=is_source_device,
        is_target_device=is_target_device,
    )


# ---------------------------------------------------------------------------
# A — Sentinel presence
# ---------------------------------------------------------------------------


class TestSentinelPresence:
    """Group A: sentinel strings are present and non-empty."""

    def test_A01_authority_sentinel(self):
        from core.multi_device_coordination_authority import MULTI_DEVICE_COORDINATION_AUTHORITY
        assert isinstance(MULTI_DEVICE_COORDINATION_AUTHORITY, str)
        assert len(MULTI_DEVICE_COORDINATION_AUTHORITY) > 20

    def test_A02_pr6_integrated_sentinel(self):
        from core.multi_device_coordination_authority import MULTI_DEVICE_COORDINATION_AUTHORITY_PR6_SENTINEL
        assert isinstance(MULTI_DEVICE_COORDINATION_AUTHORITY_PR6_SENTINEL, str)
        assert "PR-6" in MULTI_DEVICE_COORDINATION_AUTHORITY_PR6_SENTINEL

    def test_A03_source_controller_owns_runtime_authority_policy(self):
        from core.multi_device_coordination_authority import SOURCE_CONTROLLER_OWNS_RUNTIME_AUTHORITY_POLICY
        assert isinstance(SOURCE_CONTROLLER_OWNS_RUNTIME_AUTHORITY_POLICY, str)
        assert "source_controller" in SOURCE_CONTROLLER_OWNS_RUNTIME_AUTHORITY_POLICY.lower()

    def test_A04_target_only_executor_no_control_policy(self):
        from core.multi_device_coordination_authority import TARGET_ONLY_EXECUTOR_HAS_NO_CONTROL_AUTHORITY_POLICY
        assert isinstance(TARGET_ONLY_EXECUTOR_HAS_NO_CONTROL_AUTHORITY_POLICY, str)
        assert "target_only_executor" in TARGET_ONLY_EXECUTOR_HAS_NO_CONTROL_AUTHORITY_POLICY.lower()

    def test_A05_observer_only_no_execution_policy(self):
        from core.multi_device_coordination_authority import OBSERVER_ONLY_HAS_NO_EXECUTION_AUTHORITY_POLICY
        assert isinstance(OBSERVER_ONLY_HAS_NO_EXECUTION_AUTHORITY_POLICY, str)
        assert "observer_only" in OBSERVER_ONLY_HAS_NO_EXECUTION_AUTHORITY_POLICY.lower()

    def test_A06_coordination_role_derivation_is_posture_driven_policy(self):
        from core.multi_device_coordination_authority import COORDINATION_ROLE_DERIVATION_IS_POSTURE_DRIVEN_POLICY
        assert isinstance(COORDINATION_ROLE_DERIVATION_IS_POSTURE_DRIVEN_POLICY, str)
        assert "posture" in COORDINATION_ROLE_DERIVATION_IS_POSTURE_DRIVEN_POLICY.lower()


# ---------------------------------------------------------------------------
# B — CoordinationRole enum
# ---------------------------------------------------------------------------


class TestCoordinationRoleEnum:
    """Group B: all expected enum values exist and are str-compatible."""

    def test_B01_source_controller_value(self):
        from core.multi_device_coordination_authority import CoordinationRole
        assert CoordinationRole.SOURCE_CONTROLLER.value == "source_controller"

    def test_B02_joined_runtime_participant_value(self):
        from core.multi_device_coordination_authority import CoordinationRole
        assert CoordinationRole.JOINED_RUNTIME_PARTICIPANT.value == "joined_runtime_participant"

    def test_B03_target_only_executor_value(self):
        from core.multi_device_coordination_authority import CoordinationRole
        assert CoordinationRole.TARGET_ONLY_EXECUTOR.value == "target_only_executor"

    def test_B04_observer_only_value(self):
        from core.multi_device_coordination_authority import CoordinationRole
        assert CoordinationRole.OBSERVER_ONLY.value == "observer_only"

    def test_B05_unresolved_value(self):
        from core.multi_device_coordination_authority import CoordinationRole
        assert CoordinationRole.UNRESOLVED.value == "unresolved"

    def test_B06_all_roles_are_str_subclass(self):
        from core.multi_device_coordination_authority import CoordinationRole
        for role in CoordinationRole:
            assert isinstance(role, str)
            assert isinstance(role.value, str)


# ---------------------------------------------------------------------------
# C — derive_coordination_role: source_controller path
# ---------------------------------------------------------------------------


class TestDeriveRoleSourceController:
    """Group C: source device with control_only posture → source_controller."""

    def test_C01_source_device_control_only(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(
            source_runtime_posture="control_only",
            is_source_device=True,
        )
        assert role == CoordinationRole.SOURCE_CONTROLLER

    def test_C02_source_formation_role_control_only(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(
            source_runtime_posture="control_only",
            formation_role="source_device",
        )
        assert role == CoordinationRole.SOURCE_CONTROLLER

    def test_C03_primary_execution_formation_role(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(
            source_runtime_posture="control_only",
            formation_role="primary_execution_device",
        )
        assert role == CoordinationRole.SOURCE_CONTROLLER

    def test_C04_source_device_no_posture_defaults_to_source_controller(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        # No posture → control_only semantics → source_controller for source device
        role = derive_coordination_role(is_source_device=True)
        assert role == CoordinationRole.SOURCE_CONTROLLER


# ---------------------------------------------------------------------------
# D — derive_coordination_role: joined_runtime_participant path
# ---------------------------------------------------------------------------


class TestDeriveRoleJoinedRuntimeParticipant:
    """Group D: source device + join_runtime → joined_runtime_participant."""

    def test_D01_source_device_join_runtime(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(
            source_runtime_posture="join_runtime",
            is_source_device=True,
        )
        assert role == CoordinationRole.JOINED_RUNTIME_PARTICIPANT

    def test_D02_source_formation_role_join_runtime(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(
            source_runtime_posture="join_runtime",
            formation_role="source_device",
        )
        assert role == CoordinationRole.JOINED_RUNTIME_PARTICIPANT

    def test_D03_primary_execution_join_runtime(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(
            source_runtime_posture="join_runtime",
            formation_role="primary_execution_device",
        )
        assert role == CoordinationRole.JOINED_RUNTIME_PARTICIPANT


# ---------------------------------------------------------------------------
# E — derive_coordination_role: observer_only path
# ---------------------------------------------------------------------------


class TestDeriveRoleObserverOnly:
    """Group E: observer formation role → observer_only regardless of posture."""

    def test_E01_observer_formation_role(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(formation_role="observer_device")
        assert role == CoordinationRole.OBSERVER_ONLY

    def test_E02_observer_with_join_runtime_posture(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        # Observer role is definitive: even join_runtime posture doesn't override it.
        role = derive_coordination_role(
            source_runtime_posture="join_runtime",
            formation_role="observer_device",
        )
        assert role == CoordinationRole.OBSERVER_ONLY

    def test_E03_observer_with_is_target_true(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(
            formation_role="observer_device",
            is_target_device=True,
        )
        assert role == CoordinationRole.OBSERVER_ONLY


# ---------------------------------------------------------------------------
# F — derive_coordination_role: target_only_executor path
# ---------------------------------------------------------------------------


class TestDeriveRoleTargetOnlyExecutor:
    """Group F: non-source target device → target_only_executor."""

    def test_F01_target_device_no_source_flag(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(is_target_device=True)
        assert role == CoordinationRole.TARGET_ONLY_EXECUTOR

    def test_F02_target_device_control_only_posture(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(
            source_runtime_posture="control_only",
            is_target_device=True,
        )
        assert role == CoordinationRole.TARGET_ONLY_EXECUTOR

    def test_F03_target_device_join_runtime_posture(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(
            source_runtime_posture="join_runtime",
            is_target_device=True,
        )
        assert role == CoordinationRole.TARGET_ONLY_EXECUTOR


# ---------------------------------------------------------------------------
# G — Unknown/None posture falls back to control_only semantics
# ---------------------------------------------------------------------------


class TestPostureFallback:
    """Group G: unknown or None posture falls back to control_only semantics."""

    def test_G01_none_posture_source_device(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(source_runtime_posture=None, is_source_device=True)
        assert role == CoordinationRole.SOURCE_CONTROLLER

    def test_G02_empty_string_posture(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(source_runtime_posture="", is_source_device=True)
        assert role == CoordinationRole.SOURCE_CONTROLLER

    def test_G03_unknown_posture_string(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(
            source_runtime_posture="unknown_posture_value",
            is_source_device=True,
        )
        assert role == CoordinationRole.SOURCE_CONTROLLER


# ---------------------------------------------------------------------------
# H — Unresolved fallback
# ---------------------------------------------------------------------------


class TestDeriveRoleUnresolved:
    """Group H: no disambiguating signals → UNRESOLVED."""

    def test_H01_no_signals_returns_unresolved(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role()
        assert role == CoordinationRole.UNRESOLVED

    def test_H02_posture_only_no_role_or_flags(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(source_runtime_posture="control_only")
        assert role == CoordinationRole.UNRESOLVED

    def test_H03_unknown_formation_role_not_source_not_target(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        role = derive_coordination_role(formation_role="relay_device")
        assert role == CoordinationRole.UNRESOLVED


# ---------------------------------------------------------------------------
# I — CoordinationRoleRecord
# ---------------------------------------------------------------------------


class TestCoordinationRoleRecord:
    """Group I: record construction and derived flags."""

    def test_I01_source_controller_has_control_authority(self):
        rec = _make_record(is_source_device=True, source_runtime_posture="control_only")
        from core.multi_device_coordination_authority import CoordinationRole
        assert rec.coordination_role == CoordinationRole.SOURCE_CONTROLLER
        assert rec.has_control_authority is True

    def test_I02_source_controller_has_execution_responsibility(self):
        rec = _make_record(is_source_device=True)
        assert rec.has_execution_responsibility is True

    def test_I03_observer_only_no_control_authority(self):
        rec = _make_record(formation_role="observer_device")
        from core.multi_device_coordination_authority import CoordinationRole
        assert rec.coordination_role == CoordinationRole.OBSERVER_ONLY
        assert rec.has_control_authority is False

    def test_I04_observer_only_no_execution_responsibility(self):
        rec = _make_record(formation_role="observer_device")
        assert rec.has_execution_responsibility is False

    def test_I05_target_only_no_control_authority(self):
        rec = _make_record(is_target_device=True)
        assert rec.has_control_authority is False

    def test_I06_target_only_has_execution_responsibility(self):
        rec = _make_record(is_target_device=True)
        assert rec.has_execution_responsibility is True

    def test_I07_joined_participant_has_control_authority(self):
        rec = _make_record(is_source_device=True, source_runtime_posture="join_runtime")
        from core.multi_device_coordination_authority import CoordinationRole
        assert rec.coordination_role == CoordinationRole.JOINED_RUNTIME_PARTICIPANT
        assert rec.has_control_authority is True

    def test_I08_unresolved_no_execution_responsibility(self):
        rec = _make_record()  # no signals
        from core.multi_device_coordination_authority import CoordinationRole
        assert rec.coordination_role == CoordinationRole.UNRESOLVED
        assert rec.has_execution_responsibility is False


# ---------------------------------------------------------------------------
# J — CoordinationRoleRecord.to_dict
# ---------------------------------------------------------------------------


class TestCoordinationRoleRecordToDict:
    """Group J: to_dict() produces all expected keys."""

    def test_J01_to_dict_has_required_keys(self):
        rec = _make_record(is_source_device=True)
        d = rec.to_dict()
        required = [
            "record_id",
            "task_id",
            "device_id",
            "coordination_role",
            "source_runtime_posture",
            "has_control_authority",
            "has_execution_responsibility",
            "derivation_reason",
            "timestamp",
            "authority",
        ]
        for key in required:
            assert key in d, f"Missing key: {key}"

    def test_J02_coordination_role_is_string_value(self):
        rec = _make_record(is_source_device=True)
        d = rec.to_dict()
        assert d["coordination_role"] == "source_controller"

    def test_J03_authority_field_contains_pr6_text(self):
        rec = _make_record(is_source_device=True)
        d = rec.to_dict()
        assert "PR6" in d["authority"] or "AUTHORITY" in d["authority"]


# ---------------------------------------------------------------------------
# K — build_coordination_role_record
# ---------------------------------------------------------------------------


class TestBuildCoordinationRoleRecord:
    """Group K: builder derives role internally."""

    def test_K01_source_controller_built(self):
        from core.multi_device_coordination_authority import CoordinationRole, build_coordination_role_record
        rec = build_coordination_role_record(
            device_id="dev_source",
            task_id="task_k01",
            source_runtime_posture="control_only",
            is_source_device=True,
        )
        assert rec.coordination_role == CoordinationRole.SOURCE_CONTROLLER
        assert rec.device_id == "dev_source"
        assert rec.task_id == "task_k01"

    def test_K02_observer_only_built(self):
        from core.multi_device_coordination_authority import CoordinationRole, build_coordination_role_record
        rec = build_coordination_role_record(
            device_id="dev_observer",
            formation_role="observer_device",
        )
        assert rec.coordination_role == CoordinationRole.OBSERVER_ONLY

    def test_K03_posture_normalised_in_record(self):
        from core.multi_device_coordination_authority import build_coordination_role_record
        rec = build_coordination_role_record(
            device_id="dev_x",
            source_runtime_posture=None,  # should normalise to control_only
        )
        assert rec.source_runtime_posture == "control_only"


# ---------------------------------------------------------------------------
# L — build_coordination_role_snapshot: source controller
# ---------------------------------------------------------------------------


class TestBuildSnapshotSourceController:
    """Group L: source_controller_device_id extracted correctly."""

    def test_L01_source_controller_identified(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [
            _make_record(device_id="dev_src", is_source_device=True),
            _make_record(device_id="dev_tgt", is_target_device=True),
        ]
        snap = build_coordination_role_snapshot(records, task_id="t_l01")
        assert snap.source_controller_device_id == "dev_src"

    def test_L02_no_source_controller_when_no_source_record(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [
            _make_record(device_id="dev_tgt", is_target_device=True),
        ]
        snap = build_coordination_role_snapshot(records)
        assert snap.source_controller_device_id is None

    def test_L03_task_id_carried_into_snapshot(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [_make_record(device_id="dev_a", is_source_device=True, task_id="task_l03")]
        snap = build_coordination_role_snapshot(records)
        assert snap.task_id == "task_l03"


# ---------------------------------------------------------------------------
# M — build_coordination_role_snapshot: has_joined_runtime_participant
# ---------------------------------------------------------------------------


class TestBuildSnapshotJoinedParticipant:
    """Group M: has_joined_runtime_participant flag."""

    def test_M01_true_when_joined_participant_present(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [
            _make_record(device_id="dev_joined", is_source_device=True, source_runtime_posture="join_runtime"),
        ]
        snap = build_coordination_role_snapshot(records)
        assert snap.has_joined_runtime_participant is True

    def test_M02_false_when_no_joined_participant(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [
            _make_record(device_id="dev_src", is_source_device=True, source_runtime_posture="control_only"),
        ]
        snap = build_coordination_role_snapshot(records)
        assert snap.has_joined_runtime_participant is False


# ---------------------------------------------------------------------------
# N — build_coordination_role_snapshot: target_only and observer lists
# ---------------------------------------------------------------------------


class TestBuildSnapshotTargetAndObserver:
    """Group N: target_only_executor and observer_only lists populated."""

    def test_N01_target_only_executor_list(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [
            _make_record(device_id="dev_tgt1", is_target_device=True),
            _make_record(device_id="dev_tgt2", is_target_device=True),
        ]
        snap = build_coordination_role_snapshot(records)
        assert "dev_tgt1" in snap.target_only_executor_device_ids
        assert "dev_tgt2" in snap.target_only_executor_device_ids

    def test_N02_observer_only_list(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [
            _make_record(device_id="dev_obs", formation_role="observer_device"),
        ]
        snap = build_coordination_role_snapshot(records)
        assert "dev_obs" in snap.observer_only_device_ids

    def test_N03_mixed_roles(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [
            _make_record(device_id="src", is_source_device=True),
            _make_record(device_id="tgt", is_target_device=True),
            _make_record(device_id="obs", formation_role="observer_device"),
        ]
        snap = build_coordination_role_snapshot(records)
        assert snap.source_controller_device_id == "src"
        assert "tgt" in snap.target_only_executor_device_ids
        assert "obs" in snap.observer_only_device_ids


# ---------------------------------------------------------------------------
# O — is_authority_clear when one controller, no unresolved
# ---------------------------------------------------------------------------


class TestAuthorityClarity:
    """Group O/P: is_authority_clear flag."""

    def test_O01_authority_clear_one_source_no_unresolved(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [
            _make_record(device_id="src", is_source_device=True),
            _make_record(device_id="tgt", is_target_device=True),
        ]
        snap = build_coordination_role_snapshot(records)
        assert snap.is_authority_clear is True

    def test_P01_authority_not_clear_when_unresolved_present(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [
            _make_record(device_id="src", is_source_device=True),
            _make_record(device_id="unresolved_dev"),  # no signals → unresolved
        ]
        snap = build_coordination_role_snapshot(records)
        assert snap.is_authority_clear is False
        assert "unresolved_dev" in snap.unresolved_device_ids

    def test_P02_authority_not_clear_when_no_source_controller(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [
            _make_record(device_id="tgt", is_target_device=True),
        ]
        snap = build_coordination_role_snapshot(records)
        assert snap.is_authority_clear is False


# ---------------------------------------------------------------------------
# Q — CoordinationRoleSnapshot.to_dict
# ---------------------------------------------------------------------------


class TestCoordinationRoleSnapshotToDict:
    """Group Q: to_dict() has all expected keys including PR6 sentinel."""

    def test_Q01_to_dict_has_required_keys(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [_make_record(device_id="src", is_source_device=True)]
        snap = build_coordination_role_snapshot(records)
        d = snap.to_dict()
        required = [
            "snapshot_id",
            "task_id",
            "source_controller_device_id",
            "has_joined_runtime_participant",
            "target_only_executor_device_ids",
            "observer_only_device_ids",
            "unresolved_device_ids",
            "is_authority_clear",
            "record_count",
            "records",
            "timestamp",
            "authority",
            "pr6_sentinel",
        ]
        for key in required:
            assert key in d, f"Missing key: {key}"

    def test_Q02_pr6_sentinel_non_empty(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        snap = build_coordination_role_snapshot([])
        d = snap.to_dict()
        assert "PR-6" in d["pr6_sentinel"] or "PR6" in d["pr6_sentinel"]

    def test_Q03_records_serialised_as_list_of_dicts(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [_make_record(device_id="src", is_source_device=True)]
        snap = build_coordination_role_snapshot(records)
        d = snap.to_dict()
        assert isinstance(d["records"], list)
        assert isinstance(d["records"][0], dict)


# ---------------------------------------------------------------------------
# R — get_source_controller_device_id
# ---------------------------------------------------------------------------


class TestGetSourceControllerDeviceId:
    """Group R: helper returns correct device ID."""

    def test_R01_returns_source_controller_id(self):
        from core.multi_device_coordination_authority import (
            build_coordination_role_snapshot,
            get_source_controller_device_id,
        )
        records = [
            _make_record(device_id="dev_ctrl", is_source_device=True),
        ]
        snap = build_coordination_role_snapshot(records)
        assert get_source_controller_device_id(snap) == "dev_ctrl"

    def test_R02_returns_none_when_no_controller(self):
        from core.multi_device_coordination_authority import (
            build_coordination_role_snapshot,
            get_source_controller_device_id,
        )
        records = [_make_record(device_id="tgt", is_target_device=True)]
        snap = build_coordination_role_snapshot(records)
        assert get_source_controller_device_id(snap) is None


# ---------------------------------------------------------------------------
# S — CoordinationRoleRuntime
# ---------------------------------------------------------------------------


class TestCoordinationRoleRuntime:
    """Group S: ring-buffer record/snapshot with eviction."""

    def test_S01_record_and_retrieve(self):
        from core.multi_device_coordination_authority import CoordinationRoleRuntime
        rt = CoordinationRoleRuntime(max_size=10)
        rec = _make_record(device_id="dev_s01", is_source_device=True)
        rt.record(rec)
        snaps = rt.snapshot()
        assert len(snaps) == 1
        assert snaps[0].device_id == "dev_s01"

    def test_S02_ring_eviction(self):
        from core.multi_device_coordination_authority import CoordinationRoleRuntime
        rt = CoordinationRoleRuntime(max_size=3)
        for i in range(5):
            rt.record(_make_record(device_id=f"dev_{i}"))
        assert len(rt) == 3
        snaps = rt.snapshot()
        # Most recent 3: dev_2, dev_3, dev_4
        device_ids = [r.device_id for r in snaps]
        assert "dev_4" in device_ids
        assert "dev_0" not in device_ids

    def test_S03_snapshot_max_recent_respected(self):
        from core.multi_device_coordination_authority import CoordinationRoleRuntime
        rt = CoordinationRoleRuntime(max_size=50)
        for i in range(30):
            rt.record(_make_record())
        snaps = rt.snapshot(max_recent=5)
        assert len(snaps) == 5

    def test_S04_empty_runtime_snapshot_is_empty(self):
        from core.multi_device_coordination_authority import CoordinationRoleRuntime
        rt = CoordinationRoleRuntime()
        assert rt.snapshot() == []
        assert len(rt) == 0


# ---------------------------------------------------------------------------
# T — get/reset_coordination_role_runtime singleton
# ---------------------------------------------------------------------------


class TestSingletonGetReset:
    """Group T: singleton identity and reset."""

    def test_T01_get_returns_same_instance(self):
        from core.multi_device_coordination_authority import (
            get_coordination_role_runtime,
            reset_coordination_role_runtime,
        )
        reset_coordination_role_runtime()
        rt1 = get_coordination_role_runtime()
        rt2 = get_coordination_role_runtime()
        assert rt1 is rt2

    def test_T02_reset_gives_new_instance(self):
        from core.multi_device_coordination_authority import (
            get_coordination_role_runtime,
            reset_coordination_role_runtime,
        )
        rt1 = get_coordination_role_runtime()
        reset_coordination_role_runtime()
        rt2 = get_coordination_role_runtime()
        assert rt1 is not rt2

    def test_T03_records_cleared_after_reset(self):
        from core.multi_device_coordination_authority import (
            get_coordination_role_runtime,
            reset_coordination_role_runtime,
            record_coordination_role,
        )
        reset_coordination_role_runtime()
        record_coordination_role(_make_record(device_id="before_reset"))
        reset_coordination_role_runtime()
        rt = get_coordination_role_runtime()
        assert len(rt) == 0


# ---------------------------------------------------------------------------
# U — record_coordination_role: fire-and-forget, never raises
# ---------------------------------------------------------------------------


class TestRecordCoordinationRole:
    """Group U: fire-and-forget helper."""

    def test_U01_stores_record_in_runtime(self):
        from core.multi_device_coordination_authority import (
            get_coordination_role_runtime,
            record_coordination_role,
            reset_coordination_role_runtime,
        )
        reset_coordination_role_runtime()
        rec = _make_record(device_id="dev_u01", is_source_device=True)
        record_coordination_role(rec)
        rt = get_coordination_role_runtime()
        assert len(rt) >= 1

    def test_U02_does_not_raise_on_error(self):
        from core.multi_device_coordination_authority import (
            record_coordination_role,
            reset_coordination_role_runtime,
        )
        reset_coordination_role_runtime()
        # record_coordination_role is fire-and-forget: passing a non-record
        # value (None) should be silently ignored, never raising.
        record_coordination_role(None)  # type: ignore[arg-type]
        # If we reach here without an exception, the test passes.


# ---------------------------------------------------------------------------
# V — core.runtime re-exports
# ---------------------------------------------------------------------------


class TestCoreRuntimeReExports:
    """Group V: all PR-6 symbols accessible from core.runtime.

    Note: core.runtime imports pydantic via contracts.cross_runtime_result_merge.
    Tests in this group are skipped in environments where pydantic is unavailable.
    """

    @staticmethod
    def _import_runtime():
        pytest.importorskip("pydantic", reason="pydantic required for core.runtime")
        import core.runtime as runtime
        return runtime

    def test_V01_coordination_role_enum(self):
        rt = self._import_runtime()
        assert hasattr(rt.CoordinationRole, "SOURCE_CONTROLLER")

    def test_V02_coordination_role_record(self):
        rt = self._import_runtime()
        assert rt.CoordinationRoleRecord is not None

    def test_V03_coordination_role_snapshot(self):
        rt = self._import_runtime()
        assert rt.CoordinationRoleSnapshot is not None

    def test_V04_derive_coordination_role(self):
        rt = self._import_runtime()
        assert rt.derive_coordination_role(is_source_device=True) == rt.CoordinationRole.SOURCE_CONTROLLER

    def test_V05_build_coordination_role_record(self):
        rt = self._import_runtime()
        rec = rt.build_coordination_role_record(device_id="dev", is_source_device=True)
        assert rec.coordination_role == rt.CoordinationRole.SOURCE_CONTROLLER

    def test_V06_build_coordination_role_snapshot(self):
        rt = self._import_runtime()
        rec = rt.build_coordination_role_record(device_id="d", is_source_device=True)
        snap = rt.build_coordination_role_snapshot([rec])
        assert snap.source_controller_device_id == "d"

    def test_V07_authority_sentinel(self):
        rt = self._import_runtime()
        assert isinstance(rt.MULTI_DEVICE_COORDINATION_AUTHORITY, str)

    def test_V08_pr6_sentinel(self):
        rt = self._import_runtime()
        assert "PR-6" in rt.MULTI_DEVICE_COORDINATION_AUTHORITY_PR6_SENTINEL

    def test_V09_get_source_controller_device_id(self):
        rt = self._import_runtime()
        rec = rt.build_coordination_role_record(device_id="ctrl", is_source_device=True)
        snap = rt.build_coordination_role_snapshot([rec])
        assert rt.get_source_controller_device_id(snap) == "ctrl"


# ---------------------------------------------------------------------------
# W — multi_device_control_integrity PR6 sentinel
# ---------------------------------------------------------------------------


class TestIntegrityPR6Sentinel:
    """Group W: PR6 alignment sentinel in multi_device_control_integrity."""

    def test_W01_sentinel_present(self):
        from core.multi_device_control_integrity import MULTI_DEVICE_COORDINATION_AUTHORITY_ALIGNED_PR6
        assert isinstance(MULTI_DEVICE_COORDINATION_AUTHORITY_ALIGNED_PR6, str)
        assert len(MULTI_DEVICE_COORDINATION_AUTHORITY_ALIGNED_PR6) > 30

    def test_W02_sentinel_references_pr6(self):
        from core.multi_device_control_integrity import MULTI_DEVICE_COORDINATION_AUTHORITY_ALIGNED_PR6
        assert "PR6" in MULTI_DEVICE_COORDINATION_AUTHORITY_ALIGNED_PR6

    def test_W03_sentinel_mentions_coordination_roles(self):
        from core.multi_device_control_integrity import MULTI_DEVICE_COORDINATION_AUTHORITY_ALIGNED_PR6
        text = MULTI_DEVICE_COORDINATION_AUTHORITY_ALIGNED_PR6.lower()
        assert "source_controller" in text or "coordination" in text


# ---------------------------------------------------------------------------
# X — multi_device_projection_canonicalization PR6 sentinel
# ---------------------------------------------------------------------------


class TestProjectionCanonicalizationPR6Sentinel:
    """Group X: PR6 sentinel in projection canonicalization."""

    def test_X01_sentinel_present(self):
        from core.multi_device_projection_canonicalization import MULTI_DEVICE_PROJECTION_COORDINATION_ROLE_INTEGRATED
        assert isinstance(MULTI_DEVICE_PROJECTION_COORDINATION_ROLE_INTEGRATED, str)

    def test_X02_sentinel_mentions_pr6(self):
        from core.multi_device_projection_canonicalization import MULTI_DEVICE_PROJECTION_COORDINATION_ROLE_INTEGRATED
        assert "PR-6" in MULTI_DEVICE_PROJECTION_COORDINATION_ROLE_INTEGRATED or "PR6" in MULTI_DEVICE_PROJECTION_COORDINATION_ROLE_INTEGRATED

    def test_X03_coordination_role_in_all_exports(self):
        import core.multi_device_projection_canonicalization as mod
        assert "MULTI_DEVICE_PROJECTION_COORDINATION_ROLE_INTEGRATED" in mod.__all__


# ---------------------------------------------------------------------------
# Y — enrich_multi_device_projection: coordination_role_snapshot in output
# ---------------------------------------------------------------------------


class TestEnrichProjectionCoordinationRole:
    """Group Y: coordination role data surfaces in projection enrichment."""

    def test_Y01_coordination_role_available(self):
        from core.multi_device_projection_canonicalization import enrich_multi_device_projection
        enrichment = enrich_multi_device_projection()
        assert enrichment.coordination_role_available is True

    def test_Y02_coordination_role_snapshot_is_dict(self):
        from core.multi_device_projection_canonicalization import enrich_multi_device_projection
        enrichment = enrich_multi_device_projection()
        assert isinstance(enrichment.coordination_role_snapshot, dict)

    def test_Y03_to_dict_includes_coordination_fields(self):
        from core.multi_device_projection_canonicalization import enrich_multi_device_projection
        enrichment = enrich_multi_device_projection()
        d = enrichment.to_dict()
        assert "coordination_role_snapshot" in d
        assert "coordination_role_available" in d

    def test_Y04_coordination_snapshot_has_pr6_sentinel_key(self):
        from core.multi_device_projection_canonicalization import enrich_multi_device_projection
        enrichment = enrich_multi_device_projection()
        snap = enrichment.coordination_role_snapshot
        assert snap is not None
        assert "pr6_sentinel" in snap


# ---------------------------------------------------------------------------
# Z — Backwards safety: derive with no arguments
# ---------------------------------------------------------------------------


class TestBackwardsSafety:
    """Group Z: derive_coordination_role with no arguments returns UNRESOLVED."""

    def test_Z01_no_args_returns_unresolved(self):
        from core.multi_device_coordination_authority import CoordinationRole, derive_coordination_role
        assert derive_coordination_role() == CoordinationRole.UNRESOLVED

    def test_Z02_build_snapshot_empty_list_ok(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        snap = build_coordination_role_snapshot([])
        assert snap.source_controller_device_id is None
        assert snap.is_authority_clear is False

    def test_Z03_record_coordination_role_is_additive(self):
        """record_coordination_role does not affect existing runtime records."""
        from core.multi_device_coordination_authority import (
            get_coordination_role_runtime,
            record_coordination_role,
            reset_coordination_role_runtime,
        )
        reset_coordination_role_runtime()
        rec1 = _make_record(device_id="existing_dev")
        record_coordination_role(rec1)
        before_count = len(get_coordination_role_runtime())

        rec2 = _make_record(device_id="new_dev")
        record_coordination_role(rec2)
        after_count = len(get_coordination_role_runtime())

        assert after_count == before_count + 1


# ---------------------------------------------------------------------------
# AA — Mixed formation with multiple roles
# ---------------------------------------------------------------------------


class TestMixedFormation:
    """Group AA: realistic mixed formation with all four role types."""

    def test_AA01_full_formation_authority_clear(self):
        from core.multi_device_coordination_authority import (
            build_coordination_role_snapshot,
            CoordinationRole,
        )
        records = [
            _make_record(device_id="ctrl_dev", is_source_device=True, source_runtime_posture="control_only"),
            _make_record(device_id="joined_dev", is_source_device=True, source_runtime_posture="join_runtime"),
            _make_record(device_id="exec_dev", is_target_device=True),
            _make_record(device_id="obs_dev", formation_role="observer_device"),
        ]
        snap = build_coordination_role_snapshot(records, task_id="task_aa01")
        assert snap.source_controller_device_id == "ctrl_dev"
        assert snap.has_joined_runtime_participant is True
        assert "exec_dev" in snap.target_only_executor_device_ids
        assert "obs_dev" in snap.observer_only_device_ids
        assert snap.is_authority_clear is True

    def test_AA02_role_counts_match(self):
        from core.multi_device_coordination_authority import build_coordination_role_snapshot
        records = [
            _make_record(device_id="c", is_source_device=True),
            _make_record(device_id="t1", is_target_device=True),
            _make_record(device_id="t2", is_target_device=True),
            _make_record(device_id="o", formation_role="observer_device"),
        ]
        snap = build_coordination_role_snapshot(records)
        assert len(snap.target_only_executor_device_ids) == 2
        assert len(snap.observer_only_device_ids) == 1


# ---------------------------------------------------------------------------
# AB — observer_only: no authority, no execution responsibility
# ---------------------------------------------------------------------------


class TestObserverOnlyAuthority:
    """Group AB: observer_only has no authority and no execution responsibility."""

    def test_AB01_no_control_authority(self):
        rec = _make_record(formation_role="observer_device")
        assert rec.has_control_authority is False

    def test_AB02_no_execution_responsibility(self):
        rec = _make_record(formation_role="observer_device")
        assert rec.has_execution_responsibility is False

    def test_AB03_role_value(self):
        from core.multi_device_coordination_authority import CoordinationRole
        rec = _make_record(formation_role="observer_device")
        assert rec.coordination_role == CoordinationRole.OBSERVER_ONLY


# ---------------------------------------------------------------------------
# AC — target_only_executor: no control authority, has execution responsibility
# ---------------------------------------------------------------------------


class TestTargetOnlyExecutorAuthority:
    """Group AC: target_only_executor lacks control authority but executes."""

    def test_AC01_no_control_authority(self):
        rec = _make_record(is_target_device=True)
        assert rec.has_control_authority is False

    def test_AC02_has_execution_responsibility(self):
        rec = _make_record(is_target_device=True)
        assert rec.has_execution_responsibility is True

    def test_AC03_role_value(self):
        from core.multi_device_coordination_authority import CoordinationRole
        rec = _make_record(is_target_device=True)
        assert rec.coordination_role == CoordinationRole.TARGET_ONLY_EXECUTOR


# ---------------------------------------------------------------------------
# AD — joined_runtime_participant: control authority and execution responsibility
# ---------------------------------------------------------------------------


class TestJoinedRuntimeParticipantAuthority:
    """Group AD: joined_runtime_participant has both authority and execution."""

    def test_AD01_has_control_authority(self):
        rec = _make_record(is_source_device=True, source_runtime_posture="join_runtime")
        assert rec.has_control_authority is True

    def test_AD02_has_execution_responsibility(self):
        rec = _make_record(is_source_device=True, source_runtime_posture="join_runtime")
        assert rec.has_execution_responsibility is True

    def test_AD03_role_value(self):
        from core.multi_device_coordination_authority import CoordinationRole
        rec = _make_record(is_source_device=True, source_runtime_posture="join_runtime")
        assert rec.coordination_role == CoordinationRole.JOINED_RUNTIME_PARTICIPANT
