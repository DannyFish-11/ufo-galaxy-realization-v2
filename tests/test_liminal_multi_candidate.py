"""tests/test_liminal_multi_candidate.py
==========================================
阈限态(第二态)多方案模拟/决策回归(阶段1c)。

所有者要 LIMINAL 承载"做各种决策并进行模拟、选择模式",MANIFEST 做实际决策并执行。
Gecko 预演(core/liminal_rehearsal)原只单方案预演+重试;这里扩展为【多候选:生成多策略
→ 各自沙盘模拟 → 排名选优】,选中项即"在阈限态做出的决策",并可喂 LIMINAL 投影
(SimulationSummary)展示"候选 vs 已提交"。默认候选数=1(零行为变化)。
"""

from __future__ import annotations

import pytest

from core.liminal_rehearsal import (
    CandidatePlan,
    LiminalRehearsal,
    MultiCandidateOutcome,
    RehearsalOutcome,
    n_candidates,
)


def _cp(label, *, success, steps, attempts=1):
    oc = RehearsalOutcome(
        success=success,
        attempts=attempts,
        trajectory=[{"tool": "t", "args": {}, "result": {}} for _ in range(steps)],
    )
    return CandidatePlan(label=label, approach=label, outcome=oc)


# ── 决策/排名(纯逻辑,无 LLM)──────────────────────────────────────────────
def test_selects_success_over_failure():
    plans = [_cp("A", success=False, steps=1), _cp("B", success=True, steps=3), _cp("C", success=False, steps=2)]
    best = min(range(len(plans)), key=lambda i: plans[i].rank_key())
    mc = MultiCandidateOutcome(candidates=plans, selected_index=best)
    assert mc.selected.label == "B", "成功候选必须优先于失败候选"


def test_selects_fewer_steps_among_successes():
    plans = [_cp("A", success=True, steps=5), _cp("B", success=True, steps=2), _cp("C", success=True, steps=4)]
    best = min(range(len(plans)), key=lambda i: plans[i].rank_key())
    assert plans[best].label == "B", "都成功时选步数最少的"


def test_simulation_summary_kwargs_shows_candidates_and_committed():
    plans = [_cp("快", success=True, steps=2), _cp("稳", success=False, steps=1)]
    mc = MultiCandidateOutcome(candidates=plans, selected_index=0)
    kw = mc.simulation_summary_kwargs(is_active=True, scenario_label="打开应用")
    assert kw["candidate_paths"] == ["快", "稳"], "投影要展示所有候选路径"
    assert kw["committed_path"] == "快", "选中且成功的候选 = 已提交路径"
    assert kw["simulation_kind"] == "sandbox" and kw["is_active"] is True

    # build_simulation_summary 能消费这些 kwargs(与投影层对接)
    from core.liminal_space_mapping import build_simulation_summary

    summ = build_simulation_summary(**kw)
    assert summ.candidate_paths == ["快", "稳"] and summ.committed_path == "快" and summ.is_committed is True


def test_committed_path_none_when_selected_failed():
    plans = [_cp("A", success=False, steps=1)]
    mc = MultiCandidateOutcome(candidates=plans, selected_index=0)
    assert mc.simulation_summary_kwargs()["committed_path"] is None, "选中项都失败则未提交"


def test_n_candidates_env(monkeypatch):
    monkeypatch.delenv("GALAXY_REHEARSAL_CANDIDATES", raising=False)
    # 默认 2 而不是 1。改默认的理由不是"多点更好"：candidate_paths / committed_path
    # 只在多候选分支里产出（见 openclawd 的 _ncand > 1 判断），默认 1 时
    # simulation_summary 从不产出，阈限态的可视内容整条链路失效——那等于接了一根
    # 没有信号的线。2 是"能看见权衡"的最小值：有两条候选才谈得上"在评估多个"。
    assert n_candidates() == 2, "默认多候选，否则阈限态的可视内容无从产出"
    monkeypatch.setenv("GALAXY_REHEARSAL_CANDIDATES", "1")
    assert n_candidates() == 1, "显式设 1 可退回单方案"
    monkeypatch.setenv("GALAXY_REHEARSAL_CANDIDATES", "3")
    assert n_candidates() == 3
    monkeypatch.setenv("GALAXY_REHEARSAL_CANDIDATES", "99")
    assert n_candidates() == 5, "上限封顶 5"
    monkeypatch.setenv("GALAXY_REHEARSAL_CANDIDATES", "x")
    assert n_candidates() == 2, "非法值回落到默认值"


# ── rehearse_options 端到端(假路由)────────────────────────────────────────
class _Resp:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeRouter:
    """按 prompt 内容路由:候选生成→JSON数组;裁判→complete;模拟器→response。
    chat_with_tools 首轮给一个只读工具调用,次轮收手 → 每候选一步轨迹。"""

    def __init__(self, n_approaches=3):
        self._n = n_approaches

    async def chat(self, messages, temperature=0.0, max_tokens=0):
        prompt = messages[-1]["content"]
        if "种" in prompt and "策略" in prompt:
            arr = [{"label": f"方案{i+1}", "approach": f"策略{i+1}"} for i in range(self._n)]
            import json as _j

            return _Resp(content=_j.dumps(arr, ensure_ascii=False))
        if "任务完成度裁判" in prompt:
            return _Resp(content='{"complete": true}')
        return _Resp(content='{"response": {"ok": true}, "state_delta": {}}')

    async def chat_with_tools(self, messages, tools=None, max_tokens=0):
        # 若本轮已经喂过工具结果(出现 role=tool),就收手表示完成。
        if any(m.get("role") == "tool" for m in messages):
            return _Resp(content="完成")
        return _Resp(
            content="",
            tool_calls=[{"id": "c1", "function": {"name": "node__fs__read_file", "arguments": '{"path":"/a"}'}}],
        )


@pytest.mark.asyncio
async def test_rehearse_options_single_candidate_passthrough():
    r = LiminalRehearsal(_FakeRouter(), real_dispatch=None, tools=_TOOLS)
    mc = await r.rehearse_options("读取文件", candidates=1)
    assert len(mc.candidates) == 1 and mc.selected is not None


@pytest.mark.asyncio
async def test_rehearse_options_multi_generates_and_selects():
    r = LiminalRehearsal(_FakeRouter(n_approaches=3), real_dispatch=None, tools=_TOOLS)
    mc = await r.rehearse_options("读取文件并处理", candidates=3)
    assert len(mc.candidates) == 3, "应生成并模拟 3 个候选"
    assert mc.selected is not None, "应选出一个决策"
    kw = mc.simulation_summary_kwargs(is_active=False)
    assert len(kw["candidate_paths"]) == 3


_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "node__fs__read_file",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        },
    },
]
