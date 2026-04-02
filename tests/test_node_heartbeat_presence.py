#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_node_heartbeat_presence.py
======================================
PR-7: Capability & Node Assimilation — tests for node heartbeat and
fabric presence tracking.

Coverage
--------
A) FabricPresence — heartbeat age tracking
   - heartbeat_age_secs() grows over time
   - heartbeat_age_secs() is near-zero immediately after construction
   - to_dict() heartbeat_age_secs is a float

B) Node registration → initial presence state
   - freshly assimilated node is ONLINE
   - freshly assimilated node heartbeat_count is 1
   - freshly assimilated node host is stored
   - freshly assimilated node port is stored

C) Heartbeat updates
   - heartbeat() increments heartbeat_count
   - heartbeat() updates last_heartbeat_at
   - multiple heartbeats accumulate count correctly
   - heartbeat on DEGRADED node restores ONLINE (when health_score >= 0.5)
   - heartbeat on OFFLINE node restores ONLINE

D) Degradation
   - health_score < 0.5 → presence DEGRADED
   - exactly 0.5 → presence ONLINE (boundary)
   - exactly 0.0 → presence DEGRADED

E) Offline transitions
   - mark_offline() → presence OFFLINE
   - mark_offline() with reason stores reason in event
   - OFFLINE node excluded from list_online_records()

F) Stale detection
   - mark_stale_if_expired(ttl=0) marks all ONLINE nodes STALE
   - mark_stale_if_expired does NOT affect OFFLINE nodes
   - stale nodes excluded from list_online_records()
   - heartbeat() on STALE node restores ONLINE

G) Rejoin / re-registration
   - assimilating an OFFLINE node sets presence ONLINE
   - assimilating an OFFLINE node emits 'rejoin' event
   - re-registration after STALE increments heartbeat_count

H) Observable event sequence
   - event log records 'registered' on first assimilation
   - event log records 'heartbeat' on heartbeat
   - event log records 'offline' on mark_offline
   - event log records 'rejoin' on re-assimilation after offline
   - event log is bounded (ring buffer)
   - event log entries have non-empty node_id

I) Multiple nodes — isolation
   - heartbeat on node A does not affect node B
   - mark_offline on node A does not affect node B
   - stale detection marks all expired nodes

J) Presence in snapshot
   - snapshot by_presence_state counts ONLINE correctly
   - snapshot by_presence_state counts OFFLINE correctly
   - snapshot total_nodes includes all nodes
"""

from __future__ import annotations

import time

import pytest

from core.capability_assimilation import (
    AssimilationPresenceState,
    FabricPresence,
    NodeParticipantKind,
    get_capability_assimilation_layer,
    reset_capability_assimilation_layer,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset():
    reset_capability_assimilation_layer()
    from core.network_graph_runtime import reset_network_graph_runtime
    reset_network_graph_runtime()
    yield
    reset_capability_assimilation_layer()


def _layer():
    return get_capability_assimilation_layer()


# ===========================================================================
# A) FabricPresence — heartbeat age tracking
# ===========================================================================


def test_a01_heartbeat_age_grows_over_time():
    fp = FabricPresence(node_id="n1")
    age1 = fp.heartbeat_age_secs()
    # Sleep a tiny bit to ensure monotonic clock advances
    time.sleep(0.01)
    age2 = fp.heartbeat_age_secs()
    assert age2 >= age1


def test_a02_heartbeat_age_near_zero_after_construction():
    fp = FabricPresence(node_id="n1")
    assert fp.heartbeat_age_secs() < 1.0  # should be much less than 1 second


def test_a03_to_dict_heartbeat_age_secs_is_float():
    fp = FabricPresence(node_id="n1")
    d = fp.to_dict()
    assert isinstance(d["heartbeat_age_secs"], float)


# ===========================================================================
# B) Node registration → initial presence state
# ===========================================================================


def test_b01_freshly_assimilated_node_is_online():
    layer = _layer()
    rec = layer.assimilate("fresh-1")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.ONLINE


def test_b02_freshly_assimilated_heartbeat_count_is_1():
    layer = _layer()
    rec = layer.assimilate("fresh-2")
    assert rec.fabric_presence.heartbeat_count == 1


def test_b03_freshly_assimilated_host_stored():
    layer = _layer()
    layer.assimilate("fresh-3", host="10.0.0.5")
    rec = layer.get_record("fresh-3")
    assert rec.fabric_presence.host == "10.0.0.5"


def test_b04_freshly_assimilated_port_stored():
    layer = _layer()
    layer.assimilate("fresh-4", port=9999)
    rec = layer.get_record("fresh-4")
    assert rec.fabric_presence.port == 9999


# ===========================================================================
# C) Heartbeat updates
# ===========================================================================


def test_c01_heartbeat_increments_count():
    layer = _layer()
    layer.assimilate("hb-1")
    layer.heartbeat("hb-1")
    rec = layer.get_record("hb-1")
    assert rec.fabric_presence.heartbeat_count == 2


def test_c02_heartbeat_updates_last_heartbeat_at():
    layer = _layer()
    layer.assimilate("hb-2")
    old_ts = layer.get_record("hb-2").fabric_presence.last_heartbeat_at
    time.sleep(0.01)
    layer.heartbeat("hb-2")
    new_ts = layer.get_record("hb-2").fabric_presence.last_heartbeat_at
    assert new_ts >= old_ts


def test_c03_multiple_heartbeats_accumulate():
    layer = _layer()
    layer.assimilate("hb-3")
    layer.heartbeat("hb-3")
    layer.heartbeat("hb-3")
    layer.heartbeat("hb-3")
    rec = layer.get_record("hb-3")
    assert rec.fabric_presence.heartbeat_count == 4


def test_c04_heartbeat_restores_online_from_degraded():
    layer = _layer()
    layer.assimilate("hb-4")
    layer.heartbeat("hb-4", health_score=0.1)  # → DEGRADED
    layer.heartbeat("hb-4", health_score=1.0)  # → ONLINE
    rec = layer.get_record("hb-4")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.ONLINE


def test_c05_heartbeat_restores_online_from_offline():
    layer = _layer()
    layer.assimilate("hb-5")
    layer.mark_offline("hb-5")
    layer.heartbeat("hb-5", health_score=1.0)
    rec = layer.get_record("hb-5")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.ONLINE


# ===========================================================================
# D) Degradation
# ===========================================================================


def test_d01_health_below_0_5_degrades():
    layer = _layer()
    layer.assimilate("deg-1")
    layer.heartbeat("deg-1", health_score=0.3)
    rec = layer.get_record("deg-1")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.DEGRADED


def test_d02_exactly_0_5_keeps_online():
    layer = _layer()
    layer.assimilate("deg-2")
    layer.heartbeat("deg-2", health_score=0.5)
    rec = layer.get_record("deg-2")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.ONLINE


def test_d03_exactly_0_degrades():
    layer = _layer()
    layer.assimilate("deg-3")
    layer.heartbeat("deg-3", health_score=0.0)
    rec = layer.get_record("deg-3")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.DEGRADED


# ===========================================================================
# E) Offline transitions
# ===========================================================================


def test_e01_mark_offline_sets_offline():
    layer = _layer()
    layer.assimilate("off-1")
    layer.mark_offline("off-1")
    rec = layer.get_record("off-1")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.OFFLINE


def test_e02_mark_offline_reason_in_event():
    layer = _layer()
    layer.assimilate("off-2")
    layer.mark_offline("off-2", reason="planned shutdown")
    events = [e for e in layer.get_event_log() if e.event_kind == "offline"]
    assert any("planned shutdown" in str(e.details) for e in events)


def test_e03_offline_node_excluded_from_online():
    layer = _layer()
    layer.assimilate("off-3")
    layer.mark_offline("off-3")
    online_ids = [r.node_id for r in layer.list_online_records()]
    assert "off-3" not in online_ids


# ===========================================================================
# F) Stale detection
# ===========================================================================


def test_f01_mark_stale_if_expired_ttl_zero():
    layer = _layer()
    layer.assimilate("stale-1")
    stale = layer.mark_stale_if_expired(heartbeat_ttl_secs=0.0)
    assert "stale-1" in stale


def test_f02_mark_stale_does_not_affect_offline():
    layer = _layer()
    layer.assimilate("stale-2")
    layer.mark_offline("stale-2")
    stale = layer.mark_stale_if_expired(heartbeat_ttl_secs=0.0)
    # OFFLINE node should NOT be re-transitioned to STALE
    assert "stale-2" not in stale


def test_f03_stale_node_excluded_from_online():
    layer = _layer()
    layer.assimilate("stale-3")
    layer.mark_stale_if_expired(heartbeat_ttl_secs=0.0)
    online_ids = [r.node_id for r in layer.list_online_records()]
    assert "stale-3" not in online_ids


def test_f04_heartbeat_on_stale_restores_online():
    layer = _layer()
    layer.assimilate("stale-4")
    layer.mark_stale_if_expired(heartbeat_ttl_secs=0.0)
    layer.heartbeat("stale-4", health_score=1.0)
    rec = layer.get_record("stale-4")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.ONLINE


# ===========================================================================
# G) Rejoin / re-registration
# ===========================================================================


def test_g01_re_assimilation_after_offline_sets_online():
    layer = _layer()
    layer.assimilate("rj-1")
    layer.mark_offline("rj-1")
    layer.assimilate("rj-1")
    rec = layer.get_record("rj-1")
    assert rec.fabric_presence.presence_state == AssimilationPresenceState.ONLINE


def test_g02_re_assimilation_after_offline_emits_rejoin():
    layer = _layer()
    layer.assimilate("rj-2")
    layer.mark_offline("rj-2")
    layer.assimilate("rj-2")
    events = [e for e in layer.get_event_log() if e.event_kind == "rejoin"]
    assert len(events) >= 1


def test_g03_re_registration_after_stale_increments_count():
    layer = _layer()
    layer.assimilate("rj-3")
    layer.mark_stale_if_expired(heartbeat_ttl_secs=0.0)
    layer.assimilate("rj-3")
    rec = layer.get_record("rj-3")
    assert rec.fabric_presence.heartbeat_count >= 2


# ===========================================================================
# H) Observable event sequence
# ===========================================================================


def test_h01_event_registered_on_first_assimilation():
    layer = _layer()
    layer.assimilate("ev-1")
    events = [e for e in layer.get_event_log() if e.event_kind == "registered"]
    assert any(e.node_id == "ev-1" for e in events)


def test_h02_event_heartbeat_on_heartbeat():
    layer = _layer()
    layer.assimilate("ev-2")
    layer.heartbeat("ev-2")
    events = [e for e in layer.get_event_log() if e.event_kind == "heartbeat"]
    assert any(e.node_id == "ev-2" for e in events)


def test_h03_event_offline_on_mark_offline():
    layer = _layer()
    layer.assimilate("ev-3")
    layer.mark_offline("ev-3")
    events = [e for e in layer.get_event_log() if e.event_kind == "offline"]
    assert any(e.node_id == "ev-3" for e in events)


def test_h04_event_rejoin_after_offline():
    layer = _layer()
    layer.assimilate("ev-4")
    layer.mark_offline("ev-4")
    layer.assimilate("ev-4")
    events = [e for e in layer.get_event_log() if e.event_kind == "rejoin"]
    assert any(e.node_id == "ev-4" for e in events)


def test_h05_event_log_is_bounded():
    layer = _layer()
    # Emit many events
    for i in range(300):
        layer.assimilate(f"flood-{i}")
    assert len(layer.get_event_log()) <= 256


def test_h06_event_entries_have_non_empty_node_id():
    layer = _layer()
    layer.assimilate("ev-6")
    for event in layer.get_event_log():
        assert event.node_id


# ===========================================================================
# I) Multiple nodes — isolation
# ===========================================================================


def test_i01_heartbeat_on_a_does_not_affect_b():
    layer = _layer()
    layer.assimilate("iso-a")
    layer.assimilate("iso-b")
    layer.heartbeat("iso-a", health_score=0.1)  # → A degraded
    rec_b = layer.get_record("iso-b")
    assert rec_b.fabric_presence.presence_state == AssimilationPresenceState.ONLINE


def test_i02_offline_on_a_does_not_affect_b():
    layer = _layer()
    layer.assimilate("iso-c")
    layer.assimilate("iso-d")
    layer.mark_offline("iso-c")
    rec_d = layer.get_record("iso-d")
    assert rec_d.fabric_presence.presence_state == AssimilationPresenceState.ONLINE


def test_i03_stale_detection_marks_all_expired():
    layer = _layer()
    layer.assimilate("stale-x")
    layer.assimilate("stale-y")
    stale = layer.mark_stale_if_expired(heartbeat_ttl_secs=0.0)
    assert "stale-x" in stale
    assert "stale-y" in stale


# ===========================================================================
# J) Presence in snapshot
# ===========================================================================


def test_j01_snapshot_counts_online_correctly():
    layer = _layer()
    layer.assimilate("snap-on1")
    layer.assimilate("snap-on2")
    snap = layer.snapshot()
    assert snap["by_presence_state"].get("online", 0) >= 2


def test_j02_snapshot_counts_offline_correctly():
    layer = _layer()
    layer.assimilate("snap-off1")
    layer.mark_offline("snap-off1")
    snap = layer.snapshot()
    assert snap["by_presence_state"].get("offline", 0) >= 1


def test_j03_snapshot_total_nodes_includes_all():
    layer = _layer()
    layer.assimilate("snap-t1")
    layer.assimilate("snap-t2")
    layer.assimilate("snap-t3")
    snap = layer.snapshot()
    assert snap["total_nodes"] >= 3
