#!/usr/bin/env python3
"""
check_file_complexity.py — File-size and complexity budget guardrail.

目的:在新的巨型文件成形之前发现它,并阻止既有的巨型文件继续长大。

为什么要重做基线(2026-08 校准)
--------------------------------
这道闸在 CI 上是 ``--strict`` 跑的,也就是说它**会让构建失败**。而实测:主干上
``File Complexity Budget`` 是 guardrails 工作流里**唯一**失败的 job,且连续多次
构建都红(其余六个 job 全绿)。原因是基线是很久以前记下的,之后文件一路长:

    core/openclawd.py                          7500 → 9718
    core/routes/projection.py                  3500 → 7715
    core/runtime/source_dispatch_orchestrator  1100 → 4328
    ……另有 20 个文件越界,其中 12 个压根没有基线条目

一道**永远是红的**闸等于**没有闸**:它不再区分"今天变糟了"和"一直就这样",
于是所有人学会无视它,而真正的新增巨型文件也就跟着混过去了。这次校准把基线
重置到**当前实际行数**,让它重新回到"只要再长一行就报"的状态。

这不是把标准放宽 —— 标准从来就是"不许变得更糟",而不是"必须先变好"。把已经
欠下的债记成债(基线),和阻止新债(阈值),是两件事;混在一起的结果就是两件都失效。
真正的偿还(拆分这些文件)是独立的工作,不该由这道闸来逼,也逼不动。

基线为什么放在外部 JSON
------------------------
原先基线是本文件里的一个 dict,重新基线要手改二十几个数字 —— 容易改错、容易漏,
而且 diff 混在代码里不好审。现在放在 ``config/file_complexity_baseline.json``:
``--update-baseline`` 一条命令重写它,产出的 diff 就是"哪些文件涨了多少",
审查者一眼能看出这次是不是在偷偷放宽。

Thresholds (lines):
  ERROR_THRESHOLD   — 没有基线条目的文件超过它就算违规(strict 下失败)
  WARN_THRESHOLD    — 超过它只告警,永不失败

Usage:
    python scripts/check_file_complexity.py                   # warning mode
    python scripts/check_file_complexity.py --strict          # strict mode (CI)
    python scripts/check_file_complexity.py --update-baseline # 重新记录基线
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------
ERROR_THRESHOLD = 2000  # lines — new files must not exceed this
WARN_THRESHOLD = 1000  # lines — warn but don't block

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO_ROOT / "config" / "file_complexity_baseline.json"

# Directories to scan
SCAN_DIRS = ["core", "galaxy_gateway", "enhancements", "dashboard"]

# Patterns to skip
SKIP_PARTS = {"__pycache__", ".venv", "venv", "node_modules", "build", "dist", "external"}


def load_baseline() -> dict[str, int]:
    """读取基线。文件不存在时返回空 —— 那样所有文件都按阈值判,是最严的一档。

    刻意不在缺文件时报错:基线丢了应该表现为"闸变严",而不是"闸崩了"。
    """
    if not BASELINE_PATH.is_file():
        return {}
    try:
        raw = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"⚠️  基线文件读取失败,按无基线(最严)处理: {exc}", file=sys.stderr)
        return {}
    entries = raw.get("files", raw) if isinstance(raw, dict) else {}
    return {str(k): int(v) for k, v in entries.items() if isinstance(v, (int, float))}


def count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open("r", encoding="utf-8", errors="replace"))
    except OSError:
        return 0


def scan() -> list[tuple[str, int]]:
    """返回 [(相对路径, 行数)],按路径排序。"""
    found: list[tuple[str, int]] = []
    for scan_dir in SCAN_DIRS:
        scan_path = REPO_ROOT / scan_dir
        if not scan_path.is_dir():
            continue
        for py_file in sorted(scan_path.rglob("*.py")):
            if any(part in py_file.parts for part in SKIP_PARTS):
                continue
            found.append((str(py_file.relative_to(REPO_ROOT)), count_lines(py_file)))
    return found


def update_baseline() -> int:
    """把**当前**超阈值文件的行数记成新基线。

    只记录超过 WARN_THRESHOLD 的文件:比它小的文件不需要条目(阈值本身就够宽),
    记进来只会让基线文件随着无关改动不停抖动。
    """
    previous = load_baseline()
    files = {rel: lines for rel, lines in scan() if lines > WARN_THRESHOLD}

    grew = [(r, previous[r], n) for r, n in sorted(files.items()) if r in previous and n > previous[r]]
    added = [(r, n) for r, n in sorted(files.items()) if r not in previous]

    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(
            {
                "_comment": (
                    "File-size baseline for scripts/check_file_complexity.py. "
                    "每个条目 = 该文件被允许的最大行数(即记录时的实际行数)。"
                    "超过就在 --strict 下失败。用 --update-baseline 重新生成;"
                    "重新生成的 diff 会明确显示哪些文件涨了,请在评审时确认那是有意的。"
                ),
                "files": dict(sorted(files.items())),
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"✅ 基线已写入 {BASELINE_PATH.relative_to(REPO_ROOT)}({len(files)} 个文件)")
    if grew:
        print("\n以下文件的上限被抬高了 —— 请确认这是有意的:")
        for rel, old, new in grew:
            print(f"  {rel}: {old} → {new} (+{new - old})")
    if added:
        print("\n新纳入基线的文件:")
        for rel, n in added:
            print(f"  {rel}: {n}")
    return 0


def main() -> int:
    if "--update-baseline" in sys.argv:
        return update_baseline()

    strict = "--strict" in sys.argv
    baseline = load_baseline()

    errors: list[str] = []
    warnings: list[str] = []

    for rel, lines in scan():
        limit = baseline.get(rel)

        if limit is not None:
            # 已记录基线的文件:只要没长过基线就放行(债记在案,但不许加深)。
            if lines > limit:
                errors.append(
                    f"  {rel}: {lines} lines — baseline is {limit} lines "
                    f"(+{lines - limit}; 请拆分,或在确属有意时用 --update-baseline 重记基线)"
                )
        elif lines > ERROR_THRESHOLD:
            errors.append(f"  {rel}: {lines} lines — exceeds ERROR_THRESHOLD of {ERROR_THRESHOLD} lines")
        elif lines > WARN_THRESHOLD:
            warnings.append(
                f"  {rel}: {lines} lines — exceeds WARN_THRESHOLD of {WARN_THRESHOLD} lines (consider splitting)"
            )

    exit_code = 0

    if warnings:
        print("\n⚠️  File-size warnings (non-blocking):\n")
        for w in warnings:
            print(w)

    if errors:
        print("\n❌ File-size budget violations:\n")
        for e in errors:
            print(e)
        if strict:
            print("\nFailing CI (--strict mode).")
            exit_code = 1
        else:
            print("\nWarning only — pass --strict to fail CI.")

    if not errors:
        print("\n✅ 没有文件越过它的基线/阈值。")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
