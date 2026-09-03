"""跨仓改动必须能在单个 PR 里验证。

`android-v2-contract-compatibility` 这道门要同时检出本仓与安卓仓。它此前取的是安卓仓
的**默认分支**，于是任何"两边一起改"的契约改动都不可能在单个 PR 里变绿：本仓这一侧
改了、安卓那一侧还在分支上，门就红，只能先合安卓再回来重跑。

`test_grounding_rule_is_one_rule` 正是最容易撞上这条的用例——它直接读安卓仓的
`GroundingArbiter.kt` 比对阈值与来源标签。这道门越有用，被这堵墙挡住的次数就越多。

这里钉住修法本身：PR 找同名分支、其余一律默认分支。两条缺一不可——
只有前半句，主干就不再对着主干验证，"main 是绿的"这句话会失去意义。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
JOB = "android-v2-contract-compatibility"


@pytest.fixture(scope="module")
def job() -> dict:
    assert WORKFLOW.is_file(), f"工作流不在预期位置: {WORKFLOW} —— 这本身就是漂移"
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert JOB in data["jobs"], f"{JOB} 这道门不见了"
    return data["jobs"][JOB]


@pytest.fixture(scope="module")
def resolve_step(job: dict) -> dict:
    steps = [s for s in job["steps"] if s.get("id") == "sibling"]
    assert steps, "没有解析兄弟仓 ref 的步骤 —— 说明又被硬钉回去了"
    return steps[0]


@pytest.fixture(scope="module")
def checkout_step(job: dict) -> dict:
    for s in job["steps"]:
        with_ = s.get("with") or {}
        if "repository" in with_ and "android_repo" in str(with_.get("path", "")):
            return s
    raise AssertionError("找不到检出安卓仓的步骤")


def test_the_sibling_checkout_is_not_hard_pinned(checkout_step: dict):
    """写死 ref: main（或干脆不写、取默认分支）就是这堵墙本身。"""
    ref = str((checkout_step.get("with") or {}).get("ref", ""))
    assert ref, "没有 ref —— 会取兄弟仓默认分支，等于硬钉 main"
    assert "steps.sibling.outputs.ref" in ref, f"ref 不是解析出来的，而是写死的: {ref!r}"


def test_the_default_branch_is_always_validated_against_the_default_branch(resolve_step: dict):
    """需要守住的不变式只有一条：main 必须对着 main 验证。

    边界刻意划在「是不是 main」，不是「是不是 PR」。本仓 push 与 pull_request 都触发
    CI；若 push 那一遍恒用默认分支，跨仓改动就永远有一条注定红的运行 —— 墙没拆掉，
    只是挪了个位置。手表仓正是这样红了一轮才发现的。
    """
    run = resolve_step["run"]
    assert (
        '[ "$BRANCH" != "$DEFAULT_REF" ]' in run
    ), "没有『分支名等于默认分支就不去找同名分支』这一条 —— main 可能被拿去对着别的 ref 验证"


def test_branch_name_is_taken_correctly_for_both_event_kinds(resolve_step: dict):
    """PR 上必须取 head_ref：``github.ref_name`` 在 PR 事件里是 ``123/merge``，不是分支名。"""
    branch = str((resolve_step.get("env") or {}).get("BRANCH", ""))
    assert "pull_request" in branch and "head_ref" in branch, f"PR 上没取 head_ref: {branch!r}"
    assert (
        "github.ref_name" in branch
    ), f"非 PR 事件没有回落到 ref_name: {branch!r} —— 推特性分支那一遍会恒用默认分支，必然红"


def test_it_falls_back_instead_of_failing(resolve_step: dict):
    """探测失败（网络/权限/分支不存在）必须回落默认分支，而不是把整条门弄红。"""
    run = resolve_step["run"]
    assert "DEFAULT_REF=main" in run
    assert 'REF="$DEFAULT_REF"' in run, "没有先置默认值 —— 探测失败会留下未定义的 REF"
    assert ">/dev/null 2>&1" in run, "ls-remote 的失败没有被吞掉，会触发 set -e"


def test_the_token_never_reaches_the_log(resolve_step: dict):
    """带 token 的 URL 不能被回显，脚本也不能开 -x。"""
    run = resolve_step["run"]
    assert "set -euo pipefail" in run
    assert "set -x" not in run
    for line in run.splitlines():
        stripped = line.strip()
        if stripped.startswith("echo") and "x-access-token" in stripped:
            raise AssertionError(f"把带 token 的 URL 回显进日志了: {stripped}")


def test_a_non_default_ref_is_announced_loudly(resolve_step: dict):
    """用了兄弟仓分支时，合并顺序必须写进作业摘要。

    这条绿只证明「两个分支放在一起是好的」，不证明合进 main 之后也好。顺序反了，
    main 会在合并那一刻变红 —— 那时候没有任何东西提示过为什么。
    """
    run = resolve_step["run"]
    assert "GITHUB_STEP_SUMMARY" in run, "没有写作业摘要"
    assert "合并顺序" in run, "摘要里没有说明合并顺序 —— 这正是这条绿唯一的风险"


def test_the_grounding_drift_gate_still_runs_in_this_job(job: dict):
    """这道门被解锁之后，最该受益的那个用例必须还挂在上面。"""
    body = yaml.dump(job, allow_unicode=True)
    assert "test_grounding_rule_is_one_rule.py" in body
