"""tests/test_speculative_draft.py
====================================
投机解码的草稿位:**声明 × 绑定能力 × 真机实测**三维互不冒充,以及 D 档那条路
从目录一直到渲染契约的全程。

这件事为什么必须做成三维
------------------------
投机解码不是无条件加速:公开实测里同一件事既有 +2.69× 也有净 −44.6%,而且在同一台
机器上 ``--spec-draft-n-max`` 取默认 15 是净亏、取 4 才 +27%。所以

* "存不存在"(目录声明)、"接不接得上"(绑定签名)、"值不值得"(真机 A/B)
  是三个**不同的问题**,任何一个都不能替另外两个回答;
* **默认必须是关**,而且"没测过"要与"测过、结论是别开"分得开。

不加载任何模型、不触网:绑定探测只读签名,A/B 全部注入假执行体。
"""

from __future__ import annotations

import json

import pytest

import core.draft_benchmark as db
import core.render_pathway as rp
import core.speculative_draft as sd
import core.thinking_locus as tl
from core.draft_benchmark import BenchRun, benchmark_draft, verdict_from_labels
from core.speculative_draft import DraftMeasurement, DraftSpec


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    """实测记录是**真文件**。隔到 tmp_path —— 仓库已经因为共享状态文件栽过一次:
    一个临时脚本把档位落成 C,两条毫不相干的测试一起变红。"""
    monkeypatch.setattr(sd, "_STATE_FILE", tmp_path / "speculative_draft.json")
    monkeypatch.delenv("GALAXY_SPECULATIVE_DRAFT", raising=False)
    rp.reset_pathway_cache()
    tl.reset()
    yield
    rp.reset_pathway_cache()
    tl.reset()


# ══════════════════════════════════════════════════════════════════════════
# A. 声明维:"没查过" 与 "确认没有" 必须分得开
# ══════════════════════════════════════════════════════════════════════════


def test_a01_default_is_unknown_not_none():
    """与 ``ModelSpec.is_moe`` 用 Optional[bool] 同一条:前者该去问,后者到此为止。"""
    spec = DraftSpec.unknown()
    assert spec.mechanism == "unknown"
    assert spec.is_settled is False
    assert spec.is_possible is False


def test_a02_none_means_someone_checked():
    spec = DraftSpec(mechanism="none")
    assert spec.is_settled is True  # 查过了
    assert spec.is_possible is False  # 结论是没有


def test_a03_settled_is_derived_not_relisted():
    """每加一套机制都得记得改一处清单 —— 那正是加 mtp_self 时漏掉的地方。

    漏掉的表现是新机制被判成"没人查过",探测直接不列它:不报错、不变慢、不生效。
    """
    for m in sd.DRAFT_MECHANISMS:
        assert DraftSpec(mechanism=m).is_settled is (m != "unknown"), m


def test_a04_external_mechanism_needs_a_candidate():
    """声明了 dflash 却一个检查点都没有 —— 探测无从下手,那和没声明是一回事。"""
    assert DraftSpec(mechanism="dflash").is_possible is False
    assert DraftSpec(mechanism="dflash", candidate_repos=("z-lab/X",)).is_possible is True


def test_a05_self_hosted_mechanism_needs_no_candidate():
    """自带 MTP 头的草稿就在权重里,要问的是"这份 GGUF 里有没有那个头"。"""
    spec = DraftSpec(mechanism="mtp_self")
    assert spec.is_possible is True
    assert spec.needs_external_checkpoint is False


def test_a06_spec_type_table_covers_the_llama_cpp_mechanisms():
    assert DraftSpec(mechanism="dflash", candidate_repos=("x",)).spec_type == "draft-dflash"
    assert DraftSpec(mechanism="mtp_self").spec_type == "draft-mtp"
    # Ollama 那套不走 --spec-type,如实给空串而不是编一个
    assert DraftSpec(mechanism="ollama_mtp").spec_type == ""


def test_a07_zero_runtime_mb_means_unmeasured_not_free():
    """草稿是**额外**权重,一定占。0 只能是"没量过"。"""
    spec = DraftSpec(mechanism="dflash", candidate_repos=("x",))
    assert spec.runtime_mb() == 0
    assert spec.to_dict()["measured"] is False


# ══════════════════════════════════════════════════════════════════════════
# B. 绑定能力维:接不上要说"接不上",不是"慢"
# ══════════════════════════════════════════════════════════════════════════


def test_b01_absent_and_unsupported_are_different():
    """前者装上可能就有,后者得换构建 —— 合成一个,用户会去装一个已经装好的东西。"""
    assert "absent" in sd.BINDING_SUPPORT
    assert "unsupported" in sd.BINDING_SUPPORT


def test_b02_missing_binding_reports_absent():
    verdict, found = sd.llama_binding_draft_support()
    assert verdict in sd.BINDING_SUPPORT
    if verdict == "absent":
        assert found == ()


def test_b03_binding_probe_reads_the_signature_only(monkeypatch):
    """只读签名,绝不加载模型 —— 与 moe_offload_supported 是同一招。"""

    class _FakeLlama:
        def __init__(self, model_path=None, spec_type=None, spec_draft_n_max=None):
            raise AssertionError("绑定探测绝不该构造 Llama 实例")

    import sys
    import types

    mod = types.ModuleType("llama_cpp")
    mod.Llama = _FakeLlama  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", mod)
    verdict, found = sd.llama_binding_draft_support()
    assert verdict == "supported"
    assert set(found) == {"spec_type", "spec_draft_n_max"}


def test_b04_binding_without_draft_params_is_unsupported(monkeypatch):
    class _Plain:
        def __init__(self, model_path=None, n_ctx=4096):
            pass

    import sys
    import types

    mod = types.ModuleType("llama_cpp")
    mod.Llama = _Plain  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "llama_cpp", mod)
    assert sd.llama_binding_draft_support() == ("unsupported", ())


# ══════════════════════════════════════════════════════════════════════════
# C. 实测维:默认关,而且"没测过"≠"没问题"
# ══════════════════════════════════════════════════════════════════════════


def test_c01_untested_is_the_default_and_means_do_not_enable():
    m = sd.load_measurement("qwythos-9b-v2")
    assert m.verdict == "untested"
    assert m.should_enable is False


def test_c02_load_returns_an_object_not_none():
    """None 只会诱导调用方补一个默认值 —— 而这里唯一安全的默认是"别开"。"""
    assert isinstance(sd.load_measurement("nobody"), DraftMeasurement)


def test_c03_slower_is_a_real_outcome_not_an_error():
    """RTX 3090 + Q4 走 llama.cpp 是净 −44.6%。这不是"测挂了,回头再试"。"""
    assert "slower" in sd.DRAFT_VERDICTS
    assert "error" in sd.DRAFT_VERDICTS
    m = DraftMeasurement(tag="t", verdict="slower", speedup=0.55)
    assert m.should_enable is False


def test_c04_marginal_speedup_does_not_clear_the_bar():
    """1% 的波动淹没在采样噪声里,拿它去开一个要占显存的东西不划算。"""
    assert DraftMeasurement(tag="t", verdict="faster", speedup=1.01).should_enable is False
    assert DraftMeasurement(tag="t", verdict="faster", speedup=sd.MIN_SPEEDUP).should_enable is True


def test_c05_measurement_round_trips_through_disk():
    sd.save_measurement(DraftMeasurement(tag="t", verdict="faster", speedup=1.3, n_max=4, drafter_runtime_mb=900))
    got = sd.load_measurement("t")
    assert (got.verdict, got.speedup, got.n_max, got.drafter_runtime_mb) == ("faster", 1.3, 4, 900)


def test_c06_n_max_is_recorded_because_the_default_is_the_wrong_answer():
    """同机器上 15 净亏、4 是 +27% —— 不记下来,结论既复现不了也说不清针对哪个配置。"""
    sd.save_measurement(DraftMeasurement(tag="t", verdict="faster", speedup=1.27, n_max=4))
    assert sd.load_measurement("t").n_max == 4


def test_c07_corrupt_state_file_degrades_to_untested(tmp_path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(sd, "_STATE_FILE", bad)
    assert sd.load_measurement("t").verdict == "untested"


def test_c09_state_path_is_not_an_env_knob():
    """运行时状态文件放哪不该出现在配置面上 —— 与 model_catalog 同一条约定。

    第一版给了个 ``GALAXY_DRAFT_STATE_FILE``,CI 当场拦下:凡被代码读取的
    ``GALAXY_*`` 都得登记进 CONFIG_SCHEMA 与面板,而"往哪写文件"既是
    "站在梯子上搬梯子",也不该让配置接口指定任意写入路径。
    """
    src = (sd.PROJECT_ROOT / "core" / "speculative_draft.py").read_text(encoding="utf-8")
    reads = [ln for ln in src.splitlines() if "os.environ.get(" in ln or "os.getenv(" in ln]
    assert all("GALAXY_SPECULATIVE_DRAFT" in ln for ln in reads), reads


def test_c10_the_kill_switch_is_registered_everywhere():
    """开关登记不全 = 功能没接到面板上:后端缺 → /api/config/all 不返回它;
    前端缺 → 设置页上没有它的位置;而 POST /api/config 还会把它当 unknown_keys 拒掉。"""
    from core.routes.config import CONFIG_SCHEMA

    assert "GALAXY_SPECULATIVE_DRAFT" in CONFIG_SCHEMA
    panel = (sd.PROJECT_ROOT / "electron/renderer/panel/src/settings_inventory.ts").read_text(encoding="utf-8")
    assert "'GALAXY_SPECULATIVE_DRAFT'" in panel


def test_c08_labelled_runs_live_under_a_reserved_key():
    """同一层里混着两种含义的键,迟早有人遍历它当型号表用。"""
    sd.save_labelled_run("qwythos-9b-v2", "baseline", {"tokens": 80, "seconds": 4.0})
    raw = json.loads(sd.state_file().read_text(encoding="utf-8"))
    assert "_runs" in raw
    assert all(not k.startswith("_") for k in raw if k != "_runs")


# ══════════════════════════════════════════════════════════════════════════
# D. 三条全成立才开
# ══════════════════════════════════════════════════════════════════════════


def _enable(tag: str, speedup: float = 1.3) -> None:
    sd.save_measurement(DraftMeasurement(tag=tag, verdict="faster", speedup=speedup, n_max=4))


def test_d01_declared_and_measured_enables_it():
    _enable("qwythos-9b-v2")
    assert sd.is_enabled("qwythos-9b-v2") is True


def test_d02_measured_but_undeclared_stays_off():
    """目录没声明机制 → 连怎么开都不知道,一个漂亮的实测数字也不作数。"""
    _enable("gemma4:e2b")
    assert sd.draft_spec_of("gemma4:e2b").is_possible is False
    assert sd.is_enabled("gemma4:e2b") is False


def test_d03_declared_but_unmeasured_stays_off():
    """默认关:没测过的机器上开它,期望值是负的。"""
    assert sd.draft_spec_of("qwythos-9b-v2").is_possible is True
    assert sd.is_enabled("qwythos-9b-v2") is False


def test_d04_env_kill_switch_wins(monkeypatch):
    _enable("qwythos-9b-v2")
    monkeypatch.setenv("GALAXY_SPECULATIVE_DRAFT", "0")
    assert sd.is_enabled("qwythos-9b-v2") is False


def test_d05_unknown_tag_is_never_enabled():
    _enable("no-such-model")
    assert sd.is_enabled("no-such-model") is False


# ══════════════════════════════════════════════════════════════════════════
# E. 显存:确定的 0 ≠ 判不了
# ══════════════════════════════════════════════════════════════════════════


def test_e01_disabled_costs_nothing():
    assert sd.draft_footprint_mb("qwythos-9b-v2") == (0, "草稿位未启用")


def test_e02_self_hosted_head_costs_a_certain_zero():
    """自带 MTP 头没有独立权重 —— 这个 0 是确定的,不是"没量过"。"""
    _enable("qwythos-9b-v2")
    mb, why = sd.draft_footprint_mb("qwythos-9b-v2")
    assert mb == 0
    assert "自带" in why


def test_e03_external_checkpoint_unmeasured_is_undecidable(monkeypatch):
    """已启用但没人量过占多少 → 判不了(-1),**不能当 0 吸收**。

    吸收掉得到的是一个偏小的门槛,而偏小的门槛会放行 —— 正是目录里记着的
    MiniCPM-o 那个故障形态:准入判"放得下",加载到一半 OOM。
    """
    monkeypatch.setattr(sd, "draft_spec_of", lambda _t: DraftSpec(mechanism="dflash", candidate_repos=("z-lab/X",)))
    _enable("qwythos-9b-v2")
    mb, why = sd.draft_footprint_mb("qwythos-9b-v2")
    assert mb == -1
    assert "没人量过" in why


def test_e04_external_checkpoint_measured_adds_its_weight(monkeypatch):
    monkeypatch.setattr(sd, "draft_spec_of", lambda _t: DraftSpec(mechanism="dflash", candidate_repos=("z-lab/X",)))
    sd.save_measurement(
        DraftMeasurement(tag="qwythos-9b-v2", verdict="faster", speedup=1.3, n_max=4, drafter_runtime_mb=900)
    )
    assert sd.draft_footprint_mb("qwythos-9b-v2")[0] == 900


def test_e05_tier_footprint_is_unchanged_while_disabled():
    from core.model_catalog import tier_runtime_footprint_range_mb

    assert tier_runtime_footprint_range_mb("D") == (18000, 18000)


def test_e06_tier_footprint_absorbs_a_measured_drafter(monkeypatch):
    from core.model_catalog import tier_runtime_footprint_range_mb

    monkeypatch.setattr(sd, "draft_spec_of", lambda _t: DraftSpec(mechanism="dflash", candidate_repos=("z-lab/X",)))
    for tag in ("openbmb/minicpm-o4.5", "qwythos-9b-v2"):
        sd.save_measurement(DraftMeasurement(tag=tag, verdict="faster", speedup=1.3, n_max=4, drafter_runtime_mb=500))
    lo, hi = tier_runtime_footprint_range_mb("D")
    assert lo == 18000 + 1000  # 两位各多一份草稿


def test_e07_undecidable_drafter_makes_the_whole_tier_undecidable(monkeypatch):
    """判不了必须能被调用方看见 —— (0,0) 是这条链上既定的"判不了"信号。"""
    from core.model_catalog import tier_runtime_footprint_range_mb

    monkeypatch.setattr(sd, "draft_spec_of", lambda _t: DraftSpec(mechanism="dflash", candidate_repos=("z-lab/X",)))
    _enable("qwythos-9b-v2")  # 开了,但没量过草稿多大
    assert tier_runtime_footprint_range_mb("D") == (0, 0)


# ══════════════════════════════════════════════════════════════════════════
# F. A/B:扫块大小,而且默认值恰恰是常见的错误答案
# ══════════════════════════════════════════════════════════════════════════


def _runner(speeds):
    def run(_tag, n):
        if n not in speeds:
            raise RuntimeError(f"没测这个配置: {n}")
        return int(speeds[n] * 4), 4.0

    return run


def test_f01_sweep_includes_the_upstream_default():
    """只测默认 15 会得出"投机解码没用";只测小值会不知道默认值坑在哪。"""
    assert 15 in db.DEFAULT_N_MAX_SWEEP
    assert any(n < 15 for n in db.DEFAULT_N_MAX_SWEEP)


def test_f02_picks_the_best_block_size_not_the_default():
    """复刻公开实测的形状:默认 15 净亏、4 才是赢的那个。"""
    m, runs = benchmark_draft("qwythos-9b-v2", runner=_runner({0: 20.0, 4: 25.4, 8: 22.0, 15: 11.1}), repeats=1)
    assert m.verdict == "faster"
    assert m.n_max == 4
    assert m.should_enable is True
    assert len(runs) == 4  # 基线 + 三个块大小


def test_f03_a_net_loss_is_reported_as_slower():
    m, _ = benchmark_draft("qwythos-9b-v2", runner=_runner({0: 20.0, 4: 12.0, 8: 11.0, 15: 11.1}), repeats=1)
    assert m.verdict == "slower"
    assert m.speedup < 1.0
    assert m.should_enable is False


def test_f04_undeclared_model_is_unsupported_not_slower():
    m, runs = benchmark_draft("gemma4:e2b", runner=_runner({0: 20.0}), repeats=1)
    assert m.verdict == "unsupported"
    assert runs == []  # 无从测起,一趟都没跑


def test_f05_binding_failure_is_unsupported_not_error():
    def _boom(_tag, _n):
        raise RuntimeError("llama-cpp-python 不透出草稿位参数(结论=absent)")

    m, _ = benchmark_draft("qwythos-9b-v2", runner=_boom, repeats=1)
    assert m.verdict == "unsupported"


def test_f06_a_crash_is_error_not_slower():
    def _boom(_tag, n):
        if n == 0:
            return 80, 4.0
        raise RuntimeError("显存炸了")

    m, _ = benchmark_draft("qwythos-9b-v2", runner=_boom, repeats=1)
    assert m.verdict == "error"


def test_f07_default_runner_refuses_rather_than_guessing():
    """不把旗标塞进 kwargs 碰运气:塞进去会被静默忽略,表现是"开了但没变快"。"""
    m, _ = benchmark_draft("qwythos-9b-v2", repeats=1)
    assert m.verdict == "unsupported"
    assert "llama-server" in m.detail  # 如实给出唯一可用的那条路


def test_f08_benchmark_never_writes_state():
    """测量是只读观测,落盘是对运行时行为的改变 —— 那一步该由人显式发起。"""
    benchmark_draft("qwythos-9b-v2", runner=_runner({0: 20.0, 4: 30.0, 8: 22.0, 15: 11.1}), repeats=1)
    assert sd.load_measurement("qwythos-9b-v2").verdict == "untested"
    assert sd.is_enabled("qwythos-9b-v2") is False


def test_f09_best_of_repeats_takes_the_fastest_not_the_mean():
    """取平均会让一次后台编译把结论压翻。"""
    seq = iter([(80, 8.0), (80, 4.0)])  # 第一趟被别的东西抢卡

    def run(_tag, n):
        return (80, 4.0) if n == 0 else next(seq)

    m, _ = benchmark_draft("qwythos-9b-v2", runner=run, n_max_sweep=(4,), repeats=2)
    assert m.speedup == pytest.approx(1.0)  # 取快的那一趟 → 与基线持平,而不是被慢的那趟拖成 0.5


# ══════════════════════════════════════════════════════════════════════════
# G. 人跑两趟量服务(今天唯一真正可用的那条路)
# ══════════════════════════════════════════════════════════════════════════


def test_g01_two_passes_produce_a_verdict():
    m = verdict_from_labels("qwythos-9b-v2", {"baseline": BenchRun(0, 80, 4.0), "4": BenchRun(4, 100, 4.0)})
    assert m.verdict == "faster"
    assert m.n_max == 4


def test_g02_without_a_baseline_there_is_no_conclusion():
    """只量了开着的那趟,一个漂亮的 tok/s 完全可能比关掉还慢。"""
    m = verdict_from_labels("qwythos-9b-v2", {"4": BenchRun(4, 100, 4.0)})
    assert m.verdict == "untested"


def test_g03_baseline_only_is_also_untested():
    m = verdict_from_labels("qwythos-9b-v2", {"baseline": BenchRun(0, 80, 4.0)})
    assert m.verdict == "untested"


def test_g04_verdict_logic_has_exactly_one_definition():
    """两条路(进程内扫 / 人跑两趟)必须走同一条判定,否则会在"多少算更快"上分叉。"""
    swept, _ = benchmark_draft("qwythos-9b-v2", runner=_runner({0: 20.0, 4: 25.0}), n_max_sweep=(4,), repeats=1)
    manual = verdict_from_labels("qwythos-9b-v2", {"baseline": BenchRun(0, 80, 4.0), "4": BenchRun(4, 100, 4.0)})
    assert swept.verdict == manual.verdict
    assert swept.speedup == pytest.approx(manual.speedup)


def test_g05_endpoint_measurement_reports_failure_instead_of_raising():
    class _Dead:
        def post(self, *_a, **_k):
            raise OSError("connection refused")

    run = db.measure_endpoint("http://127.0.0.1:9/v1", "qwythos-9b-v2", client=_Dead())
    assert run.ok is False
    assert "refused" in run.error


def test_g06_endpoint_prefers_the_servers_own_token_count():
    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"usage": {"completion_tokens": 123}, "choices": [{"message": {"content": "x" * 4}}]}

    class _Http:
        def post(self, *_a, **_k):
            return _Resp()

    run = db.measure_endpoint("http://x/v1", "m", client=_Http())
    assert run.tokens == 123  # 不是按字符粗估出来的 2


# ══════════════════════════════════════════════════════════════════════════
# H. D 档全程:目录 → 决策 → 渲染契约
# ══════════════════════════════════════════════════════════════════════════


def test_h01_d_tier_reasoning_slot_declares_its_mechanism():
    from core.model_catalog import get_tier

    reasoning = [s for s in get_tier("D").slots if s.role == "reasoning"][0]
    tag = reasoning.candidates[0]
    assert tag == "qwythos-9b-v2"
    spec = sd.draft_spec_of(tag)
    assert spec.mechanism == "mtp_self"
    assert spec.needs_external_checkpoint is False


def test_h02_declaration_reaches_the_catalog_dict():
    from core.model_catalog import exact_model

    d = exact_model("qwythos-9b-v2").to_dict()["draft"]
    assert d["mechanism"] == "mtp_self"
    assert d["spec_type"] == "draft-mtp"


def test_h03_contract_says_not_accelerated_when_untested():
    tl.record(provider="local_openai", model="qwythos-9b-v2", role="coder", is_local=True, route_type="produce")
    view = rp.resolve_thinking_locus_view()
    assert view.locus == "local"
    assert view.draft_active is False
    assert view.draft_speedup == 0.0


def test_h04_contract_shows_acceleration_once_measured():
    tl.record(provider="local_openai", model="qwythos-9b-v2", role="coder", is_local=True, route_type="produce")
    _enable("qwythos-9b-v2", speedup=1.26)
    rp.reset_pathway_cache()
    view = rp.resolve_thinking_locus_view()
    assert view.draft_active is True
    assert view.draft_speedup == pytest.approx(1.26)


def test_h05_measured_slower_shows_the_number_but_not_the_flag():
    """ "测过、结论是别开"与"没测过"在面板上必须分得开。"""
    tl.record(provider="local_openai", model="qwythos-9b-v2", role="coder", is_local=True, route_type="produce")
    sd.save_measurement(DraftMeasurement(tag="qwythos-9b-v2", verdict="slower", speedup=0.55, n_max=15))
    rp.reset_pathway_cache()
    view = rp.resolve_thinking_locus_view()
    assert view.draft_active is False
    assert view.draft_speedup == pytest.approx(0.55)


def test_h06_cloud_locus_never_claims_anything_about_drafts():
    """云端怎么解码这边既管不着也看不见 —— 报"没开"会被读成"云端没被加速"。"""
    _enable("qwythos-9b-v2")
    tl.record(provider="anthropic", model="qwythos-9b-v2", role="critic", is_local=False, route_type="gatekeep")
    rp.reset_pathway_cache()
    view = rp.resolve_thinking_locus_view()
    assert view.locus == "cloud"
    assert view.draft_active is False
    assert view.draft_speedup == 0.0


def test_h07_both_bits_ride_the_render_contract():
    import core.phase_contract as pc

    tl.record(provider="local_openai", model="qwythos-9b-v2", role="coder", is_local=True, route_type="produce")
    _enable("qwythos-9b-v2", speedup=1.4)
    rp.reset_pathway_cache()
    d = pc.resolve_render_posture(lifecycle="manifest").to_dict()["thinking_locus"]
    assert d["draft_active"] is True
    assert d["draft_speedup"] == pytest.approx(1.4)


def test_h08_schema_declares_both_bits():
    import core.phase_contract as pc

    names = [f["name"] for f in pc.render_contract_schema()["thinking_locus_fields"]]
    assert "draft_active" in names and "draft_speedup" in names


def test_h09_readout_survives_a_broken_state_module(monkeypatch):
    """可见性绝不该拖垮广播。"""
    monkeypatch.setattr(sd, "is_enabled", lambda _t: (_ for _ in ()).throw(RuntimeError("boom")))
    tl.record(provider="local_openai", model="qwythos-9b-v2", role="coder", is_local=True, route_type="produce")
    rp.reset_pathway_cache()
    assert rp.resolve_thinking_locus_view().draft_active is False
