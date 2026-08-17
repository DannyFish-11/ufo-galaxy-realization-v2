#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_unrunnable_tier_degrades_not_just_warns.py

钉住：**跑不起来的档要降下来，不能只喊一嗓子。**

背景
====
上一轮补上了探针：``tier_is_runnable`` 会问 ``moe_offload_supported()``，
``print_runtime_gaps`` 在选档当场和每一条启动路径上都把缺口打到终端。但探针**只
会喊，不会让**：

1. 用户某天选了 C 档，存进记录；
2. 之后换了台机器 / 升级了 ``llama-cpp-python`` / 装的那个版本不透出 ``n_cpu_moe``；
3. 开机 → 终端打一行"C 档有 1 位跑不起来" → **然后照样去加载 C 档**；
4. 推理位按整权重 18 GB 要显存 → 加载抛 → 被 ``reconcile_tier`` 捕获、撤账、
   ``logger.error`` 一行 → 用户拿到的是一个看得见的告警 + 一个看不见的失败。

**探针有、降级路径没有，比两样都没有更糟**：它给人"已经防住了"的错觉。

本文件钉的是第 3 步：跑不起来就降到跑得起来的最高档，且——

* 降级只影响**本进程运行时**（``GALAXY_MODEL_TIER``），**记录一个字都不动**。
  那是用户的意图；机器现在的状态是暂时的，装回缺的依赖重启就该自动回到原档。
* ``OLLAMA_MODEL`` 必须跟着降。留着 C 档推理位的 tag 不管，走它的文本请求会全部
  落到一个这一档根本不加载的模型上 —— 正是上一轮修过的那类错位。
"""

from __future__ import annotations

import json

import pytest

import core.model_catalog as mc
import core.model_selection as ms
import core.runtime_readiness as rr


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """记录文件指到临时目录，三个派生 env 清空 —— 别碰仓库里那份真的。"""
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(mc, "_STATE_FILE", tmp_path / "model_state.json")
    monkeypatch.setattr(mc, "_LEGACY_TIER_FILE", tmp_path / ".galaxy_tier")
    monkeypatch.setattr(mc, "_LEGACY_MODEL_FILE", tmp_path / ".galaxy_model")
    for key in ("GALAXY_MODEL_TIER", "OLLAMA_MODEL", "GALAXY_PERCEPTION_MODEL"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


def _only_c_is_broken(monkeypatch):
    monkeypatch.setattr(rr, "tier_is_runnable", lambda key: key != "C")


class TestTheEffectiveTierFallsBack:
    """``effective_tier`` = 这台机器**现在**跑得起来的那一档。"""

    def test_an_unrunnable_tier_falls_to_the_highest_runnable_one(self, monkeypatch):
        _only_c_is_broken(monkeypatch)
        # 落到 D 而不是 B：D 档推理位是稠密 9B，不欠专家卸载那张票，所以它才是
        # "跑得起来的最高档"。降到 B 会白白丢掉双模型形态。
        assert rr.effective_tier("C") == "D"

    def test_a_runnable_tier_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(rr, "tier_is_runnable", lambda key: True)
        assert rr.effective_tier("C") == "C"

    def test_it_never_upgrades(self, monkeypatch):
        """降级是为了能跑起来，不是替用户改主意往上升。"""
        monkeypatch.setattr(rr, "tier_is_runnable", lambda key: True)
        assert rr.effective_tier("A") == "A"

    def test_when_nothing_runs_it_lands_on_the_lowest_tier(self, monkeypatch):
        monkeypatch.setattr(rr, "tier_is_runnable", lambda key: False)
        assert rr.effective_tier("C") == mc.tier_keys()[0]

    def test_an_unevaluable_probe_does_not_degrade_anything(self, monkeypatch):
        """判不了 ≠ 跑不了。拿一次探测异常去改用户的档，比不改危险得多。"""

        def boom(key):
            raise RuntimeError("探测炸了")

        monkeypatch.setattr(rr, "tier_is_runnable", boom)
        assert rr.effective_tier("C") == "C"

    def test_this_machine_reproduces_it_for_real(self):
        """真机复现：装了 llama-cpp-python、但它不透出 n_cpu_moe 时，C 跑不起来而 D 能跑。

        **两个前提都要显式检查，缺一条就跳过。** 这条钉的是"C 和 D 的差别只在专家
        卸载"，而要看得出这个差别，得先有一台**装了 llama_cpp、只是缺卸载能力**的
        机器：

        * 装了卸载能力 → C 本来就跑得起来，没差别可看；
        * **根本没装 llama_cpp** → C 和 D 的推理位都判 backend_missing，两个都跑不
          起来，同样没差别可看。

        第二条是这条测试最初漏掉的：它只查了 ``moe_offload_supported()``，把"本机装
        了 llama_cpp"当成了不言自明的前提。开发机上装了、CI 上没装，于是本地绿、
        CI 红 —— 断言写的是"D 不该受卸载缺失影响"，CI 上 D 挂掉的真实原因却是
        整个后端没装，跟卸载一点关系没有。**测试把自己那台机器的环境当成了普遍前提。**
        """
        from core.local_model_backends import list_available_backends, moe_offload_supported

        if "llama_cpp" not in list_available_backends():
            pytest.skip("本机没装 llama-cpp-python —— 两个推理位都跑不起来，这条区分不出 C 与 D")
        if moe_offload_supported():
            pytest.skip("本机支持专家卸载，C 档本来就跑得起来")
        assert not rr.tier_is_runnable("C")
        assert rr.tier_is_runnable("D"), "D 档不该受专家卸载缺失影响"
        assert rr.effective_tier("C") == "D"


class TestDegradingDoesNotRewriteTheRecord:
    """降级只改运行时。用户存的还是他选的那一档。"""

    def test_the_runtime_tier_drops_but_the_file_does_not(self, isolated, monkeypatch):
        mc.save_tier("C")
        before = json.loads(mc._STATE_FILE.read_text(encoding="utf-8"))
        assert before["tier"] == "C"
        for key in ("GALAXY_MODEL_TIER", "OLLAMA_MODEL", "GALAXY_PERCEPTION_MODEL"):
            monkeypatch.delenv(key, raising=False)  # 模拟新进程：只剩磁盘记录

        _only_c_is_broken(monkeypatch)
        assert ms.apply_effective_tier() == "D"

        assert mc.load_tier() == "D", "运行时没降下来"
        after = json.loads(mc._STATE_FILE.read_text(encoding="utf-8"))
        assert after == before, "降级把用户存的选择改写了"

    def test_the_main_brain_follows_the_effective_tier(self, isolated, monkeypatch):
        """留着 C 档推理位的 tag 不管，文本请求会落到一个这一档不加载的模型上。"""
        mc.save_tier("C")
        for key in ("GALAXY_MODEL_TIER", "OLLAMA_MODEL", "GALAXY_PERCEPTION_MODEL"):
            monkeypatch.delenv(key, raising=False)
        assert mc.main_brain() == "qwen3.6:35b-a3b"

        _only_c_is_broken(monkeypatch)
        ms.apply_effective_tier()

        assert mc.main_brain() == mc.default_main_brain_for_tier("D")
        assert mc.main_brain() != "qwen3.6:35b-a3b"
        assert mc.default_main_brain_for_tier("D") in mc.active_tags()

    def test_a_custom_model_outside_the_catalog_is_never_touched(self, isolated, monkeypatch):
        """目录外的自定义模型是用户显式填的 —— 与 save_tier "显式一律尊重"同一立场。"""
        mc.save_tier("C")
        for key in ("GALAXY_MODEL_TIER", "OLLAMA_MODEL", "GALAXY_PERCEPTION_MODEL"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("OLLAMA_MODEL", "my-own/finetune:v3")

        _only_c_is_broken(monkeypatch)
        ms.apply_effective_tier()

        assert mc.load_tier() == "D", "档位该降的还是要降"
        assert mc.main_brain() == "my-own/finetune:v3", "把用户自己填的模型改掉了"

    def test_no_degrade_reports_nothing_happened(self, isolated, monkeypatch):
        """返回 "" 是调用方判断"这次的派生值能不能回写"的唯一依据。"""
        mc.save_tier("B")
        monkeypatch.setattr(rr, "tier_is_runnable", lambda key: True)
        assert ms.apply_effective_tier() == ""

    def test_a_degraded_boot_does_not_persist_the_derived_brain(self, isolated, monkeypatch):
        """整条启动路径跑一遍：resolve_main_brain 不能把降档派生的值写回记录。

        它第一条判据读的就是 ``OLLAMA_MODEL``，而降级刚改过它 —— 照常
        ``save_choice`` 的话，等于拿一次环境故障把用户的选择永久改掉。
        """
        mc.save_tier("C")
        before = json.loads(mc._STATE_FILE.read_text(encoding="utf-8"))
        for key in ("GALAXY_MODEL_TIER", "OLLAMA_MODEL", "GALAXY_PERCEPTION_MODEL"):
            monkeypatch.delenv(key, raising=False)

        _only_c_is_broken(monkeypatch)
        returned = ms.resolve_main_brain(interactive=False)

        assert returned == mc.default_main_brain_for_tier("D")
        assert json.loads(mc._STATE_FILE.read_text(encoding="utf-8")) == before

    def test_an_undegraded_boot_still_persists_as_before(self, isolated, monkeypatch):
        """反向：没降级时回写行为一个字都没变。"""
        mc.save_tier("B")
        monkeypatch.setattr(rr, "tier_is_runnable", lambda key: True)
        for key in ("GALAXY_MODEL_TIER", "OLLAMA_MODEL", "GALAXY_PERCEPTION_MODEL"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("OLLAMA_MODEL", "gemma4:e2b")

        ms.resolve_main_brain(interactive=False)

        assert json.loads(mc._STATE_FILE.read_text(encoding="utf-8"))["main_brain"] == "gemma4:e2b"


class TestDegradingIsWiredIntoStartup:
    """降级要在读 ``OLLAMA_MODEL`` 那几条路**之前**发生，否则等于一句空话。"""

    def test_resolve_main_brain_degrades_before_it_reads_the_env(self):
        import inspect

        src = inspect.getsource(ms.resolve_main_brain)
        assert "apply_effective_tier()" in src, "启动路径没接降级"
        assert src.index("apply_effective_tier()") < src.index(
            'os.environ.get("OLLAMA_MODEL"'
        ), "降级放在了读 OLLAMA_MODEL 之后 —— 这次启动已经按跑不起来的那一档把主脑定下来了"

    def test_the_launcher_resolves_the_brain_before_it_loads_anything(self):
        """降级要落在**任何模型被加载之前**，否则降了也白降。

        ``resolve_main_brain`` 是降级唯一的落点，而它只在 launcher 里被调一次。
        谁要是把 ``start_local_brain()`` 挪到它前面，这次启动就会先按跑不起来的
        那一档把模型拉起来 —— 降级变成一句在失败之后才说的话。
        """
        import inspect

        from launcher import services

        src = inspect.getsource(services)
        assert src.index("ms.resolve_main_brain") < src.index(
            "await self.start_local_brain()"
        ), "本地大脑在主脑解析之前就启动了 —— 降级来不及生效"

    def test_the_message_says_the_record_was_not_touched(self, isolated, monkeypatch, capsys):
        """用户得知道自己不用再去选一次档。"""
        mc.save_tier("C")
        for key in ("GALAXY_MODEL_TIER", "OLLAMA_MODEL", "GALAXY_PERCEPTION_MODEL"):
            monkeypatch.delenv(key, raising=False)
        _only_c_is_broken(monkeypatch)

        ms.apply_effective_tier()

        out = capsys.readouterr().out
        assert "C" in out and "B" in out
        assert "没有被改写" in out


class TestTheFootprintIsReportedAsARange:
    """一个数看不出底下压着假设；一对数里，差值本身就是"有多少是空头支票"。"""

    def test_the_moe_tier_spread_is_the_offload_assumption(self):
        lo, hi = mc.tier_runtime_footprint_range_mb("C")
        assert hi > lo, "C 档的驻留量全靠专家卸载，悲观值必须更大"
        spec = mc.exact_model("qwen3.6:35b-a3b")
        assert hi - lo == spec.size_mb() - spec.runtime_mb()

    def test_a_non_moe_tier_has_no_spread(self):
        lo, hi = mc.tier_runtime_footprint_range_mb("B")
        assert lo == hi

    def test_the_dense_dual_tier_owes_no_iou(self):
        """D 档存在的全部理由：它的显存账**不欠**专家卸载那张票。

        差为 0 = 这一档的预算里没有"假设某件事成立"的部分。C 档差 10700 MB，
        那正是它在多数机器上判不可跑的原因。这两个数放在一起，D 档为什么该排在
        C 档之前（门槛更低）就是自明的。
        """
        assert mc.tier_runtime_footprint_range_mb("D") == mc.tier_runtime_footprint_range_mb("D")[:1] * 2
        c_lo, c_hi = mc.tier_runtime_footprint_range_mb("C")
        assert c_hi > c_lo, "C 档的卸载假设消失了？那 D 档就没有存在理由了"

    def test_the_dense_reasoning_slot_is_declared_not_moe(self):
        """必须是显式 ``False``，不是 ``None``（没人填过）。

        ``None`` 会让 ``resolve_is_moe`` 退回命名惯例兜底去猜；而调度器一旦把它当
        MoE，就会对一个稠密模型尝试专家卸载拆分 —— 拆出来的分配是没有意义的。
        """
        spec = mc.exact_model("qwythos-9b-v2")
        assert spec.is_moe is False
        assert spec.runtime_mb() >= spec.size_mb(), "稠密模型的驻留量不该小于权重（那是卸载才有的事）"

    def test_the_single_value_is_the_optimistic_head(self):
        for key in mc.tier_keys():
            assert mc.tier_runtime_footprint_mb(key) == mc.tier_runtime_footprint_range_mb(key)[0]

    def test_an_unknown_tag_makes_the_whole_tier_unjudgeable(self, monkeypatch):
        """不能跳过查不到的那位接着求和 —— 那样得到的门槛**偏小**，准入会放行装不下的档。"""
        monkeypatch.setattr(mc, "active_tags", lambda k="": ["openbmb/minicpm-o4.5", "nope/not-in-catalog"])
        assert mc.tier_runtime_footprint_range_mb("C") == (0, 0)

    def test_a_tag_whose_family_exists_is_not_answered_with_the_family_number(self, monkeypatch):
        """``gemma4:31b`` 不在目录里，但 ``gemma4`` 这一家在。

        走 ``get_model`` 的家族兜底会拿**同家族第一条**(``gemma4:e2b``，1800 MB)
        来回答一个 31B 型号 —— 档级门槛于是被答成 1800 MB 出头，准入必然放行，
        加载到一半必 OOM。这条是上面那条纯结构断言的行为版：它盯的是数字。
        """
        monkeypatch.setattr(mc, "active_tags", lambda k="": ["gemma4:31b"])
        assert mc.get_model("gemma4:31b").runtime_mb() == 1800, "家族兜底的前提变了，这条要重写"
        assert mc.tier_runtime_footprint_range_mb("A") == (0, 0), "档级驻留量吃了家族兜底的数字"


class TestTheVramCriterionRefusesFamilyFallback:
    """显存口径一律精确查表。同家族的 2B 和 31B 差一个数量级。"""

    def test_exact_model_does_not_fall_back_to_the_family(self):
        assert mc.get_model("gemma4:31b") is not None, "get_model 的家族兜底本身是对的（后端口径）"
        assert mc.exact_model("gemma4:31b") is None, "显存口径不能拿同家族第一条的数字冒充"

    def test_the_tier_level_entry_uses_the_exact_lookup_too(self):
        """单 tag 那个入口早就修了，档级这个才是喂给推荐器的那一个。"""
        import inspect

        src = inspect.getsource(mc.tier_runtime_footprint_range_mb)
        assert "exact_model(" in src
        assert "get_model(" not in src, "档级驻留量又走回 get_model 的家族兜底了"


class TestTheMainBrainRuleLivesInOnePlace:
    """上一轮出事就是因为这条规则被写了两遍，错的那遍赢了。"""

    def test_save_tier_and_the_degrade_path_ask_the_same_function(self):
        import inspect

        assert "default_main_brain_for_tier" in inspect.getsource(mc.save_tier)
        assert "default_main_brain_for_tier" in inspect.getsource(ms.apply_effective_tier)

    def test_the_composite_tier_still_resolves_to_the_reasoning_slot(self):
        """复合档取"档内第一个 source=local"会指到感知位 —— 那正是上一轮的 bug。"""
        assert mc.default_main_brain_for_tier("C") == "qwen3.6:35b-a3b"
        slot = mc.slot_for_role(mc.SLOT_REASONING, "C")
        assert slot is not None and mc.default_main_brain_for_tier("C") == slot.tag

    def test_single_tiers_resolve_to_their_first_local_model(self):
        for key in mc.tier_keys():
            if mc._TIERS[key].kind == "composite":
                continue
            locals_in_tier = [s.tag for s in mc.tier_models(key) if s.source == "local"]
            assert mc.default_main_brain_for_tier(key) == locals_in_tier[0]
