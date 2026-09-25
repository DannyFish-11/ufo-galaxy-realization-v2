#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/replay_verification_ladder.py — 用故障注入量 L0 漏选了多少。

判据
====
L0 的承诺是「不漏任何会红的用例」。这件事不能靠读代码相信，要量：

1. 选一个模块 M，算出 L0(M)；
2. 在 M 末尾注入一行 ``raise RuntimeError("LADDER_REPLAY_FAULT:M")`` —— 此后任何
   导入 M 的地方（收集期或运行期、模块级或懒导入）都会带着这个标记失败；
3. 跑 L0 **没选中**的那部分测试（补集）；
4. 补集里凡是带着这个标记失败的测试，就是一次漏选。

补集接近全量，所以按 ``scripts/ci_test_shard.py`` 同一套 crc32 切成 ``--jobs`` 份并行跑。
只数**带标记**的失败：补集里本来就红的（缺依赖之类环境问题）与本次改动无关。

注入会改工作区里的源文件，``finally`` 里无条件还原；另外脚本拒绝在该文件有未提交改动
时运行，以免还原时覆盖掉别人的工作。**请在独立的 git worktree 里跑。**

用法
====
    python scripts/replay_verification_ladder.py --module core/self_improvement.py
    python scripts/replay_verification_ladder.py --module core/a.py --module core/b.py --mode collect
    python scripts/replay_verification_ladder.py --module core/a.py --json /tmp/report.json

``--mode collect`` 只做收集（快，只能验证模块级依赖）；``--mode run`` 真跑（慢，能验证
懒导入）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import zlib
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.verification_ladder import (  # noqa: E402 — path bootstrap must precede import
    CI_MARKER_EXPRESSION,
    build_dependency_index,
    select_affected_tests,
)

MARKER = "LADDER_REPLAY_FAULT"


def _dirty(rel: str) -> bool:
    proc = subprocess.run(
        ["git", "status", "--porcelain", "--", rel],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return bool(proc.stdout.strip())


def _split(files: List[str], jobs: int) -> List[List[str]]:
    buckets: List[List[str]] = [[] for _ in range(jobs)]
    for f in files:
        buckets[zlib.crc32(f.encode("utf-8")) % jobs].append(f)
    return [b for b in buckets if b]


def _run_bucket(files: List[str], mode: str, timeout_s: float) -> subprocess.Popen:
    argv = [sys.executable, "-m", "pytest", *files, "-q", "-p", "no:cacheprovider", "-rfE", "--tb=line"]
    argv += ["--co"] if mode == "collect" else ["-m", CI_MARKER_EXPRESSION]
    return subprocess.Popen(
        argv,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _missed_tests(output: str, complement: List[str]) -> List[str]:
    hits = set()
    for line in output.splitlines():
        if MARKER not in line:
            continue
        for test in complement:
            if test in line:
                hits.add(test)
    return sorted(hits)


def replay(module: str, mode: str, jobs: int, timeout_s: float) -> Dict[str, object]:
    path = REPO_ROOT / module
    if not path.is_file():
        raise SystemExit(f"模块不存在：{module}")
    if _dirty(module):
        raise SystemExit(f"{module} 有未提交的改动 —— 注入后还原会覆盖它，拒绝运行")

    index = build_dependency_index()
    plan = select_affected_tests([module], index)
    complement = [t for t in index.test_files if t not in set(plan.tests)]

    original = path.read_text(encoding="utf-8")
    started = time.monotonic()
    outputs: List[str] = []
    try:
        path.write_text(original + f'\n\nraise RuntimeError("{MARKER}:{module}")\n', encoding="utf-8")
        procs = [_run_bucket(bucket, mode, timeout_s) for bucket in _split(complement, jobs)]
        for proc in procs:
            try:
                out, _ = proc.communicate(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, _ = proc.communicate()
                out = (out or "") + "\n[replay] 这一份超时被终止\n"
            outputs.append(out or "")
    finally:
        path.write_text(original, encoding="utf-8")

    joined = "\n".join(outputs)
    missed = _missed_tests(joined, complement)
    return {
        "module": module,
        "mode": mode,
        "l0_size": len(plan.tests),
        "complement_size": len(complement),
        "missed": missed,
        "marker_lines": [line for line in joined.splitlines() if MARKER in line][:50],
        "duration_s": round(time.monotonic() - started, 1),
        "summaries": [o.strip().splitlines()[-1] if o.strip() else "" for o in outputs],
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--module", action="append", required=True, help="要注入故障的模块（可重复）")
    parser.add_argument("--mode", choices=("run", "collect"), default="run")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=3600.0, help="每份的超时（秒）")
    parser.add_argument("--json", help="把报告写到这个文件")
    args = parser.parse_args(argv)

    reports = [replay(m, args.mode, max(1, args.jobs), args.timeout) for m in args.module]
    for r in reports:
        verdict = "✅ 无漏选" if not r["missed"] else f"❌ 漏选 {len(r['missed'])} 个"
        print(
            f"{verdict}  {r['module']}  L0={r['l0_size']}  补集={r['complement_size']}  "
            f"模式={r['mode']}  耗时={r['duration_s']}s"
        )
        for t in r["missed"]:
            print(f"    漏选：{t}")
    if args.json:
        Path(args.json).write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if any(r["missed"] for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
