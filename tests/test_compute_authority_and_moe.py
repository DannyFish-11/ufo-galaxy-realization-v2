#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_compute_authority_and_moe.py
===========================================
资源权威统一 + MoE 专家卸载。

两个缺口：
1. **Ollama 绕开调度器**——它是唯一不进资源账本的后端，于是 gpu_model_count /
   max_gpu_models / 换档驱逐全部对它失明，`ComputeScheduler` 不是唯一真相源；
2. **MoE 无法落位**——`ModelAllocation` 只有 ``n_gpu_layers`` 一轴，表达不了
   "注意力/共享层进显存、专家 FFN 进内存"这件事，而那正是让"有能力但带不动"的
   模型跑起来的机制。

判据全部基于**本机实测**（``hardware_compute_profiler`` 采样的 free VRAM /
available RAM），不是外部传入的需求值。目录保持 A/B 两档不变；MoE 型号以
临时挂载验证，绝不落库。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import pytest

from core.compute_scheduler import ComputeScheduler, ModelAllocation, SchedulerConfig


# ---------------------------------------------------------------------------
# 实测硬件替身：形状与 hardware_compute_profiler 的产出一致
# ---------------------------------------------------------------------------
class _GPU:
    def __init__(self, free_mb: int, total_mb: int = 16384, index: int = 0):
        self.index = index
        self.free_vram_mb = free_mb
        self.total_vram_mb = total_mb
        self.used_vram_mb = total_mb - free_mb

    @property
    def vram_usage_ratio(self) -> float:
        return self.used_vram_mb / max(1, self.total_vram_mb)


class _CPU:
    def __init__(self, available_ram_mb: int):
        self.available_ram_mb = available_ram_mb
        self.total_ram_mb = available_ram_mb * 2


class _Profile:
    def __init__(self, gpus: List[_GPU], available_ram_mb: int):
        self.gpus = gpus
        self.cpu = _CPU(available_ram_mb)


def _scheduler_on(monkeypatch, *, free_vram_mb: int, ram_mb: int, gpus: Optional[List[_GPU]] = None):
    """构造一个"本机实测出这样的硬件"的调度器。"""
    import core.hardware_compute_profiler as hcp

    profile = _Profile(gpus if gpus is not None else [_GPU(free_vram_mb)], ram_mb)

    class _Profiler:
        def profile_sync(self):
            return profile

    monkeypatch.setattr(hcp, "get_hardware_profiler", lambda: _Profiler())
    return ComputeScheduler()


# ===========================================================================
# 一、MoE 拆分：判据来自实测硬件
# ===========================================================================


def test_moe_split_uses_measured_hardware_not_caller_input(monkeypatch) -> None:
    """显存装不下整模型、但装得下共享层时 → 拆分：专家进内存。

    分配理由里必须带上**实测数字**，证明判据来自本机而不是入参需求。
    """
    sched = _scheduler_on(monkeypatch, free_vram_mb=4096, ram_mb=32768)
    alloc = asyncio.run(sched.schedule_model("probe-moe", model_size_mb=20000, is_moe=True))

    assert alloc.is_moe is True, "MoE 模型没有走拆分分支"
    assert alloc.n_cpu_moe > 0, "没有任何专家被卸到内存 —— 拆分没生效"
    assert alloc.n_gpu_layers == -1, "注意力/共享层应全部上 GPU（与专家卸载正交）"
    assert alloc.is_expert_offloaded is True
    assert "free=4096MB" in alloc.reason and "RAM=32768MB" in alloc.reason, f"理由未带实测数字: {alloc.reason}"


def test_moe_split_is_monotonic_in_free_vram(monkeypatch) -> None:
    """显存越少 → 卸到内存的专家层越多（拆分随实测硬件单调变化）。

    两种显存都必须**能**拆（共享层放得下）才谈得上单调；共享层放不下时算法
    如实拒绝拆分，那是另一条判据（见 test_moe_declines_when_shared_layers_do_not_fit）。
    """
    roomy = _scheduler_on(monkeypatch, free_vram_mb=8192, ram_mb=65536)
    a_roomy = asyncio.run(roomy.schedule_model("m", model_size_mb=20000, is_moe=True))

    tight = _scheduler_on(monkeypatch, free_vram_mb=4096, ram_mb=65536)
    a_tight = asyncio.run(tight.schedule_model("m", model_size_mb=20000, is_moe=True))

    assert a_roomy.is_moe and a_tight.is_moe, "两种显存都应能拆分（否则单调性无从谈起）"
    assert a_tight.n_cpu_moe > a_roomy.n_cpu_moe, f"显存更少却卸得更少: {a_tight.n_cpu_moe} vs {a_roomy.n_cpu_moe}"


def test_moe_declines_when_shared_layers_do_not_fit(monkeypatch) -> None:
    """连注意力/共享层都放不下 → 不做 MoE 拆分，老实回落既有分支。"""
    sched = _scheduler_on(monkeypatch, free_vram_mb=256, ram_mb=65536)
    alloc = asyncio.run(sched.schedule_model("huge-moe", model_size_mb=80000, is_moe=True))
    assert alloc.is_moe is False, "共享层都放不下却仍报 MoE 拆分"
    assert alloc.n_cpu_moe == 0


def test_moe_declines_when_ram_cannot_hold_experts(monkeypatch) -> None:
    """内存兜不住被卸的专家 → 拒绝拆分（换来疯狂换页不如老实降级）。"""
    sched = _scheduler_on(monkeypatch, free_vram_mb=4096, ram_mb=1024)
    alloc = asyncio.run(sched.schedule_model("moe", model_size_mb=20000, is_moe=True))
    assert alloc.is_moe is False, "内存明显不够却仍要卸专家进内存"


def test_moe_declines_when_ram_is_unmeasurable(monkeypatch) -> None:
    """内存探测不到（0）时不冒险拆分 —— 未知不等于充足。"""
    sched = _scheduler_on(monkeypatch, free_vram_mb=4096, ram_mb=0)
    alloc = asyncio.run(sched.schedule_model("moe", model_size_mb=20000, is_moe=True))
    assert alloc.is_moe is False


def test_non_moe_path_is_byte_identical(monkeypatch) -> None:
    """非 MoE 分配逐字段不变（新字段默认安全，不影响既有行为）。"""
    sched = _scheduler_on(monkeypatch, free_vram_mb=20000, ram_mb=32768)
    alloc = asyncio.run(sched.schedule_model("plain", model_size_mb=4000))
    assert alloc.is_moe is False and alloc.n_cpu_moe == 0
    assert alloc.n_gpu_layers == -1 and alloc.quantization == "none"


def test_allocation_defaults_are_backward_compatible() -> None:
    """不传 MoE 参数构造分配 → 字段安全默认。"""
    a = ModelAllocation(model_id="x", backend="ollama", device="cpu", quantization="q4", n_gpu_layers=0, reason="r")
    assert a.is_moe is False and a.n_cpu_moe == 0 and a.is_expert_offloaded is False


def test_split_respects_configured_safety_margins() -> None:
    """安全系数真的参与计算（不是摆设）：收紧显存安全系数 → 卸得更多（或直接拒绝）。"""
    sched = ComputeScheduler()
    loose = sched._split_moe(20000, 10000, 65536, SchedulerConfig(moe_vram_safety=0.9))
    strict = sched._split_moe(20000, 10000, 65536, SchedulerConfig(moe_vram_safety=0.5))
    assert loose is not None and strict is not None, f"该显存下两档系数都应能拆: {loose} / {strict}"
    assert strict > loose, f"更保守的安全系数反而卸得更少: {strict} vs {loose}"


def test_stricter_safety_never_loosens_the_decision() -> None:
    """更保守的系数不可能给出更激进的结论：要么卸更多，要么干脆拒绝。"""
    sched = ComputeScheduler()
    loose = sched._split_moe(20000, 4096, 65536, SchedulerConfig(moe_vram_safety=0.9))
    strict = sched._split_moe(20000, 4096, 65536, SchedulerConfig(moe_vram_safety=0.5))
    assert strict is None or (loose is not None and strict >= loose)


# ===========================================================================
# 二、llama.cpp 参数翻译（三级降级）
# ===========================================================================


def _load_with_fake_llama(monkeypatch, tmp_path, alloc: ModelAllocation, init_params: List[str]) -> Dict[str, Any]:
    """用一个签名可控的假 Llama 驱动真实 load_model，返回它收到的参数。"""
    import sys
    import types

    import core.compute_scheduler as cs
    import core.local_model_backends as lmb

    captured: Dict[str, Any] = {}

    # 用 exec 造一个**签名真的不同**的 __init__，让 inspect.signature 探测有意义
    ns: Dict[str, Any] = {"captured": captured}
    sig = ", ".join(["self"] + [f"{p}=None" for p in init_params] + ["**kw"])
    body = "captured.update({k: v for k, v in locals().items() if k not in ('self', 'kw')}); captured.update(kw)"
    exec(f"def __init__({sig}):\n    {body}", ns)  # noqa: S102

    fake_llama_cls = type("Llama", (), {"__init__": ns["__init__"]})
    fake_mod = types.ModuleType("llama_cpp")
    fake_mod.Llama = fake_llama_cls
    monkeypatch.setitem(sys.modules, "llama_cpp", fake_mod)

    class _S:
        async def schedule_model(self, *a, **k):
            captured["_sched_kwargs"] = k
            return alloc

        def register_loaded(self, _a):
            captured["_registered"] = True

        config = SchedulerConfig()

    monkeypatch.setattr(cs, "get_compute_scheduler", lambda: _S())

    gguf = tmp_path / "m.q4.gguf"
    gguf.write_bytes(b"x" * 4096)
    ok = asyncio.run(lmb.LlamaCppBackend().load_model(str(gguf)))
    captured["_ok"] = ok
    return captured


def _moe_alloc(n_cpu_moe: int = 8) -> ModelAllocation:
    return ModelAllocation(
        model_id="m",
        backend="llama_cpp",
        device="cuda:0",
        quantization="none",
        n_gpu_layers=-1,
        reason="moe",
        is_moe=True,
        n_cpu_moe=n_cpu_moe,
    )


def test_moe_offload_prefers_native_param(monkeypatch, tmp_path) -> None:
    """llama-cpp-python 支持 n_cpu_moe 时直接传（与 CLI --n-cpu-moe 同义）。"""
    got = _load_with_fake_llama(
        monkeypatch, tmp_path, _moe_alloc(8), ["model_path", "n_gpu_layers", "n_ctx", "verbose", "n_cpu_moe"]
    )
    assert got["_ok"] is True
    assert got.get("n_cpu_moe") == 8, f"未使用原生入参: {got}"
    assert got.get("n_gpu_layers") == -1, "注意力/共享层仍应全部上 GPU"


def test_moe_offload_falls_back_to_tensor_override(monkeypatch, tmp_path) -> None:
    """没有 n_cpu_moe 时退到 override_tensor 正则，把专家张量钉到 CPU。"""
    got = _load_with_fake_llama(
        monkeypatch, tmp_path, _moe_alloc(8), ["model_path", "n_gpu_layers", "n_ctx", "verbose", "override_tensor"]
    )
    ov = got.get("override_tensor")
    assert ov, f"未退到 override_tensor: {got}"
    assert ov.endswith("=CPU"), f"override 语法应为 <正则>=<buffer>: {ov}"
    assert "exps" in ov, "override 应匹配专家张量 ffn_*_exps"


def test_moe_offload_degrades_loudly_when_unsupported(monkeypatch, tmp_path, caplog) -> None:
    """两条路都不通 → 仍能加载，但必须响亮告知"专家卸载未生效"。"""
    import logging

    with caplog.at_level(logging.WARNING):
        got = _load_with_fake_llama(
            monkeypatch, tmp_path, _moe_alloc(8), ["model_path", "n_gpu_layers", "n_ctx", "verbose"]
        )
    assert got["_ok"] is True, "不支持专家卸载不应导致加载失败"
    assert "n_cpu_moe" not in got and "override_tensor" not in got
    assert any("专家卸载未生效" in r.message for r in caplog.records), "静默退化 —— 现场看不出为何 OOM"


def test_override_pattern_targets_top_layers() -> None:
    """override 正则针对**顶部 N 层**（与 --n-cpu-moe 语义一致），不是全量。"""
    from core.local_model_backends import LlamaCppBackend

    part = LlamaCppBackend._moe_cpu_override_pattern(4, 32)
    assert "28|29|30|31" in part, f"顶部 4 层的块索引不对: {part}"
    full = LlamaCppBackend._moe_cpu_override_pattern(-1, 32)
    assert "blk" not in full, f"全部层不应逐个列举块索引: {full}"


def test_non_moe_allocation_adds_no_extra_llama_params(monkeypatch, tmp_path) -> None:
    """非 MoE 分配不得混入任何专家卸载参数。"""
    plain = ModelAllocation(
        model_id="m", backend="llama_cpp", device="cuda:0", quantization="q4", n_gpu_layers=20, reason="plain"
    )
    got = _load_with_fake_llama(
        monkeypatch, tmp_path, plain, ["model_path", "n_gpu_layers", "n_ctx", "verbose", "n_cpu_moe"]
    )
    assert got.get("n_gpu_layers") == 20
    assert not got.get("n_cpu_moe"), f"非 MoE 却传了专家卸载参数: {got}"


# ===========================================================================
# 三、Ollama 进资源账本（调度器成为唯一真相源）
# ===========================================================================


def test_ollama_load_enters_resource_ledger(monkeypatch) -> None:
    """Ollama 加载必须进账本，卸载必须销账 —— 否则调度器对它永远失明。"""
    import core.compute_scheduler as cs
    import core.local_model_backends as lmb

    ledger: Dict[str, Any] = {}

    class _S:
        async def schedule_model(self, model_id, size_mb, requires_multimodal=False, preferred_backend=None, **kw):
            ledger["scheduled"] = (model_id, size_mb, preferred_backend)
            return ModelAllocation(
                model_id=model_id, backend="ollama", device="cpu", quantization="q4", n_gpu_layers=0, reason="acct"
            )

        def register_loaded(self, alloc):
            ledger["registered"] = alloc.model_id

        def unregister(self, model_id):
            ledger["unregistered"] = model_id

    monkeypatch.setattr(cs, "get_compute_scheduler", lambda: _S())

    backend = lmb.OllamaBackend()
    asyncio.run(backend.load_model("gemma4:12b"))
    assert ledger.get("scheduled"), "Ollama 加载没有咨询调度器 —— 账本看不到它占的资源"
    assert ledger["scheduled"][2] == "ollama"
    assert ledger.get("registered") == "gemma4:12b", "加载后未登记"

    asyncio.run(backend.unload_model("gemma4:12b"))
    assert ledger.get("unregistered") == "gemma4:12b", "卸载后未销账 —— 账本会越积越多"


def test_ollama_size_comes_from_catalog_ssot(monkeypatch) -> None:
    """Ollama 标签没有本地文件，尺寸必须取自模型目录（SSOT），不是瞎猜。"""
    import core.compute_scheduler as cs
    import core.local_model_backends as lmb
    from core.model_catalog import get_model

    spec = get_model("gemma4:12b")
    assert spec is not None and spec.size_mb() > 0

    seen: Dict[str, Any] = {}

    class _S:
        async def schedule_model(self, model_id, size_mb, requires_multimodal=False, preferred_backend=None, **kw):
            seen["size"] = size_mb
            return ModelAllocation(
                model_id=model_id, backend="ollama", device="cpu", quantization="q4", n_gpu_layers=0, reason="r"
            )

        def register_loaded(self, _a):
            pass

    monkeypatch.setattr(cs, "get_compute_scheduler", lambda: _S())
    asyncio.run(lmb.OllamaBackend().load_model("gemma4:12b"))
    assert seen["size"] == spec.size_mb(), f"尺寸未取自目录 SSOT: {seen}"


def test_ollama_load_survives_scheduler_outage(monkeypatch, caplog) -> None:
    """调度器不可用时加载仍成功，但必须响亮告知账本会偏少。"""
    import logging

    import core.compute_scheduler as cs
    import core.local_model_backends as lmb

    def _broken():
        raise RuntimeError("scheduler down")

    monkeypatch.setattr(cs, "get_compute_scheduler", _broken)
    with caplog.at_level(logging.WARNING):
        ok = asyncio.run(lmb.OllamaBackend().load_model("gemma4:12b"))
    assert ok is True, "调度器故障不应连坐加载"
    assert any("资源账本" in r.message for r in caplog.records), "静默失账 —— 后续分配会过量承诺"


# ===========================================================================
# 四、目录：临时挂载不落库 + llama_cpp 源放行 + 档位不变
# ===========================================================================


def test_ephemeral_spec_never_pollutes_catalog() -> None:
    """临时挂 MoE 型号用于验证：可查询，但绝不进目录/快照/候选清单。"""
    from core.model_catalog import (
        ModelCapability,
        ModelSpec,
        all_models,
        catalog_snapshot,
        choice_order,
        clear_ephemeral_specs,
        get_model,
        register_ephemeral_spec,
    )

    before_models = {m.tag for m in all_models()}
    spec = ModelSpec(
        tag="probe-moe-30b-a3b",
        name="MoE 验证型号",
        desc="仅本进程验证用",
        caps=ModelCapability(tools=True),
        source="llama_cpp",
        size_mb_val=18000,
        is_moe=True,
    )
    try:
        register_ephemeral_spec(spec)
        got = get_model("probe-moe-30b-a3b")
        assert got is not None and got.is_moe is True, "临时型号查不到"
        assert {m.tag for m in all_models()} == before_models, "临时型号污染了目录"
        assert "probe-moe-30b-a3b" not in choice_order(), "临时型号进了主脑候选清单"
        assert "probe-moe-30b-a3b" not in str(catalog_snapshot()), "临时型号进了快照（会被持久化）"
    finally:
        clear_ephemeral_specs()
    assert get_model("probe-moe-30b-a3b") is None, "清理后仍可见"


def test_catalog_tiers_and_models_unchanged() -> None:
    """目录 SSOT 不变式：A/B 单模型档 + C 双模型复合档。

    这条钉的是**档位构成**不许悄悄变，不是"永远只有两档"。加 C 档是显式动作
    （见 tests/test_brain_roster_slots.py）；档位无声增减才是要拦的。
    """
    from core.model_catalog import all_models, all_tiers

    assert [t.key for t in all_tiers()] == ["A", "B", "D", "C"]
    assert {t.key: t.kind for t in all_tiers()} == {
        "A": "single",
        "B": "single",
        "D": "composite",
        "C": "composite",
    }
    # 钉**具体是哪几个**，不是钉个数：光比个数，删掉一个再加一个照样过 ——
    # 而"悄悄换掉一个型号"正是这条守卫要拦的那类改动。
    assert {m.tag for m in all_models()} == {
        "gemma4:e2b",
        "gemma4:e4b",
        "gemma4:12b",
        "openbmb/minicpm-o4.5",
        "qwen3.6:35b-a3b",
        # C 档推理位的第二候选。加它是**显式动作**(见
        # tests/test_c_tier_has_a_second_reasoning_candidate.py)，与加 C 档同一性质：
        # 档位构成没动(仍是 A/B 单模型 + D/C 复合)，动的是 C 档推理位的候选表。
        "agents-a1:35b-a3b",
        "qwythos-9b-v2",
    }


def test_llama_cpp_source_is_admitted_to_choices() -> None:
    """source=llama_cpp（本地 GGUF）应可进主脑候选 —— MoE 专家卸载只在这条路上可用。"""
    import inspect

    from core.model_catalog import choice_order

    src = inspect.getsource(choice_order)
    assert '"llama_cpp"' in src, "候选清单仍只放行 Ollama 源，GGUF/MoE 无路可走"


# ===========================================================================
# 五、换档收口：算目标 → 驱逐 → 加载
# ===========================================================================


def test_reconcile_tier_evicts_then_loads(monkeypatch) -> None:
    """换档由调度器一处负责：非目标档模型被真卸载 + 销账，目标档被加载。"""
    import core.compute_scheduler as cs

    sched = _scheduler_on(monkeypatch, free_vram_mb=20000, ram_mb=65536)
    # 账本里先放一个不属于目标档的模型
    sched.register_loaded(
        ModelAllocation(
            model_id="stale-model", backend="ollama", device="cpu", quantization="q4", n_gpu_layers=0, reason="old"
        )
    )

    calls: Dict[str, List[str]] = {"unloaded": [], "loaded": []}

    class _Backend:
        async def unload_model(self, mid):
            calls["unloaded"].append(mid)

        async def load_model(self, mid):
            calls["loaded"].append(mid)
            return True

    monkeypatch.setattr(cs.ComputeScheduler, "_create_backend", staticmethod(lambda _n: _Backend()))

    allocs = asyncio.run(sched.reconcile_tier("A"))

    assert "stale-model" in calls["unloaded"], "非目标档模型没被卸载"
    assert sched.get_allocation("stale-model") is None, "卸载后没销账"
    assert calls["loaded"], "目标档模型没有被加载"

    # 只加载**这一档正在跑的**那几个(每位一个),不是全部候选。
    #
    # 原来这里加载的是 tier_models()(全部候选) —— A 档是单模型档,却会把三个
    # Gemma 一起拉起来占显存,而同时只有一个当主脑。槽位改成候选制之后这条自然
    # 修掉了:换档只加载 active_tags()。
    from core.model_catalog import active_tags

    expected = set(active_tags("A"))
    assert len(expected) == 1, "A 档是单模型档,正在跑的应当只有一个"
    assert set(calls["loaded"]) == expected, f"加载集合与正在跑的不一致: {calls['loaded']} vs {expected}"
    assert len(calls["loaded"]) == 1, f"单模型档却加载了 {len(calls['loaded'])} 个 —— 白占显存"


def test_reconcile_tier_survives_backend_failures(monkeypatch) -> None:
    """单个模型卸载/加载失败不得中断整次换档（其余照常对齐）。"""
    import core.compute_scheduler as cs

    sched = _scheduler_on(monkeypatch, free_vram_mb=20000, ram_mb=65536)
    sched.register_loaded(
        ModelAllocation(
            model_id="stuck", backend="ollama", device="cpu", quantization="q4", n_gpu_layers=0, reason="old"
        )
    )

    class _Backend:
        async def unload_model(self, mid):
            raise RuntimeError("unload exploded")

        async def load_model(self, mid):
            raise RuntimeError("load exploded")

    monkeypatch.setattr(cs.ComputeScheduler, "_create_backend", staticmethod(lambda _n: _Backend()))

    allocs = asyncio.run(sched.reconcile_tier("A"))  # 不应抛出
    assert sched.get_allocation("stuck") is None, "卸载失败也必须销账，否则账本永远脏"
    assert isinstance(allocs, list)


def test_tier_switch_route_delegates_to_scheduler() -> None:
    """换档路由必须委托调度器对齐资源，而不是自己各算各的。"""
    import ast
    import inspect

    import core.routes.models as models_routes

    tree = ast.parse(inspect.getsource(models_routes))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "reconcile_tier"
    ]
    assert calls, "换档路由没有走调度器的资源对齐（注释不算，必须是真实调用）"


# ===========================================================================
# 六、硬件探测必须在没有 psutil 的机器上也给出真数（否则 MoE 等于没有）
# ===========================================================================


def test_ram_probe_works_without_psutil(monkeypatch) -> None:
    """psutil 缺席时内存仍须探到真数 —— 此前直接归 0，让所有"按可用内存决策"
    的能力（MoE 专家卸载首当其冲）在最小化部署上等于不存在。"""
    import builtins

    from core.hardware_compute_profiler import HardwareComputeProfiler

    real_import = builtins.__import__

    def _no_psutil(name, *a, **k):
        if name == "psutil":
            raise ImportError("psutil absent (simulated)")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_psutil)
    cpu = HardwareComputeProfiler()._profile_cpu()

    assert cpu.total_ram_mb > 0, "无 psutil 时内存总量探不到 —— 回到 0 的老路"
    assert cpu.available_ram_mb > 0, "无 psutil 时可用内存探不到"
    assert cpu.available_ram_mb <= cpu.total_ram_mb
    assert cpu.physical_cores >= 1, "无 psutil 时核数也不该归 1 以下"


def test_ram_probe_reports_zero_only_when_truly_unmeasurable(monkeypatch) -> None:
    """所有原生接口都失败时才归 0 —— 那时的 0 才真的表示"测不到"。"""
    from core.hardware_compute_profiler import HardwareComputeProfiler

    monkeypatch.setattr(HardwareComputeProfiler, "_probe_ram_without_psutil", staticmethod(lambda: (0, 0)))
    import builtins

    real_import = builtins.__import__

    def _no_psutil(name, *a, **k):
        if name == "psutil":
            raise ImportError("psutil absent")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_psutil)
    cpu = HardwareComputeProfiler()._profile_cpu()
    assert cpu.available_ram_mb == 0 and cpu.total_ram_mb == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
