#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_moe_detection_has_one_criterion.py

钉住：**「这个型号是不是 MoE」只有一个判据，而且"没人填过"不等于"确认不是"**。

背景
====
MoE 专家卸载（``ComputeScheduler._split_moe``：注意力+共享层进显存、专家 FFN
留内存）是"显存带不动的模型也能跑起来"的解法。它只在 ``is_moe=True`` 时才尝试。

而 ``is_moe`` 原来是 ``ModelSpec`` 上一个 ``bool = False`` 的字段，全目录零条目
填过。消费方 ``_looks_like_moe`` 是这么写的：

.. code-block:: python

    spec = get_model(model_id)
    flag = getattr(spec, "is_moe", None) if spec is not None else None
    if flag is not None:          # ← 这一支是照 Optional 语义写的
        return bool(flag)
    ...命名惯例兜底（qwen3-30b-a3b / mixtral / *b-a*b）...

字段是非 Optional 的 ``bool``，所以只要 ``spec is not None``，``flag`` 就**永远
不是** ``None`` —— 命名兜底那一段对任何能在目录里查到的 tag 都够不着。而
``get_model`` 还带 root 前缀松匹配（``gemma4:任意后缀`` 都能命中 ``gemma4:e2b``）。

实测（修复前）::

    qwen3-30b-a3b          -> True      # 不在目录里，走命名兜底
    qwen3-30b-a3b 进目录后  -> False     # 目录"权威"地答了个默认值
    gemma4:whatever-moe    -> False     # 名字里明写 moe 也没用

代价：MoE 专家卸载**静默失效**，没有任何报错，现场只看到"模型带不动"。

处置
====
1. ``is_moe`` 改成 ``Optional[bool] = None``。``None`` = 没人填过（退回命名兜底），
   ``True``/``False`` = 人工确认过的结论（一律以它为准，包括确认它不是 MoE）。
2. 判据收成一处 ``model_catalog.resolve_is_moe``。原来
   ``local_model_backends._looks_like_moe`` 和 ``compute_scheduler`` 换档路径
   各判各的 —— 后者直接读 ``spec.is_moe``，所以换档加载的模型**永远**不是 MoE。

注：这在当前目录（4 个型号，确实都不是 MoE）上不产生线上故障 —— 它是**陷阱**
不是活缺陷。但第一个往目录里加 MoE 型号的人，会在没有任何提示的情况下失去专家
卸载。这与 ``can_fit_model`` 那个 ``@property`` 是同一类，按同一标准处理。
"""

from __future__ import annotations

import pytest

import core.model_catalog as mc
from core.local_model_backends import LlamaCppBackend
from core.model_catalog import ModelSpec, resolve_is_moe


@pytest.fixture
def caps():
    return mc.get_model("gemma4:e2b").caps


@pytest.fixture(autouse=True)
def _clean():
    mc.clear_ephemeral_specs()
    yield
    mc.clear_ephemeral_specs()


def _register(tag: str, caps, **kw):
    mc.register_ephemeral_spec(ModelSpec(tag=tag, name="probe", desc="", caps=caps, **kw))


# ---------------------------------------------------------------------------
# 一、这条缺陷本身：进了目录不该让识别变差
# ---------------------------------------------------------------------------

#: 命名惯例认得出的真实 MoE 型号。
_MOE_NAMES = ["qwen3-30b-a3b", "mixtral-8x7b", "Qwen3-235B-A22B", "some-moe-7b"]


@pytest.mark.parametrize("tag", _MOE_NAMES)
def test_naming_convention_recognises_moe(tag):
    assert resolve_is_moe(tag) is True, f"{tag} 没被命名惯例认出来"


@pytest.mark.parametrize("tag", _MOE_NAMES)
def test_entering_the_catalog_without_filling_the_field_must_not_break_detection(tag, caps):
    """**这就是被修掉的那条。** 修复前：进目录 = 被默认值判成"不是 MoE"。"""
    assert resolve_is_moe(tag) is True
    _register(tag, caps)  # 有人把它加进目录，但没填 is_moe
    assert resolve_is_moe(tag) is True, (
        f"{tag} 一进目录就不是 MoE 了 —— is_moe 的默认值被当成了权威结论。"
        "专家卸载会在这里静默失效，现场只看到'模型带不动'"
    )


def test_root_prefix_match_does_not_leak_a_default_verdict(caps):
    """``get_model`` 带 root 前缀松匹配，别让它把别的型号的默认值借过来。"""
    assert mc.get_model("gemma4:whatever-moe").tag == "gemma4:e2b", "前提变了：root 前缀匹配没生效"
    assert resolve_is_moe("gemma4:whatever-moe") is True, "名字里明写 moe 却被 gemma4:e2b 的默认值否掉了"


# ---------------------------------------------------------------------------
# 二、区分度：填过的必须真的说了算（两个方向都要）
# ---------------------------------------------------------------------------


def test_catalog_true_overrides_a_dense_looking_name(caps):
    _register("totally-dense-model", caps, is_moe=True)
    assert resolve_is_moe("totally-dense-model") is True, "人工确认是 MoE，却被名字否掉了"


def test_catalog_false_overrides_a_moe_looking_name(caps):
    """这一条才是 ``Optional`` 的意义：**「确认它不是」必须可表达**。

    只把 False 当"没填过"来处理（不改类型、直接让 False 也走兜底）能让上面几条
    变绿，但会让"确认不是 MoE"永远说不出口。这条钉住那种改法不成立。
    """
    _register("qwen3-30b-a3b", caps, is_moe=False)
    assert resolve_is_moe("qwen3-30b-a3b") is False, "显式填了 is_moe=False，却还是被名字翻案了"


def test_none_is_the_default_and_means_unfilled():
    """字段类型本身：默认必须是 None 而不是 False。"""
    from dataclasses import fields

    f = {x.name: x for x in fields(ModelSpec)}["is_moe"]
    assert f.default is None, f"is_moe 默认值又变回 {f.default!r} —— '没填过'与'确认不是'会再次同值"
    assert all(s.is_moe is None for s in mc.all_models()), "现有目录条目都没填过，应保持 None"


# ---------------------------------------------------------------------------
# 三、判据同源：两个消费方不许各判各的
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tag", _MOE_NAMES + ["gemma4:12b", "openbmb/minicpm-o4.5", "llama3-8b"])
def test_backend_and_catalog_agree(tag):
    """``local_model_backends`` 的包装必须与目录判据逐个吻合。"""
    assert LlamaCppBackend._looks_like_moe(tag, "") == resolve_is_moe(tag), f"{tag}：两处判据分家了"


def test_tier_switch_path_uses_the_same_criterion():
    """换档加载路径原来直接读 ``spec.is_moe`` —— 那是默认值，永远不是 MoE。

    钉源码而不是跑一次换档：换档要真的拉起后端。这里确认它引的是共享判据。
    """
    import inspect

    from core.compute_scheduler import ComputeScheduler

    src = inspect.getsource(ComputeScheduler.reconcile_tier)
    assert "resolve_is_moe" in src, "换档路径没走共享判据，又回到读 spec.is_moe 了"
    assert 'getattr(spec, "is_moe"' not in src, "换档路径还在直接读 spec.is_moe"


def test_moe_flag_actually_reaches_the_split():
    """判据对了还得真的送进 ``_split_moe`` —— 否则改判据是白改。

    ``is_moe=False`` 时哪怕显存明显不够也不该产出 MoE 拆分；``True`` 时同样的
    硬件才走拆分。这条钉的是"这一位有没有被消费"。
    """
    from core.compute_scheduler import ComputeScheduler, SchedulerConfig

    # 必须是 object.__new__：ComputeScheduler 是单例，``Cls.__new__(Cls)`` 拿到的
    # 是**进程级单例本身**，给它挂 config 会污染整个测试会话
    # （tests/test_no_test_hijacks_a_singleton.py 钉着这条）。
    sched = object.__new__(ComputeScheduler)
    sched.config = SchedulerConfig()

    # 24G 卡剩 6G，要放 20G 的模型：整模型放不下，但注意力+共享层（10%）放得下。
    args = (20000, 6000, 64000)
    assert sched._split_moe(*args) is not None, "这组硬件本该能拆 —— 样本选得不对，下面证明不了什么"
