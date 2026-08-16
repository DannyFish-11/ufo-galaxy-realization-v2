#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_vram_admission_reads_runtime_not_weights.py

钉住：**「装不装得下」问的是运行时驻留量，不是权重大小**。

背景
====
``core/model_catalog`` 原来只有一栏尺寸 ``size_mb_val``，被两种完全不同的问题
共用：

* "要下载多少 / 占多少磁盘" —— 这是权重大小；
* "显存装不装得下"           —— 这是**加载后驻留在加速器里的量**。

这两个数对普通稠密模型差不多，对另外两类差得很远，而且**方向相反**：

* 全模态模型 **大于**权重：MiniCPM-o 4.5 的 4bit 权重 6 GB，跑起来还要驮上
  视觉编码器、音频编码器与语音解码器，实测约 11 GB；
* MoE 走专家卸载后 **小于**权重：35B-A3B 的 INT4 权重 18 GB，专家留内存、
  只有激活的 3 B 上卡，显存实测约 7.3 GB。

于是修复前，8 GB 显卡上：

.. code-block:: text

    HardwareProfile(vram_mb=8192).can_fit_model(6000)   -> True     # 按权重判
    实际加载                                             -> 11 GB → OOM

准入说"放得下"，加载到一半 OOM。而且报错在**加载途中**、不在准入处 ——
现场看到的是"这模型带不动"，不是"准入判错了"。同一个错值还喂给
``model_selection.recommend()``：8 GB 卡上首次启动就会**推荐**这个装不下的模型。

处置
====
``ModelSpec`` 拆成两栏：``size_mb()`` 权重、``runtime_mb()`` 驻留量。
没量过的型号 ``runtime_mb()`` 退回权重值（历史行为，不臆造数字）。
显存相关的判断一律问 ``runtime_mb()`` / ``LocalBrainManager.model_runtime_mb()``。
"""

from __future__ import annotations

import core.model_catalog as mc
import core.model_selection as ms
from core.hardware_compute_profiler import VRAM_HEADROOM_FACTOR
from core.local_brain_manager import HardwareProfile
from core.local_brain_manager import LocalBrainManager as LBM

# 8 GB 独显、空载。整篇的判据基准。
EIGHT_GB = HardwareProfile(vram_mb=8192, vram_used_mb=0)


def test_the_two_numbers_are_actually_different_for_the_omni_model():
    """全模态模型的驻留量必须显著大于权重 —— 否则下面所有断言都无从区分。"""
    spec = mc.get_model("openbmb/minicpm-o4.5")
    assert spec.size_mb() == 6000, "权重那一栏被改动了"
    assert spec.runtime_mb() == 11000
    assert spec.runtime_mb() > spec.size_mb(), "两栏又变成同一个数了，这条测试也就白测了"


def test_eight_gig_card_admits_by_weights_but_must_reject_by_runtime():
    """同一张卡、同一个模型，两种口径给相反答案 —— 必须按驻留量那个。

    这是本次修复的**判别点**：如果 ``runtime_mb()`` 又退回权重，第二条断言就红。
    """
    spec = mc.get_model("openbmb/minicpm-o4.5")
    assert EIGHT_GB.can_fit_model(spec.size_mb()) is True, "6 GB 权重在 8 GB 卡上本就判得下(这正是当初的陷阱)"
    assert EIGHT_GB.can_fit_model(spec.runtime_mb()) is False, "11 GB 驻留判成放得下 —— 加载到一半必 OOM"


def test_manager_side_accessor_reports_runtime_not_weights():
    """``LocalBrainManager`` 那张兜底表也必须有一个只答驻留量的入口。"""
    assert LBM.MODEL_SIZE_ESTIMATE_MB["openbmb/minicpm-o4.5"] == 6000, "权重表被改成驻留量了 —— 那是下载量，两码事"
    assert LBM.model_runtime_mb("openbmb/minicpm-o4.5") == 11000
    assert EIGHT_GB.can_fit_model(LBM.model_runtime_mb("openbmb/minicpm-o4.5")) is False


def test_unmeasured_models_keep_the_old_behaviour():
    """没量过驻留量的型号，两栏必须相等 —— 保守回落，不许凭空造数。"""
    for tag in ("gemma4:e2b", "gemma4:e4b", "gemma4:12b"):
        spec = mc.get_model(tag)
        assert spec.runtime_mb_val == 0, f"{tag} 被填了一个没有出处的驻留量"
        assert spec.runtime_mb() == spec.size_mb()
    # 目录外的通用型号(只在 LocalBrainManager 兜底表里)同理。
    assert LBM.model_runtime_mb("qwen2:7b") == LBM.MODEL_SIZE_ESTIMATE_MB["qwen2:7b"]


def test_moe_runtime_is_smaller_than_weights():
    """MoE 方向相反：专家卸载后驻留远小于权重。合成一栏必然在某一类上判错。"""
    spec = mc.get_model("qwen3.6:35b-a3b")
    assert spec.size_mb() == 18000
    assert spec.runtime_mb() == 7300
    assert spec.runtime_mb() < spec.size_mb()
    # 18 GB 权重在 8 GB 卡上当然判不下；7.3 GB 驻留也仍然判不下(余量 1.2 → 8760)。
    # 这里钉的不是"能装",是**两个数确实走的是不同判据**。
    assert EIGHT_GB.can_fit_model(spec.size_mb()) is False
    assert int(7300 * VRAM_HEADROOM_FACTOR) == 8760


def test_recommend_never_returns_a_model_that_cannot_fit():
    """推荐必须自洽：推出来的型号，按驻留量算得装得下预算。

    修复前 ``recommend()`` 拿权重去比预算，于是它推荐的东西自己都装不下。
    """
    runtime = {s.tag: s.runtime_mb() for s in mc.all_models()}
    for budget in (2000, 4000, 6826, 9000, 13653, 30000):
        tag = ms.recommend(budget, True)
        need = runtime.get(tag)
        if need:
            assert need <= budget, f"预算 {budget} MB 却推荐了驻留 {need} MB 的 {tag}"


def test_recommend_would_have_returned_the_oversized_model_under_the_old_criterion():
    """反向确认这条修复真的改变了行为，而不是碰巧本来就对。

    8 GB 卡的预算带里存在一个区间：按权重判 MiniCPM-o 合格、按驻留判不合格。
    区间非空，才说明两套判据在真实硬件上确实会分家。
    """
    spec = mc.get_model("openbmb/minicpm-o4.5")
    lo, hi = spec.size_mb(), spec.runtime_mb()
    assert lo < hi
    budget = (lo + hi) // 2  # 6000 < 8500 < 11000
    assert lo <= budget, "按权重判:这个预算下会被放行"
    assert hi > budget, "按驻留判:同一个预算下必须被拦"


def test_footprint_does_not_inherit_a_sibling_size_from_the_family_fallback():
    """目录查不到就答 0，**绝不**退回同家族的另一个型号。

    ``get_model()`` 有一条同家族兜底：查不到 ``gemma4:31b`` 就返回家族里的第一条
    ``gemma4:e2b``。那条兜底对"这个家族由哪个后端加载"是对的，对显存是错的 ——
    一个 31B 型号会被答成 1800 MB，于是放不下的模型被判成放得下，加载到一半必 OOM。
    猜错的数字比没有数字更危险。
    """
    assert mc.get_model("gemma4:31b") is not None, "前提变了：同家族兜底已被移除，本条判据要重写"
    assert mc.runtime_footprint_mb("gemma4:31b") == 0, "驻留量走了同家族兜底 —— 会把 31B 判成 2B"
    assert mc.runtime_footprint_mb("openbmb/minicpm-o4.5") == 11000, "精确命中的那条不该受影响"


def test_manager_defers_to_the_catalog_but_keeps_its_own_table():
    """同一个型号的驻留量不许在两处各写一份 —— 迟早只改一处。

    目录有的以目录为准；目录没有的(只在兜底表里的通用型号)仍由本类作答。
    """
    assert LBM.model_runtime_mb("openbmb/minicpm-o4.5") == mc.runtime_footprint_mb("openbmb/minicpm-o4.5")
    assert mc.runtime_footprint_mb("qwen2:7b") == 0, "前提变了：这个型号进目录了"
    assert LBM.model_runtime_mb("qwen2:7b") == LBM.MODEL_SIZE_ESTIMATE_MB["qwen2:7b"]
    # 家族兜底不许经由 manager 这条路重新渗回准入判据。
    assert LBM.model_runtime_mb("gemma4:31b") == LBM.MODEL_SIZE_ESTIMATE_MB["gemma4:31b"]
