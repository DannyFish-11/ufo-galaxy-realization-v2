"""tests/test_render_pathway_contract.py
==========================================
渲染契约新增的两位:**走哪条通路**(``pathway``)与**这一轮在哪儿想**
(``thinking_locus``),以及它们背后的路由回执 ``core.thinking_locus``。

两位为什么必须都在
------------------
``perception`` 说"这一侧有没有信号",``pathway`` 说"这条信号是**怎么**进去的"——
原生一条通路、接了桥两段(转写丢语气、抽帧丢连续性),渲染上本就不该长一个样。
而通路取决于"这一轮由谁来想":本地档位瞎着、这轮交给一家能看的云端时,视觉可用。

不触网、不加载模型:全部注入替身 + 静态 provider 表。
"""

from __future__ import annotations

import pytest

import core.modality_capability as mc
import core.phase_contract as pc
import core.render_pathway as rp
import core.thinking_locus as tl


@pytest.fixture(autouse=True)
def _isolate():
    """回执和通路缓存都是**进程级**状态,不清会把上一条用例的结论漏给下一条。"""
    tl.reset()
    rp.reset_pathway_cache()
    yield
    tl.reset()
    rp.reset_pathway_cache()


# ══════════════════════════════════════════════════════════════════════════
# A. 回执:没决策过 ≠ 决策成本地
# ══════════════════════════════════════════════════════════════════════════


def test_a01_fresh_process_is_unknown_not_local():
    """默认 locus 是 unknown。报成 local 会让渲染端在还没开始想的时刻画出"本地在想"。"""
    rec = tl.last()
    assert rec.locus == "unknown"
    assert rec.is_decided is False


def test_a02_last_returns_an_empty_record_not_none():
    """空态要是一个语义明确的对象;None 只会诱导调用方去补一个默认值。"""
    assert tl.last() is not None
    assert isinstance(tl.last(), tl.ThinkingLocusRecord)


def test_a03_recording_a_local_choice():
    tl.record(provider="ollama", model="gemma4:e2b", role="executor", is_local=True, route_type="dispatch")
    rec = tl.last()
    assert (rec.locus, rec.provider, rec.route_type, rec.is_decided) == ("local", "ollama", "dispatch", True)


def test_a04_recording_a_cloud_choice():
    tl.record(provider="anthropic", model="claude-sonnet-5", role="critic", is_local=False, route_type="gatekeep")
    assert tl.last().locus == "cloud"


def test_a05_a_failed_route_is_not_local():
    """provider="none" 是路由失败。记成本地会画出一个不存在的推理过程。"""
    tl.record(provider="none", model="none", role="coder", is_local=True, route_type="produce")
    rec = tl.last()
    assert rec.locus == "unknown"
    assert rec.is_decided is False
    assert rec.route_type == "produce"  # 角色意图仍然记着 —— 失败的是落点,不是意图


def test_a06_empty_provider_is_treated_as_no_decision():
    tl.record(provider="", model="", role="x", is_local=False, route_type="produce")
    assert tl.last().locus == "unknown"


def test_a07_unknown_route_type_is_normalised():
    tl.record(provider="ollama", model="m", role="x", is_local=True, route_type="telepathy")
    assert tl.last().route_type == "unknown"


def test_a08_only_the_last_one_is_kept():
    tl.record(provider="ollama", model="a", role="executor", is_local=True, route_type="dispatch")
    tl.record(provider="openai", model="b", role="critic", is_local=False, route_type="gatekeep")
    assert tl.last().provider == "openai"


def test_a09_locus_provider_is_cloud_only():
    """negotiate(locus=) 只接受远端归属 —— 本地那侧的能力源本来就是它的默认。"""
    tl.record(provider="ollama", model="m", role="executor", is_local=True, route_type="dispatch")
    assert tl.locus_provider() is None
    tl.record(provider="openai", model="m", role="critic", is_local=False, route_type="gatekeep")
    assert tl.locus_provider() == "openai"


def test_a10_reset_really_resets():
    tl.record(provider="openai", model="m", role="critic", is_local=False, route_type="gatekeep")
    tl.reset()
    assert tl.last().locus == "unknown"


# ══════════════════════════════════════════════════════════════════════════
# B. 路由那一侧:结论从单一漏斗记出来
# ══════════════════════════════════════════════════════════════════════════


def test_b01_role_routing_records_a_receipt():
    """五个返回点共用一个漏斗 —— 逐点记账必然在加分支时漏记。"""
    from core.multi_llm_router import MultiLLMRouter

    router = MultiLLMRouter()
    router.select_brain_for_role("executor")
    assert tl.last().role == "executor"
    assert tl.last().route_type == "dispatch"


def test_b02_route_type_follows_the_role_intent_not_the_landing_spot():
    from core.multi_llm_router import MultiLLMRouter

    router = MultiLLMRouter()
    for role, expected in (("executor", "dispatch"), ("coder", "produce"), ("critic", "gatekeep")):
        router.select_brain_for_role(role)
        assert tl.last().route_type == expected, role


def test_b03_produce_roles_are_never_marked_fallback():
    """产出角色"按能力选,不按位置选",所以落在哪边都不是回落。"""
    from core.multi_llm_router import MultiLLMRouter

    router = MultiLLMRouter()
    router.select_brain_for_role("coder")
    assert tl.last().is_fallback is False


def test_b04_recording_failure_never_breaks_routing(monkeypatch):
    """记账绝不该影响路由本身。"""
    from core.multi_llm_router import MultiLLMRouter

    def _boom(**_kw):
        raise RuntimeError("recorder down")

    monkeypatch.setattr(tl, "record", _boom)
    router = MultiLLMRouter()
    decision = router.select_brain_for_role("executor")  # 不抛
    assert decision is not None


def test_b05_the_impl_is_still_reachable_for_callers_that_want_no_receipt():
    """拆两层不是为了加行为 —— 实现那一层照旧可用,只是不记账。"""
    from core.multi_llm_router import MultiLLMRouter

    router = MultiLLMRouter()
    router._select_brain_for_role_impl("executor")
    assert tl.last().locus == "unknown"  # 没走公开入口 → 没有回执


# ══════════════════════════════════════════════════════════════════════════
# C. 通路视图:只读、恒四条、locus 决定能力源
# ══════════════════════════════════════════════════════════════════════════


def test_c01_unwired_view_has_all_four_lanes():
    view = rp.ModalityPathwayView.unwired()
    assert [lane.modality for lane in view.lanes] == list(rp.PATHWAY_MODALITIES)
    assert all(lane.mode == "unavailable" for lane in view.lanes)
    assert view.is_wired is False


def test_c02_no_negotiator_in_process_means_unwired(monkeypatch):
    """绝不为了填一格去 import 一串重模块 —— 在场桥是 200ms 一拍的热路径。"""
    monkeypatch.setitem(__import__("sys").modules, "core.modality_capability", None)
    assert rp.resolve_pathway_view().is_wired is False


def test_c03_wired_view_reports_four_lanes_in_order():
    view = rp.resolve_pathway_view(locus="local")
    assert [lane.modality for lane in view.lanes] == list(rp.PATHWAY_MODALITIES)


def test_c04_cloud_locus_changes_the_pathway():
    """本维存在的全部理由:本地瞎着,而这一轮交给一家能看的云端。"""
    blind = rp.resolve_pathway_view(locus="groq")
    seeing = rp.resolve_pathway_view(locus="anthropic")
    lane = {la.modality: la for la in blind.lanes}["vision_in"]
    assert lane.mode == "unavailable"
    lane2 = {la.modality: la for la in seeing.lanes}["vision_in"]
    assert lane2.mode == "native"


def test_c05_locus_is_taken_from_the_receipt_when_not_given():
    tl.record(provider="anthropic", model="m", role="critic", is_local=False, route_type="gatekeep")
    assert rp.resolve_pathway_view().locus == "anthropic"


def test_c06_local_receipt_does_not_hijack_the_locus():
    """本地回执 → locus_provider() 为 None → 按本地协商,而不是把 "ollama" 当 provider。"""
    tl.record(provider="ollama", model="m", role="executor", is_local=True, route_type="dispatch")
    assert rp.resolve_pathway_view().locus == "local"


def test_c07_counts_are_derived_not_stored():
    view = rp.resolve_pathway_view(locus="anthropic")
    assert view.native_count == sum(1 for la in view.lanes if la.mode == "native")
    assert view.bridged_count == sum(1 for la in view.lanes if la.mode == "bridge")


def test_c08_negotiation_blowing_up_degrades_to_unwired(monkeypatch):
    """可见性绝不该拖垮广播。"""

    def _boom(**_kw):
        raise RuntimeError("negotiate exploded")

    monkeypatch.setattr(mc, "negotiate", _boom)
    assert rp.resolve_pathway_view(locus="local").is_wired is False


def test_c09_illegal_mode_from_backend_is_normalised(monkeypatch):
    class _Res:
        mode = "teleport"
        limited_by = "gremlins"

    class _Plan:
        locus = "local"

        def get(self, _m):
            return _Res()

    monkeypatch.setattr(mc, "negotiate", lambda **_kw: _Plan())
    view = rp.resolve_pathway_view(locus="local")
    assert all(la.mode == "unavailable" and la.limited_by == "" for la in view.lanes)


def test_c10_cache_is_keyed_by_locus(monkeypatch):
    calls = []

    real = mc.negotiate

    def _counting(**kw):
        calls.append(kw.get("locus"))
        return real(**kw)

    monkeypatch.setattr(mc, "negotiate", _counting)
    rp.resolve_pathway_view(locus="local")
    rp.resolve_pathway_view(locus="local")
    assert len(calls) == 1  # 第二次命中缓存
    rp.resolve_pathway_view(locus="anthropic")
    assert len(calls) == 2  # 换 locus 不复用


def test_c11_clearing_the_cache_forces_a_recompute(monkeypatch):
    calls = []
    real = mc.negotiate
    monkeypatch.setattr(mc, "negotiate", lambda **kw: (calls.append(1), real(**kw))[1])
    rp.resolve_pathway_view(locus="local")
    rp.reset_pathway_cache()
    rp.resolve_pathway_view(locus="local")
    assert len(calls) == 2


def test_c12_ttl_is_shorter_than_a_noticeable_pause():
    """缓存窗口要短到人眼分辨不出 —— 否则画面会停在旧结论上。"""
    assert 0 < rp.PATHWAY_TTL_S <= 5.0


def test_c13_pathway_vocabulary_matches_the_negotiator():
    """两边各写一份词汇表(本模块要在协商层没导入时也能给空态),一致性机器校验。"""
    assert set(rp.PATHWAY_MODALITIES) == {mc.VISION_IN, mc.AUDIO_IN, mc.AUDIO_OUT, mc.VIDEO_IN}
    assert set(rp.PATHWAY_MODES) == {"native", "bridge", "unavailable"}


def test_c14_pathway_limits_cover_everything_the_negotiator_can_report():
    """协商层能报出来的归因,契约里必须都有对应的一档,否则面板静默失配。"""
    import core.provider_modality as pm

    seen = set()
    for loc in [None] + [s["name"] for s in pm._registry()]:
        for dev in (None, {"device_id": "d", "capabilities": ["screen"]}):
            plan = mc.negotiate(locus=loc, device=dev, asr_available=True, tts_available=True)
            for m in rp.PATHWAY_MODALITIES:
                seen.add(plan.get(m).limited_by)
    assert seen <= set(rp.PATHWAY_LIMITS)


def test_c15_tier_kind_is_unknown_when_the_catalog_is_absent(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "core.model_catalog", None)
    assert rp._tier_kind() == "unknown"


# ══════════════════════════════════════════════════════════════════════════
# D. 归属视图
# ══════════════════════════════════════════════════════════════════════════


def test_d01_undecided_when_nothing_routed():
    view = rp.resolve_thinking_locus_view()
    assert view.is_decided is False
    assert view.locus == "unknown"


def test_d02_no_receipt_module_means_undecided(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "core.thinking_locus", None)
    assert rp.resolve_thinking_locus_view().is_decided is False


def test_d03_carries_the_whole_decision():
    tl.record(
        provider="anthropic",
        model="claude-sonnet-5",
        role="critic",
        is_local=False,
        route_type="gatekeep",
        reason="角色[critic] 把关角色(常驻云端)",
        is_fallback=False,
    )
    view = rp.resolve_thinking_locus_view()
    assert (view.locus, view.provider, view.model, view.role) == (
        "cloud",
        "anthropic",
        "claude-sonnet-5",
        "critic",
    )
    assert view.route_type == "gatekeep"
    assert "把关" in view.reason


def test_d04_reason_is_truncated_not_dropped():
    """丢了就没法在面板上排障;不截断会让一帧被一句话撑爆。"""
    tl.record(provider="openai", model="m", role="critic", is_local=False, route_type="gatekeep", reason="很长" * 500)
    assert 0 < len(rp.resolve_thinking_locus_view().reason) <= rp._REASON_MAX


def test_d05_fallback_is_a_separate_bit_from_locus():
    """「把关角色在本地」既可能是纯本地方案的正常形态,也可能是云端全挂了的降级。"""
    tl.record(provider="ollama", model="m", role="critic", is_local=True, route_type="gatekeep", is_fallback=True)
    view = rp.resolve_thinking_locus_view()
    assert view.locus == "local" and view.is_fallback is True


def test_d06_receipt_blowing_up_degrades_to_undecided(monkeypatch):
    def _boom():
        raise RuntimeError("receipt exploded")

    monkeypatch.setattr(tl, "last", _boom)
    assert rp.resolve_thinking_locus_view().is_decided is False


def test_d07_illegal_locus_from_the_receipt_is_normalised(monkeypatch):
    class _Rec:
        locus = "the_moon"
        provider = "p"
        model = "m"
        role = "r"
        route_type = "gatekeep"
        reason = ""
        is_fallback = False

    monkeypatch.setattr(tl, "last", lambda: _Rec())
    assert rp.resolve_thinking_locus_view().locus == "unknown"


# ══════════════════════════════════════════════════════════════════════════
# E. 接进契约:两位在每一帧里都在,包括兜底帧
# ══════════════════════════════════════════════════════════════════════════


def test_e01_both_views_are_present_on_every_posture():
    d = pc.resolve_render_posture(lifecycle="silent").to_dict()
    assert "pathway" in d and "thinking_locus" in d


def test_e02_anchor_only_fallback_still_carries_both(monkeypatch):
    """兜底最常出现的场合正是第一态 —— 在那里抹成空等于把要修的问题搬进兜底路径。"""
    monkeypatch.setattr(pc, "last_continuum_posture", lambda: None)
    tl.record(provider="anthropic", model="m", role="critic", is_local=False, route_type="gatekeep")
    d = pc.resolve_render_posture(lifecycle="silent").to_dict()
    assert d["source"] == "anchor_only"
    assert d["thinking_locus"]["locus"] == "cloud"
    assert len(d["pathway"]["lanes"]) == 4


def test_e03_pathway_survives_json_round_trip():
    import json

    d = pc.resolve_render_posture(lifecycle="manifest").to_dict()
    again = json.loads(json.dumps(d))
    assert again["pathway"]["lanes"] == d["pathway"]["lanes"]


def test_e04_derived_bits_are_in_the_dict():
    """asdict 只会照搬字段,派生位(native_count / is_decided)会整块漏掉。"""
    d = pc.resolve_render_posture(lifecycle="silent").to_dict()
    assert "native_count" in d["pathway"]
    assert "is_decided" in d["thinking_locus"]


def test_e05_schema_declares_both_and_the_vocabularies():
    sch = pc.render_contract_schema()
    names = [f["name"] for f in sch["fields"]]
    assert "pathway" in names and "thinking_locus" in names
    assert sch["pathway_modes"] == list(rp.PATHWAY_MODES)
    assert sch["thinking_loci"] == list(rp.THINKING_LOCI)
    assert "" in sch["pathway_limits"]  # 空串是合法取值(没被限制),不能被生成端吃掉


def test_e06_reexported_from_the_contract_module():
    """渲染端只该认 core.phase_contract 一个门。"""
    assert pc.ModalityPathwayView is rp.ModalityPathwayView
    assert pc.ThinkingLocusView is rp.ThinkingLocusView
    for name in ("ModalityPathwayView", "ThinkingLocusView", "resolve_pathway_view"):
        assert name in pc.__all__


def test_e07_contract_field_count_matches_the_dataclass():
    import dataclasses

    d = pc.resolve_render_posture(lifecycle="silent").to_dict()
    assert set(d) == {f.name for f in dataclasses.fields(pc.RenderPosture)}
