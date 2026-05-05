#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5v2_operator_observability.py
==========================================
PR-5 V2: Operator-facing observability and diagnosability improvements.

Validates that the following observability gaps are closed by the current code:

A.  DeviceStateSnapshot.to_dict() includes snapshot_age_seconds (freshness).
B.  get_ecosystem_summary() includes last_snapshot_absorbed_at,
    snapshot_freshness_seconds, and snapshot_truth_received.
C.  OperatorSnapshot.android_ecosystem carries freshness keys after a
    snapshot is absorbed (ANDROID_ECOSYSTEM_SNAPSHOT_KEYS whitelist).
D.  ANDROID_ECOSYSTEM_SNAPSHOT_KEYS includes the three new freshness keys.
E.  FlowOperatorProjection.to_dict() includes last_event_absorbed_at.
F.  inspect_flow() populates last_event_absorbed_at from entity metadata.
G.  snapshot_truth_received is False when store is empty.
H.  snapshot_age_seconds is non-negative.
I.  snapshot_freshness_seconds is non-negative when devices exist.
J.  last_event_absorbed_at is None when no execution event has been absorbed.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_stores():
    """Reset all relevant singletons before and after each test."""
    try:
        from core.android_device_state_store import reset_android_device_state_store
        reset_android_device_state_store()
    except Exception:
        pass
    try:
        from core.operator_surface import reset_operator_surface
        reset_operator_surface()
    except Exception:
        pass
    try:
        from core.flow_level_operator_surface import reset_flow_level_operator_surface
        reset_flow_level_operator_surface()
    except Exception:
        pass
    try:
        from core.delegated_flow_entity import reset_delegated_flow_entity_runtime
        reset_delegated_flow_entity_runtime()
    except Exception:
        pass
    yield
    try:
        from core.android_device_state_store import reset_android_device_state_store
        reset_android_device_state_store()
    except Exception:
        pass
    try:
        from core.operator_surface import reset_operator_surface
        reset_operator_surface()
    except Exception:
        pass
    try:
        from core.flow_level_operator_surface import reset_flow_level_operator_surface
        reset_flow_level_operator_surface()
    except Exception:
        pass
    try:
        from core.delegated_flow_entity import reset_delegated_flow_entity_runtime
        reset_delegated_flow_entity_runtime()
    except Exception:
        pass


def _absorb_snapshot(device_id: str = "dev_001", **kwargs):
    from core.android_device_state_store import absorb_device_state_snapshot
    payload = {"model_ready": True, "llama_cpp_available": True, "local_loop_ready": True}
    payload.update(kwargs)
    return absorb_device_state_snapshot(device_id, payload)


def _register_flow(canonical_task_id: str = "", device_id: str = "dev_001"):
    from core.delegated_flow_entity import (
        create_delegated_flow_entity,
        record_delegated_flow,
        DelegatedFlowKind,
    )
    entity = create_delegated_flow_entity(
        flow_kind=DelegatedFlowKind.task_assign,
        canonical_task_id=canonical_task_id,
        device_id=device_id,
    )
    record_delegated_flow(entity)
    return entity


# ===========================================================================
# A.  DeviceStateSnapshot.to_dict() includes snapshot_age_seconds
# ===========================================================================


class TestSnapshotAgeSeconds:
    def test_A01_snapshot_age_seconds_present_in_to_dict(self):
        snap = _absorb_snapshot()
        d = snap.to_dict()
        assert "snapshot_age_seconds" in d, "snapshot_age_seconds missing from to_dict()"

    def test_A02_snapshot_age_seconds_is_float(self):
        snap = _absorb_snapshot()
        d = snap.to_dict()
        assert isinstance(d["snapshot_age_seconds"], float)

    def test_A03_snapshot_age_seconds_non_negative(self):
        snap = _absorb_snapshot()
        d = snap.to_dict()
        assert d["snapshot_age_seconds"] >= 0.0

    def test_A04_to_dict_json_serialisable(self):
        snap = _absorb_snapshot()
        json.dumps(snap.to_dict())  # must not raise


# ===========================================================================
# B.  get_ecosystem_summary() includes freshness fields
# ===========================================================================


class TestEcosystemSummaryFreshnessFields:
    def test_B01_snapshot_truth_received_false_when_empty(self):
        from core.android_device_state_store import get_device_ecosystem_summary
        summary = get_device_ecosystem_summary()
        assert summary["snapshot_truth_received"] is False

    def test_B02_last_snapshot_absorbed_at_none_when_empty(self):
        from core.android_device_state_store import get_device_ecosystem_summary
        summary = get_device_ecosystem_summary()
        assert summary["last_snapshot_absorbed_at"] is None

    def test_B03_snapshot_freshness_seconds_none_when_empty(self):
        from core.android_device_state_store import get_device_ecosystem_summary
        summary = get_device_ecosystem_summary()
        assert summary["snapshot_freshness_seconds"] is None

    def test_B04_snapshot_truth_received_true_after_absorb(self):
        from core.android_device_state_store import get_device_ecosystem_summary
        _absorb_snapshot("dev_b04")
        summary = get_device_ecosystem_summary()
        assert summary["snapshot_truth_received"] is True

    def test_B05_last_snapshot_absorbed_at_populated_after_absorb(self):
        from core.android_device_state_store import get_device_ecosystem_summary
        before = time.time()
        _absorb_snapshot("dev_b05")
        after = time.time()
        summary = get_device_ecosystem_summary()
        ts = summary["last_snapshot_absorbed_at"]
        assert ts is not None
        assert before <= ts <= after + 0.1

    def test_B06_snapshot_freshness_seconds_non_negative_after_absorb(self):
        from core.android_device_state_store import get_device_ecosystem_summary
        _absorb_snapshot("dev_b06")
        summary = get_device_ecosystem_summary()
        assert summary["snapshot_freshness_seconds"] >= 0.0

    def test_B07_last_snapshot_absorbed_at_is_max_across_devices(self):
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            get_device_ecosystem_summary,
        )
        absorb_device_state_snapshot("dev_early", {"model_ready": True})
        time.sleep(0.01)
        absorb_device_state_snapshot("dev_late", {"model_ready": True})
        summary = get_device_ecosystem_summary()
        # The ecosystem summary must reflect the most recent snapshot
        from core.android_device_state_store import list_device_state_snapshots
        snapshots = list_device_state_snapshots()
        expected_max = max(s.absorbed_at for s in snapshots)
        assert summary["last_snapshot_absorbed_at"] == pytest.approx(expected_max, abs=0.001)

    def test_B08_ecosystem_summary_json_serialisable(self):
        from core.android_device_state_store import get_device_ecosystem_summary
        _absorb_snapshot("dev_b08")
        json.dumps(get_device_ecosystem_summary())  # must not raise


# ===========================================================================
# C.  OperatorSnapshot.android_ecosystem carries freshness keys
# ===========================================================================


class TestOperatorSnapshotAndroidEcosystemFreshness:
    def test_C01_android_ecosystem_empty_when_no_snapshots(self):
        from core.operator_surface import get_operator_surface
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        eco = snap.android_ecosystem
        # When no devices have sent snapshots, snapshot_truth_received should be False
        assert eco.get("snapshot_truth_received") is False

    def test_C02_android_ecosystem_snapshot_truth_received_after_absorb(self):
        from core.operator_surface import get_operator_surface
        _absorb_snapshot("dev_c02")
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        eco = snap.android_ecosystem
        assert eco.get("snapshot_truth_received") is True

    def test_C03_android_ecosystem_last_snapshot_absorbed_at_populated(self):
        from core.operator_surface import get_operator_surface
        before = time.time()
        _absorb_snapshot("dev_c03")
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        eco = snap.android_ecosystem
        ts = eco.get("last_snapshot_absorbed_at")
        assert ts is not None
        assert ts >= before

    def test_C04_android_ecosystem_snapshot_freshness_seconds_populated(self):
        from core.operator_surface import get_operator_surface
        _absorb_snapshot("dev_c04")
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        eco = snap.android_ecosystem
        assert eco.get("snapshot_freshness_seconds") is not None
        assert eco["snapshot_freshness_seconds"] >= 0.0

    def test_C05_operator_snapshot_to_dict_json_serialisable(self):
        from core.operator_surface import get_operator_surface
        _absorb_snapshot("dev_c05")
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        json.dumps(snap.to_dict())  # must not raise


# ===========================================================================
# D.  ANDROID_ECOSYSTEM_SNAPSHOT_KEYS includes the three new freshness keys
# ===========================================================================


class TestAndroidEcosystemSnapshotKeys:
    def test_D01_snapshot_truth_received_in_whitelist(self):
        from core.operator_surface import ANDROID_ECOSYSTEM_SNAPSHOT_KEYS
        assert "snapshot_truth_received" in ANDROID_ECOSYSTEM_SNAPSHOT_KEYS

    def test_D02_last_snapshot_absorbed_at_in_whitelist(self):
        from core.operator_surface import ANDROID_ECOSYSTEM_SNAPSHOT_KEYS
        assert "last_snapshot_absorbed_at" in ANDROID_ECOSYSTEM_SNAPSHOT_KEYS

    def test_D03_snapshot_freshness_seconds_in_whitelist(self):
        from core.operator_surface import ANDROID_ECOSYSTEM_SNAPSHOT_KEYS
        assert "snapshot_freshness_seconds" in ANDROID_ECOSYSTEM_SNAPSHOT_KEYS

    def test_D04_legacy_count_keys_still_present(self):
        from core.operator_surface import ANDROID_ECOSYSTEM_SNAPSHOT_KEYS
        for key in (
            "total_devices_with_snapshot",
            "local_ai_ready_count",
            "model_ready_count",
            "accessibility_ready_count",
            "overlay_ready_count",
            "local_loop_ready_count",
            "pending_first_download_count",
        ):
            assert key in ANDROID_ECOSYSTEM_SNAPSHOT_KEYS, f"{key!r} missing from whitelist"


# ===========================================================================
# E.  FlowOperatorProjection.to_dict() includes last_event_absorbed_at
# ===========================================================================


class TestFlowProjectionLastEventAbsorbedAt:
    def test_E01_last_event_absorbed_at_in_to_dict(self):
        from core.flow_level_operator_surface import FlowOperatorProjection
        proj = FlowOperatorProjection(flow_id="f_e01")
        d = proj.to_dict()
        assert "last_event_absorbed_at" in d, "last_event_absorbed_at missing from to_dict()"

    def test_E02_last_event_absorbed_at_defaults_to_none(self):
        from core.flow_level_operator_surface import FlowOperatorProjection
        proj = FlowOperatorProjection(flow_id="f_e02")
        assert proj.last_event_absorbed_at is None
        assert proj.to_dict()["last_event_absorbed_at"] is None

    def test_E03_last_event_absorbed_at_float_when_set(self):
        from core.flow_level_operator_surface import FlowOperatorProjection
        ts = time.time()
        proj = FlowOperatorProjection(flow_id="f_e03", last_event_absorbed_at=ts)
        assert proj.to_dict()["last_event_absorbed_at"] == ts

    def test_E04_to_dict_json_serialisable_with_absorbed_at(self):
        from core.flow_level_operator_surface import FlowOperatorProjection
        proj = FlowOperatorProjection(flow_id="f_e04", last_event_absorbed_at=time.time())
        json.dumps(proj.to_dict())  # must not raise


# ===========================================================================
# F.  inspect_flow() populates last_event_absorbed_at from entity metadata
# ===========================================================================


class TestInspectFlowLastEventAbsorbedAt:
    def test_F01_last_event_absorbed_at_none_when_no_events_absorbed(self):
        from core.flow_level_operator_surface import get_flow_level_operator_surface
        entity = _register_flow()
        fid = entity.identity.delegated_flow_id
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(fid)
        assert proj is not None
        assert proj.last_event_absorbed_at is None

    def test_F02_last_event_absorbed_at_populated_after_event_absorbed(self):
        from core.android_device_state_store import absorb_device_execution_event
        from core.flow_level_operator_surface import get_flow_level_operator_surface
        entity = _register_flow()
        fid = entity.identity.delegated_flow_id
        before = time.time()
        absorb_device_execution_event("dev_f02", {
            "flow_id": fid,
            "task_id": "task_f02",
            "phase": "execution",
            "step_index": 2,
        })
        after = time.time()
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(fid)
        assert proj is not None
        ts = proj.last_event_absorbed_at
        assert ts is not None, "last_event_absorbed_at should be populated after event absorbed"
        assert before <= ts <= after + 0.1

    def test_F03_inspect_flow_projection_json_serialisable_after_event(self):
        from core.android_device_state_store import absorb_device_execution_event
        from core.flow_level_operator_surface import get_flow_level_operator_surface
        entity = _register_flow()
        fid = entity.identity.delegated_flow_id
        absorb_device_execution_event("dev_f03", {
            "flow_id": fid,
            "task_id": "task_f03",
            "phase": "planning",
        })
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(fid)
        assert proj is not None
        json.dumps(proj.to_dict())  # must not raise


# ===========================================================================
# G.  snapshot_truth_received is False when store is empty
# ===========================================================================


class TestSnapshotTruthReceivedEmpty:
    def test_G01_truth_received_false_on_empty_store(self):
        from core.android_device_state_store import get_device_ecosystem_summary
        summary = get_device_ecosystem_summary()
        assert summary["snapshot_truth_received"] is False

    def test_G02_operator_snapshot_truth_received_false_on_empty_store(self):
        from core.operator_surface import get_operator_surface
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        assert snap.android_ecosystem.get("snapshot_truth_received") is False


# ===========================================================================
# H.  snapshot_age_seconds is non-negative
# ===========================================================================


class TestSnapshotAgeNonNegative:
    def test_H01_snapshot_age_non_negative_immediately(self):
        snap = _absorb_snapshot("dev_h01")
        d = snap.to_dict()
        assert d["snapshot_age_seconds"] >= 0.0

    def test_H02_snapshot_age_increases_over_time(self):
        snap = _absorb_snapshot("dev_h02")
        age1 = snap.to_dict()["snapshot_age_seconds"]
        time.sleep(0.05)
        age2 = snap.to_dict()["snapshot_age_seconds"]
        assert age2 >= age1


# ===========================================================================
# I.  snapshot_freshness_seconds is non-negative when devices exist
# ===========================================================================


class TestSnapshotFreshnessNonNegative:
    def test_I01_freshness_non_negative_after_absorb(self):
        from core.android_device_state_store import get_device_ecosystem_summary
        _absorb_snapshot("dev_i01")
        summary = get_device_ecosystem_summary()
        assert summary["snapshot_freshness_seconds"] >= 0.0

    def test_I02_freshness_reflects_recency(self):
        from core.android_device_state_store import get_device_ecosystem_summary
        _absorb_snapshot("dev_i02")
        time.sleep(0.05)
        summary = get_device_ecosystem_summary()
        assert summary["snapshot_freshness_seconds"] >= 0.05 - 0.01  # small tolerance


# ===========================================================================
# J.  last_event_absorbed_at is None when no execution event has been absorbed
# ===========================================================================


class TestLastEventAbsorbedAtWhenNoEvents:
    def test_J01_none_when_no_events_for_flow(self):
        from core.flow_level_operator_surface import get_flow_level_operator_surface
        entity = _register_flow()
        fid = entity.identity.delegated_flow_id
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(fid)
        assert proj is not None
        assert proj.last_event_absorbed_at is None

    def test_J02_dict_contains_none_value(self):
        from core.flow_level_operator_surface import get_flow_level_operator_surface
        entity = _register_flow()
        fid = entity.identity.delegated_flow_id
        surface = get_flow_level_operator_surface()
        proj = surface.inspect_flow(fid)
        assert proj is not None
        d = proj.to_dict()
        assert "last_event_absorbed_at" in d
        assert d["last_event_absorbed_at"] is None
