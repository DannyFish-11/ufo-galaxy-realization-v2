"""tests/test_observability_is_actually_recorded.py — 指标与审计的采集点真的在真实位置被调到。

这一组能力此前的共同问题：**读取面都对外了，写入端没人调**。``/metrics`` 上运行 SLO 的
计数恒为 0、审计里没有选路 / 失败归类 / 策略决定、执行事件接口只看得到网关轨迹、
熔断次数恒为 0、决策时间线永远没有「主源切换」—— 看起来是「没出过事」，实际是「没人记」。

这里每个用例都走**真实的生产入口**（``CommandRouter.route_envelope``、``TaskGraph.execute``、
``CircuitBreaker``、``DurableAuditStore.append``、``run_startup_recovery`` 的记账、选路记录、
策略对齐面、感知源恢复快照），断言计数或记录真的变了，而不是直接调采集函数本身。
"""

from __future__ import annotations

import pytest

from core.schemas.task_envelope import TaskEnvelope


@pytest.fixture(autouse=True)
def _fresh_singletons():
    from core.audit_event_semantics import reset_audit_event_semantics
    from core.critical_path_harness import reset_critical_path_harness
    from core.execution_observability.event_log import reset_execution_event_log
    from core.operational_slo_metrics import reset_operational_slo_metrics

    reset_operational_slo_metrics()
    reset_audit_event_semantics()
    reset_execution_event_log()
    reset_critical_path_harness()
    yield
    reset_operational_slo_metrics()
    reset_audit_event_semantics()
    reset_execution_event_log()
    reset_critical_path_harness()


def _slo():
    from core.operational_slo_metrics import get_operational_slo_metrics

    return get_operational_slo_metrics().snapshot()


def _router(success: bool):
    from core.command_router import CommandRouter

    async def _exec(*_args, **_kwargs):
        return {
            "success": success,
            "result": "ok" if success else None,
            "request_id": "r1",
            "task_id": "t-obs",
            "trace_id": "tr-obs",
            "command_id": "c1",
            "device_id": "dev1",
            "command": "probe",
            "via": "mock",
            "error_code": None if success else "EXECUTION_FAILED",
            "error_message": None if success else "boom",
            "latency_ms": 0.0,
        }

    return CommandRouter(executor=_exec)


def _envelope(task_id: str, targets=None) -> TaskEnvelope:
    return TaskEnvelope(
        task_id=task_id,
        trace_id=f"tr-{task_id}",
        source="test",
        targets=list(targets if targets is not None else ["obs-dev"]),
        tool_name="probe",
        args={},
    )


@pytest.fixture
def _slots_open(monkeypatch):
    """派发槽位门放行（与 test_pr1_p0_completion_and_capability_closure 的桩同一做法）。"""
    from core import canonical_dispatch_slot_authority as slots

    def _approve(device_ids, execution_mode, **_kw):
        return slots.CanonicalDispatchSlotsResult(
            execution_mode=execution_mode,
            approved_slots=[
                slots.CanonicalDispatchSlot(
                    device_id=d,
                    execution_mode=execution_mode,
                    slot_approved=True,
                    status=slots.CanonicalDispatchSlotStatus.SLOT_APPROVED.value,
                    reason="test",
                )
                for d in device_ids
            ],
            blocked_slots=[],
            can_proceed=True,
        )

    monkeypatch.setattr(slots, "get_canonical_dispatch_slots", _approve)


class TestDispatchSpine:
    @pytest.mark.asyncio
    async def test_gate_rejection_is_counted_as_route_rejection(self):
        result = await _router(True).route_envelope(_envelope("t-empty", targets=[]))
        assert result.get("error_code") == "INVALID_ENVELOPE"
        assert _slo()["route_rejection"]["rejection_reason_counts"].get("INVALID_ENVELOPE") == 1
        assert _slo()["dispatch"]["attempts_total"] == 0

    @pytest.mark.asyncio
    async def test_successful_dispatch_is_counted_audited_and_emitted(self, _slots_open):
        result = await _router(True).route_envelope(_envelope("t-ok"))
        assert result.get("success") is True

        dispatch = _slo()["dispatch"]
        assert dispatch["attempts_total"] == 1
        assert dispatch["successes_total"] == 1
        assert dispatch["failures_total"] == 0

        from core.audit_event_semantics import get_audit_event_semantics

        kinds = {e.kind for e in get_audit_event_semantics().get_by_task("t-ok")}
        assert "route_decision" in {str(getattr(k, "value", k)) for k in kinds}

        from core.execution_observability.event_log import recent_execution_events

        assert any(e["origin"] == "command_router" for e in recent_execution_events(10))

        from core.critical_path_harness import snapshot_critical_path

        assert snapshot_critical_path()["dispatch_count"] == 1

    @pytest.mark.asyncio
    async def test_failed_dispatch_is_counted_and_gets_failure_handling_advice(self, _slots_open):
        result = await _router(False).route_envelope(_envelope("t-bad"))
        assert result.get("success") is False

        dispatch = _slo()["dispatch"]
        assert dispatch["attempts_total"] == 1
        assert dispatch["failures_total"] == 1
        assert "failure_handling_advice" in result

        from core.audit_event_semantics import get_audit_event_semantics

        kinds = {str(getattr(e.kind, "value", e.kind)) for e in get_audit_event_semantics().get_by_task("t-bad")}
        assert "failure_domain_identified" in kinds
        assert "policy_decision" in kinds


class TestOtherProducers:
    @pytest.mark.asyncio
    async def test_task_graph_completion_becomes_an_execution_event(self):
        from core.execution_observability.event_log import recent_execution_events
        from core.task_graph import TaskGraph

        graph = TaskGraph(trace_id="tr-graph", graph_id="g-obs")

        async def _node(_node_obj, _ctx):
            return {"ok": True}

        graph.add_node("one step", node_id="n1", handler=_node)
        await graph.execute()
        assert any(e["origin"] == "task_graph" for e in recent_execution_events(10))

    @pytest.mark.asyncio
    async def test_circuit_open_is_counted(self):
        from core.resilience.circuit_breaker import CircuitBreaker
        from core.resilience.metrics import get_resilience_metrics

        before = get_resilience_metrics().snapshot()["total_circuit_opens"]
        breaker = CircuitBreaker(target="obs-dev", failure_threshold=2, window_size=2)
        for _ in range(2):
            await breaker._record_failure()
        assert get_resilience_metrics().snapshot()["total_circuit_opens"] == before + 1

    def test_audit_persistence_success_and_failure_are_counted(self, tmp_path):
        from core.replay_audit_persistence import DurableAuditStore, ReplayAuditRecord

        ok_store = DurableAuditStore(store_path=tmp_path / "audit.jsonl")
        assert ok_store.append(ReplayAuditRecord(kind="replay", payload={"x": 1})) is True
        bad_store = DurableAuditStore(store_path=tmp_path / "no_such_dir" / "deeper" / "audit.jsonl")
        bad_store._store_path = tmp_path  # a directory: open(..., "a") fails
        assert bad_store.append(ReplayAuditRecord(kind="replay", payload={"x": 2})) is False

        persisted = _slo()["audit_persistence"]
        assert persisted["persist_successes_total"] == 1
        assert persisted["persist_failures_total"] == 1

    def test_startup_recovery_report_is_counted(self):
        from types import SimpleNamespace

        from core.recovery_telemetry import record_recovery_outcome

        report = SimpleNamespace(
            inflight_tasks_recovered=4,
            inflight_tasks_resumable=2,
            inflight_tasks_replay_only=1,
            inflight_tasks_reissuable=1,
            errors=["Mesh session recovery failed: disk"],
            _dispatched_ids={"a", "b", "c"},
        )
        record_recovery_outcome(report)
        rec = _slo()["recovery"]
        assert (rec["attempts_total"], rec["resumed_total"], rec["replayed_total"], rec["reissued_total"]) == (
            4,
            2,
            1,
            1,
        )
        assert rec["failed_total"] == 1
        assert _slo()["startup_recovery"] == {"tasks_scanned_total": 4, "actions_taken_total": 3}

    def test_run_startup_recovery_calls_the_recorder(self, monkeypatch):
        import core.recovery_telemetry as rt
        import core.runtime_restart_recovery as rrr

        seen = []
        monkeypatch.setattr(rt, "record_recovery_outcome", lambda report: seen.append(report))
        monkeypatch.setattr(rrr.RuntimeRestartRecoveryCoordinator, "run_recovery", lambda self: "REPORT")
        rrr.run_startup_recovery(task_lifecycle_store=object())
        assert seen == ["REPORT"]

    def test_model_route_fallback_is_counted(self):
        from core.routing_observability import recent_fallback_decisions, record_routing_decision

        record_routing_decision(
            {"route_type": "partial_multimodal", "fallback_reason": "native_multimodal_provider_unavailable"},
            trace_id="tr-fb",
        )
        assert _slo()["fallback"]["fallback_kind_counts"].get("native_multimodal_to_text") == 1
        assert recent_fallback_decisions(1)[0]["trace_id"] == "tr-fb"

    def test_policy_alignment_mismatch_is_counted(self, monkeypatch):
        import core.policy.alignment_surface as al
        from core.routing_observability import get_control_loop_metrics

        before = get_control_loop_metrics().projection_mismatch_count
        al._count_projection_mismatch()
        assert get_control_loop_metrics().projection_mismatch_count == before + 1


class TestSourceSwitchReachesTheTimeline:
    def test_real_snapshot_keys_are_understood(self):
        from core.decision_timeline import get_decision_timeline, record_source_switch_event, reset_decision_timeline

        reset_decision_timeline()
        snapshot = {
            "recent_switch_events": [
                {
                    "modality": "audio",
                    "previous_source_id": "mic-a",
                    "new_source_id": "mic-b",
                    "reason": "primary_failed",
                }
            ]
        }
        event = record_source_switch_event(source_recovery_dict=snapshot)
        assert event is not None
        text = str(
            get_decision_timeline().snapshot().to_dict()
            if hasattr(get_decision_timeline().snapshot(), "to_dict")
            else get_decision_timeline().snapshot()
        )
        assert "mic-b" in text
        reset_decision_timeline()


class TestReadSurface:
    def test_recent_events_endpoint_returns_layered_events(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from core.execution_observability.event_log import record_execution_event
        from core.execution_observability.normalizers import normalize_task_envelope
        from core.routes.observability import create_router

        record_execution_event(normalize_task_envelope(_envelope("t-read")), origin="command_router")
        app = FastAPI()
        app.include_router(create_router())
        body = TestClient(app).get("/api/v1/observability/execution/recent-events").json()
        assert body["layered_count"] >= 1
        assert body["layered_events"][0]["origin"] == "command_router"
