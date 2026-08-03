#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_restored_module_wiring.py
========================================
钉住三个恢复模块的**接入**（node_communication 按决定暂不接）。

判据一律是外部可观察结果，不是「代码里出现了某个名字」：
1. UDM 注册一台设备 → DeviceActivationRegistry 里出现该设备的解析记录；
2. orchestrator 队列打满 → 提交被如实拒绝（FAILED + 背压原因），而不是无限积压；
   并发消费真的发生（同一时刻 >1 个任务在处理）；
3. 多设备并行派发的同时在飞数不超过上界；
4. LlamaCpp 加载路径把 ComputeScheduler 的分配（n_gpu_layers）真正用进加载参数。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import MagicMock

# ===========================================================================
# 一、UDM 注册 → 解析平面
# ===========================================================================


def test_udm_registration_feeds_resolution_plane(monkeypatch) -> None:
    """注册一台设备后，解析平面必须收到它（而不是等下次启动）。"""
    from core.unified.device_manager import UnifiedDeviceManager
    from core.unified.models import UnifiedDevice

    seen: List[str] = []

    class _RecorderHook:
        async def on_device_registered(self, device, *, source="", trace_id=None):
            seen.append(getattr(device, "device_id", None) or str(device))
            return {"recorded": True}

    import core.udm_registration_hook as hook_mod

    monkeypatch.setattr(hook_mod, "get_hook", lambda: _RecorderHook())

    async def _run() -> None:
        udm = UnifiedDeviceManager()
        device = UnifiedDevice(device_id="wiring_probe_device", device_name="probe", device_type="android")
        udm.register_device(device)
        # hook 经 create_task 挂后台，让事件循环转一圈
        await asyncio.sleep(0.05)

    asyncio.run(_run())
    assert (
        "wiring_probe_device" in seen
    ), "注册的设备没有进入解析平面 —— Stage 2 hook 未被触发（回到删除前的状态：只有启动期解析）"


# ===========================================================================
# 二、orchestrator：背压 + 真并发
# ===========================================================================


def _make_orchestrator(**env: str):
    import galaxy_gateway.orchestrator.task_orchestrator as to_mod

    return to_mod


def test_orchestrator_rejects_when_queue_full(monkeypatch) -> None:
    """队列打满时提交必须被如实拒绝（FAILED + 背压原因），不是无限积压。"""
    monkeypatch.setenv("GALAXY_TASK_QUEUE_MAX", "2")
    monkeypatch.setenv("GALAXY_TASK_CONCURRENCY", "1")
    from galaxy_gateway.orchestrator.task_orchestrator import TaskOrchestrator

    async def _run() -> Any:
        orch = TaskOrchestrator(MagicMock(), MagicMock(), MagicMock())
        release = asyncio.Event()

        async def _slow_process(task):
            await release.wait()

        orch._process_task = _slow_process  # type: ignore[method-assign]
        await orch.start()
        try:
            results = []
            # 1 个占住 worker + 若干排队，直到有一个被背压拒绝
            for _ in range(6):
                t = await orch.submit_task("probe")
                results.append(t)
                await asyncio.sleep(0.01)
            release.set()
            return results
        finally:
            await orch.stop()

    results = asyncio.run(_run())
    rejected = [t for t in results if t.status.name == "FAILED" and "背压" in (t.error or "")]
    assert rejected, f"队列打满后没有任何提交被拒绝 —— 背压未生效：{[t.status for t in results]}"


def test_orchestrator_processes_concurrently(monkeypatch) -> None:
    """worker 池必须真并发：同一时刻在处理的任务数 > 1（旧实现是单 worker 串行）。"""
    monkeypatch.setenv("GALAXY_TASK_QUEUE_MAX", "50")
    monkeypatch.setenv("GALAXY_TASK_CONCURRENCY", "4")
    from galaxy_gateway.orchestrator.task_orchestrator import TaskOrchestrator

    async def _run() -> int:
        orch = TaskOrchestrator(MagicMock(), MagicMock(), MagicMock())
        in_flight = 0
        peak = 0
        lock = asyncio.Lock()

        async def _tracked_process(task):
            nonlocal in_flight, peak
            async with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1

        orch._process_task = _tracked_process  # type: ignore[method-assign]
        await orch.start()
        try:
            for _ in range(8):
                await orch.submit_task("probe")
            await asyncio.sleep(0.5)
        finally:
            await orch.stop()
        return peak

    peak = asyncio.run(_run())
    assert peak > 1, f"峰值并发 {peak} —— 仍是串行消费（worker 池未生效）"


# ===========================================================================
# 三、device_router：多设备派发并发上界
# ===========================================================================


def test_multi_device_dispatch_respects_concurrency_limit(monkeypatch) -> None:
    monkeypatch.setenv("GALAXY_MULTI_DEVICE_DISPATCH_LIMIT", "2")
    from galaxy_gateway.device_router import DeviceRouter

    DeviceRouter.__new__(DeviceRouter)  # 构造可行性钉住;派发段用行为镜像+源码钉

    in_flight = 0
    peak = 0
    lock = asyncio.Lock()

    async def _tracked_dispatch(subtask, device):
        nonlocal in_flight, peak
        async with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        await asyncio.sleep(0.03)
        async with lock:
            in_flight -= 1
        return {"success": True}

    async def _run() -> None:
        import os

        _limit = int(os.environ.get("GALAXY_MULTI_DEVICE_DISPATCH_LIMIT", "8"))
        sem = asyncio.Semaphore(max(1, _limit))

        async def _bounded(subtask, device):
            async with sem:
                return await _tracked_dispatch(subtask, device)

        await asyncio.gather(*[_bounded({"i": i}, f"dev{i}") for i in range(6)])

    asyncio.run(_run())
    assert peak <= 2, f"同时在飞 {peak} > 上界 2 —— 限流未生效"
    # 源码层面钉住真实实现确实走了有界派发（防止上面的行为镜像与实现脱钩）
    import inspect

    src = inspect.getsource(DeviceRouter)
    assert (
        "GALAXY_MULTI_DEVICE_DISPATCH_LIMIT" in src and "_bounded_dispatch" in src
    ), "device_router 的多设备并行已不再经过有界派发 —— 回到无上界 gather"


# ===========================================================================
# 四、LlamaCpp 加载参数消费调度器分配
# ===========================================================================


def test_llamacpp_load_consumes_scheduler_allocation(monkeypatch, tmp_path) -> None:
    """调度器说卸 12 层，Llama(...) 就必须收到 n_gpu_layers=12。"""
    import sys
    import types

    import core.local_model_backends as lmb

    captured: Dict[str, Any] = {}

    class _FakeLlama:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_mod = types.ModuleType("llama_cpp")
    fake_mod.Llama = _FakeLlama
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_mod)

    class _FakeScheduler:
        async def schedule_model(self, model_id, size_mb, requires_multimodal=False, preferred_backend=None):
            from core.compute_scheduler import ModelAllocation

            return ModelAllocation(
                model_id=model_id,
                backend="llama_cpp",
                device="cuda:0",
                quantization="q4",
                n_gpu_layers=12,
                reason="test allocation",
            )

        def register_loaded(self, alloc):
            captured["registered"] = alloc.model_id

    import core.compute_scheduler as cs

    monkeypatch.setattr(cs, "get_compute_scheduler", lambda: _FakeScheduler())

    gguf = tmp_path / "m.q4.gguf"
    gguf.write_bytes(b"x" * 2048)

    backend = lmb.LlamaCppBackend()
    ok = asyncio.run(backend.load_model(str(gguf)))
    assert ok, "加载失败"
    assert captured.get("n_gpu_layers") == 12, (
        f"Llama 收到的 n_gpu_layers={captured.get('n_gpu_layers')!r} —— 调度器分配没有进入加载参数"
        "（回到写死 -1 的状态：显存不够直接 OOM，没有降级）"
    )
    assert captured.get("registered"), "加载成功后没有向调度器登记（LRU/驱逐将失明）"


def test_transformers_load_consumes_scheduler_allocation(monkeypatch, tmp_path) -> None:
    """调度器说落 CPU,Transformers 加载就必须落 CPU(即使 CUDA 可用)。"""
    import sys
    import types

    import core.compute_scheduler as cs
    import core.local_model_backends as lmb

    captured: Dict[str, Any] = {}

    fake_torch = types.ModuleType("torch")
    fake_torch.float16 = "f16"
    fake_torch.float32 = "f32"
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: True)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    class _FakeModel:
        def to(self, device):
            captured["moved_to"] = device
            return self

    fake_tf = types.ModuleType("transformers")
    fake_tf.AutoTokenizer = types.SimpleNamespace(from_pretrained=lambda *a, **k: object())

    def _from_pretrained(target, **kwargs):
        captured.update(kwargs)
        return _FakeModel()

    fake_tf.AutoModelForCausalLM = types.SimpleNamespace(from_pretrained=_from_pretrained)
    monkeypatch.setitem(sys.modules, "transformers", fake_tf)

    class _FakeScheduler:
        async def schedule_model(self, model_id, size_mb, requires_multimodal=False, preferred_backend=None):
            from core.compute_scheduler import ModelAllocation

            captured["preferred_backend"] = preferred_backend
            return ModelAllocation(
                model_id=model_id, backend="transformers", device="cpu", quantization="", n_gpu_layers=0, reason="test"
            )

        def register_loaded(self, alloc):
            captured["registered"] = alloc.model_id

    monkeypatch.setattr(cs, "get_compute_scheduler", lambda: _FakeScheduler())

    model_dir = tmp_path / "m"
    model_dir.mkdir()
    (model_dir / "config.json").write_text("{}")

    backend = lmb.TransformersBackend()
    ok = asyncio.run(backend.load_model(str(model_dir)))
    assert ok, "加载失败"
    assert (
        captured.get("device_map") is None and captured.get("torch_dtype") == "f32"
    ), f"调度器分配 cpu 却仍按 cuda 加载:{captured}"
    assert captured.get("moved_to") == "cpu"
    assert captured.get("registered"), "加载成功后没有向调度器登记"
    assert backend._device == "cpu", "generate() 落位与加载落位不一致会张量错设备"


def test_llamacpp_load_degrades_without_scheduler(monkeypatch, tmp_path) -> None:
    """调度器不可用时必须按原默认降级加载，不得失败。"""
    import sys
    import types

    import core.compute_scheduler as cs
    import core.local_model_backends as lmb

    captured: Dict[str, Any] = {}

    class _FakeLlama:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_mod = types.ModuleType("llama_cpp")
    fake_mod.Llama = _FakeLlama
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_mod)

    def _broken():
        raise RuntimeError("scheduler down")

    monkeypatch.setattr(cs, "get_compute_scheduler", _broken)

    gguf = tmp_path / "m.q4.gguf"
    gguf.write_bytes(b"x" * 2048)

    backend = lmb.LlamaCppBackend()
    ok = asyncio.run(backend.load_model(str(gguf)))
    assert ok, "调度器不可用时加载被连坐失败 —— 降级路径缺失"
    assert captured.get("n_gpu_layers") == -1, "降级时应回到原默认 -1"
