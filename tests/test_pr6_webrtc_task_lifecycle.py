"""tests/test_pr6_webrtc_task_lifecycle.py
=========================================
PR-6: WebRTC Task-Lifecycle Integration — focused test suite.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — WebRTCTransportState enum: all values present, from_string(), is_terminal(),
     is_usable() properties.
C  — WebRTCTaskLifecycleAction enum: all values present.
D  — WebRTCTaskBinding: construction, defaults, to_dict(), from_dict(), to_json(),
     is_active property.
E  — WebRTCTaskBindingSnapshot: construction, to_dict(), to_json().
F  — WebRTCTaskSessionRegistry: push, replace_latest_for_task,
     get_latest_for_task, list_all, list_active, size, capacity, clear.
G  — bind_webrtc_session_to_task: creates binding, stores in registry.
H  — bind_webrtc_session_to_task: re-binding same task_id replaces record.
I  — classify_transport_lifecycle_action: connected → continue_running.
J  — classify_transport_lifecycle_action: reconnecting → degrade.
K  — classify_transport_lifecycle_action: degraded → degrade.
L  — classify_transport_lifecycle_action: failed → terminate_failed.
M  — classify_transport_lifecycle_action: closed → terminate_cancelled.
N  — classify_transport_lifecycle_action: unknown → no_change.
O  — classify_transport_lifecycle_action: terminal task → no_change.
P  — classify_transport_lifecycle_action: connected + degraded task → recover.
Q  — apply_transport_state_to_task_lifecycle: updates binding transport_state.
R  — apply_transport_state_to_task_lifecycle: does not mutate original binding.
S  — apply_transport_state_to_task_lifecycle: last_transition_at updated.
T  — apply_transport_state_to_task_lifecycle: with runtime advances task.
U  — teardown_binding_on_task_terminal: marks binding as torn_down.
V  — teardown_binding_on_task_terminal: idempotent — second call returns False.
W  — teardown_binding_on_task_terminal: no binding returns False (idempotent).
X  — teardown_binding_on_task_terminal: sets transport_state to closed.
Y  — teardown_binding_on_task_terminal: sets torn_down_at timestamp.
Z  — get_webrtc_task_binding: returns latest binding for task_id.
AA — get_webrtc_task_binding: returns None for unknown task_id.
AB — list_active_webrtc_task_bindings: excludes torn-down bindings.
AC — list_active_webrtc_task_bindings: empty when no active bindings.
AD — build_webrtc_task_binding_snapshot: counts match.
AE — build_webrtc_task_binding_snapshot: includes policy sentinels.
AF — build_webrtc_task_binding_snapshot: empty registry → zero counts.
AG — core.runtime re-exports: all PR-6 symbols accessible from core.runtime.
AH — WebRTCTransportState.from_string: unknown string → unknown.
AI — WebRTCTaskBinding.from_dict: malformed transport_state → safe default.
AJ — WebRTCTaskBinding.from_dict: non-dict raises ValueError.
AK — Ring buffer capacity: 128 default.
AL — Multiple tasks: each gets its own binding.
AM — Snapshot to_dict contains expected keys.
AN — WebRTCTaskBinding is_active: torn_down → False.
AO — WebRTCTaskBinding is_active: failed transport → False.
AP — apply_transport_state_to_task_lifecycle with string transport state.
AQ — Full lifecycle: bind → degrade → recover → teardown.
AR — classify_transport_lifecycle_action: string transport state input.
AS — reset_webrtc_task_session_registry: clears singleton.
AT — get_webrtc_task_session_registry: returns same singleton.
AU — Two separate tasks: list_active returns both when both active.
AV — apply_transport_state_to_task_lifecycle: failed transport marks is_active False.
AW — Snapshot snapshotted_at is recent timestamp.
AX — All 11 policy sentinels are non-empty strings.
AY — Snapshot records are newest-first.
AZ — WebRTC session manager config accepts task_id and device_id fields.
"""

from __future__ import annotations

import json
import time
import uuid

import pytest

from core.webrtc_task_lifecycle import (
    # Sentinels
    WEBRTC_TASK_LIFECYCLE_AUTHORITY,
    WEBRTC_SESSION_MUST_BE_TASK_SCOPED_POLICY,
    TRANSPORT_STATE_DRIVES_LIFECYCLE_ACTION_POLICY,
    TERMINAL_TASK_TRIGGERS_SESSION_TEARDOWN_POLICY,
    DEGRADED_TRANSPORT_YIELDS_DEGRADED_TASK_POLICY,
    FAILED_TRANSPORT_YIELDS_FAILED_TASK_POLICY,
    RECONNECTED_TRANSPORT_RESUMES_RUNNING_TASK_POLICY,
    BINDING_IS_TASK_SCOPED_SINGLE_SESSION_POLICY,
    TEARDOWN_IS_IDEMPOTENT_POLICY,
    SESSION_BINDING_RECORD_IS_IMMUTABLE_POLICY,
    WEBRTC_TASK_LIFECYCLE_PR6_SENTINEL,
    # Enums
    WebRTCTransportState,
    WebRTCTaskLifecycleAction,
    # Dataclasses
    WebRTCTaskBinding,
    WebRTCTaskBindingSnapshot,
    # Class
    WebRTCTaskSessionRegistry,
    # Functions
    bind_webrtc_session_to_task,
    classify_transport_lifecycle_action,
    apply_transport_state_to_task_lifecycle,
    teardown_binding_on_task_terminal,
    get_webrtc_task_binding,
    list_active_webrtc_task_bindings,
    build_webrtc_task_binding_snapshot,
    get_webrtc_task_session_registry,
    reset_webrtc_task_session_registry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_registry() -> WebRTCTaskSessionRegistry:
    """Return a fresh, isolated registry (not the module singleton)."""
    return WebRTCTaskSessionRegistry(capacity=128)


def _new_task_id() -> str:
    return f"task_{uuid.uuid4().hex[:12]}"


def _new_session_id() -> str:
    return f"sess_{uuid.uuid4().hex[:12]}"


def _bind(task_id: str = None, session_id: str = None, device_id: str = "dev-1", **kw) -> WebRTCTaskBinding:
    reg = kw.pop("registry", _fresh_registry())
    return bind_webrtc_session_to_task(
        task_id or _new_task_id(),
        session_id or _new_session_id(),
        device_id,
        registry=reg,
        **kw,
    )


# ---------------------------------------------------------------------------
# Group A — Sentinel presence and correctness
# ---------------------------------------------------------------------------

def test_a1_authority_sentinel_non_empty():
    assert isinstance(WEBRTC_TASK_LIFECYCLE_AUTHORITY, str)
    assert len(WEBRTC_TASK_LIFECYCLE_AUTHORITY) > 0


def test_a2_pr6_sentinel_non_empty():
    assert isinstance(WEBRTC_TASK_LIFECYCLE_PR6_SENTINEL, str)
    assert "pr6" in WEBRTC_TASK_LIFECYCLE_PR6_SENTINEL.lower()


def test_a3_session_scoped_policy():
    assert "POLICY" in WEBRTC_SESSION_MUST_BE_TASK_SCOPED_POLICY


def test_a4_transport_drives_lifecycle_policy():
    assert "POLICY" in TRANSPORT_STATE_DRIVES_LIFECYCLE_ACTION_POLICY


def test_a5_terminal_teardown_policy():
    assert "POLICY" in TERMINAL_TASK_TRIGGERS_SESSION_TEARDOWN_POLICY


def test_a6_degraded_transport_policy():
    assert "POLICY" in DEGRADED_TRANSPORT_YIELDS_DEGRADED_TASK_POLICY


def test_a7_failed_transport_policy():
    assert "POLICY" in FAILED_TRANSPORT_YIELDS_FAILED_TASK_POLICY


def test_a8_reconnected_resumes_policy():
    assert "POLICY" in RECONNECTED_TRANSPORT_RESUMES_RUNNING_TASK_POLICY


def test_a9_binding_task_scoped_policy():
    assert "POLICY" in BINDING_IS_TASK_SCOPED_SINGLE_SESSION_POLICY


def test_a10_teardown_idempotent_policy():
    assert "POLICY" in TEARDOWN_IS_IDEMPOTENT_POLICY


def test_a11_record_immutable_policy():
    assert "POLICY" in SESSION_BINDING_RECORD_IS_IMMUTABLE_POLICY


# ---------------------------------------------------------------------------
# Group B — WebRTCTransportState enum
# ---------------------------------------------------------------------------

def test_b1_all_transport_states_present():
    states = {s.value for s in WebRTCTransportState}
    assert states == {"connected", "reconnecting", "degraded", "failed", "closed", "unknown"}


def test_b2_from_string_connected():
    assert WebRTCTransportState.from_string("connected") == WebRTCTransportState.connected


def test_b3_from_string_unknown_string_returns_unknown():
    assert WebRTCTransportState.from_string("totally_invalid") == WebRTCTransportState.unknown


def test_b4_from_string_with_explicit_default():
    result = WebRTCTransportState.from_string("bad", default=WebRTCTransportState.failed)
    assert result == WebRTCTransportState.failed


def test_b5_is_terminal_failed():
    assert WebRTCTransportState.failed.is_terminal is True


def test_b6_is_terminal_closed():
    assert WebRTCTransportState.closed.is_terminal is True


def test_b7_is_terminal_connected_false():
    assert WebRTCTransportState.connected.is_terminal is False


def test_b8_is_usable_connected():
    assert WebRTCTransportState.connected.is_usable is True


def test_b9_is_usable_degraded():
    assert WebRTCTransportState.degraded.is_usable is True


def test_b10_is_usable_failed_false():
    assert WebRTCTransportState.failed.is_usable is False


def test_b11_is_usable_closed_false():
    assert WebRTCTransportState.closed.is_usable is False


def test_b12_is_usable_reconnecting_false():
    assert WebRTCTransportState.reconnecting.is_usable is False


# ---------------------------------------------------------------------------
# Group C — WebRTCTaskLifecycleAction enum
# ---------------------------------------------------------------------------

def test_c1_all_actions_present():
    actions = {a.value for a in WebRTCTaskLifecycleAction}
    assert actions == {
        "continue_running",
        "degrade",
        "recover",
        "terminate_failed",
        "terminate_cancelled",
        "no_change",
    }


# ---------------------------------------------------------------------------
# Group D — WebRTCTaskBinding dataclass
# ---------------------------------------------------------------------------

def test_d1_binding_default_construction():
    b = WebRTCTaskBinding()
    assert b.task_id == ""
    assert b.webrtc_session_id == ""
    assert b.device_id == ""
    assert b.transport_state == WebRTCTransportState.unknown
    assert b.task_lifecycle == "created"
    assert b.is_torn_down is False
    assert b.torn_down_at is None
    assert isinstance(b.binding_id, str) and len(b.binding_id) > 0


def test_d2_binding_to_dict_contains_expected_keys():
    b = WebRTCTaskBinding(task_id="t1", webrtc_session_id="s1", device_id="d1")
    d = b.to_dict()
    assert "binding_id" in d
    assert d["task_id"] == "t1"
    assert d["webrtc_session_id"] == "s1"
    assert d["device_id"] == "d1"
    assert d["transport_state"] == "unknown"
    assert d["is_torn_down"] is False


def test_d3_binding_from_dict_round_trip():
    b = WebRTCTaskBinding(
        task_id="t2",
        webrtc_session_id="s2",
        device_id="d2",
        transport_state=WebRTCTransportState.connected,
        task_lifecycle="running",
    )
    d = b.to_dict()
    b2 = WebRTCTaskBinding.from_dict(d)
    assert b2.task_id == "t2"
    assert b2.webrtc_session_id == "s2"
    assert b2.transport_state == WebRTCTransportState.connected
    assert b2.task_lifecycle == "running"
    assert b2.binding_id == b.binding_id


def test_d4_binding_to_json_valid_json():
    b = WebRTCTaskBinding(task_id="t3")
    j = b.to_json()
    parsed = json.loads(j)
    assert parsed["task_id"] == "t3"


def test_d5_binding_is_active_true_when_not_torn_down():
    b = WebRTCTaskBinding(transport_state=WebRTCTransportState.connected, is_torn_down=False)
    assert b.is_active is True


def test_d6_binding_is_active_false_when_torn_down():
    b = WebRTCTaskBinding(is_torn_down=True)
    assert b.is_active is False


def test_d7_binding_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        WebRTCTaskBinding.from_dict("not_a_dict")


def test_d8_binding_from_dict_malformed_transport_state_defaults():
    b = WebRTCTaskBinding.from_dict({"transport_state": "INVALID_STATE"})
    assert b.transport_state == WebRTCTransportState.unknown


# ---------------------------------------------------------------------------
# Group E — WebRTCTaskBindingSnapshot
# ---------------------------------------------------------------------------

def test_e1_snapshot_defaults():
    s = WebRTCTaskBindingSnapshot()
    assert s.total_bindings == 0
    assert s.active_bindings == 0
    assert s.torn_down_bindings == 0
    assert isinstance(s.snapshot_id, str) and len(s.snapshot_id) > 0


def test_e2_snapshot_to_dict_keys():
    s = WebRTCTaskBindingSnapshot()
    d = s.to_dict()
    assert "total_bindings" in d
    assert "active_bindings" in d
    assert "torn_down_bindings" in d
    assert "bindings_by_transport_state" in d
    assert "records" in d
    assert "policy_sentinels" in d
    assert "snapshotted_at" in d


def test_e3_snapshot_to_json_valid_json():
    s = WebRTCTaskBindingSnapshot(total_bindings=1)
    j = s.to_json()
    parsed = json.loads(j)
    assert parsed["total_bindings"] == 1


# ---------------------------------------------------------------------------
# Group F — WebRTCTaskSessionRegistry
# ---------------------------------------------------------------------------

def test_f1_push_increases_size():
    reg = _fresh_registry()
    reg.push(WebRTCTaskBinding(task_id="t1"))
    assert reg.size() == 1


def test_f2_get_latest_for_task_returns_most_recent():
    reg = _fresh_registry()
    b1 = WebRTCTaskBinding(task_id="t1", webrtc_session_id="s1")
    b2 = WebRTCTaskBinding(task_id="t1", webrtc_session_id="s2")
    reg.push(b1)
    reg.push(b2)
    result = reg.get_latest_for_task("t1")
    assert result.webrtc_session_id == "s2"


def test_f3_get_latest_for_task_unknown_returns_none():
    reg = _fresh_registry()
    assert reg.get_latest_for_task("unknown_task") is None


def test_f4_list_all_returns_all_entries():
    reg = _fresh_registry()
    reg.push(WebRTCTaskBinding(task_id="t1"))
    reg.push(WebRTCTaskBinding(task_id="t2"))
    assert len(reg.list_all()) == 2


def test_f5_list_active_excludes_torn_down():
    reg = _fresh_registry()
    b1 = WebRTCTaskBinding(task_id="t1", transport_state=WebRTCTransportState.connected, is_torn_down=False)
    b2 = WebRTCTaskBinding(task_id="t2", transport_state=WebRTCTransportState.connected, is_torn_down=True)
    reg.push(b1)
    reg.push(b2)
    active = reg.list_active()
    assert len(active) == 1
    assert active[0].task_id == "t1"


def test_f6_clear_empties_registry():
    reg = _fresh_registry()
    reg.push(WebRTCTaskBinding(task_id="t1"))
    reg.clear()
    assert reg.size() == 0


def test_f7_replace_latest_for_task_updates_record():
    reg = _fresh_registry()
    b1 = WebRTCTaskBinding(task_id="t1", transport_state=WebRTCTransportState.connected)
    reg.replace_latest_for_task(b1)
    b2 = WebRTCTaskBinding(task_id="t1", transport_state=WebRTCTransportState.degraded)
    reg.replace_latest_for_task(b2)
    result = reg.get_latest_for_task("t1")
    assert result.transport_state == WebRTCTransportState.degraded
    # replace should not increase size if task_id already present
    assert reg.size() == 1


def test_f8_capacity_default():
    reg = _fresh_registry()
    assert reg.capacity() == 128


def test_f9_replace_latest_for_task_appends_if_not_present():
    reg = _fresh_registry()
    b = WebRTCTaskBinding(task_id="new_task")
    reg.replace_latest_for_task(b)
    assert reg.size() == 1
    assert reg.get_latest_for_task("new_task") is not None


# ---------------------------------------------------------------------------
# Group G-H — bind_webrtc_session_to_task
# ---------------------------------------------------------------------------

def test_g1_bind_creates_binding():
    reg = _fresh_registry()
    b = bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    assert b.task_id == "t1"
    assert b.webrtc_session_id == "s1"
    assert b.device_id == "d1"
    assert b.is_torn_down is False


def test_g2_bind_stores_in_registry():
    reg = _fresh_registry()
    bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    assert reg.get_latest_for_task("t1") is not None


def test_g3_bind_initial_transport_state_connected_by_default():
    reg = _fresh_registry()
    b = bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    assert b.transport_state == WebRTCTransportState.connected


def test_g4_bind_metadata_stored():
    reg = _fresh_registry()
    b = bind_webrtc_session_to_task("t1", "s1", "d1", metadata={"trace_id": "abc"}, registry=reg)
    assert b.metadata["trace_id"] == "abc"


def test_h1_rebind_same_task_replaces_binding():
    reg = _fresh_registry()
    bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    b2 = bind_webrtc_session_to_task("t1", "s2", "d1", registry=reg)
    result = reg.get_latest_for_task("t1")
    assert result.webrtc_session_id == "s2"
    assert reg.size() == 1  # replace, not append


# ---------------------------------------------------------------------------
# Group I-P — classify_transport_lifecycle_action
# ---------------------------------------------------------------------------

def test_i1_connected_non_terminal_task_returns_continue():
    action = classify_transport_lifecycle_action("running", WebRTCTransportState.connected)
    assert action == WebRTCTaskLifecycleAction.continue_running


def test_j1_reconnecting_returns_degrade():
    action = classify_transport_lifecycle_action("running", WebRTCTransportState.reconnecting)
    assert action == WebRTCTaskLifecycleAction.degrade


def test_k1_degraded_transport_returns_degrade():
    action = classify_transport_lifecycle_action("running", WebRTCTransportState.degraded)
    assert action == WebRTCTaskLifecycleAction.degrade


def test_l1_failed_transport_returns_terminate_failed():
    action = classify_transport_lifecycle_action("running", WebRTCTransportState.failed)
    assert action == WebRTCTaskLifecycleAction.terminate_failed


def test_m1_closed_transport_returns_terminate_cancelled():
    action = classify_transport_lifecycle_action("running", WebRTCTransportState.closed)
    assert action == WebRTCTaskLifecycleAction.terminate_cancelled


def test_n1_unknown_transport_returns_no_change():
    action = classify_transport_lifecycle_action("running", WebRTCTransportState.unknown)
    assert action == WebRTCTaskLifecycleAction.no_change


def test_o1_terminal_task_completed_returns_no_change():
    action = classify_transport_lifecycle_action("completed", WebRTCTransportState.failed)
    assert action == WebRTCTaskLifecycleAction.no_change


def test_o2_terminal_task_failed_returns_no_change():
    action = classify_transport_lifecycle_action("failed", WebRTCTransportState.reconnecting)
    assert action == WebRTCTaskLifecycleAction.no_change


def test_o3_terminal_task_cancelled_returns_no_change():
    action = classify_transport_lifecycle_action("cancelled", WebRTCTransportState.closed)
    assert action == WebRTCTaskLifecycleAction.no_change


def test_p1_connected_transport_degraded_task_returns_recover():
    action = classify_transport_lifecycle_action("degraded", WebRTCTransportState.connected)
    assert action == WebRTCTaskLifecycleAction.recover


# ---------------------------------------------------------------------------
# Group Q-T — apply_transport_state_to_task_lifecycle
# ---------------------------------------------------------------------------

def test_q1_apply_updates_transport_state():
    reg = _fresh_registry()
    b = bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    updated = apply_transport_state_to_task_lifecycle(b, WebRTCTransportState.degraded, registry=reg)
    assert updated.transport_state == WebRTCTransportState.degraded


def test_r1_apply_does_not_mutate_original():
    reg = _fresh_registry()
    b = bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    original_state = b.transport_state
    apply_transport_state_to_task_lifecycle(b, WebRTCTransportState.reconnecting, registry=reg)
    assert b.transport_state == original_state  # original unchanged


def test_s1_apply_updates_last_transition_at():
    reg = _fresh_registry()
    b = bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    old_ts = b.last_transition_at
    updated = apply_transport_state_to_task_lifecycle(b, WebRTCTransportState.degraded, registry=reg)
    assert updated.last_transition_at >= (old_ts or 0)


def test_t1_apply_with_runtime_advances_task_to_degraded():
    """When a runtime is provided, DEGRADED transport should advance the task lifecycle."""
    from core.canonical_task import (
        build_canonical_task,
        TaskLifecycle,
        get_canonical_task_runtime,
        reset_canonical_task_runtime,
    )
    reset_canonical_task_runtime()
    rt = get_canonical_task_runtime()

    task = build_canonical_task(goal="stream screen", requested_action="screen_capture")
    task.advance_lifecycle(TaskLifecycle.RUNNING)
    rt.register(task)

    reg = _fresh_registry()
    b = bind_webrtc_session_to_task(
        task.task_id, "s1", "d1",
        task_lifecycle="running",
        registry=reg,
    )
    updated = apply_transport_state_to_task_lifecycle(
        b, WebRTCTransportState.degraded, runtime=rt, registry=reg
    )
    # Task should now be DEGRADED
    stored = rt.get_by_task_id(task.task_id)
    assert stored.lifecycle == TaskLifecycle.DEGRADED
    assert updated.task_lifecycle == "degraded"

    reset_canonical_task_runtime()


def test_t2_apply_with_runtime_advances_task_to_failed():
    from core.canonical_task import (
        build_canonical_task,
        TaskLifecycle,
        get_canonical_task_runtime,
        reset_canonical_task_runtime,
    )
    reset_canonical_task_runtime()
    rt = get_canonical_task_runtime()

    task = build_canonical_task(goal="stream screen")
    task.advance_lifecycle(TaskLifecycle.RUNNING)
    rt.register(task)

    reg = _fresh_registry()
    b = bind_webrtc_session_to_task(task.task_id, "s1", "d1", task_lifecycle="running", registry=reg)
    apply_transport_state_to_task_lifecycle(b, WebRTCTransportState.failed, runtime=rt, registry=reg)

    stored = rt.get_by_task_id(task.task_id)
    assert stored.lifecycle == TaskLifecycle.FAILED

    reset_canonical_task_runtime()


# ---------------------------------------------------------------------------
# Group U-Y — teardown_binding_on_task_terminal
# ---------------------------------------------------------------------------

def test_u1_teardown_marks_binding_torn_down():
    reg = _fresh_registry()
    bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    result = teardown_binding_on_task_terminal("t1", "completed", registry=reg)
    assert result is True
    b = reg.get_latest_for_task("t1")
    assert b.is_torn_down is True


def test_v1_teardown_idempotent_second_call_returns_false():
    reg = _fresh_registry()
    bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    teardown_binding_on_task_terminal("t1", "completed", registry=reg)
    result = teardown_binding_on_task_terminal("t1", "completed", registry=reg)
    assert result is False


def test_w1_teardown_no_binding_returns_false():
    reg = _fresh_registry()
    result = teardown_binding_on_task_terminal("nonexistent_task", "completed", registry=reg)
    assert result is False


def test_x1_teardown_sets_transport_to_closed():
    reg = _fresh_registry()
    bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    teardown_binding_on_task_terminal("t1", "completed", registry=reg)
    b = reg.get_latest_for_task("t1")
    assert b.transport_state == WebRTCTransportState.closed


def test_y1_teardown_sets_torn_down_at():
    reg = _fresh_registry()
    before = time.time()
    bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    teardown_binding_on_task_terminal("t1", "completed", registry=reg)
    b = reg.get_latest_for_task("t1")
    assert b.torn_down_at is not None
    assert b.torn_down_at >= before


# ---------------------------------------------------------------------------
# Group Z-AA — get_webrtc_task_binding
# ---------------------------------------------------------------------------

def test_z1_get_binding_returns_latest():
    reg = _fresh_registry()
    bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    b = get_webrtc_task_binding("t1", registry=reg)
    assert b is not None
    assert b.task_id == "t1"


def test_aa1_get_binding_unknown_returns_none():
    reg = _fresh_registry()
    assert get_webrtc_task_binding("unknown", registry=reg) is None


# ---------------------------------------------------------------------------
# Group AB-AC — list_active_webrtc_task_bindings
# ---------------------------------------------------------------------------

def test_ab1_list_active_excludes_torn_down():
    reg = _fresh_registry()
    bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    bind_webrtc_session_to_task("t2", "s2", "d2", registry=reg)
    teardown_binding_on_task_terminal("t2", "completed", registry=reg)
    active = list_active_webrtc_task_bindings(registry=reg)
    task_ids = {b.task_id for b in active}
    assert "t1" in task_ids
    assert "t2" not in task_ids


def test_ac1_list_active_empty_when_no_bindings():
    reg = _fresh_registry()
    assert list_active_webrtc_task_bindings(registry=reg) == []


# ---------------------------------------------------------------------------
# Group AD-AF — build_webrtc_task_binding_snapshot
# ---------------------------------------------------------------------------

def test_ad1_snapshot_counts_match():
    reg = _fresh_registry()
    bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    bind_webrtc_session_to_task("t2", "s2", "d2", registry=reg)
    teardown_binding_on_task_terminal("t2", "completed", registry=reg)
    snap = build_webrtc_task_binding_snapshot(registry=reg)
    assert snap.total_bindings == 2
    assert snap.active_bindings == 1
    assert snap.torn_down_bindings == 1


def test_ae1_snapshot_includes_policy_sentinels():
    reg = _fresh_registry()
    snap = build_webrtc_task_binding_snapshot(registry=reg)
    assert "WEBRTC_TASK_LIFECYCLE_AUTHORITY" in snap.policy_sentinels
    assert "WEBRTC_TASK_LIFECYCLE_PR6_SENTINEL" in snap.policy_sentinels


def test_af1_empty_registry_snapshot_zero_counts():
    reg = _fresh_registry()
    snap = build_webrtc_task_binding_snapshot(registry=reg)
    assert snap.total_bindings == 0
    assert snap.active_bindings == 0


# ---------------------------------------------------------------------------
# Group AG — core.runtime re-exports
# ---------------------------------------------------------------------------

def test_ag1_core_runtime_exports_pr6_symbols():
    pytest.importorskip("pydantic", reason="pydantic required for core.runtime import")
    from core.runtime import (
        WEBRTC_TASK_LIFECYCLE_AUTHORITY,
        WEBRTC_TASK_LIFECYCLE_PR6_SENTINEL,
        WebRTCTransportState,
        WebRTCTaskLifecycleAction,
        WebRTCTaskBinding,
        WebRTCTaskBindingSnapshot,
        WebRTCTaskSessionRegistry,
        bind_webrtc_session_to_task,
        classify_transport_lifecycle_action,
        apply_transport_state_to_task_lifecycle,
        teardown_binding_on_task_terminal,
        get_webrtc_task_binding,
        list_active_webrtc_task_bindings,
        build_webrtc_task_binding_snapshot,
        get_webrtc_task_session_registry,
        reset_webrtc_task_session_registry,
    )
    assert WEBRTC_TASK_LIFECYCLE_AUTHORITY
    assert WEBRTC_TASK_LIFECYCLE_PR6_SENTINEL


# ---------------------------------------------------------------------------
# Group AH — from_string edge cases
# ---------------------------------------------------------------------------

def test_ah1_from_string_unknown():
    assert WebRTCTransportState.from_string("totally_invalid") == WebRTCTransportState.unknown


def test_ah2_from_string_reconnecting():
    assert WebRTCTransportState.from_string("reconnecting") == WebRTCTransportState.reconnecting


# ---------------------------------------------------------------------------
# Group AI-AJ — from_dict edge cases
# ---------------------------------------------------------------------------

def test_ai1_from_dict_malformed_transport_state():
    b = WebRTCTaskBinding.from_dict({"transport_state": "GARBAGE"})
    assert b.transport_state == WebRTCTransportState.unknown


def test_aj1_from_dict_non_dict_raises():
    with pytest.raises(ValueError):
        WebRTCTaskBinding.from_dict(["not", "a", "dict"])


# ---------------------------------------------------------------------------
# Group AK — Ring buffer capacity
# ---------------------------------------------------------------------------

def test_ak1_default_capacity_is_128():
    reg = _fresh_registry()
    assert reg.capacity() == 128


# ---------------------------------------------------------------------------
# Group AL-AU — Additional integration / multi-task scenarios
# ---------------------------------------------------------------------------

def test_al1_multiple_tasks_independent_bindings():
    reg = _fresh_registry()
    bind_webrtc_session_to_task("task_a", "sess_a", "dev_1", registry=reg)
    bind_webrtc_session_to_task("task_b", "sess_b", "dev_2", registry=reg)
    a = reg.get_latest_for_task("task_a")
    b = reg.get_latest_for_task("task_b")
    assert a.webrtc_session_id == "sess_a"
    assert b.webrtc_session_id == "sess_b"


def test_am1_snapshot_to_dict_has_required_keys():
    reg = _fresh_registry()
    snap = build_webrtc_task_binding_snapshot(registry=reg)
    d = snap.to_dict()
    required = {
        "total_bindings", "active_bindings", "torn_down_bindings",
        "bindings_by_transport_state", "records", "snapshot_id",
        "snapshotted_at", "policy_sentinels",
    }
    assert required <= set(d.keys())


def test_an1_is_active_false_when_torn_down():
    b = WebRTCTaskBinding(is_torn_down=True, transport_state=WebRTCTransportState.connected)
    assert b.is_active is False


def test_ao1_is_active_false_when_failed_transport():
    b = WebRTCTaskBinding(transport_state=WebRTCTransportState.failed, is_torn_down=False)
    assert b.is_active is False


def test_ap1_apply_with_string_transport_state():
    reg = _fresh_registry()
    b = bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    updated = apply_transport_state_to_task_lifecycle(b, "degraded", registry=reg)
    assert updated.transport_state == WebRTCTransportState.degraded


def test_aq1_full_lifecycle_bind_degrade_recover_teardown():
    """End-to-end: bind → degrade → recover → teardown."""
    reg = _fresh_registry()

    # 1. Bind
    b = bind_webrtc_session_to_task("t1", "s1", "d1", task_lifecycle="running", registry=reg)
    assert b.is_active is True

    # 2. Transport degrades
    b = apply_transport_state_to_task_lifecycle(b, WebRTCTransportState.degraded, registry=reg)
    assert b.transport_state == WebRTCTransportState.degraded

    # 3. Transport reconnects (recovers)
    b = apply_transport_state_to_task_lifecycle(b, WebRTCTransportState.connected, registry=reg)
    assert b.transport_state == WebRTCTransportState.connected

    # 4. Task completes → teardown
    result = teardown_binding_on_task_terminal("t1", "completed", registry=reg)
    assert result is True
    final = reg.get_latest_for_task("t1")
    assert final.is_torn_down is True
    assert final.transport_state == WebRTCTransportState.closed


def test_ar1_classify_with_string_transport_state():
    action = classify_transport_lifecycle_action("running", "failed")
    assert action == WebRTCTaskLifecycleAction.terminate_failed


def test_as1_reset_clears_singleton():
    reset_webrtc_task_session_registry()
    reg1 = get_webrtc_task_session_registry()
    reg1.push(WebRTCTaskBinding(task_id="t1"))
    reset_webrtc_task_session_registry()
    reg2 = get_webrtc_task_session_registry()
    assert reg2.size() == 0
    reset_webrtc_task_session_registry()


def test_at1_get_registry_returns_same_singleton():
    reset_webrtc_task_session_registry()
    r1 = get_webrtc_task_session_registry()
    r2 = get_webrtc_task_session_registry()
    assert r1 is r2
    reset_webrtc_task_session_registry()


def test_au1_two_tasks_both_active_in_list_active():
    reg = _fresh_registry()
    bind_webrtc_session_to_task("ta", "sa", "da", registry=reg)
    bind_webrtc_session_to_task("tb", "sb", "db", registry=reg)
    active = list_active_webrtc_task_bindings(registry=reg)
    task_ids = {b.task_id for b in active}
    assert "ta" in task_ids
    assert "tb" in task_ids


def test_av1_apply_failed_transport_binding_becomes_inactive():
    reg = _fresh_registry()
    b = bind_webrtc_session_to_task("t1", "s1", "d1", registry=reg)
    updated = apply_transport_state_to_task_lifecycle(b, WebRTCTransportState.failed, registry=reg)
    assert updated.is_active is False


def test_aw1_snapshot_snapshotted_at_is_recent():
    reg = _fresh_registry()
    before = time.time()
    snap = build_webrtc_task_binding_snapshot(registry=reg)
    assert snap.snapshotted_at >= before


def test_ax1_all_policy_sentinels_non_empty():
    policies = [
        WEBRTC_TASK_LIFECYCLE_AUTHORITY,
        WEBRTC_SESSION_MUST_BE_TASK_SCOPED_POLICY,
        TRANSPORT_STATE_DRIVES_LIFECYCLE_ACTION_POLICY,
        TERMINAL_TASK_TRIGGERS_SESSION_TEARDOWN_POLICY,
        DEGRADED_TRANSPORT_YIELDS_DEGRADED_TASK_POLICY,
        FAILED_TRANSPORT_YIELDS_FAILED_TASK_POLICY,
        RECONNECTED_TRANSPORT_RESUMES_RUNNING_TASK_POLICY,
        BINDING_IS_TASK_SCOPED_SINGLE_SESSION_POLICY,
        TEARDOWN_IS_IDEMPOTENT_POLICY,
        SESSION_BINDING_RECORD_IS_IMMUTABLE_POLICY,
        WEBRTC_TASK_LIFECYCLE_PR6_SENTINEL,
    ]
    for p in policies:
        assert isinstance(p, str) and len(p) > 0, f"Sentinel is empty: {p!r}"


def test_ay1_snapshot_records_newest_first():
    """Snapshot records should reflect the registry state with newest entries first."""
    reg = _fresh_registry()
    bind_webrtc_session_to_task("t_old", "s_old", "d_old", registry=reg)
    bind_webrtc_session_to_task("t_new", "s_new", "d_new", registry=reg)
    snap = build_webrtc_task_binding_snapshot(registry=reg)
    # The snapshot reverses list_all() so newest is first
    assert len(snap.records) == 2
    assert snap.records[0]["task_id"] == "t_new"
    assert snap.records[1]["task_id"] == "t_old"


# ---------------------------------------------------------------------------
# Group AZ — WebRTC session manager config extensions (PR-6)
# ---------------------------------------------------------------------------

def test_az1_manager_config_accepts_task_id():
    pytest.importorskip("numpy", reason="numpy required for WebRTCManagerConfig tests")
    from core.multimodal.webrtc_session_manager import WebRTCManagerConfig
    cfg = WebRTCManagerConfig(task_id="my_task")
    assert cfg.task_id == "my_task"


def test_az2_manager_config_accepts_device_id():
    pytest.importorskip("numpy", reason="numpy required for WebRTCManagerConfig tests")
    from core.multimodal.webrtc_session_manager import WebRTCManagerConfig
    cfg = WebRTCManagerConfig(device_id="my_device")
    assert cfg.device_id == "my_device"


def test_az3_manager_config_task_id_defaults_none():
    pytest.importorskip("numpy", reason="numpy required for WebRTCManagerConfig tests")
    from core.multimodal.webrtc_session_manager import WebRTCManagerConfig
    cfg = WebRTCManagerConfig()
    assert cfg.task_id is None


def test_az4_manager_config_device_id_defaults_none():
    pytest.importorskip("numpy", reason="numpy required for WebRTCManagerConfig tests")
    from core.multimodal.webrtc_session_manager import WebRTCManagerConfig
    cfg = WebRTCManagerConfig()
    assert cfg.device_id is None


# ---------------------------------------------------------------------------
# Group — multimodal event types (PR-6 additions)
# ---------------------------------------------------------------------------

def test_multimodal_event_pr6_types_present():
    pytest.importorskip("numpy", reason="numpy required for multimodal events tests")
    from core.multimodal.multimodal_events import MultimodalEventType
    assert MultimodalEventType.WEBRTC_TASK_BOUND.value == "webrtc.task.bound"
    assert MultimodalEventType.WEBRTC_TASK_LIFECYCLE_CHANGED.value == "webrtc.task.lifecycle_changed"
    assert MultimodalEventType.WEBRTC_TASK_TORN_DOWN.value == "webrtc.task.torn_down"


def test_multimodal_event_pr6_dataclasses_constructible():
    pytest.importorskip("numpy", reason="numpy required for multimodal events tests")
    from core.multimodal.multimodal_events import (
        WebRTCTaskBoundEvent,
        WebRTCTaskLifecycleChangedEvent,
        WebRTCTaskTornDownEvent,
    )
    e1 = WebRTCTaskBoundEvent(task_id="t1", webrtc_session_id="s1", device_id="d1")
    assert e1.task_id == "t1"

    e2 = WebRTCTaskLifecycleChangedEvent(task_id="t1", transport_state="degraded")
    assert e2.transport_state == "degraded"

    e3 = WebRTCTaskTornDownEvent(task_id="t1", terminal_lifecycle="completed")
    assert e3.terminal_lifecycle == "completed"
