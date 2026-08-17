#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_context_is_measured_not_guessed.py

钉住上一轮上下文改动的五处**自我修正** —— 它们修的是上一轮自己留下的毛病。

上一轮把写死的 ``n_ctx = 4096`` 换成了一个"推导值"。但那个推导值的三个输入全是
新拍的常数(``_CHARS_PER_TOKEN`` / ``_TOKENS_PER_TOOL_DEF`` / ``_TOKENS_BASELINE``)，
**等于用三个新猜的数换掉了一个旧猜的数**。更糟的是形状搞反了：

    want = min(demand, model_cap)      ← 把一个静态预测值当成了天花板

``n_ctx`` 是加载期参数，定了就改不了。拿静态预测封顶，意味着显存再富余、模型能吃
1M，系统也永远用不超过那个数 —— 而那个数里"会话历史"只是一个拍出来的 2048，恰恰
是长会话里唯一真正在涨的东西。**让唯一会变的东西说了不算。**

本文件钉五条：

1. 五个型号填上了**真实**的上下文上限（查证过，不是猜的）；
2. KV 单价从"目录里没人填得出的常数"变成**加载时实测**，实测优先于声明；
3. ``n_ctx`` 的形状改对：装配量是**下限**，显存决定能在下限之上开多大；
4. 显存是**物理硬上限**，下限不能盖过它（硬开到下限的结果是加载不起来）；
5. 工具表的 token 数**数真表**，不再是 ``条数 × 180``。
"""

from __future__ import annotations

import json

import pytest

import core.compute_scheduler as cs
import core.context_measurements as cm
import core.context_trim as ct
import core.model_catalog as mc


@pytest.fixture
def isolated_measurements(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "_FILE", tmp_path / "context_measurements.json")
    monkeypatch.delenv("GALAXY_LLAMA_CTX", raising=False)
    monkeypatch.delenv("GALAXY_IGNORE_CONTEXT_MEASUREMENTS", raising=False)
    return tmp_path


def _fix_vram(monkeypatch, free_mb: int):
    monkeypatch.setattr(cs.ComputeScheduler, "read_moe_inputs", staticmethod(lambda profile=None: (free_mb, 64000)))


class TestTheRealContextLimitsAreFilledIn:
    """ "没人填过"就会让那条截断告警**每次开机必响**，而用户无从处置。

    永远响的告警是噪音，而噪音会训练人忽略这个通道 —— 那正好废掉"缺口要说出来"
    这整套立场。
    """

    def test_no_model_is_left_at_the_placeholder_default(self):
        unfilled = [t for t, s in mc._MODELS.items() if not s.max_ctx_val]
        assert not unfilled, f"这些型号还在吃 4096 占位默认，那条截断告警会一直响: {unfilled}"

    def test_the_limits_are_specific_not_copy_pasted(self):
        """五个型号不该是同一个数 —— 那种整齐通常意味着有人一把填了个统一值。"""
        assert len({s.max_ctx() for s in mc._MODELS.values()}) >= 3

    def test_every_model_can_now_hold_what_this_repo_assembles(self):
        """填上真实上限之后，本仓库的装配量对每个型号都装得下了。"""
        demand = ct.assembled_token_demand()
        for tag, spec in mc._MODELS.items():
            assert spec.max_ctx() >= demand, f"{tag} 的上下文({spec.max_ctx()})装不下装配量({demand})"


class TestKvPriceIsMeasuredNotDeclared:
    """那一栏目录里全是 0，于是显存那条分支**一次都没执行过** —— 接了等于没接。"""

    def test_an_unmeasured_model_reports_unknown_not_free(self, isolated_measurements):
        assert cm.effective_kv_mb_per_1k("qwythos-9b-v2") == 0
        assert cm.measured_source("qwythos-9b-v2") == "未知"

    def test_a_measurement_is_recorded_and_wins(self, isolated_measurements):
        assert cm.record_kv_cost("qwythos-9b-v2", n_ctx=10240, kv_mb=1000) == 100
        assert cm.effective_kv_mb_per_1k("qwythos-9b-v2") == 100
        assert cm.measured_source("qwythos-9b-v2") == "实测"

    def test_an_implausible_measurement_is_refused(self, isolated_measurements):
        """噪声值**不记**。一个偏小的单价会让上下文开得过大，加载时 OOM。

        宁可保持"没量过"（= 不敢按显存放开），也不要把噪声写进去当事实。
        """
        assert cm.record_kv_cost("qwythos-9b-v2", n_ctx=10240, kv_mb=-500) is None
        assert cm.record_kv_cost("qwythos-9b-v2", n_ctx=10240, kv_mb=0.0001) is None
        assert cm.effective_kv_mb_per_1k("qwythos-9b-v2") == 0, "不可信的值不该被记下"

    def test_the_record_survives_a_restart(self, isolated_measurements):
        cm.record_kv_cost("qwythos-9b-v2", n_ctx=10240, kv_mb=1000)
        data = json.loads(cm._FILE.read_text(encoding="utf-8"))
        assert data["qwythos-9b-v2"]["kv_mb_per_1k"] == 100

    def test_the_load_path_actually_measures(self):
        """量的地方必须在加载路径上 —— 模型只在那里被加载一次。"""
        import inspect

        import core.local_model_backends as lmb

        src = inspect.getsource(lmb.LlamaCppBackend.load_model)
        assert "_read_free_vram_mb()" in src, "加载前没读显存，没法算差值"
        assert "_record_kv_measurement(" in src, "加载后没记 KV 开销"


class TestDemandIsAFloorNotACeiling:
    """上一轮把装配量当成了天花板 —— 形状反了。"""

    def test_a_roomy_machine_opens_far_above_the_demand(self, isolated_measurements, monkeypatch):
        cm.record_kv_cost("qwythos-9b-v2", n_ctx=10240, kv_mb=1000)  # 100 MB/1K
        _fix_vram(monkeypatch, 24576)
        n_ctx, why = cs.get_compute_scheduler().context_budget_for("qwythos-9b-v2")
        assert n_ctx > ct.assembled_token_demand() * 5, "显存富余却还卡在静态预测值上"
        assert "显存" in why

    def test_it_is_still_capped_by_the_model_itself(self, isolated_measurements, monkeypatch):
        cm.record_kv_cost("openbmb/minicpm-o4.5", n_ctx=8192, kv_mb=400)
        _fix_vram(monkeypatch, 999999)
        n_ctx, _why = cs.get_compute_scheduler().context_budget_for("openbmb/minicpm-o4.5")
        assert n_ctx == mc.exact_model("openbmb/minicpm-o4.5").max_ctx(), "显存无限也不能超过模型自己吃得下的"

    def test_the_million_token_model_can_actually_reach_a_million(self, isolated_measurements, monkeypatch):
        """上一轮 Qwythos 的 1M 上下文是**够不着的** —— 被静态预测封在一万出头。"""
        cm.record_kv_cost("qwythos-9b-v2", n_ctx=10240, kv_mb=1000)
        _fix_vram(monkeypatch, 999999)
        n_ctx, _why = cs.get_compute_scheduler().context_budget_for("qwythos-9b-v2")
        assert n_ctx == 1048576

    def test_without_a_known_price_it_neither_opens_nor_shrinks(self, isolated_measurements, monkeypatch):
        """不知道单价就既不敢往上开、也不敢往下砍 —— 用编出来的分母动真实需求是错的。"""
        _fix_vram(monkeypatch, 24576)
        n_ctx, why = cs.get_compute_scheduler().context_budget_for("qwythos-9b-v2")
        assert n_ctx == max(mc.MIN_CTX, min(ct.assembled_token_demand(), 1048576))
        assert "未知" in why


class TestVramIsAHardPhysicalCeiling:
    """显存撑不住下限时，**下限要让路** —— 否则模型根本加载不起来。"""

    def test_a_tight_machine_gets_what_vram_allows_not_the_floor(self, isolated_measurements, monkeypatch):
        """llama.cpp 会在加载时一次分配整个 KV cache。硬开到下限 = 加载即 OOM。

        拿"装不全"(质量问题)换"加载不了"(可用性问题)，方向是反的。
        """
        cm.record_kv_cost("qwythos-9b-v2", n_ctx=10240, kv_mb=1000)  # 100 MB/1K
        _fix_vram(monkeypatch, 9000)  # 0.8×9000 − 7000 = 200 MB → 约 2048 token
        demand = ct.assembled_token_demand()
        n_ctx, why = cs.get_compute_scheduler().context_budget_for("qwythos-9b-v2")
        assert n_ctx < demand, "显存只够两千 token，却按一万多的下限开 —— 加载会 OOM"
        assert n_ctx >= mc.MIN_CTX
        assert "截断" in why and "加载得起来" in why


class TestTheToolTableIsCountedNotGuessed:
    """``条数 × 180`` 里那个 180 是拍的；工具表其实是可以枚举的。"""

    def test_the_real_table_is_preferred_when_available(self, monkeypatch):
        fake = [{"function": {"name": "x" * 100, "description": "y" * 400, "parameters": {}}} for _ in range(30)]
        monkeypatch.setattr("core.skill_loader.skill_loader.list_as_mcp_tools", lambda: fake)
        assert ct._real_tool_table_tokens() > 0
        assert ct._tool_table_size() == 30

    def test_it_falls_back_instead_of_failing(self, monkeypatch):
        """枚举不到就退回按条数估 —— 拿不到真值不是错误，是退一步。"""

        def boom():
            raise RuntimeError("技能加载器没起来")

        monkeypatch.setattr("core.skill_loader.skill_loader.list_as_mcp_tools", boom)
        assert ct._real_tool_table_tokens() == 0
        assert ct.assembled_token_demand() > 0, "退回估算之后仍要给得出一个数"

    def test_the_conversion_lives_in_one_place(self):
        """字符→token 的换算只此一处，否则迟早在某个调用点上分家。"""
        import inspect

        src = inspect.getsource(ct)
        # 除 count_tokens 自己那一处外，不该再有人直接除这个常数。
        assert src.count("/ _CHARS_PER_TOKEN") == 1

    def test_a_real_tokenizer_is_used_when_one_is_loaded(self, monkeypatch):
        monkeypatch.setattr("core.local_model_backends.tokenize_with_loaded_model", lambda t: 4242)
        assert ct.count_tokens(chars_or_text="随便一段文本") == 4242

    def test_no_model_is_loaded_just_to_count_tokens(self):
        """为了数 token 去加载一个模型是本末倒置 —— 要几十秒、要显存。"""
        import inspect

        import core.local_model_backends as lmb

        src = inspect.getsource(lmb.tokenize_with_loaded_model)
        assert "Llama(" not in src and "load_model" not in src
