#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_context_length_follows_reality.py

钉住：**上下文长度按实际定，不是一个常数。**

修的是什么
==========
``LlamaCppBackend.__init__`` 里写着 ``self._n_ctx = 4096``。一个常数，同时冒充了三件
本该分别去问的事，而三个知道答案的人一个都没被问过：

1. **模型能吃多长** —— 目录。Qwythos-9B 能吃 1M，被这个常数封在 4096；
2. **显存还能给 KV cache 多少** —— ``ComputeScheduler``（资源判断的唯一权威）；
3. **这次实际要装多少** —— ``context_trim``。

第 3 条是活着的缺陷：按本仓库**自己配的预算**（``GALAXY_TOOLS_MAX`` 个工具定义 +
``GALAXY_TOOL_PRUNE_KEEP_ROUNDS`` 轮各 ``GALAXY_TOOL_RESULT_MAX_CHARS`` 字符的工具
结果 + 系统提示）算出来是**一万一千多 token**，而分配的是 4096。

**超出的部分在 llama.cpp 那层静默截断** —— 没有异常、没有日志、没有任何一处核对过
这两个数。用户看到的是"它怎么记不住前面说的"，而不是"上下文不够"。

装配端按**字符**裁、分配端按 **token** 分配，中间隔着一个从来没人算过的换算。
"""

from __future__ import annotations

import inspect

import core.compute_scheduler as cs
import core.context_trim as ct
import core.local_model_backends as lmb
import core.model_catalog as mc
import core.model_selection as ms


class TestTheDemandSideIsDerivedNotGuessed:
    """ "需要多长"要从**本仓库自己配的那几个预算**推出来，不是另拍一个数。"""

    def test_it_reads_the_repos_own_budgets(self, monkeypatch):
        base = ct.assembled_token_demand()
        monkeypatch.setenv("GALAXY_TOOLS_MAX", "48")
        assert ct.assembled_token_demand() > base, "工具数翻倍，装配量却没变 —— 没在读真预算"

    def test_more_kept_rounds_means_more_context(self, monkeypatch):
        base = ct.assembled_token_demand()
        monkeypatch.setenv("GALAXY_TOOL_PRUNE_KEEP_ROUNDS", "9")
        assert ct.assembled_token_demand() > base

    def test_the_repo_really_does_assemble_more_than_the_old_constant(self):
        """这条不是造出来的场景 —— 它就是仓库的默认配置。

        默认预算下装配量远超原来写死的 4096。这条一旦转绿变红（装配量掉到 4096 以下），
        说明有人把 context_trim 的预算改小了，那时这个钉子该跟着重估，而不是删掉。
        """
        assert ct.assembled_token_demand() > 4096

    def test_chars_are_converted_to_tokens_conservatively(self):
        """换算分母取小 = 高估 token 数。估多了只是多开一点上下文；估少了是静默截断。"""
        assert ct._CHARS_PER_TOKEN <= 3.0


class TestTheSchedulerOwnsTheDecision:
    """判据在调度器（它同时看目录、实测显存、真实装配量），不在加载器里。"""

    def test_a_model_that_can_take_more_gets_more(self):
        n_ctx, _why = cs.get_compute_scheduler().context_budget_for("qwythos-9b-v2")
        assert n_ctx > 4096, "能吃 1M 的型号仍被按 4096 装"
        assert n_ctx >= ct.assembled_token_demand()

    def test_a_model_is_capped_at_its_own_limit(self, monkeypatch):
        """上限比装配量还小的型号要被自己的上限封顶，并且**说出来**。

        目录里现在每个型号都填了真实上限，且都大于装配量(那正是填它们的收益 ——
        那条截断告警不再每次开机必响)。所以这条改用一个合成型号来验**机制**：
        机制还在，只是现实里暂时没有型号触发它。
        """
        tiny = mc.ModelSpec(
            "tiny-ctx", "上限很小的型号", "", mc.ModelCapability(tools=True), source="llama_cpp", max_ctx_val=4096
        )
        real = mc.exact_model
        monkeypatch.setattr(mc, "exact_model", lambda t: tiny if t == "tiny-ctx" else real(t))
        n_ctx, why = cs.get_compute_scheduler().context_budget_for("tiny-ctx")
        assert n_ctx == 4096
        assert "超过" in why, "被自己的上限卡住了，却没在理由里说出来"

    def test_it_never_goes_below_the_floor(self, monkeypatch):
        """再挤也要装得下系统提示 + 工具表，否则表现是"它什么都记不住"而非"显存不够"。

        断言写死 2048 而**不是**写 ``>= mc.MIN_CTX`` —— 后者是自指的：把 MIN_CTX
        调成 1，那种写法照样绿。下限的值本身就是要钉的东西。
        """
        monkeypatch.setattr(ct, "assembled_token_demand", lambda tag="": 1)
        n_ctx, _why = cs.get_compute_scheduler().context_budget_for("qwythos-9b-v2")
        assert mc.MIN_CTX == 2048, "下限被改了 —— 这是个判据，不是可随手调的旋钮"
        assert n_ctx == 2048

    def test_an_explicit_setting_is_always_respected(self, monkeypatch):
        monkeypatch.setenv("GALAXY_LLAMA_CTX", "65536")
        n_ctx, why = cs.get_compute_scheduler().context_budget_for("gemma4:e2b")
        assert n_ctx == 65536 and "显式指定" in why

    def test_an_unknown_tag_falls_back_instead_of_guessing(self):
        n_ctx, _why = cs.get_compute_scheduler().context_budget_for("nobody/never-heard-of-it")
        assert n_ctx == max(mc.MIN_CTX, min(ct.assembled_token_demand(), mc.DEFAULT_MAX_CTX))

    def test_it_always_says_where_the_number_came_from(self):
        """一个说不出依据的数字，就是下一个"底下压着假设"的常数。"""
        for tag in mc._MODELS:
            _n, why = cs.get_compute_scheduler().context_budget_for(tag)
            assert why and len(why) > 10, f"{tag} 的上下文预算没有理由"

    def test_it_does_not_read_the_hardware_profile_a_second_time(self):
        """取数复用 read_moe_inputs —— 上一轮正是"取数写在调用点上"出过 NameError。"""
        src = inspect.getsource(cs.ComputeScheduler.context_budget_for)
        assert "read_moe_inputs" in src
        assert "get_compute_profile_sync" not in src, "又自己去读了一遍画像"


class TestVramOnlyNarrowsWhenTheCostIsKnown:
    """没量过 KV 单价就不敢拿显存去砍上下文 —— 那等于用一个编出来的分母砍真实需求。"""

    def test_an_unmeasured_model_is_not_narrowed_by_vram(self):
        spec = mc.exact_model("qwythos-9b-v2")
        assert spec.kv_mb_per_1k() == 0, "这条前提变了，本测试要重写"
        n_ctx, why = cs.get_compute_scheduler().context_budget_for("qwythos-9b-v2")
        # 断言的是**语义**(没被显存动过 = 恰好等于装配量)，不是理由串里有没有"显存"
        # 这两个字 —— 那种写法太脆:理由现在会主动说明"KV 单价未知，不敢按显存放开"。
        assert n_ctx == ct.assembled_token_demand()
        assert "未知" in why

    def test_a_measured_model_is_narrowed_when_vram_is_tight(self, monkeypatch):
        """量过单价、且显存不够时，上下文要被压下来 —— 而且要说是被显存压的。"""
        monkeypatch.setattr(cs.ComputeScheduler, "read_moe_inputs", staticmethod(lambda profile=None: (9000, 32000)))
        real = mc.exact_model
        squeezed = mc.ModelSpec(
            "kv-measured",
            "量过 KV 的型号",
            "",
            mc.ModelCapability(tools=True),
            source="llama_cpp",
            size_mb_val=5000,
            runtime_mb_val=7000,
            max_ctx_val=1_000_000,
            kv_mb_per_1k_val=100,
        )
        monkeypatch.setattr(mc, "exact_model", lambda t: squeezed if t == "kv-measured" else real(t))
        n_ctx, why = cs.get_compute_scheduler().context_budget_for("kv-measured")
        # 9000×0.8 − 7000 = 200 MB 给 KV → 200/100×1024 = 2048 token
        assert n_ctx < ct.assembled_token_demand()
        assert "显存" in why


class TestTheLoaderAsksInsteadOfHardcoding:
    """加载器只负责用，不负责定 —— 与 n_gpu_layers 同一个立场。"""

    def test_the_load_path_asks_the_scheduler(self):
        src = inspect.getsource(lmb.LlamaCppBackend)
        assert "context_budget_for" in src, "加载器没问调度器"

    def test_the_constant_is_only_a_fallback_now(self):
        """``self._n_ctx`` 可以留着当兜底，但不能再是 llama_kwargs 的直接取值处。"""
        src = inspect.getsource(lmb.LlamaCppBackend)
        assert '"n_ctx": self._n_ctx' not in src, "又把写死的常数直接塞进加载参数了"
        assert '"n_ctx": n_ctx' in src

    def test_falling_back_is_loud(self):
        """调度器不可用时退回兜底要**响亮** —— 默默按 4096 装正是原来的毛病。"""
        src = inspect.getsource(lmb.LlamaCppBackend)
        assert "logger.warning" in src and "上下文预算不可评估" in src


class TestBothLoadPathsAskTheSameAuthority:
    """两条本地加载路径原来**各拍一个数**，而且都没算过实际装配量。

    - ``LlamaCppBackend``：``n_ctx = 4096``
    - Ollama（``multi_llm_router``）：``num_ctx = 8192``

    Ollama 那条的注释里已经诊断对了病因（"系统提示+工具定义+记忆+历史很容易超过
    模型默认上下文…溢出 → 前缀 KV 缓存全废 → 越聊越慢"），但开的药是一个整数
    8192 —— 而真实装配量是一万一千多，**8192 同样不够**，只是比 4096 好一点。

    同一个判据两处各写各的，错的那处不会有人发现。现在两边都问调度器。
    """

    def test_the_ollama_path_no_longer_hardcodes_its_own_number(self):
        """判据钉在**那段代码**上,不钉在它所在的文件上。

        原来读的是整个 ``core.multi_llm_router`` 模块的源码。2026-09-06 把四条
        适配器拆去 ``core/llm_adapters.py`` 之后,这条当场红了 —— 红的不是它要
        保护的性质(Ollama 仍然问调度器要预算),而是它**顺手编码进去的一个前提**:
        "那段代码在那个文件里"。

        搬家不该让判据失效。所以改成直接问那个类。
        """
        from core.multi_llm_router import OllamaAdapter

        src = inspect.getsource(OllamaAdapter)
        assert "context_budget_for" in src, "Ollama 那条路还在自己拍数"

    def test_the_repo_demand_exceeds_both_old_constants(self):
        """这两个常数当初都是拍的 —— 拿真实装配量一比就知道。"""
        demand = ct.assembled_token_demand()
        assert demand > 4096, "llama.cpp 那条路原来的 4096"
        assert demand > 8192, "Ollama 那条路原来的 8192 —— 同样不够"

    def test_an_explicit_ollama_setting_is_still_respected(self, monkeypatch):
        """显式指定一律尊重：留空才自动定，填了就是用户说了算。"""
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        assert CONFIG_SCHEMA["GALAXY_OLLAMA_NUM_CTX"]["default"] == "", "默认值该留空(=自动)，不是再拍一个数"
        assert CONFIG_SCHEMA["GALAXY_LLAMA_CTX"]["default"] == ""

    def test_both_context_keys_are_reachable_from_the_panel(self):
        """判据接上了但用户改不了，等于没接 —— 面板上要有它们的位置。"""
        import pathlib

        tsx = pathlib.Path("electron/renderer/panel/src/settings_inventory.ts").read_text(encoding="utf-8")
        assert "GALAXY_LLAMA_CTX" in tsx
        assert "GALAXY_OLLAMA_NUM_CTX" in tsx


class TestTheGapIsSaidOutLoud:
    """装不下要说出来；但**不能**说成"跑不起来"。"""

    def test_nothing_is_squeezed_now_that_the_real_limits_are_filled_in(self, capsys):
        """填上真实上限之后，**不该再有型号被挤** —— 那条告警不再每次开机必响。

        永远响的告警是噪音，而噪音会训练人忽略这个通道。这一条钉的就是"它安静了"。
        """
        rows = ms.print_context_budget("B")
        out = capsys.readouterr().out
        assert rows and all(r["n_ctx"] >= r["demand"] for r in rows)
        assert "截断" not in out, "还有型号装不下 —— 去把它的 max_ctx_val 填上"

    def test_a_squeezed_model_would_still_be_reported(self, monkeypatch, capsys):
        """反向：机制还在。上限真的不够时仍要打出来，并指出该填哪一栏。"""
        real = mc.exact_model
        tiny = mc.ModelSpec(
            "tiny-ctx", "上限很小的型号", "", mc.ModelCapability(tools=True), source="llama_cpp", max_ctx_val=4096
        )
        monkeypatch.setattr(mc, "exact_model", lambda t: tiny if t == "tiny-ctx" else real(t))
        monkeypatch.setattr(mc, "active_tags", lambda k="": ["tiny-ctx"])
        ms.print_context_budget("B")
        out = capsys.readouterr().out
        assert "截断" in out and "max_ctx_val" in out

    def test_a_roomy_model_prints_nothing(self, capsys):
        ms.print_context_budget("D")  # D 档推理位能吃 1M
        out = capsys.readouterr().out
        assert "qwythos-9b-v2" not in out, "装得下的那一位不该被报出来"

    def test_it_is_wired_into_every_startup_path(self):
        src = inspect.getsource(ms)
        assert src.count("print_context_budget(") >= 5, "有启动路径漏了上下文预算报告"

    def test_being_squeezed_never_makes_a_tier_unrunnable(self):
        """关键分界：上下文装不下 ≠ 跑不起来。

        ``tier_is_runnable`` 就是 ``not slot_runtime_gaps(...)``。把"上下文不够"塞进
        缺口表，这一档会被判成跑不起来并触发**降档** —— 拿一次质量下降换掉一整个档。
        """
        import core.runtime_readiness as rr

        assert rr.tier_is_runnable("B"), "B 档在岗那位上下文被挤，却被判成跑不起来了"
        kinds = {g.get("kind") for g in rr.slot_runtime_gaps("B")}
        assert not {k for k in kinds if "ctx" in str(k) or "context" in str(k)}


class TestTheDefaultIsPureAddition:
    """没填过 max_ctx_val 的型号，行为与加这一栏之前逐字节一致。"""

    def test_the_default_equals_the_old_hardcoded_value(self):
        assert mc.DEFAULT_MAX_CTX == 4096, "改这个默认值等于替所有没量过的型号做主张"

    def test_every_unfilled_model_still_gets_the_old_number(self):
        for tag, spec in mc._MODELS.items():
            if spec.max_ctx_val:
                continue
            n_ctx, _why = cs.get_compute_scheduler().context_budget_for(tag)
            assert n_ctx == 4096, f"{tag} 没填过上限，上下文却变了"
