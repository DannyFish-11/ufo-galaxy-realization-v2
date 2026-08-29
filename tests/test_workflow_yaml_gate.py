"""这道工作流门真的拦得住吗 —— 用它当初没拦住的那个 bug 来验它。

背景在 ``scripts/check_workflow_yaml.py`` 的模块头里:
``dual_repo_reality_audit.yml`` 同一步里有两个 ``env:``,PyYAML 放行、
Actions 拒收,于是那个工作流一个月里每次推送都 startup_failure,一个 job 都没起过。

这份测试要钉住的不是"脚本能跑",是**它对当初那份文件会报红**。
一道自己没被验过会不会红的门,和这次事故是同一个毛病。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_workflow_yaml.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_workflow_yaml", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


# ──────────────────────────────────────────────────────────────────────────
# 一、当初那个 bug
# ──────────────────────────────────────────────────────────────────────────

#: 事故现场的最小复现:一个 step,两个 env: —— 前后各一个。
THE_BUG = """
name: Example
on:
  push:
    branches: [main]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Validate
        env:
          A: "1"
        run: |
          echo hi
        env:
          PYTHONPATH: /x
"""


def test_pyyaml_safe_load_swallows_it():
    """先钉住**为什么没人发现** —— safe_load 对重复键是「后者覆盖前者」,不报错。

    这一条不是在测我们的代码,是在钉住那个前提:任何用 safe_load 的本地校验
    都会放行这份文件。前提哪天变了(PyYAML 改成报错),这条会红,那时可以撤掉
    这道门的一半理由。
    """
    doc = yaml.safe_load(THE_BUG)
    step = doc["jobs"]["check"]["steps"][0]
    assert step["env"] == {"PYTHONPATH": "/x"}, "前一个 env 被无声吃掉了"
    assert "A" not in step["env"]


def test_strict_loader_rejects_it():
    """而这道门用的 loader 会报错,并且指到那一行。"""
    with pytest.raises(mod._DuplicateKeyError) as exc:
        yaml.load(THE_BUG, Loader=mod.StrictLoader)
    assert "env" in str(exc.value.problem)
    assert exc.value.problem_mark is not None


def test_gate_reports_the_bug_with_a_line_number(tmp_path, monkeypatch):
    """整条路走一遍:落到盘上,让门去查,它必须报红且带行号。"""
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "broken.yml").write_text(THE_BUG, encoding="utf-8")

    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "WORKFLOW_DIR", wf)

    report = mod.check_workflows()
    assert report["files_checked"] == 1
    assert len(report["problems"]) == 1
    problem = report["problems"][0]
    assert "重复键" in problem
    assert "broken.yml:" in problem, "得指到文件和行,否则查起来还得靠猜"


# ──────────────────────────────────────────────────────────────────────────
# 二、其余几条结构判据
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "body,fragment",
    [
        (
            "name: X\njobs:\n  a:\n    runs-on: u\n    steps:\n      - run: echo\n",
            "缺 on:",
        ),
        (
            "name: X\non: push\n",
            "缺 jobs:",
        ),
        (
            "name: X\non: push\njobs:\n  a:\n    runs-on: u\n",
            "既没有 steps: 也没有 uses:",
        ),
        (
            "name: X\non: push\njobs:\n  a:\n    runs-on: u\n    needs: [ghost]\n" "    steps:\n      - run: echo\n",
            "不存在的 job",
        ),
        (
            "name: X\non: push\njobs:\n  a:\n    runs-on: u\n    steps:\n"
            "      - name: both\n        uses: actions/checkout@v4\n        run: echo\n",
            "同时有 run: 和 uses:",
        ),
        (
            "name: X\non: push\njobs:\n  a:\n    runs-on: u\n    steps:\n"
            "      - name: neither\n        with:\n          k: v\n",
            "既没有 run: 也没有 uses:",
        ),
    ],
)
def test_structural_rejections(body, fragment):
    problems = mod._check_structure("f.yml", yaml.safe_load(body))
    assert any(fragment in p for p in problems), f"{fragment!r} 没被报出来: {problems}"


def test_on_parsed_as_boolean_true_still_counts():
    """YAML 1.1 会把裸 ``on`` 解析成布尔 True。不认这一种的话,几乎每个文件都会误报 ——
    而一道天天误报的门三周内一定会被关掉。"""
    doc = yaml.safe_load("name: X\non: push\njobs:\n  a:\n    runs-on: u\n    steps:\n      - run: echo\n")
    assert True in doc and "on" not in doc, "前提:PyYAML 把 on 读成 True"
    assert mod._check_structure("f.yml", doc) == []


# ──────────────────────────────────────────────────────────────────────────
# 三、这道门自己的失效方式
# ──────────────────────────────────────────────────────────────────────────


def test_zero_files_is_not_green(tmp_path, monkeypatch):
    """一个文件都没查到时**不能**报绿 —— 与判据保鲜门同一条规矩。"""
    empty = tmp_path / ".github" / "workflows"
    empty.mkdir(parents=True)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "WORKFLOW_DIR", empty)

    report = mod.check_workflows()
    assert report["files_checked"] == 0
    monkeypatch.setattr("sys.argv", ["check_workflow_yaml.py"])
    assert mod.main() == 2, "查了 0 个文件却退 0,就是这次事故的翻版"


def test_gate_declares_what_it_does_not_cover():
    """绿灯必须自带边界。声明为空,就等于在暗示「全都验过了」。"""
    report = mod.check_workflows()
    assert report["not_covered"], "不能声称覆盖一切"
    assert "不等于" in report["green_means"]


# ──────────────────────────────────────────────────────────────────────────
# 四、真仓库
# ──────────────────────────────────────────────────────────────────────────


def test_repo_workflows_are_clean():
    report = mod.check_workflows()
    assert report["files_checked"] > 0
    assert report["problems"] == [], f"仓库里的工作流有问题: {report['problems']}"


def test_the_original_file_no_longer_has_two_env_blocks():
    """具体钉住事故现场那一份 —— 防止将来又被加回去一个 env:。"""
    path = REPO_ROOT / ".github" / "workflows" / "dual_repo_reality_audit.yml"
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=mod.StrictLoader)
    step = [s for s in doc["jobs"]["check-audit"]["steps"] if "Validate audit correctness" in str(s.get("name", ""))]
    assert len(step) == 1
    env = step[0]["env"]
    # 合并之后这四个都得在 —— 只留一个 env 但把 PYTHONPATH 丢了,是另一种修坏。
    for key in (
        "PYTHONPATH",
        "DUAL_RUNTIME_CROSS_REPO_PROTECTED_VERIFICATION",
        "DISPATCH_EVIDENCE_JSON",
        "MANUAL_EVIDENCE_JSON",
    ):
        assert key in env, f"{key} 在合并 env: 时丢了"
