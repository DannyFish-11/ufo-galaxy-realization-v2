"""tests/test_render_contract_fusion.py — 渲染契约与阈限态的融合钉子

这份测试钉的不是"函数返回值对不对"，是**几条结构性事实**——它们一旦悄悄回退，
症状会出现在完全不相干的地方（面板上一片空白、动画对不上状态），极难回溯。

钉四件事：

1. **返回弧可分辨**。``formless`` 与 ``receding`` 的公共三态投影都是 ``silent``，
   如果渲染契约也把它们抹平，「刚做完正在退场」与「静息」在渲染端就是同一个数。
   旧的一维投影正是如此（实测两者输出逐位相同）。

2. **两根轴不能互相冒充**。``lifecycle``（主体生命周期，桥广播的那根）与
   ``continuum_phase``（内部连续体姿态）是不同的轴，``TriState`` 的类文档明确
   禁止混淆。契约必须能表达 ``lifecycle=silent`` 且 ``continuum_phase=receding``
   这种组合——那正是"主体看着安静，其实刚做完在收尾"。

3. **禁止转移不可被表达**。``manifest → liminal`` 在 PHASE_TRANSITION_TABLE 里是
   Forbidden（"结构不能不经 receding 就解体"）。``next_phases`` 不许给出它。

4. **阈限内容与阈限相位真的耦合**。预演登记必须发生在 LIMINAL 段内；不在那儿要
   留下痕迹（warning），而不是静静地成立。
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from core.continuum.types import ContinuumPhase, ContinuumState, RuntimeDomain
from core.phase_contract import (
    FORBIDDEN_TRANSITIONS,
    LIFECYCLE_STATES,
    PHASE_TRANSITIONS,
    RENDER_PHASES,
    SimulationSummary,
    resolve_phase_posture,
    resolve_render_posture,
    tri_state_of,
)


def _state(phase: ContinuumPhase, **kw) -> ContinuumState:
    base = dict(presence_intensity=0.7, coherence=0.6, ambiguity=0.4, stability=0.9)
    base.update(kw)
    return ContinuumState(phase=phase, **base)


# ── 1. 返回弧可分辨 ────────────────────────────────────────────────────────


def test_legacy_projection_flattens_the_return_arc():
    """先钉住"旧契约确实抹平了返回弧"——这是本次改造的前提，不是假设。

    如果哪天这条不再成立（旧投影自己修好了），本文件其余的钉子就该重新审视。
    """
    old_formless = resolve_phase_posture("static", _state(ContinuumPhase.FORMLESS))
    old_receding = resolve_phase_posture("static", _state(ContinuumPhase.RECEDING))
    assert old_formless.to_dict() == old_receding.to_dict(), "旧的一维投影本就分不出这两相"


def test_render_contract_distinguishes_receding_from_formless():
    """新契约必须分得出。这是整件事的核心。"""
    f = resolve_render_posture("silent", _state(ContinuumPhase.FORMLESS))
    r = resolve_render_posture("silent", _state(ContinuumPhase.RECEDING))

    assert f.continuum_phase == "formless" and r.continuum_phase == "receding"
    assert r.is_returning is True and f.is_returning is False
    # ExpressionEngine 对这两相给出的形态本就不同，契约必须原样带出来
    assert r.form_signature == "collapsing_field", "receding 的形态是坍缩场"
    assert f.form_signature == "none", "formless 无形态"
    assert r.texture_hint and not f.texture_hint, "receding 有质感提示（soft_dissolve），formless 没有"
    assert f.to_dict() != r.to_dict()


def test_tri_state_projection_still_collapses_both():
    """公共三态投影仍然把两相都折叠成 silent —— 它对 API 消费者是对的，
    所以不动它。正因为它这样，渲染端才必须用 continuum_phase 而不是 tri_state。"""
    assert tri_state_of("formless") == "silent"
    assert tri_state_of("receding") == "silent"


# ── 2. 两根轴各归其位 ──────────────────────────────────────────────────────


def test_two_axes_are_independent():
    """主轴由调用方给，副轴从 state 读，互不覆盖。

    旧的 resolve_render_posture 只读 state.phase 就返回，等于用副轴冒充主轴——
    接到桥上会给出与 payload.phase 不一致的相位帧。
    """
    p = resolve_render_posture("silent", _state(ContinuumPhase.RECEDING))
    assert p.lifecycle == "silent", "主轴照实用传入值"
    assert p.continuum_phase == "receding", "副轴照实读 state"
    assert p.is_returning is True, "主体看着安静，其实刚做完在收尾"


@pytest.mark.parametrize("life", LIFECYCLE_STATES)
@pytest.mark.parametrize("phase", RENDER_PHASES)
def test_every_axis_combination_is_expressible(life, phase):
    """两根轴的任意组合都不该炸，也不该被悄悄改写成别的值。"""
    p = resolve_render_posture(life, _state(ContinuumPhase(phase)))
    assert p.lifecycle == life
    assert p.continuum_phase == phase


def test_unknown_lifecycle_falls_back_to_silent():
    assert resolve_render_posture("不存在的相位", _state(ContinuumPhase.LIMINAL)).lifecycle == "silent"


# ── 3. 转移拓扑 ────────────────────────────────────────────────────────────


def test_next_phases_never_offers_a_forbidden_transition():
    """契约给出的合法去向里，不许出现转移表明令禁止的那些。"""
    for src, targets in PHASE_TRANSITIONS.items():
        for dst in targets:
            assert (src, dst) not in FORBIDDEN_TRANSITIONS, f"{src}→{dst} 被禁止却出现在 next_phases"


def test_manifest_can_only_exit_through_receding():
    """从表达期出来的动作永远是「消散」，绝不是「退回上一档」。

    旧契约用 retreat_tendency 让 manifest 的深度朝 liminal 的锚点漂移，表达的正是
    这个被禁止的转移。
    """
    assert PHASE_TRANSITIONS["manifest"] == ("receding",)
    assert ("manifest", "liminal") in FORBIDDEN_TRANSITIONS
    p = resolve_render_posture("manifest", _state(ContinuumPhase.MANIFEST, retreat_tendency=1.0))
    assert p.next_phases == ("receding",), "即便回撤倾向拉满，出口也只有 receding"


def test_cycle_closes():
    """四相构成闭环：从 formless 出发，沿合法转移能回到 formless。"""
    seen, cur = [], "formless"
    for _ in range(len(RENDER_PHASES) + 1):
        seen.append(cur)
        cur = PHASE_TRANSITIONS[cur][0]  # 取主路径（liminal 的第一个是 manifest）
        if cur == "formless":
            break
    assert cur == "formless", "环没闭上"
    assert "receding" in seen, "闭环必须经过返回弧"


# ── 4. 阈限内容与阈限相位的耦合 ────────────────────────────────────────────


def test_second_dimension_is_carried():
    p = resolve_render_posture("manifest", _state(ContinuumPhase.MANIFEST, runtime_domain=RuntimeDomain.CROSS_DEVICE))
    assert p.runtime_domain == "cross_device", "第二维必须到达渲染端"


def test_simulation_summary_rides_along():
    sim = SimulationSummary(
        is_active=True,
        simulation_kind="sandbox",
        candidate_paths=("直接调用", "先查后调"),
        committed_path="先查后调",
        is_committed=True,
        step_count=4,
        scenario_label="打开应用",
    )
    p = resolve_render_posture("liminal", _state(ContinuumPhase.LIMINAL), liminal_activity="rehearsing", simulation=sim)
    d = p.to_dict()
    assert d["liminal_activity"] == "rehearsing"
    assert d["simulation"]["candidate_paths"] == ["直接调用", "先查后调"], "候选路径是阈限态的可视内容"
    assert d["simulation"]["committed_path"] == "先查后调"


def test_rehearsal_outside_liminal_leaves_a_trace(caplog):
    """不变量：在非阈限相位登记内容要留下 warning。

    不抛异常（可见性绝不拖垮请求），但必须有痕迹——否则「预演跑在阈限态里」
    就只是靠时序巧合成立，哪天有人挪动 advance(MANIFEST) 的触发点，阈限态的
    可视内容会静默落空。
    """
    from core.desktop_presence_runtime import RuntimeSession, TriState

    s = RuntimeSession(source="test")
    s.advance(TriState.MANIFEST)
    with caplog.at_level(logging.WARNING):
        s.enter_liminal_activity("rehearsing")
    assert any("阈限内容登记于非阈限相位" in r.message for r in caplog.records)


def test_rehearsal_inside_liminal_is_silent(caplog):
    from core.desktop_presence_runtime import RuntimeSession, TriState

    s = RuntimeSession(source="test")
    s.advance(TriState.LIMINAL)
    with caplog.at_level(logging.WARNING):
        s.enter_liminal_activity("rehearsing", {"candidate_paths": ["A", "B"]})
    assert not [r for r in caplog.records if "阈限内容登记于非阈限相位" in r.message]
    assert s.liminal_activity == "rehearsing"


def test_activity_clears_on_lifecycle_transitions():
    """回 SILENT 摘要一并清空；进 MANIFEST 只清活动、保留摘要。

    保留是有意的：表达期面板仍要能显示"按哪条候选提交的"——那是结果不是活动。
    """
    from core.desktop_presence_runtime import RuntimeSession, TriState

    s = RuntimeSession(source="test")
    s.advance(TriState.LIMINAL)
    s.enter_liminal_activity("rehearsing", {"candidate_paths": ["A"]})

    s.advance(TriState.MANIFEST)
    assert s.liminal_activity == "none"
    assert s.simulation_summary is not None, "表达期仍要能显示按哪条提交的"

    s.advance(TriState.SILENT)
    assert s.simulation_summary is None, "回静息才真正清空"


def test_context_isolation_across_concurrent_requests():
    """并发请求之间阈限内容不许串台，且请求结束后登记是空操作。"""
    from core.desktop_presence_runtime import RuntimeSession, TriState
    from core.liminal_activity import bind_runtime_session, note_liminal_activity, unbind_runtime_session

    async def one(tag):
        s = RuntimeSession(source=tag)
        s.advance(TriState.LIMINAL)
        tok = bind_runtime_session(s)
        try:
            await asyncio.sleep(0)
            note_liminal_activity("rehearsing", {"candidate_paths": [f"{tag}-A"]})
            await asyncio.sleep(0)
            return s.simulation_summary["candidate_paths"]
        finally:
            unbind_runtime_session(tok)

    async def main():
        return await asyncio.gather(*[one(f"r{i}") for i in range(3)])

    got = asyncio.run(main())
    assert got == [["r0-A"], ["r1-A"], ["r2-A"]], "并发请求的阈限内容串台了"
    assert note_liminal_activity("rehearsing") is False, "请求外登记必须是空操作"


# ── 降级如实标注 ──────────────────────────────────────────────────────────


def test_degradation_is_labelled_not_faked(monkeypatch):
    """拿不到 continuum 时如实标注 anchor_only，但主轴仍然可信。

    主轴来自在场运行时，与 continuum 是两条独立链路——continuum 没跑不代表
    主体生命周期不知道自己在哪。

    「拿不到 continuum」这个前提必须**安排出来**，不能假设它默认成立：
    ``last_continuum_posture()`` 读的是进程级 OpenClawd 单例里的最近一拍，
    只要同一进程里任何一条先跑的用例建过那个单例，这里就拿得到 state，
    于是 source 变成 continuum，这条判据在全量里红、单跑绿。
    把前提写出来，判据才与执行顺序无关。
    """
    monkeypatch.setattr("core.phase_contract.last_continuum_posture", lambda: None)
    p = resolve_render_posture("manifest", None)
    assert p.source == "anchor_only"
    assert p.lifecycle == "manifest", "主轴不该被降级抹掉"
    assert p.is_returning is False, "没有真实相位时不许凭空猜一段返回弧"


def test_degraded_state_is_surfaced():
    st = ContinuumState.degraded_fallback("continuum_internal_error")
    p = resolve_render_posture("silent", st)
    assert p.degraded is True
    assert p.degrade_reason == "continuum_internal_error"


# ── 相位闸门驱动预演 ──────────────────────────────────────────────────────


def _tools():
    return [{"function": {"name": "probe"}}]


def test_gate_allows_when_there_is_no_lifecycle_at_all():
    """没有在场运行时（直接调 OpenClawd / ambient 回路 / 测试裸跑）必须放行。

    这一条是整个闸门最危险的地方：判否会把预演在这些路径上**静默关掉**，
    而症状（"复杂任务不再预演了"）根本不会指向相位闸门。闸门管的是"相位不对
    时别推演"，不是"没有相位时别推演"。
    """
    from core.liminal_activity import in_deliberation_window
    from core.liminal_rehearsal import should_rehearse

    assert in_deliberation_window() is True
    assert should_rehearse(0.9, _tools()) is True


def test_gate_opens_in_liminal_and_closes_in_manifest(caplog):
    from core.desktop_presence_runtime import RuntimeSession, TriState
    from core.liminal_activity import bind_runtime_session, in_deliberation_window, unbind_runtime_session
    from core.liminal_rehearsal import should_rehearse

    s = RuntimeSession(source="test")
    s.advance(TriState.LIMINAL)
    tok = bind_runtime_session(s)
    try:
        assert in_deliberation_window() is True
        assert should_rehearse(0.9, _tools()) is True

        s.advance(TriState.MANIFEST)
        with caplog.at_level(logging.WARNING):
            assert in_deliberation_window() is False
        assert any("审议窗口已关闭" in r.message for r in caplog.records), "窗口关闭必须留痕，不许静默"
        assert should_rehearse(0.9, _tools()) is False
    finally:
        unbind_runtime_session(tok)


def test_forced_mode_cannot_bypass_the_phase_gate(monkeypatch):
    """GALAXY_LIMINAL_REHEARSAL=1 是成本开关，不是语义豁免。

    主体已经落手之后，"在动手前先推演一遍"这句话本身就不成立，再便宜也不该做。
    """
    from core.desktop_presence_runtime import RuntimeSession, TriState
    from core.liminal_activity import bind_runtime_session, unbind_runtime_session
    from core.liminal_rehearsal import should_rehearse

    monkeypatch.setenv("GALAXY_LIMINAL_REHEARSAL", "1")
    s = RuntimeSession(source="test")
    s.advance(TriState.LIMINAL)
    s.advance(TriState.MANIFEST)
    tok = bind_runtime_session(s)
    try:
        assert should_rehearse(0.1, _tools()) is False, "强制模式也不该越过相位闸门"
    finally:
        unbind_runtime_session(tok)


def test_gate_does_not_change_cost_semantics(monkeypatch):
    """闸门只加前提，不改原有的成本判据。"""
    from core.desktop_presence_runtime import RuntimeSession, TriState
    from core.liminal_activity import bind_runtime_session, unbind_runtime_session
    from core.liminal_rehearsal import should_rehearse

    monkeypatch.delenv("GALAXY_LIMINAL_REHEARSAL", raising=False)
    s = RuntimeSession(source="test")
    s.advance(TriState.LIMINAL)
    tok = bind_runtime_session(s)
    try:
        assert should_rehearse(0.1, _tools()) is False, "复杂度不够仍然否决"
        assert should_rehearse(0.9, []) is False, "没有工具仍然否决"
        assert should_rehearse(0.9, _tools()) is True
    finally:
        unbind_runtime_session(tok)


def test_commit_to_manifest_drives_the_phase_and_closes_the_window():
    """认知层宣告审议结束 → 相位前进 → 窗口关闭。

    这是「非流式路径也有审议窗口」的实现：此前非流式在派发**之前**就进 MANIFEST，
    窗口宽度为零，相位闸门会把那条路径上的预演整个关掉。
    """
    from core.desktop_presence_runtime import RuntimeSession, TriState
    from core.liminal_activity import (
        bind_runtime_session,
        commit_to_manifest,
        in_deliberation_window,
        unbind_runtime_session,
    )

    s = RuntimeSession(source="test")
    s.advance(TriState.LIMINAL)
    calls = []

    def _enter_manifest():
        if s.tristate is not TriState.LIMINAL:  # 与真实实现同款幂等守卫
            return
        s.advance(TriState.MANIFEST)
        calls.append(1)

    s.manifest_hook = _enter_manifest
    tok = bind_runtime_session(s)
    try:
        assert in_deliberation_window() is True
        assert commit_to_manifest("react_loop") is True
        assert s.tristate is TriState.MANIFEST
        assert in_deliberation_window() is False

        commit_to_manifest("again")
        assert len(calls) == 1, "重复宣告不该重复推进相位"
    finally:
        unbind_runtime_session(tok)

    s.advance(TriState.SILENT)
    assert [t[0].value for t in s.transitions] == ["liminal", "manifest", "silent"]


def test_missing_signal_still_leaves_a_complete_trajectory():
    """信号送不达时（没绑 hook）宣告返回 False，而 finally 兜底仍补齐三段轨迹。

    下游（审计、跨设备同步）看到的相位序列在两种情况下完全一致。
    """
    from core.desktop_presence_runtime import RuntimeSession, TriState
    from core.liminal_activity import bind_runtime_session, commit_to_manifest, unbind_runtime_session

    s = RuntimeSession(source="test")
    s.advance(TriState.LIMINAL)
    tok = bind_runtime_session(s)
    try:
        assert commit_to_manifest("x") is False, "没绑 hook 时如实返回未送达"
    finally:
        unbind_runtime_session(tok)

    if s.tristate is TriState.LIMINAL:  # handle_request 的 finally 兜底
        s.advance(TriState.MANIFEST)
    s.advance(TriState.SILENT)
    assert [t[0].value for t in s.transitions] == ["liminal", "manifest", "silent"]


def test_runtime_binds_the_manifest_hook_before_dispatch():
    """在场运行时必须在派发【之前】把 manifest_hook 绑好。

    绑晚了认知层的宣告就落空，非流式路径会退回"窗口宽度为零"。按 AST 比较
    绑定与派发的行号，不钉源码排版。
    """
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "core" / "desktop_presence_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    bind_lines = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Attribute) and t.attr == "manifest_hook" for t in n.targets)
    ]
    dispatch_lines = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_dispatch"
    ]
    assert bind_lines, "运行时没有绑定 manifest_hook —— 认知层的宣告会落空"
    assert dispatch_lines, "找不到 _dispatch 调用"
    assert min(bind_lines) < min(
        dispatch_lines
    ), f"manifest_hook 绑在第 {min(bind_lines)} 行，晚于派发的第 {min(dispatch_lines)} 行"


def test_cognition_commits_before_the_react_loop():
    """认知层必须在真实 ReAct 循环【之前】宣告审议结束。

    宣告晚了，工具已经开始执行而相位还停在 LIMINAL——面板会把落手期画成思考期。
    """
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "core" / "openclawd.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    commit_lines = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_commit_manifest"
    ]
    react_lines = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_react_loop"
    ]
    assert commit_lines, "认知层没有宣告审议结束"
    assert react_lines, "找不到 _react_loop 调用"
    assert min(commit_lines) < min(
        react_lines
    ), f"宣告在第 {min(commit_lines)} 行，晚于 ReAct 循环的第 {min(react_lines)} 行"


def test_runtime_commits_to_manifest_at_the_dispatch_chokepoint():
    """派发返回处必须有收口的 ``_enter_manifest()``，且排在 finally 兜底之前。

    为什么必须有这个收口点
    ----------------------
    更早的两条信号（流式首 token、认知层在 ReAct 前显式宣告）各自更精确，但都
    **只覆盖部分路径**。真跑一次请求实测到漏网：它走的是
    ``core/agent/execution_planner.py`` 那条线，压根不经过 handle_chat 的 ReAct
    循环，于是显式宣告从没被调到，整个派发停在 LIMINAL —— MANIFEST 宽度为零。

    认知层的出口不止一个，逐个去打提交点必然漏。派发返回是**所有路径的必经之地**。
    实测确认它确实开火（advance(MANIFEST) 的调用栈指到这一行），且因为幂等守卫
    只开一次，finally 的兜底不会重复推进。
    """
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "core" / "desktop_presence_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    enter_calls = sorted(
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_enter_manifest"
    )
    dispatch_calls = sorted(
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_dispatch"
    )
    assert dispatch_calls, "找不到 _dispatch 调用"
    after_dispatch = [ln for ln in enter_calls if ln > dispatch_calls[0]]
    assert len(after_dispatch) >= 2, (
        f"派发之后的 _enter_manifest() 少于 2 处（收口点 + finally 兜底），实际在 {after_dispatch}"
        " —— 收口点若被删掉，不经过 ReAct 的认知路径会让 MANIFEST 宽度归零"
    )


def test_pre_dispatch_manifest_only_survives_behind_the_kill_switch():
    """派发前的 ``_enter_manifest()`` **只允许**出现在回退开关分支里。

    直线路径上的那一次正是"审议窗口在非流式路径上宽度为零"的来源，必须没有。
    但 ``GALAXY_MANIFEST_ON_FIRST_TOKEN=0`` 这个逃生口是文档承诺过的——它要能
    **整体**退回旧时序，所以那一支里的调用是对的，不能一刀切禁掉。

    这条判据是被实测逼出来的：先把派发前的调用无条件删掉，
    ``test_kill_switch_reverts_to_old_behavior`` 当场变红——逃生口被我弄坏了。
    """
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "core" / "desktop_presence_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    dispatch_line = min(
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "_dispatch"
    )

    # 回退开关分支（`elif not _manifest_on_first_token:` / `if not ...:`）的行号区间，
    # 以及流式钩子等嵌套函数体——这两类里的调用是合规的。
    allowed: list = []
    for n in ast.walk(tree):
        if isinstance(n, ast.If):
            test = n.test
            if (
                isinstance(test, ast.UnaryOp)
                and isinstance(test.op, ast.Not)
                and isinstance(test.operand, ast.Name)
                and test.operand.id == "_manifest_on_first_token"
            ):
                allowed.append((n.lineno, max(getattr(x, "lineno", n.lineno) for x in ast.walk(n))))
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in (
            "_hooked_on_delta",
            "_enter_manifest",
        ):
            allowed.append((n.lineno, max(getattr(x, "lineno", n.lineno) for x in ast.walk(n))))

    offenders = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "_enter_manifest"
        and n.lineno < dispatch_line
        and not any(lo <= n.lineno <= hi for lo, hi in allowed)
    ]
    assert not offenders, (
        f"派发前第 {offenders} 行在回退开关分支之外直接进 MANIFEST —— "
        "非流式的审议窗口会退回零宽，相位闸门驱动的预演在那条路径上会失效"
    )


def test_kill_switch_branch_exists():
    """回退开关那一支必须还在 —— 它是文档承诺的逃生口。"""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "core" / "desktop_presence_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = any(
        isinstance(n, ast.If)
        and isinstance(n.test, ast.UnaryOp)
        and isinstance(n.test.op, ast.Not)
        and isinstance(n.test.operand, ast.Name)
        and n.test.operand.id == "_manifest_on_first_token"
        and any(
            isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id == "_enter_manifest"
            for c in ast.walk(n)
        )
        for n in ast.walk(tree)
    )
    assert found, "GALAXY_MANIFEST_ON_FIRST_TOKEN=0 的回退分支不见了 —— 逃生口失效"
