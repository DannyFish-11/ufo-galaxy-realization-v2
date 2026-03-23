#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr32_permission_safety_state.py
==========================================
Tests for PR-32: Harden permission visibility, trust surfaces, and control
safety for multimodal runtime.

Coverage
--------
1.  PermissionStatus enum
    - all expected values present and stable
    - from_string round-trips all known values
    - from_string returns UNKNOWN for unrecognised input

2.  TrustLabel enum
    - all expected values present and stable
    - from_string round-trips all known values
    - from_string returns UNKNOWN for unrecognised input

3.  SafetyGatingReason enum
    - all expected values present and stable
    - from_string round-trips all known values
    - from_string returns NONE for unrecognised input

4.  ExecutionRiskTier enum
    - all expected values present and stable
    - from_string round-trips all known values
    - from_string returns UNKNOWN for unrecognised input

5.  ModalityPermissionRecord
    - to_dict / from_dict round-trip
    - sensitive modalities are flagged correctly
    - unavailable health → RESTRICTED trust label and PERMISSION_UNAVAILABLE gating
    - denied health → DENIED status and PERMISSION_DENIED gating
    - healthy active microphone → SENSITIVE trust label

6.  ExecutionTrustAnnotation
    - to_dict / from_dict round-trip
    - annotation_id is generated when omitted
    - remote elevated execution sets requires_confirmation=True

7.  PermissionSafetySnapshot
    - to_dict / from_dict round-trip (including nested records)
    - from_dict with execution_trust_annotation nested dict

8.  OperatorSafetySummary
    - to_dict / from_dict round-trip
    - derived_from_snapshot_id matches the snapshot

9.  build_permission_safety_snapshot (acceptance: projection coherence)
    - empty input produces valid snapshot with UNKNOWN trust label
    - source registry with healthy microphone → SENSITIVE trust, active sensitive list
    - source registry with unavailable camera → any_permission_missing=True
    - source registry with denied source → any_permission_denied=True
    - canonical_perception active_modalities supplement registry records
    - degradation_reasons propagated from canonical_perception
    - remote REMOTE_AGENT step in execution plan → REMOTE_ELEVATED risk tier
    - degraded envelope with critical severity → gating reason present
    - is_gated=True when gating reasons are non-empty
    - snapshot is fully JSON-serialisable

10. build_operator_safety_summary (shell-facing summaries)
    - summary fields mirror snapshot values
    - active sensitive modalities appear in operator_message
    - missing permission visible in operator_message
    - gating reason visible in operator_message
    - remote pending visible in operator_message
    - derived_from_snapshot_id matches snapshot.snapshot_id
    - summary never acts as independent truth source (fields are derived)

11. PermissionSafetyState singleton
    - get_permission_safety_state returns same object on repeated calls
    - reset_permission_safety_state clears singleton
    - commit/latest_snapshot round-trip
    - snapshot_dict returns None when no snapshot committed

12. Missing/denied permissions degrade clearly (acceptance: gating visibility)
    - denied modality leads to is_gated=True and reason in safety_gating_reasons
    - unavailable modality leads to any_permission_missing=True

13. Remote/elevated execution trust annotations (acceptance: high-risk visibility)
    - local execution → LOCAL_SAFE tier, TRUSTED label
    - remote agent → REMOTE_ELEVATED tier, ELEVATED label
    - remote elevated → requires_confirmation=True

14. Safety state serialisation alignment
    - full snapshot serialises and deserialises without data loss
    - operator summary to_dict matches known structure

15. OpenClawd integration (permission_safety_state in response metadata)
    - _build_permission_safety_state returns a dict
    - returned dict is JSON-serialisable
    - singleton is updated after call

16. DesktopPresenceRuntime integration
    - permission_safety_summary returns a dict with expected keys
    - permission_safety_summary with registry-populated snapshot has trust label
    - permission_safety_summary never raises
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _import_module():
    from core.multimodal.permission_safety_state import (
        PermissionStatus,
        TrustLabel,
        SafetyGatingReason,
        ExecutionRiskTier,
        ModalityPermissionRecord,
        ExecutionTrustAnnotation,
        PermissionSafetySnapshot,
        OperatorSafetySummary,
        build_permission_safety_snapshot,
        build_operator_safety_summary,
        get_permission_safety_state,
        reset_permission_safety_state,
        PermissionSafetyState,
    )
    return (
        PermissionStatus,
        TrustLabel,
        SafetyGatingReason,
        ExecutionRiskTier,
        ModalityPermissionRecord,
        ExecutionTrustAnnotation,
        PermissionSafetySnapshot,
        OperatorSafetySummary,
        build_permission_safety_snapshot,
        build_operator_safety_summary,
        get_permission_safety_state,
        reset_permission_safety_state,
        PermissionSafetyState,
    )


def _make_source_registry_snapshot(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"sources": sources}


def _mic_source(health: str = "healthy", is_active: bool = True) -> Dict[str, Any]:
    return {
        "source_id": "builtin:microphone",
        "modality": "microphone",
        "health": health,
        "is_active": is_active,
    }


def _cam_source(health: str = "healthy", is_active: bool = True) -> Dict[str, Any]:
    return {
        "source_id": "builtin:webcam",
        "modality": "camera",
        "health": health,
        "is_active": is_active,
    }


def _remote_execution_plan() -> Dict[str, Any]:
    return {
        "steps": [
            {"step_type": "REMOTE_AGENT", "description": "deploy agent on remote node"}
        ]
    }


def _local_execution_plan() -> Dict[str, Any]:
    return {"steps": [{"step_type": "LOCAL_MANIFESTATION", "description": "local ui"}]}


# ---------------------------------------------------------------------------
# 1. PermissionStatus
# ---------------------------------------------------------------------------


class TestPermissionStatus:
    def test_all_values_present(self):
        (PermissionStatus, *_) = _import_module()
        values = {v.value for v in PermissionStatus}
        assert "granted" in values
        assert "denied" in values
        assert "unavailable" in values
        assert "unknown" in values

    def test_from_string_round_trip(self):
        (PermissionStatus, *_) = _import_module()
        for member in PermissionStatus:
            assert PermissionStatus.from_string(member.value) == member

    def test_from_string_unknown_default(self):
        (PermissionStatus, *_) = _import_module()
        assert PermissionStatus.from_string("nonsense") == PermissionStatus.UNKNOWN


# ---------------------------------------------------------------------------
# 2. TrustLabel
# ---------------------------------------------------------------------------


class TestTrustLabel:
    def test_all_values_present(self):
        _, TrustLabel, *_ = _import_module()
        values = {v.value for v in TrustLabel}
        assert "trusted" in values
        assert "elevated" in values
        assert "sensitive" in values
        assert "restricted" in values
        assert "unknown" in values

    def test_from_string_round_trip(self):
        _, TrustLabel, *_ = _import_module()
        for member in TrustLabel:
            assert TrustLabel.from_string(member.value) == member

    def test_from_string_unknown_default(self):
        _, TrustLabel, *_ = _import_module()
        assert TrustLabel.from_string("nope") == TrustLabel.UNKNOWN


# ---------------------------------------------------------------------------
# 3. SafetyGatingReason
# ---------------------------------------------------------------------------


class TestSafetyGatingReason:
    def test_all_values_present(self):
        _, _, SafetyGatingReason, *_ = _import_module()
        values = {v.value for v in SafetyGatingReason}
        assert "permission_denied" in values
        assert "permission_unavailable" in values
        assert "permission_unknown" in values
        assert "source_degraded" in values
        assert "source_unavailable" in values
        assert "source_stale" in values
        assert "sensitive_modality_unconfirmed" in values
        assert "remote_execution_unconfirmed" in values
        assert "elevated_risk_unreviewed" in values
        assert "policy_guard" in values
        assert "none" in values

    def test_from_string_round_trip(self):
        _, _, SafetyGatingReason, *_ = _import_module()
        for member in SafetyGatingReason:
            assert SafetyGatingReason.from_string(member.value) == member

    def test_from_string_none_default(self):
        _, _, SafetyGatingReason, *_ = _import_module()
        assert SafetyGatingReason.from_string("???") == SafetyGatingReason.NONE


# ---------------------------------------------------------------------------
# 4. ExecutionRiskTier
# ---------------------------------------------------------------------------


class TestExecutionRiskTier:
    def test_all_values_present(self):
        _, _, _, ExecutionRiskTier, *_ = _import_module()
        values = {v.value for v in ExecutionRiskTier}
        assert "local_safe" in values
        assert "local_elevated" in values
        assert "remote_standard" in values
        assert "remote_elevated" in values
        assert "unknown" in values

    def test_from_string_round_trip(self):
        _, _, _, ExecutionRiskTier, *_ = _import_module()
        for member in ExecutionRiskTier:
            assert ExecutionRiskTier.from_string(member.value) == member

    def test_from_string_unknown_default(self):
        _, _, _, ExecutionRiskTier, *_ = _import_module()
        assert ExecutionRiskTier.from_string("???") == ExecutionRiskTier.UNKNOWN


# ---------------------------------------------------------------------------
# 5. ModalityPermissionRecord
# ---------------------------------------------------------------------------


class TestModalityPermissionRecord:
    def test_to_dict_from_dict_round_trip(self):
        (
            PermissionStatus,
            TrustLabel,
            SafetyGatingReason,
            _,
            ModalityPermissionRecord,
            *_,
        ) = _import_module()
        rec = ModalityPermissionRecord(
            modality="microphone",
            source_id="builtin:mic",
            permission_status=PermissionStatus.GRANTED,
            trust_label=TrustLabel.SENSITIVE,
            is_active=True,
            is_sensitive=True,
            gating_reason=SafetyGatingReason.NONE,
            gating_reasons=[],
        )
        d = rec.to_dict()
        rec2 = ModalityPermissionRecord.from_dict(d)
        assert rec2.modality == "microphone"
        assert rec2.permission_status == PermissionStatus.GRANTED
        assert rec2.trust_label == TrustLabel.SENSITIVE
        assert rec2.is_active is True
        assert rec2.is_sensitive is True
        assert rec2.gating_reason == SafetyGatingReason.NONE

    def test_sensitive_modalities_flagged(self):
        _, _, _, _, ModalityPermissionRecord, *_ = _import_module()
        rec = ModalityPermissionRecord.from_dict({"modality": "camera", "is_sensitive": True})
        assert rec.is_sensitive is True

    def test_unavailable_health_restricted_label(self):
        (
            PermissionStatus,
            TrustLabel,
            SafetyGatingReason,
            _,
            ModalityPermissionRecord,
            *_,
        ) = _import_module()
        # Build via build_permission_safety_snapshot with unavailable source
        from core.multimodal.permission_safety_state import build_permission_safety_snapshot
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot(
                [_cam_source(health="unavailable")]
            )
        )
        rec = snap.modality_permissions[0]
        assert rec.permission_status == PermissionStatus.UNAVAILABLE
        assert rec.trust_label == TrustLabel.RESTRICTED
        assert SafetyGatingReason.PERMISSION_UNAVAILABLE.value in rec.gating_reasons

    def test_denied_health_denied_status(self):
        from core.multimodal.permission_safety_state import (
            PermissionStatus,
            TrustLabel,
            build_permission_safety_snapshot,
        )
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot(
                [{"modality": "microphone", "health": "denied", "is_active": False}]
            )
        )
        rec = snap.modality_permissions[0]
        assert rec.permission_status == PermissionStatus.DENIED
        assert rec.trust_label == TrustLabel.RESTRICTED

    def test_healthy_active_microphone_sensitive_label(self):
        from core.multimodal.permission_safety_state import (
            TrustLabel,
            build_permission_safety_snapshot,
        )
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot([_mic_source()])
        )
        rec = snap.modality_permissions[0]
        assert rec.trust_label == TrustLabel.SENSITIVE
        assert rec.is_sensitive is True
        assert rec.is_active is True


# ---------------------------------------------------------------------------
# 6. ExecutionTrustAnnotation
# ---------------------------------------------------------------------------


class TestExecutionTrustAnnotation:
    def test_to_dict_from_dict_round_trip(self):
        (
            _,
            TrustLabel,
            SafetyGatingReason,
            ExecutionRiskTier,
            _,
            ExecutionTrustAnnotation,
            *_,
        ) = _import_module()
        ann = ExecutionTrustAnnotation(
            execution_id="test-exec-1",
            risk_tier=ExecutionRiskTier.REMOTE_ELEVATED,
            trust_label=TrustLabel.ELEVATED,
            is_remote=True,
            is_elevated=True,
            requires_confirmation=True,
            remote_execution_mode="agent_runtime",
            eligibility_confirmed=False,
            gating_reason=SafetyGatingReason.REMOTE_EXECUTION_UNCONFIRMED,
            gating_reasons=[SafetyGatingReason.REMOTE_EXECUTION_UNCONFIRMED.value],
        )
        d = ann.to_dict()
        ann2 = ExecutionTrustAnnotation.from_dict(d)
        assert ann2.execution_id == "test-exec-1"
        assert ann2.risk_tier == ExecutionRiskTier.REMOTE_ELEVATED
        assert ann2.trust_label == TrustLabel.ELEVATED
        assert ann2.is_remote is True
        assert ann2.requires_confirmation is True
        assert ann2.remote_execution_mode == "agent_runtime"

    def test_annotation_id_generated(self):
        from core.multimodal.permission_safety_state import ExecutionTrustAnnotation
        ann = ExecutionTrustAnnotation()
        assert ann.annotation_id is not None
        assert len(ann.annotation_id) > 0

    def test_remote_elevated_requires_confirmation(self):
        from core.multimodal.permission_safety_state import build_permission_safety_snapshot
        snap = build_permission_safety_snapshot(
            execution_plan=_remote_execution_plan(),
        )
        assert snap.execution_trust_annotation is not None
        assert snap.execution_trust_annotation.is_remote is True
        assert snap.execution_trust_annotation.requires_confirmation is True


# ---------------------------------------------------------------------------
# 7. PermissionSafetySnapshot
# ---------------------------------------------------------------------------


class TestPermissionSafetySnapshot:
    def test_to_dict_from_dict_round_trip(self):
        (
            PermissionStatus,
            TrustLabel,
            SafetyGatingReason,
            ExecutionRiskTier,
            ModalityPermissionRecord,
            ExecutionTrustAnnotation,
            PermissionSafetySnapshot,
            *_,
        ) = _import_module()
        snap = PermissionSafetySnapshot(
            trace_id="t-1",
            runtime_session_id="rs-1",
            modality_permissions=[
                ModalityPermissionRecord(
                    modality="microphone",
                    permission_status=PermissionStatus.GRANTED,
                    trust_label=TrustLabel.SENSITIVE,
                    is_active=True,
                    is_sensitive=True,
                )
            ],
            active_sensitive_modalities=["microphone"],
            any_permission_denied=False,
            any_permission_missing=False,
            overall_trust_label=TrustLabel.SENSITIVE,
            safety_gating_reasons=[],
            is_gated=False,
        )
        d = snap.to_dict()
        snap2 = PermissionSafetySnapshot.from_dict(d)
        assert snap2.trace_id == "t-1"
        assert snap2.runtime_session_id == "rs-1"
        assert len(snap2.modality_permissions) == 1
        assert snap2.modality_permissions[0].modality == "microphone"
        assert snap2.overall_trust_label == TrustLabel.SENSITIVE
        assert snap2.is_gated is False

    def test_nested_execution_trust_annotation_survives_round_trip(self):
        from core.multimodal.permission_safety_state import (
            PermissionSafetySnapshot,
            ExecutionTrustAnnotation,
            ExecutionRiskTier,
            TrustLabel,
        )
        eta = ExecutionTrustAnnotation(
            risk_tier=ExecutionRiskTier.REMOTE_ELEVATED,
            trust_label=TrustLabel.ELEVATED,
            is_remote=True,
        )
        snap = PermissionSafetySnapshot(execution_trust_annotation=eta)
        d = snap.to_dict()
        snap2 = PermissionSafetySnapshot.from_dict(d)
        assert snap2.execution_trust_annotation is not None
        assert snap2.execution_trust_annotation.is_remote is True
        assert snap2.execution_trust_annotation.risk_tier == ExecutionRiskTier.REMOTE_ELEVATED


# ---------------------------------------------------------------------------
# 8. OperatorSafetySummary
# ---------------------------------------------------------------------------


class TestOperatorSafetySummary:
    def test_to_dict_from_dict_round_trip(self):
        (
            _,
            TrustLabel,
            SafetyGatingReason,
            _,
            _,
            _,
            _,
            OperatorSafetySummary,
            *_,
        ) = _import_module()
        summary = OperatorSafetySummary(
            overall_trust_label=TrustLabel.SENSITIVE,
            active_sensitive_modalities=["microphone"],
            any_permission_missing=False,
            is_gated=False,
            primary_gating_reason=SafetyGatingReason.NONE.value,
            remote_execution_pending=False,
            operator_message="trust=sensitive [sensitive:microphone]",
            derived_from_snapshot_id="snap-1",
        )
        d = summary.to_dict()
        s2 = OperatorSafetySummary.from_dict(d)
        assert s2.overall_trust_label == TrustLabel.SENSITIVE
        assert s2.active_sensitive_modalities == ["microphone"]
        assert s2.derived_from_snapshot_id == "snap-1"

    def test_derived_from_snapshot_id_matches_snapshot(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            build_operator_safety_summary,
        )
        snap = build_permission_safety_snapshot()
        summary = build_operator_safety_summary(snap)
        assert summary.derived_from_snapshot_id == snap.snapshot_id


# ---------------------------------------------------------------------------
# 9. build_permission_safety_snapshot
# ---------------------------------------------------------------------------


class TestBuildPermissionSafetySnapshot:
    def test_empty_input_valid_snapshot(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            TrustLabel,
        )
        snap = build_permission_safety_snapshot()
        assert snap is not None
        assert snap.overall_trust_label is not None
        assert isinstance(snap.snapshot_id, str)

    def test_healthy_microphone_sensitive_trust_active_list(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            TrustLabel,
        )
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot([_mic_source()])
        )
        assert "microphone" in snap.active_sensitive_modalities
        # worst-case label: sensitive
        assert snap.overall_trust_label in (TrustLabel.SENSITIVE, TrustLabel.RESTRICTED)

    def test_unavailable_camera_permission_missing(self):
        from core.multimodal.permission_safety_state import build_permission_safety_snapshot
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot(
                [_cam_source(health="unavailable")]
            )
        )
        assert snap.any_permission_missing is True

    def test_denied_source_permission_denied(self):
        from core.multimodal.permission_safety_state import build_permission_safety_snapshot
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot(
                [{"modality": "microphone", "health": "denied", "is_active": False}]
            )
        )
        assert snap.any_permission_denied is True
        assert snap.any_permission_missing is True

    def test_canonical_perception_active_modalities_supplement_registry(self):
        from core.multimodal.permission_safety_state import build_permission_safety_snapshot
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot([]),
            canonical_perception={
                "active_modalities": ["text", "audio"],
                "degradation_reasons": [],
            },
        )
        modality_names = {r.modality for r in snap.modality_permissions}
        assert "text" in modality_names
        assert "audio" in modality_names

    def test_degradation_reasons_propagated_from_perception(self):
        from core.multimodal.permission_safety_state import build_permission_safety_snapshot
        snap = build_permission_safety_snapshot(
            canonical_perception={"degradation_reasons": ["text_only", "no_audio"]}
        )
        assert "text_only" in snap.degradation_reasons
        assert "no_audio" in snap.degradation_reasons

    def test_remote_agent_step_remote_elevated_risk_tier(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            ExecutionRiskTier,
        )
        snap = build_permission_safety_snapshot(execution_plan=_remote_execution_plan())
        assert snap.execution_trust_annotation is not None
        assert snap.execution_trust_annotation.risk_tier == ExecutionRiskTier.REMOTE_ELEVATED

    def test_degraded_envelope_critical_severity_gating_reason(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            SafetyGatingReason,
        )
        snap = build_permission_safety_snapshot(
            degraded_operation_envelope={"operator_severity": "critical"}
        )
        assert snap.is_gated is True
        assert SafetyGatingReason.ELEVATED_RISK_UNREVIEWED.value in snap.safety_gating_reasons

    def test_is_gated_when_gating_reasons_nonempty(self):
        from core.multimodal.permission_safety_state import build_permission_safety_snapshot
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot(
                [_cam_source(health="unavailable")]
            )
        )
        assert snap.is_gated is True
        assert len(snap.safety_gating_reasons) > 0

    def test_json_serialisable(self):
        from core.multimodal.permission_safety_state import build_permission_safety_snapshot
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot(
                [_mic_source(), _cam_source(health="unavailable")]
            ),
            execution_plan=_remote_execution_plan(),
            trace_id="trace-json-test",
        )
        d = snap.to_dict()
        # Must not raise
        serialised = json.dumps(d)
        assert "microphone" in serialised


# ---------------------------------------------------------------------------
# 10. build_operator_safety_summary
# ---------------------------------------------------------------------------


class TestBuildOperatorSafetySummary:
    def test_fields_mirror_snapshot(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            build_operator_safety_summary,
        )
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot([_mic_source()])
        )
        summary = build_operator_safety_summary(snap)
        assert summary.overall_trust_label == snap.overall_trust_label
        assert summary.any_permission_missing == snap.any_permission_missing
        assert summary.is_gated == snap.is_gated
        assert summary.active_sensitive_modalities == snap.active_sensitive_modalities

    def test_active_sensitive_in_operator_message(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            build_operator_safety_summary,
        )
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot([_mic_source()])
        )
        summary = build_operator_safety_summary(snap)
        assert "microphone" in summary.operator_message

    def test_missing_permission_in_operator_message(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            build_operator_safety_summary,
        )
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot(
                [_cam_source(health="unavailable")]
            )
        )
        summary = build_operator_safety_summary(snap)
        assert "permission" in summary.operator_message.lower()

    def test_gating_reason_in_operator_message(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            build_operator_safety_summary,
        )
        snap = build_permission_safety_snapshot(
            degraded_operation_envelope={"operator_severity": "critical"}
        )
        summary = build_operator_safety_summary(snap)
        assert "gated" in summary.operator_message.lower()

    def test_remote_pending_in_operator_message(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            build_operator_safety_summary,
        )
        snap = build_permission_safety_snapshot(execution_plan=_remote_execution_plan())
        summary = build_operator_safety_summary(snap)
        assert summary.remote_execution_pending is True
        assert "remote" in summary.operator_message.lower()

    def test_derived_from_snapshot_id_correct(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            build_operator_safety_summary,
        )
        snap = build_permission_safety_snapshot()
        summary = build_operator_safety_summary(snap)
        assert summary.derived_from_snapshot_id == snap.snapshot_id

    def test_summary_fields_are_derived_from_snapshot(self):
        """Verify summary never adds state not present in snapshot."""
        from core.multimodal.permission_safety_state import (
            PermissionSafetySnapshot,
            TrustLabel,
            build_operator_safety_summary,
        )
        snap = PermissionSafetySnapshot(
            overall_trust_label=TrustLabel.TRUSTED,
            active_sensitive_modalities=[],
            any_permission_missing=False,
            is_gated=False,
            safety_gating_reasons=[],
        )
        summary = build_operator_safety_summary(snap)
        assert summary.overall_trust_label == TrustLabel.TRUSTED
        assert summary.active_sensitive_modalities == []
        assert summary.is_gated is False


# ---------------------------------------------------------------------------
# 11. PermissionSafetyState singleton
# ---------------------------------------------------------------------------


class TestPermissionSafetyStateSingleton:
    def setup_method(self):
        from core.multimodal.permission_safety_state import reset_permission_safety_state
        reset_permission_safety_state()

    def test_same_singleton_repeated_calls(self):
        from core.multimodal.permission_safety_state import (
            get_permission_safety_state,
            reset_permission_safety_state,
        )
        reset_permission_safety_state()
        s1 = get_permission_safety_state()
        s2 = get_permission_safety_state()
        assert s1 is s2

    def test_reset_clears_singleton(self):
        from core.multimodal.permission_safety_state import (
            get_permission_safety_state,
            reset_permission_safety_state,
        )
        reset_permission_safety_state()
        s1 = get_permission_safety_state()
        reset_permission_safety_state()
        s2 = get_permission_safety_state()
        assert s1 is not s2

    def test_commit_latest_snapshot_round_trip(self):
        from core.multimodal.permission_safety_state import (
            get_permission_safety_state,
            build_permission_safety_snapshot,
        )
        state = get_permission_safety_state()
        snap = build_permission_safety_snapshot(trace_id="commit-test")
        state.commit(snap)
        assert state.latest_snapshot is snap

    def test_snapshot_dict_none_when_uncommitted(self):
        from core.multimodal.permission_safety_state import (
            get_permission_safety_state,
            reset_permission_safety_state,
        )
        reset_permission_safety_state()
        state = get_permission_safety_state()
        assert state.snapshot_dict() is None

    def test_snapshot_dict_after_commit(self):
        from core.multimodal.permission_safety_state import (
            get_permission_safety_state,
            build_permission_safety_snapshot,
        )
        state = get_permission_safety_state()
        snap = build_permission_safety_snapshot(trace_id="dict-test")
        state.commit(snap)
        d = state.snapshot_dict()
        assert isinstance(d, dict)
        assert d["trace_id"] == "dict-test"


# ---------------------------------------------------------------------------
# 12. Missing/denied permissions degrade clearly
# ---------------------------------------------------------------------------


class TestPermissionDegradationVisibility:
    def test_denied_leads_to_is_gated(self):
        from core.multimodal.permission_safety_state import build_permission_safety_snapshot
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot(
                [{"modality": "microphone", "health": "denied", "is_active": False}]
            )
        )
        assert snap.is_gated is True
        assert "permission_denied" in snap.safety_gating_reasons

    def test_unavailable_leads_to_permission_missing(self):
        from core.multimodal.permission_safety_state import build_permission_safety_snapshot
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot(
                [_cam_source(health="unavailable")]
            )
        )
        assert snap.any_permission_missing is True
        assert snap.is_gated is True


# ---------------------------------------------------------------------------
# 13. Remote/elevated execution trust annotations
# ---------------------------------------------------------------------------


class TestExecutionTrustAnnotationIntegration:
    def test_local_execution_local_safe_trusted(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            ExecutionRiskTier,
            TrustLabel,
        )
        snap = build_permission_safety_snapshot(execution_plan=_local_execution_plan())
        assert snap.execution_trust_annotation is not None
        assert snap.execution_trust_annotation.risk_tier == ExecutionRiskTier.LOCAL_SAFE
        assert snap.execution_trust_annotation.trust_label == TrustLabel.TRUSTED

    def test_remote_agent_remote_elevated_elevated_label(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            ExecutionRiskTier,
            TrustLabel,
        )
        snap = build_permission_safety_snapshot(execution_plan=_remote_execution_plan())
        ann = snap.execution_trust_annotation
        assert ann is not None
        assert ann.risk_tier == ExecutionRiskTier.REMOTE_ELEVATED
        assert ann.trust_label == TrustLabel.ELEVATED

    def test_remote_elevated_requires_confirmation(self):
        from core.multimodal.permission_safety_state import build_permission_safety_snapshot
        snap = build_permission_safety_snapshot(execution_plan=_remote_execution_plan())
        ann = snap.execution_trust_annotation
        assert ann is not None
        assert ann.requires_confirmation is True
        assert ann.eligibility_confirmed is False


# ---------------------------------------------------------------------------
# 14. Safety state serialisation alignment
# ---------------------------------------------------------------------------


class TestSerialisationAlignment:
    def test_full_snapshot_serialise_deserialise_no_loss(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            PermissionSafetySnapshot,
        )
        snap = build_permission_safety_snapshot(
            source_registry_snapshot=_make_source_registry_snapshot(
                [_mic_source(), _cam_source(health="unavailable")]
            ),
            execution_plan=_remote_execution_plan(),
            canonical_perception={"active_modalities": ["audio"], "degradation_reasons": []},
            trace_id="serial-test",
            runtime_session_id="session-x",
        )
        d = snap.to_dict()
        snap2 = PermissionSafetySnapshot.from_dict(d)
        assert snap2.trace_id == "serial-test"
        assert snap2.runtime_session_id == "session-x"
        assert snap2.any_permission_missing == snap.any_permission_missing
        assert snap2.is_gated == snap.is_gated
        assert snap2.overall_trust_label == snap.overall_trust_label
        assert len(snap2.modality_permissions) == len(snap.modality_permissions)

    def test_operator_summary_dict_has_expected_keys(self):
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            build_operator_safety_summary,
        )
        snap = build_permission_safety_snapshot()
        summary = build_operator_safety_summary(snap)
        d = summary.to_dict()
        expected_keys = {
            "overall_trust_label",
            "active_sensitive_modalities",
            "any_permission_missing",
            "is_gated",
            "primary_gating_reason",
            "remote_execution_pending",
            "operator_message",
            "derived_from_snapshot_id",
            "derived_at",
        }
        assert expected_keys.issubset(set(d.keys()))


# ---------------------------------------------------------------------------
# 15. OpenClawd integration
# ---------------------------------------------------------------------------


class TestOpenClawdIntegration:
    def test_build_permission_safety_state_returns_dict(self):
        """_build_permission_safety_state returns a serialisable dict."""
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        # Minimal initialisation
        oc._logger = __import__("logging").getLogger("test")

        result = oc._build_permission_safety_state(
            multimodal_route={"route_type": "text_only", "is_native_multimodal": False},
            canonical_perception={"active_modalities": [], "degradation_reasons": ["text_only"]},
            trace_id="oc-test",
            runtime_session_id="rs-oc-test",
        )
        assert result is not None
        assert isinstance(result, dict)

    def test_build_permission_safety_state_json_serialisable(self):
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        oc._logger = __import__("logging").getLogger("test")

        result = oc._build_permission_safety_state(
            multimodal_route={"route_type": "text_only"},
            trace_id="json-oc-test",
        )
        assert result is not None
        json.dumps(result)  # must not raise

    def test_singleton_updated_after_call(self):
        from core.multimodal.permission_safety_state import (
            get_permission_safety_state,
            reset_permission_safety_state,
        )
        from core.openclawd import OpenClawd

        reset_permission_safety_state()
        oc = OpenClawd.__new__(OpenClawd)
        oc._logger = __import__("logging").getLogger("test")

        oc._build_permission_safety_state(
            trace_id="singleton-update-test",
        )
        state = get_permission_safety_state()
        assert state.latest_snapshot is not None


# ---------------------------------------------------------------------------
# 16. DesktopPresenceRuntime integration
# ---------------------------------------------------------------------------


class TestDesktopPresenceRuntimeIntegration:
    def _make_runtime(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        rt = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
        # Minimal initialisation for permission_safety_summary
        from core.multimodal.perception_source_registry import PerceptionSourceRegistry
        rt._source_registry = PerceptionSourceRegistry()
        return rt

    def test_permission_safety_summary_returns_dict(self):
        rt = self._make_runtime()
        result = rt.permission_safety_summary()
        assert isinstance(result, dict)

    def test_permission_safety_summary_has_operator_message(self):
        rt = self._make_runtime()
        result = rt.permission_safety_summary()
        assert "operator_message" in result

    def test_permission_safety_summary_trust_label_present(self):
        from core.multimodal.permission_safety_state import (
            reset_permission_safety_state,
        )
        reset_permission_safety_state()
        rt = self._make_runtime()
        result = rt.permission_safety_summary()
        assert "overall_trust_label" in result

    def test_permission_safety_summary_never_raises(self):
        """permission_safety_summary must never propagate exceptions."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        rt = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
        # Deliberately broken registry to test resilience
        rt._source_registry = None
        result = rt.permission_safety_summary()
        assert isinstance(result, dict)

    def test_permission_safety_summary_from_result_dict(self):
        """When given an OpenClawd result dict, the method uses embedded snapshot."""
        from core.multimodal.permission_safety_state import (
            build_permission_safety_snapshot,
            reset_permission_safety_state,
        )
        reset_permission_safety_state()
        rt = self._make_runtime()
        snap = build_permission_safety_snapshot(trace_id="rt-result-test")
        fake_result = {
            "metadata": {
                "permission_safety_state": snap.to_dict()
            }
        }
        result = rt.permission_safety_summary(result=fake_result)
        assert result["derived_from_snapshot_id"] == snap.snapshot_id


# ---------------------------------------------------------------------------
# Module import smoke-test
# ---------------------------------------------------------------------------


class TestModuleImports:
    def test_all_public_symbols_importable(self):
        from core.multimodal.permission_safety_state import (
            PermissionStatus,
            TrustLabel,
            SafetyGatingReason,
            ExecutionRiskTier,
            ModalityPermissionRecord,
            ExecutionTrustAnnotation,
            PermissionSafetySnapshot,
            OperatorSafetySummary,
            build_permission_safety_snapshot,
            build_operator_safety_summary,
            get_permission_safety_state,
            reset_permission_safety_state,
            PermissionSafetyState,
        )
        assert PermissionSafetyState is not None
