#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_clone_to_running_dual_brain.py

钉住"从克隆到使用"这条链上被真机跑出来的四个断点。

这四条不是纸上推演 —— 是把 ``interactive_select`` 放进真 pty 里键入 "3"、把
``llama-server`` 换成一个真在监听的 OpenAI 兼容进程、按真实硬件画像结构喂
``moe_split_from_profile`` 跑出来的。每一条都对应终端上肉眼可见的一个错误结果。

链条：``git clone`` → 装依赖 → 选档 → **两个模型都真的在岗**
"""

from __future__ import annotations

import inspect

import pytest

import core.model_catalog as mc
import core.model_selection as ms


class TestCompositeMainBrainIsDecidedInOnePlace:
    """断点 1：选 C 档，``OLLAMA_MODEL`` 指到了**感知位**。

    ``save_tier`` 里早就修好过一次这条规则（复合档主脑 = 推理位），可
    ``interactive_select._resolve_brain`` 自己又写了一条 "取档内第一个本地模型"，
    再作为**显式** ``main_brain`` 传进去 —— 而显式指定是一律尊重的，于是那条正确
    规则整个被盖掉：

    .. code-block:: text

        _resolve_brain('C') → openbmb/minicpm-o4.5   ← 感知位（source=local）
        save_tier('C')      → qwen3.6:35b-a3b        ← 推理位（source=llama_cpp）

    后果是所有走 ``OLLAMA_MODEL`` 的文本请求全落到感知位上。
    """

    def test_the_composite_tier_main_brain_is_the_reasoning_slot(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("GALAXY_MODEL_TIER", raising=False)
        chosen = mc.save_tier("C")
        reasoning = mc.model_for_role(mc.SLOT_REASONING, "C")
        perception = mc.model_for_role(mc.SLOT_PERCEPTION, "C")
        assert chosen == reasoning
        assert chosen != perception, "主脑指到了感知位 —— 文本请求会全落在它身上"

    def test_running_the_selector_on_the_composite_tier_persists_the_reasoning_slot(self, tmp_path, monkeypatch):
        """真跑一遍选档，看**落盘的**是哪一位 —— 上一条只验了 ``save_tier`` 自己。

        这条才是用户看得到的那个结果。真机上用 pty 键入 "3" 复现过：

        .. code-block:: text

            interactive_select() → openbmb/minicpm-o4.5   ← 修之前
            interactive_select() → qwen3.6:35b-a3b        ← 修之后
        """
        monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("GALAXY_MODEL_TIER", raising=False)
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        # 非交互路会用推荐档；把推荐钉在 C 上，走的仍是同一个 _commit
        monkeypatch.setattr(ms, "recommend_tier", lambda *a, **k: "C")
        monkeypatch.setattr(ms.sys, "stdin", None)  # 非 tty → 不阻塞在 input()

        got = ms.interactive_select()
        assert got == mc.model_for_role(mc.SLOT_REASONING, "C")
        assert got != mc.model_for_role(mc.SLOT_PERCEPTION, "C")
        assert mc.main_brain() == got, "返回值和落盘记录不一致"
        assert mc.perception_brain() == mc.model_for_role(mc.SLOT_PERCEPTION, "C"), "感知位没被独立记住"

    def test_the_selector_defers_instead_of_deciding(self):
        """``_resolve_brain`` 对 composite 必须返回 None（= 我不发表意见）。

        返回一个 tag 就等于把 ``save_tier`` 的规则盖掉，无论那个 tag 对不对。
        """
        src = inspect.getsource(ms.interactive_select)
        assert "return local[0].tag  # composite" not in src, "档内又自己给复合档定了主脑"
        assert 'if tier is not None and tier.kind != "single"' in src
        assert "main_brain=_resolve_brain(tier_key)" in src

    def test_it_returns_what_was_actually_persisted(self):
        """返回值必须来自 ``save_tier``，不是传进去的那个入参。

        两者在复合档上本来就不该相同；返回入参 = 调用方拿到一个和记录不一致的 tag。
        """
        src = inspect.getsource(ms.interactive_select)
        assert "brain = mc.save_tier(" in src
        assert "return brain" in src


class TestTheRecommenderKnowsEveryTier:
    """断点 2：``recommend_tier`` 只认识 A 和 B。

    于是无论显卡多大，新装机器都只会被推到 B 档 —— C 档只能靠用户自己在列表里翻到。
    """

    def test_it_does_not_hardcode_a_two_tier_world(self):
        src = inspect.getsource(ms.recommend_tier)
        assert "tier_keys()" in src, "档位清单又写死在推荐器里了"

    def test_a_big_gpu_with_a_capable_runtime_gets_the_dual_tier(self, monkeypatch):
        monkeypatch.setattr("core.runtime_readiness.tier_is_runnable", lambda key: True)
        need = mc.tier_runtime_footprint_mb("C")
        assert ms.recommend_tier(True, need + 1000) == "C"

    def test_it_never_recommends_a_tier_this_machine_cannot_run(self, monkeypatch):
        """装得下 ≠ 跑得起来。

        C 档推理位要 ``llama-cpp-python`` **且**要它做得到专家卸载。缺任何一条还推 C，
        就是把失败推迟到加载时 —— 而加载失败是被捕获、只写日志的，用户看到的会是
        "模型带不动"，不是"你还缺个依赖"。
        """
        monkeypatch.setattr("core.runtime_readiness.tier_is_runnable", lambda key: key != "C")
        need = mc.tier_runtime_footprint_mb("C")
        assert ms.recommend_tier(True, need + 100000) == "B"

    def test_a_small_gpu_is_not_pushed_into_the_dual_tier(self, monkeypatch):
        monkeypatch.setattr("core.runtime_readiness.tier_is_runnable", lambda key: True)
        assert ms.recommend_tier(True, 7000) == "A"

    def test_no_gpu_is_always_the_light_tier(self, monkeypatch):
        monkeypatch.setattr("core.runtime_readiness.tier_is_runnable", lambda key: True)
        assert ms.recommend_tier(False, 999999) == "A"


class TestTheFootprintIsPerSlotAndSummed:
    """复合档的几位是**同时**在岗的，门槛得求和，而且按驻留量不是权重量。"""

    def test_a_composite_tier_sums_its_slots(self):
        c = mc.tier_runtime_footprint_mb("C")
        parts = [mc.get_model(t).runtime_mb() for t in mc.active_tags("C")]
        assert len(parts) >= 2, "C 档应当有两位同时在岗"
        assert c == sum(parts)

    def test_it_counts_the_selected_candidate_not_the_whole_roster(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("GALAXY_MODEL_TIER", "C")
        monkeypatch.setenv("GALAXY_PERCEPTION_MODEL", "gemma4:e2b")
        light = mc.tier_runtime_footprint_mb("C")
        monkeypatch.setenv("GALAXY_PERCEPTION_MODEL", "openbmb/minicpm-o4.5")
        heavy = mc.tier_runtime_footprint_mb("C")
        assert light < heavy, "换了个更小的感知位，档位门槛却没变 —— 说明按全体候选算的"

    def test_it_uses_runtime_not_weights(self):
        """MiniCPM-o 4.5 权重 6 GB、跑起来 11 GB。拿权重当门槛会推荐一个必 OOM 的档。"""
        spec = mc.get_model("openbmb/minicpm-o4.5")
        assert spec.runtime_mb() > spec.size_mb()
        assert mc.tier_runtime_footprint_mb("B") == spec.runtime_mb()


class TestMissingRuntimeIsSaidOutLoudAtStartup:
    """断点 3：缺口只在两个 HTTP 端点的响应里回。

    可第一次装完还没进面板，往后每次开机也不进面板 —— 选过一次 C 档之后，推理位
    每次都加载失败、每次都只写一行 DEBUG 日志，终端上一个字都没有。
    """

    def test_the_selection_path_prints_them(self):
        assert "print_runtime_gaps(tier_key)" in inspect.getsource(ms.interactive_select)

    @pytest.mark.parametrize("path", ["env_model", "saved"])
    def test_every_startup_path_prints_them(self, path):
        """env / 已保存这两条路**跳过选档界面**，也就是第一次之后的每一次启动。"""
        src = inspect.getsource(ms.resolve_main_brain)
        assert src.count("print_runtime_gaps(") >= 3, "有启动路径漏了缺口报告"

    def test_it_prints_nothing_when_there_is_nothing_to_say(self, monkeypatch, capsys):
        monkeypatch.setattr("core.runtime_readiness.slot_runtime_gaps", lambda key: [])
        assert ms.print_runtime_gaps("A") == []
        assert capsys.readouterr().out == "", "没缺口却打了东西 —— 每次开机都要吓一跳"

    def test_it_prints_the_detail_that_says_what_to_do(self, monkeypatch, capsys):
        gap = {"kind": "backend_missing", "tag": "x:1", "detail": "装法: pip install foo"}
        monkeypatch.setattr("core.runtime_readiness.slot_runtime_gaps", lambda key: [gap])
        out_gaps = ms.print_runtime_gaps("C")
        out = capsys.readouterr().out
        assert out_gaps == [gap]
        assert "backend_missing" in out and "pip install foo" in out

    def test_a_broken_probe_never_blocks_startup(self, monkeypatch):
        monkeypatch.setattr(
            "core.runtime_readiness.slot_runtime_gaps",
            lambda key: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        with pytest.raises(RuntimeError):
            import core.runtime_readiness as rr

            rr.slot_runtime_gaps("C")
        # 但选档路必须扛住它
        assert ms.print_runtime_gaps("C") == []


class TestTheProfileIsReadInOnePlace:
    """断点 4：``--n-cpu-moe`` 的 N 算不出来，报"这台机器拆不动"。

    真因是取数取错了字段 —— 而这两个字段的位置都不直观：

    ============================  ==========================================
    要的东西                      真实位置
    ============================  ==========================================
    可用显存                      ``profile.gpus[i].free_vram_mb``，取 free 最大那块
    可用内存                      ``profile.cpu.available_ram_mb`` —— **挂在 cpu 上**
    ============================  ==========================================

    从画像顶层读 ``available_ram_mb`` 恒得 0（顶层压根没这个字段），于是
    ``_split_moe`` 的判据 3 恒不通过，**任何机器都返回 None**。表现是"专家卸载在这台
    机器上拆不动"，而不是"我读错了字段"。
    """

    @staticmethod
    def _profile(free_vram_list, avail_ram):
        class _G:
            def __init__(self, i, free):
                self.index, self.free_vram_mb, self.total_vram_mb = i, free, free

        class _C:
            available_ram_mb = avail_ram

        class _P:
            gpus = [_G(i, f) for i, f in enumerate(free_vram_list)]
            cpu = _C()

        return _P()

    def test_it_reads_free_vram_from_the_roomiest_card(self):
        from core.compute_scheduler import ComputeScheduler

        s = ComputeScheduler()
        one = s.moe_split_from_profile(18000, self._profile([20000], 32000))
        two = s.moe_split_from_profile(18000, self._profile([1000, 20000], 32000))
        assert one is not None and one == two, "多卡时没挑显存最空的那块"

    def test_it_reads_ram_from_the_cpu_section(self):
        from core.compute_scheduler import ComputeScheduler

        s = ComputeScheduler()
        assert s.moe_split_from_profile(18000, self._profile([8000], 32000)) is not None
        assert s.moe_split_from_profile(18000, self._profile([8000], 2000)) is None, "内存兜不住却放行了"

    def test_the_scheduler_and_the_setup_script_share_the_reader(self):
        """加载时的 N 和命令行上给的 N 必须是同一个数，否则显存账两处对不上。"""
        import scripts.setup_reasoning_slot as srs
        from core.compute_scheduler import ComputeScheduler

        assert "moe_split_from_profile" in inspect.getsource(ComputeScheduler._schedule_model_locked)
        assert "moe_split_from_profile" in inspect.getsource(srs.compute_n_cpu_moe)
        assert "_split_moe(" not in inspect.getsource(srs.compute_n_cpu_moe), "脚本绕过取数那层自己调了算法"

    def test_no_gpu_means_no_split(self):
        from core.compute_scheduler import ComputeScheduler

        assert ComputeScheduler().moe_split_from_profile(18000, self._profile([], 32000)) is None


class TestTheWeightsCanBeFetchedWithoutOllama:
    """C 档推理位根本不走 Ollama —— 它要的只是一个 GGUF 文件路径。

    ``download_and_import_to_ollama`` 的终点是 ``ollama create``，所以它开头就
    ``if not shutil.which("ollama"): return None``。用那个函数去拿推理位权重，一台没装
    Ollama 的机器会在第一行静默返回 None，而它其实完全下得动。
    """

    def test_the_download_only_path_does_not_require_ollama(self, monkeypatch):
        import core.hf_ollama_import_fallback as hf

        monkeypatch.setattr(hf.shutil, "which", lambda name: None)  # 没装 ollama
        seen = {}

        def _dl(repo_id, filename, local_dir):
            seen["repo"], seen["file"] = repo_id, filename
            return f"{local_dir}/{filename}"

        got = hf.download_gguf(
            "qwen3.6:35b-a3b",
            candidates=["fake/repo"],
            size_budget_mb=19800,
            find_gguf_file_fn=lambda repo, size_budget_mb: "Q4_K_M.gguf",
            hf_hub_download_fn=_dl,
        )
        assert got and got.endswith("Q4_K_M.gguf")
        assert seen["repo"] == "fake/repo"

    def test_both_download_paths_land_in_the_same_tree(self):
        """同一份 18 GB 权重不能被下两遍，清理脚本也只认得一棵树。"""
        import core.hf_ollama_import_fallback as hf

        src = inspect.getsource(hf.download_and_import_to_ollama)
        assert "gguf_cache_dir(" in src, "Ollama 那条路又自己拼了一次下载目录"
        assert "hf_gguf_cache" not in src, "路径字面量还留在调用点上"

    def test_the_budget_comes_from_the_catalog_weight(self):
        """固定 6000 的预算会**静默**降到最小量化档（绕过 prefer_quant），比失败更难查。"""
        import core.hf_ollama_import_fallback as hf

        assert hf._size_budget_for("qwen3.6:35b-a3b") > hf.DEFAULT_SIZE_BUDGET_MB


class TestTheSetupScriptIsSourcedFromTheCatalog:
    """脚本不许自带一份模型清单/尺寸 —— 换了推理位它得跟着换。"""

    def test_the_reasoning_slot_comes_from_the_catalog(self):
        import scripts.setup_reasoning_slot as srs

        tag, weight, runtime = srs.reasoning_slot()
        assert tag == mc.model_for_role(mc.SLOT_REASONING, "C")
        assert weight == mc.get_model(tag).size_mb()
        assert runtime == mc.get_model(tag).runtime_mb()

    def test_the_env_keys_match_the_ones_the_router_reads(self):
        """脚本打出来的键名必须就是路由真会读的那几个，错一个字就白配。"""
        import core.multi_llm_router as router
        import scripts.setup_reasoning_slot as srs

        keys = set(srs.env_block("some:tag", 18080))
        src = inspect.getsource(router)
        for k in keys:
            assert k in src, f"{k} 路由根本不读 —— 用户照着配了也不会生效"

    def test_it_does_not_download_and_execute_a_binary(self):
        """本仓明令不做 ``curl | sh`` 式远程脚本执行；下载并执行预编译二进制是同一类事。"""
        import pathlib

        src = pathlib.Path(inspect.getfile(__import__("scripts.setup_reasoning_slot", fromlist=["x"]))).read_text(
            encoding="utf-8"
        )
        body = src.split('"""', 2)[-1]  # 跳过模块 docstring（里面有讲解用的命令示例）
        for bad in ("curl ", "wget ", "urlretrieve"):
            assert bad not in body, f"脚本里出现了 {bad!r} —— 不许替用户下二进制"

    def test_writing_env_updates_in_place_and_keeps_the_rest(self, tmp_path):
        import scripts.setup_reasoning_slot as srs

        env = tmp_path / ".env"
        env.write_text("# 注释\nOPENAI_API_KEY=sk-x\nGALAXY_LOCAL_OPENAI_URL=http://old:1/v1\n", encoding="utf-8")
        srs.write_env(srs.env_block("t:1", 18080), env)
        out = env.read_text(encoding="utf-8")
        assert "# 注释" in out and "OPENAI_API_KEY=sk-x" in out, "写配置把别人的配置搞丢了"
        assert "http://old:1/v1" not in out, "已有的键没被就地更新，成了两条同名"
        assert out.count("GALAXY_LOCAL_OPENAI_URL=") == 1

    def test_the_command_carries_the_offload_flag(self):
        import scripts.setup_reasoning_slot as srs

        cmd = srs.build_command("llama-server", "/w.gguf", 24, 18080)
        assert "--n-cpu-moe" in cmd and cmd[cmd.index("--n-cpu-moe") + 1] == "24"
        # 拆不动时不许瞎填一个数
        assert "--n-cpu-moe" not in srs.build_command("llama-server", "/w.gguf", None, 18080)
