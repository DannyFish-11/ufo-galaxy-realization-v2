"""tests/test_data_rsi.py — 轨迹 → 用例（Data-RSI）与能力结论保鲜（R9）。

这个文件同时是 Data-RSI 补丁的验证器：补丁改的是 ``config/eval_cases/trajectories.jsonl``，
验证阶梯按文件名把本文件选进来，「用例集每一行都是合法、id 唯一的 EvalCase」那一条就是判据。
"""

from __future__ import annotations

import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.engineering_verification import VerificationObservation
from core.eval.cases import TRAJECTORY_CASES, EvalCase, builtin_cases, default_cases
from core.meta.kernel import SignalBundle, freshness_violation, run_cycle
from core.meta.operators.data_rsi import CASES_REL, DataRSIOperator, cases_from_traces
from core.meta.store import ArtifactStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def _summary(task, success, *, task_type="query", strategy="single", ts=None, result="任意文字"):
    return SimpleNamespace(
        summary_id=f"s{abs(hash((task, success, ts))) % 10**8}",
        task=task,
        success=success,
        strategy=strategy,
        task_type=task_type,
        timestamp=ts if ts is not None else time.time(),
        result_summary=result,
    )


def _obs(exit_code=0):
    return VerificationObservation(
        command=(sys.executable, "-m", "pytest"),
        requested="pytest",
        recognized_verifier=True,
        executed=True,
        exit_code=exit_code,
        timed_out=False,
        duration_s=0.01,
        evidence_ref="context_archive:data#1",
    )


class _Verifier:
    def run(self, proposal, workspace):
        return [_obs(0)]


def _sandbox(tmp_path):
    @contextmanager
    def factory():
        target = tmp_path / "sandbox"
        target.mkdir(exist_ok=True)

        class _S:
            path = target

        yield _S()

    return factory


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(tmp_path / "store")


def _traces(store, summaries, root):
    return DataRSIOperator(root=root, summaries=summaries).collect(store).traces


# ---------------------------------------------------------------------------
# 验证器：仓库里的轨迹用例集必须合法（trajectories.jsonl）
# ---------------------------------------------------------------------------


def test_trajectory_case_files_are_valid_eval_cases():
    ids = set()
    for path in sorted((REPO_ROOT / "config" / "eval_cases").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case = EvalCase.from_dict(json.loads(line))
            assert case.prompt.strip(), f"{path.name}: 空 prompt"
            assert case.expect_success in (True, False), f"{path.name}: 轨迹用例必须声明期望成败"
            assert case.id not in ids, f"{path.name}: 重复 id {case.id}"
            ids.add(case.id)


# ---------------------------------------------------------------------------
# 轨迹 → 用例：确定性、只读类型化字段
# ---------------------------------------------------------------------------


def test_consistent_success_becomes_a_regression_case(store, tmp_path):
    traces = _traces(store, [_summary("打开记事本", True), _summary("打开记事本", True)], tmp_path)
    [case] = cases_from_traces(traces).values()
    assert case["expect_success"] is True and "capability" in case["tags"] and "query" in case["tags"]
    assert case["provenance"]["observations"] == 2 and len(case["provenance"]["traces"]) == 2


def test_consistent_failure_becomes_a_boundary_case(store, tmp_path):
    traces = _traces(store, [_summary("订机票", False, ts=1), _summary("订机票", False, ts=2)], tmp_path)
    [case] = cases_from_traces(traces).values()
    assert case["expect_success"] is False and "boundary" in case["tags"]


@pytest.mark.parametrize(
    "summaries",
    [
        [_summary("查天气", True)],  # 只观测到一次
        [_summary("查天气", True, ts=1), _summary("查天气", False, ts=2)],  # 有成有败
    ],
)
def test_thin_or_unstable_evidence_produces_no_case(store, tmp_path, summaries):
    assert cases_from_traces(_traces(store, summaries, tmp_path)) == {}


def test_result_text_is_never_read(store, tmp_path):
    """只读类型化字段：结果文字怎么写都不影响用例（对象锚定，不从散文里抠结构）。"""
    a = cases_from_traces(_traces(store, [_summary("列目录", True, ts=1, result="成功!!!")] * 2, tmp_path))
    b = cases_from_traces(_traces(store, [_summary("列目录", True, ts=1, result="failed 失败")] * 2, tmp_path))
    assert a == b
    trace = _traces(store, [_summary("列目录", True, ts=1, result="x")], tmp_path)[0]
    assert "result_summary" not in trace.payload


def test_whitespace_variants_are_the_same_task(store, tmp_path):
    traces = _traces(store, [_summary("打开  记事本", True, ts=1), _summary(" 打开 记事本 ", True, ts=2)], tmp_path)
    assert len(cases_from_traces(traces)) == 1


def test_traces_carry_the_time_the_task_happened(store, tmp_path):
    [trace] = _traces(store, [_summary("x", True, ts=0)], tmp_path)
    assert trace.created_at.startswith("1970-01-01"), "M→D 新鲜度比的是任务发生时刻"
    assert trace.lineage.operator == "runtime"


def test_model_commit_makes_older_traces_stale(store, tmp_path):
    traces = _traces(store, [_summary("x", True, ts=0), _summary("x", True, ts=1)], tmp_path)
    store.record_commit("model", "patch:m", "verdict:m", "2000-01-01T00:00:00+00:00")
    assert "M→D" in freshness_violation("data", SignalBundle(traces=traces), store)


# ---------------------------------------------------------------------------
# 端到端：提案 → 验证 → 裁决 → 生效
# ---------------------------------------------------------------------------


def _cycle(tmp_path, store, summaries, stale_claims=None, mode="on"):
    live = tmp_path / "live"
    live.mkdir(exist_ok=True)
    op = DataRSIOperator(root=live, summaries=summaries)
    return live, run_cycle(
        op,
        op.collect(store),
        store=store,
        verifier=_Verifier(),
        mode=mode,
        sandbox_factory=_sandbox(tmp_path),
        live_root=live,
        stale_claims=stale_claims,
    )


def test_cases_are_committed_and_not_reproposed(tmp_path, store):
    summaries = [_summary("打开记事本", True, ts=1), _summary("打开记事本", True, ts=2)]
    live, report = _cycle(tmp_path, store, summaries)
    [outcome] = report.outcomes
    assert outcome.outcome == "committed"
    [line] = (live / CASES_REL).read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["prompt"] == "打开记事本"
    _, again = _cycle(tmp_path, store, summaries)
    assert again.outcomes == [], "同样的轨迹不该再提一遍"


def test_a_moved_capability_boundary_updates_the_case(tmp_path, store):
    _cycle(tmp_path, store, [_summary("订机票", False, ts=1), _summary("订机票", False, ts=2)])
    live, report = _cycle(tmp_path, store, [_summary("订机票", True, ts=3), _summary("订机票", True, ts=4)])
    [outcome] = report.outcomes
    assert outcome.outcome == "committed"
    patch = store.get(outcome.patch_id)
    assert "能力边界移动 1" in patch.payload["rationale"]
    [line] = (live / CASES_REL).read_text(encoding="utf-8").splitlines()
    assert json.loads(line)["expect_success"] is True


def test_operator_cannot_write_the_scorer(tmp_path, store):
    from core.meta.kernel import write_surface_violation

    assert "G6" in write_surface_violation("data", ["core/eval/scorer.py"])
    assert write_surface_violation("data", [CASES_REL]) == ""


# ---------------------------------------------------------------------------
# R9：生效之后，因此失效的旧结论要自己报出来
# ---------------------------------------------------------------------------


def test_commit_reports_newly_stale_claims(tmp_path, store):
    answers = iter([["already-stale"], ["already-stale", "capability-matrix-says-cannot-book-flights"]])
    summaries = [_summary("订机票", True, ts=1), _summary("订机票", True, ts=2)]
    _, report = _cycle(tmp_path, store, summaries, stale_claims=lambda: next(answers))
    [outcome] = report.outcomes
    assert "capability-matrix-says-cannot-book-flights" in outcome.reason
    assert "already-stale" not in outcome.reason, "生效前就过期的不算这次造成的"
    lesson = store.get(outcome.lesson_id)
    assert lesson.payload["stale_claims"] == ["capability-matrix-says-cannot-book-flights"]


def test_default_stale_check_reads_the_real_claims_file():
    from core.assessment_freshness import freshness_report
    from core.meta.kernel import _stale_claims

    report = freshness_report()
    assert report["claims_loaded"] > 0
    assert _stale_claims() == report["stale"]


# ---------------------------------------------------------------------------
# 生成的用例真的会被跑到
# ---------------------------------------------------------------------------


def test_default_cases_include_trajectory_cases(tmp_path, monkeypatch):
    import core.eval.cases as cases_mod

    target = tmp_path / "trajectories.jsonl"
    monkeypatch.setattr(cases_mod, "TRAJECTORY_CASES", target)
    assert [c.id for c in cases_mod.default_cases()] == [c.id for c in builtin_cases()], "没有文件时与内置逐个相同"
    target.write_text(json.dumps({"id": "traj_x", "prompt": "p", "expect_success": True}) + "\n", encoding="utf-8")
    assert [c.id for c in cases_mod.default_cases()][-1] == "traj_x"


def test_eval_script_uses_default_cases():
    source = (REPO_ROOT / "scripts" / "run_agent_eval.py").read_text(encoding="utf-8")
    assert "load_cases(args.cases) if args.cases else default_cases()" in source
    assert TRAJECTORY_CASES.as_posix().endswith(CASES_REL)
    assert isinstance(default_cases(), list)


def test_data_operator_is_registered():
    from core.meta.operators import build_operator

    op = build_operator("data_rsi")
    assert (op.name, op.scope) == ("data_rsi", "data")
