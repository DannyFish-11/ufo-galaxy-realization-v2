#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_reasoning_slot_stays_resident.py

钉住：**显存告急时先让开的是感知位，不是推理位。**

判据是"重载代价"，不是"谁更重要"
================================
``ComputeScheduler._release_oldest_locked`` 原本按 ``last_accessed`` 选最久没用的。
双模型档下这条规则的结果是**确定的**，不是概率问题：

* 感知位常年空转等事件发生 —— ``last_accessed`` 天然最旧；
* 推理位刚被唤起干完活 —— 时间戳最新。

于是纯 LRU 每次都精准踢中感知位。但真正该护住的是**另一位**：

===================  ==========================  ==========================
位                    重载要付什么                 结论
===================  ==========================  ==========================
推理位 35B-A3B        18 GB 权重走 mmap，还要重算   **常驻** —— 踢它等于把最贵
                      专家卸载拆分,几十秒起         的那步重做一遍
感知位（可换）         最小的 Gemma 4 E2B 1.8 GB;   **可让** —— 代价只是下一拍
                      ``ambient_attention_loop``    重载
                      的心跳每 tick 都会再要它
===================  ==========================  ==========================

早先这两位的常驻标志是反的，理由写的是"感知位被踢了就再也醒不来"。那句话说重了：
``core/ambient_attention_loop.py`` 的常驻心跳就是把它拉回来的人（Ollama 的
``/api/chat`` 按需加载），它并不需要靠钉住来保命。

为什么是"排最后"而不是"排除"
============================
"排除常驻位"会把单模型档的安全阀焊死：那时全场只有一个模型且它常驻，真的显存
告急就无路可走。故这里只**降序**——有非常驻的先踢非常驻的，全场都常驻才回落去踢
最旧的那个。单模型档因此逐字节维持原行为。
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
    monkeypatch.delenv("GALAXY_PERCEPTION_MODEL", raising=False)


class TestCompositeTier:
    def test_the_expensive_reasoning_slot_is_not_the_one_evicted(self, scheduler, composite_tier):
        """推理位刚干完活(时间戳最新)时,纯 LRU 本来也不会选它 —— 这条不算数。

        真正的判别场景在下一条:推理位**恰好也很久没用**时,仍不许踢它。
        """
        now = time.time()
        scheduler._models[PERCEPTION] = _alloc(PERCEPTION, last_accessed=now - 3600)
        scheduler._models[REASONING] = _alloc(REASONING, last_accessed=now - 1)

        assert asyncio.run(scheduler._release_oldest_locked()) is True
        assert REASONING in scheduler._models
        assert PERCEPTION not in scheduler._models

    def test_reasoning_survives_even_when_it_is_the_oldest(self, scheduler, composite_tier):
        """**判别点**:推理位比感知位还旧时,纯 LRU 会踢它,常驻策略必须拦住。"""
        now = time.time()
        scheduler._models[REASONING] = _alloc(REASONING, last_accessed=now - 7200)  # 更旧
        scheduler._models[PERCEPTION] = _alloc(PERCEPTION, last_accessed=now - 60)

        by_lru = sorted(scheduler._models.items(), key=lambda x: x[1].last_accessed)
        assert by_lru[0][0] == REASONING, "构造的场景没能复现'推理位最旧',这条测试就失去意义了"

        assert asyncio.run(scheduler._release_oldest_locked()) is True
        assert REASONING in scheduler._models, "推理位被踢了 —— 18 GB 权重与专家卸载拆分都要重做一遍"
        assert PERCEPTION not in scheduler._models

    def test_the_pinned_set_comes_from_the_catalog(self, scheduler, composite_tier):
        scheduler._models[PERCEPTION] = _alloc(PERCEPTION, last_accessed=1.0)
        scheduler._models[REASONING] = _alloc(REASONING, last_accessed=2.0)
        assert scheduler._resident_model_ids() == {REASONING}

    def test_pinned_set_follows_the_swapped_perception_model(self, scheduler, monkeypatch):
        """换了感知位之后,常驻名单仍然只有推理位 —— 换人不影响谁常驻。"""
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        monkeypatch.setenv("GALAXY_PERCEPTION_MODEL", "gemma4:e2b")
        scheduler._models["gemma4:e2b"] = _alloc("gemma4:e2b", last_accessed=1.0)
        scheduler._models[REASONING] = _alloc(REASONING, last_accessed=2.0)
        assert scheduler._resident_model_ids() == {REASONING}

    def test_perception_slot_alone_is_still_evictable(self, scheduler, composite_tier):
        scheduler._models[PERCEPTION] = _alloc(PERCEPTION, last_accessed=1.0)
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
        scheduler._models[REASONING] = _alloc(REASONING, last_accessed=now - 7200)
        scheduler._models[PERCEPTION] = _alloc(PERCEPTION, last_accessed=now - 60)

        assert scheduler._resident_model_ids() == set()
        assert asyncio.run(scheduler._release_oldest_locked()) is True
        assert REASONING not in scheduler._models  # 纯 LRU 的结果


class TestLedgerFollowsReality:
    """真实路径实测发现的：加载失败的模型不许留在账本里。

    实跑 ``reconcile_tier("C")``（本机没装 llama_cpp）看到的：

    .. code-block:: text

        WARNING 换档加载 qwen3.6:35b-a3b 失败(其余模型继续): No module named 'llama_cpp'
        换档后账本: ['openbmb/minicpm-o4.5', 'qwen3.6:35b-a3b']   ← 它明明没加载上

    ``schedule_model`` 先记账、再交给后端真加载；后端抛了，异常被吞掉，账本条目
    却留着。而账本正是淘汰、常驻判定、状态盘的依据 —— 双模型档下这个形状尤其难查：
    推理位其实没起来，可从系统内部看"两个模型都在跑"是成立的。
    """

    @staticmethod
    def _patch_backend(monkeypatch, result):
        import core.compute_scheduler as cs

        class _Backend:
            async def load_model(self, _mid):
                if isinstance(result, Exception):
                    raise result
                return result

            async def unload_model(self, _mid):
                return True

        monkeypatch.setattr(cs.ComputeScheduler, "_create_backend", staticmethod(lambda _n: _Backend()))

    def test_a_failed_load_is_rolled_back(self, scheduler, composite_tier, monkeypatch):
        self._patch_backend(monkeypatch, RuntimeError("后端起不来"))
        asyncio.run(scheduler.reconcile_tier("C"))
        assert scheduler._models == {}, f"加载全失败,账本却还留着 {list(scheduler._models)}"

    def test_a_backend_returning_false_also_rolls_back(self, scheduler, composite_tier, monkeypatch):
        """后端不抛异常、只是返回 False（GGUF 文件找不到走的就是这条）也算失败。"""
        self._patch_backend(monkeypatch, False)
        asyncio.run(scheduler.reconcile_tier("C"))
        assert scheduler._models == {}, "后端返回 False 被当成了成功"

    def test_a_successful_load_stays_in_the_ledger(self, scheduler, composite_tier, monkeypatch):
        self._patch_backend(monkeypatch, True)
        asyncio.run(scheduler.reconcile_tier("C"))
        assert set(scheduler._models) == {PERCEPTION, REASONING}

    def test_only_the_selected_perception_model_is_loaded(self, scheduler, monkeypatch):
        """换人之后加载的是**选中的**那个,不是候选表里的全部。"""
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        monkeypatch.setenv("GALAXY_PERCEPTION_MODEL", "gemma4:e2b")
        self._patch_backend(monkeypatch, True)
        asyncio.run(scheduler.reconcile_tier("C"))
        assert set(scheduler._models) == {"gemma4:e2b", REASONING}
        assert PERCEPTION not in scheduler._models, "没选中的候选也被拉起来了 —— 白占显存"
