#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_the_last_guessed_constants_are_measured.py

钉住上下文这条链上**最后三个没有依据的数**。

前两轮把 ``n_ctx = 4096`` 换成推导值、又把推导值的形状改对(装配量是下限不是上限)。
剩下三处仍然是"拍的"，而且各有各的坏法：

1. ``_TOKENS_BASELINE = 2048`` 把**两件性质不同的东西**压成了一个数 —— 一半是
   可以量到的事实(系统头就在那儿)，一半是量不到的政策(给回复留多少)。捆在一起的
   后果是**可量的那一半也永远量不到**；
2. ``size_mb_val`` 记的是"某一档量化下"的体积，而目录里没有地方写"哪一档" ——
   用户换成 Q8_0，准入判"放得下"、加载到一半 OOM，而报错在加载途中不在准入处；
3. ``count_tokens`` 只在**模型已加载**时用得上真 tokenizer，可决定 ``n_ctx`` 恰恰
   发生在加载**之前** —— 于是"用真 tokenizer"在最需要它的那一刻永远不生效。

三条的解法是同一个形状：**能量到的就去量，量不到的就明说是政策。**
"""

from __future__ import annotations

import json

import pytest

import core.compute_scheduler as cs
import core.context_compaction as cc
import core.context_measurements as cm
import core.context_trim as ct
import core.local_model_backends as lmb
import core.model_catalog as mc


@pytest.fixture
def isolated_measurements(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "_FILE", tmp_path / "context_measurements.json")
    monkeypatch.setattr(cc, "_ANCHOR_FILE", tmp_path / "context_anchors.json")
    monkeypatch.delenv("GALAXY_IGNORE_CONTEXT_MEASUREMENTS", raising=False)
    monkeypatch.delenv("GALAXY_MAX_TOKENS_ANSWER", raising=False)
    return tmp_path


def _session(head_chars: int = 400, rounds: int = 20, body_chars: int = 800):
    msgs = [{"role": "system", "content": "系" * head_chars}]
    for i in range(rounds):
        msgs.append({"role": "user", "content": f"第{i}轮" + "问" * body_chars})
        msgs.append({"role": "assistant", "content": f"第{i}答" + "答" * body_chars})
    return msgs


# ───────────────────────── ① 基线拆成"事实 + 政策" ─────────────────────────


class TestTheBaselineIsSplitIntoFactAndPolicy:
    """一个盖着两件事的常数，等于两件事都说不清。"""

    def test_the_lumped_constant_is_gone(self):
        assert not hasattr(ct, "_TOKENS_BASELINE"), "又把可量的事实和拍死的政策捆回一个数里了"
        assert hasattr(ct, "_TOKENS_SYSTEM_HEAD_FALLBACK") and hasattr(ct, "_TOKENS_REPLY_HEADROOM_DEFAULT")

    def test_the_policy_half_follows_the_config_that_already_governs_it(self, isolated_measurements, monkeypatch):
        """回复留白量不到，但也**不必新拍** —— GALAXY_MAX_TOKENS_ANSWER 已经在管同一件事。"""
        before = ct.assembled_token_demand()
        monkeypatch.setenv("GALAXY_MAX_TOKENS_ANSWER", str(ct._TOKENS_REPLY_HEADROOM_DEFAULT + 8000))
        assert ct.assembled_token_demand() == before + 8000, "调大了回复上限，窗口却没跟着留位置"

    def test_the_fact_half_is_measured_and_beats_the_fallback(self, isolated_measurements):
        assert ct._system_head_tokens() == ct._TOKENS_SYSTEM_HEAD_FALLBACK, "没量过时该走兜底"
        cm.record_system_head_tokens(9000)
        assert ct._system_head_tokens() == 9000, "量到了却还在用兜底常数"

    def test_an_unmeasured_head_is_unknown_not_free(self, isolated_measurements):
        assert cm.system_head_tokens() == 0
        assert cm.record_system_head_tokens(0) is None
        assert cm.record_system_head_tokens(10**9) is None, "六万 token 以上的系统头是别的问题，不该当基线记下"

    def test_the_record_survives_a_restart(self, isolated_measurements):
        cm.record_system_head_tokens(3210)
        assert json.loads(cm._FILE.read_text(encoding="utf-8"))[cm._SYSTEM_HEAD_KEY]["tokens"] == 3210


class TestItMeasuresTheHeadNotTheWholeAssembly:
    """**这条是本文件里最要紧的一条。**

    "把实际装配量记回去当下一次的需求"听起来最自然，但它是个会自己塌掉的闭环：
    KV 单价未知时 ``n_ctx`` 就等于装配需求，而压缩层会把实际占用压到窗口的七成 ——
    于是实测必然小于上次的需求，记回去，**每重启一次窗口缩三成**，几次之后塌到
    ``MIN_CTX``，而全程没有任何一条错误。

    所以只记**不受 n_ctx 反向约束**的那一段：系统头。它既不被压缩层碰、也不被
    context_trim 裁。
    """

    def test_it_measures_only_the_head_not_the_history(self, isolated_measurements):
        msgs = _session(head_chars=400, rounds=20, body_chars=800)
        head_only = cc.observe_system_head(msgs)
        whole = cc.estimate_tokens(msgs)
        assert 0 < head_only < whole / 10, f"量到了 {head_only}，而整段是 {whole} —— 这不是系统头，是把历史也算进去了"

    def test_the_anchor_summary_does_not_count_as_head(self, isolated_measurements):
        """摘要是压缩自己的产物。把它算进"这套部署的系统头有多长"就成了自己量自己。"""
        msgs = _session()
        plain = cc.observe_system_head(msgs)
        msgs.insert(1, {"role": "system", "content": f"{cc.ANCHOR_MARKER}\n" + "摘" * 4000})
        assert cc.observe_system_head(msgs) == plain, "摘要被算进系统头了 —— 那会随压缩次数越滚越大"

    def test_repeated_compaction_never_shrinks_the_demand(self, isolated_measurements):
        """降级棘轮的回归测试：压几轮之后，下一次开的窗口不该比这次小。"""
        msgs = _session()
        cc.observe_system_head(msgs)
        first = ct.assembled_token_demand()
        for _ in range(5):
            cc.compact_messages(msgs, lambda prior, fresh: (prior or "") + "|摘要", session_id="s")
            cc.observe_system_head(msgs)
            msgs += [{"role": "user", "content": "又一轮" * 300} for _ in range(10)]
        assert ct.assembled_token_demand() >= first, "压了几轮之后装配下限反而变小了 —— 这就是那个会塌掉的闭环"

    def test_the_record_is_a_high_water_mark(self, isolated_measurements):
        """估少了是静默截断，估多了只是多开一点上下文 —— 方向性后果不对称。"""
        cm.record_system_head_tokens(5000)
        assert cm.record_system_head_tokens(1000) == 5000
        assert cm.system_head_tokens() == 5000

    def test_it_is_wired_before_the_compaction_check(self):
        """挂在 should_compact 后面等于绝大多数部署永远量不到 —— 压缩只在长会话里触发。"""
        import inspect

        import core.openclawd as oc

        src = inspect.getsource(oc.OpenClawd._compact_context_if_needed)
        assert "observe_system_head" in src, "系统头没人量"
        assert src.index("observe_system_head") < src.index("should_compact")


# ─────────────────── ② 权重体积：磁盘上的真文件压过量化假设 ───────────────────


def _fake_weights(tmp_path, monkeypatch, tag: str, mb: int):
    p = tmp_path / f"{tag.replace('/', '--')}.gguf"
    with open(p, "wb") as f:
        f.truncate(mb * 1024 * 1024)
    monkeypatch.setattr(lmb, "resolve_gguf_path", lambda t, _p=str(p), _tag=tag: _p if t == _tag else None)
    mc._warned_weight_divergence.clear()
    return p


class TestTheWeightOnDiskBeatsTheQuantAssumption:
    """``size_mb_val`` 底下压着一句注释里的"按 Q4_K_M 记"，而目录里没地方写"哪一档"。"""

    def test_it_falls_back_to_the_catalog_when_not_downloaded(self, monkeypatch):
        monkeypatch.setattr(lmb, "resolve_gguf_path", lambda t: None)
        assert mc.effective_weight_mb("qwythos-9b-v2") == mc.exact_model("qwythos-9b-v2").size_mb()

    def test_the_real_file_wins_when_it_is_there(self, tmp_path, monkeypatch):
        _fake_weights(tmp_path, monkeypatch, "qwythos-9b-v2", 9500)
        assert mc.effective_weight_mb("qwythos-9b-v2") == 9500

    def test_a_quantization_mismatch_is_said_out_loud(self, tmp_path, monkeypatch, caplog):
        """差值本身就是"你换过量化"这条信息 —— 默默换掉等于把它咽了。"""
        _fake_weights(tmp_path, monkeypatch, "qwythos-9b-v2", 9500)
        with caplog.at_level("WARNING"):
            mc.effective_weight_mb("qwythos-9b-v2")
        assert any("量化" in r.message for r in caplog.records)

    def test_it_does_not_cry_wolf_on_a_few_percent(self, tmp_path, monkeypatch, caplog):
        """GGUF 头部与对齐填充带来百分之几的出入，报出来就成噪音。"""
        declared = mc.exact_model("qwythos-9b-v2").size_mb()
        _fake_weights(tmp_path, monkeypatch, "qwythos-9b-v2", int(declared * 1.05))
        with caplog.at_level("WARNING"):
            mc.effective_weight_mb("qwythos-9b-v2")
        assert not [r for r in caplog.records if "量化" in r.message]

    def test_the_admission_footprint_uses_it(self, tmp_path, monkeypatch):
        """接了但没人用等于没接：悲观那一头正是"按整权重要显存"的估计。"""
        before = mc.tier_runtime_footprint_range_mb("D")
        _fake_weights(tmp_path, monkeypatch, "qwythos-9b-v2", 9500)
        after = mc.tier_runtime_footprint_range_mb("D")
        assert after[1] > before[1], "换了量化，档级悲观门槛却一动不动"
        assert after[0] == before[0], "乐观那一头问的是驻留量，不该跟着权重变"


# ────────────────── ③ 加载之前就能数真 token（只读词表） ──────────────────


class TestARealTokenizerIsReachableBeforeTheModelLoads:
    """鸡生蛋：决定 ``n_ctx`` 在加载之前，而"用真 tokenizer"要求模型已加载。"""

    def test_the_estimate_is_only_the_third_choice(self, monkeypatch):
        monkeypatch.setattr(lmb, "tokenize_with_loaded_model", lambda t: 0)
        monkeypatch.setattr(lmb, "tokenize_with_vocab_only", lambda t, tag: 777)
        assert ct.count_tokens("随便一段文本", "some-tag") == 777

    def test_a_loaded_model_still_wins_over_opening_a_vocab(self, monkeypatch):
        monkeypatch.setattr(lmb, "tokenize_with_loaded_model", lambda t: 4242)
        monkeypatch.setattr(lmb, "tokenize_with_vocab_only", lambda t, tag: pytest.fail("手上有现成的还去开词表"))
        assert ct.count_tokens("随便一段文本", "some-tag") == 4242

    def test_without_a_tag_it_never_opens_anything(self, monkeypatch):
        """不知道该开谁的词表就别开 —— 退回折算，不是去挑一个。"""
        monkeypatch.setattr(lmb, "tokenize_with_loaded_model", lambda t: 0)
        monkeypatch.setattr(lmb, "tokenize_with_vocab_only", lambda t, tag: pytest.fail("没给 tag 却开了词表"))
        assert ct.count_tokens("随便一段文本") == int(len("随便一段文本") / ct._CHARS_PER_TOKEN)

    def test_a_model_that_cannot_be_opened_is_not_retried_forever(self, monkeypatch):
        """负缓存和正缓存一样要紧：没有它，开不出来的型号每次数 token 都要重试一遍。"""
        monkeypatch.setattr(lmb, "_VOCAB_ONLY", {})
        monkeypatch.setattr(lmb, "resolve_gguf_path", lambda t: None)
        assert lmb.tokenize_with_vocab_only("文本", "nope") == 0
        assert lmb._VOCAB_ONLY.get("nope") is False

    def test_the_tool_table_is_handed_over_as_text_not_as_a_char_count(self):
        """交字符数等于主动放弃真 tokenizer 那两条路 —— 而工具表是装配量里最大的一块。"""
        import inspect

        src = inspect.getsource(ct._real_tool_table_tokens)
        assert "count_tokens(serialized" in src

    def test_the_scheduler_passes_the_tag_through(self):
        """定 n_ctx 那一刻正是最需要真值的时候：那时必然没有已加载的模型。"""
        import inspect

        src = inspect.getsource(cs.ComputeScheduler.context_budget_for)
        assert "assembled_token_demand(tag)" in src

    def test_it_never_loads_weights_just_to_count(self):
        """只读词表才是可接受的代价；读权重张量不是。"""
        import inspect

        src = inspect.getsource(lmb._vocab_only_tokenizer)
        assert "vocab_only=True" in src


class TestAnUnevaluableDemandFallsBackDownNotUp:
    """接 tag 时发现的一处旧缺陷 —— 顺手修掉的那条。

    装配量算不出来时，原来退回 ``model_cap``。听着像"保守"，其实是**最危险**的
    选择：``demand`` 是**下限**，把它顶到模型上限等于"什么都不知道，所以按最大开"。
    Qwythos 的上限是 1M —— 一次评估失败就会让 llama.cpp 在加载时去分配一个
    一百万 token 的 KV cache，而这条退化只记在 debug 级，现场只看得到一次
    莫名其妙的 OOM。

    这正是本方法自己的注释在说的那件事：拿"装不全"换"加载不了"，方向是反的。
    """

    def test_it_does_not_open_the_maximum_when_it_cannot_tell(self, monkeypatch, caplog):
        def boom(tag=""):
            raise RuntimeError("装配量算不出来")

        monkeypatch.setattr(ct, "assembled_token_demand", boom)
        with caplog.at_level("WARNING"):
            n_ctx, _why = cs.get_compute_scheduler().context_budget_for("qwythos-9b-v2")
        assert n_ctx == mc.MIN_CTX, f"判不了却开到了 {n_ctx} —— 加载时要一次分配这么大的 KV cache"
        assert any("没有按实际需求定" in r.message for r in caplog.records), "这条退化只记在 debug 级就等于没说"
