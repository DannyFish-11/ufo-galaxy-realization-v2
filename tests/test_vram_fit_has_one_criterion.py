#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_vram_fit_has_one_criterion.py

钉住：**「这个模型放得下吗」只有一个判据，而且它真的会看你问的是多大的模型**。

两条，都是任务 #53 排查 0–3 层第 1 层（资源权威统一）时查出来的。

一、``GPUProfile.can_fit_model`` 是 ``@property`` 却带参数
---------------------------------------------------------
``@property`` 的 getter 只接受 ``self``。挂上去之后：

* ``profile.can_fit_model`` —— 属性求值，``model_size_mb`` **永远取默认的 4000**。
  问「20GB 的模型放得进 6GB 空闲显存吗」，答 ``True``。
* ``profile.can_fit_model(20000)`` —— 按签名那样调用，先求值成 ``bool`` 再去调用它，
  ``TypeError: 'bool' object is not callable``。

全仓零调用方，所以它没有造成过线上故障 —— 这是**陷阱**不是活缺陷。但第一个照签名
用它的人，拿到的不是错答案就是崩溃。

二、同一件事有两套判据，余量不同
--------------------------------
``core/local_brain_manager.HardwareProfile.can_fit_model`` 另有一套：
``(vram_mb - vram_used_mb) * 0.9 >= size``，10% 余量、而且 free 是减出来的。
两套在一条真实的带里给相反结论（24G 卡已用 18G 时，5000/5200/5400MB 三档）。

余量统一取 20%（``VRAM_HEADROOM_FACTOR``）：权重之外还要给激活值与 KV cache 留
地方，按 10% 算放得下、实际 OOM，代价比保守地少放一个模型大得多。
"""

from __future__ import annotations

import pytest

from core.hardware_compute_profiler import VRAM_HEADROOM_FACTOR, GPUProfile, GPUVendor
from core.local_brain_manager import HardwareProfile


def _gpu(*, total: int = 24000, free: int = 6000) -> GPUProfile:
    return GPUProfile(
        index=0,
        vendor=GPUVendor.NVIDIA,
        name="test-gpu",
        total_vram_mb=total,
        free_vram_mb=free,
        used_vram_mb=total - free,
        utilization_percent=0.0,
        temperature_c=0.0,
    )


# ---------------------------------------------------------------------------
# 一、它必须真的看你问的是多大的模型
# ---------------------------------------------------------------------------


def test_can_fit_model_actually_reads_its_argument():
    """这就是被修掉的那条：@property 让参数永远取默认的 4000。"""
    gpu = _gpu(free=6000)
    assert gpu.can_fit_model(2000) is True
    assert gpu.can_fit_model(4000) is True
    assert gpu.can_fit_model(8000) is False, "6000MB 空闲显存不可能放得下 8GB 模型"
    assert gpu.can_fit_model(20000) is False, "问 20GB 却答放得下 —— 参数又被吃掉了"


def test_it_is_a_method_not_a_property():
    """按签名调用不许抛 TypeError。

    钉住调用**形式**而不只是返回值：改回 @property 的话，``gpu.can_fit_model``
    会是一个 bool，下面这行就成了 ``bool(...)(8000)``。
    """
    gpu = _gpu(free=6000)
    assert callable(gpu.can_fit_model), "can_fit_model 又变回属性了"
    assert gpu.can_fit_model() is True, "不带参数时应按默认 4000 判"


def test_headroom_is_actually_applied():
    """余量必须真的留出来 —— 否则「刚好放得下」就是一定 OOM。"""
    gpu = _gpu(free=6000)
    exactly = int(6000 / VRAM_HEADROOM_FACTOR)
    assert gpu.can_fit_model(exactly - 100) is True
    assert gpu.can_fit_model(exactly + 100) is False, "余量没生效：按权重大小刚好塞下了"


# ---------------------------------------------------------------------------
# 二、两处判据必须同源
# ---------------------------------------------------------------------------

#: 旧口径与新口径给相反结论的那条带（24G 卡已用 18G）。**这就是修复的全部内容**，
#: 换成一堆本来就一致的样本，上面那条测不出东西。
_DISAGREEING_SIZES = (5000, 5200, 5400)


@pytest.mark.parametrize("size_mb", _DISAGREEING_SIZES)
def test_both_implementations_agree(size_mb):
    gpu = _gpu(total=24000, free=6000)
    brain = HardwareProfile(vram_mb=24000, vram_used_mb=18000)
    assert brain.can_fit_model(size_mb) == gpu.can_fit_model(size_mb), (
        f"{size_mb}MB：local_brain_manager 判 {brain.can_fit_model(size_mb)}、"
        f"hardware_compute_profiler 判 {gpu.can_fit_model(size_mb)} —— 两套判据又分家了"
    )


def test_the_disagreeing_band_is_the_one_that_was_fixed():
    """判据要**有区分度**：确认这几档在旧口径下确实是打架的。

    旧口径：(vram - used) * 0.9 >= size    新口径：(vram - used) > size * 1.2
    """
    free = 6000
    for size_mb in _DISAGREEING_SIZES:
        old = free * 0.9 >= size_mb
        new = free > size_mb * VRAM_HEADROOM_FACTOR
        assert old != new, f"{size_mb}MB 在新旧口径下本来就一致，这个样本证明不了什么"


def test_falls_back_when_the_authority_is_unavailable(monkeypatch):
    """权威模块取不到时退回原口径，而不是让本地主脑管理器整个起不来。"""
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "core.hardware_compute_profiler":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    brain = HardwareProfile(vram_mb=24000, vram_used_mb=18000)
    assert brain.can_fit_model(1000) is True
    assert brain.can_fit_model(20000) is False
