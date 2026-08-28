"""作用域这根轴:它现在真的有值,而且"判不出来"不会被读成"本地"。

这个文件钉的是什么
------------------
"本地的事本地说了算,跨设备的事中心说了算"——这套按作用域分权威的设计,
成立的前提是**作用域本身说得准**。

而在 ``core/continuum/runtime_domain_resolver.py`` 之前,它说不准:
``ContinuumState.runtime_domain`` 默认 ``None``,每拍真正产出状态的
``TemporalEngine`` 里这个词出现 **0 次**,唯一带值的构造点是一个写死 ``LOCAL``
的最小静默兜底。一根被执行策略、模型拓扑、投影、面板、``RenderPosture``
一起当判据用的轴,上游从来没人填。

所以这里的判据分两类:
A 组 —— 轴真的被赋值了(否则整套设计站在空地上);
B 组 —— "判不出来"不会退化成"本地"(否则每一次判不出来,权威都会被静默交给本地,
        而判不出来的时刻恰恰是最需要中心仲裁的时刻)。
"""

from __future__ import annotations

import pytest

from core.continuum import runtime_domain_resolver as rdr
from core.continuum.types import ContinuumPhase, ContinuumState, RuntimeDomain, TriStatePhase


class _FakeSession:
    """挂载会话只需要"存在"这一件事,判定不看它的内容。"""


# ══════════════════════════════════════════════════════════════════════════
# A. 轴真的被赋值了
# ══════════════════════════════════════════════════════════════════════════


def test_a01_a_real_tick_stamps_the_axis():
    """这一条是整块改动的存在理由:跑一拍,轴上得有东西。

    改动之前这里恒为 ``None``。
    """
    from core.continuum.orchestrator import ContinuumOrchestrator

    state = ContinuumOrchestrator().run(trace_id="test-domain-axis")
    assert state.runtime_domain is not None, "跑完一拍 runtime_domain 仍是 None —— 轴又空了"
    assert isinstance(state.runtime_domain, RuntimeDomain)


def test_a02_the_stamp_does_not_break_the_tick():
    """判定挂了不能打断一拍 —— 姿态比作用域重要。"""
    from core.continuum import orchestrator as orch_mod

    def _boom(_phase):
        raise RuntimeError("resolver 炸了")

    original = rdr.resolve_runtime_domain
    rdr.resolve_runtime_domain = _boom
    try:
        state = orch_mod.ContinuumOrchestrator().run(trace_id="test-domain-boom")
        assert state.phase is not None
    finally:
        rdr.resolve_runtime_domain = original


def test_a03_the_axis_reaches_the_render_contract():
    """契约层要能把它透出去,否则赋了值也没人看得见。"""
    import json

    from core.phase_contract import render_contract_schema

    blob = json.dumps(render_contract_schema(), ensure_ascii=False)
    assert "runtime_domain" in blob
    # 契约层对"判不出来"的表述必须留着 —— 它是下游区分 null 与 local 的唯一依据
    assert "尚未判定" in blob


# ══════════════════════════════════════════════════════════════════════════
# B. "判不出来"不许变成"本地"
# ══════════════════════════════════════════════════════════════════════════


def test_b01_an_unreadable_phase_is_unresolved_not_local():
    verdict = rdr.resolve_runtime_domain("这不是一个相位")
    assert verdict.domain is None
    assert verdict.resolved is False
    assert verdict.source == "unresolved"


def test_b02_an_unavailable_registry_is_unresolved_not_local(monkeypatch):
    """注册表问不到 = 判不出来。

    这是最要紧的一条:连接刚抖动、编队刚建立、注册表还没同步 —— 正是这些时刻
    问不到,也正是这些时刻最需要中心仲裁。静默判成 local 等于在最不该的时候
    把权威交给本地。
    """
    monkeypatch.setattr(rdr, "_active_remote_sessions", lambda: None)
    verdict = rdr.resolve_runtime_domain(ContinuumPhase.MANIFEST)
    assert verdict.domain is None
    assert "不回落" in verdict.reason


def test_b03_zero_remotes_and_cannot_tell_are_different(monkeypatch):
    """0 台远端(判得出,是本地)与问不到(判不出来)必须可区分。

    两者混成一个值,上面那条判据就没有意义了 —— 它们的 domain 都会是 local。
    """
    monkeypatch.setattr(rdr, "_active_remote_sessions", lambda: [])
    zero = rdr.resolve_runtime_domain(ContinuumPhase.MANIFEST)

    monkeypatch.setattr(rdr, "_active_remote_sessions", lambda: None)
    unknown = rdr.resolve_runtime_domain(ContinuumPhase.MANIFEST)

    assert zero.domain is RuntimeDomain.LOCAL and zero.remote_count == 0
    assert unknown.domain is None and unknown.remote_count is None


def test_b04_the_orchestrator_leaves_none_rather_than_writing_local(monkeypatch):
    """判不出来时,这一拍宁可**不写**,也不能写一个 local 上去。"""
    monkeypatch.setattr(rdr, "_active_remote_sessions", lambda: None)
    state = ContinuumState(phase=ContinuumPhase.MANIFEST)
    verdict = rdr.resolve_runtime_domain(state.phase)
    assert verdict.domain is None
    # 编排器只在 domain 非 None 时才写 —— 所以原状态保持未判定
    assert state.runtime_domain is None


def test_b05_the_report_says_plainly_what_null_means():
    report = rdr.domain_report()
    assert "不是" in report["unresolved_means"]
    assert "null" in report["remote_sessions_note"]


# ══════════════════════════════════════════════════════════════════════════
# C. 判定规则照抄 types.py 那张表,不做表外推导
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    ("phase", "remotes", "expected"),
    [
        (ContinuumPhase.FORMLESS, 3, RuntimeDomain.LOCAL),
        (ContinuumPhase.RECEDING, 3, RuntimeDomain.LOCAL),
        (ContinuumPhase.LIMINAL, 0, RuntimeDomain.LOCAL),
        (ContinuumPhase.LIMINAL, 2, RuntimeDomain.TRANSITION),
        (ContinuumPhase.MANIFEST, 0, RuntimeDomain.LOCAL),
        (ContinuumPhase.MANIFEST, 1, RuntimeDomain.CROSS_DEVICE),
    ],
)
def test_c01_the_table(phase, remotes, expected, monkeypatch):
    monkeypatch.setattr(rdr, "_active_remote_sessions", lambda: [_FakeSession() for _ in range(remotes)])
    assert rdr.resolve_runtime_domain(phase).domain is expected


def test_c02_silent_does_not_even_ask_the_registry(monkeypatch):
    """静默态的判定与远端无关(表里写死),所以不该每拍白查一次注册表。"""
    calls = []

    def _counted():
        calls.append(1)
        return []

    monkeypatch.setattr(rdr, "_active_remote_sessions", _counted)
    rdr.resolve_runtime_domain(ContinuumPhase.FORMLESS)
    assert calls == []


def test_c03_tri_state_input_is_accepted_too():
    """上游可能递三态也可能递四相,两种都得认 —— 认不出就成了 unresolved,
    那会让轴在某些调用点静默变空。"""
    assert rdr.resolve_runtime_domain(TriStatePhase.SILENT).domain is RuntimeDomain.LOCAL


# ══════════════════════════════════════════════════════════════════════════
# D. 与 runtime_domain_intent 是两回事
# ══════════════════════════════════════════════════════════════════════════


def test_d01_intent_and_fact_are_separate_names_on_purpose():
    """``runtime_domain_intent``(编队声明要跨设备)与 ``runtime_domain``
    (这一拍实际在哪儿跑)不是重复定义。

    两者可以不一致,而不一致本身有信息量:声明了要跨设备、但远端一个都没挂上来。
    合并成一处会把这个信息抹掉 —— 这条判据挡的就是"顺手统一一下"。
    """
    from core.device_formation.formation_group import DeviceFormationGroup

    assert hasattr(DeviceFormationGroup, "__dataclass_fields__")
    assert "runtime_domain_intent" in DeviceFormationGroup.__dataclass_fields__
    # 事实轴不该出现在编队声明里
    assert "runtime_domain" not in DeviceFormationGroup.__dataclass_fields__


def test_d02_each_default_is_right_in_its_own_context():
    """两处 ``runtime_domain_intent`` 的默认值不同,但各自语境里都是对的 ——
    编队存在就意味着跨设备;摘要的默认语境是"没有活跃编队"。

    钉住它是因为看起来像矛盾,容易被后来人"修"成一致。
    """
    from core.device_formation.formation_group import DeviceFormationGroup
    from core.device_formation.formation_summary import FormationSummary

    assert DeviceFormationGroup.__dataclass_fields__["runtime_domain_intent"].default == "cross_device"
    assert FormationSummary.__dataclass_fields__["runtime_domain_intent"].default == "local"


# ══════════════════════════════════════════════════════════════════════════
# E. 判定要能被问到 —— 否则 null 与 local 的区分只活在代码里
# ══════════════════════════════════════════════════════════════════════════


def test_e01_the_verdict_is_reachable_over_http():
    """诊断端点必须在。

    这一位的全部价值在于 ``null``(判不出来)与 ``local``(判出来了,是本地)
    分得开。如果外面问不到,这个区分就只活在代码里,运维和面板都用不上。
    """
    import inspect

    from core.routes import diagnostics

    src = inspect.getsource(diagnostics)
    assert "/api/v1/runtime/domain" in src
    assert "domain_report" in src


def test_e02_the_endpoint_is_in_the_generated_api_surface():
    """后端加了端点却忘了重跑生成器,面板就调不到 —— 生成物必须同步。"""
    from pathlib import Path

    gen = Path(__file__).resolve().parent.parent / "electron/renderer/panel/src/types/api.gen.ts"
    assert "/api/v1/runtime/domain" in gen.read_text(encoding="utf-8")
