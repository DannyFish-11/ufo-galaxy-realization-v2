#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_perception_slot_survives_vram_pressure.py

钉住：**显存告急时被踢的不能是感知位。**

为什么恰恰是它会被踢
====================
``ComputeScheduler._release_oldest_locked`` 按 ``last_accessed`` 选最久没用的。
双模型档下这条规则的结果是**确定的**，不是概率问题：

* 感知位常年空转等事件发生 —— 它的 ``last_accessed`` 天然最旧；
* 推理位刚被唤起干完活 —— 时间戳最新。

于是纯 LRU 每次都精准踢中感知位。而这一位**被踢了就再也醒不来**：三态里
``silent → liminal`` 这一跳由它触发，可唤醒它的信号（看到什么、听到什么）
又只有它自己接得到。踢掉之后系统永远停在 silent，没有任何报错 ——
表现只是"它再也没反应了"。

为什么是"排最后"而不是"排除"
============================
"排除常驻位"会把单模型档的安全阀焊死：那时全场只有一个模型且它常驻，真的
显存告急就无路可走。故这里只**降序**——有非常驻的先踢非常驻的，全场都常驻
才回落去踢最旧的那个。单模型档因此逐字节维持原行为。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from core.compute_scheduler import ComputeScheduler, ModelAllocation

PERCEPTION = "openbmb/minicpm-o4.5"
REASONING = "qwen3.6:35b-a3b"


def _alloc(model_id: str, *, last_accessed: float, device: str = "cuda:0") -> ModelAllocation:
    return ModelAllocation(
        model_id=model_id,
        backend="llama_cpp",
        device=device,
        quantization="none",
        n_gpu_layers=-1,
        reason="test fixture",
        last_accessed=last_accessed,
    )


@pytest.fixture
def scheduler():
    """独占调度器账本(它是单例),用完还原。"""
    sched = ComputeScheduler()
    saved = dict(sched._models)
    sched._models.clear()
    try:
        yield sched
    finally:
        sched._models.clear()
        sched._models.update(saved)


@pytest.fixture
def composite_tier(monkeypatch):
    monkeypatch.setenv("GALAXY_MODEL_TIER", "C")


class TestCompositeTier:
    def test_the_idle_perception_slot_is_not_the_one_evicted(self, scheduler, composite_tier):
        """感知位最旧（真实形状），淘汰仍必须落到推理位头上。"""
        now = time.time()
        scheduler._models[PERCEPTION] = _alloc(PERCEPTION, last_accessed=now - 3600)  # 空转一小时
        scheduler._models[REASONING] = _alloc(REASONING, last_accessed=now - 1)  # 刚干完活

        assert asyncio.run(scheduler._release_oldest_locked()) is True
        assert PERCEPTION in scheduler._models, "感知位被踢了 —— 三态从此卡在 silent，且不会报错"
        assert REASONING not in scheduler._models

    def test_pure_lru_would_have_picked_the_perception_slot(self, scheduler, composite_tier):
        """反向确认：不看常驻位的话，被选中的**就是**感知位。

        这条钉的是"这次修复确实改变了行为"，否则上一条可能只是碰巧对。
        """
        now = time.time()
        scheduler._models[PERCEPTION] = _alloc(PERCEPTION, last_accessed=now - 3600)
        scheduler._models[REASONING] = _alloc(REASONING, last_accessed=now - 1)

        by_lru = sorted(scheduler._models.items(), key=lambda x: x[1].last_accessed)
        assert by_lru[0][0] == PERCEPTION, "构造的场景没能复现出'感知位最旧'，这条测试就失去意义了"

    def test_the_pinned_set_comes_from_the_catalog(self, scheduler, composite_tier):
        scheduler._models[PERCEPTION] = _alloc(PERCEPTION, last_accessed=1.0)
        scheduler._models[REASONING] = _alloc(REASONING, last_accessed=2.0)
        assert scheduler._resident_model_ids() == {PERCEPTION}

    def test_reasoning_slot_alone_is_still_evictable(self, scheduler, composite_tier):
        """只剩推理位时照常淘汰 —— 它由 OpenClawd 显式唤起，踢了能再加载。"""
        scheduler._models[REASONING] = _alloc(REASONING, last_accessed=1.0)
        assert asyncio.run(scheduler._release_oldest_locked()) is True
        assert scheduler._models == {}


class TestSingleTierBehaviourIsUnchanged:
    def test_the_sole_brain_is_still_released_under_pressure(self, scheduler, monkeypatch):
        """单模型档：全场都常驻 → 回落淘汰，安全阀不许被钉死。"""
        monkeypatch.setenv("GALAXY_MODEL_TIER", "A")
        scheduler._models["gemma4:12b"] = _alloc("gemma4:12b", last_accessed=1.0)
        assert asyncio.run(scheduler._release_oldest_locked()) is True
        assert scheduler._models == {}

    def test_no_gpu_models_still_reports_false(self, scheduler, monkeypatch):
        monkeypatch.setenv("GALAXY_MODEL_TIER", "A")
        scheduler._models["cpu-only"] = _alloc("cpu-only", last_accessed=1.0, device="cpu")
        assert asyncio.run(scheduler._release_oldest_locked()) is False
        assert "cpu-only" in scheduler._models


class TestDegradation:
    def test_catalog_failure_falls_back_to_plain_lru(self, scheduler, monkeypatch, composite_tier):
        """目录查不到时退化成纯 LRU —— 不许因为查不到就拒绝淘汰(那会锁死安全阀)。"""
        import core.model_catalog as mc

        def _boom(*_a, **_kw):
            raise RuntimeError("catalog unavailable")

        monkeypatch.setattr(mc, "is_resident", _boom)
        now = time.time()
        scheduler._models[PERCEPTION] = _alloc(PERCEPTION, last_accessed=now - 3600)
        scheduler._models[REASONING] = _alloc(REASONING, last_accessed=now - 1)

        assert scheduler._resident_model_ids() == set()
        assert asyncio.run(scheduler._release_oldest_locked()) is True
        assert PERCEPTION not in scheduler._models  # 纯 LRU 的结果
