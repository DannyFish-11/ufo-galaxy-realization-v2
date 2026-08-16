#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_missing_runtime_is_reported.py

钉住：**某一位的加载运行时没装，必须在换档/换人的响应里说出来。**

背景
====
``local_model_backends.list_available_backends()`` 早就在答"哪个后端的依赖装了"
—— 但换档/换人那条路**从来没问过它**。于是真机上是这样：

1. 用户选 C 档（双模型）；
2. ``reconcile_tier`` 去加载推理位，``LlamaCppBackend.load_model`` 抛
   ``No module named 'llama_cpp'``；
3. 异常被捕获、账本撤销、写一行 WARNING 到日志；
4. **接口返回 success:true，面板上什么都看不到。**

用户以为两个模型都跑起来了，实际只有感知位在岗。这就是"能力装了没人用"的
另一种形态：判据（`list_available_backends`）在，消费方没接。

``llama-cpp-python`` **该**是可选依赖（GB 级、要编译、平台特定，A/B 单模型档
完全用不到），本文件不主张把它改成硬依赖。主张的是：**"可选"的前提是缺了要说**，
而不是默默少跑一个模型。
"""

from __future__ import annotations

import pytest

import core.model_catalog as mc
import core.routes.models as m


class TestTheCriterionIsSingleSourced:
    """``source`` → 后端 这条判据只能有一处。"""

    def test_backend_for_source_covers_every_source_in_the_catalog(self):
        for spec in mc.all_models():
            assert mc.backend_for_source(spec.source), f"{spec.tag} 的 source={spec.source!r} 没有对应后端"

    def test_the_scheduler_asks_the_catalog_not_its_own_conditional(self):
        """原来这条散在 ``reconcile_tier`` 的调用点上，写成一个三元表达式。

        只有一个调用点时看不出问题；一旦别处也要问"这个型号归谁加载"（状态盘就要），
        就会各写各的，然后在某个 source 上分家。
        """
        import inspect

        from core.compute_scheduler import ComputeScheduler

        src = inspect.getsource(ComputeScheduler.reconcile_tier)
        assert '"llama_cpp" if spec.source' not in src, "判据又被就地写回调用点了"
        assert "_backend_for_source(" in src, "换档没走目录那条唯一判据"

    def test_known_sources_map_as_expected(self):
        assert mc.backend_for_tag("gemma4:12b") == "ollama"
        assert mc.backend_for_tag("openbmb/minicpm-o4.5") == "ollama"
        assert mc.backend_for_tag("qwen3.6:35b-a3b") == "llama_cpp"


class TestGapsAreReported:
    def test_a_missing_backend_becomes_an_actionable_gap(self, monkeypatch):
        monkeypatch.setattr(m, "_BACKEND_PIP", {"llama_cpp": "llama-cpp-python"})
        monkeypatch.setattr(
            "core.local_model_backends.list_available_backends",
            lambda: ["ollama"],  # llama_cpp 没装
        )
        gaps = m.slot_runtime_gaps("C")
        assert len(gaps) == 1, f"C 档推理位缺运行时却报了 {len(gaps)} 条"
        g = gaps[0]
        assert g["kind"] == "backend_missing"
        assert g["tag"] == "qwen3.6:35b-a3b"
        assert g["backend"] == "llama_cpp"
        assert g["pip"] == "llama-cpp-python", "没给出装法 —— 用户拿到告警也不知道该干嘛"
        assert "不会上岗" in g["detail"]

    def test_no_gap_when_everything_is_installed(self, monkeypatch):
        monkeypatch.setattr(
            "core.local_model_backends.list_available_backends",
            lambda: ["ollama", "llama_cpp"],
        )
        monkeypatch.setattr("core.local_model_backends.moe_offload_supported", lambda: True)
        assert m.slot_runtime_gaps("C") == []

    def test_single_tiers_need_only_ollama(self, monkeypatch):
        """A/B 档完全用不到 llama_cpp —— 不该因为它没装就对单模型用户报缺口。"""
        monkeypatch.setattr(
            "core.local_model_backends.list_available_backends",
            lambda: ["ollama"],
        )
        assert m.slot_runtime_gaps("A") == []
        assert m.slot_runtime_gaps("B") == []

    def test_it_reports_the_selected_model_not_every_candidate(self, monkeypatch):
        """按 active_tags 算 —— 候选表里没被选中的那几个不该拉进来评估。"""
        monkeypatch.setattr(
            "core.local_model_backends.list_available_backends",
            lambda: ["ollama", "llama_cpp"],
        )
        monkeypatch.setattr("core.local_model_backends.moe_offload_supported", lambda: True)
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        monkeypatch.setenv("GALAXY_PERCEPTION_MODEL", "gemma4:e2b")
        assert m.slot_runtime_gaps("C") == []

    def test_probe_failure_degrades_quietly(self, monkeypatch):
        """评估不了就当没缺口 —— 不许因为探测失败就吓唬用户说"缺依赖"。"""
        monkeypatch.setattr(
            "core.local_model_backends.list_available_backends",
            lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        assert m.slot_runtime_gaps("C") == []


class TestTheEndpointsActuallyCarryIt:
    """能力装了得有人用 —— 报告器写好了，两个接口必须真的把它带回去。"""

    @pytest.mark.parametrize("fn_name", ["select_tier", "select_slot"])
    def test_the_response_includes_runtime_gaps(self, fn_name):
        import inspect

        src = inspect.getsource(getattr(m, fn_name))
        assert "slot_runtime_gaps(" in src, f"{fn_name} 没把运行时缺口带进响应 —— 又只剩日志了"
        assert "runtime_gaps" in src


class TestItIsRegisteredWhereUsersLook:
    def test_llama_cpp_is_in_the_optional_dependency_registry(self):
        """``scripts/check_dependencies.py`` 是用户查"我缺什么"的地方。

        它原来没有这一条 —— llama-cpp-python 只躺在 requirements.txt 的存档注释里，
        而那段注释的前提是"缺了会优雅降级"。C 档之后不再成立：缺了就是少一个模型。
        """
        import importlib.util
        import pathlib

        spec = importlib.util.spec_from_file_location(
            "_chkdeps", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "check_dependencies.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.OPTIONAL_DEPS.get("llama_cpp") == "llama-cpp-python"


class TestAnUnachievablePlacementIsAlsoAGap:
    """后端装了，还得看它**做不做得到目录声称的那种落位**。

    这一条是装上真的 llama-cpp-python 之后才发现的 —— 光看代码看不出来：

    .. code-block:: text

        llama_cpp 0.3.34（PyPI 最新）
        n_cpu_moe      在? False
        override_tensor 在? False
        专家卸载生效? False

    而目录给推理位登记的 ``runtime_mb_val=7300`` **就是按专家卸载生效写的**
    （18 GB 权重 → 7.3 GB 驻留）。卸载做不到时那个数是空头支票：准入按 7.3 GB
    放行，加载时按 18 GB 要显存，8 GB 卡上必炸 —— 而告警只在**加载时**才喊，
    中间隔着一整次加载。
    """

    def test_it_flags_when_offload_is_declared_but_unavailable(self, monkeypatch):
        monkeypatch.setattr(
            "core.local_model_backends.list_available_backends",
            lambda: ["ollama", "llama_cpp"],
        )
        monkeypatch.setattr("core.local_model_backends.moe_offload_supported", lambda: False)
        gaps = [g for g in m.slot_runtime_gaps("C") if g["kind"] == "moe_offload_unavailable"]
        assert len(gaps) == 1, "卸载做不到却没报 —— 用户会拿着 7.3 GB 的账去撞 18 GB 的现实"
        g = gaps[0]
        assert g["declared_runtime_mb"] == 7300
        assert g["actual_runtime_mb"] == 18000, "没说清做不到时到底要多少"
        assert "llama-server" in g["detail"], "没给出可行的替代接法"

    def test_the_capability_probe_reads_the_installed_library(self):
        """判据必须问**装着的那个库**，不是版本号、不是猜。"""
        import inspect

        from core.local_model_backends import moe_offload_supported

        src = inspect.getsource(moe_offload_supported)
        body = src.split('"""')[-1]
        assert "import llama_cpp" in body
        assert "signature" in body, "按签名探测,不按版本号猜 —— 各版本入参不同"
        assert "n_cpu_moe" in body and "override_tensor" in body

    def test_a_non_moe_model_is_never_flagged(self, monkeypatch):
        """只对"声称靠卸载省显存"的型号报 —— 别的型号跟这条无关。"""
        monkeypatch.setattr(
            "core.local_model_backends.list_available_backends",
            lambda: ["ollama", "llama_cpp"],
        )
        monkeypatch.setattr("core.local_model_backends.moe_offload_supported", lambda: False)
        for key in ("A", "B"):
            assert [g for g in m.slot_runtime_gaps(key) if g["kind"] == "moe_offload_unavailable"] == []
