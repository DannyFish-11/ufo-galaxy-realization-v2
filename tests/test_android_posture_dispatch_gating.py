"""tests/test_android_posture_dispatch_gating.py
=================================================
Tests for Android source runtime posture integration into canonical
readiness / participation / dispatch gating (PR-F — posture gating).

Coverage
--------
A.  update_session_posture() — happy path: sets posture on active entry.
B.  update_session_posture() — unknown posture normalised to control_only.
C.  update_session_posture() — returns None when no active session exists.
D.  update_session_posture() — join_runtime posture preserved as-is.
E.  update_session_posture() — metadata is merged, not replaced.
F.  _score_candidate() — control_only posture produces rejection.
G.  _score_candidate() — join_runtime posture passes gate.
H.  _score_candidate() — empty posture defaults to join_runtime (eligible).
I.  _select_target_from_candidates() — control_only device excluded.
J.  _select_target_from_candidates() — join_runtime device selected.
K.  _select_target_from_candidates() — mix: only join_runtime device wins.
L.  handle_agent_status() — posture field updates session registry.
M.  handle_agent_status() — missing posture field is silently ignored.
N.  handle_agent_status() — unrecognised posture value normalised to control_only.
O.  Sentinel constants importable from source_dispatch_orchestrator.
P.  Policy sentinel importable from attached_runtime_session_registry.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.attached_runtime_session_registry import (
    ANDROID_POSTURE_GATING_UPDATE_AUTHORITY,
    get_session_registry,
    list_active_sessions,
    register_session,
    reset_session_registry,
    update_session_posture,
)
from core.runtime.source_dispatch_orchestrator import (
    ANDROID_CONTROL_ONLY_POSTURE_IS_NOT_DISPATCH_TARGET_POLICY,
    ANDROID_POSTURE_GATING_INTEGRATED_SENTINEL,
    POSTURE_GATE_PRESERVES_BACKWARD_COMPAT_POLICY,
    POSTURE_UPDATE_AFFECTS_NEXT_SELECTION_CYCLE_POLICY,
    _score_candidate,
    _select_target_from_candidates,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_readiness(registered: bool = True, routable: bool = True) -> Any:
    r = MagicMock()
    r.registered = registered
    r.routable = routable
    return r


def _make_participation(
    orchestration_eligible: bool = True,
    participant_tier: str = "execution_endpoint",
) -> Any:
    p = MagicMock()
    p.orchestration_eligible = orchestration_eligible
    p.participant_tier = participant_tier
    return p


# ---------------------------------------------------------------------------
# A. update_session_posture — happy path
# ---------------------------------------------------------------------------


class TestUpdateSessionPostureHappyPath:
    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_A1_sets_posture_on_active_entry(self):
        register_session("dev_a", posture="join_runtime")
        result = update_session_posture("dev_a", "control_only")
        assert result is not None
        assert result.posture == "control_only"

    def test_A2_entry_remains_active(self):
        register_session("dev_b", posture="join_runtime")
        result = update_session_posture("dev_b", "control_only")
        assert result is not None
        assert result.is_active()

    def test_A3_runtime_session_id_preserved(self):
        entry = register_session("dev_c", posture="join_runtime")
        original_rsid = entry.runtime_session_id
        result = update_session_posture("dev_c", "control_only")
        assert result is not None
        assert result.runtime_session_id == original_rsid

    def test_A4_device_id_preserved(self):
        register_session("dev_d", posture="join_runtime")
        result = update_session_posture("dev_d", "control_only")
        assert result is not None
        assert result.device_id == "dev_d"


# ---------------------------------------------------------------------------
# B. update_session_posture — unknown posture normalised to control_only
# ---------------------------------------------------------------------------


class TestUpdateSessionPostureUnknownNormalised:
    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_B1_unknown_string_normalised(self):
        register_session("dev_e", posture="join_runtime")
        result = update_session_posture("dev_e", "observe_only")
        assert result is not None
        assert result.posture == "control_only"

    def test_B2_empty_string_normalised(self):
        register_session("dev_f", posture="join_runtime")
        result = update_session_posture("dev_f", "")
        assert result is not None
        assert result.posture == "control_only"

    def test_B3_none_like_normalised(self):
        register_session("dev_g", posture="join_runtime")
        result = update_session_posture("dev_g", "  ")
        assert result is not None
        assert result.posture == "control_only"


# ---------------------------------------------------------------------------
# C. update_session_posture — returns None for absent device
# ---------------------------------------------------------------------------


class TestUpdateSessionPostureAbsentDevice:
    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_C1_returns_none_for_unknown_device(self):
        result = update_session_posture("no_such_device", "join_runtime")
        assert result is None

    def test_C2_no_side_effects_on_other_devices(self):
        register_session("dev_h", posture="join_runtime")
        update_session_posture("nonexistent", "control_only")
        sessions = list_active_sessions()
        assert any(s.device_id == "dev_h" for s in sessions)


# ---------------------------------------------------------------------------
# D. update_session_posture — join_runtime preserved
# ---------------------------------------------------------------------------


class TestUpdateSessionPostureJoinRuntime:
    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_D1_join_runtime_set_correctly(self):
        register_session("dev_i", posture="control_only")
        result = update_session_posture("dev_i", "join_runtime")
        assert result is not None
        assert result.posture == "join_runtime"

    def test_D2_case_insensitive(self):
        register_session("dev_j", posture="control_only")
        result = update_session_posture("dev_j", "JOIN_RUNTIME")
        assert result is not None
        assert result.posture == "join_runtime"


# ---------------------------------------------------------------------------
# E. update_session_posture — metadata merged
# ---------------------------------------------------------------------------


class TestUpdateSessionPostureMetadataMerge:
    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_E1_new_metadata_merged(self):
        register_session("dev_k", posture="join_runtime", metadata={"original": True})
        result = update_session_posture("dev_k", "control_only", metadata={"new_key": "v"})
        assert result is not None
        assert result.metadata.get("original") is True
        assert result.metadata.get("new_key") == "v"


# ---------------------------------------------------------------------------
# F. _score_candidate — control_only posture rejected
# ---------------------------------------------------------------------------


class TestScoreCandidateControlOnly:
    def test_F1_control_only_returns_zero_score(self):
        score, reason = _score_candidate(
            "sess_1",
            "dev_1",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=False,
            posture="control_only",
        )
        assert score == 0
        assert reason == "posture:control_only:not_dispatch_target"

    def test_F2_rejection_reason_is_stable_string(self):
        _, reason = _score_candidate(
            "sess_2",
            "dev_2",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=False,
            posture="control_only",
        )
        assert "posture" in reason
        assert "control_only" in reason


# ---------------------------------------------------------------------------
# G. _score_candidate — join_runtime posture passes
# ---------------------------------------------------------------------------


class TestScoreCandidateJoinRuntime:
    def test_G1_join_runtime_passes(self):
        score, reason = _score_candidate(
            "sess_3",
            "dev_3",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=False,
            posture="join_runtime",
        )
        assert score > 0
        assert reason == ""

    def test_G2_reuse_bonus_still_applies(self):
        score_no_reuse, _ = _score_candidate(
            "sess_4",
            "dev_4",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=False,
            posture="join_runtime",
        )
        score_reuse, _ = _score_candidate(
            "sess_5",
            "dev_5",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=True,
            posture="join_runtime",
        )
        assert score_reuse > score_no_reuse


# ---------------------------------------------------------------------------
# H. _score_candidate — empty posture defaults to join_runtime
# ---------------------------------------------------------------------------


class TestScoreCandidateEmptyPosture:
    def test_H1_empty_posture_eligible(self):
        score, reason = _score_candidate(
            "sess_6",
            "dev_6",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=False,
            posture="",
        )
        assert score > 0
        assert reason == ""

    def test_H2_no_posture_kwarg_uses_default(self):
        score, reason = _score_candidate(
            "sess_7",
            "dev_7",
            readiness=_make_readiness(),
            participation=_make_participation(),
            reuse_eligible=False,
        )
        assert score > 0
        assert reason == ""


# ---------------------------------------------------------------------------
# I. _select_target_from_candidates — control_only device excluded
# ---------------------------------------------------------------------------


class TestSelectTargetControlOnlyExcluded:
    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_I1_control_only_device_not_selected(self):
        register_session("android_dev_1", posture="control_only")
        result = _select_target_from_candidates(
            readiness_inputs={"android_dev_1": _make_readiness()},
            participation_inputs={"android_dev_1": _make_participation()},
        )
        assert result is None

    def test_I2_control_only_after_posture_update_not_selected(self):
        register_session("android_dev_2", posture="join_runtime")
        update_session_posture("android_dev_2", "control_only")
        result = _select_target_from_candidates(
            readiness_inputs={"android_dev_2": _make_readiness()},
            participation_inputs={"android_dev_2": _make_participation()},
        )
        assert result is None


# ---------------------------------------------------------------------------
# J. _select_target_from_candidates — join_runtime device selected
# ---------------------------------------------------------------------------


class TestSelectTargetJoinRuntimeSelected:
    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_J1_join_runtime_device_selected(self):
        register_session("android_dev_3", posture="join_runtime")
        result = _select_target_from_candidates(
            readiness_inputs={"android_dev_3": _make_readiness()},
            participation_inputs={"android_dev_3": _make_participation()},
        )
        assert result is not None
        assert result.target_device_id == "android_dev_3"


# ---------------------------------------------------------------------------
# K. _select_target_from_candidates — mix: only join_runtime wins
# ---------------------------------------------------------------------------


class TestSelectTargetMixPostures:
    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_K1_only_join_runtime_device_wins(self):
        register_session("ctrl_dev", posture="control_only")
        register_session("join_dev", posture="join_runtime")
        result = _select_target_from_candidates(
            readiness_inputs={
                "ctrl_dev": _make_readiness(),
                "join_dev": _make_readiness(),
            },
            participation_inputs={
                "ctrl_dev": _make_participation(),
                "join_dev": _make_participation(),
            },
        )
        assert result is not None
        assert result.target_device_id == "join_dev"

    def test_K2_posture_update_changes_eligibility(self):
        register_session("swappable_dev", posture="join_runtime")
        # Before update: eligible
        r1 = _select_target_from_candidates(
            readiness_inputs={"swappable_dev": _make_readiness()},
            participation_inputs={"swappable_dev": _make_participation()},
        )
        assert r1 is not None

        # After posture update to control_only: ineligible
        update_session_posture("swappable_dev", "control_only")
        r2 = _select_target_from_candidates(
            readiness_inputs={"swappable_dev": _make_readiness()},
            participation_inputs={"swappable_dev": _make_participation()},
        )
        assert r2 is None


# ---------------------------------------------------------------------------
# L. handle_agent_status — posture field updates registry
# ---------------------------------------------------------------------------


class TestHandleAgentStatusPostureUpdate:
    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_L1_posture_field_updates_registry(self):
        from galaxy_gateway.android.handlers.heartbeat import handle_agent_status

        register_session("mobile_dev_1", posture="join_runtime")

        bridge = MagicMock()
        bridge._lock = asyncio.Lock()
        bridge._devices = {}
        bridge._patch_runtime_state_to_udm = MagicMock()

        message = {
            "device_id": "mobile_dev_1",
            "status": {"source_runtime_posture": "control_only"},
        }

        asyncio.run(handle_agent_status(bridge, None, message))

        sessions = list_active_sessions()
        entry = next((s for s in sessions if s.device_id == "mobile_dev_1"), None)
        assert entry is not None
        assert entry.posture == "control_only"

    def test_L2_posture_key_alternative_field_name(self):
        from galaxy_gateway.android.handlers.heartbeat import handle_agent_status

        register_session("mobile_dev_2", posture="control_only")

        bridge = MagicMock()
        bridge._lock = asyncio.Lock()
        bridge._devices = {}
        bridge._patch_runtime_state_to_udm = MagicMock()

        message = {
            "device_id": "mobile_dev_2",
            "status": {"posture": "join_runtime"},
        }

        asyncio.run(handle_agent_status(bridge, None, message))

        sessions = list_active_sessions()
        entry = next((s for s in sessions if s.device_id == "mobile_dev_2"), None)
        assert entry is not None
        assert entry.posture == "join_runtime"


# ---------------------------------------------------------------------------
# M. handle_agent_status — missing posture field silently ignored
# ---------------------------------------------------------------------------


class TestHandleAgentStatusNoPosture:
    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_M1_no_posture_field_unchanged(self):
        from galaxy_gateway.android.handlers.heartbeat import handle_agent_status

        register_session("mobile_dev_3", posture="join_runtime")

        bridge = MagicMock()
        bridge._lock = asyncio.Lock()
        bridge._devices = {}
        bridge._patch_runtime_state_to_udm = MagicMock()

        message = {
            "device_id": "mobile_dev_3",
            "status": {"battery": 90},  # no posture field
        }

        asyncio.run(handle_agent_status(bridge, None, message))

        sessions = list_active_sessions()
        entry = next((s for s in sessions if s.device_id == "mobile_dev_3"), None)
        assert entry is not None
        assert entry.posture == "join_runtime"  # unchanged


# ---------------------------------------------------------------------------
# N. handle_agent_status — unrecognised posture normalised to control_only
# ---------------------------------------------------------------------------


class TestHandleAgentStatusUnknownPosture:
    def setup_method(self):
        reset_session_registry()

    def teardown_method(self):
        reset_session_registry()

    def test_N1_unknown_posture_normalised(self):
        from galaxy_gateway.android.handlers.heartbeat import handle_agent_status

        register_session("mobile_dev_4", posture="join_runtime")

        bridge = MagicMock()
        bridge._lock = asyncio.Lock()
        bridge._devices = {}
        bridge._patch_runtime_state_to_udm = MagicMock()

        message = {
            "device_id": "mobile_dev_4",
            "status": {"source_runtime_posture": "unknown_mode"},
        }

        asyncio.run(handle_agent_status(bridge, None, message))

        sessions = list_active_sessions()
        entry = next((s for s in sessions if s.device_id == "mobile_dev_4"), None)
        assert entry is not None
        assert entry.posture == "control_only"  # normalised to safe default


# ---------------------------------------------------------------------------
# O. Sentinel constants importable from source_dispatch_orchestrator
# ---------------------------------------------------------------------------


class TestOrchestatorSentinelsImportable:
    def test_O1_android_posture_gating_integrated_sentinel(self):
        assert "ANDROID_POSTURE_GATING_INTEGRATED" in ANDROID_POSTURE_GATING_INTEGRATED_SENTINEL

    def test_O2_control_only_not_dispatch_target_policy(self):
        assert "control_only" in ANDROID_CONTROL_ONLY_POSTURE_IS_NOT_DISPATCH_TARGET_POLICY

    def test_O3_backward_compat_policy(self):
        assert "join_runtime" in POSTURE_GATE_PRESERVES_BACKWARD_COMPAT_POLICY

    def test_O4_next_selection_cycle_policy(self):
        assert "control_only" in POSTURE_UPDATE_AFFECTS_NEXT_SELECTION_CYCLE_POLICY


# ---------------------------------------------------------------------------
# P. Policy sentinel importable from attached_runtime_session_registry
# ---------------------------------------------------------------------------


class TestRegistrySentinelImportable:
    def test_P1_android_posture_gating_update_authority(self):
        assert "update_session_posture" in ANDROID_POSTURE_GATING_UPDATE_AUTHORITY
