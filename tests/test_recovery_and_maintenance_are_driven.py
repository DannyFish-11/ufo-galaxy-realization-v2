"""tests/test_recovery_and_maintenance_are_driven.py — 重启恢复与周期清扫真的有人在驱动。

这一组的共同问题：**方法都写好了，没人按时调、没人在对的时刻调**。节点心跳超时、超时信封、
待决项、任务记忆 TTL、安全策略热重载只在被读到时才发现；委托流与混合执行从不落盘，重启恢复
读到的永远是空；续接重绑只记「待重绑」不记后两半；被叫停的任务在生命周期里永远停在 running；
续跑的执行在 Mesh 会话里查不到来历；参与方重连后挂着的信封没人交回。

每个用例走真实入口（周期循环、``run_startup_recovery``、完成入口、生命周期管理器、派发连续性门、
参与方心跳），断言状态真的变了。
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

# ---------------------------------------------------------------------------
# 周期维护循环本身
# ---------------------------------------------------------------------------


class TestPeriodicMaintenanceLoop:
    @pytest.mark.asyncio
    async def test_due_sweeps_run_and_one_failure_does_not_stop_the_rest(self):
        from core.periodic_maintenance import PeriodicMaintenance

        m = PeriodicMaintenance()
        calls = []

        def _boom():
            raise RuntimeError("disk gone")

        async def _async_ok():
            calls.append("async")
            return ["a", "b"]

        m.register("boom", _boom, every_s=60, run_first=True)
        m.register("async_ok", _async_ok, every_s=60, run_first=True)
        m.register("later", lambda: calls.append("later"), every_s=60)

        ran = await m.run_due()
        assert sorted(ran) == ["async_ok", "boom"]
        assert calls == ["async"]
        by_name = {s["name"]: s for s in m.status()["sweeps"]}
        assert by_name["boom"]["errors"] == 1 and "disk gone" in by_name["boom"]["last_error"]
        assert by_name["async_ok"]["last_outcome"] == 2
        assert by_name["later"]["runs"] == 0

        await m.run_due(now=time.monotonic() + 61)
        assert calls == ["async", "async", "later"]

    @pytest.mark.asyncio
    async def test_loop_starts_ticks_and_final_sweeps_run_on_stop(self):
        from core.periodic_maintenance import PeriodicMaintenance

        m = PeriodicMaintenance(tick_s=0.01)
        ticks, finals = [], []
        m.register("tick", lambda: ticks.append(1), every_s=0.0, run_first=True)
        m.register("checkpoint", lambda: finals.append(1), every_s=3600, final=True)
        assert m.start() is True
        await asyncio.sleep(0.05)
        assert m.status()["running"] is True and ticks
        await m.stop()
        assert m.status()["running"] is False
        assert finals == [1]

    def test_core_sweeps_are_registered(self):
        from core.periodic_maintenance import PeriodicMaintenance, register_core_sweeps

        names = {s["name"] for s in register_core_sweeps(PeriodicMaintenance()).status()["sweeps"]}
        assert {
            "task_envelopes.cancel_timed_out",
            "pending_decisions.sweep_expired",
            "task_memory.evict_expired",
            "hybrid_executions.prune",
            "security_policy.hot_reload",
            "delegated_flows.checkpoint",
        } <= names

    @pytest.mark.asyncio
    async def test_every_core_sweep_runs_cleanly_against_the_real_registries(self):
        from core.periodic_maintenance import PeriodicMaintenance, register_core_sweeps

        m = register_core_sweeps(PeriodicMaintenance())
        await m.run_due(now=time.monotonic() + 10**6)
        errors = {s["name"]: s["last_error"] for s in m.status()["sweeps"] if s["errors"]}
        assert errors == {}

    def test_status_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from core.routes.observability import create_router

        app = FastAPI()
        app.include_router(create_router())
        body = TestClient(app).get("/api/v1/observability/maintenance").json()
        assert set(body) == {"running", "tick_s", "sweeps"}


class TestSweepsDoTheirJob:
    @pytest.mark.asyncio
    async def test_timed_out_envelope_is_cancelled(self):
        import core.periodic_maintenance as pm
        from core.schemas.task_envelope import TaskEnvelope
        from core.task_envelope_lifecycle_registry import get_lifecycle_registry, reset_lifecycle_registry

        reset_lifecycle_registry()
        env = TaskEnvelope(task_id="t-stale", trace_id="tr", source="test", targets=["d1"], tool_name="x", args={})
        fut = asyncio.get_running_loop().create_future()
        record = get_lifecycle_registry().register(env, future=fut, timeout=1.0)
        assert pm._envelopes_timed_out() == []  # 刚超时：留给等待方自己按 TimeoutError 收场
        record.registered_at -= 1.0 + pm._ENVELOPE_TIMEOUT_GRACE_S + 0.1
        assert pm._envelopes_timed_out() == ["t-stale"]
        assert fut.cancelled()
        reset_lifecycle_registry()

    def test_heartbeat_age_sweeps_are_not_registered_without_a_heartbeat_source(self):
        from core.periodic_maintenance import PeriodicMaintenance, register_core_sweeps

        names = {s["name"] for s in register_core_sweeps(PeriodicMaintenance()).status()["sweeps"]}
        assert not any("stale" in n or "offline" in n for n in names)

    def test_security_policy_is_reloaded_when_the_file_changed(self, monkeypatch):
        import core.periodic_maintenance as pm
        import core.security_policy_loader as spl

        reloaded = []
        monkeypatch.setattr(spl, "get_security_policy", lambda: object())
        monkeypatch.setattr(spl, "check_policy_file_changed", lambda: True)
        monkeypatch.setattr(spl, "reload_security_policy", lambda *a, **k: reloaded.append(1))
        assert pm._security_policy_hot_reload() is True
        assert reloaded == [1]

    def test_security_policy_never_loaded_is_left_alone(self, monkeypatch):
        import core.periodic_maintenance as pm
        import core.security_policy_loader as spl

        monkeypatch.setattr(spl, "get_security_policy", lambda: None)
        monkeypatch.setattr(spl, "reload_security_policy", lambda *a, **k: pytest.fail("must not load"))
        assert pm._security_policy_hot_reload() is False


# ---------------------------------------------------------------------------
# 委托流：落盘 → 重启读回
# ---------------------------------------------------------------------------


@pytest.fixture
def _delegated_runtimes():
    from core.android_runtime_dispatch_binding import reset_dispatch_binding_runtime
    from core.attached_runtime_session_registry import reset_session_registry
    from core.delegated_flow_entity import reset_delegated_flow_entity_runtime
    from core.delegated_flow_persistence import reset_delegated_flow_persistence_bundle
    from core.delegated_runtime_handoff_contract import reset_handoff_contract_runtime

    resets = (
        reset_dispatch_binding_runtime,
        reset_session_registry,
        reset_delegated_flow_entity_runtime,
        reset_handoff_contract_runtime,
        reset_delegated_flow_persistence_bundle,
    )
    for r in resets:
        r()
    yield
    for r in resets:
        r()


class TestDelegatedFlowCheckpoint:
    def test_empty_process_does_not_overwrite_the_previous_snapshot(self, tmp_path, monkeypatch, _delegated_runtimes):
        import core.delegated_flow_persistence as dfp
        from core.delegated_flow_entity import create_delegated_flow_entity
        from core.periodic_maintenance import DelegatedFlowCheckpoint

        store = dfp.FlowEntityDurableStore(store_path=os.path.join(str(tmp_path), "flow_entity.json"))
        previous = create_delegated_flow_entity(delegated_flow_id="flow-before-restart")
        assert store.save([previous])

        bundle = dfp.DelegatedFlowPersistenceBundle(
            session_store=dfp.SessionDurableStore(store_path=os.path.join(str(tmp_path), "s.json")),
            contract_store=dfp.ContractDurableStore(store_path=os.path.join(str(tmp_path), "c.json")),
            binding_store=dfp.BindingDurableStore(store_path=os.path.join(str(tmp_path), "b.json")),
            flow_entity_store=store,
        )
        monkeypatch.setattr(dfp, "get_delegated_flow_persistence_bundle", lambda **_k: bundle)
        from core.delegated_flow_entity import reset_delegated_flow_entity_runtime

        reset_delegated_flow_entity_runtime()  # 「重启后」：进程内还什么都没有

        checkpoint = DelegatedFlowCheckpoint()
        assert checkpoint() == {}
        assert [e.delegated_flow_id for e in store.load()[1]] == ["flow-before-restart"]

        create_delegated_flow_entity(delegated_flow_id="flow-now")
        assert checkpoint() == {"flow_entity": True}
        assert [e.delegated_flow_id for e in store.load()[1]] == ["flow-now"]
        assert not os.path.exists(os.path.join(str(tmp_path), "s.json"))

    def test_restart_puts_persisted_flows_back_into_the_runtime(self, tmp_path, _delegated_runtimes):
        import core.delegated_flow_persistence as dfp
        from core.delegated_flow_entity import (
            create_delegated_flow_entity,
            get_delegated_flow_entity_runtime,
            reset_delegated_flow_entity_runtime,
        )

        store = dfp.FlowEntityDurableStore(store_path=os.path.join(str(tmp_path), "flow_entity.json"))
        create_delegated_flow_entity(delegated_flow_id="f-old")
        create_delegated_flow_entity(delegated_flow_id="f-new")
        assert store.save(get_delegated_flow_entity_runtime().list_all())

        reset_delegated_flow_entity_runtime()
        assert dfp.rehydrate_flow_entity_runtime(store=store) == 2
        runtime = get_delegated_flow_entity_runtime()
        assert runtime.get_by_flow_id("f-old") is not None
        assert [e.delegated_flow_id for e in runtime.list_all()] == ["f-new", "f-old"]
        assert dfp.rehydrate_flow_entity_runtime(store=store) == 0  # 已在的不重复放


# ---------------------------------------------------------------------------
# 混合执行：状态变化落盘，重启恢复读得到
# ---------------------------------------------------------------------------


class TestHybridExecutionsReachTheDisk:
    def test_transition_is_persisted_and_restart_recovery_reads_it(self, tmp_path, monkeypatch):
        import core.hybrid_orchestration_continuity as hoc

        store = hoc.HybridContinuityPersistenceStore(store_dir=str(tmp_path))
        monkeypatch.setattr(hoc, "get_hybrid_persistence_store", lambda *a, **k: store)
        registry = hoc.HybridOrchestrationContinuityRegistry()
        record = registry.create_and_register(task_id="t-hybrid")
        assert registry.transition(record.execution_id, hoc.HybridOrchestrationLifecycleState.dispatched)
        assert registry.transition(record.execution_id, hoc.HybridOrchestrationLifecycleState.running)
        assert store.load(record.execution_id).lifecycle_state == hoc.HybridOrchestrationLifecycleState.running

        fresh = hoc.HybridOrchestrationContinuityRegistry()  # 「重启后」
        assert fresh.restore_from_persistence(store) == 1
        assert fresh.mark_all_running_as_interrupted(reason="process_restart") == 1
        assert store.load(record.execution_id).lifecycle_state == hoc.HybridOrchestrationLifecycleState.interrupted

    def test_old_settled_records_are_pruned_from_disk(self, tmp_path):
        import core.hybrid_orchestration_continuity as hoc

        store = hoc.HybridContinuityPersistenceStore(store_dir=str(tmp_path))
        old = hoc.HybridOrchestrationRecord(task_id="old")
        old.lifecycle_state = hoc.HybridOrchestrationLifecycleState.completed
        old.updated_at = time.time() - 10 * 24 * 3600
        live = hoc.HybridOrchestrationRecord(task_id="live")
        live.lifecycle_state = hoc.HybridOrchestrationLifecycleState.running
        live.updated_at = time.time() - 10 * 24 * 3600
        assert store.save(old) and store.save(live)
        assert store.prune_settled(older_than_s=7 * 24 * 3600) == 1
        assert store.load(old.execution_id) is None
        assert store.load(live.execution_id) is not None

    def test_production_startup_recovery_uses_the_durable_hybrid_store(self, monkeypatch):
        import core.delegated_flow_persistence as dfp
        import core.runtime_restart_recovery as rrr

        seen = {}

        def _capture(self):
            seen["store"] = self._hybrid_continuity_store
            return rrr.RuntimeRecoveryReport()

        monkeypatch.setattr(rrr.RuntimeRestartRecoveryCoordinator, "run_recovery", _capture)
        monkeypatch.setattr(dfp, "rehydrate_flow_entity_runtime", lambda **_k: 3)
        monkeypatch.setattr(rrr, "_startup_recovery_report", None)
        report = rrr.run_startup_recovery()
        assert seen["store"] is not None
        assert report.delegated_flow_entities_restored == 3
        assert report.to_dict()["delegated_flow_entities_restored"] == 3


# ---------------------------------------------------------------------------
# 续接重绑：待重绑 → 新等待方 → 结果送达，闭环能判成
# ---------------------------------------------------------------------------


class TestContinuationRebindLoopCloses:
    @pytest.mark.asyncio
    async def test_new_waiter_and_delivery_close_the_loop(self):
        from core.canonical_completion_ingress import CanonicalCompletionIngress
        from core.continuation_rebind_registry import (
            get_continuation_rebind_registry,
            reset_continuation_rebind_registry,
        )

        reset_continuation_rebind_registry()
        rebind = get_continuation_rebind_registry()
        rebind.register_rebind_pending("t-rebind", recovery_id="rec-1")

        ingress = CanonicalCompletionIngress()
        fut = ingress.register_pending_dispatch("h-1", task_id="t-rebind")
        assert rebind.get_record("t-rebind").state.value == "rebound"

        class _Env:
            task_id = "t-rebind"
            handoff_id = "h-1"

        assert ingress.complete_pending_dispatch("h-1", _Env()) is True
        assert fut.done()
        assert rebind.is_loop_closed("t-rebind")
        reset_continuation_rebind_registry()

    @pytest.mark.asyncio
    async def test_ordinary_dispatch_leaves_the_rebind_registry_untouched(self):
        from core.canonical_completion_ingress import CanonicalCompletionIngress
        from core.continuation_rebind_registry import (
            get_continuation_rebind_registry,
            reset_continuation_rebind_registry,
        )

        reset_continuation_rebind_registry()
        CanonicalCompletionIngress().register_pending_dispatch("h-2", task_id="t-plain")
        assert get_continuation_rebind_registry().get_record("t-plain") is None


# ---------------------------------------------------------------------------
# 叫停 → interrupted
# ---------------------------------------------------------------------------


class TestCancelledWorkIsMarkedInterrupted:
    @staticmethod
    def _envelope(task_id):
        from core.schemas.task_envelope import TaskEnvelope

        return TaskEnvelope(task_id=task_id, trace_id=f"tr-{task_id}", source="test", targets=["d"], tool_name="x")

    @pytest.mark.asyncio
    async def test_cancel_while_running_marks_interrupted(self, monkeypatch):
        from core.task_lifecycle import TaskLifecycleManager, get_lifecycle_manager

        interrupted = []
        monkeypatch.setattr(
            TaskLifecycleManager, "mark_interrupted", lambda self, env, reason="": interrupted.append(env.task_id)
        )
        started = asyncio.Event()

        async def _work():
            get_lifecycle_manager().mark_running(self._envelope("t-stop"))
            started.set()
            await asyncio.sleep(10)

        task = asyncio.ensure_future(_work())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)
        assert interrupted == ["t-stop"]

    @pytest.mark.asyncio
    async def test_finished_or_failed_work_is_not_interrupted(self, monkeypatch):
        from core.task_lifecycle import TaskLifecycleManager, get_lifecycle_manager

        interrupted = []
        monkeypatch.setattr(
            TaskLifecycleManager, "mark_interrupted", lambda self, env, reason="": interrupted.append(env.task_id)
        )

        async def _work():
            lcm = get_lifecycle_manager()
            env = lcm.mark_running(self._envelope("t-done"))
            await asyncio.sleep(0)
            lcm.mark_done(env, result_summary="ok")
            lcm.mark_running(self._envelope("t-raise"))
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await asyncio.ensure_future(_work())
        await asyncio.sleep(0)
        assert interrupted == []


# ---------------------------------------------------------------------------
# 续跑挂回 Mesh 会话、参与方重连交回挂着的信封
# ---------------------------------------------------------------------------


class TestResumedWorkFindsItsContext:
    def test_resumed_execution_is_associated_with_its_mesh_session(self, monkeypatch):
        import core.mesh.mesh_session_lifecycle as msl
        from core.dispatch_continuity_gate import associate_resumed_mesh_execution
        from core.schemas.task_envelope import TaskEnvelope

        calls = []
        monkeypatch.setattr(
            msl, "associate_resumed_execution_with_session", lambda sid, ctx, **kw: calls.append((sid, kw)) or "rec"
        )
        env = TaskEnvelope(
            task_id="t-resumed",
            trace_id="tr-new",
            source="test",
            targets=["d"],
            tool_name="x",
            continuity_context={"prior_mesh_session_id": "mesh-1", "prior_dispatch_id": "old"},
        )
        assert associate_resumed_mesh_execution(env) == "rec"
        assert calls == [("mesh-1", {"resumed_dispatch_id": "t-resumed", "resumed_trace_id": "tr-new"})]

        fresh = TaskEnvelope(task_id="t-fresh", trace_id="tr", source="test", targets=["d"], tool_name="x")
        assert associate_resumed_mesh_execution(fresh) is None
        assert len(calls) == 1

    def test_participant_back_from_offline_gets_pending_envelopes_resumed(self, monkeypatch):
        import core.participant_admission as pa
        import core.task_envelope_lifecycle_registry as telr
        from core.unified.device_manager import get_unified_device_manager

        class _Device:
            status = "disconnected"

        udm = get_unified_device_manager()
        monkeypatch.setattr(pa, "_check_participant", lambda *_a, **_k: None)
        monkeypatch.setattr(udm, "get_device", lambda _id: _Device())
        monkeypatch.setattr(udm, "heartbeat", lambda _id: None)

        class _Registry:
            def resume_for_device(self, device_id):
                return [f"{device_id}-task"]

        monkeypatch.setattr(telr, "get_lifecycle_registry", lambda: _Registry())
        assert pa.participant_heartbeat("p1")["resumed_task_ids"] == ["p1-task"]

        class _OnlineDevice:
            status = "online"

        monkeypatch.setattr(udm, "get_device", lambda _id: _OnlineDevice())
        assert "resumed_task_ids" not in pa.participant_heartbeat("p1")


class TestGatewaySweepIsRegistered:
    @pytest.mark.asyncio
    async def test_parallel_group_timeouts_are_swept(self):
        from core.periodic_maintenance import get_periodic_maintenance
        from galaxy_gateway.bootstrap.lifecycle import _register_gateway_sweeps

        _register_gateway_sweeps()
        m = get_periodic_maintenance()
        names = {s["name"] for s in m.status()["sweeps"]}
        assert "gateway.parallel_groups.expire_timeouts" in names
        await m.run_due(now=time.monotonic() + 10**6)
        sweep = {s["name"]: s for s in m.status()["sweeps"]}["gateway.parallel_groups.expire_timeouts"]
        assert sweep["errors"] == 0 and sweep["runs"] >= 1
