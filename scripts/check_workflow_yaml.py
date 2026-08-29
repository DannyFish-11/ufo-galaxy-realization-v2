#!/usr/bin/env python3
"""工作流门 —— 让 Actions 会拒收、而 PyYAML 会放行的那几类写法当场红。

它是从哪来的
------------
2026-08-29 查 CI 时发现:``.github/workflows/dual_repo_reality_audit.yml``
**从 2026-07-31 起,每一次推送都 startup_failure** —— 0 个 job、0 秒、
run_number 已经到 1772。main 上如此,每条分支上都如此。

原因是同一个 step 里有两个 ``env:``:一个在 ``run:`` 前面(新加的
protected-verification 三个变量),一个在 ``run:`` 后面(原有的 PYTHONPATH)。

**为什么没人发现**:

* ``yaml.safe_load`` 对重复键的处理是「后者覆盖前者」,不报错。
  所以任何本地校验、任何用 PyYAML 的脚本,看到的都是一份合法的工作流。
* Actions 的解析器**拒收整个文件**,连 ``name:`` 都读不出来 ——
  所以它在 UI 里显示成文件路径,而不是 "Dual-Repo System Reality Audit"。
* 它在**每条分支上都是红的**,于是这一条红失去了信号意义:
  谁看都觉得"它一直这样"。

后果是整整一个月:PR-537 的五维现实审计一次没跑过,
``repository_dispatch: android-protected-reality-audit`` 那条跨仓证据通道
也从来没被触发过 —— 一道 blocking 的门,挂在那儿,一次都没执行。

**这正是本仓一直在防的那个缺陷,只是这次长在 CI 上**:看起来接上了,其实没有。

它查什么
--------
只查**能机械查、且 Actions 确实会拒收**的那几类:

1. 重复的映射键(就是上面那个 bug);
2. 一个 step 同时有 ``uses:`` 和 ``run:``,或者两个都没有;
3. 一个 job 既没有 ``steps:`` 也没有 ``uses:``;
4. 顶层缺 ``on:``;
5. ``needs:`` 指向同文件里不存在的 job。

它**不**查什么 —— 这条要紧
--------------------------
它不是 Actions 的完整 schema 校验器,也做不成一个:
表达式语法、action 的 ``with:`` 参数是否正确、runner 标签存不存在、
可复用工作流的入参 —— 这些它一概不看。

**所以它绿不等于工作流一定能起来。** 把它说成"工作流校验通过"就是过度声明,
而过度声明的门比没有门更危险:那正是这次事故本身的形状。

用法
----
::

    python3 scripts/check_workflow_yaml.py            # 有问题即非零退出
    python3 scripts/check_workflow_yaml.py --json     # 机器可读
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

#: 这道门声明它**没有**覆盖的东西。写在代码里,是为了防止下一个人把
#: "这道门绿了" 读成 "这个工作流一定能起来"。
NOT_COVERED: Tuple[str, ...] = (
    "${{ }} 表达式的语法与上下文可用性",
    "action 的 with: 入参是否齐备/拼对",
    "runs-on 的 runner 标签存不存在",
    "可复用工作流(uses: ./.github/workflows/x.yml)的入参匹配",
    "权限/环境/密钥在组织策略下是否真的可用",
)


class _DuplicateKeyError(yaml.constructor.ConstructorError):
    pass


class StrictLoader(yaml.SafeLoader):
    """和 SafeLoader 一样,但**重复键报错** —— Actions 就是这么做的。"""


def _no_duplicate_keys(loader: StrictLoader, node: yaml.MappingNode, deep: bool = False) -> Dict[Any, Any]:
    mapping: Dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise _DuplicateKeyError(
                None,
                None,
                f"重复键 {key!r} —— PyYAML 会「后者覆盖前者」,Actions 会拒收整个文件",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys)


def _iter_workflow_files() -> List[Path]:
    if not WORKFLOW_DIR.is_dir():
        return []
    return sorted(p for p in WORKFLOW_DIR.iterdir() if p.suffix in (".yml", ".yaml"))


def _check_structure(rel: str, doc: Any) -> List[str]:
    """结构层面的几条。只报 Actions 确实会拒的。"""
    problems: List[str] = []
    if not isinstance(doc, dict):
        return [f"{rel}: 顶层不是映射"]

    # ``on:`` 会被 YAML 1.1 解析成布尔 True —— 两种都算数。
    if "on" not in doc and True not in doc:
        problems.append(f"{rel}: 顶层缺 on:(工作流没有触发条件)")

    jobs = doc.get("jobs")
    if not isinstance(jobs, dict) or not jobs:
        problems.append(f"{rel}: 顶层缺 jobs:(或为空)")
        return problems

    job_ids = set(jobs)
    for job_id, job in jobs.items():
        where = f"{rel}::{job_id}"
        if not isinstance(job, dict):
            problems.append(f"{where}: job 不是映射")
            continue

        has_steps = isinstance(job.get("steps"), list) and bool(job.get("steps"))
        has_uses = bool(job.get("uses"))
        if not has_steps and not has_uses:
            problems.append(f"{where}: 既没有 steps: 也没有 uses:")

        for dep in _as_list(job.get("needs")):
            if dep not in job_ids:
                problems.append(f"{where}: needs: 指向不存在的 job {dep!r}")

        for idx, step in enumerate(job.get("steps") or []):
            if not isinstance(step, dict):
                problems.append(f"{where}: 第 {idx} 步不是映射")
                continue
            name = step.get("name") or step.get("uses") or f"#{idx}"
            step_has_run = "run" in step
            step_has_uses = "uses" in step
            if step_has_run and step_has_uses:
                problems.append(f"{where} 步骤「{name}」: 同时有 run: 和 uses:")
            elif not step_has_run and not step_has_uses:
                problems.append(f"{where} 步骤「{name}」: 既没有 run: 也没有 uses:")

    return problems


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


def check_workflows() -> Dict[str, Any]:
    """复验全部工作流文件。"""
    files = _iter_workflow_files()
    problems: List[str] = []

    for path in files:
        rel = str(path.relative_to(REPO_ROOT))
        try:
            doc = yaml.load(path.read_text(encoding="utf-8"), Loader=StrictLoader)
        except _DuplicateKeyError as exc:
            mark = exc.problem_mark
            line = mark.line + 1 if mark else "?"
            problems.append(f"{rel}:{line}: {exc.problem}")
            continue
        except Exception as exc:  # noqa: BLE001 — 任何解析失败都是这道门要报的
            problems.append(f"{rel}: 解析失败 — {exc}")
            continue
        problems.extend(_check_structure(rel, doc))

    return {
        # 0 个文件与"全都干净"是两回事 —— 见 main() 的退出码。
        "files_checked": len(files),
        "problems": problems,
        "not_covered": list(NOT_COVERED),
        "green_means": (
            "这几类机械可查的写法没问题。**不等于**工作流一定能在 Actions 上起来 ——"
            "见 not_covered。"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    report = check_workflows()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f".github/workflows 校验 —— 文件数 {report['files_checked']}")
        print()
        if report["files_checked"] == 0:
            print("⚠️  一个工作流文件都没找到 —— 这不是「全都干净」,是这道门什么都没查。")
        elif report["problems"]:
            print(f"❌ {len(report['problems'])} 处:")
            for p in report["problems"]:
                print(f"   · {p}")
            print()
            print("重复键这一类要特别说一句:PyYAML 的 safe_load 会「后者覆盖前者」,")
            print("所以本地任何用 PyYAML 的校验都会放行;而 Actions 拒收整个文件,")
            print("表现是每次推送一个 startup_failure —— 0 job、0 秒、连 name 都读不出来。")
        else:
            print("✅ 机械可查的那几类都没问题。")
            print()
            print("这道门**不**覆盖:")
            for item in report["not_covered"]:
                print(f"   · {item}")
            print("所以它绿不等于工作流一定能起来。")

    if report["files_checked"] == 0:
        # 什么都没查却报绿,是这类门最坏的失效方式 —— 与保鲜门同一条规矩。
        return 2
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
